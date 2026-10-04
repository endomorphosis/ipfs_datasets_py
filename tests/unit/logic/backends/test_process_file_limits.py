"""Separate per-file limits preserve private workspace aggregate enforcement."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends import process as module


@pytest.mark.parametrize("invalid", [True, False, 0, -1, 1.5, "8192", float("inf")])
def test_file_limit_rejects_invalid_values(invalid):
    with pytest.raises(module.ToolProcessError, match="max_file_bytes"):
        module.ToolRunLimits(max_file_bytes=invalid)


@pytest.mark.parametrize("file_bytes", [None, 1, 4 * 1024**3])
def test_posix_limit_callback_uses_explicit_file_cap_or_workspace_fallback(monkeypatch, file_bytes):
    resource = pytest.importorskip("resource")
    observed = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, value: observed.append((kind, value)))
    limits = module.ToolRunLimits(max_workspace_bytes=64 * 1024**2, max_file_bytes=file_bytes)
    callback = module._resource_preexec(limits)
    if callback is None:
        pytest.skip("POSIX resource callback")
    callback()
    expected = limits.max_workspace_bytes if file_bytes is None else file_bytes
    assert (resource.RLIMIT_FSIZE, (expected, expected)) in observed


@pytest.mark.parametrize("file_bytes", [None, 1, 4 * 1024**3])
def test_linux_limit_argv_uses_explicit_file_cap_or_workspace_fallback(monkeypatch, file_bytes):
    monkeypatch.setattr(module, "_linux_prlimit_path", lambda: "/trusted/prlimit")
    limits = module.ToolRunLimits(max_workspace_bytes=64 * 1024**2, max_file_bytes=file_bytes)
    command = module._linux_resource_argv(("native-tool",), limits)
    expected = limits.max_workspace_bytes if file_bytes is None else file_bytes
    assert f"--fsize={expected}:{expected}" in command
    assert command[-2:] == ["--", "native-tool"]


def test_disabled_file_limit_preserves_legacy_opt_out(monkeypatch):
    resource = pytest.importorskip("resource")
    observed = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, value: observed.append((kind, value)))
    monkeypatch.setattr(module, "_linux_prlimit_path", lambda: "/trusted/prlimit")
    limits = module.ToolRunLimits(max_file_bytes=1, enforce_file_size_limit=False)
    callback = module._resource_preexec(limits)
    if callback is not None:
        callback()
    assert not any(kind == resource.RLIMIT_FSIZE for kind, _ in observed)
    assert not any(arg.startswith("--fsize=") for arg in module._linux_resource_argv(("native-tool",), limits))


def _native_run(tmp_path: Path, script: str, *arguments: str, max_file_bytes=None, compute_limits=True):
    if not sys.platform.startswith("linux"):
        pytest.skip("Native Linux prlimit qualification")
    runner = module.BoundedToolRunner(workspace_root=tmp_path / "workspaces")
    limits = module.ToolRunLimits(
        timeout_seconds=3,
        cpu_seconds=1 if compute_limits else None,
        memory_bytes=256 * 1024**2 if compute_limits else None,
        max_input_bytes=1024,
        max_output_bytes=1024,
        max_workspace_bytes=4096,
        max_file_bytes=max_file_bytes,
    )
    result = runner.run(module.ToolRunRequest(argv=(sys.executable, "-c", script, *arguments), limits=limits))
    assert result.workspace_cleaned
    assert not list((tmp_path / "workspaces").iterdir())
    return result


def test_native_external_file_can_exceed_private_workspace_with_explicit_file_cap(tmp_path):
    target = tmp_path / "external.heap"
    result = _native_run(
        tmp_path,
        "import pathlib, sys; pathlib.Path(sys.argv[1]).write_bytes(b'x' * 8192)",
        str(target),
        max_file_bytes=8192,
    )
    assert result.ok, result
    assert target.stat().st_size == 8192
    assert not result.workspace_limit_exceeded


@pytest.mark.parametrize("max_file_bytes,expected_size", [(None, 4096), (8192, 8192)])
def test_native_external_file_is_stopped_at_default_or_explicit_file_cap(tmp_path, max_file_bytes, expected_size):
    target = tmp_path / "external.heap"
    result = _native_run(
        tmp_path,
        "import os, signal, sys; signal.signal(signal.SIGXFSZ, signal.SIG_DFL); "
        "fd = os.open(sys.argv[1], os.O_CREAT | os.O_WRONLY, 0o600); "
        "os.write(fd, b'x' * int(sys.argv[2])); os.write(fd, b'x'); os.close(fd)",
        str(target), str(expected_size),
        max_file_bytes=max_file_bytes,
        compute_limits=False,
    )
    assert not result.ok
    assert result.returncode == -signal.SIGXFSZ
    assert result.resource_exhausted
    assert target.stat().st_size == expected_size
    assert not result.workspace_limit_exceeded


def test_larger_file_cap_does_not_weaken_private_workspace_aggregate_bound(tmp_path):
    result = _native_run(
        tmp_path,
        "import pathlib; pathlib.Path('first').write_bytes(b'a' * 3072); "
        "pathlib.Path('second').write_bytes(b'b' * 3072)",
        max_file_bytes=8192,
    )
    assert result.returncode == 0
    assert not result.ok
    assert result.workspace_limit_exceeded and result.resource_exhausted
