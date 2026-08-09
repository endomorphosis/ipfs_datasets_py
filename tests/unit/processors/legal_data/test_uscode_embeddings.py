"""Unit tests for pinned legal embedding generation (USCIR-017).

Acceptance:

* Unknown/mutable/placeholder model references fail closed.
* Output keys exactly match admitted chunks.
* Dimensions/norms are validated.
* Legacy positional vectors are never promoted.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (
    DEFAULT_DIMENSION,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    FIXTURE_SCHEMA_VERSION,
    NORM_TOLERANCE,
    SCHEMA_VERSION,
    TASK_ID,
    AdmittedChunk,
    ChunkKeyMismatchError,
    DeviceFallbackPolicy,
    DimensionValidationError,
    EmbeddingConfigError,
    EmbeddingFixtureError,
    EmbeddingGenerationResult,
    HardwareUnavailableError,
    LegacyVectorPromotionError,
    NormValidationError,
    UnpinnedModelError,
    UscodeEmbeddingConfig,
    UscodeEmbeddingGenerator,
    assert_output_keys_match_admitted,
    build_default_embedding_contract_fixture_payload,
    coerce_admitted_chunks,
    default_embedding_config,
    default_embedding_contract_fixture_path,
    generate_uscode_embeddings,
    input_content_hash,
    is_legacy_positional_identity,
    is_placeholder_model_ref,
    is_untrusted_legacy_vector_row,
    l2_norm,
    load_embedding_contract_fixture_payload,
    promote_legacy_vectors,
    reject_placeholder_model_ref,
    run_contract_case,
    select_device,
    validate_vector_dimension,
    validate_vector_norm,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    PositionalIdentityError,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_embedding_contract.json"
)


def _sample_chunks() -> list[dict]:
    return [
        {
            "chunk_cid": (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "entry_cid": (
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            "text": "Whoever invents or discovers any new and useful process.",
            "heading": "Inventions patentable",
            "title": "35",
            "section": "101",
            "legal_id": "usc:us:35:101",
        },
        {
            "chunk_cid": (
                "sha256:cccccccccccccccccccccccccccccccc"
                "cccccccccccccccccccccccccccccccc"
            ),
            "entry_cid": (
                "sha256:dddddddddddddddddddddddddddddddd"
                "dddddddddddddddddddddddddddddddd"
            ),
            "text": "Each agency shall make available to the public information.",
            "heading": "Public information",
            "title": "5",
            "section": "552",
            "legal_id": "usc:us:5:552",
        },
    ]


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_embedding_contract_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_embedding_contract_fixture_path().name == (
        "uscode_embedding_contract.json"
    )
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["acceptance"][
        "unknown_mutable_placeholder_model_refs_fail_closed"
    ]
    assert payload["acceptance"]["output_keys_exactly_match_admitted_chunks"]
    assert payload["acceptance"]["dimensions_and_norms_validated"]
    assert payload["acceptance"]["legacy_positional_vectors_never_promoted"]
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 5
    # Recipe form: no bulk per-vector golden dumps.
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "embeddings" not in case


def test_default_payload_matches_on_disk_recipe():
    built = build_default_embedding_contract_fixture_payload()
    on_disk = load_embedding_contract_fixture_payload(_FIXTURE_PATH)
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


def test_malformed_fixture_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": "nope", "cases": []}),
        encoding="utf-8",
    )
    with pytest.raises(EmbeddingFixtureError):
        load_embedding_contract_fixture_payload(bad)


def test_all_contract_cases_pass():
    payload = load_embedding_contract_fixture_payload(_FIXTURE_PATH)
    for case in payload["cases"]:
        outcome = run_contract_case(case)
        assert outcome["ok"], outcome


# ---------------------------------------------------------------------------
# Config pin / fail-closed model refs
# ---------------------------------------------------------------------------


def test_default_config_is_fully_bound():
    config = default_embedding_config()
    assert config.schema_version == SCHEMA_VERSION
    assert config.model_id == DEFAULT_MODEL_ID
    assert config.model_revision == DEFAULT_MODEL_REVISION
    assert config.license
    assert config.max_tokens > 0
    assert config.pooling == "mean"
    assert config.normalization == "l2"
    assert config.input_fields == ("text",)
    assert config.dimension == DEFAULT_DIMENSION
    assert config.vector_space_id
    assert config.config_cid.startswith("sha256:")
    assert len(config.digest) == 64


@pytest.mark.parametrize(
    "model_id,model_revision",
    [
        ("unknown", DEFAULT_MODEL_REVISION),
        ("placeholder", DEFAULT_MODEL_REVISION),
        ("mock", DEFAULT_MODEL_REVISION),
        ("none", DEFAULT_MODEL_REVISION),
        ("org/dummy", DEFAULT_MODEL_REVISION),
        (DEFAULT_MODEL_ID, "latest"),
        (DEFAULT_MODEL_ID, "main"),
        (DEFAULT_MODEL_ID, "HEAD"),
        (DEFAULT_MODEL_ID, "unknown"),
        (DEFAULT_MODEL_ID, "unpinned"),
        ("", DEFAULT_MODEL_REVISION),
        (DEFAULT_MODEL_ID, ""),
        (None, DEFAULT_MODEL_REVISION),
        (DEFAULT_MODEL_ID, None),
    ],
)
def test_unknown_mutable_placeholder_model_refs_fail_closed(
    model_id, model_revision
):
    with pytest.raises((UnpinnedModelError, EmbeddingConfigError)):
        UscodeEmbeddingConfig(model_id=model_id, model_revision=model_revision)
    with pytest.raises((UnpinnedModelError, EmbeddingConfigError)):
        reject_placeholder_model_ref(
            model_id=model_id, model_revision=model_revision
        )


def test_placeholder_detection_helpers():
    assert is_placeholder_model_ref("unknown")
    assert is_placeholder_model_ref("mock")
    assert is_placeholder_model_ref("")
    assert is_placeholder_model_ref(None)
    assert not is_placeholder_model_ref(DEFAULT_MODEL_ID)


def test_missing_license_fails_closed():
    with pytest.raises((UnpinnedModelError, EmbeddingConfigError)):
        UscodeEmbeddingConfig(license="unknown")


def test_invalid_pooling_and_normalization_fail():
    with pytest.raises(EmbeddingConfigError):
        UscodeEmbeddingConfig(pooling="mystery")
    with pytest.raises(EmbeddingConfigError):
        UscodeEmbeddingConfig(normalization="zscore")


def test_empty_input_fields_fail():
    with pytest.raises(EmbeddingConfigError):
        UscodeEmbeddingConfig(input_fields=())


# ---------------------------------------------------------------------------
# Output keys match admitted chunks
# ---------------------------------------------------------------------------


def test_output_keys_exactly_match_admitted_chunks():
    result = generate_uscode_embeddings(_sample_chunks())
    admitted = {c["chunk_cid"] for c in _sample_chunks()}
    assert set(result.embeddings.keys()) == admitted
    assert set(result.admitted_chunk_cids) == admitted
    assert_output_keys_match_admitted(
        result.embeddings, result.admitted_chunk_cids
    )


def test_extra_output_key_fails_closed():
    result = generate_uscode_embeddings(_sample_chunks())
    bad = dict(result.embeddings)
    # Forge an extra key.
    first = next(iter(bad.values()))
    bad[
        "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    ] = first
    with pytest.raises(ChunkKeyMismatchError):
        assert_output_keys_match_admitted(bad, result.admitted_chunk_cids)


def test_missing_output_key_fails_closed():
    result = generate_uscode_embeddings(_sample_chunks())
    bad = dict(result.embeddings)
    del bad[next(iter(bad))]
    with pytest.raises(ChunkKeyMismatchError):
        assert_output_keys_match_admitted(bad, result.admitted_chunk_cids)


def test_duplicate_admitted_chunk_cid_fails():
    chunks = _sample_chunks()
    chunks.append(dict(chunks[0]))
    with pytest.raises(ChunkKeyMismatchError):
        coerce_admitted_chunks(chunks)


def test_positional_chunk_cid_rejected():
    with pytest.raises(PositionalIdentityError):
        AdmittedChunk(chunk_cid="row-12", text="nope")
    with pytest.raises(PositionalIdentityError):
        coerce_admitted_chunks(
            [{"chunk_cid": "row-99", "text": "positional"}]
        )


# ---------------------------------------------------------------------------
# Dimensions / norms
# ---------------------------------------------------------------------------


def test_dimensions_and_unit_norms_validated():
    result = generate_uscode_embeddings(_sample_chunks())
    for cid, rec in result.embeddings.items():
        assert rec.dimension == DEFAULT_DIMENSION
        assert len(rec.embedding) == DEFAULT_DIMENSION
        assert all(math.isfinite(x) for x in rec.embedding)
        assert abs(rec.l2_norm - 1.0) <= NORM_TOLERANCE
        measured = l2_norm(rec.embedding)
        assert abs(measured - 1.0) <= NORM_TOLERANCE
        assert rec.input_hash == input_content_hash(
            next(c["text"] for c in _sample_chunks() if c["chunk_cid"] == cid)
        )


def test_wrong_dimension_from_embedder_fails():
    def bad_embedder(texts):
        return [[0.25] * 16 for _ in texts]

    with pytest.raises(DimensionValidationError):
        generate_uscode_embeddings(_sample_chunks(), embedder=bad_embedder)


def test_non_unit_norm_fails_validation():
    vector = (2.0, 0.0, 0.0)
    with pytest.raises(NormValidationError):
        validate_vector_norm(vector, normalization="l2")


def test_validate_vector_dimension_helper():
    ok = validate_vector_dimension([0.0, 1.0, 0.0], dimension=3)
    assert ok == (0.0, 1.0, 0.0)
    with pytest.raises(DimensionValidationError):
        validate_vector_dimension([1.0, 2.0], dimension=3)
    with pytest.raises(DimensionValidationError):
        validate_vector_dimension([float("nan"), 0.0], dimension=2)


def test_empty_text_zero_vector_allowed_under_l2():
    chunks = [
        {
            "chunk_cid": (
                "sha256:99999999999999999999999999999999"
                "99999999999999999999999999999999"
            ),
            "text": "",
        }
    ]
    result = generate_uscode_embeddings(chunks)
    rec = result.embeddings[chunks[0]["chunk_cid"]]
    assert rec.l2_norm == 0.0
    assert all(x == 0.0 for x in rec.embedding)


# ---------------------------------------------------------------------------
# Legacy positional vectors never promoted
# ---------------------------------------------------------------------------


def test_legacy_positional_vectors_never_promoted():
    legacy_rows = [
        {
            "id": "row-0",
            "document_index": 0,
            "embedding": [0.1] * DEFAULT_DIMENSION,
            "model": None,
            "model_revision": None,
        },
        {
            "cid": "row-99",
            "embedding": [0.2] * DEFAULT_DIMENSION,
        },
        {
            # Well-formed-looking row still cannot use the promotion path.
            "chunk_cid": (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "entry_cid": (
                "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            ),
            "model_id": DEFAULT_MODEL_ID,
            "model_revision": DEFAULT_MODEL_REVISION,
            "embedding": [0.3] * DEFAULT_DIMENSION,
        },
    ]
    with pytest.raises(LegacyVectorPromotionError) as excinfo:
        promote_legacy_vectors(legacy_rows)
    assert excinfo.value.code == "legacy_promotion_forbidden"


def test_empty_legacy_batch_still_forbidden():
    with pytest.raises(LegacyVectorPromotionError):
        promote_legacy_vectors([])


def test_legacy_identity_helpers():
    assert is_legacy_positional_identity("row-12")
    assert is_legacy_positional_identity("document_index_3")
    assert not is_legacy_positional_identity(
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert is_untrusted_legacy_vector_row(
        {"id": "row-1", "embedding": [0.1] * 8, "model": None}
    )
    assert is_untrusted_legacy_vector_row(
        {
            "chunk_cid": (
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "model_id": "unknown",
            "model_revision": DEFAULT_MODEL_REVISION,
            "embedding": [0.1] * 8,
        }
    )


# ---------------------------------------------------------------------------
# Reproducibility, batching, CPU fallback, checkpoints
# ---------------------------------------------------------------------------


def test_generation_is_reproducible():
    first = generate_uscode_embeddings(_sample_chunks())
    second = generate_uscode_embeddings(_sample_chunks())
    assert first.vectors_by_chunk_cid == second.vectors_by_chunk_cid
    for cid in first.embeddings:
        assert first.embeddings[cid].input_hash == second.embeddings[cid].input_hash
        assert first.embeddings[cid].model_id == DEFAULT_MODEL_ID
        assert first.embeddings[cid].model_revision == DEFAULT_MODEL_REVISION


def test_batching_covers_all_chunks():
    config = UscodeEmbeddingConfig(batch_size=1)
    result = generate_uscode_embeddings(_sample_chunks(), config=config)
    assert result.batch_count == 2
    assert len(result.embeddings) == 2


def test_cpu_fallback_when_cuda_unavailable():
    def probe(device: str) -> bool:
        return str(device).startswith("cpu")

    config = UscodeEmbeddingConfig(
        device="cuda",
        device_fallback=DeviceFallbackPolicy.FALLBACK_CPU,
    )
    result = generate_uscode_embeddings(
        _sample_chunks(),
        config=config,
        device_probe=probe,
    )
    assert result.device_requested == "cuda"
    assert result.device_selected == "cpu"
    assert result.device_fallback_applied is True


def test_hardware_block_policy():
    def probe(device: str) -> bool:
        return device == "cpu"

    with pytest.raises(HardwareUnavailableError):
        select_device(
            "cuda",
            fallback=DeviceFallbackPolicy.BLOCK,
            probe=probe,
        )


def test_checkpoint_written_atomically(tmp_path: Path):
    ckpt = tmp_path / "embed.ckpt.json"
    config = UscodeEmbeddingConfig(batch_size=1)
    result = generate_uscode_embeddings(
        _sample_chunks(),
        config=config,
        checkpoint_path=ckpt,
    )
    assert ckpt.is_file()
    payload = json.loads(ckpt.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["config_digest"] == config.digest
    assert set(payload["completed_chunk_cids"]) == set(result.embeddings)


def test_generator_class_matches_function():
    gen = UscodeEmbeddingGenerator()
    result = gen.generate(_sample_chunks())
    assert isinstance(result, EmbeddingGenerationResult)
    assert len(result.embeddings) == 2


def test_result_to_dict_roundtrip_surface():
    result = generate_uscode_embeddings(_sample_chunks())
    payload = result.to_dict(include_vectors=True)
    assert payload["vector_count"] == 2
    assert set(payload["embeddings"]) == set(result.embeddings)
    compact = result.to_dict(include_vectors=False)
    assert "embeddings" not in compact
    assert set(compact["embedding_keys"]) == set(result.embeddings)
