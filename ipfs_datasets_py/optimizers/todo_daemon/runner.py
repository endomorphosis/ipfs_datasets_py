"""Reusable hook-driven runner for optimizer todo daemons."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from .engine import CommandResult, Proposal, Task, append_jsonl, atomic_write_json, read_text, utc_now
from .status import (
    ActiveStatusSnapshot,
    advance_active_status_snapshot,
    build_active_status_payload,
)


StatusWriter = Callable[..., None]


@dataclass(frozen=True)
class PreTaskBlock:
    """Decision returned by a daemon-specific pre-work circuit breaker."""

    summary: str
    failure_kind: str
    result: str
    mark: str = "!"


@dataclass(frozen=True)
class TodoDaemonHooks:
    """Domain hooks needed by the generic todo-daemon runner."""

    parse_tasks: Callable[[str], list[Task]]
    select_task: Callable[[Iterable[Task], Any], Optional[Task]]
    replace_task_mark: Callable[[str, Task, str], str]
    update_generated_status: Callable[[str, dict[str, Any], list[Task]], str]
    produce_proposal: Callable[[Any, Task, StatusWriter], Proposal]
    apply_proposal: Callable[[Proposal, Any], Proposal]
    run_validation: Callable[[Any, Proposal], list[CommandResult]]
    should_skip_validation: Callable[[Proposal], bool]
    is_retryable_failure: Callable[[Proposal], bool]
    failure_block_threshold: Callable[[Proposal, Any], int]
    failure_count_for_block: Callable[[Any, str], int]
    should_sleep_between_cycles: Callable[[str, Any], bool]
    exception_diagnostic: Callable[[BaseException], str]
    pre_task_block: Callable[[Any, Task], Optional[PreTaskBlock]] = lambda _config, _task: None
    no_eligible_summary: str = "No eligible todo daemon tasks remain."
    exception_summary: str = "Daemon cycle crashed before completion."
    exception_impact: str = (
        "The exception was captured as a durable diagnostic so watch mode can continue "
        "and the supervisor can inspect the failure history."
    )


class TodoDaemonRunner:
    """Reusable status, heartbeat, progress, and task-board loop for todo daemons."""

    def __init__(self, config: Any, hooks: TodoDaemonHooks) -> None:
        self.config = config
        self.hooks = hooks
        self._heartbeat_stop = threading.Event()
        self._active_status = ActiveStatusSnapshot(started_at=utc_now())

    def write_status(self, state: str, **extra: Any) -> None:
        now = utc_now()
        if state != "heartbeat":
            target_task = None
            if "target_task" in extra:
                target_task = str(extra.get("target_task") or "")
            self._active_status = advance_active_status_snapshot(
                self._active_status,
                state=state,
                now=now,
                target_task=target_task,
            )
        payload = build_active_status_payload(
            state=state,
            snapshot=self._active_status,
            now=now,
            pid=os.getpid(),
            extra=extra,
        )
        atomic_write_json(self.config.resolve(self.config.status_file), payload)

    def heartbeat(self) -> None:
        while not self._heartbeat_stop.wait(self.config.heartbeat_seconds):
            self.write_status("heartbeat", active_state=self._active_status.state)

    def run_cycle(self) -> Proposal:
        board_path = self.config.resolve(self.config.task_board)
        board = read_text(board_path)
        tasks = self.hooks.parse_tasks(board)
        selected = self.hooks.select_task(tasks, self.config)
        if selected is None:
            proposal = Proposal(summary=self.hooks.no_eligible_summary, failure_kind="no_eligible_tasks")
            proposal.dry_run = not self.config.apply
            self.write_status("no_eligible_tasks", target_task="")
            self.write_progress([proposal])
            self.write_cycle_diagnostic(proposal, stage="no_eligible_tasks")
            return proposal

        self.write_status("selected_task", target_task=selected.label)
        pre_task_block = self.hooks.pre_task_block(self.config, selected)
        if (
            self.config.apply
            and selected.status in {"needed", "in-progress"}
            and pre_task_block is not None
        ):
            proposal = Proposal(
                summary=pre_task_block.summary,
                failure_kind=pre_task_block.failure_kind,
                target_task=selected.label,
            )
            proposal.dry_run = False
            board = self.hooks.replace_task_mark(board, selected, pre_task_block.mark)
            tasks_after = self.hooks.parse_tasks(board)
            board = self.hooks.update_generated_status(
                board,
                {
                    "target_task": selected.label,
                    "result": pre_task_block.result,
                    "summary": proposal.summary,
                },
                tasks_after,
            )
            board_path.write_text(board, encoding="utf-8")
            self.write_progress([proposal])
            append_jsonl(
                self.config.resolve(self.config.result_log),
                {"created_at": utc_now(), "proposal": proposal.to_dict()},
            )
            self.write_status("cycle_completed", valid=False, artifact=proposal.to_dict())
            return proposal

        if selected.status == "needed" and self.config.apply:
            board = self.hooks.replace_task_mark(board, selected, "~")
            board_path.write_text(board, encoding="utf-8")

        proposal = self.hooks.produce_proposal(self.config, selected, self.write_status)
        proposal.target_task = selected.label
        proposal.dry_run = not self.config.apply
        if proposal.failure_kind in {"parse", "llm"} or not proposal.files:
            self.write_progress([proposal])
            self.write_cycle_diagnostic(proposal, stage="before_validation")

        if self.config.apply and proposal.files:
            self.write_status("applying_files", target_task=selected.label)
            proposal = self.hooks.apply_proposal(proposal, self.config)
        elif self.hooks.should_skip_validation(proposal):
            proposal.validation_results = []
        else:
            proposal.validation_results = self.hooks.run_validation(self.config, proposal)

        board = read_text(board_path)
        if self.config.apply:
            if proposal.valid:
                board = self.hooks.replace_task_mark(board, selected, "x")
            elif selected.status in {"needed", "in-progress"} and not self.hooks.is_retryable_failure(proposal):
                prior_failures = self.hooks.failure_count_for_block(self.config, selected.label)
                mark = "!" if prior_failures + 1 >= self.hooks.failure_block_threshold(proposal, self.config) else " "
                board = self.hooks.replace_task_mark(board, selected, mark)
            elif selected.status in {"needed", "in-progress"}:
                board = self.hooks.replace_task_mark(board, selected, " ")
        tasks_after = self.hooks.parse_tasks(board)
        board = self.hooks.update_generated_status(
            board,
            {
                "target_task": selected.label,
                "result": "accepted" if proposal.valid else proposal.failure_kind or "not_applied",
                "summary": proposal.summary,
            },
            tasks_after,
        )
        board_path.write_text(board, encoding="utf-8")
        self.write_progress([proposal])
        append_jsonl(self.config.resolve(self.config.result_log), {"created_at": utc_now(), "proposal": proposal.to_dict()})
        self.write_status("cycle_completed", valid=proposal.valid, artifact=proposal.to_dict())
        return proposal

    def write_cycle_diagnostic(self, proposal: Proposal, *, stage: str) -> None:
        append_jsonl(
            self.config.resolve(self.config.result_log),
            {
                "created_at": utc_now(),
                "stage": stage,
                "diagnostic": proposal.to_dict(),
            },
        )

    def record_cycle_exception(self, exc: BaseException, *, consecutive_exceptions: int) -> Proposal:
        proposal = Proposal(
            summary=self.hooks.exception_summary,
            impact=self.hooks.exception_impact,
            errors=[self.hooks.exception_diagnostic(exc)],
            failure_kind="daemon_exception",
            target_task=self._active_status.target_task,
        )
        proposal.dry_run = not self.config.apply
        proposal.applied = False
        artifact = proposal.to_dict()
        try:
            self.write_progress([proposal])
        except Exception as progress_exc:
            artifact["progress_error"] = self.hooks.exception_diagnostic(progress_exc)
        try:
            self.write_cycle_diagnostic(proposal, stage="cycle_exception")
        except Exception:
            pass
        try:
            self.write_status(
                "cycle_exception",
                valid=False,
                consecutive_exceptions=consecutive_exceptions,
                artifact=artifact,
            )
        except Exception:
            pass
        return proposal

    def write_progress(self, proposals: list[Proposal]) -> None:
        board = read_text(self.config.resolve(self.config.task_board))
        tasks = self.hooks.parse_tasks(board)
        payload = {
            "updated_at": utc_now(),
            "task_counts": {
                "needed": sum(1 for task in tasks if task.status == "needed"),
                "in_progress": sum(1 for task in tasks if task.status == "in-progress"),
                "complete": sum(1 for task in tasks if task.status == "complete"),
                "blocked": sum(1 for task in tasks if task.status == "blocked"),
            },
            "latest": proposals[-1].to_dict() if proposals else {},
        }
        atomic_write_json(self.config.resolve(self.config.progress_file), payload)

    def run(self) -> list[Proposal]:
        thread = threading.Thread(target=self.heartbeat, daemon=True)
        thread.start()
        proposals: list[Proposal] = []
        try:
            count = 0
            consecutive_exceptions = 0
            while True:
                count += 1
                try:
                    proposal = self.run_cycle()
                    consecutive_exceptions = 0
                except KeyboardInterrupt:
                    raise
                except BaseException as exc:
                    consecutive_exceptions += 1
                    proposal = self.record_cycle_exception(
                        exc,
                        consecutive_exceptions=consecutive_exceptions,
                    )
                proposals.append(proposal)
                if not self.config.watch:
                    break
                if proposal.failure_kind == "no_eligible_tasks":
                    break
                if self.config.iterations > 0 and count >= self.config.iterations:
                    break
                if proposal.failure_kind == "daemon_exception":
                    if self.config.crash_backoff_seconds > 0:
                        time.sleep(self.config.crash_backoff_seconds)
                    continue
                if self.config.interval_seconds > 0:
                    board_now = read_text(self.config.resolve(self.config.task_board))
                    if not self.hooks.should_sleep_between_cycles(board_now, self.config):
                        continue
                    self.write_status("sleeping", seconds=self.config.interval_seconds)
                    time.sleep(self.config.interval_seconds)
        finally:
            self._heartbeat_stop.set()
            thread.join(timeout=1)
        return proposals
