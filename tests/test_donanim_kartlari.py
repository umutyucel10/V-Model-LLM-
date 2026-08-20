# -*- coding: utf-8 -*-

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import donanim_kartlari_algilama as detection
from donanim_kartlari_model import (
    AlternativeLink,
    CONFIDENCE_WEIGHTS,
    HardwareCard,
    HardwareCatalog,
    MISSING_VALUE,
    SourceEvidence,
    TechnicalData,
    calculate_card_confidence,
)


def traceability_report(revision=1):
    return {
        "revision": revision,
        "nodes": [
            {"id": "SGD-001", "node_type": "Sistem gereksinimi", "title": "Kontrol"},
            {"id": "SITET-001", "node_type": "Sistem doğrulama testi", "title": "Kontrol testi"},
            {"id": "HW-001", "node_type": "Parça/bileşen", "title": "Ana Kontrol Kartı"},
        ],
        "edges": [
            {
                "source_id": "SGD-001", "target_id": "HW-001",
                "relationship_type": "allocated_to", "evidence_text": "Açık tahsis",
                "source_document": "SGD",
            },
            {
                "source_id": "SGD-001", "target_id": "SITET-001",
                "relationship_type": "verified_by", "evidence_text": "Açık test bağı",
                "source_document": "SITET",
            },
        ],
    }


def structured_hardware():
    return {
        "HW-ROOT": {
            "ID": "HW-ROOT",
            "description": "Fren Kontrol Sistemi",
            "category": "Sistem",
        },
        "HW-001": {
            "ID": "HW-001",
            "description": "Ana Kontrol Kartı",
            "manufacturer": "EHSİM",
            "part_number": "AKK-100",
            "model": "M1",
            "category": "Kart/modül",
            "rationale": "Fren komutlarını işler.",
            "parent_id": "HW-ROOT",
            "linked_requirements": ["SGD-001"],
            "specifications": {
                "Çalışma Sıcaklığı": "-40 °C - +85 °C",
                "Boyutlar": "100 x 50 x 20 mm",
                "Besleme Gerilimi": "28 VDC",
                "Haberleşme": "CAN, RS-485",
            },
            "instances": [
                {"location": "Sol kanal", "parent_id": "HW-ROOT", "quantity": 1},
                {"location": "Sağ kanal", "parent_id": "HW-ROOT", "quantity": 1},
            ],
            "alternatives": ["HW-002"],
        },
        "HW-002": {
            "ID": "HW-002",
            "description": "Yedek Kontrol Kartı",
            "manufacturer": "EHSİM",
            "part_number": "YKK-200",
            "category": "Kart/modül",
        },
    }


class HardwareCardModelTests(unittest.TestCase):
    def test_missing_values_are_not_zero(self):
        card = HardwareCard(hardware_id="HW-001", part_name="Sensör")
        self.assertEqual(card.part_number, MISSING_VALUE)
        self.assertEqual(card.technical_data.weight, MISSING_VALUE)
        self.assertNotEqual(card.technical_data.weight, 0)

    def test_temperature_dimensions_and_units(self):
        data, matches = detection.extract_technical_data(
            "Çalışma sıcaklığı: -40 °C ila +85 °C; "
            "Depolama sıcaklığı: -55°C - +125°C; "
            "Boyutlar: 10 x 20 x 30 mm; Ağırlık: 1,5 kg; "
            "Besleme gerilimi: 28 VDC; Güç tüketimi: 12 W; CAN ve RS-485"
        )
        self.assertEqual((data.operating_temperature_min, data.operating_temperature_max), (-40.0, 85.0))
        self.assertEqual((data.storage_temperature_min, data.storage_temperature_max), (-55.0, 125.0))
        self.assertEqual((data.length, data.width, data.height), (10.0, 20.0, 30.0))
        self.assertEqual(data.dimension_unit, "mm")
        self.assertEqual((data.weight, data.weight_unit), (1.5, "kg"))
        self.assertEqual(data.supply_voltage, "28 VDC")
        self.assertIn("CAN", data.communication_interfaces)
        self.assertIn("operating_temperature", matches)

    def test_confidence_weights_are_deterministic(self):
        self.assertEqual(sum(CONFIDENCE_WEIGHTS.values()), 100.0)
        card = HardwareCard(
            hardware_id="HW-001", part_name="Kart", part_number="P-1",
            manufacturer="Üretici", hardware_type="Kart/modül",
            description="Kontrol kartı", system_role="Kontrol",
            technical_data=TechnicalData(supply_voltage="28 VDC"),
            requirement_ids=["SGD-001"], test_ids=["SITET-001"],
            source_evidence=[
                SourceEvidence("hardware_id", "Liste", field_confidence=100),
                SourceEvidence("part_name", "Datasheet", extraction_method="datasheet_label", field_confidence=95),
            ],
        )
        score, explanation = calculate_card_confidence(card)
        self.assertEqual(score, 100.0)
        self.assertIn("LM Studio güven değeri kullanılmadı", explanation["note"])

    def test_unapproved_full_compatibility_is_downgraded(self):
        link = AlternativeLink(
            "HW-001", "HW-002", compatibility_status="Tam uyumlu",
            source="Belge", user_approval="Onay bekliyor",
        )
        self.assertEqual(link.compatibility_status, "Koşullu uyumlu")


