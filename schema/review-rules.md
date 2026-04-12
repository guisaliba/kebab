# Review Rules

- Review packages must include summary, claim ledger, contradictions, open questions, decision, and proposed wiki files.
- Every review package must have one explicit status: pending, approved, approved_with_edits, rejected.
- Rejections are valid outcomes and should be preserved for auditability.
- Approval is about the proposed diff, not merely the existence of the source.
- Review manifest path is `staging/reviews/REV-YYYY-NNNN/manifest.yaml`.
- Review manifest required fields: `review_id`, `source_id`, `package_status`, `created_at`, `updated_at`, `proposed_paths`, `notes`.
- Claim ledger canonical path is `staging/reviews/REV-YYYY-NNNN/claim-ledger.jsonl`.
- Retrieval-backed curation is explicit invocation via `scripts/curate/main.py` and writes only to `staging/reviews/REV-YYYY-NNNN/retrieval-assist/`.
- `retrieval-assist/manifest.yaml` required fields: `review_id`, `generated_at`, `retrieval_policy_version`, `proposal_count`, `proposal_paths`, `evidence_bundle_paths`, `notes`.
- `retrieval-assist/proposals.jsonl` entries must include `proposal_id`, `target_proposed_path`, `intended_wiki_path`, `change_type`, `summary`, `evidence_bundle_id`, `review_status`.
- `change_type` allowed values: `append_section`, `update_section`, `new_note_link`, `conflict_flag`.
- `target_proposed_path` must point to `staging/reviews/REV-.../proposed/wiki/...`; `intended_wiki_path` is informational and must point under `wiki/...`.
- Every evidence bundle (`retrieval-assist/evidence/EV-*.yaml`) must include structured grounding (`normalized_citations`, `source_ids`, citation format version) plus winner/supporting hit source markers and citations.
- Reruns fail by default if retrieval-assist artifacts already exist; rerun with `--overwrite` to replace and update `generated_at`.
