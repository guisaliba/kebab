"""Pluggable ingestion adapters: route media/doc sources to normalized text under raw/sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.lib.ingestion_audio import AudioIngestError, extract_audio_wav
from scripts.lib.ingestion_manifest import (
    classify_original,
    has_chunk_input_files,
    ingestion_section,
    list_original_rel_paths,
    resolve_under_source,
)
from scripts.lib.ingestion_ocr import OcrIngestError, ocr_pdf_fallback, prepare_ocr_extracted_text, try_digital_pdf_then_ocr_if_empty
from scripts.lib.ingestion_pdf import PdfIngestError, extract_pdf_text_to_file, pdf_text_is_effectively_empty
from scripts.lib.ingestion_transcription import describe_transcription_seam


class IngestionError(RuntimeError):
    """Raised when adapters cannot produce normalized inputs for chunking."""


@dataclass
class PreparedIngestArtifacts:
    """Result of adapter preparation before chunking."""

    source_kind: str
    text_paths: list[Path]
    derived_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    adapter_name: str = "unknown"


def _sorted_transcripts(source_dir: Path) -> list[Path]:
    return sorted((source_dir / "transcript").glob("*.md"))


def _sorted_extracted_txt(source_dir: Path) -> list[Path]:
    return sorted((source_dir / "extracted").glob("*.txt"))


def prepare_text_passthrough(source_dir: Path) -> PreparedIngestArtifacts:
    """Use existing transcript/*.md or extracted/*.txt (baseline compatibility)."""
    transcript = _sorted_transcripts(source_dir)
    if transcript:
        return PreparedIngestArtifacts(
            source_kind="transcript",
            text_paths=transcript,
            notes=["Existing transcript/*.md used for chunking (highest precedence)."],
            adapter_name="text_passthrough",
        )
    extracted = _sorted_extracted_txt(source_dir)
    if extracted:
        return PreparedIngestArtifacts(
            source_kind="extracted",
            text_paths=extracted,
            notes=["Existing extracted/*.txt used for chunking."],
            adapter_name="text_passthrough",
        )
    raise IngestionError(
        f"{source_dir}: no transcript/*.md or extracted/*.txt for chunking after adapter preparation."
    )


def infer_adapter_name(source_dir: Path, manifest: dict[str, Any]) -> str:
    """Infer adapter id from originals when ingestion.adapter is auto."""
    for rel in list_original_rel_paths(manifest):
        abs_path = resolve_under_source(source_dir, rel)
        if not abs_path.exists():
            continue
        kind = classify_original(abs_path)
        if kind in {"video", "audio"}:
            return "audio"
        if kind == "pdf":
            return "pdf"
        if kind == "image":
            return "ocr"
    raise IngestionError(
        "Cannot infer ingestion adapter: no existing originals matched known types. "
        "Add files under files.originals or provide transcript/*.md / extracted/*.txt."
    )


def prepare_ingest(
    source_dir: Path,
    manifest: dict[str, Any],
    *,
    skip_adapters: bool = False,
    check_tools: bool = True,
) -> PreparedIngestArtifacts:
    """
    Run adapter preparation so chunking can use transcript/extracted precedence.

    If normalized text already exists, uses text passthrough without invoking ffmpeg/OCR.
    """
    source_dir = source_dir.resolve()

    if not skip_adapters and has_chunk_input_files(source_dir):
        return prepare_text_passthrough(source_dir)

    if skip_adapters:
        return prepare_text_passthrough(source_dir)

    ing = ingestion_section(manifest)
    raw_adapter = ing.get("adapter")
    adapter = (raw_adapter or "auto").strip().lower()
    if adapter in {"", "auto"}:
        adapter = infer_adapter_name(source_dir, manifest)

    if adapter == "text":
        return prepare_text_passthrough(source_dir)

    if adapter == "audio":
        try:
            wav = extract_audio_wav(source_dir, manifest, check_tools=check_tools)
        except AudioIngestError as exc:
            raise IngestionError(str(exc)) from exc
        return PreparedIngestArtifacts(
            source_kind="audio-wav",
            text_paths=[],
            derived_files=[wav],
            notes=[
                f"ffmpeg extracted WAV: {wav.relative_to(source_dir)}",
                describe_transcription_seam(),
            ],
            adapter_name="audio",
        )

    if adapter == "pdf":
        use_ocr = bool(ing.get("use_ocr"))
        if use_ocr:
            try:
                path, _text = prepare_ocr_extracted_text(source_dir, manifest)
            except OcrIngestError as exc:
                raise IngestionError(str(exc)) from exc
            return PreparedIngestArtifacts(
                source_kind="extracted",
                text_paths=[path],
                notes=["PDF ingested via OCR (ingestion.use_ocr: true)."],
                adapter_name="ocr",
            )
        try:
            out_txt, text = extract_pdf_text_to_file(source_dir, manifest)
        except PdfIngestError as exc:
            raise IngestionError(str(exc)) from exc
        if not pdf_text_is_effectively_empty(text):
            return PreparedIngestArtifacts(
                source_kind="extracted",
                text_paths=[out_txt],
                notes=["Digital PDF text extracted to extracted/*.txt."],
                adapter_name="pdf",
            )
        try:
            path, _text2 = ocr_pdf_fallback(source_dir, manifest)
        except OcrIngestError as exc:
            raise IngestionError(
                "PDF had no extractable text layer and OCR fallback failed. "
                "Install tesseract (+ poppler pdftoppm for scanned PDFs) or add transcript/*.md. "
                f"Detail: {exc}"
            ) from exc
        return PreparedIngestArtifacts(
            source_kind="extracted",
            text_paths=[path],
            notes=[
                "Digital PDF text was empty; OCR fallback produced extracted/*.txt.",
            ],
            adapter_name="ocr",
        )

    if adapter == "ocr":
        try:
            path, _text = prepare_ocr_extracted_text(source_dir, manifest)
        except OcrIngestError as exc:
            raise IngestionError(str(exc)) from exc
        return PreparedIngestArtifacts(
            source_kind="extracted",
            text_paths=[path],
            notes=["Image/PDF ingested via OCR adapter."],
            adapter_name="ocr",
        )

    raise IngestionError(f"unsupported ingestion.adapter: {adapter!r}")
