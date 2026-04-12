from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from scripts.lib.frontmatter import dump_markdown_with_frontmatter, parse_markdown_with_frontmatter
from scripts.lib.ids import next_review_id, next_wiki_id
from scripts.lib.paths import ROOT
from scripts.lib.retrieval_curation import generate_retrieval_assist
from scripts.lib.time import utc_now_iso8601


def load_registry(registry_path: Path) -> dict[str, Any]:
    if not registry_path.exists():
        return {"version": 1, "sources": []}
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {"version": 1, "sources": []}
    if "sources" not in data or not isinstance(data["sources"], list):
        data["sources"] = []
    return data


def upsert_registry_entry(registry_path: Path, source_manifest: dict[str, Any], source_rel_path: str) -> None:
    registry = load_registry(registry_path)
    source_id = source_manifest["source_id"]
    entry = {
        "source_id": source_id,
        "path": source_rel_path,
        "type": source_manifest.get("type", "unknown"),
        "language": source_manifest.get("language", "pt-BR"),
        "status": source_manifest.get("status", "active"),
    }
    replaced = False
    for idx, current in enumerate(registry["sources"]):
        if current.get("source_id") == source_id:
            registry["sources"][idx] = entry
            replaced = True
            break
    if not replaced:
        registry["sources"].append(entry)
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_review_id() -> str:
    year = datetime.now(timezone.utc).year
    review_root = ROOT / "staging" / "reviews"
    review_root.mkdir(parents=True, exist_ok=True)
    return next_review_id(review_root.iterdir(), year=year)


def _collect_existing_wiki_ids() -> list[str]:
    ids: list[str] = []
    for path in (ROOT / "wiki").rglob("*.md"):
        if path.name in {"index.md", "log.md"}:
            continue
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            continue
        frontmatter_block = content.split("\n---\n", 1)[0].replace("---\n", "")
        frontmatter = yaml.safe_load(frontmatter_block) or {}
        wiki_id = frontmatter.get("id")
        if isinstance(wiki_id, str):
            ids.append(wiki_id)
    return ids


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def _extract_segments(text: str) -> list[tuple[str | None, str]]:
    lines = text.splitlines()
    segments: list[tuple[str | None, str]] = []
    current_time: str | None = None
    current_lines: list[str] = []
    for line in lines:
        time_match = re.search(r"\[(\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2})\]", line)
        if line.startswith("## Segment") and time_match:
            if current_lines:
                segments.append((current_time, " ".join(current_lines).strip()))
            current_time = time_match.group(1).replace(" ", "")
            current_lines = []
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current_lines.append(stripped)
    if current_lines:
        segments.append((current_time, " ".join(current_lines).strip()))
    return segments


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if len(part.strip()) > 20]


def _classify_claim(sentence: str) -> tuple[str, str, list[str]]:
    lowered = sentence.lower()
    claim_type = "diagnostic"
    confidence = "medium"
    touches = ["/wiki/source-notes/"]

    if "broad targeting" in lowered:
        claim_type = "prescriptive"
        touches = ["/wiki/tactics/broad-targeting.md", "/wiki/platforms/meta-ads.md"]
    elif "roas" in lowered or "diagnostic" in lowered:
        claim_type = "diagnostic"
        touches = ["/wiki/platforms/meta-ads.md"]
        confidence = "high"
    elif "ctr" in lowered or "cpm" in lowered or "convers" in lowered:
        claim_type = "heuristic"
        touches = ["/wiki/platforms/meta-ads.md"]
    else:
        touches = ["/wiki/platforms/meta-ads.md"]

    if "não" in lowered or "nem sempre" in lowered:
        confidence = "high" if claim_type == "diagnostic" else confidence
    return claim_type, confidence, touches


