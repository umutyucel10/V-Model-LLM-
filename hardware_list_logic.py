# -*- coding: utf-8 -*-
"""Akıllı Donanım Listesi için bağımsız veri modeli ve doğrulama kuralları.

Bu modül LLM çağrısı veya arayüz kodu içermez. Yapay zekâdan, katalogdan ya da
kullanıcıdan gelecek ham veriyi tek ve güvenli bir sözleşmeye dönüştürür.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping


DSB = "DSB"
ELIGIBLE_REQUIREMENT_TYPES = frozenset({"SGD", "STT"})
HARDWARE_STATUSES = ("Önerilen", "İnceleniyor", "Onaylandı", "Reddedildi")
HARDWARE_RISK_LEVELS = ("Belirsiz", "Düşük", "Orta", "Yüksek")
HARDWARE_CATEGORIES = (
    "İşlem Birimi",
    "FPGA / DSP",
    "Bellek / Depolama",
    "Güç Birimi",
    "RF Birimi",
    "Haberleşme Arayüzü",
    "Sensör",
    "Kablo / Konnektör",
    "Soğutma",
    "Mekanik",
    "Test / Ölçüm",
    "Diğer",
)
DEFAULT_CATEGORY = "Sınıflandırılmamış"
ISSUE_SEVERITIES = ("Hata", "Uyarı", "Bilgi")

_HARDWARE_ID_RE = re.compile(r"^HW-(\d{3,})$")
_STATUS_ALIASES = {
    "önerilen": "Önerilen",
    "oneri": "Önerilen",
    "öneri": "Önerilen",
    "suggested": "Önerilen",
    "draft": "Önerilen",
    "inceleniyor": "İnceleniyor",
    "incelemede": "İnceleniyor",
    "review": "İnceleniyor",
    "in review": "İnceleniyor",
    "onaylandı": "Onaylandı",
    "onaylandi": "Onaylandı",
    "approved": "Onaylandı",
    "reddedildi": "Reddedildi",
    "rejected": "Reddedildi",
}
_RISK_ALIASES = {
    "belirsiz": "Belirsiz",
    "unknown": "Belirsiz",
    "dsb": "Belirsiz",
    "düşük": "Düşük",
    "dusuk": "Düşük",
    "low": "Düşük",
    "orta": "Orta",
    "medium": "Orta",
    "yüksek": "Yüksek",
    "yuksek": "Yüksek",
    "high": "Yüksek",
}


def _clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or default


def _normalize_choice(value: Any, aliases: Mapping[str, str], default: str) -> str:
    # Türkçe büyük "İ" casefold sırasında "i" + birleşik nokta üretir.
    # Kullanıcıdan gelen ve daha önce normalize edilmiş değerler aynı anahtara düşmeli.
    key = _clean_text(value).casefold().replace("\u0307", "")
    return aliases.get(key, default)


def _normalize_quantity(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, quantity)


def _normalize_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str) and value.strip().endswith("%"):
            confidence = float(value.strip().removesuffix("%")) / 100
        else:
            confidence = float(value)
            if 1 < confidence <= 100:
                confidence /= 100
    except (TypeError, ValueError):
        return None
    if not 0 <= confidence <= 1:
        return None
    return round(confidence, 4)


def normalize_hardware_id(value: Any) -> str:
    candidate = _clean_text(value).upper()
    return candidate if _HARDWARE_ID_RE.fullmatch(candidate) else ""


def normalize_requirement_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_ids: Iterable[Any] = re.split(r"[,;\n]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        raw_ids = value
    else:
        raw_ids = [value]

    result: list[str] = []
    seen: set[str] = set()
    for raw_id in raw_ids:
        requirement_id = _clean_text(raw_id).upper()
        if requirement_id and requirement_id not in seen:
            result.append(requirement_id)
            seen.add(requirement_id)
    return result


def normalize_specifications(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    specifications: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _clean_text(raw_key)
        if not key:
            continue
        specifications[key] = _clean_text(raw_value, DSB)
    return specifications


@dataclass(slots=True)
class HardwareItem:
    item_id: str
    category: str = DEFAULT_CATEGORY
    description: str = DSB
    quantity: int = 1
    specifications: dict[str, str] = field(default_factory=dict)
    linked_requirements: list[str] = field(default_factory=list)
    status: str = "Önerilen"
    risk: str = "Belirsiz"
    confidence: float | None = None
    manufacturer: str = DSB
    part_number: str = DSB
    rationale: str = DSB
    review_note: str = ""
    source_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ID": self.item_id,
            "category": self.category,
            "description": self.description,
            "quantity": self.quantity,
            "specifications": dict(self.specifications),
            "linked_requirements": list(self.linked_requirements),
            "status": self.status,
            "risk": self.risk,
            "confidence": self.confidence,
            "manufacturer": self.manufacturer,
            "part_number": self.part_number,
            "rationale": self.rationale,
            "review_note": self.review_note,
            "source_excerpt": self.source_excerpt,
        }


def normalize_hardware_item(raw: Mapping[str, Any], item_id: str | None = None) -> HardwareItem:
    """Ham bir kaydı güvenli HardwareItem sözleşmesine dönüştürür."""
    normalized_id = normalize_hardware_id(item_id or raw.get("ID") or raw.get("item_id"))
    if not normalized_id:
        raise ValueError("Geçerli bir donanım ID'si gerekli (ör. HW-001).")

    return HardwareItem(
        item_id=normalized_id,
        category=_clean_text(raw.get("category"), DEFAULT_CATEGORY),
        description=_clean_text(raw.get("description") or raw.get("name"), DSB),
        quantity=_normalize_quantity(raw.get("quantity", 1)),
        specifications=normalize_specifications(
            raw.get("specifications", raw.get("specs", {}))
        ),
        linked_requirements=normalize_requirement_ids(
            raw.get("linked_requirements", raw.get("requirement_ids"))
        ),
        status=_normalize_choice(raw.get("status"), _STATUS_ALIASES, "Önerilen"),
        risk=_normalize_choice(raw.get("risk"), _RISK_ALIASES, "Belirsiz"),
        confidence=_normalize_confidence(raw.get("confidence")),
        manufacturer=_clean_text(raw.get("manufacturer"), DSB),
        part_number=_clean_text(raw.get("part_number"), DSB),
        rationale=_clean_text(raw.get("rationale"), DSB),
        review_note=_clean_text(raw.get("review_note") or raw.get("review_notes")),
        source_excerpt=_clean_text(raw.get("source_excerpt") or raw.get("source")),
    )


def next_hardware_id(existing_ids: Iterable[str]) -> str:
    highest = 0
    for item_id in existing_ids:
        match = _HARDWARE_ID_RE.fullmatch(_clean_text(item_id).upper())
        if match:
            highest = max(highest, int(match.group(1)))
    return f"HW-{highest + 1:03d}"


def build_hardware_registry(
    raw_items: Iterable[Mapping[str, Any]],
    existing: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Yeni kayıtları mevcut donanım havuzuna çakışmasız biçimde ekler."""
    registry: dict[str, dict[str, Any]] = {}

    for existing_id, raw in (existing or {}).items():
        if not isinstance(raw, Mapping):
            continue
        normalized_id = normalize_hardware_id(existing_id) or next_hardware_id(registry)
        item = normalize_hardware_item(raw, normalized_id)
        registry[item.item_id] = item.to_dict()

    for raw in raw_items:
        if not isinstance(raw, Mapping):
            continue
        preferred_id = normalize_hardware_id(raw.get("ID") or raw.get("item_id"))
        item_id = preferred_id if preferred_id and preferred_id not in registry else next_hardware_id(registry)
        item = normalize_hardware_item(raw, item_id)
        registry[item.item_id] = item.to_dict()

    return registry


