from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts_vieneu_assets import (
    CODEC_DIR,
    CODEC_FILES,
    CODEC_REPO_ID,
    GRAPH_FILES,
    MODEL_REPO_ID,
    MODEL_ROOT,
    ONNX_SUBFOLDER,
    assets_ready,
)


def _default_download(repo_id: str, filename: str, **kwargs) -> str:
    from huggingface_hub import hf_hub_download

    return hf_hub_download(repo_id=repo_id, filename=filename, **kwargs)


def materialize(
    *,
    model_root: Path = MODEL_ROOT,
    codec_dir: Path = CODEC_DIR,
    download=None,
) -> tuple[Path, Path]:
    """Download VieNeu ONNX graph/data pairs into ordinary local directories.

    Using ``local_dir`` avoids loading ONNX external-data tensors directly from
    Hugging Face's symlink/blob cache layout, which recent ONNX Runtime versions
    correctly reject when the model and its external data canonicalize to
    different blob directories.
    """

    model_root = Path(model_root)
    codec_dir = Path(codec_dir)
    onnx_dir = model_root / ONNX_SUBFOLDER
    model_root.mkdir(parents=True, exist_ok=True)
    codec_dir.mkdir(parents=True, exist_ok=True)
    download = download or _default_download

    for filename in GRAPH_FILES:
        download(
            MODEL_REPO_ID,
            filename,
            repo_type="model",
            subfolder=ONNX_SUBFOLDER,
            local_dir=str(model_root),
        )

    for filename in CODEC_FILES:
        download(
            CODEC_REPO_ID,
            filename,
            repo_type="model",
            local_dir=str(codec_dir),
        )

    if not assets_ready(onnx_dir=onnx_dir, codec_dir=codec_dir):
        raise RuntimeError("VieNeu materialized model/codec assets are incomplete")
    return onnx_dir, codec_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Materialize VieNeu ONNX model and codec assets")
    parser.add_argument("--model-root", default=str(MODEL_ROOT))
    parser.add_argument("--codec-dir", default=str(CODEC_DIR))
    args = parser.parse_args(argv)
    try:
        onnx_dir, codec_dir = materialize(
            model_root=Path(args.model_root),
            codec_dir=Path(args.codec_dir),
        )
    except Exception as exc:
        print(f"Cannot materialize VieNeu assets: {exc}")
        return 1
    print(f"ONNX: {onnx_dir}")
    print(f"Codec: {codec_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
