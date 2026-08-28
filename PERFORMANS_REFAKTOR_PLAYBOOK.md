# EHSİM V-Model Aracı — Performans Yeniden Yapılandırma Playbook'u

Bu dosya, projeyi devraldığınız stajyerlerden kalan haliyle çalışan ama performans
sorunları yaşayan **AI-V-Model-Tool-for-System-Engineers** (EHSİM) projesini,
Claude Code ile adım adım, güvenli ve ölçülebilir şekilde yeniden yapılandırmak
için hazırlanmış bir **prompt kütüphanesidir**. Her faz, doğrudan Claude Code'a
yapıştırabileceğiniz hazır bir talimat bloğu içerir.

Bu dosyayı projenin kök dizinine koyduk (`PERFORMANS_REFAKTOR_PLAYBOOK.md`).
Claude Code bu depoda çalışırken bu dosyayı her an okuyup referans alabilir.

## Nasıl kullanılır

1. Fazları **sırayla** uygulayın; bir fazı atlamak sonraki fazların güvenlik
   ağını (testler, ölçümler, plan onayı) zayıflatır.
2. Her faz için ayrı bir git dalı açın (`refactor/faz-06-mimari` gibi) ve fazı
   bitirdiğinizde commit'leyin. Böylece bir faz sorun çıkarırsa geri almak
   tek komutluk bir iş olur.
3. "PLAN MODU" ibaresi geçen fazlarda önce Claude Code'un sadece bir plan
   üretmesini isteyin, kod değişikliğine onaydan sonra geçin.
4. Her fazın sonunda `pytest tests/ -q` çalıştırın; mevcutken geçen testler
   fazdan sonra da geçmeli. Kırılan bir test "performans iyileştirmesi" olarak
   kabul edilmez.
5. Acele ediyorsanız dosyanın en altındaki **"Tek komutla otomatik yürütme"**
   promptunu kullanabilirsiniz — Claude Code bu playbook'u kendisi okuyup
   fazları sırayla, her fazdan sonra sizden onay isteyerek uygular.

---

## Genel kurallar (her promptun başında geçerli sayılır)

Aşağıdaki kurallar tüm fazlar için geçerlidir; her fazın promptu bunları
zaten hatırlatır ama toplu görünüm için burada listelendi:

- Mevcut davranış/işlevsellik bozulmayacak. Her değişiklikten sonra uygulama
  gerçekten çalıştırılabilir olmalı.
- Küçük, gözden geçirilebilir adımlar halinde ilerle; tek seferde onlarca
  dosyayı değiştirme.
- Kod silmeden/taşımadan önce o koda yapılan tüm referansları (import,
  çağrı) ara ve listele.
- `.venv/`, `HuggingFaceEmbeddings/`, `rag_chroma_lms/`, `outputs/`,
  `output/`, `tmp/`, `__pycache__/`, `repomix-output.xml` gibi üretilmiş/ikili
  veri veya bağımlılık dizinlerine kaynak kod gibi davranma; bunlar veri/artefakt
  olarak ele alınmalı, elle düzenlenmemeli.
- Türkçe alan terminolojisini (değişken/fonksiyon adlarındaki `donanim_`,
  `etki_analizi_`, `mimari_cerceve_` gibi önekler) yeniden adlandırma o fazın
  açık hedefi değilse koru.
- Performans iyileştirme iddiası sayı ile desteklenmeli (ms, MB, çağrı sayısı);
  "daha hızlı olmalı" gibi varsayımlarla yetinme, ölç.

---

## Proje envanteri (referans — doğrulanmış bulgular)

Claude Code'un tekrar keşfetmesine gerek kalmasın diye çıkarılan özet:

- **Yığın:** Python 3.12, GUI: `tkinter` + `ttkbootstrap` + `tkinterdnd2`
  (sürükle-bırak), veri: `pandas`/`numpy`, PDF: `PyMuPDF`/`pypdf`, çıktı
  üretimi: `reportlab` (PDF), `openpyxl` (Excel), `python-docx`/`docxtpl`
  (Word), RAG: `langchain` + `langchain-chroma` + `sentence-transformers` +
  `chromadb`, LLM erişimi: yerel **LM Studio** (OpenAI uyumlu API,
  `http://localhost:1234/v1`, model `google_gemma-3-4b-it`) üzerinden
  `requests` ile HTTP.
