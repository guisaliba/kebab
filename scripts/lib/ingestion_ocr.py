"""OCR adapter: raster images and scanned PDFs -> extracted/*.txt via tesseract (local)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from scripts.lib.ingestion_manifest import classify_original, list_original_rel_paths, resolve_under_source
from scripts.lib.ingestion_pdf import extract_pdf_text_to_file, pdf_text_is_effectively_empty
from scripts.lib.tool_detection import pdftoppm_available, tesseract_available


class OcrIngestError(RuntimeError):
    pass


def _tesseract_bin() -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise OcrIngestError("tesseract not found on PATH (required for OCR ingestion)")
    return exe


def _run_tesseract_on_image(image_path: Path, out_txt: Path, lang: str) -> None:
    st = tesseract_available()
    if not st["available"]:
        raise OcrIngestError(f"tesseract not usable: {st['detail']}")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_base = out_txt.with_suffix("")  # tesseract adds .txt
    proc = subprocess.run(
        [_tesseract_bin(), str(image_path), str(out_base), "-l", lang],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr or proc.stdout or "tesseract failed"
        raise OcrIngestError(err.strip()[:2000])
    produced = Path(str(out_base) + ".txt")
    if not produced.exists():
        raise OcrIngestError("tesseract did not produce output .txt")
    if produced.resolve() != out_txt.resolve():
        text = produced.read_text(encoding="utf-8", errors="replace")
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        out_txt.write_text(text, encoding="utf-8")
        produced.unlink(missing_ok=True)


def ocr_image_to_extracted_txt(
    source_dir: Path,
    image_path: Path,
    *,
    lang: str = "por+eng",
) -> Path:
    out_txt = source_dir / "extracted" / f"{image_path.stem}.txt"
    _run_tesseract_on_image(image_path, out_txt, lang)
    return out_txt


def _ocr_pdf_via_pdftoppm(source_dir: Path, pdf_path: Path, lang: str) -> Path:
    """First page only -> PNG -> tesseract (optional pdftoppm)."""
    ppm = pdftoppm_available()
    if not ppm["available"]:
        raise OcrIngestError(
            "pdftoppm not available: install poppler-utils for scanned-PDF OCR, "
            "or provide image originals under files.originals"
        )

    out_txt = source_dir / "extracted" / f"{pdf_path.stem}.txt"
    with tempfile.TemporaryDirectory(prefix="kebab-ocr-") as tmp:
        tmp_path = Path(tmp)
        prefix = tmp_path / "page"
        proc = subprocess.run(
            [ppm["detail"], "-f", "1", "-l", "1", "-png", str(pdf_path), str(prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr or proc.stdout or "pdftoppm failed"
            raise OcrIngestError(err.strip()[:2000])
        candidates = sorted(tmp_path.glob("*.png"))
        if not candidates:
            raise OcrIngestError("pdftoppm produced no PNG pages")
        _run_tesseract_on_image(candidates[0], out_txt, lang)
    return out_txt


def prepare_ocr_extracted_text(source_dir: Path, manifest: dict[str, Any]) -> tuple[Path, str]:
    """
    Pick first image or PDF under originals; write extracted/*.txt.

    - Image originals: always OCR to extracted/<stem>.txt
    - PDF + ingestion.use_ocr true: OCR first page via pdftoppm + tesseract (skip digital extract)
    - PDF + use_ocr false: not used by router (digital PDF path handles this)
    """
    ing = manifest.get("ingestion") if isinstance(manifest.get("ingestion"), dict) else {}
    lang = ing.get("tesseract_lang") or "por+eng"

    for rel in list_original_rel_paths(manifest):
        abs_path = resolve_under_source(source_dir, rel)
        if not abs_path.exists():
            continue
        kind = classify_original(abs_path)
        if kind == "image":
            path = ocr_image_to_extracted_txt(source_dir, abs_path, lang=lang)
            return path, path.read_text(encoding="utf-8", errors="replace")
        if kind == "pdf":
            path = _ocr_pdf_via_pdftoppm(source_dir, abs_path, lang=lang)
            return path, path.read_text(encoding="utf-8", errors="replace")

    raise OcrIngestError("no image or PDF original found for OCR")


def _ocr_pdf_for_first_original(
    source_dir: Path,
    manifest: dict[str, Any],
    *,
    try_digital_first: bool,
) -> tuple[Path, str]:
    """Shared helper: locate first PDF original and produce OCR output.

    If *try_digital_first* is True, attempts digital text extraction first and
    returns it when non-empty; otherwise goes straight to pdftoppm + tesseract.
    """
    ing = manifest.get("ingestion") if isinstance(manifest.get("ingestion"), dict) else {}
    lang = ing.get("tesseract_lang") or "por+eng"

    for rel in list_original_rel_paths(manifest):
        abs_path = resolve_under_source(source_dir, rel)
        if not abs_path.exists():
            continue
        if classify_original(abs_path) != "pdf":
            continue
        if try_digital_first:
            out_txt, text = extract_pdf_text_to_file(source_dir, manifest, output_txt=None)
            if not pdf_text_is_effectively_empty(text):
                return out_txt, text
        path = _ocr_pdf_via_pdftoppm(source_dir, abs_path, lang=lang)
        return path, path.read_text(encoding="utf-8", errors="replace")

    raise OcrIngestError("no PDF original found")


def try_digital_pdf_then_ocr_if_empty(source_dir: Path, manifest: dict[str, Any]) -> tuple[Path, str]:
    """
    Prefer digital text extraction; if empty, run OCR PDF path.

    Used when PDF is present but text layer may be missing.
    """
    return _ocr_pdf_for_first_original(source_dir, manifest, try_digital_first=True)


def ocr_pdf_fallback(source_dir: Path, manifest: dict[str, Any]) -> tuple[Path, str]:
    """
    Run OCR on the first PDF original without attempting digital text extraction first.

    Used when the caller has already determined the digital text layer is empty.
    """
    return _ocr_pdf_for_first_original(source_dir, manifest, try_digital_first=False)
