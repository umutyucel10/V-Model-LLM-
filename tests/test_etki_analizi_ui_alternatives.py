# -*- coding: utf-8 -*-

import unittest

import tkinter as tk

from etki_analizi_logic import calculate_impact_analysis
from etki_analizi_ui import ImpactAnalysisWorkspace


class _FakeVariable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeWidget:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


class _FakeListbox:
    def __init__(self):
        self.items = []
        self.selection = None

    def delete(self, _first, _last):
        self.items.clear()

    def insert(self, _index, value):
        self.items.append(value)

    def selection_set(self, index):
        self.selection = index


class _FakeTree:
    def __init__(self):
        self.options = {}
        self.headings = {}
        self.columns = {}
        self.rows = {}
        self.selected = ()

    def configure(self, **options):
        self.options.update(options)

    def heading(self, key, **options):
        self.headings[key] = options

    def column(self, key, **options):
        self.columns[key] = options

    def delete(self, *items):
        for item in items:
            self.rows.pop(item, None)

    def get_children(self):
        return tuple(self.rows)

    def insert(self, _parent, _index, *, iid, values):
        self.rows[iid] = tuple(values)

    def selection(self):
        return self.selected

    def selection_set(self, item):
        self.selected = (item,)

    def selection_remove(self, *_items):
        self.selected = ()


def _workspace(alternatives=()):
    workspace = ImpactAnalysisWorkspace.__new__(ImpactAnalysisWorkspace)
    workspace.language_getter = lambda: "tr"
    workspace.alternatives = list(alternatives)
    workspace.parameters = []
    workspace.new_alternative = _FakeVariable()
    workspace.active_alternative = _FakeVariable()
    workspace.active_alternative_hint = _FakeVariable()
    workspace.alternative_list = _FakeListbox()
    workspace.active_combo = _FakeWidget()
    workspace.parameter_save_button = _FakeWidget()
    return workspace


class AlternativeSelectorTests(unittest.TestCase):
    def test_empty_selector_is_disabled_and_explains_how_to_add(self):
        workspace = _workspace()

        workspace._refresh_alternatives()

        self.assertEqual(workspace.active_combo.options["state"], "disabled")
        self.assertEqual(workspace.active_combo.options["values"], [])
        self.assertEqual(
            workspace.active_alternative_hint.get(),
            "Önce soldaki alana alternatif adı yazıp Ekle'ye basın.",
        )
        self.assertEqual(
            workspace.parameter_save_button.options["state"], tk.DISABLED
        )

    def test_first_added_alternative_is_visible_and_selected(self):
        workspace = _workspace()
        workspace._refresh_parameter_table = lambda: None
        workspace.new_alternative.set("Seramik Balata B")

        workspace._add_alternative()

        self.assertEqual(workspace.alternatives, ["Seramik Balata B"])
        self.assertEqual(workspace.alternative_list.items, ["Seramik Balata B"])
        self.assertEqual(workspace.alternative_list.selection, 0)
        self.assertEqual(workspace.active_alternative.get(), "Seramik Balata B")
        self.assertEqual(workspace.active_combo.options["state"], "readonly")
        self.assertEqual(
            workspace.active_combo.options["values"], ["Seramik Balata B"]
        )
        self.assertEqual(
            workspace.parameter_save_button.options["state"], tk.NORMAL
        )


class ParameterMatrixTests(unittest.TestCase):
    def test_each_alternative_has_its_own_named_table_column(self):
        workspace = _workspace(["Seramik Balata B", "Yarı Metalik Balata C"])

        definitions = workspace._parameter_table_columns()
        headings = {key: tr for key, tr, _en, _width, _anchor in definitions}

        self.assertEqual(headings["alternative_0"], "Seramik Balata B")
        self.assertEqual(headings["alternative_1"], "Yarı Metalik Balata C")

    def test_five_parameters_and_all_alternative_values_are_visible(self):
        workspace = _workspace(["Seramik Balata B", "Yarı Metalik Balata C"])
        workspace.parameter_tree = _FakeTree()
        workspace.parameter_table_status = _FakeVariable()
        workspace.editing_index = None
        workspace.parameters = [
            {
                "name": f"Parametre {index}",
                "current_value": str(index),
                "alternative_values": {
                    "Seramik Balata B": str(index + 10),
                    "Yarı Metalik Balata C": str(index + 20),
                },
                "unit": "birim",
                "weight": "20",
                "direction": "Yüksek daha iyi",
                "minimum": "0",
                "maximum": "100",
                "mandatory": index == 1,
            }
            for index in range(1, 6)
        ]

        workspace._refresh_parameter_table()

        self.assertEqual(len(workspace.parameter_tree.rows), 5)
        self.assertEqual(
            workspace.parameter_tree.options["columns"][:4],
            ["name", "current", "alternative_0", "alternative_1"],
        )
        self.assertEqual(
            workspace.parameter_tree.rows["0"][:4],
            ("Parametre 1", "1", "11", "21"),
        )
        self.assertEqual(
            workspace.parameter_tree.rows["4"][:4],
            ("Parametre 5", "5", "15", "25"),
        )
        self.assertEqual(
            workspace.parameter_table_status.get(),
            "5 parametre · 2 alternatif",
        )

    def test_sequential_parameter_entries_do_not_overwrite_previous_rows(self):
        workspace = _workspace(["Seramik Balata B"])
        workspace.active_alternative.set("Seramik Balata B")
        workspace.editing_index = None
        workspace.mandatory = _FakeVariable(False)
        workspace.parameter_vars = {
            key: _FakeVariable()
            for key in (
                "name", "current", "alternative", "unit", "weight",
                "direction", "minimum", "maximum",
            )
        }
        workspace._clear_parameter_form = lambda: setattr(
            workspace, "editing_index", None
        )
        workspace._refresh_parameter_table = lambda: None

        for index in range(1, 6):
            values = {
                "name": f"Parametre {index}",
                "current": str(index),
                "alternative": str(index + 10),
                "unit": "birim",
                "weight": "20",
                "direction": "Yüksek daha iyi",
                "minimum": "0",
                "maximum": "100",
            }
            for key, value in values.items():
                workspace.parameter_vars[key].set(value)
            workspace._save_parameter()

        self.assertEqual(
            [item["name"] for item in workspace.parameters],
            [f"Parametre {index}" for index in range(1, 6)],
        )
        self.assertEqual(
            [
                item["alternative_values"]["Seramik Balata B"]
                for item in workspace.parameters
            ],
            ["11", "12", "13", "14", "15"],
        )
        result = calculate_impact_analysis({
            "analysis_name": "Beş parametre testi",
            "current_state": "Mevcut parça",
            "change_reason": "Karşılaştırma",
            "alternatives": workspace.alternatives,
            "parameters": workspace.parameters,
        })
        self.assertEqual(len(result["alternatives"][0]["criteria"]), 5)


if __name__ == "__main__":
    unittest.main()
