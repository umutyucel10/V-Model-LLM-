# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i (Faz 7 — mimari yeniden yapılandırma).

Bu modülün gerçek içeriği `rag/manager.py`'ye taşındı (bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md). `sys.modules` üzerinden bu isim,
rag.manager ile TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni kod
doğrudan `from rag.manager import ...` kullanmalı.

Not: rag/manager.py, doğrudan `python rag_manager.py` ile çalıştırılabilen
bir script (kendi `if __name__ == "__main__":` bloğu var). Ama bu blok artık
"rag.manager" adıyla import edildiğinde tetiklenmiyor (sadece gerçekten
`__main__` olarak çalıştırıldığında tetiklenir) — bu yüzden aşağıda, bu
dosya doğrudan çalıştırıldığında aynı davranışı elle tetikliyoruz.
"""

import sys

from rag import manager as _module

sys.modules[__name__] = _module

if __name__ == "__main__":
    print("🤖 IEEE 15288 RAG Sistem Yönetimi")
    _module.main_menu()
