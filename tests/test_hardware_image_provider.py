# -*- coding: utf-8 -*-
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

from hardware_image_provider import (
    ComfyUIImageProvider, DisabledImageProvider, HttpImageGenerationProvider,
    ImageGenerationCancelled, ImageProviderError, MockImageProvider,
    create_image_provider, validate_image_bytes,
)


class HardwareImageProviderTests(unittest.TestCase):
    def test_mock_health_and_successful_generation(self):
        provider = MockImageProvider()
        self.assertTrue(provider.is_available())
        self.assertTrue(provider.health_check()["available"])
        result = provider.generate_image("safe prompt", "logo", {"seed": 17})
        media, size = validate_image_bytes(result.image_bytes)
        self.assertEqual(media, "image/png")
        self.assertEqual(result.seed, 17)
        self.assertGreaterEqual(size[0], 1)

    def test_mock_failure(self):
        with self.assertRaises(ImageProviderError):
            MockImageProvider(fail=True).generate_image("prompt")

    def test_cancel(self):
        provider = MockImageProvider(delay=.3); errors = []
        thread = threading.Thread(target=lambda: self._capture(provider, errors))
        thread.start(); time.sleep(.04); provider.cancel_generation(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any(isinstance(error, ImageGenerationCancelled) for error in errors))

    @staticmethod
    def _capture(provider, errors):
        try: provider.generate_image("prompt")
        except Exception as error: errors.append(error)

    def test_corrupt_and_oversized_image_rejected(self):
        with self.assertRaises(ImageProviderError):
            validate_image_bytes(b"not-an-image")
        valid = MockImageProvider().generate_image("prompt").image_bytes
        with self.assertRaises(ImageProviderError):
            validate_image_bytes(valid, max_file_size=3)

    def test_disabled_provider_message(self):
        provider = DisabledImageProvider()
        self.assertFalse(provider.is_available())
        with self.assertRaisesRegex(ImageProviderError, "ayrı bir görsel üretim modeli"):
            provider.generate_image("prompt")

    def test_provider_factory(self):
        self.assertIsInstance(create_image_provider({}), DisabledImageProvider)
        self.assertIsInstance(create_image_provider({"provider": "custom_api"}), HttpImageGenerationProvider)
        self.assertIsInstance(create_image_provider({"provider": "comfyui"}), ComfyUIImageProvider)
        self.assertIsInstance(create_image_provider({"provider": "mock"}), MockImageProvider)

    def test_secret_is_redacted_from_safe_error(self):
        provider = HttpImageGenerationProvider({"api_key": "TOP-SECRET"})
        error = provider._safe_error(RuntimeError("token TOP-SECRET invalid"), "Hata")
        self.assertNotIn("TOP-SECRET", str(error))
        self.assertIn("[GİZLİ]", str(error))

    def test_cross_origin_image_download_does_not_forward_api_key(self):
        provider = HttpImageGenerationProvider({
            "base_url": "http://127.0.0.1:9000", "api_key": "TOP-SECRET",
        })
        response = Mock(); response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"image_url": "https://images.example.test/result.png"}
        fetched = Mock(); fetched.headers = {"Content-Length": "4"}
        fetched.iter_content.return_value = [b"data"]
        provider._session.get = Mock(return_value=fetched)
        self.assertEqual(provider._response_bytes(response), b"data")
        headers = provider._session.get.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("TOP-SECRET", str(headers))


class ComfyUIProviderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.workflow_path = Path(self.folder.name) / "workflow-api.json"
        self.image_bytes = MockImageProvider().generate_image("fixture").image_bytes

    def tearDown(self):
        self.folder.cleanup()

    @staticmethod
    def _graph():
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 8, "denoise": 1, "latent_image": ["5", 0],
                    "model": ["4", 0], "negative": ["7", 0], "positive": ["6", 0],
                    "sampler_name": "euler", "scheduler": "normal",
                    "seed": "{{SEED}}", "steps": 20,
                },
            },
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{MODEL}}"}},
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}", "batch_size": 1},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": "EHSİM: {{PROMPT}}"},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": "{{NEGATIVE_PROMPT}}"},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "EHSIM", "images": ["8", 0]},
            },
        }

    def _write_workflow(self, *, wrapped=False, unquoted_width=False):
        payload = {"prompt": self._graph()} if wrapped else self._graph()
        text = json.dumps(payload, ensure_ascii=False)
        if unquoted_width:
            text = text.replace('"{{WIDTH}}"', "{{WIDTH}}")
        self.workflow_path.write_text(text, encoding="utf-8")

    def _provider(self, **values):
        config = {
            "base_url": "http://127.0.0.1:8188",
            "workflow_path": str(self.workflow_path),
            "model": "ehsim-model.safetensors",
            "api_key": "TOP-SECRET",
            "timeout": 3,
            "poll_interval": 0.05,
        }
        config.update(values)
        provider = ComfyUIImageProvider(config)
        provider._cancel_session.post = Mock(return_value=self._response({}, status=200))
        return provider

    @staticmethod
    def _response(payload=None, *, status=200, content=b"", headers=None, chunks=None):
        response = Mock()
        response.ok = 200 <= status < 400
        response.status_code = status
        response.headers = dict(headers or {})
        response.content = content
        response.json.return_value = payload
        response.iter_content.return_value = list(chunks if chunks is not None else [content])
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
        else:
            response.raise_for_status.return_value = None
        return response

    def test_typed_markers_and_wrapped_workflow_are_supported(self):
        self._write_workflow(wrapped=True, unquoted_width=True)
        provider = self._provider()
        workflow = provider._workflow(
            'kart "A"\nsatır {{MODEL}}', "logo, yazı",
            {"seed": 17, "width": 640, "height": 480},
        )
        self.assertEqual(workflow["3"]["inputs"]["seed"], 17)
        self.assertIsInstance(workflow["3"]["inputs"]["seed"], int)
        self.assertEqual(workflow["5"]["inputs"]["width"], 640)
        self.assertEqual(workflow["5"]["inputs"]["height"], 480)
        self.assertEqual(workflow["4"]["inputs"]["ckpt_name"], "ehsim-model.safetensors")
        self.assertEqual(
            workflow["6"]["inputs"]["text"],
            'EHSİM: kart "A"\nsatır {{MODEL}}',
        )
        self.assertEqual(workflow["7"]["inputs"]["text"], "logo, yazı")

    def test_health_rejects_missing_or_ui_format_workflow_without_network(self):
        provider = self._provider(workflow_path=str(self.workflow_path.with_name("missing.json")))
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("bulunamadı", health["message"])
        provider._session.get.assert_not_called()

        self.workflow_path.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
        provider = self._provider()
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("Export Workflow (API)", health["message"])
        provider._session.get.assert_not_called()

        graph = self._graph()
        graph["6"]["inputs"]["text"] = "sabit prompt"
        self.workflow_path.write_text(json.dumps(graph), encoding="utf-8")
        provider = self._provider()
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("{{PROMPT}}", health["message"])
        provider._session.get.assert_not_called()

        self._write_workflow()
        provider = self._provider(output_node_id="999")
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("'999'", health["message"])
        provider._session.get.assert_not_called()

    def test_health_rejects_misplaced_or_disconnected_markers_without_network(self):
        graph = self._graph()
        graph["5"]["inputs"]["width"] = 512
        graph["9"]["inputs"]["filename_prefix"] = "EHSIM-{{WIDTH}}"
        self.workflow_path.write_text(json.dumps(graph), encoding="utf-8")
        provider = self._provider()
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("{{WIDTH}}", health["message"])
        self.assertIn("yalnızca", health["message"])
        provider._session.get.assert_not_called()

        graph = self._graph()
        graph["6"]["inputs"]["text"] = "sabit prompt"
        graph["10"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": "{{PROMPT}}"},
        }
        self.workflow_path.write_text(json.dumps(graph), encoding="utf-8")
        provider = self._provider()
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("{{PROMPT}}", health["message"])
        self.assertIn("bağlı değil", health["message"])
        provider._session.get.assert_not_called()

        graph = self._graph()
        graph["5"]["inputs"]["width"] = "piksel-{{WIDTH}}"
        self.workflow_path.write_text(json.dumps(graph), encoding="utf-8")
        provider = self._provider()
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("{{WIDTH}}", health["message"])
        self.assertIn("tam girdi değeri", health["message"])
        provider._session.get.assert_not_called()

    def test_multiple_outputs_require_an_explicit_downloadable_output_node(self):
        graph = self._graph()
        graph["10"] = {
            "class_type": "PreviewImage", "inputs": {"images": ["8", 0]},
        }
        self.workflow_path.write_text(json.dumps(graph), encoding="utf-8")
        provider = self._provider()
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("birden çok", health["message"])
        provider._session.get.assert_not_called()

        provider = self._provider(output_node_id="8")
        provider._session.get = Mock()
        health = provider.health_check()
        self.assertFalse(health["available"])
        self.assertIn("SaveImage/PreviewImage", health["message"])
        provider._session.get.assert_not_called()

        provider = self._provider(output_node_id="9")
        provider._session.get = Mock(return_value=self._response({"system": {}, "devices": []}))
        self.assertTrue(provider.health_check()["available"])

    def test_health_and_model_discovery_use_auth_headers(self):
        self._write_workflow()
        provider = self._provider()
        provider._session.get = Mock(side_effect=[
            self._response({"system": {"comfyui_version": "test"}, "devices": []}),
            self._response(["other.safetensors", "ehsim-model.safetensors"]),
        ])
        self.assertTrue(provider.health_check()["available"])
        self.assertEqual(
            provider.list_models(),
            ["ehsim-model.safetensors", "other.safetensors"],
        )
        for call in provider._session.get.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer TOP-SECRET")

    def test_generation_queues_polls_streams_and_returns_final_output(self):
        self._write_workflow()
        provider = self._provider()
        provider._session.post = Mock(return_value=self._response({"prompt_id": "job-1"}))
        history = {
            "job-1": {
                "status": {"status_str": "success"},
                "outputs": {
                    "8": {"images": [{"filename": "preview.png", "type": "temp"}]},
                    "9": {"images": [{
                        "filename": "final.png", "subfolder": "ehsim", "type": "output",
                    }]},
                },
            }
        }
        image_response = self._response(
            content=self.image_bytes,
            headers={"Content-Length": str(len(self.image_bytes))},
            chunks=[self.image_bytes[:13], self.image_bytes[13:]],
        )
        provider._session.get = Mock(side_effect=[self._response(history), image_response])

        result = provider.generate_image(
            'güvenli "prompt"', "logo", {"seed": 23, "width": 640, "height": 480},
        )
        self.assertEqual(result.provider, "comfyui")
        self.assertEqual(result.model, "ehsim-model.safetensors")
        self.assertEqual(result.seed, 23)
        self.assertEqual(result.metadata["prompt_id"], "job-1")
        self.assertEqual(result.metadata["output_node_id"], "9")
        self.assertEqual(result.metadata["remote_filename"], "final.png")
        queue_call = provider._session.post.call_args
        self.assertEqual(queue_call.args[0], "http://127.0.0.1:8188/prompt")
        self.assertEqual(queue_call.kwargs["headers"]["Authorization"], "Bearer TOP-SECRET")
        self.assertEqual(queue_call.kwargs["json"]["prompt"]["3"]["inputs"]["seed"], 23)
        self.assertTrue(queue_call.kwargs["json"]["client_id"])
        view_call = provider._session.get.call_args_list[-1]
        self.assertTrue(view_call.kwargs["stream"])
        self.assertEqual(view_call.kwargs["params"]["filename"], "final.png")
        image_response.close.assert_called_once_with()

    def test_execution_error_is_safe_and_actionable(self):
        self._write_workflow()
        provider = self._provider()
        provider._session.post = Mock(return_value=self._response({"prompt_id": "job-error"}))
        provider._session.get = Mock(return_value=self._response({
            "job-error": {
                "status": {
                    "status_str": "error",
                    "messages": [["execution_error", {
                        "exception_message": "checkpoint TOP-SECRET yüklenemedi",
                    }]],
                },
                "outputs": {"9": {"images": [{
                    "filename": "partial.png", "type": "output",
                }]}},
            }
        }))
        with self.assertRaises(ImageProviderError) as raised:
            provider.generate_image("prompt", options={"seed": 1})
        self.assertIn("yürütme hatası", str(raised.exception))
        self.assertIn("[GİZLİ]", str(raised.exception))
        self.assertNotIn("TOP-SECRET", str(raised.exception))
        self.assertEqual(provider._session.get.call_count, 1)

    def test_prompt_validation_error_keeps_safe_comfy_details(self):
        self._write_workflow()
        provider = self._provider()
        provider._session.post = Mock(return_value=self._response({
            "error": {
                "message": "Prompt outputs failed validation",
                "details": "checkpoint TOP-SECRET bulunamadı",
            },
            "node_errors": {
                "9": {"errors": [{"message": "Required input is missing", "details": "images"}]},
            },
        }, status=400))
        provider._session.get = Mock()
        with self.assertRaises(ImageProviderError) as raised:
            provider.generate_image("prompt", options={"seed": 1})
        message = str(raised.exception)
        self.assertIn("iş akışını reddetti", message)
        self.assertIn("Prompt outputs failed validation", message)
        self.assertIn("[GİZLİ]", message)
        self.assertNotIn("TOP-SECRET", message)
        provider._session.get.assert_not_called()

    def test_timeout_and_oversized_download_are_bounded(self):
        self._write_workflow()
        provider = self._provider()
        provider.timeout = 0.06
        provider.poll_interval = 0.05
        provider._session.post = Mock(return_value=self._response({"prompt_id": "job-timeout"}))
        provider._session.get = Mock(return_value=self._response({}))
        with self.assertRaisesRegex(ImageProviderError, "zaman aşımına"):
            provider.generate_image("prompt", options={"seed": 2})
        self.assertEqual(provider._cancel_session.post.call_count, 1)
        self.assertTrue(
            provider._cancel_session.post.call_args.args[0].endswith(
                "/api/jobs/job-timeout/cancel"
            )
        )

        provider = self._provider(max_file_size=10)
        provider._session.post = Mock(return_value=self._response({"prompt_id": "job-large"}))
        oversized_response = self._response(
            content=b"not-read", headers={"Content-Length": "11"}, chunks=[b"not-read"],
        )
        provider._session.get = Mock(side_effect=[
            self._response({
                "job-large": {"outputs": {"9": {"images": [{
                    "filename": "large.png", "type": "output",
                }]}}}
            }),
            oversized_response,
        ])
        with self.assertRaisesRegex(ImageProviderError, "dosya boyutunu"):
            provider.generate_image("prompt", options={"seed": 3})
        oversized_response.iter_content.assert_not_called()
        oversized_response.close.assert_called_once_with()

    def test_streaming_download_obeys_the_absolute_generation_deadline(self):
        self._write_workflow()
        provider = self._provider()
        response = self._response(content=b"", chunks=[b"first", b"second"])
        provider._session.get = Mock(return_value=response)
        with patch(
            "hardware_image_provider.time.monotonic",
            side_effect=[0.0, 0.0, 0.5, 1.0],
        ):
            with self.assertRaisesRegex(ImageProviderError, "zaman aşımına"):
                provider._download_image(
                    {"filename": "slow.png", "type": "output"}, deadline=1.0,
                )
        response.close.assert_called_once_with()

    def test_cancel_stops_local_wait_and_attempts_pending_removal_only(self):
        self._write_workflow()
        provider = self._provider()
        provider.timeout = 1.0
        provider._session.post = Mock(return_value=self._response({"prompt_id": "job-cancel"}))
        history_started = threading.Event()

        def poll_history(*_args, **_kwargs):
            history_started.set()
            return self._response({})

        provider._session.get = Mock(side_effect=poll_history)
        provider._cancel_session.post = Mock(side_effect=[
            self._response({}, status=404), self._response({}, status=200),
        ])
        errors = []

        def generate():
            try:
                provider.generate_image("prompt", options={"seed": 9})
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=generate)
        worker.start()
        self.assertTrue(history_started.wait(1.0))
        provider.cancel_generation()
        worker.join(2.0)
        self.assertFalse(worker.is_alive())
        deadline = time.monotonic() + 1.0
        while provider._cancel_session.post.call_count < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(any(isinstance(error, ImageGenerationCancelled) for error in errors))
        self.assertEqual(provider._cancel_session.post.call_count, 2)
        first, second = provider._cancel_session.post.call_args_list
        self.assertTrue(first.args[0].endswith("/api/jobs/job-cancel/cancel"))
        self.assertTrue(second.args[0].endswith("/queue"))
        self.assertEqual(second.kwargs["json"], {"delete": ["job-cancel"]})
        self.assertNotIn("/interrupt", " ".join(
            call.args[0] for call in provider._cancel_session.post.call_args_list
        ))

    def test_stream_cancellation_closes_response_and_returns_no_image(self):
        self._write_workflow()
        provider = self._provider()
        response = self._response(content=self.image_bytes)

        def chunks():
            yield self.image_bytes[:10]
            provider._cancel.set()
            yield self.image_bytes[10:]

        response.iter_content.side_effect = lambda **_kwargs: chunks()
        provider._session.get = Mock(return_value=response)
        with self.assertRaises(ImageGenerationCancelled):
            provider._download_image({"filename": "cancel.png", "type": "output"})
        response.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
