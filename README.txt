====================================================================
  V-MODEL TEKNIK DOKUMAN URETIM UYGULAMASI  (EHSIM)
====================================================================

Bu dosyayi bastan sona oku, adimlari sirayla yap.

Gunluk kullanim icin daha kisa/pratik bir rehber istersen
EHSIM_NASIL_CALISTIRILIR.txt dosyasina da bakabilirsin.


1) GEREKSINIMLER (bir kez kurulur)
--------------------------------------------------------------------
 - Python 3.12 : python.org adresinden indir. Kurarken
   "Add Python to PATH" kutucugunu MUTLAKA isaretle.
 - VSCode + Python eklentisi (Microsoft) - opsiyonel ama onerilir.
 - LM Studio : indir, ac ve icine bir model yukle. Varsayilan olarak
   uygulama "google_gemma-3-4b-it" modelini arar:
       google_gemma-3-4b-it
   (LM Studio > sol ustteki arama > model adini yaz > indir.)
   Farkli bir model kullanmak istersen (ornegin "gemma-4-e4b-it"),
   config.py'yi degistirmene gerek yok - Adim 5'te anlatilan
   EHSIM_LM_MODEL ortam degiskeniyle calisma zamaninda secebilirsin.
   ONEMLI: Uygulamayi kullanirken LM Studio ACIK, model YUKLU ve
   "Local Server" BASLATILMIS olmali (http://localhost:1234).


2) PROJEYI EDIN
--------------------------------------------------------------------
 Bu repoyu klonla (ya da zip olarak indirip cikart). Icinde kod
 dosyalari (.py), requirements.txt ve gerekli varliklar var.

 NOT: "HuggingFaceEmbeddings/" klasoru (yerel embedding modeli,
 ~88 MB) bilinçli olarak repoya dahil edilmemistir (buyuk ve tekrar
 indirilebilir oldugu icin .gitignore'da). Uygulamayi ilk calistirmadan
 once bunu bir kez kendin indirmen gerekir:
   1. https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
      adresine git.
   2. "Files and versions" sekmesindeki TUM dosyalari indir.
   3. Proje klasorunde HuggingFaceEmbeddings\all-MiniLM-L6-v2\ yolunu
      olustur ve indirdigin dosyalari oraya koy.
 Bu adim atlanirsa dokuman uretimi "Embedding Hatasi: Path ... not
 found" diye basarisiz olur.


3) SANAL ORTAM + PAKETLER (bir kez, internet gerekir)
--------------------------------------------------------------------
 Proje klasorunun icinde bir terminal ac (VSCode'da Terminal > New
 Terminal, ya da klasorde Shift+Sag tik > "PowerShell penceresi
 burada ac") ve su 3 satiri sirayla calistir:

     py -3.12 -m venv .venv
     .\.venv\Scripts\python.exe -m pip install --upgrade pip
     .\.venv\Scripts\python.exe -m pip install -r requirements.txt

 Bu adim paketleri indirir, birkac dakika surer. Sadece BIR kez yapilir.


4) CALISTIR
--------------------------------------------------------------------
 Ayni terminalde (LM Studio'da hangi modeli yuklediysen o modelin
 adini EHSIM_LM_MODEL ile bildirdikten sonra):

     $env:EHSIM_LM_MODEL = "google_gemma-3-4b-it"    # yuklu modelinle degistir
     .\.venv\Scripts\python.exe "Arayüz.py"

 veya VSCode'da "Arayüz.py" dosyasini acip F5'e bas (bu durumda
 EHSIM_LM_MODEL'i o terminalde ayri ayarlaman gerekir, aksi halde
 varsayilan "google_gemma-3-4b-it" aranir).


5) MODEL SECIMI (EHSIM_LM_MODEL)
--------------------------------------------------------------------
 Uygulama varsayilan olarak "google_gemma-3-4b-it" modelini arar
 (bkz. config.py > DEFAULT_MODEL_NAME). LM Studio'da farkli bir model
 yuklediysen (ornegin "gemma-4-e4b-it"), her yeni terminal penceresinde
 calistirmadan ONCE su satiri yaz:

     $env:EHSIM_LM_MODEL = "gemma-4-e4b-it"

 Tirnak icindeki isim, LM Studio'da yuklu modelin TAM ismiyle birebir
 ayni olmali. Bu adim atlanirsa (ya da yanlis yazilirsa) uygulama
 hicbir hata gostermeden BOS sonuclar uretir (SGD/STT gibi bolumler
 bos cikar) - bu en sik karisilan sorundur.


6) KULLANIM
--------------------------------------------------------------------
 1. LM Studio acik + dogru model yuklu ve sunucu baslatilmis oldugundan
    emin ol.
 2. "Girdi Dosyalari" kismina bir teknik-ister PDF'i surukle-birak
    (ya da "..." dugmesiyle sec).
 3. Gereksinim sayilarini gir (ornek: 15 / 15 / 15). Buyuk sayilar
    (20-30+) da artik guvenle uretilebiliyor, tek cagrida sabit bir
    tavana takilmiyor.
 4. "Dokumanlari Uret"e bas, uretim bitene kadar bekle.
 5. "Dokumanlari Indir" ile PDF / Excel / Word / DOORS (CSV) olarak
    kaydet.


SIK KARSILASILAN SORUNLAR
--------------------------------------------------------------------
 - "Baglanti reddedildi" hatasi  -> LM Studio kapali ya da "Local
                                    Server" baslatilmamis. Ac ve
                                    kontrol et.
 - SGD/STT gibi bolumler BOS geliyor, uretim 1-2 saniyede bitiyor
                                 -> Adim 5'teki EHSIM_LM_MODEL adi,
                                    LM Studio'daki yuklu modelin
                                    ismiyle birebir ayni degil.
 - "Embedding Hatasi: Path ... HuggingFaceEmbeddings ... not found"
                                 -> Adim 2'deki embedding modelini
                                    henuz indirmedin/dogru yere
                                    koymadin.
 - Surukle-birak calismiyor      -> requirements.txt zaten tkinterdnd2
                                    kurar; olmazsa "..." dugmesini
                                    kullan.
 - Python bulunamadi (py komutu) -> Python 3.12 kurulu degil ya da
                                    PATH'e eklenmemis. Adim 1'i tekrar
                                    yap.

Kolay gelsin.


7) COMFYUI ILE AI DONANIM GORSELI (istege bagli)
--------------------------------------------------------------------
 ComfyUI baglantisi varsayilan olarak kapalidir ve uygulamanin diger
 ozelliklerini etkilemez. Kurulum, API workflow hazirlama, ortam
 degiskenleri ve guvenli kabul akisi icin COMFYUI_KURULUM.md dosyasini
 okuyun.
