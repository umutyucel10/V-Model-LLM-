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

class _FiltreMixin:
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

