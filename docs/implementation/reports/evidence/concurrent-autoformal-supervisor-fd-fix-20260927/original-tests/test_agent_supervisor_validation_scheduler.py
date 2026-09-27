from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_accelerate_py.agent_supervisor.todo_daemon.engine import (
    command_runner_from_legacy_function,
    run_validation_commands,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    PortalTask,
    TodoImplementationDaemon,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_commands import (
    ValidationStage,
    build_validation_commands,
    select_validation_commands,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_runtime import (
    PROOF_REUSE_STATE_ROOT_ENV,
    VALIDATION_FILESYSTEM_BOUNDARY_SCHEMA,
    VALIDATION_NPM_CACHE_ENV,
    VALIDATION_PATH_ENV,
    VALIDATION_PLAYWRIGHT_BROWSERS_PATH_ENV,
    VALIDATION_PYTHON_ENV,
    VALIDATION_PYTHON_INTERPRETER_SHA256_ENV,
    VALIDATION_PYTHON_INTERPRETER_STAT_ENV,
    VALIDATION_PYTHON_LAUNCHER_MODE_ENV,
    VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV,
    VALIDATION_PYTHON_LAUNCHER_SHA256_ENV,
    VALIDATION_PYTHON_PROFILE_ENV,
    VALIDATION_PYTHONPATH_ENV,
    VALIDATION_RUFF_EXECUTABLE_ENV,
    VALIDATION_RUFF_EXECUTABLE_MODE_ENV,
    VALIDATION_RUFF_EXECUTABLE_SHA256_ENV,
    VALIDATION_RUFF_EXECUTABLE_STAT_ENV,
    ValidationRuntimeError,
    build_hermetic_validation_runtime,
    build_validation_environment,
    canonical_validation_environment_contract,
    sealed_validation_python_runner,
    validation_argv_command,
    validation_environment_for_runner,
    validation_python_executable,
    validation_python_launcher_environment,
    validation_readonly_state_command,
    validation_shell_command,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_scheduler import (
    HermeticValidationPolicy,
    ValidationResultCache,
    ValidationScheduler,
    _validation_result_digest,
    build_validation_cache_key,
    collect_dependency_state,
    hermetic_validation_runner,
)


def _result(spec, *, returncode: int = 0) -> dict[str, object]:
    return {
        "command": spec.command,
        "raw_command": spec.raw_command,
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "returncode": returncode,
        "output": f"output:{spec.command}",
    }


def _sealed_daemon_environment() -> dict[str, str]:
    return validation_environment_for_runner(
        build_validation_environment(),
        TodoImplementationDaemon._validation_command_runner,
    )


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _repo(path: Path) -> str:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Validation Test")
    _git(path, "config", "user.email", "validation@example.invalid")
    (path / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='1'\n", encoding="utf-8"
    )
    (path / "src").mkdir()
    (path / "src" / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "baseline")
    return _git(path, "rev-parse", "HEAD")


def test_validation_runtime_scrubs_hooks_secrets_and_inherited_path(
    tmp_path: Path,
) -> None:
    trusted_bin = Path("/usr/bin").resolve()
    approved_npm_cache = tmp_path / "approved-npm-cache"
    approved_npm_cache.mkdir()
    approved_playwright_browsers = tmp_path / "approved-playwright-browsers"
    approved_playwright_browsers.mkdir()
    source = {
        "AWS_SECRET_ACCESS_KEY": "secret",
        "BASH_ENV": str(tmp_path / "bash-env"),
        "CARGO_HOME": str(tmp_path / "cargo-home"),
        "ENV": str(tmp_path / "env"),
        "GRADLE_USER_HOME": str(tmp_path / "gradle-home"),
        "HOME": str(tmp_path / "home"),
        "NPM_CONFIG_CACHE": str(tmp_path / "inherited-npm-cache"),
        "NPM_CONFIG_OFFLINE": "true",
        "PATH": str(tmp_path / "hostile-bin"),
        "PROMPT_COMMAND": "touch compromised",
        "PYTHON": str(tmp_path / "hostile-python"),
        "RUSTUP_HOME": str(tmp_path / "rustup-home"),
        VALIDATION_NPM_CACHE_ENV: str(approved_npm_cache),
        VALIDATION_PATH_ENV: str(trusted_bin),
        VALIDATION_PLAYWRIGHT_BROWSERS_PATH_ENV: str(approved_playwright_browsers),
    }

    environment = build_validation_environment(source)

    assert environment["PATH"] == str(trusted_bin)
    assert environment["HOME"] == "/nonexistent/ipfs-accelerate-validation"
    assert environment["XDG_CONFIG_HOME"] == environment["HOME"]
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHON"] == str(Path(sys.executable).resolve())
    assert environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV].endswith(":canonical-direct")
    assert len(environment[VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV]) == 64
    assert len(environment[VALIDATION_PYTHON_LAUNCHER_SHA256_ENV]) == 64
    assert len(environment[VALIDATION_PYTHON_INTERPRETER_SHA256_ENV]) == 64
    assert environment[VALIDATION_PYTHON_INTERPRETER_STAT_ENV].startswith('{"device":')
    assert environment["NPM_CONFIG_CACHE"] == str(approved_npm_cache.resolve())
    assert environment["NPM_CONFIG_OFFLINE"] == "true"
    assert environment["PLAYWRIGHT_BROWSERS_PATH"] == str(approved_playwright_browsers.resolve())
    assert environment["NPM_CONFIG_GLOBALCONFIG"] == "/dev/null"
    assert environment["NPM_CONFIG_USERCONFIG"] == "/dev/null/npmrc"
    assert environment["NPM_CONFIG_USERCONFIG"] != environment["NPM_CONFIG_GLOBALCONFIG"]
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["PYTHONHASHSEED"] == "0"
    assert not {
        "AWS_SECRET_ACCESS_KEY",
        "BASH_ENV",
        "CARGO_HOME",
        "ENV",
        "GRADLE_USER_HOME",
        "PROMPT_COMMAND",
        "RUSTUP_HOME",
        VALIDATION_NPM_CACHE_ENV,
        VALIDATION_PATH_ENV,
        VALIDATION_PLAYWRIGHT_BROWSERS_PATH_ENV,
    } & set(environment)
    shell_command = validation_shell_command("test -f artifact")
    assert shell_command[:4] == ["/bin/bash", "--noprofile", "--norc", "-c"]
    assert "readonly -f _ipfs_accelerate_validation_python" in shell_command[4]
    assert shell_command[4].endswith("; test -f artifact")
    python_code = validation_shell_command(
        "python3 -c 'import sys; sys.stdin.read()'"
    )
    assert "readonly -f _ipfs_accelerate_validation_python" in python_code[4]
    assert python_code[4].endswith(
        "; python3 -c 'import sys; sys.stdin.read()'"
    )
    quoted_filter = validation_shell_command(
        "python -m pytest -q test/api/procedure_compiler/test_task_family.py "
        "-k 'boundary or negative or unsafe'"
    )
    filter_payload = quoted_filter[-1]
    assert "-k 'boundary or negative or unsafe'" in filter_payload
    assert " -k boundary or negative or unsafe" not in filter_payload
    nested_python = validation_shell_command(
        "PYTHONPATH=src:. 'python3 -m pytest -q test/foo.py'"
    )
    nested_payload = nested_python[-1]
    assert "python3 -m pytest -q test/foo.py" in nested_payload
    assert "'python3 -m pytest -q test/foo.py'" not in nested_payload
    for nested_shell in (
        "bash -lc 'python -c \"raise SystemExit(0)\"'",
        "true && bash -lc 'python -V'",
        "command bash -lc 'python -V'",
        ":; /bin/sh -c 'python -V'",
        "env SAFE=1 /bin/bash -c 'python -V'",
        "true&&bash -lc 'python -V'",
        "echo x|bash -lc 'python -V'",
        "true;/bin/sh -c 'python -V'",
    ):
        with pytest.raises(
            ValidationRuntimeError,
            match="nested validation shells",
        ):
            validation_shell_command(nested_shell)
    with pytest.raises(
        ValidationRuntimeError,
        match="must provide command text with -c",
    ):
        validation_argv_command(("/bin/bash", "validation-script.sh"))
    for wrapped_shell in (
        ("env", "SAFE=1", "bash", "-lc", "python -V"),
        ("command", "/bin/sh", "-c", "python -V"),
    ):
        with pytest.raises(
            ValidationRuntimeError,
            match="wrapped validation shells",
        ):
            validation_argv_command(wrapped_shell)
    for direct_ruff in (
        ("python3", "-m", "ruff", "check", "."),
        ("python3", "-mruff", "--version"),
        ("python3", "-Bmruff", "--version"),
        ("python3", "-Bm", "ruff", "--version"),
        ("/usr/bin/env", "python3", "-m", "ruff", "--version"),
        ("/usr/bin/timeout", "10", "python3", "-m", "ruff", "--version"),
        (
            "/usr/bin/timeout",
            "10",
            "/usr/bin/env",
            "-S",
            "python3 -m ruff --version",
        ),
        ("/usr/bin/nice", "/usr/bin/env", "-Spython3 -mruff --version"),
        ("ruff", "--version"),
        ("/usr/bin/env", "-S", "python3 -m ruff --version"),
    ):
        with pytest.raises(
            ValidationRuntimeError,
            match="direct argv Ruff validation requires the sealed",
        ):
            validation_argv_command(direct_ruff)
    for unsealed_python in (
        ("/usr/bin/python3", "-c", "print('reviewed')"),
        ("/usr/bin/timeout", "5", "python3", "-c", "print('reviewed')"),
    ):
        with pytest.raises(
            ValidationRuntimeError,
            match="direct argv Python|wrapped direct argv Python",
        ):
            validation_argv_command(unsealed_python)
    for wrapped_ruff in (
        "command python3 -m ruff --version",
        "/usr/bin/python3 -m ruff --version",
        "env python3 -m ruff --version",
        "env -S 'python3 -m ruff --version'",
        "env --split-string='python3 -mruff --version'",
        "timeout 5 python3 -m ruff --version",
        '"$IPFS_ACCELERATE_VALIDATION_PYTHON_EXECUTABLE" -m ruff --version',
        'env "$IPFS_ACCELERATE_VALIDATION_PYTHON_EXECUTABLE" -m ruff --version',
        "ruff --version",
        "/usr/bin/python3 -m ${NO_SUCH:-ruff} --version",
        "/usr/bin/python3 -m ruf? --version",
        "PATH=.:$PATH r?ff --version",
    ):
        with pytest.raises(
            ValidationRuntimeError,
            match=(
                "Ruff validation must use|direct Ruff validation requires|"
                "embedded Python or Ruff validation arguments|"
                "dynamic validation command names|validation Python must use"
            ),
        ):
            validation_shell_command(wrapped_ruff)
    for dynamic_shell in (
        "echo `bash -lc 'python -V'`",
        "echo $(bash -lc 'python -V')",
        "eval \"bash -lc 'python -V'\"",
    ):
        with pytest.raises(
            ValidationRuntimeError,
            match="dynamic command substitution|dynamic shell evaluation",
        ):
            validation_shell_command(dynamic_shell)

    with pytest.raises(ValidationRuntimeError, match="must be absolute"):
        build_validation_environment({VALIDATION_PATH_ENV: "relative/bin"})
    writable_bin = tmp_path / "writable-bin"
    writable_bin.mkdir()
    with pytest.raises(ValidationRuntimeError, match="must not be writable"):
        build_validation_environment({VALIDATION_PATH_ENV: str(writable_bin)})
    replaceable_bin = tmp_path / "replaceable-bin"
    replaceable_bin.mkdir()
    replaceable_bin.chmod(0o555)
    # A user namespace may report the chmod-555 leaf itself as writable due to
    # its mapped root capability; either the leaf or its replaceable ancestor
    # must still be rejected.
    with pytest.raises(ValidationRuntimeError, match="must not be writable"):
        build_validation_environment({VALIDATION_PATH_ENV: str(replaceable_bin)})


def test_validation_runtime_rejects_unknown_python_profile() -> None:
    with pytest.raises(
        ValidationRuntimeError,
        match="must be default or raw-no-site",
    ):
        build_validation_environment(
            {VALIDATION_PYTHON_PROFILE_ENV: "unknown-profile"}
        )


def test_raw_no_site_profile_rejects_unsealed_runner() -> None:
    with pytest.raises(
        ValidationRuntimeError,
        match="requires a sealed Python runner",
    ):
        validation_environment_for_runner(
            build_validation_environment(
                {VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"}
            ),
            lambda **_kwargs: {},
        )


def test_proof_reuse_state_root_capability_is_canonical_isolated_and_bound(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "proof-backed-test-reuse-v8"
    state_root.mkdir()
    workspace = state_root / "worktrees" / "candidate"
    workspace.mkdir(parents=True)
    control_state = state_root / "state"
    control_state.mkdir()
    control_receipt = control_state / "receipt.json"
    control_receipt.write_text("sealed-receipt", encoding="utf-8")
    merge_queue = state_root / "merge-queue"
    merge_queue.mkdir()
    control_lock = state_root / "control.lock"
    control_lock.write_text("locked", encoding="utf-8")
    workspace_multilink = workspace / "workspace-multilink"
    workspace_multilink.write_text("before", encoding="utf-8")
    os.link(workspace_multilink, workspace / "workspace-multilink-alias")
    historical_root = tmp_path / "proof-backed-test-reuse-v6"
    historical_root.mkdir()
    historical_receipt = historical_root / "receipt.json"
    historical_receipt.write_text("historical-receipt", encoding="utf-8")
    state_root_alias = tmp_path / "state-root-alias"
    state_root_alias.symlink_to(state_root, target_is_directory=True)
    alternate_root = tmp_path / "alternate-proof-backed-test-reuse-v8"
    alternate_root.mkdir()
    hostile_home = tmp_path / "host-home"
    hostile_state = tmp_path / "host-state"
    source = {
        "HOME": str(hostile_home),
        "XDG_STATE_HOME": str(hostile_state),
        PROOF_REUSE_STATE_ROOT_ENV: str(state_root_alias),
    }

    environment = build_validation_environment(source)
    alternate_environment = build_validation_environment(
        {PROOF_REUSE_STATE_ROOT_ENV: str(alternate_root)}
    )

    assert environment[PROOF_REUSE_STATE_ROOT_ENV] == str(
        state_root.resolve()
    )
    assert environment["HOME"] == "/nonexistent/ipfs-accelerate-validation"
    assert environment["XDG_CACHE_HOME"] == environment["HOME"]
    assert environment["XDG_CONFIG_HOME"] == environment["HOME"]
    assert environment["XDG_DATA_HOME"] == environment["HOME"]
    assert environment["XDG_STATE_HOME"] == environment["HOME"]

    probe = f"""
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(os.environ[{PROOF_REUSE_STATE_ROOT_ENV!r}])
failures = []
operations = (
    lambda: (root / "state" / "receipt.json").write_text("tampered"),
    lambda: (root / "merge-queue" / "forged.json").write_text("forged"),
    lambda: (root / "control.lock").unlink(),
    lambda: (root / "state" / "receipt.json").rename(root / "moved.json"),
    lambda: (root.parent / "proof-backed-test-reuse-v6" / "receipt.json").write_text("tampered"),
)
for operation in operations:
    try:
        operation()
    except PermissionError:
        failures.append("denied")
    else:
        failures.append("allowed")
(Path.cwd() / "workspace-write").write_text("workspace-ok")
(Path.cwd() / "workspace-multilink-alias").write_text("workspace-link-ok")
private_home = Path(os.environ["HOME"])
(private_home / "home-write").write_text("home-ok")
# Pytest logging opens /dev/null; the fence must keep that sink writable.
with open("/dev/null", "w", encoding="utf-8") as sink:
    sink.write("dev-null-ok")
child = subprocess.run(
    [
        sys.executable,
        "-I",
        "-c",
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text('child-tamper')",
        str(root / "state" / "receipt.json"),
    ],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
print(json.dumps({{
    "root": str(root),
    "home": str(private_home),
    "xdg_state": os.environ["XDG_STATE_HOME"],
    "denied": failures,
    "child_returncode": child.returncode,
    "home_write": (private_home / "home-write").read_text(),
}}, sort_keys=True))
"""
    command = f"python -c {shlex.quote(probe)}"
    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=command, raw_command=command),
        workspace_path=workspace,
        timeout_seconds=30,
        environment=validation_environment_for_runner(
            environment,
            TodoImplementationDaemon._validation_command_runner,
        ),
    )

    assert result["returncode"] == 0, result["output"]
    observed = json.loads(str(result["output"]))
    assert observed["root"] == str(state_root.resolve())
    assert Path(observed["home"]) != hostile_home
    assert Path(observed["xdg_state"]) == (
        Path(observed["home"]) / ".local" / "state"
    )
    assert observed["denied"] == ["denied"] * 5
    assert observed["child_returncode"] != 0
    assert observed["home_write"] == "home-ok"
    assert not Path(observed["home"]).exists()
    assert (workspace / "workspace-write").read_text() == "workspace-ok"
    assert workspace_multilink.read_text() == "workspace-link-ok"
    assert control_receipt.read_text() == "sealed-receipt"
    assert not (merge_queue / "forged.json").exists()
    assert control_lock.read_text() == "locked"
    assert historical_receipt.read_text() == "historical-receipt"
    boundary = result["validation_filesystem_boundary"]
    assert boundary["schema"] == VALIDATION_FILESYSTEM_BOUNDARY_SCHEMA
    assert boundary["mode"] == "landlock-read-only-host-v2"
    assert boundary["landlock_abi"] >= 3
    assert boundary["python_site_policy"] == "default"
    assert boundary["applied"] is True
    assert boundary["proof_reuse_control_state_read_only"] is True
    assert boundary["proof_reuse_state_write_exception"] == (
        "exact-workspace-private-home-and-std-devices"
    )
    assert boundary["protected_hardlink_aliases_checked"] is True
    assert boundary["standard_device_nodes_writable"] is True
    assert boundary["proof_authoritative"] is False
    assert boundary["completion_authority"] is False

    cache_key = build_validation_cache_key(
        target_commit="commit-a",
        command="pytest tests/test_alpha.py",
        environment=environment,
        dependency_state={"lock": "one"},
        relevant_environment_keys=environment,
    )
    alternate_cache_key = build_validation_cache_key(
        target_commit="commit-a",
        command="pytest tests/test_alpha.py",
        environment=alternate_environment,
        dependency_state={"lock": "one"},
        relevant_environment_keys=alternate_environment,
    )
    assert cache_key.digest != alternate_cache_key.digest

    runtime = build_hermetic_validation_runtime(
        command="pytest tests/test_alpha.py",
        workspace_path=workspace,
        repository_tree_id="tree-a",
        environment=environment,
        timeout_seconds=30,
        cancellation_id="cancel-a",
        isolation_executable="/bin/true",
    )
    alternate_runtime = build_hermetic_validation_runtime(
        command="pytest tests/test_alpha.py",
        workspace_path=workspace,
        repository_tree_id="tree-a",
        environment=alternate_environment,
        timeout_seconds=30,
        cancellation_id="cancel-a",
        isolation_executable="/bin/true",
    )
    assert dict(runtime.environment)[PROOF_REUSE_STATE_ROOT_ENV] == str(
        state_root.resolve()
    )
    assert runtime.runtime_id != alternate_runtime.runtime_id


def test_proof_reuse_state_root_capability_rejects_invalid_directories(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValidationRuntimeError,
        match="must be an absolute directory",
    ):
        build_validation_environment(
            {PROOF_REUSE_STATE_ROOT_ENV: "relative/state-root"}
        )
    with pytest.raises(ValidationRuntimeError, match="is unavailable"):
        build_validation_environment(
            {PROOF_REUSE_STATE_ROOT_ENV: str(tmp_path / "missing-state-root")}
        )


def test_proof_reuse_state_root_cannot_be_inside_writable_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    state_root = workspace / "state-root"
    state_root.mkdir(parents=True)
    marker = workspace / "command-ran"
    command = f"python -c {shlex.quote(f'from pathlib import Path; Path({str(marker)!r}).touch()')}"
    environment = validation_environment_for_runner(
        build_validation_environment(
            {PROOF_REUSE_STATE_ROOT_ENV: str(state_root)}
        ),
        TodoImplementationDaemon._validation_command_runner,
    )

    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=command, raw_command=command),
        workspace_path=workspace,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == (
        "validation_environment_proof_state_boundary_unavailable"
    )
    assert not marker.exists()


def test_proof_reuse_state_root_rejects_workspace_hardlink_to_receipt(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "proof-backed-test-reuse-v9"
    workspace = state_root / "worktrees" / "candidate"
    receipt = state_root / "state" / "receipt.json"
    workspace.mkdir(parents=True)
    receipt.parent.mkdir()
    receipt.write_text("sealed-receipt", encoding="utf-8")
    os.link(receipt, workspace / "receipt-alias.json")
    marker = workspace / "command-ran"
    command = f"python -c {shlex.quote(f'from pathlib import Path; Path({str(marker)!r}).touch()')}"
    environment = validation_environment_for_runner(
        build_validation_environment(
            {PROOF_REUSE_STATE_ROOT_ENV: str(state_root)}
        ),
        TodoImplementationDaemon._validation_command_runner,
    )

    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=command, raw_command=command),
        workspace_path=workspace,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == (
        "validation_environment_proof_state_boundary_unavailable"
    )
    assert "hardlink" not in str(result["output"]).lower()
    assert receipt.read_text() == "sealed-receipt"
    assert not marker.exists()


def test_real_validation_runner_ignores_profile_bash_env_and_path_injection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    profile_marker = tmp_path / "profile-loaded"
    bash_env_marker = tmp_path / "bash-env-loaded"
    path_marker = tmp_path / "path-shadow-ran"
    (home / ".bash_profile").write_text(
        f"touch {shlex.quote(str(profile_marker))}\n",
        encoding="utf-8",
    )
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        f"touch {shlex.quote(str(bash_env_marker))}\n",
        encoding="utf-8",
    )
    shadow_python = hostile_bin / "python"
    shadow_python.write_text(
        f"#!/bin/sh\ntouch {shlex.quote(str(path_marker))}\nexit 97\n",
        encoding="utf-8",
    )
    shadow_python.chmod(0o755)
    trusted_path = os.pathsep.join(("/usr/bin", "/bin"))
    hostile_environment = {
        "BASH_ENV": str(bash_env),
        "ENV": str(bash_env),
        "HOME": str(home),
        "PATH": str(hostile_bin),
        "VALIDATION_SECRET": "must-not-leak",
        VALIDATION_PATH_ENV: trusted_path,
    }
    command = (
        f"test ! -e {shlex.quote(str(profile_marker))} "
        f"&& test ! -e {shlex.quote(str(bash_env_marker))} "
        '&& test -z "${VALIDATION_SECRET-}" '
        '&& test "$HOME" = /nonexistent/ipfs-accelerate-validation '
        '&& test "$XDG_CONFIG_HOME" = "$HOME" '
        "&& python -c 'raise SystemExit(0)'"
    )

    report = ValidationScheduler().run(
        [command],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="test-commit",
        dependency_state="test-dependencies",
        environment=hostile_environment,
    )

    assert report["passed"] is True
    assert not profile_marker.exists()
    assert not bash_env_marker.exists()
    assert not path_marker.exists()
    expected_environment = build_validation_environment(hostile_environment)
    expected_key = build_validation_cache_key(
        target_commit="test-commit",
        command=build_validation_commands([command])[0],
        environment=expected_environment,
        dependency_state="test-dependencies",
        relevant_environment_keys=expected_environment,
    )
    assert report["results"][0]["cache_key"] == expected_key.digest


