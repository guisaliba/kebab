from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from scripts.lib.indexing import index_freshness, load_index, normalize_text, tokenize, write_index
from scripts.lib.paths import INDEX_DIR, ROOT
from scripts.lib.retrieval_aliases import apply_scoped_aliases

EVIDENCE_INTENT_TERMS = {
    "chunk",
    "chunk_id",
    "segment",
    "transcript",
    "raw",
    "timestamp",
    "timecode",
    "evidencia",
    "evidence",
    "json",
    "start",
    "end",
}
CANONICAL_CUE_TERMS = {"canonical", "platform", "tactic", "playbook", "metric", "overview", "vs", "versus"}
SOURCE_ID_PATTERN = re.compile(r"\bsrc-\d{4}-\d{4}\b", re.IGNORECASE)
TIMECODE_PATTERN = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")
SEGMENT_NUMBER_PATTERN = re.compile(r"\bsegment\s+(\d+)\b")
CHUNK_NUMBER_PATTERN = re.compile(r"\bchunk[-_ ]?0*(\d+)\b")


@dataclass
class SearchHit:
    path: Path
    score: float
    bm25_total: float
    bm25_fields: dict[str, float]
    heuristic_fields: dict[str, float]
    metadata: dict[str, Any]
    acceptance_reasons: list[str]
    rejection_reasons: list[str]

    @property
    def accepted(self) -> bool:
        return self.metadata.get("accepted", False)

    def explain_payload(self) -> dict[str, Any]:
        final_score = self.bm25_total + sum(self.heuristic_fields.values())
        return {
            "path": str(self.path.relative_to(ROOT)),
            "accepted": self.accepted,
            "final_score": round(float(final_score), 6),
            "bm25_total": round(float(self.bm25_total), 6),
            "bm25_fields": {key: round(float(value), 6) for key, value in self.bm25_fields.items()},
            "heuristic_fields": {
                key: round(float(value), 6) for key, value in self.heuristic_fields.items()
            },
            "acceptance_reasons": self.acceptance_reasons,
            "rejection_reasons": self.rejection_reasons,
            "metadata": self.metadata,
        }

    def explain_text(self) -> str:
        payload = self.explain_payload()
        bm25_parts = ", ".join(f"{k}={v:.3f}" for k, v in payload["bm25_fields"].items())
        heur_parts = ", ".join(f"{k}={v:.3f}" for k, v in payload["heuristic_fields"].items())
        reasons = payload["acceptance_reasons"] if payload["accepted"] else payload["rejection_reasons"]
        label = "accepted_reasons" if payload["accepted"] else "rejected_reasons"
        return (
            f"bm25_total={payload['bm25_total']:.3f} [{bm25_parts}] | "
            f"heuristics=[{heur_parts}] | final_score={payload['final_score']:.3f} | "
            f"{label}={'; '.join(reasons) if reasons else 'none'}"
        )


def _safe_load_or_build(corpus_type: str, output_dir: Path | None = None) -> dict[str, Any]:
    try:
        return load_index(corpus_type, output_dir=output_dir)
    except (FileNotFoundError, ValueError):
        write_index(corpus_type, output_dir=output_dir)
        return load_index(corpus_type, output_dir=output_dir)


def _field_bm25_scores(documents: list[dict[str, Any]], query_tokens: list[str]) -> dict[str, list[float]]:
    field_scores: dict[str, list[float]] = {}
    for field in ("title", "headings", "filename", "frontmatter", "body"):
        corpus = [tokenize(doc["normalized_fields"].get(field, "")) for doc in documents]
        if not any(corpus):
            field_scores[field] = [0.0] * len(documents)
            continue
        bm25 = BM25Okapi(corpus)
        field_scores[field] = list(bm25.get_scores(query_tokens))
    return field_scores


def _fuzzy_expand(query_tokens: list[str], vocabulary: set[str]) -> tuple[list[str], set[str]]:
    expanded = list(query_tokens)
    added: set[str] = set()
    for token in query_tokens:
        if len(token) < 5:
            continue
        if token in vocabulary:
            continue
        if token.isdigit():
            continue
        cutoff = 0.9 if len(token) <= 6 else 0.86
        matches = difflib.get_close_matches(token, vocabulary, n=2, cutoff=cutoff)
        for match in matches:
            if match not in expanded:
                expanded.append(match)
                added.add(match)
    return expanded, added


