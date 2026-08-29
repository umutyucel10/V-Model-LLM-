# -*- coding: utf-8 -*-
"""Mimari aday incelemesi, manuel koruma ve atomik sürümleme.

Bu katman KART 1'in değişmez ``CandidateProposal`` ve ``ReviewDecision``
sözleşmelerini değiştirmez. İngilizce yaşam döngüsü durumları yönetim
zarfına aittir. Kullanıcı düzenlemesi yeni bir ``user_supplied`` aday
sürümüne dönüştürülür; otomatik yeniden tarama bu sürümü ezemez.

Yayım dizilimi::

    outputs/<project_id>/architecture/vNNNN/architecture.json

Bir sürüm önce geçici klasörde hazırlanıp geri okunarak doğrulanır. Sürüm
klasörü hazır olmadan ``latest.json`` ve kök audit log ilerletilmez.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Callable, Mapping, Sequence

from etki_analizi_izlenebilirlik import atomic_write_json, project_identity
from mimari_cerceve_katalog import get_framework_profile
from mimari_cerceve_model import (
    ACTOR_USER,
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureSnapshot,
    CandidateProposal,
    DECISION_ACCEPT,
    DECISION_EDIT,
    DECISION_REJECT,
    DERIVATION_USER_SUPPLIED,
    EvidenceLink,
    REVIEW_APPROVED,
    ReviewDecision,
    SNAPSHOT_DRAFT,
    evidence_fingerprint_for,
    proposal_digest,
    stable_id_for,
)


SCHEMA_VERSION = "1.0"
PRODUCER = "mimari_cerceve_yonetim"
PRODUCER_VERSION = "1.0"
# Faz 7'de bu dosya proje kokunden mimari_cerceve/ alt paketine tasindi;
# __file__.parent artik alt paketi gosterdigi icin proje kokune cikmak icin
# bir ust dizine (.parent.parent) cikiyoruz - davranis (outputs/ klasorunu
# proje kokunde bulmak) tasimadan onceki haliyle ayni kalsin diye.
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "outputs"

STATUS_CANDIDATE = "candidate"
STATUS_APPROVED = "approved"
STATUS_EDITED = "edited"
STATUS_REJECTED = "rejected"
STATUS_STALE = "stale"
STATUS_SUPERSEDED = "superseded"
LIFECYCLE_STATUSES = frozenset({
    STATUS_CANDIDATE,
    STATUS_APPROVED,
    STATUS_EDITED,
    STATUS_REJECTED,
    STATUS_STALE,
    STATUS_SUPERSEDED,
})

CONFLICT_UNRESOLVED = "unresolved"
CONFLICT_KEEP_MANUAL = "keep_manual"
CONFLICT_USE_AUTOMATIC = "use_automatic"
CONFLICT_SUPERSEDED = "superseded"
SOURCE_REQUIREMENT_TYPES = frozenset({"TID", "SGD", "STT"})

_LOCK = threading.RLock()


class ArchitectureManagementError(ValueError):
    """İnceleme, uzlaştırma veya sürümleme güvenlik kapısı hatası."""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ArchitectureManagementError("Metin alanı string olmalıdır.")
    return " ".join(value.split())


def _now(value: datetime | None = None) -> datetime:
    result = value or datetime.now().astimezone()
    if result.tzinfo is None or result.utcoffset() is None:
        raise ArchitectureManagementError("Zaman bilgisi saat dilimi içermelidir.")
    return result


def _timestamp(value: datetime | None = None) -> str:
    return _now(value).isoformat(timespec="seconds")


def _json_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ArchitectureManagementError(f"JSON özeti üretilemedi: {error}") from error
    return hashlib.sha256(encoded).hexdigest()


def source_requirement_fingerprints(
    flat_data: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """TID/SGD/STT kaynak revizyonları için kararlı içerik parmak izi üretir."""

    if not isinstance(flat_data, Mapping):
        raise ArchitectureManagementError("Kaynak gereksinimler mapping olmalıdır.")
    result: dict[str, str] = {}
    for key, raw in flat_data.items():
        if not isinstance(raw, Mapping):
            continue
        requirement_type = _clean(raw.get("type", "")).upper()
        if requirement_type not in SOURCE_REQUIREMENT_TYPES:
            continue
        requirement_id = _clean(raw.get("ID") or str(key)).upper()
        if not requirement_id:
            raise ArchitectureManagementError("Kaynak gereksinim kimliği boş olamaz.")
        if requirement_id in result:
            raise ArchitectureManagementError("Yinelenen kaynak gereksinim kimliği var.")
        # Kaynak normalizasyonu, mimari_cerceve_cikarim._normalize_requirements
        # ile aynı alias önceliğini kullanır. Aksi halde çıkarımı
        # değiştiren ``description``/``bound``/``parent_id`` güncellemeleri
        # eski bir onayın parmak izinde görünmez.
        content = _clean(raw.get("content") or raw.get("description"))
        bound_to = _clean(
            raw.get("bound_to") or raw.get("bound") or raw.get("parent_id")
        )
        result[requirement_id] = _json_digest({
            "id": requirement_id,
            "type": requirement_type,
            "content": content,
            "bound_to": bound_to,
        })
    return {key: result[key] for key in sorted(result)}


def _payload(proposal: CandidateProposal) -> dict[str, str]:
    return {str(key): str(value) for key, value in proposal.proposed_payload.items()}


def _record_id_for(proposal: CandidateProposal) -> str:
    payload = _payload(proposal)
    entity_type = payload.get(
        "element_type" if proposal.proposal_type == "element" else "relationship_type",
        "",
    )
    return stable_id_for("ARCH-REVIEW", {
        "profile": proposal.framework_profile_id,
        "proposal_type": proposal.proposal_type,
        "entity_type": entity_type,
        "identity_key": proposal.identity_key,
        "source_element_id": proposal.source_element_id,
        "target_element_id": proposal.target_element_id,
    })


def _source_signature(proposal: CandidateProposal) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (link.source_item_id.upper(), link.evidence_fingerprint)
        for link in proposal.evidence_links
        if link.is_source_evidence
    ))


def _source_ids(proposal: CandidateProposal) -> frozenset[str]:
    return frozenset(item.upper() for item in proposal.source_requirement_ids)


@dataclass(slots=True)
class AuditEvent:
    event_type: str
    occurred_at: str
    actor: str
    record_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""

    def __post_init__(self) -> None:
        self.event_type = _clean(self.event_type)
        self.occurred_at = _clean(self.occurred_at)
        self.actor = _clean(self.actor)
        self.record_id = _clean(self.record_id)
        if not self.event_type or not self.occurred_at or not self.actor:
            raise ArchitectureManagementError("Audit olayı tür, zaman ve aktör gerektirir.")
        try:
            parsed = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ArchitectureManagementError("Audit zamanı ISO-8601 olmalıdır.") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ArchitectureManagementError("Audit zamanı saat dilimi içermelidir.")
        if not isinstance(self.details, Mapping):
            raise ArchitectureManagementError("Audit ayrıntıları JSON nesnesi olmalıdır.")
        self.details = deepcopy(dict(self.details))
        self.event_id = _clean(self.event_id) or stable_id_for("ARCH-AUDIT", {
            "type": self.event_type,
            "time": self.occurred_at,
            "actor": self.actor,
            "record": self.record_id,
            "details_digest": _json_digest(self.details),
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "record_id": self.record_id,
            "details": deepcopy(self.details),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AuditEvent":
        if not isinstance(raw, Mapping):
            raise ArchitectureManagementError("Audit olayı JSON nesnesi olmalıdır.")
        return cls(
            event_type=raw.get("event_type", ""),
            occurred_at=raw.get("occurred_at", ""),
            actor=raw.get("actor", ""),
            record_id=raw.get("record_id", ""),
            details=raw.get("details", {}),
            event_id=raw.get("event_id", ""),
        )


@dataclass(slots=True)
class ArchitectureConflict:
    record_id: str
    field_name: str
    manual_value: str
    previous_automatic_value: str
    new_automatic_value: str
    source_requirement_ids: tuple[str, ...]
    created_at: str
    resolution: str = CONFLICT_UNRESOLVED
    resolved_at: str = ""
    resolved_by: str = ""
    conflict_id: str = ""

    def __post_init__(self) -> None:
        self.record_id = _clean(self.record_id)
        self.field_name = _clean(self.field_name)
        self.manual_value = _clean(self.manual_value)
        self.previous_automatic_value = _clean(self.previous_automatic_value)
        self.new_automatic_value = _clean(self.new_automatic_value)
        self.created_at = _clean(self.created_at)
        self.resolution = _clean(self.resolution)
        self.resolved_at = _clean(self.resolved_at)
        self.resolved_by = _clean(self.resolved_by)
        self.source_requirement_ids = tuple(sorted({
            _clean(item).upper() for item in self.source_requirement_ids if _clean(item)
        }))
        if not self.record_id or not self.field_name or not self.created_at:
            raise ArchitectureManagementError("Conflict kayıt kimliği, alanı ve zamanı gerektirir.")
        if self.resolution not in {
            CONFLICT_UNRESOLVED, CONFLICT_KEEP_MANUAL, CONFLICT_USE_AUTOMATIC,
            CONFLICT_SUPERSEDED,
        }:
            raise ArchitectureManagementError("Desteklenmeyen conflict çözümü.")
        if self.resolution == CONFLICT_UNRESOLVED and (self.resolved_at or self.resolved_by):
            raise ArchitectureManagementError("Çözülmemiş conflict çözüm bilgisi taşıyamaz.")
        if self.resolution != CONFLICT_UNRESOLVED and (not self.resolved_at or not self.resolved_by):
            raise ArchitectureManagementError("Çözülmüş conflict aktör ve zaman gerektirir.")
        self.conflict_id = _clean(self.conflict_id) or stable_id_for("ARCH-CONFLICT", {
            "record": self.record_id,
            "field": self.field_name,
            "manual": self.manual_value,
            "previous_auto": self.previous_automatic_value,
            "new_auto": self.new_automatic_value,
            # Aynı otomatik değer döngüsü daha sonra yeniden oluşursa,
            # önceki çözülmüş/superseded olay audit geçmişini korurken
            # yeni olay ayrı bir conflict olarak incelenebilmelidir.
            "created_at": self.created_at,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "record_id": self.record_id,
            "field_name": self.field_name,
            "manual_value": self.manual_value,
            "previous_automatic_value": self.previous_automatic_value,
            "new_automatic_value": self.new_automatic_value,
            "source_requirement_ids": list(self.source_requirement_ids),
            "created_at": self.created_at,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArchitectureConflict":
        if not isinstance(raw, Mapping):
            raise ArchitectureManagementError("Conflict JSON nesnesi olmalıdır.")
        return cls(
            record_id=raw.get("record_id", ""),
            field_name=raw.get("field_name", ""),
            manual_value=raw.get("manual_value", ""),
            previous_automatic_value=raw.get("previous_automatic_value", ""),
            new_automatic_value=raw.get("new_automatic_value", ""),
            source_requirement_ids=tuple(raw.get("source_requirement_ids", ())),
            created_at=raw.get("created_at", ""),
            resolution=raw.get("resolution", CONFLICT_UNRESOLVED),
            resolved_at=raw.get("resolved_at", ""),
            resolved_by=raw.get("resolved_by", ""),
            conflict_id=raw.get("conflict_id", ""),
        )


@dataclass(slots=True)
class ManagedCandidate:
    proposal: CandidateProposal
    automatic_proposal: CandidateProposal
    status: str = STATUS_CANDIDATE
    manual_fields: tuple[str, ...] = ()
    current_decision: ReviewDecision | None = None
    decision_history: tuple[ReviewDecision, ...] = ()
    previous_proposal_ids: tuple[str, ...] = ()
    stale_requirement_ids: tuple[str, ...] = ()
    stale_reason: str = ""
    superseded_by: str = ""
    updated_at: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, CandidateProposal):
            self.proposal = CandidateProposal.from_dict(self.proposal)
        if not isinstance(self.automatic_proposal, CandidateProposal):
            self.automatic_proposal = CandidateProposal.from_dict(self.automatic_proposal)
        self.status = _clean(self.status)
        if self.status not in LIFECYCLE_STATUSES:
            raise ArchitectureManagementError(f"Desteklenmeyen aday durumu: {self.status}")
        if self.proposal.framework_profile_id != self.automatic_proposal.framework_profile_id:
            raise ArchitectureManagementError("Manuel ve otomatik aday profilleri uyuşmuyor.")
        self.manual_fields = tuple(sorted({_clean(item) for item in self.manual_fields if _clean(item)}))
        if any(item not in self.proposal.proposed_payload for item in self.manual_fields):
            raise ArchitectureManagementError("Manuel alan aday payload'ında bulunmuyor.")
        if self.manual_fields and self.proposal.proposal_origin != DERIVATION_USER_SUPPLIED:
            raise ArchitectureManagementError("Manuel alanlar user_supplied aday sürümü gerektirir.")
        if self.current_decision is not None and not isinstance(self.current_decision, ReviewDecision):
            self.current_decision = ReviewDecision.from_dict(self.current_decision)
        self.decision_history = tuple(
            item if isinstance(item, ReviewDecision) else ReviewDecision.from_dict(item)
            for item in self.decision_history
        )
        self.previous_proposal_ids = tuple(dict.fromkeys(
            _clean(item) for item in self.previous_proposal_ids if _clean(item)
        ))
        self.stale_requirement_ids = tuple(sorted({
            _clean(item).upper() for item in self.stale_requirement_ids if _clean(item)
        }))
        self.stale_reason = _clean(self.stale_reason)
        self.superseded_by = _clean(self.superseded_by)
        self.updated_at = _clean(self.updated_at)
        if self.status == STATUS_SUPERSEDED and not self.superseded_by:
            raise ArchitectureManagementError("Superseded aday yeni kayıt kimliği gerektirir.")
        if self.status != STATUS_SUPERSEDED and self.superseded_by:
            raise ArchitectureManagementError("superseded_by yalnız superseded durumda kullanılabilir.")
        if self.status == STATUS_APPROVED:
            if (
                self.current_decision is None
                or self.current_decision.decision != DECISION_ACCEPT
                or self.current_decision.candidate_id != self.proposal.proposal_id
                or self.current_decision.candidate_digest != proposal_digest(self.proposal)
            ):
                raise ArchitectureManagementError("Approved aday geçerli kullanıcı kabul kararı gerektirir.")
        elif self.status == STATUS_EDITED:
            if (
                self.current_decision is None
                or self.current_decision.decision != DECISION_EDIT
                or self.current_decision.candidate_id not in self.previous_proposal_ids
            ):
                raise ArchitectureManagementError(
                    "edited aday düzenleme öncesi adaya bağlı kullanıcı kararı gerektirir."
                )
        elif self.status == STATUS_REJECTED:
            if (
                self.current_decision is None
                or self.current_decision.decision != DECISION_REJECT
                or self.current_decision.candidate_id != self.proposal.proposal_id
                or self.current_decision.candidate_digest != proposal_digest(self.proposal)
            ):
                raise ArchitectureManagementError(
                    "rejected aday geçerli kullanıcı reddetme kararı gerektirir."
                )
        if self.status in {STATUS_CANDIDATE, STATUS_STALE, STATUS_SUPERSEDED}:
            # Bu durumlarda geçmiş karar tutulabilir; fakat current_decision
            # yayıma yetki veren güncel karar değildir.
            pass
        self.record_id = _clean(self.record_id) or _record_id_for(self.automatic_proposal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "status": self.status,
            "proposal": self.proposal.to_dict(),
            "automatic_proposal": self.automatic_proposal.to_dict(),
            "manual_fields": list(self.manual_fields),
            "current_decision": self.current_decision.to_dict() if self.current_decision else None,
            "decision_history": [item.to_dict() for item in self.decision_history],
            "previous_proposal_ids": list(self.previous_proposal_ids),
            "stale_requirement_ids": list(self.stale_requirement_ids),
            "stale_reason": self.stale_reason,
            "superseded_by": self.superseded_by,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ManagedCandidate":
        if not isinstance(raw, Mapping):
            raise ArchitectureManagementError("Yönetilen aday JSON nesnesi olmalıdır.")
        return cls(
            proposal=raw.get("proposal", {}),
            automatic_proposal=raw.get("automatic_proposal", raw.get("proposal", {})),
            status=raw.get("status", STATUS_CANDIDATE),
            manual_fields=tuple(raw.get("manual_fields", ())),
            current_decision=raw.get("current_decision"),
            decision_history=tuple(raw.get("decision_history", ())),
            previous_proposal_ids=tuple(raw.get("previous_proposal_ids", ())),
            stale_requirement_ids=tuple(raw.get("stale_requirement_ids", ())),
            stale_reason=raw.get("stale_reason", ""),
            superseded_by=raw.get("superseded_by", ""),
            updated_at=raw.get("updated_at", ""),
            record_id=raw.get("record_id", ""),
        )


@dataclass(slots=True)
class ArchitectureManagementState:
    project_name: str
    framework_profile_id: str
    records: dict[str, ManagedCandidate] = field(default_factory=dict)
    conflicts: list[ArchitectureConflict] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)
    known_requirement_ids: tuple[str, ...] = ()
    source_requirement_fingerprints: dict[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    project_id: str = ""

    def __post_init__(self) -> None:
        self.project_name = _clean(self.project_name)
        self.framework_profile_id = _clean(self.framework_profile_id)
        if not self.project_name or not self.framework_profile_id:
            raise ArchitectureManagementError("Proje adı ve çerçeve profili boş olamaz.")
        expected_project_id = project_identity(self.project_name)[0]
        supplied_project_id = _clean(self.project_id)
        if supplied_project_id and supplied_project_id != expected_project_id:
            raise ArchitectureManagementError("Yönetim durumu proje kimliği proje adıyla uyuşmuyor.")
        self.project_id = expected_project_id
        normalized_records: dict[str, ManagedCandidate] = {}
        for key, value in dict(self.records).items():
            record = value if isinstance(value, ManagedCandidate) else ManagedCandidate.from_dict(value)
            if record.record_id != _clean(str(key)):
                raise ArchitectureManagementError("Yönetilen aday sözlük anahtarı record_id ile uyuşmuyor.")
            if record.proposal.framework_profile_id != self.framework_profile_id:
                raise ArchitectureManagementError("Yönetilen aday proje profiliyle uyuşmuyor.")
            normalized_records[record.record_id] = record
        self.records = normalized_records
        self.conflicts = [
            item if isinstance(item, ArchitectureConflict) else ArchitectureConflict.from_dict(item)
            for item in self.conflicts
        ]
        self.audit_events = [
            item if isinstance(item, AuditEvent) else AuditEvent.from_dict(item)
            for item in self.audit_events
        ]
        if len({item.conflict_id for item in self.conflicts}) != len(self.conflicts):
            raise ArchitectureManagementError("Yinelenen conflict kimliği var.")
        if len({item.event_id for item in self.audit_events}) != len(self.audit_events):
            raise ArchitectureManagementError("Yinelenen audit olayı kimliği var.")
        self.known_requirement_ids = tuple(sorted({
            _clean(item).upper() for item in self.known_requirement_ids if _clean(item)
        }))
        normalized_fingerprints: dict[str, str] = {}
        if not isinstance(self.source_requirement_fingerprints, Mapping):
            raise ArchitectureManagementError("Kaynak parmak izleri JSON nesnesi olmalıdır.")
        for raw_id, raw_digest in self.source_requirement_fingerprints.items():
            requirement_id = _clean(str(raw_id)).upper()
            digest = _clean(raw_digest).lower()
            if not requirement_id or len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ArchitectureManagementError("Geçersiz kaynak gereksinim parmak izi.")
            normalized_fingerprints[requirement_id] = digest
        self.source_requirement_fingerprints = {
            key: normalized_fingerprints[key] for key in sorted(normalized_fingerprints)
        }
        self.schema_version = _clean(self.schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "framework_profile_id": self.framework_profile_id,
            "known_requirement_ids": list(self.known_requirement_ids),
            "source_requirement_fingerprints": dict(self.source_requirement_fingerprints),
            "records": {
                key: self.records[key].to_dict() for key in sorted(self.records)
            },
            "conflicts": [item.to_dict() for item in self.conflicts],
            "audit_events": [item.to_dict() for item in self.audit_events],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArchitectureManagementState":
        if not isinstance(raw, Mapping):
            raise ArchitectureManagementError("Yönetim durumu JSON nesnesi olmalıdır.")
        return cls(
            project_name=raw.get("project_name", ""),
            framework_profile_id=raw.get("framework_profile_id", ""),
            records=dict(raw.get("records", {})),
            conflicts=list(raw.get("conflicts", ())),
            audit_events=list(raw.get("audit_events", ())),
            known_requirement_ids=tuple(raw.get("known_requirement_ids", ())),
            source_requirement_fingerprints=dict(
                raw.get("source_requirement_fingerprints", {})
            ),
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            project_id=raw.get("project_id", ""),
        )


@dataclass(frozen=True, slots=True)
class PublicationResult:
    project_id: str
    version: str
    version_directory: str
    architecture_path: str
    latest_path: str
    change_summary_path: str
    audit_log_path: str


def create_management_state(
    project_name: str,
    candidates: Sequence[CandidateProposal],
    *,
    framework_profile_id: str | None = None,
    known_requirement_ids: Sequence[str] = (),
    source_requirement_fingerprints: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> ArchitectureManagementState:
    proposals = tuple(candidates)
    if not proposals and not framework_profile_id:
        raise ArchitectureManagementError("Boş aday kümesi için çerçeve profili açık verilmelidir.")
    profile_id = _clean(framework_profile_id) if framework_profile_id else proposals[0].framework_profile_id
    records: dict[str, ManagedCandidate] = {}
    timestamp = _timestamp(now)
    for proposal in proposals:
        if not isinstance(proposal, CandidateProposal):
            raise ArchitectureManagementError("Aday kümesi CandidateProposal içermelidir.")
        if proposal.framework_profile_id != profile_id:
            raise ArchitectureManagementError("Aday kümesinde birden fazla profil bulunamaz.")
        record = ManagedCandidate(
            proposal=proposal,
            automatic_proposal=proposal,
            updated_at=timestamp,
        )
        if record.record_id in records:
            raise ArchitectureManagementError("Aynı semantik aday yönetim kümesinde yinelenemez.")
        records[record.record_id] = record
    state = ArchitectureManagementState(
        project_name=project_name,
        framework_profile_id=profile_id,
        records=records,
        known_requirement_ids=tuple(known_requirement_ids),
        source_requirement_fingerprints=dict(source_requirement_fingerprints or {}),
    )
    _append_audit(
        state,
        "review_created",
        "system",
        timestamp,
        details={"candidate_count": len(records)},
    )
    return state


def _append_audit(
    state: ArchitectureManagementState,
    event_type: str,
    actor: str,
    occurred_at: str,
    *,
    record_id: str = "",
    details: Mapping[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        occurred_at=occurred_at,
        actor=actor,
        record_id=record_id,
        details=dict(details or {}),
    )
    if event.event_id not in {item.event_id for item in state.audit_events}:
        state.audit_events.append(event)
    return event


def _record(state: ArchitectureManagementState, record_id: str) -> ManagedCandidate:
    try:
        return state.records[_clean(record_id)]
    except KeyError as error:
        raise ArchitectureManagementError("Yönetilecek mimari aday bulunamadı.") from error


def _ensure_reviewable(record: ManagedCandidate) -> None:
    if record.status == STATUS_SUPERSEDED:
        raise ArchitectureManagementError("Superseded aday yeniden incelenemez.")
    if record.status == STATUS_STALE:
        raise ArchitectureManagementError(
            "Stale aday güncel kaynakla yeniden çıkarılmadan incelenemez."
        )


def approve_candidate(
    state: ArchitectureManagementState,
    record_id: str,
    actor: str,
    *,
    rationale: str = "",
    now: datetime | None = None,
) -> ManagedCandidate:
    record = _record(state, record_id)
    _ensure_reviewable(record)
    timestamp = _timestamp(now)
    decision = ReviewDecision.for_proposal(
        record.proposal,
        DECISION_ACCEPT,
        _clean(actor),
        timestamp,
        rationale=_clean(rationale),
    )
    record.status = STATUS_APPROVED
    record.current_decision = decision
    record.decision_history = (*record.decision_history, decision)
    record.stale_requirement_ids = ()
    record.stale_reason = ""
    record.updated_at = timestamp
    _append_audit(
        state, "candidate_approved", actor, timestamp, record_id=record.record_id,
        details={"proposal_id": record.proposal.proposal_id, "decision_id": decision.decision_id},
    )
    return record


def reject_candidate(
    state: ArchitectureManagementState,
    record_id: str,
    actor: str,
    *,
    rationale: str = "",
    now: datetime | None = None,
) -> ManagedCandidate:
    record = _record(state, record_id)
    _ensure_reviewable(record)
    timestamp = _timestamp(now)
    decision = ReviewDecision.for_proposal(
        record.proposal,
        DECISION_REJECT,
        _clean(actor),
        timestamp,
        rationale=_clean(rationale),
    )
    record.status = STATUS_REJECTED
    record.current_decision = decision
    record.decision_history = (*record.decision_history, decision)
    record.updated_at = timestamp
    _append_audit(
        state, "candidate_rejected", actor, timestamp, record_id=record.record_id,
        details={"proposal_id": record.proposal.proposal_id, "decision_id": decision.decision_id},
    )
    return record


def _build_edited_proposal(
    record: ManagedCandidate,
    edited_payload: Mapping[str, Any],
    actor: str,
    timestamp: str,
) -> CandidateProposal:
    if not isinstance(edited_payload, Mapping):
        raise ArchitectureManagementError("Düzenlenen payload JSON nesnesi olmalıdır.")
    expected = set(record.proposal.proposed_payload)
    if set(edited_payload) != expected:
        missing = sorted(expected - set(edited_payload))
        extra = sorted(set(edited_payload) - expected)
        parts = []
        if missing:
            parts.append("eksik=" + ", ".join(missing))
        if extra:
            parts.append("fazla=" + ", ".join(extra))
        raise ArchitectureManagementError("Düzenlenen payload alanları değiştirilemez: " + "; ".join(parts))
    payload = {key: _clean(value) for key, value in edited_payload.items()}
    evidence_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_item_id = f"USER-EDIT-{record.record_id}"
    source_document = "Mimari kullanıcı incelemesi"
    source_location = f"candidate/{record.record_id}/{timestamp}"
    user_evidence = EvidenceLink(
        source_item_id=source_item_id,
        source_document=source_document,
        source_location=source_location,
        evidence_text=evidence_text,
        evidence_fingerprint=evidence_fingerprint_for(
            source_document, source_item_id, source_location, evidence_text,
        ),
        confidence_score=1.0,
        derivation_kind=DERIVATION_USER_SUPPLIED,
        producer=PRODUCER,
        producer_version=PRODUCER_VERSION,
    )
    links = tuple({
        item.evidence_id: item
        for item in (*record.automatic_proposal.evidence_links, user_evidence)
    }.values())
    proposal_id = stable_id_for("ARCH-EDITED-PROPOSAL", {
        "record": record.record_id,
        "payload_digest": _json_digest(payload),
    })
    type_field = "element_type" if record.proposal.proposal_type == "element" else "relationship_type"
    try:
        return CandidateProposal(
            identity_key=payload["identity_key"],
            framework_profile_id=record.proposal.framework_profile_id,
            proposal_type=record.proposal.proposal_type,
            title=payload["name"],
            rationale=f"{actor} tarafından kullanıcı incelemesinde düzenlendi.",
            proposed_payload=payload,
            source_requirement_ids=record.automatic_proposal.source_requirement_ids,
            evidence_text=evidence_text,
            confidence_score=1.0,
            evidence_links=links,
            payload_evidence_ids={key: (user_evidence.evidence_id,) for key in payload},
            source_element_id=record.proposal.source_element_id,
            target_element_id=record.proposal.target_element_id,
            target_stable_id=record.proposal.target_stable_id,
            proposal_origin=DERIVATION_USER_SUPPLIED,
            version=record.proposal.version,
            proposal_id=proposal_id,
        )
    except ValueError as error:
        raise ArchitectureManagementError(str(error)) from error


def edit_candidate(
    state: ArchitectureManagementState,
    record_id: str,
    edited_payload: Mapping[str, Any],
    actor: str,
    *,
    rationale: str = "",
    now: datetime | None = None,
) -> ManagedCandidate:
    record = _record(state, record_id)
    _ensure_reviewable(record)
    timestamp = _timestamp(now)
    previous = record.proposal
    decision = ReviewDecision.for_proposal(
        previous,
        DECISION_EDIT,
        _clean(actor),
        timestamp,
        rationale=_clean(rationale),
    )
    edited = _build_edited_proposal(record, edited_payload, _clean(actor), timestamp)
    base_payload = _payload(record.automatic_proposal)
    manual_fields = tuple(sorted(
        key for key, value in _payload(edited).items() if value != base_payload.get(key)
    ))
    if not manual_fields:
        raise ArchitectureManagementError("Düzenleme otomatik adayla aynı; manuel değişiklik bulunamadı.")
    record.previous_proposal_ids = tuple(dict.fromkeys(
        (*record.previous_proposal_ids, previous.proposal_id)
    ))
    record.proposal = edited
    record.manual_fields = manual_fields
    record.status = STATUS_EDITED
    record.current_decision = decision
    record.decision_history = (*record.decision_history, decision)
    record.updated_at = timestamp
    _append_audit(
        state, "candidate_edited", actor, timestamp, record_id=record.record_id,
        details={
            "previous_proposal_id": previous.proposal_id,
            "proposal_id": edited.proposal_id,
            "manual_fields": list(manual_fields),
            "decision_id": decision.decision_id,
        },
    )
    return record


def mark_candidate_stale(
    state: ArchitectureManagementState,
    record_id: str,
    requirement_ids: Sequence[str],
    reason: str,
    *,
    actor: str = "system",
    now: datetime | None = None,
) -> ManagedCandidate:
    record = _record(state, record_id)
    if record.status == STATUS_SUPERSEDED:
        return record
    timestamp = _timestamp(now)
    normalized_ids = tuple(sorted({
        _clean(item).upper() for item in requirement_ids if _clean(item)
    }))
    record.status = STATUS_STALE
    record.current_decision = None
    record.stale_requirement_ids = normalized_ids
    record.stale_reason = _clean(reason)
    record.updated_at = timestamp
    _append_audit(
        state, "candidate_stale", actor, timestamp, record_id=record.record_id,
        details={"requirement_ids": list(normalized_ids), "reason": record.stale_reason},
    )
    return record


def supersede_candidate(
    state: ArchitectureManagementState,
    record_id: str,
    superseded_by: str,
    actor: str,
    *,
    now: datetime | None = None,
) -> ManagedCandidate:
    record = _record(state, record_id)
    replacement = _record(state, superseded_by)
    if record.record_id == replacement.record_id:
        raise ArchitectureManagementError("Aday kendisi tarafından superseded yapılamaz.")
    timestamp = _timestamp(now)
    record.status = STATUS_SUPERSEDED
    record.superseded_by = replacement.record_id
    record.updated_at = timestamp
    _append_audit(
        state, "candidate_superseded", actor, timestamp, record_id=record.record_id,
        details={"superseded_by": replacement.record_id},
    )
    return record


def _merge_unscanned_automatic_evidence(
    previous: CandidateProposal,
    incoming: CandidateProposal,
    scanned_requirement_ids: frozenset[str],
) -> CandidateProposal:
    """Kısmi taramada seçilmeyen kaynak bağlarını kaybetmeden yeni adayı kurar."""

    if not scanned_requirement_ids:
        return incoming
    retained_links = tuple(
        link for link in previous.evidence_links
        if link.source_item_id.upper() not in scanned_requirement_ids
    )
    if not retained_links:
        return incoming
    merged_links = tuple(sorted(
        {link.evidence_id: link for link in (
            *retained_links, *incoming.evidence_links,
        )}.values(),
        key=lambda link: (link.source_item_id, link.evidence_id),
    ))
    if len(merged_links) == len(incoming.evidence_links):
        return incoming
    raw = incoming.to_dict()
    raw["evidence_links"] = [link.to_dict() for link in merged_links]
    raw["source_requirement_ids"] = sorted({
        link.source_item_id.upper() for link in merged_links
    })
    raw["payload_evidence_ids"] = {
        key: [link.evidence_id for link in merged_links]
        for key in incoming.proposed_payload
    }
    return CandidateProposal.from_dict(raw)


def reconcile_candidates(
    state: ArchitectureManagementState,
    new_candidates: Sequence[CandidateProposal],
    *,
    changed_requirement_ids: Sequence[str] = (),
    scanned_requirement_ids: Sequence[str] = (),
    known_requirement_ids: Sequence[str] | None = None,
    source_fingerprints: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> ArchitectureManagementState:
    """Yeni otomatik taramayı manuel değerleri ezmeden yönetim durumuna uygular."""

    reconciliation_now = _now(now)
    timestamp = reconciliation_now.isoformat(timespec="seconds")
    changed_ids = set(
        _clean(item).upper() for item in changed_requirement_ids if _clean(item)
    )
    scanned_ids = frozenset(
        _clean(item).upper() for item in scanned_requirement_ids if _clean(item)
    )
    previous_known_ids = frozenset(state.known_requirement_ids)
    current_known_ids = (
        frozenset(
            _clean(item).upper() for item in known_requirement_ids if _clean(item)
        )
        if known_requirement_ids is not None
        else previous_known_ids
    )
    removed_ids = previous_known_ids - current_known_ids
    previous_fingerprints = dict(state.source_requirement_fingerprints)
    if source_fingerprints is None:
        current_fingerprints = previous_fingerprints
        fingerprint_changed_ids: set[str] = set()
    else:
        normalized_fingerprint_state = ArchitectureManagementState(
            project_name=state.project_name,
            framework_profile_id=state.framework_profile_id,
            source_requirement_fingerprints=dict(source_fingerprints),
        )
        current_fingerprints = dict(
            normalized_fingerprint_state.source_requirement_fingerprints
        )
        if previous_fingerprints:
            fingerprint_changed_ids = {
                item
                for item in set(previous_fingerprints) | set(current_fingerprints)
                if previous_fingerprints.get(item) != current_fingerprints.get(item)
            }
        elif previous_known_ids:
            # Eski 1.0 review_state dosyalarında digest yoktur. İlk geçişte
            # eski onayı sessizce güncel saymak yerine kanıt kapsamını stale yap.
            fingerprint_changed_ids = set(previous_known_ids) | set(current_fingerprints)
        else:
            fingerprint_changed_ids = set()
        changed_ids.update(fingerprint_changed_ids)
    changed_ids = frozenset(changed_ids)

    # Kaynağı değişen onayı incoming aday uygulanmadan önce geçersizleştir.
    # Böylece aynı taramada gerçekten yenilenen aday yeniden reviewable olabilir;
    # tarama kapsamı dışında kalan kayıt ise stale kalır.
    stale_before_refresh: set[str] = set()
    for record in state.records.values():
        affected = _source_ids(record.automatic_proposal) & set(changed_ids)
        if affected and record.status != STATUS_SUPERSEDED:
            mark_candidate_stale(
                state,
                record.record_id,
                tuple(sorted(affected)),
                "Kaynak gereksinim parmak izi değişti; aday güncel kanıtla yeniden çıkarılmalı.",
                now=reconciliation_now,
            )
            stale_before_refresh.add(record.record_id)
    incoming: dict[str, CandidateProposal] = {}
    for proposal in new_candidates:
        if not isinstance(proposal, CandidateProposal):
            raise ArchitectureManagementError("Yeni tarama CandidateProposal içermelidir.")
        if proposal.framework_profile_id != state.framework_profile_id:
            raise ArchitectureManagementError("Yeni aday profili yönetim durumuyla uyuşmuyor.")
        record_id = _record_id_for(proposal)
        if record_id in incoming:
            raise ArchitectureManagementError("Yeni taramada yinelenen semantik aday var.")
        incoming[record_id] = proposal

    existing_conflict_ids = {item.conflict_id for item in state.conflicts}
    for record_id, proposal in incoming.items():
        record = state.records.get(record_id)
        if record is None:
            state.records[record_id] = ManagedCandidate(
                proposal=proposal,
                automatic_proposal=proposal,
                updated_at=timestamp,
            )
            _append_audit(
                state, "candidate_discovered", "system", timestamp, record_id=record_id,
                details={"proposal_id": proposal.proposal_id},
            )
            continue
        if record.status == STATUS_SUPERSEDED:
            continue
        was_stale = record.status == STATUS_STALE
        stale_ids_before_refresh = frozenset(record.stale_requirement_ids)
        proposal = _merge_unscanned_automatic_evidence(
            record.automatic_proposal, proposal, scanned_ids,
        )
        previous_auto = record.automatic_proposal
        previous_auto_payload = _payload(previous_auto)
        new_auto_payload = _payload(proposal)
        effective_payload = _payload(record.proposal)
        signature_changed = _source_signature(previous_auto) != _source_signature(proposal)
        payload_changed = previous_auto_payload != new_auto_payload
        affected_ids = set(_source_ids(previous_auto) | _source_ids(proposal)) & set(changed_ids)
        if signature_changed and not affected_ids:
            previous_signature = dict(_source_signature(previous_auto))
            current_signature = dict(_source_signature(proposal))
            affected_ids.update(
                item for item in set(previous_signature) | set(current_signature)
                if previous_signature.get(item) != current_signature.get(item)
            )

        for field_name in record.manual_fields:
            previous_value = previous_auto_payload.get(field_name, "")
            new_value = new_auto_payload.get(field_name, "")
            manual_value = effective_payload.get(field_name, "")
            if new_value != previous_value and new_value != manual_value:
                conflict = ArchitectureConflict(
                    record_id=record.record_id,
                    field_name=field_name,
                    manual_value=manual_value,
                    previous_automatic_value=previous_value,
                    new_automatic_value=new_value,
                    source_requirement_ids=tuple(sorted(_source_ids(proposal))),
                    created_at=timestamp,
                )
                if conflict.conflict_id not in existing_conflict_ids:
                    for previous_conflict in state.conflicts:
                        if (
                            previous_conflict.record_id == record.record_id
                            and previous_conflict.field_name == field_name
                            and previous_conflict.resolution == CONFLICT_UNRESOLVED
                        ):
                            previous_conflict.resolution = CONFLICT_SUPERSEDED
                            previous_conflict.resolved_at = timestamp
                            previous_conflict.resolved_by = "system"
                            _append_audit(
                                state,
                                "conflict_superseded",
                                "system",
                                timestamp,
                                record_id=record.record_id,
                                details={
                                    "conflict_id": previous_conflict.conflict_id,
                                    "superseded_by": conflict.conflict_id,
                                    "field_name": field_name,
                                },
                            )
                    state.conflicts.append(conflict)
                    existing_conflict_ids.add(conflict.conflict_id)
                    _append_audit(
                        state, "manual_automatic_conflict", "system", timestamp,
                        record_id=record.record_id,
                        details={"conflict_id": conflict.conflict_id, "field_name": field_name},
                    )

        record.automatic_proposal = proposal
        if record.manual_fields:
            # Manuel payload aynen korunur; fakat kaynak bağları yeni taramanın
            # parmak izleriyle yenilenir. Böylece stale kayıt yeniden
            # onaylandığında eski kaynak kanıtıyla yayımlanamaz.
            record.proposal = _build_edited_proposal(
                record,
                effective_payload,
                "Korunan kullanıcı düzenlemesi",
                timestamp,
            )
        else:
            record.proposal = proposal
        record.updated_at = timestamp
        unresolved_for_record = any(
            conflict.record_id == record.record_id
            and conflict.resolution == CONFLICT_UNRESOLVED
            for conflict in state.conflicts
        )
        stale_evidence_refreshed = bool(
            was_stale
            and stale_ids_before_refresh
            and stale_ids_before_refresh <= scanned_ids
        )
        if (
            (record_id in stale_before_refresh or stale_evidence_refreshed)
            and not unresolved_for_record
        ):
            record.status = STATUS_EDITED if record.manual_fields else STATUS_CANDIDATE
            record.stale_requirement_ids = ()
            record.stale_reason = ""
            record.current_decision = None
        elif (affected_ids or signature_changed or payload_changed) and record.status in {
            STATUS_APPROVED, STATUS_EDITED, STATUS_REJECTED,
        }:
            mark_candidate_stale(
                state,
                record.record_id,
                tuple(sorted(affected_ids or _source_ids(proposal))),
                "Kaynak gereksinim veya otomatik aday içeriği değişti; önceki kullanıcı kararı yeniden incelenmeli.",
                now=reconciliation_now,
            )

    for record_id, record in tuple(state.records.items()):
        if record_id in incoming or record.status == STATUS_SUPERSEDED:
            continue
        affected = _source_ids(record.automatic_proposal) & (
            changed_ids | scanned_ids | removed_ids
        )
        if affected:
            mark_candidate_stale(
                state,
                record_id,
                tuple(sorted(affected)),
                "Kaynak değişikliği sonrasında aday yeni taramada bulunamadı.",
                now=reconciliation_now,
            )
    if known_requirement_ids is not None:
        state.known_requirement_ids = tuple(sorted(current_known_ids))
    if source_fingerprints is not None:
        state.source_requirement_fingerprints = current_fingerprints
    _append_audit(
        state,
        "automatic_rescan_reconciled",
        "system",
        timestamp,
        details={
            "incoming_candidate_count": len(incoming),
            "changed_requirement_ids": sorted(changed_ids),
            "scanned_requirement_ids": sorted(scanned_ids),
            "removed_requirement_ids": sorted(removed_ids),
            "fingerprint_changed_requirement_ids": sorted(fingerprint_changed_ids),
        },
    )
    return state


def resolve_conflict(
    state: ArchitectureManagementState,
    conflict_id: str,
    resolution: str,
    actor: str,
    *,
    now: datetime | None = None,
) -> ArchitectureConflict:
    conflict = next(
        (item for item in state.conflicts if item.conflict_id == _clean(conflict_id)), None
    )
    if conflict is None:
        raise ArchitectureManagementError("Çözülecek conflict bulunamadı.")
    if conflict.resolution != CONFLICT_UNRESOLVED:
        raise ArchitectureManagementError("Conflict daha önce çözülmüş.")
    if resolution not in {CONFLICT_KEEP_MANUAL, CONFLICT_USE_AUTOMATIC}:
        raise ArchitectureManagementError("Geçersiz conflict çözümü.")
    timestamp = _timestamp(now)
    record = _record(state, conflict.record_id)
    resolution_actor = _clean(actor)
    if not resolution_actor:
        raise ArchitectureManagementError("Conflict çözüm aktörü boş olamaz.")
    current_automatic_value = _payload(record.automatic_proposal).get(
        conflict.field_name, ""
    )
    if current_automatic_value != conflict.new_automatic_value:
        # Eski bir conflict'in USE_AUTOMATIC kararı, daha yeni otomatik
        # çıkarımı ara bir değerle ezemez. KEEP_MANUAL da kullanıcıya
        # artık güncel olmayan bir karşılaştırma sunacağı için aynı
        # kayıt güvenli biçimde superseded yapılır.
        conflict.resolution = CONFLICT_SUPERSEDED
        conflict.resolved_at = timestamp
        conflict.resolved_by = "system"
        record.updated_at = timestamp
        _append_audit(
            state,
            "conflict_superseded",
            "system",
            timestamp,
            record_id=record.record_id,
            details={
                "conflict_id": conflict.conflict_id,
                "field_name": conflict.field_name,
                "reason": "automatic_value_changed",
            },
        )
        return conflict
    if resolution == CONFLICT_USE_AUTOMATIC:
        merged = _payload(record.proposal)
        merged[conflict.field_name] = conflict.new_automatic_value
        remaining_manual = tuple(
            item for item in record.manual_fields if item != conflict.field_name
        )
        if remaining_manual:
            record.proposal = _build_edited_proposal(record, merged, _clean(actor), timestamp)
        else:
            record.proposal = record.automatic_proposal
        record.manual_fields = remaining_manual
        if record.status == STATUS_APPROVED:
            record.status = STATUS_STALE
            record.stale_requirement_ids = conflict.source_requirement_ids
            record.stale_reason = (
                "Conflict çözümünde otomatik değer seçildi; değişen içerik yeniden onaylanmalı."
            )
    conflict.resolution = resolution
    conflict.resolved_at = timestamp
    conflict.resolved_by = resolution_actor
    unresolved_for_record = any(
        item.record_id == record.record_id
        and item.resolution == CONFLICT_UNRESOLVED
        for item in state.conflicts
    )
    if record.status == STATUS_STALE and not unresolved_for_record:
        # Kaynakla uzlaştırılmış içerik yeniden açık kullanıcı kararı
        # bekler; eski kabul kararı kendiliğinden canlandırılmaz.
        record.status = STATUS_EDITED if record.manual_fields else STATUS_CANDIDATE
        record.current_decision = None
        record.stale_requirement_ids = ()
        record.stale_reason = ""
    record.updated_at = timestamp
    _append_audit(
        state, "conflict_resolved", actor, timestamp, record_id=record.record_id,
        details={"conflict_id": conflict.conflict_id, "resolution": resolution},
    )
    return conflict


def _architecture_root(
    project_name: str,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    root = Path(output_root) if output_root is not None else DEFAULT_OUTPUT_ROOT
    return root / project_identity(project_name)[0] / "architecture"


def review_state_path(
    project_name: str,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    return _architecture_root(project_name, output_root) / "review_state.json"


def profile_review_state_path(
    project_name: str,
    framework_profile_id: str,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    """İki profilin kullanıcı kararlarını birbirini ezmeden ayıran ek yol."""

    try:
        profile = get_framework_profile(_clean(framework_profile_id))
    except KeyError as error:
        raise ArchitectureManagementError(str(error)) from error
    return _architecture_root(project_name, output_root) / f"review_state.{profile.profile_id}.json"


def save_management_state(
    state: ArchitectureManagementState,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    path = review_state_path(state.project_name, output_root)
    atomic_write_json(path, state.to_dict())
    return path


def save_profile_management_state(
    state: ArchitectureManagementState,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Profil-kapsamlı inceleme durumunu atomik kaydeder."""

    path = profile_review_state_path(
        state.project_name, state.framework_profile_id, output_root,
    )
    atomic_write_json(path, state.to_dict())
    return path


