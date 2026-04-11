import os
import subprocess
import sys
import time
from pathlib import Path

from scripts.lib.indexing import index_freshness
from scripts.lib.paths import ROOT


def test_index_freshness_uses_fast_path_when_index_is_current() -> None:
    build = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "index" / "main.py"),
            "--target",
            "wiki",
            "--rebuild",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout
    status = index_freshness("wiki", verbose=False)
    assert status["is_stale"] is False
    assert status["used_detailed_scan"] is False


def test_query_surfaces_stale_index_warning() -> None:
    build = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "index" / "main.py"),
            "--target",
            "wiki",
            "--rebuild",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr + build.stdout

    target = ROOT / "wiki" / "overview.md"
    stat = target.stat()
    try:
        bumped = time.time() + 120
        os.utime(target, (bumped, bumped))
        query = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "query" / "main.py"),
                "--question",
                "overview wiki",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert query.returncode == 0, query.stderr + query.stdout
        assert "index_status[wiki]:" in query.stdout
        assert "WARNING: stale wiki index detected" in query.stdout
        assert "detailed_scan=True" in query.stdout
    finally:
        os.utime(target, (stat.st_atime, stat.st_mtime))
