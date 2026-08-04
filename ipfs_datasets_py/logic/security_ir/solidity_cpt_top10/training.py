"""Bounded, reproducible formal-learning runs for Solidity CPT Top-10.

The runner in this module is deliberately backend-neutral.  Importing it does
not discover credentials, access a network, download a model, select a GPU, or
start training.  A caller must inject a backend, and dry-run mode is the
default.  The included tiny backend is an inert deterministic fixture for
tests and operator preflight only; it is not a trained model.

Requests bind every material input and resource decision.  Checkpoint
manifests bind opaque checkpoint bytes without deserializing or executing
them.  Terminal receipts are content addressed and keep failure states
explicit.  Learned artifacts always have ``candidate`` authority: neither a
checkpoint nor a successful receipt is proof, a contract-safety decision, a
release approval, or transaction authority.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity, cid_v1
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)

TRAINING_REQUEST_SCHEMA_VERSION: Final = "solidity-cpt-formal-training-request/v1"
CHECKPOINT_MANIFEST_SCHEMA_VERSION: Final = "solidity-cpt-formal-training-checkpoint/v1"
TRAINING_RECEIPT_SCHEMA_VERSION: Final = "solidity-cpt-formal-training-receipt/v1"
TRAINING_BACKEND_RESULT_SCHEMA_VERSION: Final = "solidity-cpt-formal-training-backend-result/v1"
TRAINING_IDENTITY_DOMAIN: Final = "solidity-cpt-security-ir/formal-training"

CANDIDATE_AUTHORITY: Final = "candidate"
NO_PROOF_AUTHORITY: Final = False
NO_TRANSACTION_AUTHORITY: Final = False

DEFAULT_MAX_INPUT_BYTES: Final = 1 * 1024 * 1024
DEFAULT_MAX_INPUT_TOKENS: Final = 8_192
DEFAULT_MAX_STEPS: Final = 16
DEFAULT_TIMEOUT_MS: Final = 10_000
DEFAULT_MAX_MEMORY_BYTES: Final = 512 * 1024 * 1024
DEFAULT_MAX_CHECKPOINTS: Final = 2
DEFAULT_MAX_CHECKPOINT_BYTES: Final = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_CHECKPOINT_BYTES: Final = 4 * 1024 * 1024

MAX_INPUT_BYTES: Final = 1 * 1024 * 1024 * 1024
MAX_INPUT_TOKENS: Final = 100_000_000
MAX_STEPS: Final = 10_000_000
MAX_TIMEOUT_MS: Final = 7 * 24 * 60 * 60 * 1_000
MAX_MEMORY_BYTES: Final = 1 << 50
MAX_CHECKPOINTS: Final = 100_000
MAX_CHECKPOINT_BYTES: Final = 64 * 1024 * 1024 * 1024
MAX_TOTAL_CHECKPOINT_BYTES: Final = 1 << 50

_CID_RE = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GATED_ACTIONS = frozenset(
    {
        "model_download",
        "ambient_credentials",
        "external_tracking",
        "full_gpu_execution",
        "checkpoint_upload",
        "publication",
    }
)


class TrainingContractError(ValueError):
    """Base class for malformed training contracts."""


class TrainingIntegrityError(TrainingContractError):
    """Raised when a request, checkpoint, or receipt fails rehashing."""


class TrainingAuthorityError(TrainingContractError):
    """Raised when a request exceeds its explicit operator authority."""


class TrainingBackendError(RuntimeError):
    """Base class for explicit backend failures."""


class TrainingBackendUnavailable(TrainingBackendError):
    """The pinned backend or capability is unavailable."""


class TrainingTimedOut(TrainingBackendError):
    """The backend reached the request's time budget."""


class TrainingCancelled(TrainingBackendError):
    """The caller or backend cancelled the run."""


class TrainingPartial(TrainingBackendError):
    """The backend stopped after producing only partial state."""


class TrainingDiverged(TrainingBackendError):
    """The backend reported non-finite or divergent learning state."""


class TrainingStale(TrainingBackendError):
    """A backend result belongs to a different request or lineage."""


class TrainingCorrupt(TrainingBackendError):
    """A backend result or checkpoint failed an integrity check."""


class TrainingMode(StrEnum):
    """Execution modes with safe local defaults."""

    DRY_RUN = "dry_run"
    TINY_OFFLINE = "tiny_offline"
    AUTHORIZED_OFFLINE = "authorized_offline"


class TrainingStatus(StrEnum):
    """Closed terminal-state vocabulary; no failure is folded into success."""

    DRY_RUN = "dry_run"
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    DIVERGENT = "divergent"
    STALE = "stale"
    CORRUPT = "corrupt"
    FAILED = "failed"


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise TrainingContractError(f"{name} must be one of: {choices}") from exc


