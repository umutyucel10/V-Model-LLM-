# -*- coding: utf-8 -*-

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import etki_analizi_entegrasyon as integration
import etki_analizi_simulasyon as simulation
import etki_analizi_simulasyon_ui as simulation_ui
from tests.test_etki_analizi_simulasyon import _traceability_graph


def _simulation_result(report):
    return simulation.simulate_change(
        report,
        simulation.ChangeRequest(
            requirement_id="SYS-REQ-001",
            current_value="10 kg",
            proposed_value="8 kg",
            reason="Kütle hedefini iyileştirme",
            requested_by="Sistem Mühendisliği",
            change_type=simulation.CHANGE_NUMERIC_LIMIT,
            assumptions=("Tartım yöntemi değişmeyecek.",),
        ),
        use_lm_studio=False,
        use_existing_rag=False,
    )


class StructuredRagIntegrationTests(unittest.TestCase):
    def test_same_document_version_is_not_reindexed(self):
        report = _traceability_graph()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            first = integration.update_structured_rag_index(
                report,
                data_path=directory,
                rag_builder=lambda force: calls.append(force) or True,
            )
            second = integration.update_structured_rag_index(
                report,
                data_path=directory,
                rag_builder=lambda force: calls.append(force) or True,
            )

            self.assertEqual(first["status"], "updated")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(calls, [True])
            content = Path(first["path"]).read_text(encoding="utf-8")
            self.assertIn("SYS-REQ-001", content)
            self.assertIn("maksimum ağırlığı", content)

    def test_changed_document_version_rebuilds_index(self):
        report = _traceability_graph()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            integration.update_structured_rag_index(
                report, data_path=directory,
                rag_builder=lambda force: calls.append(force) or True,
            )
            report["nodes"][1]["description"] = "Maksimum ağırlık 8 kg olmalıdır."
            result = integration.update_structured_rag_index(
                report, data_path=directory,
                rag_builder=lambda force: calls.append(force) or True,
            )

            self.assertEqual(result["status"], "updated")
            self.assertEqual(calls, [True, True])

    def test_cancelled_indexing_does_not_call_rag_builder(self):
        event = threading.Event()
        event.set()
        builder = MagicMock(return_value=True)
        with tempfile.TemporaryDirectory() as directory:
            result = integration.update_structured_rag_index(
                _traceability_graph(), data_path=directory,
                rag_builder=builder, cancel_event=event,
            )

        self.assertEqual(result["status"], "cancelled")
        builder.assert_not_called()


class ManualTraceabilityCorrectionTests(unittest.TestCase):
    def _report(self, directory):
        report = _traceability_graph()
        project_dir = Path(directory) / report["project_id"]
        project_dir.mkdir(parents=True)
        report["storage_path"] = str(project_dir / "traceability.json")
        return report

    def test_manual_edge_can_be_added_persisted_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(directory)
            updated, edge = integration.add_manual_edge(
                report, "SYS-REQ-099", "TEST-031", "verified_by"
            )
            self.assertIn(edge["id"], {item["id"] for item in updated["edges"]})
            self.assertEqual(edge["confidence_level"], "Kullanıcı onaylı")
            self.assertTrue(integration.overrides_path(report).is_file())

            reloaded = integration.apply_overrides(report)
            self.assertIn(edge["id"], {item["id"] for item in reloaded["edges"]})
            removed = integration.reject_edge(reloaded, edge["id"])
            self.assertNotIn(edge["id"], {item["id"] for item in removed["edges"]})

    def test_rejected_automatic_edge_is_excluded_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(directory)
            updated = integration.reject_edge(report, "E-006")

            self.assertNotIn("E-006", {item["id"] for item in updated["edges"]})
            self.assertIn("E-006", {item["id"] for item in report["edges"]})
            self.assertEqual(updated["user_overrides"]["rejected_edge_count"], 1)

    def test_suggestion_decision_is_persisted_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self._report(directory)
            overrides = integration.set_suggestion_decision(
                report, "SUG-001", "Kabul edildi"
            )

            self.assertEqual(
                overrides["suggestion_decisions"]["SUG-001"], "Kabul edildi"
            )
            self.assertEqual(
                integration.load_overrides(report)["suggestion_decisions"]["SUG-001"],
                "Kabul edildi",
            )


class SimulationPresentationTests(unittest.TestCase):
    def test_nine_result_views_contain_both_v_model_legs_and_sources(self):
        report = _traceability_graph()
        result = _simulation_result(report)
        views = simulation_ui.build_result_views(result, report)

        self.assertEqual(len(simulation_ui.RESULT_TAB_TITLES), 9)
        self.assertEqual(views["target"]["id"], "SYS-REQ-001")
        self.assertTrue(any(
            item["id"] == "SYS-REQ-001" and item["proposed"] == "8 kg"
            for item in views["requirements"]
        ))
        self.assertTrue(any(item["id"] == "SUB-008" for item in views["left"]))
        self.assertTrue(any(item["id"] == "TEST-031" for item in views["right"]))
        self.assertTrue(any(
            "SYS-REQ-001" in item["path"] and "TEST-031" in item["path"]
            for item in views["sources"]
        ))
        self.assertEqual(views["summary"]["impact_count"], len(result.impacts))
        self.assertIn("decision", views["summary"])

    def test_impact_color_uses_gray_for_low_confidence(self):
        self.assertEqual(simulation_ui.impact_color("Kritik", 0.2), "#7A7F87")
        self.assertEqual(simulation_ui.impact_color("Kritik", 0.9), "#C62828")


class PostGenerationPipelineTests(unittest.TestCase):
    def test_traceability_worker_completes_rag_health_pipeline(self):
        import Arayüz

        app = object.__new__(Arayüz.TIDGeneratorApp)
        app._traceability_generation_token = 7
        app.last_traceability_report = None
        app.last_traceability_health = None
        app.impact_analysis_workspace = None
        app.update_status_text = MagicMock()
        app.master = MagicMock()
        app.master.after.side_effect = lambda _delay, callback: callback()
        report = _traceability_graph()
        report["capabilities"] = {"lm_studio": {"available": False, "message": "LM kapalı"}}
        report["summary"] = {
            "node_count": len(report["nodes"]), "edge_count": len(report["edges"])
        }
        rag_status = {"status": "updated", "updated": True, "message": "RAG hazır"}

        with patch.object(
            Arayüz.etki_analizi_izlenebilirlik, "build_traceability_map",
            return_value=report,
        ), patch.object(
            Arayüz.etki_analizi_entegrasyon, "apply_overrides",
            side_effect=lambda value: value,
        ), patch.object(
            Arayüz.etki_analizi_entegrasyon, "update_structured_rag_index",
            return_value=rag_status,
        ) as rag_update, patch.object(
            Arayüz.messagebox, "showinfo"
        ):
            app._traceability_worker(
                7, "Uçtan Uca Proje", {}, {}, [], (), False, threading.Event()
            )

        rag_update.assert_called_once()
        self.assertIs(app.last_traceability_report, report)
        self.assertTrue(app.last_traceability_health["ready"])
        self.assertEqual(app.last_traceability_health["rag_status"], "updated")


if __name__ == "__main__":
    unittest.main()
