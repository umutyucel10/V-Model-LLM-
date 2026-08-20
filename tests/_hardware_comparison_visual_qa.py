# -*- coding: utf-8 -*-
"""Gerçek Tk karşılaştırma ekranı için görsel QA aracı."""

from pathlib import Path
import sys
import tkinter as tk

from ttkbootstrap.style import Style

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import donanim_kartlari_karsilastirma_ui as comparison_ui
import donanim_kartlari_yonetim as management


def main() -> None:
    root = tk.Tk(); root.geometry("1x1+0+0"); Style(theme="litera")
    palette = {
        "bg": "#F5F6F7", "surface": "#FFFFFF", "fg": "#222222",
        "muted": "#5C666D", "entry_bg": "#FFFFFF",
        "entry_fg": "#222222", "accent": "#0052cc",
    }
    catalog = management.sample_catalog()
    traceability = {"nodes": [{
        "id": "DEMO-REQ-PWR-001", "title": "28 V ana besleme gereksinimi",
        "mandatory": True, "source_document": "Sistem Gereksinimleri",
        "confidence_level": "Kesin",
    }]}
    window = comparison_ui.HardwareComparisonWorkspace(
        root, catalog, ["SAMPLE-DCDC", "SAMPLE-DCDC-B", "SAMPLE-DCDC-C"],
        traceability, lambda: palette,
    )
    window.window.geometry("1280x760")
    window.window.deiconify(); window.window.lift()
    root.update_idletasks(); root.update(); window.window.update_idletasks(); window.window.update()
    root_x, root_y = window.window.winfo_rootx(), window.window.winfo_rooty()
    width, height = window.window.winfo_width(), window.window.winfo_height()
    from PIL import ImageGrab
    target = Path("/private/tmp/ehsim_hardware_comparison.png")
    ImageGrab.grab(bbox=(root_x, root_y, root_x + width, root_y + height)).save(target)
    print(
        f"COMPARISON_QA window={width}x{height} rows={len(window.tree.get_children())} "
        f"violations={len(window.result['mandatory_violations'])} screenshot={target}",
        flush=True,
    )
    window.close(); root.destroy()


if __name__ == "__main__":
    main()
