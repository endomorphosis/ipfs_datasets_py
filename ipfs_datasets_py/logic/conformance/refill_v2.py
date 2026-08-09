"""Reachable-gap scoring and strict derived-task admission (LFP2-048).

Interfaces: ``ReachableGapScorer@1``, ``DerivedTaskAdmission@2``

This module is the Wave-2 control-plane gate between typed reachable gaps and
an append-only derived task ledger:

* every scored gap carries a stable content identity over owner, evidence
  obligation, discovery receipt, scope, validation, and authority ceiling;
* Cartesian unsupported cells, advisor-only routes, vague cleanup, duplicates,
  unsafe, protected, and broad/unscoped tasks are rejected **before** append;
* admitted tasks require content identity, evidence obligation, discovery,
  ownership, dependency lineage, bounded scope, validation, dedupe, budget,
  and an authority ceiling that never grants completion or seed mutation;
* seed goals/tasks remain immutable; derived work hangs under LFP2-G090.

Generated tasks are evidence only — never completion or mutation authority.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

REACHABLE_GAP_SCORER_INTERFACE: Final = "ReachableGapScorer@1"
DERIVED_TASK_ADMISSION_INTERFACE: Final = "DerivedTaskAdmission@2"
REACHABLE_GAP_SCORER_VERSION: Final = "1.0.0"
DERIVED_TASK_ADMISSION_VERSION: Final = "2.0.0"

REACHABLE_GAP_CANDIDATE_SCHEMA: Final = "logic-reachable-gap-candidate/v2"
GAP_SCORE_SCHEMA: Final = "logic-reachable-gap-score/v1"
DERIVED_TASK_SCHEMA: Final = "logic-derived-task-proposal/v2"
ADMISSION_DECISION_SCHEMA: Final = "logic-derived-task-admission-decision/v2"
ADMISSION_RECEIPT_SCHEMA: Final = "logic-derived-task-admission-receipt/v2"
REFILL_POLICY_SCHEMA: Final = "logic-refill-policy/v2"
SCORER_RECEIPT_SCHEMA: Final = "logic-reachable-gap-scorer-receipt/v1"

TASK_ID: Final = "LFP2-048"
GOAL_ID: Final = "LFP2-G090"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"
PRODUCER_ID: Final = "reachable-gap-scorer@1"
ADMISSION_PRODUCER_ID: Final = "derived-task-admission@2"

# Eleven immutable seed goals (root + ten children). Derived-goal budgets
# never count these against max_goals_per_epoch.
IMMUTABLE_SEED_GOALS: Final[tuple[str, ...]] = (
    "LFP2-G000",
    "LFP2-G010",
    "LFP2-G020",
    "LFP2-G030",
    "LFP2-G040",
    "LFP2-G050",
    "LFP2-G060",
    "LFP2-G070",
    "LFP2-G080",
    "LFP2-G090",
    "LFP2-G100",
)
IMMUTABLE_SEED_GOAL_COUNT: Final = 11
assert len(IMMUTABLE_SEED_GOALS) == IMMUTABLE_SEED_GOAL_COUNT

DEFAULT_PARENT_GOAL_ID: Final = "LFP2-G090"
DEFAULT_MAX_GOALS_PER_EPOCH: Final = 8
DEFAULT_MAX_TASKS_PER_EPOCH: Final = 24
DEFAULT_MIN_OPEN_TASKS: Final = 8
DEFAULT_MAX_OPEN_TASKS: Final = 48
DEFAULT_MAX_REFINEMENT_DEPTH: Final = 3
DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES: Final = 2
DEFAULT_COOLDOWN_SECONDS: Final = 3600
DEFAULT_MAX_PATHS: Final = 8
DEFAULT_MAX_CONTEXT_PATHS: Final = 8
DEFAULT_MAX_CONTEXT_BUDGET_BYTES: Final = 40_000

DEFAULT_STOP_POLICY: Final = (
    "stop:reachable-gap-refill@2:"
    "max-goals=8;max-tasks=24;max-open=48;max-depth=3;"
    "max-retries=2;cooldown=3600;seed-goals-excluded;"
    "no-seed-mutation;no-cartesian;no-advisor-only;"
    "no-vague-cleanup;no-unscoped-codebase"
)

DEFAULT_PROTECTED_PATHS: Final[tuple[str, ...]] = (
    ".gitignore",
    "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_V2_PLAN.md",
    "docs/architecture/ipfs_datasets_logic_family_parser_v2.objectives.md",
    "docs/architecture/ipfs_datasets_logic_family_parser_v2.todo.md",
    "config/agent_supervisor_ipfs_datasets_logic_family_parser_v2_scheduler.json",
    "scripts/validate_ipfs_datasets_logic_family_parser_v2_board.py",
    "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md",
    "docs/architecture/ipfs_datasets_logic_family_parser.objectives.md",
    "docs/architecture/ipfs_datasets_logic_family_parser.todo.md",
    "config/agent_supervisor_ipfs_datasets_logic_family_parser_scheduler.json",
    "scripts/validate_ipfs_datasets_logic_family_parser_board.py",
    "ipfs_datasets_py/docs/architecture/logic/LOGIC_FAMILY_PARSER_RELEASE.md",
    "ipfs_datasets_py/data/logic/conformance/logic_family_parser_release.json",
    "ipfs_accelerate_py/agent_supervisor/runtime/configured_board_scheduler.py",
    "ipfs_accelerate_py/agent_supervisor/runtime/grok_cli_runner.py",
    "ipfs_accelerate_py/agent_supervisor/runtime/multi_supervisor_runner.py",
    "ipfs_accelerate_py/agent_supervisor/todo_daemon/implementation_daemon.py",
)

MAX_ID_BYTES: Final = 512
MAX_TEXT_BYTES: Final = 4_096
MAX_PATH_BYTES: Final = 1_024
MAX_GAPS: Final = 256
MAX_VALIDATION_COMMANDS: Final = 16

_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-=]{0,511}$")
_GOAL_ID_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,255}$")

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
        "mutate_seed_objectives",
    }
)

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

_VAGUE_CLEANUP_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "cleanup",
        "clean up",
        "clean-up",
        "refactor everything",
        "improve codebase",
        "codebase cleanup",
        "general cleanup",
        "misc cleanup",
        "tech debt",
        "technical debt",
        "drive-by",
        "drive by",
        "tidy up",
        "housekeeping",
        "chore: cleanup",
        "vague cleanup",
    }
)

_UNSAFE_COMMAND_MARKERS: Final[tuple[str, ...]] = (
    "rm -rf",
    "rm -r ",
    "sudo ",
    "curl |",
    "wget |",
    ">/dev/sd",
    "mkfs",
    ":(){",
    "chmod 777",
    "dd if=",
    "eval ",
    "`",
    "$(",
    "&& rm",
    ";rm ",
)

# Base priority weights for admissible gap kinds (higher = more urgent).
_KIND_PRIORITY: Final[Mapping[str, int]] = MappingProxyType(
    {
        "parser_counterexample": 100,
        "profile_counterexample": 95,
        "extension_schema_hole": 90,
        "extension_type_hole": 88,
        "extension_binder_hole": 86,
        "reachable_translation_hole": 84,
        "domain_formal_view_gap": 82,
        "raw_target_ingress_gap": 80,
        "capability_execution_gap": 78,
        "capability_replay_gap": 76,
        "provider_toolchain_drift": 74,
        "unvalidated_evidence": 72,
        "ui_ux_ir_revision": 70,
        "failing_reachable_matrix_cell": 68,
        "missing_fixture": 66,
        "unsupported_ast_node": 64,
        "other_reachable": 50,
    }
)

# Gap kinds that are never refill-admissible (rejected before append).
_NON_REFILL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "cartesian_unsupported",
        "advisor_only",
        "vague_cleanup",
        "unsafe",
        "broad_codebase",
    }
)


# ---------------------------------------------------------------------------
# Errors / vocabularies
# ---------------------------------------------------------------------------


class RefillV2Error(ValueError):
    """A gap, score, policy, or admission receipt is malformed."""


class RefillV2BoundsError(RefillV2Error):
    """A population or field exceeds a hard bound."""


class RefillV2AuthorityError(RefillV2Error):
    """A candidate claims forbidden completion or mutation authority."""


class GapKind(StrEnum):
    """Closed origin kinds for content-addressed reachable gaps."""

    # Admissible triggers (plan §Objective refill contract).
    PARSER_COUNTEREXAMPLE = "parser_counterexample"
    PROFILE_COUNTEREXAMPLE = "profile_counterexample"
    EXTENSION_SCHEMA_HOLE = "extension_schema_hole"
    EXTENSION_TYPE_HOLE = "extension_type_hole"
    EXTENSION_BINDER_HOLE = "extension_binder_hole"
    REACHABLE_TRANSLATION_HOLE = "reachable_translation_hole"
    DOMAIN_FORMAL_VIEW_GAP = "domain_formal_view_gap"
    RAW_TARGET_INGRESS_GAP = "raw_target_ingress_gap"
    CAPABILITY_EXECUTION_GAP = "capability_execution_gap"
    CAPABILITY_REPLAY_GAP = "capability_replay_gap"
    PROVIDER_TOOLCHAIN_DRIFT = "provider_toolchain_drift"
    UNVALIDATED_EVIDENCE = "unvalidated_evidence"
    UI_UX_IR_REVISION = "ui_ux_ir_revision"
    FAILING_REACHABLE_MATRIX_CELL = "failing_reachable_matrix_cell"
    MISSING_FIXTURE = "missing_fixture"
    UNSUPPORTED_AST_NODE = "unsupported_ast_node"
    OTHER_REACHABLE = "other_reachable"
    # Explicit non-refill kinds (rejected before append).
    CARTESIAN_UNSUPPORTED = "cartesian_unsupported"
    ADVISOR_ONLY = "advisor_only"
    VAGUE_CLEANUP = "vague_cleanup"
    UNSAFE = "unsafe"
    BROAD_CODEBASE = "broad_codebase"


class AdmissionDisposition(StrEnum):
    """Per-gap admission decision (fail-closed vocabulary)."""

    ADMITTED = "admitted"
    CARTESIAN_REJECTED = "cartesian_rejected"
    ADVISOR_ONLY_REJECTED = "advisor_only_rejected"
    VAGUE_CLEANUP_REJECTED = "vague_cleanup_rejected"
    DUPLICATE = "duplicate"
    UNSAFE_REJECTED = "unsafe_rejected"
    PROTECTED_REJECTED = "protected_rejected"
    BROAD_REJECTED = "broad_rejected"
    BOUND_REJECTED = "bound_rejected"
    DEPTH_REJECTED = "depth_rejected"
    RETRY_EXHAUSTED = "retry_exhausted"
    COOLDOWN = "cooldown"
    MALFORMED = "malformed"
    MISSING_REQUIREMENT = "missing_requirement"
    AUTHORITY_REJECTED = "authority_rejected"
    NOT_REFILL_ELIGIBLE = "not_refill_eligible"
    LOW_SCORE = "low_score"


class EpochDisposition(StrEnum):
    """Stable outcomes of one admission epoch."""

    ADMITTED = "admitted"
    DUPLICATE_ONLY = "duplicate_only"
    BOUND_EXCEEDED = "bound_exceeded"
    OPEN_WORK_CEILING = "open_work_ceiling"
    EMPTY_INPUT = "empty_input"
    REJECTED = "rejected"
    REPLAY_NOOP = "replay_noop"


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
        raise RefillV2Error(f"{name} must be a string")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise RefillV2Error(f"{name} must be normalized single-line text")
    if required and not text:
        raise RefillV2Error(f"{name} is required")
    if len(text.encode("utf-8")) > limit:
        raise RefillV2BoundsError(f"{name} exceeds its byte bound")
    return text


def _identifier(value: Any, name: str, *, required: bool = True) -> str:
    text = _text(value, name, required=required, limit=MAX_ID_BYTES)
    if not text:
        return ""
    if not _IDENTIFIER_RE.fullmatch(text):
        raise RefillV2Error(f"{name} is malformed")
    return text


def _goal_id(value: Any, name: str = "goal_id") -> str:
    text = _text(value, name, limit=MAX_ID_BYTES)
    if not _GOAL_ID_RE.fullmatch(text):
        raise RefillV2Error(f"{name} is malformed")
    return text


def _bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise RefillV2Error(f"{name} must be a boolean")


def _nonneg_int(value: Any, name: str, *, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RefillV2Error(f"{name} must be an integer")
    if value < 0 or value > maximum:
        raise RefillV2BoundsError(f"{name} out of bounds")
    return value


def _positive_int(value: Any, name: str, *, maximum: int = 1_000_000) -> int:
    number = _nonneg_int(value, name, maximum=maximum)
    if number < 1:
        raise RefillV2Error(f"{name} must be >= 1")
    return number


def _enum(value: Any, enum_cls: type[StrEnum], name: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    text = _text(value, name)
    try:
        return enum_cls(text)
    except ValueError as exc:
        raise RefillV2Error(f"{name} has unknown value {text!r}") from exc


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
        raise RefillV2Error("paths must be repository-relative and non-escaping")
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
        raise RefillV2Error(f"{name} must be a sequence of paths")
    if len(items) > maximum:
        raise RefillV2BoundsError(f"{name} exceeds its path bound")
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        path = _normalize_path(raw)
        if not path or path in seen:
            continue
        if len(path.encode("utf-8")) > MAX_PATH_BYTES:
            raise RefillV2BoundsError(f"{name} path exceeds its byte bound")
        seen.add(path)
        out.append(path)
    if required and not out:
        raise RefillV2Error(f"{name} must not be empty")
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
        raise RefillV2Error(f"{name} must be a sequence of identifiers")
    if len(items) > maximum:
        raise RefillV2BoundsError(f"{name} exceeds its item bound")
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = _identifier(raw, name, required=True)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    if required and not out:
        raise RefillV2Error(f"{name} must not be empty")
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
        raise RefillV2Error(f"{name} must be a sequence of strings")
    if len(items) > maximum:
        raise RefillV2BoundsError(f"{name} exceeds its item bound")
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
        raise RefillV2Error(f"{name} must be a mapping")
    try:
        canonical = json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise RefillV2Error(f"{name} must be canonical JSON data") from exc
    if not isinstance(canonical, dict):
        raise RefillV2Error(f"{name} must be a mapping")
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
            raise RefillV2AuthorityError(f"{where} cannot claim {key}")


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


def is_vague_cleanup_text(*parts: str) -> bool:
    """Return True when free text describes vague codebase cleanup only."""

    blob = " ".join(part.strip().lower() for part in parts if part).strip()
    if not blob:
        return False
    for marker in _VAGUE_CLEANUP_MARKERS:
        if marker in blob:
            return True
    return False


def is_unsafe_command(command: str) -> bool:
    """Return True when a validation command matches unsafe shell patterns."""

    lowered = command.lower()
    return any(marker in lowered for marker in _UNSAFE_COMMAND_MARKERS)


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
class RefillPolicyV2:
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
    max_context_budget_bytes: int = DEFAULT_MAX_CONTEXT_BUDGET_BYTES
    min_score: int = 1
    parent_goal_id: str = DEFAULT_PARENT_GOAL_ID
    mutate_seed_board: bool = False
    mutate_seed_objectives: bool = False
    unscoped_codebase_refill_allowed: bool = False
    seed_tasks_are_immutable: bool = True
    seed_goals_are_immutable: bool = True
    cartesian_unsupported_allowed: bool = False
    advisor_only_allowed: bool = False
    vague_cleanup_allowed: bool = False
    protected_paths: tuple[str, ...] = DEFAULT_PROTECTED_PATHS
    stop_policy: str = DEFAULT_STOP_POLICY
    schema: str = REFILL_POLICY_SCHEMA

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
        object.__setattr__(
            self,
            "max_context_budget_bytes",
            _positive_int(
                self.max_context_budget_bytes,
                "max_context_budget_bytes",
                maximum=250_000,
            ),
        )
        object.__setattr__(
            self, "min_score", _nonneg_int(self.min_score, "min_score", maximum=1_000)
        )
        object.__setattr__(self, "parent_goal_id", _goal_id(self.parent_goal_id))
        object.__setattr__(
            self, "mutate_seed_board", _bool(self.mutate_seed_board, "mutate_seed_board")
        )
        if self.mutate_seed_board:
            raise RefillV2AuthorityError(
                "mutate_seed_board must remain false; seed definitions are immutable"
            )
        object.__setattr__(
            self,
            "mutate_seed_objectives",
            _bool(self.mutate_seed_objectives, "mutate_seed_objectives"),
        )
        if self.mutate_seed_objectives:
            raise RefillV2AuthorityError(
                "mutate_seed_objectives must remain false; objective heap is immutable"
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
            raise RefillV2AuthorityError("seed_tasks_are_immutable must be true")
        object.__setattr__(
            self,
            "seed_goals_are_immutable",
            _bool(self.seed_goals_are_immutable, "seed_goals_are_immutable"),
        )
        if not self.seed_goals_are_immutable:
            raise RefillV2AuthorityError("seed_goals_are_immutable must be true")
        object.__setattr__(
            self,
            "cartesian_unsupported_allowed",
            _bool(
                self.cartesian_unsupported_allowed, "cartesian_unsupported_allowed"
            ),
        )
        object.__setattr__(
            self,
            "advisor_only_allowed",
            _bool(self.advisor_only_allowed, "advisor_only_allowed"),
        )
        object.__setattr__(
            self,
            "vague_cleanup_allowed",
            _bool(self.vague_cleanup_allowed, "vague_cleanup_allowed"),
        )
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
        if self.schema != REFILL_POLICY_SCHEMA:
            raise RefillV2Error(f"policy schema must be {REFILL_POLICY_SCHEMA}")

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
            "max_context_budget_bytes": self.max_context_budget_bytes,
            "min_score": self.min_score,
            "parent_goal_id": self.parent_goal_id,
            "mutate_seed_board": self.mutate_seed_board,
            "mutate_seed_objectives": self.mutate_seed_objectives,
            "unscoped_codebase_refill_allowed": self.unscoped_codebase_refill_allowed,
            "seed_tasks_are_immutable": self.seed_tasks_are_immutable,
            "seed_goals_are_immutable": self.seed_goals_are_immutable,
            "cartesian_unsupported_allowed": self.cartesian_unsupported_allowed,
            "advisor_only_allowed": self.advisor_only_allowed,
            "vague_cleanup_allowed": self.vague_cleanup_allowed,
            "protected_paths": list(self.protected_paths),
            "stop_policy": self.stop_policy,
            "immutable_seed_goals": list(IMMUTABLE_SEED_GOALS),
            "immutable_seed_goal_count": IMMUTABLE_SEED_GOAL_COUNT,
            "seed_goals_excluded_from_derived_budget": True,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> RefillPolicyV2:
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise RefillV2Error("policy must be a mapping")
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
            "max_context_budget_bytes",
            "min_score",
            "parent_goal_id",
            "mutate_seed_board",
            "mutate_seed_objectives",
            "unscoped_codebase_refill_allowed",
            "seed_tasks_are_immutable",
            "seed_goals_are_immutable",
            "cartesian_unsupported_allowed",
            "advisor_only_allowed",
            "vague_cleanup_allowed",
            "protected_paths",
            "stop_policy",
            "schema",
        }
        kwargs = {key: payload[key] for key in known if key in payload}
        return cls(**kwargs)

    @classmethod
    def default(cls) -> RefillPolicyV2:
        return cls()


@dataclass(frozen=True, slots=True)
class ScanIdentity:
    """Content identities that must match across consecutive refill scans."""

    source_identity: str
    config_identity: str
    corpus_identity: str
    provider_identity: str = ""
    registry_identity: str = ""
    objective_identity: str = ""
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
        for field_name in (
            "provider_identity",
            "registry_identity",
            "objective_identity",
            "tree_id",
            "repository_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(
                    getattr(self, field_name),
                    field_name,
                    required=False,
                    limit=MAX_ID_BYTES,
                ),
            )

    @property
    def composite_digest(self) -> str:
        return _stable_digest(
            {
                "source_identity": self.source_identity,
                "config_identity": self.config_identity,
                "corpus_identity": self.corpus_identity,
                "provider_identity": self.provider_identity,
                "registry_identity": self.registry_identity,
                "objective_identity": self.objective_identity,
                "tree_id": self.tree_id,
                "repository_id": self.repository_id,
            }
        )

    def matches(self, other: ScanIdentity) -> bool:
        return (
            self.source_identity == other.source_identity
            and self.config_identity == other.config_identity
            and self.corpus_identity == other.corpus_identity
            and self.provider_identity == other.provider_identity
            and self.registry_identity == other.registry_identity
            and self.objective_identity == other.objective_identity
            and self.tree_id == other.tree_id
            and self.repository_id == other.repository_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identity": self.source_identity,
            "config_identity": self.config_identity,
            "corpus_identity": self.corpus_identity,
            "provider_identity": self.provider_identity,
            "registry_identity": self.registry_identity,
            "objective_identity": self.objective_identity,
            "tree_id": self.tree_id,
            "repository_id": self.repository_id,
            "composite_digest": self.composite_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ScanIdentity:
        if not isinstance(payload, Mapping):
            raise RefillV2Error("scan identity must be a mapping")
        return cls(
            source_identity=payload.get("source_identity", ""),
            config_identity=payload.get("config_identity", ""),
            corpus_identity=payload.get("corpus_identity", ""),
            provider_identity=payload.get("provider_identity", ""),
            registry_identity=payload.get("registry_identity", ""),
            objective_identity=payload.get("objective_identity", ""),
            tree_id=payload.get("tree_id", ""),
            repository_id=payload.get("repository_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ReachableGapCandidate:
    """One owner-scoped typed reachable gap eligible for scoring."""

    gap_id: str
    gap_kind: GapKind
    owner: str
    subject: str
    evidence_obligation: str
    discovery_receipt: str
    content_identity: str = ""
    evidence: str = ""
    originating_goal_id: str = DEFAULT_PARENT_GOAL_ID
    family_id: str = ""
    profile_id: str = ""
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
    support_status: str = ""
    route_disposition: str = ""
    context_budget_bytes: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = REACHABLE_GAP_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(self, "gap_kind", _enum(self.gap_kind, GapKind, "gap_kind"))
        object.__setattr__(self, "owner", _text(self.owner, "owner"))
        object.__setattr__(self, "subject", _text(self.subject, "subject"))
        object.__setattr__(
            self,
            "evidence_obligation",
            _text(
                self.evidence_obligation,
                "evidence_obligation",
                required=False,
                limit=MAX_TEXT_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "discovery_receipt",
            _text(
                self.discovery_receipt,
                "discovery_receipt",
                required=False,
                limit=MAX_ID_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "content_identity",
            _text(
                self.content_identity,
                "content_identity",
                required=False,
                limit=MAX_ID_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            _text(self.evidence, "evidence", required=False, limit=MAX_TEXT_BYTES),
        )
        object.__setattr__(
            self, "originating_goal_id", _goal_id(self.originating_goal_id)
        )
        for optional_id in ("family_id", "profile_id"):
            object.__setattr__(
                self,
                optional_id,
                _text(
                    getattr(self, optional_id),
                    optional_id,
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
            self, "fixture_ids", _ids(self.fixture_ids, "fixture_ids", maximum=32)
        )
        object.__setattr__(
            self,
            "validation_commands",
            _command_strings(self.validation_commands, "validation_commands"),
        )
        object.__setattr__(
            self, "dependencies", _ids(self.dependencies, "dependencies", maximum=32)
        )
        object.__setattr__(self, "depth", _nonneg_int(self.depth, "depth", maximum=16))
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
            self,
            "support_status",
            _text(
                self.support_status, "support_status", required=False, limit=MAX_ID_BYTES
            ),
        )
        object.__setattr__(
            self,
            "route_disposition",
            _text(
                self.route_disposition,
                "route_disposition",
                required=False,
                limit=MAX_ID_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "context_budget_bytes",
            _nonneg_int(
                self.context_budget_bytes, "context_budget_bytes", maximum=250_000
            ),
        )
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata, "metadata"))
        _reject_authority_claims(self.metadata, where=f"gap {self.gap_id}")
        if self.schema != REACHABLE_GAP_CANDIDATE_SCHEMA:
            raise RefillV2Error(
                f"gap schema must be {REACHABLE_GAP_CANDIDATE_SCHEMA}"
            )

    @property
    def derived_content_identity(self) -> str:
        """Stable identity over the gap body (excludes attempt counters)."""

        return _stable_digest(
            {
                "gap_id": self.gap_id,
                "gap_kind": self.gap_kind.value,
                "owner": self.owner,
                "subject": self.subject,
                "evidence_obligation": self.evidence_obligation,
                "discovery_receipt": self.discovery_receipt,
                "evidence": self.evidence,
                "originating_goal_id": self.originating_goal_id,
                "family_id": self.family_id,
                "profile_id": self.profile_id,
                "authority_ceiling": self.authority_ceiling,
                "owned_paths": list(self.owned_paths),
                "fixture_ids": list(self.fixture_ids),
                "validation_commands": list(self.validation_commands),
                "dependencies": list(self.dependencies),
                "depth": self.depth,
                "support_status": self.support_status,
                "route_disposition": self.route_disposition,
            }
        )

    @property
    def identity_key(self) -> str:
        if self.content_identity:
            return self.content_identity
        return self.derived_content_identity

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "gap_id": self.gap_id,
            "gap_kind": self.gap_kind.value,
            "owner": self.owner,
            "subject": self.subject,
            "evidence_obligation": self.evidence_obligation,
            "discovery_receipt": self.discovery_receipt,
            "content_identity": self.identity_key,
            "evidence": self.evidence,
            "originating_goal_id": self.originating_goal_id,
            "family_id": self.family_id,
            "profile_id": self.profile_id,
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
            "support_status": self.support_status,
            "route_disposition": self.route_disposition,
            "context_budget_bytes": self.context_budget_bytes,
            "metadata": dict(self.metadata),
            "derived_content_identity": self.derived_content_identity,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ReachableGapCandidate:
        if not isinstance(payload, Mapping):
            raise RefillV2Error("gap record must be a mapping")
        return cls(
            gap_id=payload.get("gap_id", ""),
            gap_kind=payload.get("gap_kind", GapKind.OTHER_REACHABLE),
            owner=payload.get("owner", ""),
            subject=payload.get("subject", ""),
            evidence_obligation=payload.get("evidence_obligation", ""),
            discovery_receipt=payload.get("discovery_receipt", ""),
            content_identity=payload.get("content_identity", ""),
            evidence=payload.get("evidence", ""),
            originating_goal_id=payload.get(
                "originating_goal_id", DEFAULT_PARENT_GOAL_ID
            ),
            family_id=payload.get("family_id", ""),
            profile_id=payload.get("profile_id", ""),
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
            support_status=payload.get("support_status", ""),
            route_disposition=payload.get("route_disposition", ""),
            context_budget_bytes=payload.get("context_budget_bytes", 0),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class GapScore:
    """Deterministic score for one reachable gap candidate."""

    gap_id: str
    content_identity: str
    priority: int
    admissible: bool
    rejection_reasons: tuple[str, ...] = ()
    gap_kind: str = ""
    owner: str = ""
    evidence_obligation: str = ""
    discovery_receipt: str = ""
    authority_ceiling: str = "none"
    score_digest: str = ""
    schema: str = GAP_SCORE_SCHEMA
    interface: str = REACHABLE_GAP_SCORER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self,
            "content_identity",
            _text(self.content_identity, "content_identity", limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self, "priority", _nonneg_int(self.priority, "priority", maximum=10_000)
        )
        object.__setattr__(self, "admissible", _bool(self.admissible, "admissible"))
        object.__setattr__(
            self,
            "rejection_reasons",
            _ids(self.rejection_reasons, "rejection_reasons", maximum=32),
        )
        object.__setattr__(
            self,
            "gap_kind",
            _text(self.gap_kind, "gap_kind", required=False, limit=MAX_ID_BYTES),
        )
        object.__setattr__(
            self,
            "owner",
            _text(self.owner, "owner", required=False, limit=MAX_TEXT_BYTES),
        )
        object.__setattr__(
            self,
            "evidence_obligation",
            _text(
                self.evidence_obligation,
                "evidence_obligation",
                required=False,
                limit=MAX_TEXT_BYTES,
            ),
        )
        object.__setattr__(
            self,
            "discovery_receipt",
            _text(
                self.discovery_receipt,
                "discovery_receipt",
                required=False,
                limit=MAX_ID_BYTES,
            ),
        )
        ceiling = _text(
            self.authority_ceiling,
            "authority_ceiling",
            required=False,
            limit=MAX_ID_BYTES,
        )
        object.__setattr__(self, "authority_ceiling", ceiling or "none")
        if not self.score_digest:
            object.__setattr__(
                self,
                "score_digest",
                _stable_digest(
                    {
                        "gap_id": self.gap_id,
                        "content_identity": self.content_identity,
                        "priority": self.priority,
                        "admissible": self.admissible,
                        "rejection_reasons": list(self.rejection_reasons),
                        "gap_kind": self.gap_kind,
                    }
                ),
            )
        if self.interface != REACHABLE_GAP_SCORER_INTERFACE:
            raise RefillV2Error(
                f"score interface must be {REACHABLE_GAP_SCORER_INTERFACE}"
            )
        if self.schema != GAP_SCORE_SCHEMA:
            raise RefillV2Error(f"score schema must be {GAP_SCORE_SCHEMA}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "gap_id": self.gap_id,
            "content_identity": self.content_identity,
            "priority": self.priority,
            "admissible": self.admissible,
            "rejection_reasons": list(self.rejection_reasons),
            "gap_kind": self.gap_kind,
            "owner": self.owner,
            "evidence_obligation": self.evidence_obligation,
            "discovery_receipt": self.discovery_receipt,
            "authority_ceiling": self.authority_ceiling,
            "score_digest": self.score_digest,
        }


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
    evidence_obligation: str
    discovery_receipt: str
    authority_ceiling: str
    context_paths: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    depth: int = 1
    family_id: str = ""
    profile_id: str = ""
    gap_kind: str = GapKind.OTHER_REACHABLE.value
    priority: int = 0
    stop_policy: str = DEFAULT_STOP_POLICY
    schema: str = DERIVED_TASK_SCHEMA

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
            "evidence_obligation",
            _text(self.evidence_obligation, "evidence_obligation"),
        )
        object.__setattr__(
            self,
            "discovery_receipt",
            _text(self.discovery_receipt, "discovery_receipt"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _text(self.authority_ceiling, "authority_ceiling") or "none",
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
            "validation_commands",
            _command_strings(self.validation_commands, "validation_commands"),
        )
        object.__setattr__(
            self,
            "acceptance_criteria",
            _command_strings(self.acceptance_criteria, "acceptance_criteria"),
        )
        object.__setattr__(
            self, "dependencies", _ids(self.dependencies, "dependencies", maximum=32)
        )
        object.__setattr__(self, "depth", _nonneg_int(self.depth, "depth", maximum=16))
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
            self, "gap_kind", _text(self.gap_kind, "gap_kind", limit=MAX_ID_BYTES)
        )
        object.__setattr__(
            self, "priority", _nonneg_int(self.priority, "priority", maximum=10_000)
        )
        object.__setattr__(
            self,
            "stop_policy",
            _text(self.stop_policy, "stop_policy", limit=MAX_TEXT_BYTES),
        )
        if self.schema != DERIVED_TASK_SCHEMA:
            raise RefillV2Error(f"task schema must be {DERIVED_TASK_SCHEMA}")

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
            "evidence_obligation": self.evidence_obligation,
            "discovery_receipt": self.discovery_receipt,
            "authority_ceiling": self.authority_ceiling,
            "validation_commands": list(self.validation_commands),
            "acceptance_criteria": list(self.acceptance_criteria),
            "dependencies": list(self.dependencies),
            "depth": self.depth,
            "family_id": self.family_id,
            "profile_id": self.profile_id,
            "gap_kind": self.gap_kind,
            "priority": self.priority,
            "stop_policy": self.stop_policy,
            "completion_authority": False,
            "mutation_authority": False,
            "seed_board_edit": False,
        }


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Per-gap decision recorded before any append."""

    gap_id: str
    identity_key: str
    disposition: AdmissionDisposition
    reason_codes: tuple[str, ...] = ()
    task_id: str = ""
    task_cid: str = ""
    goal_id: str = ""
    priority: int = 0
    schema: str = ADMISSION_DECISION_SCHEMA

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
            self, "reason_codes", _ids(self.reason_codes, "reason_codes", maximum=32)
        )
        object.__setattr__(
            self, "task_id", _identifier(self.task_id, "task_id", required=False)
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
        object.__setattr__(
            self, "priority", _nonneg_int(self.priority, "priority", maximum=10_000)
        )
        if self.schema != ADMISSION_DECISION_SCHEMA:
            raise RefillV2Error(
                f"decision schema must be {ADMISSION_DECISION_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "gap_id": self.gap_id,
            "identity_key": self.identity_key,
            "disposition": self.disposition.value,
            "reason_codes": list(self.reason_codes),
            "task_id": self.task_id,
            "task_cid": self.task_cid,
            "goal_id": self.goal_id,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class RefillMemory:
    """Cross-epoch memory for dedupe, retries, and open work."""

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
            _ids(self.admitted_identity_keys, "admitted_identity_keys", maximum=4_096),
        )
        object.__setattr__(
            self,
            "open_task_count",
            _nonneg_int(self.open_task_count, "open_task_count", maximum=1_000_000),
        )
        attempts = _mapping_proxy(self.attempt_counts, "attempt_counts")
        for _key, value in attempts.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RefillV2Error("attempt_counts values must be non-negative ints")
        object.__setattr__(self, "attempt_counts", attempts)
        object.__setattr__(
            self,
            "last_failure_fingerprints",
            _mapping_proxy(
                self.last_failure_fingerprints, "last_failure_fingerprints"
            ),
        )
        object.__setattr__(
            self,
            "last_attempt_epoch_s",
            _mapping_proxy(self.last_attempt_epoch_s, "last_attempt_epoch_s"),
        )
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
class AdmissionReceipt:
    """Result of one bounded DerivedTaskAdmission@2 epoch."""

    disposition: EpochDisposition
    epoch_id: str
    scan_identity: ScanIdentity
    decisions: tuple[AdmissionDecision, ...] = ()
    admitted_tasks: tuple[DerivedTaskProposal, ...] = ()
    scores: tuple[GapScore, ...] = ()
    policy: RefillPolicyV2 = field(default_factory=RefillPolicyV2)
    memory: RefillMemory = field(default_factory=RefillMemory)
    derived_goal_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    seed_definitions_mutated: bool = False
    schema: str = ADMISSION_RECEIPT_SCHEMA
    interface: str = DERIVED_TASK_ADMISSION_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, EpochDisposition, "disposition"),
        )
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        if not isinstance(self.scan_identity, ScanIdentity):
            raise RefillV2Error("scan_identity must be ScanIdentity")
        if not isinstance(self.policy, RefillPolicyV2):
            object.__setattr__(self, "policy", RefillPolicyV2.from_dict(self.policy))
        if not isinstance(self.memory, RefillMemory):
            raise RefillV2Error("memory must be RefillMemory")
        object.__setattr__(
            self,
            "derived_goal_ids",
            _ids(self.derived_goal_ids, "derived_goal_ids", maximum=256),
        )
        object.__setattr__(
            self, "reason_codes", _ids(self.reason_codes, "reason_codes", maximum=64)
        )
        object.__setattr__(
            self,
            "seed_definitions_mutated",
            _bool(self.seed_definitions_mutated, "seed_definitions_mutated"),
        )
        if self.seed_definitions_mutated:
            raise RefillV2AuthorityError(
                "epoch receipt cannot report seed definition mutation"
            )
        if self.interface != DERIVED_TASK_ADMISSION_INTERFACE:
            raise RefillV2Error(
                f"interface must be {DERIVED_TASK_ADMISSION_INTERFACE}"
            )
        if self.schema != ADMISSION_RECEIPT_SCHEMA:
            raise RefillV2Error(f"receipt schema must be {ADMISSION_RECEIPT_SCHEMA}")
        if len(self.admitted_tasks) > self.policy.max_tasks_per_epoch:
            raise RefillV2BoundsError("admitted tasks exceed max_tasks_per_epoch")
        derived_count = count_derived_goals(self.derived_goal_ids)
        if derived_count > self.policy.max_goals_per_epoch:
            raise RefillV2BoundsError(
                "derived goals exceed max_goals_per_epoch (seed goals excluded)"
            )
        for goal_id in self.derived_goal_ids:
            if is_seed_goal(goal_id):
                raise RefillV2BoundsError(
                    f"seed goal {goal_id} must not appear in derived_goal_ids"
                )
        if self.memory.open_task_count > self.policy.max_open_tasks:
            raise RefillV2BoundsError("open_task_count exceeds max_open_tasks")

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
            "version": DERIVED_TASK_ADMISSION_VERSION,
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "program_id": PROGRAM_ID,
            "producer_id": ADMISSION_PRODUCER_ID,
            "disposition": self.disposition.value,
            "epoch_id": self.epoch_id,
            "scan_identity": self.scan_identity.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "admitted_tasks": [task.to_dict() for task in self.admitted_tasks],
            "scores": [score.to_dict() for score in self.scores],
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


