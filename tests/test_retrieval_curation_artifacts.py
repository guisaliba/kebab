import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.lib.paths import ROOT
from scripts.lib.retrieval_curation import (
    _compute_confidence_assessment,
    _extract_intent,
    _normalize_citation_marker,
    _review_action_for_confidence,
)
from scripts.lib.validation import validate_review_package


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_review_manifest(review_dir: Path, package_status: str, proposed_path: str) -> None:
    payload = {
        "review_id": review_dir.name,
        "source_id": "SRC-2099-9003",
        "package_status": package_status,
        "created_at": "2026-04-09T00:00:00Z",
        "updated_at": "2026-04-09T00:00:00Z",
        "proposed_paths": [proposed_path],
        "notes": "retrieval-assist test",
    }
    (review_dir / "manifest.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _build_review_fixture(review_id: str) -> tuple[Path, Path]:
    review_dir = ROOT / "staging" / "reviews" / review_id
    proposed_rel = Path(f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md")
    proposed_path = ROOT / proposed_rel
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    proposed_path.parent.mkdir(parents=True, exist_ok=True)

    source_page = ROOT / "wiki" / "platforms" / "meta-ads.md"
    proposed_path.write_text(source_page.read_text(encoding="utf-8"), encoding="utf-8")
    (review_dir / "source-summary.md").write_text("# Source Summary\n", encoding="utf-8")
    (review_dir / "contradictions.md").write_text("# Contradictions\n", encoding="utf-8")
    (review_dir / "open-questions.md").write_text("# Open Questions\n", encoding="utf-8")
    (review_dir / "claim-ledger.jsonl").write_text(
        (
            '{"claim_id":"CLM-0001","source_id":"SRC-2099-9003","claim":"ROAS baixo exige diagnostico por criativo e audiencia","type":"diagnostic","confidence":"high","evidence":["0001 00:00:10-00:00:40"],"touches":["/wiki/platforms/meta-ads.md"]}\n'
            '{"claim_id":"CLM-0002","source_id":"SRC-2099-9003","claim":"Broad targeting depende de contexto","type":"prescriptive","confidence":"medium","evidence":["0001 00:00:41-00:01:20"],"touches":["/wiki/tactics/broad-targeting.md"]}\n'
        ),
        encoding="utf-8",
    )
    (review_dir / "decision.md").write_text("# Decision\n\nStatus: pending\n", encoding="utf-8")
    _write_review_manifest(review_dir, "pending", str(proposed_rel))
    return review_dir, proposed_path


def test_curate_generates_retrieval_assist_artifacts_and_never_writes_wiki() -> None:
    review_id = "REV-2099-9003"
    review_dir, _ = _build_review_fixture(review_id)
    wiki_before = {path: _read(path) for path in (ROOT / "wiki").rglob("*.md")}
    try:
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout

        assist_dir = review_dir / "retrieval-assist"
        manifest = yaml.safe_load((assist_dir / "manifest.yaml").read_text(encoding="utf-8"))
        assert manifest["review_id"] == review_id
        assert manifest["proposal_count"] >= 1

        proposals = [
            json.loads(line)
            for line in (assist_dir / "proposals.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert proposals
        proposal = proposals[0]
        assert f"staging/reviews/{review_id}/proposed/wiki/" in proposal["target_proposed_path"]
        assert proposal["intended_wiki_path"].startswith("wiki/")
        assert proposal["change_type"] in {"append_section", "update_section", "new_note_link", "conflict_flag"}
        assert isinstance(proposal["confidence_score"], float)
        assert proposal["confidence_band"] in {"high", "medium", "low"}
        assert isinstance(proposal["confidence_reason_codes"], list)
        assert proposal["review_action"] in {"quick-approve", "normal-review", "deep-review"}

        evidence_path = assist_dir / "evidence" / f"{proposal['evidence_bundle_id']}.yaml"
        evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
        evidence_text = evidence_path.read_text(encoding="utf-8")
        assert "&id" not in evidence_text
        assert "*id" not in evidence_text
        assert "grounding" in evidence
        assert isinstance(evidence["grounding"]["normalized_citations"], list)
        assert isinstance(evidence["grounding"]["source_ids"], list)
        assert evidence["grounding"]["citation_format_version"] == "v1"
        assert isinstance(evidence["winner"]["score"], float)
        assert isinstance(evidence["winner"]["explain_payload"], dict)
        assert isinstance(evidence["supporting_hits"], list)
        assert isinstance(evidence["confidence_assessment"], dict)
        assert isinstance(evidence["confidence_assessment"]["score"], float)
        assert evidence["confidence_assessment"]["band"] in {"high", "medium", "low"}
        assert isinstance(evidence["confidence_assessment"]["reason_codes"], list)
        assert isinstance(evidence["confidence_assessment"]["factor_breakdown"], dict)
        assert evidence["confidence_assessment"]["review_action"] in {"quick-approve", "normal-review", "deep-review"}
        assert proposal["confidence_score"] == evidence["confidence_assessment"]["score"]
        assert proposal["confidence_band"] == evidence["confidence_assessment"]["band"]
        assert proposal["confidence_reason_codes"] == evidence["confidence_assessment"]["reason_codes"]
        assert proposal["review_action"] == evidence["confidence_assessment"]["review_action"]
        for supporting_hit in evidence["supporting_hits"]:
            assert supporting_hit["path"] != evidence["winner"]["path"]
            assert isinstance(supporting_hit["score"], float)
            assert isinstance(supporting_hit["explain_payload"], dict)
        assert "CLM-0001" in evidence["why_suggested"]
        assert isinstance(evidence["quality_flags"], list)
        assert isinstance(evidence["selection_policy"], dict)
        assert evidence["retrieval_context"]["alias_influence_class"] in {
            "alias_only",
            "fuzzy_only",
            "both_independently",
            "combined_only",
            "alias_plus_fuzzy_interaction",
            "none",
        }
        reviewer_summary = (assist_dir / "reviewer-summary.md").read_text(encoding="utf-8")
        triage_line = (
            f"- {proposal['proposal_id']} | confidence={proposal['confidence_score']} ({proposal['confidence_band']}) "
            f"| reasons={', '.join(proposal['confidence_reason_codes']) or 'none'} | action={proposal['review_action']}"
        )
        assert triage_line in reviewer_summary

        second = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert second.returncode != 0
        assert "rerun with --overwrite" in (second.stderr + second.stdout)

        overwrite = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id, "--overwrite"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert overwrite.returncode == 0, overwrite.stderr + overwrite.stdout

        wiki_after = {path: _read(path) for path in (ROOT / "wiki").rglob("*.md")}
        assert wiki_before == wiki_after
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)


def test_curate_overwrite_replaces_existing_artifacts() -> None:
    review_id = "REV-2099-9004"
    review_dir, _ = _build_review_fixture(review_id)
    try:
        first = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert first.returncode == 0, first.stderr + first.stdout

        assist_dir = review_dir / "retrieval-assist"
        stale_evidence = assist_dir / "evidence" / "EV-9999.yaml"
        stale_evidence.write_text("stale: true\n", encoding="utf-8")

        overwrite = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id, "--overwrite"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert overwrite.returncode == 0, overwrite.stderr + overwrite.stdout
        assert not stale_evidence.exists()
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)


def test_extract_intent_deduplicates_title_and_heading() -> None:
    content = (
        "---\n"
        "title: Meta Ads\n"
        "---\n\n"
        "# meta ads\n"
        "Conteúdo\n"
    )
    assert _extract_intent(content, "fallback") == "Meta Ads"


def test_review_validator_enforces_retrieval_assist_contract_fields() -> None:
    review_id = "REV-2099-9005"
    review_dir, _ = _build_review_fixture(review_id)
    try:
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout

        assist_dir = review_dir / "retrieval-assist"
        manifest_path = assist_dir / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["review_id"] = "REV-0000-0000"
        manifest["proposal_count"] = 999
        manifest["proposal_paths"] = ["staging/reviews/REV-0000-0000/proposed/wiki/platforms/meta-ads.md"]
        manifest["evidence_bundle_paths"] = [
            f"staging/reviews/{review_id}/retrieval-assist/evidence/EV-9999.yaml"
        ]
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")

        proposals_path = assist_dir / "proposals.jsonl"
        broken_proposal = {
            "proposal_id": "PRP-0001",
            "target_proposed_path": f"staging/reviews/{review_id}/proposed/wiki/platforms/meta-ads.md",
            "intended_wiki_path": "wiki/platforms/meta-ads.md",
            "change_type": "update_section",
            "summary": "test summary",
            "evidence_bundle_id": "EV-0001",
            "review_status": "proposed",
            "confidence_score": 1.5,
            "confidence_band": "invalid",
            "confidence_reason_codes": ["invalid_reason"],
            "review_action": "approve",
        }
        proposals_path.write_text(json.dumps(broken_proposal, ensure_ascii=False) + "\n", encoding="utf-8")

        errors = validate_review_package(review_dir)
        assert any("review_id mismatch" in error for error in errors)
        assert any("proposal_count mismatch" in error for error in errors)
        assert any("confidence_score must be numeric in [0,1]" in error for error in errors)
        assert any("invalid confidence_band" in error for error in errors)
        assert any("confidence_reason_codes[1] invalid value" in error for error in errors)
        assert any("invalid review_action" in error for error in errors)
        assert any("evidence_bundle_paths do not match proposals.jsonl evidence bundles" in error for error in errors)
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)


def test_supporting_hits_prioritize_distinct_paths_and_exclude_winner() -> None:
    review_id = "REV-2099-9006"
    review_dir, _ = _build_review_fixture(review_id)
    try:
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout

        proposals = [
            json.loads(line)
            for line in (review_dir / "retrieval-assist" / "proposals.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        update_proposal = next(item for item in proposals if item["change_type"] == "update_section")
        evidence_path = review_dir / "retrieval-assist" / "evidence" / f"{update_proposal['evidence_bundle_id']}.yaml"
        evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))

        winner_path = evidence["winner"]["path"]
        supporting_paths = [hit["path"] for hit in evidence["supporting_hits"]]
        assert winner_path not in supporting_paths
        assert len(supporting_paths) == len(set(supporting_paths))
        assert evidence["selection_policy"]["distinctness_rules"] == [
            "different_path",
            "different_page_type",
            "different_source_or_citation_context",
        ]
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)


