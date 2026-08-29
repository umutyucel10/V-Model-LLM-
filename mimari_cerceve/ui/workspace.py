# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — mimari_cerceve_ui.py'nin bölünmüş
parçalarından biri: ArchitectureFrameworkWorkspace sınıfının kendisi,
mixin'lerin birleşimi olarak. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md
bölüm 6.
"""

from .kurulum import _KurulumMixin
from .kaynak_yonetimi import _KaynakMixin
from .cikarim_akisi import _CikarimMixin
from .gorunum_kartlari import _GorunumMixin
from .aday_inceleme import _AdayMixin
from .render_onizleme import _RenderMixin
from .dogrulama import _DogrulamaMixin
from .disa_aktarim_yayim import _YayimMixin


class ArchitectureFrameworkWorkspace(
    _KurulumMixin,
    _KaynakMixin,
    _CikarimMixin,
    _GorunumMixin,
    _AdayMixin,
    _RenderMixin,
    _DogrulamaMixin,
    _YayimMixin,
):
    """Beş adımlı, bağımsız Mimari Çerçeve Stüdyosu Toplevel'i."""
