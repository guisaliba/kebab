import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from scripts.lib.paths import ROOT, STAGING_DIR
from scripts.lib.reviewer_outcomes import (
    ALLOWED_PROPOSAL_DECISION_STATUSES,
    classify_dataset_provenance,
    decision_status_to_outcome,
    extract_decision_status,
    normalize_provenance,
    normalize_proposal_decision_status,
    normalize_reviewer_outcome,
    proposal_decisions_path,
)
from scripts.lib.time import is_iso8601_utc, utc_now_iso8601

DEFAULT_OUTCOMES_PATH = "staging/reviewer-outcomes/outcomes.jsonl"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{index}: invalid JSONL: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"{path}:{index}: row must be an object")
        rows.append(payload)
    return rows


def _append_jsonl_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_proposal(review_id: str, proposal_id: str) -> dict[str, Any]:
    proposals_path = ROOT / "staging" / "reviews" / review_id / "retrieval-assist" / "proposals.jsonl"
    if not proposals_path.exists():
        raise SystemExit(f"retrieval-assist proposals not found: {proposals_path}")
    proposals = _load_jsonl(proposals_path)
    for proposal in proposals:
        if str(proposal.get("proposal_id")) == proposal_id:
            return proposal
    raise SystemExit(f"proposal not found: {proposal_id} in {proposals_path}")


def _predicted_fields(review_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    evidence_bundle_id = str(proposal.get("evidence_bundle_id", ""))
    confidence_score = proposal.get("confidence_score")
    confidence_band = proposal.get("confidence_band")
    review_action = proposal.get("review_action")

    if isinstance(confidence_score, (int, float)) and isinstance(confidence_band, str) and isinstance(review_action, str):
        return {
            "evidence_bundle_id": evidence_bundle_id,
            "predicted_confidence_score": float(confidence_score),
            "predicted_confidence_band": confidence_band,
            "predicted_review_action": review_action,
        }

    if not evidence_bundle_id:
        raise SystemExit("proposal missing evidence_bundle_id and confidence fields")
    evidence_path = ROOT / "staging" / "reviews" / review_id / "retrieval-assist" / "evidence" / f"{evidence_bundle_id}.yaml"
    if not evidence_path.exists():
        raise SystemExit(f"evidence bundle not found: {evidence_path}")
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8")) or {}
    confidence = evidence.get("confidence_assessment")
    if not isinstance(confidence, dict):
        raise SystemExit(f"missing confidence_assessment in {evidence_path}")
    score = confidence.get("score")
    band = confidence.get("band")
    action = confidence.get("review_action")
    if not isinstance(score, (int, float)) or not isinstance(band, str) or not isinstance(action, str):
        raise SystemExit(f"incomplete confidence_assessment fields in {evidence_path}")
    return {
        "evidence_bundle_id": evidence_bundle_id,
        "predicted_confidence_score": float(score),
        "predicted_confidence_band": band,
        "predicted_review_action": action,
    }


def _outcome_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("review_id", "")),
        str(row.get("proposal_id", "")),
        str(row.get("evidence_bundle_id", "")),
    )


def _build_outcome_row_from_proposal(
    *,
    review_id: str,
    proposal: dict[str, Any],
    actual_decision: str,
    notes: str | None,
) -> dict[str, Any]:
    normalized = normalize_reviewer_outcome(actual_decision)
    if normalized is None:
        raise SystemExit(
            "actual decision could not be normalized; expected approve/approve_with_edits/reject (or supported aliases)"
        )

    proposal_id = str(proposal.get("proposal_id", ""))
    predicted = _predicted_fields(review_id, proposal)
    return {
        "recorded_at": utc_now_iso8601(),
        "review_id": review_id,
        "proposal_id": proposal_id,
        "evidence_bundle_id": predicted["evidence_bundle_id"],
        "predicted_confidence_score": predicted["predicted_confidence_score"],
        "predicted_confidence_band": predicted["predicted_confidence_band"],
        "predicted_review_action": predicted["predicted_review_action"],
        "actual_reviewer_decision": actual_decision,
        "actual_reviewer_decision_normalized": normalized,
        "provenance": "real",
        "notes": notes or "",
    }


def _build_outcome_row(
    *,
    review_id: str,
    proposal_id: str,
    actual_decision: str,
    notes: str | None,
) -> dict[str, Any]:
    proposal = _load_proposal(review_id, proposal_id)
    return _build_outcome_row_from_proposal(
        review_id=review_id,
        proposal=proposal,
        actual_decision=actual_decision,
        notes=notes,
    )


