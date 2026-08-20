# -*- coding: utf-8 -*-

from copy import deepcopy
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import mimari_cerceve_ui as ui


class _FakeVariable:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeWidget:
    def __init__(self):
        self.options = {}
        self.grid_calls = []
        self.pack_calls = []
        self.grid_forget_count = 0
        self.visible = False

    def configure(self, **options):
        self.options.update(options)

    config = configure

    def grid(self, **options):
        self.grid_calls.append(options)
        self.visible = True

    def grid_configure(self, **options):
        self.grid_calls.append(options)

    def pack(self, **options):
        self.pack_calls.append(options)

    def grid_forget(self):
        self.grid_forget_count += 1
        self.visible = False

    def grid_remove(self):
        self.grid_forget()


class _FakeTree:
    def __init__(self):
        self.rows = []

    def get_children(self):
        return tuple(range(len(self.rows)))

    def delete(self, *_items):
        self.rows.clear()

    def insert(self, _parent, _index, *, values, tags=()):
        self.rows.append({"values": tuple(values), "tags": tuple(tags)})
        return str(len(self.rows) - 1)


class _FakeBody:
    def __init__(self):
        self.column_weights = {}
        self.row_weights = {}

    def columnconfigure(self, index, *, weight):
        self.column_weights[index] = weight

    def rowconfigure(self, index, *, weight):
        self.row_weights[index] = weight


class _PollingWindow:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))
        return f"after-{len(self.after_calls)}"

    def winfo_exists(self):
        return True


def _headless_workspace(language="tr"):
    workspace = object.__new__(ui.ArchitectureFrameworkWorkspace)
    workspace._language_override = None
    workspace.language_getter = lambda: language
    workspace.project_name_getter = lambda: "Proje"
    workspace._active_project_name = "Proje"
    workspace._closed = False
    workspace._state_write_lock = threading.RLock()
    workspace._lifecycle_lock = threading.RLock()
    workspace._state_revision = 0
    workspace._source_change_token = 0
    return workspace


class ArchitectureUiStaticContractTests(unittest.TestCase):
    def test_five_workflow_steps_are_ordered_and_bilingual(self):
        self.assertEqual(
            [step.step_id for step in ui.WORKFLOW_STEPS],
            ["sources", "extract", "review", "render", "validate_export"],
        )
        self.assertEqual(
            [step.tr for step in ui.WORKFLOW_STEPS],
            [
                "Kaynakları seç",
                "Mimari adayları çıkar",
                "Gözden geçir",
                "Görünüm üret",
                "Doğrula ve dışa aktar",
            ],
        )
        self.assertEqual(
            [step.en for step in ui.WORKFLOW_STEPS],
            [
                "Select sources",
                "Extract architecture candidates",
                "Review",
                "Generate view",
                "Validate and export",
            ],
        )

    def test_profile_choices_show_exact_framework_and_application_versions(self):
        self.assertEqual(tuple(ui.PROFILE_OPTIONS), ("dodaf", "naf"))
        self.assertEqual(ui.PROFILE_OPTIONS["dodaf"].tr, "DoDAF 2.02")
        self.assertEqual(ui.PROFILE_OPTIONS["dodaf"].framework_version, "2.02")
        naf = ui.PROFILE_OPTIONS["naf"]
        self.assertEqual(naf.tr, "NAF 4.1 / ArchiMate 3.2")
        self.assertEqual(naf.framework_version, "4.1")
        self.assertEqual((naf.application_profile, naf.application_profile_version),
                         ("ArchiMate", "3.2"))

    def test_profile_filters_expose_only_kart5_render_views(self):
        self.assertEqual(
            ui.PROFILE_VIEW_IDS["dodaf"],
            ("AV-2", "SV-1", "SV-2", "SV-4", "SV-5a", "SV-7"),
        )
        self.assertEqual(
            ui.PROFILE_VIEW_IDS["naf"],
            ("L2-L3", "L3", "L4", "L8", "P2", "P3", "P4", "L4-P4", "P8"),
        )
        self.assertNotIn("AV-1", ui.PROFILE_VIEW_IDS["dodaf"])
        self.assertFalse(any(view_id.startswith("SvcV-")
                             for view_id in ui.PROFILE_VIEW_IDS["dodaf"]))

    def test_status_palette_has_distinct_required_semantic_roles(self):
        expected_roles = {"selection", "verified", "review", "error", "no_data"}
        self.assertEqual(set(ui.LIGHT_STATUS_COLORS), expected_roles)
        self.assertEqual(set(ui.DARK_STATUS_COLORS), expected_roles)
        self.assertEqual(
            dict(ui.LIGHT_STATUS_COLORS),
            {
                "selection": "#0052CC",
                "verified": "#217A43",
                "review": "#9A6400",
                "error": "#B42318",
                "no_data": "#667085",
            },
        )
        self.assertEqual(len(set(ui.LIGHT_STATUS_COLORS.values())), 5)
        self.assertEqual(len(set(ui.DARK_STATUS_COLORS.values())), 5)

    def test_layout_boundary_selects_wide_and_narrow_modes(self):
        self.assertEqual(ui.layout_mode_for_width(ui.LAYOUT_BREAKPOINT - 1), "narrow")
        self.assertEqual(ui.layout_mode_for_width(ui.LAYOUT_BREAKPOINT), "wide")
        self.assertEqual(ui.layout_mode_for_width(1920), "wide")
        with self.assertRaises(TypeError):
            ui.layout_mode_for_width(object())


class SourceRequirementPresenterTests(unittest.TestCase):
    def setUp(self):
        self.flat_data = {
            "tid-key": {
                "type": "TID", "ID": "TID-002",
                "content": "Operatör sistemi durdurabilmelidir.",
            },
            "sgd-key": {
                "type": "SGD", "ID": "SGD-010",
                "content": "Fren Sistemi 28 V besleme alır.", "bound_to": "TID-002",
            },
            "stt-key": {
                "type": "STT", "ID": "STT-003",
                "description": "Fren Sistemi gerilim testi.", "parent_id": "SGD-010",
            },
            "kmtd-key": {
                "type": "KMTD", "ID": "KMTD-001", "content": "Kapsam dışı",
            },
            "bad": "mapping olmayan kayıt",
        }

    def test_filter_keeps_only_tid_sgd_stt_in_stable_order_without_mutation(self):
        before = deepcopy(self.flat_data)

        rows = ui.filter_source_requirements(self.flat_data)

        self.assertEqual(self.flat_data, before)
        self.assertEqual(
            [(row.record_type, row.requirement_id) for row in rows],
            [("TID", "TID-002"), ("SGD", "SGD-010"), ("STT", "STT-003")],
        )
        self.assertEqual(rows[1].bound_to, "TID-002")
        self.assertEqual(rows[2].content, "Fren Sistemi gerilim testi.")

    def test_query_and_type_filters_search_ids_content_and_parent(self):
        by_content = ui.filter_source_requirements(self.flat_data, query="28 v")
        by_parent = ui.filter_source_requirements(self.flat_data, query="SGD-010")
        by_type = ui.filter_source_requirements(self.flat_data, types="STT")
        unsupported = ui.filter_source_requirements(self.flat_data, types="KMTD")

        self.assertEqual([row.requirement_id for row in by_content], ["SGD-010"])
        self.assertEqual(
            [row.requirement_id for row in by_parent],
            ["SGD-010", "STT-003"],
        )
        self.assertEqual([row.requirement_id for row in by_type], ["STT-003"])
        self.assertEqual(unsupported, ())


class ViewCardStatusTests(unittest.TestCase):
    def test_all_four_card_states_and_bilingual_labels(self):
        rendered = SimpleNamespace(status="rendered", missing_inputs=())
        missing = SimpleNamespace(status="blocked", missing_inputs=("System x 2",))
        blocked = SimpleNamespace(status="blocked", missing_inputs=())

        self.assertEqual(ui.classify_view_card_state(rendered), ui.VIEW_READY)
        self.assertEqual(
            ui.classify_view_card_state(rendered, pending_candidates=1),
            ui.VIEW_REVIEW_REQUIRED,
        )
        self.assertEqual(ui.classify_view_card_state(missing), ui.VIEW_MISSING_INPUT)
        self.assertEqual(ui.classify_view_card_state(blocked), ui.VIEW_BLOCKED)
        self.assertEqual(
            [ui.view_card_status_label(value, "tr") for value in (
                ui.VIEW_READY, ui.VIEW_REVIEW_REQUIRED,
                ui.VIEW_MISSING_INPUT, ui.VIEW_BLOCKED,
            )],
            ["Hazır", "İnceleme Gerekli", "Eksik Girdi", "Engelli"],
        )
        self.assertEqual(ui.view_card_status_label(ui.VIEW_READY, "en"), "Ready")

    def test_integrity_stale_and_explicit_block_override_other_states(self):
        rendered = SimpleNamespace(status="rendered", missing_inputs=())
        failed_integrity = SimpleNamespace(
            model_integrity=SimpleNamespace(passed=False, findings=()),
        )
        self.assertEqual(
            ui.classify_view_card_state(rendered, failed_integrity),
            ui.VIEW_BLOCKED,
        )
        self.assertEqual(
            ui.classify_view_card_state(rendered, stale=True),
            ui.VIEW_BLOCKED,
        )
        self.assertEqual(
            ui.classify_view_card_state(rendered, blocked=True),
            ui.VIEW_BLOCKED,
        )

    def test_view_or_framework_error_cannot_be_shown_as_verified_ready(self):
        rendered = SimpleNamespace(status="rendered", missing_inputs=())
        blocking_finding = SimpleNamespace(
            severity="error", blocking=True,
        )
        failed_view = SimpleNamespace(
            model_integrity=SimpleNamespace(passed=True, findings=()),
            view_generatability=SimpleNamespace(passed=False, findings=(blocking_finding,)),
            framework_conformance=SimpleNamespace(aligned=True, findings=()),
        )
        failed_framework = SimpleNamespace(
            model_integrity=SimpleNamespace(passed=True, findings=()),
            view_generatability=SimpleNamespace(passed=True, findings=()),
            framework_conformance=SimpleNamespace(aligned=False, findings=(blocking_finding,)),
        )

        self.assertEqual(
            ui.classify_view_card_state(rendered, failed_view), ui.VIEW_BLOCKED,
        )
        self.assertEqual(
            ui.classify_view_card_state(rendered, failed_framework), ui.VIEW_BLOCKED,
        )

    def test_unknown_card_state_is_missing_input_and_invalid_label_is_rejected(self):
        self.assertEqual(ui.classify_view_card_state(), ui.VIEW_MISSING_INPUT)
        with self.assertRaises(ValueError):
            ui.view_card_status_label("unknown", "tr")


