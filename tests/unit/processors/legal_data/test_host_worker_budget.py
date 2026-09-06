"""Unit tests for live CPU/RAM/swap worker admission."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.host_worker_budget import (
    BYTES_PER_WORKER,
    COMBINED_COLLAPSE,
    HostPressureSnapshot,
    combined_pressure,
    cpu_memory_worker_limit,
    heuristic_worker_cap,
    host_worker_pressure,
)

GIB = 1024 * 1024 * 1024


def _snap(**overrides: object) -> HostPressureSnapshot:
    values: dict[str, object] = {
        "nproc": 20,
        "load1": 1.0,
        "mem_available": 80 * GIB,
        "mem_total": 121 * GIB,
        "swap_free": 15 * GIB,
        "swap_total": 15 * GIB,
    }
    values.update(overrides)
    return HostPressureSnapshot(**values)  # type: ignore[arg-type]


def test_heuristic_worker_cap_is_half_the_machine() -> None:
    assert heuristic_worker_cap(1) == 1
    assert heuristic_worker_cap(2) == 1
    assert heuristic_worker_cap(20) == 10


def test_idle_host_admits_heuristic_workers() -> None:
    workers, reason = host_worker_pressure(_snap())
    assert reason == "admitted"
    assert workers == 10
    assert workers == heuristic_worker_cap(20)


def test_unused_cores_shrink_admission() -> None:
    workers, reason = host_worker_pressure(_snap(load1=12.0))
    assert reason == "admitted"
    assert workers == 8


def test_swap_alone_does_not_collapse_when_ram_and_cpu_are_free() -> None:
    workers, reason = host_worker_pressure(
        _snap(swap_free=0, swap_total=15 * GIB)
    )
    assert reason == "admitted"
    assert workers >= 8
    score, parts = combined_pressure(_snap(swap_free=0, swap_total=15 * GIB))
    assert parts["swap"] == 1.0
    assert score < COMBINED_COLLAPSE


def test_tiny_swap_free_does_not_collapse_when_ram_is_plentiful() -> None:
    workers, reason = host_worker_pressure(
        _snap(swap_free=128 * 1024 * 1024, swap_total=15 * GIB)
    )
    assert reason == "admitted"
    assert workers >= 8


def test_combined_ram_cpu_swap_collapses() -> None:
    workers, reason = host_worker_pressure(
        _snap(
            load1=19.0,
            mem_available=8 * GIB,
            mem_total=121 * GIB,
            swap_free=GIB,
            swap_total=15 * GIB,
        )
    )
    assert workers == 1
    assert reason == "host_combined_pressure"


def test_memory_headroom_collapses_to_one_worker() -> None:
    workers, reason = host_worker_pressure(
        _snap(mem_available=GIB, mem_total=121 * GIB)
    )
    assert workers == 1
    assert reason == "host_memory_headroom"


def test_cpu_memory_worker_limit_uses_heuristic_default() -> None:
    idle = _snap()
    assert cpu_memory_worker_limit(None, idle) == 10
    assert cpu_memory_worker_limit(32, idle) == 10
    assert cpu_memory_worker_limit(1, idle) == 1
    swap_only = _snap(swap_free=0, swap_total=15 * GIB)
    assert cpu_memory_worker_limit(32, swap_only) >= 8


def test_bytes_per_worker_limits_admission() -> None:
    workers, reason = host_worker_pressure(
        _snap(mem_available=3 * GIB, mem_total=10 * GIB)
    )
    assert reason == "admitted"
    assert workers == 1
    assert 3 * GIB // BYTES_PER_WORKER == 1