class HardwareDetectionTests(unittest.TestCase):
    def test_hardware_is_detected_from_structured_requirement_text(self):
        records = {
            "SGD-009": {
                "ID": "SGD-009", "type": "SGD",
                "content": (
                    "Ana kontrol kartı 28 VDC besleme ile CAN arayüzünü "
                    "desteklemelidir."
                ),
            }
        }
        catalog = detection.build_or_update_hardware_catalog(
            "Gereksinim", structured_records=records, persist=False,
        )
        self.assertEqual(len(catalog.hardware_items), 1)
        card = catalog.hardware_items[0]
        self.assertEqual(card.part_name, "Ana kontrol kartı")
        self.assertEqual(card.requirement_ids, ["SGD-009"])
        self.assertEqual(card.technical_data.supply_voltage, "28 VDC")
        self.assertIn("CAN", card.technical_data.communication_interfaces)

    def test_turkish_plural_and_possessive_hardware_names_are_normalized(self):
        records = {
            "SR-001": {
                "ID": "SR-001", "type": "SGD",
                "content": "Kompozit fren pabuçları mevcut araçla uyumlu olmalıdır.",
            },
            "SR-002": {
                "ID": "SR-002", "type": "SGD",
                "content": "Kompozit disk fren balatalarının ağırlığı 1.2 kg'dan az olmalıdır.",
            },
            "SSR-001": {
                "ID": "SSR-001", "type": "STT",
                "content": "Fren sistemi kontrol ünitesiyle CAN üzerinden haberleşmelidir.",
            },
        }
        catalog = detection.build_or_update_hardware_catalog(
            "Türkçe", structured_records=records, persist=False,
        )
        names = {item.part_name for item in catalog.hardware_items}
        self.assertEqual(
            names,
            {
                "Kompozit Fren Pabucu", "Kompozit Disk Fren Balatası",
                "Fren Sistemi Kontrol Ünitesi",
            },
        )
        self.assertEqual(len(catalog.product_instances), 3)

    def test_structured_detection_links_and_product_tree(self):
        catalog = detection.build_or_update_hardware_catalog(
            "Fren", traceability_report=traceability_report(),
            structured_hardware=structured_hardware(), persist=False,
        )
        self.assertEqual(len(catalog.hardware_items), 3)
        card = next(item for item in catalog.hardware_items if item.hardware_id == "HW-001")
        self.assertEqual(card.manufacturer, "EHSİM")
        self.assertEqual(card.part_number, "AKK-100")
        self.assertEqual(card.technical_data.operating_temperature_min, -40.0)
        self.assertEqual(card.technical_data.length, 100.0)
        self.assertIn("SGD-001", card.requirement_ids)
        self.assertIn("SITET-001", card.test_ids)
        self.assertIn("HW-002", card.alternative_ids)
        self.assertGreaterEqual(card.confidence_score, 90)
        instances = [item for item in catalog.product_instances if item.hardware_id == "HW-001"]
        self.assertEqual(len(instances), 2)
        self.assertEqual({item.location for item in instances}, {"Sol kanal", "Sağ kanal"})
        relations = [item for item in catalog.product_tree if item["parent_instance_id"] != MISSING_VALUE]
        self.assertEqual(len(relations), 2)
        root = next(item for item in catalog.hardware_items if item.hardware_id == "HW-ROOT")
        self.assertIn("HW-001", root.child_ids)
        self.assertTrue(all(item.source_evidence for item in instances))

    def test_same_part_spelling_variations_share_one_catalog_card(self):
        raw = {
            "first": {
                "description": "Ana-Kontrol Kartı", "part_number": "AKK-100",
                "manufacturer": "EHSİM", "location": "Sol",
            },
            "second": {
                "description": "ana kontrol kartı", "part_number": "AKK-100",
                "manufacturer": "EHSİM", "location": "Sağ",
            },
        }
        catalog = detection.build_or_update_hardware_catalog(
            "Yazım", structured_hardware=raw, persist=False,
        )
        self.assertEqual(len(catalog.hardware_items), 1)
        self.assertEqual(len(catalog.product_instances), 2)
        self.assertEqual(
            {_item.location for _item in catalog.product_instances}, {"Sol", "Sağ"}
        )

    def test_datasheet_name_number_manufacturer_and_conflict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "akk.txt"
            path.write_text(
                "Parça Adı: Ana Kontrol Kartı\n"
                "Parça Numarası: AKK-100\n"
                "Üretici: EHSİM\n"
                "Model: M1\n"
                "Çalışma Sıcaklığı: -30 °C - +70 °C\n"
                "Boyutlar: 100 x 50 x 20 mm\n",
                encoding="utf-8",
            )
            catalog = detection.build_or_update_hardware_catalog(
                "Fren", traceability_report=traceability_report(),
                structured_hardware=structured_hardware(),
                datasheet_paths=[path], persist=False,
            )
        card = next(item for item in catalog.hardware_items if item.part_number == "AKK-100")
        self.assertEqual(card.manufacturer, "EHSİM")
        self.assertTrue(any(e.extraction_method.startswith("datasheet") for e in card.source_evidence))
        self.assertTrue(any(item["field"] == "operating_temperature_min" for item in catalog.conflicts))

    def test_reprocessing_unchanged_sources_reuses_catalog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = detection.build_or_update_hardware_catalog(
                "Tekrar", traceability_report=traceability_report(1),
                structured_hardware=structured_hardware(), output_root=temp_dir,
            )
            second = detection.build_or_update_hardware_catalog(
                "Tekrar", traceability_report=traceability_report(2),
                structured_hardware=structured_hardware(), output_root=temp_dir,
            )
            self.assertTrue(first.updated)
            self.assertFalse(second.updated)
            self.assertEqual(second.version, "v0001")
            latest = Path(second.storage_path)
            self.assertTrue(latest.exists())
            data = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(len(data["hardware_items"]), 3)
            self.assertTrue((latest.parent / "donanim_katalogu.v0001.json").exists())

    def test_changed_scan_retains_items_missing_from_current_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = detection.build_or_update_hardware_catalog(
                "Koruma", structured_hardware=structured_hardware(), output_root=temp_dir,
            )
            changed = structured_hardware()
            changed.pop("HW-002")
            changed["HW-001"] = dict(changed["HW-001"], rationale="Yeni tarama")
            second = detection.build_or_update_hardware_catalog(
                "Koruma", structured_hardware=changed, output_root=temp_dir,
            )
            retained = next(item for item in second.hardware_items if item.hardware_id == "HW-002")
            self.assertEqual(retained.source_presence_status, "Kaynaktan artık bulunamadı")
            self.assertTrue(any(
                item.get("type") == "source_item_missing" and item.get("hardware_id") == "HW-002"
                for item in second.unresolved_items
            ))

    def test_lm_offline_does_not_block_base_catalog(self):
        def offline(_context):
            raise ConnectionError("LM Studio kapalı")

        catalog = detection.build_or_update_hardware_catalog(
            "Çevrimdışı", traceability_report=traceability_report(),
            structured_hardware=structured_hardware(), lm_extractor=offline,
            persist=False,
        )
        self.assertEqual(len(catalog.hardware_items), 3)
        self.assertTrue(any(item["type"] == "lm_inference_unavailable" for item in catalog.unresolved_items))

    def test_invalid_model_item_without_source_is_rejected(self):
        def invalid(_context):
            return [{"part_name": "Uydurma Kart", "part_number": "FAKE-1"}]

        catalog = detection.build_or_update_hardware_catalog(
            "Doğrulama", traceability_report=traceability_report(),
            structured_hardware=structured_hardware(), lm_extractor=invalid,
            persist=False,
        )
        self.assertFalse(any(item.part_name == "Uydurma Kart" for item in catalog.hardware_items))

    def test_ambiguous_trace_target_is_not_selected_randomly(self):
        report = {
            "nodes": [
                {
                    "id": "SGD-010", "node_type": "Sistem gereksinimi",
                    "document_type": "SGD", "description": "Ana mikrodenetleyici kullanılmalıdır.",
                },
                {"id": "HW-010", "node_type": "Parça/bileşen", "title": "A Mikrodenetleyici"},
                {"id": "HW-011", "node_type": "Parça/bileşen", "title": "B Mikrodenetleyici"},
            ],
            "edges": [
                {"source_id": "SGD-010", "target_id": "HW-010", "relationship_type": "allocated_to"},
                {"source_id": "SGD-010", "target_id": "HW-011", "relationship_type": "allocated_to"},
            ],
        }
        catalog = detection.build_or_update_hardware_catalog(
            "Belirsiz", traceability_report=report, persist=False,
        )
        self.assertEqual({item.hardware_id for item in catalog.hardware_items}, {"HW-010", "HW-011"})
        self.assertTrue(any(
            item.get("type") == "ambiguous_hardware_trace"
            for item in catalog.unresolved_items
        ))

    def test_document_read_error_does_not_stop_catalog(self):
        catalog = detection.build_or_update_hardware_catalog(
            "Hatalı belge", traceability_report=traceability_report(),
            structured_hardware=structured_hardware(),
            source_paths=["/olmayan/belge.pdf"], persist=False,
        )
        self.assertEqual(len(catalog.hardware_items), 3)
        physical = next(item for item in catalog.sources if item.get("name") == "belge.pdf")
        self.assertEqual(physical["status"], "error")

    def test_pdf_datasheet_image_is_extracted_to_catalog_assets(self):
        try:
            import fitz
            from PIL import Image
        except ImportError:
            self.skipTest("PyMuPDF/Pillow yok")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "component.png"
            Image.new("RGB", (100, 100), "#0052cc").save(image_path)
            pdf_path = root / "datasheet.pdf"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "Part Name: Image Sensor\nPart Number: IMG-100\nManufacturer: EHSIM")
            page.insert_image(fitz.Rect(72, 100, 172, 200), filename=str(image_path))
            document.save(pdf_path)
            document.close()
            catalog = detection.build_or_update_hardware_catalog(
                "Görsel", datasheet_paths=[pdf_path],
                output_root=root / "catalogs",
            )
            self.assertEqual(len(catalog.hardware_items), 1)
            stored_image = Path(catalog.hardware_items[0].image_path)
            self.assertTrue(stored_image.exists())
            self.assertTrue(str(stored_image).startswith(str((root / "catalogs").resolve())))


