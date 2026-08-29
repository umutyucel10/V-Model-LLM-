# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — donanim_kartlari_ui.py'nin bölünmüş
parçalarından biri: modül seviyesi sabitler, yardımcı fonksiyonlar ve küçük
yardımcı diyalog sınıfları. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
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