def load_management_state(
    project_name: str,
    output_root: str | os.PathLike[str] | None = None,
) -> ArchitectureManagementState | None:
    path = review_state_path(project_name, output_root)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchitectureManagementError(f"Mimari inceleme durumu okunamadı: {error}") from error
    state = ArchitectureManagementState.from_dict(raw)
    expected_project_id = project_identity(project_name)[0]
    if state.project_id != expected_project_id:
        raise ArchitectureManagementError("Mimari inceleme durumu proje kimliğiyle uyuşmuyor.")
    return state


def load_profile_management_state(
    project_name: str,
    framework_profile_id: str,
    output_root: str | os.PathLike[str] | None = None,
) -> ArchitectureManagementState | None:
    """Profil dosyasını, yoksa aynı profildeki eski tekil zarfı salt-okur."""

    profile = get_framework_profile(_clean(framework_profile_id))
    path = profile_review_state_path(project_name, profile.profile_id, output_root)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ArchitectureManagementError(
                f"Profil mimari inceleme durumu okunamadı: {error}"
            ) from error
        state = ArchitectureManagementState.from_dict(raw)
        if state.framework_profile_id != profile.profile_id:
            raise ArchitectureManagementError(
                "Profil inceleme dosyası beklenen çerçeve profiliyle uyuşmuyor."
            )
        if state.project_id != project_identity(project_name)[0]:
            raise ArchitectureManagementError(
                "Profil mimari inceleme durumu proje kimliğiyle uyuşmuyor."
            )
        return state
    legacy = load_management_state(project_name, output_root)
    if legacy is None or legacy.framework_profile_id != profile.profile_id:
        return None
    return legacy


