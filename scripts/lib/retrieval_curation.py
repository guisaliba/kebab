from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from scripts.lib.frontmatter import parse_markdown_with_frontmatter
from scripts.lib.ids import validate_source_id
from scripts.lib.paths import ROOT
from scripts.lib.querying import SearchHit, collect_source_markers, search_raw_chunks, search_wiki
from scripts.lib.time import utc_now_iso8601
from scripts.lib.validation import load_yaml

ALLOWED_CHANGE_TYPES = {"append_section", "update_section", "new_note_link", "conflict_flag"}
ALIAS_ATTRIBUTION_CLASSES = {
    "alias_only",
    "fuzzy_only",
    "both_independently",
    "combined_only",
    "alias_plus_fuzzy_interaction",
    "none",
}
RETRIEVAL_POLICY_VERSION = "phase4-v1"
CLAIM_CONFIDENCE_WEIGHT = {"high": 3, "medium": 2, "low": 1}
ALLOWED_QUALITY_FLAGS = {
    "weak_linked_claim_coverage",
    "low_citation_coverage",
    "single_supporting_context",
    "duplicated_evidence_unavoidable",
}
POSITIVE_REASON_CODES = {
    "claims_linked_strong",
    "citations_grounded",
    "supporting_context_diverse",
}
CAUTIONARY_REASON_CODES = {
    "weak_linked_claim_coverage",
    "low_citation_coverage",
    "single_supporting_context",
    "duplicated_evidence_unavoidable",
}
ALLOWED_CONFIDENCE_BANDS = {"high", "medium", "low"}
ALLOWED_REVIEW_ACTIONS = {"quick-approve", "normal-review", "deep-review"}


def _winner_path(hits: list[SearchHit]) -> str | None:
    if not hits:
        return None
    return str(hits[0].path.relative_to(ROOT))


def _normalize_intent_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _combine_intent_parts(primary: str, secondary: str) -> str:
    primary_clean = primary.strip()
    secondary_clean = secondary.strip()
    if not primary_clean:
        return secondary_clean
    if not secondary_clean:
        return primary_clean
    if _normalize_intent_text(primary_clean) == _normalize_intent_text(secondary_clean):
        return primary_clean
    return f"{primary_clean} {secondary_clean}"


def _search_hits(question: str, *, fuzzy: bool, aliases: bool) -> tuple[str, list[SearchHit]]:
    wiki_hits = search_wiki(
        question,
        min_score=0.8,
        fuzzy=fuzzy,
        include_navigation=False,
        use_aliases=aliases,
    )
    if wiki_hits:
        return ("wiki", wiki_hits[:3])
    raw_hits = search_raw_chunks(
        question,
        min_score=0.6,
        fuzzy=fuzzy,
        use_aliases=aliases,
    )
    return ("wiki+raw", raw_hits[:3])


def _collect_search_variants(question: str) -> dict[tuple[bool, bool], tuple[str, list[SearchHit]]]:
    variants: dict[tuple[bool, bool], tuple[str, list[SearchHit]]] = {}
    for fuzzy, aliases in ((False, False), (False, True), (True, False), (True, True)):
        variants[(fuzzy, aliases)] = _search_hits(question, fuzzy=fuzzy, aliases=aliases)
    return variants


def _classify_alias_influence(
    question: str,
    *,
    search_variants: dict[tuple[bool, bool], tuple[str, list[SearchHit]]] | None = None,
) -> str:
    variants = search_variants or _collect_search_variants(question)
    _, hits_none = variants[(False, False)]
    _, hits_alias = variants[(False, True)]
    _, hits_fuzzy = variants[(True, False)]
    _, hits_both = variants[(True, True)]

    baseline = _winner_path(hits_none)
    alias_only = _winner_path(hits_alias)
    fuzzy_only = _winner_path(hits_fuzzy)
    combined = _winner_path(hits_both)

    alias_changed = alias_only != baseline
    fuzzy_changed = fuzzy_only != baseline
    combined_changed = combined != baseline

    if combined_changed and not alias_changed and not fuzzy_changed:
        return "combined_only"
    if alias_changed and fuzzy_changed:
        if combined_changed and combined != alias_only and combined != fuzzy_only:
            return "alias_plus_fuzzy_interaction"
        return "both_independently"
    if alias_changed and not fuzzy_changed:
        return "alias_only"
    if fuzzy_changed and not alias_changed:
        return "fuzzy_only"
    return "none"


