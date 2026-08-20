# EHSİM Mimari Çerçeve Tasarımı

> **Belge durumu:** Kart 0 tasarım kararı — henüz uygulanmadı  
> **Hedef profil sürümleri:** DoDAF 2.02 ve NAF 4.1  
> **NAF için EHSİM varsayılan uygulama profili:** ArchiMate 3.2  
> **Son doğrulama tarihi:** 2026-08-12

## 1. Amaç ve mevcut durum

Bu belge, EHSİM'in mevcut V-Model belge ve izlenebilirlik verilerinden DoDAF ve
NAF mimari görünümleri üretmesi için uygulanacak kapsamı, kanıt sınırını,
onay kapılarını ve sürümleme modelini tanımlar. Bu bir uygulama tasarımıdır;
bugün projede DoDAF, NAF, ArchiMate, DM2/PES veya mimari model değişim
katmanı bulunmamaktadır.

Mevcut ve yeniden kullanılacak gerçek altyapı:

- `Arayüz.py`: TID, SGD, STT, KMTD, SITET ve AST üretimini yönetir; uzun
  izlenebilirlik işlerini arka plan iş parçacığında çalıştırır ve Tkinter'a
  `after(...)` ile döner.
- `etki_analizi_izlenebilirlik.py`: kaynak belge/bölüm, kanıt metni, güven
  derecesi, düğüm ve bağ içeren sürümlü izlenebilirlik grafiğini üretir.
- `etki_analizi_simulasyon.py`: etki hesabını deterministik yapar; Gemma/LM
  Studio'yu yalnızca izinli gerçek kimliklere bağlı mühendislik önerileri için
  kullanır.
- `etki_analizi_degisim_paketi.py` ve `etki_analizi_degisim_ui.py`: karar,
  açık kullanıcı onayı, onay özeti, yedekleme, doğrulama ve atomik yeni
  sürüm yayımlama sınırını uygular.

DoDAF 2.02, DoD tarafından resmî ve güncel sürüm olarak yayımlanmaktadır.
NAF 4.1 ise NATO'nun Mart 2026 tarihli güncel çerçevesidir. Bu belgede
tanımlanan “ilk paketler” EHSİM'in uygulama önceliğidir; resmî çerçevelerin
her proje için zorunlu tuttuğu paketler değildir.

## 2. Normatif profil kararları

### 2.1 Güncel profiller

| Profil | EHSİM hedef sürümü | Tasarım kuralı |
|---|---:|---|
| DoDAF | 2.02 | Model adları ve anlamları DoD CIO tanımlarına göre tutulur. DoDAF uyumu ancak DM2 tanımlama ve PES aktarılabilirliği ayrıca doğrulanırsa ileri sürülür. |
| NAF | 4.1 | Güncel NAF 4.1 viewpoint adları, NAF Information Model kapsamları ve zorunlu/isteğe bağlı içerik kuralları kullanılır. |
| ArchiMate | 3.2 | NAF için EHSİM'in varsayılan uygulama profilidir. NAF IM ↔ ArchiMate eşlemesi resmî NATO uygulama kılavuzuna dayanır. |

**Sınır:** NATO, ArchiMate 3.2'yi NAF 4.1 için desteklenen bir uygulama
yolu olarak belgeler; onu tek veya NATO tarafından “varsayılan” yol ilan etmez.
ArchiMate 3.2'nin varsayılan olması bir **EHSİM tasarım kararıdır**. UAF
DMM gibi başka uygulama yolları bu kartın kapsamı dışındadır.

### 2.2 Eski NAF v3 adları

NAF v3 adları yalnızca içe aktarma uyumluluğu etiketi olarak desteklenir:

1. İçe aktarıcı eski etiketi `legacy_source_label` alanında aynen korur.
2. Etiket, sürümlü ve tek yönlü bir eşleme tablosuyla NAF 4.1 kanonik
   viewpoint kimliğine dönüştürülür.