def test_weak_case_quality_flags_and_strict_grounding() -> None:
    review_id = "REV-2099-9007"
    review_dir, _ = _build_review_fixture(review_id)
    try:
        source_note_rel = Path(
            f"staging/reviews/{review_id}/proposed/wiki/source-notes/weak-source-note.md"
        )
        source_note_path = ROOT / source_note_rel
        source_note_path.parent.mkdir(parents=True, exist_ok=True)
        source_note_path.write_text(
            (
                "---\n"
                "id: WIKI-SOURCE_NOTE-0999\n"
                "title: Weak Source Note\n"
                "type: source-note\n"
                "status: active\n"
                "language: pt-BR\n"
                "created_at: 2026-04-09T00:00:00Z\n"
                "updated_at: 2026-04-09T00:00:00Z\n"
                "review_status: proposed\n"
                "confidence: medium\n"
                "sources:\n"
                "- SRC-2099-9003\n"
                "topics:\n"
                "- meta-ads\n"
                "---\n\n"
                "# Weak Source Note\n"
                "Sem ligação direta de touches para este caminho.\n"
            ),
            encoding="utf-8",
        )
        manifest_path = review_dir / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["proposed_paths"].append(str(source_note_rel))
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")

        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout

        proposals = [
            json.loads(line)
            for line in (review_dir / "retrieval-assist" / "proposals.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        weak_proposal = next(item for item in proposals if item["change_type"] == "new_note_link")
        evidence_path = review_dir / "retrieval-assist" / "evidence" / f"{weak_proposal['evidence_bundle_id']}.yaml"
        evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))

        assert "weak_linked_claim_coverage" in evidence["quality_flags"]
        assert "No linked claims found in claim-ledger.jsonl" in evidence["why_suggested"]
        assert evidence["rationale_claim_ids"] == []
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)


