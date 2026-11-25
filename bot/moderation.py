"""Her chat mesajına kuralları uygular: yasaklı kelime, caps, etiket."""
import collections, itertools, threading, time

from . import CFG, db, kick, llm, rules


def blacklist(targeted=False):
    """targeted=False: her zaman yasak kelimeler. True: yalnızca birine yöneltilmişse yasak olanlar."""
    return [w for w in CFG["blacklist"]["words"] if w["targeted"] == targeted]


NOTES = collections.deque(maxlen=50)  # panelin masaüstü bildirimi olarak gösterdiği olaylar
_note_id = itertools.count(1)


def notify(kind, uid, name, text):
    NOTES.append({"id": next(_note_id), "kind": kind, "user_id": uid, "username": name, "text": text[:200]})


_last = {}  # komut -> son cevaplanma zamanı


def command(text, name):
    """Mesaj bir komutla başlıyorsa (ör. !abone nasıl olunur) yazanı etiketleyerek cevabını chate yazar."""
    c, words = CFG["commands"], text.lower().split()
    for item in c["items"]:
        trigger = item["trigger"].lower()
        if words[:1] == [trigger]:
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
            "sender": {"user_id": s["id"], "username": s["username"], "identity": s.get("identity")},
            "reply_to": reply_to(m)}


def reply_to(m):
    """Cevap mesajıysa cevaplanan mesajın {id, user_id, username}'i, değilse None."""
    meta = m.get("metadata") or {}
    msg, who = meta.get("original_message") or {}, meta.get("original_sender") or {}
    return {"id": str(msg["id"]), "user_id": who.get("id"), "username": who.get("username", "")} if msg.get("id") else None


def helper(ev):
    """Geçici moderatör bir mesaja komutla cevap verdiyse işlemi uygular ve kime/kim istedi diye kaydeder. İşlendiyse True."""
    reply, name = ev.get("reply_to"), ev["sender"]["username"]
    h = CFG["helpers"]
    words = ev["content"].lower().split()
    if not reply or name.lower() not in [n.lower() for n in h["nicks"]] or not words:
        return False
    cmd = next((c for c in h["commands"] if c["trigger"].lower() == words[0]), None)
    if not cmd:
        return False
    row = db.message(reply["id"])
    # Korunanlar: yayıncı, muaf rozetliler ve geçici moderatörlerin kendisi.
    if reply["user_id"] == ev["broadcaster"]["user_id"] or (row and row["exempt"]) or reply["username"].lower() in [n.lower() for n in h["nicks"]]:
        print(f"[yardımcı] {name}: {cmd['trigger']} reddedildi, {reply['username']} korumalı", flush=True)
        return True
    do, minutes = cmd["do"], cmd["minutes"] or 5
    print(f"[yardımcı] {name} istedi: {cmd['trigger']} -> {reply['username']} ({do})", flush=True)
    evidence = [row] if row else [{"id": reply["id"], "user_id": reply["user_id"], "username": reply["username"], "content": ""}]
    db.log(reply["user_id"], reply["username"], "yardimci", 0, do, f"{name} istedi: {cmd['trigger']}", evidence)
    kick.delete(reply["id"])
    if do == "timeout":
        kick.timeout(reply["user_id"], minutes, f"{name} istedi")
    elif do == "ban":
        kick.ban(reply["user_id"], f"{name} istedi")
    return True


def mod_event(ev):
    """Başka bir moderatörün (ya da senin Kick arayüzünden) yaptığı silme/timeout/ban olayı.
    Silinen mesaj yasaklı kelime sayacına eklenir; sayaç dolunca bot timeout/ban atar. Timeout ve ban yalnızca kaydedilir."""
    print(f"[mod olayı] {ev}", flush=True)  # shortcut: olay alanları resmî belgeye değil gözleme dayanıyor; Kick değiştirirse buradan anlaşılır
    if ev["_event"] == "deleted":
        mid = str((ev.get("message") or {}).get("id") or "")
        if not mid or ("msg", mid) in kick.MINE:
            return
        row = db.message(mid)
        if row is None or row["exempt"]:  # tanımadığımız mesaj ya da muaf kişi
            return
        uid, name = row["user_id"], row["username"]
        count = db.bump(uid, "blacklist")
        action = rules.blacklist_action(count, CFG["blacklist"]["strikes_before_timeout"])
        db.log(uid, name, "mod", count, action, "mesajı başka bir moderatör sildi", [row])
        print(f"[mod silmesi] {name}: ihlal #{count}, karar: {action}", flush=True)
        if action == "timeout":
            kick.timeout(uid, CFG["blacklist"]["timeout_minutes"], "Moderatör silmeleri")
        elif action == "ban":
            kick.ban(uid, "Moderatör silmeleri")
    elif ev["_event"] == "banned":
        who, by = ev.get("user") or {}, (ev.get("banned_by") or {}).get("username", "?")
        if who.get("id") is None or ("user", who["id"]) in kick.MINE:
            kick.MINE.discard(("user", who.get("id")))
            return
        action = "ban" if ev.get("permanent") else "timeout"
        db.log(who["id"], who.get("username", "?"), "mod", 0, action, f"{by} attı" + ("" if ev.get("permanent") else f" (bitiş: {ev.get('expires_at')})"), [])


