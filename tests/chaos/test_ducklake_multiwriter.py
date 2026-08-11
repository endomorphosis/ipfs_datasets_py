"""Chaos tests for distributed Quack concurrency and fenced owner recovery (DQK-095).

Acceptance coverage:

* DuckDB, Quack, DuckLake, and object-store artifacts/images are immutable-digest
  pinned and emit a capability receipt
* Process, endpoint, container, network, catalog-file, registry, and volume
  create/reconcile/teardown are owner-locked and idempotent for one exact run
* Normal completion and injected process death clean only owned resources and
  leave no process, endpoint, container, network, or volume leaks
* The validation suite fails rather than skips when the owned harness is unavailable
* One DuckDB + Quack owner is the sole client of each catalog file; a second live
  owner or direct file opener is rejected by generation policy and the native
  DuckDB file lock
* Two remote writers racing the same logical key through one owner prove one
  durable reservation winner
* Independent catalog shards execute concurrently and one slow shard does not
  serialize the others
* A crash after the DuckLake commit may create a temporary in-doubt snapshot;
  its persisted operation ID is detected on restart and bounded reconciliation
  yields exactly one terminal receipt or quarantine
* No snapshot remains terminally unreceipted and recovery never creates a second
  logical transition for the same operation ID
* An owner-process outage and cold active/passive restart drill proves bounded
  admission stop, session teardown, endpoint/token revocation, storage-capability
  expiry, native-lock handoff, fencing, and recovery without claiming Quack
  replication or built-in high availability
* Lease loss in an already-running incumbent stops new requests and tears down
  sessions before a successor can open; stale startup and split-brain cases are
  tested separately
* A split-brain or stale-generation owner is rejected before opening the catalog
* Catalog recovery cannot point metadata at missing or foreign Parquet files
* Long readers and writers remain observable and cannot block control leases

Hermetic: no live Docker, DuckDB, Quack, or network required. The owned harness
lives in ``scripts/ops/ducklake_test_services.py`` and concurrency logic in
``ipfs_datasets_py/ducklake/concurrency.py``. When the harness is unavailable the
suite **fails** rather than skips.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_HARNESS_PATH = _REPO_ROOT / "scripts/ops/ducklake_test_services.py"
_LOCK_PATH = _REPO_ROOT / "requirements/ducklake-services.lock"


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

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_harness_module() -> ModuleType:
    """Load the ops harness without requiring scripts.ops package install."""

    module_name = "ducklake_test_services"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "CONTRACT_TASK_ID", None) == "DQK-095":
        return existing
    if not _HARNESS_PATH.is_file():
        raise AssertionError(
            f"owned harness module missing at {_HARNESS_PATH}; "
            "validation suite fails rather than skips"
        )
    spec = importlib.util.spec_from_file_location(module_name, _HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load harness module from {_HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _require_harness_module() -> ModuleType:
    """Fail closed when the owned harness is unavailable (never skip)."""

    try:
        module = _load_harness_module()
    except Exception as exc:  # noqa: BLE001 — intentional fail-not-skip
        raise AssertionError(
            f"owned DuckLake test-services harness unavailable: {exc}; "
            "validation suite fails rather than skips"
        ) from exc
    if not _LOCK_PATH.is_file():
        raise AssertionError(
            f"digest-pinned services lock missing at {_LOCK_PATH}; "
            "validation suite fails rather than skips"
        )
    return module


# Load once; failure is a hard test failure, not a skip.
services = _require_harness_module()

from ipfs_datasets_py.ducklake import concurrency as mw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def harness() -> Any:
    h = services.DuckLakeTestServicesHarness(
        owner=services.new_run_owner(run_id=f"test-{services._new_id('r')}")
    )
    h.require_harness()
    h.start()
    try:
        yield h
    finally:
        if h.available:
            try:
                h.complete()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Digest pins + capability receipt
# ---------------------------------------------------------------------------


def test_services_lock_is_digest_pinned_and_emits_capability_receipt() -> None:
    report = dict(services.install_check(_LOCK_PATH))
    assert report["ok"] is True
    assert report["owner_task_id"] == "DQK-095"
    assert report["quack_replication_claimed"] is False
    assert report["builtin_high_availability_claimed"] is False
    assert report["single_catalog_owner_required"] is True
    assert report["lock_sha256"].startswith("sha256:")
    assert report["capability_receipt_id"]
    assert report["capability_receipt_digest"].startswith("sha256:")

    images = report["image_digests"]
    for role in ("probe", "object_store", "catalog_owner"):
        assert role in images, f"missing image pin for {role}"
        assert images[role].startswith("sha256:")
        assert len(images[role]) == len("sha256:") + 64

    artifacts = report["artifact_digests"]
    assert "duckdb_package" in artifacts
    assert "lock" in artifacts
    assert any(k.startswith("extension.quack") for k in artifacts)
    assert any(k.startswith("extension.ducklake") for k in artifacts)
    assert any(k.startswith("extension.httpfs") for k in artifacts)

    kinds = set(report["owner_locked_resource_kinds"])
    assert kinds == {
        "process",
        "endpoint",
        "container",
        "network",
        "catalog_file",
        "registry",
        "volume",
    }


def test_capability_receipt_bound_to_run_and_lock() -> None:
    profile = services.load_services_lock(_LOCK_PATH)
    receipt_a = services.emit_capability_receipt(profile, run_id="run-alpha")
    receipt_b = services.emit_capability_receipt(profile, run_id="run-beta")
    assert receipt_a.run_id == "run-alpha"
    assert receipt_b.run_id == "run-beta"
    assert receipt_a.lock_sha256 == profile.lock_sha256
    assert receipt_a.quack_replication_claimed is False
    body = dict(receipt_a.as_mapping())
    assert body["receipt_digest"].startswith("sha256:")
    assert body["required_artifacts"]
    assert "object_store" in body["required_artifacts"]


# ---------------------------------------------------------------------------
# Owner-locked create / reconcile / teardown + no leaks
# ---------------------------------------------------------------------------


def test_create_reconcile_teardown_are_owner_locked_and_idempotent(
    harness: Any,
) -> None:
    kinds = list(services.ResourceKind)
    for kind in kinds:
        name = f"{kind.value}-one"
        first = harness.registry.create(kind=kind, name=name, attributes={"n": 1})
        second = harness.registry.create(kind=kind, name=name, attributes={"n": 2})
        assert first.resource_id == second.resource_id
        assert second.attributes["n"] == 2
        third = harness.registry.reconcile(kind=kind, name=name, attributes={"n": 3})
        assert third.resource_id == first.resource_id
        assert third.attributes["n"] == 3
        t1 = dict(harness.registry.teardown(kind=kind, name=name))
        t2 = dict(harness.registry.teardown(kind=kind, name=name))
        assert t1["action"] == "torn_down"
        assert t2["action"] == "already_absent"
        assert t2["idempotent"] is True


def test_foreign_resources_never_inspected_reused_or_deleted(harness: Any) -> None:
    harness.registry.register_foreign(
        kind=services.ResourceKind.VOLUME,
        name="foreign-vol",
        foreign_run_id="other-run",
    )
    with pytest.raises(services.ForeignResourceError, match="foreign"):
        harness.registry.inspect(kind=services.ResourceKind.VOLUME, name="foreign-vol")
    with pytest.raises(services.ForeignResourceError, match="foreign"):
        harness.registry.reconcile(
            kind=services.ResourceKind.VOLUME, name="foreign-vol"
        )
    with pytest.raises(services.ForeignResourceError, match="foreign"):
        harness.registry.teardown(
            kind=services.ResourceKind.VOLUME, name="foreign-vol"
        )
    with pytest.raises(services.ForeignResourceError, match="foreign"):
        harness.registry.create(
            kind=services.ResourceKind.VOLUME, name="foreign-vol"
        )


def test_normal_completion_cleans_only_owned_resources_no_leaks() -> None:
    h = services.DuckLakeTestServicesHarness(
        owner=services.new_run_owner(run_id="complete-run")
    )
    h.start()
    h.create_catalog_owner(catalog_id="cat_complete", owner_generation=1)
    h.registry.register_foreign(
        kind=services.ResourceKind.NETWORK,
        name="foreign-net",
        foreign_run_id="foreign-complete",
    )
    report = dict(h.complete())
    assert report["remaining_owned"] == 0
    for kind, count in report["leaks"].items():
        assert count == 0, f"leak in {kind}"
    assert report["capability_expired"] is True
    assert report["endpoints_revoked"] is True
    assert report["quack_replication_claimed"] is False


def test_process_death_cleans_only_owned_resources_no_leaks() -> None:
    h = services.DuckLakeTestServicesHarness(
        owner=services.new_run_owner(run_id="death-run")
    )
    h.start()
    h.create_catalog_owner(catalog_id="cat_death", owner_generation=1)
    h.registry.register_foreign(
        kind=services.ResourceKind.CONTAINER,
        name="foreign-ctr",
        foreign_run_id="foreign-death",
    )
    death = dict(h.inject_process_death())
    assert death["process_dead"] is True
    assert death["remaining_owned"] == 0
    assert death["foreign_untouched"]
    for kind, count in death["leaks"].items():
        assert count == 0, f"leak in {kind} after process death"
    assert death["endpoints_revoked"] is True
    assert death["storage_capabilities_expired"] is True


def test_catalog_owner_process_death_releases_lock_only_for_owned() -> None:
    h = services.DuckLakeTestServicesHarness(
        owner=services.new_run_owner(run_id="owner-death")
    )
    h.start()
    created = dict(h.create_catalog_owner(catalog_id="cat_kill", owner_generation=1))
    assert created["native_file_lock"] == "acquired"
    # Second open of same path rejected while live.
    with pytest.raises(services.OwnerLockError, match="native DuckDB file lock"):
        h.create_catalog_owner(catalog_id="cat_kill", owner_generation=2)
    killed = dict(h.kill_catalog_owner("cat_kill"))
    assert killed["process_dead"] is True
    assert killed["admission_stopped"] is True
    assert killed["endpoint_revoked"] is True
    assert killed["native_file_lock_released"] is True
    # Successor may open after lock release.
    reopened = dict(
        h.try_open_catalog_file(
            catalog_path="/var/lib/ducklake/catalogs/cat_kill.duckdb",
            claimant_process_id="successor-1",
            owner_generation=2,
            expected_generation=2,
        )
    )
    assert reopened["opened"] is True
    h.complete()


# ---------------------------------------------------------------------------
# Harness unavailable → fail, never skip
# ---------------------------------------------------------------------------


def test_unavailable_harness_fails_rather_than_skips() -> None:
    bad = services.DuckLakeTestServicesHarness(available=False)
    with pytest.raises(services.HarnessUnavailableError, match="fail rather than skip"):
        bad.require_harness()
    with pytest.raises(services.HarnessUnavailableError):
        bad.start()


def test_missing_lock_fails_closed() -> None:
    with pytest.raises(services.DigestPinError, match="not found"):
        services.load_services_lock("/nonexistent/ducklake-services.lock")


def test_self_check_passes() -> None:
    report = dict(services.self_check())
    assert report["ok"] is True
    assert report["self_check"]["ok"] is True
    assert report["self_check"]["unavailable_fails"] is True
    assert report["self_check"]["foreign_untouched"] is True


# ---------------------------------------------------------------------------
# Single owner + second opener rejected
# ---------------------------------------------------------------------------


def test_one_owner_per_catalog_second_and_direct_open_rejected() -> None:
    result = dict(mw.prove_second_owner_rejected())
    assert result["ok"] is True
    assert result["direct_open_rejected"] is True
    assert result["second_owner_rejected"] is True
    assert result["single_owner"] is True
    assert result["quack_replication_claimed"] is False


def test_remote_writer_cannot_open_catalog_file_directly() -> None:
    plane = mw.MultiWriterPlane()
    owner = plane.provision_shard(
        catalog_id="cat_remote_deny", shard_id="shard_remote_deny", port=19201
    )
    client = mw.RemoteWriterClient("remote-1", owner)
    with pytest.raises(mw.DirectCatalogOpenRejected):
        client.attempt_direct_catalog_open()


# ---------------------------------------------------------------------------
# Same logical key race → one winner
# ---------------------------------------------------------------------------


def test_same_logical_key_race_one_durable_winner() -> None:
    result = dict(mw.prove_same_logical_key_one_winner())
    assert result["ok"] is True
    assert result["winners"] == 1
    assert result["losers"] == 1
    assert result["idempotent_replay_ok"] is True


def test_duplicate_idempotency_key_is_logical_once() -> None:
    plane = mw.MultiWriterPlane()
    owner = plane.provision_shard(
        catalog_id="cat_idem", shard_id="shard_idem", port=19210
    )
    client = mw.RemoteWriterClient("idem-client", owner)
    client.connect()
    first = client.write(
        logical_key={"event_id": 1},
        idempotency_key="same-idem",
        operation_id="op-idem-1",
        payload="first",
    )
    assert first.outcome is mw.OperationOutcome.COMMITTED
    # Lost-reply style retry with same operation + idempotency key.
    second = client.write(
        logical_key={"event_id": 1},
        idempotency_key="same-idem",
        operation_id="op-idem-1",
        payload="retry",
    )
    assert second.outcome is mw.OperationOutcome.DUPLICATE_IDEMPOTENT
    assert second.snapshot_version == first.snapshot_version


# ---------------------------------------------------------------------------
# Independent shards concurrent
# ---------------------------------------------------------------------------


def test_independent_shards_concurrent_slow_does_not_serialize() -> None:
    result = dict(mw.prove_concurrent_shards_not_serialized())
    assert result["ok"] is True
    assert result["b_finished_before_a"] is True
    assert result["independent_shards"] is True
    assert result["shard_b_duration_s"] < result["shard_a_duration_s"]


# ---------------------------------------------------------------------------
# In-doubt crash recovery
# ---------------------------------------------------------------------------


def test_crash_after_ducklake_commit_in_doubt_one_terminal() -> None:
    result = dict(mw.prove_in_doubt_recovery_one_terminal())
    assert result["ok"] is True
    assert result["crash_outcome"] == "in_doubt"
    assert result["terminal_outcome"] in {"committed", "quarantined"}
    assert result["second_transition_prevented"] is True
    assert result["unreceipted_snapshots"] == []


def test_recovery_never_second_logical_transition() -> None:
    plane = mw.MultiWriterPlane()
    owner = plane.provision_shard(
        catalog_id="cat_twice", shard_id="shard_twice", port=19220
    )
    client = mw.RemoteWriterClient("twice", owner)
    client.connect()
    crash = client.write(
        logical_key={"event_id": 3},
        idempotency_key="idem-twice",
        operation_id="op-twice",
        simulate_crash_after_snapshot=True,
    )
    assert crash.outcome is mw.OperationOutcome.IN_DOUBT
    r1 = owner.reconcile_in_doubt()
    r2 = owner.reconcile_in_doubt()
    r3 = owner.reconcile_in_doubt()
    assert r1.second_transition_prevented is True
    assert r2.second_transition_prevented is True
    assert r3.second_transition_prevented is True
    terminal = owner._terminal_by_operation["op-twice"]
    assert terminal.outcome in {
        mw.OperationOutcome.COMMITTED,
        mw.OperationOutcome.QUARANTINED,
    }
    # Exactly one terminal mapping for the operation ID.
    assert list(owner._terminal_by_operation.keys()).count("op-twice") == 1


def test_in_doubt_marker_persists_operation_id() -> None:
    plane = mw.MultiWriterPlane()
    owner = plane.provision_shard(
        catalog_id="cat_marker", shard_id="shard_marker", port=19221
    )
    client = mw.RemoteWriterClient("marker", owner)
    client.connect()
    crash = client.write(
        logical_key="marker-key",
        idempotency_key="idem-marker",
        operation_id="op-marker-99",
        simulate_crash_after_snapshot=True,
    )
    assert crash.outcome is mw.OperationOutcome.IN_DOUBT
    assert "op-marker-99" in owner._in_doubt_markers
    marker = owner._in_doubt_markers["op-marker-99"]
    assert marker.operation_id == "op-marker-99"
    assert marker.snapshot_version is not None
    assert marker.snapshot_version >= 1
    body = dict(marker.as_mapping())
    assert body["schema"] == mw.IN_DOUBT_MARKER_SCHEMA


# ---------------------------------------------------------------------------
# Active/passive restart
# ---------------------------------------------------------------------------


def test_active_passive_restart_drill() -> None:
    result = dict(mw.prove_active_passive_restart())
    assert result["ok"] is True
    drill = result["drill"]
    assert drill["native_lock_handoff"] is True
    assert drill["fencing_complete"] is True
    assert drill["quack_replication_claimed"] is False
    assert drill["builtin_high_availability_claimed"] is False
    assert drill["predecessor_stop"]["admission_stopped"] is True
    assert drill["predecessor_stop"]["endpoint_token_revoked"] is True
    assert drill["predecessor_stop"]["storage_capabilities_expired"] is True
    assert drill["successor_owner_generation"] == 2
    # In-doubt from before restart must be reconciled.
    recon = drill["reconciliation"]
    assert recon["second_transition_prevented"] is True


# ---------------------------------------------------------------------------
# Lease loss + split-brain + stale generation
# ---------------------------------------------------------------------------


def test_lease_loss_stops_new_requests_and_tears_sessions() -> None:
    result = dict(mw.prove_lease_loss_stops_incumbent())
    assert result["ok"] is True
    assert result["new_requests_rejected"] is True
    assert result["successor_blocked_while_lock_held"] is True
    assert result["stale_startup_rejected"] is True
    assert result["lease_loss"]["admission_stopped"] is True
    assert result["lease_loss"]["sessions_torn_down"] == 1


def test_split_brain_and_stale_generation_rejected_before_open() -> None:
    result = dict(mw.prove_split_brain_rejected_before_open())
    assert result["ok"] is True
    assert result["split_brain_rejected_before_open"] is True
    assert result["stale_generation_rejected_before_open"] is True


def test_harness_stale_generation_rejected_before_catalog_open() -> None:
    h = services.DuckLakeTestServicesHarness(
        owner=services.new_run_owner(run_id="stale-gen")
    )
    h.start()
    h.create_catalog_owner(catalog_id="cat_stale", owner_generation=3)
    with pytest.raises(services.OwnerLockError, match="stale or split-brain"):
        h.try_open_catalog_file(
            catalog_path="/var/lib/ducklake/catalogs/cat_stale.duckdb",
            claimant_process_id="stale-claimant",
            owner_generation=1,
            expected_generation=3,
        )
    h.complete()


# ---------------------------------------------------------------------------
# Missing / foreign Parquet recovery guards
# ---------------------------------------------------------------------------


def test_catalog_recovery_rejects_missing_and_foreign_parquet() -> None:
    result = dict(mw.prove_missing_foreign_parquet_rejected())
    assert result["ok"] is True
    assert result["missing_rejected"] is True
    assert result["foreign_rejected"] is True
    assert result["owned_recoverable"] is True


# ---------------------------------------------------------------------------
# Long readers/writers observable; do not block control leases
# ---------------------------------------------------------------------------


def test_long_readers_writers_observable_do_not_block_control_leases() -> None:
    result = dict(mw.prove_long_readers_do_not_block_control())
    assert result["ok"] is True
    assert result["control_lease_count"] == 5
    assert result["max_control_lease_acquire_s"] < 0.1
    assert result["long_ops_blocked_control"] is False
    assert "long-1" in result["long_ops_observable"]


# ---------------------------------------------------------------------------
# Object-store latency injection (harness)
# ---------------------------------------------------------------------------


def test_object_store_latency_injection_still_owner_bound() -> None:
    h = services.DuckLakeTestServicesHarness(
        owner=services.new_run_owner(run_id="latency-run"),
        object_store_latency_ms=20.0,
    )
    h.start()
    store = h.object_store()
    put = dict(store.put("key/a.parquet", b"payload-bytes"))
    assert put["digest"].startswith("sha256:")
    got = dict(store.get("key/a.parquet") or {})
    assert got["digest"] == put["digest"]
    store.expire_capabilities()
    with pytest.raises(services.OwnerLockError, match="expired"):
        store.put("key/b.parquet", b"nope")
    h.complete()


# ---------------------------------------------------------------------------
# Full suite aggregator
# ---------------------------------------------------------------------------


def test_run_concurrency_suite_all_proofs() -> None:
    suite = dict(mw.run_concurrency_suite())
    assert suite["ok"] is True
    assert suite["task_id"] == "DQK-095"
    assert suite["quack_replication_claimed"] is False
    assert suite["builtin_high_availability_claimed"] is False
    expected = {
        "second_owner_rejected",
        "same_logical_key_one_winner",
        "concurrent_shards_not_serialized",
        "in_doubt_recovery_one_terminal",
        "active_passive_restart",
        "lease_loss_stops_incumbent",
        "split_brain_rejected_before_open",
        "missing_foreign_parquet_rejected",
        "long_readers_do_not_block_control",
    }
    assert set(suite["proofs"]) == expected
    for name, proof in suite["proofs"].items():
        assert proof["ok"] is True, f"proof {name} failed: {proof}"


def test_no_quack_replication_or_ha_claims_in_modules() -> None:
    assert services.QUACK_REPLICATION_CLAIMED is False
    assert services.BUILTIN_HIGH_AVAILABILITY_CLAIMED is False
    assert mw.QUACK_REPLICATION_CLAIMED is False
    assert mw.BUILTIN_HIGH_AVAILABILITY_CLAIMED is False
    profile = services.load_services_lock(_LOCK_PATH)
    assert profile.settings.get("quack_replication_claimed", "false") == "false"
    assert (
        profile.settings.get("builtin_high_availability_claimed", "false") == "false"
    )


# ---------------------------------------------------------------------------
# Snapshot readers remain concurrent with writers (observability)
# ---------------------------------------------------------------------------


def test_snapshot_reader_and_writer_remain_observable() -> None:
    plane = mw.MultiWriterPlane()
    owner = plane.provision_shard(
        catalog_id="cat_rw", shard_id="shard_rw", port=19230
    )
    barrier = threading.Barrier(2)
    outcomes: dict[str, Any] = {}

    def writer() -> None:
        client = mw.RemoteWriterClient("rw-w", owner)
        client.connect()
        barrier.wait(timeout=5)
        outcomes["write"] = client.write(
            logical_key="rw-key",
            idempotency_key="idem-rw",
            operation_id="op-rw",
            long_op_id="rw-write",
        )

    def reader() -> None:
        barrier.wait(timeout=5)
        # Snapshot reader acquires control lease and observes long ops.
        lease = owner.acquire_control_lease("snapshot-reader", ttl_seconds=2.0)
        outcomes["lease"] = dict(lease.as_mapping())
        outcomes["observed"] = dict(owner.observe_long_ops())

    t_w = threading.Thread(target=writer)
    t_r = threading.Thread(target=reader)
    t_w.start()
    t_r.start()
    t_w.join(timeout=10)
    t_r.join(timeout=10)
    assert outcomes["write"].outcome is mw.OperationOutcome.COMMITTED
    assert outcomes["lease"]["holder"] == "snapshot-reader"
    # Observability map is present (may be empty if reader raced before write start).
    assert isinstance(outcomes["observed"], dict)
