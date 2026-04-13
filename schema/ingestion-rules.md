# Ingestion Rules

- Every source must have a `manifest.yaml`.
- Every source must be registered in `raw/registry.yaml`.
- Raw source content is immutable after ingestion (except metadata append per policy).
- Long transcripts should be chunked into stable file units.
- Every ingest must create a review package in `staging/reviews/`.
- No source may promote directly into `wiki/`.

## Phase 5 — adapters and normalized artifacts

- Ingestion runs **adapters** to produce normalized text under the source directory before chunking.
- Chunking still follows strict precedence: **`transcript/*.md` first**, then **`extracted/*.txt`**.
- Fixed locations for this repository phase:
  - **Extracted audio** (e.g. WAV from ffmpeg): under `extracted/` (paths may be listed in `files.extracted_audio`).
  - **Extracted / OCR text**: under `extracted/` as `*.txt`.
  - **Transcript text**: under `transcript/` as `*.md`.
- Adapters are **pluggable**; remote providers are not required in Phase 5 but should fit the same seams.

### Optional `ingestion` mapping in `manifest.yaml`

- `adapter`: `auto` | `text` | `audio` | `pdf` | `ocr` (default: `auto`).
  - `auto` infers from the first existing file in `files.originals` (video/audio → `audio`, PDF → `pdf`, raster image → `ocr`).
  - `text` requires existing `transcript/*.md` or `extracted/*.txt` (same as legacy behavior).
- `use_ocr` (boolean): when `true` and `adapter` is `pdf`, run the OCR path for PDFs (skips digital text extraction for that ingest).
- `tesseract_lang` (string): optional Tesseract language bundle (default `por+eng`).

### `files` hints

- `files.originals`: list of **relative** paths to inputs (video, audio, PDF, images).
- `files.extracted_audio`: optional explicit paths for ffmpeg output (under `extracted/`).
- Other `files.*` lists remain documentation hints; validators require relative paths under the source tree.

### Local tools

- **ffmpeg**: audio extraction (`adapter: audio`).
- **pypdf** (Python): digital PDF text extraction (`adapter: pdf`).
- **tesseract** (+ **pdftoppm** from poppler for scanned PDFs): OCR path.

Missing tools surface as clear errors at prepare time (imports do not hard-fail on optional binaries).

### Transcription

- Automatic speech-to-text is **not** executed in this phase; the seam is documented in `scripts/lib/ingestion_transcription.py`.
- For video/audio sources, provide `transcript/*.md` or `extracted/*.txt` for chunking after audio extraction, or extend the transcription seam later.

### Reset before real ingestion

- See `docs/reset-before-real-ingestion.md` for a safe manual sequence to archive or remove toy `staging/` / `wiki/` state before production-like ingests.
