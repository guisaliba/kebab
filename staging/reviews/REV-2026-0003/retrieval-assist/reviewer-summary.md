# Reviewer Summary

- review_id: REV-2026-0003
- proposals: 2

## Triage
- PRP-0001 | confidence=0.3 (low) | reasons=citations_grounded, supporting_context_diverse, weak_linked_claim_coverage | action=deep-review
- PRP-0002 | confidence=0.7 (medium) | reasons=claims_linked_strong, citations_grounded, single_supporting_context | action=normal-review

## PRP-0001 — new_note_link
- target: staging/reviews/REV-2026-0003/proposed/wiki/source-notes/meta-ads-course-module-1.md
- intended_wiki_path: wiki/source-notes/meta-ads-course-module-1.md
- confidence: 0.3 (low)
- confidence_reasons: citations_grounded, supporting_context_diverse, weak_linked_claim_coverage
- why: No linked claims found in claim-ledger.jsonl; target /wiki/source-notes/meta-ads-course-module-1.md; top retrieval hit wiki/source-notes/src-2026-0001-meta-ads-course-module-1.md (score=30.20162); citation spans SRC-2026-0001 §lesson-01 00:00:00-00:02:10; SRC-2026-0001 §lesson-01 00:02:11-00:05:30.
- reviewer_action: deep-review

## PRP-0002 — update_section
- target: staging/reviews/REV-2026-0003/proposed/wiki/platforms/meta-ads.md
- intended_wiki_path: wiki/platforms/meta-ads.md
- confidence: 0.7 (medium)
- confidence_reasons: claims_linked_strong, citations_grounded, single_supporting_context
- why: Linked claims CLM-0001: Hoje vamos falar sobre estrutura de campanha em Meta Ads e por que o ROAS sozinho nem sempre é suficiente para diagnosticar um problema. | CLM-0005: Não é uma regra universal.; target /wiki/platforms/meta-ads.md; top retrieval hit wiki/platforms/meta-ads.md (score=17.819179); citation spans SRC-2026-0001 §lesson-01 00:00:00-00:02:10; SRC-2026-0001 §lesson-01 00:02:11-00:05:30.
- reviewer_action: normal-review
