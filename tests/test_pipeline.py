from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dictate.app import Pipeline
from dictate.cleanup import CleanupResult


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = Pipeline.__new__(Pipeline)
        self.pipeline.asr = SimpleNamespace(transcribe=Mock(return_value="Um please call Sarah tomorrow"))
        self.pipeline.cleaner = SimpleNamespace(clean=Mock(return_value=CleanupResult("Please call Sarah tomorrow.", "cleaned")))
        self.audio = SimpleNamespace(SAMPLE_RATE=16000, trim_silence=lambda data: data[160:])

    def test_pipeline_times_and_output(self):
        with patch.dict("sys.modules", {"dictate.audio": self.audio}):
            result = self.pipeline.process([0] * 16000)
        self.assertEqual(result.text, "Please call Sarah tomorrow.")
        self.assertEqual(result.timings["audio_s"], 1)
        self.assertEqual(result.timings["trimmed_s"], 0.99)
        for stage in ("vad_ms", "asr_ms", "cleanup_ms", "pipeline_ms"):
            self.assertGreaterEqual(result.timings[stage], 0)

    def test_model_error_preserves_raw_transcript(self):
        self.pipeline.cleaner.clean.side_effect = RuntimeError("model failed")
        with patch.dict("sys.modules", {"dictate.audio": self.audio}), self.assertLogs(level="ERROR"):
            result = self.pipeline.process([0] * 16000)
        self.assertEqual(result.text, result.raw)
        self.assertEqual(result.cleanup_status, "error_fallback")

    def test_disabled_cleanup(self):
        self.pipeline.cleaner = None
        with patch.dict("sys.modules", {"dictate.audio": self.audio}):
            result = self.pipeline.process([0] * 16000)
        self.assertEqual(result.text, result.raw)
        self.assertEqual(result.cleanup_status, "disabled")

    def test_empty_transcript_does_not_invoke_cleanup(self):
        self.pipeline.asr.transcribe.return_value = ""
        with patch.dict("sys.modules", {"dictate.audio": self.audio}):
            result = self.pipeline.process([0] * 16000)
        self.pipeline.cleaner.clean.assert_not_called()
        self.assertEqual(result.text, "")
        self.assertEqual(result.cleanup_status, "empty")