def _materialize(record: ManagedCandidate) -> ArchitectureElement | ArchitectureRelationship:
    proposal = record.proposal
    decision = record.current_decision
    if record.status != STATUS_APPROVED or decision is None:
        raise ArchitectureManagementError("Yalnız approved aday kanonik mimariye alınabilir.")
    if (
        decision.actor_type != ACTOR_USER
        or decision.decision != DECISION_ACCEPT
        or decision.candidate_id != proposal.proposal_id
        or decision.candidate_digest != proposal_digest(proposal)
    ):
        raise ArchitectureManagementError("Approved aday kararı güncel aday digest'iyle uyuşmuyor.")
    payload = _payload(proposal)
    common = {
        "identity_key": payload["identity_key"],
        "framework_profile_id": proposal.framework_profile_id,
        "name": payload["name"],
        "description": payload["description"],
        "source_requirement_ids": proposal.source_requirement_ids,
        "evidence_text": proposal.evidence_text,
        "confidence_score": proposal.confidence_score,
        "evidence_links": proposal.evidence_links,
        "review_status": REVIEW_APPROVED,
        "version": proposal.version,
        "derivation_kind": proposal.proposal_origin,
        "source_proposal_id": proposal.proposal_id,
        "approval_decision_id": decision.decision_id,
    }
    try:
        if proposal.proposal_type == "element":
            return ArchitectureElement(
                element_type=payload["element_type"],
                **common,
            )
        return ArchitectureRelationship(
            relationship_type=payload["relationship_type"],
            source_element_id=proposal.source_element_id,
            target_element_id=proposal.target_element_id,
            **common,
        )
    except ValueError as error:
        raise ArchitectureManagementError(str(error)) from error


