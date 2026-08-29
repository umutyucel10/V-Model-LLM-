# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_kartlari/model.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
donanim_kartlari.model ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor —
`__all__`'ın eksik olması ya da özel (private) isimlere yapılan test
mock'ları gibi durumlarda bile şeffaf çalışır (aynı nesne). Yeni kod
doğrudan `from donanim_kartlari.model import ...` kullanmalı.
"""

import sys

from donanim_kartlari import model as _module

sys.modules[__name__] = _module
