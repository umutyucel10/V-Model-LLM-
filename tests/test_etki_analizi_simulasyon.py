# -*- coding: utf-8 -*-

import json
import time
import unittest

import etki_analizi_simulasyon as simulation


def _node(identifier, node_type, description, document="Sistem Mühendisliği Belgesi", **extra):
    value = {
        "id": identifier,
        "canonical_id": identifier,
        "aliases": [identifier],
        "node_type": node_type,
        "title": identifier,
        "description": description,
        "v_model_level": "Test seviyesi" if "test" in node_type.casefold() else "Tasarım seviyesi",
        "version": "1.0",
        "status": "Onaylandı",
        "source_document": document,
        "source_section": "3.2",
        "evidence_text": description,
        "confidence_level": "Kesin",
        "confidence": 1.0,
        "technical_parameters": [],
    }
    value.update(extra)
    return value


def _edge(identifier, source, target, relationship, evidence=None, confidence="Kesin", score=1.0):
    return {
        "id": identifier,
        "source_id": source,
        "target_id": target,
        "relationship_type": relationship,
        "confidence_level": confidence,
        "confidence": score,
        "evidence_text": evidence or f"{source} {relationship} {target}",
        "source_document": "İzlenebilirlik Matrisi",
        "derivation_method": "test_fixture",
    }


def _traceability_graph():
    nodes = [
        _node(
            "CR-001",
            "Müşteri/paydaş gereksinimi",
            "Platform toplam maksimum ağırlığı 10 kg değerini aşmamalıdır.",
            "Müşteri Gereksinimleri",
            technical_parameters=[{"raw": "10 kg", "value": 10.0, "unit": "kg"}],
        ),
        _node(
            "SYS-REQ-001",
            "Sistem gereksinimi",
            "Sistemin maksimum ağırlığı 10 kg değerini aşmamalıdır.",
            "Sistem Gereksinimleri",
            technical_parameters=[{"raw": "10 kg", "value": 10.0, "unit": "kg"}],
        ),
        _node(
            "SYS-REQ-002",
            "Sistem gereksinimi",
            "Sistemin izin verilen maksimum ağırlığı 12 kg olabilir.",
            "Sistem Gereksinimleri",
            technical_parameters=[{"raw": "12 kg", "value": 12.0, "unit": "kg"}],
        ),
        _node(
            "SYS-REQ-099",
            "Sistem gereksinimi",
            "Bakım kayıtları elektronik olarak saklanmalıdır.",
            "Sistem Gereksinimleri",
        ),
        _node(
            "SUB-008",
            "Alt sistem gereksinimi",
            "Motor alt sistemi ağırlık tahsisine uymalıdır.",
            "Alt Sistem Gereksinimleri",
        ),
        _node("MOTOR-02", "Parça/bileşen", "Ana tahrik motoru", "Akıllı Donanım Listesi"),
        _node("IF-MECH-01", "Mekanik arayüz", "Motor mekanik montaj arayüzü", "Arayüz Kontrol Belgesi"),
        _node("DES-01", "Tasarım kararı", "Hafif motor taşıyıcı tasarımı", "Tasarım Kararları"),
        _node("TEST-031", "Sistem doğrulama testi", "Sistem toplam ağırlık doğrulama testi", "Sistem Test Belgesi"),
        _node("ACCEPT-01", "Müşteri kabul/geçerleme testi", "Müşteri ağırlık kabul testi", "Kabul Test Belgesi"),
        _node("DOC-SGD", "Teknik belge", "Sistem Gereksinimleri Belgesi", "Sistem Gereksinimleri"),
        _node("DOC-STT", "Teknik belge", "Alt Sistem Gereksinimleri Belgesi", "Alt Sistem Gereksinimleri"),
        _node("DOC-TEST", "Teknik belge", "Sistem Test Belgesi", "Sistem Test Belgesi"),
    ]
    edges = [
        _edge("E-001", "SYS-REQ-001", "CR-001", "derives_from"),
        _edge("E-002", "SUB-008", "SYS-REQ-001", "derives_from"),
        _edge("E-003", "SUB-008", "MOTOR-02", "allocated_to"),
        _edge("E-004", "MOTOR-02", "IF-MECH-01", "interfaces_with"),
        _edge("E-005", "SUB-008", "DES-01", "implemented_by"),
        _edge("E-006", "SYS-REQ-001", "TEST-031", "verified_by"),
        _edge("E-007", "CR-001", "ACCEPT-01", "validated_by"),
        _edge("E-008", "SYS-REQ-001", "SYS-REQ-002", "conflicts_with"),
        _edge("E-009", "SYS-REQ-099", "CR-001", "derives_from"),
        _edge("E-010", "SYS-REQ-001", "DOC-SGD", "documented_in"),
        _edge("E-011", "SUB-008", "DOC-STT", "documented_in"),
        _edge("E-012", "TEST-031", "DOC-TEST", "documented_in"),
    ]
    return {
        "schema_version": "1.0",
        "project_id": "simulation-test-project",
        "project_name": "Simülasyon Test Projesi",
        "generated_at": "2026-07-31T12:00:00+03:00",
        "source_documents": [],
        "nodes": nodes,
        "edges": edges,
        "unlinked_requirements": ["SYS-REQ-099"],
        "unverified_requirements": ["SYS-REQ-099"],
        "conflicts": [],
        "missing_information": [],
    }


