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

class _CopilotMixin:
    def _create_chat_panel(self, master, target_bg):
        """Sağ tarafta üretilen maddeleri revize etmek için sohbet paneli."""
        panel = ttk.Frame(master, style="light", width=370)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        head = ttk.Frame(panel, style="light")
        head.pack(fill="x", padx=10, pady=(12, 4))
        self._L(head, "🤖 Doküman Copilot", "🤖 Document Copilot", font=("Segoe UI", 13, "bold"),
                foreground=self.dark_blue, style="primary.TLabel").pack(side="left")

        self._L(panel,
                "Üretilen bir maddeyi revize ettir. Örn:\n«UR-004'ü daha teknik yaz, güvenlik standardı ekle»",
                "Revise a generated item. E.g.:\n«Make UR-004 more technical, add a security standard»",
                font=("Segoe UI", 8), foreground="#666", justify="left",
                wraplength=340, style="secondary.TLabel").pack(fill="x", padx=10, pady=(0, 6))

        hist_frame = ttk.Frame(panel, style="light")
        hist_frame.pack(fill="both", expand=True, padx=10)
        sb = ttk.Scrollbar(hist_frame, orient="vertical")
        sb.pack(side="right", fill="y")
        self.chat_history = tk.Text(hist_frame, wrap="word", relief="solid", borderwidth=1,
                                    state=tk.DISABLED, font=("Segoe UI", 9), yscrollcommand=sb.set)
        self.chat_history.pack(side="left", fill="both", expand=True)
        self._theme_texts.append(self.chat_history)
        sb.config(command=self.chat_history.yview)
        self.chat_history.tag_config("user", foreground="#0052cc", font=("Segoe UI", 9, "bold"))
        self.chat_history.tag_config("bot", foreground="#1a7f37")
        self.chat_history.tag_config("err", foreground="#c1121f")
        self.chat_history.tag_config("info", foreground="#666", font=("Segoe UI", 8, "italic"))

        entry_frame = ttk.Frame(panel, style="light")
        entry_frame.pack(fill="x", padx=10, pady=10)
        self.chat_entry = ttk.Entry(entry_frame, font=("Segoe UI", 10))
        self.chat_entry.pack(side="left", fill="x", expand=True)
        self.chat_entry.bind("<Return>", lambda e: self._chat_send())
        self.chat_send_btn = ttk.Button(entry_frame, style="primary.TButton",
                                        command=self._chat_send, width=8)
        self._reg_btn(self.chat_send_btn, "Gönder", "Send")
        self.chat_send_btn.config(text=self._t("Gönder", "Send"))
        self.chat_send_btn.pack(side="left", padx=(6, 0))

        # Karşılama metni (dil değişince yeniden yazılabilmesi için saklanır)
        self._chat_greeting = (
            "Merhaba! Önce dokümanları üret, sonra bir maddeyi bana revize ettir. Örn: «SR-002'yi daha ölçülebilir yap».",
            "Hello! First generate documents, then ask me to revise an item. E.g.: «Make SR-002 more measurable».")
        self._chat_has_convo = False   # gerçek bir sohbet başlayınca True
        self._chat_append(self._t(*self._chat_greeting), "info")

    def _chat_append(self, text, tag="bot"):
        def _inner():
            self.chat_history.config(state=tk.NORMAL)
            prefix = {"user": "\n👤 Sen:\n", "bot": "\n🤖 Copilot:\n", "err": "\n⚠️ "}.get(tag, "\n")
            self.chat_history.insert(tk.END, prefix + text + "\n", tag)
            self.chat_history.see(tk.END)
            self.chat_history.config(state=tk.DISABLED)
        self.master.after(0, _inner)

    def _find_target_id(self, msg):
        """Mesajdan flat_data'daki bir madde ID'sini yakalar (Türkçe/nokta duyarsız)."""
        def norm(s):
            s = s.upper()
            for a, b in (("İ", "I"), ("Ö", "O"), ("Ğ", "G"), ("Ü", "U"),
                         ("Ş", "S"), ("Ç", "C"), ("I", "I")):
                s = s.replace(a, b)
            return s
        nmsg = norm(msg)
        # Uzun ID'leri (DTET-YTET-001 gibi) önce dene ki kısa parçalar yanlış eşleşmesin
        for key in sorted(self.flat_data.keys(), key=len, reverse=True):
            if norm(key) in nmsg:
                return key
        return None

    def _chat_send(self):
        msg = self.chat_entry.get().strip()
        if not msg:
            return
        if not self.flat_data:
            self._chat_append("Henüz üretilmiş doküman yok. Önce 'Dokümanları Üret' ile üretim yap.", "err")
            return
        self.chat_entry.delete(0, tk.END)
        self._chat_has_convo = True   # artık dil değişiminde karşılamayı üzerine yazma
        self._chat_append(msg, "user")
        self.chat_send_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._chat_worker, args=(msg,), daemon=True).start()

    def _chat_worker(self, msg):
        try:
            from llm_handler import call_gemma3_api
            target = self._find_target_id(msg)
            if not target:
                self._chat_append("Hangi maddeyi revize edeceğimi bulamadım. Lütfen ID yaz "
                                  "(ör: UR-004, SR-002).", "err")
                return
            old = self.flat_data[target].get("content", "")
            # "BÖL" komutu: atomik olmayan bir maddeyi ayrı gereksinimlere böl
            if any(w in msg.lower() for w in ("böl", "parçala", "ayrı madde")):
                self._split_requirement(target)
                return
            self._chat_append(f"{target} revize ediliyor...", "info")

            # DSB kararını PYTHON'da deterministik ver (4B model 'değer verildi mi' ayrımını
            # güvenilir yapamıyor). 3 durum: (1) değer isteniyor+sayı var → kullan,
            # (2) değer isteniyor+sayı yok → DSB, (3) sadece ton/ifade değişikliği → sayıları koru.
            import re as _re
            _VALUE_KW = ("değer", "sayı", "sayısal", "süre", "eşik", "sınır", "menzil", "mesafe",
                         "sıcaklık", "hız", "frekans", "oran", "gecikme", "tolerans", "doğruluk",
                         "hassasiyet", "kapasite", "aralık", "metrik", "ölçülebilir", "birim",
                         "limit", "seviye", "band", "bant", "voltaj", "akım", "güç", "boyut", "ağırlık")
            # ÖNEMLİ: "SR-001" gibi ID'lerin içindeki rakamları (001) "kullanıcı sayı verdi"
            # sanmamak için, sayı kontrolünden ÖNCE mesajdan ID'leri temizle.
            _msg_no_id = _re.sub(_re.escape(target), "", msg, flags=_re.I) if target else msg
            _msg_no_id = _re.sub(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2,}(?:-[A-Za-zÇĞİÖŞÜçğıöşü]+)*-\d+", "", _msg_no_id)
            _has_number = bool(_re.search(r"\d", _msg_no_id))
            _asks_value = any(k in msg.lower() for k in _VALUE_KW)
            if _has_number:
                dsb_directive = ("NOT: Kullanıcı somut sayısal değer(ler) verdi. Bu değerleri AYNEN "
                                 "kullan. Bu istekte 'DSB' YAZMA.")
            elif _asks_value:
                dsb_directive = ("NOT: Kullanıcı bir sayısal değer/eşik istiyor ama sayının kendisini "
                                 "VERMEDİ. O değerin yerine MUTLAKA 'DSB' yaz (birimi koru) — sayı UYDURMA.")
            else:
                dsb_directive = ("NOT: Bu istek yalnızca ifade/ton değişikliğidir. Mevcut metindeki TÜM "
                                 "sayıları ve değerleri AYNEN KORU; yeni sayı ekleme, 'DSB' YAZMA.")
            prompt = (
                f"MADDE ID: {target}\n"
                f"MEVCUT METİN: \"{old}\"\n\n"
                f"KULLANICI İSTEĞİ: {msg}\n\n"
                f"{dsb_directive}\n\n"
                "Bu maddeyi yukarıdaki nota ve sistem mühendisliği kurallarına göre revize et. "
                "Yanıt olarak SADECE revize edilmiş madde metnini ver."
            )
            resp = call_gemma3_api(prompt, max_tokens=280, temperature=0.1,
                                   system_message=self.COPILOT_SYSTEM_PROMPT)
            if not resp or not resp.strip():
                self._chat_append(f"{target} için model cevap vermedi. LM Studio açık ve model yüklü mü?", "err")
                return
            new = self._clean_revision(resp)
            # Model, kullanıcı mesajındaki madde ID'sini gövdeye kopyalıyor
            # ("... AT-014 test senaryosunda karşılanmalıdır"). Madde metni kendi ID'sini
            # içermemeli (ID zaten ayrı sütunda) → hedef ID'yi metinden temizle.
            # Ek YALNIZCA kesme işaretiyle bitişikse silinir ("SR-002'nin"); aksi halde
            # sonraki kelimeden harf yenir ("AT-014 test" → "t")!
            _id_pat = _re.compile(r"\s*\b" + _re.escape(target) + r"\b(?:['’][a-zçğıöşü]{1,4})?\s*", _re.I)
            new = _id_pat.sub(" ", new)
            new = _re.sub(r"\s{2,}", " ", new).strip(" ,;:")
            if "DSB" in new.upper():
                new = text_cleanup.dsb_temizle(new)   # DSB varsa çelişen uydurma sayıları temizle
            self._apply_revision(target, old, new)

            # Ana konsolda da GÖRÜNÜR yap (kullanıcı genelde sol tarafa bakıyor)
            self.update_status_text(f"\n━━━ COPILOT · {target} GÜNCELLENDİ ━━━", is_complete=True)
            self.update_status_text(f"ESKİ: {old}")
            self.update_status_text(f"YENİ: {new}", is_complete=True)

            # --- DEĞİŞİKLİK ETKİ ANALİZİ: bir GEREKSİNİM değişince, ona bağlı test(ler)i
            #     yeni gereksinim metnine göre YENİDEN ÜRET (kullanıcı tercihi).
            #     Gereksinimde DSB varsa üretilen teste de DSB notu eklenir. ---
            extra = ""
            architecture_changed_ids = {target}
            if self.flat_data[target].get("type") in self.REQ_TYPES:
                self._chat_append(f"{target} değişti → bağlı test(ler) yeniden üretiliyor...", "info")
                affected = self._ripple_regenerate(target)
                if affected:
                    architecture_changed_ids.update(affected)
                    extra = ("\n🔗 Bağlı test(ler) yeni gereksinime göre güncellendi: "
                             + ", ".join(affected))
            self.master.after(
                0,
                lambda ids=tuple(sorted(architecture_changed_ids)):
                    self._notify_architecture_sources_changed(ids),
            )
            self._chat_append(f"✅ {target} güncellendi:\n{new}{extra}\n\n"
                              "(İndirdiğinde pdf/excel/html/word çıktısına yansır.)", "bot")
        except Exception as e:
            self._chat_append(f"Hata: {e}", "err")
        finally:
            self.master.after(0, lambda: self.chat_send_btn.config(state=tk.NORMAL))

    def _clean_revision(self, text):
        """4B modelin eklediği başlık/etiket/markdown/liste artıklarını temizler, tek paragraf yapar."""
        import re
        text = (text or "").strip().strip('"').strip()
        # markdown vurgu ve işaretlerini kaldır
        text = re.sub(r'[*_`#]+', '', text)
        # uydurma standart kodlarını (örn. "(GS-005)") her yerden temizle
        text = re.sub(r'\s*\((?:GS|STD|MIL-?STD|DS|TS)[-\s]?\d+\)', '', text, flags=re.I)

        label = re.compile(r'^(madde\s*id|madde|revizyon|revize|id|çıktı|cikti|cevap|output|sonuç|sonuc|not)\b[\s:–-]*', re.I)
        verb = re.compile(r'(malı|meli|olmalı|etmeli|dır|dir|dur|dür)\b', re.I)

        kept = []
        for ln in text.split("\n"):
            s = ln.strip().lstrip("-•·*").strip()
            if not s:
                continue
            low = s.lower().replace("̇", "")  # Türkçe İ combining-dot'u temizle
            if label.match(low):
                # etiketi kırp; geriye anlamlı bir gereksinim cümlesi kalıyorsa tut, yoksa (başlık) at
                stripped = label.sub('', s).strip()
                if verb.search(stripped.lower()) and len(stripped.split()) >= 4:
                    kept.append(stripped)
                continue
            kept.append(s)

        out = " ".join(kept)
        out = re.sub(r'\s+', ' ', out)
        out = re.sub(r'\s+([.,;:])', r'\1', out)   # " ." -> "."
        return out.strip(' -–•:')

    def _sync_item_text(self, item_id, old_text, new_text):
        """Bir maddenin yeni metnini ham çıktı metnine ve ilgili last_*_list'e yansıtır."""
        # 1) ham metin (txt çıktısı / konsol tutarlılığı)
        #    ID'ye BAĞLI satırı değiştir ("ID | metin" formatı). Kör replace kullanılırsa,
        #    iki maddenin metni birebir AYNI olduğunda ikisi birden değişirdi → yanlış madde bozulur.
        if old_text and (self.last_generated_output or ""):
            eski_satir = f"{item_id} | {old_text}"
            yeni_satir = f"{item_id} | {new_text}"
            if eski_satir in self.last_generated_output:
                self.last_generated_output = self.last_generated_output.replace(eski_satir, yeni_satir)
            elif old_text in self.last_generated_output:
                # yedek yol: sadece İLK eşleşme (diğer maddelere bulaşmasın)
                self.last_generated_output = self.last_generated_output.replace(old_text, new_text, 1)
        # 2) ilgili last_*_list (sınıflandırma tutarlılığı) — best effort
        t = self.flat_data.get(item_id, {}).get("type", "")
        list_map = {
            "TID":       (self.last_tid_list, "TID_ID", "TID_Aciklama"),
            "SGD":       (self.last_sgd_list, "SGD_ID", "SGD_Aciklama"),
            "STT":       (self.last_stt_list, "STT_ID", "STT_Aciklama"),
            "SITET":     (self.last_sitet_list, "SITET_ID", "SITET_Aciklama"),
            "AST":       (self.last_alt_sistem_test_list, "AST_ID", "AST_Aciklama"),
        }
        if t in list_map:
            lst, idk, txtk = list_map[t]
            for it in lst:
                if it.get(idk) == item_id:
                    it[txtk] = new_text
                    break

    def _apply_revision(self, target, old, new):
        """Revizyonu flat_data + ham metin + ilgili last_*_list üzerinde uygular."""
        self._notify_architecture_source_mutation_started()
        self.flat_data[target]["content"] = new     # tüm çıktıların (pdf/excel/html/docx) kaynağı
        self._sync_item_text(target, old, new)
        self.update_status_text(f"[Copilot] {target} güncellendi.", is_complete=True)

    def _ripple_regenerate(self, requirement_id):
        """
        DEĞİŞİKLİK ETKİ ANALİZİ (TAM KASKAD): Bir gereksinim revize edilince, ona bağlı
        HEM alt gereksinimleri HEM testleri yeni metne göre yeniden üretir. Alt gereksinimler
        için işlem özyinelemeli olarak aşağı iner (UR→SR→SSR ve her birinin testi).
        Üst maddede 'DSB' varsa, türeyen tüm maddelerde de ilgili değer DSB olur (uydurma yok).
        """
        self._notify_architecture_source_mutation_started()
        child_req_gen = {
            "TID": sgd_generator_logic.generate_sgd_from_ur,
            "SGD": stt_generator_logic.generate_subsystem_req_from_sgd,
        }
        test_gen = {
            "TID": kmtd_generator_logic.generate_kmtd_from_tid,
            "SGD": sitet_generator_logic.generate_sitet_from_sgd,
            "STT": alt_sistem_test_logic.generate_subsystem_test,
        }
        dsb_kural = (" [KURAL: Yukarıdaki maddede 'DSB' geçen değer belirsizdir; türeteceğin "
                     "maddede de o değer için sayı UYDURMA, yerine 'DSB' yaz.]")
        note = (" (Not: Üst gereksinimde DSB bulunduğu için bu maddede de ilgili değer DSB'dir.)")
        affected, visited = [], set()

        def kaskad(parent_id):
            if parent_id in visited:
                return
            visited.add(parent_id)
            parent = self.flat_data.get(parent_id, {})
            ptype = parent.get("type")
            ptext = parent.get("content", "")
            dsb = "DSB" in (ptext or "").upper()
            girdi = (ptext + dsb_kural) if dsb else ptext
            cocuklar = [(k, v) for k, v in list(self.flat_data.items())
                        if v.get("bound_to") == parent_id]
            for iid, it in cocuklar:
                itype = it.get("type")
                if itype in self.TEST_TYPES:
                    gen_fn = test_gen.get(ptype)
                elif itype in self.REQ_TYPES:
                    gen_fn = child_req_gen.get(ptype)
                else:
                    gen_fn = None
                if not gen_fn:
                    continue
                try:
                    raw = gen_fn(girdi, "Proje")
                except Exception as e:
                    self.update_status_text(f"[Copilot] {iid} yeniden üretilemedi: {e}", is_error=True)
                    continue
                if not raw:
                    continue
                yeni = text_cleanup.temizle(raw, test=(itype in self.TEST_TYPES))
                if not yeni:
                    continue
                if dsb:
                    # DSB ile çelişen uydurma sayı/örnekleri temizle ('(örneğin 100g)', '100g DSB'...)
                    yeni = text_cleanup.dsb_temizle(yeni)
                    if "DSB" not in yeni.upper():
                        # Model DSB yerine sayı uydurdu → çelişkili not yerine sayıları DSB yap
                        donusmus = text_cleanup.sayilari_dsb_yap(yeni)
                        yeni = donusmus if "DSB" in donusmus.upper() else (yeni.rstrip() + note).strip()
                eski = it.get("content", "")
                it["content"] = yeni
                self._sync_item_text(iid, eski, yeni)
                affected.append(iid)
                if itype in self.REQ_TYPES:   # alt gereksinimin de altını güncelle
                    kaskad(iid)

        kaskad(requirement_id)
        if affected:
            self.update_status_text(
                f"[Copilot] {requirement_id} değişti → bağlı madde(ler) güncellendi: "
                f"{', '.join(affected)}", is_complete=True)
        return affected

    def _split_requirement(self, target):
        """Atomik olmayan bir maddeyi ('...ve...ve...') ayrı gereksinimlere böler.
        İlk parça orijinali günceller; diğerleri yeni ID'lerle (SR-002b, SR-002c...) eklenir,
        aynı üst maddeye bağlanır. Her yeni gereksinim parçasına bağlı bir test de üretilir."""
        from llm_handler import call_gemma3_api
        item = self.flat_data.get(target, {})
        content = item.get("content", "")
        itype = item.get("type", "")
        bound = item.get("bound_to", "")
        self._chat_append(f"{target} atomik parçalara bölünüyor...", "info")

        prompt = (
            "Aşağıdaki gereksinim maddesi birden fazla gereksinim içeriyor (atomik değil). "
            "Bunu, her biri TEK ve bağımsız bir gereksinim olan AYRI cümlelere böl.\n\n"
            f"MADDE: \"{content}\"\n\n"
            "Kurallar:\n"
            "- Her satıra yalnızca 1 gereksinim yaz; numara, işaret, etiket KOYMA.\n"
            "- Her biri tam bir 'sistem ... -malıdır' cümlesi olsun.\n"
            "- Orijinal anlamı KORU; yeni gereksinim uydurma, hiçbirini atlama.\n"
        )
        resp = call_gemma3_api(prompt, max_tokens=300, temperature=0.1,
                               system_message=self.COPILOT_SYSTEM_PROMPT)
        parts = []
        for ln in (resp or "").split("\n"):
            p = text_cleanup.temizle(ln)
            if p and len(p.split()) >= 3 and p not in parts:
                parts.append(p)
        if len(parts) < 2:
            self._chat_append(f"{target} bölünemedi (tek gereksinim gibi görünüyor).", "err")
            return

        test_gen = {
            "TID": kmtd_generator_logic.generate_kmtd_from_tid,
            "SGD": sitet_generator_logic.generate_sitet_from_sgd,
            "STT": alt_sistem_test_logic.generate_subsystem_test,
        }
        test_tip = {"TID": "KMTD", "SGD": "SITET", "STT": "AST"}
        test_pre = {"TID": "AT", "SGD": "SITET", "STT": "SST"}

        prefix, _, numpart = target.rpartition("-")
        olusan = [target]

        # 1) İlk parça orijinali günceller + (gereksinimse) testini senkronla
        self._apply_revision(target, content, parts[0])
        architecture_changed_ids = {target}
        if itype in self.REQ_TYPES:
            ripple_changed_ids = self._ripple_regenerate(target) or ()
            architecture_changed_ids.update(
                item_id for item_id in ripple_changed_ids
                if self.flat_data.get(item_id, {}).get("type") in self.REQ_TYPES
            )

        # 2) Diğer parçalar → yeni maddeler (+ bağlı test)
        harf = "bcdefghi"
        for i, p in enumerate(parts[1:]):
            son = harf[i] if i < len(harf) else str(i + 2)
            yid = f"{prefix}-{numpart}{son}"
            while yid in self.flat_data:
                yid += "x"
            self.flat_data[yid] = {"type": itype, "ID": yid, "content": p, "bound_to": bound}
            self.last_generated_output += f"\n{yid} | {p}"
            olusan.append(yid)
            architecture_changed_ids.add(yid)
            gen = test_gen.get(itype)
            if gen:
                try:
                    tt = text_cleanup.temizle(gen(p, "Proje") or "", test=True)
                except Exception:
                    tt = ""
                if tt:
                    tid_ = f"{test_pre[itype]}-{numpart}{son}"
                    while tid_ in self.flat_data:
                        tid_ += "x"
                    self.flat_data[tid_] = {"type": test_tip[itype], "ID": tid_,
                                            "content": tt, "bound_to": yid}
                    self.last_generated_output += f"\n{tid_} | {tt}"

        self.update_status_text(f"\n━━━ COPILOT · {target} BÖLÜNDÜ ({len(parts)} parça) ━━━",
                                is_complete=True)
        for pid in olusan:
            self.update_status_text(f"{pid}: {self.flat_data[pid]['content']}")
        self._chat_append(
            f"✅ {target} {len(parts)} atomik gereksinime bölündü: " + ", ".join(olusan)
            + "\n(Her yeni parçaya bağlı test de üretildi. İndirdiğinde çıktılara yansır.)", "bot")
        self.master.after(
            0,
            lambda ids=tuple(sorted(architecture_changed_ids)):
                self._notify_architecture_sources_changed(ids),
        )

    def _ripple_dsb(self, requirement_id):
        """
        Paydaş kuralı 5 — İZLENEBİLİRLİK YAYILIMI (ripple effect):
        Bir gereksinim maddesi 'DSB' içerecek şekilde revize edildiğinde, ona BAĞLI olan
        test maddelerini (KMTD/SITET/AST/DTET-YTET) bulur ve onların test kriterine de
        'DSB' notu ekler. Bağ ilişkisi: test maddesinin bound_to == gereksinim ID'si.
        Etkilenen test ID'lerinin listesini döndürür.
        """
        note = " (Not: İlgili gereksinimde DSB bulunduğu için test kriteri de DSB'dir.)"
        affected = []
        for item_id, d in list(self.flat_data.items()):
            if d.get("type") in self.TEST_TYPES and d.get("bound_to") == requirement_id:
                old_c = d.get("content", "")
                if "DSB" in old_c.upper():
                    continue  # zaten DSB'li → tekrar ekleme
                new_c = (old_c.rstrip() + note).strip()
                d["content"] = new_c
                self._sync_item_text(item_id, old_c, new_c)
                affected.append(item_id)
        if affected:
            self.update_status_text(
                f"[Copilot] DSB yayılımı → {requirement_id} bağlı test(ler)i güncellendi: "
                f"{', '.join(affected)}", is_complete=True)
        return affected

    # ------------------------------------------------------------------ #
    #  EXCEL / HTML / WORD çıktıları (hepsi flat_data + VMODEL_SECTIONS)  #
    # ------------------------------------------------------------------ #
