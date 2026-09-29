import tempfile
import unittest
import wave
from pathlib import Path

import tts_service
import tts_worker


class _VoiceConfig:
    sample_rate = 1000


class _Voice:
    def __init__(self):
        self.config = _VoiceConfig()
        self.calls = []

    def phoneme_ids_to_audio(self, ids, syn_config=None, include_alignments=False):
        self.calls.append(list(ids))
        return [0.25] * 4


class _Frontend:
    def process(self, text):
        return {
            "processed_text": text,
            "chunks": [
                {"text": "câu một.", "phoneme_ids": [1, 0, 10, 0, 2]},
                {"text": "câu hai.", "phoneme_ids": [1, 0, 10, 0, 2]},
            ],
        }

    def close(self):
        pass


class InterChunkPauseTests(unittest.TestCase):
    def test_two_nghi_chunks_insert_exact_pcm_pause_and_invalidate_old_cache(self):
        self.assertEqual(tts_worker.INTER_CHUNK_SILENCE_SECONDS, 0.45)
        self.assertEqual(tts_service.CACHE_FORMAT_VERSION, 7)

        synth = tts_worker.NghiOnnxSynthesizer(
            Path("voice.onnx"), Path("voice.onnx.json"), _Frontend()
        )
        synth._voice = _Voice()
        synth._make_synthesis_config = lambda: object()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.wav"
            synth("Câu một. Câu hai.", output)
            with wave.open(str(output), "rb") as wav_file:
                frames = wav_file.readframes(wav_file.getnframes())
                self.assertEqual(wav_file.getnframes(), 4 + 450 + 4)

        first_audio_bytes = 4 * 2
        pause_bytes = 450 * 2
        pause = frames[first_audio_bytes:first_audio_bytes + pause_bytes]
        self.assertEqual(pause, b"\x00\x00" * 450)


if __name__ == "__main__":
    unittest.main()
