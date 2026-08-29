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

class _AdayMixin:
    def _candidate_filter_mode(self) -> str:
        mode = _clean(self.candidate_filter_var.get())
        return mode if mode in CANDIDATE_FILTER_LABELS else CANDIDATE_FILTER_ACTIONABLE

    def _on_candidate_filter_changed(self) -> None:
        index = self.candidate_filter_combo.current()
        keys = tuple(CANDIDATE_FILTER_LABELS)
        self.candidate_filter_var.set(keys[index] if 0 <= index < len(keys) else keys[0])
        self._refresh_candidate_tree()

    def _select_all_candidates(self) -> None:
        """Filtrelenmiş listedeki tüm adayları seçer; gizli kayda dokunmaz."""

        children = self.candidate_tree.get_children()
        if children:
            self.candidate_tree.selection_set(children)
        self._show_selected_candidate()

    def _refresh_candidate_tree(self) -> None:
        if not hasattr(self, "candidate_tree"):
            return
        previous = tuple(self.candidate_tree.selection())
        for item in self.candidate_tree.get_children():
            self.candidate_tree.delete(item)
        state = getattr(self, "management_state", None)
        total = 0
        if state:
            total = len(state.records)
            for record_id in filter_candidate_records(
                state.records, self._candidate_filter_mode(),
            ):
                record = state.records[record_id]
                proposal = record.proposal
                payload = proposal.proposed_payload
                self.candidate_tree.insert(
                    "", "end", iid=record_id,
                    values=(proposal.proposal_type, payload.get("name", ""), record.status),
                    tags=(record.status,),
                )
        listed = self.candidate_tree.get_children()
        count_var = getattr(self, "candidate_count_var", None)
        if count_var is not None:
            count_var.set(
                self._tr(f"{len(listed)} / {total} kayıt", f"{len(listed)} / {total} records")
            )
        restored = tuple(item for item in previous if self.candidate_tree.exists(item))
        if restored:
            self.candidate_tree.selection_set(restored)
        elif listed:
            self.candidate_tree.selection_set(listed[0])
        self._show_selected_candidate()

    def _selected_records(self) -> tuple[management.ManagedCandidate, ...]:
        state = self.management_state
        selected = self.candidate_tree.selection() if hasattr(self, "candidate_tree") else ()
        if not state or not selected:
            return ()
        return tuple(
            record for record in (state.records.get(item) for item in selected)
            if record is not None
        )

    def _selected_record(self) -> management.ManagedCandidate | None:
        records = self._selected_records()
        return records[0] if records else None

    @staticmethod
    def _proposal_stable_id(proposal: CandidateProposal) -> str:
        """Adayın kanonikleşirse alacağı kimliği, içerik eklemeden hesaplar."""

        payload = proposal.proposed_payload
        if proposal.target_stable_id:
            return proposal.target_stable_id
        if proposal.proposal_type == "element":
            return stable_id_for("ARCH-ELEMENT", {
                "profile": proposal.framework_profile_id,
                "element_type": payload.get("element_type", ""),
                "identity_key": payload.get("identity_key", ""),
            })
        return stable_id_for("ARCH-REL", {
            "profile": proposal.framework_profile_id,
            "relationship_type": payload.get("relationship_type", ""),
            "identity_key": payload.get("identity_key", ""),
            "source": proposal.source_element_id,
            "target": proposal.target_element_id,
        })

    @staticmethod
    def _set_text(widget: Any, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def _show_selected_candidate(self) -> None:
        record = self._selected_record()
        for item in self.relationship_tree.get_children(): self.relationship_tree.delete(item)
        for item in self.validation_tree.get_children(): self.validation_tree.delete(item)
        if record is None:
            self._set_text(self.detail_text, self._tr("Aday seçilmedi.", "No candidate selected."))
            self._set_text(self.evidence_text, self._tr("Kaynak kanıtı yok.", "No source evidence."))
            self.confidence_var.set(0.0); self.confidence_text_var.set("—")
            self._update_review_controls()
            return
        proposal = record.proposal
        payload = proposal.proposed_payload
        details = [
            f"ID: {record.record_id}",
            f"{self._tr('Durum', 'Status')}: {record.status}",
            f"{self._tr('Tür', 'Type')}: {payload.get('element_type') or payload.get('relationship_type')}",
            f"{self._tr('Ad', 'Name')}: {payload.get('name', '')}",
            f"{self._tr('Açıklama', 'Description')}: {payload.get('description', '')}",
            f"{self._tr('Kaynak gereksinimler', 'Source requirements')}: {', '.join(proposal.source_requirement_ids)}",
        ]
        if record.stale_reason:
            details.append(f"stale: {record.stale_reason}")
        self._set_text(self.detail_text, "\n\n".join(details))
        evidence_parts = []
        for link in proposal.evidence_links:
            evidence_parts.append(
                f"{link.source_item_id} · {link.source_document}\n"
                f"{link.source_location}\n{link.evidence_text}\n"
                f"evidence_id={link.evidence_id}"
            )
        self._set_text(self.evidence_text, "\n\n".join(evidence_parts) or self._tr(
            "Kaynak kanıtı belirsiz/eksik.", "Source evidence is unknown/missing.",
        ))
        confidence = float(proposal.confidence_score)
        self.confidence_var.set(confidence)
        self.confidence_text_var.set(f"{confidence:.0%}")

        state = self.management_state
        if state:
            selected_stable_id = self._proposal_stable_id(proposal)
            for relation_record in state.records.values():
                candidate = relation_record.proposal
                if candidate.proposal_type != "relationship":
                    continue
                if relation_record.record_id == record.record_id or (
                    candidate.source_element_id == selected_stable_id
                    or candidate.target_element_id == selected_stable_id
                ):
                    relation_type = candidate.proposed_payload.get("relationship_type", "")
                    self.relationship_tree.insert(
                        "", "end", values=(
                            relation_type, candidate.source_element_id, candidate.target_element_id,
                        ),
                    )
        self._populate_validation_findings(record)
        self._update_review_controls()

    def _populate_validation_findings(self, record: management.ManagedCandidate | None = None) -> None:
        for item in self.validation_tree.get_children(): self.validation_tree.delete(item)
        report = self.current_validation_report
        if report:
            target_ids = {""}
            profile_id = (
                self.profile_var.get()
                if hasattr(self, "profile_var")
                else _clean(getattr(report, "framework_profile_id", ""))
            )
            view_id = self.view_var.get() if hasattr(self, "view_var") else ""
            target_ids.update((profile_id, view_id))
            if record:
                target_ids.update((
                    record.record_id,
                    record.proposal.proposal_id,
                    self._proposal_stable_id(record.proposal),
                ))
            for dimension in (
                report.view_generatability, report.model_integrity, report.framework_conformance,
            ):
                for finding in dimension.findings:
                    if finding.target_id and finding.target_id not in target_ids:
                        continue
                    scope = _clean(getattr(finding, "view_id", "")) or _clean(
                        getattr(finding, "target_id", "")
                    )
                    message = f"[{scope}] {finding.message}" if scope else finding.message
                    self.validation_tree.insert(
                        "", "end", values=(finding.severity, message),
                        tags=(finding.severity,),
                    )
        if self.extraction_result:
            for gap in self.extraction_result.information_gaps:
                self.validation_tree.insert(
                    "", "end", values=("information", gap.message), tags=("information",),
                )
        management_state = getattr(self, "management_state", None)
        if management_state:
            for conflict in management_state.conflicts:
                if conflict.resolution != management.CONFLICT_UNRESOLVED:
                    continue
                if record is not None and conflict.record_id != record.record_id:
                    continue
                self.validation_tree.insert(
                    "", "end",
                    values=(
                        "warning",
                        self._tr(
                            f"Çözülmemiş kullanıcı/otomatik çakışması: {conflict.field_name}",
                            f"Unresolved manual/automatic conflict: {conflict.field_name}",
                        ),
                    ),
                    tags=("warning",),
                )

    def _selected_unresolved_conflicts(self) -> tuple[Any, ...]:
        record = self._selected_record()
        if record is None or self.management_state is None:
            return ()
        return tuple(sorted(
            (
                conflict for conflict in self.management_state.conflicts
                if conflict.record_id == record.record_id
                and conflict.resolution == management.CONFLICT_UNRESOLVED
            ),
            key=lambda conflict: conflict.conflict_id,
        ))

    def _update_review_controls(self) -> None:
        if not hasattr(self, "approve_button"):
            return
        records = self._selected_records()
        record = records[0] if records else None
        single_disabled = (
            self._working or record is None
            or record.status == management.STATUS_SUPERSEDED
        )
        single_state = tk.DISABLED if single_disabled else tk.NORMAL
        # Onay yalnız gerçekten onaylanabilir bir kayıt seçiliyken açılır; stale
        # kayda tıklayan kullanıcı engel uyarısıyla karşılaşmaz.
        approvable = any(
            item.status in ACTIONABLE_RECORD_STATUSES for item in records
        )
        self.approve_button.configure(
            state=tk.DISABLED if (self._working or not approvable) else tk.NORMAL
        )
        self.edit_button.configure(state=single_state)
        self.reject_button.configure(state=single_state)
        if hasattr(self, "select_all_button"):
            self.select_all_button.configure(
                state=tk.DISABLED if self._working else tk.NORMAL
            )
        if hasattr(self, "conflict_button"):
            conflict_state = (
                tk.NORMAL
                if not self._working and self._selected_unresolved_conflicts()
                else tk.DISABLED
            )
            self.conflict_button.configure(state=conflict_state)

    def _persist_review_state(self) -> bool:
        state = self.management_state
        if state is None:
            return False
        management.save_profile_management_state(state)
        return True

    def _capture_review_guard(self, record_id: str) -> tuple[Any, ...]:
        """Capture the source generation and exact review-state revision."""

        state = self.management_state
        return (
            self._source_change_token,
            self._state_revision,
            self._active_project_name,
            getattr(state, "framework_profile_id", ""),
            record_id,
            state,
        )

    def _review_guard_is_current(self, guard: tuple[Any, ...]) -> bool:
        source_token, revision, project_name, profile_id, record_id, state = guard
        if (
            self._closed
            or self.management_state is not state
            or self._source_change_token != source_token
            or self._state_revision != revision
            or self._active_project_name != project_name
            or getattr(state, "framework_profile_id", "") != profile_id
            or getattr(self, "_source_revision_blocked", False)
            or getattr(self, "_source_generation_in_progress", False)
            or getattr(self, "_traceability_revision_blocked", False)
        ):
            return False
        records = getattr(state, "records", None)
        return not isinstance(records, Mapping) or not record_id or record_id in records

    def _report_stale_review_block(self) -> None:
        self.status_var.set(self._tr(
            "Kaynak veya inceleme durumu değişti; eski iletişim kutusu kararı uygulanmadı.",
            "Source or review state changed; the stale dialog decision was not applied.",
        ))

    def _review_transaction(
        self,
        mutation: Callable[[Any], None],
        *,
        expected_guard: tuple[Any, ...] | None = None,
    ) -> None:
        """Persist a review mutation only if its state revision still matches."""

        state = self.management_state
        if state is None:
            raise management.ArchitectureManagementError("İnceleme durumu yok.")
        guard = expected_guard or self._capture_review_guard("")
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            raise management.ArchitectureManagementError(
                "Kaynak veya inceleme durumu değişti; karar uygulanmadı."
            )
        working = management.ArchitectureManagementState.from_dict(
            deepcopy(state.to_dict())
        )
        mutation(working)
        profile_id = working.framework_profile_id
        with self._state_write_lock:
            if not self._review_guard_is_current(guard):
                self._report_stale_review_block()
                raise management.ArchitectureManagementError(
                    "Kaynak veya inceleme durumu değişti; karar uygulanmadı."
                )
            management.save_profile_management_state(working)
        # A source notification may arrive from another thread during the
        # atomic save. Its worker will write after us, but this stale object must
        # never be restored to the live UI state.
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            raise management.ArchitectureManagementError(
                "Kaynak veya inceleme durumu değişti; karar uygulanmadı."
            )
        self.management_state = working
        self._states_by_profile[profile_id] = working
        self._state_revision += 1

    def _element_record_index(
        self, state: management.ArchitectureManagementState,
    ) -> dict[str, str]:
        """Kanonik öğe kimliğinden yönetim kaydına eşleme kurar."""

        index: dict[str, str] = {}
        for record_id, record in state.records.items():
            if record.proposal.proposal_type != "element":
                continue
            index.setdefault(self._proposal_stable_id(record.proposal), record_id)
        return index

    def _endpoint_closure(
        self,
        state: management.ArchitectureManagementState,
        selected_ids: Sequence[str],
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Onay kümesini ilişki uçlarıyla tamamlar.

        Onaylı bir ilişkinin ucu onaysızsa ``build_working_snapshot`` her
        görünümde hata verir. Bu kapanış, onaylanabilir uçları kümeye ekler ve
        onaylanamayan (stale/eksik) uca sahip ilişkileri ayrıca döndürür.
        """

        index = self._element_record_index(state)
        required = set(selected_ids)
        unfixable: set[str] = set()
        changed = True
        while changed:
            changed = False
            for record_id, record in state.records.items():
                proposal = record.proposal
                if proposal.proposal_type != "relationship":
                    continue
                if record_id not in required and record.status != management.STATUS_APPROVED:
                    continue
                for endpoint in (proposal.source_element_id, proposal.target_element_id):
                    if not endpoint:
                        continue
                    endpoint_record_id = index.get(endpoint)
                    endpoint_record = (
                        state.records.get(endpoint_record_id) if endpoint_record_id else None
                    )
                    if endpoint_record is None:
                        unfixable.add(record_id)
                        continue
                    if endpoint_record.status == management.STATUS_APPROVED:
                        continue
                    if endpoint_record.status not in ACTIONABLE_RECORD_STATUSES:
                        unfixable.add(record_id)
                        continue
                    if endpoint_record_id not in required:
                        required.add(endpoint_record_id)
                        changed = True
        return frozenset(required), frozenset(unfixable - required)

    def _approve_selected(self) -> None:
        if not self._ensure_current_project_context():
            return
        state = self.management_state
        records = self._selected_records()
        if not state or not records:
            return
        reviewable = tuple(
            record for record in records
            if record.status in ACTIONABLE_RECORD_STATUSES
        )
        skipped = len(records) - len(reviewable)
        if not reviewable:
            messagebox.showinfo(
                self._tr("Onay Engeli", "Approval Blocked"),
                self._tr(
                    "Seçilen kayıtların hepsi stale veya superseded. Bunlar güncel "
                    "kaynakla yeniden çıkarılmadan onaylanamaz.",
                    "Every selected record is stale or superseded. These cannot be "
                    "approved without re-extraction from the current source.",
                ),
                parent=self.window,
            )
            return

        selected_ids = [record.record_id for record in reviewable]
        required, unfixable = self._endpoint_closure(state, selected_ids)
        added = required - set(selected_ids)
        reject_ids: tuple[str, ...] = ()
        if unfixable:
            titles = ", ".join(sorted(
                state.records[item].proposal.title for item in tuple(unfixable)[:5]
            ))
            answer = messagebox.askyesno(
                self._tr("Boşta kalan ilişki", "Dangling relationship"),
                self._tr(
                    f"{len(unfixable)} ilişkinin ucu onaylanamaz durumda (stale veya eksik): "
                    f"{titles}\n\nBunlar onaylı kaldığı sürece hiçbir görünüm üretilemez.\n"
                    "Bu ilişkileri reddedip devam edeyim mi?",
                    f"{len(unfixable)} relationship(s) have endpoints that cannot be approved "
                    f"(stale or missing): {titles}\n\nWhile they stay approved no view can be "
                    "generated.\nShould I reject them and continue?",
                ),
                parent=self.window,
            )
            if not answer:
                return
            reject_ids = tuple(sorted(unfixable))

        if added:
            if not messagebox.askyesno(
                self._tr("Uçları da onayla", "Approve endpoints too"),
                self._tr(
                    f"Seçtiğin {len(selected_ids)} kaydın yanına, ilişkilerin uçları olan "
                    f"{len(added)} öğe daha eklenecek. Uçlar onaysız kalırsa şema üretilemez.\n\n"
                    "Devam edilsin mi?",
                    f"{len(added)} more element(s) — the endpoints of the selected relationships — "
                    f"will be approved alongside your {len(selected_ids)} record(s). Views cannot "
                    "be generated while endpoints stay unapproved.\n\nContinue?",
                ),
                parent=self.window,
            ):
                return

        guard = self._capture_review_guard("")
        actor = self._tr("UI Kullanıcısı", "UI User")
        rationale = self._tr(
            "Mimari Stüdyo açık kullanıcı onayı",
            "Explicit Architecture Studio user approval",
        )
        endpoint_rationale = self._tr(
            "İlişki ucu olarak açık kullanıcı onayıyla birlikte onaylandı",
            "Approved together with its relationship by explicit user decision",
        )

        def mutation(working: management.ArchitectureManagementState) -> None:
            for record_id in reject_ids:
                management.reject_candidate(
                    working, record_id, actor,
                    rationale=self._tr(
                        "Ucu onaylanamayan ilişki kullanıcı onayıyla reddedildi",
                        "Relationship with unapprovable endpoint rejected by user decision",
                    ),
                )
            # Öğeler ilişkilerden önce onaylanır; ara durumda boşta uç kalmaz.
            ordered = sorted(required, key=lambda item: (
                working.records[item].proposal.proposal_type != "element", item,
            ))
            for record_id in ordered:
                if working.records[record_id].status == management.STATUS_APPROVED:
                    continue
                management.approve_candidate(
                    working, record_id, actor,
                    rationale=(rationale if record_id in set(selected_ids)
                               else endpoint_rationale),
                )

        try:
            self._review_transaction(mutation, expected_guard=guard)
        except Exception as error:
            messagebox.showerror(
                self._tr("Onay Engeli", "Approval Blocked"), str(error), parent=self.window,
            )
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree(); self._refresh_view_cards()
        parts = [self._tr(f"{len(required)} aday onaylandı", f"{len(required)} candidate(s) approved")]
        if added:
            parts.append(self._tr(f"{len(added)} uç eklendi", f"{len(added)} endpoint(s) added"))
        if reject_ids:
            parts.append(self._tr(f"{len(reject_ids)} boşta ilişki reddedildi",
                                  f"{len(reject_ids)} dangling relationship(s) rejected"))
        if skipped:
            parts.append(self._tr(f"{skipped} stale kayıt atlandı", f"{skipped} stale record(s) skipped"))
        self.status_var.set(" · ".join(parts))

    def _reject_selected(self) -> None:
        if not self._ensure_current_project_context():
            return
        record = self._selected_record()
        if not record or not self.management_state:
            return
        guard = self._capture_review_guard(record.record_id)
        reason = simpledialog.askstring(
            self._tr("Reddetme gerekçesi", "Rejection rationale"),
            self._tr("Aday neden reddediliyor?", "Why is this candidate rejected?"),
            parent=self.window,
        )
        if reason is None:
            return
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            return
        try:
            self._review_transaction(lambda state: management.reject_candidate(
                state, record.record_id, self._tr("UI Kullanıcısı", "UI User"),
                rationale=reason,
            ), expected_guard=guard)
        except Exception as error:
            messagebox.showerror(self._tr("İnceleme Engeli", "Review Blocked"), str(error), parent=self.window)
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree(); self._refresh_view_cards()

    def _edit_selected(self) -> None:
        if not self._ensure_current_project_context():
            return
        record = self._selected_record()
        if not record or not self.management_state:
            return
        guard = self._capture_review_guard(record.record_id)
        payload = dict(record.proposal.proposed_payload)
        edited = simpledialog.askstring(
            self._tr("Aday açıklamasını düzenle", "Edit candidate description"),
            self._tr("Açıklama", "Description"),
            initialvalue=str(payload.get("description", "")), parent=self.window,
        )
        if edited is None:
            return
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            return
        payload["description"] = edited
        try:
            self._review_transaction(lambda state: management.edit_candidate(
                state, record.record_id, payload,
                self._tr("UI Kullanıcısı", "UI User"),
                rationale=self._tr("Mimari Stüdyo kullanıcı düzenlemesi", "Architecture Studio user edit"),
            ), expected_guard=guard)
        except Exception as error:
            messagebox.showerror(self._tr("Düzenleme Engeli", "Edit Blocked"), str(error), parent=self.window)
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree(); self._refresh_view_cards()

    def _resolve_selected_conflict(self) -> None:
        if not self._ensure_current_project_context():
            return
        conflicts = self._selected_unresolved_conflicts()
        if not conflicts or self.management_state is None:
            return
        conflict = conflicts[0]
        guard = self._capture_review_guard(conflict.record_id)
        keep_manual = messagebox.askyesnocancel(
            self._tr("Çakışmayı çöz", "Resolve conflict"),
            self._tr(
                "Evet: kullanıcı değerini koru\nHayır: yeni otomatik değeri kullan\n"
                f"Alan: {conflict.field_name}",
                "Yes: keep the user value\nNo: use the new automatic value\n"
                f"Field: {conflict.field_name}",
            ),
            parent=self.window,
        )
        if keep_manual is None:
            return
        if not self._review_guard_is_current(guard):
            self._report_stale_review_block()
            return
        resolution = (
            management.CONFLICT_KEEP_MANUAL
            if keep_manual else management.CONFLICT_USE_AUTOMATIC
        )
        try:
            self._review_transaction(lambda state: management.resolve_conflict(
                state,
                conflict.conflict_id,
                resolution,
                self._tr("UI Kullanıcısı", "UI User"),
            ), expected_guard=guard)
        except Exception as error:
            messagebox.showerror(
                self._tr("Çakışma Çözüm Engeli", "Conflict Resolution Blocked"),
                str(error), parent=self.window,
            )
            return
        self._invalidate_architecture_outputs(self.management_state.framework_profile_id)
        self._refresh_candidate_tree()
        self._refresh_view_cards()
        self.status_var.set(self._tr(
            "Çakışma kullanıcı kararıyla çözüldü.",
            "Conflict resolved by explicit user decision.",
        ))

