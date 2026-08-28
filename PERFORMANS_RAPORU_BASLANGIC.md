# PERFORMANS RAPORU — BAŞLANGIÇ (Faz 2)

**Tarih:** 2026-08-28
**Yöntem:** `cProfile` + `time.perf_counter` ile gerçek çağrı/duvar-saati ölçümü
(tahmin değil). Harness script'leri `scripts/profiling/` altında **geçici**
tutuldu, commit'lenmedi (bkz. playbook Faz 2 kuralı). Ortam: Windows 11,
Python 3.12.10, LM Studio açık ve `gemma-4-e4b-it` modeli yüklü (bkz.
BASELINE.md'deki model adı notu — ölçümler için `EHSIM_LM_MODEL` env
değişkeniyle yüklü modele göre ayarlandı).

---

## a) Uygulama açılışı (`Arayüz.py` import + ilk pencere)

| Adım | Süre (duvar saati) | Not |
|---|---|---|
| `import Arayüz` (profilsiz, ham) | **12.75 s** | cProfile altında 28.9s'e çıkıyor (profiler ek yükü) |
| `TIDGeneratorApp.__init__` (ilk pencere) | **2.95 s** | ~2.5s'i doğrudan Tk widget oluşturma (`_tkinter.tkapp.call`) |
| **Toplam açılış** | **~15.7 s** | Kullanıcı `python Arayüz.py` dedikten pencere görünene kadar |

**En çok zaman tüketen 10 kalem (import, cumulative time):**

| # | Kalem | Cum. süre |
|---|---|---|
| 1 | `torch._ops` / `torch._higher_order_ops.*` (op kayıt zinciri) | ~15–83 s (profiler ek yüküyle şişmiş; ham `import torch` tek başına ~2.2s) |
| 2 | `langchain_text_splitters.base` modülü (import zamanı) | 12.6 s (cum, iç içe torch importlarını da kapsıyor) |
| 3 | `builtins.__import__` (toplam, 1352 çağrı) | 17.0 s |
| 4 | `ttkbootstrap.style.bootstyle.__init__` × 72 (72 buton/stil) | 2.35 s |
| 5 | `Arayüz.py:432 _create_header` | 2.27 s |
| 6 | `tkinter.ttk.Widget.__init__` × 75 | 2.33 s |
| 7 | GUI-only importlar (`tkinter`, `PIL`, `ttkbootstrap`, `reportlab`, `openpyxl`, `numpy`) | 0.67 s (referans: küçük) |
| 8 | `langchain_huggingface` importu (izole) | 0.96 s |
| 9 | `ttkbootstrap.window.Window.__init__` | 0.25 s |
| 10 | 25 kardeş modülün (`donanim_kartlari_ui`, `mimari_cerceve_ui`, `etki_analizi_*` vb.) eager import'u | ölçülemeyen ek pay — hepsi tek `try/except ImportError` bloğunda, pencere açılmadan **önce** sırayla import ediliyor |

**Kök neden:** `Arayüz.py:29` — `from langchain_huggingface import HuggingFaceEmbeddings` —
modül seviyesinde, koşulsuz olarak import ediliyor. Bu, transitif olarak
`sentence-transformers` → `torch`'u tetikliyor ve **PyTorch'un C++ operatör
kayıt zinciri tek başına saniyelerce sürüyor.** Oysa gerçek RAG akışında
(`rag_handler.py`) embedding önceliği **LM Studio HTTP API**'sidir;
`HuggingFaceEmbeddings`/torch sadece LM Studio yokken devreye giren bir
yedek yoldur (bkz. rag_handler.py `_initialize_embeddings`). Yani normal
kullanımda hiç kullanılmayan bir bağımlılık, her açılışta zorunlu olarak
yükleniyor.

Ayrıca `Arayüz.py` başında 25 kardeş modül (bazıları 60-140 KB) tek seferde,
sırayla import ediliyor — bunların kaçı gerçekten "ilk pencere" için gerekli,
kaçı yalnızca kullanıcı ilgili sekmeye tıkladığında gerekli, ayrıştırılmamış.

---

## b) RAG veritabanı yükleme (`rag_handler.py`)

| Adım | Süre | Not |
|---|---|---|
| `rag_handler` modülü importu | 11.7 s | (a) ile aynı torch/langchain zincirinin tekrarı — ayrı process'te ölçüldü |
| `RAGHandler()` → `_initialize_embeddings()` | **2.076 s** | Neredeyse tamamı `requests.get(LMSTUDIO_BASE_URL+"/models")` — senkron ağ round-trip'i |
| `_load_existing_database()` (Chroma yükleme) | 0.328 s | `chromadb.PersistentClient` init baskın |
| **İkinci `RAGHandler()` + `_load_existing_database()`** | **2.082 s (tekrar!)** | `embeddings_same=False`, `db_same=False` — **tekillik (singleton) garantisi yok** |

