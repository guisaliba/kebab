import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from scripts.lib.paths import ROOT
from scripts.lib.reviewer_outcomes import normalize_reviewer_outcome
from scripts.lib.time import utc_now_iso8601

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
    normalized = normalize_reviewer_outcome(actual_decision)
    if normalized is None:
        raise SystemExit(
            "actual decision could not be normalized; expected approve/approve_with_edits/reject (or supported aliases)"
        )

    proposal = _load_proposal(review_id, proposal_id)
    predicted = _predicted_fields(review_id, proposal)
    new_row = {
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

    candidate_key = _outcome_key(new_row)
    if _key_exists_in_jsonl(dataset_path, candidate_key):
        raise SystemExit(
            f"duplicate outcome entry rejected (append-only): review_id={review_id}, proposal_id={proposal_id}, evidence_bundle_id={predicted['evidence_bundle_id']}"
        )

    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(new_row, ensure_ascii=False) + "\n")
    return new_row


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

    row_count, invalid_count = validate_outcomes(dataset_path)
    print(f"outcomes rows: {row_count}")
    print(f"normalization mismatches: {invalid_count}")
    if invalid_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
