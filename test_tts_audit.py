import copy
import unittest
from pathlib import Path

from tools import tts_phoneme_audit as audit


ROOT = Path(__file__).resolve().parent


def make_payload():
    cases = []
    for index, sentence in enumerate(audit.TEST_SENTENCES):
        if index == 1:
            chunks = [
                {"text": "huỳnh quốc phước đã điểm danh thành công.", "phoneme_ids": [1, 0, 131, 0, 2]},
                {"text": "mời sinh viên tiếp theo.", "phoneme_ids": [1, 0, 137, 0, 2]},
            ]
        else:
            chunks = [{"text": sentence.lower(), "phoneme_ids": [1, 0, index + 10, 0, 2]}]
        cases.append({
            "original": sentence,
            "processed_text": sentence.lower(),
            "chunks": chunks,
        })
    return {"metadata": {"nghi_commit": audit.NGHI_COMMIT}, "cases": cases}


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

    def test_validate_payload_requires_all_cases_and_scalar_integer_ids(self):
        with self.assertRaisesRegex(ValueError, "cases"):
            audit.validate_nghi_payload({"metadata": {}})
        payload = make_payload()
        payload["cases"][0]["chunks"][0]["phoneme_ids"] = [[1], [0], [2]]
        with self.assertRaisesRegex(ValueError, "scalar integer"):
            audit.validate_nghi_payload(payload)

    def test_compare_frontend_parity_accepts_exact_match_and_case2_two_chunks(self):
        oracle = make_payload()
        production = copy.deepcopy(oracle)
        result = audit.compare_frontend_parity(oracle, production)
        self.assertTrue(result["all_match"])
        self.assertEqual(len(result["cases"]), 5)
        self.assertEqual(len(result["cases"][1]["production"]["chunks"]), 2)
        self.assertTrue(all(case["match"] for case in result["cases"]))

    def test_compare_frontend_parity_rejects_processed_text_mismatch(self):
        oracle = make_payload(); production = copy.deepcopy(oracle)
        production["cases"][0]["processed_text"] = "khác"
        with self.assertRaisesRegex(ValueError, r"Case 1.*processed_text"):
            audit.compare_frontend_parity(oracle, production)

    def test_compare_frontend_parity_rejects_chunk_count_and_case2_not_two(self):
        oracle = make_payload(); production = copy.deepcopy(oracle)
        production["cases"][1]["chunks"] = production["cases"][1]["chunks"][:1]
        with self.assertRaisesRegex(ValueError, r"Case 2.*chunk count|Case 2.*two chunks"):
            audit.compare_frontend_parity(oracle, production)

    def test_compare_frontend_parity_rejects_chunk_text_mismatch(self):
        oracle = make_payload(); production = copy.deepcopy(oracle)
        production["cases"][2]["chunks"][0]["text"] = "sai câu"
        with self.assertRaisesRegex(ValueError, r"Case 3.*chunk 1.*text"):
            audit.compare_frontend_parity(oracle, production)

    def test_compare_frontend_parity_rejects_first_id_mismatch_with_position(self):
        oracle = make_payload(); production = copy.deepcopy(oracle)
        production["cases"][4]["chunks"][0]["phoneme_ids"][2] = 999
        with self.assertRaisesRegex(ValueError, r"Case 5.*chunk 1.*phoneme id.*index 2"):
            audit.compare_frontend_parity(oracle, production)

    def test_markdown_report_is_oracle_vs_production_and_marks_pass(self):
        oracle = make_payload(); production = copy.deepcopy(oracle)
        result = audit.compare_frontend_parity(oracle, production)
        result["metadata"] = {"nghi_commit": audit.NGHI_COMMIT, "generated_utc": "now"}
        report = audit.render_markdown(result)
        self.assertIn("NGHI oracle", report)
        self.assertIn("Production frontend", report)
        self.assertIn("Parity: PASS", report)
        self.assertIn(audit.NGHI_COMMIT, report)
        self.assertNotIn("Attendance / Piper", report)

    def test_powershell_audit_reuses_installed_runtime_without_network_or_native_piper(self):
        text = (ROOT / "tools" / "tts_phoneme_audit.ps1").read_text(encoding="utf-8").lower()
        self.assertIn("tts\\runtime\\node", text)
        self.assertIn("tts\\runtime\\nghitts", text)
        self.assertIn("tts\\nghi_frontend.mjs", text)
        self.assertIn(".venv-tts\\scripts\\python.exe", text)
        for forbidden in ("piper.exe", "git clone", "npm ci", "invoke-webrequest", "curl "):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
