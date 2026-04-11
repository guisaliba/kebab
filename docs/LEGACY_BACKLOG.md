# Legacy Implementation Backlog

This file is meant for a SWE agent or human implementer.

## Phase 1 — Core repository mechanics

- Implement manifest loading and validation
- Implement frontmatter validation for wiki pages
- Implement review package validation
- Implement append-only logging helper for `wiki/log.md`
- Implement promote workflow that copies approved files into `wiki/`
- Implement canonical path and ID utilities

## Phase 2 — Source ingestion

- Add audio extraction wrapper using ffmpeg
- Add chunking logic for long transcripts
- Add pluggable transcription provider layer
- Add text extraction path for PDFs and born-digital books
- Add OCR path for scanned PDFs
- Add source registry updater

## Phase 3 — LLM-assisted curation

- Implement claim extraction pipeline
- Implement proposed page update generation
- Implement contradiction detection against existing wiki pages
- Implement durable source-note generation
- Implement review package creation from prompt templates

## Phase 4 — Query flow

- Implement index-first retrieval over `wiki/`
- Implement source-note fallback
- Implement raw chunk fallback for evidence
- Implement citation formatting
- Implement optional reusable answer filing into staging

## Phase 5 — Health checks

- Orphan page detection
- Missing citation detection
- Duplicate concept detection
- Low-confidence canonical page detection
- Stale unresolved contradiction detection

## Phase 6 — Optional later work

- Add search engine integration
- Add MCP adapter
- Add UI for review and promotion
- Add role-based access and audit trail

## Acceptance criteria

A source can move from raw -> staging -> wiki without any direct automated write into production wiki.