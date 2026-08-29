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

class _KaynakMixin:
    def refresh(self) -> None:
        current_project_name = _clean(self.project_name_getter()) or "Proje"
        if current_project_name != self._active_project_name:
            self._reset_project_context(current_project_name)
        try:
            flat_snapshot = deepcopy(dict(self.flat_data_getter() or {}))
        except Exception as error:
            self.status_var.set(self._tr(
                f"Kaynak gereksinimleri okunamadı: {error}",
                f"Source requirements could not be read: {error}",
            ))
            flat_snapshot = {}
        self._flat_snapshot = flat_snapshot
        self._refresh_source_tree(select_all=True)
        self._refresh_candidate_tree()
        self._refresh_view_cards()

    def on_sources_changed(self, requirement_ids: Sequence[str] | None = None) -> None:
        """Kaynak revizyonunda eski kararları ezmeden ilgili kayıtları stale yapar."""

        if self._closed:
            return
        # Bu bildirim mutasyon tamamlandıktan sonra ana thread'den gelir.
        # Pre-mutation kancasının koyduğu katı kilit artık normal
        # stale-kaydı/onarım akışına devredilebilir.
        self._source_mutation_in_progress = False
        # Kaynak bildirimi ana ekrandaki proje değişiminden sonra gelebilir. Eski
        # projenin bellekteki durumunu yeni projenin ``flat_data`` verisiyle asla
        # kaydetme; önce bağlamı kesin olarak ayır.
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._publish_cancel_event.set()
        self._source_revision_blocked = True
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._source_change_token += 1
        self._state_revision += 1
        self._publish_token += 1
        self._extraction_context.clear()
        if self._working:
            self._busy(False)
        for affected_profile in PROFILE_OPTIONS:
            self._invalidate_architecture_outputs(affected_profile)
        incoming_changed_ids = frozenset(
            _clean(item).upper() for item in (requirement_ids or ()) if _clean(item)
        )
        pending_changed_ids = getattr(self, "_pending_source_changed_ids", set())
        self._pending_source_changed_ids = pending_changed_ids
        pending_changed_ids.update(incoming_changed_ids)
        if requirement_ids is None:
            self._pending_source_mark_all = True
        changed_ids = frozenset(pending_changed_ids)
        mark_all = bool(getattr(self, "_pending_source_mark_all", False))
        try:
            live_flat = self.flat_data_getter() or {}
            current_fingerprints = management.source_requirement_fingerprints(
                live_flat
            )
            current_known = tuple(
                item.requirement_id
                for item in filter_source_requirements(live_flat)
            )
        except Exception as error:
            self.status_var.set(self._tr(
                f"Kaynak değişikliği okunamadı: {error}",
                f"Source change could not be read: {error}",
            ))
            return
        token = self._source_change_token
        states = tuple(self._states_by_profile.items())
        pending_profiles = getattr(self, "_pending_source_profiles", set())
        self._pending_source_profiles = pending_profiles
        pending_profiles.update(profile_id for profile_id, _state in states)
        self._busy(True, self._tr(
            "Kaynak değişikliği arka planda kaydediliyor…",
            "Persisting source change in background…",
        ))
        try:
            worker = threading.Thread(
                target=self._source_change_worker,
                args=(
                    token, states, changed_ids, mark_all, current_known,
                    current_fingerprints,
                ),
                daemon=True,
                name="architecture-source-change",
            )
            worker.start()
        except Exception as error:
            self._source_change_token += 1
            self._busy(False)
            self.status_var.set(self._tr(
                f"Kaynak değişikliği worker'ı başlatılamadı: {error}",
                f"Source-change worker could not be started: {error}",
            ))

    def on_source_mutation_started(self) -> None:
        """Kaynak mutasyonundan önce tüm eski mimari işleri thread-safe iptal eder.

        Ana uygulamadaki sohbet/generasyon worker'ları ``flat_data`` verisini Tk
        ana döngüsü dışında değiştirebilir. Bu kanca bilinçli olarak hiçbir
        Tk nesnesine dokunmaz; kaynak değişikliğinin ayrıntılı stale/yenileme
        bildirimi mutasyon tamamlandıktan sonra ``on_sources_changed`` ile gelir.
        """

        lifecycle_lock = getattr(self, "_lifecycle_lock", None)
        if lifecycle_lock is None:
            lifecycle_lock = threading.RLock()
            self._lifecycle_lock = lifecycle_lock
        with lifecycle_lock:
            publish_cancel = getattr(self, "_publish_cancel_event", None)
            if publish_cancel is not None:
                publish_cancel.set()
            # Yalnız Python durumuna dokunulur; Tk değişkeni/widget/getter'ı yoktur.
            # Post-mutation ``on_sources_changed`` UI temizliğini ve kalıcı stale
            # yazımını tamamlayana dek hiçbir eski iş sonucu kullanılamaz.
            self._source_revision_blocked = True
            self._source_mutation_in_progress = True
            self._extraction_token = getattr(self, "_extraction_token", 0) + 1
            self._render_token = getattr(self, "_render_token", 0) + 1
            self._validation_token = getattr(self, "_validation_token", 0) + 1
            self._source_change_token = getattr(self, "_source_change_token", 0) + 1
            self._publish_token = getattr(self, "_publish_token", 0) + 1
            self._state_revision = getattr(self, "_state_revision", 0) + 1
            extraction_context = getattr(self, "_extraction_context", None)
            if extraction_context is not None:
                extraction_context.clear()

    def _source_change_worker(
        self,
        token: int,
        states: Sequence[tuple[str, management.ArchitectureManagementState]],
        changed_ids: frozenset[str],
        mark_all: bool,
        current_known: tuple[str, ...],
        current_fingerprints: Mapping[str, str] | None = None,
    ) -> None:
        updated: dict[str, management.ArchitectureManagementState] = {}
        try:
            for profile_id, original in states:
                if token != self._source_change_token or self._closed:
                    raise management.ArchitectureManagementError(
                        "Kaynak değişikliği işlemi geçersiz kılındı."
                    )
                working = management.ArchitectureManagementState.from_dict(
                    deepcopy(original.to_dict())
                )
                for record in working.records.values():
                    if record.status == management.STATUS_SUPERSEDED:
                        continue
                    source_ids = set(record.automatic_proposal.source_requirement_ids)
                    affected = source_ids if mark_all else source_ids & set(changed_ids)
                    if affected:
                        management.mark_candidate_stale(
                            working,
                            record.record_id,
                            tuple(sorted(affected)),
                            "Kaynak veri değişti; önceki kullanıcı kararı yeniden incelenmeli.",
                        )
                working.known_requirement_ids = current_known
                working.source_requirement_fingerprints = dict(current_fingerprints or {})
                # The generation check and atomic profile write are one
                # serialized CAS boundary. If a newer generation starts while
                # this save is running, its worker waits and necessarily writes
                # last; an older worker waiting here is rejected before writing.
                with self._state_write_lock:
                    if token != self._source_change_token or self._closed:
                        raise management.ArchitectureManagementError(
                            "Kaynak değişikliği işlemi geçersiz kılındı."
                        )
                    management.save_profile_management_state(working)
                updated[profile_id] = working
            error: Exception | None = None
        except Exception as caught:
            error = caught
        self._dispatch_after(
            lambda: self._finish_source_change(token, updated, error)
        )

    def _finish_source_change(
        self,
        token: int,
        updated: Mapping[str, management.ArchitectureManagementState],
        error: Exception | None,
    ) -> None:
        if token != self._source_change_token or self._closed:
            return
        self._busy(False)
        if error is not None:
            self.management_state = self._states_by_profile.get(self.profile_var.get())
            self.refresh()
            self.status_var.set(self._tr(
                f"Kaynak değişikliği tam kaydedilemedi; yeniden tarama zorunlu: {error}",
                f"Source change was not fully saved; rescan is required: {error}",
            ))
            return
        self._states_by_profile.update(updated)
        self._state_revision += 1
        self._source_revision_blocked = bool(
            getattr(self, "_source_mutation_in_progress", False)
            or getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        )
        getattr(self, "_pending_source_changed_ids", set()).clear()
        self._pending_source_mark_all = False
        getattr(self, "_pending_source_profiles", set()).clear()
        profile_id = self.profile_var.get()
        self.management_state = self._states_by_profile.get(profile_id)
        self.extraction_result = None
        self.refresh()
        self.status_var.set(self._tr(
            (
                "Belge/izlenebilirlik üretimi sürüyor; mimari işlemleri geçici olarak engelli."
                if self._source_revision_blocked
                else "Kaynaklar değişti; ilgili mimari adaylar yeniden inceleme bekliyor."
            ),
            (
                "Document/traceability generation is still running; architecture actions remain blocked."
                if self._source_revision_blocked
                else "Sources changed; affected architecture candidates require review again."
            ),
        ))

    def on_generation_started(self) -> None:
        """Belge seti kısmen yazılırken eski izlenebilirliğin kullanılmasını engeller."""

        if self._closed:
            return
        self.on_source_mutation_started()
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._source_generation_in_progress = True
        self._traceability_revision_blocked = True
        self.on_sources_changed(None)

    def on_traceability_ready(
        self, requirement_ids: Sequence[str] | None = None,
    ) -> None:
        """Yeni belge seti ve ona ait izlenebilirlik birlikte hazır olduğunda kilidi yeniler."""

        if self._closed:
            return
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._source_generation_in_progress = False
        self._traceability_revision_blocked = False
        # Son ``flat_data`` ve yeni izlenebilirlik aynı revizyon olarak yeniden
        # işlenir; blok ancak bu kayıt başarıyla tamamlanınca kalkar.
        self.on_sources_changed(requirement_ids)

    def on_generation_failed(self, detail: str = "") -> None:
        """Yeni izlenebilirlik üretilemediyse eski raporla mimari işlemi açmaz."""

        if self._closed:
            return
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project != self._active_project_name:
            self._reset_project_context(current_project)
            self.refresh()
        self._source_generation_in_progress = False
        self._source_mutation_in_progress = False
        self._traceability_revision_blocked = True
        self._source_revision_blocked = True
        self._publish_cancel_event.set()
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._publish_token += 1
        self._extraction_context.clear()
        for profile_id in PROFILE_OPTIONS:
            self._invalidate_architecture_outputs(profile_id)
        if self._working:
            self._busy(False)
        suffix = f": {detail}" if _clean(detail) else ""
        self.status_var.set(self._tr(
            f"Yeni izlenebilirlik hazırlanamadı; mimari işlemler engelli{suffix}",
            f"New traceability is unavailable; architecture actions are blocked{suffix}",
        ))

    def _ensure_sources_ready(self) -> bool:
        if not (
            getattr(self, "_source_revision_blocked", False)
            or getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        ):
            return True
        self.status_var.set(self._tr(
            "Kaynak belge seti ve ona ait yeni izlenebilirlik henüz birlikte hazır değil.",
            "The source document set and its new traceability are not ready together yet.",
        ))
        return False

    def _ensure_extraction_ready(self) -> bool:
        """Yeni kaynak/izlenebilirlik tamamlanmadan çıkarım başlatma.

        Yalnızca kaynak durumunun atomik kaydı başarısız olduysa yeniden
        çıkarım, bu durumu güncel parmak izleriyle onarabilen tek kullanıcı
        eylemidir. Bu nedenle ``_source_revision_blocked`` tek başına çıkarımı
        engellemez; belge üretimi veya izlenebilirlik yenilemesi sürüyorsa engeller.
        Render, doğrulama ve yayımlama ise daha katı ``_ensure_sources_ready``
        kapısını kullanmaya devam eder.
        """

        if not (
            getattr(self, "_source_mutation_in_progress", False)
            or
            getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        ):
            return True
        self.status_var.set(self._tr(
            "Kaynak belge seti ve ona ait yeni izlenebilirlik henüz birlikte hazır değil.",
            "The source document set and its new traceability are not ready together yet.",
        ))
        return False

    def _ensure_current_project_context(self) -> bool:
        current_project = _clean(self.project_name_getter()) or "Proje"
        if current_project == self._active_project_name:
            return True
        self._reset_project_context(current_project)
        self.refresh()
        self.status_var.set(self._tr(
            "Proje bağlamı değişti; eski mimari işlemi engellendi.",
            "Project context changed; the stale architecture action was blocked.",
        ))
        return False

    def _reset_project_context(self, project_name: str) -> None:
        """Açık pencere başka projeye geçtiğinde proje durumlarını kesin ayırır."""

        # Proje adı belge/izlenebilirlik üretimi sürerken değiştirilebilir.
        # Projeye özgü kaynak-kayıt hatasını taşıma; ancak uygulama-geneli
        # üretim/izlenebilirlik kilidini yeni bağlamda da koru.
        generation_in_progress = bool(
            getattr(self, "_source_generation_in_progress", False)
        )
        source_mutation_in_progress = bool(
            getattr(self, "_source_mutation_in_progress", False)
        )
        traceability_blocked = bool(
            getattr(self, "_traceability_revision_blocked", False)
        )
        self._publish_cancel_event.set()
        self._extraction_token += 1
        self._render_token += 1
        self._validation_token += 1
        self._source_change_token += 1
        self._state_revision += 1
        self._publish_token += 1
        self._active_project_name = _clean(project_name) or "Proje"
        self._states_by_profile.clear()
        self._render_results.clear()
        self._validation_reports.clear()
        self._preview_images.clear()
        self._preview_errors.clear()
        self._extraction_context.clear()
        self.management_state = None
        self.extraction_result = None
        self.current_snapshot = None
        self.current_render_result = None
        self.current_validation_report = None
        self._source_revision_blocked = bool(
            source_mutation_in_progress
            or generation_in_progress
            or traceability_blocked
        )
        self._source_mutation_in_progress = source_mutation_in_progress
        self._source_generation_in_progress = generation_in_progress
        self._traceability_revision_blocked = traceability_blocked
        self._pending_source_changed_ids.clear()
        self._pending_source_mark_all = False
        getattr(self, "_pending_source_profiles", set()).clear()
        if self._working:
            self._busy(False)
        if hasattr(self, "preview_canvas"):
            self._clear_preview(self._tr(
                "Proje değişti; önce yeni projenin kaynaklarını seçin.",
                "Project changed; select the new project's sources first.",
            ))

    def _filtered_sources(self) -> tuple[SourceRequirement, ...]:
        selected_type = _clean(self.source_type_var.get()).upper()
        types: Sequence[str] | str | None = (
            SUPPORTED_SOURCE_TYPES if selected_type in {"", "ALL"} else selected_type
        )
        return filter_source_requirements(
            getattr(self, "_flat_snapshot", {}), self.source_query_var.get(), types,
        )

    def _refresh_source_tree(self, select_all: bool = False) -> None:
        previous = set(self.source_tree.selection()) if hasattr(self, "source_tree") else set()
        records = self._filtered_sources()
        self._source_records = records
        for item in self.source_tree.get_children():
            self.source_tree.delete(item)
        for record in records:
            self.source_tree.insert(
                "", "end", iid=record.requirement_id,
                values=(record.record_type, record.requirement_id, record.content),
            )
        retained = [item.requirement_id for item in records if item.requirement_id in previous]
        if select_all and not previous:
            retained = [item.requirement_id for item in records]
        if retained:
            self.source_tree.selection_set(retained)
        self._update_source_count()

    def _update_source_count(self) -> None:
        selected_count = len(self.source_tree.selection())
        total = len(self._source_records)
        self.source_count_var.set(self._tr(
            f"{selected_count}/{total} kaynak seçili · yalnız TID/SGD/STT",
            f"{selected_count}/{total} sources selected · TID/SGD/STT only",
        ))

    def _selected_source_ids(self) -> tuple[str, ...]:
        return tuple(self.source_tree.selection())

    def _busy(self, value: bool, message: str = "") -> None:
        self._working = bool(value)
        self.status_var.set(message)
        buttons = (
            self.extract_button, self.render_button, self.validate_button,
            self.export_button, self.publish_button,
        )
        for button in buttons:
            button.configure(state=tk.DISABLED if value else tk.NORMAL)
        for button in getattr(self, "profile_buttons", {}).values():
            button.configure(state=tk.DISABLED if value else tk.NORMAL)
        for button, _badge in getattr(self, "_view_card_widgets", {}).values():
            button.configure(state=tk.DISABLED if value else tk.NORMAL)
        if value:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self._update_review_controls()

