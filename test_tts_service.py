import io
import json
import queue
import tempfile
import threading
import time
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

import tts_service

FAKE_WAV = b"RIFF\x04\x00\x00\x00WAVE"
READY_LINE = json.dumps({
    "type": "ready", "ok": True, "voice": "Thùy Dung",
    "engine": "vieneu-v3-turbo", "backend": "onnx-fp32",
}) + "\n"


class TTSServicePureTests(unittest.TestCase):
    def test_vieneu_identity_and_cache_version_are_pinned(self):
        self.assertEqual(tts_service.VOICE_ID, "Thùy Dung")
        self.assertEqual(tts_service.TTS_ENGINE, "vieneu-v3-turbo")
        self.assertEqual(tts_service.TTS_ENGINE_VERSION, "3.8.3")
        self.assertEqual(tts_service.TTS_BACKEND, "onnx-fp32")
        self.assertEqual(tts_service.CACHE_FORMAT_VERSION, 6)
        self.assertEqual(tts_service.WORKER_STARTUP_TIMEOUT_SECONDS, 90.0)
        self.assertEqual(tts_service.WORKER_REQUEST_TIMEOUT_SECONDS, 45.0)

    def test_normalize_text_preserves_case_punctuation_and_collapses_whitespace(self):
        raw = "  Nguye\u0302\u0303n   Thị  THÚY.  "
        result = tts_service.normalize_text(raw)
        self.assertEqual(result, "Nguyễn Thị THÚY.")
        self.assertEqual(unicodedata.normalize("NFC", result), result)

    def test_cache_key_is_deterministic_and_sensitive_to_all_engine_identity(self):
        base = tts_service.cache_key("  Nguyễn   Thị An ")
        self.assertEqual(base, tts_service.cache_key("Nguyễn Thị An"))
        self.assertEqual(len(base), 64)
        for attr, value in (
            ("VOICE_ID", "Mỹ Duyên"),
            ("TTS_ENGINE", "vieneu-v4"),
            ("TTS_ENGINE_VERSION", "3.8.4"),
            ("TTS_BACKEND", "onnx-int8"),
        ):
            with mock.patch.object(tts_service, attr, value):
                self.assertNotEqual(base, tts_service.cache_key("Nguyễn Thị An"), attr)
        self.assertNotEqual(base, tts_service.cache_key("Nguyễn Thị Anh"))


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
        calls, results, errors = [], [], []
        start = threading.Barrier(3)
        def synth(text, output_path):
            calls.append(text)
            time.sleep(0.05)
            self.write_fake_wav(text, output_path)
        def run():
            try:
                start.wait()
                results.append(tts_service.ensure_audio("Nguyễn Văn Bình"))
            except Exception as exc:
                errors.append(exc)
        with mock.patch.object(tts_service, "_synthesize_to_path", side_effect=synth):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads: thread.start()
            start.wait()
            for thread in threads: thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(results[0], results[1])
        self.assertEqual(calls, ["Nguyễn Văn Bình"])

    def test_failed_synthesis_leaves_no_partial_or_final_wav(self):
        def synth(_text, output_path):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(b"partial")
            raise RuntimeError("boom")
        with mock.patch.object(tts_service, "_synthesize_to_path", side_effect=synth):
            with self.assertRaises(tts_service.TTSSynthesisError):
                tts_service.ensure_audio("Trần Thị Mai")
        files = [p for p in (self.root / "cache").rglob("*") if p.is_file()]
        self.assertEqual(files, [])

    def test_precache_deduplicates_names_and_counts_results(self):
        cached_path = tts_service._cache_path("Nguyễn Văn An")
        self.write_fake_wav("x", cached_path)
        calls = []
        def fake_ensure(name):
            calls.append(name)
            if name == "Lỗi Tổng Hợp":
                raise tts_service.TTSUnavailableError("missing runtime")
            path = tts_service._cache_path(name)
            self.write_fake_wav(name, path)
            return path
        students = [
            {"full_name":"Nguyễn Văn An"}, {"full_name":"  Nguyễn  Văn An "},
            {"full_name":"Trần Thị Bình"}, {"fullName":"Trần Thị Bình"},
            {"full_name":"Lỗi Tổng Hợp"},
        ]
        with mock.patch.object(tts_service, "ensure_audio", side_effect=fake_ensure):
            result = tts_service.precache_students(students)
        self.assertEqual(result, {"total":3,"generated":1,"cached":1,"failed":1})
        self.assertEqual(calls, ["Trần Thị Bình", "Lỗi Tổng Hợp"])


