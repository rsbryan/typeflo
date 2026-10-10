import importlib.util
from pathlib import Path
import tempfile
import unittest
import wave

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if HAS_NUMPY:
    import numpy as np
    from dictate.audio import SAMPLE_RATE, read_wav, trim_silence


@unittest.skipUnless(HAS_NUMPY, "numpy is not installed")
class AudioTests(unittest.TestCase):
    def test_empty_and_silent_recordings(self):
        self.assertEqual(len(trim_silence(np.array([]))), 0)
        self.assertEqual(len(trim_silence(np.zeros(SAMPLE_RATE))), 0)

    def test_edges_trimmed_and_internal_pause_preserved(self):
        samples = np.concatenate([np.zeros(16000), np.ones(3200) * 0.1, np.zeros(8000),
                                  np.ones(3200) * 0.1, np.zeros(16000)]).astype(np.float32)
        trimmed = trim_silence(samples)
        np.testing.assert_array_equal(trimmed, samples[14080:32320])

    def test_partial_frame_retained(self):
        samples = np.ones(401, dtype=np.float32) * 0.1
        np.testing.assert_array_equal(trim_silence(samples), samples)

    def test_wav_validation_and_scaling(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            with wave.open(str(path), "wb") as file:
                file.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                file.writeframes(np.array([-32768, 0, 16384], dtype="<i2").tobytes())
            np.testing.assert_array_equal(read_wav(path), [-1, 0, 0.5])
            with wave.open(str(path), "wb") as file:
                file.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
            with self.assertRaisesRegex(ValueError, "no audio"):
                read_wav(path)
