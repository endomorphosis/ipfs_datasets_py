"""Smart-contract safety gate (CRYPTOIR-G510 / CRYPTOIR-027).

``ContractSafetyGate`` binds a transaction candidate to exact deployed
code/proxy/upgrade/state epochs, a named required-obligation set, proof or
simulation evidence, assumptions, and freshness, then emits a deterministic
:class:`ContractSafetyDecision`.

Acceptance (fail-closed):

* Exact code/proxy/upgrade/state epochs and the required obligation set are
  receipt-bound.
* ``disproved``, ``unsupported-required``, ``unknown``, ``stale``,
  ``unavailable``, ``errored``, ``mismatched``, or ``unexecuted`` analyses
  block automated use.
* Static, simulation, monitor, SAT, and proof authorities remain distinct and
  non-elevating.
* An upgraded contract (changed upgrade/code epoch) invalidates prior
  permission.
* Only the transaction whose exact effects and required obligations were
  evaluated may receive a non-blocking decision.

This module issues safety *composition results* only.  It never signs,
broadcasts, or accepts bare booleans / caller approval as authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    AnalysisOutcome,
    TransactionVerdictOutcome,
    transaction_blocks_automation,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest

from .errors import GuardForbiddenSurfaceError, GuardPolicyError, GuardValidationError
from .models import TransactionCandidate, TransactionIntent

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

CONTRACT_SAFETY_GATE_INTERFACE: Final = "ContractSafetyGate@1"
CONTRACT_SAFETY_GATE_SCHEMA_VERSION: Final = "wallet-guard.contract-safety-gate/v1"
CODE_EPOCH_SCHEMA_VERSION: Final = "wallet-guard.code-epoch/v1"
REQUIRED_OBLIGATION_SET_SCHEMA_VERSION: Final = (
    "wallet-guard.required-obligation-set/v1"
)
CONTRACT_SAFETY_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.contract-safety-decision/v1"
)
OBLIGATION_EVIDENCE_SCHEMA_VERSION: Final = "wallet-guard.obligation-evidence/v1"
CONTRACT_SAFETY_REQUEST_SCHEMA_VERSION: Final = (
    "wallet-guard.contract-safety-request/v1"
)

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-contract-safety-v1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)

_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approval",
        "allow",
        "allowed",
        "private_key",
        "private_keys",
        "secret",
        "secrets",
        "seed",
        "mnemonic",
        "signature",
        "signatures",
        "signed_tx",
        "signed_transaction",
        "broadcast",
        "broadcast_url",
        "raw_key",
        "signing_key",
        "api_key",
        "caller_approved",
        "force_allow",
        "bypass",
    }
)


# ---------------------------------------------------------------------------
# Authority lattice (non-interchangeable)
# ---------------------------------------------------------------------------


class AnalysisAuthority(str, Enum):
    """Closed analysis-authority lattice for obligation evidence.

    Authorities answer different questions and **never elevate**:

    * ``PROOF`` — theorem / formal proof of a named obligation
    * ``STATIC`` — static analysis evidence (not a theorem proof)
    * ``SIMULATION`` — sandboxed simulation / differential evidence
    * ``MONITOR`` — bounded-trace monitor satisfaction
    * ``SAT`` — satisfiability-only solver answers

    A SAT or monitor result cannot satisfy a proof-required obligation.
    """

    PROOF = "proof"
    STATIC = "static"
    SIMULATION = "simulation"
    MONITOR = "monitor"
    SAT = "sat"


# Relative strength for *satisfaction of a required authority only*.
# Higher values may satisfy lower requirements; never the reverse.
_AUTHORITY_RANK: Final[Mapping[AnalysisAuthority, int]] = {
    AnalysisAuthority.SAT: 0,
    AnalysisAuthority.MONITOR: 1,
    AnalysisAuthority.SIMULATION: 2,
    AnalysisAuthority.STATIC: 3,
    AnalysisAuthority.PROOF: 4,
}

# Explicit non-elevation edges used by tests and composition diagnostics.
_NON_ELEVATING_PAIRS: Final[frozenset[tuple[AnalysisAuthority, AnalysisAuthority]]] = (
    frozenset(
        {
            (AnalysisAuthority.SAT, AnalysisAuthority.PROOF),
            (AnalysisAuthority.SAT, AnalysisAuthority.STATIC),
            (AnalysisAuthority.MONITOR, AnalysisAuthority.PROOF),
            (AnalysisAuthority.MONITOR, AnalysisAuthority.STATIC),
            (AnalysisAuthority.SIMULATION, AnalysisAuthority.PROOF),
            (AnalysisAuthority.STATIC, AnalysisAuthority.PROOF),
        }
    )
)


class EpochKind(str, Enum):
    """What a :class:`CodeEpoch` freezes for the safety gate."""

    CODE = "code"
    PROXY = "proxy"
    UPGRADE = "upgrade"
    STATE = "state"
    PROGRAM_DATA = "program_data"
    STORAGE = "storage"


# Outcomes that map to terminal transaction blocks when required.
_DENY_OUTCOMES: Final[frozenset[AnalysisOutcome]] = frozenset(
    {AnalysisOutcome.DISPROVED}
)
_ERROR_OUTCOMES: Final[frozenset[AnalysisOutcome]] = frozenset(
    {AnalysisOutcome.ERROR}
)
_STALE_OUTCOMES: Final[frozenset[AnalysisOutcome]] = frozenset(
    {AnalysisOutcome.STALE}
)
_UNSUPPORTED_OUTCOMES: Final[frozenset[AnalysisOutcome]] = frozenset(
    {AnalysisOutcome.UNSUPPORTED}
)
_UNKNOWN_OUTCOMES: Final[frozenset[AnalysisOutcome]] = frozenset(
    {
        AnalysisOutcome.UNKNOWN,
        AnalysisOutcome.INCONCLUSIVE,
    }
)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise GuardValidationError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise GuardValidationError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise GuardValidationError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise GuardValidationError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuardValidationError(f"{name} is not a stable identifier")
    return text


def _digest(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = _text(value, name, allow_empty=allow_empty, max_chars=96)
    if not text:
        return text
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise GuardValidationError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _timestamp(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=64)
    if not _ISO8601_RE.fullmatch(text):
        raise GuardValidationError(
            f"{name} must be an ISO-8601 UTC/offset timestamp"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuardValidationError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GuardValidationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _reject_forbidden(value: Mapping[str, Any], record_name: str) -> None:
    hit = sorted(set(value) & _FORBIDDEN_FIELDS)
    if hit:
        raise GuardForbiddenSurfaceError(
            f"{record_name} contains forbidden custody/approval field(s): "
            f"{', '.join(hit)}",
            details={"fields": hit},
        )


def _unique_ids(
    values: Any,
    name: str,
    *,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: tuple[str, ...] = ()
    elif isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise GuardValidationError(f"{name} must be a sequence of strings")
    else:
        if len(values) > MAX_COLLECTION_ITEMS:
            raise GuardValidationError(f"{name} exceeds maximum collection size")
        items = tuple(_identifier(item, f"{name} item") for item in values)
        if len(items) != len(set(items)):
            raise GuardValidationError(f"{name} values must be unique")
    if require_non_empty and not items:
        raise GuardValidationError(f"{name} must be non-empty")
    return items


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise GuardValidationError(f"unsupported {name}: {value!r}") from exc


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_expired(expiry: str, now: str) -> bool:
    return now > expiry


def authority_satisfies(
    provided: AnalysisAuthority | str,
    required: AnalysisAuthority | str,
) -> bool:
    """Return True only when *provided* may satisfy *required* without elevation.

    Distinct authorities remain non-interchangeable.  Only equal or strictly
    stronger authorities on the closed rank satisfy a requirement; SAT never
    satisfies PROOF, MONITOR never satisfies STATIC/PROOF, etc.
    """

    prov = _enum(AnalysisAuthority, provided, "provided")  # type: ignore[arg-type]
    req = _enum(AnalysisAuthority, required, "required")  # type: ignore[arg-type]
    assert isinstance(prov, AnalysisAuthority)
    assert isinstance(req, AnalysisAuthority)
    if (prov, req) in _NON_ELEVATING_PAIRS:
        return False
    # Same authority always matches.
    if prov is req:
        return True
    # Proof may satisfy any weaker requirement (still not a transaction ALLOW).
    if prov is AnalysisAuthority.PROOF:
        return True
    # Otherwise require exact match — no silent cross-family promotion.
    return False


# ---------------------------------------------------------------------------
# CodeEpoch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodeEpoch:
    """Exact deployed code/proxy/upgrade/state epoch bound into a safety decision.

    Mutable control planes (proxy implementation, upgrade authority) and live
    code are epochs: changing the epoch invalidates dependent permission.
    """

    epoch_id: str
    subject_id: str
    kind: EpochKind
    value_digest: str
    network: str = ""
    chain_namespace: str = ""
    code_digest: str = ""
    proxy_implementation_digest: str = ""
    upgrade_authority_digest: str = ""
    state_digest: str = ""
    block_or_slot: str = ""
    observed_at: str = ""
    expires_at: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CODE_EPOCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch_id", _identifier(self.epoch_id, "epoch_id"))
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(self, "kind", _enum(EpochKind, self.kind, "kind"))
        object.__setattr__(
            self, "value_digest", _digest(self.value_digest, "value_digest")
        )
        object.__setattr__(
            self,
            "network",
            _text(self.network, "network", allow_empty=True, max_chars=128),
        )
        object.__setattr__(
            self,
            "chain_namespace",
            _text(
                self.chain_namespace, "chain_namespace", allow_empty=True, max_chars=128
            ),
        )
        for name in (
            "code_digest",
            "proxy_implementation_digest",
            "upgrade_authority_digest",
            "state_digest",
        ):
            object.__setattr__(
                self, name, _digest(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(
            self,
            "block_or_slot",
            _text(self.block_or_slot, "block_or_slot", allow_empty=True, max_chars=128),
        )
        if self.observed_at:
            object.__setattr__(
                self, "observed_at", _timestamp(self.observed_at, "observed_at")
            )
        else:
            object.__setattr__(self, "observed_at", "")
        if self.expires_at:
            object.__setattr__(
                self, "expires_at", _timestamp(self.expires_at, "expires_at")
            )
        else:
            object.__setattr__(self, "expires_at", "")
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "CodeEpoch.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != CODE_EPOCH_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported CodeEpoch schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def is_stale(self, now: str) -> bool:
        if not self.expires_at:
            return False
        return _is_expired(self.expires_at, now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "block_or_slot": self.block_or_slot,
            "chain_namespace": self.chain_namespace,
            "code_digest": self.code_digest,
            "epoch_id": self.epoch_id,
            "expires_at": self.expires_at,
            "kind": self.kind.value if isinstance(self.kind, EpochKind) else self.kind,
            "network": self.network,
            "observed_at": self.observed_at,
            "proxy_implementation_digest": self.proxy_implementation_digest,
            "schema_version": self.schema_version,
            "state_digest": self.state_digest,
            "subject_id": self.subject_id,
            "upgrade_authority_digest": self.upgrade_authority_digest,
            "value_digest": self.value_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CodeEpoch":
        value = _mapping(value, "CodeEpoch")
        _reject_forbidden(value, "CodeEpoch")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "block_or_slot",
                    "chain_namespace",
                    "code_digest",
                    "epoch_id",
                    "expires_at",
                    "kind",
                    "network",
                    "observed_at",
                    "proxy_implementation_digest",
                    "schema_version",
                    "state_digest",
                    "subject_id",
                    "upgrade_authority_digest",
                    "value_digest",
                }
            ),
            "CodeEpoch",
        )
        return cls(
            epoch_id=value.get("epoch_id", ""),
            subject_id=value.get("subject_id", ""),
            kind=value.get("kind", "code"),
            value_digest=value.get("value_digest", ""),
            network=value.get("network", ""),
            chain_namespace=value.get("chain_namespace", ""),
            code_digest=value.get("code_digest", ""),
            proxy_implementation_digest=value.get(
                "proxy_implementation_digest", ""
            ),
            upgrade_authority_digest=value.get("upgrade_authority_digest", ""),
            state_digest=value.get("state_digest", ""),
            block_or_slot=value.get("block_or_slot", ""),
            observed_at=value.get("observed_at", ""),
            expires_at=value.get("expires_at", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", CODE_EPOCH_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# RequiredObligationSet
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequiredObligationSet:
    """Named set of required security obligations with authority floors.

    Each obligation must be evaluated under an authority that satisfies
    :meth:`required_authority_for`.  The set is receipt-bound into every
    :class:`ContractSafetyDecision`.
    """

    set_id: str
    obligation_ids: tuple[str, ...]
    required_authority: Mapping[str, AnalysisAuthority] = field(default_factory=dict)
    default_authority: AnalysisAuthority = AnalysisAuthority.PROOF
    policy_id: str = ""
    policy_revision: str = ""
    assumption_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = REQUIRED_OBLIGATION_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "set_id", _identifier(self.set_id, "set_id"))
        object.__setattr__(
            self,
            "obligation_ids",
            _unique_ids(
                self.obligation_ids, "obligation_ids", require_non_empty=True
            ),
        )
        object.__setattr__(
            self,
            "default_authority",
            _enum(AnalysisAuthority, self.default_authority, "default_authority"),
        )
        normalized: dict[str, AnalysisAuthority] = {}
        if not isinstance(self.required_authority, Mapping):
            raise GuardValidationError("required_authority must be a mapping")
        for key, value in self.required_authority.items():
            oid = _identifier(key, "required_authority key")
            if oid not in self.obligation_ids:
                raise GuardValidationError(
                    f"required_authority key {oid!r} is not in obligation_ids"
                )
            normalized[oid] = _enum(  # type: ignore[assignment]
                AnalysisAuthority, value, f"required_authority[{oid}]"
            )
        object.__setattr__(self, "required_authority", dict(normalized))
        object.__setattr__(
            self,
            "policy_id",
            _text(self.policy_id, "policy_id", allow_empty=True, max_chars=256),
        )
        object.__setattr__(
            self,
            "policy_revision",
            _text(
                self.policy_revision,
                "policy_revision",
                allow_empty=True,
                max_chars=128,
            ),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_ids(self.assumption_ids, "assumption_ids"),
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "RequiredObligationSet.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != REQUIRED_OBLIGATION_SET_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported RequiredObligationSet schema: {self.schema_version!r}"
            )

    def required_authority_for(self, obligation_id: str) -> AnalysisAuthority:
        oid = _identifier(obligation_id, "obligation_id")
        if oid not in self.obligation_ids:
            raise GuardValidationError(
                f"obligation_id {oid!r} is not in this RequiredObligationSet"
            )
        return self.required_authority.get(oid, self.default_authority)  # type: ignore[return-value]

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        auth = {
            key: (
                value.value if isinstance(value, AnalysisAuthority) else value
            )
            for key, value in self.required_authority.items()
        }
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": dict(self.attributes),
            "default_authority": (
                self.default_authority.value
                if isinstance(self.default_authority, AnalysisAuthority)
                else self.default_authority
            ),
            "obligation_ids": list(self.obligation_ids),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "required_authority": auth,
            "schema_version": self.schema_version,
            "set_id": self.set_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RequiredObligationSet":
        value = _mapping(value, "RequiredObligationSet")
        _reject_forbidden(value, "RequiredObligationSet")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "attributes",
                    "default_authority",
                    "obligation_ids",
                    "policy_id",
                    "policy_revision",
                    "required_authority",
                    "schema_version",
                    "set_id",
                }
            ),
            "RequiredObligationSet",
        )
        return cls(
            set_id=value.get("set_id", ""),
            obligation_ids=tuple(value.get("obligation_ids", ())),
            required_authority=value.get("required_authority", {}),
            default_authority=value.get("default_authority", "proof"),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", REQUIRED_OBLIGATION_SET_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Obligation evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObligationAnalysisEvidence:
    """One analysis result for a named obligation under a bound code epoch.

    Authorities remain distinct.  ``executed=False`` is treated as unexecuted
    and always blocks automated use for required obligations.
    """

    evidence_id: str
    obligation_id: str
    outcome: AnalysisOutcome
    authority: AnalysisAuthority
    code_epoch_id: str
    code_epoch_digest: str
    executed: bool = True
    receipt_id: str = ""
    model_digest: str = ""
    assumption_ids: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()
    candidate_digest: str = ""
    intent_digest: str = ""
    freshness_expires_at: str = ""
    unavailable: bool = False
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = OBLIGATION_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "outcome", _enum(AnalysisOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self, "authority", _enum(AnalysisAuthority, self.authority, "authority")
        )
        object.__setattr__(
            self, "code_epoch_id", _identifier(self.code_epoch_id, "code_epoch_id")
        )
        object.__setattr__(
            self,
            "code_epoch_digest",
            _digest(self.code_epoch_digest, "code_epoch_digest"),
        )
        if not isinstance(self.executed, bool):
            raise GuardValidationError("executed must be a bool")
        if not isinstance(self.unavailable, bool):
            raise GuardValidationError("unavailable must be a bool")
        object.__setattr__(
            self,
            "receipt_id",
            _text(self.receipt_id, "receipt_id", allow_empty=True, max_chars=256),
        )
        object.__setattr__(
            self,
            "model_digest",
            _digest(self.model_digest, "model_digest", allow_empty=True),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_ids(self.assumption_ids, "assumption_ids"),
        )
        object.__setattr__(
            self, "effect_ids", _unique_ids(self.effect_ids, "effect_ids")
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _digest(self.candidate_digest, "candidate_digest", allow_empty=True),
        )
        object.__setattr__(
            self,
            "intent_digest",
            _digest(self.intent_digest, "intent_digest", allow_empty=True),
        )
        if self.freshness_expires_at:
            object.__setattr__(
                self,
                "freshness_expires_at",
                _timestamp(self.freshness_expires_at, "freshness_expires_at"),
            )
        else:
            object.__setattr__(self, "freshness_expires_at", "")
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "ObligationAnalysisEvidence.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def is_stale(self, now: str) -> bool:
        if not self.freshness_expires_at:
            return False
        return _is_expired(self.freshness_expires_at, now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": dict(self.attributes),
            "authority": (
                self.authority.value
                if isinstance(self.authority, AnalysisAuthority)
                else self.authority
            ),
            "candidate_digest": self.candidate_digest,
            "code_epoch_digest": self.code_epoch_digest,
            "code_epoch_id": self.code_epoch_id,
            "effect_ids": list(self.effect_ids),
            "evidence_id": self.evidence_id,
            "executed": self.executed,
            "freshness_expires_at": self.freshness_expires_at,
            "intent_digest": self.intent_digest,
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, AnalysisOutcome)
                else self.outcome
            ),
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "summary": self.summary,
            "unavailable": self.unavailable,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObligationAnalysisEvidence":
        value = _mapping(value, "ObligationAnalysisEvidence")
        _reject_forbidden(value, "ObligationAnalysisEvidence")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "attributes",
                    "authority",
                    "candidate_digest",
                    "code_epoch_digest",
                    "code_epoch_id",
                    "effect_ids",
                    "evidence_id",
                    "executed",
                    "freshness_expires_at",
                    "intent_digest",
                    "model_digest",
                    "obligation_id",
                    "outcome",
                    "receipt_id",
                    "schema_version",
                    "summary",
                    "unavailable",
                }
            ),
            "ObligationAnalysisEvidence",
        )
        return cls(
            evidence_id=value.get("evidence_id", ""),
            obligation_id=value.get("obligation_id", ""),
            outcome=value.get("outcome", "unknown"),
            authority=value.get("authority", "proof"),
            code_epoch_id=value.get("code_epoch_id", ""),
            code_epoch_digest=value.get("code_epoch_digest", ""),
            executed=value.get("executed", True),
            receipt_id=value.get("receipt_id", ""),
            model_digest=value.get("model_digest", ""),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            effect_ids=tuple(value.get("effect_ids", ())),
            candidate_digest=value.get("candidate_digest", ""),
            intent_digest=value.get("intent_digest", ""),
            freshness_expires_at=value.get("freshness_expires_at", ""),
            unavailable=value.get("unavailable", False),
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", OBLIGATION_EVIDENCE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Request + decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContractSafetyRequest:
    """Request binding candidate, epochs, obligations, and analysis evidence.

    Permits only evaluation of the exact transaction effects and obligations
    named here.  Substitution of network, candidate, effects, or epochs is
    detected at evaluation and revalidation time.
    """

    request_id: str
    intent: TransactionIntent
    candidate: TransactionCandidate
    required_obligations: RequiredObligationSet
    code_epochs: tuple[CodeEpoch, ...]
    evidence: tuple[ObligationAnalysisEvidence, ...]
    tenant_id: str
    actor_id: str
    policy_id: str
    issued_at: str
    expiry: str
    evaluated_effect_ids: tuple[str, ...] = ()
    primary_code_epoch_id: str = ""
    proxy_epoch_id: str = ""
    upgrade_epoch_id: str = ""
    state_epoch_id: str = ""
    prior_decision_digest: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SAFETY_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        if not isinstance(self.intent, TransactionIntent):
            if isinstance(self.intent, Mapping):
                object.__setattr__(
                    self, "intent", TransactionIntent.from_dict(self.intent)
                )
            else:
                raise GuardValidationError("intent must be a TransactionIntent")
        if not isinstance(self.candidate, TransactionCandidate):
            if isinstance(self.candidate, Mapping):
                object.__setattr__(
                    self,
                    "candidate",
                    TransactionCandidate.from_dict(self.candidate),
                )
            else:
                raise GuardValidationError(
                    "candidate must be a TransactionCandidate"
                )
        if self.candidate.intent_id != self.intent.intent_id:
            raise GuardValidationError(
                "candidate.intent_id must match intent.intent_id"
            )
        if self.candidate.network and self.candidate.network != self.intent.network:
            raise GuardValidationError(
                "candidate.network must match intent.network when provided"
            )
        if not isinstance(self.required_obligations, RequiredObligationSet):
            if isinstance(self.required_obligations, Mapping):
                object.__setattr__(
                    self,
                    "required_obligations",
                    RequiredObligationSet.from_dict(self.required_obligations),
                )
            else:
                raise GuardValidationError(
                    "required_obligations must be a RequiredObligationSet"
                )
        epochs = _sequence_of_epochs(self.code_epochs)
        if not epochs:
            raise GuardValidationError("at least one CodeEpoch is required")
        object.__setattr__(self, "code_epochs", epochs)
        epoch_ids = {e.epoch_id for e in epochs}
        if len(epoch_ids) != len(epochs):
            raise GuardValidationError("code_epochs epoch_id values must be unique")
        evidence_items = _sequence_of_evidence(self.evidence)
        object.__setattr__(self, "evidence", evidence_items)
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        object.__setattr__(
            self, "policy_id", _identifier(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        if self.expiry < self.issued_at:
            raise GuardValidationError("expiry must not precede issued_at")
        # Default evaluated effects = intent expected effects when omitted.
        if self.evaluated_effect_ids:
            object.__setattr__(
                self,
                "evaluated_effect_ids",
                _unique_ids(
                    self.evaluated_effect_ids,
                    "evaluated_effect_ids",
                    require_non_empty=True,
                ),
            )
        else:
            object.__setattr__(
                self,
                "evaluated_effect_ids",
                tuple(effect.effect_id for effect in self.intent.expected_effects),
            )
        intent_effect_ids = {e.effect_id for e in self.intent.expected_effects}
        for eid in self.evaluated_effect_ids:
            if eid not in intent_effect_ids:
                raise GuardValidationError(
                    f"evaluated_effect_ids item {eid!r} is not bound on the intent"
                )
        primary = self.primary_code_epoch_id or epochs[0].epoch_id
        object.__setattr__(
            self, "primary_code_epoch_id", _identifier(primary, "primary_code_epoch_id")
        )
        if self.primary_code_epoch_id not in epoch_ids:
            raise GuardValidationError(
                "primary_code_epoch_id must reference a bound CodeEpoch"
            )
        for name in ("proxy_epoch_id", "upgrade_epoch_id", "state_epoch_id"):
            raw = getattr(self, name)
            if raw:
                oid = _identifier(raw, name)
                if oid not in epoch_ids:
                    raise GuardValidationError(
                        f"{name} must reference a bound CodeEpoch"
                    )
                object.__setattr__(self, name, oid)
            else:
                object.__setattr__(self, name, "")
        object.__setattr__(
            self,
            "prior_decision_digest",
            _digest(
                self.prior_decision_digest, "prior_decision_digest", allow_empty=True
            ),
        )
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "ContractSafetyRequest.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def epoch_by_id(self, epoch_id: str) -> CodeEpoch:
        for epoch in self.code_epochs:
            if epoch.epoch_id == epoch_id:
                return epoch
        raise GuardValidationError(f"unknown code epoch: {epoch_id}")

    @property
    def intent_digest(self) -> str:
        return self.intent.digest

    @property
    def candidate_digest(self) -> str:
        return self.candidate.digest

    @property
    def request_digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "attributes": dict(self.attributes),
            "candidate": self.candidate.to_dict(),
            "code_epochs": [e.to_dict() for e in self.code_epochs],
            "evaluated_effect_ids": list(self.evaluated_effect_ids),
            "evidence": [e.to_dict() for e in self.evidence],
            "expiry": self.expiry,
            "intent": self.intent.to_dict(),
            "issued_at": self.issued_at,
            "policy_id": self.policy_id,
            "primary_code_epoch_id": self.primary_code_epoch_id,
            "prior_decision_digest": self.prior_decision_digest,
            "proxy_epoch_id": self.proxy_epoch_id,
            "request_id": self.request_id,
            "required_obligations": self.required_obligations.to_dict(),
            "schema_version": self.schema_version,
            "state_epoch_id": self.state_epoch_id,
            "tenant_id": self.tenant_id,
            "upgrade_epoch_id": self.upgrade_epoch_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractSafetyRequest":
        value = _mapping(value, "ContractSafetyRequest")
        _reject_forbidden(value, "ContractSafetyRequest")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actor_id",
                    "attributes",
                    "candidate",
                    "code_epochs",
                    "evaluated_effect_ids",
                    "evidence",
                    "expiry",
                    "intent",
                    "issued_at",
                    "policy_id",
                    "primary_code_epoch_id",
                    "prior_decision_digest",
                    "proxy_epoch_id",
                    "request_id",
                    "required_obligations",
                    "schema_version",
                    "state_epoch_id",
                    "tenant_id",
                    "upgrade_epoch_id",
                }
            ),
            "ContractSafetyRequest",
        )
        return cls(
            request_id=value.get("request_id", ""),
            intent=value.get("intent", {}),
            candidate=value.get("candidate", {}),
            required_obligations=value.get("required_obligations", {}),
            code_epochs=tuple(value.get("code_epochs", ())),
            evidence=tuple(value.get("evidence", ())),
            tenant_id=value.get("tenant_id", ""),
            actor_id=value.get("actor_id", ""),
            policy_id=value.get("policy_id", ""),
            issued_at=value.get("issued_at", ""),
            expiry=value.get("expiry", ""),
            evaluated_effect_ids=tuple(value.get("evaluated_effect_ids", ())),
            primary_code_epoch_id=value.get("primary_code_epoch_id", ""),
            proxy_epoch_id=value.get("proxy_epoch_id", ""),
            upgrade_epoch_id=value.get("upgrade_epoch_id", ""),
            state_epoch_id=value.get("state_epoch_id", ""),
            prior_decision_digest=value.get("prior_decision_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CONTRACT_SAFETY_REQUEST_SCHEMA_VERSION
            ),
        )


def _sequence_of_epochs(values: Any) -> tuple[CodeEpoch, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise GuardValidationError("code_epochs must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise GuardValidationError("code_epochs exceeds maximum collection size")
    out: list[CodeEpoch] = []
    for item in values:
        if isinstance(item, CodeEpoch):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(CodeEpoch.from_dict(item))
        else:
            raise GuardValidationError(
                "code_epochs items must be CodeEpoch or mappings"
            )
    return tuple(out)


def _sequence_of_evidence(values: Any) -> tuple[ObligationAnalysisEvidence, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise GuardValidationError("evidence must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise GuardValidationError("evidence exceeds maximum collection size")
    out: list[ObligationAnalysisEvidence] = []
    for item in values:
        if isinstance(item, ObligationAnalysisEvidence):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(ObligationAnalysisEvidence.from_dict(item))
        else:
            raise GuardValidationError(
                "evidence items must be ObligationAnalysisEvidence or mappings"
            )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class ContractSafetyDecision:
    """Deterministic, receipt-bound contract-safety decision for one candidate.

    Only :attr:`TransactionVerdictOutcome.ALLOW` with ``blocks_automation=False``
    permits automated use, and only for the exact candidate / effects /
    obligations / epochs bound into this decision.  An upgraded contract
    invalidates the decision via epoch mismatch on revalidation.
    """

    decision_id: str
    request_digest: str
    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    intent_digest: str
    candidate_digest: str
    network: str
    obligation_set_digest: str
    obligation_set_id: str
    code_epoch_digests: Mapping[str, str]
    primary_code_epoch_id: str
    primary_code_epoch_digest: str
    evaluated_effect_ids: tuple[str, ...]
    obligation_results: Mapping[str, str]
    authority_results: Mapping[str, str]
    evidence_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    issued_at: str
    expiry: str
    producer_id: str = DEFAULT_PRODUCER_ID
    proxy_epoch_id: str = ""
    upgrade_epoch_id: str = ""
    state_epoch_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_SAFETY_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "outcome",
            _enum(TransactionVerdictOutcome, self.outcome, "outcome"),
        )
        if not isinstance(self.blocks_automation, bool):
            raise GuardValidationError("blocks_automation must be a bool")
        # Consistency: only ALLOW may leave automation unblocked.
        expected_block = transaction_blocks_automation(self.outcome)  # type: ignore[arg-type]
        if self.outcome is TransactionVerdictOutcome.ALLOW:
            if self.blocks_automation:
                raise GuardValidationError(
                    "ALLOW decisions must set blocks_automation=False"
                )
        elif not self.blocks_automation:
            raise GuardValidationError(
                f"non-ALLOW outcome {self.outcome} must block automation"
            )
        if expected_block and not self.blocks_automation:
            raise GuardValidationError(
                "blocks_automation inconsistent with outcome"
            )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_ids(self.reason_codes, "reason_codes", require_non_empty=True)
            if self.reason_codes
            else ("contract.decision",),
        )
        if isinstance(self.reasons, (str, bytes, bytearray)) or not isinstance(
            self.reasons, Sequence
        ):
            raise GuardValidationError("reasons must be a sequence of strings")
        object.__setattr__(
            self,
            "reasons",
            tuple(_text(r, "reasons item") for r in self.reasons)
            if self.reasons
            else ("contract safety decision",),
        )
        object.__setattr__(
            self, "intent_digest", _digest(self.intent_digest, "intent_digest")
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _digest(self.candidate_digest, "candidate_digest"),
        )
        object.__setattr__(self, "network", _identifier(self.network, "network"))
        object.__setattr__(
            self,
            "obligation_set_digest",
            _digest(self.obligation_set_digest, "obligation_set_digest"),
        )
        object.__setattr__(
            self,
            "obligation_set_id",
            _identifier(self.obligation_set_id, "obligation_set_id"),
        )
        if not isinstance(self.code_epoch_digests, Mapping):
            raise GuardValidationError("code_epoch_digests must be a mapping")
        digests = {
            _identifier(k, "code_epoch_digests key"): _digest(
                v, f"code_epoch_digests[{k}]"
            )
            for k, v in self.code_epoch_digests.items()
        }
        object.__setattr__(self, "code_epoch_digests", digests)
        object.__setattr__(
            self,
            "primary_code_epoch_id",
            _identifier(self.primary_code_epoch_id, "primary_code_epoch_id"),
        )
        object.__setattr__(
            self,
            "primary_code_epoch_digest",
            _digest(self.primary_code_epoch_digest, "primary_code_epoch_digest"),
        )
        object.__setattr__(
            self,
            "evaluated_effect_ids",
            _unique_ids(self.evaluated_effect_ids, "evaluated_effect_ids"),
        )
        if not isinstance(self.obligation_results, Mapping):
            raise GuardValidationError("obligation_results must be a mapping")
        object.__setattr__(
            self,
            "obligation_results",
            {
                _identifier(k, "obligation_results key"): _text(
                    v, f"obligation_results[{k}]"
                )
                for k, v in self.obligation_results.items()
            },
        )
        if not isinstance(self.authority_results, Mapping):
            raise GuardValidationError("authority_results must be a mapping")
        object.__setattr__(
            self,
            "authority_results",
            {
                _identifier(k, "authority_results key"): _text(
                    v, f"authority_results[{k}]"
                )
                for k, v in self.authority_results.items()
            },
        )
        object.__setattr__(
            self, "evidence_ids", _unique_ids(self.evidence_ids, "evidence_ids")
        )
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )
        for name in ("proxy_epoch_id", "upgrade_epoch_id", "state_epoch_id"):
            raw = getattr(self, name)
            if raw:
                object.__setattr__(self, name, _identifier(raw, name))
            else:
                object.__setattr__(self, name, "")
        if not isinstance(self.attributes, Mapping):
            raise GuardValidationError("attributes must be a mapping")
        _reject_forbidden(self.attributes, "ContractSafetyDecision.attributes")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def permits_automation(self) -> bool:
        """True only for a current non-blocking ALLOW."""

        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attributes": dict(self.attributes),
            "authority_results": dict(self.authority_results),
            "blocks_automation": self.blocks_automation,
            "candidate_digest": self.candidate_digest,
            "code_epoch_digests": dict(self.code_epoch_digests),
            "decision_id": self.decision_id,
            "evaluated_effect_ids": list(self.evaluated_effect_ids),
            "evidence_ids": list(self.evidence_ids),
            "expiry": self.expiry,
            "intent_digest": self.intent_digest,
            "issued_at": self.issued_at,
            "network": self.network,
            "obligation_results": dict(self.obligation_results),
            "obligation_set_digest": self.obligation_set_digest,
            "obligation_set_id": self.obligation_set_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, TransactionVerdictOutcome)
                else self.outcome
            ),
            "primary_code_epoch_digest": self.primary_code_epoch_digest,
            "primary_code_epoch_id": self.primary_code_epoch_id,
            "producer_id": self.producer_id,
            "proxy_epoch_id": self.proxy_epoch_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "state_epoch_id": self.state_epoch_id,
            "upgrade_epoch_id": self.upgrade_epoch_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractSafetyDecision":
        value = _mapping(value, "ContractSafetyDecision")
        _reject_forbidden(value, "ContractSafetyDecision")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "attributes",
                    "authority_results",
                    "blocks_automation",
                    "candidate_digest",
                    "code_epoch_digests",
                    "decision_id",
                    "evaluated_effect_ids",
                    "evidence_ids",
                    "expiry",
                    "intent_digest",
                    "issued_at",
                    "network",
                    "obligation_results",
                    "obligation_set_digest",
                    "obligation_set_id",
                    "outcome",
                    "primary_code_epoch_digest",
                    "primary_code_epoch_id",
                    "producer_id",
                    "proxy_epoch_id",
                    "reason_codes",
                    "reasons",
                    "request_digest",
                    "schema_version",
                    "state_epoch_id",
                    "upgrade_epoch_id",
                }
            ),
            "ContractSafetyDecision",
        )
        return cls(
            decision_id=value.get("decision_id", ""),
            request_digest=value.get("request_digest", ""),
            outcome=value.get("outcome", "error"),
            blocks_automation=value.get("blocks_automation", True),
            reason_codes=tuple(value.get("reason_codes", ())),
            reasons=tuple(value.get("reasons", ())),
            intent_digest=value.get("intent_digest", ""),
            candidate_digest=value.get("candidate_digest", ""),
            network=value.get("network", ""),
            obligation_set_digest=value.get("obligation_set_digest", ""),
            obligation_set_id=value.get("obligation_set_id", ""),
            code_epoch_digests=value.get("code_epoch_digests", {}),
            primary_code_epoch_id=value.get("primary_code_epoch_id", ""),
            primary_code_epoch_digest=value.get("primary_code_epoch_digest", ""),
            evaluated_effect_ids=tuple(value.get("evaluated_effect_ids", ())),
            obligation_results=value.get("obligation_results", {}),
            authority_results=value.get("authority_results", {}),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            issued_at=value.get("issued_at", ""),
            expiry=value.get("expiry", ""),
            producer_id=value.get("producer_id", DEFAULT_PRODUCER_ID),
            proxy_epoch_id=value.get("proxy_epoch_id", ""),
            upgrade_epoch_id=value.get("upgrade_epoch_id", ""),
            state_epoch_id=value.get("state_epoch_id", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CONTRACT_SAFETY_DECISION_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@dataclass
class ContractSafetyGate:
    """Compose security analysis evidence into a contract-safety decision.

    Deterministic, fail-closed, and custody-neutral.  Does not issue signing
    capabilities (those remain owned by :class:`TransactionPreflight`); this
    gate only answers whether required contract obligations are satisfied for
    the exact candidate and epochs under evaluation.
    """

    producer_id: str = DEFAULT_PRODUCER_ID
    interface: str = CONTRACT_SAFETY_GATE_INTERFACE
    schema_version: str = CONTRACT_SAFETY_GATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.interface != CONTRACT_SAFETY_GATE_INTERFACE:
            raise GuardValidationError(
                f"unsupported contract safety gate interface: {self.interface!r}"
            )
        if self.schema_version != CONTRACT_SAFETY_GATE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported contract safety gate schema: {self.schema_version!r}"
            )
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )

    def evaluate(
        self,
        request: ContractSafetyRequest | Mapping[str, Any],
        *,
        now: str | None = None,
        live_code_epochs: Sequence[CodeEpoch | Mapping[str, Any]] | None = None,
    ) -> ContractSafetyDecision:
        """Evaluate contract safety for *request*.

        Parameters
        ----------
        request:
            Exact candidate + epoch + obligation + evidence binding.
        now:
            Evaluation clock (ISO-8601).  Defaults to UTC now.
        live_code_epochs:
            Optional live epochs used to detect upgrades / substitution after
            a prior decision.  When provided, each bound epoch id must match
            the live digest or the decision is invalidated (STALE / DENY path).
        """

        if not isinstance(request, ContractSafetyRequest):
            if isinstance(request, Mapping):
                request = ContractSafetyRequest.from_dict(request)
            else:
                raise GuardValidationError(
                    "request must be a ContractSafetyRequest"
                )

        clock = now or _iso_now()
        reason_codes: list[str] = []
        reasons: list[str] = []
        obligation_results: dict[str, str] = {}
        authority_results: dict[str, str] = {}
        blocking: TransactionVerdictOutcome | None = None

        def _block(
            outcome: TransactionVerdictOutcome, code: str, reason: str
        ) -> None:
            nonlocal blocking
            reason_codes.append(code)
            reasons.append(reason)
            blocking = _prefer_blocking(blocking, outcome)

        # Request freshness
        if _is_expired(request.expiry, clock):
            _block(
                TransactionVerdictOutcome.STALE,
                "contract.request_expired",
                "contract safety request expired before evaluation",
            )
        if _is_expired(request.intent.expires_at, clock):
            _block(
                TransactionVerdictOutcome.STALE,
                "contract.intent_expired",
                "unsigned intent expired before evaluation",
            )

        # Epoch freshness and primary binding
        primary = request.epoch_by_id(request.primary_code_epoch_id)
        for epoch in request.code_epochs:
            if epoch.is_stale(clock):
                _block(
                    TransactionVerdictOutcome.STALE,
                    f"contract.epoch_stale:{epoch.epoch_id}",
                    f"code epoch {epoch.epoch_id} is stale",
                )
            if epoch.network and epoch.network != request.intent.network:
                _block(
                    TransactionVerdictOutcome.DENY,
                    f"contract.epoch_network_mismatch:{epoch.epoch_id}",
                    f"code epoch {epoch.epoch_id} network does not match intent",
                )

        # Live upgrade / substitution detection
        if live_code_epochs is not None:
            live_map = _live_epoch_map(live_code_epochs)
            for epoch in request.code_epochs:
                live = live_map.get(epoch.epoch_id)
                if live is None:
                    # Subject-based upgrade detection for same subject_id.
                    live = _find_live_by_subject(live_map, epoch.subject_id, epoch.kind)
                if live is None:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        f"contract.epoch_unavailable:{epoch.epoch_id}",
                        f"live code epoch unavailable for {epoch.epoch_id}",
                    )
                    continue
                if live.digest != epoch.digest or live.value_digest != epoch.value_digest:
                    _block(
                        TransactionVerdictOutcome.STALE,
                        f"contract.epoch_upgraded:{epoch.epoch_id}",
                        (
                            f"code/proxy/upgrade/state epoch {epoch.epoch_id} "
                            "changed; prior permission invalidated"
                        ),
                    )

        # Index evidence by obligation (first match; extras recorded but ignored)
        evidence_by_obl: dict[str, ObligationAnalysisEvidence] = {}
        for item in request.evidence:
            if item.obligation_id not in evidence_by_obl:
                evidence_by_obl[item.obligation_id] = item

        required = request.required_obligations
        for obligation_id in required.obligation_ids:
            required_auth = required.required_authority_for(obligation_id)
            evidence = evidence_by_obl.get(obligation_id)
            if evidence is None:
                obligation_results[obligation_id] = "unexecuted"
                authority_results[obligation_id] = "none"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.unexecuted:{obligation_id}",
                    f"required obligation {obligation_id} has no analysis evidence",
                )
                continue

            authority_results[obligation_id] = (
                evidence.authority.value
                if isinstance(evidence.authority, AnalysisAuthority)
                else str(evidence.authority)
            )

            # Unavailable evidence
            if evidence.unavailable:
                obligation_results[obligation_id] = "unavailable"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.unavailable:{obligation_id}",
                    f"analysis for obligation {obligation_id} is unavailable",
                )
                continue

            # Unexecuted
            if not evidence.executed:
                obligation_results[obligation_id] = "unexecuted"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.unexecuted:{obligation_id}",
                    f"analysis for obligation {obligation_id} was not executed",
                )
                continue

            # Stale evidence / outcome
            if evidence.is_stale(clock) or evidence.outcome in _STALE_OUTCOMES:
                obligation_results[obligation_id] = "stale"
                _block(
                    TransactionVerdictOutcome.STALE,
                    f"contract.stale:{obligation_id}",
                    f"analysis for obligation {obligation_id} is stale",
                )
                continue

            # Epoch mismatch (adversarial code/proxy/state substitution)
            bound_epoch = None
            try:
                bound_epoch = request.epoch_by_id(evidence.code_epoch_id)
            except GuardValidationError:
                obligation_results[obligation_id] = "mismatched"
                _block(
                    TransactionVerdictOutcome.DENY,
                    f"contract.epoch_unknown:{obligation_id}",
                    (
                        f"evidence for {obligation_id} references unknown "
                        f"code epoch {evidence.code_epoch_id}"
                    ),
                )
                continue
            if evidence.code_epoch_digest != bound_epoch.digest:
                obligation_results[obligation_id] = "mismatched"
                _block(
                    TransactionVerdictOutcome.DENY,
                    f"contract.epoch_digest_mismatch:{obligation_id}",
                    (
                        f"evidence for {obligation_id} is not bound to the "
                        "exact code epoch digest under evaluation"
                    ),
                )
                continue
            if evidence.code_epoch_id != request.primary_code_epoch_id:
                # Evidence may bind to proxy/upgrade/state epochs when those
                # are declared; otherwise require primary.
                allowed_epoch_ids = {
                    request.primary_code_epoch_id,
                    request.proxy_epoch_id,
                    request.upgrade_epoch_id,
                    request.state_epoch_id,
                } - {""}
                if evidence.code_epoch_id not in allowed_epoch_ids:
                    obligation_results[obligation_id] = "mismatched"
                    _block(
                        TransactionVerdictOutcome.DENY,
                        f"contract.epoch_not_in_scope:{obligation_id}",
                        (
                            f"evidence for {obligation_id} binds an epoch "
                            "outside the request scope"
                        ),
                    )
                    continue

            # Candidate / intent binding (permit only evaluated transaction)
            if (
                evidence.candidate_digest
                and evidence.candidate_digest != request.candidate_digest
            ):
                obligation_results[obligation_id] = "mismatched"
                _block(
                    TransactionVerdictOutcome.DENY,
                    f"contract.candidate_mismatch:{obligation_id}",
                    (
                        f"evidence for {obligation_id} was not evaluated on "
                        "this exact candidate"
                    ),
                )
                continue
            if (
                evidence.intent_digest
                and evidence.intent_digest != request.intent_digest
            ):
                obligation_results[obligation_id] = "mismatched"
                _block(
                    TransactionVerdictOutcome.DENY,
                    f"contract.intent_mismatch:{obligation_id}",
                    (
                        f"evidence for {obligation_id} was not evaluated on "
                        "this exact intent"
                    ),
                )
                continue

            # Effect binding: evidence must cover evaluated effects when listed
            if evidence.effect_ids:
                missing_effects = [
                    eid
                    for eid in request.evaluated_effect_ids
                    if eid not in set(evidence.effect_ids)
                ]
                if missing_effects:
                    obligation_results[obligation_id] = "mismatched"
                    _block(
                        TransactionVerdictOutcome.DENY,
                        f"contract.effect_mismatch:{obligation_id}",
                        (
                            f"evidence for {obligation_id} does not cover "
                            f"evaluated effects: {', '.join(missing_effects)}"
                        ),
                    )
                    continue

            # Authority non-elevation
            if not authority_satisfies(evidence.authority, required_auth):
                obligation_results[obligation_id] = "authority_mismatch"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.authority_mismatch:{obligation_id}",
                    (
                        f"authority {evidence.authority.value} cannot satisfy "
                        f"required {required_auth.value} for {obligation_id}"
                    ),
                )
                continue

            outcome = evidence.outcome
            assert isinstance(outcome, AnalysisOutcome)

            if outcome in _DENY_OUTCOMES:
                obligation_results[obligation_id] = "disproved"
                _block(
                    TransactionVerdictOutcome.DENY,
                    f"contract.disproved:{obligation_id}",
                    f"obligation {obligation_id} was disproved",
                )
                continue
            if outcome in _ERROR_OUTCOMES:
                obligation_results[obligation_id] = "errored"
                _block(
                    TransactionVerdictOutcome.ERROR,
                    f"contract.errored:{obligation_id}",
                    f"analysis for obligation {obligation_id} errored",
                )
                continue
            if outcome in _UNSUPPORTED_OUTCOMES:
                obligation_results[obligation_id] = "unsupported_required"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.unsupported_required:{obligation_id}",
                    (
                        f"required obligation {obligation_id} is unsupported "
                        "by the analysis backend"
                    ),
                )
                continue
            if outcome in _UNKNOWN_OUTCOMES:
                obligation_results[obligation_id] = "unknown"
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.unknown:{obligation_id}",
                    f"analysis for obligation {obligation_id} is unknown/inconclusive",
                )
                continue
            if outcome is not AnalysisOutcome.PROVED:
                # Any other non-proved outcome fails closed.
                obligation_results[obligation_id] = outcome.value
                _block(
                    TransactionVerdictOutcome.INCONCLUSIVE,
                    f"contract.not_proved:{obligation_id}",
                    (
                        f"obligation {obligation_id} outcome {outcome.value} "
                        "does not prove the requirement"
                    ),
                )
                continue

            # PROVED under adequate authority
            obligation_results[obligation_id] = "proved"

        # If nothing blocked, ALLOW — only for exact evaluated effects/obligations.
        if blocking is None:
            outcome = TransactionVerdictOutcome.ALLOW
            if not reason_codes:
                reason_codes.append("contract.allow")
                reasons.append(
                    "all required obligations proved under bound code epochs"
                )
            blocks = False
        else:
            outcome = blocking
            blocks = True

        epoch_digests = {e.epoch_id: e.digest for e in request.code_epochs}
        decision_id = "decision:" + stable_digest(
            {
                "request": request.request_digest,
                "producer": self.producer_id,
                "outcome": outcome.value,
            }
        )[:32]

        return ContractSafetyDecision(
            decision_id=decision_id,
            request_digest=request.request_digest,
            outcome=outcome,
            blocks_automation=blocks,
            reason_codes=tuple(reason_codes),
            reasons=tuple(reasons),
            intent_digest=request.intent_digest,
            candidate_digest=request.candidate_digest,
            network=request.intent.network,
            obligation_set_digest=request.required_obligations.digest,
            obligation_set_id=request.required_obligations.set_id,
            code_epoch_digests=epoch_digests,
            primary_code_epoch_id=primary.epoch_id,
            primary_code_epoch_digest=primary.digest,
            evaluated_effect_ids=request.evaluated_effect_ids,
            obligation_results=obligation_results,
            authority_results=authority_results,
            evidence_ids=tuple(e.evidence_id for e in request.evidence),
            assumption_ids=request.required_obligations.assumption_ids,
            issued_at=request.issued_at,
            expiry=request.expiry,
            producer_id=self.producer_id,
            proxy_epoch_id=request.proxy_epoch_id,
            upgrade_epoch_id=request.upgrade_epoch_id,
            state_epoch_id=request.state_epoch_id,
        )

    def revalidate(
        self,
        decision: ContractSafetyDecision | Mapping[str, Any],
        request: ContractSafetyRequest | Mapping[str, Any],
        *,
        now: str | None = None,
        live_code_epochs: Sequence[CodeEpoch | Mapping[str, Any]] | None = None,
    ) -> ContractSafetyDecision:
        """Revalidate a prior decision against the live request and epochs.

        Any material change (candidate, effects, obligation set, code/proxy/
        upgrade/state epoch) invalidates prior permission and returns a
        blocking decision.
        """

        if not isinstance(decision, ContractSafetyDecision):
            if isinstance(decision, Mapping):
                decision = ContractSafetyDecision.from_dict(decision)
            else:
                raise GuardValidationError(
                    "decision must be a ContractSafetyDecision"
                )
        if not isinstance(request, ContractSafetyRequest):
            if isinstance(request, Mapping):
                request = ContractSafetyRequest.from_dict(request)
            else:
                raise GuardValidationError(
                    "request must be a ContractSafetyRequest"
                )

        clock = now or _iso_now()
        mismatches: list[str] = []
        if decision.request_digest != request.request_digest:
            mismatches.append("request_digest")
        if decision.intent_digest != request.intent_digest:
            mismatches.append("intent_digest")
        if decision.candidate_digest != request.candidate_digest:
            mismatches.append("candidate_digest")
        if decision.network != request.intent.network:
            mismatches.append("network")
        if decision.obligation_set_digest != request.required_obligations.digest:
            mismatches.append("obligation_set")
        if set(decision.evaluated_effect_ids) != set(request.evaluated_effect_ids):
            mismatches.append("evaluated_effect_ids")
        for epoch in request.code_epochs:
            prior = decision.code_epoch_digests.get(epoch.epoch_id)
            if prior is None or prior != epoch.digest:
                mismatches.append(f"epoch:{epoch.epoch_id}")

        if mismatches:
            return ContractSafetyDecision(
                decision_id="decision:" + stable_digest(
                    {
                        "prior": decision.digest,
                        "mismatches": mismatches,
                        "request": request.request_digest,
                    }
                )[:32],
                request_digest=request.request_digest,
                outcome=TransactionVerdictOutcome.STALE,
                blocks_automation=True,
                reason_codes=("contract.revalidation_mismatch",),
                reasons=(
                    "prior contract safety permission invalidated: "
                    + ", ".join(mismatches),
                ),
                intent_digest=request.intent_digest,
                candidate_digest=request.candidate_digest,
                network=request.intent.network,
                obligation_set_digest=request.required_obligations.digest,
                obligation_set_id=request.required_obligations.set_id,
                code_epoch_digests={e.epoch_id: e.digest for e in request.code_epochs},
                primary_code_epoch_id=request.primary_code_epoch_id,
                primary_code_epoch_digest=request.epoch_by_id(
                    request.primary_code_epoch_id
                ).digest,
                evaluated_effect_ids=request.evaluated_effect_ids,
                obligation_results={
                    oid: "invalidated" for oid in request.required_obligations.obligation_ids
                },
                authority_results={},
                evidence_ids=(),
                assumption_ids=request.required_obligations.assumption_ids,
                issued_at=request.issued_at,
                expiry=request.expiry,
                producer_id=self.producer_id,
                proxy_epoch_id=request.proxy_epoch_id,
                upgrade_epoch_id=request.upgrade_epoch_id,
                state_epoch_id=request.state_epoch_id,
                attributes={"mismatches": list(mismatches)},
            )

        if _is_expired(decision.expiry, clock):
            return self.evaluate(
                request, now=clock, live_code_epochs=live_code_epochs
            )

        # Re-run full evaluation with live epochs so upgrades fail closed.
        return self.evaluate(
            request, now=clock, live_code_epochs=live_code_epochs
        )


def _prefer_blocking(
    current: TransactionVerdictOutcome | None,
    candidate: TransactionVerdictOutcome,
) -> TransactionVerdictOutcome:
    """Deterministic blocker precedence: DENY > ERROR > STALE > REVIEW > INCONCLUSIVE."""

    if current is None:
        return candidate
    order = {
        TransactionVerdictOutcome.DENY: 0,
        TransactionVerdictOutcome.ERROR: 1,
        TransactionVerdictOutcome.STALE: 2,
        TransactionVerdictOutcome.REVIEW: 3,
        TransactionVerdictOutcome.INCONCLUSIVE: 4,
        TransactionVerdictOutcome.ALLOW: 5,
    }
    return current if order[current] <= order[candidate] else candidate


def _live_epoch_map(
    live_code_epochs: Sequence[CodeEpoch | Mapping[str, Any]],
) -> dict[str, CodeEpoch]:
    result: dict[str, CodeEpoch] = {}
    for item in live_code_epochs:
        if isinstance(item, CodeEpoch):
            epoch = item
        elif isinstance(item, Mapping):
            epoch = CodeEpoch.from_dict(item)
        else:
            raise GuardValidationError(
                "live_code_epochs items must be CodeEpoch or mappings"
            )
        result[epoch.epoch_id] = epoch
    return result


def _find_live_by_subject(
    live_map: Mapping[str, CodeEpoch],
    subject_id: str,
    kind: EpochKind | str,
) -> CodeEpoch | None:
    kind_value = kind.value if isinstance(kind, EpochKind) else str(kind)
    for epoch in live_map.values():
        if epoch.subject_id == subject_id and (
            epoch.kind.value if isinstance(epoch.kind, EpochKind) else epoch.kind
        ) == kind_value:
            return epoch
    return None


def evaluate_contract_safety(
    request: ContractSafetyRequest | Mapping[str, Any],
    *,
    now: str | None = None,
    live_code_epochs: Sequence[CodeEpoch | Mapping[str, Any]] | None = None,
    gate: ContractSafetyGate | None = None,
) -> ContractSafetyDecision:
    """Module-level helper matching the plan surface for contract safety."""

    engine = gate or ContractSafetyGate()
    return engine.evaluate(
        request, now=now, live_code_epochs=live_code_epochs
    )


__all__ = [
    "AnalysisAuthority",
    "CODE_EPOCH_SCHEMA_VERSION",
    "CONTRACT_SAFETY_DECISION_SCHEMA_VERSION",
    "CONTRACT_SAFETY_GATE_INTERFACE",
    "CONTRACT_SAFETY_GATE_SCHEMA_VERSION",
    "CONTRACT_SAFETY_REQUEST_SCHEMA_VERSION",
    "CodeEpoch",
    "ContractSafetyDecision",
    "ContractSafetyGate",
    "ContractSafetyRequest",
    "DEFAULT_PRODUCER_ID",
    "EpochKind",
    "OBLIGATION_EVIDENCE_SCHEMA_VERSION",
    "ObligationAnalysisEvidence",
    "REQUIRED_OBLIGATION_SET_SCHEMA_VERSION",
    "RequiredObligationSet",
    "authority_satisfies",
    "evaluate_contract_safety",
]