def test_citation_marker_parsing_is_conservative_and_deterministic() -> None:
    marker = "[Sources: SRC-2026-0001 §lesson-01 00:00:10-00:00:40; MALFORMED; SRC-2026-0002 ch.03]"
    parsed = _normalize_citation_marker(marker)
    assert parsed == [
        {"source_id": "SRC-2026-0001", "evidence_ref": "§lesson-01 00:00:10-00:00:40"},
        {"source_id": "SRC-2026-0002", "evidence_ref": "ch.03"},
    ]

    invalid = _normalize_citation_marker("[Sources: SRC-2026-0001; incomplete]")
    assert invalid == []


def test_confidence_mapping_uses_highest_scrutiny_rule() -> None:
    assert _review_action_for_confidence(band="high", reason_codes=[]) == "quick-approve"
    assert _review_action_for_confidence(band="high", reason_codes=["single_supporting_context"]) == "normal-review"
    assert _review_action_for_confidence(band="high", reason_codes=["low_citation_coverage"]) == "deep-review"

    assessment = _compute_confidence_assessment(
        linked_claims=[],
        normalized_citations=[],
        supporting_hits=[],
        quality_flags=["weak_linked_claim_coverage", "single_supporting_context"],
    )
    assert assessment["band"] == "low"
    assert assessment["review_action"] == "deep-review"


def test_validate_review_package_returns_errors_not_raises_on_nonstring_reason_codes() -> None:
    review_id = "REV-2099-9010"
    review_dir, _ = _build_review_fixture(review_id)
    try:
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "curate" / "main.py"), "--review-id", review_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + run.stdout

        assist_dir = review_dir / "retrieval-assist"
        proposals_path = assist_dir / "proposals.jsonl"
        existing_lines = proposals_path.read_text(encoding="utf-8").splitlines()
        first_proposal = json.loads(existing_lines[0])
        first_proposal["confidence_reason_codes"] = ["valid_str", 42, None]
        proposals_path.write_text(json.dumps(first_proposal, ensure_ascii=False) + "\n", encoding="utf-8")

        errors = validate_review_package(review_dir)
        assert isinstance(errors, list), "validate_review_package must return a list, not raise"
        assert any("confidence_reason_codes" in error for error in errors)
    finally:
        if review_dir.exists():
            shutil.rmtree(review_dir)
