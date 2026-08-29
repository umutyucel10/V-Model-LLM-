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

class _KarsilastirmaMixin:
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