3. Yeni model, ekran, dışa aktarım ve API hiçbir zaman v3 adı üretmez.
4. Tek bir v3 ürünün birden fazla v4.1 viewpoint'e karşılık gelmesi
   durumunda otomatik seçim yapılmaz; sonuç “belirsiz/eksik” olur ve kullanıcı
   eşleme onayı istenir.
5. Eşlemenin kaynak sürümü, orijinal etiket ve kullanıcı kararı denetim
   kaydında tutulur.

Bu “yalnız içe aktarma” davranışı NATO zorunluluğu değil, eski adların
yeni veri modeline sızmasını önleyen EHSİM uyumluluk politikasıdır. Örnek
eşlemeler: `NOV-1 → L2-L3`, `NOV-2/NOV-3 → L3`, `NOV-5 → L4`,
`NOV-6a → L8`, `NOV-4/NSV-1 → P2`, `NSV-2/NSV-6 → P3`, `NSV-4 → P4`,
`NSV-5 → L4-P4`, `NSV-10a → P8`. Eşleme tablosu uygulanmadan önce resmî
NAF kaynak sürümüyle test edilmelidir.

## 3. Görünüm üretilebilirlik sınıfları

Her viewpoint örneği tek ve zorunlu bir `generation_class` taşır. Sınıflar
birbirinin yerine geçmez.

### A — Gereksinimden doğrudan çıkarılabilir

Yalnızca kaynak gereksinim veya mevcut kesin izlenebilirlik bağında açıkça
bulunan kimlik, ifade, sayı, birim ve ilişkilerle eksiksiz doldurulabilen
içeriktir. Dönüşüm deterministik olmalı ve her mimari öğe en az bir
`evidence_ref` taşımalıdır. Gemma bu sınıftaki gerçekleri oluşturmaz veya
değiştirmez; en fazla aynı kanıtın kontrollü metin sunumunu önerebilir.

### B — Kullanıcı onayı isteyen aday

Kaynakta dayanağı olan fakat eşleme, sınıflandırma, fonksiyon tahsisi,
etkileşim yönü veya mimari yorum gerektiren içeriktir. Gemma yalnızca
kanıtlı adaylar önerebilir. Her aday:

- gerçek kaynak kimliklerinden oluşan izin listesine uymalı,
- kanıt referansı, çıkarım gerekçesi ve güven düzeyi taşımalı,
- `Mühendislik önerisi — kullanıcı onayı gerekli` durumuyla başlamalı,
- varsayılan olarak `Ertele` kararında kalmalı,
- kullanıcı `Kabul et` demeden kanonik mimari modele girmemelidir.

Model hiçbir adayı kendiliğinden onaylayamaz. Aday metni onaydan sonra
değişirse onay geçersiz olur ve yeniden istenir.

### C — Ek girdi olmadan üretilemez

Kaynakta aktör/sistem/servis sınırı, arayüz ucu, akış yönü, protokol,
fonksiyon tahsisi, ölçüt-zaman ufku, operasyonel faaliyet veya bağlam gibi
viewpoint'in zorunlu alanlarından biri yoksa içerik bu sınıfa girer. Çıktı:

- uydurulmuş bir mimari öğe değil,
- `belirsiz/eksik` durumu,
- eksik alanların listesi,
- gerekli girdi türü ve kullanıcıya yöneltilecek soru,
- ilgili kaynak ve viewpoint kimliğidir.

Sınıf C, boş kutularla “tamamlanmış” bir görünüm üretmez ve Gemma
eksik değerleri tahmin etmez.

## 4. Uygulama paketleri

Paketler teslimat sırasını belirler; resmî çerçevelerin bütününü veya
asgari uyum kümesini temsil etmez.

### 4.1 İlk DoDAF uygulama paketi