def _request(change_type, identifier, current, proposed, query=""):
    return simulation.ChangeRequest(
        requirement_id=identifier,
        current_value=current,
        proposed_value=proposed,
        reason="Mühendislik değişiklik talebi",
        requested_by="Sistem Mühendisliği",
        change_type=change_type,
        assumptions=("Mevcut izlenebilirlik haritası günceldir.",),
        query=query,
    )


def _simulate(request, **kwargs):
    arguments = {
        "use_existing_rag": False,
        "use_lm_studio": False,
    }
    arguments.update(kwargs)
    return simulation.simulate_change(_traceability_graph(), request, **arguments)


def _impact(result, identifier):
    return next((item for item in result.impacts if item.item_id == identifier), None)


class DeterministicImpactSimulationTests(unittest.TestCase):
    def test_lm_call_has_a_hard_total_deadline(self):
        started = time.monotonic()

        def slow_model(_prompt):
            time.sleep(0.2)
            return "{}"

        with self.assertRaisesRegex(TimeoutError, "yanıt vermedi"):
            simulation._call_with_deadline(slow_model, "test", timeout_seconds=0.02)

        self.assertLess(time.monotonic() - started, 0.15)

    def test_customer_requirement_change_propagates_to_left_and_right_legs(self):
        result = _simulate(_request(
            simulation.CHANGE_REQUIREMENT_TEXT,
            "CR-001",
            "Maksimum ağırlık 10 kg",
            "Maksimum ağırlık 8 kg",
        ))

        self.assertEqual(result.status, "completed")
        self.assertEqual(_impact(result, "SYS-REQ-001").traceability_path.display_path, "CR-001 → SYS-REQ-001")
        self.assertIsNotNone(_impact(result, "ACCEPT-01"))
        self.assertTrue(result.v_model_analysis["left_leg"]["customer_requirement_update"]["required"])
        self.assertTrue(result.v_model_analysis["left_leg"]["system_requirement_update"]["required"])
        self.assertTrue(result.v_model_analysis["right_leg"]["acceptance_validation_update"]["required"])

    def test_system_requirement_change_separates_upper_lower_test_and_conflict_impacts(self):
        result = _simulate(_request(
            simulation.CHANGE_REQUIREMENT_TEXT,
            "SYS-REQ-001",
            "Maksimum ağırlık 10 kg",
            "Maksimum ağırlık 9 kg",
        ))

        self.assertIsNotNone(_impact(result, "CR-001"))
        self.assertIsNotNone(_impact(result, "SUB-008"))
        self.assertIsNotNone(_impact(result, "TEST-031"))
        self.assertIsNotNone(_impact(result, "SYS-REQ-002"))
        self.assertTrue(any(item["item_id"] == "CR-001" for item in result.categorized_impacts["upper_requirement_impacts"]))
        self.assertTrue(any(item["item_id"] == "SUB-008" for item in result.categorized_impacts["lower_requirement_impacts"]))
        self.assertTrue(any(item["item_id"] == "SYS-REQ-002" for item in result.categorized_impacts["conflicting_requirements"]))

    def test_numeric_limit_question_calculates_delta_and_complete_paths(self):
        question = (
            "SYS-REQ-001 gereksinimindeki maksimum ağırlık 10 kg'dan "
            "8 kg'a düşürülürse ne olur?"
        )
        result = simulation.simulate_question(
            _traceability_graph(),
            question,
            use_existing_rag=False,
            use_lm_studio=False,
        )

        self.assertEqual(result.change_request.change_type, simulation.CHANGE_NUMERIC_LIMIT)
        self.assertEqual(result.numeric_change["current"], 10.0)
        self.assertEqual(result.numeric_change["proposed"], 8.0)
        self.assertEqual(result.numeric_change["percentage_change"], -20.0)
        motor = _impact(result, "MOTOR-02")
        self.assertEqual(motor.traceability_path.display_path, "SYS-REQ-001 → SUB-008 → MOTOR-02")
        self.assertIsInstance(motor.impact_score, int)
        self.assertEqual(result.scoring_method["calculated_by"], "Python — deterministik")

    def test_requirement_removal_marks_linked_tests_potentially_invalid(self):
        result = _simulate(_request(
            simulation.CHANGE_REQUIREMENT_REMOVE,
            "SYS-REQ-001",
            "Sistemin maksimum ağırlığı 10 kg değerini aşmamalıdır.",
            None,
        ))

        linked_test = next(
            item for item in result.categorized_impacts["potentially_invalid_tests"]
            if item["test_id"] == "TEST-031"
        )
        self.assertEqual(linked_test["status"], "Geçersiz kalabilir")
        self.assertIn("SYS-REQ-001 → TEST-031", linked_test["path"]["display_path"])

    def test_part_alternative_propagates_back_to_requirements_and_interfaces(self):
        result = _simulate(_request(
            simulation.CHANGE_PART_ALTERNATIVE,
            "MOTOR-02",
            "Mevcut motor",
            "Alternatif motor",
        ))

        self.assertEqual(result.selected_item["id"], "MOTOR-02")
        self.assertEqual(_impact(result, "SYS-REQ-001").traceability_path.display_path, "MOTOR-02 → SUB-008 → SYS-REQ-001")
        self.assertIsNotNone(_impact(result, "IF-MECH-01"))
        self.assertTrue(result.v_model_analysis["left_leg"]["architecture_design_part_interface_impact"]["affected"])

    def test_interface_change_reaches_component_design_and_requirements(self):
        result = _simulate(_request(
            simulation.CHANGE_INTERFACE,
            "IF-MECH-01",
            "Dört cıvatalı mekanik arayüz",
            "Altı cıvatalı mekanik arayüz",
        ))

        self.assertEqual(result.selected_item["id"], "IF-MECH-01")
        self.assertTrue(any(item["item_id"] == "MOTOR-02" for item in result.categorized_impacts["affected_parts"]))
        self.assertIsNotNone(_impact(result, "SUB-008"))
        self.assertIsNotNone(_impact(result, "SYS-REQ-001"))

    def test_requirement_without_direct_right_leg_test_requires_new_test(self):
        result = _simulate(_request(
            simulation.CHANGE_REQUIREMENT_TEXT,
            "SYS-REQ-099",
            "Bakım kayıtları elektronik saklanmalıdır.",
            "Bakım kayıtları şifreli elektronik saklanmalıdır.",
        ))

        new_test = next(
            item for item in result.categorized_impacts["new_or_updated_tests"]
            if item["test_id"] is None
        )
        self.assertEqual(new_test["status"], "Yeni test gerekli")
        self.assertIn("doğrudan bağlı", new_test["reason"])

    def test_free_text_with_multiple_matches_never_selects_randomly(self):
        request = _request(
            simulation.CHANGE_REQUIREMENT_TEXT,
            "",
            "ağırlık gereksinimi",
            "ağırlık sınırı güncellensin",
            query="sistem maksimum ağırlık gereksinimi",
        )
        result = _simulate(request)

        self.assertEqual(result.status, "selection_required")
        self.assertGreaterEqual(len(result.candidates), 2)
        self.assertLessEqual(len(result.candidates), 5)
        self.assertIsNone(result.selected_item)
        self.assertEqual(result.lm_status["status"], "not_called")

    def test_exact_id_match_is_resolved_before_rag(self):
        def rag_must_not_run(*_args, **_kwargs):
            raise AssertionError("Kesin kimlik eşleşmesinde RAG çağrılmamalı")

        result = simulation.simulate_change(
            _traceability_graph(),
            _request(
                simulation.CHANGE_REQUIREMENT_TEXT,
                "SYS-REQ-001",
                "10 kg",
                "9 kg",
            ),
            rag_search=rag_must_not_run,
            use_lm_studio=False,
        )

        self.assertEqual(result.selected_item["id"], "SYS-REQ-001")
        self.assertEqual(result.candidates[0]["match_source"], ["Kesin kimlik"])

    def test_rag_can_only_boost_ids_that_exist_in_traceability(self):
        def rag_search(_query, k=5):
            return [
                ({"page_content": "İlgili kayıt SYS-REQ-099 bakım kanıtıdır."}, 0.95),
                ({"page_content": "Bilinmeyen kayıt UNKNOWN-777"}, 1.0),
            ][:k]

        candidates = simulation.find_requirement_candidates(
            _traceability_graph(), "bakım kanıtı",
            rag_search=rag_search, use_existing_rag=False,
        )

        candidate_ids = [item["id"] for item in candidates]
        self.assertIn("SYS-REQ-099", candidate_ids)
        self.assertNotIn("UNKNOWN-777", candidate_ids)
        matched = next(item for item in candidates if item["id"] == "SYS-REQ-099")
        self.assertIn("RAG", matched["match_source"])

    def test_requirement_addition_has_no_fabricated_path_or_exact_score(self):
        result = _simulate(_request(
            simulation.CHANGE_REQUIREMENT_ADD,
            "SYS-NEW-001",
            None,
            "Sistem taşıma sırasında titreşim sınırını karşılamalıdır.",
            query="taşıma titreşim gereksinimi",
        ))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.impacts, [])
        self.assertEqual(result.summary["overall_impact_level"], "Belirlenemedi — tahsis bağlantısı yok")
        self.assertTrue(any("kesin etki yolu" in warning for warning in result.warnings))
        self.assertTrue(any(item["test_id"] is None for item in result.categorized_impacts["new_or_updated_tests"]))

    def test_remaining_supported_change_types_run_on_existing_graph(self):
        cases = (
            (simulation.CHANGE_PRIORITY, "Orta", "Kritik"),
            (simulation.CHANGE_VERIFICATION, "Analiz", "Test"),
            (simulation.CHANGE_SYSTEM_ALTERNATIVE, "Durum A", "Durum B"),
            (simulation.CHANGE_OPERATING_CONDITION, "20 °C", "40 °C"),
        )
        for change_type, current, proposed in cases:
            with self.subTest(change_type=change_type):
                result = _simulate(_request(change_type, "SYS-REQ-001", current, proposed))
                self.assertEqual(result.status, "completed")
                self.assertGreater(result.summary["impact_count"], 0)
                self.assertTrue(all(0 <= item.impact_score <= 100 for item in result.impacts))