def build_working_snapshot(
    state: ArchitectureManagementState,
    selected_view_ids: Sequence[str],
    *,
    version: str = "v0001",
    now: datetime | None = None,
) -> ArchitectureSnapshot:
    """Onaylı çalışma durumunu dosya yazmadan ``ArchitectureSnapshot`` yapar.

    Yalnız güncel açık kullanıcı kabul kararına sahip ``approved`` kayıtlar
    kanonikleştirilir. Onaysız adaylar snapshot'a sızmaz; approved kayıtlarla
    ilgili çözülmemiş conflict veya approved olmayan bir öğeye uzanan ilişki
    çalışma görünümünün üretilmesini engeller. Snapshot bir doğrulama sonucu
    iddia etmediği için her zaman ``Taslak`` durumundadır.

    ``candidate_proposals`` ve ``review_decisions`` alanları tam audit geçmişi
    değil, her kanonik kaydın etkin aday -> kullanıcı kabul kararı zinciridir.
    Tam geçmiş ``ArchitectureManagementState`` içinde korunmaya devam eder.
    """

    if not isinstance(state, ArchitectureManagementState):
        raise ArchitectureManagementError(
            "Çalışma snapshot'ı ArchitectureManagementState gerektirir."
        )
    if isinstance(selected_view_ids, (str, bytes)):
        raise ArchitectureManagementError(
            "Seçili görünüm kimlikleri tek string değil bir dizi olmalıdır."
        )
    try:
        requested_view_ids = tuple(selected_view_ids)
    except TypeError as error:
        raise ArchitectureManagementError(
            "Seçili görünüm kimlikleri yinelenebilir bir dizi olmalıdır."
        ) from error

    try:
        profile = get_framework_profile(state.framework_profile_id)
    except KeyError as error:
        raise ArchitectureManagementError(str(error)) from error

    canonical_view_ids: list[str] = []
    seen_view_ids: set[str] = set()
    for raw_view_id in requested_view_ids:
        view_id = _clean(raw_view_id)
        if not view_id:
            raise ArchitectureManagementError("Seçili görünüm kimliği boş olamaz.")
        try:
            view = profile.get_view(view_id)
        except KeyError as error:
            raise ArchitectureManagementError(str(error)) from error
        key = view.view_id.casefold()
        if key not in seen_view_ids:
            canonical_view_ids.append(view.view_id)
            seen_view_ids.add(key)

    approved = sorted(
        (
            record
            for record in state.records.values()
            if record.status == STATUS_APPROVED
        ),
        key=lambda record: record.record_id,
    )
    if not approved:
        raise ArchitectureManagementError(
            "Çalışma snapshot'ına alınacak approved mimari adayı bulunamadı."
        )

    approved_record_ids = {record.record_id for record in approved}
    unresolved = sorted(
        (
            conflict
            for conflict in state.conflicts
            if conflict.resolution == CONFLICT_UNRESOLVED
            and conflict.record_id in approved_record_ids
        ),
        key=lambda conflict: conflict.conflict_id,
    )
    if unresolved:
        raise ArchitectureManagementError(
            "Approved adaylarda çözülmemiş conflict bulunuyor: "
            + ", ".join(conflict.conflict_id for conflict in unresolved)
        )

    materialized = [_materialize(record) for record in approved]
    elements = tuple(sorted(
        (
            item
            for item in materialized
            if isinstance(item, ArchitectureElement)
        ),
        key=lambda item: item.stable_id,
    ))
    relationships = tuple(sorted(
        (
            item
            for item in materialized
            if isinstance(item, ArchitectureRelationship)
        ),
        key=lambda item: item.stable_id,
    ))
    element_ids = {item.stable_id for item in elements}
    dangling: list[str] = []
    for relationship in relationships:
        missing = sorted({
            endpoint
            for endpoint in (
                relationship.source_element_id,
                relationship.target_element_id,
            )
            if endpoint not in element_ids
        })
        if missing:
            dangling.append(
                f"{relationship.stable_id} -> {', '.join(missing)}"
            )
    if dangling:
        raise ArchitectureManagementError(
            "Approved mimari ilişkide snapshot'ta olmayan öğe ucu var: "
            + "; ".join(dangling)
        )

    proposals = tuple(sorted(
        (record.proposal for record in approved),
        key=lambda proposal: proposal.proposal_id,
    ))
    decisions = tuple(sorted(
        (
            record.current_decision
            for record in approved
            if record.current_decision is not None
        ),
        key=lambda decision: decision.decision_id,
    ))

    try:
        return ArchitectureSnapshot(
            identity_key=f"{state.project_id}:working-architecture",
            project_id=state.project_id,
            name=f"{state.project_name} Mimari Çalışma Snapshot'ı",
            framework_profile_id=state.framework_profile_id,
            framework_version=profile.version,
            version=version,
            status=SNAPSHOT_DRAFT,
            created_at=_timestamp(now),
            elements=elements,
            relationships=relationships,
            candidate_proposals=proposals,
            review_decisions=decisions,
            selected_view_ids=tuple(canonical_view_ids),
        )
    except ValueError as error:
        raise ArchitectureManagementError(str(error)) from error


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchitectureManagementError(f"{label} okunamadı: {error}") from error
    if not isinstance(raw, dict):
        raise ArchitectureManagementError(f"{label} JSON nesnesi olmalıdır.")
    return raw


