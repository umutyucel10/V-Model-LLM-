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

class _GorunumMixin:
    def _on_profile_changed(self) -> None:
        # O sırada çalışan eski profil işi tamamlanabilir; sonucu yeni profile
        # uygulamamak için yalnız yerel token'ı geçersiz kılarız.
        self._publish_cancel_event.set()
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._publish_token += 1
        self._extraction_context.clear()
        if self._working:
            self._busy(False)
        profile_id = self.profile_var.get()
        self.management_state = self._states_by_profile.get(profile_id)
        self._state_revision += 1
        self.extraction_result = None
        self.current_snapshot = None
        self.current_render_result = None
        self.current_validation_report = None
        self.view_var.set(PROFILE_VIEW_IDS[profile_id][0])
        self._rebuild_view_cards()
        self._refresh_candidate_tree()
        self._clear_preview(self._tr("Henüz görünüm üretilmedi.", "No view has been generated yet."))
        self._refresh_view_cards()

    def _invalidate_architecture_outputs(self, profile_id: str) -> None:
        """Kaynak/karar değişince eski snapshot, doğrulama ve SVG'yi geçersizler."""

        for key in tuple(self._render_results):
            if key[0] == profile_id:
                self._render_results.pop(key, None)
        for key in tuple(self._validation_reports):
            if key[0] == profile_id:
                self._validation_reports.pop(key, None)
        for key in tuple(self._preview_images):
            if key[0] == profile_id:
                self._preview_images.pop(key, None)
        for key in tuple(self._preview_errors):
            if key[0] == profile_id:
                self._preview_errors.pop(key, None)
        if self.profile_var.get() == profile_id:
            self.current_snapshot = None
            self.current_render_result = None
            self.current_validation_report = None
            if hasattr(self, "preview_canvas"):
                self._clear_preview(self._tr(
                    "Kaynak veya kullanıcı kararı değişti; görünümü yeniden üretin.",
                    "Source data or user decision changed; regenerate the view.",
                ))

    def _rebuild_view_cards(self) -> None:
        for child in self.view_cards.winfo_children():
            child.destroy()
        self._view_card_widgets.clear()
        profile_id = self.profile_var.get()
        for index, view_id in enumerate(PROFILE_VIEW_IDS[profile_id]):
            row, column = divmod(index, 3)
            self.view_cards.columnconfigure(column, weight=1)
            card = ttk.Frame(self.view_cards, style="Architecture.Card.TFrame", padding=3)
            card.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0), pady=2)
            button = ttk.Button(
                card, text=view_id, command=lambda value=view_id: self._select_view(value),
                style="Architecture.View.TButton", width=9,
            )
            button.pack(side="left")
            badge = ttk.Label(card, text="", style="Architecture.NoData.TLabel")
            badge.pack(side="left", padx=(4, 0))
            self._view_card_widgets[view_id] = (button, badge)

    def _select_view(self, view_id: str) -> None:
        if view_id not in PROFILE_VIEW_IDS[self.profile_var.get()]:
            raise ValueError(f"Seçili profile ait olmayan görünüm: {view_id}")
        self.view_var.set(view_id)
        key = (self.profile_var.get(), view_id)
        self.current_render_result = self._render_results.get(key)
        self.current_validation_report = self._validation_reports.get(key)
        if self.current_render_result and self.current_render_result.svg:
            self._display_svg(
                self.current_render_result.svg,
                self._preview_images.get(key),
                self._preview_errors.get(key, ""),
            )
        else:
            self._clear_preview(self._tr("Bu görünüm henüz üretilmedi.", "This view has not been generated yet."))
        self._refresh_view_cards()

    def _view_status(self, view_id: str) -> str:
        profile = self.profile_var.get()
        state = self._states_by_profile.get(profile)
        definition = get_view_definition(profile, view_id)
        allowed_element_types = {
            *definition.required_element_types,
            *definition.optional_element_types,
            *(item for group in definition.required_any_of_element_types for item in group),
        }
        allowed_relationship_types = {
            *definition.required_relationships,
            *definition.optional_relationships,
            *(item for group in definition.required_any_of_relationships for item in group),
        }
        relevant_records = tuple(
            record for record in state.records.values()
            if (
                record.proposal.proposal_type == "element"
                and record.proposal.proposed_payload.get("element_type") in allowed_element_types
            ) or (
                record.proposal.proposal_type == "relationship"
                and record.proposal.proposed_payload.get("relationship_type")
                in allowed_relationship_types
            )
        ) if state else ()
        stale = any(item.status == management.STATUS_STALE for item in relevant_records)
        pending = sum(
            item.status in {management.STATUS_CANDIDATE, management.STATUS_EDITED}
            for item in relevant_records
        )
        report = self._validation_reports.get((profile, view_id))
        warning_count = 0
        if report:
            warning_count = sum(
                getattr(finding, "severity", "") == "warning"
                for dimension in (
                    report.view_generatability, report.model_integrity,
                    report.framework_conformance,
                )
                for finding in dimension.findings
            )
        return classify_view_card_state(
            self._render_results.get((profile, view_id)), report,
            pending_candidates=pending, stale=stale, warning_count=warning_count,
        )

    def _refresh_view_cards(self) -> None:
        language = self._language()
        current = self.view_var.get()
        for view_id, (button, badge) in self._view_card_widgets.items():
            status = self._view_status(view_id)
            badge.configure(
                text=view_card_status_label(status, language),
                style={
                    VIEW_READY: "Architecture.Ready.TLabel",
                    VIEW_REVIEW_REQUIRED: "Architecture.Review.TLabel",
                    VIEW_MISSING_INPUT: "Architecture.NoData.TLabel",
                    VIEW_BLOCKED: "Architecture.Error.TLabel",
                }[status],
            )
            button.configure(style=(
                "Architecture.ViewSelected.TButton" if view_id == current
                else "Architecture.View.TButton"
            ))

