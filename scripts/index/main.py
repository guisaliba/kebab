import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.indexing import write_index
from scripts.lib.paths import INDEX_DIR


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["wiki", "raw", "all"], default="all")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve() if args.output_dir else INDEX_DIR
    targets = ["wiki", "raw"] if args.target == "all" else [args.target]

    if args.rebuild:
        for target in targets:
            index_name = f"{target}.index.json"
            index_path = output_dir / index_name
            if index_path.exists():
                index_path.unlink()

    for target in targets:
        path = write_index(target, output_dir=output_dir)
        print(f"indexed {target}: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
