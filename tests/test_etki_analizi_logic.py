# -*- coding: utf-8 -*-

import unittest

import etki_analizi_logic as logic


def _analysis(parameters, alternatives=None):
    return {
        "analysis_name": "İşlemci kartı değişikliği",
        "current_state": "Mevcut Kart A",
        "change_reason": "Tedarik riski",
        "alternatives": alternatives or ["Kart B"],
        "parameters": parameters,
    }


class EtkiAnaliziLogicTests(unittest.TestCase):
    def test_weights_are_normalized_to_one_hundred_percent(self):
        weights = logic.normalize_weights([
            {"name": "Maliyet", "weight": 2},
            {"name": "Performans", "weight": 3},
        ])

        self.assertAlmostEqual(sum(weights), 100.0)
        self.assertAlmostEqual(weights[0], 40.0)
        self.assertAlmostEqual(weights[1], 60.0)

    def test_high_and_low_directions_produce_expected_scores(self):
        self.assertEqual(
            logic.score_value(75, 0, 100, "Yüksek daha iyi"),
            75.0,
        )
        self.assertEqual(
            logic.score_value(25, 0, 100, "Düşük daha iyi"),
            75.0,
        )

    def test_total_score_uses_normalized_weights(self):
        result = logic.calculate_impact_analysis(_analysis([
            {
                "name": "Maliyet",
                "current_value": 100,
                "alternative_values": {"Kart B": 80},
                "unit": "TL",
                "weight": 2,
                "direction": "Düşük daha iyi",
                "minimum": 50,
                "maximum": 150,
                "mandatory": False,
            },
            {
                "name": "Performans",
                "current_value": 50,
                "alternative_values": {"Kart B": 80},
                "unit": "puan",
                "weight": 3,
                "direction": "Yüksek daha iyi",
                "minimum": 0,
                "maximum": 100,
                "mandatory": True,
            },
        ]))

        alternative = result["alternatives"][0]
        self.assertEqual(alternative["status"], "Uygun")
        self.assertEqual(alternative["total_score"], 76.0)
        self.assertEqual(
            result["best_alternative"]["alternative_name"],
            "Kart B",
        )

    def test_mandatory_criterion_outside_limits_is_unsuitable(self):
        result = logic.calculate_impact_analysis(_analysis([
            {
                "name": "Sıcaklık",
                "current_value": 65,
                "alternative_values": {"Kart B": 85},
                "unit": "°C",
                "weight": 100,
                "direction": "Düşük daha iyi",
                "minimum": -40,
                "maximum": 70,
                "mandatory": True,
            }
        ]))

        alternative = result["alternatives"][0]
        self.assertEqual(alternative["status"], "Uygun değil")
        self.assertTrue(alternative["mandatory_failed"])
        self.assertEqual(
            alternative["criteria"][0]["status"],
            "Zorunlu kriter sağlanmadı",
        )
        self.assertIsNone(result["best_alternative"])

    def test_missing_value_is_not_treated_as_zero(self):
        result = logic.calculate_impact_analysis(_analysis([
            {
                "name": "Kütle",
                "current_value": 10,
                "alternative_values": {"Kart B": ""},
                "unit": "kg",
                "weight": 100,
                "direction": "Düşük daha iyi",
                "minimum": 5,
                "maximum": 15,
                "mandatory": False,
            }
        ]))

        alternative = result["alternatives"][0]
        self.assertEqual(alternative["status"], "Veri eksik")
        self.assertIsNone(alternative["total_score"])
        self.assertIsNone(alternative["criteria"][0]["criterion_score"])

    def test_difference_and_percentage_are_calculated(self):
        difference = logic.calculate_difference(80, 100)

        self.assertEqual(difference["difference"], 20.0)
        self.assertEqual(difference["difference_percent"], 25.0)

    def test_percentage_difference_is_undefined_when_current_is_zero(self):
        difference = logic.calculate_difference(0, 12)

        self.assertEqual(difference["difference"], 12.0)
        self.assertIsNone(difference["difference_percent"])

    def test_best_alternative_ignores_unsuitable_and_missing_results(self):
        result = logic.calculate_impact_analysis(_analysis(
            alternatives=["A", "B", "C"],
            parameters=[
                {
                    "name": "Kapasite",
                    "current_value": 20,
                    "alternative_values": {"A": 70, "B": 110, "C": ""},
                    "unit": "GB",
                    "weight": 100,
                    "direction": "Yüksek daha iyi",
                    "minimum": 0,
                    "maximum": 100,
                    "mandatory": True,
                }
            ],
        ))

        statuses = {
            item["alternative_name"]: item["status"]
            for item in result["alternatives"]
        }
        self.assertEqual(statuses, {
            "A": "Uygun",
            "B": "Uygun değil",
            "C": "Veri eksik",
        })
        self.assertEqual(result["best_alternative"], {
            "alternative_name": "A",
            "total_score": 70.0,
        })

    def test_decimal_comma_is_supported(self):
        self.assertEqual(
            logic.score_value("7,5", "0", "10", "yüksek"),
            75.0,
        )

    def test_zero_weight_total_has_clear_turkish_error(self):
        with self.assertRaisesRegex(
            logic.EtkiAnaliziHatasi,
            "toplamı sıfırdan büyük",
        ):
            logic.normalize_weights([
                {"name": "Maliyet", "weight": 0},
                {"name": "Kütle", "weight": 0},
            ])

    def test_invalid_numeric_value_has_clear_turkish_error(self):
        with self.assertRaisesRegex(
            logic.EtkiAnaliziHatasi,
            "geçerli bir sayısal değer",
        ):
            logic.calculate_impact_analysis(_analysis([
                {
                    "name": "Kütle",
                    "current_value": "on",
                    "alternative_values": {"Kart B": 8},
                    "unit": "kg",
                    "weight": 100,
                    "direction": "Düşük daha iyi",
                    "minimum": 5,
                    "maximum": 15,
                    "mandatory": False,
                }
            ]))


if __name__ == "__main__":
    unittest.main()

