# -*- coding: utf-8 -*-
"""Faz 7 (mimari yeniden yapılandırma) — Arayüz.py'nin bölünmüş
parçalarından biri: modül seviyesi yardımcı fonksiyon(lar). Bkz.
MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 3.
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


start1_time = time.time()

def pre_process_files(file_paths, status_callback=None):
    all_chunks = []
    
    for file_path in file_paths:
        if status_callback:
            status_callback(f"Dosya işleniyor: {os.path.basename(file_path)}")
        
        chunks = tid_generator_logic.extract_book_chunks(file_path)
        
        if status_callback:
            status_callback(f"{len(chunks)} adet chunk bulundu.")
        
        all_chunks.extend(chunks)

    if not all_chunks:
        if status_callback:
            status_callback("Chunk bulunamadı.", is_error=True)
        return None, None

    if status_callback:
        status_callback(f"Toplam {len(all_chunks)} adet chunk bulundu.")
        status_callback("Chunk'lar embedding ile analiz ediliyor...\n")

    try:
        # Faz 7'de bu fonksiyon proje kokunden arayuz/ alt paketine tasindi;
        # bir ust dizine cikip proje kokundeki HuggingFaceEmbeddings/'i
        # bulmaya devam ediyoruz (davranis tasimadan onceki haliyle ayni).
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        yerel_model_yolu = os.path.join(base_dir, "HuggingFaceEmbeddings", "all-MiniLM-L6-v2")
        embedder = HuggingFaceEmbeddings(model_name=yerel_model_yolu)
        
        embeddings = np.array(embedder.embed_documents(all_chunks))
        
        center = np.mean(embeddings, axis=0)
        similarities = [
            np.dot(e, center) / (np.linalg.norm(e) * np.linalg.norm(center))
            for e in embeddings
        ]
        sorted_indices = np.argsort(similarities)[::-1]
        
        return all_chunks, sorted_indices

    except Exception as e:
        if status_callback:
            status_callback(f"Embedding Hatası: {str(e)}", is_error=True)
        return None, None
