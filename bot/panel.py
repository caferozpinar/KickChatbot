"""Yerel yönetim paneli: ayarlar, inceleme kuyruğu ve elle aksiyon. Yalnızca bu bilgisayardan erişilir."""
import http.server, json, os, threading, urllib.parse
from pathlib import Path

from . import CFG, STATE, channel, db, kick, llm, moderation, rules, save

PORT = 8765
PAGE = Path(__file__).with_name("panel.html")


def state():
    return {"config": CFG, "open": db.open_count(),
            "status": {**STATE, "logged_in": kick.logged_in(), "has_app": kick.has_app(), "redirect": kick.REDIRECT, "scopes": kick.SCOPES}}


def violations(query):
    status = "open" if query.get("status") == ["open"] else None
    return [{**dict(v), "evidence": json.loads(v["evidence"])} for v in db.violations(200, status)]


def test(body):
    text = str(body["text"])
    return {"word": rules.blacklist_hit(text, *moderation.blacklist()),
            "targeted": rules.blacklist_hit(text, *moderation.blacklist(targeted=True)),
            "caps": rules.is_caps(text, CFG["caps"]["min_letters"])}


def action(body):
    """Bir kayıt üzerinden elle aksiyon. Hedef, o kaydın kanıtındaki bir mesaj ya da kullanıcı olmak zorunda."""
    v = db.violation(int(body["id"]))
    if v is None:
        raise ValueError("Kayıt bulunamadı")
    evidence, act = json.loads(v["evidence"]), body["action"]
    users = {v["user_id"]: v["username"], **{m["user_id"]: m["username"] for m in evidence}}
    dry = " (yazdırma modu, uygulanmadı)" if CFG["dry_run"] else ""
    if act in ("close", "reopen"):
        db.annotate(v["id"], status="done" if act == "close" else "open")
        return
    if act == "teach":  # modelin öğrendiği örnek: bu kaydın mesajı kişiye yönelik miydi?
        if v["rule"] != "hedefli" or body["label"] not in ("kisi", "serbest"):
            raise ValueError("Bu kayıt öğretilemez")
        note = str(body.get("note") or "").strip()[:200]
        db.teach(llm.mask(evidence[-1:], CFG["nick"])[0][0][1], body["label"], note)  # hedefli kayıtta son mesaj, karar verilen mesajdır
        return db.annotate(v["id"], "Öğretildi: " + ("kişiye yönelik" if body["label"] == "kisi" else "kişiye yönelik değil")
                           + (f" ({note})" if note else ""))
    if act == "delete":
        msg = next((m for m in evidence if m["id"] == body["message_id"]), None)
        if msg is None:
            raise ValueError("Mesaj bu kayda ait değil")
        kick.delete(msg["id"])
        note = f"{msg['username']} mesajı silindi: {msg['content'][:80]}"
    else:
        uid = body["user_id"]
        if uid not in users:
            raise ValueError("Kullanıcı bu kayda ait değil")
        if act == "timeout":
            minutes = int(body["minutes"])
            if not 1 <= minutes <= 10080:
                raise ValueError("Süre 1 ile 10080 dakika arasında olmalı")
            kick.timeout(uid, minutes, "Panel")
            note = f"{users[uid]}: {minutes} dk timeout"
        elif act == "ban":
            kick.ban(uid, "Panel")
            note = f"{users[uid]}: kalıcı ban"
        elif act == "unban":
            kick.unban(uid)
            note = f"{users[uid]}: timeout/ban kaldırıldı"
        elif act == "reset":
            db.reset(uid)
            note, dry = f"{users[uid]}: sayaçlar sıfırlandı", ""
        else:
            raise ValueError("Bilinmeyen aksiyon")
    db.annotate(v["id"], note + dry)


def save_config(body):
    save(body)
    db.init()  # kanal ya da yazdırma modu değiştiyse o kanalın veritabanına geç


def run(body):
    """Başlat / durdur."""
    if body["on"] and not (channel() and channel()["chatroom_id"]):
        raise ValueError("Önce Kurulum sayfasından kanalını ve chat odasını bağla")
    STATE["running"] = bool(body["on"])


def login(body):
    try:
        return {"url": kick.login_start(str(body.get("client_id") or ""), str(body.get("client_secret") or ""),
                                        f"http://localhost:{PORT}/#kurulum")}
    except OSError:
        raise ValueError("8080 numaralı bağlantı noktası başka bir program tarafından kullanılıyor; o programı kapatıp yeniden dene")


def quit_app(body):
    threading.Timer(0.3, os._exit, [0]).start()  # cevap gittikten sonra kapan


ROUTES = {"/api/config": save_config, "/api/action": action, "/api/test": test, "/api/run": run, "/api/login": login,
          "/api/quit": quit_app, "/api/resolve": lambda b: {"broadcaster_user_id": kick.resolve(str(b["slug"]))}}


class Handler(http.server.BaseHTTPRequestHandler):
    def _local(self):
        # Başka bir sitenin tarayıcı üzerinden panele istek atmasını engelle (DNS rebinding / CSRF).
        ok = self.headers.get("Host", "").rsplit(":", 1)[0] in ("localhost", "127.0.0.1")
        if not ok:
            self._json(403, {"error": "Yalnızca localhost"})
        return ok

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._local():
            return
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/state":
            self._json(200, state())
        elif url.path == "/api/violations":
            self._json(200, violations(urllib.parse.parse_qs(url.query)))
        else:
            self._json(404, {"error": "Yok"})

    def do_POST(self):
        if not self._local():
            return
        handler = ROUTES.get(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        # JSON şartı: başka sitelerdeki formlar bu içerik türüyle istek gönderemez.
        if handler is None or not self.headers.get("Content-Type", "").startswith("application/json") \
                or not 0 < length <= 1_000_000:
            return self._json(400, {"error": "Geçersiz istek"})
        try:
            self._json(200, handler(json.loads(self.rfile.read(length))) or {"ok": True})
        except (ValueError, KeyError, TypeError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # Kick API hatası gibi; panelde gösterilir
            self._json(502, {"error": str(e)})

    def log_message(self, *a):
        pass


def server():
    """Yalnızca bu bilgisayardan erişilir. Port doluysa OSError verir (uygulama zaten açık)."""
    class Server(http.server.ThreadingHTTPServer):
        # Windows'ta bu seçenek aynı porta ikinci bir uygulamanın bağlanmasına izin verir; Linux'ta ise
        # kapatıp hemen yeniden açabilmek için gerekir.
        allow_reuse_address = os.name != "nt"
    return Server(("127.0.0.1", PORT), Handler)
