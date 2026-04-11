import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.frontmatter import dump_markdown_with_frontmatter, parse_markdown_with_frontmatter
from scripts.lib.logging import append_wiki_log
from scripts.lib.paths import ROOT, WIKI_DIR
from scripts.lib.time import utc_now_iso8601
from scripts.lib.validation import load_yaml, validate_review_package


def _target_wiki_path(review_dir: Path, proposed_path: str) -> Path:
    proposed_abs = (ROOT / proposed_path).resolve()
    proposed_root = (review_dir / "proposed" / "wiki").resolve()
    if not str(proposed_abs).startswith(str(proposed_root)):
        raise ValueError(f"proposed path outside review proposed/wiki: {proposed_path}")
    rel = proposed_abs.relative_to(proposed_root)
    return WIKI_DIR / rel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--allow-overwrite", action="store_true")
    args = parser.parse_args()

    review_dir = ROOT / "staging" / "reviews" / args.review_id
    if not review_dir.exists():
        raise SystemExit(f"review directory not found: {review_dir}")

    review_errors = validate_review_package(review_dir)
    if review_errors:
        raise SystemExit("review package invalid:\n" + "\n".join(review_errors))

    manifest_path = review_dir / "manifest.yaml"
    manifest = load_yaml(manifest_path)
    package_status = manifest["package_status"]
    if package_status not in {"approved", "approved_with_edits"}:
        raise SystemExit(
            f"review package status must be approved or approved_with_edits; got {package_status}"
        )

    proposed_paths = manifest["proposed_paths"]
    now = utc_now_iso8601()
    overwritten: list[str] = []
    promoted: list[str] = []
    for proposed_path in proposed_paths:
        source_path = ROOT / proposed_path
        target_path = _target_wiki_path(review_dir, proposed_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        exists = target_path.exists()
        if exists and not args.allow_overwrite:
            raise SystemExit(
                f"target file exists (refusing overwrite): {target_path.relative_to(ROOT)}. "
                "Re-run with --allow-overwrite."
            )

        doc = parse_markdown_with_frontmatter(source_path.read_text(encoding="utf-8"))
        doc.frontmatter["review_status"] = "approved"
        doc.frontmatter["updated_at"] = now
        target_path.write_text(
            dump_markdown_with_frontmatter(doc.frontmatter, doc.body),
            encoding="utf-8",
        )
        promoted.append(str(target_path.relative_to(ROOT)))
        if exists:
            overwritten.append(str(target_path.relative_to(ROOT)))

    manifest["updated_at"] = now
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    log_lines = [
        f"promoted review_id={manifest['review_id']} source_id={manifest['source_id']}",
        f"package_status={package_status}",
        f"files={len(promoted)}",
    ]
    for path in promoted:
        log_lines.append(f"promoted {path}")
    for path in overwritten:
        log_lines.append(f"overwrite {path}")
    append_wiki_log(ROOT / "wiki" / "log.md", "promote", log_lines)

    print(f"promoted review: {manifest['review_id']}")
    print(f"files promoted: {len(promoted)}")
    print(f"overwrites: {len(overwritten)}")


if __name__ == "__main__":
    main()
