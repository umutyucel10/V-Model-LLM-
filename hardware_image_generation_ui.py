# -*- coding: utf-8 -*-
"""Donanım kartı AI görsel üretimi için onay kapılı Tkinter arayüzü."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Mapping, Sequence

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover
    Image = ImageTk = None

from donanim_kartlari_model import MISSING_VALUE, clean_text
from hardware_image_generation import (
    AI_CONCEPT_WARNING, discard_preview_file, generate_batch, has_any_image, has_real_image,
    store_generated_image, write_preview_file,
)
from hardware_image_prompt import VISUAL_TYPES, PromptPlan, prepare_prompt_with_gemma
from hardware_image_provider import (
    GeneratedImage, ImageGenerationCancelled, ImageGenerationProvider,
    ImageProviderError, create_image_provider,
)


NO_PROVIDER_MESSAGE = (
    "Gemma görsel üretim açıklaması hazırlayabilir; ancak görüntü dosyası "
    "oluşturmak için ayrı bir görsel üretim modeli yapılandırılmalıdır."
)

VIEWS = ("Ön 3/4 görünüm", "İzometrik", "Önden", "Yandan", "Üstten", "Sistem bağlamında")
BACKGROUNDS = ("Nötr açık gri", "Beyaz", "Şeffaf", "Teknik çalışma tezgâhı", "Sistem bağlamı")
ASPECT_RATIOS = ("1:1", "4:3", "3:2", "16:9", "9:16")
RESOLUTIONS = ("768 × 768", "1024 × 1024", "1152 × 768", "1344 × 768")


def _dimensions(value: str, ratio: str) -> tuple[int, int]:
    values = [int(number) for number in value.replace("×", "x").split("x") if number.strip().isdigit()]
    if len(values) == 2:
        return values[0], values[1]
    ratios = {"1:1": (1024, 1024), "4:3": (1024, 768), "3:2": (1152, 768), "16:9": (1344, 768), "9:16": (768, 1344)}
    return ratios.get(ratio, (1024, 1024))


class AIImageGenerationDialog(tk.Toplevel):
    """Prompt inceleme, üretim, önizleme ve iki aşamalı kabul penceresi."""

    def __init__(
        self,
        parent: tk.Misc,
        item: Mapping[str, Any],
        output_root: str | Path,
        on_accept: Callable[[Mapping[str, Any], bool], None],
        *,
        provider: ImageGenerationProvider | None = None,
        palette: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = dict(item); self.output_root = Path(output_root)
        self.on_accept = on_accept; self.provider = provider or create_image_provider()
        self.palette = dict(palette or {"bg": "#F4F6F8", "surface": "#FFFFFF", "fg": "#26323E", "muted": "#66727E", "accent": "#0759C7"})
        self.plan: PromptPlan | None = None; self.generated: GeneratedImage | None = None
        self.preview_path: Path | None = None; self.preview_photo: Any = None
        self._job_token = 0; self._provider_check_token = 0
        self._busy = False; self._provider_available = False
        self.title("AI Donanım Görseli · Kanıt Kontrollü Üretim")
        self.geometry("1120x780"); self.minsize(940, 680); self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build(); self._check_provider()

    def _build(self) -> None:
        self.configure(background=self.palette["bg"])
        self.columnconfigure(0, weight=1); self.rowconfigure(3, weight=1)
        style = ttk.Style(self)
        style.configure("AIWorkbench.TFrame", background=self.palette["bg"])
        style.configure("AIWorkbench.Surface.TFrame", background=self.palette["surface"])
        style.configure("AIWorkbench.Title.TLabel", background=self.palette["bg"], foreground=self.palette["fg"], font=("Segoe UI", 17, "bold"))
        style.configure("AIWorkbench.Meta.TLabel", background=self.palette["surface"], foreground=self.palette["muted"], font=("Consolas", 9))
        style.configure("AIWorkbench.Warning.TLabel", background="#FFF2CC", foreground="#8A5A00", font=("Segoe UI", 9, "bold"))
        style.configure("AIWorkbench.Step.TLabel", background=self.palette["surface"], foreground=self.palette["accent"], font=("Consolas", 9, "bold"))
        style.configure("AIWorkbench.Section.TLabel", background=self.palette["surface"], foreground=self.palette["fg"], font=("Segoe UI", 10, "bold"))

        header = ttk.Frame(self, style="AIWorkbench.TFrame", padding=(14, 10))
        header.grid(row=0, column=0, sticky="ew"); header.columnconfigure(0, weight=1)
        ttk.Label(header, text="AI DONANIM GÖRSELİ", style="AIWorkbench.Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"{clean_text(self.item.get('part_name'), MISSING_VALUE)}  ·  {clean_text(self.item.get('hardware_id'), MISSING_VALUE)}", style="AIWorkbench.Meta.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.provider_status = tk.StringVar(value="Görsel sağlayıcısı denetleniyor…")
        ttk.Label(header, textvariable=self.provider_status, style="AIWorkbench.Meta.TLabel").grid(row=0, column=1, rowspan=2, sticky="e")

        rail = ttk.Frame(self, style="AIWorkbench.Surface.TFrame", padding=(12, 8), borderwidth=1, relief="solid")
        rail.grid(row=1, column=0, sticky="ew", padx=12); rail.columnconfigure((0, 2, 4, 6, 8), weight=1)
        for index, label in enumerate(("KANIT", "PROMPT", "SAĞLAYICI", "ÖNİZLEME", "KULLANICI KARARI")):
            ttk.Label(rail, text=label, style="AIWorkbench.Step.TLabel", anchor="center").grid(row=0, column=index * 2, sticky="ew")
            if index < 4:
                ttk.Label(rail, text="→", style="AIWorkbench.Meta.TLabel").grid(row=0, column=index * 2 + 1)

        ttk.Label(self, text=AI_CONCEPT_WARNING, style="AIWorkbench.Warning.TLabel", anchor="center", padding=(8, 7)).grid(row=2, column=0, sticky="ew", padx=12, pady=(7, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=3, column=0, sticky="nsew", padx=12, pady=8)
        controls = ttk.Frame(body, style="AIWorkbench.Surface.TFrame", padding=11, borderwidth=1, relief="solid")
        prompt_panel = ttk.Frame(body, style="AIWorkbench.Surface.TFrame", padding=11, borderwidth=1, relief="solid")
        body.add(controls, weight=2); body.add(prompt_panel, weight=3)
        controls.columnconfigure(1, weight=1); controls.rowconfigure(9, weight=1)
        prompt_panel.columnconfigure(0, weight=1); prompt_panel.rowconfigure(2, weight=1)

        ttk.Label(controls, text="ÜRETİM AYARLARI", style="AIWorkbench.Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))
        self.visual_type = tk.StringVar(value=VISUAL_TYPES[0]); self.view = tk.StringVar(value=VIEWS[0])
        self.background = tk.StringVar(value=BACKGROUNDS[0]); self.aspect = tk.StringVar(value=ASPECT_RATIOS[0])
        self.resolution = tk.StringVar(value=RESOLUTIONS[1]); self.model = tk.StringVar(value="Sağlayıcı modeli bekleniyor")
        for row, (label, variable, values) in enumerate((
            ("Görsel türü", self.visual_type, VISUAL_TYPES), ("Bakış açısı", self.view, VIEWS),
            ("Arka plan", self.background, BACKGROUNDS), ("En-boy oranı", self.aspect, ASPECT_RATIOS),
            ("Çözünürlük", self.resolution, RESOLUTIONS), ("Görsel modeli", self.model, (self.model.get(),)),
        ), 1):
            ttk.Label(controls, text=label, style="AIWorkbench.Meta.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            combo = ttk.Combobox(controls, textvariable=variable, values=values, state="readonly")
            combo.grid(row=row, column=1, sticky="ew", pady=3)
            if label == "Görsel modeli": self.model_combo = combo

        ttk.Label(controls, text="İlave açıklama (varsayım olarak işaretlenir)", style="AIWorkbench.Meta.TLabel").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 3))
        self.additional = tk.Text(controls, height=5, wrap="word", font=("Segoe UI", 9), relief="solid", borderwidth=1)
        self.additional.configure(
            background=self.palette["surface"], foreground=self.palette["fg"],
            insertbackground=self.palette["fg"], selectbackground=self.palette["accent"],
            selectforeground="#FFFFFF",
        )
        self.additional.grid(row=8, column=0, columnspan=2, sticky="ew")
        self.preview_canvas = tk.Canvas(controls, height=220, background="#F3F5F7", highlightthickness=1, highlightbackground="#D4DAE0")
        self.preview_canvas.grid(row=9, column=0, columnspan=2, sticky="nsew", pady=(9, 0))
        self.preview_canvas.create_text(205, 105, text="ÖNİZLEME BEKLENİYOR", fill="#66727E", font=("Consolas", 9))

        ttk.Label(prompt_panel, text="GEMMA PROMPT PLANI", style="AIWorkbench.Section.TLabel").grid(row=0, column=0, sticky="w")
        self.plan_meta = tk.StringVar(value="Prompt henüz hazırlanmadı.")
        ttk.Label(prompt_panel, textvariable=self.plan_meta, style="AIWorkbench.Meta.TLabel", wraplength=570, justify="left").grid(row=1, column=0, sticky="ew", pady=(3, 7))
        prompt_holder = ttk.Frame(prompt_panel, style="AIWorkbench.Surface.TFrame")
        prompt_holder.grid(row=2, column=0, sticky="nsew"); prompt_holder.columnconfigure(0, weight=1); prompt_holder.rowconfigure(1, weight=3); prompt_holder.rowconfigure(3, weight=1)
        ttk.Label(prompt_holder, text="Düzenlenebilir prompt", style="AIWorkbench.Meta.TLabel").grid(row=0, column=0, sticky="w")
        self.prompt_text = tk.Text(prompt_holder, wrap="word", font=("Consolas", 9), undo=True, relief="solid", borderwidth=1)
        self.prompt_text.configure(
            background=self.palette["surface"], foreground=self.palette["fg"],
            insertbackground=self.palette["fg"], selectbackground=self.palette["accent"],
            selectforeground="#FFFFFF",
        )
        self.prompt_text.grid(row=1, column=0, sticky="nsew", pady=(3, 8))
        ttk.Label(prompt_holder, text="Negative prompt", style="AIWorkbench.Meta.TLabel").grid(row=2, column=0, sticky="w")
        self.negative_text = tk.Text(prompt_holder, height=6, wrap="word", font=("Consolas", 8), undo=True, relief="solid", borderwidth=1)
        self.negative_text.configure(
            background=self.palette["surface"], foreground=self.palette["fg"],
            insertbackground=self.palette["fg"], selectbackground=self.palette["accent"],
            selectforeground="#FFFFFF",
        )
        self.negative_text.grid(row=3, column=0, sticky="nsew", pady=(3, 0))

        footer = ttk.Frame(self, style="AIWorkbench.TFrame", padding=(12, 0, 12, 11))
        footer.grid(row=4, column=0, sticky="ew"); footer.columnconfigure(2, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=160); self.progress.grid(row=0, column=0, padx=(0, 8), pady=(0, 6))
        self.status = tk.StringVar(value="Önce Gemma ile prompt hazırlayın.")
        ttk.Label(footer, textvariable=self.status, style="AIWorkbench.Title.TLabel", font=("Segoe UI", 9)).grid(row=0, column=1, columnspan=8, sticky="w", pady=(0, 6))
        self.prepare_button = ttk.Button(footer, text="1 · Gemma ile Prompt Hazırla", command=self._prepare_prompt)
        self.prepare_button.grid(row=1, column=3, padx=3)
        self.copy_button = ttk.Button(footer, text="Promptu Kopyala", command=self._copy_prompt, state="disabled")
        self.copy_button.grid(row=1, column=4, padx=3)
        self.generate_button = ttk.Button(footer, text="2 · Görseli Üret", command=self._generate, state="disabled")
        self.generate_button.grid(row=1, column=5, padx=3)
        self.accept_button = ttk.Button(footer, text="3 · Kabul Et", command=self._accept, state="disabled")
        self.accept_button.grid(row=1, column=6, padx=3)
        self.reject_button = ttk.Button(footer, text="Reddet", command=self._reject, state="disabled")
        self.reject_button.grid(row=1, column=7, padx=3)
        ttk.Button(footer, text="Kapat", command=self.close).grid(row=1, column=8, padx=(8, 0))

    def _generation_options(self) -> dict[str, Any]:
        width, height = _dimensions(self.resolution.get(), self.aspect.get())
        return {
            "visual_type": self.visual_type.get(), "view": self.view.get(),
            "background": self.background.get(), "aspect_ratio": self.aspect.get(),
            "resolution": self.resolution.get(), "width": width, "height": height,
            "model": "" if self.model.get().startswith("Sağlayıcı") else self.model.get(),
            "additional_description": self.additional.get("1.0", "end").strip(),
        }

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy; self.status.set(message)
        if busy:
            self.progress.start(12); self.prepare_button.configure(state="disabled"); self.generate_button.configure(state="disabled")
        else:
            self.progress.stop(); self.prepare_button.configure(state="normal")
            self.generate_button.configure(state="normal" if self.plan and self._provider_available else "disabled")

    def _check_provider(self) -> None:
        self._provider_check_token += 1; token = self._provider_check_token
        results: queue.Queue[tuple[dict[str, Any], list[str]]] = queue.Queue(maxsize=1)
        def worker() -> None:
            try: results.put((self.provider.health_check(), self.provider.list_models()))
            except Exception: results.put(({"available": False, "message": "Görsel sağlayıcısına bağlanılamadı."}, []))
        threading.Thread(target=worker, daemon=True, name="image-provider-health").start()
        self.after(60, lambda: self._poll_provider(token, results))

    def _poll_provider(self, token: int, results: queue.Queue) -> None:
        if token != self._provider_check_token or not self.winfo_exists(): return
        try: health, models = results.get_nowait()
        except queue.Empty:
            self.after(60, lambda: self._poll_provider(token, results)); return
        self._provider_available = bool(health.get("available"))
        self.provider_status.set(f"Sağlayıcı: {health.get('provider', self.provider.provider_name)} · {health.get('message', '')}")
        values = models or ["Model yapılandırılmadı"]
        self.model_combo.configure(values=values); self.model.set(values[0])
        if not self._provider_available:
            self.status.set(NO_PROVIDER_MESSAGE)
        elif self.plan:
            self.generate_button.configure(state="normal")

    def _prepare_prompt(self) -> None:
        if self._busy: return
        self._set_busy(True, "Gemma doğrulanmış kart alanlarından prompt hazırlıyor…")
        token = self._job_token = self._job_token + 1
        results: queue.Queue[tuple[PromptPlan | None, str]] = queue.Queue(maxsize=1)
        item, options = dict(self.item), self._generation_options()
        def worker() -> None:
            try: results.put((prepare_prompt_with_gemma(item, options), ""))
            except Exception as error: results.put((None, str(error)))
        threading.Thread(target=worker, daemon=True, name="gemma-image-prompt").start()
        self.after(70, lambda: self._poll_prompt(token, results))

    def _poll_prompt(self, token: int, results: queue.Queue) -> None:
        if token != self._job_token or not self.winfo_exists(): return
        try: plan, error = results.get_nowait()
        except queue.Empty:
            self.after(70, lambda: self._poll_prompt(token, results)); return
        if error or plan is None:
            self._set_busy(False, f"Prompt hazırlanamadı: {error}"); return
        self.plan = plan
        for widget, value in ((self.prompt_text, plan.prompt), (self.negative_text, plan.negative_prompt)):
            widget.delete("1.0", "end"); widget.insert("1.0", value)
        self.plan_meta.set(
            f"Yöntem: {plan.preparation_method} · Kullanılan doğrulanmış alan: {len(plan.known_features_used)} · "
            f"Dışarıda bırakılan bilinmeyen alan: {len(plan.unknown_features_omitted)} · Önerilen bakış: {plan.recommended_view}"
        )
        self.copy_button.configure(state="normal")
        message = "Prompt hazır; üretimden önce inceleyip düzenleyebilirsiniz."
        if not self._provider_available: message = NO_PROVIDER_MESSAGE
        self._set_busy(False, message)

    def _copy_prompt(self) -> None:
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt: return
        self.clipboard_clear(); self.clipboard_append(prompt); self.status.set("Prompt panoya kopyalandı.")

    def _generate(self) -> None:
        if self._busy or not self.plan: return
        if not self._provider_available:
            messagebox.showinfo("Görsel Sağlayıcısı Yok", NO_PROVIDER_MESSAGE, parent=self); return
        prompt = self.prompt_text.get("1.0", "end").strip()
        negative = self.negative_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Prompt Gerekli", "Görsel üretim promptu boş bırakılamaz.", parent=self); return
        if not messagebox.askyesno(
            "Kavramsal Görsel Üretimi",
            f"Ayrı görsel sağlayıcısıyla üretim başlatılsın mı?\n\n{AI_CONCEPT_WARNING}", parent=self,
        ): return
        self._reject(clear_status=False); self._set_busy(True, "Görsel sağlayıcısı resmi arka planda üretiyor…")
        token = self._job_token = self._job_token + 1
        results: queue.Queue[tuple[GeneratedImage | None, str]] = queue.Queue(maxsize=1)
        options = self._generation_options()
        def worker() -> None:
            try: results.put((self.provider.generate_image(prompt, negative, options), ""))
            except Exception as error: results.put((None, str(error)))
        threading.Thread(target=worker, daemon=True, name="hardware-image-generation").start()
        self.after(80, lambda: self._poll_generation(token, results))

    def _poll_generation(self, token: int, results: queue.Queue) -> None:
        if token != self._job_token or not self.winfo_exists(): return
        try: generated, error = results.get_nowait()
        except queue.Empty:
            self.after(80, lambda: self._poll_generation(token, results)); return
        if error or generated is None:
            self._set_busy(False, f"Görsel üretilemedi: {error}"); return
        try:
            self.generated = generated; self.preview_path = write_preview_file(generated)
            self._show_preview(generated.image_bytes)
        except Exception as preview_error:
            self.generated = None; self._set_busy(False, f"Üretilen görsel doğrulanamadı: {preview_error}"); return
        self.accept_button.configure(state="normal"); self.reject_button.configure(state="normal")
        self._set_busy(False, "Önizleme hazır. Galeriye eklemek için Kabul Et düğmesine basın.")

    def _show_preview(self, data: bytes) -> None:
        self.preview_canvas.delete("all")
        self.preview_canvas.update_idletasks()
        canvas_width = max(320, self.preview_canvas.winfo_width())
        canvas_height = max(140, self.preview_canvas.winfo_height())
        if not Image or not ImageTk:
            self.preview_canvas.create_text(canvas_width // 2, canvas_height // 2, text="GÖRSEL DOĞRULANDI\nÖnizleme için Pillow gerekli", fill="#0759C7", justify="center"); return
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGBA")
            image.thumbnail((canvas_width - 20, max(80, canvas_height - 48)), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        image_area_height = canvas_height - 34
        self.preview_canvas.create_image(canvas_width // 2, image_area_height // 2, image=self.preview_photo)
        self.preview_canvas.create_rectangle(4, canvas_height - 30, canvas_width - 4, canvas_height - 4, fill="#FFF2CC", outline="")
        self.preview_canvas.create_text(canvas_width // 2, canvas_height - 17, text="AI KAVRAMSAL · TEKNİK DOĞRULAMA İÇİN KULLANILAMAZ", fill="#8A5A00", font=("Consolas", 7, "bold"))

    def _accept(self) -> None:
        if not self.generated or not self.plan: return
        prompt = self.prompt_text.get("1.0", "end").strip(); negative = self.negative_text.get("1.0", "end").strip()
        try:
            record = store_generated_image(
                self.generated, self.output_root, clean_text(self.item.get("hardware_id"), "donanim"),
                prompt=prompt, negative_prompt=negative, caption=self.plan.caption,
                card_version=clean_text(self.item.get("version"), MISSING_VALUE),
                verified_fields=self.plan.known_features_used, generation_options=self._generation_options(),
            )
            make_cover = messagebox.askyesno(
                "Kapak Görseli Onayı",
                "AI kavramsal görsel galeriye eklenecek. Ayrıca kartın kapak görseli yapılsın mı?\n\n"
                "Gerçek/datasheet görsel varsa Hayır seçmeniz önerilir.", parent=self,
            )
            self.on_accept(record, make_cover)
        except Exception as error:
            messagebox.showerror("Görsel Kaydedilemedi", str(error), parent=self); return
        discard_preview_file(self.preview_path); self.preview_path = None
        messagebox.showinfo("Görsel Kabul Edildi", "AI kavramsal görsel metadata ve uyarısıyla galeriye eklendi.", parent=self)
        self.destroy()

    def _reject(self, clear_status: bool = True) -> None:
        discard_preview_file(self.preview_path); self.preview_path = None; self.generated = None; self.preview_photo = None
        self.accept_button.configure(state="disabled"); self.reject_button.configure(state="disabled")
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            max(160, self.preview_canvas.winfo_width() // 2),
            max(70, self.preview_canvas.winfo_height() // 2),
            text="ÖNİZLEME BEKLENİYOR", fill="#66727E", font=("Consolas", 9),
        )
        if clear_status: self.status.set("Önizleme reddedildi; kalıcı kataloğa eklenmedi.")

    def close(self) -> None:
        self._job_token += 1
        if self._busy: self.provider.cancel_generation()
        discard_preview_file(self.preview_path); self.preview_path = None
        self.destroy()


class BulkAIImageDialog(tk.Toplevel):
    """Varsayılan kapalı, açık onaylı ve iptal edilebilir toplu üretim penceresi."""

    def __init__(
        self, parent: tk.Misc, items: Sequence[Mapping[str, Any]], output_root: str | Path,
        on_finished: Callable[[Mapping[str, Mapping[str, Any]]], None],
        *, provider: ImageGenerationProvider | None = None,
    ) -> None:
        super().__init__(parent); self.items = [dict(item) for item in items]
        self.output_root = Path(output_root); self.on_finished = on_finished
        self.provider = provider or create_image_provider(); self.cancel_event = threading.Event(); self._running = False
        self.eligible = [item for item in self.items if not has_any_image(item)]
        self.title("Toplu AI Görsel Üretimi"); self.geometry("700x430"); self.minsize(620, 390); self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close); self._build(); self._health_check()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1); self.rowconfigure(3, weight=1)
        ttk.Label(self, text="TOPLU AI GÖRSEL ÜRETİMİ", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 3))
        ttk.Label(self, text=f"{len(self.items)} kart incelendi · {len(self.eligible)} kartta gerçek görsel yok · {len(self.items)-len(self.eligible)} gerçek görsel korunarak atlanacak", font=("Consolas", 9)).grid(row=1, column=0, sticky="w", padx=14)
        ttk.Label(self, text=AI_CONCEPT_WARNING, foreground="#8A5A00", background="#FFF2CC", anchor="center", padding=8).grid(row=2, column=0, sticky="ew", padx=14, pady=10)
        panel = ttk.Frame(self, padding=12, borderwidth=1, relief="solid"); panel.grid(row=3, column=0, sticky="nsew", padx=14); panel.columnconfigure(1, weight=1)
        self.visual_type = tk.StringVar(value=VISUAL_TYPES[0]); self.model = tk.StringVar(value="Model bekleniyor"); self.resolution = tk.StringVar(value=RESOLUTIONS[1])
        for row, (label, variable, values) in enumerate((("Görsel türü", self.visual_type, VISUAL_TYPES), ("Model", self.model, (self.model.get(),)), ("Çözünürlük", self.resolution, RESOLUTIONS))):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            combo = ttk.Combobox(panel, textvariable=variable, values=values, state="readonly"); combo.grid(row=row, column=1, sticky="ew", pady=4)
            if row == 1: self.model_combo = combo
        self.status = tk.StringVar(value="Sağlayıcı denetleniyor…"); ttk.Label(panel, textvariable=self.status, wraplength=580, justify="left").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 6))
        self.progress = ttk.Progressbar(panel, mode="determinate", maximum=max(1, len(self.eligible))); self.progress.grid(row=4, column=0, columnspan=2, sticky="ew")
        actions = ttk.Frame(self); actions.grid(row=4, column=0, sticky="e", padx=14, pady=12)
        self.start_button = ttk.Button(actions, text="Toplu Üretimi Başlat", command=self.start, state="disabled"); self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="İptal", command=self.cancel, state="disabled"); self.cancel_button.pack(side="left", padx=6)
        ttk.Button(actions, text="Kapat", command=self.close).pack(side="left")

    def _health_check(self) -> None:
        results: queue.Queue[tuple[dict[str, Any], list[str]]] = queue.Queue(maxsize=1)
        def worker() -> None:
            try: results.put((self.provider.health_check(), self.provider.list_models()))
            except Exception: results.put(({"available": False}, []))
        threading.Thread(target=worker, daemon=True, name="bulk-image-health").start()
        def poll() -> None:
            try: health, models = results.get_nowait()
            except queue.Empty:
                if self.winfo_exists(): self.after(60, poll)
                return
            values = models or ["Model yapılandırılmadı"]; self.model_combo.configure(values=values); self.model.set(values[0])
            available = bool(health.get("available"))
            self.status.set(health.get("message") if available else NO_PROVIDER_MESSAGE)
            self.start_button.configure(state="normal" if available and self.eligible else "disabled")
        self.after(60, poll)

    def start(self) -> None:
        if self._running or not self.eligible: return
        if not messagebox.askyesno("Toplu Üretim Onayı", f"{len(self.eligible)} kart için AI kavramsal görsel üretilecek. Devam edilsin mi?\n\nGerçek görseller atlanacak; hiçbir AI görseli otomatik kapak yapılmayacak.", parent=self): return
        self._running = True; self.cancel_event.clear(); self.start_button.configure(state="disabled"); self.cancel_button.configure(state="normal"); self.status.set("Toplu üretim başladı…")
        events: queue.Queue[tuple[str, Any]] = queue.Queue()
        options = {"visual_type": self.visual_type.get(), "model": self.model.get(), "resolution": self.resolution.get(), "width": _dimensions(self.resolution.get(), "1:1")[0], "height": _dimensions(self.resolution.get(), "1:1")[1]}
        def prompt_builder(item: Mapping[str, Any]) -> Mapping[str, Any]:
            return prepare_prompt_with_gemma(item, options).to_dict()
        def progress(current: int, total: int, hardware_id: str) -> None:
            events.put(("progress", (current, total, hardware_id)))
        def worker() -> None:
            result = generate_batch(self.items, self.provider, prompt_builder, self.output_root, options=options, cancel_event=self.cancel_event, progress_callback=progress)
            events.put(("done", result))
        threading.Thread(target=worker, daemon=True, name="bulk-hardware-images").start()
        self.after(80, lambda: self._poll(events))

    def _poll(self, events: queue.Queue) -> None:
        if not self.winfo_exists(): return
        done = None
        while True:
            try: event, payload = events.get_nowait()
            except queue.Empty: break
            if event == "progress":
                current, total, hardware_id = payload; self.progress.configure(maximum=max(1, total), value=current); self.status.set(f"{current}/{total} · {hardware_id}")
            elif event == "done": done = payload
        if done is None:
            self.after(80, lambda: self._poll(events)); return
        self._running = False; self.cancel_button.configure(state="disabled"); self.start_button.configure(state="normal" if self.eligible else "disabled")
        if done.generated: self.on_finished(done.generated)
        self.status.set(
            f"Tamamlandı · {len(done.generated)} üretildi · {len(done.skipped_real_images)} gerçek görsel atlandı · "
            f"{len(done.skipped_existing_images)} mevcut kavramsal görsel atlandı · {len(done.failed)} hata"
            + (" · kullanıcı iptal etti" if done.cancelled else "")
        )

    def cancel(self) -> None:
        if self._running:
            self.cancel_event.set(); self.provider.cancel_generation(); self.status.set("İptal isteniyor; mevcut sağlayıcı çağrısının kapanması bekleniyor…")

    def close(self) -> None:
        if self._running:
            self.cancel(); return
        self.destroy()


__all__ = ["AIImageGenerationDialog", "BulkAIImageDialog", "NO_PROVIDER_MESSAGE"]
