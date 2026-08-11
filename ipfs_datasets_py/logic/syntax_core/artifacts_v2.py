"""Versioned parse and elaboration artifacts (Wave-2).

Interfaces (LFP2-006):

* ``ParseArtifact@2`` — source/CST/AST identities with exact source and
  diagnostic lineage
* ``ElaborationArtifact@2`` — typed elaboration identity bound to a parse
  artifact and source document lineage

Legacy ``ParseArtifact@1`` / ``ElaborationResult`` remain readable through
explicit adapters.  New writes use the v2 envelopes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    TypedExpression,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_AMBIGUITIES,
    MAX_CST_NODES,
    MAX_DIAGNOSTICS,
    MAX_TOKENS,
    DiagnosticSeverity,
    LogicCST,
    LogicToken,
    ParseArtifact,
    ParseStatus,
    SourceDocument,
    SourceMap,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    _freeze_mapping,
    _non_negative_int,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.syntax_core.elaboration import (
    ElaborationResult,
    ElaborationStatus,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    LogicSignature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PARSE_ARTIFACT_V2_INTERFACE: Final = "ParseArtifact@2"
ELABORATION_ARTIFACT_V2_INTERFACE: Final = "ElaborationArtifact@2"

PARSE_ARTIFACT_V2_SCHEMA_VERSION: Final = "syntax-parse-artifact/v2"
ELABORATION_ARTIFACT_V2_SCHEMA_VERSION: Final = "syntax-elaboration-artifact/v2"
ARTIFACTS_V2_MODULE_VERSION: Final = "1.0.0"

# Legacy dual-read markers.
LEGACY_PARSE_ARTIFACT_INTERFACE: Final = "ParseArtifact@1"
LEGACY_PARSE_ARTIFACT_SCHEMA_VERSION: Final = "syntax-parse-artifact/v1"


class ArtifactV2Error(SyntaxContractError):
    """Raised when a v2 parse/elaboration artifact is malformed."""


class ArtifactLineageError(ArtifactV2Error):
    """Raised when source or diagnostic lineage is broken or contradictory."""


class ElaborationArtifactStatus(str, Enum):
    """Outcome of a versioned elaboration artifact."""

    OK = "ok"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


def _optional_sha256(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _sha256_hex(value, field_name)


def _status_value(status: object) -> str:
    if isinstance(status, Enum):
        return status.value
    return str(status)


# ---------------------------------------------------------------------------
# ParseArtifact@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParseArtifactV2:
    """Versioned parse result with exact source and diagnostic lineage.

    Interface: ``ParseArtifact@2``.

    Binds:

    * ``document_id`` + ``source_digest`` — exact source identity
    * tokens / CST / surface AST — syntactic structure
    * ``typed_roots`` — optional core AST roots already projected from the CST
    * diagnostics with stable ids and related-id lineage
    * ``content_digest`` — structural identity of the artifact body
    * ``lineage_digest`` — identity over source + diagnostic lineage only
    """

    artifact_id: str
    request_id: str
    document_id: str
    source_digest: str
    status: ParseStatus | str
    tokens: tuple[LogicToken, ...] = ()
    cst: LogicCST | None = None
    surface_ast: tuple[SurfaceASTRef, ...] = ()
    typed_roots: tuple[LogicNode, ...] = ()
    source_map: SourceMap | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    ambiguity_count: int = 0
    content_digest: str = ""
    lineage_digest: str = ""
    legacy_content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PARSE_ARTIFACT_V2_SCHEMA_VERSION

    interface: ClassVar[str] = PARSE_ARTIFACT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        object.__setattr__(
            self,
            "source_digest",
            _sha256_hex(self.source_digest, "source_digest"),
        )

        if isinstance(self.status, ParseStatus):
            status = self.status
        else:
            try:
                status = ParseStatus(_text(self.status, "status", maximum=32))
            except ValueError as error:
                raise ArtifactV2Error(
                    f"status must be a ParseStatus value; got {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        tokens = tuple(
            item
            if isinstance(item, LogicToken)
            else LogicToken.from_dict(_require_mapping(item, "tokens item"))
            for item in _require_sequence(self.tokens, "tokens")
        )
        if len(tokens) > MAX_TOKENS:
            raise ArtifactV2Error("ParseArtifactV2.tokens exceeds hard ceiling")
        token_ids = [item.token_id for item in tokens]
        if len(token_ids) != len(set(token_ids)):
            raise ArtifactV2Error(
                "ParseArtifactV2.tokens must have unique token_id values"
            )
        for token in tokens:
            if token.document_id and token.document_id != self.document_id:
                raise ArtifactLineageError(
                    f"token {token.token_id} document_id does not match artifact"
                )
        object.__setattr__(self, "tokens", tokens)

        if self.cst is not None:
            if not isinstance(self.cst, LogicCST):
                object.__setattr__(
                    self,
                    "cst",
                    LogicCST.from_dict(_require_mapping(self.cst, "cst")),
                )
            if self.cst.document_id != self.document_id:
                raise ArtifactLineageError(
                    "LogicCST.document_id must match ParseArtifactV2.document_id"
                )

        surface_ast = tuple(
            item
            if isinstance(item, SurfaceASTRef)
            else SurfaceASTRef.from_dict(
                _require_mapping(item, "surface_ast item")
            )
            for item in _require_sequence(self.surface_ast, "surface_ast")
        )
        if len(surface_ast) > MAX_CST_NODES:
            raise ArtifactV2Error("surface_ast exceeds hard ceiling")
        ast_ids = [item.node_id for item in surface_ast]
        if len(ast_ids) != len(set(ast_ids)):
            raise ArtifactV2Error("surface_ast node_id values must be unique")
        known_ast = set(ast_ids)
        for node in surface_ast:
            unknown = [child for child in node.child_ids if child not in known_ast]
            if unknown:
                raise ArtifactV2Error(
                    f"surface AST node {node.node_id} references unknown "
                    f"child ids: {', '.join(unknown)}"
                )
        object.__setattr__(self, "surface_ast", surface_ast)

        typed_roots = tuple(
            item
            if isinstance(item, LogicNode)
            else LogicNode.from_dict(_require_mapping(item, "typed_roots item"))
            for item in _require_sequence(self.typed_roots, "typed_roots")
        )
        if len(typed_roots) > MAX_CST_NODES:
            raise ArtifactV2Error("typed_roots exceeds hard ceiling")
        root_ids = [item.node_id for item in typed_roots]
        if len(root_ids) != len(set(root_ids)):
            raise ArtifactV2Error("typed_roots node_id values must be unique")
        object.__setattr__(self, "typed_roots", typed_roots)

        if self.source_map is not None and not isinstance(self.source_map, SourceMap):
            object.__setattr__(
                self,
                "source_map",
                SourceMap.from_dict(
                    _require_mapping(self.source_map, "source_map")
                ),
            )
        if self.source_map is not None:
            if (
                self.source_map.document_id
                and self.source_map.document_id != self.document_id
            ):
                raise ArtifactLineageError(
                    "SourceMap.document_id must match ParseArtifactV2.document_id"
                )

        diagnostics = tuple(
            item
            if isinstance(item, SyntaxDiagnostic)
            else SyntaxDiagnostic.from_dict(
                _require_mapping(item, "diagnostics item")
            )
            for item in _require_sequence(self.diagnostics, "diagnostics")
        )
        if len(diagnostics) > MAX_DIAGNOSTICS:
            raise ArtifactV2Error(
                "ParseArtifactV2.diagnostics exceeds hard ceiling"
            )
        diagnostic_ids = [item.diagnostic_id for item in diagnostics]
        if len(diagnostic_ids) != len(set(diagnostic_ids)):
            raise ArtifactLineageError(
                "duplicate diagnostics are rejected; diagnostic_id values "
                "must be unique"
            )
        known_diagnostics = set(diagnostic_ids)
        for item in diagnostics:
            dangling = [
                related
                for related in item.related_diagnostic_ids
                if related not in known_diagnostics
            ]
            if dangling:
                raise ArtifactLineageError(
                    f"diagnostic {item.diagnostic_id} references unknown "
                    f"related diagnostics: {', '.join(dangling)}"
                )
        object.__setattr__(self, "diagnostics", diagnostics)

        ambiguity_count = _non_negative_int(self.ambiguity_count, "ambiguity_count")
        if ambiguity_count > MAX_AMBIGUITIES:
            raise ArtifactV2Error("ambiguity_count exceeds hard ceiling")
        object.__setattr__(self, "ambiguity_count", ambiguity_count)

        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != PARSE_ARTIFACT_V2_SCHEMA_VERSION:
            raise ArtifactV2Error(
                f"unsupported ParseArtifactV2 schema_version "
                f"{self.schema_version!r}"
            )

        if self.legacy_content_digest:
            object.__setattr__(
                self,
                "legacy_content_digest",
                _sha256_hex(
                    self.legacy_content_digest, "legacy_content_digest"
                ),
            )

        # Status-specific structural requirements (same fail-closed rules as v1).
        if status is ParseStatus.OK and any(item.is_error for item in diagnostics):
            raise ArtifactV2Error(
                "ParseArtifactV2 status ok cannot carry error/fatal diagnostics"
            )
        if status is ParseStatus.OK and self.cst is None:
            raise ArtifactV2Error("ParseArtifactV2 status ok requires a LogicCST")
        if status is ParseStatus.RECOVERED and self.cst is None:
            raise ArtifactV2Error(
                "ParseArtifactV2 status recovered requires a LogicCST"
            )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise ArtifactV2Error(
                    "content_digest does not match ParseArtifactV2 content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

        lineage = content_sha256(canonical_json_bytes(self._lineage_payload()))
        if self.lineage_digest:
            provided_lineage = _sha256_hex(self.lineage_digest, "lineage_digest")
            if provided_lineage != lineage:
                raise ArtifactLineageError(
                    "lineage_digest does not match ParseArtifactV2 lineage"
                )
            object.__setattr__(self, "lineage_digest", provided_lineage)
        else:
            object.__setattr__(self, "lineage_digest", lineage)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "ambiguity_count": self.ambiguity_count,
            "artifact_id": self.artifact_id,
            "cst": None if self.cst is None else self.cst.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document_id": self.document_id,
            "interface": self.interface,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_map": None
            if self.source_map is None
            else self.source_map.to_dict(),
            "status": _status_value(self.status),
            "surface_ast": [item.to_dict() for item in self.surface_ast],
            "tokens": [item.to_dict() for item in self.tokens],
            "typed_roots": [item.to_dict() for item in self.typed_roots],
        }

    def _lineage_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "diagnostics": [
                {
                    "code": item.code,
                    "diagnostic_id": item.diagnostic_id,
                    "related_diagnostic_ids": list(item.related_diagnostic_ids),
                    "severity": _status_value(item.severity),
                }
                for item in self.diagnostics
            ],
            "document_id": self.document_id,
            "request_id": self.request_id,
            "source_digest": self.source_digest,
            "status": _status_value(self.status),
        }

    def validate_against(self, document: SourceDocument) -> None:
        """Cross-check source digest and diagnostic lineage against *document*."""

        if document.document_id != self.document_id:
            raise ArtifactLineageError(
                "document_id does not match the supplied SourceDocument"
            )
        if document.content_digest != self.source_digest:
            raise ArtifactLineageError(
                "source_digest does not match SourceDocument.content_digest"
            )
        for token in self.tokens:
            token.validate_against(document)
        if self.cst is not None:
            if self.cst.source_length != document.byte_length:
                raise ArtifactLineageError(
                    "LogicCST.source_length must equal SourceDocument.byte_length"
                )
        for node in self.surface_ast:
            node.range.validate_against(
                document.byte_length, field_name=f"surface AST {node.node_id}"
            )
        for diagnostic in self.diagnostics:
            diagnostic.validate_against(document)

    def to_v1(self) -> ParseArtifact:
        """Project to legacy ``ParseArtifact@1`` (drops typed roots / lineage)."""

        return ParseArtifact(
            artifact_id=self.artifact_id,
            request_id=self.request_id,
            document_id=self.document_id,
            status=self.status,
            tokens=self.tokens,
            cst=self.cst,
            surface_ast=self.surface_ast,
            diagnostics=self.diagnostics,
            ambiguity_count=self.ambiguity_count,
            metadata={
                **_thaw_mapping(self.metadata),
                "migrated_from": PARSE_ARTIFACT_V2_INTERFACE,
                "source_digest": self.source_digest,
                "lineage_digest": self.lineage_digest,
            },
        )

    @classmethod
    def from_v1(
        cls,
        artifact: ParseArtifact,
        *,
        source_digest: str,
        typed_roots: Sequence[LogicNode] = (),
        source_map: SourceMap | None = None,
        artifact_id: str | None = None,
    ) -> "ParseArtifactV2":
        """Lift a legacy ``ParseArtifact@1`` into ``ParseArtifact@2``."""

        if not isinstance(artifact, ParseArtifact):
            raise ArtifactV2Error("from_v1 requires a ParseArtifact")
        return cls(
            artifact_id=artifact_id or artifact.artifact_id,
            request_id=artifact.request_id,
            document_id=artifact.document_id,
            source_digest=source_digest,
            status=artifact.status,
            tokens=artifact.tokens,
            cst=artifact.cst,
            surface_ast=artifact.surface_ast,
            typed_roots=tuple(typed_roots),
            source_map=source_map,
            diagnostics=artifact.diagnostics,
            ambiguity_count=artifact.ambiguity_count,
            legacy_content_digest=artifact.content_digest,
            metadata={
                **_thaw_mapping(artifact.metadata),
                "migrated_from": LEGACY_PARSE_ARTIFACT_INTERFACE,
            },
        )

    @classmethod
    def from_document(
        cls,
        document: SourceDocument,
        *,
        artifact_id: str,
        request_id: str,
        status: ParseStatus | str,
        tokens: Sequence[LogicToken] = (),
        cst: LogicCST | None = None,
        surface_ast: Sequence[SurfaceASTRef] = (),
        typed_roots: Sequence[LogicNode] = (),
        source_map: SourceMap | None = None,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        ambiguity_count: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ParseArtifactV2":
        """Build a v2 parse artifact bound to *document*'s exact identity."""

        return cls(
            artifact_id=artifact_id,
            request_id=request_id,
            document_id=document.document_id,
            source_digest=document.content_digest,
            status=status,
            tokens=tuple(tokens),
            cst=cst,
            surface_ast=tuple(surface_ast),
            typed_roots=tuple(typed_roots),
            source_map=source_map,
            diagnostics=tuple(diagnostics),
            ambiguity_count=ambiguity_count,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["lineage_digest"] = self.lineage_digest
        payload["legacy_content_digest"] = self.legacy_content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParseArtifactV2":
        payload = _require_mapping(data, "ParseArtifactV2")
        interface = payload.get("interface")
        if interface is not None and interface != PARSE_ARTIFACT_V2_INTERFACE:
            raise ArtifactV2Error(
                f"unsupported ParseArtifactV2 interface {interface!r}"
            )
        cst_payload = payload.get("cst")
        source_map_payload = payload.get("source_map")
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            status=str(payload.get("status") or ParseStatus.FAILED.value),
            tokens=tuple(
                LogicToken.from_dict(_require_mapping(item, "tokens item"))
                for item in _require_sequence(
                    payload.get("tokens") or (), "tokens"
                )
            ),
            cst=(
                None
                if cst_payload is None
                else LogicCST.from_dict(_require_mapping(cst_payload, "cst"))
            ),
            surface_ast=tuple(
                SurfaceASTRef.from_dict(
                    _require_mapping(item, "surface_ast item")
                )
                for item in _require_sequence(
                    payload.get("surface_ast") or (), "surface_ast"
                )
            ),
            typed_roots=tuple(
                LogicNode.from_dict(_require_mapping(item, "typed_roots item"))
                for item in _require_sequence(
                    payload.get("typed_roots") or (), "typed_roots"
                )
            ),
            source_map=(
                None
                if source_map_payload is None
                else SourceMap.from_dict(
                    _require_mapping(source_map_payload, "source_map")
                )
            ),
            diagnostics=tuple(
                SyntaxDiagnostic.from_dict(
                    _require_mapping(item, "diagnostics item")
                )
                for item in _require_sequence(
                    payload.get("diagnostics") or (), "diagnostics"
                )
            ),
            ambiguity_count=int(payload.get("ambiguity_count") or 0),
            content_digest=str(payload.get("content_digest") or ""),
            lineage_digest=str(payload.get("lineage_digest") or ""),
            legacy_content_digest=str(payload.get("legacy_content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or PARSE_ARTIFACT_V2_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# ElaborationArtifact@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ElaborationArtifactV2:
    """Versioned elaboration envelope with parse/source diagnostic lineage.

    Interface: ``ElaborationArtifact@2``.

    Binds:

    * parse artifact identity (``parse_artifact_id`` + digests)
    * exact source identity (``document_id`` + ``source_digest``)
    * typed expression / elaboration result identity
    * diagnostics preserving related-id lineage from parse through elaboration
    """

    artifact_id: str
    parse_artifact_id: str
    document_id: str
    source_digest: str
    status: ElaborationArtifactStatus | ElaborationStatus | str
    typed_expression: TypedExpression | None = None
    root: LogicNode | None = None
    normalized_root: LogicNode | None = None
    signature: LogicSignature | None = None
    parse_content_digest: str = ""
    parse_lineage_digest: str = ""
    elaboration_result_id: str = ""
    elaboration_content_digest: str = ""
    semantic_digest: str = ""
    unresolved_overloads: tuple[str, ...] = ()
    unknown_symbols: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    content_digest: str = ""
    lineage_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ELABORATION_ARTIFACT_V2_SCHEMA_VERSION

    interface: ClassVar[str] = ELABORATION_ARTIFACT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "parse_artifact_id",
            _record_id(self.parse_artifact_id, "parse_artifact_id"),
        )
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        object.__setattr__(
            self,
            "source_digest",
            _sha256_hex(self.source_digest, "source_digest"),
        )

        status = self._coerce_status(self.status)
        object.__setattr__(self, "status", status)

        if self.typed_expression is not None and not isinstance(
            self.typed_expression, TypedExpression
        ):
            object.__setattr__(
                self,
                "typed_expression",
                TypedExpression.from_dict(
                    _require_mapping(self.typed_expression, "typed_expression")
                ),
            )
        if self.root is not None and not isinstance(self.root, LogicNode):
            object.__setattr__(
                self,
                "root",
                LogicNode.from_dict(_require_mapping(self.root, "root")),
            )
        if self.normalized_root is not None and not isinstance(
            self.normalized_root, LogicNode
        ):
            object.__setattr__(
                self,
                "normalized_root",
                LogicNode.from_dict(
                    _require_mapping(self.normalized_root, "normalized_root")
                ),
            )
        if self.signature is not None and not isinstance(
            self.signature, LogicSignature
        ):
            object.__setattr__(
                self,
                "signature",
                LogicSignature.from_dict(
                    _require_mapping(self.signature, "signature")
                ),
            )

        object.__setattr__(
            self,
            "parse_content_digest",
            _optional_sha256(self.parse_content_digest, "parse_content_digest"),
        )
        object.__setattr__(
            self,
            "parse_lineage_digest",
            _optional_sha256(self.parse_lineage_digest, "parse_lineage_digest"),
        )
        if self.elaboration_result_id:
            object.__setattr__(
                self,
                "elaboration_result_id",
                _record_id(
                    self.elaboration_result_id, "elaboration_result_id"
                ),
            )
        object.__setattr__(
            self,
            "elaboration_content_digest",
            _optional_sha256(
                self.elaboration_content_digest, "elaboration_content_digest"
            ),
        )
        if self.semantic_digest:
            object.__setattr__(
                self,
                "semantic_digest",
                _text(self.semantic_digest, "semantic_digest", maximum=64),
            )

        object.__setattr__(
            self,
            "unresolved_overloads",
            tuple(
                _text(item, "unresolved_overloads item", maximum=256)
                for item in _require_sequence(
                    self.unresolved_overloads, "unresolved_overloads"
                )
            ),
        )
        object.__setattr__(
            self,
            "unknown_symbols",
            tuple(
                _text(item, "unknown_symbols item", maximum=256)
                for item in _require_sequence(
                    self.unknown_symbols, "unknown_symbols"
                )
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(
                _text(item, "assumptions item", maximum=1024)
                for item in _require_sequence(self.assumptions, "assumptions")
            ),
        )

        diagnostics = tuple(
            item
            if isinstance(item, SyntaxDiagnostic)
            else SyntaxDiagnostic.from_dict(
                _require_mapping(item, "diagnostics item")
            )
            for item in _require_sequence(self.diagnostics, "diagnostics")
        )
        if len(diagnostics) > MAX_DIAGNOSTICS:
            raise ArtifactV2Error(
                "ElaborationArtifactV2.diagnostics exceeds hard ceiling"
            )
        diagnostic_ids = [item.diagnostic_id for item in diagnostics]
        if len(diagnostic_ids) != len(set(diagnostic_ids)):
            raise ArtifactLineageError(
                "duplicate diagnostics are rejected; diagnostic_id values "
                "must be unique"
            )
        known_diagnostics = set(diagnostic_ids)
        for item in diagnostics:
            dangling = [
                related
                for related in item.related_diagnostic_ids
                if related not in known_diagnostics
            ]
            if dangling:
                raise ArtifactLineageError(
                    f"diagnostic {item.diagnostic_id} references unknown "
                    f"related diagnostics: {', '.join(dangling)}"
                )
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )

        if self.schema_version != ELABORATION_ARTIFACT_V2_SCHEMA_VERSION:
            raise ArtifactV2Error(
                f"unsupported ElaborationArtifactV2 schema_version "
                f"{self.schema_version!r}"
            )

        # OK requires a typed expression; unresolved/failed must not claim one
        # is backend-ready (typed expression may still be absent).
        if status is ElaborationArtifactStatus.OK:
            if self.typed_expression is None:
                raise ArtifactV2Error(
                    "ElaborationArtifactV2 status ok requires a TypedExpression"
                )
            if self.unresolved_overloads or self.unknown_symbols:
                raise ArtifactV2Error(
                    "ElaborationArtifactV2 status ok cannot carry unresolved "
                    "overloads or unknown symbols"
                )
            if any(item.is_error for item in diagnostics):
                raise ArtifactV2Error(
                    "ElaborationArtifactV2 status ok cannot carry error/fatal "
                    "diagnostics"
                )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise ArtifactV2Error(
                    "content_digest does not match ElaborationArtifactV2 content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

        lineage = content_sha256(canonical_json_bytes(self._lineage_payload()))
        if self.lineage_digest:
            provided_lineage = _sha256_hex(self.lineage_digest, "lineage_digest")
            if provided_lineage != lineage:
                raise ArtifactLineageError(
                    "lineage_digest does not match ElaborationArtifactV2 lineage"
                )
            object.__setattr__(self, "lineage_digest", provided_lineage)
        else:
            object.__setattr__(self, "lineage_digest", lineage)

    @staticmethod
    def _coerce_status(
        value: object,
    ) -> ElaborationArtifactStatus:
        if isinstance(value, ElaborationArtifactStatus):
            return value
        if isinstance(value, ElaborationStatus):
            return ElaborationArtifactStatus(value.value)
        text = _text(value, "status", maximum=32)
        try:
            return ElaborationArtifactStatus(text)
        except ValueError as error:
            raise ArtifactV2Error(
                f"status must be an ElaborationArtifactStatus; got {value!r}"
            ) from error

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "artifact_id": self.artifact_id,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "document_id": self.document_id,
            "elaboration_content_digest": self.elaboration_content_digest,
            "elaboration_result_id": self.elaboration_result_id,
            "interface": self.interface,
            "normalized_root": None
            if self.normalized_root is None
            else self.normalized_root.to_dict(),
            "parse_artifact_id": self.parse_artifact_id,
            "parse_content_digest": self.parse_content_digest,
            "parse_lineage_digest": self.parse_lineage_digest,
            "root": None if self.root is None else self.root.to_dict(),
            "schema_version": self.schema_version,
            "semantic_digest": self.semantic_digest,
            "signature": None
            if self.signature is None
            else self.signature.to_dict(),
            "source_digest": self.source_digest,
            "status": _status_value(self.status),
            "typed_expression": None
            if self.typed_expression is None
            else self.typed_expression.to_dict(),
            "unknown_symbols": list(self.unknown_symbols),
            "unresolved_overloads": list(self.unresolved_overloads),
        }

    def _lineage_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "diagnostics": [
                {
                    "code": item.code,
                    "diagnostic_id": item.diagnostic_id,
                    "related_diagnostic_ids": list(item.related_diagnostic_ids),
                    "severity": _status_value(item.severity),
                }
                for item in self.diagnostics
            ],
            "document_id": self.document_id,
            "parse_artifact_id": self.parse_artifact_id,
            "parse_content_digest": self.parse_content_digest,
            "parse_lineage_digest": self.parse_lineage_digest,
            "source_digest": self.source_digest,
            "status": _status_value(self.status),
        }

    @property
    def backend_ready(self) -> bool:
        if self.status is not ElaborationArtifactStatus.OK:
            return False
        if self.typed_expression is None:
            return False
        if self.unresolved_overloads or self.unknown_symbols:
            return False
        for diagnostic in self.diagnostics:
            severity = diagnostic.severity
            if isinstance(severity, DiagnosticSeverity):
                if severity.rank >= DiagnosticSeverity.ERROR.rank:
                    return False
            elif str(severity) in {
                DiagnosticSeverity.ERROR.value,
                DiagnosticSeverity.FATAL.value,
            }:
                return False
        return True

    def require_backend_ready(self) -> TypedExpression:
        if not self.backend_ready or self.typed_expression is None:
            raise ArtifactV2Error(
                "elaboration artifact is not backend-ready: unresolved "
                "work or broken lineage must not reach backends"
            )
        return self.typed_expression

    def validate_lineage(
        self,
        *,
        parse_artifact: ParseArtifactV2 | None = None,
        document: SourceDocument | None = None,
    ) -> None:
        """Verify parse/source lineage bindings when parents are supplied."""

        if document is not None:
            if document.document_id != self.document_id:
                raise ArtifactLineageError(
                    "document_id does not match the supplied SourceDocument"
                )
            if document.content_digest != self.source_digest:
                raise ArtifactLineageError(
                    "source_digest does not match SourceDocument.content_digest"
                )
        if parse_artifact is not None:
            if parse_artifact.artifact_id != self.parse_artifact_id:
                raise ArtifactLineageError(
                    "parse_artifact_id does not match the supplied ParseArtifactV2"
                )
            if parse_artifact.document_id != self.document_id:
                raise ArtifactLineageError(
                    "parse artifact document_id does not match elaboration "
                    "document_id"
                )
            if parse_artifact.source_digest != self.source_digest:
                raise ArtifactLineageError(
                    "parse artifact source_digest does not match elaboration "
                    "source_digest"
                )
            if (
                self.parse_content_digest
                and parse_artifact.content_digest != self.parse_content_digest
            ):
                raise ArtifactLineageError(
                    "parse_content_digest does not match ParseArtifactV2"
                )
            if (
                self.parse_lineage_digest
                and parse_artifact.lineage_digest != self.parse_lineage_digest
            ):
                raise ArtifactLineageError(
                    "parse_lineage_digest does not match ParseArtifactV2"
                )

    @classmethod
    def from_elaboration_result(
        cls,
        result: ElaborationResult,
        *,
        artifact_id: str,
        parse_artifact: ParseArtifactV2,
        document: SourceDocument | None = None,
        extra_diagnostics: Sequence[SyntaxDiagnostic] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> "ElaborationArtifactV2":
        """Bind an :class:`ElaborationResult` to parse/source lineage."""

        if not isinstance(result, ElaborationResult):
            raise ArtifactV2Error(
                "from_elaboration_result requires an ElaborationResult"
            )
        if not isinstance(parse_artifact, ParseArtifactV2):
            raise ArtifactV2Error(
                "from_elaboration_result requires a ParseArtifactV2"
            )
        if document is not None:
            if document.document_id != parse_artifact.document_id:
                raise ArtifactLineageError(
                    "document does not match parse artifact document_id"
                )
            if document.content_digest != parse_artifact.source_digest:
                raise ArtifactLineageError(
                    "document content_digest does not match parse source_digest"
                )

        # Merge diagnostics while preserving lineage (reject id collisions).
        merged: list[SyntaxDiagnostic] = list(result.diagnostics)
        seen = {item.diagnostic_id for item in merged}
        for item in extra_diagnostics:
            if item.diagnostic_id in seen:
                raise ArtifactLineageError(
                    f"duplicate diagnostic id {item.diagnostic_id!r} when "
                    "merging elaboration diagnostics"
                )
            merged.append(item)
            seen.add(item.diagnostic_id)
        # Include parse diagnostics that are not already present so lineage
        # from parse through elaboration is preserved.
        for item in parse_artifact.diagnostics:
            if item.diagnostic_id not in seen:
                merged.append(item)
                seen.add(item.diagnostic_id)

        status = ElaborationArtifactStatus(result.status.value)
        return cls(
            artifact_id=artifact_id,
            parse_artifact_id=parse_artifact.artifact_id,
            document_id=parse_artifact.document_id,
            source_digest=parse_artifact.source_digest,
            status=status,
            typed_expression=result.typed_expression,
            root=result.root,
            normalized_root=result.normalized_root,
            signature=result.signature,
            parse_content_digest=parse_artifact.content_digest,
            parse_lineage_digest=parse_artifact.lineage_digest,
            elaboration_result_id=result.result_id,
            elaboration_content_digest=result.content_digest,
            semantic_digest=result.semantic_digest,
            unresolved_overloads=result.unresolved_overloads,
            unknown_symbols=result.unknown_symbols,
            assumptions=result.assumptions,
            diagnostics=tuple(merged),
            metadata=dict(metadata or {}),
        )

    def to_elaboration_result(self) -> ElaborationResult:
        """Project to an :class:`ElaborationResult` (drops parse lineage)."""

        status_map = {
            ElaborationArtifactStatus.OK: ElaborationStatus.OK,
            ElaborationArtifactStatus.FAILED: ElaborationStatus.FAILED,
            ElaborationArtifactStatus.UNRESOLVED: ElaborationStatus.UNRESOLVED,
            ElaborationArtifactStatus.REJECTED: ElaborationStatus.REJECTED,
        }
        return ElaborationResult(
            result_id=self.elaboration_result_id or f"elab:{self.artifact_id}",
            status=status_map[self.status],
            typed_expression=self.typed_expression,
            root=self.root,
            normalized_root=self.normalized_root,
            signature=self.signature,
            unresolved_overloads=self.unresolved_overloads,
            unknown_symbols=self.unknown_symbols,
            assumptions=self.assumptions,
            # Recompute digests: projection may carry merged parse diagnostics
            # that were not part of the original ElaborationResult identity.
            diagnostics=self.diagnostics,
            semantic_digest=self.semantic_digest,
            metadata={
                **_thaw_mapping(self.metadata),
                "migrated_from": ELABORATION_ARTIFACT_V2_INTERFACE,
                "parse_artifact_id": self.parse_artifact_id,
                "source_digest": self.source_digest,
                "lineage_digest": self.lineage_digest,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["backend_ready"] = self.backend_ready
        payload["content_digest"] = self.content_digest
        payload["lineage_digest"] = self.lineage_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ElaborationArtifactV2":
        payload = _require_mapping(data, "ElaborationArtifactV2")
        interface = payload.get("interface")
        if (
            interface is not None
            and interface != ELABORATION_ARTIFACT_V2_INTERFACE
        ):
            raise ArtifactV2Error(
                f"unsupported ElaborationArtifactV2 interface {interface!r}"
            )
        typed_payload = payload.get("typed_expression")
        root_payload = payload.get("root")
        norm_payload = payload.get("normalized_root")
        sig_payload = payload.get("signature")
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            parse_artifact_id=str(payload.get("parse_artifact_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            status=str(
                payload.get("status") or ElaborationArtifactStatus.FAILED.value
            ),
            typed_expression=(
                None
                if typed_payload is None
                else TypedExpression.from_dict(
                    _require_mapping(typed_payload, "typed_expression")
                )
            ),
            root=(
                None
                if root_payload is None
                else LogicNode.from_dict(_require_mapping(root_payload, "root"))
            ),
            normalized_root=(
                None
                if norm_payload is None
                else LogicNode.from_dict(
                    _require_mapping(norm_payload, "normalized_root")
                )
            ),
            signature=(
                None
                if sig_payload is None
                else LogicSignature.from_dict(
                    _require_mapping(sig_payload, "signature")
                )
            ),
            parse_content_digest=str(payload.get("parse_content_digest") or ""),
            parse_lineage_digest=str(payload.get("parse_lineage_digest") or ""),
            elaboration_result_id=str(
                payload.get("elaboration_result_id") or ""
            ),
            elaboration_content_digest=str(
                payload.get("elaboration_content_digest") or ""
            ),
            semantic_digest=str(payload.get("semantic_digest") or ""),
            unresolved_overloads=tuple(
                payload.get("unresolved_overloads") or ()
            ),
            unknown_symbols=tuple(payload.get("unknown_symbols") or ()),
            assumptions=tuple(payload.get("assumptions") or ()),
            diagnostics=tuple(
                SyntaxDiagnostic.from_dict(
                    _require_mapping(item, "diagnostics item")
                )
                for item in _require_sequence(
                    payload.get("diagnostics") or (), "diagnostics"
                )
            ),
            content_digest=str(payload.get("content_digest") or ""),
            lineage_digest=str(payload.get("lineage_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version")
                or ELABORATION_ARTIFACT_V2_SCHEMA_VERSION
            ),
        )


__all__ = [
    "ARTIFACTS_V2_MODULE_VERSION",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "ELABORATION_ARTIFACT_V2_SCHEMA_VERSION",
    "LEGACY_PARSE_ARTIFACT_INTERFACE",
    "LEGACY_PARSE_ARTIFACT_SCHEMA_VERSION",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "PARSE_ARTIFACT_V2_SCHEMA_VERSION",
    "ArtifactLineageError",
    "ArtifactV2Error",
    "ElaborationArtifactStatus",
    "ElaborationArtifactV2",
    "ParseArtifactV2",
]
