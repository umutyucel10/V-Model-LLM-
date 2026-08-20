# -*- coding: utf-8 -*-
"""Donanım Kartları arayüzü için güvenli katalog yönetim katmanı.

Otomatik algılanan katalog değiştirilmez. Kullanıcının eklediği veya düzelttiği
alanlar proje klasöründeki ayrı bir bindirme (override) dosyasında saklanır ve
görüntüleme sırasında katalogla birleştirilir. Böylece yeni bir belge taraması
manuel kararları sessizce ezemez.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import uuid

from donanim_kartlari_model import (
    CONFIDENCE_WEIGHTS,
    MISSING_VALUE,
    PLACEHOLDER_IMAGE,
    HardwareCard,
    HardwareCatalog,
    ProductInstance,
    SourceEvidence,
    TechnicalData,
    calculate_card_confidence,
    clean_text,
    is_missing,
)
from etki_analizi_izlenebilirlik import atomic_write_json, project_identity


OVERRIDE_FILENAME = "donanim_kartlari_kullanici.json"
OVERRIDE_SCHEMA_VERSION = "1.4"

DEFAULT_UI_PREFERENCES = {
    "view_mode": "Kart",
    "system_filter": "Tümü",
    "manufacturer_filter": "Tümü",
    "working_filter": "Tümü",
    "lifecycle_filter": "Tümü",
    "confidence_filter": "Tümü",
    "sort_by": "Güven: yüksekten düşüğe",
    "group_by": "Gruplama: Yok",
    "impacted_only": False,
    "no_alternative_only": False,
    "no_datasheet_only": False,
}

TECHNICAL_LABELS = {
    "operating_temperature_min": "Çalışma sıcaklığı min.",
    "operating_temperature_max": "Çalışma sıcaklığı maks.",
    "storage_temperature_min": "Depolama sıcaklığı min.",
    "storage_temperature_max": "Depolama sıcaklığı maks.",
    "length": "Uzunluk",
    "width": "Genişlik",
    "height": "Yükseklik",
    "diameter": "Çap",
    "weight": "Ağırlık",
    "supply_voltage": "Besleme gerilimi",
    "power_consumption": "Güç tüketimi",
    "environmental_resistance": "Çevresel dayanım",
    "reliability": "Güvenilirlik",
}

TECHNICAL_UNITS = {
    "operating_temperature_min": "temperature_unit",
    "operating_temperature_max": "temperature_unit",
    "storage_temperature_min": "temperature_unit",
    "storage_temperature_max": "temperature_unit",
    "length": "dimension_unit",
    "width": "dimension_unit",
    "height": "dimension_unit",
    "diameter": "dimension_unit",
    "weight": "weight_unit",
    "supply_voltage": "V",
    "power_consumption": "W",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _catalog_dict(catalog: HardwareCatalog | Mapping[str, Any] | None) -> dict[str, Any]:
    if catalog is None:
        return {}
    if isinstance(catalog, HardwareCatalog):
        return catalog.to_dict()
    return deepcopy(dict(catalog))


def _safe_project_id(project_name: str, catalog: Mapping[str, Any] | None = None) -> str:
    if catalog and clean_text(catalog.get("project_id")):
        return clean_text(catalog.get("project_id"))
    return project_identity(project_name or "Proje")[0]


def overrides_path(
    project_name: str,
    catalog: HardwareCatalog | Mapping[str, Any] | None = None,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    raw = _catalog_dict(catalog)
    storage_path = clean_text(raw.get("storage_path"))
    if storage_path:
        return Path(storage_path).resolve().parent / OVERRIDE_FILENAME
    root = Path(output_root) if output_root else Path(__file__).resolve().parent / "outputs" / "traceability"
    return root / _safe_project_id(project_name, raw) / OVERRIDE_FILENAME


def empty_overrides(project_name: str, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": OVERRIDE_SCHEMA_VERSION,
        "project_id": _safe_project_id(project_name, catalog),
        "project_name": clean_text(project_name, "Proje"),
        "updated_at": _now(),
        "manual_items": {},
        "generated_visuals": {},
        "gallery_images": {},
        "field_overrides": {},
        "rejected_fields": {},
        "manual_alternative_links": [],
        "state_profiles": {},
        "attached_datasheets": {},
        "source_missing_decisions": {},
        "ui_preferences": deepcopy(DEFAULT_UI_PREFERENCES),
        "change_history": [],
    }


def load_overrides(
    project_name: str,
    catalog: HardwareCatalog | Mapping[str, Any] | None = None,
    output_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    path = overrides_path(project_name, catalog, output_root)
    if not path.exists():
        return empty_overrides(project_name, _catalog_dict(catalog))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as error:
        raise ValueError(f"Donanım Kartları kullanıcı verisi okunamadı: {error}") from error
    base = empty_overrides(project_name, _catalog_dict(catalog))
    if isinstance(raw, Mapping):
        for key in base:
            if key in raw:
                base[key] = deepcopy(raw[key])
    return base


def save_overrides(
    project_name: str,
    overrides: Mapping[str, Any],
    catalog: HardwareCatalog | Mapping[str, Any] | None = None,
    output_root: str | os.PathLike[str] | None = None,
) -> Path:
    payload = empty_overrides(project_name, _catalog_dict(catalog))
    payload.update(deepcopy(dict(overrides)))
    payload["schema_version"] = OVERRIDE_SCHEMA_VERSION
    payload["updated_at"] = _now()
    path = overrides_path(project_name, catalog, output_root)
    atomic_write_json(path, payload)
    return path


def update_ui_preferences(overrides: dict[str, Any], **values: Any) -> dict[str, Any]:
    """Proje bazlı katalog görünüm tercihlerini güvenli bindirmede saklar."""
    preferences = overrides.setdefault("ui_preferences", deepcopy(DEFAULT_UI_PREFERENCES))
    for key, value in values.items():
        if key in DEFAULT_UI_PREFERENCES:
            preferences[key] = deepcopy(value)
    return deepcopy(preferences)


def _get_nested(mapping: Mapping[str, Any], field_path: str) -> Any:
    value: Any = mapping
    for part in field_path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _set_nested(mapping: dict[str, Any], field_path: str, value: Any) -> None:
    parts = field_path.split(".")
    target = mapping
    for part in parts[:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    target[parts[-1]] = deepcopy(value)


def _item_index(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        clean_text(item.get("hardware_id")): item
        for item in catalog.get("hardware_items", [])
        if isinstance(item, dict) and clean_text(item.get("hardware_id"))
    }


def apply_overrides(
    catalog: HardwareCatalog | Mapping[str, Any] | None,
    overrides: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Kataloğun çalışma kopyasını üretir ve çözülmemiş çakışmaları döndürür."""
    view = _catalog_dict(catalog)
    if not view:
        view = {
            "project_id": "", "project_name": "", "version": "v0000",
            "hardware_items": [], "product_instances": [], "product_tree": [],
            "alternative_links": [], "unresolved_items": [], "conflicts": [], "sources": [],
        }
    overrides = deepcopy(dict(overrides or {}))
    by_id = _item_index(view)
    conflicts: list[dict[str, Any]] = []

    for hardware_id, item in dict(overrides.get("manual_items") or {}).items():
        if not isinstance(item, Mapping):
            continue
        materialized = deepcopy(dict(item))
        materialized["hardware_id"] = clean_text(materialized.get("hardware_id"), str(hardware_id))
        materialized["data_origin"] = "Manuel"
        if hardware_id in by_id:
            by_id[hardware_id].update(materialized)
        else:
            view.setdefault("hardware_items", []).append(materialized)
            by_id[hardware_id] = materialized

    # Otomatik illüstrasyon, gerçek katalog verisini değiştirmeyen ayrı bir
    # görünüm katmanıdır. Kullanıcı görseli/manuel alanlar aşağıda işlendiği
    # için her zaman bu kaydın önüne geçer.
    for hardware_id, record in dict(overrides.get("generated_visuals") or {}).items():
        item = by_id.get(hardware_id)
        if not item or not isinstance(record, Mapping):
            continue
        from donanim_kartlari_gorsel import visual_content_fingerprint
        if clean_text(record.get("content_fingerprint")) != visual_content_fingerprint(item):
            continue
        generated_path = clean_text(record.get("image_path"))
        current_path = clean_text(item.get("image_path"))
        if not generated_path or not Path(generated_path).is_file():
            continue
        if current_path and current_path != PLACEHOLDER_IMAGE and Path(current_path).is_file():
            continue
        item["image_path"] = generated_path
        item["image_source"] = clean_text(
            record.get("image_source"),
            "AI içerik temelli teknik illüstrasyon (gerçek ürün fotoğrafı değildir)",
        )
        item["image_is_generated"] = True
        item["visual_brief"] = deepcopy(record.get("visual_brief") or {})

    for hardware_id, fields in dict(overrides.get("field_overrides") or {}).items():
        item = by_id.get(hardware_id)
        if not item or not isinstance(fields, Mapping):
            continue
        item.setdefault("manual_fields", [])
        for field_path, record in fields.items():
            if not isinstance(record, Mapping):
                record = {"value": record, "base_value": None}
            auto_value = _get_nested(item, field_path)
            base_value = record.get("base_value")
            manual_value = record.get("value")
            if base_value is not None and auto_value != base_value and auto_value != manual_value:
                conflicts.append({
                    "type": "manual_auto_conflict", "hardware_id": hardware_id,
                    "field": field_path, "previous_auto_value": base_value,
                    "new_auto_value": auto_value, "manual_value": manual_value,
                    "message": "Otomatik tarama ile manuel değer farklı; manuel değer korunuyor.",
                })
            _set_nested(item, field_path, manual_value)
            if field_path not in item["manual_fields"]:
                item["manual_fields"].append(field_path)

    for hardware_id, fields in dict(overrides.get("rejected_fields") or {}).items():
        item = by_id.get(hardware_id)
        if not item:
            continue
        item.setdefault("rejected_fields", [])
        for field_path in fields or []:
            _set_nested(item, clean_text(field_path), MISSING_VALUE)
            if field_path not in item["rejected_fields"]:
                item["rejected_fields"].append(field_path)

    for hardware_id, records in dict(overrides.get("state_profiles") or {}).items():
        if hardware_id in by_id:
            by_id[hardware_id]["state_profiles"] = deepcopy(records or [])
    for hardware_id, paths in dict(overrides.get("attached_datasheets") or {}).items():
        if hardware_id in by_id:
            by_id[hardware_id]["attached_datasheets"] = list(dict.fromkeys(paths or []))
    for hardware_id, records in dict(overrides.get("gallery_images") or {}).items():
        item = by_id.get(hardware_id)
        if not item:
            continue
        combined = [
            deepcopy(dict(record)) for record in item.get("gallery_images", []) or []
            if isinstance(record, Mapping)
        ]
        seen_paths = {clean_text(record.get("path")) for record in combined}
        for record in records or []:
            if not isinstance(record, Mapping):
                continue
            path = clean_text(record.get("path"))
            if not path or path in seen_paths:
                continue
            combined.append(deepcopy(dict(record)))
            seen_paths.add(path)
        item["gallery_images"] = combined
    for hardware_id, record in dict(overrides.get("source_missing_decisions") or {}).items():
        item = by_id.get(hardware_id)
        if not item:
            continue
        decision = record.get("decision") if isinstance(record, Mapping) else record
        item["source_missing_decision"] = clean_text(decision, "Ertelendi")
        if decision == "Kullanımdan kaldırıldı":
            item["lifecycle_status"] = "Kullanımdan kaldırıldı"

    existing_links = {
        (clean_text(link.get("source_hardware_id")), clean_text(link.get("alternative_hardware_id")))
        for link in view.get("alternative_links", []) if isinstance(link, Mapping)
    }
    for link in overrides.get("manual_alternative_links", []) or []:
        if not isinstance(link, Mapping):
            continue
        key = (clean_text(link.get("source_hardware_id")), clean_text(link.get("alternative_hardware_id")))
        if not all(key) or key in existing_links:
            continue
        view.setdefault("alternative_links", []).append(deepcopy(dict(link)))
        existing_links.add(key)
        if key[0] in by_id:
            alternatives = by_id[key[0]].setdefault("alternative_ids", [])
            if key[1] not in alternatives:
                alternatives.append(key[1])

    view["hardware_items"] = sorted(
        view.get("hardware_items", []),
        key=lambda item: (clean_text(item.get("part_name")).casefold(), clean_text(item.get("hardware_id"))),
    )
    view["manual_conflicts"] = conflicts
    view["user_overrides_applied"] = bool(overrides)
    return view, conflicts


