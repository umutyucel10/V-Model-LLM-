# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `core/config.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
core.config ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor — yani
`import config` ile `import core.config` birebir aynı nesneyi verir;
`patch.object(config, "...")` gibi test mock'ları da (private/özel isimler
dahil) sorunsuz çalışır. Yeni kod doğrudan `from core.config import ...`
kullanmalı.
"""

import sys

from core import config as _module

sys.modules[__name__] = _module
