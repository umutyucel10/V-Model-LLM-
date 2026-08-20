# -*- coding: utf-8 -*-

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import donanim_kartlari_yonetim as management
from donanim_kartlari_ui import catalog_filter_options, product_tree_instances
from donanim_kartlari_model import MISSING_VALUE, PLACEHOLDER_IMAGE


class HardwareCardsManagementTests(unittest.TestCase):
    def setUp(self):
        self.catalog = management.sample_catalog()

    def test_sample_tree_has_requested_hierarchy_and_two_dcdc_alternatives(self):
        by_id = {item["hardware_id"]: item for item in self.catalog["hardware_items"]}
        self.assertEqual(by_id["SAMPLE-DCDC"]["parent_id"], "SAMPLE-PDB")
        self.assertEqual(by_id["SAMPLE-MCB"]["parent_id"], "SAMPLE-CPU-SUB")
        self.assertEqual(
            by_id["SAMPLE-DCDC"]["alternative_ids"],
            ["SAMPLE-DCDC-B", "SAMPLE-DCDC-C"],
        )
        tree_hardware = {item["hardware_id"] for item in self.catalog["product_tree"]}
        self.assertNotIn("SAMPLE-DCDC-B", tree_hardware)
        self.assertTrue(self.catalog["is_sample"])
        self.assertIn("GERÇEK PROJE VERİSİ DEĞİLDİR", self.catalog["project_name"])

    def test_manual_override_survives_new_automatic_value_and_reports_conflict(self):
        overrides = management.empty_overrides("Örnek", self.catalog)
        management.set_field_override(
            overrides, "SAMPLE-DCDC", "manufacturer", "Kullanıcı Üreticisi", self.catalog
        )
        rescanned = deepcopy(self.catalog)
        card = next(item for item in rescanned["hardware_items"] if item["hardware_id"] == "SAMPLE-DCDC")
        card["manufacturer"] = "Yeni Otomatik Üretici"
        view, conflicts = management.apply_overrides(rescanned, overrides)
        rendered = next(item for item in view["hardware_items"] if item["hardware_id"] == "SAMPLE-DCDC")
        self.assertEqual(rendered["manufacturer"], "Kullanıcı Üreticisi")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["new_auto_value"], "Yeni Otomatik Üretici")

    def test_override_file_is_atomic_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            overrides = management.empty_overrides("Kart Projesi", self.catalog)
            management.attach_datasheets(overrides, "SAMPLE-DCDC", [Path(directory) / "ornek.pdf"])
            path = management.save_overrides(
                "Kart Projesi", overrides, self.catalog, output_root=directory
            )
            loaded = management.load_overrides(
                "Kart Projesi", self.catalog, output_root=directory
            )
            self.assertTrue(path.exists())
            self.assertEqual(len(loaded["attached_datasheets"]["SAMPLE-DCDC"]), 1)
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())

    def test_manual_item_and_rejected_field_are_visible_without_touching_base(self):
        base = deepcopy(self.catalog)
        overrides = management.empty_overrides("Örnek", base)
        manual_id = management.add_manual_item(overrides, {
            "part_name": "Manuel Sensör", "part_number": "USR-001",
            "manufacturer": "Kullanıcı", "hardware_type": "Parça/bileşen",
        })
        management.reject_automatic_field(overrides, "SAMPLE-DCDC", "manufacturer")
        view, _ = management.apply_overrides(base, overrides)
        by_id = {item["hardware_id"]: item for item in view["hardware_items"]}
        self.assertIn(manual_id, by_id)
        self.assertEqual(by_id["SAMPLE-DCDC"]["manufacturer"], MISSING_VALUE)
        original = next(item for item in base["hardware_items"] if item["hardware_id"] == "SAMPLE-DCDC")
        self.assertEqual(original["manufacturer"], "Örnek Üretici")

    def test_manual_item_is_materialized_in_existing_product_tree(self):
        overrides = management.empty_overrides("Örnek", self.catalog)
        manual_id = management.add_manual_item(overrides, {
            "part_name": "Manuel Sensör", "parent_id": "SAMPLE-MCB",
        })
        view, _ = management.apply_overrides(self.catalog, overrides)
        instances = product_tree_instances(view)
        manual = next(item for item in instances if item["hardware_id"] == manual_id)
        parent = next(item for item in instances if item["hardware_id"] == "SAMPLE-MCB")
        self.assertEqual(manual["parent_instance_id"], parent["instance_id"])

    def test_filter_search_manufacturer_lifecycle_and_confidence(self):
        cards = management.filter_cards(
            self.catalog, search="dönüştürücü", manufacturer="Örnek Üretici",
            lifecycle_status="Önerilen",
        )
        self.assertEqual([item["hardware_id"] for item in cards], ["SAMPLE-DCDC"])
        low = management.filter_cards(self.catalog, confidence="Düşük (0–59)")
        self.assertTrue(low)

    def test_system_filter_includes_all_descendants(self):
        cards = management.filter_cards(self.catalog, system_filter="Güç Alt Sistemi")
        ids = {item["hardware_id"] for item in cards}
        self.assertIn("SAMPLE-PDB", ids)
        self.assertIn("SAMPLE-DCDC", ids)
        self.assertIn("SAMPLE-CUR", ids)
        self.assertNotIn("SAMPLE-CPU", ids)

    def test_manual_technical_value_keeps_automatic_base_for_conflict_detection(self):
        overrides = management.empty_overrides("Örnek", self.catalog)
        management.set_field_override(
            overrides, "SAMPLE-DCDC", "technical_data.weight", 0.08, self.catalog
        )
        rescanned = deepcopy(self.catalog)
        card = next(item for item in rescanned["hardware_items"] if item["hardware_id"] == "SAMPLE-DCDC")
        card["technical_data"]["weight"] = 0.09
        view, conflicts = management.apply_overrides(rescanned, overrides)
        rendered = next(item for item in view["hardware_items"] if item["hardware_id"] == "SAMPLE-DCDC")
        self.assertEqual(rendered["technical_data"]["weight"], 0.08)
        self.assertEqual(conflicts[0]["field"], "technical_data.weight")

    def test_catalog_diff_keeps_missing_items_for_user_decision(self):
        current = deepcopy(self.catalog)
        current["hardware_items"] = [
            item for item in current["hardware_items"] if item["hardware_id"] != "SAMPLE-TEMP"
        ]
        current["hardware_items"][0]["system_role"] = "Değiştirildi"
        summary = management.compare_catalogs(self.catalog, current)
        self.assertIn("SAMPLE-TEMP", summary["missing_items"])
        self.assertEqual(summary["counts"]["missing"], 1)
        self.assertGreaterEqual(summary["counts"]["changed"], 1)

    def test_source_missing_decision_never_deletes_card(self):
        retained = deepcopy(self.catalog)
        card = next(item for item in retained["hardware_items"] if item["hardware_id"] == "SAMPLE-TEMP")
        card["source_presence_status"] = "Kaynaktan artık bulunamadı"
        overrides = management.empty_overrides("Örnek", retained)
        management.record_source_missing_decision(overrides, "SAMPLE-TEMP", "Kullanımdan kaldırıldı")
        view, _ = management.apply_overrides(retained, overrides)
        rendered = next(item for item in view["hardware_items"] if item["hardware_id"] == "SAMPLE-TEMP")
        self.assertEqual(rendered["lifecycle_status"], "Kullanımdan kaldırıldı")
        self.assertEqual(rendered["source_presence_status"], "Kaynaktan artık bulunamadı")

    def test_impact_payload_uses_shared_numeric_parameters_and_real_alternatives(self):
        payload = management.build_impact_payload(self.catalog, "SAMPLE-DCDC")
        self.assertEqual(payload["alternatives"], ["DC/DC Alternatif B", "DC/DC Alternatif C"])
        self.assertGreaterEqual(len(payload["parameters"]), 4)
        self.assertAlmostEqual(sum(float(item["weight"]) for item in payload["parameters"]), 100.0, places=2)
        self.assertEqual(payload["hardware_context"]["requirement_ids"], ["DEMO-REQ-PWR-001"])

    def test_simulation_result_creates_impact_and_missing_data_badges(self):
        result = {
            "impacts": [{
                "item_id": "DEMO-REQ-PWR-001", "impact_level": "Kritik",
                "traceability_path": {"node_ids": ["DEMO-REQ-PWR-001", "SAMPLE-DCDC"]},
            }],
            "engineering_suggestions": [{"affected_items": ["SAMPLE-DCDC"]}],
        }
        badges = management.build_impact_badges(self.catalog, result)
        self.assertIn("Kritik etki", badges["SAMPLE-DCDC"])
        self.assertIn("Alternatif önerildi", badges["SAMPLE-DCDC"])

    def test_filter_options_keep_missing_values_out(self):
        options = catalog_filter_options(self.catalog)
        self.assertEqual(options["manufacturers"][0], "Tümü")
        self.assertNotIn(MISSING_VALUE, options["manufacturers"])
        self.assertIn("Örnek Üretici", options["manufacturers"])

    def test_image_removal_override_only_changes_card_link(self):
        overrides = management.empty_overrides("Örnek", self.catalog)
        management.set_field_override(
            overrides, "SAMPLE-DCDC", "image_path", PLACEHOLDER_IMAGE, self.catalog
        )
        view, _ = management.apply_overrides(self.catalog, overrides)
        card = next(item for item in view["hardware_items"] if item["hardware_id"] == "SAMPLE-DCDC")
        self.assertEqual(card["image_path"], PLACEHOLDER_IMAGE)


if __name__ == "__main__":
    unittest.main()
