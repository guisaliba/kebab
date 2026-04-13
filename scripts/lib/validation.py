from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from scripts.lib.frontmatter import parse_markdown_with_frontmatter
from scripts.lib.ids import (
    ALLOWED_PAGE_TYPES,
    validate_page_type,
    validate_review_id,
    validate_source_id,
    validate_wiki_id,
)
from scripts.lib.paths import ROOT, SCHEMA_DIR
from scripts.lib.reviewer_outcomes import (
    ALLOWED_PROPOSAL_DECISION_STATUSES,
    normalize_proposal_decision_status,
    proposal_decisions_path,
)
from scripts.lib.time import is_iso8601_utc


CITATION_RE = re.compile(r"\[Sources:\s+[^\]]+\]")
REVIEW_PACKAGE_STATUSES = {"pending", "approved", "approved_with_edits", "rejected"}
PAGE_REVIEW_STATUSES = {"proposed", "approved", "rejected"}

REQUIRED_REVIEW_FILES = {
    "source-summary.md",
    "contradictions.md",
    "open-questions.md",
    "decision.md",
    "claim-ledger.jsonl",
}
REQUIRED_RETRIEVAL_ASSIST_FILES = {"manifest.yaml", "proposals.jsonl", "reviewer-summary.md"}
ALLOWED_RETRIEVAL_CHANGE_TYPES = {"append_section", "update_section", "new_note_link", "conflict_flag"}
ALLOWED_RETRIEVAL_QUALITY_FLAGS = {
    "weak_linked_claim_coverage",
    "low_citation_coverage",
    "single_supporting_context",
    "duplicated_evidence_unavoidable",
}
ALLOWED_CONFIDENCE_BANDS = {"high", "medium", "low"}
ALLOWED_CONFIDENCE_REASON_CODES = {
    "claims_linked_strong",
    "citations_grounded",
    "supporting_context_diverse",
    "weak_linked_claim_coverage",
    "low_citation_coverage",
    "single_supporting_context",
    "duplicated_evidence_unavoidable",
}
ALLOWED_REVIEW_ACTIONS = {"quick-approve", "normal-review", "deep-review"}


