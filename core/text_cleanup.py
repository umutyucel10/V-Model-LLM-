# -*- coding: utf-8 -*-
"""
Üretilen madde metinleri için ORTAK temizleme.
4B model prompt'lardaki örnek formatları sızdırıyor (etiket, numara, markdown,
'GEREKSİNİM:/BAŞARILI TEST:' echo'su vb.). Bu fonksiyon hepsini deterministik temizler.
"""
import re

# Baştan silinecek etiketler (büyük/küçük harf duyarsız; Türkçe İ/ı destekli)
_LABEL = re.compile(
    r"(?is)^\s*("
    r"kmtd|kabul( muayene)? test[İIıi]?|"
    r"sitet|s[İIıi]stem [İIıi]şletme test[İIıi]?|"
    r"s[İIıi]stem gereks[İIıi]n[İIıi]m[İIıi]?|s[İIıi]stem test[İIıi]?|"
    r"s[İIıi]stem gerekl[İIıi]l[İIıi]ğ[İIıi]?|gerekl[İIıi]l[İIıi]k|"
    r"alt s[İIıi]stem test[İIıi]|alt s[İIıi]stem gereks[İIıi]n[İIıi]m[İIıi]|"
    r"dtet[- ]?ytet|dtet|ytet|"
    r"donanım\s*[-/]\s*yazılım(?:\s+geliştirme)?(?:\s+özeti)?|dgö\s*[-/]?\s*ygö|"
    r"test senaryosu|senaryo|gereks[İIıi]n[İIıi]m|"
    r"\[?ast\]?|\[?kmtd\]?"
    r")\s*[-:]?\s*"
)
# 'GEREKSİNİM: ... BAŞARILI TEST: <asıl test>' echo'sunda baştan 'BAŞARILI TEST:'e kadarını at
_BASARILI = re.compile(r"(?is)^.*?başarılı test\s*:?\s*")

# YABANCI ALFABE SIZINTISI: Qwen (Çin modeli) Türkçe çıktıya Çince karıştırıyor
# (ör. '...toplu olarak秤重，则将总重量不超过12 kg。总重量 ≤ 12 kg').
# PDF fontunda CJK glifi olmadığı için \x00 kutusu (􀀀􀀀􀀀) görünür; Excel/HTML/Word'de ise
# GERÇEK Çince görünür → kök çözüm: ham metinden temizle.
# NOT: Yunanca BİLEREK bırakıldı (µs, Ω, θ gibi mühendislik sembolleri meşru).
_YABANCI_ALFABE = re.compile(
    r"[　-〿"      # CJK noktalama （，。、）
    r"぀-ヿ"       # Hiragana/Katakana
    r"㐀-䶿"       # CJK Ext-A
    r"一-鿿"       # CJK (Çince/Kanji)
    r"가-힯"       # Hangul
    r"＀-￯"       # Tam genişlik formlar
    r"Ѐ-ӿ"       # Kiril
    r"֐-׿"       # İbranice
    r"؀-ۿ]+"     # Arapça
)


