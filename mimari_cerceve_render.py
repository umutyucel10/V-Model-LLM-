# -*- coding: utf-8 -*-
"""ArchitectureSnapshot tabanlı deterministik SVG görünüm motoru.

Gemma/model çıktısı, koordinat, çizim kodu, flat_data veya haricî bağlam
kabul edilmez. Public API'nin tek mimari veri kaynağı gerçek bir
``ArchitectureSnapshot`` nesnesidir.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
import textwrap
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

from mimari_cerceve_dogrulama import validate_architecture
from mimari_cerceve_gorunumleri import (
    ArchitectureViewError,
    ArchitectureViewProjection,
    PRESENTATION_DIAGRAM,
    PRESENTATION_MATRIX,
    PRESENTATION_TABLE,
    SUPPORTED_RENDER_VIEW_IDS,
    VIEW_GENERATORS,
    get_view_generator,
)
from mimari_cerceve_model import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureSnapshot,
    EvidenceLink,
    ValidationFinding,
)


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

RENDER_STATUS_RENDERED = "rendered"
RENDER_STATUS_BLOCKED = "blocked"

_STYLE = """
.background { fill: #f7f9fc; }
.title { font: 700 24px 'Segoe UI', Arial, sans-serif; fill: #182230; }
.subtitle { font: 400 13px 'Segoe UI', Arial, sans-serif; fill: #52606d; }
.node rect { fill: #ffffff; stroke: #365b7d; stroke-width: 2; rx: 10; }
.node-type { font: 600 11px 'Segoe UI', Arial, sans-serif; fill: #35607f; }
.node-name { font: 700 14px 'Segoe UI', Arial, sans-serif; fill: #172b3a; }
.node-meta { font: 400 10px 'Segoe UI', Arial, sans-serif; fill: #52606d; }
.edge { stroke: #718096; stroke-width: 2; fill: none; }
.edge-label { font: 600 10px 'Segoe UI', Arial, sans-serif; fill: #34495e; }
.table-border { fill: #ffffff; stroke: #9aabba; stroke-width: 1; }
.table-header { fill: #dce8f2; stroke: #7992a8; stroke-width: 1; }
.table-text { font: 400 11px 'Segoe UI', Arial, sans-serif; fill: #1f3444; }
.table-head-text { font: 700 11px 'Segoe UI', Arial, sans-serif; fill: #18354b; }
.matrix-hit { fill: #2b7a78; }
.trace-title { font: 700 15px 'Segoe UI', Arial, sans-serif; fill: #18354b; }
.trace-row { fill: #ffffff; stroke: #ccd6df; stroke-width: 1; }
.trace-text { font: 400 10px 'Segoe UI', Arial, sans-serif; fill: #334e5c; }
.trace-link { font: 600 10px 'Segoe UI', Arial, sans-serif; fill: #155d85; text-decoration: underline; }
""".strip()


class ArchitectureRenderError(ValueError):
    """Render API programlama/sözleşme hatası."""


class ViewRenderBlockedError(ArchitectureRenderError):
    def __init__(self, result: "ViewRenderResult") -> None:
        self.result = result
        super().__init__(
            f"{result.view_id} üretimi engellendi: " + "; ".join(result.missing_inputs)
        )


@dataclass(frozen=True, slots=True)
class ViewRenderResult:
    view_id: str
    snapshot_id: str
    status: str
    render_kind: str
    svg: str | None
    missing_inputs: tuple[str, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()
    included_element_ids: tuple[str, ...] = ()
    included_relationship_ids: tuple[str, ...] = ()
    content_sha256: str = ""

    @property
    def rendered(self) -> bool:
        return self.status == RENDER_STATUS_RENDERED and self.svg is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "render_kind": self.render_kind,
            "svg": self.svg,
            "missing_inputs": list(self.missing_inputs),
            "findings": [item.to_dict() for item in self.findings],
            "included_element_ids": list(self.included_element_ids),
            "included_relationship_ids": list(self.included_relationship_ids),
            "content_sha256": self.content_sha256,
        }


def _svg_tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def _dom_id(kind: str, value: str) -> str:
    raw = str(value)
    readable = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-._:")[:42] or "record"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{readable}-{digest}"


def _record_dom_id(record: ArchitectureElement | ArchitectureRelationship) -> str:
    kind = "element" if isinstance(record, ArchitectureElement) else "relationship"
    return _dom_id(kind, record.stable_id)


def _trace_dom_id(record: ArchitectureElement | ArchitectureRelationship) -> str:
    return _dom_id("trace", record.stable_id)


def _record_attributes(
    record: ArchitectureElement | ArchitectureRelationship,
) -> dict[str, str]:
    record_type = (
        record.element_type if isinstance(record, ArchitectureElement)
        else record.relationship_type
    )
    evidence_ids = tuple(sorted(link.evidence_id for link in record.evidence_links))
    attributes = {
        "data-architecture-id": record.stable_id,
        "data-architecture-type": record_type,
        "data-requirement-ids": " ".join(sorted(record.source_requirement_ids)),
        "data-evidence-ids": " ".join(evidence_ids),
    }
    if isinstance(record, ArchitectureRelationship):
        attributes.update({
            "data-source-element-id": record.source_element_id,
            "data-target-element-id": record.target_element_id,
        })
    return attributes


def _wrapped_lines(value: str, width: int, maximum: int) -> tuple[str, ...]:
    normalized = " ".join(str(value).split())
    if not normalized:
        return ("belirsiz/eksik",)
    lines = textwrap.wrap(
        normalized,
        width=max(4, width),
        break_long_words=True,
        break_on_hyphens=False,
    ) or [normalized]
    if len(lines) > maximum:
        lines = lines[:maximum]
        lines[-1] = lines[-1][:-1] + "…" if lines[-1] else "…"
    return tuple(lines)


def _add_text_lines(
    parent: ET.Element,
    x: int,
    y: int,
    lines: Iterable[str],
    *,
    css_class: str,
    line_height: int = 15,
    anchor: str | None = None,
) -> ET.Element:
    attributes = {"x": str(x), "y": str(y), "class": css_class}
    if anchor:
        attributes["text-anchor"] = anchor
    text_element = ET.SubElement(parent, _svg_tag("text"), attributes)
    for index, line in enumerate(lines):
        span = ET.SubElement(
            text_element,
            _svg_tag("tspan"),
            {"x": str(x), "dy": "0" if index == 0 else str(line_height)},
        )
        if anchor:
            span.set("text-anchor", anchor)
        span.text = line
    return text_element


def _root(
    projection: ArchitectureViewProjection,
    snapshot: ArchitectureSnapshot,
    width: int,
    height: int,
) -> ET.Element:
    root = ET.Element(_svg_tag("svg"), {
        "viewBox": f"0 0 {width} {height}",
        "width": str(width),
        "height": str(height),
        "role": "img",
        "aria-labelledby": "view-title view-description",
        "data-view-id": projection.view_id,
        "data-framework-profile": snapshot.framework_profile_id,
        "data-snapshot-id": snapshot.snapshot_id,
        "data-render-kind": projection.presentation,
    })
    title = ET.SubElement(root, _svg_tag("title"), {"id": "view-title"})
    title.text = f"{projection.view_id} — {projection.view_definition.name}"
    description = ET.SubElement(root, _svg_tag("desc"), {"id": "view-description"})
    description.text = projection.view_definition.purpose
    metadata = ET.SubElement(root, _svg_tag("metadata"))
    metadata.text = (
        f"profile={snapshot.framework_profile_id};"
        f"framework-version={snapshot.framework_version};"
        f"view={projection.view_id};snapshot={snapshot.snapshot_id}"
    )
    defs = ET.SubElement(root, _svg_tag("defs"))
    style = ET.SubElement(defs, _svg_tag("style"), {"type": "text/css"})
    style.text = _STYLE
    marker = ET.SubElement(defs, _svg_tag("marker"), {
        "id": "arrow", "viewBox": "0 0 10 10", "refX": "9", "refY": "5",
        "markerWidth": "7", "markerHeight": "7", "orient": "auto-start-reverse",
    })
    ET.SubElement(marker, _svg_tag("path"), {"d": "M 0 0 L 10 5 L 0 10 z", "fill": "#718096"})
    ET.SubElement(root, _svg_tag("rect"), {
        "class": "background", "x": "0", "y": "0",
        "width": str(width), "height": str(height),
    })
    _add_text_lines(root, 34, 38, (f"{projection.view_id} · {projection.view_definition.name}",), css_class="title")
    _add_text_lines(root, 34, 64, _wrapped_lines(projection.view_definition.purpose, 130, 2), css_class="subtitle", line_height=14)
    return root


def _trace_registries(
    projection: ArchitectureViewProjection,
) -> tuple[
    tuple[ArchitectureElement | ArchitectureRelationship, ...],
    Mapping[str, tuple[str, ...]],
    Mapping[str, tuple[EvidenceLink, tuple[str, ...]]],
]:
    records: tuple[ArchitectureElement | ArchitectureRelationship, ...] = (
        *projection.elements, *projection.relationships,
    )
    records = tuple(sorted(records, key=lambda item: (item.__class__.__name__, item.stable_id)))
    requirement_owners: dict[str, set[str]] = {}
    evidence_records: dict[str, tuple[EvidenceLink, set[str]]] = {}
    for record in records:
        for requirement_id in record.source_requirement_ids:
            requirement_owners.setdefault(requirement_id, set()).add(record.stable_id)
        for evidence in record.evidence_links:
            current = evidence_records.setdefault(evidence.evidence_id, (evidence, set()))
            current[1].add(record.stable_id)
    return (
        records,
        {key: tuple(sorted(value)) for key, value in sorted(requirement_owners.items())},
        {
            key: (value[0], tuple(sorted(value[1])))
            for key, value in sorted(evidence_records.items())
        },
    )


def _trace_height(projection: ArchitectureViewProjection) -> int:
    records, requirements, evidence = _trace_registries(projection)
    return 68 + len(records) * 58 + len(requirements) * 44 + len(evidence) * 66


def _append_traceability(
    root: ET.Element,
    projection: ArchitectureViewProjection,
    start_y: int,
    width: int,
) -> None:
    records, requirements, evidence = _trace_registries(projection)
    layer = ET.SubElement(root, _svg_tag("g"), {
        "id": "layer-traceability", "data-layer": "traceability",
        "transform": f"translate(0 {start_y})",
    })
    _add_text_lines(layer, 34, 26, ("Gereksinim ve kanıt geri bağlantıları",), css_class="trace-title")
    y = 42
    record_lookup = {record.stable_id: record for record in records}
    for record in records:
        group = ET.SubElement(layer, _svg_tag("g"), {
            "id": _trace_dom_id(record),
            "data-trace-for": record.stable_id,
        })
        ET.SubElement(group, _svg_tag("rect"), {
            "class": "trace-row", "x": "28", "y": str(y),
            "width": str(width - 56), "height": "50", "rx": "5",
        })
        back = ET.SubElement(group, _svg_tag("a"), {"href": f"#{_record_dom_id(record)}"})
        _add_text_lines(
            back, 40, y + 17,
            (f"{record.stable_id} · {record.name}",),
            css_class="trace-link",
        )
        x = 40
        for requirement_id in sorted(record.source_requirement_ids):
            req_link = ET.SubElement(group, _svg_tag("a"), {
                "href": f"#{_dom_id('requirement', requirement_id)}",
                "data-link-kind": "requirement",
                "data-link-id": requirement_id,
            })
            _add_text_lines(req_link, x, y + 36, (requirement_id,), css_class="trace-link")
            x += min(190, 12 + len(requirement_id) * 7)
        for evidence_link in sorted(record.evidence_links, key=lambda item: item.evidence_id):
            ev_link = ET.SubElement(group, _svg_tag("a"), {
                "href": f"#{_dom_id('evidence', evidence_link.evidence_id)}",
                "data-link-kind": "evidence",
                "data-link-id": evidence_link.evidence_id,
            })
            _add_text_lines(ev_link, x, y + 36, (evidence_link.evidence_id,), css_class="trace-link")
            x += min(230, 12 + len(evidence_link.evidence_id) * 7)
        y += 58

    for requirement_id, owner_ids in requirements.items():
        group = ET.SubElement(layer, _svg_tag("g"), {
            "id": _dom_id("requirement", requirement_id),
            "data-requirement-id": requirement_id,
        })
        ET.SubElement(group, _svg_tag("rect"), {
            "class": "trace-row", "x": "28", "y": str(y),
            "width": str(width - 56), "height": "36", "rx": "5",
        })
        owner = record_lookup[owner_ids[0]]
        back = ET.SubElement(group, _svg_tag("a"), {"href": f"#{_record_dom_id(owner)}"})
        _add_text_lines(
            back, 40, y + 23,
            (f"Gereksinim {requirement_id} · kullanan kayıtlar: {', '.join(owner_ids)}",),
            css_class="trace-link",
        )
        y += 44

    for evidence_id, (evidence_link, owner_ids) in evidence.items():
        group = ET.SubElement(layer, _svg_tag("g"), {
            "id": _dom_id("evidence", evidence_id),
            "data-evidence-id": evidence_id,
            "data-source-item-id": evidence_link.source_item_id,
        })
        ET.SubElement(group, _svg_tag("rect"), {
            "class": "trace-row", "x": "28", "y": str(y),
            "width": str(width - 56), "height": "58", "rx": "5",
        })
        owner = record_lookup[owner_ids[0]]
        back = ET.SubElement(group, _svg_tag("a"), {"href": f"#{_record_dom_id(owner)}"})
        _add_text_lines(back, 40, y + 17, (evidence_id,), css_class="trace-link")
        source_text = f"{evidence_link.source_document} · {evidence_link.source_location} · {evidence_link.source_item_id}"
        _add_text_lines(group, 40, y + 34, _wrapped_lines(source_text, 150, 1), css_class="trace-text")
        _add_text_lines(group, 40, y + 49, _wrapped_lines(evidence_link.evidence_text, 150, 1), css_class="trace-text")
        y += 66


def _render_diagram(
    snapshot: ArchitectureSnapshot,
    projection: ArchitectureViewProjection,
) -> str:
    node_width, node_height = 210, 92
    gap_x, gap_y = 52, 54
    count = len(projection.elements)
    columns = min(4, max(1, math.ceil(math.sqrt(count))))
    rows = max(1, (count + columns - 1) // columns)
    width = max(980, 68 + columns * node_width + (columns - 1) * gap_x)
    diagram_y = 106
    content_height = diagram_y + rows * node_height + max(0, rows - 1) * gap_y + 46
    height = content_height + _trace_height(projection)
    root = _root(projection, snapshot, width, height)

    positions: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(projection.elements):
        row, column = divmod(index, columns)
        x = 34 + column * (node_width + gap_x)
        y = diagram_y + row * (node_height + gap_y)
        positions[item.stable_id] = (x, y)

    edge_layer = ET.SubElement(root, _svg_tag("g"), {
        "id": "layer-edges", "data-layer": "edges",
    })
    for index, relationship in enumerate(projection.relationships):
        source_x, source_y = positions[relationship.source_element_id]
        target_x, target_y = positions[relationship.target_element_id]
        x1, y1 = source_x + node_width // 2, source_y + node_height // 2
        x2, y2 = target_x + node_width // 2, target_y + node_height // 2
        anchor = ET.SubElement(edge_layer, _svg_tag("a"), {
            "href": f"#{_trace_dom_id(relationship)}",
        })
        group = ET.SubElement(anchor, _svg_tag("g"), {
            "id": _record_dom_id(relationship),
            **_record_attributes(relationship),
        })
        title = ET.SubElement(group, _svg_tag("title"))
        title.text = f"{relationship.relationship_type}: {relationship.name}"
        ET.SubElement(group, _svg_tag("line"), {
            "class": "edge", "x1": str(x1), "y1": str(y1),
            "x2": str(x2), "y2": str(y2), "marker-end": "url(#arrow)",
        })
        _add_text_lines(
            group,
            (x1 + x2) // 2,
            (y1 + y2) // 2 - 7 - (index % 3) * 11,
            _wrapped_lines(relationship.relationship_type, 26, 1),
            css_class="edge-label",
            anchor="middle",
        )

    node_layer = ET.SubElement(root, _svg_tag("g"), {
        "id": "layer-nodes", "data-layer": "nodes",
    })
    for element in projection.elements:
        x, y = positions[element.stable_id]
        anchor = ET.SubElement(node_layer, _svg_tag("a"), {
            "href": f"#{_trace_dom_id(element)}",
        })
        group = ET.SubElement(anchor, _svg_tag("g"), {
            "id": _record_dom_id(element), "class": "node",
            **_record_attributes(element),
        })
        title = ET.SubElement(group, _svg_tag("title"))
        title.text = f"{element.element_type}: {element.name}"
        ET.SubElement(group, _svg_tag("rect"), {
            "x": str(x), "y": str(y), "width": str(node_width),
            "height": str(node_height), "rx": "10",
        })
        _add_text_lines(group, x + 12, y + 18, (element.element_type,), css_class="node-type")
        _add_text_lines(group, x + 12, y + 40, _wrapped_lines(element.name, 27, 2), css_class="node-name", line_height=17)
        requirements = ", ".join(sorted(element.source_requirement_ids)) or "belirsiz/eksik"
        _add_text_lines(group, x + 12, y + 80, _wrapped_lines(f"Req: {requirements}", 34, 1), css_class="node-meta")

    _append_traceability(root, projection, content_height, width)
    return _serialize(root)


def _table_rows(
    projection: ArchitectureViewProjection,
) -> tuple[ArchitectureElement | ArchitectureRelationship, ...]:
    return tuple(sorted(
        (*projection.elements, *projection.relationships),
        key=lambda item: (
            0 if isinstance(item, ArchitectureElement) else 1,
            item.stable_id,
        ),
    ))


def _render_table(
    snapshot: ArchitectureSnapshot,
    projection: ArchitectureViewProjection,
) -> str:
    rows = _table_rows(projection)
    width = 1240
    top, header_height, row_height = 106, 46, 78
    table_height = header_height + len(rows) * row_height
    content_height = top + table_height + 36
    height = content_height + _trace_height(projection)
    root = _root(projection, snapshot, width, height)
    layer = ET.SubElement(root, _svg_tag("g"), {
        "id": "layer-table", "data-layer": "table", "role": "table",
        "aria-label": projection.view_definition.name,
    })
    columns = (
        (34, 180, "Tür"),
        (214, 280, "Ad / açıklama"),
        (494, 250, "Gereksinimler"),
        (744, 462, "Kanıt kayıtları"),
    )
    header = ET.SubElement(layer, _svg_tag("g"), {"role": "row"})
    for x, cell_width, title in columns:
        cell = ET.SubElement(header, _svg_tag("g"), {"role": "columnheader"})
        ET.SubElement(cell, _svg_tag("rect"), {
            "class": "table-header", "x": str(x), "y": str(top),
            "width": str(cell_width), "height": str(header_height),
        })
        _add_text_lines(cell, x + 10, top + 28, (title,), css_class="table-head-text")

    for row_index, record in enumerate(rows):
        y = top + header_height + row_index * row_height
        anchor = ET.SubElement(layer, _svg_tag("a"), {
            "href": f"#{_trace_dom_id(record)}",
        })
        row = ET.SubElement(anchor, _svg_tag("g"), {
            "id": _record_dom_id(record), "role": "row",
            **_record_attributes(record),
        })
        record_type = record.element_type if isinstance(record, ArchitectureElement) else record.relationship_type
        evidence_ids = ", ".join(sorted(link.evidence_id for link in record.evidence_links))
        values = (
            record_type,
            f"{record.name} · {record.description}",
            ", ".join(sorted(record.source_requirement_ids)),
            evidence_ids,
        )
        widths = (20, 38, 34, 66)
        for (x, cell_width, _), value, wrap_width in zip(columns, values, widths):
            cell = ET.SubElement(row, _svg_tag("g"), {"role": "cell"})
            ET.SubElement(cell, _svg_tag("rect"), {
                "class": "table-border", "x": str(x), "y": str(y),
                "width": str(cell_width), "height": str(row_height),
            })
            _add_text_lines(
                cell, x + 10, y + 20,
                _wrapped_lines(value, wrap_width, 3),
                css_class="table-text", line_height=16,
            )

    _append_traceability(root, projection, content_height, width)
    return _serialize(root)


def _matrix_relationships(
    projection: ArchitectureViewProjection,
    row: ArchitectureElement,
    column: ArchitectureElement,
) -> tuple[ArchitectureRelationship, ...]:
    endpoints = {row.stable_id, column.stable_id}
    return tuple(
        relationship for relationship in projection.relationships
        if relationship.relationship_type in projection.matrix_relationship_types
        and {relationship.source_element_id, relationship.target_element_id} == endpoints
    )


def _render_matrix(
    snapshot: ArchitectureSnapshot,
    projection: ArchitectureViewProjection,
) -> str:
    row_header_width, column_width, row_height = 270, 190, 72
    left, top, column_header_height = 34, 112, 92
    width = max(980, left * 2 + row_header_width + len(projection.column_elements) * column_width)
    matrix_height = column_header_height + len(projection.row_elements) * row_height
    content_height = top + matrix_height + 38
    height = content_height + _trace_height(projection)
    root = _root(projection, snapshot, width, height)
    layer = ET.SubElement(root, _svg_tag("g"), {
        "id": "layer-matrix", "data-layer": "matrix", "role": "table",
        "aria-label": projection.view_definition.name,
    })

    corner = ET.SubElement(layer, _svg_tag("g"), {"role": "columnheader"})
    ET.SubElement(corner, _svg_tag("rect"), {
        "class": "table-header", "x": str(left), "y": str(top),
        "width": str(row_header_width), "height": str(column_header_height),
    })
    _add_text_lines(corner, left + 12, top + 30, ("Satır / Sütun",), css_class="table-head-text")

    for column_index, column in enumerate(projection.column_elements):
        x = left + row_header_width + column_index * column_width
        anchor = ET.SubElement(layer, _svg_tag("a"), {"href": f"#{_trace_dom_id(column)}"})
        group = ET.SubElement(anchor, _svg_tag("g"), {
            "id": _record_dom_id(column), "role": "columnheader",
            **_record_attributes(column),
        })
        ET.SubElement(group, _svg_tag("rect"), {
            "class": "table-header", "x": str(x), "y": str(top),
            "width": str(column_width), "height": str(column_header_height),
        })
        _add_text_lines(
            group, x + column_width // 2, top + 24,
            _wrapped_lines(column.name, 24, 3),
            css_class="table-head-text", line_height=16, anchor="middle",
        )

    for row_index, row_element in enumerate(projection.row_elements):
        y = top + column_header_height + row_index * row_height
        row_group = ET.SubElement(layer, _svg_tag("g"), {"role": "row"})
        row_anchor = ET.SubElement(row_group, _svg_tag("a"), {
            "href": f"#{_trace_dom_id(row_element)}",
        })
        header = ET.SubElement(row_anchor, _svg_tag("g"), {
            "id": _record_dom_id(row_element), "role": "rowheader",
            **_record_attributes(row_element),
        })
        ET.SubElement(header, _svg_tag("rect"), {
            "class": "table-header", "x": str(left), "y": str(y),
            "width": str(row_header_width), "height": str(row_height),
        })
        _add_text_lines(header, left + 12, y + 24, _wrapped_lines(row_element.name, 34, 2), css_class="table-head-text", line_height=16)

        for column_index, column in enumerate(projection.column_elements):
            x = left + row_header_width + column_index * column_width
            matches = _matrix_relationships(projection, row_element, column)
            cell_attributes = {
                "id": _dom_id("cell", f"{row_element.stable_id}|{column.stable_id}"),
                "role": "cell",
                "data-row-element-id": row_element.stable_id,
                "data-column-element-id": column.stable_id,
                "data-relationship-ids": " ".join(item.stable_id for item in matches),
            }
            cell = ET.SubElement(row_group, _svg_tag("g"), cell_attributes)
            ET.SubElement(cell, _svg_tag("rect"), {
                "class": "table-border", "x": str(x), "y": str(y),
                "width": str(column_width), "height": str(row_height),
            })
            if matches:
                for match_index, relationship in enumerate(matches):
                    relation_anchor = ET.SubElement(cell, _svg_tag("a"), {
                        "href": f"#{_trace_dom_id(relationship)}",
                    })
                    relation_group = ET.SubElement(relation_anchor, _svg_tag("g"), {
                        "id": _record_dom_id(relationship),
                        **_record_attributes(relationship),
                    })
                    title = ET.SubElement(relation_group, _svg_tag("title"))
                    title.text = f"{relationship.relationship_type}: {relationship.name}"
                    if match_index == 0:
                        ET.SubElement(relation_group, _svg_tag("circle"), {
                            "class": "matrix-hit", "cx": str(x + column_width // 2),
                            "cy": str(y + row_height // 2 - 7), "r": "8",
                        })
                        _add_text_lines(
                            relation_group, x + column_width // 2, y + row_height // 2 + 16,
                            (" / ".join(item.relationship_type for item in matches),),
                            css_class="edge-label", anchor="middle",
                        )

    _append_traceability(root, projection, content_height, width)
    return _serialize(root)


def _serialize(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return payload.decode("utf-8") + "\n"


def _neighbors(
    projection: ArchitectureViewProjection,
    element_id: str,
    relationship_type: str,
    target_types: set[str],
) -> tuple[str, ...]:
    type_by_id = {item.stable_id: item.element_type for item in projection.elements}
    values: set[str] = set()
    for relationship in projection.relationships:
        if relationship.relationship_type != relationship_type:
            continue
        if relationship.source_element_id == element_id:
            other = relationship.target_element_id
        elif relationship.target_element_id == element_id:
            other = relationship.source_element_id
        else:
            continue
        if type_by_id.get(other) in target_types:
            values.add(other)
    return tuple(sorted(values))


def _semantic_projection_missing(
    projection: ArchitectureViewProjection,
) -> tuple[str, ...]:
    missing: set[str] = set()
    view_id = projection.view_id
    by_type: dict[str, tuple[ArchitectureElement, ...]] = {}
    for element in projection.elements:
        by_type.setdefault(element.element_type, ())
        by_type[element.element_type] = (*by_type[element.element_type], element)

    if not projection.elements:
        missing.add("Görünüm filtresine uyan onaylı ve kanıtlı mimari öğe")
    if view_id == "L2-L3" and not (
        by_type.get("Node") or by_type.get("Needline")
    ):
        missing.add("L2-L3 için kanıtlı kavramsal bağlam: Node|Needline")

    if view_id == "AV-2":
        for term in by_type.get("DictionaryTerm", ()):
            definitions = _neighbors(projection, term.stable_id, "defined_by", {"Definition"})
            if not definitions:
                missing.add(f"{term.stable_id}: DictionaryTerm↔Definition defined_by")
            if definitions and not any(
                _neighbors(projection, definition_id, "derived_from", {"AuthoritativeSource"})
                or _neighbors(projection, term.stable_id, "derived_from", {"AuthoritativeSource"})
                for definition_id in definitions
            ):
                missing.add(f"{term.stable_id}: Definition↔AuthoritativeSource derived_from")

    flow_specs = {
        "SV-1": ("SystemResourceFlow", {"System"}),
        "SV-2": ("SystemResourceFlow", {"Port"}),
        "SV-4": ("ResourceFlow", {"SystemFunction"}),
        "P4": ("ResourceFlow", {"ResourceFunction", "PhysicalActiveResource", "PhysicalPassiveResource"}),
    }
    if view_id in flow_specs:
        flow_type, endpoint_types = flow_specs[view_id]
        flows = (*by_type.get(flow_type, ()),)
        if view_id == "P4":
            flows = (*flows, *by_type.get("FunctionalFlow", ()))
        for flow in flows:
            sources = _neighbors(projection, flow.stable_id, "flow_source", endpoint_types)
            targets = _neighbors(projection, flow.stable_id, "flow_target", endpoint_types)
            if not sources:
                missing.add(f"{flow.stable_id}: flow_source")
            if not targets:
                missing.add(f"{flow.stable_id}: flow_target")
            if sources and targets and not set(sources).isdisjoint(targets):
                missing.add(f"{flow.stable_id}: farklı kaynak ve hedef uç")

    if view_id == "SV-2":
        for port in by_type.get("Port", ()):
            if not _neighbors(projection, port.stable_id, "port_belongs_to", {"System"}):
                missing.add(f"{port.stable_id}: Port↔System port_belongs_to")
    if view_id == "SV-4":
        for function in by_type.get("SystemFunction", ()):
            if not _neighbors(projection, function.stable_id, "performed_by", {"SystemOrResource"}):
                missing.add(f"{function.stable_id}: SystemFunction↔SystemOrResource performed_by")

    interaction_specs = {
        "L3": ("LogicalInteraction", {"LogicalActiveResource"}, {"LogicalPassiveResource"}),
        "P3": ("ResourceInteraction", {"PhysicalActiveResource"}, set()),
    }
    if view_id in interaction_specs:
        interaction_type, endpoint_types, passive_types = interaction_specs[view_id]
        for interaction in by_type.get(interaction_type, ()):
            sources = _neighbors(projection, interaction.stable_id, "interaction_source", endpoint_types)
            targets = _neighbors(projection, interaction.stable_id, "interaction_target", endpoint_types)
            if not sources:
                missing.add(f"{interaction.stable_id}: interaction_source")
            if not targets:
                missing.add(f"{interaction.stable_id}: interaction_target")
            if sources and targets and not set(sources).isdisjoint(targets):
                missing.add(f"{interaction.stable_id}: farklı etkileşim uçları")
            if passive_types and not _neighbors(projection, interaction.stable_id, "conveys", passive_types):
                missing.add(f"{interaction.stable_id}: conveys")

    if view_id == "L4":
        for activity in by_type.get("OperationalActivity", ()):
            if not _neighbors(projection, activity.stable_id, "performs", {"Node", "Role"}):
                missing.add(f"{activity.stable_id}: Node|Role performs")
        for flow in by_type.get("OperationalControlFlow", ()):
            if not _neighbors(projection, flow.stable_id, "control_flow_source", {"OperationalActivity"}):
                missing.add(f"{flow.stable_id}: control_flow_source")
            if not _neighbors(projection, flow.stable_id, "control_flow_target", {"OperationalActivity"}):
                missing.add(f"{flow.stable_id}: control_flow_target")

    if view_id == "P3":
        for protocol in by_type.get("Protocol", ()):
            if not _neighbors(projection, protocol.stable_id, "implements", {"PhysicalActiveResource"}):
                missing.add(f"{protocol.stable_id}: PhysicalActiveResource↔Protocol implements")
            if not _neighbors(projection, protocol.stable_id, "conforms_to", {"Standard"}):
                missing.add(f"{protocol.stable_id}: Protocol↔Standard conforms_to")

    if view_id in {"L8", "P8"}:
        prefix = "Logical" if view_id == "L8" else "Resource"
        target_types = (
            {"LogicalActiveResource", "LogicalBehaviour", "LogicalPassiveResource"}
            if view_id == "L8"
            else {"PhysicalActiveResource", "PhysicalBehaviour", "PhysicalPassiveResource"}
        )
        for requirement in by_type.get(f"{prefix}Requirement", ()):
            constraints = _neighbors(
                projection, requirement.stable_id, "relates_to", {f"{prefix}Constraint"}
            )
            if not constraints:
                missing.add(f"{requirement.stable_id}: Requirement↔Constraint relates_to")
            if not (
                _neighbors(projection, requirement.stable_id, "applies_to", target_types)
                or any(
                    _neighbors(projection, constraint_id, "applies_to", target_types)
                    for constraint_id in constraints
                )
            ):
                missing.add(f"{requirement.stable_id}: applies_to hedefi")

    if view_id == "SV-7":
        for measure in by_type.get("Measure", ()):
            targets = _neighbors(
                projection, measure.stable_id, "measure_applies_to", {"SystemModelElement"}
            )
            if not targets:
                missing.add(f"{measure.stable_id}: measure_applies_to hedefi")
            valid_time = _neighbors(projection, measure.stable_id, "valid_during", {"Timeframe"})
            if not valid_time:
                valid_time = tuple(
                    timeframe
                    for target_id in targets
                    for timeframe in _neighbors(
                        projection, target_id, "valid_during", {"Timeframe"}
                    )
                )
            if not valid_time:
                missing.add(f"{measure.stable_id}: valid_during Timeframe")

    if projection.presentation == PRESENTATION_MATRIX:
        if not projection.row_elements:
            missing.add("Matris satır öğeleri")
        if not projection.column_elements:
            missing.add("Matris sütun öğeleri")
        if projection.row_elements and projection.column_elements and not any(
            _matrix_relationships(projection, row, column)
            for row in projection.row_elements
            for column in projection.column_elements
        ):
            missing.add("En az bir kanıtlı matris eşlemesi")

    return tuple(sorted(missing, key=lambda value: (value.casefold(), value)))


def _embedded_blocking_findings(
    snapshot: ArchitectureSnapshot,
    projection: ArchitectureViewProjection,
) -> tuple[ValidationFinding, ...]:
    definition = projection.view_definition
    allowed_types = set(definition.required_element_types) | set(definition.optional_element_types)
    for group in definition.required_any_of_element_types:
        allowed_types.update(group)
    relevant_ids = {
        item.stable_id for item in snapshot.elements if item.element_type in allowed_types
    }
    relevant_ids.update(
        item.stable_id for item in snapshot.relationships
        if item.relationship_type in (
            set(definition.required_relationships)
            | set(definition.optional_relationships)
            | {value for group in definition.required_any_of_relationships for value in group}
        )
    )
    always_relevant = {snapshot.snapshot_id, snapshot.project_id}
    return tuple(sorted(
        (
            finding for finding in snapshot.validation_findings
            if finding.blocking
            and finding.severity == "error"
            and (not finding.view_id or finding.view_id == projection.view_id)
            and (
                not finding.target_id
                or finding.target_id in relevant_ids
                or finding.target_id in always_relevant
            )
        ),
        key=lambda item: item.finding_id,
    ))


def _missing_from_findings(findings: Iterable[ValidationFinding]) -> tuple[str, ...]:
    values: set[str] = set()
    for finding in findings:
        if finding.missing_fields:
            values.update(f"{finding.code}: {field}" for field in finding.missing_fields)
        else:
            values.add(f"{finding.code}: {finding.message}")
    return tuple(sorted(values, key=lambda value: (value.casefold(), value)))


def _blocked_result(
    snapshot: ArchitectureSnapshot,
    projection: ArchitectureViewProjection,
    missing_inputs: Iterable[str],
    findings: Iterable[ValidationFinding] = (),
) -> ViewRenderResult:
    return ViewRenderResult(
        view_id=projection.view_id,
        snapshot_id=snapshot.snapshot_id,
        status=RENDER_STATUS_BLOCKED,
        render_kind=projection.presentation,
        svg=None,
        missing_inputs=tuple(sorted(set(missing_inputs), key=lambda value: (value.casefold(), value))),
        findings=tuple(sorted(set(findings), key=lambda item: item.finding_id)),
        included_element_ids=projection.element_ids,
        included_relationship_ids=projection.relationship_ids,
    )


def render_view(snapshot: ArchitectureSnapshot, view_id: str) -> ViewRenderResult:
    """Seçili bir görünümü deterministik SVG olarak üretir.

    Beklenen veri eksikliği exception değildir: ``status='blocked'`` ve
    ``svg=None`` döner. Yanlış kaynak tipi, desteklenmeyen, profil-dışı veya
    snapshot'ta seçilmemiş görünüm programlama hatasıdır.
    """

    if not isinstance(snapshot, ArchitectureSnapshot):
        raise TypeError("Render motorunun tek veri kaynağı ArchitectureSnapshot olmalıdır.")
    if not isinstance(view_id, str) or not view_id:
        raise TypeError("Görünüm kimliği boş olmayan string olmalıdır.")
    if view_id not in SUPPORTED_RENDER_VIEW_IDS:
        raise ArchitectureRenderError(f"Desteklenmeyen ilk-aşama görünümü: {view_id}")
    if view_id not in snapshot.selected_view_ids:
        raise ArchitectureRenderError(
            f"{view_id} ArchitectureSnapshot.selected_view_ids içinde seçili değil."
        )
    try:
        generator = get_view_generator(snapshot.framework_profile_id, view_id)
        projection = generator.project(snapshot)
    except ArchitectureViewError as error:
        raise ArchitectureRenderError(str(error)) from error

    report = validate_architecture(snapshot, selected_view_ids=(view_id,))
    target_result = next(
        (item for item in report.view_generatability.view_results if item.view_id == view_id),
        None,
    )
    blocking_findings: list[ValidationFinding] = []
    if not report.model_integrity.passed:
        blocking_findings.extend(
            item for item in report.model_integrity.findings if item.severity == "error"
        )
    if target_result is None:
        missing = ("Görünüm doğrulama sonucu",)
        return _blocked_result(snapshot, projection, missing)
    if not target_result.generatable:
        blocking_findings.extend(
            item for item in target_result.findings if item.severity == "error"
        )
    embedded = _embedded_blocking_findings(snapshot, projection)
    blocking_findings.extend(embedded)
    semantic_missing = _semantic_projection_missing(projection)
    missing = (*_missing_from_findings(blocking_findings), *semantic_missing)
    if blocking_findings or semantic_missing:
        return _blocked_result(snapshot, projection, missing, blocking_findings)

    if projection.presentation == PRESENTATION_DIAGRAM:
        svg = _render_diagram(snapshot, projection)
    elif projection.presentation == PRESENTATION_MATRIX:
        svg = _render_matrix(snapshot, projection)
    elif projection.presentation == PRESENTATION_TABLE:
        svg = _render_table(snapshot, projection)
    else:
        raise ArchitectureRenderError(
            f"Desteklenmeyen render sunumu: {projection.presentation}"
        )
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()
    return ViewRenderResult(
        view_id=projection.view_id,
        snapshot_id=snapshot.snapshot_id,
        status=RENDER_STATUS_RENDERED,
        render_kind=projection.presentation,
        svg=svg,
        included_element_ids=projection.element_ids,
        included_relationship_ids=projection.relationship_ids,
        content_sha256=digest,
    )


def render_selected_views(
    snapshot: ArchitectureSnapshot,
) -> tuple[ViewRenderResult, ...]:
    if not isinstance(snapshot, ArchitectureSnapshot):
        raise TypeError("Render motorunun tek veri kaynağı ArchitectureSnapshot olmalıdır.")
    unsupported = tuple(
        view_id for view_id in snapshot.selected_view_ids
        if view_id not in SUPPORTED_RENDER_VIEW_IDS
    )
    if unsupported:
        raise ArchitectureRenderError(
            "Seçili fakat KART 5 kapsamında desteklenmeyen görünümler: "
            + ", ".join(unsupported)
        )
    return tuple(
        render_view(snapshot, view_id)
        for view_id in sorted(snapshot.selected_view_ids, key=lambda value: (value.casefold(), value))
    )


def render_view_or_raise(snapshot: ArchitectureSnapshot, view_id: str) -> ViewRenderResult:
    result = render_view(snapshot, view_id)
    if not result.rendered:
        raise ViewRenderBlockedError(result)
    return result


def write_view_svg(result: ViewRenderResult, target_path: str | os.PathLike[str]) -> Path:
    """Başarılı SVG sonucunu aynı dizinde atomik olarak yazar."""

    if not isinstance(result, ViewRenderResult):
        raise TypeError("Yazılacak değer ViewRenderResult olmalıdır.")
    if not result.rendered or result.svg is None:
        raise ViewRenderBlockedError(result)
    target = Path(target_path)
    if target.suffix.casefold() != ".svg":
        raise ArchitectureRenderError("SVG hedef dosyası .svg uzantılı olmalıdır.")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(result.svg)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise
    return target


def render_view_to_file(
    snapshot: ArchitectureSnapshot,
    view_id: str,
    target_path: str | os.PathLike[str],
) -> ViewRenderResult:
    result = render_view_or_raise(snapshot, view_id)
    write_view_svg(result, target_path)
    return result


# ---------------------------------------------------------------------------
# Önizleme yardımcısı
#
# Kanonik SVG renkleri gömülü bir <style> bloğuyla verir. Bu, tarayıcı ve
# ArchiMate araçları için doğru biçimdir; ancak uygulama içi önizlemeyi üreten
# PyMuPDF gömülü CSS'i uygulamaz ve her öğeyi varsayılan siyahla çizer.
#
# Aşağıdaki dönüşüm YALNIZCA önizleme içindir. Dışa aktarılan ve yayımlanan
# SVG'ye dokunulmaz; içerik özeti (content_sha256) değişmez.
# ---------------------------------------------------------------------------

_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_FONT_SHORTHAND_RE = re.compile(
    r"^\s*(?P<weight>\d{3})?\s*(?P<size>[\d.]+)px\s+(?P<family>.+?)\s*$"
)
# SVG sunum özniteliğine çevrilebilen bildirimler. Diğerleri yok sayılır.
_PRESENTATION_PROPERTIES = frozenset({
    "fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap",
    "opacity", "fill-opacity", "stroke-opacity", "rx", "ry",
    "font-size", "font-weight", "font-family", "text-anchor",
})


def _expand_declarations(block: str) -> dict[str, str]:
    """Bir CSS bloğunu sunum özniteliği sözlüğüne çevirir."""

    declarations: dict[str, str] = {}
    for item in block.split(";"):
        if ":" not in item:
            continue
        name, _, value = item.partition(":")
        name = name.strip().casefold()
        value = value.strip()
        if not name or not value:
            continue
        if name == "font":
            match = _FONT_SHORTHAND_RE.match(value)
            if match is None:
                continue
            if match.group("weight"):
                declarations["font-weight"] = match.group("weight")
            declarations["font-size"] = match.group("size")
            declarations["font-family"] = match.group("family")
            continue
        if name in _PRESENTATION_PROPERTIES:
            declarations[name] = value
    return declarations


def parse_style_rules(css_text: str) -> dict[str, dict[str, str]]:
    """``.sinif`` ve ``.sinif etiket`` seçicilerini bildirimlerine eşler."""

    rules: dict[str, dict[str, str]] = {}
    for selector_group, block in _CSS_RULE_RE.findall(css_text):
        declarations = _expand_declarations(block)
        if not declarations:
            continue
        for selector in selector_group.split(","):
            selector = " ".join(selector.split())
            if not selector:
                continue
            rules.setdefault(selector, {}).update(declarations)
    return rules


def svg_with_inline_styles(svg: str) -> str:
    """Gömülü CSS'i sunum özniteliklerine taşıyarak önizlenebilir SVG döndürür.

    Girdi değiştirilmez; CSS bulunmazsa ya da ayrıştırılamazsa özgün metin
    aynen döner. Önizleme hiçbir koşulda görünüm üretimini engellememelidir.
    """

    if not isinstance(svg, str) or "<style" not in svg:
        return svg
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return svg
    css_text = "".join(
        node.text or "" for node in root.iter(f"{{{SVG_NS}}}style")
    )
    rules = parse_style_rules(css_text)
    if not rules:
        return svg

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def _apply(element: ET.Element, declarations: Mapping[str, str]) -> None:
        for name, value in declarations.items():
            element.set(name, value)

    for element in root.iter():
        class_value = element.get("class")
        if not class_value:
            continue
        for class_name in class_value.split():
            _apply(element, rules.get(f".{class_name}", {}))
            # ``.node rect`` gibi torun seçiciler için alt ağacı tara.
            prefix = f".{class_name} "
            for selector, declarations in rules.items():
                if not selector.startswith(prefix):
                    continue
                wanted = selector[len(prefix):].strip()
                if not wanted or " " in wanted:
                    continue
                for descendant in element.iter():
                    if descendant is not element and _local(descendant.tag) == wanted:
                        _apply(descendant, declarations)
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode")


__all__ = [
    "ArchitectureRenderError",
    "RENDER_STATUS_BLOCKED",
    "RENDER_STATUS_RENDERED",
    "SVG_NS",
    "parse_style_rules",
    "ViewRenderBlockedError",
    "ViewRenderResult",
    "render_selected_views",
    "render_view",
    "render_view_or_raise",
    "render_view_to_file",
    "svg_with_inline_styles",
    "write_view_svg",
]
