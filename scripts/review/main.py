import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.paths import ROOT
from scripts.lib.validation import validate_review_package


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-id", required=True)
    args = parser.parse_args()

    review_dir = ROOT / "staging" / "reviews" / args.review_id
    if not review_dir.exists():
        raise SystemExit(f"review directory not found: {review_dir}")

    errors = validate_review_package(review_dir)
    if errors:
        print(f"review invalid: {args.review_id}")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print(f"review valid: {args.review_id}")
    print(f"artifacts checked in {review_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