def _text(
    value: Any,
    name: str,
    *,
    maximum: int = 512,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TrainingContractError(f"{name} must be a string")
    if value != value.strip() or "\x00" in value or len(value) > maximum:
        raise TrainingContractError(f"{name} must be bounded trimmed text")
    if not allow_empty and not value:
        raise TrainingContractError(f"{name} must be non-empty")
    return value


def _cid(value: Any, name: str, *, allow_empty: bool = False) -> str:
    result = _text(value, name, maximum=128, allow_empty=allow_empty)
    if result and not _CID_RE.fullmatch(result):
        raise TrainingContractError(f"{name} must be a canonical CIDv1 sha2-256 identity")
    return result


def _sha256(value: Any, name: str, *, allow_empty: bool = False) -> str:
    result = _text(value, name, maximum=64, allow_empty=allow_empty)
    if result and not _SHA256_RE.fullmatch(result):
        raise TrainingContractError(f"{name} must be lowercase SHA-256")
    return result


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise TrainingContractError(f"{name} must be a positive integer no greater than {maximum}")
    return value


def _non_negative_int(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise TrainingContractError(f"{name} must be a non-negative integer no greater than {maximum}")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingContractError(f"{name} must be a mapping")
    return value


def _strict_wire_fields(
    value: Mapping[str, Any],
    fields: frozenset[str],
    name: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - optional - set(value))
    if unknown or missing:
        details: list[str] = []
        if unknown:
            details.append("unknown fields: " + ", ".join(unknown))
        if missing:
            details.append("missing fields: " + ", ".join(missing))
        raise TrainingIntegrityError(f"{name}: {'; '.join(details)}")


def _frozen_mapping(value: Any, name: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(_mapping(value, name))
    except ProvenanceValidationError as exc:
        raise TrainingContractError(f"{name}: {exc}") from exc


def _strings(
    value: Any,
    name: str,
    *,
    maximum_items: int = 64,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TrainingContractError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name} item") for item in value)
    if len(result) > maximum_items or len(result) != len(set(result)):
        raise TrainingContractError(f"{name} is too large or contains duplicates")
    if allowed is not None and not set(result) <= allowed:
        raise TrainingContractError(f"{name} contains an unsupported value")
    return tuple(sorted(result))


def _finite_json(value: Any, *, location: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise TrainingDiverged(f"non-finite numeric value at {location}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_json(item, location=f"{location}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _finite_json(item, location=f"{location}[{index}]")


def _identity(payload: Mapping[str, Any], suffix: str, schema: str) -> str:
    return canonical_identity(
        payload,
        domain=f"{TRAINING_IDENTITY_DOMAIN}/{suffix}",
        schema_version=schema,
    ).cid


@dataclass(frozen=True, slots=True)
class TrainingBudgets:
    """Hard resource ceilings supplied to and checked around the backend."""

    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    max_steps: int = DEFAULT_MAX_STEPS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_memory_bytes: int = DEFAULT_MAX_MEMORY_BYTES
    max_checkpoints: int = DEFAULT_MAX_CHECKPOINTS
    max_checkpoint_bytes: int = DEFAULT_MAX_CHECKPOINT_BYTES
    max_total_checkpoint_bytes: int = DEFAULT_MAX_TOTAL_CHECKPOINT_BYTES

    def __post_init__(self) -> None:
        for name, maximum in (
            ("max_input_bytes", MAX_INPUT_BYTES),
            ("max_input_tokens", MAX_INPUT_TOKENS),
            ("max_steps", MAX_STEPS),
            ("timeout_ms", MAX_TIMEOUT_MS),
            ("max_memory_bytes", MAX_MEMORY_BYTES),
            ("max_checkpoints", MAX_CHECKPOINTS),
            ("max_checkpoint_bytes", MAX_CHECKPOINT_BYTES),
            ("max_total_checkpoint_bytes", MAX_TOTAL_CHECKPOINT_BYTES),
        ):
            _positive_int(getattr(self, name), name, maximum)
        if self.max_checkpoint_bytes > self.max_total_checkpoint_bytes:
            raise TrainingContractError("max_checkpoint_bytes cannot exceed max_total_checkpoint_bytes")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "max_checkpoints": self.max_checkpoints,
            "max_input_bytes": self.max_input_bytes,
            "max_input_tokens": self.max_input_tokens,
            "max_memory_bytes": self.max_memory_bytes,
            "max_steps": self.max_steps,
            "max_total_checkpoint_bytes": self.max_total_checkpoint_bytes,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrainingBudgets:
        value = _mapping(value, "budgets")
        return cls(
            max_input_bytes=value.get("max_input_bytes", DEFAULT_MAX_INPUT_BYTES),
            max_input_tokens=value.get("max_input_tokens", DEFAULT_MAX_INPUT_TOKENS),
            max_steps=value.get("max_steps", DEFAULT_MAX_STEPS),
            timeout_ms=value.get("timeout_ms", DEFAULT_TIMEOUT_MS),
            max_memory_bytes=value.get("max_memory_bytes", DEFAULT_MAX_MEMORY_BYTES),
            max_checkpoints=value.get("max_checkpoints", DEFAULT_MAX_CHECKPOINTS),
            max_checkpoint_bytes=value.get("max_checkpoint_bytes", DEFAULT_MAX_CHECKPOINT_BYTES),
            max_total_checkpoint_bytes=value.get(
                "max_total_checkpoint_bytes",
                DEFAULT_MAX_TOTAL_CHECKPOINT_BYTES,
            ),
        )


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """Pinned execution hardware/capability profile."""

    profile_id: str = "cpu-tiny-offline-v1"
    accelerator: str = "cpu"
    device_count: int = 1
    precision: str = "float32"
    deterministic_algorithms: bool = True
    network_access: bool = False
    full_gpu_execution: bool = False

    def __post_init__(self) -> None:
        _text(self.profile_id, "hardware profile_id")
        accelerator = _text(self.accelerator, "accelerator", maximum=32)
        if accelerator not in {"cpu", "gpu", "tpu", "other"}:
            raise TrainingContractError("unsupported accelerator")
        _positive_int(self.device_count, "device_count", 1024)
        _text(self.precision, "precision", maximum=32)
        if type(self.deterministic_algorithms) is not bool:
            raise TrainingContractError("deterministic_algorithms must be boolean")
        if type(self.network_access) is not bool:
            raise TrainingContractError("network_access must be boolean")
        if type(self.full_gpu_execution) is not bool:
            raise TrainingContractError("full_gpu_execution must be boolean")
        if self.full_gpu_execution and accelerator != "gpu":
            raise TrainingContractError("full_gpu_execution requires accelerator='gpu'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accelerator": self.accelerator,
            "deterministic_algorithms": self.deterministic_algorithms,
            "device_count": self.device_count,
            "full_gpu_execution": self.full_gpu_execution,
            "network_access": self.network_access,
            "precision": self.precision,
            "profile_id": self.profile_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HardwareProfile:
        value = _mapping(value, "hardware")
        return cls(
            profile_id=value.get("profile_id", "cpu-tiny-offline-v1"),
            accelerator=value.get("accelerator", "cpu"),
            device_count=value.get("device_count", 1),
            precision=value.get("precision", "float32"),
            deterministic_algorithms=value.get("deterministic_algorithms", True),
            network_access=value.get("network_access", False),
            full_gpu_execution=value.get("full_gpu_execution", False),
        )


@dataclass(frozen=True, slots=True)
class TrainingOutputPolicy:
    """Output and external-side-effect policy; deny is the default."""

    retain_checkpoints: bool = True
    retain_logs: bool = False
    model_download: bool = False
    ambient_credentials: bool = False
    external_tracking: bool = False
    checkpoint_upload: bool = False
    publication: bool = False
    learned_output_authority: str = CANDIDATE_AUTHORITY

    def __post_init__(self) -> None:
        for name in (
            "retain_checkpoints",
            "retain_logs",
            "model_download",
            "ambient_credentials",
            "external_tracking",
            "checkpoint_upload",
            "publication",
        ):
            if type(getattr(self, name)) is not bool:
                raise TrainingContractError(f"{name} must be boolean")
        if self.learned_output_authority != CANDIDATE_AUTHORITY:
            raise TrainingAuthorityError("learned outputs must have candidate authority only")

    @property
    def requested_gated_actions(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "model_download",
                "ambient_credentials",
                "external_tracking",
                "checkpoint_upload",
                "publication",
            )
            if getattr(self, name)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambient_credentials": self.ambient_credentials,
            "checkpoint_upload": self.checkpoint_upload,
            "external_tracking": self.external_tracking,
            "learned_output_authority": self.learned_output_authority,
            "model_download": self.model_download,
            "publication": self.publication,
            "retain_checkpoints": self.retain_checkpoints,
            "retain_logs": self.retain_logs,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrainingOutputPolicy:
        value = _mapping(value, "output_policy")
        return cls(
            retain_checkpoints=value.get("retain_checkpoints", True),
            retain_logs=value.get("retain_logs", False),
            model_download=value.get("model_download", False),
            ambient_credentials=value.get("ambient_credentials", False),
            external_tracking=value.get("external_tracking", False),
            checkpoint_upload=value.get("checkpoint_upload", False),
            publication=value.get("publication", False),
            learned_output_authority=value.get("learned_output_authority", CANDIDATE_AUTHORITY),
        )


@dataclass(frozen=True, slots=True)
class TrainingAuthorityGrant:
    """Content-addressed operator approval for separately governed actions."""

    approval_id: str
    authority_cid: str
    permitted_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.approval_id, "approval_id")
        _cid(self.authority_cid, "authority_cid")
        object.__setattr__(
            self,
            "permitted_actions",
            _strings(
                self.permitted_actions,
                "permitted_actions",
                allowed=_GATED_ACTIONS,
            ),
        )
        if not self.permitted_actions:
            raise TrainingAuthorityError("authority grant must permit an action")

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "authority_cid": self.authority_cid,
            "permitted_actions": list(self.permitted_actions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrainingAuthorityGrant:
        value = _mapping(value, "authority_grant")
        return cls(
            approval_id=value.get("approval_id", ""),
            authority_cid=value.get("authority_cid", ""),
            permitted_actions=tuple(value.get("permitted_actions", ())),
        )


@dataclass(frozen=True, slots=True)
class FormalTrainingRequest:
    """Exact immutable request for one backend-neutral learning run."""

    source_cid: str
    graph_cid: str
    index_cid: str
    partition_cid: str
    license_cid: str
    training_data_cid: str
    base_model_id: str
    base_model_revision: str
    tokenizer_id: str
    tokenizer_revision: str
    objective: str
    feature_schema: Mapping[str, Any]
    target_schema: Mapping[str, Any]
    hyperparameters: Mapping[str, Any]
    seed: int
    backend_id: str
    backend_capability: str
    hardware: HardwareProfile = field(default_factory=HardwareProfile)
    budgets: TrainingBudgets = field(default_factory=TrainingBudgets)
    output_policy: TrainingOutputPolicy = field(default_factory=TrainingOutputPolicy)
    mode: TrainingMode = TrainingMode.DRY_RUN
    authority_grant: TrainingAuthorityGrant | None = None
    schema_version: str = TRAINING_REQUEST_SCHEMA_VERSION
    request_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "source_cid",
            "graph_cid",
            "index_cid",
            "partition_cid",
            "license_cid",
            "training_data_cid",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        for name in (
            "base_model_id",
            "base_model_revision",
            "tokenizer_id",
            "tokenizer_revision",
            "objective",
            "backend_id",
            "backend_capability",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in ("base_model_revision", "tokenizer_revision"):
            if getattr(self, name).casefold() in {"main", "master", "latest", "head"}:
                raise TrainingContractError(f"{name} must be an exact revision")
        object.__setattr__(
            self,
            "feature_schema",
            _frozen_mapping(self.feature_schema, "feature_schema"),
        )
        object.__setattr__(
            self,
            "target_schema",
            _frozen_mapping(self.target_schema, "target_schema"),
        )
        object.__setattr__(
            self,
            "hyperparameters",
            _frozen_mapping(self.hyperparameters, "hyperparameters"),
        )
        try:
            _finite_json(thaw_json(self.hyperparameters))
        except TrainingDiverged as exc:
            raise TrainingContractError(str(exc)) from exc
        _non_negative_int(self.seed, "seed", (1 << 63) - 1)
        if not isinstance(self.hardware, HardwareProfile):
            object.__setattr__(
                self,
                "hardware",
                HardwareProfile.from_dict(_mapping(self.hardware, "hardware")),
            )
        if not isinstance(self.budgets, TrainingBudgets):
            object.__setattr__(
                self,
                "budgets",
                TrainingBudgets.from_dict(_mapping(self.budgets, "budgets")),
            )
        if not isinstance(self.output_policy, TrainingOutputPolicy):
            object.__setattr__(
                self,
                "output_policy",
                TrainingOutputPolicy.from_dict(_mapping(self.output_policy, "output_policy")),
            )
        object.__setattr__(self, "mode", _enum(TrainingMode, self.mode, "mode"))
        if self.authority_grant is not None and not isinstance(self.authority_grant, TrainingAuthorityGrant):
            object.__setattr__(
                self,
                "authority_grant",
                TrainingAuthorityGrant.from_dict(_mapping(self.authority_grant, "authority_grant")),
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TRAINING_REQUEST_SCHEMA_VERSION:
            raise TrainingContractError("unsupported training request schema")
        self._validate_authority()
        computed = self.identity
        if self.request_id and self.request_id != computed:
            raise TrainingIntegrityError("request_id does not match rehashed training request")
        object.__setattr__(self, "request_id", computed)

    def _validate_authority(self) -> None:
        requested = set(self.output_policy.requested_gated_actions)
        if self.hardware.network_access:
            requested.add("model_download")
        if self.hardware.full_gpu_execution:
            requested.add("full_gpu_execution")
        if requested:
            if self.authority_grant is None:
                raise TrainingAuthorityError("gated training actions require separate operator authority")
            missing = requested - set(self.authority_grant.permitted_actions)
            if missing:
                raise TrainingAuthorityError("authority grant does not permit: " + ", ".join(sorted(missing)))
        if self.mode in {TrainingMode.DRY_RUN, TrainingMode.TINY_OFFLINE}:
            if (
                self.hardware.network_access
                or self.hardware.full_gpu_execution
                or self.hardware.accelerator != "cpu"
                or requested
            ):
                raise TrainingAuthorityError(f"{self.mode.value} must remain CPU-only, offline, and local")

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "request",
            TRAINING_REQUEST_SCHEMA_VERSION,
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority_grant": (None if self.authority_grant is None else self.authority_grant.to_dict()),
            "backend_capability": self.backend_capability,
            "backend_id": self.backend_id,
            "base_model_id": self.base_model_id,
            "base_model_revision": self.base_model_revision,
            "budgets": self.budgets.to_dict(),
            "feature_schema": thaw_json(self.feature_schema),
            "graph_cid": self.graph_cid,
            "hardware": self.hardware.to_dict(),
            "hyperparameters": thaw_json(self.hyperparameters),
            "index_cid": self.index_cid,
            "license_cid": self.license_cid,
            "mode": self.mode.value,
            "objective": self.objective,
            "output_policy": self.output_policy.to_dict(),
            "partition_cid": self.partition_cid,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "source_cid": self.source_cid,
            "target_schema": thaw_json(self.target_schema),
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "training_data_cid": self.training_data_cid,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FormalTrainingRequest:
        value = _mapping(value, "training request")
        _strict_wire_fields(
            value,
            frozenset(
                {
                    "authority_grant",
                    "backend_capability",
                    "backend_id",
                    "base_model_id",
                    "base_model_revision",
                    "budgets",
                    "feature_schema",
                    "graph_cid",
                    "hardware",
                    "hyperparameters",
                    "index_cid",
                    "license_cid",
                    "mode",
                    "objective",
                    "output_policy",
                    "partition_cid",
                    "request_id",
                    "schema_version",
                    "seed",
                    "source_cid",
                    "target_schema",
                    "tokenizer_id",
                    "tokenizer_revision",
                    "training_data_cid",
                }
            ),
            "training request",
            optional=frozenset({"request_id"}),
        )
        return cls(
            source_cid=value.get("source_cid", ""),
            graph_cid=value.get("graph_cid", ""),
            index_cid=value.get("index_cid", ""),
            partition_cid=value.get("partition_cid", ""),
            license_cid=value.get("license_cid", ""),
            training_data_cid=value.get("training_data_cid", ""),
            base_model_id=value.get("base_model_id", ""),
            base_model_revision=value.get("base_model_revision", ""),
            tokenizer_id=value.get("tokenizer_id", ""),
            tokenizer_revision=value.get("tokenizer_revision", ""),
            objective=value.get("objective", ""),
            feature_schema=value.get("feature_schema", {}),
            target_schema=value.get("target_schema", {}),
            hyperparameters=value.get("hyperparameters", {}),
            seed=value.get("seed", -1),
            backend_id=value.get("backend_id", ""),
            backend_capability=value.get("backend_capability", ""),
            hardware=HardwareProfile.from_dict(value.get("hardware", {})),
            budgets=TrainingBudgets.from_dict(value.get("budgets", {})),
            output_policy=TrainingOutputPolicy.from_dict(value.get("output_policy", {})),
            mode=value.get("mode", TrainingMode.DRY_RUN.value),
            authority_grant=(
                None
                if value.get("authority_grant") is None
                else TrainingAuthorityGrant.from_dict(value.get("authority_grant", {}))
            ),
            schema_version=value.get("schema_version", TRAINING_REQUEST_SCHEMA_VERSION),
            request_id=value.get("request_id", ""),
        )


@dataclass(frozen=True, slots=True)
class BackendCheckpoint:
    """Opaque bytes returned by an injected backend before manifesting."""

    payload: bytes
    step: int
    state_schema: str
    request_id: str = ""
    parent_checkpoint_id: str = ""
    expected_sha256: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.payload, (bytes, bytearray, memoryview)):
            raise TrainingCorrupt("checkpoint payload must be bytes")
        object.__setattr__(self, "payload", bytes(self.payload))
        _non_negative_int(self.step, "checkpoint step", MAX_STEPS)
        _text(self.state_schema, "checkpoint state_schema")
        if self.request_id:
            _cid(self.request_id, "checkpoint request_id")
        if self.parent_checkpoint_id:
            _cid(self.parent_checkpoint_id, "parent_checkpoint_id")
        if self.expected_sha256:
            _sha256(self.expected_sha256, "expected_sha256")
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata, "checkpoint metadata"))
        try:
            _finite_json(thaw_json(self.metadata))
        except TrainingDiverged:
            raise


@dataclass(frozen=True, slots=True)
class CheckpointManifest:
    """Content-addressed descriptor for one opaque checkpoint payload."""

    request_id: str
    backend_id: str
    backend_capability: str
    sequence: int
    step: int
    state_schema: str
    byte_length: int
    payload_sha256: str
    payload_cid: str
    parent_checkpoint_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    learned_output_authority: str = CANDIDATE_AUTHORITY
    proof_authority: bool = NO_PROOF_AUTHORITY
    transaction_authority: bool = NO_TRANSACTION_AUTHORITY
    schema_version: str = CHECKPOINT_MANIFEST_SCHEMA_VERSION
    checkpoint_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _cid(self.request_id, "request_id"))
        _text(self.backend_id, "backend_id")
        _text(self.backend_capability, "backend_capability")
        _non_negative_int(self.sequence, "sequence", MAX_CHECKPOINTS)
        _non_negative_int(self.step, "step", MAX_STEPS)
        _text(self.state_schema, "state_schema")
        _non_negative_int(self.byte_length, "byte_length", MAX_CHECKPOINT_BYTES)
        _sha256(self.payload_sha256, "payload_sha256")
        _cid(self.payload_cid, "payload_cid")
        if self.parent_checkpoint_id:
            _cid(self.parent_checkpoint_id, "parent_checkpoint_id")
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata, "checkpoint metadata"))
        if (
            self.learned_output_authority != CANDIDATE_AUTHORITY
            or self.proof_authority is not False
            or self.transaction_authority is not False
        ):
            raise TrainingAuthorityError("checkpoints are candidate-only and grant no proof or transaction authority")
        if self.schema_version != CHECKPOINT_MANIFEST_SCHEMA_VERSION:
            raise TrainingContractError("unsupported checkpoint manifest schema")
        computed = self.identity
        if self.checkpoint_id and self.checkpoint_id != computed:
            raise TrainingIntegrityError("checkpoint_id does not match rehashed manifest")
        object.__setattr__(self, "checkpoint_id", computed)

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "checkpoint",
            CHECKPOINT_MANIFEST_SCHEMA_VERSION,
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "backend_capability": self.backend_capability,
            "backend_id": self.backend_id,
            "byte_length": self.byte_length,
            "learned_output_authority": self.learned_output_authority,
            "metadata": thaw_json(self.metadata),
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "payload_cid": self.payload_cid,
            "payload_sha256": self.payload_sha256,
            "proof_authority": False,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "state_schema": self.state_schema,
            "step": self.step,
            "transaction_authority": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"checkpoint_id": self.checkpoint_id, **self.deterministic_dict()}

    def verify_payload(self, payload: bytes | bytearray | memoryview) -> None:
        raw = bytes(payload)
        if len(raw) != self.byte_length:
            raise TrainingCorrupt("checkpoint byte length does not match manifest")
        if hashlib.sha256(raw).hexdigest() != self.payload_sha256:
            raise TrainingCorrupt("checkpoint SHA-256 does not match manifest")
        if cid_v1(raw) != self.payload_cid:
            raise TrainingCorrupt("checkpoint content CID does not match manifest")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CheckpointManifest:
        value = _mapping(value, "checkpoint manifest")
        _strict_wire_fields(
            value,
            frozenset(
                {
                    "backend_capability",
                    "backend_id",
                    "byte_length",
                    "checkpoint_id",
                    "learned_output_authority",
                    "metadata",
                    "parent_checkpoint_id",
                    "payload_cid",
                    "payload_sha256",
                    "proof_authority",
                    "request_id",
                    "schema_version",
                    "sequence",
                    "state_schema",
                    "step",
                    "transaction_authority",
                }
            ),
            "checkpoint manifest",
            optional=frozenset({"checkpoint_id"}),
        )
        return cls(
            request_id=value.get("request_id", ""),
            backend_id=value.get("backend_id", ""),
            backend_capability=value.get("backend_capability", ""),
            sequence=value.get("sequence", -1),
            step=value.get("step", -1),
            state_schema=value.get("state_schema", ""),
            byte_length=value.get("byte_length", -1),
            payload_sha256=value.get("payload_sha256", ""),
            payload_cid=value.get("payload_cid", ""),
            parent_checkpoint_id=value.get("parent_checkpoint_id", ""),
            metadata=value.get("metadata", {}),
            learned_output_authority=value.get("learned_output_authority", CANDIDATE_AUTHORITY),
            proof_authority=value.get("proof_authority", False),
            transaction_authority=value.get("transaction_authority", False),
            schema_version=value.get("schema_version", CHECKPOINT_MANIFEST_SCHEMA_VERSION),
            checkpoint_id=value.get("checkpoint_id", ""),
        )


@dataclass(frozen=True, slots=True)
class BackendRunResult:
    """Normalized terminal data returned by a training backend."""

    status: TrainingStatus
    checkpoints: tuple[BackendCheckpoint, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    consumed_input_bytes: int = 0
    consumed_input_tokens: int = 0
    completed_steps: int = 0
    runtime_ms: int = 0
    peak_memory_bytes: int = 0
    output_model_cid: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = TRAINING_BACKEND_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(TrainingStatus, self.status, "backend status"))
        if self.status is TrainingStatus.DRY_RUN:
            raise TrainingContractError("a backend cannot return dry_run")
        normalized: list[BackendCheckpoint] = []
        for item in self.checkpoints:
            if not isinstance(item, BackendCheckpoint):
                raise TrainingCorrupt("backend checkpoints must be BackendCheckpoint values")
            normalized.append(item)
        object.__setattr__(self, "checkpoints", tuple(normalized))
        _finite_json(self.metrics)
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics, "backend metrics"))
        for name, maximum in (
            ("consumed_input_bytes", MAX_INPUT_BYTES),
            ("consumed_input_tokens", MAX_INPUT_TOKENS),
            ("completed_steps", MAX_STEPS),
            ("runtime_ms", MAX_TIMEOUT_MS),
            ("peak_memory_bytes", MAX_MEMORY_BYTES),
        ):
            _non_negative_int(getattr(self, name), name, maximum)
        if self.output_model_cid:
            _cid(self.output_model_cid, "output_model_cid")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostic", maximum=1024) for item in self.diagnostics),
        )
        if self.schema_version != TRAINING_BACKEND_RESULT_SCHEMA_VERSION:
            raise TrainingContractError("unsupported backend result schema")


