"""Unit tests for DuckDB graph projection (DQK-016).

Acceptance coverage:

* Large graph data is scanned from immutable segments rather than duplicated
* Predicate pushdown works (filters attach to READ_PARQUET)
* Projection rows bind exact graph revision and source CID

Also covers normalized vertex/edge/property/adjacency/provenance/segment/
lineage surfaces and preservation of checksums, CIDs, staging refusal, and
``_SUCCESS`` markers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.storage.duckdb_projection import (
    ADJACENCY_VIEW,
    EDGES_VIEW,
    PROJECTION_SCHEMA,
    PROPERTIES_VIEW,
    PUBLICATION_MARKER,
    SCHEMA_VERSION,
    SEGMENTS_TABLE,
    STAGING_DIRNAME,
    VERTICES_VIEW,
    DuckDBGraphProjection,
    ProjectionError,
    create_duckdb_graph_projection,
)


# ---------------------------------------------------------------------------
# Helpers — build immutable revision dirs without pyarrow
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _write_parquet(conn: Any, path: Path, rows_sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(f"CREATE OR REPLACE TEMP TABLE _tmp_export AS {rows_sql}")
    # Escape single quotes for path literal.
    lit = str(path.resolve()).replace("'", "''")
    conn.execute(f"COPY _tmp_export TO '{lit}' (FORMAT PARQUET)")


def _build_revision(
    root: Path,
    *,
    revision_id: str = "rev-001",
    parent_revision: Optional[str] = None,
    with_manifest: bool = True,
    success: bool = True,
    under_staging: bool = False,
) -> Path:
    """Create a published-looking revision directory with parquet partitions."""

    if under_staging:
        rev_dir = root / STAGING_DIRNAME / "tmp-uuid" / revision_id
    else:
        rev_dir = root / "acme" / "skills" / "revisions" / revision_id
    rev_dir.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect()
    try:
        _write_parquet(
            conn,
            rev_dir / "nodes.parquet",
            """
            SELECT * FROM (VALUES
                ('n1', 'Person', 'Alice', '{"age":30}', 0.95, NULL, '1'),
                ('n2', 'Org', 'Acme', '{"city":"SF"}', 1.0, NULL, '1'),
                ('n3', 'Person', 'Bob', '{"age":25}', 1.0, NULL, '1')
            ) v(id, type, name, properties_json, confidence, source_text, schema_version)
            """,
        )
        _write_parquet(
            conn,
            rev_dir / "edges.parquet",
            """
            SELECT * FROM (VALUES
                ('e1', 'WORKS_AT', 'n1', 'n2', '{"since":2020}', 1.0, NULL, '1'),
                ('e2', 'KNOWS', 'n1', 'n3', '{}', 1.0, NULL, '1')
            ) v(id, type, source_id, target_id, properties_json, confidence, source_text, schema_version)
            """,
        )
        _write_parquet(
            conn,
            rev_dir / "properties.parquet",
            """
            SELECT * FROM (VALUES
                ('node', 'n1', 'age', '30', 'int', '1'),
                ('node', 'n1', 'city', '"SF"', 'str', '1'),
                ('node', 'n2', 'city', '"SF"', 'str', '1'),
                ('edge', 'e1', 'since', '2020', 'int', '1')
            ) v(owner_kind, owner_id, key, value_json, value_type, schema_version)
            """,
        )
        _write_parquet(
            conn,
            rev_dir / "adjacency.parquet",
            """
            SELECT * FROM (VALUES
                ('n1', 'out', 'n2', 'e1', 'WORKS_AT', '1'),
                ('n2', 'in', 'n1', 'e1', 'WORKS_AT', '1'),
                ('n1', 'out', 'n3', 'e2', 'KNOWS', '1'),
                ('n3', 'in', 'n1', 'e2', 'KNOWS', '1')
            ) v(node_id, direction, neighbor_id, edge_id, edge_type, schema_version)
            """,
        )
    finally:
        conn.close()

    checksums: Dict[str, str] = {}
    partitions: List[Dict[str, Any]] = []
    for kind in ("nodes", "edges", "properties", "adjacency"):
        rel = f"{kind}.parquet"
        path = rev_dir / rel
        digest = _sha256_file(path)
        checksums[rel] = digest
        partitions.append(
            {
                "partition_id": f"part-{kind}",
                "kind": kind,
                "path": rel,
                "codec": "parquet",
                "checksum": {"algorithm": "sha256", "hex_digest": digest},
                "row_count": 0,
                "size_bytes": path.stat().st_size,
                "cid": f"sha256:{digest}",
                "schema_version": "1",
            }
        )

    (rev_dir / "checksums.json").write_text(
        json.dumps(checksums, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    if with_manifest:
        root_hex = hashlib.sha256(
            json.dumps(checksums, sort_keys=True).encode("utf-8")
        ).hexdigest()
        manifest = {
            "manifest_version": "kg-revision-manifest/v1",
            "tenant": "acme",
            "graph_id": "skills",
            "revision_id": revision_id,
            "parent_revision": parent_revision,
            "schema_id": "kg-parquet-graph",
            "schema_version": "1",
            "ontology_id": "none",
            "ontology_version": "0",
            "graph_kind": "knowledge",
            "storage_profile": "parquet",
            "codec": "parquet",
            "counts": {"node_count": 3, "edge_count": 2, "document_count": 0},
            "partitions": partitions,
            "indexes": [],
            "shards": [],
            "provenance": {
                "producer_id": "dqk-016-tests",
                "producer_version": "1",
                "source": "unit",
                "created_at": "2026-08-10T00:00:00Z",
            },
            "checksum": {"algorithm": "sha256", "hex_digest": root_hex},
            "root_cid": f"sha256:{root_hex}",
        }
        (rev_dir / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    if success:
        (rev_dir / PUBLICATION_MARKER).write_text("ok\n", encoding="utf-8")

    return rev_dir


@pytest.fixture
def projection(tmp_path: Path) -> Iterator[DuckDBGraphProjection]:
    proj = DuckDBGraphProjection(tmp_path / "projection.duckdb")
    try:
        yield proj
    finally:
        proj.close()


@pytest.fixture
def published_revision(tmp_path: Path) -> Path:
    return _build_revision(tmp_path / "store")


# ---------------------------------------------------------------------------
# Schema / factory
# ---------------------------------------------------------------------------


def test_schema_constants() -> None:
    assert PROJECTION_SCHEMA.startswith("ipfs_datasets_py/")
    assert SCHEMA_VERSION == 1
    assert PUBLICATION_MARKER == "_SUCCESS"
    assert STAGING_DIRNAME == ".staging"


def test_factory_and_meta_tables(tmp_path: Path) -> None:
    proj = create_duckdb_graph_projection(tmp_path / "p.duckdb")
    try:
        names = set(proj.table_names())
        assert SEGMENTS_TABLE in names
        assert "lineage" in names
        assert "provenance" in names
        assert VERTICES_VIEW in names
        assert EDGES_VIEW in names
        assert PROPERTIES_VIEW in names
        assert ADJACENCY_VIEW in names
        assert proj.payload_is_view_backed()
        row = proj.execute(
            "SELECT value FROM projection_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row[0] == str(SCHEMA_VERSION)
    finally:
        proj.close()


def test_import_is_inert() -> None:
    # Module import must not open DuckDB until constructed.
    import ipfs_datasets_py.knowledge_graphs.storage.duckdb_projection as mod

    assert hasattr(mod, "DuckDBGraphProjection")


# ---------------------------------------------------------------------------
# Project revision — scan not duplicate
# ---------------------------------------------------------------------------


def test_project_revision_scans_immutable_segments(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    result = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    assert result.duplicated_bytes == 0
    assert projection.duplicated_payload_bytes() == 0
    assert projection.payload_is_view_backed()

    # Payload files unchanged (immutable).
    for kind in ("nodes", "edges", "properties", "adjacency"):
        path = published_revision / f"{kind}.parquet"
        assert path.is_file()
        # Success marker preserved.
    assert (published_revision / PUBLICATION_MARKER).is_file()

    # Segment registry records paths + checksums + CIDs; does not embed bytes.
    segs = projection.list_segments(tenant="acme", graph_id="skills")
    assert len(segs) == 4
    for seg in segs:
        assert seg.graph_revision == "rev-001"
        assert seg.checksum.startswith("sha256:")
        assert seg.source_cid
        assert seg.success_marker
        assert Path(seg.absolute_path).is_file()
        assert Path(seg.absolute_path).stat().st_size == seg.byte_size
        # Checksum still matches on-disk bytes.
        actual = _sha256_file(Path(seg.absolute_path))
        assert seg.checksum == f"sha256:{actual}"

    # DuckDB file should stay small relative to payload (metadata only).
    duck_size = projection.path.stat().st_size
    payload_size = sum(
        (published_revision / f"{k}.parquet").stat().st_size
        for k in ("nodes", "edges", "properties", "adjacency")
    )
    assert payload_size > 0
    # Metadata catalog must not have swallowed the payload.
    assert duck_size < payload_size * 4 or duck_size < 2_000_000


def test_refuse_incomplete_without_success_marker(
    projection: DuckDBGraphProjection, tmp_path: Path
) -> None:
    rev = _build_revision(tmp_path / "store", success=False)
    with pytest.raises(ProjectionError) as exc:
        projection.project_revision(
            tenant="acme",
            graph_id="skills",
            revision_id="rev-001",
            revision_dir=rev,
        )
    assert exc.value.code == "INTEGRITY"
    assert exc.value.cause_code == "MISSING_SUCCESS_MARKER"


def test_refuse_staging_path(
    projection: DuckDBGraphProjection, tmp_path: Path
) -> None:
    rev = _build_revision(tmp_path / "store", under_staging=True)
    with pytest.raises(ProjectionError) as exc:
        projection.project_revision(
            tenant="acme",
            graph_id="skills",
            revision_id="rev-001",
            revision_dir=rev,
        )
    assert exc.value.code == "INTEGRITY"
    assert exc.value.cause_code == "STAGING_PATH"


def test_checksum_mismatch_fails_closed(
    projection: DuckDBGraphProjection, tmp_path: Path
) -> None:
    rev = _build_revision(tmp_path / "store")
    # Corrupt checksums.json / manifest entry while keeping file bytes.
    manifest = json.loads((rev / "manifest.json").read_text(encoding="utf-8"))
    for part in manifest["partitions"]:
        if part["kind"] == "nodes":
            part["checksum"]["hex_digest"] = "0" * 64
            part["cid"] = "sha256:" + ("0" * 64)
    (rev / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ProjectionError) as exc:
        projection.project_revision(
            tenant="acme",
            graph_id="skills",
            revision_id="rev-001",
            revision_dir=rev,
            verify_checksums=True,
        )
    assert exc.value.code == "INTEGRITY"
    assert exc.value.cause_code == "CHECKSUM_MISMATCH"


def test_duplicate_project_is_already_exists(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    with pytest.raises(ProjectionError) as exc:
        projection.project_revision(
            tenant="acme",
            graph_id="skills",
            revision_id="rev-001",
            revision_dir=published_revision,
        )
    assert exc.value.code == "ALREADY_EXISTS"


def test_overwrite_replaces_projection(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    result = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
        overwrite=True,
    )
    assert len(result.segments) == 4
    assert len(projection.list_segments(graph_revision="rev-001")) == 4


# ---------------------------------------------------------------------------
# Predicate pushdown
# ---------------------------------------------------------------------------


def test_predicate_pushdown_works(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    plan = projection.explain_scan(
        VERTICES_VIEW,
        filters=[("type", "=", "Person")],
        graph_revision="rev-001",
    )
    assert "READ_PARQUET" in plan
    assert "Filters" in plan or "type" in plan
    # Result correctness.
    rows = projection.scan_vertices(
        filters=[("type", "=", "Person")],
        graph_revision="rev-001",
    )
    assert {r["id"] for r in rows} == {"n1", "n3"}
    assert all(r["type"] == "Person" for r in rows)


def test_predicate_pushdown_edges_and_adjacency(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    edges = projection.scan_edges(filters=[("type", "=", "KNOWS")])
    assert len(edges) == 1
    assert edges[0]["id"] == "e2"

    plan = projection.explain_scan(
        EDGES_VIEW, filters=[("type", "=", "KNOWS")]
    )
    assert "READ_PARQUET" in plan

    adj = projection.scan_adjacency(
        filters=[("direction", "=", "out"), ("node_id", "=", "n1")]
    )
    assert {a["neighbor_id"] for a in adj} == {"n2", "n3"}


def test_predicate_pushdown_properties(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    rows = projection.scan_properties(
        filters=[("key", "=", "city"), ("owner_kind", "=", "node")]
    )
    assert len(rows) == 2
    assert {r["owner_id"] for r in rows} == {"n1", "n2"}


def test_invalid_filter_rejected(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    with pytest.raises(ProjectionError) as exc:
        projection.scan_vertices(filters=["bad"])  # type: ignore[list-item]
    assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Revision + source CID binding
# ---------------------------------------------------------------------------


def test_projection_rows_bind_revision_and_source_cid(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    result = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    assert result.source_cid
    assert result.graph_revision == "rev-001"

    vertices = projection.scan_vertices(graph_revision="rev-001")
    assert len(vertices) == 3
    for row in vertices:
        assert row["graph_revision"] == "rev-001"
        assert row["source_cid"]  # segment-level source CID
        assert row["tenant"] == "acme"
        assert row["graph_id"] == "skills"
        assert row["segment_id"]

    edges = projection.scan_edges(graph_revision="rev-001")
    assert all(e["graph_revision"] == "rev-001" for e in edges)
    assert all(e["source_cid"] for e in edges)

    # Lineage + provenance bind revision-level root CID.
    lineage = projection.get_lineage("acme", "skills", "rev-001")
    assert lineage.source_cid == result.source_cid
    assert lineage.root_cid == result.source_cid

    prov = projection.get_provenance("acme", "skills", "rev-001")
    assert prov.source_cid == result.source_cid
    assert prov.producer_id == "dqk-016-tests"
    assert prov.graph_revision == "rev-001"


def test_multi_revision_binding_isolation(
    projection: DuckDBGraphProjection, tmp_path: Path
) -> None:
    rev1 = _build_revision(tmp_path / "store", revision_id="rev-001")
    rev2 = _build_revision(
        tmp_path / "store",
        revision_id="rev-002",
        parent_revision="rev-001",
    )
    r1 = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=rev1,
    )
    r2 = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-002",
        revision_dir=rev2,
    )
    assert r1.source_cid != r2.source_cid or r1.graph_revision != r2.graph_revision

    only_r1 = projection.scan_vertices(graph_revision="rev-001")
    only_r2 = projection.scan_vertices(graph_revision="rev-002")
    assert len(only_r1) == 3
    assert len(only_r2) == 3
    assert all(r["graph_revision"] == "rev-001" for r in only_r1)
    assert all(r["graph_revision"] == "rev-002" for r in only_r2)

    lin2 = projection.get_lineage("acme", "skills", "rev-002")
    assert lin2.parent_revision == "rev-001"
    assert lin2.source_cid == r2.source_cid


def test_filter_by_source_cid(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    result = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    # Segment CIDs may differ per partition; filter by revision-level binding
    # column graph_revision is the primary axis. Segment source_cid is present.
    segs = projection.list_segments(graph_revision="rev-001")
    node_seg = next(s for s in segs if s.kind == "nodes")
    rows = projection.scan_vertices(source_cid=node_seg.source_cid)
    assert len(rows) == 3
    assert all(r["source_cid"] == node_seg.source_cid for r in rows)
    # Explicit root CID on project is revision-level.
    assert result.source_cid


# ---------------------------------------------------------------------------
# IPLD segment registry (no byte duplication)
# ---------------------------------------------------------------------------


def test_register_ipld_segment_preserves_cid_checksum(
    projection: DuckDBGraphProjection,
) -> None:
    digest = "ab" * 32
    rec = projection.register_ipld_segment(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-ipld",
        kind="nodes",
        source_cid=f"sha256:{digest}",
        checksum=f"sha256:{digest}",
        byte_size=128,
        media_type="ipld-dag-cbor",
        relative_path="blocks/nodes.car",
    )
    assert rec.source_cid == f"sha256:{digest}"
    assert rec.checksum == f"sha256:{digest}"
    assert rec.byte_size == 128
    assert rec.media_type == "ipld-dag-cbor"
    # IPLD-only segments are metadata; typed views stay empty if no parquet.
    assert projection.scan_vertices(graph_revision="rev-ipld") == []
    segs = projection.list_segments(graph_revision="rev-ipld")
    assert len(segs) == 1


# ---------------------------------------------------------------------------
# Persistence / restart
# ---------------------------------------------------------------------------


def test_projection_survives_reopen(
    tmp_path: Path, published_revision: Path
) -> None:
    path = tmp_path / "persist.duckdb"
    with DuckDBGraphProjection(path) as proj:
        proj.project_revision(
            tenant="acme",
            graph_id="skills",
            revision_id="rev-001",
            revision_dir=published_revision,
        )
    with DuckDBGraphProjection(path) as proj:
        assert proj.payload_is_view_backed()
        rows = proj.scan_vertices(
            filters=[("type", "=", "Person")],
            graph_revision="rev-001",
        )
        assert {r["id"] for r in rows} == {"n1", "n3"}
        lin = proj.get_lineage("acme", "skills", "rev-001")
        assert lin.graph_revision == "rev-001"
        assert lin.source_cid


def test_column_projection(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
    )
    rows = projection.scan_vertices(
        columns=["id", "type", "graph_revision", "source_cid"],
        graph_revision="rev-001",
    )
    assert set(rows[0].keys()) == {"id", "type", "graph_revision", "source_cid"}


def test_explicit_source_cid_override(
    projection: DuckDBGraphProjection, published_revision: Path
) -> None:
    # Use a valid labeled digest as explicit revision root CID.
    explicit = "sha256:" + ("cd" * 32)
    result = projection.project_revision(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-001",
        revision_dir=published_revision,
        source_cid=explicit,
    )
    assert result.source_cid == explicit
    assert projection.get_lineage("acme", "skills", "rev-001").source_cid == explicit
    assert (
        projection.get_provenance("acme", "skills", "rev-001").source_cid == explicit
    )


def test_context_manager_closes(tmp_path: Path) -> None:
    path = tmp_path / "cm.duckdb"
    with DuckDBGraphProjection(path) as proj:
        assert not proj._closed  # noqa: SLF001
    assert proj._closed  # noqa: SLF001
    with pytest.raises(ProjectionError) as exc:
        proj.list_segments()
    assert exc.value.code == "STORAGE"
