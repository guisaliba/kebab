import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.lib.paths import ROOT
from scripts.lib.validation import validate_review_package


def _build_review_fixture(
    review_id: str,
    *,
    decision_status: str = "pending",
    include_retrieval_assist: bool = True,
    proposals: list[dict[str, object]] | None = None,
    proposal_decisions: list[dict[str, object]] | None = None,
) -> Path:
    review_dir = ROOT / "staging" / "reviews" / review_id
    assist_dir = review_dir / "retrieval-assist"
    evidence_dir = assist_dir / "evidence"
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "decision.md").write_text(
        f"# Decision\n\nStatus: {decision_status}\nReviewer:\nReviewed_at:\n",
        encoding="utf-8",
    )
    if not include_retrieval_assist:
        return review_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)

    proposals = proposals or [
        {
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
    ]
    proposals_path = assist_dir / "proposals.jsonl"
    proposals_path.write_text(
        "".join(json.dumps(proposal, ensure_ascii=False) + "\n" for proposal in proposals),
        encoding="utf-8",
    )
    for proposal in proposals:
        evidence_bundle_id = str(proposal["evidence_bundle_id"])
        score = float(proposal.get("confidence_score", 0.72))
        band = str(proposal.get("confidence_band", "medium"))
        action = str(proposal.get("review_action", "normal-review"))
        reason_codes = proposal.get("confidence_reason_codes", ["citations_grounded"])
        if not isinstance(reason_codes, list):
            reason_codes = ["citations_grounded"]
        (evidence_dir / f"{evidence_bundle_id}.yaml").write_text(
            (
                "confidence_assessment:\n"
                f"  score: {score}\n"
                f"  band: {band}\n"
                f"  reason_codes: {json.dumps(reason_codes, ensure_ascii=False)}\n"
                "  factor_breakdown: {}\n"
                f"  review_action: {action}\n"
            ),
            encoding="utf-8",
        )
    if proposal_decisions:
        (review_dir / "proposal-decisions.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in proposal_decisions),
            encoding="utf-8",
        )
    return review_dir


def _write_review_manifest(review_dir: Path, proposal_paths: list[str]) -> None:
    payload = {
        "review_id": review_dir.name,
        "source_id": "SRC-2099-9800",
        "package_status": "pending",
        "created_at": "2026-04-12T00:00:00Z",
        "updated_at": "2026-04-12T00:00:00Z",
        "proposed_paths": proposal_paths,
        "notes": "test review",
    }
    (review_dir / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_required_review_files(review_dir: Path) -> None:
    (review_dir / "source-summary.md").write_text("# Source Summary\n", encoding="utf-8")
    (review_dir / "contradictions.md").write_text("# Contradictions\n", encoding="utf-8")
    (review_dir / "open-questions.md").write_text("# Open Questions\n", encoding="utf-8")
    (review_dir / "claim-ledger.jsonl").write_text(
        '{"claim_id":"CLM-0001","source_id":"SRC-2099-9800","claim":"test","touches":["/wiki/platforms/meta-ads.md"]}\n',
        encoding="utf-8",
    )


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


def test_batch_capture_appends_rows_and_skips_duplicates_and_pending_reviews() -> None:
    captured_review = _build_review_fixture("REV-2099-9805", decision_status="approved_with_edits")
    pending_review = _build_review_fixture("REV-2099-9806", decision_status="pending")
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-batch-capture.jsonl"
    if dataset_path.exists():
        dataset_path.unlink()
    try:
        first = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "batch-capture",
                "--review-id",
                "REV-2099-9805",
                "--review-id",
                "REV-2099-9806",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert first.returncode == 0, first.stderr + first.stdout
        assert "captured_rows: 1" in first.stdout
        assert "skipped_pending: 1" in first.stdout

        second = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "batch-capture",
                "--review-id",
                "REV-2099-9805",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert second.returncode == 0, second.stderr + second.stdout
        assert "captured_rows: 0" in second.stdout
        assert "skipped_duplicates: 1" in second.stdout
    finally:
        for review_dir in (captured_review, pending_review):
            if review_dir.exists():
                shutil.rmtree(review_dir)
        if dataset_path.exists():
            dataset_path.unlink()


def test_batch_capture_skips_reviews_without_retrieval_assist() -> None:
    review_dir = _build_review_fixture("REV-2099-9807", decision_status="approved", include_retrieval_assist=False)
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-batch-skip-no-assist.jsonl"
    if dataset_path.exists():
        dataset_path.unlink()
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "batch-capture",
                "--review-id",
                "REV-2099-9807",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout
        assert "skipped_missing_retrieval: 1" in run.stdout
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        if dataset_path.exists():
            dataset_path.unlink()


def test_status_command_reports_readiness_gaps() -> None:
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-status.jsonl"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(
        json.dumps(
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "review_id": "REV-2099-9808",
                "proposal_id": "PRP-0001",
                "evidence_bundle_id": "EV-0001",
                "predicted_confidence_score": 0.4,
                "predicted_confidence_band": "low",
                "predicted_review_action": "deep-review",
                "actual_reviewer_decision": "approved_with_edits",
                "actual_reviewer_decision_normalized": "approve_with_edits",
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
                "status",
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout
        assert "dataset_provenance: real" in run.stdout
        assert "rows_total: 1" in run.stdout
        assert "real_outcomes_min_met: false (have 1, need 30, remaining 29)" in run.stdout
        assert "approve_with_edits_class_balance_met: false (have 1, need 8, remaining 7)" in run.stdout
        assert "tuning_allowed: false" in run.stdout
    finally:
        if dataset_path.exists():
            dataset_path.unlink()


def test_batch_capture_prefers_proposal_decision_sidecar_over_review_status() -> None:
    review_id = "REV-2099-9809"
    review_dir = _build_review_fixture(
        review_id,
        decision_status="approved",
        proposal_decisions=[
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "proposal_id": "PRP-0001",
                "decision": "rejected",
                "notes": "Reject this proposal",
                "reviewer": "human",
            }
        ],
    )
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-sidecar-override.jsonl"
    if dataset_path.exists():
        dataset_path.unlink()
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "batch-capture",
                "--review-id",
                review_id,
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout
        assert "proposal_overrides=1" in run.stdout
        row = json.loads(dataset_path.read_text(encoding="utf-8").splitlines()[0])
        assert row["actual_reviewer_decision"] == "rejected"
        assert row["actual_reviewer_decision_normalized"] == "reject"
        assert "proposal sidecar decision" in row["notes"]
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        if dataset_path.exists():
            dataset_path.unlink()


def test_batch_capture_mixes_proposal_decisions_and_review_fallback() -> None:
    review_id = "REV-2099-9810"
    review_dir = _build_review_fixture(
        review_id,
        decision_status="approved",
        proposals=[
            {
                "proposal_id": "PRP-0001",
                "target_proposed_path": f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md",
                "intended_wiki_path": "wiki/platforms/meta-ads.md",
                "change_type": "update_section",
                "summary": "proposal one",
                "evidence_bundle_id": "EV-0001",
                "review_status": "proposed",
                "confidence_score": 0.72,
                "confidence_band": "medium",
                "confidence_reason_codes": ["citations_grounded"],
                "review_action": "normal-review",
            },
            {
                "proposal_id": "PRP-0002",
                "target_proposed_path": f"staging/reviews/{review_id}/proposed/wiki/source-notes/test.md",
                "intended_wiki_path": "wiki/source-notes/test.md",
                "change_type": "new_note_link",
                "summary": "proposal two",
                "evidence_bundle_id": "EV-0002",
                "review_status": "proposed",
                "confidence_score": 0.15,
                "confidence_band": "low",
                "confidence_reason_codes": ["low_citation_coverage"],
                "review_action": "deep-review",
            },
        ],
        proposal_decisions=[
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "proposal_id": "PRP-0001",
                "decision": "approved_with_edits",
            }
        ],
    )
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-mixed-capture.jsonl"
    if dataset_path.exists():
        dataset_path.unlink()
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "batch-capture",
                "--review-id",
                review_id,
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout
        assert "captured_rows: 2" in run.stdout
        assert "proposal_overrides=1" in run.stdout
        rows = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        normalized = {row["proposal_id"]: row["actual_reviewer_decision_normalized"] for row in rows}
        assert normalized == {"PRP-0001": "approve_with_edits", "PRP-0002": "approve"}
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        if dataset_path.exists():
            dataset_path.unlink()


def test_batch_capture_uses_proposal_decisions_even_when_review_is_pending() -> None:
    review_id = "REV-2099-9812"
    review_dir = _build_review_fixture(
        review_id,
        decision_status="pending",
        proposals=[
            {
                "proposal_id": "PRP-0001",
                "target_proposed_path": f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md",
                "intended_wiki_path": "wiki/platforms/meta-ads.md",
                "change_type": "update_section",
                "summary": "proposal one",
                "evidence_bundle_id": "EV-0001",
                "review_status": "proposed",
                "confidence_score": 0.72,
                "confidence_band": "medium",
                "confidence_reason_codes": ["citations_grounded"],
                "review_action": "normal-review",
            },
            {
                "proposal_id": "PRP-0002",
                "target_proposed_path": f"staging/reviews/{review_id}/proposed/wiki/source-notes/test.md",
                "intended_wiki_path": "wiki/source-notes/test.md",
                "change_type": "new_note_link",
                "summary": "proposal two",
                "evidence_bundle_id": "EV-0002",
                "review_status": "proposed",
                "confidence_score": 0.15,
                "confidence_band": "low",
                "confidence_reason_codes": ["low_citation_coverage"],
                "review_action": "deep-review",
            },
        ],
        proposal_decisions=[
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "proposal_id": "PRP-0001",
                "decision": "approved_with_edits",
            }
        ],
    )
    dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-pending-sidecar.jsonl"
    if dataset_path.exists():
        dataset_path.unlink()
    try:
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "outcomes" / "main.py"),
                "batch-capture",
                "--review-id",
                review_id,
                "--dataset-path",
                str(dataset_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout
        assert "captured_rows: 1" in run.stdout
        assert "skipped_pending: 1" in run.stdout
        rows = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["proposal_id"] == "PRP-0001"
        assert rows[0]["actual_reviewer_decision_normalized"] == "approve_with_edits"
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        if dataset_path.exists():
            dataset_path.unlink()


def test_review_validator_rejects_invalid_proposal_decision_sidecar() -> None:
    review_id = "REV-2099-9811"
    review_dir = _build_review_fixture(
        review_id,
        decision_status="approved",
        proposal_decisions=[
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "proposal_id": "PRP-9999",
                "decision": "approve",
            }
        ],
    )
    try:
        _write_review_manifest(
            review_dir,
            [f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md"],
        )
        _write_required_review_files(review_dir)
        errors = validate_review_package(review_dir)
        assert any("unknown proposal_id PRP-9999" in error for error in errors)
        assert any("decision must be one of" in error for error in errors)
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)


