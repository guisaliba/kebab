# Ingestion adapter operational smoke — 2026-04-13

Operational checkpoint only (Phase 5 follow-up). No code or adapter changes.

**Integrity:** OCR is **not** validated on this machine unless `tesseract` is installed **and** a real OCR smoke succeeds. This run: **OCR = SKIPPED** (tesseract absent).

---

## Environment

| Field | Value |
|-------|--------|
| Date | 2026-04-13 |
| Host | Linux 6.19.11-arch1-1 (x86_64) |
| Repo | `/home/projects/active/aurea/kb-wiki` |
| Python venv | `.venv` |

---

## Preflight (binaries and Python)

Commands:

```bash
command -v ffmpeg; ffmpeg -version | head -1
command -v tesseract || echo "MISSING"
command -v pdftoppm; pdftoppm -v 2>&1 | head -1
.venv/bin/python -c "import pypdf; print('pypdf', pypdf.__version__)"
```

**Result:**

| Tool | Status |
|------|--------|
| ffmpeg | Present (`/usr/bin/ffmpeg`) |
| tesseract | **MISSING** (not on PATH) |
| pdftoppm | Present (`/usr/bin/pdftoppm`) |
| pypdf | 6.10.0 (venv) |

---

## Install attempt (system packages)

**Proposed:** `sudo pacman -S --needed tesseract tesseract-data-eng tesseract-data-por`

**Attempted:** `sudo pacman -S --needed --noconfirm tesseract tesseract-data-eng tesseract-data-por`

**Result:** **Blocked** — `sudo` requires a TTY/password in this environment (`sudo: a terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper`).

**No system packages were installed** during this checkpoint.

**Optional (manual):** Run the `pacman` command above locally, then re-run OCR smoke and update this section.

---

## Fixture generation (not part of adapter binaries)

To obtain a **digital PDF with a real text layer** for `pypdf` extraction, **fpdf2** was installed in the project venv and used once to generate `/tmp/smoke-digital.pdf`, then copied to the throwaway source.

```bash
.venv/bin/pip install fpdf2
.venv/bin/python -c "from fpdf import FPDF; p=FPDF(); p.add_page(); p.set_font('Helvetica', size=24); p.cell(0,40,'Smoke test digital PDF text layer.'); p.output('/tmp/smoke-digital.pdf')"
```

**Note:** fpdf2 is only for test input; **ingestion** still uses **pypdf** in [`scripts/lib/ingestion_pdf.py`](../../scripts/lib/ingestion_pdf.py).

---

## Tool versions after install

**System:** unchanged (no sudo install).

| Component | Version / detail |
|-----------|-------------------|
| ffmpeg | `ffmpeg version n8.1 Copyright (c) 2000-2026 the FFmpeg developers` |
| pdftoppm | `pdftoppm version 26.03.0` |
| tesseract | Not installed |
| pypdf | 6.10.0 |

---

## Per-path smoke status

| Path | Status | Notes |
|------|--------|--------|
| `ffmpeg_smoke` (`extract_audio_wav`) | **PASS** | WAV written under `extracted/` |
| `pdf_smoke` (`extract_pdf_text_to_file`) | **PASS** | Non-empty `extracted/*.txt` |
| `ocr_smoke` (`prepare_ocr_extracted_text`) | **SKIPPED** | `tesseract` not on PATH; error: `tesseract not usable: not found on PATH` |

---

## Throwaway sources (relative to repo root)

| ID | Role |
|----|------|
| `raw/sources/SRC-2099-9200-smoke-audio/` | ffmpeg: `original/smoke.mp4` (video + silent AAC; regenerated after first video-only file failed: no audio stream) |
| `raw/sources/SRC-2099-9201-smoke-pdf/` | PDF: `original/smoke.pdf` (from fpdf2 fixture) |
| `raw/sources/SRC-2099-9202-smoke-ocr/` | PNG: `original/smoke.png` (ffmpeg `drawtext`) |

---

## Commands run (adapter-level)

### 1) Audio — PASS

```bash
cd /home/projects/active/aurea/kb-wiki
.venv/bin/python -c "
from pathlib import Path
import yaml
from scripts.lib.ingestion_audio import extract_audio_wav
sd = Path('raw/sources/SRC-2099-9200-smoke-audio').resolve()
m = yaml.safe_load((sd / 'manifest.yaml').read_text(encoding='utf-8'))
p = extract_audio_wav(sd, m, check_tools=True)
print('AUDIO_OK', p.resolve())
"
```

**Artifact:** `raw/sources/SRC-2099-9200-smoke-audio/extracted/smoke.wav` (32772 bytes on success run).

