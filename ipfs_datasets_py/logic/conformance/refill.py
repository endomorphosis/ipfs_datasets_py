"""Bounded objective refill to a current-tree fixed point (LFP-046).

Interfaces: ``LogicGapRefill@1``, ``ObjectiveRefillFixedPoint@1``

This module is the control-plane transaction between typed, owner-scoped
evidence gaps and an append-only derived task ledger:

* every admitted task is content-addressed over gap identity, owner paths,
  source/config/corpus identities, and validation command;
* per-epoch derived goal limits **exclude** the 11 immutable seed goals;
* open-task, attempt, depth, and cooldown bounds hold fail-closed;
* seed task definitions and protected control artifacts are never rewritten;
* duplicates and broad unscoped codebase tasks are rejected;
* two consecutive scans over identical source/config/corpus identities that
  emit no new admissible tasks constitute a fixed point.

Generated tasks and the gap ledger are evidence only — never completion or
mutation authority.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_GAP_REFILL_INTERFACE: Final = "LogicGapRefill@1"
OBJECTIVE_REFILL_FIXED_POINT_INTERFACE: Final = "ObjectiveRefillFixedPoint@1"
LOGIC_GAP_REFILL_VERSION: Final = "1.0.0"
LOGIC_GAP_REFILL_SCHEMA: Final = "logic-gap-refill/v1"
LOGIC_GAP_CANDIDATE_SCHEMA: Final = "logic-gap-refill-candidate/v1"
LOGIC_GAP_TASK_SCHEMA: Final = "logic-gap-refill-derived-task/v1"
LOGIC_GAP_LEDGER_ENTRY_SCHEMA: Final = "logic-gap-refill-ledger-entry/v1"
LOGIC_GAP_EPOCH_RECEIPT_SCHEMA: Final = "logic-gap-refill-epoch-receipt/v1"
OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA: Final = "objective-refill-fixed-point-receipt/v1"
LOGIC_GAP_REFILL_POLICY_SCHEMA: Final = "logic-gap-refill-policy/v1"

TASK_ID: Final = "LFP-046"
GOAL_ID: Final = "LFP-G090"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v1"
PRODUCER_ID: Final = "logic-gap-refill@1"

# Eleven immutable seed goals (root + ten children). Derived-goal budgets
# never count these against max_goals_per_epoch.
IMMUTABLE_SEED_GOALS: Final[tuple[str, ...]] = (
    "LFP-G000",
    "LFP-G010",
    "LFP-G020",
    "LFP-G030",
    "LFP-G040",
    "LFP-G050",
    "LFP-G060",
    "LFP-G070",
    "LFP-G080",
    "LFP-G090",
    "LFP-G100",
)
IMMUTABLE_SEED_GOAL_COUNT: Final = 11
assert len(IMMUTABLE_SEED_GOALS) == IMMUTABLE_SEED_GOAL_COUNT

DEFAULT_PARENT_GOAL_ID: Final = "LFP-G090"
DEFAULT_MAX_GOALS_PER_EPOCH: Final = 8
DEFAULT_MAX_TASKS_PER_EPOCH: Final = 24
DEFAULT_MIN_OPEN_TASKS: Final = 8
DEFAULT_MAX_OPEN_TASKS: Final = 48
DEFAULT_MAX_REFINEMENT_DEPTH: Final = 3
DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES: Final = 2
DEFAULT_COOLDOWN_SECONDS: Final = 3600
DEFAULT_MAX_PATHS: Final = 8
DEFAULT_MAX_CONTEXT_PATHS: Final = 8

DEFAULT_STOP_POLICY: Final = (
    "stop:logic-gap-refill@1:"
    "max-goals=8;max-tasks=24;max-open=48;max-depth=3;"
    "max-retries=2;cooldown=3600;seed-goals-excluded;"
    "no-seed-mutation;no-unscoped-codebase"
)

DEFAULT_PROTECTED_PATHS: Final[tuple[str, ...]] = (
    "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md",
    "docs/architecture/ipfs_datasets_logic_family_parser.objectives.md",
    "docs/architecture/ipfs_datasets_logic_family_parser.todo.md",
    "config/agent_supervisor_ipfs_datasets_logic_family_parser_scheduler.json",
    "scripts/validate_ipfs_datasets_logic_family_parser_board.py",
    "ipfs_accelerate_py/agent_supervisor/runtime/configured_board_scheduler.py",
    "ipfs_accelerate_py/agent_supervisor/runtime/grok_cli_runner.py",
    "ipfs_accelerate_py/agent_supervisor/runtime/multi_supervisor_runner.py",
    "ipfs_accelerate_py/agent_supervisor/todo_daemon/implementation_daemon.py",
)

DEFAULT_RUNTIME_REFILL_RELATIVE: Final = (
    "data/agent_supervisor/ipfs_datasets_logic_family_parser/refill"
)
DEFAULT_FIXED_POINT_RECEIPT_NAME: Final = "fixed_point_receipt.json"
DEFAULT_GAP_LEDGER_NAME: Final = "gap_ledger.jsonl"

MAX_ID_BYTES: Final = 512
MAX_TEXT_BYTES: Final = 4_096
MAX_PATH_BYTES: Final = 1_024
MAX_GAPS: Final = 256
MAX_LEDGER_ENTRIES: Final = 4_096
MAX_VALIDATION_COMMANDS: Final = 16

_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-=]{0,511}$")
_GOAL_ID_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,255}$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")

_AUTHORITY_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "completion_authority",
        "mutation_authority",
        "claims_completion",
        "may_mutate",
        "seed_board_edit",
        "authorize_self",
        "self_authorization",
        "lower_threshold",
        "threshold_override",
        "mark_complete",
        "mark_parent_complete",
        "automatic_promotion",
        "mutate_seed_board",
    }
)

# Broad unscoped patterns that indicate a non-owner-scoped codebase task.
_UNSCOPED_PATH_MARKERS: Final[frozenset[str]] = frozenset(
    {
        ".",
        "*",
        "**",
        "**/*",
        "src",
        "src/",
        "lib",
        "lib/",
        "ipfs_datasets_py",
        "ipfs_datasets_py/",
        "ipfs_accelerate_py",
        "ipfs_accelerate_py/",
        "docs",
        "docs/",
        "tests",
        "tests/",
        "test",
        "test/",
    }
)


# ---------------------------------------------------------------------------
# Errors / vocabularies
# ---------------------------------------------------------------------------


class LogicGapRefillError(ValueError):
    """A gap, policy, ledger entry, or receipt is malformed."""


class LogicGapRefillBoundsError(LogicGapRefillError):
    """A population or field exceeds a hard bound."""


class LogicGapRefillAuthorityError(LogicGapRefillError):
    """A candidate claims forbidden completion or mutation authority."""


class GapKind(StrEnum):
    """Closed origin kinds for content-addressed derived refill tasks."""

    MATRIX_CELL = "matrix_cell"
    UNREGISTERED_EMITTED_ID = "unregistered_emitted_id"
    UNDOCUMENTED_CONTROLLED_SYNTAX = "undocumented_controlled_syntax"
    STALE_CONSUMER = "stale_consumer"
    FAILING_PUBLIC_EXAMPLE = "failing_public_example"
    UNSUPPORTED_AST_NODE = "unsupported_ast_node"
    MISSING_FIXTURE = "missing_fixture"
    TRANSLATION_PRESERVATION = "translation_preservation"
    DIFFERENTIAL_DISAGREEMENT = "differential_disagreement"
    UNRECONSTRUCTED_CANDIDATE = "unreconstructed_candidate"
    PROVIDER_CAPABILITY_DRIFT = "provider_capability_drift"
    DOMAIN_VERTICAL_SLICE = "domain_vertical_slice"
    RELEASE_FLOOR = "release_floor"
    OTHER = "other"


class AdmissionDisposition(StrEnum):
    """Per-gap admission decision."""

    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    BOUND_REJECTED = "bound_rejected"
    DEPTH_REJECTED = "depth_rejected"
    RETRY_EXHAUSTED = "retry_exhausted"
    COOLDOWN = "cooldown"
    UNSCOPED_REJECTED = "unscoped_rejected"
    PROTECTED_REJECTED = "protected_rejected"
    SEED_GOAL_EXCLUDED = "seed_goal_excluded"
    AUTHORITY_REJECTED = "authority_rejected"
    MALFORMED = "malformed"
    FIXED_POINT_SKIP = "fixed_point_skip"
    NOT_REFILL_ELIGIBLE = "not_refill_eligible"


class EpochDisposition(StrEnum):
    """Stable outcomes of one refill epoch."""

    ADMITTED = "admitted"
    FIXED_POINT_CLOSED = "fixed_point_closed"
    DUPLICATE_ONLY = "duplicate_only"
    BOUND_EXCEEDED = "bound_exceeded"
    OPEN_WORK_CEILING = "open_work_ceiling"
    EMPTY_INPUT = "empty_input"
    REPLAY_NOOP = "replay_noop"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    required: bool = True,
    limit: int = MAX_TEXT_BYTES,
) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise LogicGapRefillError(f"{name} must be a string")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise LogicGapRefillError(f"{name} must be normalized single-line text")
    if required and not text:
        raise LogicGapRefillError(f"{name} is required")
    if len(text.encode("utf-8")) > limit:
        raise LogicGapRefillBoundsError(f"{name} exceeds its byte bound")
    return text


def _identifier(value: Any, name: str, *, required: bool = True) -> str:
    text = _text(value, name, required=required, limit=MAX_ID_BYTES)
    if not text:
        return ""
    if not _IDENTIFIER_RE.fullmatch(text):
        raise LogicGapRefillError(f"{name} is malformed")
    return text


def _goal_id(value: Any, name: str = "goal_id") -> str:
    text = _text(value, name, limit=MAX_ID_BYTES)
    if not _GOAL_ID_RE.fullmatch(text):
        raise LogicGapRefillError(f"{name} is malformed")
    return text


def _bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise LogicGapRefillError(f"{name} must be a boolean")


def _nonneg_int(value: Any, name: str, *, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LogicGapRefillError(f"{name} must be an integer")
    if value < 0 or value > maximum:
        raise LogicGapRefillBoundsError(f"{name} out of bounds")
    return value


def _positive_int(value: Any, name: str, *, maximum: int = 1_000_000) -> int:
    number = _nonneg_int(value, name, maximum=maximum)
    if number < 1:
        raise LogicGapRefillError(f"{name} must be >= 1")
    return number


def _enum(value: Any, enum_cls: type[StrEnum], name: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    text = _text(value, name)
    try:
        return enum_cls(text)
    except ValueError as exc:
        raise LogicGapRefillError(f"{name} has unknown value {text!r}") from exc


def _normalize_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    normalized = posixpath.normpath(raw)
    if normalized in (".",):
        return ""
    if (
        normalized.startswith("/")
        or normalized == ".."
        or normalized.startswith("../")
        or "/../" in f"/{normalized}/"
    ):
        raise LogicGapRefillError("paths must be repository-relative and non-escaping")
    return normalized


def _paths(
    values: Any,
    name: str,
    *,
    maximum: int = DEFAULT_MAX_PATHS,
    required: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, str):
        items = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = values
    else:
        raise LogicGapRefillError(f"{name} must be a sequence of paths")
    if len(items) > maximum:
        raise LogicGapRefillBoundsError(f"{name} exceeds its path bound")
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        path = _normalize_path(raw)
        if not path or path in seen:
            continue
        if len(path.encode("utf-8")) > MAX_PATH_BYTES:
            raise LogicGapRefillBoundsError(f"{name} path exceeds its byte bound")
        seen.add(path)
        out.append(path)
    if required and not out:
        raise LogicGapRefillError(f"{name} must not be empty")
    return tuple(out)


def _ids(
    values: Any,
    name: str,
    *,
    maximum: int = 64,
    required: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, str):
        items = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = values
    else:
        raise LogicGapRefillError(f"{name} must be a sequence of identifiers")
    if len(items) > maximum:
        raise LogicGapRefillBoundsError(f"{name} exceeds its item bound")
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = _identifier(raw, name, required=True)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    if required and not out:
        raise LogicGapRefillError(f"{name} must not be empty")
    return tuple(out)


def _command_strings(
    values: Any,
    name: str,
    *,
    maximum: int = MAX_VALIDATION_COMMANDS,
) -> tuple[str, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, str):
        items = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = values
    else:
        raise LogicGapRefillError(f"{name} must be a sequence of strings")
    if len(items) > maximum:
        raise LogicGapRefillBoundsError(f"{name} exceeds its item bound")
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = _text(raw, name, required=True, limit=MAX_TEXT_BYTES)
        normalized = " ".join(text.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return tuple(out)


def _mapping_proxy(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise LogicGapRefillError(f"{name} must be a mapping")
    try:
        canonical = json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise LogicGapRefillError(f"{name} must be canonical JSON data") from exc
    if not isinstance(canonical, dict):
        raise LogicGapRefillError(f"{name} must be a mapping")
    return MappingProxyType(canonical)


def _stable_digest(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        encoded = payload.encode("utf-8")
    else:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _reject_authority_claims(metadata: Mapping[str, Any], *, where: str) -> None:
    for key, value in metadata.items():
        norm = str(key).lower().replace("-", "_")
        if norm in _AUTHORITY_FORBIDDEN_KEYS and value not in (False, None, "", 0):
            raise LogicGapRefillAuthorityError(f"{where} cannot claim {key}")


def _path_hits_protected(path: str, protected: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    for anchor in protected:
        target = anchor.replace("\\", "/").strip("/")
        if normalized == target or normalized.startswith(target + "/"):
            return True
    return False


def is_unscoped_codebase_scope(paths: Sequence[str]) -> bool:
    """Return True when *paths* are missing or only broad unscoped roots."""

    if not paths:
        return True
    for path in paths:
        normalized = path.replace("\\", "/").strip("/")
        if not normalized:
            return True
        if normalized in _UNSCOPED_PATH_MARKERS:
            return True
        # Single top-level segment without a concrete owner file is unscoped.
        parts = [part for part in normalized.split("/") if part]
        if len(parts) == 1 and parts[0] in {
            "ipfs_datasets_py",
            "ipfs_accelerate_py",
            "docs",
            "tests",
            "test",
            "src",
            "lib",
            "scripts",
            "config",
            "data",
        }:
            return True
    return False


def is_seed_goal(goal_id: str) -> bool:
    """Return True when *goal_id* is one of the 11 immutable seed goals."""

    return goal_id in IMMUTABLE_SEED_GOALS


def count_derived_goals(goal_ids: Iterable[str]) -> int:
    """Count goals that count against the per-epoch derived-goal budget."""

    return sum(1 for goal_id in goal_ids if not is_seed_goal(goal_id))


# ---------------------------------------------------------------------------
# Policy / identities / gap records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicGapRefillPolicy:
    """Hard bounds for one derived refill epoch (seed goals excluded)."""

    max_goals_per_epoch: int = DEFAULT_MAX_GOALS_PER_EPOCH
    max_tasks_per_epoch: int = DEFAULT_MAX_TASKS_PER_EPOCH
    min_open_tasks: int = DEFAULT_MIN_OPEN_TASKS
    max_open_tasks: int = DEFAULT_MAX_OPEN_TASKS
    max_refinement_depth: int = DEFAULT_MAX_REFINEMENT_DEPTH
    max_unchanged_failure_retries: int = DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    max_paths: int = DEFAULT_MAX_PATHS
    max_context_paths: int = DEFAULT_MAX_CONTEXT_PATHS
    parent_goal_id: str = DEFAULT_PARENT_GOAL_ID
    mutate_seed_board: bool = False
    unscoped_codebase_refill_allowed: bool = False
    seed_tasks_are_immutable: bool = True
    protected_paths: tuple[str, ...] = DEFAULT_PROTECTED_PATHS
    stop_policy: str = DEFAULT_STOP_POLICY
    schema: str = LOGIC_GAP_REFILL_POLICY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_goals_per_epoch",
            _positive_int(self.max_goals_per_epoch, "max_goals_per_epoch", maximum=8),
        )
        object.__setattr__(
            self,
            "max_tasks_per_epoch",
            _positive_int(self.max_tasks_per_epoch, "max_tasks_per_epoch", maximum=24),
        )
        object.__setattr__(
            self,
            "min_open_tasks",
            _nonneg_int(self.min_open_tasks, "min_open_tasks", maximum=48),
        )
        object.__setattr__(
            self,
            "max_open_tasks",
            _positive_int(self.max_open_tasks, "max_open_tasks", maximum=48),
        )
        # Partial overrides (e.g. max_open_tasks=2 with default min=8) clamp
        # the floor rather than fail — the ceiling remains the hard bound.
        if self.min_open_tasks > self.max_open_tasks:
            object.__setattr__(self, "min_open_tasks", self.max_open_tasks)
        object.__setattr__(
            self,
            "max_refinement_depth",
            _positive_int(
                self.max_refinement_depth, "max_refinement_depth", maximum=8
            ),
        )
        object.__setattr__(
            self,
            "max_unchanged_failure_retries",
            _nonneg_int(
                self.max_unchanged_failure_retries,
                "max_unchanged_failure_retries",
                maximum=16,
            ),
        )
        object.__setattr__(
            self,
            "cooldown_seconds",
            _nonneg_int(self.cooldown_seconds, "cooldown_seconds", maximum=86_400),
        )
        object.__setattr__(
            self,
            "max_paths",
            _positive_int(self.max_paths, "max_paths", maximum=64),
        )
        object.__setattr__(
            self,
            "max_context_paths",
            _positive_int(self.max_context_paths, "max_context_paths", maximum=64),
        )
        object.__setattr__(self, "parent_goal_id", _goal_id(self.parent_goal_id))
        if not is_seed_goal(self.parent_goal_id):
            # Parent may be a seed goal; derived children hang under it.
            pass
        object.__setattr__(
            self, "mutate_seed_board", _bool(self.mutate_seed_board, "mutate_seed_board")
        )
        if self.mutate_seed_board:
            raise LogicGapRefillAuthorityError(
                "mutate_seed_board must remain false; seed definitions are immutable"
            )
        object.__setattr__(
            self,
            "unscoped_codebase_refill_allowed",
            _bool(
                self.unscoped_codebase_refill_allowed,
                "unscoped_codebase_refill_allowed",
            ),
        )
        object.__setattr__(
            self,
            "seed_tasks_are_immutable",
            _bool(self.seed_tasks_are_immutable, "seed_tasks_are_immutable"),
        )
        if not self.seed_tasks_are_immutable:
            raise LogicGapRefillAuthorityError("seed_tasks_are_immutable must be true")
        object.__setattr__(
            self,
            "protected_paths",
            _paths(self.protected_paths, "protected_paths", maximum=64)
            or DEFAULT_PROTECTED_PATHS,
        )
        object.__setattr__(
            self,
            "stop_policy",
            _text(self.stop_policy, "stop_policy", limit=MAX_TEXT_BYTES),
        )
        if self.schema != LOGIC_GAP_REFILL_POLICY_SCHEMA:
            raise LogicGapRefillError(
                f"policy schema must be {LOGIC_GAP_REFILL_POLICY_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "max_goals_per_epoch": self.max_goals_per_epoch,
            "max_tasks_per_epoch": self.max_tasks_per_epoch,
            "min_open_tasks": self.min_open_tasks,
            "max_open_tasks": self.max_open_tasks,
            "max_refinement_depth": self.max_refinement_depth,
            "max_unchanged_failure_retries": self.max_unchanged_failure_retries,
            "cooldown_seconds": self.cooldown_seconds,
            "max_paths": self.max_paths,
            "max_context_paths": self.max_context_paths,
            "parent_goal_id": self.parent_goal_id,
            "mutate_seed_board": self.mutate_seed_board,
            "unscoped_codebase_refill_allowed": self.unscoped_codebase_refill_allowed,
            "seed_tasks_are_immutable": self.seed_tasks_are_immutable,
            "protected_paths": list(self.protected_paths),
            "stop_policy": self.stop_policy,
            "immutable_seed_goals": list(IMMUTABLE_SEED_GOALS),
            "immutable_seed_goal_count": IMMUTABLE_SEED_GOAL_COUNT,
            "seed_goals_excluded_from_derived_budget": True,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> LogicGapRefillPolicy:
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise LogicGapRefillError("policy must be a mapping")
        known = {
            "max_goals_per_epoch",
            "max_tasks_per_epoch",
            "min_open_tasks",
            "max_open_tasks",
            "max_refinement_depth",
            "max_unchanged_failure_retries",
            "cooldown_seconds",
            "max_paths",
            "max_context_paths",
            "parent_goal_id",
            "mutate_seed_board",
            "unscoped_codebase_refill_allowed",
            "seed_tasks_are_immutable",
            "protected_paths",
            "stop_policy",
            "schema",
        }
        kwargs = {key: payload[key] for key in known if key in payload}
        return cls(**kwargs)

    @classmethod
    def default(cls) -> LogicGapRefillPolicy:
        return cls()


@dataclass(frozen=True, slots=True)
class ScanIdentity:
    """Content identities that must match across consecutive fixed-point scans."""

    source_identity: str
    config_identity: str
    corpus_identity: str
    tree_id: str = ""
    repository_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity", limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "config_identity",
            _text(self.config_identity, "config_identity", limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "corpus_identity",
            _text(self.corpus_identity, "corpus_identity", limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "tree_id",
            _text(self.tree_id, "tree_id", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "repository_id",
            _text(
                self.repository_id, "repository_id", required=False, limit=MAX_ID_BYTES
            ),
        )

    @property
    def composite_digest(self) -> str:
        return _stable_digest(
            {
                "source_identity": self.source_identity,
                "config_identity": self.config_identity,
                "corpus_identity": self.corpus_identity,
                "tree_id": self.tree_id,
                "repository_id": self.repository_id,
            }
        )

    def matches(self, other: ScanIdentity) -> bool:
        return (
            self.source_identity == other.source_identity
            and self.config_identity == other.config_identity
            and self.corpus_identity == other.corpus_identity
            and self.tree_id == other.tree_id
            and self.repository_id == other.repository_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identity": self.source_identity,
            "config_identity": self.config_identity,
            "corpus_identity": self.corpus_identity,
            "tree_id": self.tree_id,
            "repository_id": self.repository_id,
            "composite_digest": self.composite_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ScanIdentity:
        if not isinstance(payload, Mapping):
            raise LogicGapRefillError("scan identity must be a mapping")
        return cls(
            source_identity=payload.get("source_identity", ""),
            config_identity=payload.get("config_identity", ""),
            corpus_identity=payload.get("corpus_identity", ""),
            tree_id=payload.get("tree_id", ""),
            repository_id=payload.get("repository_id", ""),
        )


@dataclass(frozen=True, slots=True)
class LogicGapRecord:
    """One owner-scoped typed gap eligible for bounded derived refill."""

    gap_id: str
    gap_kind: GapKind
    owner: str
    subject: str
    evidence: str = ""
    originating_goal_id: str = DEFAULT_PARENT_GOAL_ID
    family_id: str = ""
    profile_id: str = ""
    source_schema: str = ""
    target_schema: str = ""
    preservation_kind: str = ""
    authority_ceiling: str = "none"
    owned_paths: tuple[str, ...] = ()
    context_paths: tuple[str, ...] = ()
    fixture_ids: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    depth: int = 1
    attempt_count: int = 0
    last_attempt_epoch_s: int = 0
    last_failure_fingerprint: str = ""
    refill_eligible: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = LOGIC_GAP_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(self, "gap_kind", _enum(self.gap_kind, GapKind, "gap_kind"))
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        object.__setattr__(
            self,
            "evidence",
            _text(self.evidence, "evidence", required=False, limit=MAX_TEXT_BYTES),
        )
        object.__setattr__(
            self, "originating_goal_id", _goal_id(self.originating_goal_id)
        )
        object.__setattr__(
            self,
            "family_id",
            _text(self.family_id, "family_id", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "profile_id",
            _text(self.profile_id, "profile_id", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "source_schema",
            _text(
                self.source_schema, "source_schema", required=False, limit=MAX_ID_BYTES
            ),
        )
        object.__setattr__(
            self,
            "target_schema",
            _text(
                self.target_schema, "target_schema", required=False, limit=MAX_ID_BYTES
            ),
        )
        object.__setattr__(
            self,
            "preservation_kind",
            _text(
                self.preservation_kind,
                "preservation_kind",
                required=False,
                limit=MAX_ID_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _text(
                self.authority_ceiling,
                "authority_ceiling",
                required=False,
                limit=MAX_ID_BYTES,
            )
            or "none",
        )
        object.__setattr__(
            self,
            "owned_paths",
            _paths(self.owned_paths, "owned_paths", maximum=DEFAULT_MAX_PATHS),
        )
        object.__setattr__(
            self,
            "context_paths",
            _paths(
                self.context_paths, "context_paths", maximum=DEFAULT_MAX_CONTEXT_PATHS
            ),
        )
        object.__setattr__(
            self,
            "fixture_ids",
            _ids(self.fixture_ids, "fixture_ids", maximum=32),
        )
        object.__setattr__(
            self,
            "validation_commands",
            _command_strings(self.validation_commands, "validation_commands"),
        )
        object.__setattr__(
            self,
            "dependencies",
            _ids(self.dependencies, "dependencies", maximum=32),
        )
        object.__setattr__(
            self, "depth", _nonneg_int(self.depth, "depth", maximum=16)
        )
        object.__setattr__(
            self,
            "attempt_count",
            _nonneg_int(self.attempt_count, "attempt_count", maximum=1_000),
        )
        object.__setattr__(
            self,
            "last_attempt_epoch_s",
            _nonneg_int(
                self.last_attempt_epoch_s, "last_attempt_epoch_s", maximum=4_102_444_800
            ),
        )
        object.__setattr__(
            self,
            "last_failure_fingerprint",
            _text(
                self.last_failure_fingerprint,
                "last_failure_fingerprint",
                required=False,
                limit=MAX_ID_BYTES,
            ),
        )
        object.__setattr__(
            self, "refill_eligible", _bool(self.refill_eligible, "refill_eligible")
        )
        object.__setattr__(
            self, "metadata", _mapping_proxy(self.metadata, "metadata")
        )
        _reject_authority_claims(self.metadata, where=f"gap {self.gap_id}")
        if self.schema != LOGIC_GAP_CANDIDATE_SCHEMA:
            raise LogicGapRefillError(
                f"gap schema must be {LOGIC_GAP_CANDIDATE_SCHEMA}"
            )

    @property
    def content_digest(self) -> str:
        """Stable identity over the gap body (excludes attempt counters)."""

        return _stable_digest(
            {
                "gap_id": self.gap_id,
                "gap_kind": self.gap_kind.value,
                "owner": self.owner,
                "subject": self.subject,
                "evidence": self.evidence,
                "originating_goal_id": self.originating_goal_id,
                "family_id": self.family_id,
                "profile_id": self.profile_id,
                "source_schema": self.source_schema,
                "target_schema": self.target_schema,
                "preservation_kind": self.preservation_kind,
                "authority_ceiling": self.authority_ceiling,
                "owned_paths": list(self.owned_paths),
                "fixture_ids": list(self.fixture_ids),
                "validation_commands": list(self.validation_commands),
                "dependencies": list(self.dependencies),
                "depth": self.depth,
            }
        )

    @property
    def identity_key(self) -> str:
        return self.content_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "gap_id": self.gap_id,
            "gap_kind": self.gap_kind.value,
            "owner": self.owner,
            "subject": self.subject,
            "evidence": self.evidence,
            "originating_goal_id": self.originating_goal_id,
            "family_id": self.family_id,
            "profile_id": self.profile_id,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "preservation_kind": self.preservation_kind,
            "authority_ceiling": self.authority_ceiling,
            "owned_paths": list(self.owned_paths),
            "context_paths": list(self.context_paths),
            "fixture_ids": list(self.fixture_ids),
            "validation_commands": list(self.validation_commands),
            "dependencies": list(self.dependencies),
            "depth": self.depth,
            "attempt_count": self.attempt_count,
            "last_attempt_epoch_s": self.last_attempt_epoch_s,
            "last_failure_fingerprint": self.last_failure_fingerprint,
            "refill_eligible": self.refill_eligible,
            "metadata": dict(self.metadata),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LogicGapRecord:
        if not isinstance(payload, Mapping):
            raise LogicGapRefillError("gap record must be a mapping")
        return cls(
            gap_id=payload.get("gap_id", ""),
            gap_kind=payload.get("gap_kind", GapKind.OTHER),
            owner=payload.get("owner", ""),
            subject=payload.get("subject", ""),
            evidence=payload.get("evidence", ""),
            originating_goal_id=payload.get(
                "originating_goal_id", DEFAULT_PARENT_GOAL_ID
            ),
            family_id=payload.get("family_id", ""),
            profile_id=payload.get("profile_id", ""),
            source_schema=payload.get("source_schema", ""),
            target_schema=payload.get("target_schema", ""),
            preservation_kind=payload.get("preservation_kind", ""),
            authority_ceiling=payload.get("authority_ceiling", "none"),
            owned_paths=payload.get("owned_paths", ()),
            context_paths=payload.get("context_paths", ()),
            fixture_ids=payload.get("fixture_ids", ()),
            validation_commands=payload.get("validation_commands", ()),
            dependencies=payload.get("dependencies", ()),
            depth=payload.get("depth", 1),
            attempt_count=payload.get("attempt_count", 0),
            last_attempt_epoch_s=payload.get("last_attempt_epoch_s", 0),
            last_failure_fingerprint=payload.get("last_failure_fingerprint", ""),
            refill_eligible=payload.get("refill_eligible", True),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class DerivedTaskProposal:
    """One content-addressed derived task admitted into the gap ledger."""

    task_id: str
    task_cid: str
    gap_id: str
    identity_key: str
    goal_id: str
    title: str
    owned_paths: tuple[str, ...]
    context_paths: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    depth: int = 1
    family_id: str = ""
    profile_id: str = ""
    authority_ceiling: str = "none"
    gap_kind: str = GapKind.OTHER.value
    stop_policy: str = DEFAULT_STOP_POLICY
    schema: str = LOGIC_GAP_TASK_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "task_cid", _text(self.task_cid, "task_cid"))
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "identity_key", _text(self.identity_key, "identity_key")
        )
        object.__setattr__(self, "goal_id", _goal_id(self.goal_id))
        object.__setattr__(self, "title", _text(self.title, "title"))
        object.__setattr__(
            self,
            "owned_paths",
            _paths(self.owned_paths, "owned_paths", required=True),
        )
        object.__setattr__(
            self,
            "context_paths",
            _paths(self.context_paths, "context_paths", maximum=DEFAULT_MAX_CONTEXT_PATHS),
        )
        object.__setattr__(
            self,
            "validation_commands",
            _command_strings(self.validation_commands, "validation_commands"),
        )
        object.__setattr__(
            self,
            "acceptance_criteria",
            _command_strings(self.acceptance_criteria, "acceptance_criteria"),
        )
        object.__setattr__(
            self,
            "dependencies",
            _ids(self.dependencies, "dependencies", maximum=32),
        )
        object.__setattr__(
            self, "depth", _nonneg_int(self.depth, "depth", maximum=16)
        )
        object.__setattr__(
            self,
            "family_id",
            _text(self.family_id, "family_id", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "profile_id",
            _text(self.profile_id, "profile_id", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _text(
                self.authority_ceiling,
                "authority_ceiling",
                required=False,
                limit=MAX_ID_BYTES,
            )
            or "none",
        )
        object.__setattr__(
            self,
            "gap_kind",
            _text(self.gap_kind, "gap_kind", limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "stop_policy",
            _text(self.stop_policy, "stop_policy", limit=MAX_TEXT_BYTES),
        )
        if is_seed_goal(self.goal_id):
            # Derived tasks hang under a seed parent but never rewrite seed goals.
            pass
        if self.schema != LOGIC_GAP_TASK_SCHEMA:
            raise LogicGapRefillError(f"task schema must be {LOGIC_GAP_TASK_SCHEMA}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_cid": self.task_cid,
            "gap_id": self.gap_id,
            "identity_key": self.identity_key,
            "goal_id": self.goal_id,
            "title": self.title,
            "owned_paths": list(self.owned_paths),
            "context_paths": list(self.context_paths),
            "validation_commands": list(self.validation_commands),
            "acceptance_criteria": list(self.acceptance_criteria),
            "dependencies": list(self.dependencies),
            "depth": self.depth,
            "family_id": self.family_id,
            "profile_id": self.profile_id,
            "authority_ceiling": self.authority_ceiling,
            "gap_kind": self.gap_kind,
            "stop_policy": self.stop_policy,
            "completion_authority": False,
            "mutation_authority": False,
            "seed_board_edit": False,
        }


@dataclass(frozen=True, slots=True)
class GapAdmissionDecision:
    """Per-gap decision recorded in the append-only ledger."""

    gap_id: str
    identity_key: str
    disposition: AdmissionDisposition
    reason_codes: tuple[str, ...] = ()
    task_id: str = ""
    task_cid: str = ""
    goal_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "identity_key", _text(self.identity_key, "identity_key")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, AdmissionDisposition, "disposition"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _ids(self.reason_codes, "reason_codes", maximum=32),
        )
        object.__setattr__(
            self,
            "task_id",
            _identifier(self.task_id, "task_id", required=False),
        )
        object.__setattr__(
            self,
            "task_cid",
            _text(self.task_cid, "task_cid", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "goal_id",
            _text(self.goal_id, "goal_id", required=False, limit=MAX_ID_BYTES),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "identity_key": self.identity_key,
            "disposition": self.disposition.value,
            "reason_codes": list(self.reason_codes),
            "task_id": self.task_id,
            "task_cid": self.task_cid,
            "goal_id": self.goal_id,
        }


@dataclass(frozen=True, slots=True)
class GapLedgerEntry:
    """One append-only ledger row for a gap admission decision."""

    entry_id: str
    epoch_id: str
    decision: GapAdmissionDecision
    scan_identity: ScanIdentity
    gap_digest: str
    sequence: int
    schema: str = LOGIC_GAP_LEDGER_ENTRY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _identifier(self.entry_id, "entry_id"))
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        if not isinstance(self.decision, GapAdmissionDecision):
            raise LogicGapRefillError("decision must be GapAdmissionDecision")
        if not isinstance(self.scan_identity, ScanIdentity):
            raise LogicGapRefillError("scan_identity must be ScanIdentity")
        object.__setattr__(self, "gap_digest", _text(self.gap_digest, "gap_digest"))
        object.__setattr__(
            self, "sequence", _nonneg_int(self.sequence, "sequence", maximum=1_000_000)
        )
        if self.schema != LOGIC_GAP_LEDGER_ENTRY_SCHEMA:
            raise LogicGapRefillError(
                f"ledger schema must be {LOGIC_GAP_LEDGER_ENTRY_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "entry_id": self.entry_id,
            "epoch_id": self.epoch_id,
            "sequence": self.sequence,
            "gap_digest": self.gap_digest,
            "decision": self.decision.to_dict(),
            "scan_identity": self.scan_identity.to_dict(),
        }

    def to_jsonl(self) -> str:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )


@dataclass(frozen=True, slots=True)
class RefillMemory:
    """In-epoch and cross-epoch memory for dedupe, retries, and open work."""

    admitted_identity_keys: tuple[str, ...] = ()
    open_task_count: int = 0
    attempt_counts: Mapping[str, int] = field(default_factory=dict)
    last_failure_fingerprints: Mapping[str, str] = field(default_factory=dict)
    last_attempt_epoch_s: Mapping[str, int] = field(default_factory=dict)
    now_epoch_s: int = 0
    derived_goal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "admitted_identity_keys",
            _ids(
                self.admitted_identity_keys,
                "admitted_identity_keys",
                maximum=MAX_LEDGER_ENTRIES,
            ),
        )
        object.__setattr__(
            self,
            "open_task_count",
            _nonneg_int(self.open_task_count, "open_task_count", maximum=1_000_000),
        )
        attempts = _mapping_proxy(self.attempt_counts, "attempt_counts")
        for key, value in attempts.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LogicGapRefillError("attempt_counts values must be non-negative ints")
        object.__setattr__(self, "attempt_counts", attempts)
        fps = _mapping_proxy(
            self.last_failure_fingerprints, "last_failure_fingerprints"
        )
        object.__setattr__(self, "last_failure_fingerprints", fps)
        last = _mapping_proxy(self.last_attempt_epoch_s, "last_attempt_epoch_s")
        object.__setattr__(self, "last_attempt_epoch_s", last)
        object.__setattr__(
            self,
            "now_epoch_s",
            _nonneg_int(self.now_epoch_s, "now_epoch_s", maximum=4_102_444_800),
        )
        object.__setattr__(
            self,
            "derived_goal_ids",
            _ids(self.derived_goal_ids, "derived_goal_ids", maximum=256),
        )

    def with_admission(
        self,
        *,
        identity_key: str,
        goal_id: str,
        open_delta: int = 1,
    ) -> RefillMemory:
        admitted = list(self.admitted_identity_keys)
        if identity_key not in admitted:
            admitted.append(identity_key)
        derived = list(self.derived_goal_ids)
        if goal_id and not is_seed_goal(goal_id) and goal_id not in derived:
            derived.append(goal_id)
        return RefillMemory(
            admitted_identity_keys=tuple(admitted),
            open_task_count=self.open_task_count + open_delta,
            attempt_counts=dict(self.attempt_counts),
            last_failure_fingerprints=dict(self.last_failure_fingerprints),
            last_attempt_epoch_s=dict(self.last_attempt_epoch_s),
            now_epoch_s=self.now_epoch_s,
            derived_goal_ids=tuple(derived),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_identity_keys": list(self.admitted_identity_keys),
            "open_task_count": self.open_task_count,
            "attempt_counts": dict(self.attempt_counts),
            "last_failure_fingerprints": dict(self.last_failure_fingerprints),
            "last_attempt_epoch_s": dict(self.last_attempt_epoch_s),
            "now_epoch_s": self.now_epoch_s,
            "derived_goal_ids": list(self.derived_goal_ids),
        }


@dataclass(frozen=True, slots=True)
class EpochReceipt:
    """Result of one bounded refill epoch scan."""

    disposition: EpochDisposition
    epoch_id: str
    scan_identity: ScanIdentity
    decisions: tuple[GapAdmissionDecision, ...] = ()
    admitted_tasks: tuple[DerivedTaskProposal, ...] = ()
    ledger_entries: tuple[GapLedgerEntry, ...] = ()
    policy: LogicGapRefillPolicy = field(default_factory=LogicGapRefillPolicy)
    memory: RefillMemory = field(default_factory=RefillMemory)
    derived_goal_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    seed_definitions_mutated: bool = False
    schema: str = LOGIC_GAP_EPOCH_RECEIPT_SCHEMA
    interface: str = LOGIC_GAP_REFILL_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, EpochDisposition, "disposition"),
        )
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        if not isinstance(self.scan_identity, ScanIdentity):
            raise LogicGapRefillError("scan_identity must be ScanIdentity")
        if not isinstance(self.policy, LogicGapRefillPolicy):
            object.__setattr__(
                self, "policy", LogicGapRefillPolicy.from_dict(self.policy)
            )
        if not isinstance(self.memory, RefillMemory):
            raise LogicGapRefillError("memory must be RefillMemory")
        object.__setattr__(
            self,
            "derived_goal_ids",
            _ids(self.derived_goal_ids, "derived_goal_ids", maximum=256),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _ids(self.reason_codes, "reason_codes", maximum=64),
        )
        object.__setattr__(
            self,
            "seed_definitions_mutated",
            _bool(self.seed_definitions_mutated, "seed_definitions_mutated"),
        )
        if self.seed_definitions_mutated:
            raise LogicGapRefillAuthorityError(
                "epoch receipt cannot report seed definition mutation"
            )
        if self.interface != LOGIC_GAP_REFILL_INTERFACE:
            raise LogicGapRefillError(
                f"interface must be {LOGIC_GAP_REFILL_INTERFACE}"
            )
        if self.schema != LOGIC_GAP_EPOCH_RECEIPT_SCHEMA:
            raise LogicGapRefillError(
                f"epoch schema must be {LOGIC_GAP_EPOCH_RECEIPT_SCHEMA}"
            )
        # Bounds invariants.
        if len(self.admitted_tasks) > self.policy.max_tasks_per_epoch:
            raise LogicGapRefillBoundsError("admitted tasks exceed max_tasks_per_epoch")
        derived_count = count_derived_goals(self.derived_goal_ids)
        if derived_count > self.policy.max_goals_per_epoch:
            raise LogicGapRefillBoundsError(
                "derived goals exceed max_goals_per_epoch (seed goals excluded)"
            )
        for goal_id in self.derived_goal_ids:
            if is_seed_goal(goal_id):
                raise LogicGapRefillBoundsError(
                    f"seed goal {goal_id} must not appear in derived_goal_ids"
                )
        if self.memory.open_task_count > self.policy.max_open_tasks:
            raise LogicGapRefillBoundsError("open_task_count exceeds max_open_tasks")

    @property
    def admits_work(self) -> bool:
        return bool(self.admitted_tasks)

    @property
    def receipt_digest(self) -> str:
        return _stable_digest(
            {
                "disposition": self.disposition.value,
                "epoch_id": self.epoch_id,
                "scan_identity": self.scan_identity.to_dict(),
                "admitted_task_cids": [task.task_cid for task in self.admitted_tasks],
                "decision_dispositions": [
                    decision.disposition.value for decision in self.decisions
                ],
                "derived_goal_ids": list(self.derived_goal_ids),
                "reason_codes": list(self.reason_codes),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "version": LOGIC_GAP_REFILL_VERSION,
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "program_id": PROGRAM_ID,
            "producer_id": PRODUCER_ID,
            "disposition": self.disposition.value,
            "epoch_id": self.epoch_id,
            "scan_identity": self.scan_identity.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "admitted_tasks": [task.to_dict() for task in self.admitted_tasks],
            "ledger_entries": [entry.to_dict() for entry in self.ledger_entries],
            "policy": self.policy.to_dict(),
            "memory": self.memory.to_dict(),
            "derived_goal_ids": list(self.derived_goal_ids),
            "derived_goal_count": count_derived_goals(self.derived_goal_ids),
            "immutable_seed_goals_excluded": True,
            "immutable_seed_goal_count": IMMUTABLE_SEED_GOAL_COUNT,
            "reason_codes": list(self.reason_codes),
            "seed_definitions_mutated": self.seed_definitions_mutated,
            "completion_authority": False,
            "mutation_authority": False,
            "receipt_digest": self.receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class FixedPointReceipt:
    """ObjectiveRefillFixedPoint@1 receipt for two consecutive identical scans."""

    is_fixed_point: bool
    scan_identity: ScanIdentity
    first_epoch: EpochReceipt
    second_epoch: EpochReceipt
    consecutive_empty_scans: int
    gap_ledger_digest: str
    policy: LogicGapRefillPolicy = field(default_factory=LogicGapRefillPolicy)
    reason_codes: tuple[str, ...] = ()
    schema: str = OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA
    interface: str = OBJECTIVE_REFILL_FIXED_POINT_INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "is_fixed_point", _bool(self.is_fixed_point, "is_fixed_point")
        )
        if not isinstance(self.scan_identity, ScanIdentity):
            raise LogicGapRefillError("scan_identity must be ScanIdentity")
        if not isinstance(self.first_epoch, EpochReceipt):
            raise LogicGapRefillError("first_epoch must be EpochReceipt")
        if not isinstance(self.second_epoch, EpochReceipt):
            raise LogicGapRefillError("second_epoch must be EpochReceipt")
        if not self.first_epoch.scan_identity.matches(self.second_epoch.scan_identity):
            raise LogicGapRefillError(
                "fixed-point scans require identical source/config/corpus identities"
            )
        if not self.scan_identity.matches(self.first_epoch.scan_identity):
            raise LogicGapRefillError(
                "receipt scan_identity must match epoch scan identities"
            )
        object.__setattr__(
            self,
            "consecutive_empty_scans",
            _nonneg_int(
                self.consecutive_empty_scans,
                "consecutive_empty_scans",
                maximum=1_000,
            ),
        )
        object.__setattr__(
            self,
            "gap_ledger_digest",
            _text(self.gap_ledger_digest, "gap_ledger_digest"),
        )
        if not isinstance(self.policy, LogicGapRefillPolicy):
            object.__setattr__(
                self, "policy", LogicGapRefillPolicy.from_dict(self.policy)
            )
        object.__setattr__(
            self,
            "reason_codes",
            _ids(self.reason_codes, "reason_codes", maximum=64),
        )
        if self.interface != OBJECTIVE_REFILL_FIXED_POINT_INTERFACE:
            raise LogicGapRefillError(
                f"interface must be {OBJECTIVE_REFILL_FIXED_POINT_INTERFACE}"
            )
        if self.schema != OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA:
            raise LogicGapRefillError(
                f"schema must be {OBJECTIVE_FIXED_POINT_RECEIPT_SCHEMA}"
            )
        if self.task_id != TASK_ID:
            raise LogicGapRefillError(f"task_id must be {TASK_ID}")
        if self.goal_id != GOAL_ID:
            raise LogicGapRefillError(f"goal_id must be {GOAL_ID}")
        # Fixed point requires two consecutive scans with zero new admissions.
        if self.is_fixed_point:
            if self.first_epoch.admits_work or self.second_epoch.admits_work:
                raise LogicGapRefillError(
                    "is_fixed_point requires both epochs to admit no new tasks"
                )
            if self.consecutive_empty_scans < 2:
                raise LogicGapRefillError(
                    "is_fixed_point requires consecutive_empty_scans >= 2"
                )

    @property
    def receipt_digest(self) -> str:
        return _stable_digest(
            {
                "is_fixed_point": self.is_fixed_point,
                "scan_identity": self.scan_identity.to_dict(),
                "first_epoch_digest": self.first_epoch.receipt_digest,
                "second_epoch_digest": self.second_epoch.receipt_digest,
                "consecutive_empty_scans": self.consecutive_empty_scans,
                "gap_ledger_digest": self.gap_ledger_digest,
                "reason_codes": list(self.reason_codes),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "version": LOGIC_GAP_REFILL_VERSION,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "program_id": PROGRAM_ID,
            "producer_id": PRODUCER_ID,
            "is_fixed_point": self.is_fixed_point,
            "consecutive_empty_scans": self.consecutive_empty_scans,
            "scan_identity": self.scan_identity.to_dict(),
            "first_epoch": self.first_epoch.to_dict(),
            "second_epoch": self.second_epoch.to_dict(),
            "gap_ledger_digest": self.gap_ledger_digest,
            "policy": self.policy.to_dict(),
            "reason_codes": list(self.reason_codes),
            "immutable_seed_goals": list(IMMUTABLE_SEED_GOALS),
            "immutable_seed_goal_count": IMMUTABLE_SEED_GOAL_COUNT,
            "seed_definitions_mutated": False,
            "completion_authority": False,
            "mutation_authority": False,
            "seed_board_edit": False,
            "receipt_digest": self.receipt_digest,
        }


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


def _derived_goal_id_for(gap: LogicGapRecord, *, parent_goal_id: str) -> str:
    """Build a derived (non-seed) goal id hanging under the parent seed goal."""

    short = hashlib.sha256(gap.identity_key.encode("utf-8")).hexdigest()[:8]
    # Explicit non-seed prefix so budget counting excludes seed goals.
    return f"LFP-D-{parent_goal_id}-{short}"


def _task_id_for(gap: LogicGapRecord, sequence: int) -> str:
    short = hashlib.sha256(gap.identity_key.encode("utf-8")).hexdigest()[:10]
    return f"LFP-R{sequence:04d}-{short}"


def _task_cid_for(
    task_id: str,
    gap: LogicGapRecord,
    scan_identity: ScanIdentity,
) -> str:
    return _stable_digest(
        {
            "task_id": task_id,
            "gap_identity": gap.identity_key,
            "owned_paths": list(gap.owned_paths),
            "scan": scan_identity.to_dict(),
            "validation_commands": list(gap.validation_commands),
            "producer": PRODUCER_ID,
        }
    )


def _default_validation_commands(gap: LogicGapRecord) -> tuple[str, ...]:
    if gap.validation_commands:
        return gap.validation_commands
    return (
        "cd ipfs_datasets_py && python -m pytest -q "
        "tests/unit/logic/conformance/test_refill.py",
    )


def _default_acceptance(gap: LogicGapRecord) -> tuple[str, ...]:
    return (
        f"resolve gap {gap.gap_id} of kind {gap.gap_kind.value}",
        "owner-scoped paths only",
        "no seed board mutation",
        "no completion authority",
    )


def _evaluate_gap(
    gap: LogicGapRecord,
    *,
    policy: LogicGapRefillPolicy,
    memory: RefillMemory,
    admitted_this_epoch: int,
    derived_goals_this_epoch: set[str],
    now_epoch_s: int,
) -> tuple[AdmissionDisposition, tuple[str, ...]]:
    if not gap.refill_eligible:
        return AdmissionDisposition.NOT_REFILL_ELIGIBLE, ("not_refill_eligible",)

    if gap.identity_key in memory.admitted_identity_keys:
        return AdmissionDisposition.DUPLICATE, ("duplicate_identity",)

    if gap.depth > policy.max_refinement_depth:
        return AdmissionDisposition.DEPTH_REJECTED, ("depth_exceeded",)

    # Unchanged failure retry / cooldown.
    prior_attempts = int(memory.attempt_counts.get(gap.identity_key, gap.attempt_count))
    prior_fp = str(
        memory.last_failure_fingerprints.get(
            gap.identity_key, gap.last_failure_fingerprint
        )
        or ""
    )
    if prior_fp and prior_fp == gap.last_failure_fingerprint:
        if prior_attempts >= policy.max_unchanged_failure_retries:
            return AdmissionDisposition.RETRY_EXHAUSTED, ("retry_exhausted",)
        last_ts = int(
            memory.last_attempt_epoch_s.get(
                gap.identity_key, gap.last_attempt_epoch_s
            )
            or 0
        )
        if last_ts and now_epoch_s and (now_epoch_s - last_ts) < policy.cooldown_seconds:
            return AdmissionDisposition.COOLDOWN, ("cooldown_active",)

    scope_paths = gap.owned_paths
    if not policy.unscoped_codebase_refill_allowed and is_unscoped_codebase_scope(
        scope_paths
    ):
        return AdmissionDisposition.UNSCOPED_REJECTED, ("unscoped_codebase",)

    protected_hits = [
        path
        for path in scope_paths
        if _path_hits_protected(path, policy.protected_paths)
    ]
    if protected_hits:
        return AdmissionDisposition.PROTECTED_REJECTED, ("protected_path",)

    # Attempting to place a derived *goal* that collides with a seed goal id
    # is rejected; derived tasks may hang under seed parents.
    if is_seed_goal(gap.originating_goal_id) is False:
        # Originating goal is already derived; count against budget when new.
        pass

    open_budget = policy.max_open_tasks - memory.open_task_count
    if open_budget <= 0:
        return AdmissionDisposition.BOUND_REJECTED, ("open_work_ceiling",)

    if admitted_this_epoch >= policy.max_tasks_per_epoch:
        return AdmissionDisposition.BOUND_REJECTED, ("task_bound",)

    # Derived goal budget (seed goals excluded).
    candidate_goal = _derived_goal_id_for(gap, parent_goal_id=policy.parent_goal_id)
    prospective_goals = set(derived_goals_this_epoch)
    if candidate_goal not in prospective_goals and not is_seed_goal(candidate_goal):
        if len(prospective_goals) >= policy.max_goals_per_epoch:
            return AdmissionDisposition.BOUND_REJECTED, ("goal_bound",)

    return AdmissionDisposition.ADMITTED, ("admitted",)


def run_refill_epoch(
    gaps: Sequence[LogicGapRecord | Mapping[str, Any]],
    *,
    scan_identity: ScanIdentity | Mapping[str, Any],
    policy: LogicGapRefillPolicy | Mapping[str, Any] | None = None,
    memory: RefillMemory | None = None,
    epoch_id: str = "",
    now_epoch_s: int | None = None,
    ledger_sequence_start: int = 0,
) -> EpochReceipt:
    """Admit a bounded set of content-addressed derived tasks from typed gaps.

    Seed goal definitions are never rewritten.  Per-epoch derived-goal limits
    exclude the 11 immutable seed goals.  Duplicates and unscoped codebase
    tasks are rejected fail-closed.
    """

    if policy is None:
        policy = LogicGapRefillPolicy.default()
    elif isinstance(policy, Mapping):
        policy = LogicGapRefillPolicy.from_dict(policy)
    elif not isinstance(policy, LogicGapRefillPolicy):
        raise LogicGapRefillError("policy must be LogicGapRefillPolicy or mapping")

    if isinstance(scan_identity, Mapping):
        scan_identity = ScanIdentity.from_dict(scan_identity)
    elif not isinstance(scan_identity, ScanIdentity):
        raise LogicGapRefillError("scan_identity must be ScanIdentity or mapping")

    if memory is None:
        memory = RefillMemory(now_epoch_s=now_epoch_s or 0)
    now = now_epoch_s if now_epoch_s is not None else memory.now_epoch_s

    if len(gaps) > MAX_GAPS:
        raise LogicGapRefillBoundsError(f"gaps exceed hard bound of {MAX_GAPS}")

    normalized: list[LogicGapRecord] = []
    for raw in gaps:
        if isinstance(raw, LogicGapRecord):
            normalized.append(raw)
        elif isinstance(raw, Mapping):
            normalized.append(LogicGapRecord.from_dict(raw))
        else:
            raise LogicGapRefillError("each gap must be LogicGapRecord or mapping")

    # Deterministic order by gap identity (gap_id), then content digest.
    # gap_id primary so admission order is stable and independent of input order
    # and of opaque content-hash ordering.
    normalized.sort(key=lambda gap: (gap.gap_id, gap.identity_key))

    if not epoch_id:
        epoch_id = "epoch:" + _stable_digest(
            {
                "scan": scan_identity.composite_digest,
                "gap_ids": [gap.gap_id for gap in normalized],
                "policy": policy.to_dict(),
            }
        )[7:23]

    decisions: list[GapAdmissionDecision] = []
    admitted_tasks: list[DerivedTaskProposal] = []
    ledger_entries: list[GapLedgerEntry] = []
    derived_goals: set[str] = set(memory.derived_goal_ids)
    epoch_derived_goals: set[str] = set()
    reason_codes: list[str] = []
    next_memory = memory
    sequence = ledger_sequence_start

    if not normalized:
        return EpochReceipt(
            disposition=EpochDisposition.EMPTY_INPUT,
            epoch_id=epoch_id,
            scan_identity=scan_identity,
            decisions=(),
            admitted_tasks=(),
            ledger_entries=(),
            policy=policy,
            memory=next_memory,
            derived_goal_ids=tuple(sorted(derived_goals)),
            reason_codes=("empty_input",),
            seed_definitions_mutated=False,
        )

    for gap in normalized:
        disposition, reasons = _evaluate_gap(
            gap,
            policy=policy,
            memory=next_memory,
            admitted_this_epoch=len(admitted_tasks),
            derived_goals_this_epoch=epoch_derived_goals,
            now_epoch_s=now,
        )

        task_id = ""
        task_cid = ""
        goal_id = ""
        if disposition is AdmissionDisposition.ADMITTED:
            goal_id = _derived_goal_id_for(gap, parent_goal_id=policy.parent_goal_id)
            if is_seed_goal(goal_id):
                # Defensive: derived goal construction must never collide.
                disposition = AdmissionDisposition.SEED_GOAL_EXCLUDED
                reasons = ("seed_goal_collision",)
            else:
                sequence += 1
                task_id = _task_id_for(gap, sequence)
                task_cid = _task_cid_for(task_id, gap, scan_identity)
                owned = gap.owned_paths[: policy.max_paths]
                context = (gap.context_paths or owned)[: policy.max_context_paths]
                task = DerivedTaskProposal(
                    task_id=task_id,
                    task_cid=task_cid,
                    gap_id=gap.gap_id,
                    identity_key=gap.identity_key,
                    goal_id=goal_id,
                    title=(
                        f"Derived refill for {gap.gap_kind.value}: {gap.subject}"
                    )[:256],
                    owned_paths=owned,
                    context_paths=context,
                    validation_commands=_default_validation_commands(gap),
                    acceptance_criteria=_default_acceptance(gap),
                    dependencies=gap.dependencies,
                    depth=gap.depth,
                    family_id=gap.family_id,
                    profile_id=gap.profile_id,
                    authority_ceiling=gap.authority_ceiling,
                    gap_kind=gap.gap_kind.value,
                    stop_policy=policy.stop_policy,
                )
                admitted_tasks.append(task)
                epoch_derived_goals.add(goal_id)
                derived_goals.add(goal_id)
                next_memory = next_memory.with_admission(
                    identity_key=gap.identity_key,
                    goal_id=goal_id,
                    open_delta=1,
                )

        decision = GapAdmissionDecision(
            gap_id=gap.gap_id,
            identity_key=gap.identity_key,
            disposition=disposition,
            reason_codes=reasons,
            task_id=task_id,
            task_cid=task_cid,
            goal_id=goal_id,
        )
        decisions.append(decision)
        reason_codes.extend(reasons)

        entry = GapLedgerEntry(
            entry_id=f"ledger:{epoch_id}:{sequence if task_id else gap.gap_id}",
            epoch_id=epoch_id,
            decision=decision,
            scan_identity=scan_identity,
            gap_digest=gap.content_digest,
            sequence=sequence if task_id else ledger_sequence_start + len(decisions),
        )
        ledger_entries.append(entry)

    # Classify epoch disposition.
    if admitted_tasks:
        epoch_disposition = EpochDisposition.ADMITTED
    elif all(
        decision.disposition is AdmissionDisposition.DUPLICATE
        for decision in decisions
    ):
        epoch_disposition = EpochDisposition.DUPLICATE_ONLY
    elif any(
        decision.disposition is AdmissionDisposition.BOUND_REJECTED
        for decision in decisions
    ):
        if any("open_work_ceiling" in decision.reason_codes for decision in decisions):
            epoch_disposition = EpochDisposition.OPEN_WORK_CEILING
        else:
            epoch_disposition = EpochDisposition.BOUND_EXCEEDED
    elif all(
        decision.disposition
        in {
            AdmissionDisposition.FIXED_POINT_SKIP,
            AdmissionDisposition.DUPLICATE,
            AdmissionDisposition.NOT_REFILL_ELIGIBLE,
        }
        for decision in decisions
    ):
        epoch_disposition = EpochDisposition.FIXED_POINT_CLOSED
    else:
        epoch_disposition = EpochDisposition.REJECTED

    # Stable unique reason codes.
    unique_reasons: list[str] = []
    seen_reasons: set[str] = set()
    for code in reason_codes:
        if code not in seen_reasons:
            seen_reasons.add(code)
            unique_reasons.append(code)

    return EpochReceipt(
        disposition=epoch_disposition,
        epoch_id=epoch_id,
        scan_identity=scan_identity,
        decisions=tuple(decisions),
        admitted_tasks=tuple(admitted_tasks),
        ledger_entries=tuple(ledger_entries),
        policy=policy,
        memory=RefillMemory(
            admitted_identity_keys=next_memory.admitted_identity_keys,
            open_task_count=next_memory.open_task_count,
            attempt_counts=dict(next_memory.attempt_counts),
            last_failure_fingerprints=dict(next_memory.last_failure_fingerprints),
            last_attempt_epoch_s=dict(next_memory.last_attempt_epoch_s),
            now_epoch_s=now,
            derived_goal_ids=tuple(sorted(derived_goals)),
        ),
        derived_goal_ids=tuple(sorted(g for g in derived_goals if not is_seed_goal(g))),
        reason_codes=tuple(unique_reasons),
        seed_definitions_mutated=False,
    )


def run_fixed_point_scans(
    gaps: Sequence[LogicGapRecord | Mapping[str, Any]],
    *,
    scan_identity: ScanIdentity | Mapping[str, Any],
    policy: LogicGapRefillPolicy | Mapping[str, Any] | None = None,
    memory: RefillMemory | None = None,
    now_epoch_s: int | None = None,
) -> FixedPointReceipt:
    """Run two consecutive epochs over identical identities.

    Fixed point holds when both epochs admit no new tasks (including the case
    where the first epoch already drained remaining gaps and the second is a
    pure replay/duplicate scan).
    """

    if policy is None:
        policy = LogicGapRefillPolicy.default()
    elif isinstance(policy, Mapping):
        policy = LogicGapRefillPolicy.from_dict(policy)

    if isinstance(scan_identity, Mapping):
        scan_identity = ScanIdentity.from_dict(scan_identity)

    first = run_refill_epoch(
        gaps,
        scan_identity=scan_identity,
        policy=policy,
        memory=memory,
        epoch_id="",
        now_epoch_s=now_epoch_s,
        ledger_sequence_start=0,
    )
    second = run_refill_epoch(
        gaps,
        scan_identity=scan_identity,
        policy=policy,
        memory=first.memory,
        epoch_id="",
        now_epoch_s=now_epoch_s,
        ledger_sequence_start=len(first.ledger_entries),
    )

    empty_count = 0
    if not first.admits_work:
        empty_count += 1
    if not second.admits_work:
        empty_count += 1

    # Fixed point: second scan over identical identities admits nothing.
    # When the first already admitted work, the second must still be empty
    # (duplicates only) for consecutive-empty semantics after drain.  The
    # acceptance criterion is "two consecutive scans ... produce no new
    # admissible tasks" — both must be empty for is_fixed_point=True.
    is_fp = (not first.admits_work) and (not second.admits_work)
    consecutive = 2 if is_fp else empty_count

    all_ledger = list(first.ledger_entries) + list(second.ledger_entries)
    ledger_digest = _stable_digest([entry.to_dict() for entry in all_ledger])

    reasons: list[str] = []
    if is_fp:
        reasons.append("consecutive_empty_scans")
    else:
        if first.admits_work:
            reasons.append("first_epoch_admitted_work")
        if second.admits_work:
            reasons.append("second_epoch_admitted_work")
        else:
            reasons.append("second_epoch_empty_after_drain")

    return FixedPointReceipt(
        is_fixed_point=is_fp,
        scan_identity=scan_identity,
        first_epoch=first,
        second_epoch=second,
        consecutive_empty_scans=consecutive if is_fp else empty_count,
        gap_ledger_digest=ledger_digest,
        policy=policy,
        reason_codes=tuple(reasons),
    )


def drain_to_fixed_point(
    gaps: Sequence[LogicGapRecord | Mapping[str, Any]],
    *,
    scan_identity: ScanIdentity | Mapping[str, Any],
    policy: LogicGapRefillPolicy | Mapping[str, Any] | None = None,
    memory: RefillMemory | None = None,
    now_epoch_s: int | None = None,
    max_epochs: int = 8,
) -> FixedPointReceipt:
    """Repeatedly run epochs until two consecutive empty scans or *max_epochs*.

    After the working set is drained (all remaining gaps are duplicates or
    rejected), a final pair of empty scans produces the fixed-point receipt.
    """

    if policy is None:
        policy = LogicGapRefillPolicy.default()
    elif isinstance(policy, Mapping):
        policy = LogicGapRefillPolicy.from_dict(policy)

    if isinstance(scan_identity, Mapping):
        scan_identity = ScanIdentity.from_dict(scan_identity)

    current_memory = memory or RefillMemory(now_epoch_s=now_epoch_s or 0)
    last_epoch: EpochReceipt | None = None
    previous_epoch: EpochReceipt | None = None
    all_ledger: list[GapLedgerEntry] = []
    sequence = 0

    for index in range(max_epochs):
        epoch = run_refill_epoch(
            gaps,
            scan_identity=scan_identity,
            policy=policy,
            memory=current_memory,
            epoch_id=f"epoch-drain-{index + 1:02d}",
            now_epoch_s=now_epoch_s,
            ledger_sequence_start=sequence,
        )
        all_ledger.extend(epoch.ledger_entries)
        sequence += len(epoch.ledger_entries)
        current_memory = epoch.memory
        previous_epoch = last_epoch
        last_epoch = epoch
        if (
            previous_epoch is not None
            and not previous_epoch.admits_work
            and not last_epoch.admits_work
        ):
            ledger_digest = _stable_digest([entry.to_dict() for entry in all_ledger])
            return FixedPointReceipt(
                is_fixed_point=True,
                scan_identity=scan_identity,
                first_epoch=previous_epoch,
                second_epoch=last_epoch,
                consecutive_empty_scans=2,
                gap_ledger_digest=ledger_digest,
                policy=policy,
                reason_codes=("drained_to_fixed_point", "consecutive_empty_scans"),
            )

    # Force a confirming empty replay pair when work was admitted earlier.
    assert last_epoch is not None
    confirm = run_refill_epoch(
        gaps,
        scan_identity=scan_identity,
        policy=policy,
        memory=current_memory,
        epoch_id="epoch-confirm",
        now_epoch_s=now_epoch_s,
        ledger_sequence_start=sequence,
    )
    all_ledger.extend(confirm.ledger_entries)
    ledger_digest = _stable_digest([entry.to_dict() for entry in all_ledger])
    is_fp = (not last_epoch.admits_work) and (not confirm.admits_work)
    empty_total = int(not last_epoch.admits_work) + int(not confirm.admits_work)
    return FixedPointReceipt(
        is_fixed_point=is_fp,
        scan_identity=scan_identity,
        first_epoch=last_epoch,
        second_epoch=confirm,
        consecutive_empty_scans=2 if is_fp else empty_total,
        gap_ledger_digest=ledger_digest,
        policy=policy,
        reason_codes=(
            ("drained_to_fixed_point", "consecutive_empty_scans")
            if is_fp
            else ("max_epochs_exhausted",)
        ),
    )


# ---------------------------------------------------------------------------
# Artifact IO
# ---------------------------------------------------------------------------


def render_gap_ledger_jsonl(entries: Sequence[GapLedgerEntry]) -> str:
    """Render ledger entries as canonical JSONL (trailing newline)."""

    lines = [entry.to_jsonl() for entry in entries]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def write_gap_ledger(path: Path | str, entries: Sequence[GapLedgerEntry]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render_gap_ledger_jsonl(entries)
    target.write_text(text, encoding="utf-8")
    return target


def write_fixed_point_receipt(
    path: Path | str, receipt: FixedPointReceipt
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def load_fixed_point_receipt(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LogicGapRefillError("fixed-point receipt must be a JSON object")
    return payload


def load_gap_ledger(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    text = target.read_text(encoding="utf-8")
    if not text.strip():
        return []
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise LogicGapRefillError("ledger line must be a JSON object")
        entries.append(payload)
    return entries


def default_refill_artifact_dir(repo_root: Path | str | None = None) -> Path:
    """Resolve the superproject-relative refill artifact directory."""

    if repo_root is None:
        # conformance/refill.py -> logic -> ipfs_datasets_py -> ipfs_datasets_py package root
        # -> superproject (parents[4])
        here = Path(__file__).resolve()
        # .../ipfs_datasets_py/ipfs_datasets_py/logic/conformance/refill.py
        # parents: conformance, logic, ipfs_datasets_py, ipfs_datasets_py(pkg), superproject
        candidates = [
            here.parents[4],  # superproject when nested
            here.parents[3],  # datasets package root
        ]
        for candidate in candidates:
            probe = candidate / DEFAULT_RUNTIME_REFILL_RELATIVE
            if probe.parent.exists() or (candidate / "docs" / "architecture").exists():
                return candidate / DEFAULT_RUNTIME_REFILL_RELATIVE
        return candidates[0] / DEFAULT_RUNTIME_REFILL_RELATIVE
    return Path(repo_root) / DEFAULT_RUNTIME_REFILL_RELATIVE


def materialize_current_tree_fixed_point(
    *,
    repo_root: Path | str | None = None,
    gaps: Sequence[LogicGapRecord | Mapping[str, Any]] | None = None,
    scan_identity: ScanIdentity | Mapping[str, Any] | None = None,
    policy: LogicGapRefillPolicy | Mapping[str, Any] | None = None,
) -> FixedPointReceipt:
    """Drain *gaps* (default: empty current-tree set) and write receipt + ledger.

    With an empty gap set the two consecutive empty scans immediately form a
    fixed point — the production posture when discovery has no remaining
    refill-eligible work under identical source/config/corpus identities.
    """

    root = Path(repo_root) if repo_root is not None else None
    artifact_dir = default_refill_artifact_dir(root)
    if scan_identity is None:
        scan_identity = ScanIdentity(
            source_identity="source:current-tree:logic-family-parser",
            config_identity=(
                "config:agent_supervisor_ipfs_datasets_logic_family_parser_scheduler"
            ),
            corpus_identity="corpus:logic-conformance:current",
            tree_id="tree:current",
            repository_id="repository:ipfs-datasets-logic-family-parser",
        )
    if gaps is None:
        gaps = ()
    if policy is None:
        policy = LogicGapRefillPolicy.default()

    if isinstance(scan_identity, Mapping):
        scan_identity = ScanIdentity.from_dict(scan_identity)
    if isinstance(policy, Mapping):
        policy = LogicGapRefillPolicy.from_dict(policy)

    receipt = drain_to_fixed_point(
        gaps,
        scan_identity=scan_identity,
        policy=policy,
        now_epoch_s=0,
    )
    # Collect full ledger from both epochs (drain may have more; re-run
    # fixed-point pair already embeds two epochs).
    ledger_entries = list(receipt.first_epoch.ledger_entries) + list(
        receipt.second_epoch.ledger_entries
    )
    # Always record a terminal fixed-point audit row so the ledger is
    # non-empty evidence even when the gap set was already drained.
    if isinstance(scan_identity, ScanIdentity) and isinstance(
        policy, LogicGapRefillPolicy
    ):
        audit = GapLedgerEntry(
            entry_id=f"ledger:fixed-point:{receipt.receipt_digest[7:23]}",
            epoch_id=receipt.second_epoch.epoch_id,
            decision=GapAdmissionDecision(
                gap_id="fixed-point-audit",
                identity_key=receipt.scan_identity.composite_digest,
                disposition=(
                    AdmissionDisposition.FIXED_POINT_SKIP
                    if receipt.is_fixed_point
                    else AdmissionDisposition.BOUND_REJECTED
                ),
                reason_codes=(
                    ("consecutive_empty_scans", "identical_identities")
                    if receipt.is_fixed_point
                    else ("fixed_point_not_reached",)
                ),
            ),
            scan_identity=receipt.scan_identity,
            gap_digest=receipt.gap_ledger_digest,
            sequence=len(ledger_entries) + 1,
        )
        ledger_entries.append(audit)
    write_fixed_point_receipt(
        artifact_dir / DEFAULT_FIXED_POINT_RECEIPT_NAME, receipt
    )
    write_gap_ledger(artifact_dir / DEFAULT_GAP_LEDGER_NAME, ledger_entries)
    return receipt


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "AdmissionDisposition",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_MAX_GOALS_PER_EPOCH",
    "DEFAULT_MAX_OPEN_TASKS",
    "DEFAULT_MAX_REFINEMENT_DEPTH",
    "DEFAULT_MAX_TASKS_PER_EPOCH",
    "DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES",
    "DEFAULT_MIN_OPEN_TASKS",
    "DEFAULT_PROTECTED_PATHS",
    "DEFAULT_STOP_POLICY",
    "DerivedTaskProposal",
    "EpochDisposition",
    "EpochReceipt",
    "FixedPointReceipt",
    "GapAdmissionDecision",
    "GapKind",
    "GapLedgerEntry",
    "GOAL_ID",
    "IMMUTABLE_SEED_GOAL_COUNT",
    "IMMUTABLE_SEED_GOALS",
    "LOGIC_GAP_REFILL_INTERFACE",
    "LOGIC_GAP_REFILL_VERSION",
    "LogicGapRecord",
    "LogicGapRefillAuthorityError",
    "LogicGapRefillBoundsError",
    "LogicGapRefillError",
    "LogicGapRefillPolicy",
    "OBJECTIVE_REFILL_FIXED_POINT_INTERFACE",
    "PROGRAM_ID",
    "PRODUCER_ID",
    "RefillMemory",
    "ScanIdentity",
    "TASK_ID",
    "count_derived_goals",
    "default_refill_artifact_dir",
    "drain_to_fixed_point",
    "is_seed_goal",
    "is_unscoped_codebase_scope",
    "load_fixed_point_receipt",
    "load_gap_ledger",
    "materialize_current_tree_fixed_point",
    "render_gap_ledger_jsonl",
    "run_fixed_point_scans",
    "run_refill_epoch",
    "write_fixed_point_receipt",
    "write_gap_ledger",
]


def _resolve_superproject_root() -> Path:
    """Locate the accelerator superproject that owns the refill runtime dir."""

    here = Path(__file__).resolve()
    # .../ipfs_datasets_py/ipfs_datasets_py/logic/conformance/refill.py
    nested_repo = here.parents[3]
    superproject = here.parents[4]
    for candidate in (superproject, nested_repo, Path.cwd()):
        if (candidate / "docs" / "architecture").is_dir() or (
            candidate / "config" / "agent_supervisor_ipfs_datasets_logic_family_parser_scheduler.json"
        ).is_file():
            return candidate
    return superproject


if __name__ == "__main__":
    _receipt = materialize_current_tree_fixed_point(repo_root=_resolve_superproject_root())
    _dir = default_refill_artifact_dir(_resolve_superproject_root())
    print(f"wrote {_dir / DEFAULT_FIXED_POINT_RECEIPT_NAME}")
    print(f"wrote {_dir / DEFAULT_GAP_LEDGER_NAME}")
    print(f"is_fixed_point={_receipt.is_fixed_point}")
    print(f"receipt_digest={_receipt.receipt_digest}")
    raise SystemExit(0 if _receipt.is_fixed_point else 1)
