"""Executable evidence for runtime capability inventory safety.

The probes in this module are fully injected.  The tests therefore exercise
the benchmark contract without importing optional backends, contacting a
model service, invoking a solver, or reading a developer's real environment.
"""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from typing import Callable

import pytest

import benchmarks.logic_pipeline as logic_pipeline
from benchmarks.logic_pipeline import capabilities


Probe = Callable[
    [capabilities.ProbeContext],
    capabilities.CapabilityRecord,
]


def _record(
    kind: capabilities.CapabilityKind,
    *,
    status: capabilities.CapabilityStatus = capabilities.CapabilityStatus.AVAILABLE,
    identity: dict[str, object] | None = None,
    reason: str | None = None,
) -> capabilities.CapabilityRecord:
    return capabilities.CapabilityRecord(
        kind=kind,
        status=status,
        identity=(
            identity
            if identity is not None
            else {"implementation": f"test-{kind.value}", "version": "1"}
        ),
        provenance=("injected-test-probe",),
        reason=reason,
    )


def _available_probes() -> dict[capabilities.CapabilityKind, Probe]:
    return {
        kind: (lambda _context, kind=kind: _record(kind))
        for kind in capabilities.REQUIRED_CAPABILITY_KINDS
    }


def _probe(
    tmp_path: Path,
    *,
    probes: dict[capabilities.CapabilityKind, Probe] | None = None,
) -> capabilities.CapabilityInventory:
    paths = logic_pipeline.RunPaths.for_run(
        "capability-run-001",
        benchmark_root=tmp_path / "benchmark-state",
    )
    return capabilities.probe_runtime_capabilities(
        "capability-run-001",
        paths,
        probes=probes or _available_probes(),
    )


def test_objective_evidence_and_required_capability_set_are_stable() -> None:
    assert (
        capabilities.HSSLEV0125F83()
        == "runtime capabilities and identities"
    )
    assert capabilities.CAPABILITY_INVENTORY_SCHEMA.endswith(
        "capability-inventory.v1"
    )
    assert {kind.value for kind in capabilities.REQUIRED_CAPABILITY_KINDS} == {
        "spacy_pipeline",
        "symai",
        "llm_router",
        "hammer",
        "leanstral_service",
        "lean_toolchain",
        "cache_backend",
        "resource_scheduler",
    }


