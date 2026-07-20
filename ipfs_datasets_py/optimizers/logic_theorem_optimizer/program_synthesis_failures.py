"""Failure taxonomy and bounded recovery for program-synthesis workers.

The Codex program-synthesis loop has several very different failure modes.  A
provider timeout is safe to retry, for example, while retrying a patch which
consistently violates its assigned write scope only wastes capacity.  This
module provides one deterministic boundary between raw packet evidence and
recovery orchestration:

* :class:`ProgramSynthesisFailureClassifier` turns exceptions and daemon packet
  dictionaries into a stable, precedence-aware taxonomy;
* :class:`ProgramSynthesisFailureRecovery` persists evidence and retry state
  before it invokes a category-specific retry, rebase, or rescue callback;
* :class:`FailureRateReporter` reports transient and terminal rates separately
  for every program-synthesis scope.

Git and queue mutations are deliberately injected as callbacks.  The daemon
already owns locking, worktree creation, patch replay, and queue persistence;
keeping those operations outside this module makes recovery usable by both the
daemon and isolated workers without creating a second unsafe Git abstraction.
"""

from __future__ import annotations

import fnmatch
import fcntl
import hashlib
import json
import math
import os
import shutil
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional


PROGRAM_SYNTHESIS_FAILURE_SCHEMA_VERSION: Final = "program-synthesis-failure-v1"
PROGRAM_SYNTHESIS_RECOVERY_SCHEMA_VERSION: Final = "program-synthesis-recovery-v1"
FAILURE_RATE_REPORT_SCHEMA_VERSION: Final = "program-synthesis-failure-rates-v1"


class FailureCategory(str, Enum):
    """Stable categories emitted by the program-synthesis failure boundary."""

    TRANSPORT = "transport"
    PROVIDER_TIMEOUT = "provider_timeout"
    MALFORMED_RESPONSE = "malformed_response"
    EMPTY_PATCH = "empty_patch"
    APPLY_CONFLICT = "apply_conflict"
    STALE_BASE = "stale_base"
    SCOPE_VIOLATION = "scope_violation"
    DETERMINISTIC_TEST_FAILURE = "deterministic_test_failure"
    METRIC_REGRESSION = "metric_regression"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    SUPERVISOR_INTERRUPTION = "supervisor_interruption"

    @classmethod
    def coerce(cls, value: "FailureCategory | str") -> "FailureCategory":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "timeout": cls.PROVIDER_TIMEOUT,
            "provider_error": cls.TRANSPORT,
            "network": cls.TRANSPORT,
            "no_changes": cls.EMPTY_PATCH,
            "empty_diff": cls.EMPTY_PATCH,
            "merge_conflict": cls.APPLY_CONFLICT,
            "validation_failure": cls.DETERMINISTIC_TEST_FAILURE,
            "test_failure": cls.DETERMINISTIC_TEST_FAILURE,
            "oom": cls.RESOURCE_EXHAUSTION,
            "cancelled": cls.SUPERVISOR_INTERRUPTION,
            "canceled": cls.SUPERVISOR_INTERRUPTION,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"unsupported program-synthesis failure category: {value!r}") from exc


class RecoveryAction(str, Enum):
    """The bounded action associated with a failure category."""

    RETRY = "retry"
    REBASE = "rebase"
    RESCUE = "rescue"
    TERMINAL = "terminal"
    PRESERVE = "preserve"


class RecoveryStatus(str, Enum):
    """Result of applying a recovery policy."""

    RETRY_SCHEDULED = "retry_scheduled"
    REBASED = "rebased"
    RESCUED = "rescued"
    RECOVERED = "recovered"
    TERMINAL = "terminal"
    INTERRUPTED = "interrupted"
    ACTION_FAILED = "action_failed"


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    """Retry and worktree handling policy for one failure category."""

    action: RecoveryAction
    max_retries: int
    transient: bool
    preserve_worktree: bool = False
    retry_delays_seconds: tuple[float, ...] = ()
    fallback_action: RecoveryAction = RecoveryAction.TERMINAL

    def __post_init__(self) -> None:
        if int(self.max_retries) < 0:
            raise ValueError("max_retries must be non-negative")
        object.__setattr__(self, "max_retries", int(self.max_retries))
        delays = tuple(float(value) for value in self.retry_delays_seconds)
        if any(not math.isfinite(value) or value < 0 for value in delays):
            raise ValueError("retry delays must be finite and non-negative")
        object.__setattr__(self, "retry_delays_seconds", delays)

    def delay_for_retry(self, retry_number: int) -> float:
        if not self.retry_delays_seconds:
            return 0.0
        index = max(0, min(int(retry_number) - 1, len(self.retry_delays_seconds) - 1))
        return self.retry_delays_seconds[index]


