# -*- coding: utf-8 -*-

import ast
from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import mimari_cerceve_gorunumleri as views
import mimari_cerceve_model as model
import mimari_cerceve_render as render


@dataclass(frozen=True)
class _ApprovedRecord:
    record: model.ArchitectureElement | model.ArchitectureRelationship
    proposal: model.CandidateProposal
    decision: model.ReviewDecision


def _evidence(requirement_id, text):
    document = "Sistem Gereksinimleri"
    location = f"Gereksinim {requirement_id}"
    return model.EvidenceLink(
        source_item_id=requirement_id,
        source_document=document,
        source_location=location,
        evidence_text=text,
        evidence_fingerprint=model.evidence_fingerprint_for(
            document, requirement_id, location, text,
        ),
        confidence_score=0.95,
        derivation_kind=model.DERIVATION_DETERMINISTIC,
        producer="test_mimari_cerceve_render",
        producer_version="1.0",
    )


def _approved_element(profile, requirement_id, name, element_type):
    text = f"{name} adlı {element_type} mimari öğesi kaynakta açıkça tanımlıdır."
    evidence = _evidence(requirement_id, text)
    payload = {
        "identity_key": name,
        "name": name,
        "element_type": element_type,
        "description": text,
    }
    proposal = model.CandidateProposal(
        identity_key=name,
        framework_profile_id=profile,
        proposal_type="element",
        title=f"{name} adayı",
        rationale="Birebir kaynak kanıtı kullanıldı.",
        proposed_payload=payload,
        payload_evidence_ids={key: (evidence.evidence_id,) for key in payload},
        source_requirement_ids=(requirement_id,),
        evidence_text=text,
        confidence_score=0.95,
        evidence_links=(evidence,),
        proposal_origin=model.DERIVATION_MODEL_SUGGESTION,
    )
    decision = model.ReviewDecision.for_proposal(
        proposal,
        model.DECISION_ACCEPT,
        "Sistem Mimarı",
        "2026-08-14T09:00:00+03:00",
    )
    element = model.ArchitectureElement(
        identity_key=name,
        framework_profile_id=profile,
        name=name,
        element_type=element_type,
        description=text,
        source_requirement_ids=(requirement_id,),
        evidence_text=text,
        confidence_score=0.95,
        evidence_links=(evidence,),
        review_status=model.REVIEW_APPROVED,
        derivation_kind=model.DERIVATION_MODEL_SUGGESTION,
        source_proposal_id=proposal.proposal_id,
        approval_decision_id=decision.decision_id,
    )
    return _ApprovedRecord(element, proposal, decision)


def _approved_relationship(
    profile,
    requirement_id,
    name,
    relationship_type,
    source_element_id,
    target_element_id,
):
    text = (
        f"{name} adlı {relationship_type} ilişkisi kaynakta açıkça "
        f"{source_element_id} ve {target_element_id} uçları arasında tanımlıdır."
    )
    evidence = _evidence(requirement_id, text)
    payload = {
        "identity_key": name,
        "name": name,
        "relationship_type": relationship_type,
        "description": text,
    }
    proposal = model.CandidateProposal(
        identity_key=name,
        framework_profile_id=profile,
        proposal_type="relationship",
        title=f"{name} adayı",
        rationale="Birebir kaynak kanıtı kullanıldı.",
        proposed_payload=payload,
        payload_evidence_ids={key: (evidence.evidence_id,) for key in payload},
        source_requirement_ids=(requirement_id,),
        evidence_text=text,
        confidence_score=0.95,
        evidence_links=(evidence,),
        source_element_id=source_element_id,
        target_element_id=target_element_id,
        proposal_origin=model.DERIVATION_MODEL_SUGGESTION,
    )
    decision = model.ReviewDecision.for_proposal(
        proposal,
        model.DECISION_ACCEPT,
        "Sistem Mimarı",
        "2026-08-14T09:00:00+03:00",
    )
    relationship = model.ArchitectureRelationship(
        identity_key=name,
        framework_profile_id=profile,
        name=name,
        relationship_type=relationship_type,
        source_element_id=source_element_id,
        target_element_id=target_element_id,
        description=text,
        source_requirement_ids=(requirement_id,),
        evidence_text=text,
        confidence_score=0.95,
        evidence_links=(evidence,),
        review_status=model.REVIEW_APPROVED,
        derivation_kind=model.DERIVATION_MODEL_SUGGESTION,
        source_proposal_id=proposal.proposal_id,
        approval_decision_id=decision.decision_id,
    )
    return _ApprovedRecord(relationship, proposal, decision)


