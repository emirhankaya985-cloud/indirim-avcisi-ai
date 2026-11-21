# İndirim Avcısı AI — Fiyat ve Kupon Takip Botu

**Durum:** Kod ve yerel testler hazırlanmıştır. Gerçek ürünler, bir kupon kaynağı, Telegram sırları ve GitHub zamanlayıcısı kullanıcı tarafından bağlanmadan **canlı değil**. Örnek/sahte fiyat veya kupon üretilmez.

## Neler yapar?

- Trendyol, Amazon TR, Hepsiburada ve n11'in **izin verdiği ve makine-okunabilir fiyat içeren** HTTPS ürün sayfalarını 30 dakika aralıklarla kontrol etmeyi dener.
- Ürünün ilk tespit edilen fiyatını **başlangıç seviyesi** olarak kaydeder; ilk taramada sahte indirim göndermez.
- Fiyat, bir önceki seviyeye göre istenen yüzdede düşer **ve** son 30 günün kayıtlı asgari fiyatından daha düşükse Telegram bildirimi sıraya alır. İndirim algılama yalnızca **kendi fiyat geçmişimize** dayanır; mağazanın indirim iddialarını doğrulamaz.
- Son 90 günlük fiyat değişim geçmişini takip eder, yinelenen bildirimleri azaltır, hatalarda bildirimleri sırada tutar.
- Konfigüre edilmiş **RSS/Atom kupon kaynaklarında** yeni kupon başlıklarını izler. Başlık bulunan yeni kayıtları yalnızca **"KUPON ADAYI (DOĞRULANMADI)"** olarak gönderir. Kuponun ödeme ekranında çalıştığını asla iddia etmez.
- Telegram API başarı/`message_id` döndürmeden bildirim gönderilmiş sayılmaz. Bu, mesajın telefonda açıldığını veya cihazın bildirimi aldığını kanıtlamaz. Başarısız gönderimler artan beklemeyle (30 dakika → 1 saat → 2 saat ... en fazla 24 saat) yeniden denenir; son 100 taramanın hata özeti tutulur. Kalıcı state dosyası GitHub Actions tarafından commit edilir.

## Hızlı kurulum (0 TL hedefi)

1. Kodu **mevcut Public GitHub deposuna**, örn. `emirhankaya985-cloud/indirim-avcisi-ai`, yükleyin. Bu ZIP kendi kendine bir repo veya cron oluşturmaz.
2. `config.json` içine izlenecek **gerçek ürün bağlantılarını** veya **gerçek RSS/Atom kupon akışlarını** girin. Örnek şema aşağıda. Fiyatı mağaza sayfasından otomatik çıkaramayan bağlantılar hata verir; e-ticaret siteleri otomasyon erişimini engelleyebilir.
3. GitHub deposunda **Settings → Secrets and variables → Actions → New repository secret** bölümünden `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` tanımlayın. Tokenı kaynak dosyalarına koymayın. Aynı isimli mevcut secretların başka projelerde olması bu yeni depoda otomatik çalışacağı anlamına gelmez.
4. **Settings → Secrets and variables → Actions → Variables** bölümünde `TRACKING_ENABLED=true` tanımlayın **yalnızca gerçek ürün/kupon kaynakları, Telegram sırları ve Actions bütçesi doğrulandıktan sonra**. Bu bayrak yokken 30 dakikalık workflow, runner ayırmadan atlanır (ücretli sürprizlerden kaçınmak için).
5. **Actions → Watch prices and coupon feeds → Run workflow** ile manuel bir çalışma başlatın. `data/state.json` ve run loglarını kontrol edin.
6. Telegram bağlantısını yerel bilgisayarda `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` ortam değişkenleriyle `python -m tracker test-telegram` komutuyla doğrulayabilirsiniz.
7. İlk fiyat ölçümü alarm üretmez; fiyat düştüğünde ikinci tarama ile test edin. Kupon akışı ilk okumada mevcut eski girdileri kaydeder, geçmiş girdileri topluca bildirmez.

**Gerçek 7/24 kesintisiz çalışma garantisi yok.** GitHub Actions 30 dk periyodik zamanlayıcıdır; yoğunlukta gecikebilir veya atlanabilir. GitHub planı, kota, depo gizliliği ve Actions kurallarına göre kullanım maliyetlerini denetleyin. **Public repo üzerindeki standart GitHub-hosted runner kullanımı ücretsizdir**; üçüncü taraf servisler, özel runner'lar veya ücretli özellikler maliyet doğurabilir. GitHub hesap faturalama bütçesini 0 USD üst sınırına getirmeden sıfır ücret garanti edilemez. GitHub docs: https://docs.github.com/en/billing/concepts/product-billing/github-actions ve https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows . Özel depoda ücretsiz kota dolabilir. Mağazanın robots.txt ve kullanım koşulları izin vermiyorsa otomatik sayfa okumayı zorlamayın; onun yerine resmi API/akış kullanın.

### `config.json` şeması

`products` dizisi içinde örnek (bu **gerçek ürün değil**, yer tutucudur):

```json
{
  "products": [
    {
      "id": "klavye01",
      "name": "Takip etmek istediğim klavye",
      "url": "https://www.trendyol.com/GERCEK-URUN-ADRESI",
      "currency": "TRY",
      "drop_percent": 5,
      "cooldown_hours": 24
    }
  ],
  "coupon_feeds": [
    {
      "id": "magaza-rss",
      "name": "İzinli kupon RSS kaynağı",
      "url": "https://MAGAZA-VEYA-YAYINCI-DOMAINI/AKIS.xml"
    }
  ]
}
```

