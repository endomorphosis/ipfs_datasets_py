"""KGP-009: Versioned ParquetGraphStore contract tests.

Acceptance coverage:
* Store normalized nodes, edges, adjacency, properties, and indexes
* Schema versions on partitions and revision manifests
* Bounded row groups with statistics
* Per-file SHA-256 checksums
* Predicate pushdown via PyArrow filters
* Schema evolution (additive nullable columns)
* Atomic temp/fsync/rename publication of revision directories
* Restart verification after reopening the store
* Corrupt / truncated file detection
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from ipfs_datasets_py.knowledge_graphs.storage.parquet import (
    DATASET_SCHEMA_VERSIONS,
    DEFAULT_ROW_GROUP_SIZE,
    MAX_ROW_GROUP_SIZE,
    PARQUET_MAGIC,
    STORAGE_PROFILE,
    TYPED_ERROR_CODES,
    GraphStoreError,
    ParquetGraphStore,
    create_parquet_graph_store,
    detect_parquet_corruption,
    evolve_table_to_schema,
    get_partition_schema,
    normalize_edge,
    normalize_node,
    verify_parquet_file,
)

pyarrow = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ParquetGraphStore]:
    s = ParquetGraphStore.open(tmp_path / "parquet-store", row_group_size=2)
    try:
        yield s
    finally:
        s.close()


def _sample_nodes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "n1",
            "type": "Person",
            "name": "Alice",
            "properties": {"age": 30, "city": "SF"},
            "confidence": 0.95,
        },
        {
            "id": "n2",
            "type": "Org",
            "name": "Acme",
            "properties": {"city": "SF"},
        },
        {
            "id": "n3",
            "type": "Person",
            "name": "Bob",
            "properties": {"age": 25},
        },
    ]


def _sample_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e1",
            "type": "WORKS_AT",
            "source_id": "n1",
            "target_id": "n2",
            "properties": {"since": 2020},
        },
        {
            "id": "e2",
            "type": "KNOWS",
            "source_id": "n1",
            "target_id": "n3",
        },
    ]


def _publish(store: ParquetGraphStore, **overrides: Any):
    kwargs = dict(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        nodes=_sample_nodes(),
        edges=_sample_edges(),
        provenance={
            "producer_id": "kgp-009-tests",
            "producer_version": "1",
            "source": "contract",
            "created_at": "2026-07-29T00:00:00Z",
        },
    )
    kwargs.update(overrides)
    return store.publish_revision(**kwargs)


# ---------------------------------------------------------------------------
# Constants / factory
# ---------------------------------------------------------------------------


def test_storage_profile_constant() -> None:
    assert STORAGE_PROFILE == "parquet"
    assert ParquetGraphStore.storage_profile == "parquet"
    assert DEFAULT_ROW_GROUP_SIZE <= MAX_ROW_GROUP_SIZE
    assert PARQUET_MAGIC == b"PAR1"


def test_create_factory(tmp_path: Path) -> None:
    s = create_parquet_graph_store(tmp_path / "g", row_group_size=8)
    assert isinstance(s, ParquetGraphStore)
    assert s.storage_profile == "parquet"
    s.close()


def test_graph_store_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        GraphStoreError("NOT_A_REAL_CODE", "nope")


def test_graph_store_error_typed_dict() -> None:
    err = GraphStoreError(
        "INTEGRITY",
        "bad",
        details={"path": "x"},
        cause_code="CHECKSUM_MISMATCH",
    )
    d = err.to_typed_dict()
    assert d["code"] == "INTEGRITY"
    assert d["retryable"] is False
    assert d["cause_code"] == "CHECKSUM_MISMATCH"
    assert d["code"] in TYPED_ERROR_CODES


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_node_and_edge() -> None:
    n = normalize_node(
        {"entity_id": "x", "entity_type": "Person", "name": "X", "properties": {"k": 1}},
        schema_version="1",
    )
    assert n["id"] == "x"
    assert n["type"] == "Person"
    assert json.loads(n["properties_json"]) == {"k": 1}
    assert n["schema_version"] == "1"

    e = normalize_edge(
        {
            "relationship_id": "r1",
            "relationship_type": "KNOWS",
            "source": "a",
            "target": "b",
        },
        schema_version="1",
    )
    assert e["id"] == "r1"
    assert e["source_id"] == "a"
    assert e["target_id"] == "b"


def test_normalize_node_rejects_bad_id() -> None:
    with pytest.raises(GraphStoreError) as ei:
        normalize_node({"name": "no-id"}, schema_version="1")
    assert ei.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Publish: nodes, edges, adjacency, properties, indexes
# ---------------------------------------------------------------------------


def test_publish_stores_normalized_partitions(store: ParquetGraphStore) -> None:
    result = _publish(store)
    assert result.tenant == "acme"
    assert result.revision_id == "rev-001"
    assert set(result.partitions) == {"nodes", "edges", "adjacency", "properties"}
    assert "idx-type" in result.indexes

    rev = Path(result.path)
    assert (rev / "_SUCCESS").is_file()
    assert (rev / "manifest.json").is_file()
    assert (rev / "nodes.parquet").is_file()
    assert (rev / "edges.parquet").is_file()
    assert (rev / "adjacency.parquet").is_file()
    assert (rev / "properties.parquet").is_file()
    assert (rev / "indexes" / "idx-type.parquet").is_file()

    # Catalog control metadata must not live inside parquet payloads.
    for name in ("nodes.parquet", "edges.parquet"):
        pf = pq.ParquetFile(rev / name)
        names = set(pf.schema_arrow.names)
        assert "branch" not in names
        assert "lease_id" not in names
        assert "head_revision" not in names


def test_manifest_schema_versions_and_profile(store: ParquetGraphStore) -> None:
    result = _publish(store)
    man = result.manifest
    assert man["storage_profile"] == "parquet"
    assert man["codec"] == "parquet"
    assert man["schema_version"] == "1"
    assert man["counts"]["node_count"] == 3
    assert man["counts"]["edge_count"] == 2
    kinds = {p["kind"] for p in man["partitions"]}
    assert kinds >= {"nodes", "edges", "adjacency", "properties"}
    for part in man["partitions"]:
        assert part["schema_version"] in {"1", "2"}
        assert part["checksum"]["algorithm"] == "sha256"
        assert len(part["checksum"]["hex_digest"]) == 64
        assert part["cid"].startswith("b")
    assert any(i["index_id"] == "idx-type" for i in man["indexes"])


def test_properties_are_normalized_eav(store: ParquetGraphStore) -> None:
    _publish(store)
    props = store.scan_properties("acme", "skills", "rev-001")
    keys = {(p["owner_kind"], p["owner_id"], p["key"]) for p in props}
    assert ("node", "n1", "age") in keys
    assert ("node", "n1", "city") in keys
    assert ("edge", "e1", "since") in keys
    age = next(p for p in props if p["owner_id"] == "n1" and p["key"] == "age")
    assert json.loads(age["value_json"]) == 30
    assert age["value_type"] == "int"


def test_adjacency_bidirectional(store: ParquetGraphStore) -> None:
    _publish(store)
    adj = store.scan_adjacency("acme", "skills", "rev-001")
    # 2 edges * 2 directions
    assert len(adj) == 4
    outs = [a for a in adj if a["node_id"] == "n1" and a["direction"] == "out"]
    assert {a["neighbor_id"] for a in outs} == {"n2", "n3"}
    ins = [a for a in adj if a["node_id"] == "n2" and a["direction"] == "in"]
    assert ins and ins[0]["neighbor_id"] == "n1"


def test_type_index_entries(store: ParquetGraphStore) -> None:
    _publish(store)
    idx = store.scan_index("acme", "skills", "rev-001", "idx-type")
    by_key = {row["key"]: row for row in idx}
    assert "Person" in by_key
    assert "Org" in by_key
    assert json.loads(by_key["Person"]["value_json"])["count"] == 2
    assert set(json.loads(by_key["Person"]["refs_json"])) == {"n1", "n3"}


def test_publish_duplicate_revision_is_already_exists(store: ParquetGraphStore) -> None:
    _publish(store)
    with pytest.raises(GraphStoreError) as ei:
        _publish(store)
    assert ei.value.code == "ALREADY_EXISTS"


def test_publish_overwrite(store: ParquetGraphStore) -> None:
    _publish(store)
    result = _publish(
        store,
        overwrite=True,
        nodes=[{"id": "only", "type": "X", "name": "Only"}],
        edges=[],
    )
    assert result.manifest["counts"]["node_count"] == 1
    nodes = store.scan_nodes("acme", "skills", "rev-001")
    assert [n["id"] for n in nodes] == ["only"]


# ---------------------------------------------------------------------------
# Bounded row groups + statistics
# ---------------------------------------------------------------------------


def test_bounded_row_groups(store: ParquetGraphStore) -> None:
    # 3 nodes with row_group_size=2 → at least 2 row groups
    _publish(store)
    rgs = store.row_group_stats("acme", "skills", "rev-001", "nodes")
    assert len(rgs) >= 2
    for rg in rgs[:-1]:
        assert rg["num_rows"] <= store.row_group_size
    assert sum(rg["num_rows"] for rg in rgs) == 3


def test_row_group_size_bounds_on_open(tmp_path: Path) -> None:
    with pytest.raises(GraphStoreError) as ei:
        ParquetGraphStore.open(tmp_path / "bad", row_group_size=0)
    assert ei.value.code == "INVALID_REQUEST"

    with pytest.raises(GraphStoreError) as ei:
        ParquetGraphStore.open(
            tmp_path / "bad2",
            row_group_size=MAX_ROW_GROUP_SIZE + 1,
            max_row_group_size=MAX_ROW_GROUP_SIZE + 1,
        )
    assert ei.value.code == "INVALID_REQUEST"


def test_statistics_written(store: ParquetGraphStore) -> None:
    result = _publish(store)
    stats = store.get_statistics("acme", "skills", "rev-001")
    assert stats["revision_id"] == "rev-001"
    assert stats["row_group_size"] == store.row_group_size
    assert "nodes" in stats["partitions"]
    assert stats["partitions"]["nodes"]["row_count"] == 3
    assert "columns" in stats["partitions"]["nodes"]
    assert "type" in stats["partitions"]["nodes"]["columns"]
    assert "idx-type" in stats["indexes"]
    # PublishResult mirrors stats
    assert result.statistics["partitions"]["edges"]["row_count"] == 2


def test_parquet_file_has_write_statistics(store: ParquetGraphStore) -> None:
    result = _publish(store)
    path = Path(result.path) / "nodes.parquet"
    pf = pq.ParquetFile(path)
    assert pf.metadata.num_row_groups >= 1
    col = pf.metadata.row_group(0).column(0)
    # Statistics object present when write_statistics=True
    assert col.statistics is not None or pf.metadata.num_rows == 0


# ---------------------------------------------------------------------------
# Checksums
# ---------------------------------------------------------------------------


def test_checksums_match_files(store: ParquetGraphStore) -> None:
    result = _publish(store)
    checksums = store.get_checksums("acme", "skills", "rev-001")
    rev = Path(result.path)
    import hashlib

    for rel, expected in checksums.items():
        if rel == "checksums.json":
            continue
        path = rev / rel
        assert path.is_file()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected
    # Partition results expose checksums too
    assert result.partitions["nodes"].checksum == checksums["nodes.parquet"]


# ---------------------------------------------------------------------------
# Predicate pushdown
# ---------------------------------------------------------------------------


def test_predicate_pushdown_nodes_by_type(store: ParquetGraphStore) -> None:
    _publish(store)
    persons = store.scan_nodes(
        "acme", "skills", "rev-001", filters=[("type", "==", "Person")]
    )
    assert {n["id"] for n in persons} == {"n1", "n3"}
    orgs = store.scan_nodes(
        "acme", "skills", "rev-001", filters=[("type", "==", "Org")]
    )
    assert [n["id"] for n in orgs] == ["n2"]


def test_predicate_pushdown_edges_and_adjacency(store: ParquetGraphStore) -> None:
    _publish(store)
    knows = store.scan_edges(
        "acme", "skills", "rev-001", filters=[("type", "==", "KNOWS")]
    )
    assert len(knows) == 1
    assert knows[0]["id"] == "e2"

    outs = store.scan_adjacency(
        "acme",
        "skills",
        "rev-001",
        filters=[("node_id", "==", "n1"), ("direction", "==", "out")],
    )
    assert {a["neighbor_id"] for a in outs} == {"n2", "n3"}


def test_predicate_pushdown_properties_and_index(store: ParquetGraphStore) -> None:
    _publish(store)
    ages = store.scan_properties(
        "acme",
        "skills",
        "rev-001",
        filters=[("key", "==", "age")],
    )
    assert {p["owner_id"] for p in ages} == {"n1", "n3"}

    person_bucket = store.scan_index(
        "acme",
        "skills",
        "rev-001",
        "idx-type",
        filters=[("key", "==", "Person")],
    )
    assert len(person_bucket) == 1


def test_column_projection(store: ParquetGraphStore) -> None:
    _publish(store)
    rows = store.scan_nodes(
        "acme", "skills", "rev-001", columns=["id", "type"]
    )
    assert set(rows[0].keys()) == {"id", "type"}


def test_invalid_filter_shape(store: ParquetGraphStore) -> None:
    _publish(store)
    with pytest.raises(GraphStoreError) as ei:
        store.scan_nodes("acme", "skills", "rev-001", filters=["bad"])  # type: ignore[list-item]
    assert ei.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Schema evolution
# ---------------------------------------------------------------------------


def test_schema_versions_registry() -> None:
    s1 = get_partition_schema("nodes", "1")
    s2 = get_partition_schema("nodes", "2")
    assert "id" in s1.names
    assert "label" not in s1.names
    assert "label" in s2.names
    assert DATASET_SCHEMA_VERSIONS["nodes"] == "1"


def test_evolve_table_adds_null_columns() -> None:
    import pyarrow as pa

    t = pa.table({"id": ["a"], "type": ["Person"], "name": ["A"]})
    target = get_partition_schema("nodes", "2")
    evolved = evolve_table_to_schema(t, target)
    assert "label" in evolved.column_names
    assert evolved.column("label")[0].as_py() is None
    assert evolved.num_rows == 1


def test_schema_evolution_on_read(store: ParquetGraphStore) -> None:
    # Publish with default schema v1 (no label column on disk).
    _publish(store)
    # Read requesting schema v2 — additive nullable label filled with nulls.
    rows = store.scan_nodes(
        "acme", "skills", "rev-001", schema_version="2"
    )
    assert "label" in rows[0]
    assert rows[0]["label"] is None
    assert rows[0]["id"] == "n1" or any(r["id"] == "n1" for r in rows)


def test_publish_with_nodes_schema_v2(store: ParquetGraphStore) -> None:
    result = _publish(
        store,
        revision_id="rev-v2",
        partition_schema_versions={"nodes": "2"},
        nodes=[
            {
                "id": "n9",
                "type": "Person",
                "name": "Zed",
                "label": "primary",
                "properties": {},
            }
        ],
        edges=[],
    )
    assert result.partitions["nodes"].schema_version == "2"
    rows = store.scan_nodes("acme", "skills", "rev-v2")
    assert rows[0]["label"] == "primary"
    # Still readable under v1 projection (label dropped if not in target)
    rows_v1 = store.scan_nodes(
        "acme", "skills", "rev-v2", schema_version="1", columns=["id", "type", "name"]
    )
    assert "id" in rows_v1[0]


# ---------------------------------------------------------------------------
# Atomic publication
# ---------------------------------------------------------------------------


def test_atomic_publish_no_staging_left(store: ParquetGraphStore) -> None:
    _publish(store)
    staging = store.staging_root()
    if staging.exists():
        leftovers = list(staging.iterdir())
        assert leftovers == [], f"staging leftovers: {leftovers}"
    assert store.has_revision("acme", "skills", "rev-001")
    assert store.list_revisions("acme", "skills") == ["rev-001"]


def test_readers_never_see_partial_revision(store: ParquetGraphStore, tmp_path: Path) -> None:
    """Incomplete revision directories (no _SUCCESS) are invisible to list/open."""
    # Manually create a half-written revision dir without marker.
    bad = store.revision_dir("acme", "skills", "rev-partial")
    bad.mkdir(parents=True)
    (bad / "nodes.parquet").write_bytes(b"not-a-real-parquet")
    assert "rev-partial" not in store.list_revisions("acme", "skills")
    assert store.has_revision("acme", "skills", "rev-partial") is False
    with pytest.raises(GraphStoreError) as ei:
        store.open_revision("acme", "skills", "rev-partial")
    assert ei.value.code in {"NOT_FOUND", "INTEGRITY"}


def test_publish_cleans_incomplete_prior(store: ParquetGraphStore) -> None:
    bad = store.revision_dir("acme", "skills", "rev-001")
    bad.mkdir(parents=True)
    (bad / "garbage.txt").write_text("incomplete", encoding="utf-8")
    # No _SUCCESS → treat as incomplete and replace.
    result = _publish(store)
    assert result.revision_id == "rev-001"
    assert not (Path(result.path) / "garbage.txt").exists()


# ---------------------------------------------------------------------------
# Restart verification
# ---------------------------------------------------------------------------


def test_restart_verification_across_instances(tmp_path: Path) -> None:
    root = tmp_path / "durable"
    store1 = ParquetGraphStore.open(root, row_group_size=4)
    try:
        result = _publish(store1, revision_id="rev-restart")
        path = result.path
        checksum_nodes = result.partitions["nodes"].checksum
    finally:
        store1.close()

    store2 = ParquetGraphStore.open(root, row_group_size=4)
    try:
        assert store2.has_revision("acme", "skills", "rev-restart")
        report = store2.verify_revision("acme", "skills", "rev-restart")
        assert report["ok"] is True
        handle = store2.open_revision("acme", "skills", "rev-restart")
        assert handle.manifest["revision_id"] == "rev-restart"
        nodes = handle.scan_nodes(filters=[("type", "==", "Person")])
        assert {n["id"] for n in nodes} == {"n1", "n3"}
        assert handle.checksums["nodes.parquet"] == checksum_nodes
        assert Path(path).is_dir()
    finally:
        store2.close()


def test_open_revision_verify_flag(store: ParquetGraphStore) -> None:
    _publish(store)
    h = store.open_revision("acme", "skills", "rev-001", verify=True)
    assert h.statistics["partitions"]["nodes"]["row_count"] == 3
    h2 = store.open_revision("acme", "skills", "rev-001", verify=False)
    assert h2.revision_id == "rev-001"


# ---------------------------------------------------------------------------
# Corrupt / truncated detection
# ---------------------------------------------------------------------------


def test_detect_truncated_file(tmp_path: Path) -> None:
    p = tmp_path / "t.parquet"
    p.write_bytes(b"PAR1")  # too short
    assert detect_parquet_corruption(p) in {"TRUNCATED", "BAD_MAGIC_FOOTER", "TRUNCATED_FOOTER"}


def test_detect_bad_magic(tmp_path: Path) -> None:
    p = tmp_path / "t.parquet"
    p.write_bytes(b"XXXX" + b"\x00" * 20 + b"PAR1")
    assert detect_parquet_corruption(p) == "BAD_MAGIC_HEADER"


def test_verify_revision_detects_checksum_tamper(store: ParquetGraphStore) -> None:
    result = _publish(store)
    path = Path(result.path) / "nodes.parquet"
    # Tamper while keeping approximate size (overwrite middle bytes).
    data = bytearray(path.read_bytes())
    mid = len(data) // 2
    data[mid] = (data[mid] + 1) % 256
    path.write_bytes(bytes(data))
    with pytest.raises(GraphStoreError) as ei:
        store.verify_revision("acme", "skills", "rev-001")
    assert ei.value.code == "INTEGRITY"
    assert ei.value.cause_code in {
        "CHECKSUM_MISMATCH",
        "BAD_MAGIC_HEADER",
        "BAD_MAGIC_FOOTER",
        "PARQUET_UNREADABLE",
        "TRUNCATED",
        "TRUNCATED_FOOTER",
        "SIZE_MISMATCH",
    }


def test_verify_revision_detects_truncation(store: ParquetGraphStore) -> None:
    result = _publish(store)
    path = Path(result.path) / "edges.parquet"
    raw = path.read_bytes()
    path.write_bytes(raw[: max(8, len(raw) // 4)])
    with pytest.raises(GraphStoreError) as ei:
        store.verify_revision("acme", "skills", "rev-001")
    assert ei.value.code == "INTEGRITY"


def test_scan_rejects_corrupt_partition(store: ParquetGraphStore) -> None:
    result = _publish(store)
    path = Path(result.path) / "nodes.parquet"
    path.write_bytes(b"PAR1XXXXPAR1")
    with pytest.raises(GraphStoreError) as ei:
        store.scan_nodes("acme", "skills", "rev-001")
    assert ei.value.code == "INTEGRITY"


def test_verify_parquet_file_helper(store: ParquetGraphStore) -> None:
    result = _publish(store)
    path = Path(result.path) / "properties.parquet"
    info = verify_parquet_file(
        path,
        expected_checksum=result.partitions["properties"].checksum,
        expected_size=result.partitions["properties"].size_bytes,
        expected_rows=result.partitions["properties"].row_count,
    )
    assert info["row_count"] == result.partitions["properties"].row_count
    assert info["checksum"] == result.partitions["properties"].checksum


# ---------------------------------------------------------------------------
# Missing revision / closed store / cancellation
# ---------------------------------------------------------------------------


def test_missing_revision_not_found(store: ParquetGraphStore) -> None:
    with pytest.raises(GraphStoreError) as ei:
        store.get_manifest("acme", "skills", "no-such-rev")
    assert ei.value.code == "NOT_FOUND"


def test_closed_store_rejects_ops(store: ParquetGraphStore) -> None:
    store.close()
    with pytest.raises(GraphStoreError) as ei:
        _publish(store)
    assert ei.value.code == "STORAGE"


def test_cancel_check_aborts_publish(tmp_path: Path) -> None:
    cancelled = threading.Event()

    def check() -> None:
        if cancelled.is_set():
            raise GraphStoreError(
                "STORAGE",
                "operation cancelled",
                retryable=True,
                details={"cancelled": True},
                cause_code="CANCELLED",
            )

    s = ParquetGraphStore.open(tmp_path / "c", cancel_check=check, row_group_size=8)
    cancelled.set()
    with pytest.raises(GraphStoreError) as ei:
        _publish(s)
    assert ei.value.cause_code == "CANCELLED"
    s.close()


def test_illegal_tenant_slug(store: ParquetGraphStore) -> None:
    with pytest.raises(GraphStoreError) as ei:
        store.publish_revision(
            tenant="../evil",
            graph_id="g",
            revision_id="r1",
            nodes=[],
            edges=[],
        )
    assert ei.value.code == "INVALID_REQUEST"


def test_custom_index_payload(store: ParquetGraphStore) -> None:
    result = _publish(
        store,
        revision_id="rev-idx",
        build_type_index=False,
        indexes={
            "idx-name": [
                {
                    "kind": "btree",
                    "key": "Alice",
                    "value": {"field": "name"},
                    "refs": ["n1"],
                }
            ]
        },
    )
    assert "idx-name" in result.indexes
    rows = store.scan_index("acme", "skills", "rev-idx", "idx-name")
    assert rows[0]["key"] == "Alice"
    assert rows[0]["kind"] == "btree"


def test_empty_graph_publish(store: ParquetGraphStore) -> None:
    result = _publish(
        store,
        revision_id="rev-empty",
        nodes=[],
        edges=[],
        build_type_index=True,
    )
    assert result.manifest["counts"]["node_count"] == 0
    assert result.manifest["counts"]["edge_count"] == 0
    assert store.scan_nodes("acme", "skills", "rev-empty") == []
    assert store.scan_adjacency("acme", "skills", "rev-empty") == []


def test_parent_revision_recorded(store: ParquetGraphStore) -> None:
    _publish(store, revision_id="rev-a")
    result = _publish(
        store,
        revision_id="rev-b",
        parent_revision="rev-a",
        nodes=[{"id": "n9", "type": "X", "name": "Nine"}],
        edges=[],
    )
    assert result.manifest["parent_revision"] == "rev-a"
    assert set(store.list_revisions("acme", "skills")) == {"rev-a", "rev-b"}
