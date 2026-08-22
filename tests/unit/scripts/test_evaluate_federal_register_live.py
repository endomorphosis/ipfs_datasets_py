"""Hermetic tests for LCR-071 live BM25 self-retrieval evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ops.legal_data.evaluate_federal_register_live as ev


def _write_index(index_dir: Path) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    docs = [
        {"legal_id": "fr:2026-04129:2026-03-03", "token_count": 10, "unique_terms": 4},
        {"legal_id": "fr:2026-04130:2026-03-03", "token_count": 8, "unique_terms": 3},
    ]
    (index_dir / "documents.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in docs), encoding="utf-8"
    )
    triples = [
        {"term": "2026-04129", "legal_id": "fr:2026-04129:2026-03-03", "tf": 2},
        {"term": "2026-04130", "legal_id": "fr:2026-04130:2026-03-03", "tf": 2},
        {"term": "federal", "legal_id": "fr:2026-04129:2026-03-03", "tf": 3},
        {"term": "federal", "legal_id": "fr:2026-04130:2026-03-03", "tf": 3},
    ]
    (index_dir / "posting_triples.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in triples), encoding="utf-8"
    )
    (index_dir / "manifest.json").write_text(
        json.dumps(
            {
                "documents": 2,
                "avg_doc_tokens": 9.0,
                "triples_path": str(index_dir / "posting_triples.jsonl"),
                "authorizing_hub_upload": False,
            }
        ),
        encoding="utf-8",
    )


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ev.LiveEvalError, match="required receipt missing"):
        ev.evaluate_live(
            index_dir=tmp_path / "missing",
            corpus_dir=tmp_path,
            require_complete=False,
            write_receipt=False,
        )


def test_document_number_self_retrieval_passes(tmp_path: Path) -> None:
    index_dir = tmp_path / "bm25"
    _write_index(index_dir)
    repo = tmp_path / "repo"
    graph_path = repo / ev.GRAPH_RELPATH
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(
        json.dumps(
            {
                "fixture_only": False,
                "node_count": 4,
                "edge_count": 3,
                "adjacency_inversion": True,
            }
        ),
        encoding="utf-8",
    )
    report = ev.evaluate_live(
        index_dir=index_dir,
        corpus_dir=tmp_path,
        repository_root=repo,
        sample_size=2,
        require_complete=False,
        write_receipt=True,
    )
    assert report["fixture_only"] is False
    assert report["live_canary"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["bm25"]["recall_at_1"] == 1.0
    assert report["status"] == "passed"
    assert (repo / ev.EVAL_RELPATH).is_file()
