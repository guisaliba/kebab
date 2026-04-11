import re
from pathlib import Path
from typing import Iterable


SRC_ID_RE = re.compile(r"^SRC-\d{4}-\d{4}$")
REV_ID_RE = re.compile(r"^REV-\d{4}-\d{4}$")

ALLOWED_PAGE_TYPES = {
    "overview",
    "concept",
    "tactic",
    "playbook",
    "platform",
    "metric",
    "framework",
    "creator",
    "source-note",
    "comparison",
    "qa",
    "decision",
}

PAGE_TYPE_TO_WIKI_TOKEN = {page_type: page_type.replace("-", "_").upper() for page_type in ALLOWED_PAGE_TYPES}
WIKI_ID_RE = re.compile(r"^WIKI-([A-Z_]+)-(\d{4})$")


def validate_source_id(source_id: str) -> bool:
    return bool(SRC_ID_RE.fullmatch(source_id))


def validate_review_id(review_id: str) -> bool:
    return bool(REV_ID_RE.fullmatch(review_id))


def validate_page_type(page_type: str) -> bool:
    return page_type in ALLOWED_PAGE_TYPES


def validate_wiki_id(wiki_id: str, page_type: str) -> bool:
    match = WIKI_ID_RE.fullmatch(wiki_id)
    if not match:
        return False
    expected_token = PAGE_TYPE_TO_WIKI_TOKEN.get(page_type)
    if expected_token is None:
        return False
    return match.group(1) == expected_token


def next_review_id(existing_review_dirs: Iterable[Path], year: int) -> str:
    max_num = 0
    for review_dir in existing_review_dirs:
        name = review_dir.name
        match = REV_ID_RE.fullmatch(name)
        if not match:
            continue
        if not name.startswith(f"REV-{year}-"):
            continue
        max_num = max(max_num, int(name[-4:]))
    return f"REV-{year}-{max_num + 1:04d}"


def next_wiki_id(existing_ids: Iterable[str], page_type: str) -> str:
    token = PAGE_TYPE_TO_WIKI_TOKEN[page_type]
    prefix = f"WIKI-{token}-"
    max_num = 0
    for wiki_id in existing_ids:
        if not wiki_id.startswith(prefix):
            continue
        suffix = wiki_id[-4:]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    return f"{prefix}{max_num + 1:04d}"
