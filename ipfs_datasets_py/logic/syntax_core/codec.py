"""Versioned codecs for typed logic expressions and elaboration results.

Interfaces (LFP-015):

* ``TypedLogicCodec@1`` — deterministic encode/decode with schema migration
  gates and exact round-trip for supported versions

Codecs never invent defaults that change semantics.  Unknown schema versions
are rejected fail-closed.  Round-trip is required for every admitted payload.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.ast import (
    AstError,
    LogicNode,
    TypedExpression,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _require_mapping,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.syntax_core.elaboration import (
    ElaborationError,
    ElaborationResult,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    LogicSignature,
    SignatureError,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

TYPED_LOGIC_CODEC_INTERFACE: Final = "TypedLogicCodec@1"
CODEC_MODULE_VERSION: Final = "1.0.0"
CODEC_SCHEMA_VERSION: Final = "syntax-typed-logic-codec/v1"
CODED_ENVELOPE_SCHEMA_VERSION: Final = "syntax-typed-logic-envelope/v1"

# Admitted payload schema versions (encode/decode).  Migration paths are
# explicit; unknown versions never silently decode as a neighbour version.
SUPPORTED_TYPED_EXPRESSION_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "syntax-typed-expression/v1",
    }
)
SUPPORTED_LOGIC_NODE_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "syntax-logic-node/v1",
    }
)
SUPPORTED_SIGNATURE_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "syntax-logic-signature/v1",
    }
)
SUPPORTED_ELABORATION_RESULT_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "syntax-elaboration-result/v1",
    }
)
SUPPORTED_ENVELOPE_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        CODED_ENVELOPE_SCHEMA_VERSION,
    }
)


class CodecError(SyntaxContractError):
    """Raised when encode/decode/migration fails closed."""


class CodecKind(str, Enum):
    """Payload kinds admitted by the typed logic codec."""

    TYPED_EXPRESSION = "typed_expression"
    LOGIC_NODE = "logic_node"
    SIGNATURE = "signature"
    ELABORATION_RESULT = "elaboration_result"


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodecEnvelope:
    """Versioned wire envelope around a typed logic payload."""

    kind: CodecKind | str
    schema_version: str
    payload: Mapping[str, Any]
    content_digest: str = ""
    codec_version: str = CODED_ENVELOPE_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.kind, CodecKind):
            kind = self.kind
        else:
            try:
                kind = CodecKind(_text(self.kind, "kind", maximum=64))
            except ValueError as error:
                raise CodecError(
                    f"kind must be a CodecKind value; got {self.kind!r}"
                ) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version", maximum=128),
        )
        if self.codec_version not in SUPPORTED_ENVELOPE_VERSIONS:
            raise CodecError(
                f"unsupported envelope codec_version {self.codec_version!r}"
            )
        payload = _freeze_mapping(self.payload, "payload")
        if not payload:
            raise CodecError("CodecEnvelope.payload must not be empty")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        digest = content_sha256(
            canonical_json_bytes(
                {
                    "kind": kind.value,
                    "payload": _thaw_mapping(payload),
                    "schema_version": self.schema_version,
                }
            )
        )
        if self.content_digest:
            provided = _text(self.content_digest, "content_digest", maximum=64)
            if provided != digest:
                raise CodecError(
                    "content_digest does not match CodecEnvelope payload"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codec_version": self.codec_version,
            "content_digest": self.content_digest,
            "kind": self.kind.value
            if isinstance(self.kind, CodecKind)
            else self.kind,
            "metadata": _thaw_mapping(self.metadata),
            "payload": _thaw_mapping(self.payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CodecEnvelope":
        payload = _require_mapping(data, "CodecEnvelope")
        return cls(
            kind=str(payload.get("kind") or ""),
            schema_version=str(payload.get("schema_version") or ""),
            payload=_require_mapping(payload.get("payload") or {}, "payload"),
            content_digest=str(payload.get("content_digest") or ""),
            codec_version=str(
                payload.get("codec_version") or CODED_ENVELOPE_SCHEMA_VERSION
            ),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
        )


# ---------------------------------------------------------------------------
# TypedLogicCodec@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedLogicCodec:
    """Deterministic typed-logic codec with explicit migration gates.

    Interface: ``TypedLogicCodec@1``.
    """

    codec_id: str = "codec:typed-logic"
    strict_digests: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CODEC_SCHEMA_VERSION

    interface: ClassVar[str] = TYPED_LOGIC_CODEC_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "codec_id", _text(self.codec_id, "codec_id", maximum=256)
        )
        if not isinstance(self.strict_digests, bool):
            raise CodecError("strict_digests must be a bool")
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != CODEC_SCHEMA_VERSION:
            raise CodecError(
                f"unsupported TypedLogicCodec schema_version "
                f"{self.schema_version!r}"
            )

    # -- encode ------------------------------------------------------------

    def encode_typed_expression(
        self, expression: TypedExpression
    ) -> CodecEnvelope:
        if not isinstance(expression, TypedExpression):
            raise CodecError("encode_typed_expression requires a TypedExpression")
        payload = expression.to_dict()
        schema_version = str(
            payload.get("schema_version") or expression.schema_version
        )
        self._require_version(
            schema_version,
            SUPPORTED_TYPED_EXPRESSION_VERSIONS,
            "TypedExpression",
        )
        return CodecEnvelope(
            kind=CodecKind.TYPED_EXPRESSION,
            schema_version=schema_version,
            payload=payload,
        )

    def encode_node(self, node: LogicNode) -> CodecEnvelope:
        if not isinstance(node, LogicNode):
            raise CodecError("encode_node requires a LogicNode")
        payload = node.to_dict()
        schema_version = str(payload.get("schema_version") or node.schema_version)
        self._require_version(
            schema_version, SUPPORTED_LOGIC_NODE_VERSIONS, "LogicNode"
        )
        return CodecEnvelope(
            kind=CodecKind.LOGIC_NODE,
            schema_version=schema_version,
            payload=payload,
        )

    def encode_signature(self, signature: LogicSignature) -> CodecEnvelope:
        if not isinstance(signature, LogicSignature):
            raise CodecError("encode_signature requires a LogicSignature")
        payload = signature.to_dict()
        schema_version = str(
            payload.get("schema_version") or signature.schema_version
        )
        self._require_version(
            schema_version, SUPPORTED_SIGNATURE_VERSIONS, "LogicSignature"
        )
        return CodecEnvelope(
            kind=CodecKind.SIGNATURE,
            schema_version=schema_version,
            payload=payload,
        )

    def encode_elaboration_result(
        self, result: ElaborationResult
    ) -> CodecEnvelope:
        if not isinstance(result, ElaborationResult):
            raise CodecError(
                "encode_elaboration_result requires an ElaborationResult"
            )
        payload = result.to_dict()
        schema_version = str(
            payload.get("schema_version") or result.schema_version
        )
        self._require_version(
            schema_version,
            SUPPORTED_ELABORATION_RESULT_VERSIONS,
            "ElaborationResult",
        )
        return CodecEnvelope(
            kind=CodecKind.ELABORATION_RESULT,
            schema_version=schema_version,
            payload=payload,
        )

    def encode(self, value: object) -> CodecEnvelope:
        """Encode a supported typed-logic value into a :class:`CodecEnvelope`."""

        if isinstance(value, TypedExpression):
            return self.encode_typed_expression(value)
        if isinstance(value, LogicNode):
            return self.encode_node(value)
        if isinstance(value, LogicSignature):
            return self.encode_signature(value)
        if isinstance(value, ElaborationResult):
            return self.encode_elaboration_result(value)
        raise CodecError(
            f"unsupported encode value type {type(value).__name__}"
        )

    def encode_bytes(self, value: object) -> bytes:
        """Canonical JSON bytes of the envelope for *value*."""

        envelope = self.encode(value)
        return canonical_json_bytes(envelope.to_dict())

    def encode_json(self, value: object) -> str:
        return self.encode_bytes(value).decode("ascii")

    # -- decode ------------------------------------------------------------

    def decode_envelope(
        self, data: Mapping[str, Any] | CodecEnvelope | bytes | str
    ) -> CodecEnvelope:
        if isinstance(data, CodecEnvelope):
            return data
        if isinstance(data, (bytes, bytearray)):
            try:
                parsed = json.loads(bytes(data).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CodecError(f"invalid codec bytes: {error}") from error
            data = parsed
        elif isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as error:
                raise CodecError(f"invalid codec JSON: {error}") from error
        envelope = CodecEnvelope.from_dict(_require_mapping(data, "envelope"))
        return envelope

    def decode(self, data: Mapping[str, Any] | CodecEnvelope | bytes | str) -> object:
        """Decode *data* to the concrete typed-logic object."""

        envelope = self.decode_envelope(data)
        kind = envelope.kind
        payload = _thaw_mapping(envelope.payload)
        migrated = self.migrate_payload(
            kind=kind if isinstance(kind, CodecKind) else CodecKind(str(kind)),
            schema_version=envelope.schema_version,
            payload=payload,
        )
        if kind is CodecKind.TYPED_EXPRESSION or kind == CodecKind.TYPED_EXPRESSION.value:
            return self._decode_typed_expression(migrated)
        if kind is CodecKind.LOGIC_NODE or kind == CodecKind.LOGIC_NODE.value:
            return self._decode_node(migrated)
        if kind is CodecKind.SIGNATURE or kind == CodecKind.SIGNATURE.value:
            return self._decode_signature(migrated)
        if (
            kind is CodecKind.ELABORATION_RESULT
            or kind == CodecKind.ELABORATION_RESULT.value
        ):
            return self._decode_elaboration_result(migrated)
        raise CodecError(f"unsupported codec kind {kind!r}")

    def decode_typed_expression(
        self, data: Mapping[str, Any] | CodecEnvelope | bytes | str
    ) -> TypedExpression:
        value = self.decode(data)
        if not isinstance(value, TypedExpression):
            raise CodecError(
                f"expected TypedExpression; got {type(value).__name__}"
            )
        return value

    def decode_node(
        self, data: Mapping[str, Any] | CodecEnvelope | bytes | str
    ) -> LogicNode:
        value = self.decode(data)
        if not isinstance(value, LogicNode):
            raise CodecError(f"expected LogicNode; got {type(value).__name__}")
        return value

    def decode_signature(
        self, data: Mapping[str, Any] | CodecEnvelope | bytes | str
    ) -> LogicSignature:
        value = self.decode(data)
        if not isinstance(value, LogicSignature):
            raise CodecError(
                f"expected LogicSignature; got {type(value).__name__}"
            )
        return value

    def decode_elaboration_result(
        self, data: Mapping[str, Any] | CodecEnvelope | bytes | str
    ) -> ElaborationResult:
        value = self.decode(data)
        if not isinstance(value, ElaborationResult):
            raise CodecError(
                f"expected ElaborationResult; got {type(value).__name__}"
            )
        return value

    # -- round-trip / migration --------------------------------------------

    def round_trip(self, value: object) -> object:
        """Encode then decode *value*; used by tests and migration checks."""

        return self.decode(self.encode(value))

    def round_trip_bytes(self, value: object) -> object:
        return self.decode(self.encode_bytes(value))

    def migrate_payload(
        self,
        *,
        kind: CodecKind,
        schema_version: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Migrate *payload* to the current schema for *kind*.

        Unknown versions are rejected.  Same-version payloads are returned
        unchanged (copy).  Future versions must register an explicit path.
        """

        supported = self._supported_versions(kind)
        self._require_version(schema_version, supported, kind.value)
        # v1 is current for all kinds; identity migration.
        current = next(iter(sorted(supported)))
        if schema_version == current:
            return dict(payload)
        # No multi-hop migrations yet; refuse rather than invent.
        raise CodecError(
            f"no migration path for {kind.value} from {schema_version!r} "
            f"to {current!r}"
        )

    # -- internals ---------------------------------------------------------

    def _supported_versions(self, kind: CodecKind) -> frozenset[str]:
        if kind is CodecKind.TYPED_EXPRESSION:
            return SUPPORTED_TYPED_EXPRESSION_VERSIONS
        if kind is CodecKind.LOGIC_NODE:
            return SUPPORTED_LOGIC_NODE_VERSIONS
        if kind is CodecKind.SIGNATURE:
            return SUPPORTED_SIGNATURE_VERSIONS
        if kind is CodecKind.ELABORATION_RESULT:
            return SUPPORTED_ELABORATION_RESULT_VERSIONS
        raise CodecError(f"unsupported kind {kind!r}")

    def _require_version(
        self,
        version: str,
        supported: frozenset[str],
        label: str,
    ) -> None:
        if version not in supported:
            raise CodecError(
                f"unsupported {label} schema_version {version!r}; "
                f"admitted versions: {sorted(supported)}"
            )

    def _decode_typed_expression(
        self, payload: Mapping[str, Any]
    ) -> TypedExpression:
        schema_version = str(
            payload.get("schema_version") or "syntax-typed-expression/v1"
        )
        self._require_version(
            schema_version,
            SUPPORTED_TYPED_EXPRESSION_VERSIONS,
            "TypedExpression",
        )
        try:
            expression = TypedExpression.from_dict(payload)
        except (AstError, SignatureError, SyntaxContractError) as error:
            raise CodecError(f"typed expression decode failed: {error}") from error
        if self.strict_digests and payload.get("content_digest"):
            if expression.content_digest != payload["content_digest"]:
                raise CodecError(
                    "decoded TypedExpression content_digest mismatch"
                )
        return expression

    def _decode_node(self, payload: Mapping[str, Any]) -> LogicNode:
        schema_version = str(
            payload.get("schema_version") or "syntax-logic-node/v1"
        )
        self._require_version(
            schema_version, SUPPORTED_LOGIC_NODE_VERSIONS, "LogicNode"
        )
        try:
            return LogicNode.from_dict(payload)
        except (AstError, SyntaxContractError) as error:
            raise CodecError(f"logic node decode failed: {error}") from error

    def _decode_signature(self, payload: Mapping[str, Any]) -> LogicSignature:
        schema_version = str(
            payload.get("schema_version") or "syntax-logic-signature/v1"
        )
        self._require_version(
            schema_version, SUPPORTED_SIGNATURE_VERSIONS, "LogicSignature"
        )
        try:
            return LogicSignature.from_dict(payload)
        except (SignatureError, SyntaxContractError) as error:
            raise CodecError(f"signature decode failed: {error}") from error

    def _decode_elaboration_result(
        self, payload: Mapping[str, Any]
    ) -> ElaborationResult:
        schema_version = str(
            payload.get("schema_version") or "syntax-elaboration-result/v1"
        )
        self._require_version(
            schema_version,
            SUPPORTED_ELABORATION_RESULT_VERSIONS,
            "ElaborationResult",
        )
        # Drop derived fields that are recomputed on construction.
        cleaned = dict(payload)
        cleaned.pop("backend_ready", None)
        try:
            result = ElaborationResult.from_dict(cleaned)
        except (ElaborationError, SyntaxContractError, AstError, SignatureError) as error:
            raise CodecError(
                f"elaboration result decode failed: {error}"
            ) from error
        if self.strict_digests and payload.get("content_digest"):
            if result.content_digest != payload["content_digest"]:
                raise CodecError(
                    "decoded ElaborationResult content_digest mismatch"
                )
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "codec_id": self.codec_id,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "schema_version": self.schema_version,
            "strict_digests": self.strict_digests,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypedLogicCodec":
        payload = _require_mapping(data, "TypedLogicCodec")
        interface = payload.get("interface")
        if interface is not None and interface != TYPED_LOGIC_CODEC_INTERFACE:
            raise CodecError(
                f"unsupported TypedLogicCodec interface {interface!r}"
            )
        return cls(
            codec_id=str(payload.get("codec_id") or "codec:typed-logic"),
            strict_digests=bool(payload.get("strict_digests", True)),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or CODEC_SCHEMA_VERSION
            ),
        )


