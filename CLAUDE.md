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

## Dizin/dosya haritası (iş alanına göre)
- **Donanım kartları:** `donanim_kartlari_ui.py`, `donanim_kartlari_yonetim.py`,
  `donanim_kartlari_model.py`, `donanim_kartlari_algilama.py`,
  `donanim_kartlari_gorsel.py`, `donanim_kartlari_karsilastirma_ui.py`,
  `donanim_detayli_inceleme*.py`, `hardware_*` dosyaları (liste/export/
  generator/review), `hardware_image_*` (AI görsel üretimi, ComfyUI).
- **Etki analizi:** `etki_analizi_ui.py`, `etki_analizi_logic.py`,
  `etki_analizi_simulasyon*.py`, `etki_analizi_degisim_*.py`,
  `etki_analizi_izlenebilirlik.py`, `etki_analizi_raporlama.py`,
  `etki_analizi_entegrasyon.py`.
- **Mimari çerçeve (DoDAF/NAF):** `mimari_cerceve_ui.py`,
  `mimari_cerceve_yonetim.py`, `mimari_cerceve_model.py`,
  `mimari_cerceve_render.py`, `mimari_cerceve_cikarim.py`,
  `mimari_cerceve_dogrulama.py`, `mimari_cerceve_katalog.py`,
  `mimari_cerceve_gorunumleri.py`. Tasarım kararları: `MIMARI_CERCEVE_TASARIM.md`.
- **LLM erişimi:** `llm_handler.py` (LM Studio'ya `requests` ile HTTP,
  batch/tekli üretim fonksiyonları), `lmstudio_model.py` (aktif model adı,
  port tespiti).
- **RAG:** `rag_handler.py` (`RAGHandler` sınıfı — embedding + Chroma
  yükleme/kaydetme), `rag_manager.py`, `rebuild_rag.py`.
- **Belge üretim modülleri:** `tid_generator_logic.py`,
  `dgöygö_generator_logic.py`, `dtet_ytet_generator_logic.py`,
  `kmtd_generator_logic.py`, `sgd_generator_logic.py`,
  `sitet_generator_logic.py`, `stt_generator_logic.py`,
  `sablon_generator_logic.py`, `hardware_generator_logic.py`.
- **Veri/çıktı:** `data_processor.py` (TİD işleme, ağaç/düz veri yapıları),
  `pdf_extraction.py`, `html_generation.py`, `hardware_export_logic.py`,
  `file_handler.py`, `text_cleanup.py`.
- **Ortak/çekirdek:** `config.py` (tüm ayarlar), `app_identity.py`,
  `sozluk.py`, `kalite_denetci.py`, `alt_sistem_test_logic.py`.
- **Giriş noktaları:** `Arayüz.py` (GUI, ~159 KB — pencere kurulumu +
  sekme/panel yönetimi + sohbet + tüm iş alanlarının entegrasyonu tek dosyada),
  `main.py` (CLI toplu akış).

## Bilinen risk alanları (büyük/karmaşık "god-file" adayları)
`Arayüz.py` (~159 KB), `donanim_kartlari_ui.py` (~138 KB),
`mimari_cerceve_ui.py` (~137 KB), `mimari_cerceve_yonetim.py` (~94 KB),
`mimari_cerceve_model.py` (~89 KB), `etki_analizi_ui.py` (~80 KB),
`etki_analizi_simulasyon.py` / `etki_analizi_simulasyon_ui.py` (~70 KB),
`donanim_kartlari_algilama.py` (~68 KB), `etki_analizi_degisim_paketi.py`
(~60 KB), `donanim_kartlari_yonetim.py` (~56 KB),
`mimari_cerceve_render.py` (~49 KB), `etki_analizi_izlenebilirlik.py`
(~43 KB), `llm_handler.py` (~42 KB, ağ + threading), `rag_handler.py`
(~29 KB, Chroma/embedding).

`Arayüz_yedek.py` Faz 3'te (RISK_HARITASI.md) hiçbir yerden import
edilmediği doğrulanıp Faz 4'te silindi — artık yok.

Threading deseni (`threading.Thread(...)` + `self.master.after(...)`)
repo genelinde 32 yerde (12 dosyada) tekrarlanıyor, ortak bir yardımcıya
çıkarılmamış — bkz. playbook Faz 8.

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
tanımlanan 13 fazlık (Faz 0-12) bir yeniden yapılandırma sürecinden
geçiriliyor. Sürecin ilerleme durumu için o dosyayı ve fazlar ilerledikçe
oluşturulan `BASELINE.md`, `PERFORMANS_RAPORU_BASLANGIC.md`,
`RISK_HARITASI.md`, `MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md` gibi rapor
dosyalarını kontrol et.
