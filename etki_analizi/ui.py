# -*- coding: utf-8 -*-
"""Etki Analizi çalışma alanının Tkinter arayüzü ve olay yönetimi."""

from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping

import etki_analizi_logic as logic
import etki_analizi_raporlama as reporting
import etki_analizi_simulasyon as simulation
import etki_analizi_simulasyon_ui as simulation_ui

SIMULATION_CANDIDATE_COLUMNS = (
    ("id", "Kimlik", "ID", 135, "w"),
    ("type", "Öğe türü", "Item type", 175, "w"),
    ("score", "Eşleşme", "Match", 80, "e"),
    ("title", "Başlık", "Title", 260, "w"),
)


PARAMETER_LEADING_COLUMNS = (
    ("name", "Parametre adı", "Parameter", 145, "w"),
    ("current", "Mevcut değer", "Current", 90, "e"),
)

PARAMETER_TRAILING_COLUMNS = (
    ("unit", "Birim", "Unit", 65, "center"),
    ("weight", "Önem ağırlığı", "Weight", 95, "e"),
    ("direction", "Değer yönü", "Direction", 125, "center"),
    ("minimum", "Minimum sınır", "Minimum", 90, "e"),
    ("maximum", "Maksimum sınır", "Maximum", 90, "e"),
    ("mandatory", "Zorunlu", "Mandatory", 70, "center"),
)

RESULT_COLUMNS = (
    ("alternative", "Alternatif", "Alternative", 210, "w"),
    ("score", "Toplam puan", "Total score", 100, "e"),
    ("status", "Durum", "Status", 120, "center"),
    ("note", "Karar notu", "Decision note", 390, "w"),
)

COMPARISON_COLUMNS = (
    ("alternative", "Alternatif", "Alternative", 120, "w"),
    ("parameter", "Parametre", "Parameter", 135, "w"),
    ("current", "Mevcut", "Current", 70, "e"),
    ("value", "Alternatif", "Alternative", 75, "e"),
    ("difference", "Fark", "Difference", 70, "e"),
    ("percent", "Fark %", "Diff. %", 70, "e"),
    ("unit", "Birim", "Unit", 55, "center"),
    ("weight", "Ağırlık %", "Weight %", 75, "e"),
    ("score", "Kriter puanı", "Score", 80, "e"),
    ("status", "Kriter durumu", "Criterion status", 175, "w"),
)


