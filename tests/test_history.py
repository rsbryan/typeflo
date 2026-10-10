from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from dictate.app import Result
from dictate.config import Config
from dictate.history import History


def result(text, pipeline_ms, audio_s=3.0):
    return Result(raw=text.lower(), text=text, cleanup_status="cleaned",
                  timings={"pipeline_ms": pipeline_ms, "asr_ms": pipeline_ms / 4,
                           "cleanup_ms": pipeline_ms / 2, "vad_ms": 1, "audio_s": audio_s})


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.history = History(Path(self.directory.name) / "history.sqlite3")
        self.addCleanup(self.history.close)

    def test_rows_and_stats(self):
        config = Config()
        self.history.add(result("Please call Sarah tomorrow morning.", 300), config, "Mail")
        self.history.add(result("Meet at three.", 100), config, "Notes")
        self.history.add(result("Benchmark text here.", 500), config, "Benchmark", "benchmark")
        rows = self.history.list()
        self.assertEqual([row["application"] for row in rows], ["Benchmark", "Notes", "Mail"])
        self.assertEqual(rows[2]["words"], 5)
        self.assertEqual(rows[2]["timings"]["pipeline_ms"], 300)
        stats = self.history.stats()
        self.assertEqual(stats["sessions"], 2)
        self.assertEqual(stats["words"], 8)
        self.assertEqual(stats["benchmarks"], 1)
        self.assertEqual(stats["p50_ms"], 300)
        self.assertEqual(stats["p95_ms"], 500)
        self.assertEqual(stats["wpm"], 80)
        self.assertEqual(len(stats["days"]), 7)
        self.assertEqual(stats["days"][-1]["words"], 8)

    def test_disabled_history_keeps_metrics_only(self):
        config = replace(Config(), history_enabled=False)
        self.history.add(result("Private words here.", 200), config, "Mail")
        row = self.history.list()[0]
        self.assertEqual((row["text"], row["raw"]), ("", ""))
        self.assertEqual(row["words"], 3)
        self.assertEqual(self.history.stats()["words"], 3)

    def test_delete_and_clear(self):
        config = Config()
        first = self.history.add(result("One two three four.", 100), config)
        self.history.add(result("Five six.", 100), config)
        self.history.delete(first)
        self.assertEqual(len(self.history.list()), 1)
        self.history.clear()
        self.assertEqual(self.history.list(), [])
        self.assertEqual(self.history.stats()["p50_ms"], 0)