def record_change(
    overrides: dict[str, Any], hardware_id: str, action: str, field: str = "",
    old_value: Any = None, new_value: Any = None, actor: str = "Kullanıcı",
) -> None:
    """Donanım kartındaki kullanıcı eylemini salt eklemeli geçmişe kaydeder."""
    overrides.setdefault("change_history", []).append({
        "timestamp": _now(), "hardware_id": clean_text(hardware_id),
        "action": clean_text(action, "Donanım kartı güncellendi"),
        "field": clean_text(field), "old_value": deepcopy(old_value),
        "new_value": deepcopy(new_value), "actor": clean_text(actor, "Kullanıcı"),
    })


def set_field_override(
    overrides: dict[str, Any], hardware_id: str, field_path: str,
    value: Any, base_catalog: HardwareCatalog | Mapping[str, Any] | None,
) -> None:
    raw = _catalog_dict(base_catalog)
    item = _item_index(raw).get(hardware_id, {})
    fields = overrides.setdefault("field_overrides", {}).setdefault(hardware_id, {})
    previous = fields.get(field_path)
    base_value = previous.get("base_value") if isinstance(previous, Mapping) else _get_nested(item, field_path)
    old_value = previous.get("value") if isinstance(previous, Mapping) else base_value
    fields[field_path] = {"value": deepcopy(value), "base_value": deepcopy(base_value), "updated_at": _now()}
    if old_value != value:
        record_change(
            overrides, hardware_id, "Manuel alan düzenlemesi", field_path,
            old_value=old_value, new_value=value,
        )


