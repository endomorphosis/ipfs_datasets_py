"""Canonical control-plane contracts for the agent supervisor.

This module is intentionally transport-neutral.  Python, CLI, and MCP
adapters can all exchange the same immutable records without acquiring
different authority semantics.

Operation names are closed and each name has a fixed maximum authority.
Mutation requests fail closed unless they carry explicit roots, an exact
authorization decision, lease/fencing data, expected effects, and a scoped
idempotency key.  Result effect claims are checked against both the operation
authority and, when available, the originating request.
"""

from __future__ import annotations

import base64
import binascii
import json
import posixpath
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ..proof.formal_verification_contracts import (
    CanonicalContract,
    ContractValidationError,
    canonical_json_bytes,
    content_identity,
)


CONTROL_CONTRACT_VERSION = 1
CONTRACT_VERSION = CONTROL_CONTRACT_VERSION
SCHEMA_VERSION = CONTROL_CONTRACT_VERSION
CONTROL_CATALOG_VERSION = 2
OPERATION_CATALOG_VERSION = CONTROL_CATALOG_VERSION

OPERATION_CATALOG_V2_REQUIREMENT_ID: Final[str] = (
    "294719425747343997526263348545558645762"
)

CONTROL_BOUNDS_SCHEMA = "ipfs_accelerate_py/agent-supervisor/control-bounds@1"
EXPECTED_EFFECT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/expected-effect@1"
EFFECT_CLAIM_SCHEMA = "ipfs_accelerate_py/agent-supervisor/effect-claim@1"
IDEMPOTENCY_KEY_SCHEMA = "ipfs_accelerate_py/agent-supervisor/idempotency-key@1"
AUTHORIZATION_DECISION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-authorization-decision@1"
)
OPERATION_REQUEST_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/operation-request@1"
)
OPERATION_ERROR_SCHEMA = "ipfs_accelerate_py/agent-supervisor/operation-error@1"
DRY_RUN_PREVIEW_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/dry-run-preview@1"
)
OPERATION_RESULT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/operation-result@1"
OPERATION_CAPABILITY_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/operation-capability@1"
)
CAPABILITY_REPORT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/capability-report@1"
)
CONTROL_TARGET_DESCRIPTOR_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-target-descriptor@2"
)
CONTROL_PAGINATION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-pagination@2"
)
CONTROL_OPERATION_DESCRIPTOR_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-operation-descriptor@2"
)
CONTROL_OPERATION_CATALOG_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-operation-catalog@2"
)
CONTROL_CATALOG_NEGOTIATION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-catalog-negotiation@2"
)
CONTROL_CAPABILITY_RESOLUTION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-capability-resolution@2"
)
EVENT_CURSOR_SCHEMA = "ipfs_accelerate_py/agent-supervisor/event-cursor@2"
EVENT_PAGE_SCHEMA = "ipfs_accelerate_py/agent-supervisor/event-page@2"
CONTROL_QUERY_AUDIT_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-query-audit-receipt@2"
)
CONTROL_PROPOSAL_AUDIT_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-proposal-audit-receipt@2"
)
CONTROL_MUTATION_AUDIT_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-mutation-audit-receipt@2"
)
CONTROL_DISCOVERY_MANIFEST_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-discovery-manifest@1"
)
CONTROL_DISCOVERY_RUNTIME_STATE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-discovery-runtime-state@1"
)
CONTROL_DISCOVERY_OBSERVATION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-discovery-observation@1"
)
CONTROL_DISCOVERY_SAFETY_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-discovery-safety-evidence@1"
)
CONTROL_DISCOVERY_COMPLETION_QUORUM_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/"
    "control-discovery-completion-quorum-evidence@2"
)
CONTROL_DISCOVERY_COMPLETION_MEMBER_HEALTH_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/"
    "control-discovery-completion-member-health@1"
)
LIFECYCLE_COMMAND_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/lifecycle-command@1"
)
CONTROL_SURFACE_PARITY_CASE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-surface-parity-case@1"
)
CONTROL_SURFACE_PARITY_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-surface-parity-evidence@2"
)
CONTROL_SURFACE_PARITY_COMPLETION_QUORUM_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/"
    "control-surface-parity-completion-quorum-evidence@1"
)
CONTROL_SURFACE_PARITY_COMPLETION_MEMBER_HEALTH_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/"
    "control-surface-parity-completion-member-health@1"
)
MUTATION_GUARD_REJECTION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/mutation-guard-rejection@2"
)
CONTROL_MUTATION_GUARD_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-mutation-guard-evidence@3"
)
CONTROL_MUTATION_COMPLETION_QUORUM_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/"
    "control-mutation-completion-quorum-evidence@2"
)
CONTROL_MUTATION_COMPLETION_MEMBER_HEALTH_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/"
    "control-mutation-completion-member-health@1"
)
CONTROL_MUTATION_RUNTIME_STATE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/control-mutation-runtime-state@1"
)
MUTATION_GUARD_EXECUTION_OBSERVATION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/mutation-guard-execution-observation@1"
)

# ASI-G070/ASI-G103: the requirement is emitted only by a validated
# ControlSurfaceParityEvidence record.  Merely mentioning this opaque ID is
# intentionally not completion evidence.
CONTROL_SURFACE_PARITY_REQUIREMENT_ID: Final[str] = (
    "031486194157679117987393491870400400279"
)
CONTROL_SURFACE_PARITY_OBJECTIVE_ID: Final[str] = "ASI-G103"
CONTROL_SURFACE_PARITY_OBJECTIVE_REVISION: Final[str] = "ASI-G103@asi-078"
CONTROL_SURFACE_PARITY_COMPLETION_ANALYZER_VERSION: Final[str] = (
    "asi-g103-objective-validation@1"
)
CONTROL_SURFACE_PARITY_COMPLETION_CONFIGURATION_REVISION: Final[str] = (
    "unified-control-surface-parity-completion@1"
)
CONTROL_SURFACE_PARITY_REQUIRED_EXHAUSTIVE_RECEIPTS: Final[int] = 2
CONTROL_SURFACE_PARITY_ACCEPTANCE_CRITERIA: Final[tuple[str, ...]] = (
    "The shared schema describes all operations",
    (
        "every CLI/MCP adapter decodes and dispatches the canonical request "
        "directly"
    ),
    "canonical records are exactly equal to Python behavior",
    "bounded reads and watches cannot exceed contract limits",
    (
        "unsafe CLI defaults and unconfigured MCP mutation authority fail "
        "closed"
    ),
    (
        "and the exact requirement ID appears only in a "
        "tree/objective/policy-bound parity evidence record that rejects any "
        "surface, vocabulary, schema, or behavior drift."
    ),
)
UNIFIED_CONTROL_OBJECTIVE_ID: Final[str] = "ASI-G070"
UNIFIED_CONTROL_OBJECTIVE_REVISION: Final[str] = "ASI-G070@asi-085"
UNIFIED_CONTROL_COMPLETION_ANALYZER_VERSION: Final[str] = (
    "asi-g070-objective-validation@1"
)
UNIFIED_CONTROL_COMPLETION_CONFIGURATION_REVISION: Final[str] = (
    "unified-control-parent-completion@1"
)
UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS: Final[int] = 2
UNIFIED_CONTROL_PRODUCING_TASK_IDS: Final[tuple[str, ...]] = (
    "ASI-002",
    "ASI-018",
    "ASI-019",
    "ASI-020",
    "ASI-021",
)
UNIFIED_CONTROL_CHILD_GOAL_IDS: Final[tuple[str, ...]] = (
    "ASI-G103",
    "ASI-G104",
    "ASI-G105",
)
UNIFIED_CONTROL_ACCEPTANCE_CRITERIA: Final[tuple[str, ...]] = (
    "Shared operations have schema and behavior parity across Python, CLI, "
    "and MCP",
    "read operations are bounded",
    (
        "mutations require authorization, explicit roots, dry-run/preview, "
        "idempotency, lease/fencing, and audit receipts"
    ),
    "lifecycle state and errors are consistent",
    "tool discovery has no provider or process-start side effects",
)
CONTROL_MUTATION_GUARD_REQUIREMENT_ID: Final[str] = (
    "184125100306462690646212311073240043804"
)
CONTROL_MUTATION_GUARD_OBJECTIVE_ID: Final[str] = "ASI-G104"
CONTROL_MUTATION_GUARD_OBJECTIVE_REVISION: Final[str] = (
    "ASI-G104@asi-077"
)
CONTROL_MUTATION_GUARD_COMPLETION_ANALYZER_VERSION: Final[str] = (
    "asi-g104-objective-validation@1"
)
CONTROL_MUTATION_GUARD_COMPLETION_CONFIGURATION_REVISION: Final[str] = (
    "unified-control-mutation-completion@1"
)
CONTROL_MUTATION_GUARD_REQUIRED_EXHAUSTIVE_RECEIPTS: Final[int] = 2
CONTROL_MUTATION_GUARD_REJECTION_SCENARIOS: Final[tuple[str, ...]] = (
    "path_escape",
    "stale_binding",
    "unauthorized",
    "undeclared_effect",
    "unfenced",
    "unscoped_idempotency",
)
CONTROL_MUTATION_GUARD_ACCEPTANCE_CRITERIA: Final[tuple[str, ...]] = (
    (
        "Unauthorized, unscoped, unfenced, stale, path-escaping, or "
        "undeclared-effect mutations fail before dispatch on every surface"
    ),
    "dry-run stays proposal-only",
    "a permitted current mutation emits a typed applied-effect audit receipt",
    "exact retries and restart replay do not duplicate the backend effect",
    "conflicting reuse fails",
    (
        "and only the complete tamper-evident applied/replayed/rejection "
        "matrix emits the exact requirement ID."
    ),
)
CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID: Final[str] = (
    "186773143401179107362964063059661378722"
)
CONTROL_DISCOVERY_SAFETY_OBJECTIVE_ID: Final[str] = "ASI-G105"
CONTROL_DISCOVERY_SAFETY_OBJECTIVE_REVISION: Final[str] = (
    "ASI-G105@asi-076"
)
CONTROL_DISCOVERY_SAFETY_COMPLETION_ANALYZER_VERSION: Final[str] = (
    "asi-g105-objective-validation@1"
)
CONTROL_DISCOVERY_SAFETY_COMPLETION_CONFIGURATION_REVISION: Final[str] = (
    "unified-control-discovery-completion@1"
)
CONTROL_DISCOVERY_SAFETY_REQUIRED_EXHAUSTIVE_RECEIPTS: Final[int] = 2
CONTROL_DISCOVERY_SAFETY_ACCEPTANCE_CRITERIA: Final[tuple[str, ...]] = (
    (
        "Repeated Python, CLI, and MCP discovery is byte-deterministic and "
        "covers the same closed operation/schema population"
    ),
    "no backend or configured service factory is called",
    (
        "optional supervisor provider imports and process starts remain "
        "independently observed at zero delta"
    ),
    "agent CLI discovery does not construct unrelated runtime state",
    "only tool execution can increment MCP service resolution",
    (
        "and only the complete current-tree three-surface evidence emits the "
        "exact requirement ID."
    ),
)
# Compatibility spelling for callers which describe this boundary as
# discovery isolation rather than discovery safety.
CONTROL_DISCOVERY_ISOLATION_REQUIREMENT_ID: Final[str] = (
    CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID
)

ABSOLUTE_MAX_CONTROL_BYTES = 1_048_576
ABSOLUTE_MAX_CONTROL_ITEMS = 4_096
ABSOLUTE_MAX_CONTROL_DEPTH = 32
ABSOLUTE_MAX_CONTROL_TEXT_BYTES = 65_536


class ControlContractError(ContractValidationError):
    """Base exception for invalid control contracts."""


class UnknownOperationError(ControlContractError):
    """Raised when an operation is not in the closed operation vocabulary."""


class PathEscapeError(ControlContractError):
    """Raised when a root or repository-relative path can escape its scope."""


class MissingIdempotencyError(ControlContractError):
    """Raised when a mutation is not bound to an idempotency key."""


class AuthorizationBindingError(ControlContractError):
    """Raised when mutation authorization is absent, denied, or mismatched."""


class AuthorityViolationError(ControlContractError):
    """Raised when a request or result claims more authority than allowed."""


class ControlBoundsError(ControlContractError):
    """Raised when a control record exceeds a count, byte, or depth bound."""


class CatalogVersionNegotiationError(ControlContractError):
    """Raised when peers have no mutually supported catalog version."""


class UnsupportedCatalogVersionError(CatalogVersionNegotiationError):
    """Compatibility spelling for a failed catalog version negotiation."""


class UnsupportedCapabilityError(ControlContractError):
    """Raised when an operation's required backend capability is absent."""


class EventCursorError(ControlContractError):
    """Raised when an event cursor is malformed or cannot be replayed."""


class CursorReplayError(EventCursorError):
    """Raised when an event cursor is stale, foreign, or out of range."""


class _ControlCanonicalContract(CanonicalContract):
    """Canonical mixin whose decoding failures retain the control error type."""

    @classmethod
    def from_json(cls, payload: str) -> "_ControlCanonicalContract":
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ControlContractError("control contract JSON is malformed") from exc
        if not isinstance(value, Mapping):
            raise ControlContractError(
                "control contract JSON must contain an object"
            )
        decoder = getattr(cls, "from_dict", None)
        if decoder is None:
            raise ControlContractError(
                f"{cls.__name__} does not support from_dict"
            )
        return decoder(value)


class OperationAuthority(str, Enum):
    """Maximum semantic authority of an operation or effect."""

    READ = "read"
    PROPOSAL = "proposal"
    MUTATION = "mutation"

    @property
    def rank(self) -> int:
        return {
            OperationAuthority.READ: 0,
            OperationAuthority.PROPOSAL: 1,
            OperationAuthority.MUTATION: 2,
        }[self]

    def allows(self, other: "OperationAuthority | str") -> bool:
        return self.rank >= _authority(other).rank


Authority = OperationAuthority


class ControlSurface(str, Enum):
    """The independently invoked public supervisor control surfaces."""

    PYTHON = "python"
    CLI = "cli"
    MCP = "mcp"


class ControlBehaviorClass(str, Enum):
    """Behavior classes required before cross-surface parity can qualify."""

    READ_SUCCESS = "read_success"
    PROPOSAL_SUCCESS = "proposal_success"
    STABLE_FAILURE = "stable_failure"
    MUTATION_SUCCESS = "mutation_success"


class Operation(str, Enum):
    """Closed set of supervisor operations shared by all control surfaces."""

    CAPABILITIES = "capabilities"
    STATUS = "status"
    HEALTH = "health"
    METRICS = "metrics"
    GOALS = "goals"
    TASKS = "tasks"
    BUNDLES = "bundles"
    LANES = "lanes"
    EVENTS = "events"
    RECEIPTS = "receipts"
    CACHE_INSPECT = "cache_inspect"
    CACHES = "cache_inspect"
    ARTIFACT_QUERY = "artifact_query"

    OBJECTIVE_PREVIEW = "objective_preview"
    PLAN = "plan"
    PLAN_CREATE_PREVIEW = "plan_create_preview"
    PLAN_STEER_PREVIEW = "plan_steer_preview"
    WORKFLOW_PREVIEW = "workflow_preview"
    RESCUE_PREVIEW = "rescue_preview"

    OBJECTIVE_REFINE = "objective_refine"
    OBJECTIVE_RECONCILE = "objective_reconcile"
    BACKLOG_REFILL = "backlog_refill"
    REFILL = "backlog_refill"
    PLAN_CREATE_APPLY = "plan_create_apply"
    PLAN_STEER_APPLY = "plan_steer_apply"
    WORKFLOW_MATERIALIZE = "workflow_materialize"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    DRAIN = "drain"
    STOP = "stop"
    RESTART = "restart"
    RETRY = "retry"
    CANCEL = "cancel"
    QUARANTINE = "quarantine"
    VALIDATION_REPLAY = "validation_replay"
    RESCUE = "rescue"

    @property
    def authority(self) -> OperationAuthority:
        return OPERATION_AUTHORITIES[self]

    @property
    def mutating(self) -> bool:
        return self.authority is OperationAuthority.MUTATION


READ_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    {
        Operation.CAPABILITIES,
        Operation.STATUS,
        Operation.HEALTH,
        Operation.METRICS,
        Operation.GOALS,
        Operation.TASKS,
        Operation.BUNDLES,
        Operation.LANES,
        Operation.EVENTS,
        Operation.RECEIPTS,
        Operation.CACHE_INSPECT,
        Operation.ARTIFACT_QUERY,
    }
)
PROPOSAL_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    {
        Operation.OBJECTIVE_PREVIEW,
        Operation.PLAN,
        Operation.PLAN_CREATE_PREVIEW,
        Operation.PLAN_STEER_PREVIEW,
        Operation.WORKFLOW_PREVIEW,
        Operation.RESCUE_PREVIEW,
    }
)
MUTATION_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    set(Operation).difference(READ_OPERATIONS).difference(PROPOSAL_OPERATIONS)
)
PROMPT_CONTROL_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    {
        Operation.WORKFLOW_PREVIEW,
        Operation.WORKFLOW_MATERIALIZE,
        Operation.RESTART,
        Operation.RESCUE_PREVIEW,
        Operation.RESCUE,
    }
)
PLAN_CONTROL_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    {
        Operation.PLAN_CREATE_PREVIEW,
        Operation.PLAN_CREATE_APPLY,
        Operation.PLAN_STEER_PREVIEW,
        Operation.PLAN_STEER_APPLY,
    }
)
# Workflow aliases share the create/steer facade but keep their own catalog
# identity for Python/CLI/MCP discovery and parity receipts.
PLAN_WORKFLOW_ALIAS_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    {
        Operation.WORKFLOW_PREVIEW,
        Operation.WORKFLOW_MATERIALIZE,
    }
)
DOWNSTREAM_EFFECT_PREVIEW_OPERATIONS: Final[frozenset[Operation]] = frozenset(
    {
        Operation.WORKFLOW_PREVIEW,
        Operation.RESCUE_PREVIEW,
        Operation.PLAN_CREATE_PREVIEW,
        Operation.PLAN_STEER_PREVIEW,
    }
)
OPERATION_AUTHORITIES: Final[Mapping[Operation, OperationAuthority]] = (
    MappingProxyType(
        {
            **{item: OperationAuthority.READ for item in READ_OPERATIONS},
            **{item: OperationAuthority.PROPOSAL for item in PROPOSAL_OPERATIONS},
            **{item: OperationAuthority.MUTATION for item in MUTATION_OPERATIONS},
        }
    )
)


class EffectKind(str, Enum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    WRITE_STATE = "write_state"
    WRITE_REPOSITORY = "write_repository"
    DELETE_STATE = "delete_state"
    DELETE_REPOSITORY = "delete_repository"
    LIFECYCLE_TRANSITION = "lifecycle_transition"
    START_PROCESS = "start_process"
    STOP_PROCESS = "stop_process"
    EXECUTE_VALIDATION = "execute_validation"
    EMIT_AUDIT = "emit_audit"

    @property
    def authority(self) -> OperationAuthority:
        if self is EffectKind.OBSERVE:
            return OperationAuthority.READ
        if self is EffectKind.PROPOSE:
            return OperationAuthority.PROPOSAL
        return OperationAuthority.MUTATION


class AuthorizationVerdict(str, Enum):
    PERMIT = "permit"
    DENY = "deny"


class OperationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"

    @property
    def successful(self) -> bool:
        return self is OperationStatus.SUCCEEDED


class ErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    UNKNOWN_OPERATION = "unknown_operation"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    STALE_TREE = "stale_tree"
    STALE_LEASE = "stale_lease"
    BOUNDS_EXCEEDED = "bounds_exceeded"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_CURSOR = "invalid_cursor"
    CURSOR_EXPIRED = "cursor_expired"
    PATH_ESCAPE = "path_escape"
    IDEMPOTENCY_REQUIRED = "idempotency_required"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    AUTHORITY_VIOLATION = "authority_violation"
    INVALID_LIFECYCLE_TRANSITION = "invalid_lifecycle_transition"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class LifecycleAction(str, Enum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    DRAIN = "drain"
    STOP = "stop"
    RESTART = "restart"
    RETRY = "retry"
    CANCEL = "cancel"
    QUARANTINE = "quarantine"

    @property
    def operation(self) -> Operation:
        return Operation(self.value)


LifecycleOperation = LifecycleAction


def _text(
    value: Any,
    name: str,
    *,
    required: bool = True,
    max_bytes: int = ABSOLUTE_MAX_CONTROL_TEXT_BYTES,
) -> str:
    if not isinstance(value, str):
        raise ControlContractError(f"{name} must be a string")
    result = value.strip()
    if required and not result:
        raise ControlContractError(f"{name} must not be empty")
    if "\x00" in result:
        raise ControlContractError(f"{name} must not contain NUL")
    if len(result.encode("utf-8")) > max_bytes:
        raise ControlBoundsError(f"{name} exceeds {max_bytes} UTF-8 bytes")
    return result


def _nonnegative(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlContractError(f"{name} must be a non-negative integer")
    return value


def _positive(value: Any, name: str) -> int:
    result = _nonnegative(value, name)
    if result < 1:
        raise ControlContractError(f"{name} must be at least 1")
    return result


def _enum(value: Any, kind: type[Enum], name: str) -> Any:
    try:
        return kind(str(getattr(value, "value", value)))
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in kind)
        if kind is Operation:
            raise UnknownOperationError(
                f"unknown operation {value!r}; allowed operations: {allowed}"
            ) from exc
        raise ControlContractError(f"{name} must be one of: {allowed}") from exc


def _operation(value: Any) -> Operation:
    return _enum(value, Operation, "operation")


def _authority(value: Any) -> OperationAuthority:
    return _enum(value, OperationAuthority, "authority")


def _schema(payload: Mapping[str, Any], expected: str) -> None:
    if not isinstance(payload, Mapping):
        raise ControlContractError("control contract payload must be an object")
    supplied = payload.get("schema")
    if supplied not in (None, "", expected):
        raise ControlContractError(
            f"unsupported control schema {supplied!r}; expected {expected}"
        )
    version = payload.get("contract_version", payload.get("schema_version"))
    if version not in (None, CONTROL_CONTRACT_VERSION):
        raise ControlContractError("unsupported control contract version")


def _reject_unknown(
    payload: Mapping[str, Any], allowed: Iterable[str], noun: str
) -> None:
    if set(payload).difference(allowed):
        raise ControlContractError(
            f"{noun} contains unsupported fields; rebuild its canonical payload"
        )


def _identity(payload: Mapping[str, Any], actual: str, noun: str) -> None:
    claimed = payload.get("content_id")
    if claimed not in (None, "") and claimed != actual:
        raise ControlContractError(f"{noun} identity does not match payload")


def _absolute_root(value: Any, name: str) -> str:
    result = _text(value, name).replace("\\", "/")
    if not result.startswith("/"):
        raise PathEscapeError(f"{name} must be an absolute path")
    if ".." in PurePosixPath(result).parts:
        raise PathEscapeError(f"{name} must not traverse a parent")
    normalized = posixpath.normpath(result)
    if normalized == "/":
        raise PathEscapeError(f"{name} must not be the filesystem root")
    return normalized


def _relative_path(value: Any, name: str, *, required: bool = True) -> str:
    result = _text(value, name, required=required).replace("\\", "/")
    if not result:
        return ""
    candidate = PurePosixPath(result)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or (candidate.parts and candidate.parts[0].endswith(":"))
    ):
        raise PathEscapeError(f"{name} must be repository-relative")
    normalized = candidate.as_posix().removeprefix("./")
    if normalized in ("", "."):
        if required:
            raise PathEscapeError(f"{name} must not be empty")
        return ""
    return normalized


def _strings(
    values: Any,
    name: str,
    *,
    required: bool = False,
    maximum: int = ABSOLUTE_MAX_CONTROL_ITEMS,
) -> tuple[str, ...]:
    if values is None:
        source: Any = ()
    elif isinstance(values, str):
        source = (values,)
    elif isinstance(values, Sequence) and not isinstance(
        values, (bytes, bytearray, memoryview)
    ):
        source = values
    else:
        raise ControlContractError(f"{name} must be a sequence of strings")
    result = tuple(sorted({_text(item, name) for item in source}))
    if required and not result:
        raise ControlContractError(f"{name} must not be empty")
    if len(result) > maximum:
        raise ControlBoundsError(f"{name} exceeds its count bound")
    return result


def _paths(values: Any, name: str) -> tuple[str, ...]:
    return tuple(
        sorted(_relative_path(item, name) for item in _strings(values, name))
    )


_PATH_KEYS: Final[frozenset[str]] = frozenset(
    {
        "path",
        "paths",
        "repository_path",
        "repository_paths",
        "target_path",
        "target_paths",
        "artifact_path",
        "artifact_paths",
        "state_path",
        "state_paths",
        "worktree_path",
        "worktree_paths",
    }
)


_PROMPT_CONTROL_PARAMETER_FIELDS: Final[
    Mapping[Operation, frozenset[str]]
] = MappingProxyType(
    {
        Operation.WORKFLOW_PREVIEW: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "directory",
                "prompt_source",
                "output_mode",
                "markdown_path",
                "duckdb_path",
                "request_root",
                "scan_root",
                "catalog_root",
            }
        ),
        Operation.WORKFLOW_MATERIALIZE: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "preview_ref",
                "preview_root",
                "preview_repository_id",
                "preview_tree_id",
                "preview_objective_id",
                "preview_objective_revision",
                "preview_policy_id",
                "preview_policy_revision",
                "catalog_root",
                "output_mode",
                "markdown_path",
                "duckdb_path",
                "expected_revision",
                "apply_request",
            }
        ),
        Operation.RESTART: frozenset(
            {
                "target",
                "repository_id",
                "target_id",
                "run_id",
                "configuration_root",
                "expected_revision",
                "deadline_ms",
                "health_window_ms",
                "reason",
            }
        ),
        Operation.RESCUE_PREVIEW: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "incident_cid",
                "incident_root",
                "incident_repository_id",
                "incident_tree_id",
                "incident_objective_id",
                "incident_objective_revision",
                "incident_policy_id",
                "incident_policy_revision",
                "exhaustion_receipt_cid",
                "allow_llm_fallback",
                "max_actions",
                "deadline_ms",
            }
        ),
        Operation.RESCUE: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "incident_cid",
                "incident_root",
                "incident_repository_id",
                "incident_tree_id",
                "incident_objective_id",
                "incident_objective_revision",
                "incident_policy_id",
                "incident_policy_revision",
                "rescue_plan_cid",
                "rescue_plan_root",
                "rescue_plan_incident_cid",
                "rescue_plan_tree_id",
                "action_index",
                "expected_revision",
                "deadline_ms",
            }
        ),
    }
)

_PLAN_CONTROL_PARAMETER_FIELDS: Final[
    Mapping[Operation, frozenset[str]]
] = MappingProxyType(
    {
        Operation.PLAN_CREATE_PREVIEW: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "mode",
                "plan_request",
                "materials",
                "compatibility_alias",
                "directory",
                "prompt_source",
                "output_mode",
                "markdown_path",
                "duckdb_path",
                "request_root",
                "scan_root",
                "catalog_root",
            }
        ),
        Operation.PLAN_CREATE_APPLY: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "preview_ref",
                "preview_root",
                "preview_repository_id",
                "preview_tree_id",
                "preview_objective_id",
                "preview_objective_revision",
                "preview_policy_id",
                "preview_policy_revision",
                "apply_request",
                "output_mode",
                "markdown_path",
                "duckdb_path",
                "expected_revision",
                "catalog_root",
            }
        ),
        Operation.PLAN_STEER_PREVIEW: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "plan_request",
                "materials",
                "live_state",
                "directive_cid",
                "base_admitted_plan_root",
                "base_materialized_plan_root",
            }
        ),
        Operation.PLAN_STEER_APPLY: frozenset(
            {
                "target",
                "repository_id",
                "tree_id",
                "preview_ref",
                "preview_root",
                "apply_request",
                "markdown_path",
                "duckdb_path",
                "expected_revision",
                "output_mode",
            }
        ),
    }
)

_PROMPT_SOURCE_FIELDS: Final[frozenset[str]] = frozenset(
    {"kind", "content_cid", "artifact_ref", "inline_text"}
)


def _validate_plan_control_parameters(
    operation: Operation,
    parameters: Mapping[str, Any],
) -> None:
    """Validate closed plan create/steer parameter shapes (PDR-032)."""

    allowed = _PLAN_CONTROL_PARAMETER_FIELDS.get(operation)
    if allowed is None:
        return
    unknown = set(parameters).difference(allowed)
    if unknown:
        raise ControlContractError(
            f"{operation.value} parameters contain unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    target = parameters.get("target")
    if target is not None and not isinstance(target, Mapping):
        raise ControlContractError("target must be an object")
    for name in ("plan_request", "materials", "live_state", "apply_request"):
        value = parameters.get(name)
        if value is not None and not isinstance(value, Mapping):
            raise ControlContractError(f"{name} must be an object")
    mode = parameters.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise ControlContractError("mode must be a string")
    output_mode = parameters.get("output_mode")
    if output_mode not in (None, "markdown", "duckdb", "both"):
        raise ControlContractError(
            "output_mode must be markdown, duckdb, or both"
        )
    if operation in {
        Operation.PLAN_CREATE_APPLY,
        Operation.PLAN_STEER_APPLY,
    }:
        # Apply may carry a full apply_request and/or preview bindings.
        # Real mutation admission still requires control-plane permit/lease/
        # fence/idempotency/expected effects regardless of these fields.
        if not any(
            parameters.get(name)
            for name in (
                "apply_request",
                "preview_ref",
                "preview_root",
            )
        ):
            raise ControlContractError(
                f"{operation.value} requires apply_request or preview bindings"
            )


def _validate_prompt_control_parameters(
    operation: Operation,
    parameters: Mapping[str, Any],
    *,
    repository_root: str,
    repository_id: str,
    tree_id: str,
    objective_id: str,
    objective_revision: str,
    policy_id: str,
    policy_revision: str,
) -> None:
    """Validate the closed, transport-neutral parameter shapes for ASI-150."""

    if operation in _PLAN_CONTROL_PARAMETER_FIELDS:
        _validate_plan_control_parameters(operation, parameters)
        return

    allowed = _PROMPT_CONTROL_PARAMETER_FIELDS.get(operation)
    if allowed is None:
        return
    unknown = set(parameters).difference(allowed)
    if unknown:
        raise ControlContractError(
            f"{operation.value} parameters contain unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    target = parameters.get("target")
    if target is not None and not isinstance(target, Mapping):
        raise ControlContractError("target must be an object")

    if operation is Operation.WORKFLOW_PREVIEW:
        missing = {
            name
            for name in ("directory", "prompt_source")
            if name not in parameters
        }
        if missing:
            raise ControlContractError(
                "workflow_preview requires parameters: "
                + ", ".join(sorted(missing))
            )
        directory = parameters.get("directory")
        if directory is not None:
            selected_directory = _text(directory, "directory").replace(
                "\\", "/"
            )
            if selected_directory.startswith("/"):
                normalized_directory = _absolute_root(
                    selected_directory, "directory"
                )
                try:
                    PurePosixPath(normalized_directory).relative_to(
                        PurePosixPath(repository_root)
                    )
                except ValueError as exc:
                    raise PathEscapeError(
                        "directory lies outside repository_root"
                    ) from exc
            else:
                _relative_path(selected_directory, "directory")
        source = parameters.get("prompt_source")
        if source is not None:
            if not isinstance(source, Mapping):
                raise ControlContractError("prompt_source must be an object")
            if set(source).difference(_PROMPT_SOURCE_FIELDS):
                raise ControlContractError(
                    "prompt_source contains unsupported fields"
                )
        output_mode = parameters.get("output_mode")
        if output_mode not in (None, "markdown", "duckdb", "both"):
            raise ControlContractError(
                "output_mode must be markdown, duckdb, or both"
            )

    if operation is Operation.WORKFLOW_MATERIALIZE:
        required_preview_fields = {
            "preview_ref",
            "preview_root",
            "preview_repository_id",
            "preview_tree_id",
            "preview_objective_id",
            "preview_objective_revision",
            "preview_policy_id",
            "preview_policy_revision",
        }
        missing = {
            name
            for name in required_preview_fields
            if not parameters.get(name)
        }
        if missing:
            raise ControlContractError(
                "workflow_materialize requires preview bindings: "
                + ", ".join(sorted(missing))
            )
        output_mode = parameters.get("output_mode")
        if output_mode not in (None, "markdown", "duckdb", "both"):
            raise ControlContractError(
                "output_mode must be markdown, duckdb, or both"
            )

    if operation in {Operation.RESCUE_PREVIEW, Operation.RESCUE}:
        required_incident_fields = {
            "incident_cid",
            "incident_root",
            "incident_repository_id",
            "incident_tree_id",
            "incident_objective_id",
            "incident_objective_revision",
            "incident_policy_id",
            "incident_policy_revision",
        }
        missing = {
            name
            for name in required_incident_fields
            if not parameters.get(name)
        }
        if missing:
            raise ControlContractError(
                f"{operation.value} requires incident bindings: "
                + ", ".join(sorted(missing))
            )

    if operation is Operation.RESCUE:
        missing = {
            name
            for name in (
                "rescue_plan_cid",
                "rescue_plan_root",
                "rescue_plan_incident_cid",
                "rescue_plan_tree_id",
            )
            if not parameters.get(name)
        }
        if missing:
            raise ControlContractError(
                "rescue requires plan bindings: "
                + ", ".join(sorted(missing))
            )
        plan_incident = parameters.get("rescue_plan_incident_cid")
        if plan_incident not in (None, parameters.get("incident_cid")):
            raise AuthorizationBindingError(
                "rescue plan belongs to a different incident"
            )
        plan_tree = parameters.get("rescue_plan_tree_id")
        if plan_tree not in (None, tree_id):
            raise AuthorizationBindingError(
                "rescue plan belongs to a different tree"
            )

    for name in (
        "action_index",
        "deadline_ms",
        "expected_revision",
        "health_window_ms",
        "max_actions",
    ):
        if name in parameters:
            _nonnegative(parameters[name], name)
    if (
        "max_actions" in parameters
        and parameters["max_actions"] > 64
    ):
        raise ControlBoundsError("max_actions exceeds the catalog bound")
    if "allow_llm_fallback" in parameters and not isinstance(
        parameters["allow_llm_fallback"], bool
    ):
        raise ControlContractError("allow_llm_fallback must be a boolean")

    binding_fields = {
        "repository_id": repository_id,
        "tree_id": tree_id,
        "objective_id": objective_id,
        "objective_revision": objective_revision,
        "policy_id": policy_id,
        "policy_revision": policy_revision,
    }
    prefixes: tuple[str, ...] = ()
    if operation is Operation.WORKFLOW_MATERIALIZE:
        prefixes = ("preview",)
    elif operation in {Operation.RESCUE_PREVIEW, Operation.RESCUE}:
        prefixes = ("incident",)
    for prefix in prefixes:
        for suffix, current in binding_fields.items():
            supplied = parameters.get(f"{prefix}_{suffix}")
            if supplied not in (None, current):
                raise AuthorizationBindingError(
                    f"{prefix} {suffix} does not match the current request"
                )


def _freeze_value(
    value: Any,
    *,
    name: str,
    max_depth: int,
    max_items: int,
    max_text_bytes: int,
    check_paths: bool = True,
) -> Any:
    """Validate and deeply freeze a canonical, optionally path-checked value."""

    seen = 0

    def visit(item: Any, depth: int, key_name: str = "") -> Any:
        nonlocal seen
        seen += 1
        if seen > max_items:
            raise ControlBoundsError(f"{name} exceeds its item-count bound")
        if depth > max_depth:
            raise ControlBoundsError(f"{name} exceeds its nesting-depth bound")
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, str):
            text = _text(
                item, name, required=False, max_bytes=max_text_bytes
            )
            if (
                check_paths
                and key_name in _PATH_KEYS
                and not key_name.endswith("paths")
            ):
                return _relative_path(text, key_name, required=False)
            return text
        if isinstance(item, Enum):
            return visit(item.value, depth, key_name)
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise ControlContractError(f"{name} object keys must be strings")
            frozen: dict[str, Any] = {}
            for key in sorted(item):
                normalized_key = _text(
                    key, f"{name} key", max_bytes=max_text_bytes
                )
                raw = item[key]
                if (
                    check_paths
                    and normalized_key in _PATH_KEYS
                    and normalized_key.endswith("paths")
                ):
                    if isinstance(raw, str) or not isinstance(raw, Sequence):
                        raise PathEscapeError(
                            f"{normalized_key} must be a sequence of paths"
                        )
                    frozen[normalized_key] = tuple(
                        _relative_path(member, normalized_key) for member in raw
                    )
                else:
                    frozen[normalized_key] = visit(
                        raw, depth + 1, normalized_key
                    )
            return MappingProxyType(frozen)
        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray, memoryview)
        ):
            return tuple(visit(member, depth + 1, key_name) for member in item)
        raise ControlContractError(
            f"{name} contains unsupported value type {type(item).__name__}"
        )

    return visit(value, 0)


