import tempfile
import threading
import time
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

import tts_service


FAKE_WAV = b"RIFF\x04\x00\x00\x00WAVE"


class TTSServicePureTests(unittest.TestCase):
    def test_normalize_text_preserves_vietnamese_and_collapses_whitespace(self):
        raw = "  Nguye\u0302\u0303n   Thị  An  "
        result = tts_service.normalize_text(raw)
        self.assertEqual(result, "Nguyễn Thị An")
        self.assertEqual(unicodedata.normalize("NFC", result), result)

    def test_cache_key_is_deterministic_for_same_text_and_config(self):
        first = tts_service.cache_key("Nguyễn Thị An")
        second = tts_service.cache_key("  Nguyễn   Thị An ")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_cache_key_changes_when_text_changes(self):
        self.assertNotEqual(
            tts_service.cache_key("Nguyễn Thị An"),
            tts_service.cache_key("Nguyễn Thị Anh"),
        )

    def test_cache_key_changes_when_voice_revision_changes(self):
        original = tts_service.cache_key("Nguyễn Thị An")
        with mock.patch.object(tts_service, "VOICE_REVISION", "future-revision"):
            changed = tts_service.cache_key("Nguyễn Thị An")
        self.assertNotEqual(original, changed)

    def test_default_voice_is_pinned_nghi_tts_vietnamese_voice(self):
        self.assertEqual(tts_service.VOICE_ID, "calmwoman3688")
        self.assertEqual(
            tts_service.VOICE_REVISION,
            "sannht-vi_voice-62e57b18157ed213b3863a7a8a35b14d3404554b",
        )

    def test_cache_format_is_bumped_after_native_backend_switch(self):
        self.assertEqual(tts_service.CACHE_FORMAT_VERSION, 3)


class TTSServiceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache_patch = mock.patch.object(tts_service, "CACHE_DIR", self.root / "cache")
        self.cache_patch.start()
        tts_service.shutdown_worker()

    def tearDown(self):
        tts_service.shutdown_worker()
        self.cache_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def write_fake_wav(_text, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(FAKE_WAV)

    def test_cache_miss_synthesizes_once_then_cache_hit_reuses_file(self):
        calls = []

        def synth(text, output_path):
            calls.append(text)
            self.write_fake_wav(text, output_path)

        with mock.patch.object(tts_service, "_synthesize_to_path", side_effect=synth):
            first = tts_service.ensure_audio("Nguyễn Thị An")
            second = tts_service.ensure_audio("  Nguyễn   Thị An ")

        self.assertEqual(first, second)
        self.assertEqual(calls, ["Nguyễn Thị An"])
        self.assertEqual(first.read_bytes(), FAKE_WAV)

    def test_concurrent_same_key_requests_synthesize_only_once(self):
        calls = []
        start = threading.Barrier(3)
        results = []
        errors = []

        def synth(text, output_path):
            calls.append(text)
            time.sleep(0.05)
            self.write_fake_wav(text, output_path)

        def run():
            try:
                start.wait()
                results.append(tts_service.ensure_audio("Nguyễn Văn Bình"))
            except Exception as exc:  # pragma: no cover - diagnostic capture
                errors.append(exc)

        with mock.patch.object(tts_service, "_synthesize_to_path", side_effect=synth):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(calls, ["Nguyễn Văn Bình"])

    def test_failed_synthesis_leaves_no_partial_or_final_wav(self):
        def synth(_text, output_path):
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"partial")
            raise RuntimeError("boom")

        with mock.patch.object(tts_service, "_synthesize_to_path", side_effect=synth):
            with self.assertRaises(tts_service.TTSSynthesisError):
                tts_service.ensure_audio("Trần Thị Mai")

        files = [path for path in (self.root / "cache").rglob("*") if path.is_file()]
        self.assertEqual(files, [])

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValueError):
            tts_service.ensure_audio("   ")

    def test_precache_deduplicates_names_and_counts_cached_generated_failed(self):
        cached_path = tts_service._cache_path("Nguyễn Văn An")
        self.write_fake_wav("Nguyễn Văn An", cached_path)
        calls = []

        def fake_ensure(name):
            calls.append(name)
            if name == "Lỗi Tổng Hợp":
                raise tts_service.TTSUnavailableError("missing runtime")
            path = tts_service._cache_path(name)
            self.write_fake_wav(name, path)
            return path

        students = [
            {"full_name": "Nguyễn Văn An"},
            {"full_name": "  Nguyễn  Văn An "},
            {"full_name": "Trần Thị Bình"},
            {"fullName": "Trần Thị Bình"},
            {"full_name": "Lỗi Tổng Hợp"},
            {"full_name": "   "},
        ]
        with mock.patch.object(tts_service, "ensure_audio", side_effect=fake_ensure):
            result = tts_service.precache_students(students)

        self.assertEqual(
            result,
            {"total": 3, "generated": 1, "cached": 1, "failed": 1},
        )
        self.assertEqual(calls, ["Trần Thị Bình", "Lỗi Tổng Hợp"])


class TTSServiceStatusTests(unittest.TestCase):
    def test_missing_runtime_and_model_report_unavailable_without_crash(self):
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
        self.assertEqual(status["voice"], "calmwoman3688")
        self.assertEqual(status["cache_files"], 0)


if __name__ == "__main__":
    unittest.main()
