# -*- coding: utf-8 -*-
"""DoDAF 2.02 / NAF 4.1 için UI'dan bağımsız doğrulama motoru.

Motor üç ayrı soruyu ayrı sonuçlar olarak cevaplar:

* seçilen görünüm eldeki onaylı veriden üretilebilir mi,
* mimari kayıtlar kendi içinde bütün ve kanıtlı mı,
* yerel model seçilen çerçevenin uygulanmış semantik kapılarını
  geçiyor mu.

``mimari_cerceve_katalog`` içindeki gerekli tür ve ilişkiler EHSİM'in
asgari veri kapılarıdır; eksiksiz DM2/PES veya NAF Information Model
karşılığı değildir. Aşağıdaki eşleme tabloları bu sınırı her satırda
``verified``, ``provisional`` veya ``missing`` olarak taşır. Kaynakta
doğrulanmayan ilişki adı uydurulmaz; hedef ``belirsiz/eksik`` kalır.

Bu sürümde yerel PES ve ArchiMate exchange doğrulayıcısı yoktur. Bu
nedenle rapor hiçbir zaman "DoDAF uyumlu" veya "NAF uyumlu" demez; en iyi
sonuç, açık sınırlarıyla "... ile hizalı taslak"tır.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from mimari_cerceve_katalog import (
    DODAF_PROFILE_ID,
    DODAF_VERSION,
    FRAMEWORK_PROFILES,
    NAF_PROFILE_ID,
    NAF_VERSION,
    get_framework_profile,
)
from mimari_cerceve_model import (
    AUTOMATIC_DERIVATION_KINDS,
    DERIVATION_MODEL_SUGGESTION,
    DERIVATION_USER_SUPPLIED,
    KNOWN_ELEMENT_TYPES,
    KNOWN_RELATIONSHIP_TYPES,
    REVIEW_APPROVED,
    REVIEW_EDITED,
    ValidationFinding,
    ViewDefinition,
    evidence_fingerprint_for,
)


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFORMATION = "information"

DIMENSION_VIEW_GENERATABILITY = "view_generatability"
DIMENSION_MODEL_INTEGRITY = "model_integrity"
DIMENSION_FRAMEWORK_CONFORMANCE = "framework_conformance"

STATUS_GENERATABLE = "üretilebilir"
STATUS_NOT_GENERATABLE = "üretilemez"
STATUS_INTEGRITY_VALID = "bütün"
STATUS_INTEGRITY_INVALID = "bütünlük hatası"

DODAF_SOURCE = "https://dodcio.defense.gov/DoDAF/"
DODAF_DM2_SOURCE = (
    "https://dodcio.defense.gov/Library/DoD-Architecture-Framework/"
    "dodaf20_logical.aspx"
)
DODAF_PES_SOURCE = (
    "https://dodcio.defense.gov/Library/DoD-Architecture-Framework/dodaf20_pes/"
)
NAF_SOURCE = (
    "https://www.nato.int/content/dam/nato/webready/documents/"
    "publications-and-reports/NATO-Architecture-Framework-v4-1-en.pdf"
)
NAF_ARCHIMATE_SOURCE = (
    "https://www.nato.int/content/dam/nato/webready/documents/"
    "publications-and-reports/NATO-Architecture-Framework-ArchiMate-v4-1-en.pdf"
)


@dataclass(frozen=True, slots=True)
class MappingRule:
    """Yerel tür ile resmî bilgi modeli/profil arasındaki izlenebilir satır."""

    local_type: str
    target_types: tuple[str, ...]
    status: str
    source_url: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.local_type.strip():
            raise ValueError("Eşleme yerel türü boş olamaz.")
        if not self.target_types:
            raise ValueError("Eşleme hedefi açıkça tanımlanmalıdır.")
        if self.status not in {"verified", "provisional", "missing"}:
            raise ValueError(f"Desteklenmeyen eşleme durumu: {self.status}")

    @property
    def complete(self) -> bool:
        return self.status == "verified" and "belirsiz/eksik" not in self.target_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_type": self.local_type,
            "target_types": list(self.target_types),
            "status": self.status,
            "source_url": self.source_url,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class ViewValidationResult:
    view_id: str
    generatable: bool
    status: str
    findings: tuple[ValidationFinding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "generatable": self.generatable,
            "status": self.status,
            "findings": [item.to_dict() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class ValidationDimensionResult:
    dimension: str
    passed: bool
    status: str
    findings: tuple[ValidationFinding, ...] = ()
    view_results: tuple[ViewValidationResult, ...] = ()
    aligned: bool = False
    conformant: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "passed": self.passed,
            "status": self.status,
            "aligned": self.aligned,
            "conformant": self.conformant,
            "findings": [item.to_dict() for item in self.findings],
            "view_results": [item.to_dict() for item in self.view_results],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureValidationReport:
    framework_profile_id: str
    framework_version: str
    view_generatability: ValidationDimensionResult
    model_integrity: ValidationDimensionResult
    framework_conformance: ValidationDimensionResult

    @property
    def findings(self) -> tuple[ValidationFinding, ...]:
        values = (
            *self.view_generatability.findings,
            *self.model_integrity.findings,
            *self.framework_conformance.findings,
        )
        return _unique_findings(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework_profile_id": self.framework_profile_id,
            "framework_version": self.framework_version,
            "view_generatability": self.view_generatability.to_dict(),
            "model_integrity": self.model_integrity.to_dict(),
            "framework_conformance": self.framework_conformance.to_dict(),
            "findings": [item.to_dict() for item in self.findings],
        }


def _rule(
    local_type: str,
    targets: str | Sequence[str],
    status: str,
    source_url: str,
    notes: str = "",
) -> MappingRule:
    target_types = (targets,) if isinstance(targets, str) else tuple(targets)
    return MappingRule(local_type, target_types, status, source_url, notes)


# DoD'un DM2 sözlüğü kavramları ve görünümleri eşler. Buradaki
# ``verified`` satırlar yalnız doğrudan kavram ailesi eşlemesidir. Attribute
# veya association seviyesinde kesinleştirilmeyen satırlar provisional/missing
# kalır; bunlar PES uygunluğu kanıtı değildir.
_DODAF_ELEMENT_RULES: dict[str, MappingRule] = {
    "ArchitectureDescription": _rule("ArchitectureDescription", "ArchitecturalDescription", "verified", DODAF_DM2_SOURCE),
    "ArchitectureMetadata": _rule("ArchitectureMetadata", "ArchitecturalDescription attributes", "provisional", DODAF_DM2_SOURCE),
    "AuthoritativeSource": _rule("AuthoritativeSource", "Information/Pedigree", "provisional", DODAF_DM2_SOURCE),
    "Definition": _rule("Definition", "Description attribute", "provisional", DODAF_DM2_SOURCE),
    "DictionaryTerm": _rule("DictionaryTerm", "Name/Description attributes", "provisional", DODAF_DM2_SOURCE),
    "Measure": _rule("Measure", "Measure", "verified", DODAF_DM2_SOURCE),
    "OperationalActivity": _rule("OperationalActivity", "Activity", "verified", DODAF_DM2_SOURCE),
    "Port": _rule("Port", "Port", "verified", DODAF_DM2_SOURCE),
    "ResourceFlow": _rule("ResourceFlow", "ResourceFlow", "verified", DODAF_DM2_SOURCE),
    "Service": _rule("Service", "Service", "verified", DODAF_DM2_SOURCE),
    "ServiceFunction": _rule("ServiceFunction", "Activity", "provisional", DODAF_DM2_SOURCE),
    "ServiceModelElement": _rule("ServiceModelElement", "Service/Performer", "provisional", DODAF_DM2_SOURCE),
    "ServiceOrResource": _rule("ServiceOrResource", "Service/Performer", "provisional", DODAF_DM2_SOURCE),
    "ServiceResourceFlow": _rule("ServiceResourceFlow", "ResourceFlow", "verified", DODAF_DM2_SOURCE),
    "System": _rule("System", "Performer", "verified", DODAF_DM2_SOURCE),
    "SystemFunction": _rule("SystemFunction", "Activity", "verified", DODAF_DM2_SOURCE),
    "SystemItem": _rule("SystemItem", "Performer/Resource", "provisional", DODAF_DM2_SOURCE),
    "SystemModelElement": _rule("SystemModelElement", "Performer", "provisional", DODAF_DM2_SOURCE),
    "SystemOrResource": _rule("SystemOrResource", "Performer", "provisional", DODAF_DM2_SOURCE),
    "SystemResourceFlow": _rule("SystemResourceFlow", "ResourceFlow", "verified", DODAF_DM2_SOURCE),
    "Timeframe": _rule("Timeframe", "TemporalWhole/Condition", "provisional", DODAF_DM2_SOURCE),
}

_DODAF_RELATIONSHIP_RULES: dict[str, MappingRule] = {
    "allocated_to": _rule("allocated_to", "Activity-performed-by-Performer association", "provisional", DODAF_DM2_SOURCE),
    "defined_by": _rule("defined_by", "belirsiz/eksik", "missing", DODAF_DM2_SOURCE),
    "derived_from": _rule("derived_from", "Rule/Agreement derivation association", "provisional", DODAF_DM2_SOURCE),
    "flow_source": _rule("flow_source", "ResourceFlow source association", "provisional", DODAF_DM2_SOURCE),
    "flow_target": _rule("flow_target", "ResourceFlow target association", "provisional", DODAF_DM2_SOURCE),
    "maps_to": _rule("maps_to", "Activity traceability association", "provisional", DODAF_DM2_SOURCE),
    "measure_applies_to": _rule("measure_applies_to", "Measure association", "provisional", DODAF_DM2_SOURCE),
    "performed_by": _rule("performed_by", "Activity-performed-by-Performer association", "provisional", DODAF_DM2_SOURCE),
    "port_belongs_to": _rule("port_belongs_to", "Port-to-Performer association", "provisional", DODAF_DM2_SOURCE),
    "realizes": _rule("realizes", "Activity traceability association", "provisional", DODAF_DM2_SOURCE),
    "valid_during": _rule("valid_during", "Temporal association", "provisional", DODAF_DM2_SOURCE),
}


# NATO kılavuzu NAF IM ile ArchiMate arasında bire-bir değil, çoktan-çoğa
# eşleme tanımlar. Liste değerleri bu nedenle bilinçli olarak tuple'dır.
_NAF_ELEMENT_RULES: dict[str, MappingRule] = {
    "CapabilityConfiguration": _rule("CapabilityConfiguration", ("Grouping",), "verified", NAF_ARCHIMATE_SOURCE),
    "FunctionalFlow": _rule("FunctionalFlow", ("Flow", "Triggering"), "provisional", NAF_ARCHIMATE_SOURCE),
    "LogicalActiveResource": _rule(
        "LogicalActiveResource",
        ("Business actor", "Application component", "Equipment", "Node", "Grouping"),
        "verified", NAF_ARCHIMATE_SOURCE,
    ),
    "LogicalBehaviour": _rule(
        "LogicalBehaviour",
        ("Application function", "Business function", "Technology function", "Business process"),
        "verified", NAF_ARCHIMATE_SOURCE,
    ),
    "LogicalConstraint": _rule("LogicalConstraint", "Requirement", "verified", NAF_ARCHIMATE_SOURCE),
    "LogicalEvent": _rule("LogicalEvent", "Business event", "provisional", NAF_ARCHIMATE_SOURCE),
    "LogicalInteraction": _rule("LogicalInteraction", "Business interaction", "verified", NAF_ARCHIMATE_SOURCE),
    "LogicalPassiveResource": _rule("LogicalPassiveResource", ("Business object", "Material"), "verified", NAF_ARCHIMATE_SOURCE),
    "LogicalRationale": _rule("LogicalRationale", "Driver", "verified", NAF_ARCHIMATE_SOURCE),
    "LogicalRequirement": _rule("LogicalRequirement", "Requirement", "verified", NAF_ARCHIMATE_SOURCE),
    "LogicalSpecification": _rule("LogicalSpecification", ("Grouping", "Requirement"), "verified", NAF_ARCHIMATE_SOURCE),
    "Needline": _rule("Needline", "Business collaboration", "verified", NAF_ARCHIMATE_SOURCE),
    "Node": _rule("Node", "Grouping", "verified", NAF_ARCHIMATE_SOURCE),
    "OperationalActivity": _rule("OperationalActivity", ("Business process", "Business function"), "provisional", NAF_ARCHIMATE_SOURCE),
    "OperationalControlFlow": _rule("OperationalControlFlow", "Triggering", "provisional", NAF_ARCHIMATE_SOURCE),
    "PhysicalActiveResource": _rule(
        "PhysicalActiveResource",
        ("Application component", "Communication network", "Device", "Distribution network", "Equipment", "Facility", "Business actor", "Business role", "System software"),
        "verified", NAF_ARCHIMATE_SOURCE,
    ),
    "PhysicalBehaviour": _rule("PhysicalBehaviour", ("Business process", "Technology process"), "provisional", NAF_ARCHIMATE_SOURCE),
    "PhysicalPassiveResource": _rule("PhysicalPassiveResource", ("Artifact", "Data object", "Material"), "provisional", NAF_ARCHIMATE_SOURCE),
    "Protocol": _rule("Protocol", "Artifact", "verified", NAF_ARCHIMATE_SOURCE),
    "ResourceConstraint": _rule("ResourceConstraint", "Requirement", "verified", NAF_ARCHIMATE_SOURCE),
    "ResourceFlow": _rule("ResourceFlow", "Flow", "provisional", NAF_ARCHIMATE_SOURCE),
    "ResourceFunction": _rule("ResourceFunction", ("Business function", "Application function", "Technology function"), "provisional", NAF_ARCHIMATE_SOURCE),
    "ResourceInteraction": _rule("ResourceInteraction", "Technology interaction", "verified", NAF_ARCHIMATE_SOURCE),
    "ResourceRationale": _rule("ResourceRationale", "Driver", "verified", NAF_ARCHIMATE_SOURCE),
    "ResourceRequirement": _rule("ResourceRequirement", "Requirement", "verified", NAF_ARCHIMATE_SOURCE),
    "ResourceSpecification": _rule("ResourceSpecification", ("Grouping", "Requirement"), "verified", NAF_ARCHIMATE_SOURCE),
    "Role": _rule("Role", "Business role", "verified", NAF_ARCHIMATE_SOURCE),
    "Standard": _rule("Standard", "Contract", "verified", NAF_ARCHIMATE_SOURCE),
}

_NAF_RELATIONSHIP_RULES: dict[str, MappingRule] = {
    "aggregates": _rule("aggregates", "Aggregation", "provisional", NAF_ARCHIMATE_SOURCE),
    "applies_to": _rule("applies_to", "Association/Realization", "provisional", NAF_ARCHIMATE_SOURCE),
    "conforms_to": _rule("conforms_to", "Association", "provisional", NAF_ARCHIMATE_SOURCE),
    "control_flow_source": _rule("control_flow_source", "Triggering endpoint", "provisional", NAF_ARCHIMATE_SOURCE),
    "control_flow_target": _rule("control_flow_target", "Triggering endpoint", "provisional", NAF_ARCHIMATE_SOURCE),
    "conveys": _rule("conveys", "Flow/Access", "provisional", NAF_ARCHIMATE_SOURCE),
    "delivers": _rule("delivers", "Access/Flow", "provisional", NAF_ARCHIMATE_SOURCE),
    "depends_on": _rule("depends_on", "Serving/Association", "provisional", NAF_ARCHIMATE_SOURCE),
    "flow_source": _rule("flow_source", "Flow endpoint", "provisional", NAF_ARCHIMATE_SOURCE),
    "flow_target": _rule("flow_target", "Flow endpoint", "provisional", NAF_ARCHIMATE_SOURCE),
    "implements": _rule("implements", "Realization", "provisional", NAF_ARCHIMATE_SOURCE),
    "interaction_source": _rule("interaction_source", "Interaction endpoint", "provisional", NAF_ARCHIMATE_SOURCE),
    "interaction_target": _rule("interaction_target", "Interaction endpoint", "provisional", NAF_ARCHIMATE_SOURCE),
    "performs": _rule("performs", "Assignment", "provisional", NAF_ARCHIMATE_SOURCE),
    "realizes": _rule("realizes", "Realization", "provisional", NAF_ARCHIMATE_SOURCE),
    "relates_to": _rule("relates_to", "Association", "provisional", NAF_ARCHIMATE_SOURCE),
    "structurally_contains": _rule("structurally_contains", "Composition/Aggregation", "provisional", NAF_ARCHIMATE_SOURCE),
    "uses": _rule("uses", "Access/Serving", "provisional", NAF_ARCHIMATE_SOURCE),
}


def _catalog_types(profile_id: str, relationship: bool = False) -> set[str]:
    profile = get_framework_profile(profile_id)
    result: set[str] = set()
    for view in profile.view_definitions:
        if relationship:
            result.update(view.required_relationships)
            result.update(view.optional_relationships)
            for group in view.required_any_of_relationships:
                result.update(group)
        else:
            result.update(view.required_element_types)
            result.update(view.optional_element_types)
            for group in view.required_any_of_element_types:
                result.update(group)
    return result


def _complete_table(
    rows: Mapping[str, MappingRule],
    required_types: Iterable[str],
    source_url: str,
) -> Mapping[str, MappingRule]:
    completed = dict(rows)
    for item_type in sorted(set(required_types)):
        completed.setdefault(
            item_type,
            _rule(
                item_type,
                "belirsiz/eksik",
                "missing",
                source_url,
                "Katalogda desteklenir; normatif hedef eşleme bu sürümde doğrulanmadı.",
            ),
        )
    return MappingProxyType(completed)


DODAF_DM2_ELEMENT_MAPPINGS: Mapping[str, MappingRule] = _complete_table(
    _DODAF_ELEMENT_RULES, _catalog_types(DODAF_PROFILE_ID), DODAF_DM2_SOURCE,
)
DODAF_DM2_RELATIONSHIP_MAPPINGS: Mapping[str, MappingRule] = _complete_table(
    _DODAF_RELATIONSHIP_RULES,
    _catalog_types(DODAF_PROFILE_ID, relationship=True),
    DODAF_DM2_SOURCE,
)
NAF_ARCHIMATE_ELEMENT_MAPPINGS: Mapping[str, MappingRule] = _complete_table(
    _NAF_ELEMENT_RULES, _catalog_types(NAF_PROFILE_ID), NAF_ARCHIMATE_SOURCE,
)
NAF_ARCHIMATE_RELATIONSHIP_MAPPINGS: Mapping[str, MappingRule] = _complete_table(
    _NAF_RELATIONSHIP_RULES,
    _catalog_types(NAF_PROFILE_ID, relationship=True),
    NAF_ARCHIMATE_SOURCE,
)

# Açık "table" adı isteyen tüketiciler için geriye/ileri uyumlu aliaslar.
DODAF_DM2_CONCEPT_MAPPING_TABLE = DODAF_DM2_ELEMENT_MAPPINGS
DODAF_DM2_RELATIONSHIP_MAPPING_TABLE = DODAF_DM2_RELATIONSHIP_MAPPINGS
NAF_IM_ARCHIMATE_ELEMENT_MAPPING_TABLE = NAF_ARCHIMATE_ELEMENT_MAPPINGS
NAF_IM_ARCHIMATE_RELATIONSHIP_MAPPING_TABLE = NAF_ARCHIMATE_RELATIONSHIP_MAPPINGS


# Bir türün yalnız var olmasının yetmediği, görünüme özgü asgari
# kardinaliteler. Bunlar EHSİM yerel üretilebilirlik kapılarıdır.
VIEW_MINIMUM_CARDINALITIES: Mapping[str, tuple[tuple[str, int], ...]] = MappingProxyType({
    "SV-1": (("System", 2),),
    "SV-2": (("System", 2),),
    "SvcV-1": (("Service", 2),),
    "SvcV-2": (("Service", 2),),
    "L3": (("LogicalActiveResource", 2),),
    "P3": (("PhysicalActiveResource", 2),),
})

# (ilişki türü, izinli uç-türü çiftleri). Yön, ayrı
# source/target ilişkileriyle zaten temsil edildiği için bu asgari kapıda çift
# sırasından bağımsız denetlenir.
VIEW_RELATION_ENDPOINT_CARDINALITIES: Mapping[
    str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
] = MappingProxyType({
    "SV-1": (
        ("flow_source", (("SystemResourceFlow", "System"),)),
        ("flow_target", (("SystemResourceFlow", "System"),)),
    ),
    "SV-2": (
        ("port_belongs_to", (("Port", "System"),)),
        ("flow_source", (("SystemResourceFlow", "Port"),)),
        ("flow_target", (("SystemResourceFlow", "Port"),)),
    ),
    "SV-4": (
        ("performed_by", (("SystemFunction", "SystemOrResource"),)),
        ("flow_source", (("ResourceFlow", "SystemFunction"),)),
        ("flow_target", (("ResourceFlow", "SystemFunction"),)),
    ),
    "SV-5a": (("maps_to", (("OperationalActivity", "SystemFunction"),)),),
    "SV-7": (
        ("measure_applies_to", (("Measure", "SystemModelElement"),)),
        ("valid_during", (("Measure", "Timeframe"), ("SystemModelElement", "Timeframe"))),
    ),
    "SvcV-1": (
        ("flow_source", (("ServiceResourceFlow", "Service"),)),
        ("flow_target", (("ServiceResourceFlow", "Service"),)),
    ),
    "SvcV-2": (
        ("port_belongs_to", (("Port", "Service"),)),
        ("flow_source", (("ServiceResourceFlow", "Port"),)),
        ("flow_target", (("ServiceResourceFlow", "Port"),)),
    ),
    "SvcV-4": (
        ("performed_by", (("ServiceFunction", "ServiceOrResource"),)),
        ("flow_source", (("ResourceFlow", "ServiceFunction"),)),
        ("flow_target", (("ResourceFlow", "ServiceFunction"),)),
    ),
    "SvcV-5": (("maps_to", (("OperationalActivity", "ServiceFunction"),)),),
    "SvcV-7": (
        ("measure_applies_to", (("Measure", "ServiceModelElement"),)),
        ("valid_during", (("Measure", "Timeframe"), ("ServiceModelElement", "Timeframe"))),
    ),
    "L3": (
        ("interaction_source", (("LogicalInteraction", "LogicalActiveResource"),)),
        ("interaction_target", (("LogicalInteraction", "LogicalActiveResource"),)),
        ("conveys", (("LogicalInteraction", "LogicalPassiveResource"),)),
    ),
    "L4": (
        ("control_flow_source", (("OperationalControlFlow", "OperationalActivity"),)),
        ("control_flow_target", (("OperationalControlFlow", "OperationalActivity"),)),
    ),
    "L8": (("relates_to", (("LogicalRequirement", "LogicalConstraint"),)),),
    "P3": (
        ("interaction_source", (("ResourceInteraction", "PhysicalActiveResource"),)),
        ("interaction_target", (("ResourceInteraction", "PhysicalActiveResource"),)),
        ("implements", (("PhysicalActiveResource", "Protocol"),)),
        ("conforms_to", (("Protocol", "Standard"),)),
    ),
    "L4-P4": (("realizes", (("OperationalActivity", "ResourceFunction"),)),),
    "P8": (("relates_to", (("ResourceRequirement", "ResourceConstraint"),)),),
})


def _as_mapping(value: Any, label: str = "Mimari veri") -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        if isinstance(raw, Mapping):
            return raw
    raise ValueError(f"{label} JSON nesnesi veya to_dict destekleyen model olmalıdır.")


def _records(raw: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    value = raw.get(key, ())
    if value is None:
        return ()
    if isinstance(value, Mapping):
        value = value.values()
    if not isinstance(value, (list, tuple, set, frozenset)) and not hasattr(value, "__iter__"):
        return ()
    result: list[Mapping[str, Any]] = []
    for item in value:
        try:
            result.append(_as_mapping(item, key))
        except ValueError:
            result.append({"_invalid_record": repr(item)[:120]})
    return tuple(result)


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value).casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _truthy_collection(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_truthy_collection(item) for item in value)
    return bool(value)


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    target_id: str = "",
    view_id: str = "",
    missing_fields: Iterable[str] = (),
    evidence_ids: Iterable[str] = (),
    blocking: bool | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,
        message=message,
        target_id=_clean(target_id),
        view_id=_clean(view_id),
        missing_fields=tuple(_clean(item) for item in missing_fields if _clean(item)),
        evidence_ids=tuple(_clean(item) for item in evidence_ids if _clean(item)),
        blocking=(severity == SEVERITY_ERROR if blocking is None else blocking),
    )


def _unique_findings(values: Iterable[ValidationFinding]) -> tuple[ValidationFinding, ...]:
    by_id: dict[str, ValidationFinding] = {}
    for finding in values:
        by_id.setdefault(finding.finding_id, finding)
    rank = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFORMATION: 2, "info": 2}
    return tuple(sorted(
        by_id.values(),
        key=lambda item: (
            rank.get(item.severity, 9), item.view_id, item.code, item.target_id,
        ),
    ))


def _has_error(findings: Iterable[ValidationFinding]) -> bool:
    return any(item.severity == SEVERITY_ERROR for item in findings)


def _item_id(item: Mapping[str, Any], relationship: bool = False) -> str:
    keys = ("stable_id", "relationship_id", "id") if relationship else ("stable_id", "element_id", "id")
    return next((_clean(item.get(key)) for key in keys if _clean(item.get(key))), "")


def _item_type(item: Mapping[str, Any], relationship: bool = False) -> str:
    key = "relationship_type" if relationship else "element_type"
    return _clean(item.get(key, item.get("type", "")))


def _valid_source_evidence(link: Mapping[str, Any]) -> bool:
    kind = _clean(link.get("derivation_kind"))
    if kind not in AUTOMATIC_DERIVATION_KINDS:
        return False
    required = (
        "source_item_id", "source_document", "source_location",
        "evidence_text", "evidence_fingerprint", "producer", "producer_version",
    )
    if any(not _clean(link.get(key)) for key in required):
        return False
    try:
        expected = evidence_fingerprint_for(
            link["source_document"], link["source_item_id"],
            link["source_location"], link["evidence_text"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    confidence = link.get("confidence_score")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        return False
    return expected == _clean(link.get("evidence_fingerprint")).casefold()


def _source_evidence(item: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    links = item.get("evidence_links", ())
    if not isinstance(links, (list, tuple)):
        return ()
    return tuple(
        link for link in links
        if isinstance(link, Mapping) and _valid_source_evidence(link)
    )


def _source_requirements_are_covered(
    item: Mapping[str, Any], links: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    requirement_ids = {
        _clean(value).upper()
        for value in item.get("source_requirement_ids", ()) or ()
        if _clean(value)
    }
    evidence_ids = {
        _clean(link.get("source_item_id")).upper() for link in links
        if _clean(link.get("source_item_id"))
    }
    return tuple(sorted(requirement_ids - evidence_ids))


def _contains_explicit_phrase(text: str, phrase: str) -> bool:
    normalized_text = _norm(text)
    normalized_phrase = _norm(phrase)
    if not normalized_phrase:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text,
    ) is not None


def _review_is_usable(item: Mapping[str, Any], root_status: str) -> bool:
    status = _clean(item.get("lifecycle_status", item.get("status", ""))).casefold()
    if status:
        return status in {"approved", "edited"}
    review = _clean(item.get("review_status"))
    if review:
        return review in {REVIEW_APPROVED, REVIEW_EDITED, "approved", "edited"}
    # KART 3 yayımında kök ``approved`` ise eski/haricî kayıtlar item
    # seviyesinde durum taşımayabilir. Bu yalnız yayımlanmış zarf için kabul edilir.
    return root_status.casefold() == "approved"


def _management_records(management_state: Any) -> Mapping[str, Mapping[str, Any]]:
    if management_state is None:
        return MappingProxyType({})
    raw = _as_mapping(management_state, "Mimari yönetim durumu")
    records = raw.get("records", {})
    if not isinstance(records, Mapping):
        return MappingProxyType({})
    return MappingProxyType({
        _clean(str(key)): _as_mapping(value, "Yönetilen aday")
        for key, value in records.items()
        if _clean(str(key))
    })


def _integrity_findings(
    architecture: Mapping[str, Any],
    elements: tuple[Mapping[str, Any], ...],
    relationships: tuple[Mapping[str, Any], ...],
    profile_id: str,
    framework_version: str,
    management_state: Any,
) -> tuple[tuple[ValidationFinding, ...], frozenset[str]]:
    findings: list[ValidationFinding] = []
    blocked_ids: set[str] = set()
    root_status = _clean(architecture.get("status"))

    expected_profile = FRAMEWORK_PROFILES.get(profile_id)
    if expected_profile is None:
        findings.append(_finding(
            "invalid_framework_profile", SEVERITY_ERROR,
            f"Desteklenmeyen çerçeve profili: {profile_id or 'belirsiz/eksik'}.",
            target_id=profile_id,
        ))
    elif framework_version != expected_profile.version:
        findings.append(_finding(
            "framework_version_mismatch", SEVERITY_ERROR,
            f"Profil sürümü {expected_profile.version} olmalıdır; "
            f"gelen değer {framework_version or 'belirsiz/eksik'}.",
            target_id=profile_id,
            missing_fields=("framework_version",),
        ))

    valid_element_types = set(KNOWN_ELEMENT_TYPES)
    for candidate_profile in FRAMEWORK_PROFILES.values():
        for view in candidate_profile.view_definitions:
            valid_element_types.update(view.required_element_types)
            valid_element_types.update(view.optional_element_types)
            for group in view.required_any_of_element_types:
                valid_element_types.update(group)
    valid_relationship_types = set(KNOWN_RELATIONSHIP_TYPES)
    for candidate_profile in FRAMEWORK_PROFILES.values():
        for view in candidate_profile.view_definitions:
            valid_relationship_types.update(view.required_relationships)
            valid_relationship_types.update(view.optional_relationships)
            for group in view.required_any_of_relationships:
                valid_relationship_types.update(group)

    seen: set[str] = set()
    for item in elements:
        item_id = _item_id(item)
        if not item_id:
            item_id = "belirsiz-element"
            findings.append(_finding(
                "missing_stable_id", SEVERITY_ERROR,
                "Mimari öğenin kararlı kimliği yok.",
                target_id=item_id,
                missing_fields=("stable_id",),
            ))
        elif item_id in seen:
            findings.append(_finding(
                "duplicate_stable_id", SEVERITY_ERROR,
                f"Yinelenen mimari kimlik: {item_id}.", target_id=item_id,
            ))
        seen.add(item_id)

        item_type = _item_type(item)
        if item_type not in valid_element_types:
            findings.append(_finding(
                "invalid_element_type", SEVERITY_ERROR,
                f"Geçersiz mimari öğe türü: {item_type or 'belirsiz/eksik'}.",
                target_id=item_id,
                missing_fields=("element_type",),
            ))
            blocked_ids.add(item_id)
        if _clean(item.get("framework_profile_id")) not in {"", profile_id}:
            findings.append(_finding(
                "item_profile_mismatch", SEVERITY_ERROR,
                "Mimari öğe rapor profiliyle uyuşmuyor.", target_id=item_id,
            ))
            blocked_ids.add(item_id)
        source_links = _source_evidence(item)
        uncovered_requirements = _source_requirements_are_covered(item, source_links)
        if not source_links or uncovered_requirements:
            findings.append(_finding(
                "missing_source_evidence", SEVERITY_ERROR,
                "Mimari öğe geçerli, birebir ve gereksinim kimliklerini "
                "kapsayan kaynak kanıtı taşımıyor.",
                target_id=item_id,
                missing_fields=("evidence_links", *uncovered_requirements),
            ))
            blocked_ids.add(item_id)
        if not _review_is_usable(item, root_status):
            findings.append(_finding(
                "unapproved_candidate_used", SEVERITY_ERROR,
                "Onaylanmamış aday kanonik mimari/görünüm verisi olarak kullanılamaz.",
                target_id=item_id,
                missing_fields=("user_review",),
            ))
            blocked_ids.add(item_id)
        lifecycle = _clean(item.get("lifecycle_status", item.get("status", ""))).casefold()
        if lifecycle == "stale" or bool(item.get("stale_requirement_ids")):
            findings.append(_finding(
                "stale_item_used", SEVERITY_ERROR,
                "Eski/stale mimari öğe yeni görünümde kullanılamaz.",
                target_id=item_id,
            ))
            blocked_ids.add(item_id)

        if item_type in {"Protocol", "Standard"}:
            name = _clean(item.get("name"))
            evidence_corpus = " ".join(
                _clean(link.get("evidence_text")) for link in source_links
            )
            if not name or not _contains_explicit_phrase(evidence_corpus, name):
                findings.append(_finding(
                    "unsupported_protocol_or_standard", SEVERITY_ERROR,
                    f"{item_type} adı kaynak kanıtında birebir bulunamadı: "
                    f"{name or 'belirsiz/eksik'}.",
                    target_id=item_id,
                    missing_fields=("source_protocol_or_standard",),
                ))
                blocked_ids.add(item_id)

    element_ids = {_item_id(item) for item in elements if _item_id(item)}
    for item in relationships:
        item_id = _item_id(item, relationship=True) or "belirsiz-relationship"
        if item_id in seen:
            findings.append(_finding(
                "duplicate_stable_id", SEVERITY_ERROR,
                f"Yinelenen mimari kimlik: {item_id}.", target_id=item_id,
            ))
        seen.add(item_id)
        relationship_type = _item_type(item, relationship=True)
        if relationship_type not in valid_relationship_types:
            findings.append(_finding(
                "invalid_relationship_type", SEVERITY_ERROR,
                f"Geçersiz mimari ilişki türü: {relationship_type or 'belirsiz/eksik'}.",
                target_id=item_id,
                missing_fields=("relationship_type",),
            ))
            blocked_ids.add(item_id)
        if _clean(item.get("framework_profile_id")) not in {"", profile_id}:
            findings.append(_finding(
                "item_profile_mismatch", SEVERITY_ERROR,
                "Mimari ilişki rapor profiliyle uyuşmuyor.", target_id=item_id,
            ))
            blocked_ids.add(item_id)
        endpoints = {
            "source_element_id": _clean(item.get("source_element_id")),
            "target_element_id": _clean(item.get("target_element_id")),
        }
        missing_endpoints = tuple(
            f"{key}:{value or 'belirsiz/eksik'}"
            for key, value in endpoints.items() if value not in element_ids
        )
        if missing_endpoints:
            findings.append(_finding(
                "dangling_relationship", SEVERITY_ERROR,
                "Mimari ilişkinin kaynak veya hedef ucu modelde bulunmuyor.",
                target_id=item_id,
                missing_fields=missing_endpoints,
            ))
            blocked_ids.add(item_id)
        if endpoints["source_element_id"] == endpoints["target_element_id"]:
            findings.append(_finding(
                "invalid_relationship_cardinality", SEVERITY_ERROR,
                "İlişki iki farklı mimari uca bağlanmalıdır.", target_id=item_id,
            ))
            blocked_ids.add(item_id)
        source_links = _source_evidence(item)
        uncovered_requirements = _source_requirements_are_covered(item, source_links)
        if not source_links or uncovered_requirements:
            findings.append(_finding(
                "missing_source_evidence", SEVERITY_ERROR,
                "Mimari ilişki geçerli, birebir ve gereksinim kimliklerini "
                "kapsayan kaynak kanıtı taşımıyor.",
                target_id=item_id,
                missing_fields=("evidence_links", *uncovered_requirements),
            ))
            blocked_ids.add(item_id)
        if not _review_is_usable(item, root_status):
            findings.append(_finding(
                "unapproved_candidate_used", SEVERITY_ERROR,
                "Onaylanmamış ilişki adayı görünüm verisi olarak kullanılamaz.",
                target_id=item_id,
                missing_fields=("user_review",),
            ))
            blocked_ids.add(item_id)
        lifecycle = _clean(item.get("lifecycle_status", item.get("status", ""))).casefold()
        if lifecycle == "stale" or bool(item.get("stale_requirement_ids")):
            findings.append(_finding(
                "stale_item_used", SEVERITY_ERROR,
                "Eski/stale mimari ilişki yeni görünümde kullanılamaz.",
                target_id=item_id,
            ))
            blocked_ids.add(item_id)

    management_records = _management_records(management_state)
    for record_id in architecture.get("source_record_ids", ()) or ():
        key = _clean(record_id)
        record = management_records.get(key)
        if record is None:
            if management_records:
                findings.append(_finding(
                    "management_record_missing", SEVERITY_WARNING,
                    "Yayımlanan kaydın yönetim kaydı bulunamadı.", target_id=key,
                    blocking=False,
                ))
            continue
        status = _clean(record.get("status")).casefold()
        if status == "stale":
            findings.append(_finding(
                "stale_item_used", SEVERITY_ERROR,
                "Yayımlanan mimari stale bir yönetim kaydına dayanıyor.",
                target_id=key,
            ))
        elif status not in {"approved", "edited"}:
            findings.append(_finding(
                "unapproved_candidate_used", SEVERITY_ERROR,
                f"Yayım kaynağı onaylı/düzenlenmiş değil: {status or 'belirsiz'}.",
                target_id=key,
            ))

    # Ayrı aday havuzundaki bir kayıt, kanonik bir target kimliğine bağlıysa
    # açık kullanıcı kararı olmadan kullanılmış sayılır.
    decisions = {
        _clean(item.get("candidate_id")): item
        for item in _records(architecture, "review_decisions")
        if _clean(item.get("candidate_id"))
    }
    for proposal in _records(architecture, "candidate_proposals"):
        proposal_id = _clean(proposal.get("proposal_id"))
        target_id = _clean(proposal.get("target_stable_id"))
        if target_id and target_id in element_ids:
            decision = decisions.get(proposal_id, {})
            accepted = _clean(decision.get("decision")) in {"Kabul et", "Düzenle"}
            if not accepted:
                findings.append(_finding(
                    "unapproved_candidate_used", SEVERITY_ERROR,
                    "Kanonik kayda bağlı adayın açık kullanıcı onayı yok.",
                    target_id=target_id,
                    missing_fields=("review_decision",),
                ))
                blocked_ids.add(target_id)

    return _unique_findings(findings), frozenset(blocked_ids)


def _view_lookup(
    profile_id: str,
    additional: Mapping[str, ViewDefinition] | Sequence[ViewDefinition] | None,
) -> Mapping[str, ViewDefinition]:
    result: dict[str, ViewDefinition] = {}
    profile = FRAMEWORK_PROFILES.get(profile_id)
    if profile:
        result.update({item.view_id.casefold(): item for item in profile.view_definitions})
    if additional:
        values = additional.values() if isinstance(additional, Mapping) else additional
        for value in values:
            view = value if isinstance(value, ViewDefinition) else ViewDefinition.from_dict(value)
            result[view.view_id.casefold()] = view
    return MappingProxyType(result)


def _has_context(
    kind: str,
    context: Mapping[str, Any],
    elements: Sequence[Mapping[str, Any]],
) -> bool:
    aliases = {
        "scenario": ("scenario", "scenarios", "senaryo", "senaryolar"),
        "state": ("state", "states", "durum", "durumlar"),
        "time": ("time", "times", "timeframe", "timeframes", "zaman", "zamanlar"),
    }[kind]
    if any(_truthy_collection(context.get(key)) for key in aliases):
        return True
    suffixes = {
        "scenario": ("scenario",),
        "state": ("state",),
        "time": ("timeframe", "temporalwhole"),
    }[kind]
    return any(_norm(_item_type(item)).endswith(suffixes) for item in elements)


def _context_requirements(view: ViewDefinition) -> tuple[str, ...]:
    text = _norm(" ".join(view.data_prerequisites))
    required: list[str] = []
    if re.search(r"\b(senaryo|scenario)", text):
        required.append("scenario")
    if re.search(r"\b(durum|state)", text):
        required.append("state")
    if re.search(r"\b(zaman|time|temporal)", text):
        required.append("time")
    return tuple(required)


def _connects_types(
    relationship: Mapping[str, Any],
    expected_a: str,
    expected_b: str,
    element_types: Mapping[str, str],
) -> bool:
    source = element_types.get(_clean(relationship.get("source_element_id")), "")
    target = element_types.get(_clean(relationship.get("target_element_id")), "")
    return {source, target} == {expected_a, expected_b}


def _view_cardinality_findings(
    view: ViewDefinition,
    elements: tuple[Mapping[str, Any], ...],
    relationships: tuple[Mapping[str, Any], ...],
) -> tuple[ValidationFinding, ...]:
    findings: list[ValidationFinding] = []
    type_counts: dict[str, int] = {}
    for item in elements:
        item_type = _item_type(item)
        type_counts[item_type] = type_counts.get(item_type, 0) + 1
    for item_type, minimum in VIEW_MINIMUM_CARDINALITIES.get(view.view_id, ()):
        actual = type_counts.get(item_type, 0)
        if actual < minimum:
            findings.append(_finding(
                "cardinality_violation", SEVERITY_ERROR,
                f"{view.view_id} için en az {minimum} {item_type} gerekir; bulunan {actual}.",
                view_id=view.view_id,
                missing_fields=(f"{item_type}:min={minimum}:actual={actual}",),
            ))

    element_types = {_item_id(item): _item_type(item) for item in elements}
    for relationship_type, allowed_pairs in VIEW_RELATION_ENDPOINT_CARDINALITIES.get(
        view.view_id, (),
    ):
        candidates = tuple(
            item for item in relationships
            if _item_type(item, True) == relationship_type
        )
        valid = any(
            any(
                _connects_types(item, left_type, right_type, element_types)
                for left_type, right_type in allowed_pairs
            )
            for item in candidates
        )
        if candidates and not valid:
            allowed = tuple(f"{left}<->{right}" for left, right in allowed_pairs)
            findings.append(_finding(
                "cardinality_violation", SEVERITY_ERROR,
                f"{view.view_id} içindeki {relationship_type} ilişkisi gerekli "
                "uç türlerine bağlanmıyor.",
                view_id=view.view_id,
                missing_fields=(relationship_type, *allowed),
            ))

    if view.view_id == "L4":
        performers = tuple(
            item for item in relationships if _item_type(item, True) == "performs"
        )
        for activity in (item for item in elements if _item_type(item) == "OperationalActivity"):
            activity_id = _item_id(activity)
            valid = any(
                activity_id in {
                    _clean(rel.get("source_element_id")),
                    _clean(rel.get("target_element_id")),
                }
                and (
                    element_types.get(_clean(rel.get("source_element_id"))) in {"Node", "Role"}
                    or element_types.get(_clean(rel.get("target_element_id"))) in {"Node", "Role"}
                )
                for rel in performers
            )
            if not valid:
                findings.append(_finding(
                    "cardinality_violation", SEVERITY_ERROR,
                    "L4 içinde her OperationalActivity en az bir Node veya Role icracısı gerektirir.",
                    target_id=activity_id,
                    view_id=view.view_id,
                    missing_fields=("performer:Node|Role",),
                ))

    if view.view_id in {"L8", "P8"}:
        targets = (
            {"LogicalActiveResource", "LogicalBehaviour", "LogicalPassiveResource"}
            if view.view_id == "L8"
            else {"PhysicalActiveResource", "PhysicalBehaviour", "PhysicalPassiveResource"}
        )
        valid = any(
            _item_type(rel, True) == "applies_to"
            and (
                element_types.get(_clean(rel.get("source_element_id"))) in targets
                or element_types.get(_clean(rel.get("target_element_id"))) in targets
            )
            for rel in relationships
        )
        if not valid:
            findings.append(_finding(
                "cardinality_violation", SEVERITY_ERROR,
                f"{view.view_id} için applies_to ilişkisi uygulanabilir hedef türüne bağlanmalıdır.",
                view_id=view.view_id,
                missing_fields=("applies_to_target",),
            ))

    if view.view_id == "P4":
        active = any(
            _item_type(rel, True) in {"uses", "performs"}
            and _connects_types(rel, "ResourceFunction", "PhysicalActiveResource", element_types)
            for rel in relationships
        )
        passive = any(
            _item_type(rel, True) in {"uses", "delivers"}
            and _connects_types(rel, "ResourceFunction", "PhysicalPassiveResource", element_types)
            for rel in relationships
        )
        if not active or not passive:
            missing = []
            if not active:
                missing.append("ResourceFunction-(uses|performs)-PhysicalActiveResource")
            if not passive:
                missing.append("ResourceFunction-(uses|delivers)-PhysicalPassiveResource")
            findings.append(_finding(
                "cardinality_violation", SEVERITY_ERROR,
                "P4 alternatif ilişki grupları gerekli uç türlerine bağlanmıyor.",
                view_id=view.view_id,
                missing_fields=missing,
            ))
    return _unique_findings(findings)


def _validate_views(
    selected_view_ids: Sequence[str],
    view_catalog: Mapping[str, ViewDefinition],
    elements: tuple[Mapping[str, Any], ...],
    relationships: tuple[Mapping[str, Any], ...],
    blocked_ids: frozenset[str],
    context: Mapping[str, Any],
) -> tuple[ValidationDimensionResult, frozenset[str], frozenset[str]]:
    all_findings: list[ValidationFinding] = []
    results: list[ViewValidationResult] = []
    used_element_types: set[str] = set()
    used_relationship_types: set[str] = set()
    if not selected_view_ids:
        finding = _finding(
            "selected_view_missing", SEVERITY_ERROR,
            "Doğrulanacak en az bir görünüm kimliği seçilmelidir.",
            missing_fields=("selected_view_ids",),
        )
        return ValidationDimensionResult(
            DIMENSION_VIEW_GENERATABILITY, False, STATUS_NOT_GENERATABLE,
            (finding,), (),
        ), frozenset(), frozenset()

    usable_elements = tuple(item for item in elements if _item_id(item) not in blocked_ids)
    usable_relationships = tuple(
        item for item in relationships
        if _item_id(item, relationship=True) not in blocked_ids
        and _clean(item.get("source_element_id")) not in blocked_ids
        and _clean(item.get("target_element_id")) not in blocked_ids
    )
    element_types = {_item_type(item) for item in usable_elements}
    relationship_types = {_item_type(item, True) for item in usable_relationships}

    for raw_view_id in selected_view_ids:
        view_id = _clean(raw_view_id)
        view = view_catalog.get(view_id.casefold())
        findings: list[ValidationFinding] = []
        if view is None:
            findings.append(_finding(
                "unknown_view", SEVERITY_ERROR,
                f"Görünüm katalogda bulunamadı: {view_id or 'belirsiz/eksik'}.",
                view_id=view_id,
            ))
        else:
            used_element_types.update(view.required_element_types)
            used_relationship_types.update(view.required_relationships)
            for group in view.required_any_of_element_types:
                used_element_types.update(group)
            for group in view.required_any_of_relationships:
                used_relationship_types.update(group)

            missing_elements = tuple(
                item_type for item_type in view.required_element_types
                if item_type not in element_types
            )
            if missing_elements:
                findings.append(_finding(
                    "missing_required_element", SEVERITY_ERROR,
                    f"{view.view_id} için zorunlu mimari öğe türleri eksik.",
                    view_id=view.view_id,
                    missing_fields=missing_elements,
                ))
            missing_relationships = tuple(
                item_type for item_type in view.required_relationships
                if item_type not in relationship_types
            )
            if missing_relationships:
                findings.append(_finding(
                    "missing_required_relationship", SEVERITY_ERROR,
                    f"{view.view_id} için zorunlu mimari ilişki türleri eksik.",
                    view_id=view.view_id,
                    missing_fields=missing_relationships,
                ))
            for group in view.required_any_of_element_types:
                if not any(item_type in element_types for item_type in group):
                    findings.append(_finding(
                        "missing_required_element_choice", SEVERITY_ERROR,
                        f"{view.view_id} için alternatif zorunlu öğe grubu eksik.",
                        view_id=view.view_id,
                        missing_fields=("|".join(group),),
                    ))
            for group in view.required_any_of_relationships:
                if not any(item_type in relationship_types for item_type in group):
                    findings.append(_finding(
                        "missing_required_relationship_choice", SEVERITY_ERROR,
                        f"{view.view_id} için alternatif zorunlu ilişki grubu eksik.",
                        view_id=view.view_id,
                        missing_fields=("|".join(group),),
                    ))
            findings.extend(_view_cardinality_findings(
                view, usable_elements, usable_relationships,
            ))
            for context_kind in _context_requirements(view):
                if not _has_context(context_kind, context, usable_elements):
                    findings.append(_finding(
                        "missing_view_context", SEVERITY_ERROR,
                        f"{view.view_id} için gerekli {context_kind} bilgisi bulunmuyor.",
                        view_id=view.view_id,
                        missing_fields=(context_kind,),
                    ))
        normalized = _unique_findings(findings)
        generatable = not _has_error(normalized)
        result = ViewValidationResult(
            view_id=view_id,
            generatable=generatable,
            status=STATUS_GENERATABLE if generatable else STATUS_NOT_GENERATABLE,
            findings=normalized,
        )
        results.append(result)
        all_findings.extend(normalized)

    normalized_all = _unique_findings(all_findings)
    passed = bool(results) and all(item.generatable for item in results)
    return ValidationDimensionResult(
        DIMENSION_VIEW_GENERATABILITY,
        passed,
        STATUS_GENERATABLE if passed else STATUS_NOT_GENERATABLE,
        normalized_all,
        tuple(results),
    ), frozenset(used_element_types), frozenset(used_relationship_types)


def _mapping_findings(
    items: Sequence[Mapping[str, Any]],
    relationship: bool,
    table: Mapping[str, MappingRule],
    code_prefix: str,
) -> tuple[ValidationFinding, ...]:
    findings: list[ValidationFinding] = []
    for item in items:
        item_id = _item_id(item, relationship)
        item_type = _item_type(item, relationship)
        rule = table.get(item_type)
        if rule is None:
            findings.append(_finding(
                f"{code_prefix}_mapping_missing", SEVERITY_WARNING,
                f"{item_type or 'belirsiz/eksik'} için çerçeve eşlemesi yok.",
                target_id=item_id,
                missing_fields=(item_type or "type",),
                blocking=False,
            ))
        elif not rule.complete:
            findings.append(_finding(
                f"{code_prefix}_mapping_incomplete", SEVERITY_INFORMATION,
                f"{item_type} eşlemesi {rule.status}; normatif ayrıntı "
                "belirsiz/eksik olarak kaydedildi.",
                target_id=item_id,
                missing_fields=(item_type,),
                blocking=False,
            ))
    return _unique_findings(findings)


def _framework_findings(
    architecture: Mapping[str, Any],
    profile_id: str,
    framework_version: str,
    elements: tuple[Mapping[str, Any], ...],
    relationships: tuple[Mapping[str, Any], ...],
    view_result: ValidationDimensionResult,
    integrity_result: ValidationDimensionResult,
    application_profile: Mapping[str, Any] | None,
) -> ValidationDimensionResult:
    findings: list[ValidationFinding] = []
    semantic_pass = view_result.passed and integrity_result.passed

    if profile_id == DODAF_PROFILE_ID:
        dodaf_element_mapping_findings = _mapping_findings(
            elements, False, DODAF_DM2_ELEMENT_MAPPINGS, "dm2_concept",
        )
        dodaf_relationship_mapping_findings = _mapping_findings(
            relationships, True, DODAF_DM2_RELATIONSHIP_MAPPINGS, "dm2_relationship",
        )
        findings.extend(dodaf_element_mapping_findings)
        findings.extend(dodaf_relationship_mapping_findings)
        if any(
            item.code.endswith("_mapping_missing")
            for item in (*dodaf_element_mapping_findings, *dodaf_relationship_mapping_findings)
        ):
            semantic_pass = False
        findings.append(_finding(
            "pes_export_not_implemented", SEVERITY_INFORMATION,
            "PES aktarımı ve yerel PES şema doğrulayıcısı uygulanmadı; "
            "DoDAF uyumluluğu iddia edilemez.",
            target_id=profile_id,
            missing_fields=("PES exporter", "PES validator"),
            blocking=False,
        ))
        if framework_version != DODAF_VERSION:
            semantic_pass = False
        status = (
            "DoDAF ile hizalı taslak"
            if semantic_pass
            else "DoDAF ile hizalı taslak — zorunlu kontroller eksik"
        )
    elif profile_id == NAF_PROFILE_ID:
        naf_element_mapping_findings = _mapping_findings(
            elements, False, NAF_ARCHIMATE_ELEMENT_MAPPINGS, "naf_archimate_element",
        )
        naf_relationship_mapping_findings = _mapping_findings(
            relationships, True, NAF_ARCHIMATE_RELATIONSHIP_MAPPINGS,
            "naf_archimate_relationship",
        )
        findings.extend(naf_element_mapping_findings)
        findings.extend(naf_relationship_mapping_findings)
        if any(
            item.code.endswith("_mapping_missing")
            for item in (*naf_element_mapping_findings, *naf_relationship_mapping_findings)
        ):
            semantic_pass = False
        profile_data: Mapping[str, Any] = application_profile or {}
        supplied_name = _clean(profile_data.get(
            "name", architecture.get("application_profile", "")
        ))
        supplied_version = _clean(profile_data.get(
            "version", architecture.get("application_profile_version", "")
        ))
        if supplied_name and _norm(supplied_name) != "archimate":
            findings.append(_finding(
                "archimate_profile_mismatch", SEVERITY_ERROR,
                "NAF 4.1 EHSİM varsayılan uygulama profili ArchiMate olmalıdır.",
                target_id=profile_id,
                missing_fields=("ArchiMate",),
            ))
            semantic_pass = False
        if supplied_version and supplied_version != "3.2":
            findings.append(_finding(
                "archimate_profile_version_mismatch", SEVERITY_ERROR,
                "NAF 4.1 uygulama profili sürümü ArchiMate 3.2 olmalıdır.",
                target_id=profile_id,
                missing_fields=("3.2",),
            ))
            semantic_pass = False
        if not supplied_name or not supplied_version:
            findings.append(_finding(
                "archimate_profile_metadata_missing", SEVERITY_INFORMATION,
                "Mimari örneğinde uygulama profili etiketi yok; katalog varsayılanı "
                "ArchiMate 3.2 kullanıldı, gerçek araç profili belirsiz/eksik.",
                target_id=profile_id,
                missing_fields=("application_profile", "application_profile_version"),
                blocking=False,
            ))

        specializations = profile_data.get("element_specializations", {})
        if specializations and not isinstance(specializations, Mapping):
            findings.append(_finding(
                "archimate_specialization_map_invalid", SEVERITY_ERROR,
                "ArchiMate element_specializations alanı JSON nesnesi olmalıdır.",
                target_id=profile_id,
            ))
            semantic_pass = False
        elif isinstance(specializations, Mapping):
            for item in elements:
                item_id = _item_id(item)
                item_type = _item_type(item)
                rule = NAF_ARCHIMATE_ELEMENT_MAPPINGS.get(item_type)
                specialization = _clean(specializations.get(item_id))
                if specialization and rule and _norm(specialization) not in {
                    _norm(value) for value in rule.target_types
                }:
                    findings.append(_finding(
                        "archimate_specialization_mismatch", SEVERITY_ERROR,
                        f"{item_type} için ArchiMate özel türü izinli NAF 4.1 "
                        "eşleme kümesinde değil.",
                        target_id=item_id,
                        missing_fields=rule.target_types,
                    ))
                    semantic_pass = False
        findings.append(_finding(
            "naf_exchange_not_implemented", SEVERITY_INFORMATION,
            "NAF IM / ArchiMate 3.2 exchange doğrulayıcısı uygulanmadı; "
            "NAF uyumluluğu iddia edilemez.",
            target_id=profile_id,
            missing_fields=("NAF exchange validator",),
            blocking=False,
        ))
        if framework_version != NAF_VERSION:
            semantic_pass = False
        status = (
            "NAF ile hizalı taslak"
            if semantic_pass
            else "NAF ile hizalı taslak — zorunlu semantik kontroller eksik"
        )
    else:
        findings.append(_finding(
            "framework_mapping_unavailable", SEVERITY_ERROR,
            "Seçilen profil için çerçeve eşleme motoru bulunmuyor.",
            target_id=profile_id,
        ))
        semantic_pass = False
        status = "Çerçeve uyumluluğu doğrulanamadı"

    normalized = _unique_findings(findings)
    # Bu sürümde normatif exchange doğrulayıcısı olmadığından conformance
    # kapısı geçmiş sayılmaz. ``aligned`` yerel semantik hizalamayı ayrıca
    # gösterir; böylece ``passed=True`` yanlışlıkla "uyumlu" diye okunamaz.
    return ValidationDimensionResult(
        DIMENSION_FRAMEWORK_CONFORMANCE,
        False,
        status,
        normalized,
        aligned=semantic_pass and not _has_error(normalized),
        conformant=False,
    )


def validate_architecture(
    architecture: Mapping[str, Any] | Any,
    *,
    selected_view_ids: Sequence[str] | None = None,
    management_state: Mapping[str, Any] | Any | None = None,
    context_data: Mapping[str, Any] | None = None,
    view_definitions: Mapping[str, ViewDefinition] | Sequence[ViewDefinition] | None = None,
    application_profile: Mapping[str, Any] | None = None,
) -> ArchitectureValidationReport:
    """Mimariyi üç bağımsız sonuç alanında doğrular.

    ``architecture`` bir KART 1 ``ArchitectureSnapshot``, KART 3
    ``architecture.json`` sözlüğü veya aynı alanları taşıyan ham JSON
    nesnesi olabilir. Ham nesne kabul edilmesi bilinçlidir: katı model
    kurucusunun reddedeceği dangling/kanıtsız kayıtları rapora bulgu olarak
    döndürebilmek gerekir.
    """

    raw = _as_mapping(architecture)
    profile_id = _clean(raw.get("framework_profile_id")).casefold()
    profile = FRAMEWORK_PROFILES.get(profile_id)
    framework_version = _clean(raw.get("framework_version"))
    if not framework_version and profile is not None:
        # KART 3 yayım zarfı profil sürümünü henüz ayrı alan olarak
        # saklamıyor; katalogdaki sabit profil sürümü kullanılır.
        framework_version = profile.version

    elements = _records(raw, "elements")
    relationships = _records(raw, "relationships")
    integrity_findings, blocked_ids = _integrity_findings(
        raw, elements, relationships, profile_id, framework_version, management_state,
    )
    integrity_passed = not _has_error(integrity_findings)
    integrity_result = ValidationDimensionResult(
        DIMENSION_MODEL_INTEGRITY,
        integrity_passed,
        STATUS_INTEGRITY_VALID if integrity_passed else STATUS_INTEGRITY_INVALID,
        integrity_findings,
    )

    selected = tuple(selected_view_ids) if selected_view_ids is not None else tuple(
        raw.get("selected_view_ids", ()) or ()
    )
    catalog = _view_lookup(profile_id, view_definitions)
    merged_context: dict[str, Any] = {}
    embedded_context = raw.get("context_data", {})
    if isinstance(embedded_context, Mapping):
        merged_context.update(embedded_context)
    if context_data:
        merged_context.update(context_data)
    for key in (
        "scenario", "scenarios", "senaryo", "senaryolar",
        "state", "states", "durum", "durumlar",
        "time", "times", "timeframe", "timeframes", "zaman", "zamanlar",
    ):
        if key in raw and key not in merged_context:
            merged_context[key] = raw[key]

    view_result, _used_elements, _used_relationships = _validate_views(
        selected, catalog, elements, relationships, blocked_ids, merged_context,
    )
    framework_result = _framework_findings(
        raw, profile_id, framework_version, elements, relationships,
        view_result, integrity_result, application_profile,
    )
    return ArchitectureValidationReport(
        framework_profile_id=profile_id,
        framework_version=framework_version,
        view_generatability=view_result,
        model_integrity=integrity_result,
        framework_conformance=framework_result,
    )


def validate_view_generatability(
    architecture: Mapping[str, Any] | Any,
    **kwargs: Any,
) -> ValidationDimensionResult:
    """Yalnız görünüm üretilebilirliği sonucunu döndürür."""

    return validate_architecture(architecture, **kwargs).view_generatability


def validate_model_integrity(
    architecture: Mapping[str, Any] | Any,
    **kwargs: Any,
) -> ValidationDimensionResult:
    """Yalnız mimari model bütünlüğü sonucunu döndürür."""

    return validate_architecture(architecture, **kwargs).model_integrity


def validate_framework_conformance(
    architecture: Mapping[str, Any] | Any,
    **kwargs: Any,
) -> ValidationDimensionResult:
    """Yalnız çerçeve hizalama/uyumluluk kapısı sonucunu döndürür."""

    return validate_architecture(architecture, **kwargs).framework_conformance


__all__ = [
    "ArchitectureValidationReport",
    "DIMENSION_FRAMEWORK_CONFORMANCE",
    "DIMENSION_MODEL_INTEGRITY",
    "DIMENSION_VIEW_GENERATABILITY",
    "DODAF_DM2_CONCEPT_MAPPING_TABLE",
    "DODAF_DM2_ELEMENT_MAPPINGS",
    "DODAF_DM2_RELATIONSHIP_MAPPING_TABLE",
    "DODAF_DM2_RELATIONSHIP_MAPPINGS",
    "MappingRule",
    "NAF_ARCHIMATE_ELEMENT_MAPPINGS",
    "NAF_ARCHIMATE_RELATIONSHIP_MAPPINGS",
    "NAF_IM_ARCHIMATE_ELEMENT_MAPPING_TABLE",
    "NAF_IM_ARCHIMATE_RELATIONSHIP_MAPPING_TABLE",
    "SEVERITY_ERROR",
    "SEVERITY_INFORMATION",
    "SEVERITY_WARNING",
    "STATUS_GENERATABLE",
    "STATUS_INTEGRITY_INVALID",
    "STATUS_INTEGRITY_VALID",
    "STATUS_NOT_GENERATABLE",
    "VIEW_MINIMUM_CARDINALITIES",
    "VIEW_RELATION_ENDPOINT_CARDINALITIES",
    "ValidationDimensionResult",
    "ViewValidationResult",
    "validate_architecture",
    "validate_framework_conformance",
    "validate_model_integrity",
    "validate_view_generatability",
]