def set_generated_visuals(
    overrides: dict[str, Any], records: Mapping[str, Mapping[str, Any]],
) -> None:
    """Üretilen görselleri kullanıcı alanlarından ayrı bir katmanda saklar."""
    target = overrides.setdefault("generated_visuals", {})
    for hardware_id, record in records.items():
        if not isinstance(record, Mapping):
            continue
        path = clean_text(record.get("image_path"))
        if not hardware_id or not path:
            continue
        payload = deepcopy(dict(record))
        payload["image_path"] = path
        payload["updated_at"] = _now()
        target[clean_text(hardware_id)] = payload


def add_gallery_image(
    overrides: dict[str, Any], hardware_id: str, record: Mapping[str, Any],
) -> None:
    """Kullanıcı tarafından kabul edilen görseli metadata'sıyla galeriye ekler."""
    path = clean_text(record.get("path"))
    if not path:
        raise ValueError("Galeriye eklenecek görsel yolu bulunamadı.")
    values = overrides.setdefault("gallery_images", {}).setdefault(hardware_id, [])
    values[:] = [
        deepcopy(dict(value)) for value in values
        if isinstance(value, Mapping) and clean_text(value.get("path")) != path
    ]
    payload = deepcopy(dict(record)); payload["path"] = path
    payload.setdefault("created_at", _now()); payload.setdefault("is_cover", False)
    values.append(payload)
    record_change(
        overrides, hardware_id, "Galeri görseli kullanıcı tarafından kabul edildi",
        "gallery_images", new_value={
            "path": path, "source_type": payload.get("source_type"),
            "is_ai": bool(payload.get("is_ai")),
        },
    )


def remove_gallery_image(
    overrides: dict[str, Any], hardware_id: str, image_path: str,
) -> bool:
    """Galeri kaydını kaldırır; özgün datasheet veya gerçek dosyayı silmez."""
    values = overrides.setdefault("gallery_images", {}).setdefault(hardware_id, [])
    before = len(values)
    values[:] = [
        value for value in values
        if not isinstance(value, Mapping) or clean_text(value.get("path")) != clean_text(image_path)
    ]
    changed = len(values) != before
    if changed:
        record_change(
            overrides, hardware_id, "Galeri görseli kaldırıldı", "gallery_images",
            old_value=clean_text(image_path),
        )
    return changed


def reject_automatic_field(overrides: dict[str, Any], hardware_id: str, field_path: str) -> None:
    fields = overrides.setdefault("rejected_fields", {}).setdefault(hardware_id, [])
    if field_path not in fields:
        fields.append(field_path)
        record_change(overrides, hardware_id, "Otomatik alan reddedildi", field_path)


def add_manual_item(overrides: dict[str, Any], values: Mapping[str, Any]) -> str:
    part_name = clean_text(values.get("part_name"), "Yeni Donanım")
    hardware_id = clean_text(values.get("hardware_id"))
    if not hardware_id:
        slug = re.sub(r"[^A-Z0-9]+", "-", part_name.upper()).strip("-")[:32] or "DONANIM"
        hardware_id = f"MAN-{slug}-{uuid.uuid4().hex[:6].upper()}"
    card = HardwareCard(
        hardware_id=hardware_id,
        part_name=part_name,
        part_number=values.get("part_number", MISSING_VALUE),
        manufacturer=values.get("manufacturer", MISSING_VALUE),
        model_series=values.get("model_series", MISSING_VALUE),
        hardware_type=values.get("hardware_type", "Parça/bileşen"),
        description=values.get("description", MISSING_VALUE),
        system_role=values.get("system_role", MISSING_VALUE),
        parent_id=values.get("parent_id", MISSING_VALUE),
        image_path=values.get("image_path", PLACEHOLDER_IMAGE),
        working_states=list(values.get("working_states") or ["Normal"]),
        lifecycle_status=values.get("lifecycle_status", "Önerilen"),
        requirement_ids=list(values.get("requirement_ids") or []),
        alternative_ids=list(values.get("alternative_ids") or []),
        source_evidence=[SourceEvidence(
            field_name="manual_item", source_document="Kullanıcı girişi",
            evidence_text="Donanım Kartları ekranında kullanıcı tarafından eklendi.",
            extraction_method="manual", field_confidence=100, certainty="Kesin bilgi",
        )],
    )
    card.confidence_score, card.confidence_breakdown = calculate_card_confidence(card)
    payload = card.to_dict()
    payload["data_origin"] = "Manuel"
    overrides.setdefault("manual_items", {})[hardware_id] = payload
    return hardware_id


def add_alternative_link(
    overrides: dict[str, Any], source_id: str, alternative_id: str,
    reason: str, compatibility_status: str = "İncelenmedi",
) -> None:
    links = overrides.setdefault("manual_alternative_links", [])
    key = (source_id, alternative_id)
    links[:] = [
        item for item in links
        if (item.get("source_hardware_id"), item.get("alternative_hardware_id")) != key
    ]
    links.append({
        "source_hardware_id": source_id,
        "alternative_hardware_id": alternative_id,
        "reason": clean_text(reason, MISSING_VALUE),
        "compatibility_status": compatibility_status,
        "parameter_differences": {}, "met_requirements": [], "unmet_requirements": [],
        "new_risks": [], "source": "Kullanıcı girişi", "user_approval": "Onay bekliyor",
    })
    record_change(
        overrides, source_id, "Alternatif bağlantısı eklendi", "alternative_ids",
        new_value=alternative_id,
    )


