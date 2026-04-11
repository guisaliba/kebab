# Review Rules

- Review packages must include summary, claim ledger, contradictions, open questions, decision, and proposed wiki files.
- Every review package must have one explicit status: pending, approved, approved_with_edits, rejected.
- Rejections are valid outcomes and should be preserved for auditability.
- Approval is about the proposed diff, not merely the existence of the source.
- Review manifest path is `staging/reviews/REV-YYYY-NNNN/manifest.yaml`.
- Review manifest required fields: `review_id`, `source_id`, `package_status`, `created_at`, `updated_at`, `proposed_paths`, `notes`.
- Claim ledger canonical path is `staging/reviews/REV-YYYY-NNNN/claim-ledger.jsonl`.
