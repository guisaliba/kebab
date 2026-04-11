from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import yaml


@dataclass
class MarkdownDocument:
    frontmatter: dict[str, Any]
    body: str


def _normalize_yaml_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    if isinstance(value, dict):
        return {key: _normalize_yaml_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_normalize_yaml_value(item) for item in value]
    return value


def parse_markdown_with_frontmatter(content: str) -> MarkdownDocument:
    if not content.startswith("---\n"):
        raise ValueError("markdown file missing frontmatter start")
    parts = content.split("\n---\n", 1)
    if len(parts) != 2:
        raise ValueError("markdown file missing frontmatter closing delimiter")
    raw_frontmatter = parts[0][4:]
    body = parts[1]
    data = _normalize_yaml_value(yaml.safe_load(raw_frontmatter) or {})
    if not isinstance(data, dict):
        raise ValueError("frontmatter must parse to a mapping")
    return MarkdownDocument(frontmatter=data, body=body)


def dump_markdown_with_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    serialized = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{serialized}\n---\n\n{body.lstrip()}"
