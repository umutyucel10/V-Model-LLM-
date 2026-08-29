# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `belge_uretim/sablon.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
belge_uretim.sablon ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor.

Not: belge_uretim/sablon.py'nin (eski sablon_generator_logic.py'nin) TÜM
içeriği baştan sona tek bir üçlü-tırnaklı string'in içinde — yani dosya
zaten devre dışı/ölü kod (hiçbir isim tanımlamıyor, sadece bir string
ifadesi). Bu taşıma bu durumu değiştirmiyor, olduğu gibi taşıyor.
"""

import sys

from belge_uretim import sablon as _module

sys.modules[__name__] = _module
