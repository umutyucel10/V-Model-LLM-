# -*- coding: utf-8 -*-
"""Gemma ile kanıta bağlı donanım görsel promptu hazırlama katmanı.

Gemma yalnızca metinsel görsel planı üretir. Bu modül hiçbir görüntü dosyası
üretmez ve görsel sağlayıcıya ağ isteği göndermez.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Callable, Mapping

from donanim_kartlari_model import MISSING_VALUE, clean_text, is_missing


PROMPT_SCHEMA_KEYS = (
    "prompt", "negative_prompt", "caption", "known_features_used",
    "unknown_features_omitted", "assumptions", "recommended_view",
)

VISUAL_TYPES = (
    "Nötr katalog görseli",
    "Beyaz arka planlı ürün görünümü",
    "İzometrik kavramsal görünüm",
    "Sistem içindeki konumunu anlatan kavramsal görünüm",
    "Basitleştirilmiş blok diyagram",
    "Patlatılmış kavramsal görünüm",
)

BASE_NEGATIVE_PROMPT = (
    "logo, marka işareti, filigran, okunabilir parça numarası, uydurma ölçü, "
    "uydurma konektör, bilinmeyen bağlantı noktası, üretim teknik çizimi, "
    "ölçülendirilmiş mühendislik çizimi, sertifika işareti, teknik kanıt görünümü"
)


class PromptPreparationError(ValueError):
    pass


@dataclass(slots=True)
class VerifiedHardwareContext:
    fields: dict[str, Any] = field(default_factory=dict)
    field_labels: dict[str, str] = field(default_factory=dict)
    omitted_fields: list[str] = field(default_factory=list)
    evidence_summary: dict[str, str] = field(default_factory=dict)

    @property
    def allowed_feature_labels(self) -> set[str]:
        return set(self.field_labels.values())

    def to_prompt_payload(self) -> dict[str, Any]:
        return dict(self.fields)


@dataclass(slots=True)
class PromptPlan:
    prompt: str
    negative_prompt: str
    caption: str
    known_features_used: list[str]
    unknown_features_omitted: list[str]
    assumptions: list[str]
    recommended_view: str
    preparation_method: str = "Gemma"

    def to_dict(self, *, include_internal: bool = False) -> dict[str, Any]:
        values = asdict(self)
        if not include_internal:
            values.pop("preparation_method", None)
        return values


FIELD_LABELS = {
    "part_name": "Parça adı",
    "hardware_type": "Parça türü",
    "system_role": "Sistem görevi",
    "description": "Teknik bağlam",
    "technical_data.length": "Uzunluk",
    "technical_data.width": "Genişlik",
    "technical_data.height": "Yükseklik",
    "technical_data.diameter": "Çap",
    "technical_data.dimension_unit": "Boyut birimi",
    "technical_data.mechanical_interfaces": "Mekanik bağlantı noktaları",
    "technical_data.electrical_interfaces": "Elektriksel bağlantı noktaları",
    "technical_data.communication_interfaces": "Haberleşme bağlantı noktaları",
}


def _nested(item: Mapping[str, Any], path: str) -> Any:
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _evidence_index(item: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for evidence in item.get("source_evidence", []) or []:
        if not isinstance(evidence, Mapping):
            continue
        field_name = clean_text(evidence.get("field_name"), "")
        if field_name:
            result.setdefault(field_name, []).append(dict(evidence))
    return result


def _is_verified_field(
    item: Mapping[str, Any], field_path: str, evidence: Mapping[str, list[dict[str, Any]]],
) -> tuple[bool, str]:
    manual = set(item.get("manual_fields") or [])
    if item.get("data_origin") == "Manuel" or field_path in manual:
        return True, "Kullanıcı tarafından doğrulanmış manuel alan"
    aliases = {field_path, field_path.removeprefix("technical_data.")}
    for alias in aliases:
        for record in evidence.get(alias, []):
            certainty = clean_text(record.get("certainty"), "").casefold()
            if certainty in {"kesin bilgi", "verified", "doğrulandı", "manual", "manuel"}:
                source = clean_text(record.get("source_document"), "Kaynak belge")
                location = clean_text(record.get("location"), "")
                return True, f"{source}{' · ' + location if location else ''}"
    return False, ""


def build_verified_hardware_context(item: Mapping[str, Any]) -> VerifiedHardwareContext:
    """Yalnızca kesin kanıtlı veya manuel doğrulanmış kart alanlarını döndürür."""
    evidence = _evidence_index(item)
    fields: dict[str, Any] = {}
    labels: dict[str, str] = {}
    omitted: list[str] = []
    sources: dict[str, str] = {}

    for field_path, label in FIELD_LABELS.items():
        value = _nested(item, field_path)
        verified, source = _is_verified_field(item, field_path, evidence)
        if verified and not is_missing(value) and value not in ([], {}):
            fields[field_path] = value
            labels[field_path] = label
            sources[field_path] = source
        else:
            omitted.append(label)

    technical = dict(item.get("technical_data") or {})
    custom = dict(technical.get("custom_parameters") or {})
    for name, value in custom.items():
        folded = clean_text(name).casefold()
        if not any(token in folded for token in ("malzeme", "material", "renk", "color", "colour")):
            continue
        field_path = f"technical_data.custom_parameters.{name}"
        verified, source = _is_verified_field(item, field_path, evidence)
        label = clean_text(name)
        if verified and not is_missing(value):
            fields[field_path] = value; labels[field_path] = label; sources[field_path] = source
        else:
            omitted.append(label)

    # Boyut oranı yalnızca en az iki kesin fiziksel boyut varsa türetilir.
    dimension_paths = [
        path for path in (
            "technical_data.length", "technical_data.width", "technical_data.height",
        ) if path in fields
    ]
    if len(dimension_paths) >= 2:
        values = [fields[path] for path in dimension_paths]
        fields["derived_aspect_ratio"] = " : ".join(clean_text(value) for value in values)
        labels["derived_aspect_ratio"] = "Doğrulanmış boyut oranı"
        sources["derived_aspect_ratio"] = "Doğrulanmış fiziksel boyutlardan türetildi"
    else:
        omitted.append("Boyut oranı")
    # Görsel modeline doğrulanmış olsa bile marka, logo veya okunabilir parça
    # numarası gönderilmez; bunlar kavramsal görsel için gerekli değildir.
    omitted.extend(("Marka veya logo", "Okunabilir parça numarası"))

    return VerifiedHardwareContext(
        fields=fields,
        field_labels=labels,
        omitted_fields=list(dict.fromkeys(omitted)),
        evidence_summary=sources,
    )


def _context_for_gemma(
    verified: VerifiedHardwareContext, options: Mapping[str, Any],
) -> dict[str, Any]:
    values = verified.fields
    physical = {
        verified.field_labels[key]: value for key, value in values.items()
        if key.startswith("technical_data.")
        and not any(token in key for token in ("interfaces", "custom_parameters"))
    }
    material_color = {
        verified.field_labels[key]: value for key, value in values.items()
        if "custom_parameters" in key
    }
    connectors = {
        verified.field_labels[key]: value for key, value in values.items()
        if "interfaces" in key
    }
    return {
        "part_name": values.get("part_name"),
        "part_type": values.get("hardware_type"),
        "system_role": values.get("system_role"),
        "known_physical_features": physical,
        "known_material_and_color": material_color,
        "known_connection_points": connectors,
        "dimension_ratio": values.get("derived_aspect_ratio"),
        "technical_context": values.get("description"),
        "visual_type": clean_text(options.get("visual_type"), VISUAL_TYPES[0]),
        "view": clean_text(options.get("view"), "Önerilen teknik bakış"),
        "background": clean_text(options.get("background"), "Nötr açık arka plan"),
        "user_direction_as_assumption": clean_text(options.get("additional_description"), ""),
        "verified_feature_labels": sorted(verified.allowed_feature_labels),
        "unknown_features_that_must_be_omitted": verified.omitted_fields,
    }


def deterministic_prompt_plan(
    item: Mapping[str, Any], options: Mapping[str, Any] | None = None,
    *, verified_context: VerifiedHardwareContext | None = None,
) -> PromptPlan:
    """LM erişilemezken de yalnızca doğrulanmış alanlarla kopyalanabilir plan üretir."""
    options = dict(options or {})
    verified = verified_context or build_verified_hardware_context(item)
    pieces = [clean_text(options.get("visual_type"), VISUAL_TYPES[0])]
    for field_path in ("part_name", "hardware_type", "system_role", "description"):
        if field_path in verified.fields:
            pieces.append(f"{verified.field_labels[field_path]}: {clean_text(verified.fields[field_path])}")
    physical = [
        f"{verified.field_labels[key]}: {clean_text(value)}"
        for key, value in verified.fields.items() if key.startswith("technical_data.")
    ]
    if physical:
        pieces.append("Doğrulanmış özellikler: " + "; ".join(physical))
    pieces.extend((
        f"Bakış: {clean_text(options.get('view'), 'nötr teknik görünüm')}",
        f"Arka plan: {clean_text(options.get('background'), 'açık nötr yüzey')}",
        "Yalnızca listelenen doğrulanmış özellikleri göster; bilinmeyen ayrıntıları sade ve tanımsız bırak.",
        "Bu bir kavramsal görseldir; teknik çizim, üretim kanıtı veya teknik doğrulama amacıyla kullanılamaz.",
    ))
    assumptions: list[str] = []
    additional = clean_text(options.get("additional_description"), "")
    if additional:
        pieces.append(f"Kullanıcı yönlendirmesi (doğrulanmamış): {additional}")
        assumptions.append(additional)
    return PromptPlan(
        prompt=". ".join(piece.rstrip(". ") for piece in pieces if piece) + ".",
        negative_prompt=BASE_NEGATIVE_PROMPT,
        caption=f"{clean_text(verified.fields.get('part_name'), 'Donanım bileşeni')} için AI kavramsal görsel",
        known_features_used=sorted(verified.allowed_feature_labels),
        unknown_features_omitted=list(verified.omitted_fields),
        assumptions=assumptions,
        recommended_view=clean_text(options.get("view"), "Nötr teknik görünüm"),
        preparation_method="Deterministik güvenli yedek",
    )


def _extract_json(text: str) -> Mapping[str, Any]:
    candidate = clean_text(text, "")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start:end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise PromptPreparationError("Gemma geçerli prompt JSON'u döndürmedi.") from error
    if not isinstance(payload, Mapping):
        raise PromptPreparationError("Gemma prompt yanıtı JSON nesnesi olmalıdır.")
    return payload


def validate_prompt_payload(
    payload: Mapping[str, Any], verified: VerifiedHardwareContext,
) -> PromptPlan:
    missing = [key for key in PROMPT_SCHEMA_KEYS if key not in payload]
    if missing:
        raise PromptPreparationError("Gemma prompt JSON'unda zorunlu alanlar eksik: " + ", ".join(missing))
    prompt = clean_text(payload.get("prompt"), "")
    if not prompt:
        raise PromptPreparationError("Gemma boş bir görsel promptu döndürdü.")
    known_raw = payload.get("known_features_used")
    omitted_raw = payload.get("unknown_features_omitted")
    assumptions_raw = payload.get("assumptions")
    if not all(isinstance(value, list) for value in (known_raw, omitted_raw, assumptions_raw)):
        raise PromptPreparationError("Gemma prompt JSON liste alanları geçersiz.")
    allowed = verified.allowed_feature_labels
    known = [clean_text(value) for value in known_raw if clean_text(value) in allowed]
    omitted = list(dict.fromkeys([
        *verified.omitted_fields,
        *(clean_text(value) for value in omitted_raw if clean_text(value)),
    ]))
    negative = clean_text(payload.get("negative_prompt"), "")
    for phrase in BASE_NEGATIVE_PROMPT.split(", "):
        if phrase.casefold() not in negative.casefold():
            negative = f"{negative}, {phrase}".strip(", ")

    # Kartta doğrulanmış bağlantı yoksa konektör ayrıntısı yazan prompt reddedilir.
    has_verified_connector = any("bağlantı noktaları" in value.casefold() for value in allowed)
    if not has_verified_connector and re.search(r"\b(connector|konnektör|konektör|port)\b", prompt, re.IGNORECASE):
        raise PromptPreparationError("Gemma bilinmeyen bir bağlantı noktası eklemeye çalıştı.")
    return PromptPlan(
        prompt=prompt,
        negative_prompt=negative,
        caption=clean_text(payload.get("caption"), "AI kavramsal donanım görseli"),
        known_features_used=list(dict.fromkeys(known)),
        unknown_features_omitted=omitted,
        assumptions=list(dict.fromkeys(clean_text(value) for value in assumptions_raw if clean_text(value))),
        recommended_view=clean_text(payload.get("recommended_view"), "Nötr teknik görünüm"),
        preparation_method="Gemma",
    )


def prepare_prompt_with_gemma(
    item: Mapping[str, Any],
    options: Mapping[str, Any] | None = None,
    *,
    llm_callable: Callable[..., str | None] | None = None,
    allow_fallback: bool = True,
) -> PromptPlan:
    """Gemma'dan katı JSON alır; başarısızlıkta güvenli planı döndürebilir."""
    options = dict(options or {})
    verified = build_verified_hardware_context(item)
    fallback = deterministic_prompt_plan(item, options, verified_context=verified)
    if llm_callable is None:
        try:
            from llm_handler import call_gemma3_api
            llm_callable = call_gemma3_api
        except Exception:
            llm_callable = None
    if llm_callable is None:
        if allow_fallback:
            return fallback
        raise PromptPreparationError("Gemma prompt hazırlama hizmeti kullanılamıyor.")
    context_payload = _context_for_gemma(verified, options)
    system_message = (
        "Sen bir donanım görseli üretmiyorsun; ayrı bir görüntü modeli için güvenli metinsel plan hazırlıyorsun. "
        "Yalnızca VERİFİYE_KART_ALANLARI içindeki değerleri teknik gerçek olarak kullan. "
        "Bilinmeyen marka, logo, konektör, parça numarası veya ölçü ekleme. "
        "Görseli teknik kanıt, üretim çizimi ya da ölçülendirilmiş çizim olarak sunma. "
        "Yanıt yalnızca istenen yedi anahtarlı geçerli JSON olsun."
    )
    user_prompt = (
        "VERİFİYE_KART_ALANLARI:\n" + json.dumps(context_payload, ensure_ascii=False, indent=2) +
        "\n\nŞu yapıda JSON üret:\n" + json.dumps({key: [] if key in {"known_features_used", "unknown_features_omitted", "assumptions"} else "" for key in PROMPT_SCHEMA_KEYS}, ensure_ascii=False)
    )
    try:
        try:
            response = llm_callable(
                user_prompt, max_tokens=1400, temperature=0.15, system_message=system_message,
            )
        except TypeError:
            response = llm_callable(user_prompt)
        if not response:
            raise PromptPreparationError("Gemma prompt yanıtı boş döndü.")
        return validate_prompt_payload(_extract_json(str(response)), verified)
    except Exception:
        if allow_fallback:
            return fallback
        raise


__all__ = [
    "BASE_NEGATIVE_PROMPT", "PROMPT_SCHEMA_KEYS", "PromptPlan",
    "PromptPreparationError", "VerifiedHardwareContext", "VISUAL_TYPES",
    "build_verified_hardware_context", "deterministic_prompt_plan",
    "prepare_prompt_with_gemma", "validate_prompt_payload",
]
