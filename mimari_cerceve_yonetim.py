# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `mimari_cerceve/yonetim.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
mimari_cerceve.yonetim ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor.
Yeni kod doğrudan `from mimari_cerceve.yonetim import ...` kullanmalı.

Not: mimari_cerceve/yonetim.py'deki DEFAULT_OUTPUT_ROOT'un __file__ tabanlı
yol hesabı, taşıma sırasında proje köküne göre davranışı koruyacak şekilde
güncellendi (bkz. o dosyadaki not).
"""

import sys

from mimari_cerceve import yonetim as _module

sys.modules[__name__] = _module
