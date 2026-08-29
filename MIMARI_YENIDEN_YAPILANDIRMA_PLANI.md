# Mimari Yeniden Yapılandırma Planı (Faz 6 — PLAN MODU)

**Durum:** Onay bekliyor. Bu fazda hiçbir dosya değiştirilmedi/taşınmadı —
yalnızca plan. Faz 7'ye yalnızca bu plan onaylandıktan sonra geçilecek.

**Girdi:** Bu plan, CLAUDE.md (Faz 0), RISK_HARITASI.md (Faz 3, karmaşıklık
sıralaması ve bağımlılık grafikleri) ve PERFORMANS_RAPORU_BASLANGIC.md
(Faz 2) bulgularına dayanıyor.

---

## 1. Paket taşıma (`ehsim/`) mi, düz yapıda dosya bölme mi?

### Seçenek A — Kök dizini `ehsim/` paketine taşı
- **Artıları:** "Gerçek" bir Python paketi; `import ehsim.donanim_kartlari.ui`
  gibi net bir isim alanı; uzun vadede en temiz sonuç.
- **Eksileri:** Depodaki **her** `.py` dosyasının (kaynak + `tests/`
  altındaki ~35 test dosyası, toplam ~85 dosya) importlarını **aynı anda**
  güncellemeyi gerektirir — Python'da bir dosya paket içine taşınıp diğerleri
  taşınmazsa `ModuleNotFoundError` zinciri oluşur, yarı-taşınmış bir ara
  durum çalışmaz. Bu, playbook'un "küçük, gözden geçirilebilir adımlar"
  kuralıyla doğrudan çelişir: tek seferlik, ~85 dosyalık dev bir commit
  gerektirir. `main.py`, `Arayüz.py`, olası masaüstü kısayolları/betikleri
  (`python Arayüz.py`) için çalışma dizini/PYTHONPATH varsayımları da
  değişir.

### Seçenek B — Düz kök yapıda kal, sadece devasa dosyaları alt paketlere böl
- **Artıları:** Her iş alanı (`donanim_kartlari/`, `mimari_cerceve/` vb.)
  kendi alt klasörüne taşınır ama **kök dizin düz kalır**
  (`import donanim_kartlari_ui` yerine `from donanim_kartlari import ui`
  gibi). Modül modül, birer birer taşınabilir: bir dosya taşınırken geçici
  bir "re-export shim" (eski `donanim_kartlari_ui.py` dosyası, yeni
  `donanim_kartlari/ui.py`'den `from .ui import *` yapan ince bir
  yönlendirici haline gelir) eski import yollarını (`import
  donanim_kartlari_ui`) kırmadan tutar. `main.py`/`Arayüz.py` gibi giriş
  noktaları ve `tests/`'teki mevcut importlar geçiş boyunca çalışmaya devam
  eder.
- **Eksileri:** Sonuç "yarı paket" görünümlü (bazı modüller `donanim_kartlari/`
  altında, `Arayüz.py` hâlâ kökte) — Seçenek A kadar temiz değil.

### Öneri: **Seçenek B**
Gerekçe: Bu depoda tek bir "Initial commit" var (squash edilmiş geçmiş),
yani "bir şey ters giderse geri al" güvencesi zayıf; playbook'un kendisi de
her adımdan sonra `pytest` çalıştırıp küçük commit'ler istiyor. Seçenek A'nın
gerektirdiği tek-seferlik dev commit bu güvenlik ağını devre dışı bırakır.
Seçenek B, re-export shim'leri sayesinde **her commit'ten sonra hem eski hem
yeni import yolu çalışır durumda** kalır — bu playbook'un temel felsefesiyle
(küçük adım + her adımda yeşil test) birebir örtüşüyor. `ehsim/` paketine
tam geçiş, istenirse gelecekte ayrı bir playbook/faz olarak ele alınabilir.

---

## 2. Hedef klasör/dosya haritası (iş alanı bazında)

Aşağıdaki harita RISK_HARITASI.md'deki (Faz 3) bağımlılık katmanlarını
(`model → yardımcılar → render/ui`) korur; taşıma sırası da bu katmanları
izleyecek (bkz. bölüm 4).

