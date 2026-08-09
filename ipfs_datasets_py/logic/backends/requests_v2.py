"""Typed LogicObligation and BackendRequest successor contracts (Wave-2).

Interfaces (LFP2-007):

* ``LogicObligation@2`` — obligation bound to typed family, profile, property,
  view, notation, encoding, expression, feature, evidence, and finite bounds
* ``BackendRequest@2`` — provider-selection input that replaces free-form
  family/payload routing with the same typed fields

Admission is fail-closed **before** provider selection:

* cross-namespace identity misuse
* arbitrary / free-form routing payloads
* unsupported extensions
* missing resource bounds
* authority overclaims relative to evidence kind

Legacy ``BackendRequest`` (``proof-backend-request/v1``) remains dual-readable
through :meth:`BackendRequestV2.from_legacy`.  New writes use v2 only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
    family_id,
    provider_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DomainLogicSliceV2,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BACKEND_REQUEST_SCHEMA_VERSION as LEGACY_BACKEND_REQUEST_SCHEMA_VERSION,
    BackendRequest as LegacyBackendRequest,
    ExecutionBounds as LegacyExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
    require_namespace_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_OBLIGATION_V2_INTERFACE: Final = "LogicObligation@2"
BACKEND_REQUEST_V2_INTERFACE: Final = "BackendRequest@2"

LOGIC_OBLIGATION_V2_SCHEMA_VERSION: Final = "logic-obligation/v2"
BACKEND_REQUEST_V2_SCHEMA_VERSION: Final = "backend-request/v2"
REQUEST_BOUNDS_SCHEMA_VERSION: Final = "backend-request-bounds/v2"
REQUESTS_V2_MODULE_VERSION: Final = "1.0.0"

LEGACY_BACKEND_REQUEST_INTERFACE: Final = "BackendRequest@1"
LEGACY_BACKEND_REQUEST_SCHEMA_VERSION: Final = LEGACY_BACKEND_REQUEST_SCHEMA_VERSION

_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")

# Hard ceilings (callers may only tighten).
MAX_TIMEOUT_MS: Final = 3_600_000
MAX_STEPS: Final = 100_000_000
MAX_MEMORY_BYTES: Final = 16 * 1024 * 1024 * 1024
MAX_OUTPUT_BYTES: Final = 256 * 1024 * 1024
MAX_STATEMENT_CHARS: Final = 16_384

# Metadata keys that re-introduce free-form family/payload routing.
_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "payload",
        "raw_formula",
        "raw_source",
        "target_source",
        "logic_family",
        "family_string",
        "opaque_extension",
        "arbitrary_payload",
        "free_form_family",
    }
)

# Evidence kinds that may never support kernel authority.
_NON_KERNEL_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "parse",
        "model",
        "trace",
        "attack",
        "monitor",
        "candidate",
        "advisory",
    }
)

# Evidence kinds that may never support theorem-proof authority.
_NON_THEOREM_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        "parse",
        "model",
        "trace",
        "attack",
        "monitor",
        "candidate",
        "advisory",
        "core",
    }
)


class RequestV2Error(SyntaxContractError):
    """Raised when a LogicObligation@2 or BackendRequest@2 is malformed."""


class RequestAdmissionError(RequestV2Error):
    """Raised when a request fails closed before provider selection."""


class CrossNamespaceRequestError(RequestAdmissionError):
    """Raised when an identity is used in the wrong namespace role."""


class ArbitraryPayloadError(RequestAdmissionError):
    """Raised when free-form payload routing is attempted."""


class UnsupportedExtensionRequestError(RequestAdmissionError):
    """Raised when unsupported extensions would reach a backend request."""


class MissingBoundsError(RequestAdmissionError):
    """Raised when finite resource bounds are absent or incomplete."""


class AuthorityOverclaimError(RequestAdmissionError):
    """Raised when authority ceiling exceeds evidence kind support."""


class RequestAuthorityCeiling(str, Enum):
    """Closed authority ceilings a request may claim (cannot self-upgrade).

    Ordered from weakest to strongest for overclaim checks.  A request may
    never claim a stronger ceiling than its evidence kind supports.
    """

    NONE = "none"
    ADVISORY = "advisory"
    CANDIDATE = "candidate"
    BOUNDED = "bounded"
    FINITE_TRACE = "finite_trace"
    AUTHORIZATION = "authorization"
    SATISFIABILITY = "satisfiability"
    PROTOCOL = "protocol"
    RECONSTRUCTION = "reconstruction"
    KERNEL = "kernel"
    ATTESTATION = "attestation"


_AUTHORITY_RANK: Final[dict[RequestAuthorityCeiling, int]] = {
    RequestAuthorityCeiling.NONE: 0,
    RequestAuthorityCeiling.ADVISORY: 1,
    RequestAuthorityCeiling.CANDIDATE: 2,
    RequestAuthorityCeiling.BOUNDED: 3,
    RequestAuthorityCeiling.FINITE_TRACE: 4,
    RequestAuthorityCeiling.AUTHORIZATION: 5,
    RequestAuthorityCeiling.SATISFIABILITY: 6,
    RequestAuthorityCeiling.PROTOCOL: 7,
    RequestAuthorityCeiling.RECONSTRUCTION: 8,
    RequestAuthorityCeiling.KERNEL: 9,
    RequestAuthorityCeiling.ATTESTATION: 10,
}

# Maximum authority ceiling each evidence kind may claim.
_EVIDENCE_AUTHORITY_CEILING: Final[dict[str, RequestAuthorityCeiling]] = {
    "parse": RequestAuthorityCeiling.NONE,
    "advisory": RequestAuthorityCeiling.ADVISORY,
    "candidate": RequestAuthorityCeiling.CANDIDATE,
    "model": RequestAuthorityCeiling.SATISFIABILITY,
    "core": RequestAuthorityCeiling.SATISFIABILITY,
    "trace": RequestAuthorityCeiling.FINITE_TRACE,
    "monitor": RequestAuthorityCeiling.FINITE_TRACE,
    "attack": RequestAuthorityCeiling.PROTOCOL,
    "proof": RequestAuthorityCeiling.RECONSTRUCTION,
    "kernel": RequestAuthorityCeiling.KERNEL,
    "kernel_receipt": RequestAuthorityCeiling.KERNEL,
    "attestation": RequestAuthorityCeiling.ATTESTATION,
    "authorization": RequestAuthorityCeiling.AUTHORIZATION,
    "bounded": RequestAuthorityCeiling.BOUNDED,
}


def _status_value(status: object) -> str:
    if isinstance(status, Enum):
        return status.value
    return str(status)


def _identity_dict(identity: LogicIdentity) -> dict[str, str]:
    return identity.to_dict()


def _coerce_identity(
    value: object,
    expected: NamespaceKind,
    field_name: str,
) -> LogicIdentity:
    try:
        return require_namespace_identity(value, expected, field_name)
    except SyntaxContractError as error:
        message = str(error)
        if "requires namespace" in message or "CrossNamespace" in type(error).__name__:
            raise CrossNamespaceRequestError(message) from error
        raise RequestV2Error(message) from error


def _feature_tuple(value: object, field_name: str) -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=128)
        for item in _require_sequence(value, field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise RequestV2Error(f"{field_name} exceeds hard ceiling")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not _FEATURE_RE.fullmatch(item):
            raise RequestV2Error(
                f"{field_name} item must be a feature identity; got {item!r}"
            )
        if item in seen:
            raise RequestV2Error(f"{field_name} values must be unique")
        seen.add(item)
        ordered.append(item)
    return tuple(sorted(ordered))


def _forbid_metadata_routing(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS:
            raise ArbitraryPayloadError(
                f"{field_name} rejects free-form routing key {key!r}; "
                "BackendRequest@2 uses typed family/profile/property/view/"
                "notation/encoding/evidence fields only"
            )


def _positive_bound(
    value: object,
    field_name: str,
    *,
    maximum: int,
) -> int:
    if value is None:
        raise MissingBoundsError(f"{field_name} is required; bounds must be finite")
    if isinstance(value, bool) or not isinstance(value, int):
        raise MissingBoundsError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise MissingBoundsError(
            f"{field_name} must be a positive finite bound; unbounded or "
            f"non-positive values are rejected"
        )
    if value > maximum:
        raise RequestV2Error(f"{field_name} exceeds hard ceiling {maximum}")
    return value


def _coerce_authority(
    value: object, field_name: str = "authority_ceiling"
) -> RequestAuthorityCeiling:
    if isinstance(value, RequestAuthorityCeiling):
        return value
    text = _text(value, field_name, maximum=64)
    try:
        return RequestAuthorityCeiling(text)
    except ValueError as error:
        allowed = ", ".join(item.value for item in RequestAuthorityCeiling)
        raise RequestV2Error(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _check_authority_overclaim(
    ceiling: RequestAuthorityCeiling,
    evidence: LogicIdentity,
    *,
    field_name: str = "authority_ceiling",
) -> None:
    evidence_value = evidence.value
    max_ceiling = _EVIDENCE_AUTHORITY_CEILING.get(evidence_value)
    if max_ceiling is None:
        # Unknown evidence kinds are limited to advisory until registered.
        max_ceiling = RequestAuthorityCeiling.ADVISORY
    if _AUTHORITY_RANK[ceiling] > _AUTHORITY_RANK[max_ceiling]:
        raise AuthorityOverclaimError(
            f"{field_name} {ceiling.value!r} overclaims evidence kind "
            f"{evidence.qualified!r} (max admitted ceiling "
            f"{max_ceiling.value!r}); fail closed before provider selection"
        )
    if (
        ceiling is RequestAuthorityCeiling.KERNEL
        and evidence_value in _NON_KERNEL_EVIDENCE
    ):
        raise AuthorityOverclaimError(
            f"kernel authority cannot be claimed with evidence "
            f"{evidence.qualified!r}"
        )
    if evidence_value in _NON_THEOREM_EVIDENCE and ceiling in {
        RequestAuthorityCeiling.KERNEL,
        RequestAuthorityCeiling.RECONSTRUCTION,
    }:
        raise AuthorityOverclaimError(
            f"proof/reconstruction authority cannot be claimed with evidence "
            f"{evidence.qualified!r}"
        )


# ---------------------------------------------------------------------------
# RequestBounds
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestBounds:
    """Finite resource limits required on every LogicObligation@2 / request.

    All four fields are mandatory positive integers.  Missing, zero, negative,
    or non-integer bounds fail closed before provider selection.
    """

    timeout_ms: int
    max_steps: int
    max_memory_bytes: int
    max_output_bytes: int
    schema_version: str = REQUEST_BOUNDS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timeout_ms",
            _positive_bound(self.timeout_ms, "timeout_ms", maximum=MAX_TIMEOUT_MS),
        )
        object.__setattr__(
            self,
            "max_steps",
            _positive_bound(self.max_steps, "max_steps", maximum=MAX_STEPS),
        )
        object.__setattr__(
            self,
            "max_memory_bytes",
            _positive_bound(
                self.max_memory_bytes, "max_memory_bytes", maximum=MAX_MEMORY_BYTES
            ),
        )
        object.__setattr__(
            self,
            "max_output_bytes",
            _positive_bound(
                self.max_output_bytes, "max_output_bytes", maximum=MAX_OUTPUT_BYTES
            ),
        )
        if self.schema_version != REQUEST_BOUNDS_SCHEMA_VERSION:
            raise RequestV2Error(
                f"unsupported RequestBounds schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_memory_bytes": self.max_memory_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_steps": self.max_steps,
            "schema_version": self.schema_version,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RequestBounds":
        if value is None:
            raise MissingBoundsError(
                "bounds are required; BackendRequest@2 rejects missing bounds"
            )
        payload = _require_mapping(value, "bounds")
        required = (
            "timeout_ms",
            "max_steps",
            "max_memory_bytes",
            "max_output_bytes",
        )
        missing = [name for name in required if name not in payload]
        if missing:
            raise MissingBoundsError(
                f"bounds missing required field(s): {', '.join(missing)}"
            )
        unknown = sorted(set(payload) - set(required) - {"schema_version"})
        if unknown:
            raise RequestV2Error(
                f"unknown bounds field(s): {', '.join(unknown)}"
            )
        return cls(
            timeout_ms=payload["timeout_ms"],
            max_steps=payload["max_steps"],
            max_memory_bytes=payload["max_memory_bytes"],
            max_output_bytes=payload["max_output_bytes"],
            schema_version=str(
                payload.get("schema_version") or REQUEST_BOUNDS_SCHEMA_VERSION
            ),
        )

    @classmethod
    def default(cls) -> "RequestBounds":
        """Conservative finite defaults for hermetic unit tests and callers."""

        return cls(
            timeout_ms=30_000,
            max_steps=100_000,
            max_memory_bytes=512 * 1024 * 1024,
            max_output_bytes=1024 * 1024,
        )

    @classmethod
    def from_legacy(cls, bounds: LegacyExecutionBounds) -> "RequestBounds":
        if not isinstance(bounds, LegacyExecutionBounds):
            raise RequestV2Error("from_legacy requires ExecutionBounds")
        return cls(
            timeout_ms=bounds.timeout_ms,
            max_steps=bounds.max_steps,
            max_memory_bytes=bounds.max_memory_bytes,
            max_output_bytes=bounds.max_output_bytes,
        )


# ---------------------------------------------------------------------------
# LogicObligation@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicObligationV2:
    """Typed proof obligation bound to source and expression identity.

    Interface: ``LogicObligation@2``.

    Replaces free-form ``logic_family`` strings with typed family, profile,
    property, view, notation, encoding, expression, feature, evidence, bounds,
    and authority ceiling fields.  Unsupported extensions and missing bounds
    fail at construction.
    """

    obligation_id: str
    statement: str
    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    property: LogicIdentity | Mapping[str, Any] | str
    view: LogicIdentity | Mapping[str, Any] | str
    notation: LogicIdentity | Mapping[str, Any] | str
    encoding: LogicIdentity | Mapping[str, Any] | str
    evidence_kind: LogicIdentity | Mapping[str, Any] | str
    bounds: RequestBounds | Mapping[str, Any]
    authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED
    features: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    slice_id: str = ""
    slice_digest: str = ""
    unsupported_extensions: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_OBLIGATION_V2_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_OBLIGATION_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _record_id(self.obligation_id, "obligation_id")
        )
        statement = _text(self.statement, "statement", maximum=MAX_STATEMENT_CHARS)
        object.__setattr__(self, "statement", statement)
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "expression_id", _record_id(self.expression_id, "expression_id")
        )
        object.__setattr__(
            self,
            "expression_digest",
            _sha256_hex(self.expression_digest, "expression_digest"),
        )

        object.__setattr__(
            self,
            "family",
            _coerce_identity(self.family, NamespaceKind.FAMILY, "family"),
        )
        object.__setattr__(
            self,
            "profile",
            _coerce_identity(self.profile, NamespaceKind.PROFILE, "profile"),
        )
        object.__setattr__(
            self,
            "property",
            _coerce_identity(self.property, NamespaceKind.PROPERTY, "property"),
        )
        object.__setattr__(
            self,
            "view",
            _coerce_identity(self.view, NamespaceKind.VIEW, "view"),
        )
        object.__setattr__(
            self,
            "notation",
            _coerce_identity(self.notation, NamespaceKind.NOTATION, "notation"),
        )
        object.__setattr__(
            self,
            "encoding",
            _coerce_identity(self.encoding, NamespaceKind.ENCODING, "encoding"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _coerce_identity(
                self.evidence_kind, NamespaceKind.EVIDENCE, "evidence_kind"
            ),
        )

        if self.bounds is None:
            raise MissingBoundsError(
                "LogicObligation@2 requires finite bounds before provider selection"
            )
        if isinstance(self.bounds, RequestBounds):
            bounds = self.bounds
        else:
            bounds = RequestBounds.from_dict(
                _require_mapping(self.bounds, "bounds")
            )
        object.__setattr__(self, "bounds", bounds)

        ceiling = _coerce_authority(self.authority_ceiling)
        _check_authority_overclaim(ceiling, self.evidence_kind)  # type: ignore[arg-type]
        object.__setattr__(self, "authority_ceiling", ceiling)

        object.__setattr__(self, "features", _feature_tuple(self.features, "features"))
        object.__setattr__(
            self,
            "assumption_ids",
            tuple(
                sorted(
                    {
                        _record_id(item, "assumption_ids item")
                        for item in _require_sequence(
                            self.assumption_ids, "assumption_ids"
                        )
                    }
                )
            ),
        )

        if self.slice_id:
            object.__setattr__(
                self, "slice_id", _record_id(self.slice_id, "slice_id")
            )
        if self.slice_digest:
            object.__setattr__(
                self, "slice_digest", _sha256_hex(self.slice_digest, "slice_digest")
            )

        unsupported = tuple(
            sorted(
                {
                    _text(item, "unsupported_extensions item", maximum=256)
                    for item in _require_sequence(
                        self.unsupported_extensions, "unsupported_extensions"
                    )
                }
            )
        )
        if unsupported:
            raise UnsupportedExtensionRequestError(
                "LogicObligation@2 rejects unsupported extensions before "
                f"provider selection: {', '.join(unsupported)}"
            )
        object.__setattr__(self, "unsupported_extensions", unsupported)

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_metadata_routing(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != LOGIC_OBLIGATION_V2_SCHEMA_VERSION:
            raise RequestV2Error(
                f"unsupported LogicObligationV2 schema_version "
                f"{self.schema_version!r}"
            )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise RequestV2Error(
                    "content_digest does not match LogicObligationV2 content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "authority_ceiling": _status_value(self.authority_ceiling),
            "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
            "document_id": self.document_id,
            "encoding": _identity_dict(self.encoding),  # type: ignore[arg-type]
            "evidence_kind": _identity_dict(self.evidence_kind),  # type: ignore[arg-type]
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "family": _identity_dict(self.family),  # type: ignore[arg-type]
            "features": list(self.features),
            "interface": self.interface,
            "notation": _identity_dict(self.notation),  # type: ignore[arg-type]
            "obligation_id": self.obligation_id,
            "profile": _identity_dict(self.profile),  # type: ignore[arg-type]
            "property": _identity_dict(self.property),  # type: ignore[arg-type]
            "schema_version": self.schema_version,
            "slice_digest": self.slice_digest,
            "slice_id": self.slice_id,
            "source_digest": self.source_digest,
            "statement": self.statement,
            "unsupported_extensions": list(self.unsupported_extensions),
            "view": _identity_dict(self.view),  # type: ignore[arg-type]
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicObligationV2":
        payload = _require_mapping(data, "LogicObligationV2")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_OBLIGATION_V2_INTERFACE:
            raise RequestV2Error(
                f"unsupported LogicObligationV2 interface {interface!r}"
            )
        if "bounds" not in payload or payload.get("bounds") is None:
            raise MissingBoundsError(
                "LogicObligation@2 requires bounds; missing bounds fail closed"
            )
        if "payload" in payload:
            raise ArbitraryPayloadError(
                "LogicObligation@2 rejects arbitrary payload fields"
            )
        return cls(
            obligation_id=str(payload.get("obligation_id") or ""),
            statement=str(payload.get("statement") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            expression_id=str(payload.get("expression_id") or ""),
            expression_digest=str(payload.get("expression_digest") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            property=payload.get("property") or "",
            view=payload.get("view") or "",
            notation=payload.get("notation") or "",
            encoding=payload.get("encoding") or "",
            evidence_kind=payload.get("evidence_kind") or "",
            bounds=payload["bounds"],
            authority_ceiling=str(
                payload.get("authority_ceiling")
                or RequestAuthorityCeiling.BOUNDED.value
            ),
            features=tuple(payload.get("features") or ()),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            slice_id=str(payload.get("slice_id") or ""),
            slice_digest=str(payload.get("slice_digest") or ""),
            unsupported_extensions=tuple(
                payload.get("unsupported_extensions") or ()
            ),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or LOGIC_OBLIGATION_V2_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_slice(
        cls,
        slice_: DomainLogicSliceV2,
        *,
        obligation_id: str,
        statement: str,
        encoding: LogicIdentity | Mapping[str, Any] | str,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str,
        bounds: RequestBounds | Mapping[str, Any] | None = None,
        authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LogicObligationV2":
        """Admit an obligation only from an admitted domain slice."""

        if not isinstance(slice_, DomainLogicSliceV2):
            raise RequestV2Error("from_slice requires DomainLogicSliceV2")
        admitted = slice_.require_admitted()
        if bounds is None:
            raise MissingBoundsError(
                "LogicObligation@2.from_slice requires explicit finite bounds"
            )
        return cls(
            obligation_id=obligation_id,
            statement=statement,
            document_id=admitted.document_id,
            source_digest=admitted.source_digest,
            expression_id=admitted.expression_id,
            expression_digest=admitted.expression_digest,
            family=admitted.family,
            profile=admitted.profile,
            property=admitted.property,
            view=admitted.view,
            notation=admitted.notation,
            encoding=encoding,
            evidence_kind=evidence_kind,
            bounds=bounds,
            authority_ceiling=authority_ceiling,
            features=admitted.features,
            assumption_ids=admitted.assumption_ids,
            slice_id=admitted.slice_id,
            slice_digest=admitted.content_digest,
            unsupported_extensions=admitted.unsupported_extensions,
            metadata=dict(metadata or {}),
        )


# ---------------------------------------------------------------------------
# BackendRequest@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BackendRequestV2:
    """Typed backend request that fails closed before provider selection.

    Interface: ``BackendRequest@2``.

    There is no free-form ``payload`` or bare ``logic_family`` routing field.
    Provider selection inputs are exactly the typed family, profile, property,
    view, notation, encoding, expression, feature, evidence, bounds, and
    authority ceiling fields, plus optional typed ``requested_provider``.
    """

    request_id: str
    obligation_id: str
    obligation_digest: str
    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    property: LogicIdentity | Mapping[str, Any] | str
    view: LogicIdentity | Mapping[str, Any] | str
    notation: LogicIdentity | Mapping[str, Any] | str
    encoding: LogicIdentity | Mapping[str, Any] | str
    evidence_kind: LogicIdentity | Mapping[str, Any] | str
    bounds: RequestBounds | Mapping[str, Any]
    authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED
    features: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    slice_id: str = ""
    slice_digest: str = ""
    requested_provider: LogicIdentity | Mapping[str, Any] | str | None = None
    content_digest: str = ""
    legacy_request_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = BACKEND_REQUEST_V2_SCHEMA_VERSION

    interface: ClassVar[str] = BACKEND_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "obligation_id", _record_id(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "obligation_digest",
            _sha256_hex(self.obligation_digest, "obligation_digest"),
        )
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "expression_id", _record_id(self.expression_id, "expression_id")
        )
        object.__setattr__(
            self,
            "expression_digest",
            _sha256_hex(self.expression_digest, "expression_digest"),
        )

        object.__setattr__(
            self,
            "family",
            _coerce_identity(self.family, NamespaceKind.FAMILY, "family"),
        )
        object.__setattr__(
            self,
            "profile",
            _coerce_identity(self.profile, NamespaceKind.PROFILE, "profile"),
        )
        object.__setattr__(
            self,
            "property",
            _coerce_identity(self.property, NamespaceKind.PROPERTY, "property"),
        )
        object.__setattr__(
            self,
            "view",
            _coerce_identity(self.view, NamespaceKind.VIEW, "view"),
        )
        object.__setattr__(
            self,
            "notation",
            _coerce_identity(self.notation, NamespaceKind.NOTATION, "notation"),
        )
        object.__setattr__(
            self,
            "encoding",
            _coerce_identity(self.encoding, NamespaceKind.ENCODING, "encoding"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _coerce_identity(
                self.evidence_kind, NamespaceKind.EVIDENCE, "evidence_kind"
            ),
        )

        if self.bounds is None:
            raise MissingBoundsError(
                "BackendRequest@2 requires finite bounds before provider selection"
            )
        if isinstance(self.bounds, RequestBounds):
            bounds = self.bounds
        else:
            bounds = RequestBounds.from_dict(
                _require_mapping(self.bounds, "bounds")
            )
        object.__setattr__(self, "bounds", bounds)

        ceiling = _coerce_authority(self.authority_ceiling)
        _check_authority_overclaim(ceiling, self.evidence_kind)  # type: ignore[arg-type]
        object.__setattr__(self, "authority_ceiling", ceiling)

        object.__setattr__(self, "features", _feature_tuple(self.features, "features"))
        object.__setattr__(
            self,
            "assumption_ids",
            tuple(
                sorted(
                    {
                        _record_id(item, "assumption_ids item")
                        for item in _require_sequence(
                            self.assumption_ids, "assumption_ids"
                        )
                    }
                )
            ),
        )

        if self.slice_id:
            object.__setattr__(
                self, "slice_id", _record_id(self.slice_id, "slice_id")
            )
        if self.slice_digest:
            object.__setattr__(
                self, "slice_digest", _sha256_hex(self.slice_digest, "slice_digest")
            )

        if self.requested_provider is None or self.requested_provider == "":
            object.__setattr__(self, "requested_provider", None)
        else:
            object.__setattr__(
                self,
                "requested_provider",
                _coerce_identity(
                    self.requested_provider,
                    NamespaceKind.PROVIDER,
                    "requested_provider",
                ),
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_metadata_routing(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.legacy_request_digest:
            object.__setattr__(
                self,
                "legacy_request_digest",
                _sha256_hex(self.legacy_request_digest, "legacy_request_digest"),
            )

        if self.schema_version != BACKEND_REQUEST_V2_SCHEMA_VERSION:
            raise RequestV2Error(
                f"unsupported BackendRequestV2 schema_version "
                f"{self.schema_version!r}"
            )

        # Source + typed-expression identity must be present before selection.
        if not self.document_id or not self.source_digest:
            raise RequestAdmissionError(
                "BackendRequest@2 requires document_id and source_digest "
                "before provider selection"
            )
        if not self.expression_id or not self.expression_digest:
            raise RequestAdmissionError(
                "BackendRequest@2 requires expression_id and expression_digest "
                "before provider selection"
            )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise RequestV2Error(
                    "content_digest does not match BackendRequestV2 content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        provider = self.requested_provider
        return {
            "assumption_ids": list(self.assumption_ids),
            "authority_ceiling": _status_value(self.authority_ceiling),
            "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
            "document_id": self.document_id,
            "encoding": _identity_dict(self.encoding),  # type: ignore[arg-type]
            "evidence_kind": _identity_dict(self.evidence_kind),  # type: ignore[arg-type]
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "family": _identity_dict(self.family),  # type: ignore[arg-type]
            "features": list(self.features),
            "interface": self.interface,
            "notation": _identity_dict(self.notation),  # type: ignore[arg-type]
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "profile": _identity_dict(self.profile),  # type: ignore[arg-type]
            "property": _identity_dict(self.property),  # type: ignore[arg-type]
            "request_id": self.request_id,
            "requested_provider": None
            if provider is None
            else _identity_dict(provider),  # type: ignore[arg-type]
            "schema_version": self.schema_version,
            "slice_digest": self.slice_digest,
            "slice_id": self.slice_id,
            "source_digest": self.source_digest,
            "view": _identity_dict(self.view),  # type: ignore[arg-type]
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["legacy_request_digest"] = self.legacy_request_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackendRequestV2":
        payload = _require_mapping(data, "BackendRequestV2")
        interface = payload.get("interface")
        if interface is not None and interface != BACKEND_REQUEST_V2_INTERFACE:
            raise RequestV2Error(
                f"unsupported BackendRequestV2 interface {interface!r}"
            )
        if "payload" in payload:
            raise ArbitraryPayloadError(
                "BackendRequest@2 rejects arbitrary payload fields; "
                "use typed family/profile/property/view/notation/encoding/"
                "expression/feature/evidence/bounds fields"
            )
        if "logic_family" in payload:
            raise ArbitraryPayloadError(
                "BackendRequest@2 rejects free-form logic_family routing; "
                "use typed family identity"
            )
        if "bounds" not in payload or payload.get("bounds") is None:
            raise MissingBoundsError(
                "BackendRequest@2 requires bounds; missing bounds fail closed "
                "before provider selection"
            )
        return cls(
            request_id=str(payload.get("request_id") or ""),
            obligation_id=str(payload.get("obligation_id") or ""),
            obligation_digest=str(payload.get("obligation_digest") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            expression_id=str(payload.get("expression_id") or ""),
            expression_digest=str(payload.get("expression_digest") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            property=payload.get("property") or "",
            view=payload.get("view") or "",
            notation=payload.get("notation") or "",
            encoding=payload.get("encoding") or "",
            evidence_kind=payload.get("evidence_kind") or "",
            bounds=payload["bounds"],
            authority_ceiling=str(
                payload.get("authority_ceiling")
                or RequestAuthorityCeiling.BOUNDED.value
            ),
            features=tuple(payload.get("features") or ()),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            slice_id=str(payload.get("slice_id") or ""),
            slice_digest=str(payload.get("slice_digest") or ""),
            requested_provider=payload.get("requested_provider"),
            content_digest=str(payload.get("content_digest") or ""),
            legacy_request_digest=str(payload.get("legacy_request_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or BACKEND_REQUEST_V2_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_obligation(
        cls,
        obligation: LogicObligationV2,
        *,
        request_id: str,
        requested_provider: LogicIdentity | Mapping[str, Any] | str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "BackendRequestV2":
        """Build a backend request from a fully typed obligation."""

        if not isinstance(obligation, LogicObligationV2):
            raise RequestV2Error("from_obligation requires LogicObligationV2")
        return cls(
            request_id=request_id,
            obligation_id=obligation.obligation_id,
            obligation_digest=obligation.content_digest,
            document_id=obligation.document_id,
            source_digest=obligation.source_digest,
            expression_id=obligation.expression_id,
            expression_digest=obligation.expression_digest,
            family=obligation.family,
            profile=obligation.profile,
            property=obligation.property,
            view=obligation.view,
            notation=obligation.notation,
            encoding=obligation.encoding,
            evidence_kind=obligation.evidence_kind,
            bounds=obligation.bounds,
            authority_ceiling=obligation.authority_ceiling,
            features=obligation.features,
            assumption_ids=obligation.assumption_ids,
            slice_id=obligation.slice_id,
            slice_digest=obligation.slice_digest,
            requested_provider=requested_provider,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_slice(
        cls,
        slice_: DomainLogicSliceV2,
        *,
        request_id: str,
        obligation_id: str,
        statement: str,
        encoding: LogicIdentity | Mapping[str, Any] | str,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str,
        bounds: RequestBounds | Mapping[str, Any] | None = None,
        authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED,
        requested_provider: LogicIdentity | Mapping[str, Any] | str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "BackendRequestV2":
        """Admit a backend request only from an admitted domain slice.

        Cross-namespace misuse, unsupported extensions, missing bounds, and
        authority overclaims fail here — before any provider is selected.
        """

        obligation = LogicObligationV2.from_slice(
            slice_,
            obligation_id=obligation_id,
            statement=statement,
            encoding=encoding,
            evidence_kind=evidence_kind,
            bounds=bounds,
            authority_ceiling=authority_ceiling,
        )
        return cls.from_obligation(
            obligation,
            request_id=request_id,
            requested_provider=requested_provider,
            metadata=metadata,
        )

    @classmethod
    def from_legacy(
        cls,
        request: LegacyBackendRequest,
        *,
        document_id: str,
        source_digest: str,
        expression_id: str,
        expression_digest: str,
        profile: LogicIdentity | Mapping[str, Any] | str,
        property: LogicIdentity | Mapping[str, Any] | str,
        view: LogicIdentity | Mapping[str, Any] | str,
        notation: LogicIdentity | Mapping[str, Any] | str,
        encoding: LogicIdentity | Mapping[str, Any] | str,
        evidence_kind: LogicIdentity | Mapping[str, Any] | str,
        authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED,
        features: Sequence[str] = (),
        slice_id: str = "",
        slice_digest: str = "",
        request_id: str | None = None,
    ) -> "BackendRequestV2":
        """Lift a legacy BackendRequest@1 into BackendRequest@2.

        Legacy free-form ``payload`` and bare ``logic_family`` are **not**
        preserved as routing fields.  Callers must supply typed namespace
        identities and source/expression lineage explicitly.
        """

        if not isinstance(request, LegacyBackendRequest):
            raise RequestV2Error("from_legacy requires BackendRequest@1")
        if request.payload and dict(request.payload.to_dict()):
            # Explicit dual-read: payload content is dropped with a digest marker
            # in metadata, never used for routing.
            pass
        family_value = request.logic_family
        if family_value in {"", "unspecified"}:
            raise RequestAdmissionError(
                "legacy BackendRequest logic_family is unspecified; "
                "cannot lift to BackendRequest@2 without a typed family"
            )
        return cls(
            request_id=request_id or request.request_id,
            obligation_id=request.obligation_id,
            obligation_digest=request.obligation_digest
            if _looks_like_sha256(request.obligation_digest)
            else content_sha256(
                canonical_json_bytes(
                    {
                        "obligation_id": request.obligation_id,
                        "legacy_obligation_digest": request.obligation_digest,
                    }
                )
            ),
            document_id=document_id,
            source_digest=source_digest,
            expression_id=expression_id,
            expression_digest=expression_digest,
            family=family_id(family_value)
            if isinstance(family_value, str)
            else family_value,
            profile=profile,
            property=property,
            view=view,
            notation=notation,
            encoding=encoding,
            evidence_kind=evidence_kind,
            bounds=RequestBounds.from_legacy(request.bounds),
            authority_ceiling=authority_ceiling,
            features=tuple(features),
            assumption_ids=request.assumption_ids,
            slice_id=slice_id,
            slice_digest=slice_digest,
            requested_provider=(
                provider_id(request.requested_backend_id)
                if request.requested_backend_id
                else None
            ),
            legacy_request_digest=request.digest
            if _looks_like_sha256(request.digest)
            else content_sha256(
                canonical_json_bytes({"legacy_digest": request.digest})
            ),
            metadata={
                "migrated_from": LEGACY_BACKEND_REQUEST_INTERFACE,
                "legacy_query_kind": request.query_kind.value
                if isinstance(request.query_kind, QueryKind)
                else str(request.query_kind),
                "legacy_payload_dropped": True,
            },
        )


def _looks_like_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "BACKEND_REQUEST_V2_INTERFACE",
    "BACKEND_REQUEST_V2_SCHEMA_VERSION",
    "LEGACY_BACKEND_REQUEST_INTERFACE",
    "LEGACY_BACKEND_REQUEST_SCHEMA_VERSION",
    "LOGIC_OBLIGATION_V2_INTERFACE",
    "LOGIC_OBLIGATION_V2_SCHEMA_VERSION",
    "REQUESTS_V2_MODULE_VERSION",
    "REQUEST_BOUNDS_SCHEMA_VERSION",
    "ArbitraryPayloadError",
    "AuthorityOverclaimError",
    "BackendRequestV2",
    "CrossNamespaceRequestError",
    "LogicObligationV2",
    "MissingBoundsError",
    "RequestAdmissionError",
    "RequestAuthorityCeiling",
    "RequestBounds",
    "RequestV2Error",
    "UnsupportedExtensionRequestError",
]
