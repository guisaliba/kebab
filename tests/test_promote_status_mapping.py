import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.lib.paths import ROOT


def _write_review_manifest(review_dir: Path, package_status: str, proposed_path: str) -> None:
    payload = {
        "review_id": review_dir.name,
        "source_id": "SRC-2026-0001",
        "package_status": package_status,
        "created_at": "2026-04-09T00:00:00Z",
        "updated_at": "2026-04-09T00:00:00Z",
        "proposed_paths": [proposed_path],
        "notes": "test promote",
    }
    (review_dir / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def test_promote_overwrite_policy_and_status_mapping() -> None:
    review_id = "REV-2099-9002"
    review_dir = ROOT / "staging" / "reviews" / review_id
    target_rel = Path("wiki/platforms/meta-ads.md")
    proposed_rel = Path(f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md")
    target_path = ROOT / target_rel
    proposed_path = ROOT / proposed_rel

    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    proposed_path.parent.mkdir(parents=True, exist_ok=True)

    original_target = target_path.read_text(encoding="utf-8")
    original_log = (ROOT / "wiki" / "log.md").read_text(encoding="utf-8")
    proposed_path.write_text(
        original_target.replace("review_status: approved", "review_status: proposed"),
        encoding="utf-8",
    )
    (review_dir / "source-summary.md").write_text("# Source Summary\n", encoding="utf-8")
    (review_dir / "contradictions.md").write_text("# Contradictions\n", encoding="utf-8")
    (review_dir / "open-questions.md").write_text("# Open Questions\n", encoding="utf-8")
    (review_dir / "claim-ledger.jsonl").write_text(
        '{"claim_id":"CLM-1","source_id":"SRC-2026-0001","claim":"x"}\n',
        encoding="utf-8",
    )
    (review_dir / "decision.md").write_text("# Decision\n\nStatus: approved\n", encoding="utf-8")
    _write_review_manifest(review_dir, "approved", str(proposed_rel))

    try:
        denied = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "promote" / "main.py"),
                "--review-id",
                review_id,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert denied.returncode != 0
        assert "refusing overwrite" in (denied.stderr + denied.stdout)

        allowed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "promote" / "main.py"),
                "--review-id",
                review_id,
                "--allow-overwrite",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert allowed.returncode == 0, allowed.stderr + allowed.stdout

        target_content = target_path.read_text(encoding="utf-8")
        assert "review_status: approved" in target_content

        log_content = (ROOT / "wiki" / "log.md").read_text(encoding="utf-8")
        assert "overwrite wiki/platforms/meta-ads.md" in log_content
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
        target_path.write_text(original_target, encoding="utf-8")
        (ROOT / "wiki" / "log.md").write_text(original_log, encoding="utf-8")
