# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `rag/handler.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
rag.handler ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni kod
doğrudan `from rag.handler import ...` kullanmalı.
"""

import sys

from rag import handler as _module

sys.modules[__name__] = _module
