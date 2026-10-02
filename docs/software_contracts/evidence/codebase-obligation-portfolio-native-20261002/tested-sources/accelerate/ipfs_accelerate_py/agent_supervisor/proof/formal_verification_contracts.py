"""Canonical contracts and trust semantics for supervisor proof work.

The classes in this module are deliberately independent of any theorem prover
package.  They are the serialization boundary shared by proof providers,
caches, schedulers, merge gates, and goal evidence.

Two rules are central to the contract:

* identities are derived from canonical JSON and are never supplied by a
  provider; and
* authoritative assurance is a projection of typed evidence.  Provider status
  text and provider-claimed assurance are retained for audit, but cannot
  upgrade the projection.

All canonical values are DAG-JSON-compatible and reject floating point values.
Resource quantities therefore use explicit integer units (milliseconds,
bytes, and token counts).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, Iterable, List, Tuple, Type, TypeVar


CONTRACT_VERSION = 1
SCHEMA_VERSION = CONTRACT_VERSION
CODE_PROOF_OBLIGATION_SCHEMA = "ipfs_accelerate_py/agent-supervisor/code-proof-obligation@1"
PROOF_PLAN_SCHEMA = "ipfs_accelerate_py/agent-supervisor/proof-plan@1"
PROOF_PLAN_STEP_SCHEMA = "ipfs_accelerate_py/agent-supervisor/proof-plan-step@1"
PROOF_ATTEMPT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/proof-attempt@1"
PROOF_RECEIPT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/proof-receipt@1"
PROOF_EVIDENCE_SCHEMA = "ipfs_accelerate_py/agent-supervisor/proof-evidence@1"
RESOURCE_BUDGET_SCHEMA = "ipfs_accelerate_py/agent-supervisor/proof-resource-budget@1"
ASSURANCE_ASSESSMENT_SCHEMA = "ipfs_accelerate_py/agent-supervisor/assurance-assessment@1"
MAX_REJECTION_REASON_CHARS = 256

# Canonical proof contracts are durable/public artifacts.  Private proving
# inputs must remain in backend-owned memory and must never be smuggled into a
# receipt through an otherwise open-ended metadata field.
_PRIVATE_FIELD_MARKERS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "hidden_witness",
        "password",
        "private_key",
        "private_premise",
        "private_witness",
        "refresh_token",
        "secret",
        "session_token",
        "witness",
    }
)

_REJECTION_ACTIONS = {
    "artifact_rejected": "rebuild the artifact from its typed canonical contract",
    "attestation_binding_mismatch": "recreate the attestation for the exact receipt and key",
    "attestation_cache_miss": "run current attestation verification",
    "attestation_reverification_failed": "rerun the cryptographic verifier with pinned inputs",
    "attestation_reverification_required": "replay the pinned cryptographic verifier",
    "cache_binding_mismatch": "recompute the proof for the exact current inputs",
    "cache_miss": "run independent verification for the current inputs",
    "changed_premises": "recompute the proof with the current premise set",
    "expired_attestation_entry": "recreate the attestation with a current verification key",
    "freshness_requirement_not_satisfied": "recompute evidence for the current inputs",
    "malformed_attestation_entry": "discard the attestation and rerun verification",
    "malformed_cache_entry": "discard the entry and rerun independent verification",
    "malformed_proof_receipt": "rebuild the receipt from independently checked evidence",
    "partial_cache_entry": "finish independent verification before caching",
    "poisoned_attestation_entry": "quarantine the attestation and rerun verification",
    "poisoned_cache_entry": "quarantine the entry and rerun independent verification",
    "private_material": "remove private witness material from the public artifact",
    "required_assurance_not_satisfied": "run the independent verifier required by policy",
    "simulated_attestation": "use a production cryptographic backend and current key",
    "single_flight_cancelled": "retry proof work from a fresh fail-closed attempt",
    "single_flight_execution_failed": "inspect the leader locally and retry verification",
    "single_flight_timeout": "retry or increase the bounded proof-work timeout",
    "solver_only_cache_entry": "run an independent trusted kernel before promotion",
    "stale_candidate_tree": "recompute the proof for the current repository tree",
    "stale_cache_entry": "recompute proof evidence for the current inputs",
    "toolchain_drift": "recompute the proof with the current locked toolchain",
}


class ContractValidationError(ValueError):
    """Raised when a formal-verification contract is malformed or unsafe."""


class AssuranceLevel(str, Enum):
    """Ordered assurance available to policy and completion gates.

    ``SOLVER_CHECKED`` is intentionally below ``KERNEL_VERIFIED``.  An ATP or
    SMT result can be useful and reproducible without being a proof accepted by
    a small trusted kernel.  ``ATTESTED`` additionally requires a genuine
    cryptographic attestation over an existing kernel receipt.
    """

    UNVERIFIED = "unverified"
    NONE = "unverified"  # compatibility spelling
    CANDIDATE = "candidate"
    SOLVER_CHECKED = "solver_checked"
    SOLVER_VERIFIED = "solver_checked"  # compatibility spelling
    KERNEL_VERIFIED = "kernel_verified"
    ATTESTED = "attested"

    @property
    def rank(self) -> int:
        return {
            AssuranceLevel.UNVERIFIED: 0,
            AssuranceLevel.CANDIDATE: 1,
            AssuranceLevel.SOLVER_CHECKED: 2,
            AssuranceLevel.KERNEL_VERIFIED: 3,
            AssuranceLevel.ATTESTED: 4,
        }[self]

    def satisfies(self, required: "AssuranceLevel") -> bool:
        """Return whether this level meets ``required``."""

        return self.rank >= _enum(required, AssuranceLevel, field_name="required").rank


# These names make the distinction clear at call sites while retaining one
# wire vocabulary and comparison lattice.
RequiredAssuranceLevel = AssuranceLevel
AuthoritativeAssuranceLevel = AssuranceLevel
ProofAssuranceLevel = AssuranceLevel


class ProofStage(str, Enum):
    """A bounded stage in a proof-plan DAG."""

    TRANSLATE = "translate"
    MODEL_DRAFT = "model_draft"
    SOLVE = "solve"
    RECONSTRUCT = "reconstruct"
    KERNEL_VERIFY = "kernel_verify"
    VALIDATE = "validate"
    ATTEST = "attest"
    PERSIST = "persist"


class AttemptStatus(str, Enum):
    """Lifecycle state of a provider or verifier attempt."""

    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

    @property
    def terminal(self) -> bool:
        """Whether no more execution can occur within this attempt."""

        return self not in {AttemptStatus.PLANNED, AttemptStatus.RUNNING}

    @property
    def dependency_satisfied(self) -> bool:
        """Whether dependants may consume this attempt's outputs."""

        return self is AttemptStatus.SUCCEEDED


class ProofVerdict(str, Enum):
    """Semantic result of a proof receipt."""

    PROVED = "proved"
    DISPROVED = "disproved"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def conclusive(self) -> bool:
        """Whether the result settles an obligation and can stop a portfolio."""

        return self in {ProofVerdict.PROVED, ProofVerdict.DISPROVED}


class EvidenceKind(str, Enum):
    """Kind of evidence without implying that the evidence is trusted."""

    UNKNOWN = "unknown"
    LLM_OUTPUT = "llm_output"
    ATP_CANDIDATE = "atp_candidate"
    SMT_CANDIDATE = "smt_candidate"
    SOLVER_RESULT = "solver_result"
    KERNEL_VERIFICATION = "kernel_verification"
    TEST_RESULT = "test_result"
    STATIC_ANALYSIS = "static_analysis"
    CRYPTOGRAPHIC_ATTESTATION = "cryptographic_attestation"
    ZKP_ATTESTATION = "cryptographic_attestation"  # compatibility spelling
    CACHE_ENTRY = "cache_entry"