class ResponsiveLayoutSmokeTests(unittest.TestCase):
    def _workspace(self):
        workspace = _headless_workspace()
        workspace._layout_mode = ""
        workspace.body = _FakeBody()
        workspace.step_bar = _FakeBody()
        workspace.step_buttons = {
            step.step_id: _FakeWidget() for step in ui.WORKFLOW_STEPS
        }
        workspace.active_step_var = _FakeVariable("sources")
        workspace.source_panel = _FakeWidget()
        workspace.center_panel = _FakeWidget()
        workspace.inspector_panel = _FakeWidget()
        return workspace

    def test_wide_layout_places_sources_canvas_and_inspector_in_three_columns(self):
        workspace = self._workspace()

        workspace._apply_responsive_layout(1600)

        self.assertEqual(workspace._layout_mode, "wide")
        self.assertEqual(workspace.body.column_weights, {0: 3, 1: 6, 2: 4})
        self.assertEqual(workspace.source_panel.grid_calls[-1]["column"], 0)
        self.assertEqual(workspace.center_panel.grid_calls[-1]["column"], 1)
        self.assertEqual(workspace.inspector_panel.grid_calls[-1]["column"], 2)
        self.assertTrue(all(
            panel.grid_calls[-1]["row"] == 0
            for panel in (
                workspace.source_panel, workspace.center_panel, workspace.inspector_panel,
            )
        ))

    def test_narrow_layout_keeps_all_three_regions_accessible_through_steps(self):
        workspace = self._workspace()
        workspace._apply_responsive_layout(1600)

        workspace._apply_responsive_layout(900)

        self.assertEqual(workspace._layout_mode, "narrow")
        self.assertEqual(workspace.body.column_weights[0], 1)
        self.assertEqual(
            [workspace.source_panel.grid_calls[-1]["row"],
             workspace.center_panel.grid_calls[-1]["row"],
             workspace.inspector_panel.grid_calls[-1]["row"]],
            [0, 0, 0],
        )
        self.assertTrue(workspace.source_panel.visible)
        self.assertFalse(workspace.center_panel.visible)
        self.assertFalse(workspace.inspector_panel.visible)
        self.assertEqual(workspace.source_panel.grid_calls[-1]["column"], 0)

    def test_resize_ignores_child_widget_events(self):
        workspace = _headless_workspace()
        workspace.window = object()
        workspace._apply_responsive_layout = Mock()

        workspace._on_resize(SimpleNamespace(widget=object(), width=800))
        workspace._apply_responsive_layout.assert_not_called()

        workspace._on_resize(SimpleNamespace(widget=workspace.window, width=800))
        workspace._apply_responsive_layout.assert_called_once_with(800)

    def test_narrow_mode_shows_the_panel_for_each_selected_workflow_step(self):
        workspace = self._workspace()
        workspace._apply_responsive_layout(900)
        expected_panel = {
            "sources": workspace.source_panel,
            "extract": workspace.source_panel,
            "review": workspace.inspector_panel,
            "render": workspace.center_panel,
            "validate_export": workspace.inspector_panel,
        }

        for step_id, active_panel in expected_panel.items():
            with self.subTest(step=step_id):
                workspace._select_step(step_id)
                self.assertTrue(active_panel.visible)
                self.assertEqual(active_panel.grid_calls[-1]["row"], 0)
                self.assertTrue(all(
                    not panel.visible
                    for panel in (
                        workspace.source_panel,
                        workspace.center_panel,
                        workspace.inspector_panel,
                    )
                    if panel is not active_panel
                ))


class LanguageAndThemeSmokeTests(unittest.TestCase):
    def test_refresh_language_updates_registered_widgets_and_navigation_labels(self):
        workspace = _headless_workspace(language="en")
        workspace.window = MagicMock()
        workspace.window.winfo_exists.return_value = 1
        translated = _FakeWidget()
        workspace._translatable = [(translated, "Türkçe", "English")]
        workspace.language_button = _FakeWidget()
        workspace.source_tree = MagicMock()
        workspace.candidate_tree = MagicMock()
        workspace.relationship_tree = MagicMock()
        workspace.validation_tree = MagicMock()
        workspace.preview_notebook = MagicMock()
        workspace.inspector_notebook = MagicMock()
        workspace._update_source_count = Mock()
        workspace._refresh_view_cards = Mock()
        workspace._show_selected_candidate = Mock()

        workspace.refresh_language()

        workspace.window.title.assert_called_once_with("Architecture Framework Studio")
        self.assertEqual(translated.options["text"], "English")
        self.assertEqual(workspace.language_button.options["text"], "TR")
        workspace.source_tree.heading.assert_any_call("content", text="Requirement")
        workspace.preview_notebook.tab.assert_called_once_with(0, text="Diagram")
        workspace.inspector_notebook.tab.assert_any_call(3, text="Validation")

    def test_dark_theme_applies_required_status_roles_without_real_tk(self):
        workspace = _headless_workspace()
        workspace.window = MagicMock()
        workspace.window.winfo_exists.return_value = 1
        workspace._palette_override = None
        workspace.palette_getter = lambda: {
            "bg": "#1F2329", "surface": "#2B303A", "fg": "#E4E6EA",
            "muted": "#95A0A8", "entry_bg": "#2B303A",
            "entry_fg": "#E8EAED", "accent": "#5AA0F2",
        }
        workspace.style = MagicMock()
        workspace.detail_text = MagicMock()
        workspace.evidence_text = MagicMock()
        workspace.svg_text = MagicMock()
        workspace.preview_canvas = MagicMock()
        workspace._refresh_view_cards = Mock()

        workspace.apply_theme()

        workspace.window.configure.assert_called_with(background="#1F2329")
        workspace.style.configure.assert_any_call(
            "Architecture.Ready.TLabel", background="#2B303A",
            foreground=ui.DARK_STATUS_COLORS["verified"],
            font=("Segoe UI", 8, "bold"),
        )
        workspace.style.configure.assert_any_call(
            "Architecture.Review.TLabel", background="#2B303A",
            foreground=ui.DARK_STATUS_COLORS["review"],
            font=("Segoe UI", 8, "bold"),
        )
        workspace.style.configure.assert_any_call(
            "Architecture.Error.TLabel", background="#2B303A",
            foreground=ui.DARK_STATUS_COLORS["error"],
            font=("Segoe UI", 8, "bold"),
        )
        workspace.style.configure.assert_any_call(
            "Architecture.NoData.TLabel", background="#2B303A",
            foreground=ui.DARK_STATUS_COLORS["no_data"],
            font=("Segoe UI", 8, "bold"),
        )


