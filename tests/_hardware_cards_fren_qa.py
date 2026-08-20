# -*- coding: utf-8 -*-
"""Gerçek fren kataloğunda donmayan gereksinim seçimi ve görsel QA."""

import json
from pathlib import Path
import sys
import time

from PIL import ImageGrab
import ttkbootstrap as ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import donanim_kartlari_ui


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "outputs/traceability/fren-3ac30dd0/donanim_katalogu.json"
TRACE_PATH = ROOT / "outputs/traceability/fren-3ac30dd0/traceability.json"
SCREENSHOT_PATH = ROOT / "outputs/ehsim_hardware_cards_fren_fixed.png"


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    report = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    root = ttk.Window(themename="litera")
    root.withdraw()
    style = root.style
    palette = {
        "bg": "#F5F6F7", "surface": "#FFFFFF", "fg": "#222222",
        "muted": "#5C666D", "entry_bg": "#FFFFFF",
        "entry_fg": "#222222", "accent": "#0052cc",
    }
    workspace = donanim_kartlari_ui.HardwareCardsWorkspace(
        master=root, style=style, language_getter=lambda: "tr",
        palette_getter=lambda: palette,
        project_name_getter=lambda: "fren",
        catalog_getter=lambda: catalog,
        traceability_getter=lambda: report,
    )
    workspace.window.geometry("1460x850+40+40")
    started = time.perf_counter()

    def verify() -> None:
        if workspace._visual_generation_running:
            if time.perf_counter() - started > 15:
                print("FREN_QA_FAILED visual_timeout", flush=True)
                root.destroy()
                return
            root.after(100, verify)
            return
        try:
            target = next(
                item for item in workspace.catalog["hardware_items"]
                if item.get("requirement_ids")
            )
            hardware_id = target["hardware_id"]
            outer_before = workspace._card_widgets[hardware_id][0]
            click_started = time.perf_counter()
            for _ in range(25):
                workspace._trace_click(hardware_id, "requirements")
                root.update()
            card_ids = [
                item["hardware_id"]
                for item in workspace.catalog["hardware_items"]
            ]
            for card_id in card_ids:
                workspace.select_card(card_id)
                root.update()
            tree_ids: list[str] = []
            def collect_tree(parent: str = "") -> None:
                for tree_id in workspace.product_tree.get_children(parent):
                    if workspace._tree_hardware_id(tree_id):
                        tree_ids.append(tree_id)
                    collect_tree(tree_id)
            collect_tree()
            for tree_id in tree_ids:
                workspace.product_tree.selection_set(tree_id)
                root.update()
            for tab_index in range(len(donanim_kartlari_ui.DETAIL_TABS)):
                workspace.detail_notebook.select(tab_index)
                root.update()
            workspace._trace_click(hardware_id, "requirements")
            root.update()
            elapsed = time.perf_counter() - click_started
            outer_after = workspace._card_widgets[hardware_id][0]
            requirement_rows = len(
                workspace._detail_trees["requirements"].get_children("")
            )
            generated_count = sum(
                bool(item.get("image_is_generated"))
                for item in workspace.catalog["hardware_items"]
            )
            families = sorted({
                (item.get("visual_brief") or {}).get("family", "")
                for item in workspace.catalog["hardware_items"]
                if item.get("image_is_generated")
            })
            assert outer_before is outer_after, "Kart seçimi kataloğu yeniden kurdu."
            assert requirement_rows >= 1, "Gereksinim ayrıntıları gösterilmedi."
            assert generated_count == len(workspace.catalog["hardware_items"])
            assert "brake_pad" in families and "brake_shoe" in families
            assert elapsed < 3.0, f"Tıklama stres testi yavaş: {elapsed:.3f}s"
            workspace.window.update_idletasks()
            x, y = workspace.window.winfo_rootx(), workspace.window.winfo_rooty()
            w, h = workspace.window.winfo_width(), workspace.window.winfo_height()
            SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(SCREENSHOT_PATH)
            print(
                "FREN_QA_OK "
                f"cards={len(workspace.catalog['hardware_items'])} "
                f"generated={generated_count} requirement_rows={requirement_rows} "
                f"event_stress_seconds={elapsed:.4f} tree_items={len(tree_ids)} "
                f"families={','.join(families)}",
                flush=True,
            )
            print(f"SCREENSHOT {SCREENSHOT_PATH}", flush=True)
        except Exception as error:
            print(f"FREN_QA_FAILED {type(error).__name__}: {error}", flush=True)
            raise
        finally:
            def close_all() -> None:
                workspace.close()
                root.quit()
                root.destroy()
            root.after(100, close_all)

    root.after(200, verify)
    root.mainloop()


if __name__ == "__main__":
    main()
