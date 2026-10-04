"""Bounded PSI attribution must not change sampling, pressure gates or ledgers."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import (
    MAX_PRESSURE_CGROUP_SAMPLES, PressureReading, PressureScopeSample,
    ProofHostResources, ProofPressureSources, _psi, _psi_reading,
    collect_proof_host_resources,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, LeaseTimeoutError, ResourceSchedulerConfig,
)


def telemetry(tmp_path, monkeypatch, *, cgroups=2):
    proc, group = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "pressure").mkdir()
    leaf = group.joinpath(*(f"anonymous-{i}" for i in range(cgroups - 1)))
    leaf.mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n")
    relative = leaf.relative_to(group).as_posix()
    (proc / "self/cgroup").write_text(f"0::/{relative}\n")
    monkeypatch.setattr("os.sched_getaffinity", lambda _: set(range(8)))
    groups, current = [], leaf
    while True:
        groups.append(current)
        if current == group:
            break
        current = current.parent
    return proc, group, groups


def write_pressure(path, value, kind="full"):
    path.write_text(f"{kind} avg10={value} avg60=0 avg300=0 total=1\n")


def attribution(*, memory=0.0, cpu=0.0, io=0.0):
    return ProofPressureSources((PressureScopeSample("host", None,
        *(PressureReading(value, "observed") for value in (memory, cpu, io))),))


def scheduler(tmp_path, *, cooldown=0):
    current = [ProofHostResources(8, 8192, 8192)]
    calls = []

    def sample():
        calls.append(current[0])
        return current[0]

    config = ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "ledger.json", proof_resource_sampler=sample,
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=cooldown,
        poll_interval_seconds=.005)
    return GlobalResourceScheduler(config), current, calls


def test_scope_attribution_keeps_ties_and_original_read_order(tmp_path, monkeypatch):
    proc, group, groups = telemetry(tmp_path, monkeypatch)
    write_pressure(proc / "pressure/memory", 3.25)
    write_pressure(proc / "pressure/cpu", 12.5, "some")
    write_pressure(proc / "pressure/io", .5)
    write_pressure(groups[0] / "memory.pressure", 3.25)
    write_pressure(groups[0] / "cpu.pressure", 8, "some")
    write_pressure(groups[1] / "io.pressure", 7)
    (groups[0] / "cpu.max").write_text("250000 100000")
    (groups[0] / "memory.high").write_text(str(2 * 1024**3))
    (groups[0] / "memory.max").write_text(str(3 * 1024**3))
    (groups[0] / "memory.current").write_text(str(1536 * 1024**2))
    reads, read_text = [], Path.read_text

    def tracked_read(path, *args, **kwargs):
        reads.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read)
    host = collect_proof_host_resources(proc, group)
    expected = [proc / "meminfo", proc / "self/cgroup"]
    expected += [proc / f"pressure/{name}" for name in ("memory", "cpu", "io")]
    for depth, path in enumerate(groups):
        expected.append(path / "cpu.max")
        for limit in ("memory.high", "memory.max"):
            expected.append(path / limit)
            if depth == 0:
                expected.append(path / "memory.current")
        expected += [path / f"{name}.pressure" for name in ("memory", "cpu", "io")]
    assert reads == expected
    assert host == ProofHostResources(2, 2048, 512, 3.25, 12.5, 7)
    payload = host.pressure_sources.to_dict()
    assert [(row["scope"], row["depth"]) for row in payload["samples"]] == [
        ("host", None), ("cgroup", 0), ("cgroup", 1)]
    assert [row["memory"]["avg10"] for row in payload["samples"]] == [3.25, 3.25, None]
    assert payload["samples"][2]["io"] == {"avg10": 7.0, "status": "observed"}
    assert payload["omitted_cgroup_scopes"] == 0
    assert payload["omitted_maxima"] == dict(memory=None, cpu=None, io=None)
    assert "anonymous" not in json.dumps(payload)
    assert str(tmp_path) not in json.dumps(payload)


def test_metadata_cap_does_not_stop_ancestor_sampling_or_lose_maxima(tmp_path, monkeypatch):
    proc, group, groups = telemetry(tmp_path, monkeypatch, cgroups=11)
    write_pressure(proc / "pressure/cpu", 17.5, "some")
    write_pressure(groups[0] / "memory.pressure", 14.71)
    write_pressure(groups[8] / "memory.pressure", 14.71)
    write_pressure(groups[9] / "cpu.pressure", 17.5, "some")
    write_pressure(groups[10] / "io.pressure", 19.75)
    (groups[10] / "memory.high").write_text(str(1024**3))
    (groups[10] / "memory.current").write_text(str(768 * 1024**2))
    host = collect_proof_host_resources(proc, group)
    assert host == ProofHostResources(8, 1024, 256, 14.71, 17.5, 19.75)
    payload = host.pressure_sources.to_dict()
    assert len(payload["samples"]) == 1 + MAX_PRESSURE_CGROUP_SAMPLES
    assert payload["omitted_cgroup_scopes"] == 3
    assert payload["omitted_maxima"] == dict(memory=14.71, cpu=17.5, io=19.75)


def test_missing_and_malformed_omitted_telemetry_never_claims_observed_zero(tmp_path, monkeypatch):
    proc, group, groups = telemetry(tmp_path, monkeypatch, cgroups=9)
    write_pressure(groups[8] / "memory.pressure", "nan")
    write_pressure(groups[8] / "cpu.pressure", 0, "some")
    host = collect_proof_host_resources(proc, group)
    assert host == ProofHostResources(8, 8192, 6144)
    assert host.pressure_sources.to_dict()["omitted_maxima"] == dict(memory=None, cpu=0.0, io=None)


@pytest.mark.parametrize("contents,kind,expected,status", [
    (None, "full", 0, "unavailable"),
    ("", "full", 0, "unavailable"),
    ("some avg10=9\n", "full", 0, "unavailable"),
    ("full avg10=0\n", "full", 0, "observed"),
    ("some avg10=6.5\nfull avg10=9\n", "some", 6.5, "observed"),
    ("full avg10=nan\n", "full", 0, "malformed"),
    ("full avg10=inf\n", "full", 0, "malformed"),
    ("full avg10=-1\n", "full", 0, "malformed"),
    ("full avg10=101\n", "full", 0, "malformed"),
    ("full avg60=1\n", "full", 0, "malformed"),
    ("full avg10=invalid\nfull avg10=3\n", "full", 0, "malformed"),
    ("full avg10=nan\nfull avg10=3\n", "full", 3, "observed"),
    ("\nfull avg10=3\n", "full", 0, "malformed"),
])
def test_optional_psi_status_preserves_scalar_parser_behavior(tmp_path, contents, kind, expected, status):
    path = tmp_path / "pressure"
    if contents is not None:
        path.write_text(contents)
    reading = _psi_reading(path, kind)
    assert reading.status == status
    assert reading.avg10 == (expected if status == "observed" else None)
    assert reading.effective_percent == _psi(path, kind) == expected


def test_metadata_immutable_detached_and_excluded_from_host_equality():
    sources = attribution(memory=2)
    host = ProofHostResources(8, 8192, 8192, 2, pressure_sources=sources)
    assert host == replace(host, pressure_sources=None)
    assert hash(host) == hash(replace(host, pressure_sources=None))
    with pytest.raises(FrozenInstanceError):
        sources.samples[0].memory.avg10 = 90
    payload = sources.to_dict()
    payload["samples"][0]["memory"]["avg10"] = 90
    assert sources.to_dict()["samples"][0]["memory"]["avg10"] == 2


@pytest.mark.parametrize("factory", [
    lambda: PressureReading(True, "observed"),
    lambda: PressureReading(float("nan"), "observed"),
    lambda: PressureReading(0, "unavailable"),
    lambda: PressureScopeSample("/private/path", None, *(PressureReading(0, "observed"),) * 3),
    lambda: PressureScopeSample("cgroup", 8, *(PressureReading(0, "observed"),) * 3),
    lambda: ProofPressureSources(()),
    lambda: replace(attribution(), samples=attribution().samples * 10),
    lambda: replace(attribution(), omitted_cgroup_scopes=1),
    lambda: replace(attribution(), omitted_maxima=(1, None, None)),
])
def test_metadata_rejects_unbounded_or_ambiguous_shapes(factory):
    with pytest.raises(ValueError):
        factory()


def test_request_observation_adds_metadata_without_ledger_or_sampler_changes(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    owner, current, calls = scheduler(tmp_path, cooldown=2)
    current[0] = replace(current[0], memory_stall_percent=14.71,
        pressure_sources=attribution(memory=14.71))
    before = len(calls)
    with pytest.raises(LeaseTimeoutError) as first:
        owner.acquire("hammer", memory_mb=100, timeout=0)
    assert len(calls) == before + 1
    record = first.value.admission_observation
    assert record["last_sample"]["pressure_sources"] == current[0].pressure_sources.to_dict()
    assert record["last_sample"]["reason"] == "proof_memory_stall"
    with pytest.raises(LeaseTimeoutError) as second:
        owner.acquire("hammer", memory_mb=100, timeout=0)
    assert len(calls) == before + 1
    assert second.value.admission_observation["last_sample"] is None
    clock[0] += 2.1
    current[0] = replace(current[0], memory_stall_percent=5, pressure_sources=attribution(memory=5))
    with pytest.raises(LeaseTimeoutError) as third:
        owner.acquire("hammer", memory_mb=100, timeout=0)
    assert len(calls) == before + 2
    assert third.value.admission_observation["last_sample"]["pressure_sources"] != record["last_sample"]["pressure_sources"]
    state = owner.state_path.read_text()
    assert "pressure_sources" not in state and "avg10" not in state
    assert "pressure_sources" not in vars(owner.config)
    assert owner.snapshot()["active_lease_count"] == owner.snapshot()["waiting_request_count"] == 0


@pytest.mark.parametrize("bad_metadata", [None, {}, "unavailable", object()])
def test_legacy_custom_optional_metadata_does_not_change_gate(tmp_path, bad_metadata):
    owner, current, _ = scheduler(tmp_path)
    current[0] = replace(current[0], memory_stall_percent=4, pressure_sources=bad_metadata)
    with pytest.raises(LeaseTimeoutError) as caught:
        owner.acquire("hammer", memory_mb=100, timeout=0)
    record = caught.value.admission_observation
    assert record["primary_gate"]["reason"] == "proof_memory_stall"
    assert record["last_sample"]["host"]["memory_stall_percent"] == 4
    assert "pressure_sources" not in record["last_sample"]


def test_optional_metadata_projection_failure_preserves_valid_gate_and_sample(tmp_path):
    owner, current, _ = scheduler(tmp_path)
    sources = attribution(memory=4)
    object.__setattr__(sources.samples[0].memory, "avg10", float("nan"))
    current[0] = replace(current[0], memory_stall_percent=4, pressure_sources=sources)
    with pytest.raises(LeaseTimeoutError) as caught:
        owner.acquire("hammer", memory_mb=100, timeout=0)
    record = caught.value.admission_observation
    assert record["primary_gate"]["reason"] == "proof_memory_stall"
    assert record["last_sample"]["host"]["memory_stall_percent"] == 4
    assert "pressure_sources" not in record["last_sample"]
    assert owner.snapshot()["waiting_request_count"] == 0


def test_full_request_diagnostics_remain_bounded_with_long_floats(tmp_path):
    owner, current, _ = scheduler(tmp_path)
    reading = PressureReading(1.2345678901234567e-100, "observed")
    sources = ProofPressureSources((PressureScopeSample("host", None, reading, reading, reading),) + tuple(
        PressureScopeSample("cgroup", depth, reading, reading, reading) for depth in range(8)),
        2**53 - 1, (reading.avg10,) * 3)
    current[0] = replace(current[0], available_memory_mb=0, memory_stall_percent=reading.avg10,
        cpu_stall_percent=reading.avg10, io_stall_percent=reading.avg10, pressure_sources=sources)
    with pytest.raises(LeaseTimeoutError) as caught:
        owner.acquire("hammer", memory_mb=100, timeout=0)
    record = caught.value.admission_observation
    assert record["last_sample"]["pressure_sources"] == sources.to_dict()
    assert len(json.dumps(record, allow_nan=False).encode()) < 4096
