# -*- coding: utf-8 -*-
"""Geriye dönük uyumluluk shim'i + giriş noktası (Faz 7 — mimari yeniden
yapılandırma, son adım).

Bu dosyanın (eskiden 3208 satırlık tek dosya) gerçek içeriği `arayuz/`
paketine bölündü (bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 3 ve 6 —
mixin sınıfları deseni). `sys.modules` üzerinden bu isim, arayuz paketi ile
TAM OLARAK AYNI modül nesnesine yönlendiriliyor. Yeni kod doğrudan
`from arayuz import ...` kullanmalı.

Bu dosya aynı zamanda uygulamanın GİRİŞ NOKTASIdır (`python Arayüz.py`).
rag_manager.py/rebuild_rag.py/llm_handler.py shim'lerinde kullanılan
teknikle aynı şekilde: sys.modules aliaslamasından SONRA `if __name__ ==
"__main__":` bloğu, `arayuz` paketinden gerekli adları kullanarak elle
tetikleniyor — çünkü paket import edildiğinde `arayuz/workspace.py`'nin
kendi `__name__`'i "arayuz.workspace" olur, "__main__" değil.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from arayuz import TIDGeneratorApp, prepare_process_identity, ttk  # noqa: E402

if __name__ != "__main__":
    # Yalniz "import Arayüz" ile kutuphane gibi kullanildiginda alias'la;
    # `python Arayüz.py` ile dogrudan calistirildiginda __name__ zaten
    # "__main__" olur ve sys.modules["__main__"]'i degistirmek gereksiz/
    # riskli olurdu (bu surecin kendi __main__ kaydini paketle degistirir).
    sys.modules[__name__] = sys.modules["arayuz"]

if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    prepare_process_identity()
    root = ttk.Window()
    app = TIDGeneratorApp(root)
    root.mainloop()
