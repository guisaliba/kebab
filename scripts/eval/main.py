import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.querying import search_raw_chunks, search_wiki

SUPPORTED_CATEGORIES = (
    "wiki-only",
    "raw-fallback",
    "fuzzy-enabled",
    "canonical-vs-source-note",
    "mixed-ptbr-en",
)
_SUPPORTED_CATEGORIES_SET = frozenset(SUPPORTED_CATEGORIES)


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
    if len(queries) < 20:
        raise SystemExit("dataset must contain at least 20 queries")

    category_counts = {category: 0 for category in SUPPORTED_CATEGORIES}
    adversarial_counts = {category: 0 for category in SUPPORTED_CATEGORIES}
    for query in queries:
        categories = query.get("categories")
        if not isinstance(categories, list) or not categories:
            raise SystemExit(f"query {query.get('id')} missing required categories list")
        invalid = [category for category in categories if category not in _SUPPORTED_CATEGORIES_SET]
        if invalid:
            raise SystemExit(f"query {query.get('id')} has unsupported categories: {invalid}")
        for category in categories:
            category_counts[category] += 1
            if bool(query.get("adversarial", False)):
                adversarial_counts[category] += 1
    for category in SUPPORTED_CATEGORIES:
        if category_counts[category] < 6:
            raise SystemExit(f"dataset requires at least 6 cases for category '{category}'")
        if adversarial_counts[category] < 2:
            raise SystemExit(f"dataset requires at least 2 adversarial cases for category '{category}'")
    return payload


