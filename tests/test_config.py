from pathlib import Path
import tempfile
import unittest

from dictate.config import Config, load_config


class ConfigTests(unittest.TestCase):
    def test_first_run_and_existing_dictionary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dictate/config.toml"
            self.assertEqual(load_config(path), Config())
            text = 'hotkey = "f18"\nllm_enabled = false\npersonal_dictionary = ["Zoë", "Typeflo"]\n'
            path.write_text(text)
            config = load_config(path)
            self.assertEqual(config.hotkey, "f18")
            self.assertFalse(config.llm_enabled)
            self.assertEqual(config.personal_dictionary, ("Zoë", "Typeflo"))
            self.assertEqual(path.read_text(), text)

    def test_invalid_configuration(self):
        cases = [
            'hotkey = "unknown"', 'hotkey = 3', 'llm_enabled = "false"',
            'personal_dictionary = "name"', 'personal_dictionary = [42]',
            'personal_dictionary = [""]', 'asr_model = ""', 'typo = true',
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for text in cases:
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(ValueError):
                        load_config(path)
