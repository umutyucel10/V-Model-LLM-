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

class _DosyaSurukleMixin:
    def _register_drop_target(self, widget):
        """Bir widget'ı PDF/TXT sürükle-bırak hedefi yapar (tkinterdnd2 varsa)."""
        if not getattr(self, "_dnd_enabled", False):
            return
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_files_dropped)
        except Exception as e:
            print(f"Sürükle-bırak kaydı başarısız: {e}")

    def _on_files_dropped(self, event):
        """OS'ten sürüklenip bırakılan dosyaları işler."""
        try:
            dropped = self.master.tk.splitlist(event.data)
        except Exception:
            dropped = [event.data]
        valid = [p for p in dropped if p.lower().endswith((".pdf", ".txt"))]
        if not valid:
            self.update_status_text("⚠️ Sadece PDF/TXT dosyaları sürükle-bırak yapılabilir.", is_error=True)
            return
        self.file_paths = list(valid)
        names = [os.path.basename(p) for p in self.file_paths]
        display = ", ".join(names) if len(names) <= 3 else f"{len(names)} dosya seçildi"
        self.entry_widgets["proje_bilesenleri"].config(text=display)
        self.update_status_text(f"Sürükle-bırak ile eklendi: {display}", clear=True)
        return event.action

