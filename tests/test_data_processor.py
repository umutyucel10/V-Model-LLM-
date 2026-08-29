# -*- coding: utf-8 -*-
"""data_processor.py icin karakterizasyon testleri (girdi -> cikti sozlesmesi).

LLM'e gercek ag cagrisi yapilmiyor; generate_all_requirements_batch ve
process_batch_response mock'lanarak data_processor'in kendi mantigi
(batch bolme, DataFrame olusturma, agac/duz veri yapisi) test ediliyor.
"""

import unittest
from unittest.mock import patch

import pandas as pd

import data_processor


class NormalizeTidDataframeTests(unittest.TestCase):
    def test_none_or_empty_dataframe_returns_none(self):
        self.assertIsNone(data_processor._normalize_tid_dataframe(None))
        self.assertIsNone(data_processor._normalize_tid_dataframe(pd.DataFrame()))

    def test_already_correct_columns_pass_through_unchanged(self):
        df = pd.DataFrame([{"ID": "TID-001", "Açıklama": "metin"}])
        result = data_processor._normalize_tid_dataframe(df)
        self.assertListEqual(list(result.columns), ["ID", "Açıklama"])

    def test_tid_style_columns_are_auto_renamed(self):
        df = pd.DataFrame([{"TID_ID": "TID-001", "TID_Aciklama": "metin"}])
        result = data_processor._normalize_tid_dataframe(df)
        self.assertListEqual(list(result.columns), ["ID", "Açıklama"])
        self.assertEqual(result.iloc[0]["ID"], "TID-001")

    def test_missing_id_and_description_columns_returns_none(self):
        df = pd.DataFrame([{"foo": "bar"}])
        self.assertIsNone(data_processor._normalize_tid_dataframe(df))


class UpdateGlobalCountersTests(unittest.TestCase):
    def test_first_call_with_no_prior_ids_starts_at_one(self):
        counters = data_processor._update_global_counters({}, None)
        self.assertEqual(counters["sgd_counter"], 1)
        self.assertEqual(counters["stt_counter"], 1)

    def test_counters_increment_from_last_seen_id(self):
        counters = data_processor._update_global_counters(
            {"SGD_ID": "SGD-0007", "STT_ID": "STT-0012"}, None,
        )
        self.assertEqual(counters["sgd_counter"], 8)
        self.assertEqual(counters["stt_counter"], 13)

    def test_existing_counters_are_returned_unchanged(self):
        existing = {"sgd_counter": 5, "stt_counter": 5, "setet_counter": 5,
                    "sitet_counter": 5, "kabul_muayene_counter": 5}
        self.assertIs(data_processor._update_global_counters({}, existing), existing)


class ProcessTidDataBatchTests(unittest.TestCase):
    def test_batches_are_split_according_to_batch_size(self):
        tid_df = pd.DataFrame([
            {"ID": f"TID-{i:03d}", "Açıklama": f"gereksinim {i}"} for i in range(1, 4)
        ])

        with patch.object(data_processor, "BATCH_SIZE", 2), \
             patch.object(data_processor, "generate_all_requirements_batch") as gen, \
             patch.object(data_processor, "process_batch_response") as process:
            gen.return_value = ("yanit", {"info": "ctx"})
            process.side_effect = [
                [{"TID_ID": "TID-001", "SGD_ID": "SGD-0001"},
                 {"TID_ID": "TID-002", "SGD_ID": "SGD-0002"}],
                [{"TID_ID": "TID-003", "SGD_ID": "SGD-0003"}],
            ]
            result = data_processor.process_tid_data_batch(tid_df)

        self.assertEqual(gen.call_count, 2)
        first_batch_arg = gen.call_args_list[0].args[0]
        second_batch_arg = gen.call_args_list[1].args[0]
        self.assertEqual(len(first_batch_arg), 2)
        self.assertEqual(len(second_batch_arg), 1)
        self.assertEqual(len(result), 3)
        self.assertListEqual(
            list(result["TID_ID"]), ["TID-001", "TID-002", "TID-003"],
        )

    def test_empty_llm_response_for_all_batches_returns_none(self):
        tid_df = pd.DataFrame([{"ID": "TID-001", "Açıklama": "metin"}])
        with patch.object(data_processor, "generate_all_requirements_batch") as gen:
            gen.return_value = (None, {})
            result = data_processor.process_tid_data_batch(tid_df)
        self.assertIsNone(result)

    def test_invalid_dataframe_short_circuits_without_calling_llm(self):
        with patch.object(data_processor, "generate_all_requirements_batch") as gen:
            result = data_processor.process_tid_data_batch(pd.DataFrame())
        gen.assert_not_called()
        self.assertIsNone(result)