| Model | Resmî anlam | Asgari EHSİM girdisi | Olağan sınıf |
|---|---|---|---|
| AV-1 | Overview and Summary Information | proje kapsamı, amaç, paydaş, zaman ufku, varsayım, kısıt, kaynak ve durum | A+B+C |
| AV-2 | Integrated Dictionary | kullanılan mimari terimler, tanımlar ve yetkili kaynaklar | A+B |
| SV-1 | Systems Interface Description | kanıtlı sistem/bileşen kimlikleri ve aralarındaki bağlantılar | A+B+C |
| SV-2 | Systems Resource Flow Description | kaynak akışı, kaynak/hedef uçları ve varsa protokol | A+B+C |
| SV-4 | Systems Functionality Description | sistem fonksiyonları, tahsisler ve fonksiyonlar arası akışlar | A+B+C |
| SV-5a | Operational Activity to Systems Function Traceability Matrix | operasyonel faaliyet ve sistem fonksiyonu arası kanıtlı eşleme | A+B+C |
| SV-7 | Systems Measures Matrix | ölçüt, hedef/değer, birim, ilgili sistem öğesi ve zaman ufku | A+B+C |

SV-1/SV-2/SV-4/SV-5a/SV-7 üretimi için yalnızca gereksinim metni her
zaman yeterli değildir. Kaynakta zorunlu sistem ve ilişki semantiği yoksa
görünüm Sınıf C'dir.

### 4.2 İlk NAF uygulama paketi

| Viewpoint | NAF 4.1 anlamı | Asgari EHSİM girdisi | Olağan sınıf |
|---|---|---|---|
| L2-L3 | Logical Concept | bağlamı anlatan kanıtlı Node/Needline veya eşdeğer kavramlar | A+B+C |
| L3 | Logical Interactions | Node'lar, mantıksal etkileşimler ve taşınan pasif kaynaklar | A+B+C |
| L4 | Logical Activities | operasyonel faaliyetler, icracı Node/Role ve kontrol/operasyon akışları | A+B+C |
| L8 | Logical Constraints | mantıksal kısıt/gereksinim ve uygulandığı mantıksal öğe | A+B |
| P2 | Resource Structure | fiziksel aktif/pasif kaynaklar, yapı ve bağımlılıklar | A+B+C |
| P3 | Resource Interactions | aktif kaynaklar arası etkileşim, taşınan kaynak ve protokol | A+B+C |
| P4 | Resource Functions | kaynak fonksiyonları, fiziksel icracılar ve fonksiyon/kaynak akışları | A+B+C |
| L4-P4 | Activity to Function Mapping | operasyonel faaliyet ↔ kaynak fonksiyonu izlenebilirliği | A+B+C |
| P8 | Resource Constraints | kaynak kısıtı/gereksinimi ve uygulandığı fiziksel/fonksiyonel öğe | A+B |

NAF çıktılarının varsayılan gösterim modeli NATO'nun NAF 4.1
ArchiMate kılavuzundaki NAF IM ↔ ArchiMate 3.2 eşlemesidir. Kılavuzdaki
zorunlu (“shall”) içerik eksikse görünüm tamamlanmış sayılmaz.

### 4.3 İkinci aşama DoDAF servis paketi

| Model | Resmî anlam | Kabul kapısı |
|---|---|---|
| SvcV-1 | Services Context Description | servis ve alt servis sınırları ile bağlantıları kanıtlı olmalı |
| SvcV-2 | Services Resource Flow Description | servisler arası akış uçları ve varsa protokoller kanıtlı olmalı |
| SvcV-4 | Services Functionality Description | servis fonksiyonları, tahsis ve veri akışları kanıtlı olmalı |
| SvcV-5 | Operational Activity to Services Traceability Matrix | faaliyet ↔ servis eşlemesi kanıtlı veya açıkça onaylanmış olmalı |
| SvcV-7 | Services Measures Matrix | servis ölçütü, değer/birim ve zaman ufku kanıtlı olmalı |

