# -*- coding: utf-8 -*-
"""AI donanım görsellerinin güvenli dosya, galeri ve toplu işlem servisi."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable, Iterable, Mapping
import uuid

from hardware_image_provider import (
    GeneratedImage, ImageGenerationCancelled, ImageGenerationProvider,
    ImageProviderError, validate_image_bytes, validate_image_file,
)
from donanim_kartlari_model import PLACEHOLDER_IMAGE, clean_text


AI_CONCEPT_WARNING = (
    "Yapay zekâ tarafından oluşturulmuş kavramsal görseldir. "
    "Teknik doğrulama amacıyla kullanılamaz."
)
AI_IMAGE_FOLDER = "ai_gorselleri"

SOURCE_PRIORITIES = {
    "verified_user_photo": 500,
    "datasheet_image": 400,
    "technical_document_image": 300,
    "ai_concept": 200,
    "placeholder": 0,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def image_source_priority(record: Mapping[str, Any] | None) -> int:
    record = dict(record or {})
    source_kind = clean_text(record.get("source_kind"), "").casefold()
    source_type = clean_text(record.get("source_type"), "").casefold()
    is_ai = bool(record.get("is_ai"))
    if source_kind in SOURCE_PRIORITIES:
        return SOURCE_PRIORITIES[source_kind]
    if is_ai or "ai" in source_type or "yapay zek" in source_type:
        return SOURCE_PRIORITIES["ai_concept"]
    if "datasheet" in source_type:
        return SOURCE_PRIORITIES["datasheet_image"]
    if "belge" in source_type or "doküman" in source_type:
        return SOURCE_PRIORITIES["technical_document_image"]
    if clean_text(record.get("path")):
        return SOURCE_PRIORITIES["verified_user_photo"]
    return SOURCE_PRIORITIES["placeholder"]


def has_real_image(item: Mapping[str, Any]) -> bool:
    """Kartta gerçek/datasheet/belge görseli varsa AI toplu üretiminden korur."""
    path = clean_text(item.get("image_path"), "")
    if (
        path and path != PLACEHOLDER_IMAGE and Path(path).is_file()
        and not bool(item.get("image_is_generated"))
    ):
        return True
    for record in item.get("gallery_images", []) or []:
        if not isinstance(record, Mapping) or bool(record.get("is_ai")):
            continue
        candidate = clean_text(record.get("path"), "")
        if candidate and Path(candidate).is_file():
            return True
    return False


def has_any_image(item: Mapping[str, Any]) -> bool:
    """Gerçek veya kabul edilmiş kavramsal herhangi bir geçerli görsel var mı?"""
    path = clean_text(item.get("image_path"), "")
    if path and path != PLACEHOLDER_IMAGE and Path(path).is_file():
        return True
    return any(
        isinstance(record, Mapping)
        and clean_text(record.get("path"), "")
        and Path(clean_text(record.get("path"))).is_file()
        for record in item.get("gallery_images", []) or []
    )


def _safe_hardware_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", clean_text(value, "donanim")).strip("-")[:80] or "donanim"


def _extension(media_type: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(media_type, ".png")


def write_preview_file(result: GeneratedImage) -> Path:
    media_type, _size = validate_image_bytes(result.image_bytes)
    root = Path(tempfile.mkdtemp(prefix="ehsim-ai-preview-"))
    target = root / f"preview{_extension(media_type)}"
    target.write_bytes(result.image_bytes)
    validate_image_file(target)
    return target


def discard_preview_file(path: str | Path | None) -> None:
    """Yalnızca bu uygulamanın açıkça oluşturduğu önizleme alanını temizler."""
    if not path:
        return
    candidate = Path(path).resolve()
    parent = candidate.parent
    if not parent.name.startswith("ehsim-ai-preview-"):
        return
    try:
        if candidate.is_file():
            candidate.unlink()
        parent.rmdir()
    except OSError:
        pass


def store_generated_image(
    result: GeneratedImage,
    output_root: str | Path,
    hardware_id: str,
    *,
    prompt: str,
    negative_prompt: str,
    caption: str,
    card_version: str,
    verified_fields: Iterable[str],
    generation_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Doğrulanmış AI görselini benzersiz adla atomik olarak kalıcılaştırır."""
    media_type, dimensions = validate_image_bytes(result.image_bytes)
    root = Path(output_root).resolve() / AI_IMAGE_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(result.image_bytes).hexdigest()[:12]
    filename = f"{_safe_hardware_id(hardware_id)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{digest}-{uuid.uuid4().hex[:6]}{_extension(media_type)}"
    target = root / filename
    temporary = root / f".{filename}.tmp"
    try:
        temporary.write_bytes(result.image_bytes)
        validate_image_file(temporary)
        temporary.replace(target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    options = dict(generation_options or {})
    return {
        "path": str(target),
        "source_kind": "ai_concept",
        "source_type": "AI kavramsal görsel",
        "source_document": "Kullanıcı onaylı AI görsel üretimi",
        "created_at": now_iso(),
        "is_ai": True,
        "is_cover": False,
        "description": clean_text(caption, "AI kavramsal donanım görseli"),
        "warning": AI_CONCEPT_WARNING,
        "provider": clean_text(result.provider, "Bilinmeyen sağlayıcı"),
        "model": clean_text(result.model, "Bilinmeyen model"),
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": result.seed,
        "source_card_version": clean_text(card_version, "Veri bulunamadı"),
        "verified_fields_used": list(dict.fromkeys(clean_text(value) for value in verified_fields if clean_text(value))),
        "dimensions": list(dimensions),
        "media_type": media_type,
        "generation_options": options,
        "provider_metadata": dict(result.metadata or {}),
        "accepted_by_user": True,
    }


@dataclass(slots=True)
class BatchGenerationResult:
    generated: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped_real_images: list[str] = field(default_factory=list)
    skipped_existing_images: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    cancelled: bool = False


def generate_batch(
    items: Iterable[Mapping[str, Any]],
    provider: ImageGenerationProvider,
    prompt_builder: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    output_root: str | Path,
    *,
    options: Mapping[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> BatchGenerationResult:
    """Gerçek görselleri atlayan, kart hatalarında devam eden toplu servis."""
    values = [dict(item) for item in items]
    result = BatchGenerationResult()
    total = len(values)
    for index, item in enumerate(values, 1):
        hardware_id = clean_text(item.get("hardware_id"), f"donanim-{index}")
        if cancel_event and cancel_event.is_set():
            provider.cancel_generation(); result.cancelled = True; break
        if has_real_image(item):
            result.skipped_real_images.append(hardware_id)
            if progress_callback:
                progress_callback(index, total, hardware_id)
            continue
        if has_any_image(item):
            result.skipped_existing_images.append(hardware_id)
            if progress_callback:
                progress_callback(index, total, hardware_id)
            continue
        try:
            plan = dict(prompt_builder(item))
            generated = provider.generate_image(
                clean_text(plan.get("prompt")), clean_text(plan.get("negative_prompt")), options,
            )
            if cancel_event and cancel_event.is_set():
                provider.cancel_generation()
                result.cancelled = True
                break
            record = store_generated_image(
                generated, output_root, hardware_id,
                prompt=clean_text(plan.get("prompt")),
                negative_prompt=clean_text(plan.get("negative_prompt")),
                caption=clean_text(plan.get("caption")),
                card_version=clean_text(item.get("version")),
                verified_fields=plan.get("known_features_used", []),
                generation_options=options,
            )
            result.generated[hardware_id] = record
        except ImageGenerationCancelled:
            result.cancelled = True; break
        except Exception as error:
            result.failed[hardware_id] = str(error)[:280]
        if progress_callback:
            progress_callback(index, total, hardware_id)
    return result


__all__ = [
    "AI_CONCEPT_WARNING", "AI_IMAGE_FOLDER", "BatchGenerationResult",
    "SOURCE_PRIORITIES", "discard_preview_file", "generate_batch",
    "has_any_image", "has_real_image", "image_source_priority", "store_generated_image",
    "write_preview_file",
]
