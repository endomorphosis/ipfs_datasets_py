"""Unit tests for fenced proof single-flight coordination (DQK-027).

Acceptance coverage:

* At most one valid producer publishes per proof key
* Expired fence publication is rejected
* Waiters recover after producer crash without duplicate authority
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    CacheLookupReason,
    CachePolarity,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.common.duckdb_proof_coordination import (
    COORDINATION_CATALOG_DDL,
    COORDINATION_CATALOG_TABLES,
    DEFAULT_LEASE_SECONDS,
    DUCKDB_PROOF_COORDINATION_INTERFACE,
    DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION,
    AttemptStatus,
    ClaimStatus,
    DuckDBProofCoordinator,
    ExpiredFenceError,
    ProofCoordinationError,
    ProofCoordinationExecutionError,
    StaleFenceError,
    build_duckdb_proof_coordinator,
    negative_cache_ttl_for,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    ProofOutcomeKind,
    UnifiedProofEntry,
    build_duckdb_proof_store,
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
    result_id: str = "result:theorem-coord-1",
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
    store = kwargs.pop("store", None)
    if store is None:
        store = build_duckdb_proof_store(
            positive_ttl_seconds=kwargs.get("positive_ttl_seconds", 3_600.0),
            negative_ttl_seconds=kwargs.get("negative_ttl_seconds", 60.0),
        )
    return build_duckdb_proof_coordinator(
        store,
        lease_seconds=kwargs.pop("lease_seconds", 1.0),
        wait_timeout_seconds=kwargs.pop("wait_timeout_seconds", 5.0),
        outcome_ttl_seconds=kwargs.pop("outcome_ttl_seconds", 2.0),
        poll_interval_seconds=kwargs.pop("poll_interval_seconds", 0.01),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_interfaces_schema_and_catalog_are_pinned() -> None:
    coordinator = _coordinator()
    assert coordinator.interface == DUCKDB_PROOF_COORDINATION_INTERFACE
    assert coordinator.schema_version == DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION
    assert DUCKDB_PROOF_COORDINATION_INTERFACE == "DuckDBProofCoordination@1"
    assert set(coordinator.catalog_tables()) == set(COORDINATION_CATALOG_TABLES)
    assert "singleflight_claims" in COORDINATION_CATALOG_TABLES
    assert "proof_attempt_records" in COORDINATION_CATALOG_TABLES
    assert "CREATE TABLE IF NOT EXISTS singleflight_claims" in COORDINATION_CATALOG_DDL
    assert "CREATE TABLE IF NOT EXISTS proof_attempt_records" in COORDINATION_CATALOG_DDL
    assert DEFAULT_LEASE_SECONDS == 300.0


def test_module_import_is_inert_without_duckdb() -> None:
    import importlib

    mod = importlib.import_module(
        "ipfs_datasets_py.logic.common.duckdb_proof_coordination"
    )
    assert mod.DUCKDB_PROOF_COORDINATION_INTERFACE == "DuckDBProofCoordination@1"


# ---------------------------------------------------------------------------
# Dual TTL / negative caching policy
# ---------------------------------------------------------------------------


def test_negative_cache_ttl_policy_selects_dual_ttl() -> None:
    assert (
        negative_cache_ttl_for(
            outcome=ProofOutcomeKind.PROOF,
            polarity=CachePolarity.POSITIVE,
            positive_ttl_seconds=1000,
            negative_ttl_seconds=30,
        )
        == 1000
    )
    assert (
        negative_cache_ttl_for(
            outcome=ProofOutcomeKind.UNKNOWN,
            polarity=None,
            positive_ttl_seconds=1000,
            negative_ttl_seconds=30,
        )
        == 30
    )
    assert (
        negative_cache_ttl_for(
            outcome=ProofOutcomeKind.ERROR,
            polarity=CachePolarity.NEGATIVE,
            positive_ttl_seconds=1000,
            negative_ttl_seconds=30,
        )
        == 30
    )


def test_publish_applies_negative_ttl_via_store_polarity() -> None:
    now = [1_000.0]
    coordinator = _coordinator(
        positive_ttl_seconds=1_000.0,
        negative_ttl_seconds=50.0,
        clock=lambda: now[0],
    )
    key = _unified_key()
    claim = coordinator.acquire(key, owner_id="producer-a", now=now[0])
    assert claim.acquired

    unknown = UnifiedProofEntry.from_typed_result(
        key,
        _theorem(status=ResultStatus.UNKNOWN, result_id="result:unknown-1"),
        created_at=now[0],
    )
    assert unknown.polarity is CachePolarity.NEGATIVE
    stored = coordinator.publish(claim, unknown, key=key, now=now[0])
    assert stored.usable
    assert stored.entry is not None

    # Still fresh under negative TTL.
    now[0] = 1_049.0
    hit = coordinator.store.lookup(key, now=now[0])
    assert hit.usable
    assert hit.reason in {
        CacheLookupReason.HIT,
        CacheLookupReason.NEGATIVE_HIT,
    }

    # Expired under negative TTL (50s) while positive would still be live.
    now[0] = 1_051.0
    expired = coordinator.store.lookup(key, now=now[0])
    assert not expired.usable
    assert expired.reason is CacheLookupReason.EXPIRED


# ---------------------------------------------------------------------------
# At most one valid producer publishes per proof key
# ---------------------------------------------------------------------------


def test_at_most_one_valid_producer_publishes_per_proof_key() -> None:
    coordinator = _coordinator(lease_seconds=2.0)
    key = _unified_key()
    barrier = threading.Barrier(8)
    produce_count = 0
    lock = threading.Lock()
    results = []

    def run():
        nonlocal produce_count
        barrier.wait(10)

        def produce():
            nonlocal produce_count
            with lock:
                produce_count += 1
            time.sleep(0.05)
            return UnifiedProofEntry.from_typed_result(
                key,
                _theorem(result_id="result:shared-1"),
                created_at=time.time(),
            )

        return coordinator.coordinate(key, produce, owner_id=f"w-{threading.get_ident()}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: run(), range(8)))

    assert produce_count == 1
    assert sum(1 for item in results if item.produced) == 1
    assert sum(1 for item in results if item.shared) == 7
    digests = {
        item.lookup.entry.entry_digest
        for item in results
        if item.lookup.entry is not None
    }
    assert len(digests) == 1
    fences = {item.fence_token for item in results if item.fence_token}
    assert len(fences) == 1


def test_follower_cannot_publish_without_claim_token() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    owner = coordinator.acquire(key, owner_id="owner")
    follower = coordinator.acquire(key, owner_id="follower")
    assert owner.acquired
    assert not follower.acquired
    assert follower.claim_id == ""
    assert follower.fence_token == owner.fence_token

    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(), created_at=time.time()
    )
    with pytest.raises(StaleFenceError):
        coordinator.publish(follower, entry, key=key)


def test_foreign_claim_id_is_rejected() -> None:
    from dataclasses import replace

    coordinator = _coordinator()
    key = _unified_key()
    owner = coordinator.acquire(key, owner_id="owner")
    forged = replace(owner, claim_id="0" * 64)
    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(), created_at=time.time()
    )
    with pytest.raises(StaleFenceError):
        coordinator.publish(forged, entry, key=key)


# ---------------------------------------------------------------------------
# Expired fence publication is rejected
# ---------------------------------------------------------------------------


def test_expired_fence_publication_is_rejected() -> None:
    now = [1_000.0]
    coordinator = _coordinator(lease_seconds=0.1, clock=lambda: now[0])
    key = _unified_key()
    claim = coordinator.acquire(key, owner_id="host-a", lease_seconds=0.1, now=now[0])
    assert claim.acquired
    assert claim.expires_at == pytest.approx(1_000.1)

    now[0] = 1_000.11  # past lease
    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(), created_at=now[0]
    )
    with pytest.raises(ExpiredFenceError):
        coordinator.publish(claim, entry, key=key, now=now[0])
    assert coordinator.stats()["expired_rejections"] >= 1
    # Store must remain empty — no authority granted.
    assert coordinator.store.lookup(key, now=now[0]).usable is False


def test_heartbeat_rejects_expired_fence() -> None:
    now = [5_000.0]
    coordinator = _coordinator(lease_seconds=1.0, clock=lambda: now[0])
    key = _unified_key()
    claim = coordinator.acquire(key, owner_id="host-a", now=now[0])
    now[0] = 5_001.5
    with pytest.raises(ExpiredFenceError):
        coordinator.heartbeat(claim, now=now[0])


def test_superseded_fence_cannot_publish_after_takeover() -> None:
    now = [2_000.0]
    coordinator = _coordinator(lease_seconds=0.2, clock=lambda: now[0])
    key = _unified_key()
    first = coordinator.acquire(key, owner_id="host-a", now=now[0])
    now[0] = 2_000.25
    replacement = coordinator.acquire(key, owner_id="host-b", now=now[0])
    assert replacement.acquired
    assert replacement.fence_token == first.fence_token + 1

    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(result_id="result:stale"), created_at=now[0]
    )
    with pytest.raises(StaleFenceError):
        coordinator.publish(first, entry, key=key, now=now[0])

    ok = UnifiedProofEntry.from_typed_result(
        key, _theorem(result_id="result:replacement"), created_at=now[0]
    )
    stored = coordinator.publish(replacement, ok, key=key, now=now[0])
    assert stored.usable
    hit = coordinator.store.lookup(key, now=now[0])
    assert hit.usable
    assert hit.entry is not None
    assert hit.entry.result_id == "result:replacement"


# ---------------------------------------------------------------------------
# Waiters recover after producer crash without duplicate authority
# ---------------------------------------------------------------------------


def test_waiters_recover_after_producer_crash_without_duplicate_authority() -> None:
    """Crashed leader (lease expires, no heartbeat) yields one waiter publisher."""

    now = [50_000.0]
    coordinator = _coordinator(
        lease_seconds=1.0,
        wait_timeout_seconds=5.0,
        clock=lambda: now[0],
    )
    key = _unified_key()

    # Leader acquires and begins an attempt, then "crashes" (no heartbeat/publish).
    leader_claim = coordinator.acquire(
        key, owner_id="leader", lease_seconds=1.0, now=now[0]
    )
    assert leader_claim.acquired
    leader_attempt = coordinator.begin_attempt(leader_claim, now=now[0])
    assert leader_attempt.status is AttemptStatus.STARTED

    # Lease expires without publication — waiters may take over.
    now[0] = 50_001.5
    produce_count = 0
    lock = threading.Lock()
    barrier = threading.Barrier(4)
    results: list = []

    def waiter_produce():
        nonlocal produce_count
        with lock:
            produce_count += 1
        time.sleep(0.02)
        return UnifiedProofEntry.from_typed_result(
            key,
            _theorem(result_id="result:recovered"),
            created_at=now[0],
        )

    def run_waiter(_idx: int):
        barrier.wait(10)
        results.append(
            coordinator.coordinate(
                key,
                waiter_produce,
                owner_id=f"waiter-{_idx}",
                lease_seconds=2.0,
                now=now[0],
            )
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run_waiter, range(4)))

    # Crashed leader cannot publish after takeover.
    stale_entry = UnifiedProofEntry.from_typed_result(
        key,
        _theorem(result_id="result:stale-leader"),
        created_at=now[0],
    )
    with pytest.raises((StaleFenceError, ExpiredFenceError)):
        coordinator.publish(leader_claim, stale_entry, key=key, now=now[0])
    coordinator.complete_attempt(
        leader_attempt,
        status=AttemptStatus.FAILED,
        error_reason="producer_crash",
        now=now[0],
    )

    assert produce_count == 1
    assert sum(1 for item in results if item.produced) == 1
    assert all(item.usable for item in results)
    assert all(
        item.lookup.entry is not None
        and item.lookup.entry.result_id == "result:recovered"
        for item in results
    )
    # Takeover advanced the fence past the crashed leader.
    assert all(item.fence_token > leader_claim.fence_token for item in results)
    hit = coordinator.store.lookup(key, now=now[0])
    assert hit.usable
    assert hit.entry is not None
    assert hit.entry.result_id == "result:recovered"
    attempts = coordinator.list_attempts(key)
    assert any(a.status is AttemptStatus.SUCCEEDED for a in attempts)
    assert any(a.status is AttemptStatus.FAILED for a in attempts)


def test_released_owner_allows_waiter_takeover_without_duplicate() -> None:
    now = [10_000.0]
    coordinator = _coordinator(lease_seconds=5.0, clock=lambda: now[0])
    key = _unified_key()
    first = coordinator.acquire(key, owner_id="a", now=now[0])
    assert coordinator.release(first, now=now[0])
    # Immediate takeover after voluntary release.
    second = coordinator.acquire(key, owner_id="b", now=now[0])
    assert second.acquired
    assert second.fence_token == first.fence_token + 1
    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(result_id="result:after-release"), created_at=now[0]
    )
    with pytest.raises((StaleFenceError, ExpiredFenceError)):
        coordinator.publish(first, entry, key=key, now=now[0])
    stored = coordinator.publish(second, entry, key=key, now=now[0])
    assert stored.usable


# ---------------------------------------------------------------------------
# Attempt records & invalidation
# ---------------------------------------------------------------------------


def test_attempt_records_track_start_and_success() -> None:
    coordinator = _coordinator()
    key = _unified_key()

    def produce():
        return UnifiedProofEntry.from_typed_result(
            key, _theorem(), created_at=time.time()
        )

    result = coordinator.coordinate(key, produce, owner_id="recorder")
    assert result.produced
    assert result.attempt is not None
    assert result.attempt.status is AttemptStatus.SUCCEEDED
    attempts = coordinator.list_attempts(key)
    assert len(attempts) == 1
    assert attempts[0].fence_token == result.fence_token
    assert attempts[0].entry_digest


def test_invalidation_clears_authority_and_blocks_stale_publish() -> None:
    now = [20_000.0]
    coordinator = _coordinator(clock=lambda: now[0])
    key = _unified_key()
    claim = coordinator.acquire(key, owner_id="owner", now=now[0])
    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(), created_at=now[0]
    )
    coordinator.publish(claim, entry, key=key, now=now[0])
    assert coordinator.store.lookup(key, now=now[0]).usable

    record = coordinator.invalidate(
        key, reason="policy_revoked", actor_id="admin", now=now[0]
    )
    assert record.reason == "policy_revoked"
    assert not coordinator.store.lookup(key, now=now[0]).usable
    assert coordinator.read_outcome(key, now=now[0]) is None
    invalidations = coordinator.list_invalidations(key)
    assert len(invalidations) == 1
    assert coordinator.stats()["invalidations"] == 1


def test_coordinate_cache_hit_short_circuits_without_claim() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    entry = UnifiedProofEntry.from_typed_result(
        key, _theorem(), created_at=time.time()
    )
    coordinator.store.put(entry)
    calls = 0

    def produce():
        nonlocal calls
        calls += 1
        raise AssertionError("producer must not run on cache hit")

    result = coordinator.coordinate(key, produce)
    assert calls == 0
    assert result.usable
    assert not result.produced
    assert result.fence_token == 0


def test_shared_error_outcome_is_fail_closed_for_waiters() -> None:
    coordinator = _coordinator(lease_seconds=2.0, wait_timeout_seconds=3.0)
    key = _unified_key()
    entered = threading.Event()
    release = threading.Event()
    owner_errors: list[BaseException] = []
    follower_errors: list[BaseException] = []

    def fail():
        entered.set()
        assert release.wait(5)
        raise RuntimeError("secret-must-not-leak-as-authority")

    def capture(bucket, fn):
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001
            bucket.append(exc)

    owner = threading.Thread(
        target=lambda: capture(
            owner_errors,
            lambda: coordinator.coordinate(key, fail, owner_id="owner"),
        )
    )
    owner.start()
    assert entered.wait(5)
    follower = threading.Thread(
        target=lambda: capture(
            follower_errors,
            lambda: coordinator.coordinate(
                key,
                lambda: (_ for _ in ()).throw(AssertionError("should not produce")),
                owner_id="follower",
            ),
        )
    )
    follower.start()
    time.sleep(0.05)
    release.set()
    owner.join(timeout=5)
    follower.join(timeout=5)

    assert owner_errors and isinstance(owner_errors[0], RuntimeError)
    assert follower_errors
    assert isinstance(follower_errors[0], ProofCoordinationExecutionError)
    assert not coordinator.store.lookup(key).usable


def test_claim_status_and_public_projection_hide_token() -> None:
    coordinator = _coordinator()
    key = _unified_key()
    claim = coordinator.acquire(key, owner_id="owner")
    assert claim.status is ClaimStatus.CLAIMED
    public = claim.public_projection()
    assert public["claim_id"] == ""
    assert public["acquired"] is False
    assert public["fence_token"] == claim.fence_token


def test_constructor_rejects_inverted_ttl_policy() -> None:
    with pytest.raises(ProofCoordinationError):
        build_duckdb_proof_coordinator(
            positive_ttl_seconds=10.0,
            negative_ttl_seconds=20.0,
        )
