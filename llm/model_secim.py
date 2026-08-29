# -*- coding: utf-8 -*-
"""LM Studio'daki gerçek model kimliğini güvenli ve açıklanabilir biçimde seçer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import time
from typing import Any, Callable, Mapping, Sequence

import requests

from config import LMSTUDIO_API_KEY, LMSTUDIO_BASE_URL, MODEL_NAME


class ModelSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelProbeResult:
    ready: bool
    requested_model: str
    resolved_model: str
    loaded_models: tuple[str, ...]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_SECONDS = 15.0


def normalize_model_id(value: Any) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _is_gemma4_e4b(value: str) -> bool:
    normalized = normalize_model_id(value)
    return all(token in normalized.split("-") for token in ("gemma", "4", "e4b"))


def is_gemma4_e4b_model(value: str) -> bool:
    """LM Studio kimliğinin Gemma 4 E4B ailesine ait olup olmadığını döndürür."""
    return _is_gemma4_e4b(value)


def _is_gemma3_4b(value: str) -> bool:
    normalized = normalize_model_id(value)
    return all(token in normalized.split("-") for token in ("gemma", "3", "4b"))


def _resolve_family(
    loaded: Sequence[str], matcher: Callable[[str], bool], family_name: str,
) -> str | None:
    candidates = [item for item in loaded if matcher(item)]
    instruction_candidates = [
        item for item in candidates
        if any(token in normalize_model_id(item).split("-") for token in ("it", "instruct"))
    ]
    if len(instruction_candidates) == 1:
        return instruction_candidates[0]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ModelSelectionError(
            f"LM Studio'da birden fazla {family_name} bulundu: "
            + ", ".join(candidates)
            + ". Kullanılacak model kimliğini EHSIM_LM_MODEL ile kesin olarak belirtin."
        )
    return None


def loaded_model_ids(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    values: list[str] = []
    for item in (payload or {}).get("data", []) or []:
        if isinstance(item, Mapping):
            model_id = str(item.get("id") or "").strip()
            if model_id and model_id not in values:
                values.append(model_id)
    return tuple(values)


def resolve_model_id(requested_model: str, loaded_models: Sequence[str]) -> str:
    """İstenen modeli kesin/normalize eşleşmeyle bulur; başka modele düşmez."""
    requested = str(requested_model or "").strip()
    loaded = tuple(str(item).strip() for item in loaded_models if str(item).strip())
    if requested in loaded:
        return requested
    normalized_requested = normalize_model_id(requested)
    normalized_matches = [
        item for item in loaded if normalize_model_id(item) == normalized_requested
    ]
    if len(normalized_matches) == 1:
        return normalized_matches[0]

    if _is_gemma4_e4b(requested):
        resolved = _resolve_family(loaded, _is_gemma4_e4b, "Gemma 4 E4B")
        if resolved:
            return resolved
    elif _is_gemma3_4b(requested):
        resolved = _resolve_family(loaded, _is_gemma3_4b, "Gemma 3 4B")
        if resolved:
            return resolved

    loaded_text = ", ".join(loaded) if loaded else "model bulunamadı"
    raise ModelSelectionError(
        f"İstenen model LM Studio'da yüklü değil: {requested}. "
        f"Yüklü modeller: {loaded_text}. {requested} modelini yükleyip sunucuyu başlatın."
    )


def list_loaded_models(
    request_get: Callable[..., Any] = requests.get,
    timeout: float = 4.0,
) -> tuple[str, ...]:
    response = request_get(
        f"{LMSTUDIO_BASE_URL.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {LMSTUDIO_API_KEY}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return loaded_model_ids(response.json())


def get_active_model_name(
    requested_model: str | None = None,
    force_refresh: bool = False,
    request_get: Callable[..., Any] = requests.get,
) -> str:
    requested = str(requested_model or MODEL_NAME).strip()
    cached = _CACHE.get(requested)
    now = time.monotonic()
    if cached and not force_refresh and now - cached[0] <= _CACHE_SECONDS:
        return cached[1]
    loaded = list_loaded_models(request_get=request_get)
    resolved = resolve_model_id(requested, loaded)
    _CACHE[requested] = (now, resolved)
    return resolved


def probe_model(
    requested_model: str | None = None,
    request_get: Callable[..., Any] = requests.get,
) -> ModelProbeResult:
    requested = str(requested_model or MODEL_NAME).strip()
    try:
        loaded = list_loaded_models(request_get=request_get)
        resolved = resolve_model_id(requested, loaded)
        return ModelProbeResult(
            True, requested, resolved, loaded,
            f"Model hazır: {resolved}",
        )
    except ModelSelectionError as error:
        return ModelProbeResult(False, requested, "", tuple(locals().get("loaded", ())), str(error))
    except requests.RequestException as error:
        return ModelProbeResult(
            False, requested, "", (),
            f"LM Studio sunucusuna bağlanılamadı: {error}",
        )
    except Exception as error:
        return ModelProbeResult(False, requested, "", (), f"Model denetimi başarısız: {error}")


__all__ = [
    "ModelProbeResult", "ModelSelectionError", "get_active_model_name",
    "is_gemma4_e4b_model",
    "list_loaded_models", "loaded_model_ids", "normalize_model_id",
    "probe_model", "resolve_model_id",
]
