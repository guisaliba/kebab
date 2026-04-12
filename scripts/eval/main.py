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

from scripts.lib.querying import (
    calibrated_raw_min_score,
    search_raw_chunks,
    search_wiki,
    should_use_raw_fallback,
)
from scripts.lib.retrieval_curation import CONFIDENCE_MODEL_CONSTANTS

SUPPORTED_CATEGORIES = (
    "wiki-only",
    "raw-fallback",
    "fuzzy-enabled",
    "canonical-vs-source-note",
    "mixed-ptbr-en",
)
_SUPPORTED_CATEGORIES_SET = frozenset(SUPPORTED_CATEGORIES)
NORMALIZED_REVIEW_OUTCOMES = ("approve", "approve_with_edits", "reject")
REVIEW_OUTCOME_NORMALIZATION_MAP = {
    "approve": "approve",
    "approved": "approve",
    "approved_clean": "approve",
    "accept": "approve",
    "approve_with_edits": "approve_with_edits",
    "approved_with_edits": "approve_with_edits",
    "approved-edits": "approve_with_edits",
    "request_edits": "approve_with_edits",
    "revise": "approve_with_edits",
    "reject": "reject",
    "rejected": "reject",
    "decline": "reject",
}
REVIEW_ACTION_SCRUTINY = {
    "quick-approve": 0,
    "normal-review": 1,
    "deep-review": 2,
}
REVIEW_OUTCOME_REQUIRED_SCRUTINY = {
    "approve": 0,
    "approve_with_edits": 1,
    "reject": 2,
}
MATERIAL_MISMATCH_THRESHOLDS = {
    "action_alignment_rate_min": 0.75,
    "optimistic_miss_rate_max": 0.20,
    "conservative_miss_rate_max": 0.35,
}


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


def _run_single_query(question: str, fuzzy: bool, use_aliases: bool = True) -> dict[str, Any]:
    wiki_hits = search_wiki(
        question,
        min_score=0.8,
        fuzzy=fuzzy,
        include_navigation=False,
        use_aliases=use_aliases,
    )
    if wiki_hits and not should_use_raw_fallback(question, wiki_hits):
        return {
            "consulted_layers": "wiki",
            "wiki_paths": [str(hit.path.relative_to(ROOT)) for hit in wiki_hits[:3]],
            "raw_paths": [],
            "winner_trace": wiki_hits[0].explain_payload(),
        }
    raw_hits = search_raw_chunks(
        question,
        min_score=calibrated_raw_min_score(question, 0.8),
        fuzzy=fuzzy,
        use_aliases=use_aliases,
    )
    if raw_hits:
        winner_trace = raw_hits[0].explain_payload()
        return {
            "consulted_layers": "wiki+raw",
            "wiki_paths": [],
            "raw_paths": [str(hit.path.relative_to(ROOT)) for hit in raw_hits[:3]],
            "winner_trace": winner_trace,
        }
    return {
        "consulted_layers": "wiki+raw",
        "wiki_paths": [str(hit.path.relative_to(ROOT)) for hit in wiki_hits[:3]],
        "raw_paths": [],
        "winner_trace": wiki_hits[0].explain_payload() if wiki_hits else None,
    }