`SvcV-*` DoDAF terminolojisidir. NAF 4.1 servis satırı `S1–S8` adlarını
kullanır; iki aile arasında birebir eşdeğerlik bu tasarımda varsayılmaz.
DoDAF servis verisini NAF servis görünümlerine dönüştürmek ayrı bir
eşleme ve doğrulama işidir.

## 5. Durum ifadelerinin kesin tanımı

### 5.1 Taslak

Bir mimari çıktıya yalnızca şu durumda **taslak** denir:

- seçilen profil ve viewpoint kimliği bellidir,
- sözdizimsel/şema doğrulaması geçmiştir veya eksikleri açıkça listelenmiştir,
- kanıt referansları ve eksik alanlar kayıtlıdır,
- bir veya daha fazla zorunlu veri, kullanıcı onayı ya da uyum testi
  tamamlanmamıştır.

Taslak, “yanlış olabilir ama tamamlanmış gibi kullanılabilir” demek değildir;
karar ve resmî dışa aktarım girdisi olamaz.

### 5.2 Çerçeveyle hizalı

Bir çıktıya yalnızca aşağıdaki koşulların tamamında **çerçeveyle
hizalı** denir:

1. Profil sürümü, kanonik viewpoint/model kimliği ve terimler doğrudur.
2. Resmî viewpoint amacına ve zorunlu içerik kapsamına aykırı öğe yoktur.
3. Her öğe ve ilişki kaynak kanıtına veya kayıtlı açık kullanıcı
   onayına izlenebilir.
4. Eksik bilgi uydurulmamış, `belirsiz/eksik` olarak kaydedilmiştir.
5. Yerel şema, başvuru bütünlüğü, zorunlu alan ve kanıt kapıları
   geçmiştir.

Bu ifade resmî DoDAF/NAF uyum sertifikası değildir.

### 5.3 Uyumlu

**Uyumlu** en dar ve kanıta dayalı durumdur. “Çerçeveyle hizalı” koşullarına
ek olarak:

- profilin normatif bilgi modeliyle doğrulanmış olmalı,
- profilin zorunlu değişim/aktarma gereksinimini geçmeli,
- hedef aracın bağımsız içe aktarımı veya resmî doğrulama aracıyla test
  edilmiş olmalı,
- test aracı/sürümü, profil sürümü, zaman, sonuç ve artefakt özeti
  kayıtlı olmalı,
- onay makamı ve yayımlanmış sürüm belli olmalıdır.

DoDAF için bu, en azından mimari verinin DM2 kavram/ilişki/özniteliklerine
göre tanımlanmasını ve PES'e uygun aktarılabilirliğin doğrulanmasını gerektirir.
NAF için NAF 4.1 Information Model kapsamına ve seçilen uygulama yoluna
uygunluk; ArchiMate yolunda NAF 4.1 ArchiMate eşlemeleri ve geçerli ArchiMate
3.2 değişim artefaktı doğrulanmalıdır.

Bu doğrulama araçları ve dışa aktarıcılar projede henüz yoktur. Bu nedenle
ilk uygulama tamamlanana kadar EHSİM en fazla **taslak** veya **çerçeveyle
hizalı** etiketi verebilir; **uyumlu** etiketi veremez.

## 6. Kaynak kanıtı kuralları

Her kanonik mimari öğe ve ilişki aşağıdakileri taşımalıdır:

- `evidence_id`: değişmez benzersiz kimlik,
- `source_document`, `source_section` ve varsa sayfa/satır/alan konumu,
- `source_item_id`: TID/SGD/STT/test/donanım veya diğer gerçek kimlik,
- kısa `evidence_excerpt` veya yapılandırılmış alan referansı,
- `evidence_fingerprint`: kaynak içeriğin karma değeri,
- `derivation_kind`: `direct`, `deterministic`, `model_suggestion` veya
  `user_supplied`,
- `confidence_level`: mevcut sözleşmeyle uyumlu olarak `Kesin`,
  `Önerilen bağlantı` veya `Çıkarım`,
