# -*- coding: utf-8 -*-
"""EHSİM'i yalnızca bu çalıştırmada Gemma 4 E4B ile başlatır.

Normal ``Arayüz.py`` açılışı Gemma 3 4B ayarını korur.
"""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


GEMMA_4_E4B_MODEL = "google/gemma-4-e4b"


def configure_one_shot_model() -> None:
    os.environ["EHSIM_LM_MODEL"] = GEMMA_4_E4B_MODEL


def check_model() -> int:
    configure_one_shot_model()
    from lmstudio_model import probe_model

    result = probe_model(GEMMA_4_E4B_MODEL)
    print(result.message)
    if result.loaded_models:
        print("LM Studio yüklü modeller: " + ", ".join(result.loaded_models))
    if not result.ready:
        return 2

    from llm_handler import call_gemma3_api
    response = call_gemma3_api(
        "Yalnızca 'Gemma 4 E4B test başarılı' yaz.",
        # Gemma 4 düşünme belirteçlerini de bu bütçeden kullanır.
        max_tokens=256,
        temperature=0.0,
    )
    if not response:
        print("Model seçildi ancak örnek yanıt alınamadı.")
        return 3
    print("Model yanıtı: " + response.strip())
    return 0


def launch_app() -> None:
    configure_one_shot_model()
    print(f"EHSİM tek seferlik model ile başlatılıyor: {GEMMA_4_E4B_MODEL}")
    runpy.run_path(
        str(Path(__file__).resolve().with_name("Arayüz.py")),
        run_name="__main__",
    )


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(check_model())
    launch_app()
