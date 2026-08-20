# -*- coding: utf-8 -*-
"""Sağlayıcıdan bağımsız ve güvenli donanım görseli üretim katmanı.

Bu modül Tkinter veya donanım katalog kodu içermez. Sağlayıcı kimlik
bilgileri yalnızca yapılandırma/ortam değişkenlerinden gelir ve hata
metinlerinde hiçbir zaman gösterilmez.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
from dataclasses import dataclass, field
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlparse
import uuid

import requests

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - uygulama Pillow olmadan da açılır.
    Image = ImageDraw = None


ALLOWED_IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
DEFAULT_MAX_FILE_SIZE = 20 * 1024 * 1024
DEFAULT_MAX_PIXELS = 24_000_000
COMFYUI_MARKERS = frozenset({
    "{{PROMPT}}", "{{NEGATIVE_PROMPT}}", "{{MODEL}}",
    "{{SEED}}", "{{WIDTH}}", "{{HEIGHT}}",
})
COMFYUI_MARKER_PATTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class ImageProviderError(RuntimeError):
    """Kullanıcıya güvenli biçimde gösterilebilen sağlayıcı hatası."""


class ImageGenerationCancelled(ImageProviderError):
    """Kullanıcının iptal ettiği üretim."""


@dataclass(slots=True)
class GeneratedImage:
    image_bytes: bytes
    media_type: str
    provider: str
    model: str
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageGenerationProvider(ABC):
    """Bütün görsel üretim sağlayıcılarının uyguladığı sözleşme."""

    provider_name = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def generate_image(
        self, prompt: str, negative_prompt: str = "",
        options: Mapping[str, Any] | None = None,
    ) -> GeneratedImage:
        raise NotImplementedError

    @abstractmethod
    def cancel_generation(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        raise NotImplementedError


def validate_image_bytes(
    data: bytes,
    *,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> tuple[str, tuple[int, int]]:
    """PNG/JPEG/WebP içeriğini imza ve piksel sınırlarıyla doğrular."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ImageProviderError("Görsel sağlayıcısı boş bir dosya döndürdü.")
    if len(data) > max(1, int(max_file_size)):
        raise ImageProviderError("Üretilen görsel izin verilen dosya boyutunu aşıyor.")
    if Image is None:
        signatures = (
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"RIFF", "image/webp"),
        )
        for signature, media_type in signatures:
            if data.startswith(signature):
                return media_type, (0, 0)
        raise ImageProviderError("Yalnızca doğrulanmış PNG, JPEG veya WebP görselleri kabul edilir.")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
    except Exception as error:
        raise ImageProviderError("Üretilen görsel bozuk veya desteklenmeyen biçimde.") from error
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ImageProviderError("Yalnızca PNG, JPEG veya WebP görselleri kabul edilir.")
    if width <= 0 or height <= 0 or width * height > max(1, int(max_pixels)):
        raise ImageProviderError("Üretilen görsel izin verilen piksel sınırını aşıyor.")
    return ALLOWED_IMAGE_FORMATS[image_format], (width, height)


def validate_image_file(
    path: str | Path,
    *,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> tuple[str, tuple[int, int]]:
    candidate = Path(path)
    if not candidate.is_file():
        raise ImageProviderError("Görsel dosyası bulunamadı.")
    return validate_image_bytes(
        candidate.read_bytes(), max_file_size=max_file_size, max_pixels=max_pixels,
    )


class DisabledImageProvider(ImageGenerationProvider):
    provider_name = "disabled"

    def is_available(self) -> bool:
        return False

    def list_models(self) -> list[str]:
        return []

    def generate_image(
        self, prompt: str, negative_prompt: str = "",
        options: Mapping[str, Any] | None = None,
    ) -> GeneratedImage:
        raise ImageProviderError(
            "Gemma görsel üretim açıklaması hazırlayabilir; ancak görüntü dosyası "
            "oluşturmak için ayrı bir görsel üretim modeli yapılandırılmalıdır."
        )

    def cancel_generation(self) -> None:
        return None

    def health_check(self) -> dict[str, Any]:
        return {
            "available": False,
            "provider": self.provider_name,
            "message": "Görsel üretim sağlayıcısı yapılandırılmamış.",
        }


class _HttpProviderBase(ImageGenerationProvider):
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config or {})
        self.base_url = str(self.config.get("base_url") or "").rstrip("/")
        self.model = str(self.config.get("model") or "").strip()
        self.api_key = str(self.config.get("api_key") or "")
        self.timeout = max(2.0, float(self.config.get("timeout") or 180.0))
        self.max_file_size = int(self.config.get("max_file_size") or DEFAULT_MAX_FILE_SIZE)
        self.max_pixels = int(self.config.get("max_pixels") or DEFAULT_MAX_PIXELS)
        self._cancel = threading.Event()
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, image/png, image/jpeg, image/webp"}
        if self.api_key:
            header_name = str(self.config.get("api_key_header") or "Authorization")
            prefix = str(self.config.get("api_key_prefix") or "Bearer ")
            headers[header_name] = f"{prefix}{self.api_key}"
        return headers

    def _safe_error(self, error: Exception, fallback: str) -> ImageProviderError:
        text = str(error)
        if self.api_key:
            text = text.replace(self.api_key, "[GİZLİ]")
        if len(text) > 260:
            text = text[:257] + "..."
        return ImageProviderError(f"{fallback}: {text}" if text else fallback)

    def cancel_generation(self) -> None:
        self._cancel.set()

    def _reset_cancel(self) -> None:
        self._cancel.clear()

    def _ensure_not_cancelled(self) -> None:
        if self._cancel.is_set():
            raise ImageGenerationCancelled("Görsel üretimi kullanıcı tarafından iptal edildi.")

    def is_available(self) -> bool:
        return bool(self.health_check().get("available"))