def _snapshot(
    profile,
    selected_views,
    approved_records=(),
    *,
    findings=(),
    extra_proposals=(),
    reverse=False,
):
    approved_records = tuple(approved_records)
    elements = tuple(
        item.record for item in approved_records
        if isinstance(item.record, model.ArchitectureElement)
    )
    relationships = tuple(
        item.record for item in approved_records
        if isinstance(item.record, model.ArchitectureRelationship)
    )
    proposals = (*tuple(item.proposal for item in approved_records), *tuple(extra_proposals))
    decisions = tuple(item.decision for item in approved_records)
    if reverse:
        elements = tuple(reversed(elements))
        relationships = tuple(reversed(relationships))
        proposals = tuple(reversed(proposals))
        decisions = tuple(reversed(decisions))
    return model.ArchitectureSnapshot(
        identity_key="render-test-snapshot",
        project_id="render-test-project",
        name="Mimari Render Testi",
        framework_profile_id=profile,
        framework_version="2.02" if profile == "dodaf" else "4.1",
        version="v0001",
        status=model.SNAPSHOT_DRAFT,
        created_at="2026-08-14T09:10:00+03:00",
        elements=elements,
        relationships=relationships,
        candidate_proposals=proposals,
        review_decisions=decisions,
        validation_findings=tuple(findings),
        selected_view_ids=tuple(selected_views),
    )


def _sv1_records(system_a_name="Fren Sistemi", extras=()):
    system_a = _approved_element("dodaf", "SGD-001", system_a_name, "System")
    system_b = _approved_element("dodaf", "SGD-002", "Güç Sistemi", "System")
    flow = _approved_element("dodaf", "SGD-003", "Enerji Akışı", "SystemResourceFlow")
    source = _approved_relationship(
        "dodaf", "SGD-004", "Enerji kaynağı", "flow_source",
        flow.record.stable_id, system_a.record.stable_id,
    )
    target = _approved_relationship(
        "dodaf", "SGD-005", "Enerji hedefi", "flow_target",
        flow.record.stable_id, system_b.record.stable_id,
    )
    return (system_a, system_b, flow, source, target, *extras)


def _sv1_snapshot(**kwargs):
    return _snapshot("dodaf", ("SV-1",), _sv1_records(), **kwargs)


def _matrix_snapshot():
    activity = _approved_element("dodaf", "SGD-101", "Frenleme Faaliyeti", "OperationalActivity")
    function = _approved_element("dodaf", "SGD-102", "Frenleme Fonksiyonu", "SystemFunction")
    mapping = _approved_relationship(
        "dodaf", "SGD-103", "Faaliyet fonksiyon eşlemesi", "maps_to",
        activity.record.stable_id, function.record.stable_id,
    )
    return _snapshot("dodaf", ("SV-5a",), (activity, function, mapping))


def _av2_snapshot():
    term = _approved_element("dodaf", "SGD-201", "Fren", "DictionaryTerm")
    definition = _approved_element("dodaf", "SGD-202", "Fren Tanımı", "Definition")
    source = _approved_element("dodaf", "SGD-203", "Yetkili Sözlük", "AuthoritativeSource")
    defined = _approved_relationship(
        "dodaf", "SGD-204", "Terim tanım bağı", "defined_by",
        term.record.stable_id, definition.record.stable_id,
    )
    derived = _approved_relationship(
        "dodaf", "SGD-205", "Tanım kaynak bağı", "derived_from",
        definition.record.stable_id, source.record.stable_id,
    )
    return _snapshot("dodaf", ("AV-2",), (term, definition, source, defined, derived))


class RenderContractTests(unittest.TestCase):
    def test_renderer_rejects_mapping_and_duck_typed_source(self):
        snapshot = _sv1_snapshot()
        with self.assertRaises(TypeError):
            render.render_view(snapshot.to_dict(), "SV-1")

        class FakeSnapshot:
            def to_dict(self):
                return snapshot.to_dict()

        with self.assertRaises(TypeError):
            render.render_view(FakeSnapshot(), "SV-1")

    def test_supported_registry_is_exact_profile_view_allowlist(self):
        expected = {
            *(('dodaf', item) for item in ("AV-2", "SV-1", "SV-2", "SV-4", "SV-5a", "SV-7")),
            *(('naf', item) for item in ("L2-L3", "L3", "L4", "L8", "P2", "P3", "P4", "L4-P4", "P8")),
        }
        self.assertEqual(set(views.VIEW_GENERATORS), expected)
        self.assertNotIn(("dodaf", "AV-1"), views.VIEW_GENERATORS)
        self.assertNotIn(("dodaf", "SvcV-1"), views.VIEW_GENERATORS)

    def test_unknown_wrong_case_wrong_profile_and_unselected_views_are_rejected(self):
        snapshot = _sv1_snapshot()
        for view_id in ("sv-1", "SV-1 ", "AV-1", "L3"):
            with self.subTest(view_id=view_id):
                with self.assertRaises(render.ArchitectureRenderError):
                    render.render_view(snapshot, view_id)
        selected = _snapshot("dodaf", ("SV-2",), _sv1_records())
        with self.assertRaises(render.ArchitectureRenderError):
            render.render_view(selected, "SV-1")

    def test_modules_are_headless_and_model_free(self):
        forbidden = {
            "tkinter", "Arayüz", "llm_handler", "lmstudio_model",
            "mimari_cerceve_gemma", "mimari_cerceve_cikarim",
            "hardware_image_provider",
        }
        for filename in ("mimari_cerceve_render.py", "mimari_cerceve_gorunumleri.py"):
            tree = ast.parse(Path(filename).read_text(encoding="utf-8"))
            roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots.add(node.module.split(".")[0])
            self.assertFalse(roots & forbidden, (filename, roots & forbidden))


