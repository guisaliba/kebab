import subprocess
import sys

from scripts.lib.paths import ROOT


def test_fuzzy_query_typo_retrieves_target_when_enabled() -> None:
    build = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "index" / "main.py"), "--target", "wiki"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout

    no_fuzzy = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targetng meta ads",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert no_fuzzy.returncode == 0, no_fuzzy.stderr + no_fuzzy.stdout

    fuzzy = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "brod targetng meta ads",
            "--top-k",
            "3",
            "--fuzzy",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert fuzzy.returncode == 0, fuzzy.stderr + fuzzy.stdout
    assert "wiki/tactics/broad-targeting.md" in fuzzy.stdout or "wiki/platforms/meta-ads.md" in fuzzy.stdout
