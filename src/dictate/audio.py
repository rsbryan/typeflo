from pathlib import Path
from threading import Lock
import wave

import numpy as np

SAMPLE_RATE = 16_000
MAX_SECONDS = 120


def trim_silence(samples: np.ndarray, threshold: float = 0.008) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not len(samples):
        return samples
    frame = 320
    padded = np.pad(samples, (0, (-len(samples)) % frame))
    rms = np.sqrt(np.mean(padded.reshape(-1, frame) ** 2, axis=1))
    active = np.flatnonzero(rms >= threshold)
    if not len(active):
        return samples[:0]
    padding = int(0.12 * SAMPLE_RATE)
    start = max(0, int(active[0]) * frame - padding)
    end = min(len(samples), (int(active[-1]) + 1) * frame + padding)
    return samples[start:end]


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as file:
        if (file.getframerate(), file.getnchannels(), file.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ValueError("Benchmark WAV must be 16 kHz, mono, signed 16-bit PCM")
        if file.getnframes() > MAX_SECONDS * SAMPLE_RATE:
            raise ValueError(f"Benchmark WAV must be at most {MAX_SECONDS} seconds")
        if not file.getnframes():
            raise ValueError("Benchmark WAV contains no audio frames")
        return np.frombuffer(file.readframes(file.getnframes()), dtype="<i2").astype(np.float32) / 32768


class Recorder:
    def __init__(self, device=None):
        import sounddevice as sd

        self._lock = Lock()
        self._chunks = []
        self._samples = 0
        self._overflow = False
        self.level = 0.0
        self._stream = sd.InputStream(
            device=device,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=320,
            latency="low",
            callback=self._callback,
        )

    def _callback(self, data, frames, time_info, status):
        with self._lock:
            self.level = min(1.0, float(np.sqrt(np.mean(data ** 2))) * 8)
            self._overflow |= bool(status.input_overflow)
            remaining = MAX_SECONDS * SAMPLE_RATE - self._samples
            if remaining > 0:
                chunk = data[:remaining, 0].copy()
                self._chunks.append(chunk)
                self._samples += len(chunk)

    def start(self):
        with self._lock:
            self._chunks = []
            self._samples = 0
            self._overflow = False
        self._stream.start()

    def stop(self) -> np.ndarray:
        self._stream.abort()
        self.level = 0.0
        with self._lock:
            chunks, self._chunks = self._chunks, []
            if self._overflow:
                raise RuntimeError("Microphone input overflowed; please dictate again")
        return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)

    def close(self):
        self._stream.abort()
        self._stream.close()
