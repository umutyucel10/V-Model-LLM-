# -*- coding: utf-8 -*-
"""donanim_kartlari.ui paketi (Faz 7 — mimari yeniden yapılandırma).

Eski donanim_kartlari_ui.py dosyasının böldüğü hâli. Bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
"""

from .yardimcilar import (
    DETAIL_TABS,
    ScrollableCards,
    HardwareEditorDialog,
    AlternativeDialog,
    catalog_filter_options,
    product_tree_instances,
)
from .workspace import HardwareCardsWorkspace

__all__ = [
    "DETAIL_TABS",
    "ScrollableCards",
    "HardwareEditorDialog",
    "AlternativeDialog",
    "catalog_filter_options",
    "product_tree_instances",
    "HardwareCardsWorkspace",
]
