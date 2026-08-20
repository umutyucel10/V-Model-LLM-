# -*- coding: utf-8 -*-

import ast
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

import mimari_cerceve_katalog as catalog
from mimari_cerceve_model import FrameworkProfile, ViewDefinition


class ArchitectureCatalogTests(unittest.TestCase):
    def test_required_dodaf_and_naf_packages_are_complete(self):
        self.assertEqual(
            {item.view_id for item in catalog.get_view_package(catalog.DODAF_INITIAL_PACKAGE)},
            set(catalog.DODAF_INITIAL_VIEW_IDS),
        )
        self.assertEqual(
            {item.view_id for item in catalog.get_view_package(catalog.DODAF_SERVICE_PACKAGE)},
            set(catalog.DODAF_SERVICE_VIEW_IDS),
        )
        self.assertEqual(
            {item.view_id for item in catalog.get_view_package(catalog.NAF_INITIAL_PACKAGE)},
            set(catalog.NAF_INITIAL_VIEW_IDS),
        )
        self.assertEqual(len(catalog.VIEW_CATALOG), 21)

    def test_profile_versions_and_ehsim_default_application_profile(self):
        dodaf = catalog.get_framework_profile("DoDAF 2.02")
        naf = catalog.get_framework_profile("NAF 4.1")
        self.assertEqual(dodaf.version, "2.02")
        self.assertEqual(naf.version, "4.1")
        self.assertEqual(naf.default_application_profile, "ArchiMate")
        self.assertEqual(naf.application_profile_version, "3.2")
        self.assertIn("planlanan", dodaf.exchange_target)
        self.assertIn("belirsiz/eksik", naf.exchange_target)

    def test_every_view_has_purpose_prerequisites_and_export_type(self):
        for view in catalog.list_view_definitions():
            with self.subTest(profile=view.framework_profile_id, view=view.view_id):
                self.assertTrue(view.purpose.strip())
                self.assertIsInstance(view.required_element_types, tuple)
                self.assertIsInstance(view.required_relationships, tuple)
                self.assertIsInstance(view.required_any_of_element_types, tuple)
                self.assertIsInstance(view.required_any_of_relationships, tuple)
                self.assertTrue(view.data_prerequisites)
                self.assertIn(
                    view.export_type,
                    {"structured_text", "dictionary", "diagram", "matrix", "table"},
                )
                self.assertEqual(view.implementation_status, "catalog_only")
                self.assertTrue(view.source_url.startswith("https://"))

        self.assertEqual(catalog.get_view_definition("naf", "L2-L3").required_element_types, ())
        self.assertEqual(catalog.get_view_definition("naf", "L2-L3").required_relationships, ())
        self.assertEqual(catalog.get_view_definition("dodaf", "AV-1").required_relationships, ())
        self.assertIn("Protocol", catalog.get_view_definition("naf", "P3").required_element_types)

    def test_naf_conditional_requirements_are_machine_readable(self):
        l2_l3 = catalog.get_view_definition("naf", "L2-L3")
        self.assertEqual(l2_l3.required_element_types, ())
        self.assertEqual(l2_l3.required_relationships, ())
        self.assertEqual(l2_l3.optional_relationships, ())
        self.assertIn("Node", l2_l3.optional_element_types)

        l3 = catalog.get_view_definition("naf", "L3")
        self.assertIn("LogicalActiveResource", l3.required_element_types)
        self.assertIn("Node", l3.optional_element_types)
        self.assertIn("Needline", l3.optional_element_types)

        l4 = catalog.get_view_definition("naf", "L4")
        self.assertEqual(
            l4.required_any_of_element_types,
            (("Node", "Role"),),
        )
        l8 = catalog.get_view_definition("naf", "L8")
        self.assertEqual(
            set(l8.required_any_of_element_types[0]),
            {"LogicalActiveResource", "LogicalBehaviour", "LogicalPassiveResource"},
        )
        p8 = catalog.get_view_definition("naf", "P8")
        self.assertEqual(
            set(p8.required_any_of_element_types[0]),
            {"PhysicalActiveResource", "PhysicalBehaviour", "PhysicalPassiveResource"},
        )

        p4 = catalog.get_view_definition("naf", "P4")
        self.assertNotIn("uses_or_delivers", p4.required_relationships)
        self.assertNotIn("performs", p4.required_relationships)
        self.assertEqual(
            {frozenset(group) for group in p4.required_any_of_relationships},
            {frozenset({"uses", "performs"}), frozenset({"uses", "delivers"})},
        )

    def test_legacy_naf_v3_labels_are_not_canonical_catalog_keys(self):
        view_ids = {view.view_id.upper() for view in catalog.list_view_definitions()}
        self.assertFalse(any(item.startswith("NOV-") for item in view_ids))
        self.assertFalse(any(item.startswith("NSV-") for item in view_ids))
        self.assertFalse(any(item.startswith("NSOV-") for item in view_ids))

    def test_catalog_and_nested_definitions_are_immutable(self):
        with self.assertRaises(TypeError):
            catalog.FRAMEWORK_PROFILES["x"] = catalog.DODAF_PROFILE
        with self.assertRaises(TypeError):
            catalog.VIEW_CATALOG[("naf", "X")] = catalog.NAF_INITIAL_VIEWS[0]
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            catalog.NAF_INITIAL_VIEWS[0].purpose = "Değiştir"
        self.assertIsInstance(catalog.NAF_INITIAL_VIEWS[0].required_element_types, tuple)

    def test_catalog_profiles_round_trip_without_shared_mutation(self):
        for profile in catalog.FRAMEWORK_PROFILES.values():
            payload = json.loads(json.dumps(profile.to_dict(), ensure_ascii=False))
            restored = FrameworkProfile.from_dict(payload)
            self.assertEqual(restored.to_dict(), profile.to_dict())
            self.assertTrue(all(isinstance(item, ViewDefinition) for item in restored.view_definitions))
            payload["view_definitions"][0]["purpose"] = "Dış mutasyon"
            self.assertNotEqual(profile.view_definitions[0].purpose, "Dış mutasyon")

    def test_model_and_catalog_have_no_ui_import_dependency(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ("mimari_cerceve_model.py", "mimari_cerceve_katalog.py"):
            tree = ast.parse((root / filename).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertNotIn("tkinter", imported)
            self.assertNotIn("Arayüz", imported)
            self.assertFalse(any(name.endswith("_ui") for name in imported))


if __name__ == "__main__":
    unittest.main()
