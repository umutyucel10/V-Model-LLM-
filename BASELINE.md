# BASELINE — Faz 1 Çalıştırılabilirlik Doğrulaması

**Tarih:** 2026-08-28
**Ortam:** Windows 11, Python 3.12.10, `.venv` (proje kökünün bir üst dizininde,
`staj Ehsim duplicated/.venv`)

## 1. Bağımlılık kurulumu
`pip install -r requirements.txt` çalıştırıldı — tüm paketler zaten kuruluymuş
(`Requirement already satisfied`). Ek olarak `pytest` (requirements.txt'te yok
ama `tests/` klasörü için gerekli) kuruldu: `pytest-9.1.1`, `pluggy-1.6.0`,
`iniconfig-2.3.0`.

## 2. `pytest tests/ -q` sonucu
```
381 passed, 3 warnings, 67 subtests passed in 22.16s
```
- **Kırılan test yok.**
- **Atlanan (skip) test yok.**
- Uyarılar (hata değil, davranışı etkilemiyor):
  - `rag_handler.py:8` — `langchain-community` paketinin sunset/deprecated
    olduğu uyarısı (`PyPDFDirectoryLoader` importu).
  - `tests/test_mimari_cerceve_onizleme.py` (2 test) — Pillow
    `Image.getdata` deprecated uyarısı (Pillow 14'te kaldırılacak).

## 3. Uygulama başlatma denemesi
- `python -c "import Arayüz"` → başarılı, hata yok. (`mainloop()` çağrısı
  `if __name__ == "__main__":` bloğu içinde olduğu için import sırasında
  pencere açılmıyor — bu iyi bir işaret, modül import edilebilir durumda.)
- `python "Arayüz.py"` doğrudan çalıştırıldı (duman testi): pencere
  ("EHSİM" başlıklı) sorunsuz açıldı, konsola sadece bir PyMuPDF/`fitz`
  deprecation uyarısı düştü, kritik hata/traceback yok. ~8 saniye açık
  tutulup manuel olarak kapatıldı.
- LM Studio bu ortamda zaten **açık ve erişilebilir** durumda
  (`http://localhost:1234/v1/models` yanıt veriyor). **Ancak yüklü model
  `gemma-4-e4b-it`; `config.py`'deki varsayılan `MODEL_NAME` ise
  `google_gemma-3-4b-it`.** Bu bir isim uyuşmazlığı — muhtemelen bu ortamda
  bilinçli olarak farklı/daha küçük bir test modeli yüklenmiş
  (`lmstudio_model.py` içindeki `is_gemma4_e4b_model` fonksiyonunun varlığı
  bunun bilinen bir durum olduğunu düşündürüyor). Playbook'un konusu değil,
  ama LLM akışlarını uçtan uca test ederken göz önünde bulundurulmalı.
- `main.py` da aynı şekilde `if __name__ == "__main__":` guard'lı; import
  seviyesinde çalıştırılmadı (CLI toplu akış canlı bir TİD PDF'i + LLM
  çağrısı gerektirdiği için bu fazda tetiklenmedi).

## 4. "Zaten kırık" olarak not düşülen durumlar
Bu çalıştırmada **kod veya test seviyesinde kırık bir şey bulunamadı**.
Tek not edilecek konu:
- **Model adı uyuşmazlığı** (yukarıda 3. maddede açıklandı) — refactor'un
  sebep olduğu bir kırılma değil, ortamın mevcut hâli.
- `rag_chroma_lms/` altında commit'lenmiş bir Chroma koleksiyonu
  (`ab3a98a2-...`) var; bu playbook'un Faz 1 sonrası ele alacağı depo
  hijyeni (Faz 4) kapsamında ayrıca değerlendirilecek, burada sadece not
  düşülüyor.

## Sonuç
Refactor öncesi temel çizgi **yeşil**: 381/381 test geçiyor, GUI import ve
başlatma sorunsuz. Sonraki fazlarda bir test kırılırsa ya da uygulama
başlamazsa, bu BASELINE.md ile karşılaştırılarak refactor kaynaklı olup
olmadığı ayırt edilebilir.
