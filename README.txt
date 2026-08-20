====================================================================
  V-MODEL TEKNIK DOKUMAN URETIM UYGULAMASI  -  GEMMA PAKETI
  Bu paket "google_gemma-3-4b-it" modeliyle calisir.
====================================================================

Bu dosyayi bastan sona oku, adimlari sirayla yap.


1) GEREKSINIMLER (bir kez kurulur)
--------------------------------------------------------------------
 - Python 3.12 : python.org adresinden indir. Kurarken
   "Add Python to PATH" kutucugunu MUTLAKA isaretle.
 - VSCode + Python eklentisi (Microsoft).
 - LM Studio : indir, ac ve icine su modeli yukle:
       google_gemma-3-4b-it
   (LM Studio > sol ustteki arama > "google_gemma-3-4b-it" yaz > Q4_K_M olani indir.)
   ONEMLI: Uygulamayi kullanirken LM Studio ACIK ve model YUKLU olmali.


2) KLASORU YERLESTIR
--------------------------------------------------------------------
 Bu "gemma" klasorunu bilgisayarina cikar. Icinde her sey var:
   - Tum kod dosyalari (.py)
   - HuggingFaceEmbeddings\  (embedding modeli - tekrar indirmeye gerek yok)
   - requirements.txt
 NOT: Klasorde .venv YOKTUR; asagida bir kez kendin olusturacaksin.


3) SANAL ORTAM + PAKETLER (bir kez, internet gerekir)
--------------------------------------------------------------------
 Klasorun icinde bir terminal ac (VSCode'da Terminal > New Terminal,
 ya da klasorde Shift+Sag tik > "PowerShell penceresi burada ac")
 ve su 3 satiri sirayla calistir:

     py -3.12 -m venv .venv
     .\.venv\Scripts\python.exe -m pip install --upgrade pip
     .\.venv\Scripts\python.exe -m pip install -r requirements.txt

 Bu adim paketleri indirir, birkac dakika surer. Sadece BIR kez yapilir.


4) CALISTIR
--------------------------------------------------------------------
 Ayni terminalde:

     .\.venv\Scripts\python.exe "Arayüz.py"

 veya VSCode'da "Arayüz.py" dosyasini acip F5'e bas.


5) KULLANIM
--------------------------------------------------------------------
 1. LM Studio acik + "google_gemma-3-4b-it" yuklu oldugundan emin ol.
 2. "Girdi Dosyalari" kismina bir teknik-ister PDF'i surukle-birak
    (ya da "..." dugmesiyle sec).
 3. Gereksinim sayilarini gir (ornek: 15 / 15 / 15).
 4. "Dokumanlari Uret"e bas, uretim bitene kadar bekle.
 5. "Dokumanlari Indir" ile PDF / Excel / Word / DOORS (CSV) olarak kaydet.


SIK KARSILASILAN SORUNLAR
--------------------------------------------------------------------
 - "Baglanti reddedildi" hatasi  -> LM Studio kapali. Ac ve modeli yukle.
 - "Model bulunamadi"            -> LM Studio'daki model adi ile config.py
                                    icindeki MODEL_NAME ayni olmali:
                                    MODEL_NAME = "google_gemma-3-4b-it"
 - Surukle-birak calismiyor      -> requirements.txt zaten tkinterdnd2
                                    kurar; olmazsa "..." dugmesini kullan.
 - Python bulunamadi (py komutu) -> Python 3.12 kurulu degil ya da PATH'e
                                    eklenmemis. Adim 1'i tekrar yap.

Kolay gelsin.


6) COMFYUI ILE AI DONANIM GORSELI (istege bagli)
--------------------------------------------------------------------
 ComfyUI baglantisi varsayilan olarak kapalidir ve uygulamanin diger
 ozelliklerini etkilemez. API workflow hazirlama, ortam degiskenleri ve
 guvenli kabul akisi icin COMFYUI_KURULUM.md dosyasini okuyun.
