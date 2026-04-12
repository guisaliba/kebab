# Market Wiki Starter

A markdown-first, git-native internal knowledge system for curated digital marketing and e-commerce knowledge.

This repository is designed around three strict zones:

- `raw/` = immutable evidence
- `staging/` = proposed changes only
- `wiki/` = approved trusted synthesis

The operating model is:

1. ingest a source into `raw/`
2. generate a review package in `staging/`
3. review the proposed diff
4. promote approved changes into `wiki/`
5. answer questions from `wiki/` first, `raw/` second

## What this starter contains

- directory scaffold
- repo contracts for LLM maintainers and SWE agents
- page-type and frontmatter schema
- prompt stubs
- local CLI implementations for ingest/review/promote/query/lint
- one sample source
- one sample review package
- one sample promoted wiki slice

## Core invariant

**Raw is evidence. Staging is proposal. Wiki is trusted synthesis.**

## Recommended implementation order

1. local CLI tooling for ingest/review/promote
2. transcription integration
3. wiki querying workflow
4. linting and health checks
5. search layer when scale requires it
6. UI and MCP later

## Minimal local setup

This starter does not force a stack. The local scripts are Python-based for inspectable CLI workflows.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make tree
make validate
pytest -q
```

## High-level workflow

### Ingest

```bash
python scripts/ingest/main.py \
  --source-dir raw/sources/SRC-2026-0001-meta-ads-course \
  --review-id REV-2026-0001 \
  --chunk-size 1200 \
  --chunk-unit chars
```

Behavior:

- chunk input precedence is `transcript/*.md` then `extracted/*.txt`
- ingest fails clearly when neither exists
- ingest updates `raw/registry.yaml` and writes review package to `staging/reviews/REV-*/`
- ingest never writes to `wiki/`

### Review

Inspect:

- `staging/reviews/REV-2026-0001/source-summary.md`
- `staging/reviews/REV-2026-0001/contradictions.md`
- `staging/reviews/REV-2026-0001/diff.patch`
- `staging/reviews/REV-2026-0001/decision.md`
- `staging/reviews/REV-2026-0001/claim-ledger.jsonl`

Validate package structure:

```bash
python scripts/review/main.py --review-id REV-2026-0001
```

### Retrieval-Assist (Staging-only)

Generate retrieval-backed curation artifacts explicitly (not default on ingest):

```bash
python scripts/curate/main.py --review-id REV-2026-0001
```

Rerun behavior:

- default: fails when `staging/reviews/REV-*/retrieval-assist/` already exists
- use `--overwrite` to replace artifacts in place and refresh `generated_at`

Artifacts are written only under:

- `staging/reviews/REV-YYYY-NNNN/retrieval-assist/manifest.yaml`
- `staging/reviews/REV-YYYY-NNNN/retrieval-assist/proposals.jsonl`
- `staging/reviews/REV-YYYY-NNNN/retrieval-assist/evidence/EV-*.yaml`
- `staging/reviews/REV-YYYY-NNNN/retrieval-assist/reviewer-summary.md`

Contract notes:

- `target_proposed_path` always points to `staging/reviews/REV-.../proposed/wiki/...`
- `intended_wiki_path` is informational and points to `wiki/...`
- evidence bundles carry structured citation grounding (`normalized_citations`, `source_ids`, source markers, per-hit citations)
- winner and supporting hits include concrete `score` and `explain_payload` from retrieval scoring
- supporting hits explicitly exclude winner and may be fewer than max if meaningful alternatives are unavailable
- supporting-hit distinctness preference is: different `path` -> different `page_type` -> different source/citation context
- rationale (`why_suggested`) is generated from existing `claim-ledger.jsonl` links plus citation spans when present
- weak-case rationale stays strictly grounded in linked claims, retrieved hits, and present citation spans; no invented nearest-context explanations
- evidence includes `quality_flags` (`weak_linked_claim_coverage`, `low_citation_coverage`, `single_supporting_context`, `duplicated_evidence_unavoidable`) for reviewer triage
- evidence bundles compute canonical `confidence_assessment` once (`score`, `band`, `reason_codes`, `factor_breakdown`, `review_action`)
- `proposals.jsonl` and `reviewer-summary.md` mirror confidence from evidence bundles without recomputation
- confidence thresholds: `high >= 0.75`, `medium >= 0.45`, `low < 0.45`
- reviewer action mapping is deterministic: `quick-approve` (high without cautionary reasons), `normal-review` (medium or high with cautionary reasons), `deep-review` (low or critical cautionary reasons)
- malformed/partial citation marker segments are ignored conservatively (no synthetic source/evidence fields)
- retrieval-assist never writes directly to `wiki/`

### Promote

```bash
python scripts/promote/main.py --review-id REV-2026-0001
```

Overwrite policy:

- default: promotion fails if target wiki file exists
- overwrite requires `--allow-overwrite`
- overwrite is only allowed for files listed in `proposed_paths`
- all overwrites are logged in `wiki/log.md`

### Query

```bash
python scripts/query/main.py --question "Como diagnosticar ROAS fraco em campanhas de Meta Ads?"
```

Fallback behavior:

- query reads `wiki/` first
- falls back to `raw/` when zero wiki hits or when the prompt is evidence-style (`chunk`, `segment`, `transcript`, timecodes, explicit source IDs)
- disable fallback with `--wiki-only`

Ranking behavior:

- BM25-first lexical ranking with fielded boosts (`title`, `headings`, `filename`, `frontmatter`, `body`)
- navigation pages like `wiki/index.md` are demoted/excluded from normal answer ranking
- fuzzy matching is default-off and can be enabled with `--fuzzy`
- `--fuzzy-mode auto-on-zero` enables conservative fuzzy retry only when wiki accepted hits are zero
- fuzzy expansion gates short/numeric tokens to reduce noisy expansions
- typo aliases are applied via a small KB-scoped alias layer (not universal token normalization)

Useful flags:

```bash
python scripts/query/main.py \
  --question "meta ads broad targetng" \
  --top-k 5 \
  --min-score 0.8 \
  --fuzzy \
  --explain-ranking \
  --explain-ranking-format text
