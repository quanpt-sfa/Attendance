import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

import tts_worker


ROOT = Path(__file__).resolve().parent


class TTSWorkerProtocolTests(unittest.TestCase):
    def test_valid_synthesis_request_preserves_id_and_calls_synthesizer(self):
        calls = []

        def synthesize(text, output):
            calls.append((text, Path(output)))

        request = {
            "id": "req-1",
            "action": "synthesize",
            "text": "Nguyễn Văn An",
            "output": "out.wav",
        }
        response = tts_worker.handle_request(request, synthesize)
        self.assertEqual(response, {"id": "req-1", "ok": True})
        self.assertEqual(calls, [("Nguyễn Văn An", Path("out.wav"))])

    def test_invalid_action_returns_protocol_error_without_synthesis(self):
        calls = []
        response = tts_worker.handle_request(
            {"id": "req-2", "action": "delete", "text": "A", "output": "x.wav"},
            lambda *args: calls.append(args),
        )
        self.assertEqual(response["id"], "req-2")
        self.assertFalse(response["ok"])
        self.assertEqual(calls, [])

    def test_serve_writes_only_json_protocol_to_stdout(self):
        request = json.dumps({"id": "req-4", "action": "synthesize", "text": "A", "output": "x.wav"})
        stdin = io.StringIO(request + "\nnot-json\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        tts_worker.serve_streams(stdin, stdout, stderr, lambda _text, _output: None)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0], {"id": "req-4", "ok": True})
        self.assertFalse(lines[1]["ok"])
        self.assertIn("not-json", stderr.getvalue())

    def test_smoke_sample_preserves_source_case_for_nghi(self):
        sample = tts_worker.DEFAULT_SMOKE_TEXT
        self.assertIn("THÚY QUỲNH", sample)
        self.assertIn("HUỲNH QUỐC PHƯỚC", sample)


class _FakeStdin:
    def __init__(self, writes):
        self.writes = writes
        self.closed = False

    def write(self, value):
        self.writes.append(value)
        return len(value)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeStdout:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else ""


class _FakeProcess:
    def __init__(self, lines, writes):
        self.stdin = _FakeStdin(writes)
        self.stdout = _FakeStdout(lines)
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def kill(self):
        self._returncode = -9

    def wait(self, timeout=None):
        self._returncode = 0
        return 0


class NghiFrontendClientTests(unittest.TestCase):
    def _client(self, responses_per_process, calls):
        responses = list(responses_per_process)

        def process_factory(command, **kwargs):
            calls.setdefault("commands", []).append(command)
            calls.setdefault("kwargs", []).append(kwargs)
            writes = []
            calls.setdefault("writes", []).append(writes)
            return _FakeProcess(responses.pop(0), writes)

        return tts_worker.NghiFrontendClient(
            Path(r"C:\Program Files\Attendance TTS\node.exe"),
            Path(r"D:\Works With Spaces\attendance\tts\nghi_frontend.mjs"),
            Path(r"D:\Works With Spaces\attendance\tts\runtime\nghitts"),
            Path(r"D:\Works With Spaces\attendance\tts\voices\calmwoman3688.onnx.json"),
            "46d160da32041f7e176607203b958069265df7da",
            process_factory=process_factory,
        )

    def test_frontend_client_passes_source_case_and_validates_matching_id(self):
        calls = {}
        response = {
            "id": "fixed-id", "ok": True, "processed_text": "x",
            "chunks": [{"text": "X.", "phoneme_ids": [1, 0, 137, 0, 2]}],
        }
        client = self._client([[json.dumps(response) + "\n"]], calls)
        client._new_request_id = lambda: "fixed-id"
        result = client.process("HUỲNH Quốc Phước.")
        sent = json.loads(calls["writes"][0][0])
        self.assertEqual(sent["text"], "HUỲNH Quốc Phước.")
        self.assertEqual(result["chunks"][0]["phoneme_ids"], [1, 0, 137, 0, 2])

    def test_frontend_client_rejects_empty_chunks_nested_ids_float_ids_and_eof(self):
        bad_payloads = [
            {"id": "fixed-id", "ok": True, "processed_text": "x", "chunks": []},
            {"id": "fixed-id", "ok": True, "processed_text": "x", "chunks": [{"text": "x", "phoneme_ids": [[1]]}]},
            {"id": "fixed-id", "ok": True, "processed_text": "x", "chunks": [{"text": "x", "phoneme_ids": [1.5]}]},
        ]
        for payload in bad_payloads:
            calls = {}
            client = self._client([[json.dumps(payload) + "\n"], [json.dumps(payload) + "\n"]], calls)
            client._new_request_id = lambda: "fixed-id"
            with self.assertRaises((RuntimeError, ValueError)):
                client.process("Xin chào")
        calls = {}
        client = self._client([[], []], calls)
        client._new_request_id = lambda: "fixed-id"
        with self.assertRaisesRegex(RuntimeError, "exited|eof|response"):
            client.process("Xin chào")

    def test_frontend_client_restarts_once_after_sidecar_failure(self):
        calls = {}
        good = {"id": "fixed-id", "ok": True, "processed_text": "x", "chunks": [{"text": "x", "phoneme_ids": [1, 0, 2]}]}
        client = self._client([[], [json.dumps(good) + "\n"]], calls)
        client._new_request_id = lambda: "fixed-id"
        result = client.process("Xin chào")
        self.assertEqual(len(calls["commands"]), 2)
        self.assertEqual(result["chunks"][0]["phoneme_ids"], [1, 0, 2])

    def test_sidecar_command_handles_windows_paths_as_argument_list(self):
        calls = {}
        good = {"id": "fixed-id", "ok": True, "processed_text": "x", "chunks": [{"text": "x", "phoneme_ids": [1, 0, 2]}]}
        client = self._client([[json.dumps(good) + "\n"]], calls)
        client._new_request_id = lambda: "fixed-id"
        client.process("Xin chào")
        command = calls["commands"][0]
        self.assertEqual(command[0], r"C:\Program Files\Attendance TTS\node.exe")
        self.assertIn(r"D:\Works With Spaces\attendance\tts\nghi_frontend.mjs", command)
        self.assertIn(r"D:\Works With Spaces\attendance\tts\runtime\nghitts", command)
        self.assertFalse(any('"' in part for part in command))


class _FakeVoiceConfig:
    sample_rate = 1000


class _FakeVoice:
    def __init__(self, fail_on_call=None):
        self.config = _FakeVoiceConfig()
        self.calls = []
        self.fail_on_call = fail_on_call

    def phoneme_ids_to_audio(self, ids, syn_config=None, include_alignments=False):
        self.calls.append((list(ids), syn_config))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("onnx failed")
        value = 0.25 if len(self.calls) == 1 else -0.25
        return [value] * 4

    def phonemize(self, *_args, **_kwargs):
        raise AssertionError("stock Piper phonemizer must not be called")

    def synthesize(self, *_args, **_kwargs):
        raise AssertionError("Piper synthesize(text) must not be called")

    def synthesize_wav(self, *_args, **_kwargs):
        raise AssertionError("Piper synthesize_wav(text) must not be called")


class _FakeFrontend:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or [
            {"text": "câu một.", "phoneme_ids": [1, 0, 131, 0, 2]},
            {"text": "câu hai.", "phoneme_ids": [1, 0, 137, 0, 2]},
        ]
        self.error = error
        self.seen = []

    def process(self, text):
        self.seen.append(text)
        if self.error:
            raise self.error
        return {"processed_text": text.lower(), "chunks": self.chunks}

    def close(self):
        pass


class NghiOnnxSynthesizerTests(unittest.TestCase):
    def _synth(self, frontend=None, voice=None):
        synth = tts_worker.NghiOnnxSynthesizer(Path("voice.onnx"), Path("voice.onnx.json"), frontend or _FakeFrontend())
        synth._voice = voice or _FakeVoice()
        synth._make_synthesis_config = lambda: type("Cfg", (), {
            "speaker_id": 0, "length_scale": 1.0, "noise_scale": 0.667, "noise_w_scale": 0.8
        })()
        return synth

    def test_synthesizer_calls_phoneme_ids_to_audio_per_chunk_in_order(self):
        voice = _FakeVoice()
        synth = self._synth(voice=voice)
        with tempfile.TemporaryDirectory() as tmp:
            synth("HUỲNH Quốc Phước. Mời sinh viên tiếp theo.", Path(tmp) / "out.wav")
        self.assertEqual([call[0] for call in voice.calls], [[1, 0, 131, 0, 2], [1, 0, 137, 0, 2]])

    def test_synthesizer_uses_nghi_default_scales_and_speaker_zero(self):
        voice = _FakeVoice()
        synth = self._synth(voice=voice)
        with tempfile.TemporaryDirectory() as tmp:
            synth("Xin chào.", Path(tmp) / "out.wav")
        cfg = voice.calls[0][1]
        self.assertEqual(cfg.speaker_id, 0)
        self.assertEqual(cfg.length_scale, 1.0)
        self.assertAlmostEqual(cfg.noise_scale, 0.667)
        self.assertAlmostEqual(cfg.noise_w_scale, 0.8)

    def test_synthesizer_appends_chunk_audio_without_inserted_samples(self):
        synth = self._synth()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.wav"
            synth("Hai câu.", output)
            with wave.open(str(output), "rb") as wav_file:
                self.assertEqual(wav_file.getframerate(), 1000)
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getnframes(), 8)

    def test_synthesizer_never_calls_piper_text_frontend(self):
        synth = self._synth(voice=_FakeVoice())
        with tempfile.TemporaryDirectory() as tmp:
            synth("Hai câu.", Path(tmp) / "out.wav")

    def test_partial_output_is_removed_on_frontend_failure(self):
        synth = self._synth(frontend=_FakeFrontend(error=RuntimeError("frontend failed")))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.wav"
            with self.assertRaisesRegex(RuntimeError, "frontend failed"):
                synth("Xin chào", output)
            self.assertFalse(output.exists())

    def test_partial_output_is_removed_on_second_chunk_inference_failure(self):
        synth = self._synth(voice=_FakeVoice(fail_on_call=2))
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.wav"
            with self.assertRaisesRegex(RuntimeError, "onnx failed"):
                synth("Hai câu.", output)
            self.assertFalse(output.exists())


class TTSWindowsScriptContractTests(unittest.TestCase):
    def test_setup_script_pins_native_windows_runtime_voice_and_smoke_test(self):
        text = (ROOT / "Setup-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn("piper_windows_amd64.zip", text)
        self.assertIn("2023.11.14-2", text)
        self.assertIn('set "voice_id=calmwoman3688"', text)
        self.assertIn("--smoke-test", text)

    def test_check_script_is_read_only(self):
        text = (ROOT / "Check-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn("tts_service.get_status", text)
        for forbidden in ("pip install", "invoke-webrequest", "curl ", "bitsadmin", "start-bitstransfer"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
