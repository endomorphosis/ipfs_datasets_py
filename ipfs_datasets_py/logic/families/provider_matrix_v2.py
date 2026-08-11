"""ProviderCapabilityMatrix@2 — evidence-specific capabilities from one source.

Generated from the sealed :data:`BASELINE_PROVIDER_CATALOG` (and its join with
the executable-matrix lane declarations).  The matrix never invents free-form
families and never promotes providers, notations/syntaxes, properties, or
execution lanes into the family namespace.

Interfaces (LFP2-009):

* ``ProviderCapabilityMatrix@2`` — sparse, evidence-specific capability cells
  keyed by provider × lane × family × feature × property × evidence

Guarantees (fail closed):

* one reviewed generation source (baseline provider catalog + matrix lanes)
* provider / syntax / property / lane labels cannot masquerade as families
* cells bind typed :class:`LogicIdentity` values for every role
* presence never claims tool availability or proof authority
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_MATRIX,
    EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
    ProviderMatrixEntry,
)
from ipfs_datasets_py.logic.families.models import (
    EvidenceAuthority,
    SupportLevel,
    _enum,
    _identifier,
    _text,
    _version,
)
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
    family_id,
    lane_id,
    provider_id,
)
from ipfs_datasets_py.logic.families.providers import (
    BASELINE_PROVIDER_CATALOG,
    CATALOG_INTERFACE,
    ProviderCapabilityCatalog,
    ProviderCapabilityEntry,
    ProviderCatalogSource,
)
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    NON_FAMILY_PROFILE_LABELS,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

MATRIX_V2_INTERFACE: Final = "ProviderCapabilityMatrix@2"
MATRIX_V2_SCHEMA_VERSION: Final = "provider-capability-matrix/v2"
MATRIX_V2_MODULE_VERSION: Final = "1.0.0"
CELL_SCHEMA_VERSION: Final = "provider-capability-matrix-cell/v2"
FEATURE_SCHEMA_VERSION: Final = "provider-capability-feature/v2"

GENERATION_SOURCE: Final = "baseline_provider_catalog"
GENERATION_TASK: Final = "LFP2-009"

# Map ExecutableProviderMatrix@1 "family" (lane role) -> canonical lane id.
_LEGACY_MATRIX_FAMILY_TO_LANE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "smt": "smt",
        "state_model": "state_model",
        "runtime": "runtime_monitor",
        "authorization": "advisor",  # policy/authorization portfolio lane
        "protocol": "atp",  # protocol tools share ATP-style execution posture
        "hyperproperty": "smt",  # HyperLTL tools run as SMT-bounded checks
        "atp": "atp",
        "hammer": "advisor",
        "kernel": "itp_kernel",
    }
)

# Labels that must never be admitted as family_id on a v2 cell.
_KNOWN_PROVIDER_SURFACE: Final[frozenset[str]] = frozenset(
    {
        "z3",
        "cvc5",
        "tla_tlc",
        "tlc",
        "apalache",
        "runtime_mtl",
        "datalog_secpal",
        "proverif",
        "tamarin",
        "hyperltl_autohyper_mchyper",
        "vampire",
        "eprover",
        "e",
        "hammer",
        "lean",
        "rocq",
        "coq",
        "coqc",
        "isabelle",
        "ergoai",
        "ergo_ai",
        "symbolicai",
        "symai",
        "autohyper",
        "mchyper",
        "datalog-authorization",
        "secpal-authorization",
    }
)

_KNOWN_NOTATION_SYNTAX_SURFACE: Final[frozenset[str]] = frozenset(
    {
        "smt",
        "smtlib2",
        "smt_lib",
        "smt_lib2",
        "tptp",
        "tptp_fof",
        "tla",
        "tla_plus_source",
        "spthy",
        "tamarin_spthy",
        "pv",
        "proverif_pv",
        "canonical_text",
    }
)

_KNOWN_PROPERTY_SURFACE: Final[frozenset[str]] = frozenset(
    {
        "safety",
        "liveness",
        "reachability",
        "noninterference",
        "satisfiability",
        "validity",
        "secrecy",
        "termination",
        "theorem",
        "invariant",
        "contract",
        "hyperproperty",
        "refinement",
    }
)

_KNOWN_LANE_SURFACE: Final[frozenset[str]] = frozenset(
    {
        "smt",
        "smt_lane",
        "state_model",
        "runtime",
        "runtime_monitor",
        "atp",
        "advisor",
        "kernel",
        "itp_kernel",
        "authorization",  # legacy matrix lane label
        "protocol",  # legacy matrix lane label
        "hyperproperty",  # legacy matrix lane label
        "hammer",  # legacy matrix lane label
    }
)

# Domain / portfolio labels from legacy matrix logic_families that are not
# semantic families (diagnosed on migration; never admitted as family_id).
_NON_FAMILY_DOMAIN_LABELS: Final[frozenset[str]] = frozenset(
    {
        "software_verification",
        "tla_plus",
        "secpal",
        "policy",
        "protocol",
        "protocol_logic",
        "proverif",
        "tamarin",
        "hyperltl",
        "fol",
        "lean",
        "lean4",
        "rocq",
        "coq",
        "isabelle",
        "hol",
        "dependent_type_theory",
        "noninterference",
        "runtime",
        "state_transition",  # alias for transition_system, not a family id write
    }
)


class ProviderMatrixV2Error(ValueError):
    """Raised when ProviderCapabilityMatrix@2 is malformed."""


class FamilyMasqueradeError(ProviderMatrixV2Error):
    """Raised when a non-family role is offered as a family identity."""


class ProviderMatrixDriftError(ProviderMatrixV2Error):
    """Raised when generation drifts from the reviewed source catalog."""


class ProviderMatrixAuthorityError(ProviderMatrixV2Error):
    """Raised when a cell overclaims its authority ceiling."""


class CapabilityLifecycle(str, Enum):
    """Lifecycle posture for one capability cell (declaration only)."""

    DECLARED = "declared"
    COMPILABLE = "compilable"
    EXECUTABLE = "executable"
    REPLAYABLE = "replayable"
    ADVISORY = "advisory"
    DECLARATION_ONLY = "declaration_only"


_AUTHORITY_RANK: Final[dict[EvidenceAuthority, int]] = {
    EvidenceAuthority.AUTHORITATIVE: 4,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.NONE: 0,
}


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderMatrixV2Error(f"{field_name} must be a boolean")
    return value


def _identity_dict(identity: LogicIdentity) -> dict[str, str]:
    return identity.to_dict()


def _coerce_family_identity(
    value: object,
    field_name: str = "family",
) -> LogicIdentity:
    """Admit a family identity and reject role masquerades."""

    if isinstance(value, LogicIdentity):
        if value.namespace is not NamespaceKind.FAMILY:
            raise FamilyMasqueradeError(
                f"{field_name} requires family namespace; got {value.qualified}"
            )
        family_value = value.value
        identity = value
    elif isinstance(value, str):
        family_value = _identifier(value, field_name)
        identity = family_id(family_value)
    elif isinstance(value, Mapping):
        identity = LogicIdentity.from_dict(value)
        if identity.namespace is not NamespaceKind.FAMILY:
            raise FamilyMasqueradeError(
                f"{field_name} requires family namespace; got {identity.qualified}"
            )
        family_value = identity.value
    else:
        raise ProviderMatrixV2Error(
            f"{field_name} must be a family LogicIdentity or string"
        )

    reject_family_masquerade(family_value, field_name=field_name)
    if family_value not in BASELINE_FAMILY_IDS:
        raise ProviderMatrixDriftError(
            f"{field_name} {family_value!r} is outside the baseline family catalog"
        )
    return identity


def reject_family_masquerade(label: str, *, field_name: str = "family") -> None:
    """Fail closed when *label* is a provider, syntax, property, or lane surface.

    Canonical baseline family ids that legitimately share a surface form with a
    property or domain word (e.g. ``hyperproperty``, ``refinement``) are
    admitted only when they appear in :data:`BASELINE_FAMILY_IDS`.
    """

    text = _identifier(label, field_name)

    if text in NON_FAMILY_PROFILE_LABELS:
        raise FamilyMasqueradeError(
            f"{field_name} {text!r} is a non-family profile/alias label and "
            "cannot masquerade as a semantic family"
        )

    # Baseline family ids win over overlapping property/domain surface forms.
    if text in BASELINE_FAMILY_IDS:
        return

    if text in _KNOWN_PROVIDER_SURFACE:
        raise FamilyMasqueradeError(
            f"{field_name} {text!r} is a provider name and cannot masquerade "
            "as a semantic family"
        )
    if text in _KNOWN_NOTATION_SYNTAX_SURFACE:
        raise FamilyMasqueradeError(
            f"{field_name} {text!r} is a notation/syntax label and cannot "
            "masquerade as a semantic family"
        )
    if text in _KNOWN_PROPERTY_SURFACE:
        raise FamilyMasqueradeError(
            f"{field_name} {text!r} is a property/obligation label and cannot "
            "masquerade as a semantic family"
        )
    if text in _KNOWN_LANE_SURFACE:
        raise FamilyMasqueradeError(
            f"{field_name} {text!r} is an execution-lane label and cannot "
            "masquerade as a semantic family"
        )
    if text in _NON_FAMILY_DOMAIN_LABELS:
        raise FamilyMasqueradeError(
            f"{field_name} {text!r} is a non-family domain/portfolio label and "
            "cannot masquerade as a semantic family"
        )


def resolve_lane_for_matrix_family(matrix_family: str) -> LogicIdentity:
    """Map a legacy executable-matrix lane label to a canonical lane identity."""

    text = _text(matrix_family, "matrix_family").strip()
    canonical = _LEGACY_MATRIX_FAMILY_TO_LANE.get(text)
    if canonical is None:
        raise ProviderMatrixDriftError(
            f"unknown executable-matrix lane label {text!r}; cannot map to "
            "NamespaceKind.LANE"
        )
    return lane_id(canonical)


def _lifecycle_for_entry(
    entry: ProviderCapabilityEntry,
    support_level: SupportLevel,
) -> CapabilityLifecycle:
    if entry.advisory or support_level is SupportLevel.UNSUPPORTED:
        if support_level is SupportLevel.DECLARATION_ONLY:
            return CapabilityLifecycle.DECLARATION_ONLY
        return CapabilityLifecycle.ADVISORY
    if support_level is SupportLevel.DECLARATION_ONLY:
        return CapabilityLifecycle.DECLARATION_ONLY
    if entry.in_executable_matrix:
        return CapabilityLifecycle.EXECUTABLE
    return CapabilityLifecycle.DECLARED


def _authority_at_most(
    claimed: EvidenceAuthority,
    ceiling: EvidenceAuthority,
) -> bool:
    return _AUTHORITY_RANK[claimed] <= _AUTHORITY_RANK[ceiling]


# ---------------------------------------------------------------------------
# Cells and matrix
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderCapabilityFeatureV2:
    """One feature/fragment support edge under a capability cell."""

    feature_id: str
    support_level: SupportLevel = SupportLevel.NATIVE
    schema_version: str = FEATURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "feature_id", _identifier(self.feature_id, "feature_id")
        )
        object.__setattr__(
            self,
            "support_level",
            _enum(self.support_level, SupportLevel, "support_level"),
        )
        if self.schema_version != FEATURE_SCHEMA_VERSION:
            raise ProviderMatrixV2Error(
                f"unsupported feature schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "schema_version": self.schema_version,
            "support_level": self.support_level.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCapabilityFeatureV2":
        if not isinstance(value, Mapping):
            raise ProviderMatrixV2Error("feature payload must be a mapping")
        return cls(
            feature_id=value["feature_id"],
            support_level=value.get("support_level", SupportLevel.NATIVE.value),
            schema_version=value.get("schema_version", FEATURE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ProviderCapabilityCellV2:
    """One evidence-specific capability edge in ProviderCapabilityMatrix@2.

    Every identity role is explicit.  ``family`` is always a semantic family;
    providers, lanes, notations, and properties live in their own fields.
    """

    cell_id: str
    provider: LogicIdentity
    lane: LogicIdentity
    family: LogicIdentity
    evidence_kind: str
    authority_ceiling: EvidenceAuthority
    support_level: SupportLevel
    property_ids: tuple[str, ...] = ()
    features: tuple[ProviderCapabilityFeatureV2, ...] = ()
    operation_ids: tuple[str, ...] = ()
    boundedness_ids: tuple[str, ...] = ()
    lifecycle: CapabilityLifecycle = CapabilityLifecycle.DECLARED
    in_executable_matrix: bool = False
    advisory: bool = False
    notes: str = ""
    source_provider_version: str = ""
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    schema_version: str = CELL_SCHEMA_VERSION

    interface: ClassVar[str] = MATRIX_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))

        if not isinstance(self.provider, LogicIdentity):
            raise ProviderMatrixV2Error("provider must be a LogicIdentity")
        if self.provider.namespace is not NamespaceKind.PROVIDER:
            raise FamilyMasqueradeError(
                f"provider field must use provider namespace; got "
                f"{self.provider.qualified}"
            )
        if not isinstance(self.lane, LogicIdentity):
            raise ProviderMatrixV2Error("lane must be a LogicIdentity")
        if self.lane.namespace is not NamespaceKind.LANE:
            raise FamilyMasqueradeError(
                f"lane field must use lane namespace; got {self.lane.qualified}"
            )
        if not isinstance(self.family, LogicIdentity):
            raise ProviderMatrixV2Error("family must be a LogicIdentity")
        if self.family.namespace is not NamespaceKind.FAMILY:
            raise FamilyMasqueradeError(
                f"family field must use family namespace; got {self.family.qualified}"
            )
        reject_family_masquerade(self.family.value, field_name="family")

        object.__setattr__(
            self, "evidence_kind", _identifier(self.evidence_kind, "evidence_kind")
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling"),
        )
        object.__setattr__(
            self,
            "support_level",
            _enum(self.support_level, SupportLevel, "support_level"),
        )
        object.__setattr__(
            self,
            "lifecycle",
            _enum(self.lifecycle, CapabilityLifecycle, "lifecycle"),
        )
        object.__setattr__(
            self, "in_executable_matrix", _bool(self.in_executable_matrix, "in_executable_matrix")
        )
        object.__setattr__(self, "advisory", _bool(self.advisory, "advisory"))
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if self.source_provider_version:
            object.__setattr__(
                self,
                "source_provider_version",
                _version(self.source_provider_version, "source_provider_version"),
            )
        else:
            object.__setattr__(self, "source_provider_version", "")

        props = tuple(
            _identifier(item, "property_ids item") for item in self.property_ids
        )
        if len(set(props)) != len(props):
            raise ProviderMatrixV2Error("property_ids must not contain duplicates")
        # Properties are never promoted into the family field.
        for prop in props:
            if prop == self.family.value and prop not in BASELINE_FAMILY_IDS:
                raise FamilyMasqueradeError(
                    f"property {prop!r} cannot masquerade as family"
                )
        object.__setattr__(self, "property_ids", tuple(sorted(props)))

        ops = tuple(
            _identifier(item, "operation_ids item") for item in self.operation_ids
        )
        if len(set(ops)) != len(ops):
            raise ProviderMatrixV2Error("operation_ids must not contain duplicates")
        object.__setattr__(self, "operation_ids", tuple(sorted(ops)))

        bounds = tuple(
            _identifier(item, "boundedness_ids item") for item in self.boundedness_ids
        )
        if len(set(bounds)) != len(bounds):
            raise ProviderMatrixV2Error("boundedness_ids must not contain duplicates")
        object.__setattr__(self, "boundedness_ids", tuple(sorted(bounds)))

        features = tuple(
            item
            if isinstance(item, ProviderCapabilityFeatureV2)
            else ProviderCapabilityFeatureV2.from_dict(item)
            for item in self.features
        )
        features = tuple(sorted(features, key=lambda item: item.feature_id))
        feature_ids = tuple(item.feature_id for item in features)
        if len(set(feature_ids)) != len(feature_ids):
            raise ProviderMatrixV2Error("features must declare each feature at most once")
        object.__setattr__(self, "features", features)

        if self.schema_version != CELL_SCHEMA_VERSION:
            raise ProviderMatrixV2Error(
                f"unsupported cell schema_version {self.schema_version!r}"
            )

        if self.advisory and not _authority_at_most(
            self.authority_ceiling, EvidenceAuthority.ADVISORY
        ):
            raise ProviderMatrixAuthorityError(
                f"advisory cell {self.cell_id!r} cannot claim authority "
                f"{self.authority_ceiling.value!r}"
            )

        raw_metadata: object = self.metadata
        if isinstance(raw_metadata, Mapping):
            raw_metadata = tuple(raw_metadata.items())
        if (
            isinstance(raw_metadata, (str, bytes, bytearray))
            or not isinstance(raw_metadata, Sequence)
        ):
            raise ProviderMatrixV2Error("metadata must be a mapping or key/value sequence")
        meta: list[tuple[str, str]] = []
        for item in raw_metadata:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise ProviderMatrixV2Error("metadata entries must be key/value pairs")
            key = _identifier(item[0], "metadata key")
            meta.append((key, _text(item[1], f"metadata[{key}]")))
        if len({key for key, _ in meta}) != len(meta):
            raise ProviderMatrixV2Error("metadata must not contain duplicate keys")
        object.__setattr__(self, "metadata", tuple(sorted(meta)))

    @property
    def provider_id(self) -> str:
        return self.provider.value

    @property
    def family_id(self) -> str:
        return self.family.value

    @property
    def lane_id(self) -> str:
        return self.lane.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisory": self.advisory,
            "authority_ceiling": self.authority_ceiling.value,
            "boundedness_ids": list(self.boundedness_ids),
            "cell_id": self.cell_id,
            "evidence_kind": self.evidence_kind,
            "family": _identity_dict(self.family),
            "features": [item.to_dict() for item in self.features],
            "in_executable_matrix": self.in_executable_matrix,
            "interface": self.interface,
            "lane": _identity_dict(self.lane),
            "lifecycle": self.lifecycle.value,
            "metadata": {key: value for key, value in self.metadata},
            "notes": self.notes,
            "operation_ids": list(self.operation_ids),
            "property_ids": list(self.property_ids),
            "provider": _identity_dict(self.provider),
            "schema_version": self.schema_version,
            "source_provider_version": self.source_provider_version,
            "support_level": self.support_level.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCapabilityCellV2":
        if not isinstance(value, Mapping):
            raise ProviderMatrixV2Error("cell payload must be a mapping")
        schema = value.get("schema_version")
        if schema is not None and schema != CELL_SCHEMA_VERSION:
            raise ProviderMatrixV2Error(
                f"unsupported cell schema_version: {schema!r}"
            )
        return cls(
            cell_id=value["cell_id"],
            provider=LogicIdentity.from_dict(value["provider"])
            if isinstance(value.get("provider"), Mapping)
            else provider_id(str(value["provider"])),
            lane=LogicIdentity.from_dict(value["lane"])
            if isinstance(value.get("lane"), Mapping)
            else lane_id(str(value["lane"])),
            family=_coerce_family_identity(value["family"]),
            evidence_kind=value["evidence_kind"],
            authority_ceiling=value["authority_ceiling"],
            support_level=value["support_level"],
            property_ids=tuple(value.get("property_ids", ())),
            features=tuple(value.get("features", ())),
            operation_ids=tuple(value.get("operation_ids", ())),
            boundedness_ids=tuple(value.get("boundedness_ids", ())),
            lifecycle=value.get("lifecycle", CapabilityLifecycle.DECLARED.value),
            in_executable_matrix=bool(value.get("in_executable_matrix", False)),
            advisory=bool(value.get("advisory", False)),
            notes=value.get("notes", "") or "",
            source_provider_version=value.get("source_provider_version", "") or "",
            metadata=value.get("metadata", {}),
            schema_version=value.get("schema_version", CELL_SCHEMA_VERSION),
        )


def _cell_id(
    provider: str,
    lane: str,
    family: str,
    evidence: str,
) -> str:
    # Single separators only — taxonomy identifiers reject doubled punctuation.
    return f"{provider}.{lane}.{family}.{evidence}"


def _cells_from_entry(
    entry: ProviderCapabilityEntry,
    *,
    lane: LogicIdentity,
) -> list[ProviderCapabilityCellV2]:
    """Project one catalog entry into evidence-specific matrix cells."""

    cells: list[ProviderCapabilityCellV2] = []
    provider = provider_id(entry.provider_id)
    evidence_kinds = entry.evidence_ids or ("declaration",)
    for support in entry.family_support:
        family = _coerce_family_identity(support.family_id)
        features = tuple(
            ProviderCapabilityFeatureV2(
                feature_id=fragment,
                support_level=support.support_level,
            )
            for fragment in support.fragment_ids
        )
        lifecycle = _lifecycle_for_entry(entry, support.support_level)
        for evidence in evidence_kinds:
            cell = ProviderCapabilityCellV2(
                cell_id=_cell_id(
                    entry.provider_id, lane.value, support.family_id, evidence
                ),
                provider=provider,
                lane=lane,
                family=family,
                evidence_kind=evidence,
                authority_ceiling=entry.authority_ceiling,
                support_level=support.support_level,
                property_ids=support.property_ids,
                features=features,
                operation_ids=support.operation_ids,
                boundedness_ids=entry.boundedness_ids,
                lifecycle=lifecycle,
                in_executable_matrix=entry.in_executable_matrix,
                advisory=entry.advisory,
                notes=support.notes or entry.notes,
                source_provider_version=entry.provider_version,
                metadata={
                    "catalog_source": entry.catalog_source.value,
                    "generation_source": GENERATION_SOURCE,
                    "generation_task": GENERATION_TASK,
                },
            )
            cells.append(cell)
    return cells


def _lane_for_provider(
    provider_id_value: str,
    matrix_by_provider: Mapping[str, ProviderMatrixEntry],
) -> LogicIdentity:
    entry = matrix_by_provider.get(provider_id_value)
    if entry is not None:
        return resolve_lane_for_matrix_family(entry.family)
    # Advisory providers outside the executable matrix.
    if provider_id_value in {"ergoai", "symbolicai", "hammer"}:
        return lane_id("advisor")
    return lane_id("smt")


class ProviderCapabilityMatrixV2:
    """``ProviderCapabilityMatrix@2`` generated from one reviewed source.

    Construction is pure data: no PATH probes, imports, installs, or processes.
    """

    interface: Final = MATRIX_V2_INTERFACE
    schema_version: Final = MATRIX_V2_SCHEMA_VERSION

    def __init__(
        self,
        cells: Iterable[ProviderCapabilityCellV2] = (),
        *,
        version: str = MATRIX_V2_MODULE_VERSION,
        generation_source: str = GENERATION_SOURCE,
        generation_task: str = GENERATION_TASK,
        catalog_interface: str = CATALOG_INTERFACE,
        executable_matrix_interface: str = EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
        frozen: bool = False,
    ) -> None:
        self.version = _version(version, "version")
        self.generation_source = _text(generation_source, "generation_source")
        self.generation_task = _text(generation_task, "generation_task")
        self.catalog_interface = _text(catalog_interface, "catalog_interface")
        self.executable_matrix_interface = _text(
            executable_matrix_interface, "executable_matrix_interface"
        )
        self._cells: dict[str, ProviderCapabilityCellV2] = {}
        self._frozen = False
        for cell in sorted(cells, key=lambda item: item.cell_id):
            self.register(cell)
        if frozen:
            self.freeze()

    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> "ProviderCapabilityMatrixV2":
        self._frozen = True
        return self

    def _require_mutable(self) -> None:
        if self._frozen:
            raise ProviderMatrixV2Error("provider capability matrix is frozen")

    def register(self, cell: ProviderCapabilityCellV2) -> ProviderCapabilityCellV2:
        self._require_mutable()
        if not isinstance(cell, ProviderCapabilityCellV2):
            raise TypeError("cell must be a ProviderCapabilityCellV2")
        if cell.cell_id in self._cells:
            raise ProviderMatrixDriftError(
                f"duplicate capability cell {cell.cell_id!r}"
            )
        self._cells[cell.cell_id] = cell
        return cell

    def get(self, cell_id: str) -> ProviderCapabilityCellV2:
        try:
            return self._cells[cell_id]
        except KeyError as error:
            raise ProviderMatrixV2Error(f"unknown cell {cell_id!r}") from error

    @property
    def cells(self) -> Mapping[str, ProviderCapabilityCellV2]:
        return MappingProxyType(
            {key: self._cells[key] for key in sorted(self._cells)}
        )

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._cells))

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted({cell.provider_id for cell in self._cells.values()}))

    @property
    def family_ids(self) -> tuple[str, ...]:
        return tuple(sorted({cell.family_id for cell in self._cells.values()}))

    @property
    def lane_ids(self) -> tuple[str, ...]:
        return tuple(sorted({cell.lane_id for cell in self._cells.values()}))

    def cells_for_provider(self, provider: str) -> tuple[ProviderCapabilityCellV2, ...]:
        return tuple(
            self._cells[key]
            for key in sorted(self._cells)
            if self._cells[key].provider_id == provider
        )

    def cells_for_family(self, family: str) -> tuple[ProviderCapabilityCellV2, ...]:
        reject_family_masquerade(family, field_name="family")
        return tuple(
            self._cells[key]
            for key in sorted(self._cells)
            if self._cells[key].family_id == family
        )

    def is_available(self, provider: str) -> bool:
        """Catalog presence never means a tool is available."""

        if provider not in {cell.provider_id for cell in self._cells.values()}:
            raise ProviderMatrixV2Error(f"unknown provider {provider!r}")
        return False

    def claims_proof(self, provider: str) -> bool:
        """Catalog presence never constitutes a proof claim."""

        if provider not in {cell.provider_id for cell in self._cells.values()}:
            raise ProviderMatrixV2Error(f"unknown provider {provider!r}")
        return False

    def validate_no_masquerades(self) -> None:
        """Assert no cell promotes a non-family role into family_id."""

        for cell in self._cells.values():
            reject_family_masquerade(cell.family_id, field_name="family")
            if cell.provider.namespace is not NamespaceKind.PROVIDER:
                raise FamilyMasqueradeError(
                    f"cell {cell.cell_id!r} provider is not namespaced as provider"
                )
            if cell.lane.namespace is not NamespaceKind.LANE:
                raise FamilyMasqueradeError(
                    f"cell {cell.cell_id!r} lane is not namespaced as lane"
                )
            if cell.family.namespace is not NamespaceKind.FAMILY:
                raise FamilyMasqueradeError(
                    f"cell {cell.cell_id!r} family is not namespaced as family"
                )
            # Provider / lane surface forms must not collapse onto family.
            if cell.provider.value == cell.family.value:
                raise FamilyMasqueradeError(
                    f"cell {cell.cell_id!r} collapses provider and family "
                    f"to {cell.provider.value!r}"
                )
            if cell.lane.value == cell.family.value:
                raise FamilyMasqueradeError(
                    f"cell {cell.cell_id!r} collapses lane and family "
                    f"to {cell.lane.value!r}"
                )

    def validate_against_catalog(
        self,
        catalog: ProviderCapabilityCatalog | None = None,
    ) -> None:
        """Ensure every cell projects from a registered catalog entry."""

        active = catalog if catalog is not None else BASELINE_PROVIDER_CATALOG
        for cell in self._cells.values():
            entry = active.get(cell.provider_id)
            family_ids = {item.family_id for item in entry.family_support}
            if cell.family_id not in family_ids:
                raise ProviderMatrixDriftError(
                    f"cell {cell.cell_id!r} family {cell.family_id!r} is not "
                    f"declared on provider {cell.provider_id!r} in the source catalog"
                )
            if not _authority_at_most(cell.authority_ceiling, entry.authority_ceiling):
                raise ProviderMatrixAuthorityError(
                    f"cell {cell.cell_id!r} authority exceeds catalog ceiling"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_interface": self.catalog_interface,
            "cell_ids": list(self.cell_ids),
            "cells": [self._cells[key].to_dict() for key in sorted(self._cells)],
            "executable_matrix_interface": self.executable_matrix_interface,
            "family_ids": list(self.family_ids),
            "generation_source": self.generation_source,
            "generation_task": self.generation_task,
            "interface": self.interface,
            "lane_ids": list(self.lane_ids),
            "provider_ids": list(self.provider_ids),
            "schema_version": self.schema_version,
            "version": self.version,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        frozen: bool = False,
    ) -> "ProviderCapabilityMatrixV2":
        if not isinstance(value, Mapping):
            raise ProviderMatrixV2Error("matrix payload must be a mapping")
        schema = value.get("schema_version")
        if schema != MATRIX_V2_SCHEMA_VERSION:
            raise ProviderMatrixV2Error(
                f"unsupported or missing matrix schema_version: {schema!r}"
            )
        interface = value.get("interface")
        if interface not in (None, MATRIX_V2_INTERFACE):
            raise ProviderMatrixV2Error(f"unsupported matrix interface: {interface!r}")
        return cls(
            cells=(
                ProviderCapabilityCellV2.from_dict(item)
                for item in value.get("cells", ())
            ),
            version=value.get("version", MATRIX_V2_MODULE_VERSION),
            generation_source=value.get("generation_source", GENERATION_SOURCE),
            generation_task=value.get("generation_task", GENERATION_TASK),
            catalog_interface=value.get("catalog_interface", CATALOG_INTERFACE),
            executable_matrix_interface=value.get(
                "executable_matrix_interface",
                EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
            ),
            frozen=frozen,
        )

    def __contains__(self, cell_id: object) -> bool:
        return isinstance(cell_id, str) and cell_id in self._cells

    def __iter__(self) -> Iterator[ProviderCapabilityCellV2]:
        for key in sorted(self._cells):
            yield self._cells[key]

    def __len__(self) -> int:
        return len(self._cells)


def generate_provider_capability_matrix_v2(
    *,
    catalog: ProviderCapabilityCatalog | None = None,
    matrix: Sequence[ProviderMatrixEntry] | None = None,
    frozen: bool = True,
    validate: bool = True,
) -> ProviderCapabilityMatrixV2:
    """Generate ProviderCapabilityMatrix@2 from the reviewed baseline source.

    The sole generation source is the sealed provider-capability catalog joined
    with executable-matrix lane declarations.  Hand-authored duplicate provider
    lists are not accepted.
    """

    active_catalog = catalog if catalog is not None else BASELINE_PROVIDER_CATALOG
    active_matrix = tuple(matrix) if matrix is not None else EXECUTABLE_PROVIDER_MATRIX
    matrix_by_provider = {entry.provider_id: entry for entry in active_matrix}

    cells: list[ProviderCapabilityCellV2] = []
    for entry in active_catalog:
        if entry.catalog_source is not ProviderCatalogSource.BASELINE:
            # Generated-closure rows are not re-projected here; baseline is
            # the single reviewed source for ProviderCapabilityMatrix@2.
            continue
        if not entry.family_support:
            # Advisory providers without family support emit no family cells.
            continue
        lane = _lane_for_provider(entry.provider_id, matrix_by_provider)
        cells.extend(_cells_from_entry(entry, lane=lane))

    result = ProviderCapabilityMatrixV2(
        cells,
        frozen=False,
        generation_source=GENERATION_SOURCE,
        generation_task=GENERATION_TASK,
        catalog_interface=active_catalog.interface,
        executable_matrix_interface=EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
    )
    if validate:
        result.validate_no_masquerades()
        result.validate_against_catalog(active_catalog)
        # Every executable-matrix provider with family support must appear.
        for matrix_entry in active_matrix:
            catalog_entry = active_catalog.get(matrix_entry.provider_id)
            if catalog_entry.family_support and matrix_entry.provider_id not in set(
                result.provider_ids
            ):
                raise ProviderMatrixDriftError(
                    f"executable-matrix provider {matrix_entry.provider_id!r} "
                    "missing from generated matrix"
                )
    if frozen:
        result.freeze()
    return result


BASELINE_PROVIDER_CAPABILITY_MATRIX_V2: Final[ProviderCapabilityMatrixV2] = (
    generate_provider_capability_matrix_v2(frozen=True, validate=True)
)


__all__ = [
    "BASELINE_PROVIDER_CAPABILITY_MATRIX_V2",
    "CELL_SCHEMA_VERSION",
    "FEATURE_SCHEMA_VERSION",
    "GENERATION_SOURCE",
    "GENERATION_TASK",
    "MATRIX_V2_INTERFACE",
    "MATRIX_V2_MODULE_VERSION",
    "MATRIX_V2_SCHEMA_VERSION",
    "CapabilityLifecycle",
    "FamilyMasqueradeError",
    "ProviderCapabilityCellV2",
    "ProviderCapabilityFeatureV2",
    "ProviderCapabilityMatrixV2",
    "ProviderMatrixAuthorityError",
    "ProviderMatrixDriftError",
    "ProviderMatrixV2Error",
    "generate_provider_capability_matrix_v2",
    "reject_family_masquerade",
    "resolve_lane_for_matrix_family",
]
