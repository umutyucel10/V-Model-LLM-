# -*- coding: utf-8 -*-
"""AI görsel üretim tezgâhını Mock sağlayıcıyla gerçek Tk penceresinde doğrular."""

from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from ttkbootstrap.style import Style

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hardware_image_generation_ui as ui
from hardware_image_prompt import deterministic_prompt_plan
from hardware_image_provider import MockImageProvider


def main() -> None:
    root = tk.Tk(); root.withdraw(); Style(theme="litera")
    item = {
        "hardware_id": "QA-BRAKE-PAD", "part_name": "Kompozit Fren Balatası",
        "hardware_type": "Parça/bileşen", "system_role": "Fren diskinde sürtünme üretir",
        "technical_data": {"length": "120", "width": "55", "dimension_unit": "mm"},
        "source_evidence": [
            {"field_name": "part_name", "certainty": "Kesin bilgi", "source_document": "qa-fren.pdf"},
            {"field_name": "hardware_type", "certainty": "Kesin bilgi", "source_document": "qa-fren.pdf"},
            {"field_name": "system_role", "certainty": "Kesin bilgi", "source_document": "qa-fren.pdf"},
            {"field_name": "length", "certainty": "Kesin bilgi", "source_document": "qa-datasheet.pdf"},
            {"field_name": "width", "certainty": "Kesin bilgi", "source_document": "qa-datasheet.pdf"},
            {"field_name": "dimension_unit", "certainty": "Kesin bilgi", "source_document": "qa-datasheet.pdf"},
        ],
        "version": "v0004",
    }
    accepted = []
    original_prepare = ui.prepare_prompt_with_gemma
    original_ask = ui.messagebox.askyesno
    original_info = ui.messagebox.showinfo
    ui.prepare_prompt_with_gemma = lambda card, options: deterministic_prompt_plan(card, options)
    ui.messagebox.askyesno = lambda *args, **kwargs: True
    ui.messagebox.showinfo = lambda *args, **kwargs: None
    output_root = Path(tempfile.mkdtemp(prefix="ehsim-ai-qa-"))
    dialog = ui.AIImageGenerationDialog(
        root, item, output_root, lambda record, cover: accepted.append((record, cover)),
        provider=MockImageProvider(delay=.50),
    )
    dialog.geometry("1120x780"); dialog.update_idletasks(); dialog.deiconify(); dialog.lift()

    deadline = time.time() + 3
    while not dialog._provider_available and time.time() < deadline:
        root.update(); time.sleep(.02)
    assert dialog._provider_available
    dialog._prepare_prompt()
    while dialog.plan is None and time.time() < deadline:
        root.update(); time.sleep(.02)
    assert dialog.plan is not None

    heartbeats = [0]
    def heartbeat() -> None:
        if dialog.winfo_exists() and dialog.generated is None:
            heartbeats[0] += 1; dialog.after(25, heartbeat)
    dialog.after(25, heartbeat)
    dialog._generate()
    generation_deadline = time.time() + 4
    while dialog.generated is None and time.time() < generation_deadline:
        root.update(); time.sleep(.015)
    assert dialog.generated is not None
    assert heartbeats[0] >= 5, "Arayüz olay döngüsü üretim sırasında çalışmadı."
    dialog.update_idletasks()

    root_x, root_y = dialog.winfo_rootx(), dialog.winfo_rooty()
    root_w, root_h = dialog.winfo_width(), dialog.winfo_height()
    overflows = []
    for index, widget in enumerate(dialog.winfo_children()):
        x, y = widget.winfo_rootx() - root_x, widget.winfo_rooty() - root_y
        width, height = widget.winfo_width(), widget.winfo_height()
        if x < -2 or y < -2 or x + width > root_w + 2 or y + height > root_h + 2:
            overflows.append(str(index))
    output = Path(__file__).resolve().parents[1] / "outputs" / "ui_qa" / "ehsim_ai_image_workbench.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(root_x, root_y, root_x + root_w, root_y + root_h)).save(output)
        print(f"SCREENSHOT {output}")
    except Exception as error:
        print(f"SCREENSHOT_UNAVAILABLE {error}")
    print(f"AI_IMAGE_QA_READY overflows={','.join(overflows) or 'none'} heartbeats={heartbeats[0]} prompt={len(dialog.prompt_text.get('1.0', 'end').strip())} preview={bool(dialog.preview_photo)}")
    dialog._reject(); dialog.close(); root.update()
    ui.prepare_prompt_with_gemma = original_prepare
    ui.messagebox.askyesno = original_ask; ui.messagebox.showinfo = original_info
    root.destroy()


if __name__ == "__main__":
    main()
