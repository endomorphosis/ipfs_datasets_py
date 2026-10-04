"""Hyper installer ownership/publication tests; no native or network work."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import threading

import pytest

from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers import hyperproperty_transaction as tx
from ipfs_datasets_py.logic.backends.installers.install_control import installation_scope
from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationInterrupted
from ipfs_datasets_py.logic.external_provers import lazy_installer as lazy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler


def denied(*args, **kwargs):
    pytest.fail("transaction fixture reached native, network or shared scheduler work")


@pytest.fixture(autouse=True)
def no_host_work(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)
    monkeypatch.setattr(hp, "urlopen", denied)
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", denied)


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    pin = dict(hp.DEFAULT_PINS[hp.TOOL_HYPERLTL])
    monkeypatch.setattr(hp, "pin_for_tool", lambda *a, **k: dict(pin))
    root = tmp_path / "managed"
    version = root / "hyperproperty-vendor" / "hyperltl" / pin["version"]
    executable = version / "upstream" / "engine"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"old verified engine")
    executable.chmod(0o755)
    identity = hp.EngineIdentity(tool_id="hyperltl", version=pin["version"],
        executable=str(executable), license=pin["license"], source=pin["source"],
        identity_kind=pin["identity_kind"], is_hermetic_engine=False,
        is_vendor_build=True, is_upstream_build=True, executable_kind="upstream_compiled_binary",
        artifact_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        source_archive_sha256=pin["sha256"], source_tree_sha256="1"*64,
        distribution_tree_sha256="2"*64, source_archive_path=str(root / "fixture.tar.gz"),
        executable_origin="upstream/engine", dependency_identities=(hp.DependencyIdentity(
            name="fixture", constraint="fixture", executable=str(executable),
            version_output="fixture 1.0", executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(), phase="build"),))
    monkeypatch.setattr(hp, "_identity_from_disk", lambda *a, **k: identity)
    monkeypatch.setattr(hp, "tool_supported_on_platform", lambda *a, **k: True)
    return root, version, executable, identity


@pytest.mark.parametrize("value", ["", ".", "..", "../escape", "/absolute", "a/b", "a\\b", "a\x00b", "x"*129, True, 7])
def test_version_component_refuses_noncanonical_paths(value):
    with pytest.raises(hp.HyperpropertyInstallerError):
        hp._safe_version_component(value)


def test_explicit_invalid_lock_version_is_not_silently_coerced(monkeypatch):
    monkeypatch.setattr(hp, "load_deployment_lock", lambda *a, **k: {"versions": {"hyperltl": "../escape"}})
    with pytest.raises(hp.HyperpropertyInstallerError):
        hp.pin_for_tool("hyperltl")


@pytest.mark.parametrize("controls", [{"yes": False}, {"yes": True, "import_context": True},
    {"yes": True, "capability_discovery": True}, {"yes": True, "checksum_verified": False}])
def test_cached_vendor_discovery_never_publishes_or_creates_locks(vendor, controls):
    root, _, executable, _ = vendor
    before = executable.read_bytes()
    receipt = hp.ensure_hyperltl(install_root=root, vendor=True, strict=False, **controls)
    assert receipt.status == "already_present" and receipt.ok
    assert executable.read_bytes() == before
    assert not (root / "bin").exists() and not (root / ".install-locks").exists()


@pytest.mark.parametrize("field", ["yes", "strict", "force", "vendor", "import_context", "capability_discovery"])
def test_public_boolean_controls_are_exact_before_any_mutation(tmp_path, field):
    controls = {"yes": True, "vendor": True, field: 1}
    root = tmp_path / "untouched"
    with pytest.raises(hp.HyperpropertyInstallerError, match="boolean"):
        hp.ensure_hyperltl(install_root=root, **controls)
    assert not root.exists()


def test_atomic_launcher_quotes_runtime_values_and_never_interpolates_paths(vendor):
    root, _, _, identity = vendor
    identity = replace(identity, tool_id="autohyper", runtime_environment=(("DOTNET_ROOT", "/sdk/$(never)`never`'quoted"),))
    launcher = hp._publish_managed_vendor_launcher(identity, install_root=root)
    body = launcher.read_text()
    assert "export DOTNET_ROOT='/sdk/$(never)`never`'\"'\"'quoted'" in body
    assert 'export PATH="${DOTNET_ROOT}:${PATH:-}"' in body
    assert launcher.stat().st_mode & 0o777 == 0o755
    assert not list(launcher.parent.glob(".autohyper-*"))


def test_launcher_symlink_cannot_overwrite_external_file(vendor, tmp_path):
    root, _, _, identity = vendor
    outside = tmp_path / "outside"; outside.write_bytes(b"untouched")
    (root / "bin").mkdir(); (root / "bin" / "hyperltl").symlink_to(outside)
    with pytest.raises((hp.HyperpropertyInstallerError, ValueError)):
        hp._publish_managed_vendor_launcher(identity, install_root=root)
    assert outside.read_bytes() == b"untouched" and (root / "bin" / "hyperltl").is_symlink()


def test_symlinked_bin_parent_is_refused_without_external_mutation(vendor, tmp_path):
    root, _, _, identity = vendor
    outside = tmp_path / "outside"; outside.mkdir()
    (root / "bin").symlink_to(outside, target_is_directory=True)
    with pytest.raises(hp.HyperpropertyInstallerError):
        hp._publish_managed_vendor_launcher(identity, install_root=root)
    assert list(outside.iterdir()) == []


def test_cached_publication_error_is_not_reported_as_success(vendor, monkeypatch):
    root, _, executable, _ = vendor
    def fail(*args, **kwargs):
        raise OSError("controlled publication failure")
    monkeypatch.setattr(hp, "_publish_managed_vendor_launcher", fail)
    receipt = hp.ensure_hyperltl(yes=True, strict=False, vendor=True, install_root=root)
    assert receipt.status == "failed" and not receipt.ok
    assert receipt.block_reasons == ("managed_launcher_publication_failed",)
    assert executable.read_bytes() == b"old verified engine"


@pytest.mark.parametrize("failure", ["audit", "publication", "cancel"])
def test_previous_version_and_launcher_survive_late_failure(vendor, monkeypatch, failure):
    root, version, executable, identity = vendor
    original_launcher = hp._publish_managed_vendor_launcher(identity, install_root=root).read_bytes()
    signal = threading.Event()
    def build(*args, **kwargs):
        stage = root / "staged"; (stage / "upstream").mkdir(parents=True)
        (stage / "upstream" / "engine").write_bytes(b"new engine")
        hp._replace_install_tree(stage, version)
        if failure == "audit":
            raise hp.HyperpropertyInstallBlocked("controlled post-install identity failure", "post_install_identity_verification_failed")
        return identity
    monkeypatch.setattr(hp, "_materialize_vendor_engine_in_transaction", build)
    publish = hp._publish_managed_vendor_launcher
    def later(*args, **kwargs):
        publish(*args, **kwargs)
        if failure == "publication":
            raise OSError("controlled error after atomic publication")
        signal.set()
    if failure != "audit":
        monkeypatch.setattr(hp, "_publish_managed_vendor_launcher", later)
    if failure == "cancel":
        with pytest.raises(ProofOperationInterrupted):
            hp.ensure_hyperltl(yes=True, vendor=True, force=True, strict=False, install_root=root, cancellation=signal)
    else:
        receipt = hp.ensure_hyperltl(yes=True, vendor=True, force=True, strict=False, install_root=root)
        assert not receipt.ok and receipt.status in {"failed", "blocked"}
    assert executable.read_bytes() == b"old verified engine"
    assert (root / "bin" / "hyperltl").read_bytes() == original_launcher
    assert not list(version.parent.glob(".*-backup-*"))
    assert not list((root / "bin").glob(".*-backup-*"))


def test_direct_materializer_rolls_back_failed_identity_audit(vendor, monkeypatch):
    root, version, executable, _ = vendor
    def broken(*args, **kwargs):
        stage = root / "stage"; stage.mkdir()
        hp._replace_install_tree(stage, version)
        raise hp.HyperpropertyInstallBlocked("post-install audit failed")
    monkeypatch.setattr(hp, "_materialize_vendor_engine_in_transaction", broken)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        hp.materialize_vendor_engine("hyperltl", install_root=root, force=True)
    assert executable.read_bytes() == b"old verified engine"


def test_reentrant_transaction_and_cancelled_waiter_preserve_owner(tmp_path):
    root = tmp_path / "managed"; signal = threading.Event()
    held, release, contended = threading.Event(), threading.Event(), threading.Event()
    errors = []
    class ObservedLock:
        def __init__(self): self.lock = threading.Lock()
        def acquire(self, **kwargs):
            result = self.lock.acquire(**kwargs)
            if not result: contended.set()
            return result
        def release(self): self.lock.release()
    key = (str(root), "hyperltl")
    with tx._LOCKS_GUARD: tx._LOCKS[key] = ObservedLock()
    def owner():
        try:
            with installation_scope(operation_timeout_ms=5000):
                with tx.installation_transaction(root, "hyperltl") as first:
                    with tx.installation_transaction(root, "hyperltl") as second:
                        assert first is second
                        held.set()
                        assert release.wait(2)
        except BaseException as exc: errors.append(exc)
    def waiter():
        try:
            with installation_scope(operation_timeout_ms=5000, cancellation=signal):
                with tx.installation_transaction(root, "hyperltl"):
                    pytest.fail("cancelled waiter acquired transaction")
        except ProofOperationInterrupted: pass
        except BaseException as exc: errors.append(exc)
    first, second = threading.Thread(target=owner), threading.Thread(target=waiter)
    first.start()
    try:
        assert held.wait(1); second.start()
        assert contended.wait(1); signal.set(); second.join(1)
        assert not second.is_alive() and first.is_alive()
    finally:
        release.set(); first.join(2)
        if second.ident is not None: second.join(2)
    assert not errors and not first.is_alive()


def test_symlinked_lock_directory_refuses_before_external_creation(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir(); outside.mkdir(); (root / ".install-locks").symlink_to(outside, target_is_directory=True)
    with installation_scope():
        with pytest.raises(ValueError, match="symlink"):
            with tx.installation_transaction(root, "hyperltl"):
                pytest.fail("unsafe transaction entered")
    assert list(outside.iterdir()) == []


def test_dependency_root_option_is_forwarded_without_exposing_full_paths(tmp_path):
    sdk = tmp_path / "sdk"; sdk.mkdir()
    actual, public = lazy._normalize_installer_options("autohyper", {"dependency_roots": {"dotnet-sdk": str(sdk)}})
    assert actual == {"dependency_roots": {"dotnet-sdk": str(sdk)}}
    descriptor = public["dependency_roots"]["dotnet-sdk"]
    assert descriptor["kind"] == "directory" and descriptor["content_verified"] is False
    assert descriptor["path_binding_sha256"] == hashlib.sha256(str(sdk).encode()).hexdigest()
    assert str(sdk) not in str(public)


def test_reviewed_facade_forwards_roots_and_enters_same_hyper_transaction(vendor, monkeypatch):
    root, _, _, identity = vendor
    dependencies = root / "dependencies"; dependencies.mkdir()
    visits = []
    def materialize(*args, **kwargs):
        visits.append((kwargs["dependency_roots"], tx.current_transaction()))
        return identity
    monkeypatch.setattr(hp, "_materialize_vendor_engine_in_transaction", materialize)
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: root)
    monkeypatch.setattr(lazy, "_configured_user_install_root", lambda: root)
    result = lazy.execute_reviewed_install("hyperltl", allow_install=True, force=True,
        installer_options={"dependency_roots": {"ocaml": str(dependencies)}})
    assert result["available"] is True and result["installed"] is True
    assert len(visits) == 1 and visits[0][0] == {"ocaml": str(dependencies)}
    assert isinstance(visits[0][1], tx.InstallTransaction)
    assert (root / "bin" / "hyperltl").is_file()
    assert tx.current_transaction() is None


@pytest.mark.parametrize("kind", ["unknown", "relative", "symlink", "wrong-type", "too-many", "missing"])
def test_dependency_root_options_fail_closed(tmp_path, kind):
    directory = tmp_path / "sdk"; directory.mkdir()
    value = {"dotnet": str(directory)}
    if kind == "unknown": value = {"unreviewed": str(directory)}
    elif kind == "relative": value = {"dotnet": "relative"}
    elif kind == "symlink":
        link = tmp_path / "alias"; link.symlink_to(directory); value = {"dotnet": str(link)}
    elif kind == "wrong-type": value = {"dotnet": 12}
    elif kind == "too-many": value = {str(i): str(directory) for i in range(33)}
    else: value = {"dotnet": str(tmp_path / "missing")}
    with pytest.raises(ValueError):
        lazy._normalize_installer_options("autohyper", {"dependency_roots": value})


def test_lazy_progress_accepts_hyper_single_message(tmp_path, monkeypatch):
    from contextlib import nullcontext
    calls, events = [], []
    def ensure(**kwargs):
        calls.append(kwargs)
        kwargs["on_progress"]("single Hyper message")
        return {"status": "installed"}
    monkeypatch.setattr(lazy, "_resolve_reviewed_installer", lambda name: ensure)
    monkeypatch.setattr(lazy, "prover_lazy_install_enabled", lambda name: True)
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: tmp_path)
    monkeypatch.setattr(lazy, "_cross_process_install_lock", lambda name: nullcontext({}))
    monkeypatch.setattr(lazy, "clear_feature_detection_cache", lambda: None)
    assert lazy._lazy_install_prover_once("hyperltl", progress=events.append)
    assert len(calls) == 1 and calls[0]["vendor"] is True and calls[0]["hermetic_engine"] is False
    assert any(event.message == "single Hyper message" for event in events)


@pytest.mark.parametrize("provider", ["hyperltl", "autohyper", "mchyper"])
def test_lazy_cancelled_install_does_not_poison_fresh_retry(tmp_path, monkeypatch, provider):
    from contextlib import nullcontext
    from ipfs_datasets_py.logic.backends.installers.install_control import installation_checkpoint
    visits = []
    signal = threading.Event()
    def ensure(**kwargs):
        visits.append(kwargs)
        with installation_scope(operation_timeout_ms=1000, cancellation=signal):
            if len(visits) == 1:
                signal.set()
            installation_checkpoint("controlled installer callback")
        return {"status": "installed"}
    monkeypatch.setattr(lazy, "_ATTEMPTED", set())
    monkeypatch.setattr(lazy, "_INSTALL_RESULTS", {})
    monkeypatch.setattr(lazy, "_resolve_reviewed_installer", lambda name: ensure)
    monkeypatch.setattr(lazy, "prover_lazy_install_enabled", lambda name: True)
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: tmp_path)
    monkeypatch.setattr(lazy, "_cross_process_install_lock", lambda name: nullcontext({}))
    monkeypatch.setattr(lazy, "clear_feature_detection_cache", lambda: None)
    with pytest.raises(ProofOperationInterrupted):
        lazy.lazy_install_prover(provider, strict=False)
    assert provider not in lazy._ATTEMPTED and provider not in lazy._INSTALL_RESULTS
    signal.clear()
    assert lazy.lazy_install_prover(provider, strict=False)
    assert len(visits) == 2 and lazy._INSTALL_RESULTS[provider] is True


@pytest.mark.parametrize("provider", ["hyperltl", "autohyper", "mchyper"])
def test_lazy_unpolled_late_cancellation_does_not_cache_failure(monkeypatch, tmp_path, provider):
    from contextlib import nullcontext
    signal, visits = threading.Event(), []
    def ensure(**kwargs):
        visits.append(kwargs)
        if len(visits) == 1:
            signal.set()
            return {"status": "blocked"}
        return {"status": "installed"}
    monkeypatch.setattr(lazy, "_ATTEMPTED", set())
    monkeypatch.setattr(lazy, "_INSTALL_RESULTS", {})
    monkeypatch.setattr(lazy, "_resolve_reviewed_installer", lambda name: ensure)
    monkeypatch.setattr(lazy, "prover_lazy_install_enabled", lambda name: True)
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: tmp_path)
    monkeypatch.setattr(lazy, "_cross_process_install_lock", lambda name: nullcontext({}))
    monkeypatch.setattr(lazy, "clear_feature_detection_cache", lambda: None)
    with pytest.raises(ProofOperationInterrupted):
        lazy.lazy_install_prover(provider, cancellation=signal)
    assert provider not in lazy._ATTEMPTED and provider not in lazy._INSTALL_RESULTS
    signal.clear()
    assert lazy.lazy_install_prover(provider, cancellation=signal)
    assert len(visits) == 2 and lazy._INSTALL_RESULTS[provider] is True


@pytest.mark.parametrize("route", ["lazy", "explicit"])
def test_hyper_facade_thread_lock_wait_is_cancellable_before_plugin(route, monkeypatch, tmp_path):
    signal, contended = threading.Event(), threading.Event()
    errors = []
    class ObservedLock:
        def __init__(self): self.lock = threading.Lock()
        def acquire(self, **kwargs):
            result = self.lock.acquire(**kwargs)
            if not result: contended.set()
            return result
        def release(self): self.lock.release()
    lock = ObservedLock(); assert lock.acquire(timeout=0)
    monkeypatch.setattr(lazy, "_install_lock", lambda provider: lock)
    monkeypatch.setattr(lazy, "prover_lazy_install_enabled", lambda provider: True)
    monkeypatch.setattr(lazy, "_resolve_reviewed_installer", lambda provider: denied)
    monkeypatch.setattr(hp, "ensure_hyperltl", denied)
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: tmp_path / "unused")
    monkeypatch.setattr(lazy, "_configured_user_install_root", lambda: tmp_path / "unused")
    def worker():
        try:
            if route == "lazy":
                lazy.lazy_install_prover("hyperltl", operation_timeout_ms=2000, cancellation=signal)
            else:
                lazy.execute_reviewed_install("hyperltl", allow_install=True, operation_timeout_ms=2000, cancellation=signal)
        except BaseException as exc: errors.append(exc)
    thread = threading.Thread(target=worker); thread.start()
    try:
        assert contended.wait(1); signal.set(); thread.join(1)
        assert not thread.is_alive()
    finally:
        lock.release(); thread.join(2)
    assert len(errors) == 1 and isinstance(errors[0], ProofOperationInterrupted)
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("route", ["lazy", "explicit"])
def test_hyper_facade_file_lock_poll_observes_cancellation(route, monkeypatch, tmp_path):
    import fcntl
    root = tmp_path / "managed"; signal = threading.Event(); calls = []
    monkeypatch.setattr(lazy, "_ATTEMPTED", set())
    monkeypatch.setattr(lazy, "_INSTALL_RESULTS", {})
    monkeypatch.setattr(lazy, "prover_lazy_install_enabled", lambda provider: True)
    monkeypatch.setattr(lazy, "configured_user_install_root", lambda: root)
    monkeypatch.setattr(lazy, "_configured_user_install_root", lambda: root)
    monkeypatch.setattr(lazy, "_resolve_reviewed_installer", lambda provider: denied)
    monkeypatch.setattr(hp, "ensure_hyperltl", denied)
    def busy(descriptor, operation):
        assert operation == fcntl.LOCK_EX | fcntl.LOCK_NB
        calls.append(descriptor); signal.set()
        raise BlockingIOError("controlled live peer lock")
    monkeypatch.setattr(fcntl, "flock", busy)
    with pytest.raises(ProofOperationInterrupted):
        if route == "lazy":
            lazy.lazy_install_prover("hyperltl", operation_timeout_ms=1000, cancellation=signal)
        else:
            lazy.execute_reviewed_install("hyperltl", allow_install=True, operation_timeout_ms=1000, cancellation=signal)
    assert calls and "hyperltl" not in lazy._ATTEMPTED
    # Both the file descriptor and in-process lease must be drained on stop.
    with pytest.raises(OSError): os.fstat(calls[-1])
    lock = lazy._install_lock("hyperltl")
    assert lock.acquire(timeout=0)
    lock.release()
