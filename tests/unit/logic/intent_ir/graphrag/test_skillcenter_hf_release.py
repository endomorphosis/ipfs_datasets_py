from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import numpy as np
import pyarrow as pa
import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag import skillcenter_hf_release as release
from scripts.ops.intent_ir.query_skillcenter_hf import (
    ArtifactResolver,
    RemoteQueryError,
    SkillCenterRemoteIndex,
    _vector_routing_groups,
)


def _meta(
    path: Path,
    root: Path,
    *,
    kind: str,
    first_key: str,
    last_key: str,
    row_count: int,
    **extra: object,
) -> dict[str, object]:
    return release._shard_meta_row(
        path,
        root=root,
        shard_id=0,
        row_count=row_count,
        first_key=first_key,
        last_key=last_key,
        start_document_index=0,
        end_document_index=max(0, row_count - 1),
        kind=kind,
        **extra,
    )


def test_decode_fts5_varints_and_idf_floor() -> None:
    assert release._decode_fts5_varints(bytes([4, 0x86, 0x61])) == (4, 865)
    assert release._fts5_idf(10, 1) > 0
    assert release._fts5_idf(10, 9) == 1.0e-6


def test_bm25_posting_export_preserves_column_frequencies() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE VIRTUAL TABLE documents_fts USING fts5("
        "title, body, content='', columnsize=1, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    connection.executemany(
        "INSERT INTO documents_fts(rowid, title, body) VALUES (?, ?, ?)",
        [
            (1, "secure rotate", "secure credential"),
            (2, "rotate", "credential credential"),
        ],
    )
    connection.execute(
        "CREATE VIRTUAL TABLE documents_vocab USING "
        "fts5vocab(documents_fts, 'instance')"
    )
    connection.execute(
        "CREATE VIRTUAL TABLE vocab_row USING "
        "fts5vocab(documents_fts, 'row')"
    )
    terms = [
        str(row[0])
        for row in connection.execute(
            "SELECT term FROM vocab_row ORDER BY term"
        )
    ]
    rows, postings, instances = release._bm25_posting_rows(
        connection,
        first_term=terms[0],
        last_term=terms[-1],
        expected_terms=terms,
        document_lengths=[(2, 2, 4), (1, 2, 3)],
        document_count=2,
    )
    secure = next(row for row in rows if row["term"] == "secure")
    assert secure["document_indices"] == [0]
    assert secure["title_frequencies"] == [1]
    assert secure["body_frequencies"] == [1]
    assert postings == 5
    assert instances == 7


def test_partition_bm25_rows_keeps_term_groups_together() -> None:
    rows = [
        {"term": "a", "document_indices": [index]}
        for index in range(release.RELEASE_CHUNK_ROWS - 1)
    ]
    rows.extend(
        [
            {"term": "b", "document_indices": [1]},
            {"term": "b", "document_indices": [2]},
        ]
    )
    parts = list(release._partition_bm25_rows(rows))
    assert [len(part) for part in parts] == [
        release.RELEASE_CHUNK_ROWS - 1,
        2,
    ]
    assert {row["term"] for row in parts[1]} == {"b"}


def test_balanced_vector_shard_capacities_use_minimum_shard_count() -> None:
    assert release._balanced_shard_capacities(10, max_rows=4) == (4, 3, 3)
    capacities = release._balanced_shard_capacities(216_972)
    assert len(capacities) == 53
    assert set(capacities) == {4093, 4094}
    assert sum(capacities) == 216_972


def test_capacity_constrained_vector_assignment_retains_best_proposals() -> None:
    preferences = np.asarray([[0, 1]] * 6, dtype=np.int32)
    scores = np.asarray(
        [
            [0.90, 0.10],
            [0.80, 0.20],
            [0.70, 0.30],
            [0.60, 0.40],
            [0.50, 0.50],
            [0.40, 0.60],
        ],
        dtype=np.float32,
    )
    assignments = release._capacity_constrained_assignments(
        scores,
        preferences,
        (3, 3),
        np=np,
    )
    assert assignments.tolist() == [0, 0, 0, 1, 1, 1]


