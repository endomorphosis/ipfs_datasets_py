#!/usr/bin/env python3
"""Replay one sealed task in retained diagnostic worktrees, without dispatch.

No task transition, provider call, acceptance, merge, training, or publication.
The task may be blocked: this is a negative validation qualification only.
Receipts and worktrees are retained, including failures.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from run_autoformal_supervisor import pin_accelerate, validated_task_id


def observed_checks(first: dict, replay: dict, rejected: dict, *, source_span_id: str = "") -> dict[str, bool]:
    # The sealed packet, not candidate output, selects the expected gate.
    gate = ("source_replay_not_legal_equivalence" if source_span_id
            else "extended_structural_roundtrip_not_legal_equivalence")
    def metadata_passed(result):
        for line in result.get("output", "").splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if (isinstance(data, dict) and isinstance(data.get("sealed_container_dependencies"), dict)
                    and data["sealed_container_dependencies"].get("passed") is True):
                return True
        return False
    def replay_rejected(result):
        for line in result.get("output", "").splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if (isinstance(data, dict) and data.get("passed") is False
                    and data.get("gate") == gate
                    and data.get("admitted") is False and data.get("formalized") is False
                    and type(data.get("checked_count")) is int and data["checked_count"] > 0
                    and isinstance(data.get("failures"), list)
                    and any(isinstance(item, dict) and (
                        item.get("id") == source_span_id if source_span_id else
                        item.get("case") == "sealed_source" and item.get("passed") is False
                    ) for item in data.get("failures", []))):
                return True
        return False
    return {
        "image_dependencies_checked": metadata_passed(first) and metadata_passed(replay),
        "missing_regression_rejected": first.get("returncode") == 2 and "task-owned regression test is missing or a symlink" in first.get("output", ""),
        "source_replay_rejected_baseline": replay.get("returncode") == 1 and replay_rejected(replay),
        "changed_command_rejected_before_execution": rejected.get("returncode") == 75 and rejected.get("error") == "external_validation_isolation_unavailable" and "command or image differs" in rejected.get("reason", ""),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accelerate-root", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--isolation-config", required=True, type=Path)
    parser.add_argument("--task-id", required=True, type=validated_task_id)
    args = parser.parse_args(argv)
    pin_accelerate(args.accelerate_root)
    import duckdb
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_accelerate_py.agent_supervisor.task_sources.intent_repository import IntentRepository
    from ipfs_accelerate_py.agent_supervisor.todo_daemon import implementation_daemon as native
    from ipfs_accelerate_py.agent_supervisor.runtime import multi_supervisor_runner as runner
    from ipfs_accelerate_py.agent_supervisor.validation import sealed_container as adapter
    from ipfs_datasets_py.logic.autoformal.feedback_cycle import check_storage
    from ipfs_datasets_py.logic.autoformal.validator_profile import require_deployment
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import read_packet
    runtime = args.runtime_root.resolve(strict=True)
    repository = args.repository_root.resolve(strict=True)
    database = args.database.resolve(strict=True)
    if repository.parent != runtime or database.parent != runtime:
        raise ValueError("qualification requires existing private repository/database inside the owned runtime")
    def git(*values):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *values],
                                       cwd=repository, text=True, stderr=subprocess.PIPE).strip()
    if git("status", "--porcelain") or Path(git("rev-parse", "--show-toplevel")) != repository:
        raise ValueError("qualification requires a clean private snapshot")
    if require_deployment(repository) is None:
        raise ValueError("qualification requires an existing sealed validator deployment")
    sizes = git("ls-tree", "-r", "--format=%(objectsize)", "HEAD").splitlines()
    check_storage(runtime, 50_000_000_000, reserve=2 * sum(int(x) for x in sizes if x.isdigit()) + 64 * 1024**2)
    directory = Path(tempfile.mkdtemp(prefix="sealed-validator-qualification-", dir=runtime))
    report = {"schema": "autoformal.sealed-container-qualification/v1", "task_id": args.task_id,
              "provider_dispatched": False, "tasks_claimed": False, "tasks_reopened": False,
              "accepted_repairs": 0, "optimizer_updates": 0, "published": False,
              "live_repair_qualified": False, "passed": False,
              "scope": "isolated negative source replay and transport checks only",
              "directory": str(directory), "candidate_head": git("rev-parse", "HEAD")}
    def snapshot():
        with duckdb.connect(str(database), read_only=True) as connection:
            intent = IntentRepository(database, bound_connection=connection, install_schema=False)
            source = DatabaseTaskSource(intent=intent)
            tasks, cursor = [], ""
            while True:
                page = source.list_tasks(cursor=cursor, limit=100)
                tasks.extend(page.tasks)
                cursor = page.next_cursor
                if not cursor:
                    break
            found = [task for task in tasks if task.task_alias == args.task_id]
            if len(found) != 1:
                raise ValueError("task alias must identify exactly one existing task")
            state = {"revision": source.snapshot().revision, "counts": dict(Counter(t.status for t in tasks)),
                     "task_status": found[0].status, "task_cid": found[0].task_cid}
            source.close()
            return state, found[0]
    try:
        report["queue_before"], task = snapshot()
        packet = read_packet(Path(task.body["packet_path"]), task.body["packet_sha256"])
        source_span_id = "" if "extension" in packet else packet["row"]["source_span_id"]
        report["replay_family"] = "extension" if not source_span_id else "baseline"
        if len(task.validations) != 1:
            raise ValueError("qualification requires exactly one sealed validation command")
        command = shlex.join(task.validations[0]["argv"])
        outputs = [item["path"] for item in task.outputs]
        regression = "tests/unit/logic/autoformal_repairs/test_" + task.body["packet_sha256"][:20] + ".py"
        if not outputs or outputs[-1] != regression:
            raise ValueError("task regression path is not content-addressed")
        config = native.validate_external_provider_isolation_config(json.loads(args.isolation_config.read_text()))
        security = json.loads(subprocess.check_output([config.runtime_executable, "--host=" + config.runtime_endpoint,
            "info", "--format", "{{json .SecurityOptions}}"], text=True, timeout=15))
        if "name=rootless" not in security:
            raise ValueError("qualification requires rootless Docker")
        store_id = "autoformal-" + hashlib.sha256(str(database).encode()).hexdigest()[:16]
        binding = adapter.build_binding(repository=repository, control_database=database,
            store_id=store_id, image_id=config.image_id, command=command,
            task_authority={"board_namespace": task.body["board_namespace"],
                "canonical_task_cid": task.task_cid, "declared_outputs": outputs})
        raw = adapter.canonical(binding)
        (directory / "binding.json").write_bytes(raw)
        report["binding_sha256"] = adapter.sha(raw)
        program = runner.DatabaseProgramConfig(authority_mode="embedded", task_source_kind="duckdb",
            store_id=store_id, failover_policy="fail_closed")
        environment = program.environment(repository_root=repository)
        environment.update({native._LIFECYCLE_REPOSITORY_ROOT_ENV: str(repository),
                            native.PROVIDER_EXTERNAL_ISOLATION_ENV: config.environment_json(),
                            adapter.ENV: raw.decode(), adapter.SHA_ENV: adapter.sha(raw)})
        candidate = directory / "candidate"
        git("worktree", "add", "--detach", str(candidate), report["candidate_head"])
        report["candidate_worktree"] = str(candidate)
        def validate(selected_command):
            with patch.dict(os.environ, environment):
                return native.PortalImplementationDaemon._validation_command_runner(
                    spec=SimpleNamespace(command=selected_command, raw_command=selected_command),
                    workspace_path=candidate, timeout_seconds=120,
                    environment={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        first = validate(command)
        report["missing_regression"] = first
        if first.get("returncode") == 2 and "task-owned regression test is missing" in first.get("output", ""):
            target = candidate / regression
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink() or target.parent.resolve() != target.parent:
                raise ValueError("diagnostic regression must be a new contained file")
            with target.open("x") as stream:
                stream.write('def test_diagnostic_is_never_an_accepted_repair():\n    raise AssertionError("diagnostic-only sentinel, not a repair regression")\n')
            report["diagnostic_regression_only"] = regression
            replay = validate(command)
        else:
            replay = {"not_run": "transport did not reach the missing-test gate"}
        report["baseline_replay"] = replay
        rejected = validate(command + " --unapproved")
        report["changed_command"] = rejected
        report["checks"] = observed_checks(first, replay, rejected, source_span_id=source_span_id)
        report["queue_after"], _ = snapshot()
        report["checks"]["queue_unchanged"] = report["queue_before"] == report["queue_after"]
        report["checks"]["candidate_snapshot_unchanged"] = report["candidate_head"] == git("rev-parse", "HEAD") and not git("status", "--porcelain")
        report["passed"] = all(report["checks"].values())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
    report["storage_bytes"] = check_storage(runtime, 50_000_000_000)
    path = directory / "receipt.json"
    with path.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"receipt": str(path), "passed": report["passed"], "checks": report.get("checks", {}),
                      "live_repair_qualified": False, "provider_dispatched": False}))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
