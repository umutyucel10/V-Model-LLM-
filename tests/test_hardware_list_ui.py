# -*- coding: utf-8 -*-

import unittest

from hardware_list_ui import build_hardware_table_rows


class HardwareListUiPresenterTests(unittest.TestCase):
    def setUp(self):
        self.hardware_data = {
            "HW-001": {
                "ID": "HW-001",
                "category": "Güç Birimi",
                "description": "28 VDC güç modülü",
                "quantity": 2,
                "linked_requirements": ["SGD-008", "STT-014"],
                "status": "Önerilen",
                "risk": "Orta",
                "manufacturer": "DSB",
                "part_number": "DSB",
                "rationale": "STT-014 için",
            },
            "HW-002": {
                "ID": "HW-002",
                "category": "İşlem Birimi",
                "description": "Endüstriyel işlemci kartı",
                "linked_requirements": ["STT-021"],
                "status": "Onaylandı",
                "risk": "Düşük",
                "manufacturer": "Üretici",
                "part_number": "CPU-1",
                "rationale": "STT-021 için",
            },
        }

    def test_rows_preserve_engineering_columns(self):
        rows = build_hardware_table_rows(self.hardware_data)

        self.assertEqual([row["ID"] for row in rows], ["HW-001", "HW-002"])
        self.assertEqual(rows[0]["requirements"], "SGD-008, STT-014")
        self.assertEqual(rows[0]["quantity"], 2)
        self.assertTrue(rows[0]["has_dsb"])
        self.assertFalse(rows[1]["has_dsb"])

    def test_search_matches_requirement_and_description(self):
        by_requirement = build_hardware_table_rows(
            self.hardware_data, search_text="stt-014"
        )
        by_description = build_hardware_table_rows(
            self.hardware_data, search_text="işlemci"
        )

        self.assertEqual([row["ID"] for row in by_requirement], ["HW-001"])
        self.assertEqual([row["ID"] for row in by_description], ["HW-002"])

    def test_status_filter_uses_internal_status(self):
        rows = build_hardware_table_rows(
            self.hardware_data, status_filter="Onaylandı"
        )

        self.assertEqual([row["ID"] for row in rows], ["HW-002"])


if __name__ == "__main__":
    unittest.main()
