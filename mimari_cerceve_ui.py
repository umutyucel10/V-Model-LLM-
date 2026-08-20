# -*- coding: utf-8 -*-
"""DoDAF/NAF Mimari Çerçeve Stüdyosu için bağımsız Tk çalışma alanı.

Bu modül mimari veri üretmez. Kaynak seçimi KART 2 çıkarım motoruna,
kullanıcı kararları KART 3 yönetim katmanına, doğrulama KART 4 motoruna ve
şema üretimi yalnız KART 5 ``ArchitectureSnapshot`` render motoruna gider.
Modül içe aktarılırken Tk kökü veya pencere oluşturulmaz.
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


class ArchitectureFrameworkWorkspace:
    """Beş adımlı, bağımsız Mimari Çerçeve Stüdyosu Toplevel'i."""

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

    def refresh(self) -> None:
        current_project_name = _clean(self.project_name_getter()) or "Proje"
        if current_project_name != self._active_project_name:
            self._reset_project_context(current_project_name)
        try:
            flat_snapshot = deepcopy(dict(self.flat_data_getter() or {}))
        except Exception as error:
            self.status_var.set(self._tr(
                f"Kaynak gereksinimleri okunamadı: {error}",
                f"Source requirements could not be read: {error}",
            ))
            flat_snapshot = {}
        self._flat_snapshot = flat_snapshot
        self._refresh_source_tree(select_all=True)
        self._refresh_candidate_tree()
        self._refresh_view_cards()

    def on_sources_changed(self, requirement_ids: Sequence[str] | None = None) -> None:
        """Kaynak revizyonunda eski kararları ezmeden ilgili kayıtları stale yapar."""

        if self._closed:
            return
        # Bu bildirim mutasyon tamamlandıktan sonra ana thread'den gelir.
        # Pre-mutation kancasının koyduğu katı kilit artık normal
        # stale-kaydı/onarım akışına devredilebilir.
        self._source_mutation_in_progress = False
        # Kaynak bildirimi ana ekrandaki proje değişiminden sonra gelebilir. Eski
        # projenin bellekteki durumunu yeni projenin ``flat_data`` verisiyle asla
        # kaydetme; önce bağlamı kesin olarak ayır.
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._publish_cancel_event.set()
        self._source_revision_blocked = True
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._source_change_token += 1
        self._state_revision += 1
        self._publish_token += 1
        self._extraction_context.clear()
        if self._working:
            self._busy(False)
        for affected_profile in PROFILE_OPTIONS:
            self._invalidate_architecture_outputs(affected_profile)
        incoming_changed_ids = frozenset(
            _clean(item).upper() for item in (requirement_ids or ()) if _clean(item)
        )
        pending_changed_ids = getattr(self, "_pending_source_changed_ids", set())
        self._pending_source_changed_ids = pending_changed_ids
        pending_changed_ids.update(incoming_changed_ids)
        if requirement_ids is None:
            self._pending_source_mark_all = True
        changed_ids = frozenset(pending_changed_ids)
        mark_all = bool(getattr(self, "_pending_source_mark_all", False))
        try:
            live_flat = self.flat_data_getter() or {}
            current_fingerprints = management.source_requirement_fingerprints(
                live_flat
            )
            current_known = tuple(
                item.requirement_id
                for item in filter_source_requirements(live_flat)
            )
        except Exception as error:
            self.status_var.set(self._tr(
                f"Kaynak değişikliği okunamadı: {error}",
                f"Source change could not be read: {error}",
            ))
            return
        token = self._source_change_token
        states = tuple(self._states_by_profile.items())
        pending_profiles = getattr(self, "_pending_source_profiles", set())
        self._pending_source_profiles = pending_profiles
        pending_profiles.update(profile_id for profile_id, _state in states)
        self._busy(True, self._tr(
            "Kaynak değişikliği arka planda kaydediliyor…",
            "Persisting source change in background…",
        ))
        try:
            worker = threading.Thread(
                target=self._source_change_worker,
                args=(
                    token, states, changed_ids, mark_all, current_known,
                    current_fingerprints,
                ),
                daemon=True,
                name="architecture-source-change",
            )
            worker.start()
        except Exception as error:
            self._source_change_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Kaynak değişikliği worker'ı başlatılamadı: {error}",
                f"Source-change worker could not be started: {error}",
            ))

    def on_source_mutation_started(self) -> None:
        """Kaynak mutasyonundan önce tüm eski mimari işleri thread-safe iptal eder.

        Ana uygulamadaki sohbet/generasyon worker'ları ``flat_data`` verisini Tk
        ana döngüsü dışında değiştirebilir. Bu kanca bilinçli olarak hiçbir
        Tk nesnesine dokunmaz; kaynak değişikliğinin ayrıntılı stale/yenileme
        bildirimi mutasyon tamamlandıktan sonra ``on_sources_changed`` ile gelir.
        """

        lifecycle_lock = getattr(self, "_lifecycle_lock", None)
        if lifecycle_lock is None:
            lifecycle_lock = threading.RLock()
            self._lifecycle_lock = lifecycle_lock
        with lifecycle_lock:
            publish_cancel = getattr(self, "_publish_cancel_event", None)
            if publish_cancel is not None:
                publish_cancel.set()
            # Yalnız Python durumuna dokunulur; Tk değişkeni/widget/getter'ı yoktur.
            # Post-mutation ``on_sources_changed`` UI temizliğini ve kalıcı stale
            # yazımını tamamlayana dek hiçbir eski iş sonucu kullanılamaz.
            self._source_revision_blocked = True
            self._source_mutation_in_progress = True
            self._extraction_token = getattr(self, "_extraction_token", 0) + 1
            self._render_token = getattr(self, "_render_token", 0) + 1
            self._validation_token = getattr(self, "_validation_token", 0) + 1
            self._source_change_token = getattr(self, "_source_change_token", 0) + 1
            self._publish_token = getattr(self, "_publish_token", 0) + 1
            self._state_revision = getattr(self, "_state_revision", 0) + 1
            extraction_context = getattr(self, "_extraction_context", None)
            if extraction_context is not None:
                extraction_context.clear()

    def _source_change_worker(
        self,
        token: int,
        states: Sequence[tuple[str, management.ArchitectureManagementState]],
        changed_ids: frozenset[str],
        mark_all: bool,
        current_known: tuple[str, ...],
        current_fingerprints: Mapping[str, str] | None = None,
    ) -> None:
        updated: dict[str, management.ArchitectureManagementState] = {}
        try:
            for profile_id, original in states:
                if token != self._source_change_token or self._closed:
                    raise management.ArchitectureManagementError(
                        "Kaynak değişikliği işlemi geçersiz kılındı."
                    )
                working = management.ArchitectureManagementState.from_dict(
                    deepcopy(original.to_dict())
                )
                for record in working.records.values():
                    if record.status == management.STATUS_SUPERSEDED:
                        continue
                    source_ids = set(record.automatic_proposal.source_requirement_ids)
                    affected = source_ids if mark_all else source_ids & set(changed_ids)
                    if affected:
                        management.mark_candidate_stale(
                            working,
                            record.record_id,
                            tuple(sorted(affected)),
                            "Kaynak veri değişti; önceki kullanıcı kararı yeniden incelenmeli.",
                        )
                working.known_requirement_ids = current_known
                working.source_requirement_fingerprints = dict(current_fingerprints or {})
                # The generation check and atomic profile write are one
                # serialized CAS boundary. If a newer generation starts while
                # this save is running, its worker waits and necessarily writes
                # last; an older worker waiting here is rejected before writing.
                with self._state_write_lock:
                    if token != self._source_change_token or self._closed:
                        raise management.ArchitectureManagementError(
                            "Kaynak değişikliği işlemi geçersiz kılındı."
                        )
                    management.save_profile_management_state(working)
                updated[profile_id] = working
            error: Exception | None = None
        except Exception as caught:
            error = caught
        self._dispatch_after(
            lambda: self._finish_source_change(token, updated, error)
        )

    def _finish_source_change(
        self,
        token: int,
        updated: Mapping[str, management.ArchitectureManagementState],
        error: Exception | None,
    ) -> None:
        if token != self._source_change_token or self._closed:
            return
        self._busy(False)
        if error is not None:
            self.management_state = self._states_by_profile.get(self.profile_var.get())
            self.refresh()
            self.status_var.set(self._tr(
                f"Kaynak değişikliği tam kaydedilemedi; yeniden tarama zorunlu: {error}",
                f"Source change was not fully saved; rescan is required: {error}",
            ))
            return
        self._states_by_profile.update(updated)
        self._state_revision += 1
        self._source_revision_blocked = bool(
            getattr(self, "_source_mutation_in_progress", False)
            or getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        )
        getattr(self, "_pending_source_changed_ids", set()).clear()
        self._pending_source_mark_all = False
        getattr(self, "_pending_source_profiles", set()).clear()
        profile_id = self.profile_var.get()
        self.management_state = self._states_by_profile.get(profile_id)
        self.extraction_result = None
        self.refresh()
        self.status_var.set(self._tr(
            (
                "Belge/izlenebilirlik üretimi sürüyor; mimari işlemleri geçici olarak engelli."
                if self._source_revision_blocked
                else "Kaynaklar değişti; ilgili mimari adaylar yeniden inceleme bekliyor."
            ),
            (
                "Document/traceability generation is still running; architecture actions remain blocked."
                if self._source_revision_blocked
                else "Sources changed; affected architecture candidates require review again."
            ),
        ))

    def on_generation_started(self) -> None:
        """Belge seti kısmen yazılırken eski izlenebilirliğin kullanılmasını engeller."""

        if self._closed:
            return
        self.on_source_mutation_started()
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._source_generation_in_progress = True
        self._traceability_revision_blocked = True
        self.on_sources_changed(None)

    def on_traceability_ready(
        self, requirement_ids: Sequence[str] | None = None,
    ) -> None:
        """Yeni belge seti ve ona ait izlenebilirlik birlikte hazır olduğunda kilidi yeniler."""

        if self._closed:
            return
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._source_generation_in_progress = False
        self._traceability_revision_blocked = False
        # Son ``flat_data`` ve yeni izlenebilirlik aynı revizyon olarak yeniden
        # işlenir; blok ancak bu kayıt başarıyla tamamlanınca kalkar.
        self.on_sources_changed(requirement_ids)

    def on_generation_failed(self, detail: str = "") -> None:
        """Yeni izlenebilirlik üretilemediyse eski raporla mimari işlemi açmaz."""

        if self._closed:
            return
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._source_generation_in_progress = False
        self._source_mutation_in_progress = False
        self._traceability_revision_blocked = True
        self._source_revision_blocked = True
        self._publish_cancel_event.set()
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._publish_token += 1
        self._extraction_context.clear()
        for profile_id in PROFILE_OPTIONS:
            self._invalidate_architecture_outputs(profile_id)
        if self._working:
            self._busy(False)
        suffix = f": {detail}" if _clean(detail) else ""
        self.status_var.set(self._tr(
            f"Yeni izlenebilirlik hazırlanamadı; mimari işlemler engelli{suffix}",
            f"New traceability is unavailable; architecture actions are blocked{suffix}",
        ))

    def _ensure_sources_ready(self) -> bool:
        if not (
            getattr(self, "_source_revision_blocked", False)
            or getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        ):
            return True
        self.status_var.set(self._tr(
            "Kaynak belge seti ve ona ait yeni izlenebilirlik henüz birlikte hazır değil.",
            "The source document set and its new traceability are not ready together yet.",
        ))
        return False

    def _ensure_extraction_ready(self) -> bool:
        """Yeni kaynak/izlenebilirlik tamamlanmadan çıkarım başlatma.

        Yalnızca kaynak durumunun atomik kaydı başarısız olduysa yeniden
        çıkarım, bu durumu güncel parmak izleriyle onarabilen tek kullanıcı
        eylemidir. Bu nedenle ``_source_revision_blocked`` tek başına çıkarımı
        engellemez; belge üretimi veya izlenebilirlik yenilemesi sürüyorsa engeller.
        Render, doğrulama ve yayımlama ise daha katı ``_ensure_sources_ready``
        kapısını kullanmaya devam eder.
        """

        if not (
            getattr(self, "_source_mutation_in_progress", False)
            or
            getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        ):
            return True
        self.status_var.set(self._tr(
            "Kaynak belge seti ve ona ait yeni izlenebilirlik henüz birlikte hazır değil.",
            "The source document set and its new traceability are not ready together yet.",
        ))
        return False

    def _ensure_current_project_context(self) -> bool:
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project == self._active_project_name:
            return True
        self._reset_project_context(current_project)
        self.refresh()
        self.status_var.set(self._tr(
            "Proje bağlamı değişti; eski mimari işlemi engellendi.",
            "Project context changed; the stale architecture action was blocked.",
        ))
        return False

    def _reset_project_context(self, project_name: str) -> None:
        """Açık pencere başka projeye geçtiğinde proje durumlarını kesin ayırır."""

        # Proje adı belge/izlenebilirlik üretimi sürerken değiştirilebilir.
        # Projeye özgü kaynak-kayıt hatasını taşıma; ancak uygulama-geneli
        # üretim/izlenebilirlik kilidini yeni bağlamda da koru.
        generation_in_progress = bool(
            getattr(self, "_source_generation_in_progress", False)
        )
        source_mutation_in_progress = bool(
            getattr(self, "_source_mutation_in_progress", False)
        )
        traceability_blocked = bool(
            getattr(self, "_traceability_revision_blocked", False)
        )
        self._publish_cancel_event.set()
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._source_change_token += 1
        self._state_revision += 1
        self._publish_token += 1
        self._active_project_name = _clean(project_name) or "Proje"
        self._states_by_profile.clear()
        self._render_results.clear()
        self._validation_reports.clear()
        self._preview_images.clear()
        self._preview_errors.clear()
        self._extraction_context.clear()
        self.management_state = None
        self.extraction_result = None
        self.current_snapshot = None
        self.current_render_result = None
        self.current_validation_report = None
        self._source_revision_blocked = bool(
            source_mutation_in_progress
            or generation_in_progress
            or traceability_blocked
        )
        self._source_mutation_in_progress = source_mutation_in_progress
        self._source_generation_in_progress = generation_in_progress
        self._traceability_revision_blocked = traceability_blocked
        self._pending_source_changed_ids.clear()
        self._pending_source_mark_all = False
        getattr(self, "_pending_source_profiles", set()).clear()
        if self._working:
            self._busy(False)
        if hasattr(self, "preview_canvas"):
            self._clear_preview(self._tr(
                "Proje değişti; önce yeni projenin kaynaklarını seçin.",
                "Project changed; select the new project's sources first.",
            ))

    def _filtered_sources(self) -> tuple[SourceRequirement, ...]:
        selected_type = _clean(self.source_type_var.get()).upper()
        types: Sequence[str] | str | None = (
            SUPPORTED_SOURCE_TYPES if selected_type in {"", "ALL"} else selected_type
        )
        return filter_source_requirements(
            getattr(self, "_flat_snapshot", {}), self.source_query_var.get(), types,
        )

    def _refresh_source_tree(self, select_all: bool = False) -> None:
        previous = set(self.source_tree.selection()) if hasattr(self, "source_tree") else set()
        records = self._filtered_sources()
        self._source_records = records
        for item in self.source_tree.get_children():
            self.source_tree.delete(item)
        for record in records:
            self.source_tree.insert(
                "", "end", iid=record.requirement_id,
                values=(record.record_type, record.requirement_id, record.content),
            )
        retained = [item.requirement_id for item in records if item.requirement_id in previous]
        if select_all and not previous:
            retained = [item.requirement_id for item in records]
        if retained:
            self.source_tree.selection_set(retained)
        self._update_source_count()

    def _update_source_count(self) -> None:
        selected_count = len(self.source_tree.selection())
        total = len(self._source_records)
        self.source_count_var.set(self._tr(
            f"{selected_count}/{total} kaynak seçili · yalnız TID/SGD/STT",
            f"{selected_count}/{total} sources selected · TID/SGD/STT only",
        ))

    def _selected_source_ids(self) -> tuple[str, ...]:
        return tuple(self.source_tree.selection())

    def _busy(self, value: bool, message: str = "") -> None:
        self._working = bool(value)
        self.status_var.set(message)
        buttons = (
            self.extract_button, self.render_button, self.validate_button,
            self.export_button, self.publish_button,
        )
        for button in buttons:
            button.configure(state=tk.DISABLED if value else tk.NORMAL)
        for button in getattr(self, "profile_buttons", {}).values():
            button.configure(state=tk.DISABLED if value else tk.NORMAL)
        for button, _badge in getattr(self, "_view_card_widgets", {}).values():
            button.configure(state=tk.DISABLED if value else tk.NORMAL)
        if value:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self._update_review_controls()

    def _start_extraction(self) -> None:
        if self._working or not self._ensure_current_project_context():
            return
        if not self._ensure_extraction_ready():
            return
        selected_ids = set(self._selected_source_ids())
        if not selected_ids:
            self.status_var.set(self._tr("En az bir kaynak seçin.", "Select at least one source."))
            return
        profile_id = self.profile_var.get()
        try:
            live_flat = self.flat_data_getter() or {}
            source_fingerprints = management.source_requirement_fingerprints(live_flat)
            known_requirement_ids = tuple(
                item.requirement_id for item in filter_source_requirements(live_flat)
            )
            flat_snapshot = {
                str(key): deepcopy(dict(value))
                for key, value in live_flat.items()
                if isinstance(value, Mapping)
                and _clean(value.get("ID") or key).upper() in selected_ids
            }
            trace = self.traceability_getter()
            if not isinstance(trace, Mapping):
                raise ValueError(self._tr(
                    "İzlenebilirlik raporu belirsiz/eksik; önce proje izlenebilirliğini üretin.",
                    "Traceability report is unknown/missing; build project traceability first.",
                ))
            trace_snapshot = deepcopy(dict(trace))
            existing_state = getattr(self, "_states_by_profile", {}).get(profile_id)
            state_payload = (
                deepcopy(existing_state.to_dict())
                if isinstance(existing_state, management.ArchitectureManagementState)
                else None
            )
        except Exception as error:
            self.status_var.set(str(error))
            return
        self._extraction_token += 1
        token = self._extraction_token
        self._extraction_context[token] = (
            profile_id, self._active_project_name, known_requirement_ids,
            source_fingerprints,
        )
        expected_state_revision = self._state_revision
        self._busy(True, self._tr("Adaylar arka planda çıkarılıyor…", "Extracting candidates in background…"))
        try:
            worker = threading.Thread(
                target=self._extraction_worker,
                args=(
                    token, flat_snapshot, trace_snapshot, profile_id,
                    state_payload, expected_state_revision,
                ),
                daemon=True,
                name="architecture-candidate-extraction",
            )
            worker.start()
        except Exception as error:
            self._extraction_context.pop(token, None)
            self._extraction_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Aday çıkarım worker'ı başlatılamadı: {error}",
                f"Candidate-extraction worker could not be started: {error}",
            ))

    def _project_context_matches(self) -> bool:
        """Arka plan sonucunun hâlâ güncel proje bağlamına ait olduğunu söyler."""

        current = _clean(self.project_name_getter()) or "Proje"
        return current == self._active_project_name


    def _dispatch_after(self, callback: Callable[[], None]) -> None:
        """Worker sonucunu Tk çağrısı yapmadan ana-thread kuyruğuna bırakır."""

        target_queue = getattr(self, "_ui_queue", None)
        if target_queue is None:
            target_queue = queue.Queue()
            self._ui_queue = target_queue
        target_queue.put(callback)

    def _poll_ui_queue(self) -> None:
        """Yalnız Tk ana iş parçacığındaki ``after`` döngüsünden çağrılır."""

        if self._closed:
            return
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as error:
                self.status_var.set(self._tr(
                    f"Arka plan sonucu uygulanamadı: {error}",
                    f"Background result could not be applied: {error}",
                ))
        if self.exists:
            self._poll_after_id = self.window.after(40, self._poll_ui_queue)

    def _extraction_worker(
        self,
        token: int,
        flat_snapshot: Mapping[str, Mapping[str, Any]],
        trace_snapshot: Mapping[str, Any],
        profile_id: str,
        state_payload: Mapping[str, Any] | None = None,
        expected_state_revision: int | None = None,
    ) -> None:
        try:
            result = extraction.extract_architecture_candidates(
                flat_snapshot, trace_snapshot, framework_profile_id=profile_id,
            )
            state = self._prepare_extraction_state(
                token, result, state_payload=state_payload,
                expected_state_revision=expected_state_revision,
            )
            error: Exception | None = None
        except Exception as caught:
            result = None
            state = None
            error = caught
        self._dispatch_after(
            lambda: self._finish_extraction(token, result, error, state)
        )

    def _extraction_guard_is_current(
        self,
        token: int,
        profile_id: str,
        context: Sequence[Any] | None,
        expected_state_revision: int | None = None,
    ) -> bool:
        """Worker yazımı için Tk'den bağımsız token/proje/profil CAS kapısı."""

        if context is None or len(context) < 2:
            return False
        return bool(
            not self._closed
            and token == self._extraction_token
            and self._extraction_context.get(token) == context
            and context[0] == profile_id
            and context[1] == self._active_project_name
            and (
                expected_state_revision is None
                or self._state_revision == expected_state_revision
            )
        )

    def _prepare_extraction_state(
        self,
        token: int,
        result: extraction.ArchitectureExtractionResult,
        *,
        state_payload: Mapping[str, Any] | None = None,
        expected_state_revision: int | None = None,
    ) -> management.ArchitectureManagementState:
        """Load/reconcile/save işlemlerini yalnız extraction worker'inda yapar."""

        context = self._extraction_context.get(token)
        profile_id = result.framework_profile_id
        if not self._extraction_guard_is_current(
            token, profile_id, context, expected_state_revision,
        ):
            raise management.ArchitectureManagementError(
                "Aday çıkarımı daha yeni bir proje, profil veya kaynak revizyonuyla geçersiz kılındı."
            )
        project_name = str(context[1])
        known_requirement_ids = tuple(context[2]) if len(context) > 2 else ()
        source_fingerprints = dict(context[3]) if len(context) > 3 else {}

        if state_payload is not None:
            state = management.ArchitectureManagementState.from_dict(
                deepcopy(dict(state_payload))
            )
        else:
            with self._state_write_lock:
                if not self._extraction_guard_is_current(
                    token, profile_id, context, expected_state_revision,
                ):
                    raise management.ArchitectureManagementError(
                        "Aday çıkarımı kalıcı durum okunmadan önce geçersiz kılındı."
                    )
                state = management.load_profile_management_state(
                    project_name, profile_id,
                )

        if state is None:
            state = management.create_management_state(
                project_name, result.candidates,
                framework_profile_id=profile_id,
                known_requirement_ids=known_requirement_ids,
                source_requirement_fingerprints=source_fingerprints,
            )
        else:
            management.reconcile_candidates(
                state,
                result.candidates,
                scanned_requirement_ids=result.processed_requirement_ids,
                known_requirement_ids=known_requirement_ids,
                source_fingerprints=source_fingerprints,
            )

        # Kaynak-stale worker'ları ve kullanıcı kararlarıyla aynı yazıcı
        # kilidini kullan. Token/context kontrolü ile atomik profil yazımı tek
        # CAS sınırıdır; superseded worker diske ulaşamaz.
        with self._state_write_lock:
            if not self._extraction_guard_is_current(
                token, profile_id, context, expected_state_revision,
            ):
                raise management.ArchitectureManagementError(
                    "Aday çıkarımı kalıcı durum yazılmadan önce geçersiz kılındı."
                )
            management.save_profile_management_state(state)
        return state

    def _finish_extraction(
        self,
        token: int,
        result: extraction.ArchitectureExtractionResult | None,
        error: Exception | None,
        state: management.ArchitectureManagementState | None = None,
    ) -> None:
        if token != self._extraction_token or self._closed:
            return
        context = self._extraction_context.pop(token, None)
        current_project = _clean(self.project_name_getter()) or "Proje"
        if (
            context is None
            or context[1] != current_project
            or (result is not None and context[0] != result.framework_profile_id)
        ):
            self._busy(False)
            if current_project != self._active_project_name:
                self._reset_project_context(current_project)
            return
        self._busy(False)
        if error is not None or result is None or state is None:
            self.status_var.set(self._tr(
                f"Aday çıkarımı tamamlanamadı: {error or 'kalıcı inceleme durumu hazırlanamadı'}",
                f"Candidate extraction failed: {error or 'persistent review state was not prepared'}",
            ))
            return
        self.extraction_result = result
        self._invalidate_architecture_outputs(result.framework_profile_id)
        try:
            self._states_by_profile[result.framework_profile_id] = state
            self.management_state = state
            self._state_revision += 1
            pending_profiles = getattr(self, "_pending_source_profiles", set())
            pending_profiles.discard(result.framework_profile_id)
            if not pending_profiles:
                getattr(self, "_pending_source_changed_ids", set()).clear()
                self._pending_source_mark_all = False
            self._source_revision_blocked = bool(
                pending_profiles
                or getattr(self, "_source_mutation_in_progress", False)
                or getattr(self, "_source_generation_in_progress", False)
                or getattr(self, "_traceability_revision_blocked", False)
            )
        except Exception as state_error:
            self.status_var.set(self._tr(
                f"Adaylar çıkarıldı; inceleme durumu hazırlanamadı: {state_error}",
                f"Candidates extracted; review state could not be prepared: {state_error}",
            ))
            return
        self._refresh_candidate_tree()
        self._refresh_view_cards()
        self._select_step("review")
        gap_count = len(result.information_gaps)
        self.status_var.set(self._tr(
            f"{len(result.candidates)} aday çıkarıldı; {gap_count} bilgi açığı ayrı kaydedildi.",
            f"Extracted {len(result.candidates)} candidates; {gap_count} information gaps recorded separately.",
        ))

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

    def _candidate_filter_mode(self) -> str:
        mode = _clean(self.candidate_filter_var.get())
        return mode if mode in CANDIDATE_FILTER_LABELS else CANDIDATE_FILTER_ACTIONABLE

    def _on_candidate_filter_changed(self) -> None:
        index = self.candidate_filter_combo.current()
        keys = tuple(CANDIDATE_FILTER_LABELS)
        self.candidate_filter_var.set(keys[index] if 0 <= index < len(keys) else keys[0])
        self._refresh_candidate_tree()

    def _select_all_candidates(self) -> None:
        """Filtrelenmiş listedeki tüm adayları seçer; gizli kayda dokunmaz."""

        children = self.candidate_tree.get_children()
        if children:
            self.candidate_tree.selection_set(children)
        self._show_selected_candidate()

    def _refresh_candidate_tree(self) -> None:
        if not hasattr(self, "candidate_tree"):
            return
        previous = tuple(self.candidate_tree.selection())
        for item in self.candidate_tree.get_children():
            self.candidate_tree.delete(item)
        state = getattr(self, "management_state", None)
        total = 0
        if state:
            total = len(state.records)
            for record_id in filter_candidate_records(
                state.records, self._candidate_filter_mode(),
            ):
                record = state.records[record_id]
                proposal = record.proposal
                payload = proposal.proposed_payload
                self.candidate_tree.insert(
                    "", "end", iid=record_id,
                    values=(proposal.proposal_type, payload.get("name", ""), record.status),
                    tags=(record.status,),
                )
        listed = self.candidate_tree.get_children()
        count_var = getattr(self, "candidate_count_var", None)
        if count_var is not None:
            count_var.set(
                self._tr(f"{len(listed)} / {total} kayıt", f"{len(listed)} / {total} records")
            )
        restored = tuple(item for item in previous if self.candidate_tree.exists(item))
        if restored:
            self.candidate_tree.selection_set(restored)
        elif listed:
            self.candidate_tree.selection_set(listed[0])
        self._show_selected_candidate()

    def _selected_records(self) -> tuple[management.ManagedCandidate, ...]:
        state = self.management_state
        selected = self.candidate_tree.selection() if hasattr(self, "candidate_tree") else ()
        if not state or not selected:
            return ()
        return tuple(
            record for record in (state.records.get(item) for item in selected)
            if record is not None
        )

    def _selected_record(self) -> management.ManagedCandidate | None:
        records = self._selected_records()
        return records[0] if records else None

    @staticmethod
    def _proposal_stable_id(proposal: CandidateProposal) -> str:
        """Adayın kanonikleşirse alacağı kimliği, içerik eklemeden hesaplar."""

        payload = proposal.proposed_payload
        if proposal.target_stable_id:
            return proposal.target_stable_id
        if proposal.proposal_type == "element":
            return stable_id_for("ARCH-ELEMENT", {
                "profile": proposal.framework_profile_id,
                "element_type": payload.get("element_type", ""),
                "identity_key": payload.get("identity_key", ""),
            })
        return stable_id_for("ARCH-REL", {
            "profile": proposal.framework_profile_id,
            "relationship_type": payload.get("relationship_type", ""),
            "identity_key": payload.get("identity_key", ""),
            "source": proposal.source_element_id,
            "target": proposal.target_element_id,
        })

    @staticmethod
    def _set_text(widget: Any, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def _show_selected_candidate(self) -> None:
        record = self._selected_record()
        for item in self.relationship_tree.get_children(): self.relationship_tree.delete(item)
        for item in self.validation_tree.get_children(): self.validation_tree.delete(item)
        if record is None:
            self._set_text(self.detail_text, self._tr("Aday seçilmedi.", "No candidate selected."))
            self._set_text(self.evidence_text, self._tr("Kaynak kanıtı yok.", "No source evidence."))
            self.confidence_var.set(0.0); self.confidence_text_var.set("—")
            self._update_review_controls()
            return
        proposal = record.proposal
        payload = proposal.proposed_payload
        details = [
            f"ID: {record.record_id}",
            f"{self._tr('Durum', 'Status')}: {record.status}",
            f"{self._tr('Tür', 'Type')}: {payload.get('element_type') or payload.get('relationship_type')}",
            f"{self._tr('Ad', 'Name')}: {payload.get('name', '')}",
            f"{self._tr('Açıklama', 'Description')}: {payload.get('description', '')}",
            f"{self._tr('Kaynak gereksinimler', 'Source requirements')}: {', '.join(proposal.source_requirement_ids)}",
        ]
        if record.stale_reason:
            details.append(f"stale: {record.stale_reason}")
        self._set_text(self.detail_text, "\n\n".join(details))
        evidence_parts = []
        for link in proposal.evidence_links:
            evidence_parts.append(
                f"{link.source_item_id} · {link.source_document}\n"
                f"{link.source_location}\n{link.evidence_text}\n"
                f"evidence_id={link.evidence_id}"
            )
        self._set_text(self.evidence_text, "\n\n".join(evidence_parts) or self._tr(
            "Kaynak kanıtı belirsiz/eksik.", "Source evidence is unknown/missing.",
        ))
        confidence = float(proposal.confidence_score)
        self.confidence_var.set(confidence)
        self.confidence_text_var.set(f"{confidence:.0%}")

        state = self.management_state
        if state:
            selected_stable_id = self._proposal_stable_id(proposal)
            for relation_record in state.records.values():
                candidate = relation_record.proposal
                if candidate.proposal_type != "relationship":
                    continue
                if relation_record.record_id == record.record_id or (
                    candidate.source_element_id == selected_stable_id
                    or candidate.target_element_id == selected_stable_id
                ):
                    relation_type = candidate.proposed_payload.get("relationship_type", "")
                    self.relationship_tree.insert(
                        "", "end", values=(
                            relation_type, candidate.source_element_id, candidate.target_element_id,
                        ),
                    )
        self._populate_validation_findings(record)
        self._update_review_controls()

    def _populate_validation_findings(self, record: management.ManagedCandidate | None = None) -> None:
        for item in self.validation_tree.get_children(): self.validation_tree.delete(item)
        report = self.current_validation_report
        if report:
            target_ids = {""}
            profile_id = (
                self.profile_var.get()
                if hasattr(self, "profile_var")
                else _clean(getattr(report, "framework_profile_id", ""))
            )
            view_id = self.view_var.get() if hasattr(self, "view_var") else ""
            target_ids.update((profile_id, view_id))
            if record:
                target_ids.update((
                    record.record_id,
                    record.proposal.proposal_id,
                    self._proposal_stable_id(record.proposal),
                ))
            for dimension in (
                report.view_generatability, report.model_integrity, report.framework_conformance,
            ):
                for finding in dimension.findings:
                    if finding.target_id and finding.target_id not in target_ids:
                        continue
                    scope = _clean(getattr(finding, "view_id", "")) or _clean(
                        getattr(finding, "target_id", "")
                    )
                    message = f"[{scope}] {finding.message}" if scope else finding.message
                    self.validation_tree.insert(
                        "", "end", values=(finding.severity, message),
                        tags=(finding.severity,),
                    )
        if self.extraction_result:
            for gap in self.extraction_result.information_gaps:
                self.validation_tree.insert(
                    "", "end", values=("information", gap.message), tags=("information",),
                )
        management_state = getattr(self, "management_state", None)
        if management_state:
            for conflict in management_state.conflicts:
                if conflict.resolution != management.CONFLICT_UNRESOLVED:
                    continue
                if record is not None and conflict.record_id != record.record_id:
                    continue
                self.validation_tree.insert(
                    "", "end",
                    values=(
                        "warning",
                        self._tr(
                            f"Çözülmemiş kullanıcı/otomatik çakışması: {conflict.field_name}",
                            f"Unresolved manual/automatic conflict: {conflict.field_name}",
                        ),
                    ),
                    tags=("warning",),
                )

    def _selected_unresolved_conflicts(self) -> tuple[Any, ...]:
        record = self._selected_record()
        if record is None or self.management_state is None:
            return ()
        return tuple(sorted(
            (
                conflict for conflict in self.management_state.conflicts
                if conflict.record_id == record.record_id
                and conflict.resolution == management.CONFLICT_UNRESOLVED
            ),
            key=lambda conflict: conflict.conflict_id,
        ))

    def _update_review_controls(self) -> None:
        if not hasattr(self, "approve_button"):
            return
        records = self._selected_records()
        record = records[0] if records else None
        single_disabled = (
            self._working or record is None
            or record.status == management.STATUS_SUPERSEDED
        )
        single_state = tk.DISABLED if single_disabled else tk.NORMAL
        # Onay yalnız gerçekten onaylanabilir bir kayıt seçiliyken açılır; stale
        # kayda tıklayan kullanıcı engel uyarısıyla karşılaşmaz.
        approvable = any(
            item.status in ACTIONABLE_RECORD_STATUSES for item in records
        )
        self.approve_button.configure(
            state=tk.DISABLED if (self._working or not approvable) else tk.NORMAL
        )
        self.edit_button.configure(state=single_state)
        self.reject_button.configure(state=single_state)
        if hasattr(self, "select_all_button"):
            self.select_all_button.configure(
                state=tk.DISABLED if self._working else tk.NORMAL
            )
        if hasattr(self, "conflict_button"):
            conflict_state = (
                tk.NORMAL
                if not self._working and self._selected_unresolved_conflicts()
                else tk.DISABLED
            )
            self.conflict_button.configure(state=conflict_state)

    def _persist_review_state(self) -> bool:
        state = self.management_state
        if state is None:
            return False
        management.save_profile_management_state(state)
        return True

    def _capture_review_guard(self, record_id: str) -> tuple[Any, ...]:
        """Capture the source generation and exact review-state revision."""

        state = self.management_state
        return (
            self._source_change_token,
            self._state_revision,
            self._active_project_name,
            getattr(state, "framework_profile_id", ""),
            record_id,
            state,
        )

    def _review_guard_is_current(self, guard: tuple[Any, ...]) -> bool:
        source_token, revision, project_name, profile_id, record_id, state = guard
        if (
            self._closed
            or self.management_state is not state
            or self._source_change_token != source_token
            or self._state_revision != revision
            or self._active_project_name != project_name
            or getattr(state, "framework_profile_id", "") != profile_id
            or getattr(self, "_source_revision_blocked", False)
            or getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        ):
            return False
        records = getattr(state, "records", None)
        return not isinstance(records, Mapping) or not record_id or record_id in records

    def _report_stale_review_block(self) -> None:
        self.status_var.set(self._tr(
            "Kaynak veya inceleme durumu değişti; eski iletişim kutusu kararı uygulanmadı.",
            "Source or review state changed; the stale dialog decision was not applied.",
        ))

    def _review_transaction(
        self,
        mutation: Callable[[Any], None],
        *,
        expected_guard: tuple[Any, ...] | None = None,
    ) -> None:
        """Persist a review mutation only if its state revision still matches."""

        state = self.management_state
        if state is None:
            raise management.ArchitectureManagementError("İnceleme durumu yok.")
        guard = expected_guard or self._capture_review_guard("")
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            raise management.ArchitectureManagementError(
                "Kaynak veya inceleme durumu değişti; karar uygulanmadı."
            )
        working = management.ArchitectureManagementState.from_dict(
            deepcopy(state.to_dict())
        )
        mutation(working)
        profile_id = working.framework_profile_id
        with self._state_write_lock:
            if not self._review_guard_is_current(guard):
                self._report_stale_review_block()
                raise management.ArchitectureManagementError(
                    "Kaynak veya inceleme durumu değişti; karar uygulanmadı."
                )
            management.save_profile_management_state(working)
        # A source notification may arrive from another thread during the
        # atomic save. Its worker will write after us, but this stale object must
        # never be restored to the live UI state.
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            raise management.ArchitectureManagementError(
                "Kaynak veya inceleme durumu değişti; karar uygulanmadı."
            )
        self.management_state = working
        self._states_by_profile[profile_id] = working
        self._state_revision += 1

    def _element_record_index(
        self, state: management.ArchitectureManagementState,
    ) -> dict[str, str]:
        """Kanonik öğe kimliğinden yönetim kaydına eşleme kurar."""

        index: dict[str, str] = {}
        for record_id, record in state.records.items():
            if record.proposal.proposal_type != "element":
                continue
            index.setdefault(self._proposal_stable_id(record.proposal), record_id)
        return index

    def _endpoint_closure(
        self,
        state: management.ArchitectureManagementState,
        selected_ids: Sequence[str],
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Onay kümesini ilişki uçlarıyla tamamlar.

        Onaylı bir ilişkinin ucu onaysızsa ``build_working_snapshot`` her
        görünümde hata verir. Bu kapanış, onaylanabilir uçları kümeye ekler ve
        onaylanamayan (stale/eksik) uca sahip ilişkileri ayrıca döndürür.
        """

        index = self._element_record_index(state)
        required = set(selected_ids)
        unfixable: set[str] = set()
        changed = True
        while changed:
            changed = False
            for record_id, record in state.records.items():
                proposal = record.proposal
                if proposal.proposal_type != "relationship":
                    continue
                if record_id not in required and record.status != management.STATUS_APPROVED:
                    continue
                for endpoint in (proposal.source_element_id, proposal.target_element_id):
                    if not endpoint:
                        continue
                    endpoint_record_id = index.get(endpoint)
                    endpoint_record = (
                        state.records.get(endpoint_record_id) if endpoint_record_id else None
                    )
                    if endpoint_record is None:
                        unfixable.add(record_id)
                        continue
                    if endpoint_record.status == management.STATUS_APPROVED:
                        continue
                    if endpoint_record.status not in ACTIONABLE_RECORD_STATUSES:
                        unfixable.add(record_id)
                        continue
                    if endpoint_record_id not in required:
                        required.add(endpoint_record_id)
                        changed = True
        return frozenset(required), frozenset(unfixable - required)

    def _approve_selected(self) -> None:
        if not self._ensure_current_project_context():
            return
        state = self.management_state
        records = self._selected_records()
        if not state or not records:
            return
        reviewable = tuple(
            record for record in records
            if record.status in ACTIONABLE_RECORD_STATUSES
        )
        skipped = len(records) - len(reviewable)
        if not reviewable:
            messagebox.showinfo(
                self._tr("Onay Engeli", "Approval Blocked"),
                self._tr(
                    "Seçilen kayıtların hepsi stale veya superseded. Bunlar güncel "
                    "kaynakla yeniden çıkarılmadan onaylanamaz.",
                    "Every selected record is stale or superseded. These cannot be "
                    "approved without re-extraction from the current source.",
                ),
                parent=self.window,
            )
            return

        selected_ids = [record.record_id for record in reviewable]
        required, unfixable = self._endpoint_closure(state, selected_ids)
        added = required - set(selected_ids)
        reject_ids: tuple[str, ...] = ()
        if unfixable:
            titles = ", ".join(sorted(
                state.records[item].proposal.title for item in tuple(unfixable)[:5]
            ))
            answer = messagebox.askyesno(
                self._tr("Boşta kalan ilişki", "Dangling relationship"),
                self._tr(
                    f"{len(unfixable)} ilişkinin ucu onaylanamaz durumda (stale veya eksik): "
                    f"{titles}\n\nBunlar onaylı kaldığı sürece hiçbir görünüm üretilemez.\n"
                    "Bu ilişkileri reddedip devam edeyim mi?",
                    f"{len(unfixable)} relationship(s) have endpoints that cannot be approved "
                    f"(stale or missing): {titles}\n\nWhile they stay approved no view can be "
                    "generated.\nShould I reject them and continue?",
                ),
                parent=self.window,
            )
            if not answer:
                return
            reject_ids = tuple(sorted(unfixable))

        if added:
            if not messagebox.askyesno(
                self._tr("Uçları da onayla", "Approve endpoints too"),
                self._tr(
                    f"Seçtiğin {len(selected_ids)} kaydın yanına, ilişkilerin uçları olan "
                    f"{len(added)} öğe daha eklenecek. Uçlar onaysız kalırsa şema üretilemez.\n\n"
                    "Devam edilsin mi?",
                    f"{len(added)} more element(s) — the endpoints of the selected relationships — "
                    f"will be approved alongside your {len(selected_ids)} record(s). Views cannot "
                    "be generated while endpoints stay unapproved.\n\nContinue?",
                ),
                parent=self.window,
            ):
                return

        guard = self._capture_review_guard("")
        actor = self._tr("UI Kullanıcısı", "UI User")
        rationale = self._tr(
            "Mimari Stüdyo açık kullanıcı onayı",
            "Explicit Architecture Studio user approval",
        )
        endpoint_rationale = self._tr(
            "İlişki ucu olarak açık kullanıcı onayıyla birlikte onaylandı",
            "Approved together with its relationship by explicit user decision",
        )

        def mutation(working: management.ArchitectureManagementState) -> None:
            for record_id in reject_ids:
                management.reject_candidate(
                    working, record_id, actor,
                    rationale=self._tr(
                        "Ucu onaylanamayan ilişki kullanıcı onayıyla reddedildi",
                        "Relationship with unapprovable endpoint rejected by user decision",
                    ),
                )
            # Öğeler ilişkilerden önce onaylanır; ara durumda boşta uç kalmaz.
            ordered = sorted(required, key=lambda item: (
                working.records[item].proposal.proposal_type != "element", item,
            ))
            for record_id in ordered:
                if working.records[record_id].status == management.STATUS_APPROVED:
                    continue
                management.approve_candidate(
                    working, record_id, actor,
                    rationale=(rationale if record_id in set(selected_ids)
                               else endpoint_rationale),
                )

        try:
            self._review_transaction(mutation, expected_guard=guard)
        except Exception as error:
            messagebox.showerror(
                self._tr("Onay Engeli", "Approval Blocked"), str(error), parent=self.window,
            )
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree(); self._refresh_view_cards()
        parts = [self._tr(f"{len(required)} aday onaylandı", f"{len(required)} candidate(s) approved")]
        if added:
            parts.append(self._tr(f"{len(added)} uç eklendi", f"{len(added)} endpoint(s) added"))
        if reject_ids:
            parts.append(self._tr(f"{len(reject_ids)} boşta ilişki reddedildi",
                                  f"{len(reject_ids)} dangling relationship(s) rejected"))
        if skipped:
            parts.append(self._tr(f"{skipped} stale kayıt atlandı", f"{skipped} stale record(s) skipped"))
        self.status_var.set(" · ".join(parts))

    def _reject_selected(self) -> None:
        if not self._ensure_current_project_context():
            return
        record = self._selected_record()
        if not record or not self.management_state:
            return
        guard = self._capture_review_guard(record.record_id)
        reason = simpledialog.askstring(
            self._tr("Reddetme gerekçesi", "Rejection rationale"),
            self._tr("Aday neden reddediliyor?", "Why is this candidate rejected?"),
            parent=self.window,
        )
        if reason is None:
            return
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            return
        try:
            self._review_transaction(lambda state: management.reject_candidate(
                state, record.record_id, self._tr("UI Kullanıcısı", "UI User"),
                rationale=reason,
            ), expected_guard=guard)
        except Exception as error:
            messagebox.showerror(self._tr("İnceleme Engeli", "Review Blocked"), str(error), parent=self.window)
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree(); self._refresh_view_cards()

    def _edit_selected(self) -> None:
        if not self._ensure_current_project_context():
            return
        record = self._selected_record()
        if not record or not self.management_state:
            return
        guard = self._capture_review_guard(record.record_id)
        payload = dict(record.proposal.proposed_payload)
        edited = simpledialog.askstring(
            self._tr("Aday açıklamasını düzenle", "Edit candidate description"),
            self._tr("Açıklama", "Description"),
            initialvalue=str(payload.get("description", "")), parent=self.window,
        )
        if edited is None:
            return
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            return
        payload["description"] = edited
        try:
            self._review_transaction(lambda state: management.edit_candidate(
                state, record.record_id, payload,
                self._tr("UI Kullanıcısı", "UI User"),
                rationale=self._tr("Mimari Stüdyo kullanıcı düzenlemesi", "Architecture Studio user edit"),
            ), expected_guard=guard)
        except Exception as error:
            messagebox.showerror(self._tr("Düzenleme Engeli", "Edit Blocked"), str(error), parent=self.window)
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree(); self._refresh_view_cards()

    def _resolve_selected_conflict(self) -> None:
        if not self._ensure_current_project_context():
            return
        conflicts = self._selected_unresolved_conflicts()
        if not conflicts or self.management_state is None:
            return
        conflict = conflicts[0]
        guard = self._capture_review_guard(conflict.record_id)
        keep_manual = messagebox.askyesnocancel(
            self._tr("Çakışmayı çöz", "Resolve conflict"),
            self._tr(
                "Evet: kullanıcı değerini koru\nHayır: yeni otomatik değeri kullan\n"
                f"Alan: {conflict.field_name}",
                "Yes: keep the user value\nNo: use the new automatic value\n"
                f"Field: {conflict.field_name}",
            ),
            parent=self.window,
        )
        if keep_manual is None:
            return
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            return
        resolution = (
            management.CONFLICT_KEEP_MANUAL
            if keep_manual else management.CONFLICT_USE_AUTOMATIC
        )
        try:
            self._review_transaction(lambda state: management.resolve_conflict(
                state,
                conflict.conflict_id,
                resolution,
                self._tr("UI Kullanıcısı", "UI User"),
            ), expected_guard=guard)
        except Exception as error:
            messagebox.showerror(
                self._tr("Çakışma Çözüm Engeli", "Conflict Resolution Blocked"),
                str(error), parent=self.window,
            )
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree()
        self._refresh_view_cards()
        self.status_var.set(self._tr(
            "Çakışma kullanıcı kararıyla çözüldü.",
            "Conflict resolved by explicit user decision.",
        ))

    def _build_snapshot(self, view_ids: Sequence[str]) -> ArchitectureSnapshot:
        if self.management_state is None:
            raise management.ArchitectureManagementError(
                self._tr("Önce mimari adayları çıkarın ve gözden geçirin.",
                         "Extract and review architecture candidates first.")
            )
        return management.build_working_snapshot(
            self.management_state, tuple(view_ids), version="v0001",
        )

    def _start_render(self) -> None:
        if self._working or not self._ensure_current_project_context():
            return
        if not self._ensure_sources_ready():
            return
        if self.management_state is None:
            self.status_var.set(self._tr(
                "Önce mimari adayları çıkarın ve gözden geçirin.",
                "Extract and review architecture candidates first.",
            ))
            return
        view_id = self.view_var.get()
        self._render_token += 1
        token = self._render_token
        state = self.management_state
        preview_size = (
            max(self.preview_canvas.winfo_width() - 20, 320),
            max(self.preview_canvas.winfo_height() - 20, 220),
        )
        self._busy(True, self._tr("Görünüm arka planda üretiliyor…", "Generating view in background…"))
        try:
            worker = threading.Thread(
                target=self._render_worker,
                args=(token, state, view_id, preview_size),
                daemon=True, name="architecture-svg-render",
            )
            worker.start()
        except Exception as error:
            self._render_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Görünüm worker'ı başlatılamadı: {error}",
                f"View worker could not be started: {error}",
            ))

    @staticmethod
    def _rasterize_svg_preview(svg: str, preview_size: tuple[int, int]) -> Any:
        """SVG rasterizasyonunu Tk'den bağımsız worker bağlamında tamamlar."""

        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # type: ignore[no-redef]
        from PIL import Image

        # PyMuPDF gömülü <style> bloğunu uygulamaz; CSS inline edilmezse her
        # öğe varsayılan siyahla çizilir ve önizleme siyah bir dikdörtgen olur.
        # Kanonik SVG değişmez, yalnız bu kopya dönüştürülür.
        document = fitz.open(
            stream=rendering.svg_with_inline_styles(svg).encode("utf-8"),
            filetype="svg",
        )
        try:
            page = document[0]
            available_w, available_h = preview_size
            scale = min(
                available_w / max(page.rect.width, 1),
                available_h / max(page.rect.height, 1),
                2.0,
            )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            image.load()
            return image.copy()
        finally:
            document.close()

    def _render_worker(
        self,
        token: int,
        state: management.ArchitectureManagementState,
        view_id: str,
        preview_size: tuple[int, int],
    ) -> None:
        snapshot: ArchitectureSnapshot | None = None
        preview_image: Any | None = None
        preview_error = ""
        try:
            working_state = management.ArchitectureManagementState.from_dict(
                state.to_dict()
            )
            snapshot = management.build_working_snapshot(
                working_state, (view_id,), version="v0001",
            )
            result = rendering.render_view(snapshot, view_id)
            if result.status == rendering.RENDER_STATUS_RENDERED and result.svg:
                try:
                    preview_image = self._rasterize_svg_preview(
                        result.svg, preview_size,
                    )
                except Exception as raster_error:
                    preview_error = str(raster_error)
            error: Exception | None = None
        except Exception as caught:
            result = None; error = caught
        self._dispatch_after(lambda: self._finish_render(
            token, snapshot, view_id, result, preview_image, preview_error, error,
        ))

    def _finish_render(
        self,
        token: int,
        snapshot: ArchitectureSnapshot | None,
        view_id: str,
        result: rendering.ViewRenderResult | None,
        preview_image: Any | None,
        preview_error: str,
        error: Exception | None,
    ) -> None:
        if token != self._render_token or self._closed:
            return
        self._busy(False)
        if error is not None or result is None or snapshot is None:
            # Boşta uçlu onaylı ilişki her görünümü kilitler; ham hata yerine
            # kullanıcının uygulayabileceği çözümü göster.
            if "öğe ucu" in str(error):
                message = self._tr(
                    "Onaylı bir ilişkinin uçları onaysız; bu hâlde hiçbir görünüm "
                    "üretilemez. Adayları seçip 'Onayla'ya basın — uçlar otomatik "
                    "tamamlanır ya da düzeltilemeyen ilişki reddedilir.",
                    "An approved relationship has unapproved endpoints; no view can be "
                    "generated in this state. Select the candidates and press 'Approve' — "
                    "endpoints are completed automatically or the unfixable relationship "
                    "is rejected.",
                )
                self._clear_preview(message)
                self.status_var.set(message)
                return
            self.status_var.set(self._tr(f"Görünüm üretilemedi: {error}", f"View generation failed: {error}"))
            return
        if (
            snapshot.framework_profile_id != self.profile_var.get()
            or self.management_state is None
            or snapshot.project_id != self.management_state.project_id
            or view_id != self.view_var.get()
            or not self._project_context_matches()
        ):
            return
        self.current_snapshot = snapshot
        self.current_render_result = result
        key = (snapshot.framework_profile_id, view_id)
        self._render_results[key] = result
        if result.status == rendering.RENDER_STATUS_RENDERED and result.svg:
            if preview_image is not None:
                self._preview_images[key] = preview_image
            if preview_error:
                self._preview_errors[key] = preview_error
            self._display_svg(result.svg, preview_image, preview_error)
            self.status_var.set(self._tr(
                f"{view_id} deterministik SVG olarak üretildi.",
                f"{view_id} generated as deterministic SVG.",
            ))
            self._select_step("validate_export")
        else:
            self._clear_preview(self._tr(
                "Görünüm engellendi. Eksik girdiler:\n" + "\n".join(result.missing_inputs),
                "View blocked. Missing inputs:\n" + "\n".join(result.missing_inputs),
            ))
            self.status_var.set(self._tr("Görünüm eksik girdi nedeniyle engellendi.",
                                         "View blocked because inputs are missing."))
        self._refresh_view_cards()

    def _clear_preview(self, message: str) -> None:
        self._preview_photo = None
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            max(self.preview_canvas.winfo_width(), 300) // 2,
            max(self.preview_canvas.winfo_height(), 180) // 2,
            text=message, width=max(self.preview_canvas.winfo_width() - 60, 240),
            justify="center", tags=("placeholder",),
        )
        self._set_text(self.svg_text, message)

    def _display_svg(
        self,
        svg: str,
        preview_image: Any | None = None,
        preview_error: str = "",
    ) -> None:
        self._set_text(self.svg_text, svg)
        self.preview_canvas.delete("all")
        self._preview_photo = None
        if preview_image is not None:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(preview_image, master=self.window)
            except Exception as error:
                preview_error = str(error)
            else:
                self._preview_photo = photo
                self.preview_canvas.create_image(
                    max(self.preview_canvas.winfo_width(), preview_image.width) // 2,
                    max(self.preview_canvas.winfo_height(), preview_image.height) // 2,
                    image=photo, anchor="center",
                )
                return
        self.preview_canvas.create_text(
            max(self.preview_canvas.winfo_width(), 300) // 2,
            max(self.preview_canvas.winfo_height(), 180) // 2,
            text=self._tr(
                "SVG üretildi; raster önizleme bu ortamda belirsiz/eksik"
                + (f" ({preview_error})" if preview_error else "")
                + ".\nSVG sekmesi kullanılabilir.",
                "SVG generated; raster preview is unknown/unavailable in this environment"
                + (f" ({preview_error})" if preview_error else "")
                + ".\nUse the SVG tab.",
            ),
            width=max(self.preview_canvas.winfo_width() - 60, 240),
            justify="center",
        )

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
