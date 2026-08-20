# -*- coding: utf-8 -*-
"""UI'dan bağımsız, kanıta bağlı çekirdek mimari veri modeli.

Bu modül DoDAF/NAF uyumluluğu iddia etmez. Kart 1 için yerel veri
sözleşmesini tanımlar:

* güven puanı sonlu bir ``0.0 .. 1.0`` değeridir,
* kimlikler ad/açıklama/sürümden değil semantik ``identity_key`` ve kimlik
  bağlamından SHA-256 ile deterministik olarak türetilir,
* otomatik mimari öğe ve ilişkiler geçerli kaynak kanıtı olmadan kurulamaz,
* model önerileri kanonik öğe değil, açık kullanıcı kararı bekleyen
  ``CandidateProposal`` kayıtlarıdır.

Sınıflar Tkinter, ``Arayüz.py`` veya başka bir UI modülüne bağlı değildir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping
import unicodedata


SCHEMA_VERSION = "1.0"

DERIVATION_DIRECT = "direct"
DERIVATION_DETERMINISTIC = "deterministic"
DERIVATION_MODEL_SUGGESTION = "model_suggestion"
DERIVATION_USER_SUPPLIED = "user_supplied"
DERIVATION_KINDS = frozenset({
    DERIVATION_DIRECT,
    DERIVATION_DETERMINISTIC,
    DERIVATION_MODEL_SUGGESTION,
    DERIVATION_USER_SUPPLIED,
})
AUTOMATIC_DERIVATION_KINDS = frozenset({
    DERIVATION_DIRECT, DERIVATION_DETERMINISTIC,
})

REVIEW_PENDING = "Onay bekliyor"
REVIEW_APPROVED = "Onaylandı"
REVIEW_REJECTED = "Reddedildi"
REVIEW_EDITED = "Düzenlendi"
REVIEW_DEFERRED = "Ertele"
REVIEW_STATUSES = frozenset({
    REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED,
    REVIEW_EDITED, REVIEW_DEFERRED,
})

DECISION_ACCEPT = "Kabul et"
DECISION_REJECT = "Reddet"
DECISION_EDIT = "Düzenle"
DECISION_DEFER = "Ertele"
REVIEW_DECISIONS = frozenset({
    DECISION_ACCEPT, DECISION_REJECT, DECISION_EDIT, DECISION_DEFER,
})
PROPOSAL_TYPES = frozenset({"element", "relationship"})
KNOWN_ELEMENT_TYPES = frozenset({
    "ArchitectureDescription", "ArchitectureMetadata", "AuthoritativeSource",
    "CapabilityConfiguration", "Definition", "DictionaryTerm", "FunctionalFlow",
    "LogicalActiveResource", "LogicalBehaviour", "LogicalConstraint", "LogicalEvent",
    "LogicalFunction", "LogicalInteraction", "LogicalPassiveResource", "LogicalRationale",
    "LogicalRequirement", "LogicalSpecification", "Measure", "Needline", "Node",
    "OperationalActivity", "OperationalControlFlow", "Organization", "PersonType",
    "PhysicalActiveResource", "PhysicalBehaviour", "PhysicalPassiveResource", "Port",
    "Protocol", "ResourceConstraint", "ResourceFlow", "ResourceFunction",
    "ResourceInteraction", "ResourceRationale", "ResourceRequirement",
    "ResourceSpecification", "Service", "ServiceFunction", "ServiceModelElement",
    "ServiceOrResource", "ServiceResourceFlow", "Standard", "SubService", "System",
    "SystemFunction", "SystemItem", "SystemModelElement", "SystemOrResource",
    "SystemResourceFlow", "Timeframe",
})
KNOWN_RELATIONSHIP_TYPES = frozenset({
    "aggregates", "allocated_to", "applies_to", "conforms_to", "connects", "contains",
    "control_flow_source", "control_flow_target", "conveys", "decomposes",
    "defined_by", "depends_on", "derived_from", "delivers", "flow_source",
    "flow_target", "implements", "interaction_source", "interaction_target", "maps_to",
    "measure_applies_to", "operational_flow", "originates_from", "parent_of", "part_of",
    "performed_by", "performs", "port_belongs_to", "realizes", "relates_to",
    "structurally_contains", "triggers", "uses", "valid_during",
})
ELEMENT_TYPE_HINTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "system": ("sistem", "system", "alt sistem", "birim", "ünite", "kontrol", "motor"),
    "systemfunction": ("fonksiyon", "işlev", "function", "gerçekleştir"),
    "service": ("servis", "hizmet", "service", "kullanıcı girdisi"),
    "servicefunction": ("servis fonksiyonu", "hizmet işlevi", "service function", "kullanıcı girdisi"),
    "operationalactivity": ("faaliyet", "aktivite", "activity"),
    "resourcefunction": ("kaynak fonksiyonu", "kaynak işlevi", "resource function"),
    "node": ("düğüm", "node", "birim", "sistem"),
    "role": ("rol", "role"),
    "port": ("port", "arayüz", "interface"),
    "protocol": ("protokol", "protocol"),
    "standard": ("standart", "standard"),
    "measure": ("ölçüt", "ölçüm", "measure"),
    "timeframe": ("zaman", "dönem", "timeframe"),
})
RELATIONSHIP_TYPE_HINTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "connects": ("bağlan", "bağlantı", "connect", "arasında", "taşın"),
    "performedby": ("gerçekleştir", "yürüt", "perform"),
    "allocatedto": ("tahsis", "allocate"),
    "mapsto": ("eşle", "izlenebilir", "map", "aynı", "bağlı"),
    "realizes": ("gerçekleştir", "realize"),
    "flowsource": ("kaynak", "akış", "source"),
    "flowtarget": ("hedef", "akış", "target"),
    "interactionsource": ("kaynak", "etkileşim", "source"),
    "interactiontarget": ("hedef", "etkileşim", "target"),
    "conformsto": ("uygun", "uyum", "conform"),
    "implements": ("uygula", "implement"),
    "contain": ("içer", "contain"),
    "partof": ("parça", "bileşen", "part"),
    "dependson": ("bağımlı", "depend"),
    "uses": ("kullan", "use"),
    "delivers": ("teslim", "sağla", "deliver"),
})

ACTOR_USER = "user"
ACTOR_MODEL = "model"
ACTOR_RULE = "rule"
ACTOR_IMPORTER = "importer"
ACTOR_TYPES = frozenset({ACTOR_USER, ACTOR_MODEL, ACTOR_RULE, ACTOR_IMPORTER})

SNAPSHOT_DRAFT = "Taslak"
SNAPSHOT_ALIGNED = "Çerçeveyle hizalı"
SNAPSHOT_CONFORMANT = "Uyumlu"
SNAPSHOT_STATUSES = frozenset({
    SNAPSHOT_DRAFT, SNAPSHOT_ALIGNED, SNAPSHOT_CONFORMANT,
})

# ``info`` eski kayıtlar için korunur. KART 4 motoru, kullanıcıya
# gösterilen yeni ve açık seviye adı olan ``information`` değerini kullanır.
FINDING_SEVERITIES = frozenset({"info", "information", "warning", "error"})
EXPORT_TYPES = frozenset({"structured_text", "dictionary", "diagram", "matrix", "table"})
GENERATION_CLASSES = frozenset({"A", "B", "C"})
_ARTIFACT_VERSION_PATTERN = re.compile(r"^v\d{4}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Metin alanı string olmalıdır.")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _required_text(value: Any, label: str) -> str:
    try:
        text = _clean(value)
    except ValueError as error:
        raise ValueError(f"{label} string olmalıdır.") from error
    if not text:
        raise ValueError(f"{label} boş olamaz.")
    return text


def _artifact_version(value: Any, label: str) -> str:
    version = _required_text(value, label)
    if not _ARTIFACT_VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"{label} vNNNN biçiminde olmalıdır.")
    return version


def _timezone_timestamp(value: Any, label: str) -> str:
    timestamp = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} ISO-8601 biçiminde olmalıdır.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} saat dilimi içermelidir.")
    return timestamp


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Güven puanı 0.0 ile 1.0 arasında sayısal bir değer olmalıdır.")
    result = float(value)
    if not math.isfinite(result) or result < 0.0 or result > 1.0:
        raise ValueError("Güven puanı 0.0 ile 1.0 arasında ve sonlu olmalıdır.")
    return result


def _text_tuple(values: Any, *, upper: bool = False) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ValueError("Metin koleksiyonu liste veya tuple olmalıdır.")
    found: dict[str, str] = {}
    for value in values:
        text = _clean(value)
        if not text:
            continue
        text = text.upper() if upper else text
        found.setdefault(text.casefold(), text)
    return tuple(sorted(found.values(), key=lambda item: item.casefold()))


def _canonical_identity(value: Any) -> Any:
    """Kimlik girdisini sözlük/liste sırasından bağımsız hâle getirir."""
    if isinstance(value, Mapping):
        canonical: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Kimlik sözlüğü anahtarları string olmalıdır.")
            clean_key = _required_text(key, "Kimlik sözlüğü anahtarı").casefold()
            if clean_key in canonical:
                raise ValueError("Normalize edilmiş kimlik sözlüğü anahtarları çakışıyor.")
            canonical[clean_key] = _canonical_identity(item)
        return {key: canonical[key] for key in sorted(canonical)}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_canonical_identity(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ),
        )
    if isinstance(value, str):
        return _clean(value).casefold()
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Kimlik girdisi sonlu olmayan sayı içeremez.")
        return value
    raise ValueError(f"Desteklenmeyen kimlik girdisi türü: {type(value).__name__}")


def stable_id_for(namespace: str, identity_key: Any) -> str:
    """Aynı semantik anahtar için süreçlerden bağımsız kararlı kimlik üretir."""
    clean_namespace = _required_text(namespace, "Kimlik ad alanı")
    canonical = _canonical_identity(identity_key)
    if canonical in (None, "", [], {}):
        raise ValueError("Kararlı kimlik için identity_key boş olamaz.")
    encoded = json.dumps(
        {"namespace": clean_namespace.casefold(), "identity": canonical},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    prefix = re.sub(r"[^A-Z0-9]+", "-", clean_namespace.upper()).strip("-")[:18]
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20].upper()}"


def evidence_fingerprint_for(
    source_document: str,
    source_item_id: str,
    source_location: str,
    evidence_text: str,
) -> str:
    """Kaynak kanıtının içeriğe bağlı SHA-256 parmak izini üretir."""
    payload = {
        "source_document": _required_text(source_document, "Kaynak belge"),
        "source_item_id": _required_text(source_item_id, "Kaynak öğe kimliği"),
        "source_location": _required_text(source_location, "Kaynak konumu"),
        "evidence_text": _required_text(evidence_text, "Kanıt metni"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON nesnesi anahtarları string olmalıdır.")
            if key in frozen:
                raise ValueError("JSON nesnesinde yinelenen anahtar bulunamaz.")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON verisi sonlu olmayan sayı içeremez.")
        return value
    raise ValueError(f"JSON için desteklenmeyen değer türü: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _evidence_tuple(values: Any) -> tuple["EvidenceLink", ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ValueError("Kanıt bağları liste veya tuple olmalıdır.")
    result = tuple(
        item if isinstance(item, EvidenceLink) else EvidenceLink.from_dict(item)
        for item in values
    )
    identifiers = [item.evidence_id for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Aynı kayıtta yinelenen kanıt kimliği bulunamaz.")
    return result


def _has_source_evidence(links: tuple["EvidenceLink", ...]) -> bool:
    return any(link.is_source_evidence for link in links)


def _validate_record_evidence(
    derivation_kind: str,
    source_requirement_ids: tuple[str, ...],
    evidence_text: str,
    evidence_links: tuple["EvidenceLink", ...],
    entity_label: str,
) -> None:
    if not evidence_links:
        if derivation_kind in AUTOMATIC_DERIVATION_KINDS:
            raise ValueError(
                f"Otomatik {entity_label} geçerli kaynak kanıtı olmadan oluşturulamaz."
            )
        raise ValueError(f"Kanonik {entity_label} kanıt bağı olmadan oluşturulamaz.")
    if derivation_kind in AUTOMATIC_DERIVATION_KINDS and not _has_source_evidence(evidence_links):
        raise ValueError(f"Otomatik {entity_label} geçerli kaynak kanıtı olmadan oluşturulamaz.")
    if derivation_kind == DERIVATION_MODEL_SUGGESTION and not _has_source_evidence(evidence_links):
        raise ValueError(f"Model kaynaklı {entity_label} geçerli kaynak kanıtı olmadan oluşturulamaz.")
    if evidence_text not in {link.evidence_text for link in evidence_links}:
        raise ValueError(f"{entity_label.capitalize()} kanıt metni kayıtlı kanıt bağlarından biriyle eşleşmelidir.")
    if source_requirement_ids:
        evidenced_ids = {
            link.source_item_id.casefold()
            for link in evidence_links
            if link.is_source_evidence
        }
        missing = [
            requirement_id
            for requirement_id in source_requirement_ids
            if requirement_id.casefold() not in evidenced_ids
        ]
        if missing:
            raise ValueError(
                f"{entity_label.capitalize()} kaynak gereksinimlerinin kanıt bağı eksik: "
                + ", ".join(missing)
            )


def _choice_groups(values: Any, label: str) -> tuple[tuple[str, ...], ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{label} liste veya tuple olmalıdır.")
    groups: list[tuple[str, ...]] = []
    for group in values:
        choices = _text_tuple(group)
        if len(choices) < 2:
            raise ValueError(f"{label} içindeki her grup en az iki alternatif içermelidir.")
        groups.append(choices)
    return tuple(groups)


def _payload_evidence_mapping(
    value: Any,
    payload_keys: tuple[str, ...],
    evidence_links: tuple["EvidenceLink", ...],
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise ValueError("Aday payload_evidence_ids alanı JSON nesnesi olmalıdır.")
    mapped: dict[str, tuple[str, ...]] = {}
    for key, evidence_ids in value.items():
        clean_key = _required_text(key, "Aday payload kanıt alanı")
        if clean_key in mapped:
            raise ValueError("Aday payload kanıt alanları yinelenemez.")
        identifiers = _text_tuple(evidence_ids)
        if not identifiers:
            raise ValueError(f"Aday payload alanı kanıt kimliği gerektirir: {clean_key}")
        mapped[clean_key] = identifiers
    if set(mapped) != set(payload_keys):
        missing = sorted(set(payload_keys) - set(mapped))
        extra = sorted(set(mapped) - set(payload_keys))
        parts = []
        if missing:
            parts.append("kanıtsız alanlar=" + ", ".join(missing))
        if extra:
            parts.append("bilinmeyen alanlar=" + ", ".join(extra))
        raise ValueError("Aday payload kanıt eşlemesi eksik/geçersiz: " + "; ".join(parts))
    known_evidence_ids = {item.evidence_id for item in evidence_links}
    for key, identifiers in mapped.items():
        unknown = [item for item in identifiers if item not in known_evidence_ids]
        if unknown:
            raise ValueError(
                f"Aday payload alanı bilinmeyen kanıta bağlı ({key}): " + ", ".join(unknown)
            )
    return MappingProxyType(mapped)


def _payload_contains_reserved_reference(value: Any) -> str:
    reserved = {
        "sourceelementid", "targetelementid", "targetstableid",
        "sourceid", "targetid", "targets", "referencedstableids",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", _clean(key).casefold())
            if normalized in reserved:
                return str(key)
            nested = _payload_contains_reserved_reference(item)
            if nested:
                return nested
    elif isinstance(value, (list, tuple)):
        for item in value:
            nested = _payload_contains_reserved_reference(item)
            if nested:
                return nested
    return ""


def _payload_scalar_claims(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Mapping):
        return tuple(
            claim
            for item in value.values()
            for claim in _payload_scalar_claims(item)
        )
    if isinstance(value, tuple):
        return tuple(
            claim
            for item in value
            for claim in _payload_scalar_claims(item)
        )
    if value is None:
        return ()
    return (value,)


def _payload_claim_is_supported(claim: Any, evidence_texts: tuple[str, ...]) -> bool:
    corpus = "\n".join(_clean(text).casefold() for text in evidence_texts)
    def contains(candidate: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", corpus))

    if isinstance(claim, str):
        normalized = _clean(claim).casefold()
        return normalized == "belirsiz/eksik" or contains(normalized)
    if isinstance(claim, bool):
        candidates = {"true", "doğru", "evet"} if claim else {"false", "yanlış", "hayır"}
        return any(contains(candidate) for candidate in candidates)
    if isinstance(claim, (int, float)):
        number = float(claim)
        if not math.isfinite(number):
            return False
        candidates = {str(claim).casefold()}
        if number.is_integer():
            candidates.add(str(int(number)))
        candidates.update(item.replace(".", ",") for item in tuple(candidates))
        return any(contains(candidate) for candidate in candidates)
    return False


def _meaningful_words(value: str) -> frozenset[str]:
    stop_words = {
        "aday", "adayi", "bağlantı", "baglanti", "bir", "bu", "icin", "için",
        "faaliyet", "fonksiyon", "fonksiyonu", "hizmet", "hizmeti", "ile", "ilgili",
        "ilişki", "iliski", "mimari", "öğe", "oge", "olarak", "servis", "servisi",
        "sistem", "sistemi", "tarafından", "tarafindan", "ve", "veya",
    }
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", _clean(value).casefold())
        if not unicodedata.combining(char)
    )
    return frozenset(
        token
        for token in re.findall(r"[0-9a-zçğıöşü]+", normalized)
        if (len(token) >= 3 or (len(token) == 1 and token.isalnum()))
        and token not in stop_words
    )


def _normalized_phrase(value: str) -> str:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", _clean(value).casefold())
        if not unicodedata.combining(char)
    )
    return " ".join(re.findall(r"[0-9a-zçğıöşü]+", normalized))


def _sentences(value: str) -> tuple[str, ...]:
    return tuple(
        sentence
        for sentence in re.split(r"(?<=[.!?;])\s+|[\r\n]+", _clean(value))
        if sentence
    )


def _type_claim_is_grounded(
    key: str,
    claim: str,
    evidence_texts: tuple[str, ...],
    *,
    require_evidence_hint: bool,
) -> bool:
    known_types = KNOWN_ELEMENT_TYPES if key == "element_type" else KNOWN_RELATIONSHIP_TYPES
    if claim not in known_types:
        return False
    if not require_evidence_hint:
        return True
    normalized_type = re.sub(r"[^a-z0-9]", "", _normalized_phrase(claim))
    hints = (
        ELEMENT_TYPE_HINTS.get(normalized_type)
        if key == "element_type"
        else RELATIONSHIP_TYPE_HINTS.get(normalized_type)
    )
    if not hints:
        return False
    corpus = _normalized_phrase(" ".join(evidence_texts))
    return any(
        re.search(
            rf"(?<!\w){re.escape(_normalized_phrase(hint))}[a-zçğıöşü]*(?!\w)",
            corpus,
        )
        for hint in hints
    )


def _interpretive_claim_is_grounded(
    key: str,
    claim: Any,
    evidence_links: tuple["EvidenceLink", ...],
    evidence_texts: tuple[str, ...],
    *,
    require_type_evidence: bool = False,
) -> bool:
    if not isinstance(claim, str):
        return False
    if key in {"element_type", "relationship_type"}:
        return _type_claim_is_grounded(
            key,
            claim,
            evidence_texts,
            require_evidence_hint=require_type_evidence,
        )
    if key == "identity_key":
        claim_words = _meaningful_words(claim.replace("-", " ").replace("_", " "))
    else:
        claim_words = _meaningful_words(claim)
    source_words = _meaningful_words(
        " ".join(
            [*evidence_texts, *(link.source_item_id for link in evidence_links)]
        )
    )
    if key in {"identity_key", "name", "description"}:
        normalized_claim = _normalized_phrase(claim.replace("-", " ").replace("_", " "))
        normalized_sources = tuple(
            _normalized_phrase(item)
            for item in [*evidence_texts, *(link.source_item_id for link in evidence_links)]
        )
        if normalized_claim and any(normalized_claim in source for source in normalized_sources):
            return True
        if key == "description":
            return any(
                bool(claim_words)
                and claim_words.issubset(_meaningful_words(sentence))
                for text in evidence_texts
                for sentence in _sentences(text)
            )
        return bool(claim_words) and claim_words.issubset(source_words)
    return False


def _validate_payload_claim_evidence(
    payload: Mapping[str, Any],
    payload_evidence_ids: Mapping[str, tuple[str, ...]],
    evidence_links: tuple["EvidenceLink", ...],
    proposal_origin: str,
) -> None:
    technical_token_pattern = re.compile(
        r"(?<!\w)(?:[-+]?\d+(?:[.,]\d+)?|[a-zçğıöşü0-9]{2,}(?:[-_/][a-zçğıöşü0-9]+)+)(?!\w)",
        re.IGNORECASE,
    )
    evidence_by_id = {item.evidence_id: item for item in evidence_links}
    for key, value in payload.items():
        field_evidence = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in payload_evidence_ids[key]
        )
        required_derivation = (
            DERIVATION_USER_SUPPLIED
            if proposal_origin == DERIVATION_USER_SUPPLIED
            else None
        )
        if required_derivation is not None:
            has_required_evidence = any(
                link.derivation_kind == required_derivation for link in field_evidence
            )
        else:
            has_required_evidence = any(link.is_source_evidence for link in field_evidence)
        if not has_required_evidence:
            raise ValueError(
                f"Aday payload alanı uygun kaynak/girdi kanıtı gerektirir: {key}"
            )
        evidence_texts = tuple(
            link.evidence_text
            for link in field_evidence
            if (
                link.derivation_kind == DERIVATION_USER_SUPPLIED
                if proposal_origin == DERIVATION_USER_SUPPLIED
                else link.is_source_evidence
            )
        )
        claims = _payload_scalar_claims(value)
        if key in {"identity_key", "name", "element_type", "relationship_type"}:
            if not _interpretive_claim_is_grounded(
                key,
                value,
                field_evidence,
                evidence_texts,
            ):
                raise ValueError(
                    f"Aday payload yorum alanı kaynak kanıtıyla ilişkilendirilemedi: {key}"
                )
            continue
        if key == "description":
            if not _interpretive_claim_is_grounded(
                key,
                value,
                field_evidence,
                evidence_texts,
            ):
                raise ValueError(
                    "Aday payload açıklaması kaynak kanıtıyla ilişkilendirilemedi."
                )
            claims = tuple(
                token
                for claim in claims
                if isinstance(claim, str)
                for token in technical_token_pattern.findall(claim)
            )
        for claim in claims:
            if not _payload_claim_is_supported(claim, evidence_texts):
                rendered = _clean(str(claim))[:80]
                raise ValueError(
                    f"Aday payload iddiası kaynak kanıtında bulunamadı ({key}={rendered})."
                )


def _validate_automatic_canonical_claims(
    derivation_kind: str,
    identity_key: str,
    name: str,
    entity_type: str,
    description: str,
    evidence_links: tuple["EvidenceLink", ...],
    entity_label: str,
) -> None:
    if derivation_kind not in AUTOMATIC_DERIVATION_KINDS:
        return
    source_links = tuple(link for link in evidence_links if link.is_source_evidence)
    source_texts = tuple(link.evidence_text for link in source_links)
    for key, claim in (
        ("identity_key", identity_key),
        ("name", name),
        ("entity_type", entity_type),
        ("description", description),
    ):
        interpreted_key = (
            "element_type" if key == "entity_type" and entity_label == "mimari öğe"
            else "relationship_type" if key == "entity_type"
            else key
        )
        if not _interpretive_claim_is_grounded(
            interpreted_key,
            claim,
            source_links,
            source_texts,
            require_type_evidence=True,
        ):
            raise ValueError(
                f"Otomatik {entity_label} alanı kaynak kanıtıyla ilişkilendirilemedi: {key}"
            )


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    source_item_id: str
    source_document: str
    source_location: str
    evidence_text: str
    evidence_fingerprint: str
    confidence_score: float
    derivation_kind: str = DERIVATION_DIRECT
    producer: str = ""
    producer_version: str = ""
    evidence_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("source_item_id", "Kaynak öğe kimliği"),
            ("source_document", "Kaynak belge"),
            ("source_location", "Kaynak konumu"),
            ("evidence_text", "Kanıt metni"),
            ("evidence_fingerprint", "Kanıt parmak izi"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        kind = _required_text(self.derivation_kind, "Kanıt türetim türü")
        if kind not in DERIVATION_KINDS:
            raise ValueError(f"Desteklenmeyen kanıt türetim türü: {kind}")
        object.__setattr__(self, "derivation_kind", kind)
        object.__setattr__(self, "confidence_score", _confidence(self.confidence_score))
        object.__setattr__(self, "producer", _required_text(self.producer, "Kanıt üreticisi"))
        object.__setattr__(
            self, "producer_version",
            _required_text(self.producer_version, "Kanıt üretici sürümü"),
        )
        fingerprint = self.evidence_fingerprint.casefold()
        if not _SHA256_PATTERN.fullmatch(fingerprint):
            raise ValueError("Kanıt parmak izi 64 haneli SHA-256 olmalıdır.")
        expected_fingerprint = evidence_fingerprint_for(
            self.source_document,
            self.source_item_id,
            self.source_location,
            self.evidence_text,
        )
        if fingerprint != expected_fingerprint:
            raise ValueError("Kanıt parmak izi kaynak içeriğiyle uyuşmuyor.")
        object.__setattr__(self, "evidence_fingerprint", fingerprint)
        identifier = _clean(self.evidence_id) or stable_id_for("EVIDENCE", {
            "source_item_id": self.source_item_id,
            "source_document": self.source_document,
            "source_location": self.source_location,
            "fingerprint": self.evidence_fingerprint,
        })
        object.__setattr__(self, "evidence_id", identifier)

    @property
    def is_source_evidence(self) -> bool:
        """Gemma/model metnini kaynak gerçeğinden ayırır."""
        return self.derivation_kind in AUTOMATIC_DERIVATION_KINDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_item_id": self.source_item_id,
            "source_document": self.source_document,
            "source_location": self.source_location,
            "evidence_text": self.evidence_text,
            "evidence_fingerprint": self.evidence_fingerprint,
            "confidence_score": self.confidence_score,
            "derivation_kind": self.derivation_kind,
            "producer": self.producer,
            "producer_version": self.producer_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvidenceLink":
        if not isinstance(raw, Mapping):
            raise ValueError("Kanıt bağı JSON nesnesi olmalıdır.")
        return cls(
            source_item_id=raw.get("source_item_id", ""),
            source_document=raw.get("source_document", ""),
            source_location=raw.get("source_location", ""),
            evidence_text=raw.get("evidence_text", ""),
            evidence_fingerprint=raw.get("evidence_fingerprint", ""),
            confidence_score=raw.get("confidence_score", -1),
            derivation_kind=raw.get("derivation_kind", DERIVATION_DIRECT),
            producer=raw.get("producer", ""),
            producer_version=raw.get("producer_version", ""),
            evidence_id=raw.get("evidence_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ArchitectureElement:
    identity_key: str
    framework_profile_id: str
    name: str
    element_type: str
    description: str
    source_requirement_ids: tuple[str, ...]
    evidence_text: str
    confidence_score: float
    evidence_links: tuple[EvidenceLink, ...]
    review_status: str = REVIEW_PENDING
    version: str = "v0001"
    derivation_kind: str = DERIVATION_DIRECT
    source_proposal_id: str = ""
    approval_decision_id: str = ""
    stable_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("identity_key", "Mimari öğe identity_key"),
            ("framework_profile_id", "Çerçeve profili"),
            ("name", "Mimari öğe adı"),
            ("element_type", "Mimari öğe türü"),
            ("description", "Mimari öğe açıklaması"),
            ("evidence_text", "Mimari öğe kanıt metni"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        object.__setattr__(
            self, "version", _artifact_version(self.version, "Mimari öğe sürümü"),
        )
        object.__setattr__(
            self, "source_requirement_ids",
            _text_tuple(self.source_requirement_ids, upper=True),
        )
        links = _evidence_tuple(self.evidence_links)
        object.__setattr__(self, "evidence_links", links)
        object.__setattr__(self, "confidence_score", _confidence(self.confidence_score))
        status = _required_text(self.review_status, "İnceleme durumu")
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Desteklenmeyen inceleme durumu: {status}")
        if status not in {REVIEW_PENDING, REVIEW_APPROVED}:
            raise ValueError(
                "Reddedilen, düzenlenecek veya ertelenen kayıt kanonik mimari öğe olamaz."
            )
        object.__setattr__(self, "review_status", status)
        kind = _required_text(self.derivation_kind, "Türetim türü")
        if kind not in DERIVATION_KINDS:
            raise ValueError(f"Desteklenmeyen türetim türü: {kind}")
        object.__setattr__(self, "derivation_kind", kind)
        source_proposal_id = _clean(self.source_proposal_id)
        approval_decision_id = _clean(self.approval_decision_id)
        object.__setattr__(self, "source_proposal_id", source_proposal_id)
        object.__setattr__(self, "approval_decision_id", approval_decision_id)
        if status == REVIEW_APPROVED and (not source_proposal_id or not approval_decision_id):
            raise ValueError(
                "Onaylı mimari öğe kaynak aday ve açık kullanıcı karar kimliği gerektirir."
            )
        if status != REVIEW_APPROVED and (source_proposal_id or approval_decision_id):
            raise ValueError("Aday/karar kimliği yalnız onaylı mimari öğede kullanılabilir.")
        if kind in {DERIVATION_USER_SUPPLIED, DERIVATION_MODEL_SUGGESTION}:
            if status != REVIEW_APPROVED:
                raise ValueError(
                    "Kullanıcı/model girdisi kanonik modele yalnız açık onaydan sonra girebilir."
                )
        _validate_record_evidence(
            kind,
            self.source_requirement_ids,
            self.evidence_text,
            links,
            "mimari öğe",
        )
        # İncelenmemiş otomatik kanonik kayıtlar katı sözcüksel kapıdan geçer.
        # Approved bir kayıt ise KART 3'te doğrulanmış aday+karar kimliklerini
        # taşır; ArchitectureSnapshot bu kimlikleri aday payload'ı/digest'iyle
        # birebir bağlar. Böylece ``Measure`` gibi mimari sınıflandırmalar açık
        # kullanıcı kararından sonra kanonikleşebilir, karar olmadan geçemez.
        if not (
            status == REVIEW_APPROVED
            and source_proposal_id
            and approval_decision_id
        ):
            _validate_automatic_canonical_claims(
                kind,
                self.identity_key,
                self.name,
                self.element_type,
                self.description,
                links,
                "mimari öğe",
            )
        identifier = _clean(self.stable_id) or stable_id_for("ARCH-ELEMENT", {
            "profile": self.framework_profile_id,
            "element_type": self.element_type,
            "identity_key": self.identity_key,
        })
        object.__setattr__(self, "stable_id", identifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "identity_key": self.identity_key,
            "framework_profile_id": self.framework_profile_id,
            "name": self.name,
            "element_type": self.element_type,
            "description": self.description,
            "source_requirement_ids": list(self.source_requirement_ids),
            "evidence_text": self.evidence_text,
            "confidence_score": self.confidence_score,
            "evidence_links": [item.to_dict() for item in self.evidence_links],
            "review_status": self.review_status,
            "version": self.version,
            "derivation_kind": self.derivation_kind,
            "source_proposal_id": self.source_proposal_id,
            "approval_decision_id": self.approval_decision_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArchitectureElement":
        if not isinstance(raw, Mapping):
            raise ValueError("Mimari öğe JSON nesnesi olmalıdır.")
        return cls(
            identity_key=raw.get("identity_key", ""),
            framework_profile_id=raw.get("framework_profile_id", ""),
            name=raw.get("name", ""),
            element_type=raw.get("element_type", ""),
            description=raw.get("description", ""),
            source_requirement_ids=raw.get("source_requirement_ids", ()),
            evidence_text=raw.get("evidence_text", ""),
            confidence_score=raw.get("confidence_score", -1),
            evidence_links=raw.get("evidence_links", ()),
            review_status=raw.get("review_status", REVIEW_PENDING),
            version=raw.get("version", "v0001"),
            derivation_kind=raw.get("derivation_kind", DERIVATION_DIRECT),
            source_proposal_id=raw.get("source_proposal_id", ""),
            approval_decision_id=raw.get("approval_decision_id", ""),
            stable_id=raw.get("stable_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ArchitectureRelationship:
    identity_key: str
    framework_profile_id: str
    name: str
    relationship_type: str
    source_element_id: str
    target_element_id: str
    description: str
    source_requirement_ids: tuple[str, ...]
    evidence_text: str
    confidence_score: float
    evidence_links: tuple[EvidenceLink, ...]
    review_status: str = REVIEW_PENDING
    version: str = "v0001"
    derivation_kind: str = DERIVATION_DIRECT
    source_proposal_id: str = ""
    approval_decision_id: str = ""
    stable_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("identity_key", "Mimari ilişki identity_key"),
            ("framework_profile_id", "Çerçeve profili"),
            ("name", "Mimari ilişki adı"),
            ("relationship_type", "Mimari ilişki türü"),
            ("source_element_id", "Kaynak mimari öğe kimliği"),
            ("target_element_id", "Hedef mimari öğe kimliği"),
            ("description", "Mimari ilişki açıklaması"),
            ("evidence_text", "Mimari ilişki kanıt metni"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        object.__setattr__(
            self, "version", _artifact_version(self.version, "Mimari ilişki sürümü"),
        )
        if self.source_element_id == self.target_element_id:
            raise ValueError("Mimari ilişkinin kaynak ve hedef öğesi aynı olamaz.")
        object.__setattr__(
            self, "source_requirement_ids",
            _text_tuple(self.source_requirement_ids, upper=True),
        )
        links = _evidence_tuple(self.evidence_links)
        object.__setattr__(self, "evidence_links", links)
        object.__setattr__(self, "confidence_score", _confidence(self.confidence_score))
        status = _required_text(self.review_status, "İnceleme durumu")
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Desteklenmeyen inceleme durumu: {status}")
        if status not in {REVIEW_PENDING, REVIEW_APPROVED}:
            raise ValueError(
                "Reddedilen, düzenlenecek veya ertelenen kayıt kanonik mimari ilişki olamaz."
            )
        object.__setattr__(self, "review_status", status)
        kind = _required_text(self.derivation_kind, "Türetim türü")
        if kind not in DERIVATION_KINDS:
            raise ValueError(f"Desteklenmeyen türetim türü: {kind}")
        object.__setattr__(self, "derivation_kind", kind)
        source_proposal_id = _clean(self.source_proposal_id)
        approval_decision_id = _clean(self.approval_decision_id)
        object.__setattr__(self, "source_proposal_id", source_proposal_id)
        object.__setattr__(self, "approval_decision_id", approval_decision_id)
        if status == REVIEW_APPROVED and (not source_proposal_id or not approval_decision_id):
            raise ValueError(
                "Onaylı mimari ilişki kaynak aday ve açık kullanıcı karar kimliği gerektirir."
            )
        if status != REVIEW_APPROVED and (source_proposal_id or approval_decision_id):
            raise ValueError("Aday/karar kimliği yalnız onaylı mimari ilişkide kullanılabilir.")
        if kind in {DERIVATION_USER_SUPPLIED, DERIVATION_MODEL_SUGGESTION}:
            if status != REVIEW_APPROVED:
                raise ValueError(
                    "Kullanıcı/model girdisi kanonik modele yalnız açık onaydan sonra girebilir."
                )
        _validate_record_evidence(
            kind,
            self.source_requirement_ids,
            self.evidence_text,
            links,
            "mimari ilişki",
        )
        if not (
            status == REVIEW_APPROVED
            and source_proposal_id
            and approval_decision_id
        ):
            _validate_automatic_canonical_claims(
                kind,
                self.identity_key,
                self.name,
                self.relationship_type,
                self.description,
                links,
                "mimari ilişki",
            )
        identifier = _clean(self.stable_id) or stable_id_for("ARCH-REL", {
            "profile": self.framework_profile_id,
            "relationship_type": self.relationship_type,
            "identity_key": self.identity_key,
            "source": self.source_element_id,
            "target": self.target_element_id,
        })
        object.__setattr__(self, "stable_id", identifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "identity_key": self.identity_key,
            "framework_profile_id": self.framework_profile_id,
            "name": self.name,
            "relationship_type": self.relationship_type,
            "source_element_id": self.source_element_id,
            "target_element_id": self.target_element_id,
            "description": self.description,
            "source_requirement_ids": list(self.source_requirement_ids),
            "evidence_text": self.evidence_text,
            "confidence_score": self.confidence_score,
            "evidence_links": [item.to_dict() for item in self.evidence_links],
            "review_status": self.review_status,
            "version": self.version,
            "derivation_kind": self.derivation_kind,
            "source_proposal_id": self.source_proposal_id,
            "approval_decision_id": self.approval_decision_id,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArchitectureRelationship":
        if not isinstance(raw, Mapping):
            raise ValueError("Mimari ilişki JSON nesnesi olmalıdır.")
        return cls(
            identity_key=raw.get("identity_key", ""),
            framework_profile_id=raw.get("framework_profile_id", ""),
            name=raw.get("name", ""),
            relationship_type=raw.get("relationship_type", ""),
            source_element_id=raw.get("source_element_id", ""),
            target_element_id=raw.get("target_element_id", ""),
            description=raw.get("description", ""),
            source_requirement_ids=raw.get("source_requirement_ids", ()),
            evidence_text=raw.get("evidence_text", ""),
            confidence_score=raw.get("confidence_score", -1),
            evidence_links=raw.get("evidence_links", ()),
            review_status=raw.get("review_status", REVIEW_PENDING),
            version=raw.get("version", "v0001"),
            derivation_kind=raw.get("derivation_kind", DERIVATION_DIRECT),
            source_proposal_id=raw.get("source_proposal_id", ""),
            approval_decision_id=raw.get("approval_decision_id", ""),
            stable_id=raw.get("stable_id", ""),
        )


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    identity_key: str
    framework_profile_id: str
    proposal_type: str
    title: str
    rationale: str
    proposed_payload: Mapping[str, Any]
    source_requirement_ids: tuple[str, ...]
    evidence_text: str
    confidence_score: float
    evidence_links: tuple[EvidenceLink, ...]
    payload_evidence_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    source_element_id: str = ""
    target_element_id: str = ""
    target_stable_id: str = ""
    proposal_origin: str = DERIVATION_MODEL_SUGGESTION
    review_status: str = REVIEW_PENDING
    initial_decision: str = DECISION_DEFER
    version: str = "v0001"
    proposal_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("identity_key", "Aday identity_key"),
            ("framework_profile_id", "Çerçeve profili"),
            ("proposal_type", "Aday türü"),
            ("title", "Aday başlığı"),
            ("rationale", "Aday gerekçesi"),
            ("evidence_text", "Aday kanıt metni"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        object.__setattr__(self, "version", _artifact_version(self.version, "Aday sürümü"))
        proposal_type = self.proposal_type.casefold()
        if proposal_type not in PROPOSAL_TYPES:
            raise ValueError(f"Desteklenmeyen aday türü: {self.proposal_type}")
        object.__setattr__(self, "proposal_type", proposal_type)
        if not isinstance(self.proposed_payload, Mapping) or not self.proposed_payload:
            raise ValueError("Aday proposed_payload boş olmayan JSON nesnesi olmalıdır.")
        if any(not isinstance(key, str) for key in self.proposed_payload):
            raise ValueError("JSON nesnesi anahtarları string olmalıdır.")
        payload_copy = dict(self.proposed_payload)
        required_payload_fields = {
            "element": {"identity_key", "name", "element_type", "description"},
            "relationship": {"identity_key", "name", "relationship_type", "description"},
        }[proposal_type]
        missing_payload_fields = sorted(required_payload_fields - set(payload_copy))
        if missing_payload_fields:
            raise ValueError(
                "Aday payload kanonikleşme alanları eksik: "
                + ", ".join(missing_payload_fields)
            )
        extra_payload_fields = sorted(set(payload_copy) - required_payload_fields)
        if extra_payload_fields:
            raise ValueError(
                "Kart 1 aday payload'ında kanoniğe kayıpsız aktarılamayan alanlar var: "
                + ", ".join(extra_payload_fields)
            )
        for key in required_payload_fields:
            payload_copy[key] = _required_text(
                payload_copy[key], f"Aday payload {key} alanı",
            )
        if payload_copy["identity_key"] != self.identity_key:
            raise ValueError("Aday identity_key alanı payload identity_key ile uyuşmuyor.")
        frozen_payload = _freeze_json(payload_copy)
        reserved_reference = _payload_contains_reserved_reference(frozen_payload)
        if reserved_reference:
            raise ValueError(
                f"Aday payload referans alanı '{reserved_reference}' serbest JSON içinde tutulamaz; "
                "türlenmiş aday uç alanları kullanılmalıdır."
            )
        object.__setattr__(self, "proposed_payload", frozen_payload)
        object.__setattr__(
            self, "source_requirement_ids",
            _text_tuple(self.source_requirement_ids, upper=True),
        )
        links = _evidence_tuple(self.evidence_links)
        object.__setattr__(self, "evidence_links", links)
        object.__setattr__(self, "confidence_score", _confidence(self.confidence_score))
        origin = _required_text(self.proposal_origin, "Aday kökeni")
        if origin not in DERIVATION_KINDS:
            raise ValueError(f"Desteklenmeyen aday kökeni: {origin}")
        if not links:
            if origin != DERIVATION_USER_SUPPLIED:
                raise ValueError("Otomatik veya model kaynaklı aday geçerli kaynak kanıtı gerektirir.")
            raise ValueError("Kullanıcı adayı izlenebilir user_supplied kanıt bağı gerektirir.")
        if self.evidence_text not in {link.evidence_text for link in links}:
            raise ValueError("Aday kanıt metni kayıtlı kanıt bağlarından biriyle eşleşmelidir.")
        if origin != DERIVATION_USER_SUPPLIED and not _has_source_evidence(links):
            raise ValueError("Otomatik veya model kaynaklı aday geçerli kaynak kanıtı gerektirir.")
        if origin == DERIVATION_USER_SUPPLIED and not any(
            link.derivation_kind == DERIVATION_USER_SUPPLIED for link in links
        ):
            raise ValueError("Kullanıcı adayı user_supplied türünde izlenebilir girdi gerektirir.")
        if self.source_requirement_ids:
            evidenced_ids = {
                link.source_item_id.casefold()
                for link in links
                if link.is_source_evidence
            }
            missing = [
                requirement_id
                for requirement_id in self.source_requirement_ids
                if requirement_id.casefold() not in evidenced_ids
            ]
            if missing:
                raise ValueError(
                    "Aday kaynak gereksinimlerinin kanıt bağı eksik: " + ", ".join(missing)
                )
        object.__setattr__(self, "proposal_origin", origin)
        if self.review_status != REVIEW_PENDING or self.initial_decision != DECISION_DEFER:
            raise ValueError("Yeni aday yalnızca 'Onay bekliyor' ve 'Ertele' durumunda oluşturulabilir.")
        source_element_id = _clean(self.source_element_id)
        target_element_id = _clean(self.target_element_id)
        if proposal_type == "relationship":
            if not source_element_id or not target_element_id:
                raise ValueError("İlişki adayı türlenmiş kaynak ve hedef öğe kimliği gerektirir.")
            if source_element_id == target_element_id:
                raise ValueError("İlişki adayının kaynak ve hedef öğesi aynı olamaz.")
        elif source_element_id or target_element_id:
            raise ValueError("Öğe adayı kaynak/hedef ilişki ucu taşıyamaz.")
        object.__setattr__(self, "source_element_id", source_element_id)
        object.__setattr__(self, "target_element_id", target_element_id)
        object.__setattr__(self, "target_stable_id", _clean(self.target_stable_id))
        payload_evidence_ids = _payload_evidence_mapping(
            self.payload_evidence_ids,
            tuple(frozen_payload.keys()),
            links,
        )
        _validate_payload_claim_evidence(
            frozen_payload,
            payload_evidence_ids,
            links,
            origin,
        )
        object.__setattr__(self, "payload_evidence_ids", payload_evidence_ids)
        identifier = _clean(self.proposal_id) or stable_id_for("ARCH-PROPOSAL", {
            "profile": self.framework_profile_id,
            "proposal_type": self.proposal_type,
            "identity_key": self.identity_key,
            "source": self.source_element_id,
            "target_element": self.target_element_id,
            "target": self.target_stable_id,
        })
        object.__setattr__(self, "proposal_id", identifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "identity_key": self.identity_key,
            "framework_profile_id": self.framework_profile_id,
            "proposal_type": self.proposal_type,
            "title": self.title,
            "rationale": self.rationale,
            "proposed_payload": _thaw_json(self.proposed_payload),
            "payload_evidence_ids": {
                key: list(value) for key, value in self.payload_evidence_ids.items()
            },
            "source_requirement_ids": list(self.source_requirement_ids),
            "evidence_text": self.evidence_text,
            "confidence_score": self.confidence_score,
            "evidence_links": [item.to_dict() for item in self.evidence_links],
            "source_element_id": self.source_element_id,
            "target_element_id": self.target_element_id,
            "target_stable_id": self.target_stable_id,
            "proposal_origin": self.proposal_origin,
            "review_status": self.review_status,
            "initial_decision": self.initial_decision,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CandidateProposal":
        if not isinstance(raw, Mapping):
            raise ValueError("Aday öneri JSON nesnesi olmalıdır.")
        return cls(
            identity_key=raw.get("identity_key", ""),
            framework_profile_id=raw.get("framework_profile_id", ""),
            proposal_type=raw.get("proposal_type", ""),
            title=raw.get("title", ""),
            rationale=raw.get("rationale", ""),
            proposed_payload=raw.get("proposed_payload", {}),
            payload_evidence_ids=raw.get("payload_evidence_ids", {}),
            source_requirement_ids=raw.get("source_requirement_ids", ()),
            evidence_text=raw.get("evidence_text", ""),
            confidence_score=raw.get("confidence_score", -1),
            evidence_links=raw.get("evidence_links", ()),
            source_element_id=raw.get("source_element_id", ""),
            target_element_id=raw.get("target_element_id", ""),
            target_stable_id=raw.get("target_stable_id", ""),
            proposal_origin=raw.get("proposal_origin", DERIVATION_MODEL_SUGGESTION),
            review_status=raw.get("review_status", REVIEW_PENDING),
            initial_decision=raw.get("initial_decision", DECISION_DEFER),
            version=raw.get("version", "v0001"),
            proposal_id=raw.get("proposal_id", ""),
        )


def proposal_digest(proposal: CandidateProposal) -> str:
    encoded = json.dumps(
        proposal.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    candidate_id: str
    decision: str
    actor_type: str
    actor: str
    decided_at: str
    candidate_digest: str
    rationale: str = ""
    version: str = "v0001"
    decision_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("candidate_id", "Aday kimliği"),
            ("decision", "İnceleme kararı"),
            ("actor_type", "Karar aktör türü"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        object.__setattr__(self, "version", _artifact_version(self.version, "Karar sürümü"))
        if self.decision not in REVIEW_DECISIONS:
            raise ValueError(f"Desteklenmeyen inceleme kararı: {self.decision}")
        if self.actor_type not in ACTOR_TYPES:
            raise ValueError(f"Desteklenmeyen karar aktör türü: {self.actor_type}")
        object.__setattr__(self, "actor", _clean(self.actor))
        decided_at = _clean(self.decided_at)
        if decided_at:
            decided_at = _timezone_timestamp(decided_at, "Karar zamanı")
        object.__setattr__(self, "decided_at", decided_at)
        candidate_digest = _clean(self.candidate_digest).casefold()
        if candidate_digest and not _SHA256_PATTERN.fullmatch(candidate_digest):
            raise ValueError("Aday digest'i 64 haneli SHA-256 olmalıdır.")
        object.__setattr__(self, "candidate_digest", candidate_digest)
        object.__setattr__(self, "rationale", _clean(self.rationale))
        if not self.actor or not self.decided_at or not self.candidate_digest:
            raise ValueError("İnceleme kararı aktör, zaman ve aday digest'i gerektirir.")
        if self.decision != DECISION_DEFER and self.actor_type != ACTOR_USER:
            raise ValueError("Model, kural veya içe aktarıcı bir adayı onaylayamaz/reddedemez.")
        identifier = _clean(self.decision_id) or stable_id_for("ARCH-DECISION", {
            "candidate_id": self.candidate_id,
            "decision": self.decision,
            "actor_type": self.actor_type,
            "actor": self.actor,
            "decided_at": self.decided_at,
            "candidate_digest": self.candidate_digest,
        })
        object.__setattr__(self, "decision_id", identifier)

    @classmethod
    def for_proposal(
        cls,
        proposal: CandidateProposal,
        decision: str,
        actor: str,
        decided_at: str,
        *,
        rationale: str = "",
        version: str = "v0001",
    ) -> "ReviewDecision":
        return cls(
            candidate_id=proposal.proposal_id,
            decision=decision,
            actor_type=ACTOR_USER,
            actor=actor,
            decided_at=decided_at,
            candidate_digest=proposal_digest(proposal),
            rationale=rationale,
            version=version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "decision": self.decision,
            "actor_type": self.actor_type,
            "actor": self.actor,
            "decided_at": self.decided_at,
            "candidate_digest": self.candidate_digest,
            "rationale": self.rationale,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ReviewDecision":
        if not isinstance(raw, Mapping):
            raise ValueError("İnceleme kararı JSON nesnesi olmalıdır.")
        return cls(
            candidate_id=raw.get("candidate_id", ""),
            decision=raw.get("decision", ""),
            actor_type=raw.get("actor_type", ""),
            actor=raw.get("actor", ""),
            decided_at=raw.get("decided_at", ""),
            candidate_digest=raw.get("candidate_digest", ""),
            rationale=raw.get("rationale", ""),
            version=raw.get("version", "v0001"),
            decision_id=raw.get("decision_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    severity: str
    message: str
    target_id: str = ""
    view_id: str = ""
    missing_fields: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    blocking: bool = False
    version: str = "v0001"
    finding_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "Doğrulama kodu"))
        severity = _required_text(self.severity, "Doğrulama şiddeti").casefold()
        if severity not in FINDING_SEVERITIES:
            raise ValueError(f"Desteklenmeyen doğrulama şiddeti: {severity}")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "message", _required_text(self.message, "Doğrulama mesajı"))
        object.__setattr__(self, "target_id", _clean(self.target_id))
        object.__setattr__(self, "view_id", _clean(self.view_id))
        object.__setattr__(self, "missing_fields", _text_tuple(self.missing_fields))
        object.__setattr__(self, "evidence_ids", _text_tuple(self.evidence_ids))
        if not isinstance(self.blocking, bool):
            raise ValueError("Doğrulama blocking alanı boolean olmalıdır.")
        object.__setattr__(self, "version", _artifact_version(self.version, "Bulgu sürümü"))
        identifier = _clean(self.finding_id) or stable_id_for("ARCH-FINDING", {
            "code": self.code,
            "target_id": self.target_id,
            "view_id": self.view_id,
            "missing_fields": self.missing_fields,
        })
        object.__setattr__(self, "finding_id", identifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "target_id": self.target_id,
            "view_id": self.view_id,
            "missing_fields": list(self.missing_fields),
            "evidence_ids": list(self.evidence_ids),
            "blocking": self.blocking,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ValidationFinding":
        if not isinstance(raw, Mapping):
            raise ValueError("Doğrulama bulgusu JSON nesnesi olmalıdır.")
        return cls(
            code=raw.get("code", ""),
            severity=raw.get("severity", ""),
            message=raw.get("message", ""),
            target_id=raw.get("target_id", ""),
            view_id=raw.get("view_id", ""),
            missing_fields=raw.get("missing_fields", ()),
            evidence_ids=raw.get("evidence_ids", ()),
            blocking=raw.get("blocking", False),
            version=raw.get("version", "v0001"),
            finding_id=raw.get("finding_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ViewDefinition:
    framework_profile_id: str
    framework_version: str
    view_id: str
    name: str
    purpose: str
    required_element_types: tuple[str, ...]
    required_relationships: tuple[str, ...]
    data_prerequisites: tuple[str, ...]
    export_type: str
    package: str
    required_any_of_element_types: tuple[tuple[str, ...], ...] = ()
    required_any_of_relationships: tuple[tuple[str, ...], ...] = ()
    optional_element_types: tuple[str, ...] = ()
    optional_relationships: tuple[str, ...] = ()
    generation_classes: tuple[str, ...] = ("A", "B", "C")
    exchange_target: str = "belirsiz/eksik"
    implementation_status: str = "catalog_only"
    source_url: str = ""
    notes: str = ""
    stable_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("framework_profile_id", "Görünüm profil kimliği"),
            ("framework_version", "Görünüm profil sürümü"),
            ("view_id", "Görünüm kimliği"),
            ("name", "Görünüm adı"),
            ("purpose", "Görünüm amacı"),
            ("package", "Görünüm paketi"),
            ("implementation_status", "Uygulama durumu"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        for field_name in (
            "required_element_types", "required_relationships", "data_prerequisites",
            "optional_element_types", "optional_relationships", "generation_classes",
        ):
            object.__setattr__(self, field_name, _text_tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "required_any_of_element_types",
            _choice_groups(
                self.required_any_of_element_types,
                "Alternatif zorunlu öğe türleri",
            ),
        )
        object.__setattr__(
            self,
            "required_any_of_relationships",
            _choice_groups(
                self.required_any_of_relationships,
                "Alternatif zorunlu ilişki türleri",
            ),
        )
        unknown_generation_classes = set(self.generation_classes) - GENERATION_CLASSES
        if unknown_generation_classes:
            raise ValueError(
                "Desteklenmeyen üretilebilirlik sınıfı: "
                + ", ".join(sorted(unknown_generation_classes))
            )
        export_type = _required_text(self.export_type, "Dışa aktarma/sunum türü")
        if export_type not in EXPORT_TYPES:
            raise ValueError(f"Desteklenmeyen dışa aktarma/sunum türü: {export_type}")
        object.__setattr__(self, "export_type", export_type)
        object.__setattr__(self, "exchange_target", _clean(self.exchange_target) or "belirsiz/eksik")
        object.__setattr__(self, "source_url", _clean(self.source_url))
        object.__setattr__(self, "notes", _clean(self.notes))
        identifier = _clean(self.stable_id) or stable_id_for("ARCH-VIEW", {
            "profile": self.framework_profile_id,
            "framework_version": self.framework_version,
            "view_id": self.view_id,
        })
        object.__setattr__(self, "stable_id", identifier)

    @property
    def required_relationship_types(self) -> tuple[str, ...]:
        """Açık adlandırma isteyen tüketiciler için geriye dönük alias."""
        return self.required_relationships

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "framework_profile_id": self.framework_profile_id,
            "framework_version": self.framework_version,
            "view_id": self.view_id,
            "name": self.name,
            "purpose": self.purpose,
            "required_element_types": list(self.required_element_types),
            "required_relationships": list(self.required_relationships),
            "data_prerequisites": list(self.data_prerequisites),
            "export_type": self.export_type,
            "package": self.package,
            "required_any_of_element_types": [
                list(group) for group in self.required_any_of_element_types
            ],
            "required_any_of_relationships": [
                list(group) for group in self.required_any_of_relationships
            ],
            "optional_element_types": list(self.optional_element_types),
            "optional_relationships": list(self.optional_relationships),
            "generation_classes": list(self.generation_classes),
            "exchange_target": self.exchange_target,
            "implementation_status": self.implementation_status,
            "source_url": self.source_url,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ViewDefinition":
        if not isinstance(raw, Mapping):
            raise ValueError("Görünüm tanımı JSON nesnesi olmalıdır.")
        return cls(
            framework_profile_id=raw.get("framework_profile_id", ""),
            framework_version=raw.get("framework_version", ""),
            view_id=raw.get("view_id", ""),
            name=raw.get("name", ""),
            purpose=raw.get("purpose", ""),
            required_element_types=raw.get("required_element_types", ()),
            required_relationships=raw.get(
                "required_relationships", raw.get("required_relationship_types", ()),
            ),
            data_prerequisites=raw.get("data_prerequisites", ()),
            export_type=raw.get("export_type", ""),
            package=raw.get("package", ""),
            required_any_of_element_types=raw.get("required_any_of_element_types", ()),
            required_any_of_relationships=raw.get("required_any_of_relationships", ()),
            optional_element_types=raw.get("optional_element_types", ()),
            optional_relationships=raw.get("optional_relationships", ()),
            generation_classes=raw.get("generation_classes", ("A", "B", "C")),
            exchange_target=raw.get("exchange_target", "belirsiz/eksik"),
            implementation_status=raw.get("implementation_status", "catalog_only"),
            source_url=raw.get("source_url", ""),
            notes=raw.get("notes", ""),
            stable_id=raw.get("stable_id", ""),
        )


@dataclass(frozen=True, slots=True)
class FrameworkProfile:
    profile_id: str
    name: str
    version: str
    description: str
    view_definitions: tuple[ViewDefinition, ...]
    default_application_profile: str = ""
    application_profile_version: str = ""
    exchange_target: str = "belirsiz/eksik"
    source_url: str = ""
    schema_version: str = SCHEMA_VERSION
    stable_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("profile_id", "Profil kimliği"),
            ("name", "Profil adı"),
            ("version", "Profil sürümü"),
            ("description", "Profil açıklaması"),
            ("schema_version", "Profil şema sürümü"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        if not isinstance(self.view_definitions, (list, tuple)):
            raise ValueError("Profil görünüm tanımları liste veya tuple olmalıdır.")
        views = tuple(
            item if isinstance(item, ViewDefinition) else ViewDefinition.from_dict(item)
            for item in self.view_definitions
        )
        identifiers = [item.view_id.casefold() for item in views]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Profil içinde yinelenen görünüm kimliği bulunamaz.")
        for view in views:
            if view.framework_profile_id != self.profile_id or view.framework_version != self.version:
                raise ValueError("Görünüm tanımı profil kimliği/sürümüyle uyuşmuyor.")
        object.__setattr__(self, "view_definitions", views)
        application_profile = _clean(self.default_application_profile)
        application_version = _clean(self.application_profile_version)
        if bool(application_profile) != bool(application_version):
            raise ValueError("Uygulama profili adı ve sürümü birlikte tanımlanmalıdır.")
        object.__setattr__(self, "default_application_profile", application_profile)
        object.__setattr__(self, "application_profile_version", application_version)
        object.__setattr__(self, "exchange_target", _clean(self.exchange_target) or "belirsiz/eksik")
        object.__setattr__(self, "source_url", _clean(self.source_url))
        identifier = _clean(self.stable_id) or stable_id_for("ARCH-PROFILE", {
            "profile_id": self.profile_id, "version": self.version,
        })
        object.__setattr__(self, "stable_id", identifier)

    def get_view(self, view_id: str) -> ViewDefinition:
        key = _clean(view_id).casefold()
        for view in self.view_definitions:
            if view.view_id.casefold() == key:
                return view
        raise KeyError(f"Görünüm bulunamadı: {view_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "profile_id": self.profile_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "view_definitions": [item.to_dict() for item in self.view_definitions],
            "default_application_profile": self.default_application_profile,
            "application_profile_version": self.application_profile_version,
            "exchange_target": self.exchange_target,
            "source_url": self.source_url,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "FrameworkProfile":
        if not isinstance(raw, Mapping):
            raise ValueError("Çerçeve profili JSON nesnesi olmalıdır.")
        return cls(
            profile_id=raw.get("profile_id", ""),
            name=raw.get("name", ""),
            version=raw.get("version", ""),
            description=raw.get("description", ""),
            view_definitions=raw.get("view_definitions", ()),
            default_application_profile=raw.get("default_application_profile", ""),
            application_profile_version=raw.get("application_profile_version", ""),
            exchange_target=raw.get("exchange_target", "belirsiz/eksik"),
            source_url=raw.get("source_url", ""),
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            stable_id=raw.get("stable_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ArchitectureSnapshot:
    identity_key: str
    project_id: str
    name: str
    framework_profile_id: str
    framework_version: str
    version: str
    status: str
    created_at: str
    elements: tuple[ArchitectureElement, ...] = ()
    relationships: tuple[ArchitectureRelationship, ...] = ()
    candidate_proposals: tuple[CandidateProposal, ...] = ()
    review_decisions: tuple[ReviewDecision, ...] = ()
    validation_findings: tuple[ValidationFinding, ...] = ()
    selected_view_ids: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION
    snapshot_id: str = ""

    def __post_init__(self) -> None:
        for field_name, label in (
            ("identity_key", "Snapshot identity_key"),
            ("project_id", "Proje kimliği"),
            ("name", "Snapshot adı"),
            ("framework_profile_id", "Snapshot profil kimliği"),
            ("framework_version", "Snapshot profil sürümü"),
            ("status", "Snapshot durumu"),
            ("schema_version", "Snapshot şema sürümü"),
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), label))
        object.__setattr__(self, "version", _artifact_version(self.version, "Snapshot sürümü"))
        object.__setattr__(
            self,
            "created_at",
            _timezone_timestamp(self.created_at, "Snapshot oluşturma zamanı"),
        )
        if self.status not in SNAPSHOT_STATUSES:
            raise ValueError(f"Desteklenmeyen snapshot durumu: {self.status}")
        if self.status == SNAPSHOT_CONFORMANT:
            raise ValueError(
                "Kart 1 aşamasında normatif bilgi modeli/exchange doğrulayıcısı "
                "bulunmadığı için 'Uyumlu' durumu verilemez."
            )

        elements = tuple(
            item if isinstance(item, ArchitectureElement) else ArchitectureElement.from_dict(item)
            for item in self.elements
        )
        relationships = tuple(
            item if isinstance(item, ArchitectureRelationship)
            else ArchitectureRelationship.from_dict(item)
            for item in self.relationships
        )
        proposals = tuple(
            item if isinstance(item, CandidateProposal) else CandidateProposal.from_dict(item)
            for item in self.candidate_proposals
        )
        decisions = tuple(
            item if isinstance(item, ReviewDecision) else ReviewDecision.from_dict(item)
            for item in self.review_decisions
        )
        findings = tuple(
            item if isinstance(item, ValidationFinding) else ValidationFinding.from_dict(item)
            for item in self.validation_findings
        )
        for field_name, values, id_name in (
            ("elements", elements, "stable_id"),
            ("relationships", relationships, "stable_id"),
            ("candidate_proposals", proposals, "proposal_id"),
            ("review_decisions", decisions, "decision_id"),
            ("validation_findings", findings, "finding_id"),
        ):
            identifiers = [getattr(item, id_name) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"Snapshot {field_name} içinde yinelenen kararlı kimlik var.")
            object.__setattr__(self, field_name, values)

        all_record_ids = [
            *(item.stable_id for item in elements),
            *(item.stable_id for item in relationships),
            *(item.proposal_id for item in proposals),
            *(item.decision_id for item in decisions),
            *(item.finding_id for item in findings),
        ]
        if len(all_record_ids) != len(set(all_record_ids)):
            raise ValueError("Snapshot kayıt türleri arasında yinelenen kararlı kimlik var.")

        selected_view_ids = _text_tuple(self.selected_view_ids)
        object.__setattr__(self, "selected_view_ids", selected_view_ids)
        identifier = _clean(self.snapshot_id) or stable_id_for("ARCH-SNAPSHOT", {
            "project_id": self.project_id,
            "profile": self.framework_profile_id,
            "identity_key": self.identity_key,
        })

        element_ids = {item.stable_id for item in elements}
        relationship_ids = {item.stable_id for item in relationships}
        for item in elements:
            if item.framework_profile_id != self.framework_profile_id:
                raise ValueError("Mimari öğe snapshot profiliyle uyuşmuyor.")
        for relationship in relationships:
            if relationship.framework_profile_id != self.framework_profile_id:
                raise ValueError("Mimari ilişki snapshot profiliyle uyuşmuyor.")
            if relationship.source_element_id not in element_ids:
                raise ValueError(f"Mimari ilişki kaynak öğesi snapshot'ta yok: {relationship.source_element_id}")
            if relationship.target_element_id not in element_ids:
                raise ValueError(f"Mimari ilişki hedef öğesi snapshot'ta yok: {relationship.target_element_id}")

        target_registry = element_ids | relationship_ids
        for proposal in proposals:
            if proposal.framework_profile_id != self.framework_profile_id:
                raise ValueError("Aday öneri snapshot profiliyle uyuşmuyor.")
            if proposal.target_stable_id and proposal.target_stable_id not in target_registry:
                raise ValueError(
                    f"Aday önerinin hedefi snapshot'ta yok: {proposal.target_stable_id}"
                )
            if proposal.proposal_type == "relationship":
                if proposal.source_element_id not in element_ids:
                    raise ValueError(
                        "İlişki adayının kaynak öğesi snapshot'ta yok: "
                        + proposal.source_element_id
                    )
                if proposal.target_element_id not in element_ids:
                    raise ValueError(
                        "İlişki adayının hedef öğesi snapshot'ta yok: "
                        + proposal.target_element_id
                    )

        proposal_by_id = {item.proposal_id: item for item in proposals}
        decisions_by_candidate: dict[str, ReviewDecision] = {}
        decision_by_id = {item.decision_id: item for item in decisions}
        for decision in decisions:
            proposal = proposal_by_id.get(decision.candidate_id)
            if proposal is None:
                raise ValueError(f"İnceleme kararının adayı snapshot'ta yok: {decision.candidate_id}")
            if decision.candidate_id in decisions_by_candidate:
                raise ValueError("Aynı aday için birden fazla etkin inceleme kararı bulunamaz.")
            decisions_by_candidate[decision.candidate_id] = decision
            if decision.candidate_digest != proposal_digest(proposal):
                raise ValueError("Aday onaydan sonra değişmiş; inceleme kararı geçersiz.")

        evidence_registry: dict[str, dict[str, Any]] = {}
        for owner in (*elements, *relationships, *proposals):
            for evidence in owner.evidence_links:
                payload = evidence.to_dict()
                previous = evidence_registry.setdefault(evidence.evidence_id, payload)
                if previous != payload:
                    raise ValueError("Aynı kanıt kimliği farklı içerikle kullanılamaz.")

        for item in (*elements, *relationships):
            if not item.source_proposal_id and not item.approval_decision_id:
                continue
            decision = decision_by_id.get(item.approval_decision_id)
            if decision is None:
                raise ValueError("Kanonik kaydın kullanıcı onay kararı snapshot'ta yok.")
            if decision.decision != DECISION_ACCEPT or decision.actor_type != ACTOR_USER:
                raise ValueError("Kanonik kayıt yalnız açık kullanıcı kabul kararıyla onaylanabilir.")
            proposal = proposal_by_id[decision.candidate_id]
            if proposal.proposal_id != item.source_proposal_id:
                raise ValueError("Kanonik kayıt onaylanan adaydan farklı bir kaynak adaya bağlı.")
            if item.derivation_kind != proposal.proposal_origin:
                raise ValueError("Kanonik kayıt türetim türü onaylanan aday kökeniyle uyuşmuyor.")
            if item.source_requirement_ids != proposal.source_requirement_ids:
                raise ValueError("Kanonik kayıt kaynak gereksinimleri onaylanan adayla uyuşmuyor.")
            if item.evidence_text != proposal.evidence_text:
                raise ValueError("Kanonik kayıt kanıt metni onaylanan adayla uyuşmuyor.")
            if item.confidence_score != proposal.confidence_score:
                raise ValueError("Kanonik kayıt güven puanı onaylanan adayla uyuşmuyor.")
            if {link.evidence_id for link in item.evidence_links} != {
                link.evidence_id for link in proposal.evidence_links
            }:
                raise ValueError("Kanonik kayıt kanıt bağları onaylanan adayla uyuşmuyor.")
            if proposal.target_stable_id and proposal.target_stable_id != item.stable_id:
                raise ValueError("Onay kararı farklı bir kanonik hedefe aittir.")
            expected_type = "element" if isinstance(item, ArchitectureElement) else "relationship"
            if proposal.proposal_type != expected_type:
                raise ValueError("Kanonik kayıt türü onaylanan aday türüyle uyuşmuyor.")
            expected_payload = {
                "identity_key": item.identity_key,
                "name": item.name,
                "description": item.description,
            }
            if isinstance(item, ArchitectureElement):
                expected_payload["element_type"] = item.element_type
            else:
                expected_payload["relationship_type"] = item.relationship_type
                if proposal.source_element_id != item.source_element_id:
                    raise ValueError("Kanonik ilişki kaynak ucu onaylanan adayla uyuşmuyor.")
                if proposal.target_element_id != item.target_element_id:
                    raise ValueError("Kanonik ilişki hedef ucu onaylanan adayla uyuşmuyor.")
            for key, value in expected_payload.items():
                if proposal.proposed_payload.get(key) != value:
                    raise ValueError(
                        f"Kanonik kayıt alanı onaylanan adayla uyuşmuyor: {key}"
                    )

        known_finding_targets = (
            target_registry
            | set(proposal_by_id)
            | set(decision_by_id)
            | {identifier, self.project_id}
        )
        selected_views_casefold = {item.casefold() for item in selected_view_ids}
        for finding in findings:
            if finding.target_id and finding.target_id not in known_finding_targets:
                raise ValueError(f"Doğrulama bulgusu hedefi snapshot'ta yok: {finding.target_id}")
            missing_evidence_ids = [
                evidence_id
                for evidence_id in finding.evidence_ids
                if evidence_id not in evidence_registry
            ]
            if missing_evidence_ids:
                raise ValueError(
                    "Doğrulama bulgusunun kanıt bağı snapshot'ta yok: "
                    + ", ".join(missing_evidence_ids)
                )
            if finding.view_id and finding.view_id.casefold() not in selected_views_casefold:
                raise ValueError(
                    f"Doğrulama bulgusu seçilmemiş görünüme bağlı: {finding.view_id}"
                )

        if self.status == SNAPSHOT_ALIGNED:
            raise ValueError(
                "Kart 1 aşamasında profil/görünüm içerik doğrulayıcısı bulunmadığı "
                "için 'Çerçeveyle hizalı' durumu verilemez."
            )

        object.__setattr__(self, "snapshot_id", identifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "identity_key": self.identity_key,
            "project_id": self.project_id,
            "name": self.name,
            "framework_profile_id": self.framework_profile_id,
            "framework_version": self.framework_version,
            "version": self.version,
            "status": self.status,
            "created_at": self.created_at,
            "elements": [item.to_dict() for item in self.elements],
            "relationships": [item.to_dict() for item in self.relationships],
            "candidate_proposals": [item.to_dict() for item in self.candidate_proposals],
            "review_decisions": [item.to_dict() for item in self.review_decisions],
            "validation_findings": [item.to_dict() for item in self.validation_findings],
            "selected_view_ids": list(self.selected_view_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArchitectureSnapshot":
        if not isinstance(raw, Mapping):
            raise ValueError("Mimari snapshot JSON nesnesi olmalıdır.")
        return cls(
            identity_key=raw.get("identity_key", ""),
            project_id=raw.get("project_id", ""),
            name=raw.get("name", ""),
            framework_profile_id=raw.get("framework_profile_id", ""),
            framework_version=raw.get("framework_version", ""),
            version=raw.get("version", ""),
            status=raw.get("status", ""),
            created_at=raw.get("created_at", ""),
            elements=raw.get("elements", ()),
            relationships=raw.get("relationships", ()),
            candidate_proposals=raw.get("candidate_proposals", ()),
            review_decisions=raw.get("review_decisions", ()),
            validation_findings=raw.get("validation_findings", ()),
            selected_view_ids=raw.get("selected_view_ids", ()),
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            snapshot_id=raw.get("snapshot_id", ""),
        )


__all__ = [
    "ACTOR_IMPORTER", "ACTOR_MODEL", "ACTOR_RULE", "ACTOR_USER",
    "ArchitectureElement", "ArchitectureRelationship", "ArchitectureSnapshot",
    "CandidateProposal", "DECISION_ACCEPT", "DECISION_DEFER", "DECISION_EDIT",
    "DECISION_REJECT", "DERIVATION_DETERMINISTIC", "DERIVATION_DIRECT",
    "DERIVATION_MODEL_SUGGESTION", "DERIVATION_USER_SUPPLIED", "EvidenceLink",
    "FrameworkProfile", "REVIEW_APPROVED", "REVIEW_DEFERRED", "REVIEW_EDITED",
    "REVIEW_PENDING", "REVIEW_REJECTED", "ReviewDecision", "SCHEMA_VERSION",
    "SNAPSHOT_ALIGNED", "SNAPSHOT_CONFORMANT", "SNAPSHOT_DRAFT",
    "ValidationFinding", "ViewDefinition", "evidence_fingerprint_for",
    "proposal_digest", "stable_id_for",
]
