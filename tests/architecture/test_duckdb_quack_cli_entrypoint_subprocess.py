from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import sysconfig
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ops import ipfs_datasets_duckdb_quack_program as program


def _wait_for_path(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if path.is_file():
            return
        returncode = process.poll()
        if returncode is not None:
            raise AssertionError(f"sealed subprocess exited early: {returncode}")
        time.sleep(0.01)
    raise AssertionError(f"sealed subprocess did not publish {path}")


def _write_test_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path | list[str]]:
    real_program_path = Path(program.__file__).resolve()
    environment_root = tmp_path / "environment"
    site_root = (
        environment_root
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    site_root.mkdir(parents=True)
    launcher = environment_root / "bin/dqk-sealed-python"
    launcher.parent.mkdir(parents=True)
    policy_loaded = tmp_path / "policy-loaded"
    policy_path = tmp_path / "sealed-policy.py"
    policy_path.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                f"Path({str(policy_loaded)!r}).write_text('loaded', encoding='utf-8')",
                "class _Lock:",
                "    def close(self):",
                "        pass",
                "def _acquire_environment_lifecycle_lock(*, exclusive):",
                "    assert exclusive is False",
                "    return _Lock()",
                "def _local_environment_probe(**_kwargs):",
                "    return {}",
                "def _install_task_validation_runtime_adapter():",
                "    return None",
                "",
            )
        ),
        encoding="utf-8",
    )
    stdlib_root = Path(sysconfig.get_path("stdlib")).resolve()
    python_paths = [
        str(
            stdlib_root.parent
            / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
        ),
        str(stdlib_root),
        str(stdlib_root / "lib-dynload"),
        str(site_root),
    ]
    base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    monkeypatch.setenv("IPFS_DATASETS_DQK_BASE_PYTHON", str(base_python))
    monkeypatch.setattr(program, "EXPECTED_ENV_ROOT", environment_root)
    validator_root = environment_root.parent / "ipfs-datasets-duckdb-quack-validator"
    monkeypatch.setattr(program, "BOOTSTRAP_VALIDATOR_ROOT", validator_root)
    monkeypatch.setattr(program, "TASK_VALIDATION_PYTHON", validator_root / "bin/python")
    monkeypatch.setattr(program, "SEALED_PYTHON_LAUNCHER", launcher)
    monkeypatch.setattr(program, "__file__", str(policy_path))
    monkeypatch.setattr(program, "_sealed_python_paths", lambda: list(python_paths))
    launcher.write_text(
        program._sealed_python_launcher_content(python_paths),
        encoding="utf-8",
    )
    launcher.chmod(0o500)
    return {
        "real_program": real_program_path,
        "environment_root": environment_root,
        "launcher": launcher,
        "policy": policy_path,
        "policy_loaded": policy_loaded,
        "python_paths": python_paths,
    }


