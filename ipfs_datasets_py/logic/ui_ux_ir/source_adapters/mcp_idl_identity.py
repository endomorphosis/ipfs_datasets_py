"""MCP-IDL verified interface identity authority for UI/UX IR (UIR-030 / UIR-002).

Interface: ``MCPIDLIdentityInterop@1``
Profile: ``mcp-idl-interface-identity-v1``

This module is the adapter-side authority for *verified* MCP interface CIDs.
It injects or lazily loads the reviewed CIDv1/raw/sha2-256/base32 constructor
and never equates ``interface_cid``, ``ui_ir_cid``, or typed ``legacy_alias``
values.

Non-goals (fail-closed):
- Do not rewrite production registries in place.
- Do not promote pseudo-CIDs or legacy aliases to verified identity.
- Do not treat interface identity as an execution grant.
- Do not trust mutable instance caches after identity-affecting mutation.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, MutableMapping, Optional, Protocol, Sequence

# ---------------------------------------------------------------------------
# Profile constants (frozen by UIR-002 / MCPIDLIdentityInterop@1)
# ---------------------------------------------------------------------------

MCPIDL_IDENTITY_INTEROP: Final = "MCPIDLIdentityInterop@1"
INTERFACE_IDENTITY_PROFILE: Final = "mcp-idl-interface-identity-v1"
INTERFACE_IDENTITY_PROFILE_ID: Final = (
    "ContentIdentityProfile/mcp-idl-interface-identity-v1"
)
INTERFACE_IDENTITY_SCHEMA: Final = "ui-ux-ir/mcp-idl-interface-identity@1"

CID_VERSION: Final = 1
MULTICODEC_RAW: Final = 0x55
MULTICODEC_DAG_PB: Final = 0x70
MULTIHASH_SHA2_256: Final = 0x12
DIGEST_SIZE: Final = 32
MULTIBASE_PREFIX: Final = "b"
VERIFIED_CID_PREFIX: Final = "bafkrei"

IDENTITY_AFFECTING_FIELDS: Final = (
    "name",
    "namespace",
    "version",
    "methods",
    "errors",
    "requires",
    "compatibility",
    "semantic_tags",
    "observability",
    "interaction_patterns",
    "resource_cost_hints",
)

METHOD_IDENTITY_AFFECTING_FIELDS: Final = (
    "name",
    "input_schema",
    "output_schema",
    "input_schema_cid",
    "output_schema_cid",
    "errors",
    "error_schema_cids",
    "event_schema",
    "event_schema_cid",
    "streaming",
    "description",
)

# Wire dual-forms: prefer snake_case for the bound preimage (profile golden vectors).
_CAMEL_TO_SNAKE: Final = {
    "inputSchema": "input_schema",
    "outputSchema": "output_schema",
    "inputSchemaCid": "input_schema_cid",
    "outputSchemaCid": "output_schema_cid",
    "errorSchemaCids": "error_schema_cids",
    "eventSchema": "event_schema",
    "eventSchemaCid": "event_schema_cid",
    "semanticTags": "semantic_tags",
    "interactionPatterns": "interaction_patterns",
    "resourceCostHints": "resource_cost_hints",
    "compatibleWith": "compatible_with",
    "requestResponse": "request_response",
    "eventStreams": "event_streams",
    "tokensPerCall": "tokens_per_call",
    "latencyMs": "latency_ms",
    "bytesPerCall": "bytes_per_call",
    "schemaHash": "schema_hash",
}

_PLACEHOLDER_RE: Final = re.compile(r"^cidv1-sha256-[0-9a-fA-F]{64}$")
_SHA256_ALIAS_RE: Final = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_BARE_HEX_RE: Final = re.compile(r"^[0-9a-fA-F]{64}$")
_MOCK_BAFY_RE: Final = re.compile(r"^bafy-mock-", re.IGNORECASE)

# Descriptor profile tags that are accepted for adaptation. Unknown profiles fail closed.
KNOWN_DESCRIPTOR_PROFILES: Final = frozenset(
    {
        INTERFACE_IDENTITY_PROFILE,
        "mcp-idl-identity-v1",  # accelerator package profile name (interop alias)
        "mcp-idl",
        "MCP-IDL",
        "mcp++/profile-a",
    }
)


class IdentityDomain(str, Enum):
    """Typed identity domains that must never be equated for authority."""

    INTERFACE_CID = "interface_cid"
    UI_IR_CID = "ui_ir_cid"
    LEGACY_ALIAS = "legacy_alias"


class LegacyAliasKind(str, Enum):
    """Disposition kinds for non-verified historical identifiers."""

    SHA256_HEX_PREFIX = "sha256_hex_prefix"
    CIDV1_SHA256_PLACEHOLDER = "cidv1_sha256_placeholder"
    MOCK_LABEL = "mock_label"
    BARE_HEX_DIGEST = "bare_hex_digest"
    MISLABELED_DAG_PB = "mislabeled_dag_pb"
    NON_CANONICAL_CASING = "non_canonical_casing"
    UNKNOWN = "unknown"


class MCPIDLIdentityError(ValueError):
    """Base fail-closed identity error for the MCP-IDL interface profile."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "mcp_idl_identity_error",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.details = dict(details or {})


