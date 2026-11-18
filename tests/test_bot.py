import copy
import json
import threading
import unittest
from unittest import mock

from bot import CFG, DEFAULT, STATE, migrate, announcer, db, listener, llm, moderation, panel, rules, validate

llm_real = llm  # Handle testlerinde "llm" parametresi sahte modüldür

TEST_CFG = {
    "dry_run": True, "nick": "Charasy", "exempt_badges": ["broadcaster", "moderator", "vip"],
    "channel": "test", "channels": [{"slug": "test", "chatroom_id": 1, "broadcaster_user_id": 1}],
    "blacklist": {"strikes_before_timeout": 3, "timeout_minutes": 10, "decay_minutes": 30, "allowed": ["ooc"], "words": [
        {"word": "yarrak", "match": "variants", "targeted": False, "action": "standard", "minutes": 0},
        {"word": "amk", "match": "variants", "targeted": True, "action": "standard", "minutes": 0}]},
    "caps": {"streak": 5, "min_letters": 4, "timeout_minutes": 5},
    "llm": {"enabled": True, "url": "http://localhost:11434", "model": "m", "context_messages": 5,
            "dry_run": True, "examples": ""},
    "announcements": {"gap_minutes": 5, "repeat_min_minutes": 20, "repeat_max_minutes": 40, "messages": [{"text": "a", "active": True}]},
    "spam": {"enabled": True, "similarity_percent": 80, "repeat_count": 3, "min_words": 3, "timeout_minutes": 5, "warning": "spam yapma"},
    "commands": {"cooldown_seconds": 10, "items": [{"trigger": "!abone", "response": "abone olmak için link"}]},
    "helpers": {"nicks": ["ali"], "commands": [{"trigger": "!sil", "do": "delete", "minutes": 0}, {"trigger": "!to", "do": "timeout", "minutes": 7}]},
}


def event(text, uid=7, mid=None, badges=()):
    event.n += 1
    return {"message_id": mid or f"m{event.n}", "content": text,
            "broadcaster": {"user_id": 1},
            "sender": {"user_id": uid, "username": f"u{uid}", "identity": {"badges": [{"type": b} for b in badges]}}}


event.n = 0


