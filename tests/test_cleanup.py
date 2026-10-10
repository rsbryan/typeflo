from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dictate.cleanup import Cleaner, word_count


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.cleaner = Cleaner.__new__(Cleaner)
        self.cleaner.model = object()
        self.cleaner.system = "Edit only"
        self.cleaner.prefix = [10, 20]
        self.cleaner.cache = [{"tokens": [10, 20]}]
        self.cleaner.tokenizer = SimpleNamespace(
            encode=Mock(return_value=[1, 2, 3, 4, 5]),
            apply_chat_template=Mock(return_value=[10, 20, 30, 40]),
        )

    def run_clean(self, finish="stop", text="Meet at three tomorrow."):
        def generate(*args, **kwargs):
            kwargs["prompt_cache"][0]["tokens"].append(99)
            yield SimpleNamespace(text=text, generation_tokens=5, finish_reason=finish)

        generator = Mock(side_effect=generate)
        core = SimpleNamespace(synchronize=Mock())
        modules = {
            "mlx": SimpleNamespace(core=core), "mlx.core": core,
            "mlx_lm": SimpleNamespace(stream_generate=generator),
            "mlx_lm.sample_utils": SimpleNamespace(make_sampler=Mock(return_value="greedy")),
        }
        with patch.dict("sys.modules", modules):
            result = self.cleaner.clean("Meet at two actually three tomorrow")
        return result, generator

    def test_cache_isolation_and_bounded_suffix(self):
        for _ in range(2):
            result, generator = self.run_clean()
            self.assertEqual(result.text, "Meet at three tomorrow.")
            self.assertEqual(generator.call_args.kwargs["prompt"], [30, 40])
            self.assertEqual(generator.call_args.kwargs["max_tokens"], 8)
            self.assertEqual(self.cleaner.cache, [{"tokens": [10, 20]}])

    def test_capped_output_is_not_inserted(self):
        with self.assertLogs(level="WARNING"):
            result, _ = self.run_clean(finish="length")
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.text, "Meet at two actually three tomorrow")

    def test_empty_output_is_not_inserted(self):
        with self.assertLogs(level="WARNING"):
            result, _ = self.run_clean(text="")
        self.assertEqual(result.status, "fallback")

    def test_short_text_bypasses_model(self):
        for text in ("", "Hello!", "Thanks, Sarah.", "Don't do that."):
            self.assertEqual(self.cleaner.clean(text).text, text)
        self.cleaner.tokenizer.encode.assert_not_called()

    def test_word_count(self):
        self.assertEqual(word_count("Don't omit Jean-Luc."), 3)
        self.assertEqual(word_count("one,two,three,four"), 4)

    def test_mismatched_template_is_rejected(self):
        self.cleaner.tokenizer.apply_chat_template.return_value = [88, 30, 40]
        with self.assertRaisesRegex(ValueError, "system prefix"):
            self.run_clean()
