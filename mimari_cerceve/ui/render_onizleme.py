# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — mimari_cerceve_ui.py'nin bölünmüş
parçalarından biri. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import ttkbootstrap as ttk

import mimari_cerceve_cikarim as extraction
import mimari_cerceve_dogrulama as validation
import mimari_cerceve_render as rendering
import mimari_cerceve_yonetim as management
from mimari_cerceve_gorunumleri import DODAF_RENDER_VIEW_IDS, NAF_RENDER_VIEW_IDS
from mimari_cerceve_katalog import get_view_definition
from mimari_cerceve_model import ArchitectureSnapshot, CandidateProposal, stable_id_for

from .yardimcilar import (
    SUPPORTED_SOURCE_TYPES,
    LAYOUT_BREAKPOINT,
    VIEW_READY,
    VIEW_REVIEW_REQUIRED,
    VIEW_MISSING_INPUT,
    VIEW_BLOCKED,
    VIEW_CARD_STATES,
    WorkflowStep,
    ProfileOption,
    SourceRequirement,
    WORKFLOW_STEPS,
    PROFILE_OPTIONS,
    PROFILE_VIEW_IDS,
    CANDIDATE_FILTER_ACTIONABLE,
    CANDIDATE_FILTER_APPROVED,
    CANDIDATE_FILTER_ALL,
    CANDIDATE_FILTER_LABELS,
    ACTIONABLE_RECORD_STATUSES,
    filter_candidate_records,
    VIEW_STATE_LABELS,
    LIGHT_STATUS_COLORS,
    DARK_STATUS_COLORS,
    layout_mode_for_width,
    _clean,
    filter_source_requirements,
    _has_integrity_error,
    classify_view_card_state,
    view_card_status_label,
    threading,
    filedialog,
    messagebox,
    simpledialog,
    extraction,
    management,
    rendering,
)

