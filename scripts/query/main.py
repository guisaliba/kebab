import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.querying import SearchHit, collect_source_markers, search_raw_chunks, search_wiki


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


def _print_hits(hits: list[SearchHit], top_k: int, explain_ranking: bool) -> None:
    for hit in hits[:top_k]:
        rel = hit.path.relative_to(ROOT)
        preview = _summarize_hit(hit.path)
        citations = collect_source_markers(hit.path.read_text(encoding="utf-8"))
        print(f"- {rel} (score={hit.score:.3f}) {preview}")
        for citation in citations[:2]:
            print(f"  {citation}")
        if explain_ranking:
            print(f"  ranking: bm25_total={hit.bm25_total:.3f} contributions={hit.contributions}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    parser.add_argument("--wiki-only", action="store_true")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.8)
    parser.add_argument("--explain-ranking", action="store_true")
    parser.add_argument("--fuzzy", action="store_true")
    parser.add_argument(
        "--fuzzy-mode",
        choices=["off", "explicit", "auto-on-zero"],
        default="off",
    )
    args = parser.parse_args()

    use_fuzzy = args.fuzzy or args.fuzzy_mode == "explicit"
    wiki_hits = search_wiki(
        args.question,
        min_score=args.min_score,
        fuzzy=use_fuzzy,
    )
    if not wiki_hits and args.fuzzy_mode == "auto-on-zero":
        wiki_hits = search_wiki(
            args.question,
            min_score=args.min_score,
            fuzzy=True,
        )

    if wiki_hits:
        print("consulted_layers: wiki")
        print("answer:")
        _print_hits(wiki_hits, top_k=args.top_k, explain_ranking=args.explain_ranking)
        return

    if args.wiki_only:
        print("consulted_layers: wiki")
        print("no wiki matches found; raw fallback disabled via --wiki-only")
        return

    raw_hits = search_raw_chunks(
        args.question,
        min_score=max(args.min_score * 0.75, 0.4),
        fuzzy=use_fuzzy or args.fuzzy_mode == "auto-on-zero",
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
            print(f"  ranking: bm25_total={hit.bm25_total:.3f} contributions={hit.contributions}")


if __name__ == "__main__":
    main()