DEFAULT_FAILURE_POLICIES: Final[Mapping[FailureCategory, FailurePolicy]] = MappingProxyType(
    {
        FailureCategory.TRANSPORT: FailurePolicy(
            RecoveryAction.RETRY, 3, True, retry_delays_seconds=(1.0, 5.0, 15.0)
        ),
        FailureCategory.PROVIDER_TIMEOUT: FailurePolicy(
            RecoveryAction.RETRY, 2, True, preserve_worktree=True,
            retry_delays_seconds=(5.0, 20.0),
        ),
        FailureCategory.MALFORMED_RESPONSE: FailurePolicy(
            RecoveryAction.RETRY, 1, True, retry_delays_seconds=(1.0,)
        ),
        FailureCategory.EMPTY_PATCH: FailurePolicy(
            RecoveryAction.RETRY, 1, True, preserve_worktree=True,
        ),
        FailureCategory.APPLY_CONFLICT: FailurePolicy(
            RecoveryAction.RESCUE, 1, True, preserve_worktree=True,
        ),
        FailureCategory.STALE_BASE: FailurePolicy(
            RecoveryAction.REBASE, 1, True, preserve_worktree=True,
            fallback_action=RecoveryAction.RESCUE,
        ),
        FailureCategory.SCOPE_VIOLATION: FailurePolicy(
            RecoveryAction.TERMINAL, 0, False, preserve_worktree=True,
        ),
        FailureCategory.DETERMINISTIC_TEST_FAILURE: FailurePolicy(
            RecoveryAction.TERMINAL, 0, False, preserve_worktree=True,
        ),
        FailureCategory.METRIC_REGRESSION: FailurePolicy(
            RecoveryAction.TERMINAL, 0, False, preserve_worktree=True,
        ),
        FailureCategory.RESOURCE_EXHAUSTION: FailurePolicy(
            RecoveryAction.RETRY, 1, True, preserve_worktree=True,
            retry_delays_seconds=(30.0,),
        ),
        # An interrupted worker is resumable by its supervisor, but this
        # component must never restart work while shutdown is in progress.
        FailureCategory.SUPERVISOR_INTERRUPTION: FailurePolicy(
            RecoveryAction.PRESERVE, 0, True, preserve_worktree=True,
        ),
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atom(value: Any, default: str = "unknown") -> str:
    normalized = str(value or "").strip()
    return normalized or default


def _string_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        values = (value,)
    elif isinstance(value, Sequence):
        values = value
    else:
        values = (value,)
    result = []
    for item in values:
        text = str(item or "").strip().replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        if text:
            result.append(text)
    return tuple(sorted(set(result)))


def _safe_json(value: Any, *, depth: int = 0) -> Any:
    """Return deterministic, bounded JSON evidence without invoking repr hooks."""

    if depth > 8:
        return "<depth-limit>"
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > 100_000:
            return value[:100_000] + "\n<truncated>"
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _safe_json(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_json(item, depth=depth + 1) for item in list(value)[:1000]]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _safe_json(to_dict(), depth=depth + 1)
    return f"<{type(value).__name__}>"


def _digest(value: Any) -> str:
    payload = json.dumps(
        _safe_json(value), allow_nan=False, ensure_ascii=True,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _artifact_tail(path_value: Any, *, max_bytes: int = 65_536) -> str:
    """Read a bounded diagnostic tail from a packet-owned text artifact."""

    if not path_value:
        return ""
    try:
        path = Path(str(path_value))
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - int(max_bytes)), os.SEEK_SET)
            return handle.read(int(max_bytes)).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


@dataclass(frozen=True, slots=True)
class FailureObservation:
    """Normalized evidence available when one synthesis attempt fails."""

    task_id: str
    scope: str = "unknown"
    attempt: int = 1
    packet_id: str = ""
    message: str = ""
    exception: Optional[BaseException] = field(default=None, compare=False, repr=False)
    category_hint: Optional[FailureCategory | str] = None
    exec_status: str = ""
    patch_status: str = ""
    apply_status: str = ""
    validation_status: str = ""
    metric_status: str = ""
    response: Any = field(default=None, compare=False, repr=False)
    patch: str = field(default="", compare=False, repr=False)
    changed_files: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    base_revision: str = ""
    current_revision: str = ""
    supervisor_interrupted: bool = False
    resource_exhausted: bool = False
    artifacts: tuple[str | Path, ...] = field(default=(), compare=False, repr=False)
    evidence: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not str(self.task_id or "").strip():
            raise ValueError("failure observation task_id must not be empty")
        if int(self.attempt) < 1:
            raise ValueError("failure observation attempt must be at least one")
        object.__setattr__(self, "task_id", str(self.task_id).strip())
        object.__setattr__(self, "scope", _atom(self.scope))
        object.__setattr__(self, "attempt", int(self.attempt))
        object.__setattr__(self, "changed_files", _string_sequence(self.changed_files))
        object.__setattr__(self, "allowed_paths", _string_sequence(self.allowed_paths))
        object.__setattr__(self, "artifacts", tuple(self.artifacts or ()))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence or {})))

    @classmethod
    def from_packet(
        cls,
        packet: Mapping[str, Any],
        *,
        task_id: str = "",
        scope: str = "",
        attempt: Optional[int] = None,
        category_hint: Optional[FailureCategory | str] = None,
        exception: Optional[BaseException] = None,
    ) -> "FailureObservation":
        """Build an observation from a daemon packet without losing raw evidence."""

        exec_result = packet.get("codex_exec")
        exec_result = exec_result if isinstance(exec_result, Mapping) else {}
        validation = packet.get("main_apply_validation")
        validation = validation if isinstance(validation, Mapping) else {}
        metric = packet.get("target_metric_validation")
        metric = metric if isinstance(metric, Mapping) else {}
        holdout_metric = packet.get("holdout_target_metric_validation")
        holdout_metric = holdout_metric if isinstance(holdout_metric, Mapping) else {}
        todos = packet.get("todos")
        first_todo = todos[0] if isinstance(todos, Sequence) and todos else {}
        first_todo = first_todo if isinstance(first_todo, Mapping) else {}
        first_metadata = first_todo.get("metadata")
        first_metadata = first_metadata if isinstance(first_metadata, Mapping) else {}
        scopes = _string_sequence(packet.get("program_synthesis_scopes"))
        artifact_keys = (
            "packet_path", "patch_path", "task_path", "todo_list_path",
            "todo_markdown_path",
        )
        artifacts = tuple(packet[key] for key in artifact_keys if packet.get(key)) + tuple(
            exec_result[key]
            for key in ("stderr_path", "stdout_path", "last_message_path", "prompt_path")
            if exec_result.get(key)
        )
        message_parts = [
            packet.get("patch_error"), packet.get("main_apply_error"),
            packet.get("error"), packet.get("reason"),
            exec_result.get("error"), exec_result.get("reason"),
            exec_result.get("stderr_tail"), exec_result.get("stdout_tail"),
            _artifact_tail(exec_result.get("stderr_path")),
            _artifact_tail(exec_result.get("last_message_path")),
        ]
        raw_category = category_hint or packet.get("failure_category")
        if raw_category is None and packet.get("category") is not None:
            try:
                raw_category = FailureCategory.coerce(packet["category"])
            except ValueError:
                raw_category = None
        return cls(
            task_id=task_id or str(
                packet.get("task_id")
                or first_todo.get("todo_id")
                or packet.get("packet_id")
                or "unbound-packet"
            ),
            scope=scope or str(packet.get("scope") or "") or (
                scopes[0] if len(scopes) == 1
                else str(first_metadata.get("program_synthesis_scope") or "unknown")
            ),
            attempt=attempt or int(exec_result.get("attempt_count") or 1),
            packet_id=str(packet.get("packet_id") or ""),
            message="\n".join(str(item) for item in message_parts if item),
            exception=exception,
            category_hint=raw_category,
            exec_status=str(
                exec_result.get("status")
                or packet.get("exec_status")
                or packet.get("status")
                or ""
            ),
            patch_status=str(packet.get("patch_status") or ""),
            apply_status=str(packet.get("main_apply_status") or ""),
            validation_status=str(
                validation.get("status") or packet.get("validation_status") or ""
            ),
            metric_status=str(
                packet.get("main_apply_target_metric_gate")
                or holdout_metric.get("status")
                or metric.get("status")
                or ""
            ),
            response=packet.get("response"),
            patch=str(packet.get("patch") or packet.get("diff") or ""),
            changed_files=_string_sequence(
                packet.get("main_apply_target_files") or packet.get("changed_files")
            ),
            allowed_paths=_string_sequence(
                packet.get("allowed_paths")
                or first_metadata.get("suggested_target_files")
                or packet.get("suggested_target_files")
            ),
            base_revision=str(packet.get("base_revision") or packet.get("base_commit") or ""),
            current_revision=str(
                packet.get("current_revision")
                or packet.get("current_base_revision")
                or packet.get("main_head_revision")
                or ""
            ),
            supervisor_interrupted=bool(packet.get("supervisor_interrupted")),
            resource_exhausted=bool(packet.get("resource_exhausted")),
            artifacts=artifacts,
            evidence=packet,
        )


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """Deterministic category, policy, and fingerprint for an observation."""

    category: FailureCategory
    policy: FailurePolicy
    reason: str
    fingerprint: str
    out_of_scope_files: tuple[str, ...] = ()

    @property
    def transient(self) -> bool:
        return self.policy.transient

    @property
    def recoverable_worktree(self) -> bool:
        return self.policy.action in {RecoveryAction.REBASE, RecoveryAction.RESCUE}

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.policy.action.value,
            "category": self.category.value,
            "fallback_action": self.policy.fallback_action.value,
            "fingerprint": self.fingerprint,
            "max_retries": self.policy.max_retries,
            "out_of_scope_files": list(self.out_of_scope_files),
            "preserve_worktree": self.policy.preserve_worktree,
            "reason": self.reason,
            "transient": self.transient,
        }


