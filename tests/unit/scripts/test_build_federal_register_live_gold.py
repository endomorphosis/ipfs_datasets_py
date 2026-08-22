"""Hermetic tests for LCR-071 live identity gold."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ops.legal_data.build_federal_register_live_gold as gold


def test_missing_corpus_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(gold.LiveGoldError, match="corpus index missing"):
        gold.build_live_gold(
            corpus_dir=tmp_path / "missing",
            graph_dir=tmp_path / "graph",
            require_complete=False,
            write_receipt=False,
        )


def test_identity_queries_are_not_fixture(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    rows = [
        {"legal_id": "fr:2026-04129:2026-03-03", "status": "verified"},
        {"legal_id": "fr:2026-04130:2026-03-03", "status": "verified"},
        {"legal_id": "fr:2026-04131:2026-03-03", "status": "verified"},
    ]
    (corpus / "index.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    graph = tmp_path / "graph"
    graph.mkdir()
    edges = [
        {
            "source": "document:fr:2026-04129:2026-03-03",
            "edge_type": "CITES",
            "target": "citation:cfr:40:52.21",
        },
        {
            "source": "document:fr:2026-04130:2026-03-03",
            "edge_type": "CITES",
            "target": "citation:cfr:40:52.21",
        },
        {
            "source": "document:fr:2026-04131:2026-03-03",
            "edge_type": "CITES",
            "target": "citation:cfr:40:52.21",
        },
    ]
    (graph / "edges.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in edges), encoding="utf-8"
    )
    report = gold.build_live_gold(
        corpus_dir=corpus,
        graph_dir=graph,
        repository_root=tmp_path / "repo",
        exact_queries=2,
        citation_queries=1,
        require_complete=False,
        write_receipt=True,
    )
    assert report["fixture_only"] is False
    assert report["human_authored"] is False
    assert report["exact_document_queries"] == 2
    assert report["citation_queries"] == 1
    assert report["queries"][-1]["text"] == "40 CFR 52.21"
    assert (tmp_path / "repo" / gold.GOLD_RELPATH).is_file()
