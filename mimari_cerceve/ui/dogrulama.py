# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — mimari_cerceve_ui.py'nin bölünmüş
parçalarından biri. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
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

class _DogrulamaMixin:
    def _validate_current(self) -> None:
        if (
            self._working
            or not self._ensure_current_project_context()
            or self.management_state is None
        ):
            return
        if not self._ensure_sources_ready():
            return
        view_id = self.view_var.get()
        profile_id = self.profile_var.get()
        option = PROFILE_OPTIONS[profile_id]
        app_profile = (
            {"name": option.application_profile, "version": option.application_profile_version}
            if option.application_profile else None
        )
        existing_snapshot = self.current_snapshot
        if (
            existing_snapshot is not None
            and (
                existing_snapshot.framework_profile_id != profile_id
                or view_id not in existing_snapshot.selected_view_ids
            )
        ):
            existing_snapshot = None
        self._validation_token += 1
        token = self._validation_token
        state = self.management_state
        self._busy(True, self._tr(
            "Mimari doğrulama arka planda çalışıyor…",
            "Architecture validation is running in background…",
        ))
        try:
            worker = threading.Thread(
                target=self._validation_worker,
                args=(token, state, existing_snapshot, view_id, app_profile),
                daemon=True,
                name="architecture-validation",
            )
            worker.start()
        except Exception as error:
            self._validation_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Doğrulama worker'ı başlatılamadı: {error}",
                f"Validation worker could not be started: {error}",
            ))

    def _validation_worker(
        self,
        token: int,
        state: management.ArchitectureManagementState,
        snapshot: ArchitectureSnapshot | None,
        view_id: str,
        application_profile: Mapping[str, str] | None,
    ) -> None:
        try:
            working_state = management.ArchitectureManagementState.from_dict(
                state.to_dict()
            )
            if snapshot is None:
                snapshot = management.build_working_snapshot(
                    working_state, (view_id,), version="v0001",
                )
            report = validation.validate_architecture(
                snapshot,
                selected_view_ids=(view_id,),
                management_state=working_state,
                application_profile=application_profile,
            )
            error: Exception | None = None
        except Exception as caught:
            report = None
            error = caught
        self._dispatch_after(lambda: self._finish_validation(
            token, snapshot, view_id, report, error,
        ))

    def _finish_validation(
        self,
        token: int,
        snapshot: ArchitectureSnapshot | None,
        view_id: str,
        report: validation.ArchitectureValidationReport | None,
        error: Exception | None,
    ) -> None:
        if token != self._validation_token or self._closed:
            return
        self._busy(False)
        if error is not None or report is None or snapshot is None:
            self.status_var.set(self._tr(
                f"Doğrulama tamamlanamadı: {error}",
                f"Validation failed: {error}",
            ))
            return
        if (
            self.management_state is None
            or snapshot.project_id != self.management_state.project_id
            or snapshot.framework_profile_id != self.profile_var.get()
            or view_id != self.view_var.get()
            or not self._project_context_matches()
        ):
            return
        self.current_snapshot = snapshot
        self.current_validation_report = report
        self._validation_reports[(snapshot.framework_profile_id, view_id)] = report
        self._populate_validation_findings(self._selected_record())
        self._refresh_view_cards()
        self._select_step("validate_export")
        self.status_var.set(
            f"{report.view_generatability.status} · {report.model_integrity.status} · "
            f"{report.framework_conformance.status}"
        )