# ---------------------------------------------------------------------------
# Scoring engine — ReachableGapScorer@1
# ---------------------------------------------------------------------------


def _classify_pre_score_rejections(
    gap: ReachableGapCandidate,
    *,
    policy: RefillPolicyV2,
) -> list[str]:
    """Return rejection reason codes that apply before score weighting."""

    reasons: list[str] = []
    kind = gap.gap_kind

    if not gap.refill_eligible:
        reasons.append("not_refill_eligible")

    if kind is GapKind.CARTESIAN_UNSUPPORTED or (
        gap.support_status == "unsupported"
        and gap.route_disposition in {"", "excluded", "cartesian"}
    ):
        if not policy.cartesian_unsupported_allowed:
            reasons.append("cartesian_unsupported")

    if kind is GapKind.ADVISOR_ONLY or gap.authority_ceiling in {
        "advisory",
        "advisor",
        "advisor_only",
    }:
        if not policy.advisor_only_allowed:
            reasons.append("advisor_only")

    if kind is GapKind.VAGUE_CLEANUP or is_vague_cleanup_text(
        gap.subject, gap.evidence, gap.owner
    ):
        if not policy.vague_cleanup_allowed:
            reasons.append("vague_cleanup")

    if kind is GapKind.UNSAFE:
        reasons.append("unsafe")

    if kind is GapKind.BROAD_CODEBASE:
        reasons.append("broad_codebase")

    if kind.value in _NON_REFILL_KINDS and kind not in {
        GapKind.CARTESIAN_UNSUPPORTED,
        GapKind.ADVISOR_ONLY,
        GapKind.VAGUE_CLEANUP,
        GapKind.UNSAFE,
        GapKind.BROAD_CODEBASE,
    }:
        reasons.append(kind.value)

    scope_paths = gap.owned_paths
    if not policy.unscoped_codebase_refill_allowed and is_unscoped_codebase_scope(
        scope_paths
    ):
        reasons.append("broad_unscoped")

    protected_hits = [
        path
        for path in scope_paths
        if _path_hits_protected(path, policy.protected_paths)
    ]
    if protected_hits:
        reasons.append("protected_path")

    for command in gap.validation_commands:
        if is_unsafe_command(command):
            reasons.append("unsafe_command")
            break

    # Path traversal / absolute paths already fail normalization; residual
    # unsafe owner patterns.
    owner_norm = gap.owner.replace("\\", "/")
    if owner_norm.startswith("/") or ".." in owner_norm.split("/"):
        reasons.append("unsafe_owner_path")

    return reasons


