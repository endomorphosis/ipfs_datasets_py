"""Unit tests for pinned Federal Register embeddings and centroid routes (LCR-057).

Acceptance: exactly one valid 384-d normalized vector per searchable chunk;
no missing/extra/NaN; centroid and two-shard bounds hold physically and
logically.

Tests are hermetic. They use the sealed local hashed projection and never
download sentence-transformers or torch models. No Hub upload, no tokens,
no absolute home paths, and no legacy FAISS overwrite.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
    materialize_federal_register_corpus,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
    ASSIGNMENT,
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    DEFAULT_BACKEND,
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
    SCHEMA_VERSION,
    TASK_ID,
    EmbeddingConfigError,
    FederalRegisterEmbeddingConfig,
    FederalRegisterVectorBinding,
    LegacyFaissOverwriteError,
    UnpinnedModelError,
    VectorBindingError,
    VectorCoverageError,
    VectorRouteBoundError,
    admitted_fixture_chunks,
    assert_centroid_routes_bounded,
    assert_embedding_conservation,
    assert_every_chunk_once,
    assert_federal_vectors_report,
    bind_federal_register_vectors,
    bind_federal_register_vectors_from_chunks,
    bind_federal_register_vectors_from_corpus,
    bind_fixture_vectors,
    build_corpus_root_cid,
    build_federal_vectors_report,
    build_layout_root_cid,
    build_model_cid,
    chunks_from_materialized_corpus,
    default_embedding_config,
    default_vector_space_id,
    default_vectors_report_path,
    fixture_embedding_config,
    fixture_vector_bounds,
    fixture_vector_chunks,
    generate_federal_register_embeddings,
    load_federal_vectors_report,
    production_embedding_config,
    production_vector_bounds,
    prove_direct_cid_off_centroid_fetch,
    reconcile_roots,
    reject_legacy_faiss_path,
    require_pinned_gte_small,
    select_off_centroid_keys,
    write_federal_vectors_report,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_MODEL_ID as USCODE_MODEL_ID,
    DEFAULT_MODEL_REVISION as USCODE_MODEL_REVISION,
    DEFAULT_NORMALIZATION as USCODE_NORMALIZATION,
    DEFAULT_POOLING as USCODE_POOLING,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import MissingKeyError


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


@pytest.fixture(scope="module")
def corpus():
    return materialize_federal_register_corpus()


@pytest.fixture(scope="module")
def compact_binding():
    return bind_fixture_vectors()


# ---------------------------------------------------------------------------
# Identity / pin
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-vectors-v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-federal-vectors@1"
    assert TASK_ID == "LCR-057"
    assert GOAL_ID == "LCR-G120"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "federal_register_vectors.py"
    assert PRIMARY_KEY == "chunk_cid"
    assert RELEASE_PROFILE == "federal-register-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert ASSIGNMENT == "deterministic_balanced_spherical_kmeans"


def test_pin_reuses_uscode_gte_small_contract() -> None:
    pin = default_embedding_config()
    assert pin.model_id == USCODE_MODEL_ID == PINNED_MODEL_ID == "thenlper/gte-small"
    assert (
        pin.model_revision
        == USCODE_MODEL_REVISION
        == PINNED_MODEL_REVISION
        == "17e1f347d17fe144873b1201da91788898c639cd"
    )
    assert pin.pooling == USCODE_POOLING == PINNED_POOLING == "mean"
    assert pin.normalization == USCODE_NORMALIZATION == PINNED_NORMALIZATION == "l2"
    assert pin.dimension == PINNED_DIMENSION == 384
    assert pin.max_tokens == 512
    assert pin.preprocessing == PREPROCESSING == "nfkc_whitespace_collapse"
    assert pin.backend == DEFAULT_BACKEND == PROJECTION_BACKEND
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
        FederalRegisterEmbeddingConfig(
            model_id="mock", model_revision=PINNED_MODEL_REVISION
        )
    with pytest.raises(UnpinnedModelError):
        FederalRegisterEmbeddingConfig(
            model_id="unknown", model_revision=PINNED_MODEL_REVISION
        )
    with pytest.raises(UnpinnedModelError):
        FederalRegisterEmbeddingConfig(
            model_id=PINNED_MODEL_ID, model_revision="latest"
        )
    with pytest.raises(UnpinnedModelError):
        FederalRegisterEmbeddingConfig(
            model_id=PINNED_MODEL_ID, model_revision="placeholder"
        )
    with pytest.raises(UnpinnedModelError):
        require_pinned_gte_small(
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision=PINNED_MODEL_REVISION,
        )


def test_wrong_pooling_normalization_or_dimension_fail_closed() -> None:
    with pytest.raises(EmbeddingConfigError):
        FederalRegisterEmbeddingConfig(pooling="cls")
    with pytest.raises(EmbeddingConfigError):
        FederalRegisterEmbeddingConfig(normalization="none")
    with pytest.raises(EmbeddingConfigError):
        FederalRegisterEmbeddingConfig(dimension=768)
    with pytest.raises(EmbeddingConfigError):
        FederalRegisterEmbeddingConfig(max_tokens=1024)


def test_legacy_faiss_filenames_are_rejected() -> None:
    for name in (
        "federal_register_gte_small.faiss",
        "index.faiss",
        "data/vectors/federal_register_gte_small.faiss",
    ):
        with pytest.raises(LegacyFaissOverwriteError):
            reject_legacy_faiss_path(name)
    allowed = "data/vectors/centroid-000000-part-000000.parquet"
    assert reject_legacy_faiss_path(allowed) == allowed


def test_production_bounds_match_release_policy() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2
    bounds = production_vector_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == 4096
    assert bounds["maximum_rows_per_vector_centroid"] == 8192
    assert bounds["maximum_shards_per_centroid"] == 2
    assert bounds["layout_seed"] == DEFAULT_VECTOR_KMEANS_SEED
    fixture = fixture_vector_bounds()
    assert fixture["max_rows_per_shard"] == 2
    assert fixture["max_rows_per_centroid"] == 4


def test_oversize_physical_and_centroid_bounds_fail_closed() -> None:
    chunks = admitted_fixture_chunks()
    with pytest.raises(VectorRouteBoundError):
        bind_federal_register_vectors_from_chunks(chunks, max_rows_per_shard=4097)
    with pytest.raises(VectorRouteBoundError):
        bind_federal_register_vectors_from_chunks(
            chunks, max_rows_per_centroid=8193, max_rows_per_shard=4096
        )
    with pytest.raises(VectorRouteBoundError):
        bind_federal_register_vectors_from_chunks(chunks, max_shards_per_centroid=3)


# ---------------------------------------------------------------------------
# Hermetic embedding generation
# ---------------------------------------------------------------------------


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


def test_generate_is_deterministic_and_uses_projection_backend() -> None:
    chunks = admitted_fixture_chunks()
    first = generate_federal_register_embeddings(chunks)
    second = generate_federal_register_embeddings(list(reversed(chunks)))
    assert first.config.backend == PROJECTION_BACKEND
    keys = sorted(first.embeddings)
    assert keys == sorted(second.embeddings)
    for key in keys:
        assert first.embeddings[key].embedding == second.embeddings[key].embedding
        assert first.embeddings[key].input_hash == second.embeddings[key].input_hash


def test_recovery_and_excluded_rows_never_enter_embeddings() -> None:
    result = generate_federal_register_embeddings(fixture_vector_chunks())
    keys = set(result.embeddings)
    assert _cid("f") not in keys
    assert "" not in keys
    assert len(keys) == 8
    assert_embedding_conservation(result, expected_chunk_cids=sorted(keys))


def test_duplicate_chunk_cid_fails_closed() -> None:
    first = admitted_fixture_chunks()[0]
    with pytest.raises(Exception):
        generate_federal_register_embeddings([first, dict(first)])


def test_positional_identity_is_rejected() -> None:
    with pytest.raises(Exception):
        generate_federal_register_embeddings(
            [
                {
                    "chunk_cid": "row-12",
                    "entry_cid": "row-12",
                    "text": "positional identity must fail",
                }
            ]
        )


def test_empty_corpus_fails_closed() -> None:
    with pytest.raises(VectorCoverageError):
        generate_federal_register_embeddings([])


def test_input_receipts_bind_model_and_text_hash(compact_binding) -> None:
    assert len(compact_binding.input_receipts) == compact_binding.vector_count
    for receipt in compact_binding.input_receipts:
        assert receipt.model_id == PINNED_MODEL_ID
        assert receipt.model_revision == PINNED_MODEL_REVISION
        assert receipt.pooling == PINNED_POOLING
        assert receipt.normalization == PINNED_NORMALIZATION
        assert receipt.dimension == 384
        assert receipt.preprocessing == PREPROCESSING
        assert len(receipt.input_hash) == 64
        record = compact_binding.embeddings[receipt.chunk_cid]
        assert record.input_hash == receipt.input_hash


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


def test_bind_is_deterministic_under_row_permutation() -> None:
    rows = admitted_fixture_chunks()
    first = bind_fixture_vectors(rows)
    second = bind_fixture_vectors(list(reversed(rows)))
    assert first.vector_root_cid == second.vector_root_cid
    assert first.model_cid == second.model_cid
    assert first.layout_seed == second.layout_seed == DEFAULT_VECTOR_KMEANS_SEED
    assert list(first.vector_keys) == list(second.vector_keys)
    for key in first.vector_keys:
        assert first.location_for(key).relative_path == second.location_for(key).relative_path


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
    )
    assert proof["reconciled"] is True
    recomputed_model = build_model_cid(
        model_id=compact_binding.model_id,
        model_revision=compact_binding.model_revision,
        vector_space_id=compact_binding.vector_space_id,
    )
    assert recomputed_model == compact_binding.model_cid
    assert build_layout_root_cid(compact_binding.layout) == compact_binding.vector_root_cid


def test_parent_links_join_chunk_to_document(compact_binding) -> None:
    assert len(compact_binding.parent_links) == compact_binding.vector_count
    for link in compact_binding.parent_links:
        location = compact_binding.location_for(link.chunk_cid)
        assert location.entry_cid == link.entry_cid
        assert link.chunk_cid != link.entry_cid


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


def test_bare_vectors_without_pin_fail_closed() -> None:
    with pytest.raises(VectorBindingError):
        bind_federal_register_vectors(
            {_cid("a"): [0.0] * 384},
        )


# ---------------------------------------------------------------------------
# LCR-055 admitted corpus coverage
# ---------------------------------------------------------------------------


def test_documents_equal_admitted_searchable_chunks(corpus) -> None:
    binding = bind_federal_register_vectors_from_corpus(
        corpus,
        config=fixture_embedding_config(),
        **fixture_vector_bounds(),
    )
    expected = [chunk.chunk_cid for chunk in corpus.chunks]
    assert binding.vector_count == len(corpus.chunks)
    assert sorted(binding.vector_keys) == sorted(expected)
    assert_every_chunk_once(binding.layout, expected_chunk_cids=expected)
    assert_centroid_routes_bounded(binding.layout)
    rows = chunks_from_materialized_corpus(corpus)
    assert {row["chunk_cid"] for row in rows} == set(expected)
    for record in binding.embeddings.values():
        assert len(record.embedding) == 384
        assert all(math.isfinite(value) for value in record.embedding)
        norm = math.sqrt(sum(value * value for value in record.embedding))
        assert abs(norm - 1.0) <= 1e-5
    assert binding.layout.max_rows_per_centroid <= MAX_ROWS_PER_VECTOR_CENTROID
    assert binding.layout.max_shards_per_centroid <= MAX_VECTOR_SHARDS_PER_CENTROID
    for group in binding.layout.clusters:
        assert group.row_count <= 4
        assert group.shard_count <= 2
        for shard in group.shards:
            assert shard.row_count <= 2
            assert "faiss" not in shard.relative_path


def test_corpus_root_reconciles_with_admitted_chunks(corpus) -> None:
    rows = chunks_from_materialized_corpus(corpus)
    root = build_corpus_root_cid(corpus)
    binding = bind_federal_register_vectors_from_chunks(
        rows,
        corpus_root_cid=root,
        **fixture_vector_bounds(),
    )
    proof = reconcile_roots(binding, expected_corpus_root_cid=root)
    assert proof["reconciled"] is True
    assert binding.vector_count == len(rows)


def test_binding_type_and_model_receipt(compact_binding) -> None:
    assert isinstance(compact_binding, FederalRegisterVectorBinding)
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


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_vectors_report_is_secret_free_and_fixture_bound(corpus, tmp_path: Path) -> None:
    report = build_federal_vectors_report(corpus=corpus)
    assert report["task_id"] == TASK_ID
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["acceptance"]["exactly_one_vector_per_searchable_chunk"] is True
    assert report["acceptance"]["no_missing_extra_or_nan"] is True
    assert report["acceptance"]["centroid_and_two_shard_bounds_hold"] is True
    assert report["acceptance"]["physical_shard_bound_4096"] is True
    assert report["acceptance"]["legacy_faiss_not_overwritten"] is True
    assert report["acceptance"]["hub_upload"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["admitted"]["vector_count"] == len(corpus.chunks)
    assert report["family_counts"]["vector"] == len(corpus.chunks)
    assert report["network_required"] is False
    assert report["embedding_contract"]["model_id"] == PINNED_MODEL_ID
    assert report["embedding_contract"]["model_revision"] == PINNED_MODEL_REVISION
    assert report["embedding_contract"]["dimension"] == 384
    assert find_secret_surfaces(report) == []
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob
    assert_federal_vectors_report(report)
    path = tmp_path / "federal_vectors.json"
    written = write_federal_vectors_report(path, corpus=corpus)
    assert written == path
    loaded = load_federal_vectors_report(path)
    assert loaded["task_id"] == TASK_ID
    assert "/home/" not in path.read_text(encoding="utf-8")


def test_on_disk_vectors_report_matches_contract(corpus) -> None:
    path = default_vectors_report_path()
    write_federal_vectors_report(path, corpus=corpus)
    assert path.is_file()
    assert path.name == "federal_vectors.json"
    assert "legal_corpora_reindex" in path.parts
    loaded = load_federal_vectors_report(path)
    assert loaded["task_id"] == TASK_ID
    assert loaded["acceptance"]["hub_upload"] is False
    assert_federal_vectors_report(loaded)
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert loaded["checks"]["every_searchable_chunk_has_one_vector"] is True
    assert loaded["embedding_contract"]["model_id"] == PINNED_MODEL_ID
    assert loaded["bounds"]["maximum_rows_per_physical_shard"] == 4096
    assert loaded["bounds"]["maximum_rows_per_vector_centroid"] == 8192
    assert loaded["bounds"]["maximum_shards_per_centroid"] == 2
    assert "federal_register_gte_small.faiss" not in [
        path for path in loaded["demo"]["shard_relative_paths"]
    ]
    assert FORBIDDEN_LEGACY_FAISS_FILENAMES
