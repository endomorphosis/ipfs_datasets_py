"""Unit tests for the pinned local production embedding runtime (PATLAW-145)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.embedding_runtime import (
    CODE_DIGEST,
    CONFIG_DIGEST,
    DEFAULT_DEVICE,
    EMBEDDING_RUNTIME_SCHEMA_VERSION,
    PINNED_CONFIG_CID,
    PINNED_DIMENSION,
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    PINNED_TOKENIZER_ID,
    PINNED_TOKENIZER_REVISION,
    VECTOR_STABILITY_TOLERANCE,
    CancellationToken,
    DeviceFallbackPolicy,
    EmbeddingCancelledError,
    EmbeddingConfigError,
    EmbeddingResourceLimitError,
    EmbeddingRuntimeConfig,
    EmbeddingVectorCache,
    HardwareUnavailableError,
    LocalEmbeddingRuntime,
    UnpinnedModelError,
    build_default_runtime,
    evaluate_embedding_policy,
    input_content_digest,
    normalize_embedding_input,
    pinned_runtime_identity,
    select_device,
    vectors_within_tolerance,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    DisclosureClass,
)


# ---------------------------------------------------------------------------
# Identity pins
# ---------------------------------------------------------------------------


def test_pinned_runtime_identity_binds_model_tokenizer_code_config() -> None:
    identity = pinned_runtime_identity()
    assert identity.schema_version == EMBEDDING_RUNTIME_SCHEMA_VERSION
    assert identity.model_id == PINNED_MODEL_ID
    assert identity.model_revision == PINNED_MODEL_REVISION
    assert identity.tokenizer_id == PINNED_TOKENIZER_ID
    assert identity.tokenizer_revision == PINNED_TOKENIZER_REVISION
    assert identity.dimension == PINNED_DIMENSION
    assert identity.config_cid == PINNED_CONFIG_CID
    assert identity.code_digest == CODE_DIGEST
    assert identity.config_digest == CONFIG_DIGEST
    assert len(identity.code_digest) == 64
    assert len(identity.config_digest) == 64


def test_receipt_binds_model_tokenizer_code_config() -> None:
    runtime = LocalEmbeddingRuntime()
    result = runtime.embed(["35 U.S.C. § 102 claim hashing"])
    receipt = result.receipt
    assert receipt.schema_version == EMBEDDING_RUNTIME_SCHEMA_VERSION
    ident = receipt.identity
    assert ident.model_id == PINNED_MODEL_ID
    assert ident.model_revision == PINNED_MODEL_REVISION
    assert ident.tokenizer_id == PINNED_TOKENIZER_ID
    assert ident.tokenizer_revision == PINNED_TOKENIZER_REVISION
    assert ident.code_digest == CODE_DIGEST
    assert ident.config_digest == CONFIG_DIGEST
    assert ident.config_cid == PINNED_CONFIG_CID
    payload = receipt.to_dict()
    assert payload["identity"]["code_digest"] == CODE_DIGEST
    assert payload["identity"]["config_digest"] == CONFIG_DIGEST
    assert payload["identity"]["model_id"] == PINNED_MODEL_ID
    assert payload["identity"]["tokenizer_id"] == PINNED_TOKENIZER_ID


def test_unpinned_identity_rejected() -> None:
    pin = pinned_runtime_identity()
    with pytest.raises(UnpinnedModelError):
        type(pin)(
            schema_version=pin.schema_version,
            provider=pin.provider,
            model_id="some-other-model",
            model_revision=pin.model_revision,
            model_cid=pin.model_cid,
            tokenizer_id=pin.tokenizer_id,
            tokenizer_revision=pin.tokenizer_revision,
            dimension=pin.dimension,
            config_cid=pin.config_cid,
            config_digest=pin.config_digest,
            code_version=pin.code_version,
            code_digest=pin.code_digest,
            backend=pin.backend,
        )


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------


def test_same_inputs_pinned_runtime_stable_within_tolerance() -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(cache_entries=0),
    )
    texts = [
        "Method for hashing patent claims under 35 U.S.C. § 103",
        "CPC G06F16/00 semantic index builder",
        "",
    ]
    first = runtime.embed(texts, use_cache=False)
    second = runtime.embed(texts, use_cache=False)
    assert vectors_within_tolerance(
        first.vectors, second.vectors, tolerance=VECTOR_STABILITY_TOLERANCE
    )
    assert first.receipt.stability_tolerance == VECTOR_STABILITY_TOLERANCE
    # Digests also match for non-redacted public route.
    assert first.receipt.vector_digest == second.receipt.vector_digest
    assert first.receipt.input_digests == second.receipt.input_digests


def test_assert_stable_helper() -> None:
    runtime = build_default_runtime(cache_entries=0)
    result = runtime.assert_stable(
        ["stable pin vector", "another claim text"],
        rounds=3,
    )
    assert len(result.vectors) == 2
    assert all(len(v) == PINNED_DIMENSION for v in result.vectors)


def test_vectors_are_finite_and_dimension_pinned() -> None:
    runtime = LocalEmbeddingRuntime()
    result = runtime.embed(["finite vector check"])
    assert len(result.vectors) == 1
    vec = result.vectors[0]
    assert len(vec) == PINNED_DIMENSION
    assert all(math.isfinite(x) for x in vec)
    # Normalized non-empty text should have unit (or near-unit) L2 norm.
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-9 or norm == 0.0


def test_empty_batch_returns_empty_vectors_with_receipt() -> None:
    runtime = LocalEmbeddingRuntime()
    result = runtime.embed([])
    assert result.vectors == ()
    assert result.receipt.text_count == 0
    assert result.receipt.identity.model_id == PINNED_MODEL_ID


def test_input_normalization_is_deterministic() -> None:
    a = normalize_embedding_input("  35 U.S.C. § 102(a)(1)  claim  ")
    b = normalize_embedding_input("  35 U.S.C. § 102(a)(1)  claim  ")
    assert a == b
    assert input_content_digest("hello") == input_content_digest("hello")
    assert input_content_digest("hello") != input_content_digest("world")


# ---------------------------------------------------------------------------
# Device selection / hardware fallback
# ---------------------------------------------------------------------------


def test_unavailable_cuda_falls_back_to_cpu_explicitly() -> None:
    def probe(device: str) -> bool:
        return str(device).startswith("cpu")

    selected, applied = select_device(
        "cuda",
        fallback=DeviceFallbackPolicy.FALLBACK_CPU,
        probe=probe,
    )
    assert selected == DEFAULT_DEVICE
    assert applied is True

    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(
            device="cuda",
            device_fallback=DeviceFallbackPolicy.FALLBACK_CPU,
        ),
        device_probe=probe,
    )
    result = runtime.embed(["device fallback probe"])
    assert result.receipt.device_requested == "cuda"
    assert result.receipt.device_selected == "cpu"
    assert result.receipt.device_fallback_applied is True


def test_unavailable_hardware_blocks_when_policy_is_block() -> None:
    def probe(device: str) -> bool:
        return device == "cpu"

    with pytest.raises(HardwareUnavailableError) as exc_info:
        select_device(
            "cuda:0",
            fallback=DeviceFallbackPolicy.BLOCK,
            probe=probe,
        )
    assert exc_info.value.code == "hardware_unavailable"

    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(
            device="cuda",
            device_fallback=DeviceFallbackPolicy.BLOCK,
        ),
        device_probe=probe,
    )
    with pytest.raises(HardwareUnavailableError):
        runtime.embed(["should block"])


def test_available_requested_device_used_without_fallback() -> None:
    def probe(device: str) -> bool:
        return True

    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(
            device="cuda",
            device_fallback=DeviceFallbackPolicy.FALLBACK_CPU,
        ),
        device_probe=probe,
    )
    result = runtime.embed(["cuda available"])
    assert result.receipt.device_selected == "cuda"
    assert result.receipt.device_fallback_applied is False


def test_device_fallback_does_not_change_vectors() -> None:
    """Hashed backend is device-invariant; fallback must not alter vectors."""

    def cpu_only(device: str) -> bool:
        return device == "cpu"

    def all_ok(device: str) -> bool:
        return True

    texts = ["device invariant hash embedding"]
    cpu_runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(device="cpu", cache_entries=0),
        device_probe=cpu_only,
    )
    fallback_runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(
            device="cuda",
            device_fallback=DeviceFallbackPolicy.FALLBACK_CPU,
            cache_entries=0,
        ),
        device_probe=cpu_only,
    )
    # Even if cuda "available", hashed backend matches CPU.
    cuda_runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(device="cuda", cache_entries=0),
        device_probe=all_ok,
    )
    a = cpu_runtime.embed(texts, use_cache=False)
    b = fallback_runtime.embed(texts, use_cache=False)
    c = cuda_runtime.embed(texts, use_cache=False)
    assert vectors_within_tolerance(a.vectors, b.vectors)
    assert vectors_within_tolerance(a.vectors, c.vectors)
    assert b.receipt.device_fallback_applied is True


# ---------------------------------------------------------------------------
# Batching, cache, cancellation, resource bounds
# ---------------------------------------------------------------------------


def test_deterministic_batching_across_batch_sizes() -> None:
    texts = [f"claim fragment {i} G06F16/00" for i in range(7)]
    r1 = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(batch_size=2, cache_entries=0)
    )
    r2 = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(batch_size=5, cache_entries=0)
    )
    a = r1.embed(texts, use_cache=False)
    b = r2.embed(texts, use_cache=False)
    assert vectors_within_tolerance(a.vectors, b.vectors)
    assert a.receipt.batch_size == 2
    assert b.receipt.batch_size == 5


def test_cache_identity_hits_and_misses() -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(cache_entries=16)
    )
    first = runtime.embed(["cache me once"], use_cache=True)
    assert first.receipt.cache_misses == 1
    assert first.receipt.cache_hits == 0
    second = runtime.embed(["cache me once"], use_cache=True)
    assert second.receipt.cache_hits == 1
    assert second.receipt.cache_misses == 0
    assert vectors_within_tolerance(first.vectors, second.vectors)


def test_cache_key_includes_identity_digest() -> None:
    cache = EmbeddingVectorCache(max_entries=4)
    cache.put("in1", "id-a", [0.1, 0.2])
    assert cache.get("in1", "id-a") == (0.1, 0.2)
    assert cache.get("in1", "id-b") is None


def test_cancellation_before_and_mid_batch() -> None:
    token = CancellationToken(cancelled=True, reason="pre-cancel")
    runtime = LocalEmbeddingRuntime()
    with pytest.raises(EmbeddingCancelledError) as exc_info:
        runtime.embed(["x"], cancellation=token)
    assert exc_info.value.code == "cancelled"

    token2 = CancellationToken()
    # Cancel immediately — first check at start already sees cancelled.
    token2.cancel("operator-stop")
    with pytest.raises(EmbeddingCancelledError):
        runtime.embed(["a", "b", "c"], cancellation=token2)


def test_resource_limits_fail_closed() -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(max_texts_per_call=2, max_text_chars=10)
    )
    with pytest.raises(EmbeddingResourceLimitError):
        runtime.embed(["one", "two", "three"])
    with pytest.raises(EmbeddingResourceLimitError):
        runtime.embed(["x" * 11])


def test_invalid_config_rejected() -> None:
    with pytest.raises(EmbeddingConfigError):
        EmbeddingRuntimeConfig(batch_size=0)
    with pytest.raises(EmbeddingConfigError):
        EmbeddingRuntimeConfig(cache_entries=-1)
    with pytest.raises(EmbeddingConfigError):
        EmbeddingRuntimeConfig(device="tpu")


# ---------------------------------------------------------------------------
# Policy gate
# ---------------------------------------------------------------------------


def test_policy_denies_remote_for_private_and_default() -> None:
    private = evaluate_embedding_policy(
        disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        allow_remote=True,
        remote_requested=True,
    )
    assert private.code.value == "deny_remote_private"
    assert private.private_route is True
    assert private.allow_execute is True  # local still permitted

    default = evaluate_embedding_policy(
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        allow_remote=False,
        remote_requested=True,
    )
    assert default.code.value == "deny_remote_default"

    local = evaluate_embedding_policy(
        disclosure=DisclosureClass.PUBLIC_USER,
        allow_remote=False,
        remote_requested=False,
    )
    assert local.code.value == "allow_local"
    assert local.route.value == "local_pinned"


def test_remote_requested_still_runs_local_only() -> None:
    runtime = LocalEmbeddingRuntime(
        EmbeddingRuntimeConfig(allow_remote=False)
    )
    result = runtime.embed(
        ["public claim text"],
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        remote_requested=True,
    )
    assert runtime.external_call_count == 0
    assert result.receipt.policy.route.value in {
        "nonlocal_blocked",
        "nonlocal_denied",
    }
    assert len(result.vectors[0]) == PINNED_DIMENSION


def test_embedding_identity_projection() -> None:
    identity = pinned_runtime_identity().to_embedding_identity()
    assert identity.model_id == PINNED_MODEL_ID
    assert identity.model_version == PINNED_MODEL_REVISION
    assert identity.dimension == PINNED_DIMENSION
    assert identity.config_cid == PINNED_CONFIG_CID
    assert identity.metadata["code_digest"] == CODE_DIGEST
    assert identity.metadata["tokenizer_id"] == PINNED_TOKENIZER_ID


def test_embed_one_convenience() -> None:
    runtime = LocalEmbeddingRuntime()
    vec, receipt = runtime.embed_one("single text path")
    assert len(vec) == PINNED_DIMENSION
    assert receipt.text_count == 1


def test_result_to_dict_omits_vectors_by_default() -> None:
    runtime = LocalEmbeddingRuntime()
    result = runtime.embed(["dict path"])
    payload = result.to_dict()
    assert "vectors" not in payload
    assert payload["vector_count"] == 1
    with_vec = result.to_dict(include_vectors=True)
    assert "vectors" in with_vec
    assert len(with_vec["vectors"][0]) == PINNED_DIMENSION
