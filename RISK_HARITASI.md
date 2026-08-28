# RİSK HARİTASI (Faz 3 — Statik Analiz)

**Tarih:** 2026-08-28
**Araç:** `radon` (cyclomatic complexity + maintainability index), `wc -l`, `grep`
tabanlı import taraması. Kod değişikliği yapılmadı, sadece analiz.

---

## 1. Karmaşıklık sıralaması

`radon mi` (maintainability index, 0-100, düşük = kötü) çalıştırıldığında
repodaki **18 dosya tam 0.00 puanla tabana çarptı** — radon'un ayırt
edemeyeceği kadar kötü. Bu 18 dosyayı `radon cc` (cyclomatic complexity,
fonksiyon/metot bazında A-F harf notu) ile derinleştirip LOC ile birlikte
sıraladım. Puan = `F×5 + E×3 + D×2 + C×1` (F/E/D/C notlu blok sayıları).

| # | Dosya | LOC | MI | F/E/D/C blok sayısı | Risk puanı | Not |
|---|---|---|---|---|---|---|
| 1 | `mimari_cerceve_yonetim.py` | 2169 | 0.00 | F=2 E=3 D=1 C=10 | **31** | `publish_approved_architecture` (F, CC=67), `reconcile_candidates` (F, CC=56) |
| 2 | `donanim_kartlari_algilama.py` | 1450 | 0.00 | F=2 E=2 D=2 C=8 | **28** | `_structured_candidate`, `build_or_update_hardware_catalog` (ikisi de F) |
| 3 | `mimari_cerceve_model.py` | 1950 | 0.00 | F=1 E=2 D=1 C=11 | **24** | `ArchitectureSnapshot.__post_init__` (F, CC değil ama en karmaşık) |
| 4 | `donanim_kartlari_yonetim.py` | 1164 | 0.00 | F=3 E=1 D=1 C=2 | **22** | `apply_overrides`, `filter_cards`, `build_multi_comparison` (3 ayrı F) |
| 5 | `mimari_cerceve_ui.py` | 2936 | 0.00 | F=0 E=0 D=1 C=19 | **21** | En büyük dosya (satır sayısı); tekil fonksiyon karmaşıklığı diğerleri kadar uç değil ama hacim başlı başına risk |
| 6 | `Arayüz.py` | 3208 | 0.00 | F=1 E=1 D=0 C=12 | **20** | `run_ai_process` (F, CC yüksek) — ana orkestrasyon metodu |
| 7 | `donanim_kartlari_ui.py` | 2401 | 0.00 | F=0 E=0 D=4 C=11 | **19** | En büyük 2. dosya; Faz 2'de performans darboğazı da burada ölçüldü |
| 8 | `mimari_cerceve_cikarim.py` | 1404 | 0.00 | F=1 E=1 D=1 C=6 | **16** | `extract_architecture_candidates` (F) |
| 9 | `hardware_image_provider.py` | 1064 | 0.00 | F=0 E=1 D=2 C=9 | **16** | Playbook'un orijinal listesinde yoktu, analiz bunu da riskli çıkardı |
| 10 | `etki_analizi_simulasyon.py` | 1747 | 0.00 | F=0 E=0 D=4 C=7 | **15** | |

**Onur listesinde olup 10'a giremeyen ama MI=0.00 olan diğer dosyalar:**
`donanim_detayli_inceleme_ui.py`, `etki_analizi_degisim_paketi.py` (F=2,
puan 15), `etki_analizi_ui.py`, `etki_analizi_izlenebilirlik.py`,
`mimari_cerceve_dogrulama.py` (F=1 E=2 D=1, puan 14),
`mimari_cerceve_render.py` (F=1 D=1, `_semantic_projection_missing` F notu),
`etki_analizi_simulasyon_ui.py`, `Arayüz_yedek.py` (bkz. bölüm 2).

