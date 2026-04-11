import subprocess
import sys

from scripts.lib.paths import ROOT


def test_canonical_page_prioritized_over_source_note_for_same_topic() -> None:
    build = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "index" / "main.py"), "--target", "wiki"],
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
            "broad targeting meta ads",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert query.returncode == 0, query.stderr + query.stdout
    lines = [line for line in query.stdout.splitlines() if line.startswith("- ")]
    assert lines, query.stdout
    first_hit = lines[0]
    assert "wiki/tactics/broad-targeting.md" in first_hit or "wiki/platforms/meta-ads.md" in first_hit


def test_canonical_page_beats_source_note_when_query_mentions_both() -> None:
    build = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "index" / "main.py"), "--target", "wiki"],
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
            "source note src-2026-0001 versus platform page",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert query.returncode == 0, query.stderr + query.stdout
    lines = [line for line in query.stdout.splitlines() if line.startswith("- ")]
    assert lines, query.stdout
    assert "wiki/platforms/meta-ads.md" in lines[0], query.stdout
