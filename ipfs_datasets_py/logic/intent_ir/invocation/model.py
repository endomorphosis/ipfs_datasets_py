"""Canonical, immutable invocation intent envelope (InvocationIntentEnvelope@1).

This module binds the execution context of a proposed SkillCenter skill, free-form
prompt, or MCP tool call **before** Legal/Security evaluation and dispatch.

Non-goals (fail-closed invariants):
- Never executes skill text, prompt bodies, or MCP tools.
- Never stores raw secrets, auth tokens, or unrestricted private arguments.
- Never mutates after construction; identity is domain-separated and stable.
- Unknown schema versions, NaN/unbounded structures, and identity drift fail closed.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable

from ...ir_core.canonical import (
    CollectionSchema,
    CollectionSemantics,
    canonical_json_bytes,
)
from ...ir_core.identity import CanonicalIdentity, canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json,
    freeze_json_mapping,
    thaw_json,
)


INVOCATION_ENVELOPE_INTERFACE: Final = "InvocationIntentEnvelope@1"
INVOCATION_ENVELOPE_SCHEMA_VERSION: Final = "invocation-intent-envelope/v1"
INVOCATION_ENVELOPE_IDENTITY_DOMAIN: Final = "invocation-intent"
ARGUMENT_COMMITMENT_DOMAIN: Final = "invocation-intent.argument-commitment/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)

MAX_JSON_DEPTH: Final = 32
MAX_JSON_NODES: Final = 10_000
MAX_COLLECTION_ITEMS: Final = 1_024
MAX_STRING_CHARS: Final = 16_384
MAX_IDENTIFIER_CHARS: Final = 256

# Keys whose values must be secret references or redaction tokens, never raw material.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(^|[_.-])(password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|bearer|credential|session[_-]?id)([_.-]|$)"
)
_REDACTED_VALUE_RE = re.compile(
    r"(?i)^(\[REDACTED\]|<REDACTED>|REDACTED|\*{3,}|secret:[A-Za-z0-9._:/-]{1,255}"
    r"|ref:secret:[A-Za-z0-9._:/-]{1,255}|\$\{SECRET:[A-Za-z0-9._:/-]+\}$)$"
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
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
    re.compile(r"(?i)\b(?:password|api[_-]?key|secret)\s*[:=]\s*\S{8,}"),
)


class InvocationEnvelopeValidationError(ValueError):
    """Raised when an invocation envelope violates its canonical contract."""


class InvocationKind(str, Enum):
    """Top-level source shape of a proposed invocation."""

    SKILLCENTER = "skillcenter"
    PROMPT = "prompt"
    MCP_TOOL = "mcp_tool"
    COMPOSITE = "composite"
    UNSPECIFIED = "unspecified"


class DiagnosticSeverity(str, Enum):
    """Operational impact of one envelope diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class ScopeKind(str, Enum):
    """Category of a scoped resource or capability claim."""

    ACTION = "action"
    EFFECT = "effect"
    CAPABILITY = "capability"
    ASSET = "asset"
    RESOURCE = "resource"
    DATA = "data"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    SUBPROCESS = "subprocess"
    SECRET_REF = "secret_ref"


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
        raise InvocationEnvelopeValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise InvocationEnvelopeValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise InvocationEnvelopeValidationError(
            f"{name} must not have surrounding whitespace"
        )
    if len(value) > max_chars:
        raise InvocationEnvelopeValidationError(
            f"{name} exceeds maximum length of {max_chars} characters"
        )
    _reject_raw_secrets(value, name)
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(normalized):
        raise InvocationEnvelopeValidationError(f"{name} is not a stable identifier")
    return normalized


def _optional_identifier(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, name)


def _sha256_hex(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=64)
    if not _SHA256_HEX_RE.fullmatch(text):
        raise InvocationEnvelopeValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
    return text


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
    if not _DIGEST_RE.fullmatch(text):
        raise InvocationEnvelopeValidationError(
            f"{name} must be a sha256:<64-hex> digest"
        )
    return text