**Playbook'un orijinal "büyük dosya" listesiyle fark:** `hardware_image_provider.py`
ve `donanim_detayli_inceleme_ui.py` playbook'ta adı geçmiyordu ama radon
analizinde MI=0.00 çıktı — bu iki dosya da refactor kapsamına dahil edilmeli.
Buna karşılık `llm_handler.py` (playbook'ta "büyük/riskli" diye anılıyordu)
MI=3.04 ile düşük ama 0'dan yüksek; `rag_handler.py` MI=17.28 — ikisi de
kötü ama en acil 10'un dışında kalıyor.

En yüksek tekil fonksiyon karmaşıklığı (F notu, CC≥50):
`mimari_cerceve_yonetim.py: publish_approved_architecture` **CC=67**,
`mimari_cerceve_yonetim.py: reconcile_candidates` **CC=56**,
`Arayüz.py: TIDGeneratorApp.run_ai_process` **CC yüksek (F)**,
`Arayüz_yedek.py: TIDGeneratorApp.run_ai_process` **F** (aynı metodun eski kopyası).

---

## 2. `Arayüz.py` vs `Arayüz_yedek.py` — ölü kod doğrulaması

- **Referans taraması:** `grep -rn "Arayüz_yedek"` tüm `.py`, `.md`, `.bat`,
  `.txt`, `.json` dosyalarında yalnızca bu playbook'un kendi belgelerinde
  (`CLAUDE.md`, `PERFORMANS_REFAKTOR_PLAYBOOK.md`) geçiyor — **hiçbir kod
  dosyası `Arayüz_yedek.py`'yi import etmiyor veya çalıştırmıyor.**
- **Git geçmişi:** Depo tek bir "Initial commit" ile başlıyor (squash edilmiş
  geçmiş), dosyanın ne zaman/neden eklendiği git'ten çıkarılamıyor.
- **İçerik karşılaştırması** (üst düzey metot imzaları): `Arayüz.py` (3208
  satır) `Arayüz_yedek.py`'de (1662 satır) **bulunmayan onlarca metot**
  içeriyor — donanım kartları entegrasyonu, mimari çerçeve entegrasyonu,
  etki analizi/değişim paketi akışı, dil/tema değiştirme, DOORS CSV export,
  sürükle-bırak vb. `Arayüz_yedek.py`'de olup `Arayüz.py`'de aynı isimle
  bulunmayan yalnızca 2 metot var (`start_classification`,
  `run_classification_process`) — muhtemelen sonradan yeniden adlandırılmış/
  kaldırılmış eski bir sınıflandırma akışı.
- **Sonuç:** `Arayüz_yedek.py`, `Arayüz.py`'nin bugünkü özellik setinin
  çok gerisinde kalmış, **kullanılmayan bir eski yedek**.

**Öneri: SİL.** Gerekçe: (1) hiçbir çağıran yok, (2) mevcut dosyanın çok
gerisinde/eski, (3) MI=0.00 + F notlu `run_ai_process` kopyası — silinmezse
gelecekteki bir refactor turunda yanlışlıkla "aktif kod" sanılıp üzerinde
zaman harcanma riski var. Depoda tek commit olduğu için "git ile geri
getirilebilir" güvencesi de zaten sınırlı; yine de silme işlemi kendi
commit'inde yapılıp mesajda açıkça not düşülmeli (Faz 4'ün konusu).

---

## 3. Bağımlılık grafiği (iş alanı içi ve arası)

### donanim_kartlari ailesi
```
donanim_kartlari_model.py  (taban, bağımsız)
        ^
        |
donanim_kartlari_gorsel.py
donanim_kartlari_algilama.py -----> etki_analizi_izlenebilirlik.py (*)
donanim_kartlari_yonetim.py  -----> etki_analizi_izlenebilirlik.py (*)
        ^
        |
donanim_kartlari_karsilastirma_ui.py
donanim_detayli_inceleme.py -> donanim_kartlari_model.py
donanim_detayli_inceleme_raporlama.py -> donanim_detayli_inceleme.py, hardware_image_generation.py
donanim_detayli_inceleme_ui.py -> donanim_detayli_inceleme(+raporlama)
        ^
        |
donanim_kartlari_ui.py  (en üstte; hepsini + hardware_image_generation_ui,
                          hardware_image_provider'ı toplar)
```

### etki_analizi ailesi
```
etki_analizi_izlenebilirlik.py  (taban, bağımsız — ama bkz. not *)
        ^
        |
etki_analizi_logic.py (bağımsız, izlenebilirlik'e bile bağımlı değil)
etki_analizi_entegrasyon.py -> izlenebilirlik
etki_analizi_simulasyon.py  -> izlenebilirlik
        ^
        |
etki_analizi_degisim_paketi.py -> izlenebilirlik, simulasyon
etki_analizi_raporlama.py (bağımsız, sadece 3.parti export kütüphaneleri)
        ^
        |
etki_analizi_degisim_raporlama.py -> degisim_paketi, raporlama(_register_pdf_fonts)
etki_analizi_degisim_ui.py       -> degisim_paketi, degisim_raporlama
etki_analizi_simulasyon_ui.py    -> entegrasyon, simulasyon, degisim_paketi, degisim_ui
        ^
        |
etki_analizi_ui.py  (en üstte; logic+raporlama+simulasyon+simulasyon_ui'yi toplar)
```

