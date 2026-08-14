"""Unit tests for Open US Law centroid-routed vectors (OUL-029).

Acceptance: deterministic balanced spherical k-means yields at most 8192
rows and two shards per centroid; every physical shard has at most 4096
vectors sorted by descending centroid cosine then entry CID; a dedicated
entry-to-shard locator supports off-centroid graph frontier hydration.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PROJECTION_BACKEND,
    EmbeddingRecord,
    fixture_embedding_config,
    generate_open_us_law_embeddings,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_vectors import (
    ASSIGNMENT,
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_TARGET_ROWS_PER_CENTROID,
    DEFAULT_VECTOR_KMEANS_SEED,
    EMPTY_CLUSTER_POLICY,
    ENTRY_LOCATOR_KEY,
    GOAL_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PRIMARY_KEY,
    PROGRAM_ID,
    RECEIPT_SCHEMA_VERSION,
    ROWS_SORTED_BY,
    SCHEMA_VERSION,
    TASK_ID,
    VECTOR_ENTRY_LOCATOR_DIR,
    CorpusParentLink,
    OpenUsLawVectorBinding,
    VectorBindingError,
    VectorCoverageError,
    VectorReceiptError,
    VectorReleaseAuthorizationError,
    VectorRootReconcileError,
    VectorRouteBoundError,
    assert_centroid_routes_bounded,
    assert_every_chunk_once,
    assert_rows_sorted_by_centroid_cosine_then_entry_cid,
    assert_vector_receipt,
    bind_fixture_vectors,
    bind_open_us_law_vectors,
    bind_open_us_law_vectors_from_chunks,
    build_layout_root_cid,
    build_membership_hash,
    build_model_cid,
    build_vector_receipt,
    default_test_bounds,
    default_vector_receipt_path,
    fixture_vector_chunks,
    load_vector_receipt,
    production_vector_bounds,
    prove_direct_cid_off_centroid_fetch,
    prove_entry_locator_off_centroid_hydration,
    reconcile_roots,
    select_off_centroid_entry_cids,
    select_off_centroid_keys,
    shard_first_last_keys_are_lexical_ranges,
    write_vector_receipt,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import MissingKeyError


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def _cpu_probe(device: str) -> bool:
    return str(device).startswith("cpu")


def _axis_unit(index: int, dimension: int = PINNED_DIMENSION) -> tuple[float, ...]:
    values = [0.0] * dimension
    values[index % dimension] = 1.0
    return tuple(values)


def _record(
    *,
    chunk_nibble: str,
    entry_nibble: str,
    embedding: Sequence[float] | None = None,
    axis: int = 0,
    config_cid: str | None = None,
) -> EmbeddingRecord:
    pin = fixture_embedding_config()
    vector = tuple(embedding) if embedding is not None else _axis_unit(axis)
    return EmbeddingRecord(
        chunk_cid=_cid(chunk_nibble),
        embedding=vector,
        dimension=PINNED_DIMENSION,
        input_hash=f"{chunk_nibble}-input",
        model_id=pin.model_id,
        model_revision=pin.model_revision,
        vector_space_id=pin.vector_space_id,
        pooling=pin.pooling,
        normalization=pin.normalization,
        l2_norm=1.0,
        config_cid=config_cid or pin.config_cid,
        entry_cid=_cid(entry_nibble),
    )


# ---------------------------------------------------------------------------
# Identity / production bounds
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-vectors-v1"
    assert RECEIPT_SCHEMA_VERSION == "open-us-law-vector-receipt-v1"
    assert TASK_ID == "OUL-029"
    assert GOAL_ID == "OUL-G040"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert PRIMARY_KEY == "chunk_cid"
    assert ENTRY_LOCATOR_KEY == "entry_cid"
    assert ROWS_SORTED_BY == "centroid_cosine_desc_then_entry_cid"
    assert ASSIGNMENT == "deterministic_balanced_spherical_kmeans"
    assert "empty" in EMPTY_CLUSTER_POLICY
    assert VECTOR_ENTRY_LOCATOR_DIR == "indexes/vector_entry_locator"
    assert RELEASE_PROFILE == "open-us-law-sparse-graphrag/v1"


def test_production_bounds_match_release_policy() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2
    assert DEFAULT_CANDIDATE_CENTROIDS == 4
    assert DEFAULT_TARGET_ROWS_PER_CENTROID == 2048
    bounds = production_vector_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == 4096
    assert bounds["maximum_rows_per_centroid"] == 8192
    assert bounds["maximum_shards_per_centroid"] == 2
    assert bounds["sort_order"] == ROWS_SORTED_BY
    assert bounds["target_rows_per_centroid"] == 2048


def test_oversize_centroid_bound_fails_closed() -> None:
    with pytest.raises(VectorRouteBoundError):
        bind_open_us_law_vectors(
            [_record(chunk_nibble="a", entry_nibble="b")],
            max_rows_per_centroid=8193,
            max_rows_per_shard=4096,
            max_shards_per_centroid=2,
        )


def test_oversize_shard_bound_fails_closed() -> None:
    with pytest.raises(VectorRouteBoundError):
        bind_open_us_law_vectors(
            [_record(chunk_nibble="a", entry_nibble="b")],
            max_rows_per_shard=4097,
        )


def test_more_than_two_shards_per_centroid_fails_closed() -> None:
    with pytest.raises(VectorRouteBoundError):
        bind_open_us_law_vectors(
            [_record(chunk_nibble="a", entry_nibble="b")],
            max_shards_per_centroid=3,
        )


# ---------------------------------------------------------------------------
# Coverage: every chunk exactly once
# ---------------------------------------------------------------------------


def test_every_embedded_chunk_appears_exactly_once() -> None:
    chunks = fixture_vector_chunks()
    binding = bind_fixture_vectors(chunks)
    expected = sorted(row["chunk_cid"] for row in chunks)
    assert binding.vector_count == len(chunks)
    assert sorted(binding.vector_keys) == expected
    assert len(binding.vector_keys) == len(set(binding.vector_keys))
    assert_every_chunk_once(binding.layout, expected_chunk_cids=expected)
    assert set(binding.locations) == set(expected)
    observed = [cid for shard in binding.layout.shards for cid in shard.entry_cids]
    assert sorted(observed) == expected
    assert len(observed) == len(set(observed))


def test_bind_from_embedding_result_preserves_keys() -> None:
    chunks = fixture_vector_chunks()
    result = generate_open_us_law_embeddings(
        chunks,
        config=fixture_embedding_config(),
        device_probe=_cpu_probe,
    )
    bounds = default_test_bounds()
    binding = bind_open_us_law_vectors(result, **bounds)
    assert sorted(binding.vector_keys) == sorted(result.embeddings)
    assert binding.model_id == PINNED_MODEL_ID
    assert binding.model_revision == PINNED_MODEL_REVISION
    assert isinstance(binding, OpenUsLawVectorBinding)


def test_duplicate_chunk_cid_fails_closed() -> None:
    first = _record(chunk_nibble="a", entry_nibble="b", axis=0)
    with pytest.raises(VectorCoverageError):
        bind_open_us_law_vectors(
            [first, first],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_empty_embeddings_fail_closed() -> None:
    with pytest.raises(VectorBindingError):
        bind_open_us_law_vectors({})


def test_positional_chunk_cid_rejected() -> None:
    with pytest.raises(Exception):
        bind_open_us_law_vectors_from_chunks(
            [{"chunk_cid": "row-12", "text": "positional must fail"}],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


# ---------------------------------------------------------------------------
# Centroid route bounds
# ---------------------------------------------------------------------------


def test_centroid_routes_are_bounded() -> None:
    binding = bind_fixture_vectors()
    assert_centroid_routes_bounded(binding.layout)
    assert binding.layout.max_rows_per_shard <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert binding.layout.max_rows_per_centroid <= MAX_ROWS_PER_VECTOR_CENTROID
    assert binding.layout.max_shards_per_centroid <= MAX_VECTOR_SHARDS_PER_CENTROID
    for group in binding.layout.clusters:
        assert group.row_count <= binding.layout.max_rows_per_centroid
        assert group.row_count <= 8192
        assert group.shard_count <= binding.layout.max_shards_per_centroid
        assert group.shard_count <= 2
        assert 1 <= group.shard_count
        for shard in group.shards:
            assert shard.row_count <= binding.layout.max_rows_per_shard
            assert shard.row_count <= 4096
            assert shard.row_count >= 1


def test_tight_bounds_exercise_two_shards_per_centroid() -> None:
    binding = bind_fixture_vectors()
    assert binding.vector_count == 8
    assert any(group.shard_count == 2 for group in binding.layout.clusters) or (
        binding.shard_count >= 2
    )
    for group in binding.layout.clusters:
        assert group.shard_count <= 2
        assert group.row_count <= 4


def test_routing_rows_cover_every_physical_shard() -> None:
    binding = bind_fixture_vectors()
    assert len(binding.routing_rows) == binding.shard_count
    paths = {row["relative_path"] for row in binding.routing_rows}
    layout_paths = {shard.relative_path for shard in binding.layout.shards}
    assert paths == layout_paths
    for row in binding.routing_rows:
        assert row["row_count"] <= binding.layout.max_rows_per_shard
        assert int(row["centroid_shard_count"]) in (1, 2)
        centroid = row["centroid"]
        norm = math.sqrt(sum(float(x) * float(x) for x in centroid))
        assert abs(norm - 1.0) < 1e-5
        assert row["first_last_keys_are_not_lexical_ranges"] is True
        assert row["rows_sorted_by"] == ROWS_SORTED_BY


def test_centroid_route_probe_is_bounded() -> None:
    binding = bind_fixture_vectors()
    query = list(binding.layout.shards[0].embeddings[0])
    routes = binding.route_centroids(query, candidate_centroids=1)
    assert len(routes) >= 1
    assert len(routes) <= 2
    routes4 = binding.route_centroids(query, candidate_centroids=4)
    assert len(routes4) <= binding.shard_count
    assert len(routes4) <= 4 * MAX_VECTOR_SHARDS_PER_CENTROID


# ---------------------------------------------------------------------------
# Sort: descending centroid cosine then entry CID
# ---------------------------------------------------------------------------


def test_shards_are_sorted_by_centroid_cosine_then_entry_cid() -> None:
    binding = bind_fixture_vectors()
    assert_rows_sorted_by_centroid_cosine_then_entry_cid(binding)
    for shard in binding.layout.shards:
        for offset in range(1, shard.row_count):
            previous = binding.location_for(shard.entry_cids[offset - 1])
            current = binding.location_for(shard.entry_cids[offset])
            previous_key = (
                -float(shard.scores[offset - 1]),
                previous.entry_cid,
                previous.chunk_cid,
            )
            current_key = (
                -float(shard.scores[offset]),
                current.entry_cid,
                current.chunk_cid,
            )
            assert current_key >= previous_key


def test_equal_cosine_ties_break_by_entry_cid() -> None:
    shared = _axis_unit(3)
    earlier = _record(
        chunk_nibble="c",
        entry_nibble="2",
        embedding=shared,
    )
    later = _record(
        chunk_nibble="a",
        entry_nibble="8",
        embedding=shared,
    )
    binding = bind_open_us_law_vectors(
        [later, earlier],
        max_rows_per_shard=4,
        max_rows_per_centroid=4,
        target_rows_per_centroid=4,
        seed=DEFAULT_VECTOR_KMEANS_SEED,
    )
    assert binding.shard_count == 1
    shard = binding.layout.shards[0]
    assert shard.row_count == 2
    first = binding.location_for(shard.entry_cids[0])
    second = binding.location_for(shard.entry_cids[1])
    assert math.isclose(first.centroid_cosine, second.centroid_cosine, abs_tol=1e-6)
    assert first.entry_cid < second.entry_cid
    assert first.entry_cid == _cid("2")
    assert second.entry_cid == _cid("8")


# ---------------------------------------------------------------------------
# Dedicated entry-to-shard locator / off-centroid frontier
# ---------------------------------------------------------------------------


def test_entry_locator_covers_every_entry() -> None:
    binding = bind_fixture_vectors()
    index = binding.entry_locator_index()
    assert index.kind == "vectors"
    for entry_cid in binding.entry_cids:
        hit = index.locate(entry_cid)
        assert hit.row.contains(entry_cid)
        assert hit.row.kind == "vectors"
        assert hit.row.metadata["locator_key"] == ENTRY_LOCATOR_KEY
        locations = binding.locate_entry(entry_cid)
        assert locations
        for location in locations:
            assert location.entry_cid == entry_cid
            shard = next(
                item
                for item in binding.layout.shards
                if item.relative_path == location.relative_path
            )
            assert shard.entry_cids[location.row_offset] == location.chunk_cid


def test_shared_entry_cid_maps_to_every_chunk_row() -> None:
    binding = bind_fixture_vectors()
    shared = _cid("8")
    locations = binding.locate_entry(shared)
    assert len(locations) == 2
    assert {loc.chunk_cid for loc in locations} == {_cid("7"), _cid("9")}
    artifacts = binding.containing_entry_artifacts([shared])
    assert artifacts
    assert {loc.relative_path for loc in locations} <= {
        item.relative_path for item in artifacts
    }


def test_direct_cid_fetch_locates_every_key() -> None:
    binding = bind_fixture_vectors()
    for key in binding.vector_keys:
        hit = binding.locate_vector(key)
        assert hit.key == key
        assert hit.kind == "vectors"
        location = binding.location_for(key)
        assert hit.relative_path == location.relative_path
        assert hit.shard_id == location.global_shard_id
        shard = next(
            item
            for item in binding.layout.shards
            if item.relative_path == hit.relative_path
        )
        assert key in shard.entry_cids


def test_entry_locator_hydrates_off_centroid_graph_frontier() -> None:
    binding = bind_fixture_vectors()
    assert binding.cluster_count >= 2 or binding.shard_count >= 2
    query = list(binding.layout.shards[0].embeddings[0])
    proof = prove_entry_locator_off_centroid_hydration(
        binding, query, candidate_centroids=1
    )
    assert proof["off_centroid_entry_count"] >= 1
    routed = set(proof["routed_paths"])
    for sample in proof["samples"]:
        assert set(sample["off_centroid_paths"]).isdisjoint(routed)
        locations = binding.locate_entry(sample["entry_cid"])
        assert any(loc.relative_path not in routed for loc in locations)
    hydrated = binding.hydrate_off_centroid_frontier(
        proof["off_centroid_entry_cids"],
        query,
        candidate_centroids=1,
    )
    assert hydrated
    assert all(loc.relative_path not in routed for loc in hydrated)


def test_direct_cid_fetch_locates_off_centroid_graph_nodes() -> None:
    binding = bind_fixture_vectors()
    query = list(binding.layout.shards[0].embeddings[0])
    proof = prove_direct_cid_off_centroid_fetch(
        binding, query, candidate_centroids=1
    )
    assert proof["off_centroid_count"] >= 1
    routed = set(proof["routed_paths"])
    for sample in proof["samples"]:
        assert sample["relative_path"] not in routed
        hit = binding.locate_vector(sample["vector_key"])
        assert hit.relative_path == sample["relative_path"]


def test_select_off_centroid_keys_disjoint_from_routes() -> None:
    binding = bind_fixture_vectors()
    query = list(binding.layout.shards[0].embeddings[0])
    routes = binding.route_centroids(query, candidate_centroids=1)
    routed_paths = {route.relative_path for route in routes}
    off = select_off_centroid_keys(binding, query, candidate_centroids=1)
    for key in off:
        assert binding.location_for(key).relative_path not in routed_paths
    off_entries = select_off_centroid_entry_cids(
        binding, query, candidate_centroids=1
    )
    for entry_cid in off_entries:
        locations = binding.locate_entry(entry_cid)
        assert any(loc.relative_path not in routed_paths for loc in locations)


def test_missing_entry_and_vector_keys_raise() -> None:
    binding = bind_fixture_vectors()
    missing = _cid("f")
    # f is used as an entry in the fixture; use a never-admitted digest.
    missing = _cid("0")
    with pytest.raises(MissingKeyError):
        binding.locate_vector(missing)
    with pytest.raises(MissingKeyError):
        binding.locate_entry(missing)


def test_containing_artifacts_is_minimal() -> None:
    binding = bind_fixture_vectors()
    keys = list(binding.vector_keys)[:3]
    artifacts = binding.containing_vector_artifacts(keys)
    needed = {binding.location_for(key).relative_path for key in keys}
    assert {item.relative_path for item in artifacts} == needed
    assert len(artifacts) <= len(keys)


def test_shard_first_last_keys_are_not_used_as_lexical_ranges() -> None:
    binding = bind_fixture_vectors()
    # Cosine order can disagree with lexical entry_cid order. The dedicated
    # locator must still resolve every parent, including those that would
    # fall outside a cosine-sorted first/last pair.
    for entry_cid in binding.entry_cids:
        locations = binding.locate_entry(entry_cid)
        assert locations
        page = binding.entry_locator_index().locate(entry_cid)
        assert page.row.contains(entry_cid)
        for location in locations:
            routing = next(
                row
                for row in binding.routing_rows
                if row["relative_path"] == location.relative_path
            )
            # Locator path is independent of the routing row's first/last keys.
            assert routing["relative_path"] == location.relative_path
    # At least one multi-parent shard must disagree with lexical min/max, or
    # the helper must report that first/last keys are not lexical ranges.
    lexical = shard_first_last_keys_are_lexical_ranges(
        binding.routing_rows, binding.locations
    )
    assert lexical is False or any(
        len({loc.entry_cid for loc in binding.locations.values() if loc.relative_path == shard.relative_path})
        <= 1
        for shard in binding.layout.shards
    )


def test_hierarchical_entry_routes_are_present() -> None:
    binding = bind_fixture_vectors()
    assert binding.entry_route_index is not None
    assert binding.entry_route_index.kind == "vectors"
    families = {item.family for item in binding.descriptors}
    assert "vectors" in families
    assert "routing_index" in families
    assert "locator_index" in families


# ---------------------------------------------------------------------------
# Roots / revisions / determinism
# ---------------------------------------------------------------------------


def test_roots_and_revisions_reconcile() -> None:
    binding = bind_fixture_vectors()
    result = reconcile_roots(
        binding,
        expected_model_id=binding.model_id,
        expected_model_revision=binding.model_revision,
        expected_config_cid=binding.config_cid,
        expected_vector_space_id=binding.vector_space_id,
        expected_corpus_root_cid=binding.corpus_root_cid,
        expected_layout_seed=binding.layout_seed,
        expected_vector_root_cid=binding.vector_root_cid,
        expected_membership_hash=binding.membership_hash,
    )
    assert result["reconciled"] is True
    assert binding.model_cid.startswith("sha256:")
    assert binding.config_cid.startswith("sha256:")
    assert binding.vector_root_cid.startswith("sha256:")
    assert binding.membership_hash.startswith("sha256:")
    assert binding.corpus_root_cid is not None
    assert build_model_cid(
        model_id=binding.model_id,
        model_revision=binding.model_revision,
        vector_space_id=binding.vector_space_id,
    ) == binding.model_cid
    assert build_layout_root_cid(binding.layout) == binding.vector_root_cid
    assert build_membership_hash(binding.layout) == binding.membership_hash


def test_reconcile_detects_model_revision_drift() -> None:
    binding = bind_fixture_vectors()
    with pytest.raises(VectorRootReconcileError):
        reconcile_roots(binding, expected_model_revision="0" * 40)


def test_reconcile_detects_config_cid_drift() -> None:
    binding = bind_fixture_vectors()
    with pytest.raises(VectorRootReconcileError):
        reconcile_roots(binding, expected_config_cid="sha256:" + ("ab" * 32))


def test_binding_is_deterministic() -> None:
    chunks = fixture_vector_chunks()
    first = bind_fixture_vectors(chunks)
    second = bind_fixture_vectors(chunks)
    assert first.vector_root_cid == second.vector_root_cid
    assert first.membership_hash == second.membership_hash
    assert first.model_cid == second.model_cid
    assert first.config_cid == second.config_cid
    assert first.layout.seed == second.layout.seed
    assert [group.cluster_id for group in first.layout.clusters] == [
        group.cluster_id for group in second.layout.clusters
    ]
    for left, right in zip(first.layout.shards, second.layout.shards):
        assert left.relative_path == right.relative_path
        assert list(left.entry_cids) == list(right.entry_cids)


def test_input_permutation_does_not_change_layout() -> None:
    chunks = fixture_vector_chunks()
    forward = bind_fixture_vectors(chunks)
    backward = bind_fixture_vectors(list(reversed(chunks)))
    assert forward.vector_root_cid == backward.vector_root_cid
    assert forward.membership_hash == backward.membership_hash
    assert sorted(forward.vector_keys) == sorted(backward.vector_keys)


def test_mixed_model_pins_fail_closed() -> None:
    chunks = fixture_vector_chunks()[:2]
    result = generate_open_us_law_embeddings(
        chunks,
        config=fixture_embedding_config(),
        device_probe=_cpu_probe,
    )
    records = [result.embeddings[cid] for cid in sorted(result.embeddings)]
    broken = records[1].to_dict()
    broken["model_revision"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    with pytest.raises(Exception):
        bind_open_us_law_vectors(
            [records[0], broken],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_parent_links_bind_chunk_to_entry() -> None:
    chunks = fixture_vector_chunks()
    binding = bind_fixture_vectors(chunks)
    assert len(binding.parent_links) == len(chunks)
    by_chunk = {row["chunk_cid"]: row["entry_cid"] for row in chunks}
    for link in binding.parent_links:
        assert isinstance(link, CorpusParentLink)
        assert link.entry_cid == by_chunk[link.chunk_cid]
        loc = binding.location_for(link.chunk_cid)
        assert loc.entry_cid == link.entry_cid
        assert loc.chunk_cid == link.chunk_cid


def test_binding_receipt_is_manifest_ready() -> None:
    binding = bind_fixture_vectors()
    receipt = binding.receipt()
    assert receipt["task_id"] == TASK_ID
    assert receipt["schema_version"] == SCHEMA_VERSION
    assert receipt["primary_key"] == PRIMARY_KEY
    assert receipt["entry_locator_key"] == ENTRY_LOCATOR_KEY
    assert receipt["rows_sorted_by"] == ROWS_SORTED_BY
    assert receipt["assignment"] == ASSIGNMENT
    assert receipt["vector_count"] == binding.vector_count
    assert receipt["membership_hash"] == binding.membership_hash
    assert isinstance(binding.descriptors, tuple)
    assert len(binding.descriptors) >= binding.shard_count + 1
    families = {item.family for item in binding.descriptors}
    assert "vectors" in families
    assert "routing_index" in families
    assert "locator_index" in families


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def test_on_disk_receipt_matches_builder_and_cannot_authorize() -> None:
    path = default_vector_receipt_path()
    assert path.is_file()
    assert path.as_posix().endswith("docs/reports/open_us_law_reindex/vector_receipt.json")
    on_disk = load_vector_receipt(path)
    built = build_vector_receipt()
    assert on_disk["task_id"] == TASK_ID
    assert on_disk["goal_id"] == GOAL_ID
    assert on_disk["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert on_disk["receipt_sha256"] == built["receipt_sha256"]
    assert on_disk == built
    assert_vector_receipt(on_disk)
    assert on_disk["authorizing_for_release"] is False
    assert on_disk["authorizing_for_publication"] is False
    assert on_disk["projection_fallback_authorizes_release"] is False
    assert on_disk["proves_software_contract_only"] is True
    assert on_disk["rows_sorted_by"] == ROWS_SORTED_BY
    assert on_disk["assignment"] == ASSIGNMENT
    assert on_disk["bounds"]["maximum_rows_per_physical_shard"] == 4096
    assert on_disk["bounds"]["maximum_rows_per_centroid"] == 8192
    assert on_disk["bounds"]["maximum_shards_per_centroid"] == 2
    pin = on_disk["model_pin"]
    assert pin["model_id"] == PINNED_MODEL_ID
    assert pin["model_revision"] == PINNED_MODEL_REVISION
    assert pin["dimension"] == 384
    assert on_disk["acceptance"]["deterministic_balanced_spherical_kmeans"] is True
    assert on_disk["acceptance"]["at_most_8192_rows_per_centroid"] is True
    assert on_disk["acceptance"]["at_most_two_shards_per_centroid"] is True
    assert on_disk["acceptance"]["every_physical_shard_at_most_4096_vectors"] is True
    assert on_disk["acceptance"]["sorted_by_centroid_cosine_desc_then_entry_cid"] is True
    assert on_disk["acceptance"]["dedicated_entry_to_shard_locator"] is True
    assert (
        on_disk["acceptance"]["entry_locator_supports_off_centroid_graph_frontier"]
        is True
    )
    assert on_disk["checks"]["demo_off_centroid_entry_count"] >= 1
    assert on_disk["demo"]["backend"] == PROJECTION_BACKEND
    assert on_disk["demo"]["authorizing_for_release"] is False
    dumped = json.dumps(on_disk)
    assert "HF_TOKEN" not in dumped
    assert "secret" not in dumped.lower()


def test_receipt_assert_rejects_authorization_and_wrong_pin() -> None:
    payload = build_vector_receipt()
    payload["authorizing_for_release"] = True
    with pytest.raises(VectorReleaseAuthorizationError):
        assert_vector_receipt(payload)
    payload = build_vector_receipt()
    payload["projection_fallback_authorizes_release"] = True
    with pytest.raises(VectorReleaseAuthorizationError):
        assert_vector_receipt(payload)
    payload = build_vector_receipt()
    payload["model_pin"] = dict(payload["model_pin"], model_id="unknown")
    with pytest.raises(VectorReceiptError):
        assert_vector_receipt(payload)


def test_write_vector_receipt_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "vector_receipt.json"
    written = write_vector_receipt(target)
    assert written == target
    loaded = load_vector_receipt(target)
    assert_vector_receipt(loaded)
    assert loaded["receipt_sha256"] == build_vector_receipt()["receipt_sha256"]