def _priority_for(gap: ReachableGapCandidate) -> int:
    base = int(_KIND_PRIORITY.get(gap.gap_kind.value, 40))
    # Prefer shallower refinements and richer discovery evidence.
    depth_penalty = max(0, gap.depth - 1) * 5
    discovery_bonus = 5 if gap.discovery_receipt else 0
    evidence_bonus = 5 if gap.evidence_obligation else 0
    fixture_bonus = min(5, len(gap.fixture_ids))
    return max(0, base - depth_penalty + discovery_bonus + evidence_bonus + fixture_bonus)


def score_reachable_gap(
    gap: ReachableGapCandidate | Mapping[str, Any],
    *,
    policy: RefillPolicyV2 | Mapping[str, Any] | None = None,
) -> GapScore:
    """Score one reachable gap under ReachableGapScorer@1 (deterministic)."""

    if policy is None:
        policy = RefillPolicyV2.default()
    elif isinstance(policy, Mapping):
        policy = RefillPolicyV2.from_dict(policy)
    elif not isinstance(policy, RefillPolicyV2):
        raise RefillV2Error("policy must be RefillPolicyV2 or mapping")

    if isinstance(gap, Mapping):
        gap = ReachableGapCandidate.from_dict(gap)
    elif not isinstance(gap, ReachableGapCandidate):
        raise RefillV2Error("gap must be ReachableGapCandidate or mapping")

    rejections = _classify_pre_score_rejections(gap, policy=policy)
    priority = _priority_for(gap) if not rejections else 0
    admissible = not rejections and priority >= policy.min_score
    return GapScore(
        gap_id=gap.gap_id,
        content_identity=gap.identity_key,
        priority=priority,
        admissible=admissible,
        rejection_reasons=tuple(rejections),
        gap_kind=gap.gap_kind.value,
        owner=gap.owner,
        evidence_obligation=gap.evidence_obligation,
        discovery_receipt=gap.discovery_receipt,
        authority_ceiling=gap.authority_ceiling,
    )


