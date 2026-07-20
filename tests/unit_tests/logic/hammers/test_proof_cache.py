"""Trust, identity, persistence, and concurrency tests for the hammer cache."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ipfs_datasets_py.logic.hammers.proof_cache import (
    PersistentProofCache,
    ProofCacheKey,
    ProofCacheOutcome,
    ProofCacheTrustError,
    ProofTrust,
    cache_provenance_metadata,
)


def _key(**overrides):
    values = {
        "selected_premises": [{"theorem": "p", "digest": "premise-v1"}],
        "translation_version": "translator-v1",
        "solver_identities": {"z3": "4.13.3"},
        "lean_toolchain_identity": {"lean": "4.19.0", "binary": "abc"},
        "theorem_registry": {"revision": "registry-v1"},
        "policy": {"requires_reconstruction": True},
        "resource_budget": {"timeout_seconds": 5, "memory_mb": 256},
    }
    values.update(overrides)
    return ProofCacheKey.build(" theorem  notice\r\n  : True ", **values)


def test_key_is_canonical_and_covers_every_proof_input() -> None:
    key = _key()
    same = ProofCacheKey.build(
        "theorem notice\n: True",
        selected_premises=[{"digest": "premise-v1", "theorem": "p"}],
        translation_version="translator-v1",
        solver_identities={"z3": "4.13.3"},
        lean_toolchain_identity={"binary": "abc", "lean": "4.19.0"},
        theorem_registry={"revision": "registry-v1"},
        policy={"requires_reconstruction": True},
        resource_budget={"memory_mb": 256, "timeout_seconds": 5},
    )
    assert same.digest == key.digest

    dimensions = {
        "selected_premises": [{"digest": "premise-v2"}],
        "translation_version": "translator-v2",
        "solver_identities": {"z3": "4.14.0"},
        "lean_toolchain_identity": {"lean": "4.20.0"},
        "theorem_registry": {"revision": "registry-v2"},
        "policy": {"requires_reconstruction": False},
        "resource_budget": {"timeout_seconds": 6},
    }
    for name, value in dimensions.items():
        assert _key(**{name: value}).digest != key.digest


def test_unverified_atp_output_cannot_be_marked_trusted() -> None:
    with pytest.raises(ProofCacheTrustError):
        ProofCacheOutcome(
            status="proved",
            trust=ProofTrust.TRUSTED,
            payload={"solver": "z3"},
            atp_claimed_proof=True,
        )

    candidate = ProofCacheOutcome.non_trusted(
        "proved", {"solver": "z3"}, atp_claimed_proof=True
    )
    assert candidate.trusted is False


def test_persists_trusted_and_explicit_non_trusted_outcomes(tmp_path) -> None:
    path = tmp_path / "proofs.json"
    trusted_key = _key()
    candidate_key = _key(policy={"requires_reconstruction": False})
    cache = PersistentProofCache(path, max_entries=10, ttl_seconds=60)
    cache.put(trusted_key, ProofCacheOutcome.trusted_kernel("accepted", {"proof": "ok"}))
    cache.put(
        candidate_key,
        ProofCacheOutcome.non_trusted(
            "proved", {"candidate": "atp"}, atp_claimed_proof=True
        ),
    )

    restarted = PersistentProofCache(path, max_entries=10, ttl_seconds=60)
    trusted = restarted.lookup(trusted_key, require_trusted=True)
    candidate = restarted.lookup(candidate_key)
    refused = restarted.lookup(candidate_key, require_trusted=True)

    assert trusted.usable and trusted.outcome and trusted.outcome.trusted
    assert candidate.usable and candidate.outcome
    assert candidate.outcome.atp_claimed_proof is True
    assert refused.hit is True
    assert refused.usable is False
    assert refused.provenance.reason == "insufficient_trust"


def test_single_flight_coalesces_concurrent_identical_requests(tmp_path) -> None:
    cache = PersistentProofCache(tmp_path / "proofs.json")
    key = _key()
    calls = 0
    calls_lock = threading.Lock()
    ready = threading.Barrier(8)

    def produce():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return ProofCacheOutcome.trusted_kernel("accepted", {"proof": "by decide"})

    def execute():
        ready.wait()
        return cache.get_or_compute(key, produce, require_trusted=True)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: execute(), range(8)))

    assert calls == 1
    assert all(result.outcome and result.outcome.trusted for result in results)
    assert sum(result.provenance.single_flight_shared for result in results) == 7
    assert cache.stats()["single_flight_waits"] == 7


def test_changed_toolchain_misses_and_stale_entries_can_be_invalidated(tmp_path) -> None:
    cache = PersistentProofCache(tmp_path / "proofs.json")
    old = _key()
    current_identity = {"lean": "4.20.0", "binary": "new"}
    current = _key(lean_toolchain_identity=current_identity)
    cache.put(old, ProofCacheOutcome.trusted_kernel("accepted", {"proof": "old"}))

    assert cache.lookup(current).hit is False
    removed = cache.invalidate_stale_toolchains(
        solver_identities={"z3": "4.13.3"},
        lean_toolchain_identity=current_identity,
    )
    assert removed == 1
    assert cache.lookup(old).hit is False


def test_cache_provenance_is_receipt_ready(tmp_path) -> None:
    cache = PersistentProofCache(tmp_path / "proofs.json")
    result = cache.get_or_compute(
        _key(),
        lambda: ProofCacheOutcome.trusted_deterministic(
            "rejected", {"reason": "ill_formed"}, authority="parser"
        ),
    )
    metadata = cache_provenance_metadata(result)

    assert metadata["proof_cache"]["key_digest"]
    assert metadata["proof_cache"]["entry_digest"]
    assert metadata["proof_cache"]["trust"] == "trusted"
    assert metadata["proof_cache"]["reason"] == "stored"
