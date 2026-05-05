from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ipfs_datasets_py.optimizers.todo_daemon import (
    CommandResult,
    FileReplacementHooks,
    FileReplacementTodoDaemonRunner,
    LlmRouterInvocation,
    ManagedDaemonSpec,
    PathPolicy,
    PreTaskBlock,
    Proposal,
    RestartPolicy,
    SupervisedChildSpec,
    SupervisorLoop,
    SupervisorLoopConfig,
    Task,
    TodoDaemonHooks,
    TodoDaemonRunner,
    TodoDaemonRuntimeConfig,
    ValidationWorkspaceSpec,
    apply_file_replacement_proposal,
    artifact_validation_text,
    build_file_replacement_apply_proposal,
    build_lifecycle_arg_parser,
    build_python_module_command,
    build_restart_loop_command,
    build_supervisor_status_payload,
    build_todo_runner_arg_parser,
    call_llm_router,
    clear_child_pid_file,
    cleanup_stale_daemon_worktrees,
    current_task_failure_counts,
    daemon_spec_payload,
    diagnostic_signatures,
    extract_codex_event_text_candidates,
    extract_json,
    heartbeat_snapshot,
    has_diagnostic_codes,
    launch_supervised_child,
    last_task_attempt_index,
    looks_like_empty_codex_event_stream,
    materialize_proposal_files,
    owner_pid_from_worktree,
    parse_json_proposal,
    parse_markdown_tasks,
    paths_from_git_status_porcelain,
    paths_from_unified_diff,
    proposal_diff_from_worktree,
    promote_worktree_files,
    quality_failure_counts,
    quoted_env_assignments,
    read_daemon_results,
    read_json_object,
    recent_failure_count,
    recent_rollback_failure_count,
    recent_total_failure_count,
    rollback_failure_counts,
    rounds_since_last_valid,
    run_command,
    run_lifecycle_cli,
    run_todo_daemon,
    run_todo_daemon_cli,
    select_task,
    supervised_log_path,
    supervisor_run_id,
    task_failure_summary,
    temporary_validation_worktree,
    todo_daemon_proposals_payload,
    unified_diff_stats,
    untracked_paths_from_git_status_porcelain,
    verify_promoted_worktree_files,
    wait_for_child_exit,
    worktree_phase_worker_status,
    write_worktree_owner_file,
)
from ipfs_datasets_py.optimizers.todo_daemon.__main__ import (
    daemon_names,
    main as todo_daemon_package_main,
)


@dataclass
class SyntheticDaemonConfig:
    repo_root: Path
    task_board: Path = Path("todo/board.md")
    status_file: Path = Path("todo/status.json")
    progress_file: Path = Path("todo/progress.json")
    result_log: Path = Path("todo/results.jsonl")
    apply: bool = True
    watch: bool = False
    iterations: int = 1
    interval_seconds: float = 0.0
    heartbeat_seconds: float = 30.0
    crash_backoff_seconds: float = 0.0
    revisit_blocked: bool = False

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


def test_parse_markdown_tasks_and_select_reuses_checkbox_ids() -> None:
    tasks = parse_markdown_tasks(
        "\n".join(
            [
                "- [x] Task checkbox-7: Already done.",
                "- [!] Task checkbox-8: Protected blocked.",
                "- [ ] Task checkbox-9: Next reusable task.",
            ]
        )
    )

    selected = select_task(tasks, revisit_blocked=True, protected_blocked_checkbox_ids={8})

    assert selected is not None
    assert selected.checkbox_id == 9
    assert selected.label == "Task checkbox-9: Next reusable task."


def test_path_policy_validates_allowlist_and_private_artifacts() -> None:
    policy = PathPolicy(
        allowed_write_prefixes=("todo/", "docs/PLAN.md"),
        disallowed_write_prefixes=("todo/private-source/",),
        private_write_path_fragments=("storage-state",),
        private_write_path_tokens=frozenset({"session"}),
        runtime_only_change_paths=frozenset({"todo/runtime/status.json"}),
        visible_source_prefixes=("todo/",),
    )

    assert policy.validate_write_path("todo/source.py") == []
    assert "outside example daemon allowlist" in policy.validate_write_path(
        "elsewhere/source.py",
        daemon_label="example daemon",
    )[0]
    assert any(
        "private/session artifacts" in error
        for error in policy.validate_write_path("todo/auth/session.json")
    )
    assert any(
        "disallowed example daemon write target" in error
        for error in policy.validate_write_path(
            "todo/private-source/x.py",
            daemon_label="example daemon",
        )
    )
    assert policy.has_visible_source_change(["todo/source.py"])
    assert not policy.has_visible_source_change(["todo/runtime/status.json"])


def test_parse_json_proposal_accepts_plain_json_and_filters_invalid_files() -> None:
    proposal = parse_json_proposal(
        json.dumps(
            {
                "summary": "Reusable proposal",
                "impact": "Exercises shared parser",
                "files": [
                    {"path": "todo/source.py", "content": "VALUE = 1\n"},
                    {"path": "todo/ignored.py"},
                    "not-a-file",
                ],
                "validation_commands": [["python3", "-m", "compileall", "todo"]],
            }
        )
    )

    assert proposal.summary == "Reusable proposal"
    assert proposal.files == [{"path": "todo/source.py", "content": "VALUE = 1\n"}]
    assert proposal.validation_commands == [["python3", "-m", "compileall", "todo"]]


