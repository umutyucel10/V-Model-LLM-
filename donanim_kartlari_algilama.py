# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_kartlari/algilama.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
donanim_kartlari.algilama ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from donanim_kartlari.algilama import
...` kullanmalı.
"""

import sys

from donanim_kartlari import algilama as _module

sys.modules[__name__] = _module
