import json
import subprocess
import sys

from scripts.lib.paths import ROOT
from scripts.eval.main import _action_alignment, _alias_influence
from scripts.lib.reviewer_outcomes import normalize_reviewer_outcome


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
    assert "alias_influence" in sample
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


def _result_with_winner(path: str) -> dict[str, object]:
    return {
        "consulted_layers": "wiki",
        "wiki_paths": [path],
        "raw_paths": [],
    }


def test_alias_influence_classifies_alias_only() -> None:
    outcome = _alias_influence(
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
    )
    assert outcome["primary_driver"] == "alias_only"


def test_alias_influence_classifies_fuzzy_only() -> None:
    outcome = _alias_influence(
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
    )
    assert outcome["primary_driver"] == "fuzzy_only"


def test_alias_influence_classifies_both_independently() -> None:
    outcome = _alias_influence(
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
    )
    assert outcome["primary_driver"] == "both_independently"


def test_alias_influence_classifies_combined_only_interaction() -> None:
    outcome = _alias_influence(
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
    )
    assert outcome["primary_driver"] == "combined_only"


def test_alias_influence_classifies_alias_plus_fuzzy_interaction() -> None:
    outcome = _alias_influence(
        _result_with_winner("wiki/platforms/meta-ads.md"),
        _result_with_winner("wiki/tactics/broad-targeting.md"),
        _result_with_winner("wiki/glossary.md"),
        _result_with_winner("wiki/overview.md"),
    )
    assert outcome["primary_driver"] == "alias_plus_fuzzy_interaction"


def test_reviewer_outcome_normalization_is_deterministic() -> None:
    assert normalize_reviewer_outcome("approved") == "approve"
    assert normalize_reviewer_outcome("request_edits") == "approve_with_edits"
    assert normalize_reviewer_outcome("rejected") == "reject"
    assert normalize_reviewer_outcome("unknown") is None


def test_action_alignment_direction_labels() -> None:
    assert _action_alignment("quick-approve", "approve") == {"aligned": True, "direction": "aligned"}
    assert _action_alignment("quick-approve", "reject") == {"aligned": False, "direction": "optimistic"}
    assert _action_alignment("deep-review", "approve") == {"aligned": False, "direction": "conservative"}
