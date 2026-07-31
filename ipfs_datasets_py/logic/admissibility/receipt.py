"""Exact-context decision receipts and capability contracts (LIG-034).

Interfaces:

* ``DecisionReceipt@1`` — immutable, content-addressed binding of an
  authorization decision to its full evaluation context (request, actor,
  audience, tool, effects, evidence, roots, times, producer, …).
* ``AuthorizationCapability@1`` — short-lived, audience-bound, one-time
  dispatch capability derived **only** from an ``allow`` receipt under
  strict subset attenuation.

This leaf owns codecs and pure verification only.  It does not implement
service evaluation, persistence, dispatch, consumption stores, or signing
infrastructure (those belong to LIG-035/LIG-036).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.identity import cid_v1_from_digest
from .compose import (
    AUTHORIZATION_DECISION_INTERFACE,
    AuthorizationDecision,
    InternalDecisionStatus,
    map_internal_to_wire,
)
from .reasons import AdmissibilityStatus


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

DECISION_RECEIPT_INTERFACE: Final = "DecisionReceipt@1"
DECISION_RECEIPT_SCHEMA_VERSION: Final = "decision-receipt/v1"
AUTHORIZATION_CAPABILITY_INTERFACE: Final = "AuthorizationCapability@1"
AUTHORIZATION_CAPABILITY_SCHEMA_VERSION: Final = "authorization-capability/v1"
BOUND_ROOTS_SCHEMA_VERSION: Final = "decision-receipt-bound-roots/v1"
BOUND_CONTEXT_SCHEMA_VERSION: Final = "decision-receipt-bound-context/v1"

# Closed algorithm vocabulary for receipt / capability integrity identity.
# Cryptographic signing is intentionally out of scope for this leaf; the
# algorithm tags only the content-addressing / binding scheme.
KNOWN_IDENTITY_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {
        "sha256-canonical-json/v1",
    }
)
DEFAULT_IDENTITY_ALGORITHM: Final = "sha256-canonical-json/v1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_REASON_CHARS: Final = 512
MAX_STRING_CHARS: Final = 4_096

_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE: Final = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_ISO8601_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class ReceiptError(ValueError):
    """Raised when a decision receipt or capability fails closed."""


class CapabilityDerivationError(ReceiptError):
    """Raised when a capability cannot be derived or attenuated safely."""


class ReceiptVerificationError(ReceiptError):
    """Raised when an existing receipt or capability fails verification."""


# ---------------------------------------------------------------------------
# Low-level validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise ReceiptError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise ReceiptError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise ReceiptError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise ReceiptError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise ReceiptError(f"{name} is not a stable identifier")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, name)


def _digest(value: Any, name: str) -> str:
    """Normalize to bare lowercase SHA-256 hex (64 chars)."""

    text = _text(value, name, max_chars=80)
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise ReceiptError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _optional_digest(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _digest(value, name)


def _content_digest_tag(hex_digest: str) -> str:
    return f"sha256:{hex_digest}"


def _timestamp(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if value in (None, ""):
        if allow_empty:
            return ""
        raise ReceiptError(f"{name} must be a non-empty ISO-8601 timestamp")
    text = _text(value, name, max_chars=64)
    if not _ISO8601_RE.fullmatch(text):
        raise ReceiptError(
            f"{name} must be an ISO-8601 UTC/offset timestamp"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ReceiptError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ReceiptError(f"{name} must be one of: {allowed}") from exc


def _unique_sorted_ids(
    values: Any,
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
    require_identifier: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ReceiptError(f"{name} must be a sequence of strings")
    if len(values) > max_items:
        raise ReceiptError(f"{name} exceeds maximum of {max_items} items")
    if require_identifier:
        items = tuple(_identifier(item, f"{name} item") for item in values)
    else:
        items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise ReceiptError(f"{name} must be unique")
    return tuple(sorted(items))


def _unique_sorted_digests(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ReceiptError(f"{name} must be a sequence of digests")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise ReceiptError(f"{name} exceeds maximum collection size")
    items = tuple(_digest(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise ReceiptError(f"{name} must be unique")
    return tuple(sorted(items))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_hex(payload: Mapping[str, Any] | str | bytes) -> str:
    if isinstance(payload, bytes):
        data = payload
    elif isinstance(payload, str):
        data = payload.encode("utf-8")
    else:
        data = _canonical_bytes(payload)
    return hashlib.sha256(data).hexdigest()


def _is_subset(child: Sequence[str], parent: Sequence[str]) -> bool:
    return set(child).issubset(set(parent))


def _is_strict_subset(child: Sequence[str], parent: Sequence[str]) -> bool:
    child_set = set(child)
    parent_set = set(parent)
    return child_set.issubset(parent_set) and child_set != parent_set


def _algorithm(value: Any, name: str) -> str:
    text = _text(value, name)
    if text not in KNOWN_IDENTITY_ALGORITHMS:
        raise ReceiptError(
            f"unknown {name}: {text!r}; expected one of: "
            f"{', '.join(sorted(KNOWN_IDENTITY_ALGORITHMS))}"
        )
    return text


# ---------------------------------------------------------------------------
# Bound roots and context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundRoots:
    """Exact policy / corpus / revocation / circuit / VK roots for a decision.

    Any later consumer must revalidate against the same roots; substitution
    or "latest" aliases are fail-closed.
    """

    policy_root: str
    corpus_roots: tuple[str, ...] = ()
    revocation_root: str = ""
    circuit_roots: tuple[str, ...] = ()
    vk_roots: tuple[str, ...] = ()
    schema_version: str = BOUND_ROOTS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_root", _text(self.policy_root, "policy_root")
        )
        object.__setattr__(
            self,
            "corpus_roots",
            _unique_sorted_ids(self.corpus_roots, "corpus_roots"),
        )
        object.__setattr__(
            self,
            "revocation_root",
            _optional_text(self.revocation_root, "revocation_root"),
        )
        object.__setattr__(
            self,
            "circuit_roots",
            _unique_sorted_ids(self.circuit_roots, "circuit_roots"),
        )
        object.__setattr__(
            self,
            "vk_roots",
            _unique_sorted_ids(self.vk_roots, "vk_roots"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != BOUND_ROOTS_SCHEMA_VERSION:
            raise ReceiptError(
                f"unsupported bound-roots schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit_roots": list(self.circuit_roots),
            "corpus_roots": list(self.corpus_roots),
            "policy_root": self.policy_root,
            "revocation_root": self.revocation_root,
            "schema_version": self.schema_version,
            "vk_roots": list(self.vk_roots),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundRoots":
        value = _mapping(value, "bound roots")
        _reject_unknown(
            value,
            frozenset(
                {
                    "circuit_roots",
                    "corpus_roots",
                    "policy_root",
                    "revocation_root",
                    "schema_version",
                    "vk_roots",
                }
            ),
            "bound roots",
        )
        return cls(
            policy_root=value.get("policy_root", ""),
            corpus_roots=tuple(value.get("corpus_roots", ())),
            revocation_root=value.get("revocation_root", ""),
            circuit_roots=tuple(value.get("circuit_roots", ())),
            vk_roots=tuple(value.get("vk_roots", ())),
            schema_version=value.get(
                "schema_version", BOUND_ROOTS_SCHEMA_VERSION
            ),
        )

    def matches(self, other: "BoundRoots") -> bool:
        return (
            self.policy_root == other.policy_root
            and self.corpus_roots == other.corpus_roots
            and self.revocation_root == other.revocation_root
            and self.circuit_roots == other.circuit_roots
            and self.vk_roots == other.vk_roots
        )


@dataclass(frozen=True, slots=True)
class BoundContext:
    """Exact request context bound into a decision receipt.

    Holds digests / identifiers for request, arguments, actor, delegation,
    audience, tool, effects, and environment.  Raw secrets and unrestricted
    private arguments never enter this structure.
    """

    request_digest: str
    arguments_digest: str
    actor_id: str
    audience_id: str
    tool_id: str = ""
    tool_version: str = ""
    effect_ids: tuple[str, ...] = ()
    environment_digest: str = ""
    environment_id: str = ""
    delegation_ids: tuple[str, ...] = ()
    delegation_digest: str = ""
    resource_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    nonce: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BOUND_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_digest",
            _digest(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self,
            "arguments_digest",
            _digest(self.arguments_digest, "arguments_digest"),
        )
        object.__setattr__(
            self, "actor_id", _identifier(self.actor_id, "actor_id")
        )
        object.__setattr__(
            self, "audience_id", _identifier(self.audience_id, "audience_id")
        )
        object.__setattr__(
            self, "tool_id", _optional_identifier(self.tool_id, "tool_id")
        )
        object.__setattr__(
            self,
            "tool_version",
            _optional_text(self.tool_version, "tool_version"),
        )
        object.__setattr__(
            self,
            "effect_ids",
            _unique_sorted_ids(
                self.effect_ids, "effect_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self,
            "environment_digest",
            _optional_digest(self.environment_digest, "environment_digest"),
        )
        object.__setattr__(
            self,
            "environment_id",
            _optional_identifier(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self,
            "delegation_ids",
            _unique_sorted_ids(
                self.delegation_ids, "delegation_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self,
            "delegation_digest",
            _optional_digest(self.delegation_digest, "delegation_digest"),
        )
        object.__setattr__(
            self,
            "resource_ids",
            _unique_sorted_ids(
                self.resource_ids, "resource_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self,
            "capability_ids",
            _unique_sorted_ids(
                self.capability_ids, "capability_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self, "nonce", _text(self.nonce, "nonce", max_chars=128)
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != BOUND_CONTEXT_SCHEMA_VERSION:
            raise ReceiptError(
                f"unsupported bound-context schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "arguments_digest": self.arguments_digest,
            "audience_id": self.audience_id,
            "capability_ids": list(self.capability_ids),
            "delegation_digest": self.delegation_digest,
            "delegation_ids": list(self.delegation_ids),
            "effect_ids": list(self.effect_ids),
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "metadata": self.metadata.to_dict(),
            "nonce": self.nonce,
            "request_digest": self.request_digest,
            "resource_ids": list(self.resource_ids),
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundContext":
        value = _mapping(value, "bound context")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actor_id",
                    "arguments_digest",
                    "audience_id",
                    "capability_ids",
                    "delegation_digest",
                    "delegation_ids",
                    "effect_ids",
                    "environment_digest",
                    "environment_id",
                    "metadata",
                    "nonce",
                    "request_digest",
                    "resource_ids",
                    "schema_version",
                    "tool_id",
                    "tool_version",
                }
            ),
            "bound context",
        )
        return cls(
            request_digest=value.get("request_digest", ""),
            arguments_digest=value.get("arguments_digest", ""),
            actor_id=value.get("actor_id", ""),
            audience_id=value.get("audience_id", ""),
            tool_id=value.get("tool_id", ""),
            tool_version=value.get("tool_version", ""),
            effect_ids=tuple(value.get("effect_ids", ())),
            environment_digest=value.get("environment_digest", ""),
            environment_id=value.get("environment_id", ""),
            delegation_ids=tuple(value.get("delegation_ids", ())),
            delegation_digest=value.get("delegation_digest", ""),
            resource_ids=tuple(value.get("resource_ids", ())),
            capability_ids=tuple(value.get("capability_ids", ())),
            nonce=value.get("nonce", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", BOUND_CONTEXT_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# DecisionReceipt@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionReceipt:
    """``DecisionReceipt@1`` — consumer-verifiable exact-context decision.

    Binds the full request digest, selected evidence, obligations / attempts /
    results, decision policy, corpus and revocation roots, environment facts,
    actor, audience, nonce, issued / deadline / expiry times, allowed effects,
    residual duties, and producer.  Identity is content-addressed; mutation of
    any bound field yields a different digest and fails verification.
    """

    receipt_id: str
    context: BoundContext
    roots: BoundRoots
    outcome: InternalDecisionStatus
    wire_status: AdmissibilityStatus
    reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    selected_evidence_cids: tuple[str, ...]
    selected_evidence_digest: str
    obligation_ids: tuple[str, ...]
    residual_duties: tuple[str, ...]
    attempt_digests: tuple[str, ...]
    result_digests: tuple[str, ...]
    decision_digest: str
    policy_digest: str
    profile_id: str
    issued_at: str
    deadline: str
    expiry: str
    producer_id: str
    decision_interface: str = AUTHORIZATION_DECISION_INTERFACE
    identity_algorithm: str = DEFAULT_IDENTITY_ALGORITHM
    content_digest: str = ""
    content_cid: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    interface: str = DECISION_RECEIPT_INTERFACE
    schema_version: str = DECISION_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        if not isinstance(self.context, BoundContext):
            if isinstance(self.context, Mapping):
                object.__setattr__(
                    self, "context", BoundContext.from_dict(self.context)
                )
            else:
                raise ReceiptError("context must be a BoundContext")
        if not isinstance(self.roots, BoundRoots):
            if isinstance(self.roots, Mapping):
                object.__setattr__(
                    self, "roots", BoundRoots.from_dict(self.roots)
                )
            else:
                raise ReceiptError("roots must be a BoundRoots")

        object.__setattr__(
            self,
            "outcome",
            _enum(self.outcome, InternalDecisionStatus, "outcome"),
        )
        object.__setattr__(
            self,
            "wire_status",
            _enum(self.wire_status, AdmissibilityStatus, "wire_status"),
        )
        expected_wire = map_internal_to_wire(self.outcome)
        if self.wire_status is not expected_wire:
            raise ReceiptError(
                f"wire_status {self.wire_status.value!r} inconsistent with "
                f"outcome {self.outcome.value!r} "
                f"(expected {expected_wire.value!r})"
            )

        object.__setattr__(
            self,
            "reasons",
            _unique_sorted_ids(self.reasons, "reasons"),
        )
        for reason in self.reasons:
            if len(reason) > MAX_REASON_CHARS:
                raise ReceiptError("reason exceeds maximum length")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_sorted_ids(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "selected_evidence_cids",
            _unique_sorted_ids(
                self.selected_evidence_cids, "selected_evidence_cids"
            ),
        )
        object.__setattr__(
            self,
            "selected_evidence_digest",
            _digest(self.selected_evidence_digest, "selected_evidence_digest"),
        )
        object.__setattr__(
            self,
            "obligation_ids",
            _unique_sorted_ids(self.obligation_ids, "obligation_ids"),
        )
        object.__setattr__(
            self,
            "residual_duties",
            _unique_sorted_ids(self.residual_duties, "residual_duties"),
        )
        object.__setattr__(
            self,
            "attempt_digests",
            _unique_sorted_digests(self.attempt_digests, "attempt_digests"),
        )
        object.__setattr__(
            self,
            "result_digests",
            _unique_sorted_digests(self.result_digests, "result_digests"),
        )
        object.__setattr__(
            self,
            "decision_digest",
            _digest(self.decision_digest, "decision_digest"),
        )
        object.__setattr__(
            self, "policy_digest", _digest(self.policy_digest, "policy_digest")
        )
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "deadline", _timestamp(self.deadline, "deadline")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        if self.deadline < self.issued_at:
            raise ReceiptError("deadline must not precede issued_at")
        if self.expiry < self.issued_at:
            raise ReceiptError("expiry must not precede issued_at")
        if self.expiry < self.deadline:
            raise ReceiptError("expiry must not precede deadline")
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self,
            "decision_interface",
            _text(self.decision_interface, "decision_interface"),
        )
        if self.decision_interface != AUTHORIZATION_DECISION_INTERFACE:
            raise ReceiptError(
                f"unsupported decision interface: {self.decision_interface!r}"
            )
        object.__setattr__(
            self,
            "identity_algorithm",
            _algorithm(self.identity_algorithm, "identity_algorithm"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.interface != DECISION_RECEIPT_INTERFACE:
            raise ReceiptError(
                f"unsupported decision receipt interface: {self.interface!r}"
            )
        if self.schema_version != DECISION_RECEIPT_SCHEMA_VERSION:
            raise ReceiptError(
                f"unsupported decision receipt schema: {self.schema_version!r}"
            )

        body = self._identity_payload()
        digest_hex = _sha256_hex(body)
        digest_tag = _content_digest_tag(digest_hex)
        cid = cid_v1_from_digest(bytes.fromhex(digest_hex))
        if self.content_digest:
            provided = self.content_digest
            if provided.startswith("sha256:"):
                provided_hex = provided[len("sha256:") :]
            else:
                provided_hex = provided
            if provided_hex != digest_hex:
                raise ReceiptError(
                    "content_digest does not match recomputed receipt identity"
                )
        if self.content_cid and self.content_cid != cid:
            raise ReceiptError(
                "content_cid does not match recomputed receipt identity"
            )
        object.__setattr__(self, "content_digest", digest_tag)
        object.__setattr__(self, "content_cid", cid)

    # -- derived properties -------------------------------------------------

    @property
    def is_allow(self) -> bool:
        return self.outcome is InternalDecisionStatus.ALLOW

    @property
    def is_deny(self) -> bool:
        return self.outcome is InternalDecisionStatus.DENY

    @property
    def permits_capability_derivation(self) -> bool:
        """Only exact allow outcomes may mint a dispatch capability."""

        return (
            self.outcome is InternalDecisionStatus.ALLOW
            and self.wire_status is AdmissibilityStatus.ALLOW
        )

    @property
    def digest(self) -> str:
        """Bare hex form of the content digest."""

        return self.content_digest.removeprefix("sha256:")

    @property
    def nonce(self) -> str:
        return self.context.nonce

    @property
    def audience_id(self) -> str:
        return self.context.audience_id

    @property
    def actor_id(self) -> str:
        return self.context.actor_id

    @property
    def request_digest(self) -> str:
        return self.context.request_digest

    @property
    def effect_ids(self) -> tuple[str, ...]:
        return self.context.effect_ids

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "attempt_digests": list(self.attempt_digests),
            "context": self.context.to_dict(),
            "decision_digest": self.decision_digest,
            "decision_interface": self.decision_interface,
            "identity_algorithm": self.identity_algorithm,
            "interface": self.interface,
            "issued_at": self.issued_at,
            "deadline": self.deadline,
            "expiry": self.expiry,
            "metadata": self.metadata.to_dict(),
            "obligation_ids": list(self.obligation_ids),
            "outcome": self.outcome.value,
            "policy_digest": self.policy_digest,
            "producer_id": self.producer_id,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "receipt_id": self.receipt_id,
            "residual_duties": list(self.residual_duties),
            "result_digests": list(self.result_digests),
            "roots": self.roots.to_dict(),
            "schema_version": self.schema_version,
            "selected_evidence_cids": list(self.selected_evidence_cids),
            "selected_evidence_digest": self.selected_evidence_digest,
            "wire_status": self.wire_status.value,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionReceipt":
        value = _mapping(value, "decision receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attempt_digests",
                    "content_cid",
                    "content_digest",
                    "context",
                    "decision_digest",
                    "decision_interface",
                    "deadline",
                    "expiry",
                    "identity_algorithm",
                    "interface",
                    "issued_at",
                    "metadata",
                    "obligation_ids",
                    "outcome",
                    "policy_digest",
                    "producer_id",
                    "profile_id",
                    "reason_codes",
                    "reasons",
                    "receipt_id",
                    "residual_duties",
                    "result_digests",
                    "roots",
                    "schema_version",
                    "selected_evidence_cids",
                    "selected_evidence_digest",
                    "wire_status",
                }
            ),
            "decision receipt",
        )
        return cls(
            receipt_id=value.get("receipt_id", ""),
            context=value.get("context", {}),
            roots=value.get("roots", {}),
            outcome=value.get("outcome", ""),
            wire_status=value.get("wire_status", ""),
            reasons=tuple(value.get("reasons", ())),
            reason_codes=tuple(value.get("reason_codes", ())),
            selected_evidence_cids=tuple(
                value.get("selected_evidence_cids", ())
            ),
            selected_evidence_digest=value.get(
                "selected_evidence_digest", ""
            ),
            obligation_ids=tuple(value.get("obligation_ids", ())),
            residual_duties=tuple(value.get("residual_duties", ())),
            attempt_digests=tuple(value.get("attempt_digests", ())),
            result_digests=tuple(value.get("result_digests", ())),
            decision_digest=value.get("decision_digest", ""),
            policy_digest=value.get("policy_digest", ""),
            profile_id=value.get("profile_id", ""),
            issued_at=value.get("issued_at", ""),
            deadline=value.get("deadline", ""),
            expiry=value.get("expiry", ""),
            producer_id=value.get("producer_id", ""),
            decision_interface=value.get(
                "decision_interface", AUTHORIZATION_DECISION_INTERFACE
            ),
            identity_algorithm=value.get(
                "identity_algorithm", DEFAULT_IDENTITY_ALGORITHM
            ),
            content_digest=value.get("content_digest", ""),
            content_cid=value.get("content_cid", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            interface=value.get("interface", DECISION_RECEIPT_INTERFACE),
            schema_version=value.get(
                "schema_version", DECISION_RECEIPT_SCHEMA_VERSION
            ),
        )

    def verify_integrity(self) -> "DecisionReceipt":
        """Recompute identity; fail closed on digest / CID drift."""

        body = self._identity_payload()
        digest_hex = _sha256_hex(body)
        digest_tag = _content_digest_tag(digest_hex)
        cid = cid_v1_from_digest(bytes.fromhex(digest_hex))
        if digest_tag != self.content_digest:
            raise ReceiptVerificationError(
                "content_digest does not match recomputed receipt identity"
            )
        if cid != self.content_cid:
            raise ReceiptVerificationError(
                "content_cid does not match recomputed receipt identity"
            )
        return self


# ---------------------------------------------------------------------------
# AuthorizationCapability@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationCapability:
    """``AuthorizationCapability@1`` — exact, attenuated, one-time dispatch token.

    Derived only from an allow decision receipt.  Rights are a strict subset
    (proper subset of the parent effect set when attenuating) of the receipt's
    allowed effects, audience-bound, short-lived, and marked ``one_time``.
    """

    capability_id: str
    receipt_id: str
    receipt_digest: str
    audience_id: str
    request_digest: str
    allowed_effects: tuple[str, ...]
    resource_ids: tuple[str, ...]
    tool_id: str
    roots: BoundRoots
    one_time: bool
    nonce: str
    issued_at: str
    expiry: str
    producer_id: str
    parent_capability_id: str = ""
    parent_capability_digest: str = ""
    identity_algorithm: str = DEFAULT_IDENTITY_ALGORITHM
    content_digest: str = ""
    content_cid: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    interface: str = AUTHORIZATION_CAPABILITY_INTERFACE
    schema_version: str = AUTHORIZATION_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_id",
            _identifier(self.capability_id, "capability_id"),
        )
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "receipt_digest",
            _digest(self.receipt_digest, "receipt_digest"),
        )
        object.__setattr__(
            self, "audience_id", _identifier(self.audience_id, "audience_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _digest(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self,
            "allowed_effects",
            _unique_sorted_ids(
                self.allowed_effects,
                "allowed_effects",
                require_identifier=True,
            ),
        )
        if not self.allowed_effects:
            raise ReceiptError(
                "allowed_effects must be a non-empty attenuated set"
            )
        object.__setattr__(
            self,
            "resource_ids",
            _unique_sorted_ids(
                self.resource_ids, "resource_ids", require_identifier=True
            ),
        )
        object.__setattr__(
            self, "tool_id", _optional_identifier(self.tool_id, "tool_id")
        )
        if not isinstance(self.roots, BoundRoots):
            if isinstance(self.roots, Mapping):
                object.__setattr__(
                    self, "roots", BoundRoots.from_dict(self.roots)
                )
            else:
                raise ReceiptError("roots must be a BoundRoots")
        if not isinstance(self.one_time, bool):
            raise ReceiptError("one_time must be a bool")
        if not self.one_time:
            raise ReceiptError(
                "authorization capabilities must carry the one-time marker"
            )
        object.__setattr__(
            self, "nonce", _text(self.nonce, "nonce", max_chars=128)
        )
        object.__setattr__(
            self, "issued_at", _timestamp(self.issued_at, "issued_at")
        )
        object.__setattr__(self, "expiry", _timestamp(self.expiry, "expiry"))
        if self.expiry < self.issued_at:
            raise ReceiptError("capability expiry must not precede issued_at")
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self,
            "parent_capability_id",
            _optional_identifier(
                self.parent_capability_id, "parent_capability_id"
            ),
        )
        object.__setattr__(
            self,
            "parent_capability_digest",
            _optional_digest(
                self.parent_capability_digest, "parent_capability_digest"
            ),
        )
        object.__setattr__(
            self,
            "identity_algorithm",
            _algorithm(self.identity_algorithm, "identity_algorithm"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.interface != AUTHORIZATION_CAPABILITY_INTERFACE:
            raise ReceiptError(
                f"unsupported capability interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_CAPABILITY_SCHEMA_VERSION:
            raise ReceiptError(
                f"unsupported capability schema: {self.schema_version!r}"
            )

        body = self._identity_payload()
        digest_hex = _sha256_hex(body)
        digest_tag = _content_digest_tag(digest_hex)
        cid = cid_v1_from_digest(bytes.fromhex(digest_hex))
        if self.content_digest:
            provided = self.content_digest
            if provided.startswith("sha256:"):
                provided_hex = provided[len("sha256:") :]
            else:
                provided_hex = provided
            if provided_hex != digest_hex:
                raise ReceiptError(
                    "content_digest does not match recomputed capability identity"
                )
        if self.content_cid and self.content_cid != cid:
            raise ReceiptError(
                "content_cid does not match recomputed capability identity"
            )
        object.__setattr__(self, "content_digest", digest_tag)
        object.__setattr__(self, "content_cid", cid)

    @property
    def digest(self) -> str:
        return self.content_digest.removeprefix("sha256:")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "allowed_effects": list(self.allowed_effects),
            "audience_id": self.audience_id,
            "capability_id": self.capability_id,
            "expiry": self.expiry,
            "identity_algorithm": self.identity_algorithm,
            "interface": self.interface,
            "issued_at": self.issued_at,
            "metadata": self.metadata.to_dict(),
            "nonce": self.nonce,
            "one_time": True,
            "parent_capability_digest": self.parent_capability_digest,
            "parent_capability_id": self.parent_capability_id,
            "producer_id": self.producer_id,
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "resource_ids": list(self.resource_ids),
            "roots": self.roots.to_dict(),
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorizationCapability":
        value = _mapping(value, "authorization capability")
        _reject_unknown(
            value,
            frozenset(
                {
                    "allowed_effects",
                    "audience_id",
                    "capability_id",
                    "content_cid",
                    "content_digest",
                    "expiry",
                    "identity_algorithm",
                    "interface",
                    "issued_at",
                    "metadata",
                    "nonce",
                    "one_time",
                    "parent_capability_digest",
                    "parent_capability_id",
                    "producer_id",
                    "receipt_digest",
                    "receipt_id",
                    "request_digest",
                    "resource_ids",
                    "roots",
                    "schema_version",
                    "tool_id",
                }
            ),
            "authorization capability",
        )
        return cls(
            capability_id=value.get("capability_id", ""),
            receipt_id=value.get("receipt_id", ""),
            receipt_digest=value.get("receipt_digest", ""),
            audience_id=value.get("audience_id", ""),
            request_digest=value.get("request_digest", ""),
            allowed_effects=tuple(value.get("allowed_effects", ())),
            resource_ids=tuple(value.get("resource_ids", ())),
            tool_id=value.get("tool_id", ""),
            roots=value.get("roots", {}),
            one_time=value.get("one_time", False),
            nonce=value.get("nonce", ""),
            issued_at=value.get("issued_at", ""),
            expiry=value.get("expiry", ""),
            producer_id=value.get("producer_id", ""),
            parent_capability_id=value.get("parent_capability_id", ""),
            parent_capability_digest=value.get(
                "parent_capability_digest", ""
            ),
            identity_algorithm=value.get(
                "identity_algorithm", DEFAULT_IDENTITY_ALGORITHM
            ),
            content_digest=value.get("content_digest", ""),
            content_cid=value.get("content_cid", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            interface=value.get(
                "interface", AUTHORIZATION_CAPABILITY_INTERFACE
            ),
            schema_version=value.get(
                "schema_version", AUTHORIZATION_CAPABILITY_SCHEMA_VERSION
            ),
        )

    def verify_integrity(self) -> "AuthorizationCapability":
        body = self._identity_payload()
        digest_hex = _sha256_hex(body)
        digest_tag = _content_digest_tag(digest_hex)
        cid = cid_v1_from_digest(bytes.fromhex(digest_hex))
        if digest_tag != self.content_digest:
            raise ReceiptVerificationError(
                "content_digest does not match recomputed capability identity"
            )
        if cid != self.content_cid:
            raise ReceiptVerificationError(
                "content_cid does not match recomputed capability identity"
            )
        return self


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _evidence_digest(cids: Sequence[str]) -> str:
    return stable_digest({"selected_evidence_cids": sorted(cids)})


def build_decision_receipt(
    *,
    receipt_id: str,
    context: BoundContext | Mapping[str, Any],
    roots: BoundRoots | Mapping[str, Any],
    outcome: InternalDecisionStatus | str,
    reasons: Sequence[str] = (),
    reason_codes: Sequence[str] = (),
    selected_evidence_cids: Sequence[str] = (),
    selected_evidence_digest: str = "",
    obligation_ids: Sequence[str] = (),
    residual_duties: Sequence[str] = (),
    attempt_digests: Sequence[str] = (),
    result_digests: Sequence[str] = (),
    decision_digest: str = "",
    policy_digest: str = "",
    profile_id: str,
    issued_at: str,
    deadline: str,
    expiry: str,
    producer_id: str,
    decision: AuthorizationDecision | None = None,
    wire_status: AdmissibilityStatus | str | None = None,
    metadata: Mapping[str, Any] | None = None,
    identity_algorithm: str = DEFAULT_IDENTITY_ALGORITHM,
) -> DecisionReceipt:
    """Construct a content-addressed ``DecisionReceipt@1``.

    When *decision* is supplied its digests, residual obligations, evidence,
    and status fields are bound unless explicitly overridden.
    """

    if decision is not None:
        if not isinstance(decision, AuthorizationDecision):
            raise ReceiptError("decision must be an AuthorizationDecision")
        outcome = decision.status
        if wire_status is None:
            wire_status = decision.wire_status
        if not decision_digest:
            decision_digest = decision.digest
        if not policy_digest:
            policy_digest = decision.policy_digest
        if not selected_evidence_cids:
            selected_evidence_cids = decision.selected_evidence_cids
        if not residual_duties:
            residual_duties = decision.residual_obligations
        if not reasons:
            reasons = decision.reasons
        if not reason_codes:
            reason_codes = decision.reason_codes
        if not result_digests:
            result_digests = tuple(
                item.digest for item in decision.job_results
            )
        profile_id = profile_id or decision.profile_id

    outcome_enum = _enum(outcome, InternalDecisionStatus, "outcome")
    if wire_status is None:
        wire_enum = map_internal_to_wire(outcome_enum)
    else:
        wire_enum = _enum(wire_status, AdmissibilityStatus, "wire_status")

    evidence = tuple(selected_evidence_cids)
    if not selected_evidence_digest:
        selected_evidence_digest = _evidence_digest(evidence)

    if not decision_digest:
        # Synthetic decision digest over outcome + evidence + context.
        if isinstance(context, BoundContext):
            ctx_digest = context.digest
        else:
            ctx_digest = BoundContext.from_dict(context).digest
        decision_digest = stable_digest(
            {
                "context_digest": ctx_digest,
                "outcome": outcome_enum.value,
                "selected_evidence_cids": sorted(evidence),
            }
        )
    if not policy_digest:
        if isinstance(roots, BoundRoots):
            policy_digest = roots.digest
        else:
            policy_digest = BoundRoots.from_dict(roots).digest

    return DecisionReceipt(
        receipt_id=receipt_id,
        context=context,  # type: ignore[arg-type]
        roots=roots,  # type: ignore[arg-type]
        outcome=outcome_enum,
        wire_status=wire_enum,
        reasons=tuple(reasons),
        reason_codes=tuple(reason_codes),
        selected_evidence_cids=evidence,
        selected_evidence_digest=selected_evidence_digest,
        obligation_ids=tuple(obligation_ids),
        residual_duties=tuple(residual_duties),
        attempt_digests=tuple(attempt_digests),
        result_digests=tuple(result_digests),
        decision_digest=decision_digest,
        policy_digest=policy_digest,
        profile_id=profile_id,
        issued_at=issued_at,
        deadline=deadline,
        expiry=expiry,
        producer_id=producer_id,
        identity_algorithm=identity_algorithm,
        metadata=FrozenMap(metadata or {}),
    )


def derive_capability(
    receipt: DecisionReceipt,
    *,
    capability_id: str,
    allowed_effects: Sequence[str] | None = None,
    resource_ids: Sequence[str] | None = None,
    audience_id: str | None = None,
    tool_id: str | None = None,
    issued_at: str | None = None,
    expiry: str | None = None,
    producer_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    require_strict_subset: bool = True,
) -> AuthorizationCapability:
    """Derive a one-time capability from an **allow** decision receipt.

    Attenuation rules:

    * derivation is rejected for every non-allow outcome;
    * ``allowed_effects`` must be a non-empty subset of the receipt effects;
    * when the receipt declares effects and ``require_strict_subset`` is true
      (default), the capability effects must be a **strict** (proper) subset
      unless the receipt itself has exactly one effect (then equality is the
      only possible non-empty subset and is accepted);
    * resources / tool / audience / roots / nonce bind exactly and cannot
      widen;
    * capability expiry cannot exceed the receipt expiry.
    """

    if not isinstance(receipt, DecisionReceipt):
        raise CapabilityDerivationError(
            "capability derivation requires a DecisionReceipt"
        )
    receipt.verify_integrity()

    if not receipt.permits_capability_derivation:
        raise CapabilityDerivationError(
            "capability derivation requires an allow decision receipt; "
            f"got outcome={receipt.outcome.value!r} "
            f"wire_status={receipt.wire_status.value!r}"
        )

    audience = audience_id if audience_id is not None else receipt.audience_id
    if audience != receipt.audience_id:
        raise CapabilityDerivationError(
            "capability audience must match the receipt audience "
            f"(got {audience!r}, expected {receipt.audience_id!r})"
        )

    receipt_effects = receipt.effect_ids
    if allowed_effects is None:
        if not receipt_effects:
            raise CapabilityDerivationError(
                "cannot derive capability without allowed effects on the receipt"
            )
        # Default attenuation: if multiple effects, take a single least
        # privilege element (first sorted); if one, keep it.
        if len(receipt_effects) == 1:
            effects = receipt_effects
        else:
            effects = (receipt_effects[0],)
    else:
        effects = _unique_sorted_ids(
            allowed_effects, "allowed_effects", require_identifier=True
        )
        if not effects:
            raise CapabilityDerivationError(
                "allowed_effects must be non-empty"
            )
        if receipt_effects and not _is_subset(effects, receipt_effects):
            raise CapabilityDerivationError(
                "capability allowed_effects must be a subset of receipt effects "
                "(widening is forbidden)"
            )
        if (
            require_strict_subset
            and receipt_effects
            and len(receipt_effects) > 1
            and not _is_strict_subset(effects, receipt_effects)
        ):
            raise CapabilityDerivationError(
                "capability derivation requires strict subset attenuation "
                "of receipt effects"
            )

    parent_resources = receipt.context.resource_ids
    if resource_ids is None:
        resources = parent_resources
    else:
        resources = _unique_sorted_ids(
            resource_ids, "resource_ids", require_identifier=True
        )
        if parent_resources and not _is_subset(resources, parent_resources):
            raise CapabilityDerivationError(
                "capability resource_ids must be a subset of receipt resources "
                "(widening is forbidden)"
            )

    tool = tool_id if tool_id is not None else receipt.context.tool_id
    if receipt.context.tool_id and tool and tool != receipt.context.tool_id:
        raise CapabilityDerivationError(
            "capability tool_id must match the receipt tool binding"
        )

    cap_issued = issued_at if issued_at is not None else receipt.issued_at
    cap_expiry = expiry if expiry is not None else receipt.expiry
    if cap_issued < receipt.issued_at:
        raise CapabilityDerivationError(
            "capability issued_at must not precede receipt issued_at"
        )
    if cap_expiry > receipt.expiry:
        raise CapabilityDerivationError(
            "capability expiry must not exceed receipt expiry"
        )
    if cap_expiry < cap_issued:
        raise CapabilityDerivationError(
            "capability expiry must not precede issued_at"
        )

    return AuthorizationCapability(
        capability_id=capability_id,
        receipt_id=receipt.receipt_id,
        receipt_digest=receipt.digest,
        audience_id=audience,
        request_digest=receipt.request_digest,
        allowed_effects=effects,
        resource_ids=resources,
        tool_id=tool,
        roots=receipt.roots,
        one_time=True,
        nonce=receipt.nonce,
        issued_at=cap_issued,
        expiry=cap_expiry,
        producer_id=producer_id or receipt.producer_id,
        metadata=FrozenMap(metadata or {}),
    )


def attenuate_capability(
    parent: AuthorizationCapability,
    *,
    capability_id: str,
    allowed_effects: Sequence[str],
    resource_ids: Sequence[str] | None = None,
    expiry: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuthorizationCapability:
    """Re-attenuate an existing capability under strict subset rules.

    Child effects must be a **strict** (proper) subset of the parent effects.
    Resources cannot widen.  Audience, roots, nonce, request, and one-time
    marker are preserved.  Expiry may only shrink.
    """

    if not isinstance(parent, AuthorizationCapability):
        raise CapabilityDerivationError(
            "attenuation requires an AuthorizationCapability parent"
        )
    parent.verify_integrity()
    if not parent.one_time:
        raise CapabilityDerivationError(
            "parent capability missing one-time marker"
        )

    effects = _unique_sorted_ids(
        allowed_effects, "allowed_effects", require_identifier=True
    )
    if not effects:
        raise CapabilityDerivationError("allowed_effects must be non-empty")
    if not _is_strict_subset(effects, parent.allowed_effects):
        raise CapabilityDerivationError(
            "re-attenuation requires a strict subset of parent allowed_effects "
            "(widening or non-strict copy is forbidden)"
        )

    if resource_ids is None:
        resources = parent.resource_ids
    else:
        resources = _unique_sorted_ids(
            resource_ids, "resource_ids", require_identifier=True
        )
        if parent.resource_ids and not _is_subset(
            resources, parent.resource_ids
        ):
            raise CapabilityDerivationError(
                "attenuated resource_ids must be a subset of parent resources"
            )

    cap_expiry = expiry if expiry is not None else parent.expiry
    if cap_expiry > parent.expiry:
        raise CapabilityDerivationError(
            "attenuated expiry must not exceed parent expiry"
        )
    if cap_expiry < parent.issued_at:
        raise CapabilityDerivationError(
            "attenuated expiry must not precede parent issued_at"
        )

    return AuthorizationCapability(
        capability_id=capability_id,
        receipt_id=parent.receipt_id,
        receipt_digest=parent.receipt_digest,
        audience_id=parent.audience_id,
        request_digest=parent.request_digest,
        allowed_effects=effects,
        resource_ids=resources,
        tool_id=parent.tool_id,
        roots=parent.roots,
        one_time=True,
        nonce=parent.nonce,
        issued_at=parent.issued_at,
        expiry=cap_expiry,
        producer_id=parent.producer_id,
        parent_capability_id=parent.capability_id,
        parent_capability_digest=parent.digest,
        metadata=FrozenMap(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Verifiers
# ---------------------------------------------------------------------------


def verify_decision_receipt(
    receipt: DecisionReceipt | Mapping[str, Any],
    *,
    now: str | None = None,
    expected_roots: BoundRoots | Mapping[str, Any] | None = None,
    expected_audience: str | None = None,
    expected_request_digest: str | None = None,
    expected_actor: str | None = None,
    expected_nonce: str | None = None,
    expected_decision_digest: str | None = None,
    require_not_expired: bool = True,
) -> DecisionReceipt:
    """Independently verify a decision receipt's integrity and context binding.

    Rejects identity drift, unknown schema/algorithm (via construction),
    wrong audience / actor / nonce / request, stale roots, and expiry.
    """

    if isinstance(receipt, Mapping):
        receipt = DecisionReceipt.from_dict(receipt)
    elif not isinstance(receipt, DecisionReceipt):
        raise ReceiptVerificationError(
            "receipt must be a DecisionReceipt or mapping"
        )

    receipt.verify_integrity()

    if expected_audience is not None and receipt.audience_id != expected_audience:
        raise ReceiptVerificationError(
            f"audience mismatch: receipt has {receipt.audience_id!r}, "
            f"expected {expected_audience!r}"
        )
    if expected_actor is not None and receipt.actor_id != expected_actor:
        raise ReceiptVerificationError(
            f"actor mismatch: receipt has {receipt.actor_id!r}, "
            f"expected {expected_actor!r}"
        )
    if expected_nonce is not None and receipt.nonce != expected_nonce:
        raise ReceiptVerificationError(
            f"nonce mismatch: receipt has {receipt.nonce!r}, "
            f"expected {expected_nonce!r}"
        )
    if (
        expected_request_digest is not None
        and receipt.request_digest != _digest(
            expected_request_digest, "expected_request_digest"
        )
    ):
        raise ReceiptVerificationError(
            "request_digest mismatch (context mutation detected)"
        )
    if (
        expected_decision_digest is not None
        and receipt.decision_digest
        != _digest(expected_decision_digest, "expected_decision_digest")
    ):
        raise ReceiptVerificationError("decision_digest mismatch")

    if expected_roots is not None:
        if isinstance(expected_roots, Mapping):
            expected_roots = BoundRoots.from_dict(expected_roots)
        if not receipt.roots.matches(expected_roots):
            raise ReceiptVerificationError(
                "stale or mismatched policy/corpus/revocation/circuit/VK roots"
            )

    if require_not_expired and now is not None:
        now_ts = _timestamp(now, "now")
        if now_ts >= receipt.expiry:
            raise ReceiptVerificationError(
                f"receipt expired at {receipt.expiry!r} (now={now_ts!r})"
            )
        if now_ts > receipt.deadline:
            raise ReceiptVerificationError(
                f"receipt past deadline {receipt.deadline!r} (now={now_ts!r})"
            )

    return receipt


def verify_capability(
    capability: AuthorizationCapability | Mapping[str, Any],
    receipt: DecisionReceipt | Mapping[str, Any] | None = None,
    *,
    now: str | None = None,
    expected_audience: str | None = None,
    expected_roots: BoundRoots | Mapping[str, Any] | None = None,
    expected_request_digest: str | None = None,
    require_not_expired: bool = True,
) -> AuthorizationCapability:
    """Verify a capability's integrity, one-time marker, and attenuation.

    When *receipt* is provided, checks binding to that allow receipt and
    subset attenuation of effects/resources.
    """

    if isinstance(capability, Mapping):
        capability = AuthorizationCapability.from_dict(capability)
    elif not isinstance(capability, AuthorizationCapability):
        raise ReceiptVerificationError(
            "capability must be an AuthorizationCapability or mapping"
        )

    capability.verify_integrity()

    if not capability.one_time:
        raise ReceiptVerificationError(
            "capability missing required one-time marker"
        )

    if expected_audience is not None and capability.audience_id != expected_audience:
        raise ReceiptVerificationError(
            f"capability audience mismatch: has {capability.audience_id!r}, "
            f"expected {expected_audience!r}"
        )
    if (
        expected_request_digest is not None
        and capability.request_digest
        != _digest(expected_request_digest, "expected_request_digest")
    ):
        raise ReceiptVerificationError(
            "capability request_digest mismatch"
        )

    if expected_roots is not None:
        if isinstance(expected_roots, Mapping):
            expected_roots = BoundRoots.from_dict(expected_roots)
        if not capability.roots.matches(expected_roots):
            raise ReceiptVerificationError(
                "capability roots are stale or mismatched"
            )

    if require_not_expired and now is not None:
        now_ts = _timestamp(now, "now")
        if now_ts >= capability.expiry:
            raise ReceiptVerificationError(
                f"capability expired at {capability.expiry!r} (now={now_ts!r})"
            )

    if receipt is not None:
        if isinstance(receipt, Mapping):
            receipt = DecisionReceipt.from_dict(receipt)
        receipt.verify_integrity()
        if not receipt.permits_capability_derivation:
            raise ReceiptVerificationError(
                "capability cannot be bound to a non-allow receipt"
            )
        if capability.receipt_id != receipt.receipt_id:
            raise ReceiptVerificationError("capability receipt_id mismatch")
        if capability.receipt_digest != receipt.digest:
            raise ReceiptVerificationError(
                "capability receipt_digest mismatch (receipt mutation)"
            )
        if capability.audience_id != receipt.audience_id:
            raise ReceiptVerificationError(
                "capability audience does not match receipt audience"
            )
        if capability.request_digest != receipt.request_digest:
            raise ReceiptVerificationError(
                "capability request_digest does not match receipt"
            )
        if capability.nonce != receipt.nonce:
            raise ReceiptVerificationError(
                "capability nonce does not match receipt nonce"
            )
        if not capability.roots.matches(receipt.roots):
            raise ReceiptVerificationError(
                "capability roots do not match receipt roots"
            )
        if receipt.effect_ids and not _is_subset(
            capability.allowed_effects, receipt.effect_ids
        ):
            raise ReceiptVerificationError(
                "capability effects widen beyond receipt effects"
            )
        if receipt.context.resource_ids and not _is_subset(
            capability.resource_ids, receipt.context.resource_ids
        ):
            raise ReceiptVerificationError(
                "capability resources widen beyond receipt resources"
            )
        if capability.expiry > receipt.expiry:
            raise ReceiptVerificationError(
                "capability expiry exceeds receipt expiry"
            )
        if (
            receipt.context.tool_id
            and capability.tool_id
            and capability.tool_id != receipt.context.tool_id
        ):
            raise ReceiptVerificationError(
                "capability tool_id does not match receipt tool binding"
            )

    return capability


def receipt_context_fingerprint(receipt: DecisionReceipt) -> str:
    """Stable fingerprint over security-relevant context fields.

    Used by tests and future cache keys to detect any exact-context mutation.
    """

    return stable_digest(
        {
            "actor_id": receipt.actor_id,
            "arguments_digest": receipt.context.arguments_digest,
            "audience_id": receipt.audience_id,
            "delegation_digest": receipt.context.delegation_digest,
            "delegation_ids": list(receipt.context.delegation_ids),
            "effect_ids": list(receipt.effect_ids),
            "environment_digest": receipt.context.environment_digest,
            "environment_id": receipt.context.environment_id,
            "expiry": receipt.expiry,
            "nonce": receipt.nonce,
            "request_digest": receipt.request_digest,
            "roots": receipt.roots.to_dict(),
            "tool_id": receipt.context.tool_id,
            "tool_version": receipt.context.tool_version,
        }
    )


__all__ = [
    "AUTHORIZATION_CAPABILITY_INTERFACE",
    "AUTHORIZATION_CAPABILITY_SCHEMA_VERSION",
    "BOUND_CONTEXT_SCHEMA_VERSION",
    "BOUND_ROOTS_SCHEMA_VERSION",
    "AuthorizationCapability",
    "BoundContext",
    "BoundRoots",
    "CapabilityDerivationError",
    "DECISION_RECEIPT_INTERFACE",
    "DECISION_RECEIPT_SCHEMA_VERSION",
    "DEFAULT_IDENTITY_ALGORITHM",
    "DecisionReceipt",
    "KNOWN_IDENTITY_ALGORITHMS",
    "ReceiptError",
    "ReceiptVerificationError",
    "attenuate_capability",
    "build_decision_receipt",
    "derive_capability",
    "receipt_context_fingerprint",
    "verify_capability",
    "verify_decision_receipt",
]