def _normalize_reviewer_outcome(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    token = raw_value.strip().lower().replace(" ", "_")
    return REVIEW_OUTCOME_NORMALIZATION_MAP.get(token)


def _action_alignment(predicted_action: str, normalized_outcome: str) -> dict[str, Any]:
    predicted_level = REVIEW_ACTION_SCRUTINY.get(predicted_action)
    outcome_level = REVIEW_OUTCOME_REQUIRED_SCRUTINY.get(normalized_outcome)
    if predicted_level is None or outcome_level is None:
        return {"aligned": False, "direction": "unknown"}
    if predicted_level < outcome_level:
        return {"aligned": False, "direction": "optimistic"}
    if predicted_level > outcome_level:
        return {"aligned": False, "direction": "conservative"}
    return {"aligned": True, "direction": "aligned"}


def _load_reviewer_outcomes(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SystemExit("reviewer outcomes metadata must be an object")
    for key in {"dataset_version", "dataset_scope", "updated_at", "dataset_origin"}:
        if key not in metadata:
            raise SystemExit(f"reviewer outcomes metadata missing required key: {key}")
    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, list):
        raise SystemExit("reviewer outcomes payload must include outcomes list")
    return payload


def _band_reliability(entries: list[dict[str, Any]]) -> dict[str, Any]:
    by_band: dict[str, dict[str, int]] = {
        "high": {"total": 0, "approve": 0, "approve_with_edits": 0, "reject": 0},
        "medium": {"total": 0, "approve": 0, "approve_with_edits": 0, "reject": 0},
        "low": {"total": 0, "approve": 0, "approve_with_edits": 0, "reject": 0},
    }
    for entry in entries:
        band = entry.get("predicted_confidence_band")
        outcome = entry.get("normalized_outcome")
        if band not in by_band or outcome not in NORMALIZED_REVIEW_OUTCOMES:
            continue
        by_band[band]["total"] += 1
        by_band[band][outcome] += 1

    def _rate(count: int, total: int) -> float:
        return round((count / total), 6) if total else 0.0

    report: dict[str, Any] = {}
    for band, counts in by_band.items():
        total = counts["total"]
        report[band] = {
            "count": total,
            "approve_rate": _rate(counts["approve"], total),
            "approve_with_edits_rate": _rate(counts["approve_with_edits"], total),
            "reject_rate": _rate(counts["reject"], total),
        }
    return report


def _build_calibration_report(reviewer_outcomes: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    unknown_outcome_count = 0
    for outcome in reviewer_outcomes["outcomes"]:
        if not isinstance(outcome, dict):
            continue
        normalized = _normalize_reviewer_outcome(outcome.get("actual_reviewer_decision"))
        if normalized is None:
            unknown_outcome_count += 1
            continue
        predicted_action = str(outcome.get("predicted_review_action", ""))
        predicted_band = str(outcome.get("predicted_confidence_band", ""))
        alignment = _action_alignment(predicted_action, normalized)
        entries.append(
            {
                "review_id": outcome.get("review_id"),
                "proposal_id": outcome.get("proposal_id"),
                "evidence_bundle_id": outcome.get("evidence_bundle_id"),
                "predicted_confidence_score": outcome.get("predicted_confidence_score"),
                "predicted_confidence_band": predicted_band,
                "predicted_review_action": predicted_action,
                "actual_reviewer_decision": outcome.get("actual_reviewer_decision"),
                "normalized_outcome": normalized,
                "alignment": alignment,
            }
        )

    total = len(entries)
    aligned = sum(1 for item in entries if item["alignment"]["aligned"])
    optimistic = sum(1 for item in entries if item["alignment"]["direction"] == "optimistic")
    conservative = sum(1 for item in entries if item["alignment"]["direction"] == "conservative")

    action_alignment_rate = round((aligned / total), 6) if total else 0.0
    optimistic_rate = round((optimistic / total), 6) if total else 0.0
    conservative_rate = round((conservative / total), 6) if total else 0.0
    gate = {
        "thresholds": MATERIAL_MISMATCH_THRESHOLDS,
        "triggered_checks": {
            "action_alignment_rate_below_min": action_alignment_rate < MATERIAL_MISMATCH_THRESHOLDS["action_alignment_rate_min"],
            "optimistic_miss_rate_above_max": optimistic_rate > MATERIAL_MISMATCH_THRESHOLDS["optimistic_miss_rate_max"],
            "conservative_miss_rate_above_max": conservative_rate > MATERIAL_MISMATCH_THRESHOLDS["conservative_miss_rate_max"],
        },
    }
    gate["material_mismatch_triggered"] = any(gate["triggered_checks"].values())

    def _band_from_score(score: float, thresholds: dict[str, float]) -> str:
        if score >= thresholds["high_min"]:
            return "high"
        if score >= thresholds["medium_min"]:
            return "medium"
        return "low"

    def _action_from_band(band: str) -> str:
        if band == "high":
            return "quick-approve"
        if band == "medium":
            return "normal-review"
        return "deep-review"

    def _alignment_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        item_total = len(items)
        item_aligned = sum(1 for item in items if item["alignment"]["aligned"])
        item_optimistic = sum(1 for item in items if item["alignment"]["direction"] == "optimistic")
        item_conservative = sum(1 for item in items if item["alignment"]["direction"] == "conservative")
        return {
            "aligned_count": item_aligned,
            "total": item_total,
            "rate": round((item_aligned / item_total), 6) if item_total else 0.0,
            "optimistic_count": item_optimistic,
            "optimistic_rate": round((item_optimistic / item_total), 6) if item_total else 0.0,
            "conservative_count": item_conservative,
            "conservative_rate": round((item_conservative / item_total), 6) if item_total else 0.0,
        }

    tuning: dict[str, Any] = {
        "performed": False,
        "reason": "report_only_pass",
        "constants_changed": {},
    }
    dataset_origin = str(reviewer_outcomes["metadata"].get("dataset_origin", "")).strip().lower()
    if gate["material_mismatch_triggered"]:
        if dataset_origin == "synthetic":
            tuning = {
                "performed": False,
                "reason": "mismatch_detected_but_synthetic_dataset_not_tuned",
                "constants_changed": {},
            }
        else:
            current_thresholds = CONFIDENCE_MODEL_CONSTANTS["band_thresholds"]
            candidates = []
            for high_min in (0.70, 0.75, 0.80, 0.85):
                for medium_min in (0.40, 0.45, 0.50, 0.55, 0.60):
                    if medium_min >= high_min:
                        continue
                    recalculated: list[dict[str, Any]] = []
                    for item in entries:
                        score = item.get("predicted_confidence_score")
                        if not isinstance(score, (int, float)):
                            continue
                        band = _band_from_score(float(score), {"high_min": high_min, "medium_min": medium_min})
                        action = _action_from_band(band)
                        alignment = _action_alignment(action, str(item["normalized_outcome"]))
                        recalculated.append(
                            {
                                "alignment": alignment,
                            }
                        )
                    summary = _alignment_summary(recalculated)
                    candidates.append(
                        {
                            "high_min": high_min,
                            "medium_min": medium_min,
                            "summary": summary,
                        }
                    )
            candidates.sort(
                key=lambda item: (
                    -item["summary"]["rate"],
                    item["summary"]["optimistic_rate"],
                    item["summary"]["conservative_rate"],
                )
            )
            best = candidates[0] if candidates else None
            if best is not None and (
                best["summary"]["rate"] > action_alignment_rate
                or best["summary"]["optimistic_rate"] < optimistic_rate
                or best["summary"]["conservative_rate"] < conservative_rate
            ):
                tuning = {
                    "performed": True,
                    "reason": "mismatch_detected_and_threshold_tuning_applied",
                    "constants_changed": {
                        "band_thresholds.high_min": {
                            "old": current_thresholds["high_min"],
                            "new": best["high_min"],
                        },
                        "band_thresholds.medium_min": {
                            "old": current_thresholds["medium_min"],
                            "new": best["medium_min"],
                        },
                    },
                    "before_metrics": {
                        "action_alignment_rate": action_alignment_rate,
                        "optimistic_miss_rate": optimistic_rate,
                        "conservative_miss_rate": conservative_rate,
                    },
                    "after_metrics": {
                        "action_alignment_rate": best["summary"]["rate"],
                        "optimistic_miss_rate": best["summary"]["optimistic_rate"],
                        "conservative_miss_rate": best["summary"]["conservative_rate"],
                    },
                }
            else:
                tuning = {
                    "performed": False,
                    "reason": "mismatch_detected_no_better_threshold_candidate",
                    "constants_changed": {},
                }

    return {
        "dataset_metadata": reviewer_outcomes["metadata"],
        "confidence_model_constants": CONFIDENCE_MODEL_CONSTANTS,
        "normalization": {
            "allowed_normalized_outcomes": list(NORMALIZED_REVIEW_OUTCOMES),
            "normalization_map": REVIEW_OUTCOME_NORMALIZATION_MAP,
            "unknown_excluded_count": unknown_outcome_count,
        },
        "action_alignment_criteria": {
            "quick-approve": ["approve"],
            "normal-review": ["approve", "approve_with_edits"],
            "deep-review": ["approve_with_edits", "reject"],
        },
        "metrics": {
            "evaluated_outcomes_count": total,
            "action_alignment": {
                "aligned_count": aligned,
                "total": total,
                "rate": action_alignment_rate,
            },
            "optimistic_miss": {
                "count": optimistic,
                "total": total,
                "rate": optimistic_rate,
            },
            "conservative_miss": {
                "count": conservative,
                "total": total,
                "rate": conservative_rate,
            },
            "band_reliability": _band_reliability(entries),
        },
        "material_mismatch_gate": gate,
        "tuning": tuning,
        "entries": entries,
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


def _classification_label(case: dict[str, Any], result_off: dict[str, Any], result_on: dict[str, Any]) -> str:
    expected_top1 = case.get("expected_top1_path")
    all_off = (result_off["wiki_paths"] + result_off["raw_paths"])[:3]
    all_on = (result_on["wiki_paths"] + result_on["raw_paths"])[:3]
    if not expected_top1:
        return "not_applicable"
    if all_off and all_off[0] == expected_top1:
        if "fuzzy_expected_help" in case:
            pass_off = _criterion_pass(case, result_off)
            pass_on = _criterion_pass(case, result_on)
            influence = _fuzzy_influence(pass_off, pass_on)
            if bool(case.get("fuzzy_expected_help", False)) and influence != "help" and pass_off and pass_on:
                return "expectation_mismatch_non_blocking"
        return "pass"
    if expected_top1 in all_off:
        return "retrieval_success_ranking_miss"
    if expected_top1 in all_on:
        return "fuzzy_policy_mismatch_candidate"
    return "retrieval_miss"


def _final_correctness_policy(case: dict[str, Any]) -> str:
    if "fuzzy-enabled" in case.get("categories", []):
        return "fuzzy_enabled_prefers_fuzzy_on"
    return "fuzzy_off_primary"


def _winner_path(result: dict[str, Any]) -> str | None:
    paths = result["wiki_paths"] + result["raw_paths"]
    return paths[0] if paths else None


def _alias_influence(
    baseline_no_fuzzy_no_alias: dict[str, Any],
    alias_only: dict[str, Any],
    fuzzy_only: dict[str, Any],
    fuzzy_plus_alias: dict[str, Any],
) -> dict[str, Any]:
    baseline_winner = _winner_path(baseline_no_fuzzy_no_alias)
    alias_winner = _winner_path(alias_only)
    fuzzy_winner = _winner_path(fuzzy_only)
    combined_winner = _winner_path(fuzzy_plus_alias)

    alias_changed = alias_winner != baseline_winner
    fuzzy_changed = fuzzy_winner != baseline_winner
    combined_changed = combined_winner != baseline_winner

    if combined_changed and not alias_changed and not fuzzy_changed:
        primary = "combined_only"
    elif alias_changed and fuzzy_changed:
        if combined_changed and combined_winner != alias_winner and combined_winner != fuzzy_winner:
            primary = "alias_plus_fuzzy_interaction"
        else:
            primary = "both_independently"
    elif alias_changed and not fuzzy_changed:
        primary = "alias_only"
    elif fuzzy_changed and not alias_changed:
        primary = "fuzzy_only"
    else:
        primary = "none"

    return {
        "primary_driver": primary,
        "no_fuzzy_no_alias": baseline_winner,
        "alias_only": alias_winner,
        "fuzzy_only": fuzzy_winner,
        "fuzzy_plus_alias": combined_winner,
    }


def _fuzzy_expectation_alignment(case: dict[str, Any], pass_off: bool, pass_on: bool) -> str:
    if "fuzzy_expected_help" not in case:
        return "not_applicable"
    expected_help = bool(case.get("fuzzy_expected_help", False))
    influence = _fuzzy_influence(pass_off, pass_on)
    if expected_help:
        if influence == "help":
            return "met"
        if pass_off and pass_on:
            return "mismatch_non_blocking"
        return "mismatch"
    if influence == "harm":
        return "mismatch"
    return "met"


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
        if expected_help and influence != "help" and not (pass_off and pass_on):
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


def evaluate(dataset: dict[str, Any], calibration_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    queries: list[dict[str, Any]] = dataset["queries"]
    evaluated: list[dict[str, Any]] = []
    metric_inputs: list[dict[str, Any]] = []

    for case in queries:
        result_off = _run_single_query(case["query"], fuzzy=False, use_aliases=True)
        result_on = _run_single_query(case["query"], fuzzy=True, use_aliases=True)
        pass_off = _criterion_pass(case, result_off)
        pass_on = _criterion_pass(case, result_on)
        failure_codes = _collect_failure_codes(case, result_off, result_on)
        fuzzy_influence = _fuzzy_influence(pass_off, pass_on)
        alias_influence = None
        if "fuzzy-enabled" in case.get("categories", []):
            baseline_no_alias = _run_single_query(case["query"], fuzzy=False, use_aliases=False)
            fuzzy_only = _run_single_query(case["query"], fuzzy=True, use_aliases=False)
            alias_influence = _alias_influence(baseline_no_alias, result_off, fuzzy_only, result_on)

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
                "fuzzy_expectation_alignment": _fuzzy_expectation_alignment(case, pass_off, pass_on),
                "alias_influence": alias_influence,
                "winner_trace": {
                    "fuzzy_off": result_off.get("winner_trace"),
                    "fuzzy_on": result_on.get("winner_trace"),
                },
                "final_correctness_policy_used": _final_correctness_policy(case),
                "diagnostic_classification": _classification_label(case, result_off, result_on),
                "pass_fail_reasons": failure_codes,
                "result_fuzzy_off": result_off,
                "result_fuzzy_on": result_on,
            }
        )

    global_metrics = _aggregate_metrics(metric_inputs)
    by_category: dict[str, Any] = {}
    worst_failures: dict[str, list[dict[str, Any]]] = {category: [] for category in SUPPORTED_CATEGORIES}
    classification_counts: dict[str, int] = {}
    for category in SUPPORTED_CATEGORIES:
        subset = [item for item in metric_inputs if category in item["case"]["categories"]]
        by_category[category] = _aggregate_metrics(subset)
    for item in evaluated:
        label = item.get("diagnostic_classification", "unknown")
        classification_counts[label] = classification_counts.get(label, 0) + 1
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

    report = {
        "dataset_metadata": dataset["metadata"],
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {
            "global": global_metrics,
            "by_category": by_category,
        },
        "worst_failures": {"by_category": worst_failures},
        "diagnostic_summary": {"classification_counts": classification_counts},
        "queries": evaluated,
    }
    if calibration_payload is not None:
        report["confidence_calibration"] = _build_calibration_report(calibration_payload)
    return report


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
    parser.add_argument(
        "--reviewer-outcomes",
        default="tests/fixtures/reviewer_outcomes/synthetic_outcomes.json",
        help="Path to reviewer outcome dataset for confidence calibration.",
    )
    args = parser.parse_args()

    output_dir = (ROOT / args.output_dir).resolve()
    exports_evals = (ROOT / "exports" / "evals").resolve()
    if output_dir != exports_evals and not str(output_dir).startswith(str(exports_evals) + "/"):
        raise SystemExit("eval output-dir must be exports/evals or a subdirectory")

    dataset_path = (ROOT / args.dataset).resolve()
    dataset = _load_dataset(dataset_path)
    outcomes_path = (ROOT / args.reviewer_outcomes).resolve()
    outcomes_payload = _load_reviewer_outcomes(outcomes_path)
    report = evaluate(dataset, calibration_payload=outcomes_payload)

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
    calibration = report.get("confidence_calibration", {})
    if calibration:
        calibration_metrics = calibration.get("metrics", {})
        print(f"confidence_action_alignment: {calibration_metrics.get('action_alignment')}")
        print(f"confidence_optimistic_miss: {calibration_metrics.get('optimistic_miss')}")
        print(f"confidence_conservative_miss: {calibration_metrics.get('conservative_miss')}")
        gate = calibration.get("material_mismatch_gate", {})
        print(f"confidence_material_mismatch_gate: {gate}")


if __name__ == "__main__":
    main()