class TTSServiceStatusTests(unittest.TestCase):
    def _patch_paths(self, root):
        return (
            mock.patch.object(tts_service, "TTS_VENV", root / ".venv-tts"),
            mock.patch.object(tts_service, "TTS_RUNTIME_ROOT", root / "runtime"),
            mock.patch.object(tts_service, "HF_HOME", root / "runtime" / "hf"),
            mock.patch.object(tts_service, "HF_HUB_CACHE", root / "runtime" / "hf" / "hub"),
            mock.patch.object(tts_service, "SETUP_MANIFEST", root / "runtime" / "setup.json"),
            mock.patch.object(tts_service, "CACHE_DIR", root / "cache"),
            mock.patch.object(tts_service, "WORKER_SCRIPT", Path(__file__).resolve()),
        )

    def test_missing_runtime_manifest_and_cache_report_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = self._patch_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                status = tts_service.get_status()
        self.assertFalse(status["available"])
        self.assertFalse(status["runtime_present"])
        self.assertFalse(status["offline_assets_present"])
        self.assertEqual(status["voice"], "Thùy Dung")
        self.assertEqual(status["engine_version"], "3.8.3")

    def test_ready_status_requires_venv_distribution_manifest_and_nonempty_hf_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patches = self._patch_paths(root)
            (root / ".venv-tts" / "bin").mkdir(parents=True)
            (root / ".venv-tts" / "bin" / "python").write_text("")
            dist = root / ".venv-tts" / "lib" / "python3.12" / "site-packages" / "vieneu-3.8.3.dist-info"
            dist.mkdir(parents=True)
            hub = root / "runtime" / "hf" / "hub" / "models--x" / "blobs"
            hub.mkdir(parents=True)
            (hub / "blob").write_bytes(b"x")
            manifest = root / "runtime" / "setup.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"voice":"Thùy Dung","engine":"vieneu-v3-turbo","engine_version":"3.8.3","backend":"onnx-fp32","offline_verified":True}), encoding="utf-8")
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                status = tts_service.get_status()
        self.assertTrue(status["available"])
        self.assertTrue(status["package_present"])
        self.assertTrue(status["offline_assets_present"])

    def test_old_piper_files_do_not_make_runtime_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime" / "piper").mkdir(parents=True)
            (root / "runtime" / "piper" / "piper.exe").write_text("")
            patches = self._patch_paths(root)
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
                status = tts_service.get_status()
        self.assertFalse(status["available"])


class FakeProcess:
    def __init__(self, stdout_text=READY_LINE):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout_text)
        self.returncode = None
    def poll(self): return self.returncode
    def terminate(self): self.returncode = 0
    def kill(self): self.returncode = -9
    def wait(self, timeout=None): self.returncode = 0; return 0


class TTSWorkerLaunchTests(unittest.TestCase):
    def tearDown(self):
        tts_service.shutdown_worker()

    def _runtime_ok(self):
        return {"runtime_present":True,"offline_assets_present":True,"python_runtime_present":True,"package_present":True,"manifest_ready":True,"hf_cache_present":True}

    def test_worker_launch_uses_offline_environment_simple_command_and_ready_handshake(self):
        fake = FakeProcess()
        existing = Path(__file__).resolve()
        with tempfile.TemporaryDirectory() as tmp, (
            mock.patch.object(tts_service, "_runtime_components", return_value=self._runtime_ok()),
            mock.patch.object(tts_service, "WORKER_SCRIPT", existing),
            mock.patch.object(tts_service, "_worker_python", return_value=Path("python")),
            mock.patch.object(tts_service, "HF_HOME", Path(tmp) / "hf"),
            mock.patch.object(tts_service, "HF_HUB_CACHE", Path(tmp) / "hf" / "hub"),
            mock.patch.object(tts_service.subprocess, "Popen", return_value=fake) as popen,
        ):
            result = tts_service._start_worker_locked()
        self.assertIs(result, fake)
        self.assertEqual(popen.call_args.args[0], ["python", str(existing), "--serve"])
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8:strict")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["HF_HOME"], str(Path(tmp) / "hf"))
        self.assertEqual(env["HF_HUB_CACHE"], str(Path(tmp) / "hf" / "hub"))

    def test_failed_or_malformed_ready_line_is_unavailable(self):
        existing = Path(__file__).resolve()
        for line in (json.dumps({"type":"ready","ok":False,"error":"bad model"}) + "\n", "{}\n"):
            tts_service.shutdown_worker()
            with mock.patch.object(tts_service,"_runtime_components",return_value=self._runtime_ok()), mock.patch.object(tts_service,"WORKER_SCRIPT",existing), mock.patch.object(tts_service,"_worker_python",return_value=Path("python")), mock.patch.object(tts_service.subprocess,"Popen",return_value=FakeProcess(line)):
                with self.assertRaises(tts_service.TTSUnavailableError):
                    tts_service._start_worker_locked()

    def test_startup_timeout_is_bounded_to_90_seconds(self):
        class TimeoutQueue:
            def put(self, _value): pass
            def get(self, timeout=None): self.timeout = timeout; raise queue.Empty
        q = TimeoutQueue()
        existing = Path(__file__).resolve()
        with mock.patch.object(tts_service,"_runtime_components",return_value=self._runtime_ok()), mock.patch.object(tts_service,"WORKER_SCRIPT",existing), mock.patch.object(tts_service,"_worker_python",return_value=Path("python")), mock.patch.object(tts_service.queue,"Queue",return_value=q), mock.patch.object(tts_service.subprocess,"Popen",return_value=FakeProcess("")):
            with self.assertRaisesRegex(tts_service.TTSUnavailableError, "timed out"):
                tts_service._start_worker_locked()
        self.assertEqual(q.timeout, 90.0)

    def test_request_timeout_is_separate_45_seconds(self):
        seen = {}
        class Q:
            def get(self, timeout=None):
                seen["timeout"] = timeout
                return json.dumps({"id":"fixed","ok":True}) + "\n"
        fake = FakeProcess("")
        with mock.patch.object(tts_service,"_start_worker_locked",return_value=fake), mock.patch.object(tts_service,"_worker_queue",Q()), mock.patch.object(tts_service.uuid,"uuid4",return_value=type("U",(),{"hex":"fixed"})()):
            tts_service._request_worker_locked("Xin chào", Path("out.wav"))
        self.assertEqual(seen["timeout"], 45.0)


if __name__ == "__main__":
    unittest.main()
