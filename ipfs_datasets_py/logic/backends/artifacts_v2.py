"""Compiled and parsed target artifact contracts (Wave-2).

Interfaces (LFP2-008):

* ``CompiledLogicArtifact@1`` — target text/bytes bound to typed origin,
  source map, compiler, encoding, toolchain request, assumptions, losses,
  bounds, and authority ceiling
* ``ParsedTargetArtifact@1`` — decoded provider output bound to the compiled
  artifact, request, result identities, and evidence kind

Admission is fail-closed:

* raw target ingress without a compiled artifact is rejected
* raw result egress without a parsed target artifact is rejected
* unidentifiable target/result content (missing digests, missing lineage,
  free-form routing) fails before any executable backend may accept or
  return it

Raw target text may exist *inside* ``CompiledLogicArtifact``, but cannot
bypass typed family/profile/notation/encoding identity, source map,
assumptions, losses, resource bounds, and authority ceiling.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    CrossNamespaceRequestError,
    MissingBoundsError,
    RequestAdmissionError,
    RequestAuthorityCeiling,
    RequestBounds,
    RequestV2Error,
    _check_authority_overclaim,
    _coerce_authority,
    _coerce_identity,
    _feature_tuple,
    _forbid_metadata_routing,
    _identity_dict,
    _status_value,
)
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    MAX_SOURCE_BYTES,
    MAX_STRING_CHARS,
    SourceMap,
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
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

COMPILED_LOGIC_ARTIFACT_INTERFACE: Final = "CompiledLogicArtifact@1"
PARSED_TARGET_ARTIFACT_INTERFACE: Final = "ParsedTargetArtifact@1"

COMPILED_LOGIC_ARTIFACT_SCHEMA_VERSION: Final = "compiled-logic-artifact/v1"
PARSED_TARGET_ARTIFACT_SCHEMA_VERSION: Final = "parsed-target-artifact/v1"
ARTIFACTS_V2_MODULE_VERSION: Final = "1.0.0"

_COMPILER_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_LOSS_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")

# Metadata keys that re-introduce untyped raw target/result routing.
_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "payload",
        "raw_formula",
        "raw_source",
        "target_source",
        "target_text",
        "raw_target",
        "raw_result",
        "logic_family",
        "family_string",
        "opaque_extension",
        "arbitrary_payload",
        "free_form_family",
        "mock_result",
        "metadata_only_result",
    }
)


class ArtifactV2Error(SyntaxContractError):
    """Raised when a compiled/parsed target artifact is malformed."""


class ArtifactLineageError(ArtifactV2Error):
    """Raised when source, request, or compiled-artifact lineage is broken."""


class RawTargetAdmissionError(ArtifactV2Error, RequestAdmissionError):
    """Raised when raw target content attempts to bypass CompiledLogicArtifact."""


class RawResultAdmissionError(ArtifactV2Error, RequestAdmissionError):
    """Raised when raw result content attempts to bypass ParsedTargetArtifact."""


class CompiledArtifactStatus(str, Enum):
    """Outcome of a compiled logic artifact."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"