def score_reachable_gaps(
    gaps: Sequence[ReachableGapCandidate | Mapping[str, Any]],
    *,
    policy: RefillPolicyV2 | Mapping[str, Any] | None = None,
) -> tuple[GapScore, ...]:
    """Score a population deterministically ordered by (priority desc, gap_id)."""

    if policy is None:
        policy = RefillPolicyV2.default()
    elif isinstance(policy, Mapping):
        policy = RefillPolicyV2.from_dict(policy)

    if len(gaps) > MAX_GAPS:
        raise RefillV2BoundsError(f"gaps exceed hard bound of {MAX_GAPS}")

    scores = [score_reachable_gap(gap, policy=policy) for gap in gaps]
    scores.sort(key=lambda score: (-score.priority, score.gap_id, score.content_identity))
    return tuple(scores)


class ReachableGapScorer:
    """ReachableGapScorer@1 — deterministic scorer for reachable gaps."""

    interface: Final = REACHABLE_GAP_SCORER_INTERFACE
    version: Final = REACHABLE_GAP_SCORER_VERSION

    def __init__(self, policy: RefillPolicyV2 | Mapping[str, Any] | None = None) -> None:
        if policy is None:
            self.policy = RefillPolicyV2.default()
        elif isinstance(policy, Mapping):
            self.policy = RefillPolicyV2.from_dict(policy)
        elif isinstance(policy, RefillPolicyV2):
            self.policy = policy
        else:
            raise RefillV2Error("policy must be RefillPolicyV2 or mapping")

    def score(
        self, gap: ReachableGapCandidate | Mapping[str, Any]
    ) -> GapScore:
        return score_reachable_gap(gap, policy=self.policy)

    def score_many(
        self, gaps: Sequence[ReachableGapCandidate | Mapping[str, Any]]
    ) -> tuple[GapScore, ...]:
        return score_reachable_gaps(gaps, policy=self.policy)

    def receipt(
        self, gaps: Sequence[ReachableGapCandidate | Mapping[str, Any]]
    ) -> dict[str, Any]:
        scores = self.score_many(gaps)
        return {
            "schema": SCORER_RECEIPT_SCHEMA,
            "interface": self.interface,
            "version": self.version,
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "program_id": PROGRAM_ID,
            "producer_id": PRODUCER_ID,
            "policy": self.policy.to_dict(),
            "scores": [score.to_dict() for score in scores],
            "admissible_count": sum(1 for score in scores if score.admissible),
            "rejected_count": sum(1 for score in scores if not score.admissible),
            "completion_authority": False,
            "mutation_authority": False,
            "receipt_digest": _stable_digest(
                [score.to_dict() for score in scores]
            ),
        }


