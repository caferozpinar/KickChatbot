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
        try:
            STATE["live"] = kick.is_live() if on else None
            texts = [m["text"] for m in c["messages"] if m["active"]]
            if STATE["live"] and texts:
                i = pick([last.get(m, 0.0) for m in texts], time.time(),
                         c["repeat_min_minutes"] * 60, c["repeat_max_minutes"] * 60)
                if i is not None:
                    kick.send(texts[i])
                    last[texts[i]] = time.time()
        except Exception as e:  # ağ hatasında bir sonraki turda tekrar dene
            STATE["error"] = f"{time.strftime('%H:%M')} duyuru: {e}"
            traceback.print_exc()
        # durdurulmuşken kısa bekle ki Başlat'a basınca duyurular 5 dk gecikmesin
        time.sleep(c["gap_minutes"] * 60 if on else 10)
