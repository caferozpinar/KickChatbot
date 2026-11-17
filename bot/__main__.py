"""kick-bot [run | log | listen]"""
import json, os, sys, threading, time, traceback, webbrowser

from . import CFG, DATA, STATE, channel, db, kick


def open_panel(url):
    if getattr(sys, "frozen", False) and "LD_LIBRARY_PATH" in os.environ:
        # Paketlenmiş uygulama kendi kütüphane klasörünü ortama yazar; tarayıcıyı açan sistem komutları
        # (xdg-open, /bin/sh) bu kütüphanelerle çalışamaz. Alt süreçler için eski değere dön.
        os.environ["LD_LIBRARY_PATH"] = os.environ.get("LD_LIBRARY_PATH_ORIG", "")
    webbrowser.open(url)


def room():
    """Dinlenecek chat odası; bot durdurulmuşsa ya da kanal bağlanmamışsa 0."""
    ch = channel()
    return ch["chatroom_id"] if STATE["running"] and ch else 0


def chat_loop():
    from . import listener, moderation
    for m in listener.messages(room):
        try:
            if "_event" in m:
                moderation.mod_event(m)
            else:
                moderation.handle(moderation.from_websocket(m, channel()["broadcaster_user_id"]))
        except Exception as e:  # tek bir mesajdaki hata botu düşürmesin
            STATE["error"] = f"{time.strftime('%H:%M')} aksiyon: {e}"
            traceback.print_exc()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "log":
        db.init()
        for v in db.violations(50)[::-1]:
            print(time.strftime("%d.%m %H:%M", time.localtime(v["at"])), v["username"], v["rule"], f"#{v['count']}",
                  v["action"], v["detail"], [f"{m['username']}: {m['content']}" for m in json.loads(v["evidence"])], sep=" | ")
    elif cmd == "listen":  # yalnızca okuma testi: gelen mesajları ekrana yazar
        from . import listener
        STATE["running"] = True
        for m in listener.messages(room):
            print(m["sender"]["username"], [b["type"] for b in m["sender"]["identity"]["badges"]], m["content"], flush=True)
    elif cmd == "run":
        from . import announcer, panel
        url = f"http://localhost:{panel.PORT}"
        try:
            server = panel.server()
        except OSError:  # zaten çalışıyor: ikinci kez açan kullanıcıya paneli göster
            open_panel(url)
            return
        if getattr(sys, "frozen", False):  # paketlenmiş uygulamada terminal yok; çıktılar dosyaya gider
            sys.stdout = sys.stderr = open(DATA / "bot.log", "a", encoding="utf-8", buffering=1)
        db.init()
        STATE["running"] = bool(channel() and channel()["chatroom_id"])  # kurulum bittiyse açılışta kendiliğinden başlar
        threading.Thread(target=announcer.run, daemon=True).start()
        threading.Thread(target=chat_loop, daemon=True).start()
        print(f"Bot çalışıyor. Panel: {url}", flush=True)
        if "--no-browser" not in sys.argv:
            open_panel(url)
        server.serve_forever()
    else:
        sys.exit(__doc__)


main()
