# -*- coding: utf-8 -*-
"""V-Model izlenebilirlik grafiği üzerinde değişiklik etki simülasyonu.

Bu modül iki katmanı kesin biçimde ayırır:

* Grafik yayılımı, etki/risk puanları ve test geçerliliği Python ile
  deterministik olarak hesaplanır.
* LM Studio yalnızca yorum ve mühendislik önerisi üretir. Model yanıtı,
  izlenebilirlikteki gerçek kimliklerden oluşan izin listesiyle doğrulanır.

Hiçbir fonksiyon kaynak belgeleri veya izlenebilirlik haritasını değiştirmez.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from math import ceil
from pathlib import Path
import queue as thread_queue
import re
import threading
import unicodedata
from typing import Any, Callable, Iterable, Mapping, Sequence

from etki_analizi_izlenebilirlik import (
    CONFIDENCE_EXACT,
    CONFIDENCE_INFERRED,
    CONFIDENCE_SUGGESTED,
    extract_identifiers,
    normalize_identifier,
    semantic_similarity,
)


CHANGE_REQUIREMENT_ADD = "Gereksinim ekleme"
CHANGE_REQUIREMENT_TEXT = "Gereksinim metni değiştirme"
CHANGE_NUMERIC_LIMIT = "Sayısal sınır değiştirme"
CHANGE_REQUIREMENT_REMOVE = "Gereksinim kaldırma"
CHANGE_PRIORITY = "Öncelik/kritiklik değiştirme"
CHANGE_VERIFICATION = "Doğrulama yöntemi değiştirme"
CHANGE_PART_ALTERNATIVE = "Parça alternatifi"
CHANGE_SYSTEM_ALTERNATIVE = "Sistem durumu alternatifi"
CHANGE_INTERFACE = "Arayüz değişikliği"
CHANGE_OPERATING_CONDITION = "Çalışma koşulu değişikliği"

SUPPORTED_CHANGE_TYPES = (
    CHANGE_REQUIREMENT_ADD,
    CHANGE_REQUIREMENT_TEXT,
    CHANGE_NUMERIC_LIMIT,
    CHANGE_REQUIREMENT_REMOVE,
    CHANGE_PRIORITY,
    CHANGE_VERIFICATION,
    CHANGE_PART_ALTERNATIVE,
    CHANGE_SYSTEM_ALTERNATIVE,
    CHANGE_INTERFACE,
    CHANGE_OPERATING_CONDITION,
)

SUGGESTION_CATEGORIES = (
    "Alternatif gereksinim ifadesi",
    "Alternatif parça veya tasarım yaklaşımı",
    "Geriye uyumluluk çözümü",
    "Yeni emniyet önlemi",
    "Yeni doğrulama testi",
    "Arayüz koruma yöntemi",
    "Maliyet veya takvim azaltma önerisi",
    "Gereksinimi daha ölçülebilir hâle getirme",
    "Çelişki giderme önerisi",
    "İlave müşteri sorusu",
)

LM_CALL_DEADLINE_SECONDS = 25.0

REQUIREMENT_NODE_TYPES = {
    "Müşteri/paydaş gereksinimi",
    "Sistem gereksinimi",
    "Alt sistem gereksinimi",
}
TEST_NODE_TYPES = {
    "Birim testi",
    "Entegrasyon testi",
    "Sistem doğrulama testi",
    "Müşteri kabul/geçerleme testi",
    "Doğrulama kriteri",
}
INTERFACE_NODE_TYPES = {
    "Mekanik arayüz",
    "Elektriksel arayüz",
    "Yazılımsal arayüz",
}
PART_NODE_TYPES = {"Parça/bileşen", "Yazılım birimi"}
DESIGN_NODE_TYPES = {"Tasarım kararı", "Fonksiyon"}

_CHANGE_ALIASES = {
    "gereksinim ekleme": CHANGE_REQUIREMENT_ADD,
    "requirement add": CHANGE_REQUIREMENT_ADD,
    "gereksinim metni degistirme": CHANGE_REQUIREMENT_TEXT,
    "metin degisikligi": CHANGE_REQUIREMENT_TEXT,
    "requirement text change": CHANGE_REQUIREMENT_TEXT,
    "sayisal sinir degistirme": CHANGE_NUMERIC_LIMIT,
    "sinir degisikligi": CHANGE_NUMERIC_LIMIT,
    "numeric limit change": CHANGE_NUMERIC_LIMIT,
    "gereksinim kaldirma": CHANGE_REQUIREMENT_REMOVE,
    "requirement removal": CHANGE_REQUIREMENT_REMOVE,
    "oncelik/kritiklik degistirme": CHANGE_PRIORITY,
    "oncelik degistirme": CHANGE_PRIORITY,
    "kritiklik degistirme": CHANGE_PRIORITY,
    "dogrulama yontemi degistirme": CHANGE_VERIFICATION,
    "verification method change": CHANGE_VERIFICATION,
    "parca alternatifi": CHANGE_PART_ALTERNATIVE,
    "part alternative": CHANGE_PART_ALTERNATIVE,
    "sistem durumu alternatifi": CHANGE_SYSTEM_ALTERNATIVE,
    "system state alternative": CHANGE_SYSTEM_ALTERNATIVE,
    "arayuz degisikligi": CHANGE_INTERFACE,
    "interface change": CHANGE_INTERFACE,
    "calisma kosulu degisikligi": CHANGE_OPERATING_CONDITION,
    "operating condition change": CHANGE_OPERATING_CONDITION,
}

_RELATION_BONUS = {
    "conflicts_with": 20,
    "verified_by": 12,
    "validated_by": 12,
    "interfaces_with": 11,
    "allocated_to": 10,
    "implemented_by": 10,
    "satisfies": 9,
    "depends_on": 9,
    "derives_from": 8,
    "documented_in": 0,
}
_CHANGE_BONUS = {
    CHANGE_REQUIREMENT_ADD: 6,
    CHANGE_REQUIREMENT_TEXT: 8,
    CHANGE_NUMERIC_LIMIT: 12,
    CHANGE_REQUIREMENT_REMOVE: 15,
    CHANGE_PRIORITY: 10,
    CHANGE_VERIFICATION: 10,
    CHANGE_PART_ALTERNATIVE: 10,
    CHANGE_SYSTEM_ALTERNATIVE: 12,
    CHANGE_INTERFACE: 15,
    CHANGE_OPERATING_CONDITION: 12,
}
_NUMERIC_TOKEN_RE = re.compile(
    r"(?P<number>[+-]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>%|kg|g|mg|t|mm|cm|m|km|ms|sn|s|dk|saat|°c|c|v|a|ma|w|kw|"
    r"hz|khz|mhz|ghz|rpm|db|pa|bar|bit/s|kbit/s|mbit/s|gbit/s)?",
    re.IGNORECASE,
)
_SAFETY_WORDS = {
    "emniyet", "guvenlik", "güvenlik", "tehlike", "kritik", "yangin",
    "yangın", "sicaklik", "sıcaklık", "basinc", "basınç", "acil",
}
_SUGGESTION_LABEL = "Mühendislik önerisi — kullanıcı onayı gerekli"


class SimulationError(ValueError):
    """Kullanıcıya gösterilebilecek simülasyon doğrulama hatası."""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value)).casefold()
    return "".join(char for char in text if not unicodedata.combining(char))


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _normalize_change_type(value: Any) -> str:
    normalized = _fold(value)
    if normalized in _CHANGE_ALIASES:
        return _CHANGE_ALIASES[normalized]
    for supported in SUPPORTED_CHANGE_TYPES:
        if _fold(supported) == normalized:
            return supported
    raise SimulationError(
        "Desteklenmeyen değişiklik türü. Desteklenen türler: "
        + ", ".join(SUPPORTED_CHANGE_TYPES)
        + "."
    )


def _json_ready(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value


@dataclass(frozen=True)
class ChangeRequest:
    requirement_id: str = ""
    current_value: Any = None
    proposed_value: Any = None
    reason: str = ""
    requested_by: str = ""
    change_type: str = CHANGE_REQUIREMENT_TEXT
    assumptions: tuple[str, ...] = ()
    query: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ChangeRequest":
        assumptions = value.get("assumptions", value.get("varsayimlar", ()))
        if isinstance(assumptions, str):
            assumptions = tuple(
                part.strip() for part in re.split(r"[;\n]+", assumptions) if part.strip()
            )
        else:
            assumptions = tuple(_clean(item) for item in (assumptions or ()) if _clean(item))
        return cls(
            requirement_id=_clean(
                value.get("requirement_id", value.get("gereksinim_kimligi", value.get("target_id", "")))
            ),
            current_value=value.get("current_value", value.get("mevcut_deger", value.get("current_text"))),
            proposed_value=value.get("proposed_value", value.get("yeni_deger", value.get("proposed_text"))),
            reason=_clean(value.get("reason", value.get("degisiklik_nedeni", ""))),
            requested_by=_clean(value.get("requested_by", value.get("isteyen_taraf", ""))),
            change_type=_normalize_change_type(
                value.get("change_type", value.get("degisiklik_turu", ""))
            ),
            assumptions=assumptions,
            query=_clean(value.get("query", value.get("search_text", value.get("sorgu", "")))),
        )

    def validated(self) -> "ChangeRequest":
        change_type = _normalize_change_type(self.change_type)
        if not self.reason:
            raise SimulationError("Değişiklik nedeni boş bırakılamaz.")
        if not self.requested_by:
            raise SimulationError("Değişikliği isteyen taraf boş bırakılamaz.")
        if change_type != CHANGE_REQUIREMENT_ADD and not self.requirement_id and not self.query:
            raise SimulationError(
                "Gereksinim/öğe kimliği veya arama metni girilmelidir."
            )
        if change_type != CHANGE_REQUIREMENT_REMOVE and _is_blank(self.proposed_value):
            raise SimulationError("Önerilen yeni metin veya değer boş bırakılamaz.")
        return replace(self, change_type=change_type)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True)
class ImpactPath:
    path_id: str
    source_id: str
    target_id: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    relationships: tuple[str, ...]
    traversal_directions: tuple[str, ...]
    depth: int
    confidence_level: str
    confidence: float
    classification: str
    display_path: str

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True)
class ImpactItem:
    item_id: str
    node_type: str
    title: str
    categories: tuple[str, ...]
    direct: bool
    distance: int
    impact_level: str
    impact_score: int
    probability: int
    severity: int
    risk_score: int
    confidence_level: str
    confidence: float
    score_status: str
    rationale: str
    source_evidence: str
    traceability_path: ImpactPath

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True)
class RiskItem:
    category: str
    impact_level: str
    probability: int
    severity: int
    risk_score: int
    confidence_level: str
    rationale: str
    impacted_items: tuple[str, ...]
    source_evidence: str

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True)
class EngineeringSuggestion:
    suggestion_id: str
    category: str
    suggestion: str
    rationale: str
    expected_benefit: str
    new_risk: str
    affected_items: tuple[str, ...]
    required_verification: str
    source_or_assumption: str
    status: str = _SUGGESTION_LABEL

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass
class SimulationResult:
    status: str
    message: str
    change_request: ChangeRequest
    selected_item: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    impact_paths: list[ImpactPath] = field(default_factory=list)
    impacts: list[ImpactItem] = field(default_factory=list)
    categorized_impacts: dict[str, Any] = field(default_factory=dict)
    risks: list[RiskItem] = field(default_factory=list)
    engineering_suggestions: list[EngineeringSuggestion] = field(default_factory=list)
    ai_facts: list[dict[str, Any]] = field(default_factory=list)
    ai_inferences: list[dict[str, Any]] = field(default_factory=list)
    v_model_analysis: dict[str, Any] = field(default_factory=dict)
    numeric_change: dict[str, Any] | None = None
    scoring_method: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    lm_status: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


def load_traceability(
    source: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Part 1 haritasını sözlükten veya JSON dosyasından doğrulayarak yükler."""
    if isinstance(source, Mapping):
        report = dict(source)
    else:
        path = Path(source)
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise SimulationError(f"İzlenebilirlik dosyası bulunamadı: {path}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise SimulationError(f"İzlenebilirlik dosyası okunamadı: {error}") from error
    if not isinstance(report.get("nodes"), list) or not isinstance(report.get("edges"), list):
        raise SimulationError("İzlenebilirlik verisinde 'nodes' ve 'edges' listeleri bulunmalıdır.")
    return report


def _node_index(report: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    by_id: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for raw in report.get("nodes", []):
        if not isinstance(raw, Mapping):
            continue
        node_id = _clean(raw.get("id"))
        if not node_id or node_id in by_id:
            continue
        node = dict(raw)
        by_id[node_id] = node
        candidate_aliases = [node_id, raw.get("canonical_id"), *(raw.get("aliases") or [])]
        for alias in candidate_aliases:
            normalized = normalize_identifier(alias)
            if normalized and normalized not in aliases:
                aliases[normalized] = node_id
    return by_id, aliases


def _eligible_target(node: Mapping[str, Any], change_type: str) -> bool:
    node_type = _clean(node.get("node_type"))
    if node_type == "Teknik belge":
        return False
    if change_type == CHANGE_PART_ALTERNATIVE:
        return node_type in PART_NODE_TYPES
    if change_type == CHANGE_INTERFACE:
        return node_type in INTERFACE_NODE_TYPES
    if change_type in {
        CHANGE_REQUIREMENT_ADD,
        CHANGE_REQUIREMENT_TEXT,
        CHANGE_NUMERIC_LIMIT,
        CHANGE_REQUIREMENT_REMOVE,
        CHANGE_PRIORITY,
        CHANGE_VERIFICATION,
    }:
        return node_type in REQUIREMENT_NODE_TYPES
    return True


def _default_rag_search(query: str, k: int = 5) -> Sequence[Any]:
    from rag_handler import rag_handler

    return rag_handler.query_knowledge_base(query, k=k)


def _rag_result_content(item: Any) -> tuple[str, float]:
    score = 0.0
    document = item
    if isinstance(item, tuple) and len(item) >= 2:
        document, raw_score = item[0], item[1]
        try:
            score = max(0.0, min(1.0, float(raw_score)))
        except (TypeError, ValueError):
            score = 0.0
    if isinstance(document, Mapping):
        content = _clean(document.get("page_content", document.get("content", "")))
    else:
        content = _clean(getattr(document, "page_content", document))
    return content, score


def find_requirement_candidates(
    traceability: Mapping[str, Any] | str | Path,
    query: str,
    *,
    change_type: str = CHANGE_REQUIREMENT_TEXT,
    rag_search: Callable[..., Sequence[Any]] | None = None,
    use_existing_rag: bool = True,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Serbest metni gerçek düğümlerle eşleştirir; en fazla beş aday döndürür."""
    report = load_traceability(traceability)
    nodes, aliases = _node_index(report)
    change_type = _normalize_change_type(change_type)
    query = _clean(query)
    if not query:
        return []

    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    for identifier in extract_identifiers(query):
        matched = aliases.get(normalize_identifier(identifier))
        if matched and _eligible_target(nodes[matched], change_type):
            scores[matched] = 1.0
            sources.setdefault(matched, set()).add("Kesin kimlik")

    folded_query = _fold(query)
    query_tokens = set(re.findall(r"[a-z0-9çğıöşü]+", folded_query))
    for node_id, node in nodes.items():
        if not _eligible_target(node, change_type):
            continue
        composite = " ".join(
            _clean(node.get(key))
            for key in ("id", "title", "description", "evidence_text", "source_document")
        )
        score = semantic_similarity(query, composite)
        folded_composite = _fold(composite)
        if folded_query and folded_query in folded_composite:
            score = max(score, 0.9)
        elif query_tokens:
            overlap = len(query_tokens & set(re.findall(r"[a-z0-9çğıöşü]+", folded_composite)))
            score = max(score, min(0.8, overlap / max(1, len(query_tokens))))
        if score > scores.get(node_id, 0.0):
            scores[node_id] = score
        if score > 0:
            sources.setdefault(node_id, set()).add("İzlenebilirlik metni")

    search = rag_search
    if search is None and use_existing_rag:
        search = _default_rag_search
    if search is not None:
        try:
            try:
                rag_results = search(query, k=limit)
            except TypeError:
                rag_results = search(query, limit)
            for raw_result in rag_results or ():
                content, rag_score = _rag_result_content(raw_result)
                for identifier in extract_identifiers(content):
                    matched = aliases.get(normalize_identifier(identifier))
                    if matched and _eligible_target(nodes[matched], change_type):
                        boosted = min(1.0, 0.55 + (rag_score * 0.4))
                        scores[matched] = max(scores.get(matched, 0.0), boosted)
                        sources.setdefault(matched, set()).add("RAG")
        except Exception:
            # RAG hatası deterministik izlenebilirlik aramasını engellemez.
            pass

    ranked = sorted(
        (
            (score, node_id)
            for node_id, score in scores.items()
            if score >= 0.08 and _eligible_target(nodes[node_id], change_type)
        ),
        key=lambda item: (-item[0], item[1]),
    )[: max(1, min(5, int(limit)))]
    return [
        {
            "id": node_id,
            "title": _clean(nodes[node_id].get("title")) or node_id,
            "description": _clean(nodes[node_id].get("description")),
            "node_type": _clean(nodes[node_id].get("node_type")),
            "score": round(score, 4),
            "match_source": sorted(sources.get(node_id, {"İzlenebilirlik metni"})),
        }
        for score, node_id in ranked
    ]


def _resolve_target(
    report: Mapping[str, Any],
    request: ChangeRequest,
    *,
    selected_id: str | None,
    rag_search: Callable[..., Sequence[Any]] | None,
    use_existing_rag: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    nodes, aliases = _node_index(report)
    explicit = _clean(selected_id or request.requirement_id)
    if explicit:
        matched = aliases.get(normalize_identifier(explicit))
        if not matched:
            if request.change_type == CHANGE_REQUIREMENT_ADD and selected_id is None:
                return None, []
            raise SimulationError(
                f"İzlenebilirlik haritasında '{explicit}' kimliği bulunamadı."
            )
        node = nodes[matched]
        if not _eligible_target(node, request.change_type):
            raise SimulationError(
                f"'{explicit}' öğesi '{request.change_type}' değişikliği için uygun türde değildir."
            )
        return node, [{
            "id": matched,
            "title": _clean(node.get("title")) or matched,
            "description": _clean(node.get("description")),
            "node_type": _clean(node.get("node_type")),
            "score": 1.0,
            "match_source": ["Kesin kimlik"],
        }]

    search_text = request.query or _clean(request.current_value) or _clean(request.proposed_value)
    candidates = find_requirement_candidates(
        report,
        search_text,
        change_type=request.change_type,
        rag_search=rag_search,
        use_existing_rag=use_existing_rag,
        limit=5,
    )
    if not candidates:
        raise SimulationError("Girilen metinle eşleşen bir gereksinim veya öğe bulunamadı.")
    if len(candidates) == 1 and candidates[0]["score"] >= 0.22:
        return nodes[candidates[0]["id"]], candidates
    if (
        candidates[0]["score"] >= 0.82
        and candidates[0]["score"] - candidates[1]["score"] >= 0.18
    ):
        return nodes[candidates[0]["id"]], candidates
    return None, candidates


def _edge_confidence(edge: Mapping[str, Any]) -> float:
    try:
        confidence = float(edge.get("confidence"))
        return max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        return {
            CONFIDENCE_EXACT: 1.0,
            CONFIDENCE_SUGGESTED: 0.72,
            CONFIDENCE_INFERRED: 0.55,
        }.get(_clean(edge.get("confidence_level")), 0.5)


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.9:
        return CONFIDENCE_EXACT
    if confidence >= 0.65:
        return CONFIDENCE_SUGGESTED
    return CONFIDENCE_INFERRED


def _path_identifier(node_ids: Sequence[str], relationships: Sequence[str]) -> str:
    payload = "|".join(node_ids) + "::" + "|".join(relationships)
    return "PATH-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:14].upper()


def _classify_path(
    node: Mapping[str, Any], relationships: Sequence[str], directions: Sequence[str]
) -> tuple[str, tuple[str, ...]]:
    distance = len(relationships)
    node_type = _clean(node.get("node_type"))
    categories: list[str] = []
    if distance == 1:
        categories.append("Doğrudan etki")
    if node_type in REQUIREMENT_NODE_TYPES and relationships and all(
        relation == "derives_from" for relation in relationships
    ):
        if all(direction == "forward" for direction in directions):
            categories.append("Üst gereksinim etkisi")
        elif all(direction == "reverse" for direction in directions):
            categories.append("Alt gereksinim etkisi")
    if distance == 2:
        categories.append("İkinci derece etki")
    elif distance >= 3:
        categories.append("Zincirleme etki")
    if "conflicts_with" in relationships:
        categories.append("Çelişen gereksinim")
    if node_type in PART_NODE_TYPES:
        categories.append("Etkilenen parça")
    if node_type in INTERFACE_NODE_TYPES:
        categories.append("Etkilenen arayüz")
    if node_type in DESIGN_NODE_TYPES:
        categories.append("Etkilenen tasarım kararı")
    if node_type in TEST_NODE_TYPES:
        categories.append("Etkilenen doğrulama/geçerleme")
    if node_type == "Teknik belge":
        categories.append("Etkilenen belge")
    if not categories:
        categories.append("Dolaylı etki")
    return categories[0], tuple(dict.fromkeys(categories))


def _build_paths(
    report: Mapping[str, Any], source_id: str, max_depth: int
) -> tuple[list[ImpactPath], list[str]]:
    nodes, _ = _node_index(report)
    warnings: list[str] = []
    adjacency: dict[str, list[tuple[str, dict[str, Any], str]]] = {
        node_id: [] for node_id in nodes
    }
    for index, raw in enumerate(report.get("edges", []), start=1):
        if not isinstance(raw, Mapping):
            continue
        edge = dict(raw)
        left = _clean(edge.get("source_id"))
        right = _clean(edge.get("target_id"))
        if left not in nodes or right not in nodes:
            warnings.append(
                f"Bilinmeyen düğüme bağlı ilişki atlandı: {left or '?'} → {right or '?'}"
            )
            continue
        edge.setdefault("id", f"EDGE-LOCAL-{index:04d}")
        edge.setdefault("relationship_type", "depends_on")
        adjacency[left].append((right, edge, "forward"))
        adjacency[right].append((left, edge, "reverse"))
    for neighbors in adjacency.values():
        neighbors.sort(
            key=lambda item: (
                item[0], _clean(item[1].get("relationship_type")), _clean(item[1].get("id"))
            )
        )

    queue: deque[tuple[str, tuple[str, ...], tuple[dict[str, Any], ...], tuple[str, ...]]] = deque()
    queue.append((source_id, (source_id,), (), ()))
    best_depth: dict[str, int] = {source_id: 0}
    results: list[ImpactPath] = []
    while queue:
        current, node_path, edge_path, directions = queue.popleft()
        depth = len(edge_path)
        if depth >= max_depth:
            continue
        for neighbor, edge, traversal in adjacency.get(current, []):
            if neighbor in node_path:
                continue
            new_nodes = (*node_path, neighbor)
            new_edges = (*edge_path, edge)
            new_directions = (*directions, traversal)
            new_depth = len(new_edges)
            previous_depth = best_depth.get(neighbor)
            if previous_depth is not None and previous_depth <= new_depth:
                continue
            best_depth[neighbor] = new_depth
            relationships = tuple(_clean(item.get("relationship_type")) for item in new_edges)
            confidence = min((_edge_confidence(item) for item in new_edges), default=1.0)
            classification, _ = _classify_path(nodes[neighbor], relationships, new_directions)
            results.append(ImpactPath(
                path_id=_path_identifier(new_nodes, relationships),
                source_id=source_id,
                target_id=neighbor,
                node_ids=new_nodes,
                edge_ids=tuple(_clean(item.get("id")) for item in new_edges),
                relationships=relationships,
                traversal_directions=new_directions,
                depth=new_depth,
                confidence_level=_confidence_label(confidence),
                confidence=round(confidence, 4),
                classification=classification,
                display_path=" → ".join(new_nodes),
            ))
            if _clean(nodes[neighbor].get("node_type")) != "Teknik belge":
                queue.append((neighbor, new_nodes, new_edges, new_directions))
    return sorted(results, key=lambda item: (item.depth, item.target_id)), list(dict.fromkeys(warnings))


def _numeric_value(value: Any) -> tuple[float | None, str]:
    if isinstance(value, bool) or value is None:
        return None, ""
    if isinstance(value, (int, float)):
        return float(value), ""
    match = _NUMERIC_TOKEN_RE.search(_clean(value))
    if not match:
        return None, ""
    return float(match.group("number").replace(",", ".")), _clean(match.group("unit")).casefold()


def _analyze_numeric_change(
    request: ChangeRequest, target: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    current, current_unit = _numeric_value(request.current_value)
    proposed, proposed_unit = _numeric_value(request.proposed_value)
    if current is None or proposed is None:
        raise SimulationError(
            "Sayısal sınır değişikliği için mevcut ve önerilen sayısal değerler gereklidir."
        )
    if current_unit and proposed_unit and current_unit != proposed_unit:
        raise SimulationError(
            f"Mevcut ve önerilen değerlerin birimleri uyuşmuyor: {current_unit} / {proposed_unit}."
        )
    difference = proposed - current
    percent = None if current == 0 else (difference / abs(current)) * 100.0
    warnings: list[str] = []
    evidence_values = [
        parameter.get("value")
        for parameter in target.get("technical_parameters", [])
        if isinstance(parameter, Mapping)
    ]
    if evidence_values and not any(
        isinstance(value, (int, float)) and abs(float(value) - current) < 1e-9
        for value in evidence_values
    ):
        warnings.append(
            "Girilen mevcut sayısal değer, hedef düğümde çıkarılmış teknik değerlerle eşleşmedi; güven düşürüldü."
        )
    return {
        "current": current,
        "proposed": proposed,
        "unit": proposed_unit or current_unit or None,
        "absolute_change": round(difference, 6),
        "percentage_change": None if percent is None else round(percent, 4),
        "direction": "artış" if difference > 0 else "azalış" if difference < 0 else "değişiklik yok",
    }, warnings


def _impact_level(score: int) -> str:
    if score >= 80:
        return "Kritik"
    if score >= 55:
        return "Yüksek"
    if score >= 30:
        return "Orta"
    return "Düşük"


def _risk_level(score: int) -> str:
    if score >= 17:
        return "Kritik"
    if score >= 10:
        return "Yüksek"
    if score >= 5:
        return "Orta"
    return "Düşük"


def _node_bonus(node_type: str) -> int:
    if node_type == "Risk":
        return 15
    if node_type in INTERFACE_NODE_TYPES or node_type in PART_NODE_TYPES:
        return 10
    if node_type in TEST_NODE_TYPES:
        return 9
    if node_type in REQUIREMENT_NODE_TYPES or node_type in DESIGN_NODE_TYPES:
        return 8
    if node_type == "Teknik belge":
        return 2
    return 5


def _severity(node_type: str, change_type: str) -> int:
    base = 2
    if node_type in REQUIREMENT_NODE_TYPES:
        base = 3
    if node_type in PART_NODE_TYPES or node_type in INTERFACE_NODE_TYPES:
        base = 4
    if node_type in {"Sistem doğrulama testi", "Müşteri kabul/geçerleme testi", "Risk"}:
        base = 4
    if change_type in {CHANGE_REQUIREMENT_REMOVE, CHANGE_INTERFACE}:
        base += 1
    return max(1, min(5, base))


def _path_evidence(
    report: Mapping[str, Any], path: ImpactPath, node: Mapping[str, Any]
) -> str:
    edge_ids = set(path.edge_ids)
    pieces = [
        _clean(edge.get("evidence_text"))
        for edge in report.get("edges", [])
        if isinstance(edge, Mapping) and _clean(edge.get("id")) in edge_ids
        and _clean(edge.get("evidence_text"))
    ]
    node_evidence = _clean(node.get("evidence_text") or node.get("description"))
    if node_evidence:
        pieces.append(node_evidence)
    return " | ".join(dict.fromkeys(pieces))[:1000]


def _build_impact_items(
    report: Mapping[str, Any],
    request: ChangeRequest,
    paths: Sequence[ImpactPath],
    numeric_change: Mapping[str, Any] | None,
    *,
    lower_confidence: bool,
) -> list[ImpactItem]:
    nodes, _ = _node_index(report)
    items: list[ImpactItem] = []
    numeric_bonus = 0
    if numeric_change and numeric_change.get("percentage_change") is not None:
        numeric_bonus = min(15, int(round(abs(float(numeric_change["percentage_change"])) / 5)))
    for path in paths:
        node = nodes[path.target_id]
        node_type = _clean(node.get("node_type"))
        _, categories = _classify_path(node, path.relationships, path.traversal_directions)
        base = 70 if path.depth == 1 else 50 if path.depth == 2 else max(22, 43 - ((path.depth - 3) * 6))
        relation_bonus = max((_RELATION_BONUS.get(relation, 5) for relation in path.relationships), default=0)
        raw_score = (
            base
            + relation_bonus
            + _node_bonus(node_type)
            + _CHANGE_BONUS[request.change_type]
            + numeric_bonus
        )
        confidence = path.confidence
        evidence = _path_evidence(report, path, node)
        evidence_complete = bool(evidence and _clean(node.get("source_document")))
        if not evidence_complete or lower_confidence:
            confidence = min(confidence, 0.62)
        score = int(round(max(0, min(100, raw_score * (0.78 + (0.22 * confidence))))))
        probability = max(1, min(5, ceil(score / 20)))
        severity = _severity(node_type, request.change_type)
        risk_score = probability * severity
        relation_text = ", ".join(path.relationships)
        rationale = (
            f"{path.depth} adımlı grafik yolu ({relation_text}) deterministik olarak izlendi. "
            f"Değişiklik türü ve '{node_type}' öğe türü puana dahil edildi."
        )
        items.append(ImpactItem(
            item_id=path.target_id,
            node_type=node_type,
            title=_clean(node.get("title")) or path.target_id,
            categories=categories,
            direct=path.depth == 1,
            distance=path.depth,
            impact_level=_impact_level(score),
            impact_score=score,
            probability=probability,
            severity=severity,
            risk_score=risk_score,
            confidence_level=_confidence_label(confidence),
            confidence=round(confidence, 4),
            score_status="Kesin kurallı hesap" if evidence_complete and not lower_confidence else "Tahmini — eksik veri/güven düşürüldü",
            rationale=rationale,
            source_evidence=evidence or "Kaynak kanıtı eksik.",
            traceability_path=path,
        ))
    return sorted(items, key=lambda item: (-item.impact_score, item.distance, item.item_id))


def _empty_categories() -> dict[str, Any]:
    return {
        "direct_impacts": [],
        "upper_requirement_impacts": [],
        "lower_requirement_impacts": [],
        "second_degree_impacts": [],
        "cascade_impacts": [],
        "conflicting_requirements": [],
        "affected_parts": [],
        "affected_interfaces": [],
        "affected_design_decisions": [],
        "affected_verification_validation": [],
        "potentially_invalid_tests": [],
        "new_or_updated_tests": [],
        "affected_documents": [],
    }


def _categorize_impacts(
    request: ChangeRequest,
    selected: Mapping[str, Any] | None,
    impacts: Sequence[ImpactItem],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    categories = _empty_categories()
    for impact in impacts:
        value = impact.to_dict()
        names = set(impact.categories)
        if impact.direct:
            categories["direct_impacts"].append(value)
        if "Üst gereksinim etkisi" in names:
            categories["upper_requirement_impacts"].append(value)
        if "Alt gereksinim etkisi" in names:
            categories["lower_requirement_impacts"].append(value)
        if impact.distance == 2:
            categories["second_degree_impacts"].append(value)
        if impact.distance >= 3:
            categories["cascade_impacts"].append(value)
        if "Çelişen gereksinim" in names:
            categories["conflicting_requirements"].append(value)
        if impact.node_type in PART_NODE_TYPES:
            categories["affected_parts"].append(value)
        if impact.node_type in INTERFACE_NODE_TYPES:
            categories["affected_interfaces"].append(value)
        if impact.node_type in DESIGN_NODE_TYPES:
            categories["affected_design_decisions"].append(value)
        if impact.node_type in TEST_NODE_TYPES:
            categories["affected_verification_validation"].append(value)
            validity = (
                "Geçersiz kalabilir"
                if request.change_type == CHANGE_REQUIREMENT_REMOVE
                else "Yeniden doğrulama gerekli"
            )
            test_action = {
                "test_id": impact.item_id,
                "status": validity,
                "reason": f"Test, {impact.traceability_path.display_path} yolu üzerinden değişiklikten etkileniyor.",
                "path": impact.traceability_path.to_dict(),
            }
            categories["potentially_invalid_tests"].append(test_action)
            categories["new_or_updated_tests"].append({
                **test_action,
                "required_action": "Test yöntemi, girdileri ve kabul kriterleri güncellenip yeniden çalıştırılmalı.",
            })
        if impact.node_type == "Teknik belge":
            categories["affected_documents"].append(value)

    selected_id = _clean((selected or {}).get("id"))
    direct_test_edges = [
        edge for edge in report.get("edges", [])
        if isinstance(edge, Mapping)
        and _clean(edge.get("source_id")) == selected_id
        and _clean(edge.get("relationship_type")) in {"verified_by", "validated_by"}
    ]
    if request.change_type == CHANGE_REQUIREMENT_ADD or (
        selected and _clean(selected.get("node_type")) in REQUIREMENT_NODE_TYPES and not direct_test_edges
    ):
        categories["new_or_updated_tests"].append({
            "test_id": None,
            "status": "Yeni test gerekli",
            "reason": "Değiştirilen gereksinime doğrudan bağlı doğrulama/geçerleme kaydı bulunamadı.",
            "required_action": "Doğrulama yöntemi, kabul kriteri ve uygun V-Model test seviyesi tanımlanmalı.",
            "path": None,
        })

    relevant_conflicts = []
    for conflict in report.get("conflicts", []):
        if not isinstance(conflict, Mapping):
            continue
        serialized = json.dumps(conflict, ensure_ascii=False)
        if not selected_id or selected_id in serialized:
            relevant_conflicts.append(dict(conflict))
    if relevant_conflicts:
        categories["conflicting_requirements"].extend(relevant_conflicts)
    return categories


def _risk_item(
    category: str,
    probability: int,
    severity: int,
    impacts: Sequence[ImpactItem],
    rationale: str,
) -> RiskItem:
    risk_score = max(1, min(5, probability)) * max(1, min(5, severity))
    confidence = min((impact.confidence for impact in impacts), default=0.55)
    impacted_ids = tuple(dict.fromkeys(impact.item_id for impact in impacts))
    evidence = " | ".join(
        dict.fromkeys(impact.source_evidence for impact in impacts if impact.source_evidence)
    )[:800]
    return RiskItem(
        category=category,
        impact_level=_risk_level(risk_score),
        probability=max(1, min(5, probability)),
        severity=max(1, min(5, severity)),
        risk_score=risk_score,
        confidence_level=_confidence_label(confidence),
        rationale=rationale,
        impacted_items=impacted_ids,
        source_evidence=evidence or "Doğrudan kaynak kanıtı sınırlı; risk ihtiyatlı değerlendirilmiştir.",
    )


def _build_risks(
    request: ChangeRequest,
    impacts: Sequence[ImpactItem],
    selected: Mapping[str, Any] | None,
) -> list[RiskItem]:
    if not impacts and request.change_type != CHANGE_REQUIREMENT_ADD:
        return []
    by_type = lambda accepted: [item for item in impacts if item.node_type in accepted]
    requirements = by_type(REQUIREMENT_NODE_TYPES)
    tests = by_type(TEST_NODE_TYPES)
    parts_design = by_type(PART_NODE_TYPES | DESIGN_NODE_TYPES)
    interfaces = by_type(INTERFACE_NODE_TYPES)
    documents = by_type({"Teknik belge"})
    base_probability = max((item.probability for item in impacts), default=2)
    risks: list[RiskItem] = []
    if parts_design:
        risks.append(_risk_item(
            "Maliyet",
            max(2, base_probability - 1),
            3,
            parts_design,
            "Parça veya tasarım etkisi; yeniden tedarik, mühendislik ya da uyarlama maliyeti oluşturabilir.",
        ))
    schedule_impacts = [*requirements, *tests, *documents]
    if schedule_impacts or request.change_type == CHANGE_REQUIREMENT_ADD:
        risks.append(_risk_item(
            "Takvim",
            max(2, base_probability),
            3 if request.change_type != CHANGE_REQUIREMENT_REMOVE else 4,
            schedule_impacts,
            "Gereksinim ve test güncellemeleri inceleme, yeniden doğrulama ve onay takvimini etkileyebilir.",
        ))
    safety_text = _fold(
        " ".join((
            _clean(request.current_value),
            _clean(request.proposed_value),
            _clean((selected or {}).get("description")),
        ))
    )
    safety_relevant = any(word in safety_text for word in _SAFETY_WORDS) or request.change_type in {
        CHANGE_REQUIREMENT_REMOVE,
        CHANGE_NUMERIC_LIMIT,
        CHANGE_INTERFACE,
        CHANGE_OPERATING_CONDITION,
    }
    if safety_relevant:
        relevant = [*requirements, *tests, *interfaces]
        risks.append(_risk_item(
            "Emniyet",
            max(2, base_probability - (0 if request.change_type == CHANGE_REQUIREMENT_REMOVE else 1)),
            4 if request.change_type != CHANGE_REQUIREMENT_REMOVE else 5,
            relevant,
            "Sınır, arayüz, çalışma koşulu veya gereksinim kapsamındaki değişiklik emniyet kanıtlarını etkileyebilir.",
        ))
    reliability_relevant = [*parts_design, *interfaces, *tests]
    if reliability_relevant or request.change_type in {
        CHANGE_NUMERIC_LIMIT,
        CHANGE_PART_ALTERNATIVE,
        CHANGE_SYSTEM_ALTERNATIVE,
        CHANGE_INTERFACE,
        CHANGE_OPERATING_CONDITION,
    }:
        risks.append(_risk_item(
            "Güvenilirlik",
            max(2, base_probability - 1),
            4,
            reliability_relevant,
            "Parça, arayüz, sınır veya çalışma koşulu değişikliği güvenilirlik varsayımlarını ve test kapsamını etkileyebilir.",
        ))
    return risks


def _vmodel_analysis(
    selected: Mapping[str, Any] | None,
    impacts: Sequence[ImpactItem],
    categories: Mapping[str, Any],
) -> dict[str, Any]:
    all_nodes: list[tuple[str, str]] = []
    if selected:
        all_nodes.append((_clean(selected.get("id")), _clean(selected.get("node_type"))))
    all_nodes.extend((item.item_id, item.node_type) for item in impacts)

    def ids(node_types: set[str]) -> list[str]:
        return list(dict.fromkeys(node_id for node_id, node_type in all_nodes if node_type in node_types))

    customer = ids({"Müşteri/paydaş gereksinimi"})
    system = ids({"Sistem gereksinimi"})
    subsystem = ids({"Alt sistem gereksinimi"})
    architecture = ids(DESIGN_NODE_TYPES | PART_NODE_TYPES | INTERFACE_NODE_TYPES)
    unit_tests = ids({"Birim testi"})
    integration = ids({"Entegrasyon testi"})
    system_tests = ids({"Sistem doğrulama testi"})
    acceptance = ids({"Müşteri kabul/geçerleme testi"})
    test_actions = categories.get("potentially_invalid_tests", [])
    return {
        "left_leg": {
            "customer_requirement_update": {"required": bool(customer), "items": customer},
            "system_requirement_update": {"required": bool(system), "items": system},
            "subsystem_requirement_update": {"required": bool(subsystem), "items": subsystem},
            "architecture_design_part_interface_impact": {"affected": bool(architecture), "items": architecture},
        },
        "right_leg": {
            "unit_tests_update": {"required": bool(unit_tests), "items": unit_tests},
            "integration_tests_update": {"required": bool(integration), "items": integration},
            "system_verification_tests_update": {"required": bool(system_tests), "items": system_tests},
            "acceptance_validation_update": {"required": bool(acceptance), "items": acceptance},
            "existing_test_result_validity": {
                "status": "Yeniden değerlendirme gerekli" if test_actions else "Doğrudan bağlı test sonucu bulunamadı",
                "tests": test_actions,
            },
        },
    }


def _scoring_method() -> dict[str, Any]:
    return {
        "calculated_by": "Python — deterministik",
        "impact_score_formula": (
            "mesafe tabanı (1 adım=70, 2 adım=50, 3+=43'ten azalan) + "
            "ilişki katsayısı (0–20) + öğe türü katsayısı (2–15) + "
            "değişiklik türü katsayısı (6–15) + sayısal değişim katsayısı (0–15); "
            "yol güveniyle 0,78–1,00 çarpanı uygulanır ve sonuç 0–100'e kırpılır."
        ),
        "impact_levels": {"0-29": "Düşük", "30-54": "Orta", "55-79": "Yüksek", "80-100": "Kritik"},
        "probability": "Etki puanı / 20 yukarı yuvarlanır; 1–5 aralığına kırpılır.",
        "severity": "Öğe türü ve değişiklik türü için sabit mühendislik matrisi; 1–5.",
        "risk_score": "Olasılık × Şiddet (1–25).",
        "risk_levels": {"1-4": "Düşük", "5-9": "Orta", "10-16": "Yüksek", "17-25": "Kritik"},
        "confidence_rule": (
            "Yoldaki en düşük kaynak güveni kullanılır. Kaynak/kanıt veya teknik veri eksikse "
            "güven en fazla 0,62 olur ve puan 'Tahmini' olarak işaretlenir."
        ),
        "model_rule": "LM Studio bu puanların hiçbirini hesaplayamaz veya değiştiremez.",
    }


def _model_prompt(
    report: Mapping[str, Any], result: SimulationResult
) -> str:
    nodes, _ = _node_index(report)
    allowed = {
        node_id: {
            "type": _clean(node.get("node_type")),
            "description": _clean(node.get("description"))[:400],
            "evidence": _clean(node.get("evidence_text"))[:300],
        }
        for node_id, node in nodes.items()
    }
    compact_impacts = [
        {
            "item_id": item.item_id,
            "path": item.traceability_path.display_path,
            "impact_score": item.impact_score,
            "risk_score": item.risk_score,
            "evidence": item.source_evidence[:300],
        }
        for item in result.impacts[:30]
    ]
    schema = {
        "facts": [{"item_id": "GERÇEK_KİMLİK", "statement": "", "source_evidence": ""}],
        "inferences": [{"item_id": "GERÇEK_KİMLİK", "statement": "", "assumption": ""}],
        "suggestions": [{
            "category": "İZİNLİ_KATEGORİ",
            "suggestion": "",
            "rationale": "",
            "expected_benefit": "",
            "new_risk": "",
            "affected_items": ["GERÇEK_KİMLİK"],
            "required_verification": "",
            "source_or_assumption": "",
        }],
    }
    return (
        "Yalnızca geçerli JSON üret. Markdown kullanma. Gerçek kimlikleri değiştirme veya yeni kimlik üretme. "
        "İzin listesindeki kimlikler dışında kimlik kullanma. Kaynaksız teknik/sayısal değer üretme. "
        "impact_score, risk_score, probability veya severity alanı üretme; Python hesaplarını değiştirme. "
        "Kesin bilgiyi facts, çıkarımı inferences, öneriyi suggestions altında ayrı tut. "
        f"Öneri kategorileri yalnızca şunlar olabilir: {json.dumps(SUGGESTION_CATEGORIES, ensure_ascii=False)}.\n"
        f"JSON şeması: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Değişiklik: {json.dumps(result.change_request.to_dict(), ensure_ascii=False)}\n"
        f"Seçilen öğe: {json.dumps(result.selected_item, ensure_ascii=False)}\n"
        f"Deterministik etkiler: {json.dumps(compact_impacts, ensure_ascii=False)}\n"
        f"İzinli gerçek düğümler ve kanıtları: {json.dumps(allowed, ensure_ascii=False)}"
    )


def _default_lm_call(prompt: str) -> str:
    import requests
    from config import LMSTUDIO_API_KEY, LMSTUDIO_BASE_URL, MODEL_NAME
    from lmstudio_model import get_active_model_name

    active_model = get_active_model_name(MODEL_NAME)

    response = requests.post(
        f"{LMSTUDIO_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {LMSTUDIO_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": active_model,
            "messages": [
                {
                    "role": "system",
                    "content": "Kanıta dayalı sistem mühendisisin. Yalnızca istenen JSON'u üret.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2400,
            "temperature": 0.2,
            "stream": False,
        },
        timeout=(3.05, 15),
    )
    response.raise_for_status()
    payload = response.json()
    return payload["choices"][0]["message"]["content"]


def _call_with_deadline(
    caller: Callable[[str], Any], prompt: str,
    timeout_seconds: float = LM_CALL_DEADLINE_SECONDS,
) -> Any:
    """Yavaş veri akışından bağımsız, LM çağrısına kesin toplam süre sınırı uygular."""
    response_queue: thread_queue.Queue[tuple[str, Any]] = thread_queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            response_queue.put(("result", caller(prompt)))
        except Exception as error:
            response_queue.put(("error", error))

    threading.Thread(target=invoke, daemon=True).start()
    try:
        kind, value = response_queue.get(timeout=max(0.01, float(timeout_seconds)))
    except thread_queue.Empty as error:
        raise TimeoutError(
            f"LM Studio {float(timeout_seconds):.0f} saniye içinde yanıt vermedi."
        ) from error
    if kind == "error":
        raise value
    return value


def _extract_json_payload(text: Any) -> dict[str, Any]:
    raw = _clean(text)
    if not raw:
        raise ValueError("Model boş yanıt verdi.")
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Model yanıtında JSON nesnesi bulunamadı.")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Model yanıtının kökü JSON nesnesi olmalıdır.")
    return payload


def _contains_forbidden_score_fields(value: Any) -> bool:
    forbidden = {"impact_score", "risk_score", "probability", "severity", "etki_puani", "risk_puani"}
    if isinstance(value, Mapping):
        return any(
            _fold(key).replace(" ", "_") in forbidden or _contains_forbidden_score_fields(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_score_fields(item) for item in value)
    return False


def _numbers_in(value: Any) -> set[str]:
    return {match.group("number").replace(",", ".") for match in _NUMERIC_TOKEN_RE.finditer(_clean(value))}


def _validate_model_payload(
    payload: Mapping[str, Any],
    report: Mapping[str, Any],
    request: ChangeRequest,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[EngineeringSuggestion], list[str]]:
    if _contains_forbidden_score_fields(payload):
        raise SimulationError("Model hesaplanan puan alanlarını değiştirmeye çalıştı; yanıt reddedildi.")
    nodes, aliases = _node_index(report)
    allowed_ids = set(nodes)
    allowed_numbers = _numbers_in(json.dumps(report, ensure_ascii=False))
    allowed_numbers.update(_numbers_in(request.current_value))
    allowed_numbers.update(_numbers_in(request.proposed_value))
    warnings: list[str] = []

    def validated_statements(key: str, required_detail: str) -> list[dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        for raw in payload.get(key, []) if isinstance(payload.get(key, []), list) else []:
            if not isinstance(raw, Mapping):
                continue
            item_id = aliases.get(normalize_identifier(raw.get("item_id")), "")
            statement = _clean(raw.get("statement"))
            detail = _clean(raw.get(required_detail))
            if not item_id or item_id not in allowed_ids:
                warnings.append(f"Modelin bilinmeyen kimlik kullanan {key} kaydı reddedildi.")
                continue
            if not statement or not detail:
                warnings.append(f"Modelin eksik alanlı {key} kaydı reddedildi: {item_id}.")
                continue
            accepted.append({"item_id": item_id, "statement": statement, required_detail: detail})
        return accepted

    facts = validated_statements("facts", "source_evidence")
    inferences = validated_statements("inferences", "assumption")
    suggestions: list[EngineeringSuggestion] = []
    raw_suggestions = payload.get("suggestions", [])
    if not isinstance(raw_suggestions, list):
        raw_suggestions = []
    for index, raw in enumerate(raw_suggestions, start=1):
        if not isinstance(raw, Mapping):
            warnings.append("Modelin nesne olmayan önerisi reddedildi.")
            continue
        category = _clean(raw.get("category"))
        affected_raw = raw.get("affected_items", [])
        if isinstance(affected_raw, str):
            affected_raw = [affected_raw]
        affected: list[str] = []
        invalid_ids: list[str] = []
        for value in affected_raw if isinstance(affected_raw, list) else []:
            matched = aliases.get(normalize_identifier(value))
            if not matched:
                invalid_ids.append(_clean(value))
            elif matched not in affected:
                affected.append(matched)
        fields = {
            "suggestion": _clean(raw.get("suggestion")),
            "rationale": _clean(raw.get("rationale")),
            "expected_benefit": _clean(raw.get("expected_benefit")),
            "new_risk": _clean(raw.get("new_risk")),
            "required_verification": _clean(raw.get("required_verification")),
            "source_or_assumption": _clean(raw.get("source_or_assumption")),
        }
        if category not in SUGGESTION_CATEGORIES:
            warnings.append(f"İzin verilmeyen öneri kategorisi reddedildi: {category or 'boş'}.")
            continue
        if invalid_ids:
            warnings.append(
                "Modelin bilinmeyen kimlik kullanan önerisi reddedildi: " + ", ".join(invalid_ids) + "."
            )
            continue
        if not all(fields.values()):
            warnings.append(f"Modelin eksik alanlı önerisi reddedildi: {category}.")
            continue
        proposed_numbers = set()
        for value in fields.values():
            proposed_numbers.update(_numbers_in(value))
        unknown_numbers = proposed_numbers - allowed_numbers
        if unknown_numbers:
            warnings.append(
                "Modelin kaynaksız sayısal değer içeren önerisi reddedildi: "
                + ", ".join(sorted(unknown_numbers))
                + "."
            )
            continue
        suggestions.append(EngineeringSuggestion(
            suggestion_id=f"ENG-SUG-{len(suggestions) + 1:03d}",
            category=category,
            affected_items=tuple(affected),
            **fields,
        ))
    return facts, inferences, suggestions, warnings


def _apply_model_analysis(
    report: Mapping[str, Any],
    result: SimulationResult,
    lm_call: Callable[[str], Any] | None,
) -> None:
    caller = lm_call or _default_lm_call
    prompt = _model_prompt(report, result)
    try:
        response = _call_with_deadline(caller, prompt)
        repaired = False
        try:
            payload = _extract_json_payload(response)
        except Exception as first_error:
            repair_prompt = (
                "Aşağıdaki bozuk yanıtı yalnızca geçerli JSON olarak düzelt. Yeni bilgi ekleme. "
                "Markdown kullanma.\nYANIT:\n" + _clean(response)[:10000]
            )
            repaired_response = _call_with_deadline(caller, repair_prompt)
            repaired = True
            try:
                payload = _extract_json_payload(repaired_response)
            except Exception as second_error:
                raise SimulationError(
                    f"Model JSON yanıtı tek düzeltme denemesinden sonra da geçersiz: {second_error}"
                ) from first_error
        facts, inferences, suggestions, warnings = _validate_model_payload(
            payload, report, result.change_request
        )
        result.ai_facts = facts
        result.ai_inferences = inferences
        result.engineering_suggestions = suggestions
        result.warnings.extend(warnings)
        response_status = (
            "repaired" if repaired
            else "validated_with_rejections" if warnings
            else "ok"
        )
        result.lm_status = {
            "available": True,
            "status": response_status,
            "message": (
                "LM Studio JSON yanıtı bir düzeltme denemesiyle doğrulandı."
                if repaired
                else "LM Studio yorumu doğrulandı; geçersiz öğeler reddedildi."
                if warnings
                else "LM Studio yorumu doğrulandı."
            ),
            "rejected_item_count": len(warnings),
        }
    except Exception as error:
        result.lm_status = {
            "available": False,
            "status": "unavailable_or_invalid",
            "message": (
                "LM Studio kapalı, erişilemiyor veya yanıtı geçersiz; "
                f"temel grafik analizi kullanılmaya devam ediyor ({error})."
            ),
        }
        result.warnings.append(result.lm_status["message"])


def _selection_result(
    request: ChangeRequest, candidates: list[dict[str, Any]]
) -> SimulationResult:
    return SimulationResult(
        status="selection_required",
        message=(
            "Birden fazla olası eşleşme bulundu. Rastgele seçim yapılmadı; "
            "devam etmek için adaylardan birini seçin."
        ),
        change_request=request,
        candidates=candidates[:5],
        categorized_impacts=_empty_categories(),
        scoring_method=_scoring_method(),
        summary={"candidate_count": len(candidates[:5]), "impact_count": 0},
        lm_status={"available": None, "status": "not_called", "message": "Hedef seçimi bekleniyor."},
    )


def _addition_result(
    report: Mapping[str, Any],
    request: ChangeRequest,
    candidates: list[dict[str, Any]],
) -> SimulationResult:
    categories = _empty_categories()
    categories["new_or_updated_tests"].append({
        "test_id": None,
        "status": "Yeni test gerekli",
        "reason": "Yeni gereksinim için henüz izlenebilirlik ve doğrulama bağlantısı yok.",
        "required_action": "Üst/alt tahsis, doğrulama yöntemi ve kabul kriteri tanımlanmalı.",
        "path": None,
    })
    result = SimulationResult(
        status="completed",
        message="Yeni gereksinim için başlangıç etki değerlendirmesi tamamlandı.",
        change_request=request,
        candidates=candidates[:5],
        categorized_impacts=categories,
        risks=[_risk_item(
            "Takvim", 2, 3, [],
            "Yeni gereksinim ayrıştırma, tahsis, belge güncelleme ve yeni test çalışması gerektirir.",
        )],
        v_model_analysis={
            "left_leg": {
                "customer_requirement_update": {"required": True, "items": []},
                "system_requirement_update": {"required": True, "items": []},
                "subsystem_requirement_update": {"required": True, "items": []},
                "architecture_design_part_interface_impact": {"affected": None, "items": []},
            },
            "right_leg": {
                "unit_tests_update": {"required": None, "items": []},
                "integration_tests_update": {"required": None, "items": []},
                "system_verification_tests_update": {"required": True, "items": []},
                "acceptance_validation_update": {"required": None, "items": []},
                "existing_test_result_validity": {"status": "Yeni test tanımı gerekli", "tests": []},
            },
        },
        scoring_method=_scoring_method(),
        summary={
            "impact_count": 0,
            "path_count": 0,
            "risk_count": 1,
            "candidate_count": len(candidates[:5]),
            "overall_impact_level": "Belirlenemedi — tahsis bağlantısı yok",
        },
        warnings=[
            "Yeni gereksinim henüz grafikte bulunmadığı için kesin etki yolu ve puanı üretilmedi."
        ],
    )
    return result


def simulate_change(
    traceability: Mapping[str, Any] | str | Path,
    change_request: ChangeRequest | Mapping[str, Any],
    *,
    selected_id: str | None = None,
    rag_search: Callable[..., Sequence[Any]] | None = None,
    use_existing_rag: bool = True,
    use_lm_studio: bool = True,
    lm_call: Callable[[str], Any] | None = None,
    max_depth: int = 6,
) -> SimulationResult:
    """Değişikliği grafikte yayar, puanlar ve isteğe bağlı LM yorumu ekler."""
    report = load_traceability(traceability)
    request = (
        change_request
        if isinstance(change_request, ChangeRequest)
        else ChangeRequest.from_mapping(change_request)
    ).validated()
    if request.change_type == CHANGE_REQUIREMENT_ADD:
        _, aliases = _node_index(report)
        if request.requirement_id and normalize_identifier(request.requirement_id) in aliases:
            raise SimulationError(
                f"'{request.requirement_id}' kimliği zaten izlenebilirlik haritasında bulunuyor; "
                "yeni gereksinim kimliği benzersiz olmalıdır."
            )
        related = find_requirement_candidates(
            report,
            request.query or _clean(request.proposed_value),
            change_type=CHANGE_REQUIREMENT_ADD,
            rag_search=rag_search,
            use_existing_rag=use_existing_rag,
            limit=5,
        )
        result = _addition_result(report, request, related)
        if use_lm_studio:
            _apply_model_analysis(report, result, lm_call)
        else:
            result.lm_status = {
                "available": None, "status": "disabled",
                "message": "LM Studio yorumu devre dışı.",
            }
        return result
    target, candidates = _resolve_target(
        report,
        request,
        selected_id=selected_id,
        rag_search=rag_search,
        use_existing_rag=use_existing_rag,
    )

    if request.change_type == CHANGE_REQUIREMENT_ADD and target is None:
        related = find_requirement_candidates(
            report,
            request.query or _clean(request.proposed_value),
            change_type=CHANGE_REQUIREMENT_ADD,
            rag_search=rag_search,
            use_existing_rag=use_existing_rag,
            limit=5,
        )
        result = _addition_result(report, request, related)
        if use_lm_studio:
            _apply_model_analysis(report, result, lm_call)
        else:
            result.lm_status = {"available": None, "status": "disabled", "message": "LM Studio yorumu devre dışı."}
        return result

    if target is None:
        return _selection_result(request, candidates)

    if _is_blank(request.current_value):
        request = replace(request, current_value=_clean(target.get("description")))

    numeric_change = None
    warnings: list[str] = []
    if request.change_type == CHANGE_NUMERIC_LIMIT:
        numeric_change, numeric_warnings = _analyze_numeric_change(request, target)
        warnings.extend(numeric_warnings)

    paths, path_warnings = _build_paths(report, _clean(target.get("id")), max(1, min(12, max_depth)))
    warnings.extend(path_warnings)
    missing_data = bool(warnings) or not _clean(target.get("evidence_text") or target.get("description"))
    impacts = _build_impact_items(
        report,
        request,
        paths,
        numeric_change,
        lower_confidence=missing_data,
    )
    categories = _categorize_impacts(request, target, impacts, report)
    risks = _build_risks(request, impacts, target)
    vmodel = _vmodel_analysis(target, impacts, categories)
    max_impact = max((item.impact_score for item in impacts), default=0)
    result = SimulationResult(
        status="completed",
        message="Gereksinim değişikliği etki analizi tamamlandı.",
        change_request=request,
        selected_item=dict(target),
        candidates=candidates[:5],
        impact_paths=[item.traceability_path for item in impacts],
        impacts=impacts,
        categorized_impacts=categories,
        risks=risks,
        v_model_analysis=vmodel,
        numeric_change=numeric_change,
        scoring_method=_scoring_method(),
        summary={
            "impact_count": len(impacts),
            "path_count": len(paths),
            "direct_impact_count": sum(1 for item in impacts if item.direct),
            "second_degree_impact_count": sum(1 for item in impacts if item.distance == 2),
            "cascade_impact_count": sum(1 for item in impacts if item.distance >= 3),
            "risk_count": len(risks),
            "affected_test_count": len(categories["affected_verification_validation"]),
            "affected_document_count": len(categories["affected_documents"]),
            "overall_impact_score": max_impact,
            "overall_impact_level": _impact_level(max_impact),
        },
        warnings=list(dict.fromkeys(warnings)),
    )
    if use_lm_studio:
        _apply_model_analysis(report, result, lm_call)
    else:
        result.lm_status = {"available": None, "status": "disabled", "message": "LM Studio yorumu devre dışı."}
    result.summary["engineering_suggestion_count"] = len(result.engineering_suggestions)
    result.summary["warning_count"] = len(result.warnings)
    return result


def change_request_from_question(
    traceability: Mapping[str, Any] | str | Path,
    question: str,
    *,
    requested_by: str = "Kullanıcı",
    reason: str = "Kullanıcı simülasyon sorusu",
) -> ChangeRequest:
    """Doğal dil sorusundan yalnızca açıkça bulunan kimlik/değerleri çıkarır."""
    report = load_traceability(traceability)
    nodes, aliases = _node_index(report)
    question = _clean(question)
    if not question:
        raise SimulationError("Simülasyon sorusu boş bırakılamaz.")
    target_id = ""
    for identifier in extract_identifiers(question):
        matched = aliases.get(normalize_identifier(identifier))
        if matched:
            target_id = matched
            break
    folded = _fold(question)
    numeric_source = question
    for identifier in extract_identifiers(question):
        numeric_source = re.sub(re.escape(identifier), " ", numeric_source, flags=re.IGNORECASE)
    numeric_tokens = [
        " ".join(part for part in (match.group("number"), match.group("unit")) if part)
        for match in _NUMERIC_TOKEN_RE.finditer(numeric_source)
    ]
    if any(word in folded for word in ("kaldir", "sil", "iptal et")):
        change_type = CHANGE_REQUIREMENT_REMOVE
    elif "parca" in folded and "alternatif" in folded:
        change_type = CHANGE_PART_ALTERNATIVE
    elif "arayuz" in folded:
        change_type = CHANGE_INTERFACE
    elif "calisma kosul" in folded:
        change_type = CHANGE_OPERATING_CONDITION
    elif "oncelik" in folded or "kritiklik" in folded:
        change_type = CHANGE_PRIORITY
    elif "dogrulama yontem" in folded:
        change_type = CHANGE_VERIFICATION
    elif "ekle" in folded and "gereksinim" in folded:
        change_type = CHANGE_REQUIREMENT_ADD
    elif len(numeric_tokens) >= 2 and any(
        word in folded for word in ("sinir", "dusur", "artir", "maksimum", "minimum")
    ):
        change_type = CHANGE_NUMERIC_LIMIT
    else:
        change_type = CHANGE_REQUIREMENT_TEXT

    current: Any = None
    proposed: Any = question
    if change_type == CHANGE_NUMERIC_LIMIT:
        current, proposed = numeric_tokens[0], numeric_tokens[1]
    elif change_type == CHANGE_REQUIREMENT_REMOVE:
        proposed = None
        if target_id:
            current = _clean(nodes[target_id].get("description"))
    elif target_id:
        current = _clean(nodes[target_id].get("description"))
    return ChangeRequest(
        requirement_id=target_id,
        current_value=current,
        proposed_value=proposed,
        reason=reason,
        requested_by=requested_by,
        change_type=change_type,
        assumptions=(
            "Değişiklik türü ve sayısal değerler yalnızca soru metnindeki açık ifadelerden çıkarıldı.",
        ),
        query=question,
    ).validated()


def simulate_question(
    traceability: Mapping[str, Any] | str | Path,
    question: str,
    **kwargs: Any,
) -> SimulationResult:
    """Kullanıcının doğal dil sorusunu ChangeRequest'e çevirip simüle eder."""
    request_keys = {"requested_by", "reason"}
    request_kwargs = {key: kwargs.pop(key) for key in list(kwargs) if key in request_keys}
    request = change_request_from_question(traceability, question, **request_kwargs)
    return simulate_change(traceability, request, **kwargs)


__all__ = [
    "CHANGE_INTERFACE",
    "CHANGE_NUMERIC_LIMIT",
    "CHANGE_OPERATING_CONDITION",
    "CHANGE_PART_ALTERNATIVE",
    "CHANGE_PRIORITY",
    "CHANGE_REQUIREMENT_ADD",
    "CHANGE_REQUIREMENT_REMOVE",
    "CHANGE_REQUIREMENT_TEXT",
    "CHANGE_SYSTEM_ALTERNATIVE",
    "CHANGE_VERIFICATION",
    "ChangeRequest",
    "EngineeringSuggestion",
    "ImpactItem",
    "ImpactPath",
    "RiskItem",
    "SUGGESTION_CATEGORIES",
    "SUPPORTED_CHANGE_TYPES",
    "SimulationError",
    "SimulationResult",
    "change_request_from_question",
    "find_requirement_candidates",
    "load_traceability",
    "simulate_change",
    "simulate_question",
]
