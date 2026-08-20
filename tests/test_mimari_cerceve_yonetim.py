# -*- coding: utf-8 -*-

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from etki_analizi_izlenebilirlik import atomic_write_json, build_traceability_map
import mimari_cerceve_cikarim as extraction
from mimari_cerceve_model import ArchitectureSnapshot, REVIEW_APPROVED, SNAPSHOT_DRAFT
import mimari_cerceve_yonetim as management


T1 = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def _flat(first_voltage="28 V", second_voltage="12 V"):
    return {
        "SGD-001": {
            "type": "SGD",
            "ID": "SGD-001",
            "content": f"Fren Kontrol Sistemi giriş gerilimi {first_voltage} olmalıdır.",
            "bound_to": "Yok",
        },
        "SGD-002": {
            "type": "SGD",
            "ID": "SGD-002",
            "content": f"Güç Yönetim Sistemi giriş gerilimi {second_voltage} olmalıdır.",
            "bound_to": "Yok",
        },
    }


def _candidates(flat):
    report = build_traceability_map(
        "Mimari Yönetim Test Projesi",
        flat_data=flat,
        persist=False,
        check_lm_studio=False,
    )
    result = extraction.extract_architecture_candidates(flat, report)
    return result.candidates


def _systems(flat):
    return tuple(
        item for item in _candidates(flat)
        if item.proposal_type == "element"
        and item.proposed_payload["element_type"] == "System"
    )


def _record_by_name(state, name):
    return next(
        item for item in state.records.values()
        if item.proposal.proposed_payload["name"] == name
    )


