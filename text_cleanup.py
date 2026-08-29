# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `core/text_cleanup.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
core.text_cleanup ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni
kod doğrudan `from core.text_cleanup import ...` kullanmalı.
"""

import sys

from core import text_cleanup as _module

sys.modules[__name__] = _module