def _coerce_tuple(
    value: Any,
    kind: type,
    decoder: Any,
    name: str,
    *,
    maximum: int = ABSOLUTE_MAX_CONTROL_ITEMS,
) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(
        value, Sequence
    ):
        raise ControlContractError(f"{name} must be a sequence")
    if len(value) > maximum:
        raise ControlBoundsError(f"{name} exceeds its count bound")
    return tuple(
        item if isinstance(item, kind) else decoder(item) for item in value
    )


def _bounded_record(
    value: CanonicalContract,
    noun: str,
    *,
    maximum: int = ABSOLUTE_MAX_CONTROL_BYTES,
) -> None:
    if len(value.canonical_bytes()) > maximum:
        raise ControlBoundsError(f"{noun} exceeds its serialized-byte bound")


@dataclass(frozen=True)
class ControlBounds(_ControlCanonicalContract):
    """Limits carried by every operation request and result."""

    SCHEMA: ClassVar[str] = CONTROL_BOUNDS_SCHEMA

    max_items: int = 256
    max_serialized_bytes: int = 262_144
    max_depth: int = 8
    max_text_bytes: int = 8_192
    max_paths: int = 128
    max_effects: int = 64
    timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        for name in (
            "max_items",
            "max_serialized_bytes",
            "max_depth",
            "max_text_bytes",
            "max_paths",
            "max_effects",
            "timeout_ms",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if self.max_items > ABSOLUTE_MAX_CONTROL_ITEMS:
            raise ControlBoundsError("max_items exceeds the absolute limit")
        if self.max_serialized_bytes > ABSOLUTE_MAX_CONTROL_BYTES:
            raise ControlBoundsError(
                "max_serialized_bytes exceeds the absolute limit"
            )
        if self.max_depth > ABSOLUTE_MAX_CONTROL_DEPTH:
            raise ControlBoundsError("max_depth exceeds the absolute limit")
        if self.max_text_bytes > ABSOLUTE_MAX_CONTROL_TEXT_BYTES:
            raise ControlBoundsError("max_text_bytes exceeds the absolute limit")
        if self.max_paths > self.max_items or self.max_effects > self.max_items:
            raise ControlBoundsError(
                "path and effect limits cannot exceed max_items"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "max_items": self.max_items,
            "max_serialized_bytes": self.max_serialized_bytes,
            "max_depth": self.max_depth,
            "max_text_bytes": self.max_text_bytes,
            "max_paths": self.max_paths,
            "max_effects": self.max_effects,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ControlBounds":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "max_items",
                "max_serialized_bytes",
                "max_bytes",
                "max_depth",
                "max_text_bytes",
                "max_paths",
                "max_effects",
                "timeout_ms",
                "content_id",
            },
            "control bounds",
        )
        defaults = cls()
        result = cls(
            max_items=payload.get("max_items", defaults.max_items),
            max_serialized_bytes=payload.get(
                "max_serialized_bytes",
                payload.get("max_bytes", defaults.max_serialized_bytes),
            ),
            max_depth=payload.get("max_depth", defaults.max_depth),
            max_text_bytes=payload.get(
                "max_text_bytes", defaults.max_text_bytes
            ),
            max_paths=payload.get("max_paths", defaults.max_paths),
            max_effects=payload.get("max_effects", defaults.max_effects),
            timeout_ms=payload.get("timeout_ms", defaults.timeout_ms),
        )
        _identity(payload, result.content_id, "control bounds")
        return result


@dataclass(frozen=True)
class ExpectedEffect(_ControlCanonicalContract):
    """An explicit effect a caller expects an operation to produce."""

    SCHEMA: ClassVar[str] = EXPECTED_EFFECT_SCHEMA

    effect_id: str
    kind: EffectKind
    resource: str
    paths: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _text(self.effect_id, "effect_id"))
        object.__setattr__(self, "kind", _enum(self.kind, EffectKind, "kind"))
        object.__setattr__(self, "resource", _text(self.resource, "resource"))
        object.__setattr__(self, "paths", _paths(self.paths, "paths"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", required=False),
        )
        _bounded_record(self, "expected effect")

    @property
    def authority(self) -> OperationAuthority:
        return self.kind.authority

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "effect_id": self.effect_id,
            "kind": self.kind,
            "authority": self.authority,
            "resource": self.resource,
            "paths": self.paths,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExpectedEffect":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "effect_id",
                "kind",
                "authority",
                "resource",
                "paths",
                "description",
                "content_id",
            },
            "expected effect",
        )
        result = cls(
            effect_id=payload.get("effect_id", ""),
            kind=payload.get("kind", ""),
            resource=payload.get("resource", ""),
            paths=payload.get("paths", ()),
            description=payload.get("description", ""),
        )
        claimed_authority = payload.get("authority")
        if claimed_authority not in (None, "") and _authority(
            claimed_authority
        ) is not result.authority:
            raise AuthorityViolationError(
                "expected effect authority does not match its kind"
            )
        _identity(payload, result.content_id, "expected effect")
        return result


@dataclass(frozen=True)
class EffectClaim(_ControlCanonicalContract):
    """A bounded claim about an effect observed in an operation result."""

    SCHEMA: ClassVar[str] = EFFECT_CLAIM_SCHEMA

    effect_id: str
    kind: EffectKind
    resource: str
    paths: tuple[str, ...] = ()
    applied: bool = False
    receipt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _text(self.effect_id, "effect_id"))
        object.__setattr__(self, "kind", _enum(self.kind, EffectKind, "kind"))
        object.__setattr__(self, "resource", _text(self.resource, "resource"))
        object.__setattr__(self, "paths", _paths(self.paths, "paths"))
        if not isinstance(self.applied, bool):
            raise ControlContractError("applied must be a boolean")
        if self.applied and self.kind.authority is not OperationAuthority.MUTATION:
            raise AuthorityViolationError(
                "only mutation effects may be claimed as applied"
            )
        object.__setattr__(
            self,
            "receipt_id",
            _text(self.receipt_id, "receipt_id", required=False),
        )
        if self.applied and not self.receipt_id:
            raise ControlContractError(
                "an applied effect claim requires an audit receipt identity"
            )
        _bounded_record(self, "effect claim")

    @property
    def authority(self) -> OperationAuthority:
        return self.kind.authority

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "effect_id": self.effect_id,
            "kind": self.kind,
            "authority": self.authority,
            "resource": self.resource,
            "paths": self.paths,
            "applied": self.applied,
            "receipt_id": self.receipt_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectClaim":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "effect_id",
                "kind",
                "authority",
                "resource",
                "paths",
                "applied",
                "receipt_id",
                "content_id",
            },
            "effect claim",
        )
        result = cls(
            effect_id=payload.get("effect_id", ""),
            kind=payload.get("kind", ""),
            resource=payload.get("resource", ""),
            paths=payload.get("paths", ()),
            applied=payload.get("applied", False),
            receipt_id=payload.get("receipt_id", ""),
        )
        claimed_authority = payload.get("authority")
        if claimed_authority not in (None, "") and _authority(
            claimed_authority
        ) is not result.authority:
            raise AuthorityViolationError(
                "effect claim authority does not match its kind"
            )
        _identity(payload, result.content_id, "effect claim")
        return result


@dataclass(frozen=True)
class IdempotencyKey(_ControlCanonicalContract):
    """A caller-scoped mutation replay key."""

    SCHEMA: ClassVar[str] = IDEMPOTENCY_KEY_SCHEMA

    key: str
    operation: Operation
    caller: str
    repository_id: str
    objective_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _text(self.key, "idempotency key"))
        if len(self.key.encode("utf-8")) > 256:
            raise ControlBoundsError("idempotency key exceeds 256 UTF-8 bytes")
        object.__setattr__(self, "operation", _operation(self.operation))
        for name in ("caller", "repository_id", "objective_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        _bounded_record(self, "idempotency key")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "key": self.key,
            "operation": self.operation,
            "caller": self.caller,
            "repository_id": self.repository_id,
            "objective_id": self.objective_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IdempotencyKey":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "key",
                "operation",
                "caller",
                "repository_id",
                "objective_id",
                "content_id",
            },
            "idempotency key",
        )
        result = cls(
            key=payload.get("key", ""),
            operation=payload.get("operation", ""),
            caller=payload.get("caller", ""),
            repository_id=payload.get("repository_id", ""),
            objective_id=payload.get("objective_id", ""),
        )
        _identity(payload, result.content_id, "idempotency key")
        return result


@dataclass(frozen=True)
class AuthorizationDecision(_ControlCanonicalContract):
    """An exact, policy-produced authorization for one operation binding."""

    SCHEMA: ClassVar[str] = AUTHORIZATION_DECISION_SCHEMA

    verdict: AuthorizationVerdict
    operation: Operation
    granted_authority: OperationAuthority | None
    repository_root: str
    state_root: str
    repository_id: str
    tree_id: str
    objective_id: str
    objective_revision: str
    policy_id: str
    policy_revision: str
    caller: str
    lease_id: str = ""
    fencing_epoch: int | None = None
    authorized_effect_ids: tuple[str, ...] = ()
    reason_code: str = ""
    grant_ids: tuple[str, ...] = ()
    evaluated_at_ms: int = 0
    expires_at_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verdict",
            _enum(self.verdict, AuthorizationVerdict, "verdict"),
        )
        object.__setattr__(self, "operation", _operation(self.operation))
        if self.granted_authority is not None:
            object.__setattr__(
                self,
                "granted_authority",
                _authority(self.granted_authority),
            )
        object.__setattr__(
            self,
            "repository_root",
            _absolute_root(self.repository_root, "repository_root"),
        )
        object.__setattr__(
            self, "state_root", _absolute_root(self.state_root, "state_root")
        )
        for name in (
            "repository_id",
            "tree_id",
            "objective_id",
            "objective_revision",
            "policy_id",
            "policy_revision",
            "caller",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "lease_id", _text(self.lease_id, "lease_id", required=False)
        )
        if self.fencing_epoch is not None:
            object.__setattr__(
                self,
                "fencing_epoch",
                _nonnegative(self.fencing_epoch, "fencing_epoch"),
            )
        object.__setattr__(
            self,
            "authorized_effect_ids",
            _strings(
                self.authorized_effect_ids,
                "authorized_effect_ids",
                required=self.verdict is AuthorizationVerdict.PERMIT
                and self.operation.mutating,
            ),
        )
        object.__setattr__(
            self,
            "reason_code",
            _text(
                self.reason_code,
                "reason_code",
                required=self.verdict is AuthorizationVerdict.DENY,
            ),
        )
        object.__setattr__(
            self, "grant_ids", _strings(self.grant_ids, "grant_ids")
        )
        object.__setattr__(
            self,
            "evaluated_at_ms",
            _nonnegative(self.evaluated_at_ms, "evaluated_at_ms"),
        )
        if self.expires_at_ms is not None:
            object.__setattr__(
                self,
                "expires_at_ms",
                _nonnegative(self.expires_at_ms, "expires_at_ms"),
            )
            if self.expires_at_ms <= self.evaluated_at_ms:
                raise ControlContractError(
                    "expires_at_ms must follow evaluated_at_ms"
                )
        if self.verdict is AuthorizationVerdict.PERMIT:
            if self.granted_authority is None:
                raise AuthorizationBindingError(
                    "permit decisions require granted_authority"
                )
            if not self.operation.authority.allows(self.granted_authority):
                raise AuthorityViolationError(
                    "authorization grants more authority than the operation"
                )
        elif self.granted_authority is not None:
            raise AuthorizationBindingError(
                "deny decisions must not grant authority"
            )
        _bounded_record(self, "authorization decision")

    @property
    def permitted(self) -> bool:
        return self.verdict is AuthorizationVerdict.PERMIT

    @property
    def decision_id(self) -> str:
        return self.content_id

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "verdict": self.verdict,
            "operation": self.operation,
            "granted_authority": self.granted_authority,
            "repository_root": self.repository_root,
            "state_root": self.state_root,
            "repository_id": self.repository_id,
            "tree_id": self.tree_id,
            "objective_id": self.objective_id,
            "objective_revision": self.objective_revision,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "caller": self.caller,
            "lease_id": self.lease_id,
            "fencing_epoch": self.fencing_epoch,
            "authorized_effect_ids": self.authorized_effect_ids,
            "reason_code": self.reason_code,
            "grant_ids": self.grant_ids,
            "evaluated_at_ms": self.evaluated_at_ms,
            "expires_at_ms": self.expires_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AuthorizationDecision":
        _schema(payload, cls.SCHEMA)
        allowed = {
            "schema",
            "schema_version",
            "contract_version",
            "verdict",
            "operation",
            "granted_authority",
            "repository_root",
            "state_root",
            "repository_id",
            "tree_id",
            "objective_id",
            "objective_revision",
            "policy_id",
            "policy_revision",
            "caller",
            "lease_id",
            "fencing_epoch",
            "authorized_effect_ids",
            "reason_code",
            "grant_ids",
            "evaluated_at_ms",
            "expires_at_ms",
            "content_id",
        }
        _reject_unknown(payload, allowed, "authorization decision")
        result = cls(
            verdict=payload.get("verdict", ""),
            operation=payload.get("operation", ""),
            granted_authority=payload.get("granted_authority"),
            repository_root=payload.get("repository_root", ""),
            state_root=payload.get("state_root", ""),
            repository_id=payload.get("repository_id", ""),
            tree_id=payload.get("tree_id", ""),
            objective_id=payload.get("objective_id", ""),
            objective_revision=payload.get("objective_revision", ""),
            policy_id=payload.get("policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            caller=payload.get("caller", ""),
            lease_id=payload.get("lease_id", ""),
            fencing_epoch=payload.get("fencing_epoch"),
            authorized_effect_ids=payload.get("authorized_effect_ids", ()),
            reason_code=payload.get("reason_code", ""),
            grant_ids=payload.get("grant_ids", ()),
            evaluated_at_ms=payload.get("evaluated_at_ms", 0),
            expires_at_ms=payload.get("expires_at_ms"),
        )
        _identity(payload, result.content_id, "authorization decision")
        return result


@dataclass(frozen=True)
class OperationRequest(_ControlCanonicalContract):
    """One fully bound request to the shared supervisor control service."""

    SCHEMA: ClassVar[str] = OPERATION_REQUEST_SCHEMA

    operation: Operation
    repository_root: str
    state_root: str
    repository_id: str
    tree_id: str
    objective_id: str
    objective_revision: str
    policy_id: str
    policy_revision: str
    caller: str
    bounds: ControlBounds = dataclass_field(default_factory=ControlBounds)
    expected_effects: tuple[ExpectedEffect, ...] = ()
    parameters: Mapping[str, Any] = dataclass_field(default_factory=dict)
    dry_run: bool = False
    idempotency: IdempotencyKey | None = None
    authorization: AuthorizationDecision | None = None
    lease_id: str = ""
    fencing_epoch: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _operation(self.operation))
        object.__setattr__(
            self,
            "repository_root",
            _absolute_root(self.repository_root, "repository_root"),
        )
        object.__setattr__(
            self, "state_root", _absolute_root(self.state_root, "state_root")
        )
        for name in (
            "repository_id",
            "tree_id",
            "objective_id",
            "objective_revision",
            "policy_id",
            "policy_revision",
            "caller",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        bounds = self.bounds
        if not isinstance(bounds, ControlBounds):
            if not isinstance(bounds, Mapping):
                raise ControlContractError("bounds must be ControlBounds")
            bounds = ControlBounds.from_dict(bounds)
        object.__setattr__(self, "bounds", bounds)
        effects = _coerce_tuple(
            self.expected_effects,
            ExpectedEffect,
            ExpectedEffect.from_dict,
            "expected_effects",
        )
        if len(effects) > bounds.max_effects:
            raise ControlBoundsError("request exceeds its effect-count bound")
        if sum(len(item.paths) for item in effects) > bounds.max_paths:
            raise ControlBoundsError("request exceeds its path-count bound")
        effect_ids = [item.effect_id for item in effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ControlContractError("expected effect IDs must be unique")
        # A dry-run mutation is allowed to *describe* mutation-shaped expected
        # effects.  Its result remains proposal-only and cannot claim any such
        # effect was applied.
        maximum_authority = (
            OperationAuthority.MUTATION
            if self.operation in DOWNSTREAM_EFFECT_PREVIEW_OPERATIONS
            else self.operation.authority
        )
        for effect in effects:
            if not maximum_authority.allows(effect.authority):
                raise AuthorityViolationError(
                    "expected effect lies outside the request authority"
                )
        if self.operation.mutating and not self.dry_run and not effects:
            raise AuthorityViolationError(
                "mutation requests must declare expected effects"
            )
        if (
            self.operation.mutating
            and not self.dry_run
            and not any(
                effect.authority is OperationAuthority.MUTATION
                for effect in effects
            )
        ):
            raise AuthorityViolationError(
                "mutation requests must declare a mutation effect"
            )
        object.__setattr__(
            self,
            "expected_effects",
            tuple(sorted(effects, key=lambda item: item.effect_id)),
        )
        if not isinstance(self.parameters, Mapping):
            raise ControlContractError("parameters must be a mapping")
        frozen_parameters = _freeze_value(
            self.parameters,
            name="parameters",
            max_depth=bounds.max_depth,
            max_items=bounds.max_items,
            max_text_bytes=bounds.max_text_bytes,
        )
        object.__setattr__(self, "parameters", frozen_parameters)
        _validate_prompt_control_parameters(
            self.operation,
            frozen_parameters,
            repository_root=self.repository_root,
            repository_id=self.repository_id,
            tree_id=self.tree_id,
            objective_id=self.objective_id,
            objective_revision=self.objective_revision,
            policy_id=self.policy_id,
            policy_revision=self.policy_revision,
        )
        if not isinstance(self.dry_run, bool):
            raise ControlContractError("dry_run must be a boolean")
        object.__setattr__(
            self, "lease_id", _text(self.lease_id, "lease_id", required=False)
        )
        if self.fencing_epoch is not None:
            object.__setattr__(
                self,
                "fencing_epoch",
                _nonnegative(self.fencing_epoch, "fencing_epoch"),
            )
        idempotency = self.idempotency
        if idempotency is not None and not isinstance(idempotency, IdempotencyKey):
            if not isinstance(idempotency, Mapping):
                raise ControlContractError(
                    "idempotency must be an IdempotencyKey"
                )
            idempotency = IdempotencyKey.from_dict(idempotency)
        object.__setattr__(self, "idempotency", idempotency)
        authorization = self.authorization
        if authorization is not None and not isinstance(
            authorization, AuthorizationDecision
        ):
            if not isinstance(authorization, Mapping):
                raise ControlContractError(
                    "authorization must be an AuthorizationDecision"
                )
            authorization = AuthorizationDecision.from_dict(authorization)
        object.__setattr__(self, "authorization", authorization)
        if self.operation.mutating and not self.dry_run:
            self._validate_mutation_bindings()
        else:
            if idempotency is not None:
                self._validate_idempotency(idempotency)
            if authorization is not None:
                self._validate_optional_authorization(authorization)
        if len(self.canonical_bytes()) > bounds.max_serialized_bytes:
            raise ControlBoundsError(
                "operation request exceeds its serialized-byte bound"
            )

    @property
    def authority(self) -> OperationAuthority:
        return self.operation.authority

    @property
    def effective_authority(self) -> OperationAuthority:
        if self.dry_run and self.operation.mutating:
            return OperationAuthority.PROPOSAL
        return self.operation.authority

    @property
    def request_id(self) -> str:
        return self.content_id

    @property
    def idempotency_key(self) -> str:
        return self.idempotency.key if self.idempotency else ""

    def _validate_idempotency(self, key: IdempotencyKey) -> None:
        expected = (
            self.operation,
            self.caller,
            self.repository_id,
            self.objective_id,
        )
        actual = (
            key.operation,
            key.caller,
            key.repository_id,
            key.objective_id,
        )
        if actual != expected:
            raise MissingIdempotencyError(
                "idempotency key scope does not match the request"
            )

    def _validate_mutation_bindings(self) -> None:
        if self.idempotency is None:
            raise MissingIdempotencyError(
                "mutation requests require an idempotency key"
            )
        self._validate_idempotency(self.idempotency)
        if not self.lease_id or self.fencing_epoch is None:
            raise AuthorizationBindingError(
                "mutation requests require lease_id and fencing_epoch"
            )
        decision = self.authorization
        if decision is None or not decision.permitted:
            raise AuthorizationBindingError(
                "mutation requests require a permit authorization decision"
            )
        if (
            decision.granted_authority is None
            or not decision.granted_authority.allows(OperationAuthority.MUTATION)
        ):
            raise AuthorizationBindingError(
                "mutation authorization does not grant mutation authority"
            )
        binding_names = (
            "operation",
            "repository_root",
            "state_root",
            "repository_id",
            "tree_id",
            "objective_id",
            "objective_revision",
            "policy_id",
            "policy_revision",
            "caller",
            "lease_id",
            "fencing_epoch",
        )
        if any(
            getattr(decision, name) != getattr(self, name)
            for name in binding_names
        ):
            raise AuthorizationBindingError(
                "authorization decision binding does not match the request"
            )
        expected_ids = {item.effect_id for item in self.expected_effects}
        allowed_ids = set(decision.authorized_effect_ids)
        if allowed_ids != expected_ids:
            raise AuthorizationBindingError(
                "mutation authorization effect scope must exactly match "
                "every expected effect declared by the request"
            )

    def _validate_optional_authorization(
        self, decision: AuthorizationDecision
    ) -> None:
        """Validate a supplied decision even when the operation does not need it."""

        if not decision.permitted or decision.granted_authority is None:
            raise AuthorizationBindingError(
                "a supplied authorization decision must permit the request"
            )
        binding_names = (
            "operation",
            "repository_root",
            "state_root",
            "repository_id",
            "tree_id",
            "objective_id",
            "objective_revision",
            "policy_id",
            "policy_revision",
            "caller",
        )
        if any(
            getattr(decision, name) != getattr(self, name)
            for name in binding_names
        ):
            raise AuthorizationBindingError(
                "authorization decision binding does not match the request"
            )
        if not decision.granted_authority.allows(self.effective_authority):
            raise AuthorizationBindingError(
                "authorization does not grant the request authority"
            )
        if self.lease_id and decision.lease_id != self.lease_id:
            raise AuthorizationBindingError(
                "authorization lease does not match the request"
            )
        if (
            self.fencing_epoch is not None
            and decision.fencing_epoch != self.fencing_epoch
        ):
            raise AuthorizationBindingError(
                "authorization fencing epoch does not match the request"
            )
        expected_ids = {item.effect_id for item in self.expected_effects}
        allowed_ids = set(decision.authorized_effect_ids)
        if (
            expected_ids
            and "*" not in allowed_ids
            and not expected_ids.issubset(allowed_ids)
        ):
            raise AuthorizationBindingError(
                "authorization does not cover every expected effect"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "operation": self.operation,
            "authority": self.authority,
            "effective_authority": self.effective_authority,
            "repository_root": self.repository_root,
            "state_root": self.state_root,
            "repository_id": self.repository_id,
            "tree_id": self.tree_id,
            "objective_id": self.objective_id,
            "objective_revision": self.objective_revision,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "caller": self.caller,
            "bounds": self.bounds.to_record(),
            "expected_effects": tuple(
                item.to_record() for item in self.expected_effects
            ),
            "parameters": self.parameters,
            "dry_run": self.dry_run,
            "idempotency": (
                self.idempotency.to_record() if self.idempotency else None
            ),
            "authorization": (
                self.authorization.to_record() if self.authorization else None
            ),
            "lease_id": self.lease_id,
            "fencing_epoch": self.fencing_epoch,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationRequest":
        _schema(payload, cls.SCHEMA)
        allowed = {
            "schema",
            "schema_version",
            "contract_version",
            "operation",
            "authority",
            "effective_authority",
            "repository_root",
            "state_root",
            "repository_id",
            "tree_id",
            "objective_id",
            "objective_revision",
            "policy_id",
            "policy_revision",
            "caller",
            "bounds",
            "expected_effects",
            "parameters",
            "dry_run",
            "idempotency",
            "idempotency_key",
            "authorization",
            "lease_id",
            "fencing_epoch",
            "content_id",
        }
        _reject_unknown(payload, allowed, "operation request")
        operation = _operation(payload.get("operation", ""))
        raw_idempotency = payload.get("idempotency")
        if raw_idempotency is None and payload.get("idempotency_key"):
            raw_idempotency = IdempotencyKey(
                key=payload["idempotency_key"],
                operation=operation,
                caller=payload.get("caller", ""),
                repository_id=payload.get("repository_id", ""),
                objective_id=payload.get("objective_id", ""),
            )
        result = cls(
            operation=operation,
            repository_root=payload.get("repository_root", ""),
            state_root=payload.get("state_root", ""),
            repository_id=payload.get("repository_id", ""),
            tree_id=payload.get("tree_id", ""),
            objective_id=payload.get("objective_id", ""),
            objective_revision=payload.get("objective_revision", ""),
            policy_id=payload.get("policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            caller=payload.get("caller", ""),
            bounds=payload.get("bounds") or ControlBounds(),
            expected_effects=payload.get("expected_effects", ()),
            parameters=payload.get("parameters") or {},
            dry_run=payload.get("dry_run", False),
            idempotency=raw_idempotency,
            authorization=payload.get("authorization"),
            lease_id=payload.get("lease_id", ""),
            fencing_epoch=payload.get("fencing_epoch"),
        )
        for name, actual in (
            ("authority", result.authority),
            ("effective_authority", result.effective_authority),
        ):
            claimed = payload.get(name)
            if claimed not in (None, "") and _authority(claimed) is not actual:
                raise AuthorityViolationError(
                    f"request {name} does not match its operation"
                )
        _identity(payload, result.content_id, "operation request")
        return result


@dataclass(frozen=True)
class OperationError(_ControlCanonicalContract):
    """Stable machine-readable error returned by every control surface."""

    SCHEMA: ClassVar[str] = OPERATION_ERROR_SCHEMA

    code: ErrorCode
    message: str
    retryable: bool = False
    field: str = ""
    details: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _enum(self.code, ErrorCode, "code"))
        object.__setattr__(
            self, "message", _text(self.message, "message", max_bytes=2_048)
        )
        if not isinstance(self.retryable, bool):
            raise ControlContractError("retryable must be a boolean")
        object.__setattr__(
            self, "field", _text(self.field, "field", required=False)
        )
        if not isinstance(self.details, Mapping):
            raise ControlContractError("error details must be a mapping")
        details = _freeze_value(
            self.details,
            name="error details",
            max_depth=4,
            max_items=64,
            max_text_bytes=2_048,
        )
        if len(canonical_json_bytes(details)) > 16_384:
            raise ControlBoundsError("error details exceed 16384 bytes")
        object.__setattr__(self, "details", details)
        _bounded_record(self, "operation error", maximum=32_768)

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "field": self.field,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationError":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "code",
                "message",
                "retryable",
                "field",
                "details",
                "content_id",
            },
            "operation error",
        )
        result = cls(
            code=payload.get("code", ""),
            message=payload.get("message", ""),
            retryable=payload.get("retryable", False),
            field=payload.get("field", ""),
            details=payload.get("details") or {},
        )
        _identity(payload, result.content_id, "operation error")
        return result


@dataclass(frozen=True)
class DryRunPreview(_ControlCanonicalContract):
    """Non-authoritative preview of the effects of one dry-run request."""

    SCHEMA: ClassVar[str] = DRY_RUN_PREVIEW_SCHEMA

    request_id: str
    operation: Operation
    repository_id: str
    tree_id: str
    objective_id: str
    policy_id: str
    caller: str
    expected_effects: tuple[ExpectedEffect, ...] = ()
    checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    would_change: bool = False

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "repository_id",
            "tree_id",
            "objective_id",
            "policy_id",
            "caller",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "operation", _operation(self.operation))
        effects = _coerce_tuple(
            self.expected_effects,
            ExpectedEffect,
            ExpectedEffect.from_dict,
            "expected_effects",
        )
        if any(
            effect.authority is OperationAuthority.READ for effect in effects
        ):
            raise AuthorityViolationError(
                "a dry-run preview cannot present observations as changes"
            )
        object.__setattr__(
            self,
            "expected_effects",
            tuple(sorted(effects, key=lambda item: item.effect_id)),
        )
        object.__setattr__(self, "checks", _strings(self.checks, "checks"))
        object.__setattr__(
            self, "warnings", _strings(self.warnings, "warnings")
        )
        if not isinstance(self.would_change, bool):
            raise ControlContractError("would_change must be a boolean")
        _bounded_record(self, "dry-run preview")

    @property
    def authority(self) -> OperationAuthority:
        return OperationAuthority.PROPOSAL

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "request_id": self.request_id,
            "operation": self.operation,
            "authority": self.authority,
            "repository_id": self.repository_id,
            "tree_id": self.tree_id,
            "objective_id": self.objective_id,
            "policy_id": self.policy_id,
            "caller": self.caller,
            "expected_effects": tuple(
                item.to_record() for item in self.expected_effects
            ),
            "checks": self.checks,
            "warnings": self.warnings,
            "would_change": self.would_change,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DryRunPreview":
        _schema(payload, cls.SCHEMA)
        allowed = {
            "schema",
            "schema_version",
            "contract_version",
            "request_id",
            "operation",
            "authority",
            "repository_id",
            "tree_id",
            "objective_id",
            "policy_id",
            "caller",
            "expected_effects",
            "checks",
            "warnings",
            "would_change",
            "content_id",
        }
        _reject_unknown(payload, allowed, "dry-run preview")
        result = cls(
            request_id=payload.get("request_id", ""),
            operation=payload.get("operation", ""),
            repository_id=payload.get("repository_id", ""),
            tree_id=payload.get("tree_id", ""),
            objective_id=payload.get("objective_id", ""),
            policy_id=payload.get("policy_id", ""),
            caller=payload.get("caller", ""),
            expected_effects=payload.get("expected_effects", ()),
            checks=payload.get("checks", ()),
            warnings=payload.get("warnings", ()),
            would_change=payload.get("would_change", False),
        )
        claimed = payload.get("authority")
        if claimed not in (None, "") and _authority(
            claimed
        ) is not OperationAuthority.PROPOSAL:
            raise AuthorityViolationError(
                "dry-run previews have proposal authority only"
            )
        _identity(payload, result.content_id, "dry-run preview")
        return result


