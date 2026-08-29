# -*- coding: utf-8 -*-
"""Belge sonrası izlenebilirlik, RAG ve kullanıcı düzeltme entegrasyonu."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable, Mapping, Sequence

from etki_analizi_izlenebilirlik import RELATION_LABELS_TR


REQUIREMENT_TYPES = {
    "Müşteri/paydaş gereksinimi", "Sistem gereksinimi", "Alt sistem gereksinimi",
}
TEST_TYPES = {
    "Doğrulama kriteri", "Birim testi", "Entegrasyon testi",
    "Sistem doğrulama testi", "Müşteri kabul/geçerleme testi",
}
_INDEX_LOCK = threading.Lock()


class IntegrationError(RuntimeError):
    """Kullanıcıya gösterilebilecek entegrasyon hatası."""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _safe(value: Any) -> str:
    text = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in _clean(value)
    ).strip("-")
    return text or "proje"


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_text(
        path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def _project_dir(report: Mapping[str, Any]) -> Path:
    if _clean(report.get("storage_path")):
        return Path(_clean(report["storage_path"])).resolve().parent
    from etki_analizi_izlenebilirlik import DEFAULT_OUTPUT_ROOT
    return DEFAULT_OUTPUT_ROOT / _safe(report.get("project_id"))


def overrides_path(report: Mapping[str, Any]) -> Path:
    return _project_dir(report) / "traceability_overrides.json"


def _empty_overrides() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "updated_at": _now(),
        "rejected_edge_ids": [], "manual_edges": [], "suggestion_decisions": {},
    }


def load_overrides(report: Mapping[str, Any]) -> dict[str, Any]:
    path = overrides_path(report)
    if not path.exists():
        return _empty_overrides()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrationError(f"İzlenebilirlik düzeltmeleri okunamadı: {error}") from error
    if not isinstance(value, dict):
        raise IntegrationError("İzlenebilirlik düzeltme dosyası geçerli değil.")
    result = _empty_overrides()
    result.update(value)
    result["rejected_edge_ids"] = list(result.get("rejected_edge_ids") or [])
    result["manual_edges"] = list(result.get("manual_edges") or [])
    result["suggestion_decisions"] = dict(result.get("suggestion_decisions") or {})
    return result


def save_overrides(report: Mapping[str, Any], overrides: Mapping[str, Any]) -> Path:
    value = _empty_overrides()
    value.update(deepcopy(dict(overrides)))
    value["updated_at"] = _now()
    path = overrides_path(report)
    _atomic_json(path, value)
    return path


def _recalculate_health(report: dict[str, Any]) -> None:
    nodes = {
        _clean(node.get("id")): node for node in report.get("nodes", [])
        if isinstance(node, Mapping) and _clean(node.get("id"))
    }
    adjacency = {node_id: set() for node_id in nodes}
    linked: set[str] = set()
    for edge in report.get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source, target = _clean(edge.get("source_id")), _clean(edge.get("target_id"))
        if source not in nodes or target not in nodes:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
        if _clean(edge.get("relationship_type")) != "documented_in":
            linked.update((source, target))
    requirements = [
        node_id for node_id, node in nodes.items()
        if _clean(node.get("node_type")) in REQUIREMENT_TYPES
    ]
    report["unlinked_requirements"] = [
        node_id for node_id in requirements if node_id not in linked
    ]
    tests = {
        node_id for node_id, node in nodes.items()
        if _clean(node.get("node_type")) in TEST_TYPES
    }
    unverified = []
    for requirement_id in requirements:
        queue, visited, verified = [requirement_id], {requirement_id}, False
        while queue and not verified:
            for neighbour in adjacency.get(queue.pop(0), set()):
                if neighbour in tests:
                    verified = True
                    break
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
        if not verified:
            unverified.append(requirement_id)
    report["unverified_requirements"] = unverified
    summary = dict(report.get("summary") or {})
    summary.update({
        "node_count": len(nodes), "edge_count": len(report.get("edges", [])),
        "unlinked_requirement_count": len(report["unlinked_requirements"]),
        "unverified_requirement_count": len(unverified),
        "conflict_count": len(report.get("conflicts", [])),
    })
    report["summary"] = summary


def apply_overrides(
    report: Mapping[str, Any], overrides: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Düzeltmeleri raporun çalışma kopyasına uygular; kaynak raporu değiştirmez."""
    result = deepcopy(dict(report))
    value = dict(overrides or load_overrides(result))
    rejected = {_clean(item) for item in value.get("rejected_edge_ids", [])}
    result["edges"] = [
        deepcopy(dict(edge)) for edge in result.get("edges", [])
        if isinstance(edge, Mapping) and _clean(edge.get("id")) not in rejected
    ]
    node_ids = {
        _clean(node.get("id")) for node in result.get("nodes", [])
        if isinstance(node, Mapping)
    }
    edge_ids = {_clean(edge.get("id")) for edge in result["edges"]}
    for raw in value.get("manual_edges", []):
        if not isinstance(raw, Mapping):
            continue
        edge = deepcopy(dict(raw))
        if (
            _clean(edge.get("id")) and _clean(edge.get("id")) not in edge_ids
            and _clean(edge.get("source_id")) in node_ids
            and _clean(edge.get("target_id")) in node_ids
        ):
            result["edges"].append(edge)
            edge_ids.add(_clean(edge.get("id")))
    result["user_overrides"] = {
        "rejected_edge_count": len(rejected),
        "manual_edge_count": len(value.get("manual_edges", [])),
        "suggestion_decisions": dict(value.get("suggestion_decisions") or {}),
        "storage_path": str(overrides_path(result)),
    }
    _recalculate_health(result)
    return result


