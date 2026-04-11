import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.lib.paths import ROOT


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ingest_generates_review_package_and_never_writes_wiki() -> None:
    source_dir = ROOT / "raw" / "sources" / "SRC-2099-9001-test-source"
    review_id = "REV-2099-9001"
    review_dir = ROOT / "staging" / "reviews" / review_id
    if source_dir.exists():
        shutil.rmtree(source_dir)
    if review_dir.exists():
        shutil.rmtree(review_dir)

    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "transcript").mkdir(parents=True, exist_ok=True)
    (source_dir / "extracted").mkdir(parents=True, exist_ok=True)
    (source_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "source_id": "SRC-2099-9001",
                "title": "Integration Test Source",
                "type": "course",
                "language": "pt-BR",
                "status": "active",
                "topics": ["meta-ads"],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (source_dir / "transcript" / "lesson-01.md").write_text(
        "TRANSCRIPT_PRIORITY_TOKEN\n\nThis should be chunked first.\n",
        encoding="utf-8",
    )
    (source_dir / "extracted" / "lesson-01.txt").write_text(
        "EXTRACTED_FALLBACK_TOKEN\n",
        encoding="utf-8",
    )

    wiki_before = {path: _read(path) for path in (ROOT / "wiki").rglob("*.md")}
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "ingest" / "main.py"),
                "--source-dir",
                str(source_dir),
                "--review-id",
                review_id,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout

        chunk_0001 = source_dir / "chunks" / "0001.md"
        assert chunk_0001.exists()
        assert "TRANSCRIPT_PRIORITY_TOKEN" in _read(chunk_0001)
        assert "EXTRACTED_FALLBACK_TOKEN" not in _read(chunk_0001)

        manifest = yaml.safe_load((review_dir / "manifest.yaml").read_text(encoding="utf-8"))
        for field in (
            "review_id",
            "source_id",
            "package_status",
            "created_at",
            "updated_at",
            "proposed_paths",
            "notes",
        ):
            assert field in manifest
        assert manifest["package_status"] == "pending"
        assert len(manifest["proposed_paths"]) >= 1
        for proposed in manifest["proposed_paths"]:
            assert (ROOT / proposed).exists()

        claim_lines = (review_dir / "claim-ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(claim_lines) >= 1
        first_claim = yaml.safe_load(claim_lines[0])
        for field in ("claim_id", "source_id", "claim", "type", "confidence", "evidence", "touches"):
            assert field in first_claim

        contradictions = (review_dir / "contradictions.md").read_text(encoding="utf-8")
        assert "## Direct contradictions" in contradictions
        assert "## Soft tensions" in contradictions
        assert "## Compared wiki evidence" in contradictions

        review_notes = (review_dir / "review-notes.md").read_text(encoding="utf-8")
        assert "## Proposed changes summary" in review_notes
        assert "## Proposed wiki files" in review_notes

        wiki_after = {path: _read(path) for path in (ROOT / "wiki").rglob("*.md")}
        assert wiki_before == wiki_after
    finally:
        if source_dir.exists():
            shutil.rmtree(source_dir)
        if review_dir.exists():
            shutil.rmtree(review_dir)