def _mirror_operation_result_binding(result: Any) -> None:
    """Record an exact request binding. It does not apply the operation."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(getattr(result, "result_id", "") or getattr(result, "request_id", "") or "operation_result")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="operation_result_binding",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
            tree_id=str(getattr(result, "tree_id", "") or ""),
        )
    except Exception:
        pass


@dataclass(frozen=True)
class OperationResult(_ControlCanonicalContract):
    """Bounded result with effect claims constrained by operation authority."""

    SCHEMA: ClassVar[str] = OPERATION_RESULT_SCHEMA

    request_id: str
    operation: Operation
    authority: OperationAuthority
    status: OperationStatus
    repository_id: str
    tree_id: str
    objective_id: str
    policy_id: str
    caller: str
    bounds: ControlBounds = dataclass_field(default_factory=ControlBounds)
    data: Mapping[str, Any] = dataclass_field(default_factory=dict)
    effects: tuple[EffectClaim, ...] = ()
    error: OperationError | None = None
    preview: DryRunPreview | None = None
    idempotency_key: str = ""
    audit_receipt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "operation", _operation(self.operation))
        object.__setattr__(self, "authority", _authority(self.authority))
        if not self.operation.authority.allows(self.authority):
            raise AuthorityViolationError(
                "result authority lies outside the operation authority"
            )
        object.__setattr__(
            self, "status", _enum(self.status, OperationStatus, "status")
        )
        for name in (
            "repository_id",
            "tree_id",
            "objective_id",
            "policy_id",
            "caller",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        bounds = self.bounds
        if not isinstance(bounds, ControlBounds):
            if not isinstance(bounds, Mapping):
                raise ControlContractError("bounds must be ControlBounds")
            bounds = ControlBounds.from_dict(bounds)
        object.__setattr__(self, "bounds", bounds)
        if not isinstance(self.data, Mapping):
            raise ControlContractError("result data must be a mapping")
        object.__setattr__(
            self,
            "data",
            _freeze_value(
                self.data,
                name="result data",
                max_depth=bounds.max_depth,
                max_items=bounds.max_items,
                max_text_bytes=bounds.max_text_bytes,
            ),
        )
        effects = _coerce_tuple(
            self.effects, EffectClaim, EffectClaim.from_dict, "effects"
        )
        if len(effects) > bounds.max_effects:
            raise ControlBoundsError("result exceeds its effect-count bound")
        if sum(len(item.paths) for item in effects) > bounds.max_paths:
            raise ControlBoundsError("result exceeds its path-count bound")
        effect_ids = [item.effect_id for item in effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ControlContractError("result effect IDs must be unique")
        for effect in effects:
            if not self.authority.allows(effect.authority):
                raise AuthorityViolationError(
                    "result effect claim lies outside result authority"
                )
            if effect.applied and self.authority is not OperationAuthority.MUTATION:
                raise AuthorityViolationError(
                    "non-mutation results cannot claim applied effects"
                )
        object.__setattr__(
            self, "effects", tuple(sorted(effects, key=lambda item: item.effect_id))
        )
        error = self.error
        if error is not None and not isinstance(error, OperationError):
            if not isinstance(error, Mapping):
                raise ControlContractError("error must be an OperationError")
            error = OperationError.from_dict(error)
        object.__setattr__(self, "error", error)
        if self.status.successful and error is not None:
            raise ControlContractError("successful results must not contain an error")
        if not self.status.successful and error is None:
            raise ControlContractError("unsuccessful results require a typed error")
        preview = self.preview
        if preview is not None and not isinstance(preview, DryRunPreview):
            if not isinstance(preview, Mapping):
                raise ControlContractError("preview must be a DryRunPreview")
            preview = DryRunPreview.from_dict(preview)
        object.__setattr__(self, "preview", preview)
        if preview is not None:
            if (
                self.authority is not OperationAuthority.PROPOSAL
                or preview.request_id != self.request_id
                or preview.operation is not self.operation
            ):
                raise AuthorityViolationError(
                    "preview does not match the proposal result"
                )
        for name in ("idempotency_key", "audit_receipt_id"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), name, required=False),
            )
        if any(effect.applied for effect in effects) and not self.audit_receipt_id:
            raise ControlContractError(
                "applied mutation results require an audit receipt"
            )
        if any(
            effect.applied and effect.receipt_id != self.audit_receipt_id
            for effect in effects
        ):
            raise ControlContractError(
                "applied effect receipt must match the result audit receipt"
            )
        if len(self.canonical_bytes()) > bounds.max_serialized_bytes:
            raise ControlBoundsError(
                "operation result exceeds its serialized-byte bound"
            )

    @property
    def result_id(self) -> str:
        return self.content_id

    @property
    def succeeded(self) -> bool:
        return self.status.successful

    def validate_against(self, request: OperationRequest) -> None:
        """Fail closed unless this result is an exact projection of ``request``."""

        if not isinstance(request, OperationRequest):
            raise ControlContractError("request must be an OperationRequest")
        comparisons = (
            (self.request_id, request.request_id),
            (self.operation, request.operation),
            (self.repository_id, request.repository_id),
            (self.tree_id, request.tree_id),
            (self.objective_id, request.objective_id),
            (self.policy_id, request.policy_id),
            (self.caller, request.caller),
            (self.authority, request.effective_authority),
            (self.bounds, request.bounds),
        )
        if any(actual != expected for actual, expected in comparisons):
            raise AuthorityViolationError("result binding does not match request")
        expected = {item.effect_id: item for item in request.expected_effects}
        for claim in self.effects:
            declared = expected.get(claim.effect_id)
            if declared is None:
                raise AuthorityViolationError(
                    "result claims an effect not declared by the request"
                )
            if (
                claim.kind is not declared.kind
                or claim.resource != declared.resource
                or claim.paths != declared.paths
            ):
                raise AuthorityViolationError(
                    "result effect claim exceeds its declared shape"
                )
        if request.dry_run and any(item.applied for item in self.effects):
            raise AuthorityViolationError(
                "dry-run results cannot claim applied effects"
            )
        if request.operation.mutating and not request.dry_run:
            if self.idempotency_key != request.idempotency_key:
                raise AuthorityViolationError(
                    "mutation result idempotency key does not match request"
                )
        _mirror_operation_result_binding(self)

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "request_id": self.request_id,
            "operation": self.operation,
            "authority": self.authority,
            "status": self.status,
            "repository_id": self.repository_id,
            "tree_id": self.tree_id,
            "objective_id": self.objective_id,
            "policy_id": self.policy_id,
            "caller": self.caller,
            "bounds": self.bounds.to_record(),
            "data": self.data,
            "effects": tuple(item.to_record() for item in self.effects),
            "error": self.error.to_record() if self.error else None,
            "preview": self.preview.to_record() if self.preview else None,
            "idempotency_key": self.idempotency_key,
            "audit_receipt_id": self.audit_receipt_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationResult":
        _schema(payload, cls.SCHEMA)
        allowed = {
            "schema",
            "schema_version",
            "contract_version",
            "request_id",
            "operation",
            "authority",
            "status",
            "repository_id",
            "tree_id",
            "objective_id",
            "policy_id",
            "caller",
            "bounds",
            "data",
            "effects",
            "error",
            "preview",
            "idempotency_key",
            "audit_receipt_id",
            "content_id",
        }
        _reject_unknown(payload, allowed, "operation result")
        result = cls(
            request_id=payload.get("request_id", ""),
            operation=payload.get("operation", ""),
            authority=payload.get("authority", ""),
            status=payload.get("status", ""),
            repository_id=payload.get("repository_id", ""),
            tree_id=payload.get("tree_id", ""),
            objective_id=payload.get("objective_id", ""),
            policy_id=payload.get("policy_id", ""),
            caller=payload.get("caller", ""),
            bounds=payload.get("bounds") or ControlBounds(),
            data=payload.get("data") or {},
            effects=payload.get("effects", ()),
            error=payload.get("error"),
            preview=payload.get("preview"),
            idempotency_key=payload.get("idempotency_key", ""),
            audit_receipt_id=payload.get("audit_receipt_id", ""),
        )
        _identity(payload, result.content_id, "operation result")
        return result


@dataclass(frozen=True)
class OperationCapability(_ControlCanonicalContract):
    """Advertised support and bounds for one operation."""

    SCHEMA: ClassVar[str] = OPERATION_CAPABILITY_SCHEMA

    operation: Operation
    authority: OperationAuthority
    bounds: ControlBounds = dataclass_field(default_factory=ControlBounds)
    supports_dry_run: bool = False
    requires_idempotency: bool = False
    requires_authorization: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _operation(self.operation))
        object.__setattr__(self, "authority", _authority(self.authority))
        if self.authority is not self.operation.authority:
            raise AuthorityViolationError(
                "capability authority must match the operation registry"
            )
        if not isinstance(self.bounds, ControlBounds):
            if not isinstance(self.bounds, Mapping):
                raise ControlContractError("bounds must be ControlBounds")
            object.__setattr__(
                self, "bounds", ControlBounds.from_dict(self.bounds)
            )
        for name in (
            "supports_dry_run",
            "requires_idempotency",
            "requires_authorization",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ControlContractError(f"{name} must be a boolean")
        if self.operation.mutating:
            if not (
                self.supports_dry_run
                and self.requires_idempotency
                and self.requires_authorization
            ):
                raise ControlContractError(
                    "mutation capabilities must advertise dry-run, "
                    "idempotency, and authorization"
                )
        elif self.requires_idempotency:
            raise ControlContractError(
                "non-mutation capabilities must not require idempotency"
            )
        _bounded_record(self, "operation capability")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "operation": self.operation,
            "authority": self.authority,
            "bounds": self.bounds.to_record(),
            "supports_dry_run": self.supports_dry_run,
            "requires_idempotency": self.requires_idempotency,
            "requires_authorization": self.requires_authorization,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationCapability":
        _schema(payload, cls.SCHEMA)
        allowed = {
            "schema",
            "schema_version",
            "contract_version",
            "operation",
            "authority",
            "bounds",
            "supports_dry_run",
            "requires_idempotency",
            "requires_authorization",
            "content_id",
        }
        _reject_unknown(payload, allowed, "operation capability")
        result = cls(
            operation=payload.get("operation", ""),
            authority=payload.get("authority", ""),
            bounds=payload.get("bounds") or ControlBounds(),
            supports_dry_run=payload.get("supports_dry_run", False),
            requires_idempotency=payload.get("requires_idempotency", False),
            requires_authorization=payload.get(
                "requires_authorization", False
            ),
        )
        _identity(payload, result.content_id, "operation capability")
        return result


@dataclass(frozen=True)
class CapabilityReport(_ControlCanonicalContract):
    """Side-effect-free capability handshake for a control implementation."""

    SCHEMA: ClassVar[str] = CAPABILITY_REPORT_SCHEMA

    service_id: str
    service_version: str
    capabilities: tuple[OperationCapability, ...]
    contract_versions: tuple[int, ...] = (CONTROL_CONTRACT_VERSION,)
    optional_providers_loaded: bool = False
    processes_started: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_id", _text(self.service_id, "service_id"))
        object.__setattr__(
            self,
            "service_version",
            _text(self.service_version, "service_version"),
        )
        capabilities = _coerce_tuple(
            self.capabilities,
            OperationCapability,
            OperationCapability.from_dict,
            "capabilities",
        )
        operations = [item.operation for item in capabilities]
        if len(operations) != len(set(operations)):
            raise ControlContractError(
                "capability report contains duplicate operations"
            )
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted(capabilities, key=lambda item: item.operation.value)),
        )
        versions = tuple(
            sorted(
                {
                    _positive(item, "contract version")
                    for item in self.contract_versions
                }
            )
        )
        if not versions:
            raise ControlContractError("contract_versions must not be empty")
        object.__setattr__(self, "contract_versions", versions)
        for name in ("optional_providers_loaded", "processes_started"):
            if not isinstance(getattr(self, name), bool):
                raise ControlContractError(f"{name} must be a boolean")
        _bounded_record(self, "capability report")

    @property
    def supported_operations(self) -> tuple[Operation, ...]:
        return tuple(item.operation for item in self.capabilities)

    def supports(self, operation: Operation | str) -> bool:
        selected = _operation(operation)
        return selected in self.supported_operations

    def capability_for(
        self, operation: Operation | str
    ) -> OperationCapability | None:
        selected = _operation(operation)
        return next(
            (
                capability
                for capability in self.capabilities
                if capability.operation is selected
            ),
            None,
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "service_id": self.service_id,
            "service_version": self.service_version,
            "capabilities": tuple(
                item.to_record() for item in self.capabilities
            ),
            "contract_versions": self.contract_versions,
            "optional_providers_loaded": self.optional_providers_loaded,
            "processes_started": self.processes_started,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CapabilityReport":
        _schema(payload, cls.SCHEMA)
        allowed = {
            "schema",
            "schema_version",
            "contract_version",
            "service_id",
            "service_version",
            "capabilities",
            "contract_versions",
            "optional_providers_loaded",
            "processes_started",
            "content_id",
        }
        _reject_unknown(payload, allowed, "capability report")
        result = cls(
            service_id=payload.get("service_id", ""),
            service_version=payload.get("service_version", ""),
            capabilities=payload.get("capabilities", ()),
            contract_versions=payload.get(
                "contract_versions", (CONTROL_CONTRACT_VERSION,)
            ),
            optional_providers_loaded=payload.get(
                "optional_providers_loaded", False
            ),
            processes_started=payload.get("processes_started", False),
        )
        _identity(payload, result.content_id, "capability report")
        return result


class ControlTargetKind(str, Enum):
    """Semantic object addressed by a catalog operation."""

    SERVICE = "service"
    REPOSITORY = "repository"
    OBJECTIVE = "objective"
    TASK = "task"
    BUNDLE = "bundle"
    LANE = "lane"
    EVENT_STREAM = "event_stream"
    RECEIPT = "receipt"
    CACHE = "cache"
    ARTIFACT = "artifact"
    VALIDATION = "validation"
    WORKFLOW = "workflow"
    INCIDENT = "incident"


class ControlRoot(str, Enum):
    """Authority-bearing filesystem root an operation may address."""

    REPOSITORY = "repository_root"
    STATE = "state_root"
    ARTIFACT = "artifact_root"


class PaginationKind(str, Enum):
    """Closed pagination behavior declared by an operation."""

    NONE = "none"
    CURSOR = "cursor"
    EVENT_CURSOR = "event_cursor"


class CapabilityDegradation(str, Enum):
    """Fail-closed behavior when an advertised backend capability is absent."""

    FAIL_CLOSED = "fail_closed"
    LOCAL_READ_ONLY = "local_read_only"
    PROPOSAL_ONLY = "proposal_only"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ControlTargetDescriptor(_ControlCanonicalContract):
    """Target identity and roots required before an operation can dispatch."""

    SCHEMA: ClassVar[str] = CONTROL_TARGET_DESCRIPTOR_SCHEMA

    kind: ControlTargetKind
    required_selectors: tuple[str, ...]
    allowed_roots: tuple[ControlRoot, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, ControlTargetKind, "target kind")
        )
        selectors = _strings(
            self.required_selectors,
            "required_selectors",
            required=True,
            maximum=32,
        )
        allowed_selector_names = frozenset(
            {
                "service_id",
                "repository_id",
                "tree_id",
                "objective_id",
                "task_id",
                "bundle_id",
                "lane_id",
                "stream_id",
                "receipt_id",
                "cache_namespace",
                "artifact_id",
                "validation_id",
                "preview_ref",
                "incident_cid",
                "rescue_plan_cid",
            }
        )
        if not set(selectors).issubset(allowed_selector_names):
            raise ControlContractError(
                "target descriptor contains an unknown selector"
            )
        object.__setattr__(self, "required_selectors", selectors)
        try:
            roots = tuple(
                sorted(
                    {
                        item
                        if isinstance(item, ControlRoot)
                        else ControlRoot(str(item))
                        for item in self.allowed_roots
                    },
                    key=lambda item: item.value,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ControlContractError(
                "allowed_roots contains an unknown root"
            ) from exc
        if not roots:
            raise ControlContractError(
                "target descriptor must declare at least one allowed root"
            )
        object.__setattr__(self, "allowed_roots", roots)
        _bounded_record(self, "control target descriptor")

    @property
    def roots(self) -> tuple[str, ...]:
        return tuple(root.value for root in self.allowed_roots)

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": CONTROL_CATALOG_VERSION,
            "kind": self.kind,
            "required_selectors": self.required_selectors,
            "allowed_roots": self.allowed_roots,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlTargetDescriptor":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "kind",
                "required_selectors",
                "allowed_roots",
                "content_id",
            },
            "control target descriptor",
        )
        if payload.get("catalog_version", CONTROL_CATALOG_VERSION) != (
            CONTROL_CATALOG_VERSION
        ):
            raise UnsupportedCatalogVersionError(
                "unsupported target descriptor catalog version"
            )
        result = cls(
            kind=payload.get("kind", ""),
            required_selectors=payload.get("required_selectors", ()),
            allowed_roots=payload.get("allowed_roots", ()),
        )
        _identity(payload, result.content_id, "control target descriptor")
        return result


def _mirror_pagination_limit(pagination: Any, selected: int) -> int:
    """Record a page limit that fits. It does not fetch a page."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        kind = getattr(pagination, "kind", None)
        record_ref = f"{getattr(kind, 'value', kind) or 'pagination'}:{selected}"
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="control_pagination_limit",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return selected


@dataclass(frozen=True)
class ControlPagination(_ControlCanonicalContract):
    """Bounded page/cursor behavior for one operation."""

    SCHEMA: ClassVar[str] = CONTROL_PAGINATION_SCHEMA

    kind: PaginationKind
    default_limit: int
    max_limit: int
    cursor_schema: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, PaginationKind, "pagination kind")
        )
        object.__setattr__(
            self, "default_limit", _positive(self.default_limit, "default_limit")
        )
        object.__setattr__(
            self, "max_limit", _positive(self.max_limit, "max_limit")
        )
        if self.default_limit > self.max_limit:
            raise ControlBoundsError(
                "pagination default_limit cannot exceed max_limit"
            )
        object.__setattr__(
            self,
            "cursor_schema",
            _text(
                self.cursor_schema,
                "cursor_schema",
                required=self.kind is not PaginationKind.NONE,
            ),
        )
        if self.kind is PaginationKind.NONE:
            if self.cursor_schema:
                raise ControlContractError(
                    "non-paginated operations cannot declare a cursor schema"
                )
            if self.default_limit != 1 or self.max_limit != 1:
                raise ControlBoundsError(
                    "non-paginated operations must use a one-item bound"
                )
        elif self.kind is PaginationKind.EVENT_CURSOR:
            if self.cursor_schema != EVENT_CURSOR_SCHEMA:
                raise ControlContractError(
                    "event pagination must use the canonical event cursor"
                )
        _bounded_record(self, "control pagination")

    @property
    def event_cursor(self) -> bool:
        return self.kind is PaginationKind.EVENT_CURSOR

    def validate_limit(self, limit: int | None) -> int:
        selected = self.default_limit if limit is None else _positive(limit, "limit")
        if selected > self.max_limit:
            raise ControlBoundsError(
                f"page limit {selected} exceeds operation maximum {self.max_limit}"
            )
        return _mirror_pagination_limit(self, selected)

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": CONTROL_CATALOG_VERSION,
            "kind": self.kind,
            "default_limit": self.default_limit,
            "max_limit": self.max_limit,
            "cursor_schema": self.cursor_schema,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ControlPagination":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "kind",
                "default_limit",
                "max_limit",
                "cursor_schema",
                "content_id",
            },
            "control pagination",
        )
        if payload.get("catalog_version", CONTROL_CATALOG_VERSION) != (
            CONTROL_CATALOG_VERSION
        ):
            raise UnsupportedCatalogVersionError(
                "unsupported pagination catalog version"
            )
        result = cls(
            kind=payload.get("kind", ""),
            default_limit=payload.get("default_limit", 0),
            max_limit=payload.get("max_limit", 0),
            cursor_schema=payload.get("cursor_schema", ""),
        )
        _identity(payload, result.content_id, "control pagination")
        return result


@dataclass(frozen=True)
class EventCursor(_ControlCanonicalContract):
    """Opaque, content-addressed position in one immutable event stream.

    ``position`` is the last event consumed, so an initial cursor has position
    zero and replay resumes strictly after it.  The stream and snapshot
    bindings prevent a cursor from being reused against a different log or a
    rewritten projection.
    """

    SCHEMA: ClassVar[str] = EVENT_CURSOR_SCHEMA

    stream_id: str
    position: int = 0
    last_event_id: str = ""
    snapshot_id: str = ""
    catalog_version: int = CONTROL_CATALOG_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_id", _text(self.stream_id, "stream_id"))
        object.__setattr__(
            self, "position", _nonnegative(self.position, "position")
        )
        object.__setattr__(
            self,
            "last_event_id",
            _text(self.last_event_id, "last_event_id", required=False),
        )
        object.__setattr__(
            self,
            "snapshot_id",
            _text(self.snapshot_id, "snapshot_id", required=False),
        )
        if self.catalog_version != CONTROL_CATALOG_VERSION:
            raise UnsupportedCatalogVersionError(
                f"unsupported event cursor catalog version "
                f"{self.catalog_version!r}"
            )
        if self.position == 0 and self.last_event_id:
            raise EventCursorError(
                "an initial event cursor cannot name a last event"
            )
        if self.position > 0 and not self.last_event_id:
            raise EventCursorError(
                "a non-initial event cursor must name its last event"
            )
        _bounded_record(self, "event cursor", maximum=16_384)

    @classmethod
    def initial(
        cls, stream_id: str, *, snapshot_id: str = ""
    ) -> "EventCursor":
        return cls(stream_id=stream_id, snapshot_id=snapshot_id)

    @property
    def offset(self) -> int:
        return self.position

    @property
    def sequence(self) -> int:
        return self.position

    def advance(
        self,
        *,
        position: int,
        event_id: str,
        snapshot_id: str | None = None,
    ) -> "EventCursor":
        selected = _nonnegative(position, "position")
        if selected <= self.position:
            raise CursorReplayError(
                "event cursor advancement must be strictly monotonic"
            )
        next_snapshot = self.snapshot_id if snapshot_id is None else snapshot_id
        if self.snapshot_id and next_snapshot != self.snapshot_id:
            raise CursorReplayError(
                "event cursor snapshot binding cannot change during replay"
            )
        return EventCursor(
            stream_id=self.stream_id,
            position=selected,
            last_event_id=event_id,
            snapshot_id=next_snapshot,
            catalog_version=self.catalog_version,
        )

    def assert_replayable(
        self,
        *,
        stream_id: str,
        earliest_position: int,
        latest_position: int,
        snapshot_id: str = "",
    ) -> None:
        if _text(stream_id, "stream_id") != self.stream_id:
            raise CursorReplayError(
                "event cursor belongs to a different stream"
            )
        earliest = _nonnegative(earliest_position, "earliest_position")
        latest = _nonnegative(latest_position, "latest_position")
        if earliest > latest:
            raise EventCursorError(
                "earliest event position cannot exceed latest position"
            )
        # An initial position is replayable even when the first retained event
        # is position one.  Any later cursor older than the retained prefix is
        # expired.
        if self.position and self.position < max(0, earliest - 1):
            raise CursorReplayError(
                "event cursor predates the retained replay window"
            )
        if self.position > latest:
            raise CursorReplayError(
                "event cursor is ahead of the event stream"
            )
        if self.snapshot_id and snapshot_id and self.snapshot_id != snapshot_id:
            raise CursorReplayError(
                "event cursor snapshot does not match the event stream"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": self.catalog_version,
            "stream_id": self.stream_id,
            "position": self.position,
            "last_event_id": self.last_event_id,
            "snapshot_id": self.snapshot_id,
        }

    def to_token(self) -> str:
        """Encode a bounded, transport-neutral cursor with its content ID."""

        encoded = base64.urlsafe_b64encode(
            canonical_control_json_bytes(self.to_record())
        ).rstrip(b"=")
        return encoded.decode("ascii")

    encode = to_token

    @classmethod
    def from_token(cls, token: str) -> "EventCursor":
        if not isinstance(token, str) or not token or len(token) > 32_768:
            raise EventCursorError("event cursor token is malformed")
        try:
            raw = token.encode("ascii")
            padding = b"=" * (-len(raw) % 4)
            decoded = base64.b64decode(
                raw + padding,
                altchars=b"-_",
                validate=True,
            )
            payload = json.loads(decoded)
        except (
            UnicodeEncodeError,
            UnicodeDecodeError,
            binascii.Error,
            json.JSONDecodeError,
            TypeError,
        ) as exc:
            raise EventCursorError("event cursor token is malformed") from exc
        if not isinstance(payload, Mapping):
            raise EventCursorError("event cursor token must contain an object")
        return cls.from_dict(payload)

    decode = from_token

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EventCursor":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "stream_id",
                "position",
                "last_event_id",
                "snapshot_id",
                "content_id",
            },
            "event cursor",
        )
        result = cls(
            stream_id=payload.get("stream_id", ""),
            position=payload.get("position", 0),
            last_event_id=payload.get("last_event_id", ""),
            snapshot_id=payload.get("snapshot_id", ""),
            catalog_version=payload.get(
                "catalog_version", CONTROL_CATALOG_VERSION
            ),
        )
        try:
            _identity(payload, result.content_id, "event cursor")
        except ControlContractError as exc:
            raise EventCursorError(str(exc)) from exc
        return result


@dataclass(frozen=True)
class EventPage(_ControlCanonicalContract):
    """One exact bounded replay page and the cursor after its final event."""

    SCHEMA: ClassVar[str] = EVENT_PAGE_SCHEMA

    events: tuple[Mapping[str, Any], ...]
    next_cursor: EventCursor
    has_more: bool = False

    def __post_init__(self) -> None:
        if len(self.events) > ABSOLUTE_MAX_CONTROL_ITEMS:
            raise ControlBoundsError("event page exceeds its item-count bound")
        frozen_events: list[Mapping[str, Any]] = []
        for event in self.events:
            if not isinstance(event, Mapping):
                raise EventCursorError("event page entries must be objects")
            frozen_events.append(
                _freeze_value(
                    event,
                    name="event",
                    max_depth=ABSOLUTE_MAX_CONTROL_DEPTH,
                    max_items=ABSOLUTE_MAX_CONTROL_ITEMS,
                    max_text_bytes=ABSOLUTE_MAX_CONTROL_TEXT_BYTES,
                    check_paths=False,
                )
            )
        object.__setattr__(self, "events", tuple(frozen_events))
        if not isinstance(self.next_cursor, EventCursor):
            if not isinstance(self.next_cursor, Mapping):
                raise EventCursorError(
                    "next_cursor must be an EventCursor"
                )
            object.__setattr__(
                self, "next_cursor", EventCursor.from_dict(self.next_cursor)
            )
        if not isinstance(self.has_more, bool):
            raise EventCursorError("has_more must be a boolean")
        _bounded_record(self, "event page")

    @property
    def cursor(self) -> EventCursor:
        return self.next_cursor

    @property
    def items(self) -> tuple[Mapping[str, Any], ...]:
        return self.events

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": CONTROL_CATALOG_VERSION,
            "events": self.events,
            "next_cursor": self.next_cursor.to_record(),
            "has_more": self.has_more,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EventPage":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "events",
                "next_cursor",
                "has_more",
                "content_id",
            },
            "event page",
        )
        if payload.get("catalog_version", CONTROL_CATALOG_VERSION) != (
            CONTROL_CATALOG_VERSION
        ):
            raise UnsupportedCatalogVersionError(
                "unsupported event page catalog version"
            )
        result = cls(
            events=payload.get("events", ()),
            next_cursor=payload.get("next_cursor", {}),
            has_more=payload.get("has_more", False),
        )
        _identity(payload, result.content_id, "event page")
        return result


