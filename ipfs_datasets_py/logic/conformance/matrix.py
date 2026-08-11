"""Domain × formal-view × family/profile × provider capability matrix baseline.

``LogicCapabilityMatrix@1`` is a side-effect-free inventory surface.  It records
reviewed capability edges without importing solvers, probing the environment,
installing packages, or starting processes.  Support (semantic disposition),
availability (declaration/probe posture), and authority (evidence ceiling) are
independent axes; a supported cell never implies a live binary or a proof claim.

Unknown and unimplemented cells remain first-class so later refill tasks can
target exact coordinates without inventing silent success.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "LogicCapabilityMatrix@1"
SCHEMA_VERSION: Final = "logic-parser-capability-matrix/v1"
MATRIX_VERSION: Final = "1.0.0"
CELL_SCHEMA: Final = "logic-parser-capability-matrix-cell/v1"
EVIDENCE_SCHEMA: Final = "logic-parser-capability-matrix-evidence/v1"

# Baseline report path relative to the nested ``ipfs_datasets_py`` repository.
DEFAULT_BASELINE_RELATIVE_PATH: Final = (
    "docs/architecture/logic/logic_parser_baseline/capability_matrix.json"
)

# Superproject-relative evidence paths used in the sealed baseline.
_PLAN_PATH: Final = "docs/architecture/IPFS_DATASETS_LOGIC_FAMILY_PARSER_PLAN.md"
_BACKEND_REGISTRY: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/backends/registry.py"
)
_FAMILY_REGISTRY: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/families/registry.py"
)
_FAMILY_MODELS: Final = (
    "ipfs_datasets_py/ipfs_datasets_py/logic/families/models.py"
)


class CapabilityMatrixError(ValueError):
    """Raised when matrix data is malformed or contradictory."""


class SupportStatus(StrEnum):
    """Semantic support disposition for one matrix cell.

    Distinct from availability (is a binary declared/probed?) and authority
    (what evidence ceiling may the cell emit?).
    """

    NATIVE = "native"
    TRANSLATED = "translated"
    APPROXIMATE = "approximate"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class AvailabilityStatus(StrEnum):
    """Static availability posture; never claims a live install without a probe."""

    DECLARED = "declared"
    NOT_DECLARED = "not_declared"
    SOURCE_MISSING = "source_missing"
    NOT_PROBED = "not_probed"
    UNKNOWN = "unknown"


class AuthorityCeiling(StrEnum):
    """Maximum evidence authority a cell may produce under its support route."""

    EXACT = "exact"
    BOUNDED = "bounded"
    OVER_APPROXIMATION = "over_approximation"
    KERNEL = "kernel"
    PROTOCOL_SYMBOLIC = "protocol_symbolic"
    AUTHORIZATION_PROFILE = "authorization_profile"
    FINITE_TRACE = "finite_trace"
    ADVISORY = "advisory"
    CANDIDATE = "candidate"
    NONE = "none"
    UNKNOWN = "unknown"


# Support statuses that still need implementation or review refill.
REFILL_SUPPORT_STATUSES: Final = frozenset(
    {
        SupportStatus.UNKNOWN,
        SupportStatus.DECLARATION_ONLY,
        SupportStatus.UNSUPPORTED,
    }
)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityMatrixError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise CapabilityMatrixError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise CapabilityMatrixError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise CapabilityMatrixError(
            f"{field_name} must be one of {choices}"
        ) from error


def _sorted_unique(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CapabilityMatrixError(f"{field_name} must be a sequence of strings")
    items = tuple(_text(item, f"{field_name} item") for item in values)
    if len(set(items)) != len(items):
        raise CapabilityMatrixError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items))


def cell_id(
    domain_id: str,
    formal_view_id: str,
    family_id: str,
    profile_id: str,
    provider_id: str,
) -> str:
    """Stable coordinate identity for one matrix cell.

    Coordinates are joined with ``::`` so formal-view path segments that
    themselves contain ``/`` remain unambiguous.
    """

    return "::".join(
        (
            _identifier(domain_id, "domain_id"),
            _identifier(formal_view_id, "formal_view_id"),
            _identifier(family_id, "family_id"),
            _identifier(profile_id or "default", "profile_id"),
            _identifier(provider_id, "provider_id"),
        )
    )


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """Exact source evidence for a matrix claim."""

    path: str
    kind: str = "source_path"
    locator: str = ""
    note: str = ""
    schema_version: str = EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _text(self.path, "path").replace("\\", "/"))
        if self.path.startswith("/") or ".." in Path(self.path).parts:
            raise CapabilityMatrixError(
                "evidence path must be a normalized repository-relative POSIX path"
            )
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        object.__setattr__(
            self, "locator", _text(self.locator, "locator") if self.locator else ""
        )
        object.__setattr__(
            self, "note", _text(self.note, "note") if self.note else ""
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "note": self.note,
            "path": self.path,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceEvidence:
        if not isinstance(value, Mapping):
            raise CapabilityMatrixError("evidence entry must be an object")
        return cls(
            path=str(value.get("path", "")),
            kind=str(value.get("kind", "source_path")),
            locator=str(value.get("locator", "")),
            note=str(value.get("note", "")),
            schema_version=str(value.get("schema_version", EVIDENCE_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class CapabilityCell:
    """One domain × view × family/profile × provider capability cell."""

    domain_id: str
    formal_view_id: str
    family_id: str
    provider_id: str
    support: SupportStatus
    availability: AvailabilityStatus
    authority_ceiling: AuthorityCeiling
    profile_id: str = "default"
    evidence: tuple[SourceEvidence, ...] = ()
    notes: str = ""
    observed_family_label: str = ""
    unimplemented: bool = False
    schema_version: str = CELL_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self,
            "formal_view_id",
            _identifier(self.formal_view_id, "formal_view_id"),
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id or "default", "profile_id"),
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "support", _enum(self.support, SupportStatus, "support")
        )
        object.__setattr__(
            self,
            "availability",
            _enum(self.availability, AvailabilityStatus, "availability"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, AuthorityCeiling, "authority_ceiling"),
        )
        if isinstance(self.evidence, (str, bytes, bytearray)) or not isinstance(
            self.evidence, Sequence
        ):
            raise CapabilityMatrixError("evidence must be a sequence")
        evidence = tuple(
            item if isinstance(item, SourceEvidence) else SourceEvidence.from_dict(item)
            for item in self.evidence
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(sorted(evidence, key=lambda item: (item.path, item.kind, item.locator))),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        object.__setattr__(
            self,
            "observed_family_label",
            _text(self.observed_family_label, "observed_family_label")
            if self.observed_family_label
            else "",
        )
        if not isinstance(self.unimplemented, bool):
            raise CapabilityMatrixError("unimplemented must be a boolean")
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # Support never upgrades authority; unsupported/unknown force none/unknown.
        if self.support is SupportStatus.UNSUPPORTED and self.authority_ceiling not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.UNKNOWN,
        }:
            raise CapabilityMatrixError(
                "unsupported cells cannot claim a non-empty authority ceiling"
            )
        if self.support is SupportStatus.UNKNOWN and self.authority_ceiling not in {
            AuthorityCeiling.UNKNOWN,
            AuthorityCeiling.NONE,
        }:
            raise CapabilityMatrixError(
                "unknown cells cannot claim a resolved authority ceiling"
            )
        if (
            self.support is SupportStatus.ADVISORY
            and self.authority_ceiling
            not in {
                AuthorityCeiling.ADVISORY,
                AuthorityCeiling.CANDIDATE,
                AuthorityCeiling.NONE,
            }
        ):
            raise CapabilityMatrixError(
                "advisory support cannot claim stronger authority than advisory/candidate"
            )
        if (
            self.availability is AvailabilityStatus.SOURCE_MISSING
            and self.support
            not in {
                SupportStatus.DECLARATION_ONLY,
                SupportStatus.UNKNOWN,
                SupportStatus.UNSUPPORTED,
            }
        ):
            raise CapabilityMatrixError(
                "source-missing availability requires declaration-only/unknown/unsupported support"
            )

    @property
    def id(self) -> str:
        return cell_id(
            self.domain_id,
            self.formal_view_id,
            self.family_id,
            self.profile_id,
            self.provider_id,
        )

    @property
    def refill_eligible(self) -> bool:
        """Whether later inventory/refill work should revisit this cell."""

        return (
            self.unimplemented
            or self.support in REFILL_SUPPORT_STATUSES
            or self.availability
            in {
                AvailabilityStatus.SOURCE_MISSING,
                AvailabilityStatus.UNKNOWN,
                AvailabilityStatus.NOT_DECLARED,
            }
            or self.authority_ceiling is AuthorityCeiling.UNKNOWN
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "availability": self.availability.value,
            "cell_id": self.id,
            "domain_id": self.domain_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "family_id": self.family_id,
            "formal_view_id": self.formal_view_id,
            "notes": self.notes,
            "observed_family_label": self.observed_family_label,
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "refill_eligible": self.refill_eligible,
            "schema_version": self.schema_version,
            "support": self.support.value,
            "unimplemented": self.unimplemented,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CapabilityCell:
        if not isinstance(value, Mapping):
            raise CapabilityMatrixError("cell must be an object")
        return cls(
            domain_id=str(value.get("domain_id", "")),
            formal_view_id=str(value.get("formal_view_id", "")),
            family_id=str(value.get("family_id", "")),
            provider_id=str(value.get("provider_id", "")),
            support=str(value.get("support", SupportStatus.UNKNOWN.value)),
            availability=str(
                value.get("availability", AvailabilityStatus.UNKNOWN.value)
            ),
            authority_ceiling=str(
                value.get("authority_ceiling", AuthorityCeiling.UNKNOWN.value)
            ),
            profile_id=str(value.get("profile_id", "default") or "default"),
            evidence=tuple(value.get("evidence", ())),
            notes=str(value.get("notes", "")),
            observed_family_label=str(value.get("observed_family_label", "")),
            unimplemented=bool(value.get("unimplemented", False)),
            schema_version=str(value.get("schema_version", CELL_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class FormalViewAxis:
    """Domain-scoped formal view with its preferred family/profile coordinates."""

    domain_id: str
    formal_view_id: str
    family_id: str
    profile_id: str = "default"
    observed_family_label: str = ""
    description: str = ""
    source_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self,
            "formal_view_id",
            _identifier(self.formal_view_id, "formal_view_id"),
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id or "default", "profile_id"),
        )
        object.__setattr__(
            self,
            "observed_family_label",
            _text(self.observed_family_label, "observed_family_label")
            if self.observed_family_label
            else "",
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self,
            "source_paths",
            _sorted_unique(self.source_paths, "source_paths")
            if self.source_paths
            else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "domain_id": self.domain_id,
            "family_id": self.family_id,
            "formal_view_id": self.formal_view_id,
            "observed_family_label": self.observed_family_label,
            "profile_id": self.profile_id,
            "source_paths": list(self.source_paths),
        }


@dataclass(frozen=True, slots=True)
class ProviderAxis:
    """Provider lane declared by the plan / executable matrix."""

    provider_id: str
    native_families: tuple[str, ...]
    authority_ceiling: AuthorityCeiling
    support_kind: SupportStatus
    aliases: tuple[str, ...] = ()
    declared_in_executable_matrix: bool = True
    notes: str = ""
    source_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "native_families",
            _sorted_unique(self.native_families, "native_families"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, AuthorityCeiling, "authority_ceiling"),
        )
        object.__setattr__(
            self,
            "support_kind",
            _enum(self.support_kind, SupportStatus, "support_kind"),
        )
        object.__setattr__(
            self,
            "aliases",
            _sorted_unique(self.aliases, "aliases") if self.aliases else (),
        )
        if not isinstance(self.declared_in_executable_matrix, bool):
            raise CapabilityMatrixError(
                "declared_in_executable_matrix must be a boolean"
            )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        object.__setattr__(
            self,
            "source_paths",
            _sorted_unique(self.source_paths, "source_paths")
            if self.source_paths
            else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "authority_ceiling": self.authority_ceiling.value,
            "declared_in_executable_matrix": self.declared_in_executable_matrix,
            "native_families": list(self.native_families),
            "notes": self.notes,
            "provider_id": self.provider_id,
            "source_paths": list(self.source_paths),
            "support_kind": self.support_kind.value,
        }


@dataclass(frozen=True, slots=True)
class LogicCapabilityMatrix:
    """Versioned, inert domain-family-provider capability matrix."""

    domains: tuple[str, ...]
    formal_views: tuple[FormalViewAxis, ...]
    families: tuple[str, ...]
    providers: tuple[ProviderAxis, ...]
    cells: tuple[CapabilityCell, ...]
    version: str = MATRIX_VERSION
    schema_version: str = SCHEMA_VERSION
    interface: str = INTERFACE
    description: str = (
        "Domain × formal-view × family/profile × provider capability baseline. "
        "Support, availability, and authority are independent axes; unknown and "
        "unimplemented cells are retained for refill."
    )
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "domains", _sorted_unique(self.domains, "domains")
        )
        if not self.formal_views:
            raise CapabilityMatrixError("formal_views must be non-empty")
        views = tuple(
            sorted(
                self.formal_views,
                key=lambda item: (item.domain_id, item.formal_view_id, item.family_id),
            )
        )
        view_keys = {
            (item.domain_id, item.formal_view_id, item.family_id, item.profile_id)
            for item in views
        }
        if len(view_keys) != len(views):
            raise CapabilityMatrixError(
                "formal_views must be unique on domain/view/family/profile"
            )
        object.__setattr__(self, "formal_views", views)
        object.__setattr__(
            self, "families", _sorted_unique(self.families, "families")
        )
        providers = tuple(
            sorted(self.providers, key=lambda item: item.provider_id)
        )
        provider_ids = [item.provider_id for item in providers]
        if len(set(provider_ids)) != len(provider_ids):
            raise CapabilityMatrixError("providers must have unique provider_id values")
        object.__setattr__(self, "providers", providers)
        cells = tuple(sorted(self.cells, key=lambda item: item.id))
        cell_ids = [item.id for item in cells]
        if len(set(cell_ids)) != len(cell_ids):
            raise CapabilityMatrixError("cells must have unique cell_id values")
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if not isinstance(self.metadata, Mapping):
            raise CapabilityMatrixError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        # Referential integrity.
        domain_set = set(self.domains)
        family_set = set(self.families)
        provider_set = {item.provider_id for item in self.providers}
        for view in self.formal_views:
            if view.domain_id not in domain_set:
                raise CapabilityMatrixError(
                    f"formal view {view.formal_view_id!r} references unknown domain "
                    f"{view.domain_id!r}"
                )
            if view.family_id not in family_set:
                raise CapabilityMatrixError(
                    f"formal view {view.formal_view_id!r} references unknown family "
                    f"{view.family_id!r}"
                )
        for cell in self.cells:
            if cell.domain_id not in domain_set:
                raise CapabilityMatrixError(
                    f"cell {cell.id!r} references unknown domain {cell.domain_id!r}"
                )
            if cell.family_id not in family_set:
                raise CapabilityMatrixError(
                    f"cell {cell.id!r} references unknown family {cell.family_id!r}"
                )
            if cell.provider_id not in provider_set:
                raise CapabilityMatrixError(
                    f"cell {cell.id!r} references unknown provider {cell.provider_id!r}"
                )

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.providers)

    def provider(self, provider_id: str) -> ProviderAxis:
        canonical = _identifier(provider_id, "provider_id")
        for item in self.providers:
            if item.provider_id == canonical or canonical in item.aliases:
                return item
        raise CapabilityMatrixError(f"unknown provider {provider_id!r}")

    def cell_index(self) -> Mapping[str, CapabilityCell]:
        return MappingProxyType({item.id: item for item in self.cells})

    def get_cell(self, cell_key: str) -> CapabilityCell | None:
        return self.cell_index().get(cell_key)

    def unknown_cells(self) -> tuple[CapabilityCell, ...]:
        """Cells whose support disposition is still unknown."""

        return tuple(
            item for item in self.cells if item.support is SupportStatus.UNKNOWN
        )

    def unimplemented_cells(self) -> tuple[CapabilityCell, ...]:
        """Cells explicitly marked unimplemented for later refill."""

        return tuple(item for item in self.cells if item.unimplemented)

    def refill_cells(self) -> tuple[CapabilityCell, ...]:
        return tuple(item for item in self.cells if item.refill_eligible)

    def cells_for_domain(self, domain_id: str) -> tuple[CapabilityCell, ...]:
        canonical = _identifier(domain_id, "domain_id")
        return tuple(item for item in self.cells if item.domain_id == canonical)

    def cells_for_provider(self, provider_id: str) -> tuple[CapabilityCell, ...]:
        provider = self.provider(provider_id)
        return tuple(
            item for item in self.cells if item.provider_id == provider.provider_id
        )

    def support_histogram(self) -> Mapping[str, int]:
        counts: dict[str, int] = {status.value: 0 for status in SupportStatus}
        for cell in self.cells:
            counts[cell.support.value] += 1
        return MappingProxyType(counts)

    def availability_histogram(self) -> Mapping[str, int]:
        counts: dict[str, int] = {status.value: 0 for status in AvailabilityStatus}
        for cell in self.cells:
            counts[cell.availability.value] += 1
        return MappingProxyType(counts)

    def authority_histogram(self) -> Mapping[str, int]:
        counts: dict[str, int] = {status.value: 0 for status in AuthorityCeiling}
        for cell in self.cells:
            counts[cell.authority_ceiling.value] += 1
        return MappingProxyType(counts)

    def to_dict(self) -> dict[str, Any]:
        """Digest-free serialization used for hashing and round-trips."""

        refill = self.refill_cells()
        unknown = self.unknown_cells()
        unimplemented = self.unimplemented_cells()
        return {
            "authority_histogram": dict(self.authority_histogram()),
            "availability_histogram": dict(self.availability_histogram()),
            "cells": [item.to_dict() for item in self.cells],
            "description": self.description,
            "dimensions": {
                "domains": list(self.domains),
                "families": list(self.families),
                "formal_views": [item.to_dict() for item in self.formal_views],
                "providers": [item.to_dict() for item in self.providers],
            },
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "refill_cells": [item.id for item in refill],
            "refill_count": len(refill),
            "schema_version": self.schema_version,
            "support_histogram": dict(self.support_histogram()),
            "unimplemented_cells": [item.id for item in unimplemented],
            "unimplemented_count": len(unimplemented),
            "unknown_cells": [item.id for item in unknown],
            "unknown_count": len(unknown),
            "version": self.version,
        }

    def content_digest(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_baseline_dict(self) -> dict[str, Any]:
        """Serialize with a content digest over the digest-free body."""

        body = self.to_dict()
        digest = self.content_digest()
        # Stable top-level key order for human review.
        ordered_keys = (
            "schema_version",
            "interface",
            "version",
            "description",
            "notes",
            "metadata",
            "dimensions",
            "cells",
            "support_histogram",
            "availability_histogram",
            "authority_histogram",
            "unknown_count",
            "unknown_cells",
            "unimplemented_count",
            "unimplemented_cells",
            "refill_count",
            "refill_cells",
        )
        ordered = {key: body[key] for key in ordered_keys}
        ordered["content_digest_sha256"] = digest
        return ordered

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicCapabilityMatrix:
        if not isinstance(value, Mapping):
            raise CapabilityMatrixError("matrix must be an object")
        dimensions = value.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise CapabilityMatrixError("dimensions must be an object")
        formal_views = tuple(
            FormalViewAxis(
                domain_id=str(item.get("domain_id", "")),
                formal_view_id=str(item.get("formal_view_id", "")),
                family_id=str(item.get("family_id", "")),
                profile_id=str(item.get("profile_id", "default") or "default"),
                observed_family_label=str(item.get("observed_family_label", "")),
                description=str(item.get("description", "")),
                source_paths=tuple(item.get("source_paths", ())),
            )
            for item in dimensions.get("formal_views", ())
        )
        providers = tuple(
            ProviderAxis(
                provider_id=str(item.get("provider_id", "")),
                native_families=tuple(item.get("native_families", ())),
                authority_ceiling=str(
                    item.get("authority_ceiling", AuthorityCeiling.UNKNOWN.value)
                ),
                support_kind=str(
                    item.get("support_kind", SupportStatus.UNKNOWN.value)
                ),
                aliases=tuple(item.get("aliases", ())),
                declared_in_executable_matrix=bool(
                    item.get("declared_in_executable_matrix", True)
                ),
                notes=str(item.get("notes", "")),
                source_paths=tuple(item.get("source_paths", ())),
            )
            for item in dimensions.get("providers", ())
        )
        cells = tuple(
            CapabilityCell.from_dict(item) for item in value.get("cells", ())
        )
        return cls(
            domains=tuple(dimensions.get("domains", ())),
            formal_views=formal_views,
            families=tuple(dimensions.get("families", ())),
            providers=providers,
            cells=cells,
            version=str(value.get("version", MATRIX_VERSION)),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            interface=str(value.get("interface", INTERFACE)),
            description=str(value.get("description", "")),
            notes=str(value.get("notes", "")),
            metadata=dict(value.get("metadata", {}) or {}),
        )


def render_matrix_json(matrix: LogicCapabilityMatrix) -> str:
    """Deterministic JSON rendering with trailing newline."""

    return (
        json.dumps(
            matrix.to_baseline_dict(),
            ensure_ascii=True,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )


MATERIALIZATION_TARGET: Final = (
    "ipfs_datasets_py.logic.conformance.matrix:build_default_matrix"
)


def write_matrix_baseline(
    matrix: LogicCapabilityMatrix,
    path: str | Path,
    *,
    full_cells: bool = True,
) -> Path:
    """Atomically write a baseline report to ``path``.

    When ``full_cells`` is false, write a compact seal that records axes,
    histograms, unknown/refill coordinates, and a materialization pointer.
    Full cell bodies remain available from :func:`build_default_matrix`.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if full_cells:
        rendered = render_matrix_json(matrix)
    else:
        rendered = render_matrix_seal_json(matrix)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(target)
    return target


