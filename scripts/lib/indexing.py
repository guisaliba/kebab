from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.lib.frontmatter import parse_markdown_with_frontmatter
from scripts.lib.paths import INDEX_DIR, RAW_DIR, ROOT, WIKI_DIR
from scripts.lib.time import utc_now_iso8601


INDEX_VERSION = 2
WIKI_INDEX_FILENAME = "wiki.index.json"
RAW_INDEX_FILENAME = "raw.index.json"


@dataclass
class IndexedDocument:
    path: str
    mtime: float
    content_hash: str
    filename: str
    title: str
    headings: list[str]
    frontmatter: dict[str, Any]
    body_text: str
    citations_present: bool
    confidence: str
    page_type: str
    retrieval_role: str
    normalized_fields: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mtime": self.mtime,
            "content_hash": self.content_hash,
            "filename": self.filename,
            "title": self.title,
            "headings": self.headings,
            "frontmatter": self.frontmatter,
            "body_text": self.body_text,
            "citations_present": self.citations_present,
            "confidence": self.confidence,
            "page_type": self.page_type,
            "retrieval_role": self.retrieval_role,
            "normalized_fields": self.normalized_fields,
        }


def fold_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value: str) -> str:
    lowered = value.lower()
    folded = fold_accents(lowered)
    punctuation_normalized = re.sub(r"[^\w\s\-]", " ", folded, flags=re.UNICODE)
    return re.sub(r"\s+", " ", punctuation_normalized).strip()


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value)
    return [token for token in re.findall(r"[a-z0-9_\-]{2,}", normalized)]


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _extract_headings(markdown: str) -> list[str]:
    headings = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return headings


def derive_retrieval_role(path: Path, frontmatter: dict[str, Any], corpus_type: str) -> str:
    explicit = frontmatter.get("retrieval_role")
    if isinstance(explicit, str) and explicit in {"answerable", "navigation", "auxiliary"}:
        return explicit

    if corpus_type == "raw":
        return "auxiliary"

    rel_path = str(path.relative_to(ROOT))
    page_type = str(frontmatter.get("type", ""))
    if rel_path in {"wiki/index.md", "wiki/log.md"} or rel_path.endswith("/index.md"):
        return "navigation"
    if page_type == "source-note":
        return "auxiliary"
    return "answerable"


def _wiki_document(path: Path) -> IndexedDocument:
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---\n") and "\n---\n" in raw:
        doc = parse_markdown_with_frontmatter(raw)
        frontmatter = {
            "id": doc.frontmatter.get("id", ""),
            "type": doc.frontmatter.get("type", ""),
            "confidence": doc.frontmatter.get("confidence", ""),
            "review_status": doc.frontmatter.get("review_status", ""),
            "status": doc.frontmatter.get("status", ""),
            "topics": doc.frontmatter.get("topics", []),
            "aliases": doc.frontmatter.get("aliases", []),
            "retrieval_role": doc.frontmatter.get("retrieval_role", ""),
        }
        title = str(doc.frontmatter.get("title", path.stem))
        body = doc.body
    else:
        frontmatter = {}
        title = path.stem
        body = raw

    headings = _extract_headings(body)
    return IndexedDocument(
        path=str(path.relative_to(ROOT)),
        mtime=path.stat().st_mtime,
        content_hash=_content_hash(raw),
        filename=path.name,
        title=title,
        headings=headings,
        frontmatter=frontmatter,
        body_text=body,
        citations_present="[Sources:" in body,
        confidence=str(frontmatter.get("confidence", "")),
        page_type=str(frontmatter.get("type", "")),
        retrieval_role=derive_retrieval_role(path, frontmatter, corpus_type="wiki"),
        normalized_fields={
            "title": normalize_text(title),
            "headings": normalize_text(" ".join(headings)),
            "filename": normalize_text(path.name),
            "frontmatter": normalize_text(json.dumps(frontmatter, ensure_ascii=False)),
            "body": normalize_text(body),
        },
    )


def _raw_document(path: Path) -> IndexedDocument:
    body = path.read_text(encoding="utf-8")
    headings = _extract_headings(body)
    source_id = next((part for part in path.parts if part.startswith("SRC-")), "")
    frontmatter = {"source_id": source_id}
    return IndexedDocument(
        path=str(path.relative_to(ROOT)),
        mtime=path.stat().st_mtime,
        content_hash=_content_hash(body),
        filename=path.name,
        title=path.stem,
        headings=headings,
        frontmatter=frontmatter,
        body_text=body,
        citations_present="[Sources:" in body,
        confidence="",
        page_type="raw-chunk",
        retrieval_role=derive_retrieval_role(path, frontmatter, corpus_type="raw"),
        normalized_fields={
            "title": normalize_text(path.stem),
            "headings": normalize_text(" ".join(headings)),
            "filename": normalize_text(path.name),
            "frontmatter": normalize_text(json.dumps(frontmatter, ensure_ascii=False)),
            "body": normalize_text(body),
        },
    )


