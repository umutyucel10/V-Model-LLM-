# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_detayli/inceleme.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md — paket adının neden
"donanim_detayli_inceleme/" değil "donanim_detayli/" olduğuna dair not
için `donanim_detayli/__init__.py`'ye bakın). `sys.modules` üzerinden bu
isim, donanim_detayli.inceleme ile TAM OLARAK AYNI modül nesnesine
yönlendiriliyor. Yeni kod doğrudan `from donanim_detayli.inceleme import
...` kullanmalı.
"""

import sys

from donanim_detayli import inceleme as _module

sys.modules[__name__] = _module