- **Giriş noktaları:** `main.py` (CLI/toplu iz sürülebilirlik akışı) ve
  `Arayüz.py` (asıl GUI uygulaması, `root.mainloop()`).
- **Büyük/riskli dosyalar (tek dosyada onlarca sorumluluk barındıran
  "god-file" adayları):** `Arayüz.py` (~159 KB), `donanim_kartlari_ui.py`
  (~138 KB), `mimari_cerceve_ui.py` (~137 KB), `mimari_cerceve_yonetim.py`
  (~94 KB), `mimari_cerceve_model.py` (~89 KB), `etki_analizi_ui.py`
  (~80 KB), `etki_analizi_simulasyon.py` / `etki_analizi_simulasyon_ui.py`
  (~70 KB), `donanim_kartlari_algilama.py` (~68 KB), `mimari_cerceve_render.py`
  (~49 KB), `donanim_kartlari_yonetim.py` (~56 KB), `etki_analizi_degisim_paketi.py`
  (~60 KB), `etki_analizi_izlenebilirlik.py` (~43 KB), `llm_handler.py`
  (~42 KB, ağ + threading), `rag_handler.py` (~29 KB, Chroma/embedding).
- **Şüpheli ölü kod:** `Arayüz_yedek.py` (85 KB) — `Arayüz.py`'nin yedeği gibi
  duruyor, muhtemelen artık kullanılmıyor; doğrulanmalı ve muhtemelen silinmeli.
- **Threading zaten kısmen var:** `Arayüz.py` içinde LLM/donanım tarama gibi
  uzun işler `threading.Thread(...)` + `self.master.after(...)` deseniyle arka
  plana alınmış (20'den fazla yerde tekrarlanan, standart bir yardımcıya
  çıkarılmamış aynı desen). `llm_handler.py`'de `requests.post(..., timeout=
  (3.05, 180))` ile 180 saniyeye kadar bekleyen senkron çağrılar var.
- **RAG:** `rag_handler.py` embedding'leri tembel (lazy) başlatıyor ve
  Chroma veritabanını `_load_existing_database()` ile birden fazla çağrı
  noktasından yükleyebiliyor — tekilleştirme (singleton) garantisi net değil.
  `config.py`'de `CHUNK_SIZE = 4000`, `CHUNK_OVERLAP = 50`.
- **Depo hijyeni:** `repomix-output.xml` (3.5 MB, üretilmiş/statik bir bağlam
  dökümü — .gitignore'da yok), `.gitignore` içinde `chroma_db/` yazıyor ama
  gerçek klasör adı `rag_chroma_lms/` — isim uyuşmazlığı var, vektör veritabanı
  yanlışlıkla izlemeye girmiş olabilir. `HuggingFaceEmbeddings/` (yerel embedding
  model ağırlıkları) `.gitignore`'da değil. `requirements.txt`'de **hiçbir paket
  sürüm sabitlemesi (pin) yok** — `langchain`/`chromadb` ekosisteminde bu, sessiz
  kırılan güncellemeler riski taşır.
- **Testler:** `tests/` klasöründe ciddi miktarda mevcut test var (`donanim_*`,
  `etki_analizi_*`, `mimari_cerceve_*`, `hardware_*`, `rag_handler_fallback`,
  `lmstudio_model`, `app_identity` — bazıları `test_mimari_cerceve_ui.py` ~83 KB
  gibi oldukça kapsamlı). Bu, "sıfırdan test yaz" değil, "mevcut testleri
  güvenlik ağı olarak kullan ve eksik kritik alanları tamamla" fazını mümkün
  kılıyor. `tests/` içinde ayrıca `.__*` / `.___*` gibi 4096 baytlık, muhtemelen
  macOS AppleDouble kalıntısı çöp dosyalar var (`.gitignore`'da `._*` zaten
  hariç tutulmuş, yine de fiziksel temizlik gerekebilir).
- **Belge üretim modülleri:** `*_generator_logic.py` dosyaları (TİD, DGÖYGÖ,
  DTET/YTET, KMTD, SGD, SİTET, STT, şablon) IEEE 15288 kapsamında farklı
  sistem mühendisliği belge türlerini üretiyor; bunlar `html_generation.py`,
  `hardware_export_logic.py` gibi modüllerle birlikte çıktı katmanını oluşturuyor.

---

## Faz 0 — Oryantasyon ve Proje Belleği (`CLAUDE.md` oluştur)

**Amaç:** Claude Code'un her oturumda projeyi yeniden keşfetmesini önlemek
için kalıcı bir proje belleği oluşturmak.

```
Bu depoyu (AI-V-Model-Tool-for-System-Engineers / EHSİM) baştan sona keşfet:
README.txt, MIMARI_CERCEVE_TASARIM.md, COMFYUI_KURULUM.md, requirements.txt,
config.py, main.py dosyalarını oku; Arayüz.py, llm_handler.py, rag_handler.py,
data_processor.py dosyalarının importlarına ve üst düzey fonksiyon/sınıf
tanımlarına bak (tamamını satır satır okumana gerek yok).

