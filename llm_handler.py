# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `llm/handler.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
llm.handler ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni kod
doğrudan `from llm.handler import ...` kullanmalı.

Not: llm/handler.py, doğrudan `python llm_handler.py` ile çalıştırılabilen
küçük bir bağlantı testi içeriyor (kendi `if __name__ == "__main__":`
bloğu var). Bu blok artık "llm.handler" adıyla import edildiğinde
tetiklenmiyor — bu yüzden aşağıda, bu dosya doğrudan çalıştırıldığında aynı
davranışı elle tetikliyoruz. Ayrıca manage_context_files()'ın __file__
tabanlı yol hesabı, taşıma sırasında proje köküne göre davranışı koruyacak
şekilde güncellendi (bkz. o dosyadaki not).
"""

import sys

from llm import handler as _module

sys.modules[__name__] = _module

if __name__ == "__main__":
    _module.test_gemma3_connection()
