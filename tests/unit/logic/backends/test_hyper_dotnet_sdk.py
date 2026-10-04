"""Provisioner contract using authenticated tiny archives and inert probe fixtures.

These tests exercise real extraction, tree audits and transaction ownership.
They do not download SDKs, run native hosts or acquire a scheduler lease.
"""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tarfile
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends.installers import dotnet_sdk as sdk
from ipfs_datasets_py.logic.backends.installers import dotnet_sdk_archive as archive
from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
from ipfs_datasets_py.logic.backends.installers import install_control as control
from ipfs_datasets_py.logic.backends.installers import hyperproperty_transaction as transaction
from ipfs_datasets_py.logic.backends.process import RawProcessResult
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler


@pytest.fixture(autouse=True)
def no_native_or_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("SDK unit test attempted native/network/shared admission")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(hp.os, "system", denied)
    monkeypatch.setattr(hp, "urlopen", denied)
    monkeypatch.setattr(scheduler, "get_global_resource_scheduler", denied)
    monkeypatch.setattr(scheduler.GlobalResourceScheduler, "acquire", denied)


def fixture_archive(path, *, machine=183, version="8.0.300", rid="linux-arm64", runtime="8.0.5", missing=None):
    host = bytearray(64)
    host[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", host, 16, 3, machine)
    files = {
        "dotnet": bytes(host),
        "sdk/8.0.300/dotnet.dll": b"controlled SDK bytes",
        "sdk/8.0.300/.version": f"fixture-commit\n{version}\n{rid}\nfixture\n".encode(),
        "sdk/8.0.300/dotnet.runtimeconfig.json": json.dumps({"runtimeOptions": {"framework": {
            "name": "Microsoft.NETCore.App", "version": runtime}}}).encode(),
        "host/fxr/8.0.5/libhostfxr.so": b"controlled hostfxr",
        "shared/Microsoft.NETCore.App/8.0.5/libcoreclr.so": b"controlled coreclr",
        "shared/Microsoft.NETCore.App/8.0.5/System.Private.CoreLib.dll": b"controlled corelib",
    }
    if missing:
        del files[missing]
    with tarfile.open(path, "w:gz", format=tarfile.USTAR_FORMAT) as output:
        for name, data in files.items():
            row = tarfile.TarInfo(name)
            row.mode = 0o755 if name == "dotnet" else 0o644
            row.size = len(data)
            output.addfile(row, io.BytesIO(data))
    return hashlib.sha512(path.read_bytes()).hexdigest()


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root, cache = tmp_path / "managed", tmp_path / "cache"
    cache.mkdir()
    source = cache / "dotnet-sdk-8.0.300-linux-arm64.tar.gz"
    pin = dict(sdk._PINS["linux-aarch64"])
    pin["sha512"] = fixture_archive(source)
    monkeypatch.setattr(sdk, "_PINS", {"linux-aarch64": pin})
    monkeypatch.setattr(sdk, "_platform_id", lambda: "linux-aarch64")
    state = SimpleNamespace(root=root, cache=cache, source=source, pin=pin,
        calls=[], result=RawProcessResult(returncode=0, stdout=b"8.0.300\n"), hook=None)

    def probe(argv, **kwargs):
        assert control.current_install_limits().build_cpu_slots == 1
        assert budget.current_proof_operation() is not None
        state.calls.append((tuple(argv), dict(kwargs)))
        if state.hook:
            state.hook(len(state.calls), argv, kwargs)
        return state.result

    monkeypatch.setattr(control, "run_install_command", probe)
    state.ensure = lambda **kw: sdk.ensure_dotnet_sdk(yes=True, install_root=root,
        archive_cache_root=cache, **kw)
    state.target = root / "dotnet-sdk-8.0.300-linux-arm64"
    return state


def snapshot(root):
    return {str(path.relative_to(root)): (path.stat().st_mode & 0o777, path.read_bytes())
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("platform_id,rid,machine", [
    ("linux-aarch64", "linux-arm64", 183), ("linux-x86_64", "linux-x64", 62)])
def test_plan_is_inert_detached_and_has_official_pin(tmp_path, monkeypatch, platform_id, rid, machine):
    monkeypatch.setattr(sdk, "_platform_id", lambda: platform_id)
    root = tmp_path / "absent"
    first = sdk.plan_dotnet_sdk_setup(install_root=root)
    second = sdk.ensure_dotnet_sdk(install_root=root)
    assert first == second and not root.exists()
    assert first["rid"] == rid and first["status"] == "planned"
    assert first["archive_url"].endswith(f"dotnet-sdk-8.0.300-{rid}.tar.gz")
    assert len(first["archive_sha512"]) == 128 and sdk._PINS[platform_id]["elf_machine"] == machine
    assert not first["installed"] and not first["version_probe"] and not first["tree_verified"]
    first["dependency_roots"].clear(); first["notes"].clear()
    assert second["dependency_roots"] and second["notes"]


@pytest.mark.parametrize("name,value", [("yes", 1), ("yes", "yes"), ("force", 1), ("force", None)])
def test_explicit_flags_are_exact_bools(tmp_path, name, value):
    with pytest.raises(ValueError, match="bool"):
        sdk.ensure_dotnet_sdk(install_root=tmp_path / "absent", **{name: value})
    assert not (tmp_path / "absent").exists()


def test_unsupported_platform_does_not_create_root(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "_platform_id", lambda: "unsupported")
    with pytest.raises(hp.HyperpropertyInstallBlocked, match="Linux"):
        sdk.ensure_dotnet_sdk(yes=True, install_root=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


def test_fresh_install_authenticates_layout_and_isolates_both_probes(candidate, monkeypatch):
    monkeypatch.setenv("LD_PRELOAD", "/caller/untrusted.so")
    monkeypatch.setenv("DOTNET_STARTUP_HOOKS", "/caller/untrusted.dll")
    result = candidate.ensure()
    assert result["status"] == "installed" and result["installed"]
    assert result["archive_verified"] and result["tree_verified"] and result["version_probe"]
    assert result["support_only"] and result["authorizes_proof"] is False
    assert result["version_probe_output"] == "8.0.300"
    assert result["dependency_roots"] == {"dotnet-sdk": str(candidate.target)}
    assert result["executable_sha256"] == hashlib.sha256((candidate.target / "dotnet").read_bytes()).hexdigest()
    assert len(candidate.calls) == 2
    for argv, kwargs in candidate.calls:
        assert argv[1:] == ("--version",) and Path(argv[0]).is_absolute()
        assert kwargs["inherit_environment"] is False and kwargs["timeout_seconds"] == 30
        env, cwd = kwargs["environment"], kwargs["cwd"]
        assert env["PATH"] == "/usr/bin:/bin" and env["DOTNET_ROOT"] == str(Path(argv[0]).parent)
        assert "LD_PRELOAD" not in env and "DOTNET_STARTUP_HOOKS" not in env
        assert all(Path(env[key]).is_relative_to(cwd) for key in (
            "HOME", "TMPDIR", "DOTNET_CLI_HOME", "NUGET_PACKAGES", "NUGET_HTTP_CACHE_PATH"))
        assert env["DOTNET_MULTILEVEL_LOOKUP"] == "0" and not cwd.exists()
    assert not list(candidate.root.glob(".dotnet-sdk-staging-*"))


def test_cached_reuse_reauthenticates_archive_tree_and_never_probes(candidate):
    first = candidate.ensure()
    before = snapshot(candidate.target)
    second = candidate.ensure()
    assert second["status"] == "already_present" and not second["version_probe"]
    assert second["tree_sha256"] == first["tree_sha256"] and second["archive_verified"]
    assert snapshot(candidate.target) == before and len(candidate.calls) == 2


@pytest.mark.parametrize("change", ["bytes", "missing", "extra", "mode", "forged_manifest", "manifest_bool"])
def test_mutated_tree_or_manifest_is_not_executed_or_silently_replaced(candidate, change):
    candidate.ensure()
    if change == "bytes":
        (candidate.target / "dotnet").write_bytes(b"bad")
    elif change == "missing":
        (candidate.target / "sdk/8.0.300/dotnet.dll").unlink()
    elif change == "extra":
        (candidate.target / "extra").write_text("bad")
    elif change == "mode":
        (candidate.target / "dotnet").chmod(0o644)
    else:
        manifest = candidate.target / sdk.MANIFEST_NAME
        value = json.loads(manifest.read_text())
        value["tree_sha256" if change == "forged_manifest" else "support_only"] = "0" * 64 if change == "forged_manifest" else 1
        manifest.write_text(json.dumps(value))
    before = snapshot(candidate.target)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        candidate.ensure()
    assert len(candidate.calls) == 2 and snapshot(candidate.target) == before


def test_unmanaged_tree_requires_explicit_force_and_force_repairs(candidate):
    candidate.target.mkdir(parents=True)
    (candidate.target / "old").write_text("unmanaged")
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        candidate.ensure()
    assert not candidate.calls and (candidate.target / "old").read_text() == "unmanaged"
    result = candidate.ensure(force=True)
    assert result["installed"] and result["force"] and not (candidate.target / "old").exists()
    assert len(candidate.calls) == 2


@pytest.mark.parametrize("phase", [1, 2])
def test_probe_failure_restores_previous_tree_and_removes_staging(candidate, phase):
    candidate.target.mkdir(parents=True)
    (candidate.target / "old").write_text("preserve")
    before = snapshot(candidate.target)
    def fail(index, *_):
        if index == phase:
            candidate.result = RawProcessResult(returncode=1, stderr=b"loader unavailable")
    candidate.hook = fail
    with pytest.raises(hp.HyperpropertyInstallBlocked, match="version"):
        candidate.ensure(force=True)
    assert snapshot(candidate.target) == before and len(candidate.calls) == phase
    assert not list(candidate.root.glob(".dotnet-sdk-staging-*"))
    assert not list(candidate.root.glob(".*-backup-*"))


@pytest.mark.parametrize("field", ["timed_out", "cancelled", "output_truncated", "process_tree_terminated",
    "resource_exhausted", "workspace_limit_exceeded", "error"])
def test_unsafe_probe_result_never_publishes(candidate, field):
    candidate.result = replace(candidate.result, **{field: "unsafe" if field == "error" else True})
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        candidate.ensure()
    assert not candidate.target.exists() and len(candidate.calls) == 1


@pytest.mark.parametrize("output", [b"8.0.301\n", b"prefix 8.0.300\n", b"8.0.300\n8.0.300\n", b""])
def test_version_must_be_exact(candidate, output):
    candidate.result = replace(candidate.result, stdout=output)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        candidate.ensure()
    assert not candidate.target.exists()


@pytest.mark.parametrize("changes", [{"machine": 62}, {"version": "8.0.301"}, {"rid": "linux-x64"},
    {"runtime": "8.0.6"}, {"missing": "sdk/8.0.300/dotnet.dll"}])
def test_archive_layout_rejected_before_any_native_probe(candidate, changes):
    candidate.pin["sha512"] = fixture_archive(candidate.source, **changes)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        candidate.ensure()
    assert not candidate.calls and not candidate.target.exists()


@pytest.mark.parametrize("location", ["root", "cache", "sdk"])
def test_symlink_destinations_never_followed(candidate, tmp_path, location):
    external = tmp_path / "external"; external.mkdir()
    if location == "root":
        candidate.root.symlink_to(external, target_is_directory=True)
    elif location == "cache":
        candidate.source.unlink(); candidate.cache.rmdir()
        candidate.cache.symlink_to(external, target_is_directory=True)
    else:
        candidate.root.mkdir(); candidate.target.symlink_to(external, target_is_directory=True)
    with pytest.raises(hp.HyperpropertyInstallBlocked):
        candidate.ensure(force=True)
    assert not list(external.iterdir()) and not candidate.calls


def test_cache_inside_sdk_is_rejected_before_mutation(candidate):
    with pytest.raises(hp.HyperpropertyInstallBlocked, match="separate"):
        sdk.ensure_dotnet_sdk(yes=True, install_root=candidate.root, archive_cache_root=candidate.target)
    assert not candidate.root.exists() and not candidate.calls


def test_precancel_and_published_stop_rollback_then_retry(candidate):
    token = threading.Event(); token.set()
    with pytest.raises(budget.ProofOperationCancelled):
        candidate.ensure(cancellation=token)
    assert not candidate.root.exists() and not candidate.calls
    token.clear()
    candidate.target.mkdir(parents=True)
    (candidate.target / "old").write_text("preserve")
    before = snapshot(candidate.target)
    candidate.hook = lambda index, *_: token.set() if index == 2 else None
    with pytest.raises(budget.ProofOperationCancelled):
        candidate.ensure(force=True, cancellation=token)
    assert snapshot(candidate.target) == before
    token.clear(); candidate.hook = None
    assert candidate.ensure(force=True, cancellation=token)["installed"]
    assert budget.current_proof_operation() is None


def test_same_sdk_waiter_cancels_without_partial_tree_exposure(candidate, monkeypatch):
    entered, release, contended, stop = (threading.Event() for _ in range(4))
    actual_lock = threading.Lock()
    class ObservedLock:
        def acquire(self, **kwargs):
            result = actual_lock.acquire(**kwargs)
            if not result:
                contended.set()
            return result
        def release(self):
            actual_lock.release()
    monkeypatch.setitem(transaction._LOCKS, (str(candidate.root), "dotnet-sdk-linux-arm64"), ObservedLock())
    def hold(index, *_):
        if index == 1:
            entered.set()
            assert release.wait(5)
    candidate.hook = hold
    values, errors = [], []
    def run(token=None):
        try:
            values.append(candidate.ensure(cancellation=token, operation_timeout_ms=10_000))
        except BaseException as error:
            errors.append(error)
    first = threading.Thread(target=run)
    second = threading.Thread(target=run, args=(stop,))
    first.start()
    try:
        assert entered.wait(3) and not candidate.target.exists()
        second.start()
        assert contended.wait(3)
        stop.set(); second.join(3)
        assert not second.is_alive() and not candidate.target.exists()
    finally:
        release.set(); first.join(5)
        if second.ident is not None:
            second.join(5)
    assert len(values) == 1 and len(errors) == 1 and isinstance(errors[0], budget.ProofOperationCancelled)
    assert len(candidate.calls) == 2 and values[0]["status"] == "installed"
    assert candidate.ensure()["status"] == "already_present" and len(candidate.calls) == 2