Bulgularınla kök dizinde bir CLAUDE.md dosyası oluştur. İçinde şunlar olsun:
- Projenin ne işe yaradığı (IEEE 15288 tabanlı sistem mühendisliği belge
  üretim/izlenebilirlik aracı, yerel LLM ile çalışıyor)
- Çalıştırma talimatları: Python 3.12, .venv kurulumu, LM Studio'nun açık ve
  google_gemma-3-4b-it modelinin yüklü olması gerektiği, `python Arayüz.py`
  ile GUI'nin, `python main.py` ile toplu/CLI akışın başlatıldığı
- Dizin/dosya haritası: hangi *_ui.py / *_logic.py / *_yonetim.py / *_model.py
  dosyasının hangi iş alanına (donanim_kartlari, etki_analizi, mimari_cerceve,
  hardware_image_*, rag, llm) ait olduğu
- Bilinen risk alanları: en büyük/karmaşık dosyaların listesi (bu playbook'un
  "Proje envanteri" bölümünden al) ve Arayüz_yedek.py'nin durumu
- Test komutu: `pytest tests/ -q` ve mevcut kapsamın nerede güçlü/zayıf olduğu
- Dokunulmaması gereken dizinler: .venv/, HuggingFaceEmbeddings/,
  rag_chroma_lms/, outputs/, output/, tmp/, __pycache__/
- Yapılandırma: config.py'deki ortam değişkenleri (EHSIM_LM_MODEL,
  EHSIM_IMAGE_* vb.) ve varsayılan değerleri

Bu dosyayı gelecekteki her Claude Code oturumunun otomatik okuyacağı bir proje
belleği olarak yaz (kısa, madde işaretli, 1-2 sayfayı geçmesin).
```

---

## Faz 1 — Çalıştırılabilirlik ve Temel Çizgi (baseline) Doğrulaması

**Amaç:** Refactor'a başlamadan önce "şu an ne çalışıyor, ne çalışmıyor"u
netleştirmek. Bir sonraki fazlarda kırılan bir şeyin refactor'dan mı, yoksa
zaten var olan bir sorundan mı kaynaklandığını ayırt edebilmek için şart.

```
requirements.txt'teki bağımlılıkları .venv içine kur (zaten kurulu değilse).
Ardından:
1. `pytest tests/ -q` çalıştır; geçen/kırılan/atlanan (skip) test sayılarını
   ve kırılan testlerin isimlerini kaydet.
2. Uygulamayı başlatmayı dene (LM Studio çalışmıyorsa bile en azından GUI'nin
   açılıp açılmadığını, importların patlayıp patlamadığını kontrol et).
3. Bulduğun her "zaten kırık" durumu (test veya çalışma zamanı hatası) ayrı
   ayrı listele — bunlar bu playbook'un konusu değil, ama ileride bir
   refactor'ın sebep olduğu yeni bir kırılmayla karıştırılmamaları için not
   düşülmeli.
4. Bu bulguları kök dizinde BASELINE.md adlı bir dosyaya yaz (tarih, pytest
   çıktısı özeti, bilinen sorunlar listesi).
Kod değişikliği yapma, sadece raporla.
```

---

## Faz 2 — Performans Ölçüm Altyapısı ve Profilleme

**Amaç:** "Neresi yavaş" sorusunu tahmine değil ölçüme dayandırmak. Bu fazdan
çıkan rapor, sonraki fazların önceliklerini belirleyecek.

```
Amacımız uygulamanın gerçekte nerede zaman/kaynak harcadığını ölçmek, tahmin
etmemek. Şunları yap:

