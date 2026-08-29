# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_kartlari/model.py`'ye taşındı
(bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). Var olan `from
donanim_kartlari_model import ...` satırlarının kırılmaması için bu dosya
yeni konumdan olduğu gibi yeniden ihraç ediyor. Yeni kod doğrudan
`from donanim_kartlari.model import ...` kullanmalı.
"""

from donanim_kartlari.model import *  # noqa: F401,F403
from donanim_kartlari.model import __all__  # noqa: F401