ProofEvidenceKind = EvidenceKind


class EvidenceAuthority(str, Enum):
    """Boundary which produced or independently checked an evidence item."""

    UNKNOWN = "unknown"
    PROVIDER = "provider"
    LLM = "llm"
    ATP = "atp"
    SMT = "smt"
    SOLVER = "solver"
    KERNEL = "kernel"
    ATTESTATION_VERIFIER = "attestation_verifier"
    VALIDATION_RUNNER = "validation_runner"
    CACHE = "cache"


class EvidenceVerdict(str, Enum):
    """Result recorded by one evidence-producing boundary."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class EvidenceFreshness(str, Enum):
    """Whether all semantic inputs still match the evidence binding."""

    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


TEnum = TypeVar("TEnum", bound=Enum)


def _enum(value: Any, enum_type: Type[TEnum], *, field_name: str) -> TEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(sorted({str(item.value) for item in enum_type}))
        raise ContractValidationError("%s must be one of: %s" % (field_name, allowed)) from exc


def _canonical_value(value: Any) -> Any:
    """Return a canonical JSON-compatible value or fail closed."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise ContractValidationError("canonical proof contracts cannot contain floats")
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, CanonicalContract):
        return value.to_dict()
    if isinstance(value, Mapping):
        if not all(isinstance(raw_key, str) for raw_key in value):
            raise ContractValidationError("canonical object keys must be strings")
        result: Dict[str, Any] = {}
        for raw_key in sorted(value):
            result[raw_key] = _canonical_value(value[raw_key])
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(items, key=canonical_json_bytes)
    raise ContractValidationError(
        "unsupported canonical proof contract value: %s" % type(value).__name__
    )


def bounded_rejection_reason(code: Any, detail: Any = None) -> str:
    """Return a bounded, actionable, secret-free public rejection reason.

    ``detail`` is deliberately ignored.  Raw prover output and exception text
    can contain source, credentials, or hidden witnesses and therefore belong
    only in access-controlled local diagnostics.  Unknown codes collapse to a
    generic reason instead of reflecting attacker-controlled text.
    """

    raw_code = getattr(code, "value", code)
    normalized = raw_code[:96].strip().lower() if isinstance(raw_code, str) else ""
    if normalized not in _REJECTION_ACTIONS:
        normalized = "artifact_rejected"
    reason = "%s: %s" % (normalized, _REJECTION_ACTIONS[normalized])
    return reason[:MAX_REJECTION_REASON_CHARS]


# Compatibility spelling for callers which emphasize the public projection.
actionable_rejection_reason = bounded_rejection_reason


def canonical_json_bytes(value: Any) -> bytes:
    """Encode deterministic DAG-JSON-compatible UTF-8 bytes."""

    normalized = _canonical_value(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json(value: Any) -> str:
    """Encode canonical JSON text."""

    return canonical_json_bytes(value).decode("utf-8")


def content_identity(value: Any) -> str:
    """Return a CIDv1 DAG-JSON/sha2-256 identity for ``value``."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    # CIDv1 + dag-json (0x0129 varint) + sha2-256 multihash.
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def _text(value: Any, *, field_name: str, required: bool = False) -> str:
    if value is None:
        normalized = ""
    elif not isinstance(value, str):
        raise ContractValidationError("%s must be a string" % field_name)
    else:
        normalized = value.strip()
    if required and not normalized:
        raise ContractValidationError("%s is required" % field_name)
    return normalized


def _ids(
    values: Any,
    *,
    field_name: str,
    required: bool = False,
    preserve_order: bool = False,
) -> Tuple[str, ...]:
    if values is None:
        items: Iterable[Any] = ()
    elif isinstance(values, str):
        items = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = values
    else:
        raise ContractValidationError("%s must be a sequence of strings" % field_name)
    normalized: List[str] = []
    for item in items:
        text = _text(item, field_name=field_name, required=True)
        if text not in normalized:
            normalized.append(text)
    if required and not normalized:
        raise ContractValidationError("%s must not be empty" % field_name)
    return tuple(normalized if preserve_order else sorted(normalized))


def _mapping(value: Any, *, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractValidationError("%s must be a mapping" % field_name)
    normalized = _canonical_value(value)
    assert isinstance(normalized, dict)
    if _contains_private_material(normalized):
        raise ContractValidationError(bounded_rejection_reason("private_material"))
    return normalized


def _contains_private_material(value: Any) -> bool:
    """Detect private fields recursively without inspecting or echoing values."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if any(
                key == marker or key.endswith("_" + marker) or marker in key
                for marker in _PRIVATE_FIELD_MARKERS
            ):
                return True
            if _contains_private_material(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_private_material(item) for item in value)
    return False


def _nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError("%s must be a non-negative integer" % field_name)
    if value < 0:
        raise ContractValidationError("%s must be a non-negative integer" % field_name)
    return value


def _schema(payload: Mapping[str, Any], expected: str) -> None:
    if not isinstance(payload, Mapping):
        raise ContractValidationError("contract payload must be an object")
    supplied = payload.get("schema")
    if supplied not in (None, "", expected):
        raise ContractValidationError("unsupported contract schema; use %s" % expected)


def _contract_version(payload: Mapping[str, Any]) -> None:
    supplied = payload.get("contract_version")
    if supplied not in (None, CONTRACT_VERSION):
        raise ContractValidationError(
            "unsupported proof contract version; rebuild with the current contract"
        )


def _reject_unknown_fields(
    payload: Mapping[str, Any],
    allowed: Iterable[str],
    *,
    artifact_name: str,
) -> None:
    """Fail closed without reflecting attacker-controlled field names."""

    if set(payload).difference(allowed):
        raise ContractValidationError(
            "%s contains unsupported fields; rebuild its canonical payload" % artifact_name
        )


class CanonicalContract:
    """Small mixin shared by immutable content-addressed contracts."""

    SCHEMA: ClassVar[str] = ""

    def _payload(self) -> Dict[str, Any]:
        raise NotImplementedError

    @property
    def schema(self) -> str:
        return self.SCHEMA

    @property
    def schema_version(self) -> int:
        return CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return _canonical_value({"schema": self.SCHEMA, **self._payload()})

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def canonical_json(self) -> str:
        """Compatibility spelling for :meth:`to_json`."""

        return self.to_json()

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def cid(self) -> str:
        return self.content_id

    @property
    def identity(self) -> str:
        return self.content_id

    @property
    def content_identity(self) -> str:
        return self.content_id

    @property
    def canonical_id(self) -> str:
        return self.content_id

    def to_record(self) -> Dict[str, Any]:
        """Return the canonical payload with its non-recursive identity."""

        return {**self.to_dict(), "content_id": self.content_id}

    @classmethod
    def from_json(cls, payload: str) -> "CanonicalContract":
        """Decode canonical JSON through the concrete class's ``from_dict``."""

        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ContractValidationError("contract JSON is malformed") from exc
        if not isinstance(value, Mapping):
            raise ContractValidationError("contract JSON must contain an object")
        decoder = getattr(cls, "from_dict", None)
        if decoder is None:
            raise ContractValidationError("%s does not support from_dict" % cls.__name__)
        return decoder(value)


