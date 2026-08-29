# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — donanim_kartlari_ui.py'nin bölünmüş
parçalarından biri. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 6.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Mapping, Sequence
import webbrowser

try:
    from PIL import Image, ImageTk
except ImportError:  # Görsel desteği isteğe bağlıdır; yer tutucu her zaman çalışır.
    Image = ImageTk = None

import donanim_kartlari_gorsel as hardware_visuals
import donanim_kartlari_yonetim as management
from hardware_image_generation_ui import AIImageGenerationDialog, BulkAIImageDialog
from donanim_kartlari_karsilastirma_ui import HardwareComparisonWorkspace
from donanim_detayli_inceleme_ui import HardwareDetailedReview
from donanim_detayli_inceleme import gallery_entries
from donanim_kartlari_model import (
    LIFECYCLE_STATES,
    MISSING_VALUE,
    PLACEHOLDER_IMAGE,
    PRODUCT_LEVELS,
    WORKING_STATES,
    clean_text,
    is_missing,
)
from hardware_image_provider import ImageProviderError, validate_image_file


from .yardimcilar import (
    DETAIL_TABS,
    ScrollableCards,
    HardwareEditorDialog,
    AlternativeDialog,
    _clean,
    _display,
    _trace_node_index,
    catalog_filter_options,
    product_tree_instances,
)

