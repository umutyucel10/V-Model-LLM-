# -*- coding: utf-8 -*-

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import rag_handler as rag_module
import etki_analizi_entegrasyon as integration


class RagFallbackIndexTests(unittest.TestCase):
    def _handler(self, data_path):
        handler = rag_module.RAGHandler.__new__(rag_module.RAGHandler)
        handler.data_path = str(data_path)
        handler.chroma_path = str(Path(data_path) / "chroma")
        handler.embeddings = None
        handler.db = None
        handler.last_build_error = ""
        return handler

    def test_global_style_lazy_handler_does_not_contact_lm_until_rag_is_used(self):
        with patch.object(rag_module.RAGHandler, "_initialize_embeddings") as initialize:
            handler = rag_module.RAGHandler(initialize_embeddings=False)
            initialize.assert_not_called()
            self.assertFalse(handler._embeddings_initialization_attempted)
            handler.ensure_embeddings_initialized()
            initialize.assert_called_once()
            self.assertTrue(handler._embeddings_initialization_attempted)

    def test_eager_handler_remains_backward_compatible(self):
        with patch.object(rag_module.RAGHandler, "_initialize_embeddings") as initialize:
            rag_module.RAGHandler()
            initialize.assert_called_once()

    def test_txt_document_builds_searchable_index_without_unstructured_or_lm_studio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents" / "existing_requirements"
            documents.mkdir(parents=True)
            (documents / "traceability.txt").write_text(
                "ID: SGD-001\n"
                "ACIKLAMA: Sistem maksimum ağırlığı 8 kg olmalıdır.\n"
                "KANIT: Müşteri taşıma sınırı.\n",
                encoding="utf-8",
            )
            simple_index = root / "rag_simple_db.txt"
            handler = self._handler(root / "documents")

            with patch.object(rag_module, "SIMPLE_DB_PATH", str(simple_index)):
                self.assertTrue(handler.build_knowledge_base(force_rebuild=True))
                results = handler._simple_text_search("müşteri taşıma", k=3)

            self.assertTrue(simple_index.is_file())
            self.assertGreater(len(results), 0)
            self.assertIn("Müşteri taşıma sınırı", results[0][0].page_content)
            self.assertTrue(
                results[0][0].metadata["id"].startswith("traceability.txt:chunk_")
            )
            self.assertEqual(handler.last_build_error, "")

    def test_empty_document_folder_returns_explanatory_error(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = self._handler(directory)
            with patch.object(
                rag_module, "SIMPLE_DB_PATH", str(Path(directory) / "simple.txt")
            ):
                self.assertFalse(handler.build_knowledge_base(force_rebuild=True))
            self.assertIn("okunabilir", handler.last_build_error)

    def test_traceability_document_completes_integration_index_without_embeddings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handler = self._handler(root / "documents")
            simple_index = root / "rag_simple_db.txt"
            report = {
                "project_id": "fallback-test",
                "project_name": "Fallback Test",
                "revision": 1,
                "nodes": [{
                    "id": "SGD-001",
                    "node_type": "Sistem gereksinimi",
                    "v_model_level": "Sistem gereksinimi",
                    "title": "Ağırlık sınırı",
                    "description": "Sistem ağırlığı 8 kg değerini aşmamalıdır.",
                    "source_document": "Sistem Gereksinimi",
                    "source_section": "3.1",
                    "evidence_text": "SGD-001 açık kaynak metni",
                }],
                "edges": [],
            }
            with patch.object(rag_module, "SIMPLE_DB_PATH", str(simple_index)), patch.object(
                rag_module, "rag_handler", handler
            ):
                result = integration.update_structured_rag_index(
                    report, data_path=handler.data_path, force=True
                )
                matches = handler._simple_text_search("SGD-001 ağırlık", k=3)

            self.assertEqual(result["status"], "updated")
            self.assertTrue(result["updated"])
            self.assertGreater(len(matches), 0)


if __name__ == "__main__":
    unittest.main()
