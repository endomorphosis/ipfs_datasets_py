"""Immutable, chain-neutral models for bounded smart-contract acquisition.

This module defines the shared request/result surface for
``processors.smart_contracts``.  Records are content-addressed and fail closed:
public payloads never carry private keys, signing material, or broadcast
handles.

Only the Python standard library and the package-local ``canonical`` /
``errors`` modules are imported.  Importing this module performs no network
I/O, secret resolution, or package installation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any, ClassVar

from .canonical import (
    CanonicalEncodingError,
    canonical_json,
    content_digest,
    deterministic_id,
    format_datetime,
    freeze_json,
    thaw_json,
)
from .errors import InvalidRequestError, SigningForbiddenError


ACQUISITION_REQUEST_SCHEMA_VERSION = "smart-contract-acquisition-request-v1"
ACQUISITION_RESULT_SCHEMA_VERSION = "smart-contract-acquisition-result-v1"
ARTIFACT_REF_SCHEMA_VERSION = "smart-contract-artifact-ref-v1"
CHAIN_REF_SCHEMA_VERSION = "smart-contract-chain-ref-v1"

_DIGEST = re.compile(r"^[a-z0-9][a-z0-9._-]*:[A-Za-z0-9_-]+$")
_CID = re.compile(r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7][a-z2-7]+)$")
_URN_ID = re.compile(
    r"^urn:smart-contract:[a-z][a-z0-9_-]*:sha256:[0-9a-f]{64}$"
)

SECRET_SAFE_MAX_DEPTH = 32
SECRET_SAFE_MAX_NODES = 10_000
SECRET_SAFE_MAX_COLLECTION_ITEMS = 2_048
SECRET_SAFE_MAX_STRING_CHARS = 1_048_576

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_FIELD_SEPARATOR = re.compile(r"[^a-z0-9]+")
_SECRET_FIELD_WORDS = frozenset(
    {
        "authorization",
        "bearer",
        "mnemonic",
        "passphrase",
        "passwd",
        "password",
        "secret",
    }
)
_SECRET_FIELD_NAMES = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "api_secret",
        "auth_token",
        "client_secret",
        "credential",
        "credentials",
        "private_key",
        "provider_secret",
        "recovery_phrase",
        "recovery_seed",
        "refresh_token",
        "seed",
        "seed_phrase",
        "session_token",
        "signing_key",
        "signing_material",
        "user_token",
        "wallet_seed",
    }
)
_FORBIDDEN_PUBLIC_SURFACE_FIELDS = frozenset(
    {
        "broadcast",
        "broadcast_url",
        "private_key",
        "seed",
        "seed_phrase",
        "sign",
        "signer",
        "signing_key",
        "signing_material",
        "submit_transaction",
    }
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(
        r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
        r"github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9])"
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
        r"AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9])"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|passphrase|api[_-]?key|private[_-]?key|"
        r"secret|mnemonic|seed[_ -]?phrase)\s*[:=]\s*\S{4,}"
    ),
    re.compile(r"(?i)^(?:vault|keyring|secret|env|file)://"),
    re.compile(r"(?i)^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
    re.compile(
        r"(?i)^[a-z0-9][a-z0-9_-]{15,}-(?:secret|password|passwd|passphrase)$"
    ),
)


class ArtifactKind(StrEnum):
    """Kinds of contract/program/script artifacts that may be acquired."""

    BYTECODE = "bytecode"
    CREATION_BYTECODE = "creation_bytecode"
    PROGRAM = "program"
    SCRIPT = "script"
    SOURCE = "source"
    ABI = "abi"
    IDL = "idl"
    METADATA = "metadata"
    BUILD_MANIFEST = "build_manifest"
    VERIFICATION_DOCUMENT = "verification_document"
    STATE_SNAPSHOT = "state_snapshot"
    OTHER = "other"


class AcquisitionStatus(StrEnum):
    """Structured acquisition outcome; each non-success status fails closed."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    INCONSISTENT = "inconsistent"
    POISONED = "poisoned"
    STALE = "stale"
    ERROR = "error"


