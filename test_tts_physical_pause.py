import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import tts_service
import tts_worker


class PhysicalSentencePauseTests(unittest.TestCase):
    def test_native_piper_splits_sentences_and_inserts_physical_silence(self):
        calls = {"writes": []}

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "announcement.wav"

            class FakeStdin:
                def write(self, value):
                    calls["writes"].append(value)
                    return len(value)

                def flush(self):
                    pass

            class FakeStdout:
                def readline(self):
                    request = json.loads(calls["writes"][-1])
                    segment = Path(request["output_file"])
                    segment.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(segment), "wb") as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(1000)
                        wav_file.writeframes(b"\x01\x00" * 10)
                    return str(segment) + "\n"

            class FakeProcess:
                def __init__(self):
                    self.stdin = FakeStdin()
                    self.stdout = FakeStdout()

                def poll(self):
                    return None

                def terminate(self):
                    pass

                def wait(self, timeout=None):
                    return 0

            def process_factory(command, **kwargs):
                calls["command"] = command
                return FakeProcess()

            synthesizer = tts_worker.NativePiperSynthesizer(
                Path("piper.exe"),
                Path("voice.onnx"),
                Path("voice.onnx.json"),
                process_factory=process_factory,
            )
            synthesizer(
                "HUỲNH QUỐC PHƯỚC đã điểm danh thành công. Mời sinh viên tiếp theo.",
                output,
            )

            requests = [json.loads(value) for value in calls["writes"]]
            self.assertEqual(
                [request["text"] for request in requests],
                [
                    "huỳnh quốc phước đã điểm danh thành công.",
                    "mời sinh viên tiếp theo.",
                ],
            )

            with wave.open(str(output), "rb") as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 1000)
                self.assertEqual(wav_file.getnframes(), 470)
                frames = wav_file.readframes(470)

            first_sentence_bytes = 10 * 2
            silence_bytes = 450 * 2
            self.assertEqual(
                frames[first_sentence_bytes:first_sentence_bytes + silence_bytes],
                b"\x00" * silence_bytes,
            )
            self.assertNotEqual(frames[:first_sentence_bytes], b"\x00" * first_sentence_bytes)
            self.assertNotEqual(frames[-first_sentence_bytes:], b"\x00" * first_sentence_bytes)

    def test_cache_key_includes_physical_pause_render_revision(self):
        self.assertEqual(tts_service.RENDER_REVISION, "physical-sentence-pause-v1")
        original = tts_service.cache_key("Câu một. Câu hai.")
        with mock.patch.object(tts_service, "RENDER_REVISION", "future-render"):
            changed = tts_service.cache_key("Câu một. Câu hai.")
        self.assertNotEqual(original, changed)


if __name__ == "__main__":
    unittest.main()
