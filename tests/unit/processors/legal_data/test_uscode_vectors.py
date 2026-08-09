"""Unit tests for US Code vector centroid + direct-CID binding (USCIR-019).

Acceptance:

* Every embedded chunk appears exactly once.
* Direct CID fetch locates off-centroid graph nodes.
* Centroid routes are bounded.
* All roots/revisions reconcile.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    default_embedding_config,
    generate_uscode_embeddings,
)
from ipfs_datasets_py.processors.legal_data.uscode_vectors import (
    DEFAULT_VECTOR_KMEANS_SEED,
    FIXTURE_SCHEMA_VERSION,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PRIMARY_KEY,
    SCHEMA_VERSION,
    TASK_ID,
    CorpusParentLink,
    UscodeVectorBinding,
    VectorBindingError,
    VectorCoverageError,
    VectorRootReconcileError,
    assert_centroid_routes_bounded,
    assert_every_chunk_once,
    bind_uscode_vectors,
    bind_uscode_vectors_from_chunks,
    binding_from_fixture,
    build_default_vector_routes_fixture_payload,
    build_layout_root_cid,
    build_model_cid,
    default_vector_routes_fixture_path,
    load_vector_routes_fixture_payload,
    prove_direct_cid_off_centroid_fetch,
    reconcile_roots,
    run_vector_route_case,
    select_off_centroid_keys,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import MissingKeyError
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    content_sha256,
    canonical_json_bytes,
)

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_vector_routes.json"
)


def _sample_chunks() -> list[dict]:
    return [
        {
            "chunk_cid": f"sha256:{'a' * 64}",
            "entry_cid": f"sha256:{'b' * 64}",
            "text": "Whoever invents or discovers any new and useful process.",
            "heading": "Inventions patentable",
            "title": "35",
            "section": "101",
            "legal_id": "usc:us:35:101",
        },
        {
            "chunk_cid": f"sha256:{'c' * 64}",
            "entry_cid": f"sha256:{'d' * 64}",
            "text": "A patent may not be obtained if the differences would have been obvious.",
            "heading": "Non-obvious subject matter",
            "title": "35",
            "section": "103",
            "legal_id": "usc:us:35:103",
        },
        {
            "chunk_cid": f"sha256:{'e' * 64}",
            "entry_cid": f"sha256:{'f' * 64}",
            "text": "Each agency shall make available to the public information.",
            "heading": "Public information",
            "title": "5",
            "section": "552",
            "legal_id": "usc:us:5:552",
        },
        {
            "chunk_cid": f"sha256:{'1' * 64}",
            "entry_cid": f"sha256:{'2' * 64}",
            "text": "This section does not apply to specifically authorized secrets.",
            "heading": "FOIA exemptions",
            "title": "5",
            "section": "552",
            "legal_id": "usc:us:5:552:b",
        },
        {
            "chunk_cid": f"sha256:{'3' * 64}",
            "entry_cid": f"sha256:{'4' * 64}",
            "text": "The specification shall contain a written description of the invention.",
            "heading": "Specification",
            "title": "35",
            "section": "112",
            "legal_id": "usc:us:35:112",
        },
        {
            "chunk_cid": f"sha256:{'5' * 64}",
            "entry_cid": f"sha256:{'6' * 64}",
            "text": "Agencies shall promulgate rules of procedure and general policy.",
            "heading": "Rule making",
            "title": "5",
            "section": "553",
            "legal_id": "usc:us:5:553",
        },
        {
            "chunk_cid": f"sha256:{'7' * 64}",
            "entry_cid": f"sha256:{'8' * 64}",
            "text": "Patent eligibility excludes laws of nature and abstract ideas.",
            "heading": "Judicial exceptions",
            "title": "35",
            "section": "101",
            "legal_id": "usc:us:35:101:note",
        },
        {
            "chunk_cid": f"sha256:{'9' * 64}",
            "entry_cid": f"sha256:{'0' * 64}",
            "text": "Freedom of information requests shall be processed promptly.",
            "heading": "Time limits",
            "title": "5",
            "section": "552",
            "legal_id": "usc:us:5:552:a6",
        },
    ]


def _tight_bounds() -> dict:
    return {
        "seed": DEFAULT_VECTOR_KMEANS_SEED,
        "max_rows_per_shard": 2,
        "max_shards_per_centroid": 2,
        "max_rows_per_centroid": 4,
        "target_rows_per_centroid": 3,
        "entry_locator_page_size": 4,
    }


def _bind_sample(
    chunks: list[dict] | None = None,
    **overrides,
) -> UscodeVectorBinding:
    params = _tight_bounds()
    params.update(overrides)
    corpus_root = "sha256:" + content_sha256(
        canonical_json_bytes({"chunks": [c["chunk_cid"] for c in (chunks or _sample_chunks())]})
    )
    return bind_uscode_vectors_from_chunks(
        chunks or _sample_chunks(),
        corpus_root_cid=corpus_root,
        **params,
    )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_vector_routes_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_vector_routes_fixture_path().name == "uscode_vector_routes.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    acceptance = payload["acceptance"]
    assert acceptance["every_embedded_chunk_appears_exactly_once"]
    assert acceptance["direct_cid_fetch_locates_off_centroid_graph_nodes"]
    assert acceptance["centroid_routes_bounded"]
    assert acceptance["roots_and_revisions_reconcile"]
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 4
    # Recipe form: no bulk per-vector golden dumps.
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "embeddings" not in case
        assert "locations" not in case


def test_default_payload_matches_on_disk_recipe_structure():
    built = build_default_vector_routes_fixture_payload(include_realized=False)
    on_disk = load_vector_routes_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["task_id"] == on_disk["task_id"]
    assert built["default_pin"]["model_id"] == on_disk["default_pin"]["model_id"]
    assert (
        built["default_pin"]["model_revision"]
        == on_disk["default_pin"]["model_revision"]
    )
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids
    assert len(built["chunks"]) == len(on_disk["chunks"])


def test_all_fixture_cases_pass():
    payload = load_vector_routes_fixture_payload(_FIXTURE_PATH)
    binding = binding_from_fixture(payload)
    for case in payload["cases"]:
        result = run_vector_route_case(case, binding=binding, payload=payload)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Coverage: every chunk exactly once
# ---------------------------------------------------------------------------


def test_every_embedded_chunk_appears_exactly_once():
    chunks = _sample_chunks()
    binding = _bind_sample(chunks)
    expected = sorted(c["chunk_cid"] for c in chunks)
    assert binding.vector_count == len(chunks)
    assert sorted(binding.vector_keys) == expected
    assert len(binding.vector_keys) == len(set(binding.vector_keys))
    assert_every_chunk_once(binding.layout, expected_chunk_cids=expected)
    # Locations map is 1:1 with layout.
    assert set(binding.locations) == set(expected)
    observed_from_shards = [
        cid for shard in binding.layout.shards for cid in shard.entry_cids
    ]
    assert sorted(observed_from_shards) == expected
    assert len(observed_from_shards) == len(set(observed_from_shards))


def test_bind_from_embedding_result_preserves_keys():
    chunks = _sample_chunks()
    result = generate_uscode_embeddings(chunks)
    binding = bind_uscode_vectors(
        result,
        **{k: v for k, v in _tight_bounds().items() if k != "entry_locator_page_size"},
        entry_locator_page_size=_tight_bounds()["entry_locator_page_size"],
    )
    assert sorted(binding.vector_keys) == sorted(result.embeddings)
    assert binding.model_id == DEFAULT_MODEL_ID
    assert binding.model_revision == DEFAULT_MODEL_REVISION


def test_duplicate_chunk_cid_fails_closed():
    chunks = _sample_chunks()[:2]
    # Force duplicate by reusing first chunk identity with different text
    # through raw records after embedding — use mapping with collision.
    result = generate_uscode_embeddings(chunks)
    records = list(result.embeddings.values())
    # Manually craft a second record with the same chunk_cid.
    dup = records[0]
    with pytest.raises(VectorCoverageError):
        bind_uscode_vectors(
            [dup, dup],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_empty_embeddings_fail_closed():
    with pytest.raises(VectorBindingError):
        bind_uscode_vectors({})


# ---------------------------------------------------------------------------
# Centroid route bounds
# ---------------------------------------------------------------------------


def test_centroid_routes_are_bounded():
    binding = _bind_sample()
    assert_centroid_routes_bounded(binding.layout)
    assert binding.layout.max_rows_per_shard <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert binding.layout.max_rows_per_centroid <= MAX_ROWS_PER_VECTOR_CENTROID
    assert binding.layout.max_shards_per_centroid <= MAX_VECTOR_SHARDS_PER_CENTROID
    for group in binding.layout.clusters:
        assert group.row_count <= binding.layout.max_rows_per_centroid
        assert group.shard_count <= binding.layout.max_shards_per_centroid
        assert 1 <= group.shard_count
        for shard in group.shards:
            assert shard.row_count <= binding.layout.max_rows_per_shard
            assert shard.row_count >= 1


def test_production_bounds_constants_match_release_policy():
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2
    assert DEFAULT_CANDIDATE_CENTROIDS == 4


def test_routing_rows_cover_every_physical_shard():
    binding = _bind_sample()
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


def test_centroid_route_probe_is_bounded():
    binding = _bind_sample()
    query = list(binding.layout.shards[0].embeddings[0])
    routes = binding.route_centroids(query, candidate_centroids=1)
    assert len(routes) >= 1
    # At most 1 centroid * 2 shards.
    assert len(routes) <= 2
    routes4 = binding.route_centroids(query, candidate_centroids=4)
    assert len(routes4) <= binding.shard_count
    assert len(routes4) <= 4 * MAX_VECTOR_SHARDS_PER_CENTROID


# ---------------------------------------------------------------------------
# Direct CID fetch / off-centroid
# ---------------------------------------------------------------------------


def test_direct_cid_fetch_locates_every_key():
    binding = _bind_sample()
    for key in binding.vector_keys:
        hit = binding.locate_vector(key)
        assert hit.key == key
        assert hit.kind == "vectors"
        location = binding.location_for(key)
        assert hit.relative_path == location.relative_path
        assert hit.shard_id == location.global_shard_id
        # Key is present in the named data shard.
        shard = next(
            s for s in binding.layout.shards if s.relative_path == hit.relative_path
        )
        assert key in shard.entry_cids


def test_direct_cid_fetch_locates_off_centroid_graph_nodes():
    binding = _bind_sample()
    # Need multi-cluster layout so some keys fall outside a 1-centroid probe.
    assert binding.cluster_count >= 2 or binding.shard_count >= 2
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


def test_select_off_centroid_keys_disjoint_from_routes():
    binding = _bind_sample()
    query = list(binding.layout.shards[0].embeddings[0])
    routes = binding.route_centroids(query, candidate_centroids=1)
    routed_paths = {r.relative_path for r in routes}
    off = select_off_centroid_keys(binding, query, candidate_centroids=1)
    for key in off:
        assert binding.location_for(key).relative_path not in routed_paths


def test_missing_vector_key_raises():
    binding = _bind_sample()
    with pytest.raises(MissingKeyError):
        binding.locate_vector(f"sha256:{'f' * 64}")


def test_containing_artifacts_is_minimal():
    binding = _bind_sample()
    keys = list(binding.vector_keys)[:3]
    artifacts = binding.containing_vector_artifacts(keys)
    # Only shards that actually contain those keys.
    needed = {
        binding.location_for(k).relative_path for k in keys
    }
    assert {a.relative_path for a in artifacts} == needed
    assert len(artifacts) <= len(keys)


def test_entry_locator_index_covers_all_keys():
    binding = _bind_sample()
    index = binding.entry_locator_index()
    assert index.kind == "vectors"
    for key in binding.vector_keys:
        hit = index.locate(key)
        assert hit.row.contains(key)
        assert hit.row.kind == "vectors"


# ---------------------------------------------------------------------------
# Roots / revisions reconcile
# ---------------------------------------------------------------------------


def test_roots_and_revisions_reconcile():
    binding = _bind_sample()
    result = reconcile_roots(
        binding,
        expected_model_id=binding.model_id,
        expected_model_revision=binding.model_revision,
        expected_config_cid=binding.config_cid,
        expected_vector_space_id=binding.vector_space_id,
        expected_corpus_root_cid=binding.corpus_root_cid,
        expected_layout_seed=binding.layout_seed,
        expected_vector_root_cid=binding.vector_root_cid,
    )
    assert result["reconciled"] is True
    # Digests are well-formed and self-consistent.
    assert binding.model_cid.startswith("sha256:")
    assert binding.config_cid.startswith("sha256:")
    assert binding.vector_root_cid.startswith("sha256:")
    assert binding.corpus_root_cid is not None
    assert binding.corpus_root_cid.startswith("sha256:")
    assert build_model_cid(
        model_id=binding.model_id,
        model_revision=binding.model_revision,
        vector_space_id=binding.vector_space_id,
    ) == binding.model_cid
    assert build_layout_root_cid(binding.layout) == binding.vector_root_cid


def test_reconcile_detects_model_revision_drift():
    binding = _bind_sample()
    with pytest.raises(VectorRootReconcileError):
        reconcile_roots(
            binding,
            expected_model_revision="0" * 40,
        )


def test_reconcile_detects_config_cid_drift():
    binding = _bind_sample()
    with pytest.raises(VectorRootReconcileError):
        reconcile_roots(
            binding,
            expected_config_cid="sha256:" + ("ab" * 32),
        )


def test_reconcile_detects_corpus_root_drift():
    binding = _bind_sample()
    with pytest.raises(VectorRootReconcileError):
        reconcile_roots(
            binding,
            expected_corpus_root_cid="sha256:" + ("cd" * 32),
        )


def test_binding_receipt_is_manifest_ready():
    binding = _bind_sample()
    receipt = binding.receipt()
    assert receipt["task_id"] == TASK_ID
    assert receipt["schema_version"] == SCHEMA_VERSION
    assert receipt["primary_key"] == PRIMARY_KEY
    assert receipt["vector_count"] == binding.vector_count
    assert receipt["model_id"] == binding.model_id
    assert receipt["model_revision"] == binding.model_revision
    assert receipt["config_cid"] == binding.config_cid
    assert receipt["model_cid"] == binding.model_cid
    assert receipt["vector_root_cid"] == binding.vector_root_cid
    assert receipt["corpus_root_cid"] == binding.corpus_root_cid
    assert isinstance(binding.descriptors, tuple)
    assert len(binding.descriptors) >= binding.shard_count + 1  # data + routing
    families = {d.family for d in binding.descriptors}
    assert "vectors" in families
    assert "routing_index" in families
    assert "locator_index" in families


# ---------------------------------------------------------------------------
# Parent links
# ---------------------------------------------------------------------------


def test_corpus_parent_links_bind_chunk_to_entry():
    chunks = _sample_chunks()
    binding = _bind_sample(chunks)
    assert len(binding.parent_links) == len(chunks)
    by_chunk = {c["chunk_cid"]: c["entry_cid"] for c in chunks}
    for link in binding.parent_links:
        assert isinstance(link, CorpusParentLink)
        assert link.entry_cid == by_chunk[link.chunk_cid]
        loc = binding.location_for(link.chunk_cid)
        assert loc.entry_cid == link.entry_cid
        assert loc.chunk_cid == link.chunk_cid


def test_locations_for_entry_cid():
    chunks = _sample_chunks()
    # Two chunks sharing one parent entry.
    shared_entry = f"sha256:{'b' * 64}"
    chunks[0]["entry_cid"] = shared_entry
    chunks[1]["entry_cid"] = shared_entry
    binding = _bind_sample(chunks)
    locs = binding.locations_for_entry_cid(shared_entry)
    assert len(locs) == 2
    assert {loc.chunk_cid for loc in locs} == {
        chunks[0]["chunk_cid"],
        chunks[1]["chunk_cid"],
    }


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_binding_is_deterministic():
    chunks = _sample_chunks()
    first = _bind_sample(chunks)
    second = _bind_sample(chunks)
    assert first.vector_root_cid == second.vector_root_cid
    assert first.model_cid == second.model_cid
    assert first.config_cid == second.config_cid
    assert first.layout.seed == second.layout.seed
    assert [g.cluster_id for g in first.layout.clusters] == [
        g.cluster_id for g in second.layout.clusters
    ]
    for a, b in zip(first.layout.shards, second.layout.shards):
        assert a.relative_path == b.relative_path
        assert list(a.entry_cids) == list(b.entry_cids)


def test_input_permutation_does_not_change_layout():
    chunks = _sample_chunks()
    forward = _bind_sample(chunks)
    reversed_chunks = list(reversed(chunks))
    backward = _bind_sample(reversed_chunks)
    assert forward.vector_root_cid == backward.vector_root_cid
    assert sorted(forward.vector_keys) == sorted(backward.vector_keys)


# ---------------------------------------------------------------------------
# Pin / identity fail-closed
# ---------------------------------------------------------------------------


def test_positional_chunk_cid_rejected():
    with pytest.raises(Exception):
        bind_uscode_vectors_from_chunks(
            [{"chunk_cid": "row-12", "text": "positional must fail"}],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_mixed_model_pins_fail_closed():
    chunks = _sample_chunks()[:2]
    result = generate_uscode_embeddings(chunks)
    records = [result.embeddings[cid] for cid in sorted(result.embeddings)]
    # Break pin on second record via mapping coercion path.
    broken = records[1].to_dict()
    broken["model_revision"] = "deadbeef" * 5  # 40 hex chars, different pin
    with pytest.raises(VectorBindingError):
        bind_uscode_vectors(
            [records[0], broken],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_config_mismatch_with_embeddings_fails():
    chunks = _sample_chunks()[:2]
    result = generate_uscode_embeddings(chunks)
    other = default_embedding_config()
    # Force a different config_cid by reconstructing with different batch
    # does not change pin — instead pass a config with different space.
    from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
        UscodeEmbeddingConfig,
    )

    mismatched = UscodeEmbeddingConfig(
        model_id=other.model_id,
        model_revision=other.model_revision,
        dimension=other.dimension,
        vector_space_id=other.vector_space_id + ":drift",
        config_cid="sha256:" + ("11" * 32),
    )
    with pytest.raises(VectorRootReconcileError):
        bind_uscode_vectors(
            result,
            config=mismatched,
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


# ---------------------------------------------------------------------------
# Schema / to_dict
# ---------------------------------------------------------------------------


def test_binding_to_dict_omits_bulk_vectors_by_default():
    binding = _bind_sample()
    payload = binding.to_dict()
    assert "locations" not in payload
    assert "vector_keys" in payload
    assert len(payload["vector_keys"]) == binding.vector_count
    assert payload["receipt"]["vector_count"] == binding.vector_count
    full = binding.to_dict(include_locations=True)
    assert len(full["locations"]) == binding.vector_count