class CandidateLifecycleTests(unittest.TestCase):
    def test_all_management_states_are_explicit_and_user_decisions_are_audited(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _candidates(_flat()), now=T1
        )
        records = list(state.records.values())
        self.assertTrue(all(item.status == management.STATUS_CANDIDATE for item in records))
        self.assertEqual(
            management.LIFECYCLE_STATUSES,
            {"candidate", "approved", "edited", "rejected", "stale", "superseded"},
        )

        approved = management.approve_candidate(
            state, records[0].record_id, "Mimar", now=T1
        )
        rejected = management.reject_candidate(
            state, records[1].record_id, "Mimar", now=T1
        )
        self.assertEqual(approved.status, management.STATUS_APPROVED)
        self.assertEqual(rejected.status, management.STATUS_REJECTED)
        editable = records[2]
        payload = dict(editable.proposal.proposed_payload)
        payload["description"] = "Kullanıcı tarafından düzenlenen mimari açıklama."
        edited = management.edit_candidate(
            state, editable.record_id, payload, "Mimar", now=T1
        )
        stale = management.mark_candidate_stale(
            state, approved.record_id, approved.proposal.source_requirement_ids,
            "Kaynak gereksinim değişti.", now=T2,
        )
        superseded = management.supersede_candidate(
            state, rejected.record_id, edited.record_id, "Mimar", now=T2
        )

        self.assertEqual(edited.status, management.STATUS_EDITED)
        self.assertEqual(stale.status, management.STATUS_STALE)
        self.assertEqual(superseded.status, management.STATUS_SUPERSEDED)
        self.assertEqual(superseded.superseded_by, edited.record_id)
        self.assertTrue(any(item.event_type == "candidate_approved" for item in state.audit_events))
        self.assertTrue(any(item.event_type == "candidate_edited" for item in state.audit_events))
        self.assertTrue(any(item.event_type == "candidate_rejected" for item in state.audit_events))

    def test_management_state_json_round_trip_keeps_manual_data(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat()),
            known_requirement_ids=tuple(_flat()),
            source_requirement_fingerprints=management.source_requirement_fingerprints(_flat()),
            now=T1,
        )
        record = _record_by_name(state, "Fren Kontrol Sistemi")
        payload = dict(record.proposal.proposed_payload)
        payload["description"] = "Fren Kontrol Sistemi kullanıcı açıklaması."
        management.edit_candidate(state, record.record_id, payload, "Mimar", now=T1)

        restored = management.ArchitectureManagementState.from_dict(
            json.loads(json.dumps(state.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored.to_dict(), state.to_dict())
        restored_record = restored.records[record.record_id]
        self.assertEqual(restored_record.status, management.STATUS_EDITED)
        self.assertEqual(
            restored_record.proposal.proposed_payload["description"],
            "Fren Kontrol Sistemi kullanıcı açıklaması.",
        )


class ManualPreservationAndStaleTests(unittest.TestCase):
    def test_fingerprints_follow_extractor_content_and_parent_aliases(self):
        canonical = {
            "SGD-001": {
                "type": "SGD",
                "ID": "SGD-001",
                "content": "Fren Kontrol Sistemi giriş gerilimi 28 V olmalıdır.",
                "bound_to": "TID-001",
            },
        }
        alias = {
            "SGD-001": {
                "type": "SGD",
                "ID": "SGD-001",
                "description": canonical["SGD-001"]["content"],
                "bound": "TID-001",
            },
        }
        parent_alias = deepcopy(alias)
        parent_alias["SGD-001"]["parent_id"] = parent_alias["SGD-001"].pop("bound")

        canonical_digest = management.source_requirement_fingerprints(canonical)
        self.assertEqual(
            management.source_requirement_fingerprints(alias), canonical_digest
        )
        self.assertEqual(
            management.source_requirement_fingerprints(parent_alias), canonical_digest
        )

        changed = deepcopy(alias)
        changed["SGD-001"]["description"] = changed["SGD-001"][
            "description"
        ].replace("28 V", "32 V")
        self.assertNotEqual(
            management.source_requirement_fingerprints(changed), canonical_digest
        )

    def test_description_alias_change_outside_partial_scan_stales_approved_record(self):
        original = _flat("28 V", "12 V")
        changed = _flat("32 V", "12 V")
        for flat in (original, changed):
            for record in flat.values():
                record["description"] = record.pop("content")
                record["bound"] = record.pop("bound_to")
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems(original),
            known_requirement_ids=tuple(original),
            source_requirement_fingerprints=management.source_requirement_fingerprints(
                original
            ),
            now=T1,
        )
        affected = _record_by_name(state, "Fren Kontrol Sistemi")
        unaffected = _record_by_name(state, "Güç Yönetim Sistemi")
        management.approve_candidate(state, affected.record_id, "Mimar", now=T1)
        management.approve_candidate(state, unaffected.record_id, "Mimar", now=T1)

        management.reconcile_candidates(
            state,
            _systems({"SGD-002": changed["SGD-002"]}),
            scanned_requirement_ids=("SGD-002",),
            known_requirement_ids=tuple(changed),
            source_fingerprints=management.source_requirement_fingerprints(changed),
            now=T2,
        )

        self.assertEqual(affected.status, management.STATUS_STALE)
        self.assertIsNone(affected.current_decision)
        self.assertEqual(affected.stale_requirement_ids, ("SGD-001",))
        self.assertEqual(unaffected.status, management.STATUS_APPROVED)

    def test_same_id_source_change_outside_partial_scan_stales_only_affected_record(self):
        original = _flat("28 V", "12 V")
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems(original),
            known_requirement_ids=tuple(original),
            source_requirement_fingerprints=management.source_requirement_fingerprints(original),
            now=T1,
        )
        affected = _record_by_name(state, "Fren Kontrol Sistemi")
        unaffected = _record_by_name(state, "Güç Yönetim Sistemi")
        management.approve_candidate(state, affected.record_id, "Mimar", now=T1)
        management.approve_candidate(state, unaffected.record_id, "Mimar", now=T1)
        changed = _flat("32 V", "12 V")

        management.reconcile_candidates(
            state,
            _systems({"SGD-002": changed["SGD-002"]}),
            scanned_requirement_ids=("SGD-002",),
            known_requirement_ids=tuple(changed),
            source_fingerprints=management.source_requirement_fingerprints(changed),
            now=T2,
        )

        self.assertEqual(affected.status, management.STATUS_STALE)
        self.assertEqual(affected.stale_requirement_ids, ("SGD-001",))
        self.assertEqual(unaffected.status, management.STATUS_APPROVED)

    def test_stale_candidate_requires_fresh_extraction_before_new_approval(self):
        original = {"SGD-001": _flat("28 V")["SGD-001"]}
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems(original),
            known_requirement_ids=("SGD-001",),
            source_requirement_fingerprints=management.source_requirement_fingerprints(original),
            now=T1,
        )
        record = next(iter(state.records.values()))
        management.approve_candidate(state, record.record_id, "Mimar", now=T1)
        management.mark_candidate_stale(
            state, record.record_id, ("SGD-001",), "Kaynak değişti.", now=T2,
        )
        self.assertIsNone(record.current_decision)
        with self.assertRaises(management.ArchitectureManagementError):
            management.approve_candidate(state, record.record_id, "Mimar", now=T2)

        changed = {"SGD-001": _flat("32 V")["SGD-001"]}
        management.reconcile_candidates(
            state,
            _systems(changed),
            scanned_requirement_ids=("SGD-001",),
            known_requirement_ids=("SGD-001",),
            source_fingerprints=management.source_requirement_fingerprints(changed),
            now=T3,
        )

        self.assertEqual(record.status, management.STATUS_CANDIDATE)
        self.assertIn("32 V", record.proposal.proposed_payload["description"])
        management.approve_candidate(state, record.record_id, "Mimar", now=T3)
        self.assertEqual(record.status, management.STATUS_APPROVED)

    def test_legacy_state_without_fingerprints_is_conservatively_rechecked(self):
        original = _flat("28 V", "12 V")
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(original),
            known_requirement_ids=tuple(original), now=T1,
        )
        affected = _record_by_name(state, "Fren Kontrol Sistemi")
        management.approve_candidate(state, affected.record_id, "Mimar", now=T1)
        changed = _flat("32 V", "12 V")

        management.reconcile_candidates(
            state,
            _systems({"SGD-002": changed["SGD-002"]}),
            scanned_requirement_ids=("SGD-002",),
            known_requirement_ids=tuple(changed),
            source_fingerprints=management.source_requirement_fingerprints(changed),
            now=T2,
        )

        self.assertEqual(affected.status, management.STATUS_STALE)
        self.assertEqual(
            state.source_requirement_fingerprints,
            management.source_requirement_fingerprints(changed),
        )

    def test_candidate_missing_from_scanned_requirement_becomes_stale(self):
        original = {
            "SGD-001": {
                "type": "SGD", "ID": "SGD-001",
                "content": "Fren Kontrol Sistemi çalışmalıdır.",
                "bound_to": "Yok",
            },
        }
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems(original),
            known_requirement_ids=("SGD-001",),
            now=T1,
        )
        record = next(iter(state.records.values()))
        management.approve_candidate(state, record.record_id, "Mimar", now=T1)
        changed = {
            "SGD-001": {
                "type": "SGD", "ID": "SGD-001",
                "content": "Bileşen çalışmalıdır.",
                "bound_to": "Yok",
            },
        }

        management.reconcile_candidates(
            state,
            _systems(changed),
            scanned_requirement_ids=("SGD-001",),
            known_requirement_ids=("SGD-001",),
            now=T2,
        )

        self.assertEqual(record.status, management.STATUS_STALE)
        self.assertEqual(record.stale_requirement_ids, ("SGD-001",))

    def test_partial_rescan_preserves_unselected_source_evidence(self):
        full = {
            "SGD-101": {
                "type": "SGD", "ID": "SGD-101",
                "content": "Fren Kontrol Sistemi 28 V ile çalışmalıdır.",
                "bound_to": "Yok",
            },
            "STT-101": {
                "type": "STT", "ID": "STT-101",
                "content": "Fren Kontrol Sistemi durum mesajını kaydetmelidir.",
                "bound_to": "SGD-101",
            },
        }
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems(full),
            known_requirement_ids=("SGD-101", "STT-101"),
            now=T1,
        )
        record = next(iter(state.records.values()))
        management.approve_candidate(state, record.record_id, "Mimar", now=T1)

        management.reconcile_candidates(
            state,
            _systems({"SGD-101": full["SGD-101"]}),
            scanned_requirement_ids=("SGD-101",),
            known_requirement_ids=("SGD-101", "STT-101"),
            now=T2,
        )

        self.assertEqual(record.status, management.STATUS_APPROVED)
        self.assertEqual(
            {item.source_item_id for item in record.automatic_proposal.evidence_links},
            {"SGD-101", "STT-101"},
        )

    def test_removed_known_requirement_stales_its_candidate(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems({"SGD-001": _flat()["SGD-001"]}),
            known_requirement_ids=("SGD-001",),
            now=T1,
        )
        record = next(iter(state.records.values()))
        management.approve_candidate(state, record.record_id, "Mimar", now=T1)

        management.reconcile_candidates(
            state, (), known_requirement_ids=(), now=T2,
        )

        self.assertEqual(record.status, management.STATUS_STALE)
        self.assertEqual(state.known_requirement_ids, ())

    def test_rescan_preserves_manual_value_creates_conflict_and_only_stales_affected_item(self):
        original = _flat("28 V", "12 V")
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(original), now=T1
        )
        manual = _record_by_name(state, "Fren Kontrol Sistemi")
        unrelated = _record_by_name(state, "Güç Yönetim Sistemi")
        payload = dict(manual.proposal.proposed_payload)
        payload["description"] = "Fren Kontrol Sistemi manuel kullanıcı değeri."
        management.edit_candidate(state, manual.record_id, payload, "Mimar", now=T1)
        management.approve_candidate(state, unrelated.record_id, "Mimar", now=T1)
        unrelated_digest = management.proposal_digest(unrelated.proposal)

        rescanned = _flat("32 V", "12 V")
        original_snapshot = deepcopy(rescanned)
        management.reconcile_candidates(
            state,
            _systems(rescanned),
            changed_requirement_ids=("SGD-001",),
            now=T2,
        )

        self.assertEqual(rescanned, original_snapshot)
        preserved = state.records[manual.record_id]
        unchanged = state.records[unrelated.record_id]
        self.assertEqual(preserved.status, management.STATUS_STALE)
        self.assertEqual(
            preserved.proposal.proposed_payload["description"],
            "Fren Kontrol Sistemi manuel kullanıcı değeri.",
        )
        self.assertIn("32 V", preserved.automatic_proposal.proposed_payload["description"])
        current_source_links = [
            item for item in preserved.proposal.evidence_links
            if item.is_source_evidence and item.source_item_id == "SGD-001"
        ]
        self.assertEqual(len(current_source_links), 1)
        self.assertIn("32 V", current_source_links[0].evidence_text)
        self.assertEqual(unchanged.status, management.STATUS_APPROVED)
        self.assertEqual(management.proposal_digest(unchanged.proposal), unrelated_digest)
        conflicts = [
            item for item in state.conflicts
            if item.record_id == manual.record_id
            and item.field_name == "description"
        ]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].manual_value, "Fren Kontrol Sistemi manuel kullanıcı değeri.")
        self.assertIn("28 V", conflicts[0].previous_automatic_value)
        self.assertIn("32 V", conflicts[0].new_automatic_value)
        self.assertEqual(conflicts[0].resolution, management.CONFLICT_UNRESOLVED)

    def test_review_state_is_atomically_saved_and_loaded_separately(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat()), now=T1
        )
        record = _record_by_name(state, "Fren Kontrol Sistemi")
        payload = dict(record.proposal.proposed_payload)
        payload["description"] = "Fren Kontrol Sistemi kalıcı manuel açıklaması."
        management.edit_candidate(state, record.record_id, payload, "Mimar", now=T1)

        with tempfile.TemporaryDirectory() as temp:
            path = management.save_management_state(state, temp)
            loaded = management.load_management_state(state.project_name, temp)

            self.assertTrue(path.is_file())
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.to_dict(), state.to_dict())
            self.assertIn("architecture", path.parts)
            self.assertEqual(path.name, "review_state.json")

    def test_using_new_automatic_conflict_value_requires_fresh_approval(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat("28 V", "12 V")), now=T1
        )
        record = _record_by_name(state, "Fren Kontrol Sistemi")
        payload = dict(record.proposal.proposed_payload)
        payload["description"] = "Fren Kontrol Sistemi manuel değer."
        management.edit_candidate(state, record.record_id, payload, "Mimar", now=T1)
        management.reconcile_candidates(
            state,
            _systems(_flat("32 V", "12 V")),
            changed_requirement_ids=("SGD-001",),
            now=T2,
        )
        conflict = next(item for item in state.conflicts if item.record_id == record.record_id)

        management.resolve_conflict(
            state,
            conflict.conflict_id,
            management.CONFLICT_USE_AUTOMATIC,
            "Mimar",
            now=T3,
        )

        self.assertEqual(record.status, management.STATUS_CANDIDATE)
        self.assertEqual(record.manual_fields, ())
        self.assertIn("32 V", record.proposal.proposed_payload["description"])
        management.approve_candidate(state, record.record_id, "Mimar", now=T3)
        self.assertEqual(record.status, management.STATUS_APPROVED)

    def test_new_conflict_supersedes_old_value_and_only_current_auto_can_be_used(self):
        first = {"SGD-001": _flat("28 V")["SGD-001"]}
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(first), now=T1
        )
        record = next(iter(state.records.values()))
        payload = dict(record.proposal.proposed_payload)
        payload["name"] = "Fren Manuel Sistemi"
        payload["description"] = "Fren Manuel Sistemi kullanıcı açıklaması."
        management.edit_candidate(state, record.record_id, payload, "Mimar", now=T1)

        second = {"SGD-001": _flat("32 V")["SGD-001"]}
        management.reconcile_candidates(
            state,
            _systems(second),
            changed_requirement_ids=("SGD-001",),
            scanned_requirement_ids=("SGD-001",),
            now=T2,
        )
        old_conflict = next(
            item
            for item in state.conflicts
            if item.record_id == record.record_id
            and item.field_name == "description"
            and "32 V" in item.new_automatic_value
        )

        third = {"SGD-001": _flat("36 V")["SGD-001"]}
        management.reconcile_candidates(
            state,
            _systems(third),
            changed_requirement_ids=("SGD-001",),
            scanned_requirement_ids=("SGD-001",),
            now=T3,
        )
        current_conflict = next(
            item
            for item in state.conflicts
            if item.record_id == record.record_id
            and item.field_name == "description"
            and "36 V" in item.new_automatic_value
        )

        self.assertEqual(old_conflict.resolution, management.CONFLICT_SUPERSEDED)
        self.assertEqual(current_conflict.resolution, management.CONFLICT_UNRESOLVED)
        with self.assertRaisesRegex(
            management.ArchitectureManagementError, "daha önce çözülmüş"
        ):
            management.resolve_conflict(
                state,
                old_conflict.conflict_id,
                management.CONFLICT_USE_AUTOMATIC,
                "Mimar",
                now=T3,
            )

        management.resolve_conflict(
            state,
            current_conflict.conflict_id,
            management.CONFLICT_USE_AUTOMATIC,
            "Mimar",
            now=T3,
        )
        self.assertIn("36 V", record.proposal.proposed_payload["description"])
        self.assertNotIn("32 V", record.proposal.proposed_payload["description"])
        self.assertEqual(record.manual_fields, ("name",))
        management.approve_candidate(state, record.record_id, "Mimar", now=T3)
        self.assertEqual(record.status, management.STATUS_APPROVED)

    def test_legacy_old_conflict_use_automatic_is_superseded_without_mutation(self):
        first = {"SGD-001": _flat("28 V")["SGD-001"]}
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(first), now=T1
        )
        record = next(iter(state.records.values()))
        payload = dict(record.proposal.proposed_payload)
        payload["name"] = "Fren Manuel Sistemi"
        payload["description"] = "Fren Manuel Sistemi kullanıcı açıklaması."
        management.edit_candidate(state, record.record_id, payload, "Mimar", now=T1)
        management.reconcile_candidates(
            state,
            _systems({"SGD-001": _flat("32 V")["SGD-001"]}),
            changed_requirement_ids=("SGD-001",),
            scanned_requirement_ids=("SGD-001",),
            now=T2,
        )
        management.reconcile_candidates(
            state,
            _systems({"SGD-001": _flat("36 V")["SGD-001"]}),
            changed_requirement_ids=("SGD-001",),
            scanned_requirement_ids=("SGD-001",),
            now=T3,
        )
        old_conflict = next(
            item for item in state.conflicts if "32 V" in item.new_automatic_value
        )
        # Eski review_state dosyalarında aynı alan için birden fazla
        # unresolved conflict bulunabilir; bu durumun geri yüklenmesini taklit et.
        old_conflict.resolution = management.CONFLICT_UNRESOLVED
        old_conflict.resolved_at = ""
        old_conflict.resolved_by = ""
        before = dict(record.proposal.proposed_payload)

        resolved = management.resolve_conflict(
            state,
            old_conflict.conflict_id,
            management.CONFLICT_USE_AUTOMATIC,
            "Mimar",
            now=T3,
        )

        self.assertEqual(resolved.resolution, management.CONFLICT_SUPERSEDED)
        self.assertEqual(dict(record.proposal.proposed_payload), before)
        self.assertIn("36 V", record.automatic_proposal.proposed_payload["description"])
        self.assertEqual(record.status, management.STATUS_STALE)
        with self.assertRaises(management.ArchitectureManagementError):
            management.approve_candidate(state, record.record_id, "Mimar", now=T3)


