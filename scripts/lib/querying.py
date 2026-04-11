from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from scripts.lib.indexing import load_index, normalize_text, tokenize, write_index
from scripts.lib.paths import INDEX_DIR, ROOT


NAV_PATHS = {"wiki/index.md", "wiki/log.md"}


@dataclass
class SearchHit:
    path: Path
    score: float
    bm25_total: float
    contributions: dict[str, float]
    metadata: dict[str, Any]

    @property
    def accepted(self) -> bool:
        return self.metadata.get("accepted", False)


def _safe_load_or_build(corpus_type: str, output_dir: Path | None = None) -> dict[str, Any]:
    try:
        return load_index(corpus_type, output_dir=output_dir)
    except FileNotFoundError:
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
    include_nav: bool = False,
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
        if corpus_type == "wiki" and not include_nav and path_str in NAV_PATHS:
            continue

        title = doc.get("title", "")
        headings = doc.get("headings", [])
        body = doc.get("body_text", "")
        filename = doc.get("filename", "")
        page_type = doc.get("page_type", "")
        confidence = doc.get("confidence", "")

        field_total = (
            scores["title"][idx] * 3.0
            + scores["headings"][idx] * 2.0
            + scores["filename"][idx] * 1.5
            + scores["frontmatter"][idx] * 1.2
            + scores["body"][idx] * 1.0
        )
        contributions = {
            "bm25_title": scores["title"][idx] * 3.0,
            "bm25_headings": scores["headings"][idx] * 2.0,
            "bm25_filename": scores["filename"][idx] * 1.5,
            "bm25_frontmatter": scores["frontmatter"][idx] * 1.2,
            "bm25_body": scores["body"][idx],
        }

        normalized_title = normalize_text(title)
        normalized_filename = normalize_text(filename)
        phrase_boost = 0.0
        if normalized_question and normalized_question in normalized_title:
            phrase_boost += 2.0
        if normalized_question and any(normalized_question in normalize_text(heading) for heading in headings):
            phrase_boost += 1.5
        if normalized_question and normalized_question in normalized_filename:
            phrase_boost += 1.0
        contributions["phrase_boost"] = phrase_boost

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
        contributions["page_type_boost"] = page_type_boost

        confidence_boost = 0.0
        if confidence == "high":
            confidence_boost += 0.3
        elif confidence == "low":
            confidence_boost -= 0.2
        contributions["confidence_boost"] = confidence_boost

        citation_boost = 0.2 if doc.get("citations_present", False) else 0.0
        contributions["citation_boost"] = citation_boost

        if corpus_type == "wiki" and path_str == "wiki/index.md":
            contributions["navigation_penalty"] = -3.0
        else:
            contributions["navigation_penalty"] = 0.0

        final_score = field_total + sum(
            value for key, value in contributions.items() if key not in {"bm25_title", "bm25_headings", "bm25_filename", "bm25_frontmatter", "bm25_body"}
        )
        overlap_ok = _lexical_overlap_guard(query_tokens, f"{title}\n{' '.join(headings)}\n{body}")
        accepted = final_score >= min_score and overlap_ok
        hits.append(
            SearchHit(
                path=ROOT / path,
                score=final_score,
                bm25_total=field_total,
                contributions=contributions,
                metadata={
                    "accepted": accepted,
                    "corpus_type": corpus_type,
                    "page_type": page_type,
                    "confidence": confidence,
                    "citations_present": doc.get("citations_present", False),
                },
            )
        )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)


def search_wiki(
    question: str,
    min_score: float = 0.8,
    fuzzy: bool = False,
    output_dir: Path | None = None,
) -> list[SearchHit]:
    hits = _score_documents(
        corpus_type="wiki",
        question=question,
        min_score=min_score,
        fuzzy=fuzzy,
        include_nav=False,
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
        include_nav=True,
        output_dir=output_dir or INDEX_DIR,
    )
    return [hit for hit in hits if hit.accepted]


def collect_source_markers(content: str) -> list[str]:
    markers = []
    for line in content.splitlines():
        if "[Sources:" in line:
            markers.append(line[line.index("[Sources:") :].strip())
    return markers
