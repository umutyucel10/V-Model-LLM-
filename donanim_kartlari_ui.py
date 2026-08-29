# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu dosyanın (eskiden 2401 satırlık tek dosya) gerçek içeriği
`donanim_kartlari/ui/` alt paketine bölündü (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6 — mixin sınıfları deseni).
`sys.modules` üzerinden bu isim, donanim_kartlari.ui paketi ile TAM
OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni kod doğrudan
`from donanim_kartlari.ui import ...` kullanmalı.
"""

import sys

from donanim_kartlari import ui as _module

sys.modules[__name__] = _module