def add_state_profile(
    overrides: dict[str, Any], hardware_id: str, state_name: str,
    changed_parameters: str = "", affected_requirements: Sequence[str] = (),
) -> None:
    records = overrides.setdefault("state_profiles", {}).setdefault(hardware_id, [])
    records.append({
        "state": clean_text(state_name, "Kullanıcı tanımlı durum"),
        "changed_parameters": clean_text(changed_parameters, MISSING_VALUE),
        "affected_requirements": [clean_text(item) for item in affected_requirements if clean_text(item)],
        "source": "Kullanıcı girişi", "updated_at": _now(),
    })
    record_change(
        overrides, hardware_id, "Çalışma durumu eklendi", "state_profiles",
        new_value=clean_text(state_name, "Kullanıcı tanımlı durum"),
    )


def attach_datasheets(overrides: dict[str, Any], hardware_id: str, paths: Iterable[str]) -> None:
    values = overrides.setdefault("attached_datasheets", {}).setdefault(hardware_id, [])
    for path in paths:
        absolute = str(Path(path).expanduser().resolve())
        if absolute not in values:
            values.append(absolute)
            record_change(
                overrides, hardware_id, "Datasheet bağlandı", "attached_datasheets",
                new_value=absolute,
            )


def resolve_manual_auto_conflict(
    overrides: dict[str, Any], conflict: Mapping[str, Any], decision: str,
) -> None:
    """Manuel/otomatik alan çakışmasını açık kullanıcı kararıyla çözer."""
    hardware_id = clean_text(conflict.get("hardware_id"))
    field_path = clean_text(conflict.get("field"))
    fields = overrides.setdefault("field_overrides", {}).get(hardware_id, {})
    record = fields.get(field_path)
    if not isinstance(record, dict):
        return
    if decision == "Otomatik değeri kabul et":
        fields.pop(field_path, None)
        if not fields:
            overrides.get("field_overrides", {}).pop(hardware_id, None)
    elif decision == "Manuel değeri koru":
        record["base_value"] = deepcopy(conflict.get("new_auto_value"))
        record["decision"] = decision
        record["updated_at"] = _now()


def record_source_missing_decision(
    overrides: dict[str, Any], hardware_id: str, decision: str,
) -> None:
    if decision not in {"Korunsun", "Kullanımdan kaldırıldı", "Ertelendi"}:
        raise ValueError("Geçersiz kaynakta bulunamayan parça kararı.")
    overrides.setdefault("source_missing_decisions", {})[hardware_id] = {
        "decision": decision, "updated_at": _now(),
    }


def compare_catalogs(
    previous: HardwareCatalog | Mapping[str, Any] | None,
    current: HardwareCatalog | Mapping[str, Any] | None,
) -> dict[str, Any]:
    old, new = _catalog_dict(previous), _catalog_dict(current)
    old_items, new_items = _item_index(old), _item_index(new)
    added = sorted(set(new_items) - set(old_items))
    missing = sorted(
        (set(old_items) - set(new_items))
        | {
            hardware_id for hardware_id, item in new_items.items()
            if item.get("source_presence_status") == "Kaynaktan artık bulunamadı"
        }
    )
    changed: list[dict[str, Any]] = []
    compared_fields = (
        "part_name", "part_number", "manufacturer", "model_series", "hardware_type",
        "system_role", "parent_id", "lifecycle_status", "technical_data",
        "requirement_ids", "test_ids", "alternative_ids", "confidence_score",
        "source_presence_status",
    )
    for hardware_id in sorted(set(old_items) & set(new_items)):
        differences = []
        for field in compared_fields:
            if old_items[hardware_id].get(field) != new_items[hardware_id].get(field):
                differences.append({
                    "field": field, "old": deepcopy(old_items[hardware_id].get(field)),
                    "new": deepcopy(new_items[hardware_id].get(field)),
                })
        if differences:
            changed.append({"hardware_id": hardware_id, "changes": differences})
    return {
        "new_items": added, "changed_items": changed, "missing_items": missing,
        "conflicts": list(new.get("conflicts", [])),
        "counts": {
            "new": len(added), "changed": len(changed), "missing": len(missing),
            "conflicts": len(new.get("conflicts", [])),
        },
    }


def _has_datasheet(item: Mapping[str, Any]) -> bool:
    if any(clean_text(path) for path in item.get("attached_datasheets", []) or []):
        return True
    for evidence in item.get("source_evidence", []) or []:
        if not isinstance(evidence, Mapping):
            continue
        method = clean_text(evidence.get("extraction_method")).casefold()
        document = clean_text(evidence.get("source_document")).casefold()
        if "datasheet" in method or "datasheet" in document:
            return True
    return False


def _has_usable_image(item: Mapping[str, Any]) -> bool:
    path = clean_text(item.get("image_path"))
    if path and path != PLACEHOLDER_IMAGE and Path(path).is_file():
        return True
    return any(
        isinstance(record, Mapping)
        and clean_text(record.get("path"))
        and Path(clean_text(record.get("path"))).is_file()
        for record in item.get("gallery_images", []) or []
    )


