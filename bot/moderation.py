"""Her chat mesajına kuralları uygular: yasaklı kelime, caps, etiket."""
import threading, time

from . import CFG, db, kick, llm, rules


def blacklist(targeted=False):
    """targeted=False: her zaman yasak kelimeler. True: yalnızca birine yöneltilmişse yasak olanlar."""
    return rules.load_blacklist(("*" if w["anywhere"] else "") + w["word"]
                                for w in CFG["blacklist"]["words"] if w["targeted"] == targeted)


_last = {}  # komut -> son cevaplanma zamanı


def command(text, name):
    """Mesajın herhangi bir yerinde bir komut geçiyorsa (ör. !abone) yazanı etiketleyerek cevabını chate yazar."""
    c, words = CFG["commands"], text.lower().split()
    for item in c["items"]:
        trigger = item["trigger"].lower()
        if trigger in words:
            if time.time() - _last.get(trigger, 0) >= c["cooldown_seconds"]:  # aynı komuta art arda yazılınca chat dolmasın
                _last[trigger] = time.time()
                print(f"[komut] {name}: {trigger}", flush=True)
                kick.send(f"@{name} {item['response']}")
            return True
    return False


def from_websocket(m, broadcaster_id):
    """Websocket mesajını handle()'ın beklediği biçime çevirir."""
    s = m["sender"]
    return {"message_id": m["id"], "content": m["content"], "broadcaster": {"user_id": broadcaster_id},
            "sender": {"user_id": s["id"], "username": s["username"], "identity": s.get("identity")}}


def handle(ev):
    sender, text, mid = ev["sender"], ev["content"], ev["message_id"]
    uid, name = sender["user_id"], sender["username"]
    exempt = rules.is_exempt(ev, CFG["exempt_badges"])
    if not db.add_message(mid, uid, name, text, exempt):
        return
    if not exempt:
        me = {"id": mid, "user_id": uid, "username": name, "content": text}
        word = rules.blacklist_hit(text, *blacklist())
        if word:
            count = db.bump(uid, "blacklist")
            action = rules.blacklist_action(count, CFG["blacklist"]["strikes_before_timeout"])
            db.log(uid, name, "blacklist", count, action, word, [me])
            print(f"[yasaklı kelime] {name}: {text!r} -> '{word}' bulundu, ihlal #{count}, karar: {action}", flush=True)
            kick.delete(mid)
            if action == "timeout":
                kick.timeout(uid, CFG["blacklist"]["timeout_minutes"], "Yasaklı kelime")
            elif action == "ban":
                kick.ban(uid, "Yasaklı kelime (tekrar)")
            return
        word = rules.blacklist_hit(text, *blacklist(targeted=True))
        if word:  # kelime tek başına serbest; birine yöneltilmiş mi, model ya da sen karar verirsin
            rows = db.recent(CFG["llm"]["context_messages"])
            if CFG["llm"]["enabled"]:
                print(f"[hedefli kelime] {name}: {text!r} -> '{word}', model yorumluyor...", flush=True)
                threading.Thread(target=llm.targeted, args=(me, word, rows), daemon=True).start()
            else:
                print(f"[hedefli kelime] {name}: {text!r} -> '{word}', incelemeye alındı", flush=True)
                db.log(uid, name, "hedefli", 0, "inceleme", word, rows, "open")
        if rules.is_caps(text, CFG["caps"]["min_letters"]):
            count = db.bump(uid, "caps")
            print(f"[caps] {name}: {text!r} -> ardışık caps #{count}", flush=True)
            if count >= CFG["caps"]["streak"]:
                db.log(uid, name, "caps", count, "timeout", "", db.recent(count, uid))
                db.reset(uid, "caps")
                kick.timeout(uid, CFG["caps"]["timeout_minutes"], "Sürekli büyük harf")
                return
        else:
            db.reset(uid, "caps")
    if command(text, name):
        return
    if CFG["nick"] and rules.mentions(text, CFG["nick"]) and uid != ev["broadcaster"]["user_id"]:
        if CFG["llm"]["enabled"]:
            print(f"[etiket] {name}: {text!r} -> model yorumluyor...", flush=True)
            # Ayrı iş parçacığı: model saniyelerce sürer, bu sırada dinleyici ping'lere cevap verebilmeli.
            threading.Thread(target=llm.review, args=(mid,), daemon=True).start()
        else:  # model kapalıyken etiket, son mesajlarla birlikte panelin inceleme kuyruğuna düşer
            print(f"[etiket] {name}: {text!r} -> incelemeye alındı", flush=True)
            db.log(uid, name, "etiket", 0, "inceleme", "", db.recent(CFG["llm"]["context_messages"]), "open")
