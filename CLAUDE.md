# EHSİM — AI-V-Model-Tool-for-System-Engineers — Proje Belleği

## Ne işe yarar
IEEE 15288 tabanlı sistem mühendisliği belge üretim ve izlenebilirlik aracı.
Bir teknik-ister PDF'i girdi olarak alır; yerel bir LLM (LM Studio üzerinden
`google_gemma-3-4b-it`) ve RAG (Chroma + sentence-transformers embedding)
kullanarak TİD/SGD/STT/KMTD/SİTET/DGÖYGÖ/DTET-YTET gibi V-Model belgelerini
ve izlenebilirlik matrisini üretir; sonucu PDF/Excel/Word/HTML/DOORS(CSV)
olarak dışa aktarır. Ayrıca donanım kartları envanteri, etki analizi
simülasyonu ve DoDAF/NAF mimari çerçeve görünümleri (bkz.
`MIMARI_CERCEVE_TASARIM.md`) üretiyor.

## Çalıştırma
- Python 3.12, sanal ortam `.venv/` (repo'da yok, elle kurulur):
  ```
  py -3.12 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  ```
- Ön koşul: **LM Studio açık** ve `google_gemma-3-4b-it` modeli yüklü
  (`http://localhost:1234/v1`, OpenAI uyumlu API). Model adı
  `EHSIM_LM_MODEL` ortam değişkeniyle değiştirilebilir.
- GUI: `python "Arayüz.py"` (asıl uygulama, `root.mainloop()`).
- CLI/toplu iz sürülebilirlik akışı: `python main.py`.
- Testler: `pytest tests/ -q`.

## Dizin/dosya haritası (Faz 7 sonrası — GERÇEK KOD paket altında, kök .py'ler shim)

Faz 7'de (playbook) ~60 kök `.py` dosyası anlamlı paketlere taşındı.
**Gerçek kod artık paketlerin içinde**; kök dizindeki eski dosya adları
(`donanim_kartlari_ui.py`, `mimari_cerceve_yonetim.py`, `llm_handler.py`
vb.) hâlâ var ama içerikleri `sys.modules[__name__] = _module` ile paket
içindeki gerçek modüle yönlendiren birer **shim** — eski import yolları
(`import llm_handler`, `from donanim_kartlari_yonetim import ...`) kırılmadan
çalışmaya devam ediyor. Yeni kod paket yollarını kullanmalı.

- **Donanım kartları:** `donanim_kartlari/` (model.py, gorsel.py,
  algilama.py, yonetim.py, karsilastirma_ui.py, `ui/` altında 9 mixin
  dosyası — workspace.py bunları birleştirir), `donanim_detayli/`
  (inceleme.py, raporlama.py, ui.py), `hardware_liste/` (logic.py,
  review_ui.py, ui.py), `hardware_image/` (provider.py, generation.py,
  prompt.py, generation_ui.py — AI görsel üretimi/ComfyUI).
- **Etki analizi:** `etki_analizi/` (logic.py, entegrasyon.py,
  simulasyon.py, degisim_paketi.py, degisim_ui.py, raporlama.py,
  simulasyon_ui.py, ui.py). **Not:** `etki_analizi_degisim_raporlama.py`
  Faz 7'de taşınmadı, hâlâ kök dizinde gerçek kod olarak duruyor (bilinçli
  istisna, bkz. `MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md`).
- **Mimari çerçeve (DoDAF/NAF):** `mimari_cerceve/` (model.py, katalog.py,
  gorunumleri.py, dogrulama.py, cikarim.py, yonetim.py, render.py, `ui/`
  altında 8 mixin dosyası). Tasarım kararları: `MIMARI_CERCEVE_TASARIM.md`.
- **LLM erişimi:** `llm/` (handler.py — LM Studio'ya `requests.Session()`
  ile HTTP, batch/tekli üretim fonksiyonları; model_secim.py — aktif model
  adı, port tespiti).
- **RAG:** `rag/` (handler.py — `RAGHandler` sınıfı, embedding + Chroma
  yükleme/kaydetme, tembel `threading.Lock` korumalı; manager.py,
  rebuild.py).
- **Belge üretim modülleri:** `belge_uretim/` (tid.py, sgd.py, stt.py,
  dgoygo.py, dtet_ytet.py, kmtd.py, sitet.py, hardware.py, sablon.py —
  sonuncusu tamamen devre dışı/dead-code bir triple-quoted string, olduğu
  gibi taşındı).
