# PERFORMANS RAPORU — SONUÇ (Faz 12)

**Tarih:** 2026-08-29
**Yöntem:** `PERFORMANS_RAPORU_BASLANGIC.md` (Faz 2) ile **aynı senaryolar**,
mümkün olduğunca aynı harness mantığıyla tekrar ölçüldü (`time.perf_counter`,
ayrı process, geçici script'ler — commit'lenmedi). Ortam: Windows 11, aynı
makine, LM Studio açık, `gemma-4-e4b-it` yüklü (`EHSIM_LM_MODEL` env
değişkeniyle ayarlandı — bkz. BASELINE.md model adı notu, hâlâ geçerli).

**Önemli metodolojik not:** Faz 2 ölçümleri **tek seferlik**ti; burada
mümkün olan senaryolarda 2-3 tekrar yapıldı. İki ölçüm arasında makine
durumu (disk önbelleği, arka plan süreçleri) birebir aynı değil — bu yüzden
"iyileşme" olarak raporlanan her sayı için **kod düzeyinde bir neden
gösterilebiliyorsa** iyileşme koda atfediliyor, gösterilemiyorsa bu açıkça
belirtiliyor (varsayım değil, ölçüm + kök neden eşleşmesi).

---

## a) Uygulama açılışı (`Arayüz.py` import + ilk pencere)

| Adım | Öncesi (Faz 2, 1 ölçüm) | Sonrası (Faz 12, 3 ölçüm ortalaması) |
|---|---|---|
| `import Arayüz` | 12.75 s | **8.80 s** (8.63–8.90 s) |
| `TIDGeneratorApp.__init__` | 2.95 s | **1.20 s** (1.20–1.21 s) |
| **Toplam** | **~15.7 s** | **~10.0 s** (9.84–10.10 s) |

