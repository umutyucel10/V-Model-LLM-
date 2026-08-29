# -*- coding: utf-8 -*-
"""mimari_cerceve.ui paketi (Faz 7 — mimari yeniden yapılandırma).

Eski mimari_cerceve_ui.py dosyasının bölündüğü hâli. Bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.

Not: tests/test_mimari_cerceve_ui.py gibi test dosyaları
`patch.object(ui.threading, "Thread")`, `patch.object(ui.management, ...)`
gibi çağrılarla modülün üzerindeki ham import edilmiş modüllere
(threading, filedialog, messagebox, simpledialog, extraction, management,
rendering) doğrudan erişiyor - bunlar burada da yeniden ihraç ediliyor ki
bu testler şeffaf çalışsın (hepsi zaten paylaşılan tekil modül nesneleri,
hangi dosyadan erişildiği fark etmez).
"""

from .yardimcilar import (
    SUPPORTED_SOURCE_TYPES,
    LAYOUT_BREAKPOINT,
    VIEW_READY,
    VIEW_REVIEW_REQUIRED,
    VIEW_MISSING_INPUT,
    VIEW_BLOCKED,
    VIEW_CARD_STATES,
    WorkflowStep,
    ProfileOption,
    SourceRequirement,
    WORKFLOW_STEPS,
    PROFILE_OPTIONS,
    PROFILE_VIEW_IDS,
    CANDIDATE_FILTER_ACTIONABLE,
    CANDIDATE_FILTER_APPROVED,
    CANDIDATE_FILTER_ALL,
    CANDIDATE_FILTER_LABELS,
    ACTIONABLE_RECORD_STATUSES,
    filter_candidate_records,
    VIEW_STATE_LABELS,
    LIGHT_STATUS_COLORS,
    DARK_STATUS_COLORS,
    layout_mode_for_width,
    _clean,
    filter_source_requirements,
    _has_integrity_error,
    classify_view_card_state,
    view_card_status_label,
    threading,
    filedialog,
    messagebox,
    simpledialog,
    extraction,
    management,
    rendering,
)
from .workspace import ArchitectureFrameworkWorkspace

__all__ = [
    'SUPPORTED_SOURCE_TYPES',
    'LAYOUT_BREAKPOINT',
    'VIEW_READY',
    'VIEW_REVIEW_REQUIRED',
    'VIEW_MISSING_INPUT',
    'VIEW_BLOCKED',
    'VIEW_CARD_STATES',
    'WorkflowStep',
    'ProfileOption',
    'SourceRequirement',
    'WORKFLOW_STEPS',
    'PROFILE_OPTIONS',
    'PROFILE_VIEW_IDS',
    'CANDIDATE_FILTER_ACTIONABLE',
    'CANDIDATE_FILTER_APPROVED',
    'CANDIDATE_FILTER_ALL',
    'CANDIDATE_FILTER_LABELS',
    'ACTIONABLE_RECORD_STATUSES',
    'filter_candidate_records',
    'VIEW_STATE_LABELS',
    'LIGHT_STATUS_COLORS',
    'DARK_STATUS_COLORS',
    'layout_mode_for_width',
    '_clean',
    'filter_source_requirements',
    '_has_integrity_error',
    'classify_view_card_state',
    'view_card_status_label',
    'threading',
    'filedialog',
    'messagebox',
    'simpledialog',
    'extraction',
    'management',
    'rendering',
    "ArchitectureFrameworkWorkspace",
]
