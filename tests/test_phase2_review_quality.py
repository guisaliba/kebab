import shutil
import subprocess
import sys
from pathlib import Path

from scripts.lib.paths import ROOT


def test_real_source_ingest_generates_claims_and_contradiction_analysis() -> None:
    # Use a non-tracked review id so cleanup never removes committed fixtures.
    review_id = "REV-2099-9910"
    review_dir = ROOT / "staging" / "reviews" / review_id
    if review_dir.exists():
        shutil.rmtree(review_dir)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "ingest" / "main.py"),
                "--source-dir",
                "raw/sources/SRC-2026-0001-meta-ads-course",
                "--review-id",
                review_id,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr + result.stdout

        claim_lines = (review_dir / "claim-ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(claim_lines) >= 3

        contradictions = (review_dir / "contradictions.md").read_text(encoding="utf-8")
        assert "## Compared wiki evidence" in contradictions
        assert "compared with /wiki/" in contradictions

        manifest_text = (review_dir / "manifest.yaml").read_text(encoding="utf-8")
        assert "proposed/wiki/source-notes/" in manifest_text
        assert "proposed/wiki/platforms/meta-ads.md" in manifest_text
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
