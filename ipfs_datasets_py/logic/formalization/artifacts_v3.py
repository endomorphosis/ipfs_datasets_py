"""Versioned formalization artifacts and domain logic slices (Wave-2).

Interfaces (LFP2-007):

* ``FormalizationArtifact@3`` — source-mapped, domain-neutral formalization
  envelope bound to typed-expression identity
* ``DomainLogicSlice@2`` — admitted domain slice that binds exact source and
  typed-expression identity before any backend request is formed

Legacy ``FormalizationArtifact`` (compiler v1) remains dual-readable through
explicit adapters.  New writes use the v3 envelopes.  Domain slices never
admit free-form family strings, arbitrary extension payloads, or missing
source/expression lineage.
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
    profile_id,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    TypedExpression,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    MAX_DIAGNOSTICS,
    SourceDocument,
    SourceMap,
    SourceRange,
    SyntaxContractError,
    SyntaxDiagnostic,
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
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ElaborationArtifactV2,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

FORMALIZATION_ARTIFACT_V3_INTERFACE: Final = "FormalizationArtifact@3"
DOMAIN_LOGIC_SLICE_V2_INTERFACE: Final = "DomainLogicSlice@2"

FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION: Final = "formalization-artifact/v3"
DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION: Final = "domain-logic-slice/v2"
ARTIFACTS_V3_MODULE_VERSION: Final = "1.0.0"

LEGACY_FORMALIZATION_ARTIFACT_INTERFACE: Final = "FormalizationArtifact@1"
LEGACY_FORMALIZATION_ARTIFACT_SCHEMA_VERSION: Final = "formalization-artifact/v1"

_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]*(?:_[a-z0-9]+)*$")

# Metadata keys that would re-introduce free-form routing or raw ingress.
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
    }
)


class ArtifactV3Error(SyntaxContractError):
    """Raised when a v3 formalization artifact or domain slice is malformed."""


class ArtifactV3LineageError(ArtifactV3Error):
    """Raised when source or typed-expression lineage is broken."""


class DomainSliceAdmissionError(ArtifactV3Error):
    """Raised when a domain slice cannot be admitted for backend request use."""


class FormalizationArtifactStatus(str, Enum):
    """Outcome of a versioned formalization artifact."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"


class DomainSliceStatus(str, Enum):
    """Admission status of one domain logic slice."""

    ADMITTED = "admitted"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


def _status_value(status: object) -> str:
    if isinstance(status, Enum):
        return status.value
    return str(status)