def _mirror_control_bounds(descriptor: Any, requested: Any) -> Any:
    """Record bounds that fit the catalog. It does not run the operation."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        operation = getattr(descriptor, "operation", None)
        record_ref = str(getattr(operation, "value", operation) or "control_bounds")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="control_operation_bounds",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return requested


@dataclass(frozen=True)
class ControlOperationDescriptor(_ControlCanonicalContract):
    """Complete, immutable policy declaration for one control operation."""

    SCHEMA: ClassVar[str] = CONTROL_OPERATION_DESCRIPTOR_SCHEMA

    operation: Operation
    request_schema: Mapping[str, Any]
    result_schema: Mapping[str, Any]
    authority: OperationAuthority
    target_descriptor: ControlTargetDescriptor
    bounds: ControlBounds
    pagination: ControlPagination
    supports_dry_run: bool
    requires_idempotency: bool
    requires_authorization: bool
    requires_lease: bool
    requires_fencing: bool
    backend_capability: str
    degradation: CapabilityDegradation
    audit_receipt_schema: str
    family: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _operation(self.operation))
        object.__setattr__(self, "authority", _authority(self.authority))
        if self.authority is not self.operation.authority:
            raise AuthorityViolationError(
                "catalog authority must match the closed operation registry"
            )
        for name, kind, decoder in (
            (
                "target_descriptor",
                ControlTargetDescriptor,
                ControlTargetDescriptor.from_dict,
            ),
            ("bounds", ControlBounds, ControlBounds.from_dict),
            ("pagination", ControlPagination, ControlPagination.from_dict),
        ):
            current = getattr(self, name)
            if not isinstance(current, kind):
                if not isinstance(current, Mapping):
                    raise ControlContractError(
                        f"{name} must be a {kind.__name__}"
                    )
                object.__setattr__(self, name, decoder(current))
        if self.pagination.max_limit > self.bounds.max_items:
            raise ControlBoundsError(
                "pagination maximum exceeds operation max_items"
            )
        for name in ("request_schema", "result_schema"):
            schema = getattr(self, name)
            if not isinstance(schema, Mapping):
                raise ControlContractError(f"{name} must be an object")
            expected_operation = (
                schema.get("properties", {})
                .get("operation", {})
                .get("const")
            )
            if expected_operation != self.operation.value:
                raise ControlContractError(
                    f"{name} is not bound to operation {self.operation.value}"
                )
            object.__setattr__(
                self,
                name,
                _freeze_value(
                    schema,
                    name=name,
                    max_depth=ABSOLUTE_MAX_CONTROL_DEPTH,
                    max_items=ABSOLUTE_MAX_CONTROL_ITEMS,
                    max_text_bytes=ABSOLUTE_MAX_CONTROL_TEXT_BYTES,
                    check_paths=False,
                ),
            )
        for name in (
            "supports_dry_run",
            "requires_idempotency",
            "requires_authorization",
            "requires_lease",
            "requires_fencing",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ControlContractError(f"{name} must be a boolean")
        guarded = (
            self.requires_idempotency,
            self.requires_authorization,
            self.requires_lease,
            self.requires_fencing,
        )
        if self.operation.mutating:
            if not self.supports_dry_run or not all(guarded):
                raise ControlContractError(
                    "catalog mutations must require dry-run support, "
                    "idempotency, authorization, lease, and fencing"
                )
        elif any(guarded):
            raise ControlContractError(
                "non-mutation catalog operations cannot require mutation guards"
            )
        object.__setattr__(
            self,
            "backend_capability",
            _text(self.backend_capability, "backend_capability"),
        )
        object.__setattr__(
            self,
            "degradation",
            _enum(self.degradation, CapabilityDegradation, "degradation"),
        )
        object.__setattr__(
            self,
            "audit_receipt_schema",
            _text(self.audit_receipt_schema, "audit_receipt_schema"),
        )
        object.__setattr__(self, "family", _text(self.family, "family"))
        _bounded_record(self, "control operation descriptor")

    @property
    def target(self) -> ControlTargetDescriptor:
        return self.target_descriptor

    @property
    def roots(self) -> tuple[str, ...]:
        return self.target_descriptor.roots

    @property
    def dry_run(self) -> bool:
        return self.supports_dry_run

    @property
    def idempotency(self) -> bool:
        return self.requires_idempotency

    @property
    def leases(self) -> bool:
        return self.requires_lease

    @property
    def fencing(self) -> bool:
        return self.requires_fencing

    @property
    def audit_receipt(self) -> str:
        return self.audit_receipt_schema

    @property
    def request_schema_id(self) -> str:
        return content_identity(self.request_schema)

    @property
    def result_schema_id(self) -> str:
        return content_identity(self.result_schema)

    @property
    def pagination_kind(self) -> PaginationKind:
        return self.pagination.kind

    @property
    def degradation_policy(self) -> CapabilityDegradation:
        return self.degradation

    @property
    def uses_event_cursor(self) -> bool:
        return self.pagination.event_cursor

    def validate_bounds(
        self,
        requested: ControlBounds | Mapping[str, Any],
        *,
        page_limit: int | None = None,
    ) -> ControlBounds:
        if not isinstance(requested, ControlBounds):
            if not isinstance(requested, Mapping):
                raise ControlBoundsError(
                    "requested bounds must be a ControlBounds object"
                )
            try:
                requested = ControlBounds(**dict(requested))
            except (TypeError, ControlContractError) as exc:
                raise ControlBoundsError("requested bounds are invalid") from exc
        for field_name in (
            "max_items",
            "max_serialized_bytes",
            "max_depth",
            "max_text_bytes",
            "max_paths",
            "max_effects",
            "timeout_ms",
        ):
            if getattr(requested, field_name) > getattr(self.bounds, field_name):
                raise ControlBoundsError(
                    f"{field_name} exceeds the catalog bound for "
                    f"{self.operation.value}"
                )
        self.pagination.validate_limit(page_limit)
        return _mirror_control_bounds(self, requested)

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": CONTROL_CATALOG_VERSION,
            "operation": self.operation,
            "request_schema": self.request_schema,
            "result_schema": self.result_schema,
            "authority": self.authority,
            "target_descriptor": self.target_descriptor.to_record(),
            "allowed_roots": self.roots,
            "bounds": self.bounds.to_record(),
            "pagination": self.pagination.to_record(),
            "supports_dry_run": self.supports_dry_run,
            "requires_idempotency": self.requires_idempotency,
            "requires_authorization": self.requires_authorization,
            "requires_lease": self.requires_lease,
            "requires_fencing": self.requires_fencing,
            "backend_capability": self.backend_capability,
            "degradation": self.degradation,
            "audit_receipt_schema": self.audit_receipt_schema,
            "family": self.family,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlOperationDescriptor":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "operation",
                "request_schema",
                "result_schema",
                "authority",
                "target_descriptor",
                "allowed_roots",
                "bounds",
                "pagination",
                "supports_dry_run",
                "requires_idempotency",
                "requires_authorization",
                "requires_lease",
                "requires_fencing",
                "backend_capability",
                "degradation",
                "audit_receipt_schema",
                "family",
                "content_id",
            },
            "control operation descriptor",
        )
        if payload.get("catalog_version", CONTROL_CATALOG_VERSION) != (
            CONTROL_CATALOG_VERSION
        ):
            raise UnsupportedCatalogVersionError(
                "unsupported operation descriptor catalog version"
            )
        result = cls(
            operation=payload.get("operation", ""),
            request_schema=payload.get("request_schema", {}),
            result_schema=payload.get("result_schema", {}),
            authority=payload.get("authority", ""),
            target_descriptor=payload.get("target_descriptor", {}),
            bounds=payload.get("bounds", {}),
            pagination=payload.get("pagination", {}),
            supports_dry_run=payload.get("supports_dry_run", False),
            requires_idempotency=payload.get(
                "requires_idempotency", False
            ),
            requires_authorization=payload.get(
                "requires_authorization", False
            ),
            requires_lease=payload.get("requires_lease", False),
            requires_fencing=payload.get("requires_fencing", False),
            backend_capability=payload.get("backend_capability", ""),
            degradation=payload.get("degradation", ""),
            audit_receipt_schema=payload.get("audit_receipt_schema", ""),
            family=payload.get("family", ""),
        )
        claimed_roots = payload.get("allowed_roots")
        if claimed_roots not in (None, ()) and tuple(claimed_roots) != result.roots:
            raise ControlContractError(
                "operation allowed_roots do not match its target descriptor"
            )
        _identity(payload, result.content_id, "control operation descriptor")
        return result


@dataclass(frozen=True)
class CatalogNegotiation(_ControlCanonicalContract):
    """Deterministic highest-mutual-version negotiation receipt."""

    SCHEMA: ClassVar[str] = CONTROL_CATALOG_NEGOTIATION_SCHEMA

    selected_version: int
    client_versions: tuple[int, ...]
    service_versions: tuple[int, ...]
    catalog_id: str

    def __post_init__(self) -> None:
        for name in ("client_versions", "service_versions"):
            raw = getattr(self, name)
            if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
                raise CatalogVersionNegotiationError(
                    f"{name} must be a sequence of versions"
                )
            versions = tuple(
                sorted({_positive(item, "catalog version") for item in raw})
            )
            if not versions:
                raise CatalogVersionNegotiationError(
                    f"{name} must not be empty"
                )
            object.__setattr__(self, name, versions)
        selected = _positive(self.selected_version, "selected_version")
        mutual = set(self.client_versions).intersection(self.service_versions)
        if not mutual or selected != max(mutual):
            raise CatalogVersionNegotiationError(
                "selected catalog version is not the highest mutual version"
            )
        object.__setattr__(self, "selected_version", selected)
        object.__setattr__(self, "catalog_id", _text(self.catalog_id, "catalog_id"))
        _bounded_record(self, "catalog negotiation")

    @property
    def version(self) -> int:
        return self.selected_version

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "selected_version": self.selected_version,
            "client_versions": self.client_versions,
            "service_versions": self.service_versions,
            "catalog_id": self.catalog_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CatalogNegotiation":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "selected_version",
                "client_versions",
                "service_versions",
                "catalog_id",
                "content_id",
            },
            "catalog negotiation",
        )
        result = cls(
            selected_version=payload.get("selected_version", 0),
            client_versions=payload.get("client_versions", ()),
            service_versions=payload.get("service_versions", ()),
            catalog_id=payload.get("catalog_id", ""),
        )
        _identity(payload, result.content_id, "catalog negotiation")
        return result


@dataclass(frozen=True)
class CapabilityResolution(_ControlCanonicalContract):
    """Result of resolving one operation against runtime backend support."""

    SCHEMA: ClassVar[str] = CONTROL_CAPABILITY_RESOLUTION_SCHEMA

    operation: Operation
    backend_capability: str
    supported: bool
    degraded: bool
    degradation: CapabilityDegradation

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _operation(self.operation))
        object.__setattr__(
            self,
            "backend_capability",
            _text(self.backend_capability, "backend_capability"),
        )
        if not isinstance(self.supported, bool) or not isinstance(
            self.degraded, bool
        ):
            raise ControlContractError(
                "capability supported and degraded flags must be booleans"
            )
        object.__setattr__(
            self,
            "degradation",
            _enum(self.degradation, CapabilityDegradation, "degradation"),
        )
        if self.supported and self.degraded:
            raise ControlContractError(
                "a supported capability cannot also be degraded"
            )
        if not self.supported and not self.degraded:
            raise UnsupportedCapabilityError(
                "unsupported capability must fail or declare degradation"
            )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": CONTROL_CATALOG_VERSION,
            "operation": self.operation,
            "backend_capability": self.backend_capability,
            "supported": self.supported,
            "degraded": self.degraded,
            "degradation": self.degradation,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CapabilityResolution":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "operation",
                "backend_capability",
                "supported",
                "degraded",
                "degradation",
                "content_id",
            },
            "capability resolution",
        )
        result = cls(
            operation=payload.get("operation", ""),
            backend_capability=payload.get("backend_capability", ""),
            supported=payload.get("supported", False),
            degraded=payload.get("degraded", False),
            degradation=payload.get("degradation", ""),
        )
        _identity(payload, result.content_id, "capability resolution")
        return result


def _mirror_backend_capability(resolution: CapabilityResolution) -> CapabilityResolution:
    """Record a present backend capability. The check does not run the operation."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        operation = getattr(getattr(resolution, "operation", None), "value", "")
        capability = str(getattr(resolution, "backend_capability", "") or "")
        record_ref = str(capability or operation or "backend-capability")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="control_backend_capability",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return resolution


@dataclass(frozen=True)
class OperationCatalog(_ControlCanonicalContract):
    """The complete, closed generation-2 supervisor control catalog."""

    SCHEMA: ClassVar[str] = CONTROL_OPERATION_CATALOG_SCHEMA

    operation_descriptors: tuple[ControlOperationDescriptor, ...]
    catalog_version: int = CONTROL_CATALOG_VERSION
    supported_versions: tuple[int, ...] = (CONTROL_CATALOG_VERSION,)
    requirement_id: str = OPERATION_CATALOG_V2_REQUIREMENT_ID

    def __post_init__(self) -> None:
        if self.catalog_version != CONTROL_CATALOG_VERSION:
            raise UnsupportedCatalogVersionError(
                f"unsupported control catalog version {self.catalog_version!r}"
            )
        versions = tuple(
            sorted(
                {
                    _positive(item, "supported catalog version")
                    for item in self.supported_versions
                }
            )
        )
        if self.catalog_version not in versions:
            raise CatalogVersionNegotiationError(
                "catalog version must be in supported_versions"
            )
        object.__setattr__(self, "supported_versions", versions)
        descriptors = _coerce_tuple(
            self.operation_descriptors,
            ControlOperationDescriptor,
            ControlOperationDescriptor.from_dict,
            "operation_descriptors",
        )
        operations = tuple(item.operation for item in descriptors)
        if len(operations) != len(set(operations)):
            raise ControlContractError(
                "operation catalog contains duplicate operations"
            )
        expected = frozenset(Operation)
        actual = frozenset(operations)
        if actual != expected:
            missing = sorted(item.value for item in expected.difference(actual))
            extra = sorted(item.value for item in actual.difference(expected))
            raise ControlContractError(
                "operation catalog must exactly cover the closed operation "
                f"vocabulary; missing={missing}, extra={extra}"
            )
        object.__setattr__(
            self,
            "operation_descriptors",
            tuple(sorted(descriptors, key=lambda item: item.operation.value)),
        )
        if self.requirement_id != OPERATION_CATALOG_V2_REQUIREMENT_ID:
            raise ControlContractError(
                "operation catalog requirement identity does not match ASI-G270"
            )
        _bounded_record(self, "operation catalog")

    @property
    def operations(self) -> tuple[Operation, ...]:
        return tuple(item.operation for item in self.operation_descriptors)

    @property
    def descriptors(self) -> tuple[ControlOperationDescriptor, ...]:
        return self.operation_descriptors

    @property
    def capabilities(self) -> tuple[ControlOperationDescriptor, ...]:
        return self.operation_descriptors

    @property
    def operation_names(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.operations)

    @property
    def version(self) -> int:
        return self.catalog_version

    @property
    def by_name(self) -> Mapping[str, ControlOperationDescriptor]:
        return MappingProxyType(
            {
                item.operation.value: item
                for item in self.operation_descriptors
            }
        )

    @property
    def catalog_id(self) -> str:
        return self.content_id

    def __iter__(self):
        return iter(self.operation_descriptors)

    def __len__(self) -> int:
        return len(self.operation_descriptors)

    def operation(
        self, operation: Operation | str
    ) -> ControlOperationDescriptor:
        selected = _operation(operation)
        for descriptor in self.operation_descriptors:
            if descriptor.operation is selected:
                return descriptor
        # The exact-population invariant makes this defensive branch
        # unreachable for a valid enum member.
        raise UnknownOperationError(f"unknown operation {selected.value!r}")

    get = operation
    descriptor_for = operation

    def negotiate(self, client_versions: Iterable[int]) -> CatalogNegotiation:
        try:
            client = tuple(
                sorted(
                    {
                        _positive(item, "client catalog version")
                        for item in client_versions
                    }
                )
            )
        except TypeError as exc:
            raise CatalogVersionNegotiationError(
                "client_versions must be iterable"
            ) from exc
        if not client:
            raise CatalogVersionNegotiationError(
                "client_versions must not be empty"
            )
        mutual = set(client).intersection(self.supported_versions)
        if not mutual:
            raise UnsupportedCatalogVersionError(
                "no mutually supported control catalog version"
            )
        return CatalogNegotiation(
            selected_version=max(mutual),
            client_versions=client,
            service_versions=self.supported_versions,
            catalog_id=self.catalog_id,
        )

    def negotiate_version(self, client_versions: Iterable[int]) -> int:
        return self.negotiate(client_versions).selected_version

    def require_backend_capability(
        self,
        operation: Operation | str,
        available_capabilities: Iterable[str],
    ) -> CapabilityResolution:
        descriptor = self.operation(operation)
        try:
            available = frozenset(
                _strings(
                    available_capabilities,
                    "available capabilities",
                )
            )
        except TypeError as exc:
            raise UnsupportedCapabilityError(
                "available_capabilities must be iterable"
            ) from exc
        if descriptor.backend_capability not in available:
            raise UnsupportedCapabilityError(
                f"operation {descriptor.operation.value} requires backend "
                f"capability {descriptor.backend_capability!r}"
            )
        return _mirror_backend_capability(CapabilityResolution(
            operation=descriptor.operation,
            backend_capability=descriptor.backend_capability,
            supported=True,
            degraded=False,
            degradation=descriptor.degradation,
        ))

    require_capability = require_backend_capability

    def resolve_backend_capability(
        self,
        operation: Operation | str,
        available_capabilities: Iterable[str],
    ) -> CapabilityResolution:
        descriptor = self.operation(operation)
        try:
            return self.require_backend_capability(
                descriptor.operation, available_capabilities
            )
        except UnsupportedCapabilityError:
            if descriptor.degradation in {
                CapabilityDegradation.LOCAL_READ_ONLY,
                CapabilityDegradation.PROPOSAL_ONLY,
            }:
                return CapabilityResolution(
                    operation=descriptor.operation,
                    backend_capability=descriptor.backend_capability,
                    supported=False,
                    degraded=True,
                    degradation=descriptor.degradation,
                )
            raise

    resolve_capability = resolve_backend_capability

    def validate_bounds(
        self,
        operation: Operation | str,
        requested: ControlBounds | Mapping[str, Any],
        *,
        page_limit: int | None = None,
    ) -> ControlBounds:
        return self.operation(operation).validate_bounds(
            requested, page_limit=page_limit
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "catalog_version": self.catalog_version,
            "supported_versions": self.supported_versions,
            "requirement_id": self.requirement_id,
            "operation_descriptors": tuple(
                item.to_record() for item in self.operation_descriptors
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationCatalog":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "catalog_version",
                "supported_versions",
                "requirement_id",
                "operation_descriptors",
                "operations",
                "content_id",
            },
            "operation catalog",
        )
        descriptors = payload.get(
            "operation_descriptors", payload.get("operations", ())
        )
        result = cls(
            operation_descriptors=descriptors,
            catalog_version=payload.get(
                "catalog_version", CONTROL_CATALOG_VERSION
            ),
            supported_versions=payload.get(
                "supported_versions", (CONTROL_CATALOG_VERSION,)
            ),
            requirement_id=payload.get(
                "requirement_id", OPERATION_CATALOG_V2_REQUIREMENT_ID
            ),
        )
        _identity(payload, result.content_id, "operation catalog")
        return result


def replay_event_page(
    events: Sequence[Mapping[str, Any]],
    cursor: EventCursor | str,
    *,
    limit: int = 50,
    stream_id: str | None = None,
    snapshot_id: str = "",
) -> EventPage:
    """Replay one strictly ordered event page after ``cursor``.

    Events must carry a positive integer ``sequence`` (or ``position``) and
    may carry ``event_id``/``content_id``.  Duplicate or gapped sequences fail
    closed so replay cannot silently skip or apply an event twice.
    """

    selected_cursor = (
        EventCursor.from_token(cursor) if isinstance(cursor, str) else cursor
    )
    if not isinstance(selected_cursor, EventCursor):
        raise EventCursorError("cursor must be an EventCursor or token")
    selected_limit = _positive(limit, "limit")
    if selected_limit > ABSOLUTE_MAX_CONTROL_ITEMS:
        raise ControlBoundsError("event replay limit exceeds the absolute bound")
    selected_stream = (
        selected_cursor.stream_id
        if stream_id is None
        else _text(stream_id, "stream_id")
    )
    normalized: list[tuple[int, str, Mapping[str, Any]]] = []
    previous = 0
    for raw_event in events:
        if not isinstance(raw_event, Mapping):
            raise EventCursorError("event replay entries must be objects")
        position = raw_event.get("sequence", raw_event.get("position"))
        position = _positive(position, "event sequence")
        if position <= previous:
            raise CursorReplayError(
                "event replay population must be strictly ordered and unique"
            )
        previous = position
        event_id = raw_event.get("event_id", raw_event.get("content_id", ""))
        if not event_id:
            event_id = content_identity(raw_event)
        event_id = _text(event_id, "event_id")
        normalized.append((position, event_id, raw_event))
    if normalized:
        selected_cursor.assert_replayable(
            stream_id=selected_stream,
            earliest_position=normalized[0][0],
            latest_position=normalized[-1][0],
            snapshot_id=snapshot_id,
        )
    elif selected_stream != selected_cursor.stream_id:
        raise CursorReplayError("event cursor belongs to a different stream")
    if selected_cursor.position:
        anchor = next(
            (
                item
                for item in normalized
                if item[0] == selected_cursor.position
            ),
            None,
        )
        if anchor is not None and anchor[1] != selected_cursor.last_event_id:
            raise CursorReplayError(
                "event cursor anchor does not match the replay population"
            )
    pending = [item for item in normalized if item[0] > selected_cursor.position]
    if pending and pending[0][0] != selected_cursor.position + 1:
        raise CursorReplayError(
            "event replay contains a gap after the supplied cursor"
        )
    if any(
        current[0] != previous[0] + 1
        for previous, current in zip(pending, pending[1:])
    ):
        raise CursorReplayError(
            "event replay contains a gap in the pending population"
        )
    page_population = pending[:selected_limit]
    next_cursor = selected_cursor
    if page_population:
        final_position, final_event_id, _event = page_population[-1]
        next_cursor = selected_cursor.advance(
            position=final_position,
            event_id=final_event_id,
            snapshot_id=snapshot_id or None,
        )
    return EventPage(
        events=tuple(item[2] for item in page_population),
        next_cursor=next_cursor,
        has_more=len(pending) > len(page_population),
    )


def _catalog_target(operation: Operation) -> ControlTargetDescriptor:
    base_roots: tuple[ControlRoot, ...] = (
        ControlRoot.REPOSITORY,
        ControlRoot.STATE,
    )
    mapping: dict[Operation, tuple[ControlTargetKind, tuple[str, ...]]] = {
        Operation.CAPABILITIES: (
            ControlTargetKind.SERVICE,
            ("service_id",),
        ),
        Operation.STATUS: (
            ControlTargetKind.SERVICE,
            ("repository_id",),
        ),
        Operation.HEALTH: (
            ControlTargetKind.SERVICE,
            ("repository_id",),
        ),
        Operation.METRICS: (
            ControlTargetKind.SERVICE,
            ("repository_id",),
        ),
        Operation.GOALS: (
            ControlTargetKind.OBJECTIVE,
            ("repository_id", "objective_id"),
        ),
        Operation.TASKS: (
            ControlTargetKind.TASK,
            ("repository_id", "objective_id"),
        ),
        Operation.BUNDLES: (
            ControlTargetKind.BUNDLE,
            ("repository_id",),
        ),
        Operation.LANES: (
            ControlTargetKind.LANE,
            ("repository_id",),
        ),
        Operation.EVENTS: (
            ControlTargetKind.EVENT_STREAM,
            ("repository_id", "stream_id"),
        ),
        Operation.RECEIPTS: (
            ControlTargetKind.RECEIPT,
            ("repository_id",),
        ),
        Operation.CACHE_INSPECT: (
            ControlTargetKind.CACHE,
            ("repository_id", "cache_namespace"),
        ),
        Operation.ARTIFACT_QUERY: (
            ControlTargetKind.ARTIFACT,
            ("repository_id",),
        ),
        Operation.OBJECTIVE_PREVIEW: (
            ControlTargetKind.OBJECTIVE,
            ("repository_id", "objective_id"),
        ),
        Operation.PLAN_CREATE_PREVIEW: (
            ControlTargetKind.WORKFLOW,
            ("repository_id", "tree_id"),
        ),
        Operation.PLAN_CREATE_APPLY: (
            ControlTargetKind.WORKFLOW,
            ("repository_id", "tree_id"),
        ),
        Operation.PLAN_STEER_PREVIEW: (
            ControlTargetKind.WORKFLOW,
            ("repository_id", "tree_id"),
        ),
        Operation.PLAN_STEER_APPLY: (
            ControlTargetKind.WORKFLOW,
            ("repository_id", "tree_id"),
        ),
        Operation.WORKFLOW_PREVIEW: (
            ControlTargetKind.WORKFLOW,
            ("repository_id", "tree_id"),
        ),
        Operation.WORKFLOW_MATERIALIZE: (
            ControlTargetKind.WORKFLOW,
            ("repository_id", "tree_id", "preview_ref"),
        ),
        Operation.RESTART: (
            ControlTargetKind.SERVICE,
            ("repository_id",),
        ),
        Operation.RESCUE_PREVIEW: (
            ControlTargetKind.INCIDENT,
            ("repository_id", "tree_id", "incident_cid"),
        ),
        Operation.RESCUE: (
            ControlTargetKind.INCIDENT,
            ("repository_id", "tree_id", "incident_cid"),
        ),
        Operation.OBJECTIVE_REFINE: (
            ControlTargetKind.OBJECTIVE,
            ("repository_id", "objective_id"),
        ),
        Operation.OBJECTIVE_RECONCILE: (
            ControlTargetKind.OBJECTIVE,
            ("repository_id", "objective_id"),
        ),
        Operation.BACKLOG_REFILL: (
            ControlTargetKind.OBJECTIVE,
            ("repository_id", "objective_id"),
        ),
        Operation.PLAN: (
            ControlTargetKind.OBJECTIVE,
            ("repository_id", "objective_id"),
        ),
        Operation.RETRY: (
            ControlTargetKind.TASK,
            ("repository_id", "task_id"),
        ),
        Operation.CANCEL: (
            ControlTargetKind.TASK,
            ("repository_id", "task_id"),
        ),
        Operation.QUARANTINE: (
            ControlTargetKind.TASK,
            ("repository_id", "task_id"),
        ),
        Operation.VALIDATION_REPLAY: (
            ControlTargetKind.VALIDATION,
            ("repository_id", "validation_id"),
        ),
    }
    lifecycle = {
        Operation.START,
        Operation.PAUSE,
        Operation.RESUME,
        Operation.DRAIN,
        Operation.STOP,
    }
    kind, selectors = mapping.get(
        operation,
        (
            ControlTargetKind.SERVICE,
            ("repository_id",)
            if operation in lifecycle
            else ("repository_id", "tree_id"),
        ),
    )
    roots = (
        (*base_roots, ControlRoot.ARTIFACT)
        if operation
        in {Operation.ARTIFACT_QUERY, Operation.VALIDATION_REPLAY}
        else base_roots
    )
    return ControlTargetDescriptor(
        kind=kind,
        required_selectors=selectors,
        allowed_roots=roots,
    )


def _catalog_family(operation: Operation) -> str:
    families: dict[Operation, str] = {
        Operation.CAPABILITIES: "capabilities",
        Operation.HEALTH: "health",
        Operation.STATUS: "status",
        Operation.METRICS: "metrics",
        Operation.GOALS: "goals",
        Operation.TASKS: "tasks",
        Operation.BUNDLES: "bundles",
        Operation.LANES: "lanes",
        Operation.EVENTS: "events",
        Operation.RECEIPTS: "receipts",
        Operation.CACHE_INSPECT: "caches",
        Operation.OBJECTIVE_PREVIEW: "objective",
        Operation.OBJECTIVE_REFINE: "objective",
        Operation.OBJECTIVE_RECONCILE: "objective",
        Operation.BACKLOG_REFILL: "refill",
        Operation.PLAN: "plan",
        Operation.PLAN_CREATE_PREVIEW: "plan",
        Operation.PLAN_CREATE_APPLY: "plan",
        Operation.PLAN_STEER_PREVIEW: "plan",
        Operation.PLAN_STEER_APPLY: "plan",
        Operation.WORKFLOW_PREVIEW: "plan",
        Operation.WORKFLOW_MATERIALIZE: "plan",
        Operation.RESCUE_PREVIEW: "retry",
        Operation.RESCUE: "retry",
        Operation.RETRY: "retry",
        Operation.CANCEL: "cancel",
        Operation.QUARANTINE: "quarantine",
        Operation.ARTIFACT_QUERY: "artifact_query",
        Operation.VALIDATION_REPLAY: "validation_replay",
        Operation.RESTART: "lifecycle",
    }
    if operation in {
        Operation.START,
        Operation.PAUSE,
        Operation.RESUME,
        Operation.DRAIN,
        Operation.STOP,
    }:
        return "lifecycle"
    return families[operation]


def _build_operation_catalog() -> OperationCatalog:
    query_bounds = ControlBounds()
    plan_preview_bounds = ControlBounds(
        max_items=512,
        max_serialized_bytes=524_288,
        max_depth=12,
        max_text_bytes=65_536,
        max_paths=256,
        max_effects=64,
        timeout_ms=120_000,
    )
    operation_bounds: Mapping[Operation, ControlBounds] = MappingProxyType(
        {
            Operation.PLAN_CREATE_PREVIEW: plan_preview_bounds,
            Operation.PLAN_STEER_PREVIEW: plan_preview_bounds,
            Operation.PLAN_CREATE_APPLY: ControlBounds(timeout_ms=120_000),
            Operation.PLAN_STEER_APPLY: ControlBounds(timeout_ms=120_000),
            Operation.WORKFLOW_PREVIEW: plan_preview_bounds,
            Operation.WORKFLOW_MATERIALIZE: ControlBounds(
                timeout_ms=120_000
            ),
            Operation.RESTART: ControlBounds(timeout_ms=120_000),
            Operation.RESCUE_PREVIEW: ControlBounds(
                max_items=512,
                max_serialized_bytes=524_288,
                max_depth=12,
                max_text_bytes=65_536,
                max_paths=256,
                max_effects=64,
                timeout_ms=120_000,
            ),
            Operation.RESCUE: ControlBounds(timeout_ms=120_000),
        }
    )
    cursor_operations = {
        Operation.GOALS,
        Operation.TASKS,
        Operation.BUNDLES,
        Operation.LANES,
        Operation.RECEIPTS,
        Operation.CACHE_INSPECT,
        Operation.ARTIFACT_QUERY,
    }
    locally_degradable = {
        Operation.STATUS,
        Operation.HEALTH,
        Operation.METRICS,
        Operation.GOALS,
        Operation.TASKS,
        Operation.BUNDLES,
        Operation.LANES,
        Operation.EVENTS,
        Operation.RECEIPTS,
        Operation.CACHE_INSPECT,
        Operation.ARTIFACT_QUERY,
    }
    descriptors: list[ControlOperationDescriptor] = []
    for operation in sorted(Operation, key=lambda item: item.value):
        if operation is Operation.EVENTS:
            pagination = ControlPagination(
                PaginationKind.EVENT_CURSOR,
                default_limit=50,
                max_limit=256,
                cursor_schema=EVENT_CURSOR_SCHEMA,
            )
        elif operation in cursor_operations:
            pagination = ControlPagination(
                PaginationKind.CURSOR,
                default_limit=50,
                max_limit=256,
                cursor_schema=(
                    "ipfs_accelerate_py/agent-supervisor/query-cursor@2"
                ),
            )
        else:
            pagination = ControlPagination(
                PaginationKind.NONE,
                default_limit=1,
                max_limit=1,
            )
        mutation = operation.mutating
        authority = operation.authority
        receipt_schema = {
            OperationAuthority.READ: CONTROL_QUERY_AUDIT_RECEIPT_SCHEMA,
            OperationAuthority.PROPOSAL: CONTROL_PROPOSAL_AUDIT_RECEIPT_SCHEMA,
            OperationAuthority.MUTATION: CONTROL_MUTATION_AUDIT_RECEIPT_SCHEMA,
        }[authority]
        if operation is Operation.CAPABILITIES:
            backend_capability = "control.catalog.v2"
            degradation = CapabilityDegradation.NOT_APPLICABLE
        else:
            backend_capability = f"agent_supervisor.{operation.value}"
            degradation = (
                CapabilityDegradation.LOCAL_READ_ONLY
                if operation in locally_degradable
                else (
                    CapabilityDegradation.PROPOSAL_ONLY
                    if authority is OperationAuthority.PROPOSAL
                    else CapabilityDegradation.FAIL_CLOSED
                )
            )
        descriptors.append(
            ControlOperationDescriptor(
                operation=operation,
                request_schema=operation_request_json_schema(operation),
                result_schema=operation_result_json_schema(operation),
                authority=authority,
                target_descriptor=_catalog_target(operation),
                bounds=operation_bounds.get(operation, query_bounds),
                pagination=pagination,
                # Proposal operations are already intrinsically preview-only.
                # ``supports_dry_run`` is reserved for converting a mutation
                # into a proposal without dispatching its handler.
                supports_dry_run=mutation,
                requires_idempotency=mutation,
                requires_authorization=mutation,
                requires_lease=mutation,
                requires_fencing=mutation,
                backend_capability=backend_capability,
                degradation=degradation,
                audit_receipt_schema=receipt_schema,
                family=_catalog_family(operation),
            )
        )
    return OperationCatalog(tuple(descriptors))


def get_operation_catalog(
    version: int = CONTROL_CATALOG_VERSION,
) -> OperationCatalog:
    """Return the immutable local catalog without resolving a backend."""

    if version != CONTROL_CATALOG_VERSION:
        raise UnsupportedCatalogVersionError(
            f"unsupported control catalog version {version!r}"
        )
    return OPERATION_CATALOG_V2


def discover_control_catalog(
    version: int = CONTROL_CATALOG_VERSION,
) -> OperationCatalog:
    """Side-effect-free discovery spelling shared by future transports."""

    return get_operation_catalog(version)


def negotiate_catalog_version(
    client_versions: Iterable[int],
    service_versions: Iterable[int] = (CONTROL_CATALOG_VERSION,),
) -> int:
    """Select the highest mutual version without consulting runtime state."""

    try:
        client = tuple(client_versions)
        service = tuple(service_versions)
    except TypeError as exc:
        raise CatalogVersionNegotiationError(
            "catalog versions must be iterable"
        ) from exc
    client_normalized = {
        _positive(item, "client catalog version") for item in client
    }
    service_normalized = {
        _positive(item, "service catalog version") for item in service
    }
    mutual = client_normalized.intersection(service_normalized)
    if not mutual:
        raise UnsupportedCatalogVersionError(
            "no mutually supported control catalog version"
        )
    return max(mutual)


negotiate_control_version = negotiate_catalog_version
ControlOperationCatalog = OperationCatalog
ControlCapabilityCatalog = OperationCatalog
ControlCatalog = OperationCatalog
OperationDescriptor = ControlOperationDescriptor
OperationSpec = ControlOperationDescriptor
TargetDescriptor = ControlTargetDescriptor
PaginationDescriptor = ControlPagination
DegradationPolicy = CapabilityDegradation
ControlEventCursor = EventCursor
EventCursorReplayError = CursorReplayError
VersionNegotiationError = CatalogVersionNegotiationError
CapabilityUnavailableError = UnsupportedCapabilityError