class ParsedTargetStatus(str, Enum):
    """Outcome of a parsed target artifact."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


def _compiler_id(value: object, field_name: str = "compiler_id") -> str:
    text = _text(value, field_name, maximum=128)
    if not _COMPILER_ID_RE.fullmatch(text):
        raise ArtifactV2Error(
            f"{field_name} must be a dotted compiler identity; got {text!r}"
        )
    return text


def _loss_tuple(value: object, field_name: str) -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=128)
        for item in _require_sequence(value, field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ArtifactV2Error(f"{field_name} exceeds hard ceiling")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not _LOSS_ID_RE.fullmatch(item):
            raise ArtifactV2Error(
                f"{field_name} item must be a loss identity; got {item!r}"
            )
        if item in seen:
            raise ArtifactV2Error(f"{field_name} values must be unique")
        seen.add(item)
        ordered.append(item)
    return tuple(sorted(ordered))


def _assumption_tuple(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _record_id(item, f"{field_name} item")
                for item in _require_sequence(value, field_name)
            }
        )
    )


def _optional_sha256(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _sha256_hex(value, field_name)


def _target_bytes(
    target_bytes: object,
    target_text: object,
    field_name: str = "target",
) -> tuple[bytes, str]:
    """Normalize target content to exact bytes plus optional text form."""

    has_bytes = target_bytes is not None and target_bytes != b"" and target_bytes != ""
    has_text = target_text is not None and target_text != ""

    if not has_bytes and not has_text:
        raise RawTargetAdmissionError(
            f"{field_name} requires identifiable target_bytes or target_text; "
            "unidentifiable raw target content is rejected"
        )

    text_value = ""
    if has_text:
        if not isinstance(target_text, str):
            raise ArtifactV2Error(f"{field_name}_text must be a string")
        if "\x00" in target_text:
            raise ArtifactV2Error(f"{field_name}_text must not contain NUL")
        if len(target_text) > MAX_STRING_CHARS * 64:
            raise ArtifactV2Error(f"{field_name}_text exceeds hard ceiling")
        text_value = target_text

    if has_bytes:
        raw = target_bytes
        if isinstance(raw, bytearray):
            raw = bytes(raw)
        if isinstance(raw, str):
            # Wire form may carry base-less utf-8 text; require explicit text.
            raise ArtifactV2Error(
                f"{field_name}_bytes must be exact bytes, not a string"
            )
        if type(raw) is not bytes:
            raise ArtifactV2Error(f"{field_name}_bytes must be exact bytes")
        if len(raw) > MAX_SOURCE_BYTES:
            raise ArtifactV2Error(
                f"{field_name}_bytes exceeds hard ceiling of {MAX_SOURCE_BYTES}"
            )
        if b"\x00" in raw:
            raise ArtifactV2Error(f"{field_name}_bytes must not contain NUL")
        if text_value:
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ArtifactV2Error(
                    f"{field_name}_bytes is not valid utf-8 while "
                    f"{field_name}_text is provided: {error}"
                ) from error
            if decoded != text_value:
                raise ArtifactV2Error(
                    f"{field_name}_text does not match {field_name}_bytes"
                )
        return raw, text_value

    encoded = text_value.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ArtifactV2Error(
            f"{field_name}_text exceeds hard ceiling of {MAX_SOURCE_BYTES} bytes"
        )
    return encoded, text_value


def _forbid_artifact_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    try:
        _forbid_metadata_routing(metadata, field_name)
    except RequestV2Error as error:
        raise ArtifactV2Error(str(error)) from error
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS:
            raise RawTargetAdmissionError(
                f"{field_name} rejects free-form raw routing key {key!r}; "
                "use CompiledLogicArtifact@1 / ParsedTargetArtifact@1 fields"
            )


def _coerce_request_bounds(
    value: object, field_name: str = "bounds"
) -> RequestBounds:
    if value is None:
        raise MissingBoundsError(
            f"{field_name} are required; compiled artifacts reject missing bounds"
        )
    if isinstance(value, RequestBounds):
        return value
    try:
        return RequestBounds.from_dict(_require_mapping(value, field_name))
    except MissingBoundsError:
        raise
    except RequestV2Error as error:
        raise ArtifactV2Error(str(error)) from error


def _identity_or_error(
    value: object,
    expected: NamespaceKind,
    field_name: str,
) -> LogicIdentity:
    try:
        return _coerce_identity(value, expected, field_name)
    except CrossNamespaceRequestError:
        raise
    except RequestV2Error as error:
        message = str(error)
        if "requires namespace" in message:
            raise CrossNamespaceRequestError(message) from error
        raise ArtifactV2Error(message) from error


# ---------------------------------------------------------------------------
# CompiledLogicArtifact@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompiledLogicArtifact:
    """Target text/bytes gated by typed origin and compilation receipts.

    Interface: ``CompiledLogicArtifact@1``.

    Every admitted executable path must present this envelope before a
    provider may accept target content.  Raw target text is permitted only
    as identified content bound to:

    * source document + typed-expression identity
    * BackendRequest@2 identity (request_id + request_digest)
    * source map
    * compiler / encoding / family / profile / notation identities
    * assumptions, losses, finite bounds, and authority ceiling
    """

    artifact_id: str
    request_id: str
    request_digest: str
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
    compiler_id: str
    bounds: RequestBounds | Mapping[str, Any]
    target_bytes: bytes = b""
    target_text: str = ""
    target_digest: str = ""
    source_map: SourceMap | Mapping[str, Any] | None = None
    authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED
    evidence_kind: LogicIdentity | Mapping[str, Any] | str | None = None
    features: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    loss_ids: tuple[str, ...] = ()
    toolchain_id: str = ""
    obligation_id: str = ""
    obligation_digest: str = ""
    status: CompiledArtifactStatus | str = CompiledArtifactStatus.OK
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = COMPILED_LOGIC_ARTIFACT_SCHEMA_VERSION

    interface: ClassVar[str] = COMPILED_LOGIC_ARTIFACT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "request_digest", _sha256_hex(self.request_digest, "request_digest")
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
            _identity_or_error(self.family, NamespaceKind.FAMILY, "family"),
        )
        object.__setattr__(
            self,
            "profile",
            _identity_or_error(self.profile, NamespaceKind.PROFILE, "profile"),
        )
        object.__setattr__(
            self,
            "property",
            _identity_or_error(self.property, NamespaceKind.PROPERTY, "property"),
        )
        object.__setattr__(
            self,
            "view",
            _identity_or_error(self.view, NamespaceKind.VIEW, "view"),
        )
        object.__setattr__(
            self,
            "notation",
            _identity_or_error(self.notation, NamespaceKind.NOTATION, "notation"),
        )
        object.__setattr__(
            self,
            "encoding",
            _identity_or_error(self.encoding, NamespaceKind.ENCODING, "encoding"),
        )

        object.__setattr__(self, "compiler_id", _compiler_id(self.compiler_id))
        if self.toolchain_id:
            object.__setattr__(
                self, "toolchain_id", _record_id(self.toolchain_id, "toolchain_id")
            )
        if self.obligation_id:
            object.__setattr__(
                self, "obligation_id", _record_id(self.obligation_id, "obligation_id")
            )
        if self.obligation_digest:
            object.__setattr__(
                self,
                "obligation_digest",
                _sha256_hex(self.obligation_digest, "obligation_digest"),
            )

        bounds = _coerce_request_bounds(self.bounds, "bounds")
        object.__setattr__(self, "bounds", bounds)

        ceiling = _coerce_authority(self.authority_ceiling)
        object.__setattr__(self, "authority_ceiling", ceiling)

        if self.evidence_kind is None or self.evidence_kind == "":
            object.__setattr__(self, "evidence_kind", None)
        else:
            evidence = _identity_or_error(
                self.evidence_kind, NamespaceKind.EVIDENCE, "evidence_kind"
            )
            _check_authority_overclaim(ceiling, evidence)
            object.__setattr__(self, "evidence_kind", evidence)

        object.__setattr__(self, "features", _feature_tuple(self.features, "features"))
        object.__setattr__(
            self, "assumption_ids", _assumption_tuple(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(self, "loss_ids", _loss_tuple(self.loss_ids, "loss_ids"))

        if isinstance(self.status, CompiledArtifactStatus):
            status = self.status
        else:
            try:
                status = CompiledArtifactStatus(
                    _text(self.status, "status", maximum=32)
                )
            except ValueError as error:
                raise ArtifactV2Error(
                    f"status must be a CompiledArtifactStatus value; "
                    f"got {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        has_target_content = bool(self.target_bytes) or bool(self.target_text)
        if has_target_content:
            raw_bytes, text_value = _target_bytes(
                self.target_bytes, self.target_text, field_name="target"
            )
            object.__setattr__(self, "target_bytes", raw_bytes)
            object.__setattr__(self, "target_text", text_value)
            computed_target_digest = content_sha256(raw_bytes)
            if self.target_digest:
                provided = _sha256_hex(self.target_digest, "target_digest")
                if provided != computed_target_digest:
                    raise ArtifactV2Error(
                        "target_digest does not match target content identity"
                    )
                object.__setattr__(self, "target_digest", provided)
            else:
                object.__setattr__(self, "target_digest", computed_target_digest)
        elif self.target_digest:
            # Identity-only form: content may live in an external CAS; the
            # digest alone still gates unidentifiable raw ingress.
            object.__setattr__(self, "target_bytes", b"")
            object.__setattr__(self, "target_text", "")
            object.__setattr__(
                self, "target_digest", _sha256_hex(self.target_digest, "target_digest")
            )
        else:
            raise RawTargetAdmissionError(
                "CompiledLogicArtifact requires identifiable target content "
                "(target_bytes, target_text, or target_digest)"
            )

        if self.source_map is None:
            if status is CompiledArtifactStatus.OK:
                raise RawTargetAdmissionError(
                    "CompiledLogicArtifact@1 status ok requires a source_map; "
                    "raw target ingress without source mapping is rejected"
                )
            object.__setattr__(self, "source_map", None)
        else:
            if isinstance(self.source_map, SourceMap):
                source_map = self.source_map
            else:
                source_map = SourceMap.from_dict(
                    _require_mapping(self.source_map, "source_map")
                )
            if source_map.document_id and source_map.document_id != self.document_id:
                raise ArtifactLineageError(
                    "SourceMap.document_id must match CompiledLogicArtifact."
                    "document_id"
                )
            object.__setattr__(self, "source_map", source_map)

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_artifact_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != COMPILED_LOGIC_ARTIFACT_SCHEMA_VERSION:
            raise ArtifactV2Error(
                f"unsupported CompiledLogicArtifact schema_version "
                f"{self.schema_version!r}"
            )

        if status is CompiledArtifactStatus.OK:
            if not self.document_id or not self.source_digest:
                raise RawTargetAdmissionError(
                    "admitted CompiledLogicArtifact requires document_id and "
                    "source_digest"
                )
            if not self.expression_id or not self.expression_digest:
                raise RawTargetAdmissionError(
                    "admitted CompiledLogicArtifact requires expression_id and "
                    "expression_digest"
                )
            if not self.request_id or not self.request_digest:
                raise RawTargetAdmissionError(
                    "admitted CompiledLogicArtifact requires request_id and "
                    "request_digest bound to BackendRequest@2"
                )
            if not self.target_digest:
                raise RawTargetAdmissionError(
                    "admitted CompiledLogicArtifact requires target_digest"
                )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise ArtifactV2Error(
                    "content_digest does not match CompiledLogicArtifact content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        evidence = self.evidence_kind
        source_map = self.source_map
        return {
            "assumption_ids": list(self.assumption_ids),
            "authority_ceiling": _status_value(self.authority_ceiling),
            "bounds": self.bounds.to_dict(),  # type: ignore[union-attr]
            "compiler_id": self.compiler_id,
            "document_id": self.document_id,
            "encoding": _identity_dict(self.encoding),  # type: ignore[arg-type]
            "evidence_kind": None
            if evidence is None
            else _identity_dict(evidence),  # type: ignore[arg-type]
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "family": _identity_dict(self.family),  # type: ignore[arg-type]
            "features": list(self.features),
            "interface": self.interface,
            "loss_ids": list(self.loss_ids),
            "notation": _identity_dict(self.notation),  # type: ignore[arg-type]
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "profile": _identity_dict(self.profile),  # type: ignore[arg-type]
            "property": _identity_dict(self.property),  # type: ignore[arg-type]
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_map": None if source_map is None else source_map.to_dict(),
            "status": _status_value(self.status),
            "target_digest": self.target_digest,
            "target_text": self.target_text,
            "toolchain_id": self.toolchain_id,
            "view": _identity_dict(self.view),  # type: ignore[arg-type]
            # target_bytes identity is captured by target_digest only so the
            # identity payload remains JSON-safe and deterministic.
            "artifact_id": self.artifact_id,
        }

    @property
    def is_admitted(self) -> bool:
        return self.status is CompiledArtifactStatus.OK

    def require_admitted(self) -> "CompiledLogicArtifact":
        """Return self when admitted for executable backend use."""

        if not self.is_admitted:
            raise RawTargetAdmissionError(
                f"CompiledLogicArtifact {self.artifact_id} is not admitted "
                f"(status={_status_value(self.status)}); executable backends "
                "require status ok with bound origin, source map, and "
                "target identity"
            )
        if self.source_map is None:
            raise RawTargetAdmissionError(
                f"CompiledLogicArtifact {self.artifact_id} lacks source_map"
            )
        if not self.target_digest:
            raise RawTargetAdmissionError(
                f"CompiledLogicArtifact {self.artifact_id} lacks target_digest"
            )
        return self

    def validate_against_request(self, request: BackendRequestV2) -> None:
        """Cross-check lineage against a concrete BackendRequest@2."""

        if not isinstance(request, BackendRequestV2):
            raise ArtifactV2Error(
                "validate_against_request requires BackendRequestV2"
            )
        if request.request_id != self.request_id:
            raise ArtifactLineageError(
                "request_id does not match BackendRequestV2.request_id"
            )
        if request.content_digest != self.request_digest:
            raise ArtifactLineageError(
                "request_digest does not match BackendRequestV2.content_digest"
            )
        if request.document_id != self.document_id:
            raise ArtifactLineageError(
                "document_id does not match BackendRequestV2.document_id"
            )
        if request.source_digest != self.source_digest:
            raise ArtifactLineageError(
                "source_digest does not match BackendRequestV2.source_digest"
            )
        if request.expression_id != self.expression_id:
            raise ArtifactLineageError(
                "expression_id does not match BackendRequestV2.expression_id"
            )
        if request.expression_digest != self.expression_digest:
            raise ArtifactLineageError(
                "expression_digest does not match BackendRequestV2."
                "expression_digest"
            )
        if isinstance(request.family, LogicIdentity) and isinstance(
            self.family, LogicIdentity
        ):
            if request.family.value != self.family.value:
                raise ArtifactLineageError(
                    "family does not match BackendRequestV2.family"
                )
        if isinstance(request.encoding, LogicIdentity) and isinstance(
            self.encoding, LogicIdentity
        ):
            if request.encoding.value != self.encoding.value:
                raise ArtifactLineageError(
                    "encoding does not match BackendRequestV2.encoding"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        # Preserve exact target bytes as a utf-8 text mirror when possible;
        # identity always uses target_digest.
        payload["target_bytes_digest"] = self.target_digest
        payload["target_byte_length"] = len(self.target_bytes)
        return payload

    def to_wire_dict(self) -> dict[str, Any]:
        """Serialize including hex-encoded target bytes for transport."""

        payload = self.to_dict()
        payload["target_bytes_hex"] = self.target_bytes.hex()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompiledLogicArtifact":
        payload = _require_mapping(data, "CompiledLogicArtifact")
        interface = payload.get("interface")
        if interface is not None and interface != COMPILED_LOGIC_ARTIFACT_INTERFACE:
            raise ArtifactV2Error(
                f"unsupported CompiledLogicArtifact interface {interface!r}"
            )
        if "payload" in payload and "target_digest" not in payload:
            raise RawTargetAdmissionError(
                "CompiledLogicArtifact@1 rejects free-form payload routing; "
                "bind target content through target_text/target_bytes with "
                "typed origin fields"
            )
        if "raw_target" in payload or "target_source" in payload:
            raise RawTargetAdmissionError(
                "CompiledLogicArtifact@1 rejects untyped raw_target/"
                "target_source fields; use target_text/target_bytes with "
                "source_map and request lineage"
            )
        if "bounds" not in payload or payload.get("bounds") is None:
            raise MissingBoundsError(
                "CompiledLogicArtifact@1 requires bounds; missing bounds "
                "fail closed"
            )

        target_bytes: bytes | object = b""
        if "target_bytes_hex" in payload and payload.get("target_bytes_hex"):
            try:
                target_bytes = bytes.fromhex(str(payload["target_bytes_hex"]))
            except ValueError as error:
                raise ArtifactV2Error(
                    "target_bytes_hex is not valid hexadecimal"
                ) from error
        elif "target_bytes" in payload and payload.get("target_bytes") not in (
            None,
            "",
            b"",
        ):
            raw = payload["target_bytes"]
            if isinstance(raw, (bytes, bytearray)):
                target_bytes = bytes(raw)
            elif isinstance(raw, str):
                target_bytes = raw.encode("utf-8")
            else:
                raise ArtifactV2Error("target_bytes must be bytes or utf-8 text")

        source_map_payload = payload.get("source_map")
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            request_digest=str(payload.get("request_digest") or ""),
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
            compiler_id=str(payload.get("compiler_id") or ""),
            bounds=payload["bounds"],
            target_bytes=target_bytes if target_bytes != b"" else b"",
            target_text=str(payload.get("target_text") or ""),
            target_digest=str(payload.get("target_digest") or ""),
            source_map=(
                None
                if source_map_payload is None
                else source_map_payload
            ),
            authority_ceiling=str(
                payload.get("authority_ceiling")
                or RequestAuthorityCeiling.BOUNDED.value
            ),
            evidence_kind=payload.get("evidence_kind"),
            features=tuple(payload.get("features") or ()),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            loss_ids=tuple(payload.get("loss_ids") or ()),
            toolchain_id=str(payload.get("toolchain_id") or ""),
            obligation_id=str(payload.get("obligation_id") or ""),
            obligation_digest=str(payload.get("obligation_digest") or ""),
            status=str(payload.get("status") or CompiledArtifactStatus.OK.value),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or COMPILED_LOGIC_ARTIFACT_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_request(
        cls,
        request: BackendRequestV2,
        *,
        artifact_id: str,
        compiler_id: str,
        target_text: str = "",
        target_bytes: bytes = b"",
        source_map: SourceMap | Mapping[str, Any] | None = None,
        assumption_ids: Sequence[str] = (),
        loss_ids: Sequence[str] = (),
        toolchain_id: str = "",
        status: CompiledArtifactStatus | str = CompiledArtifactStatus.OK,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CompiledLogicArtifact":
        """Build a compiled artifact bound to an admitted BackendRequest@2."""

        if not isinstance(request, BackendRequestV2):
            raise ArtifactV2Error("from_request requires BackendRequestV2")
        return cls(
            artifact_id=artifact_id,
            request_id=request.request_id,
            request_digest=request.content_digest,
            document_id=request.document_id,
            source_digest=request.source_digest,
            expression_id=request.expression_id,
            expression_digest=request.expression_digest,
            family=request.family,
            profile=request.profile,
            property=request.property,
            view=request.view,
            notation=request.notation,
            encoding=request.encoding,
            compiler_id=compiler_id,
            bounds=request.bounds,
            target_text=target_text,
            target_bytes=target_bytes,
            source_map=source_map,
            authority_ceiling=request.authority_ceiling,
            evidence_kind=request.evidence_kind,
            features=request.features,
            assumption_ids=tuple(assumption_ids) or request.assumption_ids,
            loss_ids=tuple(loss_ids),
            toolchain_id=toolchain_id,
            obligation_id=request.obligation_id,
            obligation_digest=request.obligation_digest,
            status=status,
            metadata=dict(metadata or {}),
        )


def admit_compiled_target(
    request: BackendRequestV2,
    *,
    artifact_id: str,
    compiler_id: str,
    target_text: str = "",
    target_bytes: bytes = b"",
    source_map: SourceMap | Mapping[str, Any] | None = None,
    assumption_ids: Sequence[str] = (),
    loss_ids: Sequence[str] = (),
    toolchain_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> CompiledLogicArtifact:
    """Gate raw target content through CompiledLogicArtifact@1.

    Executable backends must call this (or construct
    :class:`CompiledLogicArtifact` equivalently) before accepting target
    text/bytes.  Unidentifiable raw content fails closed.
    """

    if not isinstance(request, BackendRequestV2):
        raise RawTargetAdmissionError(
            "admit_compiled_target requires BackendRequest@2; raw target "
            "ingress without a typed request is rejected"
        )
    if not target_text and not target_bytes:
        raise RawTargetAdmissionError(
            "admit_compiled_target requires identifiable target_text or "
            "target_bytes"
        )
    if source_map is None:
        raise RawTargetAdmissionError(
            "admit_compiled_target requires a source_map; raw target ingress "
            "without source mapping is rejected"
        )
    artifact = CompiledLogicArtifact.from_request(
        request,
        artifact_id=artifact_id,
        compiler_id=compiler_id,
        target_text=target_text,
        target_bytes=target_bytes,
        source_map=source_map,
        assumption_ids=assumption_ids,
        loss_ids=loss_ids,
        toolchain_id=toolchain_id,
        status=CompiledArtifactStatus.OK,
        metadata=metadata,
    )
    return artifact.require_admitted()


# ---------------------------------------------------------------------------
# ParsedTargetArtifact@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedTargetArtifact:
    """Decoded provider output bound to compiled-artifact and result identity.

    Interface: ``ParsedTargetArtifact@1``.

    Executable backends must return results through this envelope.  Raw
    stdout/stderr or free-form result blobs without compiled-artifact
    lineage, output digest, and evidence kind are rejected.
    """

    artifact_id: str
    compiled_artifact_id: str
    compiled_artifact_digest: str
    request_id: str
    request_digest: str
    provider: LogicIdentity | Mapping[str, Any] | str
    evidence_kind: LogicIdentity | Mapping[str, Any] | str
    result_kind: str
    output_digest: str
    output_bytes: bytes = b""
    output_text: str = ""
    result_digest: str = ""
    decoded_evidence_digest: str = ""
    target_digest: str = ""
    document_id: str = ""
    source_digest: str = ""
    expression_id: str = ""
    expression_digest: str = ""
    status: ParsedTargetStatus | str = ParsedTargetStatus.OK
    authority_ceiling: RequestAuthorityCeiling | str = RequestAuthorityCeiling.BOUNDED
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSED_TARGET_ARTIFACT_SCHEMA_VERSION

    interface: ClassVar[str] = PARSED_TARGET_ARTIFACT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "compiled_artifact_id",
            _record_id(self.compiled_artifact_id, "compiled_artifact_id"),
        )
        object.__setattr__(
            self,
            "compiled_artifact_digest",
            _sha256_hex(self.compiled_artifact_digest, "compiled_artifact_digest"),
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "request_digest", _sha256_hex(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "provider",
            _identity_or_error(self.provider, NamespaceKind.PROVIDER, "provider"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _identity_or_error(
                self.evidence_kind, NamespaceKind.EVIDENCE, "evidence_kind"
            ),
        )
        object.__setattr__(
            self,
            "result_kind",
            _text(self.result_kind, "result_kind", maximum=64),
        )
        if not re.fullmatch(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$", self.result_kind):
            raise ArtifactV2Error(
                f"result_kind must be a dotted result identity; got "
                f"{self.result_kind!r}"
            )

        has_output = bool(self.output_bytes) or bool(self.output_text) or bool(
            self.output_digest
        )
        if not has_output:
            raise RawResultAdmissionError(
                "ParsedTargetArtifact requires identifiable output content "
                "(output_bytes, output_text, or output_digest); unidentifiable "
                "raw result content is rejected"
            )

        if self.output_bytes or self.output_text:
            raw_bytes, text_value = _target_bytes(
                self.output_bytes, self.output_text, field_name="output"
            )
            object.__setattr__(self, "output_bytes", raw_bytes)
            object.__setattr__(self, "output_text", text_value)
            computed = content_sha256(raw_bytes)
            if self.output_digest:
                provided = _sha256_hex(self.output_digest, "output_digest")
                if provided != computed:
                    raise ArtifactV2Error(
                        "output_digest does not match output content identity"
                    )
                object.__setattr__(self, "output_digest", provided)
            else:
                object.__setattr__(self, "output_digest", computed)
        else:
            object.__setattr__(
                self, "output_digest", _sha256_hex(self.output_digest, "output_digest")
            )
            object.__setattr__(self, "output_bytes", b"")
            object.__setattr__(self, "output_text", "")

        if self.result_digest:
            object.__setattr__(
                self, "result_digest", _sha256_hex(self.result_digest, "result_digest")
            )
        else:
            # Result identity defaults to output identity when not split.
            object.__setattr__(self, "result_digest", self.output_digest)

        object.__setattr__(
            self,
            "decoded_evidence_digest",
            _optional_sha256(
                self.decoded_evidence_digest, "decoded_evidence_digest"
            ),
        )
        object.__setattr__(
            self, "target_digest", _optional_sha256(self.target_digest, "target_digest")
        )
        if self.document_id:
            object.__setattr__(
                self, "document_id", _record_id(self.document_id, "document_id")
            )
        if self.source_digest:
            object.__setattr__(
                self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
            )
        if self.expression_id:
            object.__setattr__(
                self, "expression_id", _record_id(self.expression_id, "expression_id")
            )
        if self.expression_digest:
            object.__setattr__(
                self,
                "expression_digest",
                _sha256_hex(self.expression_digest, "expression_digest"),
            )

        if isinstance(self.status, ParsedTargetStatus):
            status = self.status
        else:
            try:
                status = ParsedTargetStatus(
                    _text(self.status, "status", maximum=32)
                )
            except ValueError as error:
                raise ArtifactV2Error(
                    f"status must be a ParsedTargetStatus value; got "
                    f"{self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        ceiling = _coerce_authority(self.authority_ceiling)
        _check_authority_overclaim(ceiling, self.evidence_kind)  # type: ignore[arg-type]
        object.__setattr__(self, "authority_ceiling", ceiling)

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_artifact_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != PARSED_TARGET_ARTIFACT_SCHEMA_VERSION:
            raise ArtifactV2Error(
                f"unsupported ParsedTargetArtifact schema_version "
                f"{self.schema_version!r}"
            )

        if status is ParsedTargetStatus.OK:
            if not self.compiled_artifact_id or not self.compiled_artifact_digest:
                raise RawResultAdmissionError(
                    "admitted ParsedTargetArtifact requires compiled_artifact "
                    "identity; raw results without compilation lineage are "
                    "rejected"
                )
            if not self.request_id or not self.request_digest:
                raise RawResultAdmissionError(
                    "admitted ParsedTargetArtifact requires request identity"
                )
            if not self.output_digest or not self.result_digest:
                raise RawResultAdmissionError(
                    "admitted ParsedTargetArtifact requires output_digest and "
                    "result_digest"
                )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise ArtifactV2Error(
                    "content_digest does not match ParsedTargetArtifact content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_ceiling": _status_value(self.authority_ceiling),
            "compiled_artifact_digest": self.compiled_artifact_digest,
            "compiled_artifact_id": self.compiled_artifact_id,
            "decoded_evidence_digest": self.decoded_evidence_digest,
            "document_id": self.document_id,
            "evidence_kind": _identity_dict(self.evidence_kind),  # type: ignore[arg-type]
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "interface": self.interface,
            "output_digest": self.output_digest,
            "output_text": self.output_text,
            "provider": _identity_dict(self.provider),  # type: ignore[arg-type]
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_digest": self.result_digest,
            "result_kind": self.result_kind,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "status": _status_value(self.status),
            "target_digest": self.target_digest,
        }

    @property
    def is_admitted(self) -> bool:
        return self.status is ParsedTargetStatus.OK

    def require_admitted(self) -> "ParsedTargetArtifact":
        """Return self when admitted as an executable backend result."""

        if not self.is_admitted:
            raise RawResultAdmissionError(
                f"ParsedTargetArtifact {self.artifact_id} is not admitted "
                f"(status={_status_value(self.status)}); executable backends "
                "must return identifiable parsed results"
            )
        if not self.compiled_artifact_digest or not self.output_digest:
            raise RawResultAdmissionError(
                f"ParsedTargetArtifact {self.artifact_id} lacks required "
                "compiled/output identity"
            )
        return self

    def validate_against_compiled(
        self, compiled: CompiledLogicArtifact
    ) -> None:
        """Cross-check lineage against a concrete CompiledLogicArtifact."""

        if not isinstance(compiled, CompiledLogicArtifact):
            raise ArtifactV2Error(
                "validate_against_compiled requires CompiledLogicArtifact"
            )
        if compiled.artifact_id != self.compiled_artifact_id:
            raise ArtifactLineageError(
                "compiled_artifact_id does not match CompiledLogicArtifact"
            )
        if compiled.content_digest != self.compiled_artifact_digest:
            raise ArtifactLineageError(
                "compiled_artifact_digest does not match "
                "CompiledLogicArtifact.content_digest"
            )
        if compiled.request_id != self.request_id:
            raise ArtifactLineageError(
                "request_id does not match CompiledLogicArtifact.request_id"
            )
        if compiled.request_digest != self.request_digest:
            raise ArtifactLineageError(
                "request_digest does not match CompiledLogicArtifact."
                "request_digest"
            )
        if self.target_digest and compiled.target_digest != self.target_digest:
            raise ArtifactLineageError(
                "target_digest does not match CompiledLogicArtifact.target_digest"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        payload["output_byte_length"] = len(self.output_bytes)
        return payload

    def to_wire_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload["output_bytes_hex"] = self.output_bytes.hex()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParsedTargetArtifact":
        payload = _require_mapping(data, "ParsedTargetArtifact")
        interface = payload.get("interface")
        if interface is not None and interface != PARSED_TARGET_ARTIFACT_INTERFACE:
            raise ArtifactV2Error(
                f"unsupported ParsedTargetArtifact interface {interface!r}"
            )
        if "raw_result" in payload or "raw_output" in payload:
            raise RawResultAdmissionError(
                "ParsedTargetArtifact@1 rejects untyped raw_result/raw_output "
                "fields; bind output through output_text/output_bytes with "
                "compiled-artifact lineage"
            )
        if "payload" in payload and "output_digest" not in payload:
            raise RawResultAdmissionError(
                "ParsedTargetArtifact@1 rejects free-form payload routing for "
                "results"
            )

        output_bytes: bytes = b""
        if "output_bytes_hex" in payload and payload.get("output_bytes_hex"):
            try:
                output_bytes = bytes.fromhex(str(payload["output_bytes_hex"]))
            except ValueError as error:
                raise ArtifactV2Error(
                    "output_bytes_hex is not valid hexadecimal"
                ) from error
        elif "output_bytes" in payload and payload.get("output_bytes") not in (
            None,
            "",
            b"",
        ):
            raw = payload["output_bytes"]
            if isinstance(raw, (bytes, bytearray)):
                output_bytes = bytes(raw)
            elif isinstance(raw, str):
                output_bytes = raw.encode("utf-8")
            else:
                raise ArtifactV2Error("output_bytes must be bytes or utf-8 text")

        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            compiled_artifact_id=str(payload.get("compiled_artifact_id") or ""),
            compiled_artifact_digest=str(
                payload.get("compiled_artifact_digest") or ""
            ),
            request_id=str(payload.get("request_id") or ""),
            request_digest=str(payload.get("request_digest") or ""),
            provider=payload.get("provider") or "",
            evidence_kind=payload.get("evidence_kind") or "",
            result_kind=str(payload.get("result_kind") or ""),
            output_digest=str(payload.get("output_digest") or ""),
            output_bytes=output_bytes,
            output_text=str(payload.get("output_text") or ""),
            result_digest=str(payload.get("result_digest") or ""),
            decoded_evidence_digest=str(
                payload.get("decoded_evidence_digest") or ""
            ),
            target_digest=str(payload.get("target_digest") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            expression_id=str(payload.get("expression_id") or ""),
            expression_digest=str(payload.get("expression_digest") or ""),
            status=str(payload.get("status") or ParsedTargetStatus.OK.value),
            authority_ceiling=str(
                payload.get("authority_ceiling")
                or RequestAuthorityCeiling.BOUNDED.value
            ),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or PARSED_TARGET_ARTIFACT_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_compiled(
        cls,
        compiled: CompiledLogicArtifact,
        *,
        artifact_id: str,
        provider: LogicIdentity | Mapping[str, Any] | str,
        result_kind: str,
        output_text: str = "",
        output_bytes: bytes = b"",
        output_digest: str = "",
        result_digest: str = "",
        decoded_evidence_digest: str = "",
        evidence_kind: LogicIdentity | Mapping[str, Any] | str | None = None,
        status: ParsedTargetStatus | str = ParsedTargetStatus.OK,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ParsedTargetArtifact":
        """Build a parsed target bound to an admitted compiled artifact."""

        if not isinstance(compiled, CompiledLogicArtifact):
            raise ArtifactV2Error("from_compiled requires CompiledLogicArtifact")
        admitted = compiled.require_admitted()
        evidence = evidence_kind if evidence_kind is not None else admitted.evidence_kind
        if evidence is None or evidence == "":
            raise RawResultAdmissionError(
                "ParsedTargetArtifact requires evidence_kind"
            )
        return cls(
            artifact_id=artifact_id,
            compiled_artifact_id=admitted.artifact_id,
            compiled_artifact_digest=admitted.content_digest,
            request_id=admitted.request_id,
            request_digest=admitted.request_digest,
            provider=provider,
            evidence_kind=evidence,
            result_kind=result_kind,
            output_digest=output_digest,
            output_bytes=output_bytes,
            output_text=output_text,
            result_digest=result_digest,
            decoded_evidence_digest=decoded_evidence_digest,
            target_digest=admitted.target_digest,
            document_id=admitted.document_id,
            source_digest=admitted.source_digest,
            expression_id=admitted.expression_id,
            expression_digest=admitted.expression_digest,
            status=status,
            authority_ceiling=admitted.authority_ceiling,
            metadata=dict(metadata or {}),
        )


def admit_parsed_result(
    compiled: CompiledLogicArtifact,
    *,
    artifact_id: str,
    provider: LogicIdentity | Mapping[str, Any] | str,
    result_kind: str,
    output_text: str = "",
    output_bytes: bytes = b"",
    output_digest: str = "",
    result_digest: str = "",
    decoded_evidence_digest: str = "",
    evidence_kind: LogicIdentity | Mapping[str, Any] | str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ParsedTargetArtifact:
    """Gate raw result content through ParsedTargetArtifact@1.

    Executable backends must call this (or construct
    :class:`ParsedTargetArtifact` equivalently) before returning result
    content on the v2 route.
    """

    if not isinstance(compiled, CompiledLogicArtifact):
        raise RawResultAdmissionError(
            "admit_parsed_result requires CompiledLogicArtifact@1; raw result "
            "egress without compilation lineage is rejected"
        )
    if not output_text and not output_bytes and not output_digest:
        raise RawResultAdmissionError(
            "admit_parsed_result requires identifiable output content"
        )
    artifact = ParsedTargetArtifact.from_compiled(
        compiled,
        artifact_id=artifact_id,
        provider=provider,
        result_kind=result_kind,
        output_text=output_text,
        output_bytes=output_bytes,
        output_digest=output_digest,
        result_digest=result_digest,
        decoded_evidence_digest=decoded_evidence_digest,
        evidence_kind=evidence_kind,
        status=ParsedTargetStatus.OK,
        metadata=metadata,
    )
    return artifact.require_admitted()


__all__ = [
    "ARTIFACTS_V2_MODULE_VERSION",
    "COMPILED_LOGIC_ARTIFACT_INTERFACE",
    "COMPILED_LOGIC_ARTIFACT_SCHEMA_VERSION",
    "PARSED_TARGET_ARTIFACT_INTERFACE",
    "PARSED_TARGET_ARTIFACT_SCHEMA_VERSION",
    "ArtifactLineageError",
    "ArtifactV2Error",
    "CompiledArtifactStatus",
    "CompiledLogicArtifact",
    "ParsedTargetArtifact",
    "ParsedTargetStatus",
    "RawResultAdmissionError",
    "RawTargetAdmissionError",
    "admit_compiled_target",
    "admit_parsed_result",
]