def _key_exists_in_jsonl(path: Path, key: tuple[str, str, str]) -> bool:
    """Stream a JSONL file and return True as soon as ``key`` is found (early-exit)."""
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8") as fh:
        for line_num, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_num}: invalid JSONL: {exc}") from exc
            if _outcome_key(row) == key:
                return True
    return False


def append_outcome(
    *,
    review_id: str,
    proposal_id: str,
    actual_decision: str,
    notes: str | None,
    dataset_path: Path,
) -> dict[str, Any]:
    new_row = _build_outcome_row(
        review_id=review_id,
        proposal_id=proposal_id,
        actual_decision=actual_decision,
        notes=notes,
    )

    candidate_key = _outcome_key(new_row)
    if _key_exists_in_jsonl(dataset_path, candidate_key):
        raise SystemExit(
            f"duplicate outcome entry rejected (append-only): review_id={review_id}, proposal_id={proposal_id}, evidence_bundle_id={new_row['evidence_bundle_id']}"
        )

    _append_jsonl_row(dataset_path, new_row)
    return new_row


def _review_dirs(review_ids: list[str] | None) -> list[Path]:
    reviews_root = STAGING_DIR / "reviews"
    if review_ids:
        return [reviews_root / review_id for review_id in review_ids]
    return sorted(path for path in reviews_root.glob("REV-*") if path.is_dir())


def _load_proposal_decisions(review_dir: Path, valid_proposal_ids: set[str]) -> dict[str, dict[str, Any]]:
    sidecar_path = proposal_decisions_path(review_dir)
    if not sidecar_path.exists():
        return {}

    decisions: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(sidecar_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{sidecar_path}:{index}: invalid JSONL: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"{sidecar_path}:{index}: row must be an object")

        proposal_id = payload.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise SystemExit(f"{sidecar_path}:{index}: proposal_id must be a non-empty string")
        if proposal_id in decisions:
            raise SystemExit(
                f"{sidecar_path}:{index}: duplicate proposal_id {proposal_id}; exactly one active row per proposal_id is allowed"
            )
        if valid_proposal_ids and proposal_id not in valid_proposal_ids:
            raise SystemExit(f"{sidecar_path}:{index}: unknown proposal_id {proposal_id}")

        decision = normalize_proposal_decision_status(payload.get("decision"))
        if decision is None:
            raise SystemExit(
                f"{sidecar_path}:{index}: decision must be one of {sorted(ALLOWED_PROPOSAL_DECISION_STATUSES)}"
            )
        recorded_at = payload.get("recorded_at")
        if not isinstance(recorded_at, str) or not is_iso8601_utc(recorded_at):
            raise SystemExit(f"{sidecar_path}:{index}: recorded_at must be ISO-8601 UTC")

        notes = payload.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise SystemExit(f"{sidecar_path}:{index}: notes must be a string when present")
        reviewer = payload.get("reviewer")
        if reviewer is not None and not isinstance(reviewer, str):
            raise SystemExit(f"{sidecar_path}:{index}: reviewer must be a string when present")

        decisions[proposal_id] = {
            "decision": decision,
            "recorded_at": recorded_at,
            "notes": notes or "",
            "reviewer": reviewer or "",
        }
    return decisions


