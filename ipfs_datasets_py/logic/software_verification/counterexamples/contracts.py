"""Secret-safe public counterexample boundary (CounterexampleEnvelope@2).

This module is the datasets-owned public wire contract for counterexamples.
Python, CLI, MCP, and verification-API projections must go through
:class:`PublicCounterexampleBoundary` so raw prover output, credentials,
hidden witnesses, source blobs, and private channels never leave the trusted
side.

Semantic identity is deliberately *not* redefined here.  Normalization and
content identity are delegated to the mature supervisor normalizer in
``ipfs_accelerate_py.agent_supervisor.proof.formal_counterexamples`` so
datasets and supervisor share one identity for the same failure.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

COUNTEREXAMPLE_ENVELOPE_INTERFACE: Final = "CounterexampleEnvelope@2"
PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE: Final = "PublicCounterexampleBoundary@1"
COUNTEREXAMPLE_ENVELOPE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-envelope@2"
)
PRIVATE_ARTIFACT_REFERENCE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/private-artifact-reference@1"
)
PUBLIC_COUNTEREXAMPLE_BOUNDARY_VERSION: Final = 1

# Default retention label for material that was discarded rather than stored.
DEFAULT_DROP_RETENTION_POLICY: Final = "policy:public-counterexample-drop@1"
DEFAULT_PRIVATE_RETENTION_POLICY: Final = "policy:private-counterexample-store@1"

# Closed public envelope keys — anything else fails closed on decode.
_ENVELOPE_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "interface",
        "boundary",
        "counterexample_id",
        "content_id",
        "semantic_id",
        "kind",
        "property_class",
        "property_id",
        "violated_property",
        "summary",
        "payload",
        "model",
        "source_map",
        "tool",
        "tool_id",
        "assumptions",
        "assumption_ids",
        "bounds",
        "finite_bounds",
        "authority",
        "bindings",
        "private_artifacts",
        "redaction",
        "observation_policy_id",
        "repair_classes",
        "minimized",
        "truncated",
        "redacted",
        "contains_private_material",
        "contains_raw_prover_output",
        "contains_source",
        "envelope_version",
    }
)

_PRIVATE_ARTIFACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "digest",
        "retention_policy_id",
        "channel",
        "byte_size",
        "retained",
        "media_type",
    }
)

# Substrings that must never appear in public payload/summary/bindings values.
# Structural boolean flags such as ``contains_raw_prover_output`` are exempt
# because they deny leakage rather than carry private material.
_FORBIDDEN_PUBLIC_MARKERS: Final[tuple[str, ...]] = (
    "hidden_witness",
    "private_witness",
    "private_inputs",
    "credential",
    "access_token",
    "refresh_token",
    "api_key",
    "raw_output",
    "prover_output",
    "stdout",
    "stderr",
    "source_excerpt",
    "source_code",
    "source_text",
    "file_content",
    "repository_source",
)

# Map discovered private key names to public-safe channel classes so the
# envelope can reference retention metadata without re-emitting secret key
# names such as ``hidden_witness`` or ``credential``.
_CHANNEL_CLASS_BY_KEY: Final[dict[str, str]] = {
    "hidden_witness": "secret_material",
    "private_witness": "secret_material",
    "private_input": "secret_material",
    "private_inputs": "secret_material",
    "private_premise": "secret_material",
    "private_key": "secret_material",
    "password": "secret_material",
    "passwd": "secret_material",
    "secret": "secret_material",
    "credential": "secret_material",
    "authorization": "secret_material",
    "cookie": "secret_material",
    "api_key": "secret_material",
    "access_token": "secret_material",
    "refresh_token": "secret_material",
    "session_token": "secret_material",
    "witness": "secret_material",
    "stdout": "provider_transcript",
    "stderr": "provider_transcript",
    "transcript": "provider_transcript",
    "command_output": "provider_transcript",
    "raw": "provider_artifact",
    "raw_data": "provider_artifact",
    "raw_output": "provider_artifact",
    "provider_output": "provider_artifact",
    "prover_output": "provider_artifact",
    "full_trace": "provider_artifact",
    "full_model": "provider_artifact",
    "proof_text": "provider_artifact",
    "source": "source_blob",
    "source_code": "source_blob",
    "source_text": "source_blob",
    "source_excerpt": "source_blob",
    "file_content": "source_blob",
    "repository_source": "source_blob",
}

_SAFE_PUBLIC_CHANNEL_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "secret_material",
        "provider_transcript",
        "provider_artifact",
        "source_blob",
        "private_channel",
    }
)

_SAFE_FLAG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "contains_private_material",
        "contains_raw_prover_output",
        "contains_source",
        "redacted",
        "minimized",
        "truncated",
        "retained",
    }
)

_PRIVATE_CHANNEL_KEY_RE = re.compile(
    r"(?:^|[_\-.])(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|session[_-]?token|credential|authorization|cookie|"
    r"private[_-]?key|private[_-]?premise|private[_-]?input|"
    r"hidden[_-]?witness|private[_-]?witness|witness)(?:$|[_\-.])",
    re.IGNORECASE,
)
_FORBIDDEN_CHANNEL_KEY_RE = re.compile(
    r"^(?:raw|raw_data|raw_output|provider_output|prover_output|stdout|stderr|"
    r"transcript|full_trace|full_model|source|source_code|source_text|"
    r"source_excerpt|file_content|repository_source|proof_text|command_output|"
    r"(?:[a-z0-9]+_)+source(?:_code|_text|_excerpt|_content)?)$",
    re.IGNORECASE,
)


class CounterexampleBoundaryError(ValueError):
    """Raised when a public counterexample projection is malformed or unsafe."""


class CounterexampleAuthority(StrEnum):
    """Authority ceiling advertised on a public counterexample envelope."""

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    SATISFIABILITY = "satisfiability"
    MODEL_CHECK = "model_check"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    CANDIDATE = "candidate"
    RECONSTRUCTION = "reconstruction"
    ATTESTATION = "attestation"
    THEOREM = "theorem"
    DECLARATIVE = "declarative"


def _text(value: object, label: str, *, optional: bool = False, maximum: int = 512) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise CounterexampleBoundaryError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise CounterexampleBoundaryError(f"{label} must not contain NUL")
    if not optional and not text:
        raise CounterexampleBoundaryError(f"{label} is required")
    if len(text) > maximum:
        text = text[: max(0, maximum - 1)] + "…"
    return text


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        item = _text(value, label, maximum=256)
        return (item,) if item else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise CounterexampleBoundaryError(f"{label} must be a sequence of strings")
    items: list[str] = []
    for raw in value:
        item = _text(raw, label, maximum=256)
        if item:
            items.append(item)
    return tuple(sorted(set(items)))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CounterexampleBoundaryError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise CounterexampleBoundaryError(f"{label} keys must be strings")
    return dict(value)


def _authority(value: object) -> CounterexampleAuthority:
    if isinstance(value, CounterexampleAuthority):
        return value
    raw = getattr(value, "value", value)
    try:
        return CounterexampleAuthority(str(raw).strip().lower())
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in CounterexampleAuthority)
        raise CounterexampleBoundaryError(
            f"authority must be one of: {allowed}"
        ) from exc


def _sha256_hex(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _channel_digest(channel: str, *, retained: bool) -> str:
    """Content-address channel metadata only — never secret values."""

    return _sha256_hex(
        _canonical_json_bytes(
            {
                "channel": channel,
                "retained": retained,
                "scope": "private-artifact-reference",
            }
        )
    )


def _is_private_or_forbidden_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return bool(
        _PRIVATE_CHANNEL_KEY_RE.search(normalized)
        or _FORBIDDEN_CHANNEL_KEY_RE.match(normalized)
    )


def _collect_private_channels(
    value: Any,
    *,
    path: str = "",
    found: set[str] | None = None,
) -> set[str]:
    """Discover private/forbidden channel names without reading their values."""

    acc = found if found is not None else set()
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            if _is_private_or_forbidden_key(key):
                acc.add(key.lower().replace("-", "_"))
                continue
            _collect_private_channels(child, path=child_path, found=acc)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        for index, child in enumerate(value):
            _collect_private_channels(child, path=f"{path}[{index}]", found=acc)
    return acc


def _public_channel_class(channel: str) -> str:
    """Map a private key/channel name to a public-safe channel class."""

    normalized = _text(channel, "channel", maximum=128).lower().replace("-", "_")
    if normalized in _SAFE_PUBLIC_CHANNEL_CLASSES:
        return normalized
    if normalized in _CHANNEL_CLASS_BY_KEY:
        return _CHANNEL_CLASS_BY_KEY[normalized]
    if _is_private_or_forbidden_key(normalized):
        # Unknown private-shaped keys collapse to an opaque class.
        if "source" in normalized:
            return "source_blob"
        if any(token in normalized for token in ("stdout", "stderr", "transcript")):
            return "provider_transcript"
        if any(token in normalized for token in ("raw", "prover", "provider", "output")):
            return "provider_artifact"
        return "secret_material"
    # Already-public labels (or hashed ids) pass through when safe.
    if any(marker in normalized for marker in _FORBIDDEN_PUBLIC_MARKERS):
        return "private_channel"
    return normalized


def _assert_public_safe(value: Any, *, label: str = "projection") -> None:
    """Reject private field names and secret-bearing values on public surfaces.

    Structural denial flags (``contains_raw_prover_output``) and private-artifact
    ``channel`` class labels are allowed; raw secret key names and secret
    substrings in payload values are not.
    """

    def walk(node: Any, *, path: str, allow_channel_class: bool = False) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key)
                key_l = key.lower().replace("-", "_")
                child_path = f"{path}.{key}" if path else key
                if key_l in _SAFE_FLAG_KEYS:
                    # Boolean denial / status flags may contain marker substrings.
                    continue
                if key_l == "channel" and allow_channel_class:
                    if not isinstance(child, str) or (
                        _public_channel_class(child) not in _SAFE_PUBLIC_CHANNEL_CLASSES
                        and child not in _SAFE_PUBLIC_CHANNEL_CLASSES
                    ):
                        # Channel metadata must stay within the public taxonomy.
                        if isinstance(child, str) and any(
                            marker in child.lower() for marker in _FORBIDDEN_PUBLIC_MARKERS
                        ):
                            raise CounterexampleBoundaryError(
                                f"{label} channel metadata re-emits private key name at {child_path}"
                            )
                    walk(child, path=child_path, allow_channel_class=False)
                    continue
                if _is_private_or_forbidden_key(key) or any(
                    marker == key_l or marker in key_l
                    for marker in _FORBIDDEN_PUBLIC_MARKERS
                    if marker not in {"prover_output"}  # handled via contains_* flags
                ):
                    # Allow only the explicit denial flags already skipped above.
                    if key_l not in _SAFE_FLAG_KEYS:
                        raise CounterexampleBoundaryError(
                            f"{label} contains forbidden public channel key {key!r}"
                        )
                nested_allow = key_l == "private_artifacts"
                walk(child, path=child_path, allow_channel_class=nested_allow)
            return
        if isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray, memoryview)
        ):
            for index, child in enumerate(node):
                # Sequence elements of private_artifacts remain channel-aware.
                walk(
                    child,
                    path=f"{path}[{index}]",
                    allow_channel_class=allow_channel_class,
                )
            return
        if isinstance(node, str):
            text = node.lower()
            if allow_channel_class and _public_channel_class(node) in _SAFE_PUBLIC_CHANNEL_CLASSES:
                return
            for marker in _FORBIDDEN_PUBLIC_MARKERS:
                if marker in text:
                    raise CounterexampleBoundaryError(
                        f"{label} contains forbidden public channel {marker!r} at {path or '<root>'}"
                    )

    walk(value, path="")


def _reject_unknown_keys(
    payload: Mapping[str, Any], allowed: frozenset[str], *, label: str
) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise CounterexampleBoundaryError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class PrivateArtifactReference:
    """Public handle to privately retained (or deliberately dropped) material.

    The reference never carries raw payload bytes or secret values.  Digests
    address either a private store object (when ``retained``) or channel
    metadata only (when the material was discarded before identity formation).
    """

    channel: str
    digest: str
    retention_policy_id: str = DEFAULT_DROP_RETENTION_POLICY
    retained: bool = False
    byte_size: int | None = None
    media_type: str = ""
    schema: str = PRIVATE_ARTIFACT_REFERENCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "channel", _text(self.channel, "channel", maximum=128)
        )
        object.__setattr__(
            self, "digest", _text(self.digest, "digest", maximum=256)
        )
        object.__setattr__(
            self,
            "retention_policy_id",
            _text(self.retention_policy_id, "retention_policy_id", maximum=256),
        )
        object.__setattr__(
            self,
            "media_type",
            _text(self.media_type, "media_type", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "schema", maximum=256)
            or PRIVATE_ARTIFACT_REFERENCE_SCHEMA,
        )
        if self.schema != PRIVATE_ARTIFACT_REFERENCE_SCHEMA:
            raise CounterexampleBoundaryError(
                f"unsupported private artifact schema {self.schema!r}"
            )
        if not isinstance(self.retained, bool):
            raise CounterexampleBoundaryError("retained must be boolean")
        if self.byte_size is not None:
            if (
                isinstance(self.byte_size, bool)
                or not isinstance(self.byte_size, int)
                or self.byte_size < 0
            ):
                raise CounterexampleBoundaryError(
                    "byte_size must be a non-negative integer or null"
                )
        if self.retained and self.retention_policy_id == DEFAULT_DROP_RETENTION_POLICY:
            raise CounterexampleBoundaryError(
                "retained private artifacts require a non-drop retention policy"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": self.schema,
            "channel": self.channel,
            "digest": self.digest,
            "retention_policy_id": self.retention_policy_id,
            "retained": self.retained,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
        }
        _assert_public_safe(payload, label="private artifact reference")
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PrivateArtifactReference":
        if not isinstance(value, Mapping):
            raise CounterexampleBoundaryError(
                "private artifact reference must be an object"
            )
        _reject_unknown_keys(value, _PRIVATE_ARTIFACT_KEYS, label="private artifact")
        return cls(
            channel=value.get("channel", ""),
            digest=value.get("digest", ""),
            retention_policy_id=value.get(
                "retention_policy_id", DEFAULT_DROP_RETENTION_POLICY
            ),
            retained=bool(value.get("retained", False)),
            byte_size=value.get("byte_size"),
            media_type=value.get("media_type", ""),
            schema=value.get("schema", PRIVATE_ARTIFACT_REFERENCE_SCHEMA),
        )

    @classmethod
    def for_dropped_channel(cls, channel: str) -> "PrivateArtifactReference":
        channel_class = _public_channel_class(channel)
        return cls(
            channel=channel_class,
            digest=_channel_digest(channel_class, retained=False),
            retention_policy_id=DEFAULT_DROP_RETENTION_POLICY,
            retained=False,
        )

    @classmethod
    def for_retained_channel(
        cls,
        channel: str,
        *,
        digest: str,
        retention_policy_id: str = DEFAULT_PRIVATE_RETENTION_POLICY,
        byte_size: int | None = None,
        media_type: str = "",
    ) -> "PrivateArtifactReference":
        return cls(
            channel=_public_channel_class(channel),
            digest=digest,
            retention_policy_id=retention_policy_id,
            retained=True,
            byte_size=byte_size,
            media_type=media_type,
        )


@dataclass(frozen=True, slots=True)
class CounterexampleEnvelope:
    """Closed, bounded, content-addressed public counterexample envelope."""

    counterexample_id: str
    kind: str
    property_class: str
    violated_property: str
    summary: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    source_map: Mapping[str, Any] = field(default_factory=dict)
    tool: Mapping[str, Any] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    bounds: Mapping[str, Any] = field(default_factory=dict)
    authority: CounterexampleAuthority | str = CounterexampleAuthority.BOUNDED
    bindings: Mapping[str, Any] = field(default_factory=dict)
    private_artifacts: tuple[PrivateArtifactReference, ...] = ()
    redaction: Mapping[str, Any] = field(default_factory=dict)
    observation_policy_id: str = ""
    repair_classes: tuple[str, ...] = ()
    content_id: str = ""
    minimized: bool = True
    truncated: bool = False
    schema: str = COUNTEREXAMPLE_ENVELOPE_SCHEMA
    interface: str = COUNTEREXAMPLE_ENVELOPE_INTERFACE
    boundary: str = PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "counterexample_id",
            _text(self.counterexample_id, "counterexample_id", maximum=256),
        )
        object.__setattr__(self, "kind", _text(self.kind, "kind", maximum=128))
        object.__setattr__(
            self,
            "property_class",
            _text(self.property_class, "property_class", maximum=128),
        )
        object.__setattr__(
            self,
            "violated_property",
            _text(self.violated_property, "violated_property", maximum=256),
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", maximum=512)
        )
        object.__setattr__(self, "payload", MappingProxyType(_mapping(self.payload, "payload")))
        object.__setattr__(
            self, "source_map", MappingProxyType(_mapping(self.source_map, "source_map"))
        )
        object.__setattr__(self, "tool", MappingProxyType(_mapping(self.tool, "tool")))
        object.__setattr__(
            self, "assumptions", _string_tuple(self.assumptions, "assumptions")
        )
        object.__setattr__(self, "bounds", MappingProxyType(_mapping(self.bounds, "bounds")))
        object.__setattr__(self, "authority", _authority(self.authority))
        object.__setattr__(
            self, "bindings", MappingProxyType(_mapping(self.bindings, "bindings"))
        )
        artifacts = tuple(self.private_artifacts)
        if any(not isinstance(item, PrivateArtifactReference) for item in artifacts):
            raise CounterexampleBoundaryError(
                "private_artifacts must be PrivateArtifactReference values"
            )
        # Stable order by channel then digest.
        artifacts = tuple(
            sorted(artifacts, key=lambda item: (item.channel, item.digest))
        )
        object.__setattr__(self, "private_artifacts", artifacts)
        object.__setattr__(
            self, "redaction", MappingProxyType(_mapping(self.redaction, "redaction"))
        )
        object.__setattr__(
            self,
            "observation_policy_id",
            _text(
                self.observation_policy_id,
                "observation_policy_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "repair_classes",
            _string_tuple(self.repair_classes, "repair_classes"),
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "schema", maximum=256) or COUNTEREXAMPLE_ENVELOPE_SCHEMA,
        )
        if self.schema != COUNTEREXAMPLE_ENVELOPE_SCHEMA:
            raise CounterexampleBoundaryError(
                f"unsupported counterexample envelope schema {self.schema!r}"
            )
        object.__setattr__(
            self,
            "interface",
            _text(self.interface, "interface", maximum=128)
            or COUNTEREXAMPLE_ENVELOPE_INTERFACE,
        )
        object.__setattr__(
            self,
            "boundary",
            _text(self.boundary, "boundary", maximum=128)
            or PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE,
        )
        if self.minimized is not True:
            raise CounterexampleBoundaryError(
                "public counterexample envelopes must be minimized"
            )
        if not isinstance(self.truncated, bool):
            raise CounterexampleBoundaryError("truncated must be boolean")

        public = self._public_core()
        _assert_public_safe(public, label="counterexample envelope")
        computed_content_id = _sha256_hex(_canonical_json_bytes(public))
        if self.content_id:
            claimed = _text(self.content_id, "content_id", maximum=256)
            if claimed != computed_content_id:
                raise CounterexampleBoundaryError(
                    "counterexample content identity does not match"
                )
            object.__setattr__(self, "content_id", claimed)
        else:
            object.__setattr__(self, "content_id", computed_content_id)

    def _public_core(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumptions),
            "authority": self.authority.value
            if isinstance(self.authority, CounterexampleAuthority)
            else str(self.authority),
            "bindings": dict(self.bindings),
            "boundary": self.boundary,
            "bounds": dict(self.bounds),
            "contains_private_material": False,
            "contains_raw_prover_output": False,
            "contains_source": False,
            "counterexample_id": self.counterexample_id,
            "envelope_version": PUBLIC_COUNTEREXAMPLE_BOUNDARY_VERSION,
            "interface": self.interface,
            "kind": self.kind,
            "minimized": True,
            "observation_policy_id": self.observation_policy_id,
            "payload": dict(self.payload),
            "private_artifacts": [item.to_dict() for item in self.private_artifacts],
            "property_class": self.property_class,
            "redacted": True,
            "redaction": dict(self.redaction),
            "repair_classes": list(self.repair_classes),
            "schema": self.schema,
            "source_map": dict(self.source_map),
            "summary": self.summary,
            "tool": dict(self.tool),
            "truncated": self.truncated,
            "violated_property": self.violated_property,
        }

    @property
    def semantic_id(self) -> str:
        """Alias for the supervisor-aligned counterexample identity."""

        return self.counterexample_id

    @property
    def property_id(self) -> str:
        return self.violated_property

    @property
    def tool_id(self) -> str:
        tool = self.tool
        for key in ("tool_id", "provider_id", "primary_provider_id"):
            value = tool.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        providers = tool.get("provider_ids")
        if isinstance(providers, Sequence) and providers:
            first = providers[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
        return ""

    @property
    def model(self) -> Any:
        """Compatibility projection of public model/assignments when present."""

        if "assignments" in self.payload:
            return self.payload["assignments"]
        if "model" in self.payload:
            return self.payload["model"]
        if "steps" in self.payload:
            return self.payload["steps"]
        return dict(self.payload)

    def to_dict(self) -> dict[str, Any]:
        payload = self._public_core()
        payload["content_id"] = self.content_id
        payload["semantic_id"] = self.counterexample_id
        payload["property_id"] = self.violated_property
        payload["tool_id"] = self.tool_id
        payload["assumptions"] = list(self.assumptions)
        payload["finite_bounds"] = dict(self.bounds)
        payload["model"] = self.model
        _assert_public_safe(payload, label="counterexample envelope dict")
        return payload

    def to_public_dict(self) -> dict[str, Any]:
        """Only projection allowed on public API / CLI / MCP surfaces."""

        return self.to_dict()

    def to_witness_dict(self) -> dict[str, Any]:
        """Witness slot projection — never re-embeds raw input."""

        return {
            "kind": self.kind,
            "counterexample_id": self.counterexample_id,
            "content_id": self.content_id,
            "property_id": self.violated_property,
            "summary": self.summary,
            "payload": dict(self.payload),
            "source_map": dict(self.source_map),
            "tool": dict(self.tool),
            "assumptions": list(self.assumptions),
            "bounds": dict(self.bounds),
            "authority": self.authority.value
            if isinstance(self.authority, CounterexampleAuthority)
            else str(self.authority),
            "private_artifacts": [item.to_dict() for item in self.private_artifacts],
            "contains_private_material": False,
            "schema": self.schema,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterexampleEnvelope":
        if not isinstance(value, Mapping):
            raise CounterexampleBoundaryError("counterexample envelope must be an object")
        _reject_unknown_keys(value, _ENVELOPE_PUBLIC_KEYS, label="counterexample envelope")
        schema = value.get("schema", COUNTEREXAMPLE_ENVELOPE_SCHEMA)
        if schema not in (None, "", COUNTEREXAMPLE_ENVELOPE_SCHEMA):
            raise CounterexampleBoundaryError(
                f"unsupported counterexample envelope schema {schema!r}"
            )
        for forbidden_flag in (
            "contains_private_material",
            "contains_raw_prover_output",
            "contains_source",
        ):
            if value.get(forbidden_flag) not in (None, False):
                raise CounterexampleBoundaryError(
                    f"envelope claims {forbidden_flag}"
                )

        private_raw = value.get("private_artifacts") or ()
        if not isinstance(private_raw, Sequence) or isinstance(
            private_raw, (str, bytes, bytearray)
        ):
            raise CounterexampleBoundaryError("private_artifacts must be a sequence")
        private_artifacts = tuple(
            PrivateArtifactReference.from_dict(item)
            for item in private_raw
            if isinstance(item, Mapping)
        )

        assumptions = value.get("assumptions", value.get("assumption_ids", ()))
        bounds = value.get("bounds", value.get("finite_bounds", {}))
        envelope = cls(
            counterexample_id=value.get("counterexample_id")
            or value.get("semantic_id")
            or "",
            kind=value.get("kind", ""),
            property_class=value.get("property_class", ""),
            violated_property=value.get("violated_property")
            or value.get("property_id")
            or "",
            summary=value.get("summary", ""),
            payload=value.get("payload") or {},
            source_map=value.get("source_map") or {},
            tool=value.get("tool") or {},
            assumptions=tuple(assumptions or ()),
            bounds=bounds or {},
            authority=value.get("authority", CounterexampleAuthority.BOUNDED),
            bindings=value.get("bindings") or {},
            private_artifacts=private_artifacts,
            redaction=value.get("redaction") or {},
            observation_policy_id=value.get("observation_policy_id", ""),
            repair_classes=tuple(value.get("repair_classes") or ()),
            content_id=value.get("content_id", ""),
            minimized=value.get("minimized", False),
            truncated=bool(value.get("truncated", False)),
            schema=schema or COUNTEREXAMPLE_ENVELOPE_SCHEMA,
            interface=value.get("interface", COUNTEREXAMPLE_ENVELOPE_INTERFACE),
            boundary=value.get("boundary", PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE),
        )

        for name, actual in (
            ("counterexample_id", envelope.counterexample_id),
            ("semantic_id", envelope.counterexample_id),
            ("content_id", envelope.content_id),
        ):
            claimed = value.get(name)
            if claimed not in (None, "", actual):
                raise CounterexampleBoundaryError(
                    "counterexample content identity does not match"
                )
        return envelope


def _kind_to_authority(kind: str) -> CounterexampleAuthority:
    mapping = {
        "smt_model": CounterexampleAuthority.SATISFIABILITY,
        "smt_unsat_core": CounterexampleAuthority.SATISFIABILITY,
        "tla_trace": CounterexampleAuthority.MODEL_CHECK,
        "protocol_attack": CounterexampleAuthority.PROTOCOL,
        "hypertrace": CounterexampleAuthority.HYPERPROPERTY,
        "runtime_mtl_violation": CounterexampleAuthority.MONITOR,
        "kernel_error": CounterexampleAuthority.THEOREM,
        "dcec_contradiction": CounterexampleAuthority.BOUNDED,
        "tdfol_contradiction": CounterexampleAuthority.BOUNDED,
        "generic_failure": CounterexampleAuthority.BOUNDED,
    }
    return mapping.get(str(kind).lower(), CounterexampleAuthority.BOUNDED)


def _source_map_from_bindings(bindings: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    source_map: dict[str, Any] = {
        "ast_scope_ids": list(bindings.get("ast_scope_ids") or ()),
        "source_ref_ids": list(
            raw.get("source_ref_ids")
            or bindings.get("source_ref_ids")
            or ()
        ),
        "span_ids": list(raw.get("span_ids") or bindings.get("span_ids") or ()),
        "tree_ids": list(bindings.get("tree_ids") or ()),
    }
    # Only keep public identifiers; never embed source text.
    cleaned: dict[str, Any] = {}
    for key, value in source_map.items():
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items = [
                str(item).strip()
                for item in value
                if str(item).strip() and not _is_private_or_forbidden_key(str(item))
            ]
            cleaned[key] = sorted(set(items))
        else:
            cleaned[key] = value
    return cleaned


def _tool_from_bindings(bindings: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    provider_ids = list(bindings.get("provider_ids") or ())
    receipt_ids = list(bindings.get("receipt_ids") or ())
    tool_id = (
        raw.get("tool_id")
        or raw.get("provider_id")
        or raw.get("prover_id")
        or (provider_ids[0] if provider_ids else "")
    )
    return {
        "tool_id": str(tool_id or ""),
        "provider_ids": provider_ids,
        "receipt_ids": receipt_ids,
        "primary_provider_id": str(tool_id or (provider_ids[0] if provider_ids else "")),
    }


def _private_artifacts_for_raw(
    raw: Mapping[str, Any],
    *,
    private_store: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[PrivateArtifactReference, ...]:
    channels = sorted(_collect_private_channels(raw))
    store = private_store or {}
    # Collapse many private keys into one public channel class per class, while
    # still preferring a retained store entry when present for that class/key.
    by_class: dict[str, PrivateArtifactReference] = {}
    for channel in channels:
        channel_class = _public_channel_class(channel)
        stored = store.get(channel) or store.get(channel_class)
        if isinstance(stored, Mapping) and stored.get("digest"):
            by_class[channel_class] = PrivateArtifactReference.for_retained_channel(
                channel_class,
                digest=str(stored["digest"]),
                retention_policy_id=str(
                    stored.get("retention_policy_id")
                    or DEFAULT_PRIVATE_RETENTION_POLICY
                ),
                byte_size=stored.get("byte_size"),
                media_type=str(stored.get("media_type") or ""),
            )
        elif channel_class not in by_class:
            by_class[channel_class] = PrivateArtifactReference.for_dropped_channel(
                channel_class
            )
    return tuple(
        sorted(by_class.values(), key=lambda item: (item.channel, item.digest))
    )


def project_public_counterexample(
    witness: Any,
    *,
    kind: str | None = None,
    violated_property: str = "",
    property_class: str = "",
    summary: str = "",
    assumption_ids: Iterable[str] = (),
    finite_bounds: Mapping[str, Any] | None = None,
    bindings: Mapping[str, Any] | None = None,
    authority: CounterexampleAuthority | str | None = None,
    private_store: Mapping[str, Mapping[str, Any]] | None = None,
    observation_policy_id: str = "",
) -> CounterexampleEnvelope:
    """Project any witness through the supervisor normalizer into Envelope@2.

    Secret values are discarded by the supervisor normalizer *before* semantic
    identity is computed.  This function only wraps the public result and
    attaches private-artifact retention metadata for dropped channels.
    """

    try:
        from ipfs_accelerate_py.agent_supervisor.proof.formal_counterexamples import (
            FORMAL_COUNTEREXAMPLE_SCHEMA,
            CounterexampleValidationError,
            FormalCounterexample,
            normalize_counterexample,
        )
    except ImportError as exc:  # pragma: no cover - monorepo always vendors this
        raise CounterexampleBoundaryError(
            "supervisor counterexample normalizer is unavailable"
        ) from exc

    raw_view: dict[str, Any]
    formal: FormalCounterexample | None = None

    if isinstance(witness, FormalCounterexample):
        formal = witness
        raw_view = formal.to_dict()
    else:
        if hasattr(witness, "to_dict") and callable(witness.to_dict):
            converted = witness.to_dict()
            if not isinstance(converted, Mapping):
                raise CounterexampleBoundaryError("to_dict() must return an object")
            raw_view = dict(converted)
        elif isinstance(witness, Mapping):
            raw_view = dict(witness)
        elif isinstance(witness, Sequence) and not isinstance(
            witness, (str, bytes, bytearray, memoryview)
        ):
            raw_view = {"counterexample": list(witness)}
        else:
            raise CounterexampleBoundaryError(
                "counterexample input must be an object, sequence, or typed contract"
            )

        # Accept already-normalized supervisor contracts without re-deriving
        # payload from the outer envelope (which would drop assignments).
        schema = str(raw_view.get("schema") or "")
        looks_normalized = schema == FORMAL_COUNTEREXAMPLE_SCHEMA or (
            isinstance(raw_view.get("payload"), Mapping)
            and raw_view.get("counterexample_id")
            and raw_view.get("kind")
            and raw_view.get("violated_property")
        )
        if looks_normalized:
            try:
                formal = FormalCounterexample.from_dict(raw_view)
            except CounterexampleValidationError:
                formal = None

        if formal is None:
            try:
                formal = normalize_counterexample(
                    raw_view,
                    kind=kind,
                    bindings=bindings,
                    property_class=property_class,
                    violated_property=violated_property,
                    summary=summary,
                    assumption_ids=assumption_ids,
                    finite_bounds=finite_bounds,
                    observation_policy_id=observation_policy_id,
                )
            except CounterexampleValidationError as exc:
                raise CounterexampleBoundaryError(str(exc)) from exc

    formal_dict = formal.to_dict()
    binding_dict = (
        formal.bindings.to_dict()
        if hasattr(formal.bindings, "to_dict")
        else dict(formal_dict.get("bindings") or {})
    )
    redaction = (
        formal.redaction.to_dict()
        if hasattr(formal.redaction, "to_dict")
        else dict(formal_dict.get("redaction") or {})
    )
    kind_value = (
        formal.kind.value if hasattr(formal.kind, "value") else str(formal.kind)
    )
    selected_authority = (
        _authority(authority)
        if authority is not None
        else _kind_to_authority(kind_value)
    )
    private_artifacts = _private_artifacts_for_raw(raw_view, private_store=private_store)

    envelope = CounterexampleEnvelope(
        counterexample_id=formal.semantic_id,
        kind=kind_value,
        property_class=formal.property_class,
        violated_property=formal.violated_property,
        summary=formal.summary,
        payload=dict(formal.payload),
        source_map=_source_map_from_bindings(binding_dict, raw_view),
        tool=_tool_from_bindings(binding_dict, raw_view),
        assumptions=tuple(formal.assumption_ids),
        bounds=dict(formal.finite_bounds),
        authority=selected_authority,
        bindings=binding_dict,
        private_artifacts=private_artifacts,
        redaction=redaction,
        observation_policy_id=formal.observation_policy_id,
        repair_classes=tuple(
            item.value if hasattr(item, "value") else str(item)
            for item in formal.repair_classes
        ),
        minimized=True,
        truncated=bool(formal.truncated),
    )
    # Enforce identity alignment with supervisor normalizer.
    if envelope.counterexample_id != formal.semantic_id:
        raise CounterexampleBoundaryError(
            "datasets envelope identity diverged from supervisor semantic identity"
        )
    return envelope


class PublicCounterexampleBoundary:
    """Stable adapter for public projections and fail-closed decode."""

    interface: Final = PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE
    envelope_interface: Final = COUNTEREXAMPLE_ENVELOPE_INTERFACE
    schema: Final = COUNTEREXAMPLE_ENVELOPE_SCHEMA

    def __init__(
        self,
        *,
        default_authority: CounterexampleAuthority | str | None = None,
        private_store: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        # None preserves kind-derived authority from project_public_counterexample.
        self.default_authority = (
            None if default_authority is None else _authority(default_authority)
        )
        self.private_store = dict(private_store or {})

    def project(self, witness: Any, **kwargs: Any) -> CounterexampleEnvelope:
        if "authority" not in kwargs and self.default_authority is not None:
            kwargs["authority"] = self.default_authority
        private_store = kwargs.pop("private_store", self.private_store)
        return project_public_counterexample(
            witness,
            private_store=private_store,
            **kwargs,
        )

    def project_public_dict(self, witness: Any, **kwargs: Any) -> dict[str, Any]:
        return self.project(witness, **kwargs).to_public_dict()

    def decode(self, value: Mapping[str, Any]) -> CounterexampleEnvelope:
        return CounterexampleEnvelope.from_dict(value)

    def assert_public_safe(self, value: Any) -> None:
        _assert_public_safe(value, label="public counterexample projection")


def explain_counterexample_envelope(
    witness: Any,
    **kwargs: Any,
) -> CounterexampleEnvelope:
    """Module-level convenience entry used by verification API delegation."""

    return PublicCounterexampleBoundary().project(witness, **kwargs)


__all__ = [
    "COUNTEREXAMPLE_ENVELOPE_INTERFACE",
    "COUNTEREXAMPLE_ENVELOPE_SCHEMA",
    "DEFAULT_DROP_RETENTION_POLICY",
    "DEFAULT_PRIVATE_RETENTION_POLICY",
    "PRIVATE_ARTIFACT_REFERENCE_SCHEMA",
    "PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE",
    "PUBLIC_COUNTEREXAMPLE_BOUNDARY_VERSION",
    "CounterexampleAuthority",
    "CounterexampleBoundaryError",
    "CounterexampleEnvelope",
    "PrivateArtifactReference",
    "PublicCounterexampleBoundary",
    "explain_counterexample_envelope",
    "project_public_counterexample",
]
