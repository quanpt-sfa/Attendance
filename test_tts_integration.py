import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tts_service


FAKE_WAV = b"RIFF\x04\x00\x00\x00WAVE"


class OfflineTTSAcceptanceTests(unittest.TestCase):
    def tearDown(self):
        tts_service.shutdown_worker()

    def test_attendance_tts_modules_import_without_piper_installed(self):
        code = (
            "import sys; "
            "sys.modules['piper'] = None; "
            "import tts_service, tts_worker, server_tts, startup; "
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_missing_local_runtime_degrades_to_unavailable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(tts_service, "TTS_VENV", root / ".venv-tts"),
                mock.patch.object(tts_service, "VOICE_DIR", root / "voices"),
                mock.patch.object(tts_service, "CACHE_DIR", root / "cache"),
            ):
                status = tts_service.get_status()
        self.assertFalse(status["available"])
        self.assertFalse(status["runtime_present"])
        self.assertFalse(status["model_present"])

    def test_fake_synthesis_creates_reusable_offline_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            calls = []

            def synth(text, output):
                calls.append(text)
                output = Path(output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(FAKE_WAV)

            with (
                mock.patch.object(tts_service, "CACHE_DIR", cache),
                mock.patch.object(tts_service, "_synthesize_to_path", side_effect=synth),
            ):
                first = tts_service.ensure_audio("Nguyễn Thị An")
                second = tts_service.ensure_audio(" Nguyễn  Thị An ")

            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), FAKE_WAV)
            self.assertEqual(calls, ["Nguyễn Thị An"])

    def test_worker_shutdown_is_safe_and_idempotent(self):
        tts_service.shutdown_worker()
        tts_service.shutdown_worker()

    def test_runtime_artifact_paths_are_gitignored(self):
        ignore = (Path(__file__).resolve().parent / ".gitignore").read_text(encoding="utf-8-sig")
        self.assertIn(".venv-tts/", ignore)
        self.assertIn("tts/voices/", ignore)
        self.assertIn("tts_cache/", ignore)


if __name__ == "__main__":
    unittest.main()
