# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `belge_uretim/dtet_ytet.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
belge_uretim.dtet_ytet ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor.
Yeni kod doğrudan `from belge_uretim.dtet_ytet import ...` kullanmalı.
"""

import sys

from belge_uretim import dtet_ytet as _module

sys.modules[__name__] = _module