```

Additional retrieval hardening flags:
- `--include-navigation` includes `retrieval_role: navigation` pages in accepted hits (off by default)
- `--explain-ranking-format json` emits machine-readable explanation payloads
- `--verbose-index-status` forces detailed per-file freshness inspection (otherwise query uses fast-path freshness checks)
- `--disable-aliases` disables KB alias normalization for runtime ablation/debug checks

Index trust signals:
- query output includes `index_status[wiki]` / `index_status[raw]` with `indexed_at`
- stale index warnings are surfaced when corpus files are newer or diverge from index metadata

### Build Search Index

```bash
python scripts/index/main.py --target all --rebuild
```

Index notes:

- index files are local and inspectable under `exports/indexes/`
- schema is versioned and fielded for transparent scoring/explanations
- corpora are separated (`wiki.index.json`, `raw.index.json`) to preserve wiki-first policy

### Evaluate Retrieval (Golden Queries)

```bash
python scripts/eval/main.py
```

Evaluation notes:
- golden query dataset: `tests/fixtures/retrieval_golden/queries.json`
- dataset metadata fields: `dataset_version`, `dataset_scope`, `updated_at` (optional `notes`)
- each query uses multi-label categories via `categories: [...]`
- output artifacts: `exports/evals/`
- metrics include top-1 correctness, top-3 coverage, canonical-vs-source-note correctness, fuzzy help/harm, and raw fallback correctness
- top-1 expectations are calibrated across both wiki and raw categories for stronger ranking-signal quality
- metrics are emitted both globally and sliced by category labels
- eval output includes per-query diagnostics (`expected`, `actual`, fallback behavior, fuzzy influence, winner trace) and compact worst-failures summaries with short reason codes
- eval diagnostics also include `diagnostic_classification`, `final_correctness_policy_used`, and `fuzzy_expectation_alignment` to separate ranking misses from expectation mismatches
- typo-sensitive diagnostics include `alias_influence` (`fuzzy_only`, `alias_only`, `fuzzy_plus_alias`) to show attribution
- eval runner writes only under `exports/evals/` and does not mutate `wiki/`, `raw/`, or `staging/`

### Retrieval Normalization Policy

- keep core normalization deterministic (`lowercase`, accent folding, punctuation normalization, stable tokenization)
- keep fuzzy matching calibrated and conservative (no broad default typo expansion)
- keep alias overrides KB/domain-scoped, small, and explicit
- future alias additions should be reviewable suggestions, not automatic growth
- do not evolve a universal hardcoded typo dictionary

## Notes for agents

Read these first:

- `AGENTS.md`
- `BACKLOG.md`
- `schema/`
- `prompts/`

**Always** preserve the three-zone trust model and never introduce direct writes into `wiki/` from automated ingestion.