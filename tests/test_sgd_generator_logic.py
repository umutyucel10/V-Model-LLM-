# -*- coding: utf-8 -*-
"""generate_sgd_batch / run_generation_logic buyuk hedef sayilarinda madde
sayisinin token tavanina takilip ~15'te kilitlenmedigini dogrular
(regresyon testi)."""

import itertools
import re
import unittest
from unittest.mock import patch

import sgd_generator_logic as generator


class _DiverseBatchModel:
    """Her cagriyi, promptta istenen adet kadar BENZERSIZ satir dondurerek
    yanitlar; gercek LLM'e ihtiyac duymaz. Cagri kwargs'larini kaydeder."""

    def __init__(self):
        self.calls = []
        self._counter = itertools.count(1)

    def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        match = re.search(r"FARKLI (\d+) adet", prompt)
        requested = int(match.group(1)) if match else 1
        lines = [
            f"Sistem test gereksinimi madde numara {next(self._counter)} beslemesi olmalidir"
            for _ in range(requested)
        ]
        return "\n".join(lines)


class GenerateSgdBatchTokenBudgetTests(unittest.TestCase):
    """generate_sgd_batch, count buyudukce max_tokens'i eski 700 tavanina
    kilitlemeden olcekliyor mu?"""

    def test_small_count_uses_scaled_token_budget(self):
        model = _DiverseBatchModel()
        with patch.object(generator, "call_gemma3_api", model):
            generator.generate_sgd_batch("kaynak metin", 8)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0]["max_tokens"], 8 * 60 + 100)

    def test_large_count_is_not_capped_at_old_700_ceiling(self):
        model = _DiverseBatchModel()
        with patch.object(generator, "call_gemma3_api", model):
            generator.generate_sgd_batch("kaynak metin", 25)
        self.assertEqual(len(model.calls), 1)
        # Eski davranis: min(25*60+100, 700) == 700 (kilitli tavan).
        # Yeni davranis: min(25*60+100, 4000) == 1600 (gercek ihtiyaca gore).
        self.assertGreater(model.calls[0]["max_tokens"], 700)
        self.assertEqual(model.calls[0]["max_tokens"], 25 * 60 + 100)

    def test_returns_requested_item_count_when_model_cooperates(self):
        model = _DiverseBatchModel()
        with patch.object(generator, "call_gemma3_api", model):
            items = generator.generate_sgd_batch("kaynak metin", 25)
        self.assertEqual(len(items), 25)
        self.assertEqual(len(set(items)), 25)  # hepsi birbirinden farkli


class RunGenerationLogicSubBatchTests(unittest.TestCase):
    """run_generation_logic, buyuk max_sgds hedeflerinde tek dev cagri yerine
    alt-batch'lere bolerek hedefe ulasiyor mu (precomputed_chunks ile dosya
    okuma/embedding atlanarak izole test)."""

    def test_reaches_large_target_via_sub_batches(self):
        model = _DiverseBatchModel()
        with patch.object(generator, "call_gemma3_api", model):
            result = generator.run_generation_logic(
                file_paths=[],
                max_sgds=25,
                precomputed_chunks=["Bu bir kaynak teknik sartname metnidir."],
                precomputed_indices=[0],
            )
        self.assertTrue(result["result"])
        self.assertEqual(len(result["sgd_list"]), 25)
        # Tek dev cagri yerine birden fazla (sub-batch) cagri yapilmis olmali.
        self.assertGreater(len(model.calls), 1)
        # Her cagrinin max_tokens'i o cagrida istenen adede gore olceklenmis
        # olmali (eski davranista bu, count>10 icin sabit 700'e kilitleniyordu).
        for call in model.calls:
            requested = int(re.search(r"FARKLI (\d+) adet", call["prompt"]).group(1))
            self.assertEqual(call["max_tokens"], min(requested * 60 + 100, 4000))

    def test_small_target_still_works_in_single_round(self):
        model = _DiverseBatchModel()
        with patch.object(generator, "call_gemma3_api", model):
            result = generator.run_generation_logic(
                file_paths=[],
                max_sgds=8,
                precomputed_chunks=["Bu bir kaynak teknik sartname metnidir."],
                precomputed_indices=[0],
            )
        self.assertTrue(result["result"])
        self.assertEqual(len(result["sgd_list"]), 8)


if __name__ == "__main__":
    unittest.main()
