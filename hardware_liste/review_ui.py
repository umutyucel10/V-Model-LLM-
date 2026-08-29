# -*- coding: utf-8 -*-
"""Donanım inceleme, uyumluluk raporu ve dışa aktarım pencereleri."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping

import hardware_export_logic
import hardware_list_logic


def parse_specifications_text(value: str) -> dict[str, str]:
    """Her satırı 'Özellik: Değer' biçiminden sözlüğe dönüştürür."""
    specifications: dict[str, str] = {}
    for line_number, raw_line in enumerate(str(value or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        separator = ":" if ":" in line else "=" if "=" in line else ""
        if not separator:
            raise ValueError(
                f"Teknik özellik satırı {line_number} 'Özellik: Değer' biçiminde olmalı."
            )
        name, raw_value = line.split(separator, 1)
        name = " ".join(name.split())
        spec_value = " ".join(raw_value.split()) or hardware_list_logic.DSB
        if not name:
            raise ValueError(f"Teknik özellik satırı {line_number} için ad gerekli.")
        specifications[name] = spec_value
    return specifications


def format_specifications_text(specifications: Mapping[str, Any]) -> str:
    return "\n".join(
        f"{name}: {value}" for name, value in specifications.items()
    )


class HardwareEditorDialog:
    """Seçili BOM kaydını mühendis incelemesine uygun biçimde düzenler."""

    def __init__(
        self,
        master: tk.Misc,
        style: ttk.Style,
        item: hardware_list_logic.HardwareItem,
        known_requirement_ids: list[str],
        language_getter: Callable[[], str],
        palette_getter: Callable[[], Mapping[str, str]],
        save_callback: Callable[[str, Mapping[str, Any]], None],
    ) -> None:
        self.master = master
        self.style = style
        self.item = item
        self.known_requirement_ids = known_requirement_ids
        self.language_getter = language_getter
        self.palette_getter = palette_getter
        self.save_callback = save_callback

        self.window = tk.Toplevel(master)
        self.window.title(self._tr("Donanım Kaydını Düzenle", "Edit Hardware Record"))
        self.window.geometry("760x700")
        self.window.minsize(700, 650)
        self.window.transient(master)
        self.window.grab_set()

        self.category_var = tk.StringVar(value=item.category)
        self.quantity_var = tk.StringVar(value=str(item.quantity))
        self.risk_var = tk.StringVar(value=item.risk)
        self.manufacturer_var = tk.StringVar(value=item.manufacturer)
        self.part_number_var = tk.StringVar(value=item.part_number)
        self.requirements_var = tk.StringVar(value=", ".join(item.linked_requirements))
        self._build()
        self._apply_palette()

    def _tr(self, tr_text: str, en_text: str) -> str:
        return tr_text if self.language_getter() == "tr" else en_text

    def _label(self, parent: tk.Misc, tr_text: str, en_text: str, row: int) -> None:
        ttk.Label(
            parent,
            text=self._tr(tr_text, en_text),
            style="HardwareEditorLabel.TLabel",
        ).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=(5, 3))

    def _build(self) -> None:
        root = ttk.Frame(self.window, style="light.TFrame", padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(8, weight=1)

        ttk.Label(
            root,
            text=f"{self.item.item_id} · " + self._tr("Mühendis İncelemesi", "Engineering Review"),
            style="HardwareEditorTitle.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(
            root,
            text=self._tr(
                "Kaydedilen her değişiklik kaydı yeniden 'İnceleniyor' durumuna getirir.",
                "Every saved change returns the record to 'In Review'.",
            ),
            style="HardwareMuted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        pair = ttk.Frame(root, style="light.TFrame")
        pair.grid(row=2, column=0, columnspan=2, sticky="ew")
        for index in range(4):
            pair.columnconfigure(index, weight=1 if index in (1, 3) else 0)
        ttk.Label(pair, text=self._tr("Kategori", "Category"), style="HardwareEditorLabel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        category = ttk.Combobox(pair, textvariable=self.category_var, state="readonly")
        category.configure(values=(hardware_list_logic.DEFAULT_CATEGORY, *hardware_list_logic.HARDWARE_CATEGORIES))
        category.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        ttk.Label(pair, text=self._tr("Adet", "Quantity"), style="HardwareEditorLabel.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Spinbox(pair, from_=1, to=9999, textvariable=self.quantity_var, width=8).grid(row=0, column=3, sticky="ew")

        pair2 = ttk.Frame(root, style="light.TFrame")
        pair2.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for index in range(6):
            pair2.columnconfigure(index, weight=1 if index in (1, 3, 5) else 0)
        ttk.Label(pair2, text=self._tr("Risk", "Risk"), style="HardwareEditorLabel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        risk = ttk.Combobox(pair2, textvariable=self.risk_var, state="readonly", width=12)
        risk.configure(values=hardware_list_logic.HARDWARE_RISK_LEVELS)
        risk.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(pair2, text=self._tr("Üretici", "Manufacturer"), style="HardwareEditorLabel.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Entry(pair2, textvariable=self.manufacturer_var).grid(row=0, column=3, sticky="ew", padx=(0, 12))
        ttk.Label(pair2, text=self._tr("Parça No", "Part No"), style="HardwareEditorLabel.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 6))
        ttk.Entry(pair2, textvariable=self.part_number_var).grid(row=0, column=5, sticky="ew")

        self._label(root, "Bağlı SGD/STT Kimlikleri", "Linked SGD/STT IDs", 4)
        req_frame = ttk.Frame(root, style="light.TFrame")
        req_frame.grid(row=4, column=1, sticky="ew", pady=(5, 3))
        req_frame.columnconfigure(0, weight=1)
        ttk.Entry(req_frame, textvariable=self.requirements_var).grid(row=0, column=0, sticky="ew")
        ttk.Label(
            req_frame,
            text=self._tr(
                "Virgülle ayırın · Geçerli: ",
                "Comma-separated · Valid: ",
            ) + (", ".join(self.known_requirement_ids) or "—"),
            style="HardwareEditorHint.TLabel",
            wraplength=550,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self._label(root, "Donanım Tanımı", "Hardware Description", 5)
        self.description_text = tk.Text(root, height=3, wrap="word", font=("Segoe UI", 10))
        self.description_text.grid(row=5, column=1, sticky="ew", pady=(5, 3))
        self.description_text.insert("1.0", self.item.description)

        self._label(root, "Teknik Özellikler", "Specifications", 6)
        self.specifications_text = tk.Text(root, height=6, wrap="word", font=("Consolas", 9))
        self.specifications_text.grid(row=6, column=1, sticky="ew", pady=(5, 3))
        self.specifications_text.insert("1.0", format_specifications_text(self.item.specifications))

        self._label(root, "Gerekçe", "Rationale", 7)
        self.rationale_text = tk.Text(root, height=3, wrap="word", font=("Segoe UI", 9))
        self.rationale_text.grid(row=7, column=1, sticky="ew", pady=(5, 3))
        self.rationale_text.insert("1.0", self.item.rationale)

        self._label(root, "Mühendis Notu", "Engineer Note", 8)
        self.review_note_text = tk.Text(root, height=3, wrap="word", font=("Segoe UI", 9))
        self.review_note_text.grid(row=8, column=1, sticky="nsew", pady=(5, 3))
        self.review_note_text.insert("1.0", self.item.review_note)

        footer = ttk.Frame(root, style="light.TFrame")
        footer.grid(row=9, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(
            footer,
            text=self._tr("Vazgeç", "Cancel"),
            command=self.window.destroy,
            style="primary.Outline.TButton",
            width=12,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            footer,
            text=self._tr("Kaydet ve İncele", "Save for Review"),
            command=self._save,
            style="primary.TButton",
            width=18,
        ).pack(side="left")

    def _apply_palette(self) -> None:
        palette = self.palette_getter()
        self.window.configure(background=palette["bg"])
        self.style.configure(
            "HardwareEditorTitle.TLabel", background=palette["bg"],
            foreground=palette["fg"], font=("Segoe UI", 14, "bold"),
        )
        self.style.configure(
            "HardwareEditorLabel.TLabel", background=palette["bg"],
            foreground=palette["fg"], font=("Segoe UI", 9, "bold"),
        )
        self.style.configure(
            "HardwareEditorHint.TLabel", background=palette["bg"],
            foreground=palette["muted"], font=("Segoe UI", 8),
        )
        for widget in (
            self.description_text, self.specifications_text,
            self.rationale_text, self.review_note_text,
        ):
            widget.configure(
                background=palette["entry_bg"], foreground=palette["entry_fg"],
                insertbackground=palette["fg"], relief="solid", borderwidth=1,
            )

    def _save(self) -> None:
        try:
            description = " ".join(self.description_text.get("1.0", tk.END).split())
            if not description or description == hardware_list_logic.DSB:
                raise ValueError(self._tr(
                    "Donanım tanımı zorunludur.",
                    "Hardware description is required.",
                ))
            quantity = int(self.quantity_var.get())
            if quantity < 1:
                raise ValueError(self._tr("Adet en az 1 olmalı.", "Quantity must be at least 1."))
            linked = hardware_list_logic.normalize_requirement_ids(self.requirements_var.get())
            if not linked:
                raise ValueError(self._tr(
                    "En az bir SGD/STT bağlantısı gerekli.",
                    "At least one SGD/STT link is required.",
                ))
            unknown = [item_id for item_id in linked if item_id not in self.known_requirement_ids]
            if unknown:
                raise ValueError(self._tr(
                    "Bilinmeyen gereksinim bağlantısı: ",
                    "Unknown requirement link: ",
                ) + ", ".join(unknown))
            changes = {
                "category": self.category_var.get(),
                "description": description,
                "quantity": quantity,
                "risk": self.risk_var.get(),
                "manufacturer": " ".join(self.manufacturer_var.get().split()) or hardware_list_logic.DSB,
                "part_number": " ".join(self.part_number_var.get().split()) or hardware_list_logic.DSB,
                "linked_requirements": linked,
                "specifications": parse_specifications_text(
                    self.specifications_text.get("1.0", tk.END)
                ),
                "rationale": " ".join(self.rationale_text.get("1.0", tk.END).split()) or hardware_list_logic.DSB,
                "review_note": " ".join(self.review_note_text.get("1.0", tk.END).split()),
            }
            self.save_callback(self.item.item_id, changes)
        except (TypeError, ValueError) as error:
            messagebox.showerror(
                self._tr("Kayıt Doğrulama", "Record Validation"),
                str(error),
                parent=self.window,
            )
            return
        self.window.destroy()


def show_compatibility_report(
    master: tk.Misc,
    style: ttk.Style,
    issues: list[Mapping[str, Any]],
    language: str,
    palette: Mapping[str, str],
) -> tk.Toplevel:
    tr = language == "tr"
    window = tk.Toplevel(master)
    window.title("Donanım Uyumluluk Raporu" if tr else "Hardware Compatibility Report")
    window.geometry("920x540")
    window.minsize(760, 420)
    window.transient(master)
    window.configure(background=palette["bg"])

    root = ttk.Frame(window, style="light.TFrame", padding=16)
    root.pack(fill="both", expand=True)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)
    summary = hardware_list_logic.compatibility_summary(issues)
    title = "MÜHENDİSLİK KAPISI · UYUMLULUK" if tr else "ENGINEERING GATE · COMPATIBILITY"
    ttk.Label(root, text=title, style="HardwareTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        root,
        text=(
            f"{summary['errors']} hata · {summary['warnings']} uyarı · {summary['info']} bilgi"
            if tr else
            f"{summary['errors']} errors · {summary['warnings']} warnings · {summary['info']} info"
        ),
        style="HardwareTrace.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(3, 10))

    columns = ("severity", "item_id", "code", "message")
    tree = ttk.Treeview(root, columns=columns, show="headings", style="Hardware.Treeview")
    headings = (
        ("severity", "Seviye" if tr else "Severity", 90),
        ("item_id", "Kayıt" if tr else "Record", 120),
        ("code", "Denetim Kodu" if tr else "Check Code", 210),
        ("message", "Açıklama" if tr else "Description", 470),
    )
    for key, label, width in headings:
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=70, anchor="w", stretch=key == "message")
    tree.grid(row=2, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    scrollbar.grid(row=2, column=1, sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)
    tree.tag_configure("error", foreground="#B42318")
    tree.tag_configure("warning", foreground="#9A6400")
    tree.tag_configure("info", foreground=palette["muted"])
    for index, issue in enumerate(issues):
        severity = str(issue.get("severity", ""))
        tag = {"Hata": "error", "Uyarı": "warning"}.get(severity, "info")
        tree.insert("", "end", iid=f"issue-{index}", values=(
            severity, issue.get("item_id", ""), issue.get("code", ""), issue.get("message", ""),
        ), tags=(tag,))
    if not issues:
        tree.insert("", "end", values=(
            "Bilgi" if tr else "Info", "—", "NO_ISSUES",
            "Uyumluluk sorunu bulunmadı." if tr else "No compatibility issues found.",
        ), tags=("info",))
    ttk.Button(
        root, text="Kapat" if tr else "Close", command=window.destroy,
        style="primary.Outline.TButton", width=12,
    ).grid(row=3, column=0, sticky="e", pady=(10, 0))
    return window


def export_hardware_with_dialog(
    master: tk.Misc,
    export_format: str,
    registry: Mapping[str, Mapping[str, Any]],
    flat_data: Mapping[str, Mapping[str, Any]],
    project_name: str,
    language: str,
) -> dict[str, Any] | None:
    tr = language == "tr"
    approved_only = messagebox.askyesnocancel(
        "BOM Dışa Aktarım" if tr else "BOM Export",
        (
            "Yalnızca ONAYLI kayıtlar aktarılsın mı?\n\n"
            "Evet: yalnız onaylı kayıtlar\nHayır: tüm çalışma kayıtları\nİptal: dışa aktarma"
            if tr else
            "Export APPROVED records only?\n\n"
            "Yes: approved records only\nNo: all working records\nCancel: stop export"
        ),
        parent=master,
    )
    if approved_only is None:
        return None
    is_excel = export_format.lower() == "excel"
    extension = ".xlsx" if is_excel else ".csv"
    filetypes = (
        [("Excel BOM", "*.xlsx")]
        if is_excel else [("IBM DOORS CSV", "*.csv")]
    )
    safe_project = "_".join((project_name or "Proje").split())
    path = filedialog.asksaveasfilename(
        parent=master,
        title="BOM Dosyasını Kaydet" if tr else "Save BOM File",
        defaultextension=extension,
        initialfile=f"{safe_project}_Donanim_BOM{extension}",
        filetypes=filetypes,
    )
    if not path:
        return None
    try:
        if is_excel:
            result = hardware_export_logic.export_hardware_excel(
                path, registry, flat_data, project_name, bool(approved_only)
            )
        else:
            result = hardware_export_logic.export_hardware_doors_csv(
                path, registry, flat_data, project_name, bool(approved_only)
            )
    except (OSError, TypeError, ValueError) as error:
        messagebox.showerror(
            "BOM Dışa Aktarım Hatası" if tr else "BOM Export Error",
            str(error),
            parent=master,
        )
        return None
    messagebox.showinfo(
        "BOM Hazır" if tr else "BOM Ready",
        (
            f"{result['record_count']} donanım kaydı aktarıldı.\n{result['path']}"
            if tr else
            f"Exported {result['record_count']} hardware records.\n{result['path']}"
        ),
        parent=master,
    )
    return result
