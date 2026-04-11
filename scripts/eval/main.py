import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.querying import search_raw_chunks, search_wiki


def _load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required_meta = {"dataset_version", "dataset_scope", "updated_at"}
    metadata = payload.get("metadata", {})
    missing_meta = required_meta - set(metadata.keys())
    if missing_meta:
        raise SystemExit(f"dataset metadata missing required keys: {sorted(missing_meta)}")
    queries = payload.get("queries", [])
    if not isinstance(queries, list):
        raise SystemExit("dataset queries must be a list")
    return payload


def _run_single_query(question: str, fuzzy: bool) -> dict[str, Any]:
    wiki_hits = search_wiki(question, min_score=0.8, fuzzy=fuzzy, include_navigation=False)
    if wiki_hits:
        return {
            "consulted_layers": "wiki",
            "wiki_paths": [str(hit.path.relative_to(ROOT)) for hit in wiki_hits[:3]],
            "raw_paths": [],
        }
    raw_hits = search_raw_chunks(question, min_score=0.6, fuzzy=fuzzy)
    return {
        "consulted_layers": "wiki+raw",
        "wiki_paths": [],
        "raw_paths": [str(hit.path.relative_to(ROOT)) for hit in raw_hits[:3]],
    }


def _criterion_pass(case: dict[str, Any], result: dict[str, Any]) -> bool:
    all_paths = result["wiki_paths"] + result["raw_paths"]
    expected_top1 = case.get("expected_top1_path")
    expected_top3 = case.get("expected_top3_paths", [])
    if expected_top1:
        return bool(all_paths) and all_paths[0] == expected_top1
    if expected_top3:
        return bool(set(all_paths[:3]) & set(expected_top3))
    return bool(all_paths)


def _canonical_vs_source_note_ok(case: dict[str, Any], result: dict[str, Any]) -> bool:
    if not case.get("expect_canonical_over_source_note", False):
        return True
    paths = result["wiki_paths"]
    canonical_index = None
    source_note_index = None
    for idx, path in enumerate(paths):
        if "/source-notes/" in path:
            source_note_index = idx if source_note_index is None else source_note_index
        else:
            canonical_index = idx if canonical_index is None else canonical_index
    if canonical_index is None or source_note_index is None:
        return True
    return canonical_index < source_note_index


def evaluate(dataset: dict[str, Any]) -> dict[str, Any]:
    queries: list[dict[str, Any]] = dataset["queries"]
    evaluated: list[dict[str, Any]] = []

    top1_total = 0
    top1_ok = 0
    top3_total = 0
    top3_ok = 0
    canonical_total = 0
    canonical_ok = 0
    fallback_total = 0
    fallback_ok = 0
    fuzzy_total = 0
    fuzzy_help = 0
    fuzzy_harm = 0

    for case in queries:
        result_off = _run_single_query(case["query"], fuzzy=False)
        result_on = _run_single_query(case["query"], fuzzy=True)

        if case.get("expected_top1_path"):
            top1_total += 1
            if _criterion_pass({"expected_top1_path": case["expected_top1_path"]}, result_off):
                top1_ok += 1
        expected_top3 = case.get("expected_top3_paths", [])
        if expected_top3:
            top3_total += 1
            if bool(set((result_off["wiki_paths"] + result_off["raw_paths"])[:3]) & set(expected_top3)):
                top3_ok += 1

        if case.get("expect_canonical_over_source_note", False):
            canonical_total += 1
            if _canonical_vs_source_note_ok(case, result_off):
                canonical_ok += 1

        if "expect_raw_fallback" in case:
            fallback_total += 1
            expected = bool(case.get("expect_raw_fallback", False))
            observed = result_off["consulted_layers"] == "wiki+raw" and len(result_off["raw_paths"]) > 0
            if (expected and observed) or (not expected and not observed):
                fallback_ok += 1

        if "fuzzy_expected_help" in case:
            fuzzy_total += 1
            pass_off = _criterion_pass(case, result_off)
            pass_on = _criterion_pass(case, result_on)
            if pass_on and not pass_off:
                fuzzy_help += 1
            if pass_off and not pass_on:
                fuzzy_harm += 1

        evaluated.append(
            {
                "id": case["id"],
                "query": case["query"],
                "result_fuzzy_off": result_off,
                "result_fuzzy_on": result_on,
            }
        )

    def _rate(ok: int, total: int) -> float:
        return round((ok / total), 6) if total else 0.0

    return {
        "dataset_metadata": dataset["metadata"],
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {
            "top1_correctness": {"ok": top1_ok, "total": top1_total, "rate": _rate(top1_ok, top1_total)},
            "top3_coverage": {"ok": top3_ok, "total": top3_total, "rate": _rate(top3_ok, top3_total)},
            "canonical_vs_source_note_correctness": {
                "ok": canonical_ok,
                "total": canonical_total,
                "rate": _rate(canonical_ok, canonical_total),
            },
            "raw_fallback_correctness": {
                "ok": fallback_ok,
                "total": fallback_total,
                "rate": _rate(fallback_ok, fallback_total),
            },
            "fuzzy_help_vs_harm": {
                "help_count": fuzzy_help,
                "harm_count": fuzzy_harm,
                "total_cases": fuzzy_total,
            },
        },
        "queries": evaluated,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        default="tests/fixtures/retrieval_golden/queries.json",
        help="Path to golden dataset JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="exports/evals",
        help="Evaluation output directory (writes only under exports/evals by policy).",
    )
    args = parser.parse_args()

    output_dir = (ROOT / args.output_dir).resolve()
    exports_evals = (ROOT / "exports" / "evals").resolve()
    if output_dir != exports_evals and not str(output_dir).startswith(str(exports_evals) + "/"):
        raise SystemExit("eval output-dir must be exports/evals or a subdirectory")

    dataset_path = (ROOT / args.dataset).resolve()
    dataset = _load_dataset(dataset_path)
    report = evaluate(dataset)

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"retrieval-eval-{report['evaluated_at'].replace(':', '').replace('-', '')}.json"
    out_path = output_dir / filename
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"eval_report: {out_path.relative_to(ROOT)}")
    print(f"top1_correctness: {report['metrics']['top1_correctness']}")
    print(f"top3_coverage: {report['metrics']['top3_coverage']}")
    print(f"canonical_vs_source_note_correctness: {report['metrics']['canonical_vs_source_note_correctness']}")
    print(f"raw_fallback_correctness: {report['metrics']['raw_fallback_correctness']}")
    print(f"fuzzy_help_vs_harm: {report['metrics']['fuzzy_help_vs_harm']}")


if __name__ == "__main__":
    main()
