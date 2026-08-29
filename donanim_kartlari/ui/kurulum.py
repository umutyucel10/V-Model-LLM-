# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — donanim_kartlari_ui.py'nin bölünmüş
parçalarından biri. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Mapping, Sequence
import webbrowser

try:
    from PIL import Image, ImageTk
except ImportError:  # Görsel desteği isteğe bağlıdır; yer tutucu her zaman çalışır.
    Image = ImageTk = None

import donanim_kartlari_gorsel as hardware_visuals
import donanim_kartlari_yonetim as management
from hardware_image_generation_ui import AIImageGenerationDialog, BulkAIImageDialog
from donanim_kartlari_karsilastirma_ui import HardwareComparisonWorkspace
from donanim_detayli_inceleme_ui import HardwareDetailedReview
from donanim_detayli_inceleme import gallery_entries
from donanim_kartlari_model import (
    LIFECYCLE_STATES,
    MISSING_VALUE,
    PLACEHOLDER_IMAGE,
    PRODUCT_LEVELS,
    WORKING_STATES,
    clean_text,
    is_missing,
)
from hardware_image_provider import ImageProviderError, validate_image_file


from .yardimcilar import (
    DETAIL_TABS,
    ScrollableCards,
    HardwareEditorDialog,
    AlternativeDialog,
    _clean,
    _display,
    _trace_node_index,
    catalog_filter_options,
    product_tree_instances,
)

