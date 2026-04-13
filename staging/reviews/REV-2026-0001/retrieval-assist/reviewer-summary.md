# Reviewer Summary

- review_id: REV-2026-0001
- proposals: 3

## Triage
- PRP-0001 | confidence=0.15 (low) | reasons=claims_linked_strong, low_citation_coverage, single_supporting_context | action=deep-review
- PRP-0002 | confidence=0.325 (low) | reasons=citations_grounded, single_supporting_context | action=deep-review
- PRP-0003 | confidence=0.0 (low) | reasons=weak_linked_claim_coverage, low_citation_coverage, single_supporting_context | action=deep-review

## PRP-0001 — update_section
- target: staging/reviews/REV-2026-0001/proposed/wiki/platforms/meta-ads.md
- intended_wiki_path: wiki/platforms/meta-ads.md
- confidence: 0.15 (low)
- confidence_reasons: claims_linked_strong, low_citation_coverage, single_supporting_context
- why: Linked claims CLM-0001: ROAS alone is not sufficient to diagnose campaign problems. | CLM-0002: When creative is weak, CTR may be low even if CPM is acceptable.; target /wiki/platforms/meta-ads.md; top retrieval hit raw/sources/SRC-2026-0001-meta-ads-course/chunks/0002.md (score=1.776494); no citation spans found.
- reviewer_action: deep-review

## PRP-0002 — update_section
- target: staging/reviews/REV-2026-0001/proposed/wiki/tactics/broad-targeting.md
- intended_wiki_path: wiki/tactics/broad-targeting.md
- confidence: 0.325 (low)
- confidence_reasons: citations_grounded, single_supporting_context
- why: Linked claims CLM-0003: Broad targeting can work well when creative testing velocity is high and the offer is strong.; target /wiki/tactics/broad-targeting.md; top retrieval hit wiki/tactics/broad-targeting.md (score=21.22862); citation spans SRC-2026-0001 §lesson-01 00:05:31-00:08:40.
- reviewer_action: deep-review

## PRP-0003 — new_note_link
- target: staging/reviews/REV-2026-0001/proposed/wiki/source-notes/src-2026-0001-meta-ads-course-module-1.md
- intended_wiki_path: wiki/source-notes/src-2026-0001-meta-ads-course-module-1.md
- confidence: 0.0 (low)
- confidence_reasons: weak_linked_claim_coverage, low_citation_coverage, single_supporting_context
- why: No linked claims found in claim-ledger.jsonl; target /wiki/source-notes/src-2026-0001-meta-ads-course-module-1.md; top retrieval hit raw/sources/SRC-2026-0001-meta-ads-course/chunks/0002.md (score=2.576494); no citation spans found.
- reviewer_action: deep-review