class Rules(unittest.TestCase):
    @staticmethod
    def hit(text, word, match="variants"):
        found = rules.blacklist_hit(text, [{"word": word, "match": match, "action": "standard"}])
        return found and found[1]

    def test_blacklist(self):
        for hit in ("yarrak", "YARRRRRRAK", "sen yaaarrraaak"):
            self.assertTrue(self.hit(hit, "yarrak"), hit)
        for clean in ("yarın", "yarraklar", "selam [emote:1:yarrak]"):  # ekli hal yalnızca "her yerde" ile yakalanır
            self.assertIsNone(self.hit(clean, "yarrak"), clean)
        for hit in ("salaksın", "SALAAAK"):
            self.assertTrue(self.hit(hit, "salak", "anywhere"), hit)

    def test_blacklist_evasion(self):
        for hit in ("seftali", "ŞEFTALİ", "ş e f t a l i", "s.e.f.t.a.l.i", "seftal1", "s3ft4li", "bu bir Ş E F T A L İ işte"):
            self.assertTrue(self.hit(hit, "şeftali"), hit)
        for clean in ("şeftalili", "sen ve ben", "saat 5 te 1 elma", "sftali"):  # sesli harf düşürme yakalanmaz
            self.assertIsNone(self.hit(clean, "şeftali"), clean)
        for hit in ("sik kafalı", "s1k"):
            self.assertTrue(self.hit(hit, "sik"), hit)
        self.assertTrue(self.hit("GÖÖÖT", "göt", "anywhere"))
        for clean in ("sık kafalı", "şık"):  # mesajdaki Türkçe harf başka harfin yerine sayılmaz
            self.assertIsNone(self.hit(clean, "sik"), clean)

    def test_blacklist_exact(self):
        for hit in ("oç", "OÇ", "sen oç!", "OÇ oç"):
            self.assertEqual(self.hit(hit, "oç", "exact").lower(), "oç", hit)
        for clean in ("oc", "o ç", "0ç", "oçç", "oçlar", "koç", "[emote:1:oç]"):  # birebir: türev, uzatma, ek yok
            self.assertIsNone(self.hit(clean, "oç", "exact"), clean)

    def test_allowed(self):
        w = [{"word": "oc", "match": "variants", "action": "standard"}]
        hit = lambda t: rules.blacklist_hit(t, w, ["OOC", "occ"])
        for clean in ("ooc", "OOC", "occ", "sen ooc sen"):
            self.assertIsNone(hit(clean), clean)
        for caught in ("oc", "oooc", "ooc oc", "o c"):  # serbest kelime başkasını açmaz
            self.assertTrue(hit(caught), caught)

    def test_blacklist_action(self):
        self.assertEqual([rules.blacklist_action(n, 3) for n in (1, 2, 3, 4, 5)],
                         ["delete", "delete", "timeout", "ban", "ban"])
        self.assertEqual([rules.blacklist_action(1, 3, a) for a in ("delete", "timeout", "ban")], ["delete", "timeout", "ban"])

    def test_caps(self):
        self.assertTrue(rules.is_caps("NE DİYORSUN IŞIK", 4))
        self.assertTrue(rules.is_caps("@Charasy SELAM [emote:1:Kappa]", 4))
        self.assertFalse(rules.is_caps("Selam MİLLET", 4))
        self.assertFalse(rules.is_caps("GG", 4))
        self.assertFalse(rules.is_caps("[emote:37226:KEKW] 123", 4))

    def test_mentions(self):
        self.assertTrue(rules.mentions("selam @charasy!", "Charasy"))
        self.assertFalse(rules.mentions("selam @Charasy2", "Charasy"))
        self.assertFalse(rules.mentions("selam Charasy", "Charasy"))

    def test_chat_message(self):
        inner = '{"id":"e95b","content":"aaa","sender":{"id":29063855,"username":"Charasy"}}'
        frame = {"push": {"channel": "chatrooms.1.v2", "pub": {"data": {"event": "App\\Events\\ChatMessageEvent", "data": inner}}}}
        msg = listener.chat_message(frame)
        self.assertEqual(msg["content"], "aaa")
        ev = moderation.from_websocket(msg, 29063855)
        self.assertEqual((ev["message_id"], ev["sender"]["user_id"]), ("e95b", 29063855))
        self.assertTrue(rules.is_exempt(ev, []))  # rozet bilgisi yokken de yayın sahibi muaf
        self.assertIsNone(listener.chat_message({"id": 2, "subscribe": {}}))
        self.assertIsNone(listener.chat_message({"push": {"pub": {"data": {"event": "App\\Events\\Other", "data": "{}"}}}}))

    def test_mask(self):
        rows = [{"username": "Ahmet54", "content": "selam @Charasy ve @Veli_x, sen nasılsın"},
                {"username": "sen", "content": "AHMET54 sus, charasy haklı"}]
        lines, real = llm.mask(rows, "Charasy")
        self.assertEqual(lines, [("Kişi1", "selam @Yayıncı ve @Kişi3, sen nasılsın"), ("Kişi2", "Kişi1 sus, Yayıncı haklı")])
        self.assertEqual(llm.unmask("Kişi1 ve Yayıncı, Kişi9", real), "Ahmet54 ve Charasy, Kişi9")

    def test_similarity(self):
        self.assertEqual(rules.similarity("Selam nasılsınız HERKES", "selam nasılsınııız herkes"), 100)
        self.assertEqual(rules.similarity("bir iki üç dört beş", "bir iki üç dört altı"), 80)
        self.assertEqual(rules.similarity("bir iki üç", "dört beş altı"), 0)
        self.assertEqual(rules.similarity("[emote:1:x]", "selam"), 0)

    def test_pick(self):
        self.assertIsNone(announcer.pick([90, 95], 100, 20, 40))       # hepsi çok yeni
        self.assertEqual(announcer.pick([90, 75], 100, 20, 40), 1)     # yalnızca biri min'i geçti
        self.assertEqual(announcer.pick([50, 75, 70], 100, 20, 40), 0)  # süresi dolan öne geçer

    def test_validate(self):
        self.assertEqual(validate(copy.deepcopy(TEST_CFG)), TEST_CFG)
        for path, bad in ((("caps", "streak"), 0), (("caps", "streak"), "5"), (("caps", "streak"), True), (("spam", "repeat_count"), 1),
                          (("blacklist", "timeout_minutes"), 10081), (("channel",), "yok"),
                          (("channels",), [{"slug": "../x", "chatroom_id": 1, "broadcaster_user_id": 1}]),
                          (("announcements", "messages"), [{"text": "x" * 501, "active": True}]), (("channel",), ""),
                          (("commands", "items"), [{"trigger": "iki kelime", "response": "x"}])):
            cfg = copy.deepcopy(TEST_CFG)
            target = cfg
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = bad
            with self.assertRaises(ValueError, msg=str(path)):
                validate(cfg)
        self.assertEqual(validate(copy.deepcopy(DEFAULT)), DEFAULT)   # yeni kurulum: kanal ve nick henüz yok
        cfg = copy.deepcopy(TEST_CFG)
        cfg["channels"].append({"slug": "TEST", "chatroom_id": 0, "broadcaster_user_id": 1})  # büyük/küçük harf farkıyla aynı kanal
        with self.assertRaisesRegex(ValueError, "iki kez"):
            validate(cfg)
        cfg = copy.deepcopy(TEST_CFG)
        cfg["fazla"] = 1
        with self.assertRaises(ValueError):
            validate(cfg)


