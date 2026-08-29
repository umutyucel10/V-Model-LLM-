# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `mimari_cerceve/cikarim.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
mimari_cerceve.cikarim ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from mimari_cerceve.cikarim import
...` kullanmalı.
"""

import sys

from mimari_cerceve import cikarim as _module

sys.modules[__name__] = _module
