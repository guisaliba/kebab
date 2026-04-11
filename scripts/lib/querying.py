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


def _fuzzy_expand(query_tokens: list[str], vocabulary: set[str]) -> list[str]:
    expanded = list(query_tokens)
    for token in query_tokens:
        if len(token) < 4:
            continue
        matches = difflib.get_close_matches(token, vocabulary, n=2, cutoff=0.88)
        for match in matches:
            if match not in expanded:
                expanded.append(match)
    return expanded


def _lexical_overlap_guard(query_tokens: list[str], body: str) -> bool:
    body_tokens = set(tokenize(body))
    return bool(body_tokens.intersection(query_tokens))


def _score_documents(
    corpus_type: str,
    question: str,
    min_score: float,
    fuzzy: bool,
    include_navigation: bool = False,
    output_dir: Path | None = None,
) -> list[SearchHit]:
    index = _safe_load_or_build(corpus_type, output_dir=output_dir)
    documents = index["documents"]
    normalized_question = normalize_text(question)
    query_tokens = tokenize(normalized_question)
    if not query_tokens:
        return []

    vocabulary = {
        token
        for document in documents
        for token in tokenize(document["normalized_fields"].get("title", ""))
        + tokenize(document["normalized_fields"].get("headings", ""))
        + tokenize(document["normalized_fields"].get("body", ""))
    }
    if fuzzy:
        query_tokens = _fuzzy_expand(query_tokens, vocabulary)

    scores = _field_bm25_scores(documents, query_tokens)
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
            role_adjustment -= 0.25
        elif retrieval_role == "navigation":
            role_adjustment -= 1.25
        heuristic_fields["role_adjustment"] = float(role_adjustment)

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
    output_dir: Path | None = None,
) -> list[SearchHit]:
    hits = _score_documents(
        corpus_type="wiki",
        question=question,
        min_score=min_score,
        fuzzy=fuzzy,
        include_navigation=include_navigation,
        output_dir=output_dir or INDEX_DIR,
    )
    return [hit for hit in hits if hit.accepted]


def search_raw_chunks(
    question: str,
    min_score: float = 0.6,
    fuzzy: bool = False,
    output_dir: Path | None = None,
) -> list[SearchHit]:
    hits = _score_documents(
        corpus_type="raw",
        question=question,
        min_score=min_score,
        fuzzy=fuzzy,
        include_navigation=True,
        output_dir=output_dir or INDEX_DIR,
    )
    return [hit for hit in hits if hit.accepted]


def index_status(corpus_type: str, output_dir: Path | None = None) -> dict[str, Any]:
    try:
        freshness = index_freshness(corpus_type, output_dir=output_dir or INDEX_DIR)
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