def _optional_sha256(value: object, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _sha256_hex(value, field_name)


def _domain_id(value: object, field_name: str = "domain") -> str:
    text = _text(value, field_name, maximum=128)
    if not _DOMAIN_RE.fullmatch(text):
        raise ArtifactV3Error(
            f"{field_name} must be a lowercase domain identifier; got {text!r}"
        )
    return text


def _feature_tuple(value: object, field_name: str) -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=128)
        for item in _require_sequence(value, field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise ArtifactV3Error(f"{field_name} exceeds hard ceiling")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not _FEATURE_RE.fullmatch(item):
            raise ArtifactV3Error(
                f"{field_name} item must be a feature identity; got {item!r}"
            )
        if item in seen:
            raise ArtifactV3Error(f"{field_name} values must be unique")
        seen.add(item)
        ordered.append(item)
    return tuple(sorted(ordered))


def _identity_payload_value(identity: LogicIdentity) -> dict[str, str]:
    return identity.to_dict()


def _forbid_metadata_routing(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS:
            raise ArtifactV3Error(
                f"{field_name} rejects free-form routing key {key!r}; "
                "use typed family/profile/property/view/notation fields"
            )


def _coerce_identity(
    value: object,
    expected: NamespaceKind,
    field_name: str,
) -> LogicIdentity:
    try:
        return require_namespace_identity(value, expected, field_name)
    except SyntaxContractError as error:
        raise ArtifactV3Error(str(error)) from error


# ---------------------------------------------------------------------------
# DomainLogicSlice@2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainLogicSliceV2:
    """Admitted domain slice bound to exact source and typed-expression identity.

    Interface: ``DomainLogicSlice@2``.

    Every admitted slice carries:

    * ``document_id`` + ``source_digest`` — exact source identity
    * ``expression_id`` + ``expression_digest`` — typed-expression identity
    * typed family / profile / property / view / notation namespaces
    * optional source range and feature set
    * explicit rejection of unsupported extensions and free-form payloads

    Only slices with status ``admitted`` may seed ``BackendRequest@2``.
    """

    slice_id: str
    domain: str
    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    property: LogicIdentity | Mapping[str, Any] | str
    view: LogicIdentity | Mapping[str, Any] | str
    notation: LogicIdentity | Mapping[str, Any] | str
    status: DomainSliceStatus | str = DomainSliceStatus.ADMITTED
    source_range: SourceRange | None = None
    features: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    unsupported_extensions: tuple[str, ...] = ()
    formalization_artifact_id: str = ""
    elaboration_artifact_id: str = ""
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION

    interface: ClassVar[str] = DOMAIN_LOGIC_SLICE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "slice_id", _record_id(self.slice_id, "slice_id"))
        object.__setattr__(self, "domain", _domain_id(self.domain, "domain"))
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

        if isinstance(self.status, DomainSliceStatus):
            status = self.status
        else:
            try:
                status = DomainSliceStatus(
                    _text(self.status, "status", maximum=32)
                )
            except ValueError as error:
                raise ArtifactV3Error(
                    f"status must be a DomainSliceStatus value; got {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        if self.source_range is not None and not isinstance(
            self.source_range, SourceRange
        ):
            object.__setattr__(
                self,
                "source_range",
                SourceRange.from_dict(
                    _require_mapping(self.source_range, "source_range")
                ),
            )

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
        if len(unsupported) > MAX_COLLECTION_ITEMS:
            raise ArtifactV3Error("unsupported_extensions exceeds hard ceiling")
        object.__setattr__(self, "unsupported_extensions", unsupported)

        if self.formalization_artifact_id:
            object.__setattr__(
                self,
                "formalization_artifact_id",
                _record_id(
                    self.formalization_artifact_id, "formalization_artifact_id"
                ),
            )
        if self.elaboration_artifact_id:
            object.__setattr__(
                self,
                "elaboration_artifact_id",
                _record_id(
                    self.elaboration_artifact_id, "elaboration_artifact_id"
                ),
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_metadata_routing(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION:
            raise ArtifactV3Error(
                f"unsupported DomainLogicSliceV2 schema_version "
                f"{self.schema_version!r}"
            )

        # Admission rules: admitted slices must be fully bound and free of
        # unsupported extensions.
        if status is DomainSliceStatus.ADMITTED:
            if unsupported:
                raise DomainSliceAdmissionError(
                    "admitted DomainLogicSliceV2 cannot carry unsupported "
                    f"extensions: {', '.join(unsupported)}"
                )
            if not self.source_digest or not self.expression_digest:
                raise DomainSliceAdmissionError(
                    "admitted DomainLogicSliceV2 requires source_digest and "
                    "expression_digest"
                )
            if not self.document_id or not self.expression_id:
                raise DomainSliceAdmissionError(
                    "admitted DomainLogicSliceV2 requires document_id and "
                    "expression_id"
                )
        if status is DomainSliceStatus.UNSUPPORTED and not unsupported:
            raise DomainSliceAdmissionError(
                "unsupported DomainLogicSliceV2 must list unsupported_extensions"
            )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise ArtifactV3Error(
                    "content_digest does not match DomainLogicSliceV2 content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "domain": self.domain,
            "document_id": self.document_id,
            "elaboration_artifact_id": self.elaboration_artifact_id,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "family": _identity_payload_value(self.family),  # type: ignore[arg-type]
            "features": list(self.features),
            "formalization_artifact_id": self.formalization_artifact_id,
            "interface": self.interface,
            "notation": _identity_payload_value(self.notation),  # type: ignore[arg-type]
            "profile": _identity_payload_value(self.profile),  # type: ignore[arg-type]
            "property": _identity_payload_value(self.property),  # type: ignore[arg-type]
            "schema_version": self.schema_version,
            "slice_id": self.slice_id,
            "source_digest": self.source_digest,
            "source_range": None
            if self.source_range is None
            else self.source_range.to_dict(),
            "status": _status_value(self.status),
            "unsupported_extensions": list(self.unsupported_extensions),
            "view": _identity_payload_value(self.view),  # type: ignore[arg-type]
        }

    @property
    def is_admitted(self) -> bool:
        return self.status is DomainSliceStatus.ADMITTED

    def require_admitted(self) -> "DomainLogicSliceV2":
        """Return self when admitted; otherwise fail before backend use."""

        if not self.is_admitted:
            raise DomainSliceAdmissionError(
                f"DomainLogicSliceV2 {self.slice_id} is not admitted "
                f"(status={_status_value(self.status)}); backend requests "
                "require admitted slices with bound source and typed-expression "
                "identity"
            )
        if self.unsupported_extensions:
            raise DomainSliceAdmissionError(
                f"DomainLogicSliceV2 {self.slice_id} carries unsupported "
                "extensions and cannot seed BackendRequest@2"
            )
        return self

    def validate_against(
        self,
        *,
        document: SourceDocument | None = None,
        expression: TypedExpression | None = None,
    ) -> None:
        """Cross-check source and typed-expression identity when parents exist."""

        if document is not None:
            if document.document_id != self.document_id:
                raise ArtifactV3LineageError(
                    "document_id does not match the supplied SourceDocument"
                )
            if document.content_digest != self.source_digest:
                raise ArtifactV3LineageError(
                    "source_digest does not match SourceDocument.content_digest"
                )
            if self.source_range is not None:
                self.source_range.validate_against(
                    document.byte_length, field_name="source_range"
                )
        if expression is not None:
            if expression.expression_id != self.expression_id:
                raise ArtifactV3LineageError(
                    "expression_id does not match the supplied TypedExpression"
                )
            if expression.content_digest != self.expression_digest:
                raise ArtifactV3LineageError(
                    "expression_digest does not match TypedExpression.content_digest"
                )
            if isinstance(expression.family, LogicIdentity) and isinstance(
                self.family, LogicIdentity
            ):
                if expression.family.value != self.family.value:
                    raise ArtifactV3LineageError(
                        "slice family does not match TypedExpression.family"
                    )
            if isinstance(expression.profile, LogicIdentity) and isinstance(
                self.profile, LogicIdentity
            ):
                if expression.profile.value != self.profile.value:
                    raise ArtifactV3LineageError(
                        "slice profile does not match TypedExpression.profile"
                    )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DomainLogicSliceV2":
        payload = _require_mapping(data, "DomainLogicSliceV2")
        interface = payload.get("interface")
        if interface is not None and interface != DOMAIN_LOGIC_SLICE_V2_INTERFACE:
            raise ArtifactV3Error(
                f"unsupported DomainLogicSliceV2 interface {interface!r}"
            )
        range_payload = payload.get("source_range")
        return cls(
            slice_id=str(payload.get("slice_id") or ""),
            domain=str(payload.get("domain") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            expression_id=str(payload.get("expression_id") or ""),
            expression_digest=str(payload.get("expression_digest") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            property=payload.get("property") or "",
            view=payload.get("view") or "",
            notation=payload.get("notation") or "",
            status=str(payload.get("status") or DomainSliceStatus.ADMITTED.value),
            source_range=(
                None
                if range_payload is None
                else SourceRange.from_dict(
                    _require_mapping(range_payload, "source_range")
                )
            ),
            features=tuple(payload.get("features") or ()),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            unsupported_extensions=tuple(
                payload.get("unsupported_extensions") or ()
            ),
            formalization_artifact_id=str(
                payload.get("formalization_artifact_id") or ""
            ),
            elaboration_artifact_id=str(
                payload.get("elaboration_artifact_id") or ""
            ),
            content_digest=str(payload.get("content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version") or DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_typed_expression(
        cls,
        expression: TypedExpression,
        *,
        slice_id: str,
        domain: str,
        document_id: str,
        source_digest: str,
        property: LogicIdentity | Mapping[str, Any] | str,
        view: LogicIdentity | Mapping[str, Any] | str = "source",
        notation: LogicIdentity | Mapping[str, Any] | str = "canonical_text",
        status: DomainSliceStatus | str = DomainSliceStatus.ADMITTED,
        source_range: SourceRange | None = None,
        features: Sequence[str] = (),
        assumption_ids: Sequence[str] = (),
        unsupported_extensions: Sequence[str] = (),
        formalization_artifact_id: str = "",
        elaboration_artifact_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> "DomainLogicSliceV2":
        """Build a slice bound to a concrete typed expression and source."""

        if not isinstance(expression, TypedExpression):
            raise ArtifactV3Error(
                "from_typed_expression requires a TypedExpression"
            )
        family = expression.family
        profile = expression.profile
        return cls(
            slice_id=slice_id,
            domain=domain,
            document_id=document_id,
            source_digest=source_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=family if family is not None else family_id("first_order"),
            profile=profile if profile is not None else profile_id("many_sorted"),
            property=property,
            view=view,
            notation=notation,
            status=status,
            source_range=source_range if source_range is not None else expression.range,
            features=tuple(features),
            assumption_ids=tuple(assumption_ids),
            unsupported_extensions=tuple(unsupported_extensions),
            formalization_artifact_id=formalization_artifact_id,
            elaboration_artifact_id=elaboration_artifact_id,
            metadata=dict(metadata or {}),
        )


# ---------------------------------------------------------------------------
# FormalizationArtifact@3
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormalizationArtifactV3:
    """Source-mapped domain-neutral formalization envelope.

    Interface: ``FormalizationArtifact@3``.

    Binds:

    * exact source identity (``document_id`` + ``source_digest``)
    * typed-expression identity (``expression_id`` + ``expression_digest``)
    * optional elaboration artifact lineage
    * zero or more ``DomainLogicSlice@2`` entries
    * typed family / profile / view / notation namespaces
    * diagnostics and content/lineage digests
    """

    artifact_id: str
    sample_id: str
    domain: str
    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    family: LogicIdentity | Mapping[str, Any] | str
    profile: LogicIdentity | Mapping[str, Any] | str
    view: LogicIdentity | Mapping[str, Any] | str
    notation: LogicIdentity | Mapping[str, Any] | str
    status: FormalizationArtifactStatus | str = FormalizationArtifactStatus.OK
    slices: tuple[DomainLogicSliceV2, ...] = ()
    elaboration_artifact_id: str = ""
    elaboration_content_digest: str = ""
    parse_artifact_id: str = ""
    source_map: SourceMap | None = None
    assumption_ids: tuple[str, ...] = ()
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    content_digest: str = ""
    lineage_digest: str = ""
    legacy_content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION

    interface: ClassVar[str] = FORMALIZATION_ARTIFACT_V3_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _record_id(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "sample_id", _record_id(self.sample_id, "sample_id")
        )
        object.__setattr__(self, "domain", _domain_id(self.domain, "domain"))
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
            "view",
            _coerce_identity(self.view, NamespaceKind.VIEW, "view"),
        )
        object.__setattr__(
            self,
            "notation",
            _coerce_identity(self.notation, NamespaceKind.NOTATION, "notation"),
        )

        if isinstance(self.status, FormalizationArtifactStatus):
            status = self.status
        else:
            try:
                status = FormalizationArtifactStatus(
                    _text(self.status, "status", maximum=32)
                )
            except ValueError as error:
                raise ArtifactV3Error(
                    f"status must be a FormalizationArtifactStatus; "
                    f"got {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        slices = tuple(
            item
            if isinstance(item, DomainLogicSliceV2)
            else DomainLogicSliceV2.from_dict(
                _require_mapping(item, "slices item")
            )
            for item in _require_sequence(self.slices, "slices")
        )
        if len(slices) > MAX_COLLECTION_ITEMS:
            raise ArtifactV3Error("slices exceeds hard ceiling")
        slice_ids = [item.slice_id for item in slices]
        if len(slice_ids) != len(set(slice_ids)):
            raise ArtifactV3Error("slices must have unique slice_id values")
        for item in slices:
            if item.document_id != self.document_id:
                raise ArtifactV3LineageError(
                    f"slice {item.slice_id} document_id does not match artifact"
                )
            if item.source_digest != self.source_digest:
                raise ArtifactV3LineageError(
                    f"slice {item.slice_id} source_digest does not match artifact"
                )
            if item.domain != self.domain:
                raise ArtifactV3LineageError(
                    f"slice {item.slice_id} domain does not match artifact"
                )
            # Expression identity: slices may share the artifact expression or
            # project a related sub-expression, but must still be bound.
            if not item.expression_id or not item.expression_digest:
                raise ArtifactV3LineageError(
                    f"slice {item.slice_id} lacks typed-expression identity"
                )
        object.__setattr__(self, "slices", slices)

        if self.elaboration_artifact_id:
            object.__setattr__(
                self,
                "elaboration_artifact_id",
                _record_id(
                    self.elaboration_artifact_id, "elaboration_artifact_id"
                ),
            )
        object.__setattr__(
            self,
            "elaboration_content_digest",
            _optional_sha256(
                self.elaboration_content_digest, "elaboration_content_digest"
            ),
        )
        if self.parse_artifact_id:
            object.__setattr__(
                self,
                "parse_artifact_id",
                _record_id(self.parse_artifact_id, "parse_artifact_id"),
            )

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
                raise ArtifactV3LineageError(
                    "SourceMap.document_id must match FormalizationArtifactV3."
                    "document_id"
                )

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

        diagnostics = tuple(
            item
            if isinstance(item, SyntaxDiagnostic)
            else SyntaxDiagnostic.from_dict(
                _require_mapping(item, "diagnostics item")
            )
            for item in _require_sequence(self.diagnostics, "diagnostics")
        )
        if len(diagnostics) > MAX_DIAGNOSTICS:
            raise ArtifactV3Error("diagnostics exceeds hard ceiling")
        diagnostic_ids = [item.diagnostic_id for item in diagnostics]
        if len(diagnostic_ids) != len(set(diagnostic_ids)):
            raise ArtifactV3LineageError(
                "duplicate diagnostics are rejected; diagnostic_id values "
                "must be unique"
            )
        known = set(diagnostic_ids)
        for item in diagnostics:
            dangling = [
                related
                for related in item.related_diagnostic_ids
                if related not in known
            ]
            if dangling:
                raise ArtifactV3LineageError(
                    f"diagnostic {item.diagnostic_id} references unknown "
                    f"related diagnostics: {', '.join(dangling)}"
                )
        object.__setattr__(self, "diagnostics", diagnostics)

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_metadata_routing(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION:
            raise ArtifactV3Error(
                f"unsupported FormalizationArtifactV3 schema_version "
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

        if status is FormalizationArtifactStatus.OK:
            if any(item.is_error for item in diagnostics):
                raise ArtifactV3Error(
                    "FormalizationArtifactV3 status ok cannot carry "
                    "error/fatal diagnostics"
                )
            if not slices:
                raise ArtifactV3Error(
                    "FormalizationArtifactV3 status ok requires at least one "
                    "DomainLogicSlice"
                )
            if not any(item.is_admitted for item in slices):
                raise ArtifactV3Error(
                    "FormalizationArtifactV3 status ok requires at least one "
                    "admitted DomainLogicSlice"
                )

        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            provided = _sha256_hex(self.content_digest, "content_digest")
            if provided != content:
                raise ArtifactV3Error(
                    "content_digest does not match FormalizationArtifactV3 content"
                )
            object.__setattr__(self, "content_digest", provided)
        else:
            object.__setattr__(self, "content_digest", content)

        lineage = content_sha256(canonical_json_bytes(self._lineage_payload()))
        if self.lineage_digest:
            provided_lineage = _sha256_hex(self.lineage_digest, "lineage_digest")
            if provided_lineage != lineage:
                raise ArtifactV3LineageError(
                    "lineage_digest does not match FormalizationArtifactV3 lineage"
                )
            object.__setattr__(self, "lineage_digest", provided_lineage)
        else:
            object.__setattr__(self, "lineage_digest", lineage)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "assumption_ids": list(self.assumption_ids),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "domain": self.domain,
            "document_id": self.document_id,
            "elaboration_artifact_id": self.elaboration_artifact_id,
            "elaboration_content_digest": self.elaboration_content_digest,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "family": _identity_payload_value(self.family),  # type: ignore[arg-type]
            "interface": self.interface,
            "notation": _identity_payload_value(self.notation),  # type: ignore[arg-type]
            "parse_artifact_id": self.parse_artifact_id,
            "profile": _identity_payload_value(self.profile),  # type: ignore[arg-type]
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "slices": [item.to_dict() for item in self.slices],
            "source_digest": self.source_digest,
            "source_map": None
            if self.source_map is None
            else self.source_map.to_dict(),
            "status": _status_value(self.status),
            "view": _identity_payload_value(self.view),  # type: ignore[arg-type]
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
            "elaboration_artifact_id": self.elaboration_artifact_id,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "sample_id": self.sample_id,
            "source_digest": self.source_digest,
            "status": _status_value(self.status),
        }

    @property
    def admitted_slices(self) -> tuple[DomainLogicSliceV2, ...]:
        return tuple(item for item in self.slices if item.is_admitted)

    def require_admitted_slices(self) -> tuple[DomainLogicSliceV2, ...]:
        admitted = self.admitted_slices
        if not admitted:
            raise DomainSliceAdmissionError(
                f"FormalizationArtifactV3 {self.artifact_id} has no admitted "
                "domain slices; BackendRequest@2 requires bound source and "
                "typed-expression identity"
            )
        return admitted

    def validate_against(
        self,
        *,
        document: SourceDocument | None = None,
        expression: TypedExpression | None = None,
        elaboration: ElaborationArtifactV2 | None = None,
    ) -> None:
        """Cross-check source, expression, and elaboration lineage."""

        if document is not None:
            if document.document_id != self.document_id:
                raise ArtifactV3LineageError(
                    "document_id does not match the supplied SourceDocument"
                )
            if document.content_digest != self.source_digest:
                raise ArtifactV3LineageError(
                    "source_digest does not match SourceDocument.content_digest"
                )
            for item in self.slices:
                item.validate_against(document=document)
            if self.source_map is not None:
                for entry in self.source_map.entries:
                    entry.range.validate_against(
                        document.byte_length,
                        field_name=f"source map {entry.entry_id}",
                    )
        if expression is not None:
            if expression.expression_id != self.expression_id:
                raise ArtifactV3LineageError(
                    "expression_id does not match the supplied TypedExpression"
                )
            if expression.content_digest != self.expression_digest:
                raise ArtifactV3LineageError(
                    "expression_digest does not match TypedExpression.content_digest"
                )
        if elaboration is not None:
            if (
                self.elaboration_artifact_id
                and elaboration.artifact_id != self.elaboration_artifact_id
            ):
                raise ArtifactV3LineageError(
                    "elaboration_artifact_id does not match ElaborationArtifactV2"
                )
            if elaboration.document_id != self.document_id:
                raise ArtifactV3LineageError(
                    "elaboration document_id does not match formalization "
                    "document_id"
                )
            if elaboration.source_digest != self.source_digest:
                raise ArtifactV3LineageError(
                    "elaboration source_digest does not match formalization "
                    "source_digest"
                )
            if (
                self.elaboration_content_digest
                and elaboration.content_digest != self.elaboration_content_digest
            ):
                raise ArtifactV3LineageError(
                    "elaboration_content_digest does not match "
                    "ElaborationArtifactV2.content_digest"
                )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["lineage_digest"] = self.lineage_digest
        payload["legacy_content_digest"] = self.legacy_content_digest
        payload["metadata"] = _thaw_mapping(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FormalizationArtifactV3":
        payload = _require_mapping(data, "FormalizationArtifactV3")
        interface = payload.get("interface")
        if interface is not None and interface != FORMALIZATION_ARTIFACT_V3_INTERFACE:
            raise ArtifactV3Error(
                f"unsupported FormalizationArtifactV3 interface {interface!r}"
            )
        source_map_payload = payload.get("source_map")
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            sample_id=str(payload.get("sample_id") or ""),
            domain=str(payload.get("domain") or ""),
            document_id=str(payload.get("document_id") or ""),
            source_digest=str(payload.get("source_digest") or ""),
            expression_id=str(payload.get("expression_id") or ""),
            expression_digest=str(payload.get("expression_digest") or ""),
            family=payload.get("family") or "",
            profile=payload.get("profile") or "",
            view=payload.get("view") or "",
            notation=payload.get("notation") or "",
            status=str(
                payload.get("status") or FormalizationArtifactStatus.OK.value
            ),
            slices=tuple(
                DomainLogicSliceV2.from_dict(_require_mapping(item, "slices item"))
                for item in _require_sequence(payload.get("slices") or (), "slices")
            ),
            elaboration_artifact_id=str(
                payload.get("elaboration_artifact_id") or ""
            ),
            elaboration_content_digest=str(
                payload.get("elaboration_content_digest") or ""
            ),
            parse_artifact_id=str(payload.get("parse_artifact_id") or ""),
            source_map=(
                None
                if source_map_payload is None
                else SourceMap.from_dict(
                    _require_mapping(source_map_payload, "source_map")
                )
            ),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
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
            legacy_content_digest=str(payload.get("legacy_content_digest") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version")
                or FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_elaboration(
        cls,
        elaboration: ElaborationArtifactV2,
        *,
        artifact_id: str,
        sample_id: str,
        domain: str,
        property: LogicIdentity | Mapping[str, Any] | str,
        view: LogicIdentity | Mapping[str, Any] | str = "source",
        notation: LogicIdentity | Mapping[str, Any] | str = "canonical_text",
        document: SourceDocument | None = None,
        features: Sequence[str] = (),
        assumption_ids: Sequence[str] = (),
        source_map: SourceMap | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "FormalizationArtifactV3":
        """Project a backend-ready elaboration into FormalizationArtifact@3."""

        if not isinstance(elaboration, ElaborationArtifactV2):
            raise ArtifactV3Error("from_elaboration requires ElaborationArtifactV2")
        expression = elaboration.require_backend_ready()
        if document is not None:
            if document.document_id != elaboration.document_id:
                raise ArtifactV3LineageError(
                    "document_id does not match ElaborationArtifactV2"
                )
            if document.content_digest != elaboration.source_digest:
                raise ArtifactV3LineageError(
                    "source_digest does not match ElaborationArtifactV2"
                )

        slice_item = DomainLogicSliceV2.from_typed_expression(
            expression,
            slice_id=f"slice:{artifact_id}",
            domain=domain,
            document_id=elaboration.document_id,
            source_digest=elaboration.source_digest,
            property=property,
            view=view,
            notation=notation,
            features=features,
            assumption_ids=assumption_ids,
            formalization_artifact_id=artifact_id,
            elaboration_artifact_id=elaboration.artifact_id,
        )
        return cls(
            artifact_id=artifact_id,
            sample_id=sample_id,
            domain=domain,
            document_id=elaboration.document_id,
            source_digest=elaboration.source_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=expression.family
            if expression.family is not None
            else family_id("first_order"),
            profile=expression.profile
            if expression.profile is not None
            else profile_id("many_sorted"),
            view=view,
            notation=notation,
            status=FormalizationArtifactStatus.OK,
            slices=(slice_item,),
            elaboration_artifact_id=elaboration.artifact_id,
            elaboration_content_digest=elaboration.content_digest,
            parse_artifact_id=elaboration.parse_artifact_id,
            source_map=source_map,
            assumption_ids=tuple(assumption_ids),
            diagnostics=elaboration.diagnostics,
            metadata=dict(metadata or {}),
        )


__all__ = [
    "ARTIFACTS_V3_MODULE_VERSION",
    "DOMAIN_LOGIC_SLICE_V2_INTERFACE",
    "DOMAIN_LOGIC_SLICE_V2_SCHEMA_VERSION",
    "FORMALIZATION_ARTIFACT_V3_INTERFACE",
    "FORMALIZATION_ARTIFACT_V3_SCHEMA_VERSION",
    "LEGACY_FORMALIZATION_ARTIFACT_INTERFACE",
    "LEGACY_FORMALIZATION_ARTIFACT_SCHEMA_VERSION",
    "ArtifactV3Error",
    "ArtifactV3LineageError",
    "DomainLogicSliceV2",
    "DomainSliceAdmissionError",
    "DomainSliceStatus",
    "FormalizationArtifactStatus",
    "FormalizationArtifactV3",
]
