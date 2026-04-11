import json
import subprocess
import sys

from scripts.lib.paths import ROOT


def test_explain_ranking_text_is_human_readable() -> None:
    query = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "Como diagnosticar ROAS em Meta Ads?",
            "--top-k",
            "1",
            "--explain-ranking",
            "--explain-ranking-format",
            "text",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert query.returncode == 0, query.stderr + query.stdout
    assert "explain: bm25_total=" in query.stdout
    assert "accepted_reasons=" in query.stdout or "rejected_reasons=" in query.stdout
    assert "np.float64" not in query.stdout


def test_explain_ranking_json_is_machine_readable() -> None:
    query = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "Como diagnosticar ROAS em Meta Ads?",
            "--top-k",
            "1",
            "--explain-ranking",
            "--explain-ranking-format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert query.returncode == 0, query.stderr + query.stdout
    explain_line = next(line for line in query.stdout.splitlines() if "explain_json:" in line)
    payload = json.loads(explain_line.split("explain_json:", 1)[1].strip())
    assert "bm25_total" in payload
    assert "bm25_fields" in payload
    assert "heuristic_fields" in payload
    assert isinstance(payload["accepted"], bool)
