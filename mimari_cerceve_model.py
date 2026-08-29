# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `mimari_cerceve/model.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
mimari_cerceve.model ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor —
`__all__`'ın eksik olması (bkz. AUTOMATIC_DERIVATION_KINDS) ya da özel
(private) isimlere yapılan test mock'ları gibi durumlarda bile şeffaf
çalışır (aynı nesne). Yeni kod doğrudan `from mimari_cerceve.model import
...` kullanmalı.
"""

import sys

from mimari_cerceve import model as _module

sys.modules[__name__] = _module
