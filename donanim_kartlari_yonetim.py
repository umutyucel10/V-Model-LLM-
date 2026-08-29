# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_kartlari/yonetim.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
donanim_kartlari.yonetim ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from donanim_kartlari.yonetim import
...` kullanmalı.

Not: donanim_kartlari/yonetim.py'deki overrides_path()'in __file__ tabanlı
varsayılan yol hesabı, taşıma sırasında proje köküne göre davranışı
koruyacak şekilde güncellendi (bkz. o dosyadaki not).
"""

import sys

from donanim_kartlari import yonetim as _module

sys.modules[__name__] = _module
