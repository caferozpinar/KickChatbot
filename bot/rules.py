"""Saf kural fonksiyonları: ağ ve veritabanı yok, hepsi test edilebilir."""
import re

_EMOTE = re.compile(r"\[emote:\d+:[^\]]*\]")
_MENTION = re.compile(r"@\w+")
_WORD = re.compile(r"[^\W\d_]+")
_REPEAT = re.compile(r"(.)\1+")


_LEET = str.maketrans("013457$", "oieasts")  # rakamla yazım: 'seftal1' -> 'seftali'
_SPACED = re.compile(r"(?<=\b\w)[\W_]+(?=\w\b)")  # tek harflerin arasındaki ayraç: 'ş e f', 's.e.f'
_PLAIN = {"ş": "s", "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ü": "u"}


def normalize(text):
    """Kaçamak yazımları tek biçime indirir: 'Ş E F T A L 1', 'ŞEFTAAALİ' -> 'şeftali'."""
    text = _EMOTE.sub(" ", text).replace("I", "ı").replace("İ", "i").lower().translate(_LEET)
    return _REPEAT.sub(r"\1", _SPACED.sub("", text))


def _pattern(word):
    # Tek yönlü: listedeki Türkçe harf, mesajdaki düz haliyle de eşleşir ('şeftali' <- 'seftali'),
    # ama mesajdaki Türkçe harf yalnızca kendisiyle eşleşir ('sik' yasakken 'sık' serbest).
    return "".join(f"[{c}{_PLAIN[c]}]" if c in _PLAIN else re.escape(c) for c in normalize(word))


def load_blacklist(lines):
    """(tam kelime desenleri, her yerde aranan desenler). '*' ile başlayan satır her yerde aranır."""
    words, parts = [], []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            if line[1:].strip():
                parts.append(re.compile(_pattern(line[1:].strip())))
        else:
            words.append(re.compile(_pattern(line)))
    return words, parts


def blacklist_hit(text, words, parts):
    norm = normalize(text)
    for token in _WORD.findall(norm):
        if any(w.fullmatch(token) for w in words):
            return token
    return next((m.group() for m in (p.search(norm) for p in parts) if m), None)


def blacklist_action(count, strikes):
    """count: bu kullanıcının toplam ihlali. Mesaj her durumda silinir."""
    return "delete" if count < strikes else "timeout" if count == strikes else "ban"


def is_caps(text, min_letters):
    letters = [c for c in _MENTION.sub("", _EMOTE.sub("", text)) if c.isalpha()]
    return len(letters) >= min_letters and not any(c.islower() for c in letters)


def is_exempt(event, exempt_badges):
    sender = event["sender"]
    badges = (sender.get("identity") or {}).get("badges") or []
    return (sender["user_id"] == event["broadcaster"]["user_id"]
            or any(b.get("type") in exempt_badges for b in badges))


def mentions(text, nick):
    return re.search(rf"@{re.escape(nick)}\b", text, re.IGNORECASE) is not None
