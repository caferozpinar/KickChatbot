import copy
import json
import threading
import unittest
from unittest import mock

from bot import CFG, DEFAULT, STATE, announcer, db, listener, llm, moderation, panel, rules, validate

llm_real = llm  # Handle testlerinde "llm" parametresi sahte modüldür

TEST_CFG = {
    "dry_run": True, "nick": "Charasy", "exempt_badges": ["broadcaster", "moderator", "vip"],
    "channel": "test", "channels": [{"slug": "test", "chatroom_id": 1, "broadcaster_user_id": 1}],
    "blacklist": {"strikes_before_timeout": 3, "timeout_minutes": 10, "words": [{"word": "yarrak", "anywhere": False, "targeted": False},
                                                                              {"word": "amk", "anywhere": False, "targeted": True}]},
    "caps": {"streak": 5, "min_letters": 4, "timeout_minutes": 5},
    "llm": {"enabled": True, "url": "http://localhost:11434", "model": "m", "context_messages": 5,
            "dry_run": True, "examples": ""},
    "announcements": {"gap_minutes": 5, "repeat_min_minutes": 20, "repeat_max_minutes": 40, "messages": ["a"]},
}


def event(text, uid=7, mid=None, badges=()):
    event.n += 1
    return {"message_id": mid or f"m{event.n}", "content": text,
            "broadcaster": {"user_id": 1},
            "sender": {"user_id": uid, "username": f"u{uid}", "identity": {"badges": [{"type": b} for b in badges]}}}


event.n = 0


class Rules(unittest.TestCase):
    def test_blacklist(self):
        words, parts = rules.load_blacklist(["# yorum", "yarrak", "*salak"])
        for hit in ("yarrak", "YARRRRRRAK", "sen yaaarrraaak", "salaksın", "SALAAAK"):
            self.assertTrue(rules.blacklist_hit(hit, words, parts), hit)
        for clean in ("yarın", "yarraklar", "selam [emote:1:yarrak]"):  # ekli hal yalnızca * ile yakalanır
            self.assertIsNone(rules.blacklist_hit(clean, words, parts), clean)

    def test_blacklist_evasion(self):
        words, parts = rules.load_blacklist(["şeftali"])
        for hit in ("seftali", "ŞEFTALİ", "ş e f t a l i", "s.e.f.t.a.l.i", "seftal1", "s3ft4li", "bu bir Ş E F T A L İ işte"):
            self.assertTrue(rules.blacklist_hit(hit, words, parts), hit)
        for clean in ("şeftalili", "sen ve ben", "saat 5 te 1 elma", "sftali"):  # sesli harf düşürme yakalanmaz
            self.assertIsNone(rules.blacklist_hit(clean, words, parts), clean)
        words, parts = rules.load_blacklist(["sik", "*göt"])
        for hit in ("sik kafalı", "s1k", "gotlek", "GÖÖÖT"):
            self.assertTrue(rules.blacklist_hit(hit, words, parts), hit)
        for clean in ("sık kafalı", "şık", "güt"):  # mesajdaki Türkçe harf başka harfin yerine sayılmaz
            self.assertIsNone(rules.blacklist_hit(clean, words, parts), clean)

    def test_blacklist_action(self):
        self.assertEqual([rules.blacklist_action(n, 3) for n in (1, 2, 3, 4, 5)],
                         ["delete", "delete", "timeout", "ban", "ban"])

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

    def test_pick(self):
        self.assertIsNone(announcer.pick([90, 95], 100, 20, 40))       # hepsi çok yeni
        self.assertEqual(announcer.pick([90, 75], 100, 20, 40), 1)     # yalnızca biri min'i geçti
        self.assertEqual(announcer.pick([50, 75, 70], 100, 20, 40), 0)  # süresi dolan öne geçer

    def test_validate(self):
        self.assertEqual(validate(copy.deepcopy(TEST_CFG)), TEST_CFG)
        for path, bad in ((("caps", "streak"), 0), (("caps", "streak"), "5"), (("caps", "streak"), True),
                          (("blacklist", "timeout_minutes"), 10081), (("channel",), "yok"),
                          (("channels",), [{"slug": "../x", "chatroom_id": 1, "broadcaster_user_id": 1}]),
                          (("announcements", "messages"), ["x" * 501]), (("channel",), "")):
            cfg = copy.deepcopy(TEST_CFG)
            target = cfg
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = bad
            with self.assertRaises(ValueError, msg=str(path)):
                validate(cfg)
        self.assertEqual(validate(copy.deepcopy(DEFAULT)), DEFAULT)   # yeni kurulum: kanal ve nick henüz yok
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