@runtime_checkable
class FormalTrainingBackend(Protocol):
    """Injected backend contract.  Implementations must obey request budgets."""

    backend_id: str
    capability: str

    def run(
        self,
        request: FormalTrainingRequest,
        records: Sequence[Mapping[str, Any]],
    ) -> BackendRunResult:
        """Run entirely under the supplied request and return opaque state."""


@dataclass(frozen=True, slots=True)
class FormalTrainingReceipt:
    """Content-addressed terminal receipt for one exact request."""

    request_id: str
    status: TrainingStatus
    backend_id: str
    backend_capability: str
    checkpoints: tuple[CheckpointManifest, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    consumed_input_bytes: int = 0
    consumed_input_tokens: int = 0
    completed_steps: int = 0
    runtime_ms: int = 0
    peak_memory_bytes: int = 0
    output_model_cid: str = ""
    diagnostics: tuple[str, ...] = ()
    learned_output_authority: str = CANDIDATE_AUTHORITY
    proof_authority: bool = NO_PROOF_AUTHORITY
    transaction_authority: bool = NO_TRANSACTION_AUTHORITY
    schema_version: str = TRAINING_RECEIPT_SCHEMA_VERSION
    receipt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _cid(self.request_id, "request_id"))
        object.__setattr__(self, "status", _enum(TrainingStatus, self.status, "status"))
        _text(self.backend_id, "backend_id")
        _text(self.backend_capability, "backend_capability")
        normalized: list[CheckpointManifest] = []
        for item in self.checkpoints:
            manifest = (
                item
                if isinstance(item, CheckpointManifest)
                else CheckpointManifest.from_dict(_mapping(item, "checkpoint manifest"))
            )
            if manifest.request_id != self.request_id:
                raise TrainingStale("checkpoint belongs to a different request")
            normalized.append(manifest)
        object.__setattr__(self, "checkpoints", tuple(normalized))
        self._validate_lineage()
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics, "receipt metrics"))
        _finite_json(thaw_json(self.metrics))
        for name, maximum in (
            ("consumed_input_bytes", MAX_INPUT_BYTES),
            ("consumed_input_tokens", MAX_INPUT_TOKENS),
            ("completed_steps", MAX_STEPS),
            ("runtime_ms", MAX_TIMEOUT_MS),
            ("peak_memory_bytes", MAX_MEMORY_BYTES),
        ):
            _non_negative_int(getattr(self, name), name, maximum)
        if self.output_model_cid:
            _cid(self.output_model_cid, "output_model_cid")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostic", maximum=1024) for item in self.diagnostics),
        )
        if (
            self.learned_output_authority != CANDIDATE_AUTHORITY
            or self.proof_authority is not False
            or self.transaction_authority is not False
        ):
            raise TrainingAuthorityError("training receipts are candidate-only and non-authoritative")
        if self.schema_version != TRAINING_RECEIPT_SCHEMA_VERSION:
            raise TrainingContractError("unsupported training receipt schema")
        computed = self.identity
        if self.receipt_id and self.receipt_id != computed:
            raise TrainingIntegrityError("receipt_id does not match rehashed training receipt")
        object.__setattr__(self, "receipt_id", computed)

    def _validate_lineage(self) -> None:
        previous = ""
        previous_step = -1
        for sequence, manifest in enumerate(self.checkpoints):
            if manifest.sequence != sequence:
                raise TrainingCorrupt("checkpoint sequence is not contiguous")
            if manifest.parent_checkpoint_id != previous:
                raise TrainingCorrupt("checkpoint parent lineage does not match")
            if manifest.step < previous_step:
                raise TrainingCorrupt("checkpoint steps are not monotonic")
            previous = manifest.checkpoint_id
            previous_step = manifest.step

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "receipt",
            TRAINING_RECEIPT_SCHEMA_VERSION,
        )

    @property
    def successful(self) -> bool:
        return self.status is TrainingStatus.SUCCEEDED

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "backend_capability": self.backend_capability,
            "backend_id": self.backend_id,
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "completed_steps": self.completed_steps,
            "consumed_input_bytes": self.consumed_input_bytes,
            "consumed_input_tokens": self.consumed_input_tokens,
            "diagnostics": list(self.diagnostics),
            "learned_output_authority": self.learned_output_authority,
            "metrics": thaw_json(self.metrics),
            "output_model_cid": self.output_model_cid,
            "peak_memory_bytes": self.peak_memory_bytes,
            "proof_authority": False,
            "request_id": self.request_id,
            "runtime_ms": self.runtime_ms,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "transaction_authority": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FormalTrainingReceipt:
        value = _mapping(value, "training receipt")
        _strict_wire_fields(
            value,
            frozenset(
                {
                    "backend_capability",
                    "backend_id",
                    "checkpoints",
                    "completed_steps",
                    "consumed_input_bytes",
                    "consumed_input_tokens",
                    "diagnostics",
                    "learned_output_authority",
                    "metrics",
                    "output_model_cid",
                    "peak_memory_bytes",
                    "proof_authority",
                    "receipt_id",
                    "request_id",
                    "runtime_ms",
                    "schema_version",
                    "status",
                    "transaction_authority",
                }
            ),
            "training receipt",
            optional=frozenset({"receipt_id"}),
        )
        return cls(
            request_id=value.get("request_id", ""),
            status=value.get("status", ""),
            backend_id=value.get("backend_id", ""),
            backend_capability=value.get("backend_capability", ""),
            checkpoints=tuple(CheckpointManifest.from_dict(item) for item in value.get("checkpoints", ())),
            metrics=value.get("metrics", {}),
            consumed_input_bytes=value.get("consumed_input_bytes", 0),
            consumed_input_tokens=value.get("consumed_input_tokens", 0),
            completed_steps=value.get("completed_steps", 0),
            runtime_ms=value.get("runtime_ms", 0),
            peak_memory_bytes=value.get("peak_memory_bytes", 0),
            output_model_cid=value.get("output_model_cid", ""),
            diagnostics=tuple(value.get("diagnostics", ())),
            learned_output_authority=value.get("learned_output_authority", CANDIDATE_AUTHORITY),
            proof_authority=value.get("proof_authority", False),
            transaction_authority=value.get("transaction_authority", False),
            schema_version=value.get("schema_version", TRAINING_RECEIPT_SCHEMA_VERSION),
            receipt_id=value.get("receipt_id", ""),
        )


