"""Bounded installed-runtime preparation, with no downloads or installers."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import zipfile

import pytest

from ipfs_datasets_py.logic.backends.installers import state_model as legacy
from ipfs_datasets_py.logic.backends.installers import state_model_preparation as preparation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig,
)


@pytest.fixture
def owner(tmp_path):
    current = [ProofHostResources(4, 4096, 4096)]
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: current[0],
        lane_reservations={}, total_cpu_slots=3, total_memory_mb=3000,
        proof_memory_headroom_mb=512, total_child_process_slots=2,
        auto_renew_leases=False, poll_interval_seconds=.01, proof_backoff_seconds=.02,
    ))
    yield scheduler, current
    assert scheduler.snapshot()["active_root_lease_count"] == 0
    assert scheduler.snapshot()["waiting_request_count"] == 0


@pytest.fixture
def fixture_toolchain(tmp_path, monkeypatch):
    """Synthetic identity fixtures; native JVM qualification is a separate test."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", (
            "Manifest-Version: 1.0\nX-Git-Tag: v1.8.0\n"
            "X-Git-ShortRevision: 30cc360\n"
            "X-Git-Revision: 30cc3601321c3fc02e044d0ecb5c58d8921e18df\n\n"
        ))
    payload = buffer.getvalue()
    monkeypatch.setattr(legacy, "TLC_SHA256", hashlib.sha256(payload).hexdigest())
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(payload)

    def java(mode="normal"):
        executable = tmp_path / ("fixture-java-" + mode)
        code = f'''#!{Path(sys.executable).resolve()}
import sys,time
mode={mode!r}
if mode == 'slow':
    print('starting', flush=True)
    time.sleep(30)
if sys.argv[-1] == '-version':
    print('openjdk version "' + ('1.8.0_482' if mode == 'wrong_version' else '21.0.9') + '"')
    sys.exit(3 if mode == 'bad_java_exit' else 0)
print('TLC - provides model checking and simulation of TLA+ specifications - Version fixture')
print('SYNOPSIS')
print('DESCRIPTION')
if mode == 'truncated':
    print('x' * 200000)
sys.exit(7 if mode == 'bad_help_exit' else 1)
'''
        executable.write_text(code)
        executable.chmod(0o700)
        return executable
    return jar, java


def _run(owner, fixture_toolchain, mode="normal", **kwargs):
    jar, java = fixture_toolchain
    return preparation.prepare_tlc_runtime(
        java_executable=java(mode), jar_path=jar, scheduler=owner[0], **kwargs,
    )


def test_separate_native_children_and_limits_share_one_owner(owner, fixture_toolchain):
    observed_children = []

    def progress(phase, _):
        if phase in {"java_probe", "tlc_probe"}:
            roots = owner[0].active_leases()
            assert len(roots) == 1
            observed_children.append(phase)

    result = _run(owner, fixture_toolchain, on_progress=progress)
    assert result.usable, result.to_dict()
    assert observed_children == ["java_probe", "tlc_probe"]
    report = result.to_dict()
    assert report["installation_performed"] is report["model_check_executed"] is False
    assert report["grants_proof_authority"] is report["grants_repository_authority"] is False
    assert len(report["probes"]) == 2
    assert len({probe["child_lease_id"] for probe in report["probes"]}) == 2
    assert report["limits"]["resident_memory_bytes"] == 256 * 1024**2
    assert report["limits"]["reservation_memory_mb"] == 384
    assert report["limits"]["address_space_bytes"] == 4 * 1024**3
    assert all(probe["observation"]["workspace_cleaned"] for probe in report["probes"])
    assert report["probes"][1]["timeout_seconds"] < report["probes"][0]["timeout_seconds"]
    assert len(result.digest) == 64


def test_external_pressure_between_probes_backs_off_then_resumes(owner, fixture_toolchain):
    timer = None
    pressured_at = []

    def progress(phase, _):
        nonlocal timer
        if phase == "tlc_probe":
            healthy = owner[1][0]
            owner[1][0] = replace(healthy, available_memory_mb=100)
            pressured_at.append(time.monotonic())
            timer = threading.Timer(.2, lambda: owner[1].__setitem__(0, healthy))
            timer.start()

    try:
        result = _run(owner, fixture_toolchain, on_progress=progress, timeout_seconds=3)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.usable, result.to_dict()
    assert time.monotonic() - pressured_at[0] >= .19
    assert len(result.probes) == 2
    assert owner[0].snapshot()["counters"]["saturation_events_total"] > 0


def test_cancellation_while_pressure_blocks_second_probe_cleans_waiter(owner, fixture_toolchain):
    signal = threading.Event()
    timer = None

    def progress(phase, _):
        nonlocal timer
        if phase == "tlc_probe":
            owner[1][0] = replace(owner[1][0], available_memory_mb=100)
            timer = threading.Timer(.1, signal.set)
            timer.start()

    try:
        result = _run(owner, fixture_toolchain, on_progress=progress, cancellation=signal)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.status == "cancelled"
    assert len(result.probes) == 1