def test_codex_jsonl_helpers_parse_assistant_proposals() -> None:
    response = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "example"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "```json\n{\"summary\":\"from codex\",\"files\":[]}\n```",
                            }
                        ],
                    },
                }
            ),
        ]
    )

    candidates = extract_codex_event_text_candidates(response)

    assert candidates == ["```json\n{\"summary\":\"from codex\",\"files\":[]}\n```"]
    assert extract_json(response) == {"summary": "from codex", "files": []}
    assert looks_like_empty_codex_event_stream(json.dumps({"type": "thread.started"}))
    assert not looks_like_empty_codex_event_stream(response)


def test_command_result_compaction_omits_html_and_provider_tokens() -> None:
    compacted = CommandResult(
        command=("example",),
        returncode=1,
        stdout="<html><body><script>challenge</script></body></html>",
        stderr="token __cf_chl_tk=secret",
    ).compact()

    assert "challenge" not in compacted["stdout"]
    assert "__cf_chl_tk=secret" not in compacted["stderr"]


def test_shared_run_command_supports_timeout_seconds_and_stdin(tmp_path: Path) -> None:
    ok = run_command(
        ("python3", "-c", "import sys; print(sys.stdin.read().upper())"),
        cwd=tmp_path,
        timeout_seconds=5,
        stdin="ok",
    )
    timed_out = run_command(
        ("python3", "-c", "import time; time.sleep(30)"),
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert ok.ok
    assert ok.stdout.strip() == "OK"
    assert timed_out.returncode == 124
    assert "Command timed out after 1s" in timed_out.stderr


def test_llm_router_invocation_runs_isolated_child_with_prefixed_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SYNTH_LLM_BACKEND", raising=False)
    package = tmp_path / "ipfs_datasets_py"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "llm_router.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "def generate_text(prompt, model_name, provider, allow_local_fallback, timeout, max_new_tokens, temperature):",
                "    return json.dumps({",
                "        'prompt': prompt,",
                "        'model_name': model_name,",
                "        'provider': provider,",
                "        'allow_local_fallback': allow_local_fallback,",
                "        'timeout': timeout,",
                "        'max_new_tokens': max_new_tokens,",
                "        'temperature': temperature,",
                "    })",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = json.loads(
        call_llm_router(
            "hello",
            LlmRouterInvocation(
                repo_root=tmp_path,
                model_name="example-model",
                provider="example-provider",
                allow_local_fallback=True,
                timeout_seconds=7,
                max_new_tokens=321,
                max_prompt_chars=1000,
                temperature=0.2,
                backend_env_name="SYNTH_LLM_BACKEND",
                env_prefix="SYNTH_LLM",
                prompt_file_prefix="synthetic-llm-prompt-",
            ),
        )
    )

    assert payload == {
        "prompt": "hello",
        "model_name": "example-model",
        "provider": "example-provider",
        "allow_local_fallback": True,
        "timeout": 7,
        "max_new_tokens": 321,
        "temperature": 0.2,
    }


def test_daemon_history_helpers_are_reusable(tmp_path: Path) -> None:
    log = tmp_path / "daemon.jsonl"
    rows = [
        {"results": [{"valid": True, "artifact": {"target_task": "Task `A`", "summary": "done"}}]},
        {
            "results": [
                {
                    "valid": False,
                    "artifact": {
                        "target_task": "Task A",
                        "summary": "first",
                        "failure_kind": "preflight",
                        "errors": ["bad path"],
                    },
                }
            ]
        },
        {
            "results": [
                {
                    "valid": False,
                    "artifact": {
                        "target_task": "Task `A`",
                        "summary": "second",
                        "failure_kind": "validation",
                        "errors": ["bad type"],
                    },
                }
            ]
        },
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    parsed = read_daemon_results(log)
    summary = task_failure_summary(parsed, "Task A")

    assert len(parsed) == 3
    assert recent_failure_count(parsed, "Task A", "validation") == 1
    assert recent_failure_count(parsed, "Task A", "preflight") == 0
    assert recent_total_failure_count(parsed, "Task A") == 2
    assert current_task_failure_counts(parsed, "Task A") == {
        "total_since_success": 2,
        "by_kind_since_success": {"validation": 1, "preflight": 1},
    }
    assert rounds_since_last_valid(parsed) == 2
    assert last_task_attempt_index(parsed, "Task A") == 2
    assert summary["latest_failure"]["failure_kind"] == "validation"
    assert summary["latest_failure"]["errors"] == ["bad type"]


def test_daemon_diagnostic_failure_loop_helpers_are_reusable() -> None:
    rows = [
        (
            {"valid": True},
            {"target_task": "Task A", "failure_kind": "", "errors": []},
        ),
        (
            {"valid": False},
            {
                "target_task": "Task `A`",
                "failure_kind": "quality",
                "errors": ["src/example.ts(1,1): error TS2339: Property 'foo' does not exist."],
                "validation_results": [{"stdout": "", "stderr": "error TS2339: Property 'bar' does not exist."}],
            },
        ),
        (
            {"valid": False},
            {
                "target_task": "Task `A`",
                "failure_kind": "quality",
                "errors": ["src/example.ts(2,1): error TS2339: Property 'baz' does not exist."],
                "validation_results": [],
            },
        ),
        (
            {"valid": False},
            {
                "target_task": "Task B",
                "failure_kind": "parse",
                "errors": ["bad json"],
                "changed_files": ["todo/output.py"],
            },
        ),
    ]

    quality_counts = quality_failure_counts(
        rows,
        classify_failure_kind=lambda artifact: str(artifact.get("failure_kind") or ""),
        quality_failure_kind="quality",
    )
    rollback_counts = rollback_failure_counts(
        rows,
        classify_failure_kind=lambda artifact: str(artifact.get("failure_kind") or ""),
        rollback_failure_kinds=frozenset({"quality", "parse"}),
    )

    assert has_diagnostic_codes(artifact_validation_text(rows[1][1]), frozenset({"TS2339"}))
    assert diagnostic_signatures(artifact_validation_text(rows[1][1])) == [
        "TS2339:Property '<symbol>' does not exist."
    ]
    assert quality_counts["total"] == 2
    assert quality_counts["consecutive"] == 0
    assert quality_counts["by_task"] == {"Task `A`": 2}
    assert quality_counts["top_signature_count"] == 2
    assert rollback_counts["total"] == 2
    assert rollback_counts["consecutive"] == 0
    assert rollback_counts["by_kind"] == {"quality": 2}
    assert recent_rollback_failure_count(
        rows[:-1],
        "Task A",
        classify_failure_kind=lambda artifact: str(artifact.get("failure_kind") or ""),
        rollback_failure_kinds=frozenset({"quality"}),
    ) == 2


def test_git_parsing_helpers_are_reusable() -> None:
    status = "\n".join(
        [
            " M ipfs_datasets_py/logic/deontic/parser.py",
            "R  old.py -> new.py",
            "?? tests/unit_tests/logic/deontic/test_parser.py",
        ]
    )
    diff = "\n".join(
        [
            "diff --git a/ipfs_datasets_py/logic/deontic/parser.py b/ipfs_datasets_py/logic/deontic/parser.py",
            "--- a/ipfs_datasets_py/logic/deontic/parser.py",
            "+++ b/ipfs_datasets_py/logic/deontic/parser.py",
            "@@ -1,2 +1,1 @@",
            "-old",
            "-line",
            "+new",
            "diff --git a/tests/unit_tests/logic/deontic/test_parser.py b/tests/unit_tests/logic/deontic/test_parser.py",
            "--- a/tests/unit_tests/logic/deontic/test_parser.py",
            "+++ b/tests/unit_tests/logic/deontic/test_parser.py",
            "@@ -1 +1,2 @@",
            " test",
            "+extra",
        ]
    )

    stats = unified_diff_stats(
        diff,
        test_file_prefixes=("tests/unit_tests/logic/deontic/",),
        production_file_prefixes=("ipfs_datasets_py/logic/deontic/",),
    )

    assert paths_from_git_status_porcelain(status) == [
        "ipfs_datasets_py/logic/deontic/parser.py",
        "new.py",
        "tests/unit_tests/logic/deontic/test_parser.py",
    ]
    assert untracked_paths_from_git_status_porcelain(status) == [
        "tests/unit_tests/logic/deontic/test_parser.py"
    ]
    assert paths_from_unified_diff(diff) == [
        "ipfs_datasets_py/logic/deontic/parser.py",
        "tests/unit_tests/logic/deontic/test_parser.py",
    ]
    assert stats["files_changed"] == 2
    assert stats["insertions"] == 2
    assert stats["deletions"] == 2
    assert stats["deletion_heavy_files"] == ["ipfs_datasets_py/logic/deontic/parser.py"]
    assert stats["production_deletion_heavy_files"] == ["ipfs_datasets_py/logic/deontic/parser.py"]
    assert stats["test_deletion_heavy_files"] == []


def test_worktree_owner_and_cleanup_helpers_are_reusable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    worktree_root = repo / ".daemon" / "worktrees"
    cycle = worktree_root / "cycle_01_20260101T000000000000Z_12345"
    repair = worktree_root / "repair_01_20260101T000000000000Z_12345"
    for index, path in enumerate((cycle, repair), start=1):
        path.mkdir(parents=True)
        owner_path = path / ".todo_owner.json"
        write_worktree_owner_file(
            owner_path,
            schema="synthetic.todo_owner",
            repo_root=repo,
            attempt=index,
            extra={"created_at_epoch": 1},
        )
        assert read_json_object(owner_path)["attempt"] == index

    calls: list[tuple[str, ...]] = []

    def fake_run_command(command, *, cwd, timeout_seconds, stdin=None):
        calls.append(tuple(command))
        if tuple(command[:3]) == ("git", "worktree", "list"):
            return CommandResult(tuple(command), 0, "", "")
        return CommandResult(tuple(command), 0, "", "")

    result = cleanup_stale_daemon_worktrees(
        repo_root=repo,
        worktree_root=worktree_root,
        stale_after_seconds=10,
        owner_filename=".todo_owner.json",
        run_command_fn=fake_run_command,
        owner_alive=lambda _pid, _repo, _worktree: False,
        now_epoch=100,
    )

    assert result["valid"] is True
    assert {Path(item["path"]).name for item in result["removed"]} == {cycle.name, repair.name}
    assert not cycle.exists()
    assert not repair.exists()
    assert owner_pid_from_worktree(Path("cycle_01_20260101T000000000000Z_54321"), {}) == 54321
    assert calls.count(("git", "worktree", "prune", "--expire", "now")) == 2
    assert ("git", "worktree", "list", "--porcelain") in calls


def test_validation_worktree_materializes_promotes_and_cleans_up(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "todo").mkdir()
    (repo / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "PLAN.md").write_text("Synthetic plan\n", encoding="utf-8")
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    external = repo / "external" / "metadata"
    external.mkdir(parents=True)
    (external / "record.txt").write_text("metadata\n", encoding="utf-8")
    spec = ValidationWorkspaceSpec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"), Path("docs/PLAN.md")),
        root_files=("package.json",),
        external_reference_paths=(Path("external/metadata"),),
        stale_seconds=0,
    )
    proposal = Proposal(files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}])

    with temporary_validation_worktree(spec) as worktree:
        assert (worktree / "example-worktree.json").exists()
        assert (worktree / "todo" / "source.py").read_text(encoding="utf-8") == "VALUE = 1\n"
        assert (worktree / "docs" / "PLAN.md").exists()
        assert (worktree / "package.json").exists()
        assert (worktree / "external" / "metadata" / "record.txt").exists()

        changed = materialize_proposal_files(proposal, worktree)
        diff = proposal_diff_from_worktree(repo, worktree, changed)

        assert changed == ["todo/source.py"]
        assert "+VALUE = 2" in diff
        promote_worktree_files(repo, worktree, changed)
        assert verify_promoted_worktree_files(repo, worktree, changed) == []

    assert not any((repo / ".daemon" / "worktrees").iterdir())