def temizle(text, test=False):
    """Bir madde metnindeki etiket/numara/markdown/echo artıklarını temizler."""
    if not text:
        return text
    # KONTROL KARAKTERLERİ (NUL vb.): model ara sıra \x00 üretiyor; PDF fontu bunları
    # "notdef" kutusu (􀀀􀀀􀀀) olarak çiziyor. \s bunları yakalamaz → ayrıca silinmeli.
    # BOŞLUKLA değiştir (silme!): aksi halde kelimeler yapışır ('12 kg' + 'PASS' → 'kgPASS')
    # ve sonraki kural/etiket regex'leri kelime sınırını kaybedip eşleşmez.
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", text)
    t = _YABANCI_ALFABE.sub(" ", t)              # Çince vb. sızıntı (Qwen kaynaklı)
    # İngilizce etiket sızıntısı → Türkçe karşılığı
    t = re.sub(r"(?i)\bPASS\s*(?:/\s*FAIL\s*)?CRITERION\b", "GEÇTİ KRİTERİ", t)
    t = re.sub(r"(?i)\bFAIL\s+CRITERION\b", "KALDI KRİTERİ", t)
    # Türkçe cümleye tek tük karışan İngilizce kelimeler (tümü İngilizce olsaydı
    # gecerli_mi() zaten reddedip yeniden ürettirirdi) → Türkçe karşılığına çevir.
    for _en, _tr in ((r"time", "süre"), (r"value", "değer"), (r"duration", "süre"),
                     (r"latency", "gecikme"), (r"accuracy", "doğruluk"),
                     (r"threshold", "eşik"), (r"range", "menzil"), (r"speed", "hız")):
        t = re.sub(r"(?i)\b" + _en + r"\b", _tr, t)
    t = re.sub(r"\*+", "", t)                    # markdown yıldızları (**, ****)
    t = t.replace("\r", " ").replace("\n", " ")
    if test:                                     # test echo'su: BAŞARILI TEST'ten sonrasını al
        m = _BASARILI.match(t)
        if m and t[m.end():].strip():
            t = t[m.end():]
    t = re.sub(r"^\s*\d+\s*[\.\)\-–]\s*", "", t)  # baştaki '1.' / '2)' / '1- ' (tire de dahil)
    # PROMPT SIZINTISI: kural kelimelerimiz cevaba karışıyor ('DAİMA', 'YANLIŞ:', 'DOĞRU:')
    t = re.sub(r"(?i)\b(?:DA[İIİ]M[AE])\b\s*", "", t)
    t = re.sub(r"(?i)^\s*(?:YANLIŞ|DOĞRU)\s*:\s*", "", t)
    # MODEL AÇIKLAMASI sızıntısı: model bazen '(Not: ... çünkü ...)' diye gerekçe yazıyor → sonuna kadar sil
    t = re.sub(r"(?is)\s*\(?\s*Not\s*:.*$", "", t)
    # Boş kalan 'GEÇTİ KRİTERİ:' (ardında ölçüt yok, cümle sonu) → sil
    t = re.sub(r"(?i)\s*GEÇT[İI]\s*KR[İI]TER[İI]\s*:?\s*$", "", t)
    # baştaki 'TEST:' ve 'ALT "' echo'su (iki nokta/tırnak zorunlu → 'Test edilen'i BOZMAZ)
    t = re.sub(r'(?i)^\s*test\s*:\s*', "", t)
    t = re.sub(r'(?i)^\s*alt\s+["“]\s*', "", t)
    # gövde ortasında kalan etiket echo'ları ('... Test senaryosu: ...', '... ALT SİSTEM TESTİ: ...')
    t = re.sub(r"\s*(?:test senaryosu|senaryo|(?:alt )?s[İIıi]stem (?:test|gereks[İIıi]n[İIıi]m)[İIıi]?)\s*:\s*",
               " ", t, flags=re.I)
    t = _LABEL.sub("", t)                         # baştaki etiket(ler)
    t = re.sub(r"^\s*\d+\s*[\.\)]\s*", "", t)     # etiket sonrası kalan numara
    # SARKAN ZORUNLULUK EKİ: birimden sonra yalnız kalan 'malıdır' anlamsızdır
    # ('20 saniyede malidir' → '20 saniye içinde tamamlanmalıdır'). dsb_temizle'de DEĞİL
    # burada olmalı, çünkü bu bozukluk DSB içermeyen maddelerde de görülüyor.
    # SADECE BİRİM sonrası uygulanır. Yalın 'DSB malıdır' (birimsiz) buraya GİRMEMELİ —
    # o, "değer gerekmiyor" demektir ve dsb_temizle onu tamamen kaldırır.
    t = re.sub(r"(?i)\b(" + _DSB_UNITS + r")\s*(?:de|da|te|ta)?\s+"
               r"(?:(?:ol)?mal[ıi]d[ıi]r|(?:ol)?melidir|mal[ıi]|meli)\b",
               r"\1 içinde tamamlanmalıdır", t)
    # SONDA SARKAN DSB: cümle zaten TAMAMLANMIŞ (zorunluluk fiili ile bitmiş), ardına DSB
    # tacılmış → bu bir DEĞER yer tutucusu değil, artıktır; atılır.
    #   'tespit etmeli DSB saniye' → 'tespit etmeli'
    #   'olmamalıdır: DSB'         → 'olmamalıdır'
    #   'sağlanmalıdır. DSB saniye'→ 'sağlanmalıdır'
    # KORUNUR: 'Ağırlık DSB kg olmalıdır' (cümle içi, DSB'den sonra devam var → $ tutmaz)
    #          '< DSB saniye' (geçti kriteri; fiille bitmediği için eşleşmez)
    t = re.sub(r"(?i)(d[ıi]r|t[ıi]r|dur|dür|mal[ıi]|meli)\s*[.:;,]?\s+"
               r"DSB(?:\s+(?:" + _DSB_UNITS + r"|ol\w+|belirlen\w+))?\s*\.?\s*$", r"\1", t)
    t = t.replace('"', " ")
    t = re.sub(r"\s+", " ", t).strip(" .:-()[]")
    while t and t[0] in "([-" and t[-1] in ")]":
        t = t[1:-1].strip()
    # Baştan parça silindiyse cümle küçük harfle başlamış olabilir → ilk harfi büyüt.
    if t and t[0].islower():
        t = ("İ" + t[1:]) if t[0] == "i" else (t[0].upper() + t[1:])
    return t


