# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `belge_uretim/sgd.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
belge_uretim.sgd ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni
kod doğrudan `from belge_uretim.sgd import ...` kullanmalı.

Not: belge_uretim/sgd.py'deki get_chunk_embeddings()'in __file__ tabanlı
HuggingFaceEmbeddings/ yol hesabı, taşıma sırasında proje köküne göre
davranışı koruyacak şekilde güncellendi.
"""

import sys

from belge_uretim import sgd as _module

sys.modules[__name__] = _module