@dataclass(frozen=True)
class ControlDiscoveryManifest(_ControlCanonicalContract):
    """Canonical contract exposed by one side-effect-free discovery surface.

    Request and result schema identities are derived from the authoritative
    schema producers.  A transport therefore cannot qualify by advertising a
    caller-supplied digest or a partial operation vocabulary.
    """

    SCHEMA: ClassVar[str] = CONTROL_DISCOVERY_MANIFEST_SCHEMA

    surface: ControlSurface
    operations: tuple[Operation, ...] = tuple(
        sorted(Operation, key=lambda item: item.value)
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "surface",
            _enum(self.surface, ControlSurface, "surface"),
        )
        operations = tuple(
            sorted(
                {_operation(item) for item in self.operations},
                key=lambda item: item.value,
            )
        )
        expected = tuple(sorted(Operation, key=lambda item: item.value))
        if operations != expected:
            raise ControlContractError(
                "discovery manifest must bind the complete operation vocabulary"
            )
        object.__setattr__(self, "operations", operations)
        _bounded_record(self, "control discovery manifest")

    @property
    def request_schema_ids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                operation.value: content_identity(
                    operation_request_json_schema(operation)
                )
                for operation in self.operations
            }
        )

    @property
    def result_schema_ids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                operation.value: content_identity(
                    operation_result_json_schema(operation)
                )
                for operation in self.operations
            }
        )

    @property
    def schema_population_id(self) -> str:
        """Identify the transport-independent closed discovery population."""

        return content_identity(
            {
                "operations": tuple(
                    operation.value for operation in self.operations
                ),
                "request_schema_ids": dict(self.request_schema_ids),
                "result_schema_ids": dict(self.result_schema_ids),
            }
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "surface": self.surface,
            "operations": self.operations,
            "request_schema_ids": dict(self.request_schema_ids),
            "result_schema_ids": dict(self.result_schema_ids),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlDiscoveryManifest":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "surface",
                "operations",
                "request_schema_ids",
                "result_schema_ids",
                "content_id",
            },
            "control discovery manifest",
        )
        result = cls(
            surface=payload.get("surface", ""),
            operations=payload.get("operations", ()),
        )
        for name, actual in (
            ("request_schema_ids", result.request_schema_ids),
            ("result_schema_ids", result.result_schema_ids),
        ):
            claimed = payload.get(name)
            if claimed not in (None, ""):
                if not isinstance(claimed, Mapping) or dict(claimed) != dict(
                    actual
                ):
                    raise ControlContractError(
                        f"discovery manifest {name} does not match shared schemas"
                    )
        _identity(payload, result.content_id, "control discovery manifest")
        return result


@dataclass(frozen=True)
class ControlDiscoveryRuntimeState(_ControlCanonicalContract):
    """Independently observed state surrounding a discovery-only action.

    The three counters are cumulative instrumentation readings.  Comparing
    before and after states catches even a provider load or short-lived child
    process which is absent by the time the final module/process inventory is
    sampled.
    """

    SCHEMA: ClassVar[str] = CONTROL_DISCOVERY_RUNTIME_STATE_SCHEMA

    optional_provider_modules: tuple[str, ...] = ()
    child_process_ids: tuple[int, ...] = ()
    service_resolution_count: int = 0
    optional_provider_load_count: int = 0
    process_start_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "optional_provider_modules",
            _strings(
                self.optional_provider_modules,
                "optional_provider_modules",
            ),
        )
        if isinstance(self.child_process_ids, (str, bytes, bytearray)):
            raise ControlContractError(
                "child_process_ids must be a sequence of integers"
            )
        try:
            process_ids = tuple(
                sorted(
                    {
                        _positive(item, "child process ID")
                        for item in self.child_process_ids
                    }
                )
            )
        except TypeError as exc:
            raise ControlContractError(
                "child_process_ids must be a sequence of integers"
            ) from exc
        if len(process_ids) > ABSOLUTE_MAX_CONTROL_ITEMS:
            raise ControlBoundsError(
                "child_process_ids exceeds its count bound"
            )
        object.__setattr__(self, "child_process_ids", process_ids)
        for name in (
            "service_resolution_count",
            "optional_provider_load_count",
            "process_start_count",
        ):
            object.__setattr__(
                self, name, _nonnegative(getattr(self, name), name)
            )
        _bounded_record(self, "control discovery runtime state")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "optional_provider_modules": self.optional_provider_modules,
            "child_process_ids": self.child_process_ids,
            "service_resolution_count": self.service_resolution_count,
            "optional_provider_load_count": self.optional_provider_load_count,
            "process_start_count": self.process_start_count,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlDiscoveryRuntimeState":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "optional_provider_modules",
                "child_process_ids",
                "service_resolution_count",
                "optional_provider_load_count",
                "process_start_count",
                "content_id",
            },
            "control discovery runtime state",
        )
        result = cls(
            optional_provider_modules=payload.get(
                "optional_provider_modules", ()
            ),
            child_process_ids=payload.get("child_process_ids", ()),
            service_resolution_count=payload.get(
                "service_resolution_count", 0
            ),
            optional_provider_load_count=payload.get(
                "optional_provider_load_count", 0
            ),
            process_start_count=payload.get("process_start_count", 0),
        )
        _identity(payload, result.content_id, "control discovery runtime state")
        return result


@dataclass(frozen=True)
class ControlDiscoveryObservation(_ControlCanonicalContract):
    """A repeated deterministic discovery observed between runtime snapshots."""

    SCHEMA: ClassVar[str] = CONTROL_DISCOVERY_OBSERVATION_SCHEMA

    surface: ControlSurface
    first_manifest: ControlDiscoveryManifest | Mapping[str, Any]
    second_manifest: ControlDiscoveryManifest | Mapping[str, Any]
    before: ControlDiscoveryRuntimeState | Mapping[str, Any]
    after: ControlDiscoveryRuntimeState | Mapping[str, Any]

    def __post_init__(self) -> None:
        surface = _enum(self.surface, ControlSurface, "surface")
        object.__setattr__(self, "surface", surface)
        for name, kind, decoder in (
            (
                "first_manifest",
                ControlDiscoveryManifest,
                ControlDiscoveryManifest.from_dict,
            ),
            (
                "second_manifest",
                ControlDiscoveryManifest,
                ControlDiscoveryManifest.from_dict,
            ),
            (
                "before",
                ControlDiscoveryRuntimeState,
                ControlDiscoveryRuntimeState.from_dict,
            ),
            (
                "after",
                ControlDiscoveryRuntimeState,
                ControlDiscoveryRuntimeState.from_dict,
            ),
        ):
            value = getattr(self, name)
            if not isinstance(value, kind):
                if not isinstance(value, Mapping):
                    raise ControlContractError(
                        f"{name} must be a {kind.__name__}"
                    )
                value = decoder(value)
            object.__setattr__(self, name, value)
        assert isinstance(self.first_manifest, ControlDiscoveryManifest)
        assert isinstance(self.second_manifest, ControlDiscoveryManifest)
        assert isinstance(self.before, ControlDiscoveryRuntimeState)
        assert isinstance(self.after, ControlDiscoveryRuntimeState)
        if (
            self.first_manifest.surface is not surface
            or self.second_manifest.surface is not surface
        ):
            raise ControlContractError(
                "discovery manifest surface does not match its observation"
            )
        if (
            self.first_manifest.canonical_bytes()
            != self.second_manifest.canonical_bytes()
        ):
            raise ControlContractError(
                "repeated control discovery is not byte-deterministic"
            )
        for name in (
            "optional_provider_modules",
            "child_process_ids",
            "service_resolution_count",
            "optional_provider_load_count",
            "process_start_count",
        ):
            if getattr(self.before, name) != getattr(self.after, name):
                raise ControlContractError(
                    "control discovery changed observed runtime state: " + name
                )
        _bounded_record(self, "control discovery observation")

    @property
    def manifest(self) -> ControlDiscoveryManifest:
        assert isinstance(self.first_manifest, ControlDiscoveryManifest)
        return self.first_manifest

    @property
    def side_effect_free(self) -> bool:
        return True

    def _payload(self) -> dict[str, Any]:
        assert isinstance(self.first_manifest, ControlDiscoveryManifest)
        assert isinstance(self.second_manifest, ControlDiscoveryManifest)
        assert isinstance(self.before, ControlDiscoveryRuntimeState)
        assert isinstance(self.after, ControlDiscoveryRuntimeState)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "surface": self.surface,
            "side_effect_free": True,
            "first_manifest": self.first_manifest.to_record(),
            "second_manifest": self.second_manifest.to_record(),
            "before": self.before.to_record(),
            "after": self.after.to_record(),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlDiscoveryObservation":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "surface",
                "side_effect_free",
                "first_manifest",
                "second_manifest",
                "before",
                "after",
                "content_id",
            },
            "control discovery observation",
        )
        if payload.get("side_effect_free") not in (None, True):
            raise ControlContractError(
                "discovery observation cannot claim a failed safety result"
            )
        result = cls(
            surface=payload.get("surface", ""),
            first_manifest=payload.get("first_manifest") or {},
            second_manifest=payload.get("second_manifest") or {},
            before=payload.get("before") or {},
            after=payload.get("after") or {},
        )
        _identity(payload, result.content_id, "control discovery observation")
        return result