class MissingInputGateTests(unittest.TestCase):
    def test_missing_sv1_inputs_block_without_svg_and_list_requirements(self):
        snapshot = _snapshot("dodaf", ("SV-1",))

        result = render.render_view(snapshot, "SV-1")

        self.assertEqual(result.status, render.RENDER_STATUS_BLOCKED)
        self.assertIsNone(result.svg)
        joined = " ".join(result.missing_inputs)
        for expected in ("System", "SystemResourceFlow", "flow_source", "flow_target"):
            self.assertIn(expected, joined)

    def test_empty_l2_l3_is_blocked_without_placeholder_schema(self):
        snapshot = _snapshot("naf", ("L2-L3",))

        result = render.render_view(snapshot, "L2-L3")

        self.assertIsNone(result.svg)
        self.assertIn("Node|Needline", " ".join(result.missing_inputs))

    def test_l2_l3_renders_only_after_real_node_content_exists(self):
        node = _approved_element(
            "naf", "SGD-300", "Komuta Düğümü", "Node"
        )
        snapshot = _snapshot("naf", ("L2-L3",), (node,))

        result = render.render_view(snapshot, "L2-L3")

        self.assertTrue(result.rendered)
        self.assertIn(node.record.stable_id, result.included_element_ids)

    def test_blocking_snapshot_finding_for_view_blocks_but_other_view_does_not(self):
        base = _sv1_snapshot()
        flow = next(item for item in base.elements if item.element_type == "SystemResourceFlow")
        blocking = model.ValidationFinding(
            code="stale_item_used",
            severity="error",
            message="Kayıt stale.",
            target_id=flow.stable_id,
            view_id="SV-1",
            blocking=True,
        )
        blocked = _snapshot("dodaf", ("SV-1",), _sv1_records(), findings=(blocking,))
        self.assertIsNone(render.render_view(blocked, "SV-1").svg)

        other = model.ValidationFinding(
            code="stale_item_used",
            severity="error",
            message="Başka görünüm kaydı stale.",
            target_id=flow.stable_id,
            view_id="SV-2",
            blocking=True,
        )
        unaffected = _snapshot(
            "dodaf", ("SV-1", "SV-2"), _sv1_records(), findings=(other,)
        )
        self.assertTrue(render.render_view(unaffected, "SV-1").rendered)

    def test_selected_view_batch_keeps_good_and_blocked_results_separate(self):
        snapshot = _snapshot("dodaf", ("SV-1", "SV-2"), _sv1_records())

        results = {item.view_id: item for item in render.render_selected_views(snapshot)}

        self.assertTrue(results["SV-1"].rendered)
        self.assertFalse(results["SV-2"].rendered)
        self.assertIsNone(results["SV-2"].svg)


