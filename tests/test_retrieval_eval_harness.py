import json
import subprocess
import sys
from pathlib import Path

from scripts.lib.paths import ROOT


def test_eval_runner_outputs_required_metrics() -> None:
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "eval" / "main.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + run.stdout
    report_line = next(line for line in run.stdout.splitlines() if line.startswith("eval_report:"))
    rel_path = report_line.split(":", 1)[1].strip()
    report_path = ROOT / rel_path
    assert report_path.exists()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "dataset_metadata" in payload
    metrics = payload["metrics"]["global"]
    assert "top1_correctness" in metrics
    assert "top3_coverage" in metrics
    assert "canonical_vs_source_note_correctness" in metrics
    assert "fuzzy_help_vs_harm" in metrics
    assert "raw_fallback_correctness" in metrics
    assert metrics["top1_correctness"]["total"] >= 12
    assert "confidence_calibration" in payload
    calibration = payload["confidence_calibration"]
    assert calibration["dataset_metadata"]["dataset_origin"] == "synthetic"
    assert calibration["dataset_provenance"] == "synthetic"
    assert calibration["normalization"]["unknown_excluded_count"] >= 1
    assert "material_mismatch_gate" in calibration
    assert "action_alignment" in calibration["metrics"]
    assert "band_reliability" in calibration["metrics"]
    assert "class_balance" in calibration["metrics"]
    assert "readiness" in calibration
    assert calibration["tuning"]["performed"] is False
    assert calibration["tuning"]["automatic_tuning_enabled"] is False
