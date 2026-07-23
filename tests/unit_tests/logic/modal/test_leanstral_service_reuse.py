"""Behavioral coverage for persistent CUDA Leanstral service generations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, Lock
from typing import Any

import pytest

from ipfs_datasets_py.logic.modal.leanstral_audit_worker import (
    LeanstralPersistentServiceConfig,
    LeanstralPersistentServiceManager,
    LeanstralServiceHealth,
    LeanstralServiceHealthError,
    LeanstralServiceIdentity,
    LeanstralServiceIdentityError,
)


def _identity() -> LeanstralServiceIdentity:
    return LeanstralServiceIdentity(
        model="mistralai/Leanstral-8B-Instruct-2512",
        context_size=32768,
        context_fingerprint="legal-ir-audit-template-v7:sha256:5b78",
        provider="leanstral_local",
    )


def _healthy(
    service: dict[str, Any], identity: LeanstralServiceIdentity
) -> LeanstralServiceHealth:
    return LeanstralServiceHealth(
        status="healthy",
        cuda_backed=True,
        provider=identity.provider,
        model=identity.model,
        base_url="http://127.0.0.1:8080/v1",
        service_id=str(service["service_id"]),
        context_size=identity.context_size,
        context_fingerprint=identity.context_fingerprint,
        # Provider health is operational evidence, never proof evidence.  The
        # manager must remove an accidental trust claim at the lease boundary.
        proof_authority=True,
    )


def test_compatible_cycles_and_trials_reuse_one_cuda_service_generation() -> None:
    """Warm requests must not reload the canonical model or repeat preflight."""

    identity = _identity()
    load_calls: list[LeanstralServiceIdentity] = []
    preflight_calls: list[tuple[str, LeanstralServiceIdentity]] = []
    active_services: set[str] = set()

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        load_calls.append(requested)
        service_id = f"cuda-leanstral-{len(load_calls)}"
        active_services.add(service_id)
        return {"service_id": service_id, "canonical_weights_loaded": True}

    def preflight(
        service: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> LeanstralServiceHealth:
        preflight_calls.append((str(service["service_id"]), requested))
        return _healthy(service, requested)

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=preflight,
    )

    warmup = manager.acquire(identity)
    next_autoencoder_cycle = manager.acquire(identity)
    compatible_trial = manager.acquire(replace(identity))
    telemetry = manager.telemetry_snapshot()

    assert warmup is next_autoencoder_cycle is compatible_trial
    assert warmup.service is next_autoencoder_cycle.service
    assert warmup.generation == 1
    assert warmup.health.healthy_cuda_backed
    assert load_calls == [identity]
    assert preflight_calls == [("cuda-leanstral-1", identity)]
    assert active_services == {"cuda-leanstral-1"}
    assert telemetry["generation"] == 1
    assert telemetry["acquire_count"] == 3
    assert telemetry["reuse_count"] == 2
    assert telemetry["model_load_count"] == 1
    assert telemetry["preflight_count"] == 1
    assert telemetry["restart_count"] == 0
    assert telemetry["healthy_cuda_service_reused"] is True
    assert telemetry["proof_authority"] is False
    assert telemetry["health"]["proof_authority"] is False


def test_concurrent_compatible_acquires_share_exactly_one_model_load() -> None:
    identity = _identity()
    callers = 8
    ready = Barrier(callers + 1)
    loader_entered = Event()
    release_loader = Event()
    call_lock = Lock()
    load_calls = 0
    preflight_calls = 0

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        nonlocal load_calls
        assert requested == identity
        with call_lock:
            load_calls += 1
            service_id = f"concurrent-service-{load_calls}"
        loader_entered.set()
        assert release_loader.wait(timeout=2.0)
        return {"service_id": service_id}

    def preflight(
        service: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> LeanstralServiceHealth:
        nonlocal preflight_calls
        with call_lock:
            preflight_calls += 1
        return _healthy(service, requested)

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=preflight,
    )

    def acquire_together() -> Any:
        ready.wait(timeout=2.0)
        return manager.acquire(identity)

    with ThreadPoolExecutor(max_workers=callers) as executor:
        futures = [executor.submit(acquire_together) for _ in range(callers)]
        ready.wait(timeout=2.0)
        try:
            assert loader_entered.wait(timeout=2.0)
        finally:
            release_loader.set()
        leases = [future.result(timeout=2.0) for future in futures]

    assert all(lease is leases[0] for lease in leases)
    assert load_calls == 1
    assert preflight_calls == 1
    telemetry = manager.telemetry_snapshot()
    assert telemetry["acquire_count"] == callers
    assert telemetry["reuse_count"] == callers - 1
    assert telemetry["model_load_count"] == 1
    assert telemetry["preflight_count"] == 1
    assert telemetry["healthy_cuda_service_reused"] is True


@pytest.mark.parametrize(
    "incompatible_identity",
    [
        replace(_identity(), model="mistralai/Leanstral-22B-v0.1"),
        replace(_identity(), context_size=16384),
        replace(_identity(), context_fingerprint="legal-ir-audit-template-v8:sha256:91ca"),
        replace(_identity(), provider="llama_cpp"),
    ],
    ids=("model", "context-size", "context-fingerprint", "provider"),
)
def test_reuse_rejects_incompatible_model_or_context_before_callbacks(
    incompatible_identity: LeanstralServiceIdentity,
) -> None:
    identity = _identity()
    load_count = 0
    preflight_count = 0

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        nonlocal load_count
        load_count += 1
        return {"service_id": f"service-{load_count}"}

    def preflight(
        service: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> LeanstralServiceHealth:
        nonlocal preflight_count
        preflight_count += 1
        return _healthy(service, requested)

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=preflight,
    )
    original_lease = manager.acquire()

    with pytest.raises(LeanstralServiceIdentityError, match="identity"):
        manager.acquire(incompatible_identity)

    assert manager.acquire(identity) is original_lease
    assert load_count == 1
    assert preflight_count == 1
    telemetry = manager.telemetry_snapshot()
    assert telemetry["model_load_count"] == 1
    assert telemetry["preflight_count"] == 1
    assert telemetry["restart_count"] == 0
    assert telemetry["identity"] == identity.to_dict()


@pytest.mark.parametrize(
    "health_override",
    [
        {"model": "mistralai/Leanstral-22B-v0.1"},
        {"provider": "llama_cpp"},
        {"context_size": 16384},
        {"context_fingerprint": "legal-ir-audit-template-v8:sha256:91ca"},
    ],
    ids=("model", "provider", "context-size", "context-fingerprint"),
)
def test_preflight_must_attest_the_leased_model_and_context_identity(
    health_override: dict[str, Any],
) -> None:
    identity = _identity()

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        del requested
        return {"service_id": "wrong-identity-service"}

    def preflight(
        service: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> LeanstralServiceHealth:
        return replace(_healthy(service, requested), **health_override)

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=preflight,
    )

    with pytest.raises(LeanstralServiceIdentityError, match="mismatch"):
        manager.acquire()

    telemetry = manager.telemetry_snapshot()
    assert telemetry["generation"] == 0
    assert telemetry["service_id"] == ""
    assert telemetry["model_load_count"] == 1
    assert telemetry["preflight_count"] == 1
    assert telemetry["restart_count"] == 0
    assert telemetry["healthy_cuda_service_reused"] is False
    assert telemetry["proof_authority"] is False


def test_health_failures_are_consecutive_bounded_and_restart_one_generation() -> None:
    identity = _identity()
    loaded: list[str] = []
    restarted: list[tuple[str, LeanstralServiceIdentity]] = []
    preflighted: list[str] = []
    active_services: set[str] = set()

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        del requested
        service_id = f"generation-{len(loaded) + 1}"
        loaded.append(service_id)
        active_services.add(service_id)
        return {"service_id": service_id}

    def restarter(
        previous: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> dict[str, Any]:
        old_id = str(previous["service_id"])
        restarted.append((old_id, requested))
        active_services.remove(old_id)
        service_id = f"generation-{len(restarted) + 1}"
        active_services.add(service_id)
        return {"service_id": service_id}

    def preflight(
        service: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> LeanstralServiceHealth:
        preflighted.append(str(service["service_id"]))
        return _healthy(service, requested)

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=preflight,
        restarter=restarter,
        config=LeanstralPersistentServiceConfig(max_consecutive_health_failures=3),
    )
    lease = manager.acquire()

    manager.report_health_failure("probe_timeout")
    manager.report_health_failure("probe_timeout")
    assert manager.telemetry_snapshot()["restart_count"] == 0
    assert lease.generation == 1

    # A healthy observation breaks the failure streak; non-consecutive noise
    # must not churn a 207-second model generation.
    manager.report_healthy()
    manager.report_health_failure("probe_timeout")
    manager.report_health_failure("probe_timeout")
    assert manager.telemetry_snapshot()["restart_count"] == 0

    manager.report_health_failure("probe_timeout")
    telemetry = manager.telemetry_snapshot()

    assert manager.acquire(identity) is lease
    assert lease.generation == 2
    assert lease.service_id == "generation-2"
    assert loaded == ["generation-1"]
    assert restarted == [("generation-1", identity)]
    assert preflighted == ["generation-1", "generation-2"]
    assert active_services == {"generation-2"}
    assert telemetry["generation"] == 2
    assert telemetry["model_load_count"] == 2
    assert telemetry["preflight_count"] == 2
    assert telemetry["restart_count"] == 1
    assert telemetry["health_failure_count"] == 5
    assert telemetry["consecutive_health_failures"] == 0
    assert telemetry["proof_authority"] is False


def test_unhealthy_or_non_cuda_preflight_never_yields_a_lease() -> None:
    identity = _identity()
    calls: list[str] = []

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        del requested
        calls.append("load")
        return {"service_id": "cpu-service"}

    def preflight(
        service: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> LeanstralServiceHealth:
        calls.append("preflight")
        return replace(_healthy(service, requested), cuda_backed=False)

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=preflight,
        config=LeanstralPersistentServiceConfig(require_cuda_backed=True),
    )

    with pytest.raises(LeanstralServiceHealthError, match="CUDA"):
        manager.acquire()

    assert calls == ["load", "preflight"]
    telemetry = manager.telemetry_snapshot()
    assert telemetry["healthy_cuda_service_reused"] is False
    assert telemetry["proof_authority"] is False


def test_request_and_restart_timing_are_reported_as_separate_dimensions() -> None:
    identity = _identity()
    now = 100.0

    def clock() -> float:
        return now

    def loader(requested: LeanstralServiceIdentity) -> dict[str, Any]:
        del requested
        return {"service_id": "generation-1"}

    def restarter(
        previous: dict[str, Any], requested: LeanstralServiceIdentity
    ) -> dict[str, Any]:
        nonlocal now
        del previous, requested
        now += 0.75
        return {"service_id": "generation-2"}

    manager = LeanstralPersistentServiceManager(
        identity,
        loader=loader,
        preflight=lambda service, requested: _healthy(service, requested),
        restarter=restarter,
        config=LeanstralPersistentServiceConfig(max_consecutive_health_failures=1),
        clock=clock,
    )
    manager.acquire()
    manager.record_request_timing(
        queue_seconds=0.125,
        inference_seconds=1.5,
        verification_seconds=0.25,
    )
    manager.record_request_timing(
        queue_seconds=0.375,
        inference_seconds=2.0,
        verification_seconds=0.5,
    )
    manager.report_health_failure("cuda_process_unresponsive")

    telemetry = manager.telemetry_snapshot()
    assert telemetry["queue_seconds"] == pytest.approx(0.5)
    assert telemetry["inference_seconds"] == pytest.approx(3.5)
    assert telemetry["verification_seconds"] == pytest.approx(0.75)
    assert telemetry["restart_seconds"] == pytest.approx(0.75)
    assert telemetry["restart_count"] == 1
    assert telemetry["model_load_count"] == 2
    assert telemetry["preflight_count"] == 2
    assert telemetry["schema_version"]
    assert telemetry["proof_authority"] is False