_SUPERVISOR_PATTERNS: Final = (
    "supervisor interrupt", "shutdown requested", "received sigterm",
    "worker cancelled", "worker canceled", "graceful shutdown",
)
_RESOURCE_PATTERNS: Final = (
    "out of memory", "cannot allocate memory", "memoryerror", "cuda out of memory",
    "resource temporarily unavailable", "no space left on device", "disk quota exceeded",
    "too many open files", "killed by oom", "exit code 137", "signal 9",
    "main_apply_lock_timeout", "apply lock timeout", "lock acquisition timeout",
)
_TIMEOUT_PATTERNS: Final = (
    "provider timeout", "request timeout", "request timed out", "deadline exceeded",
    "context deadline", "gateway timeout", "timed out waiting for model",
)
_TRANSPORT_PATTERNS: Final = (
    "connection reset", "connection refused", "connection aborted", "broken pipe",
    "network is unreachable", "temporary failure in name resolution", "dns failure",
    "tls handshake", "service unavailable", "bad gateway", "rate limit",
    "too many requests", "temporarily unavailable", "model is at capacity",
)
_MALFORMED_PATTERNS: Final = (
    "malformed response", "invalid response", "invalid json", "jsondecodeerror",
    "schema validation", "missing response", "unexpected response format",
)
_EMPTY_PATCH_PATTERNS: Final = (
    "no changes found", "empty patch", "empty diff", "awaiting_codex_changes",
    "no_merged_delta", "no merged delta",
)
_STALE_PATTERNS: Final = (
    "stale base", "base revision changed", "base commit changed", "not up to date",
    "behind current main", "does not match index",
)
_CONFLICT_PATTERNS: Final = (
    "apply conflict", "merge conflict", "patch does not apply", "git apply",
    "apply-check-failed", "apply check failed", "dirty target", "patch failed",
)
_SCOPE_PATTERNS: Final = (
    "scope violation", "outside assigned scope", "out of scope", "write-set violation",
    "unauthorized path",
)
_METRIC_PATTERNS: Final = (
    "metric regression", "target metric regression", "objective regression",
    "quality regression", "holdout regression",
)
_TEST_PATTERNS: Final = (
    "deterministic test failure", "validation failed", "tests failed", "pytest failed",
    "assertionerror", "syntaxerror", "typecheck failed",
)


