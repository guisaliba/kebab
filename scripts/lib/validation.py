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


def validate_manifest_source(manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    errors: list[str] = []
    source_id = manifest.get("source_id")
    if not isinstance(source_id, str) or not validate_source_id(source_id):
        errors.append(f"{manifest_path}: invalid source_id")
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
    return errors


def validate_retrieval_assist_artifacts(review_dir: Path) -> list[str]:
    errors: list[str] = []
    assist_dir = review_dir / "retrieval-assist"
    if not assist_dir.exists():
        return errors

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
        generated_at = manifest.get("generated_at")
        if not isinstance(generated_at, str) or not is_iso8601_utc(generated_at):
            errors.append(f"{manifest_path} invalid generated_at, expected ISO-8601 UTC")

    proposals_path = assist_dir / "proposals.jsonl"
    if proposals_path.exists():
        for idx, line in enumerate(proposals_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                proposal = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{proposals_path}:{idx}: invalid JSON: {exc}")
                continue

            target_proposed_path = proposal.get("target_proposed_path")
            if not isinstance(target_proposed_path, str) or f"staging/reviews/{review_dir.name}/proposed/wiki/" not in target_proposed_path:
                errors.append(f"{proposals_path}:{idx}: invalid target_proposed_path")
            elif not (ROOT / target_proposed_path).exists():
                errors.append(f"{proposals_path}:{idx}: missing target_proposed_path file")

            intended_wiki_path = proposal.get("intended_wiki_path")
            if not isinstance(intended_wiki_path, str) or not intended_wiki_path.startswith("wiki/"):
                errors.append(f"{proposals_path}:{idx}: invalid intended_wiki_path")

            change_type = proposal.get("change_type")
            if change_type not in ALLOWED_RETRIEVAL_CHANGE_TYPES:
                errors.append(f"{proposals_path}:{idx}: invalid change_type {change_type}")

            evidence_bundle_id = proposal.get("evidence_bundle_id")
            if not isinstance(evidence_bundle_id, str):
                errors.append(f"{proposals_path}:{idx}: missing evidence_bundle_id")
                continue
            evidence_path = assist_dir / "evidence" / f"{evidence_bundle_id}.yaml"
            if not evidence_path.exists():
                errors.append(f"{proposals_path}:{idx}: missing evidence bundle {evidence_bundle_id}")
                continue
            evidence = load_yaml(evidence_path)
            grounding = evidence.get("grounding")
            if not isinstance(grounding, dict):
                errors.append(f"{evidence_path}: missing grounding block")
                continue
            normalized_citations = grounding.get("normalized_citations")
            if not isinstance(normalized_citations, list):
                errors.append(f"{evidence_path}: normalized_citations must be a list")

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
