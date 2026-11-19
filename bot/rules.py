"""Saf kural fonksiyonları: ağ ve veritabanı yok, hepsi test edilebilir."""
import difflib, functools, re

_EMOTE = re.compile(r"\[emote:\d+:[^\]]*\]")
_MENTION = re.compile(r"@\w+")
_WORD = re.compile(r"[^\W\d_]+")
_REPEAT = re.compile(r"(.)\1+")


_LEET = str.maketrans("013457$", "oieasts")  # rakamla yazım: 'seftal1' -> 'seftali'
_SPACED = re.compile(r"(?<=\b\w)[\W_]+(?=\w\b)")  # tek harflerin arasındaki ayraç: 'ş e f', 's.e.f'
_PLAIN = {"ş": "s", "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ü": "u"}


def _lower(text):
    return text.replace("I", "ı").replace("İ", "i").lower()  # Türkçe küçük harf


def normalize(text):
    """Kaçamak yazımları tek biçime indirir: 'Ş E F T A L 1', 'ŞEFTAAALİ' -> 'şeftali'."""
    text = _lower(_EMOTE.sub(" ", text)).translate(_LEET)
    return _REPEAT.sub(r"\1", _SPACED.sub("", text))


def _pattern(word):
    # Tek yönlü: listedeki Türkçe harf, mesajdaki düz haliyle de eşleşir ('şeftali' <- 'seftali'),
    # ama mesajdaki Türkçe harf yalnızca kendisiyle eşleşir ('sik' yasakken 'sık' serbest).
    return "".join(f"[{c}{_PLAIN[c]}]" if c in _PLAIN else re.escape(c) for c in normalize(word))


@functools.cache
def _matcher(word, match):
    """Bir mesajda kelimeyi arayan fonksiyon; bulursa bulduğu metni, bulamazsa None döndürür."""
    if match == "exact":  # yazıldığı gibi: yalnızca büyük/küçük harf farkı yok sayılır ('oç' yasakken 'oc' ve 'oçç' serbest)
        pattern = re.compile(r"(?<!\w)" + re.escape(_lower(word)) + r"(?!\w)")
        return lambda text: (m := pattern.search(_lower(_EMOTE.sub(" ", text)))) and m.group()
    pattern = re.compile(_pattern(word))
    if match == "anywhere":  # başka kelimenin içinde de
        return lambda text: (m := pattern.search(normalize(text))) and m.group()
    return lambda text: next((t for t in _WORD.findall(normalize(text)) if pattern.fullmatch(t)), None)  # variants


_SEVERITY = {"delete": 0, "standard": 1, "timeout": 2, "ban": 3}


def blacklist_hit(text, words, allowed=()):
    """words: ayardaki kelime kayıtları. Mesajda geçen kayıtlardan cezası en ağır olanı ve bulunan metni döndürür:
    (kayıt, metin) ya da None. Eşitlikte listede önce gelen seçilir.
    allowed: serbest kelimeler; mesajda yazıldığı gibi (harf sıkıştırmadan) geçiyorsa aramadan önce metinden çıkarılır."""
    ok = {_lower(a.strip()) for a in allowed}
    text = re.sub(r"\w+", lambda m: " " if _lower(m.group()) in ok else m.group(), text) if ok else text
    hits = [(w, found) for w in words if w["word"].strip() and (found := _matcher(w["word"].strip(), w["match"])(text))]
    return max(hits, key=lambda h: _SEVERITY[h[0]["action"]], default=None)


def blacklist_action(count, strikes, action="standard"):
    """Mesaj her durumda silinir; dönen değer ek cezadır. 'standard' kullanıcının toplam ihlaline (count) göre tırmanır."""
    if action != "standard":
        return action
    return "delete" if count < strikes else "timeout" if count == strikes else "ban"


_VOWELS = re.compile("[aeiou]")  # Türkçe harfler _PLAIN ile sadeleştikten sonra


def _words(text):
    """Mesajın kelimeleri: noktalama atılır, Türkçe harfler sadeleşir, emote ve harf uzatma fark etmez."""
    return re.findall(r"\w+", normalize(text).translate(str.maketrans(_PLAIN)))


def _same(a, b):
    """Kelimeyi sessiz harfleri belirler ('geldin' ~ 'geledin', 'mo' ~ 'mu'): sesliler çıkarılınca aynı kalanlar, uzun kelimelerde (4+ sessiz) %80 ve üstü benzeyenler de aynı sayılır."""
    ka, kb = _VOWELS.sub("", a) or a, _VOWELS.sub("", b) or b  # sesliden ibaret kelime kendisiyle kıyaslanır
    return ka == kb or (min(len(ka), len(kb)) > 3 and difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.8)


def similarity(a, b):
    """İki mesajın kelime benzerliği, 0-100 (eşleşen kelime / toplam kelime). Kelime sırası fark etmez."""
    x, y = _words(a), _words(b)
    if not x or not y:
        return 0
    left, matched = list(y), 0
    for w in x:  # her kelime diğer mesajda henüz eşleşmemiş benzer bir kelimeyle eşlenir
        i = next((i for i, v in enumerate(left) if _same(w, v)), None)
        if i is not None:
            del left[i]
            matched += 1
    return round(200 * matched / (len(x) + len(y)))


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
