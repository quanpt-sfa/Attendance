"""Compare NGHI-TTS and Attendance/Piper text-to-phoneme inputs.

This is a development-only diagnostic. It does not participate in production
synthesis and deliberately does not add or alter audio pauses.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts_worker import prepare_spoken_name  # noqa: E402

NGHI_COMMIT = "46d160da32041f7e176607203b958069265df7da"
TEST_SENTENCES = [
    "Huỳnh Quốc Phước đã điểm danh thành công.",
    "Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.",
    "Huỳnh Quốc Phước, bạn đã điểm danh thành công.",
    "Bạn đã điểm danh thành công!",
    "Bạn đã điểm danh thành công?",
]
PUNCTUATION = (".", ",", "!", "?", ":", ";")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PHONEME_RE = re.compile(r"Phonemes for sentence:\s*(.*)$", re.IGNORECASE)
IDS_RE = re.compile(
    r"Converted\s+\d+\s+phoneme\(s\)\s+to\s+\d+\s+phoneme id\(s\):\s*(.*)$",
    re.IGNORECASE,
)


def _first_id(config: dict[str, Any], symbol: str) -> int | None:
    values = config.get("phoneme_id_map", {}).get(symbol) or []
    return int(values[0]) if values else None


def parse_piper_debug(stderr: str) -> list[dict[str, Any]]:
    """Parse legacy native Piper --debug phoneme/ID diagnostics.

    The pinned Windows runtime logs one ``Phonemes for sentence`` line followed
    by ``Converted ... phoneme id(s)`` before each ONNX inference call.
    """
    clean = ANSI_RE.sub("", stderr or "")
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in clean.splitlines():
        line = raw_line.strip()
        match = PHONEME_RE.search(line)
        if match:
            current = {"phoneme_string": match.group(1).strip(), "phoneme_ids": []}
            records.append(current)
            continue

        match = IDS_RE.search(line)
        if not match:
            continue
        ids = [int(value) for value in re.findall(r"-?\d+", match.group(1))]
        if current is None or current.get("phoneme_ids"):
            current = {"phoneme_string": "", "phoneme_ids": ids}
            records.append(current)
        else:
            current["phoneme_ids"] = ids

    return records


def analyze_punctuation(
    phoneme_string: str, phoneme_ids: list[int], voice_config: dict[str, Any]
) -> dict[str, Any]:
    """Locate punctuation characters and their configured IDs in one inference input."""
    result: dict[str, Any] = {}
    for symbol in PUNCTUATION:
        phoneme_id = _first_id(voice_config, symbol)
        result[symbol] = {
            "phoneme_positions": [
                index for index, character in enumerate(phoneme_string) if character == symbol
            ],
            "id": phoneme_id,
            "id_positions": (
                [index for index, value in enumerate(phoneme_ids) if value == phoneme_id]
                if phoneme_id is not None
                else []
            ),
        }

    id_map = voice_config.get("phoneme_id_map", {})
    result["special_ids"] = {
        "BOS": list(id_map.get("^", [])),
        "PAD": list(id_map.get("_", [])),
        "EOS": list(id_map.get("$", [])),
    }
    return result


def validate_nghi_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("NGHI audit output must be a JSON object")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("NGHI audit output is missing cases")
    if len(cases) != len(TEST_SENTENCES):
        raise ValueError(
            f"NGHI audit returned {len(cases)} cases; expected {len(TEST_SENTENCES)}"
        )
    return payload


def _load_voice_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_command(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **kwargs,
    )


def run_piper_case(
    piper_exe: Path,
    model_path: Path,
    config_path: Path,
    original_text: str,
    voice_config: dict[str, Any],
) -> dict[str, Any]:
    spoken_text = prepare_spoken_name(original_text)
    with tempfile.TemporaryDirectory(prefix="attendance-piper-audit-") as temp_dir:
        output_path = Path(temp_dir) / "audit.wav"
        command = [
            str(piper_exe),
            "--model",
            str(model_path),
            "--config",
            str(config_path),
            "--output_file",
            str(output_path),
            "--debug",
        ]
        completed = _run_command(
            command,
            input=spoken_text + "\n",
            cwd=str(piper_exe.parent),
        )

    if completed.returncode != 0:
        raise RuntimeError(
            "Native Piper audit failed for "
            f"{original_text!r} (exit={completed.returncode}):\n{completed.stderr}"
        )

    sentences = parse_piper_debug(completed.stderr)
    if not sentences or any(not item.get("phoneme_ids") for item in sentences):
        raise RuntimeError(
            "Could not parse phoneme string/IDs from native Piper --debug output. "
            "Raw stderr follows:\n" + completed.stderr
        )

    for sentence in sentences:
        sentence["punctuation"] = analyze_punctuation(
            sentence.get("phoneme_string", ""), sentence.get("phoneme_ids", []), voice_config
        )

    return {
        "input_text": spoken_text,
        "sentences": sentences,
    }


def run_nghi_audit(
    node_exe: str,
    harness_path: Path,
    nghi_root: Path,
    voice_config_path: Path,
) -> dict[str, Any]:
    request = json.dumps({"sentences": TEST_SENTENCES}, ensure_ascii=False)
    command = [
        node_exe,
        str(harness_path),
        "--nghi-root",
        str(nghi_root),
        "--voice-config",
        str(voice_config_path),
        "--expected-commit",
        NGHI_COMMIT,
    ]
    completed = _run_command(command, input=request, cwd=str(ROOT))
    if completed.returncode != 0:
        raise RuntimeError(
            "NGHI-TTS audit harness failed "
            f"(exit={completed.returncode}):\n{completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "NGHI-TTS audit harness did not return valid JSON. "
            f"stdout={completed.stdout!r}\nstderr={completed.stderr}"
        ) from exc
    return validate_nghi_payload(payload)


def _format_ids(values: list[int]) -> str:
    return " ".join(str(value) for value in values)


def _format_punctuation(punctuation: dict[str, Any]) -> str:
    parts = []
    for symbol in PUNCTUATION:
        item = punctuation.get(symbol, {})
        if item.get("phoneme_positions") or item.get("id_positions"):
            parts.append(
                f"`{symbol}`→id {item.get('id')}; "
                f"phoneme-pos={item.get('phoneme_positions', [])}; "
                f"id-pos={item.get('id_positions', [])}"
            )
    return "; ".join(parts) if parts else "none"


def render_markdown(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata", {})
    lines = [
        "# TTS Phoneme Audit",
        "",
        f"- NGHI-TTS commit: `{metadata.get('nghi_commit', '')}`",
        f"- Piper runtime: `{metadata.get('piper_runtime', '')}`",
        f"- Voice: `{metadata.get('voice', '')}`",
        f"- Voice revision: `{metadata.get('voice_revision', '')}`",
        f"- Generated UTC: `{metadata.get('generated_utc', '')}`",
        "",
        "This report compares linguistic inputs immediately before ONNX inference. "
        "It does not add post-synthesis silence.",
        "",
    ]

    for index, case in enumerate(payload.get("cases", []), start=1):
        lines.extend(
            [
                f"## Case {index}",
                "",
                f"**Original:** {case.get('original', '')}",
                "",
                f"**Attendance spoken text:** {case.get('attendance_spoken_text', '')}",
                "",
                "### NGHI-TTS",
                "",
                f"Processed text: `{case.get('nghi', {}).get('processed_text', '')}`",
                "",
            ]
        )
        for chunk_index, chunk in enumerate(case.get("nghi", {}).get("chunks", []), start=1):
            lines.extend(
                [
                    f"Chunk {chunk_index}: `{chunk.get('text', '')}`",
                    "",
                    f"Phonemes: `{chunk.get('phoneme_string', '')}`",
                    "",
                    f"IDs: `{_format_ids(chunk.get('phoneme_ids', []))}`",
                    "",
                    f"Punctuation: {_format_punctuation(chunk.get('punctuation', {}))}",
                    "",
                ]
            )

        lines.extend(["### Attendance / Piper", ""])
        for sentence_index, sentence in enumerate(
            case.get("piper", {}).get("sentences", []), start=1
        ):
            lines.extend(
                [
                    f"Sentence {sentence_index} phonemes: `{sentence.get('phoneme_string', '')}`",
                    "",
                    f"IDs: `{_format_ids(sentence.get('phoneme_ids', []))}`",
                    "",
                    f"Punctuation: {_format_punctuation(sentence.get('punctuation', {}))}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def build_audit(
    nghi_payload: dict[str, Any],
    piper_exe: Path,
    model_path: Path,
    config_path: Path,
    voice_config: dict[str, Any],
) -> dict[str, Any]:
    cases = []
    for original, nghi_case in zip(TEST_SENTENCES, nghi_payload["cases"], strict=True):
        if nghi_case.get("original") != original:
            raise ValueError(
                "NGHI case order/text mismatch: "
                f"expected {original!r}, got {nghi_case.get('original')!r}"
            )

        for chunk in nghi_case.get("chunks", []):
            chunk["punctuation"] = analyze_punctuation(
                chunk.get("phoneme_string", ""), chunk.get("phoneme_ids", []), voice_config
            )

        piper_case = run_piper_case(
            piper_exe, model_path, config_path, original, voice_config
        )
        cases.append(
            {
                "original": original,
                "attendance_spoken_text": prepare_spoken_name(original),
                "nghi": nghi_case,
                "piper": piper_case,
            }
        )

    return {
        "metadata": {
            "nghi_commit": NGHI_COMMIT,
            "piper_runtime": str(piper_exe),
            "voice": voice_config.get("dataset") or voice_config.get("name") or "calmwoman3688",
            "voice_revision": "sannht/vi_voice@62e57b18157ed213b3863a7a8a35b14d3404554b",
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "punctuation_ids": {
                symbol: _first_id(voice_config, symbol) for symbol in PUNCTUATION
            },
            "special_ids": {
                "BOS": voice_config.get("phoneme_id_map", {}).get("^", []),
                "PAD": voice_config.get("phoneme_id_map", {}).get("_", []),
                "EOS": voice_config.get("phoneme_id_map", {}).get("$", []),
            },
        },
        "cases": cases,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit NGHI-TTS vs Attendance/Piper phonemes")
    parser.add_argument("--nghi-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tts_audit_output")
    parser.add_argument("--node", default="node")
    parser.add_argument(
        "--piper-exe", type=Path, default=ROOT / "tts" / "runtime" / "piper" / "piper.exe"
    )
    parser.add_argument(
        "--model", type=Path, default=ROOT / "tts" / "voices" / "calmwoman3688.onnx"
    )
    parser.add_argument(
        "--config", type=Path, default=ROOT / "tts" / "voices" / "calmwoman3688.onnx.json"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    harness_path = ROOT / "tools" / "nghi_phoneme_audit.mjs"
    required = [args.piper_exe, args.model, args.config, harness_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing audit prerequisite(s):\n- " + "\n- ".join(missing))

    voice_config = _load_voice_config(args.config)
    nghi_payload = run_nghi_audit(args.node, harness_path, args.nghi_root, args.config)
    payload = build_audit(
        nghi_payload,
        args.piper_exe,
        args.model,
        args.config,
        voice_config,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "tts_phoneme_audit.json"
    markdown_path = args.output_dir / "tts_phoneme_audit.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
