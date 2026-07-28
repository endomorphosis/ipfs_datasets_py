"""Public hardened authorization API (LIG-038).

Interface: ``IntentAuthorizationAPI@1``

Stable, redacted wrapper around :class:`IntentAuthorizationService`.  Callers
must supply explicit source / actor / audience / tool / argument /
environment bindings and exact policy / corpus / revocation roots.  Responses
expose allow/reject/abstain compatibility plus typed decision and receipt
references with bounded redacted views.

Hard invariants
---------------
* Never executes skill text, prompt bodies, MCP tools, shell, or eval.
* Never issues or consumes a dispatch capability (that is the pre-dispatch
  enforcement leaf, not this API).
* Never returns raw prompts, unrestricted arguments, secrets, witnesses, or
  private formulas.
* Unknown, malformed, or backend-unavailable paths fail closed (never allow).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..intent_ir.invocation.model import (
    ActorBinding,
    ArgumentCommitment,
    AudienceBinding,
    EnvironmentBinding,
    InvocationEnvelopeValidationError,
    InvocationIntentEnvelope,
    InvocationKind,
    InvocationScope,
    PolicyRequirements,
    ScopeEntry,
    ScopeKind,
    SourceBinding,
    ToolBinding,
    validate_invocation_envelope,
)
from ..ir_core.claims import FrozenMap, stable_digest
from .compose import (
    AUTHORIZATION_DECISION_INTERFACE,
    AuthorizationDecision,
    InternalDecisionStatus,
    map_internal_to_wire,
)
from .reasons import AdmissibilityStatus
from .receipt import (
    DECISION_RECEIPT_INTERFACE,
    BoundContext,
    BoundRoots,
    DecisionReceipt,
    ReceiptError,
    ReceiptVerificationError,
    verify_decision_receipt,
)
from .service import (
    AuthorizationBudget,
    AuthorizationServiceError,
    AuthorizationServiceResult,
    IntentAuthorizationService,
    OfflineAuthorizationDependencies,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

INTENT_AUTHORIZATION_API_INTERFACE: Final = "IntentAuthorizationAPI@1"
INTENT_AUTHORIZATION_API_SCHEMA_VERSION: Final = "intent-authorization-api/v1"
AUTHORIZATION_API_RESULT_SCHEMA_VERSION: Final = "authorization-api-result/v1"
AUTHORIZATION_API_REQUEST_SCHEMA_VERSION: Final = "authorization-api-request/v1"
TYPED_REF_SCHEMA_VERSION: Final = "authorization-typed-ref/v1"
REDACTED_VIEW_SCHEMA_VERSION: Final = "authorization-redacted-view/v1"

DEFAULT_API_PRODUCER_ID: Final = "producer:intent-authorization-api-v1"

MAX_DIAGNOSTICS: Final = 64
MAX_REASON_CHARS: Final = 256
MAX_IDENTIFIER_CHARS: Final = 256
MAX_VIEW_STRING_CHARS: Final = 512
MAX_VIEW_LIST_ITEMS: Final = 64
MAX_VIEW_DEPTH: Final = 6
MAX_VIEW_KEYS: Final = 64
MAX_REDACTED_ARG_KEYS: Final = 32

# Keys / path fragments that must never leave the API surface.
_SENSITIVE_KEY_RE: Final = re.compile(
    r"(?i)(^|[_.-])("
    r"prompt|skill_md|skill_body|source_body|source_text|raw_text|"
    r"password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"witness|proof_bytes|proof_blob|private_formula|formula_body|"
    r"raw_arguments|unredacted|credential|session[_-]?key|bearer"
    r")([_.-]|$)"
)

_SENSITIVE_VALUE_HINT_RE: Final = re.compile(
    r"(?i)(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|"
    r"sk-[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,})"
)

COMPATIBILITY_STATUSES: Final[frozenset[str]] = frozenset(
    {
        AdmissibilityStatus.ALLOW.value,
        AdmissibilityStatus.REJECT.value,
        AdmissibilityStatus.ABSTAIN.value,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthorizationAPIError(ValueError):
    """Raised (or mapped) when the public API fails closed."""


class AuthorizationAPIValidationError(AuthorizationAPIError):
    """Malformed or incomplete API input."""


class AuthorizationAPIBackendError(AuthorizationAPIError):
    """Backend unavailable or non-authoritative evaluation path."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AuthorizationAPIValidationError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise AuthorizationAPIValidationError(
            f"{name} must be a non-empty trimmed string"
        )
    if value and value != value.strip():
        raise AuthorizationAPIValidationError(
            f"{name} must not have surrounding whitespace"
        )
    if len(value) > MAX_IDENTIFIER_CHARS * 4:
        raise AuthorizationAPIValidationError(f"{name} exceeds maximum length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) > MAX_IDENTIFIER_CHARS:
        raise AuthorizationAPIValidationError(f"{name} exceeds maximum length")
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorizationAPIValidationError(f"{name} must be a mapping")
    return value


def _sequence_of_text(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise AuthorizationAPIValidationError(
            f"{name} must be a sequence of strings"
        )
    items = tuple(_text(item, f"{name} item") for item in value)
    if len(items) != len(set(items)):
        raise AuthorizationAPIValidationError(f"{name} must be unique")
    return tuple(sorted(items))


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(key))


def _truncate_str(value: str, *, limit: int = MAX_VIEW_STRING_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def redact_value(
    value: Any,
    *,
    depth: int = 0,
    path: str = "root",
) -> Any:
    """Bound and redact a JSON-ish structure for public API views.

    Removes sensitive keys, bounds depth/list size/string length, and replaces
    opaque private material with ``[REDACTED]``.
    """

    if depth > MAX_VIEW_DEPTH:
        return "[REDACTED:depth]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _SENSITIVE_VALUE_HINT_RE.search(value):
            return "[REDACTED]"
        return _truncate_str(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        keys = list(value.keys())[:MAX_VIEW_KEYS]
        for key in keys:
            key_s = str(key)
            if _is_sensitive_key(key_s):
                out[key_s] = "[REDACTED]"
                continue
            child_path = f"{path}.{key_s}"
            out[key_s] = redact_value(
                value[key], depth=depth + 1, path=child_path
            )
        if len(value) > MAX_VIEW_KEYS:
            out["_truncated_keys"] = len(value) - MAX_VIEW_KEYS
        return out
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        items = list(value)[:MAX_VIEW_LIST_ITEMS]
        redacted_items = [
            redact_value(item, depth=depth + 1, path=f"{path}[{index}]")
            for index, item in enumerate(items)
        ]
        if len(value) > MAX_VIEW_LIST_ITEMS:
            redacted_items.append(
                f"[REDACTED:{len(value) - MAX_VIEW_LIST_ITEMS}_more]"
            )
        return redacted_items
    # Never expose arbitrary objects.
    return f"[REDACTED:{type(value).__name__}]"


def _bound_reasons(values: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        text = _truncate_str(raw.strip(), limit=MAX_REASON_CHARS)
        if not text or text in seen:
            continue
        if _is_sensitive_key(text) or _SENSITIVE_VALUE_HINT_RE.search(text):
            text = "[REDACTED:reason]"
        seen.add(text)
        out.append(text)
        if len(out) >= MAX_DIAGNOSTICS:
            break
    return tuple(out)


# ---------------------------------------------------------------------------
# Typed refs and redacted views
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedDecisionRef:
    """Stable typed reference to an ``AuthorizationDecision@1``."""

    ref_id: str
    digest: str
    interface: str = AUTHORIZATION_DECISION_INTERFACE
    schema_version: str = TYPED_REF_SCHEMA_VERSION
    status: str = ""
    wire_status: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _identifier(self.ref_id, "ref_id"))
        object.__setattr__(self, "digest", _text(self.digest, "digest"))
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        if self.interface != AUTHORIZATION_DECISION_INTERFACE:
            raise AuthorizationAPIValidationError(
                f"unsupported decision ref interface: {self.interface!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self, "status", _optional_text(self.status, "status")
        )
        object.__setattr__(
            self,
            "wire_status",
            _optional_text(self.wire_status, "wire_status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "interface": self.interface,
            "ref_id": self.ref_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "wire_status": self.wire_status,
        }

    @classmethod
    def from_decision(cls, decision: AuthorizationDecision) -> "TypedDecisionRef":
        digest = decision.digest
        return cls(
            ref_id=f"decision:{digest[:24]}",
            digest=digest,
            status=decision.status.value,
            wire_status=decision.wire_status.value,
        )


@dataclass(frozen=True, slots=True)
class TypedReceiptRef:
    """Stable typed reference to a ``DecisionReceipt@1``."""

    ref_id: str
    digest: str
    content_cid: str = ""
    interface: str = DECISION_RECEIPT_INTERFACE
    schema_version: str = TYPED_REF_SCHEMA_VERSION
    wire_status: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _identifier(self.ref_id, "ref_id"))
        object.__setattr__(self, "digest", _text(self.digest, "digest"))
        object.__setattr__(
            self,
            "content_cid",
            _optional_text(self.content_cid, "content_cid"),
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        if self.interface != DECISION_RECEIPT_INTERFACE:
            raise AuthorizationAPIValidationError(
                f"unsupported receipt ref interface: {self.interface!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "wire_status",
            _optional_text(self.wire_status, "wire_status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_cid": self.content_cid,
            "digest": self.digest,
            "interface": self.interface,
            "ref_id": self.ref_id,
            "schema_version": self.schema_version,
            "wire_status": self.wire_status,
        }

    @classmethod
    def from_receipt(cls, receipt: DecisionReceipt) -> "TypedReceiptRef":
        return cls(
            ref_id=receipt.receipt_id,
            digest=receipt.digest,
            content_cid=receipt.content_cid,
            wire_status=receipt.wire_status.value,
        )


def redacted_decision_view(
    decision: AuthorizationDecision | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Public redacted view of an authorization decision (no formulas/jobs)."""

    if decision is None:
        return None
    if isinstance(decision, AuthorizationDecision):
        payload = {
            "bundle_digest": decision.bundle_digest,
            "policy_digest": decision.policy_digest,
            "profile_id": decision.profile_id,
            "reason_codes": list(decision.reason_codes)[:MAX_DIAGNOSTICS],
            "reasons": list(_bound_reasons(decision.reasons)),
            "selected_evidence_cids": list(decision.selected_evidence_cids)[
                :MAX_VIEW_LIST_ITEMS
            ],
            "status": decision.status.value,
            "wire_status": decision.wire_status.value,
            "decision_digest": decision.digest,
            "residual_obligations": list(decision.residual_obligations)[
                :MAX_VIEW_LIST_ITEMS
            ],
            "interface": AUTHORIZATION_DECISION_INTERFACE,
            "schema_version": REDACTED_VIEW_SCHEMA_VERSION,
            # Intentionally omit job_results / diagnostics bodies / metadata
            # that may carry private formula material.
        }
        return redact_value(payload)
    return redact_value(
        {
            k: v
            for k, v in dict(decision).items()
            if k
            not in {
                "job_results",
                "diagnostics",
                "metadata",
                "formulas",
                "witnesses",
            }
        }
    )


def redacted_receipt_view(
    receipt: DecisionReceipt | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Public redacted view of a decision receipt (digests only)."""

    if receipt is None:
        return None
    if isinstance(receipt, DecisionReceipt):
        payload = {
            "receipt_id": receipt.receipt_id,
            "content_cid": receipt.content_cid,
            "content_digest": receipt.content_digest,
            "outcome": receipt.outcome.value,
            "wire_status": receipt.wire_status.value,
            "reason_codes": list(receipt.reason_codes)[:MAX_DIAGNOSTICS],
            "reasons": list(_bound_reasons(receipt.reasons)),
            "profile_id": receipt.profile_id,
            "issued_at": receipt.issued_at,
            "deadline": receipt.deadline,
            "expiry": receipt.expiry,
            "producer_id": receipt.producer_id,
            "decision_digest": receipt.decision_digest,
            "policy_digest": receipt.policy_digest,
            "selected_evidence_digest": receipt.selected_evidence_digest,
            "selected_evidence_cids": list(receipt.selected_evidence_cids)[
                :MAX_VIEW_LIST_ITEMS
            ],
            "obligation_ids": list(receipt.obligation_ids)[:MAX_VIEW_LIST_ITEMS],
            "residual_duties": list(receipt.residual_duties)[
                :MAX_VIEW_LIST_ITEMS
            ],
            "context": {
                "actor_id": receipt.context.actor_id,
                "audience_id": receipt.context.audience_id,
                "tool_id": receipt.context.tool_id,
                "tool_version": receipt.context.tool_version,
                "request_digest": receipt.context.request_digest,
                "arguments_digest": receipt.context.arguments_digest,
                "environment_digest": receipt.context.environment_digest,
                "environment_id": receipt.context.environment_id,
                "effect_ids": list(receipt.context.effect_ids)[
                    :MAX_VIEW_LIST_ITEMS
                ],
                "nonce": receipt.context.nonce,
            },
            "roots": {
                "policy_root": receipt.roots.policy_root,
                "corpus_roots": list(receipt.roots.corpus_roots)[
                    :MAX_VIEW_LIST_ITEMS
                ],
                "revocation_root": receipt.roots.revocation_root,
            },
            "interface": DECISION_RECEIPT_INTERFACE,
            "schema_version": REDACTED_VIEW_SCHEMA_VERSION,
        }
        return redact_value(payload)
    raw = dict(receipt)
    # Drop fields that may embed private material.
    for key in (
        "metadata",
        "attempt_digests",
        "result_digests",
        "capability",
        "witnesses",
        "proofs",
    ):
        raw.pop(key, None)
    return redact_value(raw)


def redacted_context_view(
    context: BoundContext | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if context is None:
        return None
    if isinstance(context, BoundContext):
        return redact_value(
            {
                "actor_id": context.actor_id,
                "audience_id": context.audience_id,
                "tool_id": context.tool_id,
                "tool_version": context.tool_version,
                "request_digest": context.request_digest,
                "arguments_digest": context.arguments_digest,
                "environment_digest": context.environment_digest,
                "environment_id": context.environment_id,
                "effect_ids": list(context.effect_ids)[:MAX_VIEW_LIST_ITEMS],
                "nonce": context.nonce,
                "schema_version": REDACTED_VIEW_SCHEMA_VERSION,
            }
        )
    return redact_value(context)


def redacted_roots_view(
    roots: BoundRoots | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if roots is None:
        return None
    if isinstance(roots, BoundRoots):
        return redact_value(
            {
                "policy_root": roots.policy_root,
                "corpus_roots": list(roots.corpus_roots)[:MAX_VIEW_LIST_ITEMS],
                "revocation_root": roots.revocation_root,
                "schema_version": REDACTED_VIEW_SCHEMA_VERSION,
            }
        )
    return redact_value(roots)


# ---------------------------------------------------------------------------
# Request / result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationAPIResult:
    """Redacted public result of :meth:`IntentAuthorizationAPI.evaluate`.

    ``compatibility`` is the legacy allow/reject/abstain wire status.
    ``status`` preserves the richer internal decision status when available.
    Capability tokens are never present on this surface.
    """

    compatibility: AdmissibilityStatus
    status: InternalDecisionStatus
    reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    decision_ref: TypedDecisionRef | None = None
    receipt_ref: TypedReceiptRef | None = None
    decision_view: Mapping[str, Any] | None = None
    receipt_view: Mapping[str, Any] | None = None
    context_view: Mapping[str, Any] | None = None
    roots_view: Mapping[str, Any] | None = None
    profile_id: str = ""
    executed: bool = False
    capability_issued: bool = False
    capability_consumed: bool = False
    error: str = ""
    error_type: str = ""
    interface: str = INTENT_AUTHORIZATION_API_INTERFACE
    schema_version: str = AUTHORIZATION_API_RESULT_SCHEMA_VERSION
    producer_id: str = DEFAULT_API_PRODUCER_ID
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        compat = self.compatibility
        if not isinstance(compat, AdmissibilityStatus):
            compat = AdmissibilityStatus(compat)
        status = self.status
        if not isinstance(status, InternalDecisionStatus):
            status = InternalDecisionStatus(status)
        expected = map_internal_to_wire(status)
        if compat is not expected:
            # Fail closed: never advertise allow when internal status disagrees.
            if compat is AdmissibilityStatus.ALLOW:
                raise AuthorizationAPIError(
                    "compatibility allow inconsistent with internal status "
                    f"{status.value!r} (fail closed)"
                )
            # Prefer the internal→wire mapping for non-allow paths.
            compat = expected
        object.__setattr__(self, "compatibility", compat)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reasons", _bound_reasons(self.reasons))
        object.__setattr__(
            self, "reason_codes", _bound_reasons(self.reason_codes)
        )
        object.__setattr__(
            self, "profile_id", _optional_text(self.profile_id, "profile_id")
        )
        object.__setattr__(self, "executed", bool(self.executed))
        object.__setattr__(
            self, "capability_issued", bool(self.capability_issued)
        )
        object.__setattr__(
            self, "capability_consumed", bool(self.capability_consumed)
        )
        if self.executed:
            raise AuthorizationAPIError(
                "API result cannot claim execution (fail closed)"
            )
        if self.capability_issued or self.capability_consumed:
            raise AuthorizationAPIError(
                "API surface cannot issue or consume dispatch capabilities"
            )
        object.__setattr__(self, "error", _optional_text(self.error, "error"))
        object.__setattr__(
            self, "error_type", _optional_text(self.error_type, "error_type")
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        if self.interface != INTENT_AUTHORIZATION_API_INTERFACE:
            raise AuthorizationAPIError(
                f"unsupported API interface: {self.interface!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != AUTHORIZATION_API_RESULT_SCHEMA_VERSION:
            raise AuthorizationAPIError(
                f"unsupported API result schema: {self.schema_version!r}"
            )
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self, "diagnostics", _bound_reasons(self.diagnostics)
        )
        if self.decision_view is not None and not isinstance(
            self.decision_view, Mapping
        ):
            raise AuthorizationAPIError("decision_view must be a mapping")
        if self.receipt_view is not None and not isinstance(
            self.receipt_view, Mapping
        ):
            raise AuthorizationAPIError("receipt_view must be a mapping")
        if self.context_view is not None and not isinstance(
            self.context_view, Mapping
        ):
            raise AuthorizationAPIError("context_view must be a mapping")
        if self.roots_view is not None and not isinstance(
            self.roots_view, Mapping
        ):
            raise AuthorizationAPIError("roots_view must be a mapping")
        # Force redaction of any residual sensitive material.
        if self.decision_view is not None:
            object.__setattr__(
                self, "decision_view", FrozenMap(redact_value(self.decision_view))
            )
        if self.receipt_view is not None:
            object.__setattr__(
                self, "receipt_view", FrozenMap(redact_value(self.receipt_view))
            )
        if self.context_view is not None:
            object.__setattr__(
                self, "context_view", FrozenMap(redact_value(self.context_view))
            )
        if self.roots_view is not None:
            object.__setattr__(
                self, "roots_view", FrozenMap(redact_value(self.roots_view))
            )

    @property
    def is_allow(self) -> bool:
        return (
            self.compatibility is AdmissibilityStatus.ALLOW
            and self.status is InternalDecisionStatus.ALLOW
        )

    @property
    def wire_status(self) -> AdmissibilityStatus:
        """Alias for allow/reject/abstain compatibility."""

        return self.compatibility

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_consumed": False,
            "capability_issued": False,
            "compatibility": self.compatibility.value,
            "context_view": (
                None
                if self.context_view is None
                else (
                    self.context_view.to_dict()
                    if isinstance(self.context_view, FrozenMap)
                    else dict(self.context_view)
                )
            ),
            "decision_ref": (
                None
                if self.decision_ref is None
                else self.decision_ref.to_dict()
            ),
            "decision_view": (
                None
                if self.decision_view is None
                else (
                    self.decision_view.to_dict()
                    if isinstance(self.decision_view, FrozenMap)
                    else dict(self.decision_view)
                )
            ),
            "diagnostics": list(self.diagnostics),
            "error": self.error,
            "error_type": self.error_type,
            "executed": False,
            "interface": self.interface,
            "producer_id": self.producer_id,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "receipt_ref": (
                None if self.receipt_ref is None else self.receipt_ref.to_dict()
            ),
            "receipt_view": (
                None
                if self.receipt_view is None
                else (
                    self.receipt_view.to_dict()
                    if isinstance(self.receipt_view, FrozenMap)
                    else dict(self.receipt_view)
                )
            ),
            "roots_view": (
                None
                if self.roots_view is None
                else (
                    self.roots_view.to_dict()
                    if isinstance(self.roots_view, FrozenMap)
                    else dict(self.roots_view)
                )
            ),
            "schema_version": self.schema_version,
            "status": self.status.value,
            "wire_status": self.compatibility.value,
        }


# ---------------------------------------------------------------------------
# Input coercion
# ---------------------------------------------------------------------------


def _coerce_source(value: Any) -> SourceBinding:
    if isinstance(value, SourceBinding):
        return value
    if isinstance(value, str):
        return SourceBinding(
            kind=InvocationKind.SKILLCENTER,
            source_ref=value,
            source_revision="unspecified",
            intent_document_id="intent-doc:api-unspecified",
            formalization_artifact_id="formal:api-unspecified",
        )
    data = _mapping(value, "source")
    if hasattr(SourceBinding, "from_dict"):
        try:
            return SourceBinding.from_dict(data)
        except Exception as exc:  # noqa: BLE001 — map to API validation
            raise AuthorizationAPIValidationError(
                f"invalid source binding: {exc}"
            ) from exc
    kind = data.get("kind", InvocationKind.SKILLCENTER)
    if isinstance(kind, str):
        try:
            kind = InvocationKind(kind)
        except ValueError as exc:
            raise AuthorizationAPIValidationError(
                f"unknown source kind {kind!r}; fail closed"
            ) from exc
    return SourceBinding(
        kind=kind,
        source_ref=_text(
            data.get("source_ref", data.get("ref", "")), "source_ref"
        ),
        source_revision=_text(
            data.get("source_revision", data.get("revision", "unspecified")),
            "source_revision",
        ),
        intent_document_id=_text(
            data.get("intent_document_id", "intent-doc:api-unspecified"),
            "intent_document_id",
        ),
        formalization_artifact_id=_text(
            data.get("formalization_artifact_id", "formal:api-unspecified"),
            "formalization_artifact_id",
        ),
    )


def _coerce_actor(value: Any) -> ActorBinding:
    if isinstance(value, ActorBinding):
        return value
    if isinstance(value, str):
        return ActorBinding(actor_id=value)
    data = _mapping(value, "actor")
    actor_id = data.get("actor_id") or data.get("id")
    if not actor_id:
        raise AuthorizationAPIValidationError("actor.actor_id is required")
    return ActorBinding(actor_id=_identifier(actor_id, "actor.actor_id"))


def _coerce_audience(value: Any) -> AudienceBinding:
    if isinstance(value, AudienceBinding):
        return value
    if isinstance(value, str):
        return AudienceBinding(audience_id=value)
    data = _mapping(value, "audience")
    audience_id = data.get("audience_id") or data.get("id")
    if not audience_id:
        raise AuthorizationAPIValidationError("audience.audience_id is required")
    return AudienceBinding(
        audience_id=_identifier(audience_id, "audience.audience_id")
    )


def _coerce_tool(value: Any) -> ToolBinding:
    if isinstance(value, ToolBinding):
        return value
    if isinstance(value, str):
        return ToolBinding(tool_id=value, tool_version="0")
    data = _mapping(value, "tool")
    tool_id = data.get("tool_id") or data.get("id") or data.get("name")
    if not tool_id:
        raise AuthorizationAPIValidationError("tool.tool_id is required")
    version = data.get("tool_version") or data.get("version") or "0"
    return ToolBinding(
        tool_id=_identifier(tool_id, "tool.tool_id"),
        tool_version=_text(version, "tool.tool_version"),
    )


def _coerce_arguments(value: Any) -> ArgumentCommitment:
    if isinstance(value, ArgumentCommitment):
        # Re-validate redaction invariants.
        return ArgumentCommitment.from_dict(value.to_dict())
    if value is None:
        raise AuthorizationAPIValidationError("arguments are required")
    if isinstance(value, Mapping):
        # If already an ArgumentCommitment shape, accept it; otherwise treat
        # the mapping as redacted argument display values.
        if "commitment" in value or "redacted_arguments" in value:
            return ArgumentCommitment.from_dict(value)
        if any(_is_sensitive_key(str(k)) for k in value):
            raise AuthorizationAPIValidationError(
                "arguments contain sensitive keys; supply redacted arguments only"
            )
        redacted = redact_value(dict(value))
        if not isinstance(redacted, dict):
            raise AuthorizationAPIValidationError(
                "arguments redaction produced non-mapping"
            )
        if len(redacted) > MAX_REDACTED_ARG_KEYS:
            raise AuthorizationAPIValidationError(
                "arguments exceed redacted key bound"
            )
        return ArgumentCommitment.from_redacted(redacted)
    raise AuthorizationAPIValidationError(
        "arguments must be a mapping or ArgumentCommitment"
    )


def _normalize_sha256_digest(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("sha256:"):
        hex_part = text[len("sha256:") :]
    else:
        hex_part = text
        text = f"sha256:{hex_part}"
    if len(hex_part) != 64 or any(c not in "0123456789abcdef" for c in hex_part):
        raise AuthorizationAPIValidationError(
            f"{name} must be sha256:<64-lowercase-hex>"
        )
    return text


def _coerce_environment(value: Any) -> EnvironmentBinding:
    if isinstance(value, EnvironmentBinding):
        return value
    data = _mapping(value, "environment")
    environment_id = data.get("environment_id") or data.get("id")
    snapshot = data.get("snapshot_digest") or data.get("digest")
    if not environment_id:
        raise AuthorizationAPIValidationError(
            "environment.environment_id is required"
        )
    if not snapshot:
        raise AuthorizationAPIValidationError(
            "environment.snapshot_digest is required"
        )
    return EnvironmentBinding(
        environment_id=_identifier(
            environment_id, "environment.environment_id"
        ),
        snapshot_digest=_normalize_sha256_digest(
            snapshot, "environment.snapshot_digest"
        ),
    )


def _coerce_scope(value: Any | None) -> InvocationScope:
    if value is None:
        return InvocationScope(
            actions=(
                ScopeEntry(
                    entry_id="scope-action-api-default",
                    kind=ScopeKind.ACTION,
                    value="action:api-evaluate",
                ),
            ),
            effects=(
                ScopeEntry(
                    entry_id="scope-effect-api-default",
                    kind=ScopeKind.EFFECT,
                    value="effect:api-none",
                ),
            ),
        )
    if isinstance(value, InvocationScope):
        return value
    data = _mapping(value, "scope")
    try:
        scope = InvocationScope.from_dict(data)
    except Exception as exc:  # noqa: BLE001
        raise AuthorizationAPIValidationError(
            f"invalid scope: {exc}"
        ) from exc
    if not scope.actions:
        raise AuthorizationAPIValidationError(
            "scope.actions must contain at least one action"
        )
    return scope


def _require_explicit_roots(
    *,
    policy_root: Any,
    corpus_roots: Any,
    revocation_root: Any,
    legal_corpus_ref: Any = "",
    security_corpus_ref: Any = "",
    intent_corpus_ref: Any = "",
) -> tuple[str, tuple[str, ...], str]:
    policy = _text(policy_root, "policy_root")
    roots = list(_sequence_of_text(corpus_roots, "corpus_roots"))
    for label, ref in (
        ("legal_corpus_ref", legal_corpus_ref),
        ("security_corpus_ref", security_corpus_ref),
        ("intent_corpus_ref", intent_corpus_ref),
    ):
        text = _optional_text(ref, label)
        if text and text not in roots:
            roots.append(text)
    if not roots:
        raise AuthorizationAPIValidationError(
            "at least one corpus root is required "
            "(corpus_roots and/or legal/security/intent refs)"
        )
    # Revocation root is required as an explicit binding (may be a well-known
    # empty-revocation sentinel, but the field itself must be provided).
    if revocation_root is None:
        raise AuthorizationAPIValidationError(
            "revocation_root is required (exact root binding)"
        )
    rev = _text(revocation_root, "revocation_root", allow_empty=True)
    # Empty string is only allowed when caller intentionally passes ""; still
    # counts as an explicit binding.  Whitespace-only is rejected by _text.
    return policy, tuple(sorted(set(roots))), rev


def build_invocation_envelope(
    *,
    source: Any,
    actor: Any,
    audience: Any,
    tool: Any,
    arguments: Any,
    environment: Any,
    policy_root: str,
    corpus_roots: Sequence[str],
    revocation_root: str,
    envelope_id: str = "",
    tenant_id: str = "tenant:api",
    nonce: str = "",
    created_at: str = "2026-07-28T12:00:00Z",
    deadline: str = "2026-07-28T12:10:00Z",
    profile: str = "legal-strict",
    scope: Any | None = None,
    invocation_kind: Any | None = None,
) -> InvocationIntentEnvelope:
    """Assemble and validate a canonical invocation from explicit fields."""

    source_b = _coerce_source(source)
    actor_b = _coerce_actor(actor)
    audience_b = _coerce_audience(audience)
    tool_b = _coerce_tool(tool)
    args_b = _coerce_arguments(arguments)
    env_b = _coerce_environment(environment)
    scope_b = _coerce_scope(scope)

    if not envelope_id:
        envelope_id = "env:api:" + stable_digest(
            {
                "actor": actor_b.actor_id,
                "audience": audience_b.audience_id,
                "source": source_b.source_ref,
                "tool": tool_b.tool_id,
                "args": args_b.commitment,
            }
        )[:20]
    if not nonce:
        nonce = "nonce:api:" + stable_digest(
            {"envelope_id": envelope_id, "created_at": created_at}
        )[:16]

    kind = invocation_kind or source_b.kind
    if isinstance(kind, str):
        kind = InvocationKind(kind)

    envelope = InvocationIntentEnvelope(
        envelope_id=_identifier(envelope_id, "envelope_id"),
        source=source_b,
        tenant_id=_identifier(tenant_id, "tenant_id"),
        actor=actor_b,
        audience=audience_b,
        tool=tool_b,
        arguments=args_b,
        nonce=_text(nonce, "nonce"),
        created_at=_text(created_at, "created_at"),
        deadline=_text(deadline, "deadline"),
        invocation_kind=kind,
        policy=PolicyRequirements(
            policy_profile=_text(profile, "profile"),
            policy_root=policy_root,
            corpus_roots=tuple(corpus_roots),
            revocation_root=revocation_root,
        ),
        scope=scope_b,
        environment=env_b,
    )
    validate_invocation_envelope(envelope)
    return envelope


def _validate_envelope_explicit_fields(
    envelope: InvocationIntentEnvelope,
) -> None:
    """Fail closed if a provided envelope omits required security fields."""

    if not envelope.source or not envelope.source.source_ref:
        raise AuthorizationAPIValidationError("envelope.source is required")
    if not envelope.actor or not envelope.actor.actor_id:
        raise AuthorizationAPIValidationError("envelope.actor is required")
    if not envelope.audience or not envelope.audience.audience_id:
        raise AuthorizationAPIValidationError("envelope.audience is required")
    if not envelope.tool or not envelope.tool.tool_id:
        raise AuthorizationAPIValidationError("envelope.tool is required")
    if envelope.arguments is None:
        raise AuthorizationAPIValidationError("envelope.arguments are required")
    if not envelope.environment or not envelope.environment.environment_id:
        raise AuthorizationAPIValidationError("envelope.environment is required")
    if not envelope.environment.snapshot_digest:
        raise AuthorizationAPIValidationError(
            "envelope.environment.snapshot_digest is required"
        )


# ---------------------------------------------------------------------------
# Result projection from service
# ---------------------------------------------------------------------------


def _result_from_service(
    service_result: AuthorizationServiceResult,
    *,
    producer_id: str,
    error: str = "",
    error_type: str = "",
) -> AuthorizationAPIResult:
    decision = service_result.decision
    receipt = service_result.receipt
    decision_ref = (
        TypedDecisionRef.from_decision(decision) if decision is not None else None
    )
    receipt_ref = (
        TypedReceiptRef.from_receipt(receipt) if receipt is not None else None
    )
    diagnostics: list[str] = []
    if service_result.trace is not None:
        for item in service_result.trace.diagnostics[:MAX_DIAGNOSTICS]:
            # Keep stage labels; drop free-form payloads that may hold secrets.
            if isinstance(item, str) and (
                item.startswith("auth.service.")
                or item.startswith("auth.api.")
            ):
                diagnostics.append(_truncate_str(item, limit=MAX_REASON_CHARS))

    return AuthorizationAPIResult(
        compatibility=service_result.wire_status,
        status=service_result.status,
        reasons=service_result.reasons,
        reason_codes=service_result.reason_codes,
        decision_ref=decision_ref,
        receipt_ref=receipt_ref,
        decision_view=redacted_decision_view(decision),
        receipt_view=redacted_receipt_view(receipt),
        context_view=redacted_context_view(service_result.context),
        roots_view=redacted_roots_view(service_result.roots),
        profile_id=service_result.profile_id,
        executed=False,
        capability_issued=False,
        capability_consumed=False,
        error=error,
        error_type=error_type,
        producer_id=producer_id,
        diagnostics=tuple(diagnostics),
    )


def _fail_closed_api_result(
    *,
    reason: str,
    error_type: str = "fail_closed",
    status: InternalDecisionStatus = InternalDecisionStatus.ERROR,
    producer_id: str = DEFAULT_API_PRODUCER_ID,
    profile_id: str = "",
) -> AuthorizationAPIResult:
    wire = map_internal_to_wire(status)
    assert wire is not AdmissibilityStatus.ALLOW
    return AuthorizationAPIResult(
        compatibility=wire,
        status=status,
        reasons=(reason,),
        reason_codes=(f"api.{error_type}",),
        decision_ref=None,
        receipt_ref=None,
        decision_view=None,
        receipt_view=None,
        context_view=None,
        roots_view=None,
        profile_id=profile_id,
        executed=False,
        capability_issued=False,
        capability_consumed=False,
        error=reason,
        error_type=error_type,
        producer_id=producer_id,
        diagnostics=("auth.api.fail_closed",),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentAuthorizationAPI:
    """``IntentAuthorizationAPI@1`` — hardened, redacted authorization surface.

    Does not dispatch tools, does not issue/consume dispatch capabilities, and
    never returns raw private content.  Evaluation is delegated to
    :class:`IntentAuthorizationService` with ``derive_capability_on_allow``
    forced off.
    """

    producer_id: str = DEFAULT_API_PRODUCER_ID
    interface: str = INTENT_AUTHORIZATION_API_INTERFACE
    schema_version: str = INTENT_AUTHORIZATION_API_SCHEMA_VERSION
    service: IntentAuthorizationService | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        if self.interface != INTENT_AUTHORIZATION_API_INTERFACE:
            raise AuthorizationAPIError(
                f"unsupported API interface: {self.interface!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != INTENT_AUTHORIZATION_API_SCHEMA_VERSION:
            raise AuthorizationAPIError(
                f"unsupported API schema: {self.schema_version!r}"
            )

    def _service(self) -> IntentAuthorizationService:
        return self.service or IntentAuthorizationService(
            producer_id=self.producer_id
        )

    def evaluate(
        self,
        *,
        source: Any = None,
        actor: Any = None,
        audience: Any = None,
        tool: Any = None,
        arguments: Any = None,
        environment: Any = None,
        policy_root: Any = None,
        corpus_roots: Any = None,
        revocation_root: Any = None,
        legal_corpus_ref: str = "",
        security_corpus_ref: str = "",
        intent_corpus_ref: str = "",
        invocation: Any = None,
        profile: str | None = None,
        budget: AuthorizationBudget | Mapping[str, Any] | None = None,
        deps: OfflineAuthorizationDependencies | None = None,
        envelope_id: str = "",
        tenant_id: str = "tenant:api",
        nonce: str = "",
        created_at: str = "2026-07-28T12:00:00Z",
        deadline: str = "2026-07-28T12:10:00Z",
        scope: Any | None = None,
        # Explicitly rejected capability / execution knobs:
        derive_capability_on_allow: bool = False,
        execute_target: bool = False,
        consume_capability: bool = False,
        issue_capability: bool = False,
        **_ignored: Any,
    ) -> AuthorizationAPIResult:
        """Evaluate an exact-context authorization request.

        Requires explicit ``source``, ``actor``, ``audience``, ``tool``,
        ``arguments``, ``environment``, ``policy_root``, corpus roots, and
        ``revocation_root``.  A pre-built ``invocation`` envelope may be
        supplied in addition, but the explicit roots remain mandatory and the
        envelope must already carry the required bindings.

        Capability issue/consume and target execution flags are rejected.
        """

        try:
            if execute_target or consume_capability or issue_capability:
                raise AuthorizationAPIValidationError(
                    "API cannot execute targets or issue/consume dispatch "
                    "capabilities (fail closed)"
                )
            if derive_capability_on_allow:
                raise AuthorizationAPIValidationError(
                    "derive_capability_on_allow is forbidden on the public "
                    "API surface (fail closed)"
                )

            if policy_root is None or corpus_roots is None or revocation_root is None:
                # Allow roots to come only from explicit kwargs — not silently
                # from an envelope — so callers always pin exact roots.
                missing = [
                    name
                    for name, val in (
                        ("policy_root", policy_root),
                        ("corpus_roots", corpus_roots),
                        ("revocation_root", revocation_root),
                    )
                    if val is None
                ]
                raise AuthorizationAPIValidationError(
                    "exact roots required: " + ", ".join(missing)
                )

            policy, corpus, revocation = _require_explicit_roots(
                policy_root=policy_root,
                corpus_roots=corpus_roots,
                revocation_root=revocation_root,
                legal_corpus_ref=legal_corpus_ref,
                security_corpus_ref=security_corpus_ref,
                intent_corpus_ref=intent_corpus_ref,
            )

            envelope: InvocationIntentEnvelope
            if invocation is not None:
                if isinstance(invocation, InvocationIntentEnvelope):
                    envelope = invocation
                elif isinstance(invocation, Mapping):
                    envelope = InvocationIntentEnvelope.from_dict(invocation)
                else:
                    raise AuthorizationAPIValidationError(
                        "invocation must be an envelope or mapping"
                    )
                _validate_envelope_explicit_fields(envelope)
                # Explicit field overrides still required when provided so the
                # caller cannot skip actor/tool by only passing an envelope
                # without also declaring the security-relevant bindings.
                for label, provided in (
                    ("source", source),
                    ("actor", actor),
                    ("audience", audience),
                    ("tool", tool),
                    ("arguments", arguments),
                    ("environment", environment),
                ):
                    if provided is None:
                        raise AuthorizationAPIValidationError(
                            f"{label} is required explicitly alongside invocation"
                        )
            else:
                for label, provided in (
                    ("source", source),
                    ("actor", actor),
                    ("audience", audience),
                    ("tool", tool),
                    ("arguments", arguments),
                    ("environment", environment),
                ):
                    if provided is None:
                        raise AuthorizationAPIValidationError(
                            f"{label} is required"
                        )
                envelope = build_invocation_envelope(
                    source=source,
                    actor=actor,
                    audience=audience,
                    tool=tool,
                    arguments=arguments,
                    environment=environment,
                    policy_root=policy,
                    corpus_roots=corpus,
                    revocation_root=revocation,
                    envelope_id=envelope_id,
                    tenant_id=tenant_id,
                    nonce=nonce,
                    created_at=created_at,
                    deadline=deadline,
                    profile=profile or "legal-strict",
                    scope=scope,
                )

            # Force safe budget defaults when none provided.
            if budget is None:
                budget_obj = AuthorizationBudget(production_mode=True)
            elif isinstance(budget, AuthorizationBudget):
                budget_obj = budget
            else:
                budget_obj = AuthorizationBudget.from_dict(
                    _mapping(budget, "budget")
                )
            budget_obj.validate_side_effect_flags()

            service_result = self._service().evaluate(
                envelope,
                policy_ref=policy,
                legal_corpus_ref=legal_corpus_ref or (
                    corpus[0] if corpus else ""
                ),
                security_corpus_ref=security_corpus_ref,
                intent_corpus_ref=intent_corpus_ref,
                revocation_root=revocation,
                environment={
                    "environment_id": envelope.environment.environment_id,
                    "snapshot_digest": envelope.environment.snapshot_digest,
                },
                budget=budget_obj,
                profile=profile or envelope.policy.policy_profile,
                deps=deps,
                # Hard force: public API never mints dispatch capabilities.
                derive_capability_on_allow=False,
            )

            # Backend-unavailable / non-authoritative paths must not allow.
            if service_result.capability is not None:
                # Defensive: service must not have issued one; strip and fail.
                return _fail_closed_api_result(
                    reason=(
                        "service returned a capability on the public API "
                        "surface; stripped and rejected (fail closed)"
                    ),
                    error_type="capability_forbidden",
                    status=InternalDecisionStatus.ERROR,
                    producer_id=self.producer_id,
                    profile_id=service_result.profile_id,
                )

            error = ""
            error_type = ""
            if service_result.status is not InternalDecisionStatus.ALLOW:
                if any(
                    "unavailable" in code or "backend" in code
                    for code in service_result.reason_codes
                ) or any(
                    "unavailable" in r.lower() or "backend" in r.lower()
                    for r in service_result.reasons
                ):
                    error = "backend unavailable or non-authoritative; fail closed"
                    error_type = "backend_unavailable"
                elif service_result.trace.exception_type:
                    error = (
                        service_result.trace.exception_message
                        or service_result.trace.exception_type
                    )
                    error_type = service_result.trace.exception_type
                elif service_result.reasons:
                    error = service_result.reasons[0]
                    error_type = "non_allow"

            return _result_from_service(
                service_result,
                producer_id=self.producer_id,
                error=error,
                error_type=error_type,
            )
        except (
            AuthorizationAPIValidationError,
            AuthorizationAPIError,
            AuthorizationServiceError,
            InvocationEnvelopeValidationError,
            ReceiptError,
            ValueError,
            TypeError,
        ) as exc:
            return _fail_closed_api_result(
                reason=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
                status=InternalDecisionStatus.ERROR,
                producer_id=self.producer_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail closed
            return _fail_closed_api_result(
                reason=f"unexpected evaluation failure: {type(exc).__name__}",
                error_type=type(exc).__name__,
                status=InternalDecisionStatus.ERROR,
                producer_id=self.producer_id,
            )

    def verify_receipt(
        self,
        receipt: DecisionReceipt | Mapping[str, Any],
        *,
        expected_policy_root: str = "",
        expected_corpus_roots: Sequence[str] | None = None,
        expected_revocation_root: str | None = None,
        expected_audience: str = "",
        expected_actor: str = "",
        now: str | None = None,
    ) -> AuthorizationAPIResult:
        """Verify a decision receipt without consuming any capability.

        Returns an allow compatibility only when the receipt itself records
        allow **and** integrity / root checks pass.  This method never
        dispatches and never marks a capability consumed.
        """

        try:
            expected_roots = None
            if (
                expected_policy_root
                or expected_corpus_roots is not None
                or expected_revocation_root is not None
            ):
                if not expected_policy_root:
                    raise AuthorizationAPIValidationError(
                        "expected_policy_root required when pinning roots"
                    )
                corpus = tuple(expected_corpus_roots or ())
                if not corpus:
                    raise AuthorizationAPIValidationError(
                        "expected_corpus_roots required when pinning roots"
                    )
                if expected_revocation_root is None:
                    raise AuthorizationAPIValidationError(
                        "expected_revocation_root required when pinning roots"
                    )
                expected_roots = BoundRoots(
                    policy_root=expected_policy_root,
                    corpus_roots=corpus,
                    revocation_root=expected_revocation_root,
                )

            verified = verify_decision_receipt(
                receipt,
                expected_roots=expected_roots,
                expected_audience=expected_audience or None,
                expected_actor=expected_actor or None,
                now=now,
            )

            # Verification success is not tool execution; map receipt outcome.
            return AuthorizationAPIResult(
                compatibility=verified.wire_status,
                status=verified.outcome,
                reasons=verified.reasons,
                reason_codes=verified.reason_codes,
                decision_ref=TypedDecisionRef(
                    ref_id=f"decision:{verified.decision_digest[:24]}",
                    digest=verified.decision_digest,
                    status=verified.outcome.value,
                    wire_status=verified.wire_status.value,
                ),
                receipt_ref=TypedReceiptRef.from_receipt(verified),
                decision_view=None,
                receipt_view=redacted_receipt_view(verified),
                context_view=redacted_context_view(verified.context),
                roots_view=redacted_roots_view(verified.roots),
                profile_id=verified.profile_id,
                executed=False,
                capability_issued=False,
                capability_consumed=False,
                producer_id=self.producer_id,
                diagnostics=("auth.api.receipt.verified",),
            )
        except (
            AuthorizationAPIValidationError,
            AuthorizationAPIError,
            ReceiptError,
            ReceiptVerificationError,
            ValueError,
            TypeError,
        ) as exc:
            return _fail_closed_api_result(
                reason=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
                status=InternalDecisionStatus.ERROR,
                producer_id=self.producer_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _fail_closed_api_result(
                reason=f"receipt verification failed: {type(exc).__name__}",
                error_type=type(exc).__name__,
                status=InternalDecisionStatus.ERROR,
                producer_id=self.producer_id,
            )


def evaluate_authorization_api(**kwargs: Any) -> AuthorizationAPIResult:
    """Module-level helper for :class:`IntentAuthorizationAPI`."""

    return IntentAuthorizationAPI().evaluate(**kwargs)


def verify_authorization_receipt_api(
    receipt: DecisionReceipt | Mapping[str, Any],
    **kwargs: Any,
) -> AuthorizationAPIResult:
    """Module-level helper to verify a receipt without capability consumption."""

    return IntentAuthorizationAPI().verify_receipt(receipt, **kwargs)


def api_capabilities() -> dict[str, Any]:
    """Describe the public API surface (no evaluation, no execution)."""

    return {
        "interface": INTENT_AUTHORIZATION_API_INTERFACE,
        "schema_version": INTENT_AUTHORIZATION_API_SCHEMA_VERSION,
        "compatibility_statuses": sorted(COMPATIBILITY_STATUSES),
        "required_fields": [
            "source",
            "actor",
            "audience",
            "tool",
            "arguments",
            "environment",
            "policy_root",
            "corpus_roots",
            "revocation_root",
        ],
        "returns": [
            "compatibility",
            "status",
            "decision_ref",
            "receipt_ref",
            "decision_view",
            "receipt_view",
        ],
        "executed": False,
        "issues_capability": False,
        "consumes_capability": False,
        "operations": ["evaluate", "verify_receipt", "api_capabilities"],
    }


__all__ = [
    "AUTHORIZATION_API_REQUEST_SCHEMA_VERSION",
    "AUTHORIZATION_API_RESULT_SCHEMA_VERSION",
    "COMPATIBILITY_STATUSES",
    "DEFAULT_API_PRODUCER_ID",
    "INTENT_AUTHORIZATION_API_INTERFACE",
    "INTENT_AUTHORIZATION_API_SCHEMA_VERSION",
    "REDACTED_VIEW_SCHEMA_VERSION",
    "TYPED_REF_SCHEMA_VERSION",
    "AuthorizationAPIBackendError",
    "AuthorizationAPIError",
    "AuthorizationAPIResult",
    "AuthorizationAPIValidationError",
    "IntentAuthorizationAPI",
    "TypedDecisionRef",
    "TypedReceiptRef",
    "api_capabilities",
    "build_invocation_envelope",
    "evaluate_authorization_api",
    "redact_value",
    "redacted_context_view",
    "redacted_decision_view",
    "redacted_receipt_view",
    "redacted_roots_view",
    "verify_authorization_receipt_api",
]
