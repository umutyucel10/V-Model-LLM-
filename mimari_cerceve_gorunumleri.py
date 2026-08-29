# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `mimari_cerceve/gorunumleri.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
mimari_cerceve.gorunumleri ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from mimari_cerceve.gorunumleri import
...` kullanmalı.
"""

import sys

from mimari_cerceve import gorunumleri as _module

sys.modules[__name__] = _module
