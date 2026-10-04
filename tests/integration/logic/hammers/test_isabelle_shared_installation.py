"""Real worker/process controls with a synthetic archive, never proof evidence."""
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tarfile
import threading
import time

import pytest

from ipfs_datasets_py.logic.backends.installers import isabelle as legacy
from ipfs_datasets_py.logic.backends.installers import isabelle_installation as installation
from ipfs_datasets_py.logic.backends import process
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
        proof_backoff_seconds=.02, poll_interval_seconds=.01))
    yield scheduler, telemetry, healthy
    assert scheduler.snapshot()["active_lease_count"] == 0
    assert scheduler.snapshot()["waiting_request_count"] == 0


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    source = tmp_path / "source" / legacy.ISABELLE_VERSION
    for directory in (source / "bin", source / "etc", source / "lib/scripts"):
        directory.mkdir(parents=True)
    (source / "etc/ISABELLE_IDENTIFIER").write_text(legacy.ISABELLE_VERSION)
    for path in ("etc/settings", "etc/components", "lib/scripts/getsettings"):
        (source / path).write_text("# fixture\n")
    executable = source / "bin/isabelle"
    executable.write_text(f'''#!{Path(sys.executable).resolve()}
import sys
args=sys.argv[1:]
if args==['version']:
    print({legacy.ISABELLE_VERSION!r})
elif args==['process_theories','-?']:
    print('Usage: isabelle process_theories [OPTIONS] [THEORIES...]')
    sys.exit(1)
elif args[0]=='build':
    assert '-n' in args
else:
    assert args[0]=='process_theories'
    print('IPFS_ISABELLE_KERNEL_CHECKED')
''')
    executable.chmod(0o755)
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname=legacy.ISABELLE_VERSION)
    pin = legacy.select_strict_pin("isabelle", platform_key=legacy.detect_platform_key())
    selected = replace(pin, artifact_url=archive.as_uri(), sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(legacy, "select_strict_pin", lambda *a, **kw: selected)
    monkeypatch.setattr(legacy, "check_storage_budget", lambda root: {"ok": True})
    return tmp_path / "installed", archive, source


def run(owner, bundle, **kwargs):
    return installation.ensure_isabelle_installation(yes=True, strict=False, scheduler=owner[0],
        install_root=bundle[0], **kwargs)


def test_real_bounded_worker_cold_warm_and_force_use_one_owner(owner, bundle, monkeypatch):
    launches = []
    original = process.SubprocessExecutor.execute
    def observe(self, invocation, cancellation=None):
        leases = owner[0].active_leases()
        assert sum(not row.get("parent_lease_id") for row in leases) == 1
        assert len(leases) in (2, 3)
        launches.append(invocation)
        return original(self, invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", observe)
    cold = run(owner, bundle)
    assert cold.usable and cold.installed, cold.to_dict()
    assert cold.checksum_verified and cold.download_attempted
    assert cold.staged_preparation["smoke_accepted"] and cold.preparation["smoke_accepted"]
    assert not cold.cleanup_pending
    assert (bundle[0] / "bin/isabelle").read_bytes() == installation._launcher_bytes(bundle[0] / legacy.ISABELLE_VERSION)
    warm = run(owner, bundle)
    assert warm.usable and warm.already_present and not warm.download_attempted
    assert not warm.checksum_verified  # No assertion that warm files equal full archive.
    forced = run(owner, bundle, force=True)
    assert forced.usable and forced.installed and not forced.cleanup_pending, forced.to_dict()
    assert not list(bundle[0].glob(".previous-*"))
    assert not list(bundle[0].glob(".bounded-isabelle-*"))
    worker = next(row for row in launches if "-m" in row.argv)
    assert worker.limits.resident_memory_bytes == 512 * 1024**2
    assert worker.limits.memory_bytes == 2 * 1024**3
    assert worker.limits.max_workspace_bytes == legacy.MAX_DOWNLOAD_BYTES
    assert all("USER_HOME" not in row.environment for row in launches)
    assert all(not Path(row.cwd).exists() for row in launches)
    assert cold.to_dict()["grants_proof_authority"] is False


@pytest.mark.parametrize("phase", ["admission", "admitted", "locked", "archive", "staged_validation", "publication", "published_validation", "validated"])
def test_cancellation_never_leaves_partial_published_replacement(owner, bundle, phase):
    root = bundle[0]
    old = root / legacy.ISABELLE_VERSION
    old.mkdir(parents=True)
    (old / "old").write_text("keep")
    (root / "bin").mkdir()
    (root / "bin/isabelle").write_text("old launcher")
    signal = threading.Event()
    receipt = run(owner, bundle, force=True, cancellation=signal,
        on_progress=lambda stage, _: signal.set() if stage == phase else None)
    assert not receipt.usable and receipt.reason_codes == ["cancelled"], receipt.to_dict()
    assert (old / "old").read_text() == "keep"
    assert (root / "bin/isabelle").read_text() == "old launcher"
    assert not list(root.glob(".previous-*"))
    assert not (root / "bin/.isabelle.previous").exists()
    for path in receipt.cleanup_pending:
        assert Path(path).is_dir()


@pytest.mark.parametrize("kind", ["bad_final", "different_identity", "write_then_fail"])
def test_postpublication_failure_rolls_back_tree_and_launcher(owner, bundle, monkeypatch, kind):
    old = bundle[0] / legacy.ISABELLE_VERSION
    old.mkdir(parents=True)
    (old / "old").write_text("keep")
    (bundle[0] / "bin").mkdir()
    launcher = bundle[0] / "bin/isabelle"
    launcher.write_text("old launcher")
    original = installation.prepare_isabelle_runtime
    calls = []
    def prepare(**kwargs):
        observed = original(**kwargs)
        calls.append(observed)
        if len(calls) == 2:
            if kind == "bad_final":
                return replace(observed, status="unavailable", reason_code="controlled_failure")
            if kind == "different_identity":
                from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
                bindings = observed.bindings.to_dict()
                bindings["runtime"]["selected_file_sha256"]["bin/isabelle"] = "0" * 64
                return replace(observed, bindings=FrozenMap(bindings))
        return observed
    monkeypatch.setattr(installation, "prepare_isabelle_runtime", prepare)
    write = legacy.write_launcher
    if kind == "write_then_fail":
        def fail(*a, **kw):
            write(*a, **kw)
            raise OSError("controlled publication failure")
        monkeypatch.setattr(legacy, "write_launcher", fail)
    receipt = run(owner, bundle, force=True)
    assert not receipt.usable, receipt.to_dict()
    assert (old / "old").read_text() == "keep"
    assert launcher.read_text() == "old launcher"
    assert not receipt.cleanup_pending


@pytest.mark.parametrize("field", ["request_sha256", "sha256", "candidate_relative_path", "extra", "command", "truncated"])
def test_worker_receipt_tampering_never_reaches_native_checks(owner, bundle, monkeypatch, field):
    original = process.BoundedToolRunner.run
    def forge(self, request, **kwargs):
        result = original(self, request, **kwargs)
        if "-m" in request.argv:
            if field == "command":
                return replace(result, command=("unrelated",))
            if field == "truncated":
                return replace(result, output_truncated=True)
            value = json.loads(result.output_files["result.json"])
            value[field] = "tampered"
            return replace(result, output_files={"result.json": json.dumps(value).encode()})
        assert "-c" in request.argv  # Only bounded cleanup may follow.
        return result
    monkeypatch.setattr(process.BoundedToolRunner, "run", forge)
    result = run(owner, bundle)
    assert not result.usable and not result.staged_preparation
    assert not (bundle[0] / legacy.ISABELLE_VERSION).exists()


def test_pressure_after_extraction_backs_off_before_native_validation(owner, bundle):
    timer = None
    began = []
    def progress(phase, _):
        nonlocal timer
        if phase == "staged_validation":
            owner[1][0] = replace(owner[2], available_memory_mb=100)
            began.append(time.monotonic())
            timer = threading.Timer(.2, lambda: owner[1].__setitem__(0, owner[2]))
            timer.start()
    try:
        result = run(owner, bundle, on_progress=progress, timeout_seconds=10)
    finally:
        if timer:
            timer.cancel()
            timer.join(1)
    assert result.usable, result.to_dict()
    assert time.monotonic() - began[0] >= .19
    assert owner[0].snapshot()["counters"]["saturation_events_total"] > 0


def test_root_pressure_has_finite_deadline_and_no_install_mutation(owner, bundle):
    owner[1][0] = replace(owner[2], available_memory_mb=100)
    result = run(owner, bundle, timeout_seconds=.05)
    assert result.reason_codes == ["deadline_exceeded"] and not result.download_attempted
    assert not bundle[0].exists()


def test_lock_wait_cancellation_does_not_probe_or_download(owner, bundle):
    locked, release, cancel = threading.Event(), threading.Event(), threading.Event()
    def hold():
        with legacy._INSTALL_MUTEX:
            locked.set()
            release.wait(3)
    holder = threading.Thread(target=hold)
    holder.start()
    assert locked.wait(1)
    timer = threading.Timer(.1, cancel.set)
    timer.start()
    try:
        result = run(owner, bundle, cancellation=cancel)
    finally:
        release.set()
        holder.join(1)
        timer.cancel()
        timer.join(1)
    assert result.reason_codes == ["cancelled"] and not result.download_attempted


def test_outer_parent_is_borrowed_not_released_or_double_charged(owner, bundle):
    with owner[0].acquire("orchestration", cpu_slots=3, memory_mb=2304, child_process_slots=12) as parent:
        result = installation.ensure_isabelle_installation(yes=True, strict=False,
            install_root=bundle[0], parent_lease=parent)
        assert result.usable, result.to_dict()
        assert not parent.released and len(owner[0].active_leases()) == 1


def test_strict_failure_retains_structured_receipt(owner, bundle):
    owner[1][0] = replace(owner[2], available_memory_mb=100)
    with pytest.raises(installation.IsabelleInstallationError) as caught:
        installation.ensure_isabelle_installation(yes=True, install_root=bundle[0],
            scheduler=owner[0], timeout_seconds=.05)
    assert caught.value.receipt.reason_codes == ["deadline_exceeded"]


def test_missing_install_requires_yes_and_does_not_create_root(owner, bundle):
    receipt = installation.ensure_isabelle_installation(install_root=bundle[0], scheduler=owner[0])
    assert receipt.status == "blocked" and not bundle[0].exists()


def test_write_then_fail_without_prior_launcher_restores_empty_destination(owner, bundle, monkeypatch):
    write = legacy.write_launcher
    def fail(*a, **kw):
        write(*a, **kw)
        raise OSError("controlled failure after launcher publication")
    monkeypatch.setattr(legacy, "write_launcher", fail)
    receipt = run(owner, bundle)
    assert not receipt.usable
    assert not (bundle[0] / "bin/isabelle").exists()
    assert not (bundle[0] / legacy.ISABELLE_VERSION).exists()


def test_backup_cleanup_failure_does_not_revoke_committed_install(owner, bundle, monkeypatch):
    old = bundle[0] / legacy.ISABELLE_VERSION
    old.mkdir(parents=True)
    (old / "old").write_text("keep")
    rename = Path.replace
    def fail(self, target):
        if self.name == ".previous-" + legacy.ISABELLE_VERSION:
            raise OSError("controlled backup retirement failure")
        return rename(self, target)
    monkeypatch.setattr(Path, "replace", fail)
    receipt = run(owner, bundle, force=True)
    assert receipt.usable and receipt.installed, receipt.to_dict()
    assert receipt.cleanup["reason"] == "committed_backup_retirement_failed"
    assert str(bundle[0] / (".previous-" + legacy.ISABELLE_VERSION)) in receipt.cleanup_pending
    assert (bundle[0] / (".previous-" + legacy.ISABELLE_VERSION) / "old").read_text() == "keep"


def test_cleanup_after_commit_is_best_effort_and_retains_owned_path(owner, bundle, monkeypatch):
    original = process.BoundedToolRunner.run
    def fail(self, request, **kwargs):
        observed = original(self, request, **kwargs) if "-c" not in request.argv else None
        if observed is None:
            raise OSError("controlled cleanup failure")
        return observed
    monkeypatch.setattr(process.BoundedToolRunner, "run", fail)
    receipt = run(owner, bundle)
    assert receipt.usable and receipt.installed and receipt.cleanup_pending
    assert all(Path(path).exists() for path in receipt.cleanup_pending)


@pytest.mark.parametrize("argument,value", [
    ("timeout_seconds", True), ("timeout_seconds", 0), ("timeout_seconds", float("nan")),
    ("timeout_seconds", 3601), ("memory_mb", True), ("memory_mb", 512),
    ("yes", 1), ("force", 1), ("parent_lease", object()), ("scheduler", object()),
    ("cancellation", object()), ("on_progress", 1),
    ("build_hol", 1), ("allow_download", 1),
    ("build_memory_mb", True), ("build_memory_mb", 1024), ("build_memory_mb", 8193),
])
def test_invalid_limits_or_contracts_rejected_before_side_effects(bundle, argument, value):
    with pytest.raises((ValueError, TypeError)):
        installation.ensure_isabelle_installation(install_root=bundle[0], **{argument: value})
    assert not bundle[0].exists()


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_live_download_is_terminated_without_cache_corruption_or_publication(owner, bundle, monkeypatch, stop):
    entered, finish, cancel = threading.Event(), threading.Event(), threading.Event()
    class Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"partial bytes")
            self.wfile.flush()
            entered.set()
            finish.wait(5)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    serving = threading.Thread(target=server.serve_forever)
    serving.start()
    pin = legacy.select_strict_pin("isabelle")
    monkeypatch.setattr(legacy, "select_strict_pin", lambda *a, **kw:
        replace(pin, artifact_url=f"http://127.0.0.1:{server.server_port}/fixture.tar.gz"))
    cache = bundle[0] / "downloads/fixture.tar.gz"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"old cache retained")
    def cancel_download():
        if entered.wait(3):
            time.sleep(.1)
            cancel.set()
    canceller = threading.Thread(target=cancel_download) if stop == "cancel" else None
    if canceller:
        canceller.start()
    try:
        receipt = run(owner, bundle, cancellation=cancel, timeout_seconds=3 if stop == "cancel" else 1)
    finally:
        finish.set()
        if canceller:
            canceller.join(1)
        server.shutdown()
        server.server_close()
        serving.join(1)
    assert entered.is_set()
    assert receipt.reason_codes == ["cancelled" if stop == "cancel" else "deadline_exceeded"], receipt.to_dict()
    assert not receipt.usable and not receipt.checksum_verified and not receipt.staged_preparation
    observed = receipt.worker["observation"]
    assert observed["process_tree_terminated"] and observed["workspace_cleaned"]
    assert not Path(f"/proc/{observed['pid']}").exists()
    assert cache.read_bytes() == b"old cache retained"
    assert not list(cache.parent.glob("*.partial"))
    assert not (bundle[0] / legacy.ISABELLE_VERSION).exists()
    assert receipt.cleanup_pending and all(Path(path).exists() for path in receipt.cleanup_pending)


