import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tts_service


class NghiRuntimeAssetStatusTests(unittest.TestCase):
    def test_missing_nghi_npm_assets_or_commit_marker_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "python.exe"
            node = root / "node.exe"
            adapter = root / "nghi_frontend.mjs"
            nghi = root / "nghitts"
            model = root / "voice.onnx"
            config = root / "voice.onnx.json"
            worker = root / "tts_worker.py"
            for path in (python, node, adapter, model, config, worker):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            nghi.mkdir(parents=True, exist_ok=True)

            with (
                mock.patch.object(tts_service, "NODE_EXE", node),
                mock.patch.object(tts_service, "NGHI_ROOT", nghi),
                mock.patch.object(tts_service, "NGHI_ADAPTER", adapter),
                mock.patch.object(tts_service, "WORKER_SCRIPT", worker),
                mock.patch.object(tts_service, "_worker_python", return_value=python),
                mock.patch.object(tts_service, "_voice_model", return_value=model),
                mock.patch.object(tts_service, "_voice_config", return_value=config),
            ):
                status = tts_service.get_status()
                self.assertFalse(status["available"])
                self.assertFalse(status["nghi_frontend_present"])

                (nghi / ".attendance-nghi-commit").write_text(
                    tts_service.NGHI_COMMIT + "\n", encoding="utf-8"
                )
                status = tts_service.get_status()
                self.assertFalse(status["available"])
                self.assertFalse(status["nghi_frontend_present"])

                phonemizer = nghi / "node_modules" / "phonemizer"
                phonemizer.mkdir(parents=True)
                status = tts_service.get_status()
                self.assertTrue(status["available"])
                self.assertTrue(status["nghi_frontend_present"])

    def test_wrong_nghi_commit_marker_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "python.exe"
            node = root / "node.exe"
            adapter = root / "nghi_frontend.mjs"
            nghi = root / "nghitts"
            model = root / "voice.onnx"
            config = root / "voice.onnx.json"
            worker = root / "tts_worker.py"
            for path in (python, node, adapter, model, config, worker):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            (nghi / "node_modules" / "phonemizer").mkdir(parents=True)
            (nghi / ".attendance-nghi-commit").write_text("wrong\n", encoding="utf-8")

            with (
                mock.patch.object(tts_service, "NODE_EXE", node),
                mock.patch.object(tts_service, "NGHI_ROOT", nghi),
                mock.patch.object(tts_service, "NGHI_ADAPTER", adapter),
                mock.patch.object(tts_service, "WORKER_SCRIPT", worker),
                mock.patch.object(tts_service, "_worker_python", return_value=python),
                mock.patch.object(tts_service, "_voice_model", return_value=model),
                mock.patch.object(tts_service, "_voice_config", return_value=config),
            ):
                status = tts_service.get_status()
                self.assertFalse(status["available"])
                self.assertFalse(status["nghi_frontend_present"])


if __name__ == "__main__":
    unittest.main()
