import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.lib.paths import ROOT


def _build_review_fixture(review_id: str) -> Path:
    review_dir = ROOT / "staging" / "reviews" / review_id
    assist_dir = review_dir / "retrieval-assist"
    evidence_dir = assist_dir / "evidence"
    if review_dir.exists():
        shutil.rmtree(review_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    proposal = {
        "proposal_id": "PRP-0001",
        "target_proposed_path": f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md",
        "intended_wiki_path": "wiki/platforms/meta-ads.md",
        "change_type": "update_section",
        "summary": "test summary",
        "evidence_bundle_id": "EV-0001",
        "review_status": "proposed",
        "confidence_score": 0.72,
        "confidence_band": "medium",
        "confidence_reason_codes": ["citations_grounded"],
        "review_action": "normal-review",
    }
    (assist_dir / "proposals.jsonl").write_text(json.dumps(proposal, ensure_ascii=False) + "\n", encoding="utf-8")
    (evidence_dir / "EV-0001.yaml").write_text(
        "confidence_assessment:\n  score: 0.72\n  band: medium\n  reason_codes: [citations_grounded]\n  factor_breakdown: {}\n  review_action: normal-review\n",
        encoding="utf-8",
    )
    return review_dir


def test_append_outcome_writes_real_row_and_rejects_duplicate() -> None:
    review_id = "REV-2099-9801"
    review_dir = _build_review_fixture(review_id)
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-outcomes.jsonl"
    if dataset_path.exists():
        dataset_path.unlink()
    try:
        append = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "append",
                "--review-id",
                review_id,
                "--proposal-id",
                "PRP-0001",
                "--actual-decision",
                "approved_with_edits",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert append.returncode == 0, append.stderr + append.stdout
        lines = [line for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["actual_reviewer_decision_normalized"] == "approve_with_edits"
        assert row["provenance"] == "real"

        duplicate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "append",
                "--review-id",
                review_id,
                "--proposal-id",
                "PRP-0001",
                "--actual-decision",
                "approved_with_edits",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert duplicate.returncode != 0
        assert "duplicate outcome entry rejected" in (duplicate.stderr + duplicate.stdout)
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        if dataset_path.exists():
            dataset_path.unlink()


def test_validate_outcomes_catches_normalization_mismatch() -> None:
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-invalid-outcomes.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "review_id": "REV-2099-9802",
                "proposal_id": "PRP-0001",
                "evidence_bundle_id": "EV-0001",
                "predicted_confidence_score": 0.4,
                "predicted_confidence_band": "low",
                "predicted_review_action": "deep-review",
                "actual_reviewer_decision": "approved",
                "actual_reviewer_decision_normalized": "reject",
                "provenance": "real",
                "notes": "",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "validate",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode != 0
        assert "normalization mismatches: 1" in (run.stderr + run.stdout)
    finally:
        if dataset_path.exists():
            dataset_path.unlink()


def test_eval_reports_real_dataset_provenance_and_class_balance_from_jsonl() -> None:
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-real-provenance.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "recorded_at": "2026-04-12T00:00:00Z",
            "review_id": "REV-2099-9803",
            "proposal_id": "PRP-0001",
            "evidence_bundle_id": "EV-0001",
            "predicted_confidence_score": 0.8,
            "predicted_confidence_band": "high",
            "predicted_review_action": "quick-approve",
            "actual_reviewer_decision": "approved",
            "actual_reviewer_decision_normalized": "approve",
            "provenance": "real",
            "notes": "",
        },
        {
            "recorded_at": "2026-04-12T00:01:00Z",
            "review_id": "REV-2099-9804",
            "proposal_id": "PRP-0001",
            "evidence_bundle_id": "EV-0001",
            "predicted_confidence_score": 0.4,
            "predicted_confidence_band": "low",
            "predicted_review_action": "deep-review",
            "actual_reviewer_decision": "rejected",
            "actual_reviewer_decision_normalized": "reject",
            "provenance": "real",
            "notes": "",
        },
    ]
    dataset_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "eval" / "main.py"),
                "--reviewer-outcomes",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout
        report_line = next(line for line in run.stdout.splitlines() if line.startswith("eval_report:"))
        report_path = ROOT / report_line.split(":", 1)[1].strip()
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        calibration = payload["confidence_calibration"]
        assert calibration["dataset_provenance"] == "real"
        assert calibration["metrics"]["class_balance"]["counts"]["approve"] == 1
        assert calibration["metrics"]["class_balance"]["counts"]["reject"] == 1
    finally:
        if dataset_path.exists():
            dataset_path.unlink()
