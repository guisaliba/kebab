"""Transcription provider seam (execution deferred unless explicitly wired)."""

from __future__ import annotations

SEAM_NOTE = (
    "Automatic speech-to-text is not executed in this repository phase. "
    "Provide transcript/*.md or extracted/*.txt for chunking, or extend this seam with a local/provider adapter."
)


def describe_transcription_seam() -> str:
    return SEAM_NOTE