1. cProfile veya py-spy / pyinstrument ile aşağıdaki akışları ayrı ayrı
   profille (gerekiyorsa geçici, commit'lenmeyecek bir scripts/profiling/
   klasörü altında küçük harness script'leri yaz):
   a) Uygulama açılışı (Arayüz.py import + ilk pencere açılana kadar)
   b) RAG veritabanı yükleme (rag_handler.py _load_existing_database / build)
   c) Donanım kartları listesi/algılama akışı (donanim_kartlari_algilama.py,
      donanim_kartlari_ui.py liste render'ı)
   d) Mimari çerçeve render/görünüm akışı (mimari_cerceve_render.py,
      mimari_cerceve_gorunumleri.py)
   e) Bir belge üretim akışı uçtan uca (PDF okuma -> LLM çağrısı -> HTML/
      Excel/Word çıktı üretimi)
2. Her akış için en çok zaman/bellek tüketen ilk 10 fonksiyonu/dosyayı,
   yaklaşık süreleriyle birlikte tablo halinde raporla.
3. UI donmalarına (Tkinter ana thread bloklanması) özellikle dikkat et: hangi
   çağrılar arka plan thread'inde değil de ana thread'de çalışıyor ve
   `master.after`/`mainloop`'u bekletiyor, bunu ayrı bir listede belirt.
4. Bulguları kök dizinde PERFORMANS_RAPORU_BASLANGIC.md dosyasına yaz. Bu
   rapor, hangi fazın (7, 8, 9, 10) en yüksek öncelikli olduğuna karar
   vermemiz için kullanılacak.

Henüz kod değişikliği/optimizasyon yapma, sadece ölç ve raporla.
```

---

## Faz 3 — Statik Risk Haritası (karmaşıklık, tekrar, ölü kod)

**Amaç:** Hangi dosyaların yeniden yapılandırmaya en çok ihtiyacı olduğunu
nesnel ölçütlerle sıralamak.

```
1. radon (cc ve mi) veya benzeri bir araçla (yoksa `pip install radon
   --break-system-packages` ile kur, ya da basitçe satır sayısı + fonksiyon
   sayısı + en uzun fonksiyonun satır sayısı ile) repodaki tüm .py dosyalarını
   karmaşıklığa göre sırala. Özellikle şu dosyalara odaklan: Arayüz.py,
   donanim_kartlari_ui.py, mimari_cerceve_ui.py, mimari_cerceve_yonetim.py,
   mimari_cerceve_model.py, etki_analizi_ui.py, etki_analizi_simulasyon.py,
   etki_analizi_simulasyon_ui.py, donanim_kartlari_algilama.py.
2. Arayüz.py ile Arayüz_yedek.py'yi karşılaştır (diff). Arayüz_yedek.py'nin
   gerçekten kullanılmayan bir yedek dosya mı yoksa hâlâ bir yerden import
   edilen/referans verilen bir dosya mı olduğunu kesin olarak doğrula (grep ile
   tüm importları tara). Sonucu ve önerini raporla (sil / arşivle / tut).
3. Her iş alanı için (donanim_kartlari_*, etki_analizi_*, mimari_cerceve_*)
   *_logic.py / *_ui.py / *_yonetim.py / *_model.py dosyaları arasındaki
   bağımlılıkları (kim kimi import ediyor) basit bir metin/ASCII bağımlılık
   grafiği olarak çıkar. Döngüsel bağımlılık var mı özellikle belirt.
4. Bulguları RISK_HARITASI.md dosyasına yaz: en riskli 10 dosya, gerekçesi ve
   önerilen aksiyon (böl / sadeleştir / test ekle / dokunma).

Kod değişikliği yapma, sadece analiz ve rapor.
```

---

## Faz 4 — Depo ve Bağımlılık Hijyeni

**Amaç:** Performans ve sürdürülebilirliği doğrudan etkileyen depo/ortam
sorunlarını (şişkinlik, sürüm belirsizliği, yanlış .gitignore eşlemesi) gidermek.

```
1. .gitignore dosyasını gözden geçir: `chroma_db/` yazıyor ama gerçek RAG
   veritabanı klasörü `rag_chroma_lms/`. Bu eşleşmeyi düzelt (doğru klasör
   adını ekle) ve klasörün şu anda git tarafından izlenip izlenmediğini
   `git status`/`git ls-files` ile kontrol et; izleniyorsa `git rm -r --cached`
   ile izlemeden çıkar.
2. repomix-output.xml (~3.5 MB, üretilmiş statik bağlam dökümü) dosyasının
   git tarafından izlenip izlenmediğini kontrol et. İzleniyorsa .gitignore'a
   ekle ve depodan çıkar (dosyayı silme, sadece git takibinden çıkar);
   projeye "gerektiğinde repomix ile yeniden üretilir" notunu README veya
   CLAUDE.md'ye ekle.
