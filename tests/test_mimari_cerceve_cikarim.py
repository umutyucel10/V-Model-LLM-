# -*- coding: utf-8 -*-

from copy import deepcopy
import json
from pathlib import Path
import unittest

import etki_analizi_izlenebilirlik as traceability
import mimari_cerceve_cikarim as extraction
import mimari_cerceve_render as rendering
import mimari_cerceve_yonetim as management
from mimari_cerceve_model import (
    DECISION_DEFER,
    DERIVATION_MODEL_SUGGESTION,
    REVIEW_PENDING,
)


def _flat_data():
    return {
        "TID-001": {
            "type": "TID",
            "ID": "TID-001",
            "content": "Platform güvenli güç dağıtımı sağlamalıdır.",
            "bound_to": "Yok",
        },
        "SGD-001": {
            "type": "SGD",
            "ID": "SGD-001",
            "content": "Güç Sistemi giriş gerilimi en fazla 28 V olmalıdır.",
            "bound_to": "TID-001",
        },
        "STT-001": {
            "type": "STT",
            "ID": "STT-001",
            "content": (
                "Fren Kontrol Sistemi durum mesajını Güç Yönetim Sistemi'ne "
                "CAN arayüzü üzerinden gönderir."
            ),
            "bound_to": "SGD-001",
        },
        "SITET-001": {
            "type": "SITET",
            "ID": "SITET-001",
            "content": "Giriş gerilimi ölçülmelidir.",
            "bound_to": "SGD-001",
        },
    }


def _report(flat):
    return traceability.build_traceability_map(
        "Mimari Çıkarım Testi",
        flat_data=flat,
        persist=False,
        check_lm_studio=False,
    )


def _extract(flat=None):
    data = flat or _flat_data()
    return extraction.extract_architecture_candidates(data, _report(data))


def _element_candidates(result, element_type):
    return [
        item for item in result.candidates
        if item.proposal_type == "element"
        and item.proposed_payload["element_type"] == element_type
    ]


def _relationship_candidates(result, relationship_type):
    return [
        item for item in result.candidates
        if item.proposal_type == "relationship"
        and item.proposed_payload["relationship_type"] == relationship_type
    ]


