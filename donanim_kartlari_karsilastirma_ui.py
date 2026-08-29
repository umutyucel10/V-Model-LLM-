# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_kartlari/karsilastirma_ui.py`'ye
taşındı (bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules`
üzerinden bu isim, donanim_kartlari.karsilastirma_ui ile TAM OLARAK AYNI
modül nesnesine yönlendiriliyor. Yeni kod doğrudan
`from donanim_kartlari.karsilastirma_ui import ...` kullanmalı.
"""

import sys

from donanim_kartlari import karsilastirma_ui as _module

sys.modules[__name__] = _module
