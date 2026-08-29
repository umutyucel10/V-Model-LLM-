# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `etki_analizi/logic.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
etki_analizi.logic ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni
kod doğrudan `from etki_analizi.logic import ...` kullanmalı.
"""

import sys

from etki_analizi import logic as _module

sys.modules[__name__] = _module