```
donanim_kartlari/
  __init__.py
  model.py            <- donanim_kartlari_model.py (değişmeden taşınır, zaten temiz)
  gorsel.py            <- donanim_kartlari_gorsel.py
  algilama.py          <- donanim_kartlari_algilama.py (F notlu 2 fonksiyon burada;
                           bölme sırasında ayrı dosyalara da ayrılabilir, bkz. not)
  yonetim.py            <- donanim_kartlari_yonetim.py (F notlu 3 fonksiyon burada)
  ui.py                <- donanim_kartlari_ui.py (2401 satır — muhtemelen
                           tek dosya olarak taşınamayacak kadar büyük, bkz. not)
  karsilastirma_ui.py  <- donanim_kartlari_karsilastirma_ui.py

donanim_detayli/              [GÜNCELLEME — Faz 7'de "donanim_detayli_inceleme/"
  __init__.py                  yerine "donanim_detayli/" adı kullanıldı: paket
  inceleme.py           <- donanim_detayli_inceleme.py            adı ile
  raporlama.py          <- donanim_detayli_inceleme_raporlama.py  shim dosyası
  ui.py                 <- donanim_detayli_inceleme_ui.py         donanim_detayli_inceleme.py
                                aynı isimde olamayacağı için (paket dizini ile
                                modül dosyası çakışır) yeniden adlandırıldı.

hardware_liste/            (eski/basit donanım listesi — donanim_kartlari
  __init__.py               ailesinden BAĞIMSIZ, ayrı bir özellik; Faz 6
  logic.py                  taramasında ikisinin de Arayüz.py'de ayrı
  export.py                 butonlarla canlı olduğu doğrulandı, biri "ölü
  review_ui.py               kod" değil)
  generator_logic.py
  ui.py

hardware_image/
  __init__.py
  provider.py           <- hardware_image_provider.py (ComfyUI/API istemcisi)
  generation.py         <- hardware_image_generation.py
  prompt.py             <- hardware_image_prompt.py
  generation_ui.py      <- hardware_image_generation_ui.py

etki_analizi/
  __init__.py
  [GÜNCELLEME — uygulandı: izlenebilirlik.py buraya değil, core/izlenebilirlik.py'ye
   taşındı; bkz. 2a'nın güncellenmiş hâli.]
  logic.py
  entegrasyon.py
  simulasyon.py
  simulasyon_ui.py
  degisim_paketi.py
  degisim_raporlama.py
  degisim_ui.py
  raporlama.py
  ui.py

mimari_cerceve/
  __init__.py
  model.py
  katalog.py
  gorunumleri.py
  dogrulama.py
  render.py
  cikarim.py
  yonetim.py
  ui.py                 <- mimari_cerceve_ui.py (2936 satır — en büyük ikinci
                            dosya, tek parça taşınamaz, bkz. not)

rag/
  __init__.py
  handler.py            <- rag_handler.py
  manager.py            <- rag_manager.py
  rebuild.py            <- rebuild_rag.py

llm/
  __init__.py
  handler.py            <- llm_handler.py
  model_secim.py         <- lmstudio_model.py

belge_uretim/                (tid/sgd/stt/... generator_logic ailesi — hepsi
  __init__.py                 zaten birbirine benzer, ince, tekil sorumluluklu
  tid.py                      dosyalar; RISK_HARITASI.md'de bu dosyalar acil
  sgd.py                      listede değildi, sadece klasörleniyor)
  stt.py
  dgoygo.py
  dtet_ytet.py
  kmtd.py
  sitet.py
  sablon.py
  hardware.py            <- hardware_generator_logic.py

core/                        (üç iş alanının da paylaştığı gerçek çekirdek —
  __init__.py                  bkz. RISK_HARITASI.md bölüm 3 "alanlar arası
  config.py             <- config.py                bağımlılık" notu)
  app_identity.py       <- app_identity.py
  text_cleanup.py       <- text_cleanup.py
  html_generation.py    <- html_generation.py
  pdf_extraction.py     <- pdf_extraction.py
  izlenebilirlik.py     <- etki_analizi_izlenebilirlik.py (TAMAMI — bkz. 2a,
                            uygulandı: Faz 7'de bölme yerine tüm dosya taşındı)

(kökte kalanlar)
  Arayüz.py             <- ince orkestrasyon katmanına indirgenir (bkz. bölüm 3)
  main.py               <- CLI akışı, değişmeden kalır
  file_handler.py       <- yalnızca main.py kullanıyor, core'a taşınmaz
  kalite_denetci.py     <- yalnızca Arayüz.py kullanıyor, core'a taşınmaz
  sozluk.py             <- yalnızca Arayüz.py kullanıyor (_show_sozluk), core'a taşınmaz
  data_processor.py     <- main.py'nin CLI akışına özel, değişmeden kalır
```

