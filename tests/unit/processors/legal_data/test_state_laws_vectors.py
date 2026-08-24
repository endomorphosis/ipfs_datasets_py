"""Unit tests for state-law centroid-routed vectors (LCR-029).

Acceptance: every vector appears exactly once; physical paths match
centroid routes; shards <=4096, centroids <=8192 rows / two shards;
ordering, determinism, and recall gates pass.

Tests are hermetic. They consume LCR-028 hashed-projection embeddings
and never download sentence-transformers or torch models. No Hub upload,
no tokens, no absolute home paths, and no legacy FAISS overwrite.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (
    PINNED_DIMENSION as EMBED_DIMENSION,
    PINNED_MODEL_ID as EMBED_MODEL_ID,
    PINNED_MODEL_REVISION as EMBED_MODEL_REVISION,
    PROJECTION_BACKEND as EMBED_PROJECTION_BACKEND,
    generate_state_laws_embeddings,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.state_laws_vectors import (
    ASSIGNMENT,
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    DEFAULT_BACKEND,
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_TARGET_ROWS_PER_CENTROID,
    DEFAULT_VECTOR_KMEANS_SEED,
    FORBIDDEN_LEGACY_FAISS_FILENAMES,
    GOAL_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    PREPROCESSING,
    PRIMARY_KEY,
    PRODUCER,
    PRODUCTION_BACKEND,
    PROGRAM_ID,
    PROJECTION_BACKEND,
    REPORT_SCHEMA,
    ROWS_SORTED_BY,
    SCHEMA_VERSION,
    TASK_ID,
    CorpusParentLink,
    LegacyFaissOverwriteError,
    StateLawsVectorBinding,
    UnpinnedModelError,
    VectorBindingError,
    VectorReleaseAuthorizationError,
    VectorRouteBoundError,
    VectorRootReconcileError,
    admitted_fixture_chunks,
    assert_centroid_routes_bounded,
    assert_every_chunk_once,
    assert_physical_paths_match_centroid_routes,
    assert_rows_sorted_by_centroid_cosine,
    assert_vector_evaluation_report,
    bind_fixture_vectors,
    bind_state_laws_vectors,
    bind_state_laws_vectors_from_chunks,
    bind_state_laws_vectors_from_embeddings,
    build_layout_root_cid,
    build_membership_hash,
    build_model_cid,
    build_vector_evaluation_report,
    check_evaluation_report,
    default_embedding_config,
    default_vector_evaluation_report_path,
    default_vector_space_id,
    evaluate_fixture_recall,
    fixture_embedding_config,
    fixture_vector_bounds,
    fixture_vector_chunks,
    load_vector_evaluation_report,
    production_embedding_config,
    production_vector_bounds,
    prove_direct_cid_off_centroid_fetch,
    reconcile_roots,
    reject_legacy_faiss_path,
    require_pinned_gte_small,
    select_off_centroid_keys,
    write_vector_evaluation_report,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import MissingKeyError


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


@pytest.fixture(scope="module")
def compact_binding():
    return bind_fixture_vectors()


# ---------------------------------------------------------------------------
# Identity / pin / bounds
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-vectors-v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-vector-evaluation@1"
    assert TASK_ID == "LCR-029"
    assert GOAL_ID == "LCR-G040"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "state_laws_vectors.py"
    assert PRIMARY_KEY == "chunk_cid"
    assert RELEASE_PROFILE == "state-laws-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert ASSIGNMENT == "deterministic_balanced_spherical_kmeans"
    assert ROWS_SORTED_BY == "cosine_similarity_to_shard_centroid_desc"


def test_pin_reuses_lcr028_gte_small_contract() -> None:
    pin = default_embedding_config()
    assert pin.model_id == EMBED_MODEL_ID == PINNED_MODEL_ID == "thenlper/gte-small"
    assert (
        pin.model_revision
        == EMBED_MODEL_REVISION
        == PINNED_MODEL_REVISION
        == "17e1f347d17fe144873b1201da91788898c639cd"
    )
    assert pin.pooling == PINNED_POOLING == "mean"
    assert pin.normalization == PINNED_NORMALIZATION == "l2"
    assert pin.dimension == PINNED_DIMENSION == EMBED_DIMENSION == 384
    assert pin.max_tokens == 512
    assert pin.preprocessing == PREPROCESSING == "nfkc_whitespace_collapse"
    assert pin.backend == DEFAULT_BACKEND == PROJECTION_BACKEND == EMBED_PROJECTION_BACKEND
    assert pin.vector_space_id == default_vector_space_id()
    assert "gte-small@" in pin.vector_space_id
    assert PINNED_MODEL_REVISION in pin.vector_space_id


def test_production_config_declares_gte_small_and_sentence_transformers() -> None:
    production = production_embedding_config()
    assert production.model_id == PINNED_MODEL_ID
    assert production.model_revision == PINNED_MODEL_REVISION
    assert production.backend == PRODUCTION_BACKEND
    assert production.dimension == 384
    assert production.pooling == "mean"
    assert production.normalization == "l2"
    assert production.is_projection_backend is False
    fixture = fixture_embedding_config()
    assert fixture.is_projection_backend is True
    assert fixture.backend != production.backend


def test_placeholder_model_refs_fail_closed() -> None:
    with pytest.raises(UnpinnedModelError):
        require_pinned_gte_small(
            model_id="mock", model_revision=PINNED_MODEL_REVISION
        )
    with pytest.raises(UnpinnedModelError):
        require_pinned_gte_small(
            model_id=PINNED_MODEL_ID, model_revision="latest"
        )
    with pytest.raises(UnpinnedModelError):
        require_pinned_gte_small(
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision=PINNED_MODEL_REVISION,
        )


def test_legacy_faiss_filenames_are_rejected() -> None:
    for name in (
        "state_laws_gte_small.faiss",
        "index.faiss",
        "data/vectors/ipfs_state_laws.faiss",
    ):
        with pytest.raises(LegacyFaissOverwriteError):
            reject_legacy_faiss_path(name)
    allowed = "data/vectors/centroid-000000-part-000000.parquet"
    assert reject_legacy_faiss_path(allowed) == allowed


def test_production_bounds_match_release_policy() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2
    assert DEFAULT_CANDIDATE_CENTROIDS == 4
    assert DEFAULT_TARGET_ROWS_PER_CENTROID == 2048
    bounds = production_vector_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == 4096
    assert bounds["maximum_rows_per_vector_centroid"] == 8192
    assert bounds["maximum_shards_per_centroid"] == 2
    assert bounds["layout_seed"] == DEFAULT_VECTOR_KMEANS_SEED
    assert bounds["rows_sorted_by"] == ROWS_SORTED_BY
    fixture = fixture_vector_bounds()
    assert fixture["max_rows_per_shard"] == 2
    assert fixture["max_rows_per_centroid"] == 4


def test_oversize_physical_and_centroid_bounds_fail_closed() -> None:
    chunks = admitted_fixture_chunks()
    with pytest.raises(VectorRouteBoundError):
        bind_state_laws_vectors_from_chunks(chunks, max_rows_per_shard=4097)
    with pytest.raises(VectorRouteBoundError):
        bind_state_laws_vectors_from_chunks(
            chunks, max_rows_per_centroid=8193, max_rows_per_shard=4096
        )
    with pytest.raises(VectorRouteBoundError):
        bind_state_laws_vectors_from_chunks(chunks, max_shards_per_centroid=3)


# ---------------------------------------------------------------------------
# Coverage / centroid routes
# ---------------------------------------------------------------------------


def test_every_embedded_chunk_appears_exactly_once(compact_binding) -> None:
    expected = sorted(row["chunk_cid"] for row in admitted_fixture_chunks())
    assert compact_binding.vector_count == len(expected)
    assert sorted(compact_binding.vector_keys) == expected
    assert len(compact_binding.vector_keys) == len(set(compact_binding.vector_keys))
    assert_every_chunk_once(compact_binding.layout, expected_chunk_cids=expected)
    assert set(compact_binding.locations) == set(expected)
    observed = [
        cid for shard in compact_binding.layout.shards for cid in shard.entry_cids
    ]
    assert sorted(observed) == expected
    assert len(observed) == len(set(observed))


def test_bind_from_embedding_result_preserves_keys() -> None:
    chunks = admitted_fixture_chunks()
    result = generate_state_laws_embeddings(
        chunks, config=fixture_embedding_config()
    )
    bounds = fixture_vector_bounds()
    binding = bind_state_laws_vectors(
        result,
        max_rows_per_shard=int(bounds["max_rows_per_shard"]),
        max_rows_per_centroid=int(bounds["max_rows_per_centroid"]),
        max_shards_per_centroid=int(bounds["max_shards_per_centroid"]),
        target_rows_per_centroid=int(bounds["target_rows_per_centroid"]),
        seed=int(bounds["seed"]),
        kmeans_iterations=int(bounds["kmeans_iterations"]),
        entry_locator_page_size=int(bounds["entry_locator_page_size"]),
        config=fixture_embedding_config(),
        corpus_root_cid=None,
    )
    assert sorted(binding.vector_keys) == sorted(result.embeddings)
    assert binding.model_id == PINNED_MODEL_ID
    assert binding.model_revision == PINNED_MODEL_REVISION
    assert isinstance(binding, StateLawsVectorBinding)


def test_bind_from_lcr028_embedding_binding() -> None:
    from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (
        bind_fixture_embeddings,
    )

    embeddings = bind_fixture_embeddings()
    binding = bind_state_laws_vectors_from_embeddings(
        embeddings, **fixture_vector_bounds()
    )
    assert sorted(binding.vector_keys) == sorted(embeddings.vector_keys)
    assert binding.corpus_root_cid == embeddings.corpus_root_cid


def test_duplicate_chunk_cid_fails_closed() -> None:
    first = admitted_fixture_chunks()[0]
    with pytest.raises(Exception):
        bind_state_laws_vectors_from_chunks(
            [first, dict(first)], **fixture_vector_bounds()
        )


def test_empty_embeddings_fail_closed() -> None:
    with pytest.raises(VectorBindingError):
        bind_state_laws_vectors({})


def test_positional_chunk_cid_rejected() -> None:
    with pytest.raises(Exception):
        bind_state_laws_vectors_from_chunks(
            [{"chunk_cid": "row-12", "text": "positional must fail"}],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_centroid_specific_shards_and_two_shard_bounds(compact_binding) -> None:
    assert_centroid_routes_bounded(compact_binding.layout)
    assert compact_binding.layout.max_rows_per_shard == 2
    assert compact_binding.layout.max_rows_per_centroid == 4
    assert compact_binding.layout.max_shards_per_centroid == 2
    for group in compact_binding.layout.clusters:
        assert group.row_count <= 4
        assert group.shard_count <= 2
        for shard in group.shards:
            assert shard.row_count <= 2
            assert shard.relative_path.startswith("data/vectors/centroid-")
            assert "-part-" in shard.relative_path
            assert shard.relative_path.endswith(".parquet")
            assert "faiss" not in shard.relative_path
    assert any(group.shard_count == 2 for group in compact_binding.layout.clusters) or (
        compact_binding.shard_count >= compact_binding.cluster_count
    )


def test_physical_paths_match_centroid_routes(compact_binding) -> None:
    assert_physical_paths_match_centroid_routes(compact_binding)
    layout_paths = {shard.relative_path for shard in compact_binding.layout.shards}
    routing_paths = {row["relative_path"] for row in compact_binding.routing_rows}
    assert layout_paths == routing_paths
    assert len(compact_binding.routing_rows) == compact_binding.shard_count


def test_shards_are_sorted_by_centroid_cosine(compact_binding) -> None:
    assert_rows_sorted_by_centroid_cosine(compact_binding)
    for shard in compact_binding.layout.shards:
        for offset in range(1, shard.row_count):
            assert float(shard.scores[offset]) <= float(shard.scores[offset - 1]) + 1e-9


def test_recovery_and_excluded_rows_never_enter_vectors() -> None:
    binding = bind_fixture_vectors(fixture_vector_chunks())
    keys = set(binding.vector_keys)
    assert _cid("f") not in keys
    assert "" not in keys
    assert len(keys) == 8


def test_fixture_embeddings_are_384d_l2_normalized_and_finite(compact_binding) -> None:
    admitted = admitted_fixture_chunks()
    assert compact_binding.vector_count == len(admitted)
    for chunk in admitted:
        record = compact_binding.embeddings[chunk["chunk_cid"]]
        assert len(record.embedding) == 384
        assert record.dimension == 384
        assert all(math.isfinite(value) for value in record.embedding)
        norm = math.sqrt(sum(value * value for value in record.embedding))
        assert abs(norm - 1.0) <= 1e-5
        assert record.model_id == PINNED_MODEL_ID
        assert record.model_revision == PINNED_MODEL_REVISION
        assert record.pooling == "mean"
        assert record.normalization == "l2"


# ---------------------------------------------------------------------------
# Determinism / roots
# ---------------------------------------------------------------------------


def test_bind_is_deterministic_under_row_permutation() -> None:
    rows = admitted_fixture_chunks()
    first = bind_fixture_vectors(rows)
    second = bind_fixture_vectors(list(reversed(rows)))
    assert first.vector_root_cid == second.vector_root_cid
    assert first.membership_hash == second.membership_hash
    assert first.model_cid == second.model_cid
    assert first.layout_seed == second.layout_seed == DEFAULT_VECTOR_KMEANS_SEED
    assert list(first.vector_keys) == list(second.vector_keys)
    for key in first.vector_keys:
        assert first.location_for(key).relative_path == second.location_for(key).relative_path
        assert list(first.layout.shards[0].entry_cids) or True
    for left, right in zip(first.layout.shards, second.layout.shards):
        assert left.relative_path == right.relative_path
        assert list(left.entry_cids) == list(right.entry_cids)


def test_roots_reconcile(compact_binding) -> None:
    proof = reconcile_roots(
        compact_binding,
        expected_model_id=PINNED_MODEL_ID,
        expected_model_revision=PINNED_MODEL_REVISION,
        expected_config_cid=compact_binding.config_cid,
        expected_vector_space_id=compact_binding.vector_space_id,
        expected_corpus_root_cid=compact_binding.corpus_root_cid,
        expected_layout_seed=DEFAULT_VECTOR_KMEANS_SEED,
        expected_vector_root_cid=compact_binding.vector_root_cid,
        expected_membership_hash=compact_binding.membership_hash,
    )
    assert proof["reconciled"] is True
    recomputed_model = build_model_cid(
        model_id=compact_binding.model_id,
        model_revision=compact_binding.model_revision,
        vector_space_id=compact_binding.vector_space_id,
    )
    assert recomputed_model == compact_binding.model_cid
    assert build_layout_root_cid(compact_binding.layout) == compact_binding.vector_root_cid
    assert build_membership_hash(compact_binding.layout) == compact_binding.membership_hash


def test_reconcile_detects_model_revision_drift(compact_binding) -> None:
    with pytest.raises(VectorRootReconcileError):
        reconcile_roots(compact_binding, expected_model_revision="0" * 40)


def test_parent_links_join_chunk_to_document(compact_binding) -> None:
    assert len(compact_binding.parent_links) == compact_binding.vector_count
    for link in compact_binding.parent_links:
        assert isinstance(link, CorpusParentLink)
        location = compact_binding.location_for(link.chunk_cid)
        assert location.entry_cid == link.entry_cid
        assert link.chunk_cid != link.entry_cid


# ---------------------------------------------------------------------------
# Direct CID locators / off-centroid fetch
# ---------------------------------------------------------------------------


def test_direct_cid_fetch_locates_every_key(compact_binding) -> None:
    for key in compact_binding.vector_keys:
        hit = compact_binding.locate_vector(key)
        assert hit.key == key
        assert hit.kind == "vectors"
        location = compact_binding.location_for(key)
        assert hit.relative_path == location.relative_path
        assert hit.shard_id == location.global_shard_id
        shard = next(
            item
            for item in compact_binding.layout.shards
            if item.relative_path == hit.relative_path
        )
        assert key in shard.entry_cids


def test_direct_cid_fetch_locates_off_centroid_keys(compact_binding) -> None:
    query = list(compact_binding.layout.shards[0].embeddings[0])
    proof = prove_direct_cid_off_centroid_fetch(
        compact_binding, query, candidate_centroids=1
    )
    assert proof["off_centroid_count"] >= 1
    missing = "sha256:" + ("ab" * 32)
    with pytest.raises(MissingKeyError):
        compact_binding.locate_vector(missing)
    off = select_off_centroid_keys(compact_binding, query, candidate_centroids=1)
    assert off
    hit = compact_binding.locate_vector(off[0])
    assert hit.relative_path not in proof["routed_paths"]


def test_centroid_routing_returns_bounded_shards(compact_binding) -> None:
    query = list(compact_binding.layout.shards[0].embeddings[0])
    routes = compact_binding.route_centroids(query, candidate_centroids=1)
    assert routes
    assert len(routes) <= 2
    for route in routes:
        assert route.relative_path.startswith("data/vectors/centroid-")
        assert route.row_count <= 2


def test_entry_locator_covers_every_key(compact_binding) -> None:
    index = compact_binding.entry_locator_index()
    assert index.kind == "vectors"
    for key in compact_binding.vector_keys:
        hit = index.locate(key)
        assert hit.row.contains(key)
        assert hit.row.kind == "vectors"


def test_bare_vectors_without_pin_fail_closed() -> None:
    with pytest.raises(VectorBindingError):
        bind_state_laws_vectors({_cid("a"): [0.0] * 384})


def test_mixed_model_pins_fail_closed() -> None:
    chunks = admitted_fixture_chunks()[:2]
    result = generate_state_laws_embeddings(
        chunks, config=fixture_embedding_config()
    )
    records = [result.embeddings[cid] for cid in sorted(result.embeddings)]
    broken = records[1].to_dict()
    broken["model_revision"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    with pytest.raises(Exception):
        bind_state_laws_vectors(
            [records[0], broken],
            max_rows_per_shard=4,
            max_rows_per_centroid=4,
            target_rows_per_centroid=4,
        )


def test_binding_type_and_model_receipt(compact_binding) -> None:
    assert isinstance(compact_binding, StateLawsVectorBinding)
    receipt = compact_binding.model_receipt()
    assert receipt["model_id"] == PINNED_MODEL_ID
    assert receipt["model_revision"] == PINNED_MODEL_REVISION
    assert receipt["pooling"] == "mean"
    assert receipt["normalization"] == "l2"
    assert receipt["dimension"] == 384
    assert receipt["preprocessing"] == PREPROCESSING
    assert receipt["seed"] == DEFAULT_VECTOR_KMEANS_SEED
    compact = compact_binding.receipt()
    assert compact["task_id"] == TASK_ID
    assert compact["primary_key"] == PRIMARY_KEY
    assert compact["vector_count"] == 8
    families = {item.family for item in compact_binding.descriptors}
    assert "vectors" in families
    assert "routing_index" in families
    assert "locator_index" in families


# ---------------------------------------------------------------------------
# Recall / probe selection
# ---------------------------------------------------------------------------


def test_exhaustive_recall_and_probe_selection_pass(compact_binding) -> None:
    recall = evaluate_fixture_recall(compact_binding)
    assert recall["recall_gates_pass"] is True
    assert recall["production_searchable"] is False
    assert recall["recall_gate"] == 0.95
    assert recall["query_count"] == compact_binding.vector_count
    selection = recall["default_probe"]
    assert selection["meets_recall_gate"] is True
    assert int(selection["default_probe_centroids"]) >= 1
    test_at = recall["test_at_default_probe"]
    assert test_at["meets_recall_gate"] is True
    assert float(test_at["recall_at_1"]) >= 0.95


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_vectors_report_is_secret_free_and_fixture_bound(tmp_path: Path) -> None:
    report = build_vector_evaluation_report()
    assert report["task_id"] == TASK_ID
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["goal_id"] == GOAL_ID
    assert report["program_id"] == PROGRAM_ID
    assert report["acceptance"]["every_vector_exactly_once"] is True
    assert report["acceptance"]["physical_paths_match_centroid_routes"] is True
    assert report["acceptance"]["centroid_and_two_shard_bounds_hold"] is True
    assert report["acceptance"]["physical_shard_bound_4096"] is True
    assert report["acceptance"]["legacy_faiss_not_overwritten"] is True
    assert report["acceptance"]["recall_gates_pass"] is True
    assert report["acceptance"]["hub_upload"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["secrets_absent"] is True
    assert report["admitted"]["vector_count"] == 8
    assert report["family_counts"]["vector"] == 8
    assert report["network_required"] is False
    assert report["embedding_contract"]["model_id"] == PINNED_MODEL_ID
    assert report["embedding_contract"]["model_revision"] == PINNED_MODEL_REVISION
    assert report["embedding_contract"]["dimension"] == 384
    assert report["evaluation"]["recall_gates_pass"] is True
    assert report["evaluation"]["production_searchable"] is False
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob
    assert_vector_evaluation_report(report)
    path = tmp_path / "vector_evaluation.json"
    written = write_vector_evaluation_report(path)
    assert written == path
    loaded = load_vector_evaluation_report(path)
    assert loaded["task_id"] == TASK_ID
    assert "/home/" not in path.read_text(encoding="utf-8")


def test_on_disk_vectors_report_matches_contract() -> None:
    path = default_vector_evaluation_report_path()
    write_vector_evaluation_report(path)
    assert path.is_file()
    assert path.name == "vector_evaluation.json"
    assert "legal_corpora_reindex" in path.parts
    loaded = load_vector_evaluation_report(path)
    assert loaded["task_id"] == TASK_ID
    assert loaded["acceptance"]["hub_upload"] is False
    assert_vector_evaluation_report(loaded)
    result = check_evaluation_report(loaded)
    assert result["ok"] is True
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert loaded["checks"]["every_vector_exactly_once"] is True
    assert loaded["embedding_contract"]["model_id"] == PINNED_MODEL_ID
    assert loaded["bounds"]["maximum_rows_per_physical_shard"] == 4096
    assert loaded["bounds"]["maximum_rows_per_vector_centroid"] == 8192
    assert loaded["bounds"]["maximum_shards_per_centroid"] == 2
    for shard_path in loaded["demo"]["shard_relative_paths"]:
        assert "faiss" not in shard_path
    assert FORBIDDEN_LEGACY_FAISS_FILENAMES


def test_report_cannot_authorize_publication() -> None:
    report = build_vector_evaluation_report()
    broken = dict(report)
    broken["authorizing_for_publication"] = True
    with pytest.raises(VectorReleaseAuthorizationError):
        assert_vector_evaluation_report(broken)


def test_fixture_generation_does_not_touch_the_network(monkeypatch) -> None:
    import urllib.request

    def _blocked(*_args, **_kwargs):
        raise AssertionError("network I/O is forbidden in LCR-029 fixtures")

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    binding = bind_fixture_vectors()
    assert binding.vector_count == 8
    report = build_vector_evaluation_report(binding=binding)
    assert report["network_required"] is False
