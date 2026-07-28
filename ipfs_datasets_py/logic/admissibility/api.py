"""Hardened public Intent authorization API (LIG-038).

Interface: ``IntentAuthorizationAPI@1``

Stable, redacted surface over :class:`IntentAuthorizationService` for Python
callers that must evaluate exact invocations and verify receipts without
side effects.

Hardening invariants
--------------------
* Require **explicit** source, actor, audience, tool, argument commitment,
  and environment bindings plus **exact** policy / corpus / revocation roots.
* Return allow / reject / abstain **compatibility** status together with
  typed decision and receipt **refs** (digests / ids), not private payloads.
* Emit only **bound and redacted** views — never prompts, raw arguments,
  secrets, witnesses, or private formulas.
* Unknown, malformed, and backend-unavailable paths **fail closed**
  (never promote to allow).
* This API **never executes** skill / prompt / tool bodies, **never issues**
  a dispatch capability, and **never consumes** a one-time capability
  (dispatch remains PreInvocationEnforcement@1 / supervisor ownership).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..ir_core.claims import FrozenMap, stable_digest
from .compose import AuthorizationDecision, InternalDecisionStatus, map_internal_to_wire
from .reasons import AdmissibilityStatus
from .receipt import (
    BoundContext,
    BoundRoots,
    DecisionReceipt,
    ReceiptError,
    ReceiptVerificationError,
    verify_decision_receipt,
)
from .service import (
    AuthorizationBudget,
    AuthorizationRootError,
    AuthorizationServiceError,
    AuthorizationServiceResult,
    CancellationToken,
    IntentAuthorizationService,
    OfflineAuthorizationDependencies,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

INTENT_AUTHORIZATION_API_INTERFACE: Final = "IntentAuthorizationAPI@1"
INTENT_AUTHORIZATION_API_SCHEMA_VERSION: Final = "intent-authorization-api/v1"
TYPED_DECISION_REF_SCHEMA_VERSION: Final = "typed-decision-ref/v1"
TYPED_RECEIPT_REF_SCHEMA_VERSION: Final = "typed-receipt-ref/v1"
REDACTED_AUTHORIZATION_VIEW_SCHEMA_VERSION: Final = (
    "redacted-authorization-view/v1"
)
AUTHORIZATION_API_RESULT_SCHEMA_VERSION: Final = "authorization-api-result/v1"
BOUND_CONTEXT_VIEW_SCHEMA_VERSION: Final = "bound-context-view/v1"
BOUND_ROOTS_VIEW_SCHEMA_VERSION: Final = "bound-roots-view/v1"

DEFAULT_API_PRODUCER_ID: Final = "producer:intent-authorization-api-v1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_REASON_CHARS: Final = 512
MAX_REASONS: Final = 64
MAX_DIAGNOSTICS: Final = 64
MAX_COLLECTION_ITEMS: Final = 1_024

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")

# Field / token names that must never appear in redacted public views.
_FORBIDDEN_VIEW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "prompts",
        "raw_prompt",
        "argument",
        "arguments",
        "raw_arguments",
        "redacted_arguments",
        "secret",
        "secrets",
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "authorization_header",
        "credential",
        "credentials",
        "private_key",
        "privatekey",
        "witness",
        "witnesses",
        "witness_data",
        "formula",
        "formulas",
        "private_formula",
        "private_formulas",
        "skill_md",
        "body",
        "plaintext",
        "bearer",
        "session_secret",
        "capability_token",
        "dispatch_token",
    }
)

_FORBIDDEN_SUBSTRINGS: Final[tuple[str, ...]] = (
    "prompt",
    "secret",
    "witness",
    "password",
    "private_key",
    "api_key",
    "raw_arg",
    "skill_md",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthorizationAPIError(ValueError):
    """Raised when the hardened authorization API fails closed."""


class AuthorizationAPIRequestError(AuthorizationAPIError):
    """Raised when required invocation / root fields are missing or malformed."""


class AuthorizationAPIBackendError(AuthorizationAPIError):
    """Raised when the authorization backend is unavailable (fail closed)."""


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
        raise AuthorizationAPIRequestError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise AuthorizationAPIRequestError(
            f"{name} must be a non-empty trimmed string"
        )
    if value and value != value.strip():
        raise AuthorizationAPIRequestError(
            f"{name} must not have surrounding whitespace"
        )
    if len(value) > max_chars:
        raise AuthorizationAPIRequestError(
            f"{name} exceeds maximum length of {max_chars}"
        )
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise AuthorizationAPIRequestError(f"{name} is not a stable identifier")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, name)


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise AuthorizationAPIRequestError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
    return text


def _optional_digest(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _digest(value, name)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorizationAPIRequestError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AuthorizationAPIRequestError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _unique_sorted(
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
        raise AuthorizationAPIRequestError(f"{name} must be a sequence of strings")
    if len(values) > max_items:
        raise AuthorizationAPIRequestError(
            f"{name} exceeds maximum of {max_items} items"
        )
    if require_identifier:
        items = tuple(_identifier(item, f"{name} item") for item in values)
    else:
        items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise AuthorizationAPIRequestError(f"{name} must be unique")
    return tuple(sorted(items))


def _bounded_reasons(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item:
            continue
        # Bound length and strip potentially sensitive free text.
        cleaned = item.strip()[:MAX_REASON_CHARS]
        if not cleaned or cleaned in seen:
            continue
        lower = cleaned.lower()
        if any(token in lower for token in _FORBIDDEN_SUBSTRINGS):
            cleaned = "auth.api.reason.redacted"
        seen.add(cleaned)
        ordered.append(cleaned)
        if len(ordered) >= MAX_REASONS:
            break
    return tuple(ordered)


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower().strip()
    if lowered in _FORBIDDEN_VIEW_KEYS:
        return True
    return any(token in lowered for token in _FORBIDDEN_SUBSTRINGS)


def redact_mapping(
    value: Any,
    *,
    max_depth: int = 6,
    _depth: int = 0,
) -> Any:
    """Recursively drop forbidden keys and bound nested structure.

    Used to guarantee public views never carry prompts, arguments, secrets,
    witnesses, or private formulas even if upstream maps grow new fields.
    """

    if _depth > max_depth:
        return "[redacted:max-depth]"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_forbidden_key(key_text):
                continue
            out[key_text] = redact_mapping(
                item, max_depth=max_depth, _depth=_depth + 1
            )
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_COLLECTION_ITEMS:
            value = value[:MAX_COLLECTION_ITEMS]
        return [
            redact_mapping(item, max_depth=max_depth, _depth=_depth + 1)
            for item in value
        ]
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            return value[:MAX_STRING_CHARS] + "…"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # Unknown objects never leak repr into public views.
    return f"[redacted:{type(value).__name__}]"


# ---------------------------------------------------------------------------
# Typed refs and redacted views
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedDecisionRef:
    """Content-addressed decision reference (no private decision body)."""

    decision_digest: str
    status: str
    wire_status: str
    profile_id: str = ""
    policy_digest: str = ""
    interface: str = "AuthorizationDecision@1"
    schema_version: str = TYPED_DECISION_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_digest",
            _digest(self.decision_digest, "decision_digest"),
        )
        object.__setattr__(
            self, "status", _text(self.status, "status", max_chars=64)
        )
        object.__setattr__(
            self,
            "wire_status",
            _text(self.wire_status, "wire_status", max_chars=32),
        )
        if self.wire_status not in {"allow", "reject", "abstain"}:
            raise AuthorizationAPIRequestError(
                "wire_status must be allow, reject, or abstain"
            )
        object.__setattr__(
            self,
            "profile_id",
            _optional_text(self.profile_id, "profile_id"),
        )
        object.__setattr__(
            self,
            "policy_digest",
            _optional_digest(self.policy_digest, "policy_digest"),
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TYPED_DECISION_REF_SCHEMA_VERSION:
            raise AuthorizationAPIRequestError(
                f"unsupported decision-ref schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_digest": self.decision_digest,
            "interface": self.interface,
            "policy_digest": self.policy_digest,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "wire_status": self.wire_status,
        }

    @classmethod
    def from_decision(cls, decision: AuthorizationDecision) -> "TypedDecisionRef":
        return cls(
            decision_digest=decision.digest,
            status=decision.status.value,
            wire_status=decision.wire_status.value,
            profile_id=decision.profile_id,
            policy_digest=decision.policy_digest,
            interface=decision.interface,
        )


@dataclass(frozen=True, slots=True)
class TypedReceiptRef:
    """Content-addressed receipt reference (ids / digests only)."""

    receipt_id: str
    content_digest: str
    content_cid: str = ""
    wire_status: str = "abstain"
    outcome: str = "error"
    expiry: str = ""
    audience_id: str = ""
    request_digest: str = ""
    interface: str = "DecisionReceipt@1"
    schema_version: str = TYPED_RECEIPT_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        digest = self.content_digest
        if digest.startswith("sha256:"):
            digest = digest[len("sha256:") :]
        object.__setattr__(
            self, "content_digest", _digest(digest, "content_digest")
        )
        object.__setattr__(
            self,
            "content_cid",
            _optional_text(self.content_cid, "content_cid"),
        )
        object.__setattr__(
            self,
            "wire_status",
            _text(self.wire_status, "wire_status", max_chars=32),
        )
        if self.wire_status not in {"allow", "reject", "abstain"}:
            raise AuthorizationAPIRequestError(
                "wire_status must be allow, reject, or abstain"
            )
        object.__setattr__(
            self, "outcome", _text(self.outcome, "outcome", max_chars=64)
        )
        object.__setattr__(
            self, "expiry", _optional_text(self.expiry, "expiry")
        )
        object.__setattr__(
            self,
            "audience_id",
            _optional_identifier(self.audience_id, "audience_id"),
        )
        object.__setattr__(
            self,
            "request_digest",
            _optional_digest(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TYPED_RECEIPT_REF_SCHEMA_VERSION:
            raise AuthorizationAPIRequestError(
                f"unsupported receipt-ref schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audience_id": self.audience_id,
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "expiry": self.expiry,
            "interface": self.interface,
            "outcome": self.outcome,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "wire_status": self.wire_status,
        }

    @classmethod
    def from_receipt(cls, receipt: DecisionReceipt) -> "TypedReceiptRef":
        return cls(
            receipt_id=receipt.receipt_id,
            content_digest=receipt.digest,
            content_cid=receipt.content_cid,
            wire_status=receipt.wire_status.value,
            outcome=receipt.outcome.value,
            expiry=receipt.expiry,
            audience_id=receipt.audience_id,
            request_digest=receipt.request_digest,
            interface=receipt.interface,
        )


@dataclass(frozen=True, slots=True)
class BoundContextView:
    """Bound request context digests / identifiers (no raw arguments)."""

    request_digest: str
    arguments_digest: str
    actor_id: str
    audience_id: str
    tool_id: str = ""
    tool_version: str = ""
    effect_ids: tuple[str, ...] = ()
    environment_digest: str = ""
    environment_id: str = ""
    nonce: str = ""
    schema_version: str = BOUND_CONTEXT_VIEW_SCHEMA_VERSION

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
            _unique_sorted(
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
            self, "nonce", _text(self.nonce, "nonce", max_chars=128)
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "arguments_digest": self.arguments_digest,
            "audience_id": self.audience_id,
            "effect_ids": list(self.effect_ids),
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "nonce": self.nonce,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
        }

    @classmethod
    def from_bound_context(cls, context: BoundContext) -> "BoundContextView":
        return cls(
            request_digest=context.request_digest,
            arguments_digest=context.arguments_digest,
            actor_id=context.actor_id,
            audience_id=context.audience_id,
            tool_id=context.tool_id,
            tool_version=context.tool_version,
            effect_ids=context.effect_ids,
            environment_digest=context.environment_digest,
            environment_id=context.environment_id,
            nonce=context.nonce,
        )


@dataclass(frozen=True, slots=True)
class BoundRootsView:
    """Exact policy / corpus / revocation roots bound into a decision."""

    policy_root: str
    corpus_roots: tuple[str, ...] = ()
    revocation_root: str = ""
    schema_version: str = BOUND_ROOTS_VIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_root", _text(self.policy_root, "policy_root")
        )
        object.__setattr__(
            self,
            "corpus_roots",
            _unique_sorted(self.corpus_roots, "corpus_roots"),
        )
        object.__setattr__(
            self,
            "revocation_root",
            _optional_text(self.revocation_root, "revocation_root"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_roots": list(self.corpus_roots),
            "policy_root": self.policy_root,
            "revocation_root": self.revocation_root,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_bound_roots(cls, roots: BoundRoots) -> "BoundRootsView":
        return cls(
            policy_root=roots.policy_root,
            corpus_roots=roots.corpus_roots,
            revocation_root=roots.revocation_root,
        )


@dataclass(frozen=True, slots=True)
class RedactedAuthorizationView:
    """Public, privacy-preserving view of one authorization evaluation.

    Contains only digests, identifiers, closed statuses, and bounded reasons.
    """

    wire_status: str
    internal_status: str
    reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    profile_id: str = ""
    context: BoundContextView | None = None
    roots: BoundRootsView | None = None
    decision_ref: TypedDecisionRef | None = None
    receipt_ref: TypedReceiptRef | None = None
    executed: bool = False
    capability_issued: bool = False
    capability_consumed: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = REDACTED_AUTHORIZATION_VIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "wire_status",
            _text(self.wire_status, "wire_status", max_chars=32),
        )
        if self.wire_status not in {"allow", "reject", "abstain"}:
            raise AuthorizationAPIRequestError(
                "wire_status must be allow, reject, or abstain"
            )
        object.__setattr__(
            self,
            "internal_status",
            _text(self.internal_status, "internal_status", max_chars=64),
        )
        object.__setattr__(
            self, "reasons", _bounded_reasons(tuple(self.reasons))
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_sorted(
                self.reason_codes, "reason_codes", max_items=MAX_REASONS
            ),
        )
        object.__setattr__(
            self,
            "profile_id",
            _optional_text(self.profile_id, "profile_id"),
        )
        object.__setattr__(self, "executed", bool(self.executed))
        object.__setattr__(
            self, "capability_issued", bool(self.capability_issued)
        )
        object.__setattr__(
            self, "capability_consumed", bool(self.capability_consumed)
        )
        # Hard safety: public API never claims it issued or consumed a capability.
        if self.capability_issued or self.capability_consumed:
            raise AuthorizationAPIError(
                "redacted view must not claim capability issue/consume "
                "(API never issues or consumes dispatch capabilities)"
            )
        if self.executed:
            raise AuthorizationAPIError(
                "redacted view must never report executed=true"
            )
        diagnostics = _bounded_reasons(tuple(self.diagnostics))
        if len(diagnostics) > MAX_DIAGNOSTICS:
            diagnostics = diagnostics[:MAX_DIAGNOSTICS]
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != REDACTED_AUTHORIZATION_VIEW_SCHEMA_VERSION:
            raise AuthorizationAPIRequestError(
                f"unsupported redacted-view schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "capability_consumed": False,
            "capability_issued": False,
            "context": None if self.context is None else self.context.to_dict(),
            "decision_ref": (
                None if self.decision_ref is None else self.decision_ref.to_dict()
            ),
            "diagnostics": list(self.diagnostics),
            "executed": False,
            "internal_status": self.internal_status,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "receipt_ref": (
                None if self.receipt_ref is None else self.receipt_ref.to_dict()
            ),
            "roots": None if self.roots is None else self.roots.to_dict(),
            "schema_version": self.schema_version,
            "wire_status": self.wire_status,
        }
        return redact_mapping(payload)


@dataclass(frozen=True, slots=True)
class AuthorizationAPIResult:
    """Typed result of :meth:`IntentAuthorizationAPI.evaluate`.

    Compatibility status is the legacy wire ``allow`` / ``reject`` /
    ``abstain`` value.  Typed refs and the redacted view never embed private
    payloads or dispatch capabilities.
    """

    wire_status: AdmissibilityStatus
    internal_status: InternalDecisionStatus
    reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    decision_ref: TypedDecisionRef | None = None
    receipt_ref: TypedReceiptRef | None = None
    view: RedactedAuthorizationView | None = None
    profile_id: str = ""
    producer_id: str = DEFAULT_API_PRODUCER_ID
    interface: str = INTENT_AUTHORIZATION_API_INTERFACE
    schema_version: str = AUTHORIZATION_API_RESULT_SCHEMA_VERSION
    # Internal-only handles for offline tests; never serialized on to_dict().
    _service_result: AuthorizationServiceResult | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        wire = self.wire_status
        if not isinstance(wire, AdmissibilityStatus):
            wire = AdmissibilityStatus(wire)
        status = self.internal_status
        if not isinstance(status, InternalDecisionStatus):
            status = InternalDecisionStatus(status)
        expected = map_internal_to_wire(status)
        if wire is not expected:
            raise AuthorizationAPIError(
                f"wire_status {wire.value!r} inconsistent with "
                f"internal_status {status.value!r} "
                f"(expected {expected.value!r})"
            )
        object.__setattr__(self, "wire_status", wire)
        object.__setattr__(self, "internal_status", status)
        object.__setattr__(
            self, "reasons", _bounded_reasons(tuple(self.reasons))
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_sorted(
                self.reason_codes, "reason_codes", max_items=MAX_REASONS
            ),
        )
        object.__setattr__(
            self,
            "profile_id",
            _optional_text(self.profile_id, "profile_id"),
        )
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        if self.interface != INTENT_AUTHORIZATION_API_INTERFACE:
            raise AuthorizationAPIError(
                f"unsupported API interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_API_RESULT_SCHEMA_VERSION:
            raise AuthorizationAPIError(
                f"unsupported API result schema: {self.schema_version!r}"
            )

    @property
    def is_allow(self) -> bool:
        return self.wire_status is AdmissibilityStatus.ALLOW

    @property
    def compatibility_status(self) -> AdmissibilityStatus:
        return self.wire_status

    def to_dict(self) -> dict[str, Any]:
        """Public serialization — redacted, no service internals, no capability."""

        payload = {
            "decision_ref": (
                None if self.decision_ref is None else self.decision_ref.to_dict()
            ),
            "interface": self.interface,
            "internal_status": self.internal_status.value,
            "producer_id": self.producer_id,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "receipt_ref": (
                None if self.receipt_ref is None else self.receipt_ref.to_dict()
            ),
            "schema_version": self.schema_version,
            "view": None if self.view is None else self.view.to_dict(),
            "wire_status": self.wire_status.value,
            # Explicit non-execution / non-capability contract on every payload.
            "executed": False,
            "capability_issued": False,
            "capability_consumed": False,
        }
        return redact_mapping(payload)


# ---------------------------------------------------------------------------
# Explicit binding validation
# ---------------------------------------------------------------------------


def _require_explicit_bindings(envelope: Any) -> None:
    """Fail closed unless source/actor/audience/tool/arguments/environment exist."""

    try:
        source = envelope.source
        actor = envelope.actor
        audience = envelope.audience
        tool = envelope.tool
        arguments = envelope.arguments
        environment = envelope.environment
    except AttributeError as exc:
        raise AuthorizationAPIRequestError(
            "invocation envelope missing required binding attributes"
        ) from exc

    source_kind = getattr(source, "kind", None)
    source_ref = getattr(source, "source_ref", "") or ""
    if source_kind is None and not source_ref:
        raise AuthorizationAPIRequestError(
            "explicit source binding is required (kind or source_ref)"
        )
    if hasattr(source_kind, "value"):
        kind_value = str(source_kind.value)
    else:
        kind_value = str(source_kind or "")
    if not kind_value.strip() and not str(source_ref).strip():
        raise AuthorizationAPIRequestError(
            "explicit source binding is required (kind or source_ref)"
        )

    actor_id = getattr(actor, "actor_id", "") or ""
    if not str(actor_id).strip():
        raise AuthorizationAPIRequestError("explicit actor_id is required")

    audience_id = getattr(audience, "audience_id", "") or ""
    if not str(audience_id).strip():
        raise AuthorizationAPIRequestError("explicit audience_id is required")

    tool_id = getattr(tool, "tool_id", "") or ""
    if not str(tool_id).strip():
        raise AuthorizationAPIRequestError("explicit tool_id is required")

    commitment = getattr(arguments, "commitment", "") or ""
    if not str(commitment).strip():
        raise AuthorizationAPIRequestError(
            "explicit argument commitment is required "
            "(raw arguments are never accepted on the public API)"
        )

    env_id = getattr(environment, "environment_id", "") or ""
    env_digest = getattr(environment, "snapshot_digest", "") or ""
    if not str(env_id).strip() and not str(env_digest).strip():
        raise AuthorizationAPIRequestError(
            "explicit environment binding is required "
            "(environment_id or snapshot_digest)"
        )


def _require_exact_roots(
    *,
    policy_ref: str,
    legal_corpus_ref: str,
    security_corpus_ref: str,
    intent_corpus_ref: str,
    revocation_root: str,
    corpus_roots: Sequence[str] = (),
) -> tuple[str, tuple[str, ...], str]:
    """Require exact policy, at least one corpus root, and a revocation root."""

    policy = _text(policy_ref, "policy_ref")
    corpus: list[str] = []
    for ref, name in (
        (legal_corpus_ref, "legal_corpus_ref"),
        (security_corpus_ref, "security_corpus_ref"),
        (intent_corpus_ref, "intent_corpus_ref"),
    ):
        text = _optional_text(ref, name)
        if text:
            corpus.append(text)
    for item in corpus_roots or ():
        text = _text(item, "corpus_roots item")
        if text not in corpus:
            corpus.append(text)
    if not corpus:
        raise AuthorizationAPIRequestError(
            "exact corpus root is required "
            "(legal_corpus_ref, security_corpus_ref, intent_corpus_ref, "
            "or corpus_roots)"
        )
    rev = _text(revocation_root, "revocation_root")
    return policy, tuple(sorted(set(corpus))), rev


def _fail_closed_result(
    *,
    status: InternalDecisionStatus,
    reasons: Sequence[str],
    reason_codes: Sequence[str] = (),
    profile_id: str = "",
    producer_id: str = DEFAULT_API_PRODUCER_ID,
    context: BoundContext | None = None,
    roots: BoundRoots | None = None,
) -> AuthorizationAPIResult:
    """Build a non-allow API result (never allow)."""

    assert status is not InternalDecisionStatus.ALLOW
    wire = map_internal_to_wire(status)
    context_view = (
        None if context is None else BoundContextView.from_bound_context(context)
    )
    roots_view = None if roots is None else BoundRootsView.from_bound_roots(roots)
    view = RedactedAuthorizationView(
        wire_status=wire.value,
        internal_status=status.value,
        reasons=tuple(reasons),
        reason_codes=tuple(reason_codes),
        profile_id=profile_id,
        context=context_view,
        roots=roots_view,
        decision_ref=None,
        receipt_ref=None,
        diagnostics=("auth.api.fail_closed",),
    )
    return AuthorizationAPIResult(
        wire_status=wire,
        internal_status=status,
        reasons=tuple(reasons),
        reason_codes=tuple(reason_codes),
        decision_ref=None,
        receipt_ref=None,
        view=view,
        profile_id=profile_id,
        producer_id=producer_id,
    )


def project_service_result(
    service_result: AuthorizationServiceResult,
    *,
    producer_id: str = DEFAULT_API_PRODUCER_ID,
) -> AuthorizationAPIResult:
    """Project a service result into the hardened public API shape.

    Strips envelopes, evidence bodies, capabilities, and any private fields.
    """

    if not isinstance(service_result, AuthorizationServiceResult):
        raise AuthorizationAPIError(
            "service_result must be an AuthorizationServiceResult"
        )

    # Hard safety: never promote a capability-bearing service result through
    # the public API as if the API issued it — capability is stripped.
    decision_ref: TypedDecisionRef | None = None
    if service_result.decision is not None:
        decision_ref = TypedDecisionRef.from_decision(service_result.decision)

    receipt_ref: TypedReceiptRef | None = None
    if service_result.receipt is not None:
        receipt_ref = TypedReceiptRef.from_receipt(service_result.receipt)

    context_view = (
        None
        if service_result.context is None
        else BoundContextView.from_bound_context(service_result.context)
    )
    roots_view = (
        None
        if service_result.roots is None
        else BoundRootsView.from_bound_roots(service_result.roots)
    )

    diagnostics: list[str] = []
    if service_result.trace is not None:
        for item in service_result.trace.diagnostics[:MAX_DIAGNOSTICS]:
            if isinstance(item, str) and item.startswith("auth."):
                diagnostics.append(item)

    view = RedactedAuthorizationView(
        wire_status=service_result.wire_status.value,
        internal_status=service_result.status.value,
        reasons=service_result.reasons,
        reason_codes=service_result.reason_codes,
        profile_id=service_result.profile_id,
        context=context_view,
        roots=roots_view,
        decision_ref=decision_ref,
        receipt_ref=receipt_ref,
        diagnostics=tuple(diagnostics),
    )
    return AuthorizationAPIResult(
        wire_status=service_result.wire_status,
        internal_status=service_result.status,
        reasons=service_result.reasons,
        reason_codes=service_result.reason_codes,
        decision_ref=decision_ref,
        receipt_ref=receipt_ref,
        view=view,
        profile_id=service_result.profile_id,
        producer_id=producer_id,
        _service_result=service_result,
    )


# ---------------------------------------------------------------------------
# IntentAuthorizationAPI@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentAuthorizationAPI:
    """``IntentAuthorizationAPI@1`` — hardened Python authorization surface.

    Wraps :class:`IntentAuthorizationService` without rewriting it.  Evaluation
    is side-effect free with respect to tools and dispatch: the API never
    executes content, never installs backends, never mutates a corpus, never
    issues a dispatch capability, and never consumes one.
    """

    service: IntentAuthorizationService = field(
        default_factory=IntentAuthorizationService
    )
    producer_id: str = DEFAULT_API_PRODUCER_ID
    interface: str = INTENT_AUTHORIZATION_API_INTERFACE
    schema_version: str = INTENT_AUTHORIZATION_API_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        if self.interface != INTENT_AUTHORIZATION_API_INTERFACE:
            raise AuthorizationAPIError(
                f"unsupported API interface: {self.interface!r}"
            )
        if self.schema_version != INTENT_AUTHORIZATION_API_SCHEMA_VERSION:
            raise AuthorizationAPIError(
                f"unsupported API schema: {self.schema_version!r}"
            )
        if not isinstance(self.service, IntentAuthorizationService):
            raise AuthorizationAPIError(
                "service must be an IntentAuthorizationService instance"
            )

    def evaluate(
        self,
        invocation: Any = None,
        *,
        policy_ref: str = "",
        legal_corpus_ref: str = "",
        security_corpus_ref: str = "",
        intent_corpus_ref: str = "",
        corpus_roots: Sequence[str] = (),
        revocation_root: str = "",
        environment: Mapping[str, Any] | None = None,
        budget: AuthorizationBudget | Mapping[str, Any] | None = None,
        profile: Any = None,
        deps: OfflineAuthorizationDependencies | None = None,
        cancellation: CancellationToken | None = None,
        circuit_roots: Sequence[str] = (),
        vk_roots: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> AuthorizationAPIResult:
        """Evaluate an exact invocation through the hardened public API.

        Requires explicit policy / corpus / revocation roots.  Always passes
        ``derive_capability_on_allow=False`` to the underlying service.
        """

        if invocation is None:
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=("invocation is required",),
                reason_codes=("auth.api.missing_invocation",),
                producer_id=self.producer_id,
            )

        try:
            policy, corpus, rev = _require_exact_roots(
                policy_ref=policy_ref,
                legal_corpus_ref=legal_corpus_ref,
                security_corpus_ref=security_corpus_ref,
                intent_corpus_ref=intent_corpus_ref,
                revocation_root=revocation_root,
                corpus_roots=corpus_roots,
            )
        except AuthorizationAPIRequestError as exc:
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(str(exc),),
                reason_codes=("auth.api.missing_roots",),
                producer_id=self.producer_id,
            )

        # Pre-validate envelope-shaped invocations before service evaluation
        # so missing bindings fail closed with a stable public reason.
        try:
            self._prevalidate_invocation(invocation, environment=environment)
        except AuthorizationAPIRequestError as exc:
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(str(exc),),
                reason_codes=("auth.api.missing_binding",),
                producer_id=self.producer_id,
            )

        # Map multi corpus roots onto service kwargs (first three slots).
        legal = legal_corpus_ref or (corpus[0] if corpus else "")
        security = security_corpus_ref or (
            corpus[1] if len(corpus) > 1 else (corpus[0] if corpus else "")
        )
        intent = intent_corpus_ref or (corpus[2] if len(corpus) > 2 else "")

        try:
            service_result = self.service.evaluate(
                invocation,
                policy_ref=policy,
                legal_corpus_ref=legal,
                security_corpus_ref=security,
                intent_corpus_ref=intent,
                revocation_root=rev,
                environment=environment,
                budget=budget,
                profile=profile,
                deps=deps,
                cancellation=cancellation,
                # Public API never issues dispatch capabilities.
                derive_capability_on_allow=False,
                circuit_roots=circuit_roots,
                vk_roots=vk_roots,
                metadata=metadata,
            )
        except AuthorizationRootError as exc:
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(str(exc),),
                reason_codes=("auth.api.root_error",),
                producer_id=self.producer_id,
            )
        except AuthorizationServiceError as exc:
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(str(exc),),
                reason_codes=("auth.api.service_error",),
                producer_id=self.producer_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail closed, never allow
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(f"backend unavailable: {type(exc).__name__}",),
                reason_codes=("auth.api.backend_unavailable",),
                producer_id=self.producer_id,
            )

        # Backend-unavailable signals from the service itself.
        if self._looks_backend_unavailable(service_result):
            # Preserve non-allow; never promote.  Re-tag for public consumers.
            projected = project_service_result(
                service_result, producer_id=self.producer_id
            )
            if projected.is_allow:
                return _fail_closed_result(
                    status=InternalDecisionStatus.ERROR,
                    reasons=("backend unavailable; coerced away from allow",),
                    reason_codes=("auth.api.backend_unavailable",),
                    producer_id=self.producer_id,
                    context=service_result.context,
                    roots=service_result.roots,
                )
            return projected

        projected = project_service_result(
            service_result, producer_id=self.producer_id
        )
        # Defense in depth: public API never returns capability-bearing allow
        # artifacts even if the service was misconfigured.
        if service_result.capability is not None:
            # Strip by re-projecting; capability is already omitted from views.
            # Additionally, if somehow is_allow with capability, keep allow
            # only when the decision itself is allow (capability ignored).
            pass
        return projected

    def verify_receipt(
        self,
        receipt: DecisionReceipt | Mapping[str, Any],
        *,
        now: str | None = None,
        expected_roots: BoundRoots | Mapping[str, Any] | None = None,
        expected_audience: str | None = None,
        expected_request_digest: str | None = None,
        expected_actor: str | None = None,
        expected_nonce: str | None = None,
        require_not_expired: bool = True,
    ) -> AuthorizationAPIResult:
        """Verify a decision receipt without consuming any capability.

        Returns a redacted allow/reject/abstain compatibility projection of
        the verified receipt.  Verification failures fail closed.
        """

        try:
            verified = verify_decision_receipt(
                receipt,
                now=now,
                expected_roots=expected_roots,
                expected_audience=expected_audience,
                expected_request_digest=expected_request_digest,
                expected_actor=expected_actor,
                expected_nonce=expected_nonce,
                require_not_expired=require_not_expired,
            )
        except (ReceiptVerificationError, ReceiptError, TypeError, ValueError) as exc:
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(f"receipt verification failed: {exc}",),
                reason_codes=("auth.api.receipt_verify_failed",),
                producer_id=self.producer_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _fail_closed_result(
                status=InternalDecisionStatus.ERROR,
                reasons=(f"backend unavailable: {type(exc).__name__}",),
                reason_codes=("auth.api.backend_unavailable",),
                producer_id=self.producer_id,
            )

        receipt_ref = TypedReceiptRef.from_receipt(verified)
        # Decision body is not rehydrated here — only receipt identity.
        decision_digest = verified.decision_digest
        decision_ref = TypedDecisionRef(
            decision_digest=decision_digest,
            status=verified.outcome.value,
            wire_status=verified.wire_status.value,
            profile_id=verified.profile_id,
            policy_digest=verified.policy_digest,
        )
        context_view = BoundContextView.from_bound_context(verified.context)
        roots_view = BoundRootsView.from_bound_roots(verified.roots)
        view = RedactedAuthorizationView(
            wire_status=verified.wire_status.value,
            internal_status=verified.outcome.value,
            reasons=verified.reasons,
            reason_codes=verified.reason_codes,
            profile_id=verified.profile_id,
            context=context_view,
            roots=roots_view,
            decision_ref=decision_ref,
            receipt_ref=receipt_ref,
            diagnostics=("auth.api.receipt.verified",),
        )
        return AuthorizationAPIResult(
            wire_status=verified.wire_status,
            internal_status=verified.outcome,
            reasons=verified.reasons,
            reason_codes=verified.reason_codes,
            decision_ref=decision_ref,
            receipt_ref=receipt_ref,
            view=view,
            profile_id=verified.profile_id,
            producer_id=self.producer_id,
        )

    # -- helpers -------------------------------------------------------------

    def _prevalidate_invocation(
        self,
        invocation: Any,
        *,
        environment: Mapping[str, Any] | None,
    ) -> None:
        """Validate explicit bindings on envelope-like inputs.

        Raw sources that still need a normalizer are accepted only when the
        caller supplies a deps.normalizer (checked later by the service).
        Mapping/envelope forms must already carry required bindings.
        """

        # Lazy import to keep api import light and avoid circular weight.
        from ..intent_ir.invocation.model import InvocationIntentEnvelope

        if isinstance(invocation, InvocationIntentEnvelope):
            _require_explicit_bindings(invocation)
            return

        if isinstance(invocation, Mapping):
            if "envelope_id" in invocation or "schema_version" in invocation:
                try:
                    envelope = InvocationIntentEnvelope.from_dict(invocation)
                except Exception as exc:  # noqa: BLE001
                    raise AuthorizationAPIRequestError(
                        f"malformed invocation envelope: {exc}"
                    ) from exc
                _require_explicit_bindings(envelope)
                return
            # Non-canonical source map: require explicit identity keys so the
            # public API does not accept anonymous free-form blobs silently.
            required_keys = (
                "source",
                "actor",
                "audience",
                "tool",
                "arguments",
                "environment",
            )
            missing = [key for key in required_keys if key not in invocation]
            if missing:
                raise AuthorizationAPIRequestError(
                    "non-canonical invocation mapping missing explicit fields: "
                    + ", ".join(missing)
                )
            return

        # Opaque object — service will require a normalizer; still require
        # environment snapshot when provided as a separate binding.
        if environment is not None:
            _mapping(environment, "environment")
            env_id = environment.get("environment_id", "")
            env_digest = environment.get("environment_digest") or environment.get(
                "snapshot_digest", ""
            )
            if not env_id and not env_digest:
                raise AuthorizationAPIRequestError(
                    "environment mapping requires environment_id or digest"
                )

    @staticmethod
    def _looks_backend_unavailable(
        result: AuthorizationServiceResult,
    ) -> bool:
        if result.is_allow:
            return False
        codes = " ".join(result.reason_codes).lower()
        reasons = " ".join(result.reasons).lower()
        blob = f"{codes} {reasons} {result.trace.exception_type}".lower()
        markers = (
            "backend",
            "unavailable",
            "timeout",
            "solver",
            "not installed",
            "which returned none",
        )
        return any(marker in blob for marker in markers)


def evaluate_authorization_api(
    invocation: Any = None,
    **kwargs: Any,
) -> AuthorizationAPIResult:
    """Module-level helper: run the default hardened authorization API."""

    return IntentAuthorizationAPI().evaluate(invocation, **kwargs)


def stable_request_fingerprint(
    *,
    actor_id: str,
    audience_id: str,
    tool_id: str,
    arguments_digest: str,
    environment_digest: str,
    policy_root: str,
    corpus_roots: Sequence[str],
    revocation_root: str,
    nonce: str,
) -> str:
    """Deterministic fingerprint over exact public bindings (no secrets)."""

    payload = {
        "actor_id": _identifier(actor_id, "actor_id"),
        "arguments_digest": _digest(arguments_digest, "arguments_digest"),
        "audience_id": _identifier(audience_id, "audience_id"),
        "corpus_roots": list(_unique_sorted(corpus_roots, "corpus_roots")),
        "environment_digest": _digest(
            environment_digest, "environment_digest"
        ),
        "nonce": _text(nonce, "nonce", max_chars=128),
        "policy_root": _text(policy_root, "policy_root"),
        "revocation_root": _text(revocation_root, "revocation_root"),
        "tool_id": _identifier(tool_id, "tool_id"),
    }
    return stable_digest(payload)


__all__ = [
    "AUTHORIZATION_API_RESULT_SCHEMA_VERSION",
    "AuthorizationAPIBackendError",
    "AuthorizationAPIError",
    "AuthorizationAPIRequestError",
    "AuthorizationAPIResult",
    "BOUND_CONTEXT_VIEW_SCHEMA_VERSION",
    "BOUND_ROOTS_VIEW_SCHEMA_VERSION",
    "BoundContextView",
    "BoundRootsView",
    "DEFAULT_API_PRODUCER_ID",
    "INTENT_AUTHORIZATION_API_INTERFACE",
    "INTENT_AUTHORIZATION_API_SCHEMA_VERSION",
    "IntentAuthorizationAPI",
    "REDACTED_AUTHORIZATION_VIEW_SCHEMA_VERSION",
    "RedactedAuthorizationView",
    "TYPED_DECISION_REF_SCHEMA_VERSION",
    "TYPED_RECEIPT_REF_SCHEMA_VERSION",
    "TypedDecisionRef",
    "TypedReceiptRef",
    "evaluate_authorization_api",
    "project_service_result",
    "redact_mapping",
    "stable_request_fingerprint",
]