class HttpImageGenerationProvider(_HttpProviderBase):
    """Yerel veya kullanıcı tanımlı JSON/HTTP görsel API sağlayıcısı."""

    provider_name = "http"

    def health_check(self) -> dict[str, Any]:
        if not self.base_url:
            return {"available": False, "provider": self.provider_name, "message": "API adresi yapılandırılmamış."}
        health_path = str(self.config.get("health_path") or "/health")
        try:
            response = self._session.get(
                f"{self.base_url}{health_path}", headers=self._headers(), timeout=min(8.0, self.timeout),
            )
            return {
                "available": response.ok,
                "provider": self.provider_name,
                "status_code": response.status_code,
                "message": "Sağlayıcı hazır." if response.ok else "Sağlayıcı sağlık kontrolü başarısız.",
            }
        except requests.RequestException:
            return {"available": False, "provider": self.provider_name, "message": "Görsel sağlayıcısına bağlanılamadı."}

    def list_models(self) -> list[str]:
        models_path = str(self.config.get("models_path") or "").strip()
        if not models_path:
            return [self.model] if self.model else []
        try:
            response = self._session.get(
                f"{self.base_url}{models_path}", headers=self._headers(), timeout=min(8.0, self.timeout),
            )
            response.raise_for_status()
            payload = response.json()
            raw = payload.get("models", payload.get("data", [])) if isinstance(payload, Mapping) else payload
            return [str(item.get("id") if isinstance(item, Mapping) else item) for item in raw or [] if item]
        except Exception:
            return [self.model] if self.model else []

    def _response_bytes(self, response: requests.Response) -> bytes:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type.startswith("image/"):
            return response.content
        try:
            payload = response.json()
        except ValueError as error:
            raise ImageProviderError("Görsel API yanıtı geçerli JSON veya görsel değil.") from error
        if not isinstance(payload, Mapping):
            raise ImageProviderError("Görsel API yanıt yapısı desteklenmiyor.")
        encoded = payload.get("image_base64") or payload.get("image") or payload.get("b64_json")
        if not encoded and isinstance(payload.get("data"), list) and payload["data"]:
            first = payload["data"][0]
            if isinstance(first, Mapping):
                encoded = first.get("b64_json") or first.get("image_base64")
        if encoded:
            try:
                return base64.b64decode(str(encoded), validate=True)
            except Exception as error:
                raise ImageProviderError("Görsel API geçersiz Base64 içeriği döndürdü.") from error
        image_url = payload.get("image_url") or payload.get("url")
        if image_url:
            parsed = urlparse(str(image_url))
            base = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ImageProviderError("Görsel API güvenli olmayan bir indirme adresi döndürdü.")
            # Sağlayıcı kimlik bilgisini başka bir sunucuya asla iletme.
            same_origin = (parsed.scheme, parsed.netloc) == (base.scheme, base.netloc)
            headers = self._headers() if same_origin else {"Accept": "image/png, image/jpeg, image/webp"}
            try:
                fetched = self._session.get(
                    str(image_url), headers=headers, timeout=self.timeout, stream=True,
                )
                fetched.raise_for_status()
                declared = int(fetched.headers.get("Content-Length") or 0)
                if declared > self.max_file_size:
                    raise ImageProviderError("Üretilen görsel izin verilen dosya boyutunu aşıyor.")
                chunks: list[bytes] = []; size = 0
                for chunk in fetched.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_file_size:
                        raise ImageProviderError("Üretilen görsel izin verilen dosya boyutunu aşıyor.")
                    chunks.append(chunk)
                return b"".join(chunks)
            except ImageProviderError:
                raise
            except requests.RequestException as error:
                raise self._safe_error(error, "Üretilen görsel indirilemedi") from error
        raise ImageProviderError("Görsel API yanıtında görüntü içeriği bulunamadı.")

    def generate_image(
        self, prompt: str, negative_prompt: str = "",
        options: Mapping[str, Any] | None = None,
    ) -> GeneratedImage:
        if not self.base_url:
            raise ImageProviderError("Görsel API adresi yapılandırılmamış.")
        self._reset_cancel(); self._ensure_not_cancelled()
        options = dict(options or {})
        endpoint = str(self.config.get("generate_path") or "/generate")
        model = str(options.pop("model", "") or self.model)
        payload = {"prompt": prompt, "negative_prompt": negative_prompt, "model": model, **options}
        try:
            response = self._session.post(
                f"{self.base_url}{endpoint}", headers={**self._headers(), "Content-Type": "application/json"},
                json=payload, timeout=self.timeout,
            )
            response.raise_for_status(); self._ensure_not_cancelled()
            data = self._response_bytes(response)
            media_type, dimensions = validate_image_bytes(
                data, max_file_size=self.max_file_size, max_pixels=self.max_pixels,
            )
            seed = options.get("seed")
            return GeneratedImage(
                bytes(data), media_type, self.provider_name, model,
                int(seed) if seed not in (None, "") else None,
                {"dimensions": dimensions},
            )
        except ImageProviderError:
            raise
        except requests.RequestException as error:
            raise self._safe_error(error, "Görsel sağlayıcısı üretim isteğini tamamlayamadı") from error


