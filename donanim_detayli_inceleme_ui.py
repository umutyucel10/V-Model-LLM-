# -*- coding: utf-8 -*-
"""Ana Donanım Kartları çalışma alanındaki geniş ayrıntılı inceleme ekranı."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping
import webbrowser

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

from donanim_detayli_inceleme import (
    alternative_comparison_rows, alternative_ids, breadcrumb, child_items,
    connection_rows, display, gallery_entries, history_rows, item_index,
    overview, requirement_rows, source_rows, state_rows, technical_rows,
)
from donanim_detayli_inceleme_raporlama import export_hardware_excel, export_hardware_pdf
from donanim_kartlari_model import MISSING_VALUE, PLACEHOLDER_IMAGE, clean_text, is_missing


TABS = (
    ("overview", "Genel Bakış"), ("technical", "Teknik Özellikler"),
    ("requirements", "Gereksinimler ve Testler"), ("connections", "Sistem Bağlantıları"),
    ("states", "Çalışma Durumları"), ("alternatives", "Alternatifler"),
    ("gallery", "Görseller"), ("sources", "Kaynak ve Kanıtlar"),
    ("history", "Değişiklik Geçmişi"),
)


class HardwareDetailedReview(ttk.Frame):
    """Katalog verisini değiştirmeden, seçili parçayı mühendislik tezgâhında inceler."""

    EDIT_FIELDS = (
        ("part_name", "Parça adı"), ("part_number", "Parça numarası"),
        ("manufacturer", "Üretici"), ("model_series", "Model / seri"),
        ("hardware_type", "Donanım türü"), ("system_role", "Sistem görevi"),
        ("lifecycle_status", "Yaşam döngüsü"),
    )

    def __init__(
        self, parent: tk.Misc, style: ttk.Style,
        palette_getter: Callable[[], Mapping[str, str]],
        catalog_getter: Callable[[], Mapping[str, Any]],
        traceability_getter: Callable[[], Mapping[str, Any]],
        overrides_getter: Callable[[], Mapping[str, Any]],
        back_callback: Callable[[], None],
        save_callback: Callable[[str, Mapping[str, Any]], None],
        datasheet_callback: Callable[[str], None],
        impact_callback: Callable[[str, str | None], None],
        requirement_callback: Callable[[str], None],
        image_callback: Callable[[str, str], None],
    ) -> None:
        super().__init__(parent, style="HardwareRoot.TFrame")
        self.style = style; self.palette_getter = palette_getter
        self.catalog_getter = catalog_getter; self.traceability_getter = traceability_getter
        self.overrides_getter = overrides_getter; self.back_callback = back_callback
        self.save_callback = save_callback; self.datasheet_callback = datasheet_callback
        self.impact_callback = impact_callback; self.requirement_callback = requirement_callback
        self.image_callback = image_callback
        self.hardware_id = ""; self.item: dict[str, Any] = {}; self.editing = False; self.dirty = False
        self._edit_vars: dict[str, tk.StringVar] = {}
        self._trees: dict[str, ttk.Treeview] = {}
        self._source_records: list[dict[str, Any]] = []
        self._gallery: list[dict[str, Any]] = []; self._gallery_index = 0
        self._gallery_zoom = 1.0; self._gallery_photo: Any = None
        self._thumbnail_cache: OrderedDict[tuple[str, int, int], Any] = OrderedDict()
        self._photo_loading: set[tuple[str, int, int]] = set()
        self._photo_callbacks: dict[tuple[str, int, int], list[Callable[[Any], None]]] = {}
        self._export_token = 0
        self._build(); self.apply_theme()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1); self.rowconfigure(4, weight=1)
        nav = ttk.Frame(self, style="HardwareDetailNav.TFrame", padding=(8, 6), borderwidth=1, relief="solid")
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 6)); nav.columnconfigure(2, weight=1)
        ttk.Button(nav, text="← Kataloğa Dön", command=self.request_back).grid(row=0, column=0, padx=(0, 8))
        self.prev_button = ttk.Button(nav, text="‹ Önceki", command=lambda: self._move(-1)); self.prev_button.grid(row=0, column=1)
        self.breadcrumb_var = tk.StringVar(value=MISSING_VALUE)
        ttk.Label(nav, textvariable=self.breadcrumb_var, style="HardwareDetailBreadcrumb.TLabel", anchor="center").grid(row=0, column=2, sticky="ew", padx=10)
        self.next_button = ttk.Button(nav, text="Sonraki ›", command=lambda: self._move(1)); self.next_button.grid(row=0, column=3)
        ttk.Label(nav, text="Sekme", style="HardwareDetailBreadcrumb.TLabel").grid(row=0, column=4, padx=(12, 4))
        self.tab_selector_var = tk.StringVar(value=TABS[0][1])
        self.tab_selector = ttk.Combobox(
            nav, textvariable=self.tab_selector_var,
            values=[title for _key, title in TABS], state="readonly", width=24,
            style="Hardware.TCombobox",
        )
        self.tab_selector.grid(row=0, column=5)
        self.tab_selector.bind("<<ComboboxSelected>>", self._selector_tab_changed)

        identity = ttk.Frame(self, style="HardwareDetailSurface.TFrame", padding=10, borderwidth=1, relief="solid")
        identity.grid(row=1, column=0, sticky="ew", pady=(0, 6)); identity.columnconfigure(1, weight=1)
        self.hero_canvas = tk.Canvas(identity, width=184, height=126, highlightthickness=1, borderwidth=0)
        self.hero_canvas.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 12))
        self.title_var = tk.StringVar(); self.subtitle_var = tk.StringVar(); self.role_var = tk.StringVar()
        ttk.Label(identity, textvariable=self.title_var, style="HardwareDetailHeroTitle.TLabel").grid(row=0, column=1, sticky="nw")
        ttk.Label(identity, textvariable=self.subtitle_var, style="HardwareDetailMono.TLabel").grid(row=1, column=1, sticky="nw", pady=(3, 0))
        ttk.Label(identity, textvariable=self.role_var, style="HardwareDetailBody.TLabel", wraplength=460, justify="left").grid(row=2, column=1, sticky="nw", pady=(6, 0))
        self.identity_facts = ttk.Frame(identity, style="HardwareDetailSurface.TFrame")
        self.identity_facts.grid(row=0, column=2, rowspan=3, sticky="ne", padx=(14, 0))
        self.fact_vars = [tk.StringVar() for _ in range(7)]
        for variable in self.fact_vars:
            ttk.Label(self.identity_facts, textvariable=variable, style="HardwareDetailMono.TLabel", anchor="e").pack(anchor="e", pady=1)

        actions = ttk.Frame(self, style="HardwareDetailToolbar.TFrame", padding=(7, 6), borderwidth=1, relief="solid")
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        actions.columnconfigure((0, 1, 2, 3), weight=1)
        for index, (text, command, style_name) in enumerate((
            ("Düzenle", self.start_edit, "primary.TButton"),
            ("Datasheet Aç / Yükle", lambda: self.datasheet_callback(self.hardware_id), "primary.Outline.TButton"),
            ("Alternatiflerle Karşılaştır", lambda: self.select_tab("alternatives"), "primary.Outline.TButton"),
            ("Etki Analizini Başlat", lambda: self.impact_callback(self.hardware_id, None), "primary.TButton"),
            ("Görsel Ekle / Üret", self._image_menu, "primary.Outline.TButton"),
            ("PDF Kartı Oluştur", lambda: self._export("pdf"), "primary.Outline.TButton"),
            ("Excel'e Aktar", lambda: self._export("xlsx"), "primary.Outline.TButton"),
        )):
            ttk.Button(actions, text=text, command=command, style=style_name).grid(
                row=index // 4, column=index % 4, sticky="ew", padx=3, pady=2,
            )

        self.edit_frame = ttk.Frame(self, style="HardwareDetailEdit.TFrame", padding=8, borderwidth=1, relief="solid")
        self.edit_frame.columnconfigure((1, 3, 5), weight=1)
        for index, (field, label) in enumerate(self.EDIT_FIELDS):
            row, pair = divmod(index, 3); column = pair * 2
            ttk.Label(self.edit_frame, text=label, style="HardwareDetailEdit.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 5), pady=3)
            variable = tk.StringVar(); variable.trace_add("write", self._mark_dirty); self._edit_vars[field] = variable
            ttk.Entry(self.edit_frame, textvariable=variable).grid(row=row, column=column + 1, sticky="ew", padx=(0, 10), pady=3)
        edit_actions = ttk.Frame(self.edit_frame, style="HardwareDetailEdit.TFrame")
        edit_actions.grid(row=3, column=0, columnspan=6, sticky="e", pady=(7, 0))
        ttk.Button(edit_actions, text="İptal", command=self.cancel_edit).pack(side="right")
        ttk.Button(edit_actions, text="Değişiklikleri Kaydet", style="primary.TButton", command=self.save_edit).pack(side="right", padx=(0, 6))

        self.trace_bar = ttk.Frame(self, style="HardwareDetailTrace.TFrame", padding=(8, 5), borderwidth=1, relief="solid")
        self.trace_bar.grid(row=3, column=0, sticky="ew", pady=(0, 6)); self.trace_bar.columnconfigure((0, 2, 4, 6, 8), weight=1)
        trace_items = (("Üst Sistem", "connections"), ("Parça", "overview"), ("Gereksinim", "requirements"), ("Test", "requirements"), ("Alternatif", "alternatives"))
        for index, (text, tab) in enumerate(trace_items):
            ttk.Button(self.trace_bar, text=text, style="HardwareDetailTrace.TButton", command=lambda key=tab: self.select_tab(key)).grid(row=0, column=index * 2, sticky="ew")
            if index < len(trace_items) - 1:
                ttk.Label(self.trace_bar, text="→", style="HardwareDetailTraceArrow.TLabel").grid(row=0, column=index * 2 + 1, padx=4)

        self.notebook = ttk.Notebook(self, style="HardwareDetail.TNotebook")
        self.notebook.grid(row=4, column=0, sticky="nsew")
        self.tabs: dict[str, ttk.Frame] = {}
        for key, title in TABS:
            frame = ttk.Frame(self.notebook, style="HardwareDetailSurface.TFrame", padding=7)
            self.notebook.add(frame, text=title); self.tabs[key] = frame
        self._build_overview(); self._build_technical(); self._build_requirements()
        self._build_connections(); self._build_states(); self._build_alternatives()
        self._build_gallery(); self._build_sources(); self._build_history()

    def _tree(self, tab: str, columns: tuple[tuple[str, str, int], ...], row: int = 0) -> ttk.Treeview:
        frame = self.tabs[tab]; frame.columnconfigure(0, weight=1); frame.rowconfigure(row, weight=1)
        holder = ttk.Frame(frame, style="HardwareDetailSurface.TFrame"); holder.grid(row=row, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1); holder.rowconfigure(0, weight=1)
        tree = ttk.Treeview(holder, columns=[c[0] for c in columns], show="headings", style="HardwareDetail.Treeview")
        for key, title, width in columns:
            tree.heading(key, text=title); tree.column(key, width=width, minwidth=55, anchor="e" if key in {"value", "minimum", "maximum", "tolerance", "confidence"} else "w")
        y = ttk.Scrollbar(holder, orient="vertical", command=tree.yview); x = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky="nsew"); y.grid(row=0, column=1, sticky="ns"); x.grid(row=1, column=0, sticky="ew")
        self._trees[tab] = tree; return tree

    def _build_overview(self) -> None:
        tree = self._tree("overview", (("field", "Mühendislik Özeti", 210), ("value", "İçerik", 900)))
        tree.configure(style="HardwareOverview.Treeview"); tree.column("value", anchor="w")

    def _build_technical(self) -> None:
        self._tree("technical", (
            ("category", "Kategori", 105), ("parameter", "Parametre", 180), ("value", "Değer", 110),
            ("unit", "Birim", 70), ("minimum", "Minimum", 90), ("maximum", "Maksimum", 90),
            ("tolerance", "Tolerans", 90), ("state", "Durum Değeri", 130), ("source", "Kaynak", 170),
            ("location", "Sayfa / Bölüm", 120), ("confidence", "Güven", 70), ("certainty", "Bilgi Türü", 120),
        ))

    def _build_requirements(self) -> None:
        tree = self._tree("requirements", (
            ("id", "Kimlik", 130), ("text", "Gereksinim Metni", 420), ("level", "Seviye", 120),
            ("relation", "İlişki", 110), ("compliance", "Karşılama", 120), ("tests", "Bağlı Test", 170),
            ("result", "Test Sonucu", 110), ("source", "Kaynak", 160), ("confidence", "Güven", 80),
        ))
        tree.bind("<Double-1>", lambda _event: self._open_requirement())
        actions = ttk.Frame(self.tabs["requirements"], style="HardwareDetailSurface.TFrame"); actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="Gereksinim Ayrıntısını Aç", command=self._open_requirement).pack(side="left")
        ttk.Button(actions, text="Bu Gereksinim Değişirse Ne Olur?", style="primary.TButton", command=self._simulate_requirement).pack(side="right")

    def _build_connections(self) -> None:
        frame = self.tabs["connections"]; frame.columnconfigure(0, weight=2); frame.columnconfigure(1, weight=1); frame.rowconfigure(0, weight=1)
        tree = self._tree("connections", (("direction", "Yön", 55), ("type", "Bağlantı Türü", 170), ("id", "Kimlik", 140), ("name", "Bağlı Öğe", 260), ("source", "Kaynak", 160)))
        tree.master.grid_configure(row=0, column=0, padx=(0, 7))
        self.connection_canvas = tk.Canvas(frame, highlightthickness=1, borderwidth=0, width=330)
        self.connection_canvas.grid(row=0, column=1, sticky="nsew")

    def _build_states(self) -> None:
        self._tree("states", (("state", "Durum", 120), ("parameters", "Değişen Teknik Değerler", 240), ("requirements", "Etkilenen Gereksinimler", 200), ("parts", "Etkilenen Parçalar", 180), ("risks", "Aktif Riskler", 180), ("tests", "Gerekli Testler", 180), ("behavior", "Beklenen Sistem Davranışı", 270)))

    def _build_alternatives(self) -> None:
        frame = self.tabs["alternatives"]; frame.columnconfigure(0, weight=1); frame.rowconfigure(1, weight=1)
        selector = ttk.Frame(frame, style="HardwareDetailSurface.TFrame"); selector.grid(row=0, column=0, sticky="ew", pady=(0, 6)); selector.columnconfigure(1, weight=1)
        ttk.Label(selector, text="Karşılaştırılan alternatif", style="HardwareDetailSection.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.alt_var = tk.StringVar(); self.alt_combo = ttk.Combobox(selector, textvariable=self.alt_var, state="readonly", style="Hardware.TCombobox")
        self.alt_combo.grid(row=0, column=1, sticky="ew"); self.alt_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_alternative_comparison())
        ttk.Button(selector, text="Alternatif Kartını Aç", command=self._open_selected_alternative).grid(row=0, column=2, padx=6)
        ttk.Button(selector, text="Bu Alternatifi Simüle Et", style="primary.TButton", command=self._simulate_alternative).grid(row=0, column=3)
        self._tree("alternatives", (("parameter", "Parametre", 250), ("current", "Mevcut Parça", 190), ("alternative", "Alternatif Parça", 190), ("unit", "Birim", 80), ("assessment", "Değerlendirme", 170)), row=1)

    def _build_gallery(self) -> None:
        frame = self.tabs["gallery"]; frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
        self.gallery_canvas = tk.Canvas(frame, highlightthickness=1, borderwidth=0, cursor="fleur")
        self.gallery_canvas.grid(row=0, column=0, sticky="nsew")
        self.gallery_canvas.bind("<MouseWheel>", self._gallery_wheel); self.gallery_canvas.bind("<ButtonPress-1>", lambda event: self.gallery_canvas.scan_mark(event.x, event.y)); self.gallery_canvas.bind("<B1-Motion>", lambda event: self.gallery_canvas.scan_dragto(event.x, event.y, gain=1))
        controls = ttk.Frame(frame, style="HardwareDetailSurface.TFrame"); controls.grid(row=1, column=0, sticky="ew", pady=(6, 0)); controls.columnconfigure(4, weight=1)
        ttk.Button(controls, text="‹ Önceki", command=lambda: self._gallery_move(-1)).grid(row=0, column=0)
        ttk.Button(controls, text="Sonraki ›", command=lambda: self._gallery_move(1)).grid(row=0, column=1, padx=4)
        ttk.Button(controls, text="−", width=3, command=lambda: self._set_zoom(.8)).grid(row=0, column=2)
        ttk.Button(controls, text="+", width=3, command=lambda: self._set_zoom(1.25)).grid(row=0, column=3, padx=(3, 10))
        self.gallery_meta = tk.StringVar(); ttk.Label(controls, textvariable=self.gallery_meta, style="HardwareDetailMono.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Button(controls, text="Tam Ekran", command=self._gallery_fullscreen).grid(row=1, column=0, pady=(5, 0))
        ttk.Button(controls, text="Dosyaya Kaydet", command=self._save_gallery_file).grid(row=1, column=1, padx=4, pady=(5, 0))
        ttk.Button(controls, text="Kapak Görseli Yap", command=lambda: self._gallery_action("cover")).grid(row=1, column=2, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            controls, text="AI Görseli Oluştur", style="primary.TButton",
            command=lambda: self.image_callback(self.hardware_id, "generate"),
        ).grid(row=1, column=4, sticky="e", padx=(6, 0), pady=(5, 0))
        ttk.Button(controls, text="Görseli Kaldır", command=lambda: self._gallery_action("remove")).grid(row=1, column=5, padx=(4, 0), pady=(5, 0))
        self.gallery_warning = tk.StringVar(value="")
        ttk.Label(
            controls, textvariable=self.gallery_warning,
            style="HardwareDetailWarning.TLabel", anchor="center",
        ).grid(row=2, column=0, columnspan=6, sticky="ew", pady=(6, 0))

    def _build_sources(self) -> None:
        tree = self._tree("sources", (("field", "Alan", 120), ("document", "Kaynak Belge", 210), ("location", "Sayfa / Bölüm", 130), ("evidence", "Kanıt Metni", 430), ("method", "Çıkarma Yöntemi", 140), ("confidence", "Güven", 70), ("certainty", "Bilgi Türü", 120)))
        tree.bind("<Double-1>", lambda _event: self._open_source())
        actions = ttk.Frame(self.tabs["sources"], style="HardwareDetailSurface.TFrame"); actions.grid(row=1, column=0, sticky="e", pady=(6, 0))
        ttk.Button(actions, text="Seçili Kaynağı Aç", command=self._open_source).pack(side="right")

    def _build_history(self) -> None:
        self._tree("history", (("timestamp", "Tarih", 170), ("action", "İşlem", 240), ("field", "Alan", 180), ("old", "Önceki Değer", 260), ("new", "Yeni Değer", 260), ("actor", "Kullanıcı", 120)))

    def open(self, hardware_id: str, initial_tab: str | None = None) -> None:
        if hardware_id not in item_index(self.catalog_getter()):
            raise ValueError("Detaylı incelenecek donanım kartı bulunamadı.")
        if self.editing and self.dirty and hardware_id != self.hardware_id and not messagebox.askyesno("Kaydedilmemiş Değişiklik", "Kaydedilmemiş düzenlemeler silinsin mi?", parent=self.winfo_toplevel()):
            return
        self.hardware_id = hardware_id; self.editing = False; self.dirty = False; self.edit_frame.grid_forget()
        self.trace_bar.grid_configure(row=3); self.notebook.grid_configure(row=4)
        self.rowconfigure(4, weight=1); self.rowconfigure(5, weight=0)
        self.refresh(); self.select_tab(initial_tab or "overview")

    def refresh(self) -> None:
        catalog = self.catalog_getter(); self.item = item_index(catalog).get(self.hardware_id, {})
        if not self.item: return
        self.breadcrumb_var.set(breadcrumb(catalog, self.hardware_id)); self.title_var.set(display(self.item.get("part_name")))
        self.subtitle_var.set(f"PN  {display(self.item.get('part_number'))}   ·   {display(self.item.get('manufacturer'))}   ·   {display(self.item.get('model_series'))}   ·   {display(self.item.get('hardware_type'))}")
        self.role_var.set(f"Sistem görevi: {display(self.item.get('system_role'))}")
        source = display(self.item.get("data_origin", self.item.get("image_source")))
        facts = (f"Yaşam: {display(self.item.get('lifecycle_status'))}", f"Çalışma: {display(self.item.get('working_states'))}", f"Güven: {display(self.item.get('confidence_score'))}/100", f"Kaynak: {source}", f"Güncelleme: {display(self.item.get('updated_at'))}", f"Sürüm: {display(self.item.get('version'))}", f"Kimlik: {self.hardware_id}")
        for variable, value in zip(self.fact_vars, facts): variable.set(value)
        self._render_hero(); self._render_all_tabs(); self._update_navigation()

    def _render_all_tabs(self) -> None:
        catalog, report = self.catalog_getter(), self.traceability_getter()
        for tree in self._trees.values(): tree.delete(*tree.get_children())
        labels = {"system_role": "Sistem görevi", "purpose": "Kullanım amacı", "location": "Ürün ağacı konumu", "parent": "Üst sistem", "children": "Alt bileşenler", "quantity": "Kullanım miktarı", "critical_limits": "Kritik teknik sınırlar", "critical_requirements": "Kritik gereksinimler", "risks": "Açık riskler", "missing": "Eksik bilgiler", "actions": "Önerilen mühendislik aksiyonları"}
        for key, value in overview(self.item, catalog, report).items(): self._trees["overview"].insert("", "end", values=(labels.get(key, key), str(value).replace("\n", "  •  ")))
        for row in technical_rows(self.item): self._trees["technical"].insert("", "end", values=tuple(row[k] for k in ("category", "parameter", "value", "unit", "minimum", "maximum", "tolerance", "state_value", "source_document", "location", "confidence", "certainty")))
        for row in requirement_rows(self.item, report): self._trees["requirements"].insert("", "end", iid=f"REQ::{row['id']}", values=tuple(row[k] for k in ("id", "text", "level", "relation", "compliance", "tests", "test_result", "source", "confidence")))
        for row in connection_rows(catalog, self.item, report): self._trees["connections"].insert("", "end", values=tuple(row[k] for k in ("direction", "type", "id", "name", "source")))
        for row in state_rows(self.item): self._trees["states"].insert("", "end", values=tuple(row[k] for k in ("state", "parameters", "requirements", "parts", "risks", "tests", "behavior")))
        self._source_records = source_rows(self.item)
        for index, row in enumerate(self._source_records): self._trees["sources"].insert("", "end", iid=f"SRC::{index}", values=tuple(row[k] for k in ("field", "document", "location", "evidence", "method", "confidence", "certainty")))
        for row in history_rows(self.overrides_getter(), self.hardware_id): self._trees["history"].insert("", "end", values=tuple(display(row.get(k)) for k in ("timestamp", "action", "field", "old_value", "new_value", "actor")))
        self._render_connection_graph(); self._refresh_alternatives(); self._refresh_gallery()

    def _render_connection_graph(self) -> None:
        canvas = self.connection_canvas; palette = self.palette_getter(); canvas.delete("all"); canvas.configure(background=palette["surface"], highlightbackground="#D8DEE5")
        width = max(canvas.winfo_width(), 320); height = max(canvas.winfo_height(), 280); center_x, center_y = width // 2, height // 2
        rows = connection_rows(self.catalog_getter(), self.item, self.traceability_getter())[:8]
        canvas.create_rectangle(center_x-70, center_y-24, center_x+70, center_y+24, outline=palette["accent"], width=2)
        canvas.create_text(center_x, center_y, text=display(self.item.get("part_name"))[:26], fill=palette["fg"], font=("Segoe UI", 9, "bold"))
        for index, row in enumerate(rows):
            side = -1 if index % 2 == 0 else 1; lane = index // 2; y = 35 + lane * 58; x = center_x + side * 125
            canvas.create_line(center_x + side*70, center_y, x - side*55, y, fill=palette["muted"], arrow="last")
            canvas.create_rectangle(x-55, y-18, x+55, y+18, outline="#D8DEE5")
            canvas.create_text(x, y, text=display(row.get("name"))[:22], width=100, fill=palette["fg"], font=("Segoe UI", 7))

    def _refresh_alternatives(self) -> None:
        by_id = item_index(self.catalog_getter()); ids = alternative_ids(self.catalog_getter(), self.hardware_id)
        values = [f"{display(by_id.get(i, {}).get('part_name'))} · {i}" for i in ids]
        self.alt_combo.configure(values=values)
        if self.alt_var.get() not in values: self.alt_var.set(values[0] if values else "Alternatif bulunamadı")
        self._render_alternative_comparison()

    def _selected_alt_id(self) -> str:
        value = self.alt_var.get(); return value.rsplit(" · ", 1)[-1] if " · " in value else ""

    def _render_alternative_comparison(self) -> None:
        tree = self._trees["alternatives"]; tree.delete(*tree.get_children()); alt_id = self._selected_alt_id()
        if not alt_id:
            tree.insert("", "end", values=(MISSING_VALUE,)*5); return
        tags = {"Olumlu": "positive", "Olumsuz": "negative", "Kritik uyumsuzluk": "critical", "Veri eksik": "missing"}
        for row in alternative_comparison_rows(self.catalog_getter(), self.hardware_id, alt_id): tree.insert("", "end", values=tuple(row[k] for k in ("parameter", "current", "alternative", "unit", "assessment")), tags=(tags.get(row["assessment"], "neutral"),))

    def _refresh_gallery(self) -> None:
        self._gallery = gallery_entries(self.item); self._gallery_index = min(self._gallery_index, max(0, len(self._gallery)-1)); self._gallery_zoom = 1.0; self._render_gallery()

    def _render_hero(self) -> None:
        canvas = self.hero_canvas; palette = self.palette_getter(); canvas.delete("all"); canvas.configure(background=palette["surface"], highlightbackground="#D8DEE5")
        path = clean_text(self.item.get("image_path")); photo = self._cached_photo(path, 176, 118)
        if photo:
            self._apply_hero_photo(path, photo)
        elif path and path != PLACEHOLDER_IMAGE and Path(path).is_file() and Image and ImageTk:
            canvas.create_text(92, 63, text="GÖRSEL YÜKLENİYOR…", fill=palette["muted"], font=("Consolas", 7))
            self._request_photo(path, 176, 118, lambda loaded, expected=path: self._apply_hero_photo(expected, loaded))
        else:
            canvas.create_rectangle(47, 22, 137, 96, outline=palette["muted"], width=2); canvas.create_text(92, 55, text="HW", fill=palette["accent"], font=("Consolas", 18, "bold")); canvas.create_text(92, 109, text="GÖRSEL BULUNAMADI", fill=palette["muted"], font=("Consolas", 7))

    def _apply_hero_photo(self, expected_path: str, photo: Any) -> None:
        if not photo or clean_text(self.item.get("image_path")) != expected_path:
            return
        canvas = self.hero_canvas; canvas.delete("all")
        canvas.create_image(92, 63, image=photo); canvas._photo = photo
        if self.item.get("image_is_generated"):
            canvas.create_rectangle(5, 101, 92, 120, fill="#FFF2CC", outline="")
            canvas.create_text(48, 111, text="AI KAVRAMSAL", fill="#9A6400", font=("Consolas", 7, "bold"))

    def _cached_photo(self, path: str, width: int, height: int) -> Any:
        if not Image or not ImageTk or not path or path == PLACEHOLDER_IMAGE or not Path(path).is_file(): return None
        key = (path, width, height)
        if key in self._thumbnail_cache:
            self._thumbnail_cache.move_to_end(key); return self._thumbnail_cache[key]
        return None

    def _request_photo(
        self, path: str, width: int, height: int, callback: Callable[[Any], None],
    ) -> None:
        cached = self._cached_photo(path, width, height)
        if cached:
            self.after_idle(lambda: callback(cached)); return
        key = (path, width, height)
        self._photo_callbacks.setdefault(key, []).append(callback)
        if key in self._photo_loading:
            return
        self._photo_loading.add(key)
        results: queue.Queue[tuple[Any, str]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                with Image.open(path) as source:
                    image = source.convert("RGBA")
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
                results.put((image, ""))
            except Exception as error:
                results.put((None, str(error)))

        threading.Thread(target=worker, daemon=True, name="donanim-thumbnail").start()
        self.after(40, lambda: self._poll_photo(key, results))

    def _poll_photo(self, key: tuple[str, int, int], results: queue.Queue) -> None:
        try:
            image, _error = results.get_nowait()
        except queue.Empty:
            self.after(40, lambda: self._poll_photo(key, results)); return
        self._photo_loading.discard(key)
        photo = ImageTk.PhotoImage(image) if image is not None and ImageTk else None
        if photo:
            self._thumbnail_cache[key] = photo
            while len(self._thumbnail_cache) > 16:
                self._thumbnail_cache.popitem(last=False)
        callbacks = self._photo_callbacks.pop(key, [])
        for callback in callbacks:
            callback(photo)

    def _render_gallery(self) -> None:
        canvas = self.gallery_canvas; palette = self.palette_getter(); canvas.delete("all"); canvas.configure(background=palette["surface"], highlightbackground="#D8DEE5")
        if not self._gallery:
            canvas.create_text(max(220, canvas.winfo_width()//2), max(150, canvas.winfo_height()//2), text="Görsel bulunamadı\nGerçek ürün görseli veya datasheet görseli bağlayabilirsiniz.", fill=palette["muted"], justify="center", font=("Segoe UI", 11)); self.gallery_meta.set("Görsel yok"); self.gallery_warning.set(""); return
        record = self._gallery[self._gallery_index]; path = record["path"]
        max_w, max_h = max(300, canvas.winfo_width()-40), max(220, canvas.winfo_height()-40)
        width, height = int(max_w*self._gallery_zoom), int(max_h*self._gallery_zoom)
        photo = self._cached_photo(path, width, height)
        if photo:
            self._apply_gallery_photo(path, photo)
        else:
            canvas.create_text(max(220, canvas.winfo_width()//2), max(150, canvas.winfo_height()//2), text="GÖRSEL ARKA PLANDA YÜKLENİYOR…", fill=palette["muted"], font=("Consolas", 8))
            self._request_photo(path, width, height, lambda loaded, expected=path: self._apply_gallery_photo(expected, loaded))

    def _apply_gallery_photo(self, expected_path: str, photo: Any) -> None:
        if not self._gallery or self._gallery[self._gallery_index]["path"] != expected_path:
            return
        canvas = self.gallery_canvas; canvas.delete("all")
        if not photo:
            self.gallery_meta.set("Görsel açılamadı veya desteklenmeyen biçim."); return
        self._gallery_photo = photo; canvas.create_image(20, 20, image=photo, anchor="nw", tags="image")
        canvas.configure(scrollregion=(0, 0, max(canvas.winfo_width(), photo.width()+40), max(canvas.winfo_height(), photo.height()+40)))
        record = self._gallery[self._gallery_index]
        label = "AI KAVRAMSAL GÖRSEL" if record["is_ai"] else "GERÇEK / BELGE GÖRSELİ"
        provider = f" · {display(record.get('provider'))} / {display(record.get('model'))}" if record["is_ai"] else ""
        self.gallery_meta.set(f"{self._gallery_index+1}/{len(self._gallery)} · {label}{provider} · {display(record['source_document'])} · {display(record['created_at'])}")
        self.gallery_warning.set(
            clean_text(record.get("warning"), "Yapay zekâ tarafından oluşturulmuş kavramsal görseldir. Teknik doğrulama amacıyla kullanılamaz.")
            if record["is_ai"] else ""
        )

    def _gallery_move(self, step: int) -> None:
        if self._gallery: self._gallery_index = (self._gallery_index + step) % len(self._gallery); self._gallery_zoom = 1.0; self._render_gallery()

    def _gallery_wheel(self, event: tk.Event) -> str: self._set_zoom(1.15 if event.delta > 0 else .87); return "break"
    def _set_zoom(self, multiplier: float) -> None: self._gallery_zoom = min(5.0, max(.2, self._gallery_zoom * multiplier)); self._render_gallery()

    def _gallery_fullscreen(self) -> None:
        if not self._gallery: return
        top = tk.Toplevel(self); top.title(f"Görsel · {display(self.item.get('part_name'))}"); top.attributes("-fullscreen", True)
        canvas = tk.Canvas(top, background="#111318", highlightthickness=0); canvas.pack(fill="both", expand=True)
        top.update_idletasks(); path = self._gallery[self._gallery_index]["path"]
        def show(photo: Any) -> None:
            if photo and top.winfo_exists():
                canvas.create_image(top.winfo_width()//2, top.winfo_height()//2, image=photo); canvas._photo = photo
        self._request_photo(path, max(320, top.winfo_width()-60), max(240, top.winfo_height()-60), show)
        ttk.Button(top, text="Tam Ekrandan Çık", command=top.destroy).place(relx=.98, rely=.03, anchor="ne"); top.bind("<Escape>", lambda _event: top.destroy())

    def _save_gallery_file(self) -> None:
        if not self._gallery: return
        source = Path(self._gallery[self._gallery_index]["path"]); target = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Görseli kaydet", initialfile=source.name, defaultextension=source.suffix)
        if target:
            try: shutil.copy2(source, target); messagebox.showinfo("Görsel Kaydedildi", f"Görsel kaydedildi:\n{target}", parent=self.winfo_toplevel())
            except OSError as error: messagebox.showerror("Görsel Kaydedilemedi", str(error), parent=self.winfo_toplevel())

    def _gallery_action(self, action: str) -> None:
        if not self._gallery:
            return
        self.image_callback(
            self.hardware_id,
            f"{action}::{self._gallery[self._gallery_index]['path']}",
        )

    def _image_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False); menu.add_command(label="Dosyadan gerçek görsel seç", command=lambda: self.image_callback(self.hardware_id, "select")); menu.add_command(label="Gemma promptu + ayrı sağlayıcı ile AI görseli oluştur", command=lambda: self.image_callback(self.hardware_id, "generate")); menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def select_tab(self, key: str) -> None:
        for index, (tab_key, _title) in enumerate(TABS):
            if tab_key == key:
                self.notebook.select(index); self.tab_selector_var.set(TABS[index][1]); break

    def _selector_tab_changed(self, _event: tk.Event | None = None) -> None:
        title = self.tab_selector_var.get()
        for key, tab_title in TABS:
            if tab_title == title:
                self.select_tab(key); break

    def _update_navigation(self) -> None:
        ids = [clean_text(item.get("hardware_id")) for item in self.catalog_getter().get("hardware_items", []) if isinstance(item, Mapping)]
        try: index = ids.index(self.hardware_id)
        except ValueError: index = -1
        self.prev_button.configure(state="normal" if index > 0 else "disabled"); self.next_button.configure(state="normal" if 0 <= index < len(ids)-1 else "disabled")

    def _move(self, step: int) -> None:
        ids = [clean_text(item.get("hardware_id")) for item in self.catalog_getter().get("hardware_items", []) if isinstance(item, Mapping)]
        if self.hardware_id in ids:
            target = ids.index(self.hardware_id)+step
            if 0 <= target < len(ids): self.open(ids[target], TABS[self.notebook.index(self.notebook.select())][0])

    def _selected_requirement(self) -> str:
        selection = self._trees["requirements"].selection(); return selection[0][5:] if selection and selection[0].startswith("REQ::") else ""

    def _open_requirement(self) -> None:
        requirement_id = self._selected_requirement()
        if requirement_id: self.requirement_callback(requirement_id)
        else: messagebox.showinfo("Gereksinim", "Önce bir gereksinim satırı seçin.", parent=self.winfo_toplevel())

    def _simulate_requirement(self) -> None:
        requirement_id = self._selected_requirement()
        if requirement_id: self.requirement_callback(requirement_id)
        else: messagebox.showinfo("Etki Analizi", "Simüle edilecek gereksinimi seçin.", parent=self.winfo_toplevel())

    def _open_selected_alternative(self) -> None:
        alt_id = self._selected_alt_id()
        if alt_id: self.open(alt_id, "overview")

    def _simulate_alternative(self) -> None:
        alt_id = self._selected_alt_id()
        if alt_id: self.impact_callback(self.hardware_id, alt_id)
        else: messagebox.showinfo("Alternatif", "Simüle edilecek alternatif bulunamadı.", parent=self.winfo_toplevel())

    def _open_source(self) -> None:
        selection = self._trees["sources"].selection()
        if not selection or not selection[0].startswith("SRC::"): messagebox.showinfo("Kaynak", "Önce bir kaynak satırı seçin.", parent=self.winfo_toplevel()); return
        record = self._source_records[int(selection[0].split("::", 1)[1])]; path = Path(clean_text(record.get("path"))).expanduser()
        if not path.is_file(): messagebox.showwarning("Kaynak Bulunamadı", "Kaynak dosyanın tam yolu bulunamadı veya dosya taşınmış.", parent=self.winfo_toplevel()); return
        try: webbrowser.open(path.resolve().as_uri())
        except Exception as error: messagebox.showerror("Kaynak Açılamadı", str(error), parent=self.winfo_toplevel())

    def start_edit(self) -> None:
        self.editing = True; self.dirty = False
        for field, _label in self.EDIT_FIELDS: self._edit_vars[field].set("" if is_missing(self.item.get(field)) else clean_text(self.item.get(field)))
        self.dirty = False
        self.edit_frame.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.trace_bar.grid_configure(row=4)
        self.notebook.grid_configure(row=5)
        self.rowconfigure(4, weight=0); self.rowconfigure(5, weight=1)

    def _mark_dirty(self, *_args: Any) -> None:
        if self.editing: self.dirty = True

    def cancel_edit(self) -> None:
        if self.dirty and not messagebox.askyesno("Düzenlemeyi İptal Et", "Kaydedilmemiş değişiklikler silinsin mi?", parent=self.winfo_toplevel()): return
        self.editing = False; self.dirty = False; self.edit_frame.grid_forget()
        self.trace_bar.grid_configure(row=3); self.notebook.grid_configure(row=4)
        self.rowconfigure(4, weight=1); self.rowconfigure(5, weight=0)

    def save_edit(self) -> None:
        name = self._edit_vars["part_name"].get().strip()
        if not name: messagebox.showwarning("Eksik Bilgi", "Parça adı boş bırakılamaz.", parent=self.winfo_toplevel()); return
        values = {field: variable.get().strip() or MISSING_VALUE for field, variable in self._edit_vars.items()}
        self.save_callback(self.hardware_id, values); self.editing = False; self.dirty = False
        self.edit_frame.grid_forget(); self.trace_bar.grid_configure(row=3); self.notebook.grid_configure(row=4)
        self.rowconfigure(4, weight=1); self.rowconfigure(5, weight=0); self.refresh()

    def request_back(self) -> None:
        if self.editing and self.dirty and not messagebox.askyesno("Kaydedilmemiş Değişiklik", "Kaydetmeden katalog ekranına dönülsün mü?", parent=self.winfo_toplevel()): return
        self.editing = False; self.dirty = False; self.back_callback()

    def _export(self, kind: str) -> None:
        name = "_".join(display(self.item.get("part_name")).split()) or "donanim_karti"; ext = ".pdf" if kind == "pdf" else ".xlsx"
        path = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Donanım kartını kaydet", initialfile=f"{name}{ext}", defaultextension=ext, filetypes=(("PDF", "*.pdf"),) if kind == "pdf" else (("Excel", "*.xlsx"),))
        if not path: return
        self._export_token += 1; token = self._export_token; results: queue.Queue[tuple[Path | None, str]] = queue.Queue(maxsize=1)
        catalog, report, overrides, hardware_id = dict(self.catalog_getter()), dict(self.traceability_getter()), dict(self.overrides_getter()), self.hardware_id
        def worker() -> None:
            try: target = export_hardware_pdf(path, catalog, hardware_id, report, overrides) if kind == "pdf" else export_hardware_excel(path, catalog, hardware_id, report, overrides); results.put((target, ""))
            except Exception as error: results.put((None, str(error)))
        threading.Thread(target=worker, daemon=True, name=f"donanim-{kind}-aktar").start(); self.after(60, lambda: self._poll_export(token, results))

    def _poll_export(self, token: int, results: queue.Queue) -> None:
        if token != self._export_token: return
        try: target, error = results.get_nowait()
        except queue.Empty: self.after(60, lambda: self._poll_export(token, results)); return
        if error: messagebox.showerror("Rapor Kaydedilemedi", f"Rapor kaydedilemedi. Dosya başka bir programda açık olabilir.\n\n{error}", parent=self.winfo_toplevel())
        else: messagebox.showinfo("Rapor Kaydedildi", f"Dosya kaydedildi:\n{target}", parent=self.winfo_toplevel())

    def apply_theme(self) -> None:
        palette = self.palette_getter(); dark = palette["bg"].lower() == "#1f2329"; border = "#3D4550" if dark else "#D8DEE5"; selected = "#234B72" if dark else "#E8F1FC"
        for style_name, background in (("HardwareDetailNav.TFrame", palette["surface"]), ("HardwareDetailSurface.TFrame", palette["surface"]), ("HardwareDetailToolbar.TFrame", palette["surface"]), ("HardwareDetailEdit.TFrame", palette["bg"]), ("HardwareDetailTrace.TFrame", palette["bg"])): self.style.configure(style_name, background=background, bordercolor=border)
        for style_name, background, foreground, font in (("HardwareDetailBreadcrumb.TLabel", palette["surface"], palette["muted"], ("Consolas", 9)), ("HardwareDetailHeroTitle.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 19, "bold")), ("HardwareDetailMono.TLabel", palette["surface"], palette["fg"], ("Consolas", 9)), ("HardwareDetailBody.TLabel", palette["surface"], palette["fg"], ("Segoe UI", 10)), ("HardwareDetailSection.TLabel", palette["surface"], palette["fg"], ("Consolas", 9, "bold")), ("HardwareDetailEdit.TLabel", palette["bg"], palette["fg"], ("Segoe UI", 8)), ("HardwareDetailTraceArrow.TLabel", palette["bg"], palette["muted"], ("Consolas", 10)), ("HardwareDetailWarning.TLabel", "#FFF2CC", "#8A5A00", ("Segoe UI", 8, "bold"))): self.style.configure(style_name, background=background, foreground=foreground, font=font)
        self.style.configure("HardwareDetail.Treeview", background=palette["surface"], fieldbackground=palette["surface"], foreground=palette["fg"], rowheight=27, bordercolor=border, font=("Consolas", 8)); self.style.configure("HardwareDetail.Treeview.Heading", background=palette["bg"], foreground=palette["fg"], bordercolor=border, font=("Segoe UI", 8, "bold")); self.style.map("HardwareDetail.Treeview", background=[("selected", selected)], foreground=[("selected", palette["fg"])])
        self.style.configure("HardwareOverview.Treeview", background=palette["surface"], fieldbackground=palette["surface"], foreground=palette["fg"], rowheight=42, bordercolor=border, font=("Segoe UI", 9))
        if "alternatives" in self._trees:
            for tag, color in (("positive", "#217A43"), ("negative", "#B54708"), ("critical", "#B42318"), ("missing", palette["muted"]), ("neutral", palette["fg"])):
                self._trees["alternatives"].tag_configure(tag, foreground=color)
        self.style.configure("HardwareDetail.TNotebook", background=palette["surface"], bordercolor=border); self.style.configure("HardwareDetail.TNotebook.Tab", background=palette["bg"], foreground=palette["muted"], padding=(9, 7), font=("Segoe UI", 8, "bold")); self.style.map("HardwareDetail.TNotebook.Tab", background=[("selected", palette["surface"])], foreground=[("selected", palette["accent"])])
        self.style.configure("HardwareDetailTrace.TButton", font=("Consolas", 9, "bold"), padding=(8, 3))


__all__ = ["HardwareDetailedReview", "TABS"]