def test_supervisor_heartbeat_and_worker_watchdog_helpers_are_reusable() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    current = {
        "heartbeat_at": (now - timedelta(seconds=5)).isoformat(),
        "heartbeat_pid": 999999999,
        "phase": "requesting_worktree_edit",
        "phase_started_at": (now - timedelta(seconds=45)).isoformat(),
    }

    heartbeat = heartbeat_snapshot(current, stale_after_seconds=30, now=now)
    stale_heartbeat = heartbeat_snapshot(
        {**current, "heartbeat_at": (now - timedelta(seconds=31)).isoformat()},
        stale_after_seconds=30,
        now=now,
    )
    worker_status = worktree_phase_worker_status(
        current,
        daemon_pid=999999999,
        threshold_seconds=30,
        now=now,
    )

    assert heartbeat.age_seconds == 5
    assert heartbeat.fresh is True
    assert heartbeat.stale is False
    assert heartbeat.pid_alive is False
    assert stale_heartbeat.stale is True
    assert worker_status["required"] is True
    assert worker_status["phase"] == "requesting_worktree_edit"
    assert worker_status["phase_age_seconds"] == 45
    assert worker_status["active_worker_count"] == 0
    assert worker_status["stalled_without_active_worker"] is True


def test_supervisor_status_payload_builder_is_reusable(tmp_path: Path) -> None:
    spec = ManagedDaemonSpec(
        name="synthetic",
        schema="synthetic.todo_daemon",
        repo_root=tmp_path,
        daemon_dir=Path(".daemon"),
        runner=("python3", "-m", "synthetic.daemon"),
        status_path=Path(".daemon/status.json"),
        progress_path=Path(".daemon/progress.json"),
        supervisor_status_path=Path(".daemon/supervisor.json"),
        supervisor_pid_path=Path(".daemon/supervisor.pid"),
        child_pid_path=Path(".daemon/child.pid"),
        supervisor_out_path=Path(".daemon/supervisor.out"),
        ensure_status_path=Path(".daemon/ensure.json"),
        ensure_check_path=Path(".daemon/ensure-check.json"),
        supervisor_lock_path=Path(".daemon/supervisor.lock"),
    )

    payload = build_supervisor_status_payload(
        spec,
        status="running",
        run_id="run-1",
        log_path=".daemon/run.log",
        daemon_pid=123,
        restart_count=2,
        last_exit_code=None,
        supervisor_pid=456,
        static_fields={"watchdog_stale_after_seconds": 90},
        extra={"model_name": "gpt-5.5"},
    )

    assert payload["schema"] == "synthetic.todo_daemon.supervisor"
    assert payload["status"] == "running"
    assert payload["supervisor_pid"] == 456
    assert payload["daemon_pid"] == 123
    assert payload["restart_count"] == 2
    assert payload["current_status_path"] == ".daemon/status.json"
    assert payload["progress_path"] == ".daemon/progress.json"
    assert payload["child_pid_path"] == ".daemon/child.pid"
    assert payload["supervisor_lock_path"] == ".daemon/supervisor.lock"
    assert payload["watchdog_stale_after_seconds"] == 90
    assert payload["model_name"] == "gpt-5.5"


