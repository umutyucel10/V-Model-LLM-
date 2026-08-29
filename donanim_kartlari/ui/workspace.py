# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — donanim_kartlari_ui.py'nin bölünmüş
parçalarından biri: HardwareCardsWorkspace sınıfının kendisi, mixin'lerin
birleşimi olarak. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
"""

from .kurulum import _KurulumMixin
from .filtre import _FiltreMixin
from .liste_render import _ListeRenderMixin
from .karsilastirma import _KarsilastirmaMixin
from .detay_paneli import _DetayPaneliMixin
from .duzenleme import _DuzenlemeMixin
from .gezinme import _GezinmeMixin


class HardwareCardsWorkspace(
    _KurulumMixin,
    _FiltreMixin,
    _ListeRenderMixin,
    _KarsilastirmaMixin,
    _DetayPaneliMixin,
    _DuzenlemeMixin,
    _GezinmeMixin,
):
    """Ürün ağacı, katalog ve datasheet ayrıntılarını senkronize eder."""