- üretici/modül, kural veya model sürümü.

Kurallar:

1. Kimliği veya konumu bulunmayan kaynak “kanıt var” sayılmaz.
2. Semantik benzerlik doğrudan kanıt değildir; yalnızca aday bağ üretir.
3. Gemma'nın metni kaynak kanıtı değildir.
4. Kaynaksız sayı, birim, protokol, arayüz, sistem, servis veya ilişki
   reddedilir.
5. Kaynak değişirse parmak izi uyuşmazlığı ilgili aday/onayı geçersiz kılar.
6. Bir öğenin bütün zorunlu alanları kanıtlı değilse kısmi kanıt ile
   tamamlanmış gösterilemez.

## 7. Kullanıcı onayı kuralları

- A sınıfı deterministik aktarım onay bekleyen yeni gerçek üretmez; buna
  rağmen yayımlama ayrı bir kullanıcı eylemidir.
- B sınıfındaki her aday için `Kabul et`, `Reddet`, `Düzenle` veya `Ertele`
  kararı tutulur; varsayılan `Ertele`dir.
- Kabul için onaylayan kişi/rol, zaman, adayın karar özeti ve kanıt parmak
  izleri kaydedilir.
- Toplu onay, aday bazındaki kararları gizleyemez.
- Aday, kanıt, profil, mapping veya hedef sürüm onaydan sonra değişirse
  onay otomatik geçersiz olur.
- Onay, eksik kaynak verisini “kaynakta vardı” hâline getirmez; kullanıcı
  eklediği bilgi `user_supplied` olarak ayrı tutulur.
- Gemma, içe aktarıcı veya kural motoru `approved=true` yazamaz.

## 8. Sürümleme ve yayımlama kuralları

Mevcut atomik ve geri döndürülebilir desen korunur:

1. Taslaklar yayımlanmış mimariden ayrı alanda tutulur.
2. Her yayım yeni, değiştirilemez `vNNNN` sürümü oluşturur; önceki
   sürümün üzerine yazılmaz.
3. `latest`/güncel işaretçisi yalnızca geçici alanda şema, kanıt,
   referans, profil ve onay kontrolleri geçtikten sonra atomik değiştirilir.
4. Her sürüm profil ve uygulama profili sürümlerini, kanonik modeli,
   görünümleri, kaynak parmak izlerini, onay kaydını, doğrulama sonucunu ve
   üretici sürümünü birlikte dondurur.
5. Yeni tarama veya profil değişikliği eski sürümü sessizce dönüştürmez;
   yeni aday ve yeni sürüm oluşturur.
6. Eski NAF etiketi, dönüşüm tablosu sürümü ve dönüşüm sonucu
   kayıtta korunur.
7. DM2/PES veya ArchiMate değişim dosyası, kanonik JSON'dan türetilen ve
   aynı sürüme bağlı bir artefakttır; veri kaynağı değildir.

## 9. Önerilen modüller

Aşağıdaki adlar hedef tasarımdır; bugün kaynak ağacında bulunmaz.

