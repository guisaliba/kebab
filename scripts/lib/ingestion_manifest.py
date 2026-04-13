"""Helpers for reading source manifest `files` and `ingestion` sections."""

from __future__ import annotations

from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
PDF_EXTENSION = ".pdf"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def ingestion_section(manifest: dict[str, Any]) -> dict[str, Any]:
    raw = manifest.get("ingestion")
    return raw if isinstance(raw, dict) else {}


def files_section(manifest: dict[str, Any]) -> dict[str, Any]:
    raw = manifest.get("files")
    return raw if isinstance(raw, dict) else {}


def list_original_rel_paths(manifest: dict[str, Any]) -> list[str]:
    files = files_section(manifest)
    originals = files.get("originals")
    if not isinstance(originals, list):
        return []
    out: list[str] = []
    for item in originals:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def resolve_under_source(source_dir: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute():
        msg = f"path must be relative to source dir: {rel}"
        raise ValueError(msg)
    if ".." in rel_path.parts:
        msg = f"path must not contain parent directory traversal: {rel}"
        raise ValueError(msg)
    resolved_source_dir = source_dir.resolve()
    resolved_path = (resolved_source_dir / rel_path).resolve()
    if not resolved_path.is_relative_to(resolved_source_dir):
        msg = f"path escapes source dir: {rel}"
        raise ValueError(msg)
    return resolved_path


def classify_original(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext == PDF_EXTENSION:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return None


def has_chunk_input_files(source_dir: Path) -> bool:
    """True if transcript/*.md or extracted/*.txt already exists."""
    transcript = sorted((source_dir / "transcript").glob("*.md"))
    if transcript:
        return True
    extracted = sorted((source_dir / "extracted").glob("*.txt"))
    return bool(extracted)
