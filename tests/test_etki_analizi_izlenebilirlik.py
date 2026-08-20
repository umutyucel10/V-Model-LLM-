# -*- coding: utf-8 -*-

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import etki_analizi_izlenebilirlik as traceability


def _sample_flat_data():
    return {
        "UR-001": {
            "type": "TID",
            "ID": "UR-001",
            "content": "Sistem 28 V gerilim ile çalışmalıdır.",
            "bound_to": "Yok",
        },
        "SR-001": {
            "type": "SGD",
            "ID": "SR-001",
            "content": "Güç birimi 28 V giriş gerilimini kabul etmelidir.",
            "bound_to": "UR-001",
        },
        "SSR-001": {
            "type": "STT",
            "ID": "SSR-001",
            "content": "Alt sistem 28 VDC güç arayüzü sağlamalıdır.",
            "bound_to": "SR-001",
        },
        "AT-001": {
            "type": "KMTD",
            "ID": "AT-001",
            "content": "Müşteri kabulünde 28 V çalışma doğrulanmalıdır.",
            "bound_to": "UR-001",
        },
        "SITET-001": {
            "type": "SITET",
            "ID": "SITET-001",
            "content": "Sistem giriş gerilimi testi uygulanmalıdır.",
            "bound_to": "SR-001",
        },
        "SST-001": {
            "type": "AST",
            "ID": "SST-001",
            "content": "Alt sistem güç arayüzü entegrasyon testi uygulanmalıdır.",
            "bound_to": "SSR-001",
        },
        "UR-999": {
            "type": "TID",
            "ID": "UR-999",
            "content": "Bakım kılavuzu sağlanmalıdır.",
            "bound_to": "Yok",
        },
    }


def _build(**overrides):
    arguments = {
        "project_name": "İzlenebilirlik Test Projesi",
        "flat_data": _sample_flat_data(),
        "persist": False,
        "check_lm_studio": False,
    }
    arguments.update(overrides)
    return traceability.build_traceability_map(**arguments)


def _edge(report, relationship_type, source_id, target_id):
    return next(
        (
            item
            for item in report["edges"]
            if item["relationship_type"] == relationship_type
            and item["source_id"] == source_id
            and item["target_id"] == target_id
        ),
        None,
    )