def build_index(corpus_type: str) -> dict[str, Any]:
    if corpus_type not in {"wiki", "raw"}:
        raise ValueError(f"unsupported corpus type: {corpus_type}")

    if corpus_type == "wiki":
        docs = []
        for path in sorted(WIKI_DIR.rglob("*.md")):
            if path.name in {"log.md"}:
                continue
            docs.append(_wiki_document(path).to_dict())
    else:
        docs = []
        for path in sorted(RAW_DIR.rglob("*")):
            if path.suffix not in {".md", ".txt"}:
                continue
            if "chunks" not in path.parts and "transcript" not in path.parts:
                continue
            docs.append(_raw_document(path).to_dict())

    return {
        "index_version": INDEX_VERSION,
        "corpus_type": corpus_type,
        "indexed_at": utc_now_iso8601(),
        "documents": docs,
    }


def iter_corpus_files(corpus_type: str) -> list[Path]:
    if corpus_type == "wiki":
        return [path for path in sorted(WIKI_DIR.rglob("*.md")) if path.name not in {"log.md"}]
    if corpus_type == "raw":
        paths: list[Path] = []
        for path in sorted(RAW_DIR.rglob("*")):
            if path.suffix not in {".md", ".txt"}:
                continue
            if "chunks" not in path.parts and "transcript" not in path.parts:
                continue
            paths.append(path)
        return paths
    raise ValueError(f"unsupported corpus type: {corpus_type}")


def _index_path(corpus_type: str, output_dir: Path | None = None) -> Path:
    root = output_dir or INDEX_DIR
    if corpus_type == "wiki":
        return root / WIKI_INDEX_FILENAME
    if corpus_type == "raw":
        return root / RAW_INDEX_FILENAME
    raise ValueError(f"unsupported corpus type: {corpus_type}")


def write_index(corpus_type: str, output_dir: Path | None = None) -> Path:
    index_path = _index_path(corpus_type, output_dir=output_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_index(corpus_type)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index_path


def load_index(corpus_type: str, output_dir: Path | None = None) -> dict[str, Any]:
    index_path = _index_path(corpus_type, output_dir=output_dir)
    if not index_path.exists():
        raise FileNotFoundError(f"index not found: {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if data.get("index_version") != INDEX_VERSION:
        raise ValueError(
            f"unsupported index version {data.get('index_version')}; expected {INDEX_VERSION}"
        )
    if data.get("corpus_type") != corpus_type:
        raise ValueError(
            f"corpus mismatch in index: {data.get('corpus_type')} != {corpus_type}"
        )
    return data


def index_freshness(
    corpus_type: str,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    index = load_index(corpus_type, output_dir=output_dir)
    corpus_files = iter_corpus_files(corpus_type)
    index_path = _index_path(corpus_type, output_dir=output_dir)
    index_mtime = os.path.getmtime(index_path) if index_path.exists() else 0.0
    newest_corpus_mtime = 0.0
    corpus_rel_paths: set[str] = set()
    for path in corpus_files:
        stat = path.stat()
        newest_corpus_mtime = max(newest_corpus_mtime, stat.st_mtime)
        corpus_rel_paths.add(str(path.relative_to(ROOT)))

    # Fast-path: if corpus files are not newer than index and verbose mode is disabled,
    # return immediately without per-file content hashing.
    if not verbose and newest_corpus_mtime <= index_mtime:
        return {
            "corpus_type": corpus_type,
            "index_path": str(index_path),
            "indexed_at": index.get("indexed_at", ""),
            "index_mtime": index_mtime,
            "newest_corpus_mtime": newest_corpus_mtime,
            "is_stale": False,
            "stale_document_count": 0,
            "missing_document_count": 0,
            "stale_documents": [],
            "missing_documents": [],
            "used_detailed_scan": False,
        }

    index_docs = {doc["path"]: doc for doc in index.get("documents", [])}
    stale_paths: list[str] = []
    missing_paths: list[str] = []
    for path in corpus_files:
        rel = str(path.relative_to(ROOT))
        doc = index_docs.get(rel)
        if doc is None:
            missing_paths.append(rel)
            continue
        stat = path.stat()
        indexed_mtime = float(doc.get("mtime", 0.0))
        if abs(indexed_mtime - stat.st_mtime) > 0.0001:
            stale_paths.append(rel)
            continue
        current_hash = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if doc.get("content_hash") != current_hash:
            stale_paths.append(rel)

    extra_paths = sorted(set(index_docs.keys()) - corpus_rel_paths)
    stale_paths.extend(extra_paths)
    stale_paths = sorted(set(stale_paths))
    is_stale = bool(stale_paths or missing_paths)
    return {
        "corpus_type": corpus_type,
        "index_path": str(index_path),
        "indexed_at": index.get("indexed_at", ""),
        "index_mtime": index_mtime,
        "newest_corpus_mtime": newest_corpus_mtime,
        "is_stale": is_stale,
        "stale_document_count": len(stale_paths),
        "missing_document_count": len(missing_paths),
        "stale_documents": stale_paths[:20],
        "missing_documents": missing_paths[:20],
        "used_detailed_scan": True,
    }