def _extract_claims(source_id: str, chunk_paths: list[Path]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    claim_index = 1
    for chunk_path in chunk_paths:
        text = chunk_path.read_text(encoding="utf-8")
        segments = _extract_segments(text)
        if not segments:
            segments = [(None, text)]
        for segment_time, segment_text in segments:
            for sentence in _split_sentences(segment_text):
                claim_type, confidence, touches = _classify_claim(sentence)
                evidence = [chunk_path.name]
                if segment_time:
                    evidence = [f"{chunk_path.stem} {segment_time}"]
                claims.append(
                    {
                        "claim_id": f"CLM-{claim_index:04d}",
                        "source_id": source_id,
                        "claim": sentence,
                        "type": claim_type,
                        "confidence": confidence,
                        "evidence": evidence,
                        "touches": touches,
                    }
                )
                claim_index += 1
    return claims


def _tokenize_portuguese(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-ZÀ-ÿ0-9\-]{3,}", text.lower())}


def _split_wiki_sentences(content: str) -> list[str]:
    if content.startswith("---\n") and "\n---\n" in content:
        content = content.split("\n---\n", 1)[1]
    parts = re.split(r"(?<=[.!?])\s+", content)
    return [part.strip() for part in parts if len(part.strip()) > 20]


def _detect_contradictions(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    wiki_pages = [path for path in (ROOT / "wiki").rglob("*.md") if path.name not in {"index.md", "log.md"}]
    direct: list[dict[str, str]] = []
    soft: list[dict[str, str]] = []
    compared: list[dict[str, str]] = []

    for claim in claims:
        claim_text = claim["claim"]
        claim_tokens = _tokenize_portuguese(claim_text)
        claim_has_negation = any(token in claim_text.lower() for token in (" não ", "nem sempre", "nunca"))
        for wiki_path in wiki_pages:
            sentences = _split_wiki_sentences(wiki_path.read_text(encoding="utf-8"))
            for sentence in sentences:
                sentence_tokens = _tokenize_portuguese(sentence)
                overlap = len(claim_tokens & sentence_tokens)
                if overlap < 4:
                    continue
                compared.append(
                    {
                        "claim_id": claim["claim_id"],
                        "wiki_page": f"/{wiki_path.relative_to(ROOT)}",
                        "match": sentence,
                    }
                )
                wiki_has_negation = any(token in sentence.lower() for token in (" não ", "nem sempre", "nunca"))
                if claim_has_negation != wiki_has_negation and overlap >= 6:
                    direct.append(
                        {
                            "claim_id": claim["claim_id"],
                            "wiki_page": f"/{wiki_path.relative_to(ROOT)}",
                            "claim": claim_text,
                            "wiki_text": sentence,
                        }
                    )
                elif overlap >= 5:
                    soft.append(
                        {
                            "claim_id": claim["claim_id"],
                            "wiki_page": f"/{wiki_path.relative_to(ROOT)}",
                            "claim": claim_text,
                            "wiki_text": sentence,
                        }
                    )
                break
    return {"direct": direct[:5], "soft": soft[:8], "compared": compared[:12]}


def _write_claim_ledger(path: Path, claims: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(claim, ensure_ascii=False) for claim in claims)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _render_source_summary(source_manifest: dict[str, Any], claims: list[dict[str, Any]]) -> str:
    high_conf = sum(1 for claim in claims if claim["confidence"] == "high")
    med_conf = sum(1 for claim in claims if claim["confidence"] == "medium")
    return (
        "# Source Summary\n\n"
        "## Source\n"
        f"- source_id: {source_manifest['source_id']}\n"
        f"- title: {source_manifest.get('title', source_manifest['source_id'])}\n"
        f"- type: {source_manifest.get('type', 'unknown')}\n"
        f"- language: {source_manifest.get('language', 'pt-BR')}\n\n"
        "## Claim extraction snapshot\n"
        f"- total_claims: {len(claims)}\n"
        f"- high_confidence_claims: {high_conf}\n"
        f"- medium_confidence_claims: {med_conf}\n"
    )


def _render_contradictions(analysis: dict[str, list[dict[str, str]]]) -> str:
    lines = ["# Contradictions", "", "## Direct contradictions"]
    if not analysis["direct"]:
        lines.append("- None detected automatically.")
    else:
        for item in analysis["direct"]:
            lines.append(
                f"- {item['claim_id']} vs {item['wiki_page']}: claim='{item['claim']}' | wiki='{item['wiki_text']}'"
            )
    lines.extend(["", "## Soft tensions"])
    if not analysis["soft"]:
        lines.append("- None detected automatically.")
    else:
        for item in analysis["soft"][:5]:
            lines.append(
                f"- {item['claim_id']} overlaps {item['wiki_page']} and should be reviewed for context drift."
            )
    lines.extend(["", "## Compared wiki evidence"])
    if not analysis["compared"]:
        lines.append("- No meaningful overlap found between new claims and current wiki.")
    else:
        for item in analysis["compared"][:6]:
            lines.append(f"- {item['claim_id']} compared with {item['wiki_page']}")
    return "\n".join(lines) + "\n"


def _render_open_questions(claims: list[dict[str, Any]], analysis: dict[str, list[dict[str, str]]]) -> str:
    lines = ["# Open Questions", ""]
    if analysis["direct"]:
        lines.append("- Which direct contradictions should be resolved before promotion?")
    if any(claim["type"] == "prescriptive" for claim in claims):
        lines.append("- Prescriptive claims detected: should they remain contextualized or be generalized?")
    lines.append("- Are additional sources needed before elevating any low-support tactic claims?")
    return "\n".join(lines) + "\n"


def _render_reviewer_notes(claims: list[dict[str, Any]], analysis: dict[str, list[dict[str, str]]], proposed_paths: list[str]) -> str:
    lines = [
        "# Review Notes",
        "",
        "## Proposed changes summary",
        f"- claims_extracted: {len(claims)}",
        f"- direct_contradictions: {len(analysis['direct'])}",
        f"- soft_tensions: {len(analysis['soft'])}",
        f"- proposed_files: {len(proposed_paths)}",
        "",
        "## Proposed wiki files",
    ]
    lines.extend(f"- {path}" for path in proposed_paths)
    lines.extend(
        [
            "",
            "## Reviewer focus",
            "- Confirm citations are specific enough (segment/timestamp/chunk).",
            "- Confirm context-bound recommendations are not promoted as universal rules.",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_source_note_body(source_id: str, claims: list[dict[str, Any]], links: list[str]) -> str:
    lines = [f"# Source Note — {source_id}", "", "## Main takeaways"]
    if not claims:
        lines.append("- No claims extracted automatically.")
    for claim in claims[:6]:
        lines.append(f"- {claim['claim']}")
    lines.extend(["", "## Linked pages"])
    for link in links:
        lines.append(f"- `{link}`")
    return "\n".join(lines) + "\n"


def _build_proposed_updates(
    review_dir: Path,
    source_manifest: dict[str, Any],
    claims: list[dict[str, Any]],
    timestamp: str,
) -> tuple[list[str], str]:
    source_id = source_manifest["source_id"]
    title = source_manifest.get("title", source_id)
    source_slug = _slugify(title)
    source_note_filename = f"{source_slug}.md" if source_slug else f"{source_id.lower()}.md"

    proposed_paths: list[str] = []
    existing_ids = _collect_existing_wiki_ids()
    link_paths: list[str] = []

    # Proposed source note.
    proposed_source_note = review_dir / "proposed" / "wiki" / "source-notes" / source_note_filename
    proposed_source_note.parent.mkdir(parents=True, exist_ok=True)
    source_note_frontmatter = {
        "id": next_wiki_id(existing_ids, "source-note"),
        "title": f"Source Note - {source_id}",
        "type": "source-note",
        "status": "active",
        "language": source_manifest.get("language", "pt-BR"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "review_status": "proposed",
        "confidence": "medium",
        "sources": [source_id],
        "topics": source_manifest.get("topics", []),
    }
    candidate_links = sorted({touch for claim in claims for touch in claim["touches"] if touch.startswith("/wiki/")})
    source_note_body = _build_source_note_body(source_id, claims, candidate_links[:6])
    proposed_source_note.write_text(
        dump_markdown_with_frontmatter(source_note_frontmatter, source_note_body),
        encoding="utf-8",
    )
    proposed_paths.append(str(proposed_source_note.relative_to(ROOT)))
    link_paths.append(f"/{proposed_source_note.relative_to(ROOT)}")

    # Proposed update to platform page if it exists.
    platform_page = ROOT / "wiki" / "platforms" / "meta-ads.md"
    if platform_page.exists():
        platform_doc = parse_markdown_with_frontmatter(platform_page.read_text(encoding="utf-8"))
        platform_doc.frontmatter["review_status"] = "proposed"
        platform_doc.frontmatter["updated_at"] = timestamp
        bullets = []
        for claim in claims[:3]:
            evidence = claim["evidence"][0]
            bullets.append(f"- {claim['claim']} [Sources: {source_id} §{evidence}]")
        addition = (
            f"\n## Proposed updates from {source_id}\n"
            + "\n".join(bullets)
            + "\n\n## Caveats\n- Essas adições permanecem contextuais até validação de múltiplas fontes.\n"
        )
        proposed_platform = review_dir / "proposed" / "wiki" / "platforms" / "meta-ads.md"
        proposed_platform.parent.mkdir(parents=True, exist_ok=True)
        proposed_platform.write_text(
            dump_markdown_with_frontmatter(platform_doc.frontmatter, platform_doc.body.rstrip() + addition),
            encoding="utf-8",
        )
        proposed_paths.append(str(proposed_platform.relative_to(ROOT)))
        link_paths.append(f"/{proposed_platform.relative_to(ROOT)}")

    return proposed_paths, "\n".join(f"- {path}" for path in link_paths)


def create_review_package(
    review_id: str,
    source_manifest: dict[str, Any],
    notes: str,
    chunk_paths: list[Path],
    *,
    run_retrieval_assist: bool = False,
    retrieval_assist_overwrite: bool = False,
) -> Path:
    review_dir = ROOT / "staging" / "reviews" / review_id
    review_dir.mkdir(parents=True, exist_ok=True)

    timestamp = utc_now_iso8601()
    source_id = source_manifest["source_id"]
    claims = _extract_claims(source_id, chunk_paths)
    analysis = _detect_contradictions(claims)
    proposed_paths, _ = _build_proposed_updates(review_dir, source_manifest, claims, timestamp)

    manifest = {
        "review_id": review_id,
        "source_id": source_id,
        "package_status": "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "proposed_paths": proposed_paths,
        "notes": notes,
    }
    (review_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    (review_dir / "source-summary.md").write_text(_render_source_summary(source_manifest, claims), encoding="utf-8")
    (review_dir / "contradictions.md").write_text(_render_contradictions(analysis), encoding="utf-8")
    (review_dir / "open-questions.md").write_text(_render_open_questions(claims, analysis), encoding="utf-8")
    (review_dir / "decision.md").write_text(
        (
            "# Decision\n\n"
            "Status: pending\n"
            "Reviewer:\n"
            "Reviewed_at:\n\n"
            "## Approved\n\n"
            "## Rejected\n\n"
            "## Reason\n"
            "Pending review.\n"
        ),
        encoding="utf-8",
    )
    (review_dir / "review-notes.md").write_text(
        _render_reviewer_notes(claims, analysis, proposed_paths),
        encoding="utf-8",
    )
    _write_claim_ledger(review_dir / "claim-ledger.jsonl", claims)
    (review_dir / "diff.patch").write_text("", encoding="utf-8")
    if run_retrieval_assist:
        assist_dir = generate_retrieval_assist(review_id=review_id, overwrite=retrieval_assist_overwrite)
        manifest["retrieval_assist_path"] = str(assist_dir.relative_to(ROOT))
        manifest["retrieval_assist_manifest"] = str((assist_dir / "manifest.yaml").relative_to(ROOT))
        manifest["updated_at"] = utc_now_iso8601()
        (review_dir / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return review_dir