def filter_cards(
    catalog: Mapping[str, Any], *, search: str = "", manufacturer: str = "",
    working_state: str = "", lifecycle_status: str = "", confidence: str = "",
    system_filter: str = "", impacted_only: bool = False,
    no_alternative_only: bool = False, no_datasheet_only: bool = False,
    impacted_ids: Iterable[str] | None = None, sort_by: str = "",
) -> list[dict[str, Any]]:
    query = clean_text(search).casefold()
    item_index = {
        clean_text(item.get("hardware_id")): item
        for item in catalog.get("hardware_items", [])
        if isinstance(item, Mapping) and clean_text(item.get("hardware_id"))
    }

    def system_memberships(item: Mapping[str, Any]) -> set[str]:
        memberships: set[str] = set()
        current: Mapping[str, Any] | None = item
        visited: set[str] = set()
        while current:
            current_id = clean_text(current.get("hardware_id"))
            if current_id in visited:
                break
            visited.add(current_id)
            memberships.update({
                current_id,
                clean_text(current.get("part_name")),
                clean_text(current.get("hardware_type")),
            })
            parent_id = clean_text(current.get("parent_id"))
            current = item_index.get(parent_id)
        return {value for value in memberships if value and not is_missing(value)}

    impacted = {clean_text(value) for value in (impacted_ids or []) if clean_text(value)}
    result = []
    for item in catalog.get("hardware_items", []):
        if not isinstance(item, Mapping):
            continue
        haystack = " ".join(clean_text(item.get(key)) for key in (
            "hardware_id", "part_name", "part_number", "manufacturer", "model_series",
            "hardware_type", "description", "system_role", "parent_id",
        )).casefold()
        if query and query not in haystack:
            continue
        if manufacturer and manufacturer != "Tümü" and clean_text(item.get("manufacturer")) != manufacturer:
            continue
        if working_state and working_state != "Tümü" and working_state not in (item.get("working_states") or []):
            continue
        if lifecycle_status and lifecycle_status != "Tümü" and clean_text(item.get("lifecycle_status")) != lifecycle_status:
            continue
        if system_filter and system_filter != "Tümü":
            if system_filter not in system_memberships(item):
                continue
        score = item.get("confidence_score")
        try:
            numeric_score = float(score)
        except (TypeError, ValueError):
            numeric_score = -1
        if confidence == "Yüksek (80–100)" and numeric_score < 80:
            continue
        if confidence == "Orta (60–79)" and not 60 <= numeric_score < 80:
            continue
        if confidence == "Düşük (0–59)" and not 0 <= numeric_score < 60:
            continue
        if confidence == "Hesaplanamadı" and numeric_score >= 0:
            continue
        hardware_id = clean_text(item.get("hardware_id"))
        if impacted_only and hardware_id not in impacted:
            continue
        if no_alternative_only and bool(item.get("alternative_ids")):
            continue
        if no_datasheet_only and _has_datasheet(item):
            continue
        result.append(deepcopy(dict(item)))
    def sort_score(item: Mapping[str, Any]) -> float:
        try:
            return float(item.get("confidence_score"))
        except (TypeError, ValueError):
            return -1.0

    if sort_by == "Güven: düşükten yükseğe":
        result.sort(key=lambda item: (sort_score(item), clean_text(item.get("part_name")).casefold()))
    elif sort_by == "Parça adı: A–Z":
        result.sort(key=lambda item: clean_text(item.get("part_name")).casefold())
    elif sort_by == "Üretici: A–Z":
        result.sort(key=lambda item: (clean_text(item.get("manufacturer")).casefold(), clean_text(item.get("part_name")).casefold()))
    else:
        result.sort(key=lambda item: (-sort_score(item), clean_text(item.get("part_name")).casefold()))
    return result


def catalog_quality_summary(
    catalog: Mapping[str, Any], *, impacted_ids: Iterable[str] | None = None,
) -> dict[str, int]:
    """Üst kalite şeridi için eyleme dönük, deterministik katalog sayıları."""
    items = [item for item in catalog.get("hardware_items", []) if isinstance(item, Mapping)]
    impacted = {clean_text(value) for value in (impacted_ids or []) if clean_text(value)}
    high = low = missing_datasheet = missing_image = missing_requirements = 0
    missing_tests = critical_without_alternative = no_alternatives = 0
    for item in items:
        try:
            score = float(item.get("confidence_score"))
        except (TypeError, ValueError):
            score = -1
        high += int(score >= 80)
        low += int(0 <= score < 60)
        missing_datasheet += int(not _has_datasheet(item))
        missing_image += int(not _has_usable_image(item))
        missing_requirements += int(not bool(item.get("requirement_ids")))
        missing_tests += int(bool(item.get("requirement_ids")) and not bool(item.get("test_ids")))
        alternatives = list(item.get("alternative_ids") or [])
        no_alternatives += int(not alternatives)
        is_critical = (
            "Kritik etki" in (item.get("impact_badges") or [])
            or clean_text(item.get("criticality")).casefold() in {"kritik", "critical"}
            or clean_text(item.get("hardware_id")) in impacted
        )
        critical_without_alternative += int(is_critical and not alternatives)
    return {
        "total": len(items), "high_confidence": high, "low_confidence": low,
        "missing_datasheet": missing_datasheet, "missing_image": missing_image,
        "missing_requirements": missing_requirements, "missing_tests": missing_tests,
        "critical_without_alternative": critical_without_alternative,
        "conflicts": len(catalog.get("conflicts", []) or []) + len(catalog.get("manual_conflicts", []) or []),
        "impacted": len(impacted), "no_alternatives": no_alternatives,
    }


def confidence_label(score: Any) -> tuple[str, str]:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "Hesaplanamadı", "none"
    if value >= 80:
        return "Yüksek güven", "high"
    if value >= 60:
        return "Orta güven", "medium"
    return "Düşük güven", "low"


def _number(value: Any) -> float | None:
    if value is None or is_missing(value):
        return None
    try:
        return float(str(value).replace(",", ".").split()[0])
    except (TypeError, ValueError):
        return None


def build_impact_payload(
    catalog: Mapping[str, Any], hardware_id: str, alternative_id: str | None = None,
) -> dict[str, Any]:
    by_id = _item_index(catalog)
    current = by_id.get(hardware_id)
    if not current:
        raise ValueError("Etki Analizine gönderilecek donanım kartı bulunamadı.")
    alternative_ids = list(current.get("alternative_ids") or [])
    for link in catalog.get("alternative_links", []):
        if isinstance(link, Mapping) and clean_text(link.get("source_hardware_id")) == hardware_id:
            alt_id = clean_text(link.get("alternative_hardware_id"))
            if alt_id and alt_id not in alternative_ids:
                alternative_ids.append(alt_id)
    if alternative_id:
        alternative_id = clean_text(alternative_id)
        alternative_ids = [alternative_id] if alternative_id in alternative_ids else []
    alternatives = [by_id[item_id] for item_id in alternative_ids if item_id in by_id]
    if not alternatives:
        raise ValueError("Bu donanım için karşılaştırılabilir alternatif bulunamadı.")

    current_td = dict(current.get("technical_data") or {})
    parameters = []
    for key, label in TECHNICAL_LABELS.items():
        current_value = _number(current_td.get(key))
        alt_values = {
            clean_text(alt.get("part_name"), alt.get("hardware_id")): _number((alt.get("technical_data") or {}).get(key))
            for alt in alternatives
        }
        if current_value is None or not any(value is not None for value in alt_values.values()):
            continue
        unit_ref = TECHNICAL_UNITS.get(key, "")
        unit = current_td.get(unit_ref, unit_ref) if unit_ref else ""
        direction = "Düşük daha iyi" if key in {
            "weight", "power_consumption", "operating_temperature_min", "storage_temperature_min",
        } else "Yüksek daha iyi"
        parameters.append({
            "name": label, "current_value": current_value, "unit": unit or "",
            "weight": 1, "direction": direction, "minimum": "", "maximum": "",
            "mandatory": False,
            "alternative_values": {
                name: "" if value is None else value for name, value in alt_values.items()
            },
        })
    if parameters:
        weight = round(100 / len(parameters), 4)
        for item in parameters:
            item["weight"] = weight
    return {
        "analysis_name": f"{clean_text(current.get('part_name'))} alternatif karşılaştırması",
        "current_state": clean_text(current.get("part_name")),
        "change_reason": (
            "Donanım Kartları kataloğundan aktarıldı.\n"
            f"Bağlı gereksinimler: {', '.join(current.get('requirement_ids') or []) or MISSING_VALUE}\n"
            f"Bağlı testler: {', '.join(current.get('test_ids') or []) or MISSING_VALUE}"
        ),
        "alternatives": [clean_text(item.get("part_name"), item.get("hardware_id")) for item in alternatives],
        "parameters": parameters,
        "hardware_context": {
            "hardware_id": hardware_id,
            "parent_id": clean_text(current.get("parent_id"), MISSING_VALUE),
            "requirement_ids": list(current.get("requirement_ids") or []),
            "test_ids": list(current.get("test_ids") or []),
            "alternative_ids": alternative_ids,
        },
    }


