import json
import subprocess
import sys

from scripts.lib.paths import ROOT


def test_eval_outputs_category_sliced_metrics() -> None:
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

    by_category = payload["metrics"]["by_category"]
    for category in (
        "wiki-only",
        "raw-fallback",
        "fuzzy-enabled",
        "canonical-vs-source-note",
        "mixed-ptbr-en",
    ):
        assert category in by_category
        assert "top1_correctness" in by_category[category]
        assert "top3_coverage" in by_category[category]
        assert "canonical_vs_source_note_correctness" in by_category[category]
        assert "raw_fallback_correctness" in by_category[category]
        assert "fuzzy_help_vs_harm" in by_category[category]