def test_vector_routing_centroid_points_to_at_most_two_sorted_shards() -> None:
    rows = [
        {
            "centroid": [1.0, 0.0],
            "centroid_shard_count": 2,
            "chunk_in_cluster": chunk,
            "cluster_id": 0,
            "shard_id": chunk,
        }
        for chunk in (0, 1)
    ]
    config = {
        "layout": "semantic_centroid_groups",
        "max_shards_per_centroid": 2,
    }
    groups = _vector_routing_groups(rows, config)
    assert len(groups) == 1
    assert [row["shard_id"] for row in groups[0]["shards"]] == [0, 1]

    malformed = [
        {
            **row,
            "centroid_shard_count": 3,
        }
        for row in rows
    ]
    malformed.append(
        {
            **malformed[-1],
            "chunk_in_cluster": 2,
            "shard_id": 2,
        }
    )
    with pytest.raises(RemoteQueryError):
        _vector_routing_groups(malformed, config)


def test_retarget_release_regenerates_publication_support_and_omits_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    output = tmp_path / "publicus"
    data_path = source / "data" / "corpus" / "part-000000.parquet"
    index_path = source / "indexes" / "corpus_chunks.parquet"
    data_path.parent.mkdir(parents=True)
    index_path.parent.mkdir(parents=True)
    data_path.write_bytes(b"immutable parquet placeholder")
    index_path.write_bytes(b"immutable index placeholder")
    cache_path = source / "scripts" / "__pycache__" / "client.pyc"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"do not publish")
    (source / "README.md").write_text("old card", encoding="utf-8")

    manifest = {
        "counts": {
            "bm25_postings": 1,
            "bm25_terms": 1,
            "corpus_rows": 1,
            "graph_edges": 1,
            "graph_nodes": 1,
            "vector_rows": 1,
        },
        "dataset_id": "Tommysha/skillcenter-bundles",
        "dataset_repo_id": "Tommysha/skillcenter-ir",
        "dataset_revision": "source-revision",
        "files": {},
        "indexes": {},
        "parquet": {"max_rows_per_file": 4096},
        "primary_key": "entry_cid",
        "schema_version": release.SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        "vector": {"dimension": 384, "model_name": "thenlper/gte-small"},
    }
    source_manifest = release.canonical_json_bytes(manifest)
    (source / "manifest.json").write_bytes(source_manifest)

    query_script = tmp_path / "query_skillcenter_hf.py"
    query_script.write_text(
        'DEFAULT_REPO_ID = "Publicus/skillcenter-ir"\n',
        encoding="utf-8",
    )
    semantic_module = tmp_path / "semantic_traversal.py"
    semantic_module.write_text("def walk():\n    return []\n", encoding="utf-8")
    skill_dir = tmp_path / "query-skillcenter-hf"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: query-skillcenter-hf\n"
        "description: Query the Publicus SkillCenter release.\n"
        "---\n\n"
        "Use `Publicus/skillcenter-ir`.\n",
        encoding="utf-8",
    )
    skill_cache = skill_dir / "__pycache__" / "helper.pyc"
    skill_cache.parent.mkdir()
    skill_cache.write_bytes(b"do not publish")

    def _validated(root: str | Path) -> release.SkillCenterHFReleaseSummary:
        release_root = Path(root)
        current = json.loads((release_root / "manifest.json").read_bytes())
        assert current["dataset_repo_id"] == "Publicus/skillcenter-ir"
        return release.SkillCenterHFReleaseSummary(
            output_dir=str(release_root),
            dataset_repo_id=current["dataset_repo_id"],
            dataset_revision=current["dataset_revision"],
            corpus_rows=1,
            bm25_terms=1,
            bm25_postings=1,
            graph_nodes=1,
            graph_edges=1,
            vector_rows=1,
            vector_chunks=1,
            manifest_sha256=release._sha256_file(
                release_root / "manifest.json"
            ),
        )

    monkeypatch.setattr(
        release,
        "validate_skillcenter_hf_release",
        _validated,
    )
    summary = release.retarget_skillcenter_hf_release(
        source,
        output_dir=output,
        dataset_repo_id="Publicus/skillcenter-ir",
        query_script=query_script,
        skill_dir=skill_dir,
        semantic_traversal_module=semantic_module,
    )

    target_manifest = json.loads((output / "manifest.json").read_bytes())
    assert target_manifest["dataset_repo_id"] == "Publicus/skillcenter-ir"
    assert target_manifest["publication"] == {
        "source_dataset_repo_id": "Tommysha/skillcenter-ir",
        "source_manifest_sha256": release._sha256_file(
            source / "manifest.json"
        ),
        "target_dataset_repo_id": "Publicus/skillcenter-ir",
    }
    assert "Publicus/skillcenter-ir" in (output / "README.md").read_text()
    assert "Publicus/skillcenter-ir" in (
        output / "skill" / skill_dir.name / "SKILL.md"
    ).read_text()
    assert not list(output.rglob("*.pyc"))
    assert not list(output.rglob("__pycache__"))
    assert data_path.stat().st_ino == (
        output / data_path.relative_to(source)
    ).stat().st_ino
    assert json.loads((source / "manifest.json").read_bytes()) == manifest
    assert summary.output_dir == str(output)


