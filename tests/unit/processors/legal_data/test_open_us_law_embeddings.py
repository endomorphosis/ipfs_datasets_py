"""Unit tests for pinned thenlper/gte-small embeddings (OUL-028).

Acceptance: every admitted chunk is embedded with sentence-transformers
thenlper/gte-small at revision 17e1f347d17fe144873b1201da91788898c639cd,
384 dimensions, mean pooling, L2 normalization, real 512-token
truncation, input hashes, device evidence, and resumable checkpoints;
projection fallback cannot authorize release.
"""

from __future__ import annotations

import inspect
import json
import math
import types
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    AUTHORIZES_PUBLICATION,
    CHECKPOINT_SCHEMA_VERSION,
    DEFAULT_BACKEND,
    DEFAULT_DEVICE,
    DEFAULT_PRECISION,
    DEFAULT_PROVIDER,
    EXACT_51_SEED_ROW_LOWER_BOUND,
    GOAL_ID,
    NORM_TOLERANCE,
    PER_CALL_CHUNK_CEILING,
    PINNED_DIMENSION,
    PINNED_MAX_TOKENS,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_NORMALIZATION,
    PINNED_POOLING,
    PINNED_TOKEN_COUNTER_ID,
    PRODUCTION_BACKEND,
    PROGRAM_ID,
    PROJECTION_BACKEND,
    PROJECTION_FALLBACK_AUTHORIZES_RELEASE,
    PROVES_SOFTWARE_CONTRACT_ONLY,
    RECEIPT_SCHEMA_VERSION,
    REQUIRES_REAL_512_TOKEN_TRUNCATION,
    SCHEMA_VERSION,
    TASK_ID,
    AdmittedChunk,
    ChunkKeyMismatchError,
    DeviceFallbackPolicy,
    DimensionValidationError,
    EmbeddingCheckpointError,
    EmbeddingConfigError,
    EmbeddingGenerationResult,
    HardwareUnavailableError,
    MissingVectorError,
    OpenUsLawEmbeddingConfig,
    OpenUsLawEmbeddingGenerator,
    ProjectionReleaseAuthorizationError,
    ReleaseAuthorizationError,
    TruncationContractError,
    UnpinnedModelError,
    apply_real_512_token_truncation,
    assert_chunk_stream_unbounded,
    assert_embedding_receipt,
    assert_no_truncating_chunk_ceiling,
    assert_output_keys_match_admitted,
    authorize_embedding_release,
    build_embedding_receipt,
    build_pinned_model_token_counter,
    build_sentence_transformers_embedder,
    build_vector_space_id,
    coerce_admitted_chunks,
    collect_model_file_evidence,
    default_embedding_config,
    default_embedding_receipt_path,
    default_vector_space_id,
    deterministic_project,
    fixture_embedding_config,
    fixture_sample_chunks,
    generate_open_us_law_embeddings,
    input_content_hash,
    is_production_backend,
    is_projection_backend,
    iter_admitted_chunks,
    l2_norm,
    load_checkpoint,
    load_embedding_receipt,
    projection_cannot_authorize_release,
    release_authorization_reasons,
    require_pinned_gte_small,
    select_device,
    validate_vector_dimension,
    validate_vector_norm,
    write_embedding_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    PositionalIdentityError,
)


def _sample_chunks() -> list[dict[str, str]]:
    return fixture_sample_chunks()


