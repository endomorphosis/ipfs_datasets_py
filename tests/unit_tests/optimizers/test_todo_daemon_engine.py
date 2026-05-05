from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ipfs_datasets_py.optimizers.todo_daemon import (
    CommandResult,
    PathPolicy,
    PreTaskBlock,
    Proposal,
    Task,
    TodoDaemonHooks,
    TodoDaemonRunner,
    ValidationWorkspaceSpec,
    materialize_proposal_files,
    parse_json_proposal,
    parse_markdown_tasks,
    proposal_diff_from_worktree,
    promote_worktree_files,
    select_task,
    temporary_validation_worktree,
    verify_promoted_worktree_files,
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
