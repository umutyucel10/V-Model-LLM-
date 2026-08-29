# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — Arayüz.py'nin bölünmüş
parçalarından biri. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 3.
"""

import csv
import os
import sys

# Windows konsolu (cp1254) emoji/Unicode karakterleri basamadığı için
# çıktıyı UTF-8'e zorla; aksi halde print(...) ifadeleri çökertir.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import threading
import traceback
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.style import Style
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont 
from reportlab.pdfbase import pdfmetrics
from openpyxl import Workbook
import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings
from app_identity import (
    APP_NAME, ICON_RELATIVE_PATH, apply_app_identity,
    prepare_process_identity, resource_path,
)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import tid_generator_logic
    import sgd_generator_logic
    import stt_generator_logic
    import dgöygö_generator_logic
    import kmtd_generator_logic
    import sitet_generator_logic
    import alt_sistem_test_logic
    import dtet_ytet_generator_logic
    import hardware_list_logic
    import hardware_generator_logic
    import hardware_list_ui
    import donanim_kartlari_gorsel
    import donanim_kartlari_ui
    import donanim_kartlari_yonetim
    import etki_analizi_ui
    import etki_analizi_izlenebilirlik
    import etki_analizi_entegrasyon
    import etki_analizi_simulasyon
    import etki_analizi_degisim_paketi
    import etki_analizi_degisim_raporlama
    import donanim_kartlari_algilama
    import mimari_cerceve_ui
    import text_cleanup
    import html_generation
    import pdf_extraction
except ImportError as e:
    messagebox.showerror(
        "Modül Hatası",
        f"Gerekli bir modül yüklenemedi: {e}\nLütfen programı yeniden kurun veya bağımlılıkları kontrol edin."
    )
    sys.exit(1)

from .yardimcilar import pre_process_files, start1_time

class _DonanimEntegrasyonMixin:
    def _get_current_hardware_catalog(self):
        """Açık projenin otomatik kataloğunu bellekten veya atomik JSON'dan yükler."""
        project_name = self.entry_widgets["proje_ismi"].get().strip()
        current = getattr(self, "last_hardware_catalog", None)
        if current and (
            not project_name or current.get("project_name") == project_name
        ):
            return dict(current)
        if not project_name:
            return None
        try:
            loaded = donanim_kartlari_algilama.load_hardware_catalog(project_name)
        except Exception as error:
            self.update_status_text(
                f"Donanım kataloğu yüklenemedi: {error}", is_error=True
            )
            return None
        if loaded:
            self.last_hardware_catalog = loaded.to_dict()
            return dict(self.last_hardware_catalog)
        return None

    def _prepare_hardware_catalog_visuals(self, project_name, catalog):
        """AI/kavramsal görseli kullanıcı onayı olmadan otomatik üretmez."""
        try:
            from config import HARDWARE_AUTO_IMAGE_GENERATION
        except Exception:
            HARDWARE_AUTO_IMAGE_GENERATION = False
        if not HARDWARE_AUTO_IMAGE_GENERATION:
            return 0
        raw_catalog = (
            catalog.to_dict() if hasattr(catalog, "to_dict")
            else dict(catalog or {})
        )
        if not raw_catalog.get("hardware_items"):
            return 0
        overrides = donanim_kartlari_yonetim.load_overrides(
            project_name, raw_catalog
        )
        view, _conflicts = donanim_kartlari_yonetim.apply_overrides(
            raw_catalog, overrides
        )
        pending = [
            item for item in view.get("hardware_items", [])
            if donanim_kartlari_gorsel.illustration_required(item)
        ]
        if not pending:
            return 0
        output_dir = (
            donanim_kartlari_yonetim.overrides_path(
                project_name, raw_catalog
            ).parent / "donanim_gorselleri"
        )
        records = donanim_kartlari_gorsel.generate_catalog_illustrations(
            view, output_dir
        )
        donanim_kartlari_yonetim.set_generated_visuals(overrides, records)
        donanim_kartlari_yonetim.save_overrides(
            project_name, overrides, raw_catalog
        )
        return len(records)

    def _open_hardware_comparison(self, payload):
        """Donanım Kartındaki alternatif ve teknik değerleri manuel analize aktarır."""
        self.open_impact_analysis_workspace()
        workspace = getattr(self, "impact_analysis_workspace", None)
        if not workspace or not workspace.exists:
            return
        try:
            workspace.prefill_hardware_comparison(payload)
        except Exception as error:
            messagebox.showerror(
                "Etki Analizi Aktarım Hatası",
                f"Donanım kartı Etki Analizine aktarılamadı: {error}",
                parent=workspace.window,
            )

    def _open_hardware_requirement(self, requirement_id):
        """Karttan seçilen gereksinimi değişiklik simülasyonu formunda açar."""
        self.open_impact_analysis_workspace()
        workspace = getattr(self, "impact_analysis_workspace", None)
        if not workspace or not workspace.exists:
            return
        try:
            workspace.prefill_requirement_simulation(requirement_id)
        except Exception as error:
            messagebox.showwarning(
                "Gereksinime Git",
                f"Gereksinim simülasyon formunda açılamadı: {error}",
                parent=workspace.window,
            )

    def _open_hardware_detail(self, hardware_reference):
        """Etki Analizi parça bağlantısını aynı Donanım Detay ekranında açar."""
        reference = str(hardware_reference or "").strip()
        report = self._get_current_traceability_report() or {}
        for node in report.get("nodes", []):
            if not isinstance(node, dict) or str(node.get("id", "")).strip() != reference:
                continue
            reference = str(node.get("title") or node.get("description") or reference).strip()
            break
        self.open_hardware_cards_workspace()
        workspace = getattr(self, "hardware_cards_workspace", None)
        if workspace and workspace.exists:
            workspace.open_detailed_review(reference)

    def _on_hardware_impact_result(self, result):
        """Gereksinim simülasyonundaki parça etkilerini kart rozetlerine taşır."""
        self.last_hardware_impact_result = (
            result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        )
        workspace = getattr(self, "hardware_cards_workspace", None)
        if workspace and workspace.exists:
            workspace.set_simulation_result(self.last_hardware_impact_result)

    def _start_hardware_datasheet_ingestion(self, datasheet_paths, hardware_id):
        """Datasheet okumasını Tk ana iş parçacığını durdurmadan başlatır."""
        project_name = self.entry_widgets["proje_ismi"].get().strip()
        if not project_name:
            messagebox.showwarning(
                "Datasheet Yükle",
                "Datasheet işlemeden önce proje adını girin.",
            )
            return
        self._hardware_catalog_generation_token += 1
        token = self._hardware_catalog_generation_token
        report = self._get_current_traceability_report() or {}
        flat_snapshot = {
            str(key): dict(value) for key, value in self.flat_data.items()
            if isinstance(value, dict)
        }
        hardware_snapshot = {
            str(key): dict(value) for key, value in self.hardware_data.items()
            if isinstance(value, dict)
        }
        source_paths = list(dict.fromkeys([
            *self.file_paths, *self.generated_document_paths,
        ]))
        threading.Thread(
            target=self._hardware_datasheet_worker,
            args=(
                token, project_name, report, flat_snapshot, hardware_snapshot,
                source_paths, tuple(datasheet_paths), hardware_id,
            ),
            daemon=True,
        ).start()

    def _hardware_datasheet_worker(
        self, token, project_name, report, flat_snapshot, hardware_snapshot,
        source_paths, datasheet_paths, hardware_id,
    ):
        try:
            previous = donanim_kartlari_algilama.load_hardware_catalog(project_name)
            catalog = donanim_kartlari_algilama.build_or_update_hardware_catalog(
                project_name,
                traceability_report=report,
                structured_hardware=hardware_snapshot,
                structured_records=flat_snapshot,
                source_paths=source_paths,
                datasheet_paths=datasheet_paths,
                persist=True,
                status_callback=self.update_status_text,
            )
            try:
                visual_count = self._prepare_hardware_catalog_visuals(
                    project_name, catalog
                )
            except Exception as visual_error:
                visual_count = 0
                self.update_status_text(
                    f"Donanım kartı görselleri hazırlanamadı: {visual_error}",
                    is_error=True,
                )
            change_summary = donanim_kartlari_yonetim.compare_catalogs(
                previous, catalog
            )
            status = {
                "status": "ready", "updated": catalog.updated,
                "hardware_count": len(catalog.hardware_items),
                "instance_count": len(catalog.product_instances),
                "conflict_count": len(catalog.conflicts),
                "visual_count": visual_count,
                "storage_path": catalog.storage_path,
                "target_hardware_id": hardware_id,
                "message": (
                    f"Datasheet işlendi; katalogda {len(catalog.hardware_items)} "
                    "donanım kartı hazır. AI görseli yalnızca kullanıcı onayıyla oluşturulur."
                ),
            }
            self.master.after(
                0, lambda: self._finish_hardware_catalog_refresh(
                    token, catalog, status, change_summary
                )
            )
        except Exception as error:
            self.master.after(
                0, lambda detail=str(error): self._finish_hardware_catalog_failure(
                    token, detail
                )
            )

    def _finish_hardware_catalog_refresh(
        self, token, catalog, status, change_summary
    ):
        if token != self._hardware_catalog_generation_token:
            return
        self.last_hardware_catalog = catalog.to_dict()
        status = dict(status)
        status["change_summary"] = dict(change_summary)
        self.last_hardware_catalog_status = status
        workspace = getattr(self, "hardware_cards_workspace", None)
        if workspace and workspace.exists:
            workspace.on_catalog_ready(
                self.last_hardware_catalog, status, change_summary
            )
        self.update_status_text(status["message"], is_complete=True)

    def _finish_hardware_catalog_failure(self, token, detail):
        if token != self._hardware_catalog_generation_token:
            return
        workspace = getattr(self, "hardware_cards_workspace", None)
        if workspace and workspace.exists:
            workspace.set_loading(False, f"Datasheet işlenemedi: {detail}")
        messagebox.showwarning(
            "Datasheet İşleme Uyarısı",
            f"Datasheet katalogla birleştirilemedi: {detail}\nÖzgün dosya değiştirilmedi.",
        )

    def _invalidate_hardware_generation(self, message=""):
        """Eski arka plan sonucunun yeni belge verisini ezmesini önler."""
        self._hardware_generation_token += 1
        workspace = getattr(self, "hardware_workspace", None)
        if workspace and workspace.exists:
            workspace.set_generation_state(False, message)

    def start_hardware_generation(self):
        """SGD/STT kayıtlarından arka planda yapılandırılmış donanım önerileri üretir."""
        records = hardware_list_logic.eligible_requirement_records(self.flat_data)
        workspace = getattr(self, "hardware_workspace", None)
        if not records:
            message = self._t(
                "Donanım analizi için içerikli SGD veya STT kaydı bulunamadı. "
                "Önce bu dokümanlardan en az birini üretin.",
                "No populated SGD or STT record was found for hardware analysis. "
                "Generate at least one of these documents first.",
            )
            if workspace and workspace.exists:
                workspace.set_generation_state(False, message)
            messagebox.showwarning(
                self._t("Donanım Önerisi", "Hardware Suggestions"),
                message,
            )
            return

        self._hardware_generation_token += 1
        token = self._hardware_generation_token
        project_name = self.entry_widgets["proje_ismi"].get().strip() or "Proje"
        flat_snapshot = {
            str(key): dict(value)
            for key, value in self.flat_data.items()
            if isinstance(value, dict)
        }
        hardware_snapshot = {
            str(key): dict(value)
            for key, value in self.hardware_data.items()
            if isinstance(value, dict)
        }
        running_message = self._t(
            f"{len(records)} SGD/STT maddesi analiz ediliyor…",
            f"Analyzing {len(records)} SGD/STT records…",
        )
        if workspace and workspace.exists:
            workspace.set_generation_state(True, running_message)
        self.update_status_text(running_message)

        thread = threading.Thread(
            target=self._run_hardware_generation,
            args=(token, project_name, flat_snapshot, hardware_snapshot),
            daemon=True,
        )
        thread.start()

    def _run_hardware_generation(
        self,
        token,
        project_name,
        flat_snapshot,
        hardware_snapshot,
    ):
        try:
            result = hardware_generator_logic.run_generation_from_requirements(
                flat_data=flat_snapshot,
                project_name=project_name,
                existing_hardware=hardware_snapshot,
                status_callback=self.update_status_text,
            )
        except Exception as error:
            result = {
                "result": False,
                "message": f"Donanım önerisi üretim hatası: {error}",
            }
        try:
            self.master.after(0, lambda: self._finish_hardware_generation(token, result))
        except tk.TclError:
            pass

    def _finish_hardware_generation(self, token, result):
        if token != self._hardware_generation_token:
            return

        workspace = getattr(self, "hardware_workspace", None)
        if result.get("result"):
            self.hardware_data.clear()
            self.hardware_data.update(result.get("hardware_data", {}))
            suggestion_count = int(result.get("suggestion_count", 0))
            requirement_count = int(result.get("requirement_count", 0))
            message = self._t(
                f"{suggestion_count} donanım önerisi oluşturuldu; {requirement_count} gereksinim analiz edildi.",
                f"Created {suggestion_count} hardware suggestions; analyzed {requirement_count} requirements.",
            )
            if workspace and workspace.exists:
                workspace.refresh()
                workspace.set_generation_state(False, message)
            self.update_status_text(message, is_complete=True)
            return

        message = str(result.get("message") or self._t(
            "Donanım önerisi üretilemedi.",
            "Hardware suggestions could not be generated.",
        ))
        if workspace and workspace.exists:
            workspace.set_generation_state(False, message)
        self.update_status_text(message, is_error=True)
        messagebox.showerror(
            self._t("Donanım Önerisi Hatası", "Hardware Suggestion Error"),
            message,
        )