class ComfyUIImageProvider(_HttpProviderBase):
    """Dosyadan yüklenen iş akışını kullanan ComfyUI HTTP sağlayıcısı."""

    provider_name = "comfyui"

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__(config)
        self.poll_interval = max(0.05, float(self.config.get("poll_interval") or 0.35))
        self.client_id = str(uuid.uuid4())
        self._active_prompt_id: str | None = None
        self._active_prompt_lock = threading.Lock()
        self._cancel_attempted_prompt_ids: set[str] = set()
        self._cancel_session = requests.Session()

    @staticmethod
    def _bounded_integer(
        value: Any, default: int, label: str, *, minimum: int, maximum: int,
    ) -> int:
        try:
            result = int(default if value in (None, "") else value)
        except (TypeError, ValueError) as error:
            raise ImageProviderError(f"ComfyUI {label} değeri sayısal olmalıdır.") from error
        if result < minimum or result > maximum:
            raise ImageProviderError(
                f"ComfyUI {label} değeri {minimum} ile {maximum} arasında olmalıdır."
            )
        return result

    def _validate_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ImageProviderError("ComfyUI adresi geçerli bir HTTP/HTTPS adresi olmalıdır.")

    @staticmethod
    def _substitute_markers(value: Any, replacements: Mapping[str, Any]) -> Any:
        if isinstance(value, Mapping):
            return {
                key: ComfyUIImageProvider._substitute_markers(item, replacements)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [ComfyUIImageProvider._substitute_markers(item, replacements) for item in value]
        if not isinstance(value, str):
            return value
        if value in replacements:
            return replacements[value]
        return COMFYUI_MARKER_PATTERN.sub(
            lambda match: str(replacements.get(match.group(0), match.group(0))), value,
        )

    @staticmethod
    def _markers_in(value: Any) -> set[str]:
        if isinstance(value, Mapping):
            found: set[str] = set()
            for item in value.values():
                found.update(ComfyUIImageProvider._markers_in(item))
            return found
        if isinstance(value, list):
            found = set()
            for item in value:
                found.update(ComfyUIImageProvider._markers_in(item))
            return found
        return set(COMFYUI_MARKER_PATTERN.findall(value)) if isinstance(value, str) else set()

    @staticmethod
    def _is_api_graph(value: Mapping[str, Any]) -> bool:
        return bool(value) and all(
            isinstance(node, Mapping) and bool(str(node.get("class_type") or "").strip())
            for node in value.values()
        )

    @staticmethod
    def _is_history_image_output(node: Mapping[str, Any]) -> bool:
        node_type = str(node.get("class_type") or "").replace("_", "").casefold()
        return "previewimage" in node_type or (
            "saveimage" in node_type and "websocket" not in node_type
        )

    @staticmethod
    def _marker_locations(
        graph: Mapping[str, Any],
    ) -> dict[str, list[tuple[str, str, Any]]]:
        locations = {marker: [] for marker in COMFYUI_MARKERS}
        for node_id, node in graph.items():
            inputs = node.get("inputs", {}) if isinstance(node, Mapping) else {}
            if not isinstance(inputs, Mapping):
                continue
            for input_name, value in inputs.items():
                for marker in ComfyUIImageProvider._markers_in(value):
                    if marker in locations:
                        locations[marker].append(
                            (str(node_id), str(input_name).casefold(), value)
                        )
        return locations

    @staticmethod
    def _linked_node_ids(value: Any, graph_ids: set[str]) -> set[str]:
        if (
            isinstance(value, list) and len(value) == 2
            and str(value[0]) in graph_ids and isinstance(value[1], int)
        ):
            return {str(value[0])}
        found: set[str] = set()
        if isinstance(value, Mapping):
            for item in value.values():
                found.update(ComfyUIImageProvider._linked_node_ids(item, graph_ids))
        elif isinstance(value, list):
            for item in value:
                found.update(ComfyUIImageProvider._linked_node_ids(item, graph_ids))
        return found

    @staticmethod
    def _upstream_node_ids(graph: Mapping[str, Any], output_node_id: str) -> set[str]:
        graph_ids = {str(node_id) for node_id in graph}
        visited: set[str] = set()
        pending = [output_node_id]
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            node = graph.get(node_id)
            inputs = node.get("inputs", {}) if isinstance(node, Mapping) else {}
            if isinstance(inputs, Mapping):
                pending.extend(
                    ComfyUIImageProvider._linked_node_ids(inputs, graph_ids) - visited
                )
        return visited

    def _output_node_id(self, graph: Mapping[str, Any]) -> str:
        configured = str(self.config.get("output_node_id") or "").strip()
        if configured:
            if configured not in graph:
                raise ImageProviderError(
                    f"ComfyUI çıktı düğümü '{configured}' API iş akışında bulunamadı."
                )
            node = graph.get(configured)
            if not isinstance(node, Mapping) or not self._is_history_image_output(node):
                raise ImageProviderError(
                    f"ComfyUI çıktı düğümü '{configured}' "
                    "indirilebilir bir SaveImage/PreviewImage düğümü değil."
                )
            return configured
        candidates = [
            str(node_id) for node_id, node in graph.items()
            if isinstance(node, Mapping) and self._is_history_image_output(node)
        ]
        if not candidates:
            raise ImageProviderError(
                "ComfyUI API iş akışında geçmişten indirilebilir bir SaveImage/PreviewImage düğümü bulunamadı."
            )
        if len(candidates) > 1:
            raise ImageProviderError(
                "ComfyUI API iş akışında birden çok görsel çıktı düğümü var; "
                "EHSIM_COMFYUI_OUTPUT_NODE ile kullanılacak düğüm seçilmelidir."
            )
        return candidates[0]

    def _validate_marker_contract(
        self, graph: Mapping[str, Any], output_node_id: str,
    ) -> None:
        expected_fields = {
            "{{PROMPT}}": {"text", "prompt", "positive", "positive_prompt", "prompt_positive"},
            "{{NEGATIVE_PROMPT}}": {"text", "negative", "negative_prompt", "prompt_negative"},
            "{{MODEL}}": {"ckpt_name", "unet_name", "model_name"},
            "{{SEED}}": {"seed", "noise_seed"},
            "{{WIDTH}}": {"width"},
            "{{HEIGHT}}": {"height"},
        }
        locations = self._marker_locations(graph)
        missing = {marker for marker, values in locations.items() if not values}
        if missing:
            markers = ", ".join(sorted(missing))
            raise ImageProviderError(
                f"ComfyUI düğüm girdilerinde EHSİM üretim işaretçisi eksik: {markers}"
            )
        for marker, values in locations.items():
            invalid_fields = sorted({
                field for _node_id, field, _value in values
                if field not in expected_fields[marker]
            })
            if invalid_fields:
                fields = ", ".join(sorted(expected_fields[marker]))
                raise ImageProviderError(
                    f"ComfyUI {marker} işaretçisi yalnızca şu girdi alanlarında kullanılabilir: {fields}"
                )
        for marker in ("{{PROMPT}}", "{{NEGATIVE_PROMPT}}"):
            if any(not isinstance(value, str) for _node_id, _field, value in locations[marker]):
                raise ImageProviderError(
                    f"ComfyUI {marker} işaretçisi bir metin girdisinde kullanılmalıdır."
                )
        for marker in ("{{MODEL}}", "{{SEED}}", "{{WIDTH}}", "{{HEIGHT}}"):
            if any(value != marker for _node_id, _field, value in locations[marker]):
                raise ImageProviderError(
                    f"ComfyUI {marker} işaretçisi ilgili alanın tam girdi değeri olmalıdır."
                )
        prompt_locations = {
            (node_id, field) for node_id, field, _value in locations["{{PROMPT}}"]
        }
        negative_locations = {
            (node_id, field) for node_id, field, _value in locations["{{NEGATIVE_PROMPT}}"]
        }
        if prompt_locations & negative_locations:
            raise ImageProviderError(
                "ComfyUI positive ve negative prompt işaretçileri ayrı girdi alanlarında olmalıdır."
            )
        upstream = self._upstream_node_ids(graph, output_node_id)
        disconnected = sorted(
            marker for marker, values in locations.items()
            if any(node_id not in upstream for node_id, _field, _value in values)
        )
        if disconnected:
            markers = ", ".join(disconnected)
            raise ImageProviderError(
                f"ComfyUI işaretçileri seçilen çıktı düğümüne bağlı değil: {markers}"
            )

    def _workflow(self, prompt: str, negative_prompt: str, options: Mapping[str, Any]) -> dict[str, Any]:
        workflow_path = Path(str(self.config.get("workflow_path") or ""))
        if not workflow_path.is_file():
            raise ImageProviderError("ComfyUI iş akışı dosyası yapılandırılmamış veya bulunamadı.")
        model = str(options.get("model") or self.model).strip()
        seed = self._bounded_integer(
            options.get("seed"), 0, "seed", minimum=0, maximum=(2 ** 64) - 1,
        )
        width = self._bounded_integer(
            options.get("width"), 1024, "genişlik", minimum=1, maximum=16_384,
        )
        height = self._bounded_integer(
            options.get("height"), 1024, "yükseklik", minimum=1, maximum=16_384,
        )
        try:
            template = workflow_path.read_text(encoding="utf-8")
            replacements = {
                "{{PROMPT}}": prompt,
                "{{NEGATIVE_PROMPT}}": negative_prompt,
                "{{MODEL}}": model,
                "{{SEED}}": seed,
                "{{WIDTH}}": width,
                "{{HEIGHT}}": height,
            }
            template_markers = set(COMFYUI_MARKER_PATTERN.findall(template))
            unknown_markers = template_markers - COMFYUI_MARKERS
            if unknown_markers:
                markers = ", ".join(sorted(unknown_markers))
                raise ImageProviderError(f"ComfyUI iş akışında desteklenmeyen işaretçi var: {markers}")
            # Önceki sürümde desteklenen, JSON içinde tırnaksız bırakılmış sayısal
            # işaretçileri korurken geçerli JSON'daki tırnaklı işaretçileri aşağıda
            # türlerini bozmadan dönüştürürüz.
            for marker in ("{{SEED}}", "{{WIDTH}}", "{{HEIGHT}}"):
                pattern = re.compile(
                    rf"(?P<prefix>(?::|,|\[)\s*){re.escape(marker)}"
                    rf"(?P<suffix>\s*(?:,|\}}|\]))"
                )
                template = pattern.sub(
                    lambda match, replacement=json.dumps(marker):
                    f"{match.group('prefix')}{replacement}{match.group('suffix')}",
                    template,
                )
            payload = json.loads(template)
        except (OSError, json.JSONDecodeError) as error:
            raise ImageProviderError("ComfyUI iş akışı dosyası okunamadı veya geçerli JSON değil.") from error
        if not isinstance(payload, Mapping):
            raise ImageProviderError("ComfyUI iş akışı JSON nesnesi olmalıdır.")
        if isinstance(payload.get("nodes"), list):
            raise ImageProviderError(
                "ComfyUI iş akışı normal kayıt biçiminde; 'Export Workflow (API)' ile dışa aktarılmalıdır."
            )
        if not self._is_api_graph(payload) and isinstance(payload.get("prompt"), Mapping):
            payload = payload["prompt"]
        if not self._is_api_graph(payload):
            raise ImageProviderError("ComfyUI iş akışı API biçiminde geçerli düğümler içermiyor.")
        for node in payload.values():
            inputs = node.get("inputs")
            if not isinstance(inputs, Mapping):
                raise ImageProviderError("ComfyUI API iş akışındaki her düğüm 'inputs' nesnesi içermelidir.")
        output_node_id = self._output_node_id(payload)
        self._validate_marker_contract(payload, output_node_id)
        if not model:
            raise ImageProviderError("ComfyUI iş akışı model işaretçisi içeriyor; model yapılandırılmamış.")
        graph = self._substitute_markers(payload, replacements)
        if not isinstance(graph, Mapping):
            raise ImageProviderError("ComfyUI iş akışı API biçiminde geçerli düğümler içermiyor.")
        return dict(graph)

    @staticmethod
    def _json_object(response: requests.Response, message: str) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise ImageProviderError(message) from error
        if not isinstance(payload, Mapping):
            raise ImageProviderError(message)
        return payload

    def _safe_detail(self, value: Any) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if self.api_key:
            text = text.replace(self.api_key, "[GİZLİ]")
        return text[:220]

    def _prompt_error_detail(self, payload: Mapping[str, Any]) -> str:
        details: list[str] = []

        def append_detail(value: Any) -> None:
            if isinstance(value, Mapping):
                for key in ("message", "details", "type"):
                    text = self._safe_detail(value.get(key))
                    if text and text not in details:
                        details.append(text)
            else:
                text = self._safe_detail(value)
                if text and text not in details:
                    details.append(text)

        append_detail(payload.get("error"))
        node_errors = payload.get("node_errors")
        if isinstance(node_errors, Mapping):
            for node_error in node_errors.values():
                if not isinstance(node_error, Mapping):
                    continue
                errors = node_error.get("errors")
                if not isinstance(errors, list):
                    continue
                for error in errors[:2]:
                    append_detail(error)
                if len(details) >= 4:
                    break
        return self._safe_detail(" | ".join(details))

    def health_check(self) -> dict[str, Any]:
        if not self.base_url:
            return {"available": False, "provider": self.provider_name, "message": "ComfyUI adresi yapılandırılmamış."}
        try:
            self._validate_base_url()
            self._workflow(
                "EHSİM bağlantı kontrolü", "",
                {"model": self.model, "seed": 0, "width": 512, "height": 512},
            )
            response = self._session.get(
                f"{self.base_url}/system_stats", headers=self._headers(),
                timeout=min(8.0, self.timeout), allow_redirects=False,
            )
            response.raise_for_status()
            payload = self._json_object(response, "ComfyUI sağlık yanıtı geçerli JSON değil.")
            if "system" not in payload and "devices" not in payload:
                raise ImageProviderError("ComfyUI sağlık yanıtı beklenen yapıda değil.")
            return {
                "available": True, "provider": self.provider_name,
                "message": "ComfyUI bağlantısı ve yerel API iş akışı ön denetimi hazır.",
            }
        except ImageProviderError as error:
            return {"available": False, "provider": self.provider_name, "message": str(error)}
        except requests.RequestException:
            return {"available": False, "provider": self.provider_name, "message": "ComfyUI servisine bağlanılamadı."}

    def list_models(self) -> list[str]:
        configured = [self.model] if self.model else []
        if not self.base_url:
            return configured
        models_path = str(self.config.get("models_path") or "/models/checkpoints").strip()
        if not models_path.startswith("/"):
            models_path = f"/{models_path}"
        try:
            self._validate_base_url()
            response = self._session.get(
                f"{self.base_url}{models_path}", headers=self._headers(),
                timeout=min(8.0, self.timeout), allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, Mapping):
                payload = payload.get("models", payload.get("checkpoints", []))
            if not isinstance(payload, (list, tuple)):
                return configured
            discovered = [str(value).strip() for value in payload or [] if str(value).strip()]
            return list(dict.fromkeys([*configured, *discovered]))
        except Exception:
            return configured

    def _execution_error(self, history: Mapping[str, Any]) -> str:
        status = history.get("status")
        if not isinstance(status, Mapping):
            return ""
        status_text = str(status.get("status_str") or "").casefold()
        if status_text not in {"error", "failed", "failure"}:
            return ""
        detail = ""
        messages = status.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, (list, tuple)) or len(message) < 2:
                    continue
                data = message[1]
                if isinstance(data, Mapping):
                    detail = self._safe_detail(
                        data.get("exception_message") or data.get("error") or data.get("message")
                    )
                    if detail:
                        break
        return f"ComfyUI iş akışı yürütme hatası: {detail}" if detail else "ComfyUI iş akışı yürütme hatası."

    def _select_image(
        self, history: Mapping[str, Any], output_node_id: str,
    ) -> tuple[str, Mapping[str, Any]]:
        execution_error = self._execution_error(history)
        if execution_error:
            raise ImageProviderError(execution_error)
        outputs = history.get("outputs")
        if not isinstance(outputs, Mapping):
            raise ImageProviderError("ComfyUI iş sonucunda çıktı bulunamadı.")
        candidates: list[tuple[int, str, Mapping[str, Any]]] = []
        for node_id in [output_node_id]:
            output = outputs.get(node_id)
            images = output.get("images", []) if isinstance(output, Mapping) else []
            if not isinstance(images, list):
                continue
            for image in images:
                if not isinstance(image, Mapping) or not str(image.get("filename") or "").strip():
                    continue
                priority = 0 if str(image.get("type") or "output") == "output" else 1
                candidates.append((priority, node_id, image))
        if not candidates:
            raise ImageProviderError(
                f"ComfyUI çıktı düğümü '{output_node_id}' görsel döndürmedi."
            )
        _priority, node_id, image_info = min(candidates, key=lambda item: item[0])
        return node_id, image_info

    def _download_image(
        self, image_info: Mapping[str, Any], *, deadline: float | None = None,
    ) -> bytes:
        self._ensure_not_cancelled()
        if deadline is not None and time.monotonic() >= deadline:
            raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
        image_type = str(image_info.get("type") or "output")
        if image_type not in {"input", "output", "temp"}:
            raise ImageProviderError("ComfyUI geçersiz bir görsel çıktı türü döndürdü.")
        response = self._session.get(
            f"{self.base_url}/view",
            params={
                "filename": str(image_info.get("filename") or ""),
                "subfolder": str(image_info.get("subfolder") or ""),
                "type": image_type,
            },
            headers=self._headers(),
            timeout=min(
                self.timeout,
                max(0.05, deadline - time.monotonic()) if deadline is not None else self.timeout,
            ),
            stream=True, allow_redirects=False,
        )
        try:
            response.raise_for_status()
            try:
                declared_size = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                declared_size = 0
            if declared_size > self.max_file_size:
                raise ImageProviderError("Üretilen görsel izin verilen dosya boyutunu aşıyor.")
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                self._ensure_not_cancelled()
                if deadline is not None and time.monotonic() >= deadline:
                    raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
                if not chunk:
                    continue
                received += len(chunk)
                if received > self.max_file_size:
                    raise ImageProviderError("Üretilen görsel izin verilen dosya boyutunu aşıyor.")
                chunks.append(chunk)
            self._ensure_not_cancelled()
            if deadline is not None and time.monotonic() >= deadline:
                raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
            return b"".join(chunks)
        finally:
            response.close()

    def _cancel_prompt(self, prompt_id: str) -> None:
        if not prompt_id or not self.base_url:
            return
        headers = {**self._headers(), "Content-Type": "application/json"}
        try:
            response = self._cancel_session.post(
                f"{self.base_url}/api/jobs/{prompt_id}/cancel", headers=headers,
                json={}, timeout=min(3.0, self.timeout), allow_redirects=False,
            )
            if response.ok:
                return
        except requests.RequestException:
            pass
        try:
            self._cancel_session.post(
                f"{self.base_url}/queue", headers=headers,
                json={"delete": [prompt_id]}, timeout=min(3.0, self.timeout),
                allow_redirects=False,
            )
        except requests.RequestException:
            pass

    def _cancel_prompt_once(self, prompt_id: str) -> None:
        if not prompt_id:
            return
        with self._active_prompt_lock:
            if prompt_id in self._cancel_attempted_prompt_ids:
                return
            self._cancel_attempted_prompt_ids.add(prompt_id)
        self._cancel_prompt(prompt_id)

    def cancel_generation(self) -> None:
        with self._active_prompt_lock:
            self._cancel.set()
            prompt_id = self._active_prompt_id
        if prompt_id:
            threading.Thread(
                target=self._cancel_prompt_once, args=(prompt_id,), daemon=True,
                name="comfyui-cancel",
            ).start()

    def generate_image(
        self, prompt: str, negative_prompt: str = "",
        options: Mapping[str, Any] | None = None,
    ) -> GeneratedImage:
        with self._active_prompt_lock:
            if self._cancel.is_set():
                self._cancel.clear()
                raise ImageGenerationCancelled("Görsel üretimi kullanıcı tarafından iptal edildi.")
            self._cancel.clear()
        self._validate_base_url()
        options = dict(options or {})
        if options.get("seed") in (None, ""):
            options["seed"] = secrets.randbelow(2 ** 64)
        workflow = self._workflow(prompt, negative_prompt, options)
        selected_output_node_id = self._output_node_id(workflow)
        deadline = time.monotonic() + self.timeout
        prompt_id = ""
        try:
            self._ensure_not_cancelled()
            response = self._session.post(
                f"{self.base_url}/prompt",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"prompt": workflow, "client_id": self.client_id},
                timeout=min(30.0, self.timeout, max(0.05, deadline - time.monotonic())),
                allow_redirects=False,
            )
            if not response.ok:
                try:
                    error_payload = response.json()
                except (TypeError, ValueError):
                    error_payload = {}
                detail = self._prompt_error_detail(error_payload) if isinstance(error_payload, Mapping) else ""
                status_code = getattr(response, "status_code", "")
                suffix = f": {detail}" if detail else f" (HTTP {status_code})"
                raise ImageProviderError(f"ComfyUI API iş akışını reddetti{suffix}")
            response.raise_for_status()
            queue_payload = self._json_object(
                response, "ComfyUI iş isteğine geçerli JSON yanıtı vermedi."
            )
            prompt_id = str(queue_payload.get("prompt_id") or "")
            if not prompt_id:
                detail = self._safe_detail(queue_payload.get("error"))
                raise ImageProviderError(
                    f"ComfyUI iş kimliği döndürmedi: {detail}" if detail
                    else "ComfyUI iş kimliği döndürmedi."
                )
            with self._active_prompt_lock:
                self._active_prompt_id = prompt_id
            self._ensure_not_cancelled()
            if time.monotonic() >= deadline:
                raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
            history: Mapping[str, Any] = {}
            while time.monotonic() < deadline:
                self._ensure_not_cancelled()
                remaining = deadline - time.monotonic()
                poll = self._session.get(
                    f"{self.base_url}/history/{prompt_id}", headers=self._headers(),
                    timeout=min(10.0, self.timeout, max(0.05, remaining)),
                    allow_redirects=False,
                )
                poll.raise_for_status()
                payload = self._json_object(
                    poll, "ComfyUI geçmiş yanıtı geçerli JSON değil."
                )
                if isinstance(payload, Mapping) and prompt_id in payload:
                    candidate = payload[prompt_id]
                    if not isinstance(candidate, Mapping):
                        raise ImageProviderError("ComfyUI iş geçmişi beklenen yapıda değil.")
                    history = candidate
                    break
                time.sleep(min(self.poll_interval, max(0.0, deadline - time.monotonic())))
            if not history:
                raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
            self._ensure_not_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
            output_node_id, image_info = self._select_image(
                history, selected_output_node_id,
            )
            data = self._download_image(image_info, deadline=deadline)
            if time.monotonic() >= deadline:
                raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
            media_type, dimensions = validate_image_bytes(
                data, max_file_size=self.max_file_size, max_pixels=self.max_pixels,
            )
            self._ensure_not_cancelled()
            if time.monotonic() >= deadline:
                raise ImageProviderError("ComfyUI üretimi zaman aşımına uğradı.")
            model = str(options.get("model") or self.model or "")
            seed = options.get("seed")
            try:
                normalized_seed = int(seed) if seed not in (None, "") else None
            except (TypeError, ValueError):
                normalized_seed = None
            self._ensure_not_cancelled()
            return GeneratedImage(
                data, media_type, self.provider_name, model,
                normalized_seed,
                {
                    "dimensions": dimensions, "prompt_id": prompt_id,
                    "output_node_id": output_node_id,
                    "remote_filename": str(image_info.get("filename") or ""),
                },
            )
        except ImageGenerationCancelled:
            if prompt_id:
                self._cancel_prompt_once(prompt_id)
            self._reset_cancel()
            raise
        except ImageProviderError:
            if prompt_id:
                self._cancel_prompt_once(prompt_id)
            raise
        except requests.RequestException as error:
            if prompt_id:
                self._cancel_prompt_once(prompt_id)
            raise self._safe_error(error, "ComfyUI üretimi tamamlanamadı") from error
        finally:
            if prompt_id:
                with self._active_prompt_lock:
                    if self._active_prompt_id == prompt_id:
                        self._active_prompt_id = None


