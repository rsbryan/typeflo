from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics

from .config import DATA_PATH


class History:
    def __init__(self, path: Path = DATA_PATH / "history.sqlite3"):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL,
            raw TEXT NOT NULL, text TEXT NOT NULL, words INTEGER NOT NULL,
            application TEXT NOT NULL, asr_model TEXT NOT NULL, llm_model TEXT NOT NULL,
            status TEXT NOT NULL, timings TEXT NOT NULL)""")
        self.db.commit()

    def add(self, result, config, application="", kind="dictation") -> int:
        words = len(re.findall(r"\b\w+\b", result.text))
        keep = config.history_enabled or kind == "benchmark"
        cursor = self.db.execute("INSERT INTO sessions VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            datetime.now().isoformat(timespec="seconds"), kind, result.raw if keep else "",
            result.text if keep else "", words, application, config.asr_model,
            config.llm_model if config.llm_enabled else "", result.cleanup_status, json.dumps(result.timings)))
        self.db.execute("DELETE FROM sessions WHERE id NOT IN (SELECT id FROM sessions ORDER BY id DESC LIMIT 5000)")
        self.db.commit()
        return cursor.lastrowid

    def list(self, limit=250):
        rows = [dict(row) for row in self.db.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,))]
        for row in rows:
            row["timings"] = json.loads(row["timings"])
        return rows

    def delete(self, identifier: int):
        self.db.execute("DELETE FROM sessions WHERE id = ?", (identifier,))
        self.db.commit()

    def clear(self):
        self.db.execute("DELETE FROM sessions")
        self.db.commit()

    def stats(self):
        rows = self.list(5000)
        dictations = [r for r in rows if r["kind"] == "dictation"]
        measured = [r for r in rows if r["timings"].get("pipeline_ms") is not None]
        latencies = sorted(r["timings"]["pipeline_ms"] for r in measured)
        stages = {key: round(statistics.median(r["timings"].get(key, 0) for r in measured), 2) if measured else 0
                  for key in ("vad_ms", "asr_ms", "cleanup_ms", "pipeline_ms")}
        duration = sum(r["timings"].get("audio_s", 0) for r in dictations)
        words = sum(r["words"] for r in dictations)
        days = []
        for offset in range(6, -1, -1):
            date = (datetime.now() - timedelta(days=offset)).date().isoformat()
            days.append({"date": date, "words": sum(r["words"] for r in dictations if r["created"].startswith(date))})
        return {"words": words, "sessions": len(dictations), "audio_s": round(duration, 1),
                "wpm": round(words / duration * 60) if duration else 0,
                "saved_minutes": round(max(0, words / 40 - duration / 60), 1),
                "p50_ms": round(statistics.median(latencies), 1) if latencies else 0,
                "p95_ms": round(latencies[max(0, math.ceil(len(latencies) * .95) - 1)], 1) if latencies else 0,
                "stages": stages, "days": days, "benchmarks": sum(r["kind"] == "benchmark" for r in rows)}

    def close(self):
        self.db.close()
