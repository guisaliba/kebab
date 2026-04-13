"""Tests for Phase 5 ingestion adapters and manifest validation."""

from __future__ import annotations

import runpy
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.lib.ingestion_adapters import infer_adapter_name, prepare_ingest, prepare_text_passthrough
from scripts.lib.paths import ROOT
from scripts.lib.validation import validate_manifest_source


def test_validate_manifest_ingestion_adapter_ok() -> None:
    errs = validate_manifest_source(
        {
            "source_id": "SRC-2099-9001",
            "ingestion": {"adapter": "auto", "use_ocr": False},
        },
        Path("manifest.yaml"),
    )
    assert errs == []


def test_validate_manifest_rejects_bad_adapter() -> None:
    errs = validate_manifest_source(
        {"source_id": "SRC-2099-9001", "ingestion": {"adapter": "magic"}},
        Path("manifest.yaml"),
    )
    assert any("ingestion.adapter" in e for e in errs)


def test_prepare_text_passthrough_prefers_transcript_over_extracted(tmp_path: Path) -> None:
    (tmp_path / "transcript").mkdir()
    (tmp_path / "extracted").mkdir()
    (tmp_path / "transcript" / "a.md").write_text("AAA\n", encoding="utf-8")
    (tmp_path / "extracted" / "b.txt").write_text("BBB\n", encoding="utf-8")
    p = prepare_text_passthrough(tmp_path)
    assert p.adapter_name == "text_passthrough"
    assert p.source_kind == "transcript"


def test_infer_adapter_audio(tmp_path: Path) -> None:
    (tmp_path / "original").mkdir()
    (tmp_path / "original" / "x.mp4").write_bytes(b"")
    manifest = {"files": {"originals": ["original/x.mp4"]}}
    assert infer_adapter_name(tmp_path, manifest) == "audio"


def test_infer_adapter_pdf(tmp_path: Path) -> None:
    (tmp_path / "original").mkdir()
    (tmp_path / "original" / "x.pdf").write_bytes(b"")
    manifest = {"files": {"originals": ["original/x.pdf"]}}
    assert infer_adapter_name(tmp_path, manifest) == "pdf"


def test_infer_adapter_image(tmp_path: Path) -> None:
    (tmp_path / "original").mkdir()
    (tmp_path / "original" / "x.png").write_bytes(b"")
    manifest = {"files": {"originals": ["original/x.png"]}}
    assert infer_adapter_name(tmp_path, manifest) == "ocr"


def test_prepare_ingest_pdf_writes_extracted_txt(tmp_path: Path) -> None:
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf not installed")

    pdf_path = tmp_path / "original" / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_path.write_bytes(b"")  # placeholder; overwrite below
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    manifest = {
        "source_id": "SRC-2099-9002",
        "files": {"originals": ["original/doc.pdf"]},
        "ingestion": {"adapter": "pdf"},
    }
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    def fake_extract(*_a: object, **_k: object) -> tuple[Path, str]:
        out = tmp_path / "extracted" / "doc.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("hello pdf fixture\n", encoding="utf-8")
        return out, "hello pdf fixture"

    with patch("scripts.lib.ingestion_adapters.extract_pdf_text_to_file", new=fake_extract):
        prepared = prepare_ingest(tmp_path, manifest, check_tools=False)
    assert prepared.adapter_name == "pdf"
    assert prepared.text_paths


def test_audio_adapter_without_text_fails_chunking(tmp_path: Path) -> None:
    """ffmpeg extracts WAV; chunking still requires text artifacts."""
    vid = tmp_path / "original" / "a.mp4"
    vid.parent.mkdir(parents=True, exist_ok=True)
    vid.write_bytes(b"not a real mp4")

    manifest = {
        "source_id": "SRC-2099-9003",
        "files": {"originals": ["original/a.mp4"]},
        "ingestion": {"adapter": "audio"},
    }

    with patch("scripts.lib.ingestion_adapters.extract_audio_wav", return_value=tmp_path / "extracted" / "a.wav"):
        prepared = prepare_ingest(tmp_path, manifest, check_tools=False)
    assert prepared.adapter_name == "audio"
    assert prepared.text_paths == []

    from scripts.lib.chunking import load_chunk_input

    with pytest.raises(ValueError, match="no chunk input"):
        load_chunk_input(tmp_path)


def test_ingest_never_writes_wiki_on_pdf_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke: ingest with mocked PDF extraction does not touch wiki/ (in-process so patch applies)."""
    src = ROOT / "raw" / "sources" / "SRC-2099-9004-pdf-proof"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)
    (src / "original").mkdir()
    (src / "original" / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    manifest = {
        "source_id": "SRC-2099-9004",
        "title": "PDF test",
        "type": "book",
        "language": "pt-BR",
        "status": "active",
        "topics": ["test"],
        "files": {"originals": ["original/doc.pdf"]},
        "ingestion": {"adapter": "pdf"},
    }
    (src / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")

    out_txt = src / "extracted" / "doc.txt"

    def fake_extract(*_a: object, **_k: object) -> tuple[Path, str]:
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        out_txt.write_text("chunkable body text for ingest test.\n" * 5, encoding="utf-8")
        return out_txt, out_txt.read_text(encoding="utf-8")

    wiki_before = {p: p.read_text(encoding="utf-8") for p in (ROOT / "wiki").rglob("*.md")}
    review_id = "REV-2099-9004"
    review_dir = ROOT / "staging" / "reviews" / review_id
    if review_dir.exists():
        shutil.rmtree(review_dir)
    try:
        monkeypatch.setattr(
            sys,
            "argv",
            ["ingest-main", "--source-dir", str(src), "--review-id", review_id],
        )
        with (
            patch("scripts.lib.ingestion_adapters.extract_pdf_text_to_file", new=fake_extract),
            patch("scripts.lib.review_package.upsert_registry_entry"),
        ):
            runpy.run_path(str(ROOT / "scripts" / "ingest" / "main.py"), run_name="__main__")
        wiki_after = {p: p.read_text(encoding="utf-8") for p in (ROOT / "wiki").rglob("*.md")}
        assert wiki_before == wiki_after
    finally:
        if src.exists():
            shutil.rmtree(src, ignore_errors=True)
        if review_dir.exists():
            shutil.rmtree(review_dir)
