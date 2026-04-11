import subprocess
import sys

from scripts.lib.paths import ROOT


def test_ranking_prefers_lexical_content_page_over_navigation_page() -> None:
    build = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "index" / "main.py"), "--target", "wiki", "--rebuild"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout

    query = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "diagnosticar ROAS Meta Ads",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert query.returncode == 0, query.stderr + query.stdout
    assert "wiki/platforms/meta-ads.md" in query.stdout
    assert "wiki/index.md" not in query.stdout
