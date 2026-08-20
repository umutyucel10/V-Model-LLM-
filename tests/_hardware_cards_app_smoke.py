# -*- coding: utf-8 -*-
"""Gerçek EHSİM ana uygulamasında Donanım Kartları uçtan uca smoke testi."""

from pathlib import Path
import sys
import time

from PIL import ImageGrab
import ttkbootstrap as ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Arayüz import TIDGeneratorApp
import donanim_kartlari_yonetim as management


PROJECT_NAME = "EHSİM DONANIM KARTLARI SMOKE"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"


def _traceability() -> dict:
    return {
        "project_id": "EHSIM-HW-SMOKE",
        "project_name": PROJECT_NAME,
        "revision": 1,
        "nodes": [
            {
                "id": "DEMO-REQ-PWR-001",
                "node_type": "Sistem gereksinimi",
                "title": "DC/DC giriş gerilimi",
                "description": "DC/DC dönüştürücü 28 V ana besleme ile çalışmalıdır.",
                "v_model_level": "Sistem",
                "source_document": "Örnek güç gereksinimleri",
                "confidence_level": "Kesin",
            },
            {
                "id": "SAMPLE-DCDC",
                "node_type": "Parça/bileşen",
                "title": "DC/DC Dönüştürücü",
                "v_model_level": "Parça",
                "source_document": "Örnek BOM",
                "confidence_level": "Kesin",
            },
            {
                "id": "DEMO-TEST-PWR-001",
                "node_type": "Birim testi",
                "title": "DC/DC giriş ve çıkış doğrulaması",
                "v_model_level": "Birim doğrulaması",
                "source_document": "Örnek test prosedürü",
                "confidence_level": "Kesin",
            },
        ],
        "edges": [
            {
                "source_id": "DEMO-REQ-PWR-001", "target_id": "SAMPLE-DCDC",
                "relationship_type": "allocated_to", "confidence_level": "Kesin",
            },
            {
                "source_id": "DEMO-REQ-PWR-001", "target_id": "DEMO-TEST-PWR-001",
                "relationship_type": "verified_by", "confidence_level": "Kesin",
            },
        ],
        "unlinked_requirements": [], "unverified_requirements": [],
        "conflicts": [], "missing_information": [],
    }


def _capture(window, filename: str) -> Path:
    window.update_idletasks()
    x, y = window.winfo_rootx(), window.winfo_rooty()
    width, height = window.winfo_width(), window.winfo_height()
    path = OUTPUT_DIR / filename
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(path)
    return path


def main() -> None:
    started_at = time.perf_counter()
    root = ttk.Window()
    app = TIDGeneratorApp(root)
    app_ready_at = time.perf_counter()
    print(f"APP_INIT_SECONDS {app_ready_at - started_at:.3f}", flush=True)
    result: dict[str, object] = {}

    def run_flow() -> None:
        flow_started_at = time.perf_counter()
        try:
            project_entry = app.entry_widgets["proje_ismi"]
            project_entry.delete(0, "end")
            project_entry.insert(0, PROJECT_NAME)
            app.last_hardware_catalog = management.sample_catalog(PROJECT_NAME)
            app.last_traceability_report = _traceability()

            app.open_hardware_cards_workspace()
            cards = app.hardware_cards_workspace
            assert cards and cards.exists, "Donanım Kartları ana uygulamadan açılamadı."
            cards.window.geometry("1460x850+40+40")
            cards.select_card("SAMPLE-DCDC")
            root.update_idletasks()
            cards_ready_at = time.perf_counter()
            card_capture = _capture(cards.window, "ehsim_hardware_cards_app_smoke.png")

            cards._send_to_impact("SAMPLE-DCDC")
            impact = app.impact_analysis_workspace
            assert impact and impact.exists, "Etki Analizi ekranı karttan açılamadı."
            assert impact.alternatives == ["DC/DC Alternatif B", "DC/DC Alternatif C"]
            assert len(impact.parameters) >= 4, "Ortak teknik parametreler aktarılmadı."
            assert impact.hardware_context.get("requirement_ids") == ["DEMO-REQ-PWR-001"]
            impact.window.geometry("1240x780+80+60")
            root.update_idletasks()
            impact_ready_at = time.perf_counter()
            impact_capture = _capture(impact.window, "ehsim_hardware_to_impact_smoke.png")

            app._open_hardware_requirement("DEMO-REQ-PWR-001")
            root.update_idletasks()
            assert impact.simulation_panel.requirement_id.get() == "DEMO-REQ-PWR-001"
            assert impact.mode_notebook.index("current") == 1

            result.update({
                "cards": len(cards.catalog.get("hardware_items", [])),
                "alternatives": len(impact.alternatives),
                "parameters": len(impact.parameters),
                "requirement": impact.simulation_panel.requirement_id.get(),
                "card_capture": card_capture,
                "impact_capture": impact_capture,
            })
            flow_finished_at = time.perf_counter()
            print(
                "APP_SMOKE_OK "
                f"cards={result['cards']} alternatives={result['alternatives']} "
                f"parameters={result['parameters']} requirement={result['requirement']}",
                flush=True,
            )
            print(
                "APP_STAGE_SECONDS "
                f"cards_ready={cards_ready_at - flow_started_at:.3f} "
                f"impact_ready={impact_ready_at - cards_ready_at:.3f} "
                f"total={flow_finished_at - flow_started_at:.3f}",
                flush=True,
            )
            print(f"SCREENSHOT {card_capture}", flush=True)
            print(f"SCREENSHOT {impact_capture}", flush=True)
        except Exception as error:
            result["error"] = error
            print(f"APP_SMOKE_FAILED {type(error).__name__}: {error}", flush=True)
        finally:
            root.after(100, root.destroy)

    root.after(700, run_flow)
    root.mainloop()
    if "error" in result:
        raise result["error"]


if __name__ == "__main__":
    main()