### 2a. `etki_analizi_izlenebilirlik.py` ikilemi — [GÜNCELLENDİ, Faz 7'de uygulandı]
RISK_HARITASI.md'de tespit edildi: bu dosya adının aksine üç iş alanı
tarafından da (`etki_analizi_*`, `donanim_kartlari_algilama/yonetim`,
`mimari_cerceve_cikarim/yonetim`) kullanılıyor. Planlama sırasında iki
seçenek değerlendirilmişti: (i) tamamını `core/`'a taşı, (ii) böl
(`core/izlenebilirlik_cekirdek.py` + `etki_analizi/izlenebilirlik.py`) ve
o sırada (ii) önerilmişti.

**Faz 7'de bu adıma gelindiğinde yapılan kullanım analizi kararı
değiştirdi:** dosyanın 17 public isminden 10'u (+ `__all__`'a hiç
girmemiş `DEFAULT_OUTPUT_ROOT`) zaten `donanim_kartlari_algilama/yonetim`
VE `mimari_cerceve_cikarim/yonetim` tarafından kullanılıyor; üstelik en
büyük fonksiyon olan `build_traceability_map` (`persist_traceability_report`
ve `load_project_traceability` ile birlikte) yalnızca etki_analizi'nin
kendi UI'ı tarafından değil, **doğrudan `Arayüz.py` tarafından** çağrılıyor.
Gerçekten sadece dosya-içi/dışarıdan hiç kullanılmayan üç isim
(`TraceabilityError`, `check_lm_studio_status`, `read_document_records`)
için ayrı bir modül açmak gereksiz karmaşıklık olurdu.

**Sonuç (kullanıcıya sunulup onaylandı): (i) — tüm dosya `core/izlenebilirlik.py`'ye
taşındı, bölme yapılmadı.** Bu, planlama aşamasında tahmin edilemeyen,
yalnızca gerçek import grafiği çıkarılınca ortaya çıkan bir düzeltmeydi;
gelecekteki fazlar için ders: kesin bölme kararları, mümkünse taşıma
adımına gelindiğinde güncel kullanım verisiyle doğrulanmalı.

### Not — çok büyük dosyalar (donanim_kartlari_ui.py, mimari_cerceve_ui.py, Arayüz.py)
Yukarıdaki haritada bu üç dosya "1-e-1" taşınmış gibi görünüyor ama
RISK_HARITASI.md'ye göre bunlar (2401, 2936, 3208 satır) muhtemelen tek
dosya olarak taşınsa bile hâlâ çok büyük kalır. Bu planın kapsamı "hangi
klasöre gidecek"i belirlemek; **içlerinin de** alt modüllere ayrılması
(örn. `donanim_kartlari/ui/liste_gorunumu.py`,
`donanim_kartlari/ui/detay_paneli.py`,
`donanim_kartlari/ui/workspace.py` gibi) Faz 7'de o dosyanın taşıma adımı
geldiğinde, dosyanın kendi iç sorumluluk sınırları (fonksiyon grupları)
incelenerek ayrıca planlanmalı. Bunu şimdiden fonksiyon fonksiyon planlamak
bu fazın kapsamını aşar ve muhtemelen yanlış tahmin üretir.

---

## 3. `Arayüz.py`'nin sorumlulukları ve hedef alt modüller

`Arayüz.py` (3208 satır) şu sorumluluk kümelerini taşıyor (yöntem
gruplarına göre):

| Sorumluluk kümesi | Temsili metotlar | Hedef |
|---|---|---|
| Pencere kurulumu, DPI, tema/dil | `__init__` (kurulum kısmı), `_apply_theme`, `_toggle_lang`, `_toggle_theme`, `_t`, `_L`, `_reg_btn`, `_create_header`, `_create_buttons` | `arayuz/pencere.py` — kalıcı "ince orkestrasyon" çekirdeği, `Arayüz.py`'de KALIR (giriş noktası olduğu için) |
| Sürükle-bırak | `_register_drop_target`, `_on_files_dropped` | `arayuz/dosya_surukle.py` |
| Belge üretimi tetikleme/izlenebilirlik | `run_ai_process`, `_traceability_worker`, `_start_traceability_build`, `_rescan_traceability_from_workspace`, `_notify_traceability_started`, `_finish_traceability_*` | `arayuz/uretim_akisi.py` |
| Donanım kartları/görsel üretim entegrasyonu | `start_hardware_generation`, `_run_hardware_generation`, `_finish_hardware_generation`, `_hardware_datasheet_worker`, `_finish_hardware_catalog_refresh/failure`, `_get_current_hardware_catalog`, `_prepare_hardware_catalog_visuals` | `arayuz/donanim_entegrasyon.py` |
| Workspace aç/kapat/senkron (donanım, etki analizi, mimari çerçeve) | `open_hardware_workspace`, `open_hardware_cards_workspace`, `open_impact_analysis_workspace`, `open_architecture_framework_workspace`, `_on_*_workspace_closed`, `_refresh_*_workspace`, `_notify_architecture_*` | `arayuz/workspace_koordinasyon.py` |
| Copilot/sohbet | `_chat_send`, `_chat_worker`, `_find_target_id`, `_apply_revision`, `_ripple_regenerate`, `_clean_revision`, `_sync_item_text`, `COPILOT_SYSTEM_PROMPT` | `arayuz/copilot.py` |
| Dışa aktarım | `download_docs`, `_export_excel`, `_export_doors_csv`, `_split_requirement` | `arayuz/disa_aktarim.py` |
| Kalite denetimi | `run_kalite_denetimi` | `arayuz/pencere.py`'de kalabilir (tek metot, ayrı dosyaya değmez) |