3. HuggingFaceEmbeddings/ (yerel embedding model ağırlıkları) klasörünün
   boyutunu ve git durumunu kontrol et; büyükse ve izleniyorsa .gitignore'a
   ekle, README/CLAUDE.md'ye "bu klasör X'ten indirilir" notu düş.
4. requirements.txt'teki tüm paketler için sürüm sabitleme (>=x,<y veya ==x)
   ekle; özellikle langchain, langchain-community, langchain-huggingface,
   langchain-chroma, chromadb, sentence-transformers gibi hızlı değişen
   paketler için. Şu an kurulu olan sürümleri `pip freeze` ile tespit edip
   pin değeri olarak kullan (böylece "çalışan" sürüm sabitlenmiş olur).
5. tests/ klasöründeki 4096 baytlık `.__*` / `.___*` / `._*` dosyalarının
   (muhtemelen macOS AppleDouble kalıntıları) fonksiyonel bir amacı olup
   olmadığını doğrula, yoksa temizle.
6. Arayüz_yedek.py için Faz 3'te verilen karara göre aksiyon al (sil/arşivle).

Her adımdan sonra `pytest tests/ -q` çalıştır, hiçbir testin bu temizlikten
etkilenmediğini doğrula. Değişiklikleri küçük, açıklayıcı commit'lere böl.
```

---

## Faz 5 — Güvenlik Ağını Güçlendirme (mevcut testleri genişlet)

**Amaç:** `tests/` klasöründe zaten ciddi bir kapsam var; bunu sıfırdan
yazmak yerine, refactor edilecek en kritik/performans açısından hassas
modüllerdeki boşlukları kapatmak.

```
tests/ klasöründeki mevcut testleri incele ve coverage.py ile
(`pip install pytest-cov --break-system-packages`, `pytest --cov=. tests/`)
modül bazında kapsam raporu çıkar.

Özellikle şu modüllerin genel davranışını (girdi -> çıktı sözleşmesi)
kilitleyen testlerin var olup olmadığını kontrol et, eksikse ekle:
- llm_handler.py (LM Studio isteklerinin nasıl kurulduğu, hata/timeout
  durumunda ne döndüğü — gerçek ağ çağrısı yapmadan, mock/monkeypatch ile)
- rag_handler.py (embedding başlatma, veritabanı yükleme/kaydetme,
  _load_existing_database'in birden çok çağrıda aynı örneği kullanıp
  kullanmadığı)
- data_processor.py (process_tid_data_batch / process_tid_data'nın küçük
  örnek bir DataFrame üzerinde ürettiği çıktı)
- Arayüz.py içindeki, Faz 7-8'de yeniden yapılandırılacak arka plan
  thread + master.after desenini kullanan en az 2-3 kritik akış (örn. sohbet
  gönderme, belge üretimi tetikleme) — burada gerçek Tkinter penceresi
  açmadan mantığı test edebileceğin şekilde (fonksiyonu UI'dan ayırarak ya da
  mock master ile) bir yaklaşım öner.

Bu testler, ileride yapacağımız bölme/optimizasyon refactor'larının
davranışı bozmadığını doğrulayacak "karakterizasyon testleri" rolünü
görecek. Var olan test stilini (fixture, mock kullanımı vb.) takip et.
```

---

## Faz 6 — Mimari Yeniden Yapılandırma Planı (PLAN MODU — henüz kod yazma)

**Amaç:** "Projenin en baştan yapılandırılması" isteğinin çekirdeği burası.
Devasa tekil dosyaları (`Arayüz.py`, `donanim_kartlari_ui.py`,
`mimari_cerceve_ui.py` vb.) sürdürülebilir bir paket yapısına taşımanın planı.

```
Şimdilik HİÇBİR dosyayı değiştirme veya taşıma — sadece bir plan yaz ve
onay bekle.

Mevcut düz (flat) dosya yapısı, her iş alanı için zaten örtük bir
*_logic / *_ui / *_yonetim / *_model ayrımı içeriyor ama hepsi kök dizinde
tek tek dev dosyalar halinde duruyor (Arayüz.py 159 KB dahil). Şunu planla:

