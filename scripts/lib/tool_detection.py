"""Lightweight detection of local prerequisites for ingestion adapters."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TypedDict


class ToolStatus(TypedDict):
    name: str
    available: bool
    detail: str


def which_or_empty(name: str) -> str:
    path = shutil.which(name)
    return path or ""


def ffmpeg_available() -> ToolStatus:
    exe = which_or_empty("ffmpeg")
    if not exe:
        return {"name": "ffmpeg", "available": False, "detail": "not found on PATH"}
    try:
        proc = subprocess.run(
            [exe, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return {"name": "ffmpeg", "available": False, "detail": f"exit {proc.returncode}"}
        first = (proc.stdout or "").splitlines()[0] if proc.stdout else "ffmpeg"
        return {"name": "ffmpeg", "available": True, "detail": first.strip()[:120]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": "ffmpeg", "available": False, "detail": str(exc)}


def tesseract_available() -> ToolStatus:
    exe = which_or_empty("tesseract")
    if not exe:
        return {"name": "tesseract", "available": False, "detail": "not found on PATH"}
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return {"name": "tesseract", "available": False, "detail": f"exit {proc.returncode}"}
        first = (proc.stdout or proc.stderr or "").splitlines()[0] if (proc.stdout or proc.stderr) else "tesseract"
        return {"name": "tesseract", "available": True, "detail": first.strip()[:120]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": "tesseract", "available": False, "detail": str(exc)}


def pdftoppm_available() -> ToolStatus:
    """Optional helper for rasterizing PDF pages (OCR path)."""
    exe = which_or_empty("pdftoppm")
    if not exe:
        return {"name": "pdftoppm", "available": False, "detail": "not found on PATH (optional)"}
    return {"name": "pdftoppm", "available": True, "detail": exe}


def summarize_prerequisites_for_manifest(*, need_ffmpeg: bool, need_tesseract: bool) -> list[str]:
    lines: list[str] = []
    if need_ffmpeg:
        st = ffmpeg_available()
        lines.append(f"ffmpeg: {'ok' if st['available'] else 'MISSING — ' + st['detail']}")
    if need_tesseract:
        st = tesseract_available()
        lines.append(f"tesseract: {'ok' if st['available'] else 'MISSING — ' + st['detail']}")
    return lines
