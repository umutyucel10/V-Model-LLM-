# -*- coding: utf-8 -*-
"""Gerçek Donanım Kartları penceresini örnek veriyle açan görsel QA aracı."""

import os
from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace

from ttkbootstrap.style import Style

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import donanim_kartlari_ui
import donanim_kartlari_yonetim


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    style = Style(theme="litera")
    catalog = donanim_kartlari_yonetim.sample_catalog()
    palette = {
        "bg": "#F5F6F7", "surface": "#FFFFFF", "fg": "#222222",
        "muted": "#5C666D", "entry_bg": "#FFFFFF",
        "entry_fg": "#222222", "accent": "#0052cc",
    }
    workspace = donanim_kartlari_ui.HardwareCardsWorkspace(
        master=root, style=style, language_getter=lambda: "tr",
        palette_getter=lambda: palette,
        project_name_getter=lambda: "ÖRNEK — GERÇEK PROJE VERİSİ DEĞİLDİR",
        catalog_getter=lambda: catalog,
        traceability_getter=lambda: {
            "nodes": [{
                "id": "DEMO-REQ-PWR-001", "title": "Dönüştürücü giriş gerilimi",
                "description": "DC/DC dönüştürücü 28 V ana besleme ile çalışmalıdır.",
                "node_type": "Sistem gereksinimi", "v_model_level": "Sistem",
                "source_document": "Örnek gereksinim", "confidence_level": "Kesin",
            }],
            "edges": [{
                "source_id": "DEMO-REQ-PWR-001", "target_id": "DEMO-TEST-PWR-001",
                "relationship": "verified_by",
            }],
        },
    )
    workspace.select_card("SAMPLE-DCDC")
    view = os.environ.get("EHSIM_QA_VIEW", "Kart")
    workspace.view_mode.set(view)
    workspace._view_changed()
    requested_tab = os.environ.get("EHSIM_QA_TAB", "identity")
    if requested_tab == "technical":
        workspace.detail_notebook.select(1)
    size = os.environ.get("EHSIM_QA_SIZE", "1460x850")
    workspace.window.geometry(size)
    workspace.window.update_idletasks()
    width = int(size.split("x", 1)[0])
    workspace._on_resize(SimpleNamespace(widget=workspace.window, width=width))
    workspace.window.update_idletasks()
    print(f"VISUAL_QA_READY {workspace.window.winfo_id()} {size}", flush=True)

    def report_geometry(label: str) -> None:
        workspace.window.update_idletasks()
        root_x, root_y = workspace.window.winfo_rootx(), workspace.window.winfo_rooty()
        root_w, root_h = workspace.window.winfo_width(), workspace.window.winfo_height()
        widgets = {
            "toolbar": workspace.toolbar, "tree": workspace.tree_panel,
            "catalog": workspace.catalog_panel, "detail": workspace.detail_panel,
            "sample_button": workspace.sample_button,
        }
        overflows = []
        for name, widget in widgets.items():
            if not widget.winfo_ismapped():
                continue
            x = widget.winfo_rootx() - root_x
            y = widget.winfo_rooty() - root_y
            width, height = widget.winfo_width(), widget.winfo_height()
            if x < 0 or y < 0 or x + width > root_w + 2 or y + height > root_h + 2:
                overflows.append(name)
        detail_below = bool(
            workspace.detail_panel.winfo_ismapped()
            and workspace.detail_panel.winfo_rooty() > workspace.catalog_panel.winfo_rooty() + 10
        )
        print(
            f"GEOMETRY {label} window={root_w}x{root_h} "
            f"overflows={','.join(overflows) or 'none'} detail_below={detail_below} "
            f"cards={len(workspace._filtered_items())}", flush=True,
        )
        try:
            from PIL import ImageGrab
            target = f"/private/tmp/ehsim_hardware_cards_{label}.png"
            image = ImageGrab.grab(bbox=(root_x, root_y, root_x + root_w, root_y + root_h))
            image.save(target)
            print(f"SCREENSHOT {target}", flush=True)
        except Exception as error:
            print(f"SCREENSHOT_UNAVAILABLE {error}", flush=True)

    label = f"{size.replace('x', '_')}_{view.lower().replace(' ', '_')}"
    if requested_tab != "identity":
        label = f"{label}_{requested_tab}"
    report_geometry(label)
    workspace.close()
    root.destroy()


if __name__ == "__main__":
    main()
