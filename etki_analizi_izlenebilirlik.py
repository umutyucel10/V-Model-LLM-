# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `core/izlenebilirlik.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md).

Faz 6 planı bu dosya için başlangıçta bir bölme (core + etki_analizi)
öneriyordu, ama taşıma öncesi yapılan kullanım analizi (17 public isimden
10'unun + DEFAULT_OUTPUT_ROOT'un donanim_kartlari, mimari_cerceve ve
doğrudan Arayüz.py tarafından kullanıldığını, en büyük fonksiyon olan
build_traceability_map'in bile yalnızca etki_analizi'ye özel olmadığını
gösterdi) sonucunda dosyanın TAMAMININ zaten paylaşılan bir çekirdek modül
olduğuna karar verildi — yapay bir bölme yapılmadı.

`sys.modules` üzerinden bu isim, core.izlenebilirlik ile TAM OLARAK AYNI
modül nesnesine yönlendiriliyor. Yeni kod doğrudan `from core.izlenebilirlik
import ...` kullanmalı.
"""

import sys

from core import izlenebilirlik as _module

sys.modules[__name__] = _module