| Modül | Sorumluluk | Yapmaması gereken |
|---|---|---|
| `mimari_profiller.py` | DoDAF 2.02, NAF 4.1 ve ArchiMate 3.2 profil kaydı; paket/viewpoint tanımları | proje verisi yazmak |
| `mimari_kanit.py` | mevcut izlenebilirlikten kanıt zarfı, parmak izi ve eksik alan listesi üretmek | semantik benzerliği kesin kanıta yükseltmek |
| `mimari_kanonik_model.py` | profilden bağımsız, sürümlü öğe/ilişki modeli ve şema doğrulaması | sunum biçimini kaynak gerçek kabul etmek |
| `mimari_uretilebilirlik.py` | A/B/C sınıfı, zorunlu alan ve eksik girdi analizi | eksik veriyi tamamlamak |
| `mimari_gemma_adaylari.py` | izin listeli, kanıtlı B sınıfı adayları ve gerekçeleri | onay vermek veya kanonik modeli yazmak |
| `mimari_onay.py` | aday kararları, onaylayan, digest ve geçersizleştirme | kullanıcı eylemi olmadan kabul etmek |
| `mimari_dodaf.py` | kanonik model ↔ DoDAF model eşlemesi ve ilk/servis paketleri | DM2/PES test edilmeden “uyumlu” demek |
| `mimari_naf.py` | NAF 4.1 viewpoint eşlemesi ve zorunlu kapsam doğrulaması | v3 adı dışa aktarmak |
| `mimari_archimate.py` | NAF IM ↔ ArchiMate 3.2 eşlemesi ve değişim artefaktı | lisanslı standart metnini projeye kopyalamak |
| `mimari_legacy_naf.py` | yalnız içe aktarma için sürümlü v3 etiket eşlemesi | yeni kayıtta legacy etiketi kanonik yapmak |
| `mimari_dogrulama.py` | şema, referans, kanıt, profil, exchange ve durum kapıları | başarısız çıktıyı yayımlamak |
| `mimari_depo.py` | taslak, değişmez `vNNNN`, atomik güncel işaretçi ve denetim kaydı | mevcut izlenebilirlik/kullanıcı dosyalarını değiştirmek |
| `mimari_uretim_ui.py` | arka plan işi, ilerleme, iptal, eksik girdi ve açık onay ekranı | Tkinter ana iş parçacığında ağır iş çalıştırmak |

Yeni modüller mevcut `etki_analizi_*` dosyalarının veri sözleşmelerini
değiştirmek yerine salt-okunur adaptörlerle kullanmalıdır.

## 10. Veri akışı

```text
Kaynak belgeler + flat_data + hardware_data
                    |
                    v
      Mevcut sürümlü izlenebilirlik grafiği
                    |
          [salt-okunur kanıt adaptörü]
                    |
                    v
     Kanıt zarfları + eksik/belirsiz alanlar
                    |
                    v
       Profil ve viewpoint kapsam seçimi
                    |
                    v
          A / B / C üretilebilirlik kapısı
             /          |           \
            A           B            C
            |           |            |
   deterministik    Gemma yalnızca   eksik girdi
     dönüşüm      kanıtlı aday    isteği
            |           |
            |     kullanıcı kararı/onayı
            |           |
             \          /
              v        v
            Kanonik mimari model
                    |
        +-----------+------------+
        |                        |
   DoDAF adaptörü          NAF 4.1 adaptörü
        |                        |
   DM2/PES artefaktı      ArchiMate 3.2 artefaktı
        |                        |
        +-----------+------------+
                    |
            Doğrulama kapıları
                    |
       taslak / çerçeveyle hizalı / uyumlu
                    |
      atomik ve değişmez vNNNN yayımı
```

Uzun süren kaynak tarama, Gemma çağrısı, model üretimi, exchange
doğrulaması ve dosya yayım hazırlığı arka plan işçisinde çalışır.
Tkinter ana iş parçacığı yalnızca durum, ilerleme, iptal ve kullanıcı
kararlarını yönetir. Sonuç UI'ya `after(...)` ile taşınır; eskimiş iş
token'ları diske yazamaz.

## 11. Kabul ve test stratejisi

Kodlama kartlarında her yeni davranış için birim testi zorunludur. Asgari
test kümesi:

- her paket ve viewpoint kaydının doğru profil sürümüne bağlı olması,
- A sınıfının yalnızca kaynakta bulunan alanları aktarması,
- B adayının kanıtsız kimlik/sayı/ilişkiyi reddetmesi ve onaysız
  yayımlanamaması,
- C sınıfının uydurma değer yerine `belirsiz/eksik` ve gerekli girdi
  listesini üretmesi,
