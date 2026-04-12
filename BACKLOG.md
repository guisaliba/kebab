# Revised Implementation Backlog

## Completed (through Phase 3E)

### Foundation and vertical slice

- Core repository mechanics
- Review package generation and validation
- Promotion flow into trusted wiki
- Chunk-based transcript/text ingestion
- Claim extraction
- Contradiction detection
- Source-note generation

### Retrieval hardening (3A-3E)

- Wiki-first retrieval + deterministic raw fallback
- BM25 + heuristic ranking with explainability
- Local materialized indexing + freshness trust signals
- Retrieval roles and navigation-page handling
- Golden-query evaluation harness + category-sliced diagnostics
- Failure-code loop for `RAW_FALLBACK_MISS`, `FUZZY_HELP_EXPECTED`, `CANONICAL_ORDER_MISS`, `TOP1_MISS`
- Raw evidence top-1 disambiguation (chunk/segment/timecode)
- Typo-heavy tactic-vs-platform top-1 disambiguation
- Alias attribution diagnostics (`alias_only`, `fuzzy_only`, `both_independently`, `combined_only`, `alias_plus_fuzzy_interaction`, `none`)
- Centralized raw evidence alignment helper for explicit component scoring
- KB/domain-scoped alias overrides (minimal, explicit) with runtime ablation support

## Phase 4 — Retrieval-backed curation assistance (next)

Staging-only. No direct writes to `wiki/`.

- Use retrieval outputs to support proposed wiki updates under `staging/`
- Attach explicit evidence bundles to each proposed change
- Generate reviewer-facing “why this change is suggested” notes
- Keep all suggestions review-gated
- Preserve retrieval-sensitive invariants from 3E:
  - keep alias attribution classes stable
  - keep centralized raw evidence alignment helper stable
  - no regression in retrieval/eval guardrails

## Retrieval normalization policy (long-term)

- Core normalization stays minimal and deterministic (lowercase, accent folding, punctuation normalization, stable tokenization)
- Fuzzy matching remains calibrated and conservative (no default broad expansion)
- Alias overrides remain KB/domain-scoped and explicit (small curated maps)
- Future alias growth should be reviewable suggestions, not automatic mutation
- No universal hardcoded typo dictionary across all domains

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