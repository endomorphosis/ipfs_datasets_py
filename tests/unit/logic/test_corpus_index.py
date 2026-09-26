"""Sparse index over a legal ledger. No Hugging Face upload and no dense product."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _index():
    path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "logic" / "autoformal" / "corpus_index.py"
    spec = importlib.util.spec_from_file_location("corpus_index_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sparse_index_keeps_only_shared_citations() -> None:
    module = _index()
    ledger = {
        "edges": [{"kind": "repeal", "source": "amend-21.sec-1.span-1", "target": "amend-18"}],
        "spans": [
            {"id": "amend-21.sec-1.span-1", "unit_id": "amend-21.sec-1", "text": "See 5 U.S.C. 552."},
            {"id": "art-1.sec-1.span-1", "unit_id": "art-1.sec-1", "text": "All legislative Powers shall be vested in a Congress."},
            {"id": "statute-a", "text": "Records under 5 U.S.C. 552."},
            {"id": "statute-b", "text": "A bank under 12 U.S.C. 1."},
        ],
    }
    triples = module.triples_from_ledger(ledger)
    assert {"subject": "amend-21.sec-1.span-1", "predicate": "repeals", "object": "amend-18"} in triples
    legal_id = module.source_legal_id("art-1.sec-1")
    assert legal_id.startswith("oul:constitution:US:us-constitution:")
    assert "1" in legal_id
    links = module.link_source_documents([
        {"id": "art-1.sec-1.span-1", "unit_id": "art-1.sec-1"},
        {"id": "preamble.span-1", "unit_id": "preamble"},
    ])
    assert links[0]["source_dataset"] == module.SOURCE_DATASET
    assert links[0]["source_legal_id"] == legal_id
    assert links[0]["formalized"] is False
    assert len(links) == 1
    indexed = module.sparse_index(triples)
    assert indexed["dense"] is False
    assert any(
        item["predicate"] == "source_document" and item["subject"] == "art-1.sec-1.span-1"
        for item in triples
    )
    assert "statute-a" in indexed["neighbors"]["amend-21.sec-1.span-1"]
    assert "amend-18" in indexed["neighbors"]["amend-21.sec-1.span-1"]
    assert "statute-b" not in indexed["neighbors"]["amend-21.sec-1.span-1"]
    assert len(indexed["neighbors"]["amend-21.sec-1.span-1"]) < len(ledger["spans"])
