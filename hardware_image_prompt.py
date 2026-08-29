# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `hardware_image/prompt.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
hardware_image.prompt ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor.
Yeni kod doğrudan `from hardware_image.prompt import ...` kullanmalı.
"""

import sys

from hardware_image import prompt as _module

sys.modules[__name__] = _module
