import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.chunking import chunk_text, load_chunk_input, write_chunks
from scripts.lib.ids import validate_review_id
from scripts.lib.ingestion_adapters import IngestionError, prepare_ingest
from scripts.lib.paths import RAW_DIR, ROOT
from scripts.lib.review_package import create_review_package, generate_review_id, upsert_registry_entry
from scripts.lib.validation import load_yaml, validate_manifest_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--review-id")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-unit", choices=["chars", "paragraphs"], default="chars")
    parser.add_argument(
        "--skip-adapters",
        action="store_true",
        help="Do not run ffmpeg/PDF/OCR adapters; require transcript/*.md or extracted/*.txt up front.",
    )
    parser.add_argument(
        "--no-check-tools",
        action="store_true",
        help="Skip local tool availability checks before invoking ffmpeg (still must exist on PATH).",
    )
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

    try:
        prepared = prepare_ingest(
            source_dir,
            manifest,
            skip_adapters=args.skip_adapters,
            check_tools=not args.no_check_tools,
        )
    except IngestionError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        source_text, source_files, source_kind = load_chunk_input(source_dir)
    except ValueError as exc:
        extra = ""
        if prepared.adapter_name == "audio":
            extra = (
                " Audio was extracted but there is still no text for chunking. "
                "Add transcript/*.md or extracted/*.txt, or extend the transcription seam."
            )
        raise SystemExit(f"{exc}{extra}") from exc

    ingest_notes = [
        f"Adapter: {prepared.adapter_name}",
        f"Chunk input: {source_kind} ({len(source_files)} file(s))",
    ]
    ingest_notes.extend(prepared.notes)
    if prepared.derived_files:
        ingest_notes.append(
            "Derived: " + ", ".join(str(p.relative_to(source_dir)) for p in prepared.derived_files)
        )
    notes_block = "; ".join(ingest_notes)

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
        notes=notes_block,
        chunk_paths=written_chunks,
    )

    print(f"ingest ok: {source_dir.relative_to(ROOT)}")
    print(f"adapter: {prepared.adapter_name}")
    print(f"chunk source: {source_kind} ({len(source_files)} file(s))")
    print(f"chunks written: {len(written_chunks)}")
    print(f"registry updated: {registry_path.relative_to(ROOT)}")
    print(f"review package: {review_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