def test_graph_adjacency_pages_are_bounded() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE nodes (
            node_cid TEXT PRIMARY KEY,
            node_type TEXT NOT NULL
        );
        CREATE TABLE edges (
            edge_cid TEXT PRIMARY KEY,
            edge_type TEXT NOT NULL,
            source_cid TEXT NOT NULL,
            target_cid TEXT NOT NULL,
            retrieval_method TEXT NOT NULL,
            score REAL
        );
        """
    )
    connection.executemany(
        "INSERT INTO nodes(node_cid, node_type) VALUES (?, ?)",
        [("cid-source", "SKILL"), ("cid-target", "SKILL")],
    )
    connection.executemany(
        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                f"edge-{index:05d}",
                "RELATED_TO",
                "cid-source",
                "cid-target",
                "test",
                float(5000 - index),
            )
            for index in range(4100)
        ],
    )
    pages = list(
        release._iter_graph_adjacency_rows(
            connection,
            direction="outgoing",
        )
    )
    assert [row["neighbor_count"] for row in pages] == [4096, 4]
    assert [row["page_index"] for row in pages] == [0, 1]
    assert {row["page_count"] for row in pages} == {2}
    assert {row["total_neighbor_count"] for row in pages} == {4100}


def test_local_remote_graph_node_neighbors_and_bounded_walk(
    tmp_path: Path,
) -> None:
    root = tmp_path / "graph-release"
    database = tmp_path / "graph.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE nodes (
            node_cid TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            entry_cid TEXT,
            label TEXT NOT NULL,
            properties_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE edges (
            edge_cid TEXT PRIMARY KEY,
            edge_type TEXT NOT NULL,
            source_cid TEXT NOT NULL,
            target_cid TEXT NOT NULL,
            retrieval_method TEXT NOT NULL,
            score REAL,
            query_terms_json TEXT NOT NULL,
            properties_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        ) WITHOUT ROWID;
        """
    )
    connection.executemany(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("cid-a", "SKILL", "cid-a", "Skill A", "{}", "node/v1"),
            ("cid-b", "SKILL", "cid-b", "Skill B", "{}", "node/v1"),
            ("cid-c", "DOMAIN", None, "security", "{}", "node/v1"),
        ],
    )
    connection.executemany(
        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "edge-1",
                "BM25_NEIGHBOR_OF",
                "cid-a",
                "cid-b",
                "bm25-okapi",
                10.0,
                "[]",
                "{}",
                "edge/v1",
            ),
            (
                "edge-2",
                "IN_DOMAIN",
                "cid-a",
                "cid-c",
                "",
                None,
                "[]",
                "{}",
                "edge/v1",
            ),
            (
                "edge-3",
                "BM25_NEIGHBOR_OF",
                "cid-b",
                "cid-a",
                "bm25-okapi",
                8.0,
                "[]",
                "{}",
                "edge/v1",
            ),
        ],
    )
    connection.commit()
    connection.close()

    node_meta = release._export_graph_table(
        database,
        table_name="nodes",
        order_column="node_cid",
        output_root=root,
        progress_callback=None,
    )
    edge_meta = release._export_graph_table(
        database,
        table_name="edges",
        order_column="edge_cid",
        output_root=root,
        progress_callback=None,
    )
    outgoing_meta, _ = release._export_graph_adjacency(
        database,
        direction="outgoing",
        output_root=root,
        progress_callback=None,
    )
    incoming_meta, _ = release._export_graph_adjacency(
        database,
        direction="incoming",
        output_root=root,
        progress_callback=None,
    )
    index_dir = root / "indexes"
    index_dir.mkdir(parents=True)
    index_rows = {
        "graph_node_chunks": node_meta,
        "graph_edge_chunks": edge_meta,
        "graph_outgoing_adjacency": outgoing_meta,
        "graph_incoming_adjacency": incoming_meta,
    }
    for name, rows in index_rows.items():
        release._write_meta_index(index_dir / f"{name}.parquet", rows)
    manifest = {
        "dataset_revision": "test-revision",
        "indexes": {
            name: release._file_descriptor(
                index_dir / f"{name}.parquet",
                root=root,
            )
            for name in index_rows
        },
        "primary_key": "entry_cid",
        "schema_version": release.SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    resolver = ArtifactResolver(
        repo_id="test/graph-release",
        revision="test",
        path_prefix="",
        token=None,
        cache_dir=tmp_path / "cache",
        local_root=root,
    )
    index = SkillCenterRemoteIndex(resolver)

    node = index.graph_node("cid-a")
    assert node["results"][0]["label"] == "Skill A"
    neighbors = index.graph_neighbors(
        "cid-a",
        direction="outgoing",
        limit=2,
        hydrate=True,
    )
    assert [
        row["neighbor_cid"] for row in neighbors["results"]
    ] == ["cid-b", "cid-c"]
    assert neighbors["diagnostics"]["adjacency_shards_fetched"] == 1
    walk = index.graph_walk(
        "cid-a",
        direction="outgoing",
        max_depth=2,
        max_nodes=10,
        max_edges=10,
        per_node_limit=2,
        max_shards=4,
    )
    assert {row["node_cid"] for row in walk["nodes"]} == {
        "cid-a",
        "cid-b",
        "cid-c",
    }
    assert len(walk["edges"]) == 3
    assert walk["diagnostics"]["adjacency_shards_fetched"] <= 2

    zero_depth = index.graph_walk(
        "cid-a",
        direction="outgoing",
        max_depth=0,
        max_nodes=10,
        max_edges=10,
        per_node_limit=2,
        max_shards=4,
    )
    assert zero_depth["diagnostics"]["stop_reason"] == "max_depth"
    assert zero_depth["diagnostics"]["complete"] is False
    assert zero_depth["edges"] == []

    node_limited = index.graph_walk(
        "cid-a",
        direction="outgoing",
        max_depth=2,
        max_nodes=2,
        max_edges=10,
        per_node_limit=2,
        max_shards=4,
    )
    assert node_limited["diagnostics"]["stop_reason"] == "max_nodes"
    assert len(node_limited["nodes"]) == 2
    returned_node_cids = {
        row["node_cid"] for row in node_limited["nodes"]
    }
    assert all(
        edge["source_cid"] in returned_node_cids
        and edge["target_cid"] in returned_node_cids
        for edge in node_limited["edges"]
    )

    edge_limited = index.graph_walk(
        "cid-a",
        direction="outgoing",
        max_depth=2,
        max_nodes=10,
        max_edges=1,
        per_node_limit=2,
        max_shards=4,
    )
    assert edge_limited["diagnostics"]["stop_reason"] == "max_edges"
    assert len(edge_limited["edges"]) == 1
    assert {
        edge_limited["edges"][0]["source_cid"],
        edge_limited["edges"][0]["target_cid"],
    }.issubset(
        {row["node_cid"] for row in edge_limited["nodes"]}
    )


def test_remote_semantic_graph_walk_uses_bounded_centroid_vectors(
    tmp_path: Path,
) -> None:
    root = tmp_path / "semantic-graph-release"
    graph_dir = root / "data" / "graph"
    vector_dir = root / "data" / "vectors"
    index_dir = root / "indexes"
    for directory in (graph_dir, vector_dir, index_dir):
        directory.mkdir(parents=True, exist_ok=True)

    node_ids = ["cid-a", "cid-b", "cid-c", "cid-d", "cid-e"]
    node_path = graph_dir / "nodes.parquet"
    release._write_parquet(
        node_path,
        pa.Table.from_pylist(
            [
                {
                    "node_cid": node_id,
                    "node_type": "SKILL",
                    "entry_cid": node_id,
                    "label": node_id,
                    "properties_json": "{}",
                    "schema_version": "node/v1",
                }
                for node_id in node_ids
            ]
        ),
    )
    adjacency_path = graph_dir / "outgoing.parquet"
    adjacency_rows = []
    for source, targets in {
        "cid-a": ["cid-b", "cid-c"],
        "cid-b": ["cid-d"],
        "cid-c": ["cid-e"],
        "cid-d": [],
        "cid-e": [],
    }.items():
        adjacency_rows.append(
            {
                "direction": "outgoing",
                "edge_cids": [
                    f"edge-{source}-{target}" for target in targets
                ],
                "edge_types": ["RELATED_TO"] * len(targets),
                "neighbor_cids": targets,
                "neighbor_count": len(targets),
                "neighbor_node_types": ["SKILL"] * len(targets),
                "node_cid": source,
                "page_count": 1,
                "page_index": 0,
                "retrieval_methods": ["test"] * len(targets),
                "schema_version": (
                    release.SKILLCENTER_HF_GRAPH_ADJACENCY_SCHEMA_VERSION
                ),
                "scores": [1.0] * len(targets),
                "total_neighbor_count": len(targets),
            }
        )
    release._write_parquet(
        adjacency_path,
        pa.Table.from_pylist(adjacency_rows),
    )

    vector_path = vector_dir / "part-000000.parquet"
    vectors = [
        [0.0, 1.0],
        [0.0, 1.0],
        [0.8, 0.2],
        [0.0, 1.0],
        [1.0, 0.0],
    ]
    fixed_vectors = pa.FixedSizeListArray.from_arrays(
        pa.array(
            [value for vector in vectors for value in vector],
            type=pa.float32(),
        ),
        2,
    )
    release._write_parquet(
        vector_path,
        pa.table(
            {
                "entry_cid": node_ids,
                "embedding": fixed_vectors,
            }
        ),
    )

    node_meta = _meta(
        node_path,
        root,
        kind="graph_nodes",
        first_key=node_ids[0],
        last_key=node_ids[-1],
        row_count=len(node_ids),
    )
    adjacency_meta = _meta(
        adjacency_path,
        root,
        kind="graph_outgoing_adjacency",
        first_key=node_ids[0],
        last_key=node_ids[-1],
        row_count=len(adjacency_rows),
        adjacency_count=4,
        direction="outgoing",
        first_page_index=0,
        last_page_index=0,
        node_count=len(node_ids),
    )
    vector_meta = _meta(
        vector_path,
        root,
        kind="vectors",
        first_key=node_ids[0],
        last_key=node_ids[-1],
        row_count=len(node_ids),
        centroid=[1.0, 0.0],
        centroid_min_score=0.0,
        centroid_shard_count=1,
        chunk_in_cluster=0,
        cluster_id=0,
        dimension=2,
        model_name="test/model",
        shard_centroid=[1.0, 0.0],
    )
    index_rows = {
        "graph_node_chunks": [node_meta],
        "graph_outgoing_adjacency": [adjacency_meta],
        "vector_chunks": [vector_meta],
    }
    for name, rows in index_rows.items():
        release._write_meta_index(index_dir / f"{name}.parquet", rows)
    manifest = {
        "dataset_revision": "test-revision",
        "indexes": {
            name: release._file_descriptor(
                index_dir / f"{name}.parquet",
                root=root,
            )
            for name in index_rows
        },
        "primary_key": "entry_cid",
        "schema_version": release.SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        "vector": {
            "centroid_count": 1,
            "default_probe_centroids": 1,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 2,
            "model_name": "test/model",
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    index = SkillCenterRemoteIndex(
        ArtifactResolver(
            repo_id="test/semantic-graph",
            revision="test",
            path_prefix="",
            token=None,
            cache_dir=tmp_path / "cache",
            local_root=root,
        )
    )

    result = index.graph_semantic_walk(
        "cid-a",
        query="find e",
        query_vector=[1.0, 0.0],
        direction="outgoing",
        max_depth=2,
        max_nodes=10,
        max_edges=10,
        per_node_limit=4,
        max_shards=2,
        candidate_centroids=1,
        max_vector_shards=1,
        beam_width=1,
        hydrate=True,
    )

    assert {node["node_cid"] for node in result["nodes"]} == {
        "cid-a",
        "cid-c",
        "cid-e",
    }
    assert result["diagnostics"]["candidate_vector_shards"] == 1
    assert result["diagnostics"]["adjacency_shards_fetched"] == 1
    assert result["diagnostics"]["traversal_strategy"] == "semantic_beam"
    assert result["nodes"][-1]["semantic_proximity"] == pytest.approx(1.0)
    assert {
        item["relative_path"] for item in result["fetch_trace"]["files"]
    } <= {
        "manifest.json",
        "indexes/graph_node_chunks.parquet",
        "indexes/graph_outgoing_adjacency.parquet",
        "indexes/vector_chunks.parquet",
        "data/graph/nodes.parquet",
        "data/graph/outgoing.parquet",
        "data/vectors/part-000000.parquet",
    }


def test_local_remote_bm25_and_vector_query_fetch_bounded_shards(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release"
    corpus_dir = root / "data" / "corpus"
    posting_dir = root / "data" / "bm25" / "postings"
    vector_dir = root / "data" / "vectors"
    index_dir = root / "indexes"
    for directory in (corpus_dir, posting_dir, vector_dir, index_dir):
        directory.mkdir(parents=True, exist_ok=True)

    corpus_rows = []
    for index, title in enumerate(("Secure rotation", "Parse logs", "Draw image")):
        corpus_rows.append(
            {
                "document_index": index,
                "entry_cid": f"cid-{index}",
                "skill_id": f"skill-{index}",
                "title": title,
                "domain": "test",
                "profile": "",
                "repository_file": "test.sqlite",
                "source_type": "repo",
                "language": "en",
                "license_expression": "MIT",
                "source_url": "https://example.invalid",
                "skill_md": f"# {title}",
                "library_md": "",
                "metadata_yaml": "",
            }
        )
    corpus_path = corpus_dir / "part-000000.parquet"
    release._write_parquet(corpus_path, pa.Table.from_pylist(corpus_rows))

    posting_path = posting_dir / "part-000000.parquet"
    posting_rows = [
        {
            "body_frequencies": [1],
            "corpus_frequency": 2,
            "document_frequency": 1,
            "document_indices": [0],
            "document_lengths": [4],
            "idf": 1.0,
            "posting_chunk_count": 1,
            "posting_chunk_index": 0,
            "schema_version": release.SKILLCENTER_HF_BM25_POSTING_SCHEMA_VERSION,
            "term": "secure",
            "title_frequencies": [1],
        }
    ]
    release._write_parquet(
        posting_path,
        pa.Table.from_pylist(
            posting_rows,
            schema=release._bm25_posting_schema(pa),
        ),
    )

    vector_path = vector_dir / "part-000000.parquet"
    embedding = pa.FixedSizeListArray.from_arrays(
        pa.array([1.0, 0.0, 0.0, 1.0, -1.0, 0.0], type=pa.float32()),
        2,
    )
    release._write_parquet(
        vector_path,
        pa.table(
            {
                "chunk_id": ["vector-000000"] * 3,
                "cluster_id": pa.array([0, 0, 0], type=pa.int32()),
                "entry_cid": ["cid-0", "cid-1", "cid-2"],
                "faiss_id": pa.array([10, 11, 12], type=pa.int64()),
                "document_index": pa.array([0, 1, 2], type=pa.int32()),
                "corpus_chunk_id": pa.array([0, 0, 0], type=pa.int32()),
                "corpus_row_offset": pa.array([0, 1, 2], type=pa.int32()),
                "skill_id": ["skill-0", "skill-1", "skill-2"],
                "title": ["Secure rotation", "Parse logs", "Draw image"],
                "domain": ["test"] * 3,
                "profile": [""] * 3,
                "repository_file": ["test.sqlite"] * 3,
                "source_type": ["repo"] * 3,
                "language": ["en"] * 3,
                "embedding": embedding,
                "schema_version": [
                    release.SKILLCENTER_HF_VECTOR_CHUNK_SCHEMA_VERSION
                ]
                * 3,
            }
        ),
    )

    corpus_meta = _meta(
        corpus_path,
        root,
        kind="corpus",
        first_key="cid-0",
        last_key="cid-2",
        row_count=3,
    )
    posting_meta = _meta(
        posting_path,
        root,
        kind="bm25_postings",
        first_key="secure",
        last_key="secure",
        row_count=1,
        posting_count=1,
        term_count=1,
        token_instance_count=2,
    )
    vector_meta = _meta(
        vector_path,
        root,
        kind="vectors",
        first_key="cid-0",
        last_key="cid-2",
        row_count=3,
        centroid=[1.0, 0.0],
        centroid_min_score=-1.0,
        centroid_shard_count=1,
        chunk_in_cluster=0,
        cluster_id=0,
        dimension=2,
        model_name="test/model",
        shard_centroid=[1.0, 0.0],
    )
    for name, rows in (
        ("corpus_chunks", [corpus_meta]),
        ("bm25_keyword_shards", [posting_meta]),
        ("vector_chunks", [vector_meta]),
    ):
        release._write_meta_index(index_dir / f"{name}.parquet", rows)
    manifest = {
        "bm25": {
            "average_document_length": 4.0,
            "b": 0.75,
            "body_weight": 1.0,
            "k1": 1.2,
            "max_query_terms": 64,
            "title_weight": 2.0,
        },
        "dataset_revision": "test-revision",
        "indexes": {
            name: release._file_descriptor(
                index_dir / f"{name}.parquet",
                root=root,
            )
            for name in (
                "corpus_chunks",
                "bm25_keyword_shards",
                "vector_chunks",
            )
        },
        "primary_key": "entry_cid",
        "schema_version": release.SKILLCENTER_HF_RELEASE_SCHEMA_VERSION,
        "vector": {
            "assignment": "recursive_spherical_kmeans",
            "centroid_count": 1,
            "default_probe_centroids": 4,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_rows_per_centroid": 8192,
            "max_shards_per_centroid": 2,
            "model_name": "test/model",
            "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
            "shard_count": 1,
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    resolver = ArtifactResolver(
        repo_id="test/release",
        revision="test",
        path_prefix="",
        token=None,
        cache_dir=tmp_path / "cache",
        local_root=root,
    )
    index = SkillCenterRemoteIndex(resolver)
    bm25 = index.bm25("secure", top_k=1)
    assert bm25["results"][0]["entry_cid"] == "cid-0"
    vector = index.vector(
        "secure intent",
        top_k=1,
        candidate_chunks=1,
        query_vector=[1.0, 0.0],
    )
    assert vector["results"][0]["entry_cid"] == "cid-0"
    assert {
        item["relative_path"] for item in vector["fetch_trace"]["files"]
    } <= {
        "manifest.json",
        "indexes/bm25_keyword_shards.parquet",
        "indexes/corpus_chunks.parquet",
        "indexes/vector_chunks.parquet",
        "data/bm25/postings/part-000000.parquet",
        "data/corpus/part-000000.parquet",
        "data/vectors/part-000000.parquet",
    }
