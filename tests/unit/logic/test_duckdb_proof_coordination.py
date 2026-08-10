"""Unit tests for the fenced single-flight proof coordinator (DQK-027).

Acceptance coverage:

* At most one valid producer publishes per proof key
* Expired fence publication is rejected
* Waiters recover after producer crash without duplicate authority
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
import threading
import time

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.logic.backends.cache_protocol import (
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    CacheLookupReason,
    CachePolarity,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.common.duckdb_proof_coordination import (
    COORDINATION_CATALOG_TABLES,
    DEFAULT_LEASE_SECONDS,
    DUCKDB_PROOF_COORDINATION_INTERFACE,
    DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION,
    AttemptStatus,
    ClaimStatus,
    CoordinationRole,
    DuckDBProofCoordinationError,
    DuckDBProofCoordinator,
    ExpiredFenceError,
    InvalidationReason,
    ProofAttemptRecord,
    ProofCoordinationTimeout,
    ProofFenceClaim,
    StaleFenceError,
    build_duckdb_proof_coordinator,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    DUCKDB_PROOF_STORE_INTERFACE,
    PROOFS_CATALOG_DDL,
    PROOFS_CATALOG_TABLES,
    DuckDBProofStore,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    build_unified_proof_key,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _theorem(
    *,
    status: ResultStatus = ResultStatus.PROVED,
    authority: ResultAuthority = ResultAuthority.THEOREM,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    result_id: str = "result:theorem-1",
    backend_id: str = "solver.z3",
    backend_version: str = "4.12.0",
    **changes,
) -> TheoremResult:
    fields = {
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


def _unified_key(**overrides):
    base = dict(
        ir={"formula": "(assert (> x 0))"},
        property_value={"property_id": "prop.safety"},
        assumptions=("assumption:int", "assumption:precondition"),
        selected_premises=("premise:nat.succ", "premise:nat.zero"),
        translator={
            "receipt_id": "tr:1",
            "preservation": "equisatisfiable",
            "version": "hammer-translator/v3",
        },
        solver_identities=(
            {"solver": "z3", "version": "4.12.0"},
            {"solver": "cvc5", "version": "1.1.0"},
        ),
        toolchain={"lean": "4.3.0", "lake": "5.0.0"},
        theorem_registry={"registry_hash": "reg:abc", "count": 12},
        policy={"mode": "production", "require_kernel": True},
        resources={"timeout_ms": 1000, "max_memory_bytes": 4096},
        tree={"tree_id": "tree:deadbeef", "commit": "abc123"},
        backend_id="solver.z3",
        backend_binary={"path": "/usr/bin/z3", "sha256": "abc"},
        backend_version="4.12.0",
        backend_config={"logic": "QF_LIA", "timeout_ms": 1000},
    )
    base.update(overrides)
    return build_unified_proof_key(**base)


def _coordinator(**kwargs) -> DuckDBProofCoordinator:
    defaults = dict(
        positive_ttl_seconds=1000.0,
        negative_ttl_seconds=30.0,
        lease_seconds=5.0,
        wait_timeout_seconds=5.0,
        poll_interval_seconds=0.01,
        outcome_handoff_seconds=2.0,
    )
    defaults.update(kwargs)
    return build_duckdb_proof_coordinator(**defaults)


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_interfaces_and_catalog_are_pinned() -> None:
    coordinator = _coordinator()
    assert coordinator.interface == DUCKDB_PROOF_COORDINATION_INTERFACE
    assert coordinator.schema_version == DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION
    assert DUCKDB_PROOF_COORDINATION_INTERFACE == "DuckDBProofCoordination@1"
    assert coordinator.store_interface == DUCKDB_PROOF_STORE_INTERFACE
    assert coordinator.cache_interface == VERIFICATION_CACHE_PROTOCOL_INTERFACE
    assert set(coordinator.catalog_tables()) == set(PROOFS_CATALOG_TABLES)
    assert "singleflight_claims" in COORDINATION_CATALOG_TABLES
    assert "invalidations" in COORDINATION_CATALOG_TABLES
    assert "CREATE TABLE IF NOT EXISTS singleflight_claims" in PROOFS_CATALOG_DDL
    assert DEFAULT_LEASE_SECONDS > 0


def test_module_import_is_inert_without_duckdb() -> None:
    import importlib

    mod = importlib.import_module(
        "ipfs_datasets_py.logic.common.duckdb_proof_coordination"
    )
    assert mod.DUCKDB_PROOF_COORDINATION_INTERFACE == "DuckDBProofCoordination@1"


def test_negative_cache_policy_describes_dual_ttl() -> None:
    coordinator = _coordinator(
        positive_ttl_seconds=100.0, negative_ttl_seconds=10.0
    )
    policy = coordinator.negative_cache_policy()
    assert policy["positive_ttl_seconds"] == 100.0
    assert policy["negative_ttl_seconds"] == 10.0
    assert ProofOutcomeKind.UNKNOWN.value in policy["negative_outcomes"]
    assert ProofOutcomeKind.ERROR.value in policy["negative_outcomes"]
    assert ProofOutcomeKind.PROOF.value in policy["positive_outcomes"]
    assert (
        coordinator.ttl_for_outcome(ProofOutcomeKind.UNKNOWN)
        == 10.0
    )
    assert coordinator.ttl_for_outcome(ProofOutcomeKind.PROOF) == 100.0


# ---------------------------------------------------------------------------
# Claim / fence basics
# ---------------------------------------------------------------------------


def test_claim_acquires_and_followers_do_not_receive_owner_token() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    leader = coordinator.claim(key, owner_id="leader-1")
    assert leader.acquired is True
    assert leader.is_leader is True
    assert leader.fence_token.startswith("fence:")
    assert leader.status is ClaimStatus.CLAIMED
    assert leader.fence_generation == 1

    follower = coordinator.claim(key, owner_id="follower-1")
    assert follower.acquired is False
    assert follower.fence_token == ""
    assert follower.fence_generation == leader.fence_generation
    assert follower.claim_id == leader.claim_id


def test_renew_extends_live_fence_and_rejects_foreign() -> None:
    clock = {"t": 1000.0}

    def now() -> float:
        return clock["t"]

    coordinator = _coordinator(clock=now, lease_seconds=10.0)
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="owner", now=1000.0)
    assert claim.expires_at == 1010.0

    clock["t"] = 1005.0
    renewed = coordinator.renew(claim, lease_seconds=10.0, now=1005.0)
    assert renewed.expires_at == 1015.0
    assert renewed.fence_token == claim.fence_token

    foreign = ProofFenceClaim(
        key_digest=claim.key_digest,
        claim_id=claim.claim_id,
        owner_id="other",
        fence_token="fence:deadbeefdeadbeefdeadbeefdeadbeef",
        fence_generation=claim.fence_generation,
        claimed_at=claim.claimed_at,
        expires_at=claim.expires_at,
        status=ClaimStatus.CLAIMED,
        acquired=True,
    )
    with pytest.raises(StaleFenceError):
        coordinator.renew(foreign, now=1006.0)


# ---------------------------------------------------------------------------
# Acceptance: at most one valid producer publishes per proof key
# ---------------------------------------------------------------------------


def test_at_most_one_valid_producer_publishes_per_proof_key() -> None:
    coordinator = _coordinator(lease_seconds=30.0, wait_timeout_seconds=10.0)
    key = _unified_key()
    calls = {"n": 0}
    barrier = threading.Barrier(8)
    results: list = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()

        def producer() -> TheoremResult:
            calls["n"] += 1
            time.sleep(0.05)
            return _theorem(result_id=f"result:call-{calls['n']}")

        result = coordinator.get_or_compute(key, producer, owner_id="worker")
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert len(results) == 8
    assert calls["n"] == 1, "exactly one producer must run"
    usable = [item for item in results if item.usable]
    assert len(usable) == 8
    entry_digests = {
        item.entry.entry_digest for item in usable if item.entry is not None
    }
    assert len(entry_digests) == 1
    producers = [
        item for item in results if item.role in {
            CoordinationRole.PRODUCER,
            CoordinationRole.RECOVERED_PRODUCER,
        }
    ]
    waiters = [item for item in results if item.role is CoordinationRole.WAITER]
    assert len(producers) == 1
    assert len(waiters) == 7
    assert all(item.single_flight_shared for item in waiters)

    # Store holds a single authoritative entry for the key.
    stored = coordinator.get(key)
    assert stored is not None
    assert stored.outcome is ProofOutcomeKind.PROOF


def test_second_publish_from_same_generation_after_success_is_stale() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="solo")
    first = coordinator.publish(claim, _theorem(), key=key)
    assert first.usable
    with pytest.raises(StaleFenceError):
        coordinator.publish(claim, _theorem(result_id="result:dup"), key=key)


def test_follower_cannot_publish() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    leader = coordinator.claim(key, owner_id="leader")
    follower = coordinator.claim(key, owner_id="follower")
    assert not follower.acquired
    with pytest.raises(StaleFenceError):
        coordinator.publish(follower, _theorem(), key=key)
    # Leader still can.
    result = coordinator.publish(leader, _theorem(), key=key)
    assert result.usable


# ---------------------------------------------------------------------------
# Acceptance: expired fence publication is rejected
# ---------------------------------------------------------------------------


def test_expired_fence_publication_is_rejected() -> None:
    clock = {"t": 100.0}

    def now() -> float:
        return clock["t"]

    coordinator = _coordinator(clock=now, lease_seconds=5.0)
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="slow-producer", now=100.0)
    assert claim.expires_at == 105.0

    clock["t"] = 106.0  # past expiry
    with pytest.raises(ExpiredFenceError):
        coordinator.publish(claim, _theorem(), key=key, now=106.0)

    stats = coordinator.stats()
    assert stats["expired_rejections"] >= 1
    # No authority may have been written under the expired fence.
    assert coordinator.get(key, now=106.0) is None


def test_expired_renew_is_rejected() -> None:
    clock = {"t": 50.0}
    coordinator = _coordinator(clock=lambda: clock["t"], lease_seconds=2.0)
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="owner", now=50.0)
    clock["t"] = 55.0
    with pytest.raises(ExpiredFenceError):
        coordinator.renew(claim, now=55.0)


def test_released_fence_publication_is_rejected() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="owner")
    assert coordinator.release(claim) is True
    with pytest.raises(StaleFenceError):
        coordinator.publish(claim, _theorem(), key=key)


# ---------------------------------------------------------------------------
# Acceptance: waiters recover after producer crash without duplicate authority
# ---------------------------------------------------------------------------


def test_waiters_recover_after_producer_crash_without_duplicate_authority() -> None:
    coordinator = _coordinator(
        lease_seconds=30.0,
        wait_timeout_seconds=10.0,
        poll_interval_seconds=0.01,
    )
    key = _unified_key()
    producer_calls = {"n": 0}
    results: list = []
    lock = threading.Lock()

    # Pre-acquire so three followers join before the leader "crashes".
    leader_claim = coordinator.claim(key, owner_id="doomed-leader")
    assert leader_claim.acquired is True

    def waiter(worker_id: int) -> None:
        def producer() -> TheoremResult:
            with lock:
                producer_calls["n"] += 1
                call_n = producer_calls["n"]
            time.sleep(0.02)
            return _theorem(result_id=f"result:recovered-{call_n}")

        result = coordinator.get_or_compute(
            key, producer, owner_id=f"waiter-{worker_id}"
        )
        with lock:
            results.append(result)

    threads = [
        threading.Thread(target=waiter, args=(index,)) for index in range(3)
    ]
    for thread in threads:
        thread.start()

    # Wait until all three waiters have joined the in-flight claim.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if coordinator.stats().get("single_flight_waits", 0) >= 3:
            break
        time.sleep(0.01)
    assert coordinator.stats().get("single_flight_waits", 0) >= 3

    # Simulate producer crash: drop the fence without publishing authority.
    assert coordinator.abandon(leader_claim) is True

    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert len(results) == 3
    assert all(item.usable for item in results)
    # Exactly one successful authority in the store (no duplicate authority).
    stored = coordinator.get(key)
    assert stored is not None
    assert coordinator.store.stats()["size"] == 1
    result_ids = {
        item.entry.result_id for item in results if item.entry is not None
    }
    assert result_ids == {stored.result_id}
    # Recovered production ran after the abandoned generation.
    assert producer_calls["n"] == 1
    assert coordinator.stats()["waiter_recoveries"] >= 1
    # Attempts include the abandoned leader generation and one success.
    attempts = coordinator.attempt_records(key)
    statuses = {item.status for item in attempts}
    assert AttemptStatus.ABANDONED in statuses
    assert AttemptStatus.SUCCEEDED in statuses
    succeeded = [
        item for item in attempts if item.status is AttemptStatus.SUCCEEDED
    ]
    assert len(succeeded) == 1
    # Late publication from the crashed fence must still be rejected.
    with pytest.raises(StaleFenceError):
        coordinator.publish(
            leader_claim, _theorem(result_id="result:zombie"), key=key
        )
    assert coordinator.store.stats()["size"] == 1
    assert coordinator.get(key).result_id == stored.result_id


def test_waiter_recovers_when_lease_expires_without_publish() -> None:
    clock = {"t": 1000.0}
    coordinator = _coordinator(
        clock=lambda: clock["t"],
        lease_seconds=1.0,
        wait_timeout_seconds=5.0,
        poll_interval_seconds=0.01,
    )
    key = _unified_key()

    # Leader acquires but never publishes (crash before handoff).
    leader = coordinator.claim(key, owner_id="doomed", now=1000.0)
    assert leader.acquired

    # Advance past lease expiry.
    clock["t"] = 1002.0
    calls = {"n": 0}

    def producer() -> TheoremResult:
        calls["n"] += 1
        return _theorem()

    # A new producer recovers authority under a new fence generation.
    result = coordinator.get_or_compute(
        key, producer, owner_id="rescuer", now=1002.0, wait_timeout_seconds=2.0
    )
    assert result.usable
    assert calls["n"] == 1
    assert result.claim is not None
    assert result.claim.fence_generation >= 2
    # Original fence cannot publish late.
    with pytest.raises((ExpiredFenceError, StaleFenceError)):
        coordinator.publish(leader, _theorem(result_id="result:late"), key=key, now=1002.0)
    assert coordinator.get(key, now=1002.0) is not None
    # Still only one store entry.
    assert coordinator.store.stats()["size"] == 1


# ---------------------------------------------------------------------------
# Dual TTL / negative caching / invalidation / attempt records
# ---------------------------------------------------------------------------


def test_negative_outcome_uses_negative_ttl_and_remains_distinct() -> None:
    clock = {"t": 100.0}
    coordinator = _coordinator(
        positive_ttl_seconds=1000.0,
        negative_ttl_seconds=10.0,
        clock=lambda: clock["t"],
        outcome_handoff_seconds=1.0,
    )
    key = _unified_key()
    unknown = _theorem(
        status=ResultStatus.UNKNOWN,
        translation_ceiling=EvidenceAuthority.NONE,
    )
    claim = coordinator.claim(key, owner_id="neg", now=100.0)
    published = coordinator.publish(claim, unknown, key=key, now=100.0)
    assert published.usable
    entry = coordinator.get(key, now=100.0)
    assert entry is not None
    assert entry.polarity is CachePolarity.NEGATIVE
    assert entry.outcome is ProofOutcomeKind.UNKNOWN
    assert coordinator.ttl_for_entry(entry) == 10.0

    clock["t"] = 120.0
    expired = coordinator.lookup(key, now=120.0)
    assert not expired.usable
    assert expired.reason is CacheLookupReason.EXPIRED

    # Re-publish a positive result after negative expiry (and handoff end).
    claim2 = coordinator.claim(key, owner_id="pos", now=120.0)
    assert claim2.acquired is True
    coordinator.publish(claim2, _theorem(), key=key, now=120.0)
    hit = coordinator.lookup(key, now=120.0)
    assert hit.usable
    assert hit.entry is not None
    assert hit.entry.polarity is CachePolarity.POSITIVE


def test_invalidate_drops_authority_and_active_claim() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="owner")
    coordinator.publish(claim, _theorem(), key=key)
    assert coordinator.get(key) is not None

    removed = coordinator.invalidate(
        key, reason=InvalidationReason.POLICY, actor_id="policy-engine"
    )
    assert removed is True
    assert coordinator.get(key) is None
    records = coordinator.invalidation_records(key)
    assert len(records) == 1
    assert records[0].reason is InvalidationReason.POLICY
    assert records[0].actor_id == "policy-engine"

    # New production after invalidation starts a fresh generation.
    result = coordinator.get_or_compute(key, lambda: _theorem(result_id="result:after-inv"))
    assert result.usable
    assert result.role is CoordinationRole.PRODUCER


def test_attempt_records_track_success_and_failure() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    claim = coordinator.claim(key, owner_id="owner")
    coordinator.publish(claim, _theorem(), key=key)
    attempts = coordinator.attempt_records(key)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.SUCCEEDED
    assert attempts[0].entry_digest
    assert attempts[0].polarity is CachePolarity.POSITIVE

    key2 = _unified_key(ir={"formula": "(assert false)"})
    claim2 = coordinator.claim(key2, owner_id="failer")
    coordinator.publish_error(claim2, reason_code="solver_boom")
    failed = coordinator.attempt_records(key2)
    assert len(failed) == 1
    assert failed[0].status is AttemptStatus.FAILED
    assert failed[0].error_reason == "solver_boom"
    # Error publication must not write store authority.
    assert coordinator.get(key2) is None


def test_claim_and_attempt_round_trip_dicts() -> None:
    claim = ProofFenceClaim(
        key_digest="sha256:" + "a" * 64,
        claim_id="claim:1",
        owner_id="owner",
        fence_token="fence:" + "b" * 32,
        fence_generation=3,
        claimed_at=1.0,
        expires_at=2.0,
        status=ClaimStatus.CLAIMED,
        acquired=True,
    )
    assert ProofFenceClaim.from_dict(claim.to_dict()) == claim

    attempt = ProofAttemptRecord(
        attempt_id="attempt:1",
        key_digest=claim.key_digest,
        claim_id=claim.claim_id,
        fence_token=claim.fence_token,
        fence_generation=3,
        owner_id="owner",
        status=AttemptStatus.RUNNING,
        started_at=1.0,
    )
    restored = ProofAttemptRecord.from_dict(attempt.to_dict())
    assert restored.attempt_id == attempt.attempt_id
    assert restored.status is AttemptStatus.RUNNING


def test_cache_hit_skips_producer() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    calls = {"n": 0}

    def producer() -> TheoremResult:
        calls["n"] += 1
        return _theorem()

    first = coordinator.get_or_compute(key, producer)
    second = coordinator.get_or_compute(key, producer)
    assert first.role is CoordinationRole.PRODUCER
    assert second.role is CoordinationRole.CACHE_HIT
    assert calls["n"] == 1
    assert second.hit


def test_get_or_compute_timeout() -> None:
    coordinator = _coordinator(
        lease_seconds=30.0,
        wait_timeout_seconds=0.15,
        poll_interval_seconds=0.02,
    )
    key = _unified_key()
    # Hold a claim without publishing so waiters block.
    claim = coordinator.claim(key, owner_id="blocker")
    assert claim.acquired

    with pytest.raises(ProofCoordinationTimeout):
        coordinator.get_or_compute(
            key,
            lambda: _theorem(),
            owner_id="waiter",
            wait_timeout_seconds=0.15,
        )


def test_build_with_existing_store() -> None:
    store = DuckDBProofStore(
        positive_ttl_seconds=50.0, negative_ttl_seconds=5.0
    )
    key = _unified_key()
    store.put_result(key, _theorem())
    coordinator = build_duckdb_proof_coordinator(store=store)
    result = coordinator.get_or_compute(key, lambda: _theorem(result_id="nope"))
    assert result.role is CoordinationRole.CACHE_HIT
    assert result.usable


def test_reject_negative_ttl_exceeding_positive() -> None:
    with pytest.raises(DuckDBProofCoordinationError):
        DuckDBProofCoordinator(
            positive_ttl_seconds=10.0, negative_ttl_seconds=100.0
        )


def test_concurrent_distinct_keys_do_not_serialize() -> None:
    coordinator = _coordinator(lease_seconds=30.0, wait_timeout_seconds=10.0)
    keys = [
        _unified_key(ir={"formula": f"(assert (= x {index}))"})
        for index in range(4)
    ]
    calls = {"n": 0}
    lock = threading.Lock()

    def make_producer(index: int):
        def producer() -> TheoremResult:
            with lock:
                calls["n"] += 1
            time.sleep(0.05)
            return _theorem(result_id=f"result:k{index}")

        return producer

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(
                coordinator.get_or_compute,
                keys[index],
                make_producer(index),
                owner_id=f"w{index}",
            )
            for index in range(4)
        ]
        outcomes = [future.result(timeout=10) for future in as_completed(futures)]

    assert len(outcomes) == 4
    assert all(item.usable for item in outcomes)
    assert calls["n"] == 4
    assert coordinator.store.stats()["size"] == 4
