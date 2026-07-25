import sqlite3
import hashlib
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus import (
    SkillCenterCorpusError,
    SkillCenterCorpusIndex,
    build_skillcenter_corpus,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_corpus_bm25 import (
    SkillCenterCorpusBM25Index,
    build_skillcenter_corpus_bm25,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_cid_graph import (
    SkillCenterCIDGraphConfig,
    SkillCenterCIDGraphIndex,
    build_skillcenter_cid_graph,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_cid_vectors import (
    SkillCenterCIDVectorIndex,
    build_skillcenter_cid_vector_index,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_embeddings import (
    SkillCenterEmbeddingConfig,
    iter_skillcenter_embedding_rows,
    run_skillcenter_embedding_job,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterBundleReader,
)


def _bundle(path: Path, *, skill_id: str, declared: int = 1) -> None:
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
        "INSERT INTO bundle_meta VALUES (?, ?)",
        (
            ("bundle_type", "lite"),
            ("created_at", "2026-07-25T00:00:00Z"),
            ("total_skills", str(declared)),
            ("version", "fixture-v1"),
        ),
    )
    connection.execute(
        "INSERT INTO skills_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            skill_id,
            "security",
            "security",
            "github",
            f"https://example.test/{skill_id}",
            f"Title {skill_id}",
            4.0,
            "github",
            "en",
            f"source-{skill_id}",
            f"primary-{skill_id}",
        ),
    )
    connection.execute(
        "INSERT INTO skills_content VALUES (?, ?, ?, ?)",
        (
            skill_id,
            "license_spdx: MIT\n",
            f"# {skill_id}\n\nVerify the result.",
            "",
        ),
    )
    connection.commit()
    connection.close()


def _readers(tmp_path: Path) -> list[SkillCenterBundleReader]:
    paths = [tmp_path / "b.sqlite", tmp_path / "a.sqlite"]
    _bundle(paths[0], skill_id="skill-b")
    _bundle(paths[1], skill_id="skill-a", declared=99)
    return [
        SkillCenterBundleReader(
            path,
            dataset_revision="revision-fixture",
            repository_file=path.name,
            allow_declared_count_mismatch=True,
        )
        for path in paths
    ]


def test_builds_verified_cid_primary_key_corpus(tmp_path: Path) -> None:
    output = tmp_path / "corpus"

    summary = build_skillcenter_corpus(
        _readers(tmp_path),
        output_dir=output,
        batch_size=1,
    )
    loaded = SkillCenterCorpusIndex.load(output)
    rows = list(loaded.iter_rows())

    assert summary.source_records == 2
    assert summary.unique_entry_cids == 2
    assert len(loaded.entry_cids) == 2
    assert [row["corpus_index"] for row in rows] == [0, 1]
    assert all(row["entry_cid"].startswith("bafk") for row in rows)
    assert all(row["entry_multihash"] for row in rows)
    assert all(row["skill_md"] for row in rows)
    assert [row["entry_cid"] for row in loaded.cid_rows] == sorted(
        row["entry_cid"] for row in rows
    )
    assert (
        pq.read_schema(output / "corpus.parquet").metadata[b"primary_key"]
        == b"entry_cid"
    )
    assert loaded.manifest["inputs"][0]["declared_total_skills"] == 99
    assert loaded.manifest["inputs"][0]["total_skills"] == 1


def test_rejects_tampered_corpus_bytes(tmp_path: Path) -> None:
    output = tmp_path / "corpus"
    build_skillcenter_corpus(_readers(tmp_path), output_dir=output)
    path = output / "corpus.parquet"
    payload = bytearray(path.read_bytes())
    payload[len(payload) // 2] ^= 1
    path.write_bytes(payload)

    with pytest.raises(SkillCenterCorpusError, match="identity mismatch"):
        SkillCenterCorpusIndex.load(output)


def test_full_corpus_bm25_uses_entry_cid_primary_key(tmp_path: Path) -> None:
    corpus_output = tmp_path / "corpus"
    bm25_output = tmp_path / "bm25"
    build_skillcenter_corpus(_readers(tmp_path), output_dir=corpus_output)

    summary = build_skillcenter_corpus_bm25(
        corpus_output,
        output_dir=bm25_output,
    )
    index = SkillCenterCorpusBM25Index.load(
        bm25_output,
        corpus_dir=corpus_output,
    )
    hit = index.search("verify result", k=1)[0]

    assert summary.indexed_entries == 2
    assert summary.primary_key == "entry_cid"
    assert hit.entry_cid in SkillCenterCorpusIndex.load(
        corpus_output, verify_rows=False
    ).entry_cids
    assert hit.matched_terms == ("result", "verify")
    assert hit.proof_authority is False
    assert index.entry_neighbors(hit.entry_cid, k=1)


def test_cid_graph_resumes_and_uses_bm25_entry_edges(tmp_path: Path) -> None:
    corpus_output = tmp_path / "corpus"
    bm25_output = tmp_path / "bm25"
    graph_output = tmp_path / "graph"
    build_skillcenter_corpus(_readers(tmp_path), output_dir=corpus_output)
    build_skillcenter_corpus_bm25(
        corpus_output,
        output_dir=bm25_output,
    )
    config = SkillCenterCIDGraphConfig(
        neighbor_k=1,
        batch_size=1,
        query_workers=2,
    )

    partial = build_skillcenter_cid_graph(
        corpus_output,
        bm25_output,
        output_dir=graph_output,
        config=config,
        max_neighbor_sources=1,
    )
    assert isinstance(partial, dict)
    assert partial["complete"] is False
    summary = build_skillcenter_cid_graph(
        corpus_output,
        bm25_output,
        output_dir=graph_output,
        config=config,
    )
    assert not isinstance(summary, dict)
    graph = SkillCenterCIDGraphIndex.load(
        graph_output,
        corpus_dir=corpus_output,
        bm25_dir=bm25_output,
    )
    entry_cid = next(iter(SkillCenterCorpusIndex.load(
        corpus_output, verify_rows=False
    ).entry_cids))

    assert summary.skill_nodes == 2
    assert summary.neighbor_edges == 2
    assert graph.manifest["primary_key"] == "entry_cid"
    assert graph.neighbors(entry_cid, k=1)[0]["entry_cid"] != entry_cid


def test_faiss_id_map_joins_vectors_by_entry_cid(tmp_path: Path) -> None:
    readers = _readers(tmp_path)
    corpus_output = tmp_path / "corpus"
    build_skillcenter_corpus(readers, output_dir=corpus_output)
    embedding_dirs = []
    config = SkillCenterEmbeddingConfig(
        model_name="fixture/model",
        provider="fixture",
        device="cpu",
        source_batch_size=1,
        chunk_chars=64,
        chunk_overlap_chars=0,
        internal_retrieval_all_records=True,
        max_chunks_per_record=1,
    )

    def embed(texts: list[str]) -> list[list[float]]:
        return [
            [
                float(value)
                for value in hashlib.sha256(text.encode()).digest()[:3]
            ]
            for text in texts
        ]

    for index, reader in enumerate(readers):
        output = tmp_path / f"embeddings-{index}"
        run_skillcenter_embedding_job(
            reader,
            profile=f"fixture-{index}",
            output_dir=output,
            config=config,
            embedder=embed,
        )
        embedding_dirs.append(output)
    vector_output = tmp_path / "vectors"
    summary = build_skillcenter_cid_vector_index(
        corpus_output,
        embedding_dirs,
        output_dir=vector_output,
    )
    vector_index = SkillCenterCIDVectorIndex.load(
        vector_output,
        corpus_dir=corpus_output,
    )
    first_embedding = next(
        iter_skillcenter_embedding_rows(embedding_dirs[0])
    )
    hit = vector_index.search_vector(first_embedding["embedding"], k=1)[0]

    assert summary.vector_count == 2
    assert summary.primary_key == "entry_cid"
    assert hit.entry_cid == first_embedding["entry_cid"]