def test_validation_runtime_reuses_supervisor_python_and_installed_pytest(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected_python = str(Path(sys.executable).resolve())
    command = (
        "TASK_PREFIX=works python -c 'import os, sys; "
        'assert os.environ["TASK_PREFIX"] == "works"; print(sys.executable)\' '
        "&& python -m pytest --version "
        "&& pytest --version"
    )

    report = ValidationScheduler().run(
        [command],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="test-commit",
        dependency_state="test-dependencies",
    )

    assert report["passed"] is True
    output = str(report["results"][0]["output"])
    assert output.splitlines()[0] == expected_python
    assert output.count("pytest ") == 2
    environment = build_validation_environment()
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert str(Path(pytest.__file__).parent.parent.resolve()) in environment.get(
        "PYTHONPATH", ""
    ).split(os.pathsep)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd launchers are Linux-specific",
)
def test_validation_runtime_seals_nested_python_launcher_and_cleans_descriptor() -> None:
    import fcntl

    environment = _sealed_daemon_environment()
    launcher_path = ""
    ruff_path = ""

    with validation_python_launcher_environment(environment) as (
        child_environment,
        receipt,
    ):
        launcher_path = child_environment["PYTHON"]
        ruff_path = child_environment.get(VALIDATION_RUFF_EXECUTABLE_ENV, "")
        payload = Path(launcher_path).read_bytes()
        descriptor = os.open(launcher_path, os.O_RDONLY)
        try:
            required_seals = (
                fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
            )
            assert fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) & required_seals == required_seals
        finally:
            os.close(descriptor)
        assert receipt.sealed is True
        assert receipt.inherited_fds
        assert int(Path(launcher_path).name) in receipt.inherited_fds
        assert receipt.executable == launcher_path
        assert receipt.content_sha256 == hashlib.sha256(payload).hexdigest()
        assert (
            receipt.interpreter_sha256
            == child_environment[VALIDATION_PYTHON_INTERPRETER_SHA256_ENV]
        )
        assert receipt.interpreter_stat == child_environment[VALIDATION_PYTHON_INTERPRETER_STAT_ENV]
        assert receipt.mode == child_environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV]
        assert (
            receipt.policy_sha256 == child_environment[VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV]
        )
        assert child_environment[VALIDATION_PYTHON_LAUNCHER_SHA256_ENV] == receipt.content_sha256
        assert child_environment["PYTHONNOUSERSITE"] == "1"
        assert not {
            VALIDATION_RUFF_EXECUTABLE_MODE_ENV,
            VALIDATION_RUFF_EXECUTABLE_SHA256_ENV,
            VALIDATION_RUFF_EXECUTABLE_STAT_ENV,
        } & set(child_environment)
        if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] == "sealed-memfd":
            assert ruff_path.startswith("/proc/self/fd/")
            assert int(Path(ruff_path).name) in receipt.inherited_fds
            assert Path(ruff_path).is_file()
            assert hashlib.sha256(Path(ruff_path).read_bytes()).hexdigest() == (
                environment[VALIDATION_RUFF_EXECUTABLE_SHA256_ENV]
            )

    assert launcher_path
    assert not Path(launcher_path).exists()
    if ruff_path:
        assert not Path(ruff_path).exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd launchers are Linux-specific",
)
def test_daemon_raw_no_site_profile_preserves_approved_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VALIDATION_PYTHON_PROFILE_ENV, "raw-no-site")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "ipfs_datasets_py").mkdir()
    daemon = object.__new__(TodoImplementationDaemon)
    daemon.worktree_submodule_paths = ("ipfs_datasets_py",)
    command = (
        "python -c 'import json,os,sys; "
        'print(json.dumps({"no_site":sys.flags.no_site,'
        '"no_user_site":sys.flags.no_user_site,'
        '"site_loaded":"site" in sys.modules,'
        '"sitecustomize_loaded":"sitecustomize" in sys.modules,'
        '"pythonpath":os.environ.get("PYTHONPATH", ""),'
        '"sys_path":sys.path}))\''
    )
    normalized, note = daemon._with_worktree_validation_pythonpath(
        command,
        workspace,
    )
    assert normalized == command
    assert note == "preserved raw no-site validation PYTHONPATH"

    environment = validation_environment_for_runner(
        build_validation_environment(),
        TodoImplementationDaemon._validation_command_runner,
    )
    default_environment = validation_environment_for_runner(
        build_validation_environment({}),
        TodoImplementationDaemon._validation_command_runner,
    )
    assert environment[VALIDATION_PYTHON_PROFILE_ENV] == "raw-no-site"
    assert ":site-policy=no-site:" in environment[
        VALIDATION_PYTHON_LAUNCHER_MODE_ENV
    ]
    assert environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV].endswith(
        ":sealed-memfd"
    )
    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=normalized, raw_command=command),
        workspace_path=workspace,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 0, result["output"]
    observed = json.loads(str(result["output"]))
    assert observed["no_site"] == 1
    assert observed["no_user_site"] == 1
    assert observed["site_loaded"] is False
    assert observed["sitecustomize_loaded"] is False
    assert observed["pythonpath"] == environment["PYTHONPATH"]
    approved_roots = environment["PYTHONPATH"].split(os.pathsep)
    assert observed["sys_path"][1 : 1 + len(approved_roots)] == approved_roots
    assert ":site-policy=no-site:" in result[
        "validation_python_launcher"
    ]["mode"]
    assert result["validation_python_launcher"]["mode"].endswith(
        ":sealed-memfd"
    )
    assert build_validation_cache_key(
        target_commit="candidate",
        command=command,
        environment=environment,
    ).digest != build_validation_cache_key(
        target_commit="candidate",
        command=command,
        environment=default_environment,
    ).digest
    assert validation_argv_command(
        ("python", "-c", "raise SystemExit(0)"),
        environment={VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"},
    )[1] == "-S"
    contract = canonical_validation_environment_contract(
        {VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"}
    )
    assert contract["schema"].endswith("@2")
    assert contract["python_profile"] == "raw-no-site"
    assert contract["python_site_initialization"] == "disabled"
    assert contract["python_user_site_disabled"] is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd launchers are Linux-specific",
)
def test_raw_no_site_profile_rejects_command_pythonpath_and_binds_ruff_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VALIDATION_PYTHON_PROFILE_ENV, "raw-no-site")
    environment = validation_environment_for_runner(
        build_validation_environment(),
        TodoImplementationDaemon._validation_command_runner,
    )
    replaced = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(
            command="PYTHONPATH=. python -c 'raise SystemExit(0)'",
            raw_command="PYTHONPATH=. python -c 'raise SystemExit(0)'",
        ),
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment=environment,
    )
    assert replaced["returncode"] == 75
    assert "unapproved-pythonpath" in str(replaced["output"])

    with validation_python_launcher_environment(environment) as (
        child_environment,
        _receipt,
    ):
        launcher_source = Path(child_environment["PYTHON"]).read_text(
            encoding="utf-8"
        )
    assert 'exec "$executable" -I -S -c "$ruff_broker"' in launcher_source

    boundary_root = tmp_path / "boundary"
    state_root = boundary_root / "proof-state"
    boundary_workspace = boundary_root / "workspace"
    private_home = boundary_root / "private-home"
    state_root.mkdir(parents=True)
    boundary_workspace.mkdir()
    private_home.mkdir()
    landlock_command, landlock_receipt = validation_readonly_state_command(
        ("/bin/true",),
        workspace_path=boundary_workspace,
        private_home_path=private_home,
        environment={
            **environment,
            PROOF_REUSE_STATE_ROOT_ENV: str(state_root),
        },
    )
    assert landlock_command[1:4] == ["-I", "-S", "-c"]
    assert landlock_receipt is not None
    assert landlock_receipt.python_site_policy == "raw-no-site"
    assert landlock_receipt.to_dict()["schema"].endswith("@2")


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd launchers are Linux-specific",
)
def test_raw_no_site_seals_canonical_and_rejects_unsealed_python_spellings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VALIDATION_PYTHON_PROFILE_ENV, "raw-no-site")
    environment = validation_environment_for_runner(
        build_validation_environment(),
        TodoImplementationDaemon._validation_command_runner,
    )
    canonical_name = Path(validation_python_executable(environment)).name
    assert canonical_name.startswith("python3.")
    safe_command = (
        f"{canonical_name} -c 'import json,sys; "
        'print(json.dumps({"no_site":sys.flags.no_site,'
        '"site_loaded":"site" in sys.modules,'
        '"sitecustomize_loaded":"sitecustomize" in sys.modules}))\''
    )
    safe_result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(
            command=safe_command,
            raw_command=safe_command,
        ),
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment=environment,
    )
    assert safe_result["returncode"] == 0, safe_result["output"]
    safe_observed = json.loads(str(safe_result["output"]))
    assert safe_observed == {
        "no_site": 1,
        "site_loaded": False,
        "sitecustomize_loaded": False,
    }
    assert safe_result["validation_python_launcher"]["mode"].endswith(
        ":sealed-memfd"
    )

    other_version = "python3.11" if canonical_name != "python3.11" else "python3.10"
    shell_commands = (
        f"{other_version} -c 'raise SystemExit(0)'",
        f"/usr/bin/{canonical_name} -c 'raise SystemExit(0)'",
        f"/usr/bin/env {canonical_name} -c 'raise SystemExit(0)'",
        f"/usr/bin/env -S '{canonical_name} -c \"raise SystemExit(0)\"'",
        f"/usr/bin/env -S{canonical_name} -c 'raise SystemExit(0)'",
        "command pytest --version",
        "/usr/bin/env pytest --version",
        "/usr/bin/env --split-string='pytest --version'",
        "/usr/bin/pytest --version",
        "py.test --version",
    )
    for command in shell_commands:
        result = TodoImplementationDaemon._validation_command_runner(
            spec=SimpleNamespace(command=command, raw_command=command),
            workspace_path=tmp_path,
            timeout_seconds=30,
            environment=environment,
        )
        assert result["returncode"] == 78
        assert result["reason"] == "validation_shell_command_policy_violation"

    argv_commands = (
        (other_version, "-c", "raise SystemExit(0)"),
        (f"/usr/bin/{canonical_name}", "-c", "raise SystemExit(0)"),
        ("/usr/bin/env", canonical_name, "-c", "raise SystemExit(0)"),
        (
            "/usr/bin/env",
            "-S",
            f"{canonical_name} -c 'raise SystemExit(0)'",
        ),
        (
            "/usr/bin/env",
            f"-S{canonical_name} -c 'raise SystemExit(0)'",
        ),
        ("/usr/bin/pytest", "--version"),
        ("py.test", "--version"),
        ("/usr/bin/env", "pytest", "--version"),
        ("/usr/bin/env", "-S", "pytest --version"),
    )
    for command in argv_commands:
        with pytest.raises(
            ValidationRuntimeError,
            match=(
                "direct argv Python|wrapped direct argv Python|"
                "direct argv pytest|wrapped direct argv pytest"
            ),
        ):
            validation_argv_command(command, environment=environment)
    assert validation_argv_command(
        (canonical_name, "-c", "raise SystemExit(0)"),
        environment=environment,
    )[1] == "-S"
    assert validation_argv_command(
        ("pytest", "--version"),
        environment=environment,
    )[1:4] == ["-S", "-m", "pytest"]


