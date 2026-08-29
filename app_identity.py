# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `core/app_identity.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
core.app_identity ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor —
`patch.object(app_identity, "_set_macos_process_name", ...)` gibi private
isimleri hedefleyen test mock'ları da sorunsuz çalışır. Yeni kod doğrudan
`from core.app_identity import ...` kullanmalı.

Not: core/app_identity.py'deki resource_path(), taşıma sırasında proje
köküne göre yol hesabını koruyacak şekilde güncellendi (bkz. o dosyadaki not).
"""

import sys

from core import app_identity as _module

sys.modules[__name__] = _module
