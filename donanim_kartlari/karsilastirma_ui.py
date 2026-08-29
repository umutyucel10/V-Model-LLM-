# -*- coding: utf-8 -*-
"""İki-dört donanım için kanıt odaklı karşılaştırma çalışma alanı."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

import donanim_kartlari_yonetim as management
from donanim_kartlari_model import MISSING_VALUE, clean_text, is_missing


def _value(value: Any) -> str:
    if value is None or is_missing(value):
        return MISSING_VALUE
    if isinstance(value, bool):
        return "Karşılar" if value else "Bağlı değil"
    if isinstance(value, float):
        return f"{value:.6g}"
    return clean_text(value, MISSING_VALUE)


class HardwareComparisonWorkspace:
    """Karşılaştırmayı katalog penceresine bağlı, geniş bir çalışma alanında gösterir."""

    def __init__(
        self, master: tk.Misc, catalog: Mapping[str, Any], hardware_ids: Sequence[str],
        traceability: Mapping[str, Any] | None,
        palette_getter: Callable[[], Mapping[str, str]],
        impact_callback: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.catalog = dict(catalog)
        self.traceability = dict(traceability or {})
        self.hardware_ids = list(hardware_ids)
        self.palette_getter = palette_getter
        self.impact_callback = impact_callback
        self.result = management.build_multi_comparison(
            self.catalog, self.hardware_ids, self.traceability
        )
        self.window = tk.Toplevel(master)
        self.window.title("Donanım Karşılaştırma Tezgâhı")
        self.window.geometry("1280x760")
        self.window.minsize(980, 620)
        self.window.transient(master)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._row_payloads: dict[str, Mapping[str, Any]] = {}
        self._build()

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
        if self.exists:
            self.window.destroy()

    def _build(self) -> None:
        palette = self.palette_getter()
        self.window.configure(background=palette["bg"])
        root = ttk.Frame(self.window, style="HardwareRoot.TFrame", padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1); root.rowconfigure(4, weight=1)

        header = ttk.Frame(root, style="HardwareRoot.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Donanım Karşılaştırma Tezgâhı", style="HardwareTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header, text="2–4 PARÇA  ·  ORTAK BİRİM  ·  ZORUNLU KRİTER  ·  KAYNAK KANITI",
            style="HardwareSignature.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(header, text="Kapat", command=self.close).grid(row=0, column=1, rowspan=2, sticky="e")

        identity = ttk.Frame(root, style="HardwarePanel.TFrame", padding=8, borderwidth=1, relief="solid")
        identity.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column, item in enumerate(self.result["items"]):
            identity.columnconfigure(column, weight=1)
            cell = ttk.Frame(identity, style="HardwarePanel.TFrame", padding=(8, 4))
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 0))
            ttk.Label(cell, text=clean_text(item.get("part_name"), MISSING_VALUE), style="HardwareCardTitle.TLabel").pack(anchor="w")
            ttk.Label(
                cell,
                text=f"PN {_value(item.get('part_number'))}  ·  {_value(item.get('manufacturer'))}",
                style="HardwareMono.TLabel",
            ).pack(anchor="w", pady=(2, 0))
            ttk.Label(
                cell,
                text=f"Güven {_value(item.get('confidence_score'))}/100  ·  {_value(item.get('lifecycle_status'))}",
                style="HardwarePanelMuted.TLabel",
            ).pack(anchor="w", pady=(2, 0))

        trace = ttk.Frame(root, style="HardwareTraceBar.TFrame", padding=(6, 3), borderwidth=1, relief="solid")
        trace.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for index, label in enumerate(("Üst Sistem", "Parça", "Gereksinim", "Test", "Alternatif")):
            trace.columnconfigure(index * 2, weight=1)
            ttk.Label(trace, text=label, style="HardwareTrace.TLabel", anchor="center").grid(row=0, column=index * 2, sticky="ew")
            if index < 4:
                ttk.Label(trace, text="→", style="HardwareTraceArrow.TLabel").grid(row=0, column=index * 2 + 1, padx=4)

        violations = self.result["mandatory_violations"]
        warning_text = (
            f"{len(violations)} zorunlu gereksinim bağlantısı ihlali — önce bu satırları inceleyin."
            if violations else
            "Zorunlu gereksinim bağlantısı ihlali bulunmadı. Eksik veri puanlamaya katılmadı."
        )
        self.warning_label = ttk.Label(
            root, text=warning_text,
            style="HardwareImpact.TLabel" if violations else "HardwarePanelMuted.TLabel",
        )
        self.warning_label.grid(row=3, column=0, sticky="ew", pady=(0, 6))

        table_box = ttk.Frame(root, style="HardwarePanel.TFrame", borderwidth=1, relief="solid")
        table_box.grid(row=4, column=0, sticky="nsew")
        table_box.columnconfigure(0, weight=1); table_box.rowconfigure(0, weight=1)
        columns = ["parameter", "unit", *self.hardware_ids, "evidence"]
        self.tree = ttk.Treeview(table_box, columns=columns, show="tree headings", style="Hardware.Treeview")
        self.tree.heading("#0", text="Öncelik")
        self.tree.heading("parameter", text="Parametre / Gereksinim")
        self.tree.heading("unit", text="Birim")
        self.tree.column("#0", width=90, minwidth=72, stretch=False)
        self.tree.column("parameter", width=220, minwidth=150)
        self.tree.column("unit", width=70, minwidth=55, anchor="center", stretch=False)
        names = {item["hardware_id"]: clean_text(item.get("part_name"), item["hardware_id"]) for item in self.result["items"]}
        for hardware_id in self.hardware_ids:
            self.tree.heading(hardware_id, text=names[hardware_id])
            self.tree.column(hardware_id, width=150, minwidth=110, anchor="e")
        self.tree.heading("evidence", text="Kaynak / güven")
        self.tree.column("evidence", width=180, minwidth=130)
        yscroll = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("mandatory", foreground="#B42318")
        self.tree.tag_configure("missing", foreground="#6B7280")
        self.tree.bind("<<TreeviewSelect>>", self._show_evidence)
        self.tree.bind("<Return>", self._show_evidence)
        self._populate_rows()

        footer = ttk.Frame(root, style="HardwareRoot.TFrame")
        footer.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.method_var = tk.StringVar(value=self.result["method"])
        ttk.Label(
            footer, textvariable=self.method_var, style="HardwarePanelMuted.TLabel",
            wraplength=850, justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            footer, text="Etki Analizine Gönder", style="primary.TButton",
            command=self._send_to_impact,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

    def _populate_rows(self) -> None:
        violation_keys = {
            (row["hardware_id"], row["requirement_id"])
            for row in self.result["mandatory_violations"]
        }
        for row in self.result["requirement_rows"]:
            values = [row["label"], row["unit"]]
            values.extend(_value(row["values"].get(hardware_id)) for hardware_id in self.hardware_ids)
            values.append(f"{_value(row.get('source'))} · {_value(row.get('confidence'))}")
            has_violation = any((hardware_id, row["key"]) in violation_keys for hardware_id in self.hardware_ids)
            item_id = self.tree.insert(
                "", "end", text="ZORUNLU" if row["mandatory"] else "Gereksinim",
                values=values, tags=("mandatory",) if has_violation else (),
            )
            self._row_payloads[item_id] = row
        for row in self.result["parameter_rows"]:
            values = [row["label"], row["unit"]]
            missing = False
            for hardware_id in self.hardware_ids:
                normalized = row["normalized_values"].get(hardware_id)
                missing = missing or normalized is None
                values.append(_value(normalized))
            source_count = len({value for value in row["sources"].values() if not is_missing(value)})
            values.append(f"{source_count} kaynak · satırı seçerek kanıtı görün")
            item_id = self.tree.insert(
                "", "end", text="Teknik", values=values,
                tags=("missing",) if missing else (),
            )
            self._row_payloads[item_id] = row

    def _show_evidence(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        row = self._row_payloads.get(selected[0], {})
        if row.get("kind") == "requirement":
            self.method_var.set(
                f"{row.get('key')} · Kaynak: {_value(row.get('source'))} · Güven: {_value(row.get('confidence'))}"
            )
            return
        lines = []
        for hardware_id in self.hardware_ids:
            source = (row.get("sources") or {}).get(hardware_id, MISSING_VALUE)
            confidence = (row.get("confidences") or {}).get(hardware_id, 0)
            assessment = (row.get("assessments") or {}).get(hardware_id, "Nötr")
            lines.append(f"{hardware_id}: {assessment} · Kaynak {_value(source)} · Güven {_value(confidence)}")
        self.method_var.set("  |  ".join(lines))

    def _send_to_impact(self) -> None:
        if not self.impact_callback:
            messagebox.showinfo(
                "Etki Analizi", "Etki Analizi bağlantısı bu oturumda kullanılabilir değil.",
                parent=self.window,
            )
            return
        try:
            payload = management.build_multi_impact_payload(
                self.catalog, self.hardware_ids, self.traceability
            )
            self.impact_callback(payload)
            self.close()
        except Exception as error:
            messagebox.showerror(
                "Etki Analizi", f"Karşılaştırma Etki Analizine aktarılamadı:\n{error}",
                parent=self.window,
            )


__all__ = ["HardwareComparisonWorkspace"]
