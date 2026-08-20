# -*- coding: utf-8 -*-

from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

import mimari_cerceve_dogrulama as validation
import mimari_cerceve_katalog as catalog
import mimari_cerceve_model as model


def _evidence(requirement_id="SGD-001", text="Fren Sistemi veri akışı gönderir."):
    document = "Sistem Gereksinimleri"
    location = f"Gereksinim {requirement_id}"
    return {
        "evidence_id": f"EV-{requirement_id}",
        "source_item_id": requirement_id,
        "source_document": document,
        "source_location": location,
        "evidence_text": text,
        "evidence_fingerprint": model.evidence_fingerprint_for(
            document, requirement_id, location, text,
        ),
        "confidence_score": 0.95,
        "derivation_kind": model.DERIVATION_DIRECT,
        "producer": "test",
        "producer_version": "1.0",
    }


def _element(item_id, name, element_type, evidence=None, **overrides):
    evidence = evidence or _evidence(item_id, f"{name} sistem mimarisi içinde tanımlıdır.")
    payload = {
        "stable_id": item_id,
        "identity_key": item_id.casefold(),
        "framework_profile_id": "dodaf",
        "name": name,
        "element_type": element_type,
        "description": evidence["evidence_text"],
        "source_requirement_ids": (evidence["source_item_id"],),
        "evidence_text": evidence["evidence_text"],
        "confidence_score": 0.95,
        "evidence_links": (evidence,),
        "review_status": model.REVIEW_APPROVED,
        "version": "v0001",
        "derivation_kind": model.DERIVATION_DETERMINISTIC,
    }
    payload.update(overrides)
    return payload


def _relationship(item_id, relationship_type, source, target, evidence=None, **overrides):
    evidence = evidence or _evidence(item_id, f"{source} ile {target} arasında akış vardır.")
    payload = {
        "stable_id": item_id,
        "identity_key": item_id.casefold(),
        "framework_profile_id": "dodaf",
        "name": relationship_type,
        "relationship_type": relationship_type,
        "source_element_id": source,
        "target_element_id": target,
        "description": evidence["evidence_text"],
        "source_requirement_ids": (evidence["source_item_id"],),
        "evidence_text": evidence["evidence_text"],
        "confidence_score": 0.94,
        "evidence_links": (evidence,),
        "review_status": model.REVIEW_APPROVED,
        "version": "v0001",
        "derivation_kind": model.DERIVATION_DETERMINISTIC,
    }
    payload.update(overrides)
    return payload


def _sv1_architecture():
    system_a = _element("SYS-A", "Fren Sistemi", "System")
    system_b = _element("SYS-B", "Güç Sistemi", "System")
    flow = _element("FLOW-1", "Enerji Akışı", "SystemResourceFlow")
    return {
        "framework_profile_id": "dodaf",
        "framework_version": "2.02",
        "status": "approved",
        "selected_view_ids": ("SV-1",),
        "elements": [system_a, system_b, flow],
        "relationships": [
            _relationship("REL-SRC", "flow_source", "FLOW-1", "SYS-A"),
            _relationship("REL-DST", "flow_target", "FLOW-1", "SYS-B"),
        ],
    }


def _codes(result):
    return {item.code for item in result.findings}


class ValidationOutcomeTests(unittest.TestCase):
    def test_three_validation_outcomes_are_separate_and_serializable(self):
        report = validation.validate_architecture(_sv1_architecture())

        self.assertEqual(
            report.view_generatability.dimension,
            validation.DIMENSION_VIEW_GENERATABILITY,
        )
        self.assertEqual(
            report.model_integrity.dimension,
            validation.DIMENSION_MODEL_INTEGRITY,
        )
        self.assertEqual(
            report.framework_conformance.dimension,
            validation.DIMENSION_FRAMEWORK_CONFORMANCE,
        )
        self.assertTrue(report.view_generatability.passed)
        self.assertTrue(report.model_integrity.passed)
        self.assertFalse(report.framework_conformance.passed)
        self.assertTrue(report.framework_conformance.aligned)
        self.assertFalse(report.framework_conformance.conformant)
        payload = report.to_dict()
        self.assertIn("view_generatability", payload)
        self.assertIn("model_integrity", payload)
        self.assertIn("framework_conformance", payload)

    def test_information_is_an_explicit_supported_finding_level(self):
        report = validation.validate_architecture(_sv1_architecture())
        severities = {item.severity for item in report.findings}
        self.assertIn("information", severities)
        finding = model.ValidationFinding(
            code="legacy-info", severity="info", message="Eski kayıt da geçerlidir."
        )
        self.assertEqual(finding.severity, "info")

    def test_unmapped_profile_records_prevent_aligned_draft_claim(self):
        architecture = _sv1_architecture()
        architecture["elements"].append(
            _element("UNMAPPED-1", "Profil dışı kayıt", "LogicalRequirement")
        )

        report = validation.validate_architecture(architecture)

        self.assertFalse(report.framework_conformance.aligned)
        self.assertIn(
            "dm2_concept_mapping_missing", _codes(report.framework_conformance)
        )