@pytest.mark.parametrize("failed_restore", ["launcher", "tree"])
def test_rollback_io_failure_preserves_recovery_paths_and_attempts_other_restore(owner, bundle, monkeypatch, failed_restore):
    old = bundle[0] / legacy.ISABELLE_VERSION
    old.mkdir(parents=True)
    (old / "old").write_text("keep")
    (bundle[0] / "bin").mkdir()
    (bundle[0] / "bin/isabelle").write_text("old launcher")
    rename = Path.replace
    def fail(self, target):
        if (failed_restore == "launcher" and self.name == ".isabelle.previous"
                or failed_restore == "tree" and self.name == ".previous-" + legacy.ISABELLE_VERSION):
            raise OSError("controlled restore failure")
        return rename(self, target)
    monkeypatch.setattr(Path, "replace", fail)
    cancel = threading.Event()
    receipt = run(owner, bundle, force=True, cancellation=cancel,
        on_progress=lambda phase, _: cancel.set() if phase == "published_validation" else None)
    assert not receipt.usable and receipt.recovery["required"]
    assert receipt.reason_codes == ["cancelled", "rollback_failed"]
    assert len(receipt.cleanup_pending) == 2 and all(Path(path).exists() for path in receipt.cleanup_pending)
    if failed_restore == "launcher":
        assert (old / "old").read_text() == "keep"
        assert (bundle[0] / "bin/.isabelle.previous").read_text() == "old launcher"
    else:
        assert (bundle[0] / "bin/isabelle").read_text() == "old launcher"
        assert (bundle[0] / (".previous-" + legacy.ISABELLE_VERSION) / "old").read_text() == "keep"


