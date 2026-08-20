# -*- coding: utf-8 -*-
import json
import unittest

from hardware_image_prompt import (
    PromptPreparationError, build_verified_hardware_context,
    deterministic_prompt_plan, prepare_prompt_with_gemma,
)


def sample_item():
    return {
        "hardware_id": "HW-BRAKE-1",
        "part_name": "Kompozit Fren Balatası",
        "part_number": "SECRET-PN-77",
        "manufacturer": "SecretBrand",
        "hardware_type": "Parça/bileşen",
        "system_role": "Fren diskinde sürtünme üretir",
        "description": "Disk fren tertibatında kullanılır",
        "technical_data": {
            "length": "120", "width": "55", "height": "14", "dimension_unit": "mm",
            "electrical_interfaces": ["Uydurma Port"],
            "custom_parameters": {"Malzeme": "Kompozit", "Renk": "Siyah"},
        },
        "source_evidence": [
            {"field_name": "part_name", "certainty": "Kesin bilgi", "source_document": "fren.pdf"},
            {"field_name": "hardware_type", "certainty": "Kesin bilgi", "source_document": "fren.pdf"},
            {"field_name": "system_role", "certainty": "Kesin bilgi", "source_document": "fren.pdf"},
            {"field_name": "description", "certainty": "Çıkarım", "source_document": "fren.pdf"},
            {"field_name": "length", "certainty": "Kesin bilgi", "source_document": "datasheet.pdf"},
            {"field_name": "width", "certainty": "Kesin bilgi", "source_document": "datasheet.pdf"},
            {"field_name": "height", "certainty": "Çıkarım", "source_document": "datasheet.pdf"},
            {"field_name": "dimension_unit", "certainty": "Kesin bilgi", "source_document": "datasheet.pdf"},
            {"field_name": "technical_data.custom_parameters.Malzeme", "certainty": "Kesin bilgi", "source_document": "datasheet.pdf"},
        ],
    }


class HardwareImagePromptTests(unittest.TestCase):
    def test_only_verified_fields_enter_context(self):
        context = build_verified_hardware_context(sample_item())
        self.assertEqual(context.fields["part_name"], "Kompozit Fren Balatası")
        self.assertEqual(context.fields["technical_data.length"], "120")
        self.assertNotIn("description", context.fields)
        self.assertNotIn("technical_data.height", context.fields)
        self.assertNotIn("technical_data.electrical_interfaces", context.fields)
        self.assertNotIn("manufacturer", context.fields)
        self.assertIn("Marka veya logo", context.omitted_fields)

    def test_deterministic_plan_omits_unknown_values(self):
        plan = deterministic_prompt_plan(sample_item(), {"visual_type": "Nötr katalog görseli"})
        self.assertIn("Kompozit Fren Balatası", plan.prompt)
        self.assertNotIn("SecretBrand", plan.prompt)
        self.assertNotIn("SECRET-PN-77", plan.prompt)
        self.assertNotIn("Uydurma Port", plan.prompt)
        self.assertIn("teknik doğrulama", plan.prompt.casefold())

    def test_gemma_json_is_validated_and_unknown_known_feature_is_rejected(self):
        captured = {}
        def fake_llm(prompt, **kwargs):
            captured["prompt"] = prompt
            return json.dumps({
                "prompt": "Kompozit fren balatası, nötr katalog görünümü, logo yok",
                "negative_prompt": "logo",
                "caption": "Fren balatası kavramsal görünümü",
                "known_features_used": ["Parça adı", "Uydurma konektör"],
                "unknown_features_omitted": ["Konektör"],
                "assumptions": [],
                "recommended_view": "Ön 3/4 görünüm",
            }, ensure_ascii=False)
        plan = prepare_prompt_with_gemma(sample_item(), llm_callable=fake_llm, allow_fallback=False)
        self.assertEqual(plan.preparation_method, "Gemma")
        self.assertEqual(plan.known_features_used, ["Parça adı"])
        self.assertNotIn("SecretBrand", captured["prompt"])
        self.assertNotIn("SECRET-PN-77", captured["prompt"])
        self.assertIn("uydurma konektör", plan.negative_prompt)

    def test_invalid_json_uses_single_safe_fallback(self):
        plan = prepare_prompt_with_gemma(sample_item(), llm_callable=lambda *_a, **_k: "bozuk-json")
        self.assertEqual(plan.preparation_method, "Deterministik güvenli yedek")
        with self.assertRaises(PromptPreparationError):
            prepare_prompt_with_gemma(
                sample_item(), llm_callable=lambda *_a, **_k: "bozuk-json", allow_fallback=False,
            )

    def test_hallucinated_connector_is_rejected(self):
        payload = {
            "prompt": "Fren balatası üzerinde iki adet connector port",
            "negative_prompt": "logo",
            "caption": "Kavramsal",
            "known_features_used": ["Parça adı"],
            "unknown_features_omitted": [], "assumptions": [],
            "recommended_view": "İzometrik",
        }
        with self.assertRaises(PromptPreparationError):
            prepare_prompt_with_gemma(
                sample_item(), llm_callable=lambda *_a, **_k: json.dumps(payload),
                allow_fallback=False,
            )


if __name__ == "__main__":
    unittest.main()