class ModelIntegrityRuleTests(unittest.TestCase):
    def test_missing_or_model_only_evidence_is_error(self):
        architecture = _sv1_architecture()
        architecture["elements"][0]["evidence_links"] = ()
        model_only = deepcopy(architecture["elements"][1]["evidence_links"][0])
        model_only["derivation_kind"] = model.DERIVATION_MODEL_SUGGESTION
        architecture["elements"][1]["evidence_links"] = (model_only,)

        result = validation.validate_model_integrity(architecture)

        self.assertFalse(result.passed)
        self.assertIn("missing_source_evidence", _codes(result))
        missing = [item for item in result.findings if item.code == "missing_source_evidence"]
        self.assertEqual(len(missing), 2)
        self.assertTrue(all(item.severity == "error" for item in missing))

    def test_evidence_must_cover_declared_requirement_id(self):
        architecture = _sv1_architecture()
        architecture["elements"][0]["source_requirement_ids"] = ("SGD-UNKNOWN",)

        result = validation.validate_model_integrity(architecture)

        finding = next(
            item for item in result.findings
            if item.code == "missing_source_evidence" and item.target_id == "SYS-A"
        )
        self.assertIn("SGD-UNKNOWN", finding.missing_fields)

    def test_dangling_relationship_is_error(self):
        architecture = _sv1_architecture()
        architecture["relationships"][0]["target_element_id"] = "UNKNOWN"

        result = validation.validate_model_integrity(architecture)

        self.assertIn("dangling_relationship", _codes(result))
        self.assertFalse(result.passed)

    def test_invalid_element_and_relationship_types_are_errors(self):
        architecture = _sv1_architecture()
        architecture["elements"][0]["element_type"] = "DragonTeleportSystem"
        architecture["relationships"][0]["relationship_type"] = "teleports_to"

        result = validation.validate_model_integrity(architecture)

        self.assertIn("invalid_element_type", _codes(result))
        self.assertIn("invalid_relationship_type", _codes(result))

    def test_unapproved_candidate_cannot_be_used_in_a_view(self):
        architecture = _sv1_architecture()
        architecture["elements"][0]["review_status"] = model.REVIEW_PENDING

        report = validation.validate_architecture(architecture)

        self.assertIn("unapproved_candidate_used", _codes(report.model_integrity))
        self.assertFalse(report.view_generatability.passed)

    def test_stale_item_is_rejected_and_management_state_is_checked(self):
        architecture = _sv1_architecture()
        architecture["source_record_ids"] = ["REC-1"]
        management_state = {
            "project_name": "Test",
            "framework_profile_id": "dodaf",
            "records": {"REC-1": {"status": "stale"}},
        }

        report = validation.validate_architecture(
            architecture, management_state=management_state
        )

        self.assertIn("stale_item_used", _codes(report.model_integrity))
        self.assertFalse(report.model_integrity.passed)

    def test_protocol_and_standard_names_must_exist_in_source_evidence(self):
        architecture = {
            "framework_profile_id": "naf",
            "framework_version": "4.1",
            "status": "approved",
            "selected_view_ids": ("L2-L3",),
            "elements": [
                _element(
                    "PROTO-1", "FlexRay", "Protocol",
                    _evidence("SGD-100", "Sistem veri aktarımı yapmalıdır."),
                    framework_profile_id="naf",
                ),
                _element(
                    "STD-1", "DO-178C", "Standard",
                    _evidence("SGD-101", "Yazılım güvenli geliştirilmelidir."),
                    framework_profile_id="naf",
                ),
            ],
            "relationships": [],
        }

        result = validation.validate_model_integrity(architecture)

        unsupported = [
            item for item in result.findings
            if item.code == "unsupported_protocol_or_standard"
        ]
        self.assertEqual(len(unsupported), 2)

    def test_protocol_name_is_not_accepted_as_part_of_an_unrelated_word(self):
        architecture = {
            "framework_profile_id": "naf",
            "framework_version": "4.1",
            "status": "approved",
            "selected_view_ids": ("L2-L3",),
            "elements": [
                _element(
                    "PROTO-CAN", "CAN", "Protocol",
                    _evidence("SGD-102", "Heyecan verisi kaydedilir."),
                    framework_profile_id="naf",
                ),
            ],
            "relationships": [],
        }

        result = validation.validate_model_integrity(architecture)

        self.assertIn("unsupported_protocol_or_standard", _codes(result))


