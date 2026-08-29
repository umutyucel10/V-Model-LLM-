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

from . import yardimcilar
from .yardimcilar import pre_process_files, start1_time

class _UretimAkisiMixin:
    def _get_current_traceability_report(self):
        """Açık proje için bellekteki veya kalıcı son izlenebilirlik haritasını döndürür."""
        project_name = self.entry_widgets["proje_ismi"].get().strip()
        if not project_name:
            return None
        current = getattr(self, "last_traceability_report", None)
        if current and current.get("project_name") == project_name:
            return current
        try:
            loaded = etki_analizi_izlenebilirlik.load_project_traceability(project_name)
        except Exception as error:
            self.update_status_text(
                f"İzlenebilirlik haritası yüklenemedi: {error}", is_error=True
            )
            return None
        if loaded:
            if etki_analizi_entegrasyon.overrides_path(loaded).exists():
                try:
                    loaded = etki_analizi_entegrasyon.apply_overrides(loaded)
                except Exception as error:
                    self.update_status_text(
                        f"İzlenebilirlik kullanıcı düzeltmeleri uygulanamadı: {error}",
                        is_error=True,
                    )
            self.last_traceability_report = loaded
        return loaded

    def _set_current_traceability_report(self, report):
        """Etki Analizi ekranındaki kullanıcı düzeltmelerini çalışma kopyasına alır."""
        self._notify_architecture_source_mutation_started()
        self.last_traceability_report = dict(report) if report else None
        if report:
            previous = getattr(self, "last_traceability_health", None) or {}
            self.last_traceability_health = (
                etki_analizi_entegrasyon.build_health_summary(
                    report,
                    {
                        "status": previous.get("rag_status", "not_run"),
                        "message": previous.get("rag_message", ""),
                    },
                )
            )
        self._notify_architecture_traceability_ready()

    def _get_impact_project_info(self):
        """Simülasyon üst durum şeridi için seçili proje/belge setini bildirir."""
        project_name = self.entry_widgets["proje_ismi"].get().strip()
        return {
            "project_name": project_name,
            "source_paths": tuple(self.file_paths),
            "generated_document_paths": tuple(self.generated_document_paths),
            "document_count": len(self.flat_data),
            "health": getattr(self, "last_traceability_health", None),
        }

    def _apply_approved_change_package(self, package, completion_callback, failure_callback):
        """Açık onaylı paketi arka planda yeni ve atomik belge sürümüne dönüştürür."""
        if not isinstance(package, etki_analizi_degisim_paketi.ChangePackage):
            failure_callback("Değişiklik paketi geçerli değil.")
            return
        project_name = self.entry_widgets["proje_ismi"].get().strip() or package.project_name
        flat_snapshot = {
            str(key): dict(value) for key, value in self.flat_data.items()
            if isinstance(value, dict)
        }
        hardware_snapshot = {
            str(key): dict(value) for key, value in self.hardware_data.items()
            if isinstance(value, dict)
        }
        source_paths = list(dict.fromkeys(
            [*self.file_paths, *self.generated_document_paths]
        ))
        sections = tuple(tuple(section) for section in self.VMODEL_SECTIONS)
        self.update_status_text(
            "Onaylanan değişiklikler geçici sürüm alanında hazırlanıyor; özgün belgeler korunuyor..."
        )

        def worker():
            def validator(new_flat, new_hardware, stage):
                post_report = etki_analizi_izlenebilirlik.build_traceability_map(
                    project_name=project_name,
                    flat_data=new_flat,
                    hardware_data=new_hardware,
                    source_paths=(),
                    document_sections=sections,
                    persist=False,
                    check_lm_studio=False,
                )
                request = etki_analizi_simulasyon.ChangeRequest.from_mapping(
                    package.change_request
                )
                target_id = (
                    request.requirement_id
                    or str((package.selected_item or {}).get("id") or "")
                )
                node_ids = {
                    str(node.get("id")) for node in post_report.get("nodes", [])
                    if isinstance(node, dict)
                }
                warnings = []
                if target_id and target_id in node_ids:
                    try:
                        if request.change_type == etki_analizi_simulasyon.CHANGE_REQUIREMENT_ADD:
                            request = etki_analizi_simulasyon.ChangeRequest(
                                requirement_id=target_id,
                                current_value=request.proposed_value,
                                proposed_value=request.proposed_value,
                                reason="Yeni gereksinimin V-Model kapanış kontrolü",
                                requested_by=request.requested_by,
                                change_type=etki_analizi_simulasyon.CHANGE_REQUIREMENT_TEXT,
                                assumptions=request.assumptions,
                                query=request.query,
                            )
                        post_result = etki_analizi_simulasyon.simulate_change(
                            post_report,
                            request,
                            selected_id=target_id,
                            use_existing_rag=False,
                            use_lm_studio=False,
                        ).to_dict()
                    except Exception as error:
                        post_result = {
                            "status": "failed",
                            "message": f"Son etki analizi çalıştırılamadı: {error}",
                            "summary": {"impact_count": 0},
                        }
                        warnings.append(post_result["message"])
                else:
                    post_result = {
                        "status": "completed",
                        "message": (
                            "Değişen gereksinim yeni izlenebilirlikte bulunmuyor; "
                            "kaldırma işlemi doğrulandı."
                        ),
                        "summary": {"impact_count": 0},
                    }
                closure = etki_analizi_degisim_paketi.compare_closure(
                    package, post_report, post_result
                )
                reports_dir = stage / "reports"
                pdf_path = reports_dir / f"{package.change_id}_Etki_Analizi.pdf"
                excel_path = reports_dir / f"{package.change_id}_Etki_Analizi.xlsx"
                etki_analizi_degisim_raporlama.export_change_package_pdf(
                    pdf_path,
                    package,
                    before_traceability=package.baseline_traceability,
                    after_traceability=post_report,
                    closure_summary=closure,
                )
                etki_analizi_degisim_raporlama.export_change_package_excel(
                    excel_path,
                    package,
                    before_traceability=package.baseline_traceability,
                    after_traceability=post_report,
                    closure_summary=closure,
                )
                return {
                    "post_traceability": post_report,
                    "post_simulation": post_result,
                    "closure_summary": closure,
                    "report_paths": {"pdf": pdf_path, "excel": excel_path},
                    "warnings": warnings,
                }

            try:
                result = etki_analizi_degisim_paketi.apply_approved_changes(
                    package,
                    flat_snapshot,
                    hardware_data=hardware_snapshot,
                    source_paths=source_paths,
                    validator=validator,
                )
            except Exception as error:
                self.master.after(
                    0, lambda detail=str(error): failure_callback(detail)
                )
                return
            try:
                result.post_traceability = (
                    etki_analizi_izlenebilirlik.persist_traceability_report(
                        result.post_traceability
                    )
                )
            except Exception as error:
                result.warnings.append(
                    f"Yeni sürüm doğrulandı; güncel izlenebilirlik işaretçisi yazılamadı: {error}"
                )
            try:
                rag_status = etki_analizi_entegrasyon.update_structured_rag_index(
                    result.post_traceability,
                    source_paths=result.created_documents,
                    force=True,
                )
            except Exception as error:
                rag_status = {
                    "status": "failed",
                    "message": f"RAG indeksi güncellenemedi: {error}",
                }
                result.warnings.append(rag_status["message"])
            health = etki_analizi_entegrasyon.build_health_summary(
                result.post_traceability, rag_status
            )
            self.master.after(
                0,
                lambda: self._finish_approved_change_package(
                    result, health, completion_callback
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_approved_change_package(self, result, health, completion_callback):
        """Doğrulanmış sürümü tek noktada aktif eder ve açık ekranları yeniler."""
        self._notify_architecture_source_mutation_started()
        previous_requirement_ids = {
            str(key).strip().upper()
            for key, record in self.flat_data.items()
            if isinstance(record, dict) and record.get("type") in {"TID", "SGD", "STT"}
        }
        self.flat_data.clear()
        self.flat_data.update(result.new_flat_data)
        self.hardware_data.clear()
        self.hardware_data.update(result.new_hardware_data)
        ordered_types = [section[0] for section in self.VMODEL_SECTIONS]
        lines = []
        for document_type in ordered_types:
            for record in self.flat_data.values():
                if record.get("type") == document_type:
                    lines.append(
                        f"{record.get('ID', '')} | {record.get('content', '')}"
                    )
        self.last_generated_output = "\n".join(lines)
        self.raw_output_cache = self.last_generated_output
        self.last_traceability_report = result.post_traceability
        self.last_traceability_health = health
        current_requirement_ids = {
            str(key).strip().upper()
            for key, record in self.flat_data.items()
            if isinstance(record, dict) and record.get("type") in {"TID", "SGD", "STT"}
        }
        changed_requirement_ids = (
            previous_requirement_ids - current_requirement_ids
        ) | {
            str(item).strip().upper()
            for item in (*result.modified_item_ids, *result.added_item_ids)
            if str(item).strip()
        }
        self._notify_architecture_traceability_ready(changed_requirement_ids)
        for path in result.created_documents:
            if path not in self.generated_document_paths:
                self.generated_document_paths.append(path)
        self._refresh_hardware_workspace()
        self._refresh_hardware_cards_workspace()
        workspace = getattr(self, "impact_analysis_workspace", None)
        if workspace and workspace.exists:
            workspace.on_traceability_ready(result.post_traceability, health)
        self.update_status_text(
            f"{result.change_id}: v{result.new_version:04d} oluşturuldu; "
            f"{result.closure_summary.get('resolved_count', 0)} etki çözüldü, "
            f"{result.closure_summary.get('continuing_count', 0)} etki devam ediyor.",
            is_complete=True,
        )
        try:
            completion_callback(result)
        except tk.TclError:
            pass

    def _rescan_traceability_from_workspace(self, force=True):
        project_name = self.entry_widgets["proje_ismi"].get().strip()
        if not project_name:
            messagebox.showwarning(
                "İzlenebilirliği Yeniden Tara",
                "Önce proje adını girin ve belgeleri üretin.",
            )
            workspace = getattr(self, "impact_analysis_workspace", None)
            if workspace and workspace.exists:
                workspace.on_traceability_failed("Proje adı bulunamadı.")
            return
        if not self.flat_data and not self.file_paths:
            messagebox.showwarning(
                "İzlenebilirliği Yeniden Tara",
                "Taranacak üretilmiş belge verisi bulunamadı. Önce 'Dokümanları Üret' işlemini tamamlayın.",
            )
            workspace = getattr(self, "impact_analysis_workspace", None)
            if workspace and workspace.exists:
                workspace.on_traceability_failed("Taranacak belge seti bulunamadı.")
            return
        self._traceability_generation_token += 1
        self._start_traceability_build(project_name, force_rescan=bool(force))

    def _cancel_traceability_from_workspace(self):
        self._traceability_cancel_event.set()
        self._traceability_generation_token += 1
        self._notify_architecture_generation_failed("Traceability scan was cancelled.")
        self.update_status_text("Etki Analizi arka plan işlemi iptal edildi.", is_error=True)

    def _start_traceability_build(self, project_name, force_rescan=False):
        """Başarılı belge üretiminin yapılandırılmış verisini arka planda tarar."""
        token = self._traceability_generation_token
        self._traceability_cancel_event.set()
        cancel_event = threading.Event()
        self._traceability_cancel_event = cancel_event
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
        source_paths = list(dict.fromkeys([
            *self.file_paths,
            *self.generated_document_paths,
        ]))
        sections = tuple(tuple(section) for section in self.VMODEL_SECTIONS)
        self.update_status_text(
            "Etki analizi izlenebilirlik altyapısı arka planda hazırlanıyor..."
        )
        self.master.after(0, self._notify_traceability_started)
        threading.Thread(
            target=self._traceability_worker,
            args=(
                token,
                project_name,
                flat_snapshot,
                hardware_snapshot,
                source_paths,
                sections,
                force_rescan,
                cancel_event,
            ),
            daemon=True,
        ).start()

    def _traceability_worker(
        self,
        token,
        project_name,
        flat_snapshot,
        hardware_snapshot,
        source_paths,
        sections,
        force_rescan=False,
        cancel_event=None,
    ):
        """İzlenebilirliği üretir; hata belge üretiminin sonucunu değiştirmez."""
        cancel_event = cancel_event or threading.Event()
        try:
            if cancel_event.is_set():
                return
            report = etki_analizi_izlenebilirlik.build_traceability_map(
                project_name=project_name,
                flat_data=flat_snapshot,
                hardware_data=hardware_snapshot,
                source_paths=source_paths,
                document_sections=sections,
                status_callback=self.update_status_text,
            )
        except Exception as error:
            if token != self._traceability_generation_token or cancel_event.is_set():
                return
            message = (
                "Belgeler üretildi ancak Etki Analizi izlenebilirlik altyapısı "
                f"hazırlanamadı: {error}"
            )
            self.update_status_text(message, is_error=True)
            self.master.after(0, lambda detail=str(error): self._finish_traceability_failure(detail))
            return

        if token != self._traceability_generation_token or cancel_event.is_set():
            return
        try:
            report = etki_analizi_entegrasyon.apply_overrides(report)
        except Exception as error:
            self.update_status_text(
                f"Kullanıcı izlenebilirlik düzeltmeleri uygulanamadı: {error}",
                is_error=True,
            )
        try:
            rag_status = etki_analizi_entegrasyon.update_structured_rag_index(
                report,
                source_paths=source_paths,
                force=force_rescan,
                cancel_event=cancel_event,
                status_callback=self.update_status_text,
            )
        except Exception as error:
            rag_status = {
                "status": "failed",
                "updated": False,
                "message": f"RAG güncelleme uyarısı: {error}",
            }
        if token != self._traceability_generation_token or cancel_event.is_set():
            return
        health = etki_analizi_entegrasyon.build_health_summary(report, rag_status)
        catalog = None
        catalog_status = {"status": "unavailable", "message": "Donanım kataloğu oluşturulmadı."}
        try:
            previous_catalog = (
                donanim_kartlari_algilama.load_hardware_catalog(project_name)
                if report.get("storage_path") else None
            )
            catalog = donanim_kartlari_algilama.build_or_update_hardware_catalog(
                project_name,
                traceability_report=report,
                structured_hardware=hardware_snapshot,
                structured_records=flat_snapshot,
                source_paths=source_paths,
                persist=bool(report.get("storage_path")),
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
            relation_count = sum(
                1 for item in catalog.product_tree
                if item.get("parent_instance_id") not in {None, "", "Veri bulunamadı"}
            )
            catalog_change_summary = donanim_kartlari_yonetim.compare_catalogs(
                previous_catalog, catalog
            )
            catalog_status = {
                "status": "ready",
                "updated": catalog.updated,
                "hardware_count": len(catalog.hardware_items),
                "instance_count": len(catalog.product_instances),
                "relation_count": relation_count,
                "conflict_count": len(catalog.conflicts),
                "visual_count": visual_count,
                "storage_path": catalog.storage_path,
                "change_summary": catalog_change_summary,
                "message": (
                    f"Donanım kataloğu hazır: {len(catalog.hardware_items)} kart, "
                    f"{len(catalog.product_instances)} kullanım yeri, "
                    "AI görsel üretimi kullanıcı onayı bekliyor."
                ),
            }
        except Exception as error:
            catalog_status = {
                "status": "failed",
                "message": (
                    "Etki analizi hazır; donanım kataloğu güncellenemedi: "
                    f"{error}"
                ),
            }
            self.update_status_text(catalog_status["message"], is_error=True)
        summary = report.get("summary", {})
        lm_status = report.get("capabilities", {}).get("lm_studio", {})
        ready_message = (
            "Etki analizi altyapısı hazır. "
            f"{summary.get('node_count', 0)} düğüm ve "
            f"{summary.get('edge_count', 0)} ilişki oluşturuldu. "
            f"{health.get('unlinked_count', 0)} bağlantısız ve "
            f"{health.get('unverified_count', 0)} doğrulama testi olmayan gereksinim bulundu. "
            f"{catalog_status.get('hardware_count', 0)} donanım kartı hazırlandı."
        )
        self.master.after(
            0,
            lambda: self._finish_traceability_success(
                token, report, health, ready_message, lm_status, rag_status,
                catalog, catalog_status,
            ),
        )

    def _notify_traceability_started(self):
        self._notify_architecture_generation_started()
        workspace = getattr(self, "impact_analysis_workspace", None)
        if workspace and workspace.exists:
            workspace.on_traceability_started()
        cards_workspace = getattr(self, "hardware_cards_workspace", None)
        if cards_workspace and cards_workspace.exists:
            cards_workspace.set_loading(
                True, "Belge seti ve donanım kataloğu arka planda taranıyor…"
            )

    def _finish_traceability_failure(self, detail):
        self._notify_architecture_generation_failed(detail)
        workspace = getattr(self, "impact_analysis_workspace", None)
        if workspace and workspace.exists:
            workspace.on_traceability_failed(
                f"İzlenebilirlik haritası oluşturulamadı: {detail}"
            )
        cards_workspace = getattr(self, "hardware_cards_workspace", None)
        if cards_workspace and cards_workspace.exists:
            cards_workspace.set_loading(
                False, f"İzlenebilirlik taraması tamamlanamadı: {detail}"
            )
        messagebox.showwarning(
            "Etki Analizi Altyapısı",
            "Belge üretimi başarıyla tamamlandı. İzlenebilirlik haritası "
            f"oluşturulamadı:\n{detail}",
        )

    def _finish_traceability_success(
        self, token, report, health, ready_message, lm_status, rag_status,
        hardware_catalog=None, hardware_catalog_status=None,
    ):
        if token != self._traceability_generation_token:
            return
        self._notify_architecture_source_mutation_started()
        self.last_traceability_report = report
        self.last_traceability_health = health
        self._notify_architecture_traceability_ready()
        self.last_hardware_catalog = (
            hardware_catalog.to_dict() if hardware_catalog is not None else None
        )
        self.last_hardware_catalog_status = hardware_catalog_status or {
            "status": "unavailable"
        }
        self.update_status_text(ready_message, is_complete=True)
        if lm_status.get("available") is False:
            self.update_status_text(lm_status.get("message", ""), is_error=True)
        if rag_status.get("status") in {"failed", "unavailable"}:
            self.update_status_text(rag_status.get("message", ""), is_error=True)
        workspace = getattr(self, "impact_analysis_workspace", None)
        if workspace and workspace.exists:
            workspace.on_traceability_ready(report, health)
        cards_workspace = getattr(self, "hardware_cards_workspace", None)
        if cards_workspace and cards_workspace.exists:
            cards_workspace.on_catalog_ready(
                self.last_hardware_catalog,
                self.last_hardware_catalog_status,
                self.last_hardware_catalog_status.get("change_summary", {}),
            )
        notice = ready_message
        if rag_status.get("status") in {"failed", "unavailable"}:
            notice += (
                "\n\nRAG indeksi güncellenemedi; grafik tabanlı analiz kullanılmaya devam edecek."
            )
        if self.last_hardware_catalog_status.get("status") == "failed":
            notice += "\n\n" + self.last_hardware_catalog_status.get("message", "")
        messagebox.showinfo("Etki Analizi Altyapısı", notice)


    def start_generation(self):
        if not self.file_paths:
            messagebox.showerror("Hata", "Girdi dosyalarını seçin.")
            return

        try:
            proje_ismi = self.entry_widgets["proje_ismi"].get().strip()
            if not proje_ismi:
                raise ValueError("Proje İsmi boş bırakılamaz.")

            doc_counts = {
                "max_tids": int(self.entry_widgets["teknik_ister"].get() or 0),
                "max_sgds": int(self.entry_widgets["sistem_gereksinimi"].get() or 0),
                "max_stts": int(self.entry_widgets["sistem_tanimlama_testi"].get() or 0),
            }

            doc_flags = {
                "generate_kmtd": self.checkbox_vars["generate_kmtd"].get(),
                "generate_sitet": self.checkbox_vars["generate_sitet"].get(),
                "generate_alt_sistem_testi": self.checkbox_vars["generate_alt_sistem_testi"].get(),
            }

            if sum(v > 0 for v in doc_counts.values()) == 0 and not any(doc_flags.values()):
                raise ValueError("En az bir doküman sayısı veya test seçilmeli.")

        except ValueError as e:
            messagebox.showerror("Hata", f"Geçersiz giriş: {e}")
            return

        # Eski mimari yayımı, kaynak sözlüğü temizlenmeden önce iptal
        # edilmelidir; aksi halde publish worker eski snapshot'ı yeni kaynak
        # revizyonunun ``latest`` sürümü olarak commit edebilir.
        self._notify_architecture_generation_started()
        self.last_generated_output = ""
        self._traceability_generation_token += 1
        self._traceability_cancel_event.set()
        self.tree_data.clear()
        self.flat_data.clear()
        # Yeni ``flat_data`` worker tarafından parça parça doldurulur. Bu
        # sürede önceki rapor yeni kaynak setine aitmiş gibi kullanılamaz.
        self.last_traceability_report = None
        self.last_traceability_health = None
        self.hardware_data.clear()
        self.generated_document_paths.clear()
        self.last_hardware_catalog = None
        self.last_hardware_catalog_status = None
        self.last_hardware_impact_result = None
        self._invalidate_hardware_generation()
        self._refresh_hardware_workspace()
        self._refresh_hardware_cards_workspace()
        self.update_status_text("--- YAPAY ZEKA ÜRETİMİ BAŞLADI ---\n", clear=True)

        self.create_docs_button.config(state=tk.DISABLED, text=self._t("İŞLENİYOR...", "PROCESSING..."), style="success.TButton")
        self.download_docs_button.config(state=tk.DISABLED)

        thread = threading.Thread(
            target=self.run_ai_process,
            args=(self.file_paths, doc_counts, doc_flags,
                  self.format_combo.get().lower(), proje_ismi)
        )
        thread.start()

    def run_ai_process(self, file_paths, doc_counts, doc_flags, output_format, proje_ismi):
        # Bu metot test/entegrasyon tarafından ``start_generation`` dışında
        # doğrudan çağrılsa bile ilk kaynak yazımından önce yayım kapansın.
        self._notify_architecture_source_mutation_started()
        total_start_time = time.time()

        # NOT: Alt Sistem Gereksinimleri (max_stts) artık kaynak dosyadan (chunk)
        # değil, üretilen SGD listesinden türetildiği için bu kontrole dahil değildir.
        kaynak_dokuman_gerekli = (
            doc_counts["max_tids"] > 0 or
            doc_counts["max_sgds"] > 0
        )

        all_chunks = None
        sorted_indices = None

        if kaynak_dokuman_gerekli:
            # Modul-nitelikli erisim: pre_process_files "arayuz.yardimcilar"
            # uzerinde patch.object ile mock'lanabilsin diye (bkz. Faz 7
            # notu - dogrudan isim importu tek basina bunu desteklemiyordu).
            all_chunks, sorted_indices = yardimcilar.pre_process_files(file_paths, self.update_status_text)
            
            if not all_chunks:
                self.update_status_text("Hata: Kaynak dosyalardan veri alınamadı, işlem durduruluyor.", is_error=True)
                self.master.after(
                    0,
                    lambda: self._notify_architecture_generation_failed(
                        "Kaynak dosyalardan veri alınamadı."
                    ),
                )
                self.master.after(0, lambda: self._reset_buttons_state())
                return

        try:
            if doc_counts.get("max_tids", 0) > 0:
                self.update_status_text("Kullanıcı Gereksinimi üretimi başlıyor...")
                result = tid_generator_logic.run_generation_logic(
                    file_paths=None,
                    max_tids=doc_counts["max_tids"],
                    output_format=output_format,
                    project_name=proje_ismi,
                    status_callback=self.update_status_text,
                    precomputed_chunks=all_chunks,
                    precomputed_indices=sorted_indices
                )
                if result.get("result"):
                    self.last_tid_list = result.get("tid_list", [])
                    output = f"\n--- KULLANICI GEREKSİNİMİ (User Requirement) --- {proje_ismi} ---\n\n"
                    for item in self.last_tid_list:
                        output += f"{item['TID_ID']} | {item['TID_Aciklama']}\n"
                        self.flat_data[item['TID_ID']] = {
                            'type': 'TID', 'bound_to': 'Yok',
                            'ID': item['TID_ID'], 'content': item['TID_Aciklama']
                        }
                    self.last_generated_output += output
                    self.update_status_text(output, is_complete=True)

            if doc_flags["generate_kmtd"]:
                if self.last_tid_list:
                    self.update_status_text("KMTD üretimi başlıyor...")
                    try:
                        result = kmtd_generator_logic.run_generation_from_requirements(
                            requirement_list=self.last_tid_list,
                            project_name=proje_ismi,
                            status_callback=self.update_status_text
                        )
                        if result.get("result"):
                            kmtd_list = result.get("kmtd_list", [])
                            output = f"\n\n--- KABUL MUAYENE TESTİ (Acceptance Test) --- {proje_ismi} ---\n\n"
                            for item in kmtd_list:
                                output += f"{item['KMTD_ID']} | {item['KMTD_Aciklama']}\n"
                                self.flat_data[item['KMTD_ID']] = {
                                    'type': 'KMTD', 'bound_to': item['Bound_TID'],
                                    'ID': item['KMTD_ID'], 'content': item['KMTD_Aciklama']
                                }
                            self.last_generated_output += output
                            self.update_status_text(output, is_complete=True)
                    except Exception as e:
                        self.update_status_text(f"KMTD Hatası: {e}", is_error=True)

            if doc_counts.get("max_sgds", 0) > 0:
                self.update_status_text("SGD üretimi başlıyor...")
                if self.last_tid_list:
                    # İZLENEBİLİRLİK: her Kullanıcı Gereksiniminden (UR) türeyen SGD (Bound_TID)
                    result = sgd_generator_logic.run_generation_from_requirements(
                        requirement_list=self.last_tid_list,
                        max_sgds=doc_counts["max_sgds"],
                        project_name=proje_ismi,
                        status_callback=self.update_status_text
                    )
                else:
                    # UR yoksa eski yöntem: doğrudan kaynak dosyadan (genel bağ)
                    result = sgd_generator_logic.run_generation_logic(
                        file_paths=None,
                        max_sgds=doc_counts["max_sgds"],
                        output_format=output_format,
                        project_name=proje_ismi,
                        status_callback=self.update_status_text,
                        precomputed_chunks=all_chunks,
                        precomputed_indices=sorted_indices
                    )
                if result.get("result"):
                    self.last_sgd_list = result.get("sgd_list", [])
                    output = f"\n\n--- SİSTEM GEREKSİNİMİ (System Requirements) --- {proje_ismi} ---\n\n"
                    for item in self.last_sgd_list:
                        output += f"{item['SGD_ID']} | {item['SGD_Aciklama']}\n"
                        self.flat_data[item['SGD_ID']] = {
                            'type': 'SGD', 'bound_to': item.get('Bound_TID', 'TID-Genel'),
                            'ID': item['SGD_ID'], 'content': item['SGD_Aciklama']
                        }
                    self.last_generated_output += output
                    self.update_status_text(output, is_complete=True)

            if doc_flags["generate_sitet"]:
                if self.last_sgd_list:
                    self.update_status_text("SITET üretimi başlıyor...")
                    try:
                        if 'sitet_generator_logic' in sys.modules:
                            result = sitet_generator_logic.run_generation_from_requirements(
                                requirement_list=self.last_sgd_list,
                                project_name=proje_ismi,
                                status_callback=self.update_status_text
                            )
                            if result.get("result"):
                                self.last_sitet_list = result.get("sitet_list", [])
                                output = f"\n\n--- Sistem Testi (System Test) LİSTESİ --- {proje_ismi} ---\n\n"
                                for item in self.last_sitet_list:
                                    output += f"{item['SITET_ID']} | {item['SITET_Aciklama']}\n"
                                    self.flat_data[item['SITET_ID']] = {
                                        'type': 'SITET', 'bound_to': item.get('Bound_SGD', 'SGD'),
                                        'ID': item['SITET_ID'], 'content': item['SITET_Aciklama']
                                    }
                                self.last_generated_output += output
                                self.update_status_text(output, is_complete=True)
                    except Exception as e:
                        self.update_status_text(f"SITET Hatası: {e}", is_error=True)

            if doc_counts.get("max_stts", 0) > 0:
                self.update_status_text("Alt Sistem Gereksinimleri üretimi başlıyor...")
                if not self.last_sgd_list:
                    self.update_status_text(
                        "Alt Sistem Gereksinimleri için önce Sistem Gereksinimi (SGD) üretmelisiniz.",
                        is_error=True
                    )
                else:
                    try:
                        result = stt_generator_logic.run_generation_from_requirements(
                            requirement_list=self.last_sgd_list,
                            max_stts=doc_counts["max_stts"],
                            project_name=proje_ismi,
                            status_callback=self.update_status_text
                        )
                        if result.get("result"):
                            self.last_stt_list = result.get("stt_list", [])
                            output = f"\n\n--- ALT SİSTEM GEREKSİNİMLERİ (Subsystem Requirements) --- {proje_ismi} ---\n\n"
                            for item in self.last_stt_list:
                                output += f"{item['STT_ID']} | {item['STT_Aciklama']}\n"
                                self.flat_data[item['STT_ID']] = {
                                    'type': 'STT', 'bound_to': item.get('Bound_SGD', 'SGD'),
                                    'ID': item['STT_ID'], 'content': item['STT_Aciklama']
                                }
                            self.last_generated_output += output
                            self.update_status_text(output, is_complete=True)
                    except Exception as e:
                        self.update_status_text(f"Alt Sistem Gereksinimleri Hatası: {e}", is_error=True)

            if doc_flags["generate_alt_sistem_testi"]:
                if self.last_stt_list:
                    self.update_status_text("Alt Sistem Testi üretimi başlıyor...")
                    try:
                        result = alt_sistem_test_logic.run_generation_from_requirements(
                            requirement_list=self.last_stt_list,
                            project_name=proje_ismi,
                            status_callback=self.update_status_text
                        )
                        if result.get("result"):
                            self.last_alt_sistem_test_list = result.get("ast_list", [])
                            output = f"\n\n--- ALT SİSTEM TESTİ (Subsystem Test) LİSTESİ --- {proje_ismi} ---\n\n"
                            for item in self.last_alt_sistem_test_list:
                                output += f"{item['AST_ID']} | {item['AST_Aciklama']}\n"
                                self.flat_data[item['AST_ID']] = {
                                    'type': 'AST', 'bound_to': item.get('Bound_STT', 'ASG'),
                                    'ID': item['AST_ID'], 'content': item['AST_Aciklama']
                                }
                            self.last_generated_output += output
                            self.update_status_text(output, is_complete=True)
                    except Exception as e:
                        self.update_status_text(f"Alt Sistem Testi Hatası: {e}", is_error=True)

            # --- ÜRETİM SONRASI DSB DÜZELTMESİ (merkezi) ---
            # DSB SADECE 'değer belli değil' işaretidir; standart/sıfat/kap adı DEĞİLDİR.
            # (a) Model yanlış kullandıysa temizle. (b) Gereksinimde DSB varsa, ona bağlı test
            #     de o değeri DSB olarak taşısın (uydurma sayı → DSB).
            try:
                # (1) HER maddede: etiket/numara/markdown artıklarını temizle ('DONANIM/YAZILIM:',
                #     baştaki '1.' gibi — text_cleanup kullanmayan generator'lar için tek noktadan)
                #     + DSB yanlış kullanımını düzelt.
                for _d in self.flat_data.values():
                    _orig = _d.get("content", "")
                    if not _orig:
                        continue
                    _is_test = _d.get("type") in self.TEST_TYPES
                    _new = text_cleanup.temizle(_orig, test=_is_test)
                    if "DSB" in (_new or "").upper():
                        _new = text_cleanup.dsb_temizle(_new)
                    if _new and _new != _orig:
                        _d["content"] = _new
                        if _orig in (self.last_generated_output or ""):
                            self.last_generated_output = self.last_generated_output.replace(_orig, _new)
                # (2) DSB ZİNCİRİ: üst gereksinimde DSB varsa, ona bağlı testte uydurma sayı → DSB
                for _d in self.flat_data.values():
                    if _d.get("type") in self.TEST_TYPES:
                        _p = self.flat_data.get(_d.get("bound_to"))
                        _orig = _d.get("content", "")
                        if _p and "DSB" in (_p.get("content", "")).upper() and "DSB" not in _orig.upper():
                            _new = text_cleanup.sayilari_dsb_yap(_orig)
                            if _new and _new != _orig:
                                _d["content"] = _new
                                if _orig in (self.last_generated_output or ""):
                                    self.last_generated_output = self.last_generated_output.replace(_orig, _new)
            except Exception as _e:
                self.update_status_text(f"Temizlik/DSB düzeltme uyarısı: {_e}", is_error=True)

            total_end_time = time.time()
            total_duration = total_end_time - total_start_time
            minutes = int(total_duration // 60)
            seconds = int(total_duration % 60)
            
            if not self.last_generated_output.strip():
                self.update_status_text("Hiçbir doküman üretilemedi.", is_error=True)
                self.master.after(
                    0,
                    lambda: self._notify_architecture_generation_failed(
                        "Hiçbir doküman üretilemedi."
                    ),
                )
            else:
                final_msg = f"Toplam Geçen Süre: {minutes} dakika {seconds} saniye\n--- YAPAY ZEKA ÜRETİMİ TAMAMLANDI ---\n"
                self.update_status_text(final_msg, is_complete=True)
                self.raw_output_cache = self.last_generated_output  
                self._start_traceability_build(proje_ismi)

        except Exception as e:
            self.update_status_text(f"KRİTİK HATA: {e}", is_error=True)
            self.master.after(
                0,
                lambda detail=str(e): self._notify_architecture_generation_failed(detail),
            )
            traceback.print_exc()
        finally:
            self.master.after(0, lambda: self._reset_buttons_state())

    def _reset_buttons_state(self):
        self.create_docs_button.config(state=tk.NORMAL, text=self._t("Dokümanları Üret", "Generate Documents"), style="primary.TButton")
        self.download_docs_button.config(state=tk.NORMAL)
        self.reset_button.config(state=tk.NORMAL)

if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    prepare_process_identity()
    root = ttk.Window()
    app = TIDGeneratorApp(root)
    root.mainloop()