def _contains(text: str, patterns: Sequence[str]) -> bool:
    normalized = text.replace("_", " ").replace("-", " ")
    return any(
        pattern in text or pattern.replace("_", " ").replace("-", " ") in normalized
        for pattern in patterns
    )


def _path_allowed(path: str, allowed: Sequence[str]) -> bool:
    path = path.rstrip("/")
    for raw_pattern in allowed:
        pattern = str(raw_pattern).rstrip("/")
        if not pattern:
            continue
        if any(char in pattern for char in "*?["):
            if fnmatch.fnmatchcase(path, pattern):
                return True
        elif path == pattern or path.startswith(pattern + "/"):
            return True
    return False


class ProgramSynthesisFailureClassifier:
    """Classify packet failures using explicit signals before textual fallbacks."""

    def __init__(
        self,
        policies: Optional[Mapping[FailureCategory | str, FailurePolicy]] = None,
    ) -> None:
        configured = dict(DEFAULT_FAILURE_POLICIES)
        for category, policy in (policies or {}).items():
            if not isinstance(policy, FailurePolicy):
                raise TypeError("failure policies must be FailurePolicy instances")
            configured[FailureCategory.coerce(category)] = policy
        missing = set(FailureCategory) - set(configured)
        if missing:
            raise ValueError(f"missing failure policies: {sorted(item.value for item in missing)}")
        self.policies = MappingProxyType(configured)

    def classify(
        self,
        observation: FailureObservation | Mapping[str, Any] | BaseException,
    ) -> FailureClassification:
        if isinstance(observation, BaseException):
            observation = FailureObservation(
                task_id="unbound-exception", message=str(observation), exception=observation
            )
        elif isinstance(observation, Mapping):
            observation = FailureObservation.from_packet(observation)
        if not isinstance(observation, FailureObservation):
            raise TypeError(
                "observation must be a FailureObservation, packet mapping, or exception"
            )

        out_of_scope = tuple(
            path for path in observation.changed_files
            if observation.allowed_paths and not _path_allowed(path, observation.allowed_paths)
        )
        text = "\n".join(
            str(item or "") for item in (
                observation.message, observation.exec_status, observation.patch_status,
                observation.apply_status, observation.validation_status,
                observation.metric_status,
                type(observation.exception).__name__ if observation.exception else "",
                str(observation.exception or ""),
            )
        ).lower()

        if observation.category_hint is not None:
            category = FailureCategory.coerce(observation.category_hint)
            reason = "explicit_category_hint"
        elif (
            observation.supervisor_interrupted
            or isinstance(observation.exception, (KeyboardInterrupt, InterruptedError))
            or _contains(text, _SUPERVISOR_PATTERNS)
        ):
            category, reason = FailureCategory.SUPERVISOR_INTERRUPTION, "supervisor_signal"
        elif (
            observation.resource_exhausted
            or isinstance(observation.exception, MemoryError)
            or _contains(text, _RESOURCE_PATTERNS)
        ):
            category, reason = FailureCategory.RESOURCE_EXHAUSTION, "resource_limit_signal"
        elif out_of_scope or _contains(text, _SCOPE_PATTERNS):
            category, reason = FailureCategory.SCOPE_VIOLATION, "changed_path_outside_scope"
        elif observation.metric_status.lower() in {"regressed", "failed_regression"} or _contains(
            text, _METRIC_PATTERNS
        ):
            category, reason = FailureCategory.METRIC_REGRESSION, "metric_gate_regressed"
        elif (
            observation.base_revision
            and observation.current_revision
            and observation.base_revision != observation.current_revision
        ) or _contains(text, _STALE_PATTERNS):
            category, reason = FailureCategory.STALE_BASE, "base_revision_is_stale"
        elif _contains(text, _CONFLICT_PATTERNS) or observation.apply_status.lower() in {
            "conflict", "check_failed", "failed"
        }:
            category, reason = FailureCategory.APPLY_CONFLICT, "patch_could_not_apply"
        elif not str(observation.patch or "").strip() and observation.patch_status.lower() in {
            "awaiting_codex_changes", "empty", "no_changes", "main_apply_no_merged_delta"
        } or _contains(text, _EMPTY_PATCH_PATTERNS):
            category, reason = FailureCategory.EMPTY_PATCH, "patch_has_no_delta"
        elif isinstance(observation.exception, TimeoutError) or observation.exec_status.lower() in {
            "timeout", "timed_out"
        } or _contains(text, _TIMEOUT_PATTERNS):
            category, reason = FailureCategory.PROVIDER_TIMEOUT, "provider_deadline_exceeded"
        elif isinstance(observation.exception, ConnectionError) or _contains(
            text, _TRANSPORT_PATTERNS
        ):
            category, reason = FailureCategory.TRANSPORT, "transport_unavailable"
        elif observation.response is not None and not isinstance(
            observation.response, (str, bytes, Mapping, Sequence)
        ) or _contains(text, _MALFORMED_PATTERNS):
            category, reason = FailureCategory.MALFORMED_RESPONSE, "response_contract_invalid"
        elif observation.validation_status.lower() in {
            "failed", "failure", "error", "timed_out"
        } or _contains(text, _TEST_PATTERNS):
            category = FailureCategory.DETERMINISTIC_TEST_FAILURE
            reason = "validation_reproducibly_failed"
        else:
            # An unrecognized failed provider response is not safe to interpret
            # as source code.  Give it the single bounded malformed retry.
            category, reason = FailureCategory.MALFORMED_RESPONSE, "unrecognized_failure_shape"

        fingerprint_payload = {
            "category": category.value,
            "scope": observation.scope,
            "reason": reason,
            "message": " ".join(observation.message.lower().split())[:1000],
            "out_of_scope_files": out_of_scope,
            "validation_status": observation.validation_status.lower(),
            "metric_status": observation.metric_status.lower(),
        }
        return FailureClassification(
            category=category,
            policy=self.policies[category],
            reason=reason,
            fingerprint=_digest(fingerprint_payload)[:24],
            out_of_scope_files=out_of_scope,
        )


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Request supplied to an injected retry/rebase/rescue operation."""

    observation: FailureObservation
    classification: FailureClassification
    retry_number: int
    retry_after_seconds: float
    evidence_path: Path


RecoveryCallback = Callable[[RecoveryContext], Any]


@dataclass(frozen=True, slots=True)
class RecoveryOperations:
    """Mutating operations owned by the caller's queue/worktree layer."""

    retry: Optional[RecoveryCallback] = None
    rebase: Optional[RecoveryCallback] = None
    rescue: Optional[RecoveryCallback] = None


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """Persistable result of one failure-handling invocation."""

    task_id: str
    scope: str
    classification: FailureClassification
    status: RecoveryStatus
    terminal: bool
    retry_number: int
    retry_after_seconds: float
    evidence_path: str
    action_result: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    poison_blocked: bool = False
    schema_version: str = PROGRAM_SYNTHESIS_RECOVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_result", MappingProxyType(dict(self.action_result or {})))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_result": _safe_json(self.action_result),
            "classification": self.classification.to_dict(),
            "evidence_path": self.evidence_path,
            "poison_blocked": self.poison_blocked,
            "reason": self.reason,
            "retry_after_seconds": self.retry_after_seconds,
            "retry_number": self.retry_number,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "status": self.status.value,
            "task_id": self.task_id,
            "terminal": self.terminal,
        }


