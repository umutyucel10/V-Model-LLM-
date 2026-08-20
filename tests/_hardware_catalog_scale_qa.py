# -*- coding: utf-8 -*-
"""500 kartlık gerçek Tk kataloğunda oluşturma ve filtre performansı."""

from copy import deepcopy
from pathlib import Path
import sys
import time
import tkinter as tk

from ttkbootstrap.style import Style

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import donanim_kartlari_ui as ui
import donanim_kartlari_yonetim as management


def large_catalog() -> dict:
    catalog = management.sample_catalog("QA 500 — GERÇEK PROJE VERİSİ DEĞİLDİR")
    template = deepcopy(catalog["hardware_items"][0])
    items = []
    for index in range(500):
        item = deepcopy(template)
        item.update({
            "hardware_id": f"PERF-{index:04d}",
            "part_name": f"Performans Kartı {index:04d}",
            "part_number": f"PN-{index:04d}",
            "manufacturer": "A Üretici" if index % 2 == 0 else "B Üretici",
            "parent_id": "Veri bulunamadı", "confidence_score": index % 101,
            "requirement_ids": [f"REQ-{index:04d}"] if index % 3 == 0 else [],
            "test_ids": [f"TEST-{index:04d}"] if index % 6 == 0 else [],
            "alternative_ids": [], "image_path": "placeholder://donanim",
        })
        items.append(item)
    catalog["hardware_items"] = items
    catalog["product_instances"] = []
    catalog["product_tree"] = []
    catalog["project_id"] = "qa-500-hardware"
    return catalog


def main() -> None:
    root = tk.Tk(); root.withdraw(); style = Style(theme="litera")
    palette = {
        "bg": "#F5F6F7", "surface": "#FFFFFF", "fg": "#222222",
        "muted": "#5C666D", "entry_bg": "#FFFFFF", "entry_fg": "#222222", "accent": "#0052cc",
    }
    catalog = large_catalog()
    started = time.perf_counter()
    workspace = ui.HardwareCardsWorkspace(
        root, style, lambda: "tr", lambda: palette, lambda: "QA 500",
        lambda: catalog, lambda: {"nodes": [], "edges": []},
    )
    workspace.window.geometry("1440x900")
    workspace.window.update_idletasks(); workspace._on_resize(type("E", (), {"widget": workspace.window, "width": 1440})())
    # Önceki QA koşusundan atomik olarak saklanmış görünüm tercihi bu
    # performans ölçümünü değiştirmesin; kart modunu özellikle doğrula.
    workspace.view_mode.set("Kart"); workspace._view_changed()
    workspace.window.update_idletasks()
    startup = time.perf_counter() - started
    rendered_cards = len(workspace._card_widgets)

    workspace.search_var.set("Performans Kartı 04")
    started = time.perf_counter(); workspace._apply_filters_changed(); workspace.window.update_idletasks()
    filter_time = time.perf_counter() - started
    filtered = len(workspace._filtered_items())

    workspace.search_var.set(workspace.search_placeholder)
    workspace.view_mode.set("Kompakt Liste")
    started = time.perf_counter(); workspace._view_changed(); workspace.window.update_idletasks()
    list_time = time.perf_counter() - started
    list_rows = len(workspace.compact_list.get_children())
    print(
        f"SCALE_QA startup={startup:.3f}s filter={filter_time:.3f}s "
        f"compact={list_time:.3f}s cards_created={rendered_cards} "
        f"filtered={filtered} compact_rows={list_rows}",
        flush=True,
    )
    if rendered_cards > workspace._card_page_size:
        raise RuntimeError("Görünmeyen katalog kartları da oluşturuldu.")
    if filter_time > 0.75:
        raise RuntimeError("500 kart araması kabul edilen etkileşim süresini aştı.")
    workspace.close(); root.destroy()


if __name__ == "__main__":
    main()
