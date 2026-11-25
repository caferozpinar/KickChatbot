"""Yayın açıkken duyuruları rastgele sırayla, tekrar aralığı sınırlarıyla atar."""
import random, time, traceback

from . import CFG, STATE, channel, kick


def pick(last, now, rmin, rmax):
    """last: her duyurunun son atılma zamanı. Süresi dolan (max) öncelikli, yoksa min'i geçenlerden rastgele."""
    overdue = [i for i, t in enumerate(last) if now - t >= rmax]
    ready = overdue or [i for i, t in enumerate(last) if now - t >= rmin]
    return random.choice(ready) if ready else None


def run():
    last = {}  # duyuru metni -> son atılma zamanı (panelden liste değişse de korunur)
    while True:
        c = CFG["announcements"]
        on = STATE["running"] and channel() is not None
        mode = STATE["announce"]
        try:
            try:
                STATE["live"] = kick.is_live() if on else None
            except Exception:
                if mode != "on":  # elle açıkken yayın durumu okunamasa da duyuru atılır
                    raise
            texts = [m["text"] for m in c["messages"] if m["active"]]
            if on and mode != "off" and (STATE["live"] or mode == "on") and texts:
                i = pick([last.get(m, 0.0) for m in texts], time.time(),
                         c["repeat_min_minutes"] * 60, c["repeat_max_minutes"] * 60)
                if i is not None:
                    kick.send(texts[i])
                    last[texts[i]] = time.time()
        except Exception as e:  # ağ hatasında bir sonraki turda tekrar dene
            STATE["error"] = f"{time.strftime('%H:%M')} duyuru: {e}"
            traceback.print_exc()
        # Beklerken her saniye bak: Başlat'a basılınca ya da duyuru modu değişince 5 dk beklenmesin
        end = time.time() + (c["gap_minutes"] * 60 if on else 10)
        while time.time() < end and STATE["announce"] == mode and STATE["running"] == on:
            time.sleep(1)