def test_unresolved_backup_blocks_warm_reuse_before_native_probes(owner, bundle, monkeypatch):
    backup = bundle[0] / (".previous-" + legacy.ISABELLE_VERSION)
    backup.mkdir(parents=True)
    monkeypatch.setattr(installation, "prepare_isabelle_runtime", lambda **kw: pytest.fail("unresolved recovery must precede native work"))
    receipt = run(owner, bundle)
    assert not receipt.usable and receipt.recovery["required"]
    assert receipt.reason_codes[-1] == "unresolved_previous_installation"
    assert receipt.cleanup_pending == [str(backup)]


@pytest.mark.parametrize("broken", ["missing", "wrong", "fifo"])
def test_warm_reuse_repairs_managed_discovery_only_with_yes(owner, bundle, broken):
    assert run(owner, bundle).usable
    launcher = bundle[0] / "bin/isabelle"
    launcher.unlink()
    if broken == "wrong":
        launcher.write_text("stale wrapper")
    elif broken == "fifo":
        os.mkfifo(launcher)
    denied = installation.ensure_isabelle_installation(install_root=bundle[0], scheduler=owner[0])
    assert not denied.usable and denied.reason_codes == ["managed_launcher_repair_requires_yes"]
    fixed = run(owner, bundle)
    assert fixed.usable and fixed.already_present and fixed.launcher_repaired
    assert not fixed.download_attempted and not fixed.cleanup_pending
    assert launcher.read_bytes() == installation._launcher_bytes(bundle[0] / legacy.ISABELLE_VERSION)