def handle(ev):
    sender, text, mid = ev["sender"], ev["content"], ev["message_id"]
    uid, name = sender["user_id"], sender["username"]
    exempt = rules.is_exempt(ev, CFG["exempt_badges"])
    if not db.add_message(mid, uid, name, text, exempt):
        return
    if CFG["nick"] and rules.mentions(text, CFG["nick"]) and name.lower() != CFG["nick"].lower():
        notify("etiket", uid, name, text)
    if helper(ev):
        return
    if not exempt:
        me = {"id": mid, "user_id": uid, "username": name, "content": text}
        hit = rules.blacklist_hit(text, blacklist(), CFG["blacklist"]["allowed"])
        if hit:
            entry, word = hit
            if entry.get("notify"):
                notify(f"yasaklı kelime: {entry['word']}", uid, name, text)
            # "Yalnızca sil" kelimeleri sayaca yazılmaz; diğerleri kullanıcının ihlal sayacını artırır.
            count = 0 if entry["action"] == "delete" else db.bump(uid, "blacklist")
            action = rules.blacklist_action(count, CFG["blacklist"]["strikes_before_timeout"], entry["action"])
            db.log(uid, name, "blacklist", count, action, word, [me])
            print(f"[yasaklı kelime] {name}: {text!r} -> '{word}' bulundu, ihlal #{count}, karar: {action}", flush=True)
            kick.delete(mid)
            if action == "timeout":
                # Kelimeye özel süre yalnızca "doğrudan timeout" için geçerli; standart cezanın timeout'u genel süreyi kullanır.
                minutes = entry["minutes"] if entry["action"] == "timeout" and entry["minutes"] else CFG["blacklist"]["timeout_minutes"]
                kick.timeout(uid, minutes, "Yasaklı kelime")
            elif action == "ban":
                kick.ban(uid, "Yasaklı kelime")
            return
        hit = rules.blacklist_hit(text, blacklist(targeted=True), CFG["blacklist"]["allowed"])
        if hit:  # kelime tek başına serbest; birine yöneltilmiş mi, model ya da sen karar verirsin
            word = hit[1]
            if hit[0].get("notify"):
                notify(f"hedefli kelime: {hit[0]['word']}", uid, name, text)
            rows = db.recent(CFG["llm"]["context_messages"])
            if CFG["llm"]["enabled"]:
                print(f"[hedefli kelime] {name}: {text!r} -> '{word}', model yorumluyor...", flush=True)
                threading.Thread(target=llm.targeted, args=(me, word, rows), daemon=True).start()
            else:
                print(f"[hedefli kelime] {name}: {text!r} -> '{word}', incelemeye alındı", flush=True)
                db.log(uid, name, "hedefli", 0, "inceleme", word, rows, "open")
        sp = CFG["spam"]
        if sp["enabled"] and len(rules.normalize(text).split()) >= sp["min_words"]:  # emote'lu/kısa mesaj sayacı ne artırır ne sıfırlar
            # Önceki mesaj: bu kullanıcının, yalnızca emotelerden oluşmayan son mesajı.
            prev = next((m for m in reversed(db.recent(10, uid)[:-1]) if rules.normalize(m["content"]).split()), None)
            if prev:
                sim = rules.similarity(prev["content"], text)
                if sim < sp["similarity_percent"]:
                    db.reset(uid, "spam")
                else:
                    count = db.bump(uid, "spam")
                    print(f"[spam] {name}: {text!r} -> önceki mesaja %{sim} benzer, sayaç {count}/{sp['repeat_count'] - 1}", flush=True)
                    if count >= sp["repeat_count"] - 1:  # 3 mesaj = 2 benzer çift
                        db.log(uid, name, "spam", count, "timeout", f"{sp['repeat_count']} kez tekrar, son benzerlik %{sim}", db.recent(sp["repeat_count"], uid))
                        db.reset(uid, "spam")
                        kick.timeout(uid, sp["timeout_minutes"], "Spam")
                        if sp["warning"]:
                            kick.send(f"@{name} {sp['warning']}")
                        return
        if rules.is_caps(text, CFG["caps"]["min_letters"]):
            count = db.bump(uid, "caps")
            print(f"[caps] {name}: {text!r} -> ardışık caps #{count}", flush=True)
            if count >= CFG["caps"]["streak"]:
                db.log(uid, name, "caps", count, "timeout", "", db.recent(count, uid))
                db.reset(uid, "caps")
                kick.timeout(uid, CFG["caps"]["timeout_minutes"], "Sürekli büyük harf")
                if CFG["caps"]["warning"]:
                    kick.send(f"@{name} {CFG['caps']['warning']}")
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