class ProviderTrustMode(StrEnum):
    """How multiple provider responses are combined without silent selection."""

    SINGLE = "single"
    REQUIRE_AGREEMENT = "require_agreement"
    PRESERVE_DISAGREEMENT = "preserve_disagreement"


def _normalized_field_name(value: str) -> str:
    separated = _CAMEL_BOUNDARY.sub("_", value).casefold()
    return _FIELD_SEPARATOR.sub("_", separated).strip("_")


def _is_secret_field(value: str) -> bool:
    normalized = _normalized_field_name(value)
    if normalized in _SECRET_FIELD_NAMES:
        return True
    if normalized in _FORBIDDEN_PUBLIC_SURFACE_FIELDS:
        return True
    return bool(_SECRET_FIELD_WORDS.intersection(normalized.split("_")))


def _is_concrete_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def ensure_secret_safe(value: Any) -> None:
    """Reject secret-shaped or unbounded values before public serialization.

    The traversal has explicit depth, node, collection, and string budgets so
    untrusted metadata cannot turn secret inspection into an unbounded
    operation.  Errors omit field paths and values because both are
    attacker-controlled and may themselves contain the secret.
    """

    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > SECRET_SAFE_MAX_DEPTH or nodes > SECRET_SAFE_MAX_NODES:
            raise ValueError("smart-contract serialization security policy limit exceeded")

        if isinstance(item, str):
            if len(item) > SECRET_SAFE_MAX_STRING_CHARS:
                raise ValueError(
                    "smart-contract serialization security policy limit exceeded"
                )
            if _is_concrete_secret(item):
                raise ValueError(
                    "smart-contract serialization rejects concrete secret values"
                )
            return

        if isinstance(item, Mapping):
            if len(item) > SECRET_SAFE_MAX_COLLECTION_ITEMS:
                raise ValueError(
                    "smart-contract serialization security policy limit exceeded"
                )
            for key, child in item.items():
                if isinstance(key, str):
                    if len(key) > SECRET_SAFE_MAX_STRING_CHARS:
                        raise ValueError(
                            "smart-contract serialization security policy limit exceeded"
                        )
                    if _is_secret_field(key) or _is_concrete_secret(key):
                        raise SigningForbiddenError(
                            "public smart-contract records reject private-key "
                            "or signing surfaces"
                        )
                visit(child, depth + 1)
            return

        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray, memoryview)
        ):
            if len(item) > SECRET_SAFE_MAX_COLLECTION_ITEMS:
                raise ValueError(
                    "smart-contract serialization security policy limit exceeded"
                )
            for child in item:
                visit(child, depth + 1)
            return

        to_dict = getattr(item, "to_dict", None)
        if callable(to_dict):
            visit(to_dict(), depth + 1)

    visit(value, 0)


def assert_no_signing_surface(value: Any) -> None:
    """Public alias that fails closed on private-key or signing fields."""

    ensure_secret_safe(value)


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    if value != value.strip():
        raise InvalidRequestError(f"{name} must not have surrounding whitespace")
    return value


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRequestError(f"{name} must be a timezone-aware datetime")
    return value


def _digest(value: str, name: str) -> str:
    text = _required(value, name)
    if not _DIGEST.fullmatch(text):
        raise InvalidRequestError(f"{name} must be a tagged digest")
    return text


def _optional_cid(value: str, name: str) -> str:
    if not value:
        return ""
    text = _required(value, name)
    if not _CID.fullmatch(text):
        raise InvalidRequestError(f"{name} must be a CID")
    return text


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):
        raise InvalidRequestError("attributes must be a mapping")
    ensure_secret_safe(frozen)
    return frozen


def _as_enum(enum_cls: type[StrEnum], value: Any, name: str) -> StrEnum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise InvalidRequestError(f"unknown {name}: {value!r}") from exc
    raise InvalidRequestError(f"{name} must be a {enum_cls.__name__} value")