def _extract_intent(content: str, fallback: str) -> str:
    if content.startswith("---\n") and "\n---\n" in content:
        doc = parse_markdown_with_frontmatter(content)
        title = str(doc.frontmatter.get("title", fallback))
        headings = [line.lstrip("#").strip() for line in doc.body.splitlines() if line.strip().startswith("#")]
        heading = headings[0] if headings else ""
        return _combine_intent_parts(title, heading)
    for line in content.splitlines():
        if line.strip():
            return _combine_intent_parts(fallback, line.strip())
    return fallback


def _normalize_citation_marker(marker: str) -> list[dict[str, str]]:
    cleaned = marker.strip()
    if not cleaned.startswith("[Sources:") or not cleaned.endswith("]"):
        return []
    inner = cleaned[len("[Sources:") : -1].strip()
    parts = [part.strip() for part in inner.split(";") if part.strip()]
    normalized: list[dict[str, str]] = []
    for part in parts:
        chunks = part.split()
        if len(chunks) < 2:
            continue
        source_id = chunks[0]
        if not validate_source_id(source_id):
            continue
        evidence_ref = " ".join(chunks[1:]).strip()
        if not evidence_ref:
            continue
        normalized.append({"source_id": source_id, "evidence_ref": evidence_ref})
    return normalized


def _dedupe_source_markers(markers: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for marker in markers:
        normalized = marker.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _hit_payload(hit: SearchHit) -> dict[str, Any]:
    path_str = str(hit.path.relative_to(ROOT))
    abs_path = ROOT / path_str
    content = abs_path.read_text(encoding="utf-8")
    snippet = next((line.strip() for line in content.splitlines() if line.strip()), "")
    source_markers = _dedupe_source_markers(collect_source_markers(content))
    citations: list[dict[str, str]] = []
    for marker in source_markers:
        citations.extend(_normalize_citation_marker(marker))
    deduped_citations = _dedupe_citations(citations)
    return {
        "path": path_str,
        "snippet": snippet[:240],
        "source_markers": source_markers,
        "citations": deduped_citations,
        "score": round(float(hit.score), 6),
        "explain_payload": hit.explain_payload(),
    }


def _change_type_from_path(path_str: str) -> str:
    if "/source-notes/" in path_str:
        return "new_note_link"
    return "update_section"


def _load_claims(review_dir: Path) -> list[dict[str, Any]]:
    claim_ledger = review_dir / "claim-ledger.jsonl"
    if not claim_ledger.exists():
        return []
    claims: list[dict[str, Any]] = []
    for line in claim_ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            claims.append(payload)
    return claims


def _target_wiki_path(review_id: str, proposed_path: str) -> str:
    target = proposed_path.split(f"staging/reviews/{review_id}/proposed/", 1)[1]
    if not target.startswith("wiki/"):
        return target
    return f"/{target}"


def _linked_claims(claims: list[dict[str, Any]], target_wiki_path: str) -> list[dict[str, Any]]:
    linked: list[dict[str, Any]] = []
    target_no_slash = target_wiki_path.lstrip("/")
    for claim in claims:
        touches = claim.get("touches", [])
        if not isinstance(touches, list):
            continue
        normalized_touches = {str(item).lstrip("/") for item in touches if isinstance(item, str)}
        if target_no_slash in normalized_touches:
            linked.append(claim)
    return sorted(
        linked,
        key=lambda claim: (
            -CLAIM_CONFIDENCE_WEIGHT.get(str(claim.get("confidence", "medium")), 2),
            str(claim.get("claim_id", "")),
        ),
    )


def _dedupe_citations(citations: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for citation in citations:
        source_id = str(citation.get("source_id", ""))
        evidence_ref = str(citation.get("evidence_ref", ""))
        if not source_id or not evidence_ref:
            continue
        key = (source_id, evidence_ref)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"source_id": source_id, "evidence_ref": evidence_ref})
    return sorted(deduped, key=lambda item: (item["source_id"], item["evidence_ref"]))