class ViewGeneratabilityRuleTests(unittest.TestCase):
    def test_required_elements_and_relationships_are_reported_separately(self):
        architecture = _sv1_architecture()
        architecture["selected_view_ids"] = ("AV-2",)

        result = validation.validate_view_generatability(architecture)

        self.assertFalse(result.passed)
        self.assertIn("missing_required_element", _codes(result))
        self.assertIn("missing_required_relationship", _codes(result))

    def test_minimum_cardinality_is_enforced(self):
        architecture = _sv1_architecture()
        architecture["elements"] = [
            item for item in architecture["elements"] if item["stable_id"] != "SYS-B"
        ]
        architecture["relationships"] = [
            item for item in architecture["relationships"]
            if item["target_element_id"] != "SYS-B"
        ]

        result = validation.validate_view_generatability(architecture)

        self.assertIn("cardinality_violation", _codes(result))
        self.assertFalse(result.passed)

    def test_relationship_endpoint_cardinality_uses_element_types(self):
        architecture = _sv1_architecture()
        architecture["relationships"][0]["source_element_id"] = "SYS-B"

        result = validation.validate_view_generatability(architecture)

        self.assertIn("cardinality_violation", _codes(result))
        self.assertFalse(result.passed)

    def test_missing_scenario_state_and_time_are_explicit_findings(self):
        custom_view = model.ViewDefinition(
            framework_profile_id="dodaf",
            framework_version="2.02",
            view_id="TEST-CONTEXT",
            name="Bağlam Testi",
            purpose="Bağlam kapısını doğrulamak.",
            required_element_types=(),
            required_relationships=(),
            data_prerequisites=(
                "Gerekli senaryo, durum ve zaman bilgisi",
            ),
            export_type="structured_text",
            package="test",
        )
        architecture = _sv1_architecture()
        architecture["selected_view_ids"] = ("TEST-CONTEXT",)

        result = validation.validate_view_generatability(
            architecture, view_definitions=(custom_view,)
        )

        context_findings = [
            item for item in result.findings if item.code == "missing_view_context"
        ]
        self.assertEqual(
            {item.missing_fields[0] for item in context_findings},
            {"scenario", "state", "time"},
        )
        self.assertTrue(all(item.severity == "error" for item in context_findings))

        passed = validation.validate_view_generatability(
            architecture,
            view_definitions=(custom_view,),
            context_data={
                "scenarios": ["Normal işletim"],
                "states": ["Aktif"],
                "timeframes": ["2026-2027"],
            },
        )
        self.assertTrue(passed.passed)


class FrameworkMappingRuleTests(unittest.TestCase):
    def test_dodaf_mapping_table_covers_catalog_but_pes_absence_blocks_claim(self):
        for view in catalog.DODAF_PROFILE.view_definitions:
            element_types = set(view.required_element_types)
            relationship_types = set(view.required_relationships)
            for group in view.required_any_of_element_types:
                element_types.update(group)
            for group in view.required_any_of_relationships:
                relationship_types.update(group)
            self.assertTrue(
                element_types.issubset(validation.DODAF_DM2_ELEMENT_MAPPINGS)
            )
            self.assertTrue(
                relationship_types.issubset(validation.DODAF_DM2_RELATIONSHIP_MAPPINGS)
            )

        result = validation.validate_framework_conformance(_sv1_architecture())
        self.assertEqual(result.status, "DoDAF ile hizalı taslak")
        self.assertNotIn("DoDAF uyumlu", result.status)
        self.assertIn("pes_export_not_implemented", _codes(result))

    def test_naf_im_archimate_table_covers_catalog_and_is_immutable(self):
        for view in catalog.NAF_PROFILE.view_definitions:
            element_types = set(view.required_element_types)
            relationship_types = set(view.required_relationships)
            for group in view.required_any_of_element_types:
                element_types.update(group)
            for group in view.required_any_of_relationships:
                relationship_types.update(group)
            self.assertTrue(
                element_types.issubset(validation.NAF_ARCHIMATE_ELEMENT_MAPPINGS)
            )
            self.assertTrue(
                relationship_types.issubset(validation.NAF_ARCHIMATE_RELATIONSHIP_MAPPINGS)
            )
        with self.assertRaises(TypeError):
            validation.NAF_ARCHIMATE_ELEMENT_MAPPINGS["X"] = None
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            validation.NAF_ARCHIMATE_ELEMENT_MAPPINGS["Node"].status = "missing"

    def test_wrong_archimate_32_specialization_fails_mandatory_semantics(self):
        node = _element(
            "NODE-1", "Komuta Düğümü", "Node",
            _evidence("SGD-200", "Komuta Düğümü tanımlıdır."),
            framework_profile_id="naf",
        )
        architecture = {
            "framework_profile_id": "naf",
            "framework_version": "4.1",
            "status": "approved",
            "selected_view_ids": ("L2-L3",),
            "elements": [node],
            "relationships": [],
        }

        result = validation.validate_framework_conformance(
            architecture,
            application_profile={
                "name": "ArchiMate",
                "version": "3.2",
                "element_specializations": {"NODE-1": "Contract"},
            },
        )

        self.assertFalse(result.passed)
        self.assertIn("archimate_specialization_mismatch", _codes(result))
        self.assertIn("NAF ile hizalı taslak", result.status)
        self.assertNotIn("NAF uyumlu", result.status)


if __name__ == "__main__":
    unittest.main()
