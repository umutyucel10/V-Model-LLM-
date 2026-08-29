# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `etki_analizi/simulasyon_ui.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
etki_analizi.simulasyon_ui ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from etki_analizi.simulasyon_ui import
...` kullanmalı.
"""

import sys

from etki_analizi import simulasyon_ui as _module

sys.modules[__name__] = _module