# ---------------------------------------------------------------------------
# Admission engine — DerivedTaskAdmission@2
# ---------------------------------------------------------------------------


def _derived_goal_id_for(gap: ReachableGapCandidate, *, parent_goal_id: str) -> str:
    short = hashlib.sha256(gap.identity_key.encode("utf-8")).hexdigest()[:8]
    return f"LFP2-D-{parent_goal_id}-{short}"


def _task_id_for(gap: ReachableGapCandidate, sequence: int) -> str:
    short = hashlib.sha256(gap.identity_key.encode("utf-8")).hexdigest()[:10]
    return f"LFP2-R{sequence:04d}-{short}"


def _task_cid_for(
    task_id: str,
    gap: ReachableGapCandidate,
    scan_identity: ScanIdentity,
) -> str:
    return _stable_digest(
        {
            "task_id": task_id,
            "gap_identity": gap.identity_key,
            "owned_paths": list(gap.owned_paths),
            "evidence_obligation": gap.evidence_obligation,
            "discovery_receipt": gap.discovery_receipt,
            "scan": scan_identity.to_dict(),
            "validation_commands": list(gap.validation_commands),
            "producer": ADMISSION_PRODUCER_ID,
        }
    )


def _default_validation_commands(gap: ReachableGapCandidate) -> tuple[str, ...]:
    if gap.validation_commands:
        return gap.validation_commands
    return (
        "cd ipfs_datasets_py && python -m pytest -q "
        "tests/unit/logic/conformance/test_refill_v2.py",
    )


