from pathlib import Path

from scripts.lib.validation import validate_wiki_markdown_file


def test_low_confidence_approved_requires_caveats(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        (
            "---\n"
            "id: WIKI-TACTIC-9999\n"
            "title: Test Page\n"
            "type: tactic\n"
            "status: active\n"
            "language: pt-BR\n"
            "created_at: 2026-04-09T00:00:00Z\n"
            "updated_at: 2026-04-09T00:00:00Z\n"
            "review_status: approved\n"
            "confidence: low\n"
            "sources:\n"
            "  - SRC-2026-0001\n"
            "topics:\n"
            "  - meta-ads\n"
            "---\n\n"
            "# Test\n\n"
            "Body text. [Sources: SRC-2026-0001 §lesson-01 00:00:00-00:00:10]\n"
        ),
        encoding="utf-8",
    )
    errors = validate_wiki_markdown_file(page)
    assert any("## Caveats" in err for err in errors)


def test_citation_marker_pattern_validation(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        (
            "---\n"
            "id: WIKI-TACTIC-9998\n"
            "title: Test Page 2\n"
            "type: tactic\n"
            "status: active\n"
            "language: pt-BR\n"
            "created_at: 2026-04-09T00:00:00Z\n"
            "updated_at: 2026-04-09T00:00:00Z\n"
            "review_status: proposed\n"
            "confidence: medium\n"
            "sources:\n"
            "  - SRC-2026-0001\n"
            "topics:\n"
            "  - meta-ads\n"
            "---\n\n"
            "# Test\n\n"
            "Bad citation [Sources SRC-2026-0001]\n"
        ),
        encoding="utf-8",
    )
    errors = validate_wiki_markdown_file(page)
    assert any("malformed citation marker" in err for err in errors)
