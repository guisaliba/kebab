from pathlib import Path

from scripts.lib.indexing import derive_retrieval_role
from scripts.lib.paths import ROOT


def test_explicit_retrieval_role_takes_precedence() -> None:
    path = ROOT / "wiki" / "platforms" / "meta-ads.md"
    role = derive_retrieval_role(path, {"type": "platform", "retrieval_role": "auxiliary"}, corpus_type="wiki")
    assert role == "auxiliary"


def test_derived_navigation_role_for_index_page() -> None:
    path = ROOT / "wiki" / "index.md"
    role = derive_retrieval_role(path, {}, corpus_type="wiki")
    assert role == "navigation"


def test_derived_answerable_and_auxiliary_roles() -> None:
    platform_path = ROOT / "wiki" / "platforms" / "meta-ads.md"
    source_note_path = ROOT / "wiki" / "source-notes" / "src-2026-0001-meta-ads-course-module-1.md"
    assert derive_retrieval_role(platform_path, {"type": "platform"}, corpus_type="wiki") == "answerable"
    assert derive_retrieval_role(source_note_path, {"type": "source-note"}, corpus_type="wiki") == "auxiliary"