**Kök neden (playbook'taki şüphe doğrulandı):** Her `RAGHandler()` çağrısı
LM Studio'ya yeniden bağlantı testi yapıyor ve yeni bir `Chroma`/embeddings
nesnesi oluşturuyor. Kod tabanında zaten modül seviyesi bir `rag_handler`
singleton'ı var (`llm_handler.py`'de `from rag_handler import ... rag_handler`
ile import ediliyor) ama `main.py` gibi başka çağrı noktaları doğrudan
`RAGHandler()` çağırarak bu singleton'ı bypass ediyor — her bypass ~2 saniye
gereksiz ağ gecikmesi demek.

---

## c) Donanım kartları listesi/algılama akışı

Repoda zaten `tests/_hardware_catalog_scale_qa.py` adında, 500 kartlık
gerçek Tk penceresiyle ölçüm yapan bir QA script'i var; onu hem olduğu gibi
hem de `cProfile` ile sardım.

**Ham (profilsiz) ölçümler — 3 ayrı çalıştırma:**

| Çalıştırma | startup (pencere+kart görünümü) | filter (arama) | compact (500 satırlık liste görünümü) |
|---|---|---|---|
| 1 (soğuk başlangıç) | 4.480 s | 2.277 s | **9.742 s** |
| 2 | 2.156 s | 1.051 s | 0.541 s |
| 3 | 2.196 s | 1.116 s | 0.633 s |

Script'in kendi kabul eşiği `filter <= 0.75s` — **3 çalıştırmanın 3'ünde de
bu eşik aşıldı ve script `RuntimeError` fırlattı.** Bu, playbook'tan önce
zaten var olan, kod içi bir performans regresyonu sinyali.

**cProfile ile en çok zaman tüketen kalemler (500 kayıt):**

| # | Fonksiyon | Cum. süre (workspace init) | Not |
|---|---|---|---|
| 1 | `_tkinter.tkapp.call` (4065 çağrı) | 2.50 s | Widget oluşturma/güncelleme |
| 2 | `_view_changed` | 1.43 s | Görünüm değişince tüm liste yeniden kuruluyor |
| 3 | `_render_catalog_view` | 1.33 s | |
| 4 | **`copy.deepcopy`** | 1.10 s (**592.215 çağrı!**) | Aşırı ve tekrarlayan deep-copy |
| 5 | `_render_cards` | 1.01 s | |
| 6 | `tk.Widget.__init__` × 722 | 0.90 s | |
| 7 | `_build_card` (yalnızca 24 görünür kart için) | 0.87 s | Sayfalama var (24/500), iyi |

**Filtre (arama) sırasında:** `_apply_filters_changed` → tüm
`_render_catalog_view`/`_render_cards`/`_build_card` zincirini **yeniden**
tetikliyor (debounce yok, artımlı güncelleme yok) — 171.169 `deepcopy`
çağrısı tek bir arama tuş vuruşunda.

**Kompakt liste görünümüne geçişte:** 500 satırın tamamı `Treeview`'e
yazılıyor (sayfalama kart görünümündeki gibi kompakt listede yok) **ve**
görünüm değişimi tetiklediği `_persist_preferences` → `save_overrides` diske
yazma + `_catalog_dict` tam deep-copy'si yapıyor — sırf görünüm modu
değiştirmek için gerekmeyen bir I/O + kopyalama maliyeti.

**Kök neden:** (1) kart görünümünde sayfalama var ama kompakt liste
görünümünde yok; (2) her filtre/görünüm değişiminde tüm widget ağacı `copy.deepcopy`
ile yeniden kuruluyor, artımlı diff yok; (3) arama kutusunda debounce yok.
Bunlar birebir playbook Faz 8'in hedeflediği desenler.

---

## d) Mimari çerçeve render/görünüm akışı

`mimari_cerceve_render.render_view` fonksiyonunu, test dosyasındaki
(`tests/test_mimari_cerceve_render.py`) fixture üreticilerini kullanarak
ölçeklendirilmiş sentetik SV-1 snapshot'larıyla ölçtüm:

| Eleman + ilişki sayısı | Süre | SVG boyutu |
|---|---|---|
| 30 eleman, 20 ilişki | 0.053 s | 153 KB |
| 180 eleman, 120 ilişki | 0.293 s | 908 KB |

Süre eleman sayısıyla **yaklaşık doğrusal** ölçekleniyor; en büyük tekil
kalem `xml.etree.ElementTree.tostring` (XML serileştirme) ve
`validate_architecture` doğrulaması, ikisi de makul oranlarda. **Bu akış şu
an bir darboğaz değil** — Faz 8/10'da öncelik verilmesi gerekmiyor.

---

## e) Uçtan uca belge üretim akışı (PDF oku → LLM → HTML)