class DeterministicSvgTests(unittest.TestCase):
    def test_same_and_permuted_snapshot_render_byte_for_byte_identically(self):
        records = _sv1_records()
        normal = _snapshot("dodaf", ("SV-1",), records)
        reversed_snapshot = _snapshot("dodaf", ("SV-1",), records, reverse=True)

        first = render.render_view(normal, "SV-1")
        second = render.render_view(normal, "SV-1")
        permuted = render.render_view(reversed_snapshot, "SV-1")

        self.assertEqual(first.svg, second.svg)
        self.assertEqual(first.svg, permuted.svg)
        self.assertEqual(first.content_sha256, second.content_sha256)

    def test_unrelated_records_and_candidates_do_not_change_or_leak_into_svg(self):
        normal = _sv1_snapshot()
        unrelated = _approved_element(
            "dodaf", "SGD-099", "UNRELATED_SECRET", "Service"
        )
        extra_relation = _approved_relationship(
            "dodaf", "SGD-098", "UNRELATED_RELATION", "contains",
            unrelated.record.stable_id,
            normal.elements[0].stable_id,
        )
        candidate_only = _approved_element(
            "dodaf", "SGD-097", "UNMATERIALIZED_CANDIDATE_SECRET", "Service"
        )
        extended = _snapshot(
            "dodaf", ("SV-1",), (*_sv1_records(), unrelated, extra_relation),
            extra_proposals=(candidate_only.proposal,),
        )

        baseline_svg = render.render_view(normal, "SV-1").svg
        extended_svg = render.render_view(extended, "SV-1").svg

        self.assertEqual(baseline_svg, extended_svg)
        self.assertNotIn("UNRELATED_SECRET", extended_svg)
        self.assertNotIn("UNRELATED_RELATION", extended_svg)
        self.assertNotIn("UNMATERIALIZED_CANDIDATE_SECRET", extended_svg)

    def test_svg_is_well_formed_namespaced_safe_and_has_backlinks(self):
        malicious_name = 'Fren </text><script>alert(1)</script> " onload="x Sistemi'
        snapshot = _snapshot(
            "dodaf", ("SV-1",), _sv1_records(system_a_name=malicious_name)
        )

        result = render.render_view(snapshot, "SV-1")
        root = ET.fromstring(result.svg)

        self.assertEqual(root.tag, f"{{{render.SVG_NS}}}svg")
        self.assertEqual(root.get("role"), "img")
        self.assertEqual(root.get("data-render-kind"), "diagram")
        self.assertIsNotNone(root.find(f"{{{render.SVG_NS}}}title"))
        self.assertIsNotNone(root.find(".//*[@id='layer-edges']"))
        self.assertIsNotNone(root.find(".//*[@id='layer-nodes']"))
        self.assertIsNotNone(root.find(".//*[@id='layer-traceability']"))
        self.assertEqual(root.findall(f".//{{{render.SVG_NS}}}script"), [])
        self.assertEqual(root.findall(f".//{{{render.SVG_NS}}}foreignObject"), [])
        self.assertIn("<script>", "".join(root.itertext()))

        all_ids = [item.get("id") for item in root.iter() if item.get("id")]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for item in root.iter():
            for key in item.attrib:
                self.assertFalse(key.casefold().startswith("on"), (item.tag, key))
            href = item.get("href")
            if href:
                self.assertTrue(href.startswith("#"), href)
        self.assertTrue(root.findall(".//*[@data-requirement-id]"))
        self.assertTrue(root.findall(".//*[@data-evidence-id]"))
        self.assertTrue(root.findall(".//*[@data-architecture-id]"))

    def test_coordinates_are_finite_integer_tokens(self):
        root = ET.fromstring(render.render_view(_sv1_snapshot(), "SV-1").svg)
        coordinate_names = {
            "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r",
            "width", "height",
        }
        for element in root.iter():
            for name, value in element.attrib.items():
                if name in coordinate_names:
                    self.assertRegex(value, r"^-?\d+$")


class PresentationAndPersistenceTests(unittest.TestCase):
    def test_matrix_view_is_semantic_grid_with_real_mapping_cell(self):
        result = render.render_view(_matrix_snapshot(), "SV-5a")
        root = ET.fromstring(result.svg)

        self.assertTrue(result.rendered)
        self.assertEqual(result.render_kind, views.PRESENTATION_MATRIX)
        self.assertIsNotNone(root.find(".//*[@id='layer-matrix']"))
        self.assertIsNone(root.find(".//*[@id='layer-edges']"))
        cells = root.findall(".//*[@data-row-element-id]")
        self.assertEqual(len(cells), 1)
        self.assertTrue(cells[0].get("data-relationship-ids"))

    def test_dictionary_view_uses_table_structure(self):
        result = render.render_view(_av2_snapshot(), "AV-2")
        root = ET.fromstring(result.svg)

        table = root.find(".//*[@id='layer-table']")
        self.assertTrue(result.rendered)
        self.assertEqual(result.render_kind, views.PRESENTATION_TABLE)
        self.assertIsNotNone(table)
        self.assertEqual(table.get("role"), "table")
        self.assertGreaterEqual(len(root.findall(".//*[@role='row']")), 6)
        self.assertNotIn("belirsiz/eksik", result.svg)

    def test_atomic_writer_writes_only_rendered_svg(self):
        rendered = render.render_view(_sv1_snapshot(), "SV-1")
        blocked = render.render_view(_snapshot("dodaf", ("SV-1",)), "SV-1")
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "sv1.svg"
            written = render.write_view_svg(rendered, target)
            self.assertEqual(written, target)
            self.assertEqual(target.read_text(encoding="utf-8"), rendered.svg)
            with self.assertRaises(render.ViewRenderBlockedError):
                render.write_view_svg(blocked, Path(temp_dir) / "blocked.svg")
            self.assertFalse((Path(temp_dir) / "blocked.svg").exists())


if __name__ == "__main__":
    unittest.main()
