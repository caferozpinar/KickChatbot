"""Kick API: OAuth girişi, token yenileme ve botun kullandığı uç noktalar."""
import base64, copy, hashlib, http.server, json, secrets, threading, time, tomllib
import urllib.error, urllib.parse, urllib.request

from . import CFG, DATA, SSL, channel, save

AUTH = "https://id.kick.com/oauth"
API = "https://api.kick.com/public/v1"
REDIRECT = "http://localhost:8080/callback"
SCOPES = "user:read channel:read chat:write moderation:ban moderation:chat_message:manage"
TOKENS = DATA / "tokens.json"
SECRETS = DATA / "secrets.json"  # panelden girilen Kick uygulama anahtarı
_lock = threading.Lock()
_login = {}  # süren girişin state ve verifier değerleri


def _private(path, text):
    path.touch(mode=0o600)  # hesabın anahtarı, yalnızca sahibi okusun
    path.write_text(text)


def _app():
    if SECRETS.exists():
        return json.loads(SECRETS.read_text())
    return tomllib.loads((DATA / "secrets.toml").read_text(encoding="utf-8"))  # eski kurulum


def has_app():
    return SECRETS.exists() or (DATA / "secrets.toml").exists()


def _http(method, url, *, form=None, body=None, token=None):
    headers, data = {"User-Agent": "kick-bot"}, None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers, method=method), timeout=20, context=SSL) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url} -> {e.code} {e.read()[:300]!r}") from None
    return json.loads(raw) if raw else None


def _token_request(**form):
    tok = _http("POST", AUTH + "/token", form={
        "client_id": _app()["client_id"], "client_secret": _app()["client_secret"], **form})
    tok["expires_at"] = time.time() + int(tok["expires_in"]) - 60
    _private(TOKENS, json.dumps(tok))
    return tok


def _adopt_account():
    """Girişten sonra nick'i ve kendi kanalını ayara ekler; kullanıcı bunları elle yazmak zorunda kalmaz."""
    cfg = copy.deepcopy(dict(CFG))
    me, own = api("GET", "/users")["data"][0], api("GET", "/channels")["data"]
    cfg["nick"] = cfg["nick"] or me["name"]
    for ch in own:
        if ch["slug"].lower() not in [c["slug"].lower() for c in cfg["channels"]]:
            cfg["channels"].append({"slug": ch["slug"], "chatroom_id": 0, "broadcaster_user_id": ch["broadcaster_user_id"]})
        cfg["channel"] = cfg["channel"] or ch["slug"]
    save(cfg)


class _Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        got = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        try:
            if not _login or got.get("state") != _login["state"] or "code" not in got:
                raise RuntimeError(f"Kick girişi onaylamadı: {got.get('error_description') or got.get('error') or 'geçersiz istek'}")
            _token_request(grant_type="authorization_code", redirect_uri=REDIRECT,
                           code_verifier=_login.pop("verifier"), code=got["code"])
            _login.clear()
            _adopt_account()
            self.send_response(302)
            self.send_header("Location", _login_done)
            self.end_headers()
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            hint = ("İnternet bağlantını kontrol edip panelden yeniden dene." if isinstance(e, OSError)
                    else "Client ID ve Client Secret değerlerini kontrol edip panelden yeniden dene.")
            self.wfile.write(f"Giriş başarısız: {e}\n\n{hint}".encode())

    def log_message(self, *a):
        pass


_login_done = "http://localhost:8765/"
_server = None


def login_start(client_id=None, client_secret=None, done_url=None):
    """Girişi başlatır ve tarayıcıda açılacak Kick adresini döndürür. Kick, onaydan sonra REDIRECT'e döner."""
    global _server, _login_done
    if client_id and client_secret:
        _private(SECRETS, json.dumps({"client_id": client_id.strip(), "client_secret": client_secret.strip()}))
    if not has_app():
        raise ValueError("Client ID ve Client Secret gerekli")
    _login_done = done_url or _login_done
    with _lock:
        if _server is None:
            _server = http.server.ThreadingHTTPServer(("127.0.0.1", 8080), _Callback)
            threading.Thread(target=_server.serve_forever, daemon=True).start()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    _login.update(state=secrets.token_urlsafe(16), verifier=verifier)
    return AUTH + "/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": _app()["client_id"], "redirect_uri": REDIRECT, "state": _login["state"],
        "scope": SCOPES, "code_challenge": challenge, "code_challenge_method": "S256"})


def _token():
    with _lock:
        tok = json.loads(TOKENS.read_text())
        if time.time() > tok["expires_at"]:
            tok = _token_request(grant_type="refresh_token", refresh_token=tok["refresh_token"])
        return tok["access_token"]


def api(method, path, body=None, **query):
    url = API + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
    return _http(method, url, body=body, token=_token())


def _bid():
    if channel() is None:
        raise ValueError("Önce bir kanal ekle")
    return channel()["broadcaster_user_id"]


def logged_in():
    return TOKENS.exists()


def resolve(slug):
    """Kanal adından resmi API'deki yayıncı numarasını bulur."""
    data = api("GET", "/channels", slug=slug)["data"]
    if not data:
        raise ValueError(f"'{slug}' adında bir kanal bulunamadı")
    return data[0]["broadcaster_user_id"]


def _dry(what):
    """dry_run açıksa aksiyonu yalnızca ekrana yazar."""
    if CFG["dry_run"]:
        print("  [aksiyon]", what, flush=True)
    return CFG["dry_run"]


def send(text, reply_to=None):
    if _dry(f"chate mesaj yazılır: {text}"):
        return
    body = {"broadcaster_user_id": _bid(), "content": text[:500], "type": "user"}
    if reply_to:
        body["reply_to_message_id"] = reply_to
    api("POST", "/chat", body)


def delete(message_id):
    if _dry(f"mesaj silinir (id {message_id})"):
        return
    api("DELETE", "/chat/" + urllib.parse.quote(message_id, safe=""))


def timeout(user_id, minutes, reason):
    if _dry(f"{minutes} dk timeout atılır (kullanıcı {user_id}, sebep: {reason})"):
        return
    api("POST", "/moderation/bans", {
        "broadcaster_user_id": _bid(), "user_id": user_id, "duration": minutes, "reason": reason[:100]})


def ban(user_id, reason):
    if _dry(f"kalıcı ban atılır (kullanıcı {user_id}, sebep: {reason})"):
        return
    api("POST", "/moderation/bans", {"broadcaster_user_id": _bid(), "user_id": user_id, "reason": reason[:100]})


def unban(user_id):
    if _dry(f"timeout/ban kaldırılır (kullanıcı {user_id})"):
        return
    api("DELETE", "/moderation/bans", {"broadcaster_user_id": _bid(), "user_id": user_id})


def is_live():
    if CFG["dry_run"] and not logged_in():  # girişsiz denemede yayın açık sayılır
        return True
    data = api("GET", "/channels", broadcaster_user_id=_bid())["data"]
    return bool(data and (data[0].get("stream") or {}).get("is_live"))