class CreateTreeStructureTests(unittest.TestCase):
    def test_builds_nested_tid_sgd_stt_setet_hierarchy(self):
        trace_df = pd.DataFrame([
            {
                "TID_ID": "TID-001", "TID_Aciklama": "Hedefi tespit et",
                "SGD_ID": "SGD-001", "SGD_Aciklama": "5 saniyede tespit",
                "STT_ID": "STT-001", "STT_Aciklama": "Radar taramasi",
                "SETET_ID": "SETET-001", "SETET_Aciklama": "Radar testi",
            },
            {
                "TID_ID": "TID-001", "TID_Aciklama": "Hedefi tespit et",
                "SGD_ID": "SGD-001", "SGD_Aciklama": "5 saniyede tespit",
                "STT_ID": "STT-001", "STT_Aciklama": "Radar taramasi",
                "SETET_ID": "SETET-002", "SETET_Aciklama": "Ikinci test",
            },
        ])
        tree = data_processor.create_tree_structure(trace_df)

        self.assertEqual(list(tree.keys()), ["TID-001"])
        sgd = tree["TID-001"]["sgds"]["SGD-001"]
        self.assertEqual(sgd["content"], "5 saniyede tespit")
        setets = sgd["stts"]["STT-001"]["setets"]
        self.assertEqual([s["id"] for s in setets], ["SETET-001", "SETET-002"])


class CreateFlatTestDataTests(unittest.TestCase):
    def test_setet_sitet_and_kabul_entries_are_collected(self):
        trace_df = pd.DataFrame([{
            "TID_ID": "TID-001", "SGD_ID": "SGD-001", "STT_ID": "STT-001",
            "SETET_ID": "SETET-001", "SETET_Aciklama": "Radar testi",
            "SITET_ID": "SITET-001", "SITET_Aciklama": "Entegrasyon testi",
            "KABUL_MUAYENE_ID": "KABUL-001",
            "KABUL_MUAYENE_Aciklama": "Kabul kriteri saglandi",
        }])
        flat = data_processor.create_flat_test_data(trace_df)

        self.assertEqual(flat["SETET-001"]["type"], "SETET")
        self.assertEqual(flat["SITET-001"]["type"], "SITET")
        self.assertEqual(flat["KABUL-001"]["type"], "KABUL MUAYENE")
        self.assertIn("STT: STT-001", flat["SETET-001"]["bound_to"])

    def test_placeholder_kabul_content_is_skipped(self):
        trace_df = pd.DataFrame([{
            "TID_ID": "TID-001", "SGD_ID": "", "STT_ID": "",
            "SETET_ID": "", "SETET_Aciklama": "",
            "SITET_ID": "", "SITET_Aciklama": "",
            "KABUL_MUAYENE_ID": "KABUL-002",
            "KABUL_MUAYENE_Aciklama": "KABUL MUAYENE bilgisi eksik",
        }])
        flat = data_processor.create_flat_test_data(trace_df)
        self.assertNotIn("KABUL-002", flat)

    def test_empty_dataframe_returns_empty_flat_data(self):
        trace_df = pd.DataFrame([], columns=["TID_ID", "SGD_ID"])
        self.assertEqual(data_processor.create_flat_test_data(trace_df), {})


if __name__ == "__main__":
    unittest.main()