class HardwareAutomaticIntegrationTests(unittest.TestCase):
    def test_traceability_worker_automatically_builds_catalog(self):
        import Arayüz as ui

        app = ui.TIDGeneratorApp.__new__(ui.TIDGeneratorApp)
        app._traceability_generation_token = 5
        app.update_status_text = lambda *args, **kwargs: None
        calls = []
        app.master = type("ImmediateMaster", (), {"after": lambda self, delay, callback: callback()})()
        app._finish_traceability_success = lambda *args: calls.append(args)
        catalog = HardwareCatalog(project_id="p", project_name="P")
        with (
            patch.object(ui.etki_analizi_izlenebilirlik, "build_traceability_map", return_value=traceability_report()),
            patch.object(ui.etki_analizi_entegrasyon, "apply_overrides", side_effect=lambda report: report),
            patch.object(ui.etki_analizi_entegrasyon, "update_structured_rag_index", return_value={"status": "unchanged"}),
            patch.object(ui.etki_analizi_entegrasyon, "build_health_summary", return_value={"unlinked_count": 0, "unverified_count": 0}),
            patch.object(ui.donanim_kartlari_algilama, "build_or_update_hardware_catalog", return_value=catalog) as builder,
        ):
            app._traceability_worker(
                5, "P", {}, {}, [], (), False,
            )
        builder.assert_called_once()
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][-2], catalog)
        self.assertEqual(calls[0][-1]["status"], "ready")

    def test_catalog_failure_does_not_fail_traceability(self):
        import Arayüz as ui

        app = ui.TIDGeneratorApp.__new__(ui.TIDGeneratorApp)
        app._traceability_generation_token = 6
        app.update_status_text = lambda *args, **kwargs: None
        calls = []
        app.master = type("ImmediateMaster", (), {"after": lambda self, delay, callback: callback()})()
        app._finish_traceability_success = lambda *args: calls.append(args)
        with (
            patch.object(ui.etki_analizi_izlenebilirlik, "build_traceability_map", return_value=traceability_report()),
            patch.object(ui.etki_analizi_entegrasyon, "apply_overrides", side_effect=lambda report: report),
            patch.object(ui.etki_analizi_entegrasyon, "update_structured_rag_index", return_value={"status": "unchanged"}),
            patch.object(ui.etki_analizi_entegrasyon, "build_health_summary", return_value={"unlinked_count": 0, "unverified_count": 0}),
            patch.object(ui.donanim_kartlari_algilama, "build_or_update_hardware_catalog", side_effect=RuntimeError("bozuk belge")),
        ):
            app._traceability_worker(6, "P", {}, {}, [], (), False)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][-2])
        self.assertEqual(calls[0][-1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
