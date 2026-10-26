"""Hardware admission for country-IR builds. No GPU and no network."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import mem
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.resources import (
    GpuSnapshot,
    HostSnapshot,
    admit_parallelism,
    assign_device,
    backoff_seconds,
    can_admit,
    job_slots,
    probe_host,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors import encode_lock_path


def _snap(
    mem: float,
    disk: float = 500.0,
    gpus: tuple[GpuSnapshot, ...] = (
        GpuSnapshot(0, 20000, 24576),
        GpuSnapshot(1, 20000, 24576),
    ),
) -> HostSnapshot:
    return HostSnapshot(mem, disk, gpus)


def test_two_free_gpus_and_ram_open_both_devices() -> None:
    admission = admit_parallelism(_snap(40.0), ceiling=4)
    assert admission.workers == 4
    assert admission.devices == ("cuda:0", "cuda:1")
    assert admission.reason == "ok"
    assert admission.backoff_s == 0.0


def test_high_ram_opens_eight_country_slots() -> None:
    admission = admit_parallelism(_snap(64.0), ceiling=8)
    assert admission.workers == 8
    assert admission.devices == ("cuda:0", "cuda:1")


def test_tight_ram_shrinks_the_pool() -> None:
    admission = admit_parallelism(_snap(25.0), ceiling=4)
    assert admission.workers == 2
    assert admission.devices == ("cuda:0", "cuda:1")


def test_low_memory_disk_and_full_gpus_pause() -> None:
    memory = admit_parallelism(_snap(5.0), ceiling=4)
    assert memory.workers == 0
    assert memory.reason == "memory"
    assert memory.backoff_s == 15.0

    disk = admit_parallelism(_snap(40.0, disk=10.0), ceiling=4)
    assert disk.workers == 0
    assert disk.reason == "disk"

    full = admit_parallelism(
        _snap(40.0, gpus=(GpuSnapshot(0, 200, 24576), GpuSnapshot(1, 100, 24576))),
        ceiling=4,
    )
    assert full.workers == 0
    assert full.reason == "gpu"
    assert full.backoff_s == 10.0


def test_low_disk_caps_at_one_worker_and_cpu_has_no_gpu_slots() -> None:
    slow = admit_parallelism(_snap(40.0, disk=30.0), ceiling=4)
    assert slow.workers == 1
    assert slow.reason == "ok"

    cpu = admit_parallelism(_snap(40.0, gpus=()), ceiling=8)
    assert cpu.devices == ("cpu",)
    assert cpu.workers == 4


def test_backoff_doubles_and_large_corpora_take_more_slots() -> None:
    assert backoff_seconds(15.0, 0) == 15.0
    assert backoff_seconds(15.0, 1) == 30.0
    assert backoff_seconds(15.0, 2) == 60.0
    assert backoff_seconds(15.0, 8) == 120.0
    assert job_slots(0) == 1
    assert job_slots(20_000) == 1
    assert job_slots(200_000) == 2
    assert job_slots(2_000_000) == 4
    assert can_admit(0, 2, 1)
    assert can_admit(1, 2, 2) is False
    assert can_admit(4, 8, 4)
    assert can_admit(5, 8, 4) is False


def test_unchanged_rows_record_the_new_source_sha() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        stamp_source_revision,
    )

    old = "a" * 40
    new = "b" * 40
    manifest = {
        "dataset_revision": old,
        "source": {"source_revision": old},
        "normalization": {"source_revision": old},
        "incremental": {
            "source_revision": old,
            "prior_revision": old,
            "source_fingerprint": old + "|digest",
        },
    }
    assert stamp_source_revision(manifest, new) is True
    assert manifest["dataset_revision"] == new
    assert manifest["source"]["source_revision"] == new
    assert manifest["normalization"]["source_revision"] == new
    assert manifest["incremental"]["source_revision"] == new
    assert manifest["incremental"]["prior_revision"] == old
    assert manifest["incremental"]["source_fingerprint"] == new + "|digest"
    assert stamp_source_revision(manifest, new) is False


def test_evictable_zfs_arc_is_size_minus_c_min() -> None:
    text = "\n".join(
        (
            "26 1 0x01 147 39984 1 2",
            "name type data",
            "size 4 48320244936",
            "c_min 4 4220265472",
            "c 4 48412720112",
        )
    )
    stats = mem.parse_arc_kstat(text)
    evictable = mem.evictable_arc_bytes(stats["size"], stats["c_min"])
    assert evictable == 48320244936 - 4220265472
    assert mem.evictable_arc_gib(text) == pytest.approx(evictable / 1024**3)
    assert mem.evictable_arc_bytes(100, 250) == 0
    assert mem.evictable_arc_gib("name type data\nsize 4 100\n") == 0.0
    assert mem.evictable_arc_gib("") == 0.0


def test_schedulable_ram_includes_arc_and_abort_does_not(monkeypatch) -> None:
    assert mem.schedulable_gib(25.6, arc_gib=40.8) == pytest.approx(66.4)
    assert mem.schedulable_gib(-1.0, arc_gib=40.8) == -1.0
    assert mem.schedulable_gib(10.0, arc_gib=-5.0) == 10.0

    monkeypatch.setattr(mem, "mem_available_gib", lambda: 2.0)
    monkeypatch.setattr(mem, "rss_gib", lambda pid=None: 1.0)
    monkeypatch.setattr(mem, "evictable_arc_gib", lambda stats_text=None: 40.0)
    assert mem.schedulable_gib() == pytest.approx(42.0)
    with pytest.raises(mem.MemAbort, match="MEM_ABORT"):
        mem.checkpoint("zfs", shed=False, abort=True, log=lambda _msg: None)


def test_evictable_arc_opens_slots_without_weakening_the_raw_pause(monkeypatch, tmp_path) -> None:
    gpus = (GpuSnapshot(0, 20000, 24576), GpuSnapshot(1, 20000, 24576))
    raw = admit_parallelism(HostSnapshot(25.0, 500.0, gpus), ceiling=8)
    assert raw.workers == 2

    with_arc = admit_parallelism(
        HostSnapshot(25.0, 500.0, gpus, schedulable_gib=65.0),
        ceiling=8,
    )
    assert with_arc.workers == 8
    assert with_arc.reason == "ok"

    # ARC above c_min does not hide a host that is already under 6 GiB free.
    paused = admit_parallelism(
        HostSnapshot(4.0, 500.0, gpus, schedulable_gib=44.0),
        ceiling=8,
    )
    assert paused.workers == 0
    assert paused.reason == "memory"

    monkeypatch.setattr(mem, "mem_available_gib", lambda: 25.0)
    monkeypatch.setattr(mem, "evictable_arc_gib", lambda stats_text=None: 40.0)
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.resources._gpu_snapshots",
        lambda: list(gpus),
    )
    snap = probe_host(tmp_path)
    assert snap.mem_available_gib == 25.0
    assert snap.schedulable_gib == pytest.approx(65.0)
    assert admit_parallelism(snap, ceiling=8).workers == 8


def test_device_assignment_spreads_across_gpus_and_locks_are_per_device() -> None:
    assert assign_device(("cuda:0", "cuda:1"), ()) == "cuda:0"
    assert assign_device(("cuda:0", "cuda:1"), ("cuda:0",)) == "cuda:1"
    assert assign_device(("cuda:0", "cuda:1"), ("cuda:0", "cuda:1", "cuda:1")) == "cuda:0"
    assert encode_lock_path("cuda").name == "cuda.encode.0.lock"
    assert encode_lock_path("cuda:1").name == "cuda.encode.1.lock"
    assert encode_lock_path("cpu").name == "cpu.encode.lock"