@dataclass(frozen=True)
class ControlDiscoverySafetyEvidence(_ControlCanonicalContract):
    """Tamper-evident proof that discovery is deterministic and isolated."""

    SCHEMA: ClassVar[str] = CONTROL_DISCOVERY_SAFETY_EVIDENCE_SCHEMA

    repository_tree: str
    objective_id: str
    policy_id: str
    policy_revision: str
    capability_report: CapabilityReport | Mapping[str, Any]
    observations: tuple[ControlDiscoveryObservation, ...]
    requirement_id: str = CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID

    def __post_init__(self) -> None:
        for name in (
            "repository_tree",
            "objective_id",
            "policy_id",
            "policy_revision",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.requirement_id != CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID:
            raise ControlContractError(
                "discovery evidence requirement_id is not the ASI-G105 requirement"
            )
        if self.objective_id != CONTROL_DISCOVERY_SAFETY_OBJECTIVE_ID:
            raise ControlContractError(
                "discovery evidence objective_id is not ASI-G105"
            )
        report = self.capability_report
        if not isinstance(report, CapabilityReport):
            if not isinstance(report, Mapping):
                raise ControlContractError(
                    "capability_report must be a CapabilityReport"
                )
            report = CapabilityReport.from_dict(report)
        expected_operations = tuple(
            sorted(Operation, key=lambda item: item.value)
        )
        if report.supported_operations != expected_operations:
            raise ControlContractError(
                "discovery evidence requires complete capabilities"
            )
        if report.optional_providers_loaded or report.processes_started:
            raise ControlContractError(
                "capability discovery reports provider or process side effects"
            )
        object.__setattr__(self, "capability_report", report)
        observations = _coerce_tuple(
            self.observations,
            ControlDiscoveryObservation,
            ControlDiscoveryObservation.from_dict,
            "observations",
        )
        surfaces = tuple(
            sorted(
                (item.surface for item in observations),
                key=lambda item: item.value,
            )
        )
        expected_surfaces = tuple(
            sorted(ControlSurface, key=lambda item: item.value)
        )
        if surfaces != expected_surfaces:
            raise ControlContractError(
                "discovery evidence requires one Python, CLI, and MCP observation"
            )
        if len(
            {item.manifest.schema_population_id for item in observations}
        ) != 1:
            raise ControlContractError(
                "Python, CLI, and MCP discovery schema populations differ"
            )
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(observations, key=lambda item: item.surface.value)),
        )
        _bounded_record(
            self,
            "control discovery safety evidence",
            maximum=ABSOLUTE_MAX_CONTROL_BYTES,
        )

    @property
    def proved_requirement_ids(self) -> tuple[str, ...]:
        return (CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID,)

    @property
    def completion_authoritative(self) -> bool:
        """Operational evidence is input to, never a substitute for, the gate."""

        return False

    def evaluate_objective_completion(
        self,
        *,
        current_state: Any = "active",
        evidence: Sequence[Any] = (),
        tasks_complete: bool = False,
        coverage: Any = None,
        analyzer_health: Any = None,
        exhaustion_quorum: Any = None,
        child_goals: Sequence[Any] = (),
        now: Any = None,
        freshness_seconds: float | None = None,
        clock_skew_seconds: float | None = None,
        analysis_inconclusive: bool = False,
        blocked_reason: str = "",
    ) -> Any:
        """Evaluate ASI-G105 through its closed, two-phase completion gate.

        The discovery record is the operational witness, not permission to
        declare its own objective complete.  Callers must separately supply a
        fresh validation for every immutable criterion, exact implementation
        and validation coverage, explicit completion-safe analyzer health, and
        the configured independent exhaustive quorum.  The tree, objective,
        policy, and receipt identities are derived from this record rather
        than accepted from completion arguments.
        """

        return _evaluate_control_objective_completion(
            self,
            objective_id=CONTROL_DISCOVERY_SAFETY_OBJECTIVE_ID,
            requirement_id=CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID,
            objective_revision=CONTROL_DISCOVERY_SAFETY_OBJECTIVE_REVISION,
            analyzer_version=(
                CONTROL_DISCOVERY_SAFETY_COMPLETION_ANALYZER_VERSION
            ),
            configuration_revision=(
                CONTROL_DISCOVERY_SAFETY_COMPLETION_CONFIGURATION_REVISION
            ),
            acceptance_criteria=(
                CONTROL_DISCOVERY_SAFETY_ACCEPTANCE_CRITERIA
            ),
            required_exhaustive_receipts=(
                CONTROL_DISCOVERY_SAFETY_REQUIRED_EXHAUSTIVE_RECEIPTS
            ),
            quorum_evidence_type=ControlDiscoveryCompletionQuorumEvidence,
            operational_complete=bool(
                self.proved_requirement_ids
                == (CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID,)
                and tuple(item.surface for item in self.observations)
                == tuple(sorted(ControlSurface, key=lambda item: item.value))
                and all(item.side_effect_free for item in self.observations)
                and not self.capability_report.optional_providers_loaded
                and not self.capability_report.processes_started
            ),
            current_state=current_state,
            evidence=evidence,
            tasks_complete=tasks_complete,
            coverage=coverage,
            analyzer_health=analyzer_health,
            exhaustion_quorum=exhaustion_quorum,
            child_goals=child_goals,
            now=now,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
            analysis_inconclusive=analysis_inconclusive,
            blocked_reason=blocked_reason,
        )

    def _payload(self) -> dict[str, Any]:
        assert isinstance(self.capability_report, CapabilityReport)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "requirement_id": self.requirement_id,
            "repository_tree": self.repository_tree,
            "objective_id": self.objective_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "capability_report": self.capability_report.to_record(),
            "observations": tuple(
                item.to_record() for item in self.observations
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlDiscoverySafetyEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "requirement_id",
                "repository_tree",
                "objective_id",
                "policy_id",
                "policy_revision",
                "capability_report",
                "observations",
                "content_id",
            },
            "control discovery safety evidence",
        )
        result = cls(
            requirement_id=payload.get("requirement_id", ""),
            repository_tree=payload.get("repository_tree", ""),
            objective_id=payload.get("objective_id", ""),
            policy_id=payload.get("policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            capability_report=payload.get("capability_report") or {},
            observations=payload.get("observations", ()),
        )
        _identity(payload, result.content_id, "control discovery safety evidence")
        return result


@dataclass(frozen=True)
class ControlDiscoveryCompletionMemberHealth(_ControlCanonicalContract):
    """Explicit completion-safety attestation for one exhaustive receipt."""

    SCHEMA: ClassVar[str] = CONTROL_DISCOVERY_COMPLETION_MEMBER_HEALTH_SCHEMA

    member_id: str
    receipt_cid: str
    healthy: bool
    safe_for_completion_reasoning: bool

    def __post_init__(self) -> None:
        for name in ("member_id", "receipt_cid"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("healthy", "safe_for_completion_reasoning"):
            if not isinstance(getattr(self, name), bool):
                raise ControlContractError(f"{name} must be a boolean")
        _bounded_record(self, "control discovery completion member health")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "member_id": self.member_id,
            "receipt_cid": self.receipt_cid,
            "healthy": self.healthy,
            "safe_for_completion_reasoning": (
                self.safe_for_completion_reasoning
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlDiscoveryCompletionMemberHealth":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "member_id",
                "receipt_cid",
                "healthy",
                "safe_for_completion_reasoning",
                "content_id",
            },
            "control discovery completion member health",
        )
        result = cls(
            member_id=payload.get("member_id", ""),
            receipt_cid=payload.get("receipt_cid", ""),
            healthy=payload.get("healthy", False),
            safe_for_completion_reasoning=payload.get(
                "safe_for_completion_reasoning", False
            ),
        )
        _identity(
            payload,
            result.content_id,
            "control discovery completion member health",
        )
        return result


@dataclass(frozen=True)
class ControlDiscoveryCompletionQuorumEvidence(_ControlCanonicalContract):
    """Bind a generic exhaustive quorum to one G105 operational witness."""

    SCHEMA: ClassVar[str] = (
        CONTROL_DISCOVERY_COMPLETION_QUORUM_EVIDENCE_SCHEMA
    )

    validation_policy_id: str
    policy_revision: str
    operational_receipt_id: str
    quorum: Any
    member_health: tuple[
        ControlDiscoveryCompletionMemberHealth | Mapping[str, Any], ...
    ]
    objective_id: str = CONTROL_DISCOVERY_SAFETY_OBJECTIVE_ID
    requirement_id: str = CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID

    def __post_init__(self) -> None:
        from ..objectives.scan_receipts import ExhaustionQuorumResult

        for name in (
            "validation_policy_id",
            "policy_revision",
            "operational_receipt_id",
            "objective_id",
            "requirement_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.objective_id != CONTROL_DISCOVERY_SAFETY_OBJECTIVE_ID:
            raise ControlContractError(
                "completion quorum objective_id is not ASI-G105"
            )
        if self.requirement_id != CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID:
            raise ControlContractError(
                "completion quorum requirement_id is not the ASI-G105 requirement"
            )
        quorum = self.quorum
        if not isinstance(quorum, ExhaustionQuorumResult):
            if not isinstance(quorum, Mapping):
                raise ControlContractError(
                    "completion quorum must contain an ExhaustionQuorumResult"
                )
            try:
                quorum = ExhaustionQuorumResult.from_dict(quorum)
            except (TypeError, ValueError) as exc:
                raise ControlContractError(
                    "completion quorum is malformed"
                ) from exc
        object.__setattr__(self, "quorum", quorum)
        member_health = _coerce_tuple(
            self.member_health,
            ControlDiscoveryCompletionMemberHealth,
            ControlDiscoveryCompletionMemberHealth.from_dict,
            "member_health",
        )
        expected_members = {
            (member.member_id, member.receipt_cid)
            for member in quorum.members
        }
        attested_members = {
            (member.member_id, member.receipt_cid)
            for member in member_health
        }
        if (
            len(member_health) != len(attested_members)
            or attested_members != expected_members
        ):
            raise ControlContractError(
                "completion member health must cover every quorum receipt exactly"
            )
        if not all(
            member.healthy and member.safe_for_completion_reasoning
            for member in member_health
        ):
            raise ControlContractError(
                "every exhaustive receipt must be explicitly healthy and "
                "safe for completion reasoning"
            )
        object.__setattr__(
            self,
            "member_health",
            tuple(sorted(member_health, key=lambda item: item.member_id)),
        )
        _bounded_record(self, "control discovery completion quorum evidence")

    def _payload(self) -> dict[str, Any]:
        quorum = self.quorum.to_dict()
        # ExhaustionQuorumResult exposes a derived float confidence for UI
        # consumers.  Canonical proof contracts encode the exact integer
        # counts instead and deliberately exclude floats.
        quorum.pop("confidence", None)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "requirement_id": self.requirement_id,
            "objective_id": self.objective_id,
            "validation_policy_id": self.validation_policy_id,
            "policy_revision": self.policy_revision,
            "operational_receipt_id": self.operational_receipt_id,
            "quorum": quorum,
            "member_health": tuple(
                item.to_record() for item in self.member_health
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlDiscoveryCompletionQuorumEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "requirement_id",
                "objective_id",
                "validation_policy_id",
                "policy_revision",
                "operational_receipt_id",
                "quorum",
                "member_health",
                "content_id",
            },
            "control discovery completion quorum evidence",
        )
        result = cls(
            requirement_id=payload.get("requirement_id", ""),
            objective_id=payload.get("objective_id", ""),
            validation_policy_id=payload.get("validation_policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            operational_receipt_id=payload.get("operational_receipt_id", ""),
            quorum=payload.get("quorum") or {},
            member_health=payload.get("member_health", ()),
        )
        _identity(
            payload,
            result.content_id,
            "control discovery completion quorum evidence",
        )
        return result


def _evaluate_control_objective_completion(
    receipt: Any,
    *,
    objective_id: str,
    requirement_id: str,
    objective_revision: str,
    analyzer_version: str,
    configuration_revision: str,
    acceptance_criteria: Sequence[str],
    required_exhaustive_receipts: int,
    quorum_evidence_type: type[Any],
    operational_complete: bool,
    current_state: Any,
    evidence: Sequence[Any],
    tasks_complete: bool,
    coverage: Any,
    analyzer_health: Any,
    exhaustion_quorum: Any,
    child_goals: Sequence[Any],
    now: Any,
    freshness_seconds: float | None,
    clock_skew_seconds: float | None,
    analysis_inconclusive: bool,
    blocked_reason: str,
) -> Any:
    """Keep objective-gate policy outside the canonical receipt payload."""

    from ..objectives.goal_completion import evaluate_goal_completion
    from ..objectives.scan_receipts import ExhaustionQuorumResult

    def payload(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        converter = getattr(value, "to_dict", None)
        if callable(converter):
            converted = converter()
            if isinstance(converted, Mapping):
                return dict(converted)
        return {}

    def criterion_key(value: Any) -> str:
        if isinstance(value, Mapping):
            value = value.get(
                "criterion",
                value.get(
                    "acceptance_criterion",
                    value.get("acceptance", ""),
                ),
            )
        return " ".join(str(value or "").strip().lower().split())

    def populated(row: Mapping[str, Any], *names: str) -> bool:
        for name in names:
            value = row.get(name)
            if isinstance(value, str) and value.strip():
                return True
            if (
                isinstance(value, Sequence)
                and not isinstance(value, (str, bytes, bytearray))
                and any(str(item or "").strip() for item in value)
            ):
                return True
        return False

    operational_complete = bool(
        operational_complete
        and receipt.objective_id == objective_id
        and receipt.requirement_id == requirement_id
    )
    expected_criteria = {
        criterion_key(item) for item in acceptance_criteria
    }

    evidence_records: list[dict[str, Any]] = []
    validation_ids_by_criterion: dict[str, set[str]] = {}
    for item in evidence:
        record = payload(item)
        if isinstance(record.get("evidence"), Mapping):
            record = dict(record["evidence"])
        evidence_records.append(record)
        key = criterion_key(record)
        identity = str(
            record.get(
                "provenance_cid",
                record.get("receipt_cid", ""),
            )
            or ""
        ).strip()
        if key and identity:
            validation_ids_by_criterion.setdefault(key, set()).add(identity)

    validation_bindings_complete = bool(
        operational_complete
        and len(evidence_records) == len(expected_criteria)
    )
    evidence_criteria: list[str] = []
    for record in evidence_records:
        key = criterion_key(record)
        evidence_criteria.append(key)
        validation = record.get("validation_receipt")
        validation = validation if isinstance(validation, Mapping) else {}
        validation_bindings_complete = bool(
            validation_bindings_complete
            and key in expected_criteria
            and validation.get("requirement_id") == requirement_id
            and validation.get("objective_id") == objective_id
            and validation.get("operational_receipt_id") == receipt.content_id
            and validation.get("validation_policy_id") == receipt.policy_id
            and validation.get("policy_revision") == receipt.policy_revision
            and validation.get("tree_id") == receipt.repository_tree
        )
    validation_bindings_complete = bool(
        validation_bindings_complete
        and len(evidence_criteria) == len(set(evidence_criteria))
        and set(evidence_criteria) == expected_criteria
    )

    coverage_projection = getattr(coverage, "completion_gate_evidence", None)
    canonical_coverage = callable(coverage_projection)
    if canonical_coverage:
        try:
            projected = coverage_projection(objective_id)
        except (TypeError, ValueError):
            projected = {}
        coverage_value = (
            dict(projected) if isinstance(projected, Mapping) else {}
        )
    else:
        coverage_value = payload(coverage)
    rows_value = coverage_value.get("criteria")
    rows = rows_value if isinstance(rows_value, list) else []
    row_keys = [
        criterion_key(row) if isinstance(row, Mapping) else ""
        for row in rows
    ]

    def validation_bound(row: Mapping[str, Any]) -> bool:
        raw_ids = row.get("validation_receipt_ids")
        if not (
            isinstance(raw_ids, Sequence)
            and not isinstance(raw_ids, (str, bytes, bytearray))
        ):
            return False
        row_receipts = {
            str(item or "").strip()
            for item in raw_ids
            if str(item or "").strip()
        }
        return bool(
            row_receipts
            and row_receipts.intersection(
                validation_ids_by_criterion.get(criterion_key(row), set())
            )
        )

    canonical_coverage_complete = True
    if canonical_coverage:
        freshness = coverage_value.get("freshness")
        freshness = freshness if isinstance(freshness, Mapping) else {}
        binding = coverage_value.get("binding")
        binding = binding if isinstance(binding, Mapping) else {}
        canonical_coverage_complete = bool(
            coverage_value.get("verified") is True
            and coverage_value.get("repository_tree")
            == receipt.repository_tree
            and freshness.get("all_receipts_fresh") is True
            and binding.get("all_receipts_bound") is True
            and binding.get("repository_tree") == receipt.repository_tree
        )
    coverage_complete = bool(
        operational_complete
        and validation_bindings_complete
        and canonical_coverage_complete
        and coverage_value.get("verified") is True
        and coverage_value.get("repository_tree") == receipt.repository_tree
        and len(row_keys) == len(expected_criteria)
        and len(row_keys) == len(set(row_keys))
        and set(row_keys) == expected_criteria
        and all(
            isinstance(row, Mapping)
            and populated(
                row,
                "implementation",
                "changed_files",
                "predicted_files",
                "ast_symbols",
                "interfaces",
            )
            and validation_bound(row)
            for row in rows
        )
    )
    if not coverage_complete:
        reasons = coverage_value.get("reason_codes")
        reasons = list(reasons) if isinstance(reasons, (list, tuple)) else []
        if not operational_complete:
            reasons.append("active_operational_evidence_missing")
        if not validation_bindings_complete:
            reasons.append("validation_not_bound_to_operational_witness")
        reasons.append("coverage_missing_implementation_validation_binding")
        coverage_value = {
            **coverage_value,
            "verified": False,
            "passed": False,
            "reason_codes": list(dict.fromkeys(reasons)),
        }

    artifact_quorum = isinstance(
        exhaustion_quorum,
        quorum_evidence_type,
    )
    if artifact_quorum:
        quorum_value = payload(exhaustion_quorum.quorum)
        artifact_quorum_binding = {
            "objective_id": exhaustion_quorum.objective_id,
            "requirement_id": exhaustion_quorum.requirement_id,
            "validation_policy_id": exhaustion_quorum.validation_policy_id,
            "policy_revision": exhaustion_quorum.policy_revision,
            "operational_receipt_id": (
                exhaustion_quorum.operational_receipt_id
            ),
        }
    else:
        quorum_value = payload(exhaustion_quorum)
        artifact_quorum_binding = {}
    quorum_binding = quorum_value.get("binding")
    quorum_binding = (
        quorum_binding if isinstance(quorum_binding, Mapping) else {}
    )
    health_value = payload(analyzer_health)
    health_metrics = health_value.get("metrics")
    health_metrics = (
        health_metrics if isinstance(health_metrics, Mapping) else {}
    )
    reported_analyzer_version = str(
        health_value.get("analyzer_version")
        or health_metrics.get("analyzer_version")
        or ""
    ).strip()
    health_binding_complete = bool(
        reported_analyzer_version == analyzer_version
        and (
            health_value.get("objective_id")
            or health_metrics.get("objective_id")
        )
        == objective_id
        and (
            health_value.get("repository_tree")
            or health_metrics.get("repository_tree")
        )
        == receipt.repository_tree
    )
    if not (
        str(health_value.get("status") or "").strip().lower() == "healthy"
        and health_value.get("healthy") is True
        and health_value.get("safe_for_completion_reasoning") is True
        and health_binding_complete
    ):
        health_value = {
            **health_value,
            "healthy": False,
            "safe_for_completion_reasoning": False,
        }

    evaluated_quorum = artifact_quorum and isinstance(
        exhaustion_quorum.quorum,
        ExhaustionQuorumResult,
    )
    canonical_binding = {
        "tree_id": receipt.repository_tree,
        "analyzer_version": analyzer_version,
        "configuration_revision": configuration_revision,
        "objective_revision": objective_revision,
    }
    artifact_binding = {
        **canonical_binding,
        "objective_id": objective_id,
        "requirement_id": requirement_id,
        "validation_policy_id": receipt.policy_id,
        "policy_revision": receipt.policy_revision,
        "operational_receipt_id": receipt.content_id,
    }
    members_value = quorum_value.get("members")
    members = members_value if isinstance(members_value, list) else []
    if evaluated_quorum:
        member_health = {
            (item.member_id, item.receipt_cid): item
            for item in getattr(exhaustion_quorum, "member_health", ())
        }
        quorum_binding = {
            **quorum_binding,
            **artifact_quorum_binding,
        }
        members = [
            {
                **member,
                "binding": {
                    **(
                        member.get("binding")
                        if isinstance(member.get("binding"), Mapping)
                        else {}
                    ),
                    **artifact_quorum_binding,
                },
                **(
                    {
                        "healthy": member_health[
                            (
                                str(member.get("member_id") or ""),
                                str(member.get("receipt_cid") or ""),
                            )
                        ].healthy,
                        "safe_for_completion_reasoning": member_health[
                            (
                                str(member.get("member_id") or ""),
                                str(member.get("receipt_cid") or ""),
                            )
                        ].safe_for_completion_reasoning,
                    }
                    if (
                        str(member.get("member_id") or ""),
                        str(member.get("receipt_cid") or ""),
                    )
                    in member_health
                    else {}
                ),
            }
            for member in members
            if isinstance(member, Mapping)
        ]
    required_binding = artifact_binding
    member_ids = [
        str(item.get("member_id") or "").strip()
        for item in members
        if isinstance(item, Mapping)
    ]
    receipt_ids = [
        str(item.get("receipt_cid") or "").strip()
        for item in members
        if isinstance(item, Mapping)
    ]
    channels = [
        str(item.get("evidence_channel") or "").strip()
        for item in members
        if isinstance(item, Mapping)
    ]

    def independent(values: Sequence[str]) -> bool:
        return bool(
            len(values) == len(members)
            and all(values)
            and len(values) == len(set(values))
        )

    evaluated_members_complete = bool(
        evaluated_quorum
        and quorum_value.get("satisfied") is True
        and all(
            isinstance(member, Mapping)
            and str(member.get("scan_mode") or "").strip().lower()
            == "exhaustive"
            and (
                not hasattr(exhaustion_quorum, "member_health")
                or (
                    member.get("healthy") is True
                    and member.get("safe_for_completion_reasoning") is True
                )
            )
            for member in members
        )
    )
    quorum_complete = bool(
        quorum_value.get("required_members")
        == required_exhaustive_receipts
        and quorum_value.get("member_count") == len(members)
        and len(members)
        >= required_exhaustive_receipts
        and quorum_value.get("satisfied") is True
        and quorum_value.get("quorum_met") is True
        and all(
            quorum_binding.get(name) == value
            for name, value in required_binding.items()
        )
        and independent(member_ids)
        and independent(receipt_ids)
        and independent(channels)
        and all(
            isinstance(member, Mapping)
            and isinstance(member.get("binding"), Mapping)
            and all(
                member["binding"].get(name) == value
                for name, value in required_binding.items()
            )
            for member in members
        )
        and (
            evaluated_members_complete
            or all(
                isinstance(member, Mapping)
                and member.get("healthy") is True
                and member.get("safe_for_completion_reasoning") is True
                and str(member.get("scan_mode") or "").strip().lower()
                == "exhaustive"
                for member in members
            )
        )
    )
    if not quorum_complete:
        quorum_value = {
            **quorum_value,
            "satisfied": False,
            "quorum_met": False,
        }

    values: dict[str, Any] = {
        "current_state": current_state,
        "acceptance_criteria": acceptance_criteria,
        "evidence": evidence,
        "tasks_complete": tasks_complete,
        "repository_tree": receipt.repository_tree,
        "now": now,
        "analysis_inconclusive": analysis_inconclusive,
        "blocked_reason": blocked_reason,
        "coverage": coverage_value,
        "analyzer_health": health_value,
        "exhaustion_quorum": quorum_value,
        "child_goals": child_goals,
        "analysis_result": None,
        "require_completion_gate": True,
    }
    if freshness_seconds is not None:
        values["freshness_seconds"] = freshness_seconds
    if clock_skew_seconds is not None:
        values["clock_skew_seconds"] = clock_skew_seconds
    return evaluate_goal_completion(**values)


def evaluate_unified_control_completion(
    *,
    repository_id: str,
    repository_tree: str,
    producing_tasks: Sequence[Any] = (),
    child_goals: Sequence[Any] = (),
    current_state: Any = "active",
    evidence: Sequence[Any] = (),
    tasks_complete: bool = False,
    coverage: Any = None,
    analyzer_health: Any = None,
    exhaustion_quorum: Any = None,
    required_exhaustive_receipts: int = (
        UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS
    ),
    now: Any = None,
    freshness_seconds: float = 3600.0,
    clock_skew_seconds: float = 300.0,
    analysis_inconclusive: bool = False,
    blocked_reason: str = "",
) -> Any:
    """Evaluate the immutable ASI-G070 parent completion boundary.

    G103, G104, and G105 each own a distinct operational witness, so no one
    child receipt can grant authority to this parent.  The parent advances
    only when its original producing tasks and exact verified child population
    are complete, every literal parent criterion has a fresh validation bound
    to implementation coverage on the current tree, analyzer health is
    explicitly completion-safe, and exactly the configured independent
    exhaustive receipts are fresh and healthy.

    The objective, producer, child, analyzer, configuration, criterion, and
    quorum populations are deliberately not caller-selectable.
    """

    from ..objectives.goal_completion import evaluate_goal_completion

    if (
        isinstance(required_exhaustive_receipts, bool)
        or not isinstance(required_exhaustive_receipts, int)
        or required_exhaustive_receipts
        != UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS
    ):
        raise ValueError(
            "required_exhaustive_receipts must equal the configured ASI-G070 "
            f"count {UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS}"
        )

    def payload(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        converter = getattr(value, "to_dict", None)
        if callable(converter):
            converted = converter()
            if isinstance(converted, Mapping):
                return dict(converted)
        return {}

    def normalized(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def parsed_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, str) and value.strip():
            try:
                result = datetime.fromisoformat(
                    value.strip().replace("Z", "+00:00")
                )
            except ValueError:
                return None
        else:
            return None
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    current = parsed_datetime(now) or datetime.now(timezone.utc)
    repository_id = str(repository_id or "").strip()
    repository_tree = str(repository_tree or "").strip()
    expected_binding = {
        "repository_id": repository_id,
        "tree_id": repository_tree,
        "objective_id": UNIFIED_CONTROL_OBJECTIVE_ID,
        "objective_revision": UNIFIED_CONTROL_OBJECTIVE_REVISION,
        "analyzer_version": UNIFIED_CONTROL_COMPLETION_ANALYZER_VERSION,
        "configuration_revision": (
            UNIFIED_CONTROL_COMPLETION_CONFIGURATION_REVISION
        ),
    }

    successful_task_states = frozenset(
        {
            "complete",
            "completed",
            "passed",
            "success",
            "succeeded",
            "verified",
            "verified_complete",
        }
    )
    task_values = [payload(item) for item in producing_tasks]
    task_ids = [
        str(item.get("task_id", item.get("id", "")) or "").strip()
        for item in task_values
    ]
    producer_population_complete = bool(
        repository_id
        and repository_tree
        and len(task_ids) == len(set(task_ids))
        and tuple(sorted(task_ids))
        == tuple(sorted(UNIFIED_CONTROL_PRODUCING_TASK_IDS))
        and all(
            normalized(item.get("status", item.get("state", "")))
            in successful_task_states
            for item in task_values
        )
    )

    evidence_ids: dict[str, set[str]] = {}
    for item in evidence:
        record = payload(item)
        source = record.get("evidence", record)
        source = source if isinstance(source, Mapping) else record
        criterion = normalized(
            source.get(
                "acceptance_criterion",
                source.get("criterion", source.get("acceptance", "")),
            )
        )
        receipt_id = str(
            source.get(
                "provenance_cid",
                source.get("receipt_id", source.get("evidence_id", "")),
            )
            or ""
        ).strip()
        if criterion and receipt_id:
            evidence_ids.setdefault(criterion, set()).add(receipt_id)

    def implementation_bound(row: Mapping[str, Any]) -> bool:
        for name in (
            "implementation",
            "implementation_binding",
            "changed_files",
            "predicted_files",
            "ast_symbols",
            "interfaces",
        ):
            value = row.get(name)
            if isinstance(value, str) and value.strip():
                return True
            if (
                isinstance(value, Sequence)
                and not isinstance(value, (str, bytes, bytearray))
                and any(str(item or "").strip() for item in value)
            ):
                return True
        return False

    def validation_ids(row: Mapping[str, Any]) -> set[str]:
        raw = row.get(
            "validation_receipt_ids",
            row.get("validation_receipt_id", ()),
        )
        if isinstance(raw, str):
            raw = (raw,)
        if not (
            isinstance(raw, Sequence)
            and not isinstance(raw, (str, bytes, bytearray))
        ):
            return set()
        return {
            str(item or "").strip()
            for item in raw
            if str(item or "").strip()
        }

    coverage_value = payload(coverage)
    rows_value = coverage_value.get("criteria")
    rows = rows_value if isinstance(rows_value, list) else []
    expected_criteria = {
        normalized(item) for item in UNIFIED_CONTROL_ACCEPTANCE_CRITERIA
    }
    row_keys = [
        normalized(
            row.get(
                "criterion",
                row.get("acceptance_criterion", row.get("acceptance", "")),
            )
        )
        for row in rows
        if isinstance(row, Mapping)
    ]
    coverage_bound = bool(
        len(row_keys) == len(expected_criteria)
        and len(row_keys) == len(set(row_keys))
        and set(row_keys) == expected_criteria
        and all(
            isinstance(row, Mapping)
            and implementation_bound(row)
            and bool(
                validation_ids(row).intersection(
                    evidence_ids.get(
                        normalized(
                            row.get(
                                "criterion",
                                row.get(
                                    "acceptance_criterion",
                                    row.get("acceptance", ""),
                                ),
                            )
                        ),
                        set(),
                    )
                )
            )
            for row in rows
        )
    )
    if not coverage_bound:
        reasons = coverage_value.get("reason_codes")
        reasons = list(reasons) if isinstance(reasons, (list, tuple)) else []
        coverage_value = {
            **coverage_value,
            "verified": False,
            "passed": False,
            "reason_codes": list(
                dict.fromkeys(
                    [*reasons, "coverage_validation_receipt_unbound"]
                )
            ),
        }

    health_value = payload(analyzer_health)
    raw_health_binding = health_value.get("binding")
    health_binding = (
        dict(raw_health_binding)
        if isinstance(raw_health_binding, Mapping)
        else {}
    )
    health_valid = bool(
        all(expected_binding.values())
        and all(
            health_binding.get(name) == value
            for name, value in expected_binding.items()
        )
        and normalized(health_value.get("status")) == "healthy"
        and health_value.get("healthy") is True
        and health_value.get("safe_for_completion_reasoning") is True
    )
    if not health_valid:
        health_value = {
            **health_value,
            "healthy": False,
            "safe_for_completion_reasoning": False,
        }

    def fresh(value: Any) -> bool:
        observed = parsed_datetime(value)
        if observed is None:
            return False
        return bool(
            observed
            <= current
            + timedelta(seconds=max(0.0, float(clock_skew_seconds)))
            and current - observed
            <= timedelta(seconds=max(0.0, float(freshness_seconds)))
        )

    quorum_value = payload(exhaustion_quorum)
    members_value = quorum_value.get("members")
    members = members_value if isinstance(members_value, list) else []
    raw_quorum_binding = quorum_value.get("binding")
    quorum_binding = (
        dict(raw_quorum_binding)
        if isinstance(raw_quorum_binding, Mapping)
        else {}
    )

    def independent_member_field(name: str) -> bool:
        values = [
            str(member.get(name) or "").strip()
            for member in members
            if isinstance(member, Mapping)
        ]
        return bool(
            len(values) == len(members)
            and all(values)
            and len(values) == len(set(values))
        )

    quorum_valid = bool(
        quorum_value.get("required_members")
        == UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS
        and quorum_value.get("member_count") == len(members)
        and len(members) == UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS
        and quorum_value.get("satisfied") is True
        and quorum_value.get("quorum_met") is True
        and health_valid
        and quorum_binding == health_binding
        and independent_member_field("member_id")
        and independent_member_field("evidence_channel")
        and independent_member_field("receipt_cid")
        and all(
            isinstance(member, Mapping)
            and member.get("healthy") is True
            and member.get("safe_for_completion_reasoning") is True
            and normalized(member.get("scan_mode")) == "exhaustive"
            and fresh(member.get("finished_at"))
            and isinstance(member.get("binding"), Mapping)
            and dict(member["binding"]) == health_binding
            for member in members
        )
    )
    if not quorum_valid:
        quorum_value = {
            **quorum_value,
            "satisfied": False,
            "quorum_met": False,
        }

    def child_is_current(child: Mapping[str, Any]) -> bool:
        gate_value = child.get("completion_gate", child.get("gate"))
        gate = gate_value if isinstance(gate_value, Mapping) else {}
        evaluated_value = gate.get("evaluated_evidence")
        evaluated = (
            evaluated_value if isinstance(evaluated_value, Mapping) else {}
        )
        validations = evaluated.get("validation_evidence")
        proof_requirements = child.get(
            "proof_requirements",
            evaluated.get("proof_requirements", ()),
        )
        if isinstance(proof_requirements, Mapping):
            proof_requirements = (proof_requirements,)
        return bool(
            normalized(
                child.get("state", child.get("next_state", ""))
            )
            == "verified_complete"
            and child.get("verified") is True
            and gate.get("passed") is True
            and evaluated.get("repository_tree") == repository_tree
            and evaluated.get("repository_id") == repository_id
            and fresh(evaluated.get("evaluated_at"))
            and isinstance(validations, list)
            and bool(validations)
            and all(
                isinstance(item, Mapping)
                and item.get("valid") is True
                and isinstance(item.get("evidence"), Mapping)
                and item["evidence"].get("repository_tree")
                == repository_tree
                and item["evidence"].get("repository_id") == repository_id
                for item in validations
            )
            and isinstance(proof_requirements, (list, tuple))
            and bool(proof_requirements)
            and all(
                isinstance(item, Mapping)
                and item.get("repository_tree") == repository_tree
                and str(item.get("provenance_id") or "").strip()
                and item.get("assurance_satisfied") is True
                and item.get("contradicted") is not True
                and normalized(item.get("proof_verdict"))
                in {"proved", "verified", "valid"}
                and normalized(item.get("freshness"))
                in {"current", "fresh"}
                and not item.get("reason_codes")
                for item in proof_requirements
            )
        )

    child_values = [payload(item) for item in child_goals]
    child_ids = [
        str(item.get("goal_id", item.get("id", "")) or "").strip()
        for item in child_values
    ]
    child_population_complete = bool(
        len(child_ids) == len(set(child_ids))
        and tuple(sorted(child_ids))
        == tuple(sorted(UNIFIED_CONTROL_CHILD_GOAL_IDS))
        and all(child_is_current(item) for item in child_values)
    )
    if not child_population_complete:
        child_values.append(
            {
                "goal_id": "ASI-G070-required-child-population",
                "state": "active",
                "verified": False,
                "completion_gate": {
                    "passed": False,
                    "reason_code": (
                        "required_child_population_or_binding_incomplete"
                    ),
                },
            }
        )

    return evaluate_goal_completion(
        current_state=current_state,
        acceptance_criteria=UNIFIED_CONTROL_ACCEPTANCE_CRITERIA,
        evidence=evidence,
        tasks_complete=bool(tasks_complete and producer_population_complete),
        repository_tree=repository_tree,
        repository_id=repository_id,
        now=current,
        freshness_seconds=freshness_seconds,
        clock_skew_seconds=clock_skew_seconds,
        coverage=coverage_value,
        analyzer_health=health_value,
        exhaustion_quorum=quorum_value,
        child_goals=child_values,
        analysis_result=None,
        analysis_inconclusive=analysis_inconclusive,
        blocked_reason=blocked_reason,
        require_completion_gate=True,
    )


# Alternate terminology retained for integrations which use "isolation".
ControlDiscoveryIsolationEvidence = ControlDiscoverySafetyEvidence


@dataclass(frozen=True)
class ControlSurfaceParityCase(_ControlCanonicalContract):
    """One independently invoked Python/CLI/MCP behavior comparison.

    Full canonical records are retained rather than caller-supplied booleans
    or digests.  Construction re-decodes every record, validates each result
    against the request, and requires byte-for-byte equality across surfaces.
    """

    SCHEMA: ClassVar[str] = CONTROL_SURFACE_PARITY_CASE_SCHEMA

    scenario: str
    request: OperationRequest | Mapping[str, Any]
    python_result: OperationResult | Mapping[str, Any]
    cli_result: OperationResult | Mapping[str, Any]
    mcp_result: OperationResult | Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scenario", _text(self.scenario, "scenario", max_bytes=128)
        )
        request = self.request
        if not isinstance(request, OperationRequest):
            if not isinstance(request, Mapping):
                raise ControlContractError(
                    "parity case request must be an OperationRequest"
                )
            request = OperationRequest.from_dict(request)
        object.__setattr__(self, "request", request)

        decoded: list[OperationResult] = []
        for field_name in ("python_result", "cli_result", "mcp_result"):
            result = getattr(self, field_name)
            if not isinstance(result, OperationResult):
                if not isinstance(result, Mapping):
                    raise ControlContractError(
                        f"{field_name} must be an OperationResult"
                    )
                result = OperationResult.from_dict(result)
            result.validate_against(request)
            object.__setattr__(self, field_name, result)
            decoded.append(result)
        records = [item.to_record() for item in decoded]
        if records[1:] != records[:-1]:
            raise ControlContractError(
                "Python, CLI, and MCP results are not canonically identical"
            )
        _bounded_record(
            self,
            "control surface parity case",
            maximum=ABSOLUTE_MAX_CONTROL_BYTES,
        )

    @property
    def operation(self) -> Operation:
        assert isinstance(self.request, OperationRequest)
        return self.request.operation

    @property
    def status(self) -> OperationStatus:
        assert isinstance(self.python_result, OperationResult)
        return self.python_result.status

    @property
    def result_id(self) -> str:
        assert isinstance(self.python_result, OperationResult)
        return self.python_result.result_id

    @property
    def behavior_class(self) -> ControlBehaviorClass:
        """Derive, rather than trust, the qualifying behavior class."""

        assert isinstance(self.request, OperationRequest)
        assert isinstance(self.python_result, OperationResult)
        if not self.python_result.succeeded:
            if self.python_result.error is None:
                raise ControlContractError(
                    "failed parity result must carry a stable typed error"
                )
            return ControlBehaviorClass.STABLE_FAILURE
        if self.request.operation.mutating and not self.request.dry_run:
            if (
                not self.python_result.audit_receipt_id
                or not any(
                    effect.applied for effect in self.python_result.effects
                )
            ):
                raise ControlContractError(
                    "successful mutation parity case must be audited and applied"
                )
            return ControlBehaviorClass.MUTATION_SUCCESS
        if self.request.effective_authority is OperationAuthority.PROPOSAL:
            if self.python_result.preview is None:
                raise ControlContractError(
                    "successful proposal parity case must carry a preview"
                )
            return ControlBehaviorClass.PROPOSAL_SUCCESS
        return ControlBehaviorClass.READ_SUCCESS

    def _payload(self) -> dict[str, Any]:
        assert isinstance(self.request, OperationRequest)
        assert isinstance(self.python_result, OperationResult)
        assert isinstance(self.cli_result, OperationResult)
        assert isinstance(self.mcp_result, OperationResult)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "scenario": self.scenario,
            "behavior_class": self.behavior_class,
            "operation": self.operation,
            "status": self.status,
            "request": self.request.to_record(),
            "python_result": self.python_result.to_record(),
            "cli_result": self.cli_result.to_record(),
            "mcp_result": self.mcp_result.to_record(),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlSurfaceParityCase":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "scenario",
                "behavior_class",
                "operation",
                "status",
                "request",
                "python_result",
                "cli_result",
                "mcp_result",
                "content_id",
            },
            "control surface parity case",
        )
        result = cls(
            scenario=payload.get("scenario", ""),
            request=payload.get("request") or {},
            python_result=payload.get("python_result") or {},
            cli_result=payload.get("cli_result") or {},
            mcp_result=payload.get("mcp_result") or {},
        )
        claimed_operation = payload.get("operation")
        if claimed_operation not in (None, "") and _operation(
            claimed_operation
        ) is not result.operation:
            raise ControlContractError(
                "parity case operation does not match its request"
            )
        claimed_behavior = payload.get("behavior_class")
        if claimed_behavior not in (None, "") and _enum(
            claimed_behavior,
            ControlBehaviorClass,
            "behavior_class",
        ) is not result.behavior_class:
            raise ControlContractError(
                "parity case behavior_class does not match its result"
            )
        claimed_status = payload.get("status")
        if claimed_status not in (None, "") and _enum(
            claimed_status, OperationStatus, "status"
        ) is not result.status:
            raise ControlContractError(
                "parity case status does not match its result"
            )
        _identity(payload, result.content_id, "control surface parity case")
        return result


@dataclass(frozen=True)
class ControlSurfaceParityEvidence(_ControlCanonicalContract):
    """Tamper-evident proof that all public control surfaces share one contract."""

    SCHEMA: ClassVar[str] = CONTROL_SURFACE_PARITY_EVIDENCE_SCHEMA

    repository_tree: str
    objective_id: str
    policy_id: str
    policy_revision: str
    capability_report: CapabilityReport | Mapping[str, Any]
    cases: tuple[ControlSurfaceParityCase, ...]
    operations: tuple[Operation, ...] = tuple(
        sorted(Operation, key=lambda item: item.value)
    )
    surfaces: tuple[ControlSurface, ...] = tuple(ControlSurface)
    requirement_id: str = CONTROL_SURFACE_PARITY_REQUIREMENT_ID

    def __post_init__(self) -> None:
        for name in (
            "repository_tree",
            "objective_id",
            "policy_id",
            "policy_revision",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.requirement_id != CONTROL_SURFACE_PARITY_REQUIREMENT_ID:
            raise ControlContractError(
                "parity evidence requirement_id is not the ASI-G103 requirement"
            )
        if self.objective_id != CONTROL_SURFACE_PARITY_OBJECTIVE_ID:
            raise ControlContractError(
                "parity evidence objective_id is not ASI-G103"
            )
        report = self.capability_report
        if not isinstance(report, CapabilityReport):
            if not isinstance(report, Mapping):
                raise ControlContractError(
                    "capability_report must be a CapabilityReport"
                )
            report = CapabilityReport.from_dict(report)
        object.__setattr__(self, "capability_report", report)

        cases = _coerce_tuple(
            self.cases,
            ControlSurfaceParityCase,
            ControlSurfaceParityCase.from_dict,
            "cases",
        )
        if not cases:
            raise ControlContractError(
                "parity evidence requires independently invoked cases"
            )
        scenarios = [item.scenario for item in cases]
        if len(scenarios) != len(set(scenarios)):
            raise ControlContractError("parity case scenarios must be unique")
        behavior_classes = {item.behavior_class for item in cases}
        required_behavior_classes = set(ControlBehaviorClass)
        if behavior_classes != required_behavior_classes:
            missing = sorted(
                item.value
                for item in required_behavior_classes - behavior_classes
            )
            raise ControlContractError(
                "parity evidence requires the complete behavior matrix"
                + (": missing " + ", ".join(missing) if missing else "")
            )
        for item in cases:
            assert isinstance(item.request, OperationRequest)
            if (
                item.request.tree_id != self.repository_tree
                or item.request.objective_id != self.objective_id
                or item.request.policy_id != self.policy_id
                or item.request.policy_revision != self.policy_revision
            ):
                raise ControlContractError(
                    "parity case is stale or bound to another objective/policy"
                )
        object.__setattr__(self, "cases", tuple(cases))

        operations = tuple(
            sorted(
                {_operation(item) for item in self.operations},
                key=lambda item: item.value,
            )
        )
        expected_operations = tuple(
            sorted(Operation, key=lambda item: item.value)
        )
        if operations != expected_operations:
            raise ControlContractError(
                "parity evidence must bind the complete operation vocabulary"
            )
        if report.supported_operations != expected_operations:
            raise ControlContractError(
                "capability report must support the complete operation vocabulary"
            )
        object.__setattr__(self, "operations", operations)

        surfaces = tuple(
            sorted(
                {_enum(item, ControlSurface, "surface") for item in self.surfaces},
                key=lambda item: item.value,
            )
        )
        expected_surfaces = tuple(
            sorted(ControlSurface, key=lambda item: item.value)
        )
        if surfaces != expected_surfaces:
            raise ControlContractError(
                "parity evidence requires Python, CLI, and MCP observations"
            )
        object.__setattr__(self, "surfaces", surfaces)
        _bounded_record(
            self,
            "control surface parity evidence",
            maximum=ABSOLUTE_MAX_CONTROL_BYTES,
        )

    @property
    def request_schema_id(self) -> str:
        return content_identity(operation_request_json_schema())

    @property
    def result_schema_id(self) -> str:
        return content_identity(operation_result_json_schema())

    @property
    def request_schema_ids(self) -> Mapping[str, str]:
        """Bind every operation-specific request schema in the closed contract."""

        return MappingProxyType(
            {
                operation.value: content_identity(
                    operation_request_json_schema(operation)
                )
                for operation in self.operations
            }
        )

    @property
    def result_schema_ids(self) -> Mapping[str, str]:
        """Bind every operation-specific result schema in the closed contract."""

        return MappingProxyType(
            {
                operation.value: content_identity(
                    operation_result_json_schema(operation)
                )
                for operation in self.operations
            }
        )

    @property
    def schema_population_id(self) -> str:
        """Identify the complete transport-independent operation schema set."""

        return content_identity(
            {
                "operations": tuple(
                    operation.value for operation in self.operations
                ),
                "request_schema_ids": dict(self.request_schema_ids),
                "result_schema_ids": dict(self.result_schema_ids),
            }
        )

    @property
    def proved_requirement_ids(self) -> tuple[str, ...]:
        return (CONTROL_SURFACE_PARITY_REQUIREMENT_ID,)

    @property
    def completion_authoritative(self) -> bool:
        """Operational evidence is input to, never a substitute for, the gate."""

        return False

    def evaluate_objective_completion(
        self,
        *,
        current_state: Any = "active",
        evidence: Sequence[Any] = (),
        tasks_complete: bool = False,
        coverage: Any = None,
        analyzer_health: Any = None,
        exhaustion_quorum: Any = None,
        child_goals: Sequence[Any] = (),
        now: Any = None,
        freshness_seconds: float | None = None,
        clock_skew_seconds: float | None = None,
        analysis_inconclusive: bool = False,
        blocked_reason: str = "",
    ) -> Any:
        """Evaluate ASI-G103 through its closed, two-phase completion gate.

        The parity receipt is the operational witness, not permission to
        declare its objective complete.  Every immutable criterion needs a
        separate current-tree validation and implementation binding, analyzer
        health must explicitly permit completion reasoning, and the configured
        independent exhaustive quorum must bind this exact witness and policy.
        """

        expected_operations = tuple(
            sorted(Operation, key=lambda item: item.value)
        )
        expected_surfaces = tuple(
            sorted(ControlSurface, key=lambda item: item.value)
        )
        return _evaluate_control_objective_completion(
            self,
            objective_id=CONTROL_SURFACE_PARITY_OBJECTIVE_ID,
            requirement_id=CONTROL_SURFACE_PARITY_REQUIREMENT_ID,
            objective_revision=CONTROL_SURFACE_PARITY_OBJECTIVE_REVISION,
            analyzer_version=(
                CONTROL_SURFACE_PARITY_COMPLETION_ANALYZER_VERSION
            ),
            configuration_revision=(
                CONTROL_SURFACE_PARITY_COMPLETION_CONFIGURATION_REVISION
            ),
            acceptance_criteria=CONTROL_SURFACE_PARITY_ACCEPTANCE_CRITERIA,
            required_exhaustive_receipts=(
                CONTROL_SURFACE_PARITY_REQUIRED_EXHAUSTIVE_RECEIPTS
            ),
            quorum_evidence_type=ControlSurfaceParityCompletionQuorumEvidence,
            operational_complete=bool(
                self.proved_requirement_ids
                == (CONTROL_SURFACE_PARITY_REQUIREMENT_ID,)
                and self.operations == expected_operations
                and self.surfaces == expected_surfaces
                and self.capability_report.supported_operations
                == expected_operations
                and set(self.request_schema_ids)
                == {item.value for item in expected_operations}
                and set(self.result_schema_ids)
                == {item.value for item in expected_operations}
                and {item.behavior_class for item in self.cases}
                == set(ControlBehaviorClass)
            ),
            current_state=current_state,
            evidence=evidence,
            tasks_complete=tasks_complete,
            coverage=coverage,
            analyzer_health=analyzer_health,
            exhaustion_quorum=exhaustion_quorum,
            child_goals=child_goals,
            now=now,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
            analysis_inconclusive=analysis_inconclusive,
            blocked_reason=blocked_reason,
        )

    def _payload(self) -> dict[str, Any]:
        assert isinstance(self.capability_report, CapabilityReport)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "requirement_id": self.requirement_id,
            "repository_tree": self.repository_tree,
            "objective_id": self.objective_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "surfaces": self.surfaces,
            "operations": self.operations,
            "request_schema_id": self.request_schema_id,
            "result_schema_id": self.result_schema_id,
            "request_schema_ids": dict(self.request_schema_ids),
            "result_schema_ids": dict(self.result_schema_ids),
            "schema_population_id": self.schema_population_id,
            "capability_report": self.capability_report.to_record(),
            "cases": tuple(item.to_record() for item in self.cases),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlSurfaceParityEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "requirement_id",
                "repository_tree",
                "objective_id",
                "policy_id",
                "policy_revision",
                "surfaces",
                "operations",
                "request_schema_id",
                "result_schema_id",
                "request_schema_ids",
                "result_schema_ids",
                "schema_population_id",
                "capability_report",
                "cases",
                "content_id",
            },
            "control surface parity evidence",
        )
        result = cls(
            requirement_id=payload.get("requirement_id", ""),
            repository_tree=payload.get("repository_tree", ""),
            objective_id=payload.get("objective_id", ""),
            policy_id=payload.get("policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            surfaces=payload.get("surfaces", ()),
            operations=payload.get("operations", ()),
            capability_report=payload.get("capability_report") or {},
            cases=payload.get("cases", ()),
        )
        for name, actual in (
            ("request_schema_id", result.request_schema_id),
            ("result_schema_id", result.result_schema_id),
            ("request_schema_ids", result.request_schema_ids),
            ("result_schema_ids", result.result_schema_ids),
            ("schema_population_id", result.schema_population_id),
        ):
            claimed = payload.get(name)
            if isinstance(actual, Mapping):
                matches = isinstance(claimed, Mapping) and dict(claimed) == dict(
                    actual
                )
            else:
                matches = claimed == actual
            if not matches:
                raise ControlContractError(
                    f"parity evidence {name} does not match the shared schema"
                )
        _identity(payload, result.content_id, "control surface parity evidence")
        return result


@dataclass(frozen=True)
class ControlSurfaceParityCompletionMemberHealth(_ControlCanonicalContract):
    """Explicit completion-safety attestation for one G103 receipt."""

    SCHEMA: ClassVar[str] = (
        CONTROL_SURFACE_PARITY_COMPLETION_MEMBER_HEALTH_SCHEMA
    )

    member_id: str
    receipt_cid: str
    healthy: bool
    safe_for_completion_reasoning: bool

    def __post_init__(self) -> None:
        for name in ("member_id", "receipt_cid"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("healthy", "safe_for_completion_reasoning"):
            if not isinstance(getattr(self, name), bool):
                raise ControlContractError(f"{name} must be a boolean")
        _bounded_record(self, "control surface parity completion member health")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "member_id": self.member_id,
            "receipt_cid": self.receipt_cid,
            "healthy": self.healthy,
            "safe_for_completion_reasoning": (
                self.safe_for_completion_reasoning
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlSurfaceParityCompletionMemberHealth":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "member_id",
                "receipt_cid",
                "healthy",
                "safe_for_completion_reasoning",
                "content_id",
            },
            "control surface parity completion member health",
        )
        result = cls(
            member_id=payload.get("member_id", ""),
            receipt_cid=payload.get("receipt_cid", ""),
            healthy=payload.get("healthy", False),
            safe_for_completion_reasoning=payload.get(
                "safe_for_completion_reasoning", False
            ),
        )
        _identity(
            payload,
            result.content_id,
            "control surface parity completion member health",
        )
        return result


@dataclass(frozen=True)
class ControlSurfaceParityCompletionQuorumEvidence(
    _ControlCanonicalContract
):
    """Bind a healthy exhaustive quorum to one G103 parity witness."""

    SCHEMA: ClassVar[str] = (
        CONTROL_SURFACE_PARITY_COMPLETION_QUORUM_EVIDENCE_SCHEMA
    )

    validation_policy_id: str
    policy_revision: str
    operational_receipt_id: str
    quorum: Any
    member_health: tuple[
        ControlSurfaceParityCompletionMemberHealth | Mapping[str, Any], ...
    ]
    objective_id: str = CONTROL_SURFACE_PARITY_OBJECTIVE_ID
    requirement_id: str = CONTROL_SURFACE_PARITY_REQUIREMENT_ID

    def __post_init__(self) -> None:
        from ..objectives.scan_receipts import ExhaustionQuorumResult

        for name in (
            "validation_policy_id",
            "policy_revision",
            "operational_receipt_id",
            "objective_id",
            "requirement_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.objective_id != CONTROL_SURFACE_PARITY_OBJECTIVE_ID:
            raise ControlContractError(
                "completion quorum objective_id is not ASI-G103"
            )
        if self.requirement_id != CONTROL_SURFACE_PARITY_REQUIREMENT_ID:
            raise ControlContractError(
                "completion quorum requirement_id is not the ASI-G103 "
                "requirement"
            )
        quorum = self.quorum
        if not isinstance(quorum, ExhaustionQuorumResult):
            if not isinstance(quorum, Mapping):
                raise ControlContractError(
                    "completion quorum must contain an ExhaustionQuorumResult"
                )
            try:
                quorum = ExhaustionQuorumResult.from_dict(quorum)
            except (TypeError, ValueError) as exc:
                raise ControlContractError(
                    "completion quorum is malformed"
                ) from exc
        object.__setattr__(self, "quorum", quorum)
        member_health = _coerce_tuple(
            self.member_health,
            ControlSurfaceParityCompletionMemberHealth,
            ControlSurfaceParityCompletionMemberHealth.from_dict,
            "member_health",
        )
        expected_members = {
            (member.member_id, member.receipt_cid)
            for member in quorum.members
        }
        attested_members = {
            (member.member_id, member.receipt_cid)
            for member in member_health
        }
        if (
            len(member_health) != len(attested_members)
            or attested_members != expected_members
        ):
            raise ControlContractError(
                "completion member health must cover every quorum receipt "
                "exactly"
            )
        if not all(
            member.healthy and member.safe_for_completion_reasoning
            for member in member_health
        ):
            raise ControlContractError(
                "every exhaustive receipt must be explicitly healthy and "
                "safe for completion reasoning"
            )
        object.__setattr__(
            self,
            "member_health",
            tuple(sorted(member_health, key=lambda item: item.member_id)),
        )
        _bounded_record(
            self,
            "control surface parity completion quorum evidence",
        )

    def _payload(self) -> dict[str, Any]:
        quorum = self.quorum.to_dict()
        quorum.pop("confidence", None)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "requirement_id": self.requirement_id,
            "objective_id": self.objective_id,
            "validation_policy_id": self.validation_policy_id,
            "policy_revision": self.policy_revision,
            "operational_receipt_id": self.operational_receipt_id,
            "quorum": quorum,
            "member_health": tuple(
                item.to_record() for item in self.member_health
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlSurfaceParityCompletionQuorumEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "requirement_id",
                "objective_id",
                "validation_policy_id",
                "policy_revision",
                "operational_receipt_id",
                "quorum",
                "member_health",
                "content_id",
            },
            "control surface parity completion quorum evidence",
        )
        result = cls(
            requirement_id=payload.get("requirement_id", ""),
            objective_id=payload.get("objective_id", ""),
            validation_policy_id=payload.get("validation_policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            operational_receipt_id=payload.get("operational_receipt_id", ""),
            quorum=payload.get("quorum") or {},
            member_health=payload.get("member_health", ()),
        )
        _identity(
            payload,
            result.content_id,
            "control surface parity completion quorum evidence",
        )
        return result


@dataclass(frozen=True)
class MutationGuardRejection(_ControlCanonicalContract):
    """One surface-observed pre-dispatch canonical mutation rejection.

    The payload is independently replayed through the authoritative parser.
    The two cumulative counters bind the observation to an adapter invocation
    that neither resolved a service nor reached a mutation backend.
    """

    SCHEMA: ClassVar[str] = MUTATION_GUARD_REJECTION_SCHEMA

    scenario: str
    surface: ControlSurface
    request_payload: Mapping[str, Any]
    error_type: str
    service_resolution_count_before: int = 0
    service_resolution_count_after: int = 0
    dispatch_count_before: int = 0
    dispatch_count_after: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", _text(self.scenario, "scenario"))
        if self.scenario not in CONTROL_MUTATION_GUARD_REJECTION_SCENARIOS:
            raise ControlContractError(
                "mutation guard rejection scenario is not in the closed "
                "rejection vocabulary"
            )
        object.__setattr__(
            self,
            "surface",
            _enum(self.surface, ControlSurface, "surface"),
        )
        for name in (
            "service_resolution_count_before",
            "service_resolution_count_after",
            "dispatch_count_before",
            "dispatch_count_after",
        ):
            object.__setattr__(
                self,
                name,
                _nonnegative(getattr(self, name), name),
            )
        if (
            self.service_resolution_count_after
            != self.service_resolution_count_before
        ):
            raise ControlContractError(
                "rejected mutation must not resolve a control service"
            )
        if self.dispatch_count_after != self.dispatch_count_before:
            raise ControlContractError(
                "rejected mutation must fail before backend dispatch"
            )
        if not isinstance(self.request_payload, Mapping):
            raise ControlContractError("request_payload must be a mapping")
        payload = dict(self.request_payload)
        payload.pop("content_id", None)
        object.__setattr__(
            self,
            "request_payload",
            _freeze_value(
                payload,
                name="rejected request payload",
                max_depth=ABSOLUTE_MAX_CONTROL_DEPTH,
                max_items=ABSOLUTE_MAX_CONTROL_ITEMS,
                max_text_bytes=ABSOLUTE_MAX_CONTROL_TEXT_BYTES,
                check_paths=False,
            ),
        )
        error_type = _text(self.error_type, "error_type")
        try:
            OperationRequest.from_dict(payload)
        except (ControlContractError, ValueError) as exc:
            actual = type(exc).__name__
        else:
            raise ControlContractError(
                "mutation guard rejection payload was accepted"
            )
        if actual != error_type:
            raise ControlContractError(
                "mutation guard rejection error_type does not match replay"
            )
        object.__setattr__(self, "error_type", error_type)
        _bounded_record(self, "mutation guard rejection")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "scenario": self.scenario,
            "surface": self.surface,
            "request_payload": self.request_payload,
            "error_type": self.error_type,
            "service_resolution_count_before": (
                self.service_resolution_count_before
            ),
            "service_resolution_count_after": (
                self.service_resolution_count_after
            ),
            "dispatch_count_before": self.dispatch_count_before,
            "dispatch_count_after": self.dispatch_count_after,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MutationGuardRejection":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "scenario",
                "surface",
                "request_payload",
                "error_type",
                "service_resolution_count_before",
                "service_resolution_count_after",
                "dispatch_count_before",
                "dispatch_count_after",
                "content_id",
            },
            "mutation guard rejection",
        )
        result = cls(
            scenario=payload.get("scenario", ""),
            surface=payload.get("surface", ""),
            request_payload=payload.get("request_payload") or {},
            error_type=payload.get("error_type", ""),
            service_resolution_count_before=payload.get(
                "service_resolution_count_before", 0
            ),
            service_resolution_count_after=payload.get(
                "service_resolution_count_after", 0
            ),
            dispatch_count_before=payload.get("dispatch_count_before", 0),
            dispatch_count_after=payload.get("dispatch_count_after", 0),
        )
        _identity(payload, result.content_id, "mutation guard rejection")
        return result


