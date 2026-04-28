"""Daemon for iteratively porting Python logic requirements to TypeScript.

The daemon is intentionally conservative:

- it uses :mod:`ipfs_datasets_py.optimizers.common` session tooling;
- it calls ``ipfs_datasets_py.llm_router.generate_text`` with ``gpt-5.5`` by
  default;
- it accepts patches only as unified diffs and applies them with ``git apply``;
- it runs a configured validation command list after each applied patch;
- it never executes arbitrary shell commands returned by the model.

This is development tooling for the repository. It does not add a runtime
server dependency to the browser-native TypeScript logic port.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
)
from ipfs_datasets_py.optimizers.common.log_schema_v3 import (
    log_error,
    log_iteration_complete,
    log_iteration_started,
    log_session_complete,
    log_session_start,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_PLAN_DOCS = (
    "docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md",
)

DEFAULT_STATUS_DOCS = (
    "docs/LOGIC_PORT_PARITY.md",
)

DEFAULT_VALIDATION_COMMANDS = (
    ("npx", "tsc", "--noEmit"),
    ("npm", "run", "validate:logic-port"),
)

JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)
DIFF_BLOCK_RE = re.compile(r"```(?:diff|patch)\s*([\s\S]*?)\s*```", re.IGNORECASE)
TASK_HEADING_RE = re.compile(r"^### Task\s+([^:\n]+):\s+(.+)$", re.MULTILINE)
CHECKBOX_TASK_RE = re.compile(r"^(?P<indent>\s*)-\s+\[(?P<mark>[ xX~!])\]\s+(?P<title>.+)$", re.MULTILINE)
DAEMON_TASK_BOARD_RE = re.compile(
    r"\n?<!-- logic-port-daemon-task-board:start -->[\s\S]*?<!-- logic-port-daemon-task-board:end -->\n?",
    re.MULTILINE,
)
FORBIDDEN_PATCH_SNIPPETS = (
    "from 'vitest'",
    'from "vitest"',
    "from '@jest/globals'",
    'from "@jest/globals"',
)

ALLOWED_WRITE_PREFIXES = (
    "src/lib/logic/",
    "docs/",
    "ipfs_datasets_py/docs/logic/",
)


@dataclass(frozen=True)
class CommandResult:
    """Result from a validation or git command."""

    command: Tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def compact(self, limit: int = 6000) -> Dict[str, Any]:
        return {
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout[-limit:],
            "stderr": self.stderr[-limit:],
        }


@dataclass(frozen=True)
class PlanTask:
    """Task extracted from a markdown implementation plan."""

    task_id: str
    title: str
    status: str

    @property
    def label(self) -> str:
        return f"Task {self.task_id}: {self.title}"


@dataclass
class LogicPortDaemonConfig:
    """Configuration for the logic-port daemon."""

    repo_root: Path = field(default_factory=lambda: Path.cwd())
    plan_docs: Tuple[Path, ...] = field(default_factory=lambda: tuple(Path(p) for p in DEFAULT_PLAN_DOCS))
    status_docs: Tuple[Path, ...] = field(default_factory=lambda: tuple(Path(p) for p in DEFAULT_STATUS_DOCS))
    typescript_logic_dir: Path = Path("src/lib/logic")
    python_logic_dir: Path = Path("ipfs_datasets_py/ipfs_datasets_py/logic")
    model_name: str = "gpt-5.5"
    provider: Optional[str] = None
    max_iterations: int = 1
    interval_seconds: float = 0.0
    target_score: float = 0.99
    dry_run: bool = True
    validation_commands: Tuple[Tuple[str, ...], ...] = DEFAULT_VALIDATION_COMMANDS
    max_prompt_chars: int = 50000
    max_patch_lines: int = 180
    command_timeout_seconds: int = 600
    max_new_tokens: int = 4096
    temperature: float = 0.1
    allow_local_fallback: bool = False
    llm_timeout_seconds: int = 900
    retry_interval_seconds: float = 300.0
    max_failure_cycles: int = 0
    result_log_path: Optional[Path] = None
    codex_trace_dir: Optional[Path] = Path("ipfs_datasets_py/.daemon/codex-runs")
    failed_patch_dir: Path = Path("ipfs_datasets_py/.daemon/failed-patches")
    patch_repair_attempts: int = 1
    task_board_doc: Optional[Path] = Path("docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md")
    update_task_board: bool = True

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


@dataclass
class LogicPortArtifact:
    """Patch proposal plus validation state for one daemon iteration."""

    summary: str = ""
    patch: str = ""
    tasks: List[str] = field(default_factory=list)
    files: List[Dict[str, str]] = field(default_factory=list)
    validation_commands: List[List[str]] = field(default_factory=list)
    raw_response: str = ""
    applied: bool = False
    dry_run: bool = True
    validation_results: List[CommandResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)

    @property
    def validation_passed(self) -> bool:
        return bool(self.validation_results) and all(result.ok for result in self.validation_results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "tasks": self.tasks,
            "has_patch": bool(self.patch.strip()),
            "files": [item.get("path", "") for item in self.files],
            "applied": self.applied,
            "dry_run": self.dry_run,
            "validation_passed": self.validation_passed,
            "validation_results": [result.compact() for result in self.validation_results],
            "errors": self.errors,
            "changed_files": self.changed_files,
        }


def _read_text(path: Path, *, limit: Optional[int] = None) -> str:
    text = path.read_text(encoding="utf-8")
    if limit is not None and len(text) > limit:
        return text[:limit] + "\n\n[truncated]\n"
    return text


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    match = JSON_BLOCK_RE.search(text)
    candidates = [match.group(1)] if match else []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def parse_llm_patch_response(text: str) -> LogicPortArtifact:
    """Parse a model response into a patch artifact.

    Preferred response format is JSON with ``summary`` and ``patch`` fields.
    A fenced diff block is accepted as a fallback to make manual testing easy.
    """

    parsed = _extract_json_object(text)
    if parsed is not None:
        validation_commands = parsed.get("validation_commands", [])
        safe_commands: List[List[str]] = []
        if isinstance(validation_commands, list):
            for command in validation_commands:
                if isinstance(command, list) and all(isinstance(part, str) for part in command):
                    safe_commands.append(command)

        return LogicPortArtifact(
            summary=str(parsed.get("summary", "")),
            patch=str(parsed.get("patch", "")),
            files=_parse_file_edits(parsed.get("files", [])),
            tasks=[str(item) for item in parsed.get("tasks", []) if isinstance(item, (str, int, float))],
            validation_commands=safe_commands,
            raw_response=text,
        )

    diff_match = DIFF_BLOCK_RE.search(text)
    if diff_match:
        return LogicPortArtifact(summary="Patch extracted from fenced diff block.", patch=diff_match.group(1), raw_response=text)

    return LogicPortArtifact(raw_response=text, errors=["LLM response did not contain JSON or a fenced diff patch."])


def _parse_file_edits(value: Any) -> List[Dict[str, str]]:
    edits: List[Dict[str, str]] = []
    if not isinstance(value, list):
        return edits
    for item in value:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        content = item.get("content")
        if isinstance(path, str) and isinstance(content, str):
            edits.append({"path": path, "content": content})
    return edits


def _strip_daemon_task_board(text: str) -> str:
    return DAEMON_TASK_BOARD_RE.sub("\n", text).rstrip() + "\n"


def _status_from_task_block(block: str) -> str:
    status_match = re.search(r"^Status:\s*(.+)$", block, re.MULTILINE)
    if not status_match:
        return "needed"
    status = status_match.group(1).strip().lower()
    if "implemented" in status and "partially" not in status:
        return "complete"
    if "partial" in status or "in progress" in status:
        return "in-progress"
    if "blocked" in status:
        return "blocked"
    return "needed"


def _status_from_checkbox(mark: str) -> str:
    if mark.lower() == "x":
        return "complete"
    if mark == "~":
        return "in-progress"
    if mark == "!":
        return "blocked"
    return "needed"


def _clean_checkbox_title(title: str) -> str:
    return re.sub(r"\s+<!--.*?-->\s*$", "", title).strip()


def _replace_checkbox_mark(markdown: str, task: PlanTask, mark: str) -> str:
    if not task.task_id.startswith("checkbox-"):
        return markdown
    try:
        target_index = int(task.task_id.removeprefix("checkbox-"))
    except ValueError:
        return markdown

    current_index = 0
    lines = markdown.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = CHECKBOX_TASK_RE.match(line.rstrip("\n"))
        if not match:
            continue
        current_index += 1
        if current_index == target_index:
            lines[index] = re.sub(r"^(\s*-\s+\[)[ xX~!](\]\s+)", rf"\g<1>{mark}\2", line, count=1)
            break
    return "".join(lines)


def _patch_changed_files(patch: str) -> List[str]:
    paths: List[str] = []
    seen = set()
    for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", patch, re.MULTILINE):
        path = match.group(2).strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def extract_plan_tasks(markdown: str) -> List[PlanTask]:
    """Extract ordered implementation tasks from the markdown plan."""

    text = _strip_daemon_task_board(markdown)
    matches = list(TASK_HEADING_RE.finditer(text))
    tasks: List[PlanTask] = []
    for index, match in enumerate(matches):
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[block_start:block_end]
        tasks.append(
            PlanTask(
                task_id=match.group(1).strip(),
                title=match.group(2).strip(),
                status=_status_from_task_block(block),
            )
        )
    if tasks:
        return tasks

    for index, match in enumerate(CHECKBOX_TASK_RE.finditer(text), start=1):
        title = _clean_checkbox_title(match.group("title"))
        if not title:
            continue
        tasks.append(
            PlanTask(
                task_id=f"checkbox-{index}",
                title=title,
                status=_status_from_checkbox(match.group("mark")),
            )
        )
    return tasks


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    stdin: Optional[str] = None,
) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return CommandResult(tuple(command), completed.returncode, completed.stdout, completed.stderr)


class LogicPortDaemonOptimizer(BaseOptimizer):
    """Optimizer-backed daemon that asks an LLM for safe repository patches."""

    def __init__(
        self,
        daemon_config: Optional[LogicPortDaemonConfig] = None,
        *,
        llm_router: Optional[Any] = None,
        optimizer_config: Optional[OptimizerConfig] = None,
    ) -> None:
        daemon_config = daemon_config or LogicPortDaemonConfig()
        base_config = optimizer_config or OptimizerConfig(
            max_iterations=daemon_config.max_iterations,
            target_score=daemon_config.target_score,
            validation_enabled=True,
            early_stopping=False,
        )
        super().__init__(config=base_config, llm_backend=llm_router)
        self.daemon_config = daemon_config
        self.llm_router = llm_router

    def generate(self, input_data: Any, context: OptimizationContext) -> LogicPortArtifact:
        prompt = self._build_prompt(input_data=input_data, context=context)
        response = self._call_llm(prompt)
        artifact = parse_llm_patch_response(response)
        artifact.dry_run = self.daemon_config.dry_run
        return artifact

    def critique(self, artifact: LogicPortArtifact, context: OptimizationContext) -> Tuple[float, List[str]]:
        feedback: List[str] = []
        score = 0.0

        if artifact.errors:
            feedback.extend(artifact.errors)
        if artifact.patch.strip():
            score += 0.25
        else:
            feedback.append("No patch was proposed.")
        if artifact.applied or artifact.dry_run:
            score += 0.25
        else:
            feedback.append("Patch was not applied.")
        if artifact.validation_results:
            passed = sum(1 for result in artifact.validation_results if result.ok)
            score += 0.5 * (passed / len(artifact.validation_results))
            for result in artifact.validation_results:
                if not result.ok:
                    feedback.append(f"Validation failed: {' '.join(result.command)}")
        else:
            feedback.append("Validation has not run yet.")

        return min(score, 1.0), feedback

    def optimize(
        self,
        artifact: LogicPortArtifact,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> LogicPortArtifact:
        if not artifact.patch.strip() and not artifact.files:
            return artifact

        if self.daemon_config.dry_run:
            artifact.validation_results = self._run_validation()
            return artifact

        preflight_errors = self._preflight_artifact(artifact)
        if preflight_errors:
            artifact.errors.extend(preflight_errors)
            return artifact

        if artifact.files:
            try:
                artifact.applied, artifact.validation_results, changed_files = self._apply_file_edits_with_validation(artifact.files)
            except Exception as exc:
                artifact.errors.append(str(exc))
                return artifact
            if not artifact.applied:
                artifact.errors.append("File edits failed validation and were rolled back.")
            else:
                artifact.changed_files = changed_files
            return artifact

        if not artifact.patch.strip():
            return artifact

        check = run_command(
            ("git", "apply", "--check", "-"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=self.daemon_config.command_timeout_seconds,
            stdin=artifact.patch,
        )
        if not check.ok:
            self._persist_failed_patch(artifact.patch, check, context=context)
            repaired = self._repair_patch(artifact.patch, check, context=context)
            if repaired.strip() and repaired != artifact.patch:
                artifact.patch = repaired
                check = run_command(
                    ("git", "apply", "--check", "-"),
                    cwd=self.daemon_config.repo_root,
                    timeout_seconds=self.daemon_config.command_timeout_seconds,
                    stdin=artifact.patch,
                )
                if not check.ok:
                    self._persist_failed_patch(artifact.patch, check, context=context)
            if not check.ok:
                artifact.errors.append("Patch failed git apply --check.")
                artifact.validation_results.append(check)
                return artifact

        applied = run_command(
            ("git", "apply", "-"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=self.daemon_config.command_timeout_seconds,
            stdin=artifact.patch,
        )
        artifact.validation_results.append(applied)
        artifact.applied = applied.ok
        if not applied.ok:
            artifact.errors.append("Patch failed git apply.")
            return artifact

        artifact.validation_results.extend(self._run_validation())
        if not artifact.validation_passed:
            rolled_back = self._rollback_patch(artifact.patch)
            artifact.validation_results.extend(rolled_back)
            if all(result.ok for result in rolled_back):
                artifact.applied = False
                artifact.errors.append("Patch failed validation and was rolled back.")
            else:
                artifact.errors.append("Patch failed validation and automatic rollback failed.")
        else:
            artifact.changed_files = _patch_changed_files(artifact.patch)
        return artifact

    def validate(self, artifact: LogicPortArtifact, context: OptimizationContext) -> bool:
        if artifact.dry_run:
            return (bool(artifact.patch.strip()) or bool(artifact.files)) and not artifact.errors
        if artifact.files:
            return artifact.applied and not artifact.errors
        return artifact.applied and artifact.validation_passed and not artifact.errors

    def run_once(self, *, session_id: Optional[str] = None) -> Dict[str, Any]:
        session_id = session_id or f"logic-port-{uuid.uuid4()}"
        context = OptimizationContext(
            session_id=session_id,
            input_data={},
            domain="logic-port",
            constraints={
                "model_name": self.daemon_config.model_name,
                "dry_run": self.daemon_config.dry_run,
            },
        )
        result = self.run_session({}, context)
        artifact = result.get("artifact")
        if isinstance(artifact, LogicPortArtifact):
            result["artifact"] = artifact.to_dict()
        return dict(result)

    def run_daemon(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        session_id = f"logic-port-daemon-{uuid.uuid4()}"
        log_session_start(
            LOGGER,
            session_id=session_id,
            domain="logic-port",
            input_size=sum(
                len(_read_text(self.daemon_config.resolve(path)))
                for path in [*self.daemon_config.plan_docs, *self.daemon_config.status_docs]
                if self.daemon_config.resolve(path).exists()
            ),
            config={
                "model_name": self.daemon_config.model_name,
                "max_iterations": self.daemon_config.max_iterations,
                "dry_run": self.daemon_config.dry_run,
            },
            component=self.__class__.__name__,
        )
        started = time.time()

        try:
            for iteration in range(self.daemon_config.max_iterations):
                iteration_started = time.time()
                log_iteration_started(
                    LOGGER,
                    session_id=session_id,
                    iteration=iteration + 1,
                    current_score=float(results[-1].get("score", 0.0)) if results else 0.0,
                    feedback_count=0,
                    component=self.__class__.__name__,
                )
                result = self.run_once(session_id=f"{session_id}-{iteration + 1}")
                results.append(result)
                score = float(result.get("score", 0.0))
                valid = bool(result.get("valid", False))
                log_iteration_complete(
                    LOGGER,
                    session_id=session_id,
                    iteration=iteration + 1,
                    score=score,
                    score_delta=score - (float(results[-2].get("score", 0.0)) if len(results) > 1 else 0.0),
                    execution_time_ms=(time.time() - iteration_started) * 1000,
                    component=self.__class__.__name__,
                )
                if valid and score >= self.daemon_config.target_score:
                    break
                if self.daemon_config.interval_seconds > 0 and iteration < self.daemon_config.max_iterations - 1:
                    time.sleep(self.daemon_config.interval_seconds)
        except Exception as exc:
            log_error(LOGGER, "logic_port_daemon_failed", error_msg=str(exc), session_id=session_id, component=self.__class__.__name__)
            results.append(
                {
                    "artifact": {
                        "summary": "Daemon failed before producing a valid patch.",
                        "tasks": [],
                        "has_patch": False,
                        "applied": False,
                        "dry_run": self.daemon_config.dry_run,
                        "validation_passed": False,
                        "validation_results": [],
                        "errors": [str(exc)],
                    },
                    "score": 0.0,
                    "iterations": len(results),
                    "valid": False,
                    "metadata": {
                        "model_name": self.daemon_config.model_name,
                        "provider": self._resolved_provider() or "auto",
                    },
                }
            )
        finally:
            final_score = float(results[-1].get("score", 0.0)) if results else 0.0
            final_valid = bool(results[-1].get("valid", False)) if results else False
            log_session_complete(
                LOGGER,
                session_id=session_id,
                domain="logic-port",
                iterations=len(results),
                final_score=final_score,
                valid=final_valid,
                execution_time_ms=(time.time() - started) * 1000,
                component=self.__class__.__name__,
            )
            self._update_task_board(results)
        return results

    def run_supervised(self, *, cycles: int = 0) -> List[Dict[str, Any]]:
        """Run daemon cycles without user input.

        Args:
            cycles: Number of cycles to run. ``0`` means run until externally
                stopped. Each cycle runs :meth:`run_daemon`.

        Returns:
            Aggregated results for bounded runs. For unbounded runs this only
            returns when interrupted or when ``max_failure_cycles`` is reached.
        """

        all_results: List[Dict[str, Any]] = []
        failure_cycles = 0
        completed_cycles = 0

        while cycles <= 0 or completed_cycles < cycles:
            completed_cycles += 1
            cycle_results = self.run_daemon()
            all_results.extend(cycle_results)
            self._append_result_log(cycle_results)
            cycle_valid = bool(cycle_results and cycle_results[-1].get("valid"))
            if cycle_valid:
                failure_cycles = 0
            else:
                failure_cycles += 1
                if self.daemon_config.max_failure_cycles and failure_cycles >= self.daemon_config.max_failure_cycles:
                    break

            if cycles > 0 and completed_cycles >= cycles:
                break

            if self.daemon_config.retry_interval_seconds > 0:
                time.sleep(self.daemon_config.retry_interval_seconds)

        return all_results

    def _append_result_log(self, results: List[Dict[str, Any]]) -> None:
        if self.daemon_config.result_log_path is None:
            return
        path = self.daemon_config.resolve(self.daemon_config.result_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "results": results}, default=str))
            handle.write("\n")

    def _update_task_board(self, results: List[Dict[str, Any]]) -> None:
        if self.daemon_config.dry_run or not self.daemon_config.update_task_board or self.daemon_config.task_board_doc is None:
            return

        path = self.daemon_config.resolve(self.daemon_config.task_board_doc)
        if not path.exists():
            return

        original = path.read_text(encoding="utf-8")
        task_text = _strip_daemon_task_board(original)
        tasks_before = extract_plan_tasks(task_text)
        if not tasks_before:
            return

        latest = results[-1] if results else {}
        latest_valid = bool(latest.get("valid"))
        latest_target = self._select_next_plan_task(tasks_before)
        if latest_valid and latest_target is not None:
            task_text = _replace_checkbox_mark(task_text, latest_target, "x")

        tasks_after = extract_plan_tasks(task_text)
        current_target = self._select_next_plan_task(tasks_after)
        board = self._render_task_board(tasks_after, current_target=current_target, latest_target=latest_target, results=results)
        updated = task_text.rstrip() + "\n\n" + board + "\n"
        path.write_text(updated, encoding="utf-8")

    def _select_next_plan_task(self, tasks: List[PlanTask]) -> Optional[PlanTask]:
        for status in ("needed", "in-progress", "blocked"):
            for task in tasks:
                if task.status == status:
                    return task
        return tasks[0] if tasks else None

    def _render_task_board(
        self,
        tasks: List[PlanTask],
        *,
        current_target: Optional[PlanTask],
        latest_target: Optional[PlanTask],
        results: List[Dict[str, Any]],
    ) -> str:
        latest = results[-1] if results else {}
        latest_artifact = latest.get("artifact", {}) if isinstance(latest.get("artifact"), dict) else {}
        latest_valid = bool(latest.get("valid"))
        latest_summary = str(latest_artifact.get("summary") or "No summary")
        latest_errors = latest_artifact.get("errors") or []
        latest_changed_files = [str(path) for path in latest_artifact.get("changed_files", []) if str(path)]
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        current_target_label = self._markdown_task_label(current_target) if current_target else "none"
        latest_target_label = self._markdown_task_label(latest_target) if latest_target else "none"

        lines = [
            "<!-- logic-port-daemon-task-board:start -->",
            "## Daemon Task Board",
            "",
            f"Last updated: {timestamp}",
            "",
            "Selection policy: choose the first port-plan checkbox that is not marked complete, keep the daemon scoped to that task, and update this board after every daemon round.",
            "",
            f"Current target: `{current_target_label}`",
            "",
            "Legend: `[ ]` needed, `[~]` in progress, `[x]` complete, `[!]` blocked or failing.",
            "",
            "### Checklist",
            "",
        ]

        for task in tasks:
            marker = {"complete": "[x]", "in-progress": "[~]", "blocked": "[!]"}.get(task.status, "[ ]")
            note = task.status
            if latest_target and task.task_id == latest_target.task_id:
                if latest_valid:
                    marker = "[x]"
                    note = "validated by latest daemon round"
                elif latest:
                    marker = "[!]"
                    note = "latest daemon round failed validation or preflight"
                else:
                    marker = "[~]"
                    note = "selected for next daemon round"
            lines.append(f"- {marker} `{self._markdown_task_label(task)}` - {note}")

        lines.extend(
            [
                "",
                "### Latest Round",
                "",
                f"- Target: `{latest_target_label}`",
                f"- Result: `{'valid' if latest_valid else 'needs follow-up'}`",
                f"- Summary: {latest_summary}",
            ]
        )
        if latest_changed_files:
            lines.append(f"- Accepted changed files: {', '.join(f'`{path}`' for path in latest_changed_files)}")
        if latest_errors:
            lines.append(f"- Errors: {'; '.join(str(error) for error in latest_errors[:3])}")

        lines.extend(
            [
                "",
                "### Required Daemon Behavior",
                "",
                "- Work only on the current port-plan target unless the task is already complete in code and tests.",
                "- If a round fails, keep the task marked as needing follow-up and use the validation error as the next-cycle constraint.",
                "- Mark a task complete only after TypeScript validation and logic-port tests pass for the accepted change.",
                "- Keep browser runtime changes TypeScript/WASM-native with no server or Python service dependency.",
                "<!-- logic-port-daemon-task-board:end -->",
            ]
        )
        return "\n".join(lines)

    def _markdown_task_label(self, task: Optional[PlanTask]) -> str:
        return task.label.replace("`", "'") if task else "none"

    def _safe_edit_path(self, raw_path: str) -> Path:
        if not raw_path or raw_path.startswith("/") or ".." in Path(raw_path).parts:
            raise ValueError(f"Unsafe file edit path: {raw_path!r}")
        normalized = raw_path.replace("\\", "/")
        if not any(normalized.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES):
            raise ValueError(f"File edit path is outside daemon allowlist: {raw_path!r}")
        return self.daemon_config.resolve(Path(normalized))

    def _apply_file_edits_with_validation(self, edits: List[Dict[str, str]]) -> Tuple[bool, List[CommandResult], List[str]]:
        originals: Dict[Path, Optional[str]] = {}
        touched: List[Path] = []
        for edit in edits:
            path = self._safe_edit_path(edit["path"])
            if path not in originals:
                originals[path] = path.read_text(encoding="utf-8") if path.exists() else None
            touched.append(path)

        try:
            for edit in edits:
                path = self._safe_edit_path(edit["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(edit["content"], encoding="utf-8")
            self._format_file_edits(touched)
            validation_results = self._run_validation()
            changed_files = sorted({str(path.relative_to(self.daemon_config.repo_root)) for path in touched})
            return all(result.ok for result in validation_results), validation_results, changed_files
        finally:
            validation_results = locals().get("validation_results")
            if not validation_results or not all(result.ok for result in validation_results):
                for path, original in originals.items():
                    if original is None:
                        try:
                            path.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        path.write_text(original, encoding="utf-8")

    def _format_file_edits(self, paths: List[Path]) -> None:
        ts_paths = [str(path.relative_to(self.daemon_config.repo_root)) for path in paths if path.suffix in {".ts", ".tsx"}]
        if not ts_paths:
            return
        run_command(
            ("npx", "prettier", "--write", *ts_paths),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=120,
        )

    def _preflight_artifact(self, artifact: LogicPortArtifact) -> List[str]:
        errors: List[str] = []
        candidates = [artifact.patch, *(edit.get("content", "") for edit in artifact.files)]
        for snippet in FORBIDDEN_PATCH_SNIPPETS:
            if any(snippet in candidate for candidate in candidates):
                errors.append(
                    f"Rejected proposal because it imports {snippet}; logic tests use Jest globals without test-framework imports."
                )
        return errors

    def _rollback_patch(self, patch: str) -> List[CommandResult]:
        check = run_command(
            ("git", "apply", "-R", "--check", "-"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=self.daemon_config.command_timeout_seconds,
            stdin=patch,
        )
        results = [check]
        if not check.ok:
            return results
        results.append(
            run_command(
                ("git", "apply", "-R", "-"),
                cwd=self.daemon_config.repo_root,
                timeout_seconds=self.daemon_config.command_timeout_seconds,
                stdin=patch,
            )
        )
        return results

    def _persist_failed_patch(self, patch: str, result: CommandResult, *, context: OptimizationContext) -> None:
        path = self.daemon_config.resolve(self.daemon_config.failed_patch_dir)
        path.mkdir(parents=True, exist_ok=True)
        stem = f"{context.session_id}-{int(time.time())}"
        (path / f"{stem}.patch").write_text(patch, encoding="utf-8")
        (path / f"{stem}.json").write_text(json.dumps(result.compact(limit=12000), indent=2), encoding="utf-8")

    def _repair_patch(self, patch: str, result: CommandResult, *, context: OptimizationContext) -> str:
        attempts = max(0, int(self.daemon_config.patch_repair_attempts))
        if attempts <= 0:
            return patch
        repair_prompt = f"""Repair this unified diff so it applies cleanly to the current repository.

