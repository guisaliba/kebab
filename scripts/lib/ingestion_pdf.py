"""Digital PDF text extraction into extracted/*.txt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from scripts.lib.ingestion_manifest import classify_original, list_original_rel_paths, resolve_under_source


class PdfIngestError(RuntimeError):
    pass


def pick_pdf_original(source_dir: Path, manifest: dict[str, Any]) -> Path:
    for rel in list_original_rel_paths(manifest):
        abs_path = resolve_under_source(source_dir, rel)
        if not abs_path.exists():
            continue
        if classify_original(abs_path) == "pdf":
            return abs_path
    raise PdfIngestError("no PDF file found under files.originals")


def extract_pdf_text_to_file(
    source_dir: Path,
    manifest: dict[str, Any],
    *,
    output_txt: Path | None = None,
) -> tuple[Path, str]:
    """Extract text from a digital PDF into extracted/*.txt. Returns (path, text)."""
    pdf_path = pick_pdf_original(source_dir, manifest)
    out_txt = output_txt or (source_dir / "extracted" / f"{pdf_path.stem}.txt")

    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text()
        if t and t.strip():
            parts.append(t.strip())
    text = "\n\n".join(parts)

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(text + ("\n" if text else ""), encoding="utf-8")
    return out_txt, text


def pdf_text_is_effectively_empty(text: str) -> bool:
    return not text or not text.strip()
