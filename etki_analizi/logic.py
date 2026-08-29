# -*- coding: utf-8 -*-
"""Etki Analizi hesaplama kuralları.

Bu modül arayüzden bağımsızdır. Arayüz yalnızca kullanıcı verisini sözlük
olarak iletir; ağırlık normalizasyonu, uygunluk puanı, kabul sınırı kontrolü,
fark hesabı ve kazanan seçimi burada yapılır.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence


STATUS_SUITABLE = "Uygun"
STATUS_UNSUITABLE = "Uygun değil"
STATUS_MISSING = "Veri eksik"

DIRECTION_HIGH = "Yüksek daha iyi"
DIRECTION_LOW = "Düşük daha iyi"
DIRECTIONS = (DIRECTION_HIGH, DIRECTION_LOW)


class EtkiAnaliziHatasi(ValueError):
    """Kullanıcıya gösterilebilecek Türkçe doğrulama hatası."""


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _parse_number(
    value: Any,
    field_name: str,
    *,
    allow_missing: bool = True,
) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_missing:
            return None
        raise EtkiAnaliziHatasi(f"'{field_name}' alanı boş bırakılamaz.")

    if isinstance(value, bool):
        raise EtkiAnaliziHatasi(
            f"'{field_name}' için geçerli bir sayısal değer girin."
        )

    try:
        if isinstance(value, str):
            normalized = value.strip().replace(" ", "").replace(",", ".")
            number = float(normalized)
        else:
            number = float(value)
    except (TypeError, ValueError):
        raise EtkiAnaliziHatasi(
            f"'{field_name}' için geçerli bir sayısal değer girin."
        ) from None

    if not isfinite(number):
        raise EtkiAnaliziHatasi(
            f"'{field_name}' için sonlu bir sayısal değer girin."
        )
    return number


def _normalize_direction(value: Any, parameter_name: str = "") -> str:
    normalized = _clean_text(value).casefold()
    high_values = {
        "yüksek daha iyi",
        "yuksek daha iyi",
        "yüksek",
        "yuksek",
        "high",
        "higher is better",
        "maximize",
        "maksimum",
    }
    low_values = {
        "düşük daha iyi",
        "dusuk daha iyi",
        "düşük",
        "dusuk",
        "low",
        "lower is better",
        "minimize",
        "minimum",
    }
    if normalized in high_values:
        return DIRECTION_HIGH
    if normalized in low_values:
        return DIRECTION_LOW

    suffix = f" ({parameter_name})" if parameter_name else ""
    raise EtkiAnaliziHatasi(
        "Değer yönü 'Yüksek daha iyi' veya 'Düşük daha iyi' olmalıdır"
        f"{suffix}."
    )


def _parse_required_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {
            "1",
            "true",
            "evet",
            "yes",
            "zorunlu",
        }
    return bool(value)


def normalize_weights(parameters: Sequence[Mapping[str, Any]]) -> list[float]:
    """Önem ağırlıklarını toplamı tam olarak 100 olacak biçimde normalize eder."""
    if not parameters:
        raise EtkiAnaliziHatasi("En az bir karşılaştırma parametresi ekleyin.")

    weights: list[float] = []
    for index, parameter in enumerate(parameters, start=1):
        name = _clean_text(
            _first(parameter, "name", "parameter_name", "parametre_adi")
        ) or f"Parametre {index}"
        raw_weight = _first(
            parameter,
            "weight",
            "importance_weight",
            "onem_agirligi",
        )
        weight = _parse_number(
            raw_weight,
            f"{name} önem ağırlığı",
            allow_missing=False,
        )
        assert weight is not None
        if weight < 0:
            raise EtkiAnaliziHatasi(
                f"'{name}' önem ağırlığı negatif olamaz."
            )
        weights.append(weight)

    total = sum(weights)
    if total <= 0:
        raise EtkiAnaliziHatasi(
            "Önem ağırlıklarının toplamı sıfırdan büyük olmalıdır."
        )
    return [(weight / total) * 100.0 for weight in weights]


def score_value(
    value: Any,
    minimum: Any,
    maximum: Any,
    direction: Any,
    *,
    parameter_name: str = "",
) -> float | None:
    """Bir değeri kabul aralığı içinde 0–100 ölçeğine dönüştürür.

    Değer veya kabul sınırlarından biri boşsa ``None`` döner. Böylece eksik
    veri hiçbir aşamada sıfırmış gibi değerlendirilmez.
    """
    label = parameter_name or "Parametre"
    numeric_value = _parse_number(value, f"{label} değeri")
    numeric_minimum = _parse_number(minimum, f"{label} minimum sınırı")
    numeric_maximum = _parse_number(maximum, f"{label} maksimum sınırı")
    normalized_direction = _normalize_direction(direction, parameter_name)

    if (
        numeric_value is None
        or numeric_minimum is None
        or numeric_maximum is None
    ):
        return None
    if numeric_minimum > numeric_maximum:
        raise EtkiAnaliziHatasi(
            f"'{label}' için minimum sınır maksimum sınırdan büyük olamaz."
        )
    if numeric_minimum == numeric_maximum:
        return 100.0 if numeric_value == numeric_minimum else 0.0

    if normalized_direction == DIRECTION_HIGH:
        score = (
            (numeric_value - numeric_minimum)
            / (numeric_maximum - numeric_minimum)
            * 100.0
        )
    else:
        score = (
            (numeric_maximum - numeric_value)
            / (numeric_maximum - numeric_minimum)
            * 100.0
        )
    return round(max(0.0, min(100.0, score)), 4)


def calculate_difference(
    current_value: Any,
    alternative_value: Any,
    *,
    parameter_name: str = "",
) -> dict[str, float | None]:
    """Alternatif ile mevcut değer arasındaki mutlak ve yüzdesel farkı verir."""
    label = parameter_name or "Parametre"
    current = _parse_number(current_value, f"{label} mevcut değeri")
    alternative = _parse_number(
        alternative_value,
        f"{label} alternatif değeri",
    )
    if current is None or alternative is None:
        return {"difference": None, "difference_percent": None}

    difference = alternative - current
    percent = None if current == 0 else (difference / abs(current)) * 100.0
    return {
        "difference": round(difference, 4),
        "difference_percent": (
            None if percent is None else round(percent, 4)
        ),
    }


def _extract_alternative_names(raw_alternatives: Any) -> list[str]:
    if not isinstance(raw_alternatives, Sequence) or isinstance(
        raw_alternatives, (str, bytes)
    ):
        raise EtkiAnaliziHatasi("Alternatifler liste biçiminde olmalıdır.")

    names: list[str] = []
    seen: set[str] = set()
    for raw in raw_alternatives:
        if isinstance(raw, Mapping):
            name = _clean_text(
                _first(raw, "name", "alternative_name", "alternatif_adi")
            )
        else:
            name = _clean_text(raw)
        if not name:
            raise EtkiAnaliziHatasi("Alternatif adı boş bırakılamaz.")
        folded = name.casefold()
        if folded in seen:
            raise EtkiAnaliziHatasi(
                f"'{name}' alternatif adı birden fazla kez kullanılmış."
            )
        seen.add(folded)
        names.append(name)

    if not names:
        raise EtkiAnaliziHatasi("En az bir alternatif ekleyin.")
    return names


def _validate_context(data: Mapping[str, Any]) -> tuple[str, str, str]:
    analysis_name = _clean_text(
        _first(data, "analysis_name", "name", "analiz_adi")
    )
    current_state = _clean_text(
        _first(data, "current_state", "current", "mevcut_durum")
    )
    change_reason = _clean_text(
        _first(data, "change_reason", "reason", "degisiklik_nedeni")
    )

    missing: list[str] = []
    if not analysis_name:
        missing.append("Analiz adı")
    if not current_state:
        missing.append("Mevcut parça veya durum")
    if not change_reason:
        missing.append("Değişiklik nedeni")
    if missing:
        raise EtkiAnaliziHatasi(
            "Şu alanları doldurun: " + ", ".join(missing) + "."
        )
    return analysis_name, current_state, change_reason


def calculate_impact_analysis(data: Mapping[str, Any]) -> dict[str, Any]:
    """Etki analizini hesaplar ve arayüzde gösterilecek yapılandırılmış sonucu döndürür."""
    if not isinstance(data, Mapping):
        raise EtkiAnaliziHatasi("Etki analizi verisi geçerli değil.")

    analysis_name, current_state, change_reason = _validate_context(data)
    alternative_names = _extract_alternative_names(
        _first(data, "alternatives", "alternatifler", default=[])
    )
    raw_parameters = _first(
        data,
        "parameters",
        "parametreler",
        default=[],
    )
    if not isinstance(raw_parameters, Sequence) or isinstance(
        raw_parameters, (str, bytes)
    ):
        raise EtkiAnaliziHatasi("Parametreler liste biçiminde olmalıdır.")
    if not raw_parameters:
        raise EtkiAnaliziHatasi("En az bir karşılaştırma parametresi ekleyin.")
    if not all(isinstance(item, Mapping) for item in raw_parameters):
        raise EtkiAnaliziHatasi("Parametre kayıtlarından biri geçerli değil.")

    parameters = list(raw_parameters)
    normalized_weights = normalize_weights(parameters)

    parameter_names: list[str] = []
    seen_parameters: set[str] = set()
    for index, parameter in enumerate(parameters, start=1):
        name = _clean_text(
            _first(parameter, "name", "parameter_name", "parametre_adi")
        )
        if not name:
            raise EtkiAnaliziHatasi(
                f"{index}. parametrenin adını girin."
            )
        folded = name.casefold()
        if folded in seen_parameters:
            raise EtkiAnaliziHatasi(
                f"'{name}' parametre adı birden fazla kez kullanılmış."
            )
        seen_parameters.add(folded)
        parameter_names.append(name)

    results: list[dict[str, Any]] = []
    for alternative_name in alternative_names:
        criteria: list[dict[str, Any]] = []
        weighted_total = 0.0
        has_missing_data = False
        mandatory_failed = False

        for index, parameter in enumerate(parameters):
            parameter_name = parameter_names[index]
            unit = _clean_text(_first(parameter, "unit", "birim"))
            current_raw = _first(
                parameter,
                "current_value",
                "mevcut_deger",
            )
            alternative_values = _first(
                parameter,
                "alternative_values",
                "alternatif_degerler",
                default={},
            )
            if not isinstance(alternative_values, Mapping):
                raise EtkiAnaliziHatasi(
                    f"'{parameter_name}' alternatif değerleri geçerli değil."
                )
            alternative_raw = alternative_values.get(alternative_name)
            minimum_raw = _first(
                parameter,
                "minimum",
                "min",
                "minimum_sinir",
            )
            maximum_raw = _first(
                parameter,
                "maximum",
                "max",
                "maksimum_sinir",
            )
            direction = _normalize_direction(
                _first(parameter, "direction", "deger_yonu"),
                parameter_name,
            )
            mandatory = _parse_required_flag(
                _first(
                    parameter,
                    "mandatory",
                    "required",
                    "zorunlu",
                    default=False,
                )
            )

            current = _parse_number(
                current_raw,
                f"{parameter_name} mevcut değeri",
            )
            alternative = _parse_number(
                alternative_raw,
                f"{parameter_name} / {alternative_name} değeri",
            )
            minimum = _parse_number(
                minimum_raw,
                f"{parameter_name} minimum sınırı",
            )
            maximum = _parse_number(
                maximum_raw,
                f"{parameter_name} maksimum sınırı",
            )
            if (
                minimum is not None
                and maximum is not None
                and minimum > maximum
            ):
                raise EtkiAnaliziHatasi(
                    f"'{parameter_name}' için minimum sınır maksimum "
                    "sınırdan büyük olamaz."
                )

            criterion_missing = any(
                value is None
                for value in (current, alternative, minimum, maximum)
            )
            if criterion_missing:
                criterion_score = None
                difference = {
                    "difference": None,
                    "difference_percent": None,
                }
                within_limits = None
                criterion_status = STATUS_MISSING
                has_missing_data = True
            else:
                criterion_score = score_value(
                    alternative,
                    minimum,
                    maximum,
                    direction,
                    parameter_name=parameter_name,
                )
                difference = calculate_difference(
                    current,
                    alternative,
                    parameter_name=parameter_name,
                )
                assert minimum is not None and maximum is not None
                assert alternative is not None
                within_limits = minimum <= alternative <= maximum
                if mandatory and not within_limits:
                    criterion_status = "Zorunlu kriter sağlanmadı"
                    mandatory_failed = True
                elif not within_limits:
                    criterion_status = "Kabul sınırı dışında"
                else:
                    criterion_status = STATUS_SUITABLE

                assert criterion_score is not None
                weighted_total += (
                    criterion_score * normalized_weights[index] / 100.0
                )

            criteria.append({
                "parameter_name": parameter_name,
                "current_value": current,
                "alternative_value": alternative,
                "unit": unit,
                "direction": direction,
                "minimum": minimum,
                "maximum": maximum,
                "mandatory": mandatory,
                "normalized_weight": round(normalized_weights[index], 4),
                "criterion_score": (
                    None
                    if criterion_score is None
                    else round(criterion_score, 2)
                ),
                "within_limits": within_limits,
                "status": criterion_status,
                **difference,
            })

        if has_missing_data:
            status = STATUS_MISSING
            total_score = None
        elif mandatory_failed:
            status = STATUS_UNSUITABLE
            total_score = round(weighted_total, 2)
        else:
            status = STATUS_SUITABLE
            total_score = round(weighted_total, 2)

        results.append({
            "alternative_name": alternative_name,
            "total_score": total_score,
            "status": status,
            "is_suitable": status == STATUS_SUITABLE,
            "has_missing_data": has_missing_data,
            "mandatory_failed": mandatory_failed,
            "criteria": criteria,
        })

    suitable_results = [
        result
        for result in results
        if result["status"] == STATUS_SUITABLE
        and result["total_score"] is not None
    ]
    best = (
        max(
            suitable_results,
            key=lambda item: (
                item["total_score"],
                item["alternative_name"].casefold(),
            ),
        )
        if suitable_results
        else None
    )

    return {
        "analysis_name": analysis_name,
        "current_state": current_state,
        "change_reason": change_reason,
        "normalized_weights": {
            name: round(normalized_weights[index], 4)
            for index, name in enumerate(parameter_names)
        },
        "alternatives": results,
        "best_alternative": (
            None
            if best is None
            else {
                "alternative_name": best["alternative_name"],
                "total_score": best["total_score"],
            }
        ),
        "calculation_explanation": [
            "Girilen önem ağırlıkları oransal olarak %100'e normalize edildi.",
            (
                "Her parametre, kabul sınırları arasında değer yönüne göre "
                "0–100 puana dönüştürüldü."
            ),
            (
                "Toplam puan, parametre puanlarının normalize ağırlıklarla "
                "çarpılıp toplanmasıyla hesaplandı."
            ),
            (
                "Zorunlu bir kriter kabul sınırının dışındaysa alternatif "
                "'Uygun değil' olarak işaretlendi."
            ),
            (
                "Boş bırakılan sayısal değerler sıfır kabul edilmedi; ilgili "
                "alternatif 'Veri eksik' olarak gösterildi."
            ),
            (
                "Fark, alternatif değer eksi mevcut değer olarak; mevcut "
                "değer sıfır değilse yüzdesel fark ayrıca hesaplandı."
            ),
        ],
    }


# Türkçe çağrı adı; dış entegrasyonlarda iki ad da aynı davranışı verir.
etki_analizi_hesapla = calculate_impact_analysis

