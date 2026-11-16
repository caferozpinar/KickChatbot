# Elle test cümleleri

İkinci hesaptan chate yaz. Kelime listesi `config.json` içindeki test listesidir:
her zaman yasak `yarrak`, `orospu` (her yerde), `şeftali`; hedefliyse yasak `amk`, `salak`, `aptal`, `gerizekalı`, `mal`.

Her bölümden önce paneldeki İnceleme sayfasından "Sayaçları sıfırla" yap, yoksa 4. ihlalde ban atılır.

## 1. Her zaman yasak (mesaj silinir, sayaç artar)

| Mesaj | Beklenen |
|---|---|
| şeftali | silinir |
| bugün seftali yedim | silinir (Türkçe harfsiz) |
| ŞEFTAAALİ | silinir (büyük harf, uzatma) |
| ş e f t a l i | silinir (boşluklu) |
| s.e.f.t.a.l.i | silinir (noktalı) |
| seftal1 | silinir (rakamla) |
| orospuluk yapma | silinir (her yerde) |
| yarrrrak | silinir |
| şeftaliler güzel | kalır (tam kelime, ekli hali yakalanmaz) |
| sftali | kalır (sesli harf düşürme yakalanmaz) |
| şef talimat verdi | kalır |

Üç silmeden sonraki ihlalde timeout, ondan sonrakinde ban gelir. Ban'ı denemek istemiyorsan 3. ihlalde dur.

## 2. Hedefliyse yasak: kişiye yönelik (model açıkken silinir, ceza kararı İnceleme'ye düşer)

| Mesaj | Beklenen |
|---|---|
| @Charasy sen tam bir salak | ihlal |
| ahmet senin ben amk | ihlal |
| bu yayıncı gerizekalı ya | ihlal |
| chatteki herkes aptal | ihlal |
| sen mal mısın | ihlal |
| (başka birinin mesajından hemen sonra) aptal | ihlal (önceki mesaja cevap) |

## 3. Hedefliyse yasak: kişiye yönelik değil (mesaj kalır)

| Mesaj | Beklenen |
|---|---|
| amk bugün çok yoruldum | kalır |
| amk yine öldüm | kalır |
| ben ne salak adamım ya | kalır (kendine) |
| bu oyun aptal bir oyun | kalır (oyuna) |
| mal alıp satıyorum | kalır (hakaret değil) |
| ne gerizekalı bir bölüm tasarımı | kalır (duruma) |

Model kapalıysa 2. ve 3. bölümdeki bütün mesajlar ceza almadan İnceleme sayfasına düşer.

## 4. Caps

| Mesaj | Beklenen |
|---|---|
| 5 kez art arda: NE DİYORSUN | 5. mesajda timeout |
| 4 kez NE DİYORSUN, sonra "tamam", sonra 4 kez daha | timeout yok (sayaç sıfırlandı) |
| GG | caps sayılmaz (kısa) |
| Selam MİLLET | caps sayılmaz |

## 5. Etiket

| Mesaj | Beklenen |
|---|---|
| @Charasy şu üstteki mesaja bakar mısın | son 5 mesaj İnceleme'ye düşer (model açıksa model yorumlar) |