**Hedef:** `Arayüz.py`, yalnızca `arayuz/pencere.py`'yi import edip
`TIDGeneratorApp`'ı kuran, `if __name__ == "__main__":` bloğunu barındıran
birkaç satırlık bir giriş noktasına iner (ya da `arayuz/pencere.py`
`TIDGeneratorApp`'ın kendisini tanımlar, `Arayüz.py` sadece
`from arayuz.pencere import TIDGeneratorApp` + çalıştırma bloğu olur).
`TIDGeneratorApp` sınıfının kendisi muhtemelen mixin/kompozisyon deseniyle
yukarıdaki alt modüllerdeki fonksiyonları bir araya getirir — bunun tam
tekniği (mixin sınıflar mı, yoksa `self.uretim = UretimAkisi(self)` gibi
delegasyon nesneleri mi) Faz 7'de bu adıma gelindiğinde, mevcut testlerin
(`tests/test_arayuz_background_flows.py` dahil) kırılmayacağı şekilde ayrıca
karara bağlanmalı.

---

## 4. Taşıma sırası (bağımlılık sırasına göre, yaprak modüller önce)

RISK_HARITASI.md'deki katmanlı yapı (`model → katalog/yönetim → render/ui`)
ve "döngüsel bağımlılık yok" bulgusu sayesinde bu sıra güvenle uygulanabilir:

1. **Yaprak/bağımsız modüller** (hiçbir iç modülü import etmeyen):
   `donanim_kartlari_model.py`, `mimari_cerceve_model.py`,
   `etki_analizi_logic.py`, `hardware_list_logic.py`, `config.py`,
   `app_identity.py`, `text_cleanup.py`.
2. **İkinci katman** (yalnızca 1. katmana bağımlı):
   `donanim_kartlari_gorsel.py`, `mimari_cerceve_katalog.py`,
   `hardware_image_provider.py`, `lmstudio_model.py`.
3. **Üçüncü katman** (izlenebilirlik çekirdeği + ona bağımlı olanlar):
   `etki_analizi_izlenebilirlik.py`'nin `core/izlenebilirlik.py`'ye taşınması
   (bölünmeden, bkz. 2a'nın güncellenmiş hâli), ardından
   `donanim_kartlari_algilama.py`, `donanim_kartlari_yonetim.py`,
   `mimari_cerceve_dogrulama.py`, `mimari_cerceve_gorunumleri.py`,
   `mimari_cerceve_cikarim.py`, `mimari_cerceve_yonetim.py`.
4. **Dördüncü katman** (render/orta katman):
   `mimari_cerceve_render.py`, `hardware_image_generation.py`,
   `hardware_image_prompt.py`, `etki_analizi_entegrasyon.py`,
   `etki_analizi_simulasyon.py`, `etki_analizi_degisim_paketi.py`,
   `etki_analizi_raporlama.py`, `rag_handler.py`, `llm_handler.py`.
5. **Beşinci katman** (UI dosyaları — en riskli, en büyük):
   `donanim_kartlari_karsilastirma_ui.py`, `donanim_detayli_inceleme*.py`,
   `hardware_image_generation_ui.py`, `hardware_list_ui.py`,
   `hardware_review_ui.py`, `etki_analizi_degisim_ui.py`,
   `etki_analizi_simulasyon_ui.py`, `etki_analizi_ui.py`,
   `donanim_kartlari_ui.py`, `mimari_cerceve_ui.py`.
6. **Son adım:** `Arayüz.py`'nin kendisi (bölüm 3'teki alt modüllere ayrılıp
   ince bir orkestrasyon dosyasına indirgenmesi). `main.py` bu süreç
   boyunca hiç değişmemeli (yalnızca `file_handler`, `data_processor`,
   `html_generation`, `config`, `rag_handler`'a bağımlı, hiçbiri
   yukarıdaki adımlarda import YOLU değişmeyecek şekilde taşınacak —
   re-export shim'leri sayesinde).

Her adımda: eski dosya, yeni konuma taşınan koddan `from <yeni_yol> import *`
yapan (ya da spesifik adları yeniden ihraç eden) bir shim'e dönüşür; böylece
o adımdan SONRA bile `import donanim_kartlari_model` gibi eski satırlar
kırılmadan çalışmaya devam eder. Tüm taşıma tamamlandıktan sonra (isteğe
bağlı, ayrı bir faz/karar) bu shim'ler kaldırılıp çağıranlar yeni yola
güncellenebilir — ama bu playbook'un zorunlu kapsamı değil.

---

## 5. Uygulama sırası / roadmap (her adım ayrı commit, aralarda pytest)

Faz 7 prompt'u (playbook'ta zaten tanımlı) her modül için tekrar tekrar
kullanılacak. Önerilen sıra (yukarıdaki 6 katmanı izler):

