# -*- coding: utf-8 -*-
"""Donanım Kartları mühendislik çalışma tezgâhı.

Bu modül yalnızca arayüz ve olay yönetimi içerir. Katalog birleştirme,
manuel alan koruması, filtreleme ve Etki Analizi aktarımı
``donanim_kartlari_yonetim`` modülünde gerçekleştirilir.
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


DETAIL_TABS = (
    ("identity", "Kimlik"),
    ("technical", "Teknik Öz."),
    ("requirements", "Gereksinim"),
    ("states", "Durumlar"),
    ("alternatives", "Alternatif"),
    ("location", "Ürün Ağacı"),
    ("sources", "Kaynaklar"),
)


def _clean(value: Any, fallback: str = MISSING_VALUE) -> str:
    return clean_text(value, fallback)


def _display(value: Any) -> str:
    if value is None or is_missing(value):
        return MISSING_VALUE
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_clean(item) for item in value) or MISSING_VALUE
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_display(item)}" for key, item in value.items()) or MISSING_VALUE
    return _clean(value)


def _trace_node_index(report: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        _clean(node.get("id"), ""): dict(node)
        for node in (report or {}).get("nodes", [])
        if isinstance(node, Mapping) and _clean(node.get("id"), "")
    }


def catalog_filter_options(catalog: Mapping[str, Any]) -> dict[str, list[str]]:
    items = [item for item in catalog.get("hardware_items", []) if isinstance(item, Mapping)]
    return {
        "systems": ["Tümü", *sorted({
            _clean(item.get("part_name"), "") for item in items
            if _clean(item.get("hardware_type"), "") in {"Sistem", "Alt sistem"}
            and not is_missing(item.get("part_name"))
        })],
        "manufacturers": ["Tümü", *sorted({
            _clean(item.get("manufacturer"), "") for item in items
            if not is_missing(item.get("manufacturer"))
        })],
        "working_states": ["Tümü", *WORKING_STATES, "Kullanıcı tanımlı durum"],
        "lifecycle": ["Tümü", *LIFECYCLE_STATES],
        "confidence": ["Tümü", "Yüksek (80–100)", "Orta (60–79)", "Düşük (0–59)", "Hesaplanamadı"],
    }


def product_tree_instances(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Otomatik ve manuel kartları silmeden, alternatifleri ayrı tutarak görünüm ağacı kurar."""
    cards = {
        _clean(item.get("hardware_id"), ""): item
        for item in catalog.get("hardware_items", [])
        if isinstance(item, Mapping) and _clean(item.get("hardware_id"), "")
    }
    alternative_ids = {
        _clean(value, "") for card in cards.values()
        for value in (card.get("alternative_ids") or [])
    }
    instances = [
        dict(item) for item in catalog.get("product_instances", [])
        if isinstance(item, Mapping)
        and _clean(item.get("hardware_id"), "") in cards
        and not (
            _clean(item.get("hardware_id"), "") in alternative_ids
            and is_missing(item.get("parent_instance_id"))
        )
    ]
    represented = {_clean(item.get("hardware_id"), "") for item in instances}
    for hardware_id, card in cards.items():
        if hardware_id in represented or hardware_id in alternative_ids:
            continue
        instances.append({
            "instance_id": f"CARD::{hardware_id}", "hardware_id": hardware_id,
            "parent_instance_id": MISSING_VALUE, "quantity": card.get("quantity", 1),
            "level": card.get("hardware_type", "Parça/bileşen"), "location": MISSING_VALUE,
            "reference_designator": MISSING_VALUE,
        })
    first_by_hardware: dict[str, str] = {}
    for instance in instances:
        first_by_hardware.setdefault(
            _clean(instance.get("hardware_id"), ""),
            _clean(instance.get("instance_id"), ""),
        )
    for instance in instances:
        card = cards.get(_clean(instance.get("hardware_id"), ""), {})
        parent_id = _clean(card.get("parent_id"), "")
        manual_parent = "parent_id" in (card.get("manual_fields") or [])
        if parent_id in first_by_hardware and (
            manual_parent or is_missing(instance.get("parent_instance_id"))
        ):
            instance["parent_instance_id"] = first_by_hardware[parent_id]
    return instances


class ScrollableCards(ttk.Frame):
    def __init__(self, parent: tk.Misc, palette_getter: Callable[[], Mapping[str, str]]) -> None:
        super().__init__(parent, style="HardwarePanel.TFrame")
        self.palette_getter = palette_getter
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="HardwareSurface.TFrame", padding=(8, 4))
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._update_scrollregion)
        self.canvas.bind("<Configure>", self._resize_inner)
        self.canvas.bind("<MouseWheel>", self._wheel)

    def _update_scrollregion(self, _event: tk.Event | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=max(1, event.width))

    def _wheel(self, event: tk.Event) -> str:
        delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 3, "units")
        return "break"

    def apply_palette(self) -> None:
        self.canvas.configure(background=self.palette_getter()["surface"])