class MockImageProvider(ImageGenerationProvider):
    """Testlerde gerçek görüntü servisi gerektirmeyen deterministik sağlayıcı."""

    provider_name = "mock"

    def __init__(self, *, available: bool = True, fail: bool = False, delay: float = 0.0) -> None:
        self.available = available; self.fail = fail; self.delay = max(0.0, delay)
        self._cancel = threading.Event(); self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return self.available

    def list_models(self) -> list[str]:
        return ["mock-technical-image-v1"] if self.available else []

    def health_check(self) -> dict[str, Any]:
        return {"available": self.available, "provider": self.provider_name, "message": "Mock sağlayıcı hazır." if self.available else "Mock sağlayıcı kapalı."}

    def cancel_generation(self) -> None:
        self._cancel.set()

    def generate_image(
        self, prompt: str, negative_prompt: str = "",
        options: Mapping[str, Any] | None = None,
    ) -> GeneratedImage:
        self._cancel.clear(); options = dict(options or {})
        self.calls.append({"prompt": prompt, "negative_prompt": negative_prompt, "options": options})
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                raise ImageGenerationCancelled("Görsel üretimi kullanıcı tarafından iptal edildi.")
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        if self._cancel.is_set():
            raise ImageGenerationCancelled("Görsel üretimi kullanıcı tarafından iptal edildi.")
        if not self.available:
            raise ImageProviderError("Mock görsel sağlayıcısı kullanılamıyor.")
        if self.fail:
            raise ImageProviderError("Mock görsel üretimi bilinçli olarak başarısız oldu.")
        if Image is None:
            data = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
        else:
            image = Image.new("RGB", (320, 240), "#F4F7FA")
            draw = ImageDraw.Draw(image); draw.rectangle((24, 24, 296, 216), outline="#0759C7", width=4)
            draw.text((44, 102), "MOCK · AI KAVRAMSAL", fill="#25313D")
            stream = BytesIO(); image.save(stream, format="PNG"); data = stream.getvalue()
        media_type, dimensions = validate_image_bytes(data)
        return GeneratedImage(
            data, media_type, self.provider_name,
            str(options.get("model") or "mock-technical-image-v1"),
            int(options["seed"]) if options.get("seed") not in (None, "") else 42,
            {"dimensions": dimensions},
        )