def test_restart_wrapper_command_builder_is_reusable() -> None:
    assert quoted_env_assignments(
        {"MODEL_NAME": "gpt 5.5", "PROVIDER": "llm_router"},
        ("MODEL_NAME", "MISSING", "PROVIDER"),
    ) == "MODEL_NAME='gpt 5.5' PROVIDER=llm_router"

    command = build_restart_loop_command(
        ("bash", "scripts/run_daemon.sh"),
        env={"MODEL_NAME": "gpt-5.5", "PROVIDER": "llm_router"},
        env_keys=("MODEL_NAME", "PROVIDER"),
        restart_delay_seconds=11,
        restart_message="legal-parser supervisor exited with code",
    )

    assert command.startswith(
        "while true; do MODEL_NAME=gpt-5.5 PROVIDER=llm_router bash scripts/run_daemon.sh; "
    )
    assert "legal-parser supervisor exited with code" in command
    assert "wrapper restarting in %ss" in command
    assert "sleep 11; done" in command


def test_supervisor_child_runtime_helpers_are_reusable(tmp_path: Path) -> None:
    run_id = supervisor_run_id(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    command = (
        "python3",
        "-c",
        "import os; print('child-ok:' + os.environ.get('EXAMPLE_DAEMON', ''))",
    )
    spec = SupervisedChildSpec(
        repo_root=tmp_path,
        command=command,
        log_path=supervised_log_path(Path(".daemon"), prefix="synthetic_child", run_id=run_id),
        child_pid_path=Path(".daemon/child.pid"),
        latest_log_path=Path(".daemon/latest.log"),
        env={"EXAMPLE_DAEMON": "todo"},
    )

    child = launch_supervised_child(spec)
    rc = wait_for_child_exit(child)

    assert run_id == "20260102T030405Z"
    assert build_python_module_command("synthetic.daemon", ("--once",), python_executable="py") == (
        "py",
        "-u",
        "-m",
        "synthetic.daemon",
        "--once",
    )
    assert RestartPolicy(restart_backoff_seconds=30, fast_restart_backoff_seconds=2).delay_for_status(
        "no_change"
    ) == 2
    assert RestartPolicy(restart_backoff_seconds=30, fast_restart_backoff_seconds=2).delay_for_status(
        "validation_failed"
    ) == 30
    assert rc == 0
    assert child.child_pid_path.read_text(encoding="utf-8").strip() == str(child.pid)
    assert child.latest_log_path is not None
    assert child.latest_log_path.is_symlink()
    assert child.latest_log_path.read_text(encoding="utf-8").strip() == "child-ok:todo"
    assert clear_child_pid_file(child) is True
    assert not child.child_pid_path.exists()


def test_python_supervisor_loop_reuses_child_runtime_and_status(tmp_path: Path) -> None:
    spec = ManagedDaemonSpec(
        name="synthetic-loop",
        schema="synthetic.todo_daemon",
        repo_root=tmp_path,
        daemon_dir=Path(".daemon"),
        runner=("python3", "-m", "synthetic.daemon"),
        status_path=Path(".daemon/child-status.json"),
        progress_path=Path(".daemon/progress.json"),
        supervisor_status_path=Path(".daemon/supervisor.json"),
        supervisor_pid_path=Path(".daemon/supervisor.pid"),
        child_pid_path=Path(".daemon/child.pid"),
        supervisor_out_path=Path(".daemon/supervisor.out"),
        ensure_status_path=Path(".daemon/ensure.json"),
        ensure_check_path=Path(".daemon/ensure-check.json"),
        supervisor_lock_path=Path(".daemon/supervisor.lock"),
        latest_log_path=Path(".daemon/latest-child.log"),
    )
    loop = SupervisorLoop(
        SupervisorLoopConfig(
            spec=spec,
            command=("python3", "-c", "print('loop-once')"),
            log_prefix="synthetic_loop",
            heartbeat_seconds=0.01,
            watchdog_startup_grace_seconds=0.0,
            max_restarts=1,
            status_static_fields={"example_supervisor": True},
        )
    )

    result = loop.run()
    supervisor_status = json.loads((tmp_path / ".daemon" / "supervisor.json").read_text(encoding="utf-8"))

    assert result.status == "child_exited"
    assert result.restart_count == 1
    assert result.last_exit_code == 0
    assert not (tmp_path / ".daemon" / "child.pid").exists()
    assert (tmp_path / ".daemon" / "latest-child.log").read_text(encoding="utf-8").strip() == "loop-once"
    assert supervisor_status["status"] == "child_exited"
    assert supervisor_status["restart_count"] == 1
    assert supervisor_status["example_supervisor"] is True


def test_file_replacement_apply_flow_promotes_only_after_validation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "todo").mkdir()
    target = repo / "todo" / "source.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)
    spec = ValidationWorkspaceSpec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"),),
    )
    accepted: list[tuple[str, str]] = []
    failed: list[tuple[str, str, str]] = []

    hooks = FileReplacementHooks(
        validate_write_path=lambda path: [] if path.startswith("todo/") else ["outside allowlist"],
        temporary_validation_worktree=lambda _config: temporary_validation_worktree(spec),
        materialize_proposal_in_worktree=lambda proposal, _config, worktree: materialize_proposal_files(
            proposal,
            worktree,
        ),
        proposal_diff_from_worktree=lambda _config, worktree, changed: proposal_diff_from_worktree(
            repo,
            worktree,
            changed,
        ),
        validation_commands_for_proposal=lambda _proposal, _config: (("synthetic-validation",),),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        worktree_config=lambda _config, worktree: SyntheticDaemonConfig(repo_root=worktree),
        syntax_preflight=lambda _worktree, _changed, _config: (
            [CommandResult(("synthetic-preflight",), 0, "ok", "")],
            [],
            "",
        ),
        has_visible_source_change=lambda changed: any(path.endswith(".py") for path in changed),
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        proposal_files_from_worktree=lambda _worktree, _changed: [],
        promote_worktree_files=lambda _config, worktree, changed: promote_worktree_files(repo, worktree, changed),
        verify_promoted_worktree_files=lambda _config, worktree, changed: verify_promoted_worktree_files(
            repo,
            worktree,
            changed,
        ),
        persist_failed_work=lambda _proposal, _config, diff_text, reason, transport: failed.append(
            (reason, transport, diff_text)
        ),
        persist_accepted_work=lambda proposal, _config, _diff_text, transport: accepted.append(
            (proposal.summary, transport)
        ),
    )

    result = build_file_replacement_apply_proposal(hooks)(
        Proposal(
            summary="Accepted reusable flow",
            files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}],
            requires_visible_source_change=True,
        ),
        config,
    )

    assert result.valid
    assert result.promotion_verified
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert accepted == [("Accepted reusable flow", "ephemeral_worktree")]
    assert failed == []


