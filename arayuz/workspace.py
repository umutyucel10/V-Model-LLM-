# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — Arayüz.py'nin bölünmüş
parçalarından biri: TIDGeneratorApp sınıfının kendisi, mixin'lerin
birleşimi olarak. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 3.
"""

from .pencere import _PencereMixin
from .dosya_surukle import _DosyaSurukleMixin
from .workspace_koordinasyon import _WorkspaceKoordinasyonMixin
from .donanim_entegrasyon import _DonanimEntegrasyonMixin
from .uretim_akisi import _UretimAkisiMixin
from .copilot import _CopilotMixin
from .disa_aktarim import _DisaAktarimMixin


class TIDGeneratorApp(
    _PencereMixin,
    _DosyaSurukleMixin,
    _WorkspaceKoordinasyonMixin,
    _DonanimEntegrasyonMixin,
    _UretimAkisiMixin,
    _CopilotMixin,
    _DisaAktarimMixin,
):
    pass