def test_warm_inner_distribution_does_not_replace_native_launcher(owner, bundle):
    assert run(owner, bundle).usable
    inner = bundle[0] / legacy.ISABELLE_VERSION
    before = (inner / "bin/isabelle").read_bytes()
    receipt = installation.ensure_isabelle_installation(yes=True, install_root=inner, scheduler=owner[0])
    assert receipt.usable and not receipt.launcher_repaired
    assert (inner / "bin/isabelle").read_bytes() == before


def test_warm_launcher_repair_failure_restores_previous_wrapper(owner, bundle, monkeypatch):
    assert run(owner, bundle).usable
    launcher = bundle[0] / "bin/isabelle"
    launcher.write_text("old stale wrapper")
    write = legacy.write_launcher
    def fail(*a, **kw):
        write(*a, **kw)
        raise OSError("controlled warm publication failure")
    monkeypatch.setattr(legacy, "write_launcher", fail)
    receipt = run(owner, bundle)
    assert not receipt.usable and not receipt.launcher_repaired
    assert launcher.read_text() == "old stale wrapper"
    assert not receipt.cleanup_pending


def cache_bundle(bundle):
    import shutil
    target = bundle[0] / "downloads" / bundle[1].name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle[1], target)
    return target


@pytest.fixture
def controlled_build(monkeypatch):
    """Controller transaction control only; actual heap work has separate tests."""
    from ipfs_datasets_py.logic.backends.installers import isabelle_hol_build as build
    events = []
    def rebuild(**kwargs):
        lease = kwargs["parent_lease"]
        assert lease.cpu_slots >= 4 and lease.memory_mb >= kwargs["memory_mb"] + 256
        assert lease.child_process_slots >= 12
        events.append(("build", kwargs))
        return {"build_succeeded": True, "persistent_heap_published": False,
                "observation": {"returncode": 0}, "heap_after": {"controlled": "identity"}}
    def verify(**kwargs):
        events.append(("verify", kwargs))
        assert kwargs["expected_build"]["persistent_heap_published"] is False
        return {"verified": True}
    monkeypatch.setattr(build, "build_staged_hol", rebuild)
    monkeypatch.setattr(build, "verify_published_hol", verify)
    return events