class _ListeRenderMixin:
    def _render_all(self) -> None:
        self.impact_badges = management.build_impact_badges(self.catalog, self.simulation_result)
        self._render_tree(); self._render_catalog_view(); self._render_detail(); self._render_quality_strip()

    def _card_index(self) -> dict[str, dict[str, Any]]:
        return {
            _clean(item.get("hardware_id"), ""): item
            for item in self.catalog.get("hardware_items", []) if isinstance(item, dict)
        }

    def _render_tree(self) -> None:
        self.product_tree.delete(*self.product_tree.get_children())
        by_id = self._card_index()
        visible = {_clean(item.get("hardware_id"), "") for item in self._filtered_items()}
        if not by_id:
            self.product_tree.insert("", "end", text="Belge üretimi bekleniyor", values=("—", "Veri yok", "—", "—"))
            return
        instances = product_tree_instances(self.catalog)
        instance_map = {_clean(item.get("instance_id"), ""): item for item in instances}
        children: dict[str, list[Mapping[str, Any]]] = {}
        roots = []
        for instance in instances:
            parent = _clean(instance.get("parent_instance_id"), "")
            if parent and not is_missing(parent) and parent in instance_map:
                children.setdefault(parent, []).append(instance)
            else:
                roots.append(instance)

        root_id = "ROOT::CATALOG"
        self.product_tree.insert("", "end", iid=root_id, text=self.catalog.get("project_name") or "Sistem / Katalog", values=("", "", "", ""), open=True)
        visited: set[str] = set()

        def insert(instance: Mapping[str, Any], parent_tree_id: str) -> None:
            instance_id = _clean(instance.get("instance_id"), "")
            hardware_id = _clean(instance.get("hardware_id"), "")
            if not instance_id or instance_id in visited or hardware_id not in by_id:
                return
            visited.add(instance_id)
            card = by_id[hardware_id]
            if visible and hardware_id not in visible and not any(_clean(child.get("hardware_id"), "") in visible for child in children.get(instance_id, [])):
                return
            score = card.get("confidence_score")
            score_text = "—" if score is None else f"{float(score):.0f}" if str(score).replace('.', '', 1).isdigit() else "—"
            badges = self.impact_badges.get(hardware_id, [])
            source_missing = card.get("source_presence_status") == "Kaynaktan artık bulunamadı"
            tree_id = f"INST::{instance_id}"
            self.product_tree.insert(
                parent_tree_id, "end", iid=tree_id, text=_clean(card.get("part_name")),
                values=(instance.get("quantity", card.get("quantity", 1)), _clean(card.get("lifecycle_status")), score_text, "!" if badges else ""),
                tags=("source_missing" if source_missing else "impact" if badges else "normal",), open=True,
            )
            for child in sorted(children.get(instance_id, []), key=lambda value: _clean(by_id.get(_clean(value.get("hardware_id"), ""), {}).get("part_name")).casefold()):
                insert(child, tree_id)
            alternatives = [item for item in card.get("alternative_ids", []) if item in by_id]
            if alternatives:
                branch = f"ALTBR::{instance_id}"
                self.product_tree.insert(tree_id, "end", iid=branch, text="Alternatifler", values=("", "Ayrı ilişki", "", ""), tags=("alternative_branch",))
                for alternative_id in alternatives:
                    alternative = by_id[alternative_id]
                    self.product_tree.insert(branch, "end", iid=f"ALT::{instance_id}::{alternative_id}", text=_clean(alternative.get("part_name")), values=("—", _clean(alternative.get("lifecycle_status")), f"{float(alternative.get('confidence_score', 0)):.0f}", ""), tags=("alternative",))

        for root in sorted(roots, key=lambda value: _clean(by_id.get(_clean(value.get("hardware_id"), ""), {}).get("part_name")).casefold()):
            insert(root, root_id)
        for instance in instances:
            if _clean(instance.get("instance_id"), "") not in visited:
                insert(instance, root_id)
        self.product_tree.tag_configure("impact", foreground="#B42318")
        self.product_tree.tag_configure("source_missing", foreground="#9A6700")
        self.product_tree.tag_configure("alternative", foreground=self.palette_getter()["accent"])
        self.product_tree.tag_configure("alternative_branch", foreground=self.palette_getter()["muted"])

    def _tree_hardware_id(self, tree_id: str) -> str:
        if tree_id.startswith("ALT::"):
            return tree_id.split("::", 2)[-1]
        if not tree_id.startswith("INST::"):
            return ""
        instance_id = tree_id[6:]
        for instance in self.catalog.get("product_instances", []):
            if _clean(instance.get("instance_id"), "") == instance_id:
                return _clean(instance.get("hardware_id"), "")
        if instance_id.startswith("CARD::"):
            return instance_id[6:]
        return ""

    def _tree_selected(self, _event: tk.Event | None = None) -> None:
        if self._syncing_tree_selection:
            return
        selection = self.product_tree.selection()
        if selection:
            hardware_id = self._tree_hardware_id(selection[0])
            # ``selection_set`` bir <<TreeviewSelect>> olayı daha kuyruğa
            # bırakır. Aynı donanımı tekrar işlemek sonsuz seçim döngüsüne ve
            # gerçek Tk mainloop'unda pencerenin donmasına neden oluyordu.
            if hardware_id and hardware_id != self.selected_id:
                self.select_card(hardware_id, scroll_cards=True)

    def _tree_open_detail(self, event: tk.Event | None = None) -> None:
        tree_id = self.product_tree.identify_row(event.y) if event else ""
        hardware_id = self._tree_hardware_id(tree_id)
        if hardware_id:
            self.open_detailed_review(hardware_id)

    def _tree_context_menu(self, event: tk.Event) -> str:
        tree_id = self.product_tree.identify_row(event.y)
        hardware_id = self._tree_hardware_id(tree_id)
        if not hardware_id:
            return "break"
        self.product_tree.selection_set(tree_id)
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(
            label="Detaylı İncele",
            command=lambda: self.open_detailed_review(hardware_id),
        )
        menu.add_command(label="Düzenle", command=lambda: (self.select_card(hardware_id), self._edit_item()))
        menu.add_command(label="Datasheet Yükle", command=lambda: (self.select_card(hardware_id), self._load_datasheet()))
        menu.add_command(
            label="Etki Analizini Başlat",
            command=lambda: self._send_to_impact(hardware_id),
        )
        menu.add_command(label="Karşılaştırmaya Ekle / Çıkar", command=lambda: self._toggle_compare(hardware_id))
        menu.add_separator()
        menu.add_command(label="Arşivle (silmez)", command=lambda: self._archive_item(hardware_id))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _render_quality_strip(self) -> None:
        summary = management.catalog_quality_summary(
            self.catalog, impacted_ids={
                hardware_id for hardware_id, badges in self.impact_badges.items()
                if "Kritik etki" in badges
            },
        )
        labels = {
            "total": "Toplam", "high_confidence": "Yüksek güven",
            "low_confidence": "Düşük güven", "missing_datasheet": "Datasheet yok",
            "missing_image": "Görsel yok", "missing_requirements": "Gereksinim yok",
            "missing_tests": "Test yok", "critical_without_alternative": "Kritik / alternatifsiz",
            "conflicts": "Çelişki",
        }
        for key, button in self.quality_buttons.items():
            button.configure(text=f"{labels[key]}  {summary.get(key, 0)}")

    def _render_catalog_view(self) -> None:
        self.cards.grid_remove(); self.compact_frame.grid_remove(); self.catalog_tree_frame.grid_remove()
        mode = self.view_mode.get()
        self._apply_catalog_panel_span(mode)
        if mode == "Kompakt Liste":
            self.compact_frame.grid(row=1, column=0, sticky="nsew")
            self._render_compact_list()
        elif mode == "Ürün Ağacı":
            self.catalog_tree_frame.grid(row=1, column=0, sticky="nsew")
            self._render_catalog_tree_view()
        else:
            self.cards.grid(row=1, column=0, sticky="nsew")
            self._render_cards()
        card_mode = mode == "Kart"
        self.prev_page_button.configure(state="normal" if card_mode and self._card_page > 0 else "disabled")
        self.next_page_button.configure(state="normal" if card_mode and self._has_next_page() else "disabled")
        if not card_mode:
            self.page_var.set("Tüm eşleşmeler")

    def _apply_catalog_panel_span(self, mode: str | None = None) -> None:
        """Ürün ağacı görünümünde aynı ağacı iki kez yan yana göstermeyi önler."""
        mode = mode or self.view_mode.get()
        if mode == "Ürün Ağacı":
            self.tree_panel.grid_remove()
            self.catalog_panel.grid(
                row=0, column=0, columnspan=2, sticky="nsew",
                padx=(0, 8 if self._wide_layout else 0),
            )
            return
        self.tree_panel.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 8))
        self.catalog_panel.grid(
            row=0, column=1, columnspan=1, sticky="nsew",
            padx=(0, 8 if self._wide_layout else 0),
        )

    def _has_next_page(self) -> bool:
        return (self._card_page + 1) * self._card_page_size < len(self._filtered_items())

    def _change_page(self, step: int) -> None:
        items = self._filtered_items()
        pages = max(1, (len(items) + self._card_page_size - 1) // self._card_page_size)
        self._card_page = max(0, min(pages - 1, self._card_page + step))
        self._render_cards(); self.cards.canvas.yview_moveto(0)

    def _group_label(self, item: Mapping[str, Any]) -> str:
        if self.group_var.get() == "Gruplama: Üretici":
            return _display(item.get("manufacturer"))
        if self.group_var.get() == "Gruplama: Alt sistem":
            by_id = self._card_index(); current = item; visited: set[str] = set()
            while isinstance(current, Mapping):
                hardware_id = _clean(current.get("hardware_id"), "")
                if hardware_id in visited: break
                visited.add(hardware_id)
                if _clean(current.get("hardware_type"), "") in {"Alt sistem", "Sistem"}:
                    return _display(current.get("part_name"))
                current = by_id.get(_clean(current.get("parent_id"), ""))
            return "Üst sistem bulunamadı"
        return ""

    def _render_compact_list(self) -> None:
        self.compact_list.delete(*self.compact_list.get_children())
        items = self._filtered_items(); total = len(self.catalog.get("hardware_items", []))
        self.count_var.set(f"{len(items)} filtrelendi / {total} toplam")
        groups: dict[str, str] = {}
        for item in items:
            parent = ""
            group = self._group_label(item)
            if group:
                parent = groups.setdefault(group, f"GROUP::{len(groups)}")
                if not self.compact_list.exists(parent):
                    self.compact_list.insert("", "end", iid=parent, text=group, values=("",) * 8, open=True, tags=("group",))
            hardware_id = _clean(item.get("hardware_id"), "")
            score = item.get("confidence_score")
            try: score_text = f"{float(score):.0f}"
            except (TypeError, ValueError): score_text = "—"
            self.compact_list.insert(parent, "end", iid=f"LIST::{hardware_id}", text=_display(item.get("part_name")), values=(
                _display(item.get("part_number")), _display(item.get("manufacturer")),
                _display(item.get("system_role")), _display(item.get("lifecycle_status")), score_text,
                len(item.get("requirement_ids") or []), len(item.get("test_ids") or []), len(item.get("alternative_ids") or []),
            ))
        selected = [f"LIST::{value}" for value in self._compare_selection if self.compact_list.exists(f"LIST::{value}")]
        if selected: self.compact_list.selection_set(selected)

    def _render_catalog_tree_view(self) -> None:
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        self._catalog_tree_hardware: dict[str, str] = {}
        visible = {_clean(item.get("hardware_id"), "") for item in self._filtered_items()}
        by_id = self._card_index(); instances = product_tree_instances(self.catalog)
        instance_by_id = {_clean(item.get("instance_id"), ""): item for item in instances}
        children: dict[str, list[Mapping[str, Any]]] = {}
        for instance in instances:
            children.setdefault(_clean(instance.get("parent_instance_id"), ""), []).append(instance)

        def insert_branch(parent: str, parent_instance: str) -> None:
            for instance in sorted(children.get(parent_instance, []), key=lambda row: _clean(by_id.get(_clean(row.get("hardware_id"), ""), {}).get("part_name")).casefold()):
                hardware_id = _clean(instance.get("hardware_id"), "")
                item = by_id.get(hardware_id, {})
                instance_id = _clean(instance.get("instance_id"), hardware_id)
                tree_id = f"CAT::{instance_id}"
                if hardware_id not in visible and not children.get(instance_id):
                    continue
                score = item.get("confidence_score")
                try: score_text = f"{float(score):.0f}"
                except (TypeError, ValueError): score_text = "—"
                self.catalog_tree.insert(parent, "end", iid=tree_id, text=_display(item.get("part_name")), values=(
                    instance.get("quantity", item.get("quantity", 1)), _display(item.get("part_number")),
                    _display(item.get("manufacturer")), _display(item.get("lifecycle_status")), score_text,
                    f"{len(item.get('requirement_ids') or [])} → {len(item.get('test_ids') or [])} → {len(item.get('alternative_ids') or [])}",
                ), open=True)
                self._catalog_tree_hardware[tree_id] = hardware_id
                insert_branch(tree_id, instance_id)

        roots = [key for key in children if not key or is_missing(key) or key not in instance_by_id]
        for root_key in roots or [""]:
            insert_branch("", root_key)
        self.count_var.set(f"{len(visible)} filtrelendi / {len(by_id)} toplam")

    def _compact_selected(self, _event: tk.Event | None = None) -> None:
        ids = [value.split("::", 1)[1] for value in self.compact_list.selection() if value.startswith("LIST::")]
        if len(ids) > 4:
            ids = ids[:4]; self.compact_list.selection_set([f"LIST::{value}" for value in ids])
            self.status_var.set("Karşılaştırmada en fazla 4 donanım seçilebilir.")
        self._compare_selection = set(ids); self._update_compare_controls()
        if len(ids) == 1: self.select_card(ids[0])

    def _compact_open(self, _event: tk.Event | None = None) -> str:
        selection = [value for value in self.compact_list.selection() if value.startswith("LIST::")]
        if selection: self.open_detailed_review(selection[-1].split("::", 1)[1])
        return "break"

    def _compact_context_menu(self, event: tk.Event) -> str:
        row = self.compact_list.identify_row(event.y)
        if not row.startswith("LIST::"): return "break"
        hardware_id = row.split("::", 1)[1]; self.compact_list.selection_set(row)
        return self._card_context_menu(event, hardware_id)

    def _catalog_tree_selected(self, _event: tk.Event | None = None) -> None:
        selection = self.catalog_tree.selection()
        if selection:
            hardware_id = getattr(self, "_catalog_tree_hardware", {}).get(selection[0], "")
            if hardware_id: self.select_card(hardware_id)

    def _catalog_tree_open(self, _event: tk.Event | None = None) -> str:
        selection = self.catalog_tree.selection()
        if selection:
            hardware_id = getattr(self, "_catalog_tree_hardware", {}).get(selection[0], "")
            if hardware_id: self.open_detailed_review(hardware_id)
        return "break"

    def _render_cards(self) -> None:
        for child in self.cards.inner.winfo_children():
            child.destroy()
        self._photo_refs.clear()
        self._card_widgets.clear()
        items = self._filtered_items()
        total = len(self.catalog.get("hardware_items", []))
        pages = max(1, (len(items) + self._card_page_size - 1) // self._card_page_size)
        self._card_page = min(self._card_page, pages - 1)
        start = self._card_page * self._card_page_size
        visible_items = items[start:start + self._card_page_size]
        shown = "0" if not items else f"{start + 1}–{start + len(visible_items)}"
        self.count_var.set(f"{len(items)} filtrelendi / {total} toplam · {shown} gösteriliyor")
        self.page_var.set(f"Sayfa {self._card_page + 1}/{pages}")
        self.prev_page_button.configure(state="normal" if self._card_page > 0 else "disabled")
        self.next_page_button.configure(state="normal" if self._card_page + 1 < pages else "disabled")
        if not items:
            empty = ttk.Frame(self.cards.inner, style="HardwareSurface.TFrame", padding=32)
            empty.pack(fill="both", expand=True)
            message = "Arama ve filtrelerle eşleşen donanım yok." if self.catalog.get("hardware_items") else "Henüz donanım kartı yok.\nÖnce belgeleri üretin; katalog izlenebilirlikten sonra otomatik hazırlanır."
            ttk.Label(empty, text=message, style="HardwareEmpty.TLabel", justify="center").pack(expand=True, pady=30)
            if not self.catalog.get("hardware_items"):
                ttk.Button(empty, text="Örnek Donanım Ağacı Yükle", command=self._load_sample).pack()
            return
        last_group = None
        for item in visible_items:
            group = self._group_label(item)
            if group and group != last_group:
                ttk.Label(
                    self.cards.inner, text=group.upper(), style="HardwareGroup.TLabel",
                ).pack(fill="x", padx=2, pady=(8 if last_group is not None else 2, 2))
                last_group = group
            self._build_card(item)

    def _build_card(self, item: Mapping[str, Any]) -> None:
        hardware_id = _clean(item.get("hardware_id"), "")
        selected = hardware_id == self.selected_id
        badges = list(self.impact_badges.get(hardware_id, []))
        source_missing = item.get("source_presence_status") == "Kaynaktan artık bulunamadı"
        if source_missing:
            badges.append("Kaynaktan artık bulunamadı")
        accent = self._card_accent(hardware_id, selected)
        outer = tk.Frame(self.cards.inner, background=accent, height=190)
        outer.pack(fill="x", pady=4)
        outer.pack_propagate(False)
        card = ttk.Frame(outer, style="HardwareCardSelected.TFrame" if selected else "HardwareCard.TFrame", padding=(9, 8))
        card.pack(fill="both", expand=True, padx=(3, 1), pady=1)
        self._card_widgets[hardware_id] = (outer, card)
        card.columnconfigure(1, weight=1); card.rowconfigure(2, weight=1)
        image = self._make_card_image(card, item)
        image.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 10))
        title = ttk.Label(card, text=_clean(item.get("part_name")), style="HardwareCardTitle.TLabel", cursor="hand2")
        title.grid(row=0, column=1, sticky="w")
        meta = ttk.Label(card, text=f"PN  {_display(item.get('part_number'))}   ·   Üretici  {_display(item.get('manufacturer'))}", style="HardwareMono.TLabel")
        meta.grid(row=1, column=1, sticky="w", pady=(2, 0))
        role = ttk.Label(card, text=f"Görev: {_display(item.get('system_role'))}", style="HardwareCardText.TLabel", wraplength=270, justify="left")
        role.grid(row=2, column=1, sticky="nw", pady=(3, 0))
        facts = ttk.Frame(card, style="HardwareCard.TFrame")
        facts.grid(row=0, column=2, rowspan=3, sticky="ne", padx=(10, 0))
        td = item.get("technical_data") or {}
        temperature_values = [td.get("operating_temperature_min"), td.get("operating_temperature_max")]
        temp = (
            MISSING_VALUE if all(is_missing(value) for value in temperature_values)
            else f"{_display(temperature_values[0])}…{_display(temperature_values[1])} {_display(td.get('temperature_unit'))}"
        )
        dimension_values = [td.get(key) for key in ("length", "width", "height")]
        dimensions = (
            MISSING_VALUE if all(is_missing(value) for value in dimension_values)
            else " × ".join(_display(value) for value in dimension_values)
            + f" {_display(td.get('dimension_unit'))}"
        )
        score = item.get("confidence_score")
        score_text = "Hesaplanamadı" if score is None else f"{float(score):.0f}/100"
        for text in (
            f"Çalışma: {temp}", f"Boyut: {dimensions}",
            f"Durum: {_display(item.get('lifecycle_status'))}", f"Güven: {score_text}",
            f"Gereksinim: {len(item.get('requirement_ids') or [])}   Alternatif: {len(item.get('alternative_ids') or [])}",
        ):
            ttk.Label(facts, text=text, style="HardwareMono.TLabel").pack(anchor="e")
        trace = ttk.Frame(card, style="HardwareTraceBar.TFrame", padding=(4, 2))
        trace.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        trace.columnconfigure((0, 2, 4, 6, 8), weight=1)
        trace_items = (
            ("Üst Sistem", "location"), ("Parça", "identity"),
            (f"Gereksinim {len(item.get('requirement_ids') or [])}", "requirements"),
            (f"Test {len(item.get('test_ids') or [])}", "requirements"), (f"Alternatif {len(item.get('alternative_ids') or [])}", "alternatives"),
        )
        for index, (text, tab) in enumerate(trace_items):
            ttk.Button(trace, text=text, style="HardwareTrace.TButton", command=lambda key=tab, hid=hardware_id: self._trace_click(hid, key)).grid(row=0, column=index * 2, sticky="ew")
            if index < 4:
                ttk.Label(trace, text="→", style="HardwareTraceArrow.TLabel").grid(row=0, column=index * 2 + 1, padx=3)
        if badges:
            ttk.Label(card, text="  ·  ".join(badges), style="HardwareImpact.TLabel").grid(row=4, column=0, sticky="w", pady=(3, 0))
        compare_text = "Karşılaştırmadan Çıkar" if hardware_id in self._compare_selection else "Karşılaştırmaya Ekle"
        ttk.Button(
            card, text=compare_text, style="HardwareTrace.TButton",
            command=lambda hid=hardware_id: self._toggle_compare(hid),
        ).grid(row=4, column=1, sticky="e", padx=(4, 4), pady=(3, 0))
        impact_button = ttk.Button(card, text="Etki Analizi", style="primary.Outline.TButton", command=lambda hid=hardware_id: self._send_to_impact(hid))
        impact_button.grid(row=4, column=2, sticky="e", pady=(3, 0))
        for widget in (outer, card, image, title, meta, role, facts):
            widget.bind("<Button-1>", lambda _event, hid=hardware_id: self.open_detailed_review(hid))
            widget.bind("<Double-1>", lambda _event, hid=hardware_id: self.open_detailed_review(hid))
            widget.bind("<Button-3>", lambda event, hid=hardware_id: self._card_context_menu(event, hid))
            widget.bind("<Button-2>", lambda event, hid=hardware_id: self._card_context_menu(event, hid))

    def _card_context_menu(self, event: tk.Event, hardware_id: str) -> str:
        menu = tk.Menu(self.window, tearoff=False)
        menu.add_command(label="Detaylı İncele", command=lambda: self.open_detailed_review(hardware_id))
        menu.add_command(label="Düzenle", command=lambda: (self.select_card(hardware_id), self._edit_item()))
        menu.add_command(label="Datasheet Yükle", command=lambda: (self.select_card(hardware_id), self._load_datasheet()))
        menu.add_command(label="Etki Analizini Başlat", command=lambda: self._send_to_impact(hardware_id))
        menu.add_command(label="Karşılaştırmaya Ekle / Çıkar", command=lambda: self._toggle_compare(hardware_id))
        menu.add_separator()
        menu.add_command(label="Arşivle (silmez)", command=lambda: self._archive_item(hardware_id))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