@dataclass(frozen=True, slots=True)
class ChainRef:
    """Chain and network coordinates for an acquisition request."""

    chain: str
    network: str
    chain_id: str = ""
    genesis_hash: str = ""
    namespace: str = ""
    schema_version: str = CHAIN_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain", _required(self.chain, "chain"))
        object.__setattr__(self, "network", _required(self.network, "network"))
        object.__setattr__(
            self, "chain_id", self.chain_id.strip() if self.chain_id else ""
        )
        object.__setattr__(
            self,
            "genesis_hash",
            self.genesis_hash.strip() if self.genesis_hash else "",
        )
        object.__setattr__(
            self, "namespace", self.namespace.strip() if self.namespace else ""
        )
        object.__setattr__(
            self, "schema_version", _required(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
            "namespace": self.namespace,
            "network": self.network,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChainRef":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ChainRef must be a mapping")
        return cls(
            chain=str(value.get("chain", "")),
            network=str(value.get("network", "")),
            chain_id=str(value.get("chain_id", "")),
            genesis_hash=str(value.get("genesis_hash", "")),
            namespace=str(value.get("namespace", "")),
            schema_version=str(
                value.get("schema_version", CHAIN_REF_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionBounds:
    """Hard per-operation resource ceilings for acquisition."""

    max_items: int = 64
    max_requests: int = 32
    max_response_bytes: int = 16 * 1024 * 1024
    max_redirects: int = 3
    max_archive_entries: int = 256
    max_depth: int = 8

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_items", _positive(self.max_items, "max_items"))
        object.__setattr__(
            self, "max_requests", _positive(self.max_requests, "max_requests")
        )
        object.__setattr__(
            self,
            "max_response_bytes",
            _positive(self.max_response_bytes, "max_response_bytes"),
        )
        object.__setattr__(
            self, "max_redirects", _non_negative(self.max_redirects, "max_redirects")
        )
        object.__setattr__(
            self,
            "max_archive_entries",
            _positive(self.max_archive_entries, "max_archive_entries"),
        )
        object.__setattr__(self, "max_depth", _positive(self.max_depth, "max_depth"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_archive_entries": self.max_archive_entries,
            "max_depth": self.max_depth,
            "max_items": self.max_items,
            "max_redirects": self.max_redirects,
            "max_requests": self.max_requests,
            "max_response_bytes": self.max_response_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcquisitionBounds":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("AcquisitionBounds must be a mapping")
        return cls(
            max_items=int(value.get("max_items", 64)),
            max_requests=int(value.get("max_requests", 32)),
            max_response_bytes=int(value.get("max_response_bytes", 16 * 1024 * 1024)),
            max_redirects=int(value.get("max_redirects", 3)),
            max_archive_entries=int(value.get("max_archive_entries", 256)),
            max_depth=int(value.get("max_depth", 8)),
        )


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    """Allowlisted, fail-closed provider selection and trust policy."""

    allowed_providers: frozenset[str] = field(default_factory=frozenset)
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    allowed_schemes: frozenset[str] = field(
        default_factory=lambda: frozenset({"https"})
    )
    trust_mode: ProviderTrustMode = ProviderTrustMode.PRESERVE_DISAGREEMENT
    require_content_digest: bool = True
    allow_http_loopback: bool = False
    max_providers: int = 4
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        providers = frozenset(
            _required(provider, "allowed_providers item")
            for provider in self.allowed_providers
        )
        hosts = frozenset(
            _required(host, "allowed_hosts item") for host in self.allowed_hosts
        )
        schemes = frozenset(
            _required(scheme, "allowed_schemes item").casefold()
            for scheme in self.allowed_schemes
        )
        if not schemes:
            raise InvalidRequestError("allowed_schemes must not be empty")
        for scheme in schemes:
            if scheme not in {"http", "https"}:
                raise InvalidRequestError(
                    f"unsupported URL scheme in provider policy: {scheme!r}"
                )
        # Pure open HTTP is rejected; loopback HTTP or HTTPS-first policies pass.
        if "http" in schemes and "https" not in schemes and not self.allow_http_loopback:
            raise InvalidRequestError(
                "http scheme requires allow_http_loopback=True or https"
            )
        object.__setattr__(self, "allowed_providers", providers)
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(
            self, "trust_mode", _as_enum(ProviderTrustMode, self.trust_mode, "trust_mode")
        )
        object.__setattr__(
            self, "max_providers", _positive(self.max_providers, "max_providers")
        )
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def permits_provider(self, provider_id: str) -> bool:
        """Return whether *provider_id* is allowlisted (empty list means open)."""

        if not self.allowed_providers:
            return True
        return provider_id in self.allowed_providers

    def permits_host(self, host: str) -> bool:
        """Return whether *host* is allowlisted (empty list means open)."""

        if not self.allowed_hosts:
            return True
        return host.casefold() in {item.casefold() for item in self.allowed_hosts}

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_http_loopback": self.allow_http_loopback,
            "allowed_hosts": sorted(self.allowed_hosts),
            "allowed_providers": sorted(self.allowed_providers),
            "allowed_schemes": sorted(self.allowed_schemes),
            "max_providers": self.max_providers,
            "metadata": thaw_json(self.metadata),
            "require_content_digest": self.require_content_digest,
            "trust_mode": self.trust_mode.value
            if isinstance(self.trust_mode, ProviderTrustMode)
            else str(self.trust_mode),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderPolicy":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ProviderPolicy must be a mapping")
        return cls(
            allowed_providers=frozenset(value.get("allowed_providers", ())),
            allowed_hosts=frozenset(value.get("allowed_hosts", ())),
            allowed_schemes=frozenset(value.get("allowed_schemes", ("https",))),
            trust_mode=value.get(
                "trust_mode", ProviderTrustMode.PRESERVE_DISAGREEMENT.value
            ),
            require_content_digest=bool(value.get("require_content_digest", True)),
            allow_http_loopback=bool(value.get("allow_http_loopback", False)),
            max_providers=int(value.get("max_providers", 4)),
            metadata=value.get("metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Content-addressed reference to acquired artifact bytes."""

    kind: ArtifactKind
    content_digest: str
    media_type: str
    byte_length: int
    content_cid: str = ""
    label: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ARTIFACT_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _as_enum(ArtifactKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "content_digest", _digest(self.content_digest, "content_digest")
        )
        object.__setattr__(self, "media_type", _required(self.media_type, "media_type"))
        object.__setattr__(
            self, "byte_length", _non_negative(self.byte_length, "byte_length")
        )
        object.__setattr__(
            self, "content_cid", _optional_cid(self.content_cid, "content_cid")
        )
        object.__setattr__(
            self, "label", self.label.strip() if self.label else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self, "schema_version", _required(self.schema_version, "schema_version")
        )
        ensure_secret_safe(self.to_dict())

    @property
    def record_id(self) -> str:
        return deterministic_id(
            "artifact-ref",
            {
                "byte_length": self.byte_length,
                "content_digest": self.content_digest,
                "kind": self.kind.value
                if isinstance(self.kind, ArtifactKind)
                else str(self.kind),
                "media_type": self.media_type,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "byte_length": self.byte_length,
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "kind": self.kind.value
            if isinstance(self.kind, ArtifactKind)
            else str(self.kind),
            "label": self.label,
            "media_type": self.media_type,
            "schema_version": self.schema_version,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRef":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ArtifactRef must be a mapping")
        return cls(
            kind=value.get("kind", ArtifactKind.OTHER.value),
            content_digest=str(value.get("content_digest", "")),
            media_type=str(value.get("media_type", "")),
            byte_length=int(value.get("byte_length", 0)),
            content_cid=str(value.get("content_cid", "")),
            label=str(value.get("label", "")),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", ARTIFACT_REF_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionProvenance:
    """Provider request/response binding for a read-only acquisition."""

    provider_id: str
    transport: str
    observed_at: datetime
    request_digest: str = ""
    response_digest: str = ""
    endpoint_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _required(self.provider_id, "provider_id")
        )
        object.__setattr__(self, "transport", _required(self.transport, "transport"))
        object.__setattr__(
            self, "observed_at", _aware(self.observed_at, "observed_at")
        )
        for name in ("request_digest", "response_digest"):
            raw = getattr(self, name)
            if raw:
                object.__setattr__(self, name, _digest(raw, name))
            else:
                object.__setattr__(self, name, "")
        object.__setattr__(
            self,
            "endpoint_id",
            self.endpoint_id.strip() if self.endpoint_id else "",
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "endpoint_id": self.endpoint_id,
            "observed_at": format_datetime(self.observed_at),
            "provider_id": self.provider_id,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "transport": self.transport,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcquisitionProvenance":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("AcquisitionProvenance must be a mapping")
        observed = value.get("observed_at")
        if isinstance(observed, str):
            text = observed.replace("Z", "+00:00")
            observed_at = datetime.fromisoformat(text)
        elif isinstance(observed, datetime):
            observed_at = observed
        else:
            raise InvalidRequestError("observed_at is required")
        return cls(
            provider_id=str(value.get("provider_id", "")),
            transport=str(value.get("transport", "")),
            observed_at=observed_at,
            request_digest=str(value.get("request_digest", "")),
            response_digest=str(value.get("response_digest", "")),
            endpoint_id=str(value.get("endpoint_id", "")),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ContractAcquisitionRequest:
    """Immutable, explicitly bounded request to acquire contract artifacts.

    Carries chain, network, artifact kind, resource bounds, cooperative
    cancellation token, deadline, and provider policy.  Acquisition is a
    read-only capability and never includes a signing or broadcast surface.
    """

    request_id: str
    chain: ChainRef
    artifact_kind: ArtifactKind
    locator: str
    bounds: AcquisitionBounds = field(default_factory=AcquisitionBounds)
    provider_policy: ProviderPolicy = field(default_factory=ProviderPolicy)
    deadline: datetime | None = None
    cancellation_token_id: str | None = None
    code_epoch: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ACQUISITION_REQUEST_SCHEMA_VERSION

    FORBIDDEN_FIELDS: ClassVar[frozenset[str]] = _FORBIDDEN_PUBLIC_SURFACE_FIELDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _required(self.request_id, "request_id")
        )
        if not isinstance(self.chain, ChainRef):
            object.__setattr__(
                self, "chain", ChainRef.from_dict(self.chain)  # type: ignore[arg-type]
            )
        object.__setattr__(
            self,
            "artifact_kind",
            _as_enum(ArtifactKind, self.artifact_kind, "artifact_kind"),
        )
        object.__setattr__(self, "locator", _required(self.locator, "locator"))
        if not isinstance(self.bounds, AcquisitionBounds):
            object.__setattr__(
                self, "bounds", AcquisitionBounds.from_dict(self.bounds)  # type: ignore[arg-type]
            )
        if not isinstance(self.provider_policy, ProviderPolicy):
            object.__setattr__(
                self,
                "provider_policy",
                ProviderPolicy.from_dict(self.provider_policy),  # type: ignore[arg-type]
            )
        if self.deadline is not None:
            object.__setattr__(self, "deadline", _aware(self.deadline, "deadline"))
        if self.cancellation_token_id is not None:
            object.__setattr__(
                self,
                "cancellation_token_id",
                _required(self.cancellation_token_id, "cancellation_token_id"),
            )
        object.__setattr__(
            self, "code_epoch", self.code_epoch.strip() if self.code_epoch else ""
        )
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self, "schema_version", _required(self.schema_version, "schema_version")
        )
        ensure_secret_safe(self.to_dict())

    @property
    def network(self) -> str:
        """Network coordinate from the embedded chain reference."""

        return self.chain.network

    @property
    def record_id(self) -> str:
        return deterministic_id(
            "acquisition-request",
            {
                "artifact_kind": self.artifact_kind.value
                if isinstance(self.artifact_kind, ArtifactKind)
                else str(self.artifact_kind),
                "chain": self.chain.to_dict(),
                "locator": self.locator,
                "request_id": self.request_id,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": self.artifact_kind.value
            if isinstance(self.artifact_kind, ArtifactKind)
            else str(self.artifact_kind),
            "attributes": thaw_json(self.attributes),
            "bounds": self.bounds.to_dict(),
            "cancellation_token_id": self.cancellation_token_id,
            "chain": self.chain.to_dict(),
            "code_epoch": self.code_epoch,
            "deadline": format_datetime(self.deadline)
            if self.deadline is not None
            else None,
            "locator": self.locator,
            "network": self.chain.network,
            "provider_policy": self.provider_policy.to_dict(),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractAcquisitionRequest":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ContractAcquisitionRequest must be a mapping")
        forbidden = sorted(set(value) & cls.FORBIDDEN_FIELDS)
        if forbidden:
            raise SigningForbiddenError(
                "public smart-contract records reject private-key or signing surfaces"
            )
        deadline = value.get("deadline")
        if isinstance(deadline, str) and deadline:
            deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        elif deadline is not None and not isinstance(deadline, datetime):
            raise InvalidRequestError("deadline must be a datetime or RFC 3339 string")
        return cls(
            request_id=str(value.get("request_id", "")),
            chain=ChainRef.from_dict(value.get("chain", {})),
            artifact_kind=value.get("artifact_kind", ArtifactKind.OTHER.value),
            locator=str(value.get("locator", "")),
            bounds=AcquisitionBounds.from_dict(value.get("bounds", {})),
            provider_policy=ProviderPolicy.from_dict(
                value.get("provider_policy", {})
            ),
            deadline=deadline,
            cancellation_token_id=value.get("cancellation_token_id"),
            code_epoch=str(value.get("code_epoch", "")),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", ACQUISITION_REQUEST_SCHEMA_VERSION)
            ),
        )


@dataclass(frozen=True, slots=True)
class ContractAcquisitionResult:
    """Immutable acquisition outcome with structured fail-closed statuses.

    Status values distinguish available, unavailable, partial, unsupported,
    inconsistent, poisoned, stale, and error outcomes.  Artifacts are
    content-addressed references only.
    """

    request_id: str
    status: AcquisitionStatus
    artifacts: tuple[ArtifactRef, ...] = ()
    provenances: tuple[AcquisitionProvenance, ...] = ()
    diagnostics: tuple[str, ...] = ()
    coverage_notes: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ACQUISITION_RESULT_SCHEMA_VERSION

    SUCCESS_STATUSES: ClassVar[frozenset[AcquisitionStatus]] = frozenset(
        {AcquisitionStatus.AVAILABLE, AcquisitionStatus.PARTIAL}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _required(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "status", _as_enum(AcquisitionStatus, self.status, "status")
        )
        artifacts = tuple(self.artifacts)
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, ArtifactRef):
                raise InvalidRequestError(
                    f"artifacts[{index}] must be an ArtifactRef"
                )
        object.__setattr__(self, "artifacts", artifacts)
        provenances = tuple(self.provenances)
        for index, provenance in enumerate(provenances):
            if not isinstance(provenance, AcquisitionProvenance):
                raise InvalidRequestError(
                    f"provenances[{index}] must be an AcquisitionProvenance"
                )
        object.__setattr__(self, "provenances", provenances)
        diagnostics = tuple(
            _required(item, "diagnostics item") for item in self.diagnostics
        )
        object.__setattr__(self, "diagnostics", diagnostics)
        coverage = tuple(
            _required(item, "coverage_notes item") for item in self.coverage_notes
        )
        object.__setattr__(self, "coverage_notes", coverage)
        object.__setattr__(self, "attributes", _freeze_mapping(self.attributes))
        object.__setattr__(
            self, "schema_version", _required(self.schema_version, "schema_version")
        )
        if (
            self.status == AcquisitionStatus.AVAILABLE
            and not self.artifacts
        ):
            raise InvalidRequestError(
                "available results must include at least one artifact"
            )
        if self.status == AcquisitionStatus.UNSUPPORTED and self.artifacts:
            raise InvalidRequestError(
                "unsupported results must not include artifacts"
            )
        ensure_secret_safe(self.to_dict())

    @property
    def is_success(self) -> bool:
        status = (
            self.status
            if isinstance(self.status, AcquisitionStatus)
            else AcquisitionStatus(str(self.status))
        )
        return status in self.SUCCESS_STATUSES

    @property
    def record_id(self) -> str:
        return deterministic_id(
            "acquisition-result",
            {
                "artifact_digests": [item.content_digest for item in self.artifacts],
                "request_id": self.request_id,
                "status": self.status.value
                if isinstance(self.status, AcquisitionStatus)
                else str(self.status),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "attributes": thaw_json(self.attributes),
            "coverage_notes": list(self.coverage_notes),
            "diagnostics": list(self.diagnostics),
            "provenances": [item.to_dict() for item in self.provenances],
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, AcquisitionStatus)
            else str(self.status),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractAcquisitionResult":
        if not isinstance(value, Mapping):
            raise InvalidRequestError("ContractAcquisitionResult must be a mapping")
        forbidden = sorted(
            set(value) & ContractAcquisitionRequest.FORBIDDEN_FIELDS
        )
        if forbidden:
            raise SigningForbiddenError(
                "public smart-contract records reject private-key or signing surfaces"
            )
        artifacts = tuple(
            ArtifactRef.from_dict(item) for item in value.get("artifacts", ())
        )
        provenances = tuple(
            AcquisitionProvenance.from_dict(item)
            for item in value.get("provenances", ())
        )
        return cls(
            request_id=str(value.get("request_id", "")),
            status=value.get("status", AcquisitionStatus.ERROR.value),
            artifacts=artifacts,
            provenances=provenances,
            diagnostics=tuple(value.get("diagnostics", ())),
            coverage_notes=tuple(value.get("coverage_notes", ())),
            attributes=value.get("attributes", {}),
            schema_version=str(
                value.get("schema_version", ACQUISITION_RESULT_SCHEMA_VERSION)
            ),
        )


def unavailable_result(
    request_id: str,
    *,
    diagnostics: Sequence[str] = (),
) -> ContractAcquisitionResult:
    """Build a structured unavailable acquisition result."""

    return ContractAcquisitionResult(
        request_id=request_id,
        status=AcquisitionStatus.UNAVAILABLE,
        diagnostics=tuple(diagnostics),
    )


def error_result(
    request_id: str,
    *,
    diagnostics: Sequence[str] = (),
) -> ContractAcquisitionResult:
    """Build a structured error acquisition result."""

    return ContractAcquisitionResult(
        request_id=request_id,
        status=AcquisitionStatus.ERROR,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "ACQUISITION_REQUEST_SCHEMA_VERSION",
    "ACQUISITION_RESULT_SCHEMA_VERSION",
    "ARTIFACT_REF_SCHEMA_VERSION",
    "CHAIN_REF_SCHEMA_VERSION",
    "AcquisitionBounds",
    "AcquisitionProvenance",
    "AcquisitionStatus",
    "ArtifactKind",
    "ArtifactRef",
    "ChainRef",
    "ContractAcquisitionRequest",
    "ContractAcquisitionResult",
    "ProviderPolicy",
    "ProviderTrustMode",
    "SECRET_SAFE_MAX_COLLECTION_ITEMS",
    "SECRET_SAFE_MAX_DEPTH",
    "SECRET_SAFE_MAX_NODES",
    "SECRET_SAFE_MAX_STRING_CHARS",
    "assert_no_signing_surface",
    "ensure_secret_safe",
    "error_result",
    "unavailable_result",
]
