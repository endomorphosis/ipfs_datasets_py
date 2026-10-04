"""Finite cgroup memory boundaries cannot disappear during proof admission."""
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import proof_resource_safety as probe
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler_module


@pytest.fixture
def hierarchy(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    group = tmp_path / "cgroup"
    leaf = group / "worker"
    (proc / "self").mkdir(parents=True)
    leaf.mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n")
    (proc / "self/cgroup").write_text("0::/worker\n")
    monkeypatch.setattr(probe.os, "sched_getaffinity", lambda _: set(range(8)))
    return proc, group, leaf


def sample(hierarchy):
    return probe.collect_proof_host_resources(*hierarchy[:2])


def boundary(path, name="memory.max", limit_mb=4096, used_mb=1024):
    (path / name).write_text(str(limit_mb * probe.MIB))
    (path / "memory.current").write_text(str(used_mb * probe.MIB))


@pytest.mark.parametrize("level", [1, 2], ids=["ancestor", "leaf"])
@pytest.mark.parametrize("name", ["memory.high", "memory.max"])
@pytest.mark.parametrize("value", [None, "", "max", "-1", "+1", "1_024", "1.5", "123 extra", "１２３", "9" * 4097],
                         ids=["missing", "empty", "unlimited-usage", "negative", "signed", "separator", "fraction", "trailing", "unicode", "overlong"])
def test_finite_boundary_requires_valid_usage(hierarchy, level, name, value):
    path = hierarchy[level]
    boundary(path, name)
    usage = path / "memory.current"
    if value is None:
        usage.unlink()
    else:
        usage.write_text(value)
    with pytest.raises((OSError, ValueError)):
        sample(hierarchy)


@pytest.mark.parametrize("name", ["memory.high", "memory.max"])
@pytest.mark.parametrize("value", ["", "MAX", "-1", "+1", "1_024", "1.5", "12 34", "１２３", "9" * 4097],
                         ids=["empty", "wrong-token", "negative", "signed", "separator", "fraction", "trailing", "unicode", "overlong"])
def test_malformed_present_boundary_is_unknown(hierarchy, name, value):
    boundary(hierarchy[2])
    (hierarchy[2] / name).write_text(value)
    with pytest.raises(ValueError):
        sample(hierarchy)


@pytest.mark.parametrize("name", ["memory.high", "memory.max", "memory.current"])
@pytest.mark.parametrize("failure", [PermissionError, OSError], ids=["permission", "io"])
def test_unreadable_present_counter_is_unknown(hierarchy, monkeypatch, name, failure):
    path = hierarchy[2]
    boundary(path)
    (path / "memory.high").write_text("max")
    original = Path.open

    def open_counter(self, *args, **kwargs):
        if self == path / name:
            raise failure("synthetic unavailable counter")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_counter)
    with pytest.raises(failure):
        sample(hierarchy)


@pytest.mark.parametrize("controls", [(), ("memory.high",), ("memory.max",), ("memory.high", "memory.max")])
def test_absent_or_unlimited_controls_do_not_require_usage(hierarchy, controls):
    for name in controls:
        (hierarchy[2] / name).write_text("max\n")
    (hierarchy[2] / "memory.current").write_text("not needed")
    result = sample(hierarchy)
    assert result.total_memory_mb == 8192
    assert result.available_memory_mb == 6144


def test_tightest_ancestor_and_leaf_boundaries_both_apply(hierarchy):
    boundary(hierarchy[1], limit_mb=6144, used_mb=5632)
    boundary(hierarchy[2], limit_mb=4096, used_mb=1024)
    (hierarchy[2] / "memory.high").write_text(str(2048 * probe.MIB))
    result = sample(hierarchy)
    assert result.total_memory_mb == 2048
    assert result.available_memory_mb == 512


@pytest.mark.parametrize("used_mb", [4096, 4097])
def test_limit_at_or_below_current_usage_reports_no_capacity(hierarchy, used_mb):
    boundary(hierarchy[2], used_mb=used_mb)
    result = sample(hierarchy)
    assert result.total_memory_mb == 4096
    assert result.available_memory_mb == 0


def test_valid_usage_accepts_zero_and_ascii_whitespace(hierarchy):
    boundary(hierarchy[2])
    (hierarchy[2] / "memory.current").write_text(" \t0\n")
    assert sample(hierarchy).available_memory_mb == 4096


def test_finite_zero_boundary_does_not_invent_positive_capacity(hierarchy):
    boundary(hierarchy[2], limit_mb=0, used_mb=0)
    with pytest.raises(ValueError, match="invalid host memory telemetry"):
        sample(hierarchy)


def test_optional_psi_stays_optional_under_finite_limits(hierarchy, monkeypatch):
    boundary(hierarchy[2])
    (hierarchy[2] / "memory.pressure").write_text("full avg10=malformed\n")
    original = Path.open

    def open_counter(self, *args, **kwargs):
        if self.name == "cpu.pressure":
            raise PermissionError("optional PSI unavailable")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_counter)
    result = sample(hierarchy)
    assert result.available_memory_mb == 3072
    assert result.memory_stall_percent == 0
    assert result.cpu_stall_percent == 0
    assert result.io_stall_percent == 0


def _default_scheduler(hierarchy, tmp_path, monkeypatch):
    monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_RESOURCE_CPU_SLOTS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_RESOURCE_MEMORY_MB", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_RESOURCE_SCHEDULER_PATH", str(tmp_path / "memory-pool.json"))
    monkeypatch.setattr(scheduler_module, "collect_proof_host_resources", lambda: sample(hierarchy))
    return scheduler_module.GlobalResourceScheduler()


@pytest.mark.parametrize("nested", [False, True], ids=["root", "child"])
@pytest.mark.parametrize("level", [1, 2], ids=["ancestor", "leaf"])
def test_default_admission_backs_off_on_unknown_usage_and_recovers(hierarchy, tmp_path, monkeypatch, nested, level):
    boundary(hierarchy[level])
    scheduler = _default_scheduler(hierarchy, tmp_path, monkeypatch)
    assert scheduler.config.proof_safety_enabled
    clock = [1000.0]
    monkeypatch.setattr(scheduler_module.time, "time", lambda: clock[0])
    parent = scheduler.acquire("hammer", cpu_slots=2, memory_mb=256, timeout=0) if nested else None
    usage = hierarchy[level] / "memory.current"
    try:
        usage.write_text("unreadable observation")
        assert scheduler.try_acquire("hammer", cpu_slots=1, memory_mb=128, parent=parent) is None
        snapshot = scheduler.snapshot()
        assert snapshot["proof_backoff"]["reason"] == "proof_resource_telemetry_unknown"
        assert snapshot["active_lease_count"] == int(nested)
        assert snapshot["waiting_request_count"] == 0
        usage.write_text(str(1024 * probe.MIB))
        # A repaired counter still honors the existing shared cooldown.
        assert scheduler.try_acquire("hammer", cpu_slots=1, memory_mb=128, parent=parent) is None
        clock[0] += scheduler.config.proof_backoff_seconds + 0.1
        with scheduler.acquire("hammer", cpu_slots=1, memory_mb=128, parent=parent, timeout=0):
            pass
        assert scheduler.snapshot()["proof_backoff"] == {}
    finally:
        if parent is not None:
            parent.release()
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_default_initialization_refuses_unknown_finite_usage(hierarchy, tmp_path, monkeypatch):
    boundary(hierarchy[2])
    (hierarchy[2] / "memory.current").unlink()
    with pytest.raises(FileNotFoundError):
        _default_scheduler(hierarchy, tmp_path, monkeypatch)
