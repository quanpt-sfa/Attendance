import json
import tempfile
import unittest
from pathlib import Path

from tools import tts_phoneme_audit as audit


class TTSAuditContractTests(unittest.TestCase):
    def test_fixed_sentences_cover_period_comma_exclamation_question(self):
        self.assertEqual(
            audit.TEST_SENTENCES,
            [
                "Huỳnh Quốc Phước đã điểm danh thành công.",
                "Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.",
                "Huỳnh Quốc Phước, bạn đã điểm danh thành công.",
                "Bạn đã điểm danh thành công!",
                "Bạn đã điểm danh thành công?",
            ],
        )

    def test_parse_piper_debug_collects_sentence_phonemes_and_ids(self):
        stderr = """
[2026-09-27 15:00:00.000] [piper] [debug] Phonemes for sentence: hwiɲ kwok fɯək.
[2026-09-27 15:00:00.001] [piper] [debug] Converted 15 phoneme(s) to 33 phoneme id(s): 1, 0, 20, 0, 37, 0, 10, 0, 2,
[2026-09-27 15:00:00.002] [piper] [debug] Phonemes for sentence: mɤj ʂiɲ vjen.
[2026-09-27 15:00:00.003] [piper] [debug] Converted 12 phoneme(s) to 27 phoneme id(s): 1, 0, 26, 0, 10, 0, 2,
"""
        parsed = audit.parse_piper_debug(stderr)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["phoneme_string"], "hwiɲ kwok fɯək.")
        self.assertEqual(parsed[0]["phoneme_ids"], [1, 0, 20, 0, 37, 0, 10, 0, 2])
        self.assertEqual(parsed[1]["phoneme_string"], "mɤj ʂiɲ vjen.")
        self.assertIn(10, parsed[1]["phoneme_ids"])

    def test_analyze_punctuation_reports_character_and_id_positions(self):
        config = {
            "phoneme_id_map": {
                "^": [1], "_": [0], "$": [2],
                ".": [10], ",": [8], "!": [4], "?": [13], ":": [11], ";": [12],
            }
        }
        analysis = audit.analyze_punctuation(
            "abc.", [1, 0, 10, 0, 2], config
        )
        self.assertEqual(analysis["."], {"phoneme_positions": [3], "id": 10, "id_positions": [2]})
        self.assertEqual(analysis[","], {"phoneme_positions": [], "id": 8, "id_positions": []})
        self.assertEqual(analysis["special_ids"], {"BOS": [1], "PAD": [0], "EOS": [2]})

    def test_markdown_report_contains_both_pipeline_sections(self):
        payload = {
            "metadata": {"nghi_commit": audit.NGHI_COMMIT},
            "cases": [
                {
                    "original": audit.TEST_SENTENCES[0],
                    "attendance_spoken_text": "huỳnh quốc phước đã điểm danh thành công.",
                    "piper": {"sentences": [{"phoneme_string": "foo.", "phoneme_ids": [1, 0, 10, 0, 2]}]},
                    "nghi": {"processed_text": "huỳnh quốc phước đã điểm danh thành công.", "chunks": [{"text": "huỳnh quốc phước đã điểm danh thành công.", "phoneme_string": "bar.", "phoneme_ids": [1, 0, 10, 0, 2]}]},
                }
            ],
        }
        report = audit.render_markdown(payload)
        self.assertIn("NGHI-TTS", report)
        self.assertIn("Attendance / Piper", report)
        self.assertIn("46d160da32041f7e176607203b958069265df7da", report)
        self.assertIn("Huỳnh Quốc Phước", report)

    def test_nghi_json_parser_rejects_missing_cases(self):
        with self.assertRaisesRegex(ValueError, "cases"):
            audit.validate_nghi_payload({"metadata": {}})


if __name__ == "__main__":
    unittest.main()
