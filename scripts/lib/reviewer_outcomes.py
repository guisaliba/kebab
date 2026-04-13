from __future__ import annotations

from pathlib import Path
from typing import Any

NORMALIZED_REVIEW_OUTCOMES = ("approve", "approve_with_edits", "reject")
PROPOSAL_DECISIONS_FILENAME = "proposal-decisions.jsonl"
PROPOSAL_DECISIONS_TEMPLATE_FILENAME = "proposal-decisions.template.jsonl"
REVIEW_OUTCOME_NORMALIZATION_MAP = {
    "approve": "approve",
    "approved": "approve",
    "approved_clean": "approve",
    "accept": "approve",
    "approve_with_edits": "approve_with_edits",
    "approved_with_edits": "approve_with_edits",
    "approved-edits": "approve_with_edits",
    "request_edits": "approve_with_edits",
    "revise": "approve_with_edits",
    "reject": "reject",
    "rejected": "reject",
    "decline": "reject",
}
ALLOWED_DATASET_PROVENANCE = {"synthetic", "real", "mixed"}
REVIEW_DECISION_TO_OUTCOME = {
    "approved": "approve",
    "approved_with_edits": "approve_with_edits",
    "rejected": "reject",
}
ALLOWED_PROPOSAL_DECISION_STATUSES = frozenset(REVIEW_DECISION_TO_OUTCOME.keys())


def normalize_reviewer_outcome(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    token = raw_value.strip().lower().replace(" ", "_")
    return REVIEW_OUTCOME_NORMALIZATION_MAP.get(token)


def normalize_provenance(raw_value: Any) -> str | None:
    """Normalize a row-level provenance value; only ``synthetic`` and ``real`` are valid at row level."""
    if not isinstance(raw_value, str):
        return None
    token = raw_value.strip().lower()
    if token in {"synthetic", "real"}:
        return token
    return None


def normalize_dataset_provenance(raw_value: Any) -> str | None:
    """Normalize a dataset-level provenance value; ``mixed`` is also valid here."""
    if not isinstance(raw_value, str):
        return None
    token = raw_value.strip().lower()
    if token in ALLOWED_DATASET_PROVENANCE:
        return token
    return None


def classify_dataset_provenance(values: list[str]) -> str:
    normalized = {value for value in values if value in {"synthetic", "real"}}
    if not normalized:
        return "real"
    if normalized == {"synthetic"}:
        return "synthetic"
    if normalized == {"real"}:
        return "real"
    return "mixed"


def decision_status_to_outcome(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    token = raw_value.strip().lower().replace(" ", "_")
    return REVIEW_DECISION_TO_OUTCOME.get(token)


def normalize_proposal_decision_status(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    token = raw_value.strip().lower().replace(" ", "_")
    if token in ALLOWED_PROPOSAL_DECISION_STATUSES:
        return token
    return None


def extract_decision_status(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        if line.startswith("Status:"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def proposal_decisions_path(review_dir: Path) -> Path:
    return review_dir / PROPOSAL_DECISIONS_FILENAME


def proposal_decisions_template_path(review_dir: Path) -> Path:
    return review_dir / PROPOSAL_DECISIONS_TEMPLATE_FILENAME
