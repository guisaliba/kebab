from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from scripts.lib.frontmatter import parse_markdown_with_frontmatter
from scripts.lib.paths import ROOT
from scripts.lib.querying import collect_source_markers, search_raw_chunks, search_wiki
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


def _winner_path(paths: list[str]) -> str | None:
    return paths[0] if paths else None


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


def _search_paths(question: str, *, fuzzy: bool, aliases: bool) -> tuple[str, list[str], list[str]]:
    wiki_hits = search_wiki(
        question,
        min_score=0.8,
        fuzzy=fuzzy,
        include_navigation=False,
        use_aliases=aliases,
    )
    if wiki_hits:
        return (
            "wiki",
            [str(hit.path.relative_to(ROOT)) for hit in wiki_hits[:3]],
            [],
        )
    raw_hits = search_raw_chunks(
        question,
        min_score=0.6,
        fuzzy=fuzzy,
        use_aliases=aliases,
    )
    return (
        "wiki+raw",
        [],
        [str(hit.path.relative_to(ROOT)) for hit in raw_hits[:3]],
    )


def _collect_search_variants(question: str) -> dict[tuple[bool, bool], tuple[str, list[str], list[str]]]:
    variants: dict[tuple[bool, bool], tuple[str, list[str], list[str]]] = {}
    for fuzzy, aliases in ((False, False), (False, True), (True, False), (True, True)):
        variants[(fuzzy, aliases)] = _search_paths(question, fuzzy=fuzzy, aliases=aliases)
    return variants


def _classify_alias_influence(
    question: str,
    *,
    search_variants: dict[tuple[bool, bool], tuple[str, list[str], list[str]]] | None = None,
) -> str:
    variants = search_variants or _collect_search_variants(question)
    _, wiki_none, raw_none = variants[(False, False)]
    _, wiki_alias, raw_alias = variants[(False, True)]
    _, wiki_fuzzy, raw_fuzzy = variants[(True, False)]
    _, wiki_both, raw_both = variants[(True, True)]

    baseline = _winner_path(wiki_none + raw_none)
    alias_only = _winner_path(wiki_alias + raw_alias)
    fuzzy_only = _winner_path(wiki_fuzzy + raw_fuzzy)
    combined = _winner_path(wiki_both + raw_both)

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
        if not chunks:
            continue
        source_id = chunks[0]
        evidence_ref = " ".join(chunks[1:]).strip()
        normalized.append({"source_id": source_id, "evidence_ref": evidence_ref})
    return normalized


def _hit_payload(path_str: str) -> dict[str, Any]:
    abs_path = ROOT / path_str
    content = abs_path.read_text(encoding="utf-8")
    snippet = next((line.strip() for line in content.splitlines() if line.strip()), "")
    source_markers = collect_source_markers(content)
    citations = []
    for marker in source_markers:
        citations.extend(_normalize_citation_marker(marker))
    return {
        "path": path_str,
        "snippet": snippet[:240],
        "source_markers": source_markers,
        "citations": citations,
    }


def _change_type_from_path(path_str: str) -> str:
    if "/source-notes/" in path_str:
        return "new_note_link"
    return "update_section"


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
        consulted_layers, wiki_hits, raw_hits = search_variants[(False, True)]
        winner_paths = wiki_hits + raw_hits
        supporting_paths = winner_paths[:3]
        winner = _hit_payload(supporting_paths[0]) if supporting_paths else {"path": "", "snippet": "", "source_markers": [], "citations": []}
        supporting_hits = [_hit_payload(path) for path in supporting_paths]
        normalized_citations = []
        for hit in supporting_hits:
            normalized_citations.extend(hit["citations"])
        source_ids = sorted({item["source_id"] for item in normalized_citations if item.get("source_id")})

        evidence_bundle_id = f"EV-{idx:04d}"
        proposal_id = f"PRP-{idx:04d}"
        intended_wiki_path = proposed_path.split(f"staging/reviews/{review_id}/proposed/", 1)[1]
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
            "winner": {
                **winner,
                "score": None,
                "explain_payload": None,
            },
            "supporting_hits": [
                {
                    **hit,
                    "score": None,
                }
                for hit in supporting_hits
            ],
            "why_suggested": "Retrieved evidence overlaps proposed update target and supports reviewer inspection.",
            "risk_or_uncertainty": "Suggestion is staging-only and requires reviewer approval before promotion.",
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
            "summary": f"Retrieval-backed review suggestion for {Path(intended_wiki_path).name}",
            "evidence_bundle_id": evidence_bundle_id,
            "review_status": "proposed",
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
    ]
    for proposal in proposals:
        reviewer_summary.extend(
            [
                f"## {proposal['proposal_id']} — {proposal['change_type']}",
                f"- target: {proposal['target_proposed_path']}",
                f"- intended_wiki_path: {proposal['intended_wiki_path']}",
                f"- why: {proposal['summary']}",
                "- reviewer_action: approve | reject | request edits",
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
