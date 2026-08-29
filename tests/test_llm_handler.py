# -*- coding: utf-8 -*-
"""llm_handler.py icin karakterizasyon testleri.

Gercek LM Studio/ag cagrisi yapilmiyor; requests.post ve yardimci
fonksiyonlar mock'lanarak (1) isteklerin nasil kuruldugu, (2) hata/timeout
durumunda ne dondugu, (3) generate_all_requirements_batch'e hazir bir
context_selection verildiginde bloklayan context-dosyasi dialogunun
(choose_context_option) atlandigi test ediliyor.
"""

import json
import unittest
from unittest.mock import Mock, patch

import requests

import llm_handler


class CallGemma3ApiErrorHandlingTests(unittest.TestCase):
    def test_connection_error_returns_none_without_raising(self):
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler.requests, "post", side_effect=requests.exceptions.ConnectionError("no route")):
            result = llm_handler.call_gemma3_api("test", max_tokens=8)
        self.assertIsNone(result)

    def test_timeout_is_a_request_exception_and_returns_none(self):
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler.requests, "post", side_effect=requests.exceptions.Timeout("180s asildi")):
            result = llm_handler.call_gemma3_api("test", max_tokens=8)
        self.assertIsNone(result)

    def test_http_error_status_with_response_body_returns_none(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        response.text = "internal error"
        response.response = response
        error = requests.exceptions.RequestException("500")
        error.response = response
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler.requests, "post", side_effect=error):
            result = llm_handler.call_gemma3_api("test", max_tokens=8)
        self.assertIsNone(result)

    def test_malformed_json_response_missing_choices_returns_none(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"unexpected": "shape"}
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler.requests, "post", return_value=response):
            result = llm_handler.call_gemma3_api("test", max_tokens=8)
        self.assertIsNone(result)

    def test_gemma4_empty_output_raises_internally_and_returns_none(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"output": []}
        with patch.object(llm_handler, "get_active_model_name", return_value="gemma-4-e4b-it"), \
             patch.object(llm_handler.requests, "post", return_value=response):
            result = llm_handler.call_gemma3_api("test", max_tokens=8)
        self.assertIsNone(result)


class CallGemma3ApiRequestConstructionTests(unittest.TestCase):
    def test_rag_chunks_are_truncated_to_max_total_length(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        long_chunks = ["a" * 5000, "b" * 5000, "c" * 5000]
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler.requests, "post", return_value=response) as post:
            llm_handler.call_gemma3_api("test", max_tokens=8, rag_chunks=long_chunks)

        system_content = post.call_args.kwargs["json"]["messages"][0]["content"]
        # 8000 karakter sinirini asan ucuncu parca dahil edilmemeli
        self.assertIn("a" * 5000, system_content)
        self.assertNotIn("c" * 5000, system_content)

    def test_prompt_longer_than_limit_is_truncated_before_sending(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler.requests, "post", return_value=response) as post:
            llm_handler.call_gemma3_api("x" * 9000, max_tokens=8)

        sent_prompt = post.call_args.kwargs["json"]["messages"][-1]["content"]
        self.assertEqual(len(sent_prompt), 8000)


class GenerateAllRequirementsBatchTests(unittest.TestCase):
    def test_explicit_context_selection_skips_blocking_dialog(self):
        """Faz 2 profilleme raporundaki bulgu: context_selection verilmezse
        choose_context_option() bloklayan bir tkinter dialogu aciyordu.
        Cagiran taraf context_selection={'option': 'none'} verdiginde bu
        dialogun hic tetiklenmedigini dogrular (regresyon koruyucusu)."""
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"TID1": {"tid_id": "TID-001"}}'}}]
        }
        with patch.object(llm_handler, "choose_context_option") as choose_dialog, \
             patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler, "get_rag_enhanced_context", return_value=""), \
             patch.object(llm_handler.requests, "post", return_value=response):
            batch_response, context_info = llm_handler.generate_all_requirements_batch(
                [("TID-001", "Sistem hedefi tespit etmeli")],
                context_selection={"option": "none", "file_path": None},
            )

        choose_dialog.assert_not_called()
        self.assertEqual(batch_response, {"TID1": {"tid_id": "TID-001"}})
        self.assertEqual(context_info["additional_context"], "")

    def test_invalid_json_response_is_skipped_not_raised(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "gecerli json degil"}}]}
        with patch.object(llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"), \
             patch.object(llm_handler, "get_rag_enhanced_context", return_value=""), \
             patch.object(llm_handler.requests, "post", return_value=response):
            batch_response, _ = llm_handler.generate_all_requirements_batch(
                [("TID-001", "aciklama")],
                context_selection={"option": "none", "file_path": None},
            )
        self.assertEqual(batch_response, {})


if __name__ == "__main__":
    unittest.main()