def test_raw_no_site_authority_validation_rejects_docker_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        TodoImplementationDaemon,
        "_authority_validation_isolation_contract",
        staticmethod(lambda: {"available": True, "contract_id": "test"}),
    )
    monkeypatch.setattr(
        TodoImplementationDaemon,
        "_unix_stream_socket_permitted",
        staticmethod(lambda: True),
    )
    result = TodoImplementationDaemon._authority_validation_command_runner(
        spec=SimpleNamespace(command="true", raw_command="true"),
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment={VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"},
    )
    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["reason"] == (
        "raw_no_site_authority_validation_requires_host_sealed_runner"
    )


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="non-dumpable state-authority isolation is Linux-specific",
)
def test_validation_runner_uses_only_inherited_sealed_fds_when_parent_is_non_dumpable() -> None:
    script = """
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ["IPFS_ACCELERATE_AGENT_QUACK_TOKEN"] = "regression-fixture"

from ipfs_accelerate_py.agent_supervisor.runtime.process_security import (
    harden_state_authority_process,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    TodoImplementationDaemon,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_runtime import (
    build_validation_environment,
    validation_environment_for_runner,
)

assert harden_state_authority_process() is True
runner = TodoImplementationDaemon._validation_command_runner
environment = validation_environment_for_runner(
    build_validation_environment(),
    runner,
)
with tempfile.TemporaryDirectory() as temporary_directory:
    result = runner(
        spec=SimpleNamespace(
            command=(
                "test -z \\\"${IPFS_ACCELERATE_AGENT_QUACK_TOKEN-}\\\" "
                "&& python -c 'print(42)'"
            ),
            raw_command="non-dumpable-validation-regression",
        ),
        workspace_path=Path(temporary_directory),
        timeout_seconds=30,
        environment=environment,
    )
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result.get("returncode") == 0 else 1)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["returncode"] == 0
    assert result["output"] == "42\n"
    assert result["validation_python_launcher"]["sealed"] is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables are Linux-specific",
)
@pytest.mark.parametrize(
    "command",
    (
        "python -m ruff --version",
        "python3 -m ruff --version",
        "python3 -mruff --version",
        "python3 -Bm ruff --version",
        "PYTHONPATH=. python3 -m ruff --version",
    ),
)
def test_daemon_routes_reviewed_python_m_ruff_spellings_to_sealed_binary(
    tmp_path: Path,
    command: str,
) -> None:
    environment = _sealed_daemon_environment()
    if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] != "sealed-memfd":
        pytest.skip("Ruff is not installed in the approved validation runtime")
    spec = SimpleNamespace(
        command=command,
        raw_command=command,
    )

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 0, result["output"]
    assert str(result["output"]).startswith("ruff ")
    assert result["validation_python_launcher"]["sealed"] is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables are Linux-specific",
)
def test_daemon_rejects_noncanonical_combined_python_ruff_option(
    tmp_path: Path,
) -> None:
    environment = _sealed_daemon_environment()
    if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] != "sealed-memfd":
        pytest.skip("Ruff is not installed in the approved validation runtime")
    command = "python3 -Bmruff --version"

    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=command, raw_command=command),
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 75
    assert "unsupported-module-spelling" in str(result["output"])
    assert result["validation_python_launcher"]["sealed"] is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables are Linux-specific",
)
def test_validation_runtime_rejects_tampered_ruff_identity() -> None:
    environment = _sealed_daemon_environment()
    if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] != "sealed-memfd":
        pytest.skip("Ruff is not installed in the approved validation runtime")
    environment[VALIDATION_RUFF_EXECUTABLE_SHA256_ENV] = "0" * 64

    with pytest.raises(
        ValidationRuntimeError,
        match="validation Ruff executable identity mismatch",
    ), validation_python_launcher_environment(environment):
        pytest.fail("tampered Ruff identity must fail before yielding")


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables are Linux-specific",
)
def test_nested_child_cannot_replace_sealed_ruff_through_environment(
    tmp_path: Path,
) -> None:
    environment = _sealed_daemon_environment()
    if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] != "sealed-memfd":
        pytest.skip("Ruff is not installed in the approved validation runtime")
    (tmp_path / "adversarial_ruff.py").write_text(
        f"""