def add_manual_edge(
    report: Mapping[str, Any], source_id: str, target_id: str, relation: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_id, target_id, relation = _clean(source_id), _clean(target_id), _clean(relation)
    node_ids = {
        _clean(node.get("id")) for node in report.get("nodes", [])
        if isinstance(node, Mapping)
    }
    if source_id not in node_ids or target_id not in node_ids:
        raise IntegrationError("Bağlantı uçları gerçek izlenebilirlik kimliklerinden seçilmelidir.")
    if source_id == target_id:
        raise IntegrationError("Bir öğe kendisine bağlanamaz.")
    if relation not in RELATION_LABELS_TR:
        raise IntegrationError("Desteklenmeyen ilişki türü seçildi.")
    digest = hashlib.sha256(
        f"{source_id}|{relation}|{target_id}".encode("utf-8")
    ).hexdigest()[:12].upper()
    edge = {
        "id": f"MANUAL-{digest}", "source_id": source_id, "target_id": target_id,
        "relationship_type": relation, "relationship_label": RELATION_LABELS_TR[relation],
        "confidence_level": "Kullanıcı onaylı", "confidence": 1.0,
        "evidence_text": "Etki Analizi ekranında kullanıcı tarafından eklendi.",
        "source_document": "Kullanıcı düzeltmesi",
        "derivation_method": "manual_override", "created_at": _now(),
    }
    overrides = load_overrides(report)
    overrides["manual_edges"] = [
        item for item in overrides["manual_edges"]
        if _clean(item.get("id") if isinstance(item, Mapping) else "") != edge["id"]
    ] + [edge]
    overrides["rejected_edge_ids"] = [
        item for item in overrides["rejected_edge_ids"] if _clean(item) != edge["id"]
    ]
    save_overrides(report, overrides)
    return apply_overrides(report, overrides), edge


def reject_edge(report: Mapping[str, Any], edge_id: str) -> dict[str, Any]:
    edge_id = _clean(edge_id)
    known = {
        _clean(edge.get("id")) for edge in report.get("edges", [])
        if isinstance(edge, Mapping)
    }
    if not edge_id or edge_id not in known:
        raise IntegrationError("Reddedilecek bağlantı bulunamadı.")
    overrides = load_overrides(report)
    base_report: Mapping[str, Any] = report
    if edge_id.startswith("MANUAL-"):
        overrides["manual_edges"] = [
            edge for edge in overrides["manual_edges"]
            if _clean(edge.get("id") if isinstance(edge, Mapping) else "") != edge_id
        ]
        base_report = deepcopy(dict(report))
        base_report["edges"] = [
            edge for edge in report.get("edges", [])
            if _clean(edge.get("id") if isinstance(edge, Mapping) else "") != edge_id
        ]
    elif edge_id not in overrides["rejected_edge_ids"]:
        overrides["rejected_edge_ids"].append(edge_id)
    save_overrides(report, overrides)
    return apply_overrides(base_report, overrides)


def set_suggestion_decision(
    report: Mapping[str, Any], suggestion_id: str, decision: str
) -> dict[str, Any]:
    if decision not in {"Kabul edildi", "Reddedildi", "Bekliyor"}:
        raise IntegrationError("Geçersiz öneri kararı.")
    overrides = load_overrides(report)
    overrides["suggestion_decisions"][_clean(suggestion_id)] = decision
    save_overrides(report, overrides)
    return overrides


def _rag_content(report: Mapping[str, Any]) -> str:
    lines = [
        f"PROJE: {_clean(report.get('project_name'))}",
        f"PROJE_KIMLIGI: {_clean(report.get('project_id'))}",
        f"IZLENEBILIRLIK_SURUMU: {report.get('revision', 0)}",
        "KAYNAK: Belge üretimindeki yapılandırılmış Python verisi", "",
    ]
    for node in report.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        lines.extend([
            f"ID: {_clean(node.get('id'))}", f"TUR: {_clean(node.get('node_type'))}",
            f"V_MODEL: {_clean(node.get('v_model_level'))}",
            f"BASLIK: {_clean(node.get('title'))}",
            f"ACIKLAMA: {_clean(node.get('description'))}",
            f"KAYNAK_BELGE: {_clean(node.get('source_document'))}",
            f"BOLUM: {_clean(node.get('section') or node.get('page_section'))}",
            f"KANIT: {_clean(node.get('evidence_text'))}", "---",
        ])
    lines.append("ILISKILER")
    for edge in report.get("edges", []):
        if isinstance(edge, Mapping):
            lines.append(
                f"{_clean(edge.get('source_id'))} -> {_clean(edge.get('relationship_type'))} "
                f"-> {_clean(edge.get('target_id'))} | {_clean(edge.get('confidence_level'))}"
            )
    return "\n".join(lines).strip() + "\n"


def document_set_fingerprint(
    report: Mapping[str, Any], source_paths: Sequence[str | os.PathLike[str]] | None = None
) -> str:
    sources = []
    for raw in source_paths or ():
        path, item = Path(raw), {"path": str(raw)}
        try:
            stat = path.stat()
            item.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        except OSError:
            item["missing"] = True
        sources.append(item)
    value = {
        "schema": "1.0", "project_id": report.get("project_id"),
        "nodes": report.get("nodes", []), "edges": report.get("edges", []),
        "sources": sorted(sources, key=lambda item: item["path"]),
    }
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def update_structured_rag_index(
    report: Mapping[str, Any], *,
    source_paths: Sequence[str | os.PathLike[str]] | None = None,
    force: bool = False, cancel_event: threading.Event | None = None,
    rag_builder: Callable[[bool], bool] | None = None,
    data_path: str | os.PathLike[str] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Aynı sürümü atlayarak yapılandırılmış izleri mevcut RAG havuzuna ekler."""
    with _INDEX_LOCK:
        if cancel_event and cancel_event.is_set():
            return {"status": "cancelled", "updated": False, "message": "RAG indeksleme iptal edildi."}
        handler = None
        if rag_builder is None or data_path is None:
            try:
                from rag_handler import rag_handler as handler
            except Exception as error:
                return {"status": "unavailable", "updated": False,
                        "message": f"RAG altyapısı yüklenemedi: {error}"}
        builder = rag_builder or (
            lambda rebuild: bool(handler.build_knowledge_base(force_rebuild=rebuild))
        )
        base = Path(data_path or getattr(handler, "data_path", "rag_documents"))
        project_id = _safe(report.get("project_id"))
        target = base / "existing_requirements" / f"traceability-{project_id}.txt"
        manifest_path = base / ".traceability-index-manifest.json"
        fingerprint = document_set_fingerprint(report, source_paths)
        manifest = {"schema_version": "1.0", "projects": {}}
        if manifest_path.exists():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    manifest.update(loaded)
                    manifest["projects"] = dict(manifest.get("projects") or {})
            except (OSError, json.JSONDecodeError):
                pass
        previous = dict(manifest["projects"].get(project_id) or {})
        if not force and previous.get("fingerprint") == fingerprint and target.exists():
            return {"status": "unchanged", "updated": False, "fingerprint": fingerprint,
                    "path": str(target.resolve()),
                    "message": "Belge sürümü değişmedi; RAG indeksi yeniden oluşturulmadı."}
        if status_callback:
            status_callback("Yapılandırılmış belge seti RAG indeksine aktarılıyor...")
        _atomic_text(target, _rag_content(report))
        if cancel_event and cancel_event.is_set():
            return {"status": "cancelled", "updated": False, "message": "RAG indeksleme iptal edildi."}
        try:
            built = bool(builder(True))
        except Exception as error:
            return {"status": "failed", "updated": False, "path": str(target.resolve()),
                    "message": f"RAG indeksi güncellenemedi: {error}"}
        if not built:
            detail = _clean(getattr(handler, "last_build_error", "")) if handler else ""
            return {"status": "failed", "updated": False, "path": str(target.resolve()),
                    "message": (
                        f"RAG belgesi hazırlandı ancak indeks tamamlanamadı: {detail}"
                        if detail else
                        "RAG belgesi hazırlandı ancak indeks tamamlanamadı."
                    )}
        manifest["projects"][project_id] = {
            "fingerprint": fingerprint, "indexed_at": _now(),
            "document_path": str(target.resolve()),
            "traceability_revision": report.get("revision", 0),
        }
        manifest["updated_at"] = _now()
        _atomic_json(manifest_path, manifest)
        return {"status": "updated", "updated": True, "fingerprint": fingerprint,
                "path": str(target.resolve()), "message": "RAG indeksi güncellendi."}


def build_health_summary(
    report: Mapping[str, Any], rag_status: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    summary, rag = dict(report.get("summary") or {}), dict(rag_status or {})
    node_count = int(summary.get("node_count", len(report.get("nodes", []))) or 0)
    return {
        "project_id": _clean(report.get("project_id")),
        "project_name": _clean(report.get("project_name")),
        "status": "Analize hazır" if node_count else "Belge üretimi gerekli",
        "ready": bool(node_count), "node_count": node_count,
        "edge_count": int(summary.get("edge_count", len(report.get("edges", []))) or 0),
        "unlinked_count": len(report.get("unlinked_requirements", [])),
        "unverified_count": len(report.get("unverified_requirements", [])),
        "conflict_count": len(report.get("conflicts", [])),
        "missing_count": len(report.get("missing_information", [])),
        "rag_status": rag.get("status", "not_run"),
        "rag_message": _clean(rag.get("message")),
        "generated_at": _clean(report.get("generated_at")),
        "revision": report.get("revision", 0),
    }


__all__ = [
    "IntegrationError", "add_manual_edge", "apply_overrides",
    "build_health_summary", "document_set_fingerprint", "load_overrides",
    "overrides_path", "reject_edge", "save_overrides",
    "set_suggestion_decision", "update_structured_rag_index",
]
