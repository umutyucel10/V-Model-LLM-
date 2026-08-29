# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — Arayüz.py'nin bölünmüş
parçalarından biri. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 3.
"""

import csv
import os
import sys

# Windows konsolu (cp1254) emoji/Unicode karakterleri basamadığı için
# çıktıyı UTF-8'e zorla; aksi halde print(...) ifadeleri çökertir.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import threading
import traceback
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.style import Style
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont 
from reportlab.pdfbase import pdfmetrics
from openpyxl import Workbook
import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings
from app_identity import (
    APP_NAME, ICON_RELATIVE_PATH, apply_app_identity,
    prepare_process_identity, resource_path,
)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import tid_generator_logic
    import sgd_generator_logic
    import stt_generator_logic
    import dgöygö_generator_logic
    import kmtd_generator_logic
    import sitet_generator_logic
    import alt_sistem_test_logic
    import dtet_ytet_generator_logic
    import hardware_list_logic
    import hardware_generator_logic
    import hardware_list_ui
    import donanim_kartlari_gorsel
    import donanim_kartlari_ui
    import donanim_kartlari_yonetim
    import etki_analizi_ui
    import etki_analizi_izlenebilirlik
    import etki_analizi_entegrasyon
    import etki_analizi_simulasyon
    import etki_analizi_degisim_paketi
    import etki_analizi_degisim_raporlama
    import donanim_kartlari_algilama
    import mimari_cerceve_ui
    import text_cleanup
    import html_generation
    import pdf_extraction
except ImportError as e:
    messagebox.showerror(
        "Modül Hatası",
        f"Gerekli bir modül yüklenemedi: {e}\nLütfen programı yeniden kurun veya bağımlılıkları kontrol edin."
    )
    sys.exit(1)

from .yardimcilar import pre_process_files, start1_time

class _PencereMixin:
    FILE_HINT = "Sürükle-bırak ya da '...' ile seç"

    def __init__(self, master):
        self.master = master
        self._app_icon = apply_app_identity(master)
        master.title(APP_NAME)
        master.geometry("1130x950")
                                                            
        self.style = Style(theme="litera")
        target_bg = self.style.colors.light
        
        self.master.configure(bg=target_bg)
        self.style.configure("TLabel", background=target_bg)
        self.style.configure("TCheckbutton", background=target_bg)
        self.style.configure("secondary.TLabel", background=target_bg)
        self.style.configure("TFrame", background=target_bg) 

        self.dark_blue = "#0052cc"
        self.style.configure("primary.TLabel", foreground=self.dark_blue, background=target_bg)
        self.style.configure("primary.TButton", background=self.dark_blue, foreground="white")
        self.style.configure("primary.Outline.TButton", foreground=self.dark_blue, bordercolor=self.dark_blue)
        self.style.configure("primary.TCombobox", fieldbackground=target_bg, background=target_bg, foreground=self.dark_blue)
        self.style.configure("success.TButton", background=self.style.colors.success, foreground="white")
        self.style.configure("Thin.Vertical.TScrollbar", width=8, arrowsize=10)
        self.style.configure("Black.TCheckbutton", foreground="black", background=target_bg)
        
        try:
            self.style.configure("info.TButton", background="#17a2b8", foreground="white")
        except:
            pass

        self.file_paths = []
        self.generated_document_paths = []
        self.template_file_path = None
        self.entry_widgets = {}
        
        self.last_generated_output = ""   
        self.raw_output_cache = ""        
        
        self.tree_data = {}
        self.flat_data = {}
        self.hardware_data = {}
        self.hardware_workspace = None
        self.hardware_cards_workspace = None
        self.impact_analysis_workspace = None
        self.mimari_cerceve_workspace = None
        self._hardware_generation_token = 0
        self._traceability_generation_token = 0
        self._hardware_catalog_generation_token = 0
        self._traceability_cancel_event = threading.Event()
        self._architecture_generation_state = "ready"
        self._architecture_generation_detail = ""
        self.last_traceability_report = None
        self.last_traceability_health = None
        self.last_hardware_catalog = None
        self.last_hardware_catalog_status = None
        self.last_hardware_impact_result = None
        self.checkbox_vars = {}

        # --- Dil (TR/EN) + Tema (aydınlık/karanlık) altyapısı ---
        self.lang = "tr"                 # "tr" | "en"
        self.dark = False                # aydınlık başla
        self._i18n = []                  # dil değişiminde yeniden etiketlenecek (widget, tr, en)
        self._theme_labels = []          # tema değişiminde yeniden renklenecek düz ttk.Label'lar
        self._theme_texts = []           # tema değişiminde yeniden renklenecek tk.Text/Canvas
        self._light_theme = "litera"
        self._dark_theme = "darkly"
        
        self.last_tid_list = []
        self.last_sgd_list = []
        self.last_stt_list = []
        self.last_dgoygo_list = []
        self.last_sitet_list = []
        self.last_alt_sistem_test_list = []
        self.last_dtet_ytet_list = []

        # --- Sürükle-Bırak (Drag & Drop) desteği: tkinterdnd2 varsa etkinleştir ---
        # Yoksa uygulama yine çalışır, sadece "..." ile tıklayarak dosya seçilir.
        self._dnd_enabled = False
        try:
            from tkinterdnd2 import TkinterDnD
            TkinterDnD._require(master)
            self._dnd_enabled = True
        except Exception as _dnd_err:
            print(f"Sürükle-bırak devre dışı (tkinterdnd2 yok): {_dnd_err}")

        # --- Ana yatay yerleşim: SOLDA mevcut form (kaydırılabilir), SAĞDA Copilot sohbet ---
        left_container = ttk.Frame(master, style="light")
        left_container.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(left_container, bg=target_bg, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=self.canvas.yview,
                                       style="Thin.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner_frame = ttk.Frame(self.canvas, padding=20, style="light")
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw")
        self.inner_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.master.bind("<MouseWheel>", self._on_mousewheel)

        self._create_header()
        self._create_input_widgets(self.inner_frame)
        self._create_output_widgets(self.inner_frame)
        self._create_buttons(self.inner_frame)

        # SAĞ TARAF: Doküman Copilot sohbet paneli
        self._create_chat_panel(master, target_bg)

    # ══════════════════════════════════════════════════════════════════
    #  DİL (TR/EN) + TEMA (Aydınlık/Karanlık) yardımcıları
    # ══════════════════════════════════════════════════════════════════
    def _t(self, tr, en):
        """Aktif dile göre metin döndürür (Türkçe karakterler kaynak string'de UTF-8)."""
        return tr if self.lang == "tr" else en

    def _L(self, parent, tr, en, translate=True, theme=True, **kw):
        """Çevrilebilir + tema-duyarlı ttk.Label oluşturur ve kaydeder."""
        w = ttk.Label(parent, text=(tr if self.lang == "tr" else en), **kw)
        if translate:
            self._i18n.append((w, tr, en))
        if theme and "foreground" in kw:
            # vurgu (başlık/mavi) mı yoksa gövde metni mi — oluşturma anında sabitle
            is_accent = (kw.get("foreground") == self.dark_blue)
            self._theme_labels.append((w, is_accent))
        return w

    def _reg_btn(self, widget, tr, en):
        """Bir butonu dil değişiminde yeniden etiketlenmek üzere kaydeder."""
        self._i18n.append((widget, tr, en))
        return widget

    def _toggle_lang(self):
        self.lang = "en" if self.lang == "tr" else "tr"
        for w, tr, en in self._i18n:
            try:
                w.config(text=(tr if self.lang == "tr" else en))
            except Exception:
                pass
        if hasattr(self, "lang_btn"):
            self.lang_btn.config(text=("EN" if self.lang == "tr" else "TR"))
        # Chat karşılama metni (Text kutusu içinde) — henüz sohbet başlamadıysa yeniden yaz
        if getattr(self, "_chat_has_convo", True) is False and hasattr(self, "chat_history"):
            self.chat_history.config(state=tk.NORMAL)
            self.chat_history.delete("1.0", tk.END)
            self.chat_history.config(state=tk.DISABLED)
            self._chat_append(self._t(*self._chat_greeting), "info")
        workspace = getattr(self, "hardware_workspace", None)
        if workspace and workspace.exists:
            workspace.refresh_language()
        cards_workspace = getattr(self, "hardware_cards_workspace", None)
        if cards_workspace and cards_workspace.exists:
            cards_workspace.refresh_language()
        impact_workspace = getattr(self, "impact_analysis_workspace", None)
        if impact_workspace and impact_workspace.exists:
            impact_workspace.refresh_language()
        architecture_workspace = getattr(self, "mimari_cerceve_workspace", None)
        if architecture_workspace and architecture_workspace.exists:
            architecture_workspace.refresh_language()

    def _toggle_theme(self):
        self.dark = not self.dark
        self._apply_theme()
        if hasattr(self, "theme_btn"):
            self.theme_btn.config(text=("☀" if self.dark else "🌙"))

    # Elle palet (ttkbootstrap theme_use scrollbar element'ini çakıştırdığı için kullanılmaz)
    _PALETTE = {
        "light": dict(bg="#F5F6F7", surface="#FFFFFF", fg="#222222", muted="#5C666D",
                      entry_bg="#FFFFFF", entry_fg="#222222", accent="#0052cc"),
        "dark":  dict(bg="#1F2329", surface="#2B303A", fg="#E4E6EA", muted="#95A0A8",
                      entry_bg="#2B303A", entry_fg="#E8EAED", accent="#5AA0F2"),
    }

    def _apply_theme(self):
        """Aydınlık/karanlık tema uygular — kendi paletiyle (ttk theme_use kullanmaz)."""
        p = self._PALETTE["dark" if self.dark else "light"]
        bg, fg, entry_bg, entry_fg, muted = p["bg"], p["fg"], p["entry_bg"], p["entry_fg"], p["muted"]
        self.dark_blue = p["accent"]

        # Arka planı olan tüm özel stiller (kod her yerde style="light" kullanıyor)
        for st in ("TLabel", "light.TLabel", "light.TFrame", "TFrame",
                   "TCheckbutton", "Black.TCheckbutton"):
            try:
                self.style.configure(st, background=bg)
            except Exception:
                pass
        self.style.configure("light.TLabel", foreground=fg)
        self.style.configure("TCheckbutton", foreground=fg)
        self.style.configure("Black.TCheckbutton", foreground=fg, background=bg)
        self.style.configure("primary.TLabel", foreground=self.dark_blue, background=bg)
        self.style.configure("primary.TButton", background=self.dark_blue, foreground="white")
        self.style.configure("secondary.TLabel", background=entry_bg, foreground=muted)
        self.style.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg,
                             insertcolor=fg)
        self.style.configure("primary.TCombobox", fieldbackground=entry_bg,
                             background=bg, foreground=entry_fg)

        # Kök + kaydırılabilir alan
        self.master.configure(bg=bg)
        if hasattr(self, "canvas"):
            self.canvas.configure(bg=bg)

        # Kayıtlı düz etiketler (inline foreground'lu olanlar)
        for w, is_accent in self._theme_labels:
            try:
                w.configure(background=bg, foreground=(self.dark_blue if is_accent else fg))
            except Exception:
                pass

        # tk.Text ve benzeri (konsol, chat)
        for w in self._theme_texts:
            try:
                w.configure(background=p["surface"], foreground=fg, insertbackground=fg)
            except Exception:
                pass

        workspace = getattr(self, "hardware_workspace", None)
        if workspace and workspace.exists:
            workspace.apply_theme()
        cards_workspace = getattr(self, "hardware_cards_workspace", None)
        if cards_workspace and cards_workspace.exists:
            cards_workspace.apply_theme()
        impact_workspace = getattr(self, "impact_analysis_workspace", None)
        if impact_workspace and impact_workspace.exists:
            impact_workspace.apply_theme()
        architecture_workspace = getattr(self, "mimari_cerceve_workspace", None)
        if architecture_workspace and architecture_workspace.exists:
            architecture_workspace.apply_theme()

    def _show_sozluk(self):
        """Teknik sözlüğü ayrı bir pencerede açar (sozluk.py'den okur)."""
        try:
            import importlib, sozluk
            importlib.reload(sozluk)
            veri = sozluk.SOZLUK
        except Exception as e:
            messagebox.showerror(self._t("Hata", "Error"),
                                 self._t(f"Sözlük yüklenemedi: {e}", f"Glossary could not load: {e}"))
            return
        c = self.style.colors
        win = tk.Toplevel(self.master)
        win.title(self._t("Teknik Sözlük", "Technical Glossary"))
        win.geometry("620x640")
        win.configure(bg=c.bg)

        ttk.Label(win, text=self._t("📖 Teknik Sözlük", "📖 Technical Glossary"),
                  font=("Segoe UI", 14, "bold"), foreground=c.primary,
                  background=c.bg).pack(anchor="w", padx=14, pady=(12, 2))
        ttk.Label(win, text=self._t("Çıktıdaki kısaltmalar ve sistem mühendisliği terimleri.",
                                    "Abbreviations in the output and systems-engineering terms."),
                  font=("Segoe UI", 9), foreground=c.secondary, background=c.bg).pack(anchor="w", padx=14)

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=8)
        sb = ttk.Scrollbar(frame, orient="vertical")
        sb.pack(side="right", fill="y")
        txt = tk.Text(frame, wrap="word", font=("Segoe UI", 10), yscrollcommand=sb.set,
                      relief="solid", borderwidth=1, background=c.inputbg,
                      foreground=c.inputfg, padx=10, pady=8, spacing1=2, spacing3=4)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        txt.tag_config("kat", foreground=c.primary, font=("Segoe UI", 11, "bold"), spacing1=10, spacing3=4)
        txt.tag_config("term", foreground=c.info, font=("Segoe UI", 10, "bold"))
        txt.tag_config("acik", foreground=c.inputfg, font=("Segoe UI", 10))
        txt.tag_config("vurgu_kat", foreground=c.success, font=("Segoe UI", 11, "bold"), spacing1=10, spacing3=4)
        txt.tag_config("ipucu", foreground=c.secondary, font=("Segoe UI", 9, "italic"), spacing3=6)

        idx = 0 if self.lang == "tr" else 1

        # ── B ÖZELLİĞİ: üretilen çıktıda geçen terimleri öne çıkar ──
        try:
            birlesik = " ".join(list(self.flat_data.keys()) +
                                [str(d.get("content", "")) for d in self.flat_data.values()])
        except Exception:
            birlesik = ""
        import re as _sr
        def _gecti(madde):
            # Kelime SINIRIYLA eşleştir (önek kabul) → 'DOA' artık 'TDOA' içinde eşleşmez.
            aramalar = madde[3] if len(madde) > 3 else [madde[0]]
            for a in aramalar:
                if a and _sr.search(r"\b" + _sr.escape(a), birlesik, _sr.I):
                    return True
            return False

        if birlesik.strip():
            gecenler = [m for maddeler in veri.values() for m in maddeler if _gecti(m)]
            txt.insert(tk.END, self._t("🔎 Bu çıktıda geçen terimler",
                                       "🔎 Terms found in this output") + "\n", "vurgu_kat")
            if gecenler:
                for madde in gecenler:
                    txt.insert(tk.END, f"  • {madde[0]}\n", "term")
                    txt.insert(tk.END, f"      {madde[1 + idx]}\n", "acik")
            else:
                txt.insert(tk.END, self._t("  (eşleşen terim bulunamadı)",
                                           "  (no matching terms found)") + "\n", "ipucu")
            txt.insert(tk.END, "\n" + "─" * 40 + "\n", "ipucu")
        else:
            txt.insert(tk.END, self._t(
                "İpucu: Doküman ürettikten sonra bu pencere, o çıktıda geçen terimleri en üstte öne çıkarır.\n",
                "Tip: After generating documents, this window highlights the terms found in that output at the top.\n"),
                "ipucu")

        # ── Tüm sözlük ──
        for kategori, maddeler in veri.items():
            txt.insert(tk.END, f"\n{kategori}\n", "kat")
            for madde in maddeler:
                txt.insert(tk.END, f"  • {madde[0]}\n", "term")
                txt.insert(tk.END, f"      {madde[1 + idx]}\n", "acik")
        txt.config(state=tk.DISABLED)

        ttk.Button(win, text=self._t("Kapat", "Close"), command=win.destroy,
                   style="primary.TButton", width=12).pack(pady=(0, 10))

    def _create_header(self):
        # ── Üst araç çubuğu: Tema · Dil · Sözlük ──
        toolbar = ttk.Frame(self.inner_frame, style="light")
        toolbar.pack(fill="x", pady=(0, 2))
        self.theme_btn = ttk.Button(toolbar, text="🌙", width=3, command=self._toggle_theme,
                                    style="primary.Outline.TButton")
        self.theme_btn.pack(side="right")
        self.lang_btn = ttk.Button(toolbar, text="EN", width=4, command=self._toggle_lang,
                                   style="primary.Outline.TButton")
        self.lang_btn.pack(side="right", padx=(0, 6))
        self.sozluk_btn = ttk.Button(toolbar, command=self._show_sozluk,
                                     style="primary.Outline.TButton")
        self._reg_btn(self.sozluk_btn, "📖 Sözlük", "📖 Glossary")
        self.sozluk_btn.pack(side="right", padx=(0, 6))

        header_frame = ttk.Frame(self.inner_frame, style="light")
        header_frame.pack(fill="x", pady=(5, 10))

        title = self._L(
            header_frame,
            "AI ile V Modeldeki Teknik Dokümanların Üretimi",
            "AI-based V-Model Technical Document Generation",
            font=("Segoe UI", 18, "bold"),
            foreground=self.dark_blue,
            style="primary.TLabel"
        )
        title.pack(side="left", pady=(0, 10), anchor='w', expand=True, fill='x')

        logo_path = resource_path(ICON_RELATIVE_PATH)
        self.ehsim_logo = self._load_logo(str(logo_path))
        if self.ehsim_logo:
            logo_label = ttk.Label(header_frame, image=self.ehsim_logo, style="light")
            logo_label.image = self.ehsim_logo
            logo_label.pack(side="right", pady=(0, 10), padx=(10, 0), anchor='e')

    def _load_logo(self, path):
        try:
            if not os.path.exists(path):
                raise FileNotFoundError
            img = Image.open(path).resize((100, 88), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"Logo yüklenemedi: {e}")
            return None

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_textarea_mousewheel(self, event):
        self.output_text_area.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _create_input_widgets(self, parent_frame):
        def create_input_row(parent, label_tr, label_en, entry_key,
                             is_file_selector=False, is_count_entry=False,
                             is_cross=False, is_template_selector=False):
            frame = ttk.Frame(parent, style="light")
            frame.pack(fill="x", pady=8)

            self._L(
                frame, f"{label_tr}:", f"{label_en}:", font=("Segoe UI", 10),
                foreground="#333333", width=39, anchor="w"
            ).pack(side="left")

            if is_file_selector:
                hint = self.FILE_HINT if self._dnd_enabled else "Seçilmedi"
                lbl = ttk.Label(frame, text=hint, relief="solid", borderwidth=1,
                                style="secondary.TLabel", width=20, anchor="w", padding=(5, 5))
                lbl.pack(side="left", expand=True, fill="x", padx=5)
                self.entry_widgets[entry_key] = lbl
                ttk.Button(frame, text="...", command=self.select_files,
                           style="primary.Outline.TButton", width=3).pack(side="left", padx=(5, 0))
                # Hem etikete hem satır çerçevesine sürükle-bırak hedefi kaydet
                self._register_drop_target(lbl)
                self._register_drop_target(frame)

            elif is_template_selector:
                lbl = ttk.Label(frame, text=self._t("Seçilmedi", "Not selected"), relief="flat",
                                style="secondary.TLabel", width=20, anchor="w", padding=(5, 5))
                lbl.pack(side="left", expand=True, fill="x", padx=5)
                self.entry_widgets[entry_key] = lbl
                ttk.Button(frame, text="...", command=self.select_template_file,
                           style="primary.Outline.TButton", width=3).pack(side="left", padx=(5, 0))

            elif is_count_entry:
                entry = ttk.Entry(frame, width=5, validate="key")
                entry['validatecommand'] = (entry.register(self.validate_number), '%P')
                entry.pack(side="left", padx=(0, 5))
                self.entry_widgets[entry_key] = entry
                entry.insert(0, "0")

            elif is_cross:
                lbl = ttk.Label(frame, text="X", font=("Segoe UI", 10, "bold"),
                                foreground="#FF0000", width=5)
                lbl.pack(side="left", padx=(0, 5))
                self.entry_widgets[entry_key] = lbl

            else:
                entry = ttk.Entry(frame)
                entry.pack(side="left", fill="x", padx=15, expand=True)
                self.entry_widgets[entry_key] = entry

        create_input_row(parent_frame, "Proje İsmi", "Project Name", "proje_ismi")
        create_input_row(parent_frame, "Girdi Dosyaları (PDF/TXT)", "Input Files (PDF/TXT)", "proje_bilesenleri", is_file_selector=True)
        create_input_row(parent_frame, "Şablon Dosyası (.docx)", "Template File (.docx)", "template_file", is_template_selector=True)

        self._L(
            parent_frame, "TEKNİK DOKÜMANLAR:", "TECHNICAL DOCUMENTS:",
            font=("Segoe UI", 10, "bold"), foreground=self.dark_blue, style="primary.TLabel"
        ).pack(pady=(15, 3), anchor="w")

        labels_frame = ttk.Frame(parent_frame, style="light")
        labels_frame.pack(pady=(5, 10), anchor="w", fill="x")
        self._L(
            labels_frame, "Gereksinim Dokümanları ve Madde Sayısı",
            "Requirement Documents and Item Count",
            font=("Segoe UI", 10, "bold", "underline"), foreground=self.dark_blue
        ).pack(side="left", padx=(0, 40))
        self._L(
            labels_frame, "Test Dokümanları", "Test Documents",
            font=("Segoe UI", 10, "bold", "underline"), foreground=self.dark_blue
        ).pack(side="left", padx=(45, 0))

        docs_frame = ttk.Frame(parent_frame, style="light", padding=10)
        docs_frame.pack(fill="x")
        left_col = ttk.Frame(docs_frame, style="light")
        right_col = ttk.Frame(docs_frame, style="light")
        left_col.pack(side="left", expand=True, fill="x")
        right_col.pack(side="right", expand=True, fill="x")

        create_input_row(left_col, "Kullanıcı Gereksinimi (User Requirement)", "User Requirement", "teknik_ister", is_count_entry=True)
        create_input_row(left_col, "Sistem Gereksinimi (System Requirements)", "System Requirement", "sistem_gereksinimi", is_count_entry=True)
        create_input_row(left_col, "Alt Sistem Gereksinimleri (Subsystem Requirements)", "Subsystem Requirement", "sistem_tanimlama_testi", is_count_entry=True)

        label_width = 39
        label_font = ("Segoe UI", 10)
        label_color = "#333333"

        def test_row(tr, en, key):
            fr = ttk.Frame(right_col, style="light")
            fr.pack(fill="x", pady=15)
            self._L(fr, f"{tr}:", f"{en}:", font=label_font, foreground=label_color,
                    width=label_width, anchor="w").pack(side="left")
            self.checkbox_vars[key] = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(fr, variable=self.checkbox_vars[key], style="Black.TCheckbutton")
            self._reg_btn(cb, "Üret", "Generate")
            cb.config(text="Üret" if self.lang == "tr" else "Generate")
            cb.pack(side="left", padx=(0, 5))

        test_row("Kabul Testi (Acceptance Test)", "Acceptance Test", "generate_kmtd")
        test_row("Sistem Testi (System Test)", "System Test", "generate_sitet")
        test_row("Alt Sistem Testi (Subsystem Testing)", "Subsystem Test", "generate_alt_sistem_testi")

    def validate_number(self, P):
        return P.isdigit() or P == ""

    def _create_output_widgets(self, parent_frame):
        self._L(
            parent_frame, "İSTENEN ÇIKTI TÜRÜ:", "OUTPUT FORMAT:",
            font=("Segoe UI", 10, "bold"), foreground=self.dark_blue, style="primary.TLabel"
        ).pack(pady=(5, 8), anchor="w")

        output_frame = ttk.Frame(parent_frame, style="light", padding=5)
        output_frame.pack(fill="x")
        self._L(output_frame, "Çıktı Formatı:", "Format:", style="light").pack(side="left")
        self.format_combo = ttk.Combobox(
            output_frame,
            values=["txt", "pdf", "excel", "html", "docx", "şablon", "DOORS"],
            state="readonly",
            width=8,
            style="primary.TCombobox"
        )
        self.format_combo.set("pdf")
        self.format_combo.pack(side="left", padx=(5, 20))
        self._L(output_frame, "Durum/Çıktı Konsolu:", "Status / Output Console:", style="light").pack(side="left")

        console_frame = ttk.Frame(parent_frame, style="light")
        console_frame.pack(pady=(10, 15), fill="both", expand=True)

        self.text_scrollbar = ttk.Scrollbar(console_frame, orient="vertical")
        self.text_scrollbar.pack(side="right", fill="y")

        self.output_text_area = tk.Text(
            console_frame,
            height=12,
            relief="solid",
            borderwidth=1,
            state=tk.DISABLED,
            yscrollcommand=self.text_scrollbar.set,
            font=("Segoe UI", 10)
        )
        self.output_text_area.pack(side="left", fill="both", expand=True)
        self.text_scrollbar.config(command=self.output_text_area.yview)
        self.output_text_area.bind("<MouseWheel>", self._on_textarea_mousewheel)
        self._theme_texts.append(self.output_text_area)   # tema değişiminde renklen

    def _create_buttons(self, parent_frame):
        architecture_frame = ttk.Frame(parent_frame, style="light")
        architecture_frame.pack(side="bottom", fill="x", pady=(0, 4))
        self.architecture_button = ttk.Button(
            architecture_frame,
            command=self.open_architecture_framework_workspace,
            style="primary.Outline.TButton",
            width=24,
        )
        self._reg_btn(
            self.architecture_button,
            "Mimari Çerçeve",
            "Architecture Framework",
        )
        self.architecture_button.config(
            text=self._t("Mimari Çerçeve", "Architecture Framework")
        )
        self.architecture_button.pack(side="left", fill="x", expand=True, pady=3)

        button_frame = ttk.Frame(parent_frame, style="light")
        button_frame.pack(side="bottom", fill="x", pady=20)

        self.hardware_button = ttk.Button(
            button_frame, command=self.open_hardware_workspace,
            style="primary.Outline.TButton", width=18)
        self._reg_btn(self.hardware_button, "Donanım Listesi", "Hardware List")
        self.hardware_button.config(text=self._t("Donanım Listesi", "Hardware List"))
        self.hardware_button.pack(side="left", pady=5)

        self.hardware_cards_button = ttk.Button(
            button_frame, command=self.open_hardware_cards_workspace,
            style="primary.Outline.TButton", width=18)
        self._reg_btn(self.hardware_cards_button, "Donanım Kartları", "Hardware Cards")
        self.hardware_cards_button.config(text=self._t("Donanım Kartları", "Hardware Cards"))
        self.hardware_cards_button.pack(side="left", padx=(8, 0), pady=5)

        self.impact_analysis_button = ttk.Button(
            button_frame, command=self.open_impact_analysis_workspace,
            style="primary.Outline.TButton", width=16)
        self._reg_btn(self.impact_analysis_button, "Etki Analizi", "Impact Analysis")
        self.impact_analysis_button.config(text=self._t("Etki Analizi", "Impact Analysis"))
        self.impact_analysis_button.pack(side="left", padx=(8, 0), pady=5)

        self.reset_button = ttk.Button(
            button_frame, command=self.reset_app, bootstyle="danger", width=15)
        self._reg_btn(self.reset_button, "İptal / Sıfırla", "Cancel / Reset")
        self.reset_button.config(text=self._t("İptal / Sıfırla", "Cancel / Reset"))
        self.reset_button.pack(side="right", padx=(10, 0), pady=5)

        self.download_docs_button = ttk.Button(
            button_frame, command=self.download_docs, style="primary.TButton")
        self._reg_btn(self.download_docs_button, "Dokümanları İndir", "Download Documents")
        self.download_docs_button.config(text=self._t("Dokümanları İndir", "Download Documents"))
        self.download_docs_button.pack(side="right", pady=5)

        # --- Gereksinim Kalite Denetçisi (ayrı özellik; kaldırmak için bu buton + kalite_denetci.py sil) ---
        self.kalite_button = ttk.Button(
            button_frame, command=self.run_kalite_denetimi, style="primary.TButton", width=16)
        self._reg_btn(self.kalite_button, "Kaliteyi Denetle", "Check Quality")
        self.kalite_button.config(text=self._t("Kaliteyi Denetle", "Check Quality"))
        self.kalite_button.pack(side="right", padx=10, pady=5)

        self.create_docs_button = ttk.Button(
            button_frame, command=self.start_generation, style="primary.TButton")
        self._reg_btn(self.create_docs_button, "Dokümanları Üret", "Generate Documents")
        self.create_docs_button.config(text=self._t("Dokümanları Üret", "Generate Documents"))
        self.create_docs_button.pack(side="right", padx=10, pady=5)

    def run_kalite_denetimi(self):
        """Üretilen maddeleri kalite kurallarına göre denetler ve ayrı bir rapor penceresi açar.
        Salt-okunur: hiçbir veriyi değiştirmez. (Ayrı özellik — kalite_denetci.py'ye bağlı.)"""
        if not self.flat_data:
            messagebox.showwarning("Uyarı", "Denetlenecek veri yok. Önce doküman üretin.")
            return
        try:
            import kalite_denetci
        except Exception as e:
            messagebox.showerror("Hata", f"Kalite denetçisi yüklenemedi: {e}")
            return
        win = tk.Toplevel(self.master)
        win.title("Gereksinim Kalite Raporu")
        win.geometry("670x620")

        baslik = ttk.Label(win, font=("Segoe UI", 12, "bold"), foreground=self.dark_blue)
        baslik.pack(anchor="w", padx=12, pady=(10, 4))

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        sb = ttk.Scrollbar(frame, orient="vertical")
        sb.pack(side="right", fill="y")
        txt = tk.Text(frame, wrap="word", font=("Consolas", 10),
                      yscrollcommand=sb.set, relief="solid", borderwidth=1)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)

        def _yenile():
            rapor = kalite_denetci.denetle(self.flat_data)
            s = rapor["summary"]
            baslik.config(text=f"Kalite Puanı: %{s['kalite']}   "
                               f"(⚠️ {s['problemli']} sorunlu / {s['total']} madde, 📌 {s['dsb']} DSB)")
            txt.config(state=tk.NORMAL)
            txt.delete("1.0", tk.END)
            txt.insert("1.0", kalite_denetci.rapor_metni(rapor))
            txt.config(state=tk.DISABLED)

        ttk.Button(win, text="🔄 Yenile (Copilot düzeltmelerinden sonra bas)",
                   command=_yenile, style="primary.TButton").pack(pady=(0, 10))
        _yenile()

    def reset_app(self):
        cevap = messagebox.askyesno("Sıfırla", "Tüm seçimler, yüklenen dosyalar ve üretilen veriler silinecek.\nEmin misiniz?")
        if not cevap:
            return

        self._notify_architecture_source_mutation_started()
        architecture_workspace = getattr(self, "mimari_cerceve_workspace", None)
        if architecture_workspace and architecture_workspace.exists:
            architecture_workspace.close()

        self.file_paths = []
        self.template_file_path = None
        self.entry_widgets["proje_bilesenleri"].config(
            text=self.FILE_HINT if self._dnd_enabled else "Seçilmedi")
        self.entry_widgets["template_file"].config(text="Seçilmedi")
        self.entry_widgets["proje_ismi"].delete(0, tk.END)
        
        sayac_alanlari = ["teknik_ister", "sistem_gereksinimi", "sistem_tanimlama_testi"]
        for key in sayac_alanlari:
            self.entry_widgets[key].delete(0, tk.END)
            self.entry_widgets[key].insert(0, "0")

        for var in self.checkbox_vars.values():
            var.set(True)

        self.last_generated_output = ""
        self.raw_output_cache = ""
        self.tree_data.clear()
        self._traceability_generation_token += 1
        self._traceability_cancel_event.set()
        self._architecture_generation_state = "ready"
        self._architecture_generation_detail = ""
        self.flat_data.clear()
        self.hardware_data.clear()
        self.generated_document_paths.clear()
        self.last_hardware_catalog = None
        self.last_hardware_catalog_status = None
        self.last_hardware_impact_result = None
        self._invalidate_hardware_generation()
        self._refresh_hardware_workspace()
        self._refresh_hardware_cards_workspace()
        self.last_tid_list = []      
        self.last_sgd_list = []
        self.last_stt_list = []
        self.last_dgoygo_list = []
        self.last_sitet_list = []
        self.last_alt_sistem_test_list = []
        self.last_dtet_ytet_list = []

        self.output_text_area.config(state=tk.NORMAL)
        self.output_text_area.delete("1.0", tk.END)
        self.output_text_area.config(state=tk.DISABLED)

        self.create_docs_button.config(state=tk.NORMAL, text=self._t("Dokümanları Üret", "Generate Documents"), style="primary.TButton")
        self.download_docs_button.config(state=tk.NORMAL)

        messagebox.showinfo("Bilgi", "Uygulama başarıyla sıfırlandı.")

    def select_files(self):
        paths = filedialog.askopenfilenames(
            title="Girdi Dosyalarını Seç",
            filetypes=[("PDF ve TXT dosyaları", "*.pdf *.txt")]
        )
        if paths:
            self.file_paths = list(paths)
            names = [os.path.basename(p) for p in self.file_paths]
            display = ", ".join(names) if len(names) <= 3 else f"{len(names)} dosya seçildi"
            self.entry_widgets["proje_bilesenleri"].config(text=display)
            self.update_status_text(f"Seçilen dosya(lar): {display}", clear=True)

    def select_template_file(self):
        path = filedialog.askopenfilename(
            title="Şablon Dosyasını Seç (docx)",
            filetypes=[("DOCX dosyaları", "*.docx"), ("Tüm Dosyalar", "*.*")]
        )
        if path:
            self.template_file_path = path
            self.entry_widgets["template_file"].config(text=os.path.basename(path))
            self.update_status_text(f"Seçilen şablon: {os.path.basename(path)}")
        else:
            self.template_file_path = None
            self.entry_widgets["template_file"].config(text="Seçilmedi")

    def update_status_text(self, message, is_error=False, is_complete=False, clear=False):
        def _inner():
            self.output_text_area.config(state=tk.NORMAL)
            if clear:
                self.output_text_area.delete("1.0", tk.END)

            tag = "msg"
            if is_error:
                tag = "error"
                self.output_text_area.tag_config(tag, foreground=self.style.colors.danger,
                                                 font=("Segoe UI", 10, "bold"))
                self.output_text_area.insert(tk.END, f"\n[HATA] {message}", tag)
            elif is_complete:
                tag = "complete"
                self.output_text_area.tag_config(tag, foreground=self.style.colors.success,
                                                 font=("Segoe UI", 10, "bold"))
                self.output_text_area.insert(tk.END, f"\n{message}", tag)
            else:
                self.output_text_area.insert(tk.END, f"\n{message}", tag)

            self.output_text_area.see(tk.END)
            self.output_text_area.config(state=tk.DISABLED)
        self.master.after(0, _inner)

    # V-Modelindeki doküman türleri: (flat_data type, başlık, bacak)
    # 'req' = sol bacak (gereksinim), 'test' = sağ bacak (doğrulama)
    VMODEL_SECTIONS = [
        ("TID",       "Kullanıcı Gereksinimi (User Requirement)",                "req"),
        ("KMTD",      "Kabul Testi (Acceptance Test)",               "test"),
        ("SGD",       "Sistem Gereksinimi (System Requirements)",            "req"),
        ("SITET",     "Sistem Testi (System Test)",                          "test"),
        ("STT",       "Alt Sistem Gereksinimleri (Subsystem Requirements)",  "req"),
        ("AST",       "Alt Sistem Testi (Subsystem Test)",                   "test"),
    ]

