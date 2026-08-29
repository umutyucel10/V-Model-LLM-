# -*- coding: utf-8 -*-
"""ArchitectureSnapshot'tan deterministik görünüm projeksiyonları.

Bu katman çizim yapmaz ve herhangi bir model/Gemma çağrısı içermez. Her
üretici, katalogda tanımlı tür ve ilişki kümesini tek kaynak olan
``ArchitectureSnapshot`` üzerinde uygular. SVG serileştirme ve önkoşul engeli
``mimari_cerceve_render`` modülündedir.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from mimari_cerceve_katalog import get_view_definition
from mimari_cerceve_model import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureSnapshot,
    REVIEW_APPROVED,
    ViewDefinition,
)


DODAF_RENDER_VIEW_IDS = (
    "AV-2", "SV-1", "SV-2", "SV-4", "SV-5a", "SV-7",
)
NAF_RENDER_VIEW_IDS = (
    "L2-L3", "L3", "L4", "L8", "P2", "P3", "P4", "L4-P4", "P8",
)
SUPPORTED_RENDER_VIEW_IDS = (*DODAF_RENDER_VIEW_IDS, *NAF_RENDER_VIEW_IDS)

PRESENTATION_DIAGRAM = "diagram"
PRESENTATION_MATRIX = "matrix"
PRESENTATION_TABLE = "table"

_PRESENTATION_BY_VIEW: Mapping[str, str] = MappingProxyType({
    "AV-2": PRESENTATION_TABLE,
    "SV-1": PRESENTATION_DIAGRAM,
    "SV-2": PRESENTATION_DIAGRAM,
    "SV-4": PRESENTATION_DIAGRAM,
    "SV-5a": PRESENTATION_MATRIX,
    "SV-7": PRESENTATION_TABLE,
    "L2-L3": PRESENTATION_DIAGRAM,
    "L3": PRESENTATION_DIAGRAM,
    "L4": PRESENTATION_DIAGRAM,
    "L8": PRESENTATION_TABLE,
    "P2": PRESENTATION_DIAGRAM,
    "P3": PRESENTATION_DIAGRAM,
    "P4": PRESENTATION_DIAGRAM,
    "L4-P4": PRESENTATION_MATRIX,
    "P8": PRESENTATION_TABLE,
})

_MATRIX_AXES: Mapping[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = (
    MappingProxyType({
        "SV-5a": (
            ("OperationalActivity",),
            ("SystemFunction",),
            ("maps_to", "realizes"),
        ),
        "L4-P4": (
            ("OperationalActivity",),
            ("ResourceFunction",),
            ("realizes", "maps_to"),
        ),
    })
)


class ArchitectureViewError(ValueError):
    """Görünüm üreticisi sözleşmesi ihlali."""


@dataclass(frozen=True, slots=True)
class ArchitectureViewProjection:
    view_definition: ViewDefinition
    presentation: str
    elements: tuple[ArchitectureElement, ...]
    relationships: tuple[ArchitectureRelationship, ...]
    row_elements: tuple[ArchitectureElement, ...] = ()
    column_elements: tuple[ArchitectureElement, ...] = ()
    matrix_relationship_types: tuple[str, ...] = ()

    @property
    def view_id(self) -> str:
        return self.view_definition.view_id

    @property
    def element_ids(self) -> tuple[str, ...]:
        return tuple(item.stable_id for item in self.elements)

    @property
    def relationship_ids(self) -> tuple[str, ...]:
        return tuple(item.stable_id for item in self.relationships)


@dataclass(frozen=True, slots=True)
class ArchitectureViewGenerator:
    framework_profile_id: str
    view_id: str
    presentation: str

    @property
    def view_definition(self) -> ViewDefinition:
        return get_view_definition(self.framework_profile_id, self.view_id)

    def project(self, snapshot: ArchitectureSnapshot) -> ArchitectureViewProjection:
        """Snapshot verisini katalog filtresine göre salt-okunur projekte eder."""

        if not isinstance(snapshot, ArchitectureSnapshot):
            raise TypeError("Görünümün tek veri kaynağı ArchitectureSnapshot olmalıdır.")
        if snapshot.framework_profile_id.casefold() != self.framework_profile_id.casefold():
            raise ArchitectureViewError(
                f"{self.view_id} görünümü {self.framework_profile_id} profiline aittir."
            )

        definition = self.view_definition
        allowed_element_types = set(definition.required_element_types)
        allowed_element_types.update(definition.optional_element_types)
        for group in definition.required_any_of_element_types:
            allowed_element_types.update(group)

        allowed_relationship_types = set(definition.required_relationships)
        allowed_relationship_types.update(definition.optional_relationships)
        for group in definition.required_any_of_relationships:
            allowed_relationship_types.update(group)

        blocking_targets = {
            finding.target_id
            for finding in snapshot.validation_findings
            if finding.blocking
            and finding.severity == "error"
            and finding.target_id
            and (not finding.view_id or finding.view_id == self.view_id)
        }
        elements = tuple(sorted(
            (
                item for item in snapshot.elements
                if item.review_status == REVIEW_APPROVED
                and item.stable_id not in blocking_targets
                and item.element_type in allowed_element_types
            ),
            key=lambda item: (item.element_type.casefold(), item.stable_id),
        ))
        element_ids = {item.stable_id for item in elements}
        relationships = tuple(sorted(
            (
                item for item in snapshot.relationships
                if item.review_status == REVIEW_APPROVED
                and item.stable_id not in blocking_targets
                and item.relationship_type in allowed_relationship_types
                and item.source_element_id in element_ids
                and item.target_element_id in element_ids
            ),
            key=lambda item: (
                item.relationship_type.casefold(),
                item.source_element_id,
                item.target_element_id,
                item.stable_id,
            ),
        ))

        row_elements: tuple[ArchitectureElement, ...] = ()
        column_elements: tuple[ArchitectureElement, ...] = ()
        matrix_relationship_types: tuple[str, ...] = ()
        if self.presentation == PRESENTATION_MATRIX:
            row_types, column_types, matrix_relationship_types = _MATRIX_AXES[self.view_id]
            row_elements = tuple(item for item in elements if item.element_type in row_types)
            column_elements = tuple(item for item in elements if item.element_type in column_types)

        return ArchitectureViewProjection(
            view_definition=definition,
            presentation=self.presentation,
            elements=elements,
            relationships=relationships,
            row_elements=row_elements,
            column_elements=column_elements,
            matrix_relationship_types=matrix_relationship_types,
        )


def _profile_for_view(view_id: str) -> str:
    if view_id in DODAF_RENDER_VIEW_IDS:
        return "dodaf"
    if view_id in NAF_RENDER_VIEW_IDS:
        return "naf"
    raise ArchitectureViewError(f"Desteklenmeyen ilk-aşama görünümü: {view_id}")


_GENERATORS: dict[tuple[str, str], ArchitectureViewGenerator] = {}
for _view_id in SUPPORTED_RENDER_VIEW_IDS:
    _profile = _profile_for_view(_view_id)
    _GENERATORS[(_profile, _view_id)] = ArchitectureViewGenerator(
        framework_profile_id=_profile,
        view_id=_view_id,
        presentation=_PRESENTATION_BY_VIEW[_view_id],
    )

VIEW_GENERATORS: Mapping[tuple[str, str], ArchitectureViewGenerator] = MappingProxyType(
    _GENERATORS
)


def get_view_generator(
    framework_profile_id: str,
    view_id: str,
) -> ArchitectureViewGenerator:
    if not isinstance(framework_profile_id, str) or not isinstance(view_id, str):
        raise TypeError("Profil ve görünüm kimlikleri string olmalıdır.")
    # Kanonik katalog kimlikleri kasıtlı olarak exact-match'tir. Eski NAF
    # etiketleri, boşluklu veya farklı case aliaslar render kimliği olamaz.
    key = (framework_profile_id, view_id)
    try:
        return VIEW_GENERATORS[key]
    except KeyError as error:
        raise ArchitectureViewError(
            f"Desteklenmeyen profil/görünüm: {framework_profile_id}/{view_id}"
        ) from error


def project_view(snapshot: ArchitectureSnapshot, view_id: str) -> ArchitectureViewProjection:
    if not isinstance(snapshot, ArchitectureSnapshot):
        raise TypeError("Görünümün tek veri kaynağı ArchitectureSnapshot olmalıdır.")
    generator = get_view_generator(snapshot.framework_profile_id, view_id)
    return generator.project(snapshot)


__all__ = [
    "ArchitectureViewError",
    "ArchitectureViewGenerator",
    "ArchitectureViewProjection",
    "DODAF_RENDER_VIEW_IDS",
    "NAF_RENDER_VIEW_IDS",
    "PRESENTATION_DIAGRAM",
    "PRESENTATION_MATRIX",
    "PRESENTATION_TABLE",
    "SUPPORTED_RENDER_VIEW_IDS",
    "VIEW_GENERATORS",
    "get_view_generator",
    "project_view",
]