class FailureEvidenceStore:
    """Append-only, atomic evidence storage for failed synthesis attempts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in "-_." else "-" for char in value)
        return cleaned.strip("-.")[:100] or "unknown"

    def preserve(
        self,
        observation: FailureObservation,
        classification: FailureClassification,
        *,
        sequence: int,
    ) -> Path:
        task_dir = (
            self.root
            / self._safe_name(observation.scope)
            / self._safe_name(observation.task_id)
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{int(sequence):06d}-{classification.category.value}-{classification.fingerprint}"
        evidence_path = task_dir / f"{stem}.json"
        artifact_dir = task_dir / f"{stem}.artifacts"
        copied_artifacts: list[dict[str, Any]] = []
        with self._lock:
            for index, raw_path in enumerate(observation.artifacts):
                source = Path(raw_path)
                record: dict[str, Any] = {"source_path": str(source)}
                try:
                    if source.is_file():
                        artifact_dir.mkdir(parents=True, exist_ok=True)
                        destination = artifact_dir / f"{index:02d}-{self._safe_name(source.name)}"
                        shutil.copy2(source, destination)
                        record.update(
                            copied=True,
                            evidence_path=str(destination),
                            sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                            size_bytes=destination.stat().st_size,
                        )
                    else:
                        record.update(copied=False, reason="missing_or_not_file")
                except OSError as exc:
                    record.update(copied=False, reason=type(exc).__name__)
                copied_artifacts.append(record)

            payload = {
                "artifacts": copied_artifacts,
                "classification": classification.to_dict(),
                "evidence": _safe_json(observation.evidence),
                "observation": {
                    "apply_status": observation.apply_status,
                    "attempt": observation.attempt,
                    "base_revision": observation.base_revision,
                    "changed_files": list(observation.changed_files),
                    "current_revision": observation.current_revision,
                    "exception_message": str(observation.exception or ""),
                    "exception_type": (
                        type(observation.exception).__name__
                        if observation.exception else ""
                    ),
                    "exec_status": observation.exec_status,
                    "message": observation.message,
                    "metric_status": observation.metric_status,
                    "packet_id": observation.packet_id,
                    "patch": observation.patch,
                    "patch_status": observation.patch_status,
                    "response": _safe_json(observation.response),
                    "scope": observation.scope,
                    "task_id": observation.task_id,
                    "validation_status": observation.validation_status,
                },
                "preserved_at": _utc_now(),
                "schema_version": PROGRAM_SYNTHESIS_FAILURE_SCHEMA_VERSION,
            }
            temporary = task_dir / f".{stem}.{os.getpid()}.{threading.get_ident()}.tmp"
            temporary.write_text(
                json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, evidence_path)
        return evidence_path


class RecoveryLedger:
    """Thread-safe retry/poison state, optionally persisted across restarts."""

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._category_attempts: Counter[str] = Counter()
        self._fingerprint_occurrences: Counter[str] = Counter()
        self._task_failures: Counter[str] = Counter()
        self._sequence = 0
        if self.path is not None and self.path.exists():
            self._load()

    @staticmethod
    def _key(task_id: str, value: str) -> str:
        return f"{task_id}\0{value}"

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
            schema_version = data.get("schema_version")
            if schema_version not in {None, PROGRAM_SYNTHESIS_RECOVERY_SCHEMA_VERSION}:
                raise ValueError(f"unsupported schema version {schema_version!r}")
            self._category_attempts = Counter(
                {str(k): int(v) for k, v in dict(data.get("category_attempts", {})).items()}
            )
            self._fingerprint_occurrences = Counter(
                {str(k): int(v) for k, v in dict(data.get("fingerprint_occurrences", {})).items()}
            )
            self._task_failures = Counter(
                {str(k): int(v) for k, v in dict(data.get("task_failures", {})).items()}
            )
            self._sequence = int(data.get("sequence", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid recovery ledger {self.path}: {exc}") from exc

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "category_attempts": dict(self._category_attempts),
            "fingerprint_occurrences": dict(self._fingerprint_occurrences),
            "schema_version": PROGRAM_SYNTHESIS_RECOVERY_SCHEMA_VERSION,
            "sequence": self._sequence,
            "task_failures": dict(self._task_failures),
            "updated_at": _utc_now(),
        }
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def record(
        self, task_id: str, category: FailureCategory, fingerprint: str
    ) -> tuple[int, int, int, int]:
        """Atomically record a failure and return sequence/category/fingerprint/task counts."""

        with self._lock:
            # Four Codex workers may share one ledger.  Reloading while holding
            # an advisory process lock prevents lost increments and duplicate
            # evidence sequence numbers across worker processes.
            lock_handle = None
            try:
                if self.path is not None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    lock_handle = self.path.with_suffix(self.path.suffix + ".lock").open("a+")
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                    if self.path.exists():
                        self._load()
                self._sequence += 1
                category_key = self._key(task_id, category.value)
                fingerprint_key = self._key(task_id, fingerprint)
                self._category_attempts[category_key] += 1
                self._fingerprint_occurrences[fingerprint_key] += 1
                self._task_failures[task_id] += 1
                self._save()
                return (
                    self._sequence,
                    self._category_attempts[category_key],
                    self._fingerprint_occurrences[fingerprint_key],
                    self._task_failures[task_id],
                )
            finally:
                if lock_handle is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                    lock_handle.close()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self.path is not None and self.path.exists():
                self._load()
            return {
                "category_attempts": dict(self._category_attempts),
                "fingerprint_occurrences": dict(self._fingerprint_occurrences),
                "sequence": self._sequence,
                "task_failures": dict(self._task_failures),
            }


def _normalize_action_result(value: Any) -> tuple[bool, dict[str, Any]]:
    if value is None:
        return True, {}
    if isinstance(value, bool):
        return value, {"succeeded": value}
    if isinstance(value, Mapping):
        result = dict(value)
        succeeded = bool(result.get("succeeded", result.get("accepted", result.get("ok", False))))
        if "status" in result and not any(key in result for key in ("succeeded", "accepted", "ok")):
            succeeded = str(result["status"]).strip().lower() in {
                "ok", "passed", "succeeded", "scheduled", "rebased", "rescued", "recovered",
            }
        return succeeded, _safe_json(result)
    return False, {"error": f"invalid_action_result:{type(value).__name__}"}


class FailureRateReporter:
    """Aggregate failure and recovery outcomes by synthesis scope."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scopes: defaultdict[str, Counter[str]] = defaultdict(Counter)

    def record(
        self,
        scope: str,
        classification: FailureClassification,
        *,
        terminal: bool,
        recovered: bool = False,
    ) -> None:
        scope = _atom(scope)
        with self._lock:
            counts = self._scopes[scope]
            counts["attempt_count"] += 1
            counts["failure_count"] += 1
            counts[f"category.{classification.category.value}"] += 1
            counter = (
                "transient_failure_count"
                if classification.transient else "nontransient_failure_count"
            )
            counts[counter] += 1
            counts["terminal_failure_count"] += int(terminal)
            counts["recovered_failure_count"] += int(recovered)

    def record_success(self, scope: str, *, count: int = 1) -> None:
        """Record successful synthesis attempts for true per-attempt rates."""

        if int(count) < 1:
            raise ValueError("success count must be at least one")
        scope = _atom(scope)
        with self._lock:
            counts = self._scopes[scope]
            counts["attempt_count"] += int(count)
            counts["success_count"] += int(count)

    def report(self) -> dict[str, Any]:
        with self._lock:
            snapshots = {scope: Counter(counts) for scope, counts in self._scopes.items()}
        total = Counter()
        scopes: dict[str, Any] = {}
        for scope, counts in sorted(snapshots.items()):
            total.update(counts)
            scopes[scope] = self._scope_report(counts)
        return {
            "generated_at": _utc_now(),
            "overall": self._scope_report(total),
            "schema_version": FAILURE_RATE_REPORT_SCHEMA_VERSION,
            "scopes": scopes,
        }

    @staticmethod
    def _scope_report(counts: Counter[str]) -> dict[str, Any]:
        failures = int(counts["failure_count"])
        attempts = int(counts["attempt_count"])
        denominator = max(1, attempts)
        return {
            "attempt_count": attempts,
            "category_counts": {
                key.removeprefix("category."): int(value)
                for key, value in sorted(counts.items()) if key.startswith("category.")
            },
            "failure_count": failures,
            "nontransient_failure_count": int(counts["nontransient_failure_count"]),
            "recovered_failure_count": int(counts["recovered_failure_count"]),
            "success_count": int(counts["success_count"]),
            "terminal_failure_count": int(counts["terminal_failure_count"]),
            "terminal_failure_rate": round(counts["terminal_failure_count"] / denominator, 9),
            "transient_failure_count": int(counts["transient_failure_count"]),
            "transient_failure_rate": round(counts["transient_failure_count"] / denominator, 9),
        }