1. Kök dizini bir Python paketine (örn. ehsim/) taşımadan önce, bunun
   gerçekten gerekli mi yoksa mevcut düz yapıda kalıp sadece dosyaları
   bölmenin mi (örn. donanim_kartlari_ui.py -> donanim_kartlari/ui_liste.py,
   donanim_kartlari/ui_detay.py, donanim_kartlari/ui_karsilastirma.py gibi
   alt modüllere bölme) daha az riskli olacağını değerlendir; artıları/
   eksileriyle iki seçeneği de yaz, birini öner.
2. Önerilen yapı ne olursa olsun, her iş alanı (donanim_kartlari,
   etki_analizi, mimari_cerceve, hardware_image_*, rag, llm, ortak/çekirdek
   UI yardımcıları) için hedef klasör/dosya haritasını çıkar.
3. Arayüz.py'nin (159 KB) hangi sorumlulukları taşıdığını listele (pencere
   kurulumu, sekme/panel yönetimi, sohbet, belge üretimi tetikleme, donanım
   kartları entegrasyonu, mimari çerçeve entegrasyonu vb.) ve bunları hangi
   alt modüllere ayırabileceğimizi öner. Amaç: Arayüz.py'yi ince bir
   "orkestrasyon/pencere kurulumu" katmanına indirgemek, iş mantığını ve alt
   panel UI'larını kendi dosyalarına taşımak.
4. Geriye dönük uyumluluk: main.py ve mevcut importlar (from X import Y)
   kırılmayacak şekilde, taşıma sırasında hangi sırayla ilerlenmesi
   gerektiğini (bağımlılık sırasına göre, önce yaprak modüller) planla.
5. Her adımın ayrı bir commit/PR olacağı, aralarında `pytest tests/ -q`
   çalıştırılacağı bir uygulama sırası (roadmap) öner.

Planı MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md olarak yaz ve bana onay için sun.
Ben onaylamadan Faz 7'ye geçme.
```

---

## Faz 7 — Kademeli Uygulama Döngüsü (onaylanan planı hayata geçir)

**Amaç:** Faz 6'da onaylanan planı, tek seferde değil, modül modül,
her adımda test edilerek uygulamak. Bu prompt her modül için tekrar kullanılır.

```
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md'de onaylanmış plana göre şu tek modülü
uygula: [BURAYA modül adını yaz, örn. "donanim_kartlari_ui.py"].

Kurallar:
1. Önce bu dosyaya yapılan tüm importları/referansları grep ile bul ve listele.
2. Dosyayı plandaki hedef alt modüllere böl / taşı; her yeni dosyanın tek ve
   net bir sorumluluğu olsun.