DEFAULT_CODEC: Final = TypedLogicCodec()


def encode(value: object) -> CodecEnvelope:
    """Encode *value* with the default codec."""

    return DEFAULT_CODEC.encode(value)


def decode(data: Mapping[str, Any] | CodecEnvelope | bytes | str) -> object:
    """Decode *data* with the default codec."""

    return DEFAULT_CODEC.decode(data)


def round_trip(value: object) -> object:
    """Round-trip *value* with the default codec."""

    return DEFAULT_CODEC.round_trip(value)


__all__ = [
    "CODED_ENVELOPE_SCHEMA_VERSION",
    "CODEC_MODULE_VERSION",
    "CODEC_SCHEMA_VERSION",
    "DEFAULT_CODEC",
    "SUPPORTED_ELABORATION_RESULT_VERSIONS",
    "SUPPORTED_ENVELOPE_VERSIONS",
    "SUPPORTED_LOGIC_NODE_VERSIONS",
    "SUPPORTED_SIGNATURE_VERSIONS",
    "SUPPORTED_TYPED_EXPRESSION_VERSIONS",
    "TYPED_LOGIC_CODEC_INTERFACE",
    "CodecEnvelope",
    "CodecError",
    "CodecKind",
    "TypedLogicCodec",
    "decode",
    "encode",
    "round_trip",
]
