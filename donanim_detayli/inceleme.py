# -*- coding: utf-8 -*-
"""Donanım Detaylı İnceleme ekranı için salt-okunur veri projeksiyonları.

Bu katman Tkinter bileşeni oluşturmaz ve katalog verisini değiştirmez. Katalog,
izlenebilirlik ve kullanıcı bindirmelerini ayrıntı ekranının tablolarına taşır.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

from donanim_kartlari_model import MISSING_VALUE, PLACEHOLDER_IMAGE, WORKING_STATES, clean_text, is_missing


TECHNICAL_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("Fiziksel", "length", "Uzunluk", "dimension_unit"),
    ("Fiziksel", "width", "Genişlik", "dimension_unit"),
    ("Fiziksel", "height", "Yükseklik", "dimension_unit"),
    ("Fiziksel", "diameter", "Çap", "dimension_unit"),
    ("Fiziksel", "weight", "Ağırlık", "weight_unit"),
    ("Termal", "operating_temperature_min", "Çalışma sıcaklığı min.", "temperature_unit"),
    ("Termal", "operating_temperature_max", "Çalışma sıcaklığı maks.", "temperature_unit"),
    ("Termal", "storage_temperature_min", "Depolama sıcaklığı min.", "temperature_unit"),
    ("Termal", "storage_temperature_max", "Depolama sıcaklığı maks.", "temperature_unit"),
    ("Elektriksel", "supply_voltage", "Besleme gerilimi", "V"),
    ("Elektriksel", "power_consumption", "Güç tüketimi", "W"),
    ("Elektriksel", "electrical_interfaces", "Elektriksel arayüzler", ""),
    ("Mekanik", "mechanical_interfaces", "Mekanik arayüzler", ""),
    ("Haberleşme", "communication_interfaces", "Haberleşme arayüzleri", ""),
    ("Çevresel", "environmental_resistance", "Çevresel dayanım", ""),
    ("Güvenilirlik", "reliability", "Güvenilirlik bilgisi", ""),
    ("Standartlar", "standards_and_certifications", "Standartlar ve sertifikalar", ""),
)


def display(value: Any) -> str:
    if value is None or is_missing(value):
        return MISSING_VALUE
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {display(item)}" for key, item in value.items()) or MISSING_VALUE
    if isinstance(value, (list, tuple, set)):
        return ", ".join(clean_text(item) for item in value if clean_text(item)) or MISSING_VALUE
    return clean_text(value, MISSING_VALUE)


def item_index(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        clean_text(item.get("hardware_id")): deepcopy(dict(item))
        for item in catalog.get("hardware_items", [])
        if isinstance(item, Mapping) and clean_text(item.get("hardware_id"))
    }


def trace_node_index(report: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        clean_text(node.get("id")): dict(node)
        for node in (report or {}).get("nodes", [])
        if isinstance(node, Mapping) and clean_text(node.get("id"))
    }


def trace_edges(report: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return [dict(edge) for edge in (report or {}).get("edges", []) if isinstance(edge, Mapping)]


def parent_chain(catalog: Mapping[str, Any], hardware_id: str) -> list[dict[str, Any]]:
    by_id = item_index(catalog)
    chain: list[dict[str, Any]] = []
    current = by_id.get(hardware_id)
    visited: set[str] = set()
    while current:
        current_id = clean_text(current.get("hardware_id"))
        if not current_id or current_id in visited:
            break
        visited.add(current_id)
        chain.append(current)
        parent_id = clean_text(current.get("parent_id"))
        current = by_id.get(parent_id)
    return list(reversed(chain))


def breadcrumb(catalog: Mapping[str, Any], hardware_id: str) -> str:
    values = [display(item.get("part_name")) for item in parent_chain(catalog, hardware_id)]
    return "  ›  ".join(values) if values else MISSING_VALUE


def child_items(catalog: Mapping[str, Any], hardware_id: str) -> list[dict[str, Any]]:
    by_id = item_index(catalog)
    parent = by_id.get(hardware_id, {})
    explicit = {clean_text(value) for value in parent.get("child_ids", []) if clean_text(value)}
    return sorted(
        [
            item for item_id, item in by_id.items()
            if item_id in explicit or clean_text(item.get("parent_id")) == hardware_id
        ],
        key=lambda item: display(item.get("part_name")).casefold(),
    )


def _evidence_for(item: Mapping[str, Any], field: str) -> dict[str, Any]:
    candidates = {field, f"technical_data.{field}"}
    for evidence in item.get("source_evidence", []) or []:
        if isinstance(evidence, Mapping) and clean_text(evidence.get("field_name")) in candidates:
            return dict(evidence)
    return {}


def _value_parts(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            "value": value.get("value", value.get("nominal", MISSING_VALUE)),
            "unit": value.get("unit", MISSING_VALUE),
            "minimum": value.get("minimum", value.get("min", MISSING_VALUE)),
            "maximum": value.get("maximum", value.get("max", MISSING_VALUE)),
            "tolerance": value.get("tolerance", MISSING_VALUE),
            "state_value": value.get("state_value", value.get("by_state", MISSING_VALUE)),
        }
    return {
        "value": value, "unit": MISSING_VALUE, "minimum": MISSING_VALUE,
        "maximum": MISSING_VALUE, "tolerance": MISSING_VALUE,
        "state_value": MISSING_VALUE,
    }


def technical_rows(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    technical = dict(item.get("technical_data") or {})
    field_confidence = dict(item.get("field_confidence") or {})
    manual_fields = set(item.get("manual_fields") or [])
    rows: list[dict[str, Any]] = []
    for category, field, label, unit_reference in TECHNICAL_FIELDS:
        parts = _value_parts(technical.get(field, MISSING_VALUE))
        unit = technical.get(unit_reference, unit_reference) if unit_reference else parts["unit"]
        if not is_missing(parts["unit"]):
            unit = parts["unit"]
        evidence = _evidence_for(item, field)
        rows.append({
            "category": category, "field": field, "parameter": label,
            "value": display(parts["value"]), "unit": display(unit),
            "minimum": display(parts["minimum"]), "maximum": display(parts["maximum"]),
            "tolerance": display(parts["tolerance"]), "state_value": display(parts["state_value"]),
            "source_document": display(evidence.get("source_document")),
            "location": display(evidence.get("location")),
            "confidence": display(
                evidence.get("field_confidence", field_confidence.get(field, field_confidence.get(f"technical_data.{field}")))
            ),
            "certainty": "Manuel" if f"technical_data.{field}" in manual_fields else display(evidence.get("certainty")),
        })
    for name, raw_value in dict(technical.get("custom_parameters") or {}).items():
        parts = _value_parts(raw_value)
        evidence = _evidence_for(item, clean_text(name))
        rows.append({
            "category": "Kullanıcı tanımlı", "field": f"custom_parameters.{name}",
            "parameter": clean_text(name), "value": display(parts["value"]),
            "unit": display(parts["unit"]), "minimum": display(parts["minimum"]),
            "maximum": display(parts["maximum"]), "tolerance": display(parts["tolerance"]),
            "state_value": display(parts["state_value"]),
            "source_document": display(evidence.get("source_document")),
            "location": display(evidence.get("location")),
            "confidence": display(evidence.get("field_confidence")),
            "certainty": "Manuel" if f"technical_data.custom_parameters.{name}" in manual_fields else display(evidence.get("certainty")),
        })
    return rows


def _relationship(edge: Mapping[str, Any]) -> str:
    return clean_text(edge.get("relationship_type", edge.get("relationship")))


def requirement_rows(item: Mapping[str, Any], report: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    nodes = trace_node_index(report)
    edges = trace_edges(report)
    hardware_id = clean_text(item.get("hardware_id"))
    test_types = ("test", "doğrulama", "geçerleme", "kabul")
    explicit_tests = [clean_text(value) for value in item.get("test_ids", []) if clean_text(value)]
    rows: list[dict[str, Any]] = []
    for requirement_id in item.get("requirement_ids", []) or []:
        requirement_id = clean_text(requirement_id)
        node = nodes.get(requirement_id, {})
        related_tests = list(explicit_tests)
        relation = "Bağlı"
        for edge in edges:
            source, target = clean_text(edge.get("source_id")), clean_text(edge.get("target_id"))
            edge_relation = _relationship(edge)
            if {source, target} == {requirement_id, hardware_id}:
                relation = edge_relation or relation
            other = target if source == requirement_id else source if target == requirement_id else ""
            other_node = nodes.get(other, {})
            node_type = clean_text(other_node.get("node_type")).casefold()
            if other and any(token in node_type for token in test_types) and other not in related_tests:
                related_tests.append(other)
        rows.append({
            "id": requirement_id, "text": display(node.get("description", node.get("title"))),
            "level": display(node.get("v_model_level")), "relation": relation,
            "compliance": display(item.get("requirement_statuses", {}).get(requirement_id, "İnceleme gerekli") if isinstance(item.get("requirement_statuses"), Mapping) else "İnceleme gerekli"),
            "tests": ", ".join(related_tests) or MISSING_VALUE,
            "test_result": display(item.get("test_results", {}).get(requirement_id) if isinstance(item.get("test_results"), Mapping) else None),
            "source": display(node.get("source_document")),
            "confidence": display(node.get("confidence_level", node.get("confidence"))),
        })
    return rows


def connection_rows(
    catalog: Mapping[str, Any], item: Mapping[str, Any], report: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    by_id = item_index(catalog)
    hardware_id = clean_text(item.get("hardware_id"))
    rows: list[dict[str, Any]] = []
    parent_id = clean_text(item.get("parent_id"))
    if parent_id and not is_missing(parent_id):
        parent = by_id.get(parent_id, {})
        rows.append({"direction": "↑", "type": "Üst sistem", "id": parent_id, "name": display(parent.get("part_name")), "source": "Ürün ağacı"})
    for child in child_items(catalog, hardware_id):
        rows.append({"direction": "↓", "type": "Alt parça", "id": child.get("hardware_id"), "name": display(child.get("part_name")), "source": "Ürün ağacı"})
    technical = dict(item.get("technical_data") or {})
    for field, label in (
        ("mechanical_interfaces", "Mekanik arayüz"),
        ("electrical_interfaces", "Elektriksel arayüz"),
        ("communication_interfaces", "Haberleşme / veri bağlantısı"),
        ("software_interfaces", "Yazılımsal arayüz"),
        ("power_connections", "Güç bağlantısı"),
        ("data_connections", "Veri bağlantısı"),
    ):
        for value in technical.get(field, []) or []:
            rows.append({"direction": "↔", "type": label, "id": MISSING_VALUE, "name": display(value), "source": "Teknik veri"})
    for dependent_id in item.get("dependent_hardware_ids", []) or []:
        dependent = by_id.get(clean_text(dependent_id), {})
        rows.append({
            "direction": "→", "type": "Bağımlı parça", "id": clean_text(dependent_id),
            "name": display(dependent.get("part_name")), "source": "Donanım kataloğu",
        })
    nodes = trace_node_index(report)
    for edge in trace_edges(report):
        source, target = clean_text(edge.get("source_id")), clean_text(edge.get("target_id"))
        if hardware_id not in {source, target}:
            continue
        other = target if source == hardware_id else source
        node = nodes.get(other, {})
        rows.append({
            "direction": "→" if source == hardware_id else "←",
            "type": display(_relationship(edge)), "id": other,
            "name": display(node.get("title", node.get("description"))),
            "source": display(edge.get("source_document")),
        })
    return rows


def state_rows(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    profiles = {
        clean_text(record.get("state")): dict(record)
        for record in item.get("state_profiles", []) or [] if isinstance(record, Mapping)
    }
    states = list(dict.fromkeys([*WORKING_STATES, *(item.get("working_states") or []), *profiles]))
    rows = []
    for state in states:
        record = profiles.get(state, {})
        rows.append({
            "state": state,
            "parameters": display(record.get("changed_parameters")),
            "requirements": display(record.get("affected_requirements")),
            "parts": display(record.get("affected_parts")),
            "risks": display(record.get("active_risks")),
            "tests": display(record.get("required_tests")),
            "behavior": display(record.get("expected_behavior")),
        })
    return rows


def alternative_links(catalog: Mapping[str, Any], hardware_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for link in catalog.get("alternative_links", []) or []:
        if not isinstance(link, Mapping):
            continue
        if clean_text(link.get("source_hardware_id")) == hardware_id:
            result[clean_text(link.get("alternative_hardware_id"))] = dict(link)
    return result


def alternative_ids(catalog: Mapping[str, Any], hardware_id: str) -> list[str]:
    current = item_index(catalog).get(hardware_id, {})
    return list(dict.fromkeys([
        *(clean_text(value) for value in current.get("alternative_ids", []) if clean_text(value)),
        *alternative_links(catalog, hardware_id).keys(),
    ]))


def _number(value: Any) -> float | None:
    if value is None or is_missing(value):
        return None
    try:
        return float(str(value).replace(",", ".").split()[0])
    except (TypeError, ValueError):
        return None


def _assessment(field: str, current: Any, alternative: Any) -> str:
    if is_missing(current) or is_missing(alternative):
        return "Veri eksik"
    left, right = _number(current), _number(alternative)
    if left is None or right is None:
        return "Nötr" if display(current).casefold() == display(alternative).casefold() else "İnceleme gerekli"
    if abs(left - right) < 1e-12:
        return "Nötr"
    if field in {"weight", "power_consumption", "operating_temperature_min", "storage_temperature_min", "cost"}:
        return "Olumlu" if right < left else "Olumsuz"
    if field == "supply_voltage":
        return "Kritik uyumsuzluk"
    return "Olumlu" if right > left else "Olumsuz"


def alternative_comparison_rows(
    catalog: Mapping[str, Any], hardware_id: str, alternative_id: str,
) -> list[dict[str, Any]]:
    by_id = item_index(catalog)
    current, alternative = by_id.get(hardware_id, {}), by_id.get(alternative_id, {})
    current_td, alternative_td = current.get("technical_data", {}) or {}, alternative.get("technical_data", {}) or {}
    rows = [
        {"parameter": "Parça adı / numarası", "current": f"{display(current.get('part_name'))} / {display(current.get('part_number'))}", "alternative": f"{display(alternative.get('part_name'))} / {display(alternative.get('part_number'))}", "unit": "—", "assessment": "Nötr"},
        {"parameter": "Üretici", "current": display(current.get("manufacturer")), "alternative": display(alternative.get("manufacturer")), "unit": "—", "assessment": "Nötr"},
    ]
    for _category, field, label, unit_reference in TECHNICAL_FIELDS:
        current_value, alternative_value = current_td.get(field), alternative_td.get(field)
        unit = current_td.get(unit_reference, unit_reference) if unit_reference else MISSING_VALUE
        rows.append({
            "parameter": label, "current": display(current_value),
            "alternative": display(alternative_value), "unit": display(unit),
            "assessment": _assessment(field, current_value, alternative_value),
        })
    link = alternative_links(catalog, hardware_id).get(alternative_id, {})
    compatibility = display(link.get("compatibility_status"))
    compatibility_assessment = {
        "Tam uyumlu": "Olumlu", "Koşullu uyumlu": "İnceleme gerekli",
        "Uyumlu değil": "Kritik uyumsuzluk", "Veri eksik": "Veri eksik",
        "İncelenmedi": "Veri eksik",
    }.get(compatibility, "Veri eksik")
    current_requirements = list(current.get("requirement_ids") or [])
    rows.extend((
        {"parameter": "Gereksinim uyumu", "current": display(current_requirements), "alternative": compatibility, "unit": "—", "assessment": compatibility_assessment},
        {"parameter": "Karşılanan / karşılanmayan gereksinimler", "current": display(current_requirements), "alternative": f"Karşılanan: {display(link.get('met_requirements'))}; Karşılanmayan: {display(link.get('unmet_requirements'))}", "unit": "—", "assessment": "Kritik uyumsuzluk" if link.get("unmet_requirements") else "Veri eksik" if not link else "Olumlu"},
        {"parameter": "Test uyumu", "current": display(current.get("test_ids")), "alternative": display(alternative.get("test_ids")), "unit": "—", "assessment": "Veri eksik" if not alternative.get("test_ids") else "İnceleme gerekli"},
        {"parameter": "Güven skoru", "current": display(current.get("confidence_score")), "alternative": display(alternative.get("confidence_score")), "unit": "/100", "assessment": _assessment("confidence_score", current.get("confidence_score"), alternative.get("confidence_score"))},
        {"parameter": "Yeni riskler", "current": display(current.get("open_risks")), "alternative": display(link.get("new_risks", alternative.get("open_risks"))), "unit": "—", "assessment": "Olumsuz" if link.get("new_risks") else "Veri eksik"},
        {"parameter": "Maliyet", "current": display(current.get("cost_information")), "alternative": display(alternative.get("cost_information")), "unit": display(alternative.get("cost_unit")), "assessment": _assessment("cost", current.get("cost_information"), alternative.get("cost_information"))},
        {"parameter": "Tedarik", "current": display(current.get("supply_information")), "alternative": display(alternative.get("supply_information")), "unit": "—", "assessment": "Veri eksik" if is_missing(alternative.get("supply_information")) else "İnceleme gerekli"},
        {"parameter": "Eksik bilgiler", "current": display(current.get("missing_information")), "alternative": display(alternative.get("missing_information")), "unit": "—", "assessment": "Veri eksik" if alternative.get("missing_information") else "Nötr"},
    ))
    return rows


def source_rows(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "field": display(evidence.get("field_name")),
            "document": display(evidence.get("source_document")),
            "location": display(evidence.get("location")),
            "evidence": display(evidence.get("evidence_text")),
            "method": display(evidence.get("extraction_method")),
            "confidence": display(evidence.get("field_confidence")),
            "certainty": display(evidence.get("certainty")),
            "path": clean_text(evidence.get("source_path", evidence.get("source_document"))),
        }
        for evidence in item.get("source_evidence", []) or [] if isinstance(evidence, Mapping)
    ]
    for path in item.get("attached_datasheets", []) or []:
        rows.append({
            "field": "datasheet", "document": Path(path).name,
            "location": "Dosya", "evidence": "Kullanıcı tarafından bağlandı.",
            "method": "manual", "confidence": "100", "certainty": "Kesin bilgi",
            "path": str(path),
        })
    return rows


def history_rows(overrides: Mapping[str, Any] | None, hardware_id: str) -> list[dict[str, Any]]:
    rows = [
        dict(record) for record in (overrides or {}).get("change_history", [])
        if isinstance(record, Mapping) and clean_text(record.get("hardware_id")) == hardware_id
    ]
    if not rows:
        fields = ((overrides or {}).get("field_overrides", {}) or {}).get(hardware_id, {})
        for field, record in fields.items():
            if isinstance(record, Mapping):
                rows.append({
                    "timestamp": record.get("updated_at"), "action": "Manuel alan düzenlemesi",
                    "field": field, "old_value": record.get("base_value"),
                    "new_value": record.get("value"), "actor": "Kullanıcı",
                })
    return sorted(rows, key=lambda row: clean_text(row.get("timestamp")), reverse=True)


def gallery_entries(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    path = clean_text(item.get("image_path"))
    if path and path != PLACEHOLDER_IMAGE and Path(path).is_file():
        generated = bool(item.get("image_is_generated"))
        metadata = dict(item.get("image_metadata") or {})
        values.append({**metadata,
            "path": path, "source_type": "AI kavramsal görsel" if generated else "Ürün / kullanıcı görseli",
            "source_document": display(item.get("image_source")),
            "created_at": display(item.get("image_created_at", item.get("updated_at"))),
            "is_ai": generated, "description": display((item.get("visual_brief") or {}).get("source_summary")),
            "is_cover": True,
        })
    for record in item.get("gallery_images", []) or []:
        if not isinstance(record, Mapping):
            continue
        candidate = clean_text(record.get("path"))
        if candidate and Path(candidate).is_file() and all(entry["path"] != candidate for entry in values):
            values.append({**dict(record),
                "path": candidate, "source_type": display(record.get("source_type")),
                "source_document": display(record.get("source_document")),
                "created_at": display(record.get("created_at")),
                "is_ai": bool(record.get("is_ai")), "description": display(record.get("description")),
                "is_cover": bool(record.get("is_cover")),
            })
    return values


def overview(item: Mapping[str, Any], catalog: Mapping[str, Any], report: Mapping[str, Any] | None) -> dict[str, Any]:
    children = child_items(catalog, clean_text(item.get("hardware_id")))
    reqs = requirement_rows(item, report)
    missing = list(item.get("missing_information") or [])
    critical_limits = [
        f"{row['parameter']}: {row['value']} {row['unit']}"
        for row in technical_rows(item)
        if row["value"] != MISSING_VALUE and row["category"] in {"Termal", "Elektriksel", "Çevresel"}
    ][:6]
    parent = parent_chain(catalog, clean_text(item.get("hardware_id")))
    return {
        "system_role": display(item.get("system_role")),
        "purpose": display(item.get("description")),
        "location": breadcrumb(catalog, clean_text(item.get("hardware_id"))),
        "parent": display(parent[-2].get("part_name")) if len(parent) > 1 else MISSING_VALUE,
        "children": ", ".join(display(child.get("part_name")) for child in children) or MISSING_VALUE,
        "quantity": display(item.get("quantity", 1)),
        "critical_limits": "\n".join(critical_limits) or MISSING_VALUE,
        "critical_requirements": "\n".join(f"{row['id']}: {row['text']}" for row in reqs[:5]) or MISSING_VALUE,
        "risks": display(item.get("open_risks")),
        "missing": "\n".join(display(value) for value in missing) or MISSING_VALUE,
        "actions": display(item.get("engineering_actions")),
    }


__all__ = [
    "TECHNICAL_FIELDS", "alternative_comparison_rows", "alternative_ids",
    "alternative_links", "breadcrumb", "child_items", "connection_rows",
    "display", "gallery_entries", "history_rows", "item_index", "overview",
    "parent_chain", "requirement_rows", "source_rows", "state_rows",
    "technical_rows", "trace_edges", "trace_node_index",
]
