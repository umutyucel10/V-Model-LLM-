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

class _DuzenlemeMixin:
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

