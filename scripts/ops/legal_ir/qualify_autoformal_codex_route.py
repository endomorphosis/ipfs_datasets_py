#!/usr/bin/env python3
"""Qualify a rootless native Codex boundary without claiming a repair task.

Uses an existing immutable Docker image; never builds/pulls, resets task state,
touches shared accelerate source, or publishes. All fixtures and receipts are
retained. A synthetic smoke test is not repair validation or proof admission.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from run_autoformal_supervisor import pin_accelerate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_rootless(security_options: list[str]) -> None:
    if type(security_options) is not list or "name=rootless" not in security_options:
        raise ValueError("provider probe requires an explicitly rootless Docker daemon")


def fixture_is_correct(path: Path) -> bool:
    # Inspect syntax and evaluate only the narrowly accepted function shape;
    # never import arbitrary model-written code into the operator process.
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeError):
        return False
    expected = ast.parse("def add_one(value):\n    return value + 1\n")
    return ast.dump(tree, include_attributes=False) == ast.dump(expected, include_attributes=False)


def run_bounded(command, *, cwd: Path, log: Path, prompt: str, timeout: float,
                container_name: str, docker: list[str]) -> dict:
    started = time.monotonic()
    with log.open("xb") as stream:
        child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                 stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        timed_out = False
        try:
            child.communicate(prompt.encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Stop only this unique qualification container/process group.
            subprocess.run([*docker, "stop", "--time=5", container_name],
                           capture_output=True, timeout=15, check=False)
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
    return {"returncode": child.returncode, "timed_out": timed_out,
            "elapsed_seconds": time.monotonic() - started,
            "log_path": str(log), "log_sha256": digest(log)}


BOUNDARY_PROBE = r'''
import json, os, pathlib
work = pathlib.Path.cwd()
checks = {}
(work / 'writable.txt').write_text('inside')
checks['workspace_writable'] = (work / 'writable.txt').read_text() == 'inside'
for name, path in [('git_read_only', work / '.git' / 'qualification-canary'),
                   ('root_read_only', pathlib.Path('/rootfs-qualification-canary'))]:
    try:
        path.write_text('forbidden')
        checks[name] = False
    except OSError:
        checks[name] = True
checks['sibling_not_visible'] = not (work.parent / 'outside-canary.txt').exists()
checks['docker_socket_not_visible'] = not pathlib.Path('/var/run/docker.sock').exists() and not pathlib.Path('/run/user/1000/docker.sock').exists()
checks['code_mode_host_present'] = os.access('/usr/local/bin/codex-code-mode-host', os.X_OK)
status = pathlib.Path('/proc/self/status').read_text().splitlines()
checks['no_capabilities'] = any(line.split() == ['CapEff:', '0000000000000000'] for line in status)
checks['no_new_privileges'] = any(line.split() == ['NoNewPrivs:', '1'] for line in status)
print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 1)
'''


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--provider-smoke", action="store_true")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    if not 10 <= args.timeout <= 300:
        parser.error("smoke timeout must be between 10 and 300 seconds")
    import re
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image_id):
        parser.error("image must be an immutable sha256 ID")
    pin_accelerate(args.accelerate_root)
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import implementation_daemon as native
    from ipfs_datasets_py.logic.autoformal.feedback_cycle import check_storage
    runtime = args.runtime_root.resolve(strict=True)
    check_storage(runtime, 50_000_000_000, reserve=256 * 1024 * 1024)
    directory = Path(tempfile.mkdtemp(prefix="codex-route-qualification-", dir=runtime))
    report = {"schema": "autoformal.codex-rootless-qualification/v1", "directory": str(directory),
              "provider_called": False, "tasks_claimed": False, "tasks_reopened": False,
              "accepted_repairs": 0, "optimizer_updates": 0, "published": False,
              "production_promotion": False, "passed": False,
              "live_repair_qualified": False, "native_validation_executed": False,
              "scope": "synthetic boundary and optional provider probe only",
              "network": "bridge for model transport; not an egress allowlist",
              "accelerate_head": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=args.accelerate_root, text=True).strip(),
              "native_command_source_sha256": digest(Path(native.__file__))}
    docker = ["/usr/bin/docker", f"--host=unix:///run/user/{os.getuid()}/docker.sock"]
    try:
        security = json.loads(subprocess.check_output(
            [*docker, "info", "--format", "{{json .SecurityOptions}}"], text=True, timeout=15))
        require_rootless(security)
        report["security_options"] = security
        identity = subprocess.check_output(
            [*docker, "image", "inspect", "--format",
             '{{.Id}}|{{.Os}}|{{.Architecture}}|{{index .Config.Labels "org.ipfs-accelerate.pcpc-runtime"}}|{{index .Config.Labels "org.ipfs-accelerate.codex.sha256"}}',
             args.image_id], text=True, timeout=15).strip().split("|")
        config = native.validate_external_provider_isolation_config({
            "schema": native.PROVIDER_EXTERNAL_ISOLATION_SCHEMA, "required": True,
            "backend": "docker", "provider_id": "codex", "runtime_executable": docker[0],
            "runtime_endpoint": docker[1].removeprefix("--host="), "image_id": identity[0],
            "image_os": identity[1], "image_architecture": identity[2], "image_label": identity[3],
            "container_executable": "/usr/local/bin/codex", "container_executable_sha256": identity[4],
            "credential_file": str(args.credential_file.resolve(strict=True)), "network": "bridge",
            "pids_limit": 128, "memory_bytes": 2 * 1024**3, "cpus": 2.0,
            "tmpfs_size_bytes": 64 * 1024**2,
        })
        config_path = directory / "isolation-config.json"
        with config_path.open("x") as stream:
            json.dump(config.to_dict(), stream, sort_keys=True, indent=2)
        report["config_path"] = str(config_path)
        report["config_sha256"] = digest(config_path)
        vendor = native._host_codex_vendor_binaries()
        report["host_vendor_binaries"] = {str(p): digest(p) for p in vendor or ()}
        repository = directory / "fixture-repository"
        workspace = directory / "fixture-worktree"
        repository.mkdir()
        subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", str(repository)], check=True)
        (repository / "probe.py").write_text("def add_one(value):\n    return value - 1\n")
        subprocess.run(["git", "add", "--", "probe.py"], cwd=repository, check=True)
        subprocess.run(["git", "-c", "user.name=Qualification", "-c", "user.email=local@localhost",
                        "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic fixture"], cwd=repository, check=True)
        subprocess.run(["git", "worktree", "add", "--detach", str(workspace)], cwd=repository, check=True, capture_output=True)
        sentinel = directory / "outside-canary.txt"
        sentinel.write_text("unchanged\n")
        inner = [config.container_executable, "exec", "--ignore-user-config", "--ignore-rules",
                 "--ephemeral", "--dangerously-bypass-approvals-and-sandbox", "--json",
                 "-C", str(workspace), "-m", "gpt-5.6-terra",
                 "-c", 'model_reasoning_effort="medium"', "-c", 'web_search="disabled"',
                 "-c", 'features.apps=false', "-c", 'features.plugins=false', "-c", 'features.hooks=false', "-"]
        command = native._docker_codex_implementation_command(inner_command=inner, workspace_path=workspace,
                                                              repository_root=repository, config=config)
        # Boundary-only probe shares the generated mounts and resource flags.
        # The Git marker is a file in a linked worktree, so probe the common
        # Git directory, not a path that would fail merely with ENOTDIR.
        probe = BOUNDARY_PROBE.replace("work / '.git' / 'qualification-canary'", repr(str(repository / '.git' / 'qualification-canary')))
        probe = probe.replace("path.write_text('forbidden')", "pathlib.Path(path).write_text('forbidden')")
        boundary = [*command[:-len(inner)], str(native._VALIDATION_CONTAINER_PYTHON), "-c", probe]
        boundary[boundary.index("--network=bridge")] = "--network=none"
        result = subprocess.run(boundary, cwd=workspace, text=True, capture_output=True, timeout=30)
        report["boundary"] = {"returncode": result.returncode, "checks": json.loads(result.stdout) if result.returncode == 0 else {},
                              "stderr": result.stderr[-2000:]}
        if result.returncode:
            raise ValueError("rootless boundary qualification failed")
        report["boundary_passed"] = True
        if args.provider_smoke:
            name = directory.name + "-provider"
            command.insert(command.index("run") + 1, "--name=" + name)
            prompt = ("This is a synthetic provider qualification, not a repair task. Edit only probe.py "
                      "using apply_patch so add_one(value) returns value + 1. Keep exactly one plain function, "
                      "with no imports, annotations, decorators, comments or docstrings. Do not use network, "
                      "read credentials, edit Git, install anything, commit, or inspect other directories. "
                      "Run python3 -c 'from probe import add_one; assert add_one(3) == 4'. Then reply READY.")
            report["provider_called"] = True
            report["smoke"] = run_bounded(command, cwd=workspace, log=directory / "provider.log",
                                         prompt=prompt, timeout=args.timeout, container_name=name, docker=docker)
            changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=workspace, text=True).splitlines()
            report["fixture_correct"] = fixture_is_correct(workspace / "probe.py")
            report["changes"] = changes
            report["outside_canary_unchanged"] = sentinel.read_text() == "unchanged\n"
            report["passed"] = (report["smoke"]["returncode"] == 0 and not report["smoke"]["timed_out"]
                                and report["fixture_correct"] and report["outside_canary_unchanged"]
                                and sorted(changes) == [" M probe.py", "?? writable.txt"])
        else:
            report["passed"] = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
    path = directory / "receipt.json"
    with path.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"receipt": str(path), "passed": report["passed"],
                      "provider_called": report["provider_called"], "tasks_claimed": False,
                      "live_repair_qualified": False}))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
