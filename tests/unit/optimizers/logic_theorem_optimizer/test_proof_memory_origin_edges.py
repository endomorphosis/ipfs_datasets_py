"""Counter decoding and visible ancestor failures must block proof admission."""
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import proof_resource_safety as probe
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources


@pytest.fixture
def hierarchy(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    group = tmp_path / "cgroup"
    leaf = group / "worker"
    (proc / "self").mkdir(parents=True)
    leaf.mkdir(parents=True)
    (proc / "meminfo").write_text("MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n")
    (proc / "self/cgroup").write_text("0::/worker\n")
    for path in (group, leaf):
        (path / "memory.high").write_text(str(1024 * probe.MIB))
        (path / "memory.max").write_text(str(1024 * probe.MIB))
        (path / "memory.current").write_text(str(256 * probe.MIB))
    monkeypatch.setattr(probe.os, "sched_getaffinity", lambda _: set(range(8)))
    return proc, group, leaf


@pytest.mark.parametrize("level", [1, 2], ids=["ancestor", "leaf"])
@pytest.mark.parametrize("name", ["memory.high", "memory.max", "memory.current"])
@pytest.mark.parametrize("raw", [b"\xff", b"1\x00", b" " * 4097],
                         ids=["invalid-ascii", "embedded-nul", "overlong-whitespace"])
def test_invalid_raw_counter_cannot_discard_visible_limit(hierarchy, level, name, raw):
    (hierarchy[level] / name).write_bytes(raw)
    with pytest.raises(ValueError):
        probe.collect_proof_host_resources(*hierarchy[:2])


@pytest.mark.parametrize("name", ["memory.high", "memory.max", "memory.current"])
@pytest.mark.parametrize("failure", [PermissionError, OSError], ids=["permission", "io"])
def test_unreadable_ancestor_counter_cannot_discard_visible_limit(hierarchy, monkeypatch, name, failure):
    target = hierarchy[1] / name
    original = Path.open

    def open_counter(self, *args, **kwargs):
        if self == target:
            raise failure("synthetic unreadable ancestor")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_counter)
    with pytest.raises(failure):
        probe.collect_proof_host_resources(*hierarchy[:2])


@pytest.mark.parametrize("level", [1, 2], ids=["ancestor", "leaf"])
@pytest.mark.parametrize("name", ["memory.high", "memory.max", "memory.current"])
def test_exact_raw_byte_bound_keeps_valid_capacity(hierarchy, level, name):
    value = str((256 if name == "memory.current" else 1024) * probe.MIB).encode("ascii")
    (hierarchy[level] / name).write_bytes(b" " * (4096 - len(value)) + value)
    snapshot = probe.collect_proof_host_resources(*hierarchy[:2])
    assert snapshot.total_memory_mb == 1024
    assert snapshot.available_memory_mb == 768


@pytest.mark.parametrize("nested", [False, True], ids=["root", "child"])
@pytest.mark.parametrize("level", [1, 2], ids=["ancestor", "leaf"])
@pytest.mark.parametrize("name", ["memory.high", "memory.max", "memory.current"])
def test_decoding_failure_backs_off_without_releasing_live_work(hierarchy, tmp_path, monkeypatch, nested, level, name):
    clock = [1000.0]
    monkeypatch.setattr(resources.time, "time", lambda: clock[0])
    config = resources.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "leases.json",
        proof_resource_sampler=lambda: probe.collect_proof_host_resources(*hierarchy[:2]),
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=0.1,
    )
    scheduler = resources.GlobalResourceScheduler(config)
    parent = scheduler.acquire("hammer", cpu_slots=2, memory_mb=128, timeout=0) if nested else None
    target = hierarchy[level] / name
    healthy = target.read_bytes()
    try:
        target.write_bytes(b"\xff")
        assert scheduler.try_acquire("hammer", memory_mb=64, parent=parent) is None
        paused = scheduler.snapshot()
        assert paused["proof_backoff"]["reason"] == "proof_resource_telemetry_unknown"
        assert paused["active_lease_count"] == int(nested)
        assert paused["waiting_request_count"] == 0
        target.write_bytes(healthy)
        assert scheduler.try_acquire("hammer", memory_mb=64, parent=parent) is None
        clock[0] += config.proof_backoff_seconds + 0.01
        with scheduler.acquire("hammer", memory_mb=64, parent=parent, timeout=0):
            pass
        assert scheduler.snapshot()["proof_backoff"] == {}
    finally:
        target.write_bytes(healthy)
        if parent is not None:
            parent.release()
    assert scheduler.snapshot()["active_lease_count"] == 0