def test_cache_only_build_replaces_staged_runtime_and_checks_persistence(owner, bundle, controlled_build):
    cache_bundle(bundle)
    result = run(owner, bundle, build_hol=True, allow_download=False)
    assert result.usable and result.installed and result.build_hol_requested, result.to_dict()
    assert not result.download_attempted and result.checksum_verified
    assert result.hol_build["persistent_heap_published"]
    assert result.hol_build["publication_verification"]["verified"]
    assert [event[0] for event in controlled_build] == ["build", "verify"]
    assert ".bounded-isabelle-" in str(controlled_build[0][1]["install_root"])
    assert controlled_build[1][1]["install_root"] == bundle[0] / legacy.ISABELLE_VERSION
    assert result.limits["cpu_slots"] == 4 and result.limits["reservation_memory_mb"] == 6400
    assert result.limits["timeout_seconds"] == 3600


def test_build_request_bypasses_usable_warm_runtime(owner, bundle, controlled_build):
    assert run(owner, bundle).usable
    result = run(owner, bundle, build_hol=True, allow_download=False)
    assert result.usable and result.installed and not result.already_present
    assert len(controlled_build) == 2


def test_build_requires_mutation_authorization_before_admission(owner, bundle, controlled_build):
    result = installation.ensure_isabelle_installation(yes=False, build_hol=True,
        scheduler=owner[0], install_root=bundle[0])
    assert result.status == "blocked" and not result.resource_lease_id
    assert not bundle[0].exists() and not controlled_build