- onay sonrası aday/kanıt değişikliğinin onayı geçersizleştirmesi,
- NAF v3 etiketlerinin yalnız içe alınması ve dışa aktarılmaması,
- çok-anlamlı legacy eşlemenin otomatik seçim yapmaması,
- zorunlu viewpoint alanı eksikken “hizalı/uyumlu” etiketi verilmemesi,
- DoDAF DM2/PES ve NAF/ArchiMate exchange kontrolü yokken `uyumlu`
  durumunun engellenmesi,
- atomik `vNNNN` yazımı, eski sürümün korunması ve başarısız kontrolde
  güncel işaretçinin değişmemesi,
- iptal/eskimiş token durumunda arka plan sonucunun UI veya depoya commit
  edilmemesi,
- mevcut test paketinin tamamının gerilemesiz geçmesi.

Kart 0 yalnızca bu belgeyi ekler; çalışan davranış eklemediği için bu kartta
yeni birim testi yoktur. Belge sonrası mevcut testlerin tamamı çalıştırılır.

## 12. Açık ve belirsiz konular

Aşağıdakiler kaynakta veya mevcut projede uygulanmış değildir; sonraki
kartlarda karar ve test gerekir:

- kanonik mimari JSON şeması ve kimlik stratejisi,
- DM2 kavram/ilişki/özniteliklerinin eksiksiz eşleme tablosu,
- PES sürümü, şeması, doğrulama aracı ve hedef araç kabul testi,
- ArchiMate 3.2 exchange biçimi ve NAF specialism bilgilerinin kayıpsız
  taşınma yöntemi,
- NAF v3 çoklu eşlemelerinde gerekli kullanıcı karar modeli,
- DoDAF SvcV ile NAF S-row arası semantik eşleme,
- AV-1 için paydaş, karar mercii, zaman ufku ve mimari kapsam girdilerinin
  UI'dan nasıl toplanacağı,
- resmî/bağımsız NAF uyum doğrulama aracının bulunup bulunmadığı,
- kullanılacak ArchiMate standardı ve exchange şeması için lisans koşulları.

Bu konular karara bağlanmadan ilgili değerler tahmin edilmez; çıktılarda
`belirsiz/eksik` olarak kalır.

## 13. Resmî kaynaklar

### ABD Savunma Bakanlığı (DoD)

- [DoDAF Architecture Framework Version 2.02 — resmî ana sayfa](https://dodcio.defense.gov/DoDAF/)
- [DoDAF 2.02 tam resmî PDF](https://dodcio.defense.gov/Portals/0/Documents/DODAF/DoDAF_v2-02_web.pdf)
- [DoDAF model listesi](https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_models/)
- [All Viewpoint: AV-1 ve AV-2](https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_all_view/)
- [AV-1 ayrıntılı tanımı](https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_av1/)
- [AV-2 ayrıntılı tanımı](https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_av2/)
- [Systems Viewpoint: SV modelleri](https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_systems/)
- [Services Viewpoint: SvcV modelleri](https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_services/)

### NATO

- [NATO Architecture Framework 4.1 — resmî PDF](https://www.nato.int/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-v4-1-en.pdf)
- [NAF 4.1 ArchiMate 3.2 Implementation Guide — resmî PDF](https://www.nato.int/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-ArchiMate-v4-1-en.pdf)
- [NATO Architecture Framework resmî konu sayfası](https://www.nato.int/cps/en/natohq/topics_157575.htm)
- [NAF 4 (2020.09) — v3/v4 viewpoint eşlemeleri için resmî PDF](https://www.nato.int/content/dam/nato/webready/documents/publications-and-reports/NAFv4_2020.09.pdf)

### The Open Group

- [ArchiMate 3.2 resmî indirme ve sürüm bilgisi](https://www.opengroup.org/archimate-licensed-downloads)
- [ArchiMate standardı ve sertifikasyon programı](https://www.opengroup.org/certifications/archimate)
- [ArchiMate Model Exchange File Format](https://www.opengroup.org/open-group-archimate-model-exchange-file-format)