### 2) Digital PDF — PASS

```bash
.venv/bin/python -c "
from pathlib import Path
import yaml
from scripts.lib.ingestion_pdf import extract_pdf_text_to_file
sd = Path('raw/sources/SRC-2099-9201-smoke-pdf').resolve()
m = yaml.safe_load((sd / 'manifest.yaml').read_text(encoding='utf-8'))
p, text = extract_pdf_text_to_file(sd, m)
print('PDF_OK', p, 'len', len(text.strip()))
"
```

**Artifact:** `raw/sources/SRC-2099-9201-smoke-pdf/extracted/smoke.txt` (contains `Smoke test digital PDF text layer.`).

### 3) OCR — SKIPPED (failure mode captured)

```bash
.venv/bin/python -c "
from pathlib import Path
import yaml
from scripts.lib.ingestion_ocr import prepare_ocr_extracted_text
sd = Path('raw/sources/SRC-2099-9202-smoke-ocr').resolve()
m = yaml.safe_load((sd / 'manifest.yaml').read_text(encoding='utf-8'))
prepare_ocr_extracted_text(sd, m)
"
```

**Exit:** non-zero. **Message:** `OcrIngestError: tesseract not usable: not found on PATH`.

---

## End-to-end ingest smoke — PASS

Used **PDF-validated** source (`SRC-2099-9201-smoke-pdf`) with existing `extracted/smoke.txt` (no `transcript/*.md`). Ingest correctly uses **text passthrough** for chunking after normalized text exists.

```bash
.venv/bin/python scripts/ingest/main.py \
  --source-dir raw/sources/SRC-2099-9201-smoke-pdf \
  --review-id REV-2099-9299
```

**Stdout:**

```
ingest ok: raw/sources/SRC-2099-9201-smoke-pdf
adapter: text_passthrough
chunk source: extracted (1 file(s))
chunks written: 1
registry updated: raw/registry.yaml
review package: staging/reviews/REV-2099-9299
```

**Review package notes** (`staging/reviews/REV-2099-9299/manifest.yaml`):

```yaml
notes: 'Adapter: text_passthrough; Chunk input: extracted (1 file(s)); Existing extracted/*.txt
  used for chunking.'
```

**Downstream files present:** `claim-ledger.jsonl`, `source-summary.md`, `contradictions.md`, `proposed/wiki/...`, etc. (standard review package).

---

## Cleanup performed

After capturing this record, the following were removed from the working tree:

- `raw/sources/SRC-2099-9200-smoke-audio/`
- `raw/sources/SRC-2099-9201-smoke-pdf/`
- `raw/sources/SRC-2099-9202-smoke-ocr/`
- `staging/reviews/REV-2099-9299/`
- `registry.yaml` entry for `SRC-2099-9201`

**fpdf2** may remain installed in `.venv` from fixture generation; remove with `pip uninstall fpdf2` if undesired.

---

## Complete re-run after `tesseract` install (2026-04-13T03:30Z UTC)

**Preflight (all present):**

| Tool | Version / path |
|------|----------------|
| ffmpeg | `ffmpeg version n8.1 Copyright (c) 2000-2026 the FFmpeg developers` |
| tesseract | `tesseract 5.5.2` (`/usr/bin/tesseract`) |
| pdftoppm | `pdftoppm version 26.03.0` |
| pypdf | 6.10.0 |

**System installs used:** none in this session (user installed missing packages before re-run).

### Code fix discovered during re-run

Image OCR failed when `extracted/` did not exist: tesseract wrote nowhere useful. **`scripts/lib/ingestion_ocr.py`** now calls `out_txt.parent.mkdir(parents=True, exist_ok=True)` before invoking tesseract (minimal bugfix, not an adapter redesign).

### Per-path status (this run)

| Path | Status |
|------|--------|
| `ffmpeg_smoke` | **PASS** — `raw/sources/SRC-2099-9200-smoke-audio/extracted/smoke.wav` (32772 bytes) |
| `pdf_smoke` | **PASS** — `raw/sources/SRC-2099-9201-smoke-pdf/extracted/smoke.txt` (34 chars of text) |
| `ocr_smoke` | **PASS** — `raw/sources/SRC-2099-9202-smoke-ocr/extracted/smoke.txt` contained `OCR smoke line` |

**Integrity:** OCR is **validated** on this machine: `tesseract` present **and** `prepare_ocr_extracted_text` **PASS**.

### Commands (same fixture layout as first run)

Audio:

