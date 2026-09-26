import unicodedata
import unittest
from unittest import mock

import tts_service


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


if __name__ == "__main__":
    unittest.main()