@pytest.mark.parametrize("cached", ["missing", "corrupt"])
def test_offline_build_never_fetches_missing_or_corrupt_archive(owner, bundle, controlled_build, cached):
    old = bundle[0] / legacy.ISABELLE_VERSION
    old.mkdir(parents=True)
    (old / "previous").write_text("preserve")
    if cached == "corrupt":
        path = cache_bundle(bundle)
        path.write_bytes(b"invalid pinned cache")
    # The selected file: source archive is valid. Any network/file-url fallback
    # would install it, so refusal proves that allow_download=False reaches worker.
    result = run(owner, bundle, build_hol=True, allow_download=False)
    assert not result.usable and not result.download_attempted
    assert not controlled_build and not result.staged_preparation
    assert (old / "previous").read_text() == "preserve"
    if cached == "missing":
        assert result.reason_codes == ["verified_archive_required"]
    else:
        assert path.read_bytes() == b"invalid pinned cache"


@pytest.mark.parametrize("failure", ["build", "verification", "cancel_after_build", "cancel_after_publication"])
def test_failed_or_cancelled_build_preserves_previous_installation(owner, bundle, controlled_build, monkeypatch, failure):
    from ipfs_datasets_py.logic.backends.installers import isabelle_hol_build as build
    cache_bundle(bundle)
    old = bundle[0] / legacy.ISABELLE_VERSION
    old.mkdir(parents=True)
    (old / "previous").write_text("preserve")
    (bundle[0] / "bin").mkdir()
    (bundle[0] / "bin/isabelle").write_text("old wrapper")
    signal = threading.Event()
    if failure == "build":
        monkeypatch.setattr(build, "build_staged_hol", lambda **kw: {
            "build_succeeded": False, "persistent_heap_published": False})
    if failure == "verification":
        monkeypatch.setattr(build, "verify_published_hol", lambda **kw: {"verified": False})
    if failure == "cancel_after_build":
        original = build.build_staged_hol
        def cancel(**kwargs):
            result = original(**kwargs)
            signal.set()
            return result
        monkeypatch.setattr(build, "build_staged_hol", cancel)
    result = run(owner, bundle, build_hol=True, allow_download=False, cancellation=signal,
        on_progress=lambda phase, _: signal.set() if failure == "cancel_after_publication"
                    and phase == "published_heap_verification" else None)
    assert not result.usable and not result.hol_build.get("persistent_heap_published")
    assert (old / "previous").read_text() == "preserve"
    assert (bundle[0] / "bin/isabelle").read_text() == "old wrapper"
    assert not list(bundle[0].glob(".previous-*"))


def test_build_parent_requires_its_larger_actual_envelope(owner, bundle, controlled_build):
    with owner[0].acquire("orchestration", cpu_slots=3, memory_mb=2304, child_process_slots=12) as parent:
        receipt = installation.ensure_isabelle_installation(yes=True, strict=False, build_hol=True,
            parent_lease=parent, install_root=bundle[0])
        assert not receipt.usable and not receipt.resource_lease_id
        assert not controlled_build and not parent.released
        assert len(owner[0].active_leases()) == 1