def test_file_replacement_apply_flow_rejects_disallowed_paths(tmp_path: Path) -> None:
    config = SyntheticDaemonConfig(repo_root=tmp_path)
    failed: list[tuple[str, str, str]] = []

    hooks = FileReplacementHooks(
        validate_write_path=lambda _path: ["outside allowlist"],
        temporary_validation_worktree=lambda _config: temporary_validation_worktree(
            ValidationWorkspaceSpec(repo_root=tmp_path, worktree_dir=Path(".daemon/worktrees"))
        ),
        materialize_proposal_in_worktree=lambda _proposal, _config, _worktree: [],
        proposal_diff_from_worktree=lambda _config, _worktree, _changed: "",
        validation_commands_for_proposal=lambda _proposal, _config: (),
        run_validation=lambda _config, _commands: [],
        worktree_config=lambda _config, worktree: SyntheticDaemonConfig(repo_root=worktree),
        syntax_preflight=lambda _worktree, _changed, _config: ([], [], ""),
        has_visible_source_change=lambda _changed: False,
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        proposal_files_from_worktree=lambda _worktree, _changed: [],
        promote_worktree_files=lambda _config, _worktree, _changed: None,
        verify_promoted_worktree_files=lambda _config, _worktree, _changed: [],
        persist_failed_work=lambda _proposal, _config, diff_text, reason, transport: failed.append(
            (reason, transport, diff_text)
        ),
        persist_accepted_work=lambda _proposal, _config, _diff_text, _transport: None,
    )

    result = apply_file_replacement_proposal(
        Proposal(files=[{"path": "elsewhere/source.py", "content": "bad\n"}]),
        config,
        hooks,
    )

    assert result.failure_kind == "preflight"
    assert result.errors == ["outside allowlist"]
    assert failed == [("preflight", "direct", "")]


