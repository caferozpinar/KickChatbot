"""SQLite: gelen mesajlar, kalıcı sayaçlar ve kanıtlı ihlal/inceleme kaydı. Her kanalın kendi dosyası vardır."""
import json, sqlite3, threading, time

from . import CFG, DATA, channel

_con = _path = None
_lock = threading.Lock()


def init(path=None):
    """Seçili kanalın veritabanını açar. Kanal ya da yazdırma modu değişince yeniden çağrılır."""
    global _con, _path
    # yazdırma modu denemeleri gerçek sayaçları kirletmesin diye ayrı dosyaya yazılır
    path = path or DATA / f"bot-{(channel() or {'slug': 'kurulum'})['slug'].lower()}.db{'.test' if CFG['dry_run'] else ''}"
    with _lock:
        if path == _path and path != ":memory:":
            return
        if _con:
            _con.close()
        _con, _path = sqlite3.connect(path, check_same_thread=False, isolation_level=None), path
        _con.row_factory = sqlite3.Row
        # shortcut: messages tablosu sınırsız büyür, dosya rahatsız edecek boyuta gelirse eski satırları silen bir temizlik ekle
        _con.executescript("""
            CREATE TABLE IF NOT EXISTS messages(
                id TEXT PRIMARY KEY, at REAL, user_id INTEGER, username TEXT, content TEXT, exempt INTEGER);
            CREATE TABLE IF NOT EXISTS counters(
                user_id INTEGER, rule TEXT, count INTEGER, PRIMARY KEY(user_id, rule));
            CREATE TABLE IF NOT EXISTS violations(
                id INTEGER PRIMARY KEY, at REAL, user_id INTEGER, username TEXT, rule TEXT, count INTEGER,
                action TEXT, detail TEXT, evidence TEXT, status TEXT, notes TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS examples(text TEXT PRIMARY KEY, label TEXT, note TEXT, at REAL);
        """)


def _q(sql, *args):
    with _lock:
        return _con.execute(sql, args).fetchall()


def add_message(mid, user_id, username, content, exempt):
    """False dönerse mesaj daha önce işlenmiştir."""
    with _lock:
        return _con.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)",
                            (mid, time.time(), user_id, username, content, int(exempt))).rowcount == 1


def recent(n, user_id=None):
    """Son n mesaj, eskiden yeniye."""
    where, args = ("WHERE user_id=?", (user_id, n)) if user_id is not None else ("", (n,))
    return _q(f"SELECT * FROM messages {where} ORDER BY rowid DESC LIMIT ?", *args)[::-1]


def bump(user_id, rule):
    return _q("""INSERT INTO counters VALUES(?,?,1) ON CONFLICT(user_id, rule)
                 DO UPDATE SET count=count+1 RETURNING count""", user_id, rule)[0]["count"]


def reset(user_id, rule=None):
    if rule:
        _q("DELETE FROM counters WHERE user_id=? AND rule=?", user_id, rule)
    else:
        _q("DELETE FROM counters WHERE user_id=?", user_id)


def log(user_id, username, rule, count, action, detail, evidence, status="done"):
    """evidence: mesaj satırları (id, user_id, username, content). status 'open' ise inceleme kuyruğuna düşer."""
    _q("INSERT INTO violations(at,user_id,username,rule,count,action,detail,evidence,status) VALUES(?,?,?,?,?,?,?,?,?)",
       time.time(), user_id, username, rule, count, action, detail,
       json.dumps([{k: m[k] for k in ("id", "user_id", "username", "content")} for m in evidence], ensure_ascii=False),
       status)


def teach(text, label, note):
    """Senin verdiğin karar: text (isimleri gizlenmiş mesaj) 'kisi' ya da 'serbest'. Aynı mesaj yeniden öğretilirse üzerine yazılır."""
    _q("INSERT OR REPLACE INTO examples VALUES(?,?,?,?)", text, label, note, time.time())


def examples():
    return _q("SELECT * FROM examples")


def users():
    """Kullanıcı başına özet: kaç mesajı silindi, kaç timeout ve ban yedi, güncel ihlal sayacı. En son olay başta."""
    return _q("""
        SELECT v.user_id, MAX(v.username) username, MAX(v.at) last,
               SUM(v.action IN ('delete', 'sil') OR (v.rule = 'blacklist' AND v.action IN ('timeout', 'ban'))) deleted,
               SUM(v.action = 'timeout') timeouts, SUM(v.action = 'ban') bans,
               COALESCE((SELECT c.count FROM counters c WHERE c.user_id = v.user_id AND c.rule = 'blacklist'), 0) strikes
        FROM violations v GROUP BY v.user_id ORDER BY last DESC LIMIT 500""")


def violations(n, status=None):
    """En yeniden eskiye."""
    if status:
        return _q("SELECT * FROM violations WHERE status=? ORDER BY id DESC LIMIT ?", status, n)
    return _q("SELECT * FROM violations ORDER BY id DESC LIMIT ?", n)


def violation(vid):
    rows = _q("SELECT * FROM violations WHERE id=?", vid)
    return rows[0] if rows else None


def open_count():
    return _q("SELECT COUNT(*) c FROM violations WHERE status='open'")[0]["c"]


def annotate(vid, note=None, status=None):
    """Kayda panelden alınan aksiyonu not olarak ekler ve/veya durumunu değiştirir."""
    if note:
        _q("UPDATE violations SET notes = notes || ? WHERE id=?", time.strftime("%d.%m %H:%M ") + note + "\n", vid)
    if status:
        _q("UPDATE violations SET status=? WHERE id=?", status, vid)