class DeterministicArchitectureExtractionTests(unittest.TestCase):
    def test_bound_to_builds_requirement_hierarchy_without_mutating_sources(self):
        flat = _flat_data()
        report = _report(flat)
        flat_before = deepcopy(flat)
        report_before = deepcopy(report)

        result = extraction.extract_architecture_candidates(flat, report)

        self.assertEqual(flat, flat_before)
        self.assertEqual(report, report_before)
        requirements = _element_candidates(result, "LogicalRequirement")
        self.assertEqual(
            {item.source_requirement_ids[0] for item in requirements},
            {"TID-001", "SGD-001", "STT-001"},
        )
        hierarchy = _relationship_candidates(result, "derived_from")
        self.assertEqual(len(hierarchy), 2)
        self.assertTrue(all(item.source_element_id for item in hierarchy))
        self.assertTrue(all(item.target_element_id for item in hierarchy))
        self.assertTrue(all(item.review_status == REVIEW_PENDING for item in result.candidates))
        self.assertTrue(all(item.initial_decision == DECISION_DEFER for item in result.candidates))
        self.assertNotIn("SITET-001", result.processed_requirement_ids)

    def test_measure_and_constraint_are_only_built_from_verbatim_number_unit(self):
        result = _extract()

        measures = _element_candidates(result, "Measure")
        constraints = _element_candidates(result, "ResourceConstraint")
        self.assertEqual(len(measures), 1)
        self.assertEqual(len(constraints), 1)
        for candidate in (measures[0], constraints[0]):
            self.assertEqual(candidate.proposed_payload["name"], "28 V")
            self.assertEqual(candidate.source_requirement_ids, ("SGD-001",))
            self.assertEqual(
                candidate.evidence_text,
                "Güç Sistemi giriş gerilimi en fazla 28 V olmalıdır.",
            )
            self.assertIn("28 V", candidate.evidence_links[0].evidence_text)

    def test_explicit_system_interface_and_directional_flow_are_candidates(self):
        result = _extract()

        system_names = {
            item.proposed_payload["name"]
            for item in _element_candidates(result, "System")
        }
        self.assertIn("Fren Kontrol Sistemi", system_names)
        self.assertIn("Güç Yönetim Sistemi", system_names)
        port_names = {
            item.proposed_payload["name"]
            for item in _element_candidates(result, "Port")
        }
        self.assertIn("CAN arayüzü", port_names)
        flow_names = {
            item.proposed_payload["name"]
            for item in _element_candidates(result, "ResourceFlow")
        }
        self.assertIn("durum mesajını", flow_names)
        self.assertEqual(len(_element_candidates(result, "SystemResourceFlow")), 1)
        self.assertEqual(len(_relationship_candidates(result, "flow_source")), 1)
        self.assertEqual(len(_relationship_candidates(result, "flow_target")), 1)
        self.assertEqual(len(_relationship_candidates(result, "connects")), 1)

    def test_dodaf_profile_flow_slice_does_not_require_generic_resource_flow_approval(self):
        flat = _flat_data()
        result = extraction.extract_architecture_candidates(
            flat, _report(flat), framework_profile_id="dodaf",
        )

        generic_flows = _element_candidates(result, "ResourceFlow")
        system_flows = _element_candidates(result, "SystemResourceFlow")
        endpoint_relationships = [
            *_relationship_candidates(result, "flow_source"),
            *_relationship_candidates(result, "flow_target"),
        ]
        self.assertEqual(len(generic_flows), 1)
        self.assertEqual(len(system_flows), 1)
        self.assertEqual(len(endpoint_relationships), 2)
        generic_flow_id = extraction.stable_id_for(
            "ARCH-ELEMENT",
            {
                "profile": "dodaf",
                "element_type": "ResourceFlow",
                "identity_key": generic_flows[0].identity_key,
            },
        )
        self.assertTrue(all(
            item.source_element_id == system_flows[0].target_stable_id
            for item in endpoint_relationships
        ))
        self.assertTrue(all(
            item.source_element_id != generic_flow_id
            for item in endpoint_relationships
        ))

        state = management.create_management_state(
            "DoDAF Gerçek Akış Fixture Testi",
            result.candidates,
            framework_profile_id="dodaf",
        )
        approved_types = {"System", "SystemResourceFlow", "flow_source", "flow_target"}
        for record_id, record in tuple(state.records.items()):
            payload = record.proposal.proposed_payload
            entity_type = payload.get("element_type", payload.get("relationship_type"))
            if entity_type in approved_types:
                management.approve_candidate(state, record_id, "Test Mimarı")

        generic_record = next(
            record for record in state.records.values()
            if record.proposal.proposal_id == generic_flows[0].proposal_id
        )
        self.assertEqual(generic_record.status, management.STATUS_CANDIDATE)

        snapshot = management.build_working_snapshot(state, ("SV-1",))
        element_ids = {item.stable_id for item in snapshot.elements}
        self.assertNotIn(generic_flow_id, element_ids)
        self.assertTrue(all(
            relationship.source_element_id in element_ids
            and relationship.target_element_id in element_ids
            for relationship in snapshot.relationships
        ))
        rendered = rendering.render_view(snapshot, "SV-1")
        self.assertEqual(rendered.status, rendering.RENDER_STATUS_RENDERED)
        self.assertIsNotNone(rendered.svg)

    def test_profile_specific_candidates_enable_dodaf_sv1_and_naf_l3_slices(self):
        flat = _flat_data()
        report = _report(flat)
        dodaf = extraction.extract_architecture_candidates(
            flat, report, framework_profile_id="dodaf",
        )
        naf = extraction.extract_architecture_candidates(
            flat, report, framework_profile_id="naf",
        )

        self.assertTrue(_element_candidates(dodaf, "SystemResourceFlow"))
        self.assertTrue(_element_candidates(naf, "LogicalActiveResource"))
        self.assertTrue(_element_candidates(naf, "LogicalInteraction"))
        self.assertTrue(_element_candidates(naf, "LogicalPassiveResource"))
        for relation_type in ("interaction_source", "interaction_target", "conveys"):
            self.assertTrue(_relationship_candidates(naf, relation_type))
        self.assertTrue(all(
            item.review_status == REVIEW_PENDING
            for item in (*dodaf.candidates, *naf.candidates)
        ))

    def test_explicit_user_approval_enables_profile_views_end_to_end(self):
        flat = _flat_data()
        report = _report(flat)
        for profile_id, view_id in (("dodaf", "SV-1"), ("naf", "L3")):
            with self.subTest(profile=profile_id, view=view_id):
                result = extraction.extract_architecture_candidates(
                    flat, report, framework_profile_id=profile_id,
                )
                state = management.create_management_state(
                    "Mimari Çıkarım Görünüm Testi",
                    result.candidates,
                    framework_profile_id=profile_id,
                )
                for record_id in tuple(state.records):
                    management.approve_candidate(state, record_id, "Test Mimarı")

                snapshot = management.build_working_snapshot(state, (view_id,))
                rendered = rendering.render_view(snapshot, view_id)

                self.assertEqual(rendered.status, rendering.RENDER_STATUS_RENDERED)
                self.assertIsNotNone(rendered.svg)
                self.assertTrue(rendered.included_element_ids)
                self.assertTrue(rendered.included_relationship_ids)

    def test_repeated_named_system_merges_all_verbatim_source_evidence(self):
        flat = {
            "SGD-101": {
                "type": "SGD", "ID": "SGD-101",
                "content": "Fren Kontrol Sistemi 28 V ile çalışmalıdır.",
                "bound_to": "Yok",
            },
            "STT-101": {
                "type": "STT", "ID": "STT-101",
                "content": "Fren Kontrol Sistemi durum mesajını kaydetmelidir.",
                "bound_to": "SGD-101",
            },
        }

        result = extraction.extract_architecture_candidates(flat, _report(flat))
        systems = [
            item for item in _element_candidates(result, "System")
            if item.proposed_payload["name"] == "Fren Kontrol Sistemi"
        ]

        self.assertEqual(len(systems), 1)
        self.assertEqual(systems[0].source_requirement_ids, ("SGD-101", "STT-101"))
        self.assertEqual(len(systems[0].evidence_links), 2)
        self.assertEqual(
            {item.evidence_text for item in systems[0].evidence_links},
            {flat["SGD-101"]["content"], flat["STT-101"]["content"]},
        )

    def test_receive_expression_reverses_source_and_target_without_guessing(self):
        flat = {
            "SGD-030": {
                "type": "SGD",
                "ID": "SGD-030",
                "content": (
                    "Güç Yönetim Sistemi durum mesajını Fren Kontrol Sistemi'nden alır."
                ),
                "bound_to": "Yok",
            },
        }

        result = extraction.extract_architecture_candidates(flat, _report(flat))
        systems = {
            item.proposed_payload["name"]: item
            for item in _element_candidates(result, "System")
        }
        flow = _element_candidates(result, "SystemResourceFlow")[0]
        dodaf_flow_id = extraction.stable_id_for(
            "ARCH-ELEMENT",
            {
                "profile": "dodaf",
                "element_type": "SystemResourceFlow",
                "identity_key": flow.identity_key,
            },
        )
        source_relation = next(
            item for item in _relationship_candidates(result, "flow_source")
            if item.source_element_id == dodaf_flow_id
        )
        target_relation = next(
            item for item in _relationship_candidates(result, "flow_target")
            if item.source_element_id == dodaf_flow_id
        )

        self.assertEqual(source_relation.source_element_id, dodaf_flow_id)
        self.assertEqual(source_relation.target_element_id, extraction.stable_id_for(
            "ARCH-ELEMENT",
            {"profile": "dodaf", "element_type": "System", "identity_key": "fren-kontrol-sistemi"},
        ))
        self.assertEqual(target_relation.target_element_id, extraction.stable_id_for(
            "ARCH-ELEMENT",
            {"profile": "dodaf", "element_type": "System", "identity_key": "guc-yonetim-sistemi"},
        ))
        self.assertEqual(set(systems), {"Güç Yönetim Sistemi", "Fren Kontrol Sistemi"})

    def test_send_expression_uses_explicit_target_when_subject_is_second(self):
        flat = {
            "STT-031": {
                "type": "STT",
                "ID": "STT-031",
                "content": (
                    "Güç Yönetim Sistemi'ne Fren Kontrol Sistemi "
                    "durum mesajını gönderir."
                ),
                "bound_to": "Yok",
            },
        }

        result = extraction.extract_architecture_candidates(flat, _report(flat))
        source_relation = _relationship_candidates(result, "flow_source")[0]
        target_relation = _relationship_candidates(result, "flow_target")[0]

        self.assertEqual(source_relation.target_element_id, extraction.stable_id_for(
            "ARCH-ELEMENT",
            {"profile": "dodaf", "element_type": "System", "identity_key": "fren-kontrol-sistemi"},
        ))
        self.assertEqual(target_relation.target_element_id, extraction.stable_id_for(
            "ARCH-ELEMENT",
            {"profile": "dodaf", "element_type": "System", "identity_key": "guc-yonetim-sistemi"},
        ))

    def test_three_system_sentence_with_missing_target_does_not_guess_first_two(self):
        flat = {
            "STT-032": {
                "type": "STT",
                "ID": "STT-032",
                "content": (
                    "Alfa Sistemi ve Beta Sistemi izlenirken Gama Sistemi "
                    "radar mesajını gönderir."
                ),
                "bound_to": "Yok",
            },
        }

        result = extraction.extract_architecture_candidates(flat, _report(flat))

        self.assertEqual(_relationship_candidates(result, "flow_source"), [])
        self.assertEqual(_relationship_candidates(result, "flow_target"), [])
        self.assertIn(
            "flow_endpoint_missing",
            {item.code for item in result.information_gaps},
        )
        self.assertEqual(
            {item.proposed_payload["name"] for item in _element_candidates(result, "System")},
            {"Alfa Sistemi", "Beta Sistemi", "Gama Sistemi"},
        )

    def test_missing_measure_unit_interface_name_and_flow_endpoint_are_separate_gaps(self):
        flat = {
            "SGD-009": {
                "type": "SGD",
                "ID": "SGD-009",
                "content": "Sistem arayüz üzerinden 12 değerinde veri göndermelidir.",
                "bound_to": "TID-404",
            },
        }

        result = extraction.extract_architecture_candidates(flat, _report(flat))
        codes = {item.code for item in result.information_gaps}

        self.assertIn("missing_bound_target", codes)
        self.assertIn("measurement_unit_missing", codes)
        self.assertIn("system_name_missing", codes)
        self.assertIn("interface_name_missing", codes)
        self.assertIn("flow_endpoint_missing", codes)
        self.assertEqual(_element_candidates(result, "Measure"), [])
        self.assertTrue(all("CAN" not in json.dumps(item.to_dict(), ensure_ascii=False) for item in result.candidates))

    def test_result_round_trip_preserves_nested_candidate_and_gap_types(self):
        result = _extract()
        payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))

        restored = extraction.ArchitectureExtractionResult.from_dict(payload)

        self.assertEqual(restored.to_dict(), result.to_dict())
        self.assertIsInstance(restored.candidates[0], type(result.candidates[0]))
        self.assertTrue(all(isinstance(item, extraction.InformationGap) for item in restored.information_gaps))

    def test_extraction_module_has_no_ui_dependency(self):
        source = Path(extraction.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import tkinter", source)
        self.assertNotIn("import Arayüz", source)
        self.assertNotIn("_ui import", source)


class FlowNameBoundaryTests(unittest.TestCase):
    """Özel ad içindeki akış sözcüğü taşınan kaynak sayılmamalıdır."""

    def test_flow_word_inside_a_system_name_is_not_a_flow(self):
        names = extraction._flow_names(
            "Veri Tabanı Yönetim Sistemi, kayıtları saklamalıdır"
        )
        # Sistem adının içindeki "Veri" taşınan kaynak değildir; cümledeki
        # gerçek kaynak adı ("kayıtları") ayrıca yakalanabilir.
        self.assertTrue(
            all("Tabanı" not in name for name in names),
            f"Sistem adı akış olarak yakalandı: {names}",
        )
        self.assertNotIn("Veri", names)

    def test_real_flow_next_to_a_system_name_is_still_detected(self):
        self.assertEqual(
            extraction._flow_names(
                "Laboratuvar Veri Toplama Birimi, tahlil verisini "
                "Ana Kontrol Sistemi'ne iletmelidir"
            ),
            ("tahlil verisini",),
        )

    def test_system_named_flow_word_does_not_produce_a_dangling_flow_element(self):
        flat = {
            "STT-001": {
                "type": "STT", "ID": "STT-001", "bound_to": "Yok",
                "content": (
                    "Veri Tabanı Yönetim Sistemi, hasta kayıtlarını en az "
                    "5 yıl süreyle saklamalıdır"
                ),
            },
        }
        result = extraction.extract_architecture_candidates(flat, _report(flat))
        flows = [
            item for item in result.candidates
            if item.proposal_type == "element"
            and item.proposed_payload["element_type"]
            in {"ResourceFlow", "SystemResourceFlow"}
        ]
        self.assertEqual(flows, [])


class WidenedFlowVocabularyTests(unittest.TestCase):
    """Taşınan kaynak yalnız veri/mesaj olmak zorunda değildir."""

    CARRIERS = (
        "tahlil sonuçlarını", "reçete bilgisini", "konum sinyalini",
        "durdurma komutunu", "denetim raporunu", "basınç ölçümünü",
        "kamera görüntüsünü", "ayar parametresini",
    )

    def test_each_carrier_noun_yields_a_connected_flow(self):
        for carrier in self.CARRIERS:
            with self.subTest(carrier=carrier):
                content = (
                    f"Toplama Birimi, {carrier} Ana Kontrol Sistemi'ne "
                    "iletmelidir"
                )
                flat = {
                    "STT-001": {
                        "type": "STT", "ID": "STT-001",
                        "bound_to": "Yok", "content": content,
                    },
                }
                result = extraction.extract_architecture_candidates(flat, _report(flat))
                self.assertTrue(
                    _relationship_candidates(result, "flow_source"),
                    f"{carrier} için flow_source üretilmedi",
                )
                self.assertTrue(
                    _relationship_candidates(result, "flow_target"),
                    f"{carrier} için flow_target üretilmedi",
                )


class DanglingFlowSuppressionTests(unittest.TestCase):
    """Uçları çözümlenmeyen akış mimari öğe olarak üretilmemelidir."""

    @staticmethod
    def _extract(content):
        flat = {
            "STT-001": {
                "type": "STT", "ID": "STT-001",
                "bound_to": "Yok", "content": content,
            },
        }
        return extraction.extract_architecture_candidates(flat, _report(flat))

    def test_carrier_without_direction_verb_produces_no_flow_element(self):
        result = self._extract(
            "Kayıt Saklama Birimi, hasta kayıtlarını en az 5 yıl saklamalıdır"
        )
        self.assertEqual(_element_candidates(result, "SystemResourceFlow"), [])
        self.assertEqual(_element_candidates(result, "ResourceFlow"), [])
        self.assertIn(
            "flow_direction_missing",
            {gap.code for gap in result.information_gaps},
        )

    def test_direction_without_two_endpoints_produces_no_flow_element(self):
        result = self._extract(
            "Toplama Birimi, ölçüm verisini dış ortama iletmelidir"
        )
        self.assertEqual(_element_candidates(result, "SystemResourceFlow"), [])
        self.assertIn(
            "flow_endpoint_missing",
            {gap.code for gap in result.information_gaps},
        )

    def test_fully_resolved_flow_still_produces_element_and_both_ends(self):
        result = self._extract(
            "Sürtünme Sensörü Birimi, ölçüm verisini Ana Kontrol Sistemi'ne "
            "iletmelidir"
        )
        self.assertTrue(_element_candidates(result, "SystemResourceFlow"))
        self.assertTrue(_relationship_candidates(result, "flow_source"))
        self.assertTrue(_relationship_candidates(result, "flow_target"))

    def test_every_emitted_flow_element_has_both_endpoint_relationships(self):
        """Uçsuz akış öğesi kalmamalı; bu koşul görünüm üretimini korur."""

        result = self._extract(
            "Veri Tabanı Yönetim Sistemi hasta kayıtlarını saklamalı; "
            "Laboratuvar Toplama Birimi, tahlil sonuçlarını Ana Kontrol "
            "Sistemi'ne iletmelidir"
        )
        flows = {
            item.proposed_payload["name"]
            for item in _element_candidates(result, "SystemResourceFlow")
        }
        ends = {
            item.proposed_payload["name"].rsplit(" ", 1)[0]
            for item in (
                *_relationship_candidates(result, "flow_source"),
                *_relationship_candidates(result, "flow_target"),
            )
        }
        for flow in flows:
            self.assertTrue(
                any(flow in name for name in ends),
                f"Uçsuz akış öğesi üretildi: {flow}",
            )


class StrictModelCandidateGateTests(unittest.TestCase):
    def test_hallucinated_protocol_actor_and_approval_are_rejected(self):
        flat = {
            "SGD-002": {
                "type": "SGD",
                "ID": "SGD-002",
                "content": "Fren Sistemi komutu 20 ms içinde işlemelidir.",
                "bound_to": "TID-001",
            },
        }
        hallucinated = {
            "proposal_type": "element",
            "identity_key": "can-protokolu",
            "name": "CAN Protokolü",
            "element_type": "Protocol",
            "description": "CAN Protokolü kullanılmalıdır.",
            "source_requirement_ids": ["SGD-002"],
            "evidence_text": flat["SGD-002"]["content"],
        }

        with self.assertRaises(extraction.ArchitectureExtractionError):
            extraction.candidate_from_strict_json(hallucinated, flat)
        for forbidden_field in ("actor", "capability", "data_class", "state", "interface_name", "approved"):
            tampered = dict(hallucinated)
            tampered[forbidden_field] = True
            with self.assertRaises(extraction.ArchitectureExtractionError):
                extraction.candidate_from_strict_json(tampered, flat)

    def test_source_backed_strict_json_remains_pending_model_candidate(self):
        flat = {
            "SGD-010": {
                "type": "SGD",
                "ID": "SGD-010",
                "content": "CAN Protokolü kullanılmalıdır.",
                "bound_to": "TID-001",
            },
        }
        raw = {
            "proposal_type": "element",
            "identity_key": "can-protokolu",
            "name": "CAN Protokolü",
            "element_type": "Protocol",
            "description": flat["SGD-010"]["content"],
            "source_requirement_ids": ["SGD-010"],
            "evidence_text": flat["SGD-010"]["content"],
        }

        candidate = extraction.candidate_from_strict_json(raw, flat)

        self.assertEqual(candidate.proposal_origin, DERIVATION_MODEL_SUGGESTION)
        self.assertEqual(candidate.review_status, REVIEW_PENDING)
        self.assertEqual(candidate.initial_decision, DECISION_DEFER)
        self.assertEqual(candidate.evidence_text, flat["SGD-010"]["content"])

    def test_strict_json_rejects_names_recombined_from_unrelated_source_words(self):
        flat = {
            "SGD-011": {
                "type": "SGD",
                "ID": "SGD-011",
                "content": "Alfa Sistemi Beta verisini UDP protokolü ile iletir.",
                "bound_to": "TID-001",
            },
        }
        common = {
            "proposal_type": "element",
            "description": flat["SGD-011"]["content"],
            "source_requirement_ids": ["SGD-011"],
            "evidence_text": flat["SGD-011"]["content"],
        }
        hallucinated_system = {
            **common,
            "identity_key": "beta-sistemi",
            "name": "Beta Sistemi",
            "element_type": "System",
        }
        hallucinated_protocol = {
            **common,
            "identity_key": "beta",
            "name": "Beta",
            "element_type": "Protocol",
        }

        for raw in (hallucinated_system, hallucinated_protocol):
            with self.subTest(name=raw["name"]):
                with self.assertRaises(extraction.ArchitectureExtractionError):
                    extraction.candidate_from_strict_json(raw, flat)

        valid_protocol = {
            **common,
            "identity_key": "udp",
            "name": "UDP",
            "element_type": "Protocol",
        }
        candidate = extraction.candidate_from_strict_json(valid_protocol, flat)
        self.assertEqual(candidate.proposed_payload["name"], "UDP")

    def test_model_relationship_cannot_invent_actor_endpoints(self):
        flat = {
            "SGD-020": {
                "type": "SGD",
                "ID": "SGD-020",
                "content": (
                    "Fren Kontrol Sistemi durum mesajını Güç Yönetim Sistemi'ne gönderir."
                ),
                "bound_to": "TID-001",
            },
        }
        raw = {
            "proposal_type": "relationship",
            "identity_key": "sgd-020-durum-mesajini-fren-kontrol-sistemi",
            "name": "durum mesajını Fren Kontrol Sistemi",
            "relationship_type": "flow_source",
            "description": flat["SGD-020"]["content"],
            "source_requirement_ids": ["SGD-020"],
            "evidence_text": flat["SGD-020"]["content"],
            "source_element_id": "ARCH-ELEMENT-UYDURMA-AKTOR",
            "target_element_id": "ARCH-ELEMENT-UYDURMA-HEDEF",
        }

        with self.assertRaises(extraction.ArchitectureExtractionError):
            extraction.candidate_from_strict_json(raw, flat)


if __name__ == "__main__":
    unittest.main()