def build_impact_badges(
    catalog: Mapping[str, Any], simulation_result: Mapping[str, Any] | None,
) -> dict[str, list[str]]:
    if not simulation_result:
        return {}
    impacts = simulation_result.get("impacts", []) or []
    suggestions = simulation_result.get("engineering_suggestions", []) or []
    badges: dict[str, list[str]] = {}
    for item in catalog.get("hardware_items", []):
        if not isinstance(item, Mapping):
            continue
        hardware_id = clean_text(item.get("hardware_id"))
        aliases = {hardware_id.casefold(), clean_text(item.get("part_name")).casefold()}
        requirement_ids = {clean_text(value).casefold() for value in item.get("requirement_ids", [])}
        test_ids = {clean_text(value).casefold() for value in item.get("test_ids", [])}
        matched = []
        for impact in impacts:
            if not isinstance(impact, Mapping):
                continue
            impact_id = clean_text(impact.get("item_id", impact.get("id"))).casefold()
            path = impact.get("traceability_path") or {}
            path_ids = {clean_text(value).casefold() for value in path.get("node_ids", [])} if isinstance(path, Mapping) else set()
            if impact_id in aliases or aliases & path_ids or requirement_ids & ({impact_id} | path_ids):
                matched.append(impact)
        values: list[str] = []
        if any(clean_text(item.get("impact_level")) == "Kritik" for item in matched):
            values.append("Kritik etki")
        elif any(clean_text(item.get("impact_level")) in {"Yüksek", "Orta"} for item in matched):
            values.append("Güncelleme gerekli")
        if any(clean_text(item.get("item_id", item.get("id"))).casefold() in test_ids for item in impacts if isinstance(item, Mapping)):
            values.append("Test gerekli")
        if any(
            aliases & {clean_text(value).casefold() for value in suggestion.get("affected_items", [])}
            for suggestion in suggestions if isinstance(suggestion, Mapping)
        ):
            values.append("Alternatif önerildi")
        if item.get("missing_information"):
            values.append("Veri eksik")
        if values:
            badges[hardware_id] = list(dict.fromkeys(values))
    return badges


_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "mm": ("mm", 1.0), "cm": ("mm", 10.0), "m": ("mm", 1000.0),
    "g": ("g", 1.0), "kg": ("g", 1000.0), "mg": ("g", 0.001),
    "mv": ("V", 0.001), "v": ("V", 1.0), "kv": ("V", 1000.0),
    "mw": ("W", 0.001), "w": ("W", 1.0), "kw": ("W", 1000.0),
    "°c": ("°C", 1.0), "c": ("°C", 1.0),
}


def normalize_technical_value(value: Any, unit: Any) -> tuple[float | None, str]:
    """Karşılaştırma için desteklenen birimleri ortak tabana dönüştürür."""
    numeric = _number(value)
    raw_unit = clean_text(unit)
    if numeric is None:
        return None, raw_unit or MISSING_VALUE
    canonical, factor = _UNIT_FACTORS.get(raw_unit.casefold(), (raw_unit, 1.0))
    return round(numeric * factor, 8), canonical


def _technical_source(item: Mapping[str, Any], key: str) -> tuple[str, Any]:
    candidates = {key, f"technical_data.{key}"}
    for evidence in item.get("source_evidence", []) or []:
        if not isinstance(evidence, Mapping):
            continue
        if clean_text(evidence.get("field_name")) in candidates:
            source = clean_text(evidence.get("source_document"), MISSING_VALUE)
            location = clean_text(evidence.get("location"))
            if location and not is_missing(location):
                source = f"{source} · {location}"
            return source, evidence.get("field_confidence", 0)
    field_confidence = item.get("field_confidence") or {}
    return MISSING_VALUE, field_confidence.get(key, field_confidence.get(f"technical_data.{key}", 0))


