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

class _WorkspaceKoordinasyonMixin:
    def open_hardware_workspace(self):
        """Akıllı Donanım Listesi mühendislik çalışma alanını açar."""
        workspace = getattr(self, "hardware_workspace", None)
        if workspace and workspace.exists:
            workspace.refresh()
            workspace.focus()
            return

        try:
            self.hardware_workspace = hardware_list_ui.HardwareWorkspace(
                master=self.master,
                style=self.style,
                hardware_data=self.hardware_data,
                flat_data=self.flat_data,
                language_getter=lambda: self.lang,
                palette_getter=self._hardware_palette,
                project_name_getter=lambda: self.entry_widgets["proje_ismi"].get().strip() or "Proje",
                generate_callback=self.start_hardware_generation,
                on_close=self._on_hardware_workspace_closed,
            )
        except Exception as e:
            self.hardware_workspace = None
            messagebox.showerror(
                self._t("Donanım Listesi Hatası", "Hardware List Error"),
                self._t(
                    f"Donanım çalışma alanı açılamadı: {e}",
                    f"Hardware workspace could not be opened: {e}",
                ),
            )

    def open_hardware_cards_workspace(self):
        """Kanıtlı donanım kartı, BOM ve datasheet çalışma alanını açar."""
        workspace = getattr(self, "hardware_cards_workspace", None)
        if workspace and workspace.exists:
            workspace.refresh()
            workspace.focus()
            return
        try:
            self.hardware_cards_workspace = donanim_kartlari_ui.HardwareCardsWorkspace(
                master=self.master, style=self.style,
                language_getter=lambda: self.lang,
                palette_getter=self._hardware_palette,
                project_name_getter=lambda: self.entry_widgets["proje_ismi"].get().strip() or "Proje",
                catalog_getter=self._get_current_hardware_catalog,
                traceability_getter=self._get_current_traceability_report,
                rescan_callback=self._rescan_traceability_from_workspace,
                datasheet_callback=self._start_hardware_datasheet_ingestion,
                impact_callback=self._open_hardware_comparison,
                requirement_callback=self._open_hardware_requirement,
                on_close=self._on_hardware_cards_workspace_closed,
            )
            if self.last_hardware_impact_result:
                self.hardware_cards_workspace.set_simulation_result(
                    self.last_hardware_impact_result
                )
        except Exception as error:
            self.hardware_cards_workspace = None
            messagebox.showerror(
                self._t("Donanım Kartları Hatası", "Hardware Cards Error"),
                self._t(
                    f"Donanım Kartları çalışma alanı açılamadı: {error}",
                    f"Hardware Cards workspace could not be opened: {error}",
                ),
            )

    def open_impact_analysis_workspace(self):
        """Çok alternatifli Etki Analizi çalışma alanını açar."""
        workspace = getattr(self, "impact_analysis_workspace", None)
        if workspace and workspace.exists:
            workspace.focus()
            return

        try:
            self.impact_analysis_workspace = (
                etki_analizi_ui.ImpactAnalysisWorkspace(
                    master=self.master,
                    style=self.style,
                    language_getter=lambda: self.lang,
                    palette_getter=self._hardware_palette,
                    traceability_getter=self._get_current_traceability_report,
                    on_close=self._on_impact_analysis_workspace_closed,
                    traceability_update_callback=self._set_current_traceability_report,
                    traceability_rescan_callback=self._rescan_traceability_from_workspace,
                    traceability_cancel_callback=self._cancel_traceability_from_workspace,
                    project_info_getter=self._get_impact_project_info,
                    change_apply_callback=self._apply_approved_change_package,
                    simulation_result_callback=self._on_hardware_impact_result,
                    hardware_detail_callback=self._open_hardware_detail,
                )
            )
        except Exception as e:
            self.impact_analysis_workspace = None
            messagebox.showerror(
                self._t("Etki Analizi Hatası", "Impact Analysis Error"),
                self._t(
                    f"Etki Analizi çalışma alanı açılamadı: {e}",
                    f"Impact Analysis workspace could not be opened: {e}",
                ),
            )

    def open_architecture_framework_workspace(self):
        """Kanıta bağlı DoDAF/NAF Mimari Çerçeve Stüdyosu'nu açar."""
        workspace = getattr(self, "mimari_cerceve_workspace", None)
        if workspace and workspace.exists:
            workspace.refresh()
            workspace.focus()
            return

        try:
            self.mimari_cerceve_workspace = (
                mimari_cerceve_ui.ArchitectureFrameworkWorkspace(
                    master=self.master,
                    style=self.style,
                    flat_data_getter=lambda: self.flat_data,
                    traceability_getter=self._get_current_traceability_report,
                    project_name_getter=lambda: (
                        self.entry_widgets["proje_ismi"].get().strip() or "Proje"
                    ),
                    language_getter=lambda: self.lang,
                    palette_getter=self._hardware_palette,
                    on_close=self._on_architecture_framework_workspace_closed,
                    language_toggle_callback=self._toggle_lang,
                    theme_toggle_callback=self._toggle_theme,
                )
            )
            generation_state = getattr(self, "_architecture_generation_state", "ready")
            if generation_state == "running":
                self.mimari_cerceve_workspace.on_generation_started()
            elif generation_state == "failed":
                self.mimari_cerceve_workspace.on_generation_failed(
                    getattr(self, "_architecture_generation_detail", "")
                )
        except Exception as error:
            self.mimari_cerceve_workspace = None
            messagebox.showerror(
                self._t("Mimari Çerçeve Hatası", "Architecture Framework Error"),
                self._t(
                    f"Mimari Çerçeve Stüdyosu açılamadı: {error}",
                    f"Architecture Framework Studio could not be opened: {error}",
                ),
            )

    def _on_architecture_framework_workspace_closed(self):
        self.mimari_cerceve_workspace = None

    def _notify_architecture_sources_changed(self, requirement_ids=None):
        """Açık Mimari Stüdyo'da eski snapshot/yayım kapılarını geçersizler."""

        workspace = getattr(self, "mimari_cerceve_workspace", None)
        if not workspace or not workspace.exists:
            return
        stable_ids = (
            None if requirement_ids is None
            else tuple(sorted({str(item).strip().upper() for item in requirement_ids if str(item).strip()}))
        )
        try:
            workspace.on_sources_changed(stable_ids)
        except Exception as error:
            self.update_status_text(
                f"Mimari Çerçeve kaynak değişikliği uygulanamadı: {error}",
                is_error=True,
            )

    def _notify_architecture_source_mutation_started(self):
        """Kaynak değişmeden önce devam eden mimari yayımı senkron iptal eder.

        Bu kanca sohbet ve belge üretim worker'larından da çağrılır. Mimari
        çalışma alanındaki hedef metot Tk nesnesine dokunmaz; ayrıntılı
        stale/yenileme bildirimi mutasyon sonrası ana-thread akışında kalır.
        """

        workspace = getattr(self, "mimari_cerceve_workspace", None)
        hook = getattr(workspace, "on_source_mutation_started", None)
        if callable(hook):
            try:
                hook()
            except Exception as error:
                # Bu kanca worker thread'den gelebilir; hata yolunda dahi Tk
                # ``after``/widget çağrısı yapma. Sonraki ana-thread kaynak
                # bildirimi normal durum/uyarı akışını tamamlar.
                self._architecture_source_mutation_error = str(error)

    def _notify_architecture_generation_started(self):
        """Kısmi belge setinin eski izlenebilirlikle kullanılmasını engeller."""

        self._architecture_generation_state = "running"
        self._architecture_generation_detail = ""
        workspace = getattr(self, "mimari_cerceve_workspace", None)
        if workspace and workspace.exists:
            workspace.on_generation_started()

    def _notify_architecture_traceability_ready(self, requirement_ids=None):
        self._architecture_generation_state = "ready"
        self._architecture_generation_detail = ""
        workspace = getattr(self, "mimari_cerceve_workspace", None)
        if workspace and workspace.exists:
            stable_ids = (
                None if requirement_ids is None
                else tuple(sorted({
                    str(item).strip().upper()
                    for item in requirement_ids if str(item).strip()
                }))
            )
            workspace.on_traceability_ready(stable_ids)

    def _notify_architecture_generation_failed(self, detail=""):
        self._architecture_generation_state = "failed"
        self._architecture_generation_detail = str(detail or "")
        workspace = getattr(self, "mimari_cerceve_workspace", None)
        if workspace and workspace.exists:
            workspace.on_generation_failed(self._architecture_generation_detail)

    def _on_impact_analysis_workspace_closed(self):
        self.impact_analysis_workspace = None

    def _on_hardware_workspace_closed(self):
        self.hardware_workspace = None

    def _on_hardware_cards_workspace_closed(self):
        self.hardware_cards_workspace = None

    def _refresh_hardware_workspace(self):
        workspace = getattr(self, "hardware_workspace", None)
        if workspace and workspace.exists:
            workspace.refresh()

    def _refresh_hardware_cards_workspace(self):
        workspace = getattr(self, "hardware_cards_workspace", None)
        if workspace and workspace.exists:
            workspace.refresh()

    def _hardware_palette(self):
        return self._PALETTE["dark" if self.dark else "light"]

