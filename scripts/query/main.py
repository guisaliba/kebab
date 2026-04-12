import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.querying import (
    SearchHit,
    calibrated_raw_min_score,
    collect_source_markers,
    explain_payload_json,
    index_status,
    search_raw_chunks,
    search_wiki,
    should_use_raw_fallback,
)


def _summarize_hit(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if content.startswith("---\n") and "\n---\n" in content:
        content = content.split("\n---\n", 1)[1]
    preview = ""
    for line in content.splitlines():
        if line.strip():
            preview = line.strip()
            break
    return preview[:220]


def _print_index_status(status: dict[str, object], include_warning: bool = True) -> None:
    corpus = status.get("corpus_type", "unknown")
    state = status.get("status", "unknown")
    if state == "missing":
        print(f"index_status[{corpus}]: missing (run scripts/index/main.py --target {corpus} --rebuild)")
        return
    if state == "invalid":
        print(f"index_status[{corpus}]: invalid ({status.get('error', 'unknown error')})")
        return
    indexed_at = status.get("indexed_at", "")
    stale = bool(status.get("is_stale", False))
    stale_count = int(status.get("stale_document_count", 0))
    missing_count = int(status.get("missing_document_count", 0))
    detailed = bool(status.get("used_detailed_scan", False))
    print(f"index_status[{corpus}]: indexed_at={indexed_at} stale={stale} detailed_scan={detailed}")
    if include_warning and stale:
        print(
            f"WARNING: stale {corpus} index detected "
            f"(stale_documents={stale_count}, missing_documents={missing_count}). "
            f"Rebuild with: python scripts/index/main.py --target {corpus} --rebuild"
        )


def _print_hits(hits: list[SearchHit], top_k: int, explain_ranking: bool, explain_format: str) -> None:
    for hit in hits[:top_k]:
        rel = hit.path.relative_to(ROOT)
        preview = _summarize_hit(hit.path)
        citations = collect_source_markers(hit.path.read_text(encoding="utf-8"))
        print(f"- {rel} (score={hit.score:.3f}) {preview}")
        for citation in citations[:2]:
            print(f"  {citation}")
        if explain_ranking:
            if explain_format == "json":
                print(f"  explain_json: {explain_payload_json(hit)}")
            else:
                print(f"  explain: {hit.explain_text()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--wiki-only", action="store_true")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.8)
    parser.add_argument("--explain-ranking", action="store_true")
    parser.add_argument("--explain-ranking-format", choices=["text", "json"], default="text")
    parser.add_argument("--fuzzy", action="store_true")
    parser.add_argument("--disable-aliases", action="store_true")
    parser.add_argument("--include-navigation", action="store_true")
    parser.add_argument("--verbose-index-status", action="store_true")
    parser.add_argument(
        "--fuzzy-mode",
        choices=["off", "explicit", "auto-on-zero"],
        default="off",
    )
    args = parser.parse_args()

    wiki_index = index_status("wiki", verbose=args.verbose_index_status)
    _print_index_status(wiki_index)

    use_fuzzy = args.fuzzy or args.fuzzy_mode == "explicit"
    use_aliases = not args.disable_aliases
    wiki_hits = search_wiki(
        args.question,
        min_score=args.min_score,
        fuzzy=use_fuzzy,
        include_navigation=args.include_navigation,
        use_aliases=use_aliases,
    )
    if not wiki_hits and args.fuzzy_mode == "auto-on-zero":
        wiki_hits = search_wiki(
            args.question,
            min_score=args.min_score,
            fuzzy=True,
            include_navigation=args.include_navigation,
            use_aliases=use_aliases,
        )

    if wiki_hits and not should_use_raw_fallback(args.question, wiki_hits):
        print("consulted_layers: wiki")
        print("answer:")
        _print_hits(
            wiki_hits,
            top_k=args.top_k,
            explain_ranking=args.explain_ranking,
            explain_format=args.explain_ranking_format,
        )
        return

    if args.wiki_only:
        print("consulted_layers: wiki")
        print("no wiki matches found; raw fallback disabled via --wiki-only")
        return

    raw_index = index_status("raw", verbose=args.verbose_index_status)
    _print_index_status(raw_index)

    raw_hits = search_raw_chunks(
        args.question,
        min_score=calibrated_raw_min_score(args.question, args.min_score),
        fuzzy=use_fuzzy or args.fuzzy_mode == "auto-on-zero",
        use_aliases=use_aliases,
    )
    print("consulted_layers: wiki+raw")
    if not raw_hits:
        print("no evidence found in wiki or raw chunks")
        return
    print("answer:")
    for hit in raw_hits[: args.top_k]:
        rel = hit.path.relative_to(ROOT)
        preview = _summarize_hit(hit.path)
        source_id = next((part for part in hit.path.parts if part.startswith("SRC-")), "unknown-source")
        print(f"- {rel} (score={hit.score:.3f}) {preview}")
        print(f"  [Sources: {source_id} {hit.path.name}]")
        if args.explain_ranking:
            if args.explain_ranking_format == "json":
                print(f"  explain_json: {explain_payload_json(hit)}")
            else:
                print(f"  explain: {hit.explain_text()}")


if __name__ == "__main__":
    main()
