"""Unit tests for deterministic centroid-routed vector shards (USCIR-018).

Acceptance:

* Row conservation and uniqueness hold.
* Each centroid has at most 8,192 rows and two shards.
* Each shard has at most 4,096 rows.
* Ordering (cosine desc + entry_cid) and deterministic seed behavior are proven.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PhysicalBoundError,
    canonical_json_dumps,
    content_sha256,
)
from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
    ASSIGNMENT,
    DEFAULT_VECTOR_KMEANS_SEED,
    ROWS_SORTED_BY,
    TASK_ID,
    VECTOR_FIXTURE_SCHEMA_VERSION,
    VectorCoverageError,
    VectorInputError,
    VectorOrderingError,
    VectorRecord,
    VectorRoutingError,
    build_centroid_routed_vector_layout,
    build_fixture_vector_rows,
    build_vector_clusters_fixture_payload,
    centroid_part_filename,
    coerce_vector_records,
    default_vector_clusters_fixture_path,
    layout_from_fixture,
    load_vector_clusters_fixture,
    normalize_unit_matrix,
    route_vector_shards,
    validate_vector_layout,
    vector_bounds_policy,
    vector_shard_relative_path,
    write_centroid_routed_vectors,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "hf_graphrag"
    / "vector_clusters.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rows_from_angles(
    angles_deg: list[float],
    *,
    prefix: str = "entry",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, angle in enumerate(angles_deg):
        radians = math.radians(angle)
        rows.append(
            {
                "document_index": index,
                "embedding": [math.cos(radians), math.sin(radians)],
                "entry_cid": f"{prefix}-{index:04d}",
            }
        )
    return rows


def _semantic_lobes(*, per_lobe: int = 4) -> list[dict[str, object]]:
    # Two well-separated lobes around 0° and 180°.
    positive = [float(index) for index in range(per_lobe)]
    negative = [180.0 + float(index) for index in range(per_lobe)]
    rows = _rows_from_angles(positive, prefix="pos")
    rows.extend(_rows_from_angles(negative, prefix="neg"))
    return rows


# ---------------------------------------------------------------------------
# Constants / bounds
# ---------------------------------------------------------------------------


def test_vector_bounds_match_release_policy():
    bounds = vector_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_rows_per_vector_centroid"] == 8192
    assert bounds["max_vector_shards_per_centroid"] == 2
    assert bounds["default_candidate_centroids"] == 4
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2
    assert DEFAULT_CANDIDATE_CENTROIDS == 4
    assert ASSIGNMENT == "deterministic_balanced_spherical_kmeans"
    assert ROWS_SORTED_BY == "cosine_similarity_to_shard_centroid_desc"


def test_centroid_part_filename_contract():
    assert (
        centroid_part_filename(0, 1)
        == "centroid-000000-part-000001.parquet"
    )
    assert vector_shard_relative_path(2, 0) == (
        "data/vectors/centroid-000002-part-000000.parquet"
    )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_rejects_empty_duplicate_and_zero_embeddings():
    with pytest.raises(VectorInputError):
        build_centroid_routed_vector_layout([])

    with pytest.raises(VectorCoverageError, match="duplicate entry_cid"):
        build_centroid_routed_vector_layout(
            [
                {"entry_cid": "same", "embedding": [1.0, 0.0]},
                {"entry_cid": "same", "embedding": [0.0, 1.0]},
            ]
        )

    with pytest.raises(VectorInputError, match="non-zero"):
        build_centroid_routed_vector_layout(
            [{"entry_cid": "z", "embedding": [0.0, 0.0]}]
        )

    with pytest.raises(VectorInputError, match="dimension mismatch"):
        build_centroid_routed_vector_layout(
            [
                {"entry_cid": "a", "embedding": [1.0, 0.0]},
                {"entry_cid": "b", "embedding": [1.0, 0.0, 0.0]},
            ]
        )


def test_rejects_bounds_above_sealed_maximums():
    rows = _semantic_lobes(per_lobe=2)
    with pytest.raises(PhysicalBoundError):
        build_centroid_routed_vector_layout(
            rows,
            max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD + 1,
        )
    with pytest.raises(PhysicalBoundError):
        build_centroid_routed_vector_layout(
            rows,
            max_shards_per_centroid=MAX_VECTOR_SHARDS_PER_CENTROID + 1,
        )
    with pytest.raises(PhysicalBoundError):
        build_centroid_routed_vector_layout(
            rows,
            max_rows_per_centroid=MAX_ROWS_PER_VECTOR_CENTROID + 1,
            max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD,
            max_shards_per_centroid=MAX_VECTOR_SHARDS_PER_CENTROID,
        )


def test_coerce_and_normalize_unit_matrix():
    records = coerce_vector_records(
        [
            {"entry_cid": "b", "embedding": [3.0, 4.0], "document_index": 1},
            VectorRecord(entry_cid="a", embedding=(0.0, 2.0), document_index=0),
        ]
    )
    assert [item.entry_cid for item in records] == ["b", "a"]
    matrix = normalize_unit_matrix(
        (
            VectorRecord(entry_cid="a", embedding=(0.0, 2.0)),
            VectorRecord(entry_cid="b", embedding=(3.0, 4.0)),
        )
    )
    assert matrix.shape == (2, 2)
    assert math.isclose(float(matrix[0] @ matrix[0]), 1.0, abs_tol=1e-6)
    assert math.isclose(float(matrix[1] @ matrix[1]), 1.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# Conservation / uniqueness / bounds
# ---------------------------------------------------------------------------


def test_row_conservation_and_uniqueness():
    rows = _semantic_lobes(per_lobe=5)
    layout = build_centroid_routed_vector_layout(
        rows,
        max_rows_per_shard=2,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=3,
        seed=DEFAULT_VECTOR_KMEANS_SEED,
    )
    observed = layout.all_entry_cids()
    expected = sorted(row["entry_cid"] for row in rows)
    assert layout.total_rows == len(rows)
    assert len(observed) == len(rows)
    assert len(set(observed)) == len(rows)
    assert sorted(observed) == expected
    validate_vector_layout(layout, expected_entry_cids=expected)


def test_centroid_and_shard_bounds_hold():
    # 12 vectors with max_rows_per_centroid=4 and max_rows_per_shard=2
    # forces multi-centroid multi-shard layout.
    rows = _rows_from_angles(
        [float(index * 30) for index in range(12)],
        prefix="v",
    )
    layout = build_centroid_routed_vector_layout(
        rows,
        max_rows_per_shard=2,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=3,
    )
    assert layout.max_rows_per_shard == 2
    assert layout.max_rows_per_centroid == 4
    assert layout.max_shards_per_centroid == 2
    for group in layout.clusters:
        assert group.row_count <= 4
        assert group.shard_count <= 2
        assert group.shard_count >= 1
        for shard in group.shards:
            assert shard.row_count <= 2
            assert shard.row_count >= 1
    # Production defaults are the sealed 4096 / 8192 / 2 constants.
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2


def test_default_bounds_capacity_formula():
    # max_rows_per_centroid defaults to shard_rows * shards_per_centroid.
    rows = _semantic_lobes(per_lobe=3)
    layout = build_centroid_routed_vector_layout(
        rows,
        max_rows_per_shard=3,
        max_shards_per_centroid=2,
        target_rows_per_centroid=3,
    )
    assert layout.max_rows_per_centroid == 6
    for group in layout.clusters:
        assert group.row_count <= 6
        assert group.shard_count <= 2


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_shard_rows_sorted_by_cosine_desc_with_entry_cid_tiebreak():
    # Identical direction so scores tie; entry_cid must order them.
    rows = [
        {"entry_cid": "entry-z", "embedding": [1.0, 0.0]},
        {"entry_cid": "entry-a", "embedding": [1.0, 0.0]},
        {"entry_cid": "entry-m", "embedding": [1.0, 0.0]},
    ]
    layout = build_centroid_routed_vector_layout(
        rows,
        max_rows_per_shard=4,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=4,
    )
    assert layout.shard_count == 1
    shard = layout.shards[0]
    assert list(shard.entry_cids) == ["entry-a", "entry-m", "entry-z"]
    assert shard.scores[0] >= shard.scores[1] >= shard.scores[2]

    # Mixed angles: scores must be non-increasing.
    mixed = _rows_from_angles([0.0, 10.0, 40.0, 80.0], prefix="mix")
    layout2 = build_centroid_routed_vector_layout(
        mixed,
        max_rows_per_shard=4,
        max_shards_per_centroid=1,
        max_rows_per_centroid=4,
        target_rows_per_centroid=4,
    )
    for shard in layout2.shards:
        for offset in range(1, shard.row_count):
            assert shard.scores[offset - 1] >= shard.scores[offset] - 1e-7


def test_validate_detects_ordering_break():
    # Force a single multi-row shard so reversing order is observable.
    rows = [
        {"entry_cid": "entry-a", "embedding": [1.0, 0.0]},
        {"entry_cid": "entry-b", "embedding": [0.9, 0.1]},
        {"entry_cid": "entry-c", "embedding": [0.7, 0.3]},
    ]
    layout = build_centroid_routed_vector_layout(
        rows,
        max_rows_per_shard=4,
        max_shards_per_centroid=1,
        max_rows_per_centroid=4,
        target_rows_per_centroid=4,
    )
    assert layout.shard_count == 1
    assert layout.shards[0].row_count == 3
    broken_shard = layout.shards[0]
    from ipfs_datasets_py.retrieval.hf_graphrag.vectors import (
        VectorClusterGroup,
        VectorClusterLayout,
        VectorShardSpec,
    )

    reversed_shard = VectorShardSpec(
        cluster_id=broken_shard.cluster_id,
        chunk_in_cluster=broken_shard.chunk_in_cluster,
        global_shard_id=broken_shard.global_shard_id,
        entry_cids=tuple(reversed(broken_shard.entry_cids)),
        document_indexes=tuple(reversed(broken_shard.document_indexes)),
        embeddings=tuple(reversed(broken_shard.embeddings)),
        scores=tuple(reversed(broken_shard.scores)),
        routing_centroid=broken_shard.routing_centroid,
        shard_centroid=broken_shard.shard_centroid,
        min_score=broken_shard.min_score,
        max_score=broken_shard.max_score,
        relative_path=broken_shard.relative_path,
        dimension=broken_shard.dimension,
    )
    group = VectorClusterGroup(
        cluster_id=0,
        entry_cids=reversed_shard.entry_cids,
        routing_centroid=reversed_shard.routing_centroid,
        shards=(reversed_shard,),
    )
    broken = VectorClusterLayout(
        clusters=(group,),
        dimension=layout.dimension,
        total_rows=reversed_shard.row_count,
        seed=layout.seed,
        max_rows_per_shard=layout.max_rows_per_shard,
        max_rows_per_centroid=layout.max_rows_per_centroid,
        max_shards_per_centroid=layout.max_shards_per_centroid,
        target_rows_per_centroid=layout.target_rows_per_centroid,
        kmeans_iterations=layout.kmeans_iterations,
    )
    with pytest.raises(VectorOrderingError):
        validate_vector_layout(broken)


# ---------------------------------------------------------------------------
# Determinism / seed
# ---------------------------------------------------------------------------


def test_layout_is_deterministic_for_same_seed_regardless_of_input_order():
    rows = _semantic_lobes(per_lobe=4)
    kwargs = {
        "max_rows_per_shard": 2,
        "max_shards_per_centroid": 2,
        "max_rows_per_centroid": 4,
        "target_rows_per_centroid": 3,
        "seed": 42,
    }
    first = build_centroid_routed_vector_layout(rows, **kwargs)
    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    second = build_centroid_routed_vector_layout(shuffled, **kwargs)

    assert first.to_dict() == second.to_dict()
    assert first.manifest_config() == second.manifest_config()
    assert first.all_entry_cids() == second.all_entry_cids()
    for left, right in zip(first.shards, second.shards):
        assert left.entry_cids == right.entry_cids
        assert left.relative_path == right.relative_path
        assert left.scores == pytest.approx(right.scores, abs=1e-6)


def test_same_seed_reproducible_across_calls():
    rows = _semantic_lobes(per_lobe=3)
    kwargs = {
        "max_rows_per_shard": 2,
        "max_shards_per_centroid": 2,
        "max_rows_per_centroid": 4,
        "target_rows_per_centroid": 2,
        "seed": DEFAULT_VECTOR_KMEANS_SEED,
    }
    layouts = [
        build_centroid_routed_vector_layout(rows, **kwargs) for _ in range(3)
    ]
    digests = [
        content_sha256(canonical_json_dumps(layout.to_dict()))
        for layout in layouts
    ]
    assert digests[0] == digests[1] == digests[2]
    assert layouts[0].seed == DEFAULT_VECTOR_KMEANS_SEED


def test_seed_is_recorded_and_layout_digest_stable():
    rows = _semantic_lobes(per_lobe=3)
    layout = build_centroid_routed_vector_layout(
        rows,
        seed=12345,
        max_rows_per_shard=2,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=2,
    )
    assert layout.seed == 12345
    assert layout.manifest_config()["seed"] == 12345
    again = build_centroid_routed_vector_layout(
        list(reversed(rows)),
        seed=12345,
        max_rows_per_shard=2,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=2,
    )
    assert content_sha256(canonical_json_dumps(layout.to_dict())) == (
        content_sha256(canonical_json_dumps(again.to_dict()))
    )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_route_vector_shards_ranks_nearest_centroid():
    rows = _semantic_lobes(per_lobe=3)
    layout = build_centroid_routed_vector_layout(
        rows,
        max_rows_per_shard=2,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=3,
    )
    routing = layout.routing_rows()
    routes = route_vector_shards(
        routing,
        (1.0, 0.0),
        candidate_centroids=1,
    )
    assert routes
    assert all(route.score == routes[0].score for route in routes)
    # All routes for the selected centroid share cluster_id.
    assert len({route.cluster_id for route in routes}) == 1
    # Positive query should prefer the positive lobe if multiple clusters.
    selected_entries = {
        entry_cid
        for group in layout.clusters
        if group.cluster_id == routes[0].cluster_id
        for entry_cid in group.entry_cids
    }
    assert any(entry_cid.startswith("pos-") for entry_cid in selected_entries)

    with pytest.raises(VectorRoutingError):
        route_vector_shards(routing, (1.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Fixture contract
# ---------------------------------------------------------------------------


def test_sealed_fixture_exists_and_matches_rebuild():
    assert FIXTURE_PATH.is_file()
    assert default_vector_clusters_fixture_path() == FIXTURE_PATH
    payload = load_vector_clusters_fixture(FIXTURE_PATH)
    assert payload["schema_version"] == VECTOR_FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["assignment"] == ASSIGNMENT
    assert payload["bounds"]["max_rows_per_physical_shard"] == 4096
    assert payload["bounds"]["max_rows_per_vector_centroid"] == 8192
    assert payload["bounds"]["max_vector_shards_per_centroid"] == 2
    assert payload["bounds"]["default_candidate_centroids"] == 4

    expected = payload["expected"]
    assert expected["seed"] == DEFAULT_VECTOR_KMEANS_SEED
    assert DEFAULT_VECTOR_KMEANS_SEED == 0x55534349
    assert expected["total_rows"] == 8
    assert expected["max_rows_per_shard"] == 2
    assert expected["max_rows_per_centroid"] == 4
    assert expected["max_shards_per_centroid"] == 2
    assert expected["rows_sorted_by"] == ROWS_SORTED_BY

    layout = layout_from_fixture(payload)
    assert layout.total_rows == expected["total_rows"]
    assert layout.seed == expected["seed"]
    assert sorted(layout.all_entry_cids()) == expected["unique_entry_cids"]
    assert len(set(layout.all_entry_cids())) == layout.total_rows

    # Fixture bounds are enforced on the realized layout.
    for group in layout.clusters:
        assert group.row_count <= expected["max_rows_per_centroid"]
        assert group.shard_count <= expected["max_shards_per_centroid"]
        for shard in group.shards:
            assert shard.row_count <= expected["max_rows_per_shard"]
            assert list(shard.scores) == sorted(shard.scores, reverse=True)

    # Recipe rebuild is byte-stable across calls (seed determinism).
    again = layout_from_fixture(payload)
    assert layout.to_dict() == again.to_dict()
    digest = content_sha256(canonical_json_dumps(layout.to_dict()))
    assert digest == content_sha256(canonical_json_dumps(again.to_dict()))

    # Generator payload agrees with the on-disk recipe / sealed bounds.
    generated = build_vector_clusters_fixture_payload(
        seed=expected["seed"],
        include_realized_layout=False,
    )
    assert generated["recipe"] == payload["recipe"]
    assert generated["test_bounds"] == payload["test_bounds"]
    assert generated["bounds"] == payload["bounds"]
    assert generated["expected"]["unique_entry_cids"] == expected["unique_entry_cids"]

    # Realized generator path is also deterministic.
    realized_a = build_vector_clusters_fixture_payload(
        seed=expected["seed"],
        include_realized_layout=True,
    )
    realized_b = build_vector_clusters_fixture_payload(
        seed=expected["seed"],
        include_realized_layout=True,
    )
    assert realized_a["expected"]["layout_digest"] == (
        realized_b["expected"]["layout_digest"]
    )
    assert realized_a["expected"]["cluster_summary"] == (
        realized_b["expected"]["cluster_summary"]
    )
    assert realized_a["expected"]["total_rows"] == expected["total_rows"]
    assert realized_a["expected"]["cluster_count"] >= 1
    assert realized_a["expected"]["shard_count"] >= 1


def test_fixture_recipe_builder():
    recipe = {
        "dimension": 2,
        "rows": [
            {"entry_cid": "x", "direction": 0.0},
            {"entry_cid": "y", "axis": 1, "sign": -1.0},
        ],
    }
    rows = build_fixture_vector_rows(recipe)
    assert rows[0]["entry_cid"] == "x"
    assert math.isclose(rows[0]["embedding"][0], 1.0, abs_tol=1e-9)
    assert rows[1]["embedding"] == [0.0, -1.0]


# ---------------------------------------------------------------------------
# Optional on-disk write (pyarrow)
# ---------------------------------------------------------------------------


def test_write_centroid_routed_vectors_round_trip(tmp_path: Path):
    pytest.importorskip("pyarrow")
    rows = _semantic_lobes(per_lobe=3)
    result = write_centroid_routed_vectors(
        rows,
        tmp_path,
        max_rows_per_shard=2,
        max_shards_per_centroid=2,
        max_rows_per_centroid=4,
        target_rows_per_centroid=3,
        seed=7,
    )
    assert result.layout.total_rows == len(rows)
    assert len(result.data_descriptors) == result.layout.shard_count
    assert result.routing_index_descriptor is not None
    for descriptor in result.data_descriptors:
        path = tmp_path / descriptor.relative_path
        assert path.is_file()
        assert path.stat().st_size == descriptor.size_bytes
    index_path = tmp_path / "indexes" / "vector_chunks.parquet"
    assert index_path.is_file()

    # Routing rows from the write result still support thin-client ranking.
    routes = route_vector_shards(
        result.routing_rows,
        (1.0, 0.0),
        candidate_centroids=1,
    )
    assert routes
    for route in routes:
        assert (tmp_path / route.relative_path).is_file()
