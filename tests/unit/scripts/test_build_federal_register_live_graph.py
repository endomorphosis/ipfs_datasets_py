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
    assert graph_report["embedding_neighbors"] is None
    assert "EMBEDDING_NEIGHBOR_OF" not in graph_report["edge_types"]


def _write_gte_small_vectors(vector_dir: Path, legal_ids: list[str]) -> None:
    import numpy as np

    from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
        PINNED_DIMENSION,
        PINNED_MODEL_ID,
        PINNED_MODEL_REVISION,
        PRODUCTION_BACKEND,
        default_vector_space_id,
    )

    vector_dir.mkdir(parents=True, exist_ok=True)
    matrix = np.zeros((len(legal_ids), PINNED_DIMENSION), dtype=np.float32)
    for index, _legal_id in enumerate(legal_ids):
        matrix[index, index % PINNED_DIMENSION] = 1.0
        if index > 0:
            matrix[index, 0] = 0.2
            matrix[index] = matrix[index] / float(np.linalg.norm(matrix[index]))
    np.save(vector_dir / "vectors.npy", matrix)
    (vector_dir / "ids.jsonl").write_text(
        "".join(
            json.dumps({"legal_id": legal_id, "row": index}) + "\n"
            for index, legal_id in enumerate(legal_ids)
        ),
        encoding="utf-8",
    )
    (vector_dir / "manifest.json").write_text(
        json.dumps(
            {
                "backend": PRODUCTION_BACKEND,
                "dimension": PINNED_DIMENSION,
                "model_id": PINNED_MODEL_ID,
                "model_revision": PINNED_MODEL_REVISION,
                "vector_count": len(legal_ids),
                "vector_space_id": default_vector_space_id(),
                "config_cid": "sha256:" + ("ab" * 32),
                "vectors_path": str(vector_dir / "vectors.npy"),
                "ids_path": str(vector_dir / "ids.jsonl"),
            }
        ),
        encoding="utf-8",
    )


def test_tiny_corpus_projects_gte_small_embedding_neighbors(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_body(
        corpus,
        "fr:2026-04129:2026-03-03",
        "FR Doc No: 2026-04129 cites 40 CFR 52.21.",
    )
    _write_body(
        corpus,
        "fr:2026-04130:2026-03-03",
        "FR Doc No: 2026-04130 related to 40 CFR 52.21.",
    )
    vectors = tmp_path / "vectors"
    _write_gte_small_vectors(
        vectors,
        ["fr:2026-04129:2026-03-03", "fr:2026-04130:2026-03-03"],
    )
    reports = graph.build_live_graph(
        corpus_dir=corpus,
        graph_dir=tmp_path / "graph",
        repository_root=tmp_path / "repo",
        require_complete=False,
        limit=2,
        write_receipts=False,
        vectors_dir=vectors,
    )
    graph_report = reports["graph"]
    assert graph_report["edge_types"]["EMBEDDING_NEIGHBOR_OF"] >= 2
    neighbors = graph_report["embedding_neighbors"]
    assert neighbors is not None
    assert neighbors["backend"] == "sentence_transformers"
    assert neighbors["model_id"] == "thenlper/gte-small"
    assert neighbors["metric"] == "gte-small-cosine"
    assert neighbors["kept_edge_count"] >= 2
    assert graph_report["adjacency_inversion"] is True
    assert reports["adjacency"]["similarity_cannot_establish_legal_authority"] is True


def test_complete_live_graph_without_gte_small_vectors_fails_closed(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_body(corpus, "fr:2026-04129:2026-03-03", "notice body")
    with pytest.raises(graph.LiveGraphError, match="GTE-small"):
        graph.build_live_graph(
            corpus_dir=corpus,
            graph_dir=tmp_path / "graph",
            require_complete=True,
            write_receipts=False,
            vectors_dir=tmp_path / "missing-vectors",
        )