class HardwareEditorDialog:
    FIELDS = (
        ("part_name", "Parça adı"), ("part_number", "Parça numarası"),
        ("manufacturer", "Üretici"), ("model_series", "Model/seri"),
        ("hardware_type", "Donanım türü"), ("system_role", "Sistem görevi"),
        ("parent_id", "Üst parça kimliği"), ("lifecycle_status", "Yaşam döngüsü"),
    )

    def __init__(self, parent: tk.Misc, values: Mapping[str, Any] | None, known_ids: Sequence[str]) -> None:
        self.result: dict[str, Any] | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Donanım Kartı Düzenle" if values else "Yeni Donanım Ekle")
        self.window.transient(parent)
        self.window.grab_set()
        self.window.resizable(True, False)
        self.vars = {key: tk.StringVar(value="" if is_missing((values or {}).get(key)) else _clean((values or {}).get(key), "")) for key, _ in self.FIELDS}
        self.vars["working_states"] = tk.StringVar(value=", ".join((values or {}).get("working_states") or ["Normal"]))
        body = ttk.Frame(self.window, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(self.FIELDS):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            if key == "hardware_type":
                widget = ttk.Combobox(body, textvariable=self.vars[key], values=PRODUCT_LEVELS, state="normal")
            elif key == "parent_id":
                widget = ttk.Combobox(body, textvariable=self.vars[key], values=[MISSING_VALUE, *known_ids], state="normal")
            elif key == "lifecycle_status":
                widget = ttk.Combobox(body, textvariable=self.vars[key], values=LIFECYCLE_STATES, state="readonly")
            else:
                widget = ttk.Entry(body, textvariable=self.vars[key])
            widget.grid(row=row, column=1, sticky="ew", pady=5)
        row = len(self.FIELDS)
        ttk.Label(body, text="Çalışma durumları").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        ttk.Entry(body, textvariable=self.vars["working_states"]).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(body, text="Virgülle ayırın; kullanıcı tanımlı durum eklenebilir.", style="HardwareMuted.TLabel").grid(row=row + 1, column=1, sticky="w")
        actions = ttk.Frame(body)
        actions.grid(row=row + 2, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(actions, text="İptal", command=self.window.destroy).pack(side="right")
        ttk.Button(actions, text="Kaydet", style="primary.TButton", command=self._save).pack(side="right", padx=(0, 8))
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.wait_visibility()
        self.window.focus_force()
        self.window.wait_window()

    def _save(self) -> None:
        name = _clean(self.vars["part_name"].get(), "")
        if not name:
            messagebox.showwarning("Eksik Bilgi", "Parça adı boş bırakılamaz.", parent=self.window)
            return
        self.result = {key: variable.get().strip() or MISSING_VALUE for key, variable in self.vars.items() if key != "working_states"}
        self.result["working_states"] = [
            item.strip() for item in self.vars["working_states"].get().split(",") if item.strip()
        ] or ["Normal"]
        self.window.destroy()


class AlternativeDialog:
    def __init__(self, parent: tk.Misc, choices: Mapping[str, str]) -> None:
        self.result: dict[str, str] | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Alternatif Parça Bağla")
        self.window.transient(parent)
        self.window.grab_set()
        self.choice = tk.StringVar(value=next(iter(choices), ""))
        self.reason = tk.StringVar()
        self.status = tk.StringVar(value="İncelenmedi")
        self.choices = dict(choices)
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Alternatif parça").grid(row=0, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.choice, values=list(choices), state="readonly", width=42).grid(row=1, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(frame, text="Alternatif olma nedeni").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.reason).grid(row=3, column=0, sticky="ew", pady=(3, 10))
        ttk.Label(frame, text="Uyum durumu").grid(row=4, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.status, values=("İncelenmedi", "Veri eksik", "Koşullu uyumlu", "Uyumlu değil"), state="readonly").grid(row=5, column=0, sticky="ew", pady=(3, 12))
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, sticky="e")
        ttk.Button(buttons, text="İptal", command=self.window.destroy).pack(side="right")
        ttk.Button(buttons, text="Bağla", style="primary.TButton", command=self._save).pack(side="right", padx=(0, 8))
        self.window.wait_visibility(); self.window.focus_force(); self.window.wait_window()

    def _save(self) -> None:
        if not self.choice.get():
            return
        self.result = {
            "hardware_id": self.choices[self.choice.get()],
            "reason": self.reason.get().strip() or MISSING_VALUE,
            "status": self.status.get(),
        }
        self.window.destroy()


class HardwareCardsWorkspace:
    """Ürün ağacı, katalog ve datasheet ayrıntılarını senkronize eder."""

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

    def _refresh_filters(self) -> None:
        options = catalog_filter_options(self.catalog)
        for combo, key, variable, prefix in zip(
            self.filter_combos,
            ("systems", "manufacturers", "working_states", "lifecycle", "confidence"),
            (self.system_filter, self.manufacturer_filter, self.working_filter, self.lifecycle_filter, self.confidence_filter),
            ("Sistem", "Üretici", "Çalışma", "Yaşam", "Güven"),
        ):
            display_values = [f"{prefix}: {value}" for value in options[key]]
            current = self._filter_value(variable.get())
            combo.configure(values=display_values)
            variable.set(
                f"{prefix}: {current}" if current in options[key]
                else f"{prefix}: Tümü"
            )

    @staticmethod
    def _filter_value(value: str) -> str:
        return value.split(":", 1)[1].strip() if ":" in value else value

    def _search_focus_in(self, _event: tk.Event | None = None) -> None:
        if self.search_var.get() == self.search_placeholder:
            self.search_var.set("")

    def _search_focus_out(self, _event: tk.Event | None = None) -> None:
        if not self.search_var.get().strip():
            self.search_var.set(self.search_placeholder)

    def _focus_search(self, _event: tk.Event | None = None) -> str:
        self.search_entry.focus_set(); self.search_entry.selection_range(0, "end")
        return "break"

    def _restore_preferences(self, project_name: str) -> None:
        if self._preferences_loaded_project == project_name:
            return
        prefs = dict(management.DEFAULT_UI_PREFERENCES)
        prefs.update(self.overrides.get("ui_preferences") or {})
        self.view_mode.set(prefs["view_mode"] if prefs["view_mode"] in {"Kart", "Kompakt Liste", "Ürün Ağacı"} else "Kart")
        self.system_filter.set(f"Sistem: {prefs['system_filter']}")
        self.manufacturer_filter.set(f"Üretici: {prefs['manufacturer_filter']}")
        self.working_filter.set(f"Çalışma: {prefs['working_filter']}")
        self.lifecycle_filter.set(f"Yaşam: {prefs['lifecycle_filter']}")
        self.confidence_filter.set(f"Güven: {prefs['confidence_filter']}")
        self.sort_var.set(prefs["sort_by"])
        self.group_var.set(prefs["group_by"])
        self.impacted_only.set(bool(prefs["impacted_only"]))
        self.no_alternative_only.set(bool(prefs["no_alternative_only"]))
        self.no_datasheet_only.set(bool(prefs["no_datasheet_only"]))
        self._preferences_loaded_project = project_name

    def _persist_preferences(self) -> None:
        if not self.base_catalog:
            return
        management.update_ui_preferences(
            self.overrides,
            view_mode=self.view_mode.get(),
            system_filter=self._filter_value(self.system_filter.get()),
            manufacturer_filter=self._filter_value(self.manufacturer_filter.get()),
            working_filter=self._filter_value(self.working_filter.get()),
            lifecycle_filter=self._filter_value(self.lifecycle_filter.get()),
            confidence_filter=self._filter_value(self.confidence_filter.get()),
            sort_by=self.sort_var.get(), group_by=self.group_var.get(),
            impacted_only=self.impacted_only.get(),
            no_alternative_only=self.no_alternative_only.get(),
            no_datasheet_only=self.no_datasheet_only.get(),
        )
        try:
            project_name = self.project_name_getter() or self.catalog.get("project_name") or "Proje"
            management.save_overrides(project_name, self.overrides, self.base_catalog)
        except Exception as error:
            self.status_var.set(f"Görünüm tercihleri kaydedilemedi: {error}")

    def _filtered_items(self) -> list[dict[str, Any]]:
        items = management.filter_cards(
            self.catalog,
            search="" if self.search_var.get() == self.search_placeholder else self.search_var.get(),
            system_filter=self._filter_value(self.system_filter.get()),
            manufacturer=self._filter_value(self.manufacturer_filter.get()),
            working_state=self._filter_value(self.working_filter.get()),
            lifecycle_status=self._filter_value(self.lifecycle_filter.get()),
            confidence=self._filter_value(self.confidence_filter.get()),
            impacted_only=self.impacted_only.get(),
            no_alternative_only=self.no_alternative_only.get(),
            no_datasheet_only=self.no_datasheet_only.get(),
            impacted_ids=self.impact_badges,
            sort_by=self.sort_var.get(),
        )
        if not self._quality_filter:
            return items
        conflicts = {
            _clean(item.get("hardware_id"), "") for item in self.catalog.get("conflicts", [])
            if isinstance(item, Mapping)
        } | {
            _clean(item.get("hardware_id"), "") for item in self.override_conflicts
            if isinstance(item, Mapping)
        }
        result = []
        for item in items:
            hardware_id = _clean(item.get("hardware_id"), "")
            if self._quality_filter == "missing_image" and management._has_usable_image(item):
                continue
            if self._quality_filter == "missing_requirements" and item.get("requirement_ids"):
                continue
            if self._quality_filter == "missing_tests" and (not item.get("requirement_ids") or item.get("test_ids")):
                continue
            if self._quality_filter == "critical_without_alternative" and (
                "Kritik etki" not in self.impact_badges.get(hardware_id, []) or item.get("alternative_ids")
            ):
                continue
            if self._quality_filter == "conflicts" and hardware_id not in conflicts:
                continue
            result.append(item)
        return result

    def _filters_changed(self, _event: tk.Event | None = None) -> None:
        if self._filter_after_id:
            try: self.window.after_cancel(self._filter_after_id)
            except tk.TclError: pass
        self._filter_after_id = self.window.after(90, self._apply_filters_changed)

    def _apply_filters_changed(self) -> None:
        self._filter_after_id = None; self._card_page = 0
        self._render_tree(); self._render_catalog_view(); self._persist_preferences()

    def _view_changed(self, _event: tk.Event | None = None) -> None:
        self._card_page = 0; self._render_catalog_view(); self._persist_preferences()

    def _clear_filters(self) -> None:
        self.search_var.set(self.search_placeholder)
        self.system_filter.set("Sistem: Tümü"); self.manufacturer_filter.set("Üretici: Tümü")
        self.working_filter.set("Çalışma: Tümü"); self.lifecycle_filter.set("Yaşam: Tümü")
        self.confidence_filter.set("Güven: Tümü")
        self.impacted_only.set(False); self.no_alternative_only.set(False); self.no_datasheet_only.set(False)
        self._quality_filter = ""; self._apply_filters_changed()

    def _quality_filter_selected(self, key: str) -> None:
        if key == "total":
            self._clear_filters(); return
        if key == "high_confidence":
            self.confidence_filter.set("Güven: Yüksek (80–100)"); self._quality_filter = ""
        elif key == "low_confidence":
            self.confidence_filter.set("Güven: Düşük (0–59)"); self._quality_filter = ""
        elif key == "missing_datasheet":
            self.no_datasheet_only.set(True); self._quality_filter = ""
        else:
            self._quality_filter = "" if self._quality_filter == key else key
        self._apply_filters_changed()

    def _render_all(self) -> None:
        self.impact_badges = management.build_impact_badges(self.catalog, self.simulation_result)
        self._render_tree(); self._render_catalog_view(); self._render_detail(); self._render_quality_strip()

    def _card_index(self) -> dict[str, dict[str, Any]]:
        return {
            _clean(item.get("hardware_id"), ""): item
            for item in self.catalog.get("hardware_items", []) if isinstance(item, dict)
        }

    def _render_tree(self) -> None:
        self.product_tree.delete(*self.product_tree.get_children())
        by_id = self._card_index()
        visible = {_clean(item.get("hardware_id"), "") for item in self._filtered_items()}
        if not by_id:
            self.product_tree.insert("", "end", text="Belge üretimi bekleniyor", values=("—", "Veri yok", "—", "—"))
            return
        instances = product_tree_instances(self.catalog)
        instance_map = {_clean(item.get("instance_id"), ""): item for item in instances}
        children: dict[str, list[Mapping[str, Any]]] = {}
        roots = []
        for instance in instances:
            parent = _clean(instance.get("parent_instance_id"), "")
            if parent and not is_missing(parent) and parent in instance_map:
                children.setdefault(parent, []).append(instance)
            else:
                roots.append(instance)

        root_id = "ROOT::CATALOG"
        self.product_tree.insert("", "end", iid=root_id, text=self.catalog.get("project_name") or "Sistem / Katalog", values=("", "", "", ""), open=True)
        visited: set[str] = set()

        def insert(instance: Mapping[str, Any], parent_tree_id: str) -> None:
            instance_id = _clean(instance.get("instance_id"), "")
            hardware_id = _clean(instance.get("hardware_id"), "")
            if not instance_id or instance_id in visited or hardware_id not in by_id:
                return
            visited.add(instance_id)
            card = by_id[hardware_id]
            if visible and hardware_id not in visible and not any(_clean(child.get("hardware_id"), "") in visible for child in children.get(instance_id, [])):
                return
            score = card.get("confidence_score")
            score_text = "—" if score is None else f"{float(score):.0f}" if str(score).replace('.', '', 1).isdigit() else "—"
            badges = self.impact_badges.get(hardware_id, [])
            source_missing = card.get("source_presence_status") == "Kaynaktan artık bulunamadı"
            tree_id = f"INST::{instance_id}"
            self.product_tree.insert(
                parent_tree_id, "end", iid=tree_id, text=_clean(card.get("part_name")),
                values=(instance.get("quantity", card.get("quantity", 1)), _clean(card.get("lifecycle_status")), score_text, "!" if badges else ""),
                tags=("source_missing" if source_missing else "impact" if badges else "normal",), open=True,
            )
            for child in sorted(children.get(instance_id, []), key=lambda value: _clean(by_id.get(_clean(value.get("hardware_id"), ""), {}).get("part_name")).casefold()):
                insert(child, tree_id)
            alternatives = [item for item in card.get("alternative_ids", []) if item in by_id]
            if alternatives:
                branch = f"ALTBR::{instance_id}"
                self.product_tree.insert(tree_id, "end", iid=branch, text="Alternatifler", values=("", "Ayrı ilişki", "", ""), tags=("alternative_branch",))
                for alternative_id in alternatives:
                    alternative = by_id[alternative_id]
                    self.product_tree.insert(branch, "end", iid=f"ALT::{instance_id}::{alternative_id}", text=_clean(alternative.get("part_name")), values=("—", _clean(alternative.get("lifecycle_status")), f"{float(alternative.get('confidence_score', 0)):.0f}", ""), tags=("alternative",))

        for root in sorted(roots, key=lambda value: _clean(by_id.get(_clean(value.get("hardware_id"), ""), {}).get("part_name")).casefold()):
            insert(root, root_id)
        for instance in instances:
            if _clean(instance.get("instance_id"), "") not in visited:
                insert(instance, root_id)
        self.product_tree.tag_configure("impact", foreground="#B42318")
        self.product_tree.tag_configure("source_missing", foreground="#9A6700")
        self.product_tree.tag_configure("alternative", foreground=self.palette_getter()["accent"])
        self.product_tree.tag_configure("alternative_branch", foreground=self.palette_getter()["muted"])

    def _tree_hardware_id(self, tree_id: str) -> str:
        if tree_id.startswith("ALT::"):
            return tree_id.split("::", 2)[-1]
        if not tree_id.startswith("INST::"):
            return ""
        instance_id = tree_id[6:]
        for instance in self.catalog.get("product_instances", []):
            if _clean(instance.get("instance_id"), "") == instance_id:
                return _clean(instance.get("hardware_id"), "")
        if instance_id.startswith("CARD::"):
            return instance_id[6:]
        return ""

    def _tree_selected(self, _event: tk.Event | None = None) -> None:
        if self._syncing_tree_selection:
            return
        selection = self.product_tree.selection()
        if selection:
            hardware_id = self._tree_hardware_id(selection[0])
            # ``selection_set`` bir <<TreeviewSelect>> olayı daha kuyruğa
            # bırakır. Aynı donanımı tekrar işlemek sonsuz seçim döngüsüne ve
            # gerçek Tk mainloop'unda pencerenin donmasına neden oluyordu.
            if hardware_id and hardware_id != self.selected_id:
                self.select_card(hardware_id, scroll_cards=True)

    def _tree_open_detail(self, event: tk.Event | None = None) -> None:
        tree_id = self.product_tree.identify_row(event.y) if event else ""
        hardware_id = self._tree_hardware_id(tree_id)
        if hardware_id:
            self.open_detailed_review(hardware_id)

    def _tree_context_menu(self, event: tk.Event) -> str:
        tree_id = self.product_tree.identify_row(event.y)
        hardware_id = self._tree_hardware_id(tree_id)
        if not hardware_id:
            return "break"
        self.product_tree.selection_set(tree_id)
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(
            label="Detaylı İncele",
            command=lambda: self.open_detailed_review(hardware_id),
        )
        menu.add_command(label="Düzenle", command=lambda: (self.select_card(hardware_id), self._edit_item()))
        menu.add_command(label="Datasheet Yükle", command=lambda: (self.select_card(hardware_id), self._load_datasheet()))
        menu.add_command(
            label="Etki Analizini Başlat",
            command=lambda: self._send_to_impact(hardware_id),
        )
        menu.add_command(label="Karşılaştırmaya Ekle / Çıkar", command=lambda: self._toggle_compare(hardware_id))
        menu.add_separator()
        menu.add_command(label="Arşivle (silmez)", command=lambda: self._archive_item(hardware_id))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _render_quality_strip(self) -> None:
        summary = management.catalog_quality_summary(
            self.catalog, impacted_ids={
                hardware_id for hardware_id, badges in self.impact_badges.items()
                if "Kritik etki" in badges
            },
        )
        labels = {
            "total": "Toplam", "high_confidence": "Yüksek güven",
            "low_confidence": "Düşük güven", "missing_datasheet": "Datasheet yok",
            "missing_image": "Görsel yok", "missing_requirements": "Gereksinim yok",
            "missing_tests": "Test yok", "critical_without_alternative": "Kritik / alternatifsiz",
            "conflicts": "Çelişki",
        }
        for key, button in self.quality_buttons.items():
            button.configure(text=f"{labels[key]}  {summary.get(key, 0)}")

    def _render_catalog_view(self) -> None:
        self.cards.grid_remove(); self.compact_frame.grid_remove(); self.catalog_tree_frame.grid_remove()
        mode = self.view_mode.get()
        self._apply_catalog_panel_span(mode)
        if mode == "Kompakt Liste":
            self.compact_frame.grid(row=1, column=0, sticky="nsew")
            self._render_compact_list()
        elif mode == "Ürün Ağacı":
            self.catalog_tree_frame.grid(row=1, column=0, sticky="nsew")
            self._render_catalog_tree_view()
        else:
            self.cards.grid(row=1, column=0, sticky="nsew")
            self._render_cards()
        card_mode = mode == "Kart"
        self.prev_page_button.configure(state="normal" if card_mode and self._card_page > 0 else "disabled")
        self.next_page_button.configure(state="normal" if card_mode and self._has_next_page() else "disabled")
        if not card_mode:
            self.page_var.set("Tüm eşleşmeler")

    def _apply_catalog_panel_span(self, mode: str | None = None) -> None:
        """Ürün ağacı görünümünde aynı ağacı iki kez yan yana göstermeyi önler."""
        mode = mode or self.view_mode.get()
        if mode == "Ürün Ağacı":
            self.tree_panel.grid_remove()
            self.catalog_panel.grid(
                row=0, column=0, columnspan=2, sticky="nsew",
                padx=(0, 8 if self._wide_layout else 0),
            )
            return
        self.tree_panel.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 8))
        self.catalog_panel.grid(
            row=0, column=1, columnspan=1, sticky="nsew",
            padx=(0, 8 if self._wide_layout else 0),
        )

    def _has_next_page(self) -> bool:
        return (self._card_page + 1) * self._card_page_size < len(self._filtered_items())

    def _change_page(self, step: int) -> None:
        items = self._filtered_items()
        pages = max(1, (len(items) + self._card_page_size - 1) // self._card_page_size)
        self._card_page = max(0, min(pages - 1, self._card_page + step))
        self._render_cards(); self.cards.canvas.yview_moveto(0)

    def _group_label(self, item: Mapping[str, Any]) -> str:
        if self.group_var.get() == "Gruplama: Üretici":
            return _display(item.get("manufacturer"))
        if self.group_var.get() == "Gruplama: Alt sistem":
            by_id = self._card_index(); current = item; visited: set[str] = set()
            while isinstance(current, Mapping):
                hardware_id = _clean(current.get("hardware_id"), "")
                if hardware_id in visited: break
                visited.add(hardware_id)
                if _clean(current.get("hardware_type"), "") in {"Alt sistem", "Sistem"}:
                    return _display(current.get("part_name"))
                current = by_id.get(_clean(current.get("parent_id"), ""))
            return "Üst sistem bulunamadı"
        return ""

    def _render_compact_list(self) -> None:
        self.compact_list.delete(*self.compact_list.get_children())
        items = self._filtered_items(); total = len(self.catalog.get("hardware_items", []))
        self.count_var.set(f"{len(items)} filtrelendi / {total} toplam")
        groups: dict[str, str] = {}
        for item in items:
            parent = ""
            group = self._group_label(item)
            if group:
                parent = groups.setdefault(group, f"GROUP::{len(groups)}")
                if not self.compact_list.exists(parent):
                    self.compact_list.insert("", "end", iid=parent, text=group, values=("",) * 8, open=True, tags=("group",))
            hardware_id = _clean(item.get("hardware_id"), "")
            score = item.get("confidence_score")
            try: score_text = f"{float(score):.0f}"
            except (TypeError, ValueError): score_text = "—"
            self.compact_list.insert(parent, "end", iid=f"LIST::{hardware_id}", text=_display(item.get("part_name")), values=(
                _display(item.get("part_number")), _display(item.get("manufacturer")),
                _display(item.get("system_role")), _display(item.get("lifecycle_status")), score_text,
                len(item.get("requirement_ids") or []), len(item.get("test_ids") or []), len(item.get("alternative_ids") or []),
            ))
        selected = [f"LIST::{value}" for value in self._compare_selection if self.compact_list.exists(f"LIST::{value}")]
        if selected: self.compact_list.selection_set(selected)

    def _render_catalog_tree_view(self) -> None:
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        self._catalog_tree_hardware: dict[str, str] = {}
        visible = {_clean(item.get("hardware_id"), "") for item in self._filtered_items()}
        by_id = self._card_index(); instances = product_tree_instances(self.catalog)
        instance_by_id = {_clean(item.get("instance_id"), ""): item for item in instances}
        children: dict[str, list[Mapping[str, Any]]] = {}
        for instance in instances:
            children.setdefault(_clean(instance.get("parent_instance_id"), ""), []).append(instance)

        def insert_branch(parent: str, parent_instance: str) -> None:
            for instance in sorted(children.get(parent_instance, []), key=lambda row: _clean(by_id.get(_clean(row.get("hardware_id"), ""), {}).get("part_name")).casefold()):
                hardware_id = _clean(instance.get("hardware_id"), "")
                item = by_id.get(hardware_id, {})
                instance_id = _clean(instance.get("instance_id"), hardware_id)
                tree_id = f"CAT::{instance_id}"
                if hardware_id not in visible and not children.get(instance_id):
                    continue
                score = item.get("confidence_score")
                try: score_text = f"{float(score):.0f}"
                except (TypeError, ValueError): score_text = "—"
                self.catalog_tree.insert(parent, "end", iid=tree_id, text=_display(item.get("part_name")), values=(
                    instance.get("quantity", item.get("quantity", 1)), _display(item.get("part_number")),
                    _display(item.get("manufacturer")), _display(item.get("lifecycle_status")), score_text,
                    f"{len(item.get('requirement_ids') or [])} → {len(item.get('test_ids') or [])} → {len(item.get('alternative_ids') or [])}",
                ), open=True)
                self._catalog_tree_hardware[tree_id] = hardware_id
                insert_branch(tree_id, instance_id)

        roots = [key for key in children if not key or is_missing(key) or key not in instance_by_id]
        for root_key in roots or [""]:
            insert_branch("", root_key)
        self.count_var.set(f"{len(visible)} filtrelendi / {len(by_id)} toplam")

    def _compact_selected(self, _event: tk.Event | None = None) -> None:
        ids = [value.split("::", 1)[1] for value in self.compact_list.selection() if value.startswith("LIST::")]
        if len(ids) > 4:
            ids = ids[:4]; self.compact_list.selection_set([f"LIST::{value}" for value in ids])
            self.status_var.set("Karşılaştırmada en fazla 4 donanım seçilebilir.")
        self._compare_selection = set(ids); self._update_compare_controls()
        if len(ids) == 1: self.select_card(ids[0])

    def _compact_open(self, _event: tk.Event | None = None) -> str:
        selection = [value for value in self.compact_list.selection() if value.startswith("LIST::")]
        if selection: self.open_detailed_review(selection[-1].split("::", 1)[1])
        return "break"

    def _compact_context_menu(self, event: tk.Event) -> str:
        row = self.compact_list.identify_row(event.y)
        if not row.startswith("LIST::"): return "break"
        hardware_id = row.split("::", 1)[1]; self.compact_list.selection_set(row)
        return self._card_context_menu(event, hardware_id)

    def _catalog_tree_selected(self, _event: tk.Event | None = None) -> None:
        selection = self.catalog_tree.selection()
        if selection:
            hardware_id = getattr(self, "_catalog_tree_hardware", {}).get(selection[0], "")
            if hardware_id: self.select_card(hardware_id)

    def _catalog_tree_open(self, _event: tk.Event | None = None) -> str:
        selection = self.catalog_tree.selection()
        if selection:
            hardware_id = getattr(self, "_catalog_tree_hardware", {}).get(selection[0], "")
            if hardware_id: self.open_detailed_review(hardware_id)
        return "break"

    def _render_cards(self) -> None:
        for child in self.cards.inner.winfo_children():
            child.destroy()
        self._photo_refs.clear()
        self._card_widgets.clear()
        items = self._filtered_items()
        total = len(self.catalog.get("hardware_items", []))
        pages = max(1, (len(items) + self._card_page_size - 1) // self._card_page_size)
        self._card_page = min(self._card_page, pages - 1)
        start = self._card_page * self._card_page_size
        visible_items = items[start:start + self._card_page_size]
        shown = "0" if not items else f"{start + 1}–{start + len(visible_items)}"
        self.count_var.set(f"{len(items)} filtrelendi / {total} toplam · {shown} gösteriliyor")
        self.page_var.set(f"Sayfa {self._card_page + 1}/{pages}")
        self.prev_page_button.configure(state="normal" if self._card_page > 0 else "disabled")
        self.next_page_button.configure(state="normal" if self._card_page + 1 < pages else "disabled")
        if not items:
            empty = ttk.Frame(self.cards.inner, style="HardwareSurface.TFrame", padding=32)
            empty.pack(fill="both", expand=True)
            message = "Arama ve filtrelerle eşleşen donanım yok." if self.catalog.get("hardware_items") else "Henüz donanım kartı yok.\nÖnce belgeleri üretin; katalog izlenebilirlikten sonra otomatik hazırlanır."
            ttk.Label(empty, text=message, style="HardwareEmpty.TLabel", justify="center").pack(expand=True, pady=30)
            if not self.catalog.get("hardware_items"):
                ttk.Button(empty, text="Örnek Donanım Ağacı Yükle", command=self._load_sample).pack()
            return
        last_group = None
        for item in visible_items:
            group = self._group_label(item)
            if group and group != last_group:
                ttk.Label(
                    self.cards.inner, text=group.upper(), style="HardwareGroup.TLabel",
                ).pack(fill="x", padx=2, pady=(8 if last_group is not None else 2, 2))
                last_group = group
            self._build_card(item)

    def _build_card(self, item: Mapping[str, Any]) -> None:
        hardware_id = _clean(item.get("hardware_id"), "")
        selected = hardware_id == self.selected_id
        badges = list(self.impact_badges.get(hardware_id, []))
        source_missing = item.get("source_presence_status") == "Kaynaktan artık bulunamadı"
        if source_missing:
            badges.append("Kaynaktan artık bulunamadı")
        accent = self._card_accent(hardware_id, selected)
        outer = tk.Frame(self.cards.inner, background=accent, height=190)
        outer.pack(fill="x", pady=4)
        outer.pack_propagate(False)
        card = ttk.Frame(outer, style="HardwareCardSelected.TFrame" if selected else "HardwareCard.TFrame", padding=(9, 8))
        card.pack(fill="both", expand=True, padx=(3, 1), pady=1)
        self._card_widgets[hardware_id] = (outer, card)
        card.columnconfigure(1, weight=1); card.rowconfigure(2, weight=1)
        image = self._make_card_image(card, item)
        image.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 10))
        title = ttk.Label(card, text=_clean(item.get("part_name")), style="HardwareCardTitle.TLabel", cursor="hand2")
        title.grid(row=0, column=1, sticky="w")
        meta = ttk.Label(card, text=f"PN  {_display(item.get('part_number'))}   ·   Üretici  {_display(item.get('manufacturer'))}", style="HardwareMono.TLabel")
        meta.grid(row=1, column=1, sticky="w", pady=(2, 0))
        role = ttk.Label(card, text=f"Görev: {_display(item.get('system_role'))}", style="HardwareCardText.TLabel", wraplength=270, justify="left")
        role.grid(row=2, column=1, sticky="nw", pady=(3, 0))
        facts = ttk.Frame(card, style="HardwareCard.TFrame")
        facts.grid(row=0, column=2, rowspan=3, sticky="ne", padx=(10, 0))
        td = item.get("technical_data") or {}
        temperature_values = [td.get("operating_temperature_min"), td.get("operating_temperature_max")]
        temp = (
            MISSING_VALUE if all(is_missing(value) for value in temperature_values)
            else f"{_display(temperature_values[0])}…{_display(temperature_values[1])} {_display(td.get('temperature_unit'))}"
        )
        dimension_values = [td.get(key) for key in ("length", "width", "height")]
        dimensions = (
            MISSING_VALUE if all(is_missing(value) for value in dimension_values)
            else " × ".join(_display(value) for value in dimension_values)
            + f" {_display(td.get('dimension_unit'))}"
        )
        score = item.get("confidence_score")
        score_text = "Hesaplanamadı" if score is None else f"{float(score):.0f}/100"
        for text in (
            f"Çalışma: {temp}", f"Boyut: {dimensions}",
            f"Durum: {_display(item.get('lifecycle_status'))}", f"Güven: {score_text}",
            f"Gereksinim: {len(item.get('requirement_ids') or [])}   Alternatif: {len(item.get('alternative_ids') or [])}",
        ):
            ttk.Label(facts, text=text, style="HardwareMono.TLabel").pack(anchor="e")
        trace = ttk.Frame(card, style="HardwareTraceBar.TFrame", padding=(4, 2))
        trace.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        trace.columnconfigure((0, 2, 4, 6, 8), weight=1)
        trace_items = (
            ("Üst Sistem", "location"), ("Parça", "identity"),
            (f"Gereksinim {len(item.get('requirement_ids') or [])}", "requirements"),
            (f"Test {len(item.get('test_ids') or [])}", "requirements"), (f"Alternatif {len(item.get('alternative_ids') or [])}", "alternatives"),
        )
        for index, (text, tab) in enumerate(trace_items):
            ttk.Button(trace, text=text, style="HardwareTrace.TButton", command=lambda key=tab, hid=hardware_id: self._trace_click(hid, key)).grid(row=0, column=index * 2, sticky="ew")
            if index < 4:
                ttk.Label(trace, text="→", style="HardwareTraceArrow.TLabel").grid(row=0, column=index * 2 + 1, padx=3)
        if badges:
            ttk.Label(card, text="  ·  ".join(badges), style="HardwareImpact.TLabel").grid(row=4, column=0, sticky="w", pady=(3, 0))
        compare_text = "Karşılaştırmadan Çıkar" if hardware_id in self._compare_selection else "Karşılaştırmaya Ekle"
        ttk.Button(
            card, text=compare_text, style="HardwareTrace.TButton",
            command=lambda hid=hardware_id: self._toggle_compare(hid),
        ).grid(row=4, column=1, sticky="e", padx=(4, 4), pady=(3, 0))
        impact_button = ttk.Button(card, text="Etki Analizi", style="primary.Outline.TButton", command=lambda hid=hardware_id: self._send_to_impact(hid))
        impact_button.grid(row=4, column=2, sticky="e", pady=(3, 0))
        for widget in (outer, card, image, title, meta, role, facts):
            widget.bind("<Button-1>", lambda _event, hid=hardware_id: self.open_detailed_review(hid))
            widget.bind("<Double-1>", lambda _event, hid=hardware_id: self.open_detailed_review(hid))
            widget.bind("<Button-3>", lambda event, hid=hardware_id: self._card_context_menu(event, hid))
            widget.bind("<Button-2>", lambda event, hid=hardware_id: self._card_context_menu(event, hid))

    def _card_context_menu(self, event: tk.Event, hardware_id: str) -> str:
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(label="Detaylı İncele", command=lambda: self.open_detailed_review(hardware_id))
        menu.add_command(label="Düzenle", command=lambda: (self.select_card(hardware_id), self._edit_item()))
        menu.add_command(label="Datasheet Yükle", command=lambda: (self.select_card(hardware_id), self._load_datasheet()))
        menu.add_command(label="Etki Analizini Başlat", command=lambda: self._send_to_impact(hardware_id))
        menu.add_command(label="Karşılaştırmaya Ekle / Çıkar", command=lambda: self._toggle_compare(hardware_id))
        menu.add_separator()
        menu.add_command(label="Arşivle (silmez)", command=lambda: self._archive_item(hardware_id))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _toggle_compare(self, hardware_id: str) -> None:
        if hardware_id in self._compare_selection:
            self._compare_selection.remove(hardware_id)
        elif len(self._compare_selection) >= 4:
            messagebox.showinfo(
                "Donanım Karşılaştırma",
                "Aynı anda en fazla 4 donanım karşılaştırılabilir. Önce mevcut seçimlerden birini çıkarın.",
                parent=self.window,
            )
            return
        else:
            self._compare_selection.add(hardware_id)
        self._update_compare_controls(); self._render_catalog_view()

    def _update_compare_controls(self) -> None:
        count = len(self._compare_selection)
        self.compare_var.set(f"Karşılaştırma: {count}/4")
        self.compare_button.configure(state="normal" if 2 <= count <= 4 else "disabled")

    def _open_comparison(self) -> None:
        if not 2 <= len(self._compare_selection) <= 4:
            messagebox.showinfo(
                "Donanım Karşılaştırma", "Karşılaştırmak için 2 ile 4 arasında donanım seçin.",
                parent=self.window,
            )
            return
        ordered = [
            _clean(item.get("hardware_id"), "") for item in self.catalog.get("hardware_items", [])
            if _clean(item.get("hardware_id"), "") in self._compare_selection
        ]
        try:
            if self._comparison_workspace and self._comparison_workspace.exists:
                self._comparison_workspace.close()
            self._comparison_workspace = HardwareComparisonWorkspace(
                self.window, self.catalog, ordered, self._traceability_report(),
                self.palette_getter, self.impact_callback,
            )
        except Exception as error:
            messagebox.showerror(
                "Donanım Karşılaştırma", f"Karşılaştırma ekranı açılamadı:\n{error}",
                parent=self.window,
            )

    def _archive_item(self, hardware_id: str) -> None:
        item = self._card_index().get(hardware_id, {})
        if not item:
            return
        if not messagebox.askyesno(
            "Donanımı Arşivle",
            f"{_display(item.get('part_name'))} silinmeyecek; yaşam döngüsü 'Kullanımdan kaldırıldı' olarak işaretlenecek. Devam edilsin mi?",
            parent=self.window,
        ):
            return
        management.archive_hardware_item(self.overrides, hardware_id, self.base_catalog)
        self._persist_and_refresh()

    def _undo_last_change(self) -> str:
        record = management.undo_last_manual_change(self.overrides, self.base_catalog)
        if not record:
            self.status_var.set("Geri alınabilecek manuel alan değişikliği bulunamadı.")
            return "break"
        self._persist_and_refresh()
        self.status_var.set(
            f"Son manuel değişiklik geri alındı: {record.get('hardware_id')} · {record.get('field')}"
        )
        return "break"

    def _make_card_image(self, parent: tk.Misc, item: Mapping[str, Any]) -> tk.Widget:
        holder = ttk.Frame(parent, style="HardwareCard.TFrame")
        path = _clean(item.get("image_path"), "")
        if path and path != PLACEHOLDER_IMAGE and Path(path).is_file() and Image and ImageTk:
            try:
                image = Image.open(path).convert("RGBA")
                image.thumbnail((72, 62), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self._photo_refs.append(photo)
                ttk.Label(holder, image=photo, style="HardwareImage.TLabel").pack()
                if item.get("image_is_generated"):
                    ttk.Label(
                        holder, text="AI İLLÜSTRASYON",
                        style="HardwareVisualBadge.TLabel",
                    ).pack(pady=(2, 0))
                return holder
            except Exception:
                pass
        canvas = tk.Canvas(holder, width=72, height=62, highlightthickness=1)
        palette = self.palette_getter()
        canvas.configure(background=palette["surface"], highlightbackground="#D8DEE5")
        canvas.create_polygon(
            36, 13, 51, 21, 51, 40, 36, 49, 21, 40, 21, 21,
            outline=palette["muted"], fill="", width=2,
        )
        canvas.create_oval(29, 24, 43, 38, outline=palette["accent"], width=2)
        canvas.create_text(
            36, 56, text="GÖRSEL", fill=palette["muted"],
            font=("Consolas", 6, "bold"),
        )
        canvas.pack()
        return holder

    def _card_accent(self, hardware_id: str, selected: bool | None = None) -> str:
        item = self._card_index().get(hardware_id, {})
        if "Kritik etki" in self.impact_badges.get(hardware_id, []):
            return "#B42318"
        if item.get("source_presence_status") == "Kaynaktan artık bulunamadı":
            return "#D97706"
        is_selected = hardware_id == self.selected_id if selected is None else selected
        return self.palette_getter()["accent"] if is_selected else "#D8DEE5"

    def _update_card_selection(self, hardware_id: str) -> None:
        widgets = self._card_widgets.get(hardware_id)
        if not widgets:
            return
        outer, card = widgets
        selected = hardware_id == self.selected_id
        outer.configure(background=self._card_accent(hardware_id, selected))
        card.configure(
            style="HardwareCardSelected.TFrame" if selected else "HardwareCard.TFrame"
        )

    def _trace_click(self, hardware_id: str, tab: str) -> None:
        tab_map = {
            "identity": "overview", "location": "connections",
            "requirements": "requirements", "alternatives": "alternatives",
        }
        self.open_detailed_review(hardware_id, tab_map.get(tab, "overview"))

    def _old_alternative_open(self, _event: tk.Event | None = None) -> None:
        selection = self._detail_trees["alternatives"].selection()
        if selection and selection[0].startswith("ALTDETAIL::"):
            self.open_detailed_review(selection[0].split("::", 1)[1], "overview")

    def select_card(self, hardware_id: str, scroll_cards: bool = False) -> None:
        if hardware_id not in self._card_index():
            return
        previous_id = self.selected_id
        self.selected_id = hardware_id
        if previous_id != hardware_id:
            self._update_card_selection(previous_id)
            self._update_card_selection(hardware_id)
        # Seçim sırasında tüm katalog kartlarını silip yeniden kurmak Tk ana
        # döngüsünü durduruyordu. Yalnızca ayrıntı paneli güncellenir.
        self._render_detail()
        self._syncing_tree_selection = True
        try:
            for tree_id in self.product_tree.get_children(""):
                if self._select_tree_recursive(tree_id, hardware_id):
                    break
        finally:
            self._syncing_tree_selection = False
        if scroll_cards:
            self.cards.canvas.yview_moveto(0)

    def open_detailed_review(
        self, hardware_reference: str, initial_tab: str | None = None,
    ) -> None:
        """Kimlik veya parça adıyla aynı geniş ayrıntı çalışma alanını açar."""
        reference = _clean(hardware_reference, "")
        by_id = self._card_index()
        hardware_id = reference if reference in by_id else ""
        if not hardware_id:
            folded = reference.casefold()
            for candidate_id, item in by_id.items():
                if folded in {
                    _clean(item.get("part_name"), "").casefold(),
                    _clean(item.get("part_number"), "").casefold(),
                }:
                    hardware_id = candidate_id
                    break
        if not hardware_id:
            messagebox.showwarning(
                "Donanım Detaylı İnceleme",
                f"'{reference}' için donanım kataloğunda eşleşen kart bulunamadı.",
                parent=self.window,
            )
            return
        self.selected_id = hardware_id
        if self._detailed_review is None:
            self._detailed_review = HardwareDetailedReview(
                self.root, self.style, self.palette_getter,
                catalog_getter=lambda: self.catalog,
                traceability_getter=self._traceability_report,
                overrides_getter=lambda: self.overrides,
                back_callback=self._close_detailed_review,
                save_callback=self._save_detailed_fields,
                datasheet_callback=self._detail_datasheet,
                impact_callback=self._detail_impact,
                requirement_callback=self._detail_requirement,
                image_callback=self._detail_image_action,
            )
        self.toolbar.grid_remove(); self.quality_panel.grid_remove(); self.body.grid_remove(); self.status_bar.grid_remove()
        self.root.rowconfigure(1, weight=1); self.root.rowconfigure(3, weight=0)
        self._detailed_review.grid(row=1, column=0, rowspan=4, sticky="nsew")
        self._detail_visible = True
        self._detailed_review.open(hardware_id, initial_tab)

    def _close_detailed_review(self) -> None:
        if self._detailed_review is not None:
            self._detailed_review.grid_remove()
        self._detail_visible = False
        self.root.rowconfigure(1, weight=0); self.root.rowconfigure(3, weight=1)
        self.toolbar.grid(); self.quality_panel.grid(); self.body.grid(); self.status_bar.grid()
        self.select_card(self.selected_id)

    def _save_detailed_fields(
        self, hardware_id: str, values: Mapping[str, Any],
    ) -> None:
        for field, value in values.items():
            management.set_field_override(
                self.overrides, hardware_id, field, value, self.base_catalog,
            )
        self.selected_id = hardware_id
        self._persist_and_refresh()

    def _detail_datasheet(self, hardware_id: str) -> None:
        self.selected_id = hardware_id
        item = self._card_index().get(hardware_id, {})
        paths = [Path(path) for path in item.get("attached_datasheets", []) or []]
        existing = next((path for path in paths if path.is_file()), None)
        if existing:
            answer = messagebox.askyesnocancel(
                "Datasheet Aç / Yükle",
                f"Bağlı datasheet:\n{existing}\n\n"
                "Evet: mevcut datasheet'i aç\nHayır: yeni datasheet yükle\nİptal: vazgeç",
                parent=self.window,
            )
            if answer is None:
                return
            if answer:
                try:
                    webbrowser.open(existing.resolve().as_uri())
                except Exception as error:
                    messagebox.showerror("Datasheet Açılamadı", str(error), parent=self.window)
                return
        self._load_datasheet()

    def _detail_impact(self, hardware_id: str, alternative_id: str | None) -> None:
        try:
            payload = management.build_impact_payload(
                self.catalog, hardware_id, alternative_id=alternative_id,
            )
        except ValueError as error:
            messagebox.showwarning("Etki Analizi", str(error), parent=self.window)
            return
        if self.impact_callback:
            self.impact_callback(payload)

    def _detail_requirement(self, requirement_id: str) -> None:
        if self.requirement_callback:
            self.requirement_callback(requirement_id)

    def _detail_image_action(self, hardware_id: str, action: str) -> None:
        self.selected_id = hardware_id
        action_name, separator, image_path = action.partition("::")
        action = action_name
        if action == "select":
            self._select_image()
        elif action == "remove":
            if separator and image_path:
                item = self._card_index().get(hardware_id, {})
                if _clean(item.get("image_path"), "") == image_path:
                    self._remove_image()
                else:
                    if not management.remove_gallery_image(self.overrides, hardware_id, image_path):
                        remaining = [
                            record for record in item.get("gallery_images", []) or []
                            if isinstance(record, Mapping) and _clean(record.get("path"), "") != image_path
                        ]
                        management.set_field_override(
                            self.overrides, hardware_id, "gallery_images", remaining,
                            self.base_catalog,
                        )
                    self._persist_and_refresh()
            else:
                self._remove_image()
        elif action == "generate":
            self._generate_selected_visual(hardware_id)
        elif action == "cover" and image_path:
            record = next(
                (entry for entry in gallery_entries(self._card_index().get(hardware_id, {})) if entry.get("path") == image_path),
                {},
            )
            management.set_field_override(self.overrides, hardware_id, "image_path", image_path, self.base_catalog)
            management.set_field_override(
                self.overrides, hardware_id, "image_source",
                _clean(record.get("source_type"), "Kullanıcı tarafından kapak seçildi"),
                self.base_catalog,
            )
            management.set_field_override(
                self.overrides, hardware_id, "image_is_generated",
                bool(record.get("is_ai")), self.base_catalog,
            )
            management.set_field_override(
                self.overrides, hardware_id, "image_metadata",
                dict(record), self.base_catalog,
            )
            self._persist_and_refresh()

    def _generate_selected_visual(self, hardware_id: str) -> None:
        item = deepcopy(self._card_index().get(hardware_id, {}))
        if not item:
            messagebox.showinfo("AI Görseli", "Önce bir donanım kartı seçin.", parent=self.window)
            return
        if self._ai_image_dialog and self._ai_image_dialog.winfo_exists():
            self._ai_image_dialog.lift(); self._ai_image_dialog.focus_force(); return
        project_name = self.project_name_getter() or self.catalog.get("project_name") or "Proje"
        output_root = management.overrides_path(project_name, self.base_catalog).parent

        def accepted(record: Mapping[str, Any], make_cover: bool) -> None:
            management.add_gallery_image(self.overrides, hardware_id, record)
            if make_cover:
                management.set_field_override(self.overrides, hardware_id, "image_path", record.get("path"), self.base_catalog)
                management.set_field_override(
                    self.overrides, hardware_id, "image_source",
                    f"{record.get('source_type')} · teknik doğrulama için kullanılamaz",
                    self.base_catalog,
                )
                management.set_field_override(self.overrides, hardware_id, "image_is_generated", True, self.base_catalog)
                management.set_field_override(self.overrides, hardware_id, "image_metadata", dict(record), self.base_catalog)
            self._persist_and_refresh()
            self.status_var.set("AI kavramsal görsel kullanıcı onayıyla galeriye eklendi.")

        self._ai_image_dialog = AIImageGenerationDialog(
            self.window, item, output_root, accepted, palette=self.palette_getter(),
        )

    def _open_bulk_image_generation(self) -> None:
        items = [dict(item) for item in self.catalog.get("hardware_items", []) if isinstance(item, Mapping)]
        if not items:
            messagebox.showinfo("Toplu AI Görseli", "Katalogda üretilecek donanım kartı yok.", parent=self.window); return
        if self._bulk_image_dialog and self._bulk_image_dialog.winfo_exists():
            self._bulk_image_dialog.lift(); self._bulk_image_dialog.focus_force(); return
        project_name = self.project_name_getter() or self.catalog.get("project_name") or "Proje"
        output_root = management.overrides_path(project_name, self.base_catalog).parent
        def finished(records: Mapping[str, Mapping[str, Any]]) -> None:
            for hardware_id, record in records.items():
                management.add_gallery_image(self.overrides, hardware_id, record)
            management.save_overrides(project_name, self.overrides, self.base_catalog)
            self.catalog, self.override_conflicts = management.apply_overrides(self.base_catalog, self.overrides)
            self._render_all()
            if self._detail_visible and self._detailed_review is not None:
                self._detailed_review.refresh()
            self.status_var.set(f"{len(records)} AI kavramsal görsel galeriye eklendi; hiçbiri otomatik kapak yapılmadı.")
        self._bulk_image_dialog = BulkAIImageDialog(
            self.window, items, output_root, finished,
        )

    def _poll_selected_visual(
        self, hardware_id: str, result_queue: queue.Queue,
    ) -> None:
        try:
            path, error = result_queue.get_nowait()
        except queue.Empty:
            self.window.after(50, lambda: self._poll_selected_visual(hardware_id, result_queue))
            return
        if error:
            self.status_var.set(f"Kavramsal görsel üretilemedi: {error}")
            messagebox.showerror("Görsel Üretilemedi", error, parent=self.window)
            return
        management.set_field_override(self.overrides, hardware_id, "image_path", path, self.base_catalog)
        management.set_field_override(
            self.overrides, hardware_id, "image_source",
            hardware_visuals.ILLUSTRATION_SOURCE, self.base_catalog,
        )
        management.set_field_override(self.overrides, hardware_id, "image_is_generated", True, self.base_catalog)
        management.set_field_override(self.overrides, hardware_id, "visual_brief", hardware_visuals.build_visual_brief(self._card_index().get(hardware_id, {})).to_dict(), self.base_catalog)
        self._persist_and_refresh()

    def _select_tree_recursive(self, tree_id: str, hardware_id: str) -> bool:
        if self._tree_hardware_id(tree_id) == hardware_id:
            if tuple(self.product_tree.selection()) != (tree_id,):
                self.product_tree.selection_set(tree_id)
            self.product_tree.see(tree_id)
            return True
        return any(self._select_tree_recursive(child, hardware_id) for child in self.product_tree.get_children(tree_id))

    def _render_detail(self) -> None:
        for tree in self._detail_trees.values():
            tree.delete(*tree.get_children())
        item = self._card_index().get(self.selected_id)
        if not item:
            self.detail_title.set("Bir donanım kartı seçin")
            self.detail_subtitle.set("Kimlik, teknik sınır ve kanıt ayrıntıları burada gösterilir.")
            self.confidence_var.set("Güven —")
            return
        self.detail_title.set(_clean(item.get("part_name")))
        self.detail_subtitle.set(f"{_display(item.get('part_number'))}  ·  {_display(item.get('manufacturer'))}  ·  {_display(item.get('hardware_id'))}")
        score = item.get("confidence_score")
        self.confidence_var.set("Güven Hesaplanamadı" if score is None else f"Güven {float(score):.0f}/100")
        identity_rows = (
            ("Donanım kimliği", item.get("hardware_id")), ("Parça adı", item.get("part_name")),
            ("Parça numarası", item.get("part_number")), ("Üretici", item.get("manufacturer")),
            ("Model/seri", item.get("model_series")), ("Sistem görevi", item.get("system_role")),
            ("Donanım türü", item.get("hardware_type")), ("Sürüm", item.get("version")),
            ("Yaşam döngüsü", item.get("lifecycle_status")),
            ("Kaynak varlığı", item.get("source_presence_status", "Kaynakta bulundu")),
            ("Kullanıcı kararı", item.get("source_missing_decision")),
            ("Görsel kaynağı", item.get("image_source")),
            ("Veri kökeni", item.get("data_origin", "Otomatik")),
        )
        for row in identity_rows:
            self._detail_trees["identity"].insert("", "end", values=(row[0], _display(row[1])))
        self._render_technical(item)
        self._render_requirements(item)
        self._render_states(item)
        self._render_alternatives(item)
        self._render_locations(item)
        self._render_sources(item)

    def _evidence_for(self, item: Mapping[str, Any], field: str) -> Mapping[str, Any]:
        for evidence in item.get("source_evidence", []) or []:
            if not isinstance(evidence, Mapping):
                continue
            name = _clean(evidence.get("field_name"), "")
            if name in {field, f"technical_data.{field}"}:
                return evidence
        return {}

    def _render_technical(self, item: Mapping[str, Any]) -> None:
        td = dict(item.get("technical_data") or {})
        unit_for = {
            "operating_temperature_min": "temperature_unit", "operating_temperature_max": "temperature_unit",
            "storage_temperature_min": "temperature_unit", "storage_temperature_max": "temperature_unit",
            "length": "dimension_unit", "width": "dimension_unit", "height": "dimension_unit", "diameter": "dimension_unit",
            "weight": "weight_unit", "supply_voltage": "V", "power_consumption": "W",
        }
        labels = {**management.TECHNICAL_LABELS,
            "communication_interfaces": "Haberleşme arayüzleri", "mechanical_interfaces": "Mekanik arayüzler",
            "electrical_interfaces": "Elektriksel arayüzler", "standards_and_certifications": "Standartlar / sertifikalar",
        }
        for field, label in labels.items():
            value = td.get(field)
            unit_key = unit_for.get(field, "")
            unit = td.get(unit_key, unit_key) if unit_key else "—"
            evidence = self._evidence_for(item, field)
            confidence = (item.get("field_confidence") or {}).get(field, evidence.get("field_confidence"))
            self._detail_trees["technical"].insert("", "end", iid=f"TECH::{field}", values=(
                label, _display(value), _display(unit), _display(evidence.get("source_document")),
                "—" if confidence is None else f"{float(confidence):.0f}",
            ))
        for key, value in (td.get("custom_parameters") or {}).items():
            self._detail_trees["technical"].insert("", "end", iid=f"TECHCUSTOM::{key}", values=(key, _display(value), "—", "Kullanıcı tanımlı", "100"))

    def _render_requirements(self, item: Mapping[str, Any]) -> None:
        report = self._traceability_report()
        nodes = _trace_node_index(report)
        edges = [edge for edge in report.get("edges", []) if isinstance(edge, Mapping)]
        for requirement_id in item.get("requirement_ids", []) or []:
            node = nodes.get(requirement_id, {})
            tests = []
            for edge in edges:
                source = _clean(edge.get("source_id", edge.get("source")), "")
                target = _clean(edge.get("target_id", edge.get("target")), "")
                relation = _clean(edge.get("relationship", edge.get("type")), "")
                if source == requirement_id and relation in {"verified_by", "validated_by", "doğrulanır", "geçerlenir"}:
                    tests.append(target)
            if not tests:
                tests = [test for test in item.get("test_ids", []) or []]
            self._detail_trees["requirements"].insert("", "end", iid=f"REQ::{requirement_id}", values=(
                requirement_id, _display(node.get("title") or node.get("description")), "allocated_to / karşılar",
                _display(node.get("v_model_level")), _display(tests), _display(node.get("source_document")),
                _display(node.get("confidence_level") or node.get("confidence")),
            ))
        if not item.get("requirement_ids"):
            self._detail_trees["requirements"].insert("", "end", values=(MISSING_VALUE,) * 7)

    def _traceability_report(self) -> dict[str, Any]:
        if self._traceability_cache is None:
            self._traceability_cache = dict(self.traceability_getter() or {})
        return self._traceability_cache

    def _render_states(self, item: Mapping[str, Any]) -> None:
        profiles = {record.get("state"): record for record in item.get("state_profiles", []) if isinstance(record, Mapping)}
        states = list(dict.fromkeys([*(item.get("working_states") or []), *profiles]))
        for state in states or [MISSING_VALUE]:
            record = profiles.get(state, {})
            self._detail_trees["states"].insert("", "end", values=(
                state, _display(record.get("changed_parameters")), _display(record.get("affected_requirements")),
            ))

    def _render_alternatives(self, item: Mapping[str, Any]) -> None:
        by_id = self._card_index()
        links = {
            _clean(link.get("alternative_hardware_id"), ""): link
            for link in self.catalog.get("alternative_links", [])
            if isinstance(link, Mapping) and _clean(link.get("source_hardware_id"), "") == self.selected_id
        }
        for alternative_id in item.get("alternative_ids", []) or []:
            alternative = by_id.get(alternative_id, {})
            link = links.get(alternative_id, {})
            self._detail_trees["alternatives"].insert("", "end", iid=f"ALTDETAIL::{alternative_id}", values=(
                alternative_id, _display(alternative.get("part_name")), _display(link.get("compatibility_status")),
                f"Karşılanan {len(link.get('met_requirements') or [])} / Karşılanmayan {len(link.get('unmet_requirements') or [])}",
                _display(link.get("new_risks")), _display(alternative.get("confidence_score")),
            ))
        if not item.get("alternative_ids"):
            self._detail_trees["alternatives"].insert("", "end", values=(MISSING_VALUE,) * 6)

    def _render_locations(self, item: Mapping[str, Any]) -> None:
        all_instances = product_tree_instances(self.catalog)
        instances = [record for record in all_instances if _clean(record.get("hardware_id"), "") == self.selected_id]
        instance_index = {_clean(record.get("instance_id"), ""): record for record in all_instances}
        card_index = self._card_index()
        for record in instances:
            parent_instance = instance_index.get(_clean(record.get("parent_instance_id"), ""), {})
            parent = card_index.get(_clean(parent_instance.get("hardware_id"), ""), {})
            self._detail_trees["location"].insert("", "end", values=(
                _display(record.get("reference_designator") or record.get("instance_id")),
                _display(parent.get("part_name") or item.get("parent_id")), _display(record.get("level")),
                record.get("quantity", 1), _display(record.get("location")),
            ))
        if not instances:
            self._detail_trees["location"].insert("", "end", values=(MISSING_VALUE, _display(item.get("parent_id")), _display(item.get("hardware_type")), item.get("quantity", 1), MISSING_VALUE))

    def _render_sources(self, item: Mapping[str, Any]) -> None:
        for index, evidence in enumerate(item.get("source_evidence", []) or []):
            if not isinstance(evidence, Mapping):
                continue
            self._detail_trees["sources"].insert("", "end", iid=f"SOURCE::{index}", values=(
                _display(evidence.get("field_name")), _display(evidence.get("source_document")),
                _display(evidence.get("location")), _display(evidence.get("extraction_method")),
                _display(evidence.get("certainty")), _display(evidence.get("field_confidence")),
                _display(evidence.get("evidence_text")),
            ))
        for path in item.get("attached_datasheets", []) or []:
            self._detail_trees["sources"].insert("", "end", values=("datasheet", Path(path).name, "Dosya", "Kullanıcı bağlantısı", "Kesin bilgi", "100", path))
        if not item.get("source_evidence") and not item.get("attached_datasheets"):
            self._detail_trees["sources"].insert("", "end", values=(MISSING_VALUE,) * 7)

    def _persist_and_refresh(self) -> None:
        project_name = self.project_name_getter() or self.catalog.get("project_name") or "Proje"
        management.save_overrides(project_name, self.overrides, self.base_catalog)
        self.catalog, self.override_conflicts = management.apply_overrides(self.base_catalog, self.overrides)
        self.status_var.set("Manuel değişiklik güvenle kaydedildi; otomatik tarama bu alanı sessizce değiştiremez.")
        self._refresh_filters(); self._render_all()
        if self._detail_visible and self._detailed_review is not None:
            self._detailed_review.refresh()
        self._start_visual_generation()

    def _start_visual_generation(self) -> None:
        """Güvenlik gereği otomatik görsel üretmez; yalnızca açık onaylı akış kullanılır."""
        try:
            from config import HARDWARE_AUTO_IMAGE_GENERATION
        except Exception:
            HARDWARE_AUTO_IMAGE_GENERATION = False
        if not HARDWARE_AUTO_IMAGE_GENERATION:
            return
        if (
            self._visual_generation_running
            or Image is None
            or not self.catalog.get("hardware_items")
        ):
            return
        pending = [
            item for item in self.catalog.get("hardware_items", [])
            if isinstance(item, Mapping)
            and hardware_visuals.illustration_required(item)
        ]
        if not pending:
            return
        self._visual_generation_token += 1
        token = self._visual_generation_token
        self._visual_generation_running = True
        project_name = (
            self.project_name_getter()
            or self.catalog.get("project_name")
            or "Proje"
        )
        output_dir = (
            management.overrides_path(project_name, self.base_catalog).parent
            / "donanim_gorselleri"
        )
        snapshot = deepcopy(self.catalog)
        self.status_var.set(
            f"{self._status_text()} · {len(pending)} teknik illüstrasyon "
            "arka planda hazırlanıyor…"
        )

        def worker() -> None:
            try:
                records = hardware_visuals.generate_catalog_illustrations(
                    snapshot, output_dir
                )
                error = ""
            except Exception as exc:
                records, error = {}, str(exc)
            result_queue.put((records, error))

        result_queue: queue.Queue[tuple[dict[str, dict[str, Any]], str]] = queue.Queue(maxsize=1)
        threading.Thread(
            target=worker,
            daemon=True,
            name="donanim-gorsel-uretimi",
        ).start()
        self.window.after(
            40, lambda: self._poll_visual_generation(token, result_queue)
        )

    def _poll_visual_generation(
        self,
        token: int,
        result_queue: queue.Queue,
    ) -> None:
        if token != self._visual_generation_token or not self.exists:
            return
        try:
            records, error = result_queue.get_nowait()
        except queue.Empty:
            self.window.after(
                40, lambda: self._poll_visual_generation(token, result_queue)
            )
            return
        self._finish_visual_generation(token, records, error)

    def _finish_visual_generation(
        self,
        token: int,
        records: Mapping[str, Mapping[str, Any]],
        error: str,
    ) -> None:
        if token != self._visual_generation_token or not self.exists:
            return
        self._visual_generation_running = False
        if error:
            self.status_var.set(
                f"{self._status_text()} · Görsel üretim uyarısı: {error}"
            )
            return
        if not records:
            self.status_var.set(self._status_text())
            return
        project_name = (
            self.project_name_getter()
            or self.catalog.get("project_name")
            or "Proje"
        )
        management.set_generated_visuals(self.overrides, records)
        management.save_overrides(
            project_name, self.overrides, self.base_catalog
        )
        self.catalog, self.override_conflicts = management.apply_overrides(
            self.base_catalog, self.overrides
        )
        self.status_var.set(
            f"{self._status_text()} · {len(records)} AI içerik temelli "
            "teknik illüstrasyon hazır."
        )
        self._render_catalog_view(); self._render_quality_strip()
        if self.selected_id:
            self._render_detail()
        if self._detail_visible and self._detailed_review is not None:
            self._detailed_review.refresh()

    def _new_item(self) -> None:
        dialog = HardwareEditorDialog(self.window, None, list(self._card_index()))
        if dialog.result:
            self.selected_id = management.add_manual_item(self.overrides, dialog.result)
            self._persist_and_refresh()

    def _edit_item(self) -> None:
        item = self._card_index().get(self.selected_id)
        if not item:
            messagebox.showinfo("Donanım Kartları", "Önce düzenlenecek kartı seçin.", parent=self.window)
            return
        dialog = HardwareEditorDialog(self.window, item, [key for key in self._card_index() if key != self.selected_id])
        if not dialog.result:
            return
        for field, value in dialog.result.items():
            management.set_field_override(self.overrides, self.selected_id, field, value, self.base_catalog)
        self._persist_and_refresh()

    def _select_image(self) -> None:
        if not self.selected_id:
            messagebox.showinfo("Görsel Seç", "Önce bir donanım kartı seçin.", parent=self.window); return
        path = filedialog.askopenfilename(parent=self.window, title="Donanım görselini seçin", filetypes=(("Doğrulanabilir görseller", "*.png *.jpg *.jpeg *.webp"), ("Tüm dosyalar", "*.*")))
        if not path:
            return
        try:
            media_type, dimensions = validate_image_file(path)
        except ImageProviderError as error:
            messagebox.showerror("Görsel Kabul Edilmedi", str(error), parent=self.window); return
        resolved = str(Path(path).resolve())
        metadata = {
            "path": resolved, "source_kind": "verified_user_photo",
            "source_type": "Kullanıcının yüklediği doğrulanmış gerçek görsel",
            "source_document": Path(path).name, "is_ai": False,
            "media_type": media_type, "dimensions": list(dimensions),
            "verified_by_user": True,
        }
        management.set_field_override(self.overrides, self.selected_id, "image_path", resolved, self.base_catalog)
        management.set_field_override(self.overrides, self.selected_id, "image_source", "Kullanıcı seçimi", self.base_catalog)
        management.set_field_override(self.overrides, self.selected_id, "image_is_generated", False, self.base_catalog)
        management.set_field_override(self.overrides, self.selected_id, "image_metadata", metadata, self.base_catalog)
        self._persist_and_refresh()

    def _remove_image(self) -> None:
        if not self.selected_id:
            return
        management.set_field_override(self.overrides, self.selected_id, "image_path", PLACEHOLDER_IMAGE, self.base_catalog)
        management.set_field_override(self.overrides, self.selected_id, "image_source", "Yer tutucu", self.base_catalog)
        management.set_field_override(self.overrides, self.selected_id, "image_is_generated", False, self.base_catalog)
        management.set_field_override(self.overrides, self.selected_id, "image_metadata", {}, self.base_catalog)
        self._persist_and_refresh()
        self.status_var.set("Kart görsel bağlantısı kaldırıldı; özgün datasheet dosyasına dokunulmadı.")

    def _edit_technical_value(self) -> None:
        tree = self._detail_trees["technical"]
        selection = tree.selection()
        item = self._card_index().get(self.selected_id)
        if not selection or not item:
            messagebox.showinfo(
                "Teknik Değer Düzenle",
                "Önce Teknik Özellikler sekmesinde bir satır seçin.",
                parent=self.window,
            )
            return
        tree_id = selection[0]
        if tree_id.startswith("TECHCUSTOM::"):
            field = tree_id.split("::", 1)[1]
            field_path = f"technical_data.custom_parameters.{field}"
            current = (item.get("technical_data") or {}).get("custom_parameters", {}).get(field)
            unit_path = ""
        elif tree_id.startswith("TECH::"):
            field = tree_id.split("::", 1)[1]
            field_path = f"technical_data.{field}"
            current = (item.get("technical_data") or {}).get(field)
            unit_key = management.TECHNICAL_UNITS.get(field, "")
            unit_path = f"technical_data.{unit_key}" if unit_key in {
                "temperature_unit", "dimension_unit", "weight_unit"
            } else ""
        else:
            return
        value = simpledialog.askstring(
            "Teknik Değer Düzenle", f"{field} için yeni değer:",
            initialvalue="" if is_missing(current) else _clean(current, ""), parent=self.window,
        )
        if value is None:
            return
        normalized: Any = value.strip() or MISSING_VALUE
        if field in {
            "operating_temperature_min", "operating_temperature_max",
            "storage_temperature_min", "storage_temperature_max", "length", "width",
            "height", "diameter", "weight",
        } and normalized != MISSING_VALUE:
            try:
                normalized = float(str(normalized).replace(",", "."))
            except ValueError:
                messagebox.showwarning(
                    "Geçersiz Teknik Değer", "Bu alan için sayısal bir değer girin.",
                    parent=self.window,
                )
                return
        elif field in {
            "communication_interfaces", "mechanical_interfaces",
            "electrical_interfaces", "standards_and_certifications",
        }:
            normalized = [part.strip() for part in str(normalized).split(",") if part.strip()]
        management.set_field_override(
            self.overrides, self.selected_id, field_path, normalized, self.base_catalog
        )
        if unit_path:
            unit_key = unit_path.rsplit(".", 1)[-1]
            current_unit = (item.get("technical_data") or {}).get(unit_key)
            unit = simpledialog.askstring(
                "Teknik Değer Birimi", "Birim:",
                initialvalue="" if is_missing(current_unit) else _clean(current_unit, ""),
                parent=self.window,
            )
            if unit is not None:
                management.set_field_override(
                    self.overrides, self.selected_id, unit_path,
                    unit.strip() or MISSING_VALUE, self.base_catalog,
                )
        self._persist_and_refresh()

    def _load_datasheet(self) -> None:
        if not self.selected_id:
            messagebox.showinfo("Datasheet Yükle", "Datasheet bağlanacak donanım kartını seçin.", parent=self.window); return
        paths = filedialog.askopenfilenames(parent=self.window, title="Datasheet PDF dosyalarını seçin", filetypes=(("PDF", "*.pdf"), ("Tüm dosyalar", "*.*")))
        if not paths:
            return
        management.attach_datasheets(self.overrides, self.selected_id, paths)
        self._persist_and_refresh()
        if self.datasheet_callback:
            self.set_loading(True, "Datasheet arka planda işleniyor; arayüz kullanılmaya devam edebilir…")
            self.datasheet_callback(list(paths), self.selected_id)

    def _rescan(self) -> None:
        if not self.rescan_callback:
            return
        self.set_loading(True, "Belge seti ve donanım kataloğu arka planda yeniden taranıyor…")
        self.rescan_callback(True)

    def _load_sample(self) -> None:
        if self.catalog.get("hardware_items") and not messagebox.askyesno("Örnek Veri", "Örnek veri yalnızca bu pencerede gösterilecek; mevcut proje kataloğu silinmeyecek. Devam edilsin mi?", parent=self.window):
            return
        self.base_catalog = management.sample_catalog()
        self.overrides = management.empty_overrides(self.base_catalog.get("project_name", "Örnek"), self.base_catalog)
        self.catalog, self.override_conflicts = management.apply_overrides(self.base_catalog, self.overrides)
        self.selected_id = "SAMPLE-DCDC"
        self.project_label.configure(text="ÖRNEK VERİ · GERÇEK PROJE VERİSİ DEĞİLDİR")
        self.status_var.set("Geliştirme/test ağacı yüklendi. Bu veriler gerçek projeye kaydedilmedi.")
        self._refresh_filters(); self._render_all()

    def _add_alternative(self) -> None:
        if not self.selected_id:
            return
        current = self._card_index().get(self.selected_id, {})
        excluded = {self.selected_id, *(current.get("alternative_ids") or [])}
        choices = {f"{_clean(item.get('part_name'))} · {_clean(item.get('part_number'))}": hardware_id for hardware_id, item in self._card_index().items() if hardware_id not in excluded}
        if not choices:
            messagebox.showinfo("Alternatif Ekle", "Bağlanabilecek başka donanım kartı bulunamadı.", parent=self.window); return
        dialog = AlternativeDialog(self.window, choices)
        if dialog.result:
            management.add_alternative_link(self.overrides, self.selected_id, dialog.result["hardware_id"], dialog.result["reason"], dialog.result["status"])
            self._persist_and_refresh()

    def _add_state(self) -> None:
        if not self.selected_id:
            return
        state = simpledialog.askstring("Durum Ekle", "Durum adı (Normal, Bakımda veya kullanıcı tanımlı):", parent=self.window)
        if not state:
            return
        changed = simpledialog.askstring("Durum Parametreleri", "Bu durumda değişen parametreleri yazın:", parent=self.window) or ""
        requirements = simpledialog.askstring("Etkilenen Gereksinimler", "Gereksinim kimliklerini virgülle ayırın:", parent=self.window) or ""
        management.add_state_profile(self.overrides, self.selected_id, state, changed, [item.strip() for item in requirements.split(",") if item.strip()])
        self._persist_and_refresh()

    def _link_requirement(self) -> None:
        if not self.selected_id:
            return
        report = self._traceability_report()
        known = _trace_node_index(report)
        requirement_id = simpledialog.askstring("Gereksinim İlişkilendir", "Gerçek gereksinim kimliğini yazın:", parent=self.window)
        if not requirement_id:
            return
        requirement_id = requirement_id.strip()
        if requirement_id not in known:
            messagebox.showwarning("Bilinmeyen Kimlik", "Bu kimlik mevcut izlenebilirlik haritasında bulunamadı; hayali bağlantı oluşturulmadı.", parent=self.window); return
        current = list(self._card_index()[self.selected_id].get("requirement_ids") or [])
        if requirement_id not in current:
            current.append(requirement_id)
        management.set_field_override(self.overrides, self.selected_id, "requirement_ids", current, self.base_catalog)
        self._persist_and_refresh()

    def _reject_source_field(self) -> None:
        tree = self._detail_trees["sources"]
        selection = tree.selection()
        if not selection or not selection[0].startswith("SOURCE::") or not self.selected_id:
            messagebox.showinfo("Otomatik Bilgiyi Reddet", "Önce Kaynaklar sekmesinde otomatik bir alan seçin.", parent=self.window); return
        index = int(selection[0].split("::", 1)[1])
        item = self._card_index().get(self.selected_id, {})
        evidence = (item.get("source_evidence") or [])[index]
        field = _clean(evidence.get("field_name"), "")
        if not field:
            return
        if not messagebox.askyesno("Otomatik Bilgiyi Reddet", f"'{field}' alanı reddedilip 'Veri bulunamadı' olarak işaretlensin mi?", parent=self.window):
            return
        management.reject_automatic_field(self.overrides, self.selected_id, field)
        self._persist_and_refresh()

    def _send_to_impact(self, hardware_id: str | None = None) -> None:
        target = hardware_id or self.selected_id
        if not target:
            messagebox.showinfo("Etki Analizi", "Önce bir donanım kartı seçin.", parent=self.window); return
        try:
            payload = management.build_impact_payload(self.catalog, target)
        except ValueError as error:
            messagebox.showwarning("Etki Analizi", str(error), parent=self.window); return
        if self.impact_callback:
            self.impact_callback(payload)

    def _go_parent(self) -> None:
        item = self._card_index().get(self.selected_id, {})
        parent_id = _clean(item.get("parent_id"), "")
        if parent_id in self._card_index():
            self.select_card(parent_id, scroll_cards=True)
        else:
            messagebox.showinfo("Üst Parça", "Seçili kart için katalogda erişilebilir üst parça bulunamadı.", parent=self.window)

    def _selected_requirement_id(self) -> str:
        selection = self._detail_trees["requirements"].selection()
        if selection and selection[0].startswith("REQ::"):
            return selection[0][5:]
        item = self._card_index().get(self.selected_id, {})
        values = item.get("requirement_ids") or []
        return values[0] if values else ""

    def _go_requirement(self) -> None:
        requirement_id = self._selected_requirement_id()
        if not requirement_id:
            messagebox.showinfo("Gereksinime Git", "Seçili kartta bağlı gereksinim bulunamadı.", parent=self.window); return
        if self.requirement_callback:
            self.requirement_callback(requirement_id)

    def _show_confidence(self) -> None:
        item = self._card_index().get(self.selected_id)
        if not item:
            return
        breakdown = item.get("confidence_breakdown") or {}
        components = breakdown.get("components") or {}
        weights = breakdown.get("weights") or management.CONFIDENCE_WEIGHTS
        labels = {
            "explicit_identity": "Kimlik doğrulama", "datasheet_or_manufacturer": "Datasheet / üretici kaynağı",
            "multi_document_consistency": "Belgeler arası tutarlılık", "requirement_and_test_links": "Gereksinim / test bağlantısı",
            "basic_field_completeness": "Alan doluluk oranı",
        }
        lines = [f"Toplam güven: {_display(item.get('confidence_score'))}/100", ""]
        for key, weight in weights.items():
            lines.append(f"{labels.get(key, key)}: {float(components.get(key, 0)):.1f} / {float(weight):.1f}")
        lines.extend(("", "Puan Python ile deterministik hesaplanır; LM Studio öznel güveni kullanılmaz."))
        messagebox.showinfo("Güven Skoru Dağılımı", "\n".join(lines), parent=self.window)

    def _show_change_summary(self) -> None:
        counts = self.change_summary.get("counts") or {}
        lines = [
            f"Yeni bulunan parçalar: {counts.get('new', 0)}",
            f"Değişen parçalar: {counts.get('changed', 0)}",
            f"Kaynakta artık bulunmayan parçalar: {counts.get('missing', 0)}",
            f"Otomatik kaynak çelişkileri: {counts.get('conflicts', 0)}",
            f"Manuel/otomatik çakışmalar: {len(self.override_conflicts)}",
        ]
        missing = self.change_summary.get("missing_items") or []
        if missing:
            lines.extend(("", "Kaynakta artık bulunmayanlar otomatik silinmedi:", *(f"• {item}" for item in missing)))
        if self.override_conflicts:
            lines.extend(("", "Manuel değerler korunuyor; aşağıdaki çözüm adımında kullanıcı kararı istenir."))
        messagebox.showinfo("Donanım Kataloğu Değişiklik Özeti", "\n".join(lines), parent=self.window)
        changed = False
        for conflict in list(self.override_conflicts):
            answer = messagebox.askyesnocancel(
                "Manuel / Otomatik Bilgi Çakışması",
                f"Kart: {conflict.get('hardware_id')}\nAlan: {conflict.get('field')}\n\n"
                f"Önceki otomatik değer: {_display(conflict.get('previous_auto_value'))}\n"
                f"Yeni otomatik değer: {_display(conflict.get('new_auto_value'))}\n"
                f"Manuel değer: {_display(conflict.get('manual_value'))}\n\n"
                "Evet: Manuel değeri koru\nHayır: Yeni otomatik değeri kabul et\nİptal: Daha sonra karar ver",
                parent=self.window,
            )
            if answer is None:
                continue
            management.resolve_manual_auto_conflict(
                self.overrides, conflict,
                "Manuel değeri koru" if answer else "Otomatik değeri kabul et",
            )
            changed = True
        for hardware_id in missing:
            current = (self.overrides.get("source_missing_decisions") or {}).get(hardware_id)
            if current:
                continue
            answer = messagebox.askyesnocancel(
                "Kaynakta Artık Bulunmayan Parça",
                f"{hardware_id} güncel belgelerde bulunamadı. Kart otomatik silinmedi.\n\n"
                "Evet: Kartı katalogda koru\nHayır: Kullanımdan kaldırıldı olarak işaretle\n"
                "İptal: Kararı ertele",
                parent=self.window,
            )
            decision = "Ertelendi" if answer is None else "Korunsun" if answer else "Kullanımdan kaldırıldı"
            management.record_source_missing_decision(self.overrides, hardware_id, decision)
            changed = True
        if changed:
            self._persist_and_refresh()

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