def build_multi_comparison(
    catalog: Mapping[str, Any], hardware_ids: Sequence[str],
    traceability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """İki-dört kartı kanıt, güven ve eksik-veri tarafsızlığıyla karşılaştırır."""
    ids = list(dict.fromkeys(clean_text(value) for value in hardware_ids if clean_text(value)))
    if not 2 <= len(ids) <= 4:
        raise ValueError("Karşılaştırma için 2 ile 4 arasında donanım seçin.")
    by_id = _item_index(catalog)
    missing_ids = [value for value in ids if value not in by_id]
    if missing_ids:
        raise ValueError(f"Karşılaştırılacak donanım bulunamadı: {', '.join(missing_ids)}")
    items = [deepcopy(by_id[value]) for value in ids]
    trace_nodes = {
        clean_text(node.get("id")): node for node in (traceability or {}).get("nodes", [])
        if isinstance(node, Mapping) and clean_text(node.get("id"))
    }

    mandatory_violations: list[dict[str, Any]] = []
    requirement_rows: list[dict[str, Any]] = []
    requirement_ids = sorted({req for item in items for req in item.get("requirement_ids", []) or []})
    for requirement_id in requirement_ids:
        node = trace_nodes.get(requirement_id, {})
        mandatory = bool(node.get("mandatory")) or clean_text(
            node.get("criticality", node.get("priority"))
        ).casefold() in {"zorunlu", "kritik", "mandatory", "critical"}
        values = {item["hardware_id"]: requirement_id in (item.get("requirement_ids") or []) for item in items}
        row = {
            "kind": "requirement", "key": requirement_id,
            "label": clean_text(node.get("title"), requirement_id), "unit": "—",
            "mandatory": mandatory, "values": values,
            "source": clean_text(node.get("source_document"), MISSING_VALUE),
            "confidence": node.get("confidence_score", node.get("confidence_level", MISSING_VALUE)),
        }
        requirement_rows.append(row)
        for hardware_id, met in values.items():
            if mandatory and not met:
                mandatory_violations.append({
                    "hardware_id": hardware_id, "requirement_id": requirement_id,
                    "message": "Zorunlu gereksinim bağlantısı bulunamadı.",
                    "source": row["source"],
                })

    parameter_rows: list[dict[str, Any]] = []
    for key, label in TECHNICAL_LABELS.items():
        unit_ref = TECHNICAL_UNITS.get(key, "")
        raw_values: dict[str, Any] = {}
        normalized: dict[str, Any] = {}
        sources: dict[str, str] = {}
        confidences: dict[str, Any] = {}
        units: list[str] = []
        for item in items:
            hardware_id = clean_text(item.get("hardware_id"))
            technical = item.get("technical_data") or {}
            raw = technical.get(key, MISSING_VALUE)
            unit = technical.get(unit_ref, unit_ref) if unit_ref else ""
            value, canonical_unit = normalize_technical_value(raw, unit)
            raw_values[hardware_id] = raw
            normalized[hardware_id] = value
            if value is not None and canonical_unit and not is_missing(canonical_unit):
                units.append(canonical_unit)
            sources[hardware_id], confidences[hardware_id] = _technical_source(item, key)
        if not any(value is not None for value in normalized.values()):
            continue
        unit = units[0] if units and len(set(units)) == 1 else (" / ".join(sorted(set(units))) or MISSING_VALUE)
        available = [value for value in normalized.values() if value is not None]
        reference = available[0] if available else None
        assessments = {}
        for hardware_id, value in normalized.items():
            if value is None:
                assessments[hardware_id] = "Veri eksik — puanlanmadı"
            elif reference is None or value == reference:
                assessments[hardware_id] = "Nötr"
            else:
                assessments[hardware_id] = "Farklı"
        parameter_rows.append({
            "kind": "parameter", "key": key, "label": label, "unit": unit,
            "mandatory": False, "values": raw_values, "normalized_values": normalized,
            "assessments": assessments, "sources": sources, "confidences": confidences,
        })

    return {
        "hardware_ids": ids, "items": items,
        "mandatory_violations": mandatory_violations,
        "requirement_rows": sorted(requirement_rows, key=lambda row: (not row["mandatory"], row["key"])),
        "parameter_rows": parameter_rows,
        "missing_is_neutral": True,
        "method": (
            "Sayısal değerler desteklenen birimlerde ortak tabana dönüştürülür. "
            "Eksik veri üstünlük veya dezavantaj sayılmaz; 'Veri eksik — puanlanmadı' olarak gösterilir. "
            "Zorunlu gereksinim bağlantısı bulunmayan ürünler listenin başında işaretlenir."
        ),
    }


def build_multi_impact_payload(
    catalog: Mapping[str, Any], hardware_ids: Sequence[str],
    traceability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    comparison = build_multi_comparison(catalog, hardware_ids, traceability)
    items = comparison["items"]
    current, alternatives = items[0], items[1:]
    parameters = []
    for row in comparison["parameter_rows"]:
        values = row["normalized_values"]
        current_value = values.get(current["hardware_id"])
        alt_values = {
            clean_text(item.get("part_name"), item["hardware_id"]): values.get(item["hardware_id"])
            for item in alternatives
        }
        if current_value is None or not any(value is not None for value in alt_values.values()):
            continue
        parameters.append({
            "name": row["label"], "current_value": current_value,
            "unit": "" if is_missing(row["unit"]) else row["unit"],
            "weight": 1, "direction": "Yüksek daha iyi", "minimum": "", "maximum": "",
            "mandatory": False,
            "alternative_values": {
                name: "" if value is None else value for name, value in alt_values.items()
            },
        })
    if parameters:
        weight = round(100 / len(parameters), 6)
        for parameter in parameters:
            parameter["weight"] = weight
    return {
        "analysis_name": f"{clean_text(current.get('part_name'))} çoklu donanım karşılaştırması",
        "current_state": clean_text(current.get("part_name")),
        "change_reason": (
            "Donanım Kataloğu çoklu karşılaştırmasından aktarıldı. Eksik teknik veri "
            "puanlanmadı; zorunlu gereksinim uyarıları karşılaştırma ekranında gösterildi."
        ),
        "alternatives": [clean_text(item.get("part_name"), item["hardware_id"]) for item in alternatives],
        "parameters": parameters,
        "hardware_context": {
            "hardware_id": current["hardware_id"],
            "parent_id": clean_text(current.get("parent_id"), MISSING_VALUE),
            "comparison_hardware_ids": comparison["hardware_ids"],
            "requirement_ids": sorted({value for item in items for value in item.get("requirement_ids", []) or []}),
            "test_ids": sorted({value for item in items for value in item.get("test_ids", []) or []}),
            "mandatory_violations": comparison["mandatory_violations"],
        },
    }


def archive_hardware_item(
    overrides: dict[str, Any], hardware_id: str,
    base_catalog: Mapping[str, Any] | None,
) -> None:
    """Kartı silmeden yaşam döngüsünde arşivler."""
    set_field_override(overrides, hardware_id, "lifecycle_status", "Kullanımdan kaldırıldı", base_catalog)
    record_change(overrides, hardware_id, "Donanım kartı arşivlendi", "lifecycle_status")


def undo_last_manual_change(
    overrides: dict[str, Any], base_catalog: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Son alan düzenlemesini geri alır; geçmiş kaydı silinmez."""
    history = overrides.setdefault("change_history", [])
    for record in reversed(history):
        if not isinstance(record, Mapping) or record.get("undone_at"):
            continue
        hardware_id = clean_text(record.get("hardware_id"))
        field = clean_text(record.get("field"))
        if not hardware_id or not field or record.get("action") != "Manuel alan düzenlemesi":
            continue
        fields = overrides.setdefault("field_overrides", {}).setdefault(hardware_id, {})
        previous = fields.get(field)
        base_value = previous.get("base_value") if isinstance(previous, Mapping) else _get_nested(
            _item_index(_catalog_dict(base_catalog)).get(hardware_id, {}), field
        )
        old_value = deepcopy(record.get("old_value"))
        fields[field] = {"value": old_value, "base_value": deepcopy(base_value), "updated_at": _now()}
        record["undone_at"] = _now()
        record_change(
            overrides, hardware_id, "Son manuel değişiklik geri alındı", field,
            old_value=record.get("new_value"), new_value=old_value,
        )
        return deepcopy(dict(record))
    return None


def sample_catalog(project_name: str = "ÖRNEK — GERÇEK PROJE VERİSİ DEĞİLDİR") -> dict[str, Any]:
    """Arayüz geliştirme/testi için istenen örnek ürün ağacını üretir."""
    cards = [
        HardwareCard("SAMPLE-SYS", "Kontrol Sistemi", hardware_type="Sistem", system_role="Sistem seviyesi ürün ağacı kökü", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-PWR", "Güç Alt Sistemi", hardware_type="Alt sistem", parent_id="SAMPLE-SYS", system_role="Güç üretimi ve dağıtımı", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-PDB", "Güç Dağıtım Kartı", part_number="PDB-DEMO-01", hardware_type="Kart/modül", parent_id="SAMPLE-PWR", system_role="Güç hatlarını korur ve dağıtır", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-DCDC", "DC/DC Dönüştürücü", part_number="DCDC-DEMO-A", manufacturer="Örnek Üretici", hardware_type="Parça/bileşen", parent_id="SAMPLE-PDB", system_role="Ana beslemeyi alt gerilim rayına dönüştürür", lifecycle_status="Önerilen", technical_data=TechnicalData(operating_temperature_min=-40, operating_temperature_max=85, temperature_unit="°C", width=24, length=32, height=11, dimension_unit="mm", weight=18, weight_unit="g", supply_voltage=28, power_consumption=12), requirement_ids=["DEMO-REQ-PWR-001"], test_ids=["DEMO-TEST-PWR-001"], alternative_ids=["SAMPLE-DCDC-B", "SAMPLE-DCDC-C"]),
        HardwareCard("SAMPLE-DCDC-B", "DC/DC Alternatif B", part_number="DCDC-DEMO-B", manufacturer="Örnek Üretici B", hardware_type="Parça/bileşen", system_role="Koşullu alternatif dönüştürücü", lifecycle_status="Alternatif", technical_data=TechnicalData(operating_temperature_min=-40, operating_temperature_max=105, temperature_unit="°C", width=26, length=34, height=10, dimension_unit="mm", weight=20, weight_unit="g", supply_voltage=28, power_consumption=10)),
        HardwareCard("SAMPLE-DCDC-C", "DC/DC Alternatif C", part_number="DCDC-DEMO-C", manufacturer="Örnek Üretici C", hardware_type="Parça/bileşen", system_role="İncelenmemiş alternatif dönüştürücü", lifecycle_status="Alternatif", technical_data=TechnicalData(operating_temperature_min=-25, operating_temperature_max=85, temperature_unit="°C", width=22, length=30, height=12, dimension_unit="mm", weight=16, weight_unit="g", supply_voltage=24, power_consumption=9)),
        HardwareCard("SAMPLE-CUR", "Akım Sensörü", part_number="CUR-DEMO-01", hardware_type="Parça/bileşen", parent_id="SAMPLE-PDB", system_role="Hat akımını ölçer", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-CPU-SUB", "İşlemci Alt Sistemi", hardware_type="Alt sistem", parent_id="SAMPLE-SYS", system_role="Kontrol algoritmalarını yürütür", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-MCB", "Ana Kontrol Kartı", part_number="MCB-DEMO-01", hardware_type="Kart/modül", parent_id="SAMPLE-CPU-SUB", system_role="İşlem, bellek ve algılayıcıları barındırır", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-CPU", "İşlemci", part_number="CPU-DEMO-01", hardware_type="Parça/bileşen", parent_id="SAMPLE-MCB", system_role="Kontrol yazılımını yürütür", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-MEM", "Bellek", part_number="MEM-DEMO-01", hardware_type="Parça/bileşen", parent_id="SAMPLE-MCB", system_role="Çalışma verisini saklar", lifecycle_status="Önerilen"),
        HardwareCard("SAMPLE-TEMP", "Sıcaklık Sensörü", part_number="TEMP-DEMO-01", hardware_type="Parça/bileşen", parent_id="SAMPLE-MCB", system_role="Kart sıcaklığını izler", lifecycle_status="Önerilen"),
    ]
    instances = []
    tree = []
    id_map: dict[str, str] = {}
    alternative_definition_ids = {"SAMPLE-DCDC-B", "SAMPLE-DCDC-C"}
    for card in cards:
        if card.hardware_id in alternative_definition_ids:
            card.confidence_score, card.confidence_breakdown = calculate_card_confidence(card)
            continue
        instance_id = f"INST-{card.hardware_id}"
        id_map[card.hardware_id] = instance_id
        parent_instance = f"INST-{card.parent_id}" if not is_missing(card.parent_id) else MISSING_VALUE
        instance = ProductInstance(instance_id, card.hardware_id, parent_instance_id=parent_instance, level=card.hardware_type)
        instances.append(instance)
        tree.append({
            "instance_id": instance_id, "hardware_id": card.hardware_id,
            "parent_instance_id": parent_instance, "quantity": 1,
            "location": "Örnek ürün ağacı", "level": card.hardware_type,
        })
        card.confidence_score, card.confidence_breakdown = calculate_card_confidence(card)
    catalog = HardwareCatalog(
        project_id="sample-hardware-tree", project_name=project_name, version="DEMO",
        hardware_items=cards, product_instances=instances, product_tree=tree,
        alternative_links=[], sources=[{
            "name": "Örnek Donanım Ağacı", "kind": "development_sample",
            "status": "Gerçek proje verisi değildir",
        }], updated=False,
    ).to_dict()
    catalog["is_sample"] = True
    return catalog


__all__ = [
    "CONFIDENCE_WEIGHTS", "DEFAULT_UI_PREFERENCES", "OVERRIDE_FILENAME", "TECHNICAL_LABELS",
    "add_alternative_link", "add_manual_item", "add_state_profile", "apply_overrides",
    "archive_hardware_item", "attach_datasheets", "build_impact_badges", "build_impact_payload",
    "build_multi_comparison", "build_multi_impact_payload", "catalog_quality_summary",
    "compare_catalogs", "confidence_label",
    "empty_overrides", "filter_cards",
    "load_overrides", "overrides_path", "record_change", "reject_automatic_field", "sample_catalog",
    "normalize_technical_value", "save_overrides", "set_field_override", "set_generated_visuals",
    "undo_last_manual_change", "update_ui_preferences",
]