| Adım | Süre | Not |
|---|---|---|
| PDF okuma (`pdf_extraction.extract_pdf_to_txt`, `kahve_test.pdf`, 8045 karakter) | **0.047 s** | İhmal edilebilir |
| `generate_all_requirements_batch` — **1 TID girdisi**, ilk (toplu) LLM çağrısı | **19.864 s** | Gerçek LM Studio çağrısı; `call_gemma3_api` tek başına 17.7s (ağ/model gecikmesi, kodun kendisi değil) |
| `process_batch_response` — eksik SGD/STT/SETET tamamlama | **+4 ayrı, sıralı LLM çağrısı daha** (ölçülmedi ama loglandı) | Toplamda **1 TID → 5 ayrı HTTP round-trip** |
| HTML üretimi (`create_tree_structure` + `create_flat_test_data` + `generate_advanced_html`, 5 kayıt) | **0.025 s** | İhmal edilebilir |

**Kök neden:** Uçtan uca sürenin neredeyse tamamı LLM ağ gecikmesi. Daha
kritik olan: **tek bir TİD için "toplu" (batch) çağrı yetmiyor, sistem eksik
SGD/STT/SETET'leri tamamlamak için ek 4 senkron/sıralı çağrı daha yapıyor**
— playbook'un "USE_BATCH_PROCESSING gerçekten çağrı sayısını azaltıyor mu"
sorusuna doğrudan olumsuz kanıt. Gerçek kullanımda (15/15/15 gereksinim gibi
sayılarla) bu, düzinelerce sıralı, paralelleştirilmemiş HTTP çağrısı
demek — Faz 9'un en yüksek etkili hedefi burası.

**Bonus bulgu — ana thread bloklaması (playbook madde 3):** `main.py` CLI
akışının kullandığı `data_processor.process_tid_data_batch` →
`llm_handler.generate_all_requirements_batch`, `context_selection`
verilmediğinde `llm_handler.choose_context_option()` içinde **senkron,
bloklayan bir `tkinter.messagebox.askyesno/askyesnocancel` penceresi**
açıyor (context dosyası yoksa "Yeni PDF yüklemek ister misiniz?" sorusu).
Ölçüm sırasında bu diyalog **34.2 saniye** açık kaldı. İyi haber: kod
incelemesiyle doğrulandı ki **gerçek GUI akışı (`Arayüz.py: run_ai_process`
→ `tid_generator_logic.run_generation_logic`) bu fonksiyonu hiç çağırmıyor**
ve zaten `threading.Thread` içinde çalışıyor — yani GUI kullanıcıları bu
donmayı yaşamıyor. Ama `main.py` CLI yolu hâlâ etkilenmiş durumda ve bu,
otomasyon/toplu iş senaryolarında sessizce sonsuza kadar asılı kalabilir.

---

## Öncelik sıralaması (Faz 7-10 için)

1. **Faz 9 (LLM/RAG)** — en yüksek öncelik. Tek TİD için 5 sıralı HTTP
   çağrısı + RAG singleton eksikliği (her `RAGHandler()` ~2s ağ gecikmesi)
   gerçek kullanımda dakikalarca sürebilecek toplam gecikmeye yol açıyor.
2. **Faz 8 (UI/Tkinter)** — donanım kartları listesinde ölçülmüş, somut
   regresyon (filtre süresi kendi eşiğini aşıyor, 500 satırlık kompakt liste
   görünümü saniyelerce sürüyor, aşırı `deepcopy`, debounce yok).
   Ayrıca `Arayüz.py` açılışında torch/HuggingFace importunun (2. bulgu,
   madde a) tembel/lazy hale getirilmesi tek başına açılış süresini
   ~10 saniye azaltabilir — bu da Faz 8 kapsamında ele alınabilir (import
   zamanlama UI donması değil ama kullanıcının gördüğü "açılış" gecikmesi).
3. **Faz 10 (Veri/Dosya I/O)** — ölçülen akışlarda (PDF okuma, HTML üretimi)
   **darboğaz bulunamadı** (ikisi de <50ms). Faz 10'u düşük öncelikli
   yapabiliriz; yine de playbook'taki iterrows/openpyxl/string-concat
   kontrolleri (özellikle çok sayfalı PDF'lerde ve büyük Excel
   üretimlerinde) statik olarak taranmalı, ama bu rapor onu acil bir
   darboğaz olarak göstermiyor.
4. **Mimari çerçeve render (madde d)** — darboğaz değil, dokunmaya gerek yok.

## Ek not (kod değişikliği değil, sadece gözlem)
`main.py`'nin bloklayan context-dialog sorunu (madde e, bonus bulgu) teknik
olarak bu playbook'un performans kapsamı dışında bir *doğruluk/UX* hatası,
ama Faz 11 (eşzamanlılık) sırasında hatırlanmalı.
