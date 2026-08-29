# -*- coding: utf-8 -*-
"""Donanım Bilgi Kartları ve ürün ağacı için bağımsız veri sözleşmesi.

Bu modül belge okumaz, LLM çağırmaz ve arayüz kodu içermez. Algılama
katmanından gelen veriyi doğrulanabilir, JSON'a çevrilebilir modellere taşır
ve güven puanını yalnızca açıklanabilir Python kurallarıyla hesaplar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "1.1"
MISSING_VALUE = "Veri bulunamadı"
PLACEHOLDER_IMAGE = "placeholder://donanim"

WORKING_STATES = (
    "Normal",
    "Bekleme",
    "Düşük performans",
    "Arızalı",
    "Bakımda",
    "Devre dışı",
)
LIFECYCLE_STATES = (
    "Mevcut",
    "Önerilen",
    "Alternatif",
    "Onay bekliyor",
    "Onaylandı",
    "Kullanımdan kaldırıldı",
    "Veri eksik",
)
PRODUCT_LEVELS = (
    "Sistem",
    "Alt sistem",
    "Donanım grubu",
    "Kart/modül",
    "Parça/bileşen",
    "Alt bileşen",
)
ALTERNATIVE_COMPATIBILITY_STATES = (
    "Tam uyumlu",
    "Koşullu uyumlu",
    "Uyumlu değil",
    "İncelenmedi",
    "Veri eksik",
)
EVIDENCE_CERTAINTY_STATES = ("Kesin bilgi", "Çıkarım", "Varsayım")
SOURCE_PRESENCE_STATES = ("Kaynakta bulundu", "Kaynaktan artık bulunamadı")

# Toplam tam olarak 100'dür. LM Studio'nun öznel skoru bu hesaba katılmaz.
CONFIDENCE_WEIGHTS = {
    "explicit_identity": 25.0,
    "datasheet_or_manufacturer": 25.0,
    "multi_document_consistency": 20.0,
    "requirement_and_test_links": 20.0,
    "basic_field_completeness": 10.0,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clean_text(value: Any, default: str = "") -> str:
    text = " ".join(str(value or "").split())
    return text or default


def is_missing(value: Any) -> bool:
    return clean_text(value).casefold() in {
        "", "dsb", "yok", "none", "null", "n/a", "na",
        MISSING_VALUE.casefold(),
    }


def missing_if_empty(value: Any) -> Any:
    if value is None or is_missing(value):
        return MISSING_VALUE
    return value


def _unique_texts(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


@dataclass(slots=True)
class SourceEvidence:
    field_name: str
    source_document: str
    location: str = MISSING_VALUE
    evidence_text: str = MISSING_VALUE
    extraction_method: str = "structured_python"
    field_confidence: float = 0.0
    certainty: str = "Kesin bilgi"

    def __post_init__(self) -> None:
        self.field_name = clean_text(self.field_name, MISSING_VALUE)
        self.source_document = clean_text(self.source_document, MISSING_VALUE)
        self.location = clean_text(self.location, MISSING_VALUE)
        self.evidence_text = clean_text(self.evidence_text, MISSING_VALUE)
        self.extraction_method = clean_text(self.extraction_method, "unknown")
        self.field_confidence = round(max(0.0, min(100.0, float(self.field_confidence or 0))), 2)
        if self.certainty not in EVIDENCE_CERTAINTY_STATES:
            self.certainty = "Çıkarım"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SourceEvidence":
        return cls(**{key: raw.get(key) for key in cls.__dataclass_fields__})


@dataclass(slots=True)
class TechnicalData:
    operating_temperature_min: Any = MISSING_VALUE
    operating_temperature_max: Any = MISSING_VALUE
    storage_temperature_min: Any = MISSING_VALUE
    storage_temperature_max: Any = MISSING_VALUE
    temperature_unit: str = MISSING_VALUE
    length: Any = MISSING_VALUE
    width: Any = MISSING_VALUE
    height: Any = MISSING_VALUE
    diameter: Any = MISSING_VALUE
    dimension_unit: str = MISSING_VALUE
    weight: Any = MISSING_VALUE
    weight_unit: str = MISSING_VALUE
    supply_voltage: Any = MISSING_VALUE
    power_consumption: Any = MISSING_VALUE
    communication_interfaces: list[str] = field(default_factory=list)
    mechanical_interfaces: list[str] = field(default_factory=list)
    electrical_interfaces: list[str] = field(default_factory=list)
    environmental_resistance: Any = MISSING_VALUE
    reliability: Any = MISSING_VALUE
    standards_and_certifications: list[str] = field(default_factory=list)
    custom_parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scalar_fields = (
            "operating_temperature_min", "operating_temperature_max",
            "storage_temperature_min", "storage_temperature_max", "temperature_unit",
            "length", "width", "height", "diameter", "dimension_unit",
            "weight", "weight_unit", "supply_voltage", "power_consumption",
            "environmental_resistance", "reliability",
        )
        for name in scalar_fields:
            setattr(self, name, missing_if_empty(getattr(self, name)))
        self.communication_interfaces = _unique_texts(self.communication_interfaces)
        self.mechanical_interfaces = _unique_texts(self.mechanical_interfaces)
        self.electrical_interfaces = _unique_texts(self.electrical_interfaces)
        self.standards_and_certifications = _unique_texts(self.standards_and_certifications)
        self.custom_parameters = {
            clean_text(key): missing_if_empty(value)
            for key, value in dict(self.custom_parameters or {}).items()
            if clean_text(key)
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "TechnicalData":
        raw = raw or {}
        return cls(**{key: raw.get(key) for key in cls.__dataclass_fields__ if key in raw})

    def populated_field_count(self) -> int:
        data = self.to_dict()
        return sum(
            1 for value in data.values()
            if (isinstance(value, (list, dict)) and bool(value))
            or (not isinstance(value, (list, dict)) and not is_missing(value))
        )


@dataclass(slots=True)
class HardwareCard:
    hardware_id: str
    part_name: str
    part_number: str = MISSING_VALUE
    manufacturer: str = MISSING_VALUE
    model_series: str = MISSING_VALUE
    hardware_type: str = MISSING_VALUE
    description: str = MISSING_VALUE
    system_role: str = MISSING_VALUE
    parent_id: str = MISSING_VALUE
    child_ids: list[str] = field(default_factory=list)
    quantity: int = 1
    image_path: str = PLACEHOLDER_IMAGE
    working_states: list[str] = field(default_factory=lambda: ["Normal"])
    lifecycle_status: str = "Veri eksik"
    technical_data: TechnicalData = field(default_factory=TechnicalData)
    requirement_ids: list[str] = field(default_factory=list)
    test_ids: list[str] = field(default_factory=list)
    alternative_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    source_evidence: list[SourceEvidence] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=now_iso)
    version: str = "1.0"
    aliases: list[str] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)
    confidence_breakdown: dict[str, Any] = field(default_factory=dict)
    source_presence_status: str = "Kaynakta bulundu"

    def __post_init__(self) -> None:
        self.hardware_id = clean_text(self.hardware_id)
        if not self.hardware_id:
            raise ValueError("Benzersiz donanım kimliği gerekli.")
        self.part_name = clean_text(self.part_name, MISSING_VALUE)
        for name in (
            "part_number", "manufacturer", "model_series", "hardware_type",
            "description", "system_role", "parent_id",
        ):
            setattr(self, name, missing_if_empty(getattr(self, name)))
        try:
            self.quantity = max(1, int(self.quantity))
        except (TypeError, ValueError):
            self.quantity = 1
        self.child_ids = _unique_texts(self.child_ids)
        self.requirement_ids = _unique_texts(self.requirement_ids)
        self.test_ids = _unique_texts(self.test_ids)
        self.alternative_ids = _unique_texts(self.alternative_ids)
        self.aliases = _unique_texts([self.part_name, *self.aliases])
        self.working_states = _unique_texts(self.working_states) or ["Normal"]
        self.lifecycle_status = (
            self.lifecycle_status if self.lifecycle_status in LIFECYCLE_STATES else "Veri eksik"
        )
        self.source_presence_status = (
            self.source_presence_status
            if self.source_presence_status in SOURCE_PRESENCE_STATES
            else "Kaynakta bulundu"
        )
        if not isinstance(self.technical_data, TechnicalData):
            self.technical_data = TechnicalData.from_dict(self.technical_data)
        self.source_evidence = [
            item if isinstance(item, SourceEvidence) else SourceEvidence.from_dict(item)
            for item in self.source_evidence
        ]
        self.missing_information = _unique_texts(self.missing_information)
        self.assumptions = _unique_texts(self.assumptions)
        self.field_confidence = {
            clean_text(key): round(max(0.0, min(100.0, float(value))), 2)
            for key, value in dict(self.field_confidence or {}).items()
            if clean_text(key)
        }

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["technical_data"] = self.technical_data.to_dict()
        result["source_evidence"] = [item.to_dict() for item in self.source_evidence]
        return result

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "HardwareCard":
        values = {key: raw.get(key) for key in cls.__dataclass_fields__ if key in raw}
        values["technical_data"] = TechnicalData.from_dict(raw.get("technical_data"))
        values["source_evidence"] = [
            SourceEvidence.from_dict(item)
            for item in raw.get("source_evidence", [])
            if isinstance(item, Mapping)
        ]
        return cls(**values)


@dataclass(slots=True)
class ProductInstance:
    instance_id: str
    hardware_id: str
    parent_instance_id: str = MISSING_VALUE
    quantity: int = 1
    location: str = MISSING_VALUE
    level: str = "Parça/bileşen"
    reference_designator: str = MISSING_VALUE
    source_evidence: list[SourceEvidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.instance_id = clean_text(self.instance_id)
        self.hardware_id = clean_text(self.hardware_id)
        if not self.instance_id or not self.hardware_id:
            raise ValueError("Ürün ağacı örneği için instance_id ve hardware_id gerekli.")
        self.parent_instance_id = missing_if_empty(self.parent_instance_id)
        self.location = missing_if_empty(self.location)
        self.reference_designator = missing_if_empty(self.reference_designator)
        self.level = clean_text(self.level, "Parça/bileşen")
        try:
            self.quantity = max(1, int(self.quantity))
        except (TypeError, ValueError):
            self.quantity = 1
        self.source_evidence = [
            item if isinstance(item, SourceEvidence) else SourceEvidence.from_dict(item)
            for item in self.source_evidence
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProductInstance":
        return cls(**{key: raw.get(key) for key in cls.__dataclass_fields__ if key in raw})


@dataclass(slots=True)
class AlternativeLink:
    source_hardware_id: str
    alternative_hardware_id: str
    reason: str = MISSING_VALUE
    compatibility_status: str = "İncelenmedi"
    parameter_differences: dict[str, Any] = field(default_factory=dict)
    met_requirements: list[str] = field(default_factory=list)
    unmet_requirements: list[str] = field(default_factory=list)
    new_risks: list[str] = field(default_factory=list)
    source: str = MISSING_VALUE
    user_approval: str = "Onay bekliyor"

    def __post_init__(self) -> None:
        if self.compatibility_status not in ALTERNATIVE_COMPATIBILITY_STATES:
            self.compatibility_status = "İncelenmedi"
        # Kanıt ve kullanıcı onayı olmadan "Tam uyumlu" kabul edilmez.
        if self.compatibility_status == "Tam uyumlu" and (
            is_missing(self.source) or self.user_approval != "Onaylandı"
        ):
            self.compatibility_status = "Koşullu uyumlu"
        self.met_requirements = _unique_texts(self.met_requirements)
        self.unmet_requirements = _unique_texts(self.unmet_requirements)
        self.new_risks = _unique_texts(self.new_risks)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AlternativeLink":
        return cls(**{key: raw.get(key) for key in cls.__dataclass_fields__ if key in raw})


@dataclass(slots=True)
class HardwareCatalog:
    project_id: str
    project_name: str
    version: str = "v0001"
    generated_at: str = field(default_factory=now_iso)
    hardware_items: list[HardwareCard] = field(default_factory=list)
    product_instances: list[ProductInstance] = field(default_factory=list)
    product_tree: list[dict[str, Any]] = field(default_factory=list)
    alternative_links: list[AlternativeLink] = field(default_factory=list)
    unresolved_items: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    source_fingerprint: str = ""
    schema_version: str = SCHEMA_VERSION
    storage_path: str = ""
    version_path: str = ""
    updated: bool = True

    def to_dict(self, include_runtime_paths: bool = True) -> dict[str, Any]:
        result = {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "version": self.version,
            "generated_at": self.generated_at,
            "hardware_items": [item.to_dict() for item in self.hardware_items],
            "product_instances": [item.to_dict() for item in self.product_instances],
            "product_tree": list(self.product_tree),
            "alternative_links": [item.to_dict() for item in self.alternative_links],
            "unresolved_items": list(self.unresolved_items),
            "conflicts": list(self.conflicts),
            "sources": list(self.sources),
            "source_fingerprint": self.source_fingerprint,
            "schema_version": self.schema_version,
        }
        if include_runtime_paths:
            result.update({
                "storage_path": self.storage_path,
                "version_path": self.version_path,
                "updated": self.updated,
            })
        return result

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "HardwareCatalog":
        return cls(
            project_id=clean_text(raw.get("project_id")),
            project_name=clean_text(raw.get("project_name")),
            version=clean_text(raw.get("version"), "v0001"),
            generated_at=clean_text(raw.get("generated_at"), now_iso()),
            hardware_items=[
                HardwareCard.from_dict(item) for item in raw.get("hardware_items", [])
                if isinstance(item, Mapping)
            ],
            product_instances=[
                ProductInstance.from_dict(item) for item in raw.get("product_instances", [])
                if isinstance(item, Mapping)
            ],
            product_tree=list(raw.get("product_tree", [])),
            alternative_links=[
                AlternativeLink.from_dict(item) for item in raw.get("alternative_links", [])
                if isinstance(item, Mapping)
            ],
            unresolved_items=list(raw.get("unresolved_items", [])),
            conflicts=list(raw.get("conflicts", [])),
            sources=list(raw.get("sources", [])),
            source_fingerprint=clean_text(raw.get("source_fingerprint")),
            schema_version=clean_text(raw.get("schema_version"), SCHEMA_VERSION),
            storage_path=clean_text(raw.get("storage_path")),
            version_path=clean_text(raw.get("version_path")),
            updated=bool(raw.get("updated", False)),
        )


def calculate_card_confidence(card: HardwareCard) -> tuple[float, dict[str, Any]]:
    """Kart güvenini sabit ağırlıklarla 0–100 arasında hesaplar."""
    exact_identity = (
        not is_missing(card.part_number)
        or any(
            evidence.field_name in {"hardware_id", "part_number"}
            and evidence.certainty == "Kesin bilgi"
            and evidence.field_confidence >= 80
            for evidence in card.source_evidence
        )
    )
    has_datasheet = any(
        evidence.extraction_method.startswith("datasheet")
        for evidence in card.source_evidence
    )
    has_manufacturer = not is_missing(card.manufacturer)
    source_documents = {
        evidence.source_document.casefold()
        for evidence in card.source_evidence
        if not is_missing(evidence.source_document)
    }

    link_points = 0.0
    if card.requirement_ids:
        link_points += CONFIDENCE_WEIGHTS["requirement_and_test_links"] / 2
    if card.test_ids:
        link_points += CONFIDENCE_WEIGHTS["requirement_and_test_links"] / 2

    basic_values = (
        card.part_name, card.hardware_type, card.description, card.system_role,
    )
    basic_populated = sum(not is_missing(value) for value in basic_values)
    if card.technical_data.populated_field_count() > 0:
        basic_populated += 1
    completeness_points = (
        CONFIDENCE_WEIGHTS["basic_field_completeness"] * basic_populated / 5
    )

    components = {
        "explicit_identity": CONFIDENCE_WEIGHTS["explicit_identity"] if exact_identity else 0.0,
        "datasheet_or_manufacturer": (
            CONFIDENCE_WEIGHTS["datasheet_or_manufacturer"]
            if has_datasheet or has_manufacturer else 0.0
        ),
        "multi_document_consistency": (
            CONFIDENCE_WEIGHTS["multi_document_consistency"]
            if len(source_documents) >= 2 else 0.0
        ),
        "requirement_and_test_links": link_points,
        "basic_field_completeness": completeness_points,
    }
    score = round(min(100.0, sum(components.values())), 2)
    explanation = {
        "score": score,
        "weights": dict(CONFIDENCE_WEIGHTS),
        "components": {key: round(value, 2) for key, value in components.items()},
        "source_document_count": len(source_documents),
        "note": "LM Studio güven değeri kullanılmadı; puan Python ile deterministik hesaplandı.",
    }
    return score, explanation


__all__ = [
    "ALTERNATIVE_COMPATIBILITY_STATES",
    "AlternativeLink",
    "CONFIDENCE_WEIGHTS",
    "EVIDENCE_CERTAINTY_STATES",
    "HardwareCard",
    "HardwareCatalog",
    "LIFECYCLE_STATES",
    "MISSING_VALUE",
    "PLACEHOLDER_IMAGE",
    "PRODUCT_LEVELS",
    "ProductInstance",
    "SCHEMA_VERSION",
    "SourceEvidence",
    "SOURCE_PRESENCE_STATES",
    "TechnicalData",
    "WORKING_STATES",
    "calculate_card_confidence",
    "clean_text",
    "is_missing",
]
