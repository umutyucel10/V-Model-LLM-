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

class _KurulumMixin:
    def __init__(
        self,
        master: tk.Misc,
        style: ttk.Style,
        flat_data_getter: Callable[[], Mapping[str, Mapping[str, Any]]],
        traceability_getter: Callable[[], Mapping[str, Any] | None],
        project_name_getter: Callable[[], str],
        language_getter: Callable[[], str],
        palette_getter: Callable[[], Mapping[str, str]],
        on_close: Callable[[], None] | None = None,
        language_toggle_callback: Callable[[], None] | None = None,
        theme_toggle_callback: Callable[[], None] | None = None,
    ) -> None:
        self.master = master
        self.style = style
        self.flat_data_getter = flat_data_getter
        self.traceability_getter = traceability_getter
        self.project_name_getter = project_name_getter
        self.language_getter = language_getter
        self.palette_getter = palette_getter
        self.on_close = on_close
        self.language_toggle_callback = language_toggle_callback
        self.theme_toggle_callback = theme_toggle_callback

        self._translatable: list[tuple[Any, str, str]] = []
        self._layout_mode = ""
        self._language_override: str | None = None
        self._palette_override: dict[str, str] | None = None
        self._closed = False
        self._extraction_token = 0
        self._render_token = 0
        self._validation_token = 0
        self._source_change_token = 0
        self._publish_token = 0
        # All architecture-state files owned by this workspace share one writer.
        # The source token is the CAS generation; the lock guarantees that a
        # superseded worker cannot finish its write after a newer worker.
        self._state_write_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._state_revision = 0
        self._publish_cancel_event = threading.Event()
        self._source_revision_blocked = False
        self._source_mutation_in_progress = False
        self._source_generation_in_progress = False
        self._traceability_revision_blocked = False
        self._pending_source_changed_ids: set[str] = set()
        self._pending_source_mark_all = False
        self._pending_source_profiles: set[str] = set()
        self._working = False
        self._source_records: tuple[SourceRequirement, ...] = ()
        self._states_by_profile: dict[str, management.ArchitectureManagementState] = {}
        self.management_state: management.ArchitectureManagementState | None = None
        self.extraction_result: extraction.ArchitectureExtractionResult | None = None
        self.current_snapshot: ArchitectureSnapshot | None = None
        self.current_render_result: rendering.ViewRenderResult | None = None
        self.current_validation_report: validation.ArchitectureValidationReport | None = None
        self._render_results: dict[tuple[str, str], rendering.ViewRenderResult] = {}
        self._validation_reports: dict[tuple[str, str], validation.ArchitectureValidationReport] = {}
        self._preview_images: dict[tuple[str, str], Any] = {}
        self._preview_errors: dict[tuple[str, str], str] = {}
        self._view_card_widgets: dict[str, tuple[Any, Any]] = {}
        self._preview_photo: Any | None = None
        self._active_project_name = _clean(self.project_name_getter()) or "Proje"
        self._extraction_context: dict[
            int, tuple[str, str, tuple[str, ...], dict[str, str]]
        ] = {}
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._poll_after_id: Any | None = None

        self.window = tk.Toplevel(master)
        self.window.geometry("1480x860")
        self.window.minsize(820, 620)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.profile_var = tk.StringVar(value="dodaf")
        self.view_var = tk.StringVar(value=PROFILE_VIEW_IDS["dodaf"][0])
        self.source_query_var = tk.StringVar()
        self.source_type_var = tk.StringVar(value="ALL")
        self.status_var = tk.StringVar()
        self.source_count_var = tk.StringVar()
        self.confidence_var = tk.DoubleVar(value=0.0)
        self.confidence_text_var = tk.StringVar(value="—")
        self.active_step_var = tk.StringVar(value=WORKFLOW_STEPS[0].step_id)
        self.candidate_filter_var = tk.StringVar(value=CANDIDATE_FILTER_ACTIONABLE)
        self.candidate_count_var = tk.StringVar(value="")

        self._build()
        self.apply_theme()
        self.refresh_language()
        self.refresh()
        self.window.bind("<Configure>", self._on_resize)
        initial_width = self.window.winfo_width()
        self._apply_responsive_layout(initial_width if initial_width > 1 else 1480)
        self._poll_after_id = self.window.after(40, self._poll_ui_queue)

    @property
    def exists(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except (AttributeError, tk.TclError):
            return False

    def focus(self) -> None:
        if not self.exists:
            return
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._publish_cancel_event.set()
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._source_change_token += 1
        self._state_revision += 1
        self._publish_token += 1
        if self._poll_after_id is not None:
            try:
                self.window.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        try:
            if self.window.winfo_exists():
                self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def _language(self) -> str:
        value = self._language_override or _clean(self.language_getter()).casefold()
        return "en" if value == "en" else "tr"

    def _tr(self, tr_text: str, en_text: str) -> str:
        return tr_text if self._language() == "tr" else en_text

    def _palette(self) -> Mapping[str, str]:
        if self._palette_override is not None:
            return self._palette_override
        palette = self.palette_getter()
        return palette if isinstance(palette, Mapping) else {}

    def _label(self, parent: Any, tr: str, en: str, **kwargs: Any) -> Any:
        widget = ttk.Label(parent, text=self._tr(tr, en), **kwargs)
        self._translatable.append((widget, tr, en))
        return widget

    def _button(self, parent: Any, tr: str, en: str, **kwargs: Any) -> Any:
        widget = ttk.Button(parent, text=self._tr(tr, en), **kwargs)
        self._translatable.append((widget, tr, en))
        return widget

    def _build(self) -> None:
        self.root = ttk.Frame(self.window, style="Architecture.Root.TFrame", padding=12)
        self.root.pack(fill="both", expand=True)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, style="Architecture.Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        titles = ttk.Frame(header, style="Architecture.Root.TFrame")
        titles.grid(row=0, column=0, sticky="w")
        self._label(
            titles, "Mimari Çerçeve Stüdyosu", "Architecture Framework Studio",
            style="Architecture.Title.TLabel",
        ).pack(anchor="w")
        self._label(
            titles,
            "Kanıta bağlı adaylar · açık kullanıcı kararı · deterministik SVG",
            "Evidence-bound candidates · explicit user decision · deterministic SVG",
            style="Architecture.Muted.TLabel",
        ).pack(anchor="w")
        header_actions = ttk.Frame(header, style="Architecture.Root.TFrame")
        header_actions.grid(row=0, column=1, sticky="e")
        self.language_button = self._button(
            header_actions, "EN", "TR", command=self._toggle_language,
            style="secondary.Outline.TButton", width=5,
        )
        self.language_button.pack(side="left", padx=(0, 5))
        self.theme_button = self._button(
            header_actions, "Açık/Koyu", "Light/Dark", command=self._toggle_theme,
            style="secondary.Outline.TButton", width=11,
        )
        self.theme_button.pack(side="left")

        self.step_bar = ttk.Frame(self.root, style="Architecture.Root.TFrame")
        self.step_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.step_buttons: dict[str, Any] = {}
        for column, step in enumerate(WORKFLOW_STEPS):
            self.step_bar.columnconfigure(column, weight=1)
            button = self._button(
                self.step_bar, step.tr, step.en,
                command=lambda value=step.step_id: self._select_step(value),
                style="Architecture.Step.TButton",
            )
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))
            self.step_buttons[step.step_id] = button

        self.body = ttk.Frame(self.root, style="Architecture.Root.TFrame")
        self.body.grid(row=2, column=0, sticky="nsew")
        self.source_panel = ttk.Frame(self.body, style="Architecture.Panel.TFrame", padding=9)
        self.center_panel = ttk.Frame(self.body, style="Architecture.Panel.TFrame", padding=9)
        self.inspector_panel = ttk.Frame(self.body, style="Architecture.Panel.TFrame", padding=9)
        self._build_source_panel()
        self._build_center_panel()
        self._build_inspector_panel()

        footer = ttk.Frame(self.root, style="Architecture.Root.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Architecture.Status.TLabel").grid(
            row=0, column=0, sticky="w",
        )
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=140)
        self.progress.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.progress.grid_remove()

    def _build_source_panel(self) -> None:
        panel = self.source_panel
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        self._label(panel, "1 · Kaynak gereksinimleri", "1 · Source requirements",
                    style="Architecture.Section.TLabel").grid(row=0, column=0, sticky="w")
        filter_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        filter_row.grid(row=1, column=0, sticky="ew", pady=(7, 5))
        filter_row.columnconfigure(0, weight=1)
        self.source_search = ttk.Entry(filter_row, textvariable=self.source_query_var)
        self.source_search.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.source_search.bind("<KeyRelease>", lambda _event: self._refresh_source_tree())
        self.source_type_combo = ttk.Combobox(
            filter_row, textvariable=self.source_type_var, state="readonly", width=8,
            values=("ALL", *SUPPORTED_SOURCE_TYPES), style="Architecture.TCombobox",
        )
        self.source_type_combo.grid(row=0, column=1)
        self.source_type_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_source_tree())
        ttk.Label(panel, textvariable=self.source_count_var,
                  style="Architecture.MutedSurface.TLabel").grid(row=2, column=0, sticky="w")
        tree_wrap = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        tree_wrap.grid(row=3, column=0, sticky="nsew", pady=(5, 0))
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.source_tree = ttk.Treeview(
            tree_wrap, columns=("type", "id", "content"), show="headings",
            selectmode="extended", style="Architecture.Treeview",
        )
        self.source_tree.column("type", width=50, stretch=False, anchor="center")
        self.source_tree.column("id", width=105, stretch=False)
        self.source_tree.column("content", width=270, stretch=True)
        source_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.source_tree.yview)
        self.source_tree.configure(yscrollcommand=source_scroll.set)
        self.source_tree.grid(row=0, column=0, sticky="nsew")
        source_scroll.grid(row=0, column=1, sticky="ns")
        self.source_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_source_count())
        self.extract_button = self._button(
            panel, "Seçilenlerden aday çıkar", "Extract from selection",
            command=self._start_extraction, style="primary.TButton",
        )
        self.extract_button.grid(row=4, column=0, sticky="ew", pady=(7, 0))

    def _build_center_panel(self) -> None:
        panel = self.center_panel
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        profile_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        profile_row.grid(row=0, column=0, sticky="ew")
        profile_row.columnconfigure(2, weight=1)
        self._label(profile_row, "Çerçeve:", "Framework:",
                    style="Architecture.SectionSurface.TLabel").grid(row=0, column=0, padx=(0, 7))
        self.profile_buttons: dict[str, Any] = {}
        for column, option in enumerate(PROFILE_OPTIONS.values(), start=1):
            button = ttk.Radiobutton(
                profile_row, text=self._tr(option.tr, option.en), value=option.profile_id,
                variable=self.profile_var, command=self._on_profile_changed,
            )
            self._translatable.append((button, option.tr, option.en))
            button.grid(row=0, column=column, sticky="w", padx=(0, 8))
            self.profile_buttons[option.profile_id] = button

        self._label(panel, "Görünüm kartları", "View cards",
                    style="Architecture.SectionSurface.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 3),
        )
        self.view_cards = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        self.view_cards.grid(row=2, column=0, sticky="ew")
        self._rebuild_view_cards()

        self.preview_notebook = ttk.Notebook(panel, style="Architecture.TNotebook")
        self.preview_notebook.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        preview_page = ttk.Frame(self.preview_notebook, style="Architecture.Surface.TFrame")
        source_page = ttk.Frame(self.preview_notebook, style="Architecture.Surface.TFrame")
        preview_page.rowconfigure(0, weight=1); preview_page.columnconfigure(0, weight=1)
        source_page.rowconfigure(0, weight=1); source_page.columnconfigure(0, weight=1)
        self.preview_notebook.add(preview_page, text=self._tr("Şema", "Diagram"))
        self.preview_notebook.add(source_page, text="SVG")
        self.preview_canvas = tk.Canvas(preview_page, highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.svg_text = tk.Text(source_page, wrap="none", state=tk.DISABLED, font=("Consolas", 9))
        svg_y = ttk.Scrollbar(source_page, orient="vertical", command=self.svg_text.yview)
        svg_x = ttk.Scrollbar(source_page, orient="horizontal", command=self.svg_text.xview)
        self.svg_text.configure(yscrollcommand=svg_y.set, xscrollcommand=svg_x.set)
        self.svg_text.grid(row=0, column=0, sticky="nsew")
        svg_y.grid(row=0, column=1, sticky="ns"); svg_x.grid(row=1, column=0, sticky="ew")
        action_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        action_row.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        action_row.columnconfigure(0, weight=1)
        self.render_button = self._button(
            action_row, "Seçili görünümü üret", "Generate selected view",
            command=self._start_render, style="primary.TButton",
        )
        self.render_button.grid(row=0, column=0, sticky="ew")

    def _build_inspector_panel(self) -> None:
        panel = self.inspector_panel
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        self._label(panel, "3 · Gözden geçir", "3 · Review",
                    style="Architecture.Section.TLabel").grid(row=0, column=0, sticky="w")

        filter_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        filter_row.grid(row=1, column=0, sticky="ew", pady=(6, 3))
        filter_row.columnconfigure(2, weight=1)
        self._label(filter_row, "Göster:", "Show:",
                    style="Architecture.MutedSurface.TLabel").grid(row=0, column=0, padx=(0, 5))
        self.candidate_filter_combo = ttk.Combobox(
            filter_row, state="readonly", width=18, style="Architecture.TCombobox",
            values=[self._tr(*CANDIDATE_FILTER_LABELS[key]) for key in CANDIDATE_FILTER_LABELS],
        )
        self.candidate_filter_combo.current(0)
        self.candidate_filter_combo.grid(row=0, column=1)
        self.candidate_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._on_candidate_filter_changed(),
        )
        ttk.Label(filter_row, textvariable=self.candidate_count_var,
                  style="Architecture.MutedSurface.TLabel").grid(row=0, column=2, sticky="e")

        candidate_wrap = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        candidate_wrap.grid(row=2, column=0, sticky="nsew", pady=(0, 7))
        candidate_wrap.columnconfigure(0, weight=1); candidate_wrap.rowconfigure(0, weight=1)
        self.candidate_tree = ttk.Treeview(
            candidate_wrap, columns=("kind", "name", "status"), show="headings",
            selectmode="extended", height=7, style="Architecture.Treeview",
        )
        self.candidate_tree.column("kind", width=75, stretch=False)
        self.candidate_tree.column("name", width=190, stretch=True)
        self.candidate_tree.column("status", width=90, stretch=False)
        candidate_scroll = ttk.Scrollbar(candidate_wrap, orient="vertical", command=self.candidate_tree.yview)
        self.candidate_tree.configure(yscrollcommand=candidate_scroll.set)
        self.candidate_tree.grid(row=0, column=0, sticky="nsew")
        candidate_scroll.grid(row=0, column=1, sticky="ns")
        self.candidate_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_candidate())

        self.inspector_notebook = ttk.Notebook(panel, style="Architecture.TNotebook")
        self.inspector_notebook.grid(row=3, column=0, sticky="nsew")
        self.detail_page = ttk.Frame(self.inspector_notebook, style="Architecture.Surface.TFrame")
        self.relationship_page = ttk.Frame(self.inspector_notebook, style="Architecture.Surface.TFrame")
        self.evidence_page = ttk.Frame(self.inspector_notebook, style="Architecture.Surface.TFrame")
        self.validation_page = ttk.Frame(self.inspector_notebook, style="Architecture.Surface.TFrame")
        for page in (self.detail_page, self.relationship_page, self.evidence_page, self.validation_page):
            page.rowconfigure(0, weight=1); page.columnconfigure(0, weight=1)
        self.inspector_notebook.add(self.detail_page, text=self._tr("Öğe", "Element"))
        self.inspector_notebook.add(self.relationship_page, text=self._tr("İlişkiler", "Relationships"))
        self.inspector_notebook.add(self.evidence_page, text=self._tr("Kaynak kanıtı", "Source evidence"))
        self.inspector_notebook.add(self.validation_page, text=self._tr("Doğrulama", "Validation"))

        self.detail_text = tk.Text(self.detail_page, wrap="word", state=tk.DISABLED, font=("Segoe UI", 9))
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        self.relationship_tree = ttk.Treeview(
            self.relationship_page, columns=("type", "source", "target"), show="headings",
            style="Architecture.Treeview",
        )
        self.relationship_tree.grid(row=0, column=0, sticky="nsew")
        self.evidence_text = tk.Text(self.evidence_page, wrap="word", state=tk.DISABLED, font=("Segoe UI", 9))
        self.evidence_text.grid(row=0, column=0, sticky="nsew")
        self.validation_tree = ttk.Treeview(
            self.validation_page, columns=("severity", "message"), show="headings",
            style="Architecture.Treeview",
        )
        self.validation_tree.grid(row=0, column=0, sticky="nsew")

        confidence_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        confidence_row.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        confidence_row.columnconfigure(1, weight=1)
        self._label(confidence_row, "Güven", "Confidence",
                    style="Architecture.MutedSurface.TLabel").grid(row=0, column=0, padx=(0, 6))
        self.confidence_bar = ttk.Progressbar(
            confidence_row, maximum=1.0, variable=self.confidence_var, mode="determinate",
        )
        self.confidence_bar.grid(row=0, column=1, sticky="ew")
        ttk.Label(confidence_row, textvariable=self.confidence_text_var,
                  style="Architecture.MutedSurface.TLabel").grid(row=0, column=2, padx=(6, 0))

        review_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        review_row.grid(row=5, column=0, sticky="ew", pady=(7, 0))
        for column in range(3): review_row.columnconfigure(column, weight=1)
        self.approve_button = self._button(
            review_row, "Onayla", "Approve", command=self._approve_selected,
            style="success.TButton",
        )
        self.edit_button = self._button(
            review_row, "Düzenle", "Edit", command=self._edit_selected,
            style="warning.Outline.TButton",
        )
        self.reject_button = self._button(
            review_row, "Reddet", "Reject", command=self._reject_selected,
            style="danger.Outline.TButton",
        )
        self.approve_button.grid(row=0, column=0, sticky="ew")
        self.edit_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.reject_button.grid(row=0, column=2, sticky="ew")
        self.select_all_button = self._button(
            review_row, "Listedekilerin tümünü seç", "Select all listed",
            command=self._select_all_candidates,
            style="secondary.Outline.TButton",
        )
        self.select_all_button.grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0),
        )
        self.conflict_button = self._button(
            review_row, "Çakışmayı çöz", "Resolve conflict",
            command=self._resolve_selected_conflict,
            style="warning.TButton",
        )
        self.conflict_button.grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0),
        )

        export_row = ttk.Frame(panel, style="Architecture.Surface.TFrame")
        export_row.grid(row=6, column=0, sticky="ew", pady=(7, 0))
        for column in range(3): export_row.columnconfigure(column, weight=1)
        self.validate_button = self._button(
            export_row, "Doğrula", "Validate", command=self._validate_current,
            style="primary.Outline.TButton",
        )
        self.export_button = self._button(
            export_row, "SVG aktar", "Export SVG", command=self._export_svg,
            style="primary.Outline.TButton",
        )
        self.publish_button = self._button(
            export_row, "Mimariyi yayımla", "Publish architecture",
            command=self._start_publish, style="primary.TButton",
        )
        self.validate_button.grid(row=0, column=0, sticky="ew")
        self.export_button.grid(row=0, column=1, sticky="ew", padx=4)
        self.publish_button.grid(row=0, column=2, sticky="ew")

    def _select_step(self, step_id: str) -> None:
        if step_id not in {step.step_id for step in WORKFLOW_STEPS}:
            raise ValueError(f"Bilinmeyen çalışma adımı: {step_id}")
        self.active_step_var.set(step_id)
        for value, button in self.step_buttons.items():
            button.configure(style=(
                "Architecture.StepSelected.TButton" if value == step_id
                else "Architecture.Step.TButton"
            ))
        if self._layout_mode == "narrow":
            self._show_narrow_panel_for_step(step_id)

    def _show_narrow_panel_for_step(self, step_id: str) -> None:
        """Dar pencerede ağır panellerden yalnız seçili adıma ait olanı gösterir."""

        panel_by_step = {
            "sources": self.source_panel,
            "extract": self.source_panel,
            "review": self.inspector_panel,
            "render": self.center_panel,
            "validate_export": self.inspector_panel,
        }
        selected_panel = panel_by_step[step_id]
        for panel in (self.source_panel, self.center_panel, self.inspector_panel):
            panel.grid_forget()
        for row in range(3):
            self.body.rowconfigure(row, weight=0)
        self.body.rowconfigure(0, weight=1)
        selected_panel.grid(row=0, column=0, sticky="nsew")

    def _on_resize(self, event: Any) -> None:
        if getattr(event, "widget", None) is not self.window:
            return
        self._apply_responsive_layout(getattr(event, "width", 0))

    def _apply_responsive_layout(self, width: int) -> None:
        mode = layout_mode_for_width(width)
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        for panel in (self.source_panel, self.center_panel, self.inspector_panel):
            panel.grid_forget()
        for index in range(3):
            self.body.columnconfigure(index, weight=0)
            self.body.rowconfigure(index, weight=0)
        if mode == "wide":
            for column, step in enumerate(WORKFLOW_STEPS):
                self.step_bar.columnconfigure(column, weight=1)
                self.step_buttons[step.step_id].grid_configure(
                    row=0, column=column, sticky="ew",
                    padx=(0 if column == 0 else 3, 0), pady=0,
                )
            self.body.rowconfigure(0, weight=1)
            self.body.columnconfigure(0, weight=3)
            self.body.columnconfigure(1, weight=6)
            self.body.columnconfigure(2, weight=4)
            self.source_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            self.center_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
            self.inspector_panel.grid(row=0, column=2, sticky="nsew")
        else:
            for column in range(5):
                self.step_bar.columnconfigure(column, weight=1 if column < 3 else 0)
            for index, step in enumerate(WORKFLOW_STEPS):
                row, column = divmod(index, 3)
                self.step_buttons[step.step_id].grid_configure(
                    row=row, column=column, sticky="ew",
                    padx=(0 if column == 0 else 3, 0),
                    pady=(3 if row else 0, 0),
                )
            self.body.columnconfigure(0, weight=1)
            self._show_narrow_panel_for_step(self.active_step_var.get())

    def _toggle_language(self) -> None:
        if self.language_toggle_callback:
            self._language_override = None
            self.language_toggle_callback()
        else:
            self._language_override = "en" if self._language() == "tr" else "tr"
        self.refresh_language()

    def _toggle_theme(self) -> None:
        if self.theme_toggle_callback:
            self._palette_override = None
            self.theme_toggle_callback()
        else:
            current = self._palette()
            dark = _clean(current.get("bg")).casefold() == "#1f2329"
            if dark:
                self._palette_override = {
                    "bg": "#F5F6F7", "surface": "#FFFFFF", "fg": "#222222",
                    "muted": "#5C666D", "entry_bg": "#FFFFFF", "entry_fg": "#222222",
                    "accent": "#0052CC",
                }
            else:
                self._palette_override = {
                    "bg": "#1F2329", "surface": "#2B303A", "fg": "#E4E6EA",
                    "muted": "#95A0A8", "entry_bg": "#2B303A", "entry_fg": "#E8EAED",
                    "accent": "#5AA0F2",
                }
        self.apply_theme()

    def refresh_language(self) -> None:
        if not self.exists:
            return
        self.window.title(self._tr("Mimari Çerçeve Stüdyosu", "Architecture Framework Studio"))
        for widget, tr_text, en_text in self._translatable:
            try:
                widget.configure(text=self._tr(tr_text, en_text))
            except (AttributeError, tk.TclError):
                pass
        self.language_button.configure(text="EN" if self._language() == "tr" else "TR")
        source_headings = (
            ("type", "Tür", "Type"), ("id", "ID", "ID"),
            ("content", "Gereksinim", "Requirement"),
        )
        for key, tr_text, en_text in source_headings:
            self.source_tree.heading(key, text=self._tr(tr_text, en_text))
        for tree, headings in (
            (self.candidate_tree, (("kind", "Kayıt", "Record"), ("name", "Ad", "Name"), ("status", "Durum", "Status"))),
            (self.relationship_tree, (("type", "İlişki", "Relationship"), ("source", "Kaynak", "Source"), ("target", "Hedef", "Target"))),
            (self.validation_tree, (("severity", "Seviye", "Severity"), ("message", "Bulgu", "Finding"))),
        ):
            for key, tr_text, en_text in headings:
                tree.heading(key, text=self._tr(tr_text, en_text))
        self.preview_notebook.tab(0, text=self._tr("Şema", "Diagram"))
        for index, labels in enumerate((
            ("Öğe", "Element"), ("İlişkiler", "Relationships"),
            ("Kaynak kanıtı", "Source evidence"), ("Doğrulama", "Validation"),
        )):
            self.inspector_notebook.tab(index, text=self._tr(*labels))
        if hasattr(self, "candidate_filter_combo"):
            keys = tuple(CANDIDATE_FILTER_LABELS)
            current = self._candidate_filter_mode()
            self.candidate_filter_combo.configure(
                values=[self._tr(*CANDIDATE_FILTER_LABELS[key]) for key in keys],
            )
            self.candidate_filter_combo.current(keys.index(current))
        self._update_source_count()
        self._refresh_view_cards()
        self._refresh_candidate_tree()
        self._show_selected_candidate()

    def apply_theme(self) -> None:
        if not self.exists:
            return
        palette = dict(self._palette())
        palette.setdefault("bg", "#F5F6F7")
        palette.setdefault("surface", "#FFFFFF")
        palette.setdefault("fg", "#222222")
        palette.setdefault("muted", "#5C666D")
        palette.setdefault("entry_bg", palette["surface"])
        palette.setdefault("entry_fg", palette["fg"])
        palette.setdefault("accent", "#0052CC")
        dark = palette["bg"].casefold() == "#1f2329"
        colors = DARK_STATUS_COLORS if dark else LIGHT_STATUS_COLORS
        border = "#3D4550" if dark else "#D8DEE5"
        self.window.configure(background=palette["bg"])
        for style_name, background in (
            ("Architecture.Root.TFrame", palette["bg"]),
            ("Architecture.Panel.TFrame", palette["surface"]),
            ("Architecture.Surface.TFrame", palette["surface"]),
            ("Architecture.Card.TFrame", palette["surface"]),
        ):
            self.style.configure(style_name, background=background, bordercolor=border)
        self.style.configure("Architecture.Title.TLabel", background=palette["bg"], foreground=palette["fg"], font=("Segoe UI", 16, "bold"))
        self.style.configure("Architecture.Muted.TLabel", background=palette["bg"], foreground=palette["muted"], font=("Segoe UI", 9))
        self.style.configure("Architecture.Status.TLabel", background=palette["bg"], foreground=palette["muted"], font=("Segoe UI", 9))
        self.style.configure("Architecture.Section.TLabel", background=palette["surface"], foreground=palette["fg"], font=("Segoe UI", 10, "bold"))
        self.style.configure("Architecture.SectionSurface.TLabel", background=palette["surface"], foreground=palette["fg"], font=("Segoe UI", 9, "bold"))
        self.style.configure("Architecture.MutedSurface.TLabel", background=palette["surface"], foreground=palette["muted"], font=("Segoe UI", 8))
        self.style.configure("Architecture.Step.TButton", foreground=palette["muted"])
        self.style.configure("Architecture.StepSelected.TButton", foreground=colors["selection"])
        self.style.configure("Architecture.View.TButton", foreground=palette["fg"])
        self.style.configure("Architecture.ViewSelected.TButton", foreground=colors["selection"])
        self.style.configure("Architecture.Ready.TLabel", background=palette["surface"], foreground=colors["verified"], font=("Segoe UI", 8, "bold"))
        self.style.configure("Architecture.Review.TLabel", background=palette["surface"], foreground=colors["review"], font=("Segoe UI", 8, "bold"))
        self.style.configure("Architecture.Error.TLabel", background=palette["surface"], foreground=colors["error"], font=("Segoe UI", 8, "bold"))
        self.style.configure("Architecture.NoData.TLabel", background=palette["surface"], foreground=colors["no_data"], font=("Segoe UI", 8, "bold"))
        self.style.configure(
            "Architecture.Treeview", background=palette["entry_bg"], fieldbackground=palette["entry_bg"],
            foreground=palette["entry_fg"], rowheight=24,
        )
        self.style.map("Architecture.Treeview", background=[("selected", colors["selection"])], foreground=[("selected", "#FFFFFF")])
        self.style.configure(
            "Architecture.Treeview.Heading",
            background=palette["surface"], foreground=palette["fg"],
        )
        self.style.configure(
            "Architecture.TNotebook", background=palette["surface"], bordercolor=border,
        )
        self.style.configure(
            "Architecture.TNotebook.Tab", background=palette["bg"], foreground=palette["muted"],
        )
        self.style.map(
            "Architecture.TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", colors["selection"])],
        )
        self.style.configure(
            "Architecture.TCombobox",
            fieldbackground=palette["entry_bg"], background=palette["entry_bg"],
            foreground=palette["entry_fg"], arrowcolor=palette["fg"],
        )
        for text_widget in (self.detail_text, self.evidence_text, self.svg_text):
            text_widget.configure(
                background=palette["entry_bg"], foreground=palette["entry_fg"],
                insertbackground=palette["fg"],
            )
        self.preview_canvas.configure(background=palette["entry_bg"])
        self.preview_canvas.itemconfigure("placeholder", fill=palette["muted"])
        self._refresh_view_cards()


__all__ = [
    "ACTIONABLE_RECORD_STATUSES", "ArchitectureFrameworkWorkspace",
    "CANDIDATE_FILTER_ACTIONABLE", "CANDIDATE_FILTER_ALL", "CANDIDATE_FILTER_APPROVED",
    "CANDIDATE_FILTER_LABELS", "DARK_STATUS_COLORS", "LAYOUT_BREAKPOINT",
    "LIGHT_STATUS_COLORS", "PROFILE_OPTIONS", "PROFILE_VIEW_IDS", "ProfileOption",
    "SUPPORTED_SOURCE_TYPES", "SourceRequirement", "VIEW_BLOCKED", "VIEW_CARD_STATES",
    "VIEW_MISSING_INPUT", "VIEW_READY", "VIEW_REVIEW_REQUIRED", "VIEW_STATE_LABELS",
    "WORKFLOW_STEPS", "WorkflowStep", "classify_view_card_state",
    "filter_candidate_records", "filter_source_requirements", "layout_mode_for_width",
    "view_card_status_label",
]
