# -*- coding: utf-8 -*-
"""rag_handler.py icin karakterizasyon testleri: embedding baslatma,
veritabani yukleme ve tekillik (singleton) garantisinin durumu.

Gercek LM Studio/ag cagrisi ve gercek Chroma diskyazimlari yapilmiyor;
_initialize_embeddings ve Chroma sinifi mock'lanarak sadece rag_handler'in
kendi orkestrasyon mantigi test ediliyor.
"""

import unittest
from unittest.mock import Mock, patch

import rag_handler as rag_module


class ModuleLevelSingletonTests(unittest.TestCase):
    """llm_handler.py ve digerleri rag_handler modulundeki tekil
    `rag_handler` nesnesini paylasarak kullanir; bu nesnenin gercekten
    tek oldugunu ve embedding'i tembel (lazy) baslattigini dogrula."""

    def test_module_level_rag_handler_is_a_single_shared_instance(self):
        self.assertIsInstance(rag_module.rag_handler, rag_module.RAGHandler)

    def test_module_level_instance_does_not_eagerly_initialize_embeddings(self):
        # RAGHandler(initialize_embeddings=False) ile olusturuldugu icin
        # import sirasinda LM Studio'ya ag cagrisi yapilmamis olmali.
        self.assertFalse(rag_module.rag_handler._embeddings_initialization_attempted)

    def test_wrapper_functions_operate_on_the_shared_singleton(self):
        stub = Mock()
        stub.get_enhanced_context.return_value = "baglam metni"
        stub.get_database_info.return_value = {"total_chunks": 3}
        with patch.object(rag_module, "rag_handler", stub):
            self.assertEqual(
                rag_module.get_rag_enhanced_context("aciklama", "SGD"),
                "baglam metni",
            )
            self.assertEqual(rag_module.get_rag_info(), {"total_chunks": 3})
        stub.get_enhanced_context.assert_called_once_with("aciklama", "SGD")
        stub.get_database_info.assert_called_once()


class SingletonGuaranteeCharacterizationTests(unittest.TestCase):
    """DIKKAT: Bu testler mevcut (istenmeyen) davranisi belgeliyor, ideali
    degil. Faz 2 performans raporunda tespit edildi: RAGHandler() dogrudan
    cagrildiginda (ornegin main.py'de) modul-seviyesi singleton'i bypass
    edip yeniden ~2 saniyelik bir LM Studio baglanti testi + yeni bir
    embeddings/db nesnesi yaratiyor. Faz 9 gercek bir singleton/cache
    ekledikten sonra bu testler guncellenmeli (artik ayni nesneyi
    dondurmesi beklenecek)."""

    def test_two_separate_instantiations_create_distinct_embeddings_objects(self):
        calls = []

        def _set_fake_embeddings(self):
            calls.append(self)
            self.embeddings = Mock(name="fake-embeddings")

        # `new=` (bir MagicMock degil, duz fonksiyon) kullaniyoruz ki
        # tanimlayici (descriptor) protokolu calissin ve `self` dogru
        # baglansin - MagicMock burada bound-method gibi davranmaz.
        with patch.object(rag_module.RAGHandler, "_initialize_embeddings", new=_set_fake_embeddings):
            first = rag_module.RAGHandler()
            second = rag_module.RAGHandler()

        self.assertIsNot(first.embeddings, second.embeddings)
        self.assertEqual(len(calls), 2)

    def test_load_existing_database_creates_a_new_chroma_instance_every_call(self):
        handler = rag_module.RAGHandler.__new__(rag_module.RAGHandler)
        handler.chroma_path = "rag_chroma_lms"
        handler.embeddings = Mock(name="fake-embeddings")
        handler.db = None

        with patch.object(rag_module, "Chroma") as chroma_cls:
            chroma_cls.side_effect = [Mock(name="db-1"), Mock(name="db-2")]
            handler._load_existing_database()
            first_db = handler.db
            handler._load_existing_database()
            second_db = handler.db

        self.assertEqual(chroma_cls.call_count, 2)
        self.assertIsNot(first_db, second_db)


class LoadExistingDatabaseErrorHandlingTests(unittest.TestCase):
    def test_chroma_init_failure_leaves_db_as_none_instead_of_raising(self):
        handler = rag_module.RAGHandler.__new__(rag_module.RAGHandler)
        handler.chroma_path = "rag_chroma_lms"
        handler.embeddings = Mock(name="fake-embeddings")
        handler.db = None

        with patch.object(rag_module, "Chroma", side_effect=RuntimeError("disk hatasi")):
            handler._load_existing_database()

        self.assertIsNone(handler.db)

    def test_no_embeddings_means_database_is_never_loaded(self):
        handler = rag_module.RAGHandler.__new__(rag_module.RAGHandler)
        handler.chroma_path = "rag_chroma_lms"
        handler.embeddings = None
        handler.db = None

        with patch.object(rag_module, "Chroma") as chroma_cls:
            handler._load_existing_database()

        chroma_cls.assert_not_called()
        self.assertIsNone(handler.db)


if __name__ == "__main__":
    unittest.main()