def _citation_context_key(hit_payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    citations = hit_payload.get("citations", [])
    if not isinstance(citations, list):
        return tuple()
    pairs: list[tuple[str, str]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        source_id = str(citation.get("source_id", ""))
        evidence_ref = str(citation.get("evidence_ref", ""))
        if source_id and evidence_ref:
            pairs.append((source_id, evidence_ref))
    return tuple(sorted(set(pairs)))


def _page_type(hit_payload: dict[str, Any]) -> str:
    explain_payload = hit_payload.get("explain_payload", {})
    if not isinstance(explain_payload, dict):
        return ""
    metadata = explain_payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    page_type = metadata.get("page_type", "")
    return str(page_type)


def _select_supporting_hits(
    *,
    search_hits: list[SearchHit],
    winner: dict[str, Any],
    max_supporting: int = 2,
) -> tuple[list[dict[str, Any]], bool]:
    if max_supporting <= 0 or len(search_hits) <= 1:
        return [], False

    winner_path = str(winner.get("path", ""))
    winner_page_type = _page_type(winner)
    winner_context = _citation_context_key(winner)

    candidate_payloads: list[dict[str, Any]] = []
    for hit in search_hits[1:]:
        payload = _hit_payload(hit)
        if str(payload.get("path", "")) == winner_path:
            continue
        candidate_payloads.append(payload)

    if not candidate_payloads:
        return [], False

    def _priority(payload: dict[str, Any]) -> tuple[int, int, int, float, str]:
        path_penalty = 0 if str(payload.get("path", "")) != winner_path else 1
        page_type_penalty = 0 if _page_type(payload) and _page_type(payload) != winner_page_type else 1
        context_key = _citation_context_key(payload)
        context_penalty = 0 if context_key and context_key != winner_context else 1
        return (
            path_penalty,
            page_type_penalty,
            context_penalty,
            -float(payload.get("score", 0.0)),
            str(payload.get("path", "")),
        )

    candidate_payloads = sorted(candidate_payloads, key=_priority)

    selected: list[dict[str, Any]] = []
    selected_paths: set[str] = set()
    selected_contexts: set[tuple[tuple[str, str], ...]] = {winner_context} if winner_context else set()

    for payload in candidate_payloads:
        if len(selected) >= max_supporting:
            break
        path_value = str(payload.get("path", ""))
        if path_value in selected_paths:
            continue
        context_key = _citation_context_key(payload)
        if context_key and context_key in selected_contexts:
            continue
        selected.append(payload)
        selected_paths.add(path_value)
        if context_key:
            selected_contexts.add(context_key)

    duplicated_unavoidable = False
    if not selected and candidate_payloads:
        fallback = candidate_payloads[0]
        selected.append(fallback)
        duplicated_unavoidable = _citation_context_key(fallback) == winner_context and bool(winner_context)

    return selected, duplicated_unavoidable


def _build_rationale(
    *,
    linked_claims: list[dict[str, Any]],
    winner: dict[str, Any],
    normalized_citations: list[dict[str, str]],
    target_wiki_path: str,
) -> tuple[str, str]:
    claim_prefix = "No linked claims found in claim-ledger.jsonl"
    if linked_claims:
        claim_refs = [f"{claim.get('claim_id', 'CLM-?')}: {str(claim.get('claim', '')).strip()}" for claim in linked_claims[:2]]
        claim_prefix = "Linked claims " + " | ".join(claim_refs)

    winner_path = winner.get("path", "")
    winner_score = winner.get("score", 0.0)
    winner_part = f"top retrieval hit {winner_path} (score={winner_score})" if winner_path else "no accepted retrieval hit"

    citation_part = "no citation spans found"
    if normalized_citations:
        spans = [f"{item['source_id']} {item['evidence_ref']}" for item in normalized_citations[:2]]
        citation_part = "citation spans " + "; ".join(spans)

    why = f"{claim_prefix}; target {target_wiki_path}; {winner_part}; {citation_part}."
    risk = "Suggestion remains staging-only and needs reviewer approval."
    if not linked_claims:
        risk = f"{risk} Claim-to-target linkage was not found in claim-ledger for {target_wiki_path}."
    if not normalized_citations:
        risk = f"{risk} Retrieved evidence lacks valid [Sources: ...] markers."
    return why, risk


def _confidence_band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _review_action_for_confidence(*, band: str, reason_codes: list[str]) -> str:
    cautionary = set(reason_codes).intersection(CAUTIONARY_REASON_CODES)
    if band == "low" or {"weak_linked_claim_coverage", "low_citation_coverage", "duplicated_evidence_unavoidable"}.intersection(
        cautionary
    ):
        return "deep-review"
    if band == "medium" or (band == "high" and cautionary):
        return "normal-review"
    return "quick-approve"


def _compute_confidence_assessment(
    *,
    linked_claims: list[dict[str, Any]],
    normalized_citations: list[dict[str, str]],
    supporting_hits: list[dict[str, Any]],
    quality_flags: list[str],
) -> dict[str, Any]:
    linked_claim_factor = min(len(linked_claims) / 3.0, 1.0)
    citation_factor = min(len(normalized_citations) / 2.0, 1.0)
    supporting_diversity_factor = 1.0 if len(supporting_hits) >= 2 else 0.5 if len(supporting_hits) == 1 else 0.0

    base_score = (
        0.45 * linked_claim_factor
        + 0.35 * citation_factor
        + 0.20 * supporting_diversity_factor
    )

    penalty = 0.0
    if "weak_linked_claim_coverage" in quality_flags:
        penalty += 0.25
    if "low_citation_coverage" in quality_flags:
        penalty += 0.2
    if "single_supporting_context" in quality_flags:
        penalty += 0.1
    if "duplicated_evidence_unavoidable" in quality_flags:
        penalty += 0.1

    score = max(0.0, min(1.0, round(base_score - penalty, 6)))
    band = _confidence_band(score)

    reason_codes: list[str] = []
    if linked_claim_factor >= 0.67:
        reason_codes.append("claims_linked_strong")
    if citation_factor >= 0.5:
        reason_codes.append("citations_grounded")
    if supporting_diversity_factor >= 1.0:
        reason_codes.append("supporting_context_diverse")
    for flag in quality_flags:
        if flag in CAUTIONARY_REASON_CODES:
            reason_codes.append(flag)
    # stable deterministic order and de-duplication
    reason_codes = list(dict.fromkeys(reason_codes))

    review_action = _review_action_for_confidence(band=band, reason_codes=reason_codes)
    if review_action not in ALLOWED_REVIEW_ACTIONS:
        review_action = "normal-review"

    return {
        "score": score,
        "band": band if band in ALLOWED_CONFIDENCE_BANDS else "medium",
        "reason_codes": reason_codes,
        "factor_breakdown": {
            "linked_claim_factor": round(linked_claim_factor, 6),
            "citation_factor": round(citation_factor, 6),
            "supporting_diversity_factor": round(supporting_diversity_factor, 6),
            "base_score": round(base_score, 6),
            "penalty": round(penalty, 6),
        },
        "review_action": review_action,
    }


def generate_retrieval_assist(review_id: str, overwrite: bool = False) -> Path:
    review_dir = ROOT / "staging" / "reviews" / review_id
    if not review_dir.exists():
        raise ValueError(f"review not found: {review_id}")
    manifest = load_yaml(review_dir / "manifest.yaml")
    proposed_paths = manifest.get("proposed_paths", [])
    if not isinstance(proposed_paths, list):
        raise ValueError("review manifest proposed_paths must be a list")

    assist_dir = review_dir / "retrieval-assist"
    if assist_dir.exists():
        if not overwrite:
            raise ValueError(f"retrieval-assist already exists for {review_id}; rerun with --overwrite")
        resolved_review_dir = review_dir.resolve()
        resolved_assist_dir = assist_dir.resolve()
        if (
            assist_dir.is_symlink()
            or resolved_assist_dir.name != "retrieval-assist"
            or not resolved_assist_dir.is_relative_to(resolved_review_dir)
        ):
            raise ValueError(f"unsafe retrieval-assist path for overwrite: {assist_dir}")
        shutil.rmtree(assist_dir)
    assist_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = assist_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    proposals: list[dict[str, Any]] = []
    evidence_paths: list[str] = []
    proposal_paths: list[str] = []
    generated_at = utc_now_iso8601()
    claims = _load_claims(review_dir)

    idx = 1
    for proposed_path in proposed_paths:
        if not isinstance(proposed_path, str):
            continue
        if f"staging/reviews/{review_id}/proposed/wiki/" not in proposed_path:
            continue
        abs_path = ROOT / proposed_path
        if not abs_path.exists():
            continue
        content = abs_path.read_text(encoding="utf-8")
        question = _extract_intent(content, abs_path.stem)
        search_variants = _collect_search_variants(question)
        consulted_layers, search_hits = search_variants[(False, True)]
        winner = _hit_payload(search_hits[0]) if search_hits else {
            "path": "",
            "snippet": "",
            "source_markers": [],
            "citations": [],
            "score": 0.0,
            "explain_payload": {},
        }
        supporting_hits, duplicated_unavoidable = _select_supporting_hits(
            search_hits=search_hits,
            winner=winner,
            max_supporting=2,
        )
        all_citations: list[dict[str, str]] = []
        for hit in [winner, *supporting_hits]:
            all_citations.extend(hit["citations"])
        normalized_citations = _dedupe_citations(all_citations)
        source_ids = sorted({item["source_id"] for item in normalized_citations})

        evidence_bundle_id = f"EV-{idx:04d}"
        proposal_id = f"PRP-{idx:04d}"
        intended_wiki_path = proposed_path.split(f"staging/reviews/{review_id}/proposed/", 1)[1]
        target_wiki_path = _target_wiki_path(review_id, proposed_path)
        linked_claims = _linked_claims(claims, target_wiki_path)
        why_suggested, risk_or_uncertainty = _build_rationale(
            linked_claims=linked_claims,
            winner=winner,
            normalized_citations=normalized_citations,
            target_wiki_path=target_wiki_path,
        )
        quality_flags: list[str] = []
        if not linked_claims:
            quality_flags.append("weak_linked_claim_coverage")
        if not normalized_citations:
            quality_flags.append("low_citation_coverage")
        if len(supporting_hits) <= 1:
            quality_flags.append("single_supporting_context")
        if duplicated_unavoidable:
            quality_flags.append("duplicated_evidence_unavoidable")
        quality_flags = [flag for flag in quality_flags if flag in ALLOWED_QUALITY_FLAGS]
        confidence_assessment = _compute_confidence_assessment(
            linked_claims=linked_claims,
            normalized_citations=normalized_citations,
            supporting_hits=supporting_hits,
            quality_flags=quality_flags,
        )

        change_type = _change_type_from_path(proposed_path)
        if change_type not in ALLOWED_CHANGE_TYPES:
            change_type = "conflict_flag"

        bundle = {
            "evidence_bundle_id": evidence_bundle_id,
            "proposal_id": proposal_id,
            "question_or_intent": question,
            "retrieval_context": {
                "consulted_layers": consulted_layers,
                "fuzzy_enabled": False,
                "aliases_enabled": True,
                "alias_influence_class": _classify_alias_influence(question, search_variants=search_variants),
            },
            "grounding": {
                "normalized_citations": normalized_citations,
                "source_ids": source_ids,
                "citation_format_version": "v1",
            },
            "winner": winner,
            "supporting_hits": supporting_hits,
            "selection_policy": {
                "max_supporting_hits": 2,
                "distinctness_rules": [
                    "different_path",
                    "different_page_type",
                    "different_source_or_citation_context",
                ],
            },
            "quality_flags": quality_flags,
            "confidence_assessment": confidence_assessment,
            "rationale_claim_ids": [str(claim.get("claim_id", "")) for claim in linked_claims[:3]],
            "why_suggested": why_suggested,
            "risk_or_uncertainty": risk_or_uncertainty,
            "generated_at": generated_at,
        }
        evidence_path = evidence_dir / f"{evidence_bundle_id}.yaml"
        evidence_path.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")
        evidence_paths.append(str(evidence_path.relative_to(ROOT)))

        proposal = {
            "proposal_id": proposal_id,
            "target_proposed_path": proposed_path,
            "intended_wiki_path": intended_wiki_path,
            "change_type": change_type,
            "summary": why_suggested,
            "evidence_bundle_id": evidence_bundle_id,
            "review_status": "proposed",
            "confidence_score": confidence_assessment["score"],
            "confidence_band": confidence_assessment["band"],
            "confidence_reason_codes": confidence_assessment["reason_codes"],
            "review_action": confidence_assessment["review_action"],
        }
        proposals.append(proposal)
        proposal_paths.append(proposed_path)
        idx += 1

    proposals_path = assist_dir / "proposals.jsonl"
    proposals_path.write_text(
        "".join(json.dumps(proposal, ensure_ascii=False) + "\n" for proposal in proposals),
        encoding="utf-8",
    )
    reviewer_summary = [
        "# Reviewer Summary",
        "",
        f"- review_id: {review_id}",
        f"- proposals: {len(proposals)}",
        "",
        "## Triage",
    ]
    for proposal in proposals:
        reasons = ", ".join(proposal.get("confidence_reason_codes", [])) or "none"
        reviewer_summary.append(
            "- "
            f"{proposal['proposal_id']} | confidence={proposal.get('confidence_score', 0.0)} ({proposal.get('confidence_band', 'medium')}) "
            f"| reasons={reasons} | action={proposal.get('review_action', 'normal-review')}"
        )
    reviewer_summary.append("")
    for proposal in proposals:
        reviewer_summary.extend(
            [
                f"## {proposal['proposal_id']} — {proposal['change_type']}",
                f"- target: {proposal['target_proposed_path']}",
                f"- intended_wiki_path: {proposal['intended_wiki_path']}",
                f"- confidence: {proposal.get('confidence_score', 0.0)} ({proposal.get('confidence_band', 'medium')})",
                f"- confidence_reasons: {', '.join(proposal.get('confidence_reason_codes', [])) or 'none'}",
                f"- why: {proposal['summary']}",
                f"- reviewer_action: {proposal.get('review_action', 'normal-review')}",
                "",
            ]
        )
    (assist_dir / "reviewer-summary.md").write_text("\n".join(reviewer_summary), encoding="utf-8")

    rerun_note = "overwritten" if overwrite else "initial"
    manifest_payload = {
        "review_id": review_id,
        "generated_at": generated_at,
        "retrieval_policy_version": RETRIEVAL_POLICY_VERSION,
        "proposal_count": len(proposals),
        "proposal_paths": proposal_paths,
        "evidence_bundle_paths": evidence_paths,
        "notes": f"retrieval-assist {rerun_note} run",
    }
    (assist_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return assist_dir