def test_reusable_lifecycle_cli_runs_check_ensure_and_spec(tmp_path: Path, capsys) -> None:
    def build_spec(repo_root: str | None) -> ManagedDaemonSpec:
        root = Path(repo_root) if repo_root else tmp_path
        return ManagedDaemonSpec(
            name="synthetic",
            schema="synthetic.todo_daemon",
            repo_root=root,
            daemon_dir=Path(".daemon"),
            runner=("python3", "-m", "synthetic.daemon"),
            status_path=Path(".daemon/status.json"),
            progress_path=Path(".daemon/progress.json"),
            supervisor_status_path=Path(".daemon/supervisor.json"),
            supervisor_pid_path=Path(".daemon/supervisor.pid"),
            child_pid_path=Path(".daemon/child.pid"),
            supervisor_out_path=Path(".daemon/supervisor.out"),
            ensure_status_path=Path(".daemon/ensure.json"),
            ensure_check_path=Path(".daemon/ensure-check.json"),
            task_board_path=Path("todo/board.md"),
            worktree_root=Path(".daemon/worktrees"),
            launch_env={"MODEL_NAME": "gpt-5.5"},
        )

    def check_fn(spec: ManagedDaemonSpec, *, stale_after_seconds: float):
        return {
            "alive": True,
            "name": spec.name,
            "stale_after_seconds": stale_after_seconds,
        }

    ensure_seen: dict[str, object] = {}

    def ensure_fn(spec: ManagedDaemonSpec, **kwargs):
        ensure_seen.update(kwargs)
        return {
            "status": "started",
            "check": {
                "alive": True,
                "name": spec.name,
                "restart_delay_seconds": kwargs["restart_delay_seconds"],
            },
        }

    parser = build_lifecycle_arg_parser(
        description="Manage synthetic daemon.",
        default_stale_after_seconds=90,
        default_startup_wait_seconds=7,
        default_launch_mode="nohup",
        launch_mode_choices=("nohup", "tmux"),
        restart_delay_flag="--restart-delay-seconds",
        default_restart_delay_seconds=3,
        stop_description="Stop synthetic daemon.",
    )

    rc = run_lifecycle_cli(
        ["check", "--repo-root", str(tmp_path), "--stale-after-seconds", "12"],
        parser=parser,
        build_spec=build_spec,
        check_fn=check_fn,
    )
    check_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert check_payload["name"] == "synthetic"
    assert check_payload["stale_after_seconds"] == 12

    rc = run_lifecycle_cli(
        ["ensure", "--repo-root", str(tmp_path), "--restart-delay-seconds", "11"],
        parser=parser,
        build_spec=build_spec,
        ensure_fn=ensure_fn,
        ensure_restart_kw="restart_delay_seconds",
    )
    ensure_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert ensure_seen["startup_wait_seconds"] == 7
    assert ensure_seen["restart_delay_seconds"] == 11
    assert ensure_payload["restart_delay_seconds"] == 11

    rc = run_lifecycle_cli(
        ["spec", "--repo-root", str(tmp_path)],
        parser=parser,
        build_spec=build_spec,
        spec_payload_builder=lambda spec: daemon_spec_payload(spec, extra={"family": "todo"}),
    )
    spec_payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert spec_payload["family"] == "todo"
    assert spec_payload["runner"] == ["python3", "-m", "synthetic.daemon"]
    assert spec_payload["task_board_path"] == "todo/board.md"