class WorkerThreadSmokeTests(unittest.TestCase):
    def test_start_extraction_copies_selected_sources_and_starts_daemon_worker(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace._selected_source_ids = Mock(return_value=("TID-001",))
        flat_data = {
            "TID-001": {"type": "TID", "ID": "TID-001", "content": "Kaynak"},
            "SGD-002": {"type": "SGD", "ID": "SGD-002", "content": "Seçilmedi"},
        }
        traceability = {"nodes": [{"id": "TID-001"}], "edges": []}
        workspace.flat_data_getter = lambda: flat_data
        workspace.traceability_getter = lambda: traceability
        workspace.profile_var = _FakeVariable("dodaf")
        workspace._extraction_token = 4
        workspace._extraction_context = {}
        workspace._active_project_name = "Worker Project"
        workspace.project_name_getter = lambda: "Worker Project"
        workspace._busy = Mock()
        workspace.status_var = _FakeVariable()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace._start_extraction()

        thread_class.return_value.start.assert_called_once_with()
        kwargs = thread_class.call_args.kwargs
        self.assertIs(kwargs["target"].__self__, workspace)
        self.assertEqual(kwargs["target"].__func__, ui.ArchitectureFrameworkWorkspace._extraction_worker)
        self.assertTrue(kwargs["daemon"])
        self.assertEqual(kwargs["name"], "architecture-candidate-extraction")
        (
            token, flat_snapshot, trace_snapshot, profile_id,
            state_payload, expected_state_revision,
        ) = kwargs["args"]
        self.assertEqual((token, profile_id), (5, "dodaf"))
        self.assertIsNone(state_payload)
        self.assertEqual(expected_state_revision, 0)
        self.assertEqual(set(flat_snapshot), {"TID-001"})
        self.assertIsNot(flat_snapshot["TID-001"], flat_data["TID-001"])
        self.assertIsNot(trace_snapshot, traceability)
        profile, project, known_ids, fingerprints = workspace._extraction_context[token]
        self.assertEqual((profile, project), ("dodaf", "Worker Project"))
        self.assertEqual(known_ids, ("TID-001", "SGD-002"))
        self.assertEqual(
            fingerprints,
            ui.management.source_requirement_fingerprints(flat_data),
        )

    def test_start_render_defers_snapshot_build_and_render_to_daemon_worker(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace.view_var = _FakeVariable("SV-1")
        state = object()
        workspace.management_state = state
        workspace.preview_canvas = MagicMock()
        workspace.preview_canvas.winfo_width.return_value = 340
        workspace.preview_canvas.winfo_height.return_value = 240
        workspace._render_token = 8
        workspace._busy = Mock()
        workspace.current_snapshot = None
        workspace.status_var = _FakeVariable()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace._start_render()

        thread_class.return_value.start.assert_called_once_with()
        kwargs = thread_class.call_args.kwargs
        self.assertIs(kwargs["target"].__self__, workspace)
        self.assertEqual(kwargs["target"].__func__, ui.ArchitectureFrameworkWorkspace._render_worker)
        self.assertEqual(kwargs["args"], (9, state, "SV-1", (320, 220)))
        self.assertTrue(kwargs["daemon"])
        self.assertEqual(kwargs["name"], "architecture-svg-render")
        self.assertIsNone(workspace.current_snapshot)

    def test_workers_never_call_tk_and_main_thread_poller_applies_completions(self):
        workspace = _headless_workspace()
        workspace.window = _PollingWindow()
        workspace._ui_queue = queue.Queue()
        workspace._poll_after_id = None
        workspace.status_var = _FakeVariable()
        workspace._finish_extraction = Mock()
        workspace._finish_render = Mock()
        prepared_state = object()
        workspace._prepare_extraction_state = Mock(return_value=prepared_state)
        extraction_result = object()
        render_result = SimpleNamespace(
            status=ui.rendering.RENDER_STATUS_RENDERED,
            svg="<svg/>",
        )
        snapshot = object()
        state = SimpleNamespace(to_dict=Mock(return_value={}))
        working_state = object()
        flat_data = {"TID-001": {"type": "TID"}}
        traceability = {"nodes": [], "edges": []}

        with patch.object(
            ui.extraction, "extract_architecture_candidates", return_value=extraction_result,
        ) as extract_call, patch.object(
            ui.management.ArchitectureManagementState, "from_dict",
            return_value=working_state,
        ), patch.object(
            ui.management, "build_working_snapshot", return_value=snapshot,
        ) as snapshot_call, patch.object(
            ui.rendering, "render_view", return_value=render_result,
        ) as render_call, patch.object(
            workspace, "_rasterize_svg_preview", return_value="preview",
        ):
            workspace._extraction_worker(3, flat_data, traceability, "naf")
            workspace._render_worker(4, state, "L3", (320, 220))

        workspace._finish_extraction.assert_not_called()
        workspace._finish_render.assert_not_called()
        self.assertEqual(workspace.window.after_calls, [])
        self.assertEqual(workspace._ui_queue.qsize(), 2)
        extract_call.assert_called_once_with(
            flat_data, traceability, framework_profile_id="naf",
        )
        snapshot_call.assert_called_once_with(
            working_state, ("L3",), version="v0001",
        )
        render_call.assert_called_once_with(snapshot, "L3")

        workspace._poll_ui_queue()

        workspace._finish_extraction.assert_called_once_with(
            3, extraction_result, None, prepared_state,
        )
        workspace._finish_render.assert_called_once_with(
            4, snapshot, "L3", render_result, "preview", "", None,
        )
        self.assertEqual(len(workspace.window.after_calls), 1)
        delay, callback = workspace.window.after_calls[0]
        self.assertEqual(delay, 40)
        self.assertEqual(callback.__func__, ui.ArchitectureFrameworkWorkspace._poll_ui_queue)

    def test_extraction_load_reconcile_and_save_run_on_worker_not_tk_poller(self):
        workspace = _headless_workspace()
        workspace._extraction_token = 7
        workspace._state_revision = 11
        workspace._extraction_context = {
            # Eski üç alanlı context de desteklenmeye devam eder.
            7: ("dodaf", "Proje", ("TID-001",)),
        }
        workspace._ui_queue = queue.Queue()
        workspace._finish_extraction = Mock()
        result = SimpleNamespace(
            framework_profile_id="dodaf",
            candidates=(object(),),
            processed_requirement_ids=("TID-001",),
        )
        prepared_state = SimpleNamespace(framework_profile_id="dodaf")
        main_thread_id = threading.get_ident()
        io_thread_ids = []

        def record_io(*_args, **_kwargs):
            io_thread_ids.append(threading.get_ident())

        with patch.object(
            ui.extraction, "extract_architecture_candidates", return_value=result,
        ), patch.object(
            ui.management, "load_profile_management_state",
            side_effect=lambda *_args, **_kwargs: (record_io(), None)[1],
        ), patch.object(
            ui.management, "create_management_state", return_value=prepared_state,
        ), patch.object(
            ui.management, "save_profile_management_state", side_effect=record_io,
        ):
            worker = threading.Thread(
                target=workspace._extraction_worker,
                args=(7, {"TID-001": {"type": "TID"}}, {"nodes": []},
                      "dodaf", None, 11),
            )
            worker.start()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(io_thread_ids)
        self.assertTrue(all(item != main_thread_id for item in io_thread_ids))
        workspace._finish_extraction.assert_not_called()
        callback = workspace._ui_queue.get_nowait()
        callback()
        workspace._finish_extraction.assert_called_once_with(
            7, result, None, prepared_state,
        )

    def test_extraction_state_revision_cas_rejects_save_after_concurrent_change(self):
        workspace = _headless_workspace()
        workspace._extraction_token = 8
        workspace._state_revision = 3
        workspace._extraction_context = {
            8: ("dodaf", "Proje", ("TID-001",), {}),
        }
        result = SimpleNamespace(
            framework_profile_id="dodaf",
            candidates=(object(),),
            processed_requirement_ids=("TID-001",),
        )
        state = SimpleNamespace(framework_profile_id="dodaf")

        def change_revision(*_args, **_kwargs):
            workspace._state_revision += 1

        with patch.object(
            ui.management.ArchitectureManagementState, "from_dict",
            return_value=state,
        ), patch.object(
            ui.management, "reconcile_candidates", side_effect=change_revision,
        ), patch.object(
            ui.management, "save_profile_management_state",
        ) as save_state:
            with self.assertRaises(ui.management.ArchitectureManagementError):
                workspace._prepare_extraction_state(
                    8, result, state_payload={"records": {}},
                    expected_state_revision=3,
                )

        save_state.assert_not_called()

    def test_extraction_thread_start_error_clears_busy_context_and_reports_status(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace._selected_source_ids = Mock(return_value=("TID-001",))
        workspace.flat_data_getter = lambda: {
            "TID-001": {
                "type": "TID", "ID": "TID-001", "content": "Kaynak",
            },
        }
        workspace.traceability_getter = lambda: {"nodes": [], "edges": []}
        workspace.profile_var = _FakeVariable("dodaf")
        workspace._extraction_token = 12
        workspace._extraction_context = {}
        workspace.status_var = _FakeVariable()

        def remember_busy(value, _message=""):
            workspace._working = bool(value)

        workspace._busy = Mock(side_effect=remember_busy)

        with patch.object(ui.threading, "Thread") as thread_class:
            thread_class.return_value.start.side_effect = RuntimeError("thread unavailable")
            workspace._start_extraction()

        self.assertFalse(workspace._working)
        self.assertEqual(workspace._extraction_context, {})
        self.assertEqual(workspace._extraction_token, 14)
        self.assertIn("thread unavailable", workspace.status_var.get())
        self.assertEqual(workspace._busy.call_args_list[-1].args, (False,))

    def test_pending_source_revision_allows_repair_extract_but_blocks_outputs(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace._source_revision_blocked = True
        workspace._source_generation_in_progress = False
        workspace._traceability_revision_blocked = False
        workspace.status_var = _FakeVariable()
        workspace.management_state = object()
        workspace.current_render_result = SimpleNamespace(
            status=ui.rendering.RENDER_STATUS_RENDERED,
            svg="<svg/>", view_id="SV-1",
        )
        workspace._selected_source_ids = Mock(return_value=("TID-001",))
        workspace.flat_data_getter = lambda: {
            "TID-001": {
                "type": "TID", "ID": "TID-001", "content": "Güncel kaynak",
            },
        }
        workspace.traceability_getter = lambda: {"nodes": [], "edges": []}
        workspace.profile_var = _FakeVariable("dodaf")
        workspace._extraction_token = 0
        workspace._extraction_context = {}
        workspace._busy = Mock()

        with patch.object(ui.threading, "Thread") as thread_class, patch.object(
            ui.filedialog, "asksaveasfilename",
        ) as save_dialog:
            workspace._start_extraction()
            workspace._start_render()
            workspace._validate_current()
            workspace._export_svg()

        thread_class.assert_called_once()
        self.assertEqual(
            thread_class.call_args.kwargs["name"],
            "architecture-candidate-extraction",
        )
        save_dialog.assert_not_called()
        self.assertIn("henüz birlikte hazır değil", workspace.status_var.get())

    def test_incomplete_traceability_blocks_repair_extraction(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace._source_revision_blocked = True
        workspace._source_generation_in_progress = False
        workspace._traceability_revision_blocked = True
        workspace.status_var = _FakeVariable()
        workspace._selected_source_ids = Mock(return_value=("TID-001",))

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace._start_extraction()

        thread_class.assert_not_called()
        self.assertIn("henüz birlikte hazır değil", workspace.status_var.get())

    def test_failed_two_profile_source_save_stays_blocked_until_both_profiles_repaired(self):
        workspace = _headless_workspace()
        workspace._active_project_name = "Proje"
        workspace._extraction_token = 1
        workspace._extraction_context = {
            1: ("dodaf", "Proje", ("TID-001",), {"TID-001": "a" * 64}),
        }
        workspace._states_by_profile = {}
        workspace._pending_source_profiles = {"dodaf", "naf"}
        workspace._pending_source_changed_ids = {"TID-001"}
        workspace._pending_source_mark_all = True
        workspace._source_revision_blocked = True
        workspace._source_generation_in_progress = False
        workspace._traceability_revision_blocked = False
        workspace._state_revision = 0
        workspace._busy = Mock()
        workspace._invalidate_architecture_outputs = Mock()
        workspace._refresh_candidate_tree = Mock()
        workspace._refresh_view_cards = Mock()
        workspace._select_step = Mock()
        workspace.status_var = _FakeVariable()
        candidate = object()

        def result_for(profile_id):
            return SimpleNamespace(
                framework_profile_id=profile_id,
                candidates=(candidate,),
                information_gaps=(),
                processed_requirement_ids=("TID-001",),
            )

        def state_for(_project, _candidates, *, framework_profile_id, **_kwargs):
            return SimpleNamespace(framework_profile_id=framework_profile_id)

        with patch.object(
            ui.management, "load_profile_management_state", return_value=None,
        ), patch.object(
            ui.management, "create_management_state", side_effect=state_for,
        ), patch.object(ui.management, "save_profile_management_state"):
            dodaf_result = result_for("dodaf")
            dodaf_state = workspace._prepare_extraction_state(1, dodaf_result)
            workspace._finish_extraction(1, dodaf_result, None, dodaf_state)
            self.assertEqual(workspace._pending_source_profiles, {"naf"})
            self.assertTrue(workspace._source_revision_blocked)

            workspace._extraction_token = 2
            workspace._extraction_context[2] = (
                "naf", "Proje", ("TID-001",), {"TID-001": "a" * 64},
            )
            naf_result = result_for("naf")
            naf_state = workspace._prepare_extraction_state(2, naf_result)
            workspace._finish_extraction(2, naf_result, None, naf_state)

        self.assertEqual(workspace._pending_source_profiles, set())
        self.assertFalse(workspace._source_revision_blocked)
        self.assertEqual(workspace._pending_source_changed_ids, set())
        self.assertFalse(workspace._pending_source_mark_all)


class SourceChangeLifecycleTests(unittest.TestCase):
    @staticmethod
    def _original_state(profile_id="dodaf"):
        return SimpleNamespace(
            framework_profile_id=profile_id,
            to_dict=Mock(return_value={
                "project_name": "Proje", "framework_profile_id": profile_id,
                "records": {},
            }),
        )

    def _workspace(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace._source_change_token = 20
        workspace._extraction_token = 2
        workspace._render_token = 3
        workspace._validation_token = 4
        workspace._publish_token = 5
        workspace._publish_cancel_event = threading.Event()
        workspace._source_revision_blocked = False
        workspace._extraction_context = {2: ("dodaf", "Proje", ("SGD-001",))}
        workspace.profile_var = _FakeVariable("dodaf")
        workspace.status_var = _FakeVariable()
        workspace.flat_data_getter = lambda: {
            "TID-001": {"type": "TID", "ID": "TID-001", "content": "Ana ister"},
            "SGD-002": {"type": "SGD", "ID": "SGD-002", "content": "Alt ister"},
        }
        workspace._states_by_profile = {
            "dodaf": self._original_state("dodaf"),
            "naf": self._original_state("naf"),
        }
        workspace.management_state = workspace._states_by_profile["dodaf"]
        workspace.current_snapshot = object()
        workspace.current_render_result = object()
        workspace.current_validation_report = object()
        workspace._render_results = {
            ("dodaf", "SV-1"): object(), ("naf", "L3"): object(),
        }
        workspace._validation_reports = {
            ("dodaf", "SV-1"): object(), ("naf", "L3"): object(),
        }
        workspace._preview_images = {
            ("dodaf", "SV-1"): object(), ("naf", "L3"): object(),
        }
        workspace._preview_errors = {
            ("dodaf", "SV-1"): "old", ("naf", "L3"): "old",
        }

        def remember_busy(value, _message=""):
            workspace._working = bool(value)

        workspace._busy = Mock(side_effect=remember_busy)
        return workspace

    def test_source_change_invalidates_outputs_immediately_and_only_schedules_daemon_state_work(self):
        workspace = self._workspace()

        with patch.object(ui.threading, "Thread") as thread_class, patch.object(
            ui.management.ArchitectureManagementState, "from_dict",
        ) as clone_state, patch.object(
            ui.management, "mark_candidate_stale",
        ) as mark_stale, patch.object(
            ui.management, "save_profile_management_state",
        ) as save_state:
            workspace.on_sources_changed((" sgd-002 ", "SGD-002", "tid-001"))

        self.assertTrue(workspace._source_revision_blocked)
        self.assertTrue(workspace._publish_cancel_event.is_set())
        self.assertEqual(workspace._extraction_context, {})
        self.assertIsNone(workspace.current_snapshot)
        self.assertIsNone(workspace.current_render_result)
        self.assertIsNone(workspace.current_validation_report)
        self.assertEqual(workspace._render_results, {})
        self.assertEqual(workspace._validation_reports, {})
        self.assertEqual(workspace._preview_images, {})
        self.assertEqual(workspace._preview_errors, {})
        clone_state.assert_not_called()
        mark_stale.assert_not_called()
        save_state.assert_not_called()

        thread_class.assert_called_once()
        kwargs = thread_class.call_args.kwargs
        self.assertIs(kwargs["target"].__self__, workspace)
        self.assertEqual(
            kwargs["target"].__func__,
            ui.ArchitectureFrameworkWorkspace._source_change_worker,
        )
        self.assertTrue(kwargs["daemon"])
        self.assertEqual(kwargs["name"], "architecture-source-change")
        token, states, changed_ids, mark_all, known_ids, fingerprints = kwargs["args"]
        self.assertEqual(token, 21)
        self.assertEqual([profile for profile, _state in states], ["dodaf", "naf"])
        self.assertEqual(changed_ids, frozenset({"SGD-002", "TID-001"}))
        self.assertFalse(mark_all)
        self.assertEqual(known_ids, ("TID-001", "SGD-002"))
        self.assertEqual(set(fingerprints), {"TID-001", "SGD-002"})
        thread_class.return_value.start.assert_called_once_with()

    def test_source_change_switches_project_before_capturing_states_or_sources(self):
        workspace = self._workspace()
        old_dodaf_state = workspace._states_by_profile["dodaf"]
        old_naf_state = workspace._states_by_profile["naf"]
        workspace._active_project_name = "Project A"
        workspace.project_name_getter = lambda: "Project B"
        workspace._pending_source_changed_ids = set()
        workspace._pending_source_mark_all = False
        workspace.refresh = Mock()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace.on_sources_changed(("SGD-002",))

        self.assertEqual(workspace._active_project_name, "Project B")
        self.assertEqual(workspace._states_by_profile, {})
        self.assertIsNone(workspace.management_state)
        _token, states, _changed, _mark_all, known, _fingerprints = (
            thread_class.call_args.kwargs["args"]
        )
        self.assertEqual(states, ())
        self.assertEqual(known, ("TID-001", "SGD-002"))
        self.assertNotIn(old_dodaf_state, [state for _profile, state in states])
        self.assertNotIn(old_naf_state, [state for _profile, state in states])
        workspace.refresh.assert_called_once_with()

    def test_overlapping_source_changes_are_coalesced_until_latest_save_succeeds(self):
        workspace = self._workspace()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace.on_sources_changed(("SGD-002",))
            workspace.on_sources_changed(("TID-001",))

        self.assertEqual(thread_class.call_count, 2)
        _token, _states, changed_ids, mark_all, _known, _fingerprints = (
            thread_class.call_args.kwargs["args"]
        )
        self.assertEqual(changed_ids, frozenset({"SGD-002", "TID-001"}))
        self.assertFalse(mark_all)

    def test_overlapping_source_workers_are_serialized_and_latest_generation_writes_last(self):
        workspace = self._workspace()
        workspace._source_change_token = 41
        workspace._ui_queue = queue.Queue()
        old_save_started = threading.Event()
        release_old_save = threading.Event()
        new_worker_prepared = threading.Event()
        new_save_entered = threading.Event()
        saved_generations = []

        def original(label):
            return SimpleNamespace(to_dict=lambda: {"label": label})

        def clone(payload):
            if payload["label"] == "new":
                new_worker_prepared.set()
            return SimpleNamespace(
                label=payload["label"], records={}, known_requirement_ids=(),
            )

        def save(working):
            if working.label == "old":
                old_save_started.set()
                self.assertTrue(release_old_save.wait(2))
            else:
                new_save_entered.set()
            saved_generations.append(working.label)

        with patch.object(
            ui.management.ArchitectureManagementState, "from_dict",
            side_effect=clone,
        ), patch.object(
            ui.management, "save_profile_management_state", side_effect=save,
        ):
            old_worker = threading.Thread(
                target=workspace._source_change_worker,
                args=(41, (("dodaf", original("old")),), frozenset(), False, ("OLD",)),
            )
            old_worker.start()
            self.assertTrue(old_save_started.wait(2))

            workspace._source_change_token = 42
            new_worker = threading.Thread(
                target=workspace._source_change_worker,
                args=(42, (("dodaf", original("new")),), frozenset(), False, ("NEW",)),
            )
            new_worker.start()
            try:
                self.assertTrue(new_worker_prepared.wait(2))
                self.assertFalse(new_save_entered.wait(0.1))
            finally:
                release_old_save.set()
            old_worker.join(2)
            new_worker.join(2)

        self.assertFalse(old_worker.is_alive())
        self.assertFalse(new_worker.is_alive())
        self.assertEqual(saved_generations, ["old", "new"])

    def test_source_change_worker_clones_stales_saves_and_queues_without_tk_call(self):
        workspace = self._workspace()
        workspace._source_change_token = 31
        workspace.window = _PollingWindow()
        workspace._ui_queue = queue.Queue()
        workspace._poll_after_id = None
        workspace._finish_source_change = Mock()
        original_record = SimpleNamespace(status=ui.management.STATUS_APPROVED)
        original = SimpleNamespace(
            records={"REC-1": original_record},
            to_dict=Mock(return_value={"records": {"REC-1": {}}}),
        )
        automatic = SimpleNamespace(source_requirement_ids=("SGD-002",))
        working_record = SimpleNamespace(
            status=ui.management.STATUS_APPROVED,
            record_id="REC-1",
            automatic_proposal=automatic,
        )
        working = SimpleNamespace(records={"REC-1": working_record}, known_requirement_ids=())

        with patch.object(
            ui.management.ArchitectureManagementState, "from_dict", return_value=working,
        ) as clone_state, patch.object(
            ui.management, "mark_candidate_stale",
        ) as mark_stale, patch.object(
            ui.management, "save_profile_management_state",
        ) as save_state:
            workspace._source_change_worker(
                31, (("dodaf", original),), frozenset({"SGD-002"}), False,
                ("TID-001", "SGD-002"),
            )

        self.assertEqual(original_record.status, ui.management.STATUS_APPROVED)
        original.to_dict.assert_called_once_with()
        clone_state.assert_called_once_with({"records": {"REC-1": {}}})
        mark_stale.assert_called_once()
        self.assertIs(mark_stale.call_args.args[0], working)
        self.assertEqual(mark_stale.call_args.args[1:3], ("REC-1", ("SGD-002",)))
        save_state.assert_called_once_with(working)
        self.assertEqual(working.known_requirement_ids, ("TID-001", "SGD-002"))
        self.assertEqual(workspace.window.after_calls, [])
        self.assertEqual(workspace._ui_queue.qsize(), 1)
        workspace._finish_source_change.assert_not_called()

        workspace._poll_ui_queue()

        workspace._finish_source_change.assert_called_once_with(
            31, {"dodaf": working}, None,
        )
        self.assertEqual(workspace.window.after_calls[0][0], 40)

    def test_source_save_failure_keeps_revision_blocked_and_never_restores_old_outputs(self):
        workspace = self._workspace()
        workspace.window = _PollingWindow()
        workspace._ui_queue = queue.Queue()
        workspace._poll_after_id = None
        workspace.refresh = Mock()
        working = SimpleNamespace(records={}, known_requirement_ids=())

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace.on_sources_changed(("SGD-002",))
        worker_kwargs = thread_class.call_args.kwargs

        with patch.object(
            ui.management.ArchitectureManagementState, "from_dict", return_value=working,
        ), patch.object(
            ui.management, "save_profile_management_state",
            side_effect=OSError("disk full"),
        ):
            worker_kwargs["target"](*worker_kwargs["args"])

        self.assertEqual(workspace.window.after_calls, [])
        self.assertEqual(workspace._ui_queue.qsize(), 1)
        workspace._poll_ui_queue()

        self.assertTrue(workspace._source_revision_blocked)
        self.assertIsNone(workspace.current_snapshot)
        self.assertIsNone(workspace.current_render_result)
        self.assertIsNone(workspace.current_validation_report)
        self.assertEqual(workspace._render_results, {})
        self.assertEqual(workspace._validation_reports, {})
        self.assertIn("disk full", workspace.status_var.get())
        workspace.refresh.assert_called_once_with()

    def test_generation_lock_survives_intermediate_source_save_until_traceability_ready(self):
        workspace = self._workspace()
        workspace._source_generation_in_progress = False
        workspace._traceability_revision_blocked = False
        workspace.refresh = Mock()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace.on_generation_started()
            first_token = workspace._source_change_token
            workspace._finish_source_change(first_token, {}, None)

            self.assertTrue(workspace._source_generation_in_progress)
            self.assertTrue(workspace._traceability_revision_blocked)
            self.assertTrue(workspace._source_revision_blocked)

            workspace.on_traceability_ready()
            final_token = workspace._source_change_token
            workspace._finish_source_change(final_token, {}, None)

        self.assertEqual(thread_class.call_count, 2)
        self.assertFalse(workspace._source_generation_in_progress)
        self.assertFalse(workspace._traceability_revision_blocked)
        self.assertFalse(workspace._source_revision_blocked)

    def test_generation_start_after_project_switch_keeps_new_project_locked(self):
        workspace = self._workspace()
        workspace._active_project_name = "Project A"
        workspace.project_name_getter = lambda: "Project B"
        workspace._pending_source_changed_ids = set()
        workspace._pending_source_mark_all = False
        workspace.refresh = Mock()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace.on_generation_started()

        self.assertEqual(workspace._active_project_name, "Project B")
        self.assertTrue(workspace._source_generation_in_progress)
        self.assertTrue(workspace._traceability_revision_blocked)
        self.assertTrue(workspace._source_revision_blocked)
        self.assertEqual(thread_class.call_args.kwargs["args"][1], ())

    def test_project_context_refresh_preserves_running_generation_gate(self):
        workspace = self._workspace()
        workspace._active_project_name = "Project A"
        workspace.project_name_getter = lambda: "Project B"
        workspace._source_generation_in_progress = True
        workspace._source_mutation_in_progress = False
        workspace._traceability_revision_blocked = True
        workspace._pending_source_changed_ids = set()
        workspace._pending_source_mark_all = False
        workspace._pending_source_profiles = set()
        workspace.refresh = Mock()

        self.assertFalse(workspace._ensure_current_project_context())

        self.assertEqual(workspace._active_project_name, "Project B")
        self.assertTrue(workspace._source_generation_in_progress)
        self.assertTrue(workspace._traceability_revision_blocked)
        self.assertTrue(workspace._source_revision_blocked)
        self.assertFalse(workspace._ensure_extraction_ready())

    def test_pre_mutation_hook_invalidates_every_stale_job_without_tk_calls(self):
        workspace = self._workspace()
        workspace._source_mutation_in_progress = False
        workspace._extraction_token = 1
        workspace._render_token = 2
        workspace._validation_token = 3
        workspace._source_change_token = 4
        workspace._publish_token = 5
        workspace._state_revision = 6
        workspace._extraction_context = {1: ("dodaf", "Proje", ())}
        workspace._publish_cancel_event = threading.Event()

        worker = threading.Thread(target=workspace.on_source_mutation_started)
        worker.start()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(workspace._publish_cancel_event.is_set())
        self.assertTrue(workspace._source_revision_blocked)
        self.assertTrue(workspace._source_mutation_in_progress)
        self.assertEqual(
            (
                workspace._extraction_token, workspace._render_token,
                workspace._validation_token, workspace._source_change_token,
                workspace._publish_token, workspace._state_revision,
            ),
            (2, 3, 4, 5, 6, 7),
        )
        self.assertEqual(workspace._extraction_context, {})
        self.assertFalse(workspace._ensure_extraction_ready())

    def test_traceability_failure_keeps_source_gate_closed(self):
        workspace = self._workspace()
        workspace._source_generation_in_progress = True
        workspace._traceability_revision_blocked = True

        workspace.on_generation_failed("map failed")

        self.assertFalse(workspace._source_generation_in_progress)
        self.assertTrue(workspace._traceability_revision_blocked)
        self.assertTrue(workspace._source_revision_blocked)
        self.assertFalse(workspace._ensure_sources_ready())
        self.assertIn("henüz birlikte hazır değil", workspace.status_var.get())


class ExplicitReviewSmokeTests(unittest.TestCase):
    @staticmethod
    def _review_workspace():
        workspace = _headless_workspace()
        record = SimpleNamespace(
            record_id="ARCH-REVIEW-001",
            proposal=SimpleNamespace(
                proposed_payload={"description": "original description"},
            ),
        )
        state = SimpleNamespace(
            framework_profile_id="dodaf",
            records={record.record_id: record},
        )
        workspace.management_state = state
        workspace._states_by_profile = {"dodaf": state}
        workspace._selected_record = Mock(return_value=record)
        workspace._review_transaction = Mock()
        workspace._source_revision_blocked = False
        workspace._source_generation_in_progress = False
        workspace._traceability_revision_blocked = False
        workspace._refresh_candidate_tree = Mock()
        workspace._refresh_view_cards = Mock()
        workspace._invalidate_architecture_outputs = Mock()
        workspace.status_var = _FakeVariable()
        workspace.window = object()
        return workspace, record, state

    def test_extraction_completion_creates_candidates_without_automatic_approval(self):
        workspace = _headless_workspace()
        workspace._extraction_token = 6
        workspace._extraction_context = {
            6: ("dodaf", "Kanıtlı Proje", ("TID-001",)),
        }
        workspace._active_project_name = "Kanıtlı Proje"
        workspace._busy = Mock()
        workspace.extraction_result = None
        workspace.project_name_getter = lambda: "Kanıtlı Proje"
        workspace._states_by_profile = {}
        workspace._state_persistence_blocked = {}
        workspace.management_state = None
        workspace._refresh_candidate_tree = Mock()
        workspace._refresh_view_cards = Mock()
        workspace._select_step = Mock()
        workspace._invalidate_architecture_outputs = Mock()
        workspace._reset_project_context = Mock()
        workspace.status_var = _FakeVariable()
        candidate = object()
        result = SimpleNamespace(
            framework_profile_id="dodaf",
            candidates=(candidate,),
            information_gaps=(),
            processed_requirement_ids=("TID-001",),
        )
        state = SimpleNamespace(framework_profile_id="dodaf")

        with patch.object(
            ui.management, "load_profile_management_state", return_value=None,
        ), patch.object(
            ui.management, "create_management_state", return_value=state,
        ) as create_state, patch.object(
            ui.management, "save_profile_management_state",
        ) as save_state, patch.object(
            ui.management, "approve_candidate",
        ) as approve:
            prepared_state = workspace._prepare_extraction_state(6, result)
            workspace._finish_extraction(6, result, None, prepared_state)

        create_state.assert_called_once_with(
            "Kanıtlı Proje", (candidate,), framework_profile_id="dodaf",
            known_requirement_ids=("TID-001",),
            source_requirement_fingerprints={},
        )
        save_state.assert_called_once_with(state)
        approve.assert_not_called()
        self.assertIs(workspace.management_state, state)
        workspace._select_step.assert_called_once_with("review")

    @staticmethod
    def _approval_workspace(records):
        workspace = _headless_workspace()
        state = SimpleNamespace(framework_profile_id="dodaf", records=records)
        workspace.management_state = state
        workspace._review_transaction = Mock(
            side_effect=lambda mutation, **_kwargs: mutation(state)
        )
        workspace._capture_review_guard = Mock(return_value=("guard",))
        workspace._refresh_candidate_tree = Mock()
        workspace._refresh_view_cards = Mock()
        workspace._invalidate_architecture_outputs = Mock()
        workspace.status_var = _FakeVariable()
        workspace.window = object()
        return workspace, state

    @staticmethod
    def _element_record(record_id, name="Öğe"):
        return SimpleNamespace(
            record_id=record_id,
            status=ui.management.STATUS_CANDIDATE,
            proposal=SimpleNamespace(
                proposal_type="element", title=name, target_stable_id=f"EL-{record_id}",
                framework_profile_id="dodaf",
                proposed_payload={"element_type": "System", "identity_key": record_id},
            ),
        )

    def test_only_explicit_approve_action_calls_management_approval(self):
        record = self._element_record("ARCH-REVIEW-001")
        workspace, state = self._approval_workspace({"ARCH-REVIEW-001": record})
        workspace._selected_records = Mock(return_value=(record,))

        with patch.object(ui.management, "approve_candidate") as approve:
            workspace._approve_selected()

        approve.assert_called_once()
        args, kwargs = approve.call_args
        self.assertEqual(args, (state, "ARCH-REVIEW-001", "UI Kullanıcısı"))
        self.assertIn("açık kullanıcı onayı", kwargs["rationale"])
        workspace._review_transaction.assert_called_once()
        self.assertIn(
            "expected_guard", workspace._review_transaction.call_args.kwargs,
        )
        self.assertIn("1 aday onaylandı", workspace.status_var.get())

    def test_batch_approval_applies_every_selected_record_once(self):
        records = {
            f"ARCH-REVIEW-{index:03d}": self._element_record(f"ARCH-REVIEW-{index:03d}")
            for index in range(1, 4)
        }
        workspace, _state = self._approval_workspace(records)
        workspace._selected_records = Mock(return_value=tuple(records.values()))

        with patch.object(ui.management, "approve_candidate") as approve:
            workspace._approve_selected()

        self.assertEqual(approve.call_count, 3)
        self.assertEqual(
            sorted(call.args[1] for call in approve.call_args_list),
            sorted(records),
        )

    def test_stale_records_are_never_approved_by_batch_action(self):
        fresh = self._element_record("ARCH-REVIEW-001")
        stale = self._element_record("ARCH-REVIEW-002")
        stale.status = ui.management.STATUS_STALE
        workspace, _state = self._approval_workspace(
            {"ARCH-REVIEW-001": fresh, "ARCH-REVIEW-002": stale}
        )
        workspace._selected_records = Mock(return_value=(fresh, stale))

        with patch.object(ui.management, "approve_candidate") as approve:
            workspace._approve_selected()

        approve.assert_called_once()
        self.assertEqual(approve.call_args.args[1], "ARCH-REVIEW-001")
        self.assertIn("1 stale kayıt atlandı", workspace.status_var.get())

    def test_relationship_approval_pulls_in_its_unapproved_endpoints(self):
        source = self._element_record("ARCH-REVIEW-SRC", "Kaynak Sistemi")
        target = self._element_record("ARCH-REVIEW-TGT", "Hedef Sistemi")
        relationship = SimpleNamespace(
            record_id="ARCH-REVIEW-REL",
            status=ui.management.STATUS_CANDIDATE,
            proposal=SimpleNamespace(
                proposal_type="relationship", title="akış", target_stable_id="REL-1",
                framework_profile_id="dodaf",
                source_element_id="EL-ARCH-REVIEW-SRC",
                target_element_id="EL-ARCH-REVIEW-TGT",
                proposed_payload={"relationship_type": "flow_source", "identity_key": "rel"},
            ),
        )
        workspace, _state = self._approval_workspace({
            "ARCH-REVIEW-SRC": source, "ARCH-REVIEW-TGT": target,
            "ARCH-REVIEW-REL": relationship,
        })
        workspace._selected_records = Mock(return_value=(relationship,))

        with patch.object(ui.messagebox, "askyesno", return_value=True) as confirm, \
                patch.object(ui.management, "approve_candidate") as approve:
            workspace._approve_selected()

        confirm.assert_called_once()
        approved = [call.args[1] for call in approve.call_args_list]
        self.assertEqual(len(approved), 3)
        # Uçlar ilişkiden önce onaylanmalı; aksi hâlde ara durumda boşta uç kalır.
        self.assertLess(approved.index("ARCH-REVIEW-SRC"), approved.index("ARCH-REVIEW-REL"))
        self.assertLess(approved.index("ARCH-REVIEW-TGT"), approved.index("ARCH-REVIEW-REL"))

    def test_endpoint_completion_is_abandoned_when_user_declines(self):
        source = self._element_record("ARCH-REVIEW-SRC")
        relationship = SimpleNamespace(
            record_id="ARCH-REVIEW-REL",
            status=ui.management.STATUS_CANDIDATE,
            proposal=SimpleNamespace(
                proposal_type="relationship", title="akış", target_stable_id="REL-1",
                framework_profile_id="dodaf",
                source_element_id="EL-ARCH-REVIEW-SRC", target_element_id="",
                proposed_payload={"relationship_type": "flow_source", "identity_key": "rel"},
            ),
        )
        workspace, _state = self._approval_workspace({
            "ARCH-REVIEW-SRC": source, "ARCH-REVIEW-REL": relationship,
        })
        workspace._selected_records = Mock(return_value=(relationship,))

        with patch.object(ui.messagebox, "askyesno", return_value=False), \
                patch.object(ui.management, "approve_candidate") as approve:
            workspace._approve_selected()

        approve.assert_not_called()
        workspace._review_transaction.assert_not_called()

    def test_reject_dialog_result_is_discarded_after_source_generation_changes(self):
        workspace, _record, _state = self._review_workspace()

        def revise_sources(*_args, **_kwargs):
            workspace._source_change_token += 1
            workspace._state_revision += 1
            workspace._source_revision_blocked = True
            return "obsolete rationale"

        with patch.object(ui.simpledialog, "askstring", side_effect=revise_sources):
            workspace._reject_selected()

        workspace._review_transaction.assert_not_called()
        self.assertIn("uygulanmadı", workspace.status_var.get())

    def test_edit_dialog_result_is_discarded_after_review_state_is_replaced(self):
        workspace, _record, state = self._review_workspace()

        def replace_state(*_args, **_kwargs):
            workspace.management_state = SimpleNamespace(
                framework_profile_id="dodaf", records={},
            )
            workspace._state_revision += 1
            return "obsolete edit"

        with patch.object(ui.simpledialog, "askstring", side_effect=replace_state):
            workspace._edit_selected()

        workspace._review_transaction.assert_not_called()
        self.assertIsNot(workspace.management_state, state)
        self.assertIn("uygulanmadı", workspace.status_var.get())

    def test_conflict_dialog_result_is_discarded_after_source_generation_changes(self):
        workspace, record, _state = self._review_workspace()
        conflict = SimpleNamespace(
            record_id=record.record_id,
            conflict_id="CONFLICT-001",
            field_name="description",
        )
        workspace._selected_unresolved_conflicts = Mock(return_value=(conflict,))

        def revise_sources(*_args, **_kwargs):
            workspace._source_change_token += 1
            workspace._state_revision += 1
            workspace._source_revision_blocked = True
            return True

        with patch.object(
            ui.messagebox, "askyesnocancel", side_effect=revise_sources,
        ):
            workspace._resolve_selected_conflict()

        workspace._review_transaction.assert_not_called()
        self.assertIn("uygulanmadı", workspace.status_var.get())

    def test_review_transaction_cas_refuses_save_when_generation_changes_during_mutation(self):
        workspace, record, live_state = self._review_workspace()
        live_state.to_dict = Mock(return_value={"records": {record.record_id: {}}})
        workspace._review_transaction = (
            ui.ArchitectureFrameworkWorkspace._review_transaction.__get__(workspace)
        )
        working = SimpleNamespace(
            framework_profile_id="dodaf",
            records={record.record_id: record},
        )
        guard = workspace._capture_review_guard(record.record_id)

        def mutation(candidate_state):
            candidate_state.changed = True
            workspace._source_change_token += 1
            workspace._state_revision += 1

        with patch.object(
            ui.management.ArchitectureManagementState, "from_dict",
            return_value=working,
        ), patch.object(
            ui.management, "save_profile_management_state",
        ) as save_state:
            with self.assertRaises(ui.management.ArchitectureManagementError):
                workspace._review_transaction(mutation, expected_guard=guard)

        save_state.assert_not_called()
        self.assertIs(workspace.management_state, live_state)
        self.assertFalse(hasattr(live_state, "changed"))
        self.assertIn("uygulanmadı", workspace.status_var.get())


class ValidationFindingPresentationTests(unittest.TestCase):
    def test_profile_and_view_targets_are_visible_in_validation_rows(self):
        workspace = _headless_workspace()
        workspace.validation_tree = _FakeTree()
        profile_finding = SimpleNamespace(
            severity="warning",
            message="PES aktarımı uygulanmadı.",
            target_id="dodaf",
            view_id="",
        )
        view_finding = SimpleNamespace(
            severity="error",
            message="Zorunlu sistem akışı eksik.",
            target_id="",
            view_id="SV-1",
        )
        workspace.current_validation_report = SimpleNamespace(
            framework_profile_id="dodaf",
            view_generatability=SimpleNamespace(findings=(view_finding,)),
            model_integrity=SimpleNamespace(findings=()),
            framework_conformance=SimpleNamespace(findings=(profile_finding,)),
        )
        workspace.extraction_result = None

        workspace._populate_validation_findings()

        rendered_rows = [
            " | ".join(str(value) for value in row["values"])
            for row in workspace.validation_tree.rows
        ]
        self.assertTrue(any("dodaf" in row.casefold() for row in rendered_rows))
        self.assertTrue(any("SV-1" in row for row in rendered_rows))
        self.assertTrue(any("PES aktarımı" in row for row in rendered_rows))
        self.assertTrue(any("Zorunlu sistem akışı" in row for row in rendered_rows))


class PublicationGateSmokeTests(unittest.TestCase):
    @staticmethod
    def _report(*, integrity=True, generatable=True):
        return SimpleNamespace(
            snapshot_id="SNAP-001",
            view_generatability=SimpleNamespace(
                passed=generatable,
                findings=(),
                view_results=(SimpleNamespace(
                    view_id="SV-1", generatable=generatable, findings=(),
                ),),
            ),
            model_integrity=SimpleNamespace(
                passed=integrity, findings=(),
            ),
            framework_conformance=SimpleNamespace(passed=True, findings=()),
        )

    @staticmethod
    def _rendered_result():
        return SimpleNamespace(
            status=ui.rendering.RENDER_STATUS_RENDERED,
            view_id="SV-1",
            snapshot_id="SNAP-001",
            svg="<svg/>",
        )

    def _workspace(self):
        workspace = _headless_workspace()
        workspace._working = False
        workspace.management_state = SimpleNamespace(framework_profile_id="dodaf")
        workspace.profile_var = _FakeVariable("dodaf")
        workspace.view_var = _FakeVariable("SV-1")
        workspace.current_snapshot = SimpleNamespace(
            snapshot_id="SNAP-001",
            framework_profile_id="dodaf",
            selected_view_ids=("SV-1",),
        )
        workspace.current_validation_report = self._report()
        workspace.current_render_result = self._rendered_result()
        workspace._validation_reports = {
            ("dodaf", "SV-1"): workspace.current_validation_report,
        }
        workspace._render_results = {
            ("dodaf", "SV-1"): workspace.current_render_result,
        }
        workspace._publish_token = 0
        workspace._busy = Mock()
        workspace.status_var = _FakeVariable()
        return workspace

    def test_publish_does_not_start_until_all_current_validation_and_render_gates_pass(self):
        cases = (
            ("validation missing", None, self._rendered_result()),
            ("integrity failed", self._report(integrity=False), self._rendered_result()),
            ("selected view not generatable", self._report(generatable=False), self._rendered_result()),
            ("render missing", self._report(), None),
        )
        for label, report, render_result in cases:
            with self.subTest(gate=label):
                workspace = self._workspace()
                workspace.current_validation_report = report
                workspace.current_render_result = render_result
                workspace._validation_reports[("dodaf", "SV-1")] = report
                workspace._render_results[("dodaf", "SV-1")] = render_result
                with patch.object(ui.threading, "Thread") as thread_class:
                    workspace._start_publish()
                thread_class.assert_not_called()
                workspace._busy.assert_not_called()
                self.assertTrue(workspace.status_var.get())

    def test_publish_starts_daemon_worker_when_current_view_is_ready(self):
        workspace = self._workspace()

        with patch.object(ui.threading, "Thread") as thread_class:
            workspace._start_publish()

        thread_class.assert_called_once()
        self.assertTrue(thread_class.call_args.kwargs["daemon"])
        self.assertEqual(thread_class.call_args.kwargs["name"], "architecture-version-publish")
        thread_class.return_value.start.assert_called_once_with()
        workspace._busy.assert_called_once()

    def test_publish_thread_start_error_cancels_context_clears_busy_and_reports_status(self):
        workspace = self._workspace()
        workspace._working = False

        def remember_busy(value, _message=""):
            workspace._working = bool(value)

        workspace._busy = Mock(side_effect=remember_busy)

        with patch.object(ui.threading, "Thread") as thread_class:
            thread_class.return_value.start.side_effect = RuntimeError("publisher unavailable")
            workspace._start_publish()

        self.assertFalse(workspace._working)
        self.assertTrue(workspace._publish_cancel_event.is_set())
        self.assertEqual(workspace._publish_token, 2)
        self.assertIn("publisher unavailable", workspace.status_var.get())
        self.assertEqual(workspace._busy.call_args_list[-1].args, (False,))


class MainScreenArchitectureIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import Arayüz

        cls.main_ui = Arayüz

    def test_main_screen_registers_bilingual_architecture_button(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        app._reg_btn = MagicMock()
        app._t = lambda tr, en: tr
        created_buttons = []

        def frame_factory(*_args, **_kwargs):
            return _FakeWidget()

        def button_factory(parent, **kwargs):
            button = _FakeWidget()
            created_buttons.append((button, parent, kwargs))
            return button

        with patch.object(self.main_ui.ttk, "Frame", side_effect=frame_factory), patch.object(
            self.main_ui.ttk, "Button", side_effect=button_factory,
        ):
            app._create_buttons(object())

        architecture = next(
            item for item in created_buttons
            if getattr(item[2].get("command"), "__func__", None)
            is self.main_ui.TIDGeneratorApp.open_architecture_framework_workspace
        )
        self.assertIs(app.architecture_button, architecture[0])
        app._reg_btn.assert_any_call(
            app.architecture_button, "Mimari Çerçeve", "Architecture Framework",
        )
        self.assertEqual(app.architecture_button.options["text"], "Mimari Çerçeve")

    def test_open_workspace_reuses_existing_single_instance(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        existing = SimpleNamespace(exists=True, refresh=Mock(), focus=Mock())
        app.mimari_cerceve_workspace = existing

        with patch.object(
            self.main_ui.mimari_cerceve_ui, "ArchitectureFrameworkWorkspace",
        ) as constructor:
            app.open_architecture_framework_workspace()

        constructor.assert_not_called()
        existing.refresh.assert_called_once_with()
        existing.focus.assert_called_once_with()

    def test_new_workspace_receives_live_project_source_and_ui_getters(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        app.mimari_cerceve_workspace = None
        app.master = object()
        app.style = object()
        app.flat_data = {"TID-001": {"type": "TID"}}
        app.lang = "tr"
        project_name = _FakeVariable("Mimari Proje")
        app.entry_widgets = {"proje_ismi": project_name}
        traceability = {"nodes": [], "edges": []}
        app._get_current_traceability_report = Mock(return_value=traceability)
        palette = {"bg": "#F5F6F7"}
        app._hardware_palette = Mock(return_value=palette)
        app._t = lambda tr, en: tr
        created = object()

        with patch.object(
            self.main_ui.mimari_cerceve_ui, "ArchitectureFrameworkWorkspace",
            return_value=created,
        ) as constructor:
            app.open_architecture_framework_workspace()

        self.assertIs(app.mimari_cerceve_workspace, created)
        kwargs = constructor.call_args.kwargs
        self.assertIs(kwargs["master"], app.master)
        self.assertIs(kwargs["style"], app.style)
        self.assertIs(kwargs["flat_data_getter"](), app.flat_data)
        self.assertIs(kwargs["traceability_getter"](), traceability)
        self.assertEqual(kwargs["project_name_getter"](), "Mimari Proje")
        self.assertEqual(kwargs["language_getter"](), "tr")
        self.assertEqual(kwargs["palette_getter"](), palette)
        self.assertIs(kwargs["on_close"].__self__, app)
        self.assertIs(kwargs["language_toggle_callback"].__self__, app)
        self.assertIs(kwargs["theme_toggle_callback"].__self__, app)

        replacement = {"SGD-002": {"type": "SGD"}}
        app.flat_data = replacement
        app.lang = "en"
        project_name.set("Updated Project")
        self.assertIs(kwargs["flat_data_getter"](), replacement)
        self.assertEqual(kwargs["language_getter"](), "en")
        self.assertEqual(kwargs["project_name_getter"](), "Updated Project")

    def test_main_language_and_theme_changes_propagate_to_open_workspace(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        architecture = SimpleNamespace(
            exists=True, refresh_language=Mock(), apply_theme=Mock(),
        )
        app.mimari_cerceve_workspace = architecture
        app.hardware_workspace = None
        app.hardware_cards_workspace = None
        app.impact_analysis_workspace = None
        app.lang = "tr"
        app._i18n = []
        app._chat_has_convo = True

        app._toggle_lang()

        self.assertEqual(app.lang, "en")
        architecture.refresh_language.assert_called_once_with()

        app.dark = True
        app.style = MagicMock()
        app.master = MagicMock()
        app._theme_labels = []
        app._theme_texts = []

        app._apply_theme()

        architecture.apply_theme.assert_called_once_with()

    def test_source_change_notifier_normalizes_ids_and_preserves_none_scope(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        architecture = SimpleNamespace(exists=True, on_sources_changed=Mock())
        app.mimari_cerceve_workspace = architecture
        app.update_status_text = Mock()

        app._notify_architecture_sources_changed(
            (" sgd-002 ", "SGD-001", "sgd-002", "", " tid-003 "),
        )
        app._notify_architecture_sources_changed(None)

        self.assertEqual(
            architecture.on_sources_changed.call_args_list[0].args,
            (("SGD-001", "SGD-002", "TID-003"),),
        )
        self.assertEqual(
            architecture.on_sources_changed.call_args_list[1].args,
            (None,),
        )
        app.update_status_text.assert_not_called()

    def test_traceability_report_update_notifies_architecture_source_change_hook(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        old_report = {"project_name": "Old Project", "nodes": []}
        app.last_traceability_report = old_report
        app.last_traceability_health = {
            "rag_status": "updated", "rag_message": "RAG ready",
        }
        mutation_order = []
        app._notify_architecture_source_mutation_started = Mock(
            side_effect=lambda: mutation_order.append(
                ("cancel", app.last_traceability_report)
            )
        )
        app._notify_architecture_traceability_ready = Mock()
        report = {"nodes": [{"id": "SGD-001"}], "edges": []}
        health = {"ready": True, "rag_status": "updated"}

        with patch.object(
            self.main_ui.etki_analizi_entegrasyon,
            "build_health_summary",
            return_value=health,
        ) as health_builder:
            app._set_current_traceability_report(report)

        self.assertEqual(app.last_traceability_report, report)
        self.assertIsNot(app.last_traceability_report, report)
        self.assertIs(app.last_traceability_health, health)
        self.assertEqual(mutation_order, [("cancel", old_report)])
        health_builder.assert_called_once()
        app._notify_architecture_traceability_ready.assert_called_once_with()

    def test_requirement_revision_cancels_architecture_jobs_before_flat_mutation(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        order = []

        class RecordingRecord(dict):
            def __setitem__(self, key, value):
                order.append(("mutate", key, value))
                super().__setitem__(key, value)

        architecture = SimpleNamespace(
            on_source_mutation_started=Mock(
                side_effect=lambda: order.append(("cancel",)),
            )
        )
        app.mimari_cerceve_workspace = architecture
        app.flat_data = {
            "TID-001": RecordingRecord(
                type="TID", ID="TID-001", content="Eski metin",
            ),
        }
        app._sync_item_text = Mock()
        app.update_status_text = Mock()

        app._apply_revision("TID-001", "Eski metin", "Yeni metin")

        self.assertEqual(order[0], ("cancel",))
        self.assertEqual(order[1], ("mutate", "content", "Yeni metin"))
        architecture.on_source_mutation_started.assert_called_once_with()

    def test_architecture_generation_hooks_keep_workspace_locked_until_traceability_ready(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        architecture = SimpleNamespace(
            exists=True,
            on_generation_started=Mock(),
            on_traceability_ready=Mock(),
            on_generation_failed=Mock(),
        )
        app.mimari_cerceve_workspace = architecture

        app._notify_architecture_generation_started()
        self.assertEqual(app._architecture_generation_state, "running")
        architecture.on_generation_started.assert_called_once_with()

        app._notify_architecture_traceability_ready((" sgd-002 ", "SGD-002"))
        self.assertEqual(app._architecture_generation_state, "ready")
        architecture.on_traceability_ready.assert_called_once_with(("SGD-002",))

        app._notify_architecture_generation_failed("trace failed")
        self.assertEqual(app._architecture_generation_state, "failed")
        self.assertEqual(app._architecture_generation_detail, "trace failed")
        architecture.on_generation_failed.assert_called_once_with("trace failed")

    def test_split_notification_includes_requirement_ids_changed_by_ripple(self):
        app = object.__new__(self.main_ui.TIDGeneratorApp)
        app.flat_data = {
            "TID-001": {
                "type": "TID", "ID": "TID-001", "content": "Bir ve iki",
                "bound_to": "Yok",
            },
            "SGD-009": {
                "type": "SGD", "ID": "SGD-009", "content": "Alt ister",
                "bound_to": "TID-001",
            },
            "AT-001": {
                "type": "KMTD", "ID": "AT-001", "content": "Test",
                "bound_to": "TID-001",
            },
        }
        app.last_generated_output = ""
        app._chat_append = Mock()
        app._apply_revision = Mock()
        app._ripple_regenerate = Mock(return_value=("SGD-009", "AT-001"))
        app.update_status_text = Mock()
        app._notify_architecture_sources_changed = Mock()
        app.master = SimpleNamespace(after=lambda _delay, callback: callback())

        with patch("llm_handler.call_gemma3_api", return_value=(
            "Sistem birinci işlevi sağlamalıdır.\n"
            "Sistem ikinci işlevi sağlamalıdır."
        )), patch.object(
            self.main_ui.text_cleanup, "temizle", side_effect=lambda value, **_kw: value,
        ), patch.object(
            self.main_ui.kmtd_generator_logic, "generate_kmtd_from_tid", return_value="",
        ):
            app._split_requirement("TID-001")

        notified_ids = app._notify_architecture_sources_changed.call_args.args[0]
        self.assertIn("TID-001", notified_ids)
        self.assertIn("TID-001b", notified_ids)
        self.assertIn("SGD-009", notified_ids)
        self.assertNotIn("AT-001", notified_ids)


if __name__ == "__main__":
    unittest.main()