Not: Bu adresler **örnek ve geçersizdir**. Gerçek link girin. `coupon_feeds` zorunlu değildir, kupon takibi isteniyorsa doldurulmalıdır. RSS/Atom olmayınca sistem kendi başına kupon kodu bulmaz. Trendyol resmi kupon sayfası (https://www.trendyol.com/s/mega-kuponlar) herkese açık **RSS akışı değildir**, bu nedenle sahte RSS URL tanımlanmadı; uygulama içi/kişiselleştirilmiş kuponlar haricî erişim olmadan otomatik doğrulanamaz.

## Komutlar

```bash
python -m unittest discover -s tests -v
python -m tracker run --dry-run
python -m tracker run
python -m tracker status
python -m tracker test-telegram
```

**Güvenlik:** Sadece HTTPS; ürünlerde izinli pazar yeri alanları; robot kuralları; yetkisiz/korumalı sayfaları aşma yok; otomatik satın alma yok; token loglama yok. Fiyatlar, gönderim durumları ve alarm geçmişi `data/state.json` içinde tutulur, mesajlar en az bir kez gönderim semantiğiyle çalışır (çok nadir commit kesintilerinde tekrar oluşabilir). Ödeme aşamasındaki kupon geçerliliği doğrulanamaz.

## Üretim kabul kontrol listesi

- [ ] Gerçek ürün URL'si ve gerçek izinli kupon kaynağı tanımlı
- [ ] İlk ürün fiyatı canlı sayfadan okunup `state.json` içine yazıldı
- [ ] Fiyat değişimi ölçüldü; gerçek fiyat düşüşü (eşik + son 30 gün dip fiyat) doğru bildirildi
- [ ] Kupon kaynağı aday bildirimi "doğrulanmadı" şeklinde iletti
- [ ] Telegram gerçek `message_id` ve `delivery_log` ile doğrulandı
- [ ] İki ardışık Actions scheduled run durumu ve state kalıcılığı doğrulandı
- [ ] GitHub Actions dakika kotası ve site robots/ToS uygunluğu kontrol edildi

Bu maddeler tamamlanmadan **🟢 çalışıyor** durumuna geçirilmez.

## Son geliştirme denetimi (2026-11-21)

- Yerel `python -m unittest discover -s tests -v`: **24/24 PASS** (ilk 16 ve 8 yeni test).
- Canlı ürünler: `config.json` şu anda **0 ürün**, canlı HTTP testi yapılmadı.
- Kupon akışları: **0 doğrulanmış izinli RSS/Atom kaynağı**. Başlık algılama yalnızca örnek veriyle test edildi.
- Telegram: `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` tanımlanmadan gerçek mesaj teslimi test edilemez. `message_id` Telegram API kabul kanıtıdır, mobil teslim/okunma kanıtı değildir.
- GitHub Actions: YAML hazır; `TRACKING_ENABLED=true` repository variable ile bilinçli etkinleştirme gerekir. Repo varsayılan dalına yüklenip **en az bir gerçek workflow run** yapılmadan çalışır olarak işaretlenmez.
- Ağ kısıtlaması: Hazırlama ortamındaki DNS erişimi başarısız, dolayısıyla Trendyol/Hepsiburada/Amazon TR ürün sayfalarına buradan canlı istek sonucu **yok**.

Sistem **cihaz kapalıyken tarama yapabilecek şekilde tasarlandı**; GitHub Actions schedule varsayılan dalda etkinleştirilmeden otomatik hizmet değildir. Site kuralları izin vermeyen ürünler otomatik olarak atlanır; robot veya CAPTCHA korumaları aşılmaz. Kuponlar yalnızca *aday* olarak iletilir. 48/gün tarama hedefidir, garanti değil.

## Neon PostgreSQL kalıcı saklama (21 Kasım 2026)

Kullanıcı Neon Free organizasyonunda bu proje için **ayrı** `indirim-avcisi-ai-free`
projesi, `indirim_avcisi` veritabanı, `tracker_state` ve `price_history`
tabloları oluşturuldu (`project_id=wispy-term-74990535`). Veritabanında
şimdilik hiç gerçek fiyat gözlemi yoktur; bir tablo oluşturulmuş olması
çalışan fiyat takibi anlamına gelmez.

GitHub Public depo Secrets bölümüne `NEON_DATABASE_URL` olarak **yalnızca Neon
Console'dan alınan** PostgreSQL bağlantı URL'sini ekleyin. Kaynak dosyaya veya
sohbete yazmayın. Secret varsa bot state'i Neon'dan okur ve **aynı transaction**
içinde `tracker_state` + `price_history` yazar; Neon hatasında yerel dosyaya
sessizce düşmez. Secret yoksa önceki sürümün Git `data/state.json` commit
kalıcılığı kullanılır. Neon sürücüsü `requirements.txt` üzerinden kurulur.

Saklanan tüm ürün bağlantılarının kaynağa ilişkin izinleri ve fiyat kanıtları
mağaza tarafından doğrulanmalıdır. Örnekleri `config.json` içine otomatik
eklerseniz bunlar kullanıcının kişisel ürünleri sayılır; tanılama örneklerini
buraya eklemeyin. Ortam dosyaları (`.env`), API anahtarları ve özel bağlantı
URL'leri `.gitignore` kapsamındadır. Telegram iletiminde başarılı `message_id`
yalnızca API kabulüdür, telefonda okundu kanıtı değildir.

**Açık sınırlama:** Mesajın Telegram tarafından kabulü ile kalıcı veritabanı
commit'i arasında iş kesilirse, nadiren aynı alarm bir kez daha gönderilebilir.
Bu sistem `at-least-once` teslim semantiği uygular.