def _load_previous_architecture(
    architecture_root: Path,
    expected_project_id: str | None = None,
) -> tuple[int, dict[str, Any] | None]:
    latest_path = architecture_root / "latest.json"
    if not latest_path.exists():
        return 0, None
    latest = _read_json(latest_path, "latest.json")
    if expected_project_id is not None and latest.get("project_id") != expected_project_id:
        raise ArchitectureManagementError("latest.json proje kimliğiyle uyuşmuyor.")
    version = latest.get("version_number")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ArchitectureManagementError("latest.json geçerli version_number içermiyor.")
    relative = _clean(latest.get("architecture_path"))
    candidate = (architecture_root / relative).resolve()
    root_resolved = architecture_root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as error:
        raise ArchitectureManagementError("latest.json proje dışına çıkan yol içeriyor.") from error
    if not candidate.is_file():
        raise ArchitectureManagementError("latest.json hedef architecture.json dosyası bulunamadı.")
    architecture = _read_json(candidate, "Önceki architecture.json")
    expected_version_name = f"v{version:04d}"
    if architecture.get("architecture_version") != expected_version_name:
        raise ArchitectureManagementError(
            "latest.json hedef mimari sürümüyle uyuşmuyor."
        )
    if expected_project_id is not None and architecture.get("project_id") != expected_project_id:
        raise ArchitectureManagementError(
            "latest.json hedef mimarisi proje kimliğiyle uyuşmuyor."
        )
    expected_digest = _clean(latest.get("content_digest"))
    if expected_digest and _json_digest(architecture) != expected_digest:
        raise ArchitectureManagementError(
            "latest.json hedef mimari içerik özetiyle uyuşmuyor."
        )
    return version, architecture