def test_package_lifecycle_dispatcher_routes_builtin_daemons(tmp_path: Path, capsys, monkeypatch) -> None:
    for name in (
        "DAEMON_DIR",
        "STATUS_PATH",
        "PROGRESS_PATH",
        "RESULT_LOG_PATH",
        "SUPERVISOR_STATUS_PATH",
        "SUPERVISOR_PID_PATH",
        "CHILD_PID_PATH",
        "SUPERVISOR_OUT_PATH",
        "ENSURE_STATUS_PATH",
        "CHECK_LOG_PATH",
        "SUPERVISOR_LOCK_PATH",
        "LATEST_LOG_PATH",
        "TASK_BOARD_PATH",
        "WORKTREE_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    assert daemon_names() == ("legal-parser", "logic-port")

    rc = todo_daemon_package_main(["logic-port", "spec", "--repo-root", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["name"] == "logic-port"
    assert payload["schema"] == "ipfs_datasets_py.logic_port_daemon"
    assert payload["runner"] == ["bash", "ipfs_datasets_py/scripts/ops/legal_data/run_logic_port_daemon.sh"]
    assert payload["task_board_path"] == "docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md"

    rc = todo_daemon_package_main(["list"])
    listed = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert listed["daemons"] == ["legal-parser", "logic-port"]


def test_reusable_todo_daemon_module_cli_runs_hooked_daemon(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-1: Module entry task.\n", encoding="utf-8")

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    def hooks_factory(_config: TodoDaemonRuntimeConfig) -> TodoDaemonHooks:
        return TodoDaemonHooks(
            parse_tasks=parse_markdown_tasks,
            select_task=lambda tasks, _config: next(iter(tasks), None),
            replace_task_mark=replace_task_mark,
            update_generated_status=lambda markdown, latest, _tasks: markdown.rstrip()
            + f"\n\nLatest result: {latest['result']}\n",
            produce_proposal=lambda _config, _selected, _write_status: Proposal(
                summary="Accepted module task",
                files=[{"path": "todo/module-output.txt", "content": "ok\n"}],
            ),
            apply_proposal=lambda proposal, _config: Proposal(
                summary=proposal.summary,
                files=proposal.files,
                validation_results=[CommandResult(("true",), 0, "", "")],
                applied=True,
                dry_run=proposal.dry_run,
                target_task=proposal.target_task,
            ),
            run_validation=lambda _config, _proposal: [CommandResult(("true",), 0, "", "")],
            should_skip_validation=lambda _proposal: False,
            is_retryable_failure=lambda _proposal: False,
            failure_block_threshold=lambda _proposal, _config: 1,
            failure_count_for_block=lambda _config, _label: 0,
            should_sleep_between_cycles=lambda _markdown, _config: False,
            exception_diagnostic=lambda exc: str(exc),
        )

    parser = build_todo_runner_arg_parser(description="Run synthetic todo module.")
    rc = run_todo_daemon_cli(
        [
            "--repo-root",
            str(repo),
            "--task-board",
            "todo/board.md",
            "--status-file",
            "todo/status.json",
            "--progress-file",
            "todo/progress.json",
            "--result-log",
            "todo/results.jsonl",
        ],
        parser=parser,
        hooks_factory=hooks_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["iterations"] == 1
    assert payload["valid"] is True
    assert payload["latest"]["summary"] == "Accepted module task"
    assert "- [x] Task checkbox-1: Module entry task." in board.read_text(encoding="utf-8")
    assert json.loads((repo / "todo" / "status.json").read_text(encoding="utf-8"))["active_state"] == "cycle_completed"
    assert len((repo / "todo" / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_todo_daemon_runner_marks_valid_task_complete(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-1: Generic reusable task.\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    def update_generated_status(markdown: str, latest: dict[str, object], _tasks: list[Task]) -> str:
        return markdown.rstrip() + f"\n\nLatest result: {latest['result']}\n"

    def produce_proposal(
        _config: SyntheticDaemonConfig,
        _selected: Task,
        write_status,
    ) -> Proposal:
        write_status("producing_fixture", target_task=_selected.label)
        return Proposal(summary="Synthetic accepted work", files=[{"path": "todo/output.txt", "content": "ok\n"}])

    def apply_proposal(proposal: Proposal, _config: SyntheticDaemonConfig) -> Proposal:
        proposal.applied = True
        proposal.validation_results = [CommandResult(("true",), 0, "", "")]
        return proposal

    hooks = TodoDaemonHooks(
        parse_tasks=parse_markdown_tasks,
        select_task=lambda tasks, _config: next(iter(tasks), None),
        replace_task_mark=replace_task_mark,
        update_generated_status=update_generated_status,
        produce_proposal=produce_proposal,
        apply_proposal=apply_proposal,
        run_validation=lambda _config, _proposal: [CommandResult(("true",), 0, "", "")],
        should_skip_validation=lambda _proposal: False,
        is_retryable_failure=lambda _proposal: False,
        failure_block_threshold=lambda _proposal, _config: 1,
        failure_count_for_block=lambda _config, _label: 0,
        should_sleep_between_cycles=lambda _markdown, _config: False,
        exception_diagnostic=lambda exc: str(exc),
    )

    proposals = TodoDaemonRunner(config, hooks).run()
    rows = (repo / "todo" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    status = json.loads((repo / "todo" / "status.json").read_text(encoding="utf-8"))

    assert proposals[-1].valid
    assert "- [x] Task checkbox-1: Generic reusable task." in board.read_text(encoding="utf-8")
    assert len(rows) == 1
    assert status["active_state"] == "cycle_completed"


def test_file_replacement_todo_daemon_runner_uses_reusable_apply_flow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-3: Concrete file runner task.\n", encoding="utf-8")
    (repo / "todo" / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)
    spec = ValidationWorkspaceSpec(
        repo_root=repo,
        worktree_dir=Path(".daemon/worktrees"),
        marker_name="example-worktree.json",
        copy_paths=(Path("todo"),),
    )

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    runner_hooks = TodoDaemonHooks(
        parse_tasks=parse_markdown_tasks,
        select_task=lambda tasks, _config: next(iter(tasks), None),
        replace_task_mark=replace_task_mark,
        update_generated_status=lambda markdown, latest, _tasks: markdown.rstrip()
        + f"\n\nLatest result: {latest['result']}\n",
        produce_proposal=lambda _config, _selected, _write_status: Proposal(
            summary="Concrete accepted work",
            files=[{"path": "todo/source.py", "content": "VALUE = 3\n"}],
            requires_visible_source_change=True,
        ),
        apply_proposal=lambda proposal, _config: proposal,
        run_validation=lambda _config, _proposal: [CommandResult(("true",), 0, "", "")],
        should_skip_validation=lambda _proposal: False,
        is_retryable_failure=lambda _proposal: False,
        failure_block_threshold=lambda _proposal, _config: 1,
        failure_count_for_block=lambda _config, _label: 0,
        should_sleep_between_cycles=lambda _markdown, _config: False,
        exception_diagnostic=lambda exc: str(exc),
    )
    accepted: list[str] = []
    file_hooks = FileReplacementHooks(
        validate_write_path=lambda path: [] if path.startswith("todo/") else ["outside allowlist"],
        temporary_validation_worktree=lambda _config: temporary_validation_worktree(spec),
        materialize_proposal_in_worktree=lambda proposal, _config, worktree: materialize_proposal_files(
            proposal,
            worktree,
        ),
        proposal_diff_from_worktree=lambda _config, worktree, changed: proposal_diff_from_worktree(
            repo,
            worktree,
            changed,
        ),
        validation_commands_for_proposal=lambda _proposal, _config: (("synthetic-validation",),),
        run_validation=lambda _config, commands: [CommandResult(commands[0], 0, "ok", "")],
        worktree_config=lambda _config, worktree: SyntheticDaemonConfig(repo_root=worktree),
        syntax_preflight=lambda _worktree, _changed, _config: (
            [CommandResult(("synthetic-preflight",), 0, "ok", "")],
            [],
            "",
        ),
        has_visible_source_change=lambda changed: any(path.endswith(".py") for path in changed),
        attempt_validation_repair=lambda proposal, _config, _worktree: (False, proposal.changed_files, ""),
        proposal_files_from_worktree=lambda _worktree, _changed: [],
        promote_worktree_files=lambda _config, worktree, changed: promote_worktree_files(repo, worktree, changed),
        verify_promoted_worktree_files=lambda _config, worktree, changed: verify_promoted_worktree_files(
            repo,
            worktree,
            changed,
        ),
        persist_failed_work=lambda _proposal, _config, _diff_text, _reason, _transport: None,
        persist_accepted_work=lambda proposal, _config, _diff_text, _transport: accepted.append(
            proposal.summary
        ),
    )

    proposals = run_todo_daemon(
        config,
        runner_factory=lambda runner_config: FileReplacementTodoDaemonRunner(
            runner_config,
            runner_hooks,
            file_hooks,
        ),
    )
    proposal = proposals[0]
    payload = todo_daemon_proposals_payload(proposals)

    assert proposal.valid
    assert payload[0]["summary"] == "Concrete accepted work"
    assert accepted == ["Concrete accepted work"]
    assert (repo / "todo" / "source.py").read_text(encoding="utf-8") == "VALUE = 3\n"
    assert "- [x] Task checkbox-3: Concrete file runner task." in board.read_text(encoding="utf-8")


def test_todo_daemon_runner_pre_task_block_marks_task_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    board = repo / "todo" / "board.md"
    board.parent.mkdir(parents=True)
    board.write_text("- [ ] Task checkbox-2: Blocked before work.\n", encoding="utf-8")
    config = SyntheticDaemonConfig(repo_root=repo)

    def replace_task_mark(markdown: str, selected: Task, mark: str) -> str:
        return re.sub(
            r"- \[[ xX~!]\] " + re.escape(selected.label),
            f"- [{mark}] " + selected.label,
            markdown,
            count=1,
        )

    hooks = TodoDaemonHooks(
        parse_tasks=parse_markdown_tasks,
        select_task=lambda tasks, _config: next(iter(tasks), None),
        replace_task_mark=replace_task_mark,
        update_generated_status=lambda markdown, latest, _tasks: markdown.rstrip()
        + f"\n\nLatest result: {latest['result']}\n",
        produce_proposal=lambda _config, _selected, _write_status: Proposal(summary="should not run"),
        apply_proposal=lambda proposal, _config: proposal,
        run_validation=lambda _config, _proposal: [],
        should_skip_validation=lambda _proposal: True,
        is_retryable_failure=lambda _proposal: False,
        failure_block_threshold=lambda _proposal, _config: 1,
        failure_count_for_block=lambda _config, _label: 0,
        should_sleep_between_cycles=lambda _markdown, _config: False,
        exception_diagnostic=lambda exc: str(exc),
        pre_task_block=lambda _config, _task: PreTaskBlock(
            summary="Blocked before work.",
            failure_kind="pre_task_block",
            result="blocked_before_work",
        ),
    )

    proposal = TodoDaemonRunner(config, hooks).run()[0]

    assert proposal.failure_kind == "pre_task_block"
    assert "- [!] Task checkbox-2: Blocked before work." in board.read_text(encoding="utf-8")
