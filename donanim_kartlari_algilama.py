# -*- coding: utf-8 -*-
"""Belgelerden Donanım Bilgi Kartı ve ürün ağacı kataloğu çıkarır.

Kaynak önceliği: yapılandırılmış Python kaydı, açık izlenebilirlik bağı,
datasheet/teknik belge, isteğe bağlı RAG ve son olarak doğrulanmış LM çıktısı.
Belge dosyaları yalnızca okunur; katalog sürümlü ve atomik olarak yazılır.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any, Callable, Iterable, Mapping, Sequence

from donanim_kartlari_model import (
    AlternativeLink,
    HardwareCard,
    HardwareCatalog,
    MISSING_VALUE,
    PLACEHOLDER_IMAGE,
    ProductInstance,
    SourceEvidence,
    TechnicalData,
    calculate_card_confidence,
    clean_text,
    is_missing,
)
from etki_analizi_izlenebilirlik import (
    DEFAULT_OUTPUT_ROOT,
    atomic_write_json,
    extract_identifiers,
    normalize_identifier,
    project_identity,
    read_document_lines,
    semantic_similarity,
)


CATALOG_FILENAME = "donanim_katalogu.json"
DETECTION_VERSION = "1.2"
METHOD_CONFIDENCE = {
    "structured_python": 100.0,
    "explicit_traceability": 95.0,
    "datasheet_label": 95.0,
    "datasheet_regex": 90.0,
    "technical_document": 78.0,
    "text_pattern": 70.0,
    "rag_match": 60.0,
    "lm_inference": 45.0,
}

_PART_LABEL_RE = re.compile(
    r"(?:parça\s*(?:adı|ismi)|bileşen|component|part\s*name)\s*[:=]\s*"
    r"(?P<value>[^|;\n]{2,100})",
    re.IGNORECASE,
)
_PART_NUMBER_RE = re.compile(
    r"(?:parça\s*(?:no|numarası)|part\s*(?:no|number)|p\s*/\s*n|ürün\s*kodu)\s*[:=#]?\s*"
    r"(?P<value>[A-Z0-9][A-Z0-9._/+\-]{2,50})",
    re.IGNORECASE,
)
_MANUFACTURER_RE = re.compile(
    r"(?:üretici|manufacturer|marka|vendor)\s*[:=]\s*(?P<value>[^|;\n]{2,80})",
    re.IGNORECASE,
)
_MODEL_RE = re.compile(
    r"(?:model(?:\s*/\s*seri)?|series|seri)\s*[:=]\s*(?P<value>[A-Z0-9][A-Z0-9._/+\-]{1,60})",
    re.IGNORECASE,
)
_TEMP_RANGE_RE = re.compile(
    r"(?P<min>[+\-−]?\d+(?:[.,]\d+)?)\s*(?:°\s*)?(?P<unit>[CFK])?\s*"
    r"(?:\.\.|-|–|—|ila|to)\s*"
    r"(?P<max>[+\-−]?\d+(?:[.,]\d+)?)\s*°?\s*(?P<unit2>[CFK])\b",
    re.IGNORECASE,
)
_DIMENSION_TRIPLE_RE = re.compile(
    r"(?P<length>\d+(?:[.,]\d+)?)\s*[x×]\s*"
    r"(?P<width>\d+(?:[.,]\d+)?)\s*[x×]\s*"
    r"(?P<height>\d+(?:[.,]\d+)?)\s*(?P<unit>mm|cm|m|in(?:ch)?)\b",
    re.IGNORECASE,
)
_HARDWARE_PHRASE_RE = re.compile(
    r"(?P<value>[A-Za-zÇĞİÖŞÜçğıöşü0-9][A-Za-zÇĞİÖŞÜçğıöşü0-9/+.\-]*"
    r"(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü0-9][A-Za-zÇĞİÖŞÜçğıöşü0-9/+.\-]*){0,4}\s+"
    r"(?:sensörü|sensor|motoru|motor|pompası|pompa|pump|valfi|valf|valve|"
    r"rölesi|röle|relay|kontrolcüsü|kontrolcü|controller|işlemcisi|işlemci|"
    r"processor|mikrodenetleyici|microcontroller|modülü|modül|module|kartı|kart|"
    r"board|ekranı|ekran|display|bataryası|batarya|battery|güç\s+kaynağı|"
    r"power\s+supply|konnektörü|konnektör|connector|kablosu|kablo|cable|"
    r"anteni|anten|antenna|fren\s+balatası|fren\s+pabucu|brake\s+pad))\b",
    re.IGNORECASE,
)
_TURKISH_HARDWARE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?P<composite>kompozit\s+)?(?P<disk>disk\s+)?fren\s+"
            r"(?:balata(?:sı|ları|larının|sının|yı|yı)?|pabu(?:cu|ç(?:ları|larının|u)?))\b",
            re.IGNORECASE,
        ),
        "brake_friction_part",
    ),
    (
        re.compile(
            r"\b(?P<prefix>ABS|fren\s+sistemi|fren)?\s*kontrol\s+ünitesi"
            r"(?:yle|nin|ne|nden|ni)?\b",
            re.IGNORECASE,
        ),
        "control_unit",
    ),
    (
        re.compile(r"\b(?:ağırlık\s+)?ölçüm\s+cihazı(?:nın|yla|na)?\b", re.IGNORECASE),
        "measurement_device",
    ),
    (
        re.compile(r"\btahrik\s+mekanizması(?:yla|nın|na)?\b", re.IGNORECASE),
        "actuation_mechanism",
    ),
)
_REQUIREMENT_NODE_TYPES = {
    "Müşteri/paydaş gereksinimi", "Sistem gereksinimi", "Alt sistem gereksinimi",
}
_TEST_NODE_TYPES = {
    "Doğrulama kriteri", "Birim testi", "Entegrasyon testi",
    "Sistem doğrulama testi", "Müşteri kabul/geçerleme testi",
}


class HardwareDetectionError(ValueError):
    """Katalog girdisi veya kalıcı kayıt hatası."""


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _canonical_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _fold(value)).strip()


def _as_float(value: str) -> float:
    return float(value.replace("−", "-").replace(",", "."))


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return clean_text(match.group("value")) if match else MISSING_VALUE


def _hardware_mentions(text: str) -> list[tuple[str, str]]:
    """Kaynak ifadesini ve birleştirilmiş tekil katalog adını birlikte döndürür."""
    mentions: list[tuple[str, str]] = []
    occupied: list[tuple[int, int]] = []
    for pattern, kind in _TURKISH_HARDWARE_PATTERNS:
        for match in pattern.finditer(text):
            raw = clean_text(match.group(0))
            if kind == "brake_friction_part":
                folded = _fold(raw)
                if "balata" in folded:
                    name = "Kompozit Disk Fren Balatası" if "kompozit" in folded and "disk" in folded else "Disk Fren Balatası"
                else:
                    name = "Kompozit Fren Pabucu" if "kompozit" in folded else "Fren Pabucu"
            elif kind == "control_unit":
                prefix = _fold(match.groupdict().get("prefix"))
                name = "ABS Kontrol Ünitesi" if prefix == "abs" else (
                    "Fren Sistemi Kontrol Ünitesi" if "fren" in prefix else "Kontrol Ünitesi"
                )
            elif kind == "measurement_device":
                name = "Ağırlık Ölçüm Cihazı" if "ağırlık" in _fold(raw) else "Ölçüm Cihazı"
            else:
                name = "Tahrik Mekanizması"
            mentions.append((name, raw))
            occupied.append(match.span())
    for match in _HARDWARE_PHRASE_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        raw = clean_text(match.group("value")).strip(".,;:()[]")
        raw = re.sub(r"^(?:e\s+)?sahip\s+(?:bir\s+)?", "", raw, flags=re.I)
        raw = re.sub(r"^bir\s+", "", raw, flags=re.I)
        if re.search(r"\bbir\s+(?:mikrodenetleyici|işlemci|ekran|sensör|pompa)\b", raw, re.I):
            raw = re.sub(r"^.*\bbir\s+", "", raw, flags=re.I)
        mentions.append((raw, raw))
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, raw in mentions:
        key = _canonical_name(name)
        if key and key not in seen:
            unique.append((name, raw))
            seen.add(key)
    return unique


def _label_value(text: str, labels: Sequence[str]) -> str:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{joined})\s*[:=]\s*([^|;\n]+)", text, re.I)
    return clean_text(match.group(1)) if match else MISSING_VALUE


def _extract_number_with_unit(
    text: str, labels: Sequence[str], units: str
) -> tuple[Any, str]:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{joined})\s*[:=]?\s*([+\-−]?\d+(?:[.,]\d+)?)\s*({units})\b",
        text,
        re.I,
    )
    if not match:
        return MISSING_VALUE, MISSING_VALUE
    return _as_float(match.group(1)), match.group(2)


def extract_technical_data(value: Any) -> tuple[TechnicalData, dict[str, str]]:
    """Açık etiket ve sayı-birimlerden teknik alanları deterministik çıkarır."""
    if isinstance(value, Mapping):
        specifications = {clean_text(k): clean_text(v) for k, v in value.items()}
        text = "\n".join(f"{key}: {item}" for key, item in specifications.items())
    else:
        specifications = {}
        text = clean_text(value)
    data = TechnicalData()
    matched: dict[str, str] = {}

    for kind, labels in (
        ("operating", ("çalışma sıcaklığı", "operating temperature", "operating temp")),
        ("storage", ("depolama sıcaklığı", "storage temperature", "storage temp")),
    ):
        for label in labels:
            label_match = re.search(re.escape(label) + r"[^\n;|]*", text, re.I)
            if not label_match:
                continue
            range_match = _TEMP_RANGE_RE.search(label_match.group(0))
            if range_match:
                setattr(data, f"{kind}_temperature_min", _as_float(range_match.group("min")))
                setattr(data, f"{kind}_temperature_max", _as_float(range_match.group("max")))
                data.temperature_unit = (range_match.group("unit2") or range_match.group("unit") or "C").upper()
                matched[f"{kind}_temperature"] = label_match.group(0)
                break

    dimension_context = _label_value(text, ("boyutlar", "ölçüler", "dimensions", "size"))
    dimension_match = _DIMENSION_TRIPLE_RE.search(
        dimension_context if not is_missing(dimension_context) else text
    )
    if dimension_match:
        data.length = _as_float(dimension_match.group("length"))
        data.width = _as_float(dimension_match.group("width"))
        data.height = _as_float(dimension_match.group("height"))
        data.dimension_unit = dimension_match.group("unit")
        matched["dimensions"] = dimension_match.group(0)
    for field_name, labels in (
        ("length", ("uzunluk", "length")),
        ("width", ("genişlik", "width")),
        ("height", ("yükseklik", "height")),
        ("diameter", ("çap", "diameter")),
    ):
        number, unit = _extract_number_with_unit(text, labels, r"mm|cm|m|in(?:ch)?")
        if not is_missing(number):
            setattr(data, field_name, number)
            data.dimension_unit = unit
            matched[field_name] = f"{number} {unit}"

    data.weight, data.weight_unit = _extract_number_with_unit(
        text, ("ağırlık", "weight", "mass"), r"mg|g|kg|lb"
    )
    if not is_missing(data.weight):
        matched["weight"] = f"{data.weight} {data.weight_unit}"
    voltage, voltage_unit = _extract_number_with_unit(
        text, ("besleme gerilimi", "giriş gerilimi", "supply voltage", "input voltage"),
        r"mV|V|kV|VDC|VAC",
    )
    if not is_missing(voltage):
        data.supply_voltage = f"{voltage:g} {voltage_unit}"
        matched["supply_voltage"] = data.supply_voltage
    power, power_unit = _extract_number_with_unit(
        text, ("güç tüketimi", "power consumption", "güç", "power"), r"mW|W|kW"
    )
    if not is_missing(power):
        data.power_consumption = f"{power:g} {power_unit}"
        matched["power_consumption"] = data.power_consumption
    if is_missing(data.supply_voltage):
        voltages = re.findall(r"\b([+\-]?\d+(?:[.,]\d+)?)\s*(mV|V|kV|VDC|VAC)\b", text, re.I)
        if len(voltages) == 1:
            data.supply_voltage = f"{_as_float(voltages[0][0]):g} {voltages[0][1]}"
            matched["supply_voltage"] = data.supply_voltage
    if is_missing(data.power_consumption):
        powers = re.findall(r"\b([+\-]?\d+(?:[.,]\d+)?)\s*(mW|W|kW)\b", text, re.I)
        if len(powers) == 1:
            data.power_consumption = f"{_as_float(powers[0][0]):g} {powers[0][1]}"
            matched["power_consumption"] = data.power_consumption

    interface_names = re.findall(
        r"\b(?:CAN(?:\s*FD)?|Ethernet|RS[- ]?232|RS[- ]?422|RS[- ]?485|UART|SPI|I2C|USB(?:\s*[0-9.]+)?|"
        r"LIN|Modbus|Profibus|ARINC[- ]?429|MIL[- ]?STD[- ]?1553)\b",
        text,
        re.I,
    )
    data.communication_interfaces = _unique(interface_names)
    mechanical = _label_value(text, ("mekanik arayüzler", "mekanik bağlantı", "mechanical interfaces"))
    electrical = _label_value(text, ("elektriksel arayüzler", "elektriksel bağlantı", "electrical interfaces"))
    if not is_missing(mechanical):
        data.mechanical_interfaces = _unique(re.split(r"[,;/]", mechanical))
    if not is_missing(electrical):
        data.electrical_interfaces = _unique(re.split(r"[,;/]", electrical))
    environmental = _label_value(
        text, ("çevresel dayanım", "environmental resistance", "ip sınıfı", "ip rating")
    )
    reliability = _label_value(text, ("güvenilirlik", "reliability", "mtbf"))
    if not is_missing(environmental):
        data.environmental_resistance = environmental
    if not is_missing(reliability):
        data.reliability = reliability
    standards = re.findall(
        r"\b(?:MIL[- ]STD[- ]\d+[A-Z]?|DO[- ]\d+[A-Z]?|ISO\s*\d+(?:[-:]\d+)*|"
        r"IEC\s*\d+(?:[-:]\d+)*|EN\s*\d+(?:[-:]\d+)*|CE|RoHS|UL\s*\d*)\b",
        text,
        re.I,
    )
    data.standards_and_certifications = _unique(standards)

    known_folded = {
        _fold(label)
        for labels in (
            ("çalışma sıcaklığı", "operating temperature"),
            ("depolama sıcaklığı", "storage temperature"),
            ("boyutlar", "dimensions"), ("ağırlık", "weight"),
            ("besleme gerilimi", "supply voltage"), ("güç tüketimi", "power consumption"),
        ) for label in labels
    }
    for key, raw_value in specifications.items():
        if _fold(key) not in known_folded and raw_value:
            data.custom_parameters[key] = MISSING_VALUE if is_missing(raw_value) else raw_value
    data.__post_init__()
    return data, matched


def _hardware_id(part_name: str, manufacturer: Any, part_number: Any) -> str:
    identity = (
        f"{_canonical_name(manufacturer)}|{_canonical_name(part_number)}"
        if not is_missing(part_number)
        else _canonical_name(part_name)
    )
    return "HW-CAT-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10].upper()


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    part_number = candidate.get("part_number")
    if not is_missing(part_number):
        return "pn:" + _canonical_name(candidate.get("manufacturer")) + ":" + _canonical_name(part_number)
    return "name:" + _canonical_name(candidate.get("part_name"))


def _evidence(
    field_name: str,
    source: str,
    text: Any,
    method: str,
    location: str = MISSING_VALUE,
    certainty: str = "Kesin bilgi",
) -> SourceEvidence:
    return SourceEvidence(
        field_name=field_name,
        source_document=source,
        location=location,
        evidence_text=clean_text(text, MISSING_VALUE),
        extraction_method=method,
        field_confidence=METHOD_CONFIDENCE.get(method, 50.0),
        certainty=certainty,
    )


def _structured_candidate(fallback_id: str, raw: Mapping[str, Any]) -> dict[str, Any] | None:
    part_name = clean_text(raw.get("part_name") or raw.get("name") or raw.get("description"))
    if not part_name or is_missing(part_name):
        return None
    source = clean_text(raw.get("source_document"), "Akıllı Donanım Listesi")
    source_text = clean_text(raw.get("source_excerpt") or raw.get("rationale") or part_name)
    specifications = raw.get("technical_data") or raw.get("specifications") or raw.get("specs") or {}
    technical_data, _ = extract_technical_data(specifications)
    item_id = clean_text(raw.get("hardware_id") or raw.get("ID") or raw.get("item_id") or fallback_id)
    if not item_id.upper().startswith("HW-"):
        item_id = _hardware_id(part_name, raw.get("manufacturer"), raw.get("part_number"))
    requirements = raw.get("linked_requirements") or raw.get("requirement_ids") or []
    if isinstance(requirements, str):
        requirements = re.split(r"[,;\n]+", requirements)
    tests = raw.get("linked_tests") or raw.get("test_ids") or []
    if isinstance(tests, str):
        tests = re.split(r"[,;\n]+", tests)
    alternatives = raw.get("alternative_ids") or raw.get("alternatives") or []
    if isinstance(alternatives, str):
        alternatives = re.split(r"[,;\n]+", alternatives)
    instances = raw.get("instances") if isinstance(raw.get("instances"), list) else []
    if not instances:
        instances = [{
            "quantity": raw.get("quantity", 1),
            "location": raw.get("location") or raw.get("usage_location"),
            "parent_id": raw.get("parent_id") or raw.get("parent_hardware_id"),
            "level": raw.get("product_level") or raw.get("level") or "Parça/bileşen",
            "reference_designator": raw.get("reference_designator"),
        }]
    status = clean_text(raw.get("lifecycle_status") or raw.get("status"), "Veri eksik")
    if status == "İnceleniyor":
        status = "Onay bekliyor"
    evidence = [
        _evidence("hardware_id", source, item_id, "structured_python"),
        _evidence("part_name", source, source_text, "structured_python"),
    ]
    field_confidence = {"hardware_id": 100.0, "part_name": 100.0}
    for field_name, field_value in (
        ("part_number", raw.get("part_number")),
        ("manufacturer", raw.get("manufacturer")),
        ("model_series", raw.get("model_series") or raw.get("model")),
        ("hardware_type", raw.get("hardware_type") or raw.get("category")),
        ("system_role", raw.get("system_role") or raw.get("rationale")),
        ("parent_id", raw.get("parent_id") or raw.get("parent_hardware_id")),
    ):
        if not is_missing(field_value):
            evidence.append(_evidence(field_name, source, field_value, "structured_python"))
            field_confidence[field_name] = 100.0
    if technical_data.populated_field_count():
        evidence.append(_evidence("technical_data", source, specifications, "structured_python"))
        field_confidence["technical_data"] = 100.0
    working_states = raw.get("working_states") or ["Normal"]
    if isinstance(working_states, str):
        working_states = [working_states]
    return {
        "hardware_id": item_id,
        "part_name": part_name,
        "part_number": raw.get("part_number", MISSING_VALUE),
        "manufacturer": raw.get("manufacturer", MISSING_VALUE),
        "model_series": raw.get("model_series") or raw.get("model") or MISSING_VALUE,
        "hardware_type": raw.get("hardware_type") or raw.get("category") or MISSING_VALUE,
        "description": raw.get("description") or part_name,
        "system_role": raw.get("system_role") or raw.get("rationale") or MISSING_VALUE,
        "parent_id": raw.get("parent_id") or raw.get("parent_hardware_id") or MISSING_VALUE,
        "quantity": raw.get("quantity", 1),
        "working_states": working_states,
        "lifecycle_status": status,
        "technical_data": technical_data,
        "requirement_ids": _unique(normalize_identifier(item) for item in requirements),
        "test_ids": _unique(normalize_identifier(item) for item in tests),
        "alternative_refs": _unique(alternatives),
        "instances": instances,
        "aliases": _unique(raw.get("aliases", [])),
        "evidence": evidence,
        "field_confidence": field_confidence,
        "source_kind": "structured_python",
        "source": source,
        "alternative_metadata": deepcopy(raw.get("alternative_metadata") or {}),
    }


def _structured_record_candidates(
    records: Mapping[str, Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Üretilmiş gereksinim metnindeki açık donanım adlarını kanıtla çıkarır."""
    candidates: list[dict[str, Any]] = []
    for fallback_id, raw in (records or {}).items():
        if not isinstance(raw, Mapping):
            continue
        record_type = clean_text(raw.get("type")).upper()
        if record_type not in {"TID", "SGD", "STT"}:
            continue
        content = clean_text(raw.get("content") or raw.get("description"))
        requirement_id = normalize_identifier(raw.get("ID") or fallback_id)
        if not content or not requirement_id:
            continue
        for part_name, raw_mention in _hardware_mentions(content):
            if len(part_name) < 3:
                continue
            technical_data, matched = extract_technical_data(content)
            source = clean_text(raw.get("source_document"), f"{record_type} yapılandırılmış verisi")
            item_evidence = [
                _evidence(
                    "part_name", source, raw_mention, "explicit_traceability",
                    clean_text(raw.get("source_section"), requirement_id),
                ),
                _evidence(
                    "requirement_ids", source, content, "explicit_traceability",
                    clean_text(raw.get("source_section"), requirement_id),
                ),
            ]
            field_confidence = {"part_name": 95.0, "requirement_ids": 95.0}
            for field_name, evidence_text in matched.items():
                item_evidence.append(_evidence(
                    f"technical_data.{field_name}", source, evidence_text,
                    "text_pattern", clean_text(raw.get("source_section"), requirement_id),
                ))
                field_confidence[f"technical_data.{field_name}"] = METHOD_CONFIDENCE["text_pattern"]
            candidates.append({
                "hardware_id": _hardware_id(part_name, None, None),
                "part_name": part_name,
                "part_number": MISSING_VALUE,
                "manufacturer": MISSING_VALUE,
                "model_series": MISSING_VALUE,
                "hardware_type": "Parça/bileşen",
                "description": content,
                "system_role": content,
                "parent_id": MISSING_VALUE,
                "quantity": 1,
                "working_states": ["Normal"],
                "lifecycle_status": "Mevcut",
                "technical_data": technical_data,
                "requirement_ids": [requirement_id],
                "test_ids": [], "alternative_refs": [],
                "instances": [{"quantity": 1, "level": "Parça/bileşen"}],
                "aliases": [], "evidence": item_evidence,
                "field_confidence": field_confidence,
                "source_kind": "structured_requirement", "source": source,
            })
    return candidates


