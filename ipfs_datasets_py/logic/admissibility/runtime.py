"""Tenant-safe decision caching and authorization runtime glue (LIG-036).

Interfaces:

* ``DecisionCacheKey@1`` — domain-separated cache identity over the complete
  security-relevant invocation/context.  Keys never contain secrets, never
  cross tenant or audience boundaries, and bind actor/delegation, tool
  version, argument commitments, policy/corpus/revocation roots, environment,
  and evidence-coverage profile.
* ``TenantSafeDecisionCache@1`` — short positive-TTL allow cache with no unsafe
  reuse of negative/unknown results unless the profile explicitly proves
  monotonicity.

This leaf owns cache key construction, an in-memory reference cache, and a
thin runtime that may consult the cache before pre-dispatch enforcement.  It
does not mutate legacy family caches, connect to real tools, or edit the
authorization service/receipt codecs.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ..ir_core.claims import FrozenMap, stable_digest
from .compose import InternalDecisionStatus
from .enforcement import (
    CapabilityConsumptionStore,
    EnforcementResult,
    FakeDispatcher,
    InMemoryCapabilityConsumptionStore,
    InvocationBinding,
    PreInvocationEnforcement,
)
from .reasons import AdmissibilityStatus
from .receipt import (
    AuthorizationCapability,
    BoundContext,
    BoundRoots,
    DecisionReceipt,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

DECISION_CACHE_KEY_INTERFACE: Final = "DecisionCacheKey@1"
DECISION_CACHE_KEY_SCHEMA_VERSION: Final = "decision-cache-key/v1"
TENANT_SAFE_DECISION_CACHE_INTERFACE: Final = "TenantSafeDecisionCache@1"
TENANT_SAFE_DECISION_CACHE_SCHEMA_VERSION: Final = (
    "tenant-safe-decision-cache/v1"
)
AUTHORIZATION_RUNTIME_INTERFACE: Final = "AuthorizationRuntime@1"
AUTHORIZATION_RUNTIME_SCHEMA_VERSION: Final = "authorization-runtime/v1"
CACHED_DECISION_SCHEMA_VERSION: Final = "cached-decision/v1"

# Short positive TTL for allow decisions (seconds).  Positive and bounded.
DEFAULT_POSITIVE_TTL_SECONDS: Final = 30
DEFAULT_MAX_POSITIVE_TTL_SECONDS: Final = 120
# Negative/unknown entries are never cached by default (TTL = 0).
DEFAULT_NEGATIVE_TTL_SECONDS: Final = 0

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096
MAX_COLLECTION_ITEMS: Final = 1_024

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")

# Field names that must never enter a cache key payload (defense in depth).
_SECRET_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "private_key",
        "privatekey",
        "witness",
        "witness_data",
        "raw_arguments",
        "plaintext",
        "bearer",
        "session_secret",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DecisionCacheError(ValueError):
    """Raised when decision-cache construction or lookup fails closed."""


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
        raise DecisionCacheError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise DecisionCacheError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise DecisionCacheError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise DecisionCacheError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise DecisionCacheError(f"{name} is not a stable identifier")
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
        raise DecisionCacheError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
    return text


def _optional_digest(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _digest(value, name)


def _unique_sorted_ids(
    values: Any,
    name: str,
    *,
    require_identifier: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise DecisionCacheError(f"{name} must be a sequence of strings")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise DecisionCacheError(f"{name} exceeds maximum collection size")
    if require_identifier:
        items = tuple(_identifier(item, f"{name} item") for item in values)
    else:
        items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise DecisionCacheError(f"{name} must be unique")
    return tuple(sorted(items))


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DecisionCacheError(f"{name} must be an int")
    if value < minimum:
        raise DecisionCacheError(f"{name} must be >= {minimum}")
    return value


def _strip_secrets(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively drop secret-like keys from a mapping (defense in depth)."""

    clean: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if key_text.lower() in _SECRET_FIELD_NAMES:
            continue
        if isinstance(value, Mapping):
            clean[key_text] = _strip_secrets(value)
        else:
            clean[key_text] = value
    return clean