class TraceabilityEngineTests(unittest.TestCase):
    def test_real_requirement_ids_are_preserved_and_parameters_are_evidence_based(self):
        report = _build()
        nodes = {node["id"]: node for node in report["nodes"]}

        for identifier in (
            "UR-001", "SR-001", "SSR-001", "AT-001",
            "SITET-001", "SST-001", "UR-999",
        ):
            self.assertIn(identifier, nodes)
        self.assertEqual(nodes["UR-001"]["canonical_id"], "UR-001")
        self.assertEqual(nodes["UR-001"]["technical_parameters"][0]["value"], 28.0)
        self.assertEqual(nodes["UR-001"]["technical_parameters"][0]["unit"].lower(), "v")

    def test_left_leg_derivation_relations_are_exact(self):
        report = _build()

        sr_edge = _edge(report, "derives_from", "SR-001", "UR-001")
        ssr_edge = _edge(report, "derives_from", "SSR-001", "SR-001")
        self.assertIsNotNone(sr_edge)
        self.assertIsNotNone(ssr_edge)
        self.assertEqual(sr_edge["confidence_level"], "Kesin")
        self.assertEqual(ssr_edge["confidence_level"], "Kesin")

    def test_right_leg_verification_and_validation_relations_are_exact(self):
        report = _build()

        acceptance = _edge(report, "validated_by", "UR-001", "AT-001")
        system_test = _edge(report, "verified_by", "SR-001", "SITET-001")
        subsystem_test = _edge(report, "verified_by", "SSR-001", "SST-001")
        self.assertIsNotNone(acceptance)
        self.assertIsNotNone(system_test)
        self.assertIsNotNone(subsystem_test)
        self.assertTrue(all(
            edge["confidence_level"] == "Kesin"
            for edge in (acceptance, system_test, subsystem_test)
        ))

    def test_unlinked_and_unverified_requirements_are_reported(self):
        report = _build()

        self.assertEqual(report["unlinked_requirements"], ["UR-999"])
        self.assertEqual(report["unverified_requirements"], ["UR-999"])

    def test_duplicate_spellings_merge_without_changing_real_id(self):
        data = _sample_flat_data()
        data["duplicate"] = {
            "type": "TID",
            "ID": "UR 001",
            "content": "Sistem farklı bir metinle 28 V gerilimde çalışmalıdır.",
            "bound_to": "Yok",
        }

        report = _build(flat_data=data)
        requirement_nodes = [
            node for node in report["nodes"]
            if node.get("canonical_id") == "UR-001"
        ]

        self.assertEqual(len(requirement_nodes), 1)
        self.assertEqual(requirement_nodes[0]["id"], "UR-001")
        self.assertIn("UR 001", requirement_nodes[0]["aliases"])
        self.assertTrue(any(
            conflict["type"] == "duplicate_identifier_conflict"
            for conflict in report["conflicts"]
        ))

    def test_same_project_is_atomically_versioned_on_rescan(self):
        with tempfile.TemporaryDirectory() as directory:
            first = _build(output_root=directory, persist=True)
            second = _build(output_root=directory, persist=True)
            latest = Path(second["storage_path"])

            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertTrue(latest.is_file())
            self.assertTrue(Path(first["version_path"]).is_file())
            self.assertTrue(Path(second["version_path"]).is_file())
            saved = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(saved["revision"], 2)
            self.assertEqual(saved["summary"]["node_count"], second["summary"]["node_count"])
            self.assertEqual(saved["summary"]["edge_count"], second["summary"]["edge_count"])

    def test_persisted_project_map_can_be_loaded_for_simulation(self):
        with tempfile.TemporaryDirectory() as directory:
            created = _build(output_root=directory, persist=True)

            loaded = traceability.load_project_traceability(
                "İzlenebilirlik Test Projesi", output_root=directory
            )

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["project_id"], created["project_id"])
            self.assertEqual(loaded["summary"], created["summary"])
            self.assertTrue(Path(loaded["storage_path"]).is_file())

    def test_invalid_document_does_not_crash_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "bozuk.pdf"
            broken.write_bytes(b"Bu bir PDF dosyasi degildir")

            report = _build(flat_data={}, source_paths=[broken])

            self.assertEqual(report["summary"]["node_count"], 0)
            self.assertEqual(len(report["source_documents"]), 1)
            self.assertEqual(report["source_documents"][0]["status"], "error")
            self.assertIn("PDF okunamadı", report["source_documents"][0]["error"])

    def test_lm_studio_offline_returns_clear_warning_and_keeps_exact_links(self):
        def unavailable(*_args, **_kwargs):
            raise ConnectionError("bağlantı reddedildi")

        report = _build(
            check_lm_studio=True,
            request_get=unavailable,
        )

        lm_status = report["capabilities"]["lm_studio"]
        self.assertFalse(lm_status["available"])
        self.assertIn("LM Studio kapalı veya erişilemiyor", lm_status["message"])
        self.assertIsNotNone(_edge(report, "derives_from", "SR-001", "UR-001"))

    def test_all_detected_document_types_get_technical_document_nodes(self):
        report = _build()
        document_nodes = {
            node["document_type"]
            for node in report["nodes"]
            if node["node_type"] == "Teknik belge"
        }

        self.assertEqual(document_nodes, {"TID", "SGD", "STT", "KMTD", "SITET", "AST"})

    def test_hardware_component_is_allocated_to_its_real_requirement(self):
        report = _build(hardware_data={
            "HW-001": {
                "ID": "HW-001",
                "name": "28 V güç modülü",
                "description": "28 V güç modülü",
                "linked_requirements": ["SR-001"],
                "specifications": {"Giriş Gerilimi": "28 V"},
                "status": "Onaylandı",
            }
        })
        component = next(
            node for node in report["nodes"] if node["id"] == "HW-001"
        )
        allocation = _edge(
            report, "allocated_to", "SR-001", "HW-001"
        )

        self.assertEqual(component["node_type"], "Parça/bileşen")
        self.assertEqual(component["technical_parameters"][0], {
            "name": "Giriş Gerilimi",
            "value": "28 V",
        })
        self.assertIsNotNone(allocation)
        self.assertEqual(allocation["confidence_level"], "Kesin")


class TraceabilityUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import Arayüz

        cls.ui = Arayüz

    def test_successful_document_generation_triggers_traceability(self):
        app = object.__new__(self.ui.TIDGeneratorApp)
        app.last_generated_output = ""
        app.raw_output_cache = ""
        app.flat_data = {}
        app.last_tid_list = []
        app.last_sgd_list = []
        app.last_stt_list = []
        app.last_sitet_list = []
        app.last_alt_sistem_test_list = []
        app.update_status_text = MagicMock()
        app._start_traceability_build = MagicMock()
        app._reset_buttons_state = MagicMock()
        app.master = MagicMock()
        app.master.after.side_effect = lambda _delay, callback: callback()

        generation_result = {
            "result": True,
            "tid_list": [{
                "TID_ID": "UR-001",
                "TID_Aciklama": "Sistem 28 V gerilim ile çalışmalıdır.",
            }],
        }
        with patch.object(
            self.ui, "pre_process_files", return_value=(["kaynak"], [0])
        ), patch.object(
            self.ui.tid_generator_logic,
            "run_generation_logic",
            return_value=generation_result,
        ), patch.object(
            self.ui.text_cleanup, "temizle", side_effect=lambda value, **_kwargs: value
        ):
            app.run_ai_process(
                ["kaynak.pdf"],
                {"max_tids": 1, "max_sgds": 0, "max_stts": 0},
                {
                    "generate_kmtd": False,
                    "generate_sitet": False,
                    "generate_alt_sistem_testi": False,
                },
                "pdf",
                "Otomatik Tetikleme Projesi",
            )

        app._start_traceability_build.assert_called_once_with(
            "Otomatik Tetikleme Projesi"
        )
        self.assertIn("UR-001", app.flat_data)

    def test_traceability_failure_does_not_raise_or_erase_document_result(self):
        app = object.__new__(self.ui.TIDGeneratorApp)
        app._traceability_generation_token = 4
        app.last_generated_output = "üretilmiş belge"
        app.last_traceability_report = None
        app.update_status_text = MagicMock()
        app.master = MagicMock()
        app.master.after.side_effect = lambda _delay, callback: callback()

        with patch.object(
            self.ui.etki_analizi_izlenebilirlik,
            "build_traceability_map",
            side_effect=RuntimeError("bozuk belge"),
        ), patch.object(self.ui.messagebox, "showwarning") as showwarning:
            app._traceability_worker(
                4,
                "Hata Projesi",
                {},
                {},
                ["bozuk.pdf"],
                tuple(self.ui.TIDGeneratorApp.VMODEL_SECTIONS),
            )

        self.assertEqual(app.last_generated_output, "üretilmiş belge")
        self.assertIsNone(app.last_traceability_report)
        showwarning.assert_called_once()
        self.assertTrue(any(
            call.kwargs.get("is_error") is True
            for call in app.update_status_text.call_args_list
        ))

    def test_impact_workspace_loader_uses_the_current_project_map(self):
        app = object.__new__(self.ui.TIDGeneratorApp)
        project_entry = MagicMock()
        project_entry.get.return_value = "Aktif Proje"
        app.entry_widgets = {"proje_ismi": project_entry}
        app.last_traceability_report = {"project_name": "Eski Proje"}
        app.update_status_text = MagicMock()
        expected = {
            "project_name": "Aktif Proje",
            "nodes": [],
            "edges": [],
        }

        with patch.object(
            self.ui.etki_analizi_izlenebilirlik,
            "load_project_traceability",
            return_value=expected,
        ) as loader:
            loaded = app._get_current_traceability_report()

        loader.assert_called_once_with("Aktif Proje")
        self.assertIs(loaded, expected)
        self.assertIs(app.last_traceability_report, expected)


if __name__ == "__main__":
    unittest.main()