def _run_single_query(question: str, fuzzy: bool) -> dict[str, Any]:
    wiki_hits = search_wiki(question, min_score=0.8, fuzzy=fuzzy, include_navigation=False)
    if wiki_hits:
        return {
            "consulted_layers": "wiki",
            "wiki_paths": [str(hit.path.relative_to(ROOT)) for hit in wiki_hits[:3]],
            "raw_paths": [],
            "winner_trace": wiki_hits[0].explain_payload(),
        }
    raw_hits = search_raw_chunks(question, min_score=0.6, fuzzy=fuzzy)
    return {
        "consulted_layers": "wiki+raw",
        "wiki_paths": [],
        "raw_paths": [str(hit.path.relative_to(ROOT)) for hit in raw_hits[:3]],
        "winner_trace": raw_hits[0].explain_payload() if raw_hits else None,
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
    if source_note_index is None:
        return True
    if canonical_index is None:
        return False
    return canonical_index < source_note_index


def _expected_object(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "top1": case.get("expected_top1_path"),
        "top3": case.get("expected_top3_paths", []),
        "expect_raw_fallback": case.get("expect_raw_fallback"),
        "expect_canonical_over_source_note": case.get("expect_canonical_over_source_note", False),
        "fuzzy_expected_help": case.get("fuzzy_expected_help"),
    }


def _actual_object(result: dict[str, Any]) -> dict[str, Any]:
    all_paths = result["wiki_paths"] + result["raw_paths"]
    return {
        "consulted_layers": result["consulted_layers"],
        "topk_paths": all_paths[:3],
        "fallback_observed": result["consulted_layers"] == "wiki+raw" and len(result["raw_paths"]) > 0,
        "winner_path": all_paths[0] if all_paths else None,
    }


def _fuzzy_influence(pass_off: bool, pass_on: bool) -> str:
    if (not pass_off) and pass_on:
        return "help"
    if pass_off and (not pass_on):
        return "harm"
    return "neutral"


def _collect_failure_codes(case: dict[str, Any], result_off: dict[str, Any], result_on: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    all_paths = (result_off["wiki_paths"] + result_off["raw_paths"])[:3]
    expected_top1 = case.get("expected_top1_path")
    expected_top3 = case.get("expected_top3_paths", [])

    if expected_top1 and (not all_paths or all_paths[0] != expected_top1):
        codes.append("TOP1_MISS")
    if expected_top3 and not bool(set(all_paths) & set(expected_top3)):
        codes.append("TOP3_MISS")
    if case.get("expect_canonical_over_source_note", False) and not _canonical_vs_source_note_ok(case, result_off):
        codes.append("CANONICAL_ORDER_MISS")
    if "expect_raw_fallback" in case:
        expected = bool(case.get("expect_raw_fallback", False))
        observed = result_off["consulted_layers"] == "wiki+raw" and len(result_off["raw_paths"]) > 0
        if expected != observed:
            codes.append("RAW_FALLBACK_MISS")
    if "fuzzy_expected_help" in case:
        pass_off = _criterion_pass(case, result_off)
        pass_on = _criterion_pass(case, result_on)
        influence = _fuzzy_influence(pass_off, pass_on)
        expected_help = bool(case.get("fuzzy_expected_help", False))
        if expected_help and influence != "help":
            codes.append("FUZZY_HELP_EXPECTED")
        if (not expected_help) and influence == "harm":
            codes.append("FUZZY_HARM_UNEXPECTED")
    return codes


def _aggregate_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
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

    for item in cases:
        case = item["case"]
        result_off = item["result_off"]
        result_on = item["result_on"]

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
            influence = _fuzzy_influence(pass_off, pass_on)
            if influence == "help":
                fuzzy_help += 1
            elif influence == "harm":
                fuzzy_harm += 1

    def _rate(ok: int, total: int) -> float:
        return round((ok / total), 6) if total else 0.0

    return {
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
    }


def evaluate(dataset: dict[str, Any]) -> dict[str, Any]:
    queries: list[dict[str, Any]] = dataset["queries"]
    evaluated: list[dict[str, Any]] = []
    metric_inputs: list[dict[str, Any]] = []

    for case in queries:
        result_off = _run_single_query(case["query"], fuzzy=False)
        result_on = _run_single_query(case["query"], fuzzy=True)
        pass_off = _criterion_pass(case, result_off)
        pass_on = _criterion_pass(case, result_on)
        failure_codes = _collect_failure_codes(case, result_off, result_on)
        fuzzy_influence = _fuzzy_influence(pass_off, pass_on)

        metric_inputs.append({"case": case, "result_off": result_off, "result_on": result_on})

        evaluated.append(
            {
                "id": case["id"],
                "query": case["query"],
                "categories": case["categories"],
                "adversarial": bool(case.get("adversarial", False)),
                "expected": _expected_object(case),
                "actual_fuzzy_off": _actual_object(result_off),
                "actual_fuzzy_on": _actual_object(result_on),
                "fuzzy_influence": fuzzy_influence,
                "winner_trace": {
                    "fuzzy_off": result_off.get("winner_trace"),
                    "fuzzy_on": result_on.get("winner_trace"),
                },
                "pass_fail_reasons": failure_codes,
                "result_fuzzy_off": result_off,
                "result_fuzzy_on": result_on,
            }
        )

    global_metrics = _aggregate_metrics(metric_inputs)
    by_category: dict[str, Any] = {}
    worst_failures: dict[str, list[dict[str, Any]]] = {category: [] for category in SUPPORTED_CATEGORIES}
    for category in SUPPORTED_CATEGORIES:
        subset = [item for item in metric_inputs if category in item["case"]["categories"]]
        by_category[category] = _aggregate_metrics(subset)
    for item in evaluated:
        if item["pass_fail_reasons"]:
            for category in item["categories"]:
                worst_failures[category].append(
                    {
                        "id": item["id"],
                        "query": item["query"],
                        "failure_reason_codes": item["pass_fail_reasons"],
                    }
                )
    def _failure_severity(failure: dict[str, Any]) -> tuple[int, int]:
        codes = failure["failure_reason_codes"]
        return (1 if "TOP1_MISS" in codes else 0, len(codes))

    worst_failures = {
        category: sorted(failures, key=_failure_severity, reverse=True)[:5]
        for category, failures in worst_failures.items()
    }

    return {
        "dataset_metadata": dataset["metadata"],
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {
            "global": global_metrics,
            "by_category": by_category,
        },
        "worst_failures": {"by_category": worst_failures},
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
    filename = f"retrieval-eval-{report['evaluated_at'].replace(':', '').replace('-', '')}-{os.getpid()}.json"
    out_path = output_dir / filename
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"eval_report: {out_path.relative_to(ROOT)}")
    global_metrics = report["metrics"]["global"]
    print(f"top1_correctness: {global_metrics['top1_correctness']}")
    print(f"top3_coverage: {global_metrics['top3_coverage']}")
    print(f"canonical_vs_source_note_correctness: {global_metrics['canonical_vs_source_note_correctness']}")
    print(f"raw_fallback_correctness: {global_metrics['raw_fallback_correctness']}")
    print(f"fuzzy_help_vs_harm: {global_metrics['fuzzy_help_vs_harm']}")


if __name__ == "__main__":
    main()