def test_direct_cli_help_is_cwd_and_pythonpath_independent(tmp_path: Path) -> None:
    poison_package = tmp_path / "poison/ipfs_accelerate_py"
    poison_package.mkdir(parents=True)
    poison_marker = tmp_path / "poison-imported"
    (poison_package / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(poison_marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(poison_package.parent)
    result = subprocess.run(
        [sys.executable, str(Path(program.__file__).resolve()), "--help"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "bootstrap-environment" in result.stdout
    assert "preflight" in result.stdout
    assert "launch" in result.stdout
    assert not poison_marker.exists()
    assert "secret" not in result.stderr.lower()


def test_accelerate_import_resists_poisoned_pythonpath_subprocess(
    tmp_path: Path,
) -> None:
    poison_root = tmp_path / "poison"
    poison_package = poison_root / "ipfs_accelerate_py"
    poison_package.mkdir(parents=True)
    marker = tmp_path / "poison-imported"
    (poison_package / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    program_path = Path(program.__file__).resolve()
    source = "\n".join(
        (
            "import json, os, runpy, sys",
            f"policy = runpy.run_path({str(program_path)!r})",
            "module = policy['_accelerate_module'](",
            "    'ipfs_accelerate_py.agent_supervisor.task_sources.duckdb_task_source',",
            "    'ipfs_accelerate_py.agent_supervisor.duckdb_task_source',",
            ")",
            "root = policy['ACCELERATE_ROOT'].resolve()",
            "resolved = [str(__import__('pathlib').Path(item or '.').resolve()) for item in sys.path]",
            "print(json.dumps({",
            "    'origin': str(module.__file__),",
            "    'protected_root': str(root),",
            "    'protected_root_count': resolved.count(str(root)),",
            "    'skip_core': os.environ.get('IPFS_ACCEL_SKIP_CORE'),",
            "    'import_eager': os.environ.get('IPFS_ACCEL_IMPORT_EAGER'),",
            "}, sort_keys=True))",
        )
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(poison_root), str(program.ACCELERATE_ROOT.resolve()))
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["origin"]).resolve().is_relative_to(
        program.ACCELERATE_ROOT.resolve()
    )
    assert payload["protected_root_count"] == 1
    assert payload["skip_core"] == "1"
    assert payload["import_eager"] == "0"
    assert not marker.exists()
    assert "secret" not in result.stderr.lower()


def test_accelerate_import_rejects_preloaded_foreign_package_subprocess(
    tmp_path: Path,
) -> None:
    poison_root = tmp_path / "poison"
    poison_package = poison_root / "ipfs_accelerate_py"
    poison_package.mkdir(parents=True)
    (poison_package / "__init__.py").write_text("FOREIGN = True\n", encoding="utf-8")
    program_path = Path(program.__file__).resolve()
    source = "\n".join(
        (
            "import ipfs_accelerate_py, runpy",
            f"policy = runpy.run_path({str(program_path)!r})",
            "try:",
            "    policy['_accelerate_module'](",
            "        'ipfs_accelerate_py.agent_supervisor.task_sources.duckdb_task_source',",
            "        'ipfs_accelerate_py.agent_supervisor.duckdb_task_source',",
            "    )",
            "except RuntimeError as exc:",
            "    print(str(exc))",
            "else:",
            "    raise SystemExit('foreign preloaded package was accepted')",
        )
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(poison_root)
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "preloaded accelerator module has a foreign origin" in result.stdout


@pytest.mark.parametrize("external_detach", [False, True])
def test_real_wrapper_process_identity_matches_foreground_and_external_detach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    external_detach: bool,
) -> None:
    wrapper = _write_test_wrapper(tmp_path, monkeypatch)
    launcher = Path(wrapper["launcher"])
    pid_path = tmp_path / "master.pid"
    ready_path = tmp_path / "ready.json"
    release_path = tmp_path / "release"
    probe_path = tmp_path / "identity-probe.py"
    probe_path.write_text(
        "\n".join(
            (
                "import json, os, sys, time",
                "from pathlib import Path",
                "pid_path, ready_path, release_path = map(Path, sys.argv[1:4])",
                "pid_path.write_text(f'{os.getpid()}\\n', encoding='utf-8')",
                "ready_path.write_text(json.dumps({",
                "    'pid': os.getpid(),",
                "    'session_id': os.getsid(0),",
                "    'argv': [item.decode(errors='replace') for item in Path('/proc/self/cmdline').read_bytes().split(b'\\0') if item],",
                "}), encoding='utf-8')",
                "deadline = time.monotonic() + 10.0",
                "while not release_path.exists() and time.monotonic() < deadline:",
                "    time.sleep(0.01)",
                "if not release_path.exists():",
                "    raise SystemExit('release was not published')",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(program, "MASTER_PID", pid_path)
    logical_command = [
        str(launcher),
        str(probe_path),
        str(pid_path),
        str(ready_path),
        str(release_path),
    ]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        **program._sealed_python_environment(),
    }
    marker = program._launch_marker()
    process = subprocess.Popen(
        logical_command,
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=external_detach,
    )
    try:
        _wait_for_path(ready_path, process)
        payload = json.loads(ready_path.read_text(encoding="utf-8"))
        actual = program._process_birth_identity(process.pid)
        assert actual is not None
        assert tuple(actual["argv"]) == program._expanded_sealed_python_argv(
            logical_command
        )
        assert program._logical_sealed_python_argv(actual["argv"]) == tuple(
            logical_command
        )
        assert program._process_identity_matches_sealed_command(
            actual,
            logical_command,
        )
        matching_relaunches = program._matching_relaunch_masters(
            logical_command,
            marker,
        )
        assert [item["pid"] for item in matching_relaunches] == [process.pid]
        assert not program._process_identity_matches_sealed_command(
            actual,
            [*logical_command, "--foreign"],
        )
        assert program._launched_identity_matches(
            actual,
            expected_command=logical_command,
            marker=marker,
            expected_pid=process.pid,
        )
        assert payload["argv"] == list(actual["argv"])
        if external_detach:
            assert payload["session_id"] == process.pid
        else:
            assert payload["session_id"] != process.pid
    finally:
        release_path.write_text("release\n", encoding="utf-8")
        process.wait(timeout=15)
    assert process.returncode == 0


def test_wrapper_scrubs_import_environment_and_trusts_base_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = _write_test_wrapper(tmp_path, monkeypatch)
    output_path = tmp_path / "runtime.json"
    validation_path = tmp_path / "validate-runtime.py"
    validation_path.write_text(
        "\n".join(
            (
                "import json, os, runpy, sys",
                "from pathlib import Path",
                f"policy = runpy.run_path({str(wrapper['real_program'])!r})",
                "probe = {",
                "    'python_sys_path': list(sys.path[1:]),",
                "    'base_python_executable': str(Path(sys.executable).resolve()),",
                "    'base_python_sha256': policy['_sha256_file'](Path(sys.executable).resolve()),",
                "    'python_executable': os.environ['IPFS_DATASETS_DQK_PYTHON_EXECUTABLE'],",
                "}",
                "valid, detail = policy['_live_runtime_import_contract'](probe)",
                "runtime = policy['_runtime_python_environment'](os.environ)",
                f"Path({str(output_path)!r}).write_text(json.dumps({{'valid': valid, 'detail': detail, 'runtime': runtime, 'executable': sys.executable, 'prefix': sys.prefix}}, sort_keys=True), encoding='utf-8')",
            )
        ),
        encoding="utf-8",
    )
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(tmp_path / "poison"),
        "PYTHONUNRELATED": "foreign",
        "LD_FOREIGN_TEST": "foreign",
        "IPFS_ACCEL_SKIP_CORE": "0",
        "IPFS_ACCEL_IMPORT_EAGER": "1",
    }
    result = subprocess.run(
        [str(wrapper["launcher"]), str(validation_path)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["valid"] is True, payload["detail"]
    assert payload["runtime"] == program._sealed_python_environment()
    assert Path(payload["executable"]).resolve() == program._trusted_base_python_path()
    assert Path(payload["prefix"]).resolve() == Path(wrapper["environment_root"])


def test_wrapper_rejects_bootstrap_before_shared_lock_or_policy_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = _write_test_wrapper(tmp_path, monkeypatch)
    policy_loaded = Path(wrapper["policy_loaded"])
    result = subprocess.run(
        [
            str(wrapper["launcher"]),
            Path(wrapper["policy"]).name,
            "bootstrap-environment",
        ],
        cwd=tmp_path,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            **program._sealed_python_environment(),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode != 0
    assert "sealed Python cannot dispatch bootstrap-environment" in result.stderr
    assert not policy_loaded.exists()


def test_retry_launch_failure_cleanup_recognizes_expanded_wrapper_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = _write_test_wrapper(tmp_path, monkeypatch)
    logical_command = [
        str(wrapper["launcher"]),
        "-m",
        "ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner",
        "--stamp",
        "dqk-test-" + "a" * 32,
    ]
    expanded = program._expanded_sealed_python_argv(logical_command)
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "master")
    monkeypatch.setattr(program, "MASTER_PID", tmp_path / "master/supervisor.pid")
    monkeypatch.setattr(program, "_assert_captured_retry_tree_dead", lambda _journal: None)
    monkeypatch.setattr(program, "_matching_relaunch_masters", lambda *_args: ())
    monkeypatch.setattr(program, "_live_program_master_identities", lambda: ())
    monkeypatch.setattr(
        program,
        "_assert_retry_runtime_quiescent",
        lambda *_args: None,
    )
    monkeypatch.setattr(program, "_read_pid", lambda _path: None)

    class Process:
        pid = 4242

        def wait(self, *, timeout: float) -> int:
            assert timeout == 30
            return 0

    monkeypatch.setattr(program.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(
        program,
        "_bind_launched_master",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bind failed")),
    )
    monkeypatch.setattr(
        program,
        "_process_birth_identity",
        lambda pid: {"pid": pid, "argv": expanded},
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(program.os, "kill", lambda pid, signum: signals.append((pid, signum)))
    with pytest.raises(RuntimeError, match="bind failed"):
        program._launch_or_adopt_retry_master(
            {"snapshot": object()},
            {"relaunch": {"command": logical_command, "marker": {}}},
        )
    assert signals == [(4242, signal.SIGTERM)]


def test_smoke_uses_the_same_non_runner_detach_topology_as_launch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = SimpleNamespace(plan_root_cid="plan:test", repository_tree_id="tree:test")
    projection = SimpleNamespace(
        snapshot=snapshot,
        row_counts={},
    )
    source = SimpleNamespace(
        snapshot=lambda: snapshot,
        validate_integrity=lambda: None,
        read_consistent_projection=lambda _tables: projection,
    )
    captured: dict[str, object] = {}

    def command(**kwargs):
        captured.update(kwargs)
        return [str(program.SEALED_PYTHON_LAUNCHER), "-m", "runner"]

    monkeypatch.setattr(program, "_source", lambda: source)
    monkeypatch.setattr(program, "supervisor_command", command)
    assert program.cmd_smoke(SimpleNamespace(dry_run=True)) == 0
    assert captured == {"lanes": 2, "duration_seconds": 60, "detach": False}
    assert "--detach" not in capsys.readouterr().out
