# -*- coding: utf-8 -*-

import os
import unittest
from unittest.mock import Mock, patch

import gemma4_e4b_test
import lmstudio_model


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        lmstudio_model._CACHE.clear()

    def test_exact_model_id_is_preserved(self):
        model_id = "google/gemma-4-e4b"
        self.assertEqual(
            lmstudio_model.resolve_model_id(model_id, [model_id]),
            model_id,
        )

    def test_lm_studio_gguf_suffix_is_resolved(self):
        loaded = "lmstudio-community/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf"
        self.assertEqual(
            lmstudio_model.resolve_model_id("google/gemma-4-e4b", [loaded]),
            loaded,
        )

    def test_requested_e4b_never_falls_back_to_old_gemma_3_4b(self):
        with self.assertRaisesRegex(lmstudio_model.ModelSelectionError, "yüklü değil"):
            lmstudio_model.resolve_model_id(
                "google/gemma-4-e4b",
                ["google_gemma-3-4b-it"],
            )

    def test_normal_gemma_3_4b_alias_still_resolves(self):
        self.assertEqual(
            lmstudio_model.resolve_model_id(
                "google_gemma-3-4b-it", ["google/gemma-3-4b"]
            ),
            "google/gemma-3-4b",
        )

    def test_ambiguous_e4b_models_require_explicit_id(self):
        with self.assertRaisesRegex(lmstudio_model.ModelSelectionError, "birden fazla"):
            lmstudio_model.resolve_model_id(
                "google/gemma-4-e4b",
                ["gemma-4-e4b-it-q4", "gemma-4-e4b-it-q8"],
            )

    def test_probe_reports_resolved_loaded_model(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{"id": "gemma-4-e4b-it-q4_k_m"}]}
        getter = Mock(return_value=response)
        result = lmstudio_model.probe_model(
            "google/gemma-4-e4b", request_get=getter
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.resolved_model, "gemma-4-e4b-it-q4_k_m")

    def test_one_shot_launcher_sets_only_process_environment(self):
        with patch.dict(os.environ, {}, clear=False):
            previous = os.environ.pop("EHSIM_LM_MODEL", None)
            try:
                gemma4_e4b_test.configure_one_shot_model()
                self.assertEqual(
                    os.environ["EHSIM_LM_MODEL"],
                    "google/gemma-4-e4b",
                )
            finally:
                if previous is None:
                    os.environ.pop("EHSIM_LM_MODEL", None)
                else:
                    os.environ["EHSIM_LM_MODEL"] = previous


class LlmHandlerModelTests(unittest.TestCase):
    def test_gemma4_document_request_uses_native_api_without_reasoning(self):
        import llm_handler

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "output": [{"type": "message", "content": "tamam"}]
        }
        with patch.object(
            llm_handler, "get_active_model_name", return_value="gemma-4-e4b-it-q4"
        ), patch.object(llm_handler.requests, "post", return_value=response) as post:
            result = llm_handler.call_gemma3_api("test", max_tokens=8)

        self.assertEqual(result, "tamam")
        self.assertTrue(post.call_args.args[0].endswith("/api/v1/chat"))
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gemma-4-e4b-it-q4")
        self.assertEqual(post.call_args.kwargs["json"]["reasoning"], "off")
        self.assertEqual(post.call_args.kwargs["json"]["max_output_tokens"], 8)
        self.assertEqual(post.call_args.kwargs["timeout"], (3.05, 180))

    def test_gemma3_request_keeps_openai_compatible_endpoint(self):
        import llm_handler

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": "eski model tamam"}}]
        }
        with patch.object(
            llm_handler, "get_active_model_name", return_value="google/gemma-3-4b"
        ), patch.object(llm_handler.requests, "post", return_value=response) as post:
            result = llm_handler.call_gemma3_api("test", max_tokens=12)

        self.assertEqual(result, "eski model tamam")
        self.assertTrue(post.call_args.args[0].endswith("/v1/chat/completions"))
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 12)


if __name__ == "__main__":
    unittest.main()