def _traceability_candidates(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for node in report.get("nodes", []):
        if not isinstance(node, Mapping) or node.get("node_type") != "Parça/bileşen":
            continue
        part_name = clean_text(node.get("title") or node.get("description"))
        if not part_name:
            continue
        technical_raw = {
            clean_text(item.get("name"), f"Parametre {index}"): item.get("value", item.get("raw"))
            for index, item in enumerate(node.get("technical_parameters", []), start=1)
            if isinstance(item, Mapping)
        }
        technical_data, _ = extract_technical_data(technical_raw)
        source = clean_text(node.get("source_document"), "İzlenebilirlik haritası")
        candidates.append({
            "hardware_id": clean_text(node.get("id")) or _hardware_id(part_name, None, None),
            "part_name": part_name,
            "part_number": node.get("part_number", MISSING_VALUE),
            "manufacturer": node.get("manufacturer", MISSING_VALUE),
            "model_series": node.get("model_series", MISSING_VALUE),
            "hardware_type": node.get("hardware_type", "Parça/bileşen"),
            "description": node.get("description") or part_name,
            "system_role": node.get("system_role", MISSING_VALUE),
            "parent_id": node.get("parent_id", MISSING_VALUE),
            "quantity": node.get("quantity", 1),
            "working_states": ["Normal"],
            "lifecycle_status": "Mevcut" if node.get("status") == "Onaylandı" else "Veri eksik",
            "technical_data": technical_data,
            "requirement_ids": [], "test_ids": [], "alternative_refs": [],
            "instances": [{"quantity": node.get("quantity", 1), "level": "Parça/bileşen"}],
            "aliases": list(node.get("aliases", [])),
            "evidence": [_evidence(
                "part_name", source, node.get("evidence_text") or part_name,
                "explicit_traceability", clean_text(node.get("source_section"), MISSING_VALUE),
            )],
            "field_confidence": {"part_name": 95.0},
            "source_kind": "traceability", "source": source,
        })
    return candidates


def _traceability_requirement_candidates(
    report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Eski proje önbelleklerinde flat_data yoksa gereksinim düğümlerini kullanır."""
    records: dict[str, dict[str, Any]] = {}
    for node in report.get("nodes", []):
        if not isinstance(node, Mapping) or node.get("node_type") not in _REQUIREMENT_NODE_TYPES:
            continue
        node_id = clean_text(node.get("id"))
        document_type = clean_text(node.get("document_type")).upper()
        if not node_id or document_type not in {"TID", "SGD", "STT"}:
            continue
        records[node_id] = {
            "ID": node_id,
            "type": document_type,
            "content": node.get("description") or node.get("evidence_text"),
            "source_document": node.get("source_document"),
            "source_section": node.get("source_section"),
        }
    result = _structured_record_candidates(records)
    for candidate in result:
        candidate["source_kind"] = "traceability_requirement"
    return result


def _align_requirement_candidates_to_traceability(
    candidates: list[dict[str, Any]], report: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Açık gereksinim→parça kenarı varsa metin adayını gerçek HW kimliğine bağlar."""
    hardware_nodes = {
        clean_text(node.get("id")): node
        for node in report.get("nodes", [])
        if isinstance(node, Mapping) and node.get("node_type") == "Parça/bileşen"
    }
    targets_by_requirement: dict[str, set[str]] = {}
    unresolved: list[dict[str, Any]] = []
    for edge in report.get("edges", []):
        if not isinstance(edge, Mapping) or edge.get("relationship_type") not in {
            "allocated_to", "implemented_by", "satisfies",
        }:
            continue
        source_id = clean_text(edge.get("source_id"))
        target_id = clean_text(edge.get("target_id"))
        if target_id in hardware_nodes:
            targets_by_requirement.setdefault(source_id, set()).add(target_id)
    for candidate in candidates:
        target_ids = {
            target_id
            for requirement_id in candidate.get("requirement_ids", [])
            for target_id in targets_by_requirement.get(requirement_id, set())
        }
        if not target_ids:
            continue
        scored = sorted(
            (
                semantic_similarity(
                    candidate.get("part_name"),
                    hardware_nodes[target_id].get("title") or hardware_nodes[target_id].get("description"),
                ),
                target_id,
            )
            for target_id in target_ids
        )
        score, target_id = scored[-1]
        second_score = scored[-2][0] if len(scored) > 1 else 0.0
        if (len(scored) == 1 and score >= 0.18) or (
            score >= 0.28 and score - second_score >= 0.08
        ):
            candidate["hardware_id"] = target_id
            candidate["aliases"] = _unique([
                *candidate.get("aliases", []), candidate.get("part_name"),
            ])
        else:
            candidate["skip_catalog"] = True
            unresolved.append({
                "type": "ambiguous_hardware_trace",
                "part_name": candidate.get("part_name"),
                "requirement_ids": list(candidate.get("requirement_ids", [])),
                "candidate_hardware_ids": [target_id for _, target_id in reversed(scored)],
                "message": (
                    "Gereksinim birden fazla parçaya bağlı; rastgele katalog eşleşmesi yapılmadı."
                ),
            })
    return unresolved


def _document_candidates(
    paths: Sequence[str | os.PathLike[str]], *, datasheet: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        source = {"name": path.name, "path": str(path), "kind": "datasheet" if datasheet else "technical_document"}
        try:
            rows = read_document_lines(path)
        except Exception as error:
            source.update({"status": "error", "error": str(error)})
            sources.append(source)
            continue
        source.update({"status": "ok", "row_count": len(rows)})
        sources.append(source)
        method = "datasheet_label" if datasheet else "technical_document"
        whole_text = "\n".join(line for line, _ in rows if clean_text(line))
        scopes: list[tuple[str, str]] = []
        if datasheet:
            scopes.append((whole_text, "Belge geneli"))
        else:
            scopes.extend((line, location) for line, location in rows)
        seen_names: set[str] = set()
        for scope, location in scopes:
            part_name = _first_match(_PART_LABEL_RE, scope)
            if is_missing(part_name):
                phrase = _HARDWARE_PHRASE_RE.search(scope)
                part_name = clean_text(phrase.group("value")) if phrase else MISSING_VALUE
            if datasheet and is_missing(part_name):
                part_name = clean_text(path.stem)
            if is_missing(part_name) or _canonical_name(part_name) in seen_names:
                continue
            seen_names.add(_canonical_name(part_name))
            part_number = _first_match(_PART_NUMBER_RE, scope)
            manufacturer = _first_match(_MANUFACTURER_RE, scope)
            model = _first_match(_MODEL_RE, scope)
            technical_data, matched = extract_technical_data(scope)
            evidence = [_evidence("part_name", path.name, scope[:500], method, location)]
            fields = {"part_name": METHOD_CONFIDENCE[method]}
            for field_name, field_value in (
                ("part_number", part_number), ("manufacturer", manufacturer), ("model_series", model),
            ):
                if not is_missing(field_value):
                    evidence.append(_evidence(field_name, path.name, field_value, method, location))
                    fields[field_name] = METHOD_CONFIDENCE[method]
            for field_name, evidence_text in matched.items():
                evidence.append(_evidence(
                    f"technical_data.{field_name}", path.name, evidence_text,
                    "datasheet_regex" if datasheet else "text_pattern", location,
                ))
                fields[f"technical_data.{field_name}"] = METHOD_CONFIDENCE[
                    "datasheet_regex" if datasheet else "text_pattern"
                ]
            identifiers = [
                identifier for identifier in extract_identifiers(scope)
                if re.match(r"^(?:TID|SGD|STT|UR|SR|SSR)-", identifier, re.I)
            ]
            candidates.append({
                "hardware_id": _hardware_id(part_name, manufacturer, part_number),
                "part_name": part_name,
                "part_number": part_number,
                "manufacturer": manufacturer,
                "model_series": model,
                "hardware_type": MISSING_VALUE,
                "description": scope[:500],
                "system_role": MISSING_VALUE,
                "parent_id": MISSING_VALUE,
                "quantity": 1,
                "working_states": ["Normal"],
                "lifecycle_status": "Mevcut" if datasheet else "Veri eksik",
                "technical_data": technical_data,
                "requirement_ids": identifiers,
                "test_ids": [], "alternative_refs": [],
                "instances": [{"quantity": 1, "location": location, "level": "Parça/bileşen"}],
                "aliases": [], "evidence": evidence, "field_confidence": fields,
                "source_kind": "datasheet" if datasheet else "technical_document",
                "source": path.name, "source_path": str(path),
            })
    return candidates, sources


def _extract_safe_datasheet_image(
    path: Path,
    asset_directory: Path,
) -> str:
    """PDF içindeki ilk makul raster görseli hash adlı PNG olarak güvenle çıkarır."""
    if path.suffix.lower() != ".pdf" or not path.exists():
        return PLACEHOLDER_IMAGE
    try:
        import fitz

        document = fitz.open(str(path))
    except Exception:
        return PLACEHOLDER_IMAGE
    try:
        for page in document:
            for image in page.get_images(full=True):
                xref = int(image[0])
                pixmap = fitz.Pixmap(document, xref)
                try:
                    if pixmap.width < 64 or pixmap.height < 64:
                        continue
                    if pixmap.width * pixmap.height > 25_000_000:
                        continue
                    if pixmap.alpha or pixmap.colorspace is None or pixmap.colorspace.n > 3:
                        converted = fitz.Pixmap(fitz.csRGB, pixmap)
                    else:
                        converted = pixmap
                    try:
                        payload = converted.tobytes("png")
                    finally:
                        if converted is not pixmap:
                            converted = None
                    if not payload or len(payload) > 20_000_000:
                        continue
                    digest = hashlib.sha256(payload).hexdigest()[:16]
                    asset_directory.mkdir(parents=True, exist_ok=True)
                    target = asset_directory / f"datasheet-{digest}.png"
                    if not target.exists():
                        temporary_name = ""
                        try:
                            with tempfile.NamedTemporaryFile(
                                mode="wb", dir=asset_directory,
                                prefix=f".{target.name}.", suffix=".tmp", delete=False,
                            ) as temporary:
                                temporary.write(payload)
                                temporary.flush()
                                os.fsync(temporary.fileno())
                                temporary_name = temporary.name
                            os.replace(temporary_name, target)
                        finally:
                            if temporary_name and os.path.exists(temporary_name):
                                os.unlink(temporary_name)
                    return str(target.resolve())
                finally:
                    pixmap = None
    finally:
        document.close()
    return PLACEHOLDER_IMAGE


def _validated_optional_candidates(
    raw_items: Iterable[Mapping[str, Any]], method: str
) -> list[dict[str, Any]]:
    """RAG/LM eklentisinden gelen öğeleri kaynak/kimlik olmadan kabul etmez."""
    result: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            continue
        part_name = clean_text(raw.get("part_name") or raw.get("name"))
        source = clean_text(raw.get("source_document") or raw.get("source"))
        evidence_text = clean_text(raw.get("evidence_text"))
        if not part_name or not source or not evidence_text:
            continue
        candidate = _structured_candidate("", raw)
        if not candidate:
            continue
        candidate["source_kind"] = method
        candidate["source"] = source
        candidate["evidence"] = [
            _evidence("part_name", source, evidence_text, method, raw.get("location", MISSING_VALUE), "Çıkarım")
        ]
        candidate["field_confidence"] = {"part_name": METHOD_CONFIDENCE[method]}
        result.append(candidate)
    return result


def _merge_technical(
    target: TechnicalData,
    incoming: TechnicalData,
    conflicts: list[dict[str, Any]],
    hardware_id: str,
    source: str,
) -> None:
    scalar_fields = (
        "operating_temperature_min", "operating_temperature_max",
        "storage_temperature_min", "storage_temperature_max", "temperature_unit",
        "length", "width", "height", "diameter", "dimension_unit",
        "weight", "weight_unit", "supply_voltage", "power_consumption",
        "environmental_resistance", "reliability",
    )
    for field_name in scalar_fields:
        current = getattr(target, field_name)
        new = getattr(incoming, field_name)
        if is_missing(current) and not is_missing(new):
            setattr(target, field_name, new)
        elif not is_missing(current) and not is_missing(new) and str(current).casefold() != str(new).casefold():
            conflicts.append({
                "type": "technical_value_conflict", "hardware_id": hardware_id,
                "field": field_name, "existing_value": current,
                "conflicting_value": new, "source": source,
            })
    for field_name in (
        "communication_interfaces", "mechanical_interfaces", "electrical_interfaces",
        "standards_and_certifications",
    ):
        setattr(target, field_name, _unique([*getattr(target, field_name), *getattr(incoming, field_name)]))
    for key, value in incoming.custom_parameters.items():
        if key not in target.custom_parameters or is_missing(target.custom_parameters[key]):
            target.custom_parameters[key] = value
        elif not is_missing(value) and str(target.custom_parameters[key]).casefold() != str(value).casefold():
            conflicts.append({
                "type": "technical_value_conflict", "hardware_id": hardware_id,
                "field": f"custom_parameters.{key}",
                "existing_value": target.custom_parameters[key],
                "conflicting_value": value, "source": source,
            })


def _make_card(candidate: Mapping[str, Any]) -> HardwareCard:
    card = HardwareCard(
        hardware_id=clean_text(candidate.get("hardware_id")),
        part_name=clean_text(candidate.get("part_name"), MISSING_VALUE),
        part_number=candidate.get("part_number", MISSING_VALUE),
        manufacturer=candidate.get("manufacturer", MISSING_VALUE),
        model_series=candidate.get("model_series", MISSING_VALUE),
        hardware_type=candidate.get("hardware_type", MISSING_VALUE),
        description=candidate.get("description", MISSING_VALUE),
        system_role=candidate.get("system_role", MISSING_VALUE),
        parent_id=candidate.get("parent_id", MISSING_VALUE),
        quantity=candidate.get("quantity", 1),
        working_states=list(candidate.get("working_states") or ["Normal"]),
        lifecycle_status=clean_text(candidate.get("lifecycle_status"), "Veri eksik"),
        technical_data=candidate.get("technical_data") or TechnicalData(),
        requirement_ids=list(candidate.get("requirement_ids") or []),
        test_ids=list(candidate.get("test_ids") or []),
        source_evidence=list(candidate.get("evidence") or []),
        aliases=list(candidate.get("aliases") or []),
        field_confidence=dict(candidate.get("field_confidence") or {}),
    )
    return card


def _merge_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[HardwareCard], dict[str, list[Mapping[str, Any]]], list[dict[str, Any]]]:
    cards_by_key: dict[str, HardwareCard] = {}
    raw_by_id: dict[str, list[Mapping[str, Any]]] = {}
    conflicts: list[dict[str, Any]] = []
    id_to_key: dict[str, str] = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        if key in {"name:", "pn::"}:
            continue
        candidate_id = clean_text(candidate.get("hardware_id"))
        existing_key = id_to_key.get(candidate_id) if candidate_id else None
        key = existing_key or key
        card = cards_by_key.get(key)
        if card is None:
            card = _make_card(candidate)
            cards_by_key[key] = card
        else:
            card.aliases = _unique([*card.aliases, candidate.get("part_name"), *candidate.get("aliases", [])])
            incoming_confidence = dict(candidate.get("field_confidence") or {})
            for field_name in (
                "part_number", "manufacturer", "model_series", "hardware_type",
                "description", "system_role", "parent_id",
            ):
                current = getattr(card, field_name)
                new = candidate.get(field_name, MISSING_VALUE)
                if is_missing(current) and not is_missing(new):
                    setattr(card, field_name, new)
                    card.field_confidence[field_name] = incoming_confidence.get(field_name, 70.0)
                elif (
                    field_name in {"part_number", "manufacturer", "model_series", "parent_id"}
                    and not is_missing(current) and not is_missing(new)
                    and _fold(current) != _fold(new)
                ):
                    conflicts.append({
                        "type": "identity_or_hierarchy_conflict", "hardware_id": card.hardware_id,
                        "field": field_name, "existing_value": current,
                        "conflicting_value": new, "source": candidate.get("source", MISSING_VALUE),
                    })
            _merge_technical(
                card.technical_data, candidate.get("technical_data") or TechnicalData(),
                conflicts, card.hardware_id, clean_text(candidate.get("source"), MISSING_VALUE),
            )
            card.requirement_ids = _unique([*card.requirement_ids, *candidate.get("requirement_ids", [])])
            card.test_ids = _unique([*card.test_ids, *candidate.get("test_ids", [])])
            card.source_evidence.extend(candidate.get("evidence") or [])
            for field_name, score in incoming_confidence.items():
                card.field_confidence[field_name] = max(card.field_confidence.get(field_name, 0), float(score))
        raw_by_id.setdefault(card.hardware_id, []).append(candidate)
        if candidate_id:
            id_to_key[candidate_id] = key
    return list(cards_by_key.values()), raw_by_id, conflicts


def _apply_trace_links(cards: list[HardwareCard], report: Mapping[str, Any]) -> None:
    nodes = {clean_text(node.get("id")): node for node in report.get("nodes", []) if isinstance(node, Mapping)}
    by_id = {card.hardware_id: card for card in cards}
    by_name = {_canonical_name(card.part_name): card for card in cards}
    node_to_card: dict[str, HardwareCard] = {}
    for node_id, node in nodes.items():
        if node.get("node_type") != "Parça/bileşen":
            continue
        card = by_id.get(node_id) or by_name.get(_canonical_name(node.get("title") or node.get("description")))
        if card:
            node_to_card[node_id] = card
    related_tests: dict[str, list[str]] = {}
    for edge in report.get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source_id, target_id = clean_text(edge.get("source_id")), clean_text(edge.get("target_id"))
        relation = clean_text(edge.get("relationship_type"))
        source_node, target_node = nodes.get(source_id, {}), nodes.get(target_id, {})
        if relation in {"verified_by", "validated_by"} and target_node.get("node_type") in _TEST_NODE_TYPES:
            related_tests.setdefault(source_id, []).append(target_id)
        if relation in {"allocated_to", "implemented_by", "satisfies"}:
            if target_id in node_to_card and source_node.get("node_type") in _REQUIREMENT_NODE_TYPES:
                card = node_to_card[target_id]
                card.requirement_ids = _unique([*card.requirement_ids, source_id])
                card.source_evidence.append(_evidence(
                    "requirement_ids", clean_text(edge.get("source_document"), "İzlenebilirlik haritası"),
                    edge.get("evidence_text") or f"{source_id} → {target_id}",
                    "explicit_traceability",
                ))
            if source_id in node_to_card and target_node.get("node_type") in _REQUIREMENT_NODE_TYPES:
                card = node_to_card[source_id]
                card.requirement_ids = _unique([*card.requirement_ids, target_id])
                card.source_evidence.append(_evidence(
                    "requirement_ids", clean_text(edge.get("source_document"), "İzlenebilirlik haritası"),
                    edge.get("evidence_text") or f"{source_id} → {target_id}",
                    "explicit_traceability",
                ))
    for card in cards:
        tests = [test_id for requirement_id in card.requirement_ids for test_id in related_tests.get(requirement_id, [])]
        card.test_ids = _unique([*card.test_ids, *tests])
        if tests:
            card.source_evidence.append(_evidence(
                "test_ids", "İzlenebilirlik haritası", ", ".join(tests),
                "explicit_traceability",
            ))


def _build_instances(
    cards: list[HardwareCard], raw_by_id: Mapping[str, list[Mapping[str, Any]]]
) -> tuple[list[ProductInstance], list[dict[str, Any]], list[dict[str, Any]]]:
    instances: list[ProductInstance] = []
    unresolved: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    first_instance_by_hardware: dict[str, str] = {}
    for card in cards:
        records = raw_by_id.get(card.hardware_id, [])
        structured_records = [
            record for record in records if record.get("source_kind") == "structured_python"
        ]
        if structured_records:
            records = structured_records
        raw_instances: list[Mapping[str, Any]] = []
        for record in records:
            for instance in record.get("instances", []):
                if not isinstance(instance, Mapping):
                    continue
                try:
                    multiple_quantity = int(instance.get("quantity", 1) or 1) > 1
                except (TypeError, ValueError):
                    multiple_quantity = False
                has_explicit_usage = any(
                    not is_missing(instance.get(field_name))
                    for field_name in (
                        "location", "parent_id", "parent_instance_id", "reference_designator",
                    )
                ) or multiple_quantity
                if record.get("source_kind") == "structured_python" or has_explicit_usage:
                    raw_instances.append(instance)
        if not raw_instances:
            raw_instances = [{
                "quantity": card.quantity,
                "parent_id": card.parent_id,
                "level": "Parça/bileşen",
            }]
        for index, raw in enumerate(raw_instances, start=1):
            location = clean_text(raw.get("location"), MISSING_VALUE)
            signature = f"{card.hardware_id}|{raw.get('parent_id')}|{location}|{raw.get('reference_designator')}|{index}"
            instance_id = "INST-" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12].upper()
            if instance_id in used_ids:
                continue
            used_ids.add(instance_id)
            first_instance_by_hardware.setdefault(card.hardware_id, instance_id)
            instances.append(ProductInstance(
                instance_id=instance_id,
                hardware_id=card.hardware_id,
                parent_instance_id=clean_text(raw.get("parent_instance_id") or raw.get("parent_id"), MISSING_VALUE),
                quantity=raw.get("quantity", card.quantity),
                location=location,
                level=clean_text(raw.get("level"), "Parça/bileşen"),
                reference_designator=raw.get("reference_designator", MISSING_VALUE),
                source_evidence=list(card.source_evidence[:1]),
            ))
    known_instance_ids = {item.instance_id for item in instances}
    known_hardware_ids = {card.hardware_id for card in cards}
    for instance in instances:
        parent = instance.parent_instance_id
        if parent in first_instance_by_hardware:
            instance.parent_instance_id = first_instance_by_hardware[parent]
        elif not is_missing(parent) and parent not in known_instance_ids:
            unresolved.append({
                "type": "unresolved_parent", "instance_id": instance.instance_id,
                "hardware_id": instance.hardware_id, "parent_reference": parent,
            })
            instance.parent_instance_id = MISSING_VALUE
    children: dict[str, list[str]] = {item.instance_id: [] for item in instances}
    for instance in instances:
        if instance.parent_instance_id in children:
            children[instance.parent_instance_id].append(instance.instance_id)
    tree = [
        {
            "instance_id": item.instance_id,
            "hardware_id": item.hardware_id,
            "parent_instance_id": item.parent_instance_id,
            "children": children[item.instance_id],
            "level": item.level,
            "quantity": item.quantity,
            "location": item.location,
        }
        for item in instances
    ]
    by_hardware = {card.hardware_id: card for card in cards}
    for item in instances:
        if item.parent_instance_id in known_instance_ids:
            parent_instance = next(parent for parent in instances if parent.instance_id == item.parent_instance_id)
            child, parent = by_hardware[item.hardware_id], by_hardware[parent_instance.hardware_id]
            child.parent_id = parent.hardware_id
            parent.child_ids = _unique([*parent.child_ids, child.hardware_id])
    return instances, tree, unresolved


def _build_alternatives(
    cards: list[HardwareCard], raw_by_id: Mapping[str, list[Mapping[str, Any]]]
) -> tuple[list[AlternativeLink], list[dict[str, Any]]]:
    links: list[AlternativeLink] = []
    unresolved: list[dict[str, Any]] = []
    by_id = {card.hardware_id: card for card in cards}
    by_name = {_canonical_name(alias): card for card in cards for alias in card.aliases}
    seen: set[tuple[str, str]] = set()
    for card in cards:
        for record in raw_by_id.get(card.hardware_id, []):
            metadata = record.get("alternative_metadata") if isinstance(record.get("alternative_metadata"), Mapping) else {}
            for reference in record.get("alternative_refs", []):
                alternative = by_id.get(reference) or by_name.get(_canonical_name(reference))
                if not alternative or alternative.hardware_id == card.hardware_id:
                    unresolved.append({
                        "type": "unresolved_alternative", "hardware_id": card.hardware_id,
                        "alternative_reference": reference,
                    })
                    continue
                key = (card.hardware_id, alternative.hardware_id)
                if key in seen:
                    continue
                seen.add(key)
                item_meta = metadata.get(reference, {}) if isinstance(metadata.get(reference), Mapping) else {}
                link = AlternativeLink(
                    source_hardware_id=card.hardware_id,
                    alternative_hardware_id=alternative.hardware_id,
                    reason=item_meta.get("reason", "Belgelerde alternatif olarak ilişkilendirildi."),
                    compatibility_status=item_meta.get("compatibility_status", "İncelenmedi"),
                    parameter_differences=dict(item_meta.get("parameter_differences") or {}),
                    met_requirements=list(item_meta.get("met_requirements") or []),
                    unmet_requirements=list(item_meta.get("unmet_requirements") or []),
                    new_risks=list(item_meta.get("new_risks") or []),
                    source=record.get("source", MISSING_VALUE),
                    user_approval=item_meta.get("user_approval", "Onay bekliyor"),
                )
                links.append(link)
                card.alternative_ids = _unique([*card.alternative_ids, alternative.hardware_id])
    return links, unresolved


def _missing_information(card: HardwareCard) -> list[str]:
    required = {
        "part_number": card.part_number,
        "manufacturer": card.manufacturer,
        "model_series": card.model_series,
        "system_role": card.system_role,
    }
    missing = [f"{field_name}: {MISSING_VALUE}" for field_name, value in required.items() if is_missing(value)]
    if card.technical_data.populated_field_count() == 0:
        missing.append(f"technical_data: {MISSING_VALUE}")
    if not card.requirement_ids:
        missing.append(f"requirement_ids: {MISSING_VALUE}")
    if not card.test_ids:
        missing.append(f"test_ids: {MISSING_VALUE}")
    if card.image_path == PLACEHOLDER_IMAGE:
        missing.append(f"image_path: {MISSING_VALUE}")
    return missing


def _source_fingerprint(
    structured_hardware: Mapping[str, Mapping[str, Any]] | None,
    structured_records: Mapping[str, Mapping[str, Any]] | None,
    report: Mapping[str, Any],
    paths: Sequence[str | os.PathLike[str]],
) -> str:
    file_state = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            stat = path.stat()
            file_state.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
        except OSError:
            file_state.append((str(path), None, None))
    payload = {
        "detection_version": DETECTION_VERSION,
        "structured_hardware": structured_hardware or {},
        "structured_records": structured_records or {},
        "traceability_nodes": report.get("nodes", []),
        "traceability_edges": report.get("edges", []),
        "files": file_state,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_hardware_catalog(
    project_name: str,
    output_root: str | os.PathLike[str] | None = None,
) -> HardwareCatalog | None:
    project_id, _ = project_identity(project_name)
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    path = root / project_id / CATALOG_FILENAME
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        catalog = HardwareCatalog.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise HardwareDetectionError(f"Donanım kataloğu okunamadı: {error}") from error
    catalog.storage_path = str(path.resolve())
    version_number = int(re.sub(r"\D", "", catalog.version) or 0)
    if version_number:
        catalog.version_path = str((path.parent / f"donanim_katalogu.v{version_number:04d}.json").resolve())
    catalog.updated = False
    return catalog


def persist_hardware_catalog(
    catalog: HardwareCatalog,
    output_root: str | os.PathLike[str] | None = None,
) -> HardwareCatalog:
    root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    project_dir = root / catalog.project_id
    latest_path = project_dir / CATALOG_FILENAME
    previous_revision = 0
    if latest_path.exists():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
            previous_revision = int(re.sub(r"\D", "", clean_text(previous.get("version"))) or 0)
        except Exception:
            previous_revision = 0
    revision = previous_revision + 1
    catalog.version = f"v{revision:04d}"
    version_path = project_dir / f"donanim_katalogu.v{revision:04d}.json"
    payload = catalog.to_dict(include_runtime_paths=False)
    atomic_write_json(version_path, payload)
    atomic_write_json(latest_path, payload)
    catalog.storage_path = str(latest_path.resolve())
    catalog.version_path = str(version_path.resolve())
    catalog.updated = True
    return catalog


def build_or_update_hardware_catalog(
    project_name: str,
    *,
    traceability_report: Mapping[str, Any] | None = None,
    structured_hardware: Mapping[str, Mapping[str, Any]] | None = None,
    structured_records: Mapping[str, Mapping[str, Any]] | None = None,
    source_paths: Sequence[str | os.PathLike[str]] | None = None,
    datasheet_paths: Sequence[str | os.PathLike[str]] | None = None,
    output_root: str | os.PathLike[str] | None = None,
    rag_extractor: Callable[..., Iterable[Mapping[str, Any]]] | None = None,
    lm_extractor: Callable[..., Iterable[Mapping[str, Any]]] | None = None,
    persist: bool = True,
    now: datetime | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> HardwareCatalog:
    """Kanıtları birleştirip proje bazlı donanım kataloğunu oluşturur/günceller."""
    project_id, _ = project_identity(project_name)
    report = dict(traceability_report or {})
    source_paths = tuple(source_paths or ())
    datasheet_paths = tuple(datasheet_paths or ())
    fingerprint = _source_fingerprint(
        structured_hardware, structured_records, report,
        [*source_paths, *datasheet_paths],
    )
    previous = load_hardware_catalog(project_name, output_root) if persist else None
    if previous and previous.source_fingerprint == fingerprint:
        previous.updated = False
        if status_callback:
            status_callback(
                f"Donanım kataloğu değişmedi: {len(previous.hardware_items)} kart yeniden kullanılacak."
            )
        return previous

    if status_callback:
        status_callback("Donanım kartları yapılandırılmış veriden algılanıyor...")
    candidates: list[dict[str, Any]] = []
    for fallback_id, raw in (structured_hardware or {}).items():
        if isinstance(raw, Mapping):
            candidate = _structured_candidate(str(fallback_id), raw)
            if candidate:
                candidates.append(candidate)
    requirement_candidates = [
        *_structured_record_candidates(structured_records),
        *_traceability_requirement_candidates(report),
    ]
    traceability_parts = _traceability_candidates(report)
    alignment_warnings = _align_requirement_candidates_to_traceability(
        requirement_candidates, report
    )
    candidates.extend(traceability_parts)
    candidates.extend(
        candidate for candidate in requirement_candidates
        if not candidate.get("skip_catalog")
    )
    document_candidates, document_sources = _document_candidates(source_paths)
    datasheet_candidates, datasheet_sources = _document_candidates(datasheet_paths, datasheet=True)
    candidates.extend(document_candidates)
    candidates.extend(datasheet_candidates)

    context = {
        "project_id": project_id,
        "structured_records": deepcopy(structured_records or {}),
        "traceability_report": report,
        "known_hardware": [candidate.get("hardware_id") for candidate in candidates],
    }
    extraction_warnings: list[dict[str, Any]] = []
    for method, extractor in (("rag_match", rag_extractor), ("lm_inference", lm_extractor)):
        if extractor is None:
            continue
        try:
            candidates.extend(_validated_optional_candidates(extractor(context), method))
        except Exception as error:
            extraction_warnings.append({
                "type": f"{method}_unavailable",
                "message": f"{method} devre dışı kaldı; kanıta dayalı temel algılama sürdü: {error}",
            })

    cards, raw_by_id, conflicts = _merge_candidates(candidates)
    detected_ids = {card.hardware_id for card in cards}
    if previous:
        previous_instances: dict[str, list[ProductInstance]] = {}
        for instance in previous.product_instances:
            previous_instances.setdefault(instance.hardware_id, []).append(instance)
        for previous_card in previous.hardware_items:
            if previous_card.hardware_id in detected_ids:
                continue
            retained = HardwareCard.from_dict(previous_card.to_dict())
            retained.source_presence_status = "Kaynaktan artık bulunamadı"
            retained.assumptions = _unique([
                *retained.assumptions,
                "Bu kart önceki katalog sürümünden korunmuştur; güncel kaynaklarda bulunamamıştır.",
            ])
            retained.source_evidence.append(_evidence(
                "source_presence_status", "Önceki donanım kataloğu",
                "Yeni taramada açık kaynak kanıtı bulunamadı; kullanıcı kararı bekleniyor.",
                "previous_catalog_retention",
            ))
            cards.append(retained)
            old_usages = previous_instances.get(retained.hardware_id, [])
            raw_by_id[retained.hardware_id] = [{
                "source": "Önceki donanım kataloğu",
                "source_kind": "retained_previous_catalog",
                "instances": [
                    {
                        "quantity": usage.quantity,
                        "location": usage.location,
                        "parent_id": retained.parent_id,
                        "level": usage.level,
                        "reference_designator": usage.reference_designator,
                    }
                    for usage in old_usages
                ],
            }]
            unresolved_already = next(
                (item for item in extraction_warnings if item.get("hardware_id") == retained.hardware_id),
                None,
            )
            if unresolved_already is None:
                extraction_warnings.append({
                    "type": "source_item_missing",
                    "hardware_id": retained.hardware_id,
                    "message": "Parça güncel kaynaklarda bulunamadı; kart silinmeden kullanıcı kararına bırakıldı.",
                })
    _apply_trace_links(cards, report)
    instances, tree, unresolved_parent = _build_instances(cards, raw_by_id)
    alternatives, unresolved_alternatives = _build_alternatives(cards, raw_by_id)
    unresolved = [
        *extraction_warnings, *alignment_warnings,
        *unresolved_parent, *unresolved_alternatives,
    ]
    if not cards:
        unresolved.append({
            "type": "no_hardware_detected",
            "message": (
                "Kaynaklarda kanıtlanabilir donanım öğesi bulunamadı. "
                "Eksik alanlar uydurulmadı; datasheet veya açık parça kaydı eklenebilir."
            ),
        })
    if persist and datasheet_paths:
        root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
        asset_directory = root / project_id / "assets"
        image_cache: dict[str, str] = {}
        for card in cards:
            datasheet_records = [
                record for record in raw_by_id.get(card.hardware_id, [])
                if record.get("source_kind") == "datasheet" and record.get("source_path")
            ]
            for record in datasheet_records:
                source_path = clean_text(record.get("source_path"))
                image_path = image_cache.setdefault(
                    source_path,
                    _extract_safe_datasheet_image(Path(source_path), asset_directory),
                )
                if image_path != PLACEHOLDER_IMAGE:
                    card.image_path = image_path
                    card.field_confidence["image_path"] = METHOD_CONFIDENCE["datasheet_regex"]
                    card.source_evidence.append(_evidence(
                        "image_path", clean_text(record.get("source"), Path(source_path).name),
                        "PDF içindeki raster görsel", "datasheet_regex",
                    ))
                    break
    for card in cards:
        card.missing_information = _missing_information(card)
        card.confidence_score, card.confidence_breakdown = calculate_card_confidence(card)
        card.updated_at = (now or datetime.now(timezone.utc)).astimezone().isoformat(timespec="seconds")

    generated_at = (now or datetime.now(timezone.utc)).astimezone().isoformat(timespec="seconds")
    sources = [
        {
            "name": "Akıllı Donanım Listesi", "kind": "structured_python",
            "status": "ok", "item_count": len(structured_hardware or {}),
        },
        {
            "name": "V-Model İzlenebilirlik Haritası", "kind": "traceability",
            "status": "ok" if report else "unavailable",
            "revision": report.get("revision"),
        },
        *document_sources,
        *datasheet_sources,
    ]
    catalog = HardwareCatalog(
        project_id=project_id,
        project_name=clean_text(project_name),
        generated_at=generated_at,
        hardware_items=sorted(cards, key=lambda item: item.hardware_id),
        product_instances=sorted(instances, key=lambda item: item.instance_id),
        product_tree=sorted(tree, key=lambda item: item["instance_id"]),
        alternative_links=sorted(
            alternatives,
            key=lambda item: (item.source_hardware_id, item.alternative_hardware_id),
        ),
        unresolved_items=unresolved,
        conflicts=conflicts,
        sources=sources,
        source_fingerprint=fingerprint,
    )
    if persist:
        persist_hardware_catalog(catalog, output_root)
    if status_callback:
        status_callback(
            f"Donanım kataloğu hazır: {len(cards)} kart, {len(instances)} kullanım yeri, "
            f"{sum(1 for item in tree if not is_missing(item['parent_instance_id']))} ürün ağacı ilişkisi."
        )
    return catalog


def ingest_datasheets(
    project_name: str,
    datasheet_paths: Sequence[str | os.PathLike[str]],
    **kwargs: Any,
) -> HardwareCatalog:
    """Sonraki kart arayüzünün kullanacağı güvenli datasheet giriş noktası."""
    return build_or_update_hardware_catalog(
        project_name, datasheet_paths=datasheet_paths, **kwargs
    )


__all__ = [
    "CATALOG_FILENAME",
    "DETECTION_VERSION",
    "HardwareDetectionError",
    "METHOD_CONFIDENCE",
    "build_or_update_hardware_catalog",
    "extract_technical_data",
    "ingest_datasheets",
    "load_hardware_catalog",
    "persist_hardware_catalog",
]
