# -*- coding: utf-8 -*-
"""Donanım kartları için kanıt metni temelli teknik illüstrasyonlar.

Bu modül gerçek ürün veya datasheet fotoğrafı üretmez. Belge taraması ve
LLM çıkarımından gelen parça adı, görev ve açıklamayı sınıflandırıp kartta
ayırt edilebilir bir teknik silüete dönüştürür. Üretilen her görselin kaynağı
bu nedenle açıkça ``AI içerik temelli teknik illüstrasyon`` olarak saklanır.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - uygulama Pillow olmadan yer tutucu kullanır.
    Image = ImageDraw = ImageFont = None

from donanim_kartlari_model import MISSING_VALUE, PLACEHOLDER_IMAGE, clean_text, is_missing


VISUAL_SCHEMA_VERSION = "1.0"
ILLUSTRATION_SOURCE = (
    "AI içerik temelli teknik illüstrasyon (gerçek ürün fotoğrafı değildir)"
)


@dataclass(frozen=True, slots=True)
class VisualBrief:
    family: str
    label: str
    source_summary: str
    confidence: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FAMILY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("brake_pad", "Disk fren balatası", ("balata", "brake pad", "disk fren")),
    ("brake_shoe", "Fren pabucu", ("pabuç", "pabuc", "brake shoe", "kampana")),
    ("brake_disc", "Fren diski", ("fren diski", "brake disc", "rotor")),
    ("abs_unit", "ABS / fren kontrol ünitesi", ("abs", "fren kontrol", "kontrol ünitesi")),
    ("actuator", "Tahrik mekanizması", ("tahrik", "aktüatör", "actuator", "servo", "motor")),
    ("instrument", "Ölçüm cihazı", ("ölçüm cihaz", "gösterge", "manometre", "ölçer", "meter")),
    ("sensor", "Sensör", ("sensör", "sensor", "algılayıcı", "transdüser")),
    ("power_module", "Güç modülü", ("dönüştürücü", "dc/dc", "güç dağıtım", "power module")),
    ("circuit_board", "Elektronik kart", ("işlemci", "bellek", "elektronik kart", "pcb", "mikrodenetleyici")),
    ("interface", "Arayüz / bağlantı bileşeni", ("konnektör", "konektör", "arayüz", "interface", "kablo")),
)


def _source_text(item: Mapping[str, Any]) -> str:
    fields: list[Any] = [
        item.get("part_name"), item.get("hardware_type"), item.get("description"),
        item.get("system_role"), item.get("model_series"),
    ]
    for evidence in item.get("source_evidence", []) or []:
        if isinstance(evidence, Mapping):
            fields.append(evidence.get("evidence_text"))
    return " ".join(clean_text(value, "") for value in fields if not is_missing(value)).casefold()


def build_visual_brief(item: Mapping[str, Any]) -> VisualBrief:
    """Belge/AI içeriğini deterministik biçimde bir görsel ailesine eşler."""
    text = _source_text(item)
    best_family = "mechanical_component"
    best_label = "Mekanik bileşen"
    best_score = 0
    for family, label, keywords in _FAMILY_RULES:
        score = sum(3 if keyword in clean_text(item.get("part_name"), "").casefold() else 1 for keyword in keywords if keyword in text)
        if score > best_score:
            best_family, best_label, best_score = family, label, score
    confidence = min(96, 42 + best_score * 14) if best_score else 35
    source_summary = clean_text(item.get("system_role"), "")
    if not source_summary:
        source_summary = clean_text(item.get("description"), "")
    if not source_summary:
        source_summary = clean_text(item.get("part_name"), MISSING_VALUE)
    return VisualBrief(best_family, best_label, source_summary[:280], confidence)


def illustration_required(item: Mapping[str, Any]) -> bool:
    """Gerçek veya kullanıcı seçimi görselini asla otomatik olarak değiştirmez."""
    if "image_path" in (item.get("manual_fields") or []):
        return False
    path = clean_text(item.get("image_path"), "")
    if path and path != PLACEHOLDER_IMAGE and Path(path).is_file():
        return False
    return True


def visual_content_fingerprint(
    item: Mapping[str, Any], brief: VisualBrief | None = None,
) -> str:
    """Belge açıklaması değiştiğinde eski illüstrasyonun yenilenmesini sağlar."""
    brief = brief or build_visual_brief(item)
    content = "|".join((
        clean_text(item.get("hardware_id"), ""),
        clean_text(item.get("part_name"), ""),
        clean_text(item.get("hardware_type"), ""),
        brief.family,
        brief.source_summary,
    ))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _font(size: int, bold: bool = False):
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            if Path(candidate).is_file():
                return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_brake_pad(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 18, y1 + 35, x2 - 18, y2 - 20), radius=18, fill="#CBD3DB", outline=ink, width=4)
    draw.polygon(((x1 + 32, y1 + 46), (x2 - 32, y1 + 46), (x2 - 48, y2 - 32), (x1 + 48, y2 - 32)), fill=accent, outline=ink)
    draw.ellipse((x1 + 38, y1 + 12, x1 + 66, y1 + 40), fill="#F7F9FB", outline=ink, width=3)
    draw.ellipse((x2 - 66, y1 + 12, x2 - 38, y1 + 40), fill="#F7F9FB", outline=ink, width=3)
    for offset in (0, 20, 40):
        draw.line((x1 + 70 + offset, y1 + 55, x1 + 58 + offset, y2 - 40), fill="#9E2A2B", width=4)


def _draw_brake_shoe(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.arc((x1 + 26, y1 + 16, x2 - 26, y2 + 40), 196, 344, fill=ink, width=24)
    draw.arc((x1 + 33, y1 + 23, x2 - 33, y2 + 33), 196, 344, fill=accent, width=12)
    draw.line((x1 + 55, y2 - 35, x2 - 55, y2 - 35), fill=ink, width=5)
    draw.ellipse((x1 + 48, y2 - 47, x1 + 70, y2 - 25), fill="#F7F9FB", outline=ink, width=3)
    draw.ellipse((x2 - 70, y2 - 47, x2 - 48, y2 - 25), fill="#F7F9FB", outline=ink, width=3)


def _draw_brake_disc(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    size = min(x2 - x1, y2 - y1)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    outer = (cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)
    draw.ellipse(outer, fill="#D7DEE5", outline=ink, width=5)
    draw.ellipse((cx - size * .31, cy - size * .31, cx + size * .31, cy + size * .31), fill="#F7F9FB", outline=accent, width=8)
    draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=ink)
    for dx, dy in ((0, -55), (52, -18), (32, 45), (-32, 45), (-52, -18)):
        draw.ellipse((cx + dx - 8, cy + dy - 8, cx + dx + 8, cy + dy + 8), fill="#F7F9FB", outline=ink, width=2)


def _draw_abs_unit(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 30, y1 + 28, x2 - 30, y2 - 22), radius=12, fill="#D5DDE5", outline=ink, width=4)
    draw.rectangle((x1 + 48, y1 + 46, x2 - 48, y2 - 55), fill="#F7F9FB", outline=accent, width=5)
    draw.text(((x1 + x2) / 2, y1 + 82), "ABS", anchor="mm", fill=accent, font=_font(34, True))
    for offset in (0, 36, 72, 108):
        px = x1 + 56 + offset
        draw.line((px, y1 + 28, px, y1 + 8), fill=ink, width=4)
        draw.ellipse((px - 5, y1 + 3, px + 5, y1 + 13), fill=accent)
    draw.rectangle((x1 + 72, y2 - 26, x2 - 72, y2 + 5), fill=ink)


def _draw_actuator(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.ellipse((x1 + 32, y1 + 35, x1 + 140, y2 - 35), fill="#D7DEE5", outline=ink, width=5)
    draw.rectangle((x1 + 86, y1 + 35, x2 - 55, y2 - 35), fill="#D7DEE5", outline=ink, width=5)
    draw.line((x2 - 55, (y1 + y2) / 2, x2 + 8, (y1 + y2) / 2), fill=accent, width=12)
    draw.ellipse((x2 - 5, (y1 + y2) / 2 - 16, x2 + 27, (y1 + y2) / 2 + 16), fill=accent, outline=ink, width=3)


def _draw_instrument(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    r = min(x2 - x1, y2 - y1) * .42
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#F7F9FB", outline=ink, width=6)
    draw.arc((cx - r + 18, cy - r + 18, cx + r - 18, cy + r - 18), 205, 335, fill=accent, width=9)
    draw.line((cx, cy, cx + r * .53, cy - r * .30), fill=ink, width=7)
    draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=accent)


def _draw_sensor(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 40, y1 + 62, x2 - 60, y2 - 52), radius=14, fill="#D7DEE5", outline=ink, width=5)
    draw.line((x2 - 60, (y1 + y2) / 2, x2 + 4, (y1 + y2) / 2), fill=ink, width=12)
    for inset in (0, 22, 44):
        draw.arc((x1 + 5 - inset / 2, y1 + 34 - inset / 2, x1 + 90 + inset, y2 - 25 + inset / 2), 285, 75, fill=accent, width=5)


def _draw_power(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 28, y1 + 36, x2 - 28, y2 - 32), radius=10, fill="#D7DEE5", outline=ink, width=5)
    draw.polygon(((x1 + 112, y1 + 52), (x1 + 82, y1 + 112), (x1 + 118, y1 + 103), (x1 + 92, y2 - 44), (x1 + 160, y1 + 88), (x1 + 124, y1 + 96)), fill=accent)
    for px in range(int(x1 + 52), int(x2 - 28), 36):
        draw.line((px, y1 + 36, px, y1 + 18), fill=ink, width=4)
        draw.line((px, y2 - 32, px, y2 - 14), fill=ink, width=4)


def _draw_board(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 25, y1 + 25, x2 - 25, y2 - 25), radius=8, fill="#DCE8E1", outline=ink, width=5)
    draw.rectangle((x1 + 88, y1 + 58, x2 - 88, y2 - 58), fill=ink, outline=accent, width=5)
    for px, py in ((55, 50), (55, 115), (185, 48), (190, 116)):
        draw.ellipse((x1 + px - 7, y1 + py - 7, x1 + px + 7, y1 + py + 7), fill=accent)
        draw.line((x1 + px, y1 + py, (x1 + x2) / 2, (y1 + y2) / 2), fill=accent, width=3)


def _draw_mechanical(draw, box, accent, ink):
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    draw.regular_polygon((cx, cy, 78), n_sides=10, fill="#D7DEE5", outline=ink)
    draw.ellipse((cx - 43, cy - 43, cx + 43, cy + 43), fill="#F7F9FB", outline=accent, width=8)
    draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=ink)


def render_technical_illustration(
    item: Mapping[str, Any], output_path: str | Path,
    brief: VisualBrief | None = None,
) -> Path:
    if Image is None:
        raise RuntimeError("Teknik illüstrasyon için Pillow kullanılamıyor.")
    brief = brief or build_visual_brief(item)
    width, height = 720, 420
    image = Image.new("RGB", (width, height), "#F4F7FA")
    draw = ImageDraw.Draw(image)
    accent, ink, muted = "#0759C7", "#25313D", "#65717D"
    draw.rectangle((0, 0, width - 1, height - 1), outline="#CBD3DB", width=3)
    draw.rectangle((0, 0, 12, height), fill=accent)
    draw.text((38, 28), brief.label.upper(), fill=accent, font=_font(20, True))
    draw.text((38, 61), clean_text(item.get("part_name"), "Donanım bileşeni")[:46], fill=ink, font=_font(28, True))
    box = (65, 122, 330, 320)
    family_drawers = {
        "brake_pad": _draw_brake_pad, "brake_shoe": _draw_brake_shoe,
        "brake_disc": _draw_brake_disc, "abs_unit": _draw_abs_unit,
        "actuator": _draw_actuator, "instrument": _draw_instrument,
        "sensor": _draw_sensor, "power_module": _draw_power,
        "circuit_board": _draw_board, "interface": _draw_sensor,
        "mechanical_component": _draw_mechanical,
    }
    family_drawers.get(brief.family, _draw_mechanical)(draw, box, accent, ink)
    draw.text((370, 135), "BELGEDEKİ GÖREV", fill=muted, font=_font(15, True))
    words = brief.source_summary.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > 38 and current:
            lines.append(current); current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    for index, line in enumerate(lines[:6]):
        draw.text((370, 168 + index * 27), line, fill=ink, font=_font(17))
    draw.rectangle((22, 368, width - 22, 402), fill="#E8EEF5")
    draw.text((38, 385), "AI İÇERİK TEMELLİ TEKNİK İLLÜSTRASYON · GERÇEK ÜRÜN FOTOĞRAFI DEĞİLDİR", anchor="lm", fill=muted, font=_font(13, True))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    image.save(temporary, format="PNG", optimize=True)
    temporary.replace(output)
    return output.resolve()


def _safe_name(value: Any) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", clean_text(value, "donanim")).strip("-")
    return safe[:72] or "donanim"


def generate_catalog_illustrations(
    catalog: Mapping[str, Any], output_dir: str | Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Eksik kart görsellerini üretir; gerçek/kullanıcı görsellerine dokunmaz."""
    items = [
        item for item in catalog.get("hardware_items", [])
        if isinstance(item, Mapping) and illustration_required(item)
    ]
    result: dict[str, dict[str, Any]] = {}
    output_root = Path(output_dir)
    total = len(items)
    for index, item in enumerate(items, start=1):
        hardware_id = clean_text(item.get("hardware_id"), f"HW-{index}")
        brief = build_visual_brief(item)
        content_fingerprint = visual_content_fingerprint(item, brief)
        fingerprint = content_fingerprint[:12]
        target = output_root / f"{_safe_name(hardware_id)}-{fingerprint}.png"
        if not target.is_file():
            render_technical_illustration(item, target, brief)
        result[hardware_id] = {
            "image_path": str(target.resolve()),
            "image_source": ILLUSTRATION_SOURCE,
            "image_is_generated": True,
            "visual_brief": brief.to_dict(),
            "content_fingerprint": content_fingerprint,
            "schema_version": VISUAL_SCHEMA_VERSION,
        }
        if progress_callback:
            progress_callback(index, total, clean_text(item.get("part_name"), hardware_id))
    return result


__all__ = [
    "ILLUSTRATION_SOURCE", "VISUAL_SCHEMA_VERSION", "VisualBrief",
    "build_visual_brief", "generate_catalog_illustrations",
    "illustration_required", "render_technical_illustration",
    "visual_content_fingerprint",
]
