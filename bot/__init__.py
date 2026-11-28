"""Ortak durum: ayarlar (config.json), doğrulama ve botun anlık durumu."""
import copy, json, os, re, ssl, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _data_dir():
    """Ayarların, giriş bilgisinin ve veritabanının durduğu klasör."""
    if os.environ.get("KICK_BOT_DATA"):
        d = Path(os.environ["KICK_BOT_DATA"])
    elif not getattr(sys, "frozen", False) and (ROOT / "config.json").exists():
        return ROOT  # kaynak koddan çalışan, ayarı kodun yanında duran kurulum
    else:  # Windows: %APPDATA%\kick-bot, Linux: ~/.local/share/kick-bot
        d = Path(os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "kick-bot"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Windows'un kendi sertifika deposu eksik olabiliyor (yeni kurulumlar, Wine); certifi'nin listesi de eklenir.
SSL = ssl.create_default_context()
try:
    import certifi
    SSL.load_verify_locations(certifi.where())
except ImportError:
    pass

DATA = _data_dir()
CONFIG = DATA / "config.json"
_V = Path(__file__).with_name("VERSION")
VERSION = _V.read_text().strip() if _V.exists() else "geliştirme"  # derlemede release.yml etiketi yazar
STATE = {"chat": False, "live": None, "error": "", "running": False, "announce": "auto"}  # panelde gösterilen anlık durum

# Yeni kurulumun ayarı: güvenli taraf (yazdırma modu açık, model kapalı, liste boş).
DEFAULT = {
    "dry_run": True, "nick": "", "exempt_badges": ["broadcaster", "moderator", "vip"], "reset_seconds": 60,
    "channel": "", "channels": [],
    "blacklist": {"strikes_before_timeout": 3, "timeout_minutes": 10, "words": [], "allowed": [], "decay_minutes": 30},
    "caps": {"streak": 5, "min_letters": 4, "timeout_minutes": 5, "warning": "lütfen büyük harfle yazma."},
    "llm": {"enabled": False, "url": "http://localhost:11434", "model": "gemma4:e2b", "context_messages": 5,
            "dry_run": True, "examples": ""},
    "announcements": {"gap_minutes": 5, "repeat_min_minutes": 20, "repeat_max_minutes": 40, "messages": []},
    "spam": {"enabled": False, "similarity_percent": 80, "repeat_count": 3, "min_words": 3, "timeout_minutes": 5,
             "warning": "lütfen aynı mesajı tekrar tekrar yazma, spam yapma."},
    "commands": {"cooldown_seconds": 10, "items": []},
    "helpers": {"nicks": [], "commands": [{"trigger": "!sil", "do": "delete", "minutes": 0}, {"trigger": "!to", "do": "timeout", "minutes": 5}]},
}

# Ayar dosyasının biçimi. Listelerdeki tek eleman, liste elemanlarının şablonudur.
SHAPE = {
    "dry_run": True, "nick": "", "exempt_badges": [""], "reset_seconds": 1,
    "channel": "",
    "channels": [{"slug": "", "chatroom_id": 1, "broadcaster_user_id": 1}],
    "blacklist": {"strikes_before_timeout": 1, "timeout_minutes": 1, "words": [{"word": "", "match": "", "targeted": False, "action": "", "minutes": 1, "notify": False}], "allowed": [""], "decay_minutes": 1},
    "caps": {"streak": 1, "min_letters": 1, "timeout_minutes": 1, "warning": ""},
    "llm": {"enabled": False, "url": "", "model": "", "context_messages": 1,
            "dry_run": True, "examples": ""},
    "announcements": {"gap_minutes": 1, "repeat_min_minutes": 1, "repeat_max_minutes": 1, "messages": [{"text": "", "active": True}]},
    "spam": {"enabled": False, "similarity_percent": 1, "repeat_count": 1, "min_words": 1, "timeout_minutes": 1, "warning": ""},
    "commands": {"cooldown_seconds": 1, "items": [{"trigger": "", "response": ""}]},
    "helpers": {"nicks": [""], "commands": [{"trigger": "", "do": "", "minutes": 1}]},
}
_CHOICES = {"match": ("exact", "variants", "anywhere"),          # birebir / türevleriyle / her yerde
            "action": ("standard", "delete", "timeout", "ban"),
            "do": ("delete", "timeout", "ban")}  # geçici moderatör komutunun işlemi   # standart / yalnızca sil / doğrudan timeout / doğrudan ban
_LIMITS = {"examples": 20000, "text": 500, "url": 200, "response": 450, "warning": 450, "trigger": 30}  # metin uzunluk sınırları (varsayılan 100)


def _check(value, ref, path, key=""):
    if isinstance(ref, dict):
        if not isinstance(value, dict) or set(value) != set(ref):
            raise ValueError(f"{path}: alanlar eksik ya da fazla")
        return {k: _check(value[k], ref[k], f"{path}.{k}", k) for k in ref}
    if isinstance(ref, list):
        if not isinstance(value, list) or len(value) > 2000:
            raise ValueError(f"{path}: liste olmalı")
        return [_check(v, ref[0], f"{path}[{i}]", key) for i, v in enumerate(value)]
    if type(value) is not type(ref):
        raise ValueError(f"{path}: türü yanlış")
    if isinstance(ref, str):
        value = value.strip()
        if key in _CHOICES and value not in _CHOICES[key]:
            raise ValueError(f"{path}: geçersiz seçenek")
        if len(value) > _LIMITS.get(key, 100) or (not value and key not in ("examples", "nick", "channel", "warning")):  # nick ve kanal kurulumda dolar
            raise ValueError(f"{path}: boş ya da çok uzun")
        if key == "trigger" and " " in value:
            raise ValueError(f"{path}: komut tek kelime olmalı (ör. !abone)")
        if key == "slug" and not re.fullmatch(r"[A-Za-z0-9_-]{1,25}", value):  # dosya adında kullanılıyor
            raise ValueError(f"{path}: kanal adı yalnızca harf, rakam, _ ve - içerebilir")
    elif isinstance(ref, int) and not isinstance(ref, bool):
        # chatroom_id 0: henüz bağlanmadı. Kelimenin minutes değeri 0: genel timeout süresi kullanılır.
        if value < (0 if key in ("chatroom_id", "minutes") else 1) or ("minutes" in key and value > 10080):
            raise ValueError(f"{path}: 1 ile {10080 if key.endswith('_minutes') else 'sonsuz'} arasında olmalı")
    return value


def validate(cfg):
    """Biçimi ve sınırları denetler; temizlenmiş ayarı döndürür, sorun varsa ValueError."""
    cfg = _check(cfg, SHAPE, "ayar")
    slugs = [c["slug"].lower() for c in cfg["channels"]]
    twice = next((s for s in slugs if slugs.count(s) > 1), None)
    if twice:
        raise ValueError(f"'{twice}' kanalı listede iki kez var; birini kaldır")
    if (slugs or cfg["channel"]) and cfg["channel"].lower() not in slugs:
        raise ValueError(f"Seçili kanal ('{cfg['channel']}') kanal listesinde yok")
    a = cfg["announcements"]
    if a["repeat_min_minutes"] > a["repeat_max_minutes"]:
        raise ValueError("Duyuru tekrar süresinde en az, en çoktan büyük olamaz")
    if cfg["spam"]["similarity_percent"] > 100:
        raise ValueError("Spam benzerlik yüzdesi 100'den büyük olamaz")
    if not 2 <= cfg["spam"]["repeat_count"] <= 50:
        raise ValueError("Spam tekrar sayısı 2 ile 50 arasında olmalı")
    return cfg


def migrate(cfg):
    """Eski sürümün ayar dosyasını bugünkü biçime getirir: eksik bölümler varsayılanla dolar, kelimeler yeni alanları alır."""
    cfg = {**copy.deepcopy(DEFAULT), **cfg}
    cfg["caps"] = {**DEFAULT["caps"], **cfg["caps"]}  # eski dosyada "warning" yok
    cfg["announcements"]["messages"] = [{"text": m, "active": True} if isinstance(m, str) else m  # eski sürümde düz metindi
                                        for m in cfg["announcements"]["messages"]]
    cfg["blacklist"] = {**DEFAULT["blacklist"], **cfg["blacklist"]}  # eski dosyada "allowed" yok
    cfg["blacklist"]["words"] = [
        {"word": w["word"], "match": w.get("match") or ("anywhere" if w.get("anywhere") else "variants"),
         "targeted": w.get("targeted", False), "action": w.get("action", "standard"), "minutes": w.get("minutes", 0), "notify": w.get("notify", False)}
        for w in cfg["blacklist"]["words"]]
    return cfg


CFG = validate(migrate(json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}))


def save(cfg):
    cfg = validate(cfg)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG)  # yarım yazılmış ayar dosyası kalmasın
    for k, v in cfg.items():  # çalışan bot aynı sözlüğü okuyor; anahtar anahtar değiştir
        CFG[k] = v


def channel():
    """Seçili kanalın ayarı; henüz kanal eklenmediyse None."""
    return next((c for c in CFG["channels"] if c["slug"].lower() == CFG["channel"].lower()), None)
