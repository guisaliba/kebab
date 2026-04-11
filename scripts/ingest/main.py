import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.chunking import chunk_text, load_chunk_input, write_chunks
from scripts.lib.ids import validate_review_id
from scripts.lib.paths import RAW_DIR, ROOT
from scripts.lib.review_package import create_review_package, generate_review_id, upsert_registry_entry
from scripts.lib.validation import load_yaml, validate_manifest_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--review-id")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-unit", choices=["chars", "paragraphs"], default="chars")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    if not source_dir.is_absolute():
        source_dir = ROOT / source_dir
    source_dir = source_dir.resolve()
    manifest_path = source_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise SystemExit(f"missing manifest: {manifest_path}")

    manifest = load_yaml(manifest_path)
    manifest_errors = validate_manifest_source(manifest, manifest_path)
    if manifest_errors:
        raise SystemExit("\n".join(manifest_errors))

    source_text, source_files, source_kind = load_chunk_input(source_dir)
    chunks = chunk_text(source_text, chunk_size=args.chunk_size, chunk_unit=args.chunk_unit)
    written_chunks = write_chunks(source_dir, chunks)

    registry_path = RAW_DIR / "registry.yaml"
    source_rel_path = str(source_dir.relative_to(ROOT))
    upsert_registry_entry(registry_path, manifest, source_rel_path)

    review_id = args.review_id or generate_review_id()
    if not validate_review_id(review_id):
        raise SystemExit(f"invalid review id: {review_id}")
    review_dir = create_review_package(
        review_id=review_id,
        source_manifest=manifest,
        notes=f"Generated from {source_kind} inputs: {', '.join(path.name for path in source_files)}",
        chunk_paths=written_chunks,
    )

    print(f"ingest ok: {source_dir.relative_to(ROOT)}")
    print(f"chunk source: {source_kind} ({len(source_files)} file(s))")
    print(f"chunks written: {len(written_chunks)}")
    print(f"registry updated: {registry_path.relative_to(ROOT)}")
    print(f"review package: {review_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