@mock.patch.object(moderation, "kick")
@mock.patch.object(moderation, "llm")
class Handle(unittest.TestCase):
    def setUp(self):
        cfg = mock.patch.dict(CFG, copy.deepcopy(TEST_CFG), clear=True)  # gerçek config.json'dan bağımsız
        cfg.start()
        self.addCleanup(cfg.stop)
        db.init(":memory:")

    def test_blacklist_escalation(self, llm, kick):
        for _ in range(4):
            moderation.handle(event("yarrrrak"))
        self.assertEqual(kick.delete.call_count, 4)
        self.assertEqual(kick.timeout.call_count, 1)   # 3. ihlal
        self.assertEqual(kick.ban.call_count, 1)       # 4. ihlal
        self.assertEqual([v["action"] for v in db.violations(9)][::-1], ["delete", "delete", "timeout", "ban"])

    def test_word_actions(self, llm, kick):
        CFG["blacklist"]["words"] += [
            {"word": "oç", "match": "exact", "targeted": False, "action": "ban", "minutes": 0},
            {"word": "mal", "match": "exact", "targeted": False, "action": "timeout", "minutes": 30},
            {"word": "hoppa", "match": "exact", "targeted": False, "action": "delete", "minutes": 0}]
        moderation.handle(event("oc"))                       # birebir değil: dokunulmaz
        kick.delete.assert_not_called()
        moderation.handle(event("hoppa", uid=3))             # yalnızca sil: ceza ve sayaç yok
        moderation.handle(event("hoppa", uid=3))
        kick.timeout.assert_not_called()
        moderation.handle(event("sen mal", uid=4))           # kelimenin kendi süresi
        kick.timeout.assert_called_once_with(4, 30, "Yasaklı kelime")
        CFG["blacklist"]["words"][-2]["action"] = "standard"  # süre yalnızca doğrudan timeout'ta geçerli; unutulmuş 30 dk uygulanmaz
        CFG["blacklist"]["strikes_before_timeout"] = 1
        moderation.handle(event("mal", uid=6))
        kick.timeout.assert_called_with(6, 10, "Yasaklı kelime")
        CFG["blacklist"]["words"][-2]["action"] = "timeout"
        moderation.handle(event("yarrak oç", uid=7))         # iki kelime birden: ağır olan (ban) kazanır, listedeki sıra önemsiz
        kick.ban.assert_called_with(7, "Yasaklı kelime")
        kick.ban.reset_mock()
        moderation.handle(event("OÇ", uid=5))                # ilk seferde doğrudan ban
        kick.ban.assert_called_once()
        by = {u["user_id"]: u for u in db.users()}
        self.assertEqual((by[3]["deleted"], by[3]["strikes"]), (2, 0))
        self.assertEqual((by[4]["timeouts"], by[4]["strikes"]), (1, 1))
        self.assertEqual((by[5]["bans"], by[5]["deleted"]), (1, 1))

    def test_helper(self, llm, kick):
        def reply(text, who="ali", target=9, badges=()):
            ev = event(text, uid=20)
            ev["sender"]["username"] = who
            ev["reply_to"] = {"id": "orig", "user_id": target, "username": f"u{target}"}
            moderation.handle(ev)
        moderation.handle(event("selam", uid=9, mid="orig"))
        reply("!to bence yeter")                       # geçici moderatör: mesaj silinir, 7 dk timeout
        kick.delete.assert_called_with("orig")
        kick.timeout.assert_called_once_with(9, 7, "ali istedi")
        self.assertEqual(db.violations(9)[0]["detail"], "ali istedi: !to")
        kick.delete.reset_mock()
        reply("!sil", who="veli")                      # listede olmayan kişi: hiçbir şey olmaz
        reply("sil", who="ali")                        # komut değil
        kick.delete.assert_not_called()
        reply("!sil", target=1)                        # yayıncı korunur
        kick.delete.assert_not_called()
        ev = event("!sil", uid=20); ev["sender"]["username"] = "ali"   # cevap değil: işlem yok
        moderation.handle(ev)
        kick.delete.assert_not_called()

    def test_decay(self, llm, kick):
        for _ in range(3):
            db.bump(4, "blacklist")
        with mock.patch("bot.db.time.time", return_value=__import__("time").time() + 65 * 60):  # 2 aralık geçti
            self.assertEqual(db.bump(4, "blacklist"), 2)   # 3 - 2 + 1
        with mock.patch("bot.db.time.time", return_value=__import__("time").time() + 10 * 3600):
            db.decay()
        self.assertEqual(db.bump(4, "blacklist"), 1)

    def test_mod_events(self, llm, kick):
        kick.MINE = set()
        for i in range(4):
            moderation.handle(event("selam", uid=9, mid=f"x{i}"))
        for i in range(4):
            moderation.mod_event({"_event": "deleted", "message": {"id": f"x{i}"}})
        self.assertEqual((kick.timeout.call_count, kick.ban.call_count), (1, 1))  # 3. ihlalde timeout, 4.'de ban
        kick.MINE = {("msg", "z")}
        moderation.handle(event("selam", uid=8, mid="z"))
        moderation.mod_event({"_event": "deleted", "message": {"id": "z"}})   # botun kendi silmesi sayılmaz
        moderation.mod_event({"_event": "deleted", "message": {"id": "yok"}})  # tanımadığımız mesaj
        self.assertEqual([v for v in db.violations(50) if v["user_id"] == 8], [])
        moderation.mod_event({"_event": "banned", "user": {"id": 5, "username": "k"}, "banned_by": {"username": "ali"}, "permanent": True})
        self.assertEqual(db.violations(1)[0]["detail"], "ali attı")

    def test_migrate(self, llm, kick):
        old = {"blacklist": {"strikes_before_timeout": 3, "timeout_minutes": 10, "words": [
            {"word": "a", "anywhere": False, "targeted": False}, {"word": "b", "anywhere": True, "targeted": True}]}}
        words = validate(migrate(old))["blacklist"]["words"]
        self.assertEqual([(w["match"], w["action"], w["minutes"]) for w in words], [("variants", "standard", 0), ("anywhere", "standard", 0)])

    def test_caps_streak(self, llm, kick):
        for _ in range(4):
            moderation.handle(event("BAĞIRIYORUM"))
        moderation.handle(event("sakinim"))               # sayaç sıfırlanır
        for _ in range(4):
            moderation.handle(event("BAĞIRIYORUM"))
        kick.timeout.assert_not_called()
        moderation.handle(event("BAĞIRIYORUM"))
        kick.timeout.assert_called_once()
        self.assertEqual(len(json.loads(db.violations(1)[0]["evidence"])), 5)

    def test_spam(self, llm, kick):
        moderation.handle(event("bu akşam maç var mı", uid=20))
        moderation.handle(event("tamamen farklı bir cümle", uid=20))
        moderation.handle(event("tamamen farklı bir cümle", uid=20))
        moderation.handle(event("[emote:1:KEKW] [emote:1:KEKW]", uid=20))  # emote zinciri bozmaz, sayılmaz
        kick.timeout.assert_not_called()  # 2 tekrar henüz yetmez
        moderation.handle(event("tamamen farklı bir cümle", uid=20))
        kick.timeout.assert_called_once()
        kick.send.assert_called_once_with("@u20 spam yapma")
        moderation.handle(event("selam", uid=21)); moderation.handle(event("selam", uid=21))  # kısa mesaj
        moderation.handle(event("tamamen farklı bir cümle", uid=22, badges=["moderator"]))
        moderation.handle(event("tamamen farklı bir cümle", uid=22, badges=["moderator"]))  # muaf
        kick.timeout.assert_called_once()

    def test_exempt_duplicate_mention(self, llm, kick):
        moderation.handle(event("yarrak", badges=["moderator"]))
        moderation.handle(event("yarrak", uid=1))          # yayın sahibi
        moderation.handle(event("yarrak", mid="same"))
        moderation.handle(event("yarrak", mid="same"))     # aynı olay iki kez gelirse tek sayılır
        self.assertEqual(kick.delete.call_count, 1)
        moderation.handle(event("@Charasy bakar mısın"))
        moderation.handle(event("@Charasy test", uid=1))   # kendi mesajı LLM'i tetiklemez
        for th in threading.enumerate():
            if th is not threading.current_thread():
                th.join(5)
        llm.review.assert_called_once()

    def test_targeted_word(self, llm, kick):
        moderation.handle(event("amk bugün çok yoruldum", uid=8))
        rows = llm.targeted.call_args.args[2]              # model açık: karar modele gider, bot kendisi ceza kesmez
        self.assertEqual(rows[-1]["content"], "amk bugün çok yoruldum")
        CFG["llm"]["enabled"] = False
        moderation.handle(event("u8 senin ben amk", uid=9))  # model kapalı: incelemeye düşer
        self.assertEqual((db.open_count(), db.violations(1)[0]["rule"]), (1, "hedefli"))
        kick.delete.assert_not_called()

        CFG["llm"]["dry_run"] = False
        me = {"id": "x", "user_id": 9, "username": "u9", "content": "u8 senin ben amk"}
        with mock.patch.object(llm_real, "kick") as lk, mock.patch.object(llm_real, "ask") as ask:
            ask.return_value = {"hedef": "durum"}
            llm_real.targeted(me, "amk", rows)
            lk.delete.assert_not_called()
            ask.return_value = {"hedef": "kisi", "gerekce": "g"}
            llm_real.targeted(me, "amk", rows)
            lk.delete.assert_called_once_with("x")          # model yalnızca siler, ceza kararı panelde
            ask.side_effect = TimeoutError("zaman aşımı")   # model çökerse silme yok, incelemeye düşer
            llm_real.targeted(me, "amk", rows)
            lk.delete.assert_called_once()
            lk.timeout.assert_not_called()
            lk.ban.assert_not_called()
        self.assertEqual(db.open_count(), 3)
        self.assertEqual(db.violations(9, "done")[0]["action"], "serbest")  # serbest bıraktığı da kayıtta

    def test_teach(self, llm, kick):
        CFG["llm"]["dry_run"] = False
        me = {"id": "x", "user_id": 9, "username": "u9", "content": "u8 senin ben amk"}
        with mock.patch.object(llm_real, "kick") as lk, mock.patch.object(llm_real, "ask", return_value={"hedef": "durum"}) as ask:
            llm_real.targeted(me, "amk", [me])               # model kaçırdı
            with self.assertRaises(ValueError):
                panel.action({"id": db.violations(1)[0]["id"], "action": "teach", "label": "uydurma"})
            panel.action({"id": db.violations(1)[0]["id"], "action": "teach", "label": "kisi", "note": "isim + senin"})
            llm_real.targeted({**me, "id": "y", "content": "u7 senin ben amk"}, "amk", [me])
            self.assertIn('"u8 senin ben amk" -> {"gerekce": "isim + senin", "hedef": "kisi"}', ask.call_args.args[1])  # benzer örnek modele gider
            lk.delete.assert_not_called()
            llm_real.targeted({**me, "id": "z"}, "amk", [me])  # aynı mesaj: model sorulmadan öğretilen karar uygulanır
            self.assertEqual(ask.call_count, 2)
            lk.delete.assert_called_once_with("z")
        self.assertEqual(llm_real.similar("bambaşka cümle", db.examples()), [])

    def test_review_queue_and_panel_actions(self, llm, kick):
        CFG["llm"]["enabled"] = False
        moderation.handle(event("kötü bir şey", uid=8, mid="bad"))
        moderation.handle(event("@Charasy şuna bak", uid=9))
        llm.review.assert_not_called()
        self.assertEqual(db.open_count(), 1)
        item = panel.violations({"status": ["open"]})[0]
        self.assertEqual([m["id"] for m in item["evidence"]][0], "bad")

        with mock.patch.object(panel, "kick") as pk:
            panel.action({"id": item["id"], "action": "delete", "message_id": "bad"})
            panel.action({"id": item["id"], "action": "timeout", "user_id": 8, "minutes": 15})
            pk.delete.assert_called_once_with("bad")
            pk.timeout.assert_called_once_with(8, 15, "Panel")
            for bad in ({"action": "delete", "message_id": "baska"}, {"action": "ban", "user_id": 12345},
                        {"action": "timeout", "user_id": 8, "minutes": 99999}, {"action": "uydurma", "user_id": 8}):
                with self.assertRaises(ValueError, msg=str(bad)):
                    panel.action({"id": item["id"], **bad})
            pk.ban.assert_not_called()
        panel.action({"id": item["id"], "action": "close"})
        self.assertEqual(db.open_count(), 0)
        self.assertIn("15 dk timeout", db.violation(item["id"])["notes"])

    def test_command(self, llm, kick):
        moderation._last.clear()
        moderation.handle(event("!ABONE nasıl olunur", uid=8))
        kick.send.assert_called_once_with("@u8 abone olmak için link")
        moderation.handle(event("!abone", uid=9))               # bekleme süresi dolmadan ikinci cevap yok
        moderation.handle(event("!abonelik ne", uid=9))         # başka kelime
        self.assertEqual(kick.send.call_count, 1)
        moderation._last.clear()
        moderation.handle(event("bana !abone linki ver", uid=9))  # mesajın ortasında da çalışır
        kick.send.assert_called_with("@u9 abone olmak için link")
        moderation._last.clear()
        moderation.handle(event("!abone", uid=1, badges=["broadcaster"]))  # muaf kullanıcılar da kullanabilir
        self.assertEqual(kick.send.call_count, 3)

    def test_start_needs_chatroom(self, llm, kick):
        self.addCleanup(STATE.update, running=False)
        panel.run({"on": True})
        self.assertTrue(STATE["running"])
        CFG["channels"][0]["chatroom_id"] = 0                 # chat odası bağlanmamış kanal başlatılamaz
        with self.assertRaises(ValueError):
            panel.run({"on": True})
        panel.run({"on": False})
        self.assertFalse(STATE["running"])


if __name__ == "__main__":
    unittest.main()
