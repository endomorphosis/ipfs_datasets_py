"""Hermetic tests for LCR-071 live Federal Register graph projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ops.legal_data.build_federal_register_live_graph as graph


def _write_body(corpus_dir: Path, legal_id: str, text: str, **extra: object) -> None:
    docno = legal_id.split(":")[1]
    date = legal_id.split(":")[2]
    rel = f"bodies/{legal_id.replace(':', '_')}.json"
    path = corpus_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "legal_id": legal_id,
        "document_number": docno,
        "publication_date": date,
        "official_source_url": f"https://www.govinfo.gov/content/pkg/{docno}.htm",
        "text": text,
        "content_hash": "abc",
        **extra,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with (corpus_dir / "index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "legal_id": legal_id,
                    "path": rel,
                    "status": "verified",
                    "content_hash": "abc",
                }
            )
            + "\n"
        )


def test_missing_corpus_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(graph.LiveGraphError, match="corpus index missing"):
        graph.build_live_graph(
            corpus_dir=tmp_path / "missing",
            graph_dir=tmp_path / "graph",
            require_complete=False,
            write_receipts=False,
        )


def test_tiny_corpus_projects_citations_and_inverts(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_body(
        corpus,
        "fr:2026-04129:2026-03-03",
        "FR Doc No: 2026-04129 cites 40 CFR 52.21 and 42 U.S.C. 7401. "
        "Docket EPA-HQ-OAR-2024-0001 RIN 2060-AU00. See also FR Doc No: 2026-04130.",
    )
    _write_body(
        corpus,
        "fr:2026-04130:2026-03-03",
        "FR Doc No: 2026-04130 related to 40 CFR 52.21.",
    )
    reports = graph.build_live_graph(
        corpus_dir=corpus,
        graph_dir=tmp_path / "graph",
        repository_root=tmp_path / "repo",
        require_complete=False,
        limit=2,
        write_receipts=True,
    )
    graph_report = reports["graph"]
    adjacency = reports["adjacency"]
    assert graph_report["fixture_only"] is False
    assert graph_report["authorizing_hub_upload"] is False
    assert graph_report["edge_count"] > 0
    assert graph_report["node_types"]["document"] == 2
    assert graph_report["node_types"]["citation_cfr"] >= 1
    assert graph_report["adjacency_inversion"] is True
    assert adjacency["fixture_only"] is False
    assert adjacency["dangling_keys"] == 0
    assert (tmp_path / "repo" / graph.GRAPH_RELPATH).is_file()
    assert (tmp_path / "repo" / graph.ADJACENCY_RELPATH).is_file()
