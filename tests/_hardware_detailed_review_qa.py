# -*- coding: utf-8 -*-
"""Donanım Detaylı İnceleme ekranını gerçek Tk penceresinde doğrular."""

import os
from pathlib import Path
import sys
import time
import tkinter as tk

from ttkbootstrap.style import Style

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import donanim_kartlari_ui
import donanim_kartlari_yonetim


def main() -> None:
    root = tk.Tk(); root.withdraw(); style = Style(theme="litera")
    catalog = donanim_kartlari_yonetim.sample_catalog()
    palette = {
        "bg": "#F5F6F7", "surface": "#FFFFFF", "fg": "#222222",
        "muted": "#5C666D", "entry_bg": "#FFFFFF",
        "entry_fg": "#222222", "accent": "#0052cc",
    }
    trace = {
        "nodes": [
            {"id": "DEMO-REQ-PWR-001", "title": "28 V giriş gerilimi", "description": "DC/DC dönüştürücü, nominal 28 V ana besleme ile çalışmalıdır.", "node_type": "Sistem gereksinimi", "v_model_level": "Sistem", "source_document": "Örnek Sistem Gereksinimleri", "confidence_level": "Kesin"},
            {"id": "DEMO-TEST-PWR-001", "title": "Giriş gerilimi doğrulaması", "node_type": "Sistem doğrulama testi", "source_document": "Örnek Test Prosedürü"},
        ],
        "edges": [{"source_id": "DEMO-REQ-PWR-001", "target_id": "DEMO-TEST-PWR-001", "relationship": "verified_by"}],
    }
    workspace = donanim_kartlari_ui.HardwareCardsWorkspace(
        master=root, style=style, language_getter=lambda: "tr",
        palette_getter=lambda: palette,
        project_name_getter=lambda: "ÖRNEK — GERÇEK PROJE VERİSİ DEĞİLDİR",
        catalog_getter=lambda: catalog, traceability_getter=lambda: trace,
    )
    size = os.environ.get("EHSIM_QA_SIZE", "1460x850")
    tab = os.environ.get("EHSIM_QA_TAB", "overview")
    workspace.window.geometry(size); workspace.window.update_idletasks()
    workspace.open_detailed_review("SAMPLE-DCDC", tab)
    workspace.window.update_idletasks(); detail = workspace._detailed_review
    assert detail is not None
    assert detail.hardware_id == "SAMPLE-DCDC"
    assert len(detail._trees["technical"].get_children()) >= 10
    assert len(detail._trees["requirements"].get_children()) == 1
    assert detail._selected_alt_id() == "SAMPLE-DCDC-B"
    detail._move(1); assert detail.hardware_id
    detail.open("SAMPLE-DCDC", tab)
    detail.start_edit(); detail.cancel_edit()
    if detail._gallery:
        detail.select_tab("gallery"); detail._set_zoom(1.1)
        for _index in range(6):
            root.update(); time.sleep(0.04)
        assert detail._gallery_photo is not None
    detail.select_tab(tab)
    workspace.window.attributes("-topmost", True)
    workspace.window.deiconify(); workspace.window.lift(); workspace.window.focus_force()
    workspace.window.update_idletasks()

    root_x, root_y = workspace.window.winfo_rootx(), workspace.window.winfo_rooty()
    root_w, root_h = workspace.window.winfo_width(), workspace.window.winfo_height()
    overflows = []
    for name, widget in (
        ("detail", detail), ("nav", detail.winfo_children()[0]),
        ("hero", detail.winfo_children()[1]), ("tabs", detail.notebook),
        ("trace", detail.trace_bar),
    ):
        x, y = widget.winfo_rootx() - root_x, widget.winfo_rooty() - root_y
        width, height = widget.winfo_width(), widget.winfo_height()
        if x < -2 or y < -2 or x + width > root_w + 2 or y + height > root_h + 2:
            overflows.append(name)
    print(
        f"DETAIL_QA_READY {workspace.window.winfo_id()} {size} tab={tab} "
        f"overflows={','.join(overflows) or 'none'} tech={len(detail._trees['technical'].get_children())} "
        f"req={len(detail._trees['requirements'].get_children())} "
        f"detail_visible={workspace._detail_visible} detail_mapped={detail.winfo_ismapped()} "
        f"toolbar_mapped={workspace.toolbar.winfo_ismapped()}",
        flush=True,
    )
    try:
        from PIL import ImageGrab
        label = "wide" if int(size.split("x", 1)[0]) >= 1220 else "narrow"
        output_root = Path(os.environ.get("EHSIM_QA_OUTPUT_ROOT", Path(__file__).resolve().parents[1]))
        output_dir = output_root / "outputs" / "ui_qa"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"ehsim_hardware_detail_{label}_{tab}.png"
        ImageGrab.grab(bbox=(root_x, root_y, root_x + root_w, root_y + root_h)).save(target)
        print(f"SCREENSHOT {target}", flush=True)
    except Exception as error:
        print(f"SCREENSHOT_UNAVAILABLE {error}", flush=True)
    workspace.window.after(250, workspace.close)
    root.mainloop()


if __name__ == "__main__":
    main()