def _lexical_overlap_guard(query_tokens: list[str], body: str) -> bool:
    body_tokens = set(tokenize(body))
    return bool(body_tokens.intersection(query_tokens))


def is_evidence_query(question: str) -> bool:
    normalized_question = normalize_text(question)
    query_tokens = set(tokenize(normalized_question))
    if "ugc" in query_tokens:
        return True
    if {"creative", "fatigue"}.issubset(query_tokens):
        return True
    if query_tokens.intersection(EVIDENCE_INTENT_TERMS):
        return True
    has_source_id = bool(SOURCE_ID_PATTERN.search(question))
    if has_source_id and query_tokens.intersection({"chunk", "segment", "transcript", "raw", "timestamp", "timecode"}):
        return True
    return bool(TIMECODE_PATTERN.search(question))


def should_use_raw_fallback(question: str, wiki_hits: list[SearchHit]) -> bool:
    if not wiki_hits:
        return True
    return is_evidence_query(question)


def calibrated_raw_min_score(question: str, wiki_min_score: float) -> float:
    if is_evidence_query(question):
        return max(wiki_min_score * 0.5, 0.2)
    return max(wiki_min_score * 0.75, 0.4)


def _raw_evidence_alignment_components(
    *,
    question: str,
    query_tokens: list[str],
    query_token_set: set[str],
    evidence_intent: bool,
    query_segment_number: str | None,
    query_chunk_number: str | None,
    query_has_transcript_intent: bool,
    path: Path,
    path_str: str,
    normalized_body: str,
    normalized_blob: str,
) -> dict[str, float]:
    components: dict[str, float] = {
        "intent_base": 0.0,
        "timecode_match": 0.0,
        "source_id_match": 0.0,
        "marker_overlap": 0.0,
        "chunk_id_alignment": 0.0,
        "chunk_number_alignment": 0.0,
        "segment_number_alignment": 0.0,
        "transcript_path_preference": 0.0,
        "segment_local_chunk_preference": 0.0,
        "generic_multi_segment_chunk_penalty": 0.0,
    }
    if evidence_intent:
        components["intent_base"] += 0.5

    is_chunk_doc = "/chunks/" in path_str
    is_transcript_doc = "/transcript/" in path_str
    chunk_id_present = "chunk_id" in normalized_body
    segment_mentions = len(SEGMENT_NUMBER_PATTERN.findall(normalized_body))

    if TIMECODE_PATTERN.search(question):
        for match in TIMECODE_PATTERN.findall(question):
            if normalize_text(match) in normalized_blob:
                components["timecode_match"] += 0.8
                break
    if SOURCE_ID_PATTERN.search(question):
        source_match = SOURCE_ID_PATTERN.search(question)
        if source_match and normalize_text(source_match.group(0)) in normalized_blob:
            components["source_id_match"] += 0.8

    evidence_markers = {
        token
        for token in query_tokens
        if token in {"chunk", "chunk_id", "segment", "transcript", "lesson", "timestamp", "start", "end"}
    }
    if evidence_markers:
        marker_hits = sum(1 for token in evidence_markers if token in normalized_blob)
        components["marker_overlap"] += min(0.6, marker_hits * 0.2)

    if "chunk_id" in query_token_set:
        if chunk_id_present:
            components["chunk_id_alignment"] += 0.9
        elif is_chunk_doc:
            components["chunk_id_alignment"] -= 0.3
    if query_chunk_number:
        if path.stem.lstrip("0") == query_chunk_number:
            components["chunk_number_alignment"] += 1.0
        elif is_chunk_doc:
            components["chunk_number_alignment"] -= 0.25

    if query_segment_number:
        if f"segment {query_segment_number}" in normalized_body:
            components["segment_number_alignment"] += 0.9
        elif segment_mentions > 0:
            components["segment_number_alignment"] -= 0.25

    if query_has_transcript_intent:
        if is_transcript_doc:
            components["transcript_path_preference"] += 1.1
        elif is_chunk_doc:
            components["transcript_path_preference"] -= 0.8

    # Segment-local chunk preference is intentionally isolated in one component to
    # keep segment-aware scoring explicit and auditable.
    if query_segment_number and not query_has_transcript_intent:
        if is_chunk_doc and f"segment {query_segment_number}" in normalized_body:
            components["segment_local_chunk_preference"] += 0.7
        if is_transcript_doc:
            components["segment_local_chunk_preference"] -= 0.5
    if query_segment_number and is_chunk_doc and segment_mentions > 1:
        components["generic_multi_segment_chunk_penalty"] -= 0.6

    return components


