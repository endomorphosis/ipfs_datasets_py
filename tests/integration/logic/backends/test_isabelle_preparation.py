"""Bounded installed-Isabelle preparation; synthetic controls and real smoke."""
from dataclasses import replace
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.installers import isabelle as legacy
from ipfs_datasets_py.logic.backends.installers import isabelle_preparation as prep
from ipfs_datasets_py.logic.backends.installers import isabelle_profile as profile
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig,
)


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(16, 16384, 16384)
    telemetry = [healthy]
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "leases.json", proof_resource_sampler=lambda: telemetry[0],
        total_cpu_slots=6, total_memory_mb=8192, total_child_process_slots=16,
        lane_reservations={}, proof_memory_headroom_mb=512,
        proof_backoff_seconds=.02, poll_interval_seconds=.01,
    ))
    yield scheduler, telemetry, healthy
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert scheduler.snapshot()["waiting_request_count"] == 0


@pytest.fixture
def distribution(tmp_path):
    """Owner-controlled fake native executable; not native theorem evidence."""
    outer = tmp_path / "installed"
    root = outer / legacy.ISABELLE_VERSION
    for directory in (root / "bin", root / "etc", root / "lib/scripts", outer / "bin"):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "etc/ISABELLE_IDENTIFIER").write_text(legacy.ISABELLE_VERSION)
    for name in ("etc/settings", "etc/components", "lib/scripts/getsettings"):
        (root / name).write_text("# controlled fixture\n")
    (outer / "bin/isabelle").write_text("# wrapper must not execute\n")
    (outer / "bin/isabelle").chmod(0o700)
    executable = root / "bin/isabelle"
    executable.write_text(f'''#!{Path(sys.executable).resolve()}
from pathlib import Path
import sys,time
root=Path(__file__).parent.parent
mode=(root/'behavior').read_text() if (root/'behavior').exists() else 'normal'
command=sys.argv[1:]
if mode=='slow':
    print('starting',flush=True)
    time.sleep(30)
if command==['version']:
    print('wrong-version' if mode=='wrong_version' else {legacy.ISABELLE_VERSION!r})
elif command==['process_theories','-?']:
    print('missing-tool' if mode=='wrong_help' else 'Usage: isabelle process_theories [OPTIONS] [THEORIES...]')
    sys.exit(1)
elif command[0]=='build':
    assert '-n' in command and '-b' in command
    sys.exit(1 if mode=='missing_hol' else 0)
else:
    assert command[0]=='process_theories'
    assert 'quick_and_dirty=false' in command
    source=Path('IPFSSetupCheck.thy').read_text()
    assert 'lemma ready: "True" by simp' in source
    assert '@{{thm ready}}' in source
    if mode=='truncated':
        print('x'*200000)
    if mode!='missing_marker':
        print('IPFS_ISABELLE_KERNEL_CHECKED')
    if mode=='error_marker':
        print('*** Synthetic theorem failure')
    if mode=='wrong_exit':
        sys.exit(3)
''')
    executable.chmod(0o700)
    return outer, root, executable


def run(owner, distribution, **kwargs):
    return prep.prepare_isabelle_runtime(install_root=distribution[0], scheduler=owner[0], **kwargs)


