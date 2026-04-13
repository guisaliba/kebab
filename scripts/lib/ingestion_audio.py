"""ffmpeg-based audio extraction into extracted/ (normalized audio artifacts)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from scripts.lib.ingestion_manifest import (
    classify_original,
    files_section,
    list_original_rel_paths,
    resolve_under_source,
)
from scripts.lib.tool_detection import ffmpeg_available


class AudioIngestError(RuntimeError):
    pass


def _pick_original_for_audio(source_dir: Path, manifest: dict[str, Any]) -> Path:
    for rel in list_original_rel_paths(manifest):
        abs_path = resolve_under_source(source_dir, rel)
        if not abs_path.exists():
            continue
        kind = classify_original(abs_path)
        if kind in {"video", "audio"}:
            return abs_path
    raise AudioIngestError("no video/audio file found under files.originals")


def _pick_output_wav(source_dir: Path, manifest: dict[str, Any], original: Path) -> Path:
    files = files_section(manifest)
    extracted_audio = files.get("extracted_audio")
    if isinstance(extracted_audio, list) and extracted_audio:
        first = extracted_audio[0]
        if isinstance(first, str) and first.strip():
            return resolve_under_source(source_dir, first.strip())
    out_dir = source_dir / "extracted"
    return out_dir / f"{original.stem}.wav"


def extract_audio_wav(source_dir: Path, manifest: dict[str, Any], *, check_tools: bool = True) -> Path:
    """Extract mono 16kHz PCM WAV under extracted/ using ffmpeg."""
    if check_tools:
        st = ffmpeg_available()
        if not st["available"]:
            raise AudioIngestError(f"ffmpeg required for audio ingestion: {st['detail']}")

    original = _pick_original_for_audio(source_dir, manifest)
    out_wav = _pick_output_wav(source_dir, manifest, original)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-i",
            str(original),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(out_wav),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ffmpeg.returncode != 0:
        err = ffmpeg.stderr or ffmpeg.stdout or "ffmpeg failed"
        raise AudioIngestError(err.strip()[:2000])

    return out_wav
