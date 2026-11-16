"""Ortak durum: ayarlar (config.json), doğrulama ve botun anlık durumu."""
import copy, json, os, re, sys
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


DATA = _data_dir()
CONFIG = DATA / "config.json"
STATE = {"chat": False, "live": None, "error": "", "running": False}  # panelde gösterilen anlık durum

# Yeni kurulumun ayarı: güvenli taraf (yazdırma modu açık, model kapalı, liste boş).
DEFAULT = {
    "dry_run": True, "nick": "", "exempt_badges": ["broadcaster", "moderator", "vip"],
    "channel": "", "channels": [],
    "blacklist": {"strikes_before_timeout": 3, "timeout_minutes": 10, "words": []},
    "caps": {"streak": 5, "min_letters": 4, "timeout_minutes": 5},
    "llm": {"enabled": False, "url": "http://localhost:11434", "model": "gemma4:e2b", "context_messages": 5,
            "dry_run": True, "examples": ""},
    "announcements": {"gap_minutes": 5, "repeat_min_minutes": 20, "repeat_max_minutes": 40, "messages": []},
    "commands": {"cooldown_seconds": 10, "items": []},
}

# Ayar dosyasının biçimi. Listelerdeki tek eleman, liste elemanlarının şablonudur.
SHAPE = {
    "dry_run": True, "nick": "", "exempt_badges": [""],
    "channel": "",
    "channels": [{"slug": "", "chatroom_id": 1, "broadcaster_user_id": 1}],
    "blacklist": {"strikes_before_timeout": 1, "timeout_minutes": 1, "words": [{"word": "", "anywhere": False, "targeted": False}]},
    "caps": {"streak": 1, "min_letters": 1, "timeout_minutes": 1},
    "llm": {"enabled": False, "url": "", "model": "", "context_messages": 1,
            "dry_run": True, "examples": ""},
    "announcements": {"gap_minutes": 1, "repeat_min_minutes": 1, "repeat_max_minutes": 1, "messages": [""]},
    "commands": {"cooldown_seconds": 1, "items": [{"trigger": "", "response": ""}]},
}
_LIMITS = {"examples": 20000, "messages": 500, "url": 200, "response": 450, "trigger": 30}  # metin uzunluk sınırları (varsayılan 100)


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
        if len(value) > _LIMITS.get(key, 100) or (not value and key not in ("examples", "nick", "channel")):  # nick ve kanal kurulumda dolar
            raise ValueError(f"{path}: boş ya da çok uzun")
        if key == "trigger" and " " in value:
            raise ValueError(f"{path}: komut tek kelime olmalı (ör. !abone)")
        if key == "slug" and not re.fullmatch(r"[A-Za-z0-9_-]{1,25}", value):  # dosya adında kullanılıyor
            raise ValueError(f"{path}: kanal adı yalnızca harf, rakam, _ ve - içerebilir")
    elif isinstance(ref, int) and not isinstance(ref, bool):
        if value < (0 if key == "chatroom_id" else 1) or (key.endswith("_minutes") and value > 10080):  # chatroom_id 0: henüz bağlanmadı
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
    return cfg


# Eski sürümün ayar dosyasında yeni eklenen bölümler yoktur; eksikleri varsayılanla tamamla.
CFG = validate({**copy.deepcopy(DEFAULT), **(json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {})})


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