def test_capability_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {
        "hammer",
        "leanstral",
        "spacy",
        "symai",
        "symbolicai",
        "ipfs_datasets_py",
    }
    real_import = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.partition(".")[0] in forbidden:
            raise AssertionError(f"unexpected optional import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert capabilities.HSSLEV0125F83()


def test_probe_inventory_contains_exactly_one_record_for_every_kind(
    tmp_path: Path,
) -> None:
    inventory = _probe(tmp_path)

    assert inventory.run_id == "capability-run-001"
    assert tuple(record.kind for record in inventory.capabilities) == (
        capabilities.REQUIRED_CAPABILITY_KINDS
    )
    assert set(inventory.by_kind) == set(
        capabilities.REQUIRED_CAPABILITY_KINDS
    )
    assert all(
        record.status is capabilities.CapabilityStatus.AVAILABLE
        for record in inventory.capabilities
    )


@pytest.mark.parametrize(
    "status",
    [
        capabilities.CapabilityStatus.DEGRADED,
        capabilities.CapabilityStatus.UNAVAILABLE,
    ],
)
def test_non_available_records_require_an_explicit_reason(
    status: capabilities.CapabilityStatus,
) -> None:
    with pytest.raises(capabilities.CapabilityContractError, match="reason"):
        _record(capabilities.CapabilityKind.SYMAI, status=status)


def test_available_record_requires_identity_and_provenance() -> None:
    with pytest.raises(capabilities.CapabilityContractError, match="identity"):
        capabilities.CapabilityRecord(
            kind=capabilities.CapabilityKind.HAMMER,
            status=capabilities.CapabilityStatus.AVAILABLE,
            identity={},
            provenance=("probe",),
        )
    with pytest.raises(
        capabilities.CapabilityContractError, match="provenance"
    ):
        capabilities.CapabilityRecord(
            kind=capabilities.CapabilityKind.HAMMER,
            status=capabilities.CapabilityStatus.AVAILABLE,
            identity={"version": "1"},
            provenance=(),
        )


def test_degraded_spacy_preserves_requested_and_effective_identity(
    tmp_path: Path,
) -> None:
    probes = _available_probes()
    probes[capabilities.CapabilityKind.SPACY_PIPELINE] = lambda _context: _record(
        capabilities.CapabilityKind.SPACY_PIPELINE,
        status=capabilities.CapabilityStatus.DEGRADED,
        identity={
            "requested_model": "en_core_web_sm",
            "effective_model": "blank:en",
            "fallback": True,
            "spacy_version": "3.8.0",
        },
        reason="requested pipeline is absent; blank English fallback is usable",
    )

    record = _probe(tmp_path, probes=probes).by_kind[
        capabilities.CapabilityKind.SPACY_PIPELINE
    ]

    assert record.status is capabilities.CapabilityStatus.DEGRADED
    assert record.identity["requested_model"] == "en_core_web_sm"
    assert record.identity["effective_model"] == "blank:en"
    assert record.identity["fallback"] is True


def test_probe_exception_becomes_explicit_unavailable_and_does_not_abort(
    tmp_path: Path,
) -> None:
    probes = _available_probes()

    def explode(_context: capabilities.ProbeContext) -> capabilities.CapabilityRecord:
        raise RuntimeError("provider token=super-secret must not escape")

    probes[capabilities.CapabilityKind.LLM_ROUTER] = explode
    inventory = _probe(tmp_path, probes=probes)
    failed = inventory.by_kind[capabilities.CapabilityKind.LLM_ROUTER]

    assert failed.status is capabilities.CapabilityStatus.UNAVAILABLE
    assert failed.reason
    assert "RuntimeError" in failed.reason
    assert "super-secret" not in json.dumps(failed.to_dict())
    assert (
        inventory.by_kind[capabilities.CapabilityKind.HAMMER].status
        is capabilities.CapabilityStatus.AVAILABLE
    )


def test_missing_probe_is_recorded_unavailable_instead_of_omitted(
    tmp_path: Path,
) -> None:
    probes = _available_probes()
    del probes[capabilities.CapabilityKind.LEANSTRAL_SERVICE]

    inventory = _probe(tmp_path, probes=probes)
    missing = inventory.by_kind[
        capabilities.CapabilityKind.LEANSTRAL_SERVICE
    ]

    assert len(inventory.capabilities) == len(
        capabilities.REQUIRED_CAPABILITY_KINDS
    )
    assert missing.status is capabilities.CapabilityStatus.UNAVAILABLE
    assert missing.reason


def test_duplicate_and_incomplete_inventory_records_fail_closed() -> None:
    records = tuple(
        _record(kind) for kind in capabilities.REQUIRED_CAPABILITY_KINDS
    )
    with pytest.raises(
        capabilities.CapabilityContractError, match="duplicate"
    ):
        capabilities.CapabilityInventory.create(
            "run-001",
            records + (records[0],),
        )
    with pytest.raises(
        capabilities.CapabilityContractError, match="missing|exactly"
    ):
        capabilities.CapabilityInventory.create("run-001", records[:-1])


def test_inventory_is_deeply_immutable() -> None:
    inventory = capabilities.CapabilityInventory.create(
        "run-001",
        tuple(
            _record(kind)
            for kind in capabilities.REQUIRED_CAPABILITY_KINDS
        ),
    )

    with pytest.raises(FrozenInstanceError):
        inventory.run_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        inventory.by_kind[capabilities.CapabilityKind.SYMAI] = _record(  # type: ignore[index]
            capabilities.CapabilityKind.SYMAI
        )
    with pytest.raises(TypeError):
        inventory.capabilities[0].identity["version"] = "changed"  # type: ignore[index]


def test_inventory_round_trip_is_strict_and_digest_is_canonical() -> None:
    records = tuple(
        _record(
            kind,
            identity={
                "version": "1",
                "nested": {"z": 2, "a": 1},
            },
        )
        for kind in capabilities.REQUIRED_CAPABILITY_KINDS
    )
    first = capabilities.CapabilityInventory.create("run-001", records)
    reordered = capabilities.CapabilityInventory.create(
        "run-001", tuple(reversed(records))
    )

    assert first == reordered
    assert capabilities.capability_inventory_sha256(first) == (
        capabilities.capability_inventory_sha256(reordered)
    )
    assert capabilities.capability_inventory_cid(first) == (
        capabilities.capability_inventory_cid(reordered)
    )
    assert first.cid == capabilities.capability_inventory_cid(first)
    assert first.cid.startswith("b")
    encoded = capabilities.canonical_capability_inventory_json(first)
    restored = capabilities.CapabilityInventory.from_dict(json.loads(encoded))
    assert restored == first
    assert json.loads(encoded) == first.to_dict()


def test_inventory_deserialization_rejects_unknown_missing_and_invalid_fields() -> None:
    inventory = capabilities.CapabilityInventory.create(
        "run-001",
        tuple(
            _record(kind)
            for kind in capabilities.REQUIRED_CAPABILITY_KINDS
        ),
    )
    payload = inventory.to_dict()

    unknown = json.loads(json.dumps(payload))
    unknown["post_probe_fallback"] = True
    with pytest.raises(capabilities.CapabilityContractError, match="unknown"):
        capabilities.CapabilityInventory.from_dict(unknown)

    missing = json.loads(json.dumps(payload))
    del missing["run_id"]
    with pytest.raises(capabilities.CapabilityContractError, match="missing"):
        capabilities.CapabilityInventory.from_dict(missing)

    bad_status = json.loads(json.dumps(payload))
    bad_status["capabilities"][0]["status"] = "silently_substituted"
    with pytest.raises(
        capabilities.CapabilityContractError, match="status|unsupported"
    ):
        capabilities.CapabilityInventory.from_dict(bad_status)

    extra_record_field = json.loads(json.dumps(payload))
    extra_record_field["capabilities"][0]["selected_variant"] = "A0"
    with pytest.raises(capabilities.CapabilityContractError, match="unknown"):
        capabilities.CapabilityInventory.from_dict(extra_record_field)


def test_secret_redaction_is_recursive_and_sanitizes_endpoint_credentials() -> None:
    raw = {
        "model": "leanstral-119b",
        "api_key": "sk-plain-secret",
        "nested": {
            "authorization": "Bearer hidden-token",
            "password": "hunter2",
            "configured": True,
        },
        "endpoint": (
            "https://alice:password@example.test/v1?"
            "api_key=query-secret&model=leanstral"
        ),
    }

    redacted = capabilities.redact_secrets(raw)
    encoded = json.dumps(redacted, sort_keys=True)

    assert redacted["model"] == "leanstral-119b"
    for secret in (
        "sk-plain-secret",
        "hidden-token",
        "hunter2",
        "alice:password",
        "query-secret",
    ):
        assert secret not in encoded
    assert "example.test" in encoded


def test_identity_payload_rejects_non_json_and_nonfinite_values() -> None:
    for value in (object(), float("nan"), float("inf")):
        with pytest.raises(
            capabilities.CapabilityContractError,
            match="canonical JSON|finite|identity",
        ):
            _record(
                capabilities.CapabilityKind.HAMMER,
                identity={"bad": value},
            )


def test_require_capabilities_returns_requested_available_records(
    tmp_path: Path,
) -> None:
    inventory = _probe(tmp_path)
    required = capabilities.require_capabilities(
        inventory,
        (
            capabilities.CapabilityKind.SPACY_PIPELINE,
            capabilities.CapabilityKind.HAMMER,
        ),
    )

    assert tuple(record.kind for record in required) == (
        capabilities.CapabilityKind.SPACY_PIPELINE,
        capabilities.CapabilityKind.HAMMER,
    )


@pytest.mark.parametrize(
    "status",
    [
        capabilities.CapabilityStatus.DEGRADED,
        capabilities.CapabilityStatus.UNAVAILABLE,
    ],
)
def test_require_capabilities_fails_closed_without_silent_fallback(
    tmp_path: Path,
    status: capabilities.CapabilityStatus,
) -> None:
    probes = _available_probes()
    probes[capabilities.CapabilityKind.SPACY_PIPELINE] = lambda _context: _record(
        capabilities.CapabilityKind.SPACY_PIPELINE,
        status=status,
        identity={
            "requested_model": "en_core_web_sm",
            "effective_model": "blank:en",
        },
        reason="requested model is not fully available",
    )
    inventory = _probe(tmp_path, probes=probes)

    with pytest.raises(
        capabilities.CapabilityUnavailableError,
        match="spacy_pipeline",
    ):
        capabilities.require_capabilities(
            inventory,
            (capabilities.CapabilityKind.SPACY_PIPELINE,),
        )


def test_cache_backend_must_be_scoped_below_this_run_cache(
    tmp_path: Path,
) -> None:
    probes = _available_probes()
    probes[capabilities.CapabilityKind.CACHE_BACKEND] = lambda _context: _record(
        capabilities.CapabilityKind.CACHE_BACKEND,
        identity={
            "implementation": "filesystem",
            "root": (tmp_path / "production-cache").as_posix(),
        },
    )

    with pytest.raises(
        capabilities.CapabilityContractError,
        match="cache.*run|run.*cache|scope",
    ):
        _probe(tmp_path, probes=probes)


def test_resource_scheduler_state_must_be_scoped_below_this_run_state(
    tmp_path: Path,
) -> None:
    probes = _available_probes()
    probes[
        capabilities.CapabilityKind.RESOURCE_SCHEDULER
    ] = lambda _context: _record(
        capabilities.CapabilityKind.RESOURCE_SCHEDULER,
        identity={
            "implementation": "GlobalResourceScheduler",
            "schema": "legal-ir-global-resource-scheduler-v1",
            "state_path": (tmp_path / "production-scheduler.json").as_posix(),
        },
    )

    with pytest.raises(
        capabilities.CapabilityContractError,
        match="scheduler.*run|run.*state|scope",
    ):
        _probe(tmp_path, probes=probes)


def test_run_scoped_cache_and_scheduler_identities_are_accepted(
    tmp_path: Path,
) -> None:
    probes = _available_probes()

    def cache(context: capabilities.ProbeContext) -> capabilities.CapabilityRecord:
        return _record(
            capabilities.CapabilityKind.CACHE_BACKEND,
            identity={
                "implementation": "filesystem",
                "root": (context.run_paths.cache / "capabilities").as_posix(),
            },
        )

    def scheduler(
        context: capabilities.ProbeContext,
    ) -> capabilities.CapabilityRecord:
        return _record(
            capabilities.CapabilityKind.RESOURCE_SCHEDULER,
            identity={
                "implementation": "GlobalResourceScheduler",
                "schema": "legal-ir-global-resource-scheduler-v1",
                "state_path": (
                    context.run_paths.state / "resource-scheduler.json"
                ).as_posix(),
            },
        )

    probes[capabilities.CapabilityKind.CACHE_BACKEND] = cache
    probes[capabilities.CapabilityKind.RESOURCE_SCHEDULER] = scheduler
    inventory = _probe(tmp_path, probes=probes)

    assert (
        inventory.by_kind[capabilities.CapabilityKind.CACHE_BACKEND].status
        is capabilities.CapabilityStatus.AVAILABLE
    )
    assert (
        inventory.by_kind[
            capabilities.CapabilityKind.RESOURCE_SCHEDULER
        ].status
        is capabilities.CapabilityStatus.AVAILABLE
    )


def test_bounded_process_communication_error_reaps_owned_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Stream:
        closed = False

        def close(self) -> None:
            self.closed = True

    class FailedCommunicationProcess:
        pid = 424242
        returncode: int | None = None
        stdin = Stream()
        stdout = Stream()
        stderr = Stream()

        def communicate(self, **_kwargs: object) -> tuple[bytes, bytes]:
            raise OSError("injected communicate failure")

        def wait(self, **_kwargs: object) -> int:
            self.returncode = -15
            return self.returncode

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def poll(self) -> int | None:
            return self.returncode

    process = FailedCommunicationProcess()
    signals: list[tuple[int, int]] = []
    reaped: list[int] = []
    monkeypatch.setattr(
        capabilities.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        capabilities.os,
        "killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )
    monkeypatch.setattr(
        capabilities,
        "_reap_bounded_process_group",
        lambda pid, **_kwargs: reaped.append(pid) or True,
    )

    with pytest.raises(OSError, match="injected communicate failure"):
        capabilities.run_bounded_process_group(
            ("injected-command",),
            timeout_seconds=1,
        )

    assert signals == [(process.pid, capabilities.signal.SIGTERM)]
    assert process.returncode == -15
    assert reaped == [process.pid]
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True