class WorkingSnapshotTests(unittest.TestCase):
    def _approved_system_state(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat()), now=T1
        )
        for record in state.records.values():
            management.approve_candidate(state, record.record_id, "Baş Mimar", now=T1)
        return state

    def test_build_working_snapshot_materializes_approved_decision_chain(self):
        state = self._approved_system_state()

        snapshot = management.build_working_snapshot(
            state, ("sv-1", "SV-1"), version="v0042", now=T2
        )

        self.assertIsInstance(snapshot, ArchitectureSnapshot)
        self.assertEqual(snapshot.status, SNAPSHOT_DRAFT)
        self.assertEqual(snapshot.framework_profile_id, "dodaf")
        self.assertEqual(snapshot.framework_version, "2.02")
        self.assertEqual(snapshot.version, "v0042")
        self.assertEqual(snapshot.selected_view_ids, ("SV-1",))
        self.assertEqual(snapshot.created_at, "2026-08-13T11:00:00+00:00")
        self.assertEqual(len(snapshot.elements), 2)
        self.assertEqual(len(snapshot.relationships), 0)
        self.assertEqual(len(snapshot.candidate_proposals), 2)
        self.assertEqual(len(snapshot.review_decisions), 2)
        proposal_ids = {item.proposal_id for item in snapshot.candidate_proposals}
        decision_ids = {item.decision_id for item in snapshot.review_decisions}
        for element in snapshot.elements:
            self.assertIn(element.source_proposal_id, proposal_ids)
            self.assertIn(element.approval_decision_id, decision_ids)

    def test_unapproved_records_are_excluded_and_all_unapproved_is_rejected(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat()), now=T1
        )
        records = sorted(state.records.values(), key=lambda item: item.record_id)
        approved = management.approve_candidate(
            state, records[0].record_id, "Baş Mimar", now=T1
        )

        snapshot = management.build_working_snapshot(state, ("SV-1",), now=T2)

        self.assertEqual(
            {item.source_proposal_id for item in snapshot.elements},
            {approved.proposal.proposal_id},
        )
        self.assertNotIn(
            records[1].proposal.proposal_id,
            {item.proposal_id for item in snapshot.candidate_proposals},
        )

        empty_approval_state = management.create_management_state(
            "Onaysız Mimari Projesi", _systems(_flat()), now=T1
        )
        with self.assertRaisesRegex(
            management.ArchitectureManagementError, "approved mimari adayı"
        ):
            management.build_working_snapshot(
                empty_approval_state, ("SV-1",), now=T2
            )

    def test_approved_relationship_with_unapproved_endpoints_is_rejected(self):
        flat = _flat()
        flat["SGD-002"]["bound_to"] = "SGD-001"
        candidates = _candidates(flat)
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", candidates, now=T1
        )
        relationship = next(
            record for record in state.records.values()
            if record.proposal.proposal_type == "relationship"
        )
        payload = dict(relationship.proposal.proposed_payload)
        payload["description"] = (
            payload["description"] + " Kullanıcı tarafından doğrulandı."
        )
        management.edit_candidate(
            state, relationship.record_id, payload, "Baş Mimar", now=T1
        )
        management.approve_candidate(
            state, relationship.record_id, "Baş Mimar", now=T1
        )

        with self.assertRaisesRegex(
            management.ArchitectureManagementError, "olmayan öğe ucu"
        ):
            management.build_working_snapshot(state, ("AV-2",), now=T2)

    def test_unresolved_conflict_on_approved_record_blocks_working_snapshot(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi",
            _systems(_flat("28 V", "12 V")),
            now=T1,
        )
        record = _record_by_name(state, "Fren Kontrol Sistemi")
        payload = dict(record.proposal.proposed_payload)
        payload["description"] = "Fren Kontrol Sistemi manuel çalışma değeri."
        management.edit_candidate(state, record.record_id, payload, "Baş Mimar", now=T1)
        management.reconcile_candidates(
            state,
            _systems(_flat("32 V", "12 V")),
            changed_requirement_ids=("SGD-001",),
            now=T2,
        )
        with self.assertRaisesRegex(
            management.ArchitectureManagementError, "Stale aday"
        ):
            management.approve_candidate(state, record.record_id, "Baş Mimar", now=T2)

    def test_working_snapshot_json_round_trip(self):
        snapshot = management.build_working_snapshot(
            self._approved_system_state(), ("SV-1",), now=T2
        )

        restored = ArchitectureSnapshot.from_dict(
            json.loads(json.dumps(snapshot.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored.to_dict(), snapshot.to_dict())

    def test_user_approved_extraction_classifications_materialize_as_candidates(self):
        state = management.create_management_state(
            "Tam Çıkarım Zinciri", _candidates(_flat()), now=T1,
        )
        for record in state.records.values():
            management.approve_candidate(state, record.record_id, "Baş Mimar", now=T2)

        snapshot = management.build_working_snapshot(state, ("SV-1",), now=T3)

        self.assertTrue(snapshot.elements)
        self.assertTrue({"Measure", "ResourceConstraint"}.issubset(
            {item.element_type for item in snapshot.elements}
        ))
        self.assertEqual(
            {item.review_status for item in (*snapshot.elements, *snapshot.relationships)},
            {REVIEW_APPROVED},
        )
        self.assertEqual(len(snapshot.candidate_proposals), len(state.records))


class ProfileScopedReviewStateTests(unittest.TestCase):
    def test_profile_loader_rejects_state_copied_from_another_project(self):
        requested = management.create_management_state(
            "İstenen Proje", (), framework_profile_id="dodaf", now=T1,
        )
        foreign = management.create_management_state(
            "Başka Proje", (), framework_profile_id="dodaf", now=T1,
        )
        with tempfile.TemporaryDirectory() as temp:
            path = management.profile_review_state_path(
                requested.project_name, "dodaf", temp,
            )
            atomic_write_json(path, foreign.to_dict())

            with self.assertRaisesRegex(
                management.ArchitectureManagementError, "proje kimliği"
            ):
                management.load_profile_management_state(
                    requested.project_name, "dodaf", temp,
                )

    def test_dodaf_and_naf_review_states_are_saved_without_overwriting_each_other(self):
        dodaf = management.create_management_state(
            "İki Profil Projesi", (), framework_profile_id="dodaf", now=T1,
        )
        naf = management.create_management_state(
            "İki Profil Projesi", (), framework_profile_id="naf", now=T1,
        )
        with tempfile.TemporaryDirectory() as temp:
            dodaf_path = management.save_profile_management_state(dodaf, temp)
            naf_path = management.save_profile_management_state(naf, temp)

            self.assertNotEqual(dodaf_path, naf_path)
            self.assertTrue(dodaf_path.name.endswith(".dodaf.json"))
            self.assertTrue(naf_path.name.endswith(".naf.json"))
            self.assertEqual(
                management.load_profile_management_state(
                    "İki Profil Projesi", "dodaf", temp,
                ).framework_profile_id,
                "dodaf",
            )
            self.assertEqual(
                management.load_profile_management_state(
                    "İki Profil Projesi", "naf", temp,
                ).framework_profile_id,
                "naf",
            )

    def test_profile_loader_reads_matching_legacy_state_without_rewriting_it(self):
        state = management.create_management_state(
            "Eski İnceleme Projesi", (), framework_profile_id="dodaf", now=T1,
        )
        with tempfile.TemporaryDirectory() as temp:
            legacy_path = management.save_management_state(state, temp)
            before = legacy_path.read_bytes()

            loaded = management.load_profile_management_state(
                "Eski İnceleme Projesi", "dodaf", temp,
            )
            missing_other = management.load_profile_management_state(
                "Eski İnceleme Projesi", "naf", temp,
            )

            self.assertEqual(loaded.framework_profile_id, "dodaf")
            self.assertIsNone(missing_other)
            self.assertEqual(legacy_path.read_bytes(), before)


class ArchitectureVersioningTests(unittest.TestCase):
    def _approved_state(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat()), now=T1
        )
        for record in state.records.values():
            management.approve_candidate(state, record.record_id, "Baş Mimar", now=T1)
        return state

    def test_versions_increment_and_latest_summary_audit_are_written(self):
        state = self._approved_state()
        with tempfile.TemporaryDirectory() as temp:
            first = management.publish_approved_architecture(
                state, "Baş Mimar", output_root=temp, now=T1
            )
            record = _record_by_name(state, "Fren Kontrol Sistemi")
            payload = dict(record.proposal.proposed_payload)
            payload["description"] = "Fren Kontrol Sistemi yayımlanan manuel açıklaması."
            management.edit_candidate(state, record.record_id, payload, "Baş Mimar", now=T2)
            management.approve_candidate(state, record.record_id, "Baş Mimar", now=T2)
            second = management.publish_approved_architecture(
                state, "Baş Mimar", output_root=temp, now=T2
            )

            self.assertEqual(first.version, "v0001")
            self.assertEqual(second.version, "v0002")
            self.assertTrue(Path(first.architecture_path).is_file())
            self.assertTrue(Path(second.architecture_path).is_file())
            self.assertEqual(Path(first.architecture_path).parent.name, "v0001")
            self.assertEqual(Path(second.architecture_path).parent.name, "v0002")
            latest = json.loads(Path(second.latest_path).read_text(encoding="utf-8"))
            self.assertEqual(latest["version"], "v0002")
            self.assertEqual(latest["architecture_path"], "v0002/architecture.json")
            summary = json.loads(Path(second.change_summary_path).read_text(encoding="utf-8"))
            self.assertEqual(summary["previous_version"], "v0001")
            self.assertEqual(summary["new_version"], "v0002")
            self.assertEqual(len(summary["modified_ids"]), 1)
            audit = json.loads(Path(second.audit_log_path).read_text(encoding="utf-8"))
            published = [
                item for item in audit["events"]
                if item["event_type"] == "architecture_published"
            ]
            self.assertEqual(len(published), 2)
            loaded = management.load_latest_architecture(state.project_name, temp)
            self.assertEqual(loaded["architecture_version"], "v0002")
            self.assertEqual(loaded["status"], management.STATUS_APPROVED)

    def test_publication_freezes_validation_and_render_manifest(self):
        state = self._approved_state()
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><title>SV-1</title></svg>'
        svg_digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()
        context = {
            "claim": "framework_aligned_draft",
            "snapshot": {"snapshot_id": "ARCH-SNAPSHOT-001", "selected_view_ids": ["SV-1"]},
            "validation": {"model_integrity": {"passed": True}},
            "rendered_views": [{"view_id": "SV-1", "content_sha256": svg_digest}],
            "application_profile": None,
        }
        with tempfile.TemporaryDirectory() as temp:
            published = management.publish_approved_architecture(
                state,
                "Baş Mimar",
                output_root=temp,
                now=T1,
                publication_context=context,
                view_artifacts={"SV-1": svg},
            )
            payload = json.loads(
                Path(published.architecture_path).read_text(encoding="utf-8")
            )
            self.assertEqual(
                payload["publication_context"]["validation"], context["validation"]
            )
            self.assertEqual(
                payload["publication_context"]["claim"], "framework_aligned_draft"
            )
            artifact = Path(published.version_directory) / "views" / "SV-1.svg"
            self.assertEqual(artifact.read_text(encoding="utf-8"), svg)
            self.assertEqual(
                payload["publication_context"]["rendered_views"][0]["artifact_path"],
                "views/SV-1.svg",
            )

    def test_cancelled_precommit_guard_leaves_no_version_pointer_or_audit(self):
        state = self._approved_state()
        guard_calls = 0

        def guard():
            nonlocal guard_calls
            guard_calls += 1
            return guard_calls < 2

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(
                management.ArchitectureManagementError, "güncel olmayan işlem"
            ):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T1,
                    precommit_guard=guard,
                )
            architecture_root = Path(temp) / state.project_id / "architecture"
            self.assertFalse((architecture_root / "v0001").exists())
            self.assertFalse((architecture_root / "latest.json").exists())
            self.assertFalse((architecture_root / "audit_log.json").exists())
            self.assertFalse(any(
                item.name.startswith(".v0001.") for item in architecture_root.iterdir()
            ))

    def test_unresolved_manual_conflict_blocks_publish_until_user_keeps_manual_value(self):
        state = management.create_management_state(
            "Mimari Yönetim Test Projesi", _systems(_flat("28 V", "12 V")), now=T1
        )
        record = _record_by_name(state, "Fren Kontrol Sistemi")
        payload = dict(record.proposal.proposed_payload)
        payload["description"] = "Fren Kontrol Sistemi manuel yayımlama değeri."
        management.edit_candidate(state, record.record_id, payload, "Baş Mimar", now=T1)
        management.reconcile_candidates(
            state,
            _systems(_flat("32 V", "12 V")),
            changed_requirement_ids=("SGD-001",),
            now=T2,
        )
        conflict = next(item for item in state.conflicts if item.record_id == record.record_id)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(
                management.ArchitectureManagementError, "approved mimari"
            ):
                management.publish_approved_architecture(
                    state, "Baş Mimar", output_root=temp, now=T2
                )
            management.resolve_conflict(
                state,
                conflict.conflict_id,
                management.CONFLICT_KEEP_MANUAL,
                "Baş Mimar",
                now=T3,
            )
            management.approve_candidate(
                state, record.record_id, "Baş Mimar", now=T3,
            )
            published = management.publish_approved_architecture(
                state, "Baş Mimar", output_root=temp, now=T3
            )
            architecture = json.loads(Path(published.architecture_path).read_text(encoding="utf-8"))
            self.assertEqual(
                architecture["elements"][0]["description"],
                "Fren Kontrol Sistemi manuel yayımlama değeri.",
            )
            self.assertEqual(conflict.resolution, management.CONFLICT_KEEP_MANUAL)

    def test_failure_before_version_commit_leaves_no_half_version_or_latest(self):
        state = self._approved_state()

        def failing_writer(path, payload):
            if Path(path).name == "change_summary.json":
                raise OSError("simulated half write")
            atomic_write_json(path, payload)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(management.ArchitectureManagementError):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T1,
                    writer=failing_writer,
                )
            architecture_root = (
                Path(temp) / state.project_id / "architecture"
            )
            self.assertFalse((architecture_root / "v0001").exists())
            self.assertFalse((architecture_root / "latest.json").exists())
            self.assertFalse((architecture_root / "audit_log.json").exists())
            self.assertFalse(any(
                item.name.startswith(".v0001.") for item in architecture_root.iterdir()
            ))

    def test_latest_failure_rolls_back_committed_directory_and_audit(self):
        state = self._approved_state()

        def failing_writer(path, payload):
            if Path(path).name == "latest.json":
                raise OSError("simulated latest failure")
            atomic_write_json(path, payload)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(management.ArchitectureManagementError):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T1,
                    writer=failing_writer,
                )
            architecture_root = Path(temp) / state.project_id / "architecture"
            self.assertFalse((architecture_root / "v0001").exists())
            self.assertFalse((architecture_root / "latest.json").exists())
            self.assertFalse((architecture_root / "audit_log.json").exists())

    def test_failed_second_publish_preserves_previous_version_pointer_and_audit(self):
        state = self._approved_state()
        with tempfile.TemporaryDirectory() as temp:
            first = management.publish_approved_architecture(
                state, "Baş Mimar", output_root=temp, now=T1
            )
            latest_before = Path(first.latest_path).read_bytes()
            audit_before = Path(first.audit_log_path).read_bytes()

            def failing_writer(path, payload):
                if Path(path).name == "latest.json":
                    raise OSError("simulated second latest failure")
                atomic_write_json(path, payload)

            with self.assertRaises(management.ArchitectureManagementError):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T2,
                    writer=failing_writer,
                )

            architecture_root = Path(first.version_directory).parent
            self.assertTrue((architecture_root / "v0001" / "architecture.json").is_file())
            self.assertFalse((architecture_root / "v0002").exists())
            self.assertEqual(Path(first.latest_path).read_bytes(), latest_before)
            self.assertEqual(Path(first.audit_log_path).read_bytes(), audit_before)
            loaded = management.load_latest_architecture(state.project_name, temp)
            self.assertEqual(loaded["architecture_version"], "v0001")

    def test_baseexception_after_version_commit_is_recovered_on_load(self):
        state = self._approved_state()

        def interrupted_writer(path, payload):
            if Path(path).name == "audit_log.json":
                raise SystemExit("simulated process interruption")
            atomic_write_json(path, payload)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(SystemExit):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T1,
                    writer=interrupted_writer,
                )

            architecture_root = Path(temp) / state.project_id / "architecture"
            committed = architecture_root / "v0001"
            self.assertTrue((committed / "COMMIT.json").is_file())
            self.assertTrue((committed / "FINALIZATION.json").is_file())
            self.assertFalse((architecture_root / "latest.json").exists())

            loaded = management.load_latest_architecture(state.project_name, temp)

            self.assertEqual(loaded["architecture_version"], "v0001")
            latest = json.loads(
                (architecture_root / "latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(latest["version"], "v0001")
            audit = json.loads(
                (architecture_root / "audit_log.json").read_text(encoding="utf-8")
            )
            published = [
                item for item in audit["events"]
                if item["event_type"] == "architecture_published"
            ]
            self.assertEqual(len(published), 1)

    def test_next_publish_recovers_committed_orphan_before_incrementing(self):
        state = self._approved_state()

        def interrupted_writer(path, payload):
            if Path(path).name == "latest.json":
                raise KeyboardInterrupt("simulated crash before pointer update")
            atomic_write_json(path, payload)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(KeyboardInterrupt):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T1,
                    writer=interrupted_writer,
                )

            architecture_root = Path(temp) / state.project_id / "architecture"
            self.assertTrue((architecture_root / "v0001" / "COMMIT.json").is_file())
            self.assertFalse((architecture_root / "latest.json").exists())

            second = management.publish_approved_architecture(
                state,
                "Baş Mimar",
                output_root=temp,
                now=T2,
            )

            self.assertEqual(second.version, "v0002")
            self.assertTrue((architecture_root / "v0001" / "architecture.json").is_file())
            self.assertTrue((architecture_root / "v0002" / "architecture.json").is_file())
            latest = json.loads(Path(second.latest_path).read_text(encoding="utf-8"))
            self.assertEqual(latest["version"], "v0002")
            summary = json.loads(
                Path(second.change_summary_path).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["previous_version"], "v0001")
            audit = json.loads(Path(second.audit_log_path).read_text(encoding="utf-8"))
            published_versions = [
                item["details"]["version"]
                for item in audit["events"]
                if item["event_type"] == "architecture_published"
            ]
            self.assertEqual(published_versions, ["v0001", "v0002"])

    def test_commitless_version_is_not_loaded_or_overwritten(self):
        state = self._approved_state()
        with tempfile.TemporaryDirectory() as temp:
            architecture_root = Path(temp) / state.project_id / "architecture"
            incomplete = architecture_root / "v0001"
            incomplete.mkdir(parents=True)
            sentinel = incomplete / "architecture.json"
            sentinel.write_text('{"incomplete": true}', encoding="utf-8")
            before = sentinel.read_bytes()

            self.assertIsNone(
                management.load_latest_architecture(state.project_name, temp)
            )
            with self.assertRaisesRegex(
                management.ArchitectureManagementError,
                "sürüm klasörü zaten var",
            ):
                management.publish_approved_architecture(
                    state,
                    "Baş Mimar",
                    output_root=temp,
                    now=T1,
                )

            self.assertEqual(sentinel.read_bytes(), before)
            self.assertFalse((architecture_root / "latest.json").exists())
            self.assertFalse((architecture_root / "audit_log.json").exists())


if __name__ == "__main__":
    unittest.main()