class ProgramSynthesisFailureRecovery:
    """Classify, preserve, and apply bounded category-specific recovery."""

    def __init__(
        self,
        evidence_store: FailureEvidenceStore | str | Path,
        *,
        classifier: Optional[ProgramSynthesisFailureClassifier] = None,
        ledger: Optional[RecoveryLedger] = None,
        ledger_path: Optional[str | Path] = None,
        operations: Optional[RecoveryOperations] = None,
        reporter: Optional[FailureRateReporter] = None,
        max_same_fingerprint: int = 3,
        max_task_failures: int = 6,
    ) -> None:
        if int(max_same_fingerprint) < 1 or int(max_task_failures) < 1:
            raise ValueError("poison-task limits must be at least one")
        if ledger is not None and ledger_path is not None:
            raise ValueError("pass either ledger or ledger_path, not both")
        self.evidence_store = (
            evidence_store if isinstance(evidence_store, FailureEvidenceStore)
            else FailureEvidenceStore(evidence_store)
        )
        self.classifier = classifier or ProgramSynthesisFailureClassifier()
        self.ledger = ledger or RecoveryLedger(ledger_path)
        self.operations = operations or RecoveryOperations()
        self.reporter = reporter or FailureRateReporter()
        self.max_same_fingerprint = int(max_same_fingerprint)
        self.max_task_failures = int(max_task_failures)

    def handle(
        self,
        observation: FailureObservation | Mapping[str, Any],
        *,
        operations: Optional[RecoveryOperations] = None,
    ) -> RecoveryOutcome:
        if isinstance(observation, Mapping):
            observation = FailureObservation.from_packet(observation)
        if not isinstance(observation, FailureObservation):
            raise TypeError("observation must be a FailureObservation or packet mapping")
        classification = self.classifier.classify(observation)
        sequence, category_attempt, fingerprint_count, task_failures = self.ledger.record(
            observation.task_id, classification.category, classification.fingerprint
        )
        evidence_path = self.evidence_store.preserve(
            observation, classification, sequence=sequence
        )
        retry_number = category_attempt
        policy = classification.policy
        poison_blocked = (
            fingerprint_count > self.max_same_fingerprint
            or task_failures > self.max_task_failures
        )
        budget_exhausted = category_attempt > policy.max_retries

        if policy.action is RecoveryAction.PRESERVE:
            outcome = RecoveryOutcome(
                task_id=observation.task_id, scope=observation.scope,
                classification=classification, status=RecoveryStatus.INTERRUPTED,
                terminal=False, retry_number=0, retry_after_seconds=0.0,
                evidence_path=str(evidence_path), reason="supervisor_owns_resume",
            )
            self.reporter.record(observation.scope, classification, terminal=False)
            return outcome

        if policy.action is RecoveryAction.TERMINAL or poison_blocked or budget_exhausted:
            reason = (
                "non_retryable_category" if policy.action is RecoveryAction.TERMINAL
                else "poison_task_loop_blocked" if poison_blocked
                else "category_retry_budget_exhausted"
            )
            outcome = RecoveryOutcome(
                task_id=observation.task_id, scope=observation.scope,
                classification=classification, status=RecoveryStatus.TERMINAL,
                terminal=True, retry_number=max(0, min(category_attempt, policy.max_retries)),
                retry_after_seconds=0.0, evidence_path=str(evidence_path),
                reason=reason, poison_blocked=poison_blocked,
            )
            self.reporter.record(observation.scope, classification, terminal=True)
            return outcome

        selected_operations = operations or self.operations
        delay = policy.delay_for_retry(retry_number)
        context = RecoveryContext(
            observation=observation, classification=classification,
            retry_number=retry_number, retry_after_seconds=delay,
            evidence_path=evidence_path,
        )
        action, callback = self._select_action(policy.action, selected_operations)
        succeeded, result = self._invoke(callback, context, action)

        if not succeeded and policy.fallback_action is not RecoveryAction.TERMINAL:
            fallback_action, fallback = self._select_action(
                policy.fallback_action, selected_operations
            )
            fallback_succeeded, fallback_result = self._invoke(fallback, context, fallback_action)
            result = {
                "primary": result,
                "primary_action": action.value,
                "fallback": fallback_result,
                "fallback_action": fallback_action.value,
            }
            succeeded, action = fallback_succeeded, fallback_action

        status = {
            RecoveryAction.RETRY: RecoveryStatus.RETRY_SCHEDULED,
            RecoveryAction.REBASE: RecoveryStatus.REBASED,
            RecoveryAction.RESCUE: RecoveryStatus.RESCUED,
        }.get(action, RecoveryStatus.RECOVERED)
        terminal = not succeeded
        if terminal:
            status = RecoveryStatus.ACTION_FAILED
        outcome = RecoveryOutcome(
            task_id=observation.task_id, scope=observation.scope,
            classification=classification, status=status, terminal=terminal,
            retry_number=retry_number, retry_after_seconds=delay,
            evidence_path=str(evidence_path), action_result=result,
            reason="recovery_action_applied" if succeeded else "recovery_action_failed",
        )
        self.reporter.record(
            observation.scope, classification, terminal=terminal, recovered=succeeded
        )
        return outcome

    @staticmethod
    def _select_action(
        action: RecoveryAction, operations: RecoveryOperations
    ) -> tuple[RecoveryAction, Optional[RecoveryCallback]]:
        return action, {
            RecoveryAction.RETRY: operations.retry,
            RecoveryAction.REBASE: operations.rebase,
            RecoveryAction.RESCUE: operations.rescue,
        }.get(action)

    @staticmethod
    def _invoke(
        callback: Optional[RecoveryCallback], context: RecoveryContext, action: RecoveryAction
    ) -> tuple[bool, dict[str, Any]]:
        if callback is None:
            return False, {"error": f"{action.value}_operation_not_configured"}
        try:
            return _normalize_action_result(callback(context))
        except Exception as exc:  # recovery failure is evidence, never a daemon crash
            return False, {"error": str(exc), "error_type": type(exc).__name__}

    def failure_rate_report(self) -> dict[str, Any]:
        return self.reporter.report()

    def record_success(self, scope: str, *, count: int = 1) -> None:
        """Include successful worker attempts in the scoped rate denominator."""

        self.reporter.record_success(scope, count=count)


# Concise public aliases for callers which do not need the longer subsystem name.
FailureClassifier = ProgramSynthesisFailureClassifier
FailureRecoveryManager = ProgramSynthesisFailureRecovery


__all__ = [
    "DEFAULT_FAILURE_POLICIES",
    "FAILURE_RATE_REPORT_SCHEMA_VERSION",
    "PROGRAM_SYNTHESIS_FAILURE_SCHEMA_VERSION",
    "PROGRAM_SYNTHESIS_RECOVERY_SCHEMA_VERSION",
    "FailureCategory",
    "FailureClassification",
    "FailureClassifier",
    "FailureEvidenceStore",
    "FailureObservation",
    "FailurePolicy",
    "FailureRateReporter",
    "FailureRecoveryManager",
    "ProgramSynthesisFailureClassifier",
    "ProgramSynthesisFailureRecovery",
    "RecoveryAction",
    "RecoveryContext",
    "RecoveryLedger",
    "RecoveryOperations",
    "RecoveryOutcome",
    "RecoveryStatus",
]
