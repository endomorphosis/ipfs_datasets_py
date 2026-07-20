"""Conflict-aware scheduling for parallel Codex program-synthesis workers.

The modal optimizer creates related repair evidence faster than a single Codex
worker can consume it.  Starting workers solely by queue priority is unsafe,
however: nominally different logic scopes can still edit a shared registry,
codec, test, or package initializer.  This module is the policy boundary for
that concurrency.  It provides:

* canonical ownership for the nine LegalIR repair lanes;
* deterministic, scope-local evidence bundles and conservative write-set
  prediction;
* an initial scheduler capped at four unique, non-conflicting scopes;
* concurrent validation of isolated worktrees;
* a fair merge serializer which permits disjoint callbacks but never overlaps
  conflicting write sets; and
* a stateful worker controller which backs off on validation failures, apply
  conflicts, memory pressure, and transient provider/infrastructure failures.

Git operations remain injected callbacks.  The daemon owns its process-safe
main-checkout lock and final promotion validation; this module never weakens
those boundaries and isolated candidate validation does not replace them.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterator, Optional


CODEX_SCOPE_SCHEDULER_SCHEMA_VERSION: Final = "legal-ir-codex-scope-scheduler-v1"
CODEX_SCOPE_BUNDLE_SCHEMA_VERSION: Final = "legal-ir-codex-scope-bundle-v1"
MAX_INITIAL_CODEX_WORKERS: Final = 4


class CodexOwnershipScope(str, Enum):
    """Canonical queue/daemon names for the LegalIR Codex ownership lanes."""

    COMPILER_PARSER = "compiler_parser"
    COMPILER_REGISTRY = "compiler_registry"
    IR_DECOMPILER = "ir_decompiler"
    DEONTIC = "deontic"
    FRAME_LOGIC = "frame_logic"
    TDFOL = "tdfol"
    KG = "knowledge_graphs"
    CEC = "cec"
    EXTERNAL_PROVER = "external_provers"

    @classmethod
    def coerce(cls, value: "CodexOwnershipScope | str") -> "CodexOwnershipScope":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "compiler": cls.COMPILER_PARSER,
            "parser": cls.COMPILER_PARSER,
            "compiler_ambiguity": cls.COMPILER_REGISTRY,
            "registry": cls.COMPILER_REGISTRY,
            "decompiler": cls.IR_DECOMPILER,
            "flogic": cls.FRAME_LOGIC,
            "frame": cls.FRAME_LOGIC,
            "td_fol": cls.TDFOL,
            "temporal_deontic_fol": cls.TDFOL,
            "kg": cls.KG,
            "knowledge_graph": cls.KG,
            "knowledge_graphs": cls.KG,
            "event_calculus": cls.CEC,
            "external_prover": cls.EXTERNAL_PROVER,
            "prover": cls.EXTERNAL_PROVER,
            "provers": cls.EXTERNAL_PROVER,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as exc:
            expected = ", ".join(scope.value for scope in cls)
            raise ValueError(f"unsupported Codex ownership scope {value!r}; expected {expected}") from exc


CODEX_OWNERSHIP_SCOPES: Final[tuple[str, ...]] = tuple(
    scope.value for scope in CodexOwnershipScope
)
# Names used in the planning packet/acceptance text.  Runtime queue names stay
# lowercase and compatible with the existing modal daemon.
CODEX_OWNERSHIP_SCOPE_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        CodexOwnershipScope.COMPILER_PARSER.value: "compiler_parser",
        CodexOwnershipScope.COMPILER_REGISTRY.value: "compiler_registry",
        CodexOwnershipScope.IR_DECOMPILER.value: "ir_decompiler",
        CodexOwnershipScope.DEONTIC.value: "deontic",
        CodexOwnershipScope.FRAME_LOGIC.value: "frame_logic",
        CodexOwnershipScope.TDFOL.value: "TDFOL",
        CodexOwnershipScope.KG.value: "KG",
        CodexOwnershipScope.CEC.value: "CEC",
        CodexOwnershipScope.EXTERNAL_PROVER.value: "external_prover",
    }
)


# These are ownership candidates, not permission grants.  Explicit allowed
# paths on a task are retained as well and can therefore reveal conflicts in
# shared files such as __init__.py or modal/codec.py.
DEFAULT_SCOPE_OWNERSHIP: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "compiler_parser": (
            "ipfs_datasets_py/logic/modal/compiler.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_modal_parser.py",
        ),
        "compiler_registry": (
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
        ),
        "ir_decompiler": (
            "ipfs_datasets_py/logic/modal/decompiler.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
        ),
        "deontic": ("ipfs_datasets_py/logic/deontic/**",),
        "frame_logic": (
            "ipfs_datasets_py/logic/flogic/**",
            "ipfs_datasets_py/logic/flogic_optimizer.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
        ),
        "tdfol": ("ipfs_datasets_py/logic/TDFOL/**",),
        "knowledge_graphs": (
            "ipfs_datasets_py/knowledge_graphs/**",
            "ipfs_datasets_py/logic/modal/kg_bridge.py",
        ),
        "cec": ("ipfs_datasets_py/logic/CEC/**",),
        "external_provers": (
            "ipfs_datasets_py/logic/external_provers/**",
            "ipfs_datasets_py/logic/bridge/external_prover_router.py",
        ),
    }
)


def canonical_codex_scope(value: CodexOwnershipScope | str) -> str:
    """Return the canonical daemon scope name, accepting task-plan aliases."""

    return CodexOwnershipScope.coerce(value).value


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _normalize_path(value: Any) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    while "//" in path:
        path = path.replace("//", "/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"write-set paths must be repository-relative: {value!r}")
    return path.rstrip("/")


def _paths(value: Any) -> tuple[str, ...]:
    normalized: set[str] = set()
    for item in _sequence(value):
        if isinstance(item, Mapping):
            item = item.get("path") or item.get("file") or item.get("pattern")
        if item:
            normalized.add(_normalize_path(item))
    return tuple(sorted(normalized))


def _identifiers(value: Any) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip() for item in _sequence(value) if str(item).strip()}))


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<depth-limit>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:512]]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict(), depth=depth + 1)
    return str(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _glob_root(pattern: str) -> str:
    positions = [pattern.find(token) for token in ("*", "?", "[") if token in pattern]
    cut = min(positions) if positions else len(pattern)
    return pattern[:cut].rstrip("/")


def _path_patterns_conflict(left: str, right: str) -> bool:
    if left == right:
        return True
    left_root, right_root = _glob_root(left), _glob_root(right)
    if not left_root or not right_root:
        return True
    if fnmatch.fnmatchcase(left, right) or fnmatch.fnmatchcase(right, left):
        return True
    # A directory pattern owns every descendant.  Plain file names do not own
    # sibling paths merely because their textual prefixes happen to match.
    left_directory = any(token in left for token in "*?[") or left.endswith("/")
    right_directory = any(token in right for token in "*?[") or right.endswith("/")
    if left_directory and (right_root == left_root or right_root.startswith(left_root + "/")):
        return True
    if right_directory and (left_root == right_root or left_root.startswith(right_root + "/")):
        return True
    return False


@dataclass(frozen=True, slots=True)
class PredictedWriteSet:
    """A conservative set of repository paths and typed symbols a patch may edit."""

    paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    unknown: bool = False
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", _paths(self.paths))
        object.__setattr__(self, "symbols", _identifiers(self.symbols))
        object.__setattr__(self, "sources", _identifiers(self.sources))

    @classmethod
    def from_value(cls, value: "PredictedWriteSet | Mapping[str, Any] | Sequence[str]") -> "PredictedWriteSet":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(
                paths=_paths(value.get("paths") or value.get("files")),
                symbols=_identifiers(value.get("symbols")),
                unknown=bool(value.get("unknown", False)),
                sources=_identifiers(value.get("sources")),
            )
        return cls(paths=_paths(value))

    def conflicts_with(self, other: "PredictedWriteSet") -> bool:
        if not isinstance(other, PredictedWriteSet):
            raise TypeError("write-set conflicts require PredictedWriteSet values")
        if self.unknown or other.unknown:
            return True
        if set(self.symbols) & set(other.symbols):
            return True
        return any(
            _path_patterns_conflict(left, right)
            for left in self.paths
            for right in other.paths
        )

    def union(self, *others: "PredictedWriteSet") -> "PredictedWriteSet":
        return PredictedWriteSet(
            paths=tuple(path for value in (self, *others) for path in value.paths),
            symbols=tuple(symbol for value in (self, *others) for symbol in value.symbols),
            unknown=any(value.unknown for value in (self, *others)),
            sources=tuple(source for value in (self, *others) for source in value.sources),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": list(self.paths),
            "sources": list(self.sources),
            "symbols": list(self.symbols),
            "unknown": self.unknown,
        }


@dataclass(frozen=True, slots=True)
class CodexScopeTask:
    """Normalized queue evidence consumed by the scheduler."""

    task_id: str
    scope: str
    priority: float = 0.0
    correlation_key: str = ""
    explicit_paths: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        task_id = str(self.task_id or "").strip()
        if not task_id:
            raise ValueError("Codex scheduler task_id must not be empty")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "scope", canonical_codex_scope(self.scope))
        priority = float(self.priority)
        if not math.isfinite(priority):
            raise ValueError("Codex scheduler priority must be finite")
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "correlation_key", str(self.correlation_key or "").strip())
        object.__setattr__(self, "explicit_paths", _paths(self.explicit_paths))
        object.__setattr__(self, "symbols", _identifiers(self.symbols))
        object.__setattr__(self, "validation_commands", _identifiers(self.validation_commands))
        object.__setattr__(self, "evidence", MappingProxyType(dict(_json_safe(self.evidence))))

    @classmethod
    def from_value(cls, value: "CodexScopeTask | Mapping[str, Any] | Any") -> "CodexScopeTask":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            to_dict = getattr(value, "to_dict", None)
            if not callable(to_dict):
                raise TypeError("Codex tasks must be mappings or expose to_dict()")
            value = to_dict()
        data = dict(value)
        metadata = dict(data.get("metadata") or {})
        task_id = data.get("task_id") or data.get("todo_id") or data.get("id")
        scope = (
            data.get("scope")
            or data.get("program_synthesis_scope")
            or data.get("ownership_scope")
            or metadata.get("program_synthesis_scope")
            or metadata.get("owned_ast_scope")
            or metadata.get("scope")
        )
        paths: list[Any] = []
        for source in (data, metadata):
            for key in (
                "predicted_write_set", "predicted_write_paths", "changed_files",
                "suggested_target_files", "target_files", "allowed_paths",
            ):
                raw = source.get(key)
                if isinstance(raw, Mapping):
                    raw = raw.get("paths")
                paths.extend(_sequence(raw))
        correlation = (
            data.get("correlation_key")
            or metadata.get("semantic_bundle_key")
            or metadata.get("correlation_key")
            or metadata.get("contract_id")
            or metadata.get("target_component")
            or data.get("action")
            or task_id
        )
        evidence = {
            "action": data.get("action"),
            "citations": data.get("citations") or (),
            "hint_evidence": metadata.get("hint_evidence") or (),
            "loss_name": data.get("loss_name"),
            "objective": data.get("objective"),
            "sample_ids": data.get("sample_ids") or (),
            "target_component": metadata.get("target_component"),
        }
        return cls(
            task_id=str(task_id or ""),
            scope=str(scope or ""),
            priority=float(data.get("priority", metadata.get("priority", 0.0)) or 0.0),
            correlation_key=str(correlation or ""),
            explicit_paths=tuple(paths),
            symbols=_identifiers(
                data.get("symbols") or metadata.get("symbols") or metadata.get("typed_ast_symbols")
            ),
            validation_commands=_identifiers(
                data.get("validation_commands") or metadata.get("validation_commands")
            ),
            evidence=evidence,
        )


class WriteSetPredictor:
    """Predict patch writes from task paths plus stable scope ownership."""

    def __init__(
        self,
        ownership: Optional[Mapping[str, Sequence[str]]] = None,
        *,
        include_scope_defaults: bool = True,
    ) -> None:
        configured = ownership or DEFAULT_SCOPE_OWNERSHIP
        self.ownership = MappingProxyType(
            {canonical_codex_scope(scope): _paths(paths) for scope, paths in configured.items()}
        )
        self.include_scope_defaults = bool(include_scope_defaults)

    def predict(self, task: CodexScopeTask | Mapping[str, Any] | Any) -> PredictedWriteSet:
        normalized = CodexScopeTask.from_value(task)
        paths = list(normalized.explicit_paths)
        sources: list[str] = []
        if normalized.explicit_paths:
            sources.append("task")
        if self.include_scope_defaults:
            paths.extend(self.ownership.get(normalized.scope, ()))
            sources.append("scope_ownership")
        unknown = not paths and not normalized.symbols
        return PredictedWriteSet(
            paths=tuple(paths), symbols=normalized.symbols, unknown=unknown, sources=tuple(sources)
        )


@dataclass(frozen=True, slots=True)
class ScopeEvidenceBundle:
    """Correlated evidence for exactly one ownership scope and one worker."""

    bundle_id: str
    scope: str
    correlation_key: str
    tasks: tuple[CodexScopeTask, ...]
    write_set: PredictedWriteSet
    priority: float
    validation_commands: tuple[str, ...] = ()
    schema_version: str = CODEX_SCOPE_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        scope = canonical_codex_scope(self.scope)
        if not self.tasks:
            raise ValueError("scope evidence bundles must contain at least one task")
        if any(task.scope != scope for task in self.tasks):
            raise ValueError("correlated evidence cannot cross ownership scopes")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "validation_commands", _identifiers(self.validation_commands))

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(task.task_id for task in self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "correlation_key": self.correlation_key,
            "priority": self.priority,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "task_ids": list(self.task_ids),
            "validation_commands": list(self.validation_commands),
            "write_set": self.write_set.to_dict(),
        }


class ScopeEvidenceBundler:
    """Bundle related evidence without ever crossing a write-ownership lane."""

    def __init__(self, *, predictor: Optional[WriteSetPredictor] = None, max_tasks: int = 16) -> None:
        if int(max_tasks) < 1:
            raise ValueError("max_tasks must be at least one")
        self.predictor = predictor or WriteSetPredictor()
        self.max_tasks = int(max_tasks)

    def bundle(
        self, tasks: Iterable[CodexScopeTask | Mapping[str, Any] | Any]
    ) -> tuple[ScopeEvidenceBundle, ...]:
        normalized = [CodexScopeTask.from_value(task) for task in tasks]
        grouped: dict[tuple[str, str], list[CodexScopeTask]] = {}
        for task in normalized:
            key = task.correlation_key or task.task_id
            grouped.setdefault((task.scope, key), []).append(task)
        bundles: list[ScopeEvidenceBundle] = []
        for (scope, correlation_key), members in sorted(grouped.items()):
            ordered = sorted(members, key=lambda item: (-item.priority, item.task_id))
            for offset in range(0, len(ordered), self.max_tasks):
                shard = tuple(ordered[offset : offset + self.max_tasks])
                write_sets = tuple(self.predictor.predict(task) for task in shard)
                write_set = write_sets[0].union(*write_sets[1:])
                payload = {
                    "correlation_key": correlation_key,
                    "scope": scope,
                    "task_ids": [task.task_id for task in shard],
                }
                bundle_id = f"scope-bundle-{_digest(payload)[:20]}"
                if len(ordered) > self.max_tasks:
                    bundle_id += f"-{(offset // self.max_tasks) + 1:02d}"
                bundles.append(
                    ScopeEvidenceBundle(
                        bundle_id=bundle_id,
                        scope=scope,
                        correlation_key=correlation_key,
                        tasks=shard,
                        write_set=write_set,
                        priority=max(task.priority for task in shard),
                        validation_commands=tuple(
                            command for task in shard for command in task.validation_commands
                        ),
                    )
                )
        return tuple(sorted(bundles, key=lambda item: (-item.priority, item.scope, item.bundle_id)))


@dataclass(frozen=True, slots=True)
class SchedulerSignals:
    """Recent rates and pressure used to choose a safe worker count."""

    validation_failure_rate: float = 0.0
    apply_conflict_rate: float = 0.0
    memory_pressure: float = 0.0
    transient_failure_rate: float = 0.0
    sample_count: int = 0

    def __post_init__(self) -> None:
        for name in (
            "validation_failure_rate", "apply_conflict_rate", "memory_pressure",
            "transient_failure_rate",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0 or value > 1.0:
                raise ValueError(f"{name} must be finite and between zero and one")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "sample_count", max(0, int(self.sample_count)))

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "SchedulerSignals":
        data = dict(value or {})
        if isinstance(data.get("overall"), Mapping):
            overall = dict(data["overall"])
            data = {**overall, **data}
        memory = data.get("memory_pressure", data.get("memory_used_ratio", 0.0))
        if isinstance(memory, bool):
            memory = 1.0 if memory else 0.0
        return cls(
            validation_failure_rate=float(
                data.get("validation_failure_rate", data.get("validation_failed_rate", 0.0)) or 0.0
            ),
            apply_conflict_rate=float(
                data.get("apply_conflict_rate", data.get("merge_conflict_rate", 0.0)) or 0.0
            ),
            memory_pressure=float(memory or 0.0),
            transient_failure_rate=float(data.get("transient_failure_rate", 0.0) or 0.0),
            sample_count=int(data.get("sample_count", data.get("attempt_count", 0)) or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "apply_conflict_rate": self.apply_conflict_rate,
            "memory_pressure": self.memory_pressure,
            "sample_count": self.sample_count,
            "transient_failure_rate": self.transient_failure_rate,
            "validation_failure_rate": self.validation_failure_rate,
        }


@dataclass(frozen=True, slots=True)
class WorkerDecision:
    requested_workers: int
    effective_workers: int
    reasons: tuple[str, ...]
    signals: SchedulerSignals

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_workers": self.effective_workers,
            "reasons": list(self.reasons),
            "requested_workers": self.requested_workers,
            "signals": self.signals.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SchedulerOutcome:
    accepted: bool = False
    validation_failed: bool = False
    apply_conflict: bool = False
    memory_pressure: bool = False
    transient_failure: bool = False


class AdaptiveWorkerController:
    """Bounded additive-decrease/slow-recovery controller for Codex workers."""

    def __init__(
        self,
        *,
        initial_workers: int = MAX_INITIAL_CODEX_WORKERS,
        min_workers: int = 1,
        window_size: int = 20,
        validation_failure_threshold: float = 0.20,
        apply_conflict_threshold: float = 0.10,
        memory_pressure_threshold: float = 0.85,
        transient_failure_threshold: float = 0.20,
        recovery_successes: int = 4,
    ) -> None:
        if not 1 <= int(min_workers) <= int(initial_workers) <= MAX_INITIAL_CODEX_WORKERS:
            raise ValueError("worker bounds must satisfy 1 <= min <= initial <= 4")
        if int(window_size) < 1 or int(recovery_successes) < 1:
            raise ValueError("window and recovery_successes must be positive")
        self.initial_workers = int(initial_workers)
        self.min_workers = int(min_workers)
        self.current_workers = self.initial_workers
        self.window: deque[SchedulerOutcome] = deque(maxlen=int(window_size))
        self.validation_failure_threshold = float(validation_failure_threshold)
        self.apply_conflict_threshold = float(apply_conflict_threshold)
        self.memory_pressure_threshold = float(memory_pressure_threshold)
        self.transient_failure_threshold = float(transient_failure_threshold)
        self.recovery_successes = int(recovery_successes)
        self._healthy_streak = 0
        self._lock = threading.Lock()

    def recommend(
        self, signals: SchedulerSignals | Mapping[str, Any], *, requested_workers: Optional[int] = None
    ) -> WorkerDecision:
        if isinstance(signals, Mapping):
            signals = SchedulerSignals.from_mapping(signals)
        requested = min(
            MAX_INITIAL_CODEX_WORKERS,
            max(self.min_workers, int(requested_workers or self.initial_workers)),
        )
        effective = requested
        reasons: list[str] = []
        checks = (
            (signals.validation_failure_rate, self.validation_failure_threshold, "validation_failures"),
            (signals.apply_conflict_rate, self.apply_conflict_threshold, "apply_conflicts"),
            (signals.transient_failure_rate, self.transient_failure_threshold, "transient_failures"),
        )
        for rate, threshold, reason in checks:
            if rate >= threshold and rate > 0.0:
                effective -= 1
                reasons.append(reason)
                if threshold > 0.0 and rate >= min(1.0, threshold * 2.5):
                    effective -= 1
        if signals.memory_pressure >= self.memory_pressure_threshold and signals.memory_pressure > 0.0:
            effective -= 1
            reasons.append("memory_pressure")
            if signals.memory_pressure >= 0.95:
                effective = self.min_workers
        effective = max(self.min_workers, min(requested, effective))
        if not reasons:
            reasons.append("healthy")
        return WorkerDecision(requested, effective, tuple(reasons), signals)

    def _signals_locked(self) -> SchedulerSignals:
        count = len(self.window)
        if not count:
            return SchedulerSignals()
        return SchedulerSignals(
            validation_failure_rate=sum(item.validation_failed for item in self.window) / count,
            apply_conflict_rate=sum(item.apply_conflict for item in self.window) / count,
            memory_pressure=sum(item.memory_pressure for item in self.window) / count,
            transient_failure_rate=sum(item.transient_failure for item in self.window) / count,
            sample_count=count,
        )

    def observe(self, outcome: SchedulerOutcome | Mapping[str, Any]) -> WorkerDecision:
        if isinstance(outcome, Mapping):
            outcome = SchedulerOutcome(**{
                key: bool(outcome.get(key, False))
                for key in SchedulerOutcome.__dataclass_fields__
            })
        with self._lock:
            self.window.append(outcome)
            unhealthy = any(
                (outcome.validation_failed, outcome.apply_conflict,
                 outcome.memory_pressure, outcome.transient_failure)
            )
            self._healthy_streak = 0 if unhealthy else self._healthy_streak + int(outcome.accepted)
            signals = self._signals_locked()
            decision = self.recommend(signals, requested_workers=self.initial_workers)
            if decision.effective_workers < self.current_workers:
                self.current_workers = decision.effective_workers
            elif self._healthy_streak >= self.recovery_successes and self.current_workers < self.initial_workers:
                self.current_workers += 1
                self._healthy_streak = 0
            return replace(decision, effective_workers=self.current_workers)

    def snapshot(self) -> WorkerDecision:
        with self._lock:
            decision = self.recommend(self._signals_locked(), requested_workers=self.initial_workers)
            return replace(decision, effective_workers=min(self.current_workers, decision.effective_workers))


@dataclass(frozen=True, slots=True)
class ScopeAssignment:
    assignment_id: str
    worker_id: str
    bundle: ScopeEvidenceBundle
    worktree_path: str = ""

    @property
    def scope(self) -> str:
        return self.bundle.scope

    @property
    def write_set(self) -> PredictedWriteSet:
        return self.bundle.write_set

    def with_worktree(self, path: str | Path) -> "ScopeAssignment":
        return replace(self, worktree_path=str(Path(path)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "bundle": self.bundle.to_dict(),
            "scope": self.scope,
            "worker_id": self.worker_id,
            "worktree_path": self.worktree_path,
        }


@dataclass(frozen=True, slots=True)
class ScopeSchedulePlan:
    assignments: tuple[ScopeAssignment, ...]
    deferred: Mapping[str, str]
    worker_decision: WorkerDecision
    schema_version: str = CODEX_SCOPE_SCHEDULER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "deferred", MappingProxyType(dict(sorted(self.deferred.items()))))

    @property
    def worker_count(self) -> int:
        return len(self.assignments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "deferred": dict(self.deferred),
            "schema_version": self.schema_version,
            "worker_count": self.worker_count,
            "worker_decision": self.worker_decision.to_dict(),
        }


class CodexScopeScheduler:
    """Select one high-value bundle per disjoint scope/write lane."""

    def __init__(
        self,
        *,
        max_workers: int = MAX_INITIAL_CODEX_WORKERS,
        bundler: Optional[ScopeEvidenceBundler] = None,
        controller: Optional[AdaptiveWorkerController] = None,
    ) -> None:
        if not 1 <= int(max_workers) <= MAX_INITIAL_CODEX_WORKERS:
            raise ValueError("Codex initial max_workers must be between one and four")
        self.max_workers = int(max_workers)
        self.bundler = bundler or ScopeEvidenceBundler()
        self.controller = controller or AdaptiveWorkerController(initial_workers=self.max_workers)

    def schedule(
        self,
        tasks: Iterable[CodexScopeTask | Mapping[str, Any] | Any],
        *,
        active_write_sets: Iterable[PredictedWriteSet | Mapping[str, Any] | Sequence[str]] = (),
        signals: SchedulerSignals | Mapping[str, Any] | None = None,
        worker_prefix: str = "codex",
    ) -> ScopeSchedulePlan:
        bundles = self.bundler.bundle(tasks)
        decision = self.controller.recommend(
            signals or SchedulerSignals(), requested_workers=self.max_workers
        )
        limit = min(self.max_workers, decision.effective_workers)
        active = [PredictedWriteSet.from_value(value) for value in active_write_sets]
        selected: list[ScopeAssignment] = []
        selected_scopes: set[str] = set()
        deferred: dict[str, str] = {}
        for bundle in bundles:
            if len(selected) >= limit:
                deferred[bundle.bundle_id] = "worker_limit"
                continue
            if bundle.scope in selected_scopes:
                deferred[bundle.bundle_id] = "scope_already_assigned"
                continue
            if any(bundle.write_set.conflicts_with(write_set) for write_set in active):
                deferred[bundle.bundle_id] = "active_write_conflict"
                continue
            if any(bundle.write_set.conflicts_with(item.write_set) for item in selected):
                deferred[bundle.bundle_id] = "predicted_write_conflict"
                continue
            number = len(selected) + 1
            selected.append(
                ScopeAssignment(
                    assignment_id=f"assignment-{number:02d}-{bundle.bundle_id}",
                    worker_id=f"{worker_prefix}-{bundle.scope}-{number:02d}",
                    bundle=bundle,
                )
            )
            selected_scopes.add(bundle.scope)
        return ScopeSchedulePlan(tuple(selected), deferred, decision)


@dataclass(frozen=True, slots=True)
class IsolatedValidationResult:
    assignment_id: str
    scope: str
    accepted: bool
    status: str
    elapsed_seconds: float
    evidence: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    worker_thread_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "assignment_id": self.assignment_id,
            "elapsed_seconds": round(self.elapsed_seconds, 9),
            "error": self.error,
            "evidence": _json_safe(self.evidence),
            "scope": self.scope,
            "status": self.status,
            "worker_thread_id": self.worker_thread_id,
        }


ValidationCallback = Callable[[ScopeAssignment], Any]


class IsolatedValidationExecutor:
    """Validate independent assignment worktrees concurrently, fail closed."""

    def __init__(self, *, max_workers: int = MAX_INITIAL_CODEX_WORKERS) -> None:
        if not 1 <= int(max_workers) <= MAX_INITIAL_CODEX_WORKERS:
            raise ValueError("isolated validation workers must be between one and four")
        self.max_workers = int(max_workers)

    @staticmethod
    def _normalize(value: Any) -> tuple[bool, Mapping[str, Any], str]:
        if value is None:
            return True, {}, ""
        if isinstance(value, bool):
            return value, {}, "" if value else "validation_failed"
        if isinstance(value, Mapping):
            data = dict(value)
            accepted = bool(data.pop("accepted", data.pop("passed", data.get("status") == "passed")))
            error = str(data.pop("error", data.pop("reason", "")) or "")
            return accepted, data, error
        return False, {}, f"invalid_validation_result:{type(value).__name__}"

    def _run(self, assignment: ScopeAssignment, callback: ValidationCallback) -> IsolatedValidationResult:
        started = time.monotonic()
        try:
            accepted, evidence, error = self._normalize(callback(assignment))
        except Exception as exc:
            accepted, evidence = False, {}
            error = f"{type(exc).__name__}: {exc}"
        return IsolatedValidationResult(
            assignment_id=assignment.assignment_id,
            scope=assignment.scope,
            accepted=accepted,
            status="passed" if accepted else "failed",
            elapsed_seconds=time.monotonic() - started,
            evidence=evidence,
            error=error,
            worker_thread_id=threading.get_ident(),
        )

    def validate(
        self,
        assignments: Sequence[ScopeAssignment],
        callback: ValidationCallback,
        *,
        require_distinct_worktrees: bool = True,
    ) -> Mapping[str, IsolatedValidationResult]:
        if not callable(callback):
            raise TypeError("isolated validation callback must be callable")
        assignment_ids = [item.assignment_id for item in assignments]
        if len(set(assignment_ids)) != len(assignment_ids):
            raise ValueError("assignment ids must be unique")
        if require_distinct_worktrees and len(assignments) > 1:
            worktrees = [str(item.worktree_path or "") for item in assignments]
            if any(not path for path in worktrees) or len(set(worktrees)) != len(worktrees):
                raise ValueError("concurrent validation requires one distinct worktree per assignment")
        results: dict[str, IsolatedValidationResult] = {}
        if not assignments:
            return MappingProxyType(results)
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(assignments)),
            thread_name_prefix="codex-isolated-validation",
        ) as pool:
            futures = {pool.submit(self._run, item, callback): item.assignment_id for item in assignments}
            for future in as_completed(futures):
                result = future.result()
                results[result.assignment_id] = result
        return MappingProxyType(dict(sorted(results.items())))


@dataclass(frozen=True, slots=True)
class MergeResult:
    assignment_id: str
    scope: str
    accepted: bool
    status: str
    wait_seconds: float
    elapsed_seconds: float
    evidence: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "assignment_id": self.assignment_id,
            "elapsed_seconds": round(self.elapsed_seconds, 9),
            "error": self.error,
            "evidence": _json_safe(self.evidence),
            "scope": self.scope,
            "status": self.status,
            "wait_seconds": round(self.wait_seconds, 9),
        }


class ConflictAwareMergeSerializer:
    """Fairly serialize overlapping merges while allowing disjoint callbacks."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active: dict[int, PredictedWriteSet] = {}
        self._pending: list[tuple[int, PredictedWriteSet]] = []
        self._next_ticket = 0
        self._counters: Counter[str] = Counter()

    @contextmanager
    def acquire(
        self, write_set: PredictedWriteSet, *, timeout_seconds: Optional[float] = None
    ) -> Iterator[float]:
        if not isinstance(write_set, PredictedWriteSet):
            raise TypeError("merge serializer requires a PredictedWriteSet")
        started = time.monotonic()
        with self._condition:
            ticket = self._next_ticket
            self._next_ticket += 1
            request = (ticket, write_set)
            self._pending.append(request)
            deadline = None if timeout_seconds is None else started + max(0.0, float(timeout_seconds))
            while True:
                active_conflict = any(write_set.conflicts_with(active) for active in self._active.values())
                earlier_conflict = any(
                    earlier_ticket < ticket and write_set.conflicts_with(earlier_set)
                    for earlier_ticket, earlier_set in self._pending
                )
                if not active_conflict and not earlier_conflict:
                    self._pending.remove(request)
                    self._active[ticket] = write_set
                    self._counters["acquisitions"] += 1
                    self._counters["contended_acquisitions"] += int(time.monotonic() > started + 0.0001)
                    self._counters["max_parallel_merges"] = max(
                        self._counters["max_parallel_merges"], len(self._active)
                    )
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0.0:
                    self._pending.remove(request)
                    self._counters["timeouts"] += 1
                    self._condition.notify_all()
                    raise TimeoutError("timed out waiting for conflicting Codex merge")
                self._condition.wait(timeout=remaining)
            wait_seconds = time.monotonic() - started
        try:
            yield wait_seconds
        finally:
            with self._condition:
                self._active.pop(ticket, None)
                self._condition.notify_all()

    def merge(
        self,
        assignments: Sequence[ScopeAssignment],
        callback: Callable[[ScopeAssignment], Any],
        *,
        max_workers: int = MAX_INITIAL_CODEX_WORKERS,
        timeout_seconds: Optional[float] = None,
    ) -> Mapping[str, MergeResult]:
        if not callable(callback):
            raise TypeError("merge callback must be callable")

        def run(assignment: ScopeAssignment) -> MergeResult:
            started = time.monotonic()
            try:
                with self.acquire(assignment.write_set, timeout_seconds=timeout_seconds) as waited:
                    value = callback(assignment)
                accepted, evidence, error = IsolatedValidationExecutor._normalize(value)
                status = "merged" if accepted else "rejected"
            except TimeoutError as exc:
                waited, accepted, evidence, error, status = (
                    time.monotonic() - started, False, {}, str(exc), "timeout"
                )
            except Exception as exc:
                waited, accepted, evidence, error, status = (
                    0.0, False, {}, f"{type(exc).__name__}: {exc}", "failed"
                )
            return MergeResult(
                assignment.assignment_id, assignment.scope, accepted, status,
                waited, time.monotonic() - started, evidence, error,
            )

        results: dict[str, MergeResult] = {}
        if assignments:
            with ThreadPoolExecutor(
                max_workers=min(MAX_INITIAL_CODEX_WORKERS, max(1, int(max_workers)), len(assignments)),
                thread_name_prefix="codex-merge",
            ) as pool:
                futures = {pool.submit(run, item): item.assignment_id for item in assignments}
                for future in as_completed(futures):
                    result = future.result()
                    results[result.assignment_id] = result
        return MappingProxyType(dict(sorted(results.items())))

    def telemetry(self) -> dict[str, int]:
        with self._condition:
            return dict(sorted(self._counters.items()))


