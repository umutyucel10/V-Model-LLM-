# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — mimari_cerceve_ui.py'nin bölünmüş
parçalarından biri: modül seviyesi sabitler, veri sınıfları ve yardımcı
fonksiyonlar. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import ttkbootstrap as ttk

import mimari_cerceve_cikarim as extraction
import mimari_cerceve_dogrulama as validation
import mimari_cerceve_render as rendering
import mimari_cerceve_yonetim as management
from mimari_cerceve_gorunumleri import DODAF_RENDER_VIEW_IDS, NAF_RENDER_VIEW_IDS
from mimari_cerceve_katalog import get_view_definition
from mimari_cerceve_model import ArchitectureSnapshot, CandidateProposal, stable_id_for


SUPPORTED_SOURCE_TYPES = ("TID", "SGD", "STT")
LAYOUT_BREAKPOINT = 1180

VIEW_READY = "ready"
VIEW_REVIEW_REQUIRED = "review_required"
VIEW_MISSING_INPUT = "missing_input"
VIEW_BLOCKED = "blocked"
VIEW_CARD_STATES = frozenset({
    VIEW_READY, VIEW_REVIEW_REQUIRED, VIEW_MISSING_INPUT, VIEW_BLOCKED,
})


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    tr: str
    en: str


@dataclass(frozen=True, slots=True)
class ProfileOption:
    profile_id: str
    tr: str
    en: str
    framework_version: str
    application_profile: str = ""
    application_profile_version: str = ""


@dataclass(frozen=True, slots=True)
class SourceRequirement:
    requirement_id: str
    record_type: str
    content: str
    bound_to: str = ""


WORKFLOW_STEPS = (
    WorkflowStep("sources", "Kaynakları seç", "Select sources"),
    WorkflowStep("extract", "Mimari adayları çıkar", "Extract architecture candidates"),
    WorkflowStep("review", "Gözden geçir", "Review"),
    WorkflowStep("render", "Görünüm üret", "Generate view"),
    WorkflowStep("validate_export", "Doğrula ve dışa aktar", "Validate and export"),
)

PROFILE_OPTIONS: Mapping[str, ProfileOption] = MappingProxyType({
    "dodaf": ProfileOption("dodaf", "DoDAF 2.02", "DoDAF 2.02", "2.02"),
    "naf": ProfileOption(
        "naf", "NAF 4.1 / ArchiMate 3.2", "NAF 4.1 / ArchiMate 3.2",
        "4.1", "ArchiMate", "3.2",
    ),
})

PROFILE_VIEW_IDS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "dodaf": tuple(DODAF_RENDER_VIEW_IDS),
    "naf": tuple(NAF_RENDER_VIEW_IDS),
})

CANDIDATE_FILTER_ACTIONABLE = "actionable"
CANDIDATE_FILTER_APPROVED = "approved"
CANDIDATE_FILTER_ALL = "all"
CANDIDATE_FILTER_LABELS: Mapping[str, tuple[str, str]] = MappingProxyType({
    CANDIDATE_FILTER_ACTIONABLE: ("İncelenebilir", "Actionable"),
    CANDIDATE_FILTER_APPROVED: ("Onaylı", "Approved"),
    CANDIDATE_FILTER_ALL: ("Tümü (stale dahil)", "All (incl. stale)"),
})

# Yalnız bu durumlar kullanıcı kararına açıktır. ``stale``/``superseded`` kayıt
# güncel kaynakla yeniden çıkarılmadan onaylanamaz; varsayılan filtre bu yüzden
# onları gizler ve kullanıcı tıklayıp engel uyarısı almaz.
ACTIONABLE_RECORD_STATUSES = frozenset({
    management.STATUS_CANDIDATE, management.STATUS_EDITED, management.STATUS_REJECTED,
})


def filter_candidate_records(
    records: Mapping[str, Any], mode: str = CANDIDATE_FILTER_ACTIONABLE,
) -> tuple[str, ...]:
    """Aday listesini duruma göre süzer; kayıt kimliklerini sıralı döndürür."""

    if mode not in CANDIDATE_FILTER_LABELS:
        raise ValueError(f"Desteklenmeyen aday filtresi: {mode}")
    if mode == CANDIDATE_FILTER_ALL:
        keep = None
    elif mode == CANDIDATE_FILTER_APPROVED:
        keep = frozenset({management.STATUS_APPROVED})
    else:
        keep = ACTIONABLE_RECORD_STATUSES
    return tuple(sorted(
        record_id for record_id, record in records.items()
        if keep is None or getattr(record, "status", "") in keep
    ))


VIEW_STATE_LABELS: Mapping[str, tuple[str, str]] = MappingProxyType({
    VIEW_READY: ("Hazır", "Ready"),
    VIEW_REVIEW_REQUIRED: ("İnceleme Gerekli", "Review Required"),
    VIEW_MISSING_INPUT: ("Eksik Girdi", "Missing Input"),
    VIEW_BLOCKED: ("Engelli", "Blocked"),
})

