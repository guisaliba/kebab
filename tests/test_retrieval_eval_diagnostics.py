import json
import subprocess
import sys

from scripts.lib.paths import ROOT


def test_eval_outputs_per_query_diagnostics_and_worst_failures() -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "eval" / "main.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + run.stdout
    report_line = next(line for line in run.stdout.splitlines() if line.startswith("eval_report:"))
    report_path = ROOT / report_line.split(":", 1)[1].strip()
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    queries = payload["queries"]
    assert len(queries) >= 20
    sample = queries[0]
    assert "categories" in sample
    assert "expected" in sample
    assert "actual_fuzzy_off" in sample
    assert "actual_fuzzy_on" in sample
    assert "fuzzy_influence" in sample
    assert sample["fuzzy_influence"] in {"help", "harm", "neutral"}
    assert "fuzzy_expectation_alignment" in sample
    assert "winner_trace" in sample
    assert "final_correctness_policy_used" in sample
    assert "diagnostic_classification" in sample
    assert "pass_fail_reasons" in sample
    assert "diagnostic_summary" in payload
    assert "classification_counts" in payload["diagnostic_summary"]

    worst = payload["worst_failures"]["by_category"]
    for category in (
        "wiki-only",
        "raw-fallback",
        "fuzzy-enabled",
        "canonical-vs-source-note",
        "mixed-ptbr-en",
    ):
        assert category in worst
        assert isinstance(worst[category], list)
        if worst[category]:
            assert "failure_reason_codes" in worst[category][0]