@pytest.mark.parametrize("phase", ["admission", "admitted", "java_probe", "tlc_probe", "complete"])
def test_progress_callback_cancellation_never_returns_usable(owner, fixture_toolchain, phase):
    signal = threading.Event()
    result = _run(owner, fixture_toolchain, cancellation=signal,
        on_progress=lambda current, _: signal.set() if current == phase else None)
    assert result.status == "cancelled"
    assert len(result.probes) == (2 if phase == "complete" else 1 if phase == "tlc_probe" else 0)


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_live_child_stops_before_lease_release(owner, fixture_toolchain, stop):
    signal = threading.Event()
    timer = None
    if stop == "cancel":
        timer = threading.Timer(.25, signal.set)
        timer.start()
    try:
        result = _run(owner, fixture_toolchain, "slow", timeout_seconds=.5,
                      cancellation=signal)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.status == ("cancelled" if stop == "cancel" else "timed_out")
    assert len(result.probes) == 1
    observation = result.probes[0].to_dict()["observation"]
    assert observation["process_tree_terminated"]
    assert observation["workspace_cleaned"]
    assert observation["pid"] is not None
    assert not Path(f"/proc/{observation['pid']}").exists()


@pytest.mark.parametrize("mode,reason", [
    ("truncated", "bounded_probe_incomplete"),
    ("wrong_version", "java_version_unsupported"),
    ("bad_java_exit", "java_version_unsupported"),
    ("bad_help_exit", "runtime_probe_failed"),
])
def test_truncation_and_wrong_versions_fail_closed(owner, fixture_toolchain, mode, reason):
    result = _run(owner, fixture_toolchain, mode)
    assert not result.usable
    assert result.reason_code == reason


@pytest.mark.parametrize("target", ["java", "jar", "manifest"])
def test_fifo_inputs_refused_without_blocking_or_native_launch(owner, fixture_toolchain, tmp_path, target):
    jar, make_java = fixture_toolchain
    java = make_java()
    fifo = tmp_path / "input-fifo"
    os.mkfifo(fifo)
    kwargs = {"java_executable": java, "jar_path": jar}
    if target == "manifest":
        (tmp_path / "manifests").mkdir()
        fifo.rename(tmp_path / "manifests/tlc.json")
        kwargs.update(java_executable=None, install_root=tmp_path)
    else:
        kwargs["java_executable" if target == "java" else "jar_path"] = fifo
    before = time.monotonic()
    result = preparation.prepare_tlc_runtime(scheduler=owner[0], **kwargs)
    assert result.reason_code == "invalid_or_oversized_artifact"
    assert not result.usable and not result.probes
    assert time.monotonic() - before < 1


def test_borrowed_parent_is_preserved_and_underfunded_parent_refused(owner, fixture_toolchain):
    jar, make_java = fixture_toolchain
    with owner[0].acquire("validation", cpu_slots=1, memory_mb=300, child_process_slots=1) as parent:
        result = preparation.prepare_tlc_runtime(
            parent_lease=parent, java_executable=make_java(), jar_path=jar,
        )
        assert result.status == "admission_denied"
        assert result.reason_code == "underfunded_parent_lease"
        assert not result.probes and not parent.released
        assert len(owner[0].active_leases()) == 1
    with owner[0].acquire("validation", cpu_slots=1, memory_mb=384, child_process_slots=1) as parent:
        result = preparation.prepare_tlc_runtime(
            parent_lease=parent, java_executable=make_java(), jar_path=jar,
        )
        assert result.usable
        assert not parent.released and len(owner[0].active_leases()) == 1


def test_admission_wait_is_part_of_total_deadline(owner, fixture_toolchain):
    owner[1][0] = replace(owner[1][0], available_memory_mb=100)
    result = _run(owner, fixture_toolchain, timeout_seconds=.1)
    assert result.status == "timed_out"
    assert not result.probes and not result.resource_lease_id


def test_default_managed_selection_reads_bounded_manifest_after_admission(owner, fixture_toolchain, tmp_path):
    jar, make_java = fixture_toolchain
    java = make_java()
    path = tmp_path / "managed"
    (path / "tlc/1.8.0").mkdir(parents=True)
    (path / "tlc/1.8.0/tla2tools.jar").write_bytes(jar.read_bytes())
    (path / "manifests").mkdir()
    (path / "manifests/tlc.json").write_text(json.dumps({
        "schema_version": legacy._MANIFEST_SCHEMA, "tool_id": "tlc", "version": legacy.TLC_VERSION,
        "artifact_sha256": legacy.TLC_SHA256, "payload_sha256": legacy.TLC_SHA256,
        "java_executable": str(java),
    }))
    result = preparation.prepare_tlc_runtime(scheduler=owner[0], install_root=path)
    assert result.usable
    assert "selection_manifest_sha256" in result.bindings.to_dict()


def test_unpinned_jar_refused_before_native_execution(owner, fixture_toolchain):
    fixture_toolchain[0].write_bytes(b"not the immutable reviewed artifact")
    result = _run(owner, fixture_toolchain)
    assert result.reason_code == "tlc_artifact_checksum_mismatch"
    assert not result.probes


def test_real_installed_java_and_tlc_preparation(owner):
    root = Path.home() / ".local/share/ipfs_datasets_py/theorem-provers"
    if not (root / "manifests/tlc.json").is_file():
        pytest.skip("native managed Java/TLC installation must already exist")
    result = preparation.prepare_tlc_runtime(scheduler=owner[0], install_root=root)
    assert result.usable, result.to_dict()
    assert len(result.probes) == 2
    assert result.bindings.to_dict()["jar"]["sha256"] == legacy.TLC_SHA256
    assert result.bindings.to_dict()["java"]["major"] >= 11
    assert result.probes[1].to_dict()["observation"]["returncode"] == 1
