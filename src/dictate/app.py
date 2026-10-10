import argparse
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import statistics
import sys
from time import perf_counter

from .config import CONFIG_PATH, Config, download_models, load_config


@dataclass
class Result:
    raw: str = ""
    text: str = ""
    timings: dict = field(default_factory=dict)
    cleanup_status: str = "disabled"


class Pipeline:
    def __init__(self, config: Config, previous=None):
        from .asr import ASR
        from .cleanup import Cleaner

        started = perf_counter()
        self.config = config
        self.asr = previous.asr if previous and previous.config.asr_model == config.asr_model else ASR(config.asr_model)
        asr_loaded = perf_counter()
        loaded = (previous.cleaner.model, previous.cleaner.tokenizer) if (
            previous and previous.cleaner and previous.config.llm_model == config.llm_model) else None
        self.cleaner = Cleaner(config.llm_model, config.personal_dictionary, config.style, loaded) if (
            config.llm_enabled and config.style != "verbatim") else None
        llm_loaded = perf_counter()
        if not previous or self.asr is not previous.asr:
            self.asr.warmup()
        if self.cleaner:
            self.cleaner.clean("This is a warmup sentence.")
        self.startup = {
            "asr_load_ms": round((asr_loaded - started) * 1000, 2),
            "llm_load_and_prefix_ms": round((llm_loaded - asr_loaded) * 1000, 2),
            "warmup_ms": round((perf_counter() - llm_loaded) * 1000, 2),
        }
        logging.info("startup %s", json.dumps(self.startup))

    def process(self, samples) -> Result:
        from .audio import SAMPLE_RATE, trim_silence

        started = perf_counter()
        trimmed = trim_silence(samples)
        vad_done = perf_counter()
        result = Result()
        result.raw = self.asr.transcribe(trimmed)
        asr_done = perf_counter()
        result.text = result.raw
        if self.cleaner and result.raw:
            try:
                cleaned = self.cleaner.clean(result.raw)
                result.text = cleaned.text
                result.cleanup_status = cleaned.status
            except Exception:
                logging.exception("Cleanup failed; retaining raw transcript")
                result.cleanup_status = "error_fallback"
        elif not result.raw:
            result.cleanup_status = "empty"
        from .snippets import expand_snippets

        result.text = expand_snippets(result.text, getattr(getattr(self, "config", None), "snippets", ()))
        done = perf_counter()
        result.timings = {
            "audio_s": round(len(samples) / SAMPLE_RATE, 3),
            "trimmed_s": round(len(trimmed) / SAMPLE_RATE, 3),
            "vad_ms": round((vad_done - started) * 1000, 2),
            "asr_ms": round((asr_done - vad_done) * 1000, 2),
            "cleanup_ms": round((done - asr_done) * 1000, 2),
            "pipeline_ms": round((done - started) * 1000, 2),
        }
        return result


def bench(config: Config, path: Path, runs: int) -> None:
    from .audio import read_wav

    started = perf_counter()
    samples = read_wav(path)
    read_ms = (perf_counter() - started) * 1000
    pipeline = Pipeline(config)
    results = []
    for run in range(1, runs + 1):
        result = pipeline.process(samples)
        results.append(result)
        print(json.dumps({
            "run": run, "wav_read_ms": round(read_ms, 2),
            **result.timings, "cleanup_status": result.cleanup_status,
            "raw": result.raw, "text": result.text,
        }, ensure_ascii=False), flush=True)
    if runs > 1:
        print(json.dumps({"median_ms": {
            key: round(statistics.median(r.timings[key] for r in results), 2)
            for key in ("vad_ms", "asr_ms", "cleanup_ms", "pipeline_ms")
        }}), flush=True)


def run_app(config: Config, config_path=CONFIG_PATH, smoke_dir=None):
    from .desktop import TypefloApp

    TypefloApp(config, config_path, smoke_dir=smoke_dir).run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Typeflo — on-device dictation for Apple Silicon")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--bench", type=Path, metavar="FILE.wav", help="benchmark a 16 kHz mono PCM WAV without pasting")
    modes.add_argument("--download-models", action="store_true", help="one-time download of configured model files")
    modes.add_argument("--download-model", metavar="MODEL", help="download one MLX model")
    parser.add_argument("--smoke-ui", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--runs", type=int, default=3, help="benchmark repetitions with resident models (default: 3)")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(args.config)
        if args.download_models or args.download_model:
            download_models(config, args.download_model)
        elif args.bench:
            bench(config, args.bench, args.runs)
        else:
            run_app(config, args.config, args.smoke_ui)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        logging.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
