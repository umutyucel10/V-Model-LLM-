# -*- coding: utf-8 -*-
"""Etki Analizi güvenli değişiklik paketi karar ve onay penceresi."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Mapping

from etki_analizi_degisim_paketi import (
    ApplicationResult,
    ChangePackage,
    ChangePackageError,
    DECISION_ACCEPT,
    DECISION_DEFER,
    DECISION_EDIT,
    DECISION_REJECT,
    mark_explicit_approval,
    save_change_package,
    update_proposal,
)
from etki_analizi_degisim_raporlama import (
    export_change_package_excel,
    export_change_package_pdf,
)


class ChangeApprovalDialog:
    """Mevcut/önerilen redline görünümü ve iki aşamalı uygulama kapısı."""

    def __init__(
        self,
        parent: tk.Misc,
        package: ChangePackage,
        *,
        apply_callback: Callable[
            [ChangePackage, Callable[[ApplicationResult], None], Callable[[str], None]],
            None,
        ] | None = None,
    ) -> None:
        self.parent = parent
        self.package = package
        self.apply_callback = apply_callback
        self.last_application: ApplicationResult | None = None
        self._proposal_by_iid: dict[str, str] = {}
        self.actor = tk.StringVar(value=package.approval_actor or "Sistem Mühendisliği")
        self.explicit_approval = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Taslak · Kullanıcı kararları bekleniyor")
        self.window = tk.Toplevel(parent)
        self.window.title(f"Değişiklik Paketi · {package.change_id}")
        self.window.geometry("1280x790")
        self.window.minsize(980, 650)
        self.window.transient(parent.winfo_toplevel())
        self._build()
        self._populate()
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)
        header = ttk.Frame(self.window, padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text="Güvenli Belge Güncelleme Paketi",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=f"{self.package.project_name} · {self.package.change_id}",
            foreground="#5C666D",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(header, textvariable=self.status).grid(row=0, column=1, rowspan=2, sticky="e")

        rail = ttk.Frame(self.window, padding=(16, 0, 16, 10))
        rail.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            rail.columnconfigure(column, weight=1)
        stages = (
            ("1", "Taslak", "Özgün belgeler korunur"),
            ("2", "Kullanıcı kararı", "Her satır tek tek değerlendirilir"),
            ("3", "Sürümlendi", "Yedek + yeni sürüm"),
            ("4", "Son kontrol", "İzler ve etkiler yeniden taranır"),
        )
        for column, (number, title, detail) in enumerate(stages):
            item = ttk.Frame(rail, padding=8, relief="solid", borderwidth=1)
            item.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0))
            ttk.Label(item, text=number, font=("Consolas", 10, "bold"), foreground="#17365D").pack(side="left", padx=(0, 8))
            text = ttk.Frame(item)
            text.pack(side="left", fill="x", expand=True)
            ttk.Label(text, text=title, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Label(text, text=detail, foreground="#5C666D").pack(anchor="w")

        split = ttk.Panedwindow(self.window, orient=tk.VERTICAL)
        split.grid(row=2, column=0, sticky="nsew", padx=16)
        ledger = ttk.Frame(split)
        detail = ttk.Frame(split)
        split.add(ledger, weight=3)
        split.add(detail, weight=2)
        ledger.columnconfigure(0, weight=1)
        ledger.rowconfigure(0, weight=1)
        columns = (
            ("decision", "Karar", 90), ("category", "Kategori", 155),
            ("document", "Belge", 155), ("section", "Bölüm", 130),
            ("requirement", "Kimlik", 105), ("current", "Mevcut içerik", 250),
            ("proposed", "Önerilen içerik", 270), ("path", "Etki yolu", 230),
            ("risk", "Risk", 70),
        )
        self.tree = ttk.Treeview(
            ledger, columns=[key for key, _title, _width in columns],
            show="headings", selectmode="browse",
        )
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=60, stretch=True, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(ledger, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(ledger, orient="horizontal", command=self.tree.xview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.tag_configure("accept", background="#D9EAD3")
        self.tree.tag_configure("reject", background="#F4CCCC")
        self.tree.tag_configure("pending", background="#FFF2CC")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)

        detail.columnconfigure(0, weight=1)
        detail.columnconfigure(1, weight=1)
        detail.rowconfigure(1, weight=1)
        ttk.Label(detail, text="MEVCUT İÇERİK", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(8, 4))
        ttk.Label(detail, text="ÖNERİLEN İÇERİK", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(8, 4))
        self.current_text = tk.Text(detail, wrap="word", height=8, relief="solid", borderwidth=1, padx=8, pady=6, state=tk.DISABLED, font=("Segoe UI", 9))
        self.proposed_text = tk.Text(detail, wrap="word", height=8, relief="solid", borderwidth=1, padx=8, pady=6, state=tk.DISABLED, font=("Segoe UI", 9))
        self.current_text.grid(row=1, column=0, sticky="nsew")
        self.proposed_text.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        self.evidence = ttk.Label(detail, text="Bir öneri seçin.", wraplength=1120, foreground="#5C666D")
        self.evidence.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        decision_bar = ttk.Frame(detail)
        decision_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(decision_bar, text="Kabul et", command=lambda: self._decide(DECISION_ACCEPT)).pack(side="left")
        ttk.Button(decision_bar, text="Reddet", command=lambda: self._decide(DECISION_REJECT)).pack(side="left", padx=(6, 0))
        ttk.Button(decision_bar, text="Düzenle", command=self._edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(decision_bar, text="Ertele", command=lambda: self._decide(DECISION_DEFER)).pack(side="left", padx=(6, 0))
        ttk.Label(decision_bar, text="Öneri metni yalnızca ‘Düzenle’ kararıyla değiştirilebilir.", foreground="#5C666D").pack(side="right")

        footer = ttk.Frame(self.window, padding=(16, 10, 16, 14))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        reports = ttk.Frame(footer)
        reports.grid(row=0, column=0, rowspan=2, sticky="w")
        ttk.Button(reports, text="PDF Raporu Kaydet", command=self._save_pdf).pack(side="left")
        ttk.Button(reports, text="Excel Raporu Kaydet", command=self._save_excel).pack(side="left", padx=(6, 0))
        approval = ttk.Frame(footer)
        approval.grid(row=0, column=1, sticky="e")
        ttk.Label(approval, text="Onayı veren kişi/rol:").pack(side="left")
        actor_entry = ttk.Entry(approval, textvariable=self.actor, width=24)
        actor_entry.pack(side="left", padx=(6, 10))
        actor_entry.bind("<KeyRelease>", lambda _event: self._refresh_gate())
        self.approval_check = ttk.Checkbutton(
            approval,
            variable=self.explicit_approval,
            command=self._refresh_gate,
            text="Özgünlerin korunacağını ve yalnızca kabul edilenlerin yeni sürüme yazılacağını onaylıyorum",
        )
        self.approval_check.pack(side="left")
        self.apply_button = ttk.Button(
            footer, text="Onaylanan Değişiklikleri Uygula",
            command=self._apply, state=tk.DISABLED,
        )
        self.apply_button.grid(row=1, column=1, sticky="e", pady=(8, 0))
        ttk.Button(footer, text="Kapat", command=self.close).grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(8, 0))

    def _populate(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._proposal_by_iid.clear()
        for index, item in enumerate(self.package.proposals):
            iid = f"proposal-{index}"
            self._proposal_by_iid[iid] = item.proposal_id
            tag = "accept" if item.decision == DECISION_ACCEPT else "reject" if item.decision == DECISION_REJECT else "pending"
            self.tree.insert("", "end", iid=iid, values=(
                item.decision, item.category, item.document_name, item.section,
                item.requirement_id, item.current_text, item.proposed_text,
                item.impact_path, item.risk_level,
            ), tags=(tag,))
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
            self._show_selected()
        self._refresh_gate()

    def _selected(self) -> Any:
        selection = self.tree.selection()
        if not selection:
            return None
        proposal_id = self._proposal_by_iid.get(selection[0])
        return next((item for item in self.package.proposals if item.proposal_id == proposal_id), None)

    @staticmethod
    def _set_text(widget: tk.Text, value: str, *, editable: bool = False) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        if not editable:
            widget.configure(state=tk.DISABLED)

    def _show_selected(self, _event: Any = None) -> None:
        item = self._selected()
        if not item:
            return
        self._set_text(self.current_text, item.current_text)
        self._set_text(self.proposed_text, item.proposed_text)
        self.evidence.configure(text=f"Gerekçe: {item.rationale}   |   Kaynak etki yolu: {item.impact_path or '-'}   |   Risk: {item.risk_level}")

    def _decide(self, decision: str) -> None:
        item = self._selected()
        if not item:
            messagebox.showwarning("Değişiklik Paketi", "Önce bir öneri seçin.", parent=self.window)
            return
        try:
            update_proposal(self.package, item.proposal_id, decision)
            save_change_package(self.package)
        except ChangePackageError as error:
            messagebox.showerror("Değişiklik Paketi", str(error), parent=self.window)
            return
        self.explicit_approval.set(False)
        self.status.set("Kullanıcı kararları güncellendi · açık onay bekleniyor")
        self._populate()

    def _edit_selected(self) -> None:
        item = self._selected()
        if not item:
            messagebox.showwarning("Değişiklik Paketi", "Önce bir öneri seçin.", parent=self.window)
            return
        self._set_text(self.proposed_text, item.proposed_text, editable=True)
        self.proposed_text.focus_set()
        editor = ttk.Frame(self.proposed_text.master)
        editor.grid(row=4, column=1, sticky="e", pady=(4, 0))
        def save_edit() -> None:
            try:
                update_proposal(
                    self.package, item.proposal_id, DECISION_EDIT,
                    proposed_text=self.proposed_text.get("1.0", tk.END).strip(),
                )
                save_change_package(self.package)
            except ChangePackageError as error:
                messagebox.showerror("Değişiklik Paketi", str(error), parent=self.window)
                return
            editor.destroy()
            self.explicit_approval.set(False)
            self._populate()
        ttk.Button(editor, text="Düzenlemeyi Kaydet", command=save_edit).pack(side="right")
        ttk.Button(editor, text="Vazgeç", command=lambda: (editor.destroy(), self._show_selected())).pack(side="right", padx=(0, 6))

    def _refresh_gate(self) -> None:
        accepted = any(item.decision == DECISION_ACCEPT for item in self.package.proposals)
        ready = accepted and self.explicit_approval.get() and bool(self.actor.get().strip()) and self.apply_callback is not None
        self.apply_button.configure(state=tk.NORMAL if ready else tk.DISABLED)

    def _apply(self) -> None:
        accepted = [item for item in self.package.proposals if item.decision == DECISION_ACCEPT]
        if not messagebox.askyesno(
            "Açık Uygulama Onayı",
            f"{len(accepted)} kabul edilmiş öneri yeni bir belge sürümüne uygulanacak.\n\n"
            "Özgün belgeler korunacak, yedek ve değişiklik kaydı oluşturulacak. "
            "Son kontroller geçmezse yeni sürüm yayımlanmayacak.\n\nDevam edilsin mi?",
            parent=self.window,
        ):
            return
        try:
            mark_explicit_approval(self.package, self.actor.get())
            save_change_package(self.package)
        except ChangePackageError as error:
            messagebox.showerror("Değişiklik Paketi", str(error), parent=self.window)
            return
        self.apply_button.configure(state=tk.DISABLED)
        self.approval_check.configure(state=tk.DISABLED)
        self.status.set("Yeni sürüm hazırlanıyor · özgün belgeler kilitli")
        if self.apply_callback:
            self.apply_callback(self.package, self.application_completed, self.application_failed)

    def application_completed(self, result: ApplicationResult) -> None:
        self.last_application = result
        self.package.status = result.status
        self.status.set(f"v{result.new_version:04d} sürümlendi · son kontrol tamamlandı")
        closure = result.closure_summary
        messagebox.showinfo(
            "Değişiklik Paketi Tamamlandı",
            f"Yeni sürüm: v{result.new_version:04d}\n"
            f"Değişen öğe: {len(result.modified_item_ids)}\n"
            f"Yeni öğe: {len(result.added_item_ids)}\n"
            f"Çözülen / devam eden etki: {closure.get('resolved_count', 0)} / {closure.get('continuing_count', 0)}\n"
            f"Yeni çelişki: {closure.get('new_conflict_count', 0)}\n\n"
            f"Sürüm klasörü:\n{result.version_directory}",
            parent=self.window,
        )

    def application_failed(self, message: str) -> None:
        self.package.approval_confirmed = False
        self.explicit_approval.set(False)
        self.approval_check.configure(state=tk.NORMAL)
        self.status.set("Uygulama durduruldu · özgün belgeler korundu")
        self._refresh_gate()
        messagebox.showerror(
            "Değişiklik Uygulanamadı",
            f"{message}\n\nÖzgün belgelerde değişiklik yapılmadı.",
            parent=self.window,
        )

    def _show_report_error(self, report_name: str, error: Exception) -> None:
        if isinstance(error, PermissionError) or getattr(error, "errno", None) in {13, 32}:
            detail = (
                "Dosyaya yazılamadı. Dosya başka bir programda açık olabilir; "
                "dosyayı kapatıp yeniden deneyin."
            )
        else:
            detail = f"Rapor kaydedilemedi: {error}"
        messagebox.showerror(report_name, detail, parent=self.window)

    def _save_pdf(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.window, title="Etki Analizi PDF Raporunu Kaydet",
            defaultextension=".pdf", filetypes=(("PDF dosyası", "*.pdf"),),
            initialfile=f"{self.package.change_id}_etki_analizi.pdf",
        )
        if not path:
            return
        try:
            export_change_package_pdf(
                path, self.package,
                after_traceability=(self.last_application.post_traceability if self.last_application else None),
                closure_summary=(self.last_application.closure_summary if self.last_application else None),
            )
        except Exception as error:
            self._show_report_error("PDF Raporu", error)
            return
        messagebox.showinfo("PDF Raporu", f"Rapor kaydedildi:\n{Path(path).resolve()}", parent=self.window)

    def _save_excel(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.window, title="Etki Analizi Excel Raporunu Kaydet",
            defaultextension=".xlsx", filetypes=(("Excel çalışma kitabı", "*.xlsx"),),
            initialfile=f"{self.package.change_id}_etki_analizi.xlsx",
        )
        if not path:
            return
        try:
            export_change_package_excel(
                path, self.package,
                after_traceability=(self.last_application.post_traceability if self.last_application else None),
                closure_summary=(self.last_application.closure_summary if self.last_application else None),
            )
        except Exception as error:
            self._show_report_error("Excel Raporu", error)
            return
        messagebox.showinfo("Excel Raporu", f"Rapor kaydedildi:\n{Path(path).resolve()}", parent=self.window)

    def close(self) -> None:
        try:
            save_change_package(self.package)
        except Exception:
            pass
        self.window.destroy()


__all__ = ["ChangeApprovalDialog"]
