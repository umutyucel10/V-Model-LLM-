# -*- coding: utf-8 -*-

import unittest

import hardware_list_logic as hardware


class HardwareListLogicTests(unittest.TestCase):
    def test_normalization_preserves_traceability_and_marks_unknown_values(self):
        item = hardware.normalize_hardware_item({
            "category": "  Güç   Birimi ",
            "description": "  28 VDC güç modülü ",
            "quantity": "2",
            "specifications": {"Giriş": "28 VDC", "Güç": ""},
            "linked_requirements": "sgd-008; STT-014; sgd-008",
            "status": "draft",
            "risk": "medium",
            "confidence": "84%",
            "part_number": "PSU-28",
        }, "hw-001")

        self.assertEqual(item.item_id, "HW-001")
        self.assertEqual(item.category, "Güç Birimi")
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.specifications["Güç"], hardware.DSB)
        self.assertEqual(item.linked_requirements, ["SGD-008", "STT-014"])
        self.assertEqual(item.status, "Önerilen")
        self.assertEqual(item.risk, "Orta")
        self.assertEqual(item.confidence, 0.84)
        self.assertEqual(item.manufacturer, hardware.DSB)

    def test_registry_assigns_stable_ids_without_overwriting_existing_items(self):
        registry = hardware.build_hardware_registry(
            [
                {"description": "İşlemci kartı", "linked_requirements": ["STT-001"]},
                {"ID": "HW-001", "description": "RF kartı"},
                {"ID": "HW-010", "description": "Güç kartı"},
            ],
            existing={
                "HW-001": {
                    "description": "Mevcut kart",
                    "linked_requirements": ["SGD-001"],
                }
            },
        )

        self.assertEqual(list(registry), ["HW-001", "HW-002", "HW-003", "HW-010"])
        self.assertEqual(registry["HW-001"]["description"], "Mevcut kart")
        self.assertEqual(registry["HW-002"]["description"], "İşlemci kartı")

    def test_only_sgd_and_stt_records_are_eligible(self):
        records = hardware.eligible_requirement_records({
            "UR-001": {"type": "TID", "content": "Kullanıcı gereksinimi"},
            "SGD-001": {"type": "SGD", "content": "Sistem gereksinimi"},
            "STT-001": {"type": "STT", "content": "Alt sistem gereksinimi"},
            "AST-001": {"type": "AST", "content": "Test"},
            "STT-EMPTY": {"type": "STT", "content": "  "},
        })

        self.assertEqual(
            [record["requirement_id"] for record in records],
            ["SGD-001", "STT-001"],
        )

    def test_many_to_many_trace_links_are_created(self):
        registry = hardware.build_hardware_registry([
            {
                "description": "Ortak güç birimi",
                "linked_requirements": ["SGD-001", "STT-003"],
            }
        ])

        self.assertEqual(hardware.build_hardware_trace_links(registry), [
            {"source_id": "SGD-001", "target_id": "HW-001", "link_type": "allocated_to"},
            {"source_id": "STT-003", "target_id": "HW-001", "link_type": "allocated_to"},
        ])

    def test_validation_reports_dsb_and_unknown_requirement(self):
        item = hardware.normalize_hardware_item({
            "description": "",
            "specifications": {"Güç": ""},
            "linked_requirements": ["STT-404"],
            "part_number": "ABC-123",
        }, "HW-001")

        warnings = hardware.validate_hardware_item(item, known_requirement_ids={"STT-001"})

        self.assertIn("Donanım açıklaması DSB.", warnings)
        self.assertIn("Bazı teknik özellikler DSB.", warnings)
        self.assertIn("Parça numarası var ancak üretici DSB.", warnings)
        self.assertIn("Bilinmeyen gereksinim bağlantısı: STT-404", warnings)

    def test_summary_counts_review_states_and_dsb(self):
        registry = hardware.build_hardware_registry([
            {
                "description": "Onaylı işlemci",
                "status": "approved",
                "risk": "low",
                "manufacturer": "Üretici",
                "part_number": "CPU-1",
                "rationale": "STT-001 için",
                "specifications": {"Sıcaklık": "-40 / +70"},
            },
            {
                "description": "RF birimi",
                "status": "review",
                "risk": "high",
            },
        ])

        self.assertEqual(hardware.hardware_registry_summary(registry), {
            "total": 2,
            "suggested": 0,
            "in_review": 1,
            "approved": 1,
            "rejected": 0,
            "high_risk": 1,
            "with_dsb": 1,
        })


if __name__ == "__main__":
    unittest.main()