# DSB ile birlikte görülen çelişkili/uydurma sayıları temizlemek için birim ve sayı kalıbı
_DSB_UNITS = (r"(?:°\s*[cCsSfF]|°|santigrat|derece|mbps|kbps|gbps|bps|ghz|mhz|khz|hz|"
              r"gb|mb|kb|tb|milisaniye|ms|saniye|sn|dakika|dk|saat|gram|gr|kg|mg|g|"
              r"litre|lt|ml|l|mm|cm|km|m|dbm|db|bar|volt|amper|watt|dpi|fps|%|adet|kez)")
_DSB_NUM = r"\d+(?:[.,]\d+)?"
# Türkçe zorunluluk (shall) ekleri — hem temizle() hem dsb_temizle() kullanıyor.
_SHALL = r"(?:ol)?mal[ıi]d[ıi]r|(?:ol)?melidir|mal[ıi]|meli"


def dsb_temizle(text):
    """
    Bir metinde 'DSB' geçiyorsa, DSB'nin (Daha Sonra Belirlenecek) ANLAMIYLA ÇELİŞEN
    uydurma sayıları temizler:
      - '93°C sıcaklık aralığında (DSB)'  → 'DSB sıcaklık aralığında'   (somut değer + (DSB) işareti)
      - '(örneğin 100g)', '(20 °C)', '(0.5 saniye)' → silinir            (parantezli örnek/değer)
      - '100g DSB' (DSB'den önce sayı)     → 'DSB'
      - 'DSB 2 saniye' (DSB'den sonra sayı) → 'DSB saniye'
      - yalnız '(DSB)' işareti             → 'DSB'
    NOT: '(RS485)', '(ARM Cortex-M7)' gibi teknik adlar KORUNUR (örnek değer değil).
    Ayrı bir boyuttaki bağımsız sayılar (ör. cümlenin başka yerindeki bir test süresi)
    kasıtlı olarak DOKUNULMAZ — onlar DSB ile doğrudan çelişmez.
    """
    if not text or "DSB" not in text.upper():
        return text
    t = text
    # -5) 'DSB malıdır' KALIBI (en sık bozukluk): model, ölçülecek değer OLMADIĞI hâlde
    #     DSB'yi zorunluluk fiiline yapıştırıyor. Sadece 'DSB'yi silmek sarkan 'malıdır'
    #     bırakır → parçanın TAMAMINI (varsa bağlacıyla) temizle.
    #       'DSB malıdır ve sistem X yapmalıdır' → 'Sistem X yapmalıdır'
    #       'Sistem, DSB malıdır ve Y içermelidir' → 'Sistem, Y içermelidir'
    #     NOT: SHALL sonunda \b ZORUNLU — yoksa 'malının' içindeki 'malı' eşleşip
    #     kelimeyi parçalar ('DSB malının' → 'nın' olurdu).
    t = re.sub(r"(?i)^\s*DSB\s+(?:" + _SHALL + r")\b\s*[,;]?\s*(?:ve|ancak|ayrıca)?\s*", "", t)
    t = re.sub(r"(?i)\bDSB\s+(?:" + _SHALL + r")\b\s*[,;]?\s*(?:ve|ayrıca)\s+", "", t)
    t = re.sub(r"(?i)\bDSB\s+(?:" + _SHALL + r")\b\s*[,;]?\s*", "", t)
    # -3) TİRE İLE YAPIŞIK UYDURMA DEĞER: model 'DSB-15 saniye' gibi DSB'yi sayıya yapıştırıyor.
    #     Kaynak değeri vermediği için sayı UYDURMA; 'DSB <birim>' bırak.
    #     'DSB-15 saniye' → 'DSB saniye', 'DSB-20sn' → 'DSB sn'
    t = re.sub(r"\bDSB\s*[-–—]\s*" + _DSB_NUM + r"\s*(" + _DSB_UNITS + r")", r"DSB \1", t, flags=re.I)
    #     'DSB-%85' / 'DSB-85%' (tire ile yüzde/sayı yapışık) → 'DSB' (sondaki boşluğu YEME)
    t = re.sub(r"\bDSB\s*[-–—]\s*%?" + _DSB_NUM + r"%?", "DSB", t, flags=re.I)
    #     'DSB-15' (birimsiz, tire ile) → 'DSB'
    t = re.sub(r"\bDSB\s*[-–—]\s*" + _DSB_NUM + r"\b", "DSB", t, flags=re.I)
    # -2) 'DSB-malıdır/-melidir' (DSB fiilin yerine sızmış) → 'DSB olmalıdır' (değer belirlenecek)
    t = re.sub(r"\bDSB\s*[-–—]\s*(?:ol)?(?:mal[ıi]d[ıi]r|melidir)\b", "DSB olmalıdır", t, flags=re.I)
    t = re.sub(r"\bDSB\s*[-–—]\s*(?:mal[ıi]|meli)\b", "DSB olmalı", t, flags=re.I)
    # -1) DSB + hal eki YANLIŞ ('DSB'ye tamamlanması' gibi sözde nesne) → kaldır. KORU: "DSB'dir".
    t = re.sub(r"\bDSB['’](?:ye|ya|de|da|te|ta|deki|daki|nde|nda|na|ne)\b\s*", "", t, flags=re.I)
    # -0b) çelişki: '(DSB = 15 saniye)' → '(DSB)'   |  sarkan/kapanmayan '(DSB' → 'DSB'
    t = re.sub(r"\(\s*DSB\s*=\s*" + _DSB_NUM + r"\s*" + _DSB_UNITS + r"?\s*\)", "(DSB)", t, flags=re.I)
    t = re.sub(r"\(\s*DSB\b(?!\s*\))", "DSB", t, flags=re.I)
    # -0a) misuse: 'DSB olarak belirtilmiş olsa da,' (DSB'yi anlatılan bir durum sanmış) → kaldır
    t = re.sub(r"\bDSB\s+olarak\s+belir(?:tilmiş|lenmiş|tilen|lenen)\s+"
               r"(?:olsa da|olmasına rağmen|olmakla birlikte|olduğu halde)\s*,?\s*", "", t, flags=re.I)
    # 0) YANLIŞ DSB KULLANIMLARI: DSB bir DEĞER yer tutucusudur; standart/kap/puan adı DEĞİL.
    #    'DSB standard*' → 'ilgili standard*'
    t = re.sub(r"\bDSB\s+(standard\w*)", r"ilgili \1", t, flags=re.I)
    #    'DSB içerisinde/içinde/boyunca...' (sahte kap/zaman) → kaldır
    t = re.sub(r"\bDSB\s+(içerisinde|içinde|boyunca|süresince|aralığında)\b", "", t, flags=re.I)
    #    'DSB' + (birim/ol.../değer.../betimleyici DIŞINDA) bir kelime → sadece 'DSB'yi kaldır.
    #    \w* ile Türkçe EK'leri de kapsa: 'milisaniyeden', 'olmalıdır' KORUNUR.
    #    BETİMLEYİCİLER (seviye/oran/olasılık...) DSB'nin geçerli değeri niteler → KORUNUR.
    #    Örn: 'en az DSB seviyesinde', 'DSB oranında', 'DSB olasılığı' → DSB SİLİNMEZ.
    _DSB_KORU = (r"ol|değer|belirlen|seviye|oran|olasıl|doğruluk|hassasiyet|"
                 r"tolerans|kapasite|çözünürlük|band|bant|frekans|menzil|mesafe|süre")
    t = re.sub(r"\bDSB\s+(?!(?:" + _DSB_UNITS + r"|" + _DSB_KORU + r")\w*\b)"
               r"([a-zA-ZçğıöşüÇĞİÖŞÜ])", r"\1", t, flags=re.I)
    # A) '<sayı><birim> ...(en fazla 4 kelime)... (DSB)' → sayıyı 'DSB' yap, (DSB)'yi kaldır
    t = re.sub(_DSB_NUM + r"\s*" + _DSB_UNITS + r"?((?:\s+\S+){0,4}?)\s*\(\s*DSB\s*\)",
               r"DSB\1", t, flags=re.I)
    # B) 'örneğin/yaklaşık ...' içeren parantezleri sil
    t = re.sub(r"\s*\([^()]*(?:örneğin|örn\.?|ör\.?|yaklaşık|yakl\.?)[^()]*\)", "", t, flags=re.I)
    # C) sadece sayı(+birim) olan parantezleri sil: (100g), (20 °C), (0.5 saniye), (100)
    t = re.sub(r"\s*\(\s*[~≈]?\s*" + _DSB_NUM + r"\s*" + _DSB_UNITS + r"?\.?\s*\)", "", t, flags=re.I)
    # D) DSB'den ÖNCE gelen sayı(+birim): '100g DSB' -> 'DSB'
    t = re.sub(r"\b" + _DSB_NUM + r"\s*" + _DSB_UNITS + r"?\s+DSB\b", "DSB", t, flags=re.I)
    # E) DSB'den SONRA gelen sayı: 'DSB 2 saniye' -> 'DSB saniye'
    #    Virgül/iki nokta varyantı da dahil: 'DSB, 15 saniye' -> 'DSB saniye'
    t = re.sub(r"\bDSB\s*[,:]?\s+" + _DSB_NUM + r"\s*", "DSB ", t, flags=re.I)
    # E2) 'DSB olmalıdır bir X' → cümle başında anlamsız; 'Sistem, bir X' olarak düzelt
    t = re.sub(r"(?i)^\s*DSB\s+olmal[ıi]d[ıi]r\s+(?=bir\b)", "Sistem, ", t)
    # F) kalan yalnız '(DSB)' -> 'DSB'
    t = re.sub(r"\(\s*DSB\s*\)", "DSB", t, flags=re.I)
    # boşluk/noktalama düzelt
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([.,;:])", r"\1", t)
    t = t.strip(" ,;:")
    # baştan parça silinmiş olabilir → ilk harfi büyüt (Türkçe i → İ)
    if t and t[0].islower():
        t = ("İ" + t[1:]) if t[0] == "i" else (t[0].upper() + t[1:])
    return t


