from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.optimizers.todo_daemon import (
    CommandResult,
    FileReplacementHooks,
    FileReplacementTodoDaemonRunner,
    ManagedDaemonSpec,
    PathPolicy,
    PreTaskBlock,
    Proposal,
    Task,
    TodoDaemonHooks,
    TodoDaemonRunner,
    TodoDaemonRuntimeConfig,
    ValidationWorkspaceSpec,
    apply_file_replacement_proposal,
    build_lifecycle_arg_parser,
    build_todo_runner_arg_parser,
    daemon_spec_payload,
    materialize_proposal_files,
    parse_json_proposal,
    parse_markdown_tasks,
    proposal_diff_from_worktree,
    promote_worktree_files,
    run_lifecycle_cli,
    run_todo_daemon_cli,
    select_task,
    temporary_validation_worktree,
    verify_promoted_worktree_files,
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


def test_command_result_compaction_omits_html_and_provider_tokens() -> None:
    compacted = CommandResult(
        command=("example",),
        returncode=1,
        stdout="<html><body><script>challenge</script></body></html>",
        stderr="token __cf_chl_tk=secret",
    ).compact()

    assert "challenge" not in compacted["stdout"]
    assert "__cf_chl_tk=secret" not in compacted["stderr"]


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

    result = apply_file_replacement_proposal(
        Proposal(
            summary="Accepted reusable flow",
            files=[{"path": "todo/source.py", "content": "VALUE = 2\n"}],
            requires_visible_source_change=True,
        ),
        config,
        hooks,
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

    proposal = FileReplacementTodoDaemonRunner(config, runner_hooks, file_hooks).run()[0]

    assert proposal.valid
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
