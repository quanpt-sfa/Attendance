"""Verify production NGHI frontend parity against the pinned upstream oracle.

This development diagnostic compares linguistic inputs before ONNX inference.
It never loads the acoustic model, invokes stock Piper phonemization, or alters
speech timing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NGHI_COMMIT = "46d160da32041f7e176607203b958069265df7da"
VOICE_REVISION = "sannht/vi_voice@62e57b18157ed213b3863a7a8a35b14d3404554b"
TEST_SENTENCES = [
    "Huỳnh Quốc Phước đã điểm danh thành công.",
    "Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.",
    "Huỳnh Quốc Phước, bạn đã điểm danh thành công.",
    "Bạn đã điểm danh thành công!",
    "Bạn đã điểm danh thành công?",
]


def validate_nghi_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a normalized five-case frontend payload."""
    if not isinstance(payload, dict):
        raise ValueError("NGHI audit output must be a JSON object")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("NGHI audit output is missing cases")
    if len(cases) != len(TEST_SENTENCES):
        raise ValueError(f"NGHI audit returned {len(cases)} cases; expected {len(TEST_SENTENCES)}")

    for case_index, (expected_original, case) in enumerate(
        zip(TEST_SENTENCES, cases, strict=True), start=1
    ):
        if not isinstance(case, dict):
            raise ValueError(f"NGHI audit case {case_index} is not an object")
        if case.get("original") != expected_original:
            raise ValueError(
                f"NGHI audit case {case_index} original mismatch: "
                f"expected {expected_original!r}, got {case.get('original')!r}"
            )
        if not isinstance(case.get("processed_text"), str):
            raise ValueError(f"NGHI audit case {case_index} is missing processed_text")
        chunks = case.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"NGHI audit case {case_index} is missing chunks")
        for chunk_index, chunk in enumerate(chunks, start=1):
            if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
                raise ValueError(f"NGHI audit case {case_index} chunk {chunk_index} has invalid text")
            ids = chunk.get("phoneme_ids")
            if not isinstance(ids, list) or not ids or any(type(value) is not int for value in ids):
                raise ValueError(
                    "NGHI phoneme_ids must be a scalar integer sequence matching the "
                    f"ONNX int64 tensor (case {case_index}, chunk {chunk_index})"
                )
    return payload


def _run_command(command: list[str], *, input_text: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_nghi_oracle(node_exe: str, nghi_root: Path, voice_config_path: Path) -> dict[str, Any]:
    """Run the independent upstream audit harness over all fixed sentences."""
    harness = ROOT / "tools" / "nghi_phoneme_audit.mjs"
    command = [
        node_exe,
        str(harness),
        "--nghi-root", str(nghi_root),
        "--voice-config", str(voice_config_path),
        "--expected-commit", NGHI_COMMIT,
    ]
    request = json.dumps({"sentences": TEST_SENTENCES}, ensure_ascii=False)
    completed = _run_command(command, input_text=request, cwd=ROOT)
    if completed.returncode != 0:
        raise RuntimeError(
            f"NGHI oracle failed (exit={completed.returncode}):\n{completed.stderr}"
        )
    try:
        return validate_nghi_payload(json.loads(completed.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "NGHI oracle did not return valid JSON. "
            f"stdout={completed.stdout!r}\nstderr={completed.stderr}"
        ) from exc


def run_production_frontend(
    node_exe: str, nghi_root: Path, voice_config_path: Path
) -> dict[str, Any]:
    """Run the actual production sidecar over the same fixed sentences."""
    adapter = ROOT / "tts" / "nghi_frontend.mjs"
    command = [
        node_exe,
        str(adapter),
        "--nghi-root", str(nghi_root),
        "--voice-config", str(voice_config_path),
        "--expected-commit", NGHI_COMMIT,
    ]
    request_lines = []
    for index, text in enumerate(TEST_SENTENCES, start=1):
        request_lines.append(
            json.dumps(
                {"id": f"audit-{index}", "action": "frontend", "text": text},
                ensure_ascii=False,
            )
        )
    completed = _run_command(command, input_text="\n".join(request_lines) + "\n", cwd=ROOT)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Production NGHI frontend failed (exit={completed.returncode}):\n{completed.stderr}"
        )

    raw_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(raw_lines) != len(TEST_SENTENCES):
        raise RuntimeError(
            "Production NGHI frontend returned "
            f"{len(raw_lines)} protocol lines; expected {len(TEST_SENTENCES)}. "
            f"stdout={completed.stdout!r}\nstderr={completed.stderr}"
        )

    cases: list[dict[str, Any]] = []
    for index, (original, raw_line) in enumerate(zip(TEST_SENTENCES, raw_lines, strict=True), start=1):
        try:
            response = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Production NGHI frontend returned malformed JSON for case {index}: {raw_line!r}"
            ) from exc
        expected_id = f"audit-{index}"
        if response.get("id") != expected_id:
            raise RuntimeError(
                f"Production NGHI frontend response ID mismatch for case {index}: "
                f"expected {expected_id!r}, got {response.get('id')!r}"
            )
        if not response.get("ok"):
            raise RuntimeError(
                f"Production NGHI frontend failed case {index}: {response.get('error') or 'unknown error'}"
            )
        cases.append(
            {
                "original": original,
                "processed_text": response.get("processed_text"),
                "chunks": response.get("chunks"),
            }
        )

    return validate_nghi_payload(
        {"metadata": {"nghi_commit": NGHI_COMMIT}, "cases": cases}
    )