def create_image_provider(config: Mapping[str, Any] | None = None) -> ImageGenerationProvider:
    """Yapılandırmadan sağlayıcı üretir; bilinmeyen türde güvenle devre dışı kalır."""
    if config is None:
        try:
            from config import IMAGE_GENERATION_CONFIG
            config = IMAGE_GENERATION_CONFIG
        except Exception:
            config = {}
    values = dict(config or {})
    provider_type = str(values.get("provider") or "disabled").strip().casefold()
    if provider_type in {"http", "local_http", "custom_api", "local_service"}:
        provider = HttpImageGenerationProvider(values)
        provider.provider_name = provider_type
        return provider
    if provider_type in {"comfyui", "comfy_ui"}:
        return ComfyUIImageProvider(values)
    if provider_type == "mock":
        return MockImageProvider(
            available=bool(values.get("available", True)), fail=bool(values.get("fail", False)),
            delay=float(values.get("delay") or 0),
        )
    return DisabledImageProvider()


__all__ = [
    "ALLOWED_IMAGE_FORMATS", "ComfyUIImageProvider", "DEFAULT_MAX_FILE_SIZE",
    "DEFAULT_MAX_PIXELS", "DisabledImageProvider", "GeneratedImage",
    "HttpImageGenerationProvider", "ImageGenerationCancelled",
    "ImageGenerationProvider", "ImageProviderError", "MockImageProvider",
    "create_image_provider", "validate_image_bytes", "validate_image_file",
]