class PseudoCIDError(MCPIDLIdentityError):
    """Raised when a pseudo-CID / placeholder is offered as verified identity."""


class PreimageMismatchError(MCPIDLIdentityError):
    """Raised when a claimed interface_cid does not match the descriptor preimage."""


class MutableIdentityDriftError(MCPIDLIdentityError):
    """Raised when a cached/mutable identity no longer matches the current snapshot."""


class UnknownDescriptorProfileError(MCPIDLIdentityError):
    """Raised when the descriptor advertises an unknown identity profile."""


class MalformedDescriptorError(MCPIDLIdentityError):
    """Raised when a descriptor is structurally unsuitable for identity binding."""


class DomainConflationError(MCPIDLIdentityError):
    """Raised when distinct identity domains are equated for authority."""


# ---------------------------------------------------------------------------
# Authority provider (injected or lazy-loaded)
# ---------------------------------------------------------------------------


CidConstructor = Callable[[bytes], str]


def _independent_cid_v1_raw(data: bytes) -> str:
    """Independent CIDv1/raw/sha2-256/base32 constructor (no package import)."""

    digest = hashlib.sha256(bytes(data)).digest()
    if len(digest) != DIGEST_SIZE:
        raise MCPIDLIdentityError(
            "unexpected SHA-256 digest size",
            reason_code="digest_size_mismatch",
            details={"size": len(digest)},
        )
    cid_bytes = bytes([CID_VERSION, MULTICODEC_RAW, MULTIHASH_SHA2_256, DIGEST_SIZE]) + digest
    return MULTIBASE_PREFIX + base64.b32encode(cid_bytes).decode("ascii").rstrip("=").lower()


def _lazy_kubo_cid_for_bytes() -> CidConstructor:
    """Lazy-load the reviewed accelerator CID constructor when available."""

    try:
        from ipfs_accelerate_py.mcp_server.mcplusplus.kubo_cid import (  # type: ignore
            cid_for_bytes,
        )
    except Exception:
        return _independent_cid_v1_raw
    return cid_for_bytes


def _lazy_registry_canonicalize() -> Optional[Callable[[Mapping[str, Any]], bytes]]:
    try:
        from ipfs_accelerate_py.mcp_server.mcplusplus.idl_registry import (  # type: ignore
            canonicalize_descriptor,
        )
    except Exception:
        return None
    return canonicalize_descriptor


class InterfaceCIDAuthority(Protocol):
    """Protocol for injected interface CID constructors."""

    def cid_for_bytes(self, data: bytes) -> str:
        """Return CIDv1/raw/sha2-256/base32 for *data*."""


@dataclass(frozen=True, slots=True)
class _CallableAuthority:
    """Adapter that wraps a plain callable as an :class:`InterfaceCIDAuthority`."""

    _fn: CidConstructor

    def cid_for_bytes(self, data: bytes) -> str:
        return self._fn(bytes(data))


def default_interface_cid_authority(
    constructor: Optional[CidConstructor] = None,
) -> InterfaceCIDAuthority:
    """Return an injected or lazily resolved CID authority."""

    if constructor is not None:
        return _CallableAuthority(constructor)
    return _CallableAuthority(_lazy_kubo_cid_for_bytes())


