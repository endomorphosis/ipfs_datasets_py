from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.ontology import (
    CorpusEdgeType,
    CorpusNodeType,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_embeddings import (
    SkillCenterEmbeddingConfig,
    run_skillcenter_embedding_job,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_bm25 import (
    build_skillcenter_bm25_index,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_graphrag import (
    SkillCenterGraphRAGConfig,
    SkillCenterGraphRAGError,
    SkillCenterGraphRAGIndex,
    build_skillcenter_graphrag_index,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterBundleReader,
)


def _write_bundle(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE bundle_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE skills_index (
            skill_id TEXT PRIMARY KEY,
            domain TEXT,
            profile TEXT,
            source_type TEXT,
            source_url TEXT,
            title TEXT,
            overall_score REAL,
            skill_kind TEXT,
            language TEXT,
            source_id TEXT,
            primary_source_id TEXT
        );
        CREATE TABLE skills_content (
            skill_id TEXT PRIMARY KEY,
            metadata_yaml TEXT,
            skill_md TEXT,
            library_md TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO bundle_meta(key, value) VALUES (?, ?)",
        (
            ("bundle_type", "lite"),
            ("created_at", "2026-07-25T00:00:00Z"),
            ("total_skills", "4"),
            ("version", "fixture-v1"),
        ),
    )
    for index, skill_id in enumerate(
        ("skill-alpha", "skill-beta", "skill-gamma", "skill-quarantined")
    ):
        connection.execute(
            "INSERT INTO skills_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill_id,
                "security",
                "security",
                "github",
                f"https://example.test/{skill_id}",
                f"Title {skill_id}",
                5.0 - index,
                "skill-md",
                "en",
                f"source-{skill_id}",
                f"primary-{skill_id}",
            ),
        )
        metadata = (
            "description: no declared license\n"
            if skill_id == "skill-quarantined"
            else "license_spdx: MIT\nlicense_risk: allow\n"
        )
        connection.execute(
            "INSERT INTO skills_content VALUES (?, ?, ?, ?)",
            (
                skill_id,
                metadata,
                f"# {skill_id}\n\nBounded instructions for {skill_id}.\n",
                "",
            ),
        )
    connection.commit()
    connection.close()


def _embed(texts: list[str] | tuple[str, ...]) -> list[list[float]]:
    vectors = []
    for text in texts:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vectors.append([float(value + 1) for value in digest[:4]])
    return vectors


def _build_fixture(tmp_path: Path) -> tuple[SkillCenterBundleReader, Path, Path]:
    bundle_path = tmp_path / "security.sqlite"
    _write_bundle(bundle_path)
    reader = SkillCenterBundleReader(
        bundle_path,
        dataset_id="example/skillcenter",
        dataset_revision="revision-123",
        repository_file="security.sqlite",
    )
    embedding_dir = tmp_path / "embeddings"
    run_skillcenter_embedding_job(
        reader,
        profile="security-lite",
        output_dir=embedding_dir,
        config=SkillCenterEmbeddingConfig(
            model_name="fixture/model",
            provider="fixture",
            device="cpu",
            source_batch_size=2,
            chunk_chars=64,
            chunk_overlap_chars=8,
        ),
        embedder=_embed,
    )
    output_dir = tmp_path / "graphrag"
    return reader, embedding_dir, output_dir


def test_build_load_search_and_graph_retrieval_are_integrity_bound(
    tmp_path: Path,
) -> None:
    pytest.importorskip("faiss")
    reader, embedding_dir, output_dir = _build_fixture(tmp_path)
    summary = build_skillcenter_graphrag_index(
        (reader,),
        embedding_dirs=(embedding_dir,),
        output_dir=output_dir,
        config=SkillCenterGraphRAGConfig(neighbor_k=2),
    )
    loaded = SkillCenterGraphRAGIndex.load(output_dir)

    assert summary.source_records == 4
    assert summary.embedded_skills == 3
    assert summary.vector_count == 3
    assert summary.neighbor_edges == 3
    assert loaded.summary == summary
    assert {
        edge.edge_type
        for edge in loaded.graph.edges
    } >= {CorpusEdgeType.NEIGHBOR_OF, CorpusEdgeType.CONTAINS}
    assert len(
        [
            node
            for node in loaded.graph.nodes
            if node.node_type is CorpusNodeType.SKILL
        ]
    ) == 4
    assert {
        item.stored for item in loaded.graph.source_bodies
    } == {False, True}

    query = _embed(["alpha query"])[0]
    hits = loaded.search_vector(query, k=2)
    assert len(hits) == 2
    assert all(hit.proof_authority is False for hit in hits)
    assert all(hit.authority == "context_only" for hit in hits)
    assert all("skill_md" not in hit.metadata for hit in hits)
    assert all(hit.metadata["graph_digest"] == summary.graph_digest for hit in hits)

    retrieval = loaded.retrieve_skill_neighbors("skill-alpha", k=2)
    assert all(item.proof_authority is False for item in retrieval.premises)
    assert retrieval.snapshot.graph_digest == summary.graph_digest


def test_existing_index_is_reused_and_config_drift_fails_closed(
    tmp_path: Path,
) -> None:
    pytest.importorskip("faiss")
    reader, embedding_dir, output_dir = _build_fixture(tmp_path)
    first = build_skillcenter_graphrag_index(
        (reader,),
        embedding_dirs=(embedding_dir,),
        output_dir=output_dir,
        config=SkillCenterGraphRAGConfig(neighbor_k=1),
    )
    second = build_skillcenter_graphrag_index(
        (reader,),
        embedding_dirs=(embedding_dir,),
        output_dir=output_dir,
        config=SkillCenterGraphRAGConfig(neighbor_k=1),
    )

    assert first == second
    with pytest.raises(SkillCenterGraphRAGError, match="different inputs"):
        build_skillcenter_graphrag_index(
            (reader,),
            embedding_dirs=(embedding_dir,),
            output_dir=output_dir,
            config=SkillCenterGraphRAGConfig(neighbor_k=2),
        )


def test_load_rejects_tampered_index_artifact(tmp_path: Path) -> None:
    pytest.importorskip("faiss")
    reader, embedding_dir, output_dir = _build_fixture(tmp_path)
    build_skillcenter_graphrag_index(
        (reader,),
        embedding_dirs=(embedding_dir,),
        output_dir=output_dir,
    )
    metadata = output_dir / "metadata.parquet"
    metadata.write_bytes(metadata.read_bytes() + b"tampered")

    with pytest.raises(SkillCenterGraphRAGError, match="descriptor"):
        SkillCenterGraphRAGIndex.load(output_dir)


def test_bm25_neighborhoods_regenerate_explainable_graph_edges(
    tmp_path: Path,
) -> None:
    pytest.importorskip("faiss")
    reader, embedding_dir, _output_dir = _build_fixture(tmp_path)
    bm25_dir = tmp_path / "bm25"
    output_dir = tmp_path / "bm25-graphrag"
    build_skillcenter_bm25_index((reader,), output_dir=bm25_dir)

    summary = build_skillcenter_graphrag_index(
        (reader,),
        embedding_dirs=(embedding_dir,),
        bm25_dir=bm25_dir,
        output_dir=output_dir,
        config=SkillCenterGraphRAGConfig(neighbor_k=2),
    )
    loaded = SkillCenterGraphRAGIndex.load(output_dir)
    neighbor_edges = [
        edge
        for edge in loaded.graph.edges
        if edge.edge_type is CorpusEdgeType.NEIGHBOR_OF
    ]

    assert summary.neighbor_backend == "bm25-okapi"
    assert loaded.manifest["bm25_input"]["vocabulary_size"] > 0
    assert neighbor_edges
    assert all(
        edge.properties["retrieval_method"] == "bm25-okapi"
        and edge.properties["score"] > 0
        and edge.properties["matched_terms"]
        for edge in neighbor_edges
    )