def _default_acceptance(gap: ReachableGapCandidate) -> tuple[str, ...]:
    return (
        f"resolve gap {gap.gap_id} of kind {gap.gap_kind.value}",
        "owner-scoped paths only",
        "no seed board mutation",
        "no completion authority",
        f"evidence obligation: {gap.evidence_obligation}",
    )


def _missing_admission_requirements(
    gap: ReachableGapCandidate,
    *,
    policy: RefillPolicyV2,
) -> list[str]:
    """Requirements that must be present before append (fail-closed)."""

    missing: list[str] = []
    if not gap.identity_key:
        missing.append("missing_content_identity")
    if not gap.evidence_obligation:
        missing.append("missing_evidence_obligation")
    if not gap.discovery_receipt:
        missing.append("missing_discovery_receipt")
    if not gap.owner:
        missing.append("missing_owner")
    if not gap.owned_paths:
        missing.append("missing_owned_paths")
    if not gap.validation_commands and not _default_validation_commands(gap):
        missing.append("missing_validation")
    # Dependencies may be empty for root derived work; lineage still records
    # originating_goal_id which is always present after normalization.
    if not gap.originating_goal_id:
        missing.append("missing_dependency_lineage")
    if not gap.authority_ceiling:
        missing.append("missing_authority_ceiling")
    budget = gap.context_budget_bytes or policy.max_context_budget_bytes
    if budget > policy.max_context_budget_bytes:
        missing.append("context_budget_exceeded")
    return missing