def eligible_requirement_records(flat_data: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    """Donanım tahsisine uygun, içerikli SGD/STT kayıtlarını döndürür."""
    records: list[dict[str, str]] = []
    for fallback_id, raw in flat_data.items():
        if not isinstance(raw, Mapping):
            continue
        requirement_type = _clean_text(raw.get("type")).upper()
        content = _clean_text(raw.get("content"))
        requirement_id = _clean_text(raw.get("ID") or fallback_id).upper()
        if requirement_type not in ELIGIBLE_REQUIREMENT_TYPES or not requirement_id or not content:
            continue
        records.append({
            "requirement_id": requirement_id,
            "requirement_type": requirement_type,
            "content": content,
        })
    return records


def validate_hardware_item(
    item: HardwareItem | Mapping[str, Any],
    known_requirement_ids: Iterable[str] | None = None,
) -> list[str]:
    """Kullanıcı incelemesinde gösterilecek veri kalitesi uyarılarını üretir."""
    normalized = item if isinstance(item, HardwareItem) else normalize_hardware_item(
        item, item.get("ID") or item.get("item_id")
    )
    warnings: list[str] = []

    if normalized.description == DSB:
        warnings.append("Donanım açıklaması DSB.")
    if normalized.category == DEFAULT_CATEGORY:
        warnings.append("Donanım kategorisi belirlenmedi.")
    if not normalized.linked_requirements:
        warnings.append("Herhangi bir SGD/STT gereksinimine bağlanmadı.")
    if not normalized.specifications:
        warnings.append("Teknik özellik bulunmuyor.")
    elif any(value == DSB for value in normalized.specifications.values()):
        warnings.append("Bazı teknik özellikler DSB.")

    if normalized.part_number != DSB and normalized.manufacturer == DSB:
        warnings.append("Parça numarası var ancak üretici DSB.")
    if normalized.confidence is None:
        warnings.append("Öneri güven değeri bulunmuyor.")

    if known_requirement_ids is not None:
        known = {str(item_id).strip().upper() for item_id in known_requirement_ids}
        unknown = [req_id for req_id in normalized.linked_requirements if req_id not in known]
        if unknown:
            warnings.append("Bilinmeyen gereksinim bağlantısı: " + ", ".join(unknown))

    return warnings


def build_hardware_trace_links(
    registry: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Çoktan çoğa gereksinim → donanım bağlantı kayıtlarını üretir."""
    links: list[dict[str, str]] = []
    for fallback_id, raw in registry.items():
        if not isinstance(raw, Mapping):
            continue
        item_id = normalize_hardware_id(raw.get("ID") or fallback_id)
        if not item_id:
            continue
        for requirement_id in normalize_requirement_ids(raw.get("linked_requirements")):
            links.append({
                "source_id": requirement_id,
                "target_id": item_id,
                "link_type": "allocated_to",
            })
    return links



def update_hardware_record(
    registry: dict[str, dict[str, Any]],
    item_id: str,
    changes: Mapping[str, Any],
    mark_in_review: bool = True,
) -> dict[str, Any]:
    """Bir kaydı normalize ederek günceller; değişiklik onayı incelemeye döndürür."""
    normalized_id = normalize_hardware_id(item_id)
    if not normalized_id or normalized_id not in registry:
        raise KeyError(f"Donanım kaydı bulunamadı: {item_id}")
    if not isinstance(changes, Mapping):
        raise TypeError("Donanım değişiklikleri sözlük biçiminde olmalı.")

    merged = dict(registry[normalized_id])
    merged.update(dict(changes))
    merged["ID"] = normalized_id
    if mark_in_review:
        merged["status"] = "İnceleniyor"
    normalized = normalize_hardware_item(merged, normalized_id).to_dict()
    registry[normalized_id] = normalized
    return normalized


def _approval_issue_pairs(
    item: HardwareItem,
    known_requirement_ids: Iterable[str] | None = None,
) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    if item.description == DSB:
        issues.append(("DESCRIPTION_DSB", "Donanım açıklaması DSB olamaz."))
    if item.category == DEFAULT_CATEGORY:
        issues.append(("CATEGORY_MISSING", "Donanım kategorisi belirlenmeli."))
    if not item.linked_requirements:
        issues.append(("TRACE_MISSING", "En az bir SGD/STT bağlantısı gerekli."))
    if item.manufacturer == DSB:
        issues.append(("MANUFACTURER_DSB", "Üretici bilgisi DSB olamaz."))
    if item.part_number == DSB:
        issues.append(("PART_NUMBER_DSB", "Parça numarası DSB olamaz."))
    if not item.specifications:
        issues.append(("SPECIFICATIONS_MISSING", "En az bir teknik özellik gerekli."))
    elif any(value == DSB for value in item.specifications.values()):
        issues.append(("SPECIFICATION_DSB", "Teknik özelliklerde DSB değer kalmamalı."))

    if known_requirement_ids is not None:
        known = {_clean_text(value).upper() for value in known_requirement_ids}
        unknown = [value for value in item.linked_requirements if value not in known]
        if unknown:
            issues.append((
                "TRACE_UNKNOWN",
                "Bilinmeyen gereksinim bağlantısı: " + ", ".join(unknown),
            ))
    return issues


def approval_blockers(
    item: HardwareItem | Mapping[str, Any],
    known_requirement_ids: Iterable[str] | None = None,
) -> list[str]:
    normalized = item if isinstance(item, HardwareItem) else normalize_hardware_item(
        item, item.get("ID") or item.get("item_id")
    )
    return [message for _code, message in _approval_issue_pairs(
        normalized, known_requirement_ids
    )]


def transition_hardware_status(
    registry: dict[str, dict[str, Any]],
    item_id: str,
    target_status: str,
    known_requirement_ids: Iterable[str] | None = None,
    review_note: str = "",
) -> dict[str, Any]:
    """Kayıt durumunu mühendislik kapısı kurallarıyla değiştirir."""
    normalized_id = normalize_hardware_id(item_id)
    if not normalized_id or normalized_id not in registry:
        raise KeyError(f"Donanım kaydı bulunamadı: {item_id}")
    status = _normalize_choice(target_status, _STATUS_ALIASES, "")
    if status not in {"İnceleniyor", "Onaylandı", "Reddedildi"}:
        raise ValueError(f"Desteklenmeyen durum geçişi: {target_status}")

    item = normalize_hardware_item(registry[normalized_id], normalized_id)
    note = _clean_text(review_note)
    if status == "Onaylandı":
        blockers = approval_blockers(item, known_requirement_ids)
        if blockers:
            raise ValueError("Onay engelleri:\n• " + "\n• ".join(blockers))
    if status == "Reddedildi" and not note:
        raise ValueError("Reddetme gerekçesi zorunludur.")

    updated = item.to_dict()
    updated["status"] = status
    if note:
        updated["review_note"] = note
    registry[normalized_id] = normalize_hardware_item(
        updated, normalized_id
    ).to_dict()
    return registry[normalized_id]


def hardware_compatibility_report(
    registry: Mapping[str, Mapping[str, Any]],
    flat_data: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Kayıt, katalog, teknik özellik ve izlenebilirlik tutarlılığını denetler."""
    report: list[dict[str, str]] = []
    eligible = eligible_requirement_records(flat_data or {})
    known_ids = {record["requirement_id"] for record in eligible}
    normalized_items: list[HardwareItem] = []

    def add(severity: str, item_id: str, code: str, message: str) -> None:
        report.append({
            "severity": severity,
            "item_id": item_id,
            "code": code,
            "message": message,
        })

    for fallback_id, raw in registry.items():
        if not isinstance(raw, Mapping):
            add("Hata", str(fallback_id), "RECORD_INVALID", "Kayıt sözlük biçiminde değil.")
            continue
        try:
            item = normalize_hardware_item(raw, raw.get("ID") or fallback_id)
        except (TypeError, ValueError) as error:
            add("Hata", str(fallback_id), "RECORD_INVALID", str(error))
            continue
        normalized_items.append(item)
        for code, message in _approval_issue_pairs(
            item, known_ids if flat_data is not None else None
        ):
            add("Hata", item.item_id, code, message)
        if item.risk == "Yüksek":
            add("Uyarı", item.item_id, "HIGH_RISK", "Kayıt yüksek riskli olarak işaretlendi.")
        if item.rationale == DSB:
            add("Uyarı", item.item_id, "RATIONALE_DSB", "Donanım gerekçesi DSB.")
        if item.confidence is None and item.status == "Önerilen":
            add("Bilgi", item.item_id, "CONFIDENCE_MISSING", "Yapay zekâ güven değeri bulunmuyor.")

    by_description: dict[tuple[str, str], list[str]] = {}
    part_manufacturers: dict[str, dict[str, list[str]]] = {}
    part_specs: dict[tuple[str, str], dict[str, dict[str, list[str]]]] = {}
    for item in normalized_items:
        if item.status == "Reddedildi":
            continue
        description_key = (
            item.category.casefold().replace("\u0307", ""),
            item.description.casefold().replace("\u0307", ""),
        )
        by_description.setdefault(description_key, []).append(item.item_id)
        if item.part_number != DSB:
            part_key = item.part_number.casefold().replace("\u0307", "")
            manufacturer_key = item.manufacturer.casefold().replace("\u0307", "")
            part_manufacturers.setdefault(part_key, {}).setdefault(
                manufacturer_key, []
            ).append(item.item_id)
            exact_part = (manufacturer_key, part_key)
            for spec_name, spec_value in item.specifications.items():
                spec_key = spec_name.casefold().replace("\u0307", "")
                value_key = spec_value.casefold().replace("\u0307", "")
                part_specs.setdefault(exact_part, {}).setdefault(
                    spec_key, {}
                ).setdefault(value_key, []).append(item.item_id)

    for item_ids in by_description.values():
        if len(item_ids) > 1:
            message = "Aynı kategori ve tanıma sahip mükerrer kayıtlar: " + ", ".join(item_ids)
            for item_id in item_ids:
                add("Uyarı", item_id, "DUPLICATE_ITEM", message)

    for manufacturers in part_manufacturers.values():
        non_dsb = [key for key in manufacturers if key and key != DSB.casefold()]
        if len(non_dsb) > 1:
            affected = [item_id for key in non_dsb for item_id in manufacturers[key]]
            message = "Aynı parça numarası farklı üreticilerle eşleşiyor: " + ", ".join(affected)
            for item_id in affected:
                add("Hata", item_id, "PART_MANUFACTURER_CONFLICT", message)

    for specs in part_specs.values():
        for spec_name, values in specs.items():
            non_dsb_values = [key for key in values if key != DSB.casefold()]
            if len(non_dsb_values) > 1:
                affected = [item_id for key in non_dsb_values for item_id in values[key]]
                message = f"Aynı parça için '{spec_name}' teknik özelliği çelişiyor: " + ", ".join(affected)
                for item_id in affected:
                    add("Hata", item_id, "SPECIFICATION_CONFLICT", message)

    if flat_data is not None:
        active_allocations: dict[str, list[str]] = {item_id: [] for item_id in known_ids}
        for item in normalized_items:
            if item.status == "Reddedildi":
                continue
            for requirement_id in item.linked_requirements:
                if requirement_id in active_allocations:
                    active_allocations[requirement_id].append(item.item_id)
        for requirement_id, item_ids in active_allocations.items():
            if not item_ids:
                add(
                    "Hata",
                    requirement_id,
                    "UNCOVERED_REQUIREMENT",
                    "SGD/STT gereksinimine etkin bir donanım tahsis edilmedi.",
                )

    order = {severity: index for index, severity in enumerate(ISSUE_SEVERITIES)}
    report.sort(key=lambda issue: (
        order.get(issue["severity"], 99), issue["item_id"], issue["code"]
    ))
    return report


def compatibility_summary(issues: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    summary = {"total": 0, "errors": 0, "warnings": 0, "info": 0}
    keys = {"Hata": "errors", "Uyarı": "warnings", "Bilgi": "info"}
    for issue in issues:
        severity = _clean_text(issue.get("severity"))
        summary["total"] += 1
        if severity in keys:
            summary[keys[severity]] += 1
    return summary


def exportable_hardware_records(
    registry: Mapping[str, Mapping[str, Any]],
    approved_only: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for fallback_id, raw in registry.items():
        if not isinstance(raw, Mapping):
            continue
        try:
            item = normalize_hardware_item(raw, raw.get("ID") or fallback_id)
        except (TypeError, ValueError):
            continue
        if approved_only and item.status != "Onaylandı":
            continue
        records.append(item.to_dict())
    return sorted(records, key=lambda record: record["ID"])

def hardware_registry_summary(
    registry: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    summary = {
        "total": 0,
        "suggested": 0,
        "in_review": 0,
        "approved": 0,
        "rejected": 0,
        "high_risk": 0,
        "with_dsb": 0,
    }
    status_keys = {
        "Önerilen": "suggested",
        "İnceleniyor": "in_review",
        "Onaylandı": "approved",
        "Reddedildi": "rejected",
    }

    for fallback_id, raw in registry.items():
        if not isinstance(raw, Mapping):
            continue
        item = normalize_hardware_item(raw, raw.get("ID") or fallback_id)
        summary["total"] += 1
        summary[status_keys[item.status]] += 1
        if item.risk == "Yüksek":
            summary["high_risk"] += 1
        if (
            DSB in {item.description, item.manufacturer, item.part_number, item.rationale}
            or any(value == DSB for value in item.specifications.values())
        ):
            summary["with_dsb"] += 1

    return summary
