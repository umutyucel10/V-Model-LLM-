# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `donanim_kartlari/model.py`'ye taşındı
(bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). Var olan `from
donanim_kartlari_model import ...` satırlarının kırılmaması için bu dosya
yeni konumdan olduğu gibi yeniden ihraç ediyor. Yeni kod doğrudan
`from donanim_kartlari.model import ...` kullanmalı.

`__all__` listesindeki isimler `import *` ile, listede unutulmuş ama yine de
modülde tanımlı diğer public isimler varsa aşağıdaki döngüyle yeniden ihraç
ediliyor — böylece `__all__`'ın eksik olması sessizce kırık bir import'a yol
açmıyor (bkz. mimari_cerceve_model.py shim'inde bulunan AUTOMATIC_DERIVATION_KINDS
örneği).
"""

from donanim_kartlari.model import *  # noqa: F401,F403
from donanim_kartlari.model import __all__  # noqa: F401

from donanim_kartlari import model as _model

for _name in dir(_model):
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = getattr(_model, _name)
del _model, _name