@dataclass(frozen=True)
class ResourceBudget(CanonicalContract):
    """Integer-unit resource limits bound into a plan and every receipt."""

    SCHEMA: ClassVar[str] = RESOURCE_BUDGET_SCHEMA

    wall_time_ms: int = 0
    cpu_time_ms: int = 0
    memory_bytes: int = 0
    disk_bytes: int = 0
    max_processes: int = 0
    max_premises: int = 0
    max_output_bytes: int = 0
    model_token_limit: int = 0
    provider_quota: int = 0
    network_allowed: bool = False

    def __post_init__(self) -> None:
        for name in (
            "wall_time_ms",
            "cpu_time_ms",
            "memory_bytes",
            "disk_bytes",
            "max_processes",
            "max_premises",
            "max_output_bytes",
            "model_token_limit",
            "provider_quota",
        ):
            object.__setattr__(
                self,
                name,
                _nonnegative_int(getattr(self, name), field_name=name),
            )
        if not isinstance(self.network_allowed, bool):
            raise ContractValidationError("network_allowed must be a boolean")

    def _payload(self) -> Dict[str, Any]:
        return {
            "wall_time_ms": self.wall_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "memory_bytes": self.memory_bytes,
            "disk_bytes": self.disk_bytes,
            "max_processes": self.max_processes,
            "max_premises": self.max_premises,
            "max_output_bytes": self.max_output_bytes,
            "model_token_limit": self.model_token_limit,
            "provider_quota": self.provider_quota,
            "network_allowed": self.network_allowed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResourceBudget":
        _schema(payload, cls.SCHEMA)
        names = (
            "wall_time_ms",
            "cpu_time_ms",
            "memory_bytes",
            "disk_bytes",
            "max_processes",
            "max_premises",
            "max_output_bytes",
            "model_token_limit",
            "provider_quota",
            "network_allowed",
        )
        return cls(**{name: payload[name] for name in names if name in payload})


def _budget(value: Any, *, field_name: str = "resource_budget") -> ResourceBudget:
    if isinstance(value, ResourceBudget):
        return value
    if isinstance(value, Mapping):
        return ResourceBudget.from_dict(value)
    raise ContractValidationError("%s must be a ResourceBudget or mapping" % field_name)


@dataclass(frozen=True)
class CodeProofObligation(CanonicalContract):
    """A reviewed invariant applied to exact repository and AST inputs."""

    SCHEMA: ClassVar[str] = CODE_PROOF_OBLIGATION_SCHEMA

    repository_tree_id: str
    ast_scope_ids: Tuple[str, ...]
    statement: str
    template_id: str
    template_version: str
    template_semantic_hash: str
    premise_ids: Tuple[str, ...] = ()
    repository_id: str = ""
    invariant_class: str = ""
    task_id: str = ""
    required_assurance: AssuranceLevel = AssuranceLevel.KERNEL_VERIFIED
    fallback_checks: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "repository_tree_id",
            "statement",
            "template_id",
            "template_version",
            "template_semantic_hash",
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), field_name=name, required=True),
            )
        for name in ("repository_id", "invariant_class", "task_id"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(
            self,
            "ast_scope_ids",
            _ids(self.ast_scope_ids, field_name="ast_scope_ids", required=True),
        )
        object.__setattr__(self, "premise_ids", _ids(self.premise_ids, field_name="premise_ids"))
        object.__setattr__(
            self,
            "fallback_checks",
            _ids(self.fallback_checks, field_name="fallback_checks"),
        )
        object.__setattr__(
            self,
            "required_assurance",
            _enum(
                self.required_assurance,
                AssuranceLevel,
                field_name="required_assurance",
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, field_name="metadata"))

    @property
    def obligation_id(self) -> str:
        return self.content_id

    @property
    def tree_id(self) -> str:
        return self.repository_tree_id

    def _payload(self) -> Dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "ast_scope_ids": self.ast_scope_ids,
            "statement": self.statement,
            "premise_ids": self.premise_ids,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_semantic_hash": self.template_semantic_hash,
            "invariant_class": self.invariant_class,
            "task_id": self.task_id,
            "required_assurance": self.required_assurance,
            "fallback_checks": self.fallback_checks,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CodeProofObligation":
        _schema(payload, cls.SCHEMA)
        result = cls(
            repository_id=payload.get("repository_id", ""),
            repository_tree_id=payload.get("repository_tree_id", ""),
            ast_scope_ids=tuple(payload.get("ast_scope_ids") or ()),
            statement=payload.get("statement", ""),
            premise_ids=tuple(payload.get("premise_ids") or ()),
            template_id=payload.get("template_id", ""),
            template_version=payload.get("template_version", ""),
            template_semantic_hash=payload.get("template_semantic_hash", ""),
            invariant_class=payload.get("invariant_class", ""),
            task_id=payload.get("task_id", ""),
            required_assurance=payload.get("required_assurance", AssuranceLevel.KERNEL_VERIFIED),
            fallback_checks=tuple(payload.get("fallback_checks") or ()),
            metadata=payload.get("metadata") or {},
        )
        claimed_id = payload.get("obligation_id") or payload.get("content_id")
        if claimed_id and claimed_id != result.obligation_id:
            raise ContractValidationError("obligation content identity does not match payload")
        return result


@dataclass(frozen=True)
class ProofPlanStep(CanonicalContract):
    """One dependency-addressable node in a :class:`ProofPlan`."""

    SCHEMA: ClassVar[str] = PROOF_PLAN_STEP_SCHEMA

    step_id: str
    obligation_id: str
    stage: ProofStage
    provider_id: str
    depends_on: Tuple[str, ...] = ()
    required_assurance: AssuranceLevel = AssuranceLevel.UNVERIFIED
    resource_class: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("step_id", "obligation_id", "provider_id"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), field_name=name, required=True),
            )
        object.__setattr__(
            self, "resource_class", _text(self.resource_class, field_name="resource_class")
        )
        object.__setattr__(self, "stage", _enum(self.stage, ProofStage, field_name="stage"))
        object.__setattr__(
            self,
            "depends_on",
            _ids(self.depends_on, field_name="depends_on"),
        )
        object.__setattr__(
            self,
            "required_assurance",
            _enum(
                self.required_assurance,
                AssuranceLevel,
                field_name="required_assurance",
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, field_name="metadata"))
        dependency_mode = self.metadata.get("dependency_mode", "all")
        if dependency_mode not in {"all", "any"}:
            raise ContractValidationError("proof-plan step dependency_mode must be 'all' or 'any'")
        for key in ("portfolio_id", "portfolio_group"):
            if key in self.metadata and not isinstance(self.metadata[key], str):
                raise ContractValidationError("proof-plan step %s must be a string" % key)
        priority = self.metadata.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ContractValidationError("proof-plan step priority must be an integer")
        if self.step_id in self.depends_on:
            raise ContractValidationError("a proof-plan step cannot depend on itself")

    @property
    def node_id(self) -> str:
        return self.step_id

    @property
    def portfolio_id(self) -> str:
        """Stable cancellation group declared by plan metadata, if any."""

        value = self.metadata.get("portfolio_id", self.metadata.get("portfolio_group", ""))
        return value.strip() if isinstance(value, str) else ""

    @property
    def dependency_mode(self) -> str:
        """Return ``all`` (default) or ``any`` dependency semantics.

        ``any`` is useful for an explicit portfolio join node.  It does not
        weaken ordinary proof-plan dependencies, which remain conjunctive.
        """

        value = self.metadata.get("dependency_mode", "all")
        return "any" if value == "any" else "all"

    def _payload(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "obligation_id": self.obligation_id,
            "stage": self.stage,
            "provider_id": self.provider_id,
            "depends_on": self.depends_on,
            "required_assurance": self.required_assurance,
            "resource_class": self.resource_class,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofPlanStep":
        _schema(payload, cls.SCHEMA)
        return cls(
            step_id=payload.get("step_id", ""),
            obligation_id=payload.get("obligation_id", ""),
            stage=payload.get("stage", ProofStage.SOLVE),
            provider_id=payload.get("provider_id", ""),
            depends_on=tuple(payload.get("depends_on") or ()),
            required_assurance=payload.get("required_assurance", AssuranceLevel.UNVERIFIED),
            resource_class=payload.get("resource_class", ""),
            metadata=payload.get("metadata") or {},
        )


def _step(value: Any) -> ProofPlanStep:
    if isinstance(value, ProofPlanStep):
        return value
    if isinstance(value, Mapping):
        return ProofPlanStep.from_dict(value)
    raise ContractValidationError("steps must contain ProofPlanStep values or mappings")


@dataclass(frozen=True)
class ProofPlan(CanonicalContract):
    """A deterministic, acyclic execution plan for one repository tree."""

    SCHEMA: ClassVar[str] = PROOF_PLAN_SCHEMA

    repository_tree_id: str
    obligation_ids: Tuple[str, ...]
    steps: Tuple[ProofPlanStep, ...]
    policy_id: str
    resource_budget: ResourceBudget
    required_assurance: AssuranceLevel = AssuranceLevel.KERNEL_VERIFIED
    max_parallel: int = 1
    task_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_tree_id",
            _text(self.repository_tree_id, field_name="repository_tree_id", required=True),
        )
        object.__setattr__(
            self,
            "obligation_ids",
            _ids(self.obligation_ids, field_name="obligation_ids", required=True),
        )
        normalized_steps = tuple(
            sorted((_step(item) for item in self.steps), key=lambda x: x.step_id)
        )
        if not normalized_steps:
            raise ContractValidationError("steps must not be empty")
        object.__setattr__(self, "steps", normalized_steps)
        object.__setattr__(
            self, "policy_id", _text(self.policy_id, field_name="policy_id", required=True)
        )
        object.__setattr__(self, "task_id", _text(self.task_id, field_name="task_id"))
        object.__setattr__(self, "resource_budget", _budget(self.resource_budget))
        object.__setattr__(
            self,
            "required_assurance",
            _enum(
                self.required_assurance,
                AssuranceLevel,
                field_name="required_assurance",
            ),
        )
        if isinstance(self.max_parallel, bool) or not isinstance(self.max_parallel, int):
            raise ContractValidationError("max_parallel must be a positive integer")
        if self.max_parallel <= 0:
            raise ContractValidationError("max_parallel must be a positive integer")
        object.__setattr__(self, "metadata", _mapping(self.metadata, field_name="metadata"))
        self._validate_graph()

    def _validate_graph(self) -> None:
        by_id = {step.step_id: step for step in self.steps}
        if len(by_id) != len(self.steps):
            raise ContractValidationError("proof-plan step_id values must be unique")
        obligations = set(self.obligation_ids)
        for step in self.steps:
            if step.obligation_id not in obligations:
                raise ContractValidationError(
                    "step %s references an obligation outside the plan" % step.step_id
                )
            missing = set(step.depends_on) - set(by_id)
            if missing:
                raise ContractValidationError(
                    "step %s has unknown dependencies: %s"
                    % (step.step_id, ", ".join(sorted(missing)))
                )

        visiting = set()
        visited = set()

        def visit(step_id: str) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise ContractValidationError("proof-plan dependencies must be acyclic")
            visiting.add(step_id)
            for dependency in by_id[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in sorted(by_id):
            visit(step_id)

    @property
    def plan_id(self) -> str:
        return self.content_id

    @property
    def dependencies(self) -> Dict[str, Tuple[str, ...]]:
        return {step.step_id: step.depends_on for step in self.steps}

    @property
    def dependants(self) -> Dict[str, Tuple[str, ...]]:
        """Reverse dependency edges, deterministically ordered."""

        result: Dict[str, List[str]] = {step.step_id: [] for step in self.steps}
        for step in self.steps:
            for dependency in step.depends_on:
                result[dependency].append(step.step_id)
        return {key: tuple(sorted(value)) for key, value in result.items()}

    @property
    def topological_step_ids(self) -> Tuple[str, ...]:
        """Return a deterministic dependency-first topological ordering."""

        remaining = {step.step_id: set(step.depends_on) for step in self.steps}
        ordered: List[str] = []
        while remaining:
            ready = sorted(
                step_id for step_id, dependencies in remaining.items() if not dependencies
            )
            # The graph was validated at construction; this is defensive
            # against future alternate constructors.
            if not ready:
                raise ContractValidationError("proof-plan dependencies must be acyclic")
            ordered.extend(ready)
            for step_id in ready:
                del remaining[step_id]
            for dependencies in remaining.values():
                dependencies.difference_update(ready)
        return tuple(ordered)

    @property
    def critical_path_lengths(self) -> Dict[str, int]:
        """Longest remaining node count from each step to a terminal node."""

        children = self.dependants
        lengths: Dict[str, int] = {}
        for step_id in reversed(self.topological_step_ids):
            lengths[step_id] = 1 + max((lengths[child] for child in children[step_id]), default=0)
        return lengths

    @property
    def downstream_unlock_counts(self) -> Dict[str, int]:
        """Number of distinct transitive dependants unlocked by each step."""

        children = self.dependants
        descendants: Dict[str, set[str]] = {}
        for step_id in reversed(self.topological_step_ids):
            reachable: set[str] = set(children[step_id])
            for child in children[step_id]:
                reachable.update(descendants[child])
            descendants[step_id] = reachable
        return {step_id: len(value) for step_id, value in descendants.items()}

    def _payload(self) -> Dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "repository_tree_id": self.repository_tree_id,
            "obligation_ids": self.obligation_ids,
            "steps": self.steps,
            "policy_id": self.policy_id,
            "resource_budget": self.resource_budget,
            "required_assurance": self.required_assurance,
            "max_parallel": self.max_parallel,
            "task_id": self.task_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofPlan":
        _schema(payload, cls.SCHEMA)
        result = cls(
            repository_tree_id=payload.get("repository_tree_id", ""),
            obligation_ids=tuple(payload.get("obligation_ids") or ()),
            steps=tuple(_step(item) for item in payload.get("steps") or ()),
            policy_id=payload.get("policy_id", ""),
            resource_budget=_budget(payload.get("resource_budget") or {}),
            required_assurance=payload.get("required_assurance", AssuranceLevel.KERNEL_VERIFIED),
            max_parallel=payload.get("max_parallel", 1),
            task_id=payload.get("task_id", ""),
            metadata=payload.get("metadata") or {},
        )
        claimed_id = payload.get("plan_id") or payload.get("content_id")
        if claimed_id and claimed_id != result.plan_id:
            raise ContractValidationError("proof-plan content identity does not match payload")
        return result


@dataclass(frozen=True)
class ProofEvidence(CanonicalContract):
    """One immutable evidence reference used by assurance derivation."""

    SCHEMA: ClassVar[str] = PROOF_EVIDENCE_SCHEMA

    kind: EvidenceKind
    authority: EvidenceAuthority
    verdict: EvidenceVerdict
    artifact_id: str
    subject_id: str = ""
    verifier_id: str = ""
    freshness: EvidenceFreshness = EvidenceFreshness.CURRENT
    independent: bool = False
    simulated: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, EvidenceKind, field_name="kind"))
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, EvidenceAuthority, field_name="authority"),
        )
        object.__setattr__(
            self,
            "verdict",
            _enum(self.verdict, EvidenceVerdict, field_name="verdict"),
        )
        object.__setattr__(
            self,
            "freshness",
            _enum(self.freshness, EvidenceFreshness, field_name="freshness"),
        )
        for name in ("artifact_id", "subject_id", "verifier_id"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if not isinstance(self.independent, bool):
            raise ContractValidationError("independent must be a boolean")
        if not isinstance(self.simulated, bool):
            raise ContractValidationError("simulated must be a boolean")
        object.__setattr__(self, "metadata", _mapping(self.metadata, field_name="metadata"))

    @property
    def evidence_id(self) -> str:
        return self.content_id

    def _payload(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "authority": self.authority,
            "verdict": self.verdict,
            "artifact_id": self.artifact_id,
            "subject_id": self.subject_id,
            "verifier_id": self.verifier_id,
            "freshness": self.freshness,
            "independent": self.independent,
            "simulated": self.simulated,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofEvidence":
        _schema(payload, cls.SCHEMA)
        _reject_unknown_fields(
            payload,
            {
                "schema",
                "kind",
                "authority",
                "verdict",
                "artifact_id",
                "subject_id",
                "verifier_id",
                "freshness",
                "independent",
                "simulated",
                "metadata",
                "evidence_id",
                "content_id",
            },
            artifact_name="proof evidence",
        )
        result = cls(
            kind=payload.get("kind", EvidenceKind.UNKNOWN),
            authority=payload.get("authority", EvidenceAuthority.UNKNOWN),
            verdict=payload.get("verdict", EvidenceVerdict.UNKNOWN),
            artifact_id=payload.get("artifact_id", ""),
            subject_id=payload.get("subject_id", ""),
            verifier_id=payload.get("verifier_id", ""),
            freshness=payload.get("freshness", EvidenceFreshness.CURRENT),
            independent=payload.get("independent", False),
            simulated=payload.get("simulated", False),
            metadata=payload.get("metadata") or {},
        )
        claimed_id = payload.get("evidence_id") or payload.get("content_id")
        if claimed_id and claimed_id != result.evidence_id:
            raise ContractValidationError("proof evidence content identity does not match payload")
        return result


def _evidence(value: Any) -> ProofEvidence:
    if isinstance(value, ProofEvidence):
        return value
    if isinstance(value, Mapping):
        return ProofEvidence.from_dict(value)
    raise ContractValidationError("evidence must contain ProofEvidence values or mappings")


@dataclass(frozen=True)
class AssuranceAssessment(CanonicalContract):
    """Auditable result of fail-closed assurance derivation."""

    SCHEMA: ClassVar[str] = ASSURANCE_ASSESSMENT_SCHEMA

    level: AssuranceLevel
    reason_codes: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", _enum(self.level, AssuranceLevel, field_name="level"))
        object.__setattr__(
            self,
            "reason_codes",
            _ids(self.reason_codes, field_name="reason_codes"),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _ids(self.evidence_ids, field_name="evidence_ids"),
        )

    def _payload(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "reason_codes": self.reason_codes,
            "evidence_ids": self.evidence_ids,
        }


_CANDIDATE_KINDS = frozenset(
    {
        EvidenceKind.LLM_OUTPUT,
        EvidenceKind.ATP_CANDIDATE,
        EvidenceKind.SMT_CANDIDATE,
        EvidenceKind.SOLVER_RESULT,
        EvidenceKind.KERNEL_VERIFICATION,
        EvidenceKind.CRYPTOGRAPHIC_ATTESTATION,
    }
)


def assess_assurance(
    evidence: Iterable[ProofEvidence],
    *,
    obligation_id: str = "",
    kernel_id: str = "",
    kernel_receipt_id: str = "",
    freshness: EvidenceFreshness = EvidenceFreshness.CURRENT,
    allow_authoritative: bool = True,
) -> AssuranceAssessment:
    """Derive assurance solely from typed evidence and exact bindings.

    A high-trust item must be accepted, current, independently produced,
    non-simulated, durably referenced, and bound to the expected subject and
    verifier.  An attestation additionally requires kernel evidence and must
    name the immutable kernel receipt it attests.
    """

    items = tuple(sorted((_evidence(item) for item in evidence), key=lambda x: x.evidence_id))
    global_freshness = _enum(freshness, EvidenceFreshness, field_name="freshness")
    expected_obligation = _text(obligation_id, field_name="obligation_id")
    expected_kernel = _text(kernel_id, field_name="kernel_id")
    expected_kernel_receipt = _text(kernel_receipt_id, field_name="kernel_receipt_id")
    reasons = set()
    accepted_ids: List[str] = []

    has_candidate = False
    has_solver = False
    has_kernel = False
    has_attestation = False

    for item in items:
        if item.verdict in (EvidenceVerdict.CANDIDATE, EvidenceVerdict.ACCEPTED):
            if item.kind in _CANDIDATE_KINDS and item.artifact_id:
                has_candidate = True
        if item.freshness is not EvidenceFreshness.CURRENT:
            reasons.add("stale_or_unknown_evidence")
            continue
        if item.simulated:
            reasons.add("simulated_evidence")
            continue
        if item.verdict is not EvidenceVerdict.ACCEPTED:
            continue

        if (
            item.kind is EvidenceKind.SOLVER_RESULT
            and item.authority is EvidenceAuthority.SOLVER
            and item.independent
            and item.artifact_id
            and item.verifier_id
            and (not expected_obligation or item.subject_id == expected_obligation)
        ):
            has_solver = True
            accepted_ids.append(item.evidence_id)

        if (
            item.kind is EvidenceKind.KERNEL_VERIFICATION
            and item.authority is EvidenceAuthority.KERNEL
            and item.independent
            and item.artifact_id
            and item.subject_id
            and item.verifier_id
            and (not expected_obligation or item.subject_id == expected_obligation)
            and (not expected_kernel or item.verifier_id == expected_kernel)
        ):
            has_kernel = True
            accepted_ids.append(item.evidence_id)

    if has_kernel:
        for item in items:
            if (
                item.kind is EvidenceKind.CRYPTOGRAPHIC_ATTESTATION
                and item.authority is EvidenceAuthority.ATTESTATION_VERIFIER
                and item.verdict is EvidenceVerdict.ACCEPTED
                and item.freshness is EvidenceFreshness.CURRENT
                and item.independent
                and not item.simulated
                and item.artifact_id
                and item.verifier_id
                and expected_kernel_receipt
                and item.subject_id == expected_kernel_receipt
            ):
                has_attestation = True
                accepted_ids.append(item.evidence_id)
                break

    if not allow_authoritative:
        if has_solver or has_kernel or has_attestation:
            reasons.add("provider_evidence_is_non_authoritative")
        level = AssuranceLevel.CANDIDATE if has_candidate else AssuranceLevel.UNVERIFIED
    elif global_freshness is not EvidenceFreshness.CURRENT:
        reasons.add("stale_or_unknown_receipt")
        level = AssuranceLevel.CANDIDATE if has_candidate else AssuranceLevel.UNVERIFIED
    elif has_attestation:
        level = AssuranceLevel.ATTESTED
    elif has_kernel:
        level = AssuranceLevel.KERNEL_VERIFIED
    elif has_solver:
        level = AssuranceLevel.SOLVER_CHECKED
    elif has_candidate:
        level = AssuranceLevel.CANDIDATE
    else:
        level = AssuranceLevel.UNVERIFIED

    if level is AssuranceLevel.UNVERIFIED:
        reasons.add("no_accepted_evidence")
    elif level is AssuranceLevel.CANDIDATE:
        reasons.add("candidate_only")
    elif level is AssuranceLevel.SOLVER_CHECKED:
        reasons.add("solver_checked_without_kernel")
    elif level is AssuranceLevel.KERNEL_VERIFIED:
        reasons.add("independent_kernel_acceptance")
    elif level is AssuranceLevel.ATTESTED:
        reasons.add("verified_cryptographic_attestation")

    return AssuranceAssessment(
        level=level,
        reason_codes=tuple(reasons),
        evidence_ids=tuple(accepted_ids),
    )


def derive_assurance(
    evidence: Iterable[ProofEvidence],
    **bindings: Any,
) -> AssuranceLevel:
    """Return only the authoritative level from :func:`assess_assurance`."""

    return assess_assurance(evidence, **bindings).level


def derive_verdict(
    evidence: Iterable[ProofEvidence],
    *,
    obligation_id: str = "",
    kernel_id: str = "",
    freshness: EvidenceFreshness = EvidenceFreshness.CURRENT,
) -> ProofVerdict:
    """Derive the authoritative semantic verdict from typed evidence.

    Proof providers do not participate in this projection.  A theorem is
    ``PROVED`` only when the same exact, current, independent kernel evidence
    which can establish kernel assurance is present.  Kernel rejection merely
    rejects a candidate proof; it does not disprove the theorem.  A
    ``DISPROVED`` verdict therefore requires an independently checked solver
    counterexample explicitly marked as such.

    ``kernel_verification`` evidence emitted by :mod:`kernel_verification`
    carries a stable ``failure_code``.  Unavailability and unsupported target
    kernels remain ``UNSUPPORTED``; execution or corrupt-evidence failures are
    ``ERROR``; ordinary proof rejection and timeouts are ``INCONCLUSIVE``.
    """

    items = tuple(sorted((_evidence(item) for item in evidence), key=lambda item: item.evidence_id))
    receipt_freshness = _enum(freshness, EvidenceFreshness, field_name="freshness")
    if receipt_freshness is not EvidenceFreshness.CURRENT:
        return ProofVerdict.INCONCLUSIVE

    expected_obligation = _text(obligation_id, field_name="obligation_id")
    expected_kernel = _text(kernel_id, field_name="kernel_id")
    failure_codes = set()

    for item in items:
        if item.kind is not EvidenceKind.KERNEL_VERIFICATION:
            continue
        if item.authority is not EvidenceAuthority.KERNEL:
            continue
        if not item.independent or item.simulated:
            continue
        if item.freshness is not EvidenceFreshness.CURRENT:
            continue
        if expected_obligation and item.subject_id != expected_obligation:
            continue
        if expected_kernel and item.verifier_id != expected_kernel:
            continue
        if item.verdict is EvidenceVerdict.ACCEPTED and item.artifact_id:
            return ProofVerdict.PROVED
        failure_code = item.metadata.get("failure_code")
        if isinstance(failure_code, str) and failure_code:
            failure_codes.add(failure_code)

    for item in items:
        if (
            item.kind is EvidenceKind.SOLVER_RESULT
            and item.authority
            in {
                EvidenceAuthority.SOLVER,
                EvidenceAuthority.VALIDATION_RUNNER,
            }
            and item.verdict is EvidenceVerdict.REJECTED
            and item.independent
            and not item.simulated
            and item.freshness is EvidenceFreshness.CURRENT
            and item.artifact_id
            and (not expected_obligation or item.subject_id == expected_obligation)
            and item.metadata.get("counterexample_verified") is True
        ):
            return ProofVerdict.DISPROVED

    if failure_codes & {"kernel_unavailable", "unsupported_kernel"}:
        return ProofVerdict.UNSUPPORTED
    if failure_codes & {
        "binding_mismatch",
        "corrupt_evidence",
        "digest_mismatch",
        "environment_mismatch",
        "forbidden_declaration",
        "malformed_reconstruction",
        "statement_mismatch",
    }:
        return ProofVerdict.ERROR
    return ProofVerdict.INCONCLUSIVE


def assurance_satisfies(actual: AssuranceLevel, required: AssuranceLevel) -> bool:
    """Compare two levels using the canonical trust lattice."""

    return _enum(actual, AssuranceLevel, field_name="actual").satisfies(
        _enum(required, AssuranceLevel, field_name="required")
    )


@dataclass(frozen=True)
class ProofAttempt(CanonicalContract):
    """An execution attempt whose provider outputs remain non-authoritative."""

    SCHEMA: ClassVar[str] = PROOF_ATTEMPT_SCHEMA

    plan_id: str
    step_id: str
    obligation_id: str
    repository_tree_id: str
    provider_id: str
    stage: ProofStage
    status: AttemptStatus
    evidence: Tuple[ProofEvidence, ...] = ()
    input_ids: Tuple[str, ...] = ()
    output_ids: Tuple[str, ...] = ()
    started_at: str = ""
    finished_at: str = ""
    resource_usage: Mapping[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    provider_claimed_assurance: AssuranceLevel = AssuranceLevel.UNVERIFIED
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "plan_id",
            "step_id",
            "obligation_id",
            "repository_tree_id",
            "provider_id",
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), field_name=name, required=True),
            )
        for name in ("started_at", "finished_at", "error_code", "error_message"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "stage", _enum(self.stage, ProofStage, field_name="stage"))
        object.__setattr__(self, "status", _enum(self.status, AttemptStatus, field_name="status"))
        normalized_evidence = tuple(
            sorted((_evidence(item) for item in self.evidence), key=lambda x: x.evidence_id)
        )
        object.__setattr__(self, "evidence", normalized_evidence)
        object.__setattr__(self, "input_ids", _ids(self.input_ids, field_name="input_ids"))
        object.__setattr__(self, "output_ids", _ids(self.output_ids, field_name="output_ids"))
        object.__setattr__(
            self,
            "resource_usage",
            _mapping(self.resource_usage, field_name="resource_usage"),
        )
        object.__setattr__(
            self,
            "provider_claimed_assurance",
            _enum(
                self.provider_claimed_assurance,
                AssuranceLevel,
                field_name="provider_claimed_assurance",
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, field_name="metadata"))

    @property
    def attempt_id(self) -> str:
        return self.content_id

    @property
    def authoritative_assurance(self) -> AssuranceLevel:
        # Attempts cross the provider boundary.  Independent verification
        # creates a ProofReceipt; an attempt can therefore never self-promote.
        return assess_assurance(
            self.evidence,
            obligation_id=self.obligation_id,
            allow_authoritative=False,
        ).level

    @property
    def assurance(self) -> AssuranceLevel:
        return self.authoritative_assurance

    @property
    def claimed_assurance(self) -> AssuranceLevel:
        return self.provider_claimed_assurance

    def _payload(self) -> Dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "obligation_id": self.obligation_id,
            "repository_tree_id": self.repository_tree_id,
            "provider_id": self.provider_id,
            "stage": self.stage,
            "status": self.status,
            "evidence": self.evidence,
            "input_ids": self.input_ids,
            "output_ids": self.output_ids,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "resource_usage": self.resource_usage,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "provider_claimed_assurance": self.provider_claimed_assurance,
            "authoritative_assurance": self.authoritative_assurance,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofAttempt":
        _schema(payload, cls.SCHEMA)
        _contract_version(payload)
        _reject_unknown_fields(
            payload,
            {
                "schema",
                "contract_version",
                "plan_id",
                "step_id",
                "obligation_id",
                "repository_tree_id",
                "provider_id",
                "stage",
                "status",
                "evidence",
                "input_ids",
                "output_ids",
                "started_at",
                "finished_at",
                "resource_usage",
                "error_code",
                "error_message",
                "provider_claimed_assurance",
                "authoritative_assurance",
                "metadata",
                "attempt_id",
                "content_id",
            },
            artifact_name="proof attempt",
        )
        result = cls(
            plan_id=payload.get("plan_id", ""),
            step_id=payload.get("step_id", ""),
            obligation_id=payload.get("obligation_id", ""),
            repository_tree_id=payload.get("repository_tree_id", ""),
            provider_id=payload.get("provider_id", ""),
            stage=payload.get("stage", ProofStage.SOLVE),
            status=payload.get("status", AttemptStatus.PLANNED),
            evidence=tuple(_evidence(item) for item in payload.get("evidence") or ()),
            input_ids=tuple(payload.get("input_ids") or ()),
            output_ids=tuple(payload.get("output_ids") or ()),
            started_at=payload.get("started_at", ""),
            finished_at=payload.get("finished_at", ""),
            resource_usage=payload.get("resource_usage") or {},
            error_code=payload.get("error_code", ""),
            error_message=payload.get("error_message", ""),
            provider_claimed_assurance=payload.get(
                "provider_claimed_assurance", AssuranceLevel.UNVERIFIED
            ),
            metadata=payload.get("metadata") or {},
        )
        claimed = payload.get("authoritative_assurance")
        if (
            claimed
            and _enum(claimed, AssuranceLevel, field_name="authoritative_assurance")
            is not result.authoritative_assurance
        ):
            raise ContractValidationError(
                "attempt authoritative assurance does not match derived evidence"
            )
        claimed_id = payload.get("attempt_id") or payload.get("content_id")
        if claimed_id and claimed_id != result.attempt_id:
            raise ContractValidationError("attempt content identity does not match payload")
        return result


