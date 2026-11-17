# kick-bot

Kick chatinde **kendi hesabınla** çalışan moderasyon botu. Ayrı bir bot hesabı yoktur: mesajı silen, timeout atan ya da
duyuru yazan sen görünürsün. Bot senin bilgisayarında çalışır, yönetim paneli tarayıcıda açılır.

## Ne yapar

- **Yasaklı kelime:** mesajı siler. Her kelime için eşleşme türünü (birebir, türevleriyle, her yerde) ve cezayı
  (standart, yalnızca sil, doğrudan timeout, doğrudan ban; kelimeye özel süreyle) ayrı seçebilirsin. Standart ceza
  ayarladığın ihlalde timeout, sonrakinde ban atar. `şeftali` yazman yeterli:
  `seftali`, `ŞEFTAAALİ`, `ş e f t a l i`, `seftal1` de yakalanır.
- **Serbest kelimeler:** `oc` yasakken `ooc` gibi yazıldığı gibi serbest bıraktığın kelimeler yakalanmaz.
- **Sayaç azalması:** ihlal sayacı her kullanıcıda 30 dakikada (ayarlanır) 1 azalır.
- **Geçici moderatörler:** yazdığın kişiler bir mesajı `!sil`, `!to` gibi komutla cevaplayınca bot o işlemi yapar ve
  "kim istedi" diye kaydeder.
- **Başka moderatörler:** onların sildiği mesajlar ihlal sayacına eklenir, timeout ve ban'leri kayda geçer.
- **Hedefliyse yasak kelime:** kelime tek başına serbesttir, birine yöneltilmişse inceleme listesine düşer.
- **Caps:** art arda tamamı büyük harf yazana timeout atar.
- **Etiket:** biri seni `@nick` ile etiketlerse son mesajlar inceleme listesine düşer.
- **Komutlar:** biri `!abone` gibi bir komut yazınca bot onu etiketleyerek ayarladığın cevabı yazar.
- **Duyurular:** yalnızca yayın açıkken, rastgele sırayla, ayarladığın aralıklarla chate yazılır; istediğin duyuruyu kutusunu kaldırıp kapatabilirsin.
- **Kullanıcılar:** kimin kaç mesajı silindi, kaç kez timeout ve ban aldı, güncel ihlal sayacı kaç.
- **İnceleme:** botun yaptığı her şey kanıt mesajlarıyla kayıtlıdır; oradan mesaj silebilir, timeout ya da ban atabilir,
  cezayı kaldırabilirsin.
- Moderatörler, VIP'ler ve yayın sahibi kurallardan muaftır.

## Kurulum

### Windows

1. [Releases](../../releases/latest) sayfasından `kick-bot.exe` dosyasını indir.
2. Çift tıkla. İlk açılışta Windows "Windows kişisel bilgisayarınızı korudu" uyarısı gösterebilir:
   **Ek bilgi → Yine de çalıştır**.
3. Tarayıcıda panel açılır. **Kurulum** sayfasındaki üç adımı izle.

### Linux

```sh
curl -fsSL https://raw.githubusercontent.com/caferozpinar/KickChatbot/main/install.sh | sh
```

Sonra uygulama menüsünden **kick-bot**'u aç.

## Kullanım

- Uygulamayı açınca panel `http://localhost:8765` adresinde açılır. Panele yalnızca bu bilgisayardan ulaşılır.
- Sağ üstteki **Başlat / Durdur** düğmesi botu çalıştırır ya da bekletir.
- Bot **Yazdırma modu**nda başlar: hiçbir şeyi silmez, yalnızca ne yapacağını kaydeder. Sonuçlardan emin olunca
  Genel sayfasından kapat.
- Tarayıcı sekmesini kapatmak botu durdurmaz. Tamamen kapatmak için Genel → **Uygulamayı kapat**.
- Güncellemek için yeni sürümü indirip eskisinin yerine koy; ayarların silinmez.

Ayarların ve kayıtların durduğu yer: Windows'ta `%APPDATA%\kick-bot`, Linux'ta `~/.local/share/kick-bot`.

## Bilinmesi gerekenler

- Chat, Kick sitesinin kendi bağlantısından okunur; bu resmi bir yol değildir. Kick değiştirirse okuma durur ve
  düzeltme yeni sürümle gelir. Silme, timeout, ban ve duyurular resmi Kick API'sinden gider.
- Client Secret ve giriş bilgin yalnızca kendi bilgisayarında saklanır. Kimseyle paylaşma.
- **Model** sayfası isteğe bağlıdır ve kapalı gelir. Açmak için bilgisayarında [Ollama](https://ollama.com) kurulu
  olmalıdır.

## Geliştirme

```sh
pip install -r requirements.txt
python -m bot                        # panel: http://localhost:8765
python -m unittest discover tests
```

Yeni sürüm: `git tag v1.0.0 && git push --tags`. GitHub Actions Windows ve Linux dosyalarını derleyip Releases
sayfasına koyar.

| Dosya | İş |
|---|---|
| `bot/listener.py` | Chat okuma (Kick sitesinin websocket'i) |
| `bot/kick.py` | Resmi API: giriş, mesaj, silme, timeout, ban |
| `bot/rules.py` | Kurallar: yasaklı kelime, caps, muafiyet |
| `bot/moderation.py` | Her mesaja kuralları uygular |
| `bot/announcer.py` | Duyurular |
| `bot/llm.py` | İsteğe bağlı yerel model |
| `bot/db.py` | Kayıtlar ve sayaçlar (SQLite) |
| `bot/panel.py`, `bot/panel.html` | Yönetim paneli |

Lisans: MIT
