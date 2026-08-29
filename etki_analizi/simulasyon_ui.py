# -*- coding: utf-8 -*-
"""Gereksinim değişikliği simülasyonu için Tkinter çalışma alanı."""

from __future__ import annotations

from dataclasses import replace
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Mapping

import etki_analizi_entegrasyon as integration
import etki_analizi_simulasyon as simulation
from etki_analizi_degisim_paketi import (
    ApplicationResult,
    ChangePackageError,
    build_change_package,
    save_change_package,
)
from etki_analizi_degisim_ui import ChangeApprovalDialog


LEFT_TYPES = {
    "Müşteri/paydaş gereksinimi": "Müşteri",
    "Sistem gereksinimi": "Sistem",
    "Alt sistem gereksinimi": "Alt sistem",
    "Fonksiyon": "Mimari",
    "Tasarım kararı": "Tasarım",
    "Parça/bileşen": "Parça",
    "Yazılım birimi": "Parça",
}
RIGHT_TYPES = {
    "Birim testi": "Birim testi",
    "Entegrasyon testi": "Entegrasyon testi",
    "Sistem doğrulama testi": "Sistem doğrulaması",
    "Müşteri kabul/geçerleme testi": "Müşteri kabul/geçerlemesi",
    "Doğrulama kriteri": "Sistem doğrulaması",
}
REQUIREMENT_TYPES = {
    "Müşteri/paydaş gereksinimi", "Sistem gereksinimi", "Alt sistem gereksinimi",
}
PART_INTERFACE_TYPES = {
    "Parça/bileşen", "Yazılım birimi", "Mekanik arayüz",
    "Elektriksel arayüz", "Yazılımsal arayüz", "Tasarım kararı", "Fonksiyon",
    "Teknik belge",
}
TEST_TYPES = set(RIGHT_TYPES)
IMPACT_COLORS = {
    "Kritik": "#C62828", "Yüksek": "#EF6C00", "Orta": "#D6A400",
    "Düşük": "#2E7D32", "Belirsiz": "#7A7F87", "Veri eksik": "#7A7F87",
}
RESULT_TAB_TITLES = (
    ("summary", "Yönetici Özeti", "Executive Summary"),
    ("left", "V-Model Sol Kol Etkileri", "V-Model Left-Leg Impacts"),
    ("right", "V-Model Sağ Kol Etkileri", "V-Model Right-Leg Impacts"),
    ("requirements", "Etkilenen Gereksinimler", "Affected Requirements"),
    ("parts", "Parçalar ve Arayüzler", "Parts and Interfaces"),
    ("tests", "Test ve Doğrulama Etkileri", "Test and Verification Impacts"),
    ("risks", "Riskler", "Risks"),
    ("ideas", "Mühendislik Fikirleri", "Engineering Ideas"),
    ("sources", "Kaynaklar ve Varsayımlar", "Sources and Assumptions"),
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def impact_color(level: Any, confidence: float | None = None) -> str:
    if confidence is not None and confidence < 0.35:
        return IMPACT_COLORS["Belirsiz"]
    return IMPACT_COLORS.get(_clean(level), IMPACT_COLORS["Belirsiz"])


def _node_index(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _clean(node.get("id")): dict(node)
        for node in report.get("nodes", [])
        if isinstance(node, Mapping) and _clean(node.get("id"))
    }


def build_result_views(
    result: simulation.SimulationResult, report: Mapping[str, Any]
) -> dict[str, Any]:
    """UI'den bağımsız, dokuz sekmenin denetlenebilir görünüm modelini üretir."""
    nodes = _node_index(report)
    impacts = {item.item_id: item for item in result.impacts}
    selected_id = _clean((result.selected_item or {}).get("id"))
    left, right = [], []
    for item in result.impacts:
        row = {
            "id": item.item_id, "title": item.title, "node_type": item.node_type,
            "level": item.impact_level, "score": item.impact_score,
            "confidence": item.confidence, "confidence_level": item.confidence_level,
            "path": item.traceability_path.display_path, "rationale": item.rationale,
            "evidence": item.source_evidence,
        }
        if item.node_type in LEFT_TYPES:
            row["lane"] = LEFT_TYPES[item.node_type]
            left.append(row)
        if item.node_type in RIGHT_TYPES:
            row["lane"] = RIGHT_TYPES[item.node_type]
            right.append(row)
    target = dict(result.selected_item or {})
    target.update({
        "id": selected_id, "level": result.summary.get("overall_impact_level", "Belirsiz"),
        "score": result.summary.get("overall_impact_score", 0),
        "confidence": 1.0, "path": selected_id, "rationale": "Değişiklik başlangıç noktasıdır.",
    })
    decisions = dict((report.get("user_overrides") or {}).get("suggestion_decisions") or {})
    ideas = []
    for item in result.engineering_suggestions:
        value = item.to_dict()
        value["decision"] = decisions.get(item.suggestion_id, "Bekliyor")
        ideas.append(value)
    critical = sum(1 for item in result.impacts if item.impact_level == "Kritik")
    updated_tests = list(result.categorized_impacts.get("new_or_updated_tests", []))
    risks = sorted(result.risks, key=lambda item: item.risk_score, reverse=True)
    confidence_values = [item.confidence for item in result.impacts]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    if critical:
        decision = "Değişiklik, kritik etkiler kapatılmadan onaylanmamalıdır."
    elif result.warnings:
        decision = "Eksik kanıtlar tamamlandıktan sonra koşullu değerlendirme önerilir."
    else:
        decision = "İzlenebilirlik yolları doğrulanarak değişiklik kuruluna sunulabilir."
    summary = {
        "change": (
            f"{selected_id or result.change_request.requirement_id or 'Yeni gereksinim'} · "
            f"{result.change_request.change_type}"
        ),
        "impact_count": len(result.impacts), "critical_count": critical,
        "document_count": result.summary.get("affected_document_count", 0),
        "test_count": len(updated_tests),
        "top_risks": [item.to_dict() for item in risks[:3]],
        "decision": decision, "confidence": confidence,
    }
    update_rows = []
    proposed = _clean(result.change_request.proposed_value)
    if result.selected_item:
        update_rows.append({
            "id": selected_id,
            "type": _clean(result.selected_item.get("node_type")) or "Sistem gereksinimi",
            "current": _clean(result.selected_item.get("description"))
            or _clean(result.change_request.current_value),
            "proposed": proposed or "Gereksinim kaldırılacak.",
            "level": result.summary.get("overall_impact_level", "Belirsiz"),
            "score": result.summary.get("overall_impact_score", 0),
            "path": selected_id,
        })
    elif result.change_request.change_type == simulation.CHANGE_REQUIREMENT_ADD:
        update_rows.append({
            "id": result.change_request.requirement_id or "YENİ-GEREKSİNİM",
            "type": "Sistem gereksinimi", "current": "—",
            "proposed": proposed, "level": "Belirsiz", "score": 0,
            "path": "Yeni izlenebilirlik bağlantıları tanımlanmalı.",
        })
    for item in result.impacts:
        node = nodes.get(item.item_id, {})
        current = _clean(node.get("description") or item.title)
        proposed_text = (
            proposed if item.item_id == selected_id and proposed
            else "Yeni metin kullanıcı tarafından tanımlanmalı; mevcut içerik otomatik değiştirilmedi."
        )
        update_rows.append({
            "id": item.item_id, "type": item.node_type, "current": current,
            "proposed": proposed_text, "level": item.impact_level,
            "score": item.impact_score, "path": item.traceability_path.display_path,
        })
    sources = []
    if selected_id:
        selected_node = nodes.get(selected_id, {})
        sources.append({
            "id": selected_id,
            "document": _clean(selected_node.get("source_document"))
            or "Kaynak belge belirtilmemiş",
            "section": _clean(
                selected_node.get("section") or selected_node.get("page_section")
            ) or "—",
            "evidence": _clean(selected_node.get("evidence_text"))
            or _clean(selected_node.get("description")),
            "path": selected_id, "rationale": "Değişiklik başlangıç noktasıdır.",
        })
    for item in result.impacts:
        node = nodes.get(item.item_id, {})
        sources.append({
            "id": item.item_id,
            "document": _clean(node.get("source_document")) or "Kaynak belge belirtilmemiş",
            "section": _clean(node.get("section") or node.get("page_section")) or "—",
            "evidence": item.source_evidence, "path": item.traceability_path.display_path,
            "rationale": item.rationale,
        })
    return {
        "summary": summary, "target": target, "left": left, "right": right,
        "requirements": [row for row in update_rows if row["type"] in REQUIREMENT_TYPES],
        "parts": [row for row in update_rows if row["type"] in PART_INTERFACE_TYPES],
        "tests": [row for row in update_rows if row["type"] in TEST_TYPES],
        "test_actions": updated_tests, "risks": [item.to_dict() for item in risks],
        "ideas": ideas, "sources": sources, "nodes": nodes, "impacts": impacts,
        "warnings": list(result.warnings), "assumptions": list(result.change_request.assumptions),
    }


class RequirementSimulationPanel:
    """İzlenebilirlik grafiği üzerinde çalışan, UI-thread güvenli simülasyon paneli."""

    def __init__(
        self, parent: tk.Misc, style: ttk.Style,
        language_getter: Callable[[], str],
        palette_getter: Callable[[], Mapping[str, str]],
        traceability_getter: Callable[[], Mapping[str, Any] | None],
        traceability_update_callback: Callable[[Mapping[str, Any]], None] | None = None,
        rescan_callback: Callable[[bool], None] | None = None,
        cancel_trace_callback: Callable[[], None] | None = None,
        project_info_getter: Callable[[], Mapping[str, Any]] | None = None,
        change_apply_callback: Callable[
            [Any, Callable[[ApplicationResult], None], Callable[[str], None]], None
        ] | None = None,
        result_callback: Callable[[simulation.SimulationResult], None] | None = None,
        hardware_detail_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.parent, self.style = parent, style
        self.language_getter, self.palette_getter = language_getter, palette_getter
        self.traceability_getter = traceability_getter
        self.traceability_update_callback = traceability_update_callback
        self.rescan_callback, self.cancel_trace_callback = rescan_callback, cancel_trace_callback
        self.project_info_getter = project_info_getter or (lambda: {})
        self.change_apply_callback = change_apply_callback
        self.result_callback = result_callback
        self.hardware_detail_callback = hardware_detail_callback
        self.last_result: simulation.SimulationResult | None = None
        self.last_change_package: Any = None
        self.change_dialog: ChangeApprovalDialog | None = None
        self.pending_request: simulation.ChangeRequest | None = None
        self.views: dict[str, Any] = {}
        self._worker_messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker_token = 0
        self._cancel_event = threading.Event()
        self._trace_in_progress = False
        self._canvas_items: dict[int, str] = {}
        self._translatable: list[tuple[tk.Widget, str, str]] = []

        self.project_name = tk.StringVar(value="Belge üretimi bekleniyor")
        self.health_status = tk.StringVar(value="Belge üretimi gerekli")
        self.health_detail = tk.StringVar(value="İzlenebilirlik verisi bulunamadı.")
        self.requirement_id = tk.StringVar()
        self.change_type = tk.StringVar(value=simulation.CHANGE_REQUIREMENT_TEXT)
        self.requested_by = tk.StringVar(value="Sistem Mühendisliği")
        self.use_lm = tk.BooleanVar(value=False)
        self.auto_rerun = tk.BooleanVar(value=False)
        self.work_status = tk.StringVar(value="Bir değişiklik isteği girilmedi.")
        self._build()
        self.apply_theme()
        self.refresh_project()

    def _tr(self, tr: str, en: str) -> str:
        return tr if self.language_getter() == "tr" else en

    def _label(self, parent: tk.Misc, tr: str, en: str, **kwargs: Any) -> ttk.Label:
        item = ttk.Label(parent, text=self._tr(tr, en), **kwargs)
        self._translatable.append((item, tr, en))
        return item

    def _button(self, parent: tk.Misc, tr: str, en: str, **kwargs: Any) -> ttk.Button:
        item = ttk.Button(parent, text=self._tr(tr, en), **kwargs)
        self._translatable.append((item, tr, en))
        return item

    def _text(self, parent: tk.Misc, height: int) -> tk.Text:
        return tk.Text(
            parent, height=height, wrap="word", relief="solid", borderwidth=1,
            font=("Segoe UI", 9), padx=6, pady=5,
        )

    def _build(self) -> None:
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(1, weight=1)
        health = ttk.Frame(
            self.parent, style="ImpactPanel.TFrame", padding=(12, 9),
            borderwidth=1, relief="solid",
        )
        health.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        health.columnconfigure(1, weight=1)
        self._label(health, "PROJE / BELGE SETİ", "PROJECT / DOCUMENT SET",
                    style="ImpactSection.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(health, textvariable=self.project_name,
                  style="ImpactGateLabel.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.health_badge = ttk.Label(health, textvariable=self.health_status,
                                      style="ImpactGateLabel.TLabel")
        self.health_badge.grid(row=0, column=2, sticky="e", padx=(10, 8))
        self.rescan_button = self._button(
            health, "İzlenebilirliği Yeniden Tara", "Rescan Traceability",
            command=self._rescan, style="primary.Outline.TButton",
        )
        self.rescan_button.grid(row=0, column=3, padx=(4, 4))
        self.trace_cancel_button = self._button(
            health, "İptal", "Cancel", command=self._cancel_all,
            state=tk.DISABLED,
        )
        self.trace_cancel_button.grid(row=0, column=4)
        ttk.Label(health, textvariable=self.health_detail,
                  style="ImpactGateHint.TLabel").grid(
            row=1, column=0, columnspan=5, sticky="ew", pady=(4, 0)
        )

        self.body = ttk.Panedwindow(self.parent, orient=tk.HORIZONTAL)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.form_shell = ttk.Frame(
            self.body, style="ImpactPanel.TFrame", width=365,
            borderwidth=1, relief="solid",
        )
        results = ttk.Frame(self.body, style="ImpactRoot.TFrame")
        self.body.add(self.form_shell, weight=0)
        self.body.add(results, weight=1)
        self._build_form(self.form_shell)
        self._build_results(results)
        self.parent.after_idle(self.ensure_visible)

    def _build_form(self, shell: ttk.Frame) -> None:
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        palette = self.palette_getter()
        self.form_canvas = tk.Canvas(shell, highlightthickness=0, background=palette["surface"])
        scroll = ttk.Scrollbar(shell, orient="vertical", command=self.form_canvas.yview)
        self.form_canvas.configure(yscrollcommand=scroll.set)
        self.form_canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        # Canvas içine eklenen formu örnek değişkenlerinde tutmak, özellikle macOS'ta
        # gizli Notebook sekmesi ilk kez açıldığında geometri bilgisinin kaybolmasını
        # önler. Boyut ve scroll bölgesi her görünür oluşta yeniden eşitlenir.
        self.form_frame = ttk.Frame(
            self.form_canvas, style="ImpactPanel.TFrame", padding=12
        )
        self.form_frame.columnconfigure(0, weight=1)
        self._form_window_id = self.form_canvas.create_window(
            (0, 0), window=self.form_frame, anchor="nw"
        )
        self.form_frame.bind("<Configure>", self._sync_form_layout)
        self.form_canvas.bind("<Configure>", self._sync_form_layout)
        self.form_canvas.bind("<Map>", lambda _event: self.parent.after_idle(
            self.ensure_visible
        ))
        form = self.form_frame
        row = 0
        self._label(form, "DEĞİŞİKLİK İSTEĞİ", "CHANGE REQUEST",
                    style="ImpactSection.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 8))
        row += 1
        self._label(form, "Gereksinim seçimi", "Requirement selection",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        self.requirement_combo = ttk.Combobox(
            form, textvariable=self.requirement_id, state="readonly", values=()
        )
        self.requirement_combo.grid(row=row, column=0, sticky="ew", pady=(3, 7))
        self.requirement_combo.bind("<<ComboboxSelected>>", self._requirement_selected)
        row += 1
        self._label(form, "Serbest metin sorusu", "Free-text question",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        self.question_text = self._text(form, 3)
        self.question_text.grid(row=row, column=0, sticky="ew", pady=(3, 7))
        self._question_placeholder = (
            "Örnek: SYS-REQ-001 gereksinimindeki maksimum ağırlığı "
            "10 kg’dan 8 kg’a düşürürsem neler etkilenir?"
        )
        self.question_text.insert("1.0", self._question_placeholder)
        self.question_text.bind("<FocusIn>", self._question_focus_in)
        self.question_text.bind("<FocusOut>", self._question_focus_out)
        row += 1
        self._label(form, "Değişiklik türü", "Change type",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Combobox(
            form, textvariable=self.change_type, values=simulation.SUPPORTED_CHANGE_TYPES,
            state="readonly",
        ).grid(row=row, column=0, sticky="ew", pady=(3, 7))
        row += 1
        self._label(form, "Mevcut gereksinim", "Current requirement",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        self.current_text = self._text(form, 3)
        self.current_text.grid(row=row, column=0, sticky="ew", pady=(3, 7))
        row += 1
        self._label(form, "Önerilen yeni gereksinim veya değer", "Proposed requirement or value",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        self.proposed_text = self._text(form, 3)
        self.proposed_text.grid(row=row, column=0, sticky="ew", pady=(3, 7))
        row += 1
        self._label(form, "Değişiklik nedeni", "Reason for change",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        self.reason_text = self._text(form, 2)
        self.reason_text.grid(row=row, column=0, sticky="ew", pady=(3, 7))
        row += 1
        self._label(form, "Değişikliği isteyen taraf", "Requested by",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Entry(form, textvariable=self.requested_by).grid(
            row=row, column=0, sticky="ew", pady=(3, 7)
        )
        row += 1
        self._label(form, "Varsayımlar (satır başına bir)", "Assumptions (one per line)",
                    style="ImpactField.TLabel").grid(row=row, column=0, sticky="w")
        row += 1
        self.assumptions_text = self._text(form, 2)
        self.assumptions_text.grid(row=row, column=0, sticky="ew", pady=(3, 6))
        row += 1
        self.lm_check = ttk.Checkbutton(
            form, variable=self.use_lm, text="LM Studio yorum ve mühendislik fikirleri"
        )
        self.lm_check.grid(row=row, column=0, sticky="w")
        self._translatable.append((
            self.lm_check, "LM Studio yorum ve mühendislik fikirleri",
            "LM Studio commentary and engineering ideas",
        ))
        row += 1
        self.auto_check = ttk.Checkbutton(
            form, variable=self.auto_rerun,
            text="Yeni belge sürümü hazır olunca hazırlanmış isteği yeniden çalıştır"
        )
        self.auto_check.grid(row=row, column=0, sticky="w", pady=(2, 7))
        self._translatable.append((
            self.auto_check,
            "Yeni belge sürümü hazır olunca hazırlanmış isteği yeniden çalıştır",
            "Rerun the prepared request when a new document version is ready",
        ))
        row += 1
        actions = ttk.Frame(form, style="ImpactPanel.TFrame")
        actions.grid(row=row, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.run_button = self._button(
            actions, "Etkiyi Simüle Et", "Simulate Impact",
            command=self.start_simulation, style="primary.TButton",
        )
        self.run_button.grid(row=0, column=0, sticky="ew")
        self.rerun_button = self._button(
            actions, "Yeniden Çalıştır", "Rerun",
            command=self._rerun, state=tk.DISABLED,
        )
        self.rerun_button.grid(row=0, column=1, padx=(6, 0))
        row += 1
        self.progress = ttk.Progressbar(form, mode="indeterminate")
        self.progress.grid(row=row, column=0, sticky="ew", pady=(8, 3))
        row += 1
        ttk.Label(form, textvariable=self.work_status, style="ImpactGateHint.TLabel",
                  wraplength=325).grid(row=row, column=0, sticky="ew")

    def _sync_form_layout(self, _event: Any = None) -> None:
        """Kaydırılabilir formun genişliğini ve görünür bölgesini güvenle eşitler."""
        try:
            width = max(1, self.form_canvas.winfo_width())
            self.form_canvas.itemconfigure(self._form_window_id, width=width)
            bbox = self.form_canvas.bbox("all")
            if bbox:
                content_height = max(self.form_canvas.winfo_height(), bbox[3])
                self.form_canvas.configure(
                    scrollregion=(0, 0, width, content_height)
                )
        except tk.TclError:
            return

    def ensure_visible(self) -> None:
        """Gizli sekmeden açılan giriş formunu görünür başlangıç konumuna getirir."""
        try:
            self.parent.update_idletasks()
            self._sync_form_layout()
            self.form_canvas.yview_moveto(0.0)
        except tk.TclError:
            return

    def select_requirement(self, requirement_id: str) -> None:
        """Dış çalışma alanından gelen gerçek gereksinim kimliğini forma taşır."""
        self.refresh_project()
        values = set(self.requirement_combo.cget("values"))
        if requirement_id not in values:
            raise ValueError(
                f"'{requirement_id}' izlenebilirlik haritasındaki gereksinimler arasında bulunamadı."
            )
        self.requirement_id.set(requirement_id)
        self._requirement_selected()
        self.parent.after_idle(self.ensure_visible)

    def _build_results(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.result_notebook = ttk.Notebook(parent, style="Impact.TNotebook")
        self.result_notebook.grid(row=0, column=0, sticky="nsew", padx=(10, 0))
        self.tabs: dict[str, ttk.Frame] = {}
        for key, tr, en in RESULT_TAB_TITLES:
            tab = ttk.Frame(self.result_notebook, style="ImpactRoot.TFrame", padding=(0, 8, 0, 0))
            self.result_notebook.add(tab, text=self._tr(tr, en))
            self.tabs[key] = tab
        self._build_summary_tab()
        self._build_vmodel_tab("left")
        self._build_vmodel_tab("right")
        self.requirement_tree = self._build_update_tab("requirements")
        self.parts_tree = self._build_update_tab("parts")
        self.parts_tree.bind(
            "<<TreeviewSelect>>", lambda _event: self._tree_detail(self.parts_tree)
        )
        self.tests_tree = self._build_test_tab()
        self.risk_tree = self._build_risk_tab()
        self.idea_tree = self._build_idea_tab()
        self._build_sources_tab()
        self._render_empty_state()

    def _render_empty_state(self) -> None:
        """Tarama ile simülasyon arasındaki bekleme durumunu açıkça gösterir."""
        self.summary_heading.configure(text="Değişiklik simülasyonu bekleniyor")
        self._set_text(self.summary_text, (
            "İzlenebilirlik haritası hazırlandıysa sol taraftan bir gereksinim seçin "
            "veya serbest metin sorunuzu yazın.\n\n"
            "Belge taraması yalnızca analiz altyapısını hazırlar; hayali bir değişiklik "
            "oluşturmaz. Değerler ve etki yolları ‘Etkiyi Simüle Et’ düğmesinden sonra "
            "bu sekmelerde gösterilir."
        ))
        self._set_text(
            self.source_text,
            "Henüz bir değişiklik simülasyonu çalıştırılmadı. Kaynak belge, bölüm, "
            "kanıt metni ve izlenebilirlik yolları simülasyon tamamlanınca burada görünür.",
        )
        self._fill_update_tree(self.requirement_tree, [])
        self._fill_update_tree(self.parts_tree, [])
        self._fill_update_tree(self.tests_tree, [])
        self.risk_tree.insert(
            "", tk.END, iid="__empty__",
            values=("Simülasyon bekleniyor", "—", "—", "—", "—", "—"),
        )
        self.idea_tree.insert(
            "", tk.END, iid="__empty__",
            values=("Simülasyon bekleniyor", "Etki analizi çalıştırıldığında doldurulur.", "—", "—"),
        )
        self._draw_vmodel("left")
        self._draw_vmodel("right")

    def _readonly_text(self, parent: tk.Misc) -> tk.Text:
        item = self._text(parent, 8)
        item.configure(state=tk.DISABLED, relief="flat")
        return item

    def _build_summary_tab(self) -> None:
        tab = self.tabs["summary"]
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.summary_heading = ttk.Label(
            tab, text="Simülasyon sonucu bekleniyor", style="ImpactTitle.TLabel"
        )
        self.summary_heading.grid(row=0, column=0, sticky="w", pady=(0, 8))
        actions = ttk.Frame(tab, style="ImpactRoot.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.change_package_button = self._button(
            actions,
            "Güncelleme Taslağı Oluştur",
            "Create Update Draft",
            command=self._open_change_package,
            state=tk.DISABLED,
            style="primary.Outline.TButton",
        )
        self.change_package_button.pack(side="left")
        ttk.Label(
            actions,
            text="Mevcut/önerilen içerik · kullanıcı kararı · yedek · yeni sürüm · son kontrol",
            style="ImpactGateHint.TLabel",
        ).pack(side="left", padx=(10, 0))
        self.summary_text = self._readonly_text(tab)
        self.summary_text.grid(row=2, column=0, sticky="nsew")

    def _open_change_package(self) -> None:
        if not self.last_result or self.last_result.status != "completed":
            messagebox.showwarning(
                self._tr("Güncelleme Taslağı", "Update Draft"),
                self._tr(
                    "Önce başarılı bir gereksinim değişikliği simülasyonu çalıştırın.",
                    "Run a successful requirement change simulation first.",
                ),
                parent=self.parent,
            )
            return
        report = getattr(self, "_active_report", None) or self.traceability_getter()
        if not report:
            messagebox.showwarning(
                self._tr("Güncelleme Taslağı", "Update Draft"),
                self._tr(
                    "İzlenebilirlik verisi bulunamadı. Önce belgeleri üretin veya yeniden tarayın.",
                    "Traceability data is unavailable. Generate or rescan documents first.",
                ),
                parent=self.parent,
            )
            return
        try:
            package = build_change_package(self.last_result, report)
            save_change_package(package)
        except (ChangePackageError, OSError, ValueError) as error:
            messagebox.showerror(
                self._tr("Güncelleme Taslağı", "Update Draft"), str(error), parent=self.parent
            )
            return
        self.last_change_package = package
        self.change_dialog = ChangeApprovalDialog(
            self.parent, package, apply_callback=self.change_apply_callback,
        )

    def _build_vmodel_tab(self, side: str) -> None:
        tab = self.tabs[side]
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=3)
        tab.rowconfigure(1, weight=1)
        canvas = tk.Canvas(tab, height=360, highlightthickness=1)
        canvas.grid(row=0, column=0, sticky="nsew")
        detail = self._readonly_text(tab)
        detail.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        setattr(self, f"{side}_canvas", canvas)
        setattr(self, f"{side}_detail", detail)
        canvas.bind("<Configure>", lambda _event, value=side: self._draw_vmodel(value))

    def _tree(self, parent: tk.Misc, columns: tuple[tuple[str, str, int], ...]) -> ttk.Treeview:
        frame = ttk.Frame(parent, style="ImpactPanel.TFrame", borderwidth=1, relief="solid")
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            frame, columns=[key for key, _title, _width in columns],
            show="headings", style="Impact.Treeview", selectmode="browse",
        )
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=60, anchor="w", stretch=True)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)
        return tree

    def _build_update_tab(self, key: str) -> ttk.Treeview:
        tab = self.tabs[key]
        tree = self._tree(tab, (
            ("id", "Kimlik", 120), ("type", "Tür", 150), ("level", "Etki", 70),
            ("current", "Mevcut içerik", 260), ("proposed", "Önerilen içerik", 280),
        ))
        tree.bind("<Double-1>", lambda _e, item=tree: self._tree_detail(item))
        return tree

    def _build_test_tab(self) -> ttk.Treeview:
        tree = self._build_update_tab("tests")
        return tree

    def _build_risk_tab(self) -> ttk.Treeview:
        tree = self._tree(self.tabs["risks"], (
            ("category", "Kategori", 120), ("level", "Seviye", 80),
            ("probability", "Olasılık", 70), ("severity", "Şiddet", 70),
            ("score", "Risk", 60), ("rationale", "Gerekçe", 430),
        ))
        return tree

    def _build_idea_tab(self) -> ttk.Treeview:
        tab = self.tabs["ideas"]
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        tree = self._tree(tab, (
            ("category", "Kategori", 170), ("suggestion", "Öneri", 360),
            ("benefit", "Beklenen fayda", 220), ("decision", "Karar", 100),
        ))
        actions = ttk.Frame(tab, style="ImpactRoot.TFrame")
        actions.pack(fill="x", pady=(6, 0))
        self._button(actions, "Kabul Et", "Accept",
                     command=lambda: self._decide_suggestion("Kabul edildi"),
                     style="primary.Outline.TButton").pack(side="right")
        self._button(actions, "Reddet", "Reject",
                     command=lambda: self._decide_suggestion("Reddedildi")).pack(side="right", padx=(0, 6))
        tree.bind("<Double-1>", lambda _e: self._idea_detail())
        return tree

    def _build_sources_tab(self) -> None:
        tab = self.tabs["sources"]
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=2)
        tab.rowconfigure(2, weight=1)
        self.edge_tree = self._tree(tab, (
            ("id", "İlişki", 120), ("source", "Kaynak", 120),
            ("relation", "Tür", 120), ("target", "Hedef", 120),
            ("confidence", "Güven", 100), ("document", "Kanıt kaynağı", 180),
        ))
        edge_parent = self.edge_tree.master
        edge_parent.pack_forget()
        edge_parent.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(tab, style="ImpactRoot.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=6)
        self._button(actions, "Yeni Etki Bağlantısı Ekle", "Add Impact Link",
                     command=self._add_edge, style="primary.Outline.TButton").pack(side="left")
        self._button(actions, "Seçili Bağlantıyı Reddet", "Reject Selected Link",
                     command=self._reject_edge).pack(side="left", padx=(6, 0))
        self._button(actions, "Seçili Kanıtı Göster", "Show Selected Evidence",
                     command=self._edge_detail).pack(side="right")
        self.source_text = self._readonly_text(tab)
        self.source_text.grid(row=2, column=0, sticky="nsew")
        self.edge_tree.bind("<Double-1>", lambda _e: self._edge_detail())

    def _set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def refresh_project(self, report: Mapping[str, Any] | None = None,
                        health: Mapping[str, Any] | None = None) -> None:
        raw = report or self.traceability_getter()
        info = dict(self.project_info_getter() or {})
        if health is None and isinstance(info.get("health"), Mapping):
            health = info["health"]
        if not raw:
            self.project_name.set(_clean(info.get("project_name")) or "Belge üretimi bekleniyor")
            self.health_status.set("Belge üretimi gerekli")
            self.health_detail.set("Önce 'Dokümanları Üret' işlemini tamamlayın.")
            self.requirement_combo.configure(values=())
            return
        try:
            applied = integration.apply_overrides(raw)
        except Exception:
            applied = dict(raw)
        self._active_report = applied
        value = dict(health or integration.build_health_summary(applied))
        self.project_name.set(value.get("project_name") or "Proje")
        self.health_status.set(value.get("status") or "Analize hazır")
        self.health_detail.set(
            f"{value.get('node_count', 0)} öğe · {value.get('edge_count', 0)} bağlantı · "
            f"{value.get('unlinked_count', 0)} bağlantısız · "
            f"{value.get('unverified_count', 0)} testsiz · "
            f"{value.get('conflict_count', 0)} çelişki · RAG: {value.get('rag_status', '—')}"
        )
        requirements = sorted(
            _clean(node.get("id")) for node in applied.get("nodes", [])
            if isinstance(node, Mapping)
            and _clean(node.get("node_type")) in REQUIREMENT_TYPES
        )
        self.requirement_combo.configure(values=requirements)
        if self.requirement_id.get() not in requirements:
            self.requirement_id.set("")
        if not self.last_result and not self._trace_in_progress:
            self.work_status.set(
                f"{len(requirements)} gereksinim seçime hazır. Bir gereksinim seçin "
                "veya serbest metin sorunuzu yazın."
            )
        self.parent.after_idle(self.ensure_visible)
        self._refresh_edges()

    def on_traceability_started(self) -> None:
        self._trace_in_progress = True
        self.health_status.set("Taranıyor")
        self.run_button.configure(state=tk.DISABLED)
        self.rescan_button.configure(state=tk.DISABLED)
        self.trace_cancel_button.configure(state=tk.NORMAL)
        self.progress.start(10)
        self.work_status.set("Belge seti ve RAG indeksi arka planda hazırlanıyor...")

    def on_traceability_ready(
        self, report: Mapping[str, Any], health: Mapping[str, Any]
    ) -> None:
        self._trace_in_progress = False
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.rescan_button.configure(state=tk.NORMAL)
        self.trace_cancel_button.configure(state=tk.DISABLED)
        self.refresh_project(report, health)
        self.work_status.set("İzlenebilirlik altyapısı analize hazır.")
        if self.pending_request and self.auto_rerun.get():
            self.parent.after_idle(self._rerun_prepared)

    def on_traceability_failed(self, message: str) -> None:
        self._trace_in_progress = False
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.rescan_button.configure(state=tk.NORMAL)
        self.trace_cancel_button.configure(state=tk.DISABLED)
        self.health_status.set("Tarama uyarısı")
        self.work_status.set(message)

    def _requirement_selected(self, _event: Any = None) -> None:
        report = getattr(self, "_active_report", None) or self.traceability_getter() or {}
        node = _node_index(report).get(self.requirement_id.get())
        if not node:
            return
        self.current_text.delete("1.0", tk.END)
        self.current_text.insert("1.0", _clean(node.get("description")))

    def _question_focus_in(self, _event: Any = None) -> None:
        if self.question_text.get("1.0", tk.END).strip() == self._question_placeholder:
            self.question_text.delete("1.0", tk.END)

    def _question_focus_out(self, _event: Any = None) -> None:
        if not self.question_text.get("1.0", tk.END).strip():
            self.question_text.insert("1.0", self._question_placeholder)

    def _request_from_form(self) -> simulation.ChangeRequest:
        report = getattr(self, "_active_report", None) or self.traceability_getter()
        if not report:
            raise simulation.SimulationError(
                "İzlenebilirlik verisi yok. Önce 'Dokümanları Üret' işlemini tamamlayın."
            )
        question = self.question_text.get("1.0", tk.END).strip()
        if question == self._question_placeholder:
            question = ""
        reason = self.reason_text.get("1.0", tk.END).strip()
        requested_by = self.requested_by.get().strip()
        current = self.current_text.get("1.0", tk.END).strip()
        proposed = self.proposed_text.get("1.0", tk.END).strip()
        selected = self.requirement_id.get().strip()
        assumptions = tuple(
            line.strip() for line in self.assumptions_text.get("1.0", tk.END).splitlines()
            if line.strip()
        )
        if question:
            request = simulation.change_request_from_question(
                report, question, requested_by=requested_by or "Kullanıcı",
                reason=reason or "Kullanıcı simülasyon sorusu",
            )
        else:
            request = simulation.ChangeRequest(
                requirement_id=selected, current_value=current or None,
                proposed_value=proposed or None, reason=reason, requested_by=requested_by,
                change_type=self.change_type.get() or simulation.CHANGE_REQUIREMENT_TEXT,
                assumptions=assumptions, query="",
            )
        request = replace(
            request,
            requirement_id=selected or request.requirement_id,
            current_value=current or request.current_value,
            proposed_value=(
                None if self.change_type.get() == simulation.CHANGE_REQUIREMENT_REMOVE
                else proposed or request.proposed_value
            ),
            reason=reason or request.reason, requested_by=requested_by or request.requested_by,
            change_type=self.change_type.get() or request.change_type,
            assumptions=assumptions or request.assumptions, query=question or request.query,
        )
        return request.validated()

    def start_simulation(
        self, selected_id: str | None = None,
        prepared_request: simulation.ChangeRequest | None = None,
    ) -> None:
        report = getattr(self, "_active_report", None) or self.traceability_getter()
        if not report:
            messagebox.showwarning(
                "İzlenebilirlik Haritası Bulunamadı",
                "Önce 'Dokümanları Üret' işlemini tamamlayın.", parent=self.parent,
            )
            return
        try:
            request = prepared_request or self._request_from_form()
        except simulation.SimulationError as error:
            messagebox.showerror("Simülasyon Girdisi Hatası", str(error), parent=self.parent)
            return
        self._mirror_request_to_form(request)
        self.pending_request = request
        self._worker_token += 1
        token = self._worker_token
        self._cancel_event = threading.Event()
        self.run_button.configure(state=tk.DISABLED)
        self.rerun_button.configure(state=tk.DISABLED)
        self.rescan_button.configure(state=tk.DISABLED)
        self.trace_cancel_button.configure(state=tk.NORMAL)
        self.progress.start(10)
        self.work_status.set("İzlenebilirlik grafiği arka planda analiz ediliyor...")
        use_lm = bool(self.use_lm.get())
        report_copy = dict(report)
        threading.Thread(
            target=self._simulation_worker,
            args=(token, report_copy, request, selected_id, use_lm, self._cancel_event),
            daemon=True,
        ).start()
        self.parent.after(60, self._poll_worker)

    def _mirror_request_to_form(self, request: simulation.ChangeRequest) -> None:
        """Serbest metinden bulunan alanları kullanıcı tarafından düzenlenebilir kılar."""
        if request.requirement_id:
            self.requirement_id.set(request.requirement_id)
        self.change_type.set(request.change_type)
        for widget, value in (
            (self.current_text, request.current_value),
            (self.proposed_text, request.proposed_value),
            (self.reason_text, request.reason),
        ):
            if not widget.get("1.0", tk.END).strip() and value is not None:
                widget.insert("1.0", _clean(value))
        if not self.assumptions_text.get("1.0", tk.END).strip() and request.assumptions:
            self.assumptions_text.insert("1.0", "\n".join(request.assumptions))

    def _simulation_worker(
        self, token: int, report: Mapping[str, Any], request: simulation.ChangeRequest,
        selected_id: str | None, use_lm: bool, cancel_event: threading.Event,
    ) -> None:
        if cancel_event.is_set():
            return
        try:
            base_result = simulation.simulate_change(
                report, request, selected_id=selected_id, use_lm_studio=False
            )
            if not use_lm or base_result.status != "completed":
                self._worker_messages.put(("result", (token, base_result)))
                return
            self._worker_messages.put(("base_result", (token, base_result)))
            if cancel_event.is_set():
                return
            enriched_result = simulation.simulate_change(
                report, request, selected_id=selected_id, use_lm_studio=True
            )
            if not cancel_event.is_set():
                self._worker_messages.put(("result", (token, enriched_result)))
        except Exception as error:
            self._worker_messages.put(("error", (token, str(error))))

    def _poll_worker(self) -> None:
        handled = False
        while True:
            try:
                kind, payload = self._worker_messages.get_nowait()
            except queue.Empty:
                break
            token, value = payload
            if token != self._worker_token or self._cancel_event.is_set():
                continue
            handled = True
            if kind == "error":
                self._simulation_failed(value)
            elif kind == "base_result":
                self._simulation_base_finished(value, token)
            else:
                self._simulation_finished(value)
        if self.run_button.cget("state") == tk.DISABLED:
            self.parent.after(80, self._poll_worker)

    def _simulation_base_finished(
        self, result: simulation.SimulationResult, token: int
    ) -> None:
        """Grafik sonucunu LM Studio tamamlanmadan kullanıcıya gösterir."""
        self.last_result = result
        self.change_package_button.configure(
            state=tk.NORMAL if result.status == "completed" else tk.DISABLED
        )
        if result.status == "selection_required":
            self.progress.stop()
            self.run_button.configure(state=tk.NORMAL)
            self.rescan_button.configure(state=tk.NORMAL)
            self.trace_cancel_button.configure(state=tk.DISABLED)
            self._show_candidates(result)
            return
        report = getattr(self, "_active_report", None) or self.traceability_getter() or {}
        self.views = build_result_views(result, report)
        self._render_result()
        self.result_notebook.select(self.tabs["summary"])
        if self.result_callback:
            self.result_callback(result)
        self.work_status.set(
            "Temel V-Model analizi hazır. LM Studio yorum ve fikirleri bekleniyor "
            "(en fazla 30 saniye)..."
        )
        self.parent.after(30000, lambda value=token: self._lm_wait_timeout(value))

    def _lm_wait_timeout(self, token: int) -> None:
        """LM gecikse bile hazırlanmış temel sonucu ekranda ve kullanılabilir tutar."""
        if token != self._worker_token or self.run_button.cget("state") != tk.DISABLED:
            return
        self._cancel_event.set()
        self._worker_token += 1
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.rescan_button.configure(state=tk.NORMAL)
        self.rerun_button.configure(state=tk.NORMAL if self.pending_request else tk.DISABLED)
        self.trace_cancel_button.configure(state=tk.DISABLED)
        message = (
            "Temel V-Model analizi tamamlandı. LM Studio 30 saniye içinde yanıt "
            "vermediği için yalnızca yapay zekâ fikirleri atlandı."
        )
        self.work_status.set(message)
        if self.last_result:
            self.last_result.lm_status = {
                "available": False, "status": "timeout", "message": message,
            }
            if message not in self.last_result.warnings:
                self.last_result.warnings.append(message)
            report = getattr(self, "_active_report", None) or self.traceability_getter() or {}
            self.views = build_result_views(self.last_result, report)
            self._render_result()
            if self.result_callback:
                self.result_callback(self.last_result)

    def _simulation_failed(self, message: str) -> None:
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.rescan_button.configure(state=tk.NORMAL)
        self.rerun_button.configure(state=tk.NORMAL if self.pending_request else tk.DISABLED)
        self.trace_cancel_button.configure(state=tk.DISABLED)
        self.work_status.set("Simülasyon tamamlanamadı.")
        messagebox.showerror("Etki Simülasyonu Hatası", message, parent=self.parent)

    def _simulation_finished(self, result: simulation.SimulationResult) -> None:
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.rescan_button.configure(state=tk.NORMAL)
        self.rerun_button.configure(state=tk.NORMAL)
        self.trace_cancel_button.configure(state=tk.DISABLED)
        self.last_result = result
        self.change_package_button.configure(
            state=tk.NORMAL if result.status == "completed" else tk.DISABLED
        )
        self.work_status.set(result.message)
        if result.status == "selection_required":
            self._show_candidates(result)
            return
        report = getattr(self, "_active_report", None) or self.traceability_getter() or {}
        self.views = build_result_views(result, report)
        self._render_result()
        self.result_notebook.select(self.tabs["summary"])
        if self.result_callback:
            self.result_callback(result)

    def _show_candidates(self, result: simulation.SimulationResult) -> None:
        dialog = tk.Toplevel(self.parent)
        dialog.title("Gereksinim Seçimi")
        dialog.geometry("720x320")
        tree = self._tree(dialog, (
            ("id", "Kimlik", 140), ("type", "Tür", 160),
            ("score", "Eşleşme", 90), ("title", "Başlık", 300),
        ))
        for candidate in result.candidates[:5]:
            tree.insert("", tk.END, iid=candidate["id"], values=(
                candidate["id"], candidate["node_type"],
                f"%{float(candidate['score']) * 100:.1f}", candidate["title"],
            ))
        def choose() -> None:
            selection = tree.selection()
            if not selection:
                messagebox.showwarning("Aday Seçimi", "Bir gereksinim seçin.", parent=dialog)
                return
            selected = selection[0]
            dialog.destroy()
            self.requirement_id.set(selected)
            self._requirement_selected()
            prepared = replace(self.pending_request, requirement_id=selected)
            self.pending_request = prepared
            self.start_simulation(selected_id=selected, prepared_request=prepared)
        self._button(dialog, "Seçili Adayla Devam Et", "Continue with Selected",
                     command=choose, style="primary.TButton").pack(pady=8)

    def _render_result(self) -> None:
        summary = self.views["summary"]
        self.summary_heading.configure(text=summary["change"])
        risks = "\n".join(
            f"• {item['category']}: {item['impact_level']} "
            f"({item['probability']}×{item['severity']}={item['risk_score']})"
            for item in summary["top_risks"]
        ) or "• Kayıtlı risk bulunamadı."
        self._set_text(self.summary_text, (
            f"Toplam etkilenen öğe: {summary['impact_count']}\n"
            f"Kritik etki: {summary['critical_count']}\n"
            f"Etkilenen belge: {summary['document_count']}\n"
            f"Güncellenecek/yeni test: {summary['test_count']}\n"
            f"Güven seviyesi: %{summary['confidence'] * 100:.1f}\n\n"
            f"EN KRİTİK RİSKLER\n{risks}\n\n"
            f"ÖNERİLEN KARAR\n{summary['decision']}"
        ))
        self._fill_update_tree(self.requirement_tree, self.views["requirements"])
        self._fill_update_tree(self.parts_tree, self.views["parts"])
        self._fill_update_tree(self.tests_tree, self.views["tests"])
        if self.views["test_actions"] and self.tests_tree.exists("__empty__"):
            self.tests_tree.delete("__empty__")
        for index, action in enumerate(self.views["test_actions"]):
            self.tests_tree.insert("", tk.END, iid=f"test-action-{index}", values=(
                action.get("test_id") or "Yeni test",
                "Önerilen test güncellemesi",
                action.get("status") or "Güncelleme gerekli",
                action.get("reason") or "—",
                action.get("required_action") or "Yeni test içeriği kullanıcı tarafından tanımlanmalı.",
            ))
        self.risk_tree.delete(*self.risk_tree.get_children())
        for index, item in enumerate(self.views["risks"]):
            self.risk_tree.insert("", tk.END, iid=f"risk-{index}", values=(
                item["category"], item["impact_level"], item["probability"],
                item["severity"], item["risk_score"], item["rationale"],
            ))
        if not self.views["risks"]:
            self.risk_tree.insert(
                "", tk.END, iid="__empty__",
                values=("Risk kaydı oluşmadı.", "—", "—", "—", "—", "—"),
            )
        self._refresh_ideas()
        self._refresh_edges()
        warnings = "\n".join(f"• {item}" for item in self.views["warnings"]) or "• Yok"
        assumptions = "\n".join(f"• {item}" for item in self.views["assumptions"]) or "• Yok"
        sources = "\n".join(
            f"• {item['id']} · {item['document']} / {item['section']}\n"
            f"  {item['path']}\n  Kanıt: {item['evidence']}"
            for item in self.views["sources"]
        ) or "• Kaynak bulunamadı."
        self._set_text(
            self.source_text,
            f"KAYNAKLAR VE ETKİ YOLLARI\n{sources}\n\n"
            f"VARSAYIMLAR\n{assumptions}\n\nUYARILAR\n{warnings}",
        )
        self._draw_vmodel("left")
        self._draw_vmodel("right")

    def _fill_update_tree(self, tree: ttk.Treeview, rows: list[dict[str, Any]]) -> None:
        tree.delete(*tree.get_children())
        if not rows:
            message = (
                "Bu kategoride etkilenmiş öğe bulunmadı."
                if self.last_result else "Simülasyon bekleniyor."
            )
            tree.insert("", tk.END, iid="__empty__", values=(message, "—", "—", "—", "—"))
            return
        for row in rows:
            tree.insert("", tk.END, iid=row["id"], values=(
                row["id"], row["type"], f"{row['level']} · {row['score']}/100",
                row["current"], row["proposed"],
            ))

    def _draw_vmodel(self, side: str) -> None:
        canvas: tk.Canvas = getattr(self, f"{side}_canvas")
        palette = self.palette_getter()
        canvas.configure(background=palette["surface"], highlightbackground=palette["muted"])
        canvas.delete("all")
        if not self.views:
            canvas.create_text(
                max(canvas.winfo_width(), 680) // 2,
                max(canvas.winfo_height(), 330) // 2,
                text=(
                    "V-Model etki yolları henüz hesaplanmadı.\n"
                    "Soldan bir değişiklik isteği girip ‘Etkiyi Simüle Et’e basın."
                ),
                fill=palette["muted"], font=("Segoe UI", 10), justify="center", width=420,
            )
            return
        self._canvas_items = {
            key: value for key, value in self._canvas_items.items()
            if key not in canvas.find_all()
        }
        width = max(canvas.winfo_width(), 680)
        height = max(canvas.winfo_height(), 330)
        target = self.views["target"]
        center_x = width - 145 if side == "left" else 145
        center_y = height // 2
        target_box = canvas.create_rectangle(
            center_x - 105, center_y - 34, center_x + 105, center_y + 34,
            fill=self.palette_getter()["accent"], outline="", width=0,
        )
        target_text = canvas.create_text(
            center_x, center_y, text=f"{target.get('id') or 'Yeni gereksinim'}\nDEĞİŞİKLİK MERKEZİ",
            fill="#FFFFFF", font=("Segoe UI", 9, "bold"), width=190,
        )
        target_id = _clean(target.get("id"))
        for canvas_item in (target_box, target_text):
            self._canvas_items[canvas_item] = target_id
            canvas.tag_bind(
                canvas_item, "<Button-1>",
                lambda _e, item=target_id, value=side: self._show_detail(item, value),
            )
        rows = self.views[side]
        lanes = list(LEFT_TYPES.values()) if side == "left" else list(RIGHT_TYPES.values())
        lanes = list(dict.fromkeys(lanes))
        x_positions = [
            80 + index * max(105, int((width - 300) / max(1, len(lanes) - 1)))
            for index in range(len(lanes))
        ]
        if side == "right":
            x_positions = [width - value for value in reversed(x_positions)]
        for index, lane in enumerate(lanes):
            x = x_positions[index]
            canvas.create_text(x, 20, text=lane.upper(), fill=palette["muted"],
                               font=("Consolas", 8, "bold"), width=110)
            lane_items = [item for item in rows if item["lane"] == lane]
            for offset, item in enumerate(lane_items[:4]):
                y = 72 + offset * 62
                color = impact_color(item["level"], item["confidence"])
                if side == "left":
                    canvas.create_line(x + 52, y, center_x - 106, center_y,
                                       fill=color, width=2, arrow=tk.LAST)
                else:
                    canvas.create_line(center_x + 106, center_y, x - 52, y,
                                       fill=color, width=2, arrow=tk.LAST)
                box = canvas.create_rectangle(
                    x - 52, y - 20, x + 52, y + 20, fill=color, outline="",
                )
                label = canvas.create_text(
                    x, y, text=f"{item['id']}\n{item['level']} {item['score']}",
                    fill="#1F2329" if item["level"] == "Orta" else "#FFFFFF",
                    font=("Segoe UI", 8, "bold"), width=96,
                )
                for canvas_item in (box, label):
                    self._canvas_items[canvas_item] = item["id"]
                    canvas.tag_bind(
                        canvas_item, "<Button-1>",
                        lambda _e, item_id=item["id"], value=side: self._show_detail(item_id, value),
                    )
        canvas.create_text(
            10, height - 10, anchor="sw",
            text="Kırmızı Kritik · Turuncu Yüksek · Sarı Orta · Yeşil Düşük · Gri Belirsiz",
            fill=palette["muted"], font=("Segoe UI", 8),
        )

    def _show_detail(self, item_id: str, side: str | None = None) -> None:
        if not item_id:
            return
        node = self.views.get("nodes", {}).get(item_id, {})
        impact = self.views.get("impacts", {}).get(item_id)
        request = self.last_result.change_request if self.last_result else None
        current = _clean(node.get("description"))
        proposed = (
            _clean(request.proposed_value)
            if request and item_id == request.requirement_id
            else "Otomatik yazılmadı; mühendislik incelemesi gerekli."
        )
        if impact:
            reason, path, evidence = (
                impact.rationale, impact.traceability_path.display_path, impact.source_evidence
            )
        else:
            reason, path, evidence = "Değişiklik başlangıç noktası.", item_id, _clean(node.get("evidence_text"))
        value = (
            f"{item_id} — {_clean(node.get('title'))}\n"
            f"Etki gerekçesi: {reason}\n"
            f"Kaynak: {_clean(node.get('source_document')) or '—'} / "
            f"{_clean(node.get('section') or node.get('page_section')) or '—'}\n"
            f"İzlenebilirlik yolu: {path}\n\n"
            f"Mevcut içerik:\n{current or '—'}\n\nÖnerilen değişiklik:\n{proposed or '—'}\n\n"
            f"Kaynak kanıtı:\n{evidence or '—'}"
        )
        if side:
            self._set_text(getattr(self, f"{side}_detail"), value)
        else:
            dialog = tk.Toplevel(self.parent)
            dialog.title(f"Etki Ayrıntısı · {item_id}")
            dialog.geometry("720x480")
            text = self._readonly_text(dialog)
            text.pack(fill="both", expand=True, padx=12, pady=12)
            self._set_text(text, value)

    def _tree_detail(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if selection and selection[0] != "__empty__":
            if tree is self.parts_tree and self.hardware_detail_callback:
                self.hardware_detail_callback(selection[0])
                return
            self._show_detail(selection[0])

    def _refresh_ideas(self) -> None:
        self.idea_tree.delete(*self.idea_tree.get_children())
        if not self.views.get("ideas"):
            message = (
                "Mühendislik önerisi bulunmadı."
                if self.last_result else "Simülasyon bekleniyor."
            )
            self.idea_tree.insert(
                "", tk.END, iid="__empty__", values=(message, "—", "—", "—")
            )
            return
        for item in self.views.get("ideas", []):
            self.idea_tree.insert("", tk.END, iid=item["suggestion_id"], values=(
                item["category"], item["suggestion"], item["expected_benefit"], item["decision"],
            ))

    def _idea_detail(self) -> None:
        selection = self.idea_tree.selection()
        if not selection:
            return
        item = next(
            (row for row in self.views.get("ideas", []) if row["suggestion_id"] == selection[0]), None
        )
        if not item:
            return
        messagebox.showinfo(
            "Mühendislik Önerisi — Kullanıcı Onayı Gerekli",
            f"{item['suggestion']}\n\nGerekçe: {item['rationale']}\n"
            f"Beklenen fayda: {item['expected_benefit']}\n"
            f"Yeni risk: {item['new_risk']}\n"
            f"Gerekli doğrulama: {item['required_verification']}\n"
            f"Kaynak/varsayım: {item['source_or_assumption']}",
            parent=self.parent,
        )

    def _decide_suggestion(self, decision: str) -> None:
        selection = self.idea_tree.selection()
        if not selection or selection[0] == "__empty__":
            messagebox.showwarning("Öneri Seçimi", "Bir mühendislik önerisi seçin.", parent=self.parent)
            return
        report = getattr(self, "_active_report", None)
        if not report:
            return
        try:
            overrides = integration.set_suggestion_decision(report, selection[0], decision)
        except integration.IntegrationError as error:
            messagebox.showerror("Öneri Kararı", str(error), parent=self.parent)
            return
        report.setdefault("user_overrides", {})["suggestion_decisions"] = overrides["suggestion_decisions"]
        for item in self.views.get("ideas", []):
            if item["suggestion_id"] == selection[0]:
                item["decision"] = decision
        self._refresh_ideas()

    def _refresh_edges(self) -> None:
        if not hasattr(self, "edge_tree"):
            return
        report = getattr(self, "_active_report", None) or self.traceability_getter() or {}
        self.edge_tree.delete(*self.edge_tree.get_children())
        for edge in report.get("edges", []):
            if not isinstance(edge, Mapping) or not _clean(edge.get("id")):
                continue
            self.edge_tree.insert("", tk.END, iid=_clean(edge["id"]), values=(
                edge["id"], edge.get("source_id"), edge.get("relationship_type"),
                edge.get("target_id"), edge.get("confidence_level"),
                edge.get("source_document") or edge.get("evidence_text"),
            ))

    def _add_edge(self) -> None:
        report = getattr(self, "_active_report", None)
        if not report:
            messagebox.showwarning("İzlenebilirlik", "Önce belge üretimini tamamlayın.", parent=self.parent)
            return
        source = simpledialog.askstring("Yeni Etki Bağlantısı", "Kaynak öğe kimliği:", parent=self.parent)
        if source is None:
            return
        target = simpledialog.askstring("Yeni Etki Bağlantısı", "Hedef öğe kimliği:", parent=self.parent)
        if target is None:
            return
        relation = simpledialog.askstring(
            "Yeni Etki Bağlantısı",
            "İlişki türü:\n" + ", ".join(integration.RELATION_LABELS_TR),
            parent=self.parent,
        )
        if relation is None:
            return
        try:
            updated, _edge = integration.add_manual_edge(report, source, target, relation)
        except integration.IntegrationError as error:
            messagebox.showerror("Bağlantı Eklenemedi", str(error), parent=self.parent)
            return
        self._replace_report(updated)
        self.work_status.set("Kullanıcı bağlantısı eklendi; analiz yeniden çalıştırılabilir.")

    def _reject_edge(self) -> None:
        selection = self.edge_tree.selection()
        if not selection:
            messagebox.showwarning("Bağlantı Seçimi", "Reddedilecek bağlantıyı seçin.", parent=self.parent)
            return
        if not messagebox.askyesno(
            "Bağlantıyı Reddet",
            "Seçili bağlantı kaynak veriden silinmeden analiz dışında bırakılsın mı?",
            parent=self.parent,
        ):
            return
        try:
            updated = integration.reject_edge(getattr(self, "_active_report", {}), selection[0])
        except integration.IntegrationError as error:
            messagebox.showerror("Bağlantı Reddedilemedi", str(error), parent=self.parent)
            return
        self._replace_report(updated)
        self.work_status.set("Bağlantı reddedildi; analiz yeniden çalıştırılabilir.")

    def _replace_report(self, report: Mapping[str, Any]) -> None:
        self._active_report = dict(report)
        if self.traceability_update_callback:
            self.traceability_update_callback(self._active_report)
        self.refresh_project(self._active_report)

    def _edge_detail(self) -> None:
        selection = self.edge_tree.selection()
        if not selection:
            return
        report = getattr(self, "_active_report", {})
        edge = next(
            (item for item in report.get("edges", []) if _clean(item.get("id")) == selection[0]), None
        )
        if edge:
            self._set_text(self.source_text, (
                f"İLİŞKİ: {edge.get('id')}\n"
                f"YOL: {edge.get('source_id')} → {edge.get('relationship_type')} → {edge.get('target_id')}\n"
                f"GÜVEN: {edge.get('confidence_level')} · {edge.get('confidence')}\n"
                f"KAYNAK: {edge.get('source_document') or '—'}\n"
                f"KANIT: {edge.get('evidence_text') or '—'}\n"
                f"YÖNTEM: {edge.get('derivation_method') or '—'}"
            ))

    def _rerun(self) -> None:
        self.start_simulation()

    def _rerun_prepared(self) -> None:
        if self.pending_request:
            self.start_simulation(prepared_request=self.pending_request)

    def _rescan(self) -> None:
        if not self.rescan_callback:
            messagebox.showwarning("Yeniden Tarama", "Yeniden tarama bağlantısı kullanılamıyor.", parent=self.parent)
            return
        self.on_traceability_started()
        self.rescan_callback(False)

    def _cancel_all(self) -> None:
        self._cancel_event.set()
        self._worker_token += 1
        if self._trace_in_progress and self.cancel_trace_callback:
            self.cancel_trace_callback()
        self._trace_in_progress = False
        self.progress.stop()
        self.run_button.configure(state=tk.NORMAL)
        self.rescan_button.configure(state=tk.NORMAL)
        self.rerun_button.configure(state=tk.NORMAL if self.pending_request else tk.DISABLED)
        self.trace_cancel_button.configure(state=tk.DISABLED)
        self.work_status.set("İşlem kullanıcı tarafından iptal edildi.")

    def refresh_language(self) -> None:
        for widget, tr, en in self._translatable:
            try:
                widget.configure(text=self._tr(tr, en))
            except tk.TclError:
                pass
        for key, tr, en in RESULT_TAB_TITLES:
            self.result_notebook.tab(self.tabs[key], text=self._tr(tr, en))

    def apply_theme(self) -> None:
        palette = self.palette_getter()
        dark = palette["bg"].lower() == "#1f2329"
        border = "#3D4550" if dark else "#D8DEE5"
        selected = "#234B72" if dark else "#D9EAFB"
        for widget in (
            self.question_text, self.current_text, self.proposed_text,
            self.reason_text, self.assumptions_text, self.summary_text,
            self.left_detail, self.right_detail, self.source_text,
        ):
            widget.configure(
                background=palette["entry_bg"], foreground=palette["entry_fg"],
                insertbackground=palette["fg"], highlightbackground=border,
                highlightcolor=palette["accent"],
            )
        self.form_canvas.configure(background=palette["surface"])
        for canvas in (self.left_canvas, self.right_canvas):
            canvas.configure(background=palette["surface"], highlightbackground=border)
        for tree in (
            self.requirement_tree, self.parts_tree, self.tests_tree,
            self.risk_tree, self.idea_tree, self.edge_tree,
        ):
            tree.tag_configure("selected", background=selected)


__all__ = ["RequirementSimulationPanel", "build_result_views", "impact_color"]
