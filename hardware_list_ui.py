# -*- coding: utf-8 -*-
"""Akıllı Donanım Listesi çalışma alanı.

SGD/STT öneri üretimi, mühendis incelemesi, uyumluluk kapısı ve BOM dışa
aktarımı için tamamlanmış çalışma alanını sağlar.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Mapping

import hardware_list_logic
import hardware_review_ui


_COLUMN_DEFINITIONS = (
    ("ID", "ID", "ID", 90, "center"),
    ("category", "Kategori", "Category", 150, "w"),
    ("description", "Donanım Tanımı", "Hardware Description", 330, "w"),
    ("quantity", "Adet", "Qty", 60, "center"),
    ("requirements", "Bağlı Gereksinimler", "Linked Requirements", 180, "w"),
    ("risk", "Risk", "Risk", 80, "center"),
    ("status", "Durum", "Status", 100, "center"),
)

_STATUS_LABELS = {
    "Önerilen": ("Önerilen", "Suggested"),
    "İnceleniyor": ("İnceleniyor", "In Review"),
    "Onaylandı": ("Onaylandı", "Approved"),
    "Reddedildi": ("Reddedildi", "Rejected"),
}

_RISK_LABELS = {
    "Belirsiz": ("Belirsiz", "Unknown"),
    "Düşük": ("Düşük", "Low"),
    "Orta": ("Orta", "Medium"),
    "Yüksek": ("Yüksek", "High"),
}


def _shorten(text: str, limit: int = 100) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _record_has_dsb(item: hardware_list_logic.HardwareItem) -> bool:
    return (
        hardware_list_logic.DSB
        in {item.description, item.manufacturer, item.part_number, item.rationale}
        or any(
            value == hardware_list_logic.DSB
            for value in item.specifications.values()
        )
    )


def build_hardware_table_rows(
    hardware_data: Mapping[str, Mapping[str, Any]],
    search_text: str = "",
    status_filter: str = "",
) -> list[dict[str, Any]]:
    """UI tablosu için normalize edilmiş, filtrelenmiş satırlar döndürür."""
    query = " ".join(str(search_text or "").casefold().split())
    rows: list[dict[str, Any]] = []

    for fallback_id, raw in hardware_data.items():
        if not isinstance(raw, Mapping):
            continue
        try:
            item = hardware_list_logic.normalize_hardware_item(
                raw, raw.get("ID") or fallback_id
            )
        except (TypeError, ValueError):
            continue
        if status_filter and item.status != status_filter:
            continue

        searchable = " ".join([
            item.item_id,
            item.category,
            item.description,
            item.manufacturer,
            item.part_number,
            " ".join(item.linked_requirements),
        ]).casefold()
        if query and query not in searchable:
            continue

        rows.append({
            "ID": item.item_id,
            "category": item.category,
            "description": _shorten(item.description),
            "quantity": item.quantity,
            "requirements": ", ".join(item.linked_requirements) or "—",
            "risk": item.risk,
            "status": item.status,
            "has_dsb": _record_has_dsb(item),
        })

    return rows


class HardwareWorkspace:
    """Donanım listesini tablo, özet ve izlenebilirlik ayrıntısıyla gösterir."""

    def __init__(
        self,
        master: tk.Misc,
        style: ttk.Style,
        hardware_data: dict[str, dict[str, Any]],
        flat_data: Mapping[str, Mapping[str, Any]],
        language_getter: Callable[[], str],
        palette_getter: Callable[[], Mapping[str, str]],
        project_name_getter: Callable[[], str] | None = None,
        generate_callback: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.master = master
        self.style = style
        self.hardware_data = hardware_data
        self.flat_data = flat_data
        self.language_getter = language_getter
        self.palette_getter = palette_getter
        self.project_name_getter = project_name_getter or (lambda: "Proje")
        self.generate_callback = generate_callback
        self.on_close = on_close
        self._translatable: list[tuple[tk.Widget, str, str]] = []
        self._selected_status = ""
        self._generation_running = False

        self.window = tk.Toplevel(master)
        self.window.geometry("1180x720")
        self.window.minsize(980, 620)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.search_var = tk.StringVar()
        self.summary_vars = {
            key: tk.StringVar(value="0")
            for key in (
                "total",
                "suggested",
                "in_review",
                "approved",
                "with_dsb",
                "high_risk",
            )
        }
        self.detail_title_var = tk.StringVar()
        self.trace_var = tk.StringVar()
        self.generation_status_var = tk.StringVar()
        self.compatibility_status_var = tk.StringVar()

        self._build()
        self.apply_theme()
        self.refresh_language()
        self.refresh()
        self.search_entry.focus_set()

    @property
    def exists(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        if not self.exists:
            return
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

    def _label(
        self,
        parent: tk.Misc,
        tr_text: str,
        en_text: str,
        **kwargs: Any,
    ) -> ttk.Label:
        widget = ttk.Label(parent, text=self._tr(tr_text, en_text), **kwargs)
        self._translatable.append((widget, tr_text, en_text))
        return widget

    def _button(
        self,
        parent: tk.Misc,
        tr_text: str,
        en_text: str,
        **kwargs: Any,
    ) -> ttk.Button:
        widget = ttk.Button(parent, text=self._tr(tr_text, en_text), **kwargs)
        self._translatable.append((widget, tr_text, en_text))
        return widget

    def _build(self) -> None:
        root = ttk.Frame(self.window, style="light.TFrame", padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        header = ttk.Frame(root, style="light.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title_group = ttk.Frame(header, style="light.TFrame")
        title_group.grid(row=0, column=0, sticky="w")
        self._label(
            title_group,
            "Akıllı Donanım Listesi",
            "Smart Hardware List",
            style="HardwareTitle.TLabel",
        ).pack(anchor="w")
        self._label(
            title_group,
            "SGD ve STT gereksinimlerine tahsis edilen donanımlar",
            "Hardware allocated to SGD and STT requirements",
            style="HardwareMuted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        self._label(
            header,
            "SGD / STT  →  DONANIM  →  DOĞRULAMA",
            "SGD / STT  →  HARDWARE  →  VERIFICATION",
            style="HardwareTrace.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))

        summary = ttk.Frame(root, style="light.TFrame")
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for index in range(6):
            summary.columnconfigure(index, weight=1, uniform="hardware-summary")

        summary_items = (
            ("total", "Toplam", "Total"),
            ("suggested", "Önerilen", "Suggested"),
            ("in_review", "İncelenen", "In Review"),
            ("approved", "Onaylı", "Approved"),
            ("with_dsb", "DSB İçeren", "With DSB"),
            ("high_risk", "Yüksek Risk", "High Risk"),
        )
        for index, (key, tr_text, en_text) in enumerate(summary_items):
            cell = ttk.Frame(
                summary,
                style="HardwareMetric.TFrame",
                padding=(12, 8),
                borderwidth=1,
                relief="solid",
            )
            cell.grid(
                row=0,
                column=index,
                sticky="ew",
                padx=(0 if index == 0 else 4, 0),
            )
            ttk.Label(
                cell,
                textvariable=self.summary_vars[key],
                style="HardwareMetricValue.TLabel",
            ).pack(anchor="w")
            self._label(
                cell,
                tr_text,
                en_text,
                style="HardwareMetricLabel.TLabel",
            ).pack(anchor="w")

        toolbar = ttk.Frame(root, style="light.TFrame")
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(1, weight=1)
        self._label(
            toolbar,
            "Ara:",
            "Search:",
            style="HardwareBody.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(6, 16))
        self.search_entry.bind("<KeyRelease>", lambda _event: self.refresh())

        self._label(
            toolbar,
            "Durum:",
            "Status:",
            style="HardwareBody.TLabel",
        ).grid(row=0, column=2, sticky="e")
        self.status_combo = ttk.Combobox(toolbar, state="readonly", width=16)
        self.status_combo.grid(row=0, column=3, padx=(6, 12))
        self.status_combo.bind("<<ComboboxSelected>>", self._on_status_selected)

        self.generate_button = ttk.Button(
            toolbar,
            command=self._request_generation,
            style="primary.TButton",
            width=16,
        )
        self.generate_button.grid(row=0, column=4, padx=(0, 8))

        self._button(
            toolbar,
            "Yenile",
            "Refresh",
            command=self.refresh,
            style="primary.Outline.TButton",
            width=10,
        ).grid(row=0, column=5)

        self.generation_progress = ttk.Progressbar(
            toolbar,
            mode="indeterminate",
            length=180,
        )
        self.generation_progress.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )
        self.generation_progress.grid_remove()
        ttk.Label(
            toolbar,
            textvariable=self.generation_status_var,
            style="HardwareStatus.TLabel",
        ).grid(
            row=1,
            column=2,
            columnspan=4,
            sticky="w",
            pady=(8, 0),
        )

        gate = ttk.Frame(
            root, style="HardwareGate.TFrame", padding=(10, 8),
            borderwidth=1, relief="solid",
        )
        gate.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        gate.columnconfigure(1, weight=1)
        self._label(
            gate, "MÜHENDİSLİK KAPISI", "ENGINEERING GATE",
            style="HardwareGateTitle.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(
            gate, textvariable=self.compatibility_status_var,
            style="HardwareGateStatus.TLabel",
        ).grid(row=0, column=1, sticky="w")
        self._button(
            gate, "Uyumluluğu Denetle", "Check Compatibility",
            command=self._show_compatibility_report,
            style="primary.Outline.TButton", width=18,
        ).grid(row=0, column=2, padx=(8, 6))
        self._button(
            gate, "Excel BOM", "Excel BOM",
            command=lambda: self._export_hardware("excel"),
            style="primary.Outline.TButton", width=12,
        ).grid(row=0, column=3, padx=(0, 6))
        self._button(
            gate, "DOORS BOM", "DOORS BOM",
            command=lambda: self._export_hardware("doors"),
            style="primary.Outline.TButton", width=12,
        ).grid(row=0, column=4)

        paned = ttk.Panedwindow(root, orient="horizontal")
        paned.grid(row=4, column=0, sticky="nsew")

        table_panel = ttk.Frame(
            paned,
            style="HardwarePanel.TFrame",
            padding=1,
            borderwidth=1,
            relief="solid",
        )
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(0, weight=1)
        paned.add(table_panel, weight=3)

        columns = [definition[0] for definition in _COLUMN_DEFINITIONS]
        self.tree = ttk.Treeview(
            table_panel,
            columns=columns,
            show="headings",
            style="Hardware.Treeview",
            selectmode="browse",
        )
        for key, tr_text, _en_text, width, anchor in _COLUMN_DEFINITIONS:
            self.tree.heading(key, text=tr_text)
            self.tree.column(
                key,
                width=width,
                minwidth=55,
                anchor=anchor,
                stretch=key in {"category", "description", "requirements"},
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._render_selected_item)

        vertical = ttk.Scrollbar(
            table_panel, orient="vertical", command=self.tree.yview
        )
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            table_panel, orient="horizontal", command=self.tree.xview
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        self.empty_label = ttk.Label(
            table_panel,
            justify="center",
            style="HardwareEmpty.TLabel",
        )

        detail_panel = ttk.Frame(
            paned,
            style="HardwarePanel.TFrame",
            padding=14,
            borderwidth=1,
            relief="solid",
            width=330,
        )
        detail_panel.columnconfigure(0, weight=1)
        detail_panel.rowconfigure(4, weight=1)
        paned.add(detail_panel, weight=1)

        self._label(
            detail_panel,
            "Kayıt Ayrıntısı",
            "Record Detail",
            style="HardwareSection.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            detail_panel,
            textvariable=self.detail_title_var,
            style="HardwareDetailTitle.TLabel",
            wraplength=300,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 4))
        ttk.Label(
            detail_panel,
            textvariable=self.trace_var,
            style="HardwareTrace.TLabel",
            wraplength=300,
        ).grid(row=2, column=0, sticky="ew", pady=(0, 10))

        review_actions = ttk.Frame(detail_panel, style="HardwarePanel.TFrame")
        review_actions.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        review_actions.columnconfigure(0, weight=1)
        review_actions.columnconfigure(1, weight=1)
        self.review_button = self._button(
            review_actions, "İncelemeye Al", "Start Review",
            command=lambda: self._set_selected_status("İnceleniyor"),
            style="primary.Outline.TButton", width=13,
        )
        self.review_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        self.edit_button = self._button(
            review_actions, "Düzenle", "Edit",
            command=self._edit_selected_item,
            style="primary.Outline.TButton", width=13,
        )
        self.edit_button.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 4))
        self.approve_button = self._button(
            review_actions, "Onayla", "Approve",
            command=lambda: self._set_selected_status("Onaylandı"),
            style="success.TButton", width=13,
        )
        self.approve_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))
        self.reject_button = self._button(
            review_actions, "Reddet", "Reject",
            command=lambda: self._set_selected_status("Reddedildi"),
            style="danger.Outline.TButton", width=13,
        )
        self.reject_button.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(4, 0))

        self.detail_text = tk.Text(
            detail_panel, wrap="word", state=tk.DISABLED, relief="flat",
            borderwidth=0, font=("Segoe UI", 10), padx=0, pady=0, cursor="arrow",
        )
        self.detail_text.grid(row=4, column=0, sticky="nsew")
        self.detail_text.tag_configure(
            "label", font=("Segoe UI", 9, "bold"), spacing1=8
        )
        self.detail_text.tag_configure("value", font=("Segoe UI", 10))
        self.detail_text.tag_configure(
            "warning", font=("Segoe UI", 9, "italic"), spacing1=6
        )

    def refresh_language(self) -> None:
        if not self.exists:
            return
        self.window.title(
            self._tr("Akıllı Donanım Listesi", "Smart Hardware List")
        )
        for widget, tr_text, en_text in self._translatable:
            try:
                widget.configure(text=self._tr(tr_text, en_text))
            except tk.TclError:
                pass

        for key, tr_text, en_text, _width, _anchor in _COLUMN_DEFINITIONS:
            self.tree.heading(key, text=self._tr(tr_text, en_text))

        selected_index = self._status_option_index(self._selected_status)
        self.status_combo.configure(values=[
            self._tr("Tümü", "All"),
            *[
                self._tr(*_STATUS_LABELS[status])
                for status in hardware_list_logic.HARDWARE_STATUSES
            ],
        ])
        self.status_combo.current(selected_index)
        self._update_generation_controls()
        self.refresh()

    def _update_generation_controls(self) -> None:
        if not self.exists:
            return
        if self._generation_running:
            text = self._tr("Üretiliyor…", "Generating…")
            state = tk.DISABLED
        else:
            text = self._tr("Öneri Oluştur", "Generate Suggestions")
            state = tk.NORMAL if self.generate_callback else tk.DISABLED
        self.generate_button.configure(text=text, state=state)

    def _request_generation(self) -> None:
        if self._generation_running:
            return
        if not self.generate_callback:
            self.generation_status_var.set(
                self._tr(
                    "Öneri üretimi bu oturumda kullanılamıyor.",
                    "Suggestion generation is unavailable in this session.",
                )
            )
            return
        self.generate_callback()

    def set_generation_state(
        self,
        running: bool,
        message: str = "",
    ) -> None:
        """Üretim denetimlerini tek noktadan günceller."""
        if not self.exists:
            return
        self._generation_running = bool(running)
        self.generation_status_var.set(message)
        if self._generation_running:
            self.generation_progress.grid()
            self.generation_progress.start(12)
        else:
            self.generation_progress.stop()
            self.generation_progress.grid_remove()
        self._update_generation_controls()
        self._update_action_controls()

    def _known_requirement_ids(self) -> list[str]:
        return [record["requirement_id"] for record in hardware_list_logic.eligible_requirement_records(self.flat_data)]

    def _selected_item_id(self) -> str:
        selected = self.tree.selection()
        return selected[0] if selected else ""

    def _update_action_controls(self) -> None:
        if not self.exists or not hasattr(self, "review_button"):
            return
        item_id = self._selected_item_id()
        raw = self.hardware_data.get(item_id)
        if self._generation_running or not isinstance(raw, Mapping):
            for button in (self.review_button, self.edit_button, self.approve_button, self.reject_button):
                button.configure(state=tk.DISABLED)
            return
        item = hardware_list_logic.normalize_hardware_item(raw, item_id)
        self.edit_button.configure(state=tk.NORMAL)
        self.review_button.configure(state=tk.DISABLED if item.status == "İnceleniyor" else tk.NORMAL)
        self.approve_button.configure(state=tk.DISABLED if item.status == "Onaylandı" else tk.NORMAL)
        self.reject_button.configure(state=tk.DISABLED if item.status == "Reddedildi" else tk.NORMAL)

    def _set_selected_status(self, target_status: str) -> None:
        item_id = self._selected_item_id()
        if not item_id:
            return
        note = ""
        if target_status == "Reddedildi":
            note = simpledialog.askstring(
                self._tr("Reddetme Gerekçesi", "Rejection Reason"),
                self._tr("Bu donanım kaydı neden reddediliyor?", "Why is this hardware record being rejected?"),
                parent=self.window,
            )
            if note is None:
                return
        try:
            hardware_list_logic.transition_hardware_status(
                self.hardware_data, item_id, target_status,
                known_requirement_ids=self._known_requirement_ids(), review_note=note,
            )
        except (KeyError, TypeError, ValueError) as error:
            messagebox.showerror(self._tr("Mühendislik Kapısı", "Engineering Gate"), str(error), parent=self.window)
            return
        self.generation_status_var.set(self._tr(
            f"{item_id} durumu '{target_status}' olarak güncellendi.",
            f"{item_id} status was updated.",
        ))
        self.refresh()

    def _edit_selected_item(self) -> None:
        item_id = self._selected_item_id()
        raw = self.hardware_data.get(item_id)
        if not item_id or not isinstance(raw, Mapping):
            return
        try:
            item = hardware_list_logic.normalize_hardware_item(raw, item_id)
        except (TypeError, ValueError) as error:
            messagebox.showerror(self._tr("Kayıt Hatası", "Record Error"), str(error), parent=self.window)
            return
        hardware_review_ui.HardwareEditorDialog(
            master=self.window, style=self.style, item=item,
            known_requirement_ids=self._known_requirement_ids(),
            language_getter=self.language_getter, palette_getter=self.palette_getter,
            save_callback=self._save_edited_item,
        )

    def _save_edited_item(self, item_id: str, changes: Mapping[str, Any]) -> None:
        hardware_list_logic.update_hardware_record(self.hardware_data, item_id, changes, mark_in_review=True)
        self.generation_status_var.set(self._tr(
            f"{item_id} kaydedildi ve incelemeye alındı.",
            f"{item_id} was saved and returned to review.",
        ))
        self.refresh()

    def _show_compatibility_report(self) -> None:
        issues = hardware_list_logic.hardware_compatibility_report(self.hardware_data, self.flat_data)
        hardware_review_ui.show_compatibility_report(
            self.window, self.style, issues, self.language_getter(), self.palette_getter()
        )

    def _export_hardware(self, export_format: str) -> None:
        result = hardware_review_ui.export_hardware_with_dialog(
            master=self.window, export_format=export_format,
            registry=self.hardware_data, flat_data=self.flat_data,
            project_name=self.project_name_getter() or "Proje",
            language=self.language_getter(),
        )
        if result:
            self.generation_status_var.set(self._tr(
                f"{result['record_count']} kayıt dışa aktarıldı.",
                f"Exported {result['record_count']} records.",
            ))

    def apply_theme(self) -> None:
        if not self.exists:
            return
        palette = self.palette_getter()
        dark = palette["bg"].lower() == "#1f2329"
        border = "#3D4550" if dark else "#D8DEE5"
        selected = "#234B72" if dark else "#D9EAFB"
        graphite = "#BBC4CC" if dark else "#3F4852"
        warning = "#F0B44D" if dark else "#9A6400"
        danger = "#FF7B72" if dark else "#B42318"
        success = "#66C58A" if dark else "#217A43"

        self.window.configure(background=palette["bg"])
        self.style.configure("HardwareTitle.TLabel", background=palette["bg"],
                             foreground=palette["fg"], font=("Segoe UI", 16, "bold"))
        self.style.configure("HardwareBody.TLabel", background=palette["bg"],
                             foreground=palette["fg"], font=("Segoe UI", 9))
        self.style.configure("HardwareMuted.TLabel", background=palette["bg"],
                             foreground=palette["muted"], font=("Segoe UI", 9))
        self.style.configure("HardwareStatus.TLabel", background=palette["bg"],
                             foreground=palette["muted"], font=("Segoe UI", 8))
        self.style.configure("HardwareTrace.TLabel", background=palette["bg"],
                             foreground=palette["accent"], font=("Consolas", 9, "bold"))
        self.style.configure("HardwareMetric.TFrame", background=palette["surface"],
                             bordercolor=border)
        self.style.configure("HardwareMetricValue.TLabel", background=palette["surface"],
                             foreground=graphite, font=("Consolas", 14, "bold"))
        self.style.configure("HardwareMetricLabel.TLabel", background=palette["surface"],
                             foreground=palette["muted"], font=("Segoe UI", 8))
        self.style.configure("HardwarePanel.TFrame", background=palette["surface"],
                             bordercolor=border)
        self.style.configure("HardwareGate.TFrame", background=palette["surface"], bordercolor=border)
        self.style.configure("HardwareGateTitle.TLabel", background=palette["surface"], foreground=graphite, font=("Consolas", 9, "bold"))
        self.style.configure("HardwareGateStatus.TLabel", background=palette["surface"], foreground=palette["muted"], font=("Segoe UI", 9))
        self.style.configure("HardwareSection.TLabel", background=palette["surface"],
                             foreground=palette["muted"], font=("Segoe UI", 9, "bold"))
        self.style.configure("HardwareDetailTitle.TLabel", background=palette["surface"],
                             foreground=palette["fg"], font=("Segoe UI", 12, "bold"))
        self.style.configure("HardwareEmpty.TLabel", background=palette["surface"],
                             foreground=palette["muted"], font=("Segoe UI", 10))
        self.style.configure(
            "Hardware.Treeview",
            background=palette["surface"],
            fieldbackground=palette["surface"],
            foreground=palette["fg"],
            bordercolor=border,
            rowheight=30,
            font=("Segoe UI", 9),
        )
        self.style.configure(
            "Hardware.Treeview.Heading",
            background=palette["bg"],
            foreground=palette["fg"],
            bordercolor=border,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
        )
        self.style.map(
            "Hardware.Treeview",
            background=[("selected", selected)],
            foreground=[("selected", palette["fg"])],
        )

        self.tree.tag_configure("approved", foreground=success)
        self.tree.tag_configure("rejected", foreground=palette["muted"])
        self.tree.tag_configure("high_risk", foreground=danger)
        self.tree.tag_configure("with_dsb", foreground=warning)
        self.detail_text.configure(
            background=palette["surface"],
            foreground=palette["fg"],
            insertbackground=palette["fg"],
        )
        self.detail_text.tag_configure("label", foreground=palette["muted"])
        self.detail_text.tag_configure("value", foreground=palette["fg"])
        self.detail_text.tag_configure("warning", foreground=warning)

    def _status_option_index(self, status: str) -> int:
        if status in hardware_list_logic.HARDWARE_STATUSES:
            return hardware_list_logic.HARDWARE_STATUSES.index(status) + 1
        return 0

    def _on_status_selected(self, _event: tk.Event | None = None) -> None:
        index = self.status_combo.current()
        self._selected_status = (
            hardware_list_logic.HARDWARE_STATUSES[index - 1]
            if index > 0
            else ""
        )
        self.refresh()

    def refresh(self) -> None:
        if not self.exists:
            return
        try:
            summary = hardware_list_logic.hardware_registry_summary(
                self.hardware_data
            )
        except (TypeError, ValueError):
            summary = {key: 0 for key in self.summary_vars}
        for key, variable in self.summary_vars.items():
            variable.set(str(summary.get(key, 0)))
        issues = hardware_list_logic.hardware_compatibility_report(self.hardware_data, self.flat_data)
        issue_summary = hardware_list_logic.compatibility_summary(issues)
        self.compatibility_status_var.set(self._tr(
            f"{issue_summary['errors']} hata · {issue_summary['warnings']} uyarı",
            f"{issue_summary['errors']} errors · {issue_summary['warnings']} warnings",
        ))

        selected = self.tree.selection()
        previous_id = selected[0] if selected else ""
        self.tree.delete(*self.tree.get_children())

        rows = build_hardware_table_rows(
            self.hardware_data,
            search_text=self.search_var.get(),
            status_filter=self._selected_status,
        )
        for row in rows:
            tags: list[str] = []
            if row["status"] == "Onaylandı":
                tags.append("approved")
            elif row["status"] == "Reddedildi":
                tags.append("rejected")
            if row["risk"] == "Yüksek":
                tags.append("high_risk")
            elif row["has_dsb"]:
                tags.append("with_dsb")

            self.tree.insert(
                "",
                "end",
                iid=row["ID"],
                values=(
                    row["ID"],
                    row["category"],
                    row["description"],
                    row["quantity"],
                    row["requirements"],
                    self._tr(*_RISK_LABELS[row["risk"]]),
                    self._tr(*_STATUS_LABELS[row["status"]]),
                ),
                tags=tuple(tags),
            )

        if rows:
            self.empty_label.place_forget()
            target_id = (
                previous_id
                if previous_id and self.tree.exists(previous_id)
                else rows[0]["ID"]
            )
            self.tree.selection_set(target_id)
            self.tree.focus(target_id)
            self.tree.see(target_id)
            self._render_selected_item()
        else:
            self._clear_detail()
            message = (
                self._tr(
                    "Filtrelerle eşleşen donanım kaydı yok.",
                    "No hardware record matches the filters.",
                )
                if self.hardware_data
                else self._tr(
                    "Henüz donanım kaydı yok.\n"
                    "SGD/STT gereksinimlerinden oluşturulan öneriler burada görünecek.",
                    "No hardware records yet.\n"
                    "Suggestions created from SGD/STT requirements will appear here.",
                )
            )
            self.empty_label.configure(text=message)
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")

    def _clear_detail(self) -> None:
        self.detail_title_var.set(
            self._tr("Bir donanım kaydı seçin", "Select a hardware record")
        )
        self.trace_var.set(
            self._tr(
                "Gereksinim bağlantıları burada gösterilir.",
                "Requirement links are shown here.",
            )
        )
        self._set_detail_text(
            self._tr(
                "Tablodan bir kayıt seçildiğinde teknik özellikler, kaynak gereksinimler "
                "ve veri kalitesi uyarıları bu alanda görünür.",
                "Select a row to see specifications, source requirements, and data-quality "
                "warnings in this panel.",
            )
        )
        self._update_action_controls()

    def _render_selected_item(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            self._clear_detail()
            return
        item_id = selected[0]
        raw = self.hardware_data.get(item_id)
        if not isinstance(raw, Mapping):
            self._clear_detail()
            return
        try:
            item = hardware_list_logic.normalize_hardware_item(raw, item_id)
        except (TypeError, ValueError):
            self._clear_detail()
            return

        self.detail_title_var.set(f"{item.item_id} · {item.category}")
        linked = "  +  ".join(item.linked_requirements) or "—"
        self.trace_var.set(f"{linked}  →  {item.item_id}")

        known_ids = {
            record["requirement_id"]
            for record in hardware_list_logic.eligible_requirement_records(
                self.flat_data
            )
        }
        warnings = hardware_list_logic.validate_hardware_item(item, known_ids)
        blockers = hardware_list_logic.approval_blockers(item, known_ids)

        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self._insert_detail(
            self._tr("Tanım", "Description"), item.description
        )
        self._insert_detail(
            self._tr("Durum", "Status"),
            self._tr(*_STATUS_LABELS[item.status]),
        )
        self._insert_detail(
            self._tr("Risk", "Risk"),
            self._tr(*_RISK_LABELS[item.risk]),
        )
        self._insert_detail(
            self._tr("Üretici / Parça", "Manufacturer / Part"),
            f"{item.manufacturer} / {item.part_number}",
        )
        confidence = (
            f"%{round(item.confidence * 100)}"
            if item.confidence is not None
            else hardware_list_logic.DSB
        )
        self._insert_detail(
            self._tr("Öneri Güveni", "Suggestion Confidence"), confidence
        )

        self.detail_text.insert(
            tk.END, self._tr("Teknik Özellikler\n", "Specifications\n"), "label"
        )
        if item.specifications:
            for key, value in item.specifications.items():
                self.detail_text.insert(tk.END, f"• {key}: {value}\n", "value")
        else:
            self.detail_text.insert(tk.END, "—\n", "value")

        self._insert_detail(
            self._tr("Gerekçe", "Rationale"), item.rationale
        )
        if item.review_note:
            self._insert_detail(self._tr("Mühendis Notu", "Engineer Note"), item.review_note)
        if item.source_excerpt:
            self._insert_detail(
                self._tr("Kaynak Alıntı", "Source Excerpt"), item.source_excerpt
            )

        if blockers:
            self.detail_text.insert(
                tk.END,
                self._tr("Onay Engelleri\n", "Approval Blockers\n"),
                "label",
            )
            for blocker in blockers:
                self.detail_text.insert(tk.END, f"• {blocker}\n", "warning")
        elif warnings:
            self.detail_text.insert(
                tk.END,
                self._tr("İnceleme Notları\n", "Review Notes\n"),
                "label",
            )
            for warning in warnings:
                self.detail_text.insert(tk.END, f"• {warning}\n", "warning")
        self.detail_text.configure(state=tk.DISABLED)
        self._update_action_controls()

    def _insert_detail(self, label: str, value: Any) -> None:
        self.detail_text.insert(tk.END, f"{label}\n", "label")
        self.detail_text.insert(tk.END, f"{value}\n", "value")

    def _set_detail_text(self, text: str) -> None:
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, text, "value")
        self.detail_text.configure(state=tk.DISABLED)