# ---------------------------------------------------------------------------
# Descriptor normalization and preimage construction
# ---------------------------------------------------------------------------


def _deep_freeze(value: Any) -> Any:
    """Return an immutable deep copy of JSON-compatible structures."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    # Reject non-JSON identity-affecting types rather than inventing a form.
    raise MalformedDescriptorError(
        f"descriptor contains non-JSON value of type {type(value).__name__}",
        reason_code="non_json_descriptor_value",
        details={"type": type(value).__name__},
    )


def freeze_descriptor_snapshot(descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
    """Deep-freeze a descriptor snapshot for identity hashing.

    Callers must pass an immutable snapshot (or accept this freeze). Mutable
    instance caches are non-authoritative after field mutation.
    """

    if not isinstance(descriptor, Mapping):
        raise MalformedDescriptorError(
            "descriptor must be a mapping",
            reason_code="descriptor_not_object",
        )
    return _deep_freeze(copy.deepcopy(dict(descriptor)))


def _normalize_key(key: str) -> str:
    return _CAMEL_TO_SNAKE.get(key, key)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return normalize_descriptor_for_identity(value)
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def normalize_descriptor_for_identity(
    descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize dual camelCase/snake_case wire forms to snake_case preimage keys.

    Dual aliases on the wire must be normalized before hashing so identity is
    independent of which alias form arrived. When both forms are present and
    disagree, the snake_case value wins (profile golden vectors use snake_case).
    """

    if not isinstance(descriptor, Mapping):
        raise MalformedDescriptorError(
            "descriptor must be a mapping",
            reason_code="descriptor_not_object",
        )

    out: dict[str, Any] = {}
    for raw_key, raw_value in descriptor.items():
        if not isinstance(raw_key, str):
            raise MalformedDescriptorError(
                "descriptor keys must be strings",
                reason_code="descriptor_key_not_string",
            )
        if raw_key == "interface_cid":
            # Must never appear inside the preimage.
            continue
        key = _normalize_key(raw_key)
        value = _normalize_value(raw_value)
        if key in out and out[key] != value and raw_key != key:
            # Prefer existing snake_case binding when dual forms disagree.
            continue
        out[key] = value
    return out


def identity_bound_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    """Return the identity-bound object used for preimage construction.

    Required profile fields are always present (empty collections when absent)
    so partial omission of claimed identity-affecting fields cannot silently
    yield a different authority surface.
    """

    normalized = normalize_descriptor_for_identity(descriptor)
    bound: dict[str, Any] = {
        "name": normalized.get("name", ""),
        "namespace": normalized.get("namespace", ""),
        "version": normalized.get("version", ""),
        "methods": list(normalized.get("methods") or []),
        "errors": list(normalized.get("errors") or []),
        "requires": list(normalized.get("requires") or []),
        "compatibility": dict(
            normalized.get("compatibility")
            or {"compatible_with": [], "supersedes": []}
        ),
    }
    # Optional-when-claimed fields: bind exactly when present on the wire.
    for optional in (
        "semantic_tags",
        "observability",
        "interaction_patterns",
        "resource_cost_hints",
    ):
        if optional in normalized:
            bound[optional] = normalized[optional]
    return bound