def _optional_digest(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _digest(value, name)


def _timestamp(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if value in (None, ""):
        if allow_empty:
            return ""
        raise InvocationEnvelopeValidationError(f"{name} must be a non-empty timestamp")
    text = _text(value, name, max_chars=64)
    if not _ISO8601_RE.fullmatch(text):
        raise InvocationEnvelopeValidationError(
            f"{name} must be an ISO-8601 UTC/offset timestamp"
        )
    return text


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvocationEnvelopeValidationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InvocationEnvelopeValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _enum_value(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise InvocationEnvelopeValidationError(
            f"unsupported {name}: {value!r}; expected one of: {choices}"
        ) from exc


def _ids(
    values: Sequence[str] | None,
    name: str,
    *,
    max_items: int = MAX_COLLECTION_ITEMS,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise InvocationEnvelopeValidationError(f"{name} must be a sequence")
    if len(values) > max_items:
        raise InvocationEnvelopeValidationError(
            f"{name} exceeds maximum of {max_items} items"
        )
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise InvocationEnvelopeValidationError(f"{name} values must be unique")
    return result


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        frozen = freeze_json_mapping(value)
    except ProvenanceValidationError as exc:
        raise InvocationEnvelopeValidationError(str(exc)) from exc
    _bound_json(frozen, name="attributes")
    _reject_secrets_in_json(frozen, path="attributes")
    return frozen


def _payload(value: Any, name: str = "payload") -> Any:
    try:
        frozen = freeze_json(value)
    except ProvenanceValidationError as exc:
        raise InvocationEnvelopeValidationError(str(exc)) from exc
    _bound_json(frozen, name=name)
    _reject_secrets_in_json(frozen, path=name)
    return frozen


def _bound_json(
    value: Any,
    *,
    name: str,
    depth: int = 0,
    counter: list[int] | None = None,
) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES:
        raise InvocationEnvelopeValidationError(
            f"{name} exceeds maximum of {MAX_JSON_NODES} JSON nodes"
        )
    if depth > MAX_JSON_DEPTH:
        raise InvocationEnvelopeValidationError(
            f"{name} exceeds maximum JSON depth of {MAX_JSON_DEPTH}"
        )
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvocationEnvelopeValidationError(
                f"{name} must not contain NaN or infinite numbers"
            )
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        raise InvocationEnvelopeValidationError(
            f"{name} string exceeds maximum length of {MAX_STRING_CHARS}"
        )
    if isinstance(value, Mapping):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise InvocationEnvelopeValidationError(
                f"{name} mapping exceeds maximum of {MAX_COLLECTION_ITEMS} keys"
            )
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvocationEnvelopeValidationError(
                    f"{name} keys must be strings"
                )
            _bound_json(
                item, name=f"{name}.{key}", depth=depth + 1, counter=counter
            )
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise InvocationEnvelopeValidationError(
                f"{name} sequence exceeds maximum of {MAX_COLLECTION_ITEMS} items"
            )
        for index, item in enumerate(value):
            _bound_json(
                item, name=f"{name}[{index}]", depth=depth + 1, counter=counter
            )


def _reject_raw_secrets(text: str, name: str) -> None:
    # Explicit redaction tokens and secret provider references are allowed.
    if _REDACTED_VALUE_RE.fullmatch(text):
        return
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise InvocationEnvelopeValidationError(
                f"{name} contains a raw secret pattern and is rejected"
            )


def _reject_secrets_in_json(value: Any, *, path: str) -> None:
    if isinstance(value, str):
        _reject_raw_secrets(value, path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key):
                if not isinstance(item, str) or not _REDACTED_VALUE_RE.fullmatch(
                    item
                ):
                    raise InvocationEnvelopeValidationError(
                        f"{child} must be a redacted token or secret reference, "
                        "not raw secret material"
                    )
            _reject_secrets_in_json(item, path=child)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _reject_secrets_in_json(item, path=f"{path}[{index}]")


def commit_redacted_arguments(redacted_arguments: Mapping[str, Any] | Any) -> str:
    """Return a domain-separated sha256 commitment over redacted arguments."""

    payload = {
        "domain": ARGUMENT_COMMITMENT_DOMAIN,
        "redacted_arguments": thaw_json(_payload(redacted_arguments, "redacted_arguments")),
    }
    digest = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Nested records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Typed reference to the source of a proposed invocation."""

    kind: InvocationKind
    source_ref: str
    source_id: str = ""
    source_revision: str = ""
    content_sha256: str = ""
    content_cid: str = ""
    intent_document_id: str = ""
    formalization_artifact_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum_value(InvocationKind, self.kind, "source.kind")
        )
        object.__setattr__(
            self, "source_ref", _identifier(self.source_ref, "source.source_ref")
        )
        object.__setattr__(
            self,
            "source_id",
            _optional_identifier(self.source_id, "source.source_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _text(self.source_revision, "source.source_revision", allow_empty=True),
        )
        if self.content_sha256:
            object.__setattr__(
                self,
                "content_sha256",
                _sha256_hex(self.content_sha256, "source.content_sha256"),
            )
        object.__setattr__(
            self,
            "content_cid",
            _text(self.content_cid, "source.content_cid", allow_empty=True),
        )
        object.__setattr__(
            self,
            "intent_document_id",
            _optional_identifier(
                self.intent_document_id, "source.intent_document_id"
            ),
        )
        object.__setattr__(
            self,
            "formalization_artifact_id",
            _optional_identifier(
                self.formalization_artifact_id,
                "source.formalization_artifact_id",
            ),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "content_cid": self.content_cid,
            "content_sha256": self.content_sha256,
            "formalization_artifact_id": self.formalization_artifact_id,
            "intent_document_id": self.intent_document_id,
            "kind": self.kind.value,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceBinding":
        value = _as_mapping(value, "source")
        _known_fields(
            value,
            frozenset(
                {
                    "kind",
                    "source_ref",
                    "source_id",
                    "source_revision",
                    "content_sha256",
                    "content_cid",
                    "intent_document_id",
                    "formalization_artifact_id",
                    "attributes",
                }
            ),
            "source",
        )
        return cls(
            kind=value.get("kind", InvocationKind.UNSPECIFIED),
            source_ref=value.get("source_ref", ""),
            source_id=value.get("source_id", ""),
            source_revision=value.get("source_revision", ""),
            content_sha256=value.get("content_sha256", ""),
            content_cid=value.get("content_cid", ""),
            intent_document_id=value.get("intent_document_id", ""),
            formalization_artifact_id=value.get("formalization_artifact_id", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ActorBinding:
    """The principal that initiates or is held responsible for the invocation."""

    actor_id: str
    kind: str = "principal"
    display_name: str = ""
    trust_domain: str = ""
    subject_attributes: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "actor_id", _identifier(self.actor_id, "actor.actor_id")
        )
        object.__setattr__(self, "kind", _text(self.kind, "actor.kind"))
        object.__setattr__(
            self,
            "display_name",
            _text(self.display_name, "actor.display_name", allow_empty=True),
        )
        object.__setattr__(
            self,
            "trust_domain",
            _optional_identifier(self.trust_domain, "actor.trust_domain"),
        )
        object.__setattr__(
            self, "subject_attributes", _attributes(self.subject_attributes)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "attributes": thaw_json(self.attributes),
            "display_name": self.display_name,
            "kind": self.kind,
            "subject_attributes": thaw_json(self.subject_attributes),
            "trust_domain": self.trust_domain,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActorBinding":
        value = _as_mapping(value, "actor")
        _known_fields(
            value,
            frozenset(
                {
                    "actor_id",
                    "kind",
                    "display_name",
                    "trust_domain",
                    "subject_attributes",
                    "attributes",
                }
            ),
            "actor",
        )
        return cls(
            actor_id=value.get("actor_id", ""),
            kind=value.get("kind", "principal"),
            display_name=value.get("display_name", ""),
            trust_domain=value.get("trust_domain", ""),
            subject_attributes=value.get("subject_attributes", {}),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class DelegationLink:
    """One hop in a delegator chain (from → to)."""

    link_id: str
    from_actor_id: str
    to_actor_id: str
    capability_ids: tuple[str, ...] = ()
    evidence_ref: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "link_id", _identifier(self.link_id, "delegation.link_id")
        )
        object.__setattr__(
            self,
            "from_actor_id",
            _identifier(self.from_actor_id, "delegation.from_actor_id"),
        )
        object.__setattr__(
            self,
            "to_actor_id",
            _identifier(self.to_actor_id, "delegation.to_actor_id"),
        )
        if self.from_actor_id == self.to_actor_id:
            raise InvocationEnvelopeValidationError(
                "delegation link from_actor_id and to_actor_id must differ"
            )
        object.__setattr__(
            self,
            "capability_ids",
            _ids(self.capability_ids, "delegation.capability_ids"),
        )
        object.__setattr__(
            self,
            "evidence_ref",
            _optional_identifier(self.evidence_ref, "delegation.evidence_ref"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "capability_ids": list(self.capability_ids),
            "evidence_ref": self.evidence_ref,
            "from_actor_id": self.from_actor_id,
            "link_id": self.link_id,
            "to_actor_id": self.to_actor_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DelegationLink":
        value = _as_mapping(value, "delegation")
        _known_fields(
            value,
            frozenset(
                {
                    "link_id",
                    "from_actor_id",
                    "to_actor_id",
                    "capability_ids",
                    "evidence_ref",
                    "attributes",
                }
            ),
            "delegation",
        )
        return cls(
            link_id=value.get("link_id", ""),
            from_actor_id=value.get("from_actor_id", ""),
            to_actor_id=value.get("to_actor_id", ""),
            capability_ids=tuple(value.get("capability_ids", ())),
            evidence_ref=value.get("evidence_ref", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class AudienceBinding:
    """Intended dispatcher/consumer of an authorized capability."""

    audience_id: str
    kind: str = "dispatcher"
    deployment_id: str = ""
    trust_domain: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "audience_id",
            _identifier(self.audience_id, "audience.audience_id"),
        )
        object.__setattr__(self, "kind", _text(self.kind, "audience.kind"))
        object.__setattr__(
            self,
            "deployment_id",
            _optional_identifier(self.deployment_id, "audience.deployment_id"),
        )
        object.__setattr__(
            self,
            "trust_domain",
            _optional_identifier(self.trust_domain, "audience.trust_domain"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "audience_id": self.audience_id,
            "deployment_id": self.deployment_id,
            "kind": self.kind,
            "trust_domain": self.trust_domain,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AudienceBinding":
        value = _as_mapping(value, "audience")
        _known_fields(
            value,
            frozenset(
                {
                    "audience_id",
                    "kind",
                    "deployment_id",
                    "trust_domain",
                    "attributes",
                }
            ),
            "audience",
        )
        return cls(
            audience_id=value.get("audience_id", ""),
            kind=value.get("kind", "dispatcher"),
            deployment_id=value.get("deployment_id", ""),
            trust_domain=value.get("trust_domain", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ToolBinding:
    """Concrete tool/server/schema/version identity for the proposed call."""

    tool_id: str
    tool_name: str = ""
    tool_version: str = ""
    server_id: str = ""
    server_name: str = ""
    transport_peer: str = ""
    input_schema_id: str = ""
    input_schema_sha256: str = ""
    output_schema_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tool_id", _identifier(self.tool_id, "tool.tool_id")
        )
        object.__setattr__(
            self,
            "tool_name",
            _text(self.tool_name, "tool.tool_name", allow_empty=True),
        )
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool.tool_version", allow_empty=True),
        )
        object.__setattr__(
            self, "server_id", _optional_identifier(self.server_id, "tool.server_id")
        )
        object.__setattr__(
            self,
            "server_name",
            _text(self.server_name, "tool.server_name", allow_empty=True),
        )
        object.__setattr__(
            self,
            "transport_peer",
            _text(self.transport_peer, "tool.transport_peer", allow_empty=True),
        )
        object.__setattr__(
            self,
            "input_schema_id",
            _optional_identifier(self.input_schema_id, "tool.input_schema_id"),
        )
        if self.input_schema_sha256:
            object.__setattr__(
                self,
                "input_schema_sha256",
                _sha256_hex(self.input_schema_sha256, "tool.input_schema_sha256"),
            )
        object.__setattr__(
            self,
            "output_schema_id",
            _optional_identifier(self.output_schema_id, "tool.output_schema_id"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "input_schema_id": self.input_schema_id,
            "input_schema_sha256": self.input_schema_sha256,
            "output_schema_id": self.output_schema_id,
            "server_id": self.server_id,
            "server_name": self.server_name,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "transport_peer": self.transport_peer,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolBinding":
        value = _as_mapping(value, "tool")
        _known_fields(
            value,
            frozenset(
                {
                    "tool_id",
                    "tool_name",
                    "tool_version",
                    "server_id",
                    "server_name",
                    "transport_peer",
                    "input_schema_id",
                    "input_schema_sha256",
                    "output_schema_id",
                    "attributes",
                }
            ),
            "tool",
        )
        return cls(
            tool_id=value.get("tool_id", ""),
            tool_name=value.get("tool_name", ""),
            tool_version=value.get("tool_version", ""),
            server_id=value.get("server_id", ""),
            server_name=value.get("server_name", ""),
            transport_peer=value.get("transport_peer", ""),
            input_schema_id=value.get("input_schema_id", ""),
            input_schema_sha256=value.get("input_schema_sha256", ""),
            output_schema_id=value.get("output_schema_id", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class ArgumentCommitment:
    """Domain-separated commitment plus a secret-free redacted display view."""

    commitment: str
    algorithm: str = "sha256"
    domain: str = ARGUMENT_COMMITMENT_DOMAIN
    redacted_arguments: Mapping[str, Any] = field(default_factory=dict)
    secret_refs: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "commitment", _digest(self.commitment, "arguments.commitment")
        )
        object.__setattr__(
            self, "algorithm", _text(self.algorithm, "arguments.algorithm")
        )
        if self.algorithm != "sha256":
            raise InvocationEnvelopeValidationError(
                f"unsupported argument commitment algorithm: {self.algorithm!r}"
            )
        object.__setattr__(
            self, "domain", _text(self.domain, "arguments.domain")
        )
        if self.domain != ARGUMENT_COMMITMENT_DOMAIN:
            raise InvocationEnvelopeValidationError(
                f"unsupported argument commitment domain: {self.domain!r}"
            )
        redacted = _attributes(self.redacted_arguments)
        object.__setattr__(self, "redacted_arguments", redacted)
        expected = commit_redacted_arguments(redacted)
        if self.commitment != expected:
            raise InvocationEnvelopeValidationError(
                "argument commitment does not match redacted arguments "
                "(identity drift or raw-secret stripping required)"
            )
        object.__setattr__(
            self, "secret_refs", _ids(self.secret_refs, "arguments.secret_refs")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "attributes": thaw_json(self.attributes),
            "commitment": self.commitment,
            "domain": self.domain,
            "redacted_arguments": thaw_json(self.redacted_arguments),
            "secret_refs": list(self.secret_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArgumentCommitment":
        value = _as_mapping(value, "arguments")
        _known_fields(
            value,
            frozenset(
                {
                    "commitment",
                    "algorithm",
                    "domain",
                    "redacted_arguments",
                    "secret_refs",
                    "attributes",
                }
            ),
            "arguments",
        )
        redacted = value.get("redacted_arguments", {})
        commitment = value.get("commitment")
        if not commitment:
            commitment = commit_redacted_arguments(redacted)
        return cls(
            commitment=commitment,
            algorithm=value.get("algorithm", "sha256"),
            domain=value.get("domain", ARGUMENT_COMMITMENT_DOMAIN),
            redacted_arguments=redacted,
            secret_refs=tuple(value.get("secret_refs", ())),
            attributes=value.get("attributes", {}),
        )

    @classmethod
    def from_redacted(
        cls,
        redacted_arguments: Mapping[str, Any],
        *,
        secret_refs: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> "ArgumentCommitment":
        """Build a commitment from a secret-free redacted argument map."""

        return cls(
            commitment=commit_redacted_arguments(redacted_arguments),
            redacted_arguments=redacted_arguments,
            secret_refs=tuple(secret_refs),
            attributes=attributes or {},
        )


@dataclass(frozen=True, slots=True)
class ScopeEntry:
    """One scoped action, effect, capability, asset, resource, or channel claim."""

    entry_id: str
    kind: ScopeKind
    value: str
    description: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_id", _identifier(self.entry_id, "scope.entry_id")
        )
        object.__setattr__(
            self, "kind", _enum_value(ScopeKind, self.kind, "scope.kind")
        )
        object.__setattr__(self, "value", _text(self.value, "scope.value"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, "scope.description", allow_empty=True),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "description": self.description,
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScopeEntry":
        value = _as_mapping(value, "scope entry")
        _known_fields(
            value,
            frozenset({"entry_id", "kind", "value", "description", "attributes"}),
            "scope entry",
        )
        return cls(
            entry_id=value.get("entry_id", ""),
            kind=value.get("kind", ScopeKind.ACTION),
            value=value.get("value", ""),
            description=value.get("description", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class InvocationScope:
    """Bundled scopes for actions, effects, capabilities, and system access."""

    actions: tuple[ScopeEntry, ...] = ()
    effects: tuple[ScopeEntry, ...] = ()
    capabilities: tuple[ScopeEntry, ...] = ()
    assets: tuple[ScopeEntry, ...] = ()
    resources: tuple[ScopeEntry, ...] = ()
    data_classes: tuple[ScopeEntry, ...] = ()
    network: tuple[ScopeEntry, ...] = ()
    filesystem: tuple[ScopeEntry, ...] = ()
    subprocess: tuple[ScopeEntry, ...] = ()
    secret_refs: tuple[ScopeEntry, ...] = ()

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "actions",
        "effects",
        "capabilities",
        "assets",
        "resources",
        "data_classes",
        "network",
        "filesystem",
        "subprocess",
        "secret_refs",
    )

    _EXPECTED_KIND: ClassVar[Mapping[str, ScopeKind]] = MappingProxyType(
        {
            "actions": ScopeKind.ACTION,
            "effects": ScopeKind.EFFECT,
            "capabilities": ScopeKind.CAPABILITY,
            "assets": ScopeKind.ASSET,
            "resources": ScopeKind.RESOURCE,
            "data_classes": ScopeKind.DATA,
            "network": ScopeKind.NETWORK,
            "filesystem": ScopeKind.FILESYSTEM,
            "subprocess": ScopeKind.SUBPROCESS,
            "secret_refs": ScopeKind.SECRET_REF,
        }
    )

    def __post_init__(self) -> None:
        seen_ids: set[str] = set()
        for name in self._FIELDS:
            raw = getattr(self, name)
            if isinstance(raw, (str, bytes, bytearray)) or not isinstance(
                raw, Sequence
            ):
                raise InvocationEnvelopeValidationError(f"scope.{name} must be a sequence")
            if len(raw) > MAX_COLLECTION_ITEMS:
                raise InvocationEnvelopeValidationError(
                    f"scope.{name} exceeds maximum of {MAX_COLLECTION_ITEMS} items"
                )
            converted: list[ScopeEntry] = []
            expected = self._EXPECTED_KIND[name]
            for item in raw:
                entry = (
                    item
                    if isinstance(item, ScopeEntry)
                    else ScopeEntry.from_dict(_as_mapping(item, f"scope.{name}"))
                )
                if entry.kind is not expected:
                    raise InvocationEnvelopeValidationError(
                        f"scope.{name} entries must have kind {expected.value}"
                    )
                if entry.entry_id in seen_ids:
                    raise InvocationEnvelopeValidationError(
                        f"duplicate scope entry_id: {entry.entry_id}"
                    )
                seen_ids.add(entry.entry_id)
                converted.append(entry)
            object.__setattr__(self, name, tuple(converted))

    def to_dict(self) -> dict[str, Any]:
        return {
            name: [item.to_dict() for item in getattr(self, name)]
            for name in self._FIELDS
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "InvocationScope":
        if value is None:
            return cls()
        value = _as_mapping(value, "scope")
        _known_fields(value, frozenset(cls._FIELDS), "scope")
        kwargs = {
            name: tuple(
                ScopeEntry.from_dict(item) for item in value.get(name, ())
            )
            for name in cls._FIELDS
        }
        return cls(**kwargs)


@dataclass(frozen=True, slots=True)
class PurposeContext:
    """Purpose, jurisdiction, location, consent, and evaluation time."""

    purpose: str = ""
    jurisdiction: str = ""
    location: str = ""
    legal_basis: str = ""
    consent_claim: str = ""
    effective_time: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "purpose",
            "jurisdiction",
            "location",
            "legal_basis",
            "consent_claim",
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"purpose.{name}", allow_empty=True),
            )
        object.__setattr__(
            self,
            "effective_time",
            _timestamp(
                self.effective_time, "purpose.effective_time", allow_empty=True
            ),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "consent_claim": self.consent_claim,
            "effective_time": self.effective_time,
            "jurisdiction": self.jurisdiction,
            "legal_basis": self.legal_basis,
            "location": self.location,
            "purpose": self.purpose,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "PurposeContext":
        if value is None:
            return cls()
        value = _as_mapping(value, "purpose")
        _known_fields(
            value,
            frozenset(
                {
                    "purpose",
                    "jurisdiction",
                    "location",
                    "legal_basis",
                    "consent_claim",
                    "effective_time",
                    "attributes",
                }
            ),
            "purpose",
        )
        return cls(
            purpose=value.get("purpose", ""),
            jurisdiction=value.get("jurisdiction", ""),
            location=value.get("location", ""),
            legal_basis=value.get("legal_basis", ""),
            consent_claim=value.get("consent_claim", ""),
            effective_time=value.get("effective_time", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    """Sandbox and runtime facts from an attested environment observer."""

    environment_id: str = ""
    deployment_id: str = ""
    snapshot_digest: str = ""
    sandbox_class: str = ""
    observer_id: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_id",
            _optional_identifier(self.environment_id, "environment.environment_id"),
        )
        object.__setattr__(
            self,
            "deployment_id",
            _optional_identifier(self.deployment_id, "environment.deployment_id"),
        )
        object.__setattr__(
            self,
            "snapshot_digest",
            _optional_digest(self.snapshot_digest, "environment.snapshot_digest"),
        )
        object.__setattr__(
            self,
            "sandbox_class",
            _text(self.sandbox_class, "environment.sandbox_class", allow_empty=True),
        )
        object.__setattr__(
            self,
            "observer_id",
            _optional_identifier(self.observer_id, "environment.observer_id"),
        )
        object.__setattr__(self, "facts", _attributes(self.facts))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "deployment_id": self.deployment_id,
            "environment_id": self.environment_id,
            "facts": thaw_json(self.facts),
            "observer_id": self.observer_id,
            "sandbox_class": self.sandbox_class,
            "snapshot_digest": self.snapshot_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "EnvironmentBinding":
        if value is None:
            return cls()
        value = _as_mapping(value, "environment")
        _known_fields(
            value,
            frozenset(
                {
                    "environment_id",
                    "deployment_id",
                    "snapshot_digest",
                    "sandbox_class",
                    "observer_id",
                    "facts",
                    "attributes",
                }
            ),
            "environment",
        )
        return cls(
            environment_id=value.get("environment_id", ""),
            deployment_id=value.get("deployment_id", ""),
            snapshot_digest=value.get("snapshot_digest", ""),
            sandbox_class=value.get("sandbox_class", ""),
            observer_id=value.get("observer_id", ""),
            facts=value.get("facts", {}),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class RollbackStep:
    """One declared rollback or compensation step (not an execution plan)."""

    step_id: str
    description: str
    action_ref: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step_id", _identifier(self.step_id, "rollback.step_id")
        )
        object.__setattr__(
            self, "description", _text(self.description, "rollback.description")
        )
        object.__setattr__(
            self,
            "action_ref",
            _optional_identifier(self.action_ref, "rollback.action_ref"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_ref": self.action_ref,
            "attributes": thaw_json(self.attributes),
            "description": self.description,
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RollbackStep":
        value = _as_mapping(value, "rollback step")
        _known_fields(
            value,
            frozenset({"step_id", "description", "action_ref", "attributes"}),
            "rollback step",
        )
        return cls(
            step_id=value.get("step_id", ""),
            description=value.get("description", ""),
            action_ref=value.get("action_ref", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class VerificationStep:
    """One declared verification or postcondition check."""

    step_id: str
    description: str
    predicate: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step_id", _identifier(self.step_id, "verification.step_id")
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "verification.description"),
        )
        object.__setattr__(
            self,
            "predicate",
            _text(self.predicate, "verification.predicate", allow_empty=True),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "description": self.description,
            "predicate": self.predicate,
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationStep":
        value = _as_mapping(value, "verification step")
        _known_fields(
            value,
            frozenset({"step_id", "description", "predicate", "attributes"}),
            "verification step",
        )
        return cls(
            step_id=value.get("step_id", ""),
            description=value.get("description", ""),
            predicate=value.get("predicate", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class PolicyRequirements:
    """Policy profile and corpus snapshot requirements for evaluation."""

    policy_profile: str = ""
    policy_root: str = ""
    corpus_roots: tuple[str, ...] = ()
    revocation_root: str = ""
    coverage_profile: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_profile",
            _optional_identifier(self.policy_profile, "policy.policy_profile"),
        )
        object.__setattr__(
            self,
            "policy_root",
            _text(self.policy_root, "policy.policy_root", allow_empty=True),
        )
        if isinstance(self.corpus_roots, (str, bytes, bytearray)) or not isinstance(
            self.corpus_roots, Sequence
        ):
            raise InvocationEnvelopeValidationError(
                "policy.corpus_roots must be a sequence"
            )
        if len(self.corpus_roots) > MAX_COLLECTION_ITEMS:
            raise InvocationEnvelopeValidationError(
                "policy.corpus_roots exceeds maximum collection size"
            )
        roots = tuple(
            _text(item, "policy.corpus_roots") for item in self.corpus_roots
        )
        if len(roots) != len(set(roots)):
            raise InvocationEnvelopeValidationError(
                "policy.corpus_roots values must be unique"
            )
        object.__setattr__(self, "corpus_roots", roots)
        object.__setattr__(
            self,
            "revocation_root",
            _text(self.revocation_root, "policy.revocation_root", allow_empty=True),
        )
        object.__setattr__(
            self,
            "coverage_profile",
            _optional_identifier(
                self.coverage_profile, "policy.coverage_profile"
            ),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "corpus_roots": list(self.corpus_roots),
            "coverage_profile": self.coverage_profile,
            "policy_profile": self.policy_profile,
            "policy_root": self.policy_root,
            "revocation_root": self.revocation_root,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "PolicyRequirements":
        if value is None:
            return cls()
        value = _as_mapping(value, "policy")
        _known_fields(
            value,
            frozenset(
                {
                    "policy_profile",
                    "policy_root",
                    "corpus_roots",
                    "revocation_root",
                    "coverage_profile",
                    "attributes",
                }
            ),
            "policy",
        )
        return cls(
            policy_profile=value.get("policy_profile", ""),
            policy_root=value.get("policy_root", ""),
            corpus_roots=tuple(value.get("corpus_roots", ())),
            revocation_root=value.get("revocation_root", ""),
            coverage_profile=value.get("coverage_profile", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    """Maps an envelope field path to a source span or reference."""

    map_id: str
    field_path: str
    source_ref: str
    start_char: int | None = None
    end_char: int | None = None
    note: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "map_id", _identifier(self.map_id, "source_map.map_id")
        )
        path = _text(self.field_path, "source_map.field_path")
        if not path.startswith(("/", "$", ".")):
            raise InvocationEnvelopeValidationError(
                "source_map.field_path must use JSON Pointer, JSONPath, or "
                "dotted-path syntax"
            )
        object.__setattr__(self, "field_path", path)
        object.__setattr__(
            self,
            "source_ref",
            _identifier(self.source_ref, "source_map.source_ref"),
        )
        for name in ("start_char", "end_char"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvocationEnvelopeValidationError(
                    f"source_map.{name} must be an integer or null"
                )
            if value < 0:
                raise InvocationEnvelopeValidationError(
                    f"source_map.{name} must be non-negative"
                )
        if self.start_char is not None and self.end_char is not None:
            if self.end_char < self.start_char:
                raise InvocationEnvelopeValidationError(
                    "source_map must satisfy start_char <= end_char"
                )
        object.__setattr__(
            self, "note", _text(self.note, "source_map.note", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "end_char": self.end_char,
            "field_path": self.field_path,
            "map_id": self.map_id,
            "note": self.note,
            "source_ref": self.source_ref,
            "start_char": self.start_char,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceMapEntry":
        value = _as_mapping(value, "source_map")
        _known_fields(
            value,
            frozenset(
                {
                    "map_id",
                    "field_path",
                    "source_ref",
                    "start_char",
                    "end_char",
                    "note",
                    "attributes",
                }
            ),
            "source_map",
        )
        return cls(
            map_id=value.get("map_id", ""),
            field_path=value.get("field_path", ""),
            source_ref=value.get("source_ref", ""),
            start_char=value.get("start_char"),
            end_char=value.get("end_char"),
            note=value.get("note", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class InvocationAssumption:
    """An explicit assumption that must remain visible for evaluation."""

    assumption_id: str
    statement: str
    source_ref: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assumption_id",
            _identifier(self.assumption_id, "assumption.assumption_id"),
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "assumption.statement")
        )
        object.__setattr__(
            self,
            "source_ref",
            _optional_identifier(self.source_ref, "assumption.source_ref"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "attributes": thaw_json(self.attributes),
            "source_ref": self.source_ref,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvocationAssumption":
        value = _as_mapping(value, "assumption")
        _known_fields(
            value,
            frozenset(
                {"assumption_id", "statement", "source_ref", "attributes"}
            ),
            "assumption",
        )
        return cls(
            assumption_id=value.get("assumption_id", ""),
            statement=value.get("statement", ""),
            source_ref=value.get("source_ref", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class InvocationDiagnostic:
    """Structured diagnostic retained on the envelope."""

    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    field_path: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _text(self.code, "diagnostic.code", max_chars=256)
        )
        object.__setattr__(
            self, "message", _text(self.message, "diagnostic.message")
        )
        object.__setattr__(
            self,
            "severity",
            _enum_value(DiagnosticSeverity, self.severity, "diagnostic.severity"),
        )
        object.__setattr__(
            self,
            "field_path",
            _text(self.field_path, "diagnostic.field_path", allow_empty=True),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "severity": self.severity.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvocationDiagnostic":
        value = _as_mapping(value, "diagnostic")
        _known_fields(
            value,
            frozenset(
                {"code", "message", "severity", "field_path", "attributes"}
            ),
            "diagnostic",
        )
        return cls(
            code=value.get("code", ""),
            message=value.get("message", ""),
            severity=value.get("severity", DiagnosticSeverity.ERROR),
            field_path=value.get("field_path", ""),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedField:
    """Preserves fields the adapter could not interpret without guessing."""

    field_path: str
    reason: str
    source_ref: str = ""
    raw_kind: str = "unknown"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "field_path",
            _text(self.field_path, "unsupported.field_path"),
        )
        object.__setattr__(
            self, "reason", _text(self.reason, "unsupported.reason")
        )
        object.__setattr__(
            self,
            "source_ref",
            _optional_identifier(self.source_ref, "unsupported.source_ref"),
        )
        object.__setattr__(
            self, "raw_kind", _text(self.raw_kind, "unsupported.raw_kind")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "field_path": self.field_path,
            "raw_kind": self.raw_kind,
            "reason": self.reason,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnsupportedField":
        value = _as_mapping(value, "unsupported field")
        _known_fields(
            value,
            frozenset(
                {
                    "field_path",
                    "reason",
                    "source_ref",
                    "raw_kind",
                    "attributes",
                }
            ),
            "unsupported field",
        )
        return cls(
            field_path=value.get("field_path", ""),
            reason=value.get("reason", ""),
            source_ref=value.get("source_ref", ""),
            raw_kind=value.get("raw_kind", "unknown"),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Collection schema for canonical identity
# ---------------------------------------------------------------------------


INVOCATION_ENVELOPE_COLLECTION_SCHEMA = CollectionSchema(
    {
        "/delegation": CollectionSemantics.ORDERED,
        "/delegation/*/capability_ids": CollectionSemantics.SET_LIKE,
        "/arguments/secret_refs": CollectionSemantics.SET_LIKE,
        "/scope/actions": CollectionSemantics.SET_LIKE,
        "/scope/effects": CollectionSemantics.SET_LIKE,
        "/scope/capabilities": CollectionSemantics.SET_LIKE,
        "/scope/assets": CollectionSemantics.SET_LIKE,
        "/scope/resources": CollectionSemantics.SET_LIKE,
        "/scope/data_classes": CollectionSemantics.SET_LIKE,
        "/scope/network": CollectionSemantics.SET_LIKE,
        "/scope/filesystem": CollectionSemantics.SET_LIKE,
        "/scope/subprocess": CollectionSemantics.SET_LIKE,
        "/scope/secret_refs": CollectionSemantics.SET_LIKE,
        "/preconditions": CollectionSemantics.ORDERED,
        "/postconditions": CollectionSemantics.ORDERED,
        "/failure_modes": CollectionSemantics.ORDERED,
        "/rollback": CollectionSemantics.ORDERED,
        "/verification": CollectionSemantics.ORDERED,
        "/policy/corpus_roots": CollectionSemantics.SET_LIKE,
        "/source_maps": CollectionSemantics.SET_LIKE,
        "/assumptions": CollectionSemantics.SET_LIKE,
        "/diagnostics": CollectionSemantics.ORDERED,
        "/unsupported_fields": CollectionSemantics.ORDERED,
    },
    # Attributes/facts may contain nested ordered sequences; leave those ordered
    # by default rather than requiring an exhaustive path declaration.
    require_declared=False,
)


# ---------------------------------------------------------------------------
# Top-level envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InvocationIntentEnvelope:
    """Immutable, canonical, redaction-aware invocation context contract.

    Binds source identity, tenant, actor/delegation, audience, tool binding,
    argument commitment, scopes, purpose/jurisdiction/time, environment,
    rollback/verification, policy/corpus requirements, nonce/deadline,
    source maps, assumptions, diagnostics, and unsupported fields.
    """

    envelope_id: str
    source: SourceBinding
    tenant_id: str
    actor: ActorBinding
    audience: AudienceBinding
    tool: ToolBinding
    arguments: ArgumentCommitment
    nonce: str
    created_at: str
    deadline: str
    invocation_kind: InvocationKind = InvocationKind.UNSPECIFIED
    trust_domain: str = ""
    delegation: tuple[DelegationLink, ...] = ()
    scope: InvocationScope = field(default_factory=InvocationScope)
    purpose: PurposeContext = field(default_factory=PurposeContext)
    environment: EnvironmentBinding = field(default_factory=EnvironmentBinding)
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    rollback: tuple[RollbackStep, ...] = ()
    verification: tuple[VerificationStep, ...] = ()
    policy: PolicyRequirements = field(default_factory=PolicyRequirements)
    trace_id: str = ""
    source_maps: tuple[SourceMapEntry, ...] = ()
    assumptions: tuple[InvocationAssumption, ...] = ()
    diagnostics: tuple[InvocationDiagnostic, ...] = ()
    unsupported_fields: tuple[UnsupportedField, ...] = ()
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = INVOCATION_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "envelope_id", _identifier(self.envelope_id, "envelope_id")
        )
        if self.schema_version != INVOCATION_ENVELOPE_SCHEMA_VERSION:
            raise InvocationEnvelopeValidationError(
                f"unsupported invocation envelope schema version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "invocation_kind",
            _enum_value(
                InvocationKind, self.invocation_kind, "invocation_kind"
            ),
        )
        if not isinstance(self.source, SourceBinding):
            object.__setattr__(
                self,
                "source",
                SourceBinding.from_dict(_as_mapping(self.source, "source")),
            )
        if (
            self.invocation_kind is not InvocationKind.UNSPECIFIED
            and self.source.kind is not InvocationKind.UNSPECIFIED
            and self.invocation_kind is not self.source.kind
            and self.invocation_kind is not InvocationKind.COMPOSITE
        ):
            raise InvocationEnvelopeValidationError(
                "invocation_kind must match source.kind unless composite"
            )
        object.__setattr__(
            self, "tenant_id", _identifier(self.tenant_id, "tenant_id")
        )
        if not isinstance(self.actor, ActorBinding):
            object.__setattr__(
                self,
                "actor",
                ActorBinding.from_dict(_as_mapping(self.actor, "actor")),
            )
        if not isinstance(self.audience, AudienceBinding):
            object.__setattr__(
                self,
                "audience",
                AudienceBinding.from_dict(
                    _as_mapping(self.audience, "audience")
                ),
            )
        if not isinstance(self.tool, ToolBinding):
            object.__setattr__(
                self,
                "tool",
                ToolBinding.from_dict(_as_mapping(self.tool, "tool")),
            )
        if not isinstance(self.arguments, ArgumentCommitment):
            object.__setattr__(
                self,
                "arguments",
                ArgumentCommitment.from_dict(
                    _as_mapping(self.arguments, "arguments")
                ),
            )
        object.__setattr__(
            self,
            "trust_domain",
            _optional_identifier(self.trust_domain, "trust_domain"),
        )
        object.__setattr__(
            self, "delegation", _coerce_records(self.delegation, DelegationLink, "delegation")
        )
        if not isinstance(self.scope, InvocationScope):
            object.__setattr__(
                self,
                "scope",
                InvocationScope.from_dict(_as_mapping(self.scope, "scope")),
            )
        if not isinstance(self.purpose, PurposeContext):
            object.__setattr__(
                self,
                "purpose",
                PurposeContext.from_dict(_as_mapping(self.purpose, "purpose")),
            )
        if not isinstance(self.environment, EnvironmentBinding):
            object.__setattr__(
                self,
                "environment",
                EnvironmentBinding.from_dict(
                    _as_mapping(self.environment, "environment")
                ),
            )
        object.__setattr__(
            self,
            "preconditions",
            _string_tuple(self.preconditions, "preconditions"),
        )
        object.__setattr__(
            self,
            "postconditions",
            _string_tuple(self.postconditions, "postconditions"),
        )
        object.__setattr__(
            self,
            "failure_modes",
            _string_tuple(self.failure_modes, "failure_modes"),
        )
        object.__setattr__(
            self,
            "rollback",
            _coerce_records(self.rollback, RollbackStep, "rollback"),
        )
        object.__setattr__(
            self,
            "verification",
            _coerce_records(self.verification, VerificationStep, "verification"),
        )
        if not isinstance(self.policy, PolicyRequirements):
            object.__setattr__(
                self,
                "policy",
                PolicyRequirements.from_dict(
                    _as_mapping(self.policy, "policy")
                ),
            )
        object.__setattr__(self, "nonce", _identifier(self.nonce, "nonce"))
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "deadline", _timestamp(self.deadline, "deadline")
        )
        if self.deadline < self.created_at:
            raise InvocationEnvelopeValidationError(
                "deadline must not precede created_at"
            )
        object.__setattr__(
            self, "trace_id", _optional_identifier(self.trace_id, "trace_id")
        )
        object.__setattr__(
            self,
            "source_maps",
            _coerce_records(self.source_maps, SourceMapEntry, "source_maps"),
        )
        object.__setattr__(
            self,
            "assumptions",
            _coerce_records(
                self.assumptions, InvocationAssumption, "assumptions"
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_records(
                self.diagnostics, InvocationDiagnostic, "diagnostics"
            ),
        )
        object.__setattr__(
            self,
            "unsupported_fields",
            _coerce_records(
                self.unsupported_fields,
                UnsupportedField,
                "unsupported_fields",
            ),
        )

        # Identity is part of the contract: recompute and reject drift.
        identity = self._compute_identity()
        if self.content_digest:
            recorded = _digest(self.content_digest, "content_digest")
            if recorded != identity.digest:
                raise InvocationEnvelopeValidationError(
                    "content_digest does not match recomputed envelope identity "
                    "(identity drift)"
                )
            object.__setattr__(self, "content_digest", recorded)
        else:
            object.__setattr__(self, "content_digest", identity.digest)
        if self.content_cid:
            recorded_cid = _text(self.content_cid, "content_cid")
            if recorded_cid != identity.cid:
                raise InvocationEnvelopeValidationError(
                    "content_cid does not match recomputed envelope identity "
                    "(identity drift)"
                )
            object.__setattr__(self, "content_cid", recorded_cid)
        else:
            object.__setattr__(self, "content_cid", identity.cid)

    def _identity_payload(self) -> dict[str, Any]:
        """Payload used for content identity (excludes digest/cid fields)."""

        payload = self.to_dict()
        payload.pop("content_digest", None)
        payload.pop("content_cid", None)
        return payload

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self._identity_payload(),
            domain=INVOCATION_ENVELOPE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
            collection_schema=INVOCATION_ENVELOPE_COLLECTION_SCHEMA,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-ready envelope payload."""

        return {
            "actor": self.actor.to_dict(),
            "arguments": self.arguments.to_dict(),
            "assumptions": [item.to_dict() for item in self.assumptions],
            "audience": self.audience.to_dict(),
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "delegation": [item.to_dict() for item in self.delegation],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "envelope_id": self.envelope_id,
            "environment": self.environment.to_dict(),
            "failure_modes": list(self.failure_modes),
            "invocation_kind": self.invocation_kind.value,
            "nonce": self.nonce,
            "policy": self.policy.to_dict(),
            "postconditions": list(self.postconditions),
            "preconditions": list(self.preconditions),
            "purpose": self.purpose.to_dict(),
            "rollback": [item.to_dict() for item in self.rollback],
            "schema_version": self.schema_version,
            "scope": self.scope.to_dict(),
            "source": self.source.to_dict(),
            "source_maps": [item.to_dict() for item in self.source_maps],
            "tenant_id": self.tenant_id,
            "tool": self.tool.to_dict(),
            "trace_id": self.trace_id,
            "trust_domain": self.trust_domain,
            "unsupported_fields": [
                item.to_dict() for item in self.unsupported_fields
            ],
            "verification": [item.to_dict() for item in self.verification],
        }

    def validate(self) -> "InvocationIntentEnvelope":
        """Re-validate this envelope against the complete contract."""

        return validate_invocation_envelope(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InvocationIntentEnvelope":
        """Decode a strict InvocationIntentEnvelope@1 document."""

        value = _as_mapping(value, "InvocationIntentEnvelope")
        allowed = frozenset(
            {
                "envelope_id",
                "schema_version",
                "invocation_kind",
                "source",
                "tenant_id",
                "actor",
                "delegation",
                "audience",
                "tool",
                "arguments",
                "trust_domain",
                "scope",
                "purpose",
                "environment",
                "preconditions",
                "postconditions",
                "failure_modes",
                "rollback",
                "verification",
                "policy",
                "nonce",
                "created_at",
                "deadline",
                "trace_id",
                "source_maps",
                "assumptions",
                "diagnostics",
                "unsupported_fields",
                "content_digest",
                "content_cid",
            }
        )
        _known_fields(value, allowed, "InvocationIntentEnvelope")
        return cls(
            envelope_id=value.get("envelope_id", ""),
            schema_version=value.get(
                "schema_version", INVOCATION_ENVELOPE_SCHEMA_VERSION
            ),
            invocation_kind=value.get(
                "invocation_kind", InvocationKind.UNSPECIFIED
            ),
            source=SourceBinding.from_dict(
                _as_mapping(value.get("source", {}), "source")
            ),
            tenant_id=value.get("tenant_id", ""),
            actor=ActorBinding.from_dict(
                _as_mapping(value.get("actor", {}), "actor")
            ),
            delegation=tuple(
                DelegationLink.from_dict(item)
                for item in value.get("delegation", ())
            ),
            audience=AudienceBinding.from_dict(
                _as_mapping(value.get("audience", {}), "audience")
            ),
            tool=ToolBinding.from_dict(
                _as_mapping(value.get("tool", {}), "tool")
            ),
            arguments=ArgumentCommitment.from_dict(
                _as_mapping(value.get("arguments", {}), "arguments")
            ),
            trust_domain=value.get("trust_domain", ""),
            scope=InvocationScope.from_dict(value.get("scope")),
            purpose=PurposeContext.from_dict(value.get("purpose")),
            environment=EnvironmentBinding.from_dict(value.get("environment")),
            preconditions=tuple(value.get("preconditions", ())),
            postconditions=tuple(value.get("postconditions", ())),
            failure_modes=tuple(value.get("failure_modes", ())),
            rollback=tuple(
                RollbackStep.from_dict(item)
                for item in value.get("rollback", ())
            ),
            verification=tuple(
                VerificationStep.from_dict(item)
                for item in value.get("verification", ())
            ),
            policy=PolicyRequirements.from_dict(value.get("policy")),
            nonce=value.get("nonce", ""),
            created_at=value.get("created_at", ""),
            deadline=value.get("deadline", ""),
            trace_id=value.get("trace_id", ""),
            source_maps=tuple(
                SourceMapEntry.from_dict(item)
                for item in value.get("source_maps", ())
            ),
            assumptions=tuple(
                InvocationAssumption.from_dict(item)
                for item in value.get("assumptions", ())
            ),
            diagnostics=tuple(
                InvocationDiagnostic.from_dict(item)
                for item in value.get("diagnostics", ())
            ),
            unsupported_fields=tuple(
                UnsupportedField.from_dict(item)
                for item in value.get("unsupported_fields", ())
            ),
            content_digest=value.get("content_digest", ""),
            content_cid=value.get("content_cid", ""),
        )

    def canonical_bytes(self) -> bytes:
        """Return domain-separated canonical identity preimage bytes."""

        return self.identity.canonical_bytes

    def canonical_json(self) -> str:
        """Return the UTF-8 decoded identity preimage (debug/display only)."""

        return self.canonical_bytes().decode("utf-8")

    @property
    def identity(self) -> CanonicalIdentity:
        """Shared fixed-profile identity for this envelope."""

        return self._compute_identity()

    @property
    def digest(self) -> str:
        return self.content_digest or self.identity.digest

    @property
    def cid(self) -> str:
        return self.content_cid or self.identity.cid


def _coerce_records(
    values: Sequence[Any],
    record_type: type[Any],
    name: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise InvocationEnvelopeValidationError(f"{name} must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise InvocationEnvelopeValidationError(
            f"{name} exceeds maximum of {MAX_COLLECTION_ITEMS} items"
        )
    converted = tuple(
        item
        if isinstance(item, record_type)
        else record_type.from_dict(_as_mapping(item, name))
        for item in values
    )
    return converted


def _string_tuple(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise InvocationEnvelopeValidationError(f"{name} must be a sequence")
    if len(values) > MAX_COLLECTION_ITEMS:
        raise InvocationEnvelopeValidationError(
            f"{name} exceeds maximum of {MAX_COLLECTION_ITEMS} items"
        )
    return tuple(_text(item, name) for item in values)


def validate_invocation_envelope(
    envelope: InvocationIntentEnvelope,
) -> InvocationIntentEnvelope:
    """Validate a fully constructed envelope (round-trip structural check)."""

    if not isinstance(envelope, InvocationIntentEnvelope):
        raise InvocationEnvelopeValidationError(
            "envelope must be an InvocationIntentEnvelope"
        )
    # Re-decode from the detached payload to catch any drift or non-frozen state.
    rebuilt = InvocationIntentEnvelope.from_dict(envelope.to_dict())
    if rebuilt.content_digest != envelope.content_digest:
        raise InvocationEnvelopeValidationError(
            "envelope identity drifted under revalidation"
        )
    if rebuilt.content_cid != envelope.content_cid:
        raise InvocationEnvelopeValidationError(
            "envelope CID drifted under revalidation"
        )
    return rebuilt


__all__ = [
    "ARGUMENT_COMMITMENT_DOMAIN",
    "INVOCATION_ENVELOPE_COLLECTION_SCHEMA",
    "INVOCATION_ENVELOPE_IDENTITY_DOMAIN",
    "INVOCATION_ENVELOPE_INTERFACE",
    "INVOCATION_ENVELOPE_SCHEMA_VERSION",
    "MAX_COLLECTION_ITEMS",
    "MAX_JSON_DEPTH",
    "MAX_JSON_NODES",
    "MAX_STRING_CHARS",
    "ActorBinding",
    "ArgumentCommitment",
    "AudienceBinding",
    "DelegationLink",
    "DiagnosticSeverity",
    "EnvironmentBinding",
    "InvocationAssumption",
    "InvocationDiagnostic",
    "InvocationEnvelopeValidationError",
    "InvocationIntentEnvelope",
    "InvocationKind",
    "InvocationScope",
    "PolicyRequirements",
    "PurposeContext",
    "RollbackStep",
    "ScopeEntry",
    "ScopeKind",
    "SourceBinding",
    "SourceMapEntry",
    "ToolBinding",
    "UnsupportedField",
    "VerificationStep",
    "commit_redacted_arguments",
    "validate_invocation_envelope",
]
