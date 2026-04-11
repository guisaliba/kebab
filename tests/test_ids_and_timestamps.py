from scripts.lib.ids import (
    validate_page_type,
    validate_review_id,
    validate_source_id,
    validate_wiki_id,
)
from scripts.lib.time import is_iso8601_utc


def test_id_patterns() -> None:
    assert validate_source_id("SRC-2026-0001")
    assert not validate_source_id("SRC-26-1")
    assert validate_review_id("REV-2026-0002")
    assert not validate_review_id("REV-2026-ABC2")


def test_wiki_id_tied_to_page_type() -> None:
    assert validate_page_type("source-note")
    assert validate_wiki_id("WIKI-SOURCE_NOTE-0001", "source-note")
    assert not validate_wiki_id("WIKI-TACTIC-0001", "source-note")


def test_iso_8601_utc() -> None:
    assert is_iso8601_utc("2026-04-09T20:31:00Z")
    assert not is_iso8601_utc("2026-04-09")