def _version_number_from_directory(path: Path) -> int | None:
    name = path.name
    if not path.is_dir() or not name.startswith("v") or not name[1:].isdigit():
        return None
    number = int(name[1:])
    if number < 1 or name != f"v{number:04d}":
        return None
    return number


def _read_recoverable_publication(
    version_directory: Path,
    expected_project_id: str,
) -> dict[str, Any] | None:
    """Return a fully verified finalization record, or ``None`` for ambiguity.

    Recovery deliberately has no best-effort path.  A directory without a
    COMMIT marker, a finalization journal, or matching content digests remains
    untouched and is never promoted to ``latest.json``.
    """

    version_number = _version_number_from_directory(version_directory)
    if version_number is None:
        return None
    version_name = f"v{version_number:04d}"
    required_paths = {
        "architecture": version_directory / "architecture.json",
        "summary": version_directory / "change_summary.json",
        "audit_event": version_directory / "audit_event.json",
        "journal": version_directory / "FINALIZATION.json",
        "commit": version_directory / "COMMIT.json",
    }
    if not all(path.is_file() for path in required_paths.values()):
        return None
    try:
        architecture = _read_json(required_paths["architecture"], "Recovery architecture.json")
        summary = _read_json(required_paths["summary"], "Recovery change_summary.json")
        audit_event = _read_json(required_paths["audit_event"], "Recovery audit_event.json")
        journal = _read_json(required_paths["journal"], "Recovery FINALIZATION.json")
        commit = _read_json(required_paths["commit"], "Recovery COMMIT.json")

        if commit.get("status") != "validated" or commit.get("version") != version_name:
            return None
        if architecture.get("project_id") != expected_project_id:
            return None
        if architecture.get("architecture_version") != version_name:
            return None
        if summary.get("new_version") != version_name:
            return None
        if _clean(commit.get("architecture_digest")) != _json_digest(architecture):
            return None
        if _clean(commit.get("change_summary_digest")) != _json_digest(summary):
            return None
        if _clean(commit.get("audit_event_digest")) != _json_digest(audit_event):
            return None
        if _clean(commit.get("finalization_digest")) != _json_digest(journal):
            return None

        if journal.get("project_id") != expected_project_id:
            return None
        if journal.get("version") != version_name:
            return None
        if journal.get("version_number") != version_number:
            return None
        latest = journal.get("latest")
        audit_events = journal.get("audit_events")
        if not isinstance(latest, Mapping) or not isinstance(audit_events, list):
            return None
        if latest.get("project_id") != expected_project_id:
            return None
        if latest.get("version") != version_name or latest.get("version_number") != version_number:
            return None
        if latest.get("architecture_path") != f"{version_name}/architecture.json":
            return None
        if latest.get("change_summary_path") != f"{version_name}/change_summary.json":
            return None
        if _clean(latest.get("content_digest")) != _json_digest(architecture):
            return None

        normalized_events: list[dict[str, Any]] = []
        event_ids: set[str] = set()
        for raw_event in audit_events:
            if not isinstance(raw_event, Mapping):
                return None
            event = AuditEvent.from_dict(raw_event).to_dict()
            event_id = event["event_id"]
            if event_id in event_ids or _json_digest(event) != _json_digest(dict(raw_event)):
                return None
            event_ids.add(event_id)
            normalized_events.append(event)
        if not any(_json_digest(item) == _json_digest(audit_event) for item in normalized_events):
            return None

        view_digests = commit.get("view_digests", {})
        if not isinstance(view_digests, Mapping):
            return None
        for raw_view_id, raw_digest in view_digests.items():
            view_id = _clean(raw_view_id)
            if (
                not view_id
                or any(
                    char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
                    for char in view_id
                )
            ):
                return None
            artifact = version_directory / "views" / f"{view_id}.svg"
            if not artifact.is_file():
                return None
            if _clean(raw_digest) != hashlib.sha256(artifact.read_bytes()).hexdigest():
                return None
    except (ArchitectureManagementError, OSError, TypeError, ValueError):
        return None

    return {
        "version_number": version_number,
        "version": version_name,
        "architecture": architecture,
        "summary": summary,
        "latest": dict(latest),
        "audit_events": normalized_events,
    }