1. ✅ (Uygulandı) `donanim_kartlari_model.py` → `donanim_kartlari/model.py` + shim
2. ✅ (Uygulandı) `mimari_cerceve_model.py` → `mimari_cerceve/model.py` + shim
   (bu adımda `__all__`'ın eksik olduğu görüldü, shim tekniği
   `sys.modules[__name__] = _module` alias yöntemine yükseltildi — bkz.
   ilgili commit mesajları)
3. ✅ (Uygulandı) `etki_analizi_logic.py`, `hardware_list_logic.py`, `config.py`,
   `app_identity.py`, `text_cleanup.py` → ilgili klasörlere. Bu adımda
   `app_identity.py`'nin `resource_path()`'inin `__file__`'a göre proje
   kökünü bulduğu, taşıma sonrası `.parent.parent`'e düzeltilmesi gerektiği
   görüldü (davranış korundu, `test_app_identity.py` ile doğrulandı).
4. ✅ (Uygulandı) `donanim_kartlari_gorsel.py`, `mimari_cerceve_katalog.py`,
   `hardware_image_provider.py`, `lmstudio_model.py`
5. ✅ (Uygulandı) `etki_analizi_izlenebilirlik.py` → `core/izlenebilirlik.py`
   — **en riskli erken adım**, üç alan da buna bağımlı olduğu için özenle
   yapıldı, ayrı onay istendi. Sonuç: plandaki "böl" kararı, taşıma
   sırasındaki kullanım analizi sonucunda "tamamını taşı"ya revize edildi
   (bkz. 2a'nın güncellenmiş hâli) — dosya bölünmedi, olduğu gibi taşındı.
6. `donanim_kartlari_algilama.py`, `donanim_kartlari_yonetim.py`
7. `mimari_cerceve_dogrulama.py`, `mimari_cerceve_gorunumleri.py`,
   `mimari_cerceve_cikarim.py`, `mimari_cerceve_yonetim.py`
8. `mimari_cerceve_render.py`, `hardware_image_generation.py`,
   `hardware_image_prompt.py`
9. `etki_analizi_entegrasyon.py`, `etki_analizi_simulasyon.py`,
   `etki_analizi_degisim_paketi.py`, `etki_analizi_raporlama.py`
10. `rag_handler.py`, `rag_manager.py`, `rebuild_rag.py`,
    `llm_handler.py` → `rag/`, `llm/`
11. Belge üretim ailesi (`tid_generator_logic.py` ve kardeşleri) → `belge_uretim/`
12. UI dosyaları (5. katman, tek tek): karşılaştırma/detay UI'ları önce,
    `donanim_kartlari_ui.py` ve `mimari_cerceve_ui.py` en son (bunlar için
    Faz 7 adımına girerken önce dosyanın KENDİ İÇİ alt-modül planı ayrıca
    çıkarılmalı, bkz. bölüm 2 notu)
13. `Arayüz.py`'nin bölüm 3'teki alt modüllere ayrılması — **son adım**,
    en riskli; bu adımdan önce `tests/test_arayuz_background_flows.py`
    kapsamının yeterliliği tekrar gözden geçirilmeli.

Her adımdan sonra: `pytest tests/ -q` (tümü geçmeli), mümkünse ilgili
ekranın manuel duman testi (Faz 1/BASELINE.md'deki gibi), sonra tek bir
açıklayıcı commit. Adım 5 (izlenebilirlik taşıması — ✅ uygulandı) ve
adım 13 (Arayüz.py) öncesinde ayrıca kullanıcı onayı istenmesi öneriliyor
çünkü bunlar en çok sayıda çağıranı etkileyen, en riskli adımlar.

---

## 6. `donanim_kartlari_ui.py` ve `mimari_cerceve_ui.py` iç bölme planı — [EK, Faz 7'de eklendi]

**Durum:** Onay bekliyor. Roadmap madde 12'nin son iki dosyası
(`donanim_kartlari_ui.py`, `mimari_cerceve_ui.py`) için, taşıma adımına
gelmeden önce söz verilen "dosyanın kendi iç sorumluluk sınırları
incelenerek ayrıca planlanmalı" notunun karşılığı budur. Şu ana kadar
Faz 7'de hiçbir dosyanın **içi** bölünmedi (hep 1 dosya → 1 dosya taşındı);
bu ikisi ilk kez bir dosyayı birden fazla dosyaya bölmeyi gerektiriyor.

### 6.1 Ortak teknik: mixin sınıfları

Her iki dosya da tek bir devasa sınıfa (`HardwareCardsWorkspace`,
`ArchitectureFrameworkWorkspace`) ait ~100 metottan oluşuyor; metotların
neredeyse tamamı aynı `self` durumuna (widget'lar, filtre durumu, önbellek)
erişiyor. Bunu birden fazla dosyaya bölmenin davranışı bozmadan yapılabilecek
tek mekanik yolu **mixin sınıfları**dır: her dosyada, ilgili metot grubunu
taşıyan bir `_XyzMixin` sınıfı tanımlanır (state tanımlamaz, sadece metot
taşır); asıl `Workspace` sınıfı bu mixin'lerden çoklu kalıtımla türetilir.
Metotların **gövdesi tek bir satır bile değişmeden** olduğu gibi taşınır —
bu yüzden bu, "bölme" fazının (Faz 7) kapsamına uyar, davranış değiştirmez.
İsimlendirme çakışması riski yok çünkü zaten tek sınıfın metotlarıydı
(hepsi zaten benzersiz isimli).

Her iki dosya da bir paket haline getirilir (örn. `donanim_kartlari/ui.py`
→ `donanim_kartlari/ui/` klasörü + `__init__.py`); `__init__.py`,
`from .workspace import HardwareCardsWorkspace` ile eski
`donanim_kartlari.ui.HardwareCardsWorkspace` erişimini korur, kök
dizindeki `donanim_kartlari_ui.py` shim'i hiç değişmez (zaten
`from donanim_kartlari import ui as _module` yapıyor — `ui` bir dosya
yerine paket olsa da bu satır aynen çalışır).

### 6.2 `donanim_kartlari/ui/` hedef dosya haritası

Kaynak: `donanim_kartlari_ui.py` (2401 satır, `ScrollableCards`,
`HardwareEditorDialog`, `AlternativeDialog`, `HardwareCardsWorkspace` — 112
metot).

```
donanim_kartlari/ui/
  __init__.py        <- from .workspace import HardwareCardsWorkspace
                         (+ dışarıdan kullanılan diğer adlar, ör. testler
                         ScrollableCards'a erişiyorsa onu da)
  yardimcilar.py      <- modül seviyesi fonksiyonlar (_clean, _display,
                          _trace_node_index, catalog_filter_options,
                          product_tree_instances) + küçük yardımcı sınıflar
                          (ScrollableCards, HardwareEditorDialog,
                          AlternativeDialog)
  kurulum.py          <- _KurulumMixin: __init__, _build, _build_detail_tabs,
                          exists, focus, close, refresh, on_catalog_ready,
                          set_loading, set_simulation_result, _status_text,
                          _on_resize, refresh_language, apply_theme
  filtre.py           <- _FiltreMixin: _refresh_filters, _filter_value,
                          _search_focus_in/out, _focus_search,
                          _restore_preferences, _persist_preferences,
                          _filtered_items, _filters_changed,
                          _apply_filters_changed, _view_changed,
                          _clear_filters, _quality_filter_selected
  liste_render.py     <- _ListeRenderMixin: _render_all, _card_index,
                          _render_tree, _tree_*, _render_quality_strip,
                          _render_catalog_view, _apply_catalog_panel_span,
                          _has_next_page, _change_page, _group_label,
                          _render_compact_list, _render_catalog_tree_view,
                          _compact_*, _catalog_tree_*, _render_cards,
                          _build_card, _card_context_menu
                          (Faz 2'nin performans darboğazı bulduğu metotların
                          TAMAMI burada — Faz 8 optimizasyonu artık 2400
                          satırlık dosya yerine bu tek dosyaya odaklanabilir)
  karsilastirma.py    <- _KarsilastirmaMixin: _toggle_compare,
                          _update_compare_controls, _open_comparison,
                          _archive_item, _undo_last_change,
                          _make_card_image, _card_accent,
                          _update_card_selection, _trace_click,
                          _old_alternative_open, select_card
  detay_paneli.py     <- _DetayPaneliMixin: open_detailed_review,
                          _close_detailed_review, _save_detailed_fields,
                          _detail_*, _generate_selected_visual,
                          _open_bulk_image_generation,
                          _poll_selected_visual, _select_tree_recursive,
                          _render_detail, _evidence_for, _render_technical,
                          _render_requirements, _traceability_report,
                          _render_states, _render_alternatives,
                          _render_locations, _render_sources
  duzenleme.py        <- _DuzenlemeMixin: _persist_and_refresh,
                          _start_visual_generation, _poll_visual_generation,
                          _finish_visual_generation, _new_item, _edit_item,
                          _select_image, _remove_image,
                          _edit_technical_value, _load_datasheet, _rescan,
                          _load_sample, _add_alternative, _add_state,
                          _link_requirement, _reject_source_field
  gezinme.py          <- _GezinmeMixin: _send_to_impact, _go_parent,
                          _selected_requirement_id, _go_requirement,
                          _show_confidence, _show_change_summary
  workspace.py         <- class HardwareCardsWorkspace(_KurulumMixin,
                          _FiltreMixin, _ListeRenderMixin,
                          _KarsilastirmaMixin, _DetayPaneliMixin,
                          _DuzenlemeMixin, _GezinmeMixin): pass
                          (gövdesi neredeyse boş; sınıf birleşimi burada)
```

9 dosya, her biri ~100-350 satır arası (en büyüğü `liste_render.py` ve
`detay_paneli.py`, ~500-600 satır civarı olabilir — gerekirse ikiye daha
bölünebilir, taşıma sırasında netleşir).

### 6.3 `mimari_cerceve/ui/` hedef dosya haritası

Kaynak: `mimari_cerceve_ui.py` (2936 satır, `WorkflowStep`, `ProfileOption`,
`SourceRequirement`, `ArchitectureFrameworkWorkspace` — 95 metot). Bu sınıf
zaten kod içinde açık bir iş akışına (kaynak seç → çıkar → görünümler →
aday incele/onayla → render/önizle → doğrula → yayımla) karşılık geliyor;
bölme bu akışı izliyor.

```
mimari_cerceve/ui/
  __init__.py          <- from .workspace import ArchitectureFrameworkWorkspace
  yardimcilar.py        <- modül seviyesi fonksiyonlar (filter_candidate_records,
                           layout_mode_for_width, _clean,
                           filter_source_requirements, _has_integrity_error,
                           classify_view_card_state, view_card_status_label)
                           + veri sınıfları (WorkflowStep, ProfileOption,
                           SourceRequirement)
  kurulum.py            <- _KurulumMixin: __init__, exists, focus, close,
                           _language, _tr, _palette, _label, _button,
                           _build, _build_source_panel, _build_center_panel,
                           _build_inspector_panel, _select_step,
                           _show_narrow_panel_for_step, _on_resize,
                           _apply_responsive_layout, _toggle_language,
                           _toggle_theme, refresh_language, apply_theme
  kaynak_yonetimi.py    <- _KaynakMixin: refresh, on_sources_changed,
                           on_source_mutation_started, _source_change_worker,
                           _finish_source_change, on_generation_started,
                           on_traceability_ready, on_generation_failed,
                           _ensure_sources_ready, _ensure_extraction_ready,
                           _ensure_current_project_context,
                           _reset_project_context, _filtered_sources,
                           _refresh_source_tree, _update_source_count,
                           _selected_source_ids, _busy
  cikarim_akisi.py      <- _CikarimMixin: _start_extraction,
                           _project_context_matches, _dispatch_after,
                           _poll_ui_queue, _extraction_worker,
                           _extraction_guard_is_current,
                           _prepare_extraction_state, _finish_extraction
  gorunum_kartlari.py   <- _GorunumMixin: _on_profile_changed,
                           _invalidate_architecture_outputs,
                           _rebuild_view_cards, _select_view, _view_status,
                           _refresh_view_cards
  aday_inceleme.py      <- _AdayMixin: _candidate_filter_mode,
                           _on_candidate_filter_changed,
                           _select_all_candidates, _refresh_candidate_tree,
                           _selected_records, _selected_record,
                           _proposal_stable_id, _set_text,
                           _show_selected_candidate,
                           _populate_validation_findings,
                           _selected_unresolved_conflicts,
                           _update_review_controls, _persist_review_state,
                           _capture_review_guard, _review_guard_is_current,
                           _report_stale_review_block, _review_transaction,
                           _element_record_index, _endpoint_closure,
                           _approve_selected, _reject_selected,
                           _edit_selected, _resolve_selected_conflict
  render_onizleme.py    <- _RenderMixin: _build_snapshot, _start_render,
                           _rasterize_svg_preview, _render_worker,
                           _finish_render, _clear_preview, _display_svg
  dogrulama.py          <- _DogrulamaMixin: _validate_current,
                           _validation_worker, _finish_validation
  disa_aktarim_yayim.py <- _YayimMixin: _export_svg, _start_publish,
                           _finish_publish
  workspace.py          <- class ArchitectureFrameworkWorkspace(_KurulumMixin,
                           _KaynakMixin, _CikarimMixin, _GorunumMixin,
                           _AdayMixin, _RenderMixin, _DogrulamaMixin,
                           _YayimMixin): pass
```

10 dosya, çoğu ~100-250 satır; `aday_inceleme.py` en büyüğü (~700 satır
civarı — bu, dosyanın en karmaşık tek sorumluluğu olan "aday onay/red/
düzenleme + çakışma çözümü" iş mantığını taşıyor, gerekirse ileride
kendi içinde de bölünebilir).

### 6.4 Uygulama sırası ve risk notu

Her iki dosya için de:
1. Modül seviyesi fonksiyonlar/veri sınıfları önce `yardimcilar.py`'ye taşınır.
2. Mixin'ler tek tek çıkarılır (en bağımsız/en az çapraz-referanslı gruptan
   başlanarak) — her mixin çıkarma adımı kendi commit'i olabilir ya da tek
   dosya taşıma işlemi için tüm mixin'ler birlikte tek commit'te de
   yapılabilir (dosya sayısı çok ama hepsi aynı mekanik "kopyala/kes" işlemi).
3. `workspace.py` en son yazılır (tüm mixin'ler hazır olduktan sonra).
4. `pytest tests/ -q` + gerçek `Arayüz.py` duman testi + ilgili workspace'in
   (donanım kartları / mimari çerçeve) manuel olarak açılıp temel
   etkileşimlerin (liste render, filtre, detay paneli, mimari çerçeve için
   kaynak seç → çıkar → görünüm oluştur adımları) çalıştığının kontrolü.

**Risk:** `tests/test_mimari_cerceve_ui.py` (~83 KB, en kapsamlı test
dosyası) ve donanım kartları tarafındaki QA script'leri
(`tests/_hardware_cards_*`) `object.__new__(Workspace)` deseniyle sınıfın
üzerinde doğrudan metot çağırıyor (bkz. Faz 5) — mixin'e bölünme bu
deseni BOZMAMALI çünkü Python'da `object.__new__(HardwareCardsWorkspace)`
ile oluşturulan örnek, sınıf MRO'sundaki (mixin'ler dahil) tüm metotlara
zaten erişebilir. Yine de bölme sonrası bu iki büyük test dosyasının
tamamının geçtiği ayrıca doğrulanmalı (zaten `pytest tests/ -q` kapsamında).

---

## Onay

Bu plan onaylanmadan Faz 7'ye geçilmeyecek. Onaydan sonra Faz 7 prompt'u
yukarıdaki sıradaki **ilk modülle** (`donanim_kartlari_model.py`)
başlatılacak.

[GÜNCELLEME] Faz 7, bu belgedeki roadmap'in 11. adımına kadar (belge
üretim ailesi dahil) onaylanıp uygulandı; UI dosyalarının çoğu (roadmap
12) da tek-dosya-taşı yöntemiyle tamamlandı. Bölüm 6'daki iç-bölme planı,
kalan iki en büyük dosya (`donanim_kartlari_ui.py`, `mimari_cerceve_ui.py`)
için ayrıca onay bekliyor.