- **Veri/çıktı:** `data_processor.py` (TİD işleme, ağaç/düz veri
  yapıları — kök dizinde, taşınmadı), `pdf_extraction.py`,
  `html_generation.py`, `hardware_export_logic.py`, `file_handler.py`,
  `text_cleanup.py` (→ `core/text_cleanup.py` shim'i).
- **Ortak/çekirdek:** `core/` (config.py — tüm ayarlar, app_identity.py,
  text_cleanup.py, izlenebilirlik.py [eski `etki_analizi_izlenebilirlik.py`
  — Faz 6'da bölme planlanmıştı, kullanım analizi çapraz-alan bağımlılık
  gösterince kullanıcı onayıyla bütün dosya olarak taşındı]).
- **Arayüz (GUI):** `arayuz/` (yardimcilar.py, pencere.py,
  dosya_surukle.py, workspace_koordinasyon.py, donanim_entegrasyon.py,
  uretim_akisi.py, copilot.py, disa_aktarim.py, workspace.py — eski tek
  parça ~159 KB `Arayüz.py`'nin mixin'lere bölünmüş hali). Kök `Arayüz.py`
  hem shim hem giriş noktası: `TIDGeneratorApp`/`prepare_process_identity`/
  `ttk`'yi `arayuz`'dan re-export eder, `__main__` altında pencereyi açar.
- **Giriş noktaları:** `Arayüz.py` (GUI), `main.py` (CLI toplu akış).

## Bilinen risk alanları (Faz 7 öncesi "god-file" adaylarının şimdiki hali)
Faz 6-7'de (playbook) en büyük dosyalar mixin desenine bölündü:
`Arayüz.py` (~159 KB) → `arayuz/` (9 dosya), `donanim_kartlari_ui.py`
(~138 KB) → `donanim_kartlari/ui/` (9 mixin dosyası),
`mimari_cerceve_ui.py` (~137 KB) → `mimari_cerceve/ui/` (8 mixin dosyası).
Bölünmemiş ama paket içine taşınmış orta-büyük dosyalar:
`mimari_cerceve/yonetim.py` (~94 KB), `mimari_cerceve/model.py` (~89 KB),
`etki_analizi/ui.py` (~80 KB), `etki_analizi/simulasyon.py` /
`simulasyon_ui.py` (~70 KB), `donanim_kartlari/algilama.py` (~68 KB),
`etki_analizi/degisim_paketi.py` (~60 KB), `donanim_kartlari/yonetim.py`
(~56 KB), `mimari_cerceve/render.py` (~49 KB), `core/izlenebilirlik.py`
(~43 KB), `llm/handler.py` (~42 KB, ağ + threading), `rag/handler.py`
(~29 KB, Chroma/embedding, artık `threading.Lock` korumalı — bkz. Faz 11).
Doğrulama yöntemi: her bölme `inspect.getsource()` ile eski/yeni kod
karşılaştırılarak bayt-bayt aynılık garantilendi (bkz.
`MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md`).

`Arayüz_yedek.py` Faz 3'te (RISK_HARITASI.md) hiçbir yerden import
edilmediği doğrulanıp Faz 4'te silindi — artık yok.

Threading deseni (`threading.Thread(...)` + `self.master.after(...)`)
repo genelinde 23 `threading.Thread()` çağrısı (15 dosyada) olarak devam
ediyor, ortak bir yardımcıya çıkarılmadı (playbook Faz 8 kapsamı dışında
bırakıldı — bilinçli tercih, sadece UI performansı hedeflendi). Faz 11'de
hepsi `daemon=True` olacak şekilde denetlendi (1 eksik bulundu, düzeltildi
— bkz. `arayuz/uretim_akisi.py`), paylaşılan `rag_handler` tekil nesnesi
kilitle korunuyor, ama ortak bir "arka plan işi" soyutlaması hâlâ yok.

## Test
`pytest tests/ -q`. `tests/` klasöründe ciddi kapsam var (`donanim_*`,
`etki_analizi_*`, `mimari_cerceve_*`, `hardware_*`, `rag_handler_fallback`,
`lmstudio_model`, `app_identity`); `test_mimari_cerceve_ui.py` (~83 KB) en
kapsamlı olanı. `tests/` içinde ayrıca `_*.py` ile başlayan (pytest'in
otomatik toplamadığı, muhtemelen manuel/QA amaçlı) yardımcı script'ler var:
`_hardware_ai_image_qa.py`, `_hardware_cards_app_smoke.py` vb.

## Dokunulmaması gereken dizinler
`.venv/`, `HuggingFaceEmbeddings/`, `rag_chroma/`, `rag_chroma_lms/`
(gerçek Chroma veritabanı klasörleri — Faz 4'te `.gitignore` düzeltildi,
artık gerçek isimlerle eşleşiyor ve git takibinden çıkarıldı), `outputs/`,
`output/`, `tmp/`, `__pycache__/`, `context_files/`, `rag_documents/`.
Bunlar üretilmiş/ikili veri veya bağımlılık dizinleri; kaynak kod gibi
elle düzenlenmemeli.

`HuggingFaceEmbeddings/` (~88 MB) sentence-transformers'ın
`all-MiniLM-L6-v2` model ağırlıklarını içerir; HuggingFace'ten yeniden
indirilebilir, bu yüzden Faz 4'te git takibinden çıkarıldı.
`repomix-output.xml` (statik bağlam dökümü) da aynı şekilde git dışı
bırakıldı; gerektiğinde `repomix` ile yeniden üretilir.

## Yapılandırma (`config.py`, ortam değişkenleriyle geçersiz kılınabilir)
- `EHSIM_LM_MODEL` → `MODEL_NAME` (varsayılan `google_gemma-3-4b-it`)
- `EHSIM_IMAGE_PROVIDER` → görsel sağlayıcı (varsayılan `disabled`)
- `EHSIM_IMAGE_API_URL`, `EHSIM_IMAGE_MODEL`, `EHSIM_IMAGE_API_KEY`,
  `EHSIM_IMAGE_API_KEY_HEADER`, `EHSIM_IMAGE_API_KEY_PREFIX`,
  `EHSIM_IMAGE_HEALTH_PATH`, `EHSIM_IMAGE_MODELS_PATH`,
  `EHSIM_IMAGE_GENERATE_PATH` → AI donanım görseli sağlayıcı ayarları
  (ComfyUI/başka bir API), bkz. `COMFYUI_KURULUM.md`
- `EHSIM_COMFYUI_WORKFLOW`, `EHSIM_COMFYUI_OUTPUT_NODE`,
  `EHSIM_COMFYUI_POLL_INTERVAL` → ComfyUI iş akışı ayarları
- `EHSIM_IMAGE_TIMEOUT` (180s), `EHSIM_IMAGE_MAX_BYTES` (20 MB),
  `EHSIM_IMAGE_MAX_PIXELS` (24 MP)
- Sabit (env ile değişmeyen) önemli değerler: `LMSTUDIO_BASE_URL`
  (`http://localhost:1234/v1`), `MAX_CONTEXT_TOKENS` (8192), `CHUNK_SIZE`
  (4000), `CHUNK_OVERLAP` (50), `USE_BATCH_PROCESSING` (True), `BATCH_SIZE`
  (10). `HARDWARE_AUTO_IMAGE_GENERATION` her zaman `False` — görsel üretimi
  yalnızca kullanıcının açık onayıyla tetiklenir.

## Performans yeniden yapılandırma süreci
Bu proje kök dizindeki `PERFORMANS_REFAKTOR_PLAYBOOK.md` dosyasında
tanımlanan 13 fazlık (Faz 0-12) yeniden yapılandırma sürecinin **tüm
fazlarını tamamladı** (2026-08-29). Her faz kendi git dalında
(`refactor/faz-N-...`, zincir halinde birbirinin üstüne) yapıldı; `main`
dalı bilinçli olarak dokunulmadan bırakıldı ve zincirin `main`'e
birleştirilmesi ayrı, kullanıcı onaylı bir adım (henüz yapılmadıysa bu
notu güncelle). Süreç detayları ve ölçümler için: `BASELINE.md` (Faz 1),
`PERFORMANS_RAPORU_BASLANGIC.md` (Faz 2, öncesi ölçümler),
`RISK_HARITASI.md` (Faz 3), `MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md`
(Faz 6-7, paket planı ve gerçek sonuç), `PERFORMANS_RAPORU_SONUC.md`
(Faz 12, öncesi/sonrası karşılaştırma), `REFAKTOR_OZETI.md` (tüm sürecin
özeti).
