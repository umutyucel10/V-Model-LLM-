# -*- coding: utf-8 -*-
from pathlib import Path
import tempfile
import threading
import unittest
from pypdf import PdfReader

import donanim_kartlari_yonetim as management
from donanim_detayli_inceleme_raporlama import export_hardware_pdf
from hardware_image_generation import (
    AI_CONCEPT_WARNING, discard_preview_file, generate_batch, has_real_image,
    store_generated_image, write_preview_file,
)
from hardware_image_provider import MockImageProvider


def item(hardware_id="HW-1", image_path="placeholder://donanim", generated=False):
    return {
        "hardware_id": hardware_id, "part_name": f"Parça {hardware_id}",
        "version": "v0004", "image_path": image_path,
        "image_is_generated": generated, "gallery_images": [],
    }


def plan(_item):
    return {
        "prompt": "Doğrulanmış parça için nötr katalog görseli",
        "negative_prompt": "logo, ölçü", "caption": "Kavramsal parça",
        "known_features_used": ["Parça adı"],
    }


class HardwareImageGenerationTests(unittest.TestCase):
    def test_store_has_ai_label_metadata_and_never_auto_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            generated = MockImageProvider().generate_image("prompt", options={"seed": 33})
            record = store_generated_image(
                generated, folder, "HW-1", prompt="prompt", negative_prompt="logo",
                caption="Kavramsal", card_version="v4", verified_fields=["Parça adı"],
            )
            self.assertTrue(Path(record["path"]).is_file())
            self.assertTrue(record["is_ai"])
            self.assertFalse(record["is_cover"])
            self.assertEqual(record["warning"], AI_CONCEPT_WARNING)
            self.assertEqual(record["provider"], "mock")
            self.assertEqual(record["seed"], 33)
            self.assertEqual(record["source_card_version"], "v4")

    def test_preview_rejection_cleans_only_safe_temp(self):
        result = MockImageProvider().generate_image("prompt")
        path = write_preview_file(result); parent = path.parent
        self.assertTrue(path.exists())
        discard_preview_file(path)
        self.assertFalse(path.exists()); self.assertFalse(parent.exists())

    def test_real_image_is_preserved_and_batch_skips_it(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder) / "real.png"
            real.write_bytes(MockImageProvider().generate_image("real").image_bytes)
            real_item = item("REAL", str(real), False)
            self.assertTrue(has_real_image(real_item))
            provider = MockImageProvider()
            result = generate_batch([real_item, item("MISSING")], provider, plan, folder)
            self.assertEqual(result.skipped_real_images, ["REAL"])
            self.assertIn("MISSING", result.generated)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(real_item["image_path"], str(real))

    def test_batch_continues_after_failed_card(self):
        class SelectiveProvider(MockImageProvider):
            def generate_image(self, prompt, negative_prompt="", options=None):
                if "FAIL" in prompt: raise RuntimeError("kart hatası")
                return super().generate_image(prompt, negative_prompt, options)
        def selective_plan(card):
            value = plan(card); value["prompt"] += " FAIL" if card["hardware_id"] == "BAD" else ""; return value
        with tempfile.TemporaryDirectory() as folder:
            result = generate_batch([item("BAD"), item("GOOD")], SelectiveProvider(), selective_plan, folder)
            self.assertIn("BAD", result.failed)
            self.assertIn("GOOD", result.generated)

    def test_batch_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            cancel = threading.Event(); cancel.set()
            result = generate_batch([item("ONE")], MockImageProvider(), plan, folder, cancel_event=cancel)
            self.assertTrue(result.cancelled); self.assertFalse(result.generated)

    def test_late_batch_cancellation_does_not_persist_returned_image(self):
        cancel = threading.Event()

        class LateCancelProvider(MockImageProvider):
            def generate_image(self, prompt, negative_prompt="", options=None):
                generated = super().generate_image(prompt, negative_prompt, options)
                cancel.set()
                return generated

        with tempfile.TemporaryDirectory() as folder:
            result = generate_batch(
                [item("LATE")], LateCancelProvider(), plan, folder,
                cancel_event=cancel,
            )
            self.assertTrue(result.cancelled)
            self.assertFalse(result.generated)
            self.assertFalse((Path(folder) / "ai_gorselleri").exists())

    def test_gallery_override_metadata_and_cover_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            generated = MockImageProvider().generate_image("prompt")
            record = store_generated_image(
                generated, folder, "HW-1", prompt="p", negative_prompt="n",
                caption="c", card_version="v1", verified_fields=["Parça adı"],
            )
            catalog = {"project_id": "p", "hardware_items": [item()]}
            overrides = management.empty_overrides("P", catalog)
            management.add_gallery_image(overrides, "HW-1", record)
            view, _ = management.apply_overrides(catalog, overrides)
            card = view["hardware_items"][0]
            self.assertEqual(card["image_path"], "placeholder://donanim")
            self.assertEqual(card["gallery_images"][0]["prompt"], "p")
            self.assertTrue(management.remove_gallery_image(overrides, "HW-1", record["path"]))

    def test_ai_cover_pdf_contains_concept_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            generated = MockImageProvider().generate_image("prompt")
            record = store_generated_image(
                generated, folder, "HW-1", prompt="p", negative_prompt="n",
                caption="c", card_version="v1", verified_fields=["Parça adı"],
            )
            card = item(); card.update({
                "image_path": record["path"], "image_is_generated": True,
                "image_metadata": record, "image_source": "AI kavramsal görsel",
                "technical_data": {}, "working_states": ["Normal"],
                "requirement_ids": [], "alternative_ids": [], "source_evidence": [],
            })
            target = Path(folder) / "ai-kart.pdf"
            export_hardware_pdf(target, {"hardware_items": [card]}, "HW-1")
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(target)).pages)
            self.assertIn("Yapay zekâ tarafından oluşturulmuş kavramsal görseldir", text)


if __name__ == "__main__":
    unittest.main()
