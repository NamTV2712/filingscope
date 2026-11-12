import json

import pytest

from src.retrieval.canonical_json import sha256_file
from src.retrieval.pdf_page_cache import FrozenPdfPages


def test_frozen_page_cache_rejects_changed_content(tmp_path):
    path = tmp_path / "pages.jsonl"
    path.write_text(json.dumps({"doc_name": "report", "page_number": 2, "text": "filing"}) + "\n", encoding="utf-8")
    expected = sha256_file(path)
    indexed = FrozenPdfPages(path, expected_sha256=expected)
    assert indexed.get("different-filing", 2) is None
    changed = path.read_text(encoding="utf-8").replace("filing", "edited")
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(ValueError, match="changed after index validation"):
        indexed.get("report", 2)
    with pytest.raises(ValueError, match="pinned extraction"):
        FrozenPdfPages(path, expected_sha256=expected)
