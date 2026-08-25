"""Unit tests for pinned state-law embeddings (LCR-028).

Acceptance: embedding key set equals admitted searchable chunk key set
exactly with no zero, duplicate, orphan, NaN, wrong-dimension, stale-model,
or changed-input vector.

Tests are hermetic. They use the sealed local hashed projection and never
download sentence-transformers or torch models. No Hub upload, no tokens,
no absolute home paths.
"""

from __future__ import annotations

import json
import math
import socket
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_chunker import (
    TASK_ID as CHUNKER_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    TASK_ID as CORPUS_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graphrag_adapter import (
    TASK_ID as ADAPTER_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    DEFAULT_BACKEND,
    GOAL_ID,
    NORM_TOLERANCE,
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
    DuplicateVectorError,
    EmbeddingConfigError,
    EmbeddingRecord,
    EmbeddingReleaseAuthorizationError,
    InputHashDriftError,
    OrphanVectorError,
    StaleModelError,
    StateLawsEmbeddingConfig,
    UnpinnedModelError,
    VectorCoverageError,
    ZeroVectorError,
    admitted_fixture_chunks,
    assert_embedding_conservation,
    assert_embedding_receipt,
    assert_input_hashes_match,
    assert_records_match_pin,
    bind_fixture_embeddings,
    build_embedding_receipt,
    check_embedding_receipt,
    check_receipt_matches_fixture,
    coerce_state_law_chunks,
    default_embedding_config,
    default_embedding_receipt_path,
    default_vector_space_id,
    fixture_embedding_chunks,
    fixture_embedding_config,
    generate_state_laws_embeddings,
    input_content_hash,
    is_production_backend,
    is_projection_backend,
    l2_norm,
    load_embedding_receipt,
    production_embedding_config,
    projection_cannot_authorize_publication,
    require_pinned_gte_small,
    validate_vector_dimension,
    write_embedding_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_MODEL_ID as USCODE_MODEL_ID,
    DEFAULT_MODEL_REVISION as USCODE_MODEL_REVISION,
    DEFAULT_NORMALIZATION as USCODE_NORMALIZATION,
    DEFAULT_POOLING as USCODE_POOLING,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    PositionalIdentityError,
)


def _cid(nibble: str) -> str:
    from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import _cid as make_cid

    return make_cid(nibble)


@pytest.fixture(scope="module")
def compact_binding():
    return bind_fixture_embeddings()


# ---------------------------------------------------------------------------
# Identity / pin
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-embeddings-v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-embeddings@1"
    assert TASK_ID == "LCR-028"
    assert GOAL_ID == "LCR-G040"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "state_laws_embeddings.py"
    assert PRIMARY_KEY == "chunk_cid"
    assert RELEASE_PROFILE == "state-laws-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert CHUNKER_TASK_ID == "LCR-025"
    assert CORPUS_TASK_ID == "LCR-024"
    assert ADAPTER_TASK_ID == "LCR-026"


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
    assert is_production_backend(production.backend) is True
    fixture = fixture_embedding_config()
    assert fixture.is_projection_backend is True
    assert is_projection_backend(fixture.backend) is True
    assert fixture.backend != production.backend
    assert projection_cannot_authorize_publication() is True
    assert fixture.may_authorize_publication is False
    assert production.may_authorize_publication is False


def test_placeholder_model_refs_fail_closed() -> None:
    with pytest.raises(UnpinnedModelError):
        StateLawsEmbeddingConfig(
            model_id="mock", model_revision=PINNED_MODEL_REVISION
        )
    with pytest.raises(UnpinnedModelError):
        StateLawsEmbeddingConfig(
            model_id="unknown", model_revision=PINNED_MODEL_REVISION
        )
    with pytest.raises(UnpinnedModelError):
        StateLawsEmbeddingConfig(
            model_id=PINNED_MODEL_ID, model_revision="latest"
        )
    with pytest.raises(UnpinnedModelError):
        StateLawsEmbeddingConfig(
            model_id=PINNED_MODEL_ID, model_revision="placeholder"
        )
    with pytest.raises(UnpinnedModelError):
        require_pinned_gte_small(
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision=PINNED_MODEL_REVISION,
        )


def test_pin_mismatch_fails_closed() -> None:
    with pytest.raises(UnpinnedModelError):
        StateLawsEmbeddingConfig(
            model_id=PINNED_MODEL_ID,
            model_revision="c9745ed1d9f207416be6d2e6f19aa49b8566f3e3",
        )
    with pytest.raises(UnpinnedModelError):
        require_pinned_gte_small(
            model_id="BAAI/bge-small-en-v1.5",
            model_revision=PINNED_MODEL_REVISION,
        )


def test_wrong_pooling_normalization_or_dimension_fail_closed() -> None:
    with pytest.raises(EmbeddingConfigError):
        StateLawsEmbeddingConfig(pooling="cls")
    with pytest.raises(EmbeddingConfigError):
        StateLawsEmbeddingConfig(normalization="none")
    with pytest.raises(EmbeddingConfigError):
        StateLawsEmbeddingConfig(dimension=768)
    with pytest.raises(EmbeddingConfigError):
        StateLawsEmbeddingConfig(max_tokens=1024)


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
        assert abs(norm - 1.0) <= NORM_TOLERANCE
        assert abs(record.l2_norm - 1.0) <= NORM_TOLERANCE
        assert record.l2_norm > 0.0
        assert record.model_id == PINNED_MODEL_ID
        assert record.model_revision == PINNED_MODEL_REVISION
        assert record.pooling == "mean"
        assert record.normalization == "l2"


def test_key_set_equals_admitted_searchable_chunks(compact_binding) -> None:
    admitted = admitted_fixture_chunks()
    expected = sorted(row["chunk_cid"] for row in admitted)
    assert compact_binding.vector_count == len(expected)
    assert sorted(compact_binding.vector_keys) == expected
    assert len(compact_binding.vector_keys) == len(set(compact_binding.vector_keys))
    result = compact_binding.generation
    assert result is not None
    assert set(result.embeddings) == set(result.admitted_chunk_cids)
    assert_embedding_conservation(result, expected_chunk_cids=expected)


def test_generate_is_deterministic_and_uses_projection_backend() -> None:
    chunks = admitted_fixture_chunks()
    first = generate_state_laws_embeddings(chunks)
    second = generate_state_laws_embeddings(list(reversed(chunks)))
    assert first.config.backend == PROJECTION_BACKEND
    keys = sorted(first.embeddings)
    assert keys == sorted(second.embeddings)
    for key in keys:
        assert first.embeddings[key].embedding == second.embeddings[key].embedding
        assert first.embeddings[key].input_hash == second.embeddings[key].input_hash


def test_recovery_and_excluded_rows_never_enter_embeddings() -> None:
    result = generate_state_laws_embeddings(fixture_embedding_chunks())
    keys = set(result.embeddings)
    assert _cid("f") not in keys
    assert "" not in keys
    assert len(keys) == 8
    assert_embedding_conservation(result, expected_chunk_cids=sorted(keys))


def test_duplicate_chunk_cid_fails_closed() -> None:
    first = admitted_fixture_chunks()[0]
    with pytest.raises(Exception):
        generate_state_laws_embeddings([first, dict(first)])


def test_positional_identity_is_rejected() -> None:
    with pytest.raises((VectorCoverageError, PositionalIdentityError, Exception)):
        generate_state_laws_embeddings(
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
        generate_state_laws_embeddings([])


def test_no_nan_or_zero_vectors(compact_binding) -> None:
    for record in compact_binding.embeddings.values():
        assert all(math.isfinite(value) for value in record.embedding)
        assert l2_norm(record.embedding) > 0.0
        assert not any(value == 0.0 and value != 0.0 for value in record.embedding)


def test_zero_vector_from_embedder_fails_closed() -> None:
    def zero_embedder(texts):
        return [[0.0] * PINNED_DIMENSION for _ in texts]

    with pytest.raises(ZeroVectorError):
        generate_state_laws_embeddings(
            admitted_fixture_chunks(),
            embedder=zero_embedder,
        )


def test_wrong_dimension_from_embedder_fails() -> None:
    def bad_embedder(texts):
        return [[0.25] * 16 for _ in texts]

    with pytest.raises(Exception):
        generate_state_laws_embeddings(
            admitted_fixture_chunks(),
            embedder=bad_embedder,
        )


def test_nan_vector_from_embedder_fails() -> None:
    def nan_embedder(texts):
        values = [0.0] * PINNED_DIMENSION
        values[0] = float("nan")
        return [list(values) for _ in texts]

    with pytest.raises(Exception):
        generate_state_laws_embeddings(
            admitted_fixture_chunks(),
            embedder=nan_embedder,
        )


def test_input_receipts_bind_model_and_text_hash(compact_binding) -> None:
    admitted = admitted_fixture_chunks()
    assert len(compact_binding.input_receipts) == compact_binding.vector_count
    by_cid = {row["chunk_cid"]: row for row in admitted}
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
        source = by_cid[receipt.chunk_cid]
        assert record.input_hash == input_content_hash(source["text"])


def test_input_hash_drift_fails_closed(compact_binding) -> None:
    drifted = [dict(row) for row in admitted_fixture_chunks()]
    drifted[0] = dict(drifted[0], text="changed statutory text must not reuse vector")
    with pytest.raises(InputHashDriftError):
        assert_input_hashes_match(compact_binding.generation, drifted)


def test_stale_model_vector_fails_closed(compact_binding) -> None:
    first = next(iter(compact_binding.embeddings.values()))
    stale = EmbeddingRecord(
        chunk_cid=first.chunk_cid,
        embedding=first.embedding,
        dimension=first.dimension,
        input_hash=first.input_hash,
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="c9745ed1d9f207416be6d2e6f19aa49b8566f3e3",
        vector_space_id=first.vector_space_id,
        pooling=first.pooling,
        normalization=first.normalization,
        l2_norm=first.l2_norm,
        config_cid=first.config_cid,
        entry_cid=first.entry_cid,
        chunk_id=first.chunk_id,
    )
    with pytest.raises((StaleModelError, UnpinnedModelError, EmbeddingConfigError)):
        assert_records_match_pin({stale.chunk_cid: stale})


def test_orphan_vector_fails_closed(compact_binding) -> None:
    expected = [row["chunk_cid"] for row in admitted_fixture_chunks()[:-1]]
    with pytest.raises(OrphanVectorError):
        assert_embedding_conservation(
            compact_binding.generation,
            expected_chunk_cids=expected,
        )


def test_coerce_skips_recovery_and_keeps_admitted() -> None:
    admitted = coerce_state_law_chunks(fixture_embedding_chunks())
    assert len(admitted) == 8
    assert all(chunk.chunk_cid for chunk in admitted)


# ---------------------------------------------------------------------------
# Receipt / CLI contract
# ---------------------------------------------------------------------------


def test_embedding_receipt_is_secret_free_and_fixture_bound(
    compact_binding, tmp_path: Path
) -> None:
    report = build_embedding_receipt(binding=compact_binding)
    assert report["task_id"] == TASK_ID
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["schema"] == REPORT_SCHEMA
    assert report["goal_id"] == GOAL_ID
    assert report["program_id"] == PROGRAM_ID
    assert report["acceptance"]["keys_equal_admitted_searchable_chunks"] is True
    assert report["acceptance"]["vector_dimension_384"] is True
    assert report["acceptance"]["l2_normalized"] is True
    assert report["acceptance"]["hub_upload"] is False
    assert report["acceptance"]["secrets_absent"] is True
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["hub_upload"] is False
    assert report["secrets_absent"] is True
    assert report["network_required"] is False
    assert report["embedding_contract"]["model_id"] == PINNED_MODEL_ID
    assert report["embedding_contract"]["model_revision"] == PINNED_MODEL_REVISION
    assert report["embedding_contract"]["dimension"] == 384
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob
    assert_embedding_receipt(report)
    path = tmp_path / "embedding_receipt.json"
    written = write_embedding_receipt(path, binding=compact_binding)
    assert written == path
    loaded = load_embedding_receipt(path)
    assert loaded["task_id"] == TASK_ID
    assert "/home/" not in path.read_text(encoding="utf-8")


def test_fixture_only_check_matches_on_disk_receipt_acceptance() -> None:
    path = default_embedding_receipt_path()
    write_embedding_receipt(path)
    assert path.is_file()
    assert path.name == "embedding_receipt.json"
    assert "legal_corpora_reindex" in path.parts
    on_disk = load_embedding_receipt(path)
    live = build_embedding_receipt()
    check_receipt_matches_fixture(on_disk, live)
    result = check_embedding_receipt(on_disk)
    assert result["ok"] is True
    assert result["task_id"] == TASK_ID
    assert result["hub_upload"] is False
    assert result["authorizing_for_publication"] is False
    assert result["secrets_absent"] is True
    assert on_disk["acceptance"] == live["acceptance"]
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob


def test_receipt_cannot_authorize_publication() -> None:
    report = build_embedding_receipt()
    mutated = dict(report)
    mutated["authorizing_for_publication"] = True
    with pytest.raises(EmbeddingReleaseAuthorizationError):
        assert_embedding_receipt(mutated)


def test_validate_helpers_reject_nan() -> None:
    with pytest.raises(Exception):
        validate_vector_dimension([float("nan"), 0.0], dimension=2)


# ---------------------------------------------------------------------------
# No network
# ---------------------------------------------------------------------------


def test_fixture_generation_does_not_touch_the_network(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("network forbidden in LCR-028 fixture embeddings")

    monkeypatch.setattr(socket, "socket", boom)
    result = generate_state_laws_embeddings(admitted_fixture_chunks())
    assert result.config.backend == PROJECTION_BACKEND
    assert len(result.embeddings) == 8
    receipt = build_embedding_receipt()
    assert receipt["network_required"] is False
    assert "sentence_transformers" not in str(result.config.backend)


def test_default_backend_never_loads_sentence_transformers() -> None:
    import sys

    before = set(sys.modules)
    generate_state_laws_embeddings(admitted_fixture_chunks())
    added = set(sys.modules) - before
    assert not any("sentence_transformers" in name for name in added)
    config = default_embedding_config()
    assert config.backend == PROJECTION_BACKEND
    assert config.device == "cpu"