### mimari_cerceve ailesi
```
mimari_cerceve_model.py  (taban, bağımsız)
        ^
        |
mimari_cerceve_katalog.py -> model
        ^
        |
mimari_cerceve_gorunumleri.py -> katalog, model
mimari_cerceve_dogrulama.py   -> katalog, model
        ^
        |
mimari_cerceve_render.py  -> dogrulama, gorunumleri, model
mimari_cerceve_cikarim.py -> katalog, model, etki_analizi_izlenebilirlik (*)
mimari_cerceve_yonetim.py -> katalog, model, etki_analizi_izlenebilirlik (*)
        ^
        |
mimari_cerceve_ui.py  (en üstte; cikarim+dogrulama+render+yonetim+gorunumleri+katalog'u toplar)
```

### (*) Alanlar arası bağımlılık — mimari not
`etki_analizi_izlenebilirlik.py` (`atomic_write_json`, `project_identity`,
ve diğer izlenebilirlik yardımcıları), adının aksine **üç iş alanı
tarafından da** kullanılıyor: `etki_analizi_*` (beklenen), ayrıca
`donanim_kartlari_algilama.py`/`donanim_kartlari_yonetim.py` **ve**
`mimari_cerceve_cikarim.py`/`mimari_cerceve_yonetim.py`. Yani bu dosya
aslında "etki analizi" alanına özel değil, üç alanın da paylaştığı **örtük
bir çekirdek/ortak modül** rolünde. Faz 6'nın hedef klasör haritasını
çıkarırken bu dosyanın (ya da içindeki paylaşılan fonksiyonların)
`etki_analizi/` altında değil, ortak bir `core/`/`shared/` konumunda
yaşaması değerlendirilmeli.

### Döngüsel bağımlılık
**Bulunamadı.** Her üç iş alanı da kendi içinde temiz, katmanlı bir yapıya
sahip (`model → katalog/yönetim yardımcıları → render/ui`), döngü yok.
Üç iş alanı **birbirini doğrudan import etmiyor** — yalnızca ortak
`etki_analizi_izlenebilirlik.py`'ye bağımlılar (yukarıdaki not) ve hepsi
`Arayüz.py` tarafından en üstten birleştiriliyor. Bu, Faz 6/7'deki
modül taşıma işini nispeten güvenli kılan iyi bir haber: alanlar arası
"spagetti" import yok, sadece tek dosyalar aşırı büyük/karmaşık.

---

## 4. Öncelikli aksiyon tablosu

| Dosya | Önerilen aksiyon | Gerekçe |
|---|---|---|
| `Arayüz_yedek.py` | **Sil** (Faz 4) | Kullanılmıyor, eski, MI=0.00 |
| `mimari_cerceve_yonetim.py` | **Böl** (Faz 7) | En yüksek risk puanı; `publish_approved_architecture` (CC=67) ve `reconcile_candidates` (CC=56) ayrı, test edilebilir fonksiyonlara ayrılmalı |
| `donanim_kartlari_algilama.py` | **Böl** (Faz 7) | 2 adet F notlu fonksiyon; Faz 2'de bu ailenin UI tarafı (donanim_kartlari_ui.py) zaten performans sorunu gösterdi |
| `mimari_cerceve_model.py` | **Sadeleştir** (Faz 7) | `ArchitectureSnapshot.__post_init__` çok fazla doğrulama mantığı taşıyor; ayrı validator fonksiyonlarına çıkarılabilir |
| `donanim_kartlari_yonetim.py` | **Böl** (Faz 7) | 3 adet F notlu fonksiyon (`apply_overrides`, `filter_cards`, `build_multi_comparison`) |
| `mimari_cerceve_ui.py`, `Arayüz.py`, `donanim_kartlari_ui.py` | **Böl + test ekle** (Faz 6 planı + Faz 7) | Hacim (LOC) ve sorumluluk çeşitliliği en yüksek 3 dosya; Faz 6'nın ana hedefi |
| `hardware_image_provider.py` | **Sadeleştir + test ekle** | Playbook'ta yoktu ama MI=0.00; `ComfyUIImageProvider.generate_image` E notlu |
| `etki_analizi_izlenebilirlik.py` | **Taşı/yeniden konumlandır** (Faz 6 planında değerlendir) | Üç alanın ortak bağımlılığı; "etki_analizi" adı yanıltıcı |
| `llm_handler.py`, `rag_handler.py` | **Dokunma (bu fazda) / Faz 9'da optimize et** | MI düşük ama en acil 10'un dışında; Faz 2 raporunda zaten davranışsal (performans) bulgular var, oraya odaklan |
| `mimari_cerceve_render.py` | **Dokunma** | Faz 2'de darboğaz olmadığı ölçüldü; karmaşıklık notu (F=1) var ama performans riski yok |

Kod değişikliği yapılmadı; bu dosya yalnızca analiz ve önceliklendirmedir.
