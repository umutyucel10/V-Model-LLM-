# -*- coding: utf-8 -*-
"""Gereksinimlerden kanıta bağlı mimari adaylar çıkarır.

Kart 2 sınırı bilinçli olarak dardır: girişteki ``flat_data`` ve mevcut
izlenebilirlik raporu yalnız okunur, yalnız TID/SGD/STT kayıtları işlenir ve
çıktı her zaman :class:`~mimari_cerceve_model.CandidateProposal` olur. Bu
modül kanonik mimariyi, kullanıcı kararlarını veya kaynak kayıtlarını yazmaz.

Gemma bu kartta çağrılmaz. ``candidate_from_strict_json`` gelecekteki model
adaptörü için katı, izin listeli bir kapıdır; model metnini kaynak kanıtı
saymaz ve adayın kendisini onaylamasına izin vermez.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence
import unicodedata

from etki_analizi_izlenebilirlik import (
    DOCUMENT_TYPE_DEFINITIONS,
    extract_technical_parameters,
    normalize_identifier,
)
from mimari_cerceve_katalog import get_framework_profile
from mimari_cerceve_model import (
    CandidateProposal,
    DERIVATION_DETERMINISTIC,
    DERIVATION_DIRECT,
    DERIVATION_MODEL_SUGGESTION,
    EvidenceLink,
    REVIEW_PENDING,
    DECISION_DEFER,
    evidence_fingerprint_for,
    stable_id_for,
)


SCHEMA_VERSION = "1.0"
PRODUCER = "mimari_cerceve_cikarim"
PRODUCER_VERSION = "1.0"
SUPPORTED_REQUIREMENT_TYPES = frozenset({"TID", "SGD", "STT"})

_NO_PARENT = frozenset({"", "yok", "none", "null", "-", "genel", "tid-genel", "sgd", "asg"})
# Taşınabilir kaynak adları. Her giriş (gövde, ek alternatifleri) çiftidir;
# Türkçe iyelik/belirtme ekleri açıkça listelenir, serbest sonek kabul edilmez.
# Yeni gövde eklerken tekil ve çoğul biçimleri birlikte yazın.
_FLOW_STEM_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("veri", r"(?:si|sini|yi|nin|ler|leri|lerini|lerin)?"),
    ("mesaj", r"(?:ı|ını|i|ini|ın|lar|ları|larını|ların)?"),
    ("enerji", r"(?:si|sini|yi|nin)?"),
    ("malzeme", r"(?:si|sini|yi|nin|ler|leri|lerini)?"),
    ("akış", r"(?:ı|ını|ın|lar|ları|larını)?"),
    ("bilgi", r"(?:si|sini|yi|nin|ler|leri|lerini|lerin)?"),
    ("sinyal", r"(?:i|ini|in|ler|leri|lerini|lerin)?"),
    ("komut", r"(?:u|unu|un|lar|ları|larını|ların)?"),
    ("sonuç", r"(?:lar|ları|larını|ların)?"),
    ("sonuc", r"(?:u|unu|un)"),
    ("rapor", r"(?:u|unu|un|lar|ları|larını|ların)?"),
    ("ölçüm", r"(?:ü|ünü|ün|ler|leri|lerini|lerin)?"),
    ("kayıt", r"(?:lar|ları|larını|ların)?"),
    ("kayd", r"(?:ı|ını|ın)"),
    ("görüntü", r"(?:sü|sünü|yü|nün|ler|leri|lerini|lerin)?"),
    ("parametre", r"(?:si|sini|yi|nin|ler|leri|lerini|lerin)?"),
)
_FLOW_WORD_RE = re.compile(
    r"\b(?:" + "|".join(
        f"{stem}{suffix}" for stem, suffix in _FLOW_STEM_SUFFIXES
    ) + r")\b",
    re.IGNORECASE,
)
_SEND_RE = re.compile(r"\b(?:gönder\w*|ilet\w*|yayınla\w*|aktar\w*)\b", re.IGNORECASE)
_RECEIVE_RE = re.compile(r"\b(?:alır\w*|almalı\w*|kabul\s+eder\w*|karşılar\w*)\b", re.IGNORECASE)
_INTERFACE_RE = re.compile(r"\b(?:arayüz(?:ü|ünü|ün)?|interface|port(?:u|unu)?)\b", re.IGNORECASE)
_PROTOCOL_RE = re.compile(r"\b(?:protokol\w*|protocol\w*)\b", re.IGNORECASE)
_CONNECTION_RE = re.compile(r"\b(?:bağlan\w*|bağlantı\w*|üzerinden|arasında)\b", re.IGNORECASE)
_LIMIT_RE = re.compile(
    r"\b(?:en\s+az|en\s+fazla|asgari|azami|minimum|maksimum|aşma\w*|"
    r"geçme\w*|altında|üstünde|içinde|arasında|eşit|tolerans)\b|[<>≤≥±]",
    re.IGNORECASE,
)
_ANY_NUMBER_RE = re.compile(r"(?<![\w-])[+-]?\d+(?:[.,]\d+)?(?![\w-])")
_SENTENCE_RE = re.compile(r"[^.!?;\r\n]+[.!?;]?", re.UNICODE)
_WORD_RE = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü_-]+", re.UNICODE)

# Ad olduğu ancak kaynakta açık yazıldığı durumda kabul edilen son ekler.
# Büyük/küçük harf duyarlı önek kuralı, "sistem" gibi jenerik kelimeleri
# özel ad sanmamayı amaçlar.
_SYSTEM_NAME_RE = re.compile(
    r"\b(?P<name>"
    r"[A-ZÇĞİÖŞÜ][0-9A-Za-zÇĞİÖŞÜçğıöşü_-]*"
    r"(?:\s+[A-ZÇĞİÖŞÜ][0-9A-Za-zÇĞİÖŞÜçğıöşü_-]*){0,4}"
    r"\s+(?:(?:Alt|alt)\s+)?"
    r"(?:Sistem(?:i)?|sistem(?:i)?|Birim(?:i)?|birim(?:i)?|Ünite(?:si)?|ünite(?:si)?)"
    r")(?=(?:['’][0-9A-Za-zÇĞİÖŞÜçğıöşü]+)?\b)",
)

_MODEL_ELEMENT_TYPES = frozenset({
    "LogicalRequirement", "Measure", "Port", "Protocol", "ResourceConstraint",
    "ResourceFlow", "System",
})
_MODEL_RELATIONSHIP_TYPES = frozenset({
    "connects", "derived_from", "flow_source", "flow_target",
})


class ArchitectureExtractionError(ValueError):
    """Çıkarım girdisi veya kanıt kapısı geçersiz olduğunda yükseltilir."""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ArchitectureExtractionError("Metin alanı string olmalıdır.")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _slug(value: str) -> str:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", _clean(value).casefold())
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^0-9a-zçğıöşü]+", "-", normalized).strip("-")


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ArchitectureExtractionError("Liste alanı list veya tuple olmalıdır.")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class InformationGap:
    """Kaynakta tamamlanamayan bir mimari bilgi ihtiyacı."""

    code: str
    message: str
    source_requirement_id: str = ""
    field_name: str = ""
    evidence_text: str = ""
    version: str = "v0001"
    gap_id: str = ""

    def __post_init__(self) -> None:
        code = _clean(self.code)
        message = _clean(self.message)
        if not code or not message:
            raise ArchitectureExtractionError("Bilgi açığı kodu ve açıklaması boş olamaz.")
        source_id = _clean(self.source_requirement_id).upper()
        field_name = _clean(self.field_name)
        evidence_text = _clean(self.evidence_text)
        version = _clean(self.version)
        if not re.fullmatch(r"v\d{4}", version):
            raise ArchitectureExtractionError("Bilgi açığı sürümü vNNNN biçiminde olmalıdır.")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "source_requirement_id", source_id)
        object.__setattr__(self, "field_name", field_name)
        object.__setattr__(self, "evidence_text", evidence_text)
        object.__setattr__(self, "version", version)
        identifier = _clean(self.gap_id) or stable_id_for("ARCH-GAP", {
            "code": code,
            "source": source_id,
            "field": field_name,
            "evidence": evidence_text,
        })
        object.__setattr__(self, "gap_id", identifier)

    def to_dict(self) -> dict[str, str]:
        return {
            "gap_id": self.gap_id,
            "code": self.code,
            "message": self.message,
            "source_requirement_id": self.source_requirement_id,
            "field_name": self.field_name,
            "evidence_text": self.evidence_text,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "InformationGap":
        if not isinstance(raw, Mapping):
            raise ArchitectureExtractionError("Bilgi açığı JSON nesnesi olmalıdır.")
        return cls(
            code=raw.get("code", ""),
            message=raw.get("message", ""),
            source_requirement_id=raw.get("source_requirement_id", ""),
            field_name=raw.get("field_name", ""),
            evidence_text=raw.get("evidence_text", ""),
            version=raw.get("version", "v0001"),
            gap_id=raw.get("gap_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ArchitectureExtractionResult:
    """Salt-okunur çıkarımın aday ve bilgi açığı zarfı."""

    framework_profile_id: str
    candidates: tuple[CandidateProposal, ...]
    information_gaps: tuple[InformationGap, ...]
    processed_requirement_ids: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION
    model_used: bool = False

    def __post_init__(self) -> None:
        profile = get_framework_profile(_clean(self.framework_profile_id))
        object.__setattr__(self, "framework_profile_id", profile.profile_id)
        candidates = tuple(
            item if isinstance(item, CandidateProposal) else CandidateProposal.from_dict(item)
            for item in _as_tuple(self.candidates)
        )
        gaps = tuple(
            item if isinstance(item, InformationGap) else InformationGap.from_dict(item)
            for item in _as_tuple(self.information_gaps)
        )
        processed = tuple(sorted({
            _clean(item).upper() for item in _as_tuple(self.processed_requirement_ids)
            if _clean(item)
        }))
        if len({item.proposal_id for item in candidates}) != len(candidates):
            raise ArchitectureExtractionError("Çıkarım sonucunda yinelenen aday kimliği var.")
        if len({item.gap_id for item in gaps}) != len(gaps):
            raise ArchitectureExtractionError("Çıkarım sonucunda yinelenen bilgi açığı kimliği var.")
        if any(item.framework_profile_id != profile.profile_id for item in candidates):
            raise ArchitectureExtractionError("Aday profili çıkarım sonucu profiliyle uyuşmuyor.")
        if not isinstance(self.model_used, bool):
            raise ArchitectureExtractionError("model_used boolean olmalıdır.")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "information_gaps", gaps)
        object.__setattr__(self, "processed_requirement_ids", processed)
        object.__setattr__(self, "schema_version", _clean(self.schema_version))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "framework_profile_id": self.framework_profile_id,
            "model_used": self.model_used,
            "processed_requirement_ids": list(self.processed_requirement_ids),
            "candidates": [item.to_dict() for item in self.candidates],
            "information_gaps": [item.to_dict() for item in self.information_gaps],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ArchitectureExtractionResult":
        if not isinstance(raw, Mapping):
            raise ArchitectureExtractionError("Çıkarım sonucu JSON nesnesi olmalıdır.")
        return cls(
            framework_profile_id=raw.get("framework_profile_id", ""),
            candidates=raw.get("candidates", ()),
            information_gaps=raw.get("information_gaps", ()),
            processed_requirement_ids=raw.get("processed_requirement_ids", ()),
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            model_used=raw.get("model_used", False),
        )


@dataclass(frozen=True, slots=True)
class _Requirement:
    requirement_id: str
    record_type: str
    content: str
    bound_to: str
    source_document: str
    source_location: str
    trace_parameters: tuple[Mapping[str, Any], ...]


def _trace_indexes(
    report: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    if not isinstance(report, Mapping):
        raise ArchitectureExtractionError("İzlenebilirlik raporu JSON nesnesi olmalıdır.")
    raw_nodes = report.get("nodes", ())
    raw_edges = report.get("edges", ())
    raw_missing = report.get("missing_information", ())
    if not isinstance(raw_nodes, (list, tuple)) or not isinstance(raw_edges, (list, tuple)):
        raise ArchitectureExtractionError("İzlenebilirlik raporu nodes/edges listeleri içermelidir.")
    nodes: dict[str, Mapping[str, Any]] = {}
    for node in raw_nodes:
        if not isinstance(node, Mapping):
            continue
        identifier = normalize_identifier(node.get("canonical_id") or node.get("id"))
        if identifier:
            nodes.setdefault(identifier, node)
    edges = tuple(item for item in raw_edges if isinstance(item, Mapping))
    missing = tuple(item for item in raw_missing if isinstance(item, Mapping)) if isinstance(raw_missing, (list, tuple)) else ()
    return nodes, edges, missing


def _prepare_requirements(
    flat_data: Mapping[str, Mapping[str, Any]],
    trace_nodes: Mapping[str, Mapping[str, Any]],
    gaps: dict[str, InformationGap],
) -> dict[str, _Requirement]:
    if not isinstance(flat_data, Mapping):
        raise ArchitectureExtractionError("flat_data kimlik anahtarlı bir sözlük olmalıdır.")
    records: dict[str, _Requirement] = {}
    for fallback_id, raw in flat_data.items():
        if not isinstance(raw, Mapping):
            continue
        raw_id = _clean(raw.get("ID") or str(fallback_id))
        requirement_id = normalize_identifier(raw_id)
        record_type = _clean(raw.get("type")).upper()
        if record_type not in SUPPORTED_REQUIREMENT_TYPES:
            continue
        if not requirement_id:
            gap = InformationGap("missing_requirement_id", "Kimliği olmayan gereksinim işlenmedi.")
            gaps.setdefault(gap.gap_id, gap)
            continue
        content = _clean(raw.get("content") or raw.get("description"))
        if not content:
            gap = InformationGap(
                "missing_requirement_text",
                "Gereksinim metni olmadığı için mimari aday üretilemedi.",
                requirement_id,
                "content",
            )
            gaps.setdefault(gap.gap_id, gap)
            continue
        if requirement_id in records:
            gap = InformationGap(
                "duplicate_requirement_id",
                "Aynı kanonik gereksinim kimliği birden fazla kayıtta bulundu.",
                requirement_id,
                "ID",
                content,
            )
            gaps.setdefault(gap.gap_id, gap)
            continue
        trace_node = trace_nodes.get(requirement_id, {})
        trace_text = _clean(trace_node.get("evidence_text") or trace_node.get("description")) if trace_node else ""
        if trace_text and trace_text != content:
            gap = InformationGap(
                "traceability_evidence_mismatch",
                "flat_data metni ile izlenebilirlik düğümü kanıt metni uyuşmuyor; flat_data esas alındı.",
                requirement_id,
                "content",
                content,
            )
            gaps.setdefault(gap.gap_id, gap)
        source_document = (
            _clean(trace_node.get("source_document"))
            if trace_node else ""
        ) or DOCUMENT_TYPE_DEFINITIONS[record_type]["document_title"]
        source_location = (
            _clean(trace_node.get("source_section"))
            if trace_node else ""
        ) or f"flat_data[{requirement_id}].content"
        trace_parameters_raw = trace_node.get("technical_parameters", ()) if trace_node else ()
        trace_parameters = tuple(
            MappingProxyType(dict(item))
            for item in trace_parameters_raw
            if isinstance(item, Mapping)
        ) if isinstance(trace_parameters_raw, (list, tuple)) else ()
        records[requirement_id] = _Requirement(
            requirement_id=requirement_id,
            record_type=record_type,
            content=content,
            bound_to=_clean(raw.get("bound_to") or raw.get("bound") or raw.get("parent_id")),
            source_document=source_document,
            source_location=source_location,
            trace_parameters=trace_parameters,
        )
    return records


def _evidence(
    requirement: _Requirement,
    *,
    field_name: str = "content",
    evidence_text: str | None = None,
) -> EvidenceLink:
    text = requirement.content if evidence_text is None else _clean(evidence_text)
    location = (
        requirement.source_location
        if field_name == "content"
        else f"flat_data[{requirement.requirement_id}].{field_name}"
    )
    return EvidenceLink(
        source_item_id=requirement.requirement_id,
        source_document=requirement.source_document,
        source_location=location,
        evidence_text=text,
        evidence_fingerprint=evidence_fingerprint_for(
            requirement.source_document,
            requirement.requirement_id,
            location,
            text,
        ),
        confidence_score=1.0,
        derivation_kind=DERIVATION_DIRECT,
        producer=PRODUCER,
        producer_version=PRODUCER_VERSION,
    )


def _element_stable_id(profile_id: str, element_type: str, identity_key: str) -> str:
    return stable_id_for("ARCH-ELEMENT", {
        "profile": profile_id,
        "element_type": element_type,
        "identity_key": identity_key,
    })


def _model_endpoint_registry(
    profile_id: str,
    requirements: Sequence[_Requirement],
) -> Mapping[str, str]:
    """Model ilişki uçlarını yalnız deterministik kaynak öğeleriyle sınırlar."""

    endpoints: dict[str, str] = {}
    for requirement in requirements:
        requirement_identity = requirement.requirement_id.casefold()
        endpoints[_element_stable_id(
            profile_id, "LogicalRequirement", requirement_identity,
        )] = "LogicalRequirement"
        for system_name, _, _ in _named_systems(requirement.content):
            endpoints[_element_stable_id(
                profile_id, "System", _slug(system_name),
            )] = "System"
        for interface_name in _interface_names(requirement.content):
            endpoints[_element_stable_id(
                profile_id, "Port", _slug(interface_name),
            )] = "Port"
        for flow_name in _flow_names(requirement.content):
            identity = f"{requirement.requirement_id.casefold()}-{_slug(flow_name)}"
            endpoints[_element_stable_id(
                profile_id, "ResourceFlow", identity,
            )] = "ResourceFlow"
    return MappingProxyType(endpoints)


def _proposal(
    *,
    profile_id: str,
    proposal_type: str,
    identity_key: str,
    name: str,
    entity_type: str,
    description: str,
    rationale: str,
    evidence_links: Sequence[EvidenceLink],
    confidence_score: float = 1.0,
    source_element_id: str = "",
    target_element_id: str = "",
    target_stable_id: str = "",
    proposal_origin: str = DERIVATION_DETERMINISTIC,
) -> CandidateProposal:
    links = tuple({item.evidence_id: item for item in evidence_links}.values())
    if not links:
        raise ArchitectureExtractionError("Aday kaynak kanıtı olmadan üretilemez.")
    type_field = "element_type" if proposal_type == "element" else "relationship_type"
    payload = {
        "identity_key": identity_key,
        "name": name,
        type_field: entity_type,
        "description": description,
    }
    all_evidence_ids = tuple(item.evidence_id for item in links)
    payload_evidence = {key: all_evidence_ids for key in payload}
    try:
        return CandidateProposal(
            identity_key=identity_key,
            framework_profile_id=profile_id,
            proposal_type=proposal_type,
            title=name,
            rationale=rationale,
            proposed_payload=payload,
            source_requirement_ids=tuple(item.source_item_id for item in links),
            evidence_text=links[0].evidence_text,
            confidence_score=confidence_score,
            evidence_links=links,
            payload_evidence_ids=payload_evidence,
            source_element_id=source_element_id,
            target_element_id=target_element_id,
            target_stable_id=target_stable_id,
            proposal_origin=proposal_origin,
            review_status=REVIEW_PENDING,
            initial_decision=DECISION_DEFER,
        )
    except ValueError as error:
        raise ArchitectureExtractionError(str(error)) from error


def _add_candidate(
    candidates: dict[str, CandidateProposal],
    candidate: CandidateProposal,
) -> None:
    previous = candidates.get(candidate.proposal_id)
    if previous is None:
        candidates[candidate.proposal_id] = candidate
        return
    if previous.to_dict() == candidate.to_dict():
        return

    previous_payload = dict(previous.proposed_payload)
    candidate_payload = dict(candidate.proposed_payload)
    previous_description = previous_payload.pop("description", "")
    candidate_description = candidate_payload.pop("description", "")
    same_semantic_candidate = (
        previous_payload == candidate_payload
        and previous.framework_profile_id == candidate.framework_profile_id
        and previous.proposal_type == candidate.proposal_type
        and previous.source_element_id == candidate.source_element_id
        and previous.target_element_id == candidate.target_element_id
        and previous.target_stable_id == candidate.target_stable_id
        and previous.proposal_origin == candidate.proposal_origin
        and previous.rationale == candidate.rationale
    )
    if not same_semantic_candidate:
        raise ArchitectureExtractionError(
            "Farklı mimari adaylar aynı kararlı kimliği üretti: "
            f"{candidate.proposal_id}"
        )

    # Aynı gerçek varlığın birden çok gereksinimde geçmesi olağandır. Kaynak
    # kanıtları sessizce düşürmek yerine tek aday zarfında, sıralamadan bağımsız
    # ve birebir metinlerle birleştiririz. Kullanıcı yine bu birleşik adayı
    # açıkça inceleyip onaylar.
    links = tuple(sorted(
        {item.evidence_id: item for item in (
            *previous.evidence_links, *candidate.evidence_links,
        )}.values(),
        key=lambda item: (item.source_item_id, item.evidence_id),
    ))
    merged_payload = dict(previous_payload)
    # Description tek bir birebir kaynak kesiti olarak kalır; diğer kesitler
    # evidence_links içinde kayıpsız tutulur. Böylece farklı cümleleri yeni bir
    # teknik iddiaya dönüştürmeden çoklu kanıt korunur.
    merged_payload["description"] = links[0].evidence_text
    evidence_ids = tuple(item.evidence_id for item in links)
    candidates[candidate.proposal_id] = CandidateProposal(
        identity_key=previous.identity_key,
        framework_profile_id=previous.framework_profile_id,
        proposal_type=previous.proposal_type,
        title=previous.title,
        rationale=previous.rationale,
        proposed_payload=merged_payload,
        source_requirement_ids=tuple(sorted({
            *previous.source_requirement_ids,
            *candidate.source_requirement_ids,
        })),
        evidence_text=links[0].evidence_text,
        confidence_score=min(previous.confidence_score, candidate.confidence_score),
        evidence_links=links,
        payload_evidence_ids={key: evidence_ids for key in merged_payload},
        source_element_id=previous.source_element_id,
        target_element_id=previous.target_element_id,
        target_stable_id=previous.target_stable_id,
        proposal_origin=previous.proposal_origin,
        review_status=REVIEW_PENDING,
        initial_decision=DECISION_DEFER,
        version=previous.version,
        proposal_id=previous.proposal_id,
    )


def _named_systems(text: str) -> tuple[tuple[str, int, int], ...]:
    found: list[tuple[str, int, int]] = []
    for match in _SYSTEM_NAME_RE.finditer(text):
        name = _clean(match.group("name"))
        if name.casefold() in {"alt sistem", "ana sistem", "bir sistem"}:
            continue
        found.append((name, match.start("name"), match.end("name")))
    return tuple(found)


def _flow_names(text: str) -> tuple[str, ...]:
    words = tuple(_WORD_RE.finditer(text))
    # "Veri Tabanı Yönetim Sistemi" gibi özel adların içindeki akış sözcüğü
    # taşınan kaynak değildir. Sistem adının kapsadığı eşleşmeler elenmezse
    # uçsuz bir akış öğesi üretilir ve bu tüm görünümü engeller.
    system_spans = tuple((start, end) for _name, start, end in _named_systems(text))
    names: list[str] = []
    for match in _FLOW_WORD_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in system_spans):
            continue
        previous = next((item for item in reversed(words) if item.end() <= match.start()), None)
        start = match.start()
        if previous is not None and previous.group(0).casefold() not in {
            "sistem", "sistemi", "birim", "birimi", "ile", "ve", "bir", "üzerinden",
        }:
            start = previous.start()
        name = _clean(text[start:match.end()])
        if name not in names:
            names.append(name)
    return tuple(names)


def _interface_names(text: str) -> tuple[str, ...]:
    words = tuple(_WORD_RE.finditer(text))
    names: list[str] = []
    for match in _INTERFACE_RE.finditer(text):
        previous = next((item for item in reversed(words) if item.end() <= match.start()), None)
        if previous is None or previous.group(0).casefold() in {
            "bir", "bu", "ile", "ve", "sistem", "sistemi", "üzerinden",
        }:
            continue
        name = _clean(text[previous.start():match.end()])
        if name.casefold() not in {"alt sistem arayüzü", "sistem arayüzü"} and name not in names:
            names.append(name)
    return tuple(names)


def _protocol_names(text: str) -> tuple[str, ...]:
    """Kaynakta açık yazılan protokol ifadesi ve kanonik adını döndürür."""

    words = tuple(_WORD_RE.finditer(text))
    names: list[str] = []
    for match in _PROTOCOL_RE.finditer(text):
        previous = next((item for item in reversed(words) if item.end() <= match.start()), None)
        if previous is None or previous.group(0).casefold() in {
            "bir", "bu", "ile", "ve", "kullanılan", "uygulanan",
        }:
            continue
        full_name = _clean(text[previous.start():match.end()])
        canonical_name = _clean(previous.group(0))
        for name in (full_name, canonical_name):
            if name and name not in names:
                names.append(name)
    return tuple(names)


def _sentence_containing(text: str, position: int) -> tuple[str, int]:
    for match in _SENTENCE_RE.finditer(text):
        if match.start() <= position < match.end():
            # Konumları kaynak metne göre koru. Boşlukları burada
            # normalleştirmek, cümle sonundaki sistemleri yanlışça dışarıda
            # bırakabilir.
            return match.group(0), match.start()
    return text, 0


def _system_case_marker(text: str, end: int) -> str:
    """Açık Türkçe yön ekini sistem adının hemen ardından okur."""

    tail = text[end:end + 16]
    prefix = r"^\s*(?:['’]\s*)?"
    if re.match(prefix + r"n?[dt][ae]n(?=$|[^\w])", tail, re.IGNORECASE):
        return "source"
    if re.match(prefix + r"(?:n?[ae]|y[ae])(?=$|[^\w])", tail, re.IGNORECASE):
        return "target"
    return ""


def _explicit_flow_endpoints(
    text: str,
    systems: Sequence[tuple[str, int, int]],
    *,
    send: bool,
    receive: bool,
) -> tuple[str, str] | None:
    """Yalnızca iki ucu da dilbilgisel olarak belirli akışı kabul eder."""

    if send == receive or len(systems) != 2:
        return None
    marked = tuple((name, _system_case_marker(text, end)) for name, _start, end in systems)
    if send:
        targets = tuple(name for name, marker in marked if marker == "target")
        sources = tuple(name for name, marker in marked if marker == "")
    else:
        sources = tuple(name for name, marker in marked if marker == "source")
        targets = tuple(name for name, marker in marked if marker == "")
    if len(sources) != 1 or len(targets) != 1 or sources[0] == targets[0]:
        return None
    return sources[0], targets[0]


def _flow_endpoint_map(
    text: str,
    systems: Sequence[tuple[str, int, int]],
    flow_names: Sequence[str],
) -> tuple[dict[str, tuple[str, str]], tuple[str, ...], tuple[str, ...]]:
    """Akış adlarını, aynı cümlede çözümlenen uçlarına eşler.

    Uçları çözümlenemeyen akış için mimari öğe üretilmez: kimsenin
    göndermediği/almadığı bir 'kaynak akışı' viewpoint anlamında akış değildir
    ve boşta uç olarak tüm görünümü engeller. Bu adlar bilgi açığı olarak
    raporlanmak üzere ayrı döndürülür.
    """

    resolved: dict[str, tuple[str, str]] = {}
    without_direction: list[str] = []
    ambiguous: list[str] = []
    for flow_name in flow_names:
        flow_position = text.find(flow_name)
        sentence, sentence_start = _sentence_containing(text, max(flow_position, 0))
        local_systems = tuple(
            (name, start, end)
            for name, start, end in systems
            if sentence_start <= start < sentence_start + len(sentence)
        )
        send = bool(_SEND_RE.search(sentence))
        receive = bool(_RECEIVE_RE.search(sentence))
        if not (send or receive):
            without_direction.append(flow_name)
            continue
        endpoints = _explicit_flow_endpoints(
            text, local_systems, send=send, receive=receive,
        )
        if endpoints is None:
            ambiguous.append(flow_name)
            continue
        resolved[flow_name] = endpoints
    return resolved, tuple(without_direction), tuple(ambiguous)


def _same_explicit_name(candidate: str, allowed_names: Sequence[str]) -> bool:
    """Tam kaynak ifadesini yalnızca izinli deterministik normalizasyonla eşler."""

    cleaned = _clean(candidate)
    candidate_slug = _slug(cleaned)
    return bool(candidate_slug) and any(
        cleaned.casefold() == _clean(allowed).casefold()
        or candidate_slug == _slug(allowed)
        for allowed in allowed_names
        if _clean(allowed)
    )


def _strict_element_names(
    entity_type: str,
    requirements: Sequence[_Requirement],
) -> tuple[str, ...]:
    names: list[str] = []
    for requirement in requirements:
        if entity_type == "LogicalRequirement":
            values = (requirement.requirement_id,)
        elif entity_type == "System":
            values = tuple(name for name, _start, _end in _named_systems(requirement.content))
        elif entity_type == "Port":
            values = _interface_names(requirement.content)
        elif entity_type == "Protocol":
            values = _protocol_names(requirement.content)
        elif entity_type in {"Measure", "ResourceConstraint"}:
            values = tuple(
                _clean(item.get("raw"))
                for item in extract_technical_parameters(requirement.content)
                if _clean(item.get("raw"))
            )
        elif entity_type == "ResourceFlow":
            values = _flow_names(requirement.content)
        else:
            values = ()
        for value in values:
            if value and value not in names:
                names.append(value)
    return tuple(names)


def _model_endpoint_names(
    profile_id: str,
    requirements: Sequence[_Requirement],
) -> Mapping[str, str]:
    names: dict[str, str] = {}
    for requirement in requirements:
        requirement_identity = requirement.requirement_id.casefold()
        names[_element_stable_id(
            profile_id, "LogicalRequirement", requirement_identity,
        )] = requirement.requirement_id
        for system_name, _start, _end in _named_systems(requirement.content):
            names[_element_stable_id(
                profile_id, "System", _slug(system_name),
            )] = system_name
        for interface_name in _interface_names(requirement.content):
            names[_element_stable_id(
                profile_id, "Port", _slug(interface_name),
            )] = interface_name
        for flow_name in _flow_names(requirement.content):
            identity = f"{requirement.requirement_id.casefold()}-{_slug(flow_name)}"
            names[_element_stable_id(
                profile_id, "ResourceFlow", identity,
            )] = flow_name
    return MappingProxyType(names)


def _trace_has_bound(
    edges: Sequence[Mapping[str, Any]], child_id: str, parent_id: str,
) -> bool:
    return any(
        normalize_identifier(edge.get("source_id")) == child_id
        and normalize_identifier(edge.get("target_id")) == parent_id
        and _clean(edge.get("derivation_method")) == "structured_bound_to"
        for edge in edges
    )


def extract_architecture_candidates(
    flat_data: Mapping[str, Mapping[str, Any]],
    traceability_report: Mapping[str, Any],
    *,
    framework_profile_id: str = "dodaf",
) -> ArchitectureExtractionResult:
    """TID/SGD/STT girdilerinden deterministik, onaysız adaylar üretir.

    Fonksiyon girdileri değiştirmez ve dosya yazmaz. Çıktıların tümü adaydır;
    bilgi tamamlanamadığında değer uydurmak yerine ``information_gaps`` kaydı
    oluşturulur.
    """

    profile = get_framework_profile(_clean(framework_profile_id))
    trace_nodes, trace_edges, trace_missing = _trace_indexes(traceability_report)
    gaps: dict[str, InformationGap] = {}
    requirements = _prepare_requirements(flat_data, trace_nodes, gaps)
    candidates: dict[str, CandidateProposal] = {}

    # İzlenebilirlik raporundaki mevcut açıkları yeni kaynak gerçeği saymadan
    # ayrı eksik bilgi kayıtlarına taşırız.
    for raw_gap in trace_missing:
        item_id = normalize_identifier(raw_gap.get("item_id"))
        if item_id and item_id not in requirements:
            continue
        message = _clean(raw_gap.get("message"))
        if not message:
            continue
        gap = InformationGap(
            code=f"traceability_{_clean(raw_gap.get('type')) or 'missing_information'}",
            message=message,
            source_requirement_id=item_id,
            field_name="traceability_report",
        )
        gaps.setdefault(gap.gap_id, gap)

    # Gereksinim öğeleri ve açık bound_to hiyerarşisi.
    for requirement in requirements.values():
        content_evidence = _evidence(requirement)
        req_identity = requirement.requirement_id.casefold()
        _add_candidate(candidates, _proposal(
            profile_id=profile.profile_id,
            proposal_type="element",
            identity_key=req_identity,
            name=requirement.requirement_id,
            entity_type="LogicalRequirement",
            description=requirement.content,
            rationale="Kaynak gereksinim kimliği ve metni doğrudan adaylaştırıldı.",
            evidence_links=(content_evidence,),
        ))

        parent_id = normalize_identifier(requirement.bound_to)
        if parent_id.casefold() in _NO_PARENT:
            parent_id = ""
        if parent_id:
            parent = requirements.get(parent_id)
            if parent is None:
                gap = InformationGap(
                    "missing_bound_target",
                    f"bound_to hedef gereksinimi bulunamadı: {requirement.bound_to}.",
                    requirement.requirement_id,
                    "bound_to",
                    requirement.bound_to,
                )
                gaps.setdefault(gap.gap_id, gap)
            else:
                if trace_edges and not _trace_has_bound(trace_edges, requirement.requirement_id, parent_id):
                    gap = InformationGap(
                        "traceability_bound_missing",
                        "flat_data bound_to bağlantısı izlenebilirlik raporunda structured_bound_to olarak bulunamadı.",
                        requirement.requirement_id,
                        "bound_to",
                        requirement.bound_to,
                    )
                    gaps.setdefault(gap.gap_id, gap)
                bound_evidence = _evidence(
                    requirement, field_name="bound_to", evidence_text=requirement.bound_to,
                )
                parent_evidence = _evidence(parent)
                child_element_id = _element_stable_id(
                    profile.profile_id, "LogicalRequirement", req_identity,
                )
                parent_identity = parent.requirement_id.casefold()
                parent_element_id = _element_stable_id(
                    profile.profile_id, "LogicalRequirement", parent_identity,
                )
                relation_identity = f"{requirement.requirement_id.casefold()}-{parent.requirement_id.casefold()}"
                _add_candidate(candidates, _proposal(
                    profile_id=profile.profile_id,
                    proposal_type="relationship",
                    identity_key=relation_identity,
                    name=f"{requirement.requirement_id} {parent.requirement_id}",
                    entity_type="derived_from",
                    description=requirement.bound_to,
                    rationale="Açık bound_to alanı gereksinim hiyerarşisi adayı olarak eşlendi.",
                    evidence_links=(bound_evidence, parent_evidence),
                    source_element_id=child_element_id,
                    target_element_id=parent_element_id,
                ))

    # Ölçüler, kısıtlar, açık sistem/ad/arayüz/akış ifadeleri.
    for requirement in requirements.values():
        evidence = _evidence(requirement)
        parameters = extract_technical_parameters(requirement.content)
        trace_raws = {
            _clean(item.get("raw")).casefold()
            for item in requirement.trace_parameters
            if _clean(item.get("raw"))
        }
        source_raws = {_clean(item.get("raw")).casefold() for item in parameters}
        for trace_raw in sorted(trace_raws - source_raws):
            gap = InformationGap(
                "traceability_parameter_conflict",
                "İzlenebilirlik parametresi kaynak gereksinim metninde birebir bulunamadı; adaylaştırılmadı.",
                requirement.requirement_id,
                "technical_parameters",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)
        if _ANY_NUMBER_RE.search(requirement.content) and not parameters:
            gap = InformationGap(
                "measurement_unit_missing",
                "Ölçülebilir sayı bulundu ancak kaynakta desteklenen birim açık değil.",
                requirement.requirement_id,
                "content",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)
        for parameter in parameters:
            raw_value = _clean(parameter.get("raw"))
            base_identity = f"{requirement.requirement_id.casefold()}-{_slug(raw_value)}"
            _add_candidate(candidates, _proposal(
                profile_id=profile.profile_id,
                proposal_type="element",
                identity_key=base_identity,
                name=raw_value,
                entity_type="Measure",
                description=requirement.content,
                rationale="Kaynak metindeki sayı-birim çifti ölçü adayı olarak çıkarıldı.",
                evidence_links=(evidence,),
            ))
            constraint_identity = f"{base_identity}-{requirement.requirement_id.casefold()}"
            _add_candidate(candidates, _proposal(
                profile_id=profile.profile_id,
                proposal_type="element",
                identity_key=constraint_identity,
                name=raw_value,
                entity_type="ResourceConstraint",
                description=requirement.content,
                rationale=(
                    "Kaynak metindeki sınır ifadesi kısıt adayı olarak çıkarıldı."
                    if _LIMIT_RE.search(requirement.content)
                    else "Gereksinimdeki açık sayı-birim değeri kullanıcı incelemeli kısıt adayıdır."
                ),
                evidence_links=(evidence,),
                confidence_score=1.0 if _LIMIT_RE.search(requirement.content) else 0.9,
            ))

        systems = _named_systems(requirement.content)
        system_ids: dict[str, str] = {}
        logical_system_ids: dict[str, str] = {}
        for system_name, _, _ in systems:
            identity = _slug(system_name)
            system_ids[system_name] = _element_stable_id(profile.profile_id, "System", identity)
            _add_candidate(candidates, _proposal(
                profile_id=profile.profile_id,
                proposal_type="element",
                identity_key=identity,
                name=system_name,
                entity_type="System",
                description=requirement.content,
                rationale="Kaynakta özel adı açıkça yazılmış sistem/alt sistem adayıdır.",
                evidence_links=(evidence,),
            ))
            if profile.profile_id == "naf":
                logical_system_ids[system_name] = _element_stable_id(
                    profile.profile_id, "LogicalActiveResource", identity,
                )
                _add_candidate(candidates, _proposal(
                    profile_id=profile.profile_id,
                    proposal_type="element",
                    identity_key=identity,
                    name=system_name,
                    entity_type="LogicalActiveResource",
                    description=requirement.content,
                    rationale=(
                        "Kaynakta adı açık sistem, NAF L3 mantıksal kaynak "
                        "sınıflandırması için kullanıcı onaylı adaydır."
                    ),
                    evidence_links=(evidence,),
                    confidence_score=0.8,
                    target_stable_id=logical_system_ids[system_name],
                ))
        if re.search(r"\b(?:sistem|alt\s+sistem|birim|ünite)\b", requirement.content, re.IGNORECASE) and not systems:
            gap = InformationGap(
                "system_name_missing",
                "Sistem/alt sistem ifadesi var ancak ayırt edici özel ad kaynakta açık değil.",
                requirement.requirement_id,
                "system_name",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)

        interface_names = _interface_names(requirement.content)
        interface_ids: dict[str, str] = {}
        for interface_name in interface_names:
            identity = _slug(interface_name)
            interface_ids[interface_name] = _element_stable_id(profile.profile_id, "Port", identity)
            _add_candidate(candidates, _proposal(
                profile_id=profile.profile_id,
                proposal_type="element",
                identity_key=identity,
                name=interface_name,
                entity_type="Port",
                description=requirement.content,
                rationale="Kaynakta adı açıkça yazılmış arayüz adayıdır.",
                evidence_links=(evidence,),
            ))
        if _INTERFACE_RE.search(requirement.content) and not interface_names:
            gap = InformationGap(
                "interface_name_missing",
                "Arayüz ifadesi var ancak arayüz adı kaynakta açık değil.",
                requirement.requirement_id,
                "interface_name",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)

        detected_flow_names = _flow_names(requirement.content)
        endpoint_map, flows_without_direction, flows_with_ambiguous_ends = (
            _flow_endpoint_map(requirement.content, systems, detected_flow_names)
        )
        # Yalnız iki ucu da çözümlenen akış mimari öğe olur.
        flow_names = tuple(
            name for name in detected_flow_names if name in endpoint_map
        )
        flow_ids: dict[str, str] = {}
        dodaf_flow_ids: dict[str, str] = {}
        logical_interaction_ids: dict[str, str] = {}
        logical_passive_ids: dict[str, str] = {}
        for flow_name in flow_names:
            identity = f"{requirement.requirement_id.casefold()}-{_slug(flow_name)}"
            flow_ids[flow_name] = _element_stable_id(profile.profile_id, "ResourceFlow", identity)
            _add_candidate(candidates, _proposal(
                profile_id=profile.profile_id,
                proposal_type="element",
                identity_key=identity,
                name=flow_name,
                entity_type="ResourceFlow",
                description=requirement.content,
                rationale="Kaynakta açıkça yazılmış veri/mesaj/enerji/malzeme akışı adayıdır.",
                evidence_links=(evidence,),
            ))
            if profile.profile_id == "dodaf":
                dodaf_flow_ids[flow_name] = _element_stable_id(
                    profile.profile_id, "SystemResourceFlow", identity,
                )
                _add_candidate(candidates, _proposal(
                    profile_id=profile.profile_id,
                    proposal_type="element",
                    identity_key=identity,
                    name=flow_name,
                    entity_type="SystemResourceFlow",
                    description=requirement.content,
                    rationale=(
                        "Kaynakta açık veri/mesaj/enerji/malzeme akışı, DoDAF "
                        "sistem kaynak akışı sınıflandırması için kullanıcı onaylı adaydır."
                    ),
                    evidence_links=(evidence,),
                    confidence_score=0.9,
                    target_stable_id=dodaf_flow_ids[flow_name],
                ))
            elif profile.profile_id == "naf":
                logical_interaction_ids[flow_name] = _element_stable_id(
                    profile.profile_id, "LogicalInteraction", identity,
                )
                logical_passive_ids[flow_name] = _element_stable_id(
                    profile.profile_id, "LogicalPassiveResource", identity,
                )
                for element_type, rationale in (
                    (
                        "LogicalInteraction",
                        "Açık yönlü akış, NAF L3 mantıksal etkileşim sınıflandırması için kullanıcı onaylı adaydır.",
                    ),
                    (
                        "LogicalPassiveResource",
                        "Açık mesaj/veri adı, NAF L3 taşınan pasif kaynak sınıflandırması için kullanıcı onaylı adaydır.",
                    ),
                ):
                    _add_candidate(candidates, _proposal(
                        profile_id=profile.profile_id,
                        proposal_type="element",
                        identity_key=identity,
                        name=flow_name,
                        entity_type=element_type,
                        description=requirement.content,
                        rationale=rationale,
                        evidence_links=(evidence,),
                        confidence_score=0.8,
                        target_stable_id=(
                            logical_interaction_ids[flow_name]
                            if element_type == "LogicalInteraction"
                            else logical_passive_ids[flow_name]
                        ),
                    ))

        has_direction_verb = bool(_SEND_RE.search(requirement.content) or _RECEIVE_RE.search(requirement.content))
        if has_direction_verb and not detected_flow_names:
            gap = InformationGap(
                "flow_name_missing",
                "Gönderme/alma ifadesi var ancak taşınan kaynak adı açık değil.",
                requirement.requirement_id,
                "flow_name",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)
        if flows_without_direction:
            gap = InformationGap(
                "flow_direction_missing",
                "Taşınabilir kaynak adı yazılmış ancak gönderme/alma yönü kaynakta "
                "açık değil; uçsuz akış öğesi üretilmedi.",
                requirement.requirement_id,
                "flow_direction",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)
        if flows_with_ambiguous_ends:
            gap = InformationGap(
                "flow_endpoint_missing",
                "Yönlü akış için iki sistem ucu ve kaynak/hedef yön ekleri "
                "aynı kaynak cümlesinde tek anlamlı değil.",
                requirement.requirement_id,
                "flow_endpoints",
                requirement.content,
            )
            gaps.setdefault(gap.gap_id, gap)

        # Uçlar yukarıda çözümlendi; burada yalnız ilişki adayları üretilir.
        for flow_name in flow_names:
            source_name, target_name = endpoint_map[flow_name]
            # DoDAF SV-1/SV-2 uçları profil-adaptörü olan
            # SystemResourceFlow'a bağlanır. Aynı semantiği generic
            # ResourceFlow üzerinde ikinci kez üretmek, kullanıcı yalnız DoDAF
            # adaylarını onayladığında onaysız generic uca dangling ilişki
            # bırakır. ResourceFlow öğesini kanıt kaydı olarak koruyoruz;
            # yalnız DoDAF profilindeki gereksiz generic uç ilişkilerini bastırıyoruz.
            if profile.profile_id != "dodaf":
                flow_id = flow_ids[flow_name]
                relation_pairs = (
                    ("flow_source", flow_id, system_ids[source_name], f"{flow_name} {source_name}"),
                    ("flow_target", flow_id, system_ids[target_name], f"{flow_name} {target_name}"),
                )
                for relationship_type, source_id, target_id, relation_name in relation_pairs:
                    relation_identity = (
                        f"{requirement.requirement_id.casefold()}-{_slug(flow_name)}-"
                        f"{_slug(source_name if relationship_type == 'flow_source' else target_name)}"
                    )
                    _add_candidate(candidates, _proposal(
                        profile_id=profile.profile_id,
                        proposal_type="relationship",
                        identity_key=relation_identity,
                        name=relation_name,
                        entity_type=relationship_type,
                        description=requirement.content,
                        rationale="Aynı kaynak cümlesindeki açık gönderme/alma yönünden çıkarıldı.",
                        evidence_links=(evidence,),
                        source_element_id=source_id,
                        target_element_id=target_id,
                    ))

            if profile.profile_id == "dodaf":
                dodaf_flow_id = dodaf_flow_ids[flow_name]
                dodaf_pairs = (
                    ("flow_source", dodaf_flow_id, system_ids[source_name], f"{flow_name} {source_name}"),
                    ("flow_target", dodaf_flow_id, system_ids[target_name], f"{flow_name} {target_name}"),
                )
                for relationship_type, source_id, target_id, relation_name in dodaf_pairs:
                    _add_candidate(candidates, _proposal(
                        profile_id=profile.profile_id,
                        proposal_type="relationship",
                        identity_key=(
                            f"{requirement.requirement_id.casefold()}-{_slug(flow_name)}-"
                            f"{_slug(source_name if relationship_type == 'flow_source' else target_name)}"
                        ),
                        name=relation_name,
                        entity_type=relationship_type,
                        description=requirement.content,
                        rationale=(
                            "Aynı kaynak cümlesindeki açık yön, DoDAF sistem kaynak akışı "
                            "ucu için kullanıcı onaylı adaydır."
                        ),
                        evidence_links=(evidence,),
                        source_element_id=source_id,
                        target_element_id=target_id,
                        confidence_score=0.9,
                    ))
            elif profile.profile_id == "naf":
                interaction_id = logical_interaction_ids[flow_name]
                naf_pairs = (
                    ("interaction_source", interaction_id, logical_system_ids[source_name], f"{flow_name} {source_name}"),
                    ("interaction_target", interaction_id, logical_system_ids[target_name], f"{flow_name} {target_name}"),
                    ("conveys", interaction_id, logical_passive_ids[flow_name], flow_name),
                )
                for relationship_type, source_id, target_id, relation_name in naf_pairs:
                    identity_suffix = (
                        _slug(source_name)
                        if relationship_type == "interaction_source"
                        else _slug(target_name)
                        if relationship_type == "interaction_target"
                        else _slug(flow_name)
                    )
                    _add_candidate(candidates, _proposal(
                        profile_id=profile.profile_id,
                        proposal_type="relationship",
                        identity_key=(
                            f"{requirement.requirement_id.casefold()}-{_slug(flow_name)}-"
                            f"{identity_suffix}"
                        ),
                        name=relation_name,
                        entity_type=relationship_type,
                        description=requirement.content,
                        rationale=(
                            "Aynı kaynak cümlesindeki açık uç ve taşınan kaynak, NAF L3 "
                            "ilişki sınıflandırması için kullanıcı onaylı adaydır."
                        ),
                        evidence_links=(evidence,),
                        source_element_id=source_id,
                        target_element_id=target_id,
                        confidence_score=0.8,
                    ))

        if interface_names and len(systems) >= 2 and _CONNECTION_RE.search(requirement.content):
            source_name, target_name = systems[0][0], systems[1][0]
            relation_identity = (
                f"{requirement.requirement_id.casefold()}-{_slug(source_name)}-{_slug(target_name)}"
            )
            _add_candidate(candidates, _proposal(
                profile_id=profile.profile_id,
                proposal_type="relationship",
                identity_key=relation_identity,
                name=f"{source_name} {target_name}",
                entity_type="connects",
                description=requirement.content,
                rationale="Aynı kaynak cümlesindeki iki sistem ve açık arayüz/bağlantı ifadesinden çıkarıldı.",
                evidence_links=(evidence,),
                source_element_id=system_ids[source_name],
                target_element_id=system_ids[target_name],
            ))

    ordered_candidates = tuple(sorted(candidates.values(), key=lambda item: item.proposal_id))
    ordered_gaps = tuple(sorted(gaps.values(), key=lambda item: item.gap_id))
    return ArchitectureExtractionResult(
        framework_profile_id=profile.profile_id,
        candidates=ordered_candidates,
        information_gaps=ordered_gaps,
        processed_requirement_ids=tuple(requirements),
        model_used=False,
    )


def candidate_from_strict_json(
    raw_candidate: Mapping[str, Any],
    flat_data: Mapping[str, Mapping[str, Any]],
    *,
    framework_profile_id: str = "dodaf",
) -> CandidateProposal:
    """Gelecekteki Gemma adaptörü için katı ve kanıta bağlı aday kapısı.

    Bu fonksiyon model çağrısı yapmaz. Gelen JSON'da fazladan alan, kaynakta
    birebir bulunmayan kanıt, izin listesi dışı mimari tür veya kendi kendine
    onay alanı varsa adayı reddeder.
    """

    if not isinstance(raw_candidate, Mapping):
        raise ArchitectureExtractionError("Model adayı JSON nesnesi olmalıdır.")
    proposal_type = _clean(raw_candidate.get("proposal_type")).casefold()
    envelope_fields = {
        "element": {
            "proposal_type", "identity_key", "name", "element_type", "description",
            "source_requirement_ids", "evidence_text",
        },
        "relationship": {
            "proposal_type", "identity_key", "name", "relationship_type", "description",
            "source_requirement_ids", "evidence_text", "source_element_id", "target_element_id",
        },
    }
    if proposal_type not in envelope_fields:
        raise ArchitectureExtractionError("Model proposal_type alanı element veya relationship olmalıdır.")
    actual_fields = set(raw_candidate)
    if actual_fields != envelope_fields[proposal_type]:
        missing = sorted(envelope_fields[proposal_type] - actual_fields)
        extra = sorted(actual_fields - envelope_fields[proposal_type])
        details = []
        if missing:
            details.append("eksik=" + ", ".join(missing))
        if extra:
            details.append("fazla=" + ", ".join(extra))
        raise ArchitectureExtractionError("Katı model aday şeması ihlali: " + "; ".join(details))

    profile = get_framework_profile(_clean(framework_profile_id))
    source_ids_raw = raw_candidate.get("source_requirement_ids")
    if not isinstance(source_ids_raw, (list, tuple)) or not source_ids_raw:
        raise ArchitectureExtractionError("Model adayı en az bir kaynak gereksinim ID'si taşımalıdır.")
    requested_ids = tuple(normalize_identifier(item) for item in source_ids_raw)
    if any(not item for item in requested_ids):
        raise ArchitectureExtractionError("Model adayında boş kaynak gereksinim ID'si olamaz.")
    trace_nodes: dict[str, Mapping[str, Any]] = {}
    gaps: dict[str, InformationGap] = {}
    requirements = _prepare_requirements(flat_data, trace_nodes, gaps)
    missing_sources = [item for item in requested_ids if item not in requirements]
    if missing_sources:
        raise ArchitectureExtractionError(
            "Model adayının kaynak gereksinimi bulunamadı: " + ", ".join(missing_sources)
        )
    evidence_text = _clean(raw_candidate.get("evidence_text"))
    source_requirements = tuple(requirements[item] for item in requested_ids)
    if evidence_text not in {item.content for item in source_requirements}:
        raise ArchitectureExtractionError(
            "Model adayı evidence_text alanı kaynak gereksinim metniyle birebir eşleşmelidir."
        )
    source_requirements = tuple(sorted(
        source_requirements,
        key=lambda item: (item.content != evidence_text, item.requirement_id),
    ))
    links = tuple(_evidence(item) for item in source_requirements)
    entity_type_field = "element_type" if proposal_type == "element" else "relationship_type"
    entity_type = _clean(raw_candidate.get(entity_type_field))
    allowed_types = _MODEL_ELEMENT_TYPES if proposal_type == "element" else _MODEL_RELATIONSHIP_TYPES
    if entity_type not in allowed_types:
        raise ArchitectureExtractionError(f"Model aday türü izin listesinde değil: {entity_type}")
    corpus = " ".join(item.content for item in source_requirements)
    explicit_type_rules = {
        "System": bool(_named_systems(corpus)),
        "Port": bool(_INTERFACE_RE.search(corpus)),
        "Protocol": bool(_PROTOCOL_RE.search(corpus)),
        "Measure": bool(extract_technical_parameters(corpus)),
        "ResourceConstraint": bool(extract_technical_parameters(corpus)),
        "ResourceFlow": bool(_FLOW_WORD_RE.search(corpus)),
        "LogicalRequirement": True,
        "connects": bool(_CONNECTION_RE.search(corpus)),
        "derived_from": any(requirement.bound_to for requirement in source_requirements),
        "flow_source": bool(_FLOW_WORD_RE.search(corpus) and (_SEND_RE.search(corpus) or _RECEIVE_RE.search(corpus))),
        "flow_target": bool(_FLOW_WORD_RE.search(corpus) and (_SEND_RE.search(corpus) or _RECEIVE_RE.search(corpus))),
    }
    if not explicit_type_rules.get(entity_type, False):
        raise ArchitectureExtractionError(
            f"Model aday türünü destekleyen açık kaynak ifadesi bulunamadı: {entity_type}"
        )
    candidate_name = _clean(raw_candidate.get("name"))
    if proposal_type == "element":
        allowed_names = _strict_element_names(entity_type, source_requirements)
        if not _same_explicit_name(candidate_name, allowed_names):
            raise ArchitectureExtractionError(
                "Model aday adı kaynakta açık tam ifade olarak bulunamadı: "
                f"{candidate_name}"
            )
    source_element_id = _clean(raw_candidate.get("source_element_id"))
    target_element_id = _clean(raw_candidate.get("target_element_id"))
    if proposal_type == "relationship":
        endpoint_registry = _model_endpoint_registry(profile.profile_id, source_requirements)
        endpoint_names = _model_endpoint_names(profile.profile_id, source_requirements)
        unknown_endpoints = [
            endpoint
            for endpoint in (source_element_id, target_element_id)
            if endpoint not in endpoint_registry
        ]
        if unknown_endpoints:
            raise ArchitectureExtractionError(
                "Model ilişki adayı kaynakta deterministik olarak tanımlanmayan uç içeriyor: "
                + ", ".join(unknown_endpoints)
            )
        source_type = endpoint_registry[source_element_id]
        target_type = endpoint_registry[target_element_id]
        valid_endpoint_types = {
            "connects": source_type in {"System", "Port"} and target_type in {"System", "Port"},
            "derived_from": source_type == target_type == "LogicalRequirement",
            "flow_source": source_type == "ResourceFlow" and target_type == "System",
            "flow_target": source_type == "ResourceFlow" and target_type == "System",
        }
        if not valid_endpoint_types[entity_type]:
            raise ArchitectureExtractionError(
                "Model ilişki adayının uç türleri ilişki türüyle uyuşmuyor."
            )
        expected_name = f"{endpoint_names[source_element_id]} {endpoint_names[target_element_id]}"
        if not _same_explicit_name(candidate_name, (expected_name,)):
            raise ArchitectureExtractionError(
                "Model ilişki aday adı kanıtlı uç adlarından deterministik "
                f"olarak türetilemedi: {candidate_name}"
            )
    return _proposal(
        profile_id=profile.profile_id,
        proposal_type=proposal_type,
        identity_key=_clean(raw_candidate.get("identity_key")),
        name=_clean(raw_candidate.get("name")),
        entity_type=entity_type,
        description=_clean(raw_candidate.get("description")),
        rationale="Katı JSON şeması ve kaynak kanıt kapısından geçen model adayıdır; kullanıcı onayı bekler.",
        evidence_links=links,
        confidence_score=0.7,
        source_element_id=source_element_id,
        target_element_id=target_element_id,
        proposal_origin=DERIVATION_MODEL_SUGGESTION,
    )


__all__ = [
    "ArchitectureExtractionError", "ArchitectureExtractionResult", "InformationGap",
    "PRODUCER", "PRODUCER_VERSION", "SCHEMA_VERSION",
    "candidate_from_strict_json", "extract_architecture_candidates",
]
