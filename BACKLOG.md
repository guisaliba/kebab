# Revised Implementation Backlog

## Completed foundation

- Core repository mechanics
- Review package generation and validation
- Promotion flow into trusted wiki
- Chunk-based transcript/text ingestion
- Claim extraction
- Contradiction detection
- Source-note generation
- Wiki-first retrieval
- Raw fallback retrieval
- BM25 + heuristic ranking
- Local materialized indexing
- Explainable ranking output
- Retrieval roles
- Stale-index warnings
- Golden-query evaluation harness
- Category-sliced retrieval diagnostics

## Phase 3C — Retrieval policy tuning and calibration

Focus on fixing what the eval data says is weak.

- Improve raw fallback trigger and ranking for evidence-style queries
- Tune fuzzy matching thresholds and token gating
- Strengthen canonical-over-source-note precedence for topical queries
- Expand top-1-labeled queries so top-1 correctness becomes meaningful
- Use failure codes as tuning backlog:
  - `RAW_FALLBACK_MISS`
  - `FUZZY_HELP_EXPECTED`
  - `CANONICAL_ORDER_MISS`

## Phase 4 — Retrieval-backed curation assistance

Still staging-only. No direct wiki writes.

- Generate retrieval-backed proposed page updates in `staging/`
- Attach explicit evidence bundles to proposed edits
- Generate reviewer-facing “why this change is suggested” notes
- Keep all suggestions review-gated

## Phase 5 — Ingestion expansion

This is where the original audio/PDF/OCR work should live.

- Add ffmpeg audio extraction wrapper
- Add pluggable transcription provider layer
- Add PDF text extraction
- Add OCR path for scanned PDFs
- Add book/document ingestion flows
- Normalize source manifests for media and document types

## Phase 6 — Health checks and wiki maintenance

- Orphan page detection
- Missing citation detection
- Duplicate concept detection
- Low-confidence canonical page detection
- Stale unresolved contradiction detection
- Broken-link / weak cross-link checks
- Registry/wiki consistency checks

## Phase 7 — Optional later work

- MCP adapter
- Review UI
- Role-based access / audit trail
- Search engine integration beyond local BM25
- Semantic rerank hook activation
- Deployment concerns

## Active acceptance criteria

- No direct automated write into production wiki outside promotion
- Query remains wiki-first and raw-second
- Retrieval changes must be benchmarked against the golden dataset
- New ingestion paths must feed raw/staging cleanly before any promotion
- Editorial suggestions must remain staging-only until explicitly approved