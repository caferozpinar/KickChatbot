"""Kick chat'ini sitenin kendi websocket'inden okur. Resmi değil: Kick değiştirirse burası bozulur."""
import json, time, urllib.request, uuid

from websockets.sync.client import connect

from . import SSL, STATE

AUTH = "https://web.kick.com/api/v1/realtime/auth/connection"
# shortcut: adres sabit yazıldı; Kick bölgeyi değiştirirse web.kick.com/api/v1/realtime/connection cevabından okunmalı
WS = "wss://realtime.us-east-1.platform.kick.com/connection/websocket"
REFRESH = 30 * 60  # misafir token'ı 45 dk geçerli


def _token(client_id):
    req = urllib.request.Request(AUTH, json.dumps({"client_id": client_id}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "kick-bot"})
    with urllib.request.urlopen(req, timeout=15, context=SSL) as r:
        return json.load(r)["data"]["token"]


def chat_message(frame):
    """Sunucudan gelen tek satır bir chat mesajıysa mesaj sözlüğünü, değilse None döndürür."""
    data = (frame.get("push") or {}).get("pub", {}).get("data") or {}
    return json.loads(data["data"]) if data.get("event") == "App\\Events\\ChatMessageEvent" else None


def messages(get_room):
    """Sonsuz üreteç: get_room() ile verilen odanın chat mesajlarını verir.
    Bağlantı koparsa 5 sn sonra, oda değişirse hemen yeniden bağlanır. get_room() 0 verirse (bot durduruldu) bekler."""
    client_id = str(uuid.uuid4())
    while True:
        try:
            room = get_room()
            if not room:
                time.sleep(1)
                continue
            with connect(WS, ssl=SSL) as ws:
                ws.send(json.dumps({"connect": {"token": _token(client_id), "name": "js"}, "id": 1}))
                ws.send(json.dumps({"subscribe": {"channel": f"chatrooms.{room}.v2", "flag": 1}, "id": 2}))
                renew = time.time() + REFRESH
                while get_room() == room:
                    try:
                        data = ws.recv(timeout=5)
                    except TimeoutError:
                        continue
                    for line in data.splitlines():
                        frame = json.loads(line)
                        if frame == {}:  # sunucunun ping'i; cevap gelmezse bağlantıyı kapatır
                            ws.send("{}")
                        elif "error" in frame:
                            raise RuntimeError(frame["error"])
                        elif frame.get("id") == 2:  # abonelik onayı
                            STATE["chat"] = True
                        elif (msg := chat_message(frame)) is not None:
                            yield msg
                    if time.time() > renew:
                        ws.send(json.dumps({"refresh": {"token": _token(client_id)}, "id": 3}))
                        renew = time.time() + REFRESH
            STATE["chat"] = False
        except Exception as e:
            STATE["chat"] = False
            STATE["error"] = f"{time.strftime('%H:%M')} chat bağlantısı: {e}"
            print("websocket koptu, yeniden bağlanılıyor:", e, flush=True)
            time.sleep(5)
