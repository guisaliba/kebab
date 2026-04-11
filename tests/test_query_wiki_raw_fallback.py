import subprocess
import sys
from pathlib import Path

from scripts.lib.paths import ROOT


def test_query_falls_back_to_raw_when_wiki_has_zero_hits() -> None:
    raw_chunk = ROOT / "raw" / "sources" / "SRC-2026-0001-meta-ads-course" / "chunks" / "9998.md"
    raw_chunk.write_text("UNIQUE_RAW_FALLBACK_TOKEN only in raw.\n", encoding="utf-8")
    try:
        fallback = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "query" / "main.py"),
                "--question",
                "UNIQUE_RAW_FALLBACK_TOKEN",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert fallback.returncode == 0, fallback.stderr + fallback.stdout
        assert "consulted_layers: wiki+raw" in fallback.stdout

        wiki_only = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "query" / "main.py"),
                "--question",
                "UNIQUE_RAW_FALLBACK_TOKEN",
                "--wiki-only",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert wiki_only.returncode == 0, wiki_only.stderr + wiki_only.stdout
        assert "raw fallback disabled" in wiki_only.stdout
    finally:
        if raw_chunk.exists():
            raw_chunk.unlink()


def test_query_falls_back_to_raw_for_evidence_style_prompt() -> None:
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "query" / "main.py"),
            "--question",
            "segment 2 CPM CTR criativo fraco",
            "--top-k",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + run.stdout
    assert "consulted_layers: wiki+raw" in run.stdout
    assert "raw/sources/SRC-2026-0001-meta-ads-course/chunks/0001.md" in run.stdout