```bash
.venv/bin/python -c "
from pathlib import Path
import yaml
from scripts.lib.ingestion_audio import extract_audio_wav
sd = Path('raw/sources/SRC-2099-9200-smoke-audio').resolve()
m = yaml.safe_load((sd / 'manifest.yaml').read_text(encoding='utf-8'))
print(extract_audio_wav(sd, m, check_tools=True))
"
```

PDF:

```bash
.venv/bin/python -c "
from pathlib import Path
import yaml
from scripts.lib.ingestion_pdf import extract_pdf_text_to_file
sd = Path('raw/sources/SRC-2099-9201-smoke-pdf').resolve()
m = yaml.safe_load((sd / 'manifest.yaml').read_text(encoding='utf-8'))
print(extract_pdf_text_to_file(sd, m))
"
```

OCR:

```bash
.venv/bin/python -c "
from pathlib import Path
import yaml
from scripts.lib.ingestion_ocr import prepare_ocr_extracted_text
sd = Path('raw/sources/SRC-2099-9202-smoke-ocr').resolve()
m = yaml.safe_load((sd / 'manifest.yaml').read_text(encoding='utf-8'))
print(prepare_ocr_extracted_text(sd, m))
"
```

### End-to-end ingest — **PASS**

```bash
.venv/bin/python scripts/ingest/main.py \
  --source-dir raw/sources/SRC-2099-9201-smoke-pdf \
  --review-id REV-2099-9299
```

Stdout:

```text
ingest ok: raw/sources/SRC-2099-9201-smoke-pdf
adapter: text_passthrough
chunk source: extracted (1 file(s))
chunks written: 1
registry updated: raw/registry.yaml
review package: staging/reviews/REV-2099-9299
```

### Cleanup (re-run)

Removed again: `SRC-2099-9200/9201/9202` smoke trees, `REV-2099-9299`, and `registry` row for `SRC-2099-9201`.

### Tests

`pytest -q` — 69 passed (after `ingestion_ocr.py` mkdir fix).

---

## Post-pull smoke (remote `cursor/phase5-ingestion-expansion`)

**Git:** `git pull origin cursor/phase5-ingestion-expansion` fast-forwarded to `031d7a5` (includes `refactor(ocr): extract shared helper…` and prior PR review fixes).

### OCR fix (exact file and change)

**File:** [`scripts/lib/ingestion_ocr.py`](../../scripts/lib/ingestion_ocr.py) — function `_run_tesseract_on_image`.

**Change:** Ensure the output directory exists **before** tesseract runs (otherwise tesseract does not create `extracted/*.txt` when `extracted/` is missing). Add:

```32:33:scripts/lib/ingestion_ocr.py
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_base = out_txt.with_suffix("")  # tesseract adds .txt
```

**Note:** The pulled branch did not include this `mkdir` at the start of `_run_tesseract_on_image`; without it, the image OCR smoke fails with `OcrIngestError: tesseract did not produce output .txt`. The line was re-applied locally for this run. (A redundant `mkdir` remains later in the same function when copying output; harmless.)

### Smoke results (this run)

| Path | Status |
|------|--------|
| ffmpeg (`extract_audio_wav`) | **PASS** |
| PDF (`extract_pdf_text_to_file`) | **PASS** |
| OCR (`prepare_ocr_extracted_text`, no pre-existing `extracted/`) | **PASS** (after `mkdir` above) |
| End-to-end ingest | **PASS** |

### End-to-end ingest — exact command and output

Command:

```bash
.venv/bin/python scripts/ingest/main.py --source-dir raw/sources/SRC-2099-9201-smoke-pdf --review-id REV-2099-9299
```

Output (full stdout, five lines):

```text
ingest ok: raw/sources/SRC-2099-9201-smoke-pdf
adapter: text_passthrough
chunk source: extracted (1 file(s))
chunks written: 1
registry updated: raw/registry.yaml
review package: staging/reviews/REV-2099-9299
```

### Cleanup (this run)

**Completed:** The throwaway source trees `raw/sources/SRC-2099-9200-smoke-audio`, `raw/sources/SRC-2099-9201-smoke-pdf`, and `raw/sources/SRC-2099-9202-smoke-ocr` were deleted; the temporary review package `staging/reviews/REV-2099-9299` was removed; `/tmp/smoke-digital.pdf` was removed. **`raw/registry.yaml`** was left matching the committed state (no `SRC-2099-9201` smoke entry). **`pytest -q`:** 69 passed.

### Uncommitted change after pull

Local modification to [`scripts/lib/ingestion_ocr.py`](../../scripts/lib/ingestion_ocr.py) (the `mkdir` line at the start of `_run_tesseract_on_image`) should be committed if you want the fix on the branch.
