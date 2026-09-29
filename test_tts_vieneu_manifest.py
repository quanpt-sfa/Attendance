import json
import tempfile
import unittest
from pathlib import Path

import tts_vieneu_manifest


READY = {
    "voice": "Thùy Dung",
    "engine": "vieneu-v3-turbo",
    "engine_version": "3.8.3",
    "backend": "onnx-fp32",
    "offline_verified": True,
    "artifacts": [{"path": "hub/models--x/blobs/a", "size": 123}],
}


class ManifestTests(unittest.TestCase):
    def test_load_manifest_returns_none_for_missing_or_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.json"
            self.assertIsNone(tts_vieneu_manifest.load_manifest(path))
            path.write_text("not-json", encoding="utf-8")
            self.assertIsNone(tts_vieneu_manifest.load_manifest(path))

    def test_manifest_ready_requires_exact_identity_and_offline_proof(self):
        self.assertTrue(tts_vieneu_manifest.manifest_is_ready(dict(READY)))
        for key, wrong in (
            ("voice", "Mỹ Duyên"),
            ("engine", "other"),
            ("engine_version", "3.8.2"),
            ("backend", "onnx-int8"),
            ("offline_verified", False),
        ):
            value = dict(READY)
            value[key] = wrong
            self.assertFalse(tts_vieneu_manifest.manifest_is_ready(value), key)
        self.assertFalse(tts_vieneu_manifest.manifest_is_ready(None))
        self.assertFalse(tts_vieneu_manifest.manifest_is_ready({}))

    def test_load_manifest_reads_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.json"
            path.write_text(json.dumps(READY, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(tts_vieneu_manifest.load_manifest(path)["voice"], "Thùy Dung")


if __name__ == "__main__":
    unittest.main()
