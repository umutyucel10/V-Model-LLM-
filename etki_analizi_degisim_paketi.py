# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `etki_analizi/degisim_paketi.py`'ye taşındı
(bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu
isim, etki_analizi.degisim_paketi ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from etki_analizi.degisim_paketi
import ...` kullanmalı.

Not: etki_analizi/degisim_paketi.py'deki DEFAULT_OUTPUT_ROOT'un __file__
tabanlı yol hesabı, taşıma sırasında proje köküne göre davranışı koruyacak
şekilde güncellendi (bkz. o dosyadaki not).
"""

import sys

from etki_analizi import degisim_paketi as _module

sys.modules[__name__] = _module