def _third_chunk() -> dict[str, str]:
    return {
        "chunk_cid": (
            "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
            "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        ),
        "entry_cid": (
            "sha256:ffffffffffffffffffffffffffffffff"
            "ffffffffffffffffffffffffffffffff"
        ),
        "text": "Resumed work embeds only remaining admitted chunks.",
        "heading": "Resume",
        "title": "1",
        "section": "3",
        "legal_id": "oul:or:statutes:1:1:3",
    }


def _cpu_probe(device: str) -> bool:
    return str(device).startswith("cpu")


def _unit_embedder(texts):
    vectors = []
    for index, text in enumerate(texts):
        values = [0.0] * PINNED_DIMENSION
        # Distinct non-zero directions so keys remain distinguishable.
        values[index % PINNED_DIMENSION] = 1.0 + (len(text) % 7) * 0.01
        vectors.append(values)
    return vectors


def _generate_fixture(**kwargs):
    kwargs.setdefault("config", fixture_embedding_config())
    kwargs.setdefault("device_probe", _cpu_probe)
    return generate_open_us_law_embeddings(_sample_chunks(), **kwargs)


# ---------------------------------------------------------------------------
# Identity / pin
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-embeddings-v1"
    assert TASK_ID == "OUL-028"
    assert GOAL_ID == "OUL-G040"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert PINNED_MODEL_ID == "thenlper/gte-small"
    assert PINNED_MODEL_REVISION == "17e1f347d17fe144873b1201da91788898c639cd"
    assert PINNED_DIMENSION == 384
    assert PINNED_MAX_TOKENS == 512
    assert PINNED_POOLING == "mean"
    assert PINNED_NORMALIZATION == "l2"
    assert DEFAULT_BACKEND == PRODUCTION_BACKEND == "sentence_transformers"
    assert DEFAULT_PROVIDER == "huggingface"
    assert DEFAULT_DEVICE == "cuda"
    assert DEFAULT_PRECISION == "fp32"
    assert REQUIRES_REAL_512_TOKEN_TRUNCATION is True
    assert PROJECTION_FALLBACK_AUTHORIZES_RELEASE is False
    assert AUTHORIZES_PUBLICATION is False
    assert PROVES_SOFTWARE_CONTRACT_ONLY is True
    assert PER_CALL_CHUNK_CEILING is None
    assert EXACT_51_SEED_ROW_LOWER_BOUND == 1_904_919


def test_default_config_is_production_sentence_transformers_pin() -> None:
    config = default_embedding_config()
    assert config.model_id == PINNED_MODEL_ID
    assert config.model_revision == PINNED_MODEL_REVISION
    assert config.dimension == 384
    assert config.pooling == "mean"
    assert config.normalization == "l2"
    assert config.max_tokens == 512
    assert config.backend == "sentence_transformers"
    assert config.provider == "huggingface"
    assert config.device == "cuda"
    assert config.vector_space_id == default_vector_space_id()
    assert config.vector_space_id == (
        "gte-small@17e1f347d17fe144873b1201da91788898c639cd"
        ":d384:pool=mean:norm=l2"
    )
    assert config.config_cid.startswith("sha256:")
    assert len(config.digest) == 64
    assert config.may_authorize_release is True
    assert is_production_backend(config.backend)
    assert not is_projection_backend(config.backend)


def test_vector_space_id_binds_pin_pooling_and_norm() -> None:
    space = build_vector_space_id()
    assert space == default_vector_space_id()
    assert "gte-small@" in space
    assert PINNED_MODEL_REVISION in space
    assert ":d384:" in space
    assert "pool=mean" in space
    assert "norm=l2" in space


@pytest.mark.parametrize(
    "model_id,model_revision",
    [
        ("unknown", PINNED_MODEL_REVISION),
        ("placeholder", PINNED_MODEL_REVISION),
        ("mock", PINNED_MODEL_REVISION),
        ("org/dummy", PINNED_MODEL_REVISION),
        (PINNED_MODEL_ID, "latest"),
        (PINNED_MODEL_ID, "main"),
        (PINNED_MODEL_ID, "HEAD"),
        (PINNED_MODEL_ID, "unknown"),
        ("", PINNED_MODEL_REVISION),
        (PINNED_MODEL_ID, ""),
        (None, PINNED_MODEL_REVISION),
        (PINNED_MODEL_ID, None),
        ("sentence-transformers/all-MiniLM-L6-v2", PINNED_MODEL_REVISION),
        (
            PINNED_MODEL_ID,
            "c9745ed1d9f207416be6d2e6f19aa49b8566f3e3",
        ),
    ],
)
def test_unknown_mutable_or_wrong_model_refs_fail_closed(
    model_id, model_revision
) -> None:
    with pytest.raises((UnpinnedModelError, EmbeddingConfigError)):
        OpenUsLawEmbeddingConfig(model_id=model_id, model_revision=model_revision)
    with pytest.raises((UnpinnedModelError, EmbeddingConfigError)):
        require_pinned_gte_small(model_id=model_id, model_revision=model_revision)


def test_pooling_normalization_dimension_and_token_ceiling_are_pinned() -> None:
    with pytest.raises(EmbeddingConfigError):
        OpenUsLawEmbeddingConfig(pooling="cls")
    with pytest.raises(EmbeddingConfigError):
        OpenUsLawEmbeddingConfig(normalization="none")
    with pytest.raises(EmbeddingConfigError):
        OpenUsLawEmbeddingConfig(dimension=768)
    with pytest.raises(EmbeddingConfigError):
        OpenUsLawEmbeddingConfig(max_tokens=4096)
    with pytest.raises(EmbeddingConfigError):
        OpenUsLawEmbeddingConfig(max_tokens=256)


def test_fixture_config_is_projection_and_cannot_authorize() -> None:
    config = fixture_embedding_config()
    assert config.backend == PROJECTION_BACKEND
    assert is_projection_backend(config.backend)
    assert config.may_authorize_release is False
    assert projection_cannot_authorize_release() is True


# ---------------------------------------------------------------------------
# Admitted keys / dimensions / hashes
# ---------------------------------------------------------------------------


def test_output_keys_exactly_match_admitted_chunks() -> None:
    result = _generate_fixture()
    admitted = {chunk["chunk_cid"] for chunk in _sample_chunks()}
    assert set(result.embeddings.keys()) == admitted
    assert set(result.admitted_chunk_cids) == admitted
    assert_output_keys_match_admitted(result.embeddings, result.admitted_chunk_cids)
    assert result.config.dimension == 384
    assert result.config.pooling == "mean"
    assert result.config.normalization == "l2"


def test_every_vector_is_384d_finite_and_l2_unit() -> None:
    result = _generate_fixture()
    for cid, rec in result.embeddings.items():
        assert rec.dimension == PINNED_DIMENSION
        assert len(rec.embedding) == PINNED_DIMENSION
        assert all(math.isfinite(x) for x in rec.embedding)
        assert abs(rec.l2_norm - 1.0) <= NORM_TOLERANCE
        assert abs(l2_norm(rec.embedding) - 1.0) <= NORM_TOLERANCE
        assert rec.model_id == PINNED_MODEL_ID
        assert rec.model_revision == PINNED_MODEL_REVISION
        assert rec.pooling == "mean"
        assert rec.normalization == "l2"
        source = next(c for c in _sample_chunks() if c["chunk_cid"] == cid)
        assert rec.input_hash == input_content_hash(source["text"])


def test_input_hashes_are_stable_and_content_addressed() -> None:
    first = _generate_fixture()
    second = _generate_fixture()
    for cid, rec in first.embeddings.items():
        other = second.embeddings[cid]
        assert rec.input_hash == other.input_hash
        assert rec.embedding == other.embedding
        assert len(rec.input_hash) == 64


def test_duplicate_and_positional_chunk_cids_fail() -> None:
    chunks = _sample_chunks()
    chunks.append(dict(chunks[0]))
    with pytest.raises(ChunkKeyMismatchError):
        coerce_admitted_chunks(chunks)
    with pytest.raises(PositionalIdentityError):
        AdmittedChunk(chunk_cid="row-12", text="nope")
    with pytest.raises(PositionalIdentityError):
        coerce_admitted_chunks([{"chunk_cid": "row-99", "text": "positional"}])


def test_wrong_dimension_from_embedder_fails() -> None:
    def bad_embedder(texts):
        return [[0.25] * 16 for _ in texts]

    with pytest.raises(DimensionValidationError):
        generate_open_us_law_embeddings(
            _sample_chunks(),
            config=default_embedding_config(),
            embedder=bad_embedder,
            device_probe=_cpu_probe,
        )


def test_validate_helpers_reject_nan_and_non_unit() -> None:
    ok = validate_vector_dimension([0.0, 1.0, 0.0], dimension=3)
    assert ok == (0.0, 1.0, 0.0)
    with pytest.raises(DimensionValidationError):
        validate_vector_dimension([float("nan"), 0.0], dimension=2)
    with pytest.raises(EmbeddingConfigError):
        validate_vector_norm((1.0, 0.0), normalization="zscore")
    with pytest.raises(Exception):
        validate_vector_norm((2.0, 0.0, 0.0), normalization="l2")


# ---------------------------------------------------------------------------
# Device evidence
# ---------------------------------------------------------------------------


def test_device_evidence_records_requested_selected_and_fallback() -> None:
    result = generate_open_us_law_embeddings(
        _sample_chunks(),
        config=default_embedding_config(),
        embedder=_unit_embedder,
        device_probe=_cpu_probe,
    )
    assert result.device.requested == "cuda"
    assert result.device.selected == "cpu"
    assert result.device.fallback_applied is True
    assert result.device.precision == "fp32"
    payload = result.device.to_dict()
    assert payload["requested"] == "cuda"
    assert payload["selected"] == "cpu"
    assert payload["runtime"]["device"] == "cpu"
    assert payload["runtime"]["precision"] == "fp32"


def test_hardware_block_policy() -> None:
    with pytest.raises(HardwareUnavailableError):
        select_device(
            "cuda",
            fallback=DeviceFallbackPolicy.BLOCK,
            probe=_cpu_probe,
        )


# ---------------------------------------------------------------------------
# Real 512-token truncation
# ---------------------------------------------------------------------------


def test_apply_real_512_token_truncation_sets_model_and_tokenizer() -> None:
    model = types.SimpleNamespace(max_seq_length=8192)
    model.tokenizer = types.SimpleNamespace(model_max_length=8192)
    evidence = apply_real_512_token_truncation(model)
    assert model.max_seq_length == 512
    assert model.tokenizer.model_max_length == 512
    assert evidence.applied is True
    assert evidence.satisfies_contract is True
    assert evidence.max_seq_length == 512
    assert evidence.tokenizer_model_max_length == 512


def test_apply_real_512_token_truncation_rejects_other_windows() -> None:
    model = types.SimpleNamespace(max_seq_length=8192)
    with pytest.raises(TruncationContractError):
        apply_real_512_token_truncation(model, max_tokens=4096)


def test_sentence_transformers_factory_sets_max_seq_length() -> None:
    captured: dict[str, object] = {}

    class FakeModel:
        def __init__(self) -> None:
            self.max_seq_length = 8192
            self.tokenizer = types.SimpleNamespace(model_max_length=8192)

        def encode(self, texts, **kwargs):
            captured["encode_kwargs"] = kwargs
            captured["max_seq_length"] = self.max_seq_length
            captured["tokenizer_max"] = self.tokenizer.model_max_length
            return _unit_embedder(texts)

    def factory(config, device):
        captured["model_id"] = config.model_id
        captured["revision"] = config.model_revision
        captured["device"] = device
        return FakeModel()

    config = default_embedding_config()
    embedder, truncation, _files, real = build_sentence_transformers_embedder(
        config, device="cpu", model_factory=factory
    )
    vectors = embedder(["Every admitted chunk uses the pinned tokenizer window."])
    assert captured["model_id"] == PINNED_MODEL_ID
    assert captured["revision"] == PINNED_MODEL_REVISION
    assert captured["max_seq_length"] == 512
    assert captured["tokenizer_max"] == 512
    encode_kwargs = captured["encode_kwargs"]
    assert isinstance(encode_kwargs, dict)
    assert encode_kwargs.get("normalize_embeddings") is True
    assert truncation.satisfies_contract is True
    assert real is False
    assert len(vectors[0]) == 384


def test_model_file_evidence_hashes_nested_snapshot_files(tmp_path: Path) -> None:
    (tmp_path / "model.safetensors").write_bytes(b"model bytes")
    module = tmp_path / "1_Pooling"
    module.mkdir()
    (module / "config.json").write_text('{"pooling":"mean"}', encoding="utf-8")
    model = types.SimpleNamespace(cache_folder=str(tmp_path))

    evidence = collect_model_file_evidence(model)

    assert evidence["revision"] == PINNED_MODEL_REVISION
    assert evidence["file_count"] == 2
    assert [item["path"] for item in evidence["files"]] == [
        "1_Pooling/config.json",
        "model.safetensors",
    ]
    assert all(len(item["sha256"]) == 64 for item in evidence["files"])


def test_sentence_transformers_loader_source_assigns_max_seq_length() -> None:
    source = inspect.getsource(apply_real_512_token_truncation)
    assert "max_seq_length" in source
    assert "model_max_length" in source
    assert "512" in source
    factory_source = inspect.getsource(build_sentence_transformers_embedder)
    assert "apply_real_512_token_truncation" in factory_source
    loader_source = inspect.getsource(
        __import__(
            "ipfs_datasets_py.processors.legal_data.open_us_law_embeddings",
            fromlist=["load_sentence_transformer_model"],
        ).load_sentence_transformer_model
    )
    assert "SentenceTransformer" in loader_source
    assert "revision=config.model_revision" in loader_source


def test_pinned_model_token_counter_counts_untruncated_special_tokens() -> None:
    calls: list[dict[str, object]] = []

    class ExpandingTokenizer:
        def __call__(self, text: str, **kwargs):
            calls.append(dict(kwargs))
            return {"input_ids": [101, *(200 for _ in text.split() for _ in range(3)), 102]}

    counter, identity = build_pinned_model_token_counter(
        tokenizer=ExpandingTokenizer()
    )

    assert identity == PINNED_TOKEN_COUNTER_ID
    assert counter("one two") == 8
    assert calls[-1]["add_special_tokens"] is True
    assert calls[-1]["truncation"] is False


def test_generate_with_model_factory_records_truncation_evidence() -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.max_seq_length = 1024
            self.tokenizer = types.SimpleNamespace(model_max_length=1024)

        def encode(self, texts, **kwargs):
            return _unit_embedder(texts)

    result = generate_open_us_law_embeddings(
        _sample_chunks(),
        config=default_embedding_config(),
        model_factory=lambda config, device: FakeModel(),
        device_probe=_cpu_probe,
    )
    assert result.truncation.applied is True
    assert result.truncation.max_seq_length == 512
    assert result.truncation.tokenizer_model_max_length == 512
    assert result.embedder_kind == "injected_sentence_transformers"
    assert result.real_inference is False
    assert result.authorizing_for_release is False


# ---------------------------------------------------------------------------
# Projection cannot authorize release
# ---------------------------------------------------------------------------


def test_projection_result_cannot_authorize_release() -> None:
    result = _generate_fixture()
    assert result.config.backend == PROJECTION_BACKEND
    assert result.real_inference is False
    reasons = release_authorization_reasons(result)
    assert "projection_backend" in reasons
    assert result.authorizing_for_release is False
    with pytest.raises(ProjectionReleaseAuthorizationError, match="cannot authorize"):
        authorize_embedding_release(result)


def test_injected_fixture_embedder_cannot_authorize_release() -> None:
    result = generate_open_us_law_embeddings(
        _sample_chunks(),
        config=default_embedding_config(),
        embedder=_unit_embedder,
        device_probe=_cpu_probe,
    )
    assert result.embedder_kind == "injected"
    assert result.real_inference is False
    assert result.truncation.satisfies_contract is False
    with pytest.raises((ProjectionReleaseAuthorizationError, ReleaseAuthorizationError)):
        authorize_embedding_release(result)


def test_projection_flag_constant_is_false() -> None:
    assert PROJECTION_FALLBACK_AUTHORIZES_RELEASE is False
    assert projection_cannot_authorize_release() is True


# ---------------------------------------------------------------------------
# Resumable checkpoints
# ---------------------------------------------------------------------------


def test_checkpoint_resume_skips_completed_work(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def tracking_embedder(texts):
        calls.append(list(texts))
        return deterministic_project(texts, dimension=PINNED_DIMENSION)

    chunks = _sample_chunks() + [_third_chunk()]
    ckpt = tmp_path / "embed.ckpt.json"
    config = fixture_embedding_config(batch_size=8)
    first = generate_open_us_law_embeddings(
        chunks[:2],
        config=config,
        embedder=tracking_embedder,
        checkpoint_path=ckpt,
        device_probe=_cpu_probe,
    )
    assert ckpt.is_file()
    assert len(first.embeddings) == 2
    assert set(first.executed_chunk_cids) == set(first.admitted_chunk_cids)
    first_texts = [text for batch in calls for text in batch]
    assert first_texts == [chunk["text"] for chunk in chunks[:2]]

    calls.clear()
    second = generate_open_us_law_embeddings(
        chunks,
        config=config,
        embedder=tracking_embedder,
        checkpoint_path=ckpt,
        resume=True,
        device_probe=_cpu_probe,
    )
    executed_texts = [text for batch in calls for text in batch]
    assert executed_texts == [chunks[2]["text"]]
    assert len(second.embeddings) == 3
    assert set(second.resumed_chunk_cids) == {
        chunks[0]["chunk_cid"],
        chunks[1]["chunk_cid"],
    }
    assert list(second.executed_chunk_cids) == [chunks[2]["chunk_cid"]]
    stored = load_checkpoint(ckpt)
    assert stored.config_digest == config.digest
    assert stored.schema_version == CHECKPOINT_SCHEMA_VERSION
    assert set(stored.completed_chunk_cids) == set(second.embeddings)


def test_checkpoint_config_mismatch_fails_closed(tmp_path: Path) -> None:
    ckpt = tmp_path / "embed.ckpt.json"
    generate_open_us_law_embeddings(
        _sample_chunks(),
        config=fixture_embedding_config(precision="fp32"),
        checkpoint_path=ckpt,
        device_probe=_cpu_probe,
    )
    with pytest.raises(EmbeddingCheckpointError, match="config_digest"):
        generate_open_us_law_embeddings(
            _sample_chunks(),
            config=fixture_embedding_config(precision="fp16"),
            checkpoint_path=ckpt,
            resume=True,
            device_probe=_cpu_probe,
        )


def test_checkpoint_input_hash_drift_fails_closed(tmp_path: Path) -> None:
    ckpt = tmp_path / "embed.ckpt.json"
    config = fixture_embedding_config()
    generate_open_us_law_embeddings(
        _sample_chunks(),
        config=config,
        checkpoint_path=ckpt,
        device_probe=_cpu_probe,
    )
    drifted = _sample_chunks()
    drifted[0] = dict(drifted[0], text="changed statutory text must not reuse vector")
    with pytest.raises(EmbeddingCheckpointError, match="input hash"):
        generate_open_us_law_embeddings(
            drifted,
            config=config,
            checkpoint_path=ckpt,
            resume=True,
            device_probe=_cpu_probe,
        )


def test_checkpoint_is_written_atomically_with_vectors(tmp_path: Path) -> None:
    ckpt = tmp_path / "nested" / "embed.ckpt.json"
    result = generate_open_us_law_embeddings(
        _sample_chunks(),
        config=fixture_embedding_config(batch_size=1),
        checkpoint_path=ckpt,
        device_probe=_cpu_probe,
    )
    payload = json.loads(ckpt.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["config_digest"] == result.config.digest
    assert set(payload["completed_chunk_cids"]) == set(result.embeddings)
    for cid, rec in result.embeddings.items():
        stored = payload["completed"][cid]
        assert stored["input_hash"] == rec.input_hash
        assert stored["embedding"] == list(rec.embedding)


# ---------------------------------------------------------------------------
# No 100,000-chunk ceiling
# ---------------------------------------------------------------------------


def test_no_per_call_ceiling_can_truncate_exact_51_seed() -> None:
    assert PER_CALL_CHUNK_CEILING is None
    assert_no_truncating_chunk_ceiling()
    assert_chunk_stream_unbounded(0)
    assert_chunk_stream_unbounded(100_001)
    assert_chunk_stream_unbounded(EXACT_51_SEED_ROW_LOWER_BOUND)
    assert_chunk_stream_unbounded(EXACT_51_SEED_ROW_LOWER_BOUND + 1)
    # Streaming iterator path does not require a Sequence with a known len.
    streamed = list(iter_admitted_chunks(iter(_sample_chunks())))
    assert len(streamed) == 2


def test_generate_accepts_iterator_without_precounting() -> None:
    result = generate_open_us_law_embeddings(
        iter(_sample_chunks()),
        config=fixture_embedding_config(),
        device_probe=_cpu_probe,
    )
    assert len(result.embeddings) == 2


def test_missing_vector_fails_closed_when_not_allowed() -> None:
    def short_embedder(texts):
        return [[0.1] * PINNED_DIMENSION]

    with pytest.raises(MissingVectorError):
        generate_open_us_law_embeddings(
            _sample_chunks(),
            config=default_embedding_config(),
            embedder=short_embedder,
            device_probe=_cpu_probe,
        )


def test_batching_covers_all_chunks() -> None:
    result = generate_open_us_law_embeddings(
        _sample_chunks(),
        config=fixture_embedding_config(batch_size=1),
        device_probe=_cpu_probe,
    )
    assert result.batch_count == 2
    assert len(result.embeddings) == 2


def test_generator_class_matches_function() -> None:
    gen = OpenUsLawEmbeddingGenerator(
        fixture_embedding_config(), device_probe=_cpu_probe
    )
    result = gen.generate(_sample_chunks())
    assert isinstance(result, EmbeddingGenerationResult)
    assert len(result.embeddings) == 2
    compact = result.to_dict(include_vectors=False)
    assert "embeddings" not in compact
    assert set(compact["embedding_keys"]) == set(result.embeddings)
    assert compact["authorizing_for_release"] is False


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def test_on_disk_receipt_matches_builder_and_cannot_authorize() -> None:
    path = default_embedding_receipt_path()
    assert path.is_file()
    assert path.as_posix().endswith("docs/reports/open_us_law_reindex/embedding_receipt.json")
    on_disk = load_embedding_receipt(path)
    built = build_embedding_receipt()
    assert on_disk["task_id"] == TASK_ID
    assert on_disk["goal_id"] == GOAL_ID
    assert on_disk["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert on_disk["receipt_sha256"] == built["receipt_sha256"]
    assert on_disk == built
    assert_embedding_receipt(on_disk)
    assert on_disk["authorizing_for_release"] is False
    assert on_disk["authorizing_for_publication"] is False
    assert on_disk["projection_fallback_authorizes_release"] is False
    assert on_disk["real_sentence_transformers_required"] is True
    assert on_disk["proves_software_contract_only"] is True
    assert on_disk["backend"]["default"] == "sentence_transformers"
    assert on_disk["per_call_chunk_ceiling"] is None
    pin = on_disk["model_pin"]
    assert pin["model_id"] == PINNED_MODEL_ID
    assert pin["model_revision"] == PINNED_MODEL_REVISION
    assert pin["dimension"] == 384
    assert pin["pooling"] == "mean"
    assert pin["normalization"] == "l2"
    assert pin["max_tokens"] == 512
    assert on_disk["acceptance"]["real_512_token_truncation"] is True
    assert on_disk["acceptance"]["projection_fallback_cannot_authorize_release"] is True
    assert on_disk["checks"]["demo_projection_blocked_from_release"] is True
    assert on_disk["checks"]["input_hashes_present"] is True
    assert "HF_TOKEN" not in json.dumps(on_disk)
    assert "secret" not in json.dumps(on_disk).lower()


def test_receipt_assert_rejects_projection_authorization() -> None:
    payload = build_embedding_receipt()
    payload["authorizing_for_release"] = True
    with pytest.raises(ProjectionReleaseAuthorizationError):
        assert_embedding_receipt(payload)
    payload = build_embedding_receipt()
    payload["projection_fallback_authorizes_release"] = True
    with pytest.raises(ProjectionReleaseAuthorizationError):
        assert_embedding_receipt(payload)
    payload = build_embedding_receipt()
    payload["model_pin"] = dict(payload["model_pin"], model_id="unknown")
    with pytest.raises(UnpinnedModelError):
        assert_embedding_receipt(payload)


def test_write_embedding_receipt_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "embedding_receipt.json"
    written = write_embedding_receipt(target)
    assert written == target
    loaded = load_embedding_receipt(target)
    assert_embedding_receipt(loaded)
    assert loaded["receipt_sha256"] == build_embedding_receipt()["receipt_sha256"]
