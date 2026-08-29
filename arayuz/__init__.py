# -*- coding: utf-8 -*-
"""arayuz paketi (Faz 7 — mimari yeniden yapılandırma, son adım).

Eski Arayüz.py dosyasının (3208 satır, TIDGeneratorApp sınıfında 86 metot)
bölündüğü hâli. Bkz. MIMARI_YENIDEN_YAPILANDIRMA_PLANI.md bölüm 3 ve 6.

Bu dosya, eski Arayüz.py'nin üst seviyesinde bulunan TÜM import edilmiş
adları (test/entegrasyon kodunun `main_ui.ttk`, `main_ui.mimari_cerceve_ui`
gibi doğrudan erişebildiği tekil modül nesneleri dahil) yeniden ihraç eder.
"""

from .yardimcilar import pre_process_files, start1_time
from .workspace import TIDGeneratorApp
from .pencere import (
    A4,
    APP_NAME,
    HuggingFaceEmbeddings,
    ICON_RELATIVE_PATH,
    Image,
    ImageTk,
    Style,
    TTFont,
    Workbook,
    alt_sistem_test_logic,
    apply_app_identity,
    canvas,
    csv,
    datetime,
    dgöygö_generator_logic,
    donanim_kartlari_algilama,
    donanim_kartlari_gorsel,
    donanim_kartlari_ui,
    donanim_kartlari_yonetim,
    dtet_ytet_generator_logic,
    etki_analizi_degisim_paketi,
    etki_analizi_degisim_raporlama,
    etki_analizi_entegrasyon,
    etki_analizi_izlenebilirlik,
    etki_analizi_simulasyon,
    etki_analizi_ui,
    filedialog,
    hardware_generator_logic,
    hardware_list_logic,
    hardware_list_ui,
    html_generation,
    kmtd_generator_logic,
    messagebox,
    mimari_cerceve_ui,
    np,
    os,
    pdf_extraction,
    pdfmetrics,
    prepare_process_identity,
    resource_path,
    sgd_generator_logic,
    sitet_generator_logic,
    stt_generator_logic,
    sys,
    text_cleanup,
    threading,
    tid_generator_logic,
    time,
    tk,
    traceback,
    ttk,
)
