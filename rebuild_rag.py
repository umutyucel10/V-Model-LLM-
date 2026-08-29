# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `rag/rebuild.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
rag.rebuild ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni kod
doğrudan `from rag.rebuild import ...` kullanmalı.

Not: rag/rebuild.py, doğrudan `python rebuild_rag.py` ile çalıştırılabilen
bir script (kendi `if __name__ == "__main__":` bloğu var). Bu blok artık
"rag.rebuild" adıyla import edildiğinde tetiklenmiyor — bu yüzden aşağıda,
bu dosya doğrudan çalıştırıldığında aynı davranışı elle tetikliyoruz.
"""

import sys

from rag import rebuild as _module

sys.modules[__name__] = _module

if __name__ == "__main__":
    _success = _module.main()
    if _success:
        print("\n🎉 RAG system is now working!")
    else:
        print("\n❌ RAG rebuild failed. Check the errors above.")
