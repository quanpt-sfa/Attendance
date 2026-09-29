import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent


class SetupScriptContractTests(unittest.TestCase):
    def test_setup_pins_vieneu_and_proves_fresh_process_offline_smoke_before_manifest(self):
        text = (ROOT / "Setup-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn('set "vieneu_version=3.8.3"', text)
        self.assertIn('vieneu==%vieneu_version%', text)
        self.assertIn('materialize_vieneu_models.py', text)
        self.assertIn('set "hf_home=%~dp0tts\\runtime\\vieneu\\hf"', text)
        self.assertIn('set "hf_hub_cache=%hf_home%\\hub"', text)
        self.assertIn('hf_hub_offline=1', text)
        self.assertGreaterEqual(text.count('tts_worker.py --smoke-test'), 2)
        materialize = text.index('materialize_vieneu_models.py')
        online = text.index('tts_worker.py --smoke-test')
        offline_flag = text.index('hf_hub_offline=1')
        offline = text.index('tts_worker.py --smoke-test', online + 1)
        manifest = text.index('write_vieneu_manifest.py')
        self.assertLess(materialize, online)
        self.assertLess(online, offline_flag)
        self.assertLess(offline_flag, offline)
        self.assertLess(offline, manifest)
        self.assertIn('importlib.metadata.version', text)
        for forbidden in ('piper_windows_amd64.zip', 'calmwoman3688', 'nghi_commit', 'node.exe', '--native-piper'):
            self.assertNotIn(forbidden, text)

    def test_check_script_is_read_only_and_reports_vieneu_status(self):
        text = (ROOT / "Check-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn('.venv-tts\\scripts\\python.exe', text)
        self.assertIn('tts_service.get_status', text)
        for label in ('voice:', 'engine:', 'version:', 'backend:', 'runtime:', 'offline assets:', 'cache:'):
            self.assertIn(label, text)
        for forbidden in ('pip install', 'invoke-webrequest', 'curl ', 'bitsadmin', 'start-bitstransfer', 'git clone', 'npm '):
            self.assertNotIn(forbidden, text)


class MaterializedAssetTests(unittest.TestCase):
    def test_materializer_downloads_onnx_and_external_data_into_real_local_directories(self):
        from tools import materialize_vieneu_models as module
        calls = []

        def fake_download(repo_id, filename, **kwargs):
            calls.append((repo_id, filename, kwargs))
            local_dir = Path(kwargs["local_dir"])
            subfolder = kwargs.get("subfolder")
            target = local_dir / subfolder / filename if subfolder else local_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            return str(target)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_root = root / "v3turbo"
            codec_dir = root / "codec"
            module.materialize(model_root=model_root, codec_dir=codec_dir, download=fake_download)

            for name in module.GRAPH_FILES:
                self.assertTrue((model_root / "onnx_update" / name).is_file(), name)
            for name in module.CODEC_FILES:
                self.assertTrue((codec_dir / name).is_file(), name)

        self.assertEqual(len(calls), len(module.GRAPH_FILES) + len(module.CODEC_FILES))
        graph_calls = calls[: len(module.GRAPH_FILES)]
        codec_calls = calls[len(module.GRAPH_FILES) :]
        self.assertTrue(all(call[0] == module.MODEL_REPO_ID for call in graph_calls))
        self.assertTrue(all(call[2].get("subfolder") == "onnx_update" for call in graph_calls))
        self.assertTrue(all(Path(call[2]["local_dir"]) == model_root for call in graph_calls))
        self.assertTrue(all(call[0] == module.CODEC_REPO_ID for call in codec_calls))
        self.assertTrue(all(call[2].get("subfolder") is None for call in codec_calls))
        self.assertTrue(all(Path(call[2]["local_dir"]) == codec_dir for call in codec_calls))


class ManifestWriterTests(unittest.TestCase):
    def setUp(self):
        from tools import write_vieneu_manifest
        self.module = write_vieneu_manifest

    def test_build_manifest_requires_exact_package_version_and_nonempty_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "hub"
            cache.mkdir()
            with mock.patch.object(self.module.importlib.metadata, "version", return_value="3.8.2"):
                with self.assertRaisesRegex(RuntimeError, "3.8.3"):
                    self.module.build_manifest(cache)
            with mock.patch.object(self.module.importlib.metadata, "version", return_value="3.8.3"):
                with self.assertRaisesRegex(RuntimeError, "empty"):
                    self.module.build_manifest(cache)

    def test_build_manifest_records_identity_timestamp_and_relative_artifact_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "hub"
            artifact = cache / "models--demo" / "blobs" / "abc"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"12345")
            with mock.patch.object(self.module.importlib.metadata, "version", return_value="3.8.3"):
                manifest = self.module.build_manifest(cache)
        self.assertEqual(manifest["voice"], "Thùy Dung")
        self.assertEqual(manifest["engine"], "vieneu-v3-turbo")
        self.assertEqual(manifest["engine_version"], "3.8.3")
        self.assertEqual(manifest["backend"], "onnx-fp32")
        self.assertIs(manifest["offline_verified"], True)
        self.assertTrue(manifest["setup_timestamp_utc"].endswith("+00:00"))
        self.assertEqual(manifest["artifacts"], [{"path": "models--demo/blobs/abc", "size": 5}])

    def test_write_manifest_is_atomic_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "hub"
            artifact = cache / "x.bin"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"xx")
            output = root / "setup.json"
            with mock.patch.object(self.module.importlib.metadata, "version", return_value="3.8.3"):
                self.module.write_manifest(cache, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["offline_verified"])
            self.assertFalse(any(root.glob("setup.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
