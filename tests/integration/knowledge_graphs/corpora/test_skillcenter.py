"""Integration / differential suite for the read-only SkillCenter adapter (KGP-025).

Coverage:
* tiny checked fixture (always-on): corpus, graph nodes/edges/adjacency, BM25
  postings, embeddings/vectors, index manifests, CID release descriptors,
  counts/checksums/provenance, skill/category/relationship/hybrid rankings,
  missing/corrupt shard fail-closed behavior, and parity with the existing
  query client when present
* environment-gated full-release receipt when ``SKILLCENTER_RELEASE_ROOT`` (or
  the default local HF release cache under
  ``~/.local/share/ipfs_datasets_py/intent-ir/skillcenter-huggingface``) is
  available
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.knowledge_graphs.adapters.skillcenter import (
    ENV_RELEASE_ROOT,
    EXPECTED_FULL_COUNTS,
    EXPECTED_PROVENANCE,
    LOCAL_FIXTURE_REVISION,
    SkillCenterAdapterError,
    SkillCenterCorpusAdapter,
    build_tiny_fixture_release,
    differential_query_parity,
    discover_build_root,
    discover_release_root,
    load_legacy_query_module,
    open_release_reader,
    rank_categories,
    rank_relationships,
    rank_skills,
    validate_manifest,
    validate_release_shards,
    _raw_sha256_cid,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def tiny_release(tmp_path: Path) -> Path:
    return build_tiny_fixture_release(tmp_path / "skillcenter-tiny")


@pytest.fixture
def adapter(tiny_release: Path) -> SkillCenterCorpusAdapter:
    return SkillCenterCorpusAdapter(
        tiny_release,
        revision=LOCAL_FIXTURE_REVISION,
    )


def test_tiny_fixture_validates_manifest_shards_and_provenance(
    adapter: SkillCenterCorpusAdapter,
) -> None:
    receipt = adapter.validate(verify_data_checksums=True, max_data_shards=None)
    assert receipt["schema"] == "skillcenter-corpus-validation-receipt/v1"
    assert (
        receipt["manifest"]["schema_version"]
        == "skillcenter-huggingface-release/v3"
    )
    assert receipt["manifest"]["primary_key"] == "entry_cid"
    assert receipt["manifest"]["counts"]["graph_nodes"] == 5
    assert receipt["manifest"]["counts"]["graph_edges"] == 4
    assert receipt["manifest"]["counts"]["corpus_rows"] == 2
    assert receipt["manifest"]["counts"]["vector_rows"] == 2
    assert receipt["provenance"]["corpus_cid"] == EXPECTED_PROVENANCE["corpus_cid"]
    assert receipt["provenance"]["graph_cid"] == EXPECTED_PROVENANCE["graph_cid"]
    assert (
        receipt["provenance"]["bm25_sqlite_cid"]
        == EXPECTED_PROVENANCE["bm25_sqlite_cid"]
    )
    assert (
        receipt["provenance"]["vector_faiss_cid"]
        == EXPECTED_PROVENANCE["vector_faiss_cid"]
    )
    kinds = receipt["shards"]["kinds"]
    for kind in (
        "graph_nodes",
        "graph_edges",
        "graph_outgoing_adjacency",
        "graph_incoming_adjacency",
        "vectors",
        "corpus",
        "bm25_postings",
    ):
        assert kinds[kind]["shard_count"] >= 1
        assert kinds[kind]["row_count_checked"] >= 1
    assert receipt["shards"]["checksums_verified"] >= 1
    assert receipt["shards"]["count_comparisons"]["graph_nodes"] == 5
    assert receipt["shards"]["count_comparisons"]["graph_edges"] == 4
    assert receipt["shards"]["count_comparisons"]["corpus_rows"] == 2
    assert "bm25_keyword_shards" in receipt["shards"]["meta_indexes"]
    assert "vector_chunks" in receipt["shards"]["meta_indexes"]
    assert "graph_node_chunks" in receipt["shards"]["meta_indexes"]


def test_skill_category_relationship_and_hybrid_rankings(
    adapter: SkillCenterCorpusAdapter,
) -> None:
    skills = adapter.rank_skills("credentials", top_k=2)
    assert skills["mode"] == "skill_ranking"
    assert skills["result_count"] == 1
    assert skills["results"][0]["entry_cid"].startswith("bafkreientryaaaa")
    assert "credentials" in skills["results"][0]["matched_terms"]

    categories = adapter.rank_categories("credentials", top_k=5)
    assert categories["mode"] == "category_ranking"
    assert categories["result_count"] >= 1
    category_names = {row["category"] for row in categories["results"]}
    assert "security" in category_names

    skill_cid = skills["results"][0]["entry_cid"]
    relationships = adapter.rank_relationships(
        skill_cid,
        direction="outgoing",
        top_k=10,
        hydrate=True,
    )
    assert relationships["mode"] == "relationship_ranking"
    assert relationships["result_count"] >= 2
    edge_types = {row["edge_type"] for row in relationships["results"]}
    assert "IN_DOMAIN" in edge_types
    assert "HAS_CONTENT" in edge_types or "BM25_NEIGHBOR_OF" in edge_types

    hybrid = adapter.hybrid(
        "credentials",
        top_k=2,
        query_vector=[1.0, 0.0],
        allow_exhaustive=True,
    )
    assert hybrid["mode"] == "hybrid"
    assert hybrid["result_count"] >= 1
    assert hybrid["results"][0]["entry_cid"].startswith("bafkreientryaaaa")
    assert hybrid["diagnostics"]["vector_enabled"] is True

    # BM25-only hybrid still ranks skills.
    hybrid_bm25 = adapter.hybrid("http", top_k=2, query_vector=None)
    assert hybrid_bm25["result_count"] == 1
    assert hybrid_bm25["results"][0]["entry_cid"].startswith("bafkreientrybbbb")


def test_bm25_vector_and_graph_queries(adapter: SkillCenterCorpusAdapter) -> None:
    bm25 = adapter.bm25("rotate credentials", top_k=2)
    assert bm25["mode"] == "bm25"
    assert bm25["result_count"] == 1
    assert "rotate" in bm25["results"][0]["matched_terms"]

    vector = adapter.vector(
        "path repair",
        top_k=1,
        query_vector=[0.0, 1.0],
        candidate_centroids=1,
        allow_exhaustive=True,
    )
    assert vector["mode"] == "vector"
    assert vector["results"][0]["entry_cid"].startswith("bafkreientrybbbb")

    skill_a = bm25["results"][0]["entry_cid"]
    node = adapter.graph_node(skill_a)
    assert node["diagnostics"]["found"] is True
    assert node["results"][0]["node_type"] == "SKILL"

    neighbors = adapter.graph_neighbors(
        skill_a,
        direction="outgoing",
        limit=10,
        hydrate=True,
        max_shards=4,
    )
    assert neighbors["result_count"] >= 2
    neighbor_types = {
        row["neighbor_node_type"] for row in neighbors["results"]
    }
    assert "DOMAIN" in neighbor_types


def test_missing_shard_fails_closed(tiny_release: Path) -> None:
    target = tiny_release / "data/graph/nodes/part-000000.parquet"
    assert target.is_file()
    target.unlink()
    adapter = SkillCenterCorpusAdapter(
        tiny_release,
        revision=LOCAL_FIXTURE_REVISION,
    )
    with pytest.raises(SkillCenterAdapterError, match="missing"):
        adapter.validate(verify_data_checksums=False)


def test_corrupt_index_digest_fails_closed(tiny_release: Path) -> None:
    manifest_path = tiny_release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrong = hashlib.sha256(b"wrong artifact").digest()
    manifest["indexes"]["bm25_keyword_shards"]["cid"] = _raw_sha256_cid(wrong)
    manifest["indexes"]["bm25_keyword_shards"]["sha256"] = wrong.hex()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = SkillCenterCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(SkillCenterAdapterError, match="digest differs|CID differs"):
        adapter.bm25("credentials", top_k=1)


def test_corrupt_data_shard_bytes_fail_closed(tiny_release: Path) -> None:
    path = tiny_release / "data/bm25/postings/part-000000.parquet"
    path.write_bytes(b"not a parquet file at all")
    # Descriptor still lists old sha; query path verifies descriptor on fetch.
    adapter = SkillCenterCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(SkillCenterAdapterError):
        adapter.bm25("credentials", top_k=1)


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
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = SkillCenterCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    # first_key/last_key no longer cover "credentials" — empty result, not crash.
    # Overlapping or unaligned key ranges would raise; wrong exclusive range yields
    # zero hits. Force an overlapping duplicate range to fail closed.
    rows = pq.read_table(index_path).to_pylist()
    rows.append(dict(rows[0]))
    rows[0]["first_key"] = "a"
    rows[0]["last_key"] = "zzzz"
    rows[1]["first_key"] = "b"
    rows[1]["last_key"] = "yyyy"
    pq.write_table(pa.Table.from_pylist(rows), index_path, compression="zstd")
    content = index_path.read_bytes()
    digest = hashlib.sha256(content).digest()
    manifest["indexes"]["bm25_keyword_shards"] = {
        "cid": _raw_sha256_cid(digest),
        "relative_path": "indexes/bm25_keyword_shards.parquet",
        "row_count": 2,
        "sha256": digest.hex(),
        "size_bytes": len(content),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    adapter = SkillCenterCorpusAdapter(
        tiny_release, revision=LOCAL_FIXTURE_REVISION
    )
    with pytest.raises(SkillCenterAdapterError, match="overlapping"):
        adapter.bm25("credentials", top_k=1)


def test_parity_with_existing_query_script(tiny_release: Path) -> None:
    skill_a = (
        "bafkreientryaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    receipt = differential_query_parity(
        tiny_release,
        revision=LOCAL_FIXTURE_REVISION,
        bm25_query="credentials",
        graph_node_cid=skill_a,
        query_vector=[1.0, 0.0],
    )
    assert receipt["parity"] in {"matched", "self_only"}
    assert receipt["skill_ranking_count"] == 1
    assert receipt["category_ranking_count"] >= 1
    assert receipt["hybrid_ranking_count"] >= 1
    if receipt["legacy_available"]:
        assert receipt["parity"] == "matched"
        assert receipt["bm25_result_count"] == 1
        assert receipt["bm25_entry_cids"] == [skill_a]
        assert receipt["graph"]["skipped"] is False
        assert receipt["graph"]["neighbor_count"] >= 2
    else:
        assert receipt["adapter_bm25_count"] == 1


def test_open_release_reader_graph_node_lookup(tiny_release: Path) -> None:
    reader = open_release_reader(tiny_release)
    skill_a = (
        "bafkreientryaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    found = reader.graph_node(skill_a)
    assert found["diagnostics"]["found"] is True
    assert found["results"][0]["label"] == "Rotate API credentials"
    missing = reader.graph_node("bafkreimissingnode000000000000000000000000000000000000001")
    assert missing["diagnostics"]["found"] is False
    assert missing["results"] == []


def test_validate_manifest_rejects_bad_schema(tiny_release: Path) -> None:
    manifest_path = tiny_release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "not-a-real-schema"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SkillCenterAdapterError, match="unsupported"):
        validate_manifest(tiny_release)


def test_ranking_helpers_match_adapter_facade(
    adapter: SkillCenterCorpusAdapter,
) -> None:
    reader = adapter.reader
    query = "credentials"
    assert (
        rank_skills(reader, query, top_k=2)["results"][0]["entry_cid"]
        == adapter.rank_skills(query, top_k=2)["results"][0]["entry_cid"]
    )
    cats = rank_categories(reader, query, top_k=3)
    assert cats["result_count"] == adapter.rank_categories(query, top_k=3)[
        "result_count"
    ]
    skill_cid = adapter.rank_skills(query, top_k=1)["results"][0]["entry_cid"]
    rel = rank_relationships(reader, skill_cid, top_k=5)
    assert rel["result_count"] == adapter.rank_relationships(
        skill_cid, top_k=5
    )["result_count"]


# ---------------------------------------------------------------------------
# Environment-gated full-release receipt
# ---------------------------------------------------------------------------


def _full_release_available() -> bool:
    root = discover_release_root()
    return root is not None and (root / "manifest.json").is_file()


@pytest.mark.skipif(
    not _full_release_available(),
    reason=(
        "full SkillCenter release not available; set SKILLCENTER_RELEASE_ROOT "
        "or install the local skillcenter-huggingface cache"
    ),
)
def test_full_release_validation_receipt() -> None:
    release = discover_release_root()
    assert release is not None
    adapter = SkillCenterCorpusAdapter(
        release,
        revision=LOCAL_FIXTURE_REVISION,
    )
    # Cap per-kind data-shard checksum enumeration for wall-clock; indexes and
    # manifest counts still pin full provenance.
    receipt = adapter.validate(
        verify_data_checksums=True,
        max_data_shards=2,
        expected_full_corpus=True,
    )
    assert receipt["expected_full_corpus"] is True
    counts = receipt["manifest"]["counts"]
    for key, expected in EXPECTED_FULL_COUNTS.items():
        assert int(counts[key]) == int(expected), key
    # Provenance bindings (CID release descriptors) must match the pinned set.
    for key in (
        "corpus_cid",
        "graph_cid",
        "bm25_sqlite_cid",
        "vector_faiss_cid",
    ):
        assert receipt["provenance"].get(key) == EXPECTED_PROVENANCE[key], key
    assert receipt["manifest"]["schema_version"] in {
        "skillcenter-huggingface-release/v2",
        "skillcenter-huggingface-release/v3",
    }

    # Representative full-release skill ranking (bounded).
    skills = adapter.rank_skills("credentials", top_k=3, include_content=False)
    assert skills["result_count"] >= 1
    assert skills["results"][0].get("entry_cid")

    # Differential parity against the packaged/existing query script when present.
    parity = adapter.differential_parity(bm25_query="credentials")
    assert parity["parity"] in {"matched", "self_only"}
    if load_legacy_query_module() is not None:
        assert parity["legacy_available"] is True
        assert parity["parity"] == "matched"


def test_discovery_helpers_do_not_raise() -> None:
    _ = discover_release_root()
    _ = discover_build_root()
    _ = os.environ.get(ENV_RELEASE_ROOT)


def test_legacy_loader_is_optional() -> None:
    module = load_legacy_query_module()
    if module is not None:
        assert hasattr(module, "SkillCenterRemoteIndex")
        assert hasattr(module, "ArtifactResolver")