LIGHT_STATUS_COLORS: Mapping[str, str] = MappingProxyType({
    "selection": "#0052CC",
    "verified": "#217A43",
    "review": "#9A6400",
    "error": "#B42318",
    "no_data": "#667085",
})
DARK_STATUS_COLORS: Mapping[str, str] = MappingProxyType({
    "selection": "#5AA0F2",
    "verified": "#66C58A",
    "review": "#F0B44D",
    "error": "#FF7B72",
    "no_data": "#A5AFB8",
})


def layout_mode_for_width(width: int) -> str:
    """Üç sütun veya erişilebilir dikey dar düzen kararını döndürür."""

    try:
        numeric = int(width)
    except (TypeError, ValueError) as error:
        raise TypeError("Pencere genişliği integer olmalıdır.") from error
    return "wide" if numeric >= LAYOUT_BREAKPOINT else "narrow"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def filter_source_requirements(
    flat_data: Mapping[str, Mapping[str, Any]],
    query: str = "",
    types: Sequence[str] | str | None = SUPPORTED_SOURCE_TYPES,
) -> tuple[SourceRequirement, ...]:
    """Girdiyi değiştirmeden yalnız TID/SGD/STT gereksinimlerini filtreler."""

    if not isinstance(flat_data, Mapping):
        raise TypeError("flat_data mapping olmalıdır.")
    if types is None:
        requested_types = set(SUPPORTED_SOURCE_TYPES)
    elif isinstance(types, str):
        requested_types = {_clean(types).upper()}
    else:
        requested_types = {_clean(item).upper() for item in types}
    requested_types &= set(SUPPORTED_SOURCE_TYPES)
    needle = _clean(query).casefold()
    records: list[SourceRequirement] = []
    for fallback_id, raw in flat_data.items():
        if not isinstance(raw, Mapping):
            continue
        record_type = _clean(raw.get("type")).upper()
        if record_type not in requested_types:
            continue
        requirement_id = _clean(raw.get("ID") or fallback_id).upper()
        content = _clean(raw.get("content") or raw.get("description"))
        bound_to = _clean(raw.get("bound_to") or raw.get("bound") or raw.get("parent_id")).upper()
        corpus = " ".join((requirement_id, record_type, content, bound_to)).casefold()
        if needle and needle not in corpus:
            continue
        records.append(SourceRequirement(requirement_id, record_type, content, bound_to))
    order = {value: index for index, value in enumerate(SUPPORTED_SOURCE_TYPES)}
    return tuple(sorted(records, key=lambda item: (
        order[item.record_type], item.requirement_id.casefold(), item.requirement_id,
    )))


def _has_integrity_error(report: Any) -> bool:
    if report is None:
        return False
    model_dimension = getattr(report, "model_integrity", None)
    if model_dimension is not None and getattr(model_dimension, "passed", True) is False:
        return True
    view_dimension = getattr(report, "view_generatability", None)
    if view_dimension is not None and getattr(view_dimension, "passed", True) is False:
        return True
    framework_dimension = getattr(report, "framework_conformance", None)
    if (
        framework_dimension is not None
        and hasattr(framework_dimension, "aligned")
        and getattr(framework_dimension, "aligned") is False
    ):
        return True
    return any(
        getattr(item, "severity", "") == "error" and getattr(item, "blocking", True)
        for dimension in (model_dimension, view_dimension, framework_dimension)
        if dimension is not None
        for item in getattr(dimension, "findings", ())
    )


def classify_view_card_state(
    render_result: Any | None = None,
    validation_report: Any | None = None,
    *,
    pending_candidates: int | bool = 0,
    stale: bool = False,
    blocked: bool = False,
    warning_count: int = 0,
) -> str:
    """Bir görünüm kartının durumunu güvenlik önceliğiyle sınıflandırır."""

    if blocked or stale or _has_integrity_error(validation_report):
        return VIEW_BLOCKED
    if render_result is not None and getattr(render_result, "status", "") == "blocked":
        if getattr(render_result, "missing_inputs", ()):
            return VIEW_MISSING_INPUT
        return VIEW_BLOCKED
    if pending_candidates or warning_count:
        return VIEW_REVIEW_REQUIRED
    if render_result is not None and getattr(render_result, "status", "") == "rendered":
        return VIEW_READY
    return VIEW_MISSING_INPUT


def view_card_status_label(status: str, language: str = "tr") -> str:
    if status not in VIEW_CARD_STATES:
        raise ValueError(f"Desteklenmeyen görünüm kartı durumu: {status}")
    return VIEW_STATE_LABELS[status][0 if language == "tr" else 1]

