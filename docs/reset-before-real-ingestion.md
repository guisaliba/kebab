# Reset / archive before meaningful ingestion

When you are ready to ingest real knowledge-base content (and discard toy `staging/` and demo `wiki/` state), do **not** delete directories blindly. Use a deliberate, reviewable sequence.

## Principles

- **No silent deletion** — every destructive step is explicit and reversible if you archived first.
- **Raw evidence** — treat `raw/sources/*` as evidence; archive or export what you need before removing sources.
- **Git** — prefer moving disposable state to a branch or archive folder outside the canonical tree if you need history.

## Suggested manual sequence

1. **Freeze state** — commit or stash any work; note current `staging/reviews/` and `wiki/` paths you care about.
2. **Export optional snapshot** — copy `staging/` and/or `wiki/` to a dated archive outside the repo (e.g. `~/archive/kebab-staging-YYYY-MM-DD/`) if you want a reference.
3. **Remove staging review packages** (only when sure):
   - `rm -rf staging/reviews/REV-*` (or selectively remove review IDs).
4. **Remove reviewer outcomes if resetting calibration experiments**:
   - `staging/reviewer-outcomes/outcomes.jsonl` — replace with empty file or remove after backup.
5. **Reset wiki demo pages** (only when sure):
   - Remove or replace files under `wiki/` that were promotion experiments; keep `wiki/index.md` and contracts as needed.
6. **Re-run validation** — `make validate` / `pytest -q` / `python scripts/query/main.py ...` smoke query.
7. **First real ingest** — run `scripts/ingest/main.py` against a new `raw/sources/SRC-...` after Phase 5 adapters are in place.

## What this repo does *not* automate

- There is no default `make reset-demo` that deletes `staging/` or `wiki/` — that would violate the “no silent deletion” rule.

## Related

- Trust model: `AGENTS.md`, `README.md`
- Ingestion rules: `schema/ingestion-rules.md`