@dataclass(frozen=True)
class ControlMutationRuntimeState(_ControlCanonicalContract):
    """Observed mutation dispatch and durable-audit population at one instant."""

    SCHEMA: ClassVar[str] = CONTROL_MUTATION_RUNTIME_STATE_SCHEMA

    dispatch_count: int = 0
    audit_receipt_count: int = 0
    last_dispatch_request_id: str = ""
    last_audit_receipt_id: str = ""

    def __post_init__(self) -> None:
        for name in ("dispatch_count", "audit_receipt_count"):
            object.__setattr__(
                self, name, _nonnegative(getattr(self, name), name)
            )
        for name in (
            "last_dispatch_request_id",
            "last_audit_receipt_id",
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), name, required=False),
            )
        if bool(self.dispatch_count) != bool(self.last_dispatch_request_id):
            raise ControlContractError(
                "dispatch count and latest request identity must both be set"
            )
        if bool(self.audit_receipt_count) != bool(
            self.last_audit_receipt_id
        ):
            raise ControlContractError(
                "audit count and latest receipt identity must both be set"
            )
        _bounded_record(self, "control mutation runtime state")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "dispatch_count": self.dispatch_count,
            "audit_receipt_count": self.audit_receipt_count,
            "last_dispatch_request_id": self.last_dispatch_request_id,
            "last_audit_receipt_id": self.last_audit_receipt_id,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlMutationRuntimeState":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "dispatch_count",
                "audit_receipt_count",
                "last_dispatch_request_id",
                "last_audit_receipt_id",
                "content_id",
            },
            "control mutation runtime state",
        )
        result = cls(
            dispatch_count=payload.get("dispatch_count", 0),
            audit_receipt_count=payload.get("audit_receipt_count", 0),
            last_dispatch_request_id=payload.get(
                "last_dispatch_request_id", ""
            ),
            last_audit_receipt_id=payload.get(
                "last_audit_receipt_id", ""
            ),
        )
        _identity(payload, result.content_id, "control mutation runtime state")
        return result


@dataclass(frozen=True)
class MutationGuardExecutionObservation(_ControlCanonicalContract):
    """Three runtime snapshots proving one dispatch and a dispatch-free replay."""

    SCHEMA: ClassVar[str] = MUTATION_GUARD_EXECUTION_OBSERVATION_SCHEMA

    request_id: str
    result_id: str
    audit_receipt_id: str
    before: ControlMutationRuntimeState | Mapping[str, Any]
    after_result: ControlMutationRuntimeState | Mapping[str, Any]
    after_replay: ControlMutationRuntimeState | Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("request_id", "result_id", "audit_receipt_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        states: dict[str, ControlMutationRuntimeState] = {}
        for name in ("before", "after_result", "after_replay"):
            item = getattr(self, name)
            if not isinstance(item, ControlMutationRuntimeState):
                if not isinstance(item, Mapping):
                    raise ControlContractError(
                        f"{name} must be a ControlMutationRuntimeState"
                    )
                item = ControlMutationRuntimeState.from_dict(item)
            object.__setattr__(self, name, item)
            states[name] = item

        before = states["before"]
        after_result = states["after_result"]
        after_replay = states["after_replay"]
        if (
            after_result.dispatch_count != before.dispatch_count + 1
            or after_result.last_dispatch_request_id != self.request_id
        ):
            raise ControlContractError(
                "mutation execution must add exactly one bound backend dispatch"
            )
        if (
            after_replay.dispatch_count != after_result.dispatch_count
            or after_replay.last_dispatch_request_id
            != after_result.last_dispatch_request_id
        ):
            raise ControlContractError(
                "idempotent replay must not dispatch the backend"
            )
        if (
            after_result.audit_receipt_count
            != before.audit_receipt_count + 1
            or after_result.last_audit_receipt_id
            != self.audit_receipt_id
        ):
            raise ControlContractError(
                "mutation execution must add exactly one bound audit receipt"
            )
        if (
            after_replay.audit_receipt_count
            != after_result.audit_receipt_count
            or after_replay.last_audit_receipt_id
            != after_result.last_audit_receipt_id
        ):
            raise ControlContractError(
                "idempotent replay must not append another audit receipt"
            )
        _bounded_record(self, "mutation guard execution observation")

    def _payload(self) -> dict[str, Any]:
        assert isinstance(self.before, ControlMutationRuntimeState)
        assert isinstance(self.after_result, ControlMutationRuntimeState)
        assert isinstance(self.after_replay, ControlMutationRuntimeState)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "request_id": self.request_id,
            "result_id": self.result_id,
            "audit_receipt_id": self.audit_receipt_id,
            "before": self.before.to_record(),
            "after_result": self.after_result.to_record(),
            "after_replay": self.after_replay.to_record(),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "MutationGuardExecutionObservation":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "request_id",
                "result_id",
                "audit_receipt_id",
                "before",
                "after_result",
                "after_replay",
                "content_id",
            },
            "mutation guard execution observation",
        )
        result = cls(
            request_id=payload.get("request_id", ""),
            result_id=payload.get("result_id", ""),
            audit_receipt_id=payload.get("audit_receipt_id", ""),
            before=payload.get("before") or {},
            after_result=payload.get("after_result") or {},
            after_replay=payload.get("after_replay") or {},
        )
        _identity(
            payload, result.content_id, "mutation guard execution observation"
        )
        return result


@dataclass(frozen=True)
class ControlMutationGuardEvidence(_ControlCanonicalContract):
    """Evidence that an applied mutation was guarded, audited, and replay-safe."""

    SCHEMA: ClassVar[str] = CONTROL_MUTATION_GUARD_EVIDENCE_SCHEMA

    repository_tree: str
    objective_id: str
    policy_id: str
    policy_revision: str
    request: OperationRequest | Mapping[str, Any]
    result: OperationResult | Mapping[str, Any]
    replay_result: OperationResult | Mapping[str, Any]
    execution: MutationGuardExecutionObservation | Mapping[str, Any]
    rejections: tuple[MutationGuardRejection, ...]
    requirement_id: str = CONTROL_MUTATION_GUARD_REQUIREMENT_ID

    def __post_init__(self) -> None:
        for name in (
            "repository_tree",
            "objective_id",
            "policy_id",
            "policy_revision",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.requirement_id != CONTROL_MUTATION_GUARD_REQUIREMENT_ID:
            raise ControlContractError(
                "mutation evidence requirement_id is not the ASI-G104 requirement"
            )
        if self.objective_id != CONTROL_MUTATION_GUARD_OBJECTIVE_ID:
            raise ControlContractError(
                "mutation evidence objective_id is not ASI-G104"
            )
        request = self.request
        if not isinstance(request, OperationRequest):
            if not isinstance(request, Mapping):
                raise ControlContractError("request must be an OperationRequest")
            request = OperationRequest.from_dict(request)
        if not request.operation.mutating or request.dry_run:
            raise ControlContractError(
                "mutation guard evidence requires a real mutation request"
            )
        if (
            request.tree_id != self.repository_tree
            or request.objective_id != self.objective_id
            or request.policy_id != self.policy_id
            or request.policy_revision != self.policy_revision
        ):
            raise ControlContractError(
                "mutation guard evidence request binding is stale"
            )
        object.__setattr__(self, "request", request)

        decoded_results: list[OperationResult] = []
        for name in ("result", "replay_result"):
            item = getattr(self, name)
            if not isinstance(item, OperationResult):
                if not isinstance(item, Mapping):
                    raise ControlContractError(
                        f"{name} must be an OperationResult"
                    )
                item = OperationResult.from_dict(item)
            item.validate_against(request)
            if not item.succeeded:
                raise ControlContractError(
                    "mutation guard evidence requires successful results"
                )
            object.__setattr__(self, name, item)
            decoded_results.append(item)
        if (
            decoded_results[0].to_record() != decoded_results[1].to_record()
            or not decoded_results[0].audit_receipt_id
            or not any(effect.applied for effect in decoded_results[0].effects)
        ):
            raise ControlContractError(
                "mutation result is not audited, applied, and exactly replayed"
            )

        execution = self.execution
        if not isinstance(execution, MutationGuardExecutionObservation):
            if not isinstance(execution, Mapping):
                raise ControlContractError(
                    "execution must be a MutationGuardExecutionObservation"
                )
            execution = MutationGuardExecutionObservation.from_dict(execution)
        if (
            execution.request_id != request.request_id
            or execution.result_id != decoded_results[0].result_id
            or execution.audit_receipt_id
            != decoded_results[0].audit_receipt_id
        ):
            raise ControlContractError(
                "mutation execution observation is detached from its request "
                "or result"
            )
        object.__setattr__(self, "execution", execution)

        rejections = _coerce_tuple(
            self.rejections,
            MutationGuardRejection,
            MutationGuardRejection.from_dict,
            "rejections",
        )
        observed_cases = {
            (item.surface, item.scenario) for item in rejections
        }
        required_cases = {
            (surface, scenario)
            for surface in ControlSurface
            for scenario in CONTROL_MUTATION_GUARD_REJECTION_SCENARIOS
        }
        if (
            observed_cases != required_cases
            or len(rejections) != len(required_cases)
        ):
            raise ControlContractError(
                "mutation evidence requires the complete rejection scenario "
                "matrix on Python, CLI, and MCP"
            )
        canonical_request = request.to_record()
        canonical_request.pop("content_id", None)
        canonical_request = dict(
            _freeze_value(
                canonical_request,
                name="canonical mutation request",
                max_depth=ABSOLUTE_MAX_CONTROL_DEPTH,
                max_items=ABSOLUTE_MAX_CONTROL_ITEMS,
                max_text_bytes=ABSOLUTE_MAX_CONTROL_TEXT_BYTES,
            )
        )
        unauthorized = dict(canonical_request)
        unauthorized.pop("authorization", None)

        unscoped_idempotency = dict(canonical_request)
        idempotency = dict(unscoped_idempotency["idempotency"])
        idempotency.pop("content_id", None)
        idempotency["objective_id"] = "objective:outside-request-scope"
        unscoped_idempotency["idempotency"] = idempotency

        unfenced = dict(canonical_request)
        unfenced.pop("lease_id", None)
        unfenced.pop("fencing_epoch", None)

        stale_binding = dict(canonical_request)
        stale_binding["tree_id"] = (
            f"{self.repository_tree}:stale-request-binding"
        )

        path_escape = dict(canonical_request)
        parameters = dict(path_escape["parameters"])
        parameters["target_path"] = "../outside-repository"
        path_escape["parameters"] = parameters

        undeclared_effect = dict(canonical_request)
        undeclared_effect["expected_effects"] = ()

        expected_rejections: dict[str, dict[str, Any]] = {
            "unauthorized": unauthorized,
            "unscoped_idempotency": unscoped_idempotency,
            "unfenced": unfenced,
            "stale_binding": stale_binding,
            "path_escape": path_escape,
            "undeclared_effect": undeclared_effect,
        }
        for rejection in rejections:
            if dict(rejection.request_payload) != expected_rejections[
                rejection.scenario
            ]:
                raise ControlContractError(
                    "mutation guard rejection is not the bound request with "
                    f"only the {rejection.scenario} guard invalidated"
                )
        object.__setattr__(
            self,
            "rejections",
            tuple(
                sorted(
                    rejections,
                    key=lambda item: (item.surface.value, item.scenario),
                )
            ),
        )
        _bounded_record(
            self,
            "control mutation guard evidence",
            maximum=ABSOLUTE_MAX_CONTROL_BYTES,
        )

    @property
    def proved_requirement_ids(self) -> tuple[str, ...]:
        return (CONTROL_MUTATION_GUARD_REQUIREMENT_ID,)

    @property
    def completion_authoritative(self) -> bool:
        """Operational evidence is input to, never a substitute for, the gate."""

        return False

    def evaluate_objective_completion(
        self,
        *,
        current_state: Any = "active",
        evidence: Sequence[Any] = (),
        tasks_complete: bool = False,
        coverage: Any = None,
        analyzer_health: Any = None,
        exhaustion_quorum: Any = None,
        child_goals: Sequence[Any] = (),
        now: Any = None,
        freshness_seconds: float | None = None,
        clock_skew_seconds: float | None = None,
        analysis_inconclusive: bool = False,
        blocked_reason: str = "",
    ) -> Any:
        """Evaluate ASI-G104 through its closed, two-phase completion gate.

        The mutation record proves one guarded runtime execution and exact
        replay.  It cannot promote its own objective: callers must separately
        supply fresh validation for every immutable criterion, exact
        implementation/validation coverage, explicit completion-safe analyzer
        health, and the configured independent exhaustive quorum.
        """

        result = self.result
        replay = self.replay_result
        execution = self.execution
        assert isinstance(result, OperationResult)
        assert isinstance(replay, OperationResult)
        assert isinstance(execution, MutationGuardExecutionObservation)
        required_rejections = {
            (surface, scenario)
            for surface in ControlSurface
            for scenario in CONTROL_MUTATION_GUARD_REJECTION_SCENARIOS
        }
        operational_complete = bool(
            self.proved_requirement_ids
            == (CONTROL_MUTATION_GUARD_REQUIREMENT_ID,)
            and isinstance(self.request, OperationRequest)
            and self.request.operation.mutating
            and not self.request.dry_run
            and result.to_record() == replay.to_record()
            and bool(result.audit_receipt_id)
            and any(effect.applied for effect in result.effects)
            and execution.request_id == self.request.request_id
            and execution.result_id == result.result_id
            and execution.audit_receipt_id == result.audit_receipt_id
            and {
                (item.surface, item.scenario)
                for item in self.rejections
            }
            == required_rejections
        )
        return _evaluate_control_objective_completion(
            self,
            objective_id=CONTROL_MUTATION_GUARD_OBJECTIVE_ID,
            requirement_id=CONTROL_MUTATION_GUARD_REQUIREMENT_ID,
            objective_revision=CONTROL_MUTATION_GUARD_OBJECTIVE_REVISION,
            analyzer_version=(
                CONTROL_MUTATION_GUARD_COMPLETION_ANALYZER_VERSION
            ),
            configuration_revision=(
                CONTROL_MUTATION_GUARD_COMPLETION_CONFIGURATION_REVISION
            ),
            acceptance_criteria=CONTROL_MUTATION_GUARD_ACCEPTANCE_CRITERIA,
            required_exhaustive_receipts=(
                CONTROL_MUTATION_GUARD_REQUIRED_EXHAUSTIVE_RECEIPTS
            ),
            quorum_evidence_type=ControlMutationCompletionQuorumEvidence,
            operational_complete=operational_complete,
            current_state=current_state,
            evidence=evidence,
            tasks_complete=tasks_complete,
            coverage=coverage,
            analyzer_health=analyzer_health,
            exhaustion_quorum=exhaustion_quorum,
            child_goals=child_goals,
            now=now,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
            analysis_inconclusive=analysis_inconclusive,
            blocked_reason=blocked_reason,
        )

    def _payload(self) -> dict[str, Any]:
        assert isinstance(self.request, OperationRequest)
        assert isinstance(self.result, OperationResult)
        assert isinstance(self.replay_result, OperationResult)
        assert isinstance(self.execution, MutationGuardExecutionObservation)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "requirement_id": self.requirement_id,
            "repository_tree": self.repository_tree,
            "objective_id": self.objective_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "request": self.request.to_record(),
            "result": self.result.to_record(),
            "replay_result": self.replay_result.to_record(),
            "execution": self.execution.to_record(),
            "rejections": tuple(item.to_record() for item in self.rejections),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlMutationGuardEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "requirement_id",
                "repository_tree",
                "objective_id",
                "policy_id",
                "policy_revision",
                "request",
                "result",
                "replay_result",
                "execution",
                "rejections",
                "content_id",
            },
            "control mutation guard evidence",
        )
        result = cls(
            requirement_id=payload.get("requirement_id", ""),
            repository_tree=payload.get("repository_tree", ""),
            objective_id=payload.get("objective_id", ""),
            policy_id=payload.get("policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            request=payload.get("request") or {},
            result=payload.get("result") or {},
            replay_result=payload.get("replay_result") or {},
            execution=payload.get("execution") or {},
            rejections=payload.get("rejections", ()),
        )
        _identity(payload, result.content_id, "control mutation guard evidence")
        return result


@dataclass(frozen=True)
class ControlMutationCompletionMemberHealth(_ControlCanonicalContract):
    """Explicit completion-safety attestation for one G104 receipt."""

    SCHEMA: ClassVar[str] = CONTROL_MUTATION_COMPLETION_MEMBER_HEALTH_SCHEMA

    member_id: str
    receipt_cid: str
    healthy: bool
    safe_for_completion_reasoning: bool

    def __post_init__(self) -> None:
        for name in ("member_id", "receipt_cid"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("healthy", "safe_for_completion_reasoning"):
            if not isinstance(getattr(self, name), bool):
                raise ControlContractError(f"{name} must be a boolean")
        _bounded_record(self, "control mutation completion member health")

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "member_id": self.member_id,
            "receipt_cid": self.receipt_cid,
            "healthy": self.healthy,
            "safe_for_completion_reasoning": (
                self.safe_for_completion_reasoning
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlMutationCompletionMemberHealth":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "member_id",
                "receipt_cid",
                "healthy",
                "safe_for_completion_reasoning",
                "content_id",
            },
            "control mutation completion member health",
        )
        result = cls(
            member_id=payload.get("member_id", ""),
            receipt_cid=payload.get("receipt_cid", ""),
            healthy=payload.get("healthy", False),
            safe_for_completion_reasoning=payload.get(
                "safe_for_completion_reasoning", False
            ),
        )
        _identity(
            payload,
            result.content_id,
            "control mutation completion member health",
        )
        return result


@dataclass(frozen=True)
class ControlMutationCompletionQuorumEvidence(_ControlCanonicalContract):
    """Bind a generic exhaustive quorum to one G104 mutation witness."""

    SCHEMA: ClassVar[str] = (
        CONTROL_MUTATION_COMPLETION_QUORUM_EVIDENCE_SCHEMA
    )

    validation_policy_id: str
    policy_revision: str
    operational_receipt_id: str
    quorum: Any
    member_health: tuple[
        ControlMutationCompletionMemberHealth | Mapping[str, Any], ...
    ]
    objective_id: str = CONTROL_MUTATION_GUARD_OBJECTIVE_ID
    requirement_id: str = CONTROL_MUTATION_GUARD_REQUIREMENT_ID

    def __post_init__(self) -> None:
        from ..objectives.scan_receipts import ExhaustionQuorumResult

        for name in (
            "validation_policy_id",
            "policy_revision",
            "operational_receipt_id",
            "objective_id",
            "requirement_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.objective_id != CONTROL_MUTATION_GUARD_OBJECTIVE_ID:
            raise ControlContractError(
                "completion quorum objective_id is not ASI-G104"
            )
        if self.requirement_id != CONTROL_MUTATION_GUARD_REQUIREMENT_ID:
            raise ControlContractError(
                "completion quorum requirement_id is not the ASI-G104 requirement"
            )
        quorum = self.quorum
        if not isinstance(quorum, ExhaustionQuorumResult):
            if not isinstance(quorum, Mapping):
                raise ControlContractError(
                    "completion quorum must contain an ExhaustionQuorumResult"
                )
            try:
                quorum = ExhaustionQuorumResult.from_dict(quorum)
            except (TypeError, ValueError) as exc:
                raise ControlContractError(
                    "completion quorum is malformed"
                ) from exc
        object.__setattr__(self, "quorum", quorum)
        member_health = _coerce_tuple(
            self.member_health,
            ControlMutationCompletionMemberHealth,
            ControlMutationCompletionMemberHealth.from_dict,
            "member_health",
        )
        expected_members = {
            (member.member_id, member.receipt_cid)
            for member in quorum.members
        }
        attested_members = {
            (member.member_id, member.receipt_cid)
            for member in member_health
        }
        if (
            len(member_health) != len(attested_members)
            or attested_members != expected_members
        ):
            raise ControlContractError(
                "completion member health must cover every quorum receipt exactly"
            )
        if not all(
            member.healthy and member.safe_for_completion_reasoning
            for member in member_health
        ):
            raise ControlContractError(
                "every exhaustive receipt must be explicitly healthy and "
                "safe for completion reasoning"
            )
        object.__setattr__(
            self,
            "member_health",
            tuple(sorted(member_health, key=lambda item: item.member_id)),
        )
        _bounded_record(self, "control mutation completion quorum evidence")

    def _payload(self) -> dict[str, Any]:
        quorum = self.quorum.to_dict()
        quorum.pop("confidence", None)
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "requirement_id": self.requirement_id,
            "objective_id": self.objective_id,
            "validation_policy_id": self.validation_policy_id,
            "policy_revision": self.policy_revision,
            "operational_receipt_id": self.operational_receipt_id,
            "quorum": quorum,
            "member_health": tuple(
                item.to_record() for item in self.member_health
            ),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ControlMutationCompletionQuorumEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "requirement_id",
                "objective_id",
                "validation_policy_id",
                "policy_revision",
                "operational_receipt_id",
                "quorum",
                "member_health",
                "content_id",
            },
            "control mutation completion quorum evidence",
        )
        result = cls(
            requirement_id=payload.get("requirement_id", ""),
            objective_id=payload.get("objective_id", ""),
            validation_policy_id=payload.get("validation_policy_id", ""),
            policy_revision=payload.get("policy_revision", ""),
            operational_receipt_id=payload.get("operational_receipt_id", ""),
            quorum=payload.get("quorum") or {},
            member_health=payload.get("member_health", ()),
        )
        _identity(
            payload,
            result.content_id,
            "control mutation completion quorum evidence",
        )
        return result


@dataclass(frozen=True)
class LifecycleCommand(_ControlCanonicalContract):
    """A typed lifecycle intent, suitable for conversion to a request."""

    SCHEMA: ClassVar[str] = LIFECYCLE_COMMAND_SCHEMA

    action: LifecycleAction
    target_id: str
    reason: str
    requested_state: str = ""
    dry_run: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action", _enum(self.action, LifecycleAction, "action")
        )
        object.__setattr__(self, "target_id", _text(self.target_id, "target_id"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self,
            "requested_state",
            _text(self.requested_state, "requested_state", required=False),
        )
        if not isinstance(self.dry_run, bool):
            raise ControlContractError("dry_run must be a boolean")
        _bounded_record(self, "lifecycle command")

    @property
    def operation(self) -> Operation:
        return self.action.operation

    @property
    def authority(self) -> OperationAuthority:
        return (
            OperationAuthority.PROPOSAL
            if self.dry_run
            else OperationAuthority.MUTATION
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_CONTRACT_VERSION,
            "action": self.action,
            "operation": self.operation,
            "authority": self.authority,
            "target_id": self.target_id,
            "reason": self.reason,
            "requested_state": self.requested_state,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LifecycleCommand":
        _schema(payload, cls.SCHEMA)
        _reject_unknown(
            payload,
            {
                "schema",
                "schema_version",
                "contract_version",
                "action",
                "operation",
                "authority",
                "target_id",
                "reason",
                "requested_state",
                "dry_run",
                "content_id",
            },
            "lifecycle command",
        )
        result = cls(
            action=payload.get("action", payload.get("operation", "")),
            target_id=payload.get("target_id", ""),
            reason=payload.get("reason", ""),
            requested_state=payload.get("requested_state", ""),
            dry_run=payload.get("dry_run", False),
        )
        claimed_operation = payload.get("operation")
        if claimed_operation not in (None, "") and _operation(
            claimed_operation
        ) is not result.operation:
            raise ControlContractError(
                "lifecycle operation does not match its action"
            )
        claimed_authority = payload.get("authority")
        if claimed_authority not in (None, "") and _authority(
            claimed_authority
        ) is not result.authority:
            raise AuthorityViolationError(
                "lifecycle authority does not match dry_run"
            )
        _identity(payload, result.content_id, "lifecycle command")
        return result


def operation_request_json_schema(
    operation: Operation | str | None = None,
) -> dict[str, Any]:
    """Return the shared JSON Schema advertised by CLI and MCP adapters.

    JSON Schema is an early validation aid, not an authorization decision.
    :class:`OperationRequest` remains the authoritative parser and performs
    cross-field identity, effect, idempotency, authorization, and lease checks.
    """

    selected = _operation(operation) if operation is not None else None
    operation_values = (
        [selected.value]
        if selected is not None
        else [item.value for item in sorted(Operation, key=lambda item: item.value)]
    )
    string_id = {"type": "string", "minLength": 1, "maxLength": 65536}
    root = {
        "type": "string",
        "minLength": 1,
        "maxLength": 65536,
        "pattern": "^/",
    }
    parameter_schema: dict[str, Any] = {"type": "object"}
    if selected in PLAN_CONTROL_OPERATIONS:
        allowed_parameters = _PLAN_CONTROL_PARAMETER_FIELDS[selected]
        object_fields = {
            "plan_request",
            "materials",
            "live_state",
            "apply_request",
            "prompt_source",
            "target",
        }
        path_fields = {"markdown_path", "duckdb_path"}
        parameter_properties: dict[str, Any] = {}
        for name in sorted(allowed_parameters):
            if name in object_fields:
                parameter_properties[name] = {
                    "type": "object",
                    "additionalProperties": True,
                }
            elif name in path_fields:
                parameter_properties[name] = {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 65536,
                    "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$)).+",
                }
            elif name == "expected_revision":
                parameter_properties[name] = {
                    "type": "integer",
                    "minimum": 0,
                }
            else:
                parameter_properties[name] = {
                    "type": "string",
                    "minLength": 1,
                }
        parameter_schema = {
            "type": "object",
            "properties": parameter_properties,
            "additionalProperties": False,
        }
    elif selected in PROMPT_CONTROL_OPERATIONS:
        allowed_parameters = _PROMPT_CONTROL_PARAMETER_FIELDS[selected]
        integer_fields = {
            "action_index",
            "deadline_ms",
            "expected_revision",
            "health_window_ms",
            "max_actions",
        }
        boolean_fields = {"allow_llm_fallback"}
        path_fields = {"markdown_path", "duckdb_path"}
        # Nested objects (apply_request) are open mappings validated by domain.
        object_fields = {"apply_request", "target", "prompt_source"}
        parameter_properties: dict[str, Any] = {
            name: (
                {"type": "integer", "minimum": 0}
                if name in integer_fields
                else (
                    {"type": "boolean"}
                    if name in boolean_fields
                    else (
                        {"type": "object", "additionalProperties": True}
                        if name in object_fields
                        else (
                            {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 65536,
                                "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$)).+",
                            }
                            if name in path_fields
                            else {"type": "string", "minLength": 1}
                        )
                    )
                )
            )
            for name in sorted(
                allowed_parameters.difference({"target", "prompt_source"})
            )
        }
        target_fields = {
            Operation.WORKFLOW_PREVIEW: ("repository_id", "tree_id"),
            Operation.WORKFLOW_MATERIALIZE: (
                "repository_id",
                "tree_id",
                "preview_ref",
            ),
            Operation.RESTART: ("repository_id",),
            Operation.RESCUE_PREVIEW: (
                "repository_id",
                "tree_id",
                "incident_cid",
            ),
            Operation.RESCUE: (
                "repository_id",
                "tree_id",
                "incident_cid",
            ),
        }[selected]
        parameter_properties["target"] = {
            "type": "object",
            "properties": {
                name: {"type": "string", "minLength": 1}
                for name in target_fields
            },
            "additionalProperties": False,
        }
        if "directory" in allowed_parameters:
            parameter_properties["directory"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 65536,
                "pattern": "^(?!.*(?:^|/)\\.\\.(?:/|$)).+",
            }
        if "prompt_source" in allowed_parameters:
            parameter_properties["prompt_source"] = {
                "type": "object",
                "properties": {
                    name: {"type": "string"}
                    for name in sorted(_PROMPT_SOURCE_FIELDS)
                },
                "additionalProperties": False,
            }
        parameter_schema = {
            "type": "object",
            "properties": parameter_properties,
            "required": {
                Operation.WORKFLOW_PREVIEW: [
                    "directory",
                    "prompt_source",
                ],
                Operation.WORKFLOW_MATERIALIZE: [
                    "preview_ref",
                    "preview_root",
                    "preview_repository_id",
                    "preview_tree_id",
                    "preview_objective_id",
                    "preview_objective_revision",
                    "preview_policy_id",
                    "preview_policy_revision",
                ],
                Operation.RESCUE_PREVIEW: [
                    "incident_cid",
                    "incident_root",
                    "incident_repository_id",
                    "incident_tree_id",
                    "incident_objective_id",
                    "incident_objective_revision",
                    "incident_policy_id",
                    "incident_policy_revision",
                ],
                Operation.RESCUE: [
                    "incident_cid",
                    "incident_root",
                    "incident_repository_id",
                    "incident_tree_id",
                    "incident_objective_id",
                    "incident_objective_revision",
                    "incident_policy_id",
                    "incident_policy_revision",
                    "rescue_plan_cid",
                    "rescue_plan_root",
                    "rescue_plan_incident_cid",
                    "rescue_plan_tree_id",
                ],
            }.get(selected, []),
            "additionalProperties": False,
        }
    properties: dict[str, Any] = {
        "schema": {"const": OPERATION_REQUEST_SCHEMA},
        "schema_version": {"type": "integer", "const": CONTROL_CONTRACT_VERSION},
        "contract_version": {
            "type": "integer",
            "const": CONTROL_CONTRACT_VERSION,
        },
        "operation": (
            {"const": selected.value}
            if selected is not None
            else {"type": "string", "enum": operation_values}
        ),
        "authority": {
            "type": "string",
            "enum": [item.value for item in OperationAuthority],
        },
        "effective_authority": {
            "type": "string",
            "enum": [item.value for item in OperationAuthority],
        },
        "repository_root": root,
        "state_root": root,
        "repository_id": string_id,
        "tree_id": string_id,
        "objective_id": string_id,
        "objective_revision": string_id,
        "policy_id": string_id,
        "policy_revision": string_id,
        "caller": string_id,
        "bounds": {"type": "object"},
        "expected_effects": {"type": "array", "maxItems": 64},
        "parameters": parameter_schema,
        "dry_run": {"type": "boolean"},
        "idempotency": {"type": ["object", "null"]},
        "idempotency_key": {"type": "string"},
        "authorization": {"type": ["object", "null"]},
        "lease_id": {"type": "string"},
        "fencing_epoch": {"type": ["integer", "null"], "minimum": 0},
        "content_id": {"type": "string"},
    }
    required = [
        "operation",
        "repository_root",
        "state_root",
        "repository_id",
        "tree_id",
        "objective_id",
        "objective_revision",
        "policy_id",
        "policy_revision",
        "caller",
    ]
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            f"{OPERATION_REQUEST_SCHEMA}#{selected.value}"
            if selected is not None
            else OPERATION_REQUEST_SCHEMA
        ),
        "title": "Agent supervisor operation request",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if selected is not None and selected.mutating:
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"dry_run": {"const": False}},
                },
                "then": {
                    "required": [
                        "expected_effects",
                        "idempotency",
                        "authorization",
                        "lease_id",
                        "fencing_epoch",
                    ]
                },
            }
        ]
    return schema


