# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `etki_analizi/degisim_ui.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
etki_analizi.degisim_ui ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from etki_analizi.degisim_ui import
...` kullanmalı.
"""

import sys

from etki_analizi import degisim_ui as _module

sys.modules[__name__] = _module
