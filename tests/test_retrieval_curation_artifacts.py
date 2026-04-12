import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.lib.paths import ROOT


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_review_manifest(review_dir: Path, package_status: str, proposed_path: str) -> None:
    payload = {
        "review_id": review_dir.name,
        "source_id": "SRC-2099-9003",
        "package_status": package_status,
        "created_at": "2026-04-09T00:00:00Z",
        "updated_at": "2026-04-09T00:00:00Z",
        "proposed_paths": [proposed_path],
        "notes": "retrieval-assist test",
    }
    (review_dir / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _build_review_fixture(review_id: str) -> tuple[Path, Path]:
    review_dir = ROOT / "staging" / "reviews" / review_id
    proposed_rel = Path(f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md")
    proposed_path = ROOT / proposed_rel
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    proposed_path.parent.mkdir(parents=True, exist_ok=True)

    source_page = ROOT / "wiki" / "platforms" / "meta-ads.md"
    proposed_path.write_text(source_page.read_text(encoding="utf-8"), encoding="utf-8")
    (review_dir / "source-summary.md").write_text("# Source Summary\n", encoding="utf-8")
    (review_dir / "contradictions.md").write_text("# Contradictions\n", encoding="utf-8")
    (review_dir / "open-questions.md").write_text("# Open Questions\n", encoding="utf-8")
    (review_dir / "claim-ledger.jsonl").write_text(
        '{"claim_id":"CLM-1","source_id":"SRC-2099-9003","claim":"x"}\n',
        encoding="utf-8",
    )
    (review_dir / "decision.md").write_text("# Decision\n\nStatus: pending\n", encoding="utf-8")
    _write_review_manifest(review_dir, "pending", str(proposed_rel))
    return review_dir, proposed_path


def test_curate_generates_retrieval_assist_artifacts_and_never_writes_wiki() -> None:
    review_id = "REV-2099-9003"
    review_dir, _ = _build_review_fixture(review_id)
    wiki_before = {path: _read(path) for path in (ROOT / "wiki").rglob("*.md")}
    try:
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout

        assist_dir = review_dir / "retrieval-assist"
        manifest = yaml.safe_load((assist_dir / "manifest.yaml").read_text(encoding="utf-8"))
        assert manifest["review_id"] == review_id
        assert manifest["proposal_count"] >= 1

        proposals = [
            json.loads(line)
            for line in (assist_dir / "proposals.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert proposals
        proposal = proposals[0]
        assert f"staging/reviews/{review_id}/proposed/wiki/" in proposal["target_proposed_path"]
        assert proposal["intended_wiki_path"].startswith("wiki/")
        assert proposal["change_type"] in {"append_section", "update_section", "new_note_link", "conflict_flag"}

        evidence_path = assist_dir / "evidence" / f"{proposal['evidence_bundle_id']}.yaml"
        evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
        assert "grounding" in evidence
        assert isinstance(evidence["grounding"]["normalized_citations"], list)
        assert evidence["retrieval_context"]["alias_influence_class"] in {
            "alias_only",
            "fuzzy_only",
            "both_independently",
            "combined_only",
            "alias_plus_fuzzy_interaction",
            "none",
        }

        second = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert second.returncode != 0
        assert "rerun with --overwrite" in (second.stderr + second.stdout)

        overwrite = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id, "--overwrite"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert overwrite.returncode == 0, overwrite.stderr + overwrite.stdout

        wiki_after = {path: _read(path) for path in (ROOT / "wiki").rglob("*.md")}
        assert wiki_before == wiki_after
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
