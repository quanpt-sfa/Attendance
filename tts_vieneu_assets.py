"""Pinned local asset layout for Attendance VieNeu v3 Turbo runtime."""
from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = PROJECT_DIR / "tts" / "runtime" / "vieneu"
MODELS_ROOT = RUNTIME_ROOT / "models"
MODEL_ROOT = MODELS_ROOT / "v3turbo"
ONNX_DIR = MODEL_ROOT / "onnx_update"
CODEC_DIR = MODELS_ROOT / "codec"

MODEL_REPO_ID = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
CODEC_REPO_ID = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
ONNX_SUBFOLDER = "onnx_update"

GRAPH_FILES = (
    "vieneu_prefill.onnx",
    "vieneu_decode_step.onnx",
    "vieneu_acoustic_cached.onnx",
    "vieneu_backbone_shared.data",
    "vieneu_v3_heads.npz",
    "config.json",
    "tokenizer.json",
)

CODEC_FILES = (
    "moss_audio_tokenizer_decode_full.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "moss_audio_tokenizer_decode_step.onnx",
    "codec_browser_onnx_meta.json",
    "moss_audio_tokenizer_encode.onnx",
    "moss_audio_tokenizer_encode.data",
)


def required_asset_paths(
    onnx_dir: Path = ONNX_DIR,
    codec_dir: Path = CODEC_DIR,
) -> tuple[Path, ...]:
    onnx_dir = Path(onnx_dir)
    codec_dir = Path(codec_dir)
    return tuple(onnx_dir / name for name in GRAPH_FILES) + tuple(
        codec_dir / name for name in CODEC_FILES
    )


def assets_ready(onnx_dir: Path = ONNX_DIR, codec_dir: Path = CODEC_DIR) -> bool:
    try:
        return all(path.is_file() and path.stat().st_size > 0 for path in required_asset_paths(onnx_dir, codec_dir))
    except OSError:
        return False
