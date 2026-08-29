# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `belge_uretim/dgoygo.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
belge_uretim.dgoygo ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor.
Yeni kod doğrudan `from belge_uretim.dgoygo import ...` kullanmalı.

Not: belge_uretim/dgoygo.py'deki get_chunk_embeddings()'in __file__ tabanlı
HuggingFaceEmbeddings/ yol hesabı, taşıma sırasında proje köküne göre
davranışı koruyacak şekilde güncellendi.
"""

import sys

from belge_uretim import dgoygo as _module

sys.modules[__name__] = _module