# ---------------------------------------------------------------------------
# DecisionCacheKey@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionCacheKey:
    """``DecisionCacheKey@1`` — complete security-relevant cache identity.

    Binds tenant, actor/delegation, audience, request/arguments digests, tool
    and version, effects, purpose, environment, effective time, policy, corpus
    roots, revocation root, circuit/VK roots, and evidence-coverage profile.

    **Never** includes secrets, raw arguments, witnesses, tokens, or nonces
    (nonces belong to one-time receipts/capabilities, not reusable cache
    identity).  Tenant isolation is structural: the key material always
    starts with the tenant domain separator.
    """

    tenant_id: str
    actor_id: str
    audience_id: str
    request_digest: str
    arguments_digest: str
    tool_id: str = ""
    tool_version: str = ""
    effect_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    delegation_ids: tuple[str, ...] = ()
    delegation_digest: str = ""
    environment_digest: str = ""
    environment_id: str = ""
    policy_root: str = ""
    corpus_roots: tuple[str, ...] = ()
    revocation_root: str = ""
    circuit_roots: tuple[str, ...] = ()
    vk_roots: tuple[str, ...] = ()
    profile_id: str = ""
    purpose: str = ""
    effective_time: str = ""
    evidence_coverage_profile: str = ""
    decision_policy_digest: str = ""
    interface: str = DECISION_CACHE_KEY_INTERFACE
    schema_version: str = DECISION_CACHE_KEY_SCHEMA_VERSION
    key_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        object.__setattr__(
            self, "actor_id", _identifier(self.actor_id, "actor_id")
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
            "arguments_digest",
            _digest(self.arguments_digest, "arguments_digest"),
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
            "resource_ids",
            _unique_sorted_ids(
                self.resource_ids, "resource_ids", require_identifier=True
            ),
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
            "environment_digest",
            _optional_digest(self.environment_digest, "environment_digest"),
        )
        object.__setattr__(
            self,
            "environment_id",
            _optional_identifier(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self, "policy_root", _optional_text(self.policy_root, "policy_root")
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
            self, "vk_roots", _unique_sorted_ids(self.vk_roots, "vk_roots")
        )
        object.__setattr__(
            self, "profile_id", _optional_text(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self, "purpose", _optional_text(self.purpose, "purpose")
        )
        object.__setattr__(
            self,
            "effective_time",
            _optional_text(self.effective_time, "effective_time"),
        )
        object.__setattr__(
            self,
            "evidence_coverage_profile",
            _optional_text(
                self.evidence_coverage_profile, "evidence_coverage_profile"
            ),
        )
        object.__setattr__(
            self,
            "decision_policy_digest",
            _optional_digest(
                self.decision_policy_digest, "decision_policy_digest"
            ),
        )
        if self.interface != DECISION_CACHE_KEY_INTERFACE:
            raise DecisionCacheError(
                f"unsupported decision cache key interface: {self.interface!r}"
            )
        if self.schema_version != DECISION_CACHE_KEY_SCHEMA_VERSION:
            raise DecisionCacheError(
                f"unsupported decision cache key schema: "
                f"{self.schema_version!r}"
            )
        digest = stable_digest(self._identity_payload())
        if self.key_digest:
            provided = self.key_digest
            if provided.startswith("sha256:"):
                provided = provided[len("sha256:") :]
            if provided != digest:
                raise DecisionCacheError(
                    "key_digest does not match recomputed cache key identity"
                )
        object.__setattr__(self, "key_digest", digest)

    def _identity_payload(self) -> dict[str, Any]:
        # Domain separator first: tenant can never be omitted from identity.
        return {
            "actor_id": self.actor_id,
            "arguments_digest": self.arguments_digest,
            "audience_id": self.audience_id,
            "circuit_roots": list(self.circuit_roots),
            "corpus_roots": list(self.corpus_roots),
            "decision_policy_digest": self.decision_policy_digest,
            "delegation_digest": self.delegation_digest,
            "delegation_ids": list(self.delegation_ids),
            "domain": "lig.decision-cache.v1",
            "effect_ids": list(self.effect_ids),
            "effective_time": self.effective_time,
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "evidence_coverage_profile": self.evidence_coverage_profile,
            "interface": self.interface,
            "policy_root": self.policy_root,
            "profile_id": self.profile_id,
            "purpose": self.purpose,
            "request_digest": self.request_digest,
            "resource_ids": list(self.resource_ids),
            "revocation_root": self.revocation_root,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "vk_roots": list(self.vk_roots),
        }

    @property
    def digest(self) -> str:
        return self.key_digest

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["key_digest"] = self.key_digest
        # Defense in depth: never serialize secrets even if smuggled later.
        return _strip_secrets(payload)

    def with_mutation(self, **overrides: Any) -> "DecisionCacheKey":
        """Return a new key with selected fields overridden (tests / probes)."""

        data = {
            "tenant_id": self.tenant_id,
            "actor_id": self.actor_id,
            "audience_id": self.audience_id,
            "request_digest": self.request_digest,
            "arguments_digest": self.arguments_digest,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "effect_ids": self.effect_ids,
            "resource_ids": self.resource_ids,
            "delegation_ids": self.delegation_ids,
            "delegation_digest": self.delegation_digest,
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "policy_root": self.policy_root,
            "corpus_roots": self.corpus_roots,
            "revocation_root": self.revocation_root,
            "circuit_roots": self.circuit_roots,
            "vk_roots": self.vk_roots,
            "profile_id": self.profile_id,
            "purpose": self.purpose,
            "effective_time": self.effective_time,
            "evidence_coverage_profile": self.evidence_coverage_profile,
            "decision_policy_digest": self.decision_policy_digest,
        }
        data.update(overrides)
        return DecisionCacheKey(**data)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionCacheKey":
        if not isinstance(value, Mapping):
            raise DecisionCacheError("decision cache key must be a mapping")
        clean = _strip_secrets(dict(value))
        return cls(
            tenant_id=clean.get("tenant_id", ""),
            actor_id=clean.get("actor_id", ""),
            audience_id=clean.get("audience_id", ""),
            request_digest=clean.get("request_digest", ""),
            arguments_digest=clean.get("arguments_digest", ""),
            tool_id=clean.get("tool_id", ""),
            tool_version=clean.get("tool_version", ""),
            effect_ids=tuple(clean.get("effect_ids", ())),
            resource_ids=tuple(clean.get("resource_ids", ())),
            delegation_ids=tuple(clean.get("delegation_ids", ())),
            delegation_digest=clean.get("delegation_digest", ""),
            environment_digest=clean.get("environment_digest", ""),
            environment_id=clean.get("environment_id", ""),
            policy_root=clean.get("policy_root", ""),
            corpus_roots=tuple(clean.get("corpus_roots", ())),
            revocation_root=clean.get("revocation_root", ""),
            circuit_roots=tuple(clean.get("circuit_roots", ())),
            vk_roots=tuple(clean.get("vk_roots", ())),
            profile_id=clean.get("profile_id", ""),
            purpose=clean.get("purpose", ""),
            effective_time=clean.get("effective_time", ""),
            evidence_coverage_profile=clean.get(
                "evidence_coverage_profile", ""
            ),
            decision_policy_digest=clean.get("decision_policy_digest", ""),
            interface=clean.get("interface", DECISION_CACHE_KEY_INTERFACE),
            schema_version=clean.get(
                "schema_version", DECISION_CACHE_KEY_SCHEMA_VERSION
            ),
            key_digest=clean.get("key_digest", ""),
        )


def build_decision_cache_key(
    *,
    tenant_id: str = "",
    actor_id: str = "",
    audience_id: str = "",
    request_digest: str = "",
    arguments_digest: str = "",
    tool_id: str = "",
    tool_version: str = "",
    effect_ids: Sequence[str] = (),
    resource_ids: Sequence[str] = (),
    delegation_ids: Sequence[str] = (),
    delegation_digest: str = "",
    environment_digest: str = "",
    environment_id: str = "",
    roots: BoundRoots | Mapping[str, Any] | None = None,
    policy_root: str = "",
    corpus_roots: Sequence[str] = (),
    revocation_root: str = "",
    circuit_roots: Sequence[str] = (),
    vk_roots: Sequence[str] = (),
    profile_id: str = "",
    purpose: str = "",
    effective_time: str = "",
    evidence_coverage_profile: str = "",
    decision_policy_digest: str = "",
    context: BoundContext | Mapping[str, Any] | None = None,
    receipt: DecisionReceipt | None = None,
) -> DecisionCacheKey:
    """Construct a :class:`DecisionCacheKey` from explicit fields or a receipt.

    When *receipt* is supplied, context and roots default from it.  Explicit
    keyword arguments override receipt projections.  Secret-bearing fields are
    never accepted into the key.
    """

    if receipt is not None:
        if not isinstance(receipt, DecisionReceipt):
            raise DecisionCacheError("receipt must be a DecisionReceipt")
        ctx = receipt.context
        r = receipt.roots
        actor_id = actor_id or ctx.actor_id
        audience_id = audience_id or ctx.audience_id
        request_digest = request_digest or ctx.request_digest
        arguments_digest = arguments_digest or ctx.arguments_digest
        tool_id = tool_id or ctx.tool_id
        tool_version = tool_version or ctx.tool_version
        effect_ids = effect_ids or ctx.effect_ids
        resource_ids = resource_ids or ctx.resource_ids
        delegation_ids = delegation_ids or ctx.delegation_ids
        delegation_digest = delegation_digest or ctx.delegation_digest
        environment_digest = environment_digest or ctx.environment_digest
        environment_id = environment_id or ctx.environment_id
        policy_root = policy_root or r.policy_root
        corpus_roots = corpus_roots or r.corpus_roots
        revocation_root = revocation_root or r.revocation_root
        circuit_roots = circuit_roots or r.circuit_roots
        vk_roots = vk_roots or r.vk_roots
        profile_id = profile_id or receipt.profile_id
        if not tenant_id:
            meta = ctx.metadata.to_dict() if ctx.metadata else {}
            tenant_id = str(meta.get("tenant_id", "") or "")
        if not decision_policy_digest:
            decision_policy_digest = receipt.policy_digest

    if context is not None:
        if isinstance(context, Mapping):
            context = BoundContext.from_dict(context)
        if not isinstance(context, BoundContext):
            raise DecisionCacheError("context must be a BoundContext or mapping")
        actor_id = actor_id or context.actor_id
        audience_id = audience_id or context.audience_id
        request_digest = request_digest or context.request_digest
        arguments_digest = arguments_digest or context.arguments_digest
        tool_id = tool_id or context.tool_id
        tool_version = tool_version or context.tool_version
        effect_ids = effect_ids or context.effect_ids
        resource_ids = resource_ids or context.resource_ids
        delegation_ids = delegation_ids or context.delegation_ids
        delegation_digest = delegation_digest or context.delegation_digest
        environment_digest = environment_digest or context.environment_digest
        environment_id = environment_id or context.environment_id

    if roots is not None:
        if isinstance(roots, Mapping):
            roots = BoundRoots.from_dict(roots)
        if not isinstance(roots, BoundRoots):
            raise DecisionCacheError("roots must be BoundRoots or mapping")
        policy_root = policy_root or roots.policy_root
        corpus_roots = corpus_roots or roots.corpus_roots
        revocation_root = revocation_root or roots.revocation_root
        circuit_roots = circuit_roots or roots.circuit_roots
        vk_roots = vk_roots or roots.vk_roots

    return DecisionCacheKey(
        tenant_id=tenant_id,
        actor_id=actor_id,
        audience_id=audience_id,
        request_digest=request_digest,
        arguments_digest=arguments_digest,
        tool_id=tool_id,
        tool_version=tool_version,
        effect_ids=tuple(effect_ids),
        resource_ids=tuple(resource_ids),
        delegation_ids=tuple(delegation_ids),
        delegation_digest=delegation_digest,
        environment_digest=environment_digest,
        environment_id=environment_id,
        policy_root=policy_root,
        corpus_roots=tuple(corpus_roots),
        revocation_root=revocation_root,
        circuit_roots=tuple(circuit_roots),
        vk_roots=tuple(vk_roots),
        profile_id=profile_id,
        purpose=purpose,
        effective_time=effective_time,
        evidence_coverage_profile=evidence_coverage_profile,
        decision_policy_digest=decision_policy_digest,
    )


# ---------------------------------------------------------------------------
# Cached decision entry + tenant-safe cache
# ---------------------------------------------------------------------------


class CacheEntryKind(str, Enum):
    """Kind of cached authorization outcome."""

    ALLOW = "allow"
    NEGATIVE = "negative"  # deny / reject
    UNKNOWN = "unknown"  # review / indeterminate / abstain / error


def _kind_for_status(
    status: InternalDecisionStatus | AdmissibilityStatus | str,
) -> CacheEntryKind:
    if isinstance(status, InternalDecisionStatus):
        if status is InternalDecisionStatus.ALLOW:
            return CacheEntryKind.ALLOW
        if status is InternalDecisionStatus.DENY:
            return CacheEntryKind.NEGATIVE
        return CacheEntryKind.UNKNOWN
    if isinstance(status, AdmissibilityStatus):
        if status is AdmissibilityStatus.ALLOW:
            return CacheEntryKind.ALLOW
        if status is AdmissibilityStatus.REJECT:
            return CacheEntryKind.NEGATIVE
        return CacheEntryKind.UNKNOWN
    text = str(status).lower()
    if text == "allow":
        return CacheEntryKind.ALLOW
    if text in {"deny", "reject"}:
        return CacheEntryKind.NEGATIVE
    return CacheEntryKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class CachedDecision:
    """Value stored under a :class:`DecisionCacheKey`."""

    kind: CacheEntryKind
    status: str
    wire_status: str
    decision_digest: str = ""
    receipt_digest: str = ""
    reason_codes: tuple[str, ...] = ()
    stored_at_monotonic: float = 0.0
    expires_at_monotonic: float = 0.0
    ttl_seconds: int = 0
    monotonic_negative: bool = False
    tenant_id: str = ""
    key_digest: str = ""
    schema_version: str = CACHED_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = self.kind
        if not isinstance(kind, CacheEntryKind):
            kind = CacheEntryKind(kind)
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.ttl_seconds, int) or self.ttl_seconds < 0:
            raise DecisionCacheError("ttl_seconds must be a non-negative int")
        if self.ttl_seconds == 0 and self.kind is CacheEntryKind.ALLOW:
            raise DecisionCacheError(
                "allow entries require a short positive TTL"
            )

    @property
    def is_allow(self) -> bool:
        return self.kind is CacheEntryKind.ALLOW

    def is_expired(self, now_monotonic: float | None = None) -> bool:
        if self.ttl_seconds <= 0:
            return True
        now = (
            time.monotonic() if now_monotonic is None else float(now_monotonic)
        )
        return now >= self.expires_at_monotonic

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_digest": self.decision_digest,
            "expires_at_monotonic": self.expires_at_monotonic,
            "key_digest": self.key_digest,
            "kind": self.kind.value,
            "monotonic_negative": self.monotonic_negative,
            "reason_codes": list(self.reason_codes),
            "receipt_digest": self.receipt_digest,
            "schema_version": self.schema_version,
            "status": self.status,
            "stored_at_monotonic": self.stored_at_monotonic,
            "tenant_id": self.tenant_id,
            "ttl_seconds": self.ttl_seconds,
            "wire_status": self.wire_status,
        }