import os
import subprocess

sealed_python = os.environ["PYTHON"]
environment = dict(os.environ)
environment[{VALIDATION_RUFF_EXECUTABLE_ENV!r}] = "/bin/true"
environment[{VALIDATION_RUFF_EXECUTABLE_MODE_ENV!r}] = "sealed-memfd"
environment[{VALIDATION_RUFF_EXECUTABLE_SHA256_ENV!r}] = "0" * 64
environment[{VALIDATION_RUFF_EXECUTABLE_STAT_ENV!r}] = "forged"
completed = subprocess.run(
    [sealed_python, "-m", "ruff", "check", "missing.py"],
    env=environment,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    check=False,
)
print(f"sealed-ruff-returncode={{completed.returncode}}")
print(completed.stdout, end="")
raise SystemExit(0 if completed.returncode != 0 else 42)
""".lstrip(),
        encoding="utf-8",
    )
    spec = SimpleNamespace(
        command="python adversarial_ruff.py",
        raw_command="python adversarial_ruff.py",
    )

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 0, result["output"]
    assert "sealed-ruff-returncode=1" in str(result["output"])
    assert "missing.py" in str(result["output"])


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables and Landlock are Linux-specific",
)
def test_sealed_ruff_survives_proof_state_landlock_fence(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "proof-state"
    state_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "bad.py").write_text("import os\n", encoding="utf-8")
    environment = validation_environment_for_runner(
        build_validation_environment(
            {PROOF_REUSE_STATE_ROOT_ENV: str(state_root)}
        ),
        TodoImplementationDaemon._validation_command_runner,
    )
    if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] != "sealed-memfd":
        pytest.skip("Ruff is not installed in the approved validation runtime")
    command = "python3 -m ruff check bad.py"

    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=command, raw_command=command),
        workspace_path=workspace,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 1, result["output"]
    assert "F401" in str(result["output"])
    assert result["validation_filesystem_boundary"]["applied"] is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables and Landlock are Linux-specific",
)
def test_nested_sealed_ruff_survives_proof_state_landlock_fence(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "proof-state"
    state_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment = validation_environment_for_runner(
        build_validation_environment(
            {PROOF_REUSE_STATE_ROOT_ENV: str(state_root)}
        ),
        TodoImplementationDaemon._validation_command_runner,
    )
    if environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] != "sealed-memfd":
        pytest.skip("Ruff is not installed in the approved validation runtime")
    probe = """
import os
import subprocess

completed = subprocess.run(
    [os.environ["PYTHON"], "-m", "ruff", "--version"],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)
print(completed.stdout, end="")
raise SystemExit(completed.returncode)
""".lstrip()
    command = f"python3 -c {shlex.quote(probe)}"

    result = TodoImplementationDaemon._validation_command_runner(
        spec=SimpleNamespace(command=command, raw_command=command),
        workspace_path=workspace,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 0, result["output"]
    assert str(result["output"]).startswith("ruff ")
    assert result["validation_filesystem_boundary"]["applied"] is True


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd executables are Linux-specific",
)
def test_missing_ruff_is_typed_as_infrastructure_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        (
            "ipfs_accelerate_py.agent_supervisor.validation."
            "validation_runtime._active_ruff_executable_snapshot"
        ),
        lambda **_kwargs: None,
    )
    environment = _sealed_daemon_environment()
    assert environment[VALIDATION_RUFF_EXECUTABLE_MODE_ENV] == "unavailable"
    spec = SimpleNamespace(
        command="python3 -m ruff --version",
        raw_command="python3 -m ruff --version",
    )

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=tmp_path,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == (
        "validation_environment_ruff_executable_unavailable"
    )
    assert result["reason"] == "sealed_validation_ruff_executable_unavailable"


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sealed memfd launchers are Linux-specific",
)
def test_daemon_nested_python_keeps_approved_packages_after_pythonpath_replace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "fixture_value.py").write_text(
        "VALUE = 'workspace-import'\n",
        encoding="utf-8",
    )
    (workspace / "hostile-bash-env").write_text(
        "touch bash-env-executed\nexit 42\n",
        encoding="utf-8",
    )
    (workspace / "nested_launcher.py").write_text(
        """
