"""Domain-view-family-provider cross-product conformance runner (LFP-040).

Interface: ``LogicConformanceRunner@1``.

The runner joins:

* the sealed capability matrix (domain × view × family/profile × provider);
* the final generated provider/translation catalog; and
* the inert parser catalog;

into one hermetic suite.  Every cell receives a typed disposition:

``native``, ``lossless``, ``approximate``, ``bounded``, ``declaration_only``,
``advisor_only``, ``unavailable``, or ``unsupported`` (always with a reason).

Hermetic policy:

* No network, installer, subprocess, or model side effects.
* Missing external tools produce typed ``unavailable`` evidence — never a
  silent pass and never an unexplained skip.
* Unexplained registry/matrix gaps fail closed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    DOMAIN_IDS,
    AuthorityCeiling,
    AvailabilityStatus,
    CapabilityCell,
    LogicCapabilityMatrix,
    SupportStatus,
    build_default_matrix,
)
from ipfs_datasets_py.logic.families.generated_catalog import (
    DEFAULT_GENERATED_CATALOG,
    GeneratedProviderTranslationCatalog,
    build_generated_provider_translation_catalog,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_PROVIDER_IDS,
    BASELINE_PROVIDER_IDS,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY, LogicFamilyRegistry
from ipfs_datasets_py.logic.parsers.catalog import (
    DEFAULT_PARSER_CATALOG,
    LogicParserCatalog,
    build_parser_catalog,
)


LOGIC_CONFORMANCE_RUNNER_INTERFACE: Final = "LogicConformanceRunner@1"
LOGIC_CONFORMANCE_RECEIPT_INTERFACE: Final = "LogicConformanceReceipt@1"
RUNNER_SCHEMA_VERSION: Final = "logic-conformance-runner/v1"
RECEIPT_SCHEMA_VERSION: Final = "logic-conformance-receipt/v1"
CELL_EVIDENCE_SCHEMA: Final = "logic-conformance-cell-evidence/v1"
UNAVAILABLE_EVIDENCE_SCHEMA: Final = "logic-conformance-unavailable-evidence/v1"
RUNNER_VERSION: Final = "1.0.0"
RUNNER_TASK_ID: Final = "LFP-040"
RUNNER_GOAL_ID: Final = "LFP-G080"

# Exact provider IDs required by acceptance (matrix + advisory).
REQUIRED_PROVIDER_IDS: Final[tuple[str, ...]] = tuple(
    sorted(set(EXECUTABLE_PROVIDER_IDS) | set(ADVISORY_PROVIDER_IDS) | set(BASELINE_PROVIDER_IDS))
)

REQUIRED_DOMAIN_IDS: Final[tuple[str, ...]] = DOMAIN_IDS


class ConformanceRunnerError(ValueError):
    """Raised when the conformance runner configuration is invalid."""


class ConformanceGapError(ConformanceRunnerError):
    """Raised when an unexplained registry or matrix gap is detected."""


class FalseSkipError(ConformanceRunnerError):
    """Raised when a cell would be skipped without typed unavailable evidence."""


class CellDisposition(StrEnum):
    """Semantic disposition of one domain-view-family-provider cell."""

    NATIVE = "native"
    LOSSLESS = "lossless"
    APPROXIMATE = "approximate"
    BOUNDED = "bounded"
    DECLARATION_ONLY = "declaration_only"
    ADVISOR_ONLY = "advisor_only"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class CellExecutionStatus(StrEnum):
    """How the hermetic runner treated one cell."""

    EXECUTED = "executed"
    UNAVAILABLE = "unavailable"
    # Explicitly forbidden as a terminal outcome without evidence.
    SKIPPED = "skipped"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConformanceRunnerError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ConformanceRunnerError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ConformanceRunnerError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ConformanceRunnerError(
            f"{field_name} must be one of {choices}"
        ) from error


def map_support_to_disposition(
    support: SupportStatus | str,
    *,
    translation_lossless: bool = False,
) -> CellDisposition:
    """Map matrix support onto the LFP-040 cross-product disposition vocabulary."""

    status = support if isinstance(support, SupportStatus) else SupportStatus(str(support))
    if status is SupportStatus.NATIVE:
        return CellDisposition.NATIVE
    if status is SupportStatus.TRANSLATED:
        return (
            CellDisposition.LOSSLESS
            if translation_lossless
            else CellDisposition.APPROXIMATE
        )
    if status is SupportStatus.APPROXIMATE:
        return CellDisposition.APPROXIMATE
    if status is SupportStatus.BOUNDED:
        return CellDisposition.BOUNDED
    if status is SupportStatus.DECLARATION_ONLY:
        return CellDisposition.DECLARATION_ONLY
    if status is SupportStatus.ADVISORY:
        return CellDisposition.ADVISOR_ONLY
    if status is SupportStatus.UNSUPPORTED:
        return CellDisposition.UNSUPPORTED
    if status is SupportStatus.UNKNOWN:
        # Unknown without a reviewed reason becomes unsupported at the runner
        # boundary only when a reason is supplied by the caller; the mapper
        # itself keeps a conservative unsupported default for fail-closed joins.
        return CellDisposition.UNSUPPORTED
    raise ConformanceRunnerError(f"unmapped support status {status!r}")


@dataclass(frozen=True, slots=True)
class UnavailableEvidence:
    """Typed evidence that a cell could not execute hermetically."""

    provider_id: str
    reason: str
    cell_id: str = ""
    capability_gap: str = "provider_or_toolchain_unavailable"
    schema_version: str = UNAVAILABLE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self, "cell_id", _text(self.cell_id, "cell_id") if self.cell_id else ""
        )
        object.__setattr__(
            self,
            "capability_gap",
            _identifier(self.capability_gap, "capability_gap"),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_gap": self.capability_gap,
            "cell_id": self.cell_id,
            "provider_id": self.provider_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnavailableEvidence":
        if not isinstance(value, Mapping):
            raise ConformanceRunnerError("unavailable evidence must be a mapping")
        return cls(
            provider_id=str(value.get("provider_id") or ""),
            reason=str(value.get("reason") or ""),
            cell_id=str(value.get("cell_id") or ""),
            capability_gap=str(
                value.get("capability_gap") or "provider_or_toolchain_unavailable"
            ),
            schema_version=str(
                value.get("schema_version") or UNAVAILABLE_EVIDENCE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class ConformanceCellEvidence:
    """Typed hermetic result for one matrix cell."""

    cell_id: str
    domain_id: str
    formal_view_id: str
    family_id: str
    profile_id: str
    provider_id: str
    disposition: CellDisposition
    execution_status: CellExecutionStatus
    reason: str
    support: SupportStatus
    availability: AvailabilityStatus
    authority_ceiling: AuthorityCeiling
    unavailable: UnavailableEvidence | None = None
    translation_ids: tuple[str, ...] = ()
    hermetic: bool = True
    schema_version: str = CELL_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        object.__setattr__(self, "domain_id", _identifier(self.domain_id, "domain_id"))
        object.__setattr__(
            self, "formal_view_id", _identifier(self.formal_view_id, "formal_view_id")
        )
        object.__setattr__(self, "family_id", _identifier(self.family_id, "family_id"))
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id or "default", "profile_id")
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, CellDisposition, "disposition"),
        )
        object.__setattr__(
            self,
            "execution_status",
            _enum(self.execution_status, CellExecutionStatus, "execution_status"),
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
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
        if self.unavailable is not None and not isinstance(
            self.unavailable, UnavailableEvidence
        ):
            if isinstance(self.unavailable, Mapping):
                object.__setattr__(
                    self,
                    "unavailable",
                    UnavailableEvidence.from_dict(self.unavailable),
                )
            else:
                raise ConformanceRunnerError(
                    "unavailable must be UnavailableEvidence or None"
                )
        object.__setattr__(
            self,
            "translation_ids",
            tuple(
                _identifier(item, "translation_ids item")
                for item in self.translation_ids
            ),
        )
        if not isinstance(self.hermetic, bool):
            raise ConformanceRunnerError("hermetic must be a boolean")
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

        # Fail closed: skipped without typed unavailable evidence is forbidden.
        if self.execution_status is CellExecutionStatus.SKIPPED:
            raise FalseSkipError(
                f"cell {self.cell_id!r} cannot terminate as skipped; emit typed "
                "unavailable evidence instead"
            )
        if self.execution_status is CellExecutionStatus.UNAVAILABLE:
            if self.unavailable is None:
                raise FalseSkipError(
                    f"cell {self.cell_id!r} is unavailable without typed evidence"
                )
            if self.disposition is not CellDisposition.UNAVAILABLE:
                raise ConformanceRunnerError(
                    f"cell {self.cell_id!r} unavailable status requires "
                    "unavailable disposition"
                )
        if self.disposition is CellDisposition.UNAVAILABLE and self.unavailable is None:
            raise FalseSkipError(
                f"cell {self.cell_id!r} unavailable disposition requires evidence"
            )
        if not self.reason:
            raise ConformanceRunnerError(
                f"cell {self.cell_id!r} must carry a non-empty reason"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "authority_ceiling": self.authority_ceiling.value,
            "availability": self.availability.value,
            "cell_id": self.cell_id,
            "disposition": self.disposition.value,
            "domain_id": self.domain_id,
            "execution_status": self.execution_status.value,
            "family_id": self.family_id,
            "formal_view_id": self.formal_view_id,
            "hermetic": self.hermetic,
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "support": self.support.value,
            "translation_ids": list(self.translation_ids),
        }
        if self.unavailable is not None:
            payload["unavailable"] = self.unavailable.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConformanceCellEvidence":
        if not isinstance(value, Mapping):
            raise ConformanceRunnerError("cell evidence must be a mapping")
        return cls(
            cell_id=str(value.get("cell_id") or ""),
            domain_id=str(value.get("domain_id") or ""),
            formal_view_id=str(value.get("formal_view_id") or ""),
            family_id=str(value.get("family_id") or ""),
            profile_id=str(value.get("profile_id") or "default"),
            provider_id=str(value.get("provider_id") or ""),
            disposition=str(value.get("disposition") or CellDisposition.UNSUPPORTED.value),
            execution_status=str(
                value.get("execution_status") or CellExecutionStatus.EXECUTED.value
            ),
            reason=str(value.get("reason") or ""),
            support=str(value.get("support") or SupportStatus.UNKNOWN.value),
            availability=str(
                value.get("availability") or AvailabilityStatus.UNKNOWN.value
            ),
            authority_ceiling=str(
                value.get("authority_ceiling") or AuthorityCeiling.UNKNOWN.value
            ),
            unavailable=value.get("unavailable"),
            translation_ids=tuple(value.get("translation_ids") or ()),
            hermetic=bool(value.get("hermetic", True)),
            schema_version=str(value.get("schema_version") or CELL_EVIDENCE_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class LogicConformanceReceipt:
    """Receipt for one hermetic cross-product suite run.

    Interface: ``LogicConformanceReceipt@1``.
    """

    INTERFACE: ClassVar[str] = LOGIC_CONFORMANCE_RECEIPT_INTERFACE

    cells: tuple[ConformanceCellEvidence, ...]
    domain_ids: tuple[str, ...]
    provider_ids: tuple[str, ...]
    schema_version: str = RECEIPT_SCHEMA_VERSION
    version: str = RUNNER_VERSION
    task_id: str = RUNNER_TASK_ID
    goal_id: str = RUNNER_GOAL_ID
    hermetic: bool = True
    false_skips: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.cells, (str, bytes, bytearray)) or not isinstance(
            self.cells, Sequence
        ):
            raise ConformanceRunnerError("cells must be a sequence")
        cells = tuple(
            item
            if isinstance(item, ConformanceCellEvidence)
            else ConformanceCellEvidence.from_dict(item)
            for item in self.cells
        )
        cell_ids = [item.cell_id for item in cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ConformanceRunnerError("receipt cells must have unique cell_id values")
        object.__setattr__(
            self, "cells", tuple(sorted(cells, key=lambda item: item.cell_id))
        )
        object.__setattr__(
            self,
            "domain_ids",
            tuple(sorted({_identifier(item, "domain_ids item") for item in self.domain_ids})),
        )
        object.__setattr__(
            self,
            "provider_ids",
            tuple(
                sorted(
                    {_identifier(item, "provider_ids item") for item in self.provider_ids}
                )
            ),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        if not isinstance(self.hermetic, bool):
            raise ConformanceRunnerError("hermetic must be a boolean")
        if not isinstance(self.false_skips, int) or self.false_skips < 0:
            raise ConformanceRunnerError("false_skips must be a non-negative integer")
        if self.false_skips != 0:
            raise FalseSkipError("conformance receipt cannot include false skips")
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    def disposition_histogram(self) -> Mapping[str, int]:
        counts: dict[str, int] = {item.value: 0 for item in CellDisposition}
        for cell in self.cells:
            counts[cell.disposition.value] += 1
        return MappingProxyType(counts)

    def unavailable_cells(self) -> tuple[ConformanceCellEvidence, ...]:
        return tuple(
            item
            for item in self.cells
            if item.disposition is CellDisposition.UNAVAILABLE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_count": self.cell_count,
            "cells": [item.to_dict() for item in self.cells],
            "disposition_histogram": dict(self.disposition_histogram()),
            "domain_ids": list(self.domain_ids),
            "false_skips": self.false_skips,
            "goal_id": self.goal_id,
            "hermetic": self.hermetic,
            "interface": self.INTERFACE,
            "notes": self.notes,
            "provider_ids": list(self.provider_ids),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "unavailable_count": len(self.unavailable_cells()),
            "version": self.version,
        }


def _lossless_translation_ids(
    family_id: str,
    catalog: GeneratedProviderTranslationCatalog,
) -> tuple[str, ...]:
    return tuple(
        edge.translation_id
        for edge in catalog.translations
        if edge.source_family_id == family_id
        and edge.translation_kind.value == "lossless"
    )


def _classify_cell(
    cell: CapabilityCell,
    *,
    generated: GeneratedProviderTranslationCatalog,
    probe_available: Mapping[str, bool] | None,
) -> ConformanceCellEvidence:
    """Classify one matrix cell hermetically into typed evidence."""

    lossless_ids = _lossless_translation_ids(cell.family_id, generated)
    translation_lossless = bool(lossless_ids) and cell.support is SupportStatus.TRANSLATED

    # Source-missing / declaration-only UI cells stay declaration_only.
    if cell.availability is AvailabilityStatus.SOURCE_MISSING:
        disposition = CellDisposition.DECLARATION_ONLY
        execution = CellExecutionStatus.EXECUTED
        unavailable = None
        reason = cell.notes or (
            f"domain {cell.domain_id} is declaration-only with source missing"
        )
    elif cell.support is SupportStatus.UNKNOWN:
        # Unexplained unknown cells are gaps — surface as unsupported with an
        # explicit reason so refill can target them; never silent success.
        if not cell.notes:
            raise ConformanceGapError(
                f"matrix cell {cell.id!r} has unknown support without a reason"
            )
        disposition = CellDisposition.UNSUPPORTED
        execution = CellExecutionStatus.EXECUTED
        unavailable = None
        reason = cell.notes
    else:
        disposition = map_support_to_disposition(
            cell.support, translation_lossless=translation_lossless
        )
        execution = CellExecutionStatus.EXECUTED
        unavailable = None
        reason = cell.notes or (
            f"support={cell.support.value}; availability={cell.availability.value}"
        )

    # Optional hermetic availability probe map.  When a provider is explicitly
    # marked unavailable, emit typed unavailable evidence rather than skipping.
    if probe_available is not None and cell.provider_id in probe_available:
        if probe_available[cell.provider_id] is False:
            # Only upgrade executable-intended cells; declaration/unsupported
            # already carry terminal dispositions.
            if disposition in {
                CellDisposition.NATIVE,
                CellDisposition.LOSSLESS,
                CellDisposition.APPROXIMATE,
                CellDisposition.BOUNDED,
                CellDisposition.ADVISOR_ONLY,
            }:
                disposition = CellDisposition.UNAVAILABLE
                execution = CellExecutionStatus.UNAVAILABLE
                reason = (
                    f"provider {cell.provider_id} is unavailable in the hermetic "
                    "validation environment"
                )
                unavailable = UnavailableEvidence(
                    provider_id=cell.provider_id,
                    reason=reason,
                    cell_id=cell.id,
                    capability_gap="provider_unavailable_in_hermetic_environment",
                )

    return ConformanceCellEvidence(
        cell_id=cell.id,
        domain_id=cell.domain_id,
        formal_view_id=cell.formal_view_id,
        family_id=cell.family_id,
        profile_id=cell.profile_id,
        provider_id=cell.provider_id,
        disposition=disposition,
        execution_status=execution,
        reason=reason,
        support=cell.support,
        availability=cell.availability,
        authority_ceiling=cell.authority_ceiling,
        unavailable=unavailable,
        translation_ids=lossless_ids if translation_lossless else (),
        hermetic=True,
    )


@dataclass(frozen=True, slots=True)
class LogicConformanceRunner:
    """Hermetic domain-view-family-provider cross-product suite runner.

    Interface: ``LogicConformanceRunner@1``.
    """

    INTERFACE: ClassVar[str] = LOGIC_CONFORMANCE_RUNNER_INTERFACE

    matrix: LogicCapabilityMatrix = field(default_factory=build_default_matrix)
    generated_catalog: GeneratedProviderTranslationCatalog = field(
        default_factory=lambda: DEFAULT_GENERATED_CATALOG
    )
    parser_catalog: LogicParserCatalog = field(
        default_factory=lambda: DEFAULT_PARSER_CATALOG
    )
    registry: LogicFamilyRegistry = field(default_factory=lambda: DEFAULT_REGISTRY)
    schema_version: str = RUNNER_SCHEMA_VERSION
    version: str = RUNNER_VERSION
    task_id: str = RUNNER_TASK_ID
    goal_id: str = RUNNER_GOAL_ID
    # When None, the runner does not probe tools and treats declaration posture
    # as sufficient for hermetic classification.  Callers may inject an explicit
    # provider_id -> available map for validation-environment probes.
    provider_availability: Mapping[str, bool] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.matrix, LogicCapabilityMatrix):
            raise ConformanceRunnerError("matrix must be a LogicCapabilityMatrix")
        if not isinstance(self.generated_catalog, GeneratedProviderTranslationCatalog):
            raise ConformanceRunnerError(
                "generated_catalog must be a GeneratedProviderTranslationCatalog"
            )
        if not isinstance(self.parser_catalog, LogicParserCatalog):
            raise ConformanceRunnerError(
                "parser_catalog must be a LogicParserCatalog"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RUNNER_SCHEMA_VERSION:
            raise ConformanceRunnerError(
                f"unsupported runner schema: {self.schema_version!r}"
            )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        if self.provider_availability is not None:
            if not isinstance(self.provider_availability, Mapping):
                raise ConformanceRunnerError(
                    "provider_availability must be a mapping or None"
                )
            object.__setattr__(
                self,
                "provider_availability",
                MappingProxyType(dict(self.provider_availability)),
            )

    def required_provider_ids(self) -> tuple[str, ...]:
        return REQUIRED_PROVIDER_IDS

    def required_domain_ids(self) -> tuple[str, ...]:
        return REQUIRED_DOMAIN_IDS

    def validate_axes(self) -> None:
        """Reject unexplained registry/matrix gaps on required axes."""

        matrix_domains = set(self.matrix.domains)
        required_domains = set(self.required_domain_ids())
        missing_domains = sorted(required_domains - matrix_domains)
        if missing_domains:
            raise ConformanceGapError(
                f"matrix missing required domains: {', '.join(missing_domains)}"
            )

        matrix_providers = set(self.matrix.provider_ids)
        required_providers = set(self.required_provider_ids())
        missing_providers = sorted(required_providers - matrix_providers)
        if missing_providers:
            raise ConformanceGapError(
                f"matrix missing required providers: {', '.join(missing_providers)}"
            )

        # Generated catalog and executable matrix must also close.
        self.generated_catalog.validate_closure(registry=self.registry)
        self.parser_catalog.validate_closure(registry=self.registry)

        # Every matrix cell must reference known axes.
        family_ids = set(self.matrix.families) | set(self.registry.families)
        for cell in self.matrix.cells:
            if cell.domain_id not in matrix_domains:
                raise ConformanceGapError(
                    f"cell {cell.id!r} references unknown domain {cell.domain_id!r}"
                )
            if cell.provider_id not in matrix_providers:
                raise ConformanceGapError(
                    f"cell {cell.id!r} references unknown provider {cell.provider_id!r}"
                )
            if cell.family_id not in family_ids:
                raise ConformanceGapError(
                    f"cell {cell.id!r} references unknown family {cell.family_id!r}"
                )
            if cell.support is SupportStatus.UNKNOWN and not cell.notes:
                raise ConformanceGapError(
                    f"unexplained unknown matrix cell {cell.id!r}"
                )

        # Executable matrix join.
        executable_ids = {entry.provider_id for entry in EXECUTABLE_PROVIDER_MATRIX}
        if not executable_ids.issubset(matrix_providers):
            raise ConformanceGapError(
                "matrix missing executable-matrix providers: "
                + ", ".join(sorted(executable_ids - matrix_providers))
            )

    def run(self, *, validate: bool = True) -> LogicConformanceReceipt:
        """Execute the hermetic cross-product suite and return a receipt."""

        if validate:
            self.validate_axes()

        evidence = tuple(
            _classify_cell(
                cell,
                generated=self.generated_catalog,
                probe_available=self.provider_availability,
            )
            for cell in self.matrix.cells
        )

        # No false skips: every matrix cell must produce evidence.
        if len(evidence) != len(self.matrix.cells):
            raise FalseSkipError(
                "runner produced fewer evidence rows than matrix cells"
            )
        skipped = [
            item for item in evidence if item.execution_status is CellExecutionStatus.SKIPPED
        ]
        if skipped:
            raise FalseSkipError(
                f"runner produced {len(skipped)} false skips"
            )

        return LogicConformanceReceipt(
            cells=evidence,
            domain_ids=tuple(self.matrix.domains),
            provider_ids=tuple(self.matrix.provider_ids),
            hermetic=True,
            false_skips=0,
            notes=(
                "Hermetic LFP-040 cross-product run. External tools are never "
                "probed unless provider_availability is injected; missing tools "
                "emit typed unavailable evidence rather than skips."
            ),
        )

    def iter_cells(self) -> Iterator[CapabilityCell]:
        return iter(self.matrix.cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "interface": self.INTERFACE,
            "matrix_cell_count": len(self.matrix.cells),
            "matrix_domains": list(self.matrix.domains),
            "matrix_providers": list(self.matrix.provider_ids),
            "parser_descriptor_ids": list(self.parser_catalog.descriptor_ids),
            "provider_availability": (
                dict(self.provider_availability)
                if self.provider_availability is not None
                else None
            ),
            "required_domain_ids": list(self.required_domain_ids()),
            "required_provider_ids": list(self.required_provider_ids()),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "version": self.version,
        }


def build_conformance_runner(
    *,
    matrix: LogicCapabilityMatrix | None = None,
    generated_catalog: GeneratedProviderTranslationCatalog | None = None,
    parser_catalog: LogicParserCatalog | None = None,
    registry: LogicFamilyRegistry | None = None,
    provider_availability: Mapping[str, bool] | None = None,
    validate: bool = True,
) -> LogicConformanceRunner:
    """Construct a hermetic LFP-040 conformance runner."""

    runner = LogicConformanceRunner(
        matrix=matrix if matrix is not None else build_default_matrix(),
        generated_catalog=(
            generated_catalog
            if generated_catalog is not None
            else build_generated_provider_translation_catalog(validate=True)
        ),
        parser_catalog=(
            parser_catalog
            if parser_catalog is not None
            else build_parser_catalog(validate=True)
        ),
        registry=registry if registry is not None else DEFAULT_REGISTRY,
        provider_availability=provider_availability,
    )
    if validate:
        runner.validate_axes()
    return runner


def run_domain_provider_matrix(
    *,
    provider_availability: Mapping[str, bool] | None = None,
    validate: bool = True,
) -> LogicConformanceReceipt:
    """Convenience entrypoint for the domain-provider cross-product suite."""

    runner = build_conformance_runner(
        provider_availability=provider_availability,
        validate=validate,
    )
    return runner.run(validate=validate)


DEFAULT_CONFORMANCE_RUNNER: Final[LogicConformanceRunner] = build_conformance_runner(
    validate=True
)


__all__ = [
    "CELL_EVIDENCE_SCHEMA",
    "DEFAULT_CONFORMANCE_RUNNER",
    "CellDisposition",
    "CellExecutionStatus",
    "ConformanceCellEvidence",
    "ConformanceGapError",
    "ConformanceRunnerError",
    "FalseSkipError",
    "LOGIC_CONFORMANCE_RECEIPT_INTERFACE",
    "LOGIC_CONFORMANCE_RUNNER_INTERFACE",
    "LogicConformanceReceipt",
    "LogicConformanceRunner",
    "RECEIPT_SCHEMA_VERSION",
    "REQUIRED_DOMAIN_IDS",
    "REQUIRED_PROVIDER_IDS",
    "RUNNER_GOAL_ID",
    "RUNNER_SCHEMA_VERSION",
    "RUNNER_TASK_ID",
    "RUNNER_VERSION",
    "UNAVAILABLE_EVIDENCE_SCHEMA",
    "UnavailableEvidence",
    "build_conformance_runner",
    "map_support_to_disposition",
    "run_domain_provider_matrix",
]
