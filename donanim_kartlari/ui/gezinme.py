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

class _GezinmeMixin:
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