def _merge_recovery_audit_events(
    architecture_root: Path,
    expected_project_id: str,
    recovery_records: Sequence[Mapping[str, Any]],
) -> None:
    if not recovery_records:
        return
    audit_path = architecture_root / "audit_log.json"
    if audit_path.exists():
        audit_payload = _read_json(audit_path, "Mimari audit log")
        if audit_payload.get("project_id") != expected_project_id:
            raise ArchitectureManagementError("Mimari audit log proje kimliğiyle uyuşmuyor.")
        if not isinstance(audit_payload.get("events"), list):
            raise ArchitectureManagementError("Mimari audit log events listesi içermelidir.")
    else:
        audit_payload = {
            "schema_version": SCHEMA_VERSION,
            "project_id": expected_project_id,
            "events": [],
        }

    known: dict[str, Mapping[str, Any]] = {}
    for raw_event in audit_payload["events"]:
        if not isinstance(raw_event, Mapping):
            raise ArchitectureManagementError("Mimari audit log geçersiz olay içeriyor.")
        event_id = _clean(raw_event.get("event_id"))
        if not event_id or event_id in known:
            raise ArchitectureManagementError("Mimari audit log belirsiz olay kimliği içeriyor.")
        known[event_id] = raw_event

    changed = False
    for record in recovery_records:
        for event in record["audit_events"]:
            event_id = event["event_id"]
            previous = known.get(event_id)
            if previous is not None:
                if _json_digest(previous) != _json_digest(event):
                    raise ArchitectureManagementError(
                        "Mimari audit log olay kimliği recovery kaydıyla çelişiyor."
                    )
                continue
            audit_payload["events"].append(deepcopy(event))
            known[event_id] = event
            changed = True
    if changed or not audit_path.exists():
        atomic_write_json(audit_path, audit_payload)


def _recover_committed_publications(
    architecture_root: Path,
    expected_project_id: str,
) -> None:
    """Idempotently finish only verified, contiguous committed versions."""

    latest_version, _ = _load_previous_architecture(
        architecture_root, expected_project_id,
    )
    directories: dict[int, Path] = {}
    if architecture_root.exists():
        for path in architecture_root.iterdir():
            version_number = _version_number_from_directory(path)
            if version_number is not None:
                directories[version_number] = path

    # Replaying journals for already-pointed versions repairs an audit write
    # that was interrupted independently of the latest pointer.
    recovery_records: list[dict[str, Any]] = []
    for version_number in sorted(number for number in directories if number <= latest_version):
        record = _read_recoverable_publication(
            directories[version_number], expected_project_id,
        )
        expected_previous = f"v{version_number - 1:04d}" if version_number > 1 else None
        if record is not None and record["summary"].get("previous_version") == expected_previous:
            recovery_records.append(record)

    recovered_latest: dict[str, Any] | None = None
    next_version = latest_version + 1
    while next_version in directories:
        record = _read_recoverable_publication(
            directories[next_version], expected_project_id,
        )
        expected_previous = f"v{next_version - 1:04d}" if next_version > 1 else None
        if record is None or record["summary"].get("previous_version") != expected_previous:
            break
        recovery_records.append(record)
        recovered_latest = record
        next_version += 1

    _merge_recovery_audit_events(
        architecture_root, expected_project_id, recovery_records,
    )
    if recovered_latest is not None:
        atomic_write_json(
            architecture_root / "latest.json", recovered_latest["latest"],
        )


def _change_summary(
    previous: Mapping[str, Any] | None,
    current_elements: Sequence[ArchitectureElement],
    current_relationships: Sequence[ArchitectureRelationship],
    *,
    previous_version: int,
    new_version: int,
    published_at: str,
    published_by: str,
    conflict_count: int,
) -> dict[str, Any]:
    previous_records = {
        item.get("stable_id"): item
        for key in ("elements", "relationships")
        for item in ((previous or {}).get(key, ()) or ())
        if isinstance(item, Mapping) and _clean(item.get("stable_id"))
    }
    current_records = {
        item.stable_id: item.to_dict()
        for item in (*current_elements, *current_relationships)
    }
    previous_ids = set(previous_records)
    current_ids = set(current_records)
    modified = sorted(
        item_id for item_id in previous_ids & current_ids
        if _json_digest(previous_records[item_id]) != _json_digest(current_records[item_id])
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "previous_version": f"v{previous_version:04d}" if previous_version else None,
        "new_version": f"v{new_version:04d}",
        "published_at": published_at,
        "published_by": published_by,
        "added_ids": sorted(current_ids - previous_ids),
        "modified_ids": modified,
        "removed_ids": sorted(previous_ids - current_ids),
        "counts": {
            "elements": len(current_elements),
            "relationships": len(current_relationships),
            "unresolved_conflicts": conflict_count,
        },
    }