def predict_codex_write_set(task: CodexScopeTask | Mapping[str, Any] | Any) -> PredictedWriteSet:
    """Convenience wrapper using the production ownership catalog."""

    return WriteSetPredictor().predict(task)


def bundle_codex_scope_evidence(
    tasks: Iterable[CodexScopeTask | Mapping[str, Any] | Any], *, max_tasks: int = 16
) -> tuple[ScopeEvidenceBundle, ...]:
    """Convenience wrapper for deterministic, scope-local evidence bundling."""

    return ScopeEvidenceBundler(max_tasks=max_tasks).bundle(tasks)


def schedule_codex_scopes(
    tasks: Iterable[CodexScopeTask | Mapping[str, Any] | Any],
    *,
    max_workers: int = MAX_INITIAL_CODEX_WORKERS,
    active_write_sets: Iterable[PredictedWriteSet] = (),
    signals: SchedulerSignals | Mapping[str, Any] | None = None,
) -> ScopeSchedulePlan:
    """Build one initial conflict-aware Codex worker wave."""

    return CodexScopeScheduler(max_workers=max_workers).schedule(
        tasks, active_write_sets=active_write_sets, signals=signals
    )


# Stable shorter aliases for runtime callers and downstream benchmark tooling.
OwnershipScope = CodexOwnershipScope
CodexTask = CodexScopeTask
CodexScopeAssignment = ScopeAssignment
ConflictAwareCodexScheduler = CodexScopeScheduler
MergeSerializer = ConflictAwareMergeSerializer
AdaptiveCodexWorkerController = AdaptiveWorkerController
IsolatedValidationRunner = IsolatedValidationExecutor
WriteSet = PredictedWriteSet


