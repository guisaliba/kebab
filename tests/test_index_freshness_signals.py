import os
import subprocess
import sys
from pathlib import Path

from scripts.lib.paths import ROOT


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
        os.utime(target, (stat.st_atime + 10, stat.st_mtime + 10))
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
    finally:
        os.utime(target, (stat.st_atime, stat.st_mtime))
