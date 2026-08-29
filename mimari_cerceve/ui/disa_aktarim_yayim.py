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

class _YayimMixin:
    def _export_svg(self) -> None:
        if not self._ensure_current_project_context():
            return
        if not self._ensure_sources_ready():
            return
        result = self.current_render_result
        if not result or result.status != rendering.RENDER_STATUS_RENDERED or not result.svg:
            self.status_var.set(self._tr("Önce başarılı bir görünüm üretin.",
                                         "Generate a successful view first.")); return
        target = filedialog.asksaveasfilename(
            parent=self.window, defaultextension=".svg",
            filetypes=(("SVG", "*.svg"),),
            initialfile=f"{result.view_id}.svg",
        )
        if not target:
            return
        try:
            path = rendering.write_view_svg(result, target)
        except Exception as error:
            messagebox.showerror(self._tr("Dışa Aktarma Hatası", "Export Error"), str(error), parent=self.window)
            return
        self.status_var.set(self._tr(f"SVG dışa aktarıldı: {path}", f"SVG exported: {path}"))

    def _start_publish(self) -> None:
        if (
            self._working
            or self.management_state is None
            or not self._ensure_current_project_context()
        ):
            return
        if not self._ensure_sources_ready():
            return
        profile_id = self.profile_var.get()
        view_id = self.view_var.get()
        report = self.current_validation_report
        result = self.current_render_result
        snapshot = self.current_snapshot
        model_ok = bool(
            report is not None
            and getattr(getattr(report, "model_integrity", None), "passed", False)
        )
        view_result = next((
            item for item in getattr(
                getattr(report, "view_generatability", None), "view_results", ()
            )
            if getattr(item, "view_id", "") == view_id
        ), None)
        view_ok = bool(
            report is not None
            and getattr(getattr(report, "view_generatability", None), "passed", False)
            and view_result is not None
            and getattr(view_result, "generatable", False)
        )
        framework_dimension = getattr(report, "framework_conformance", None)
        framework_aligned = bool(
            framework_dimension is not None
            and getattr(
                framework_dimension,
                "aligned",
                getattr(framework_dimension, "passed", False),
            )
        )
        rendered = bool(
            result is not None
            and getattr(result, "status", "") == rendering.RENDER_STATUS_RENDERED
            and getattr(result, "svg", None)
            and getattr(result, "view_id", "") == view_id
        )
        snapshot_current = bool(
            snapshot is not None
            and getattr(snapshot, "framework_profile_id", "") == profile_id
            and view_id in getattr(snapshot, "selected_view_ids", ())
            and (
                not getattr(result, "snapshot_id", "")
                or getattr(result, "snapshot_id", "") == getattr(snapshot, "snapshot_id", "")
            )
        )
        if not (model_ok and view_ok and framework_aligned and rendered and snapshot_current):
            self.status_var.set(self._tr(
                "Yayım engellendi: güncel model bütünlüğü, görünüm üretilebilirliği, "
                "çerçeve hizası ve SVG sonucu birlikte doğrulanmalıdır.",
                "Publication blocked: current model integrity, view generatability, "
                "framework alignment, and SVG result must all be validated.",
            ))
            return
        self._publish_token += 1
        token = self._publish_token
        cancel_event = threading.Event()
        self._publish_cancel_event = cancel_event
        state = (
            management.ArchitectureManagementState.from_dict(
                deepcopy(self.management_state.to_dict())
            )
            if isinstance(self.management_state, management.ArchitectureManagementState)
            else self.management_state
        )
        actor = self._tr("UI Kullanıcısı", "UI User")
        validation_payload = (
            report.to_dict() if callable(getattr(report, "to_dict", None)) else {
                "framework_profile_id": profile_id,
                "view_id": view_id,
                "model_integrity_passed": model_ok,
                "view_generatable": view_ok,
                "framework_aligned": framework_aligned,
            }
        )
        render_payload = (
            result.to_dict() if callable(getattr(result, "to_dict", None)) else {
                "view_id": view_id,
                "snapshot_id": getattr(result, "snapshot_id", ""),
                "status": getattr(result, "status", ""),
                "content_sha256": getattr(result, "content_sha256", ""),
            }
        )
        render_payload.pop("svg", None)
        option = PROFILE_OPTIONS[profile_id]
        publication_context = {
            "claim": "framework_aligned_draft",
            "snapshot": {
                "snapshot_id": getattr(snapshot, "snapshot_id", ""),
                "version": getattr(snapshot, "version", ""),
                "selected_view_ids": list(getattr(snapshot, "selected_view_ids", ())),
            },
            "validation": validation_payload,
            "rendered_views": [render_payload],
            "application_profile": (
                {
                    "name": option.application_profile,
                    "version": option.application_profile_version,
                }
                if option.application_profile else None
            ),
        }
        rendered_svg = result.svg
        self._busy(True, self._tr("Mimari sürümü atomik olarak yayımlanıyor…",
                                  "Publishing architecture version atomically…"))

        def worker() -> None:
            try:
                result = management.publish_approved_architecture(
                    state,
                    actor,
                    publication_context=publication_context,
                    view_artifacts={view_id: rendered_svg},
                    precommit_guard=lambda: not cancel_event.is_set(),
                )
                error: Exception | None = None
            except Exception as caught:
                result = None; error = caught
            self._dispatch_after(lambda: self._finish_publish(token, result, error))

        try:
            publish_worker = threading.Thread(
                target=worker, daemon=True, name="architecture-version-publish",
            )
            publish_worker.start()
        except Exception as error:
            cancel_event.set()
            self._publish_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Yayım worker'ı başlatılamadı: {error}",
                f"Publication worker could not be started: {error}",
            ))

    def _finish_publish(self, token: int, result: Any, error: Exception | None) -> None:
        if token != self._publish_token or self._closed:
            return
        self._busy(False)
        if error is not None or result is None:
            self.status_var.set(self._tr(f"Mimari yayımlanamadı: {error}",
                                         f"Architecture could not be published: {error}")); return
        self.status_var.set(self._tr(
            f"{result.version} çerçeveyle hizalı taslak olarak yayımlandı · {Path(result.architecture_path)}",
            f"Published {result.version} as a framework-aligned draft · {Path(result.architecture_path)}",
        ))