def load_yaml(path: Path) -> dict[str, Any]:
    data = _normalize_yaml(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at root")
    return data


def _normalize_yaml(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    if isinstance(value, dict):
        return {k: _normalize_yaml(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_yaml(v) for v in value]
    return value


def validate_frontmatter_schema(frontmatter: dict[str, Any]) -> None:
    schema_path = SCHEMA_DIR / "frontmatter.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=frontmatter, schema=schema)


def validate_wiki_markdown_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        doc = parse_markdown_with_frontmatter(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"{path}: invalid frontmatter format: {exc}"]

    fm = doc.frontmatter
    try:
        validate_frontmatter_schema(fm)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{path}: schema validation error: {exc}")
        return errors

    if not validate_page_type(fm["type"]):
        errors.append(f"{path}: invalid page type {fm['type']}")
    if not validate_wiki_id(fm["id"], fm["type"]):
        errors.append(f"{path}: wiki id {fm['id']} does not match page type {fm['type']}")

    for field in ("created_at", "updated_at"):
        value = fm.get(field)
        if not isinstance(value, str) or not is_iso8601_utc(value):
            errors.append(f"{path}: invalid {field}, expected ISO-8601 UTC")

    if fm.get("review_status") not in PAGE_REVIEW_STATUSES:
        errors.append(f"{path}: invalid review_status {fm.get('review_status')}")

    if fm.get("confidence") == "low" and fm.get("review_status") == "approved":
        if "## Caveats" not in doc.body:
            errors.append(f"{path}: missing required ## Caveats section")
        else:
            section = doc.body.split("## Caveats", 1)[1].strip()
            if not section:
                errors.append(f"{path}: ## Caveats section is empty")

    body = doc.body
    for line in body.splitlines():
        if "[Sources" in line and not CITATION_RE.search(line):
            errors.append(f"{path}: malformed citation marker: {line.strip()}")

    return errors


ALLOWED_INGESTION_ADAPTERS = frozenset({"auto", "text", "audio", "pdf", "ocr"})


def validate_manifest_source(manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    errors: list[str] = []
    source_id = manifest.get("source_id")
    if not isinstance(source_id, str) or not validate_source_id(source_id):
        errors.append(f"{manifest_path}: invalid source_id")

    ing = manifest.get("ingestion")
    if ing is not None:
        if not isinstance(ing, dict):
            errors.append(f"{manifest_path}: ingestion must be a mapping when present")
        else:
            adapter = ing.get("adapter")
            if adapter is not None:
                if not isinstance(adapter, str):
                    errors.append(f"{manifest_path}: ingestion.adapter must be a string")
                elif adapter.strip().lower() not in ALLOWED_INGESTION_ADAPTERS:
                    errors.append(
                        f"{manifest_path}: ingestion.adapter must be one of {sorted(ALLOWED_INGESTION_ADAPTERS)}"
                    )
            if ing.get("use_ocr") is not None and not isinstance(ing.get("use_ocr"), bool):
                errors.append(f"{manifest_path}: ingestion.use_ocr must be boolean when present")
            lang = ing.get("tesseract_lang")
            if lang is not None and not isinstance(lang, str):
                errors.append(f"{manifest_path}: ingestion.tesseract_lang must be a string when present")

    files = manifest.get("files")
    if files is not None:
        if not isinstance(files, dict):
            errors.append(f"{manifest_path}: files must be a mapping when present")
        else:
            originals = files.get("originals")
            if originals is not None:
                if not isinstance(originals, list):
                    errors.append(f"{manifest_path}: files.originals must be a list when present")
                else:
                    for idx, item in enumerate(originals):
                        if not isinstance(item, str) or not item.strip():
                            errors.append(f"{manifest_path}: files.originals[{idx}] must be a non-empty string")
                        elif Path(item).is_absolute():
                            errors.append(f"{manifest_path}: files.originals[{idx}] must be relative to the source dir")

    return errors


def validate_review_manifest(manifest: dict[str, Any], review_dir: Path) -> list[str]:
    errors: list[str] = []
    required_fields = {
        "review_id",
        "source_id",
        "package_status",
        "created_at",
        "updated_at",
        "proposed_paths",
        "notes",
    }
    for field in required_fields:
        if field not in manifest:
            errors.append(f"{review_dir}/manifest.yaml missing required field: {field}")

    review_id = manifest.get("review_id")
    if isinstance(review_id, str) and not validate_review_id(review_id):
        errors.append(f"{review_dir}/manifest.yaml invalid review_id")

    source_id = manifest.get("source_id")
    if isinstance(source_id, str) and not validate_source_id(source_id):
        errors.append(f"{review_dir}/manifest.yaml invalid source_id")

    package_status = manifest.get("package_status")
    if package_status not in REVIEW_PACKAGE_STATUSES:
        errors.append(f"{review_dir}/manifest.yaml invalid package_status")

    for field in ("created_at", "updated_at"):
        value = manifest.get(field)
        if not isinstance(value, str) or not is_iso8601_utc(value):
            errors.append(f"{review_dir}/manifest.yaml invalid {field}, expected ISO-8601 UTC")

    proposed_paths = manifest.get("proposed_paths")
    if not isinstance(proposed_paths, list):
        errors.append(f"{review_dir}/manifest.yaml proposed_paths must be a list")
    else:
        for proposed_path in proposed_paths:
            if not isinstance(proposed_path, str):
                errors.append(f"{review_dir}/manifest.yaml proposed_paths entries must be strings")
                continue
            abs_path = ROOT / proposed_path
            if not abs_path.exists():
                errors.append(f"proposed path does not exist: {proposed_path}")

    return errors


def validate_decision_file(decision_path: Path) -> list[str]:
    errors: list[str] = []
    content = decision_path.read_text(encoding="utf-8")
    status_line = None
    for line in content.splitlines():
        if line.startswith("Status:"):
            status_line = line.split(":", 1)[1].strip()
            break
    if status_line is None:
        errors.append(f"{decision_path}: missing Status line")
    elif status_line not in REVIEW_PACKAGE_STATUSES:
        errors.append(f"{decision_path}: invalid Status value")
    return errors


def validate_claim_ledger(path: Path, source_id: str) -> list[str]:
    errors: list[str] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{index}: invalid JSONL line: {exc}")
            continue
        if payload.get("source_id") != source_id:
            errors.append(f"{path}:{index}: source_id mismatch")
    return errors


def validate_review_package(review_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = review_dir / "manifest.yaml"
    if not manifest_path.exists():
        return [f"{manifest_path} missing"]
    manifest = load_yaml(manifest_path)
    errors.extend(validate_review_manifest(manifest, review_dir))

    for filename in REQUIRED_REVIEW_FILES:
        path = review_dir / filename
        if not path.exists():
            errors.append(f"{path} missing")

    claim_path = review_dir / "claim-ledger.jsonl"
    if claim_path.exists():
        source_id = manifest.get("source_id", "")
        if isinstance(source_id, str):
            errors.extend(validate_claim_ledger(claim_path, source_id))

    if (review_dir / "decision.md").exists():
        errors.extend(validate_decision_file(review_dir / "decision.md"))

    proposed_paths = manifest.get("proposed_paths", [])
    if isinstance(proposed_paths, list):
        for proposed_path in proposed_paths:
            if not isinstance(proposed_path, str):
                continue
            if "/proposed/wiki/" not in proposed_path:
                errors.append(f"proposed path not under proposed/wiki: {proposed_path}")

    errors.extend(validate_retrieval_assist_artifacts(review_dir))
    errors.extend(validate_proposal_decisions_sidecar(review_dir))
    return errors


def validate_proposal_decisions_sidecar(review_dir: Path) -> list[str]:
    errors: list[str] = []
    sidecar_path = proposal_decisions_path(review_dir)
    if not sidecar_path.exists():
        return errors

    proposals_path = review_dir / "retrieval-assist" / "proposals.jsonl"
    if not proposals_path.exists():
        return [f"{sidecar_path}: proposal-decisions requires retrieval-assist/proposals.jsonl"]

    proposal_ids: set[str] = set()
    for index, line in enumerate(proposals_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            proposal = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{proposals_path}:{index}: invalid JSONL: {exc}")
            continue
        proposal_id = proposal.get("proposal_id")
        if isinstance(proposal_id, str) and proposal_id:
            proposal_ids.add(proposal_id)

    seen_proposals: set[str] = set()
    for index, line in enumerate(sidecar_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{sidecar_path}:{index}: invalid JSONL: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{sidecar_path}:{index}: row must be an object")
            continue

        recorded_at = payload.get("recorded_at")
        if not isinstance(recorded_at, str) or not is_iso8601_utc(recorded_at):
            errors.append(f"{sidecar_path}:{index}: recorded_at must be ISO-8601 UTC")

        proposal_id = payload.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id:
            errors.append(f"{sidecar_path}:{index}: proposal_id must be a non-empty string")
        else:
            if proposal_id in seen_proposals:
                errors.append(
                    f"{sidecar_path}:{index}: duplicate proposal_id {proposal_id}; exactly one active row per proposal_id is allowed"
                )
            seen_proposals.add(proposal_id)
            if proposal_ids and proposal_id not in proposal_ids:
                errors.append(f"{sidecar_path}:{index}: unknown proposal_id {proposal_id}")

        decision = payload.get("decision")
        normalized_decision = normalize_proposal_decision_status(decision)
        if normalized_decision is None:
            errors.append(
                f"{sidecar_path}:{index}: decision must be one of {sorted(ALLOWED_PROPOSAL_DECISION_STATUSES)}"
            )

        notes = payload.get("notes")
        if notes is not None and not isinstance(notes, str):
            errors.append(f"{sidecar_path}:{index}: notes must be a string when present")

        reviewer = payload.get("reviewer")
        if reviewer is not None and not isinstance(reviewer, str):
            errors.append(f"{sidecar_path}:{index}: reviewer must be a string when present")

    return errors


def validate_retrieval_assist_artifacts(review_dir: Path) -> list[str]:
    errors: list[str] = []
    assist_dir = review_dir / "retrieval-assist"
    if not assist_dir.exists():
        return errors
    root_resolved = ROOT.resolve()
    expected_proposed_root = (review_dir / "proposed" / "wiki").resolve()
    expected_evidence_root = (assist_dir / "evidence").resolve()

    manifest_proposal_count: int | None = None
    manifest_proposal_paths: list[str] | None = None
    manifest_evidence_paths: list[str] | None = None
    claim_ids: set[str] = set()
    claim_path = review_dir / "claim-ledger.jsonl"
    if claim_path.exists():
        for line in claim_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                claim_payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            claim_id = claim_payload.get("claim_id")
            if isinstance(claim_id, str) and claim_id:
                claim_ids.add(claim_id)

    for filename in REQUIRED_RETRIEVAL_ASSIST_FILES:
        if not (assist_dir / filename).exists():
            errors.append(f"{assist_dir / filename} missing")

    manifest_path = assist_dir / "manifest.yaml"
    if manifest_path.exists():
        manifest = load_yaml(manifest_path)
        required = {
            "review_id",
            "generated_at",
            "retrieval_policy_version",
            "proposal_count",
            "proposal_paths",
            "evidence_bundle_paths",
            "notes",
        }
        for field in required:
            if field not in manifest:
                errors.append(f"{manifest_path} missing required field: {field}")
        review_id = manifest.get("review_id")
        if not isinstance(review_id, str):
            errors.append(f"{manifest_path} review_id must be a string")
        elif review_id != review_dir.name:
            errors.append(f"{manifest_path} review_id mismatch: expected {review_dir.name}, got {review_id}")
        generated_at = manifest.get("generated_at")
        if not isinstance(generated_at, str) or not is_iso8601_utc(generated_at):
            errors.append(f"{manifest_path} invalid generated_at, expected ISO-8601 UTC")
        proposal_count = manifest.get("proposal_count")
        if not isinstance(proposal_count, int) or proposal_count < 0:
            errors.append(f"{manifest_path} proposal_count must be a non-negative integer")
        else:
            manifest_proposal_count = proposal_count

        proposal_paths = manifest.get("proposal_paths")
        if not isinstance(proposal_paths, list):
            errors.append(f"{manifest_path} proposal_paths must be a list")
        else:
            manifest_proposal_paths = []
            for idx, proposal_path in enumerate(proposal_paths, start=1):
                if not isinstance(proposal_path, str):
                    errors.append(f"{manifest_path} proposal_paths[{idx}] must be a string")
                    continue
                manifest_proposal_paths.append(proposal_path)
                resolved_proposal_path = (ROOT / proposal_path).resolve()
                if not resolved_proposal_path.is_relative_to(root_resolved):
                    errors.append(f"{manifest_path} proposal_paths[{idx}] escapes repository root")
                    continue
                if not resolved_proposal_path.is_relative_to(expected_proposed_root):
                    errors.append(f"{manifest_path} proposal_paths[{idx}] not under review proposed/wiki")
                    continue
                if not resolved_proposal_path.exists():
                    errors.append(f"{manifest_path} proposal_paths[{idx}] missing file: {proposal_path}")

        evidence_bundle_paths = manifest.get("evidence_bundle_paths")
        if not isinstance(evidence_bundle_paths, list):
            errors.append(f"{manifest_path} evidence_bundle_paths must be a list")
        else:
            manifest_evidence_paths = []
            for idx, evidence_bundle_path in enumerate(evidence_bundle_paths, start=1):
                if not isinstance(evidence_bundle_path, str):
                    errors.append(f"{manifest_path} evidence_bundle_paths[{idx}] must be a string")
                    continue
                manifest_evidence_paths.append(evidence_bundle_path)
                resolved_evidence_bundle_path = (ROOT / evidence_bundle_path).resolve()
                if not resolved_evidence_bundle_path.is_relative_to(root_resolved):
                    errors.append(f"{manifest_path} evidence_bundle_paths[{idx}] escapes repository root")
                    continue
                if not resolved_evidence_bundle_path.is_relative_to(expected_evidence_root):
                    errors.append(f"{manifest_path} evidence_bundle_paths[{idx}] not under retrieval-assist/evidence")
                    continue
                if not resolved_evidence_bundle_path.exists():
                    errors.append(f"{manifest_path} evidence_bundle_paths[{idx}] missing file: {evidence_bundle_path}")

    proposals_path = assist_dir / "proposals.jsonl"
    reviewer_summary_triage: dict[str, str] = {}
    reviewer_summary_path = assist_dir / "reviewer-summary.md"
    if reviewer_summary_path.exists():
        for line in reviewer_summary_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("- PRP-"):
                continue
            proposal_id = stripped[2:].split(" |", 1)[0].strip()
            reviewer_summary_triage[proposal_id] = stripped

    parsed_proposal_count = 0
    proposal_paths_from_jsonl: list[str] = []
    evidence_paths_from_jsonl: list[str] = []
    if proposals_path.exists():
        for idx, line in enumerate(proposals_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                proposal = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{proposals_path}:{idx}: invalid JSON: {exc}")
                continue
            parsed_proposal_count += 1

            required = {
                "proposal_id",
                "target_proposed_path",
                "intended_wiki_path",
                "change_type",
                "summary",
                "evidence_bundle_id",
                "review_status",
                "confidence_score",
                "confidence_band",
                "confidence_reason_codes",
                "review_action",
            }
            for field in required:
                if field not in proposal:
                    errors.append(f"{proposals_path}:{idx}: missing required field {field}")

            proposal_id = proposal.get("proposal_id")
            if not isinstance(proposal_id, str) or not proposal_id.strip():
                errors.append(f"{proposals_path}:{idx}: invalid proposal_id")

            target_proposed_path = proposal.get("target_proposed_path")
            if not isinstance(target_proposed_path, str):
                errors.append(f"{proposals_path}:{idx}: invalid target_proposed_path")
            else:
                resolved_target_path = (ROOT / target_proposed_path).resolve()
                if not resolved_target_path.is_relative_to(root_resolved):
                    errors.append(f"{proposals_path}:{idx}: target_proposed_path escapes repository root")
                elif not resolved_target_path.is_relative_to(expected_proposed_root):
                    errors.append(f"{proposals_path}:{idx}: invalid target_proposed_path")
                elif not resolved_target_path.exists():
                    errors.append(f"{proposals_path}:{idx}: missing target_proposed_path file")
                else:
                    proposal_paths_from_jsonl.append(target_proposed_path)

            intended_wiki_path = proposal.get("intended_wiki_path")
            if not isinstance(intended_wiki_path, str) or not intended_wiki_path.startswith("wiki/"):
                errors.append(f"{proposals_path}:{idx}: invalid intended_wiki_path")

            change_type = proposal.get("change_type")
            if change_type not in ALLOWED_RETRIEVAL_CHANGE_TYPES:
                errors.append(f"{proposals_path}:{idx}: invalid change_type {change_type}")

            summary = proposal.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                errors.append(f"{proposals_path}:{idx}: invalid summary")

            review_status = proposal.get("review_status")
            if review_status not in PAGE_REVIEW_STATUSES:
                errors.append(f"{proposals_path}:{idx}: invalid review_status {review_status}")
            confidence_score = proposal.get("confidence_score")
            if not isinstance(confidence_score, (int, float)) or confidence_score < 0.0 or confidence_score > 1.0:
                errors.append(f"{proposals_path}:{idx}: confidence_score must be numeric in [0,1]")
            confidence_band = proposal.get("confidence_band")
            if confidence_band not in ALLOWED_CONFIDENCE_BANDS:
                errors.append(f"{proposals_path}:{idx}: invalid confidence_band {confidence_band}")
            confidence_reason_codes = proposal.get("confidence_reason_codes")
            if not isinstance(confidence_reason_codes, list):
                errors.append(f"{proposals_path}:{idx}: confidence_reason_codes must be a list")
            else:
                for reason_idx, reason_code in enumerate(confidence_reason_codes, start=1):
                    if not isinstance(reason_code, str) or reason_code not in ALLOWED_CONFIDENCE_REASON_CODES:
                        errors.append(
                            f"{proposals_path}:{idx}: confidence_reason_codes[{reason_idx}] invalid value {reason_code}"
                        )
            review_action = proposal.get("review_action")
            if review_action not in ALLOWED_REVIEW_ACTIONS:
                errors.append(f"{proposals_path}:{idx}: invalid review_action {review_action}")

            evidence_bundle_id = proposal.get("evidence_bundle_id")
            if not isinstance(evidence_bundle_id, str):
                errors.append(f"{proposals_path}:{idx}: missing evidence_bundle_id")
                continue
            evidence_path = assist_dir / "evidence" / f"{evidence_bundle_id}.yaml"
            if not evidence_path.exists():
                errors.append(f"{proposals_path}:{idx}: missing evidence bundle {evidence_bundle_id}")
                continue
            evidence_paths_from_jsonl.append(str(evidence_path.relative_to(ROOT)))
            evidence = load_yaml(evidence_path)
            grounding = evidence.get("grounding")
            if not isinstance(grounding, dict):
                errors.append(f"{evidence_path}: missing grounding block")
                continue
            normalized_citations = grounding.get("normalized_citations")
            if not isinstance(normalized_citations, list):
                errors.append(f"{evidence_path}: normalized_citations must be a list")
                continue
            source_ids = grounding.get("source_ids")
            if not isinstance(source_ids, list):
                errors.append(f"{evidence_path}: source_ids must be a list")
            citation_format_version = grounding.get("citation_format_version")
            if not isinstance(citation_format_version, str) or not citation_format_version:
                errors.append(f"{evidence_path}: citation_format_version must be a non-empty string")

            normalized_sources: list[str] = []
            for citation_idx, citation in enumerate(normalized_citations, start=1):
                if not isinstance(citation, dict):
                    errors.append(f"{evidence_path}: normalized_citations[{citation_idx}] must be an object")
                    continue
                citation_source_id = citation.get("source_id")
                evidence_ref = citation.get("evidence_ref")
                if not isinstance(citation_source_id, str) or not validate_source_id(citation_source_id):
                    errors.append(f"{evidence_path}: normalized_citations[{citation_idx}] has invalid source_id")
                if not isinstance(evidence_ref, str) or not evidence_ref.strip():
                    errors.append(f"{evidence_path}: normalized_citations[{citation_idx}] has invalid evidence_ref")
                if isinstance(citation_source_id, str) and validate_source_id(citation_source_id):
                    normalized_sources.append(citation_source_id)

            if isinstance(source_ids, list):
                expected_source_ids = sorted(set(normalized_sources))
                if sorted(set(str(item) for item in source_ids if isinstance(item, str))) != expected_source_ids:
                    errors.append(f"{evidence_path}: source_ids must match normalized_citations source_id values")

            winner = evidence.get("winner")
            if not isinstance(winner, dict):
                errors.append(f"{evidence_path}: winner must be an object")
            else:
                winner_score = winner.get("score")
                if not isinstance(winner_score, (int, float)):
                    errors.append(f"{evidence_path}: winner.score must be numeric")
                winner_explain = winner.get("explain_payload")
                if not isinstance(winner_explain, dict):
                    errors.append(f"{evidence_path}: winner.explain_payload must be an object")

            supporting_hits = evidence.get("supporting_hits")
            if not isinstance(supporting_hits, list):
                errors.append(f"{evidence_path}: supporting_hits must be a list")
            else:
                winner_path = winner.get("path") if isinstance(winner, dict) else None
                for hit_idx, hit in enumerate(supporting_hits, start=1):
                    if not isinstance(hit, dict):
                        errors.append(f"{evidence_path}: supporting_hits[{hit_idx}] must be an object")
                        continue
                    supporting_path = hit.get("path")
                    if isinstance(winner_path, str) and isinstance(supporting_path, str) and supporting_path == winner_path:
                        errors.append(f"{evidence_path}: supporting_hits[{hit_idx}] must exclude winner path")
                    hit_score = hit.get("score")
                    if not isinstance(hit_score, (int, float)):
                        errors.append(f"{evidence_path}: supporting_hits[{hit_idx}].score must be numeric")
                    hit_explain = hit.get("explain_payload")
                    if not isinstance(hit_explain, dict):
                        errors.append(f"{evidence_path}: supporting_hits[{hit_idx}].explain_payload must be an object")

            quality_flags = evidence.get("quality_flags")
            if not isinstance(quality_flags, list):
                errors.append(f"{evidence_path}: quality_flags must be a list")
            else:
                for flag_idx, flag in enumerate(quality_flags, start=1):
                    if not isinstance(flag, str):
                        errors.append(f"{evidence_path}: quality_flags[{flag_idx}] must be a string")
                        continue
                    if flag not in ALLOWED_RETRIEVAL_QUALITY_FLAGS:
                        errors.append(f"{evidence_path}: quality_flags[{flag_idx}] invalid value {flag}")

            confidence_assessment = evidence.get("confidence_assessment")
            if not isinstance(confidence_assessment, dict):
                errors.append(f"{evidence_path}: confidence_assessment must be an object")
            else:
                evidence_score = confidence_assessment.get("score")
                if not isinstance(evidence_score, (int, float)) or evidence_score < 0.0 or evidence_score > 1.0:
                    errors.append(f"{evidence_path}: confidence_assessment.score must be numeric in [0,1]")
                evidence_band = confidence_assessment.get("band")
                if evidence_band not in ALLOWED_CONFIDENCE_BANDS:
                    errors.append(f"{evidence_path}: confidence_assessment.band invalid value {evidence_band}")
                evidence_reason_codes = confidence_assessment.get("reason_codes")
                if not isinstance(evidence_reason_codes, list):
                    errors.append(f"{evidence_path}: confidence_assessment.reason_codes must be a list")
                else:
                    for reason_idx, reason_code in enumerate(evidence_reason_codes, start=1):
                        if not isinstance(reason_code, str) or reason_code not in ALLOWED_CONFIDENCE_REASON_CODES:
                            errors.append(
                                f"{evidence_path}: confidence_assessment.reason_codes[{reason_idx}] invalid value {reason_code}"
                            )
                factor_breakdown = confidence_assessment.get("factor_breakdown")
                if not isinstance(factor_breakdown, dict):
                    errors.append(f"{evidence_path}: confidence_assessment.factor_breakdown must be an object")
                else:
                    for field in {
                        "linked_claim_factor",
                        "citation_factor",
                        "supporting_diversity_factor",
                        "base_score",
                        "penalty",
                    }:
                        value = factor_breakdown.get(field)
                        if not isinstance(value, (int, float)):
                            errors.append(f"{evidence_path}: confidence_assessment.factor_breakdown.{field} must be numeric")
                evidence_review_action = confidence_assessment.get("review_action")
                if evidence_review_action not in ALLOWED_REVIEW_ACTIONS:
                    errors.append(
                        f"{evidence_path}: confidence_assessment.review_action invalid value {evidence_review_action}"
                    )
                if isinstance(confidence_score, (int, float)) and isinstance(evidence_score, (int, float)):
                    if abs(float(confidence_score) - float(evidence_score)) > 1e-9:
                        errors.append(
                            f"{proposals_path}:{idx}: confidence_score must mirror evidence confidence_assessment.score"
                        )
                if confidence_band in ALLOWED_CONFIDENCE_BANDS and evidence_band in ALLOWED_CONFIDENCE_BANDS:
                    if confidence_band != evidence_band:
                        errors.append(
                            f"{proposals_path}:{idx}: confidence_band must mirror evidence confidence_assessment.band"
                        )
                if isinstance(confidence_reason_codes, list) and isinstance(evidence_reason_codes, list):
                    if confidence_reason_codes != evidence_reason_codes:
                        errors.append(
                            f"{proposals_path}:{idx}: confidence_reason_codes must mirror evidence confidence_assessment.reason_codes"
                        )
                if review_action in ALLOWED_REVIEW_ACTIONS and evidence_review_action in ALLOWED_REVIEW_ACTIONS:
                    if review_action != evidence_review_action:
                        errors.append(
                            f"{proposals_path}:{idx}: review_action must mirror evidence confidence_assessment.review_action"
                        )

                summary_line = reviewer_summary_triage.get(str(proposal_id))
                if not summary_line:
                    errors.append(f"{reviewer_summary_path}: missing triage line for {proposal_id}")
                else:
                    if isinstance(confidence_reason_codes, list) and all(
                        isinstance(reason_code, str) for reason_code in confidence_reason_codes
                    ):
                        expected_reason_text = ", ".join(confidence_reason_codes)
                        if not expected_reason_text:
                            expected_reason_text = "none"
                        expected_line = (
                            f"- {proposal_id} | confidence={confidence_score} ({confidence_band}) "
                            f"| reasons={expected_reason_text} | action={review_action}"
                        )
                        if summary_line != expected_line:
                            errors.append(f"{reviewer_summary_path}: triage line mismatch for {proposal_id}")

            selection_policy = evidence.get("selection_policy")
            if not isinstance(selection_policy, dict):
                errors.append(f"{evidence_path}: selection_policy must be an object")
            else:
                max_supporting_hits = selection_policy.get("max_supporting_hits")
                if not isinstance(max_supporting_hits, int) or max_supporting_hits < 0:
                    errors.append(f"{evidence_path}: selection_policy.max_supporting_hits must be a non-negative integer")
                distinctness_rules = selection_policy.get("distinctness_rules")
                if not isinstance(distinctness_rules, list) or not all(isinstance(rule, str) for rule in distinctness_rules):
                    errors.append(f"{evidence_path}: selection_policy.distinctness_rules must be a list of strings")

            why_suggested = evidence.get("why_suggested")
            if not isinstance(why_suggested, str) or not why_suggested.strip():
                errors.append(f"{evidence_path}: why_suggested must be a non-empty string")
            if isinstance(quality_flags, list) and "weak_linked_claim_coverage" in quality_flags:
                if isinstance(why_suggested, str) and "No linked claims found in claim-ledger.jsonl" not in why_suggested:
                    errors.append(f"{evidence_path}: weak_linked_claim_coverage requires explicit linked-claim absence in why_suggested")

            rationale_claim_ids = evidence.get("rationale_claim_ids")
            if not isinstance(rationale_claim_ids, list):
                errors.append(f"{evidence_path}: rationale_claim_ids must be a list")
            else:
                for claim_idx, claim_id in enumerate(rationale_claim_ids, start=1):
                    if not isinstance(claim_id, str) or not claim_id:
                        errors.append(f"{evidence_path}: rationale_claim_ids[{claim_idx}] must be a non-empty string")
                        continue
                    if claim_ids and claim_id not in claim_ids:
                        errors.append(f"{evidence_path}: rationale_claim_ids[{claim_idx}] not found in claim-ledger.jsonl")
            if isinstance(rationale_claim_ids, list) and not rationale_claim_ids:
                if isinstance(why_suggested, str) and "No linked claims found in claim-ledger.jsonl" not in why_suggested:
                    errors.append(f"{evidence_path}: empty rationale_claim_ids must be reflected in why_suggested")

    if manifest_proposal_count is not None and manifest_proposal_count != parsed_proposal_count:
        errors.append(
            f"{manifest_path} proposal_count mismatch: manifest={manifest_proposal_count}, proposals_jsonl={parsed_proposal_count}"
        )
    if manifest_proposal_paths is not None and set(manifest_proposal_paths) != set(proposal_paths_from_jsonl):
        errors.append(f"{manifest_path} proposal_paths do not match proposals.jsonl target_proposed_path values")
    if manifest_evidence_paths is not None and set(manifest_evidence_paths) != set(evidence_paths_from_jsonl):
        errors.append(f"{manifest_path} evidence_bundle_paths do not match proposals.jsonl evidence bundles")

    return errors


def iter_wiki_pages() -> list[Path]:
    pages: list[Path] = []
    for path in (ROOT / "wiki").rglob("*.md"):
        if path.name in {"index.md", "log.md"}:
            continue
        pages.append(path)
    return sorted(pages)


def validate_page_type_list() -> list[str]:
    # Defensive check against accidental divergence.
    if not ALLOWED_PAGE_TYPES:
        return ["allowed page type list is empty"]
    return []