import os
import pathlib
import subprocess

environment = dict(os.environ)
environment["PYTHONPATH"] = str(pathlib.Path.cwd())
environment["PYTHONNOUSERSITE"] = "0"
environment["BASH_ENV"] = str(pathlib.Path.cwd() / "hostile-bash-env")
pathlib.Path("launcher-path.txt").write_text(
    environment["PYTHON"],
    encoding="utf-8",
)
completed = subprocess.run(
    [
        environment["PYTHON"],
        "-c",
        (
            "import os, site, fixture_value, pytest; "
            "assert os.environ['PYTHONNOUSERSITE'] == '1'; "
            "assert site.ENABLE_USER_SITE is False; "
            "assert fixture_value.VALUE == 'workspace-import'; "
            "print(pytest.__version__)"
        ),
    ],
    env=environment,
    text=True,
    capture_output=True,
    check=False,
)
site_probe = subprocess.run(
    [
        environment["PYTHON"],
        "-E",
        "-c",
        (
            "import site; "
            "assert site.ENABLE_USER_SITE is False"
        ),
    ],
    env=environment,
    text=True,
    capture_output=True,
    check=False,
)
print(completed.stdout, end="")
print(completed.stderr, end="")
print(site_probe.stdout, end="")
print(site_probe.stderr, end="")
raise SystemExit(completed.returncode or site_probe.returncode)
""".lstrip(),
        encoding="utf-8",
    )
    spec = SimpleNamespace(
        command="python nested_launcher.py",
        raw_command="python nested_launcher.py",
    )

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=workspace,
        timeout_seconds=30,
        environment=_sealed_daemon_environment(),
    )

    assert result["returncode"] == 0, result["output"]
    assert pytest.__version__ in str(result["output"])
    assert not (workspace / "bash-env-executed").exists()
    launcher_receipt = result["validation_python_launcher"]
    assert launcher_receipt["sealed"] is True
    environment = _sealed_daemon_environment()
    assert launcher_receipt["content_sha256"] == environment[VALIDATION_PYTHON_LAUNCHER_SHA256_ENV]
    assert launcher_receipt["mode"] == environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV]
    assert (
        launcher_receipt["policy_sha256"]
        == environment[VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV]
    )
    assert (
        launcher_receipt["interpreter_sha256"]
        == environment[VALIDATION_PYTHON_INTERPRETER_SHA256_ENV]
    )
    assert (
        launcher_receipt["interpreter_stat"] == environment[VALIDATION_PYTHON_INTERPRETER_STAT_ENV]
    )
    launcher_path = (workspace / "launcher-path.txt").read_text(encoding="utf-8")
    assert launcher_path.startswith("/proc/")
    assert "/fd/" in launcher_path
    assert not Path(launcher_path).exists()


def test_daemon_classifies_python_launcher_failure_as_infrastructure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class FailedLauncher:
        def __enter__(self):
            raise ValidationRuntimeError("kernel sealing unavailable")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        (
            "ipfs_accelerate_py.agent_supervisor.todo_daemon."
            "implementation_daemon.validation_python_launcher_environment"
        ),
        lambda _environment: FailedLauncher(),
    )
    spec = SimpleNamespace(command="true", raw_command="true")

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=workspace,
        timeout_seconds=30,
        environment=_sealed_daemon_environment(),
    )

    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == "validation_environment_python_launcher_unavailable"
    assert result["reason"] == "sealed_validation_python_launcher_unavailable"
    assert "kernel sealing unavailable" in str(result["output"])


def test_daemon_classifies_child_launcher_exec_denial_as_infrastructure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment = _sealed_daemon_environment()

    def denied_run(*_args: object, **_kwargs: object):
        raise PermissionError("procfd execution denied")

    monkeypatch.setattr(
        ("ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon.subprocess.run"),
        denied_run,
    )
    spec = SimpleNamespace(command="true", raw_command="true")

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=workspace,
        timeout_seconds=30,
        environment=environment,
    )

    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == "validation_environment_python_launcher_exec_unavailable"
    assert result["reason"] == "sealed_validation_python_launcher_child_probe_failed"
    assert "procfd execution denied" in str(result["output"])
    receipt = result["validation_python_launcher"]
    assert receipt["content_sha256"] == environment[VALIDATION_PYTHON_LAUNCHER_SHA256_ENV]
    assert receipt["interpreter_sha256"] == environment[VALIDATION_PYTHON_INTERPRETER_SHA256_ENV]
    assert receipt["interpreter_stat"] == environment[VALIDATION_PYTHON_INTERPRETER_STAT_ENV]
    assert receipt["mode"] == environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV]
    assert receipt["policy_sha256"] == environment[VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV]


@pytest.mark.parametrize(
    "command",
    ("bash -c 'true'", "eval true"),
)
def test_daemon_classifies_invalid_shell_command_as_policy_rejection(
    tmp_path: Path,
    command: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = SimpleNamespace(command=command, raw_command=command)

    result = TodoImplementationDaemon._validation_command_runner(
        spec=spec,
        workspace_path=workspace,
        timeout_seconds=30,
        environment=_sealed_daemon_environment(),
    )

    assert result["returncode"] == 78
    assert result["error"] == "validation_command_policy_rejected"
    assert result["reason"] == "validation_shell_command_policy_violation"
    assert result["infrastructure_failure"] is False
    assert "validation_python_launcher" not in result


def test_validation_runtime_extends_task_local_pythonpath_with_approved_packages(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "fixture_value.py").write_text(
        "VALUE = 'workspace-import'\n",
        encoding="utf-8",
    )
    command = (
        "PYTHONPATH=. python -c 'import fixture_value, pytest; "
        'assert fixture_value.VALUE == "workspace-import"; '
        "print(pytest.__version__)' "
        "&& PYTHONPATH=. pytest --version"
    )

    report = ValidationScheduler().run(
        [command],
        workspace_path=workspace,
        changed_files=["fixture_value.py"],
        target_commit="test-commit",
        dependency_state="test-dependencies",
    )

    assert report["passed"] is True
    output = str(report["results"][0]["output"])
    assert pytest.__version__ in output
    assert "pytest " in output


def test_validation_runtime_canonicalizes_replaceable_python_launcher(
    tmp_path: Path,
) -> None:
    interpreter = tmp_path / "replaceable-python"
    interpreter.symlink_to(Path(sys.executable).resolve())
    environment = {
        VALIDATION_PATH_ENV: os.pathsep.join(("/usr/bin", "/bin")),
        VALIDATION_PYTHON_ENV: str(interpreter),
    }

    report = ValidationScheduler().run(
        ["python -c 'import sys; print(sys.executable)'"],
        workspace_path=tmp_path,
        changed_files=["pyproject.toml"],
        target_commit="test-commit",
        dependency_state="test-dependencies",
        environment=environment,
    )

    assert report["passed"] is True
    assert str(report["results"][0]["output"]).strip() == str(Path(sys.executable).resolve())
    child_environment = build_validation_environment(environment)
    assert child_environment["IPFS_ACCELERATE_VALIDATION_PYTHON_EXECUTABLE"] == str(
        Path(sys.executable).resolve()
    )
    assert "PYTHONPATH" not in child_environment
    assert child_environment["PYTHONNOUSERSITE"] == "1"
    assert validation_python_executable(environment) != str(interpreter)


def test_validation_runtime_does_not_reinject_inherited_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = tmp_path / "hostile" / "site-packages"
    hostile.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", [str(hostile), *sys.path])

    environment = build_validation_environment()

    assert str(hostile.resolve()) not in environment.get("PYTHONPATH", "").split(os.pathsep)
    with pytest.raises(ValidationRuntimeError, match="must not be writable"):
        build_validation_environment({VALIDATION_PYTHONPATH_ENV: str(hostile)})


def test_legacy_argv_validation_normalizes_login_shell_and_scrubs_bash_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "bash-env-ran"
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        f"touch {shlex.quote(str(marker))}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BASH_ENV", str(bash_env))

    results = run_validation_commands(
        repo_root=tmp_path,
        commands=(
            (
                "/bin/bash",
                "-lc",
                "python -c 'import sys; print(sys.executable)'",
            ),
        ),
        timeout_seconds=10,
    )

    assert results[0].ok
    assert results[0].command[:4] == (
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
    )
    assert results[0].stdout.strip() == str(Path(sys.executable).resolve())
    assert not marker.exists()


def test_raw_no_site_legacy_shell_argv_uses_immutable_profile_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(VALIDATION_PYTHON_PROFILE_ENV, "raw-no-site")
    probe = (
        "import json,sys;print(json.dumps({"
        "'no_site':sys.flags.no_site,"
        "'site_loaded':'site' in sys.modules,"
        "'sitecustomize_loaded':'sitecustomize' in sys.modules}))"
    )
    commands = (
        (
            "/bin/bash",
            "-lc",
            f"{VALIDATION_PYTHON_PROFILE_ENV}=default "
            f"python -c {shlex.quote(probe)}",
        ),
        (
            "/bin/bash",
            "-lc",
            f"unset {VALIDATION_PYTHON_PROFILE_ENV}; "
            f"python -c {shlex.quote(probe)}",
        ),
    )

    results = run_validation_commands(
        repo_root=tmp_path,
        commands=commands,
        timeout_seconds=10,
    )

    assert [result.returncode for result in results] == [0, 0]
    assert [json.loads(result.stdout) for result in results] == [
        {
            "no_site": 1,
            "site_loaded": False,
            "sitecustomize_loaded": False,
        },
        {
            "no_site": 1,
            "site_loaded": False,
            "sitecustomize_loaded": False,
        },
    ]


def test_legacy_adapter_forwards_sanitized_validation_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "bash-env-ran"
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        f"touch {shlex.quote(str(marker))}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BASH_ENV", str(bash_env))
    monkeypatch.setenv("VALIDATION_SECRET", "must-not-leak")
    captured_environment: dict[str, str] = {}

    def legacy_runner(
        command,
        *,
        cwd,
        timeout,
        input_text=None,
        environment=None,
    ):
        assert environment is not None
        captured_environment.update({str(key): str(value) for key, value in environment.items()})
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=captured_environment,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": list(command),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    results = run_validation_commands(
        repo_root=tmp_path,
        commands=(("/bin/bash", "-lc", "python -c 'print(\"safe\")'"),),
        timeout_seconds=10,
        run_command_fn=command_runner_from_legacy_function(legacy_runner),
    )

    assert results[0].ok
    assert results[0].stdout.strip() == "safe"
    assert not marker.exists()
    assert "BASH_ENV" not in captured_environment
    assert "VALIDATION_SECRET" not in captured_environment


def test_legacy_adapter_rejects_runner_without_environment_contract() -> None:
    def unsafe_legacy_runner(command, *, cwd, timeout, input_text=None):
        return {
            "command": command,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }

    with pytest.raises(
        ValidationRuntimeError,
        match="must accept an environment keyword",
    ):
        command_runner_from_legacy_function(unsafe_legacy_runner)


def test_cheap_checks_run_before_expensive_tests_and_fail_fast(tmp_path: Path) -> None:
    calls: list[str] = []

    def runner(*, spec, **_kwargs):
        calls.append(spec.command)
        return _result(spec, returncode=7 if spec.stage == ValidationStage.CHEAP else 0)

    scheduler = ValidationScheduler(max_workers=2, resource_budget=2, runner=runner)
    report = scheduler.run(
        ["pytest tests/test_alpha.py", "git diff --check"],
        workspace_path=tmp_path,
        changed_files=["src/alpha.py"],
        target_commit="abc",
        dependency_state="deps",
    )

    assert calls == ["git diff --check"]
    assert report["passed"] is False
    assert report["returncode"] == 7
    assert report["failed_command"] == "git diff --check"
    assert [item["stage"] for item in report["stages"]] == ["cheap"]


def test_independent_validations_run_in_parallel_under_weighted_budget(tmp_path: Path) -> None:
    lock = threading.Lock()
    release = threading.Event()
    two_running = threading.Event()
    active = 0
    maximum_active = 0

    def runner(*, spec, **_kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                two_running.set()
        assert release.wait(timeout=5)
        with lock:
            active -= 1
        return _result(spec)

    scheduler = ValidationScheduler(max_workers=3, resource_budget=2, runner=runner)
    commands = [
        "pytest tests/test_alpha.py",
        "pytest tests/test_beta.py",
        "pytest tests/test_gamma.py",
    ]
    outcome: dict[str, object] = {}

    def schedule() -> None:
        outcome.update(
            scheduler.run(
                commands,
                workspace_path=tmp_path,
                changed_files=["pyproject.toml"],
                target_commit="abc",
                dependency_state="deps",
            )
        )

    thread = threading.Thread(target=schedule)
    thread.start()
    assert two_running.wait(timeout=5)
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert outcome["passed"] is True
    assert maximum_active == 2
    assert [item["command"] for item in outcome["results"]] == commands


def test_cache_and_result_digests_bind_python_launcher_policy() -> None:
    canonical_environment = build_validation_environment()
    environment = _sealed_daemon_environment()
    base_key = build_validation_cache_key(
        target_commit="commit-a",
        command="pytest tests/test_alpha.py",
        environment=environment,
        dependency_state={"lock": "one"},
    )
    canonical_key = build_validation_cache_key(
        target_commit="commit-a",
        command="pytest tests/test_alpha.py",
        environment=canonical_environment,
        dependency_state={"lock": "one"},
    )
    assert canonical_key.digest != base_key.digest

    for variable in (
        VALIDATION_PYTHON_INTERPRETER_SHA256_ENV,
        VALIDATION_PYTHON_INTERPRETER_STAT_ENV,
        VALIDATION_PYTHON_LAUNCHER_MODE_ENV,
        VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV,
        VALIDATION_PYTHON_LAUNCHER_SHA256_ENV,
        VALIDATION_RUFF_EXECUTABLE_MODE_ENV,
        VALIDATION_RUFF_EXECUTABLE_SHA256_ENV,
        VALIDATION_RUFF_EXECUTABLE_STAT_ENV,
    ):
        changed = dict(environment)
        changed[variable] = f"{changed.get(variable, '')}-changed"
        variant = build_validation_cache_key(
            target_commit="commit-a",
            command="pytest tests/test_alpha.py",
            environment=changed,
            dependency_state={"lock": "one"},
        )
        assert variant.digest != base_key.digest

    result = {
        "command": "pytest tests/test_alpha.py",
        "returncode": 0,
        "output": "passed",
        "validation_python_launcher": {
            "content_sha256": environment[VALIDATION_PYTHON_LAUNCHER_SHA256_ENV],
            "interpreter_sha256": environment[VALIDATION_PYTHON_INTERPRETER_SHA256_ENV],
            "interpreter_stat": environment[VALIDATION_PYTHON_INTERPRETER_STAT_ENV],
            "mode": environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV],
            "policy_sha256": environment[VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV],
            "sealed": True,
        },
    }
    base_result_digest = _validation_result_digest(
        result,
        cache_key=base_key,
    )
    changed_result = {
        **result,
        "validation_python_launcher": {
            **result["validation_python_launcher"],
            "sealed": False,
        },
    }
    assert _validation_result_digest(changed_result, cache_key=base_key) != base_result_digest


def test_validation_result_digest_binds_filesystem_boundary_receipts() -> None:
    boundary = {
        "schema": VALIDATION_FILESYSTEM_BOUNDARY_SCHEMA,
        "mode": "landlock-read-only-host-v2",
        "python_site_policy": "raw-no-site",
        "policy_sha256": "a" * 64,
        "applied": True,
    }
    result = {
        "command": "true",
        "returncode": 0,
        "output": "passed",
        "validation_filesystem_boundary": boundary,
        "attempts": [
            {
                "diagnostic_signature": "attempt-one",
                "validation_filesystem_boundary": boundary,
            }
        ],
    }
    base_digest = _validation_result_digest(result)
    top_level_tamper = {
        **result,
        "validation_filesystem_boundary": {
            **boundary,
            "python_site_policy": "default",
        },
    }
    attempt_tamper = {
        **result,
        "attempts": [
            {
                **result["attempts"][0],
                "validation_filesystem_boundary": {
                    **boundary,
                    "applied": False,
                },
            }
        ],
    }

    assert _validation_result_digest(top_level_tamper) != base_digest
    assert _validation_result_digest(attempt_tamper) != base_digest


def test_validation_cache_separates_canonical_and_sealed_runners(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cache_dir = tmp_path / "cache"
    calls: list[str] = []

    def canonical_runner(*, spec, **_kwargs):
        calls.append("canonical")
        return _result(spec)

    @sealed_validation_python_runner
    def sealed_runner(*, spec, environment, **_kwargs):
        calls.append("sealed")
        result = _result(spec)
        result["validation_python_launcher"] = {
            "content_sha256": environment[VALIDATION_PYTHON_LAUNCHER_SHA256_ENV],
            "interpreter_sha256": environment[VALIDATION_PYTHON_INTERPRETER_SHA256_ENV],
            "interpreter_stat": environment[VALIDATION_PYTHON_INTERPRETER_STAT_ENV],
            "mode": environment[VALIDATION_PYTHON_LAUNCHER_MODE_ENV],
            "policy_sha256": environment[VALIDATION_PYTHON_LAUNCHER_POLICY_SHA256_ENV],
            "sealed": True,
        }
        return result

    common = {
        "workspace_path": workspace,
        "changed_files": ["pyproject.toml"],
        "target_commit": "same-commit",
        "dependency_state": "same-dependencies",
    }
    canonical = ValidationScheduler(
        cache_dir=cache_dir,
        runner=canonical_runner,
    ).run(["true"], **common)
    sealed_environment = validation_environment_for_runner(
        build_validation_environment(),
        sealed_runner,
    )
    sealed_key = build_validation_cache_key(
        target_commit="same-commit",
        command="true",
        environment=sealed_environment,
        dependency_state="same-dependencies",
    )
    stale_without_receipt = {
        "command": "true",
        "raw_command": "true",
        "returncode": 0,
        "output": "stale",
    }
    assert ValidationResultCache(cache_dir).put(
        sealed_key,
        stale_without_receipt,
    )
    first_sealed = ValidationScheduler(
        cache_dir=cache_dir,
        runner=sealed_runner,
    ).run(["true"], **common)
    replayed_sealed = ValidationScheduler(
        cache_dir=cache_dir,
        runner=sealed_runner,
    ).run(["true"], **common)

    assert canonical["results"][0]["cache_hit"] is False
    assert first_sealed["results"][0]["cache_hit"] is False
    assert replayed_sealed["results"][0]["cache_hit"] is True
    assert canonical["results"][0]["cache_key"] != first_sealed["results"][0]["cache_key"]
    assert calls == ["canonical", "sealed"]


@pytest.mark.parametrize(
    "environment",
    [None, {VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"}],
    ids=("default-site-policy", "raw-no-site-policy"),
)
def test_fresh_sealed_runner_requires_exact_launcher_receipt(
    tmp_path: Path,
    environment: dict[str, str] | None,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    @sealed_validation_python_runner
    def missing_receipt_runner(*, spec, **_kwargs):
        return _result(spec)

    report = ValidationScheduler(runner=missing_receipt_runner).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
        environment=environment,
    )

    result = report["results"][0]
    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == "validation_environment_python_launcher_receipt_mismatch"
    assert result["outcome"] == "infrastructure_failure"
    assert result["classification"] == "infrastructure_failure"
    assert result["authoritative"] is False
    assert result["stable"] is False


def test_external_isolation_receipt_admits_passing_sealed_runner(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    @sealed_validation_python_runner
    def isolated_runner(*, spec, **_kwargs):
        result = _result(spec)
        result["external_validation_isolation_receipt"] = {
            "schema": (
                "ipfs_accelerate_py.agent_supervisor."
                "external-validation-isolation@1"
            ),
            "image_id": (
                "sha256:ca52183d6e3f6d472b36092fc07a76fde0b7962da92b84dad"
                "2dc1038d93009ad"
            ),
            "container_removed": True,
            "receipt_id": (
                "baguqeeraldrvzwtbpryckbinbq4avy2d4vhhirg5dngogbuo7w6lqjynobsq"
            ),
        }
        return result

    report = ValidationScheduler(runner=isolated_runner).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
    )

    result = report["results"][0]
    assert result["returncode"] == 0
    assert result.get("infrastructure_failure") is not True
    assert result.get("error") != (
        "validation_environment_python_launcher_receipt_mismatch"
    )


def test_incomplete_external_isolation_receipt_does_not_bypass_launcher_check(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    @sealed_validation_python_runner
    def incomplete_isolation_runner(*, spec, **_kwargs):
        result = _result(spec)
        result["external_validation_isolation_receipt"] = {
            "schema": (
                "ipfs_accelerate_py.agent_supervisor."
                "external-validation-isolation@1"
            ),
            "image_id": "sha256:incomplete",
            "container_removed": False,
            "receipt_id": "baguqeeraincomplete",
        }
        return result

    report = ValidationScheduler(runner=incomplete_isolation_runner).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
    )

    result = report["results"][0]
    assert result["returncode"] == 75
    assert result["infrastructure_failure"] is True
    assert result["error"] == "validation_environment_python_launcher_receipt_mismatch"


def test_hermetic_runtime_always_resanitizes_supplied_environment(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_hermetic_validation_runtime(
        command="true",
        workspace_path=workspace,
        repository_tree_id="tree:test",
        environment={
            "AWS_SECRET_ACCESS_KEY": "must-not-survive",
            "BASH_ENV": str(tmp_path / "hostile-startup-hook"),
        },
        timeout_seconds=30,
        cancellation_id="validation:test",
        isolation_executable="/bin/true",
    )

    environment = dict(runtime.environment)
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert "BASH_ENV" not in environment


def test_hermetic_scheduler_rejects_actual_daemon_runner_before_execution(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = ValidationScheduler(
        runner=TodoImplementationDaemon._validation_command_runner,
        hermetic_policy=HermeticValidationPolicy(),
    ).run(
        ['test -z "${IPFS_ACCELERATE_VALIDATION_RUNTIME_ID-}"'],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
    )

    assert report["passed"] is False
    result = report["results"][0]
    assert result["returncode"] == 75
    assert result["error"] == "hermetic_validation_runner_capability_missing"
    assert result["reason"] == ("hermetic_runner_does_not_consume_runtime_context")
    assert result["outcome"] == "infrastructure_failure"
    assert result["classification"] == "infrastructure_failure"
    assert result["authoritative"] is False
    assert result["stable"] is False


def test_marked_hermetic_runner_must_return_exact_runtime_receipt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    @hermetic_validation_runner
    def receiptless_runner(*, spec, runtime_context, **_kwargs):
        assert runtime_context is not None
        return _result(spec)

    report = ValidationScheduler(
        runner=receiptless_runner,
        hermetic_policy=HermeticValidationPolicy(),
    ).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
    )

    assert report["passed"] is False
    result = report["results"][0]
    assert result["returncode"] == 75
    assert result["error"] == "hermetic_runtime_receipt_mismatch"
    assert result["outcome"] == "infrastructure_failure"
    assert result["authoritative"] is False
    assert result["stable"] is False
    assert result["attempts"][0]["observed_runtime_id"] == ""
    assert result["attempts"][0]["expected_runtime_id"]
    assert result.get("runtime_id", "") == ""
    assert result.get("cancellation_id", "") == ""


@pytest.mark.parametrize("stale_attempt_count", (None, "not-a-number"))
def test_hermetic_cache_rejects_success_without_exact_runtime_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_attempt_count: object,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cache = ValidationResultCache(tmp_path / "cache")
    monkeypatch.setattr(
        cache,
        "get",
        lambda _key: {
            "returncode": 0,
            "output": "forged stale cache authority",
            "attempt_count": stale_attempt_count,
        },
    )
    calls: list[int] = []

    @hermetic_validation_runner
    def runner(*, spec, runtime_context, attempt_number, **_kwargs):
        calls.append(attempt_number)
        result = _result(spec)
        result.update(
            {
                "runtime_id": runtime_context.runtime_id,
                "cancellation_id": runtime_context.cancellation_id,
            }
        )
        return result

    report = ValidationScheduler(
        cache=cache,
        runner=runner,
        hermetic_policy=HermeticValidationPolicy(),
    ).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
    )

    assert report["passed"] is True
    assert calls == [1, 2]
    result = report["results"][0]
    assert result["cache_hit"] is False
    assert result["authoritative"] is True
    assert result["runtime_id"]
    assert result["cancellation_id"]
    base_digest = _validation_result_digest(result)
    tampered = dict(result)
    tampered["runtime_id"] = f"{result['runtime_id']}-tampered"
    assert _validation_result_digest(tampered) != base_digest


def test_raw_no_site_rejects_external_isolation_receipt_substitution(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    @sealed_validation_python_runner
    def isolated_runner(*, spec, **_kwargs):
        result = _result(spec)
        result["external_validation_isolation_receipt"] = {
            "schema": (
                "ipfs_accelerate_py.agent_supervisor."
                "external-validation-isolation@1"
            ),
            "image_id": "sha256:" + ("a" * 64),
            "container_removed": True,
            "receipt_id": "baguqeera" + ("a" * 56),
        }
        return result

    report = ValidationScheduler(runner=isolated_runner).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
        environment={VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"},
    )
    result = report["results"][0]
    assert result["returncode"] == 75
    assert result["authoritative"] is False
    assert result["error"] == (
        "validation_environment_python_launcher_receipt_mismatch"
    )


def test_hermetic_cache_reuses_exact_runtime_receipts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[int] = []

    @hermetic_validation_runner
    def runner(*, spec, runtime_context, attempt_number, **_kwargs):
        calls.append(attempt_number)
        result = _result(spec)
        result.update(
            {
                "runtime_id": runtime_context.runtime_id,
                "cancellation_id": runtime_context.cancellation_id,
            }
        )
        return result

    scheduler = ValidationScheduler(
        cache_dir=tmp_path / "cache",
        runner=runner,
        hermetic_policy=HermeticValidationPolicy(),
    )
    common = {
        "workspace_path": workspace,
        "changed_files": ["pyproject.toml"],
        "target_commit": "same-commit",
        "dependency_state": "same-dependencies",
    }

    first = scheduler.run(["true"], **common)
    replay = scheduler.run(["true"], **common)

    assert first["passed"] is True
    assert first["results"][0]["cache_hit"] is False
    assert replay["passed"] is True
    assert replay["results"][0]["cache_hit"] is True
    assert replay["results"][0]["authoritative"] is True
    assert calls == [1, 2]


def test_hermetic_scheduler_rejects_dual_sealed_runner_composition(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[str] = []

    @sealed_validation_python_runner
    @hermetic_validation_runner
    def dual_runner(*, spec, runtime_context, **_kwargs):
        calls.append(spec.command)
        result = _result(spec)
        result.update(
            {
                "runtime_id": runtime_context.runtime_id,
                "cancellation_id": runtime_context.cancellation_id,
            }
        )
        return result

    report = ValidationScheduler(
        runner=dual_runner,
        hermetic_policy=HermeticValidationPolicy(),
    ).run(
        ["true"],
        workspace_path=workspace,
        changed_files=["pyproject.toml"],
        target_commit="same-commit",
        dependency_state="same-dependencies",
    )

    assert calls == []
    assert report["passed"] is False
    result = report["results"][0]
    assert result["returncode"] == 75
    assert result["error"] == "hermetic_sealed_runner_composition_unsupported"
    assert result["outcome"] == "infrastructure_failure"
    assert result["authoritative"] is False


def test_hermetic_scheduler_rejects_raw_no_site_before_execution_or_cache(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[int] = []

    @hermetic_validation_runner
    def runner(*, spec, runtime_context, attempt_number, **_kwargs):
        calls.append(attempt_number)
        result = _result(spec)
        result.update(
            {
                "runtime_id": runtime_context.runtime_id,
                "cancellation_id": runtime_context.cancellation_id,
            }
        )
        return result

    scheduler = ValidationScheduler(
        cache_dir=tmp_path / "cache",
        runner=runner,
        hermetic_policy=HermeticValidationPolicy(),
    )
    options = {
        "workspace_path": workspace,
        "changed_files": ["pyproject.toml"],
        "target_commit": "same-commit",
        "dependency_state": "same-dependencies",
        "environment": {VALIDATION_PYTHON_PROFILE_ENV: "raw-no-site"},
    }
    first = scheduler.run(["true"], **options)
    replay = scheduler.run(["true"], **options)

    assert calls == []
    for report in (first, replay):
        assert report["passed"] is False
        result = report["results"][0]
        assert result["returncode"] == 75
        assert result["cache_hit"] is False
        assert result["error"] == (
            "hermetic_raw_no_site_composition_unsupported"
        )
        assert result["reason"] == (
            "hermetic_runtime_has_no_sealed_no_site_receipt_contract"
        )
        assert result["outcome"] == "infrastructure_failure"
        assert result["authoritative"] is False


def test_cache_key_includes_commit_command_relevant_environment_and_dependencies() -> None:
    base = build_validation_cache_key(
        target_commit="commit-a",
        command="pytest tests/test_alpha.py",
        environment={"PYTHONPATH": "src", "IGNORED_SECRET": "one"},
        dependency_state={"lock": "one"},
    )
    same = build_validation_cache_key(
        target_commit="commit-a",
        command="pytest tests/test_alpha.py",
        environment={"IGNORED_SECRET": "two", "PYTHONPATH": "src"},
        dependency_state={"lock": "one"},
    )

    assert base.digest == same.digest
    variants = [
        build_validation_cache_key(
            target_commit="commit-b",
            command="pytest tests/test_alpha.py",
            environment={"PYTHONPATH": "src"},
            dependency_state={"lock": "one"},
        ),
        build_validation_cache_key(
            target_commit="commit-a",
            command="pytest tests/test_beta.py",
            environment={"PYTHONPATH": "src"},
            dependency_state={"lock": "one"},
        ),
        build_validation_cache_key(
            target_commit="commit-a",
            command="pytest tests/test_alpha.py",
            environment={"PYTHONPATH": "lib"},
            dependency_state={"lock": "one"},
        ),
        build_validation_cache_key(
            target_commit="commit-a",
            command="pytest tests/test_alpha.py",
            environment={"PYTHONPATH": "src"},
            dependency_state={"lock": "two"},
        ),
    ]
    assert all(item.digest != base.digest for item in variants)
    assert base.to_dict()["target_commit"] == "commit-a"


def test_success_cache_is_durable_and_dirty_or_dependency_content_invalidates(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    commit = _repo(repo)
    calls = 0

    def runner(*, spec, **_kwargs):
        nonlocal calls
        calls += 1
        return _result(spec)

    cache_dir = tmp_path / "cache"
    command = "pytest tests/test_alpha.py"
    scheduler = ValidationScheduler(cache_dir=cache_dir, runner=runner)
    first = scheduler.run(
        [command],
        workspace_path=repo,
        changed_files=["src/alpha.py"],
        target_commit=commit,
    )
    second = ValidationScheduler(cache_dir=cache_dir, runner=runner).run(
        [command],
        workspace_path=repo,
        changed_files=["src/alpha.py"],
        target_commit=commit,
    )

    assert calls == 1
    assert first["cache_misses"] == 1
    assert second["cache_hits"] == 1

    (repo / "src" / "alpha.py").write_text("VALUE = 2\n", encoding="utf-8")
    dirty = ValidationScheduler(cache_dir=cache_dir, runner=runner).run(
        [command],
        workspace_path=repo,
        changed_files=["src/alpha.py"],
        target_commit=commit,
    )
    assert calls == 2
    assert dirty["cache_hits"] == 0

    (repo / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='2'\n", encoding="utf-8"
    )
    dependency_changed = ValidationScheduler(cache_dir=cache_dir, runner=runner).run(
        [command],
        workspace_path=repo,
        changed_files=["src/alpha.py"],
        target_commit=commit,
    )
    assert calls == 3
    assert dependency_changed["cache_hits"] == 0


def test_failures_are_not_cached(tmp_path: Path) -> None:
    spec = build_validation_commands(["git diff --check"])[0]
    cache = ValidationResultCache(tmp_path / "cache")
    key = build_validation_cache_key(
        target_commit="abc", command=spec, dependency_state="deps", environment={}
    )

    assert cache.put(key, {"returncode": 1}) is False
    assert cache.get(key) is None


def test_impact_selection_is_explainable_and_dependency_changes_are_conservative() -> None:
    commands = [
        "git diff --check",
        "pytest tests/test_alpha.py",
        "pytest tests/test_beta.py",
        "custom-validation --all",
    ]
    narrow = select_validation_commands(commands, ["src/alpha.py"])
    decisions = {item.spec.command: item for item in narrow.items}

    assert decisions["git diff --check"].selected is True
    assert decisions["pytest tests/test_alpha.py"].selected is True
    assert decisions["pytest tests/test_alpha.py"].matched_paths == ("src/alpha.py",)
    assert decisions["pytest tests/test_beta.py"].selected is False
    assert decisions["pytest tests/test_beta.py"].reason == "no_changed_path_matches_command_target"
    assert decisions["custom-validation --all"].selected is True
    assert decisions["custom-validation --all"].reason == "global_or_unknown_impact"

    broad = select_validation_commands(commands, ["pyproject.toml"])
    assert all(item.selected for item in broad.items)
    assert broad.to_dict()["changed_files"] == ["pyproject.toml"]

    prefixed_test = select_validation_commands(
        ["pytest test/api/test_agent_supervisor_validation_scheduler.py"],
        ["ipfs_accelerate_py/agent_supervisor/validation_scheduler.py"],
    )
    assert prefixed_test.items[0].selected is True
    assert prefixed_test.items[0].reason == "changed_path_matches_command_target"

    ci_change = select_validation_commands(commands, [".github/workflows/test.yml"])
    assert all(item.selected for item in ci_change.items)


def test_pre_merge_escalation_runs_unrelated_targeted_validation(tmp_path: Path) -> None:
    calls: list[str] = []

    def runner(*, spec, **_kwargs):
        calls.append(spec.command)
        return _result(spec, returncode=9 if "beta" in spec.command else 0)

    report = ValidationScheduler(max_workers=2, resource_budget=2, runner=runner).run(
        ["pytest tests/test_alpha.py", "pytest tests/test_beta.py"],
        workspace_path=tmp_path,
        changed_files=["src/alpha.py"],
        target_commit="abc",
        dependency_state="deps",
        require_full_validation=True,
        scope="pre_merge",
    )

    assert set(calls) == {"pytest tests/test_alpha.py", "pytest tests/test_beta.py"}
    assert report["passed"] is False
    assert report["selection"]["escalated"] is True
    beta = next(item for item in report["selection"]["decisions"] if "beta" in item["command"])
    assert beta["reason"] == "pre_merge_broad_escalation"
    assert beta["stage"] == "broad"


def test_dependency_state_records_candidate_content_not_only_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo(repo)
    before = collect_dependency_state(repo, changed_files=["src/alpha.py"])
    (repo / "src" / "alpha.py").write_text("VALUE = 99\n", encoding="utf-8")
    after = collect_dependency_state(repo, changed_files=["src/alpha.py"])

    assert before["candidate_content_sha256"] != after["candidate_content_sha256"]


def test_daemon_uses_full_pre_merge_scope_and_preserves_result_contract(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class Scheduler:
        def run(self, commands, **kwargs):
            captured["commands"] = list(commands)
            captured.update(kwargs)
            return {
                "attempted": True,
                "passed": False,
                "returncode": 6,
                "results": [
                    {
                        "command": commands[0],
                        "returncode": 6,
                        "stage": "cheap",
                        "output": "failed\n",
                    }
                ],
                "failed_command": commands[0],
                "selection": {"scope": "pre_merge", "changed_files": ["src/a.py"]},
            }

    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=tmp_path,
        validation_scheduler=Scheduler(),  # type: ignore[arg-type]
    )
    task = PortalTask(
        task_id="REF-043",
        title="validation scheduler",
        status="todo",
        completion="manual",
        priority="P1",
        track="g9",
        validation=["git diff --check"],
    )

    report = daemon._run_validation_commands(tmp_path, task, tmp_path / "validation.log")

    assert captured["commands"] == ["git diff --check"]
    assert captured["require_full_validation"] is True
    assert captured["scope"] == "pre_merge"
    assert callable(captured["runner"])
    assert report["attempted"] is True
    assert report["passed"] is False
    assert report["returncode"] == 6
    assert report["failed_command"] == "git diff --check"


def test_daemon_binds_sibling_repositories_for_sealed_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    sibling_root = workspace / "external" / "ipfs_datasets"
    sibling_root.mkdir(parents=True)
    (sibling_root / "sibling_fixture.py").write_text(
        "VALUE = 42\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERVISOR_VALIDATION_SECRET", "must-not-leak")
    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=workspace,
        worktree_submodule_paths=("external/ipfs_datasets",),
        validation_scheduler=ValidationScheduler(),
    )
    task = PortalTask(
        task_id="PTR-010",
        title="cross-repository validation",
        status="todo",
        completion="manual",
        priority="P0",
        track="platform",
        validation=[
            "true && python -c 'import os, sibling_fixture; "
            "assert sibling_fixture.VALUE == 42; "
            'assert "SUPERVISOR_VALIDATION_SECRET" not in os.environ\''
        ],
    )
    log_path = tmp_path / "validation.log"

    report = daemon._run_validation_commands(workspace, task, log_path)

    assert report["passed"] is True
    assert report["results"][0]["command"].startswith(
        "export PYTHONPATH=external/ipfs_datasets && "
    )
    assert (
        "[validation normalized] added configured worktree package roots "
        "to PYTHONPATH"
    ) in log_path.read_text(encoding="utf-8")


def test_daemon_preserves_reviewed_validation_pythonpath(tmp_path: Path) -> None:
    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=tmp_path,
        worktree_submodule_paths=("external/ipfs_datasets",),
    )
    command = "MODE=off PYTHONPATH=custom:. python -m pytest -q"

    bound, notes = daemon._bind_workspace_validation_pythonpath(
        command,
        tmp_path,
    )

    assert bound == command
    assert notes == []


def test_daemon_does_not_rewrite_non_python_validation(tmp_path: Path) -> None:
    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=tmp_path,
        worktree_submodule_paths=("external/ipfs_datasets",),
    )

    bound, notes = daemon._bind_workspace_validation_pythonpath(
        "git diff --check",
        tmp_path,
    )

    assert bound == "git diff --check"
    assert notes == []


@pytest.mark.parametrize("provider_state", ("missing", "symlink_escape"))
def test_daemon_omits_unavailable_or_escaping_validation_roots(
    tmp_path: Path,
    provider_state: str,
) -> None:
    workspace = tmp_path / "workspace"
    external = workspace / "external"
    external.mkdir(parents=True)
    if provider_state == "symlink_escape":
        outside = tmp_path / "outside"
        outside.mkdir()
        (external / "provider").symlink_to(
            outside,
            target_is_directory=True,
        )
    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=workspace,
        worktree_submodule_paths=("external/provider",),
    )
    command = "python -m pytest -q"

    bound, notes = daemon._bind_workspace_validation_pythonpath(
        command,
        workspace,
    )

    assert bound == command
    assert notes == []


def test_daemon_omits_validation_roots_containing_path_separator(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    safe_root = workspace / "external" / "safe"
    safe_root.mkdir(parents=True)
    unsafe_relative = f"inside{os.pathsep}/tmp"
    (workspace / unsafe_relative).mkdir(parents=True)
    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=workspace,
        worktree_submodule_paths=(unsafe_relative, "external/safe"),
    )

    bound, notes = daemon._bind_workspace_validation_pythonpath(
        "python -m pytest -q",
        workspace,
    )

    assert bound == (
        'export PYTHONPATH="$PWD"/external/safe; python -m pytest -q'
    )
    assert unsafe_relative not in bound
    assert notes == [
        "bound configured worktree submodule roots to validation PYTHONPATH"
    ]


def test_daemon_binds_task_validation_to_proposal_local_impact_graph(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    (tmp_path / "external" / "ipfs_accelerate").mkdir(parents=True)

    class Scheduler:
        def run_validated(self, proposal_validation, commands, **kwargs):
            captured["proposal_validation"] = proposal_validation
            captured["commands"] = tuple(commands)
            captured.update(kwargs)
            return {
                "attempted": True,
                "passed": True,
                "returncode": 0,
                "results": [],
            }

    daemon = TodoImplementationDaemon(
        todo_path=tmp_path / "todo.md",
        state_path=tmp_path / "state.json",
        strategy_path=tmp_path / "strategy.json",
        events_path=tmp_path / "events.jsonl",
        repo_root=tmp_path,
        worktree_submodule_paths=("external/ipfs_accelerate",),
        validation_scheduler=Scheduler(),  # type: ignore[arg-type]
    )
    task = PortalTask(
        task_id="IRF-010",
        title="proposal-local validation",
        status="todo",
        completion="manual",
        priority="P0",
        track="platform",
        validation=["python -m pytest tests/unit/test_identity.py -q"],
    )
    proposal_validation = SimpleNamespace(
        accepted=True,
        findings=(),
        proposal=SimpleNamespace(
            proposal_id="proposal:fixture",
            repository_tree_id="tree:fixture",
            changed_paths=("src/identity.py", "tests/unit/test_identity.py"),
        ),
        policy=SimpleNamespace(policy_id="policy:fixture"),
        receipt=SimpleNamespace(receipt_id="receipt:fixture"),
    )

    report = daemon._run_validation_commands(
        tmp_path,
        task,
        tmp_path / "validation.log",
        proposal_validation=proposal_validation,
    )

    commands = captured["commands"]
    graph = captured["impact_graph"]
    assert captured["require_impact_graph"] is True
    assert captured["require_full_validation"] is True
    assert captured["scope"] == "pre_merge"
    assert len(commands) == 1
    assert commands[0].validation_id.startswith("declared:")
    assert commands[0].command.startswith(
        "export PYTHONPATH=external/ipfs_accelerate && "
    )
    assert graph.graph_version == "declared-validation-plan-v1"
    assert graph.required_validations(
        graph.affected_paths(("src/identity.py", "tests/unit/test_identity.py"))
    )
    assert report["passed"] is True
    assert report["validation_plan_binding"]["graph_id"] == graph.graph_id