def _disposition_for_rejection(reason: str) -> AdmissionDisposition:
    mapping = {
        "cartesian_unsupported": AdmissionDisposition.CARTESIAN_REJECTED,
        "advisor_only": AdmissionDisposition.ADVISOR_ONLY_REJECTED,
        "vague_cleanup": AdmissionDisposition.VAGUE_CLEANUP_REJECTED,
        "unsafe": AdmissionDisposition.UNSAFE_REJECTED,
        "unsafe_command": AdmissionDisposition.UNSAFE_REJECTED,
        "unsafe_owner_path": AdmissionDisposition.UNSAFE_REJECTED,
        "protected_path": AdmissionDisposition.PROTECTED_REJECTED,
        "broad_unscoped": AdmissionDisposition.BROAD_REJECTED,
        "broad_codebase": AdmissionDisposition.BROAD_REJECTED,
        "not_refill_eligible": AdmissionDisposition.NOT_REFILL_ELIGIBLE,
        "duplicate_identity": AdmissionDisposition.DUPLICATE,
        "depth_exceeded": AdmissionDisposition.DEPTH_REJECTED,
        "retry_exhausted": AdmissionDisposition.RETRY_EXHAUSTED,
        "cooldown_active": AdmissionDisposition.COOLDOWN,
        "open_work_ceiling": AdmissionDisposition.BOUND_REJECTED,
        "task_bound": AdmissionDisposition.BOUND_REJECTED,
        "goal_bound": AdmissionDisposition.BOUND_REJECTED,
        "low_score": AdmissionDisposition.LOW_SCORE,
        "missing_content_identity": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_evidence_obligation": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_discovery_receipt": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_owner": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_owned_paths": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_validation": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_dependency_lineage": AdmissionDisposition.MISSING_REQUIREMENT,
        "missing_authority_ceiling": AdmissionDisposition.MISSING_REQUIREMENT,
        "context_budget_exceeded": AdmissionDisposition.BOUND_REJECTED,
        "authority_claim": AdmissionDisposition.AUTHORITY_REJECTED,
    }
    return mapping.get(reason, AdmissionDisposition.MALFORMED)


def _evaluate_admission(
    gap: ReachableGapCandidate,
    score: GapScore,
    *,
    policy: RefillPolicyV2,
    memory: RefillMemory,
    admitted_this_epoch: int,
    derived_goals_this_epoch: set[str],
    now_epoch_s: int,
) -> tuple[AdmissionDisposition, tuple[str, ...]]:
    # Scorer rejections take precedence — never append these classes.
    if score.rejection_reasons:
        primary = score.rejection_reasons[0]
        return _disposition_for_rejection(primary), score.rejection_reasons

    if not score.admissible or score.priority < policy.min_score:
        return AdmissionDisposition.LOW_SCORE, ("low_score",)

    missing = _missing_admission_requirements(gap, policy=policy)
    if missing:
        return AdmissionDisposition.MISSING_REQUIREMENT, tuple(missing)

    if gap.identity_key in memory.admitted_identity_keys:
        return AdmissionDisposition.DUPLICATE, ("duplicate_identity",)

    if gap.depth > policy.max_refinement_depth:
        return AdmissionDisposition.DEPTH_REJECTED, ("depth_exceeded",)

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
            memory.last_attempt_epoch_s.get(gap.identity_key, gap.last_attempt_epoch_s)
            or 0
        )
        if last_ts and now_epoch_s and (now_epoch_s - last_ts) < policy.cooldown_seconds:
            return AdmissionDisposition.COOLDOWN, ("cooldown_active",)

    open_budget = policy.max_open_tasks - memory.open_task_count
    if open_budget <= 0:
        return AdmissionDisposition.BOUND_REJECTED, ("open_work_ceiling",)

    if admitted_this_epoch >= policy.max_tasks_per_epoch:
        return AdmissionDisposition.BOUND_REJECTED, ("task_bound",)

    candidate_goal = _derived_goal_id_for(gap, parent_goal_id=policy.parent_goal_id)
    prospective_goals = set(derived_goals_this_epoch)
    if candidate_goal not in prospective_goals and not is_seed_goal(candidate_goal):
        if len(prospective_goals) >= policy.max_goals_per_epoch:
            return AdmissionDisposition.BOUND_REJECTED, ("goal_bound",)

    return AdmissionDisposition.ADMITTED, ("admitted",)


