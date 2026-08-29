# -*- coding: utf-8 -*-
"""Arayuz.py'deki threading.Thread + master.after arka plan deseninin
kritik akislari icin karakterizasyon testleri (Faz 5).

Yaklasim (playbook Faz 5'in istedigi "UI'dan ayirma ya da mock master"
onerisi): gercek bir Tk penceresi ACMIYORUZ. Bunun yerine, bu dosyadaki
mevcut test_mimari_cerceve_ui.py::MainScreenArchitectureIntegrationTests
ile ayni, depoda zaten yerlesik olan desen kullaniliyor:
`object.__new__(TIDGeneratorApp)` ile widget agaci kurulmadan cipiaz bir
ornek olusturulur, yalnizca test edilen metodun dokundugu birkac oznitelik
(flat_data, master, update_status_text vb.) elle/mock olarak set edilir ve
worker metodu (_chat_worker, _finish_hardware_catalog_refresh/_failure)
threading.Thread uzerinden degil DOGRUDAN, senkron cagrilir - boylece
testler deterministik olur ve gercek ag/LLM cagrisi yapilmaz.

Bu, "iyi" bir test mimarisi degil (UI mantigi hala ic ice), ama mevcut
davranisi kilitleyen ucuz bir guvenlik agi. Mantigi UI'dan tam ayirmak
Faz 7'nin (mimari yeniden yapilandirma) konusu.
"""

import unittest
from unittest.mock import Mock, patch

import Arayüz
import llm_handler


class ChatWorkerHappyPathTests(unittest.TestCase):
    def _make_app(self):
        app = object.__new__(Arayüz.TIDGeneratorApp)
        app.flat_data = {"SETET-001": {"content": "eski metin", "type": "SETET"}}
        app.last_generated_output = ""
        app.master = Mock()
        app._chat_append = Mock()
        app.update_status_text = Mock()
        return app

    def test_known_target_id_triggers_llm_call_and_updates_flat_data(self):
        app = self._make_app()
        with patch.object(llm_handler, "call_gemma3_api",
                           return_value="Radar taraması iki saniye içinde tamamlanmalıdır.") as call:
            app._chat_worker("SETET-001 metnini iki saniyeye güncelle")

        call.assert_called_once()
        self.assertIn("MADDE ID: SETET-001", call.call_args.args[0])
        self.assertEqual(
            app.flat_data["SETET-001"]["content"],
            "Radar taraması iki saniye içinde tamamlanmalıdır.",
        )
        # finally bloğu chat_send_btn'i master.after uzerinden tekrar aciyor
        app.master.after.assert_called()

    def test_empty_llm_response_reports_error_and_leaves_content_unchanged(self):
        app = self._make_app()
        with patch.object(llm_handler, "call_gemma3_api", return_value=""):
            app._chat_worker("SETET-001 metnini güncelle")

        self.assertEqual(app.flat_data["SETET-001"]["content"], "eski metin")
        error_calls = [
            c for c in app._chat_append.call_args_list
            if "model cevap vermedi" in c.args[0]
        ]
        self.assertEqual(len(error_calls), 1)


class ChatWorkerTargetNotFoundTests(unittest.TestCase):
    def test_unknown_target_id_never_calls_llm(self):
        app = object.__new__(Arayüz.TIDGeneratorApp)
        app.flat_data = {"SETET-001": {"content": "metin", "type": "SETET"}}
        app.last_generated_output = ""
        app.master = Mock()
        app._chat_append = Mock()
        app.update_status_text = Mock()

        with patch.object(llm_handler, "call_gemma3_api") as call:
            app._chat_worker("bilmediğim bir maddeyi güncelle")

        call.assert_not_called()
        error_calls = [
            c for c in app._chat_append.call_args_list
            if "bulamadım" in c.args[0]
        ]
        self.assertEqual(len(error_calls), 1)


class HardwareCatalogGenerationTokenGuardTests(unittest.TestCase):
    """Faz 2 raporunda ve playbook Faz 8/11'de bahsedilen 'is token'i'
    deseni: kullanici yeni bir islem baslattiginda (token artinca), eski
    devam eden bir arka plan isinin geciken sonucu artik UI durumuna
    yazilmamali. Bu testler _finish_hardware_catalog_refresh/_failure'in
    bu garantiyi zaten sagladigini kilitliyor."""

    def _make_app(self, token):
        app = object.__new__(Arayüz.TIDGeneratorApp)
        app._hardware_catalog_generation_token = token
        app.update_status_text = Mock()
        return app

    def test_result_matching_current_token_is_applied(self):
        app = self._make_app(token=5)
        catalog = Mock()
        catalog.to_dict.return_value = {"cards": ["A"]}

        app._finish_hardware_catalog_refresh(
            token=5, catalog=catalog, status={"message": "v1 tamam"}, change_summary={},
        )

        self.assertEqual(app.last_hardware_catalog, {"cards": ["A"]})
        app.update_status_text.assert_called_once_with("v1 tamam", is_complete=True)

    def test_stale_result_from_superseded_generation_is_ignored(self):
        app = self._make_app(token=5)
        first_catalog = Mock()
        first_catalog.to_dict.return_value = {"cards": ["A"]}
        app._finish_hardware_catalog_refresh(
            token=5, catalog=first_catalog, status={"message": "v1 tamam"}, change_summary={},
        )

        # kullanici yeni bir tarama/uretim baslatti -> token artti
        app._hardware_catalog_generation_token = 6

        stale_catalog = Mock()
        stale_catalog.to_dict.return_value = {"cards": ["STALE"]}
        app._finish_hardware_catalog_refresh(
            token=5, catalog=stale_catalog, status={"message": "stale"}, change_summary={},
        )

        # eski (token=5) sonuc uygulanmamis olmali
        self.assertEqual(app.last_hardware_catalog, {"cards": ["A"]})
        app.update_status_text.assert_called_once_with("v1 tamam", is_complete=True)

    def test_stale_failure_does_not_show_warning_dialog(self):
        app = self._make_app(token=5)
        app._hardware_catalog_generation_token = 6

        with patch.object(Arayüz.messagebox, "showwarning") as warn:
            app._finish_hardware_catalog_failure(token=5, detail="zaman aşımı")

        warn.assert_not_called()

    def test_current_failure_shows_warning_dialog_once(self):
        app = self._make_app(token=7)

        with patch.object(Arayüz.messagebox, "showwarning") as warn:
            app._finish_hardware_catalog_failure(token=7, detail="zaman aşımı")

        warn.assert_called_once()
        self.assertIn("zaman aşımı", warn.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