def _record_dict(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        result = dict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
    else:
        raise TrainingContractError("training records must be mappings or expose to_dict()")
    if not isinstance(result, Mapping):
        raise TrainingContractError("record to_dict() must return a mapping")
    if result.get("stream") == "evaluation_only":
        raise TrainingAuthorityError("evaluation_only records cannot enter a training run")
    if result.get("candidate_authority", CANDIDATE_AUTHORITY) not in {
        CANDIDATE_AUTHORITY,
        "non_authoritative",
    }:
        raise TrainingAuthorityError("training record exceeds candidate authority")
    return result


def _prepare_records(
    records: Sequence[Any],
) -> tuple[tuple[Mapping[str, Any], ...], int, int]:
    if isinstance(records, (str, bytes, bytearray)) or not isinstance(records, Sequence):
        raise TrainingContractError("records must be a sequence")
    normalized: list[Mapping[str, Any]] = []
    total_bytes = 0
    total_tokens = 0
    for item in records:
        record = _record_dict(item)
        encoded = canonical_json_bytes(record)
        total_bytes += len(encoded)
        token_count = record.get("token_count")
        if type(token_count) is int and token_count >= 0:
            total_tokens += token_count
        else:
            # Deterministic conservative estimate for records without a
            # tokenizer-produced count.  The exact tokenizer is still pinned
            # in the request and a real backend must report actual consumption.
            total_tokens += (len(encoded) + 3) // 4
        normalized.append(record)
    return tuple(normalized), total_bytes, total_tokens


def _failure_receipt(
    request: FormalTrainingRequest,
    status: TrainingStatus,
    diagnostic: str,
    *,
    checkpoints: Sequence[CheckpointManifest] = (),
    input_bytes: int = 0,
    input_tokens: int = 0,
) -> FormalTrainingReceipt:
    return FormalTrainingReceipt(
        request_id=request.request_id,
        status=status,
        backend_id=request.backend_id,
        backend_capability=request.backend_capability,
        checkpoints=tuple(checkpoints),
        consumed_input_bytes=min(input_bytes, MAX_INPUT_BYTES),
        consumed_input_tokens=min(input_tokens, MAX_INPUT_TOKENS),
        diagnostics=(diagnostic,),
    )


class FormalTrainingRunner:
    """Validate, execute, manifest, and receipt one injected training run."""

    def __init__(
        self,
        backend: FormalTrainingBackend | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._monotonic = monotonic

    def run(
        self,
        request: FormalTrainingRequest,
        records: Sequence[Any] = (),
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> FormalTrainingReceipt:
        if not isinstance(request, FormalTrainingRequest):
            raise TrainingContractError("request must be a FormalTrainingRequest")
        normalized, input_bytes, input_tokens = _prepare_records(records)
        if input_bytes > request.budgets.max_input_bytes:
            return _failure_receipt(
                request,
                TrainingStatus.PARTIAL,
                "input_byte_budget_exceeded",
                input_bytes=input_bytes,
                input_tokens=input_tokens,
            )
        if input_tokens > request.budgets.max_input_tokens:
            return _failure_receipt(
                request,
                TrainingStatus.PARTIAL,
                "input_token_budget_exceeded",
                input_bytes=input_bytes,
                input_tokens=input_tokens,
            )
        if cancelled is not None and cancelled():
            return _failure_receipt(
                request,
                TrainingStatus.CANCELLED,
                "cancelled_before_start",
                input_bytes=input_bytes,
                input_tokens=input_tokens,
            )
        if request.mode is TrainingMode.DRY_RUN:
            return FormalTrainingReceipt(
                request_id=request.request_id,
                status=TrainingStatus.DRY_RUN,
                backend_id=request.backend_id,
                backend_capability=request.backend_capability,
                consumed_input_bytes=input_bytes,
                consumed_input_tokens=input_tokens,
                diagnostics=("validated_without_backend_execution",),
            )
        backend = self._backend
        if backend is None:
            return _failure_receipt(
                request,
                TrainingStatus.UNAVAILABLE,
                "backend_not_injected",
                input_bytes=input_bytes,
                input_tokens=input_tokens,
            )
        if (
            getattr(backend, "backend_id", None) != request.backend_id
            or getattr(backend, "capability", None) != request.backend_capability
        ):
            return _failure_receipt(
                request,
                TrainingStatus.UNAVAILABLE,
                "backend_or_capability_mismatch",
                input_bytes=input_bytes,
                input_tokens=input_tokens,
            )

        started = self._monotonic()
        try:
            result = backend.run(request, normalized)
            if not isinstance(result, BackendRunResult):
                raise TrainingCorrupt("backend must return a BackendRunResult")
            elapsed_ms = max(0, int((self._monotonic() - started) * 1000))
            if elapsed_ms > request.budgets.timeout_ms:
                raise TrainingTimedOut("backend exceeded wall-clock budget")
            if cancelled is not None and cancelled():
                raise TrainingCancelled("cancelled_after_backend_return")
            return self._receipt_result(
                request,
                result,
                input_bytes=input_bytes,
                input_tokens=input_tokens,
            )
        except TrainingBackendUnavailable:
            status, diagnostic = TrainingStatus.UNAVAILABLE, "backend_unavailable"
        except TrainingTimedOut:
            status, diagnostic = TrainingStatus.TIMED_OUT, "backend_timed_out"
        except TrainingCancelled:
            status, diagnostic = TrainingStatus.CANCELLED, "backend_cancelled"
        except TrainingPartial:
            status, diagnostic = TrainingStatus.PARTIAL, "backend_partial"
        except TrainingDiverged:
            status, diagnostic = TrainingStatus.DIVERGENT, "backend_divergent"
        except TrainingStale:
            status, diagnostic = TrainingStatus.STALE, "backend_stale"
        except (TrainingCorrupt, TrainingIntegrityError):
            status, diagnostic = TrainingStatus.CORRUPT, "backend_corrupt"
        except Exception as exc:  # fail closed without leaking exception text
            status = TrainingStatus.FAILED
            diagnostic = f"backend_failed:{type(exc).__name__}"
        return _failure_receipt(
            request,
            status,
            diagnostic,
            input_bytes=input_bytes,
            input_tokens=input_tokens,
        )

    def _receipt_result(
        self,
        request: FormalTrainingRequest,
        result: BackendRunResult,
        *,
        input_bytes: int,
        input_tokens: int,
    ) -> FormalTrainingReceipt:
        budgets = request.budgets
        if result.runtime_ms > budgets.timeout_ms:
            raise TrainingTimedOut("backend declared a runtime over budget")
        if (
            result.consumed_input_bytes > budgets.max_input_bytes
            or result.consumed_input_tokens > budgets.max_input_tokens
            or result.completed_steps > budgets.max_steps
            or result.peak_memory_bytes > budgets.max_memory_bytes
        ):
            raise TrainingPartial("backend exceeded a resource budget")
        if result.consumed_input_bytes > input_bytes:
            raise TrainingCorrupt("backend consumed more bytes than supplied")
        if len(result.checkpoints) > budgets.max_checkpoints:
            raise TrainingPartial("backend exceeded checkpoint count budget")

        manifests: list[CheckpointManifest] = []
        total_checkpoint_bytes = 0
        previous = ""
        for sequence, artifact in enumerate(result.checkpoints):
            if artifact.request_id and artifact.request_id != request.request_id:
                raise TrainingStale("checkpoint belongs to a stale request")
            if artifact.parent_checkpoint_id and artifact.parent_checkpoint_id != previous:
                raise TrainingStale("checkpoint parent does not match run lineage")
            raw = artifact.payload
            total_checkpoint_bytes += len(raw)
            if len(raw) > budgets.max_checkpoint_bytes or total_checkpoint_bytes > budgets.max_total_checkpoint_bytes:
                raise TrainingPartial("checkpoint byte budget exceeded")
            digest = hashlib.sha256(raw).hexdigest()
            if artifact.expected_sha256 and artifact.expected_sha256 != digest:
                raise TrainingCorrupt("backend checkpoint digest mismatch")
            manifest = CheckpointManifest(
                request_id=request.request_id,
                backend_id=request.backend_id,
                backend_capability=request.backend_capability,
                sequence=sequence,
                step=artifact.step,
                state_schema=artifact.state_schema,
                byte_length=len(raw),
                payload_sha256=digest,
                payload_cid=cid_v1(raw),
                parent_checkpoint_id=previous,
                metadata=artifact.metadata,
            )
            manifest.verify_payload(raw)
            manifests.append(manifest)
            previous = manifest.checkpoint_id

        if result.status is TrainingStatus.SUCCEEDED and not manifests:
            raise TrainingPartial("successful training must emit a checkpoint")
        if result.output_model_cid and manifests and result.output_model_cid != manifests[-1].payload_cid:
            raise TrainingStale("output model CID does not match terminal checkpoint")
        return FormalTrainingReceipt(
            request_id=request.request_id,
            status=result.status,
            backend_id=request.backend_id,
            backend_capability=request.backend_capability,
            checkpoints=tuple(manifests),
            metrics=result.metrics,
            consumed_input_bytes=result.consumed_input_bytes,
            consumed_input_tokens=result.consumed_input_tokens,
            completed_steps=result.completed_steps,
            runtime_ms=result.runtime_ms,
            peak_memory_bytes=result.peak_memory_bytes,
            output_model_cid=result.output_model_cid,
            diagnostics=result.diagnostics,
        )


class DeterministicTinyOfflineBackend:
    """One-checkpoint CPU fixture backend; never loads or trains a model."""

    backend_id = "deterministic-tiny-offline"
    capability = "formalizer-fixture-v1"

    def run(
        self,
        request: FormalTrainingRequest,
        records: Sequence[Mapping[str, Any]],
    ) -> BackendRunResult:
        if request.mode is not TrainingMode.TINY_OFFLINE:
            raise TrainingBackendUnavailable("tiny backend only admits tiny_offline mode")
        records_digest = hashlib.sha256(canonical_json_bytes(list(records))).hexdigest()
        payload = canonical_json_bytes(
            {
                "artifact_kind": "deterministic_fixture_not_trained_weights",
                "candidate_authority": CANDIDATE_AUTHORITY,
                "record_count": len(records),
                "records_sha256": records_digest,
                "request_id": request.request_id,
                "seed": request.seed,
                "state_schema": "solidity-cpt-tiny-offline-state/v1",
            }
        )
        return BackendRunResult(
            status=TrainingStatus.SUCCEEDED,
            checkpoints=(
                BackendCheckpoint(
                    payload=payload,
                    step=1,
                    state_schema="solidity-cpt-tiny-offline-state/v1",
                    request_id=request.request_id,
                    metadata={
                        "fixture_only": True,
                        "production_checkpoint": False,
                    },
                ),
            ),
            metrics={"fixture_records": len(records)},
            consumed_input_bytes=sum(len(canonical_json_bytes(item)) for item in records),
            consumed_input_tokens=sum((len(canonical_json_bytes(item)) + 3) // 4 for item in records),
            completed_steps=1,
            runtime_ms=1,
            peak_memory_bytes=len(payload),
            output_model_cid=cid_v1(payload),
            diagnostics=("tiny_offline_fixture_only",),
        )


def verify_training_receipt(
    request: FormalTrainingRequest,
    receipt: FormalTrainingReceipt | Mapping[str, Any],
    *,
    checkpoint_payloads: Mapping[str, bytes] | None = None,
) -> FormalTrainingReceipt:
    """Rehash a receipt and optionally every checkpoint payload.

    ``checkpoint_payloads`` may be keyed by checkpoint ID or payload CID.
    Absence of payloads verifies manifest/receipt structure only and never
    claims that the opaque checkpoint bytes were inspected.
    """

    if not isinstance(request, FormalTrainingRequest):
        raise TrainingContractError("request must be a FormalTrainingRequest")
    normalized = receipt if isinstance(receipt, FormalTrainingReceipt) else FormalTrainingReceipt.from_dict(receipt)
    if normalized.request_id != request.request_id:
        raise TrainingStale("receipt belongs to a different training request")
    if normalized.backend_id != request.backend_id or normalized.backend_capability != request.backend_capability:
        raise TrainingStale("receipt backend binding differs from request")
    if checkpoint_payloads is not None:
        for manifest in normalized.checkpoints:
            payload = checkpoint_payloads.get(manifest.checkpoint_id)
            if payload is None:
                payload = checkpoint_payloads.get(manifest.payload_cid)
            if payload is None:
                raise TrainingCorrupt("checkpoint payload is missing from verification set")
            manifest.verify_payload(payload)
    return normalized


def _fixture_cid(label: str) -> str:
    return canonical_identity(
        {"fixture": label},
        domain=f"{TRAINING_IDENTITY_DOMAIN}/offline-fixture",
        schema_version="solidity-cpt-training-offline-fixture/v1",
    ).cid


def build_offline_fixture_request(
    *,
    mode: TrainingMode | str = TrainingMode.DRY_RUN,
) -> FormalTrainingRequest:
    """Return the deterministic tiny request used by the offline CLI."""

    normalized_mode = _enum(TrainingMode, mode, "mode")
    backend_id = DeterministicTinyOfflineBackend.backend_id
    capability = DeterministicTinyOfflineBackend.capability
    return FormalTrainingRequest(
        source_cid=_fixture_cid("source"),
        graph_cid=_fixture_cid("graph"),
        index_cid=_fixture_cid("index"),
        partition_cid=_fixture_cid("partition"),
        license_cid=_fixture_cid("license"),
        training_data_cid=_fixture_cid("training-data"),
        base_model_id="offline-fixture/no-model",
        base_model_revision="fixture-revision-v1",
        tokenizer_id="offline-fixture/byte-estimator",
        tokenizer_revision="fixture-tokenizer-v1",
        objective="validate formalizer training contracts without model training",
        feature_schema={"text": "string"},
        target_schema={"security_ir": "canonical-json"},
        hyperparameters={
            "batch_size": 1,
            "learning_rate": 0,
            "optimizer": "none",
        },
        seed=0,
        backend_id=backend_id,
        backend_capability=capability,
        mode=normalized_mode,
    )


def run_formal_training(
    request: FormalTrainingRequest,
    records: Sequence[Any] = (),
    *,
    backend: FormalTrainingBackend | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> FormalTrainingReceipt:
    """Convenience wrapper around :class:`FormalTrainingRunner`."""

    return FormalTrainingRunner(backend).run(request, records, cancelled=cancelled)


__all__ = [
    "BackendCheckpoint",
    "BackendRunResult",
    "CANDIDATE_AUTHORITY",
    "CHECKPOINT_MANIFEST_SCHEMA_VERSION",
    "CheckpointManifest",
    "DeterministicTinyOfflineBackend",
    "FormalTrainingBackend",
    "FormalTrainingReceipt",
    "FormalTrainingRequest",
    "FormalTrainingRunner",
    "HardwareProfile",
    "TRAINING_RECEIPT_SCHEMA_VERSION",
    "TRAINING_REQUEST_SCHEMA_VERSION",
    "TrainingAuthorityError",
    "TrainingAuthorityGrant",
    "TrainingBackendError",
    "TrainingBackendUnavailable",
    "TrainingBudgets",
    "TrainingCancelled",
    "TrainingContractError",
    "TrainingCorrupt",
    "TrainingDiverged",
    "TrainingIntegrityError",
    "TrainingMode",
    "TrainingOutputPolicy",
    "TrainingPartial",
    "TrainingStale",
    "TrainingStatus",
    "TrainingTimedOut",
    "build_offline_fixture_request",
    "run_formal_training",
    "verify_training_receipt",
]