def _mirror_kernel_verified_receipt(receipt: ProofReceipt) -> None:
    """Record kernel-verified eligibility. The check does not attest the receipt."""

    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(getattr(receipt, "obligation_id", "") or "kernel-verified-receipt")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="kernel_verified_receipt_requirement",
            record_ref=record_ref,
            subject_kind="receipt_id",
            subject_ref=record_ref,
        )
    except Exception:
        pass


@dataclass(frozen=True)
class ProofReceipt(CanonicalContract):
    """Immutable proof result binding all semantic and execution inputs.

    There is intentionally no constructor field named ``assurance`` or
    ``authoritative_assurance``.  Both are read-only projections of
    :attr:`evidence`.
    """

    SCHEMA: ClassVar[str] = PROOF_RECEIPT_SCHEMA

    obligation_id: str
    plan_id: str
    attempt_id: str
    repository_id: str
    repository_tree_id: str
    ast_scope_ids: Tuple[str, ...]
    premise_ids: Tuple[str, ...]
    translator_id: str
    solver_id: str
    kernel_id: str
    toolchain_id: str
    policy_id: str
    resource_budget: ResourceBudget
    verdict: ProofVerdict
    evidence: Tuple[ProofEvidence, ...] = ()
    provider_id: str = ""
    provider_claimed_assurance: AssuranceLevel = AssuranceLevel.UNVERIFIED
    freshness: EvidenceFreshness = EvidenceFreshness.CURRENT
    kernel_receipt_id: str = ""
    theorem_registry_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    resource_usage: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "obligation_id",
            "plan_id",
            "attempt_id",
            "repository_id",
            "repository_tree_id",
            "translator_id",
            "solver_id",
            "kernel_id",
            "toolchain_id",
            "policy_id",
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), field_name=name, required=True),
            )
        for name in (
            "provider_id",
            "kernel_receipt_id",
            "theorem_registry_id",
            "started_at",
            "finished_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(
            self,
            "ast_scope_ids",
            _ids(self.ast_scope_ids, field_name="ast_scope_ids", required=True),
        )
        object.__setattr__(
            self,
            "premise_ids",
            _ids(self.premise_ids, field_name="premise_ids"),
        )
        object.__setattr__(self, "resource_budget", _budget(self.resource_budget))
        object.__setattr__(self, "verdict", _enum(self.verdict, ProofVerdict, field_name="verdict"))
        normalized_evidence = tuple(
            sorted((_evidence(item) for item in self.evidence), key=lambda x: x.evidence_id)
        )
        object.__setattr__(self, "evidence", normalized_evidence)
        object.__setattr__(
            self,
            "provider_claimed_assurance",
            _enum(
                self.provider_claimed_assurance,
                AssuranceLevel,
                field_name="provider_claimed_assurance",
            ),
        )
        object.__setattr__(
            self,
            "freshness",
            _enum(self.freshness, EvidenceFreshness, field_name="freshness"),
        )
        object.__setattr__(
            self,
            "resource_usage",
            _mapping(self.resource_usage, field_name="resource_usage"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, field_name="metadata"))

    @property
    def receipt_id(self) -> str:
        return self.content_id

    @property
    def tree_id(self) -> str:
        return self.repository_tree_id

    @property
    def assurance_assessment(self) -> AssuranceAssessment:
        if self.verdict is not ProofVerdict.PROVED:
            return AssuranceAssessment(
                level=AssuranceLevel.UNVERIFIED,
                reason_codes=("receipt_not_proved",),
                evidence_ids=(),
            )
        return assess_assurance(
            self.evidence,
            obligation_id=self.obligation_id,
            kernel_id=self.kernel_id,
            kernel_receipt_id=self.kernel_receipt_id,
            freshness=self.freshness,
            allow_authoritative=True,
        )

    @property
    def authoritative_assurance(self) -> AssuranceLevel:
        return self.assurance_assessment.level

    @property
    def authoritative_verdict(self) -> ProofVerdict:
        """Semantic verdict projected from evidence, never provider text."""

        return derive_verdict(
            self.evidence,
            obligation_id=self.obligation_id,
            kernel_id=self.kernel_id,
            freshness=self.freshness,
        )

    @property
    def assurance(self) -> AssuranceLevel:
        return self.authoritative_assurance

    @property
    def claimed_assurance(self) -> AssuranceLevel:
        return self.provider_claimed_assurance

    def satisfies(self, required: AssuranceLevel) -> bool:
        return assurance_satisfies(self.authoritative_assurance, required)

    def completion_reference(
        self,
        required_assurance: AssuranceLevel = AssuranceLevel.KERNEL_VERIFIED,
    ) -> Dict[str, Any]:
        """Return the fail-closed projection consumed by completion gates.

        The projection deliberately carries both the provider-independent
        verdict and assurance.  Callers must not infer either value from task
        status, validation success, or ``provider_claimed_assurance``.  The
        canonical receipt is included so a persisted completion record can
        re-derive every projected value instead of trusting mutable summary
        fields.
        """

        required = _enum(
            required_assurance,
            AssuranceLevel,
            field_name="required_assurance",
        )
        verdict = self.authoritative_verdict
        assurance = self.authoritative_assurance
        fresh = self.freshness is EvidenceFreshness.CURRENT
        satisfied = bool(
            verdict is ProofVerdict.PROVED and fresh and assurance_satisfies(assurance, required)
        )
        reasons: List[str] = []
        if verdict is not ProofVerdict.PROVED:
            reasons.append("proof_verdict_%s" % verdict.value)
        if not fresh:
            reasons.append("proof_receipt_stale")
        if not assurance_satisfies(assurance, required):
            reasons.append("required_assurance_not_satisfied")
        if satisfied:
            reasons.append("required_assurance_satisfied")
        return _canonical_value(
            {
                "schema": "ipfs_accelerate_py/agent-supervisor/proof-completion-reference@1",
                "obligation_id": self.obligation_id,
                "proof_receipt_id": self.receipt_id,
                "repository_id": self.repository_id,
                "repository_tree_id": self.repository_tree_id,
                "required_assurance": required,
                "authoritative_assurance": assurance,
                "authoritative_verdict": verdict,
                "freshness": self.freshness,
                "provenance_id": self.receipt_id,
                "assurance_satisfied": satisfied,
                "reason_codes": reasons,
                "receipt": self.to_dict(),
            }
        )

    def satisfies_completion(
        self,
        required_assurance: AssuranceLevel = AssuranceLevel.KERNEL_VERIFIED,
    ) -> bool:
        """Whether this receipt alone satisfies a completion proof demand."""

        return bool(self.completion_reference(required_assurance)["assurance_satisfied"])

    @property
    def is_kernel_verified(self) -> bool:
        """Whether this is a current proved receipt accepted by its kernel.

        ``ATTESTED`` is above ``KERNEL_VERIFIED`` in the trust lattice, so an
        already-attested receipt remains kernel verified.  Keeping this check
        on the receipt contract gives optional attestation implementations one
        fail-closed eligibility boundary instead of inviting them to interpret
        provider status text or individual evidence records themselves.
        """

        return (
            self.authoritative_verdict is ProofVerdict.PROVED
            and self.freshness is EvidenceFreshness.CURRENT
            and self.satisfies(AssuranceLevel.KERNEL_VERIFIED)
        )

    @property
    def can_be_attested(self) -> bool:
        """Compatibility spelling for the receipt-attestation eligibility gate."""

        return self.is_kernel_verified

    def require_kernel_verified(self) -> None:
        """Fail unless this receipt is eligible for cryptographic attestation."""

        if self.verdict is not ProofVerdict.PROVED:
            raise ContractValidationError("attestation requires an existing proved receipt")
        if self.freshness is not EvidenceFreshness.CURRENT:
            raise ContractValidationError("attestation requires a current kernel-verified receipt")
        if not self.satisfies(AssuranceLevel.KERNEL_VERIFIED):
            raise ContractValidationError(
                "attestation requires an existing kernel-verified receipt"
            )
        _mirror_kernel_verified_receipt(self)

    def _payload(self) -> Dict[str, Any]:
        assessment = self.assurance_assessment
        return {
            "contract_version": CONTRACT_VERSION,
            "obligation_id": self.obligation_id,
            "plan_id": self.plan_id,
            "attempt_id": self.attempt_id,
            "repository_id": self.repository_id,
            "repository_tree_id": self.repository_tree_id,
            "ast_scope_ids": self.ast_scope_ids,
            "premise_ids": self.premise_ids,
            "translator_id": self.translator_id,
            "solver_id": self.solver_id,
            "kernel_id": self.kernel_id,
            "toolchain_id": self.toolchain_id,
            "theorem_registry_id": self.theorem_registry_id,
            "policy_id": self.policy_id,
            "resource_budget": self.resource_budget,
            "verdict": self.verdict,
            "evidence": self.evidence,
            "provider_id": self.provider_id,
            "provider_claimed_assurance": self.provider_claimed_assurance,
            "freshness": self.freshness,
            "kernel_receipt_id": self.kernel_receipt_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "resource_usage": self.resource_usage,
            "authoritative_verdict": self.authoritative_verdict,
            "authoritative_assurance": assessment.level,
            "assurance_reason_codes": assessment.reason_codes,
            "authoritative_evidence_ids": assessment.evidence_ids,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofReceipt":
        _schema(payload, cls.SCHEMA)
        _contract_version(payload)
        _reject_unknown_fields(
            payload,
            {
                "schema",
                "contract_version",
                "obligation_id",
                "plan_id",
                "attempt_id",
                "repository_id",
                "repository_tree_id",
                "ast_scope_ids",
                "premise_ids",
                "translator_id",
                "solver_id",
                "kernel_id",
                "toolchain_id",
                "theorem_registry_id",
                "policy_id",
                "resource_budget",
                "verdict",
                "evidence",
                "provider_id",
                "provider_claimed_assurance",
                "freshness",
                "kernel_receipt_id",
                "started_at",
                "finished_at",
                "resource_usage",
                "authoritative_verdict",
                "authoritative_assurance",
                "assurance_reason_codes",
                "authoritative_evidence_ids",
                "metadata",
                "receipt_id",
                "content_id",
            },
            artifact_name="proof receipt",
        )
        result = cls(
            obligation_id=payload.get("obligation_id", ""),
            plan_id=payload.get("plan_id", ""),
            attempt_id=payload.get("attempt_id", ""),
            repository_id=payload.get("repository_id", ""),
            repository_tree_id=payload.get("repository_tree_id", ""),
            ast_scope_ids=tuple(payload.get("ast_scope_ids") or ()),
            premise_ids=tuple(payload.get("premise_ids") or ()),
            translator_id=payload.get("translator_id", ""),
            solver_id=payload.get("solver_id", ""),
            kernel_id=payload.get("kernel_id", ""),
            toolchain_id=payload.get("toolchain_id", ""),
            theorem_registry_id=payload.get("theorem_registry_id", ""),
            policy_id=payload.get("policy_id", ""),
            resource_budget=_budget(payload.get("resource_budget") or {}),
            verdict=payload.get("verdict", ProofVerdict.INCONCLUSIVE),
            evidence=tuple(_evidence(item) for item in payload.get("evidence") or ()),
            provider_id=payload.get("provider_id", ""),
            provider_claimed_assurance=payload.get(
                "provider_claimed_assurance", AssuranceLevel.UNVERIFIED
            ),
            freshness=payload.get("freshness", EvidenceFreshness.CURRENT),
            kernel_receipt_id=payload.get("kernel_receipt_id", ""),
            started_at=payload.get("started_at", ""),
            finished_at=payload.get("finished_at", ""),
            resource_usage=payload.get("resource_usage") or {},
            metadata=payload.get("metadata") or {},
        )
        claimed = payload.get("authoritative_assurance")
        if (
            claimed
            and _enum(claimed, AssuranceLevel, field_name="authoritative_assurance")
            is not result.authoritative_assurance
        ):
            raise ContractValidationError(
                "receipt authoritative assurance does not match derived evidence"
            )
        claimed_verdict = payload.get("authoritative_verdict")
        if (
            claimed_verdict
            and _enum(claimed_verdict, ProofVerdict, field_name="authoritative_verdict")
            is not result.authoritative_verdict
        ):
            raise ContractValidationError(
                "receipt authoritative verdict does not match derived evidence"
            )
        supplied_reasons = payload.get("assurance_reason_codes")
        if (
            supplied_reasons is not None
            and _ids(supplied_reasons, field_name="assurance_reason_codes")
            != result.assurance_assessment.reason_codes
        ):
            raise ContractValidationError(
                "receipt assurance reason codes do not match derived evidence"
            )
        supplied_evidence_ids = payload.get("authoritative_evidence_ids")
        if (
            supplied_evidence_ids is not None
            and _ids(supplied_evidence_ids, field_name="authoritative_evidence_ids")
            != result.assurance_assessment.evidence_ids
        ):
            raise ContractValidationError(
                "receipt authoritative evidence IDs do not match derived evidence"
            )
        claimed_id = payload.get("receipt_id") or payload.get("content_id")
        if claimed_id and claimed_id != result.receipt_id:
            raise ContractValidationError("receipt content identity does not match payload")
        return result


__all__ = [
    "ASSURANCE_ASSESSMENT_SCHEMA",
    "CODE_PROOF_OBLIGATION_SCHEMA",
    "CONTRACT_VERSION",
    "PROOF_ATTEMPT_SCHEMA",
    "PROOF_EVIDENCE_SCHEMA",
    "PROOF_PLAN_SCHEMA",
    "PROOF_PLAN_STEP_SCHEMA",
    "PROOF_RECEIPT_SCHEMA",
    "RESOURCE_BUDGET_SCHEMA",
    "SCHEMA_VERSION",
    "MAX_REJECTION_REASON_CHARS",
    "AssuranceAssessment",
    "AssuranceLevel",
    "AttemptStatus",
    "AuthoritativeAssuranceLevel",
    "CanonicalContract",
    "CodeProofObligation",
    "ContractValidationError",
    "EvidenceAuthority",
    "EvidenceFreshness",
    "EvidenceKind",
    "EvidenceVerdict",
    "ProofAssuranceLevel",
    "ProofAttempt",
    "ProofEvidence",
    "ProofEvidenceKind",
    "ProofPlan",
    "ProofPlanStep",
    "ProofReceipt",
    "ProofStage",
    "ProofVerdict",
    "RequiredAssuranceLevel",
    "ResourceBudget",
    "assess_assurance",
    "assurance_satisfies",
    "actionable_rejection_reason",
    "bounded_rejection_reason",
    "canonical_json",
    "canonical_json_bytes",
    "content_identity",
    "derive_assurance",
    "derive_verdict",
]
