# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_detayli/raporlama.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
donanim_detayli.raporlama ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from donanim_detayli.raporlama import
...` kullanmalı.
"""

import sys

from donanim_detayli import raporlama as _module

sys.modules[__name__] = _module
