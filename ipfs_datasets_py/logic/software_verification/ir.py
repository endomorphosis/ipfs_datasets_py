"""Immutable shared intermediate representation for software verification.

``SoftwareVerificationIR`` binds semantic declarations and verification
targets to exact source bytes using the shared :mod:`logic.ir_core`
provenance types.  It deliberately contains no solver object, provider
request, execution status, or proof verdict.

The document identity is computed from :meth:`semantic_dict`.  Runtime
measurements, timestamps, host details, and other observational output are
preserved under ``observations`` by :meth:`to_dict`, but never enter the
identity preimage.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
from typing import Any, Final

from ipfs_datasets_py.logic.families.models import BoundednessKind
from ipfs_datasets_py.logic.ir_core.artifacts import Artifact
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLocation,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

from .properties import (
    PropertyValidationError,
    VerificationAssumption,
    VerificationProperty,
    validate_extensions,
)


SOFTWARE_VERIFICATION_IR_SCHEMA_VERSION: Final = "software-verification-ir/v1"
SOFTWARE_VERIFICATION_IR_IDENTITY_DOMAIN: Final = "logic.software-verification"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_OBSERVATIONAL_KEYS = frozenset(
    {
        "clock",
        "duration",
        "duration_ms",
        "elapsed",
        "elapsed_ms",
        "ended_at",
        "environment",
        "finished_at",
        "host",
        "hostname",
        "resource_usage",
        "started_at",
        "timing",
        "wall_time",
    }
)


class IRValidationError(ValueError):
    """Raised when a software-verification document is malformed."""


class DeclarationKind(str, Enum):
    """Provider-neutral declaration categories shared by domain IRs."""

    TYPE = "type"
    SORT = "sort"
    CONSTANT = "constant"
    VARIABLE = "variable"
    FUNCTION = "function"
    PREDICATE = "predicate"
    AXIOM = "axiom"
    MODULE = "module"
    STATE = "state"
    TRANSITION = "transition"
    EVENT = "event"
    TRACE = "trace"
    PROGRAM = "program"
    CONTRACT = "contract"
    RESOURCE = "resource"
    POLICY = "policy"
    PROTOCOL = "protocol"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise IRValidationError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise IRValidationError(f"{label} must not contain NUL bytes")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise IRValidationError(f"{label} must be a stable identifier")
    return result


def _identifiers(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise IRValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise IRValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IRValidationError(f"{label} must be a mapping")
    return value


def _freeze_mapping(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise IRValidationError(
            f"{label} must contain JSON-compatible data: {error}"
        ) from error


def _kind_value(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else value


def _declaration_kind(value: DeclarationKind | str) -> DeclarationKind | str:
    if isinstance(value, DeclarationKind):
        return value
    text = _text(value, "kind")
    try:
        return DeclarationKind(text)
    except ValueError:
        try:
            validate_extensions({text: None}, label="custom declaration kind")
        except PropertyValidationError as error:
            raise IRValidationError(str(error)) from error
        return text


def _boundedness_kind(value: BoundednessKind | str) -> BoundednessKind:
    try:
        return value if isinstance(value, BoundednessKind) else BoundednessKind(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in BoundednessKind)
        raise IRValidationError(f"kind must be one of {choices}") from error


def _source_mapping(
    source_ref_ids: Sequence[str],
    span_ids: Sequence[str],
    *,
    owner: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = _identifiers(source_ref_ids, f"{owner}.source_ref_ids")
    spans = _identifiers(span_ids, f"{owner}.span_ids")
    if not sources and not spans:
        raise IRValidationError(
            f"{owner} must be source mapped with source_ref_ids or span_ids"
        )
    return sources, spans


def _reject_observations(value: Mapping[str, Any], *, label: str) -> None:
    offending: list[str] = []

    def visit(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else key
                if key.casefold().replace("-", "_") in _OBSERVATIONAL_KEYS:
                    offending.append(child_path)
                visit(child, child_path)
        elif isinstance(item, tuple):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    if offending:
        raise IRValidationError(
            f"{label} contains observational keys {sorted(offending)}; "
            "put runtime output in observations"
        )


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise IRValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


@dataclass(frozen=True, slots=True)
class VerificationDeclaration:
    """One source-grounded semantic declaration above provider syntax."""

    declaration_id: str
    kind: DeclarationKind | str
    name: str
    payload: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    extensions: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_mapping(
            self.source_ref_ids,
            self.span_ids,
            owner="VerificationDeclaration",
        )
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        object.__setattr__(self, "kind", _declaration_kind(self.kind))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "payload", _freeze_mapping(self.payload, "payload")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(
            self, "depends_on", _identifiers(self.depends_on, "depends_on")
        )
        try:
            extensions = validate_extensions(self.extensions)
        except PropertyValidationError as error:
            raise IRValidationError(str(error)) from error
        object.__setattr__(self, "extensions", extensions)

    @property
    def source_refs(self) -> tuple[str, ...]:
        return self.source_ref_ids

    @property
    def body(self) -> FrozenMap:
        return self.payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "declaration_id": self.declaration_id,
            "depends_on": list(self.depends_on),
            "extensions": self.extensions.to_dict(),
            "kind": _kind_value(self.kind),
            "name": self.name,
            "payload": self.payload.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationDeclaration":
        value = _mapping(value, "declaration")
        _reject_unknown(
            value,
            frozenset(
                {
                    "declaration_id",
                    "kind",
                    "name",
                    "payload",
                    "body",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "depends_on",
                    "extensions",
                }
            ),
            "declaration",
        )
        return cls(
            declaration_id=value.get("declaration_id", ""),
            kind=value.get("kind", ""),
            name=value.get("name", ""),
            payload=FrozenMap(
                _mapping(value.get("payload", value.get("body", {})), "payload")
            ),
            source_ref_ids=tuple(
                value.get("source_ref_ids", value.get("source_refs", ()))
            ),
            span_ids=tuple(value.get("span_ids", ())),
            depends_on=tuple(value.get("depends_on", ())),
            extensions=FrozenMap(_mapping(value.get("extensions", {}), "extensions")),
        )


@dataclass(frozen=True, slots=True)
class VerificationBound:
    """Explicit semantic or execution bound attached to properties."""

    bound_id: str
    kind: BoundednessKind | str
    limits: FrozenMap = field(default_factory=FrozenMap)
    description: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    extensions: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_mapping(
            self.source_ref_ids,
            self.span_ids,
            owner="VerificationBound",
        )
        kind = _boundedness_kind(self.kind)
        limits = _freeze_mapping(self.limits, "limits")
        if (
            kind
            not in {BoundednessKind.UNBOUNDED, BoundednessKind.NOT_APPLICABLE}
            and not limits
        ):
            raise IRValidationError("bounded VerificationBound.limits must not be empty")
        if (
            kind in {BoundednessKind.UNBOUNDED, BoundednessKind.NOT_APPLICABLE}
            and limits
        ):
            raise IRValidationError(
                "unbounded and not-applicable VerificationBound.limits must be empty"
            )
        for name, value in limits.items():
            _identifier(name, "limit name")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise IRValidationError(
                    "bound limit values must be finite numbers or unit-bearing strings"
                )
            if isinstance(value, (int, float)) and value < 0:
                raise IRValidationError("bound limit values must be non-negative")
            if isinstance(value, float) and not math.isfinite(value):
                raise IRValidationError("bound limit values must be finite")
            if isinstance(value, str):
                _text(value, "bound limit value")
        object.__setattr__(self, "bound_id", _identifier(self.bound_id, "bound_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "limits", limits)
        if self.description:
            object.__setattr__(
                self, "description", _text(self.description, "description")
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        try:
            extensions = validate_extensions(self.extensions)
        except PropertyValidationError as error:
            raise IRValidationError(str(error)) from error
        object.__setattr__(self, "extensions", extensions)

    @property
    def source_refs(self) -> tuple[str, ...]:
        return self.source_ref_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_id": self.bound_id,
            "description": self.description,
            "extensions": self.extensions.to_dict(),
            "kind": self.kind.value,
            "limits": self.limits.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationBound":
        value = _mapping(value, "bound")
        _reject_unknown(
            value,
            frozenset(
                {
                    "bound_id",
                    "kind",
                    "limits",
                    "description",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "extensions",
                }
            ),
            "bound",
        )
        return cls(
            bound_id=value.get("bound_id", ""),
            kind=value.get("kind", ""),
            limits=FrozenMap(_mapping(value.get("limits", {}), "limits")),
            description=value.get("description", ""),
            source_ref_ids=tuple(
                value.get("source_ref_ids", value.get("source_refs", ()))
            ),
            span_ids=tuple(value.get("span_ids", ())),
            extensions=FrozenMap(_mapping(value.get("extensions", {}), "extensions")),
        )


def unsupported_construct_diagnostic(
    *,
    construct: str,
    subject_ids: Sequence[str],
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
    field_path: str = "",
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
    remediation: str = "",
) -> Diagnostic:
    """Build a structured diagnostic without dropping an unsupported node."""

    name = _text(construct, "construct")
    return Diagnostic(
        code=DiagnosticCode.UNSUPPORTED_FEATURE,
        message=f"Unsupported software-verification construct retained: {name}.",
        severity=severity,
        location=DiagnosticLocation(
            subject_ids=_identifiers(subject_ids, "subject_ids"),
            source_ref_ids=_identifiers(source_ref_ids, "source_ref_ids"),
            span_ids=_identifiers(span_ids, "span_ids"),
            field_path=field_path,
            metadata={"construct": name, "retained": True},
        ),
        remediation=remediation,
    )


@dataclass(frozen=True, slots=True)
class SoftwareVerificationIR:
    """Canonical immutable source-grounded software-verification document."""

    sources: tuple[SourceRef, ...]
    spans: tuple[SourceSpan, ...] = ()
    declarations: tuple[VerificationDeclaration, ...] = ()
    properties: tuple[VerificationProperty, ...] = ()
    assumptions: tuple[VerificationAssumption, ...] = ()
    bounds: tuple[VerificationBound, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    extensions: FrozenMap = field(default_factory=FrozenMap)
    observations: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = SOFTWARE_VERIFICATION_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sources",
            tuple(
                item
                if isinstance(item, SourceRef)
                else SourceRef.from_dict(_mapping(item, "source"))
                for item in self.sources
            ),
        )
        object.__setattr__(
            self,
            "spans",
            tuple(
                item
                if isinstance(item, SourceSpan)
                else SourceSpan.from_dict(_mapping(item, "span"))
                for item in self.spans
            ),
        )
        object.__setattr__(
            self,
            "declarations",
            tuple(
                item
                if isinstance(item, VerificationDeclaration)
                else VerificationDeclaration.from_dict(_mapping(item, "declaration"))
                for item in self.declarations
            ),
        )
        object.__setattr__(
            self,
            "properties",
            tuple(
                item
                if isinstance(item, VerificationProperty)
                else VerificationProperty.from_dict(_mapping(item, "property"))
                for item in self.properties
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(
                item
                if isinstance(item, VerificationAssumption)
                else VerificationAssumption.from_dict(_mapping(item, "assumption"))
                for item in self.assumptions
            ),
        )
        object.__setattr__(
            self,
            "bounds",
            tuple(
                item
                if isinstance(item, VerificationBound)
                else VerificationBound.from_dict(_mapping(item, "bound"))
                for item in self.bounds
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                item
                if isinstance(item, Diagnostic)
                else Diagnostic.from_dict(_mapping(item, "diagnostic"))
                for item in self.diagnostics
            ),
        )
        object.__setattr__(
            self,
            "artifacts",
            tuple(
                item
                if isinstance(item, Artifact)
                else Artifact.from_dict(_mapping(item, "artifact"))
                for item in self.artifacts
            ),
        )
        metadata = _freeze_mapping(self.metadata, "metadata")
        observations = _freeze_mapping(self.observations, "observations")
        _reject_observations(metadata, label="metadata")
        try:
            extensions = validate_extensions(self.extensions)
        except PropertyValidationError as error:
            raise IRValidationError(str(error)) from error
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "extensions", extensions)
        object.__setattr__(self, "observations", observations)

        self.validate()
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise IRValidationError(
                "document_id does not match canonical semantic content"
            )
        object.__setattr__(self, "document_id", computed.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.document_id

    @property
    def semantic_identity(self) -> str:
        return self.document_id

    @property
    def sha256(self) -> str:
        return self.identity.hexdigest

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=SOFTWARE_VERIFICATION_IR_IDENTITY_DOMAIN,
            schema_version=SOFTWARE_VERIFICATION_IR_SCHEMA_VERSION,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Return the canonical identity preimage, excluding observations."""

        return {
            "artifacts": [
                item.to_dict()
                for item in sorted(self.artifacts, key=lambda item: item.artifact_id)
            ],
            "assumptions": [
                item.to_dict()
                for item in sorted(
                    self.assumptions, key=lambda item: item.assumption_id
                )
            ],
            "bounds": [
                item.to_dict()
                for item in sorted(self.bounds, key=lambda item: item.bound_id)
            ],
            "declarations": [
                item.to_dict()
                for item in sorted(
                    self.declarations, key=lambda item: item.declaration_id
                )
            ],
            "diagnostics": [
                item.to_dict()
                for item in sorted(
                    self.diagnostics, key=lambda item: item.diagnostic_id
                )
            ],
            "extensions": self.extensions.to_dict(),
            "metadata": self.metadata.to_dict(),
            "properties": [
                item.to_dict()
                for item in sorted(
                    self.properties, key=lambda item: item.property_id
                )
            ],
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict()
                for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "spans": [
                item.to_dict()
                for item in sorted(self.spans, key=lambda item: item.span_id)
            ],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["document_id"] = self.document_id
        result["observations"] = self.observations.to_dict()
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def semantic_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    deterministic_bytes = semantic_bytes

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    def validate(self) -> None:
        """Validate source maps and every cross-reference in the document."""

        if self.schema_version != SOFTWARE_VERIFICATION_IR_SCHEMA_VERSION:
            raise IRValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        if not self.sources:
            raise IRValidationError("a source-grounded document requires sources")

        self._unique(self.sources, "ref_id", "source")
        self._unique(self.spans, "span_id", "span")
        self._unique(self.declarations, "declaration_id", "declaration")
        self._unique(self.properties, "property_id", "property")
        self._unique(self.assumptions, "assumption_id", "assumption")
        self._unique(self.bounds, "bound_id", "bound")
        self._unique(self.diagnostics, "diagnostic_id", "diagnostic")
        self._unique(self.artifacts, "artifact_id", "artifact")

        semantic_groups = (
            {item.declaration_id for item in self.declarations},
            {item.property_id for item in self.properties},
            {item.assumption_id for item in self.assumptions},
            {item.bound_id for item in self.bounds},
            {item.artifact_id for item in self.artifacts},
        )
        all_semantic_ids: set[str] = set()
        for group in semantic_groups:
            overlap = all_semantic_ids & group
            if overlap:
                raise IRValidationError(
                    f"semantic identifiers must be globally unique: {sorted(overlap)}"
                )
            all_semantic_ids.update(group)

        source_ids = {item.ref_id for item in self.sources}
        spans = {item.span_id: item for item in self.spans}
        for source in self.sources:
            source.validate()
        for span in self.spans:
            span.validate()
            self._known((span.source_ref_id,), source_ids, f"span {span.span_id}")

        declarations = {item.declaration_id for item in self.declarations}
        assumptions = {item.assumption_id for item in self.assumptions}
        bounds = {item.bound_id for item in self.bounds}
        for item in (
            *self.declarations,
            *self.properties,
            *self.assumptions,
            *self.bounds,
        ):
            self._validate_source_map(item, source_ids=source_ids, spans=spans)

        for declaration in self.declarations:
            self._known(
                declaration.depends_on,
                declarations,
                f"declaration {declaration.declaration_id}.depends_on",
            )
            if declaration.declaration_id in declaration.depends_on:
                raise IRValidationError(
                    f"declaration {declaration.declaration_id} depends on itself"
                )

        valid_subjects = declarations | assumptions | bounds
        for assumption in self.assumptions:
            self._known(
                assumption.subject_ids,
                declarations,
                f"assumption {assumption.assumption_id}.subject_ids",
            )
        for prop in self.properties:
            self._known(
                prop.subject_ids,
                declarations,
                f"property {prop.property_id}.subject_ids",
            )
            self._known(
                prop.assumption_ids,
                assumptions,
                f"property {prop.property_id}.assumption_ids",
            )
            self._known(
                prop.bound_ids,
                bounds,
                f"property {prop.property_id}.bound_ids",
            )

        diagnostic_ids = {item.diagnostic_id for item in self.diagnostics}
        valid_diagnostic_subjects = valid_subjects | {
            item.property_id for item in self.properties
        } | {item.artifact_id for item in self.artifacts}
        for diagnostic in self.diagnostics:
            diagnostic.validate()
            self._known(
                diagnostic.location.subject_ids,
                valid_diagnostic_subjects,
                f"diagnostic {diagnostic.diagnostic_id}.subject_ids",
            )
            self._known(
                diagnostic.location.source_ref_ids,
                source_ids,
                f"diagnostic {diagnostic.diagnostic_id}.source_ref_ids",
            )
            self._known(
                diagnostic.location.span_ids,
                set(spans),
                f"diagnostic {diagnostic.diagnostic_id}.span_ids",
            )
            self._known(
                diagnostic.related_diagnostic_ids,
                diagnostic_ids,
                f"diagnostic {diagnostic.diagnostic_id}.related_diagnostic_ids",
            )
            self._validate_span_sources(
                diagnostic.location.source_ref_ids,
                diagnostic.location.span_ids,
                spans,
                f"diagnostic {diagnostic.diagnostic_id}",
            )

        artifact_ids = {item.artifact_id for item in self.artifacts}
        for artifact in self.artifacts:
            artifact.validate()
            self._known(
                artifact.parent_artifact_ids,
                artifact_ids,
                f"artifact {artifact.artifact_id}.parent_artifact_ids",
            )

    @staticmethod
    def _unique(values: Sequence[object], field_name: str, label: str) -> None:
        ids = [getattr(item, field_name) for item in values]
        if len(ids) != len(set(ids)):
            raise IRValidationError(f"duplicate {label} identifiers")

    @staticmethod
    def _known(values: Sequence[str], known: set[str], label: str) -> None:
        missing = sorted(set(values) - known)
        if missing:
            raise IRValidationError(f"{label} references unknown ids {missing}")

    @classmethod
    def _validate_source_map(
        cls,
        item: object,
        *,
        source_ids: set[str],
        spans: Mapping[str, SourceSpan],
    ) -> None:
        item_id = next(
            getattr(item, name)
            for name in (
                "declaration_id",
                "property_id",
                "assumption_id",
                "bound_id",
            )
            if hasattr(item, name)
        )
        source_ref_ids = getattr(item, "source_ref_ids")
        span_ids = getattr(item, "span_ids")
        cls._known(source_ref_ids, source_ids, f"{item_id}.source_ref_ids")
        cls._known(span_ids, set(spans), f"{item_id}.span_ids")
        cls._validate_span_sources(
            source_ref_ids, span_ids, spans, str(item_id)
        )

    @staticmethod
    def _validate_span_sources(
        source_ref_ids: Sequence[str],
        span_ids: Sequence[str],
        spans: Mapping[str, SourceSpan],
        label: str,
    ) -> None:
        if source_ref_ids:
            unlisted = sorted(
                {
                    spans[span_id].source_ref_id
                    for span_id in span_ids
                    if spans[span_id].source_ref_id not in source_ref_ids
                }
            )
            if unlisted:
                raise IRValidationError(
                    f"{label} spans belong to unlisted sources {unlisted}"
                )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SoftwareVerificationIR":
        value = _mapping(value, "software-verification document")
        _reject_unknown(
            value,
            frozenset(
                {
                    "sources",
                    "spans",
                    "declarations",
                    "properties",
                    "assumptions",
                    "bounds",
                    "diagnostics",
                    "artifacts",
                    "metadata",
                    "extensions",
                    "observations",
                    "document_id",
                    "schema_version",
                }
            ),
            "software-verification document",
        )
        return cls(
            sources=tuple(
                SourceRef.from_dict(_mapping(item, "source"))
                for item in value.get("sources", ())
            ),
            spans=tuple(
                SourceSpan.from_dict(_mapping(item, "span"))
                for item in value.get("spans", ())
            ),
            declarations=tuple(
                VerificationDeclaration.from_dict(_mapping(item, "declaration"))
                for item in value.get("declarations", ())
            ),
            properties=tuple(
                VerificationProperty.from_dict(_mapping(item, "property"))
                for item in value.get("properties", ())
            ),
            assumptions=tuple(
                VerificationAssumption.from_dict(_mapping(item, "assumption"))
                for item in value.get("assumptions", ())
            ),
            bounds=tuple(
                VerificationBound.from_dict(_mapping(item, "bound"))
                for item in value.get("bounds", ())
            ),
            diagnostics=tuple(
                Diagnostic.from_dict(_mapping(item, "diagnostic"))
                for item in value.get("diagnostics", ())
            ),
            artifacts=tuple(
                Artifact.from_dict(_mapping(item, "artifact"))
                for item in value.get("artifacts", ())
            ),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            extensions=FrozenMap(_mapping(value.get("extensions", {}), "extensions")),
            observations=FrozenMap(
                _mapping(value.get("observations", {}), "observations")
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get(
                "schema_version", SOFTWARE_VERIFICATION_IR_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "SoftwareVerificationIR":
        try:
            decoded = json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IRValidationError(
                "software-verification document JSON is malformed"
            ) from error
        if not isinstance(decoded, Mapping):
            raise IRValidationError(
                "software-verification document JSON must contain an object"
            )
        return cls.from_dict(decoded)


# Explicit aliases make composition with ir_core apparent to adapters while
# keeping the shared kernel as the single owner of these contracts.
VerificationArtifact = Artifact
VerificationDiagnostic = Diagnostic
VerificationSource = SourceRef
VerificationSourceSpan = SourceSpan


__all__ = [
    "SOFTWARE_VERIFICATION_IR_IDENTITY_DOMAIN",
    "SOFTWARE_VERIFICATION_IR_SCHEMA_VERSION",
    "DeclarationKind",
    "IRValidationError",
    "SoftwareVerificationIR",
    "VerificationArtifact",
    "VerificationBound",
    "VerificationDeclaration",
    "VerificationDiagnostic",
    "VerificationSource",
    "VerificationSourceSpan",
    "unsupported_construct_diagnostic",
]