Return ONLY JSON with this shape:
{{
  "summary": "short repair description",
  "tasks": ["patch repair"],
  "patch": "corrected unified diff",
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Rules:
- Preserve the original intent.
- Do not add server calls or Python runtime dependencies to browser TypeScript.
- Fix malformed hunk counts, bad context, truncated hunks, and stale file context.
- The patch must be a valid unified diff accepted by git apply.

Session: {context.session_id}
git apply error:
{result.stderr or result.stdout}

Original patch:
{patch}
"""
        try:
            repaired = parse_llm_patch_response(self._call_llm(repair_prompt))
        except Exception as exc:
            LOGGER.warning("patch repair call failed: %s", exc)
            return patch
        if repaired.errors or not repaired.patch.strip():
            return patch
        return repaired.patch

    def _call_llm(self, prompt: str) -> str:
        provider = self._resolved_provider()
        if self.llm_router is not None:
            generator = getattr(self.llm_router, "generate_text", None)
            if callable(generator):
                return str(
                    generator(
                        prompt,
                        model_name=self.daemon_config.model_name,
                        provider=provider,
                        allow_local_fallback=self.daemon_config.allow_local_fallback,
                        max_new_tokens=self.daemon_config.max_new_tokens,
                        temperature=self.daemon_config.temperature,
                        timeout=self.daemon_config.llm_timeout_seconds,
                        trace=bool(self.daemon_config.codex_trace_dir),
                        trace_dir=str(self.daemon_config.resolve(self.daemon_config.codex_trace_dir)) if self.daemon_config.codex_trace_dir else None,
                    )
                )
            generator = getattr(self.llm_router, "generate", None)
            if callable(generator):
                return str(
                    generator(
                        prompt,
                        model_name=self.daemon_config.model_name,
                        max_new_tokens=self.daemon_config.max_new_tokens,
                        temperature=self.daemon_config.temperature,
                        timeout=self.daemon_config.llm_timeout_seconds,
                        trace=bool(self.daemon_config.codex_trace_dir),
                        trace_dir=str(self.daemon_config.resolve(self.daemon_config.codex_trace_dir)) if self.daemon_config.codex_trace_dir else None,
                    )
                )

        from ipfs_datasets_py import llm_router

        try:
            text = str(
                llm_router.generate_text(
                    prompt,
                    model_name=self.daemon_config.model_name,
                    provider=provider,
                    allow_local_fallback=self.daemon_config.allow_local_fallback,
                    max_new_tokens=self.daemon_config.max_new_tokens,
                    temperature=self.daemon_config.temperature,
                    timeout=self.daemon_config.llm_timeout_seconds,
                    trace=bool(self.daemon_config.codex_trace_dir),
                    trace_dir=str(self.daemon_config.resolve(self.daemon_config.codex_trace_dir)) if self.daemon_config.codex_trace_dir else None,
                )
            )
        except Exception as exc:
            raise RuntimeError(
                f"llm_router could not generate with model={self.daemon_config.model_name!r} "
                f"provider={provider or 'auto'!r}. Configure the provider credentials or pass --provider. "
                f"Original error: {exc}"
            ) from exc
        trace_getter = getattr(llm_router, "get_last_generation_trace", None)
        if callable(trace_getter):
            trace = trace_getter()
            if isinstance(trace, dict) and trace.get("effective_provider_name") == "local_hf":
                raise RuntimeError(
                    "llm_router resolved to local_hf fallback; configure a real gpt-5.5 provider or pass an explicit provider."
                )
        return text

    def _resolved_provider(self) -> Optional[str]:
        if self.daemon_config.provider:
            return self.daemon_config.provider
        if self.daemon_config.model_name.strip().lower().startswith("gpt-"):
            return "codex_cli"
        return None

    def _build_prompt(self, *, input_data: Any, context: OptimizationContext) -> str:
        doc_sections = []
        budget = self.daemon_config.max_prompt_chars
        plan_tasks: List[PlanTask] = []
        for path in [*self.daemon_config.plan_docs, *self.daemon_config.status_docs]:
            resolved = self.daemon_config.resolve(path)
            if not resolved.exists():
                continue
            text = _read_text(resolved, limit=max(2000, budget // 4))
            doc_sections.append(f"## {path}\n{text}")
            if self.daemon_config.task_board_doc is not None and resolved == self.daemon_config.resolve(self.daemon_config.task_board_doc):
                plan_tasks = extract_plan_tasks(resolved.read_text(encoding="utf-8"))

        selected_task = self._select_next_plan_task(plan_tasks)
        selected_task_text = selected_task.label if selected_task else "No markdown task could be selected."

        git_status = run_command(
            ("git", "status", "--short"),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=30,
        )
        file_inventory = run_command(
            ("git", "ls-files", str(self.daemon_config.typescript_logic_dir), str(self.daemon_config.python_logic_dir)),
            cwd=self.daemon_config.repo_root,
            timeout_seconds=30,
        )

        prompt = f"""You are implementing the browser-native TypeScript/WASM port of ipfs_datasets_py logic.

Use the TypeScript port plan as the controlling roadmap. The deterministic parser plans are not this daemon's task ledger.
Goal: improve parity with the Python logic module while preserving browser-native runtime constraints.

Hard constraints:
- Do not add server-side runtime calls to the TypeScript logic library.
- Do not wrap Python services from browser code.
- Prefer deterministic TypeScript or WASM-compatible implementations.
- Preserve existing tests and add focused tests for each change.
- Use the existing Jest test harness. Test files should rely on global describe/it/expect and must not import vitest or @jest/globals.
- Prefer adding cases to an existing matching *.test.ts file over creating a new test file.
- Return a unified diff patch only for files in this repository.
- Do not include shell commands that mutate files.
- Use conservative, PR-sized changes.
- Choose one narrow requirement per cycle.
- The daemon-selected task for this cycle is: {selected_task_text}
- Work only on that daemon-selected task unless the repository already satisfies it; if it is already satisfied, update docs/tests for that task rather than jumping ahead.
- Prefer implementation changes under src/lib/logic/ whenever the selected task asks for functionality, not only docs.
- Fixture-only work is acceptable only when the selected port-plan checkbox explicitly asks for fixtures or generated Python parity captures.
- For accepted work, the changed files must be directly usable by the TypeScript port validation suite.
- Limit the patch to at most {self.daemon_config.max_patch_lines} changed diff lines.
- Prefer one implementation file plus one focused test file.
- Do not include prose inside the patch string.
- Generate the patch against the exact current file contents shown by repository status and tracked-file inventory.
- Use valid unified-diff hunk headers and include enough unchanged context for git apply.
- If you cannot produce a patch that git apply will accept, return an empty patch with a clear summary.

Return ONLY JSON with this shape:
{{
  "summary": "short description",
  "tasks": ["requirement addressed"],
  "patch": "unified diff string, or empty if using files",
  "files": [
    {{"path": "src/lib/logic/example.ts", "content": "complete replacement file content"}}
  ],
  "validation_commands": [["npx", "tsc", "--noEmit"], ["npm", "run", "validate:logic-port"]]
}}

Prefer "files" over "patch" for TypeScript/doc changes. Use complete file contents, not snippets.
Only use paths under src/lib/logic/, docs/, or ipfs_datasets_py/docs/logic/.
Session: {context.session_id}
Model requested by daemon: {self.daemon_config.model_name}
Provider requested by daemon: {self._resolved_provider() or "auto"}
Dry run: {self.daemon_config.dry_run}

Current git status:
{git_status.stdout}
{git_status.stderr}

Relevant tracked files:
{file_inventory.stdout[-12000:]}

Documents:
{chr(10).join(doc_sections)}
"""
        if len(prompt) > budget:
            return prompt[:budget] + "\n\n[daemon prompt truncated]\n"
        return prompt

    def _run_validation(self) -> List[CommandResult]:
        results: List[CommandResult] = []
        for command in self.daemon_config.validation_commands:
            results.append(
                run_command(
                    command,
                    cwd=self.daemon_config.repo_root,
                    timeout_seconds=self.daemon_config.command_timeout_seconds,
                )
            )
            if not results[-1].ok:
                break
        return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Iteratively improve the TypeScript ipfs_datasets_py logic port.")
    parser.add_argument("--repo-root", default=".", help="Repository root containing package.json and ipfs_datasets_py/")
    parser.add_argument("--model", default="gpt-5.5", help="llm_router model name")
    parser.add_argument("--provider", default=None, help="Optional llm_router provider")
    parser.add_argument("--iterations", type=int, default=1, help="Maximum daemon iterations")
    parser.add_argument("--interval", type=float, default=0.0, help="Seconds to sleep between iterations")
    parser.add_argument("--apply", action="store_true", help="Apply model-generated patches. Default is dry-run.")
    parser.add_argument("--watch", action="store_true", help="Run continuously without user input.")
    parser.add_argument("--cycles", type=int, default=0, help="Cycles for --watch; 0 means unlimited.")
    parser.add_argument("--retry-interval", type=float, default=300.0, help="Seconds between supervised daemon cycles.")
    parser.add_argument("--max-failure-cycles", type=int, default=0, help="Stop --watch after N failed cycles; 0 means unlimited.")
    parser.add_argument("--log-file", default=None, help="Optional file for JSON results from each daemon invocation.")
    parser.add_argument("--skip-validation", action="store_true", help="Do not run validation commands")
    parser.add_argument("--validation-command", action="append", default=[], help="Validation command, shell-split by spaces")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    validation_commands: Tuple[Tuple[str, ...], ...]
    if args.skip_validation:
        validation_commands = tuple()
    elif args.validation_command:
        validation_commands = tuple(tuple(command.split()) for command in args.validation_command)
    else:
        validation_commands = DEFAULT_VALIDATION_COMMANDS

    config = LogicPortDaemonConfig(
        repo_root=Path(args.repo_root).resolve(),
        model_name=args.model,
        provider=args.provider,
        max_iterations=max(1, args.iterations),
        interval_seconds=max(0.0, args.interval),
        dry_run=not args.apply,
        validation_commands=validation_commands,
        retry_interval_seconds=max(0.0, args.retry_interval),
        max_failure_cycles=max(0, args.max_failure_cycles),
        result_log_path=Path(args.log_file) if args.log_file else None,
    )
    optimizer = LogicPortDaemonOptimizer(config)
    results = optimizer.run_supervised(cycles=max(0, args.cycles)) if args.watch else optimizer.run_daemon()
    if args.log_file and not args.watch:
        optimizer._append_result_log(results)
    print(json.dumps(results, indent=2, default=str))
    return 0 if results and bool(results[-1].get("valid")) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
