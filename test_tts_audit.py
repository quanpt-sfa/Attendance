import unittest
from pathlib import Path

from tools import tts_phoneme_audit as audit


ROOT = Path(__file__).resolve().parent


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

    def test_audit_piper_voice_collects_each_sentence_chunk_and_onnx_ids(self):
        class FakeVoice:
            def phonemize(self, text):
                self.text = text
                return [list("abc."), list("def?")]

            def phonemes_to_ids(self, phonemes):
                terminal = phonemes[-1]
                terminal_id = {".": 10, "?": 13}[terminal]
                return [1, 0, terminal_id, 0, 2]

        config = {
            "phoneme_id_map": {
                "^": [1], "_": [0], "$": [2],
                ".": [10], ",": [8], "!": [4], "?": [13], ":": [11], ";": [12],
            }
        }
        voice = FakeVoice()
        result = audit.audit_piper_voice(voice, "Hai câu.", config)

        self.assertEqual(voice.text, "hai câu.")
        self.assertEqual(len(result["sentences"]), 2)
        self.assertEqual(result["sentences"][0]["phoneme_string"], "abc.")
        self.assertEqual(result["sentences"][0]["phoneme_ids"], [1, 0, 10, 0, 2])
        self.assertEqual(result["sentences"][1]["phoneme_ids"], [1, 0, 13, 0, 2])

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
            "metadata": {
                "nghi_commit": audit.NGHI_COMMIT,
                "piper_runtime": "piper-tts 1.8.0",
            },
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
        self.assertIn("piper-tts 1.8.0", report)
        self.assertIn("46d160da32041f7e176607203b958069265df7da", report)
        self.assertIn("Huỳnh Quốc Phước", report)

    def test_nghi_json_parser_rejects_missing_cases(self):
        with self.assertRaisesRegex(ValueError, "cases"):
            audit.validate_nghi_payload({"metadata": {}})

    def test_nghi_json_parser_requires_scalar_ids_that_match_onnx_tensor(self):
        cases = []
        for sentence in audit.TEST_SENTENCES:
            cases.append(
                {
                    "original": sentence,
                    "processed_text": sentence.lower(),
                    "chunks": [
                        {
                            "text": sentence.lower(),
                            "phoneme_string": "foo.",
                            "phoneme_ids": [[1], [0], [10], [0], [2]],
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(ValueError, "scalar integer"):
            audit.validate_nghi_payload({"metadata": {}, "cases": cases})

    def test_powershell_audit_uses_same_venv_as_production_and_no_legacy_exe(self):
        text = (ROOT / "tools" / "tts_phoneme_audit.ps1").read_text(encoding="utf-8").lower()
        self.assertIn(".venv-tts\\scripts\\python.exe", text)
        self.assertNotIn("tts\\runtime\\piper\\piper.exe", text)
        self.assertNotIn("--piper-exe", text)


if __name__ == "__main__":
    unittest.main()