class ModelValidationTests(unittest.TestCase):
    def test_lm_studio_offline_keeps_deterministic_graph_result(self):
        def offline(_prompt):
            raise ConnectionError("bağlantı reddedildi")

        result = simulation.simulate_change(
            _traceability_graph(),
            _request(
                simulation.CHANGE_REQUIREMENT_TEXT,
                "SYS-REQ-001",
                "10 kg",
                "9 kg",
            ),
            use_existing_rag=False,
            use_lm_studio=True,
            lm_call=offline,
        )

        self.assertEqual(result.status, "completed")
        self.assertGreater(len(result.impacts), 0)
        self.assertFalse(result.lm_status["available"])
        self.assertIn("temel grafik analizi", result.lm_status["message"])
        self.assertEqual(result.engineering_suggestions, [])

    def test_model_suggestion_with_unknown_id_is_rejected(self):
        model_payload = {
            "facts": [],
            "inferences": [],
            "suggestions": [{
                "category": "Yeni doğrulama testi",
                "suggestion": "Ağırlık kabul kriterini yeniden doğrula.",
                "rationale": "Sınır değişikliği test kapsamını etkiler.",
                "expected_benefit": "Değişiklik kanıtlanır.",
                "new_risk": "Ek test takvimi uzatabilir.",
                "affected_items": ["UNKNOWN-999"],
                "required_verification": "Test planı mühendis tarafından gözden geçirilmeli.",
                "source_or_assumption": "İzlenebilirlik yolu varsayımı.",
            }],
        }
        result = simulation.simulate_change(
            _traceability_graph(),
            _request(simulation.CHANGE_REQUIREMENT_TEXT, "SYS-REQ-001", "10 kg", "9 kg"),
            use_existing_rag=False,
            use_lm_studio=True,
            lm_call=lambda _prompt: json.dumps(model_payload, ensure_ascii=False),
        )

        self.assertEqual(result.engineering_suggestions, [])
        self.assertEqual(result.lm_status["status"], "validated_with_rejections")
        self.assertTrue(any("bilinmeyen kimlik" in warning for warning in result.warnings))

    def test_broken_json_gets_only_one_repair_attempt(self):
        valid_payload = {
            "facts": [{
                "item_id": "SYS-REQ-001",
                "statement": "Ağırlık sınırı değişmektedir.",
                "source_evidence": "SYS-REQ-001 gereksinim metni.",
            }],
            "inferences": [],
            "suggestions": [{
                "category": "Gereksinimi daha ölçülebilir hâle getirme",
                "suggestion": "Ağırlık ölçüm koşullarını açıkça tanımla.",
                "rationale": "Ölçüm tekrarlanabilirliğini artırır.",
                "expected_benefit": "Kabul kriteri daha açık olur.",
                "new_risk": "Belge incelemesi gerekebilir.",
                "affected_items": ["SYS-REQ-001"],
                "required_verification": "Gereksinim ve test planı birlikte incelenmeli.",
                "source_or_assumption": "Mevcut gereksinimde ölçüm koşulu açık değildir.",
            }],
        }
        responses = iter(["bu json değil", json.dumps(valid_payload, ensure_ascii=False)])
        call_count = {"value": 0}

        def model_call(_prompt):
            call_count["value"] += 1
            return next(responses)

        result = simulation.simulate_change(
            _traceability_graph(),
            _request(simulation.CHANGE_REQUIREMENT_TEXT, "SYS-REQ-001", "10 kg", "9 kg"),
            use_existing_rag=False,
            use_lm_studio=True,
            lm_call=model_call,
        )

        self.assertEqual(call_count["value"], 2)
        self.assertEqual(result.lm_status["status"], "repaired")
        self.assertEqual(len(result.engineering_suggestions), 1)
        suggestion = result.engineering_suggestions[0]
        self.assertEqual(suggestion.status, "Mühendislik önerisi — kullanıcı onayı gerekli")
        self.assertEqual(suggestion.affected_items, ("SYS-REQ-001",))

    def test_model_cannot_override_deterministic_scores(self):
        payload = {
            "facts": [],
            "inferences": [],
            "suggestions": [],
            "impact_score": 1,
        }
        result = simulation.simulate_change(
            _traceability_graph(),
            _request(simulation.CHANGE_REQUIREMENT_TEXT, "SYS-REQ-001", "10 kg", "9 kg"),
            use_existing_rag=False,
            use_lm_studio=True,
            lm_call=lambda _prompt: json.dumps(payload),
        )

        self.assertFalse(result.lm_status["available"])
        self.assertNotEqual(result.summary["overall_impact_score"], 1)
        self.assertTrue(all(item.impact_score >= 0 for item in result.impacts))


if __name__ == "__main__":
    unittest.main()