def run_admission_epoch(
    gaps: Sequence[ReachableGapCandidate | Mapping[str, Any]],
    *,
    scan_identity: ScanIdentity | Mapping[str, Any],
    policy: RefillPolicyV2 | Mapping[str, Any] | None = None,
    memory: RefillMemory | None = None,
    epoch_id: str = "",
    now_epoch_s: int | None = None,
) -> AdmissionReceipt:
    """Admit a bounded set of content-addressed derived tasks from scored gaps.

    Cartesian unsupported, advisor-only, vague cleanup, duplicate, unsafe,
    protected, and broad tasks are rejected **before** append. Seed goal
    definitions are never rewritten.
    """

    if policy is None:
        policy = RefillPolicyV2.default()
    elif isinstance(policy, Mapping):
        policy = RefillPolicyV2.from_dict(policy)
    elif not isinstance(policy, RefillPolicyV2):
        raise RefillV2Error("policy must be RefillPolicyV2 or mapping")

    if isinstance(scan_identity, Mapping):
        scan_identity = ScanIdentity.from_dict(scan_identity)
    elif not isinstance(scan_identity, ScanIdentity):
        raise RefillV2Error("scan_identity must be ScanIdentity or mapping")

    if memory is None:
        memory = RefillMemory(now_epoch_s=now_epoch_s or 0)
    now = now_epoch_s if now_epoch_s is not None else memory.now_epoch_s

    if len(gaps) > MAX_GAPS:
        raise RefillV2BoundsError(f"gaps exceed hard bound of {MAX_GAPS}")

    normalized: list[ReachableGapCandidate] = []
    for raw in gaps:
        if isinstance(raw, ReachableGapCandidate):
            normalized.append(raw)
        elif isinstance(raw, Mapping):
            normalized.append(ReachableGapCandidate.from_dict(raw))
        else:
            raise RefillV2Error("each gap must be ReachableGapCandidate or mapping")

    # Score first (deterministic), then admit in score order.
    score_by_id: dict[str, GapScore] = {}
    for gap in normalized:
        score_by_id[gap.gap_id] = score_reachable_gap(gap, policy=policy)

    normalized.sort(
        key=lambda gap: (
            -score_by_id[gap.gap_id].priority,
            gap.gap_id,
            gap.identity_key,
        )
    )

    if not epoch_id:
        epoch_id = "epoch:" + _stable_digest(
            {
                "scan": scan_identity.composite_digest,
                "gap_ids": [gap.gap_id for gap in normalized],
                "policy": policy.to_dict(),
            }
        )[7:23]

    decisions: list[AdmissionDecision] = []
    admitted_tasks: list[DerivedTaskProposal] = []
    derived_goals: set[str] = set(memory.derived_goal_ids)
    epoch_derived_goals: set[str] = set()
    reason_codes: list[str] = []
    next_memory = memory
    sequence = 0
    ordered_scores: list[GapScore] = []

    if not normalized:
        return AdmissionReceipt(
            disposition=EpochDisposition.EMPTY_INPUT,
            epoch_id=epoch_id,
            scan_identity=scan_identity,
            decisions=(),
            admitted_tasks=(),
            scores=(),
            policy=policy,
            memory=next_memory,
            derived_goal_ids=tuple(sorted(derived_goals)),
            reason_codes=("empty_input",),
            seed_definitions_mutated=False,
        )

    for gap in normalized:
        score = score_by_id[gap.gap_id]
        ordered_scores.append(score)
        disposition, reasons = _evaluate_admission(
            gap,
            score,
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
                disposition = AdmissionDisposition.AUTHORITY_REJECTED
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
                    evidence_obligation=gap.evidence_obligation,
                    discovery_receipt=gap.discovery_receipt,
                    authority_ceiling=gap.authority_ceiling,
                    validation_commands=_default_validation_commands(gap),
                    acceptance_criteria=_default_acceptance(gap),
                    dependencies=gap.dependencies,
                    depth=gap.depth,
                    family_id=gap.family_id,
                    profile_id=gap.profile_id,
                    gap_kind=gap.gap_kind.value,
                    priority=score.priority,
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

        decision = AdmissionDecision(
            gap_id=gap.gap_id,
            identity_key=gap.identity_key,
            disposition=disposition,
            reason_codes=reasons,
            task_id=task_id,
            task_cid=task_cid,
            goal_id=goal_id,
            priority=score.priority,
        )
        decisions.append(decision)
        reason_codes.extend(reasons)

    if admitted_tasks:
        epoch_disposition = EpochDisposition.ADMITTED
    elif all(
        decision.disposition is AdmissionDisposition.DUPLICATE for decision in decisions
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
    else:
        epoch_disposition = EpochDisposition.REJECTED

    unique_reasons: list[str] = []
    seen_reasons: set[str] = set()
    for code in reason_codes:
        if code not in seen_reasons:
            seen_reasons.add(code)
            unique_reasons.append(code)

    return AdmissionReceipt(
        disposition=epoch_disposition,
        epoch_id=epoch_id,
        scan_identity=scan_identity,
        decisions=tuple(decisions),
        admitted_tasks=tuple(admitted_tasks),
        scores=tuple(ordered_scores),
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


class DerivedTaskAdmission:
    """DerivedTaskAdmission@2 — strict pre-append admission gate."""

    interface: Final = DERIVED_TASK_ADMISSION_INTERFACE
    version: Final = DERIVED_TASK_ADMISSION_VERSION

    def __init__(self, policy: RefillPolicyV2 | Mapping[str, Any] | None = None) -> None:
        if policy is None:
            self.policy = RefillPolicyV2.default()
        elif isinstance(policy, Mapping):
            self.policy = RefillPolicyV2.from_dict(policy)
        elif isinstance(policy, RefillPolicyV2):
            self.policy = policy
        else:
            raise RefillV2Error("policy must be RefillPolicyV2 or mapping")
        self.scorer = ReachableGapScorer(self.policy)

    def admit(
        self,
        gaps: Sequence[ReachableGapCandidate | Mapping[str, Any]],
        *,
        scan_identity: ScanIdentity | Mapping[str, Any],
        memory: RefillMemory | None = None,
        epoch_id: str = "",
        now_epoch_s: int | None = None,
    ) -> AdmissionReceipt:
        return run_admission_epoch(
            gaps,
            scan_identity=scan_identity,
            policy=self.policy,
            memory=memory,
            epoch_id=epoch_id,
            now_epoch_s=now_epoch_s,
        )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "ADMISSION_PRODUCER_ID",
    "AdmissionDecision",
    "AdmissionDisposition",
    "AdmissionReceipt",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_MAX_CONTEXT_BUDGET_BYTES",
    "DEFAULT_MAX_GOALS_PER_EPOCH",
    "DEFAULT_MAX_OPEN_TASKS",
    "DEFAULT_MAX_REFINEMENT_DEPTH",
    "DEFAULT_MAX_TASKS_PER_EPOCH",
    "DEFAULT_MAX_UNCHANGED_FAILURE_RETRIES",
    "DEFAULT_MIN_OPEN_TASKS",
    "DEFAULT_PROTECTED_PATHS",
    "DEFAULT_STOP_POLICY",
    "DERIVED_TASK_ADMISSION_INTERFACE",
    "DERIVED_TASK_ADMISSION_VERSION",
    "DerivedTaskAdmission",
    "DerivedTaskProposal",
    "EpochDisposition",
    "GOAL_ID",
    "GapKind",
    "GapScore",
    "IMMUTABLE_SEED_GOAL_COUNT",
    "IMMUTABLE_SEED_GOALS",
    "PROGRAM_ID",
    "PRODUCER_ID",
    "REACHABLE_GAP_SCORER_INTERFACE",
    "REACHABLE_GAP_SCORER_VERSION",
    "ReachableGapCandidate",
    "ReachableGapScorer",
    "RefillMemory",
    "RefillPolicyV2",
    "RefillV2AuthorityError",
    "RefillV2BoundsError",
    "RefillV2Error",
    "ScanIdentity",
    "TASK_ID",
    "count_derived_goals",
    "is_seed_goal",
    "is_unsafe_command",
    "is_unscoped_codebase_scope",
    "is_vague_cleanup_text",
    "run_admission_epoch",
    "score_reachable_gap",
    "score_reachable_gaps",
]
