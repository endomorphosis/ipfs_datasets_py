"""CounterexampleEnvelope@2 and PublicCounterexampleBoundary@1.

This module owns the datasets wire contract for public counterexamples.  Every
Python, CLI, and MCP projection of a proof failure must pass through
:class:`PublicCounterexampleBoundary` so that:

* unknown fields and forged content identities fail closed;
* ``hidden_witness``, tokens, credentials, raw source, stdout, and other
  private channels never appear on the public surface;
* raw provider material is referenced only by private digest / retention
  metadata (never embedded); and
* kind, property, source-map, tool, assumptions, bounds, and authority are
  preserved on every projection.

Semantic identity is delegated to the mature supervisor normalizer
(``ipfs_accelerate_py.agent_supervisor.proof.formal_counterexamples``) so this
module does not invent a second counterexample identity.  The envelope is a
closed, content-addressed wire shape that wraps that normalized public IR and
adds private-artifact retention handles for stripped channels.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import stable_digest


COUNTEREXAMPLE_ENVELOPE_INTERFACE: Final = "CounterexampleEnvelope@2"
PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE: Final = "PublicCounterexampleBoundary@1"
COUNTEREXAMPLE_ENVELOPE_SCHEMA: Final = "counterexample-envelope/v2"
PRIVATE_ARTIFACT_REF_SCHEMA: Final = "counterexample-private-artifact-ref/v1"
DEFAULT_RETENTION_POLICY_ID: Final = "retention:private-counterexample-artifacts@1"
DEFAULT_AUTHORITY: Final = "bounded"
REDACTED: Final = "<redacted>"
OMITTED: Final = "<omitted>"

# Absolute public budgets (aligned with supervisor public limits).
MAX_PUBLIC_PAYLOAD_BYTES: Final = 12 * 1024
MAX_ENVELOPE_BYTES: Final = 32 * 1024
MAX_TEXT_CHARS: Final = 512
MAX_COLLECTION_ITEMS: Final = 64
MAX_NESTING_DEPTH: Final = 6

_PRIVATE_KEY_RE = re.compile(
    r"(?:^|[_\-.])(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|session[_-]?token|credential|authorization|cookie|"
    r"private[_-]?key|private[_-]?premise|private[_-]?input|"
    r"hidden[_-]?witness|private[_-]?witness|token|witness)(?:$|[_\-.])",
    re.IGNORECASE,
)
_FORBIDDEN_CHANNEL_RE = re.compile(
    r"^(?:raw|raw_data|raw_output|provider_output|prover_output|stdout|stderr|"
    r"transcript|full_trace|full_model|source|source_code|source_text|"
    r"source_excerpt|file_content|repository_source|proof_text|command_output|"
    r"hidden_witness|private_witness|private_inputs|"
    r"(?:[a-z0-9]+_)+source(?:_code|_text|_excerpt|_content)?)$",
    re.IGNORECASE,
)
_INLINE_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|authorization|token|credential)\s*[:=]\s*\S+"
    ),
    re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CREDENTIAL)[A-Z0-9 ]*-----"),
    re.compile(r"(?i)\b(?:https?|ssh)://[^/\s:@]+:[^/\s@]+@"),
)

_ENVELOPE_ALLOWED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "schema_version",
        "interface",
        "envelope_id",
        "content_id",
        "counterexample_id",
        "semantic_id",
        "kind",
        "property_id",
        "violated_property",
        "property_class",
        "summary",
        "public_payload",
        "source_map",
        "tool_id",
        "provider_id",
        "assumption_ids",
        "finite_bounds",
        "bounds",
        "authority",
        "private_artifacts",
        "redaction",
        "bindings",
        "observation_policy_id",
        "repair_classes",
        "minimized",
        "truncated",
        "redacted",
        "contains_private_material",
        "contains_raw_prover_output",
        "contains_source",
        "boundary",
    }
)

_FORBIDDEN_PUBLIC_MARKERS: Final[tuple[str, ...]] = (
    "hidden_witness",
    "private_witness",
    "private_inputs",
    "api_key",
    "access_token",
    "refresh_token",
    "raw_output",
    "prover_output",
    "provider_output",
    "source_excerpt",
    "source_code",
    "source_text",
    "\"stdout\"",
    "\"stderr\"",
    "\"raw\":",
    "\"credential\"",
    "\"token\"",
)


class CounterexampleEnvelopeError(ValueError):
    """Raised when a public counterexample envelope is malformed or unsafe."""


class ConfidentialityDisposition(str, Enum):
    PUBLIC_REDACTED = "public_redacted"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _text(
    value: Any,
    label: str,
    *,
    required: bool = False,
    maximum: int = MAX_TEXT_CHARS,
) -> str:
    if value is None:
        result = ""
    elif isinstance(value, str):
        result = value.strip()
    else:
        result = str(value).strip()
    result, _ = _redact_inline(result)
    if len(result) > maximum:
        result = result[: max(0, maximum - 1)] + "…"
    if required and not result:
        raise CounterexampleEnvelopeError(f"{label} is required")
    if "\x00" in result:
        raise CounterexampleEnvelopeError(f"{label} must not contain NUL")
    return result


def _ids(values: Any, label: str) -> tuple[str, ...]:
    if values is None:
        raw: Iterable[Any] = ()
    elif isinstance(values, str):
        raw = (values,)
    elif isinstance(values, Sequence) and not isinstance(
        values, (bytes, bytearray, memoryview)
    ):
        raw = values
    else:
        raise CounterexampleEnvelopeError(f"{label} must be a sequence of strings")
    cleaned = []
    for item in raw:
        text = _text(item, label, maximum=256)
        if text and text not in {REDACTED, OMITTED}:
            cleaned.append(text)
    return tuple(sorted(set(cleaned)))


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CounterexampleEnvelopeError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise CounterexampleEnvelopeError(f"{label} keys must be strings")
    return dict(value)


def _redact_inline(value: str) -> tuple[str, int]:
    result = value
    count = 0
    for pattern in _INLINE_SECRET_PATTERNS:
        result, matches = pattern.subn(REDACTED, result)
        count += matches
    return result, count


def _normalized_key(key: str) -> str:
    return str(key).strip().lower().replace("-", "_")


def _is_private_or_forbidden_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return bool(
        _PRIVATE_KEY_RE.search(normalized) or _FORBIDDEN_CHANNEL_RE.match(normalized)
    )


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise CounterexampleEnvelopeError(
            "unknown counterexample envelope field(s): " + ", ".join(unknown)
        )


def _contains_forbidden_marker(value: Any) -> bool:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).lower()
    except (TypeError, ValueError):
        return True
    return any(marker in encoded for marker in _FORBIDDEN_PUBLIC_MARKERS)


def _safe_public_value(
    value: Any,
    *,
    remaining_items: list[int],
    depth: int,
    redacted_values: list[int],
    dropped_fields: list[int],
    truncated: list[bool],
) -> Any:
    """Return bounded public JSON without inspecting private field values."""

    if remaining_items[0] <= 0:
        truncated[0] = True
        return OMITTED
    remaining_items[0] -= 1
    if depth >= MAX_NESTING_DEPTH:
        truncated[0] = True
        return OMITTED
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # noqa: PLR0124
            truncated[0] = True
            return "<non-finite-number>"
        return format(value, ".17g")
    if isinstance(value, str):
        result, redactions = _redact_inline(value)
        redacted_values[0] += redactions
        if len(result) > MAX_TEXT_CHARS:
            truncated[0] = True
            result = result[: max(0, MAX_TEXT_CHARS - 1)] + "…"
        return result
    if isinstance(value, (bytes, bytearray, memoryview)):
        dropped_fields[0] += 1
        return OMITTED
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item)):
            key = str(raw_key).strip()
            if _is_private_or_forbidden_key(key):
                # Do not read private values into public digests.
                dropped_fields[0] += 1
                continue
            if remaining_items[0] <= 0:
                truncated[0] = True
                break
            result[key] = _safe_public_value(
                value[raw_key],
                remaining_items=remaining_items,
                depth=depth + 1,
                redacted_values=redacted_values,
                dropped_fields=dropped_fields,
                truncated=truncated,
            )
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        result_list: list[Any] = []
        for item in value:
            if remaining_items[0] <= 0:
                truncated[0] = True
                break
            result_list.append(
                _safe_public_value(
                    item,
                    remaining_items=remaining_items,
                    depth=depth + 1,
                    redacted_values=redacted_values,
                    dropped_fields=dropped_fields,
                    truncated=truncated,
                )
            )
        return result_list
    dropped_fields[0] += 1
    return OMITTED


def _bounded_public(value: Any) -> tuple[Any, int, int, bool]:
    remaining = [MAX_COLLECTION_ITEMS]
    redacted = [0]
    dropped = [0]
    truncated = [False]
    public = _safe_public_value(
        value,
        remaining_items=remaining,
        depth=0,
        redacted_values=redacted,
        dropped_fields=dropped,
        truncated=truncated,
    )
    encoded = _canonical_json_bytes(public)
    if len(encoded) > MAX_PUBLIC_PAYLOAD_BYTES:
        digest = _sha256_hex(encoded)
        public = {
            "omitted": "<public-payload-exceeded-byte-limit>",
            "public_digest": digest,
        }
        truncated[0] = True
    return public, dropped[0], redacted[0], truncated[0]


def _digest_private_blob(value: Any) -> tuple[str, int]:
    """Content-address a private channel for retention metadata only.

    The digest is never folded into the public envelope identity, so it cannot
    become a public equality oracle for secrets.
    """

    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    elif isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    else:
        try:
            raw = _canonical_json_bytes(value)
        except (TypeError, ValueError):
            raw = repr(value).encode("utf-8", errors="replace")
    return _sha256_hex(raw), len(raw)


def _collect_private_artifacts(
    value: Any,
    *,
    path: str = "",
    seen: set[str] | None = None,
) -> list["PrivateArtifactRef"]:
    """Walk raw input and emit retention refs for private / forbidden channels."""

    if seen is None:
        seen = set()
    refs: list[PrivateArtifactRef] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            if _is_private_or_forbidden_key(key):
                channel = _normalized_key(key)
                if channel in seen:
                    continue
                seen.add(channel)
                digest, byte_length = _digest_private_blob(item)
                refs.append(
                    PrivateArtifactRef(
                        channel=channel,
                        private_digest=digest,
                        retention_policy_id=DEFAULT_RETENTION_POLICY_ID,
                        byte_length=byte_length,
                        path=child_path,
                    )
                )
                continue
            refs.extend(
                _collect_private_artifacts(item, path=child_path, seen=seen)
            )
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        for index, item in enumerate(value):
            refs.extend(
                _collect_private_artifacts(
                    item, path=f"{path}[{index}]", seen=seen
                )
            )
    return refs


def _extract_source_map(raw: Mapping[str, Any]) -> "SourceMapRef":
    source_map = raw.get("source_map")
    if isinstance(source_map, Mapping):
        return SourceMapRef(
            source_ref_ids=_ids(
                source_map.get("source_ref_ids")
                or source_map.get("source_refs")
                or (),
                "source_ref_ids",
            ),
            span_ids=_ids(
                source_map.get("span_ids") or source_map.get("spans") or (),
                "span_ids",
            ),
        )
    return SourceMapRef(
        source_ref_ids=_ids(
            raw.get("source_ref_ids")
            or raw.get("source_refs")
            or raw.get("source_ref_id")
            or (),
            "source_ref_ids",
        ),
        span_ids=_ids(
            raw.get("span_ids") or raw.get("spans") or raw.get("span_id") or (),
            "span_ids",
        ),
    )


def _authority_text(value: Any) -> str:
    raw = str(getattr(value, "value", value) or DEFAULT_AUTHORITY).strip().lower()
    if not raw:
        return DEFAULT_AUTHORITY
    return raw


@dataclass(frozen=True, slots=True)
class PrivateArtifactRef:
    """Private retention handle for stripped raw / secret channels.

    Public projections may list these refs so operators know material was
    retained under policy, but the digests are excluded from the envelope
    content identity.
    """

    channel: str
    private_digest: str
    retention_policy_id: str = DEFAULT_RETENTION_POLICY_ID
    byte_length: int = 0
    path: str = ""
    media_type: str = "application/octet-stream"
    retained: bool = True
    schema: str = PRIVATE_ARTIFACT_REF_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "channel", _text(self.channel, "channel", required=True, maximum=128)
        )
        digest = _text(self.private_digest, "private_digest", required=True, maximum=128)
        if not digest.startswith("sha256:") or len(digest) < 15:
            raise CounterexampleEnvelopeError(
                "private_digest must be a sha256: hex digest"
            )
        object.__setattr__(self, "private_digest", digest)
        object.__setattr__(
            self,
            "retention_policy_id",
            _text(
                self.retention_policy_id,
                "retention_policy_id",
                required=True,
                maximum=256,
            ),
        )
        if (
            isinstance(self.byte_length, bool)
            or not isinstance(self.byte_length, int)
            or self.byte_length < 0
        ):
            raise CounterexampleEnvelopeError("byte_length must be a non-negative int")
        object.__setattr__(
            self, "path", _text(self.path, "path", maximum=512)
        )
        object.__setattr__(
            self,
            "media_type",
            _text(self.media_type, "media_type", required=True, maximum=128),
        )
        if self.retained is not True:
            raise CounterexampleEnvelopeError(
                "private artifacts on public envelopes must declare retained=True"
            )
        if self.schema != PRIVATE_ARTIFACT_REF_SCHEMA:
            raise CounterexampleEnvelopeError(
                f"unsupported private artifact schema: {self.schema!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "channel": self.channel,
            "media_type": self.media_type,
            "path": self.path,
            "private_digest": self.private_digest,
            "retained": True,
            "retention_policy_id": self.retention_policy_id,
            "schema": self.schema,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PrivateArtifactRef":
        if not isinstance(payload, Mapping):
            raise CounterexampleEnvelopeError("private artifact must be an object")
        allowed = frozenset(
            {
                "byte_length",
                "channel",
                "media_type",
                "path",
                "private_digest",
                "retained",
                "retention_policy_id",
                "schema",
            }
        )
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise CounterexampleEnvelopeError(
                "unknown private artifact field(s): " + ", ".join(unknown)
            )
        return cls(
            channel=payload.get("channel", ""),
            private_digest=payload.get("private_digest", ""),
            retention_policy_id=payload.get(
                "retention_policy_id", DEFAULT_RETENTION_POLICY_ID
            ),
            byte_length=int(payload.get("byte_length") or 0),
            path=payload.get("path", ""),
            media_type=payload.get("media_type", "application/octet-stream"),
            retained=payload.get("retained", True),
            schema=payload.get("schema", PRIVATE_ARTIFACT_REF_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class SourceMapRef:
    """Public source-map identities (never raw source text)."""

    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        object.__setattr__(self, "span_ids", _ids(self.span_ids, "span_ids"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "SourceMapRef":
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise CounterexampleEnvelopeError("source_map must be an object")
        return cls(
            source_ref_ids=payload.get("source_ref_ids") or (),
            span_ids=payload.get("span_ids") or (),
        )


@dataclass(frozen=True, slots=True)
class RedactionReport:
    disposition: ConfidentialityDisposition = (
        ConfidentialityDisposition.PUBLIC_REDACTED
    )
    dropped_fields: int = 0
    redacted_values: int = 0

    def __post_init__(self) -> None:
        disposition = self.disposition
        if not isinstance(disposition, ConfidentialityDisposition):
            disposition = ConfidentialityDisposition(
                str(getattr(disposition, "value", disposition))
            )
        object.__setattr__(self, "disposition", disposition)
        for name in ("dropped_fields", "redacted_values"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CounterexampleEnvelopeError(f"{name} must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contains_private_material": False,
            "disposition": self.disposition.value,
            "dropped_fields": self.dropped_fields,
            "redacted_values": self.redacted_values,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "RedactionReport":
        value = payload or {}
        if value.get("contains_private_material") not in (None, False):
            raise CounterexampleEnvelopeError(
                "public envelope cannot claim private material"
            )
        return cls(
            disposition=value.get(
                "disposition", ConfidentialityDisposition.PUBLIC_REDACTED
            ),
            dropped_fields=int(value.get("dropped_fields") or 0),
            redacted_values=int(value.get("redacted_values") or 0),
        )


@dataclass(frozen=True, slots=True)
class CounterexampleEnvelope:
    """Closed, content-addressed, secret-safe public counterexample wire shape.

    Interface: ``CounterexampleEnvelope@2``.
    """

    kind: str
    property_id: str
    summary: str
    public_payload: Mapping[str, Any] = field(default_factory=dict)
    property_class: str = "formal_verification"
    source_map: SourceMapRef = field(default_factory=SourceMapRef)
    tool_id: str = ""
    assumption_ids: tuple[str, ...] = ()
    finite_bounds: Mapping[str, Any] = field(default_factory=dict)
    authority: str = DEFAULT_AUTHORITY
    private_artifacts: tuple[PrivateArtifactRef, ...] = ()
    redaction: RedactionReport = field(default_factory=RedactionReport)
    bindings: Mapping[str, Any] = field(default_factory=dict)
    observation_policy_id: str = ""
    repair_classes: tuple[str, ...] = ()
    semantic_id: str = ""
    minimized: bool = True
    truncated: bool = False
    schema: str = COUNTEREXAMPLE_ENVELOPE_SCHEMA
    interface: str = COUNTEREXAMPLE_ENVELOPE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _text(self.kind, "kind", required=True, maximum=128)
        )
        object.__setattr__(
            self,
            "property_id",
            _text(self.property_id, "property_id", required=True, maximum=256),
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", required=True)
        )
        object.__setattr__(
            self,
            "property_class",
            _text(
                self.property_class,
                "property_class",
                required=True,
                maximum=128,
            ),
        )
        if not isinstance(self.source_map, SourceMapRef):
            raise CounterexampleEnvelopeError("source_map must be a SourceMapRef")
        object.__setattr__(
            self, "tool_id", _text(self.tool_id, "tool_id", maximum=256)
        )
        object.__setattr__(
            self, "assumption_ids", _ids(self.assumption_ids, "assumption_ids")
        )
        public_payload, _, _, _ = _bounded_public(_mapping(self.public_payload, "public_payload"))
        bounds, _, _, _ = _bounded_public(_mapping(self.finite_bounds, "finite_bounds"))
        if not isinstance(public_payload, Mapping) or not isinstance(bounds, Mapping):
            raise CounterexampleEnvelopeError("public payload and bounds must be objects")
        object.__setattr__(self, "public_payload", MappingProxyType(dict(public_payload)))
        object.__setattr__(self, "finite_bounds", MappingProxyType(dict(bounds)))
        object.__setattr__(self, "authority", _authority_text(self.authority))
        if any(not isinstance(item, PrivateArtifactRef) for item in self.private_artifacts):
            raise CounterexampleEnvelopeError(
                "private_artifacts must be PrivateArtifactRef values"
            )
        # Stable ordering for content-addressed identity independence.
        ordered_artifacts = tuple(
            sorted(self.private_artifacts, key=lambda item: (item.channel, item.path))
        )
        object.__setattr__(self, "private_artifacts", ordered_artifacts)
        if not isinstance(self.redaction, RedactionReport):
            raise CounterexampleEnvelopeError("redaction must be a RedactionReport")
        bindings = _mapping(self.bindings, "bindings")
        safe_bindings, _, _, _ = _bounded_public(bindings)
        if not isinstance(safe_bindings, Mapping):
            safe_bindings = {}
        object.__setattr__(self, "bindings", MappingProxyType(dict(safe_bindings)))
        object.__setattr__(
            self,
            "observation_policy_id",
            _text(self.observation_policy_id, "observation_policy_id", maximum=256),
        )
        repairs = _ids(self.repair_classes, "repair_classes")
        object.__setattr__(self, "repair_classes", repairs)
        if self.minimized is not True:
            raise CounterexampleEnvelopeError("public envelopes must be minimized")
        if not isinstance(self.truncated, bool):
            raise CounterexampleEnvelopeError("truncated must be boolean")
        if self.schema != COUNTEREXAMPLE_ENVELOPE_SCHEMA:
            raise CounterexampleEnvelopeError(
                f"unsupported envelope schema: {self.schema!r}"
            )
        if self.interface != COUNTEREXAMPLE_ENVELOPE_INTERFACE:
            raise CounterexampleEnvelopeError(
                f"unsupported envelope interface: {self.interface!r}"
            )
        public = self._public_identity_payload()
        if _contains_forbidden_marker(public):
            raise CounterexampleEnvelopeError(
                "unsafe private or raw channel entered the public envelope"
            )
        if len(_canonical_json_bytes(self.to_dict())) > MAX_ENVELOPE_BYTES:
            raise CounterexampleEnvelopeError(
                "counterexample envelope exceeds the absolute public limit"
            )

    def _public_identity_payload(self) -> dict[str, Any]:
        """Fields that define public content identity (no private digests)."""

        return {
            "assumption_ids": list(self.assumption_ids),
            "authority": self.authority,
            "bindings": dict(self.bindings),
            "finite_bounds": dict(self.finite_bounds),
            "kind": self.kind,
            "observation_policy_id": self.observation_policy_id,
            "property_class": self.property_class,
            "property_id": self.property_id,
            "public_payload": dict(self.public_payload),
            "repair_classes": list(self.repair_classes),
            "source_map": self.source_map.to_dict(),
            "summary": self.summary,
            "tool_id": self.tool_id,
        }

    @property
    def content_id(self) -> str:
        return "sha256:" + stable_digest(self._public_identity_payload())

    @property
    def envelope_id(self) -> str:
        return self.content_id

    @property
    def counterexample_id(self) -> str:
        return self.semantic_id or self.content_id

    @property
    def violated_property(self) -> str:
        return self.property_id

    @property
    def provider_id(self) -> str:
        return self.tool_id

    @property
    def contains_private_material(self) -> bool:
        return False

    @property
    def contains_raw_prover_output(self) -> bool:
        return False

    @property
    def contains_source(self) -> bool:
        return False

    def public_model(self) -> Any:
        """Best-effort public model / assignment / trace for stable API compat."""

        payload = dict(self.public_payload)
        for key in (
            "assignments",
            "model",
            "assignment",
            "trace",
            "steps",
            "core",
            "contradiction",
        ):
            if key in payload:
                return payload[key]
        return payload or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "authority": self.authority,
            "bindings": dict(self.bindings),
            "boundary": PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE,
            "contains_private_material": False,
            "contains_raw_prover_output": False,
            "contains_source": False,
            "content_id": self.content_id,
            "counterexample_id": self.counterexample_id,
            "envelope_id": self.envelope_id,
            "finite_bounds": dict(self.finite_bounds),
            "interface": self.interface,
            "kind": self.kind,
            "minimized": True,
            "observation_policy_id": self.observation_policy_id,
            "private_artifacts": [item.to_dict() for item in self.private_artifacts],
            "property_class": self.property_class,
            "property_id": self.property_id,
            "provider_id": self.tool_id,
            "public_payload": dict(self.public_payload),
            "redacted": True,
            "redaction": self.redaction.to_dict(),
            "repair_classes": list(self.repair_classes),
            "schema": self.schema,
            "schema_version": self.schema,
            "semantic_id": self.semantic_id or self.content_id,
            "source_map": self.source_map.to_dict(),
            "summary": self.summary,
            "tool_id": self.tool_id,
            "truncated": self.truncated,
            "violated_property": self.property_id,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Only projection allowed on public / model / CLI / MCP surfaces."""

        return self.to_dict()

    def to_record(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CounterexampleEnvelope":
        if not isinstance(payload, Mapping):
            raise CounterexampleEnvelopeError("envelope payload must be an object")
        _reject_unknown_fields(payload, _ENVELOPE_ALLOWED_FIELDS)
        schema = payload.get("schema") or payload.get("schema_version") or (
            COUNTEREXAMPLE_ENVELOPE_SCHEMA
        )
        if schema not in {
            COUNTEREXAMPLE_ENVELOPE_SCHEMA,
            "counterexample-envelope@2",
            COUNTEREXAMPLE_ENVELOPE_INTERFACE,
        }:
            raise CounterexampleEnvelopeError(
                f"unsupported counterexample envelope schema: {schema!r}"
            )
        interface = payload.get("interface") or COUNTEREXAMPLE_ENVELOPE_INTERFACE
        if interface != COUNTEREXAMPLE_ENVELOPE_INTERFACE:
            raise CounterexampleEnvelopeError(
                f"unsupported counterexample envelope interface: {interface!r}"
            )
        if payload.get("contains_private_material") not in (None, False):
            raise CounterexampleEnvelopeError(
                "envelope claims to contain private material"
            )
        if payload.get("contains_raw_prover_output") not in (None, False):
            raise CounterexampleEnvelopeError(
                "envelope claims to contain raw prover output"
            )
        if payload.get("contains_source") not in (None, False):
            raise CounterexampleEnvelopeError("envelope claims to contain source")

        private_artifacts = tuple(
            PrivateArtifactRef.from_dict(item)
            for item in payload.get("private_artifacts") or ()
            if isinstance(item, Mapping)
        )
        redaction = payload.get("redaction")
        source_map = payload.get("source_map")
        result = cls(
            kind=payload.get("kind") or "",
            property_id=(
                payload.get("property_id")
                or payload.get("violated_property")
                or ""
            ),
            summary=payload.get("summary") or "",
            public_payload=payload.get("public_payload") or {},
            property_class=payload.get("property_class") or "formal_verification",
            source_map=SourceMapRef.from_dict(
                source_map if isinstance(source_map, Mapping) else None
            ),
            tool_id=payload.get("tool_id") or payload.get("provider_id") or "",
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            finite_bounds=payload.get("finite_bounds")
            or payload.get("bounds")
            or {},
            authority=payload.get("authority") or DEFAULT_AUTHORITY,
            private_artifacts=private_artifacts,
            redaction=RedactionReport.from_dict(
                redaction if isinstance(redaction, Mapping) else None
            ),
            bindings=payload.get("bindings") or {},
            observation_policy_id=payload.get("observation_policy_id") or "",
            repair_classes=tuple(payload.get("repair_classes") or ()),
            semantic_id=str(
                payload.get("semantic_id")
                or payload.get("counterexample_id")
                or ""
            ),
            minimized=payload.get("minimized", True),
            truncated=bool(payload.get("truncated", False)),
            schema=COUNTEREXAMPLE_ENVELOPE_SCHEMA,
            interface=COUNTEREXAMPLE_ENVELOPE_INTERFACE,
        )
        for claimed_name in ("content_id", "envelope_id"):
            claimed = payload.get(claimed_name)
            if claimed and claimed != result.content_id:
                raise CounterexampleEnvelopeError(
                    f"forged identity: {claimed_name} does not match envelope payload"
                )
        claimed_semantic = payload.get("semantic_id") or payload.get("counterexample_id")
        if (
            claimed_semantic
            and result.semantic_id
            and claimed_semantic != result.semantic_id
            and claimed_semantic != result.content_id
        ):
            # Accept either supervisor semantic_id or local content_id.
            if claimed_semantic not in {result.semantic_id, result.content_id}:
                raise CounterexampleEnvelopeError(
                    "forged identity: counterexample_id/semantic_id does not match"
                )
        if _contains_forbidden_marker(result.to_public_dict()):
            raise CounterexampleEnvelopeError(
                "decoded envelope contains forbidden public markers"
            )
        return result


def _witness_to_mapping(witness: Any) -> dict[str, Any]:
    if witness is None:
        raise CounterexampleEnvelopeError("witness is required")
    if isinstance(witness, CounterexampleEnvelope):
        return witness.to_dict()
    if hasattr(witness, "to_dict") and callable(witness.to_dict):
        converted = witness.to_dict()
        if not isinstance(converted, Mapping):
            raise CounterexampleEnvelopeError("to_dict() must return an object")
        return dict(converted)
    if isinstance(witness, Mapping):
        return dict(witness)
    if isinstance(witness, Sequence) and not isinstance(
        witness, (str, bytes, bytearray, memoryview)
    ):
        return {"trace": list(witness)}
    raise CounterexampleEnvelopeError(
        "witness must be a mapping, sequence, typed contract, or envelope"
    )


def _try_supervisor_normalize(
    raw: Mapping[str, Any],
    *,
    kind: str | None = None,
    violated_property: str = "",
    summary: str = "",
    assumption_ids: Iterable[str] = (),
    finite_bounds: Mapping[str, Any] | None = None,
    observation_policy_id: str = "",
    bindings: Mapping[str, Any] | None = None,
) -> Any | None:
    """Delegate to the mature supervisor normalizer when importable."""

    try:
        from ipfs_accelerate_py.agent_supervisor.proof.formal_counterexamples import (
            normalize_counterexample,
        )
    except Exception:
        return None
    kwargs: dict[str, Any] = {}
    if kind:
        kwargs["kind"] = kind
    if violated_property:
        kwargs["violated_property"] = violated_property
    if summary:
        kwargs["summary"] = summary
    if assumption_ids:
        kwargs["assumption_ids"] = assumption_ids
    if finite_bounds is not None:
        kwargs["finite_bounds"] = finite_bounds
    if observation_policy_id:
        kwargs["observation_policy_id"] = observation_policy_id
    if bindings is not None:
        kwargs["bindings"] = bindings
    try:
        return normalize_counterexample(raw, **kwargs)
    except Exception as error:
        raise CounterexampleEnvelopeError(
            f"supervisor normalizer rejected witness: {error}"
        ) from error


@dataclass(frozen=True, slots=True)
class PublicCounterexampleBoundary:
    """Single closed boundary for every public counterexample projection.

    Interface: ``PublicCounterexampleBoundary@1``.
    """

    interface: str = PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE
    retention_policy_id: str = DEFAULT_RETENTION_POLICY_ID
    default_authority: str = DEFAULT_AUTHORITY

    def __post_init__(self) -> None:
        if self.interface != PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE:
            raise CounterexampleEnvelopeError(
                f"unsupported boundary interface: {self.interface!r}"
            )
        object.__setattr__(
            self,
            "retention_policy_id",
            _text(
                self.retention_policy_id,
                "retention_policy_id",
                required=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "default_authority",
            _authority_text(self.default_authority),
        )

    def project(
        self,
        witness: Any,
        *,
        kind: str | None = None,
        property_id: str = "",
        violated_property: str = "",
        summary: str = "",
        assumption_ids: Iterable[str] = (),
        finite_bounds: Mapping[str, Any] | None = None,
        observation_policy_id: str = "",
        bindings: Mapping[str, Any] | None = None,
        tool_id: str = "",
        authority: str = "",
        source_map: Mapping[str, Any] | SourceMapRef | None = None,
    ) -> CounterexampleEnvelope:
        """Normalize *witness* into a closed public :class:`CounterexampleEnvelope`."""

        raw = _witness_to_mapping(witness)
        private_artifacts = tuple(
            PrivateArtifactRef(
                channel=item.channel,
                private_digest=item.private_digest,
                retention_policy_id=self.retention_policy_id,
                byte_length=item.byte_length,
                path=item.path,
                media_type=item.media_type,
            )
            for item in _collect_private_artifacts(raw)
        )

        selected_property = _text(
            property_id
            or violated_property
            or raw.get("property_id")
            or raw.get("violated_property")
            or raw.get("invariant")
            or raw.get("obligation_id")
            or raw.get("query")
            or "",
            "property_id",
            maximum=256,
        )
        selected_summary = _text(
            summary
            or raw.get("summary")
            or raw.get("message")
            or raw.get("description")
            or "",
            "summary",
            maximum=MAX_TEXT_CHARS,
        )
        selected_kind = kind or raw.get("kind") or raw.get("witness_kind")
        selected_assumptions = _ids(
            tuple(assumption_ids)
            + tuple(raw.get("assumption_ids") or ())
            + tuple(raw.get("premise_ids") or ()),
            "assumption_ids",
        )
        selected_bounds = (
            dict(finite_bounds)
            if finite_bounds is not None
            else dict(raw.get("finite_bounds") or raw.get("bounds") or {})
        )
        selected_observation = _text(
            observation_policy_id
            or raw.get("observation_policy_id")
            or "",
            "observation_policy_id",
            maximum=256,
        )
        selected_tool = _text(
            tool_id
            or raw.get("tool_id")
            or raw.get("provider_id")
            or raw.get("prover_id")
            or "",
            "tool_id",
            maximum=256,
        )
        selected_authority = _authority_text(
            authority or raw.get("authority") or self.default_authority
        )
        if isinstance(source_map, SourceMapRef):
            selected_source_map = source_map
        elif isinstance(source_map, Mapping):
            selected_source_map = SourceMapRef.from_dict(source_map)
        else:
            selected_source_map = _extract_source_map(raw)

        selected_bindings = dict(bindings or raw.get("bindings") or {})
        # Promote common singular binding keys for the supervisor normalizer.
        for singular, plural in (
            ("plan_id", "plan_ids"),
            ("task_id", "task_ids"),
            ("tree_id", "tree_ids"),
            ("provider_id", "provider_ids"),
            ("receipt_id", "receipt_ids"),
            ("obligation_id", "obligation_ids"),
            ("policy_id", "policy_ids"),
        ):
            if singular in raw and plural not in selected_bindings:
                selected_bindings.setdefault(singular, raw.get(singular))

        normalized = _try_supervisor_normalize(
            raw,
            kind=str(selected_kind) if selected_kind else None,
            violated_property=selected_property,
            summary=selected_summary,
            assumption_ids=selected_assumptions,
            finite_bounds=selected_bounds or None,
            observation_policy_id=selected_observation,
            bindings=selected_bindings or None,
        )

        if normalized is not None:
            kind_value = str(getattr(normalized.kind, "value", normalized.kind))
            property_value = str(normalized.violated_property)
            summary_value = str(normalized.summary)
            property_class = str(normalized.property_class)
            public_payload = dict(normalized.payload)
            assumption_values = tuple(normalized.assumption_ids)
            bounds_value = dict(normalized.finite_bounds)
            observation = str(normalized.observation_policy_id or selected_observation)
            repairs = tuple(
                str(getattr(item, "value", item)) for item in normalized.repair_classes
            )
            binding_dict = (
                normalized.bindings.to_dict()
                if hasattr(normalized.bindings, "to_dict")
                else dict(selected_bindings)
            )
            tool = selected_tool
            if not tool and binding_dict.get("provider_ids"):
                providers = binding_dict["provider_ids"]
                if isinstance(providers, Sequence) and providers:
                    tool = str(providers[0])
            semantic = str(normalized.semantic_id)
            redaction = RedactionReport(
                disposition=ConfidentialityDisposition.PUBLIC_REDACTED,
                dropped_fields=int(
                    getattr(normalized.redaction, "dropped_fields", 0) or 0
                )
                + len(private_artifacts),
                redacted_values=int(
                    getattr(normalized.redaction, "redacted_values", 0) or 0
                ),
            )
            truncated = bool(normalized.truncated)
        else:
            # Standalone fail-closed fallback when supervisor is unavailable.
            public_payload, dropped, redacted, truncated = _bounded_public(
                {
                    key: value
                    for key, value in raw.items()
                    if not _is_private_or_forbidden_key(str(key))
                    and str(key)
                    not in {
                        "kind",
                        "witness_kind",
                        "summary",
                        "message",
                        "description",
                        "property_id",
                        "violated_property",
                        "assumption_ids",
                        "premise_ids",
                        "finite_bounds",
                        "bounds",
                        "authority",
                        "tool_id",
                        "provider_id",
                        "prover_id",
                        "source_map",
                        "source_ref_ids",
                        "span_ids",
                        "bindings",
                        "observation_policy_id",
                    }
                }
            )
            if not isinstance(public_payload, Mapping):
                public_payload = {"value": public_payload}
            # Prefer classic model/trace keys for the public payload body.
            for key in ("model", "assignment", "assignments", "trace", "unsat_core"):
                if key in raw and not _is_private_or_forbidden_key(key):
                    body, d2, r2, t2 = _bounded_public(raw[key])
                    public_payload = {
                        "assignments"
                        if key in {"model", "assignment"}
                        else ("core" if key == "unsat_core" else key): body
                    }
                    dropped += d2
                    redacted += r2
                    truncated = truncated or t2
                    break
            kind_value = _text(
                selected_kind or "generic_failure",
                "kind",
                required=True,
                maximum=128,
            )
            property_value = selected_property or "unknown-obligation"
            summary_value = selected_summary or (
                f"Counterexample witness of kind {kind_value}"
            )
            property_class = _text(
                raw.get("property_class") or "formal_verification",
                "property_class",
                required=True,
                maximum=128,
            )
            assumption_values = selected_assumptions
            bounds_value, d3, r3, t3 = _bounded_public(selected_bounds)
            if not isinstance(bounds_value, Mapping):
                bounds_value = {}
            dropped += d3
            redacted += r3
            truncated = truncated or t3
            observation = selected_observation
            repairs = ()
            binding_dict = dict(selected_bindings)
            tool = selected_tool
            semantic = ""
            redaction = RedactionReport(
                dropped_fields=dropped + len(private_artifacts),
                redacted_values=redacted,
            )

        envelope = CounterexampleEnvelope(
            kind=kind_value,
            property_id=property_value,
            summary=summary_value,
            public_payload=public_payload if isinstance(public_payload, Mapping) else {},
            property_class=property_class,
            source_map=selected_source_map,
            tool_id=tool,
            assumption_ids=assumption_values,
            finite_bounds=bounds_value if isinstance(bounds_value, Mapping) else {},
            authority=selected_authority,
            private_artifacts=private_artifacts,
            redaction=redaction,
            bindings=binding_dict,
            observation_policy_id=observation,
            repair_classes=repairs,
            semantic_id=semantic,
            minimized=True,
            truncated=truncated,
        )
        return envelope

    def validate(self, value: Any) -> CounterexampleEnvelope:
        """Fail closed on unknown fields, forged identities, or private leakage."""

        if isinstance(value, CounterexampleEnvelope):
            # Re-run public safety checks via round-trip.
            return CounterexampleEnvelope.from_dict(value.to_dict())
        if isinstance(value, Mapping):
            return CounterexampleEnvelope.from_dict(value)
        if hasattr(value, "to_dict") and callable(value.to_dict):
            converted = value.to_dict()
            if not isinstance(converted, Mapping):
                raise CounterexampleEnvelopeError("to_dict() must return an object")
            return CounterexampleEnvelope.from_dict(converted)
        raise CounterexampleEnvelopeError(
            "validate() requires an envelope, mapping, or typed contract"
        )

    def project_many(
        self, witnesses: Iterable[Any], **kwargs: Any
    ) -> tuple[CounterexampleEnvelope, ...]:
        by_id: dict[str, CounterexampleEnvelope] = {}
        for witness in witnesses:
            envelope = self.project(witness, **kwargs)
            key = envelope.semantic_id or envelope.content_id
            existing = by_id.get(key)
            if existing is None:
                by_id[key] = envelope
                continue
            # Merge private artifact retention handles and assumption lineage.
            merged_artifacts = {
                (item.channel, item.path): item
                for item in existing.private_artifacts + envelope.private_artifacts
            }
            by_id[key] = CounterexampleEnvelope(
                kind=existing.kind,
                property_id=existing.property_id,
                summary=existing.summary,
                public_payload=dict(existing.public_payload),
                property_class=existing.property_class,
                source_map=existing.source_map,
                tool_id=existing.tool_id or envelope.tool_id,
                assumption_ids=tuple(
                    sorted(set(existing.assumption_ids) | set(envelope.assumption_ids))
                ),
                finite_bounds=dict(existing.finite_bounds),
                authority=existing.authority,
                private_artifacts=tuple(merged_artifacts.values()),
                redaction=RedactionReport(
                    dropped_fields=max(
                        existing.redaction.dropped_fields,
                        envelope.redaction.dropped_fields,
                    ),
                    redacted_values=max(
                        existing.redaction.redacted_values,
                        envelope.redaction.redacted_values,
                    ),
                ),
                bindings={**dict(existing.bindings), **dict(envelope.bindings)},
                observation_policy_id=existing.observation_policy_id
                or envelope.observation_policy_id,
                repair_classes=tuple(
                    sorted(set(existing.repair_classes) | set(envelope.repair_classes))
                ),
                semantic_id=existing.semantic_id or envelope.semantic_id,
                minimized=True,
                truncated=existing.truncated or envelope.truncated,
            )
        return tuple(by_id[key] for key in sorted(by_id))


def project_public_counterexample(
    witness: Any, **kwargs: Any
) -> CounterexampleEnvelope:
    """Module-level convenience for :meth:`PublicCounterexampleBoundary.project`."""

    return PublicCounterexampleBoundary().project(witness, **kwargs)


def validate_public_counterexample(value: Any) -> CounterexampleEnvelope:
    """Module-level convenience for :meth:`PublicCounterexampleBoundary.validate`."""

    return PublicCounterexampleBoundary().validate(value)


__all__ = [
    "COUNTEREXAMPLE_ENVELOPE_INTERFACE",
    "COUNTEREXAMPLE_ENVELOPE_SCHEMA",
    "DEFAULT_AUTHORITY",
    "DEFAULT_RETENTION_POLICY_ID",
    "MAX_ENVELOPE_BYTES",
    "MAX_PUBLIC_PAYLOAD_BYTES",
    "PRIVATE_ARTIFACT_REF_SCHEMA",
    "PUBLIC_COUNTEREXAMPLE_BOUNDARY_INTERFACE",
    "ConfidentialityDisposition",
    "CounterexampleEnvelope",
    "CounterexampleEnvelopeError",
    "PrivateArtifactRef",
    "PublicCounterexampleBoundary",
    "RedactionReport",
    "SourceMapRef",
    "project_public_counterexample",
    "validate_public_counterexample",
]
