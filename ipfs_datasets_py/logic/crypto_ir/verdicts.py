"""Non-interchangeable Crypto IR verdict families (CRYPTOIR-G030).

Analysis outcomes, policy/transaction verdicts, satisfiability answers,
monitor results, readiness gates, heuristics, and sanctions matches each
answer a different question.  Status strings alone never promote one family
into another: a SAT answer is not a proof, a monitor hit is not a designation,
and a proof is never a transaction ``ALLOW``.

These types are the kernel vocabulary for adapters, registries, and later
gates.  They deliberately do not import chain adapters or network clients.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ..ir_core.provenance import freeze_json, thaw_json
from .identity import crypto_ir_identity
from .provenance import (
    AuthorityBinding,
    AuthorityKind,
    CryptoIRProvenance,
    CryptoIRProvenanceError,
    freeze_json_mapping,
)
from .schema_versions import (
    CRYPTO_IR_ANALYSIS_VERDICT_SCHEMA_VERSION,
    CRYPTO_IR_KERNEL_SCHEMA_VERSION,
    CRYPTO_IR_POLICY_VERDICT_SCHEMA_VERSION,
)


CRYPTO_IR_VERDICT_DOMAIN: Final[str] = "crypto-ir.verdict"


class CryptoIRVerdictError(ValueError):
    """Raised when a verdict is malformed or authority is confused."""


class VerdictFamily(str, Enum):
    """Closed, non-hierarchical verdict families.

    Families are intentionally non-interchangeable.  Conversion helpers refuse
    silent coercion across families (see :func:`refuse_verdict_coercion`).
    """

    ANALYSIS = "analysis"
    SATISFIABILITY = "satisfiability"
    MONITOR = "monitor"
    READINESS = "readiness"
    HEURISTIC = "heuristic"
    SANCTIONS = "sanctions"
    POLICY = "policy"
    AUTHORIZATION = "authorization"


class AnalysisOutcome(str, Enum):
    """Terminal analysis vocabulary for one named obligation."""

    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"
    STALE = "stale"
    ERROR = "error"


class SatisfiabilityOutcome(str, Enum):
    """Solver-model vocabulary; never coerces into analysis proof outcomes."""

    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    UNKNOWN = "unknown"
    ERROR = "error"


class MonitorOutcome(str, Enum):
    """Bounded-trace vocabulary; never coerces into theorem proof."""

    MONITOR_SATISFIED = "monitor_satisfied"
    MONITOR_VIOLATED = "monitor_violated"
    UNKNOWN = "unknown"
    ERROR = "error"


class ReadinessOutcome(str, Enum):
    """Evidence-readiness vocabulary; never coerces into proof or policy."""

    READY = "ready"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"
    ERROR = "error"


class HeuristicOutcome(str, Enum):
    """Prioritization-only vocabulary; never designates or authorizes."""

    SIGNAL = "signal"
    NO_SIGNAL = "no_signal"
    UNKNOWN = "unknown"
    ERROR = "error"


class SanctionsMatchLevel(str, Enum):
    """Non-collapsible match-authority levels for sanctions screening."""

    EXACT_LISTED_IDENTIFIER = "exact_listed_identifier"
    NAMED_DESIGNATED_PARTY = "named_designated_party"
    OWNED_ENTITY = "owned_entity"
    DIRECT_ASSOCIATION = "direct_association"
    BOUNDED_INDIRECT_EXPOSURE = "bounded_indirect_exposure"
    HEURISTIC_ASSOCIATION = "heuristic_association"
    NO_MATCH = "no_match"
    UNKNOWN = "unknown"
    ERROR = "error"


class PolicyOutcome(str, Enum):
    """Legal/risk policy evaluation outcomes under a named policy revision."""

    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"
    UNKNOWN = "unknown"
    STALE = "stale"
    ERROR = "error"


class TransactionVerdictOutcome(str, Enum):
    """Terminal transaction policy decision for one exact candidate.

    Only ``ALLOW`` may permit automated sign/broadcast, and only under a
    current one-use capability.  All other outcomes block automation.
    """

    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"
    INCONCLUSIVE = "inconclusive"
    STALE = "stale"
    ERROR = "error"


_ANALYSIS_FAIL_CLOSED: Final[frozenset[AnalysisOutcome]] = frozenset(
    {
        AnalysisOutcome.DISPROVED,
        AnalysisOutcome.UNKNOWN,
        AnalysisOutcome.UNSUPPORTED,
        AnalysisOutcome.INCONCLUSIVE,
        AnalysisOutcome.STALE,
        AnalysisOutcome.ERROR,
    }
)

_TRANSACTION_BLOCKS_AUTOMATION: Final[frozenset[TransactionVerdictOutcome]] = frozenset(
    {
        TransactionVerdictOutcome.REVIEW,
        TransactionVerdictOutcome.DENY,
        TransactionVerdictOutcome.INCONCLUSIVE,
        TransactionVerdictOutcome.STALE,
        TransactionVerdictOutcome.ERROR,
    }
)

# Explicitly forbidden silent promotions.  Keys are source families; values are
# families that must never be produced by coercion from the source.
_FORBIDDEN_COERCIONS: Final[Mapping[VerdictFamily, frozenset[VerdictFamily]]] = (
    MappingProxyType(
        {
            VerdictFamily.SATISFIABILITY: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.POLICY,
                    VerdictFamily.AUTHORIZATION,
                    VerdictFamily.SANCTIONS,
                }
            ),
            VerdictFamily.MONITOR: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.POLICY,
                    VerdictFamily.AUTHORIZATION,
                    VerdictFamily.SANCTIONS,
                }
            ),
            VerdictFamily.READINESS: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.POLICY,
                    VerdictFamily.AUTHORIZATION,
                    VerdictFamily.SANCTIONS,
                }
            ),
            VerdictFamily.HEURISTIC: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.POLICY,
                    VerdictFamily.AUTHORIZATION,
                    VerdictFamily.SANCTIONS,
                }
            ),
            VerdictFamily.ANALYSIS: frozenset(
                {
                    VerdictFamily.AUTHORIZATION,
                    VerdictFamily.SANCTIONS,
                }
            ),
            VerdictFamily.SANCTIONS: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.AUTHORIZATION,
                }
            ),
            VerdictFamily.POLICY: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.AUTHORIZATION,
                }
            ),
            VerdictFamily.AUTHORIZATION: frozenset(
                {
                    VerdictFamily.ANALYSIS,
                    VerdictFamily.SATISFIABILITY,
                    VerdictFamily.MONITOR,
                    VerdictFamily.READINESS,
                    VerdictFamily.HEURISTIC,
                    VerdictFamily.SANCTIONS,
                    VerdictFamily.POLICY,
                }
            ),
        }
    )
)


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRVerdictError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRVerdictError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRVerdictError(f"{name} must not have surrounding whitespace")
    return value


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRVerdictError(f"unsupported {name}: {value!r}") from exc


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRVerdictError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRVerdictError(f"unknown {name} field(s): {', '.join(unknown)}")


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (TypeError, ValueError, CryptoIRProvenanceError) as exc:
        raise CryptoIRVerdictError(str(exc)) from exc


def _payload(value: Any) -> Any:
    try:
        return freeze_json(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRVerdictError(str(exc)) from exc


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRVerdictError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRVerdictError(f"{name} values must be unique")
    return result


def refuse_verdict_coercion(
    source_family: VerdictFamily | str,
    target_family: VerdictFamily | str,
    *,
    context: str = "verdict conversion",
) -> None:
    """Fail closed when *source_family* would be silently relabeled as *target*.

    Distinct families answer different questions.  Only same-family identity
    conversions are permitted without an explicit re-authoring step outside
    this module.
    """

    source = _enum(VerdictFamily, source_family, "source_family")
    target = _enum(VerdictFamily, target_family, "target_family")
    if source is target:
        return
    forbidden = _FORBIDDEN_COERCIONS.get(source, frozenset())
    if target in forbidden or source is not target:
        raise CryptoIRVerdictError(
            f"{context} cannot coerce {source.value} verdict into {target.value}"
        )


def analysis_outcome_fail_closed(outcome: AnalysisOutcome | str) -> bool:
    """Return True when *outcome* must fail closed for required obligations."""

    value = _enum(AnalysisOutcome, outcome, "outcome")
    return value in _ANALYSIS_FAIL_CLOSED


_POLICY_FAIL_CLOSED: Final[frozenset[PolicyOutcome]] = frozenset(
    {
        PolicyOutcome.FAIL,
        PolicyOutcome.REVIEW,
        PolicyOutcome.UNKNOWN,
        PolicyOutcome.STALE,
        PolicyOutcome.ERROR,
    }
)


def policy_outcome_fail_closed(outcome: PolicyOutcome | str) -> bool:
    """Return True when *outcome* must fail closed for required policy checks.

    Only :attr:`PolicyOutcome.PASS` is non-fail-closed.  Policy success is still
    not transaction authorization.
    """

    value = _enum(PolicyOutcome, outcome, "outcome")
    return value in _POLICY_FAIL_CLOSED


def transaction_blocks_automation(outcome: TransactionVerdictOutcome | str) -> bool:
    """Return True when *outcome* must block automated sign/broadcast."""

    value = _enum(TransactionVerdictOutcome, outcome, "outcome")
    if value is TransactionVerdictOutcome.ALLOW:
        return False
    return value in _TRANSACTION_BLOCKS_AUTOMATION


@dataclass(frozen=True, slots=True)
class AnalysisVerdict:
    """Terminal analysis result for one named obligation under bound assumptions.

    Authority is :attr:`AuthorityKind.RESULT`.  This record never authorizes a
    transaction and never invents designations.
    """

    verdict_id: str
    outcome: AnalysisOutcome
    obligation_id: str
    family: VerdictFamily = VerdictFamily.ANALYSIS
    assumption_ids: tuple[str, ...] = ()
    model_digest: str = ""
    backend_id: str = ""
    code_epoch: str = ""
    summary: str = ""
    payload: Any = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_ANALYSIS_VERDICT_SCHEMA_VERSION.identifier

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict_id", _text(self.verdict_id, "verdict_id"))
        object.__setattr__(
            self, "outcome", _enum(AnalysisOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        family = _enum(VerdictFamily, self.family, "family")
        if family is not VerdictFamily.ANALYSIS:
            raise CryptoIRVerdictError(
                "AnalysisVerdict family must be analysis "
                f"(got {family.value!r})"
            )
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        for name in ("model_digest", "backend_id", "code_epoch", "summary"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "payload", _payload(self.payload))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if (
            self.schema_version
            != CRYPTO_IR_ANALYSIS_VERDICT_SCHEMA_VERSION.identifier
        ):
            raise CryptoIRVerdictError(
                f"unsupported analysis verdict schema: {self.schema_version}"
            )

    @property
    def fail_closed(self) -> bool:
        return analysis_outcome_fail_closed(self.outcome)

    @property
    def authority_kind(self) -> AuthorityKind:
        return AuthorityKind.RESULT

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_VERDICT_DOMAIN}.analysis",
        )

    def cannot_authorize_transaction(self) -> bool:
        """Analysis never elevates into transaction authorization authority."""

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": thaw_json(self.attributes),
            "backend_id": self.backend_id,
            "code_epoch": self.code_epoch,
            "family": self.family.value,
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "outcome": self.outcome.value,
            "payload": thaw_json(self.payload),
            "schema_version": self.schema_version,
            "summary": self.summary,
            "verdict_id": self.verdict_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisVerdict":
        value = _as_mapping(value, "AnalysisVerdict")
        _known_fields(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "attributes",
                    "backend_id",
                    "code_epoch",
                    "family",
                    "model_digest",
                    "obligation_id",
                    "outcome",
                    "payload",
                    "schema_version",
                    "summary",
                    "verdict_id",
                }
            ),
            "AnalysisVerdict",
        )
        return cls(
            verdict_id=value.get("verdict_id", ""),
            outcome=value.get("outcome", ""),
            obligation_id=value.get("obligation_id", ""),
            family=value.get("family", VerdictFamily.ANALYSIS),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            model_digest=value.get("model_digest", ""),
            backend_id=value.get("backend_id", ""),
            code_epoch=value.get("code_epoch", ""),
            summary=value.get("summary", ""),
            payload=value.get("payload", {}),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                CRYPTO_IR_ANALYSIS_VERDICT_SCHEMA_VERSION.identifier,
            ),
        )


@dataclass(frozen=True, slots=True)
class PolicyVerdict:
    """Legal/risk policy evaluation under a named policy revision.

    Authority is :attr:`AuthorityKind.RESULT` at the policy layer.  This is not
    transaction authorization; only :class:`TransactionVerdict` under
    authorization authority may permit sign/broadcast.
    """

    verdict_id: str
    outcome: PolicyOutcome
    policy_id: str
    policy_revision: str
    family: VerdictFamily = VerdictFamily.POLICY
    jurisdiction: str = ""
    summary: str = ""
    payload: Any = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_POLICY_VERDICT_SCHEMA_VERSION.identifier

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict_id", _text(self.verdict_id, "verdict_id"))
        object.__setattr__(
            self, "outcome", _enum(PolicyOutcome, self.outcome, "outcome")
        )
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "policy_revision", _text(self.policy_revision, "policy_revision")
        )
        family = _enum(VerdictFamily, self.family, "family")
        if family is not VerdictFamily.POLICY:
            raise CryptoIRVerdictError(
                f"PolicyVerdict family must be policy (got {family.value!r})"
            )
        object.__setattr__(self, "family", family)
        for name in ("jurisdiction", "summary"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "payload", _payload(self.payload))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if (
            self.schema_version
            != CRYPTO_IR_POLICY_VERDICT_SCHEMA_VERSION.identifier
        ):
            raise CryptoIRVerdictError(
                f"unsupported policy verdict schema: {self.schema_version}"
            )

    @property
    def fail_closed(self) -> bool:
        return policy_outcome_fail_closed(self.outcome)

    @property
    def authority_kind(self) -> AuthorityKind:
        return AuthorityKind.RESULT

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_VERDICT_DOMAIN}.policy",
        )

    def cannot_authorize_transaction(self) -> bool:
        """Policy evaluation never elevates into transaction authorization."""

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "family": self.family.value,
            "jurisdiction": self.jurisdiction,
            "outcome": self.outcome.value,
            "payload": thaw_json(self.payload),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "schema_version": self.schema_version,
            "summary": self.summary,
            "verdict_id": self.verdict_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyVerdict":
        value = _as_mapping(value, "PolicyVerdict")
        _known_fields(
            value,
            frozenset(
                {
                    "attributes",
                    "family",
                    "jurisdiction",
                    "outcome",
                    "payload",
                    "policy_id",
                    "policy_revision",
                    "schema_version",
                    "summary",
                    "verdict_id",
                }
            ),
            "PolicyVerdict",
        )
        return cls(
            verdict_id=value.get("verdict_id", ""),
            outcome=value.get("outcome", ""),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            family=value.get("family", VerdictFamily.POLICY),
            jurisdiction=value.get("jurisdiction", ""),
            summary=value.get("summary", ""),
            payload=value.get("payload", {}),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                CRYPTO_IR_POLICY_VERDICT_SCHEMA_VERSION.identifier,
            ),
        )


@dataclass(frozen=True, slots=True)
class TransactionVerdict:
    """Exact-candidate transaction policy decision (authorization layer).

    Only this type under :attr:`AuthorityKind.AUTHORIZATION` may emit an
    automated ``ALLOW``.  Proof, policy, sanctions, or heuristic results cannot
    be coerced into this type.
    """

    verdict_id: str
    outcome: TransactionVerdictOutcome
    intent_id: str
    candidate_id: str
    policy_id: str
    family: VerdictFamily = VerdictFamily.AUTHORIZATION
    summary: str = ""
    reason_codes: tuple[str, ...] = ()
    payload: Any = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "ipfs-datasets.crypto-ir.transaction-verdict@1.0.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict_id", _text(self.verdict_id, "verdict_id"))
        object.__setattr__(
            self,
            "outcome",
            _enum(TransactionVerdictOutcome, self.outcome, "outcome"),
        )
        object.__setattr__(self, "intent_id", _text(self.intent_id, "intent_id"))
        object.__setattr__(
            self, "candidate_id", _text(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        family = _enum(VerdictFamily, self.family, "family")
        if family is not VerdictFamily.AUTHORIZATION:
            raise CryptoIRVerdictError(
                "TransactionVerdict family must be authorization "
                f"(got {family.value!r})"
            )
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        object.__setattr__(
            self, "reason_codes", _unique_ids(self.reason_codes, "reason_codes")
        )
        object.__setattr__(self, "payload", _payload(self.payload))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def blocks_automation(self) -> bool:
        return transaction_blocks_automation(self.outcome)

    @property
    def authority_kind(self) -> AuthorityKind:
        return AuthorityKind.AUTHORIZATION

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_VERDICT_DOMAIN}.authorization",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "candidate_id": self.candidate_id,
            "family": self.family.value,
            "intent_id": self.intent_id,
            "outcome": self.outcome.value,
            "payload": thaw_json(self.payload),
            "policy_id": self.policy_id,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "summary": self.summary,
            "verdict_id": self.verdict_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionVerdict":
        value = _as_mapping(value, "TransactionVerdict")
        _known_fields(
            value,
            frozenset(
                {
                    "attributes",
                    "candidate_id",
                    "family",
                    "intent_id",
                    "outcome",
                    "payload",
                    "policy_id",
                    "reason_codes",
                    "schema_version",
                    "summary",
                    "verdict_id",
                }
            ),
            "TransactionVerdict",
        )
        return cls(
            verdict_id=value.get("verdict_id", ""),
            outcome=value.get("outcome", ""),
            intent_id=value.get("intent_id", ""),
            candidate_id=value.get("candidate_id", ""),
            policy_id=value.get("policy_id", ""),
            family=value.get("family", VerdictFamily.AUTHORIZATION),
            summary=value.get("summary", ""),
            reason_codes=tuple(value.get("reason_codes", ())),
            payload=value.get("payload", {}),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                "ipfs-datasets.crypto-ir.transaction-verdict@1.0.0",
            ),
        )


@dataclass(frozen=True, slots=True)
class TypedFamilyVerdict:
    """Generic typed verdict for non-analysis, non-policy families.

    Used for satisfiability, monitor, readiness, heuristic, and sanctions
    results so they share round-trip/identity behavior without sharing
    outcome enums or authority elevation paths.
    """

    verdict_id: str
    family: VerdictFamily
    outcome: str
    subject_id: str = ""
    summary: str = ""
    payload: Any = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "ipfs-datasets.crypto-ir.typed-family-verdict@1.0.0"

    _ALLOWED_FAMILIES: ClassVar[frozenset[VerdictFamily]] = frozenset(
        {
            VerdictFamily.SATISFIABILITY,
            VerdictFamily.MONITOR,
            VerdictFamily.READINESS,
            VerdictFamily.HEURISTIC,
            VerdictFamily.SANCTIONS,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdict_id", _text(self.verdict_id, "verdict_id"))
        family = _enum(VerdictFamily, self.family, "family")
        if family not in TypedFamilyVerdict._ALLOWED_FAMILIES:
            raise CryptoIRVerdictError(
                f"TypedFamilyVerdict does not accept family {family.value!r}"
            )
        object.__setattr__(self, "family", family)
        outcome = _text(self.outcome, "outcome")
        # Validate outcome against the family's closed vocabulary.
        _validate_family_outcome(family, outcome)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(
            self, "subject_id", _text(self.subject_id, "subject_id", allow_empty=True)
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        object.__setattr__(self, "payload", _payload(self.payload))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def authority_kind(self) -> AuthorityKind:
        if self.family is VerdictFamily.SANCTIONS:
            return AuthorityKind.EVIDENCE
        if self.family is VerdictFamily.HEURISTIC:
            return AuthorityKind.ASSUMPTION
        return AuthorityKind.RESULT

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_VERDICT_DOMAIN}.{self.family.value}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "family": self.family.value,
            "outcome": self.outcome,
            "payload": thaw_json(self.payload),
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "summary": self.summary,
            "verdict_id": self.verdict_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TypedFamilyVerdict":
        value = _as_mapping(value, "TypedFamilyVerdict")
        _known_fields(
            value,
            frozenset(
                {
                    "attributes",
                    "family",
                    "outcome",
                    "payload",
                    "schema_version",
                    "subject_id",
                    "summary",
                    "verdict_id",
                }
            ),
            "TypedFamilyVerdict",
        )
        return cls(
            verdict_id=value.get("verdict_id", ""),
            family=value.get("family", ""),
            outcome=value.get("outcome", ""),
            subject_id=value.get("subject_id", ""),
            summary=value.get("summary", ""),
            payload=value.get("payload", {}),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version",
                "ipfs-datasets.crypto-ir.typed-family-verdict@1.0.0",
            ),
        )


def _validate_family_outcome(family: VerdictFamily, outcome: str) -> None:
    mapping: dict[VerdictFamily, type[Enum]] = {
        VerdictFamily.SATISFIABILITY: SatisfiabilityOutcome,
        VerdictFamily.MONITOR: MonitorOutcome,
        VerdictFamily.READINESS: ReadinessOutcome,
        VerdictFamily.HEURISTIC: HeuristicOutcome,
        VerdictFamily.SANCTIONS: SanctionsMatchLevel,
    }
    enum_type = mapping[family]
    try:
        enum_type(outcome)
    except ValueError as exc:
        raise CryptoIRVerdictError(
            f"unsupported {family.value} outcome: {outcome!r}"
        ) from exc


def result_family_of(value: Any) -> VerdictFamily:
    """Return the closed family of a typed Crypto IR verdict."""

    if isinstance(value, AnalysisVerdict):
        return VerdictFamily.ANALYSIS
    if isinstance(value, PolicyVerdict):
        return VerdictFamily.POLICY
    if isinstance(value, TransactionVerdict):
        return VerdictFamily.AUTHORIZATION
    if isinstance(value, TypedFamilyVerdict):
        return value.family
    raise CryptoIRVerdictError(
        f"value is not a Crypto IR verdict: {type(value).__name__}"
    )


def unavailable_analysis_verdict(
    *,
    verdict_id: str,
    obligation_id: str,
    reason: str,
    backend_id: str = "",
) -> AnalysisVerdict:
    """Fail-closed analysis result when a required capability is unavailable."""

    return AnalysisVerdict(
        verdict_id=verdict_id,
        outcome=AnalysisOutcome.INCONCLUSIVE,
        obligation_id=obligation_id,
        backend_id=backend_id,
        summary=reason,
        payload={"unavailable": True, "reason": reason},
    )


def unavailable_policy_verdict(
    *,
    verdict_id: str,
    policy_id: str,
    policy_revision: str,
    reason: str,
) -> PolicyVerdict:
    """Fail-closed policy result when a required capability is unavailable."""

    return PolicyVerdict(
        verdict_id=verdict_id,
        outcome=PolicyOutcome.ERROR,
        policy_id=policy_id,
        policy_revision=policy_revision,
        summary=reason,
        payload={"unavailable": True, "reason": reason},
    )


def default_result_provenance(
    *,
    producer_id: str,
    policy_id: str = "",
) -> CryptoIRProvenance:
    """Build result-layer provenance for a typed verdict producer."""

    return CryptoIRProvenance(
        authority=AuthorityBinding(
            kind=AuthorityKind.RESULT,
            policy_id=policy_id,
        ),
        producer_id=producer_id,
    )


__all__ = [
    "CRYPTO_IR_VERDICT_DOMAIN",
    "AnalysisOutcome",
    "AnalysisVerdict",
    "CryptoIRVerdictError",
    "HeuristicOutcome",
    "MonitorOutcome",
    "PolicyOutcome",
    "PolicyVerdict",
    "ReadinessOutcome",
    "SanctionsMatchLevel",
    "SatisfiabilityOutcome",
    "TransactionVerdict",
    "TransactionVerdictOutcome",
    "TypedFamilyVerdict",
    "VerdictFamily",
    "analysis_outcome_fail_closed",
    "default_result_provenance",
    "policy_outcome_fail_closed",
    "refuse_verdict_coercion",
    "result_family_of",
    "transaction_blocks_automation",
    "unavailable_analysis_verdict",
    "unavailable_policy_verdict",
]
