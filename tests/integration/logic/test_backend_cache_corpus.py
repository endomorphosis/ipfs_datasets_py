"""Integration tests for VerificationCacheProtocol@1 and BackendProofCorpusStore@1.

Acceptance (LFV-G062 / LFV-025):

* Keys bind IR/property/assumptions, translation, backend/binary/version/config,
  resources, tree, and policy.
* Single-flight and negative TTL behavior are deterministic.
* Stale and tampered entries reject fail-closed.
* Cache never raises authority.
* Validated attempt/proof/counterexample receipts bridge into the immutable
  backend proof corpus without forcing one storage implementation.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.cache_protocol import (
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION,
    CacheLookupReason,
    CachePolarity,
    ExactVerificationCache,
    VerificationCacheAuthorityError,
    VerificationCacheEntry,
    VerificationCacheError,
    VerificationCacheIntegrityError,
    VerificationCacheKey,
    build_verification_cache_key,
    content_digest,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage
from ipfs_datasets_py.logic.proof_corpus.backend_store import (
    BACKEND_PROOF_CORPUS_STORE_INTERFACE,
    BACKEND_PROOF_CORPUS_STORE_SCHEMA_VERSION,
    BackendCorpusRecord,
    BackendProofCorpusError,
    BackendProofCorpusIntegrityError,
    BackendProofCorpusStore,
    BackendReceiptKind,
    InMemoryBackendCorpusStorage,
    build_backend_proof_corpus_store,
    receipt_kind_for_status,
)


def _theorem(
    *,
    status: ResultStatus = ResultStatus.PROVED,
    authority: ResultAuthority = ResultAuthority.THEOREM,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    result_id: str = "result:theorem-1",
    backend_id: str = "solver.z3",
    backend_version: str = "4.12.0",
    **changes: Any,
) -> TheoremResult:
    fields: dict[str, Any] = {
        "result_id": result_id,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "authority": authority,
        "status": status,
        "assumptions": ("assumption:int",),
        "bounds": ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": translation_ceiling,
        "usage": ResourceUsage(
            elapsed_ms=10,
            steps=5,
            peak_memory_bytes=512,
            output_bytes=64,
        ),
        "witness": {"kind": "proof"},
        "diagnostics": (),
        "reason": "",
        "metadata": {},
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _sat(
    *,
    status: ResultStatus = ResultStatus.SATISFIABLE,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.BOUNDED,
) -> SatisfiabilityResult:
    return SatisfiabilityResult(
        result_id="result:sat-1",
        backend_id="solver.cvc5",
        backend_version="1.1.0",
        authority=ResultAuthority.SATISFIABILITY,
        status=status,
        assumptions=("assumption:model",),
        bounds=ExecutionBounds(
            timeout_ms=500,
            max_steps=50,
            max_memory_bytes=2048,
            max_output_bytes=1024,
        ),
        translation_ceiling=translation_ceiling,
        usage=ResourceUsage(
            elapsed_ms=5,
            steps=3,
            peak_memory_bytes=256,
            output_bytes=32,
        ),
        witness={"model": {"x": 1}},
    )


def _key(**overrides: Any) -> VerificationCacheKey:
    base = dict(
        ir={"formula": "(assert (> x 0))"},
        property_value={"property_id": "prop.safety"},
        assumptions=("assumption:int", "assumption:precondition"),
        translation={
            "receipt_id": "tr:1",
            "preservation": "equisatisfiable",
        },
        backend_id="solver.z3",
        backend_binary={"path": "/usr/bin/z3", "sha256": "abc"},
        backend_version="4.12.0",
        backend_config={"logic": "QF_LIA", "timeout_ms": 1000},
        resources={"timeout_ms": 1000, "max_memory_bytes": 4096},
        tree={"tree_id": "tree:deadbeef", "commit": "abc123"},
        policy={"mode": "production", "require_kernel": False},
    )
    base.update(overrides)
    return build_verification_cache_key(**base)


# ---------------------------------------------------------------------------
# Interface pinning
# ---------------------------------------------------------------------------


def test_interfaces_and_schema_versions_are_pinned() -> None:
    cache = ExactVerificationCache()
    store = BackendProofCorpusStore()
    assert cache.interface == VERIFICATION_CACHE_PROTOCOL_INTERFACE
    assert cache.schema_version == VERIFICATION_CACHE_PROTOCOL_SCHEMA_VERSION
    assert VERIFICATION_CACHE_PROTOCOL_INTERFACE == "VerificationCacheProtocol@1"
    assert store.interface == BACKEND_PROOF_CORPUS_STORE_INTERFACE
    assert store.schema_version == BACKEND_PROOF_CORPUS_STORE_SCHEMA_VERSION
    assert BACKEND_PROOF_CORPUS_STORE_INTERFACE == "BackendProofCorpusStore@1"
    assert store.cache_interface == VERIFICATION_CACHE_PROTOCOL_INTERFACE


# ---------------------------------------------------------------------------
# Key binding dimensions
# ---------------------------------------------------------------------------


def test_cache_key_binds_all_required_dimensions() -> None:
    key = _key()
    payload = key.to_dict()
    required = {
        "ir_digest",
        "property_digest",
        "assumptions_digest",
        "translation_digest",
        "backend_id",
        "backend_binary_digest",
        "backend_version",
        "backend_config_digest",
        "resources_digest",
        "tree_digest",
        "policy_digest",
    }
    assert required.issubset(payload)
    for field_name in required:
        assert payload[field_name]
    # Round-trip preserves digest identity.
    restored = VerificationCacheKey.from_dict(payload)
    assert restored.digest == key.digest
    assert restored.cache_key == key.digest


@pytest.mark.parametrize(
    "dimension,override",
    [
        ("ir", {"ir": {"formula": "(assert false)"}}),
        ("property", {"property_value": {"property_id": "prop.liveness"}}),
        ("assumptions", {"assumptions": ("assumption:other",)}),
        ("translation", {"translation": {"receipt_id": "tr:2"}}),
        ("backend_id", {"backend_id": "solver.cvc5"}),
        ("backend_binary", {"backend_binary": {"path": "/opt/z3", "sha256": "def"}}),
        ("backend_version", {"backend_version": "4.13.0"}),
        ("backend_config", {"backend_config": {"logic": "QF_NIA"}}),
        ("resources", {"resources": {"timeout_ms": 50}}),
        ("tree", {"tree": {"tree_id": "tree:other"}}),
        ("policy", {"policy": {"mode": "dev"}}),
    ],
)
def test_each_key_dimension_change_produces_distinct_digest(
    dimension: str, override: dict[str, Any]
) -> None:
    base = _key()
    other = _key(**override)
    assert base.digest != other.digest, f"{dimension} change must alter key digest"


def test_stable_key_digest_is_deterministic() -> None:
    first = _key()
    second = _key()
    assert first.digest == second.digest
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# Exact cache hit / miss / put
# ---------------------------------------------------------------------------


def test_exact_cache_put_and_hit_preserves_authority() -> None:
    cache = ExactVerificationCache()
    key = _key()
    result = _theorem()
    stored = cache.put_result(key, result)
    assert stored.reason is CacheLookupReason.STORED
    assert stored.entry is not None
    assert stored.entry.evidence_authority is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    assert stored.entry.result_authority is ResultAuthority.THEOREM
    assert stored.entry.polarity is CachePolarity.POSITIVE

    lookup = cache.lookup(key)
    assert lookup.hit and lookup.usable
    assert lookup.reason is CacheLookupReason.HIT
    assert lookup.entry is not None
    assert lookup.entry.entry_digest == stored.entry.entry_digest
    assert lookup.entry.evidence_authority is result.translation_ceiling


def test_cache_miss_on_unknown_key() -> None:
    cache = ExactVerificationCache()
    lookup = cache.lookup(_key())
    assert not lookup.hit
    assert not lookup.usable
    assert lookup.reason is CacheLookupReason.MISS
    assert cache.get(_key()) is None


# ---------------------------------------------------------------------------
# Authority: never raise
# ---------------------------------------------------------------------------


def test_cache_rejects_evidence_authority_above_translation_ceiling() -> None:
    cache = ExactVerificationCache()
    key = _key()
    result = _theorem(translation_ceiling=EvidenceAuthority.BOUNDED)
    with pytest.raises(VerificationCacheAuthorityError, match="cannot raise"):
        VerificationCacheEntry.from_typed_result(
            key,
            result,
            evidence_authority=EvidenceAuthority.AUTHORITATIVE,
        )
    with pytest.raises(VerificationCacheAuthorityError, match="cannot raise"):
        cache.put_result(
            key,
            result,
            evidence_authority=EvidenceAuthority.AUTHORITATIVE,
        )


def test_lookup_rejects_when_stored_authority_exceeds_caller_ceiling() -> None:
    cache = ExactVerificationCache()
    key = _key()
    cache.put_result(
        key,
        _theorem(translation_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE),
    )
    lookup = cache.lookup(
        key, max_evidence_authority=EvidenceAuthority.BOUNDED
    )
    assert lookup.hit
    assert not lookup.usable
    assert lookup.reason is CacheLookupReason.INSUFFICIENT_AUTHORITY


def test_require_authority_at_most_on_entry() -> None:
    key = _key()
    entry = VerificationCacheEntry.from_typed_result(
        key,
        _theorem(translation_ceiling=EvidenceAuthority.BOUNDED),
    )
    entry.require_authority_at_most(EvidenceAuthority.BOUNDED)
    with pytest.raises(VerificationCacheAuthorityError):
        entry.require_authority_at_most(EvidenceAuthority.ADVISORY)


def test_result_authority_mismatch_is_unusable() -> None:
    cache = ExactVerificationCache()
    key = _key()
    cache.put_result(key, _theorem())
    lookup = cache.lookup(
        key, require_result_authority=ResultAuthority.SATISFIABILITY
    )
    assert lookup.hit
    assert not lookup.usable
    assert lookup.reason is CacheLookupReason.AUTHORITY_MISMATCH


# ---------------------------------------------------------------------------
# Negative TTL and positive TTL
# ---------------------------------------------------------------------------


def test_negative_ttl_expires_before_positive_ttl() -> None:
    cache = ExactVerificationCache(
        positive_ttl_seconds=1000.0,
        negative_ttl_seconds=10.0,
    )
    key = _key()
    t0 = 1_000_000.0
    cache.put_result(
        key,
        _theorem(status=ResultStatus.TIMEOUT),
        now=t0,
    )
    # Still within negative TTL.
    hit = cache.lookup(key, now=t0 + 5.0)
    assert hit.usable
    assert hit.reason is CacheLookupReason.NEGATIVE_HIT
    assert hit.entry is not None
    assert hit.entry.polarity is CachePolarity.NEGATIVE

    # Past negative TTL but well within a positive TTL window.
    expired = cache.lookup(key, now=t0 + 11.0)
    assert not expired.usable
    assert expired.reason is CacheLookupReason.EXPIRED


def test_positive_outcome_survives_beyond_negative_ttl_window() -> None:
    cache = ExactVerificationCache(
        positive_ttl_seconds=1000.0,
        negative_ttl_seconds=10.0,
    )
    key = _key()
    t0 = 2_000_000.0
    cache.put_result(key, _theorem(status=ResultStatus.PROVED), now=t0)
    still = cache.lookup(key, now=t0 + 50.0)
    assert still.usable
    assert still.reason is CacheLookupReason.HIT


def test_negative_ttl_cannot_exceed_positive_ttl() -> None:
    with pytest.raises(VerificationCacheError, match="negative_ttl"):
        ExactVerificationCache(
            positive_ttl_seconds=10.0,
            negative_ttl_seconds=20.0,
        )


# ---------------------------------------------------------------------------
# Tamper / stale rejection
# ---------------------------------------------------------------------------


def test_tampered_entry_rejects_on_from_dict() -> None:
    key = _key()
    entry = VerificationCacheEntry.from_typed_result(key, _theorem())
    payload = entry.to_dict()
    payload["result_payload"] = dict(payload["result_payload"])
    payload["result_payload"]["status"] = ResultStatus.DISPROVED.value
    with pytest.raises(VerificationCacheIntegrityError, match="digest mismatch"):
        VerificationCacheEntry.from_dict(payload)


def test_cache_rejects_tampered_in_memory_entry() -> None:
    cache = ExactVerificationCache()
    key = _key()
    entry = VerificationCacheEntry.from_typed_result(key, _theorem())
    cache.put(entry)
    # Manually corrupt the stored entry while keeping the digest field.
    corrupted_payload = entry.to_dict()
    corrupted_payload["status"] = ResultStatus.DISPROVED.value
    # Bypass constructor digest check by stuffing a mutated object into the map.
    with cache._lock:  # noqa: SLF001 — intentional integrity attack in test
        # Reconstruct with matching digest field but wrong body via object.__setattr__
        # is hard on frozen dataclasses; instead replace with a forged dict path:
        # put a re-built entry that lies about digest by patching after construction.
        forged = VerificationCacheEntry.from_typed_result(
            key, _theorem(status=ResultStatus.PROVED)
        )
        object.__setattr__(forged, "status", ResultStatus.DISPROVED)
        cache._entries[key.digest] = forged  # noqa: SLF001

    lookup = cache.lookup(key)
    assert not lookup.usable
    assert lookup.reason is CacheLookupReason.TAMPERED
    assert cache.stats()["tamper_rejections"] >= 1


def test_stale_key_dimension_misses() -> None:
    cache = ExactVerificationCache()
    key = _key()
    cache.put_result(key, _theorem())
    other = _key(tree={"tree_id": "tree:stale"})
    lookup = cache.lookup(other)
    assert not lookup.hit
    assert lookup.reason is CacheLookupReason.MISS


# ---------------------------------------------------------------------------
# Single-flight
# ---------------------------------------------------------------------------


def test_single_flight_coalesces_concurrent_producers() -> None:
    cache = ExactVerificationCache()
    key = _key()
    calls = {"n": 0}
    barrier = threading.Barrier(4)
    lock = threading.Lock()

    def producer() -> TheoremResult:
        with lock:
            calls["n"] += 1
        # Hold long enough for waiters to join the flight.
        time.sleep(0.05)
        return _theorem()

    def worker() -> Any:
        barrier.wait()
        return cache.get_or_compute(key, producer)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker) for _ in range(4)]
        results = [future.result(timeout=5.0) for future in futures]

    assert calls["n"] == 1
    assert all(item.usable for item in results)
    # Exactly one leader store; others share via single-flight.
    shared = [item for item in results if item.single_flight_shared]
    leaders = [item for item in results if not item.single_flight_shared]
    assert len(leaders) == 1
    assert leaders[0].reason is CacheLookupReason.STORED
    assert len(shared) == 3
    assert all(item.reason is CacheLookupReason.SINGLE_FLIGHT_SHARED for item in shared)
    digests = {item.entry.entry_digest for item in results if item.entry is not None}
    assert len(digests) == 1


def test_get_or_compute_returns_existing_hit_without_producer() -> None:
    cache = ExactVerificationCache()
    key = _key()
    cache.put_result(key, _theorem())
    calls = {"n": 0}

    def producer() -> TheoremResult:
        calls["n"] += 1
        return _theorem()

    lookup = cache.get_or_compute(key, producer)
    assert lookup.usable
    assert lookup.hit
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Backend proof corpus store
# ---------------------------------------------------------------------------


def test_corpus_stores_proof_and_counterexample_receipts() -> None:
    store = BackendProofCorpusStore()
    proof_key = _key()
    proof = store.put_proof(proof_key, _theorem(status=ResultStatus.PROVED))
    assert proof.kind is BackendReceiptKind.PROOF
    assert proof.content_digest.startswith("sha256:")
    assert proof.content_cid.startswith("backend-receipt:")

    cex_key = _key(backend_id="solver.cvc5", backend_version="1.1.0")
    cex = store.put_counterexample(
        cex_key,
        _sat(status=ResultStatus.SATISFIABLE),
    )
    assert cex.kind is BackendReceiptKind.COUNTEREXAMPLE

    loaded = store.get(proof.content_digest)
    assert loaded.content_digest == proof.content_digest
    assert loaded.key.digest == proof_key.digest
    assert store.get_by_key(proof_key) is not None
    assert store.get_by_key(proof_key).content_digest == proof.content_digest

    proofs = store.list_by_kind(BackendReceiptKind.PROOF)
    counterexamples = store.list_by_kind(BackendReceiptKind.COUNTEREXAMPLE)
    assert len(proofs) == 1
    assert len(counterexamples) == 1


def test_corpus_stores_attempt_and_negative_receipts() -> None:
    store = BackendProofCorpusStore()
    key = _key()
    attempt = store.put_attempt(
        key, _theorem(status=ResultStatus.TIMEOUT)
    )
    # put_attempt forces ATTEMPT kind even for timeout statuses.
    assert attempt.kind is BackendReceiptKind.ATTEMPT

    entry = VerificationCacheEntry.from_typed_result(
        key, _theorem(status=ResultStatus.UNAVAILABLE)
    )
    negative = store.put_from_cache_entry(entry)
    assert negative.kind is BackendReceiptKind.NEGATIVE


def test_corpus_rejects_put_proof_for_non_proof_status() -> None:
    store = BackendProofCorpusStore()
    with pytest.raises(BackendProofCorpusError, match="not a proof"):
        store.put_proof(_key(), _theorem(status=ResultStatus.TIMEOUT))


def test_corpus_tampered_storage_rejects() -> None:
    storage = InMemoryBackendCorpusStorage()
    store = BackendProofCorpusStore(storage=storage)
    key = _key()
    record = store.put_from_result(key, _theorem())
    storage_key = store._storage_key(record.content_digest)  # noqa: SLF001
    raw = storage.get_bytes(storage_key)
    assert raw is not None
    payload = json.loads(raw.decode("utf-8"))
    payload["status"] = ResultStatus.DISPROVED.value
    storage.put_bytes(storage_key, json.dumps(payload).encode("utf-8"))
    with pytest.raises(BackendProofCorpusIntegrityError):
        store.get(record.content_digest)


def test_corpus_never_raises_authority_on_from_result() -> None:
    store = BackendProofCorpusStore()
    key = _key()
    result = _theorem(translation_ceiling=EvidenceAuthority.BOUNDED)
    with pytest.raises(BackendProofCorpusError, match="cannot admit"):
        store.put_from_result(
            key,
            result,
            evidence_authority=EvidenceAuthority.AUTHORITATIVE,
        )


# ---------------------------------------------------------------------------
# Cache ↔ corpus bridge
# ---------------------------------------------------------------------------


def test_bridge_cache_hit_persists_immutable_record() -> None:
    cache = ExactVerificationCache()
    store = BackendProofCorpusStore(cache=cache)
    key = _key()
    cache.put_result(key, _theorem())

    record = store.bridge_cache_hit(cache, key)
    assert record is not None
    assert record.kind is BackendReceiptKind.PROOF
    assert record.source_entry_digest
    # Second bridge is idempotent for identical content.
    again = store.bridge_cache_hit(cache, key)
    assert again is not None
    assert again.content_digest == record.content_digest
    assert store.stats()["writes"] == 1


def test_bridge_cache_miss_returns_none() -> None:
    cache = ExactVerificationCache()
    store = BackendProofCorpusStore()
    assert store.bridge_cache_hit(cache, _key()) is None


def test_factory_wires_default_cache() -> None:
    store = build_backend_proof_corpus_store(with_default_cache=True)
    assert store._cache is not None  # noqa: SLF001
    key = _key()
    assert isinstance(store._cache, ExactVerificationCache)
    store._cache.put_result(key, _theorem())  # noqa: SLF001
    record = store.bridge_cache_hit(None, key)
    assert record is not None


def test_storage_backend_is_injectable() -> None:
    """Corpus does not force one storage implementation."""

    class DictStorage:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def put_bytes(self, key: str, payload: bytes) -> None:
            self.data[key] = payload

        def get_bytes(self, key: str) -> bytes | None:
            return self.data.get(key)

        def delete(self, key: str) -> bool:
            return self.data.pop(key, None) is not None

        def list_keys(self) -> list[str]:
            return list(self.data)

    custom = DictStorage()
    store = BackendProofCorpusStore(storage=custom)
    record = store.put_from_result(_key(), _theorem())
    assert any(record.content_digest in key for key in custom.data)
    loaded = store.get(record.content_digest)
    assert loaded.content_digest == record.content_digest


def test_end_to_end_get_or_compute_then_bridge() -> None:
    cache = ExactVerificationCache()
    store = build_backend_proof_corpus_store(cache=cache)
    key = _key()

    lookup = cache.get_or_compute(key, lambda: _theorem())
    assert lookup.usable
    record = store.bridge_cache_hit(cache, key)
    assert record is not None
    assert record.result_authority is ResultAuthority.THEOREM
    assert record.evidence_authority is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    # Authority ceiling still enforced on durable records.
    record.require_authority_at_most(EvidenceAuthority.INDEPENDENTLY_CHECKABLE)
    with pytest.raises(Exception, match="exceeds"):
        record.require_authority_at_most(EvidenceAuthority.NONE)


def test_receipt_kind_mapping() -> None:
    assert receipt_kind_for_status(ResultStatus.PROVED) is BackendReceiptKind.PROOF
    assert (
        receipt_kind_for_status(ResultStatus.DISPROVED)
        is BackendReceiptKind.COUNTEREXAMPLE
    )
    assert (
        receipt_kind_for_status(ResultStatus.TIMEOUT) is BackendReceiptKind.NEGATIVE
    )


def test_content_digest_helper_is_stable() -> None:
    assert content_digest({"a": 1, "b": 2}) == content_digest({"b": 2, "a": 1})
    assert content_digest({"a": 1}) != content_digest({"a": 2})


def test_invalidate_removes_cache_entry() -> None:
    cache = ExactVerificationCache()
    key = _key()
    cache.put_result(key, _theorem())
    assert cache.invalidate(key) is True
    assert cache.get(key) is None
    assert cache.invalidate(key) is False
