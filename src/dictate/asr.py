import numpy as np

from .audio import SAMPLE_RATE
from .config import model_path


class ASR:
    def __init__(self, model_name: str):
        import mlx.core as mx
        from parakeet_mlx import from_pretrained

        self.model = from_pretrained(str(model_path(model_name)))
        if self.model.preprocessor_config.sample_rate != SAMPLE_RATE:
            raise ValueError("ASR model must accept 16 kHz audio")
        mx.eval(self.model.parameters())

    def transcribe(self, samples: np.ndarray) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        if not len(samples):
            return ""
        minimum = max(400, self.model.preprocessor_config.hop_length)
        if len(samples) < minimum:
            samples = np.pad(samples, (0, minimum - len(samples)))
        audio = mx.array(samples, dtype=mx.float32)
        mel = get_logmel(audio, self.model.preprocessor_config).astype(mx.bfloat16)
        result = self.model.generate(mel)[0]
        mx.synchronize()
        return result.text.strip()

    def warmup(self):
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
