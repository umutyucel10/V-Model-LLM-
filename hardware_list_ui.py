# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `hardware_liste/ui.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
hardware_liste.ui ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor.
Yeni kod doğrudan `from hardware_liste.ui import ...` kullanmalı.
"""

import sys

from hardware_liste import ui as _module

sys.modules[__name__] = _module
