"""Integration / differential suite for the read-only CVEfixes adapter (KGP-024).

Coverage:
* tiny checked fixture (always-on): source Parquet, manifest, graph
  node/edge/adjacency shards, vector artifacts, checksums, counts, provenance,
  CVE/CWE/file/commit traversals, missing/corrupt shard fail-closed behavior,
  and parity with the existing query script when the nested producer tree is
  present
* environment-gated full-corpus receipt when ``CVEFIXES_CORPUS_ROOT`` (or the
  default ``lift_coding/.cvefixes-build/release-with-original-v2``) is available
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.knowledge_graphs.adapters.cvefixes import (
    CVEfixesAdapterError,
    CVEfixesCorpusAdapter,
    ENV_RELEASE_ROOT,
    EXPECTED_FULL_COUNTS,
    EXPECTED_PROVENANCE,
    LOCAL_FIXTURE_REVISION,
    build_tiny_fixture_release,
    differential_query_parity,
    discover_release_root,
    discover_source_root,
    load_legacy_query_module,
    open_release_reader,
    validate_manifest,
    validate_source_parquet,
    _raw_sha256_cid,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def tiny_release(tmp_path: Path) -> Path:
    return build_tiny_fixture_release(tmp_path / "cvefixes-tiny")


@pytest.fixture
def adapter(tiny_release: Path) -> CVEfixesCorpusAdapter:
    return CVEfixesCorpusAdapter(
        tiny_release,
        source_root=tiny_release / "source" / "data",
        revision=LOCAL_FIXTURE_REVISION,
    )


def test_tiny_fixture_validates_manifest_source_shards_and_provenance(
    adapter: CVEfixesCorpusAdapter,
) -> None:
    receipt = adapter.validate(verify_data_checksums=True, max_data_shards=None)
    assert receipt["schema"] == "cvefixes-corpus-validation-receipt/v1"
    assert receipt["manifest"]["schema_version"] == "cvefixes-huggingface-release/v1"
    assert receipt["manifest"]["primary_key"] == "entry_cid"
    assert receipt["manifest"]["counts"]["graph_nodes"] == 4
    assert receipt["manifest"]["counts"]["graph_edges"] == 3
    assert receipt["source"] is not None
    assert receipt["source"]["row_count"] == 1
    assert receipt["source"]["shard_count"] == 1
    assert receipt["provenance"]["source_dataset_id"] == (
        EXPECTED_PROVENANCE["source_dataset_id"]
    )
    assert receipt["provenance"]["source_revision"] == (
        EXPECTED_PROVENANCE["source_revision"]
    )
    assert receipt["provenance"]["graph_root_cid"] == (
        EXPECTED_PROVENANCE["graph_root_cid"]
    )
    kinds = receipt["shards"]["kinds"]
    for kind in (
        "graph_nodes",
        "graph_edges",
        "graph_outgoing_adjacency",
        "graph_incoming_adjacency",
        "vectors",
        "corpus",
    ):
        assert kinds[kind]["shard_count"] >= 1
        assert kinds[kind]["row_count_checked"] >= 1
    assert receipt["shards"]["checksums_verified"] >= 1
    assert receipt["shards"]["count_comparisons"]["graph_nodes"] == 4
    assert receipt["shards"]["count_comparisons"]["graph_edges"] == 3


def test_tiny_fixture_source_parquet_discovery(tiny_release: Path) -> None:
    source = tiny_release / "source" / "data"
    receipt = validate_source_parquet(source, expected_rows=1)
    assert receipt["row_count"] == 1
    assert receipt["shards"][0]["sha256"]
    with pytest.raises(CVEfixesAdapterError, match="row count differs"):
        validate_source_parquet(source, expected_rows=99)


def test_representative_cve_cwe_file_commit_traversal(
    adapter: CVEfixesCorpusAdapter,
) -> None:
    traversal = adapter.traverse_cve(
        "CVE-2018-1000524",
        max_depth=2,
        max_nodes=16,
        max_edges=32,
        max_shards=8,
        per_node_limit=8,
    )
    assert traversal["found"] is True
    assert traversal["has_cwe"] is True
    assert traversal["has_commit"] is True
    assert traversal["has_file"] is True
    types = set(traversal["by_type"])
    assert "cve" in types
    assert "cwe" in types
    assert "commit" in types
    assert "code_unit" in types
    edge_types = {edge["edge_type"] for edge in traversal["edges"]}
    assert "CLASSIFIED_AS" in edge_types
    assert "FIXED_BY" in edge_types
    assert "CHANGES" in edge_types

    neighbors = adapter.graph_neighbors(
        "node-cve-1",
        direction="outgoing",
        limit=10,
        hydrate=True,
        max_shards=4,
    )
    neighbor_types = {
        row["neighbor_node_type"] for row in neighbors["results"]
    }
    assert neighbor_types == {"cwe", "commit"}
    assert neighbors["result_count"] == 2


def test_bm25_and_vector_bounded_queries(adapter: CVEfixesCorpusAdapter) -> None:
    bm25 = adapter.bm25("buffer-overflow", top_k=1)
    assert bm25["mode"] == "bm25"
    assert bm25["result_count"] == 1
    assert bm25["results"][0]["entry_cid"] == "entry-a"
    assert "overflow" in bm25["results"][0]["matched_terms"]

    vector = adapter.vector(
        "path repair",
        top_k=1,
        query_vector=[0.0, 1.0],
        candidate_centroids=1,
        max_vector_shards=1,
    )
    assert vector["mode"] == "vector"
    assert vector["results"][0]["entry_cid"] == "entry-b"
    assert vector["diagnostics"]["vector_shards_fetched"] == 1


def test_missing_shard_fails_closed(tiny_release: Path) -> None:
    target = tiny_release / "data/graph/nodes/part-000000.parquet"
    assert target.is_file()
    target.unlink()
    adapter = CVEfixesCorpusAdapter(
        tiny_release,
        source_root=tiny_release / "source" / "data",
        revision=LOCAL_FIXTURE_REVISION,
    )
    with pytest.raises(CVEfixesAdapterError, match="missing"):
        adapter.validate(verify_data_checksums=False)


def test_corrupt_shard_digest_fails_closed(tiny_release: Path) -> None:
    # Flip a meta-index descriptor CID so integrity checks fail before query.
    manifest_path = tiny_release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrong = hashlib.sha256(b"wrong artifact").digest()
    manifest["indexes"]["bm25_keyword_shards"]["cid"] = _raw_sha256_cid(wrong)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = CVEfixesCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(CVEfixesAdapterError, match="CID differs"):
        adapter.bm25("overflow", top_k=1)


def test_corrupt_data_shard_bytes_fail_closed(tiny_release: Path) -> None:
    path = tiny_release / "data/bm25/postings/part-000000.parquet"
    path.write_bytes(b"not a parquet file at all")
    # Refresh manifest artifact checksums would still list old sha; validation
    # of graph/vector uses artifact map — for query path, loaded shard fails.
    adapter = CVEfixesCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(CVEfixesAdapterError):
        adapter.bm25("overflow", top_k=1)


def test_declared_key_range_mismatch_fails_closed(tiny_release: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    index_path = tiny_release / "indexes/bm25_keyword_shards.parquet"
    rows = pq.read_table(index_path).to_pylist()
    rows[0]["first_key"] = "aardvark"
    pq.write_table(pa.Table.from_pylist(rows), index_path, compression="zstd")
    content = index_path.read_bytes()
    digest = hashlib.sha256(content).digest()
    manifest_path = tiny_release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["indexes"]["bm25_keyword_shards"] = {
        "cid": _raw_sha256_cid(digest),
        "relative_path": "indexes/bm25_keyword_shards.parquet",
        "row_count": 1,
        "sha256": digest.hex(),
        "size_bytes": len(content),
    }
    # Keep other indexes intact.
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = CVEfixesCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(CVEfixesAdapterError, match="key range differs"):
        adapter.bm25("overflow", top_k=1)


def test_parity_with_existing_query_script(tiny_release: Path) -> None:
    receipt = differential_query_parity(
        tiny_release,
        revision=LOCAL_FIXTURE_REVISION,
        bm25_query="overflow",
        graph_node_cid="node-cve-1",
    )
    assert receipt["parity"] in {"matched", "self_only"}
    if receipt["legacy_available"]:
        assert receipt["parity"] == "matched"
        assert receipt["bm25_result_count"] == 1
        assert receipt["bm25_entry_cids"] == ["entry-a"]
        assert receipt["graph"]["skipped"] is False
        assert receipt["graph"]["neighbor_count"] == 2
    else:
        assert receipt["adapter_bm25_count"] == 1


def test_open_release_reader_graph_node_lookup(tiny_release: Path) -> None:
    reader = open_release_reader(tiny_release)
    found = reader.graph_node("node-cve-1")
    assert found["diagnostics"]["found"] is True
    assert found["results"][0]["label"] == "CVE-2018-1000524"
    missing = reader.graph_node("node-does-not-exist")
    assert missing["diagnostics"]["found"] is False
    assert missing["results"] == []


def test_validate_manifest_rejects_bad_schema(tiny_release: Path) -> None:
    manifest_path = tiny_release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "not-a-real-schema"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CVEfixesAdapterError, match="unsupported"):
        validate_manifest(tiny_release)


# ---------------------------------------------------------------------------
# Environment-gated full-corpus receipt
# ---------------------------------------------------------------------------


def _full_corpus_available() -> bool:
    root = discover_release_root()
    return root is not None and (root / "manifest.json").is_file()


@pytest.mark.skipif(
    not _full_corpus_available(),
    reason=(
        "full CVEfixes corpus not available; set CVEFIXES_CORPUS_ROOT or "
        "install lift_coding/.cvefixes-build"
    ),
)
def test_full_corpus_validation_receipt() -> None:
    release = discover_release_root()
    assert release is not None
    source = discover_source_root()
    adapter = CVEfixesCorpusAdapter(
        release,
        source_root=source,
        revision=LOCAL_FIXTURE_REVISION,
    )
    # Cap per-kind data-shard checksum enumeration for wall-clock; indexes and
    # manifest counts still pin full provenance. One shard per kind is enough
    # to prove layout + readability; counts come from the manifest.
    receipt = adapter.validate(
        verify_data_checksums=True,
        max_data_shards=2,
        expected_full_corpus=True,
    )
    assert receipt["expected_full_corpus"] is True
    counts = receipt["manifest"]["counts"]
    for key, expected in EXPECTED_FULL_COUNTS.items():
        assert int(counts[key]) == int(expected), key
    for key, expected in EXPECTED_PROVENANCE.items():
        assert receipt["provenance"].get(key) == expected, key
    if source is not None:
        assert receipt["source"] is not None
        assert receipt["source"]["row_count"] == EXPECTED_FULL_COUNTS[
            "original_data_rows"
        ]
    # Representative full-corpus traversal (bounded).
    traversal = adapter.traverse_cve(
        "CVE-2018-1000524",
        max_depth=1,
        max_nodes=16,
        max_edges=32,
        max_shards=16,
        per_node_limit=8,
    )
    assert traversal["found"] is True
    assert traversal["has_cwe"] or traversal["has_commit"] or traversal[
        "has_repository"
    ]
    # Differential parity against the nested query script when present.
    parity = adapter.differential_parity(bm25_query="overflow")
    assert parity["parity"] in {"matched", "self_only"}
    if load_legacy_query_module() is not None:
        assert parity["legacy_available"] is True
        assert parity["parity"] == "matched"


def test_discovery_helpers_do_not_raise() -> None:
    # Smoke: helpers are side-effect free and tolerate missing corpora.
    _ = discover_release_root()
    _ = discover_source_root()
    _ = os.environ.get(ENV_RELEASE_ROOT)


def test_legacy_loader_is_optional() -> None:
    module = load_legacy_query_module()
    if module is not None:
        assert hasattr(module, "CVEfixesRemoteIndex")
        assert hasattr(module, "ArtifactResolver")