def batch_capture_outcomes(*, review_ids: list[str] | None, dataset_path: Path) -> dict[str, Any]:
    existing_keys = {_outcome_key(row) for row in _load_jsonl(dataset_path)}
    captured_rows = 0
    skipped_duplicates = 0
    skipped_pending = 0
    skipped_missing_retrieval = 0
    skipped_missing_review = 0
    skipped_invalid_status = 0
    processed_reviews = 0
    messages: list[str] = []

    for review_dir in _review_dirs(review_ids):
        review_id = review_dir.name
        if not review_dir.exists():
            skipped_missing_review += 1
            messages.append(f"- {review_id}: skipped (review not found)")
            continue
        decision_path = review_dir / "decision.md"
        proposals_path = review_dir / "retrieval-assist" / "proposals.jsonl"
        if not proposals_path.exists():
            skipped_missing_retrieval += 1
            messages.append(f"- {review_id}: skipped (no retrieval-assist proposals)")
            continue

        proposals = _load_jsonl(proposals_path)
        valid_proposal_ids = {
            str(proposal.get("proposal_id", ""))
            for proposal in proposals
            if isinstance(proposal, dict) and str(proposal.get("proposal_id", ""))
        }
        sidecar_decisions = _load_proposal_decisions(review_dir, valid_proposal_ids)
        sidecar_overrides = 0
        status: str | None = None
        review_level_decision: str | None = None
        if decision_path.exists():
            status = extract_decision_status(decision_path.read_text(encoding="utf-8"))
            if status is None:
                skipped_invalid_status += 1
                messages.append(f"- {review_id}: skipped (Status line missing)")
                continue
            review_level_decision = decision_status_to_outcome(status)
            if review_level_decision is None and status.strip().lower() != "pending":
                skipped_invalid_status += 1
                messages.append(f"- {review_id}: skipped (unsupported decision status: {status})")
                continue
        elif not sidecar_decisions:
            skipped_invalid_status += 1
            messages.append(f"- {review_id}: skipped (decision.md missing and no proposal sidecar)")
            continue

        processed_reviews += 1
        review_captured = 0
        review_duplicates = 0
        review_skipped_pending = 0
        for proposal in proposals:
            proposal_id = str(proposal.get("proposal_id", ""))
            if not proposal_id:
                continue
            decision_source = "review"
            actual_decision = status or ""
            notes = f"batch-capture from review decision status: {actual_decision}" if actual_decision else ""
            if proposal_id in sidecar_decisions:
                decision_source = "proposal-sidecar"
                actual_decision = sidecar_decisions[proposal_id]["decision"]
                notes = f"batch-capture from proposal sidecar decision: {actual_decision}"
                if review_level_decision is not None and decision_status_to_outcome(actual_decision) != review_level_decision:
                    sidecar_overrides += 1
            elif review_level_decision is None:
                skipped_pending += 1
                review_skipped_pending += 1
                continue

            row = _build_outcome_row_from_proposal(
                review_id=review_id,
                proposal=proposal,
                actual_decision=actual_decision,
                notes=notes,
            )
            key = _outcome_key(row)
            if key in existing_keys:
                skipped_duplicates += 1
                review_duplicates += 1
                continue
            _append_jsonl_row(dataset_path, row)
            existing_keys.add(key)
            captured_rows += 1
            review_captured += 1
        if review_captured == 0 and review_skipped_pending and not sidecar_decisions:
            messages.append(f"- {review_id}: skipped (pending decision)")
            continue
        fallback_summary = review_level_decision or "pending"
        messages.append(
            f"- {review_id}: captured={review_captured}, skipped_duplicates={review_duplicates}, "
            f"skipped_pending={review_skipped_pending}, proposal_overrides={sidecar_overrides}, "
            f"fallback_review_status={fallback_summary}"
        )

    return {
        "processed_reviews": processed_reviews,
        "captured_rows": captured_rows,
        "skipped_duplicates": skipped_duplicates,
        "skipped_pending": skipped_pending,
        "skipped_missing_retrieval": skipped_missing_retrieval,
        "skipped_missing_review": skipped_missing_review,
        "skipped_invalid_status": skipped_invalid_status,
        "messages": messages,
    }


def _dataset_payload_for_status(dataset_path: Path) -> dict[str, Any]:
    rows = _load_jsonl(dataset_path)
    provenance_values = [normalize_provenance(row.get("provenance")) or "real" for row in rows]
    dataset_origin = classify_dataset_provenance(provenance_values)
    updated_at = utc_now_iso8601()
    if dataset_path.exists():
        updated_at = utc_now_iso8601()
        if rows:
            recorded_values = [str(row.get("recorded_at", "")) for row in rows if str(row.get("recorded_at", ""))]
            if recorded_values:
                updated_at = max(recorded_values)
    return {
        "metadata": {
            "dataset_version": "v1",
            "dataset_scope": "staging-reviewer-outcomes",
            "updated_at": updated_at,
            "dataset_origin": dataset_origin,
            "notes": "Append-only local reviewer outcome capture dataset.",
        },
        "outcomes": rows,
    }


def status_report(dataset_path: Path) -> dict[str, Any]:
    from scripts.eval.main import _build_calibration_report

    return _build_calibration_report(_dataset_payload_for_status(dataset_path))


