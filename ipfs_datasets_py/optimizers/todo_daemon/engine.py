"""Reusable task-board and validation-worktree engine for todo daemons."""

from __future__ import annotations

import difflib
import json
import os
import re
import signal
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, Sequence


DEFAULT_CHECKBOX_RE = re.compile(r"^(?P<prefix>\s*-\s+\[)(?P<mark>[ xX~!])(?P<suffix>\]\s+)(?P<title>.+)$")
JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_text(path: Path, limit: Optional[int] = None) -> str:
    text = path.read_text(encoding="utf-8")
    if limit is not None and len(text) > limit:
        return text[:limit] + "\n\n[truncated]\n"
    return text


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str, sort_keys=True) + "\n")


def compact_message(value: Any, limit: int = 700) -> str:
    text = str(value or "")
    text = re.sub(
        r"<!doctype html[\s\S]*",
        "[html response omitted]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<(?:html|head|body|script|style|svg|path|div|meta|noscript)\b[\s\S]*",
        "[html response omitted]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"__cf_chl_[A-Za-z0-9_.=-]+", "__cf_chl_[omitted]", text)
    text = re.sub(r"c[A-Z][A-Za-z0-9_]*:\s*'[^']{80,}'", "cloudflare_token: '[omitted]'", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


@dataclass(frozen=True)
class Task:
    index: int
    title: str
    status: str
    checkbox_id: int

    @property
    def label(self) -> str:
        return f"Task checkbox-{self.checkbox_id}: {self.title}"


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def compact(self, limit: int = 5000) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": compact_message(self.stdout, limit=limit),
            "stderr": compact_message(self.stderr, limit=limit),
        }


def command_result_from_object(result: Any) -> CommandResult:
    """Return a shared ``CommandResult`` from an object or mapping payload."""

    if isinstance(result, Mapping):
        command = result.get("command", ())
        returncode = result.get("returncode")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        valid = result.get("valid")
    else:
        command = getattr(result, "command", ())
        returncode = getattr(result, "returncode", None)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        valid = getattr(result, "valid", None)
    if not isinstance(command, (list, tuple)):
        command = ()
    try:
        normalized_returncode = int(returncode)
    except (TypeError, ValueError):
        normalized_returncode = 0 if valid is True else 1
    return CommandResult(
        command=tuple(str(part) for part in command),
        returncode=normalized_returncode,
        stdout=str(stdout or ""),
        stderr=str(stderr or ""),
    )


def command_results_from_objects(results: Iterable[Any]) -> list[CommandResult]:
    """Return shared ``CommandResult`` entries from command-result-like objects."""

    return [command_result_from_object(result) for result in results]


def command_runner_from_legacy_function(
    run_command_fn: Callable[..., Any],
    *,
    timeout_parameter: str = "timeout",
    stdin_parameter: str = "input_text",
) -> Callable[..., CommandResult]:
    """Adapt a dict/object-returning command runner to the shared command-runner API."""

    def run_command_adapter(
        command: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int = 60,
        stdin: str | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        kwargs: dict[str, Any] = {"cwd": cwd, timeout_parameter: timeout_seconds}
        stdin_value = input_text if input_text is not None else stdin
        if stdin_parameter and stdin_value is not None:
            kwargs[stdin_parameter] = stdin_value
        return command_result_from_object(run_command_fn(command, **kwargs))

    return run_command_adapter


@dataclass
class Proposal:
    summary: str = ""
    impact: str = ""
    files: list[dict[str, str]] = field(default_factory=list)
    validation_commands: list[list[str]] = field(default_factory=list)
    raw_response: str = ""
    errors: list[str] = field(default_factory=list)
    failure_kind: str = ""
    target_task: str = ""
    changed_files: list[str] = field(default_factory=list)
    validation_results: list[CommandResult] = field(default_factory=list)
    applied: bool = False
    dry_run: bool = True
    trusted_validation_commands: bool = False
    requires_visible_source_change: bool = False
    promotion_verified: bool = False
    promotion_errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.applied and not self.errors and all(result.ok for result in self.validation_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "impact": self.impact,
            "target_task": self.target_task,
            "files": [item.get("path", "") for item in self.files],
            "changed_files": self.changed_files,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "validation_passed": bool(self.validation_results) and all(result.ok for result in self.validation_results),
            "validation_results": [result.compact() for result in self.validation_results],
            "errors": [compact_message(error) for error in self.errors],
            "failure_kind": self.failure_kind,
            "trusted_validation_commands": self.trusted_validation_commands,
            "requires_visible_source_change": self.requires_visible_source_change,
            "promotion_verified": self.promotion_verified,
            "promotion_errors": [compact_message(error) for error in self.promotion_errors],
        }


@dataclass(frozen=True)
class PathPolicy:
    allowed_write_prefixes: tuple[str, ...]
    disallowed_write_prefixes: tuple[str, ...] = ()
    private_write_path_fragments: tuple[str, ...] = ()
    private_write_path_tokens: frozenset[str] = frozenset()
    runtime_only_change_paths: frozenset[str] = frozenset()
    ignored_visible_prefixes: tuple[str, ...] = ()
    visible_source_prefixes: tuple[str, ...] = ()
    visible_source_suffixes: tuple[str, ...] = (".py", ".ts", ".tsx", ".json", ".md")

    def validate_write_path(self, path: str, *, daemon_label: str = "todo daemon") -> list[str]:
        errors: list[str] = []
        try:
            normalized = normalized_relative_path(path)
        except ValueError as exc:
            return [str(exc)]
        if any(normalized.startswith(prefix) for prefix in self.disallowed_write_prefixes):
            errors.append(f"disallowed {daemon_label} write target: {normalized}")
        if not any(
            normalized.startswith(prefix) or normalized == prefix.rstrip("/")
            for prefix in self.allowed_write_prefixes
        ):
            errors.append(f"write target is outside {daemon_label} allowlist: {normalized}")
        if self.is_private_write_path(normalized):
            errors.append(f"private/session artifacts may not be generated by {daemon_label} proposals: {normalized}")
        return errors

    def is_private_write_path(self, normalized: str) -> bool:
        lowered = normalized.lower()
        if any(fragment in lowered for fragment in self.private_write_path_fragments):
            return True
        tokens = [token for token in re.split(r"[/._-]+", lowered) if token]
        return any(token in self.private_write_path_tokens for token in tokens)

    def has_visible_source_change(self, changed_files: Iterable[str]) -> bool:
        for path in changed_files:
            normalized = Path(path).as_posix()
            if normalized in self.runtime_only_change_paths:
                continue
            if any(normalized.startswith(prefix) for prefix in self.ignored_visible_prefixes):
                continue
            if (
                any(normalized.startswith(prefix) for prefix in self.visible_source_prefixes)
                and normalized.endswith(self.visible_source_suffixes)
            ):
                return True
        return False


@dataclass(frozen=True)
class ValidationWorkspaceSpec:
    repo_root: Path
    worktree_dir: Path
    marker_name: str = "todo-worktree.json"
    copy_paths: tuple[Path, ...] = ()
    root_files: tuple[str, ...] = ()
    external_reference_paths: tuple[Path, ...] = ()
    ignore: Optional[Callable[[str, list[str]], set[str]]] = None
    stale_seconds: int = 7200

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


def repo_relative_copy_paths(repo_root: Path, paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return non-empty copy paths as repo-relative paths when possible."""

    resolved_root = repo_root.resolve()
    copy_paths: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.as_posix() in {"", "."}:
            continue
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(resolved_root)
            except ValueError:
                continue
        if path.as_posix() in {"", "."}:
            continue
        copy_paths.append(path)
    return tuple(copy_paths)


def build_validation_workspace_spec(
    *,
    repo_root: Path,
    worktree_dir: Path,
    marker_name: str = "todo-worktree.json",
    copy_paths: Iterable[Path] = (),
    root_files: Iterable[str] = (),
    external_reference_paths: Iterable[Path] = (),
    ignore: Optional[Callable[[str, list[str]], set[str]]] = None,
    stale_seconds: int = 7200,
) -> ValidationWorkspaceSpec:
    """Build a validation-worktree spec with normalized daemon copy paths."""

    return ValidationWorkspaceSpec(
        repo_root=repo_root,
        worktree_dir=worktree_dir,
        marker_name=marker_name,
        copy_paths=repo_relative_copy_paths(repo_root, copy_paths),
        root_files=tuple(str(path) for path in root_files if str(path)),
        external_reference_paths=tuple(Path(path) for path in external_reference_paths if Path(path).as_posix()),
        ignore=ignore,
        stale_seconds=int(stale_seconds),
    )


def parse_markdown_tasks(
    markdown: str,
    *,
    checkbox_re: re.Pattern[str] = DEFAULT_CHECKBOX_RE,
) -> list[Task]:
    tasks: list[Task] = []
    for line in markdown.splitlines():
        match = checkbox_re.match(line)
        if not match:
            continue
        mark = match.group("mark")
        raw_title = match.group("title").strip()
        checkbox_id = len(tasks) + 1
        title = raw_title
        id_match = re.match(r"Task checkbox-(?P<id>\d+):\s*(?P<title>.+)$", raw_title)
        if id_match:
            checkbox_id = int(id_match.group("id"))
            title = id_match.group("title").strip()
        status = "needed"
        if mark.lower() == "x":
            status = "complete"
        elif mark == "~":
            status = "in-progress"
        elif mark == "!":
            status = "blocked"
        tasks.append(Task(index=len(tasks) + 1, title=title, status=status, checkbox_id=checkbox_id))
    return tasks


def select_task(
    tasks: Iterable[Task],
    *,
    revisit_blocked: bool = False,
    protected_blocked_checkbox_ids: Iterable[int] = (),
) -> Optional[Task]:
    task_list = list(tasks)
    for task in task_list:
        if task.status in {"needed", "in-progress"}:
            return task
    if revisit_blocked:
        protected = set(protected_blocked_checkbox_ids)
        for task in task_list:
            if task.status == "blocked" and task.checkbox_id not in protected:
                return task
    return None


def extract_json(text: str) -> Optional[dict[str, Any]]:
    match = JSON_BLOCK_RE.search(text)
    candidates = [match.group(1)] if match else []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    for event_candidate in extract_codex_event_text_candidates(stripped):
        candidates.append(event_candidate)
        event_match = JSON_BLOCK_RE.search(event_candidate)
        if event_match:
            candidates.append(event_match.group(1))
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


def extract_codex_event_text_candidates(text: str) -> list[str]:
    """Extract assistant text candidates from Codex JSONL event streams."""

    candidates: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        for value in (
            extract_text_from_codex_event_object(event),
            extract_text_from_codex_event_object(event.get("item")),
            extract_text_from_codex_event_object(event.get("message")),
        ):
            if value:
                candidates.append(value)
    return list(reversed(candidates))


def extract_text_from_codex_event_object(value: Any) -> str:
    """Return assistant text from one Codex event-like object, if present."""

    if not isinstance(value, dict):
        return ""
    value_type = value.get("type")
    if value_type in {"agent_message", "assistant_message"} and isinstance(value.get("text"), str):
        return value["text"].strip()
    if value_type == "message" and value.get("role") == "assistant":
        content = value.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if (
                    isinstance(item, dict)
                    and item.get("type") in {"text", "output_text"}
                    and isinstance(item.get("text"), str)
                ):
                    parts.append(item["text"])
            return "".join(parts).strip()
        if isinstance(value.get("text"), str):
            return value["text"].strip()
    return ""


def looks_like_empty_codex_event_stream(text: str) -> bool:
    """Return whether a JSONL response contains Codex events but no assistant text."""

    if not text.strip():
        return False
    saw_codex_event = False
    saw_assistant_text = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type.startswith(("thread.", "turn.", "item.")):
            saw_codex_event = True
        if (
            extract_text_from_codex_event_object(event)
            or extract_text_from_codex_event_object(event.get("item"))
            or extract_text_from_codex_event_object(event.get("message"))
        ):
            saw_assistant_text = True
    return saw_codex_event and not saw_assistant_text


def normalize_file_edits(value: Any) -> list[dict[str, str]]:
    """Return valid complete-file edits from a JSON-like proposal value."""

    edits: list[dict[str, str]] = []
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


def normalize_string_items(
    value: Any,
    *,
    accepted_scalar_types: tuple[type[Any], ...] = (str,),
) -> list[str]:
    """Return scalar proposal items normalized to strings."""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, accepted_scalar_types)]


def normalize_string_item_lists(value: Any) -> list[list[str]]:
    """Return nested all-string proposal item lists."""

    if not isinstance(value, list):
        return []
    return [
        list(command)
        for command in value
        if isinstance(command, list) and all(isinstance(part, str) for part in command)
    ]


def normalize_validation_commands(value: Any) -> list[list[str]]:
    """Return valid validation commands from a JSON-like proposal value."""

    return normalize_string_item_lists(value)


def normalize_task_references(value: Any) -> list[str]:
    """Return string task references from a JSON-like proposal value."""

    return normalize_string_items(value, accepted_scalar_types=(str, int, float))


def parse_json_proposal(text: str) -> Proposal:
    parsed = extract_json(text)
    if parsed is None:
        return Proposal(raw_response=text, errors=["LLM response did not contain a JSON object."], failure_kind="parse")
    return Proposal(
        summary=str(parsed.get("summary", "")),
        impact=str(parsed.get("impact", "")),
        files=normalize_file_edits(parsed.get("files", [])),
        validation_commands=normalize_validation_commands(parsed.get("validation_commands", [])),
        raw_response=text,
    )


def normalized_relative_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError(f"absolute paths are not allowed: {path}")
    normalized = candidate.as_posix()
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        raise ValueError(f"path traversal is not allowed: {path}")
    return normalized


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
    stdin: Optional[str] = None,
) -> CommandResult:
    """Run a command with captured output and process-group timeout cleanup."""

    effective_timeout = timeout_seconds if timeout_seconds is not None else timeout
    if effective_timeout is None:
        raise TypeError("run_command() requires timeout or timeout_seconds")
    process: Optional[subprocess.Popen[str]] = None
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdin=subprocess.PIPE if stdin is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(input=stdin, timeout=effective_timeout)
        return CommandResult(tuple(command), process.returncode, stdout or "", stderr or "")
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
            try:
                stdout_after, stderr_after = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                stdout_after, stderr_after = process.communicate()
            stdout = stdout_after or exc.stdout or ""
            stderr = stderr_after or exc.stderr or ""
        else:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
        stdout = stdout if isinstance(stdout, str) else stdout.decode("utf-8", errors="replace")
        stderr = stderr if isinstance(stderr, str) else stderr.decode("utf-8", errors="replace")
        timeout_message = f"Command timed out after {effective_timeout}s"
        return CommandResult(tuple(command), 124, stdout or "", (stderr + "\n" + timeout_message).strip())


def validation_commands_for_proposal(
    proposal: Proposal,
    default_commands: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    """Return trusted proposal validation commands or daemon defaults."""

    if proposal.trusted_validation_commands and proposal.validation_commands:
        return tuple(tuple(command) for command in proposal.validation_commands)
    return tuple(tuple(command) for command in default_commands)


def run_validation_commands(
    *,
    repo_root: Path,
    commands: Sequence[Sequence[str]],
    timeout_seconds: int,
    run_command_fn: Callable[..., CommandResult] = run_command,
) -> list[CommandResult]:
    """Run validation commands with the shared timeout-aware command runner."""

    results: list[CommandResult] = []
    for command in commands:
        try:
            results.append(
                run_command_fn(tuple(command), cwd=repo_root, timeout_seconds=timeout_seconds)
            )
        except TypeError as exc:
            if "timeout_seconds" not in str(exc):
                raise
            results.append(run_command_fn(tuple(command), cwd=repo_root, timeout=timeout_seconds))
    return results


def diff_for_file(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def copy_if_exists(
    source: Path,
    destination: Path,
    *,
    ignore: Optional[Callable[[str, list[str]], set[str]]] = None,
) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True, ignore=ignore)
    else:
        shutil.copy2(source, destination)


def link_or_copy_if_exists(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.symlink_to(source.resolve(), target_is_directory=source.is_dir())
    except OSError:
        copy_if_exists(source, destination)


def worktree_marker_payload(*, state: str, source_root: Path) -> dict[str, Any]:
    return {
        "created_at": utc_now(),
        "schema_version": 1,
        "source_root": source_root.as_posix(),
        "state": state,
        "transport": "ephemeral_worktree",
    }


def cleanup_stale_validation_worktrees(
    worktree_root: Path,
    *,
    marker_name: str = "todo-worktree.json",
    max_age_seconds: int = 7200,
) -> list[str]:
    if not worktree_root.exists():
        return []
    cutoff = time.time() - float(max_age_seconds)
    removed: list[str] = []
    for child in worktree_root.iterdir():
        marker = child / marker_name
        if not child.is_dir() or not marker.exists():
            continue
        try:
            if child.stat().st_mtime > cutoff:
                continue
            shutil.rmtree(child)
            removed.append(child.name)
        except FileNotFoundError:
            continue
    return removed


@contextmanager
def temporary_validation_worktree(spec: ValidationWorkspaceSpec) -> Iterator[Path]:
    cleanup_stale_validation_worktrees(
        spec.resolve(spec.worktree_dir),
        marker_name=spec.marker_name,
        max_age_seconds=spec.stale_seconds,
    )
    root = spec.resolve(spec.worktree_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    worktree = root / f"cycle-{stamp}-{uuid.uuid4().hex[:8]}"
    worktree.mkdir(parents=True)
    marker = worktree / spec.marker_name
    marker.write_text(
        json.dumps(worktree_marker_payload(state="initializing", source_root=spec.repo_root), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    try:
        for rel in spec.copy_paths:
            copy_if_exists(spec.resolve(rel), worktree / rel, ignore=spec.ignore)
        for root_file in spec.root_files:
            copy_if_exists(spec.repo_root / root_file, worktree / root_file)
        for rel in spec.external_reference_paths:
            link_or_copy_if_exists(spec.resolve(rel), worktree / rel)
        marker.write_text(
            json.dumps(worktree_marker_payload(state="ready", source_root=spec.repo_root), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        yield worktree
    finally:
        try:
            shutil.rmtree(worktree)
        except FileNotFoundError:
            pass


def materialize_proposal_files(proposal: Proposal, worktree: Path) -> list[str]:
    changed: list[str] = []
    seen: set[str] = set()
    for item in proposal.files:
        rel = normalized_relative_path(item["path"])
        target = worktree / rel
        before = target.read_text(encoding="utf-8") if target.exists() else None
        after = item["content"]
        if before == after:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(after, encoding="utf-8")
        if rel not in seen:
            seen.add(rel)
            changed.append(rel)
    return changed


def proposal_files_from_worktree(worktree: Path, changed: Iterable[str]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for rel in changed:
        target = worktree / rel
        if target.exists():
            files.append({"path": rel, "content": target.read_text(encoding="utf-8")})
    return files


def proposal_diff_from_worktree(repo_root: Path, worktree: Path, changed: Iterable[str]) -> str:
    parts: list[str] = []
    for rel in changed:
        source = repo_root / rel
        candidate = worktree / rel
        before = source.read_text(encoding="utf-8") if source.exists() else ""
        after = candidate.read_text(encoding="utf-8") if candidate.exists() else ""
        parts.append(diff_for_file(rel, before, after))
    return "".join(parts)


def promote_worktree_files(repo_root: Path, worktree: Path, changed: Iterable[str]) -> None:
    for rel in changed:
        source = worktree / rel
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def verify_promoted_worktree_files(repo_root: Path, worktree: Path, changed: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for rel in changed:
        source = worktree / rel
        target = repo_root / rel
        if not source.exists():
            errors.append(f"accepted worktree source is missing after validation: {rel}")
            continue
        if not target.exists():
            errors.append(f"main worktree target is missing after promotion: {rel}")
            continue
        try:
            source_text = source.read_text(encoding="utf-8")
            target_text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"could not verify promoted text file {rel}: {exc}")
            continue
        if source_text != target_text:
            errors.append(f"main worktree target differs from accepted worktree after promotion: {rel}")
    return errors


def workspace_artifact_payload(
    proposal: Proposal,
    *,
    transport: str,
    promoted: bool,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "artifact_kind": "ephemeral-workspace",
        "schema_version": 1,
        "created_at": utc_now(),
        "transport": transport,
        "promoted_to_main_worktree": promoted,
        "reason": reason,
        "target_task": proposal.target_task,
        "summary": proposal.summary,
        "changed_files": list(proposal.changed_files),
        "validation_passed": bool(proposal.validation_results)
        and all(result.ok for result in proposal.validation_results),
        "validation_commands": [list(result.command) for result in proposal.validation_results],
    }