**Değerlendirme:** ~%36 daha hızlı, ancak **bunu doğrudan bir koda
atfedemiyorum.** Faz 2'de kök neden olarak tespit edilen
`arayuz/yardimcilar.py:35` — `from langchain_huggingface import
HuggingFaceEmbeddings` — modül seviyesinde, koşulsuz import **hâlâ orada**
(grep ile doğrulandı, Faz 7-11 kapsamında hiçbir fazda ele alınmadı; Faz 2
raporu bunu Faz 8 için "ele alınabilir" bir fırsat olarak not düşmüştü ama
Faz 8'in fiili kapsamı yalnızca donanım kartları `deepcopy` düzeltmesiydi).
En olası açıklama: disk/OS dosya önbelleğinin bu ölçümde daha sıcak olması
(3 ardışık çalıştırma arasında süre neredeyse sabit kaldı — 9.84-10.10 s —
bu da ya gerçek bir iyileşme ya da tutarlı bir önbellek durumu olduğunu
gösteriyor, ayırt edemiyorum). **Açık madde:** torch/HuggingFaceEmbeddings
importunun tembelleştirilmesi hâlâ geçerli, ölçülmemiş bir fırsat.

---

## b) RAG veritabanı yükleme / tekillik (singleton)

| Adım | Öncesi | Sonrası |
|---|---|---|
| `RAGHandler()` → `_initialize_embeddings()` (1. çağrı) | 2.076 s | 2.054 s (fark yok — beklenen, bu süre LM Studio bağlantı testinin ağ gecikmesi, koddan bağımsız) |
| `_load_existing_database()` | 0.328 s | 0.122 s |
| **İkinci `RAGHandler()` çağrısı (main.py'den)** | **+2.082 s (tekrar!)** | **Yok — main.py artık `RAGHandler()` çağırmıyor** |

**Kök neden düzeltmesi doğrulandı:** Faz 9'da `main.py`'deki kullanılmayan
`RAGHandler()` başlatması kaldırıldı (kod incelemesiyle doğrulandı —
`main.py`'de yalnızca bunu açıklayan bir yorum satırı kaldı, gerçek çağrı
yok). Ayrıca çalışma zamanında `rag_module.rag_handler` nesnesinin her
erişimde **aynı nesne** olduğu doğrulandı (`is` karşılaştırması `True`).
Sonuç: bir uygulama çalıştırmasında RAG kurulum maliyeti **~4.16 s'den
~2.18 s'ye düştü (~%48 azalma)** — bu, ölçülmüş ve koda atfedilebilir bir
iyileşme.

---

## c) Donanım kartları listesi/algılama akışı (500 kart, `tests/_hardware_catalog_scale_qa.py`)

| Metrik | Öncesi (3 çalıştırma) | Sonrası (3 çalıştırma) |
|---|---|---|
| startup | 4.480 / 2.156 / 2.196 s | **1.272 / 1.317 / 1.320 s** |
| filter | 2.277 / 1.051 / 1.116 s | **0.614 / 0.662 / 0.680 s** |
| compact (500 satır) | **9.742** / 0.541 / 0.633 s | **0.291 / 0.316 / 0.313 s** |

Script'in kendi kabul eşiği `filter ≤ 0.75 s` — **öncesinde 3/3 çalıştırma
bu eşiği aşıp `RuntimeError` fırlatıyordu; sonrasında 3/3 çalıştırma eşiğin
altında, script hatasız tamamlanıyor.** Ayrıca en kötü durum (`compact`
9.742 s) ortadan kalktı, çalıştırmalar arası varyans da belirgin şekilde
azaldı (öncesinde 0.5-9.7 s aralığı, sonrasında 0.29-0.32 s — çok daha
kararlı).

**Kök neden düzeltmesi doğrulandı:** Faz 8'de `donanim_kartlari/yonetim.py`
içindeki `_catalog_dict` (tüm katalogun `deepcopy`'si) kullanımı,
`_safe_project_id`/`overrides_path`/`load_overrides`/`save_overrides` için
hafif bir `_catalog_get` erişimcisiyle değiştirildi. Faz 2'de ölçülen
592.215 gereksiz `deepcopy` çağrısının kaynağı buydu — bu, ölçülmüş, net,
koda atfedilebilir en büyük tekil iyileşme.

---

## d) Mimari çerçeve render/görünüm akışı

Bu koda Faz 7-11'de **davranış değiştiren hiçbir değişiklik yapılmadı**
(yalnızca `mimari_cerceve_render.py` → `mimari_cerceve/render.py` shim ile
taşındı, `git mv` sonrası `inspect.getsource()` ile bayt-bayt aynı olduğu
doğrulanmıştı — bkz. Faz 7). Faz 2'nin "darboğaz değil, doğrusal ölçekleniyor"
bulgusu hâlâ geçerli kabul ediliyor; yeniden ölçülmedi (mevcut kaynakları
kod değişmemişken tekrar ölçmek playbook'un "ölç, iddia etme" ilkesine
aykırı değil ama zaman/fayda oranı düşük — kod aynı, sonucun aynı çıkması
garanti).

---

## e) Uçtan uca belge üretim akışı (PDF oku → LLM → HTML)

| Adım | Öncesi | Sonrası |
|---|---|---|
| PDF okuma (`kahve_test.pdf`, 8045 karakter) | 0.047 s | 0.013 s |
| `process_tid_data_batch` (1 TID, batch + tamamlama çağrıları dahil) | ~19.864 s (yalnızca ilk toplu çağrı ölçülmüş, +4 tamamlama çağrısı loglanmış ama ölçülmemiş) | **158.340 s** (1 toplu + **9** tamamlama çağrısı — hepsi ölçüme dahil) |
| HTML üretimi | 0.025 s | 0.002 s |

**Bu satır doğrudan "daha yavaşlaştı" diye okunmamalı.** İki ölçüm aynı
şeyi ölçmüyor: Faz 2 yalnızca ilk toplu LLM çağrısını (`19.864 s`) süreyle
raporlayıp geri kalan 4 tamamlama çağrısını yalnızca "logland
ı, ölçülmedi" diye not düşmüştü. Faz 12'de **tüm zincir** (`process_tid_data_batch`
uçtan uca) ölçüldü ve bu girdi için 9 tamamlama çağrısı tetiklendi (SGD-003
ve SGD-004 için eksik STT'ler + bunlara bağlı SETET'ler) — yani Faz 2'nin
kendi bulgusu olan **"tek TİD → çoklu sıralı HTTP round-trip"** deseni
doğrulandı, hatta bu spesifik girdide öngörülenden daha fazla (5 değil,
toplam 10) çağrı tetiklendi.

**Kök neden hâlâ giderilmedi:** Faz 9 kapsamı yalnızca `requests.Session()`
paylaşımıydı (bağlantı/handshake yükünü azaltır) — LLM çağrılarının **kendisi**
model çıkarımıyla (inference) baskın olduğu ve **sıralı/paralelleştirilmemiş**
olduğu için Session paylaşımının buradaki gözlenebilir etkisi ihmal
edilebilir düzeyde (her çağrı ~15-20 s model gecikmesi, bağlantı kurulumu
değil). "Toplu çağrı eksik SGD/STT'leri tek seferde değil, teker teker
tamamlıyor" deseni Faz 7-11'in hiçbirinde kapsam dahilinde değildi — bu,
playbookın 13 fazının dışında kalan, gerçek ve büyük bir iyileştirme
fırsatı olarak açıkça not düşülüyor (örn. eksik SGD/STT'leri de tek bir
toplu isteğe eklemek, ya da paralel HTTP çağrısı).

---

## Genel değerlendirme

| Senaryo | Sonuç |
|---|---|
| a) Açılış | ~%36 daha hızlı, ama koda kesin atfedilemiyor (torch importu hâlâ eager) |
| b) RAG yükleme | ~%48 daha hızlı, **koda atfedilebilir** (main.py'nin redundant RAGHandler'ı kaldırıldı) |
| c) Donanım kartları (500 kayıt) | filter ve compact'te **kabul eşiğini artık geçen**, büyük ve **koda atfedilebilir** iyileşme (deepcopy eliminasyonu) |
| d) Mimari çerçeve render | değişmedi (koda dokunulmadı), zaten darboğaz değildi |
| e) Uçtan uca üretim | LLM çağrı-sayısı deseni **düzeltilmedi** — playbook kapsamının ötesinde, açık bir takip maddesi |

**Test:** `pytest tests/ -q` → **418 passed** (BASELINE.md'deki 381'den
+37, tamamı Faz 5'te eklenen yeni testler; **kırılan test yok**, aynı 2
uyarı kategorisi (langchain-community deprecation, Pillow `getdata`
deprecation) hâlâ geçerli).

**GUI duman testi:** `python Arayüz.py` başlatıldı, "EHSİM" başlıklı
pencere hatasız açıldı (yalnızca PyMuPDF/`fitz` deprecation uyarısı,
BASELINE.md ile birebir aynı), ~12 saniye açık tutulup programatik olarak
kapatıldı. **Not:** Bu ortamda Tkinter masaüstü penceresini tıklama/
sürükle-bırak ile uçtan uca kullanan bir GUI otomasyon aracım yok (Browser
araçları yalnızca web sayfaları için); playbook Faz 12 madde 4'teki tam
manuel duman testi listesi (PDF sürükle-bırak, donanım kartları ekranı,
etki analizi simülasyonu, mimari çerçeve görünümü, PDF/Excel/Word/DOORS
dışa aktarım) bu yüzden **kullanıcı tarafından elle doğrulanmalı** —
aşağıda kontrol listesi var.