3. Tüm eski import yollarını güncelle; hiçbir çağıran kod kırılmasın.
4. Bölme sırasında davranışı DEĞİŞTİRME (bu bir refactor, bir "iyileştirme"
   fazı değil — performans/mantık değişiklikleri Faz 8-10'da yapılacak).
5. Bitirince `pytest tests/ -q` çalıştır; hepsi geçmeli. Ardından mümkünse
   uygulamayı açıp ilgili ekranı/akışı manuel olarak dumanlı test (smoke
   test) et.
6. Değişikliği tek, açıklayıcı bir commit mesajıyla özetle (ne taşındı, ne
   değişmedi).

Bu modül bitince durup bana rapor ver; onayımdan sonra plandaki bir sonraki
modüle geçeceğiz.
```

---

## Faz 8 — Arayüz (Tkinter) Katmanı Performans İyileştirmesi

**Amaç:** UI donmaları ve gereksiz yeniden çizimleri gidermek; dağınık
threading desenini standartlaştırmak.

```
Arayüz.py ve donanim_kartlari_ui.py / mimari_cerceve_ui.py / etki_analizi_ui.py
gibi dosyalarda şu performans desenlerini ara ve iyileştir:

1. Standart bir arka plan çalıştırma yardımcısı oluştur (örn.
   `run_in_background(func, on_success, on_error)` gibi), threading.Thread +
   self.master.after ile tekrar eden ~20+ noktayı bu ortak yardımcıya taşı.
   Kilit noktalar: iptal edilebilirlik (kullanıcı yeni bir işlem başlattığında
   önceki devam eden thread'in sonucu artık UI'ya yazılmamalı — bir "iş
   token'ı/generation id" deseni kullan) ve hata yönetiminin tek yerde
   toplanması.
2. Liste/kart görünümlerinde (donanim kartları listesi, mimari çerçeve
   görünümleri) her veri değişiminde TÜM widget ağacının yeniden
   oluşturulup oluşturulmadığını kontrol et. Yeniden oluşturuluyorsa, sadece
   değişen satırları güncelleyecek ya da büyük listelerde sayfalama/lazy
   render uygulayacak şekilde değiştir.
3. Arama/filtre kutularına debounce ekle (her tuş vuruşunda değil, kullanıcı
   yazmayı bıraktıktan ~200-300ms sonra filtre uygula).
4. `update_idletasks()` / gereksiz `mainloop` içi senkron beklemeleri tespit
   et; UI'yi bloklayan hiçbir I/O veya ağ çağrısı ana thread'de kalmamalı.

Her değişiklikten sonra pytest'i ve ilgili ekranın manuel dumanlı testini
çalıştır. Öncesi/sonrası için Faz 2'deki profilleme yöntemiyle somut bir
karşılaştırma (ör. "N elemanlı liste render süresi X ms -> Y ms") çıkar.
```

---

## Faz 9 — LLM ve RAG Katmanı Performans İyileştirmesi

**Amaç:** LM Studio çağrılarını ve Chroma/embedding katmanını gereksiz
tekrar işten arındırmak.

```
llm_handler.py ve rag_handler.py'yi şu açılardan incele ve iyileştir:

1. requests.post çağrılarının her seferinde yeni bağlantı mı açtığını,
   yoksa bir requests.Session üzerinden bağlantı tekrar kullanımı (connection
   reuse) mı yaptığını kontrol et; Session kullanmıyorsa ekle.
2. Aynı prompt+model için tekrar eden LLM çağrılarını tespit et (varsa) ve
   basit bir bellek-içi (ya da disk tabanlı) önbellekleme ekle; bunun
   doğruluğu etkilemeyeceğinden emin ol (ör. sıcaklık/temperature 0 olmayan
   çağrılarda önbellekleme yanlış olabilir — dikkatli davran).
3. rag_handler.py'de _load_existing_database'in kaç farklı çağrı noktasından
   tetiklendiğini bul; Chroma veritabanının ve embedding modelinin süreç
   başına yalnızca BİR kez, gerçek bir tekil (singleton) olarak
   başlatıldığından emin ol.
4. config.py'deki CHUNK_SIZE (4000) / CHUNK_OVERLAP (50) değerlerinin tipik
   girdi belgeleri için kaç chunk ürettiğini ölç; aşırı sayıda küçük parça
   üretiliyorsa (gereksiz embedding çağrısı demektir) değerleri ölçüme göre
   ayarla.
5. USE_BATCH_PROCESSING/BATCH_SIZE mekanizmasının gerçekten LLM çağrı sayısını
   azalttığını (batch başına tek çağrı) doğrula; azaltmıyorsa düzelt.
6. Mümkünse, 180 saniyeye kadar sürebilen tekil cevap bekleme yerine
   streaming (LM Studio'nun OpenAI-uyumlu stream=True modu) ile UI'ya
   kademeli geri bildirim verme fizibilitesini değerlendir ve bir öneri
   sun (bu büyük bir değişiklikse önce plan olarak sun, onay bekle).

Her adımda gerçek bir LM Studio çağrısı gerektiren testleri mock'la; ağa
bağımlı olmayan testlerin pytest'te geçtiğinden emin ol.
```

---

## Faz 10 — Veri İşleme ve Dosya I/O Performansı

**Amaç:** PDF okuma, pandas işleme ve Excel/Word/PDF/HTML üretimindeki
verimsiz döngüleri gidermek.

```
data_processor.py, pdf_extraction.py, html_generation.py,
hardware_export_logic.py dosyalarını incele:

1. pandas DataFrame üzerinde satır satır `iterrows()`/`apply(axis=1)` ile
   yapılan ve vektörleştirilebilecek (vectorize edilebilecek) işlemleri
   tespit et, vektörleştir.
2. Aynı PDF'in bir oturum içinde birden fazla kez okunup okunmadığını
   (PyMuPDF/pypdf ile tekrar parse) kontrol et; gerekiyorsa sonucu önbelleğe
   al.
3. openpyxl ile Excel üretiminde hücre hücre (cell-by-cell) yazma yerine
   toplu (bulk/row-by-row append) yazım kullanılıp kullanılmadığını kontrol
   et, gerekiyorsa optimize et.
4. html_generation.py'de string birleştirmenin (`+=` ile büyüyen string)
   büyük raporlarda O(n²) davranışa yol açıp açmadığını kontrol et; gerekiyorsa
   liste biriktirip `"".join(...)` ile veya bir şablon motoruyla değiştir.
5. Her bulgu için Faz 2'deki gibi öncesi/sonrası somut süre ölçümü çıkar.

pytest'i çalıştır, ardından uçtan uca bir belge üretim akışını manuel
dumanlı test et (PDF yükle -> üret -> PDF/Excel/Word/DOORS CSV indir).
```

---

## Faz 11 — Eşzamanlılık ve Paylaşılan Durum Güvenliği

**Amaç:** Ad-hoc thread'lerin paylaşılan durumu (self.db, self.embeddings,
modül seviyesi globaller) yarış koşuluna (race condition) sokmadığından ve
kaynakları sızdırmadığından emin olmak.

```
1. rag_handler.py'deki self.db / self.embeddings gibi paylaşılan durumun,
   hem ana thread hem de arka plan thread'lerinden yazılıp yazılmadığını
   tespit et. Yazma her zaman tek bir yerden (ya da bir kilitle korunarak)
   yapılmıyorsa düzelt.
2. Kullanıcı bir işlemi (LLM çağrısı, donanım taraması) bitmeden yenisini
   başlattığında, eski thread'in sonucu geç gelip UI'ya yanlış/eski veri
   yazıp yazmadığını kontrol et (Faz 8'deki "iş token'ı" deseniyle ilişkili).
   Bu senaryoyu tekrarlayan bir test veya manuel senaryo ile doğrula.
3. Uzun süren thread'lerin uygulama kapatılırken (pencere X'e basılınca)
   düzgün sonlandığını/iptal edildiğini, arkada asılı kalmadığını kontrol et.

Bulguları ve yapılan düzeltmeleri raporla; her düzeltmeden sonra pytest'i
çalıştır.
```

---

## Faz 12 — Son Doğrulama ve Öncesi/Sonrası Raporu

**Amaç:** Yapılan tüm işi tek bir ölçülebilir sonuçla kapatmak.

```
1. Faz 2'de kullandığın profilleme senaryolarının aynısını (açılış, RAG
   yükleme, donanım listesi render, mimari çerçeve render, uçtan uca belge
   üretimi) şimdi tekrar çalıştır.
2. PERFORMANS_RAPORU_BASLANGIC.md ile şimdiki sonuçları karşılaştıran bir
   PERFORMANS_RAPORU_SONUC.md yaz: her senaryo için öncesi/sonrası süre
   (ve varsa bellek) ile yüzde iyileşme.
3. `pytest tests/ -q` çalıştır ve BASELINE.md'deki sonuçlarla karşılaştır;
   yeni kırılan test olmadığını doğrula (Faz 1'de zaten kırık olanlar hariç).
4. Aşağıdaki manuel dumanlı test listesini uygula ve sonucunu raporla:
   uygulamayı aç, bir PDF sürükle-bırak, belge üret, donanım kartları
   ekranını aç, etki analizi simülasyonu çalıştır, mimari çerçeve görünümünü
   aç, PDF/Excel/Word/DOORS(CSV) olarak dışa aktar.
5. Faz 0'da oluşturduğun CLAUDE.md'yi, artık geçerli olan yeni dosya/paket
   haritasını yansıtacak şekilde güncelle.

Son olarak, tüm playbook boyunca yapılan değişikliklerin kısa bir özetini
(hangi faz, ne yapıldı, ölçülen etki) tek bir REFAKTOR_OZETI.md dosyasında
topla.
```

---

## Tek komutla otomatik yürütme (opsiyonel)

Fazları tek tek tetiklemek yerine Claude Code'a playbook'u kendi kendine
sırayla uygulattırmak isterseniz:

```
Kök dizindeki PERFORMANS_REFAKTOR_PLAYBOOK.md dosyasını oku. İçindeki
fazları (Faz 0'dan Faz 12'ye) sırayla uygula. Her fazı bitirdiğinde:
1. O fazda ne yaptığını kısaca özetle,
2. İlgiliyse pytest tests/ -q çıktısını paylaş,
3. Bir sonraki faza geçmeden önce benden açık onay iste — özellikle Faz 6
   (mimari plan) onayım olmadan ASLA kod değiştirmeye başlama.
Bir fazda test kırılırsa veya beklenmedik bir risk bulursan dur, bana
açıkla, onay almadan ilerleme.
```
