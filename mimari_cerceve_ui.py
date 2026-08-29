# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu dosyanın (eskiden 2936 satırlık tek dosya) gerçek içeriği
`mimari_cerceve/ui/` alt paketine bölündü (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6 — mixin sınıfları deseni).
`sys.modules` üzerinden bu isim, mimari_cerceve.ui paketi ile TAM OLARAK
AYNI modül nesnesine yönlendiriliyor. Yeni kod doğrudan
`from mimari_cerceve.ui import ...` kullanmalı.
"""

import sys

from mimari_cerceve import ui as _module

sys.modules[__name__] = _module
