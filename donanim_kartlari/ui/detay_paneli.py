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

class _DetayPaneliMixin:
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

