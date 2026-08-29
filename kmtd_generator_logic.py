# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `belge_uretim/kmtd.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
belge_uretim.kmtd ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni
kod doğrudan `from belge_uretim.kmtd import ...` kullanmalı.
"""

import sys

from belge_uretim import kmtd as _module

sys.modules[__name__] = _module