class _KurulumMixin:
    def __init__(
        self, master: tk.Misc, style: ttk.Style,
        language_getter: Callable[[], str],
        palette_getter: Callable[[], Mapping[str, str]],
        project_name_getter: Callable[[], str],
        catalog_getter: Callable[[], Mapping[str, Any] | None],
        traceability_getter: Callable[[], Mapping[str, Any] | None],
        rescan_callback: Callable[[bool], None] | None = None,
        datasheet_callback: Callable[[Sequence[str], str], None] | None = None,
        impact_callback: Callable[[Mapping[str, Any]], None] | None = None,
        requirement_callback: Callable[[str], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.master = master
        self.style = style
        self.language_getter = language_getter
        self.palette_getter = palette_getter
        self.project_name_getter = project_name_getter
        self.catalog_getter = catalog_getter
        self.traceability_getter = traceability_getter
        self.rescan_callback = rescan_callback
        self.datasheet_callback = datasheet_callback
        self.impact_callback = impact_callback
        self.requirement_callback = requirement_callback
        self.on_close = on_close
        self.base_catalog: dict[str, Any] = {}
        self.catalog: dict[str, Any] = {}
        self.overrides: dict[str, Any] = {}
        self.override_conflicts: list[dict[str, Any]] = []
        self.change_summary: dict[str, Any] = {}
        self.selected_id = ""
        self.simulation_result: dict[str, Any] | None = None
        self.impact_badges: dict[str, list[str]] = {}
        self._photo_refs: list[Any] = []
        self._card_widgets: dict[str, tuple[tk.Frame, ttk.Frame]] = {}
        self._traceability_cache: dict[str, Any] | None = None
        self._syncing_tree_selection = False
        self._visual_generation_token = 0
        self._visual_generation_running = False
        self._wide_layout: bool | None = None
        self._toolbar_wide: bool | None = None
        self._quality_wide: bool | None = None
        self._loading = False
        self._detail_trees: dict[str, ttk.Treeview] = {}
        self._detailed_review: HardwareDetailedReview | None = None
        self._detail_visible = False
        self._ai_image_dialog: AIImageGenerationDialog | None = None
        self._bulk_image_dialog: BulkAIImageDialog | None = None
        self._comparison_workspace: HardwareComparisonWorkspace | None = None
        self._filter_after_id: str | None = None
        self._preferences_loaded_project = ""
        self._card_page = 0
        self._card_page_size = 24
        self._compare_selection: set[str] = set()
        self._quality_filter = ""

        self.window = tk.Toplevel(master)
        self.window.title("Donanım Kartları")
        self.window.geometry("1460x850")
        self.window.minsize(980, 680)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.bind("<Control-f>", self._focus_search)
        self.window.bind("<Command-f>", self._focus_search)
        self.window.bind("<Control-z>", lambda _event: self._undo_last_change())
        self.window.bind("<Command-z>", lambda _event: self._undo_last_change())

        self.search_placeholder = "Parça / PN / üretici ara…"
        self.search_var = tk.StringVar(value=self.search_placeholder)
        self.system_filter = tk.StringVar(value="Sistem: Tümü")
        self.manufacturer_filter = tk.StringVar(value="Üretici: Tümü")
        self.working_filter = tk.StringVar(value="Çalışma: Tümü")
        self.lifecycle_filter = tk.StringVar(value="Yaşam: Tümü")
        self.confidence_filter = tk.StringVar(value="Güven: Tümü")
        self.view_mode = tk.StringVar(value="Kart")
        self.sort_var = tk.StringVar(value="Güven: yüksekten düşüğe")
        self.group_var = tk.StringVar(value="Gruplama: Yok")
        self.impacted_only = tk.BooleanVar(value=False)
        self.no_alternative_only = tk.BooleanVar(value=False)
        self.no_datasheet_only = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Katalog yükleniyor…")
        self.count_var = tk.StringVar()
        self.detail_title = tk.StringVar(value="Bir donanım kartı seçin")
        self.detail_subtitle = tk.StringVar(value="Kimlik, teknik sınır ve kanıt ayrıntıları burada gösterilir.")
        self.confidence_var = tk.StringVar(value="Güven —")
        self.compare_var = tk.StringVar(value="Karşılaştırma: 0/4")
        self.page_var = tk.StringVar(value="Sayfa 1/1")

        self._build()
        self.apply_theme()
        self.refresh()
        self.window.bind("<Configure>", self._on_resize)

    @property
    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        if self.exists:
            self.window.deiconify(); self.window.lift(); self.window.focus_force()

    def close(self) -> None:
        if (
            self._detailed_review is not None
            and self._detail_visible
            and self._detailed_review.editing
            and self._detailed_review.dirty
            and not messagebox.askyesno(
                "Kaydedilmemiş Değişiklik",
                "Donanım kartındaki kaydedilmemiş değişiklikler silinerek pencere kapatılsın mı?",
                parent=self.window,
            )
        ):
            return
        self._visual_generation_token += 1
        if self.exists:
            self.window.destroy()
        if self.on_close:
            self.on_close()

    def _build(self) -> None:
        self.root = ttk.Frame(self.window, style="HardwareRoot.TFrame", padding=12)
        self.root.pack(fill="both", expand=True)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        header = ttk.Frame(self.root, style="HardwareRoot.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        title_box = ttk.Frame(header, style="HardwareRoot.TFrame")
        title_box.grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="Donanım Kartları", style="HardwareTitle.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="ÜRÜN AĞACI  ·  BOM  ·  DATASHEET  ·  GEREKSİNİM İZİ", style="HardwareSignature.TLabel").pack(anchor="w", pady=(2, 0))
        self.project_label = ttk.Label(header, text="", style="HardwareMeta.TLabel")
        self.project_label.grid(row=0, column=1, sticky="e")

        self.toolbar = ttk.Frame(self.root, style="HardwareToolbar.TFrame", padding=(8, 7), borderwidth=1, relief="solid")
        self.toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.toolbar.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(self.toolbar, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.search_entry.insert(0, "")
        self.search_entry.bind("<KeyRelease>", self._filters_changed)
        self.search_entry.bind("<FocusIn>", self._search_focus_in)
        self.search_entry.bind("<FocusOut>", self._search_focus_out)
        self.filter_combos: list[ttk.Combobox] = []
        for column, variable, width in (
            (1, self.system_filter, 15), (2, self.manufacturer_filter, 15),
            (3, self.working_filter, 14), (4, self.lifecycle_filter, 14),
            (5, self.confidence_filter, 15),
        ):
            combo = ttk.Combobox(self.toolbar, textvariable=variable, state="readonly", width=width, style="Hardware.TCombobox")
            combo.grid(row=0, column=column, padx=3)
            combo.bind("<<ComboboxSelected>>", self._filters_changed)
            self.filter_combos.append(combo)
        self.new_button = ttk.Button(self.toolbar, text="Yeni Donanım Ekle", style="primary.TButton", command=self._new_item)
        self.new_button.grid(row=0, column=6, padx=(8, 3))
        self.datasheet_button = ttk.Button(self.toolbar, text="Datasheet Yükle", style="primary.Outline.TButton", command=self._load_datasheet)
        self.datasheet_button.grid(row=0, column=7, padx=3)
        self.rescan_button = ttk.Button(self.toolbar, text="Kataloğu Yeniden Tara", style="primary.Outline.TButton", command=self._rescan)
        self.rescan_button.grid(row=0, column=8, padx=3)
        self.sample_button = ttk.Button(self.toolbar, text="Örnek Donanım Ağacı Yükle", command=self._load_sample)
        self.sample_button.grid(row=0, column=9, padx=(3, 0))
        self.bulk_image_button = ttk.Button(
            self.toolbar, text="Toplu AI Görseli", style="primary.Outline.TButton",
            command=self._open_bulk_image_generation,
        )
        self.bulk_image_button.grid(row=0, column=10, padx=(3, 0))

        self.quality_panel = ttk.Frame(
            self.root, style="HardwareToolbar.TFrame", padding=(8, 6),
            borderwidth=1, relief="solid",
        )
        self.quality_panel.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.quality_buttons: dict[str, ttk.Button] = {}
        quality_definitions = (
            ("total", "Toplam"), ("high_confidence", "Yüksek güven"),
            ("low_confidence", "Düşük güven"), ("missing_datasheet", "Datasheet yok"),
            ("missing_image", "Görsel yok"), ("missing_requirements", "Gereksinim yok"),
            ("missing_tests", "Test yok"), ("critical_without_alternative", "Kritik / alternatifsiz"),
            ("conflicts", "Çelişki"),
        )
        for column, (key, label) in enumerate(quality_definitions):
            self.quality_panel.columnconfigure(column, weight=1)
            button = ttk.Button(
                self.quality_panel, text=f"{label} —", style="HardwareMetric.TButton",
                command=lambda value=key: self._quality_filter_selected(value),
            )
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))
            self.quality_buttons[key] = button

        catalog_controls = self.catalog_controls = ttk.Frame(self.quality_panel, style="HardwareToolbar.TFrame")
        catalog_controls.grid(row=1, column=0, columnspan=len(quality_definitions), sticky="ew", pady=(6, 0))
        catalog_controls.columnconfigure(8, weight=1)
        self.view_combo = ttk.Combobox(
            catalog_controls, textvariable=self.view_mode, state="readonly", width=15,
            values=("Kart", "Kompakt Liste", "Ürün Ağacı"), style="Hardware.TCombobox",
        )
        self.view_combo.grid(row=0, column=0, padx=(0, 4)); self.view_combo.bind("<<ComboboxSelected>>", self._view_changed)
        self.sort_combo = ttk.Combobox(
            catalog_controls, textvariable=self.sort_var, state="readonly", width=25,
            values=("Güven: yüksekten düşüğe", "Güven: düşükten yükseğe", "Parça adı: A–Z", "Üretici: A–Z"),
            style="Hardware.TCombobox",
        )
        self.sort_combo.grid(row=0, column=1, padx=4); self.sort_combo.bind("<<ComboboxSelected>>", self._filters_changed)
        self.group_combo = ttk.Combobox(
            catalog_controls, textvariable=self.group_var, state="readonly", width=20,
            values=("Gruplama: Yok", "Gruplama: Alt sistem", "Gruplama: Üretici"),
            style="Hardware.TCombobox",
        )
        self.group_combo.grid(row=0, column=2, padx=4); self.group_combo.bind("<<ComboboxSelected>>", self._filters_changed)
        ttk.Checkbutton(catalog_controls, text="Etkilenen", variable=self.impacted_only, command=self._filters_changed).grid(row=0, column=3, padx=4)
        ttk.Checkbutton(catalog_controls, text="Alternatifsiz", variable=self.no_alternative_only, command=self._filters_changed).grid(row=0, column=4, padx=4)
        ttk.Checkbutton(catalog_controls, text="Datasheet yok", variable=self.no_datasheet_only, command=self._filters_changed).grid(row=0, column=5, padx=4)
        ttk.Button(catalog_controls, text="Filtreleri Temizle", command=self._clear_filters).grid(row=0, column=6, padx=4)
        ttk.Button(catalog_controls, text="Geri Al", command=self._undo_last_change).grid(row=0, column=7, padx=4)
        self.catalog_control_widgets = catalog_controls.winfo_children()

        self.body = ttk.Frame(self.root, style="HardwareRoot.TFrame")
        self.body.grid(row=3, column=0, sticky="nsew")
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)

        self.tree_panel = ttk.Frame(self.body, style="HardwarePanel.TFrame", borderwidth=1, relief="solid", width=330)
        self.tree_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.tree_panel.grid_propagate(False)
        self.tree_panel.columnconfigure(0, weight=1); self.tree_panel.rowconfigure(2, weight=1)
        ttk.Label(self.tree_panel, text="ÜRÜN AĞACI / BOM", style="HardwareSection.TLabel").grid(row=0, column=0, sticky="ew", padx=9, pady=(9, 3))
        ttk.Label(self.tree_panel, text="Alternatifler kesik çizgili ayrı dalda gösterilir.", style="HardwarePanelMuted.TLabel").grid(row=1, column=0, sticky="ew", padx=9, pady=(0, 6))
        tree_frame = ttk.Frame(self.tree_panel, style="HardwarePanel.TFrame")
        tree_frame.grid(row=2, column=0, sticky="nsew")
        self.product_tree = ttk.Treeview(tree_frame, columns=("qty", "status", "confidence", "impact"), show="tree headings", style="Hardware.Treeview")
        self.product_tree.heading("#0", text="Parça / Konum")
        self.product_tree.heading("qty", text="Adet")
        self.product_tree.heading("status", text="Durum")
        self.product_tree.heading("confidence", text="Güven")
        self.product_tree.heading("impact", text="Etki")
        self.product_tree.column("#0", width=135, minwidth=110)
        self.product_tree.column("qty", width=35, anchor="center", stretch=False)
        self.product_tree.column("status", width=60, anchor="center", stretch=False)
        self.product_tree.column("confidence", width=45, anchor="e", stretch=False)
        self.product_tree.column("impact", width=32, anchor="center", stretch=False)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.product_tree.yview)
        self.product_tree.configure(yscrollcommand=tree_scroll.set)
        self.product_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.product_tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.product_tree.bind("<Double-1>", self._tree_open_detail)
        self.product_tree.bind("<Button-3>", self._tree_context_menu)
        self.product_tree.bind("<Button-2>", self._tree_context_menu)
        tree_actions = ttk.Frame(self.tree_panel, style="HardwarePanel.TFrame", padding=7)
        tree_actions.grid(row=3, column=0, sticky="ew")
        ttk.Button(tree_actions, text="Üst Parçaya Git", command=self._go_parent).pack(side="left")
        ttk.Button(tree_actions, text="Gereksinime Git", command=self._go_requirement).pack(side="right")

        self.catalog_panel = ttk.Frame(self.body, style="HardwarePanel.TFrame", borderwidth=1, relief="solid")
        self.catalog_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.catalog_panel.columnconfigure(0, weight=1); self.catalog_panel.rowconfigure(1, weight=1)
        catalog_head = ttk.Frame(self.catalog_panel, style="HardwarePanel.TFrame", padding=(9, 8))
        catalog_head.grid(row=0, column=0, sticky="ew")
        catalog_head.columnconfigure(0, weight=1)
        ttk.Label(catalog_head, text="DONANIM KATALOĞU", style="HardwareSection.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(catalog_head, textvariable=self.count_var, style="HardwarePanelMuted.TLabel").grid(row=0, column=1, sticky="e")
        self.compare_button = ttk.Button(
            catalog_head, textvariable=self.compare_var, style="primary.Outline.TButton",
            command=self._open_comparison, state="disabled",
        )
        self.compare_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.prev_page_button = ttk.Button(catalog_head, text="‹", width=3, command=lambda: self._change_page(-1))
        self.prev_page_button.grid(row=0, column=3, padx=(8, 2))
        ttk.Label(catalog_head, textvariable=self.page_var, style="HardwarePanelMuted.TLabel").grid(row=0, column=4)
        self.next_page_button = ttk.Button(catalog_head, text="›", width=3, command=lambda: self._change_page(1))
        self.next_page_button.grid(row=0, column=5, padx=(2, 0))
        self.cards = ScrollableCards(self.catalog_panel, self.palette_getter)
        self.cards.grid(row=1, column=0, sticky="nsew")

        self.compact_frame = ttk.Frame(self.catalog_panel, style="HardwarePanel.TFrame")
        self.compact_frame.columnconfigure(0, weight=1); self.compact_frame.rowconfigure(0, weight=1)
        compact_columns = ("part_number", "manufacturer", "role", "status", "confidence", "requirements", "tests", "alternatives")
        self.compact_list = ttk.Treeview(
            self.compact_frame, columns=compact_columns, show="tree headings",
            selectmode="extended", style="Hardware.Treeview",
        )
        compact_headings = {
            "#0": ("Parça", 180), "part_number": ("Parça no", 100),
            "manufacturer": ("Üretici", 110), "role": ("Sistem görevi", 220),
            "status": ("Durum", 90), "confidence": ("Güven", 60),
            "requirements": ("Ger.", 45), "tests": ("Test", 45), "alternatives": ("Alt.", 45),
        }
        for name, (title, width) in compact_headings.items():
            self.compact_list.heading(name, text=title)
            self.compact_list.column(name, width=width, minwidth=40, stretch=name in {"#0", "role"})
        compact_y = ttk.Scrollbar(self.compact_frame, orient="vertical", command=self.compact_list.yview)
        compact_x = ttk.Scrollbar(self.compact_frame, orient="horizontal", command=self.compact_list.xview)
        self.compact_list.configure(yscrollcommand=compact_y.set, xscrollcommand=compact_x.set)
        self.compact_list.grid(row=0, column=0, sticky="nsew"); compact_y.grid(row=0, column=1, sticky="ns"); compact_x.grid(row=1, column=0, sticky="ew")
        self.compact_list.bind("<<TreeviewSelect>>", self._compact_selected)
        self.compact_list.bind("<Double-1>", self._compact_open)
        self.compact_list.bind("<Return>", self._compact_open)
        self.compact_list.bind("<Button-3>", self._compact_context_menu)
        self.compact_list.bind("<Button-2>", self._compact_context_menu)

        self.catalog_tree_frame = ttk.Frame(self.catalog_panel, style="HardwarePanel.TFrame")
        self.catalog_tree_frame.columnconfigure(0, weight=1); self.catalog_tree_frame.rowconfigure(0, weight=1)
        self.catalog_tree = ttk.Treeview(
            self.catalog_tree_frame, columns=("qty", "pn", "manufacturer", "status", "confidence", "trace"),
            show="tree headings", style="Hardware.Treeview",
        )
        for name, title, width in (
            ("#0", "Ürün ağacı konumu", 250), ("qty", "Adet", 45), ("pn", "Parça no", 100),
            ("manufacturer", "Üretici", 120), ("status", "Durum", 90),
            ("confidence", "Güven", 60), ("trace", "Ger. → Test → Alt.", 120),
        ):
            self.catalog_tree.heading(name, text=title); self.catalog_tree.column(name, width=width, minwidth=40, stretch=name == "#0")
        catalog_tree_y = ttk.Scrollbar(self.catalog_tree_frame, orient="vertical", command=self.catalog_tree.yview)
        catalog_tree_x = ttk.Scrollbar(self.catalog_tree_frame, orient="horizontal", command=self.catalog_tree.xview)
        self.catalog_tree.configure(yscrollcommand=catalog_tree_y.set, xscrollcommand=catalog_tree_x.set)
        self.catalog_tree.grid(row=0, column=0, sticky="nsew"); catalog_tree_y.grid(row=0, column=1, sticky="ns"); catalog_tree_x.grid(row=1, column=0, sticky="ew")
        self.catalog_tree.bind("<<TreeviewSelect>>", self._catalog_tree_selected)
        self.catalog_tree.bind("<Double-1>", self._catalog_tree_open)
        self.catalog_tree.bind("<Return>", self._catalog_tree_open)

        self.detail_panel = ttk.Frame(self.body, style="HardwarePanel.TFrame", borderwidth=1, relief="solid", width=430)
        self.detail_panel.grid(row=0, column=2, sticky="nsew")
        self.detail_panel.grid_propagate(False)
        self.detail_panel.columnconfigure(0, weight=1); self.detail_panel.rowconfigure(2, weight=1)
        detail_head = ttk.Frame(self.detail_panel, style="HardwarePanel.TFrame", padding=10)
        detail_head.grid(row=0, column=0, sticky="ew")
        detail_head.columnconfigure(0, weight=1)
        ttk.Label(detail_head, textvariable=self.detail_title, style="HardwareDetailTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail_head, textvariable=self.detail_subtitle, style="HardwarePanelMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.confidence_button = ttk.Button(detail_head, textvariable=self.confidence_var, command=self._show_confidence)
        self.confidence_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))
        detail_actions = ttk.Frame(self.detail_panel, style="HardwarePanel.TFrame", padding=(10, 0, 10, 8))
        detail_actions.grid(row=1, column=0, sticky="ew")
        ttk.Button(detail_actions, text="Düzenle", command=self._edit_item).pack(side="left")
        ttk.Button(detail_actions, text="Görsel Seç", command=self._select_image).pack(side="left", padx=(4, 0))
        ttk.Button(detail_actions, text="Görseli Kaldır", command=self._remove_image).pack(side="left", padx=(4, 0))
        ttk.Button(detail_actions, text="Etki Analizi", style="primary.TButton", command=self._send_to_impact).pack(side="right")
        self.detail_notebook = ttk.Notebook(self.detail_panel, style="Hardware.TNotebook")
        self.detail_notebook.grid(row=2, column=0, sticky="nsew")
        self.detail_tabs: dict[str, ttk.Frame] = {}
        for key, title in DETAIL_TABS:
            frame = ttk.Frame(self.detail_notebook, style="HardwareSurface.TFrame", padding=6)
            self.detail_notebook.add(frame, text=title)
            self.detail_tabs[key] = frame
        self._build_detail_tabs()
        self._detail_trees["alternatives"].bind("<<TreeviewSelect>>", self._old_alternative_open)

        self.status_bar = ttk.Frame(self.root, style="HardwareStatus.TFrame", padding=(8, 6), borderwidth=1, relief="solid")
        self.status_bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.status_bar.columnconfigure(0, weight=1)
        ttk.Label(self.status_bar, textvariable=self.status_var, style="HardwareStatus.TLabel").grid(row=0, column=0, sticky="w")
        self.summary_button = ttk.Button(self.status_bar, text="Değişiklik Özeti", command=self._show_change_summary, state="disabled")
        self.summary_button.grid(row=0, column=1, sticky="e")

    def _build_detail_tabs(self) -> None:
        definitions = {
            "identity": (("field", "Alan", 120), ("value", "Değer", 280)),
            "technical": (("field", "Teknik özellik", 120), ("value", "Değer", 80), ("unit", "Birim", 50), ("source", "Kaynak", 95), ("confidence", "Güven", 50)),
            "requirements": (("id", "Kimlik", 80), ("summary", "Özet", 135), ("relation", "İlişki", 65), ("level", "V-Model", 70), ("test", "Bağlı test", 75), ("source", "Kaynak", 80), ("confidence", "Güven", 50)),
            "states": (("state", "Durum", 90), ("parameters", "Değişen parametreler", 180), ("requirements", "Etkilenen gereksinimler", 145)),
            "alternatives": (("id", "Kimlik", 80), ("name", "Alternatif", 115), ("status", "Uyum", 70), ("criteria", "Kriter sonucu", 95), ("risks", "Yeni risk", 85), ("confidence", "Güven", 50)),
            "location": (("instance", "Kullanım yeri", 100), ("parent", "Üst parça", 100), ("level", "Seviye", 80), ("quantity", "Adet", 45), ("location", "Konum", 110)),
            "sources": (("field", "Alan", 70), ("document", "Belge/datasheet", 90), ("location", "Sayfa/bölüm", 70), ("method", "Çıkarma", 70), ("certainty", "Durum", 60), ("confidence", "Güven", 45), ("evidence", "Kanıt", 130)),
        }
        for key, columns in definitions.items():
            frame = self.detail_tabs[key]
            frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=[item[0] for item in columns], show="headings", style="Hardware.Treeview")
            for name, title, width in columns:
                tree.heading(name, text=title)
                tree.column(name, width=width, minwidth=45, anchor="w", stretch=name in {"value", "summary", "evidence", "parameters"})
            yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            tree.grid(row=0, column=0, sticky="nsew")
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll.grid(row=1, column=0, sticky="ew")
            self._detail_trees[key] = tree
        source_actions = ttk.Frame(self.detail_tabs["sources"], style="HardwareSurface.TFrame")
        source_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(source_actions, text="Seçili Otomatik Bilgiyi Reddet", command=self._reject_source_field).pack(side="right")
        technical_actions = ttk.Frame(self.detail_tabs["technical"], style="HardwareSurface.TFrame")
        technical_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(
            technical_actions, text="Seçili Teknik Değeri Düzenle",
            command=self._edit_technical_value,
        ).pack(side="right")
        alt_actions = ttk.Frame(self.detail_tabs["alternatives"], style="HardwareSurface.TFrame")
        alt_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(alt_actions, text="Alternatif Ekle", command=self._add_alternative).pack(side="left")
        ttk.Button(alt_actions, text="Etki Analizinde Karşılaştır", style="primary.TButton", command=self._send_to_impact).pack(side="right")
        state_actions = ttk.Frame(self.detail_tabs["states"], style="HardwareSurface.TFrame")
        state_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(state_actions, text="Durum Ekle", command=self._add_state).pack(side="right")
        req_actions = ttk.Frame(self.detail_tabs["requirements"], style="HardwareSurface.TFrame")
        req_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(req_actions, text="Gereksinim İlişkilendir", command=self._link_requirement).pack(side="left")
        ttk.Button(req_actions, text="Seçili Gereksinime Git", command=self._go_requirement).pack(side="right")

    def refresh(self) -> None:
        try:
            loaded = self.catalog_getter() or {}
            self.base_catalog = dict(loaded)
            project_name = self.project_name_getter() or self.base_catalog.get("project_name") or "Proje"
            self.overrides = management.load_overrides(project_name, self.base_catalog)
            self.catalog, self.override_conflicts = management.apply_overrides(self.base_catalog, self.overrides)
            self._restore_preferences(project_name)
            self._traceability_cache = None
            self.project_label.configure(text=f"PROJE / BELGE SETİ  ·  {project_name}  ·  {self.catalog.get('version', '—')}")
            self.status_var.set(self._status_text())
            self._refresh_filters()
            self._render_all()
            if self._detail_visible and self._detailed_review is not None:
                if self.selected_id in self._card_index():
                    self._detailed_review.refresh()
                else:
                    self._close_detailed_review()
            self._start_visual_generation()
        except Exception as error:
            self.status_var.set(f"Katalog yüklenemedi: {error}")
            self.catalog = {}
            self._render_all()

    def on_catalog_ready(
        self, catalog: Mapping[str, Any] | None,
        status: Mapping[str, Any] | None = None,
        change_summary: Mapping[str, Any] | None = None,
    ) -> None:
        self.set_loading(False)
        if catalog:
            self.base_catalog = dict(catalog)
            project_name = self.project_name_getter() or self.base_catalog.get("project_name") or "Proje"
            self.overrides = management.load_overrides(project_name, self.base_catalog)
            self.catalog, self.override_conflicts = management.apply_overrides(self.base_catalog, self.overrides)
            self._restore_preferences(project_name)
            self._traceability_cache = None
        self.change_summary = dict(change_summary or {})
        has_summary = any((self.change_summary.get("counts") or {}).values())
        self.summary_button.configure(state="normal" if has_summary or self.override_conflicts else "disabled")
        self.status_var.set((status or {}).get("message") or self._status_text())
        self._refresh_filters(); self._render_all()
        if self._detail_visible and self._detailed_review is not None:
            if self.selected_id in self._card_index():
                self._detailed_review.refresh()
            else:
                self._close_detailed_review()
        self._start_visual_generation()

    def set_loading(self, loading: bool, message: str = "") -> None:
        self._loading = loading
        state = "disabled" if loading else "normal"
        self.rescan_button.configure(state=state)
        self.datasheet_button.configure(state=state)
        self.new_button.configure(state=state)
        self.bulk_image_button.configure(state=state)
        if message:
            self.status_var.set(message)

    def set_simulation_result(self, result: Mapping[str, Any] | None) -> None:
        self.simulation_result = dict(result) if result else None
        self.impact_badges = management.build_impact_badges(self.catalog, self.simulation_result)
        self._render_tree(); self._render_catalog_view(); self._render_quality_strip()

    def _status_text(self) -> str:
        count = len(self.catalog.get("hardware_items", []))
        conflicts = len(self.catalog.get("conflicts", [])) + len(self.override_conflicts)
        unresolved = len(self.catalog.get("unresolved_items", []))
        source_missing = sum(
            1 for item in self.catalog.get("hardware_items", [])
            if item.get("source_presence_status") == "Kaynaktan artık bulunamadı"
        )
        if not count:
            return "Henüz donanım kataloğu yok. Önce belgeleri üretin veya örnek ağacı yükleyin."
        suffix = f" · {source_missing} kaynakta bulunamadı" if source_missing else ""
        return f"Katalog hazır · {count} kart · {conflicts} çakışma · {unresolved} çözülmemiş kayıt{suffix}"

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is not self.window:
            return
        wide = event.width >= 1500
        toolbar_wide = event.width >= 1680
        quality_wide = event.width >= 1500
        if quality_wide != self._quality_wide:
            self._quality_wide = quality_wide
            if quality_wide:
                for column, button in enumerate(self.quality_buttons.values()):
                    button.grid_configure(row=0, column=column, columnspan=1, padx=(0 if column == 0 else 3, 0))
                self.catalog_controls.grid_configure(row=1, column=0, columnspan=9, pady=(6, 0))
                for column, widget in enumerate(self.catalog_control_widgets):
                    widget.grid_configure(row=0, column=column, padx=4, pady=0)
            else:
                for index, button in enumerate(self.quality_buttons.values()):
                    row, column = (0, index) if index < 5 else (1, index - 5)
                    button.grid_configure(row=row, column=column, columnspan=1, padx=(0 if column == 0 else 3, 0), pady=(0 if row == 0 else 4, 0))
                self.catalog_controls.grid_configure(row=2, column=0, columnspan=9, pady=(6, 0))
                for index, widget in enumerate(self.catalog_control_widgets):
                    row, column = (0, index) if index < 3 else (1, index - 3)
                    widget.grid_configure(row=row, column=column, padx=4, pady=(0 if row == 0 else 4, 0))
        if toolbar_wide != self._toolbar_wide:
            self._toolbar_wide = toolbar_wide
            if toolbar_wide:
                self.search_entry.grid_configure(row=0, column=0, columnspan=1, padx=(0, 6), pady=0)
                for index, combo in enumerate(self.filter_combos, start=1):
                    combo.grid_configure(row=0, column=index, padx=3, pady=0)
                for column, button in enumerate(
                    (self.new_button, self.datasheet_button, self.rescan_button, self.sample_button, self.bulk_image_button),
                    start=6,
                ):
                    button.grid_configure(row=0, column=column, columnspan=1, padx=(8 if column == 6 else 3, 0), pady=0)
            else:
                self.search_entry.grid_configure(row=0, column=0, columnspan=2, padx=(0, 6), pady=(0, 6))
                for index, combo in enumerate(self.filter_combos, start=2):
                    combo.grid_configure(row=0, column=index, padx=3, pady=(0, 6))
                for button, column, columnspan in (
                    (self.new_button, 0, 2),
                    (self.datasheet_button, 2, 1),
                    (self.rescan_button, 3, 2),
                    (self.sample_button, 5, 2),
                    (self.bulk_image_button, 7, 2),
                ):
                    button.grid_configure(
                        row=1, column=column, columnspan=columnspan,
                        padx=(0, 6), pady=0, sticky="w",
                    )
        if wide == self._wide_layout:
            return
        self._wide_layout = wide
        self.detail_panel.grid_forget()
        if wide:
            self.body.rowconfigure(0, weight=1); self.body.rowconfigure(1, weight=0)
            self.body.columnconfigure(0, weight=0); self.body.columnconfigure(1, weight=1); self.body.columnconfigure(2, weight=0)
            self.detail_panel.configure(width=430, height=1)
            self.detail_panel.grid(row=0, column=2, sticky="nsew")
            self.tree_panel.grid_configure(row=0, column=0, padx=(0, 8))
            self.catalog_panel.grid_configure(row=0, column=1, padx=(0, 8))
        else:
            self.body.rowconfigure(0, weight=1); self.body.rowconfigure(1, weight=0)
            self.body.columnconfigure(0, weight=0); self.body.columnconfigure(1, weight=1); self.body.columnconfigure(2, weight=0)
            # Ttk Notebook'in platforma göre değişen minimum yüksekliği küçük
            # pencerede kataloğu ezdiği için dar düzende özet panel gösterilmez.
            # Kart/listeden tek tık aynı ana penceredeki geniş Detaylı İnceleme
            # çalışma alanını açar; bilgi erişimi kaybolmaz.
            self.tree_panel.grid_configure(row=0, column=0, padx=(0, 8))
            self.catalog_panel.grid_configure(row=0, column=1, padx=(0, 0))
        self._apply_catalog_panel_span()

    def refresh_language(self) -> None:
        # Bu ilk sürüm Türkçe mühendislik terimlerini kullanır; pencere başlığı yine yenilenir.
        if self.exists:
            self.window.title("Donanım Kartları" if self.language_getter() == "tr" else "Hardware Cards")

    def apply_theme(self) -> None:
        if not self.exists:
            return
        palette = self.palette_getter()
        dark = palette["bg"].lower() == "#1f2329"
        border = "#3D4550" if dark else "#D8DEE5"
        selected = "#234B72" if dark else "#E8F1FC"
        graphite = "#BBC4CC" if dark else "#3F4852"
        warning = "#F0B44D" if dark else "#9A6400"
        self.window.configure(background=palette["bg"])
        for name, background, bordercolor in (
            ("HardwareRoot.TFrame", palette["bg"], palette["bg"]),
            ("HardwarePanel.TFrame", palette["surface"], border),
            ("HardwareSurface.TFrame", palette["surface"], palette["surface"]),
            ("HardwareToolbar.TFrame", palette["surface"], border),
            ("HardwareStatus.TFrame", palette["surface"], border),
            ("HardwareCard.TFrame", palette["surface"], palette["surface"]),
            ("HardwareCardSelected.TFrame", selected, selected),
            ("HardwareTraceBar.TFrame", palette["bg"], border),
        ):
            self.style.configure(name, background=background, bordercolor=bordercolor)
        for name, background, foreground, font in (
            ("HardwareTitle.TLabel", palette["bg"], palette["fg"], ("Segoe UI", 16, "bold")),
            ("HardwareSignature.TLabel", palette["bg"], palette["accent"], ("Consolas", 9, "bold")),
            ("HardwareMeta.TLabel", palette["bg"], palette["muted"], ("Consolas", 9)),
            ("HardwareSection.TLabel", palette["surface"], graphite, ("Consolas", 9, "bold")),
            ("HardwarePanelMuted.TLabel", palette["surface"], palette["muted"], ("Segoe UI", 8)),
            ("HardwareMuted.TLabel", palette["bg"], palette["muted"], ("Segoe UI", 8)),
            ("HardwareCardTitle.TLabel", palette["surface"], palette["accent"], ("Segoe UI", 11, "bold")),
            ("HardwareCardText.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 8)),
            ("HardwareMono.TLabel", palette["surface"], palette["fg"], ("Consolas", 8)),
            ("HardwareTraceArrow.TLabel", palette["bg"], palette["muted"], ("Consolas", 9)),
            ("HardwareImpact.TLabel", palette["surface"], warning, ("Consolas", 8, "bold")),
            ("HardwareDetailTitle.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 13, "bold")),
            ("HardwareStatus.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 8)),
            ("HardwareEmpty.TLabel", palette["surface"], palette["muted"], ("Segoe UI", 10)),
            ("HardwareImage.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 8)),
            ("HardwareVisualBadge.TLabel", palette["surface"], palette["accent"], ("Consolas", 6, "bold")),
            ("HardwareTrace.TLabel", palette["bg"], palette["fg"], ("Consolas", 8, "bold")),
            ("HardwareGroup.TLabel", palette["surface"], graphite, ("Consolas", 8, "bold")),
        ):
            self.style.configure(name, background=background, foreground=foreground, font=font)
        self.style.configure("Hardware.Treeview", background=palette["surface"], fieldbackground=palette["surface"], foreground=palette["fg"], bordercolor=border, rowheight=26, font=("Segoe UI", 8))
        self.style.configure("Hardware.Treeview.Heading", background=palette["bg"], foreground=palette["fg"], bordercolor=border, relief="flat", font=("Segoe UI", 8, "bold"))
        self.style.map("Hardware.Treeview", background=[("selected", selected)], foreground=[("selected", palette["fg"])])
        self.style.configure("Hardware.TNotebook", background=palette["surface"], bordercolor=border)
        self.style.configure("Hardware.TNotebook.Tab", background=palette["bg"], foreground=palette["muted"], padding=(6, 6), font=("Segoe UI", 8, "bold"))
        self.style.map("Hardware.TNotebook.Tab", background=[("selected", palette["surface"])], foreground=[("selected", palette["accent"])])
        self.style.configure("HardwareTrace.TButton", font=("Consolas", 8), padding=(5, 2))
        self.style.configure("HardwareMetric.TButton", font=("Consolas", 8, "bold"), padding=(5, 4))
        self.style.configure("Hardware.TCombobox", fieldbackground=palette["entry_bg"], foreground=palette["entry_fg"], background=palette["entry_bg"], bordercolor=border, arrowcolor=palette["muted"])
        self.cards.apply_palette()
        if self._detailed_review is not None:
            self._detailed_review.apply_theme()
        if self.catalog:
            self._render_all()


__all__ = ["HardwareCardsWorkspace", "catalog_filter_options"]