class _RenderMixin:
    def _build_snapshot(self, view_ids: Sequence[str]) -> ArchitectureSnapshot:
        if self.management_state is None:
            raise management.ArchitectureManagementError(
                self._tr("Önce mimari adayları çıkarın ve gözden geçirin.",
                         "Extract and review architecture candidates first.")
            )
        return management.build_working_snapshot(
            self.management_state, tuple(view_ids), version="v0001",
        )

    def _start_render(self) -> None:
        if self._working or not self._ensure_current_project_context():
            return
        if not self._ensure_sources_ready():
            return
        if self.management_state is None:
            self.status_var.set(self._tr(
                "Önce mimari adayları çıkarın ve gözden geçirin.",
                "Extract and review architecture candidates first.",
            ))
            return
        view_id = self.view_var.get()
        self._render_token += 1
        token = self._render_token
        state = self.management_state
        preview_size = (
            max(self.preview_canvas.winfo_width() - 20, 320),
            max(self.preview_canvas.winfo_height() - 20, 220),
        )
        self._busy(True, self._tr("Görünüm arka planda üretiliyor…", "Generating view in background…"))
        try:
            worker = threading.Thread(
                target=self._render_worker,
                args=(token, state, view_id, preview_size),
                daemon=True, name="architecture-svg-render",
            )
            worker.start()
        except Exception as error:
            self._render_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Görünüm worker'ı başlatılamadı: {error}",
                f"View worker could not be started: {error}",
            ))

    @staticmethod
    def _rasterize_svg_preview(svg: str, preview_size: tuple[int, int]) -> Any:
        """SVG rasterizasyonunu Tk'den bağımsız worker bağlamında tamamlar."""

        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # type: ignore[no-redef]
        from PIL import Image

        # PyMuPDF gömülü <style> bloğunu uygulamaz; CSS inline edilmezse her
        # öğe varsayılan siyahla çizilir ve önizleme siyah bir dikdörtgen olur.
        # Kanonik SVG değişmez, yalnız bu kopya dönüştürülür.
        document = fitz.open(
            stream=rendering.svg_with_inline_styles(svg).encode("utf-8"),
            filetype="svg",
        )
        try:
            page = document[0]
            available_w, available_h = preview_size
            scale = min(
                available_w / max(page.rect.width, 1),
                available_h / max(page.rect.height, 1),
                2.0,
            )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            image.load()
            return image.copy()
        finally:
            document.close()

    def _render_worker(
        self,
        token: int,
        state: management.ArchitectureManagementState,
        view_id: str,
        preview_size: tuple[int, int],
    ) -> None:
        snapshot: ArchitectureSnapshot | None = None
        preview_image: Any | None = None
        preview_error = ""
        try:
            working_state = management.ArchitectureManagementState.from_dict(
                state.to_dict()
            )
            snapshot = management.build_working_snapshot(
                working_state, (view_id,), version="v0001",
            )
            result = rendering.render_view(snapshot, view_id)
            if result.status == rendering.RENDER_STATUS_RENDERED and result.svg:
                try:
                    preview_image = self._rasterize_svg_preview(
                        result.svg, preview_size,
                    )
                except Exception as raster_error:
                    preview_error = str(raster_error)
            error: Exception | None = None
        except Exception as caught:
            result = None; error = caught
        self._dispatch_after(lambda: self._finish_render(
            token, snapshot, view_id, result, preview_image, preview_error, error,
        ))

    def _finish_render(
        self,
        token: int,
        snapshot: ArchitectureSnapshot | None,
        view_id: str,
        result: rendering.ViewRenderResult | None,
        preview_image: Any | None,
        preview_error: str,
        error: Exception | None,
    ) -> None:
        if token != self._render_token or self._closed:
            return
        self._busy(False)
        if error is not None or result is None or snapshot is None:
            # Boşta uçlu onaylı ilişki her görünümü kilitler; ham hata yerine
            # kullanıcının uygulayabileceği çözümü göster.
            if "öğe ucu" in str(error):
                message = self._tr(
                    "Onaylı bir ilişkinin uçları onaysız; bu hâlde hiçbir görünüm "
                    "üretilemez. Adayları seçip 'Onayla'ya basın — uçlar otomatik "
                    "tamamlanır ya da düzeltilemeyen ilişki reddedilir.",
                    "An approved relationship has unapproved endpoints; no view can be "
                    "generated in this state. Select the candidates and press 'Approve' — "
                    "endpoints are completed automatically or the unfixable relationship "
                    "is rejected.",
                )
                self._clear_preview(message)
                self.status_var.set(message)
                return
            self.status_var.set(self._tr(f"Görünüm üretilemedi: {error}", f"View generation failed: {error}"))
            return
        if (
            snapshot.framework_profile_id != self.profile_var.get()
            or self.management_state is None
            or snapshot.project_id != self.management_state.project_id
            or view_id != self.view_var.get()
            or not self._project_context_matches()
        ):
            return
        self.current_snapshot = snapshot
        self.current_render_result = result
        key = (snapshot.framework_profile_id, view_id)
        self._render_results[key] = result
        if result.status == rendering.RENDER_STATUS_RENDERED and result.svg:
            if preview_image is not None:
                self._preview_images[key] = preview_image
            if preview_error:
                self._preview_errors[key] = preview_error
            self._display_svg(result.svg, preview_image, preview_error)
            self.status_var.set(self._tr(
                f"{view_id} deterministik SVG olarak üretildi.",
                f"{view_id} generated as deterministic SVG.",
            ))
            self._select_step("validate_export")
        else:
            self._clear_preview(self._tr(
                "Görünüm engellendi. Eksik girdiler:\n" + "\n".join(result.missing_inputs),
                "View blocked. Missing inputs:\n" + "\n".join(result.missing_inputs),
            ))
            self.status_var.set(self._tr("Görünüm eksik girdi nedeniyle engellendi.",
                                         "View blocked because inputs are missing."))
        self._refresh_view_cards()

    def _clear_preview(self, message: str) -> None:
        self._preview_photo = None
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            max(self.preview_canvas.winfo_width(), 300) // 2,
            max(self.preview_canvas.winfo_height(), 180) // 2,
            text=message, width=max(self.preview_canvas.winfo_width() - 60, 240),
            justify="center", tags=("placeholder",),
        )
        self._set_text(self.svg_text, message)

    def _display_svg(
        self,
        svg: str,
        preview_image: Any | None = None,
        preview_error: str = "",
    ) -> None:
        self._set_text(self.svg_text, svg)
        self.preview_canvas.delete("all")
        self._preview_photo = None
        if preview_image is not None:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(preview_image, master=self.window)
            except Exception as error:
                preview_error = str(error)
            else:
                self._preview_photo = photo
                self.preview_canvas.create_image(
                    max(self.preview_canvas.winfo_width(), preview_image.width) // 2,
                    max(self.preview_canvas.winfo_height(), preview_image.height) // 2,
                    image=photo, anchor="center",
                )
                return
        self.preview_canvas.create_text(
            max(self.preview_canvas.winfo_width(), 300) // 2,
            max(self.preview_canvas.winfo_height(), 180) // 2,
            text=self._tr(
                "SVG üretildi; raster önizleme bu ortamda belirsiz/eksik"
                + (f" ({preview_error})" if preview_error else "")
                + ".\nSVG sekmesi kullanılabilir.",
                "SVG generated; raster preview is unknown/unavailable in this environment"
                + (f" ({preview_error})" if preview_error else "")
                + ".\nUse the SVG tab.",
            ),
            width=max(self.preview_canvas.winfo_width() - 60, 240),
            justify="center",
        )

