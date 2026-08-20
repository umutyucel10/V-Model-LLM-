# -*- coding: utf-8 -*-

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import donanim_kartlari_gorsel as visuals
import donanim_kartlari_yonetim as management
from donanim_kartlari_model import PLACEHOLDER_IMAGE
from donanim_kartlari_ui import HardwareCardsWorkspace


class HardwareVisualTests(unittest.TestCase):
    def test_brake_content_is_not_classified_as_electronic_chip(self):
        cases = (
            ({"part_name": "Kompozit Disk Fren Balatası", "system_role": "Fren diski üzerinde sürtünme üretir"}, "brake_pad"),
            ({"part_name": "K Tipi Kompozit Fren Pabucu"}, "brake_shoe"),
            ({"part_name": "ABS Kontrol Ünitesi", "system_role": "Fren kontrolü"}, "abs_unit"),
            ({"part_name": "Ölçüm Cihazı"}, "instrument"),
        )
        for item, expected in cases:
            with self.subTest(item=item["part_name"]):
                self.assertEqual(visuals.build_visual_brief(item).family, expected)

    @unittest.skipIf(visuals.Image is None, "Pillow kullanılamıyor")
    def test_generated_illustration_is_openable_and_labeled(self):
        catalog = {
            "hardware_items": [{
                "hardware_id": "HW-BRAKE-01",
                "part_name": "Fren Pabucu",
                "system_role": "Tekerlek frenlemesini sağlar",
                "image_path": PLACEHOLDER_IMAGE,
            }]
        }
        with tempfile.TemporaryDirectory() as directory:
            records = visuals.generate_catalog_illustrations(catalog, directory)
            record = records["HW-BRAKE-01"]
            path = Path(record["image_path"])
            self.assertTrue(path.is_file())
            with visuals.Image.open(path) as image:
                self.assertEqual(image.size, (720, 420))
                self.assertEqual(image.format, "PNG")
            self.assertTrue(record["image_is_generated"])
            self.assertIn("gerçek ürün fotoğrafı değildir", record["image_source"])

    @unittest.skipIf(visuals.Image is None, "Pillow kullanılamıyor")
    def test_real_image_and_manual_image_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            real_path = Path(directory) / "real.png"
            visuals.Image.new("RGB", (10, 10), "white").save(real_path)
            self.assertFalse(visuals.illustration_required({"image_path": str(real_path)}))
            self.assertFalse(visuals.illustration_required({
                "image_path": PLACEHOLDER_IMAGE,
                "manual_fields": ["image_path"],
            }))

    @unittest.skipIf(visuals.Image is None, "Pillow kullanılamıyor")
    def test_generated_visual_is_separate_and_manual_override_wins(self):
        base = {
            "project_id": "demo", "project_name": "Demo", "version": "v1",
            "hardware_items": [{
                "hardware_id": "HW-1", "part_name": "Fren Balatası",
                "image_path": PLACEHOLDER_IMAGE,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "generated.png"
            manual = Path(directory) / "manual.png"
            visuals.Image.new("RGB", (10, 10), "blue").save(generated)
            visuals.Image.new("RGB", (10, 10), "red").save(manual)
            overrides = management.empty_overrides("Demo", base)
            management.set_generated_visuals(overrides, {"HW-1": {
                "image_path": str(generated),
                "image_source": visuals.ILLUSTRATION_SOURCE,
                "image_is_generated": True,
                "content_fingerprint": visuals.visual_content_fingerprint(
                    base["hardware_items"][0]
                ),
            }})
            view, _ = management.apply_overrides(base, overrides)
            self.assertEqual(view["hardware_items"][0]["image_path"], str(generated))
            management.set_field_override(overrides, "HW-1", "image_path", str(manual), base)
            view, _ = management.apply_overrides(base, overrides)
            self.assertEqual(view["hardware_items"][0]["image_path"], str(manual))

    @unittest.skipIf(visuals.Image is None, "Pillow kullanılamıyor")
    def test_changed_ai_content_invalidates_old_illustration(self):
        item = {
            "hardware_id": "HW-1", "part_name": "Fren Balatası",
            "system_role": "Kuru koşulda frenleme", "image_path": PLACEHOLDER_IMAGE,
        }
        base = {
            "project_id": "demo", "project_name": "Demo", "version": "v1",
            "hardware_items": [item],
        }
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "generated.png"
            visuals.Image.new("RGB", (10, 10), "blue").save(generated)
            overrides = management.empty_overrides("Demo", base)
            management.set_generated_visuals(overrides, {"HW-1": {
                "image_path": str(generated),
                "content_fingerprint": visuals.visual_content_fingerprint(item),
            }})
            changed = dict(base)
            changed["hardware_items"] = [{
                **item, "system_role": "Islak koşulda kontrollü frenleme",
            }]
            view, _ = management.apply_overrides(changed, overrides)
            self.assertEqual(view["hardware_items"][0]["image_path"], PLACEHOLDER_IMAGE)
            self.assertTrue(visuals.illustration_required(view["hardware_items"][0]))


class HardwareSelectionPerformanceTests(unittest.TestCase):
    def test_card_selection_does_not_rebuild_catalog(self):
        workspace = object.__new__(HardwareCardsWorkspace)
        workspace.selected_id = "HW-OLD"
        workspace._card_index = Mock(return_value={"HW-OLD": {}, "HW-NEW": {}})
        workspace._update_card_selection = Mock()
        workspace._render_detail = Mock()
        workspace._render_cards = Mock()
        workspace._syncing_tree_selection = False
        workspace.product_tree = Mock()
        workspace.product_tree.get_children.return_value = ("ROOT",)
        workspace._select_tree_recursive = Mock(return_value=True)
        workspace.cards = Mock()

        workspace.select_card("HW-NEW")

        workspace._render_cards.assert_not_called()
        workspace._render_detail.assert_called_once_with()
        workspace._update_card_selection.assert_any_call("HW-OLD")
        workspace._update_card_selection.assert_any_call("HW-NEW")

    def test_traceability_report_is_loaded_once(self):
        workspace = object.__new__(HardwareCardsWorkspace)
        getter = Mock(return_value={"nodes": [{"id": "REQ-1"}]})
        workspace.traceability_getter = getter
        workspace._traceability_cache = None

        self.assertEqual(workspace._traceability_report()["nodes"][0]["id"], "REQ-1")
        workspace._traceability_report()

        getter.assert_called_once_with()

    def test_queued_tree_event_for_same_card_is_ignored(self):
        workspace = object.__new__(HardwareCardsWorkspace)
        workspace._syncing_tree_selection = False
        workspace.selected_id = "HW-1"
        workspace.product_tree = Mock()
        workspace.product_tree.selection.return_value = ("INST::1",)
        workspace._tree_hardware_id = Mock(return_value="HW-1")
        workspace.select_card = Mock()

        workspace._tree_selected()

        workspace.select_card.assert_not_called()


if __name__ == "__main__":
    unittest.main()
