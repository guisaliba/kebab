# AGENTS.md

## Mission

Maintain a trusted internal wiki about digital marketing, e-commerce, ads, and adjacent operational knowledge.

## Trust model

- `raw/` = immutable evidence
- `staging/` = proposed changes only
- `wiki/` = approved trusted synthesis

## Absolute rules

- Never edit files under `raw/` after ingestion, except to append metadata that does not alter source content.
- Never write directly to `wiki/` during ingestion.
- All automated proposed changes must be written under `staging/reviews/REV-*/`.
- Every nontrivial claim must cite at least one `source_id`.
- Prefer updating existing pages over creating near-duplicates.
- When sources conflict, preserve the conflict and surface it explicitly.
- Mark uncertainty clearly.
- Do not convert context-bound advice into absolute doctrine.
- Do not use `staging/` content for end-user answers unless explicitly in admin or review mode.

## Language policy

- Canonical wiki language: `pt-BR`
- Preserve original platform terms in English where helpful.
- Preserve source titles in original language.

## Page creation rules

Create a new page only when one of the following is true:

- the concept recurs across multiple sources
- the concept cannot fit cleanly into an existing page
- the page is likely to receive future updates
- the page will materially improve future retrieval and reuse

## Ingest behavior

When a new source is ingested:

1. read source manifest
2. inspect extracted text or transcript
3. extract atomic claims
4. compare against relevant wiki pages
5. generate source summary
6. generate contradictions and open questions
7. generate proposed page changes in staging
8. emit a review package
9. do not promote automatically

## Query behavior

When answering a question:

1. read `wiki/index.md` first
2. read the most relevant wiki pages
3. consult linked source notes if needed
4. inspect `raw/` evidence only when needed
5. answer with source citations
6. if the answer is durable and reusable, propose a `wiki/qa/` or `wiki/comparisons/` addition in staging

## Review posture

Assume the human reviewer is strict.
Optimize for traceability, not cleverness.
Do not overgeneralize from one creator or one course.

## Implementation posture for SWE agents

- prefer boring, inspectable code over clever abstractions
- preserve file-based workflows and plain markdown as the system boundary
- make every step reproducible from CLI
- keep provider integrations swappable
- keep prompts versioned in repo