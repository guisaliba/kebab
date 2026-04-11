import json
import subprocess
import sys
from pathlib import Path

from scripts.lib.indexing import INDEX_VERSION
from scripts.lib.paths import ROOT


def test_index_refresh_creates_versioned_fielded_schema() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "index" / "main.py"),
            "--target",
            "all",
            "--rebuild",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    wiki_index = ROOT / "exports" / "indexes" / "wiki.index.json"
    raw_index = ROOT / "exports" / "indexes" / "raw.index.json"
    assert wiki_index.exists()
    assert raw_index.exists()

    wiki_payload = json.loads(wiki_index.read_text(encoding="utf-8"))
    assert wiki_payload["index_version"] == INDEX_VERSION
    assert wiki_payload["corpus_type"] == "wiki"
    assert "indexed_at" in wiki_payload
    assert len(wiki_payload["documents"]) >= 1

    sample_doc = wiki_payload["documents"][0]
    for field in (
        "path",
        "mtime",
        "content_hash",
        "filename",
        "title",
        "headings",
        "frontmatter",
        "body_text",
        "citations_present",
        "confidence",
        "page_type",
        "retrieval_role",
        "normalized_fields",
    ):
        assert field in sample_doc
    for normalized_field in ("title", "headings", "filename", "frontmatter", "body"):
        assert normalized_field in sample_doc["normalized_fields"]