def to_matrix_seal_dict(matrix: LogicCapabilityMatrix) -> dict[str, Any]:
    """Compact sealed baseline: axes + refill surface + materialization pointer."""

    baseline = matrix.to_baseline_dict()
    return {
        "schema_version": baseline["schema_version"],
        "interface": baseline["interface"],
        "version": baseline["version"],
        "description": baseline["description"],
        "notes": baseline["notes"],
        "metadata": baseline["metadata"],
        "materialization": MATERIALIZATION_TARGET,
        "dimensions": baseline["dimensions"],
        "cell_count": len(matrix.cells),
        "support_histogram": baseline["support_histogram"],
        "availability_histogram": baseline["availability_histogram"],
        "authority_histogram": baseline["authority_histogram"],
        "unknown_count": baseline["unknown_count"],
        "unknown_cells": baseline["unknown_cells"],
        "unimplemented_count": baseline["unimplemented_count"],
        "unimplemented_cells": baseline["unimplemented_cells"],
        "refill_count": baseline["refill_count"],
        "refill_cells": baseline["refill_cells"],
        "content_digest_sha256": baseline["content_digest_sha256"],
    }


def render_matrix_seal_json(matrix: LogicCapabilityMatrix) -> str:
    """Deterministic compact seal JSON with trailing newline."""

    return (
        json.dumps(
            to_matrix_seal_dict(matrix),
            ensure_ascii=True,
            indent=2,
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )


def _validate_seal_against_matrix(
    payload: Mapping[str, Any],
    matrix: LogicCapabilityMatrix,
) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CapabilityMatrixError(
            f"unsupported schema_version {payload.get('schema_version')!r}"
        )
    if payload.get("interface") != INTERFACE:
        raise CapabilityMatrixError(
            f"unsupported interface {payload.get('interface')!r}"
        )
    if payload.get("materialization") != MATERIALIZATION_TARGET:
        raise CapabilityMatrixError(
            f"unsupported materialization {payload.get('materialization')!r}"
        )
    live = matrix.to_baseline_dict()
    seal_dims = payload.get("dimensions")
    if seal_dims is not None:
        if not isinstance(seal_dims, Mapping):
            raise CapabilityMatrixError("seal dimensions must be an object")
        if seal_dims != live["dimensions"]:
            raise CapabilityMatrixError(
                "seal dimensions disagree with materialization"
            )
    for key in (
        "support_histogram",
        "availability_histogram",
        "authority_histogram",
        "unknown_count",
        "unknown_cells",
        "unimplemented_count",
        "unimplemented_cells",
        "refill_count",
        "refill_cells",
        "content_digest_sha256",
    ):
        if key in payload and payload[key] != live[key]:
            raise CapabilityMatrixError(
                f"seal field {key!r} disagrees with materialization"
            )
    if "cell_count" in payload and payload["cell_count"] != len(matrix.cells):
        raise CapabilityMatrixError("seal cell_count disagrees with materialization")


def load_matrix_baseline(path: str | Path) -> LogicCapabilityMatrix:
    """Load and validate a baseline capability matrix report.

    Accepts either a full cell expansion or a compact materialization seal.
    Compact seals re-materialize through :func:`build_default_matrix` and
    validate that sealed axes/histograms/refill coordinates still match.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise CapabilityMatrixError("matrix baseline must be an object")
    if payload.get("materialization"):
        matrix = build_default_matrix()
        _validate_seal_against_matrix(payload, matrix)
        return matrix
    matrix = LogicCapabilityMatrix.from_dict(payload)
    if matrix.schema_version != SCHEMA_VERSION:
        raise CapabilityMatrixError(
            f"unsupported schema_version {matrix.schema_version!r}"
        )
    if matrix.interface != INTERFACE:
        raise CapabilityMatrixError(f"unsupported interface {matrix.interface!r}")
    return matrix


def default_baseline_path(*, datasets_root: str | Path | None = None) -> Path:
    """Resolve the sealed baseline path under the nested datasets repository."""

    if datasets_root is None:
        # .../ipfs_datasets_py/logic/conformance/matrix.py -> datasets repo root
        datasets_root = Path(__file__).resolve().parents[3]
    return Path(datasets_root) / DEFAULT_BASELINE_RELATIVE_PATH


def ensure_baseline_seal(
    path: str | Path | None = None,
    *,
    datasets_root: str | Path | None = None,
) -> Path:
    """Write or refresh the compact sealed baseline for the default matrix."""

    target = Path(path) if path is not None else default_baseline_path(
        datasets_root=datasets_root
    )
    return write_matrix_baseline(
        build_default_matrix(),
        target,
        full_cells=False,
    )


# ---------------------------------------------------------------------------
# Baseline axes and materialization
# ---------------------------------------------------------------------------


def _evidence(*paths: str, locator: str = "", note: str = "") -> tuple[SourceEvidence, ...]:
    return tuple(
        SourceEvidence(path=path, locator=locator, note=note) for path in paths
    )


def _view(
    domain_id: str,
    formal_view_id: str,
    family_id: str,
    *,
    profile_id: str = "default",
    observed_family_label: str = "",
    description: str = "",
    source_paths: Sequence[str] = (),
) -> FormalViewAxis:
    return FormalViewAxis(
        domain_id=domain_id,
        formal_view_id=formal_view_id,
        family_id=family_id,
        profile_id=profile_id,
        observed_family_label=observed_family_label,
        description=description,
        source_paths=tuple(source_paths),
    )


def _provider(
    provider_id: str,
    native_families: Sequence[str],
    authority: AuthorityCeiling,
    support_kind: SupportStatus,
    *,
    aliases: Sequence[str] = (),
    declared: bool = True,
    notes: str = "",
    source_paths: Sequence[str] = (),
) -> ProviderAxis:
    return ProviderAxis(
        provider_id=provider_id,
        native_families=tuple(native_families),
        authority_ceiling=authority,
        support_kind=support_kind,
        aliases=tuple(aliases),
        declared_in_executable_matrix=declared,
        notes=notes,
        source_paths=tuple(source_paths),
    )


CANONICAL_FAMILIES: Final[tuple[str, ...]] = (
    "authorization",
    "concurrency",
    "cryptographic_protocol",
    "datalog",
    "dcec",
    "deontic",
    "event_calculus",
    "first_order",
    "frame_logic",
    "higher_order",
    "horn_chc",
    "hyperproperty",
    "modal",
    "mu_calculus",
    "program",
    "propositional",
    "refinement",
    "separation_logic",
    "tdfol",
    "temporal",
    "transition_system",
)

DOMAIN_IDS: Final[tuple[str, ...]] = (
    "crypto_ir",
    "intent_ir",
    "legal_ir",
    "security_ir",
    "software_verification",
    "ui_ux_ir",
)

# Families that are declaration-only in the v1 taxonomy wave.
DECLARATION_ONLY_FAMILIES: Final = frozenset({"mu_calculus"})

# Provider native family membership for routing support.
# Keys are provider ids; values are families they natively address.
PROVIDER_AXES: Final[tuple[ProviderAxis, ...]] = (
    _provider(
        "apalache",
        ("temporal", "transition_system"),
        AuthorityCeiling.BOUNDED,
        SupportStatus.BOUNDED,
        notes="Bounded symbolic TLA+ lane.",
        source_paths=(_BACKEND_REGISTRY, _PLAN_PATH),
    ),
    _provider(
        "cvc5",
        ("first_order", "horn_chc", "propositional"),
        AuthorityCeiling.EXACT,
        SupportStatus.NATIVE,
        notes="SMT compiler and result decoder; SyGuS remains declaration-only in v1.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/cvc5/compiler.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "datalog_secpal",
        ("authorization", "datalog"),
        AuthorityCeiling.AUTHORIZATION_PROFILE,
        SupportStatus.NATIVE,
        aliases=("datalog-authorization", "secpal-authorization"),
        notes="Datalog/Horn/SecPAL authorization lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/secpal_style_authorization.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "eprover",
        ("dcec", "first_order", "tdfol"),
        AuthorityCeiling.CANDIDATE,
        SupportStatus.NATIVE,
        aliases=("e",),
        notes="E prover classical TPTP ATP lane; untrusted until reconstructed.",
        source_paths=(_BACKEND_REGISTRY, _PLAN_PATH),
    ),
    _provider(
        "ergoai",
        ("frame_logic",),
        AuthorityCeiling.ADVISORY,
        SupportStatus.ADVISORY,
        aliases=("ergo_ai",),
        declared=False,
        notes="Controlled F-logic/rule advisor; not an executable matrix proof lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/flogic/ergoai_wrapper.py",
            _PLAN_PATH,
        ),
    ),
    _provider(
        "hammer",
        ("first_order", "higher_order"),
        AuthorityCeiling.ADVISORY,
        SupportStatus.ADVISORY,
        notes="Premise-selection/reconstruction strategy lane; advisory until reconstruction.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/hammers/backend.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "hyperltl_autohyper_mchyper",
        ("hyperproperty",),
        AuthorityCeiling.BOUNDED,
        SupportStatus.BOUNDED,
        aliases=("autohyper", "hyperltl", "mchyper"),
        notes="HyperLTL AutoHyper/MCHyper lane.",
        source_paths=(_BACKEND_REGISTRY, _PLAN_PATH),
    ),
    _provider(
        "isabelle",
        ("higher_order", "program"),
        AuthorityCeiling.KERNEL,
        SupportStatus.NATIVE,
        notes="Isabelle/HOL kernel target lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/kernel/isabelle.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "lean",
        ("higher_order", "program"),
        AuthorityCeiling.KERNEL,
        SupportStatus.NATIVE,
        notes="Lean kernel target lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/kernel/lean.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "proverif",
        ("cryptographic_protocol",),
        AuthorityCeiling.OVER_APPROXIMATION,
        SupportStatus.APPROXIMATE,
        notes="Symbolic applied-pi protocol lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/protocol/proverif.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "rocq",
        ("higher_order", "program"),
        AuthorityCeiling.KERNEL,
        SupportStatus.NATIVE,
        aliases=("coq", "coqc"),
        notes="Rocq kernel target lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/kernel/rocq.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "runtime_mtl",
        ("temporal",),
        AuthorityCeiling.FINITE_TRACE,
        SupportStatus.BOUNDED,
        notes="Finite-trace metric-temporal monitor lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/monitoring/runtime_mtl.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "symbolicai",
        (),
        AuthorityCeiling.CANDIDATE,
        SupportStatus.ADVISORY,
        aliases=("symai",),
        declared=False,
        notes="Natural-language/symbolic proposal advisor; unverified candidate only.",
        source_paths=(_PLAN_PATH,),
    ),
    _provider(
        "tamarin",
        ("cryptographic_protocol",),
        AuthorityCeiling.PROTOCOL_SYMBOLIC,
        SupportStatus.NATIVE,
        notes="Multiset-rewriting protocol lane.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/protocol/tamarin.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "tla_tlc",
        ("temporal", "transition_system"),
        AuthorityCeiling.BOUNDED,
        SupportStatus.BOUNDED,
        aliases=("tlc",),
        notes="Finite-state TLC lane; exhaustive only for configured finite state space.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/tla/runners.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
    _provider(
        "vampire",
        ("dcec", "first_order", "tdfol"),
        AuthorityCeiling.CANDIDATE,
        SupportStatus.NATIVE,
        notes="Classical TPTP ATP lane; untrusted until reconstructed.",
        source_paths=(_BACKEND_REGISTRY, _PLAN_PATH),
    ),
    _provider(
        "z3",
        ("first_order", "horn_chc", "propositional"),
        AuthorityCeiling.EXACT,
        SupportStatus.NATIVE,
        notes="SMT/CHC compiler and result decoder.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/backends/z3/compiler.py",
            _BACKEND_REGISTRY,
            _PLAN_PATH,
        ),
    ),
)

FORMAL_VIEW_AXES: Final[tuple[FormalViewAxis, ...]] = (
    # security_ir
    _view(
        "security_ir",
        "security-ir-view/threat/v1",
        "transition_system",
        profile_id="threat_model",
        observed_family_label="threat_model",
        description="Threat-model transition obligations from Security IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/formalization_adapter.py",
        ),
    ),
    _view(
        "security_ir",
        "security-ir-view/policy/v1",
        "deontic",
        profile_id="authorization_policy",
        observed_family_label="deontic",
        description="Policy and authorization norms from Security IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/formalization_adapter.py",
        ),
    ),
    _view(
        "security_ir",
        "security-ir-view/policy/v1",
        "authorization",
        profile_id="secpal",
        observed_family_label="deontic",
        description="SecPAL/Datalog authorization projection of Security IR policy.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/formalization_adapter.py",
            _PLAN_PATH,
        ),
    ),
    _view(
        "security_ir",
        "security-ir-view/transition/v1",
        "transition_system",
        description="State-transition formalization of Security IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/formalization_adapter.py",
        ),
    ),
    _view(
        "security_ir",
        "security-ir-view/transition/v1",
        "temporal",
        profile_id="ltl",
        description="Temporal threat/transition properties for Security IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/formalization_adapter.py",
            _PLAN_PATH,
        ),
    ),
    _view(
        "security_ir",
        "security-ir-view/claim/v1",
        "first_order",
        profile_id="verification_condition",
        observed_family_label="verification_condition",
        description="Verification-condition claims from Security IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/security_ir/formalization_adapter.py",
        ),
    ),
    _view(
        "security_ir",
        "security-ir-view/claim/v1",
        "horn_chc",
        profile_id="chc_vc",
        observed_family_label="verification_condition",
        description="CHC-style verification conditions for Security IR claims.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "security_ir",
        "security-ir-view/protocol/v1",
        "cryptographic_protocol",
        description="Protocol obligations declared for Security IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "security_ir",
        "security-ir-view/hyperproperty/v1",
        "hyperproperty",
        description="Hyperproperty/noninterference views for Security IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "security_ir",
        "security-ir-view/concurrency/v1",
        "concurrency",
        description="Concurrency obligations for Security IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "security_ir",
        "security-ir-view/separation/v1",
        "separation_logic",
        description="Separation/resource obligations for Security IR.",
        source_paths=(_PLAN_PATH,),
    ),
    # crypto_ir
    _view(
        "crypto_ir",
        "crypto-ir-view/propositional/v1",
        "propositional",
        description="Propositional formal target for Crypto IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/crypto_ir/formalization/compiler.py",
        ),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/smt/v1",
        "first_order",
        profile_id="smt_lib",
        observed_family_label="smt",
        description="SMT-LIB arithmetic/invariant formal target for Crypto IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/crypto_ir/formalization/compiler.py",
            _PLAN_PATH,
        ),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/fol/v1",
        "first_order",
        description="First-order formal target for Crypto IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/crypto_ir/formalization/compiler.py",
        ),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/datalog/v1",
        "datalog",
        description="Datalog/authorization formal target for Crypto IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/crypto_ir/formalization/compiler.py",
        ),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/temporal/v1",
        "temporal",
        description="Temporal/ledger-finality formal target for Crypto IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/crypto_ir/formalization/compiler.py",
            _PLAN_PATH,
        ),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/transition/v1",
        "transition_system",
        description="Ledger/reorg/finality transition systems for Crypto IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/protocol/v1",
        "cryptographic_protocol",
        description="Wallet/bridge/network protocol views for Crypto IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/hyperproperty/v1",
        "hyperproperty",
        description="Anonymity/relational hyperproperties for Crypto IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/authorization/v1",
        "authorization",
        description="Authorization/compliance views for Crypto IR.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "crypto_ir",
        "crypto-ir-view/refinement/v1",
        "refinement",
        description="Refinement obligations for Crypto IR.",
        source_paths=(_PLAN_PATH,),
    ),
    # intent_ir
    _view(
        "intent_ir",
        "intent-ir-view/facts/v1",
        "first_order",
        profile_id="typed_first_order",
        observed_family_label="typed_first_order",
        description="Typed facts/guards from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/intention-deontic/v1",
        "deontic",
        profile_id="bdi_intention",
        observed_family_label="intention_deontic",
        description="Deontic/BDI intention modalities from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/action-hoare/v1",
        "program",
        profile_id="dynamic_hoare",
        observed_family_label="dynamic_hoare",
        description="Dynamic/Hoare skill effects from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/workflow-temporal/v1",
        "temporal",
        profile_id="workflow_temporal",
        observed_family_label="workflow_temporal",
        description="Workflow temporal control from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/invariant/v1",
        "temporal",
        profile_id="safety",
        observed_family_label="safety",
        description="Safety invariants from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/failure/v1",
        "temporal",
        profile_id="safety_liveness",
        observed_family_label="safety_liveness",
        description="Failure conditions from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/verification/v1",
        "first_order",
        profile_id="verification_condition",
        observed_family_label="verification_condition",
        description="Verification criteria from Intent IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/intent_ir/formalize/compiler.py",
        ),
    ),
    _view(
        "intent_ir",
        "intent-ir-view/authorization/v1",
        "authorization",
        description="Tool/resource authorization views for Intent IR.",
        source_paths=(_PLAN_PATH,),
    ),
    # legal_ir
    _view(
        "legal_ir",
        "legal-ir-view/deontic/v1",
        "deontic",
        description="Deontic norms from Legal IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/legal_ir/adapter.py",
        ),
    ),
    _view(
        "legal_ir",
        "legal-ir-view/frame-logic/v1",
        "frame_logic",
        description="Frame-logic roles from Legal IR.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/legal_ir/adapter.py",
        ),
    ),
    _view(
        "legal_ir",
        "legal-ir-view/tdfol/v1",
        "tdfol",
        profile_id="temporal_first_order",
        observed_family_label="temporal_first_order",
        description="Temporal first-order legal formulas.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/legal_ir/adapter.py",
        ),
    ),
    _view(
        "legal_ir",
        "legal-ir-view/cec/v1",
        "event_calculus",
        observed_family_label="event_calculus",
        description="Event-calculus legal lifecycle views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/legal_ir/adapter.py",
        ),
    ),
    _view(
        "legal_ir",
        "legal-ir-view/authorization/v1",
        "authorization",
        description="Authorization profile over legal norms.",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "legal_ir",
        "legal-ir-view/description-declaration/v1",
        "modal",
        profile_id="description_logic",
        description="Description/ontology legal views remain declaration-only in v1.",
        source_paths=(_PLAN_PATH,),
    ),
    # software_verification
    _view(
        "software_verification",
        "software-verification-view/program/v1",
        "program",
        description="Program/contract views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/program.py",
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/contracts.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/vc/v1",
        "first_order",
        profile_id="verification_condition",
        observed_family_label="verification_condition",
        description="Verification-condition discharge views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/vc.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/transition/v1",
        "transition_system",
        description="Transition-system software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/transitions.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/temporal/v1",
        "temporal",
        description="Temporal software properties.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/temporal.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/separation/v1",
        "separation_logic",
        description="Separation-logic software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/separation.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/concurrency/v1",
        "concurrency",
        description="Concurrency/rely-guarantee software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/concurrency.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/refinement/v1",
        "refinement",
        description="Refinement software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/refinement.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/protocol/v1",
        "cryptographic_protocol",
        description="Protocol software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/protocol.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/hyperproperty/v1",
        "hyperproperty",
        description="Hyperproperty software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/hyperproperties.py",
        ),
    ),
    _view(
        "software_verification",
        "software-verification-view/authorization/v1",
        "authorization",
        description="Authorization software views.",
        source_paths=(
            "ipfs_datasets_py/ipfs_datasets_py/logic/software_verification/authorization.py",
        ),
    ),
    # ui_ux_ir — source not in pinned revision; declaration-only placeholders.
    _view(
        "ui_ux_ir",
        "ui-ux-ir-view/ontology/v1",
        "frame_logic",
        description="UI ontology/F-logic view (source not in pinned revision).",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "ui_ux_ir",
        "ui-ux-ir-view/event-calculus/v1",
        "event_calculus",
        description="UI event-calculus view (source not in pinned revision).",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "ui_ux_ir",
        "ui-ux-ir-view/tdfol/v1",
        "tdfol",
        description="UI TDFOL/DCEC view (source not in pinned revision).",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "ui_ux_ir",
        "ui-ux-ir-view/navigation-temporal/v1",
        "temporal",
        description="UI navigation temporal view (source not in pinned revision).",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "ui_ux_ir",
        "ui-ux-ir-view/navigation-transition/v1",
        "transition_system",
        description="UI navigation transition view (source not in pinned revision).",
        source_paths=(_PLAN_PATH,),
    ),
    _view(
        "ui_ux_ir",
        "ui-ux-ir-view/accessibility/v1",
        "first_order",
        profile_id="accessibility_property",
        description="UI accessibility property view (source not in pinned revision).",
        source_paths=(_PLAN_PATH,),
    ),
)


def _translated_families(provider: ProviderAxis) -> frozenset[str]:
    """Families reachable by a reviewed translation-shaped route."""

    native = set(provider.native_families)
    translated: set[str] = set()
    if "first_order" in native:
        translated.update({"propositional", "deontic", "modal", "tdfol", "dcec"})
    if "horn_chc" in native:
        translated.update({"datalog", "authorization"})
    if "temporal" in native or "transition_system" in native:
        translated.update({"temporal", "transition_system", "program"})
    if "higher_order" in native:
        translated.update({"first_order", "program", "separation_logic", "concurrency"})
    if provider.provider_id == "symbolicai":
        # Advisor may propose candidates for any family; never native support.
        translated = set()
    return frozenset(translated - native)


def _classify_cell(
    view: FormalViewAxis,
    provider: ProviderAxis,
) -> CapabilityCell:
    """Derive one cell without environment probing."""

    evidence_paths = list(view.source_paths) + list(provider.source_paths)
    if not evidence_paths:
        evidence_paths = [_PLAN_PATH, _FAMILY_REGISTRY, _FAMILY_MODELS]
    evidence = _evidence(
        *sorted(set(evidence_paths)),
        locator=f"{view.domain_id}/{view.formal_view_id}/{provider.provider_id}",
        note="Static inventory evidence only; availability is not runtime-probed.",
    )

    # UI domain is declaration-only until the pinned tree contains ui_ux_ir.
    if view.domain_id == "ui_ux_ir":
        return CapabilityCell(
            domain_id=view.domain_id,
            formal_view_id=view.formal_view_id,
            family_id=view.family_id,
            provider_id=provider.provider_id,
            support=SupportStatus.DECLARATION_ONLY,
            availability=AvailabilityStatus.SOURCE_MISSING,
            authority_ceiling=AuthorityCeiling.NONE,
            profile_id=view.profile_id,
            evidence=evidence,
            notes=(
                "ui_ux_ir is not present in the pinned datasets revision; "
                "every UI cell is declaration-only with source_not_in_pinned_revision."
            ),
            observed_family_label=view.observed_family_label,
            unimplemented=True,
        )

    if view.family_id in DECLARATION_ONLY_FAMILIES:
        return CapabilityCell(
            domain_id=view.domain_id,
            formal_view_id=view.formal_view_id,
            family_id=view.family_id,
            provider_id=provider.provider_id,
            support=SupportStatus.DECLARATION_ONLY,
            availability=(
                AvailabilityStatus.DECLARED
                if provider.declared_in_executable_matrix
                else AvailabilityStatus.NOT_DECLARED
            ),
            authority_ceiling=AuthorityCeiling.NONE,
            profile_id=view.profile_id,
            evidence=evidence,
            notes=f"Family {view.family_id} is declaration-only in the v1 taxonomy wave.",
            observed_family_label=view.observed_family_label,
            unimplemented=True,
        )

    # Advisor lanes.
    if provider.support_kind is SupportStatus.ADVISORY:
        # ErgoAI is meaningful for frame_logic; SymbolicAI is candidate-wide.
        if provider.provider_id == "ergoai" and view.family_id != "frame_logic":
            support = SupportStatus.UNSUPPORTED
            authority = AuthorityCeiling.NONE
            notes = "ErgoAI advisor lane is scoped to controlled F-logic/frame_logic."
            unimplemented = False
        elif provider.provider_id == "hammer" and view.family_id not in {
            "first_order",
            "higher_order",
            "program",
            "deontic",
            "tdfol",
            "dcec",
        }:
            support = SupportStatus.UNSUPPORTED
            authority = AuthorityCeiling.NONE
            notes = "Hammer advisory lane does not declare this family."
            unimplemented = False
        else:
            support = SupportStatus.ADVISORY
            authority = provider.authority_ceiling
            notes = provider.notes or "Advisory provider lane."
            unimplemented = provider.provider_id in {"ergoai", "symbolicai", "hammer"}
        return CapabilityCell(
            domain_id=view.domain_id,
            formal_view_id=view.formal_view_id,
            family_id=view.family_id,
            provider_id=provider.provider_id,
            support=support,
            availability=(
                AvailabilityStatus.DECLARED
                if provider.declared_in_executable_matrix
                else AvailabilityStatus.NOT_DECLARED
            ),
            authority_ceiling=authority,
            profile_id=view.profile_id,
            evidence=evidence,
            notes=notes,
            observed_family_label=view.observed_family_label,
            unimplemented=unimplemented,
        )

    native = set(provider.native_families)
    translated = _translated_families(provider)

    if view.family_id in native:
        support = provider.support_kind
        authority = provider.authority_ceiling
        notes = (
            f"Provider {provider.provider_id} natively addresses family "
            f"{view.family_id}."
        )
        unimplemented = support in {
            SupportStatus.DECLARATION_ONLY,
            SupportStatus.UNKNOWN,
        }
    elif view.family_id in translated:
        support = SupportStatus.TRANSLATED
        # Translated routes inherit the weaker of candidate/exact ceilings.
        if provider.authority_ceiling is AuthorityCeiling.EXACT:
            authority = AuthorityCeiling.BOUNDED
        elif provider.authority_ceiling is AuthorityCeiling.KERNEL:
            authority = AuthorityCeiling.CANDIDATE
        else:
            authority = provider.authority_ceiling
        notes = (
            f"Provider {provider.provider_id} may address family {view.family_id} "
            "only through an explicit translation edge."
        )
        unimplemented = True  # translation edge not yet closed for this domain view
    else:
        # Known provider × family incompatibility is unsupported; remaining gaps
        # stay unknown so refill can target them.
        if provider.native_families:
            support = SupportStatus.UNSUPPORTED
            authority = AuthorityCeiling.NONE
            notes = (
                f"No native or reviewed translated route from family "
                f"{view.family_id} to provider {provider.provider_id}."
            )
            unimplemented = False
        else:
            support = SupportStatus.UNKNOWN
            authority = AuthorityCeiling.UNKNOWN
            notes = "No reviewed capability edge for this coordinate."
            unimplemented = True

    availability = (
        AvailabilityStatus.NOT_PROBED
        if support
        not in {
            SupportStatus.UNSUPPORTED,
            SupportStatus.UNKNOWN,
            SupportStatus.DECLARATION_ONLY,
        }
        and provider.declared_in_executable_matrix
        else (
            AvailabilityStatus.DECLARED
            if provider.declared_in_executable_matrix
            else AvailabilityStatus.NOT_DECLARED
        )
    )
    # Unsupported cells still record that the provider is declared, without
    # implying a probe.
    if support is SupportStatus.UNSUPPORTED and provider.declared_in_executable_matrix:
        availability = AvailabilityStatus.DECLARED
    if support is SupportStatus.UNKNOWN:
        availability = AvailabilityStatus.UNKNOWN

    return CapabilityCell(
        domain_id=view.domain_id,
        formal_view_id=view.formal_view_id,
        family_id=view.family_id,
        provider_id=provider.provider_id,
        support=support,
        availability=availability,
        authority_ceiling=authority,
        profile_id=view.profile_id,
        evidence=evidence,
        notes=notes,
        observed_family_label=view.observed_family_label,
        unimplemented=unimplemented,
    )


def materialize_capability_matrix(
    *,
    formal_views: Sequence[FormalViewAxis] | None = None,
    providers: Sequence[ProviderAxis] | None = None,
    families: Sequence[str] | None = None,
    domains: Sequence[str] | None = None,
) -> LogicCapabilityMatrix:
    """Materialize the full domain-view-family-provider baseline matrix."""

    views = tuple(formal_views) if formal_views is not None else FORMAL_VIEW_AXES
    provider_axes = tuple(providers) if providers is not None else PROVIDER_AXES
    family_ids = (
        tuple(families) if families is not None else CANONICAL_FAMILIES
    )
    domain_ids = tuple(domains) if domains is not None else DOMAIN_IDS

    cells = tuple(
        _classify_cell(view, provider)
        for view in views
        for provider in provider_axes
    )
    return LogicCapabilityMatrix(
        domains=domain_ids,
        formal_views=views,
        families=family_ids,
        providers=provider_axes,
        cells=cells,
        metadata={
            "objective_id": "LFP-004",
            "goal_id": "LFP-G010",
            "program_id": "ipfs-datasets-logic-family-parser-v1",
            "availability_policy": (
                "Matrix materialization never probes the environment. "
                "Availability is declaration posture only; live install state "
                "requires an explicit runtime probe outside this module."
            ),
            "authority_policy": (
                "Authority ceilings are maximums for the cell's support route. "
                "They never promote advisor/candidate/solver evidence to kernel "
                "or authorization authority."
            ),
            "support_policy": (
                "Support is the semantic disposition of the domain-view-family "
                "to provider edge and is independent of binary availability."
            ),
            "ui_ux_policy": (
                "ui_ux_ir cells are declaration-only with "
                "source_not_in_pinned_revision until LFP-038 and source import."
            ),
            "evidence_subset": [
                "z3",
                "cvc5",
                "tla_tlc",
                "apalache",
                "datalog_secpal",
                "proverif",
                "tamarin",
                "hyperltl_autohyper_mchyper",
                "vampire",
                "eprover",
                "hammer",
                "lean",
                "rocq",
                "isabelle",
                "runtime_mtl",
                "ergoai",
                "symbolicai",
            ],
        },
        notes=(
            "Baseline materialization from plan domain mapping and static "
            "provider/family registries. Unknown and unimplemented cells are "
            "retained for later refill."
        ),
    )


def build_default_matrix() -> LogicCapabilityMatrix:
    """Build the sealed LFP-004 capability matrix baseline."""

    return materialize_capability_matrix()


DEFAULT_MATRIX: Final = build_default_matrix()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: write the compact capability-matrix seal to the baseline path."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Materialize LogicCapabilityMatrix@1 baseline seal"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output path (default: sealed baseline under docs/architecture/...)",
    )
    parser.add_argument(
        "--full-cells",
        action="store_true",
        help="Write the full cell expansion instead of the compact seal",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    matrix = build_default_matrix()
    target = Path(args.output) if args.output else default_baseline_path()
    write_matrix_baseline(matrix, target, full_cells=bool(args.full_cells))
    print(f"wrote {target} cells={len(matrix.cells)} digest={matrix.content_digest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuthorityCeiling",
    "AvailabilityStatus",
    "CANONICAL_FAMILIES",
    "CELL_SCHEMA",
    "CapabilityCell",
    "CapabilityMatrixError",
    "DEFAULT_BASELINE_RELATIVE_PATH",
    "DEFAULT_MATRIX",
    "DOMAIN_IDS",
    "EVIDENCE_SCHEMA",
    "FORMAL_VIEW_AXES",
    "FormalViewAxis",
    "INTERFACE",
    "LogicCapabilityMatrix",
    "MATRIX_VERSION",
    "PROVIDER_AXES",
    "ProviderAxis",
    "REFILL_SUPPORT_STATUSES",
    "SCHEMA_VERSION",
    "SourceEvidence",
    "SupportStatus",
    "build_default_matrix",
    "cell_id",
    "default_baseline_path",
    "MATERIALIZATION_TARGET",
    "ensure_baseline_seal",
    "load_matrix_baseline",
    "main",
    "materialize_capability_matrix",
    "render_matrix_json",
    "render_matrix_seal_json",
    "to_matrix_seal_dict",
    "write_matrix_baseline",
]