class ImpactAnalysisWorkspace:
    """Çok alternatifli etki analizi girdilerini ve sonuçlarını yönetir."""

    def __init__(
        self,
        master: tk.Misc,
        style: ttk.Style,
        language_getter: Callable[[], str],
        palette_getter: Callable[[], Mapping[str, str]],
        traceability_getter: Callable[[], Mapping[str, Any] | None] | None = None,
        on_close: Callable[[], None] | None = None,
        traceability_update_callback: Callable[[Mapping[str, Any]], None] | None = None,
        traceability_rescan_callback: Callable[[bool], None] | None = None,
        traceability_cancel_callback: Callable[[], None] | None = None,
        project_info_getter: Callable[[], Mapping[str, Any]] | None = None,
        change_apply_callback: Callable[[Any, Callable[[Any], None], Callable[[str], None]], None] | None = None,
        simulation_result_callback: Callable[[simulation.SimulationResult], None] | None = None,
        hardware_detail_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.master = master
        self.style = style
        self.language_getter = language_getter
        self.palette_getter = palette_getter
        self.traceability_getter = traceability_getter or (lambda: None)
        self.traceability_update_callback = traceability_update_callback
        self.traceability_rescan_callback = traceability_rescan_callback
        self.traceability_cancel_callback = traceability_cancel_callback
        self.project_info_getter = project_info_getter or (lambda: {})
        self.change_apply_callback = change_apply_callback
        self.simulation_result_callback = simulation_result_callback
        self.hardware_detail_callback = hardware_detail_callback
        self.on_close = on_close
        self.alternatives: list[str] = []
        self.parameters: list[dict[str, Any]] = []
        self.editing_index: int | None = None
        self.last_result: dict[str, Any] | None = None
        self.last_simulation_result: simulation.SimulationResult | None = None
        self.pending_simulation_request: simulation.ChangeRequest | None = None
        self.translatable: list[tuple[tk.Widget, str, str]] = []

        self.window = tk.Toplevel(master)
        self.window.geometry("1240x780")
        self.window.minsize(1040, 680)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.analysis_name = tk.StringVar()
        self.current_state = tk.StringVar()
        self.new_alternative = tk.StringVar()
        self.active_alternative = tk.StringVar()
        self.active_alternative_hint = tk.StringVar()
        self.parameter_mode_hint = tk.StringVar()
        self.parameter_table_status = tk.StringVar()
        self.parameter_vars = {
            key: tk.StringVar()
            for key in (
                "name", "current", "alternative", "unit", "weight",
                "direction", "minimum", "maximum",
            )
        }
        self.mandatory = tk.BooleanVar(value=False)
        self.winner_text = tk.StringVar()
        self.winner_hint = tk.StringVar()
        self.simulation_target = tk.StringVar()
        self.simulation_change_type = tk.StringVar(value=simulation.CHANGE_REQUIREMENT_TEXT)
        self.simulation_requested_by = tk.StringVar(value="Sistem Mühendisliği")
        self.simulation_use_lm = tk.BooleanVar(value=True)
        self.simulation_status = tk.StringVar(
            value="İzlenebilirlik haritası hazır olduğunda değişikliği simüle edebilirsiniz."
        )

        self._build()
        self.apply_theme()
        self.refresh_language()
        self.analysis_entry.focus_set()

    @property
    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        if self.exists:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def close(self) -> None:
        if self.exists:
            self.window.destroy()
        if self.on_close:
            self.on_close()

    def _tr(self, tr_text: str, en_text: str) -> str:
        return tr_text if self.language_getter() == "tr" else en_text

    def _label(self, parent: tk.Misc, tr: str, en: str, **kwargs: Any) -> ttk.Label:
        widget = ttk.Label(parent, text=self._tr(tr, en), **kwargs)
        self.translatable.append((widget, tr, en))
        return widget

    def _button(self, parent: tk.Misc, tr: str, en: str, **kwargs: Any) -> ttk.Button:
        widget = ttk.Button(parent, text=self._tr(tr, en), **kwargs)
        self.translatable.append((widget, tr, en))
        return widget

    def _build(self) -> None:
        root = ttk.Frame(self.window, style="ImpactRoot.TFrame", padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, style="ImpactRoot.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        titles = ttk.Frame(header, style="ImpactRoot.TFrame")
        titles.grid(row=0, column=0, sticky="w")
        self._label(
            titles, "Etki Analizi", "Impact Analysis",
            style="ImpactTitle.TLabel",
        ).pack(anchor="w")
        self._label(
            titles,
            "Parça alternatiflerini karşılaştırın veya gereksinim değişikliğini V-Model boyunca simüle edin.",
            "Compare part alternatives or simulate a requirement change across the V-Model.",
            style="ImpactMuted.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self._label(
            header,
            "KANIT  →  ETKİ YOLU  →  MÜHENDİSLİK KARARI",
            "EVIDENCE  →  IMPACT PATH  →  ENGINEERING DECISION",
            style="ImpactTrace.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(20, 0))
        self.hardware_trace_frame = ttk.Frame(
            header, style="ImpactPanel.TFrame", padding=(6, 3),
            borderwidth=1, relief="solid",
        )
        self.hardware_trace_vars: list[tk.StringVar] = []
        for index, label in enumerate(("Üst Sistem", "Parça", "Gereksinim", "Test", "Alternatif")):
            variable = tk.StringVar(value=label)
            self.hardware_trace_vars.append(variable)
            ttk.Label(
                self.hardware_trace_frame, textvariable=variable,
                style="ImpactTrace.TLabel", anchor="center",
            ).grid(row=0, column=index * 2, sticky="ew")
            self.hardware_trace_frame.columnconfigure(index * 2, weight=1)
            if index < 4:
                ttk.Label(
                    self.hardware_trace_frame, text="→", style="ImpactMuted.TLabel",
                ).grid(row=0, column=index * 2 + 1, padx=4)
        self.hardware_trace_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.hardware_trace_frame.grid_remove()

        self.mode_notebook = ttk.Notebook(root, style="Impact.TNotebook")
        self.mode_notebook.grid(row=1, column=0, sticky="nsew")
        self.manual_mode_tab = ttk.Frame(
            self.mode_notebook, style="ImpactRoot.TFrame", padding=(0, 8, 0, 0)
        )
        self.simulation_mode_tab = ttk.Frame(
            self.mode_notebook, style="ImpactRoot.TFrame", padding=(0, 8, 0, 0)
        )
        self.mode_notebook.add(self.manual_mode_tab, text="Parça/Durum Alternatifi")
        self.mode_notebook.add(
            self.simulation_mode_tab, text="Gereksinim Değişikliği Simülasyonu"
        )
        self.manual_mode_tab.columnconfigure(0, weight=1)
        self.manual_mode_tab.rowconfigure(0, weight=1)
        self.simulation_mode_tab.columnconfigure(0, weight=1)
        self.simulation_mode_tab.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(self.manual_mode_tab, style="Impact.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.input_tab = ttk.Frame(
            self.notebook, style="ImpactRoot.TFrame", padding=(0, 12, 0, 0)
        )
        self.result_tab = ttk.Frame(
            self.notebook, style="ImpactRoot.TFrame", padding=(0, 12, 0, 0)
        )
        self.notebook.add(self.input_tab, text="Analiz Girdileri")
        self.notebook.add(self.result_tab, text="Sonuçlar")
        self._build_input_tab()
        self._build_result_tab()
        self.simulation_panel = simulation_ui.RequirementSimulationPanel(
            self.simulation_mode_tab,
            style=self.style,
            language_getter=self.language_getter,
            palette_getter=self.palette_getter,
            traceability_getter=self.traceability_getter,
            traceability_update_callback=self.traceability_update_callback,
            rescan_callback=self.traceability_rescan_callback,
            cancel_trace_callback=self.traceability_cancel_callback,
            project_info_getter=self.project_info_getter,
            change_apply_callback=self.change_apply_callback,
            result_callback=self.simulation_result_callback,
            hardware_detail_callback=self.hardware_detail_callback,
        )
        self.mode_notebook.bind("<<NotebookTabChanged>>", self._mode_tab_changed)

    def _mode_tab_changed(self, _event: Any = None) -> None:
        """Gizliyken oluşturulan simülasyon formunun macOS'ta yeniden çizilmesini sağlar."""
        try:
            if self.mode_notebook.select() == str(self.simulation_mode_tab):
                self.window.after_idle(self.simulation_panel.ensure_visible)
        except (AttributeError, tk.TclError):
            return

    def _build_input_tab(self) -> None:
        self.input_tab.columnconfigure(1, weight=1)
        self.input_tab.rowconfigure(0, weight=1)

        left = ttk.Frame(
            self.input_tab, style="ImpactPanel.TFrame", padding=14,
            borderwidth=1, relief="solid", width=310,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(10, weight=1)
        self._label(
            left, "ANALİZ BAĞLAMI", "ANALYSIS CONTEXT",
            style="ImpactSection.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self._label(
            left, "Analiz adı", "Analysis name", style="ImpactField.TLabel"
        ).grid(row=1, column=0, sticky="w")
        self.analysis_entry = ttk.Entry(left, textvariable=self.analysis_name)
        self.analysis_entry.grid(row=2, column=0, sticky="ew", pady=(3, 10))
        self._label(
            left, "Mevcut parça veya durum", "Current part or state",
            style="ImpactField.TLabel",
        ).grid(row=3, column=0, sticky="w")
        ttk.Entry(left, textvariable=self.current_state).grid(
            row=4, column=0, sticky="ew", pady=(3, 10)
        )
        self._label(
            left, "Değişiklik nedeni", "Reason for change",
            style="ImpactField.TLabel",
        ).grid(row=5, column=0, sticky="w")
        self.reason_text = tk.Text(
            left, height=4, wrap="word", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=7, pady=6,
        )
        self.reason_text.grid(row=6, column=0, sticky="ew", pady=(3, 16))
        self._label(
            left, "ALTERNATİFLER", "ALTERNATIVES",
            style="ImpactSection.TLabel",
        ).grid(row=7, column=0, sticky="w", pady=(0, 8))

        add_row = ttk.Frame(left, style="ImpactPanel.TFrame")
        add_row.grid(row=8, column=0, sticky="ew", pady=(0, 8))
        add_row.columnconfigure(0, weight=1)
        alt_entry = ttk.Entry(add_row, textvariable=self.new_alternative)
        alt_entry.grid(row=0, column=0, sticky="ew")
        alt_entry.bind("<Return>", lambda _event: self._add_alternative())
        self._button(
            add_row, "Ekle", "Add", command=self._add_alternative,
            style="primary.Outline.TButton", width=7,
        ).grid(row=0, column=1, padx=(6, 0))

        self._label(
            left,
            "Alternatif adını yazıp Ekle düğmesine basın.",
            "Enter an alternative name and press Add.",
            style="ImpactGateHint.TLabel",
        ).grid(row=9, column=0, sticky="w", pady=(0, 7))

        list_frame = ttk.Frame(left, style="ImpactPanel.TFrame")
        list_frame.grid(row=10, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.alternative_list = tk.Listbox(
            list_frame, selectmode=tk.SINGLE, exportselection=False,
            activestyle="none", relief="solid", borderwidth=1,
            font=("Segoe UI", 9),
        )
        self.alternative_list.grid(row=0, column=0, sticky="nsew")
        self.alternative_list.bind(
            "<<ListboxSelect>>", self._activate_list_alternative
        )
        list_scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.alternative_list.yview
        )
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.alternative_list.configure(yscrollcommand=list_scroll.set)
        self._button(
            left, "Seçili Alternatifi Kaldır", "Remove Selected Alternative",
            command=self._remove_alternative, style="danger.Outline.TButton",
        ).grid(row=11, column=0, sticky="ew", pady=(8, 0))

        right = ttk.Frame(self.input_tab, style="ImpactRoot.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self._build_parameter_editor(right)
        self._build_parameter_table(right)

    def _build_parameter_editor(self, parent: ttk.Frame) -> None:
        active_bar = ttk.Frame(
            parent, style="ImpactGate.TFrame", padding=(10, 8),
            borderwidth=1, relief="solid",
        )
        active_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        active_bar.columnconfigure(1, weight=1)
        self._label(
            active_bar, "Düzenlenen alternatif:", "Alternative being edited:",
            style="ImpactGateLabel.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.active_combo = ttk.Combobox(
            active_bar, textvariable=self.active_alternative,
            state="disabled", width=28, style="Impact.TCombobox",
        )
        self.active_combo.grid(row=0, column=1, sticky="w")
        self.active_combo.bind(
            "<<ComboboxSelected>>", self._active_alternative_changed
        )
        ttk.Label(
            active_bar,
            textvariable=self.active_alternative_hint,
            style="ImpactGateHint.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        editor = ttk.Frame(
            parent, style="ImpactPanel.TFrame", padding=12,
            borderwidth=1, relief="solid",
        )
        editor.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            editor.columnconfigure(column, weight=1)
        definitions = (
            ("name", "Parametre adı", "Parameter name"),
            ("current", "Mevcut değer", "Current value"),
            ("alternative", "Alternatif değer", "Alternative value"),
            ("unit", "Birim", "Unit"),
            ("weight", "Önem ağırlığı", "Importance weight"),
            ("direction", "Değer yönü", "Value direction"),
            ("minimum", "Minimum kabul sınırı", "Minimum acceptance limit"),
            ("maximum", "Maksimum kabul sınırı", "Maximum acceptance limit"),
        )
        for index, (key, tr, en) in enumerate(definitions):
            row, column = (index // 4) * 2, index % 4
            self._label(editor, tr, en, style="ImpactField.TLabel").grid(
                row=row, column=column, sticky="w",
                padx=(0 if column == 0 else 8, 0),
            )
            if key == "direction":
                self.direction_combo = ttk.Combobox(
                    editor, textvariable=self.parameter_vars[key],
                    state="readonly", style="Impact.TCombobox",
                )
                widget = self.direction_combo
            else:
                widget = ttk.Entry(editor, textvariable=self.parameter_vars[key])
            widget.grid(
                row=row + 1, column=column, sticky="ew",
                padx=(0 if column == 0 else 8, 0), pady=(3, 10),
            )

        actions = ttk.Frame(editor, style="ImpactPanel.TFrame")
        actions.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        self.mandatory_check = ttk.Checkbutton(
            actions, variable=self.mandatory, style="TCheckbutton"
        )
        self.mandatory_check.pack(side="left")
        self.translatable.append(
            (self.mandatory_check, "Zorunlu kriter", "Mandatory criterion")
        )
        ttk.Label(
            actions,
            textvariable=self.parameter_mode_hint,
            style="ImpactMode.TLabel",
        ).pack(side="left", padx=(14, 0))
        self.parameter_save_button = ttk.Button(
            actions, command=self._save_parameter,
            style="primary.TButton", width=20,
        )
        self.parameter_save_button.pack(side="right")
        self._button(
            actions, "Yeni Parametre", "New Parameter",
            command=self._clear_parameter_form,
            style="primary.Outline.TButton", width=14,
        ).pack(side="right", padx=(0, 8))

    def _build_parameter_table(self, parent: ttk.Frame) -> None:
        heading = ttk.Frame(parent, style="ImpactRoot.TFrame")
        heading.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        heading.columnconfigure(0, weight=1)
        self._label(
            heading, "KARŞILAŞTIRMA PARAMETRELERİ", "COMPARISON PARAMETERS",
            style="ImpactSectionRoot.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            textvariable=self.parameter_table_status,
            style="ImpactMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        frame = ttk.Frame(
            parent, style="ImpactPanel.TFrame",
            borderwidth=1, relief="solid",
        )
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        definitions = self._parameter_table_columns()
        self.parameter_tree = ttk.Treeview(
            frame, columns=[item[0] for item in definitions],
            show="headings", style="Impact.Treeview", selectmode="browse",
        )
        self._configure_tree(self.parameter_tree, definitions)
        self.parameter_tree.grid(row=0, column=0, sticky="nsew")
        self.parameter_tree.bind(
            "<<TreeviewSelect>>", self._load_selected_parameter
        )
        vertical = ttk.Scrollbar(
            frame, orient="vertical", command=self.parameter_tree.yview
        )
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            frame, orient="horizontal", command=self.parameter_tree.xview
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.parameter_tree.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        actions = ttk.Frame(parent, style="ImpactRoot.TFrame")
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self._button(
            actions, "Seçili Parametreyi Sil", "Delete Selected Parameter",
            command=self._delete_parameter, style="danger.Outline.TButton",
        ).pack(side="left")
        self._button(
            actions, "Analizi Hesapla", "Calculate Analysis",
            command=self._calculate, style="primary.TButton", width=20,
        ).pack(side="right")

    def _parameter_table_columns(self) -> tuple:
        """Her alternatifi kendi adıyla ayrı bir karşılaştırma sütunu yapar."""
        alternative_columns = tuple(
            (
                f"alternative_{index}",
                alternative,
                alternative,
                max(110, min(210, 34 + len(alternative) * 7)),
                "e",
            )
            for index, alternative in enumerate(self.alternatives)
        )
        return (
            PARAMETER_LEADING_COLUMNS
            + alternative_columns
            + PARAMETER_TRAILING_COLUMNS
        )

    @staticmethod
    def _configure_tree(tree: ttk.Treeview, definitions: tuple) -> None:
        for key, tr, _en, width, anchor in definitions:
            tree.heading(key, text=tr)
            tree.column(
                key, width=width, minwidth=55, anchor=anchor,
                stretch=key in {"name", "parameter", "alternative", "note", "status"},
            )

    def _build_result_tab(self) -> None:
        self.result_tab.columnconfigure(0, weight=1)
        self.result_tab.rowconfigure(3, weight=1)
        winner = ttk.Frame(
            self.result_tab, style="ImpactWinner.TFrame", padding=(14, 10),
            borderwidth=1, relief="solid",
        )
        winner.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        winner.columnconfigure(1, weight=1)
        self._label(
            winner, "ÖNERİLEN KARAR", "RECOMMENDED DECISION",
            style="ImpactWinnerLabel.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Label(
            winner, textvariable=self.winner_text,
            style="ImpactWinnerValue.TLabel",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            winner, textvariable=self.winner_hint,
            style="ImpactWinnerHint.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        result_heading = ttk.Frame(
            self.result_tab, style="ImpactRoot.TFrame"
        )
        result_heading.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        result_heading.columnconfigure(0, weight=1)
        self._label(
            result_heading, "ALTERNATİF PUANLARI", "ALTERNATIVE SCORES",
            style="ImpactSectionRoot.TLabel",
        ).grid(row=0, column=0, sticky="w")
        export_actions = ttk.Frame(
            result_heading, style="ImpactRoot.TFrame"
        )
        export_actions.grid(row=0, column=1, sticky="e")
        self.pdf_export_button = self._button(
            export_actions, "PDF Raporu Kaydet", "Save PDF Report",
            command=lambda: self._save_report("pdf"),
            style="primary.Outline.TButton", width=18, state=tk.DISABLED,
        )
        self.pdf_export_button.pack(side="left")
        self.excel_export_button = self._button(
            export_actions, "Excel Raporu Kaydet", "Save Excel Report",
            command=lambda: self._save_report("excel"),
            style="primary.Outline.TButton", width=18, state=tk.DISABLED,
        )
        self.excel_export_button.pack(side="left", padx=(8, 0))

        result_frame = ttk.Frame(
            self.result_tab, style="ImpactPanel.TFrame",
            borderwidth=1, relief="solid", height=145,
        )
        result_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        result_frame.grid_propagate(False)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.result_tree = ttk.Treeview(
            result_frame, columns=[item[0] for item in RESULT_COLUMNS],
            show="headings", style="Impact.Treeview",
        )
        self._configure_tree(self.result_tree, RESULT_COLUMNS)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        result_scroll = ttk.Scrollbar(
            result_frame, orient="vertical", command=self.result_tree.yview
        )
        result_scroll.grid(row=0, column=1, sticky="ns")
        self.result_tree.configure(yscrollcommand=result_scroll.set)

        lower = ttk.Panedwindow(self.result_tab, orient="horizontal")
        lower.grid(row=3, column=0, sticky="nsew")
        comparison_panel = ttk.Frame(
            lower, style="ImpactPanel.TFrame",
            borderwidth=1, relief="solid",
        )
        comparison_panel.columnconfigure(0, weight=1)
        comparison_panel.rowconfigure(1, weight=1)
        lower.add(comparison_panel, weight=3)
        self._label(
            comparison_panel, "PARAMETRE BAZLI KARŞILAŞTIRMA",
            "PARAMETER COMPARISON", style="ImpactPanelHeading.TLabel",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        comparison_frame = ttk.Frame(
            comparison_panel, style="ImpactPanel.TFrame"
        )
        comparison_frame.grid(row=1, column=0, sticky="nsew")
        comparison_frame.columnconfigure(0, weight=1)
        comparison_frame.rowconfigure(0, weight=1)
        self.comparison_tree = ttk.Treeview(
            comparison_frame,
            columns=[item[0] for item in COMPARISON_COLUMNS],
            show="headings", style="Impact.Treeview",
        )
        self._configure_tree(self.comparison_tree, COMPARISON_COLUMNS)
        self.comparison_tree.grid(row=0, column=0, sticky="nsew")
        comparison_vertical = ttk.Scrollbar(
            comparison_frame, orient="vertical",
            command=self.comparison_tree.yview,
        )
        comparison_vertical.grid(row=0, column=1, sticky="ns")
        comparison_horizontal = ttk.Scrollbar(
            comparison_frame, orient="horizontal",
            command=self.comparison_tree.xview,
        )
        comparison_horizontal.grid(row=1, column=0, sticky="ew")
        self.comparison_tree.configure(
            yscrollcommand=comparison_vertical.set,
            xscrollcommand=comparison_horizontal.set,
        )

        explanation_panel = ttk.Frame(
            lower, style="ImpactPanel.TFrame", padding=12,
            borderwidth=1, relief="solid", width=330,
        )
        explanation_panel.columnconfigure(0, weight=1)
        explanation_panel.rowconfigure(1, weight=1)
        lower.add(explanation_panel, weight=1)
        self._label(
            explanation_panel, "HESAPLAMA AÇIKLAMASI",
            "CALCULATION EXPLANATION", style="ImpactPanelHeading.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.explanation_text = tk.Text(
            explanation_panel, wrap="word", state=tk.DISABLED,
            relief="flat", borderwidth=0, font=("Segoe UI", 9),
            padx=0, pady=0, cursor="arrow",
        )
        self.explanation_text.grid(row=1, column=0, sticky="nsew")

    def _build_simulation_tab(self) -> None:
        self.simulation_tab.columnconfigure(1, weight=1)
        self.simulation_tab.rowconfigure(0, weight=1)
        form = ttk.Frame(
            self.simulation_tab, style="ImpactPanel.TFrame", padding=14,
            borderwidth=1, relief="solid", width=390,
        )
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        form.grid_propagate(False)
        form.columnconfigure(0, weight=1)
        self._label(
            form, "DEĞİŞİKLİK İSTEĞİ", "CHANGE REQUEST",
            style="ImpactSection.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._label(
            form, "Değişiklik türü", "Change type", style="ImpactField.TLabel",
        ).grid(row=1, column=0, sticky="w")
        self.simulation_type_combo = ttk.Combobox(
            form, textvariable=self.simulation_change_type,
            values=simulation.SUPPORTED_CHANGE_TYPES, state="readonly",
            style="Impact.TCombobox",
        )
        self.simulation_type_combo.grid(row=2, column=0, sticky="ew", pady=(3, 7))
        self._label(
            form, "Gereksinim/öğe kimliği veya arama metni",
            "Requirement/item ID or search text", style="ImpactField.TLabel",
        ).grid(row=3, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.simulation_target).grid(
            row=4, column=0, sticky="ew", pady=(3, 7)
        )
        self._label(form, "Mevcut metin/değer", "Current text/value", style="ImpactField.TLabel").grid(
            row=5, column=0, sticky="w"
        )
        self.simulation_current_text = tk.Text(
            form, height=2, wrap="word", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=4,
        )
        self.simulation_current_text.grid(row=6, column=0, sticky="ew", pady=(3, 7))
        self._label(form, "Önerilen yeni metin/değer", "Proposed text/value", style="ImpactField.TLabel").grid(
            row=7, column=0, sticky="w"
        )
        self.simulation_proposed_text = tk.Text(
            form, height=2, wrap="word", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=4,
        )
        self.simulation_proposed_text.grid(row=8, column=0, sticky="ew", pady=(3, 7))
        self._label(form, "Değişiklik nedeni", "Reason for change", style="ImpactField.TLabel").grid(
            row=9, column=0, sticky="w"
        )
        self.simulation_reason_text = tk.Text(
            form, height=2, wrap="word", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=4,
        )
        self.simulation_reason_text.grid(row=10, column=0, sticky="ew", pady=(3, 7))
        self._label(form, "Değişikliği isteyen taraf", "Requested by", style="ImpactField.TLabel").grid(
            row=11, column=0, sticky="w"
        )
        ttk.Entry(form, textvariable=self.simulation_requested_by).grid(
            row=12, column=0, sticky="ew", pady=(3, 7)
        )
        self._label(form, "Varsayımlar (satır başına bir tane)", "Assumptions (one per line)", style="ImpactField.TLabel").grid(
            row=13, column=0, sticky="w"
        )
        self.simulation_assumptions_text = tk.Text(
            form, height=2, wrap="word", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=4,
        )
        self.simulation_assumptions_text.grid(row=14, column=0, sticky="ew", pady=(3, 7))
        options = ttk.Frame(form, style="ImpactPanel.TFrame")
        options.grid(row=15, column=0, sticky="ew", pady=(2, 7))
        self.simulation_lm_check = ttk.Checkbutton(
            options, variable=self.simulation_use_lm,
            text="LM Studio yorum ve mühendislik önerileri",
        )
        self.simulation_lm_check.pack(side="left")
        self.translatable.append((
            self.simulation_lm_check,
            "LM Studio yorum ve mühendislik önerileri",
            "LM Studio commentary and engineering suggestions",
        ))
        self.simulation_run_button = self._button(
            form, "Değişikliği Simüle Et", "Simulate Change",
            command=self._start_simulation, style="primary.TButton",
        )
        self.simulation_run_button.grid(row=16, column=0, sticky="ew")
        ttk.Label(
            form, textvariable=self.simulation_status,
            style="ImpactGateHint.TLabel", wraplength=350,
        ).grid(row=17, column=0, sticky="ew", pady=(7, 0))

        right = ttk.Frame(self.simulation_tab, style="ImpactRoot.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self._label(
            right, "EŞLEŞME ADAYLARI", "MATCH CANDIDATES",
            style="ImpactSectionRoot.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        candidate_frame = ttk.Frame(
            right, style="ImpactPanel.TFrame", borderwidth=1, relief="solid", height=145,
        )
        candidate_frame.grid(row=1, column=0, sticky="ew")
        candidate_frame.grid_propagate(False)
        candidate_frame.columnconfigure(0, weight=1)
        candidate_frame.rowconfigure(0, weight=1)
        self.simulation_candidate_tree = ttk.Treeview(
            candidate_frame,
            columns=[item[0] for item in SIMULATION_CANDIDATE_COLUMNS],
            show="headings", style="Impact.Treeview", selectmode="browse",
        )
        self._configure_tree(self.simulation_candidate_tree, SIMULATION_CANDIDATE_COLUMNS)
        self.simulation_candidate_tree.grid(row=0, column=0, sticky="nsew")
        self.simulation_candidate_tree.bind(
            "<Double-1>", lambda _event: self._select_simulation_candidate()
        )
        candidate_scroll = ttk.Scrollbar(
            candidate_frame, orient="vertical", command=self.simulation_candidate_tree.yview,
        )
        candidate_scroll.grid(row=0, column=1, sticky="ns")
        self.simulation_candidate_tree.configure(yscrollcommand=candidate_scroll.set)
        self.simulation_select_button = self._button(
            right, "Seçili Adayla Devam Et", "Continue with Selected Candidate",
            command=self._select_simulation_candidate,
            style="primary.Outline.TButton", state=tk.DISABLED,
        )
        self.simulation_select_button.grid(row=2, column=0, sticky="e", pady=(6, 8))
        result_frame = ttk.Frame(
            right, style="ImpactPanel.TFrame", borderwidth=1, relief="solid",
        )
        result_frame.grid(row=3, column=0, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(1, weight=1)
        self._label(
            result_frame, "KANITA DAYALI SİMÜLASYON SONUCU", "EVIDENCE-BASED SIMULATION RESULT",
            style="ImpactPanelHeading.TLabel",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 5))
        self.simulation_result_text = tk.Text(
            result_frame, wrap="word", state=tk.DISABLED, relief="flat",
            font=("Consolas", 9), padx=10, pady=8,
        )
        self.simulation_result_text.grid(row=1, column=0, sticky="nsew")
        result_scroll = ttk.Scrollbar(
            result_frame, orient="vertical", command=self.simulation_result_text.yview,
        )
        result_scroll.grid(row=1, column=1, sticky="ns")
        self.simulation_result_text.configure(yscrollcommand=result_scroll.set)

    def _start_simulation(self, selected_id: str | None = None) -> None:
        traceability = self.traceability_getter()
        if not traceability:
            self._warning(
                "İzlenebilirlik Haritası Bulunamadı",
                "Önce 'Dokümanları Üret' işlemini tamamlayın ve 'Etki analizi altyapısı hazır' mesajını bekleyin.",
            )
            return
        if selected_id and self.pending_simulation_request:
            request = self.pending_simulation_request
        else:
            target_text = self.simulation_target.get().strip()
            looks_like_id = bool(re.fullmatch(r"[A-Za-zÇĞİÖŞÜçğıöşü_-]+-?\d+", target_text))
            try:
                request = simulation.ChangeRequest(
                    requirement_id=target_text if looks_like_id else "",
                    query="" if looks_like_id else target_text,
                    current_value=self.simulation_current_text.get("1.0", tk.END).strip(),
                    proposed_value=self.simulation_proposed_text.get("1.0", tk.END).strip(),
                    reason=self.simulation_reason_text.get("1.0", tk.END).strip(),
                    requested_by=self.simulation_requested_by.get().strip(),
                    change_type=self.simulation_change_type.get(),
                    assumptions=tuple(
                        line.strip()
                        for line in self.simulation_assumptions_text.get("1.0", tk.END).splitlines()
                        if line.strip()
                    ),
                ).validated()
            except simulation.SimulationError as error:
                messagebox.showerror("Simülasyon Girdisi Hatası", str(error), parent=self.window)
                return
            self.pending_simulation_request = request
        self.simulation_run_button.configure(state=tk.DISABLED)
        self.simulation_select_button.configure(state=tk.DISABLED)
        self.simulation_status.set("İzlenebilirlik grafiği arka planda analiz ediliyor...")
        threading.Thread(
            target=self._simulation_worker,
            args=(traceability, request, selected_id, self.simulation_use_lm.get()),
            daemon=True,
        ).start()

    def _simulation_worker(
        self,
        traceability: Mapping[str, Any],
        request: simulation.ChangeRequest,
        selected_id: str | None,
        use_lm_studio: bool,
    ) -> None:
        try:
            result = simulation.simulate_change(
                traceability, request, selected_id=selected_id,
                use_lm_studio=use_lm_studio,
            )
        except Exception as error:
            self.window.after(0, lambda detail=str(error): self._simulation_failed(detail))
            return
        self.window.after(0, lambda value=result: self._simulation_finished(value))

    def _simulation_failed(self, detail: str) -> None:
        self.simulation_run_button.configure(state=tk.NORMAL)
        self.simulation_status.set("Simülasyon tamamlanamadı.")
        messagebox.showerror("Etki Simülasyonu Hatası", detail, parent=self.window)

    def _simulation_finished(self, result: simulation.SimulationResult) -> None:
        self.last_simulation_result = result
        self.simulation_run_button.configure(state=tk.NORMAL)
        self.simulation_candidate_tree.delete(*self.simulation_candidate_tree.get_children())
        for candidate in result.candidates[:5]:
            self.simulation_candidate_tree.insert(
                "", tk.END, iid=candidate["id"],
                values=(
                    candidate["id"], candidate["node_type"],
                    f"%{candidate['score'] * 100:.1f}", candidate["title"],
                ),
            )
        selection_needed = result.status == "selection_required"
        self.simulation_select_button.configure(
            state=tk.NORMAL if selection_needed else tk.DISABLED
        )
        self.simulation_status.set(result.message)
        self._render_simulation_result(result)

    def _select_simulation_candidate(self) -> None:
        selection = self.simulation_candidate_tree.selection()
        if not selection:
            self._warning("Aday Seçimi Gerekli", "Devam etmek istediğiniz gereksinimi seçin.")
            return
        self._start_simulation(selection[0])

    def _render_simulation_result(self, result: simulation.SimulationResult) -> None:
        lines = [result.message, ""]
        if result.selected_item:
            lines.extend((
                f"HEDEF: {result.selected_item.get('id')} — {result.selected_item.get('title')}",
                f"TÜR: {result.selected_item.get('node_type')}", "",
            ))
        if result.status == "selection_required":
            lines.append("Birden fazla eşleşme bulundu; yukarıdaki adaylardan birini seçin.")
        else:
            summary = result.summary
            lines.extend((
                "ÖZET",
                f"• Genel etki: {summary.get('overall_impact_level', '—')} ({summary.get('overall_impact_score', '—')}/100)",
                f"• Etki yolu: {summary.get('path_count', 0)}",
                f"• Etkilenen test: {summary.get('affected_test_count', 0)}",
                f"• Etkilenen belge: {summary.get('affected_document_count', 0)}",
                "", "ETKİ YOLLARI",
            ))
            for item in result.impacts:
                lines.append(
                    f"• [{item.impact_level} {item.impact_score}/100 | Risk {item.risk_score}/25 | "
                    f"{item.confidence_level}] {item.traceability_path.display_path}"
                )
                lines.append(f"  Kanıt: {item.source_evidence}")
            lines.extend(("", "RİSKLER"))
            for risk in result.risks:
                lines.append(
                    f"• {risk.category}: {risk.impact_level} — {risk.probability}×{risk.severity}={risk.risk_score}"
                )
            tests = result.categorized_impacts.get("new_or_updated_tests", [])
            lines.extend(("", "TEST EYLEMLERİ"))
            for test in tests:
                lines.append(f"• {test.get('test_id') or 'Yeni test'}: {test.get('status')} — {test.get('required_action')}")
            if result.engineering_suggestions:
                lines.extend(("", "MÜHENDİSLİK ÖNERİLERİ — KULLANICI ONAYI GEREKLİ"))
                for suggestion in result.engineering_suggestions:
                    lines.append(f"• {suggestion.category}: {suggestion.suggestion}")
                    lines.append(f"  Gerekçe: {suggestion.rationale}")
        if result.warnings:
            lines.extend(("", "UYARILAR"))
            lines.extend(f"• {warning}" for warning in result.warnings)
        lines.extend(("", "PUANLAMA", f"• {result.scoring_method.get('impact_score_formula', '')}"))
        self.simulation_result_text.configure(state=tk.NORMAL)
        self.simulation_result_text.delete("1.0", tk.END)
        self.simulation_result_text.insert("1.0", "\n".join(lines))
        self.simulation_result_text.configure(state=tk.DISABLED)

    def _direction_options(self) -> tuple[str, str]:
        return (
            self._tr("Yüksek daha iyi", "Higher is better"),
            self._tr("Düşük daha iyi", "Lower is better"),
        )

    def _canonical_direction(self, value: str) -> str:
        if value in {
            self._direction_options()[1], logic.DIRECTION_LOW,
            "Lower is better",
        }:
            return logic.DIRECTION_LOW
        return logic.DIRECTION_HIGH

    def _display_direction(self, value: str) -> str:
        return self._direction_options()[
            1 if self._canonical_direction(value) == logic.DIRECTION_LOW else 0
        ]

    def _add_alternative(self) -> None:
        name = " ".join(self.new_alternative.get().split())
        if not name:
            self._warning("Eksik Bilgi", "Alternatif adını girin.")
            return
        if name.casefold() in {item.casefold() for item in self.alternatives}:
            self._warning(
                "Tekrarlanan Alternatif",
                f"'{name}' alternatifi zaten eklenmiş.",
            )
            return
        self.alternatives.append(name)
        for parameter in self.parameters:
            parameter["alternative_values"][name] = ""
        self.new_alternative.set("")
        self.active_alternative.set(name)
        self._refresh_alternatives()
        self._refresh_parameter_table()

    def _remove_alternative(self) -> None:
        selection = self.alternative_list.curselection()
        if not selection:
            self._warning("Seçim Gerekli", "Kaldırılacak alternatifi seçin.")
            return
        index = int(selection[0])
        name = self.alternatives[index]
        if not messagebox.askyesno(
            "Alternatifi Kaldır",
            f"'{name}' ve bu alternatife ait değerler kaldırılacak. Devam edilsin mi?",
            parent=self.window,
        ):
            return
        self.alternatives.pop(index)
        for parameter in self.parameters:
            parameter["alternative_values"].pop(name, None)
        self.active_alternative.set(
            self.alternatives[min(index, len(self.alternatives) - 1)]
            if self.alternatives else ""
        )
        self._clear_parameter_form()
        self._refresh_alternatives()
        self._refresh_parameter_table()

    def _activate_list_alternative(self, _event: tk.Event) -> None:
        selection = self.alternative_list.curselection()
        if selection:
            self.active_alternative.set(
                self.alternatives[int(selection[0])]
            )
            self._active_alternative_changed()

    def _active_alternative_changed(
        self, _event: tk.Event | None = None
    ) -> None:
        name = self.active_alternative.get()
        if name in self.alternatives:
            index = self.alternatives.index(name)
            self.alternative_list.selection_clear(0, tk.END)
            self.alternative_list.selection_set(index)
            self.alternative_list.see(index)
        self._refresh_parameter_table()
        if self.editing_index is not None:
            self._load_parameter(self.editing_index)

    def _refresh_alternatives(self) -> None:
        active = self.active_alternative.get()
        self.alternative_list.delete(0, tk.END)
        for alternative in self.alternatives:
            self.alternative_list.insert(tk.END, alternative)
        has_alternatives = bool(self.alternatives)
        self.active_combo.configure(
            values=self.alternatives,
            state="readonly" if has_alternatives else "disabled",
        )
        if active not in self.alternatives:
            active = self.alternatives[0] if self.alternatives else ""
            self.active_alternative.set(active)
        if active:
            self.alternative_list.selection_set(
                self.alternatives.index(active)
            )
        self.active_alternative_hint.set(
            self._tr(
                "Alternatif değer sütunu bu seçime aittir."
                if has_alternatives
                else "Önce soldaki alana alternatif adı yazıp Ekle'ye basın.",
                "The alternative value column belongs to this selection."
                if has_alternatives
                else "Enter an alternative on the left and press Add first.",
            )
        )
        self.parameter_save_button.configure(
            state=tk.NORMAL if has_alternatives else tk.DISABLED
        )

    def _save_parameter(self) -> None:
        alternative = self.active_alternative.get()
        if not alternative:
            self._warning(
                "Alternatif Gerekli",
                "Parametre eklemeden önce en az bir alternatif ekleyin.",
            )
            return
        name = " ".join(self.parameter_vars["name"].get().split())
        if not name:
            self._warning("Eksik Bilgi", "Parametre adını girin.")
            return
        for index, item in enumerate(self.parameters):
            if (
                item["name"].casefold() == name.casefold()
                and index != self.editing_index
            ):
                self._warning(
                    "Tekrarlanan Parametre",
                    f"'{name}' parametresi zaten eklenmiş.",
                )
                return

        values = {
            "name": name,
            "current_value": self.parameter_vars["current"].get().strip(),
            "unit": self.parameter_vars["unit"].get().strip(),
            "weight": self.parameter_vars["weight"].get().strip(),
            "direction": self._canonical_direction(
                self.parameter_vars["direction"].get()
            ),
            "minimum": self.parameter_vars["minimum"].get().strip(),
            "maximum": self.parameter_vars["maximum"].get().strip(),
            "mandatory": self.mandatory.get(),
        }
        if self.editing_index is None:
            values["alternative_values"] = {
                item: "" for item in self.alternatives
            }
            values["alternative_values"][alternative] = (
                self.parameter_vars["alternative"].get().strip()
            )
            self.parameters.append(values)
        else:
            parameter = self.parameters[self.editing_index]
            parameter.update(values)
            parameter["alternative_values"][alternative] = (
                self.parameter_vars["alternative"].get().strip()
            )
        self._refresh_parameter_table()
        self._clear_parameter_form()

    def _delete_parameter(self) -> None:
        selection = self.parameter_tree.selection()
        if not selection:
            self._warning("Seçim Gerekli", "Silinecek parametreyi seçin.")
            return
        index = int(selection[0])
        name = self.parameters[index]["name"]
        if messagebox.askyesno(
            "Parametreyi Sil", f"'{name}' parametresi silinsin mi?",
            parent=self.window,
        ):
            self.parameters.pop(index)
            self._clear_parameter_form()
            self._refresh_parameter_table()

    def _load_selected_parameter(
        self, _event: tk.Event | None = None
    ) -> None:
        selection = self.parameter_tree.selection()
        if selection:
            self._load_parameter(int(selection[0]))

    def _load_parameter(self, index: int) -> None:
        if not 0 <= index < len(self.parameters):
            return
        item = self.parameters[index]
        self.editing_index = index
        self.parameter_vars["name"].set(item["name"])
        self.parameter_vars["current"].set(item["current_value"])
        self.parameter_vars["alternative"].set(
            item["alternative_values"].get(self.active_alternative.get(), "")
        )
        self.parameter_vars["unit"].set(item["unit"])
        self.parameter_vars["weight"].set(item["weight"])
        self.parameter_vars["direction"].set(
            self._display_direction(item["direction"])
        )
        self.parameter_vars["minimum"].set(item["minimum"])
        self.parameter_vars["maximum"].set(item["maximum"])
        self.mandatory.set(bool(item["mandatory"]))
        self._update_save_button()

    def _clear_parameter_form(self) -> None:
        self.editing_index = None
        for key, variable in self.parameter_vars.items():
            variable.set(
                self._direction_options()[0] if key == "direction" else ""
            )
        self.mandatory.set(False)
        selection = self.parameter_tree.selection()
        if selection:
            self.parameter_tree.selection_remove(*selection)
        self._update_save_button()

    def _update_save_button(self) -> None:
        editing = self.editing_index is not None
        edited_name = (
            self.parameters[self.editing_index]["name"]
            if editing and 0 <= self.editing_index < len(self.parameters)
            else ""
        )
        display_name = (
            edited_name if len(edited_name) <= 24
            else f"{edited_name[:21]}..."
        )
        self.parameter_save_button.configure(
            text=self._tr(
                "Parametreyi Güncelle" if editing else "Parametreyi Ekle",
                "Update Parameter" if editing else "Add Parameter",
            )
        )
        self.parameter_mode_hint.set(
            self._tr(
                f"DÜZENLE: {display_name}" if editing
                else "YENİ PARAMETRE GİRİŞİ",
                f"EDIT: {display_name}" if editing
                else "NEW PARAMETER ENTRY",
            )
        )

    def _refresh_parameter_table(self) -> None:
        selected = self.editing_index
        definitions = self._parameter_table_columns()
        columns = [item[0] for item in definitions]
        self.parameter_tree.configure(
            columns=columns,
            displaycolumns=columns,
        )
        for key, tr, en, width, anchor in definitions:
            self.parameter_tree.heading(key, text=self._tr(tr, en))
            self.parameter_tree.column(
                key,
                width=width,
                minwidth=55,
                anchor=anchor,
                stretch=key in {"name"},
            )
        self.parameter_tree.delete(*self.parameter_tree.get_children())
        for index, item in enumerate(self.parameters):
            values = [item["name"], item["current_value"] or "—"]
            values.extend(
                item["alternative_values"].get(alternative, "") or "—"
                for alternative in self.alternatives
            )
            values.extend((
                item["unit"] or "—",
                item["weight"] or "—",
                self._display_direction(item["direction"]),
                item["minimum"] or "—",
                item["maximum"] or "—",
                self._tr("Evet", "Yes") if item["mandatory"]
                else self._tr("Hayır", "No"),
            ))
            self.parameter_tree.insert(
                "", tk.END, iid=str(index),
                values=values,
            )
        if selected is not None and str(selected) in self.parameter_tree.get_children():
            self.parameter_tree.selection_set(str(selected))
        self.parameter_table_status.set(
            self._tr(
                f"{len(self.parameters)} parametre · "
                f"{len(self.alternatives)} alternatif",
                f"{len(self.parameters)} parameters · "
                f"{len(self.alternatives)} alternatives",
            )
        )

    def _warning(self, title: str, message: str) -> None:
        messagebox.showwarning(title, message, parent=self.window)

    def _update_export_buttons(self) -> None:
        state = tk.NORMAL if self.last_result else tk.DISABLED
        self.pdf_export_button.configure(state=state)
        self.excel_export_button.configure(state=state)

    @staticmethod
    def _safe_report_name(value: str) -> str:
        forbidden = '<>:"/\\|?*'
        cleaned = "".join(
            "_" if character in forbidden else character
            for character in str(value or "")
        )
        cleaned = "_".join(cleaned.split()).strip(" ._")
        return cleaned or "Etki_Analizi"

    def _save_report(self, report_format: str) -> None:
        if not self.last_result:
            self._update_export_buttons()
            self._warning(
                "Rapor Oluşturulamadı",
                "Rapor kaydetmeden önce Etki Analizini başarıyla hesaplayın.",
            )
            return

        is_pdf = report_format == "pdf"
        extension = ".pdf" if is_pdf else ".xlsx"
        filetypes = (
            [("PDF Raporu", "*.pdf")]
            if is_pdf
            else [("Excel Raporu", "*.xlsx")]
        )
        analysis_name = self._safe_report_name(
            self.last_result.get("analysis_name", "Etki_Analizi")
        )
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title=(
                "PDF Raporunu Kaydet"
                if is_pdf
                else "Excel Raporunu Kaydet"
            ),
            defaultextension=extension,
            initialfile=f"{analysis_name}_Etki_Analizi_Raporu{extension}",
            filetypes=filetypes + [("Tüm Dosyalar", "*.*")],
        )
        if not path:
            return

        try:
            if is_pdf:
                export_result = reporting.export_impact_analysis_pdf(
                    path, self.last_result
                )
            else:
                export_result = reporting.export_impact_analysis_excel(
                    path, self.last_result
                )
        except PermissionError:
            messagebox.showerror(
                "Rapor Kaydetme Hatası",
                "Dosyaya yazılamadı. Dosya başka bir programda açık olabilir. "
                "Dosyayı kapatıp yeniden deneyin.",
                parent=self.window,
            )
            return
        except OSError as error:
            locked = (
                getattr(error, "errno", None) in {13, 16, 26}
                or getattr(error, "winerror", None) in {32, 33}
            )
            message = (
                "Dosyaya yazılamadı. Dosya başka bir programda açık olabilir. "
                "Dosyayı kapatıp yeniden deneyin."
                if locked
                else f"Rapor dosyası kaydedilemedi: {error}"
            )
            messagebox.showerror(
                "Rapor Kaydetme Hatası", message, parent=self.window
            )
            return
        except (TypeError, ValueError) as error:
            messagebox.showerror(
                "Raporlama Hatası", str(error), parent=self.window
            )
            return
        except Exception as error:
            messagebox.showerror(
                "Raporlama Hatası",
                f"Rapor oluşturulurken beklenmeyen bir hata oluştu: {error}",
                parent=self.window,
            )
            return

        messagebox.showinfo(
            "Rapor Kaydedildi",
            f"Rapor başarıyla kaydedildi:\n{export_result['path']}",
            parent=self.window,
        )

    def _calculate(self) -> None:
        payload = {
            "analysis_name": self.analysis_name.get(),
            "current_state": self.current_state.get(),
            "change_reason": self.reason_text.get("1.0", tk.END).strip(),
            "alternatives": list(self.alternatives),
            "parameters": [
                {
                    **item,
                    "alternative_values": dict(item["alternative_values"]),
                }
                for item in self.parameters
            ],
        }
        try:
            self.last_result = logic.calculate_impact_analysis(payload)
        except logic.EtkiAnaliziHatasi as error:
            messagebox.showerror(
                "Etki Analizi Hatası", str(error), parent=self.window
            )
            return
        except Exception as error:
            messagebox.showerror(
                "Beklenmeyen Hata",
                f"Etki analizi hesaplanamadı: {error}",
                parent=self.window,
            )
            return
        self._render_result()
        self.notebook.select(self.result_tab)

    @staticmethod
    def _number(value: Any, suffix: str = "") -> str:
        if value is None:
            return "—"
        text = f"{float(value):.2f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}"

    def _status(self, value: str) -> str:
        translations = {
            logic.STATUS_SUITABLE: ("Uygun", "Suitable"),
            logic.STATUS_UNSUITABLE: ("Uygun değil", "Unsuitable"),
            logic.STATUS_MISSING: ("Veri eksik", "Missing data"),
            "Zorunlu kriter sağlanmadı": (
                "Zorunlu kriter sağlanmadı", "Mandatory criterion failed"
            ),
            "Kabul sınırı dışında": (
                "Kabul sınırı dışında", "Outside acceptance limits"
            ),
        }
        tr, en = translations.get(value, (value, value))
        return self._tr(tr, en)

    def _render_result(self) -> None:
        result = self.last_result
        if not result:
            return
        self.result_tree.delete(*self.result_tree.get_children())
        self.comparison_tree.delete(*self.comparison_tree.get_children())
        for alt_index, alternative in enumerate(result["alternatives"]):
            status = alternative["status"]
            if status == logic.STATUS_SUITABLE:
                tag = "suitable"
                note = self._tr(
                    "Tüm veriler tamam; zorunlu kriterler sağlandı.",
                    "All data is complete; mandatory criteria passed.",
                )
            elif status == logic.STATUS_UNSUITABLE:
                tag = "unsuitable"
                note = self._tr(
                    "En az bir zorunlu kriter kabul sınırının dışında.",
                    "At least one mandatory criterion is outside its limits.",
                )
            else:
                tag = "missing"
                note = self._tr(
                    "Eksik değerler tamamlanmadan toplam puan hesaplanmaz.",
                    "The total score is withheld until missing values are completed.",
                )
            self.result_tree.insert(
                "", tk.END, iid=f"alternative-{alt_index}",
                values=(
                    alternative["alternative_name"],
                    self._number(alternative["total_score"]),
                    self._status(status), note,
                ),
                tags=(tag,),
            )
            for criterion_index, criterion in enumerate(
                alternative["criteria"]
            ):
                criterion_status = criterion["status"]
                if criterion_status == logic.STATUS_MISSING:
                    criterion_tag = "missing"
                elif criterion_status in {
                    "Zorunlu kriter sağlanmadı", "Kabul sınırı dışında"
                }:
                    criterion_tag = "unsuitable"
                else:
                    criterion_tag = "suitable"
                self.comparison_tree.insert(
                    "", tk.END,
                    iid=f"criterion-{alt_index}-{criterion_index}",
                    values=(
                        alternative["alternative_name"],
                        criterion["parameter_name"],
                        self._number(criterion["current_value"]),
                        self._number(criterion["alternative_value"]),
                        self._number(criterion["difference"]),
                        self._number(criterion["difference_percent"], "%"),
                        criterion["unit"] or "—",
                        self._number(criterion["normalized_weight"], "%"),
                        self._number(criterion["criterion_score"]),
                        self._status(criterion_status),
                    ),
                    tags=(criterion_tag,),
                )

        best = result["best_alternative"]
        if best:
            self.winner_text.set(
                f"{best['alternative_name']}  ·  "
                f"{self._number(best['total_score'])}/100"
            )
            self.winner_hint.set(
                self._tr(
                    "En yüksek puanlı uygun alternatif",
                    "Highest-scoring suitable alternative",
                )
            )
        else:
            self.winner_text.set(
                self._tr(
                    "Uygun alternatif belirlenemedi",
                    "No suitable alternative identified",
                )
            )
            self.winner_hint.set(
                self._tr(
                    "Eksik verileri veya zorunlu kriterleri kontrol edin",
                    "Check missing data or mandatory criteria",
                )
            )

        lines = [
            self._tr("Analiz", "Analysis") + f": {result['analysis_name']}",
            self._tr("Mevcut durum", "Current state")
            + f": {result['current_state']}",
            "",
            self._tr("Normalize ağırlıklar:", "Normalized weights:"),
        ]
        lines.extend(
            f"• {name}: {self._number(weight, '%')}"
            for name, weight in result["normalized_weights"].items()
        )
        lines.extend(["", self._tr("Yöntem:", "Method:")])
        lines.extend(
            f"• {text}" for text in result["calculation_explanation"]
        )
        self.explanation_text.configure(state=tk.NORMAL)
        self.explanation_text.delete("1.0", tk.END)
        self.explanation_text.insert("1.0", "\n".join(lines))
        self.explanation_text.configure(state=tk.DISABLED)
        self._update_export_buttons()

    def _update_hardware_trace(self, payload: Mapping[str, Any]) -> None:
        context = dict(payload.get("hardware_context") or {})
        labels = (
            f"Üst Sistem  {context.get('parent_id') or '—'}",
            f"Parça  {payload.get('current_state') or context.get('hardware_id') or '—'}",
            f"Gereksinim  {len(context.get('requirement_ids') or [])}",
            f"Test  {len(context.get('test_ids') or [])}",
            f"Alternatif  {len(payload.get('alternatives') or [])}",
        )
        for variable, label in zip(self.hardware_trace_vars, labels):
            variable.set(label)
        self.hardware_trace_frame.grid()

    def prefill_hardware_comparison(self, payload: Mapping[str, Any]) -> None:
        """Donanım Kartları çalışma alanından gelen kanıtlı değerleri forma taşır."""
        alternatives = [
            " ".join(str(value or "").split())
            for value in payload.get("alternatives", [])
            if " ".join(str(value or "").split())
        ]
        if not alternatives:
            raise ValueError("Donanım karşılaştırması için en az bir alternatif gerekli.")
        parameters: list[dict[str, Any]] = []
        for raw in payload.get("parameters", []):
            if not isinstance(raw, Mapping) or not str(raw.get("name") or "").strip():
                continue
            alternative_values = {
                name: (raw.get("alternative_values") or {}).get(name, "")
                for name in alternatives
            }
            parameters.append({
                "name": str(raw.get("name") or "").strip(),
                "current_value": raw.get("current_value", ""),
                "unit": raw.get("unit", ""),
                "weight": raw.get("weight", ""),
                "direction": self._canonical_direction(raw.get("direction", logic.DIRECTION_HIGH)),
                "minimum": raw.get("minimum", ""),
                "maximum": raw.get("maximum", ""),
                "mandatory": bool(raw.get("mandatory", False)),
                "alternative_values": alternative_values,
            })
        self.analysis_name.set(str(payload.get("analysis_name") or "Donanım alternatif karşılaştırması"))
        self.current_state.set(str(payload.get("current_state") or ""))
        self.reason_text.configure(state=tk.NORMAL)
        self.reason_text.delete("1.0", tk.END)
        self.reason_text.insert("1.0", str(payload.get("change_reason") or ""))
        self.alternatives = alternatives
        self.parameters = parameters
        self.active_alternative.set(alternatives[0])
        self.editing_index = None
        self.last_result = None
        self.hardware_context = dict(payload.get("hardware_context") or {})
        self._update_hardware_trace(payload)
        self._refresh_alternatives()
        self._refresh_parameter_table()
        self._clear_parameter_form()
        self._update_export_buttons()
        self.mode_notebook.select(self.manual_mode_tab)
        self.notebook.select(self.input_tab)
        self.focus()

    def prefill_requirement_simulation(self, requirement_id: str) -> None:
        """Donanım kartındaki gereksinim bağını simülasyon formunda açar."""
        self.mode_notebook.select(self.simulation_mode_tab)
        self.simulation_panel.select_requirement(requirement_id)
        self.focus()

    def refresh_language(self) -> None:
        if not self.exists:
            return
        self.window.title(self._tr("Etki Analizi", "Impact Analysis"))
        for widget, tr, en in self.translatable:
            try:
                widget.configure(text=self._tr(tr, en))
            except tk.TclError:
                pass
        self.notebook.tab(
            self.input_tab,
            text=self._tr("Analiz Girdileri", "Analysis Inputs"),
        )
        self.notebook.tab(
            self.result_tab, text=self._tr("Sonuçlar", "Results")
        )
        self.mode_notebook.tab(
            self.manual_mode_tab,
            text=self._tr("Parça/Durum Alternatifi", "Part/State Alternative"),
        )
        self.mode_notebook.tab(
            self.simulation_mode_tab,
            text=self._tr("Gereksinim Değişikliği Simülasyonu", "Requirement Change Simulation"),
        )
        for tree, definitions in (
            (self.result_tree, RESULT_COLUMNS),
            (self.comparison_tree, COMPARISON_COLUMNS),
        ):
            for key, tr, en, _width, _anchor in definitions:
                tree.heading(key, text=self._tr(tr, en))
        current_direction = self._canonical_direction(
            self.parameter_vars["direction"].get()
        )
        self.direction_combo.configure(values=self._direction_options())
        self.parameter_vars["direction"].set(
            self._display_direction(current_direction)
        )
        self._update_save_button()
        self._refresh_alternatives()
        self._refresh_parameter_table()
        if self.last_result:
            self._render_result()
        self.simulation_panel.refresh_language()

    @staticmethod
    def _comboboxes(widget: tk.Misc) -> list[ttk.Combobox]:
        """Etki Analizi penceresindeki açılır listeleri döndürür."""
        result: list[ttk.Combobox] = []
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                result.append(child)
            result.extend(ImpactAnalysisWorkspace._comboboxes(child))
        return result

    @staticmethod
    def _theme_combobox_popdown(
        combo: ttk.Combobox,
        palette: Mapping[str, str],
        selected: str,
        border: str,
    ) -> None:
        """macOS sistem temasından gelen siyah Combobox menüsünü renklendirir."""
        try:
            popdown = combo.tk.call(
                "ttk::combobox::PopdownWindow", combo._w
            )
            listbox = f"{popdown}.f.l"
            combo.tk.call(
                listbox,
                "configure",
                "-background", palette["entry_bg"],
                "-foreground", palette["entry_fg"],
                "-selectbackground", selected,
                "-selectforeground", palette["fg"],
                "-highlightbackground", border,
                "-highlightcolor", palette["accent"],
            )
        except (AttributeError, tk.TclError):
            # Bazı Tk temaları açılır listeyi işletim sistemine çizdirir.
            # Bu durumda aşağıdaki option database renkleri devreye girer.
            return

    def apply_theme(self) -> None:
        if not self.exists:
            return
        palette = self.palette_getter()
        dark = palette["bg"].lower() == "#1f2329"
        border = "#3D4550" if dark else "#D8DEE5"
        selected = "#234B72" if dark else "#D9EAFB"
        graphite = "#BBC4CC" if dark else "#3F4852"
        success = "#66C58A" if dark else "#217A43"
        danger = "#FF7B72" if dark else "#B42318"
        warning = "#F0B44D" if dark else "#9A6400"

        self.window.configure(background=palette["bg"])
        style_values = (
            ("ImpactRoot.TFrame", palette["bg"], None),
            ("ImpactPanel.TFrame", palette["surface"], border),
            ("ImpactGate.TFrame", palette["surface"], border),
            ("ImpactWinner.TFrame", palette["surface"], palette["accent"]),
        )
        for style_name, background, bordercolor in style_values:
            options = {"background": background}
            if bordercolor:
                options["bordercolor"] = bordercolor
            self.style.configure(style_name, **options)

        label_styles = (
            ("ImpactTitle.TLabel", palette["bg"], palette["fg"], ("Segoe UI", 16, "bold")),
            ("ImpactMuted.TLabel", palette["bg"], palette["muted"], ("Segoe UI", 9)),
            ("ImpactTrace.TLabel", palette["bg"], palette["accent"], ("Consolas", 9, "bold")),
            ("ImpactSection.TLabel", palette["surface"], graphite, ("Consolas", 9, "bold")),
            ("ImpactSectionRoot.TLabel", palette["bg"], graphite, ("Consolas", 9, "bold")),
            ("ImpactField.TLabel", palette["surface"], palette["muted"], ("Segoe UI", 9)),
            ("ImpactGateLabel.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 9, "bold")),
            ("ImpactGateHint.TLabel", palette["surface"], palette["muted"], ("Segoe UI", 8)),
            ("ImpactMode.TLabel", palette["surface"], palette["accent"], ("Consolas", 8, "bold")),
            ("ImpactWinnerLabel.TLabel", palette["surface"], palette["accent"], ("Consolas", 9, "bold")),
            ("ImpactWinnerValue.TLabel", palette["surface"], palette["fg"], ("Consolas", 13, "bold")),
            ("ImpactWinnerHint.TLabel", palette["surface"], palette["muted"], ("Segoe UI", 8)),
            ("ImpactPanelHeading.TLabel", palette["surface"], graphite, ("Consolas", 9, "bold")),
        )
        for name, background, foreground, font in label_styles:
            self.style.configure(
                name, background=background,
                foreground=foreground, font=font,
            )
        self.style.configure(
            "Impact.TNotebook", background=palette["bg"], bordercolor=border
        )
        self.style.configure(
            "Impact.TNotebook.Tab", background=palette["bg"],
            foreground=palette["muted"], padding=(14, 7),
            font=("Segoe UI", 9, "bold"),
        )
        self.style.map(
            "Impact.TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", palette["accent"])],
        )
        self.style.configure(
            "Impact.Treeview", background=palette["surface"],
            fieldbackground=palette["surface"], foreground=palette["fg"],
            bordercolor=border, rowheight=28, font=("Segoe UI", 9),
        )
        self.style.configure(
            "Impact.Treeview.Heading", background=palette["bg"],
            foreground=palette["fg"], bordercolor=border,
            relief="flat", font=("Segoe UI", 9, "bold"),
        )
        self.style.map(
            "Impact.Treeview",
            background=[("selected", selected)],
            foreground=[("selected", palette["fg"])],
        )
        self.style.configure(
            "Impact.TCombobox",
            fieldbackground=palette["entry_bg"],
            background=palette["entry_bg"],
            foreground=palette["entry_fg"],
            arrowcolor=palette["muted"],
            bordercolor=border,
        )
        self.style.map(
            "Impact.TCombobox",
            fieldbackground=[
                ("disabled", palette["surface"]),
                ("readonly", palette["entry_bg"]),
            ],
            foreground=[
                ("disabled", palette["muted"]),
                ("readonly", palette["entry_fg"]),
            ],
            selectbackground=[("readonly", selected)],
            selectforeground=[("readonly", palette["fg"])],
        )
        popdown_options = {
            "*TCombobox*Listbox.background": palette["entry_bg"],
            "*TCombobox*Listbox.foreground": palette["entry_fg"],
            "*TCombobox*Listbox.selectBackground": selected,
            "*TCombobox*Listbox.selectForeground": palette["fg"],
        }
        for pattern, value in popdown_options.items():
            self.window.option_add(pattern, value)
        for combo in self._comboboxes(self.window):
            combo.configure(style="Impact.TCombobox")
            self._theme_combobox_popdown(combo, palette, selected, border)
        for text_widget in (
            self.reason_text,
            self.explanation_text,
        ):
            text_widget.configure(
                background=palette["entry_bg"],
                foreground=palette["entry_fg"],
                insertbackground=palette["fg"],
                highlightbackground=border,
                highlightcolor=palette["accent"],
            )
        self.alternative_list.configure(
            background=palette["entry_bg"],
            foreground=palette["entry_fg"],
            selectbackground=selected, selectforeground=palette["fg"],
            highlightbackground=border, highlightcolor=palette["accent"],
        )
        for tree in (self.result_tree, self.comparison_tree):
            tree.tag_configure("suitable", foreground=success)
            tree.tag_configure("unsuitable", foreground=danger)
            tree.tag_configure("missing", foreground=warning)
        self.simulation_panel.apply_theme()

    def on_traceability_started(self) -> None:
        """Belge sonrası tarama başladığında simülasyon durum şeridini günceller."""
        if self.exists:
            self.simulation_panel.on_traceability_started()

    def on_traceability_ready(
        self, report: Mapping[str, Any], health: Mapping[str, Any]
    ) -> None:
        """Yeni belge sürümünü açık simülasyon çalışma alanına taşır."""
        if self.exists:
            self.simulation_panel.on_traceability_ready(report, health)

    def on_traceability_failed(self, message: str) -> None:
        if self.exists:
            self.simulation_panel.on_traceability_failed(message)