def operation_result_json_schema(
    operation: Operation | str | None = None,
) -> dict[str, Any]:
    """Return the stable result-envelope JSON Schema for every surface."""

    selected = _operation(operation) if operation is not None else None
    operation_property: dict[str, Any] = (
        {"const": selected.value}
        if selected is not None
        else {
            "type": "string",
            "enum": [
                item.value
                for item in sorted(Operation, key=lambda item: item.value)
            ],
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            f"{OPERATION_RESULT_SCHEMA}#{selected.value}"
            if selected is not None
            else OPERATION_RESULT_SCHEMA
        ),
        "title": "Agent supervisor operation result",
        "type": "object",
        "properties": {
            "schema": {"const": OPERATION_RESULT_SCHEMA},
            "schema_version": {
                "type": "integer",
                "const": CONTROL_CONTRACT_VERSION,
            },
            "contract_version": {
                "type": "integer",
                "const": CONTROL_CONTRACT_VERSION,
            },
            "request_id": {"type": "string", "minLength": 1},
            "operation": operation_property,
            "authority": {
                "type": "string",
                "enum": [item.value for item in OperationAuthority],
            },
            "status": {
                "type": "string",
                "enum": [item.value for item in OperationStatus],
            },
            "repository_id": {"type": "string", "minLength": 1},
            "tree_id": {"type": "string", "minLength": 1},
            "objective_id": {"type": "string", "minLength": 1},
            "policy_id": {"type": "string", "minLength": 1},
            "caller": {"type": "string", "minLength": 1},
            "bounds": {"type": "object"},
            "data": {"type": "object"},
            "effects": {"type": "array"},
            "error": {"type": ["object", "null"]},
            "preview": {"type": ["object", "null"]},
            "idempotency_key": {"type": "string"},
            "audit_receipt_id": {"type": "string"},
            "content_id": {"type": "string", "minLength": 1},
        },
        "required": [
            "schema",
            "contract_version",
            "request_id",
            "operation",
            "authority",
            "status",
            "repository_id",
            "tree_id",
            "objective_id",
            "policy_id",
            "caller",
            "bounds",
            "data",
            "effects",
            "error",
            "preview",
            "idempotency_key",
            "audit_receipt_id",
            "content_id",
        ],
        "additionalProperties": False,
    }


# This singleton is assembled solely from local immutable values after the
# schema producers above exist.  It imports no optional provider, resolves no
# backend, starts no process, reads no file, and is safe for discovery.
OPERATION_CATALOG_V2: Final[OperationCatalog] = _build_operation_catalog()
CONTROL_OPERATION_CATALOG: Final[OperationCatalog] = OPERATION_CATALOG_V2
OPERATION_CATALOG: Final[OperationCatalog] = OPERATION_CATALOG_V2
CONTROL_CATALOG: Final[OperationCatalog] = OPERATION_CATALOG_V2
CONTROL_CAPABILITY_CATALOG: Final[OperationCatalog] = OPERATION_CATALOG_V2
DEFAULT_CONTROL_CATALOG: Final[OperationCatalog] = OPERATION_CATALOG_V2

# APMC-017 autonomy surface names.  These are not a second Operation catalog;
# they name the bounded reads/mutations the autonomy adapters must expose
# through SupervisorControlService without minting authority.
AUTONOMY_CONTROL_INTERFACE: Final[str] = "AutonomyControlSurface@1"
AUTONOMY_READ_OPERATION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "capabilities",
        "status",
        "metrics",
        "graph",
        "questions",
        "budget",
        "experience",
        "route_policy",
        "distillation",
        "repair_history",
        "escalations",
        "shadow",
    }
)
AUTONOMY_MUTATION_OPERATION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "pause",
        "resume",
        "set_level",
        "approve_policy",
        "reject_policy",
        "rollback_policy",
        "approve_repair",
        "cancel",
        "bind_escalation",
    }
)
AUTONOMY_CONTROL_OPERATION_NAMES: Final[frozenset[str]] = (
    AUTONOMY_READ_OPERATION_NAMES | AUTONOMY_MUTATION_OPERATION_NAMES
)


def canonical_control_json_bytes(value: Any) -> bytes:
    """Return canonical DAG-JSON bytes for a control value."""

    return canonical_json_bytes(value)


def decode_operation_request(
    payload: Mapping[str, Any],
) -> OperationRequest:
    """Run the canonical pre-resolution request boundary used by all surfaces.

    Real mutations that are structurally unauthorized, unscoped, unfenced,
    stale-bound, path-escaping, or missing declared effects raise here before
    a Python backend, CLI service factory, or MCP service resolver can run.
    Deployment freshness and allowlist checks then converge on the control
    service's pre-dispatch boundary.
    """

    if not isinstance(payload, Mapping):
        raise ControlContractError(
            "operation request payload must contain an object"
        )
    return OperationRequest.from_dict(payload)


def operation_authority(operation: Operation | str) -> OperationAuthority:
    """Return the registry authority for an operation, rejecting unknown IDs."""

    return _operation(operation).authority


# ---------------------------------------------------------------------------
# ASI-169 supervisor usage-governance control contracts
# ---------------------------------------------------------------------------
#
# Usage controls are a discoverable, transport-neutral surface bound to the
# shared supervisor control revisions.  They deliberately do not widen the
# closed Operation catalog; Python, CLI, and MCP adapters project the same
# schema/result/error vocabulary through ProviderUsageControl.

SUPERVISOR_USAGE_CONTROL_REQUIREMENT_ID: Final[str] = (
    "requirement:supervisor-usage-control-conformance.v1"
)
SUPERVISOR_USAGE_CONTROL_GOAL_ID: Final[str] = "ASI-G530"
SUPERVISOR_USAGE_CONTROL_SCHEMA_VERSION: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/usage-control@1"
)
SUPERVISOR_USAGE_CONTROL_TOOL_SCHEMA_VERSION: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/usage-control-tool@1"
)
SUPERVISOR_USAGE_CONTROL_CATALOG_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/usage-control-catalog@1"
)
SUPERVISOR_USAGE_METRICS_REQUIREMENT_ID: Final[str] = (
    "requirement:supervisor-usage-metrics.v1"
)
SUPERVISOR_USAGE_METRICS_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/usage-governance-metrics@1"
)
SUPERVISOR_USAGE_METRICS_SCHEMA_VERSION: Final[int] = 1

# Distinct authorities — read/detail/admin never share a token.
SUPERVISOR_USAGE_READ_AUTHORITY: Final[str] = "agent_supervisor.usage/read"
SUPERVISOR_USAGE_READ_DETAIL_AUTHORITY: Final[str] = (
    "agent_supervisor.usage/read_detail"
)
SUPERVISOR_USAGE_ADMIN_AUTHORITY: Final[str] = "agent_supervisor.usage/admin"
SUPERVISOR_USAGE_BUDGET_AUTHORITY: Final[str] = "agent_supervisor.usage/budget"
SUPERVISOR_USAGE_POLICY_AUTHORITY: Final[str] = "agent_supervisor.usage/policy"
SUPERVISOR_USAGE_CORRECTION_AUTHORITY: Final[str] = (
    "agent_supervisor.usage/correction"
)
SUPERVISOR_USAGE_RESET_AUTHORITY: Final[str] = "agent_supervisor.usage/reset"

MAX_USAGE_CONTROL_PAGE_SIZE: Final[int] = 100
MAX_USAGE_CONTROL_RECEIPTS: Final[int] = 256
MAX_USAGE_CONTROL_AUDIT: Final[int] = 512
MAX_USAGE_CONTROL_FILTERS: Final[int] = 256
MAX_USAGE_CONTROL_REASON_CODES: Final[int] = 32
MAX_USAGE_CONTROL_STRING: Final[int] = 256
MAX_USAGE_CONTROL_IDEMPOTENCY_KEY: Final[int] = 128
MAX_USAGE_CONTROL_EXPECTED_EFFECTS: Final[int] = 32
MAX_USAGE_CONTROL_BUDGET_LIMITS: Final[int] = 64

USAGE_HEADROOM_BANDS: Final[tuple[str, ...]] = (
    "unknown",
    "exhausted",
    "critical",
    "low",
    "medium",
    "high",
    "unlimited",
)

SUPERVISOR_USAGE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "unauthorized",
        "read_denied",
        "detail_denied",
        "admin_denied",
        "budget_authority_denied",
        "policy_authority_denied",
        "correction_authority_denied",
        "reset_authority_denied",
        "invalid_request",
        "invalid_filter",
        "invalid_cursor",
        "cursor_revision_mismatch",
        "stale_snapshot",
        "stale_fence",
        "revision_mismatch",
        "idempotency_conflict",
        "idempotency_replay",
        "expected_effects_exceeded",
        "lease_required",
        "fence_required",
        "mutation_denied_model_output",
        "mutation_denied_remote_peer",
        "parent_budget_raise_denied",
        "scope_not_found",
        "usage_unavailable",
        "limit_exhausted",
        "cooling_down",
        "store_unhealthy",
        "budget_rejected",
        "policy_rejected",
        "correction_rejected",
        "reset_rejected",
        "side_effect_forbidden",
        "unbounded_page",
        "completion_not_authoritative",
    }
)

# Forbidden high-cardinality metric labels (shared with scheduler projection).
SUPERVISOR_USAGE_FORBIDDEN_METRIC_LABELS: Final[frozenset[str]] = frozenset(
    {
        "request",
        "request_id",
        "credential",
        "credential_id",
        "credential_pseudonym",
        "tenant",
        "tenant_id",
        "alias",
        "model",
        "model_id",
        "model_string",
        "model_alias",
        "endpoint",
        "endpoint_uri",
        "endpoint_url",
        "url",
        "account",
        "account_pseudonym",
        "user",
        "session",
        "prompt",
        "media",
        "output",
    }
)


class SupervisorUsageAuthority(str, Enum):
    """Distinct usage-governance authorities."""

    READ = SUPERVISOR_USAGE_READ_AUTHORITY
    READ_DETAIL = SUPERVISOR_USAGE_READ_DETAIL_AUTHORITY
    ADMIN = SUPERVISOR_USAGE_ADMIN_AUTHORITY
    BUDGET = SUPERVISOR_USAGE_BUDGET_AUTHORITY
    POLICY = SUPERVISOR_USAGE_POLICY_AUTHORITY
    CORRECTION = SUPERVISOR_USAGE_CORRECTION_AUTHORITY
    RESET = SUPERVISOR_USAGE_RESET_AUTHORITY


class SupervisorUsageControlOperation(str, Enum):
    """Closed usage-governance operations (not Operation catalog members)."""

    STATUS = "usage_status"
    HEALTH = "usage_health"
    BUDGETS = "usage_budgets"
    HEADROOM = "usage_headroom"
    RESERVATIONS = "usage_reservations"
    RECEIPTS = "usage_receipts"
    ROUTE_PREVIEW = "usage_route_preview"
    BLOCKED_WORK = "usage_blocked_work"
    NEXT_ELIGIBLE = "usage_next_eligible"
    ADAPTER_CAPABILITIES = "usage_adapter_capabilities"
    SET_BUDGET = "usage_set_budget"
    SET_POLICY = "usage_set_policy"
    CORRECT = "usage_correct"
    RESET = "usage_reset"


USAGE_CONTROL_READ_OPERATIONS: Final[frozenset[SupervisorUsageControlOperation]] = (
    frozenset(
        {
            SupervisorUsageControlOperation.STATUS,
            SupervisorUsageControlOperation.HEALTH,
            SupervisorUsageControlOperation.BUDGETS,
            SupervisorUsageControlOperation.HEADROOM,
            SupervisorUsageControlOperation.RESERVATIONS,
            SupervisorUsageControlOperation.RECEIPTS,
            SupervisorUsageControlOperation.ROUTE_PREVIEW,
            SupervisorUsageControlOperation.BLOCKED_WORK,
            SupervisorUsageControlOperation.NEXT_ELIGIBLE,
            SupervisorUsageControlOperation.ADAPTER_CAPABILITIES,
        }
    )
)
USAGE_CONTROL_MUTATION_OPERATIONS: Final[
    frozenset[SupervisorUsageControlOperation]
] = frozenset(
    {
        SupervisorUsageControlOperation.SET_BUDGET,
        SupervisorUsageControlOperation.SET_POLICY,
        SupervisorUsageControlOperation.CORRECT,
        SupervisorUsageControlOperation.RESET,
    }
)
USAGE_CONTROL_PREVIEW_OPERATIONS: Final[
    frozenset[SupervisorUsageControlOperation]
] = frozenset({SupervisorUsageControlOperation.ROUTE_PREVIEW})

# Mutation operations require a distinct authority (not just generic admin).
USAGE_CONTROL_MUTATION_AUTHORITIES: Final[
    Mapping[SupervisorUsageControlOperation, str]
] = MappingProxyType(
    {
        SupervisorUsageControlOperation.SET_BUDGET: SUPERVISOR_USAGE_BUDGET_AUTHORITY,
        SupervisorUsageControlOperation.SET_POLICY: SUPERVISOR_USAGE_POLICY_AUTHORITY,
        SupervisorUsageControlOperation.CORRECT: SUPERVISOR_USAGE_CORRECTION_AUTHORITY,
        SupervisorUsageControlOperation.RESET: SUPERVISOR_USAGE_RESET_AUTHORITY,
    }
)


def usage_control_authorities() -> dict[str, str]:
    """Stable authority vocabulary for Python / CLI / MCP parity."""

    return {
        "read": SUPERVISOR_USAGE_READ_AUTHORITY,
        "read_detail": SUPERVISOR_USAGE_READ_DETAIL_AUTHORITY,
        "admin": SUPERVISOR_USAGE_ADMIN_AUTHORITY,
        "budget": SUPERVISOR_USAGE_BUDGET_AUTHORITY,
        "policy": SUPERVISOR_USAGE_POLICY_AUTHORITY,
        "correction": SUPERVISOR_USAGE_CORRECTION_AUTHORITY,
        "reset": SUPERVISOR_USAGE_RESET_AUTHORITY,
    }


def usage_control_reason_codes() -> tuple[str, ...]:
    return tuple(sorted(SUPERVISOR_USAGE_REASON_CODES))


def usage_control_operations() -> tuple[str, ...]:
    return tuple(
        sorted(item.value for item in SupervisorUsageControlOperation)
    )


def usage_control_mutation_operations() -> tuple[str, ...]:
    return tuple(sorted(item.value for item in USAGE_CONTROL_MUTATION_OPERATIONS))


def usage_control_read_operations() -> tuple[str, ...]:
    return tuple(sorted(item.value for item in USAGE_CONTROL_READ_OPERATIONS))


def discover_usage_control_catalog() -> dict[str, Any]:
    """Side-effect-free discovery of the usage-governance operation surface.

    Returns schema/result/error-equivalent operation descriptors bound to the
    supervisor usage control requirement and catalog revision identity.  Does
    not reserve, refresh, probe, invoke, or mutate.
    """

    operations: list[dict[str, Any]] = []
    for operation in sorted(
        SupervisorUsageControlOperation, key=lambda item: item.value
    ):
        mutating = operation in USAGE_CONTROL_MUTATION_OPERATIONS
        preview = operation in USAGE_CONTROL_PREVIEW_OPERATIONS
        authority = (
            USAGE_CONTROL_MUTATION_AUTHORITIES[operation]
            if mutating
            else SUPERVISOR_USAGE_READ_AUTHORITY
        )
        operations.append(
            {
                "operation": operation.value,
                "authority": authority,
                "mutating": mutating,
                "preview": preview,
                "side_effect_free": not mutating,
                "requires_idempotency": mutating,
                "requires_lease": mutating,
                "requires_fence": mutating,
                "requires_expected_revision": mutating,
                "requires_expected_effects": mutating,
                "pagination": operation
                in {
                    SupervisorUsageControlOperation.STATUS,
                    SupervisorUsageControlOperation.BUDGETS,
                    SupervisorUsageControlOperation.RESERVATIONS,
                    SupervisorUsageControlOperation.RECEIPTS,
                    SupervisorUsageControlOperation.BLOCKED_WORK,
                    SupervisorUsageControlOperation.ADAPTER_CAPABILITIES,
                },
                "default_redacts_credential_account_tenant": True,
                "completion_authoritative": False,
            }
        )
    payload = {
        "schema": SUPERVISOR_USAGE_CONTROL_CATALOG_SCHEMA,
        "schema_version": SUPERVISOR_USAGE_CONTROL_SCHEMA_VERSION,
        "tool_schema_version": SUPERVISOR_USAGE_CONTROL_TOOL_SCHEMA_VERSION,
        "requirement_id": SUPERVISOR_USAGE_CONTROL_REQUIREMENT_ID,
        "goal_id": SUPERVISOR_USAGE_CONTROL_GOAL_ID,
        "control_catalog_version": CONTROL_CATALOG_VERSION,
        "operations": operations,
        "authorities": usage_control_authorities(),
        "reason_codes": list(usage_control_reason_codes()),
        "headroom_bands": list(USAGE_HEADROOM_BANDS),
        "forbidden_metric_labels": sorted(SUPERVISOR_USAGE_FORBIDDEN_METRIC_LABELS),
        "completion_authoritative": False,
        "operational_evidence_only": True,
    }
    return MappingProxyType(payload)  # type: ignore[return-value]


def usage_headroom_band(
    available: Any = None,
    ceiling: Any = None,
    *,
    state: str | None = None,
) -> str:
    """Map typed headroom into a low-cardinality band label."""

    if state in {"exhausted"}:
        return "exhausted"
    if state in {"unknown", None} and available is None and ceiling is None:
        return "unknown"
    if state == "unknown":
        return "unknown"

    def _kind_value(quantity: Any) -> tuple[str, int | None]:
        if quantity is None:
            return "unknown", None
        if isinstance(quantity, Mapping):
            kind = str(quantity.get("kind") or "unknown")
            value = quantity.get("value")
            try:
                return kind, (None if value is None else int(value))
            except (TypeError, ValueError):
                return kind, None
        kind_attr = getattr(quantity, "kind", None)
        kind = (
            kind_attr.value
            if hasattr(kind_attr, "value")
            else str(kind_attr or "unknown")
        )
        value = getattr(quantity, "value", None)
        try:
            return kind, (None if value is None else int(value))
        except (TypeError, ValueError):
            return kind, None

    avail_kind, avail_value = _kind_value(available)
    ceil_kind, ceil_value = _kind_value(ceiling)
    if ceil_kind == "unlimited":
        return "unlimited"
    if ceil_kind == "unknown" or avail_kind == "unknown":
        return "unknown"
    if avail_kind == "unlimited":
        return "unlimited"
    if ceil_value is None or ceil_value <= 0:
        return "exhausted"
    if avail_value is None or avail_value <= 0:
        return "exhausted"
    ratio = avail_value / float(ceil_value)
    if ratio < 0.10:
        return "critical"
    if ratio < 0.25:
        return "low"
    if ratio < 0.50:
        return "medium"
    return "high"


ControlLimits = ControlBounds
RequestBounds = ControlBounds
OperationName = Operation
ControlOperation = Operation
AuthorityLevel = OperationAuthority
ControlError = OperationError
TypedOperationError = OperationError
AuthorizationResult = AuthorizationDecision
IdempotencyContract = IdempotencyKey
OperationEffect = ExpectedEffect
OperationEffectClaim = EffectClaim
ControlContractValidationError = ControlContractError


__all__ = [
    "AUTHORIZATION_DECISION_SCHEMA",
    "CAPABILITY_REPORT_SCHEMA",
    "CONTROL_CAPABILITY_CATALOG",
    "CONTROL_CAPABILITY_RESOLUTION_SCHEMA",
    "CONTROL_CATALOG_NEGOTIATION_SCHEMA",
    "CONTROL_CATALOG_VERSION",
    "CONTROL_CATALOG",
    "CONTRACT_VERSION",
    "CONTROL_BOUNDS_SCHEMA",
    "CONTROL_CONTRACT_VERSION",
    "CONTROL_DISCOVERY_ISOLATION_REQUIREMENT_ID",
    "CONTROL_DISCOVERY_MANIFEST_SCHEMA",
    "CONTROL_DISCOVERY_OBSERVATION_SCHEMA",
    "CONTROL_DISCOVERY_RUNTIME_STATE_SCHEMA",
    "CONTROL_DISCOVERY_COMPLETION_QUORUM_EVIDENCE_SCHEMA",
    "CONTROL_DISCOVERY_COMPLETION_MEMBER_HEALTH_SCHEMA",
    "CONTROL_DISCOVERY_SAFETY_ACCEPTANCE_CRITERIA",
    "CONTROL_DISCOVERY_SAFETY_COMPLETION_ANALYZER_VERSION",
    "CONTROL_DISCOVERY_SAFETY_COMPLETION_CONFIGURATION_REVISION",
    "CONTROL_DISCOVERY_SAFETY_EVIDENCE_SCHEMA",
    "CONTROL_DISCOVERY_SAFETY_OBJECTIVE_ID",
    "CONTROL_DISCOVERY_SAFETY_OBJECTIVE_REVISION",
    "CONTROL_DISCOVERY_SAFETY_REQUIRED_EXHAUSTIVE_RECEIPTS",
    "CONTROL_DISCOVERY_SAFETY_REQUIREMENT_ID",
    "CONTROL_MUTATION_COMPLETION_MEMBER_HEALTH_SCHEMA",
    "CONTROL_MUTATION_COMPLETION_QUORUM_EVIDENCE_SCHEMA",
    "CONTROL_MUTATION_GUARD_ACCEPTANCE_CRITERIA",
    "CONTROL_MUTATION_GUARD_COMPLETION_ANALYZER_VERSION",
    "CONTROL_MUTATION_GUARD_COMPLETION_CONFIGURATION_REVISION",
    "CONTROL_MUTATION_GUARD_EVIDENCE_SCHEMA",
    "CONTROL_MUTATION_GUARD_OBJECTIVE_ID",
    "CONTROL_MUTATION_GUARD_OBJECTIVE_REVISION",
    "CONTROL_MUTATION_GUARD_REJECTION_SCENARIOS",
    "CONTROL_MUTATION_GUARD_REQUIRED_EXHAUSTIVE_RECEIPTS",
    "CONTROL_MUTATION_GUARD_REQUIREMENT_ID",
    "CONTROL_MUTATION_RUNTIME_STATE_SCHEMA",
    "CONTROL_MUTATION_AUDIT_RECEIPT_SCHEMA",
    "CONTROL_OPERATION_CATALOG",
    "CONTROL_OPERATION_CATALOG_SCHEMA",
    "CONTROL_OPERATION_DESCRIPTOR_SCHEMA",
    "CONTROL_PAGINATION_SCHEMA",
    "CONTROL_PROPOSAL_AUDIT_RECEIPT_SCHEMA",
    "CONTROL_QUERY_AUDIT_RECEIPT_SCHEMA",
    "CONTROL_SURFACE_PARITY_CASE_SCHEMA",
    "CONTROL_SURFACE_PARITY_ACCEPTANCE_CRITERIA",
    "CONTROL_SURFACE_PARITY_COMPLETION_ANALYZER_VERSION",
    "CONTROL_SURFACE_PARITY_COMPLETION_CONFIGURATION_REVISION",
    "CONTROL_SURFACE_PARITY_COMPLETION_MEMBER_HEALTH_SCHEMA",
    "CONTROL_SURFACE_PARITY_COMPLETION_QUORUM_EVIDENCE_SCHEMA",
    "CONTROL_SURFACE_PARITY_EVIDENCE_SCHEMA",
    "CONTROL_SURFACE_PARITY_OBJECTIVE_ID",
    "CONTROL_SURFACE_PARITY_OBJECTIVE_REVISION",
    "CONTROL_SURFACE_PARITY_REQUIRED_EXHAUSTIVE_RECEIPTS",
    "CONTROL_SURFACE_PARITY_REQUIREMENT_ID",
    "CONTROL_TARGET_DESCRIPTOR_SCHEMA",
    "DEFAULT_CONTROL_CATALOG",
    "AUTONOMY_CONTROL_INTERFACE",
    "AUTONOMY_CONTROL_OPERATION_NAMES",
    "AUTONOMY_MUTATION_OPERATION_NAMES",
    "AUTONOMY_READ_OPERATION_NAMES",
    "EVENT_CURSOR_SCHEMA",
    "EVENT_PAGE_SCHEMA",
    "OPERATION_CATALOG",
    "OPERATION_CATALOG_VERSION",
    "OPERATION_CATALOG_V2",
    "OPERATION_CATALOG_V2_REQUIREMENT_ID",
    "UNIFIED_CONTROL_ACCEPTANCE_CRITERIA",
    "UNIFIED_CONTROL_CHILD_GOAL_IDS",
    "UNIFIED_CONTROL_COMPLETION_ANALYZER_VERSION",
    "UNIFIED_CONTROL_COMPLETION_CONFIGURATION_REVISION",
    "UNIFIED_CONTROL_OBJECTIVE_ID",
    "UNIFIED_CONTROL_OBJECTIVE_REVISION",
    "UNIFIED_CONTROL_PRODUCING_TASK_IDS",
    "UNIFIED_CONTROL_REQUIRED_EXHAUSTIVE_RECEIPTS",
    "DRY_RUN_PREVIEW_SCHEMA",
    "EFFECT_CLAIM_SCHEMA",
    "EXPECTED_EFFECT_SCHEMA",
    "IDEMPOTENCY_KEY_SCHEMA",
    "LIFECYCLE_COMMAND_SCHEMA",
    "OPERATION_CAPABILITY_SCHEMA",
    "OPERATION_ERROR_SCHEMA",
    "OPERATION_AUTHORITIES",
    "OPERATION_REQUEST_SCHEMA",
    "OPERATION_RESULT_SCHEMA",
    "SCHEMA_VERSION",
    "PROPOSAL_OPERATIONS",
    "PROMPT_CONTROL_OPERATIONS",
    "PLAN_CONTROL_OPERATIONS",
    "PLAN_WORKFLOW_ALIAS_OPERATIONS",
    "READ_OPERATIONS",
    "MUTATION_OPERATIONS",
    "DOWNSTREAM_EFFECT_PREVIEW_OPERATIONS",
    "Authority",
    "AuthorityLevel",
    "AuthorityViolationError",
    "AuthorizationBindingError",
    "AuthorizationDecision",
    "AuthorizationResult",
    "AuthorizationVerdict",
    "CapabilityDegradation",
    "CapabilityUnavailableError",
    "CapabilityReport",
    "CapabilityResolution",
    "CatalogNegotiation",
    "CatalogVersionNegotiationError",
    "ControlBehaviorClass",
    "ControlBounds",
    "ControlBoundsError",
    "ControlContractError",
    "ControlContractValidationError",
    "ControlError",
    "ControlCapabilityCatalog",
    "ControlCatalog",
    "ControlEventCursor",
    "ControlDiscoveryIsolationEvidence",
    "ControlDiscoveryManifest",
    "ControlDiscoveryCompletionQuorumEvidence",
    "ControlDiscoveryCompletionMemberHealth",
    "ControlDiscoveryObservation",
    "ControlDiscoveryRuntimeState",
    "ControlDiscoverySafetyEvidence",
    "ControlLimits",
    "ControlOperationCatalog",
    "ControlOperationDescriptor",
    "ControlPagination",
    "ControlRoot",
    "ControlTargetDescriptor",
    "ControlTargetKind",
    "ControlMutationCompletionMemberHealth",
    "ControlMutationCompletionQuorumEvidence",
    "ControlMutationGuardEvidence",
    "ControlMutationRuntimeState",
    "ControlOperation",
    "ControlSurface",
    "ControlSurfaceParityCase",
    "ControlSurfaceParityCompletionMemberHealth",
    "ControlSurfaceParityCompletionQuorumEvidence",
    "ControlSurfaceParityEvidence",
    "DryRunPreview",
    "DegradationPolicy",
    "EffectClaim",
    "EffectKind",
    "ErrorCode",
    "EventCursor",
    "EventCursorError",
    "EventCursorReplayError",
    "EventPage",
    "ExpectedEffect",
    "IdempotencyContract",
    "IdempotencyKey",
    "LifecycleAction",
    "LifecycleCommand",
    "LifecycleOperation",
    "MissingIdempotencyError",
    "MUTATION_GUARD_REJECTION_SCHEMA",
    "MUTATION_GUARD_EXECUTION_OBSERVATION_SCHEMA",
    "MutationGuardExecutionObservation",
    "MutationGuardRejection",
    "Operation",
    "OperationCatalog",
    "OperationDescriptor",
    "OperationSpec",
    "OperationAuthority",
    "OperationCapability",
    "OperationError",
    "OperationEffect",
    "OperationEffectClaim",
    "OperationName",
    "OperationRequest",
    "OperationResult",
    "OperationStatus",
    "PathEscapeError",
    "PaginationDescriptor",
    "PaginationKind",
    "RequestBounds",
    "TypedOperationError",
    "TargetDescriptor",
    "UnsupportedCapabilityError",
    "UnsupportedCatalogVersionError",
    "VersionNegotiationError",
    "UnknownOperationError",
    "CursorReplayError",
    "canonical_control_json_bytes",
    "decode_operation_request",
    "discover_control_catalog",
    "discover_usage_control_catalog",
    "evaluate_unified_control_completion",
    "get_operation_catalog",
    "negotiate_catalog_version",
    "negotiate_control_version",
    "operation_authority",
    "operation_request_json_schema",
    "operation_result_json_schema",
    "replay_event_page",
    "SUPERVISOR_USAGE_CONTROL_REQUIREMENT_ID",
    "SUPERVISOR_USAGE_CONTROL_GOAL_ID",
    "SUPERVISOR_USAGE_CONTROL_SCHEMA_VERSION",
    "SUPERVISOR_USAGE_CONTROL_TOOL_SCHEMA_VERSION",
    "SUPERVISOR_USAGE_CONTROL_CATALOG_SCHEMA",
    "SUPERVISOR_USAGE_METRICS_REQUIREMENT_ID",
    "SUPERVISOR_USAGE_METRICS_SCHEMA",
    "SUPERVISOR_USAGE_METRICS_SCHEMA_VERSION",
    "SUPERVISOR_USAGE_READ_AUTHORITY",
    "SUPERVISOR_USAGE_READ_DETAIL_AUTHORITY",
    "SUPERVISOR_USAGE_ADMIN_AUTHORITY",
    "SUPERVISOR_USAGE_BUDGET_AUTHORITY",
    "SUPERVISOR_USAGE_POLICY_AUTHORITY",
    "SUPERVISOR_USAGE_CORRECTION_AUTHORITY",
    "SUPERVISOR_USAGE_RESET_AUTHORITY",
    "SUPERVISOR_USAGE_REASON_CODES",
    "SUPERVISOR_USAGE_FORBIDDEN_METRIC_LABELS",
    "USAGE_HEADROOM_BANDS",
    "USAGE_CONTROL_READ_OPERATIONS",
    "USAGE_CONTROL_MUTATION_OPERATIONS",
    "USAGE_CONTROL_PREVIEW_OPERATIONS",
    "USAGE_CONTROL_MUTATION_AUTHORITIES",
    "MAX_USAGE_CONTROL_PAGE_SIZE",
    "SupervisorUsageAuthority",
    "SupervisorUsageControlOperation",
    "usage_control_authorities",
    "usage_control_reason_codes",
    "usage_control_operations",
    "usage_control_mutation_operations",
    "usage_control_read_operations",
    "usage_headroom_band",
]