__all__ = [
    "CODEX_OWNERSHIP_SCOPES",
    "CODEX_OWNERSHIP_SCOPE_LABELS",
    "CODEX_SCOPE_BUNDLE_SCHEMA_VERSION",
    "CODEX_SCOPE_SCHEDULER_SCHEMA_VERSION",
    "DEFAULT_SCOPE_OWNERSHIP",
    "MAX_INITIAL_CODEX_WORKERS",
    "AdaptiveWorkerController",
    "AdaptiveCodexWorkerController",
    "CodexOwnershipScope",
    "CodexScopeAssignment",
    "CodexScopeScheduler",
    "CodexScopeTask",
    "CodexTask",
    "ConflictAwareMergeSerializer",
    "ConflictAwareCodexScheduler",
    "IsolatedValidationExecutor",
    "IsolatedValidationResult",
    "IsolatedValidationRunner",
    "MergeResult",
    "MergeSerializer",
    "OwnershipScope",
    "PredictedWriteSet",
    "SchedulerOutcome",
    "SchedulerSignals",
    "ScopeAssignment",
    "ScopeEvidenceBundle",
    "ScopeEvidenceBundler",
    "ScopeSchedulePlan",
    "WorkerDecision",
    "WriteSetPredictor",
    "WriteSet",
    "bundle_codex_scope_evidence",
    "canonical_codex_scope",
    "predict_codex_write_set",
    "schedule_codex_scopes",
]
