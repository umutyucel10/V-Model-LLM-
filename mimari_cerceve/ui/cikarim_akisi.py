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

class _CikarimMixin:
    def _start_extraction(self) -> None:
        if self._working or not self._ensure_current_project_context():
            return
        if not self._ensure_extraction_ready():
            return
        selected_ids = set(self._selected_source_ids())
        if not selected_ids:
            self.status_var.set(self._tr("En az bir kaynak seçin.", "Select at least one source."))
            return
        profile_id = self.profile_var.get()
        try:
            live_flat = self.flat_data_getter() or {}
            source_fingerprints = management.source_requirement_fingerprints(live_flat)
            known_requirement_ids = tuple(
                item.requirement_id for item in filter_source_requirements(live_flat)
            )
            flat_snapshot = {
                str(key): deepcopy(dict(value))
                for key, value in live_flat.items()
                if isinstance(value, Mapping)
                and _clean(value.get("ID") or key).upper() in selected_ids
            }
            trace = self.traceability_getter()
            if not isinstance(trace, Mapping):
                raise ValueError(self._tr(
                    "İzlenebilirlik raporu belirsiz/eksik; önce proje izlenebilirliğini üretin.",
                    "Traceability report is unknown/missing; build project traceability first.",
                ))
            trace_snapshot = deepcopy(dict(trace))
            existing_state = getattr(self, "_states_by_profile", {}).get(profile_id)
            state_payload = (
                deepcopy(existing_state.to_dict())
                if isinstance(existing_state, management.ArchitectureManagementState)
                else None
            )
        except Exception as error:
            self.status_var.set(str(error))
            return
        self._extraction_token += 1
        token = self._extraction_token
        self._extraction_context[token] = (
            profile_id, self._active_project_name, known_requirement_ids,
            source_fingerprints,
        )
        expected_state_revision = self._state_revision
        self._busy(True, self._tr("Adaylar arka planda çıkarılıyor…", "Extracting candidates in background…"))
        try:
            worker = threading.Thread(
                target=self._extraction_worker,
                args=(
                    token, flat_snapshot, trace_snapshot, profile_id,
                    state_payload, expected_state_revision,
                ),
                daemon=True,
                name="architecture-candidate-extraction",
            )
            worker.start()
        except Exception as error:
            self._extraction_context.pop(token, None)
            self._extraction_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Aday çıkarım worker'ı başlatılamadı: {error}",
                f"Candidate-extraction worker could not be started: {error}",
            ))

    def _project_context_matches(self) -> bool:
        """Arka plan sonucunun hâlâ güncel proje bağlamına ait olduğunu söyler."""

        current = _clean(self.project_name_getter()) or "Proje"
        return current == self._active_project_name


    def _dispatch_after(self, callback: Callable[[], None]) -> None:
        """Worker sonucunu Tk çağrısı yapmadan ana-thread kuyruğuna bırakır."""

        target_queue = getattr(self, "_ui_queue", None)
        if target_queue is None:
            target_queue = queue.Queue()
            self._ui_queue = target_queue
        target_queue.put(callback)

    def _poll_ui_queue(self) -> None:
        """Yalnız Tk ana iş parçacığındaki ``after`` döngüsünden çağrılır."""

        if self._closed:
            return
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception as error:
                self.status_var.set(self._tr(
                    f"Arka plan sonucu uygulanamadı: {error}",
                    f"Background result could not be applied: {error}",
                ))
        if self.exists:
            self._poll_after_id = self.window.after(40, self._poll_ui_queue)

    def _extraction_worker(
        self,
        token: int,
        flat_snapshot: Mapping[str, Mapping[str, Any]],
        trace_snapshot: Mapping[str, Any],
        profile_id: str,
        state_payload: Mapping[str, Any] | None = None,
        expected_state_revision: int | None = None,
    ) -> None:
        try:
            result = extraction.extract_architecture_candidates(
                flat_snapshot, trace_snapshot, framework_profile_id=profile_id,
            )
            state = self._prepare_extraction_state(
                token, result, state_payload=state_payload,
                expected_state_revision=expected_state_revision,
            )
            error: Exception | None = None
        except Exception as caught:
            result = None
            state = None
            error = caught
        self._dispatch_after(
            lambda: self._finish_extraction(token, result, error, state)
        )

    def _extraction_guard_is_current(
        self,
        token: int,
        profile_id: str,
        context: Sequence[Any] | None,
        expected_state_revision: int | None = None,
    ) -> bool:
        """Worker yazımı için Tk'den bağımsız token/proje/profil CAS kapısı."""

        if context is None or len(context) < 2:
            return False
        return bool(
            not self._closed
            and token == self._extraction_token
            and self._extraction_context.get(token) == context
            and context[0] == profile_id
            and context[1] == self._active_project_name
            and (
                expected_state_revision is None
                or self._state_revision == expected_state_revision
            )
        )

    def _prepare_extraction_state(
        self,
        token: int,
        result: extraction.ArchitectureExtractionResult,
        *,
        state_payload: Mapping[str, Any] | None = None,
        expected_state_revision: int | None = None,
    ) -> management.ArchitectureManagementState:
        """Load/reconcile/save işlemlerini yalnız extraction worker'inda yapar."""

        context = self._extraction_context.get(token)
        profile_id = result.framework_profile_id
        if not self._extraction_guard_is_current(
            token, profile_id, context, expected_state_revision,
        ):
            raise management.ArchitectureManagementError(
                "Aday çıkarımı daha yeni bir proje, profil veya kaynak revizyonuyla geçersiz kılındı."
            )
        project_name = str(context[1])
        known_requirement_ids = tuple(context[2]) if len(context) > 2 else ()
        source_fingerprints = dict(context[3]) if len(context) > 3 else {}

        if state_payload is not None:
            state = management.ArchitectureManagementState.from_dict(
                deepcopy(dict(state_payload))
            )
        else:
            with self._state_write_lock:
                if not self._extraction_guard_is_current(
                    token, profile_id, context, expected_state_revision,
                ):
                    raise management.ArchitectureManagementError(
                        "Aday çıkarımı kalıcı durum okunmadan önce geçersiz kılındı."
                    )
                state = management.load_profile_management_state(
                    project_name, profile_id,
                )

        if state is None:
            state = management.create_management_state(
                project_name, result.candidates,
                framework_profile_id=profile_id,
                known_requirement_ids=known_requirement_ids,
                source_requirement_fingerprints=source_fingerprints,
            )
        else:
            management.reconcile_candidates(
                state,
                result.candidates,
                scanned_requirement_ids=result.processed_requirement_ids,
                known_requirement_ids=known_requirement_ids,
                source_fingerprints=source_fingerprints,
            )

        # Kaynak-stale worker'ları ve kullanıcı kararlarıyla aynı yazıcı
        # kilidini kullan. Token/context kontrolü ile atomik profil yazımı tek
        # CAS sınırıdır; superseded worker diske ulaşamaz.
        with self._state_write_lock:
            if not self._extraction_guard_is_current(
                token, profile_id, context, expected_state_revision,
            ):
                raise management.ArchitectureManagementError(
                    "Aday çıkarımı kalıcı durum yazılmadan önce geçersiz kılındı."
                )
            management.save_profile_management_state(state)
        return state

    def _finish_extraction(
        self,
        token: int,
        result: extraction.ArchitectureExtractionResult | None,
        error: Exception | None,
        state: management.ArchitectureManagementState | None = None,
    ) -> None:
        if token != self._extraction_token or self._closed:
            return
        context = self._extraction_context.pop(token, None)
        current_project = _clean(self.project_name_getter()) or "Proje"
        if (
            context is None
            or context[1] != current_project
            or (result is not None and context[0] != result.framework_profile_id)
        ):
            self._busy(False)
            if current_project != self._active_project_name:
                self._reset_project_context(current_project)
            return
        self._busy(False)
        if error is not None or result is None or state is None:
            self.status_var.set(self._tr(
                f"Aday çıkarımı tamamlanamadı: {error or 'kalıcı inceleme durumu hazırlanamadı'}",
                f"Candidate extraction failed: {error or 'persistent review state was not prepared'}",
            ))
            return
        self.extraction_result = result
        self._invalidate_architecture_outputs(result.framework_profile_id)
        try:
            self._states_by_profile[result.framework_profile_id] = state
            self.management_state = state
            self._state_revision += 1
            pending_profiles = getattr(self, "_pending_source_profiles", set())
            pending_profiles.discard(result.framework_profile_id)
            if not pending_profiles:
                getattr(self, "_pending_source_changed_ids", set()).clear()
                self._pending_source_mark_all = False
            self._source_revision_blocked = bool(
                pending_profiles
                or getattr(self, "_source_mutation_in_progress", False)
                or getattr(self, "_source_generation_in_progress", False)
                or getattr(self, "_traceability_revision_blocked", False)
            )
        except Exception as state_error:
            self.status_var.set(self._tr(
                f"Adaylar çıkarıldı; inceleme durumu hazırlanamadı: {state_error}",
                f"Candidates extracted; review state could not be prepared: {state_error}",
            ))
            return
        self._refresh_candidate_tree()
        self._refresh_view_cards()
        self._select_step("review")
        gap_count = len(result.information_gaps)
        self.status_var.set(self._tr(
            f"{len(result.candidates)} aday çıkarıldı; {gap_count} bilgi açığı ayrı kaydedildi.",
            f"Extracted {len(result.candidates)} candidates; {gap_count} information gaps recorded separately.",
        ))