@dataclass
class TenantSafeDecisionCache:
    """``TenantSafeDecisionCache@1`` — tenant-isolated decision cache.

    Rules:

    * **Allow** entries use a short positive TTL (default 30s, max 120s).
    * **Negative / unknown** entries are **not** stored unless
      ``monotonic_negative=True`` is explicitly proved by the caller profile.
    * Keys are domain-separated by tenant; lookup never crosses tenants.
    * Secret fields never enter keys or values.
    * Expired entries are treated as misses (no negative caching of expiry).
    """

    positive_ttl_seconds: int = DEFAULT_POSITIVE_TTL_SECONDS
    max_positive_ttl_seconds: int = DEFAULT_MAX_POSITIVE_TTL_SECONDS
    negative_ttl_seconds: int = DEFAULT_NEGATIVE_TTL_SECONDS
    interface: str = TENANT_SAFE_DECISION_CACHE_INTERFACE
    schema_version: str = TENANT_SAFE_DECISION_CACHE_SCHEMA_VERSION
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    # Storage: tenant_id → key_digest → CachedDecision
    _entries: dict[str, dict[str, CachedDecision]] = field(
        default_factory=dict, init=False
    )
    _hits: int = field(default=0, init=False)
    _misses: int = field(default=0, init=False)
    _stores: int = field(default=0, init=False)
    _rejected_stores: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.positive_ttl_seconds = _positive_int(
            self.positive_ttl_seconds, "positive_ttl_seconds", minimum=1
        )
        self.max_positive_ttl_seconds = _positive_int(
            self.max_positive_ttl_seconds,
            "max_positive_ttl_seconds",
            minimum=1,
        )
        if self.positive_ttl_seconds > self.max_positive_ttl_seconds:
            raise DecisionCacheError(
                "positive_ttl_seconds must not exceed max_positive_ttl_seconds"
            )
        if not isinstance(self.negative_ttl_seconds, int) or isinstance(
            self.negative_ttl_seconds, bool
        ):
            raise DecisionCacheError("negative_ttl_seconds must be an int")
        if self.negative_ttl_seconds < 0:
            raise DecisionCacheError(
                "negative_ttl_seconds must be non-negative"
            )
        if self.interface != TENANT_SAFE_DECISION_CACHE_INTERFACE:
            raise DecisionCacheError(
                f"unsupported cache interface: {self.interface!r}"
            )
        if self.schema_version != TENANT_SAFE_DECISION_CACHE_SCHEMA_VERSION:
            raise DecisionCacheError(
                f"unsupported cache schema: {self.schema_version!r}"
            )

    def get(
        self,
        key: DecisionCacheKey,
        *,
        now_monotonic: float | None = None,
    ) -> CachedDecision | None:
        """Return a non-expired entry for *key*, or None (miss)."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("key must be a DecisionCacheKey")
        now = (
            time.monotonic() if now_monotonic is None else float(now_monotonic)
        )
        tenant = key.tenant_id
        digest = key.digest
        with self._lock:
            bucket = self._entries.get(tenant)
            if not bucket:
                self._misses += 1
                return None
            entry = bucket.get(digest)
            if entry is None:
                self._misses += 1
                return None
            # Tenant binding double-check (should be structural via bucket).
            if entry.tenant_id and entry.tenant_id != tenant:
                self._misses += 1
                return None
            if entry.is_expired(now):
                # Drop expired entry; do not treat as negative cache.
                del bucket[digest]
                self._misses += 1
                return None
            self._hits += 1
            return entry

    def put(
        self,
        key: DecisionCacheKey,
        *,
        status: InternalDecisionStatus | AdmissibilityStatus | str,
        wire_status: AdmissibilityStatus | str | None = None,
        decision_digest: str = "",
        receipt_digest: str = "",
        reason_codes: Sequence[str] = (),
        monotonic_negative: bool = False,
        ttl_seconds: int | None = None,
        now_monotonic: float | None = None,
    ) -> CachedDecision | None:
        """Store a decision under *key* if the reuse policy permits.

        Returns the stored entry, or ``None`` when the store was rejected
        (e.g. negative/unknown without proved monotonicity, or non-positive
        TTL for allows).
        """

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("key must be a DecisionCacheKey")

        kind = _kind_for_status(status)
        if isinstance(status, Enum):
            status_text = status.value
        else:
            status_text = str(status)

        if wire_status is None:
            if kind is CacheEntryKind.ALLOW:
                wire_text = AdmissibilityStatus.ALLOW.value
            elif kind is CacheEntryKind.NEGATIVE:
                wire_text = AdmissibilityStatus.REJECT.value
            else:
                wire_text = AdmissibilityStatus.ABSTAIN.value
        elif isinstance(wire_status, Enum):
            wire_text = wire_status.value
        else:
            wire_text = str(wire_status)

        now = (
            time.monotonic() if now_monotonic is None else float(now_monotonic)
        )

        if kind is CacheEntryKind.ALLOW:
            ttl = (
                self.positive_ttl_seconds
                if ttl_seconds is None
                else int(ttl_seconds)
            )
            if ttl <= 0:
                with self._lock:
                    self._rejected_stores += 1
                return None
            if ttl > self.max_positive_ttl_seconds:
                ttl = self.max_positive_ttl_seconds
        else:
            # Negative / unknown: only with proved monotonicity + positive TTL.
            if not monotonic_negative:
                with self._lock:
                    self._rejected_stores += 1
                return None
            ttl = (
                self.negative_ttl_seconds
                if ttl_seconds is None
                else int(ttl_seconds)
            )
            if ttl <= 0:
                with self._lock:
                    self._rejected_stores += 1
                return None
            if ttl > self.max_positive_ttl_seconds:
                ttl = self.max_positive_ttl_seconds

        entry = CachedDecision(
            kind=kind,
            status=status_text,
            wire_status=wire_text,
            decision_digest=_optional_digest(
                decision_digest, "decision_digest"
            )
            if decision_digest
            else "",
            receipt_digest=_optional_digest(receipt_digest, "receipt_digest")
            if receipt_digest
            else "",
            reason_codes=tuple(str(c) for c in reason_codes),
            stored_at_monotonic=now,
            expires_at_monotonic=now + float(ttl),
            ttl_seconds=ttl,
            monotonic_negative=bool(monotonic_negative)
            and kind is not CacheEntryKind.ALLOW,
            tenant_id=key.tenant_id,
            key_digest=key.digest,
        )

        with self._lock:
            bucket = self._entries.setdefault(key.tenant_id, {})
            bucket[key.digest] = entry
            self._stores += 1
            return entry

    def put_from_receipt(
        self,
        key: DecisionCacheKey,
        receipt: DecisionReceipt,
        *,
        monotonic_negative: bool = False,
        ttl_seconds: int | None = None,
        now_monotonic: float | None = None,
    ) -> CachedDecision | None:
        """Store a cache entry projected from a decision receipt."""

        if not isinstance(receipt, DecisionReceipt):
            raise DecisionCacheError("receipt must be a DecisionReceipt")
        return self.put(
            key,
            status=receipt.outcome,
            wire_status=receipt.wire_status,
            decision_digest=receipt.decision_digest,
            receipt_digest=receipt.digest,
            reason_codes=receipt.reason_codes,
            monotonic_negative=monotonic_negative,
            ttl_seconds=ttl_seconds,
            now_monotonic=now_monotonic,
        )

    def invalidate(
        self,
        key: DecisionCacheKey,
    ) -> bool:
        """Remove a single entry.  Returns True if something was removed."""

        if not isinstance(key, DecisionCacheKey):
            raise DecisionCacheError("key must be a DecisionCacheKey")
        with self._lock:
            bucket = self._entries.get(key.tenant_id)
            if not bucket:
                return False
            return bucket.pop(key.digest, None) is not None

    def invalidate_tenant(self, tenant_id: str) -> int:
        """Drop all entries for a tenant.  Returns the number removed."""

        tenant = _identifier(tenant_id, "tenant_id")
        with self._lock:
            bucket = self._entries.pop(tenant, None)
            return 0 if bucket is None else len(bucket)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._stores = 0
            self._rejected_stores = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            size = sum(len(b) for b in self._entries.values())
            return {
                "hits": self._hits,
                "misses": self._misses,
                "stores": self._stores,
                "rejected_stores": self._rejected_stores,
                "size": size,
                "tenants": len(self._entries),
            }

    def size(self) -> int:
        with self._lock:
            return sum(len(b) for b in self._entries.values())


# ---------------------------------------------------------------------------
# Authorization runtime (cache + enforcement glue)
# ---------------------------------------------------------------------------


@dataclass
class AuthorizationRuntime:
    """Thin runtime combining tenant-safe cache with pre-dispatch enforcement.

    Evaluation results may be cached under a complete :class:`DecisionCacheKey`.
    Dispatch still always revalidates and consumes through
    :class:`PreInvocationEnforcement` — a cache hit never bypasses the
    pre-dispatch boundary.
    """

    cache: TenantSafeDecisionCache = field(
        default_factory=TenantSafeDecisionCache
    )
    store: CapabilityConsumptionStore = field(
        default_factory=InMemoryCapabilityConsumptionStore
    )
    dispatcher: FakeDispatcher | None = field(default_factory=FakeDispatcher)
    enforcement: PreInvocationEnforcement | None = None
    interface: str = AUTHORIZATION_RUNTIME_INTERFACE
    schema_version: str = AUTHORIZATION_RUNTIME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.enforcement is None:
            self.enforcement = PreInvocationEnforcement(
                store=self.store,
                dispatcher=self.dispatcher,
            )
        if self.interface != AUTHORIZATION_RUNTIME_INTERFACE:
            raise DecisionCacheError(
                f"unsupported runtime interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_RUNTIME_SCHEMA_VERSION:
            raise DecisionCacheError(
                f"unsupported runtime schema: {self.schema_version!r}"
            )

    def cache_decision(
        self,
        key: DecisionCacheKey,
        receipt: DecisionReceipt,
        *,
        monotonic_negative: bool = False,
        ttl_seconds: int | None = None,
    ) -> CachedDecision | None:
        """Store *receipt* under *key* subject to reuse policy."""

        return self.cache.put_from_receipt(
            key,
            receipt,
            monotonic_negative=monotonic_negative,
            ttl_seconds=ttl_seconds,
        )

    def lookup_decision(
        self,
        key: DecisionCacheKey,
        *,
        now_monotonic: float | None = None,
    ) -> CachedDecision | None:
        """Lookup a cached decision; never crosses tenant/context."""

        return self.cache.get(key, now_monotonic=now_monotonic)

    def enforce_and_dispatch(
        self,
        *,
        receipt: DecisionReceipt | Mapping[str, Any] | None,
        capability: AuthorizationCapability | Mapping[str, Any] | None,
        binding: InvocationBinding | Mapping[str, Any],
        live_roots: BoundRoots | Mapping[str, Any] | None = None,
        live_environment: Mapping[str, Any] | None = None,
        now: str | None = None,
        dispatch_payload: Mapping[str, Any] | None = None,
        cache_key: DecisionCacheKey | None = None,
    ) -> EnforcementResult:
        """Pre-dispatch enforcement; optional cache consult is observational.

        A cache hit does **not** skip revalidation or atomic consumption.
        """

        assert self.enforcement is not None
        if cache_key is not None:
            # Observational lookup only — still enforce fully below.
            _ = self.cache.get(cache_key)
        return self.enforcement.enforce_and_dispatch(
            receipt=receipt,
            capability=capability,
            binding=binding,
            live_roots=live_roots,
            live_environment=live_environment,
            now=now,
            dispatch_payload=dispatch_payload,
        )


__all__ = [
    "AUTHORIZATION_RUNTIME_INTERFACE",
    "AUTHORIZATION_RUNTIME_SCHEMA_VERSION",
    "CACHED_DECISION_SCHEMA_VERSION",
    "DEFAULT_MAX_POSITIVE_TTL_SECONDS",
    "DEFAULT_NEGATIVE_TTL_SECONDS",
    "DEFAULT_POSITIVE_TTL_SECONDS",
    "DECISION_CACHE_KEY_INTERFACE",
    "DECISION_CACHE_KEY_SCHEMA_VERSION",
    "TENANT_SAFE_DECISION_CACHE_INTERFACE",
    "TENANT_SAFE_DECISION_CACHE_SCHEMA_VERSION",
    "AuthorizationRuntime",
    "CacheEntryKind",
    "CachedDecision",
    "DecisionCacheError",
    "DecisionCacheKey",
    "TenantSafeDecisionCache",
    "build_decision_cache_key",
]