def canonicalize_interface_preimage(descriptor: Mapping[str, Any]) -> bytes:
    """Return UTF-8 canonical preimage bytes for the identity-bound descriptor.

    Matches the registry ``canonicalize_descriptor`` contract: sorted keys,
    compact separators, ``ensure_ascii=True``.
    """

    bound = identity_bound_descriptor(descriptor)
    local = json.dumps(
        bound,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    # Cross-check against package authority when available (must agree).
    registry_canonicalize = _lazy_registry_canonicalize()
    if registry_canonicalize is not None:
        via_registry = registry_canonicalize(bound)
        if via_registry != local:
            raise MCPIDLIdentityError(
                "registry canonicalize_descriptor disagrees with local preimage",
                reason_code="canonicalization_divergence",
                details={
                    "local_sha256": hashlib.sha256(local).hexdigest(),
                    "registry_sha256": hashlib.sha256(via_registry).hexdigest(),
                },
            )
    return local


# ---------------------------------------------------------------------------
# CID classification and verification
# ---------------------------------------------------------------------------


def is_pseudo_interface_cid(value: Any) -> bool:
    """Return True for digest-shaped placeholders that are never verified CIDs."""

    if not isinstance(value, str) or not value:
        return False
    text = value.strip()
    if _PLACEHOLDER_RE.match(text):
        return True
    if _SHA256_ALIAS_RE.match(text):
        return True
    if _BARE_HEX_RE.match(text):
        return True
    if _MOCK_BAFY_RE.match(text):
        return True
    return False


def classify_legacy_alias(value: str) -> LegacyAliasKind:
    """Classify a non-verified identity string as a typed legacy alias kind."""

    text = value.strip()
    if _PLACEHOLDER_RE.match(text):
        return LegacyAliasKind.CIDV1_SHA256_PLACEHOLDER
    if _SHA256_ALIAS_RE.match(text):
        return LegacyAliasKind.SHA256_HEX_PREFIX
    if _BARE_HEX_RE.match(text):
        return LegacyAliasKind.BARE_HEX_DIGEST
    if _MOCK_BAFY_RE.match(text):
        return LegacyAliasKind.MOCK_LABEL
    if text != text.lower() and text.lower().startswith(VERIFIED_CID_PREFIX):
        return LegacyAliasKind.NON_CANONICAL_CASING
    if text.startswith("bafybei"):
        return LegacyAliasKind.MISLABELED_DAG_PB
    return LegacyAliasKind.UNKNOWN


def is_verified_interface_cid_string(value: Any) -> bool:
    """Structural check for a lowercase CIDv1/raw/sha2-256/base32 string."""

    if not isinstance(value, str) or not value:
        return False
    if value != value.lower():
        return False
    if is_pseudo_interface_cid(value):
        return False
    if not value.startswith(VERIFIED_CID_PREFIX):
        return False
    if not value.startswith(MULTIBASE_PREFIX):
        return False
    body = value[1:]
    padded = body.upper() + ("=" * ((8 - (len(body) % 8)) % 8))
    try:
        raw = base64.b32decode(padded)
    except Exception:
        return False
    if len(raw) != 4 + DIGEST_SIZE:
        return False
    return (
        raw[0] == CID_VERSION
        and raw[1] == MULTICODEC_RAW
        and raw[2] == MULTIHASH_SHA2_256
        and raw[3] == DIGEST_SIZE
    )


def dag_pb_twin_cid(preimage: bytes) -> str:
    """Return the mislabeled CIDv1/dag-pb twin of *preimage* (rejection evidence)."""

    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    digest = hashlib.sha256(bytes(preimage)).digest()
    payload = bytes([CID_VERSION, MULTICODEC_DAG_PB, MULTIHASH_SHA2_256, DIGEST_SIZE]) + digest
    bits = 0
    val = 0
    out: list[str] = []
    for byte in payload:
        val = (val << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(alphabet[(val >> bits) & 31])
    if bits:
        out.append(alphabet[(val << (5 - bits)) & 31])
    return MULTIBASE_PREFIX + "".join(out)


@dataclass(frozen=True, slots=True)
class VerifiedInterfaceIdentity:
    """Profile-tagged, preimage-verified MCP interface identity."""

    interface_cid: str
    profile: str
    profile_id: str
    canonical_bytes: bytes
    sha256_hex: str
    byte_length: int
    snapshot: Mapping[str, Any]
    validated: bool = True
    reason_codes: tuple[str, ...] = ("interface_cid_verified", INTERFACE_IDENTITY_PROFILE)
    schema: str = INTERFACE_IDENTITY_SCHEMA
    legacy_aliases: tuple[str, ...] = ()

    def to_dict(self, *, include_canonical_bytes: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "byte_length": self.byte_length,
            "interface_cid": self.interface_cid,
            "legacy_aliases": list(self.legacy_aliases),
            "profile": self.profile,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "schema": self.schema,
            "sha256_hex": self.sha256_hex,
            "validated": self.validated,
        }
        if include_canonical_bytes:
            payload["canonical_bytes_hex"] = self.canonical_bytes.hex()
        return payload


@dataclass
class MCPIDLIdentityAuthority:
    """Injected/lazy authority for computing and verifying interface CIDs.

    The authority always recomputes from an immutable snapshot. It never
    returns a cached CID after the underlying descriptor mutates.
    """

    cid_authority: InterfaceCIDAuthority = field(
        default_factory=default_interface_cid_authority
    )
    profile: str = INTERFACE_IDENTITY_PROFILE
    profile_id: str = INTERFACE_IDENTITY_PROFILE_ID
    known_profiles: frozenset[str] = field(
        default_factory=lambda: KNOWN_DESCRIPTOR_PROFILES
    )

    def compute(self, descriptor: Mapping[str, Any]) -> VerifiedInterfaceIdentity:
        """Compute a verified interface_cid from a frozen descriptor snapshot."""

        self._require_known_profile(descriptor)
        snapshot = freeze_descriptor_snapshot(identity_bound_descriptor(descriptor))
        preimage = canonicalize_interface_preimage(dict(snapshot))
        via_authority = self.cid_authority.cid_for_bytes(preimage)
        via_independent = _independent_cid_v1_raw(preimage)
        if via_authority != via_independent:
            raise MCPIDLIdentityError(
                "injected CID authority diverges from independent CIDv1/raw constructor",
                reason_code="cid_authority_divergence",
                details={
                    "authority_cid": via_authority,
                    "independent_cid": via_independent,
                },
            )
        if not is_verified_interface_cid_string(via_authority):
            raise PseudoCIDError(
                "authority returned a non-verified interface CID form",
                reason_code="pseudo_cid_rejected",
                details={"cid": via_authority},
            )
        return VerifiedInterfaceIdentity(
            interface_cid=via_authority,
            profile=self.profile,
            profile_id=self.profile_id,
            canonical_bytes=preimage,
            sha256_hex=hashlib.sha256(preimage).hexdigest(),
            byte_length=len(preimage),
            snapshot=snapshot,
        )

    def verify(
        self,
        claimed_interface_cid: str,
        descriptor: Mapping[str, Any],
        *,
        legacy_aliases: Sequence[str] = (),
    ) -> VerifiedInterfaceIdentity:
        """Verify *claimed_interface_cid* against the descriptor preimage.

        Rejects pseudo-CIDs, wrong-codec twins, casing drift, and preimage
        mismatches. Typed legacy aliases may be recorded but never promoted.
        """

        if not isinstance(claimed_interface_cid, str) or not claimed_interface_cid:
            raise PseudoCIDError(
                "claimed interface_cid must be a nonempty string",
                reason_code="empty_interface_cid",
            )
        if is_pseudo_interface_cid(claimed_interface_cid):
            kind = classify_legacy_alias(claimed_interface_cid)
            raise PseudoCIDError(
                "pseudo or digest-shaped interface CID is not a verified interface_cid",
                reason_code="pseudo_cid_rejected",
                details={
                    "cid": claimed_interface_cid,
                    "legacy_alias_kind": kind.value,
                },
            )
        if claimed_interface_cid != claimed_interface_cid.lower():
            raise PseudoCIDError(
                "verified interface_cid must be lowercase base32",
                reason_code="cid_not_lowercase",
                details={"cid": claimed_interface_cid},
            )
        if not is_verified_interface_cid_string(claimed_interface_cid):
            # DAG-PB twins and other wrong-codec CIDs land here.
            kind = classify_legacy_alias(claimed_interface_cid)
            raise PseudoCIDError(
                "claimed value is not a CIDv1/raw/sha2-256/base32 interface_cid",
                reason_code="interface_cid_profile_mismatch",
                details={
                    "cid": claimed_interface_cid,
                    "legacy_alias_kind": kind.value,
                },
            )

        expected = self.compute(descriptor)
        if claimed_interface_cid != expected.interface_cid:
            raise PreimageMismatchError(
                "claimed interface_cid does not match recomputed preimage",
                reason_code="preimage_mismatch",
                details={
                    "claimed": claimed_interface_cid,
                    "expected": expected.interface_cid,
                },
            )

        # Preserve typed legacy aliases without equating them to interface_cid.
        preserved: list[str] = []
        for alias in legacy_aliases:
            if not isinstance(alias, str) or not alias:
                continue
            if alias == expected.interface_cid:
                # Recording the verified CID as a "legacy alias" is a domain error.
                raise DomainConflationError(
                    "legacy_alias must not equal verified interface_cid",
                    reason_code="legacy_alias_equals_interface_cid",
                    details={"value": alias},
                )
            preserved.append(alias)

        return VerifiedInterfaceIdentity(
            interface_cid=expected.interface_cid,
            profile=expected.profile,
            profile_id=expected.profile_id,
            canonical_bytes=expected.canonical_bytes,
            sha256_hex=expected.sha256_hex,
            byte_length=expected.byte_length,
            snapshot=expected.snapshot,
            validated=True,
            reason_codes=expected.reason_codes + ("preimage_verified",),
            legacy_aliases=tuple(preserved),
        )

    def detect_mutable_identity_drift(
        self,
        *,
        cached_interface_cid: str,
        current_descriptor: Mapping[str, Any],
    ) -> None:
        """Fail closed when a cached CID no longer matches the current snapshot.

        After an identity-affecting mutation, only the recomputed CID of the
        current immutable snapshot is verified. A pre-mutation CID is
        non-authoritative.
        """

        expected = self.compute(current_descriptor)
        if cached_interface_cid != expected.interface_cid:
            raise MutableIdentityDriftError(
                "cached interface_cid no longer matches current descriptor preimage",
                reason_code="mutable_identity_drift",
                details={
                    "cached": cached_interface_cid,
                    "current": expected.interface_cid,
                },
            )

    def _require_known_profile(self, descriptor: Mapping[str, Any]) -> None:
        """Reject unknown/malformed advertised identity profiles when present."""

        if not isinstance(descriptor, Mapping):
            raise MalformedDescriptorError(
                "descriptor must be a mapping",
                reason_code="descriptor_not_object",
            )
        advertised = descriptor.get("identity_profile") or descriptor.get("profile")
        if advertised is None:
            return
        if not isinstance(advertised, str) or not advertised.strip():
            raise UnknownDescriptorProfileError(
                "descriptor identity profile is malformed",
                reason_code="malformed_descriptor_profile",
                details={"profile": advertised},
            )
        if advertised not in self.known_profiles:
            raise UnknownDescriptorProfileError(
                f"unknown descriptor identity profile: {advertised!r}",
                reason_code="unknown_descriptor_profile",
                details={
                    "profile": advertised,
                    "known": sorted(self.known_profiles),
                },
            )
        required = ("name", "namespace", "version", "methods")
        missing = [key for key in required if key not in descriptor and _normalize_key(key) not in descriptor]
        # Methods may be under either form after normalization; check raw.
        if "methods" not in descriptor and "Methods" not in descriptor:
            missing.append("methods") if "methods" not in missing else None
        # Soft structural check: name/namespace/version must be present for verified identity.
        for key in ("name", "namespace", "version"):
            if key not in descriptor:
                # Allow after normalization path — re-check via normalize.
                pass
        normalized = normalize_descriptor_for_identity(descriptor)
        for key in ("name", "namespace", "version", "methods"):
            if key not in normalized:
                raise MalformedDescriptorError(
                    f"descriptor missing required field {key!r}",
                    reason_code="malformed_descriptor",
                    details={"missing": key},
                )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------

_DEFAULT_AUTHORITY: Optional[MCPIDLIdentityAuthority] = None


def get_default_identity_authority(
    *,
    cid_constructor: Optional[CidConstructor] = None,
) -> MCPIDLIdentityAuthority:
    """Return the process-default authority (injectable for tests)."""

    global _DEFAULT_AUTHORITY
    if cid_constructor is not None:
        return MCPIDLIdentityAuthority(
            cid_authority=default_interface_cid_authority(cid_constructor)
        )
    if _DEFAULT_AUTHORITY is None:
        _DEFAULT_AUTHORITY = MCPIDLIdentityAuthority()
    return _DEFAULT_AUTHORITY


def reset_default_identity_authority() -> None:
    """Clear the lazy default authority (tests only)."""

    global _DEFAULT_AUTHORITY
    _DEFAULT_AUTHORITY = None


def compute_verified_interface_cid(
    descriptor: Mapping[str, Any],
    *,
    authority: Optional[MCPIDLIdentityAuthority] = None,
) -> str:
    """Compute a verified ``interface_cid`` for *descriptor*."""

    auth = authority or get_default_identity_authority()
    return auth.compute(descriptor).interface_cid


def verify_interface_preimage(
    claimed_interface_cid: str,
    descriptor: Mapping[str, Any],
    *,
    legacy_aliases: Sequence[str] = (),
    authority: Optional[MCPIDLIdentityAuthority] = None,
) -> VerifiedInterfaceIdentity:
    """Verify *claimed_interface_cid* against *descriptor* preimage bytes."""

    auth = authority or get_default_identity_authority()
    return auth.verify(
        claimed_interface_cid,
        descriptor,
        legacy_aliases=legacy_aliases,
    )


def assert_domains_not_equated(
    *,
    interface_cid: str,
    ui_ir_cid: str = "",
    legacy_aliases: Sequence[str] = (),
) -> None:
    """Fail closed if distinct identity domains are treated as interchangeable."""

    if ui_ir_cid and interface_cid and ui_ir_cid == interface_cid:
        raise DomainConflationError(
            "ui_ir_cid must never equal interface_cid",
            reason_code="ui_ir_cid_equals_interface_cid",
            details={
                "left": IdentityDomain.UI_IR_CID.value,
                "right": IdentityDomain.INTERFACE_CID.value,
                "value": interface_cid,
            },
        )
    for alias in legacy_aliases:
        if alias and alias == interface_cid:
            raise DomainConflationError(
                "legacy_alias must never equal interface_cid",
                reason_code="legacy_alias_equals_interface_cid",
                details={
                    "left": IdentityDomain.LEGACY_ALIAS.value,
                    "right": IdentityDomain.INTERFACE_CID.value,
                    "value": alias,
                },
            )
        if ui_ir_cid and alias and alias == ui_ir_cid:
            raise DomainConflationError(
                "legacy_alias must never equal ui_ir_cid",
                reason_code="legacy_alias_equals_ui_ir_cid",
                details={
                    "left": IdentityDomain.LEGACY_ALIAS.value,
                    "right": IdentityDomain.UI_IR_CID.value,
                    "value": alias,
                },
            )


def classify_identity_string(value: str) -> tuple[IdentityDomain, Optional[LegacyAliasKind]]:
    """Classify a string into an identity domain (never promotes aliases)."""

    if is_verified_interface_cid_string(value):
        return IdentityDomain.INTERFACE_CID, None
    if is_pseudo_interface_cid(value) or classify_legacy_alias(value) is not LegacyAliasKind.UNKNOWN:
        return IdentityDomain.LEGACY_ALIAS, classify_legacy_alias(value)
    # Non-profile CIDs and free-form labels stay typed aliases.
    return IdentityDomain.LEGACY_ALIAS, LegacyAliasKind.UNKNOWN


__all__ = [
    "CID_VERSION",
    "DIGEST_SIZE",
    "IDENTITY_AFFECTING_FIELDS",
    "INTERFACE_IDENTITY_PROFILE",
    "INTERFACE_IDENTITY_PROFILE_ID",
    "INTERFACE_IDENTITY_SCHEMA",
    "KNOWN_DESCRIPTOR_PROFILES",
    "MCPIDL_IDENTITY_INTEROP",
    "METHOD_IDENTITY_AFFECTING_FIELDS",
    "MULTICODEC_DAG_PB",
    "MULTICODEC_RAW",
    "MULTIHASH_SHA2_256",
    "DomainConflationError",
    "IdentityDomain",
    "LegacyAliasKind",
    "MCPIDLIdentityAuthority",
    "MCPIDLIdentityError",
    "MalformedDescriptorError",
    "MutableIdentityDriftError",
    "PreimageMismatchError",
    "PseudoCIDError",
    "UnknownDescriptorProfileError",
    "VerifiedInterfaceIdentity",
    "assert_domains_not_equated",
    "canonicalize_interface_preimage",
    "classify_identity_string",
    "classify_legacy_alias",
    "compute_verified_interface_cid",
    "dag_pb_twin_cid",
    "default_interface_cid_authority",
    "freeze_descriptor_snapshot",
    "get_default_identity_authority",
    "identity_bound_descriptor",
    "is_pseudo_interface_cid",
    "is_verified_interface_cid_string",
    "normalize_descriptor_for_identity",
    "reset_default_identity_authority",
    "verify_interface_preimage",
]