# Türkçe cevap beklerken model İngilizce'ye kayabiliyor (özellikle çok dilli modeller).
# Bu kelimeler Türkçe bir gereksinim/test cümlesinde bulunmaz.
_INGILIZCE = re.compile(
    r"(?i)\b(the|must|shall|should|be|is|are|was|were|and|or|with|within|from|"
    r"system|user|interface|test|verify|verified|detected|displayed|value|time|"
    r"data|when|then|that|this|all|each|for|not|has|have)\b")


def ingilizce_mi(text, esik=4):
    """Metin ağırlıklı İngilizce mi? (eşik: kaç İngilizce belirteç görülürse)
    Türkçe cümlelerde 'test', 'sistem' gibi ortak kelimeler tek tük geçebildiği için
    eşik kullanılır; tek bir kelime yüzünden geçerli cevap reddedilmez."""
    if not text:
        return False
    return len(_INGILIZCE.findall(text)) >= esik


def gecerli_mi(text, min_kelime=5):
    """Bir üretim çıktısı kabul edilebilir mi? (generator'ların ortak kapısı)
    - boş/çok kısa değil
    - ağırlıklı İngilizce değil
    - sadece 'DSB saniye' gibi tek parça değil
    """
    if not text:
        return False
    t = text.strip()
    if len(t.split()) < min_kelime:
        return False
    if ingilizce_mi(t):
        return False
    # yalnızca DSB + birim (cümle değil)
    if re.fullmatch(r"(?i)\s*DSB\s*" + _DSB_UNITS + r"?\s*\.?\s*", t):
        return False
    return True


def sayilari_dsb_yap(text):
    """
    Metindeki '<sayı><birim>' değerlerini 'DSB <birim>' yapar.
    Kaskadda üst madde DSB iken alt madde SAYI UYDURDUYSA, çelişkili 'değer DSB'dir' notu
    yerine bu fonksiyon uydurma sayıları doğrudan DSB'ye çevirir.
    Örn: '500ms içinde' → 'DSB ms içinde', '1 saniyeden' → 'DSB saniyeden'.
    """
    if not text:
        return text
    t = re.sub(r"\b\d+(?:[.,]\d+)?\s*(" + _DSB_UNITS + r")", r"DSB \1", text, flags=re.I)
    t = re.sub(r"\bDSB\s+DSB\b", "DSB", t, flags=re.I)   # olası 'DSB DSB'
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()
