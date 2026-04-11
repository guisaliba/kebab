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
- falls back to `raw/` only when zero wiki hits
- disable fallback with `--wiki-only`

Ranking behavior:

- BM25-first lexical ranking with fielded boosts (`title`, `headings`, `filename`, `frontmatter`, `body`)
- navigation pages like `wiki/index.md` are demoted/excluded from normal answer ranking
- fuzzy matching is default-off and can be enabled with `--fuzzy`
- `--fuzzy-mode auto-on-zero` enables conservative fuzzy retry only when wiki accepted hits are zero

Useful flags:

```bash
python scripts/query/main.py \
  --question "meta ads broad targetng" \
  --top-k 5 \
  --min-score 0.8 \
  --fuzzy \
  --explain-ranking
```

### Build Search Index

```bash
python scripts/index/main.py --target all --rebuild
```

Index notes:

- index files are local and inspectable under `exports/indexes/`
- schema is versioned and fielded for transparent scoring/explanations
- corpora are separated (`wiki.index.json`, `raw.index.json`) to preserve wiki-first policy

## Notes for the implementation agent

Read these first:

- `AGENTS.md`
- `IMPLEMENTATION_BACKLOG.md`
- `schema/`
- `prompts/`

The agent should preserve the three-zone trust model and never introduce direct writes into `wiki/` from automated ingestion.