def test_duplicate_proposal_id_in_sidecar_fails_validation_and_batch_capture() -> None:
    review_id = "REV-2099-9813"
    review_dir = _build_review_fixture(
        review_id,
        decision_status="approved",
        proposal_decisions=[
            {
                "recorded_at": "2026-04-12T00:00:00Z",
                "proposal_id": "PRP-0001",
                "decision": "approved",
            },
            {
                "recorded_at": "2026-04-12T00:01:00Z",
                "proposal_id": "PRP-0001",
                "decision": "rejected",
            },
        ],
    )
    try:
        _write_review_manifest(
            review_dir,
            [f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md"],
        )
        _write_required_review_files(review_dir)
        errors = validate_review_package(review_dir)
        assert any("exactly one active row per proposal_id is allowed" in error for error in errors)

        dataset_path = ROOT / "staging" / "reviewer-outcomes" / "test-duplicate-sidecar.jsonl"
        if dataset_path.exists():
            dataset_path.unlink()
        try:
            run = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "outcomes" / "main.py"),
                    "batch-capture",
                    "--review-id",
                    review_id,
                    "--dataset-path",
                    str(dataset_path.relative_to(ROOT)),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            assert run.returncode != 0
            assert "exactly one active row per proposal_id is allowed" in (run.stderr + run.stdout)
        finally:
            if dataset_path.exists():
                dataset_path.unlink()
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
