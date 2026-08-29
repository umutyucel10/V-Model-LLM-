# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `mimari_cerceve/model.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). Var olan `from mimari_cerceve_model
import ...` satırlarının kırılmaması için bu dosya yeni konumdan olduğu gibi
yeniden ihraç ediyor. Yeni kod doğrudan `from mimari_cerceve.model import ...`
kullanmalı.

`__all__` listesindeki isimler `import *` ile, listede unutulmuş ama yine de
modülde tanımlı diğer public isimler (ör. AUTOMATIC_DERIVATION_KINDS) ise
aşağıdaki döngüyle yeniden ihraç ediliyor — böylece `__all__`'ın eksik
olması sessizce kırık bir import'a yol açmıyor.
"""

from mimari_cerceve.model import *  # noqa: F401,F403
from mimari_cerceve.model import __all__  # noqa: F401

from mimari_cerceve import model as _model

for _name in dir(_model):
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = getattr(_model, _name)
del _model, _name