def _score_documents(
    corpus_type: str,
    question: str,
    min_score: float,
    fuzzy: bool,
    include_navigation: bool = False,
    use_aliases: bool = True,
    alias_domain: str = "kb_marketing_ptbr_en",
    output_dir: Path | None = None,
) -> list[SearchHit]:
    index = _safe_load_or_build(corpus_type, output_dir=output_dir)
    documents = index["documents"]
    normalized_question = normalize_text(question)
    query_tokens = tokenize(normalized_question)
    if not query_tokens:
        return []
    evidence_intent = is_evidence_query(question)
    query_token_set = set(query_tokens)
    canonical_cues = query_token_set.intersection(CANONICAL_CUE_TERMS)
    alias_resolution = apply_scoped_aliases(
        query_token_set,
        corpus_type=corpus_type,
        domain=alias_domain,
        enable_aliases=use_aliases,
    )
    normalized_tokens = alias_resolution.normalized_tokens
    has_targeting_intent = bool(normalized_tokens.intersection({"broad", "targeting", "publico", "audience"}))
    has_diagnostic_intent = bool(
        normalized_tokens.intersection({"ctr", "cpm", "roas", "criativo", "oferta", "conversao", "diagnostico"})
    )
    query_segment_match = SEGMENT_NUMBER_PATTERN.search(normalized_question)
    query_chunk_match = CHUNK_NUMBER_PATTERN.search(normalized_question)
    query_segment_number = query_segment_match.group(1) if query_segment_match else None
    query_chunk_number = query_chunk_match.group(1) if query_chunk_match else None
    query_has_transcript_intent = "transcript" in query_token_set
    compare_source_vs_canonical = bool(query_token_set.intersection({"vs", "versus"})) and bool(
        query_token_set.intersection({"platform", "canonical", "tactic", "playbook", "metric"})
    )

    vocabulary = {
        token
        for document in documents
        for token in tokenize(document["normalized_fields"].get("title", ""))
        + tokenize(document["normalized_fields"].get("headings", ""))
        + tokenize(document["normalized_fields"].get("body", ""))
    }
    fuzzy_added_tokens: set[str] = set()
    if fuzzy:
        query_tokens, fuzzy_added_tokens = _fuzzy_expand(query_tokens, vocabulary)

    bm25_query_tokens = list(query_tokens)
    if corpus_type == "raw" and evidence_intent:
        # Numeric-only tokens from source IDs can dominate BM25 on chunk filenames.
        # Keep evidence disambiguation in dedicated heuristics instead.
        bm25_query_tokens = [token for token in bm25_query_tokens if not token.isdigit()]
    scores = _field_bm25_scores(documents, bm25_query_tokens)
    hits: list[SearchHit] = []
    for idx, doc in enumerate(documents):
        path = Path(doc["path"])
        path_str = str(path)

        title = doc.get("title", "")
        headings = doc.get("headings", [])
        body = doc.get("body_text", "")
        filename = doc.get("filename", "")
        page_type = doc.get("page_type", "")
        confidence = doc.get("confidence", "")
        retrieval_role = doc.get("retrieval_role", "answerable")

        field_total = (
            scores["title"][idx] * 3.0
            + scores["headings"][idx] * 2.0
            + scores["filename"][idx] * 1.5
            + scores["frontmatter"][idx] * 1.2
            + scores["body"][idx] * 1.0
        )
        bm25_fields = {
            "title": float(scores["title"][idx] * 3.0),
            "headings": float(scores["headings"][idx] * 2.0),
            "filename": float(scores["filename"][idx] * 1.5),
            "frontmatter": float(scores["frontmatter"][idx] * 1.2),
            "body": float(scores["body"][idx]),
        }
        heuristic_fields: dict[str, float] = {}

        normalized_title = normalize_text(title)
        normalized_filename = normalize_text(filename)
        phrase_boost = 0.0
        if normalized_question and normalized_question in normalized_title:
            phrase_boost += 2.0
        if normalized_question and any(normalized_question in normalize_text(heading) for heading in headings):
            phrase_boost += 1.5
        if normalized_question and normalized_question in normalized_filename:
            phrase_boost += 1.0
        heuristic_fields["phrase_boost"] = float(phrase_boost)

        page_type_boost = 0.0
        if page_type == "platform":
            page_type_boost += 1.0
        elif page_type == "playbook":
            page_type_boost += 0.8
        elif page_type == "tactic":
            page_type_boost += 0.7
        elif page_type == "metric":
            page_type_boost += 0.6
        elif page_type == "source-note":
            page_type_boost -= 0.4
        heuristic_fields["page_type_boost"] = float(page_type_boost)

        confidence_boost = 0.0
        if confidence == "high":
            confidence_boost += 0.3
        elif confidence == "low":
            confidence_boost -= 0.2
        heuristic_fields["confidence_boost"] = float(confidence_boost)

        citation_boost = 0.2 if doc.get("citations_present", False) else 0.0
        heuristic_fields["citation_boost"] = float(citation_boost)

        role_adjustment = 0.0
        if retrieval_role == "answerable":
            role_adjustment += 0.4
        elif retrieval_role == "auxiliary":
            role_adjustment += 0.1 if corpus_type == "raw" else -0.25
        elif retrieval_role == "navigation":
            role_adjustment -= 1.25
        heuristic_fields["role_adjustment"] = float(role_adjustment)

        canonical_precedence_boost = 0.0
        if corpus_type == "wiki":
            if page_type == "source-note":
                canonical_precedence_boost -= 0.6 if canonical_cues else 1.1
                if compare_source_vs_canonical:
                    canonical_precedence_boost -= 12.0
            elif page_type in {"platform", "playbook", "tactic", "metric", "comparison", "overview"}:
                canonical_precedence_boost += 0.45
                if compare_source_vs_canonical:
                    canonical_precedence_boost += 0.75
        heuristic_fields["canonical_precedence_boost"] = float(canonical_precedence_boost)

        evidence_alignment_boost = 0.0
        if corpus_type == "raw":
            normalized_body = normalize_text(body)
            normalized_blob = " ".join(
                [
                    normalized_title,
                    normalize_text(" ".join(headings)),
                    normalized_body,
                    normalize_text(path_str),
                    normalize_text(json.dumps(doc.get("frontmatter", {}), ensure_ascii=False)),
                ]
            )
            evidence_components = _raw_evidence_alignment_components(
                question=question,
                query_tokens=query_tokens,
                query_token_set=query_token_set,
                evidence_intent=evidence_intent,
                query_segment_number=query_segment_number,
                query_chunk_number=query_chunk_number,
                query_has_transcript_intent=query_has_transcript_intent,
                path=path,
                path_str=path_str,
                normalized_body=normalized_body,
                normalized_blob=normalized_blob,
            )
            evidence_alignment_boost += sum(evidence_components.values())
        heuristic_fields["evidence_alignment_boost"] = float(evidence_alignment_boost)

        fuzzy_match_boost = 0.0
        if fuzzy and fuzzy_added_tokens:
            title_heading_blob = " ".join([normalized_title, normalize_text(" ".join(headings))])
            body_blob = normalize_text(body)
            title_heading_hits = sum(1 for token in fuzzy_added_tokens if token in title_heading_blob)
            body_hits = sum(1 for token in fuzzy_added_tokens if token in body_blob)
            fuzzy_match_boost += min(2.2, title_heading_hits * 0.7 + body_hits * 0.35)
        heuristic_fields["fuzzy_match_boost"] = float(fuzzy_match_boost)

        tactic_platform_intent_boost = 0.0
        if corpus_type == "wiki" and has_targeting_intent and has_diagnostic_intent:
            if page_type == "tactic":
                tactic_platform_intent_boost += 1.6
            elif page_type == "platform":
                tactic_platform_intent_boost -= 0.4
            if alias_resolution.changed_tokens:
                tactic_platform_intent_boost += 0.3
        heuristic_fields["tactic_platform_intent_boost"] = float(tactic_platform_intent_boost)

        if corpus_type == "wiki" and path_str == "wiki/index.md":
            heuristic_fields["index_page_penalty"] = -1.75
        else:
            heuristic_fields["index_page_penalty"] = 0.0

        final_score = float(field_total + sum(heuristic_fields.values()))
        overlap_ok = _lexical_overlap_guard(query_tokens, f"{title}\n{' '.join(headings)}\n{body}")
        acceptance_reasons: list[str] = []
        rejection_reasons: list[str] = []
        accepted = True

        if final_score < min_score:
            accepted = False
            rejection_reasons.append("below_min_score")
        else:
            acceptance_reasons.append("score_meets_threshold")
        if not overlap_ok:
            accepted = False
            rejection_reasons.append("insufficient_lexical_overlap")
        else:
            acceptance_reasons.append("lexical_overlap_present")
        if corpus_type == "wiki" and retrieval_role == "navigation" and not include_navigation:
            accepted = False
            rejection_reasons.append("navigation_excluded_default")
        elif retrieval_role == "navigation" and include_navigation:
            acceptance_reasons.append("navigation_included_by_flag")
        if retrieval_role == "answerable":
            acceptance_reasons.append("retrieval_role_answerable")
        elif retrieval_role == "auxiliary":
            acceptance_reasons.append("retrieval_role_auxiliary")
        elif retrieval_role == "navigation":
            acceptance_reasons.append("retrieval_role_navigation")

        hits.append(
            SearchHit(
                path=ROOT / path,
                score=final_score,
                bm25_total=float(field_total),
                bm25_fields=bm25_fields,
                heuristic_fields=heuristic_fields,
                metadata={
                    "accepted": accepted,
                    "corpus_type": corpus_type,
                    "page_type": page_type,
                    "confidence": confidence,
                    "citations_present": doc.get("citations_present", False),
                    "retrieval_role": retrieval_role,
                },
                acceptance_reasons=acceptance_reasons,
                rejection_reasons=rejection_reasons,
            )
        )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)


