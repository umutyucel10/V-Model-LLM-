# -*- coding: utf-8 -*-

import json
import unittest

import hardware_generator_logic as generator


class SequenceModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.responses.pop(0) if self.responses else None


class HardwareGeneratorLogicTests(unittest.TestCase):
    def setUp(self):
        self.flat_data = {
            "SGD-001": {
                "ID": "SGD-001",
                "type": "SGD",
                "content": "Sistem 28 VDC ana besleme hattından çalışmalıdır.",
            },
            "STT-001": {
                "ID": "STT-001",
                "type": "STT",
                "content": "Alt sistem -40°C ile +70°C arasında çalışmalıdır.",
            },
            "AST-001": {
                "ID": "AST-001",
                "type": "AST",
                "content": "Bu kayıt donanım analizine girmemelidir.",
            },
        }

    def test_parser_accepts_fenced_json(self):
        response = """Açıklama
```json
{"hardware_items": [{"category": "Güç Birimi", "description": "Güç modülü"}]}
```"""

        parsed = generator.parse_hardware_response(response)

        self.assertEqual(parsed[0]["category"], "Güç Birimi")

    def test_generation_filters_unknown_links_and_forces_catalog_fields_to_dsb(self):
        payload = {
            "hardware_items": [
                {
                    "category": "Güç Birimi",
                    "description": "28 VDC güç dönüştürme birimi",
                    "quantity": 1,
                    "specifications": {"Giriş Gerilimi": "28 VDC"},
                    "linked_requirements": ["SGD-001", "STT-404"],
                    "manufacturer": "Uydurma Marka",
                    "part_number": "FAKE-1",
                    "risk": "Düşük",
                    "rationale": "SGD-001 güç donanımı gerektiriyor.",
                    "confidence": 0.88,
                },
                {
                    "category": "Diğer",
                    "description": "Bağlantısız kayıt",
                    "linked_requirements": ["STT-404"],
                },
            ]
        }
        model = SequenceModel([json.dumps(payload, ensure_ascii=False)])

        result = generator.run_generation_from_requirements(
            self.flat_data, llm_call=model
        )

        self.assertTrue(result["result"])
        self.assertEqual(result["suggestion_count"], 1)
        item = result["hardware_data"]["HW-001"]
        self.assertEqual(item["linked_requirements"], ["SGD-001"])
        self.assertEqual(item["manufacturer"], "DSB")
        self.assertEqual(item["part_number"], "DSB")
        self.assertEqual(item["risk"], "Belirsiz")
        self.assertIn("28 VDC", item["source_excerpt"])

    def test_invalid_json_is_retried_once(self):
        valid = json.dumps({
            "hardware_items": [{
                "category": "Güç Birimi",
                "description": "Güç birimi",
                "linked_requirements": ["SGD-001"],
            }]
        })
        model = SequenceModel(["geçersiz yanıt", valid])

        result = generator.run_generation_from_requirements(
            self.flat_data, llm_call=model
        )

        self.assertTrue(result["result"])
        self.assertEqual(len(model.calls), 2)
        self.assertIn("Önceki yanıt geçersizdi", model.calls[1][0])

    def test_duplicate_items_merge_requirement_links(self):
        model = SequenceModel([
            json.dumps({
                "hardware_items": [
                    {
                        "category": "Güç Birimi",
                        "description": "Ortak güç birimi",
                        "linked_requirements": ["SGD-001"],
                    },
                    {
                        "category": "Güç Birimi",
                        "description": "Ortak güç birimi",
                        "linked_requirements": ["STT-001"],
                    },
                ]
            })
        ])

        result = generator.run_generation_from_requirements(
            self.flat_data, llm_call=model
        )

        self.assertEqual(result["suggestion_count"], 1)
        self.assertEqual(
            result["hardware_data"]["HW-001"]["linked_requirements"],
            ["SGD-001", "STT-001"],
        )

    def test_reviewed_existing_item_is_preserved(self):
        model = SequenceModel([
            json.dumps({
                "hardware_items": [{
                    "category": "Güç Birimi",
                    "description": "Yeni güç birimi",
                    "linked_requirements": ["SGD-001"],
                }]
            })
        ])
        existing = {
            "HW-005": {
                "ID": "HW-005",
                "category": "İşlem Birimi",
                "description": "Mühendis tarafından incelenen kart",
                "linked_requirements": ["STT-001"],
                "status": "Onaylandı",
            },
            "HW-006": {
                "ID": "HW-006",
                "description": "Eski yapay zekâ önerisi",
                "linked_requirements": ["STT-001"],
                "status": "Önerilen",
            },
        }

        result = generator.run_generation_from_requirements(
            self.flat_data, existing_hardware=existing, llm_call=model
        )

        self.assertIn("HW-005", result["hardware_data"])
        self.assertIn("HW-006", result["hardware_data"].keys())
        self.assertEqual(
            result["hardware_data"]["HW-006"]["description"], "Yeni güç birimi"
        )
        self.assertEqual(
            result["hardware_data"]["HW-005"]["status"], "Onaylandı"
        )

    def test_no_eligible_requirements_returns_error_without_calling_model(self):
        model = SequenceModel([])

        result = generator.run_generation_from_requirements(
            {"UR-001": {"type": "TID", "content": "Kullanıcı isteği"}},
            llm_call=model,
        )

        self.assertFalse(result["result"])
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()
