# -*- coding: utf-8 -*-

from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest

import donanim_kartlari_yonetim as management
from donanim_kartlari_model import MISSING_VALUE


class HardwareCatalogImprovementTests(unittest.TestCase):
    def setUp(self):
        self.catalog = management.sample_catalog()

    def test_quality_summary_is_actionable_and_deterministic(self):
        summary = management.catalog_quality_summary(self.catalog)
        self.assertEqual(summary["total"], len(self.catalog["hardware_items"]))
        self.assertGreater(summary["missing_datasheet"], 0)
        self.assertGreater(summary["missing_requirements"], 0)
        self.assertIn("critical_without_alternative", summary)

    def test_advanced_filters_cover_no_alternative_and_no_datasheet(self):
        no_alt = management.filter_cards(self.catalog, no_alternative_only=True)
        self.assertTrue(no_alt)
        self.assertTrue(all(not item.get("alternative_ids") for item in no_alt))
        no_sheet = management.filter_cards(self.catalog, no_datasheet_only=True)
        self.assertEqual(len(no_sheet), len(self.catalog["hardware_items"]))
        impacted = management.filter_cards(
            self.catalog, impacted_only=True, impacted_ids={"SAMPLE-DCDC"},
        )
        self.assertEqual([item["hardware_id"] for item in impacted], ["SAMPLE-DCDC"])

    def test_project_preferences_round_trip_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            overrides = management.empty_overrides("Tercih Projesi", self.catalog)
            management.update_ui_preferences(
                overrides, view_mode="Kompakt Liste",
                manufacturer_filter="Örnek Üretici", no_datasheet_only=True,
            )
            management.save_overrides(
                "Tercih Projesi", overrides, self.catalog, output_root=directory,
            )
            loaded = management.load_overrides(
                "Tercih Projesi", self.catalog, output_root=directory,
            )
            self.assertEqual(loaded["ui_preferences"]["view_mode"], "Kompakt Liste")
            self.assertTrue(loaded["ui_preferences"]["no_datasheet_only"])

    def test_multi_comparison_normalizes_units_and_keeps_missing_neutral(self):
        catalog = deepcopy(self.catalog)
        by_id = {item["hardware_id"]: item for item in catalog["hardware_items"]}
        by_id["SAMPLE-DCDC-B"]["technical_data"]["weight"] = 0.02
        by_id["SAMPLE-DCDC-B"]["technical_data"]["weight_unit"] = "kg"
        by_id["SAMPLE-DCDC-C"]["technical_data"]["weight"] = MISSING_VALUE
        comparison = management.build_multi_comparison(
            catalog, ["SAMPLE-DCDC", "SAMPLE-DCDC-B", "SAMPLE-DCDC-C"],
        )
        weight = next(row for row in comparison["parameter_rows"] if row["key"] == "weight")
        self.assertEqual(weight["normalized_values"]["SAMPLE-DCDC"], 18.0)
        self.assertEqual(weight["normalized_values"]["SAMPLE-DCDC-B"], 20.0)
        self.assertIsNone(weight["normalized_values"]["SAMPLE-DCDC-C"])
        self.assertEqual(weight["assessments"]["SAMPLE-DCDC-C"], "Veri eksik — puanlanmadı")

    def test_mandatory_requirement_violations_are_listed_first(self):
        traceability = {"nodes": [{
            "id": "DEMO-REQ-PWR-001", "title": "Zorunlu güç gereksinimi",
            "mandatory": True, "source_document": "Sistem Gereksinimleri",
        }]}
        result = management.build_multi_comparison(
            self.catalog, ["SAMPLE-DCDC", "SAMPLE-DCDC-B"], traceability,
        )
        self.assertTrue(result["requirement_rows"][0]["mandatory"])
        self.assertEqual(result["mandatory_violations"][0]["hardware_id"], "SAMPLE-DCDC-B")

    def test_multi_impact_payload_preserves_evidence_context(self):
        payload = management.build_multi_impact_payload(
            self.catalog, ["SAMPLE-DCDC", "SAMPLE-DCDC-B", "SAMPLE-DCDC-C"],
        )
        self.assertEqual(len(payload["alternatives"]), 2)
        self.assertEqual(payload["hardware_context"]["parent_id"], "SAMPLE-PDB")
        self.assertAlmostEqual(
            sum(float(row["weight"]) for row in payload["parameters"]), 100.0,
            places=3,
        )

    def test_comparison_rejects_less_than_two_or_more_than_four(self):
        with self.assertRaisesRegex(ValueError, "2 ile 4"):
            management.build_multi_comparison(self.catalog, ["SAMPLE-DCDC"])
        ids = [item["hardware_id"] for item in self.catalog["hardware_items"][:5]]
        with self.assertRaisesRegex(ValueError, "2 ile 4"):
            management.build_multi_comparison(self.catalog, ids)

    def test_archive_is_non_destructive_and_manual_change_can_be_undone(self):
        overrides = management.empty_overrides("Arşiv", self.catalog)
        management.archive_hardware_item(overrides, "SAMPLE-DCDC", self.catalog)
        archived, _ = management.apply_overrides(self.catalog, overrides)
        item = next(row for row in archived["hardware_items"] if row["hardware_id"] == "SAMPLE-DCDC")
        self.assertEqual(item["lifecycle_status"], "Kullanımdan kaldırıldı")
        self.assertEqual(len(archived["hardware_items"]), len(self.catalog["hardware_items"]))
        record = management.undo_last_manual_change(overrides, self.catalog)
        self.assertIsNotNone(record)
        restored, _ = management.apply_overrides(self.catalog, overrides)
        item = next(row for row in restored["hardware_items"] if row["hardware_id"] == "SAMPLE-DCDC")
        self.assertEqual(item["lifecycle_status"], "Önerilen")

    def test_filtering_500_items_is_fast_and_stable(self):
        template = deepcopy(self.catalog["hardware_items"][0])
        items = []
        for index in range(500):
            item = deepcopy(template)
            item["hardware_id"] = f"PERF-{index:04d}"
            item["part_name"] = f"Performans Kartı {index:04d}"
            item["part_number"] = f"PN-{index:04d}"
            item["manufacturer"] = "A Üretici" if index % 2 == 0 else "B Üretici"
            item["confidence_score"] = index % 101
            items.append(item)
        catalog = deepcopy(self.catalog); catalog["hardware_items"] = items
        started = time.perf_counter()
        result = management.filter_cards(
            catalog, search="Kartı 04", manufacturer="A Üretici",
            sort_by="Güven: yüksekten düşüğe",
        )
        elapsed = time.perf_counter() - started
        self.assertTrue(result)
        self.assertLess(elapsed, 0.25)


if __name__ == "__main__":
    unittest.main()