@pytest.mark.parametrize("mode,phases,level", [
    ("command", ["version", "theory_help"], "command"),
    ("hol", ["version", "theory_help", "hol_no_build"], "hol_ready"),
    ("smoke", ["version", "theory_help", "hol_no_build", "smoke"], "kernel_smoke"),
])
def test_synthetic_stages_use_fresh_native_children_and_exact_limits(owner, distribution, monkeypatch, mode, phases, level):
    launches = []
    original = process.SubprocessExecutor.execute
    def observe(self, invocation, cancellation=None):
        rows = owner[0].active_leases()
        assert len(rows) == 2 and sum(not row.get("parent_lease_id") for row in rows) == 1
        launches.append(invocation)
        return original(self, invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", observe)
    result = run(owner, distribution, mode=mode)
    assert result.usable, result.to_dict()
    assert result.readiness_level == level
    assert [row["phase"] for row in result.probes] == phases
    assert len({row["child_lease_id"] for row in result.probes}) == len(phases)
    report = result.to_dict()
    assert report["executable"] == str(distribution[2])
    assert report["command_available"]
    assert report["hol_ready"] is (mode != "command")
    assert report["smoke_accepted"] is (mode == "smoke")
    assert not report["installation_performed"] and not report["explicit_heap_build_requested"]
    assert report["grants_proof_authority"] is report["grants_repository_authority"] is False
    assert len(result.digest) == 64
    assert report["limits"]["reservation_memory_mb"] == 2304
    for invocation in launches:
        assert invocation.limits.resident_memory_bytes == 2 * 1024**3
        assert invocation.limits.memory_bytes == 32 * 1024**3
        assert invocation.limits.cpu_seconds > 0
        assert invocation.environment["HOME"] == invocation.environment["TMPDIR"] == str(invocation.cwd)
        assert "USER_HOME" not in invocation.environment
        assert "-Xmx256m" in invocation.environment["JDK_JAVA_OPTIONS"]
        assert not Path(invocation.cwd).exists()
    for row in report["probes"]:
        assert len(row["input_sha256"]) >= 2
        assert row["observation"]["workspace_cleaned"]


@pytest.mark.parametrize("selection", ["root", "inner", "wrapper", "executable", "managed"])
def test_default_owner_and_finite_static_root_resolution(owner, distribution, monkeypatch, selection):
    monkeypatch.setattr(prep, "get_global_resource_scheduler", lambda: owner[0])
    outer, root, executable = distribution
    kwargs = {"install_root": outer}
    if selection == "inner":
        kwargs = {"install_root": root}
    elif selection in {"wrapper", "executable"}:
        kwargs = {"executable": outer / "bin/isabelle" if selection == "wrapper" else executable}
    elif selection == "managed":
        monkeypatch.setattr(legacy, "expand_user_local_root", lambda: outer)
        kwargs = {}
    result = prep.prepare_isabelle_runtime(**kwargs)
    assert result.usable, result.to_dict()
    assert result.to_dict()["native_runtime"]["runtime_root"] == str(root)


@pytest.mark.parametrize("mode,reason", [
    ("wrong_version", "isabelle_version_mismatch"),
    ("wrong_help", "isabelle_theory_processor_unavailable"),
    ("missing_hol", "hol_heap_build_required"),
    ("truncated", "bounded_probe_incomplete"),
    ("missing_marker", "smoke_not_accepted"),
    ("error_marker", "smoke_not_accepted"),
    ("wrong_exit", "smoke_not_accepted"),
])
def test_unusable_or_incomplete_stages_never_promote_readiness(owner, distribution, mode, reason):
    (distribution[1] / "behavior").write_text(mode)
    result = run(owner, distribution, mode="smoke")
    assert not result.usable and not result.smoke_accepted
    assert result.reason_code == reason
    if mode == "missing_hol":
        assert [row["phase"] for row in result.probes] == ["version", "theory_help", "hol_no_build"]
        assert result.command_available and not result.hol_ready


@pytest.mark.parametrize("mutate", ["command", "error", "workspace", "truncated"])
def test_matching_marker_with_bad_native_result_binding_is_rejected(owner, distribution, monkeypatch, mutate):
    original = process.BoundedToolRunner.run
    def forge(self, request, **kwargs):
        observed = original(self, request, **kwargs)
        if request.argv[-1] == "IPFSSetupCheck":
            changed = {"command": ("unrelated",)} if mutate == "command" else {
                "error": {"error": "execution failure"},
                "workspace": {"workspace_cleaned": False},
                "truncated": {"output_truncated": True},
            }[mutate]
            return replace(observed, **changed)
        return observed
    monkeypatch.setattr(process.BoundedToolRunner, "run", forge)
    result = run(owner, distribution, mode="smoke")
    assert not result.usable and result.reason_code == "bounded_probe_incomplete"


def test_external_pressure_between_native_phases_waits_then_resumes(owner, distribution):
    timer = None
    waited = []
    def progress(phase, _):
        nonlocal timer
        if phase == "theory_help":
            assert len(owner[0].active_leases()) == 1
            owner[1][0] = replace(owner[2], available_memory_mb=100)
            waited.append(time.monotonic())
            timer = threading.Timer(.2, lambda: owner[1].__setitem__(0, owner[2]))
            timer.start()
    try:
        result = run(owner, distribution, on_progress=progress, timeout_seconds=3)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.usable, result.to_dict()
    assert time.monotonic() - waited[0] >= .19
    assert owner[0].snapshot()["counters"]["saturation_events_total"] > 0


@pytest.mark.parametrize("stage", ["admission", "admitted", "version", "theory_help", "hol_no_build", "smoke", "complete"])
def test_callback_cancellation_at_every_boundary(owner, distribution, stage):
    signal = threading.Event()
    result = run(owner, distribution, mode="smoke", cancellation=signal,
        on_progress=lambda phase, _: signal.set() if phase == stage else None)
    assert result.status == "cancelled" and not result.smoke_accepted


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_pressure_before_second_phase_interrupts_without_native_launch(owner, distribution, stop):
    signal = threading.Event()
    timer = None
    def progress(phase, _):
        nonlocal timer
        if phase == "theory_help":
            owner[1][0] = replace(owner[2], available_memory_mb=100)
            if stop == "cancel":
                timer = threading.Timer(.08, signal.set)
                timer.start()
    try:
        result = run(owner, distribution, cancellation=signal, on_progress=progress,
            timeout_seconds=.3 if stop == "timeout" else 3)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.status == ("cancelled" if stop == "cancel" else "timed_out")
    assert len(result.probes) == 1


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_live_process_cancellation_and_deadline_join_before_releasing(owner, distribution, stop):
    (distribution[1] / "behavior").write_text("slow")
    signal = threading.Event()
    timer = threading.Timer(.2, signal.set) if stop == "cancel" else None
    if timer:
        timer.start()
    try:
        result = run(owner, distribution, cancellation=signal, timeout_seconds=.4 if stop == "timeout" else 3)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.status == ("cancelled" if stop == "cancel" else "timed_out")
    assert len(result.probes) == 1
    observed = result.probes[0]["observation"]
    assert observed["process_tree_terminated"] and observed["workspace_cleaned"]
    assert not Path(f"/proc/{observed['pid']}").exists()


@pytest.mark.parametrize("target", ["bin/isabelle", "etc/ISABELLE_IDENTIFIER", "etc/settings"])
def test_fifo_runtime_inputs_never_block_or_launch(owner, distribution, target):
    path = distribution[1] / target
    path.unlink()
    os.mkfifo(path)
    started = time.monotonic()
    result = run(owner, distribution)
    assert not result.usable and not result.probes
    assert time.monotonic() - started < 1


def test_oversized_sparse_file_refused(owner, distribution):
    with (distribution[1] / "etc/settings").open("wb") as stream:
        stream.truncate(2 * 1024**2)
    result = run(owner, distribution)
    assert not result.usable and not result.probes


def test_identity_changed_between_native_observations_refuses_success(owner, distribution):
    def change(phase, _):
        if phase == "theory_help":
            (distribution[1] / "etc/settings").write_text("changed")
    result = run(owner, distribution, on_progress=change)
    assert not result.usable and result.reason_code == "isabelle_runtime_identity_changed"


@pytest.mark.parametrize("memory,usable", [(2303, False), (2304, True)])
def test_borrowed_parent_stays_owned_and_underfunding_never_launches(owner, distribution, memory, usable):
    with owner[0].acquire("validation", cpu_slots=3, memory_mb=memory, child_process_slots=12) as parent:
        result = prep.prepare_isabelle_runtime(install_root=distribution[0], parent_lease=parent)
        assert result.usable is usable, result.to_dict()
        assert not parent.released
        assert {row["lease_id"] for row in owner[0].active_leases()} == {parent.lease_id}
        if not usable:
            assert not result.probes and result.reason_code == "underfunded_parent_lease"


def test_initial_pressure_consumes_total_admission_deadline(owner, distribution):
    owner[1][0] = replace(owner[2], available_memory_mb=100)
    result = run(owner, distribution, timeout_seconds=.1)
    assert result.status == "timed_out" and not result.probes and not result.resource_lease_id


@pytest.mark.parametrize("kwargs", [
    {"mode": "build"}, {"mode": True}, {"memory_mb": True}, {"memory_mb": 1023},
    {"timeout_seconds": False}, {"timeout_seconds": 0}, {"timeout_seconds": float("inf")},
    {"parent_lease": "token"}, {"scheduler": object()}, {"cancellation": object()},
    {"on_progress": object()}, {"install_root": "a", "executable": "b"},
])
def test_invalid_arguments_rejected_before_admission(kwargs):
    with pytest.raises((TypeError, ValueError)):
        prep.prepare_isabelle_runtime(**kwargs)


@pytest.mark.parametrize("mode,level", [("command", "command"), ("hol", "hol_ready"), ("smoke", "kernel_smoke")])
def test_real_installed_runtime_uses_default_admission(mode, level):
    """Native qualification: run explicitly after coordinating shared capacity."""
    result = prep.prepare_isabelle_runtime(mode=mode, timeout_seconds=120)
    assert result.usable, result.to_dict()
    assert result.readiness_level == level
    assert result.to_dict()["native_runtime"]["version"] == legacy.ISABELLE_VERSION
    assert all(row["observation"]["workspace_cleaned"] for row in result.probes)
    assert len({row["child_lease_id"] for row in result.probes}) == len(result.probes)
