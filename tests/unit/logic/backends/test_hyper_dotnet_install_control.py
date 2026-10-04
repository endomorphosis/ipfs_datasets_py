"""Owned SDK probe environments with real private admission, no native work."""
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.installers import install_control as control
from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from tests.unit.logic.backends._python_admission_fixtures import python_pool


@pytest.fixture(autouse=True)
def no_external_work(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("SDK control fixture attempted native or shared admission")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", denied)


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_environment_inheritance_requires_exact_bool_before_admission(value):
    with pytest.raises(ValueError, match="inherit_environment"):
        control.run_install_command([sys.executable, "-V"], inherit_environment=value)


@pytest.mark.parametrize("environment", [{"BAD=KEY": "x"}, {"KEY": "bad\x00value"},
    {"KEY": 3}, {3: "value"}, {"KEY": "x" * 131_072}])
def test_malformed_environment_is_rejected_before_shared_admission(environment):
    with pytest.raises(ValueError, match="environment"):
        control.run_install_command([sys.executable, "-V"],
            environment=environment, inherit_environment=False)


def test_isolated_environment_does_not_inherit_loader_or_sdk_overrides(monkeypatch, python_pool):
    names = ("DOTNET_STARTUP_HOOKS", "DOTNET_ADDITIONAL_DEPS", "DOTNET_SHARED_STORE",
             "MSBuildSDKsPath", "LD_PRELOAD", "LD_LIBRARY_PATH", "CONTROL_HOST_SENTINEL")
    for name in names:
        monkeypatch.setenv(name, "untrusted-host-value")
    supplied = {"PATH": "/usr/bin:/bin", "CONTROL_CALLER_SENTINEL": "explicit"}
    def execute(executor, invocation, cancellation):
        assert not any(name in invocation.environment for name in names)
        assert invocation.environment["CONTROL_CALLER_SENTINEL"] == "explicit"
        assert invocation.environment["MAKEFLAGS"] == "-j1"
        assert invocation.environment["DOTNET_PROCESSOR_COUNT"] == "1"
        assert invocation.limits.resident_memory_bytes == 1024**3
        return process.RawProcessResult(returncode=0)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with control.installation_scope(scheduler=python_pool.owner):
        result = control.run_install_command([sys.executable, "-V"],
            environment=supplied, inherit_environment=False)
    assert result.returncode == 0 and python_pool.acquired[-1].released
    assert supplied == {"PATH": "/usr/bin:/bin", "CONTROL_CALLER_SENTINEL": "explicit"}


def test_default_environment_inheritance_remains_compatible(monkeypatch, python_pool):
    monkeypatch.setenv("CONTROL_HOST_SENTINEL", "existing")
    def execute(executor, invocation, cancellation):
        assert invocation.environment["CONTROL_HOST_SENTINEL"] == "existing"
        return process.RawProcessResult(returncode=0)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with control.installation_scope(scheduler=python_pool.owner):
        control.run_install_command([sys.executable, "-V"])
    assert python_pool.acquired[-1].released


def test_isolated_command_lookup_does_not_use_ambient_path(monkeypatch, python_pool):
    observed = []; original = control.shutil.which
    monkeypatch.setenv("PATH", "/untrusted-host-bin")
    def which(command, *, path=None):
        observed.append(path)
        return original(command, path=path)
    monkeypatch.setattr(control.shutil, "which", which)
    monkeypatch.setattr(process.SubprocessExecutor, "execute",
                        lambda *args, **kwargs: process.RawProcessResult(returncode=0))
    with control.installation_scope(scheduler=python_pool.owner):
        control.run_install_command([sys.executable, "-V"], inherit_environment=False)
    assert observed == [os.defpath] and python_pool.acquired[-1].released


@pytest.mark.parametrize("stop", ["complete", "exception", "cancel"])
def test_disposable_dotnet_probe_owns_first_use_files_and_always_cleans(monkeypatch, python_pool, tmp_path, stop):
    executable = tmp_path / "sdk" / "dotnet"
    executable.parent.mkdir(); executable.write_bytes(b"fixture, never executed\n"); executable.chmod(0o755)
    cache_keys = ("HOME", "USERPROFILE", "DOTNET_CLI_HOME", "TMPDIR", "TMP", "TEMP",
                  "NUGET_PACKAGES", "NUGET_HTTP_CACHE_PATH", "NUGET_PLUGINS_CACHE_PATH")
    outside = tmp_path / "outside"
    for key in cache_keys:
        monkeypatch.setenv(key, str(outside))
    supplied = {key: str(outside) for key in cache_keys}
    seen = []; stop_event = threading.Event()
    def execute(executor, invocation, cancellation):
        seen.append(invocation.cwd)
        for key in cache_keys:
            path = Path(invocation.environment[key])
            assert path.is_relative_to(invocation.cwd)
            path.mkdir(parents=True, exist_ok=True)
            (path / "first-use.fixture").write_bytes(b"owned")
        assert invocation.environment["DOTNET_CLI_TELEMETRY_OPTOUT"] == "1"
        assert invocation.environment["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] == "1"
        assert invocation.limits.enforce_file_size_limit is False
        if stop == "exception":
            raise OSError("controlled probe failure")
        if stop == "cancel":
            stop_event.set()
        return process.RawProcessResult(returncode=0, stdout=b"8.0.300\n")
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    def call():
        with control.installation_scope(scheduler=python_pool.owner, cancellation=stop_event):
            return control.run_install_command([str(executable), "--version"], environment=supplied)
    if stop == "exception":
        with pytest.raises(OSError, match="controlled"):
            call()
    elif stop == "cancel":
        with pytest.raises(ProofOperationCancelled):
            call()
    else:
        assert call().returncode == 0
    assert seen and all(not path.exists() for path in seen)
    assert not outside.exists() and python_pool.acquired[-1].released
    assert all(value == str(outside) for value in supplied.values())


def test_explicit_build_workspace_keeps_callers_owned_cache(monkeypatch, python_pool, tmp_path):
    dotnet = tmp_path / "dotnet"; dotnet.write_bytes(b"fixture"); dotnet.chmod(0o755)
    home = tmp_path / "build-home"
    def execute(executor, invocation, cancellation):
        assert invocation.cwd == tmp_path
        assert invocation.environment["DOTNET_CLI_HOME"] == str(home)
        assert not (tmp_path / ".dotnet-probe").exists()
        return process.RawProcessResult(returncode=0)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with control.installation_scope(scheduler=python_pool.owner):
        control.run_install_command([str(dotnet), "--version"], cwd=tmp_path,
            environment={"DOTNET_CLI_HOME": str(home)}, inherit_environment=False)
    assert python_pool.acquired[-1].released


def test_autohyper_recipe_disables_sdk_workload_writes_through_bounded_transport(monkeypatch, python_pool, tmp_path):
    from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
    required = {"DOTNET_SKIP_WORKLOAD_INTEGRITY_CHECK": "true",
                "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "true",
                "DOTNET_NUGET_SIGNATURE_VERIFICATION": "true"}
    for key, value in required.items():
        monkeypatch.setenv(key, "false" if value == "true" else "true")
    sdk = tmp_path / "sdk"; sdk.mkdir()
    dotnet = sdk / "dotnet"; dotnet.write_bytes(b"fixture, never executed"); dotnet.chmod(0o755)
    source = tmp_path / "source"; project = source / "src/AutoHyper"; project.mkdir(parents=True)
    (project / "Configuration.fs").write_text("module Configuration\n" + hp._AUTOHYPER_RELOCATABLE_CONFIG_ANCHOR)
    dependencies = tuple(hp.DependencyIdentity(name=name, constraint="fixture",
        executable=str(dotnet if name == "dotnet" else tmp_path / name),
        version_output="fixture", executable_sha256="a" * 64)
        for name in ("dotnet", "autfilt", "ltl2tgba"))
    observed = []
    def execute(executor, invocation, cancellation):
        target = invocation.argv[3]
        observed.append(target)
        assert invocation.argv[1:3] == ("msbuild", "src/AutoHyper/AutoHyper.fsproj")
        assert invocation.argv[0] == str(dotnet) and invocation.cwd == source
        assert {key: invocation.environment[key] for key in required} == required
        assert Path(invocation.environment["DOTNET_CLI_HOME"]).is_relative_to(source)
        if target == "-target:Restore":
            assert "-property:RestorePackagesWithLockFile=true" in invocation.argv
            (project / "packages.lock.json").write_text("{}\n")
        else:
            assert target == "-target:Build"
            assert "-property:Configuration=Release" in invocation.argv
            assert "-property:OutputPath=" + str(source / "app") in invocation.argv
            app = source / "app"; app.mkdir(); (app / "AutoHyper").write_bytes(b"\x7fELF-fixture")
        return process.RawProcessResult(returncode=0)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with control.installation_scope(scheduler=python_pool.owner):
        executable, _, lockfiles = hp._build_upstream_source(hp.TOOL_AUTOHYPER, source, dependencies)
    assert observed == ["-target:Restore", "-target:Build"] and executable.is_file()
    assert "upstream/src/AutoHyper/packages.lock.json" in lockfiles
    assert not (source / ".hyper-build-cache").exists()
    assert list(sdk.iterdir()) == [dotnet]
    assert len(python_pool.acquired) == 2 and all(lease.released for lease in python_pool.acquired)