def search_wiki(
    question: str,
    min_score: float = 0.8,
    fuzzy: bool = False,
    include_navigation: bool = False,
    use_aliases: bool = True,
    alias_domain: str = "kb_marketing_ptbr_en",
    output_dir: Path | None = None,
) -> list[SearchHit]:
    hits = _score_documents(
        corpus_type="wiki",
        question=question,
        min_score=min_score,
        fuzzy=fuzzy,
        include_navigation=include_navigation,
        use_aliases=use_aliases,
        alias_domain=alias_domain,
        output_dir=output_dir or INDEX_DIR,
    )
    return [hit for hit in hits if hit.accepted]


def search_raw_chunks(
    question: str,
    min_score: float = 0.6,
    fuzzy: bool = False,
    use_aliases: bool = True,
    alias_domain: str = "kb_marketing_ptbr_en",
    output_dir: Path | None = None,
) -> list[SearchHit]:
    hits = _score_documents(
        corpus_type="raw",
        question=question,
        min_score=min_score,
        fuzzy=fuzzy,
        include_navigation=True,
        use_aliases=use_aliases,
        alias_domain=alias_domain,
        output_dir=output_dir or INDEX_DIR,
    )
    return [hit for hit in hits if hit.accepted]


def index_status(
    corpus_type: str,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    try:
        freshness = index_freshness(
            corpus_type,
            output_dir=output_dir or INDEX_DIR,
            verbose=verbose,
        )
        freshness["status"] = "ok"
        return freshness
    except FileNotFoundError:
        return {"status": "missing", "corpus_type": corpus_type}
    except ValueError as exc:
        return {"status": "invalid", "corpus_type": corpus_type, "error": str(exc)}


def explain_payload_json(hit: SearchHit) -> str:
    return json.dumps(hit.explain_payload(), ensure_ascii=False)


def collect_source_markers(content: str) -> list[str]:
    markers = []
    for line in content.splitlines():
        if "[Sources:" in line:
            markers.append(line[line.index("[Sources:") :].strip())
    return markers