def _restore_bytes(path: Path, content: bytes | None) -> None:
    if content is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.restore.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def publish_approved_architecture(
    state: ArchitectureManagementState,
    published_by: str,
    *,
    output_root: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
    writer: Callable[[str | os.PathLike[str], Mapping[str, Any]], None] = atomic_write_json,
    publication_context: Mapping[str, Any] | None = None,
    view_artifacts: Mapping[str, str] | None = None,
    precommit_guard: Callable[[], bool] | None = None,
) -> PublicationResult:
    """Approved mimariyi yeni ve atomik ``vNNNN`` sürümü olarak yayımlar."""

    actor = _clean(published_by)
    if not actor:
        raise ArchitectureManagementError("Yayımı yapan kullanıcı/rol boş olamaz.")
    if publication_context is not None and not isinstance(publication_context, Mapping):
        raise ArchitectureManagementError("Yayım bağlamı JSON nesnesi olmalıdır.")
    try:
        frozen_publication_context = json.loads(json.dumps(
            dict(publication_context or {}), ensure_ascii=False, sort_keys=True,
        ))
    except (TypeError, ValueError) as error:
        raise ArchitectureManagementError(f"Yayım bağlamı JSON uyumlu değil: {error}") from error
    if view_artifacts is not None and not isinstance(view_artifacts, Mapping):
        raise ArchitectureManagementError("Yayım görünüm artefaktları mapping olmalıdır.")
    frozen_view_artifacts: dict[str, str] = {}
    for raw_view_id, raw_svg in dict(view_artifacts or {}).items():
        view_id = _clean(raw_view_id)
        if (
            not view_id
            or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-" for char in view_id)
        ):
            raise ArchitectureManagementError("Görünüm artefakt kimliği güvenli değil.")
        if not isinstance(raw_svg, str) or "<svg" not in raw_svg[:500]:
            raise ArchitectureManagementError(f"{view_id} görünüm artefaktı geçerli SVG değil.")
        frozen_view_artifacts[view_id] = raw_svg
    rendered_manifest = frozen_publication_context.get("rendered_views", [])
    if frozen_view_artifacts:
        if not isinstance(rendered_manifest, list):
            raise ArchitectureManagementError("Yayım rendered_views manifesti liste olmalıdır.")
        manifest_by_view = {
            _clean(item.get("view_id")): item
            for item in rendered_manifest if isinstance(item, dict)
        }
        for view_id, svg in frozen_view_artifacts.items():
            manifest = manifest_by_view.get(view_id)
            if manifest is None:
                raise ArchitectureManagementError(
                    f"{view_id} SVG artefaktının yayım manifesti bulunamadı."
                )
            digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()
            expected = _clean(manifest.get("content_sha256"))
            if expected and expected != digest:
                raise ArchitectureManagementError(
                    f"{view_id} SVG özeti yayım manifestiyle uyuşmuyor."
                )
            manifest["content_sha256"] = digest
            manifest["artifact_path"] = f"views/{view_id}.svg"

    def ensure_commit_allowed() -> None:
        if precommit_guard is not None and not precommit_guard():
            raise ArchitectureManagementError("Mimari yayımı güncel olmayan işlem olarak iptal edildi.")

    with _LOCK:
        ensure_commit_allowed()
        architecture_root = _architecture_root(state.project_name, output_root)
        architecture_root.mkdir(parents=True, exist_ok=True)
        _recover_committed_publications(architecture_root, state.project_id)
        approved = [
            record for record in state.records.values()
            if record.status == STATUS_APPROVED
        ]
        if not approved:
            raise ArchitectureManagementError("Yayımlanacak approved mimari adayı bulunamadı.")
        approved_ids = {record.record_id for record in approved}
        unresolved = [
            item for item in state.conflicts
            if item.resolution == CONFLICT_UNRESOLVED and item.record_id in approved_ids
        ]
        if unresolved:
            raise ArchitectureManagementError("Approved adaylarda çözülmemiş conflict bulunuyor.")
        materialized = [_materialize(record) for record in approved]
        elements = sorted(
            (item for item in materialized if isinstance(item, ArchitectureElement)),
            key=lambda item: item.stable_id,
        )
        relationships = sorted(
            (item for item in materialized if isinstance(item, ArchitectureRelationship)),
            key=lambda item: item.stable_id,
        )
        element_ids = {item.stable_id for item in elements}
        for relationship in relationships:
            missing = [
                endpoint
                for endpoint in (relationship.source_element_id, relationship.target_element_id)
                if endpoint not in element_ids
            ]
            if missing:
                raise ArchitectureManagementError(
                    "Approved mimari ilişkide yayımlanmamış öğe ucu var: " + ", ".join(missing)
                )

        previous_version, previous_architecture = _load_previous_architecture(
            architecture_root, state.project_id,
        )
        new_version = previous_version + 1
        version_name = f"v{new_version:04d}"
        final_dir = architecture_root / version_name
        if final_dir.exists():
            raise ArchitectureManagementError(f"Hedef mimari sürüm klasörü zaten var: {version_name}")
        published_at = _timestamp(now)
        architecture_payload = {
            "schema_version": SCHEMA_VERSION,
            "project_id": state.project_id,
            "project_name": state.project_name,
            "framework_profile_id": state.framework_profile_id,
            "architecture_version": version_name,
            "published_at": published_at,
            "published_by": actor,
            "status": STATUS_APPROVED,
            "elements": [item.to_dict() for item in elements],
            "relationships": [item.to_dict() for item in relationships],
            "review_decisions": [
                record.current_decision.to_dict()
                for record in approved if record.current_decision is not None
            ],
            "source_record_ids": sorted(record.record_id for record in approved),
        }
        if frozen_publication_context:
            architecture_payload["publication_context"] = frozen_publication_context
        summary = _change_summary(
            previous_architecture,
            elements,
            relationships,
            previous_version=previous_version,
            new_version=new_version,
            published_at=published_at,
            published_by=actor,
            conflict_count=len(unresolved),
        )
        latest_payload = {
            "schema_version": SCHEMA_VERSION,
            "project_id": state.project_id,
            "version": version_name,
            "version_number": new_version,
            "architecture_path": f"{version_name}/architecture.json",
            "change_summary_path": f"{version_name}/change_summary.json",
            "content_digest": _json_digest(architecture_payload),
            "updated_at": published_at,
        }
        audit_path = architecture_root / "audit_log.json"
        latest_path = architecture_root / "latest.json"
        audit_payload = {
            "schema_version": SCHEMA_VERSION,
            "project_id": state.project_id,
            "events": [],
        }
        if audit_path.exists():
            audit_payload = _read_json(audit_path, "Mimari audit log")
            if audit_payload.get("project_id") != state.project_id:
                raise ArchitectureManagementError("Mimari audit log proje kimliğiyle uyuşmuyor.")
            if not isinstance(audit_payload.get("events"), list):
                raise ArchitectureManagementError("Mimari audit log events listesi içermelidir.")
        known_event_ids = {
            item.get("event_id") for item in audit_payload["events"] if isinstance(item, Mapping)
        }
        recovery_audit_events: list[dict[str, Any]] = []
        for event in state.audit_events:
            if event.event_id not in known_event_ids:
                event_payload = event.to_dict()
                audit_payload["events"].append(event_payload)
                recovery_audit_events.append(event_payload)
                known_event_ids.add(event.event_id)
        publish_event = AuditEvent(
            event_type="architecture_published",
            occurred_at=published_at,
            actor=actor,
            details={
                "version": version_name,
                "architecture_digest": latest_payload["content_digest"],
                "added_count": len(summary["added_ids"]),
                "modified_count": len(summary["modified_ids"]),
                "removed_count": len(summary["removed_ids"]),
            },
        )
        if publish_event.event_id not in known_event_ids:
            publish_event_payload = publish_event.to_dict()
            audit_payload["events"].append(publish_event_payload)
            recovery_audit_events.append(publish_event_payload)
        else:
            publish_event_payload = publish_event.to_dict()
            recovery_audit_events.append(publish_event_payload)

        finalization_payload = {
            "schema_version": SCHEMA_VERSION,
            "producer": PRODUCER,
            "producer_version": PRODUCER_VERSION,
            "project_id": state.project_id,
            "version": version_name,
            "version_number": new_version,
            "latest": latest_payload,
            "audit_events": recovery_audit_events,
        }

        stage = Path(tempfile.mkdtemp(prefix=f".{version_name}.", dir=architecture_root))
        previous_latest_bytes = latest_path.read_bytes() if latest_path.exists() else None
        previous_audit_bytes = audit_path.read_bytes() if audit_path.exists() else None
        final_committed = False
        try:
            writer(stage / "architecture.json", architecture_payload)
            writer(stage / "change_summary.json", summary)
            writer(stage / "audit_event.json", publish_event_payload)
            writer(stage / "FINALIZATION.json", finalization_payload)
            for view_id, svg in sorted(frozen_view_artifacts.items()):
                artifact_path = stage / "views" / f"{view_id}.svg"
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                with artifact_path.open("w", encoding="utf-8", newline="\n") as stream:
                    stream.write(svg)
                    stream.flush()
                    os.fsync(stream.fileno())
                actual_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                expected_digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()
                if actual_digest != expected_digest:
                    raise ArchitectureManagementError(
                        f"{view_id} SVG artefaktı geri okuma doğrulamasını geçemedi."
                    )
            writer(stage / "COMMIT.json", {
                "status": "validated",
                "version": version_name,
                "architecture_digest": latest_payload["content_digest"],
                "change_summary_digest": _json_digest(summary),
                "audit_event_digest": _json_digest(publish_event_payload),
                "finalization_digest": _json_digest(finalization_payload),
                "view_digests": {
                    view_id: hashlib.sha256(svg.encode("utf-8")).hexdigest()
                    for view_id, svg in sorted(frozen_view_artifacts.items())
                },
                "validated_at": published_at,
            })
            verified = _read_json(stage / "architecture.json", "Hazırlanan architecture.json")
            if _json_digest(verified) != latest_payload["content_digest"]:
                raise ArchitectureManagementError("Hazırlanan mimari geri okuma doğrulamasını geçemedi.")
            ensure_commit_allowed()
            os.replace(stage, final_dir)
            final_committed = True
            ensure_commit_allowed()
            writer(audit_path, audit_payload)
            ensure_commit_allowed()
            writer(latest_path, latest_payload)
            ensure_commit_allowed()
        except Exception as error:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            if final_committed and final_dir.exists():
                shutil.rmtree(final_dir, ignore_errors=True)
            _restore_bytes(audit_path, previous_audit_bytes)
            _restore_bytes(latest_path, previous_latest_bytes)
            if isinstance(error, ArchitectureManagementError):
                raise
            raise ArchitectureManagementError(f"Mimari sürüm atomik olarak yayımlanamadı: {error}") from error

        return PublicationResult(
            project_id=state.project_id,
            version=version_name,
            version_directory=str(final_dir.resolve()),
            architecture_path=str((final_dir / "architecture.json").resolve()),
            latest_path=str(latest_path.resolve()),
            change_summary_path=str((final_dir / "change_summary.json").resolve()),
            audit_log_path=str(audit_path.resolve()),
        )


def load_latest_architecture(
    project_name: str,
    output_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    architecture_root = _architecture_root(project_name, output_root)
    if not architecture_root.exists():
        return None
    expected_project_id = project_identity(project_name)[0]
    with _LOCK:
        _recover_committed_publications(architecture_root, expected_project_id)
        if not (architecture_root / "latest.json").exists():
            return None
        _, architecture = _load_previous_architecture(
            architecture_root, expected_project_id,
        )
        return architecture


__all__ = [
    "ArchitectureConflict", "ArchitectureManagementError", "ArchitectureManagementState",
    "AuditEvent", "CONFLICT_KEEP_MANUAL", "CONFLICT_SUPERSEDED",
    "CONFLICT_UNRESOLVED", "CONFLICT_USE_AUTOMATIC", "LIFECYCLE_STATUSES", "ManagedCandidate",
    "PublicationResult", "STATUS_APPROVED", "STATUS_CANDIDATE", "STATUS_EDITED",
    "STATUS_REJECTED", "STATUS_STALE", "STATUS_SUPERSEDED", "approve_candidate",
    "build_working_snapshot", "create_management_state", "edit_candidate", "load_latest_architecture",
    "load_management_state", "load_profile_management_state", "mark_candidate_stale",
    "profile_review_state_path", "publish_approved_architecture",
    "reconcile_candidates", "reject_candidate", "resolve_conflict", "review_state_path",
    "save_management_state", "save_profile_management_state", "source_requirement_fingerprints",
    "supersede_candidate",
]