def validate_outcomes(dataset_path: Path) -> tuple[int, int]:
    rows = _load_jsonl(dataset_path)
    seen: set[tuple[str, str, str]] = set()
    invalid = 0
    for index, row in enumerate(rows, start=1):
        key = _outcome_key(row)
        if key in seen:
            raise SystemExit(f"{dataset_path}:{index}: duplicate key {key}")
        seen.add(key)
        normalized = normalize_reviewer_outcome(row.get("actual_reviewer_decision"))
        normalized_recorded = row.get("actual_reviewer_decision_normalized")
        if normalized is None or normalized_recorded != normalized:
            invalid += 1
    return len(rows), invalid


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--review-id", required=True)
    append_parser.add_argument("--proposal-id", required=True)
    append_parser.add_argument("--actual-decision", required=True)
    append_parser.add_argument("--notes")
    append_parser.add_argument("--dataset-path", default=DEFAULT_OUTCOMES_PATH)

    batch_parser = subparsers.add_parser("batch-capture")
    batch_parser.add_argument("--review-id", action="append", dest="review_ids")
    batch_parser.add_argument("--dataset-path", default=DEFAULT_OUTCOMES_PATH)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--dataset-path", default=DEFAULT_OUTCOMES_PATH)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--dataset-path", default=DEFAULT_OUTCOMES_PATH)

    args = parser.parse_args()
    dataset_path = (ROOT / args.dataset_path).resolve()
    if args.command == "append":
        row = append_outcome(
            review_id=args.review_id,
            proposal_id=args.proposal_id,
            actual_decision=args.actual_decision,
            notes=args.notes,
            dataset_path=dataset_path,
        )
        print(f"outcome appended: {dataset_path.relative_to(ROOT)}")
        print(
            f"entry_key: ({row['review_id']}, {row['proposal_id']}, {row['evidence_bundle_id']}) decision={row['actual_reviewer_decision_normalized']}"
        )
        return

    if args.command == "batch-capture":
        result = batch_capture_outcomes(review_ids=args.review_ids, dataset_path=dataset_path)
        print(f"outcome dataset: {dataset_path.relative_to(ROOT)}")
        print(f"processed_reviews: {result['processed_reviews']}")
        print(f"captured_rows: {result['captured_rows']}")
        print(f"skipped_duplicates: {result['skipped_duplicates']}")
        print(f"skipped_pending: {result['skipped_pending']}")
        print(f"skipped_missing_retrieval: {result['skipped_missing_retrieval']}")
        print(f"skipped_missing_review: {result['skipped_missing_review']}")
        print(f"skipped_invalid_status: {result['skipped_invalid_status']}")
        for message in result["messages"]:
            print(message)
        return

    if args.command == "status":
        report = status_report(dataset_path)
        metrics = report["metrics"]
        readiness = report["readiness"]
        rows = metrics["evaluated_outcomes_count"]
        entries = report["entries"]
        real_rows = sum(1 for entry in entries if entry.get("provenance") == "real")
        synthetic_rows = sum(1 for entry in entries if entry.get("provenance") == "synthetic")
        print(f"outcome dataset: {dataset_path.relative_to(ROOT)}")
        print(f"dataset_provenance: {report['dataset_provenance']}")
        print(f"rows_total: {rows}")
        print(f"rows_real: {real_rows}")
        print(f"rows_synthetic: {synthetic_rows}")
        print(f"distinct_reviews: {readiness['distinct_review_count']}")
        for outcome in ("approve", "approve_with_edits", "reject"):
            count = metrics["class_balance"]["counts"][outcome]
            rate = metrics["class_balance"]["rates"][outcome]
            print(f"class_balance.{outcome}: count={count} rate={rate}")
        print(f"tuning_allowed: {str(report['tuning']['tuning_allowed']).lower()}")
        print("readiness_checks:")
        gaps = readiness.get("readiness_gaps", {})
        for check_name, passed in readiness["checks"].items():
            if passed:
                print(f"- {check_name}: true")
                continue
            gap = gaps.get(check_name, {})
            current = gap.get("current", 0)
            threshold = gap.get("threshold", 0)
            remaining = gap.get("remaining", 0)
            print(f"- {check_name}: false (have {current}, need {threshold}, remaining {remaining})")
        return

    row_count, invalid_count = validate_outcomes(dataset_path)
    print(f"outcomes rows: {row_count}")
    print(f"normalization mismatches: {invalid_count}")
    if invalid_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