def _first_id_difference(expected: list[int], actual: list[int]) -> tuple[int, Any, Any] | None:
    common = min(len(expected), len(actual))
    for index in range(common):
        if expected[index] != actual[index]:
            return index, expected[index], actual[index]
    if len(expected) != len(actual):
        index = common
        return (
            index,
            expected[index] if index < len(expected) else "<end>",
            actual[index] if index < len(actual) else "<end>",
        )
    return None


def compare_frontend_parity(
    oracle_payload: dict[str, Any], production_payload: dict[str, Any]
) -> dict[str, Any]:
    """Require production frontend output to equal the pinned NGHI oracle exactly."""
    oracle = validate_nghi_payload(oracle_payload)
    production = validate_nghi_payload(production_payload)

    oracle_case2 = oracle["cases"][1]["chunks"]
    production_case2 = production["cases"][1]["chunks"]
    if len(oracle_case2) != 2 or len(production_case2) != 2:
        raise ValueError(
            "Case 2 must produce exactly two chunks in both oracle and production; "
            f"got oracle={len(oracle_case2)}, production={len(production_case2)}"
        )

    output_cases = []
    for case_index, (oracle_case, production_case) in enumerate(
        zip(oracle["cases"], production["cases"], strict=True), start=1
    ):
        if oracle_case["processed_text"] != production_case["processed_text"]:
            raise ValueError(
                f"Case {case_index} processed_text mismatch: "
                f"oracle={oracle_case['processed_text']!r}, "
                f"production={production_case['processed_text']!r}"
            )
        oracle_chunks = oracle_case["chunks"]
        production_chunks = production_case["chunks"]
        if len(oracle_chunks) != len(production_chunks):
            raise ValueError(
                f"Case {case_index} chunk count mismatch: "
                f"oracle={len(oracle_chunks)}, production={len(production_chunks)}"
            )
        for chunk_index, (oracle_chunk, production_chunk) in enumerate(
            zip(oracle_chunks, production_chunks, strict=True), start=1
        ):
            if oracle_chunk["text"] != production_chunk["text"]:
                raise ValueError(
                    f"Case {case_index} chunk {chunk_index} text mismatch: "
                    f"oracle={oracle_chunk['text']!r}, production={production_chunk['text']!r}"
                )
            difference = _first_id_difference(
                oracle_chunk["phoneme_ids"], production_chunk["phoneme_ids"]
            )
            if difference is not None:
                id_index, expected, actual = difference
                raise ValueError(
                    f"Case {case_index} chunk {chunk_index} phoneme id mismatch at index {id_index}: "
                    f"oracle={expected}, production={actual}"
                )
        output_cases.append(
            {
                "original": oracle_case["original"],
                "oracle": oracle_case,
                "production": production_case,
                "match": True,
            }
        )

    return {"all_match": True, "cases": output_cases}


def _format_ids(values: list[int]) -> str:
    return " ".join(str(value) for value in values)


def render_markdown(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata", {})
    lines = [
        "# TTS Frontend Parity Audit",
        "",
        f"- NGHI-TTS commit: `{metadata.get('nghi_commit', '')}`",
        f"- Voice revision: `{metadata.get('voice_revision', '')}`",
        f"- Generated UTC: `{metadata.get('generated_utc', '')}`",
        "- Parity: PASS" if payload.get("all_match") else "- Parity: FAIL",
        "",
        "This report compares the pinned NGHI upstream oracle with the exact "
        "production linguistic sidecar immediately before ONNX inference.",
        "",
    ]
    for index, case in enumerate(payload.get("cases", []), start=1):
        lines.extend([f"## Case {index}", "", f"**Original:** {case.get('original', '')}", ""])
        for heading, key in (("NGHI oracle", "oracle"), ("Production frontend", "production")):
            item = case.get(key, {})
            lines.extend([f"### {heading}", "", f"Processed text: `{item.get('processed_text', '')}`", ""])
            for chunk_index, chunk in enumerate(item.get("chunks", []), start=1):
                lines.extend(
                    [
                        f"Chunk {chunk_index}: `{chunk.get('text', '')}`",
                        "",
                        f"IDs: `{_format_ids(chunk.get('phoneme_ids', []))}`",
                        "",
                    ]
                )
        lines.extend(["Parity: PASS", ""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify production NGHI frontend parity")
    parser.add_argument("--nghi-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tts_audit_output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    required = [
        args.nghi_root,
        args.config,
        ROOT / "tools" / "nghi_phoneme_audit.mjs",
        ROOT / "tts" / "nghi_frontend.mjs",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing audit prerequisite(s):\n- " + "\n- ".join(missing))

    oracle = run_nghi_oracle(args.node, args.nghi_root, args.config)
    production = run_production_frontend(args.node, args.nghi_root, args.config)
    payload = compare_frontend_parity(oracle, production)
    payload["metadata"] = {
        "nghi_commit": NGHI_COMMIT,
        "voice_revision": VOICE_REVISION,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "tts_phoneme_audit.json"
    markdown_path = args.output_dir / "tts_phoneme_audit.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
