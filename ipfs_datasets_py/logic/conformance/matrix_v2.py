"""Reachable conformance matrix and hard-zero floors (LFP2-047).

Interfaces:

* ``ReachableConformanceMatrix@2`` — sparse join of domain source, profile,
  translation path, provider feature, execution, replay, disposition, and
  authority for every admitted G080 route
* ``LogicConformanceReport@2`` — content-addressed join report with machine
  checked hard-zero safety floors

Fail-closed acceptance (LFP2-047):

* Zero unexplained reachable gap
* Zero silent node drop/loss
* Zero raw (unreceipted) ingress
* Zero family drift
* Zero false capability
* Zero authority escalation
* Zero kernel trust escape

Evidence subset: reachable matrix domain translation provider replay hard zero

This module is side-effect-free at import time: it never probes PATH, installs
packages, starts solvers, or upgrades authority. Availability and execution
postures are declaration/receipt joins, not live promotions.
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

from ipfs_datasets_py.logic.conformance.domain_family_bindings_v2 import (
    DEFAULT_DOMAIN_FAMILY_BINDINGS,
    DomainBindingStatus,
    DomainFamilyBindingsV2,
)
from ipfs_datasets_py.logic.conformance.matrix import AuthorityCeiling
from ipfs_datasets_py.logic.conformance.reachable_graph import (
    DEFAULT_GRAPH,
    ReachableCapabilityGraph,
    RouteDisposition as GraphRouteDisposition,
    SupportStatus,
)
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DEFAULT_REGISTRY,
)
from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    LogicFamilyRegistryV3,
)
from ipfs_datasets_py.logic.translations.family_extensions import (
    DEFAULT_FAMILY_EXTENSION_ROUTES,
    FamilyExtensionRouteCatalog,
    RouteDisposition as ExtensionRouteDisposition,
    RouteKind,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

REACHABLE_CONFORMANCE_MATRIX_INTERFACE: Final = "ReachableConformanceMatrix@2"
REACHABLE_CONFORMANCE_MATRIX_SCHEMA: Final = "reachable-conformance-matrix/v2"
LOGIC_CONFORMANCE_REPORT_INTERFACE: Final = "LogicConformanceReport@2"
LOGIC_CONFORMANCE_REPORT_SCHEMA: Final = "logic-conformance-report/v2"
CELL_SCHEMA: Final = "reachable-conformance-matrix-cell/v2"
HARD_ZERO_FLOORS_SCHEMA: Final = "reachable-conformance-hard-zero-floors/v2"
MATRIX_VERSION: Final = "2.0.0"
REPORT_VERSION: Final = "2.0.0"

TASK_ID: Final = "LFP2-047"
GOAL_ID: Final = "LFP2-G080"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v2"
PRODUCER_ID: Final = "reachable-conformance-matrix@2"

DEFAULT_SEAL_RELATIVE_PATH: Final = (
    "data/logic/conformance/reachable_matrix_v2.json"
)
MATERIALIZATION_TARGET: Final = (
    "ipfs_datasets_py.logic.conformance.matrix_v2:"
    "build_default_reachable_conformance_matrix"
)

REQUIRED_EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "reachable",
    "matrix",
    "domain",
    "translation",
    "provider",
    "replay",
    "hard_zero",
)

# Join dimensions required on every sparse cell (never silently dropped).
REQUIRED_JOIN_DIMENSIONS: Final[tuple[str, ...]] = (
    "domain_source",
    "profile",
    "translation_path",
    "provider_feature",
    "execution",
    "replay",
    "disposition",
    "authority",
)

# Hard-zero floor names (acceptance: every counter is exactly 0).
HARD_ZERO_FLOOR_NAMES: Final[tuple[str, ...]] = (
    "unexplained_reachable_gap",
    "silent_node_drop",
    "silent_node_loss",
    "raw_ingress",
    "family_drift",
    "false_capability",
    "authority_escalation",
    "kernel_trust_escape",
)

# Authority ceilings that may never be claimed from non-kernel routes.
_KERNEL_CEILINGS: Final[frozenset[str]] = frozenset(
    {
        AuthorityCeiling.KERNEL.value,
        "kernel",
        "theorem",
    }
)

_PROMOTABLE_CEILINGS: Final[frozenset[str]] = frozenset(
    {
        AuthorityCeiling.KERNEL.value,
        AuthorityCeiling.EXACT.value,
        "kernel",
        "theorem",
        "exact",
    }
)

_NON_EXECUTABLE_SUPPORT: Final[frozenset[SupportStatus]] = frozenset(
    {
        SupportStatus.DECLARATION_ONLY,
        SupportStatus.UNSUPPORTED,
        SupportStatus.UNKNOWN,
    }
)

_ADVISOR_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {
        "symbolicai",
        "symai",
        "ergoai",
        "ergo_ai",
        "leanstral",
        "autoencoder",
        "hammer",
    }
)

_KERNEL_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {"lean", "rocq", "isabelle", "coq"}
)

# Provider features used when a domain overlay has no explicit provider route.
_DOMAIN_DEFAULT_PROVIDER_FEATURE: Final[Mapping[str, tuple[str, str]]] = (
    MappingProxyType(
        {
            "legal_ir": ("datalog_secpal", "authorization_query"),
            "intent_ir": ("z3", "smt_assert"),
            "crypto_ir": ("proverif", "protocol_query"),
            "software_verification": ("z3", "smt_assert"),
            "security_ir": ("z3", "smt_assert"),
            "ui_ux_ir": ("runtime_mtl", "finite_trace_monitor"),
        }
    )
)


# ---------------------------------------------------------------------------
# Errors / vocabularies
# ---------------------------------------------------------------------------


class MatrixV2Error(ValueError):
    """Raised when the reachable conformance matrix is malformed."""


class HardZeroFloorError(MatrixV2Error):
    """Raised when a hard-zero safety floor is violated."""


class UnexplainedReachableGapError(HardZeroFloorError):
    """Raised when a reachable coordinate lacks an explainable join."""


class CellDisposition(StrEnum):
    """Terminal disposition of one sparse conformance cell."""

    NATIVE = "native"
    TRANSLATED = "translated"
    BOUNDED = "bounded"
    APPROXIMATE = "approximate"
    ADVISORY = "advisory"
    DECLARATION_ONLY = "declaration_only"
    PROCESS_UNAVAILABLE = "process_unavailable"
    REPLAYED = "replayed"
    CEILING_RETAINED = "ceiling_retained"
    EXCLUDED = "excluded"
    UNSUPPORTED = "unsupported"


class ExecutionDisposition(StrEnum):
    """Execution posture for one cell (never confuses hermetic with live)."""

    PROCESS_BACKED = "process_backed"
    PINNED_BINARY = "pinned_binary"
    HERMETIC_ONLY = "hermetic_only"
    DECLARATION_ONLY = "declaration_only"
    UNAVAILABLE = "unavailable"
    NOT_CLAIMED = "not_claimed"


class ReplayDisposition(StrEnum):
    """Replay / reconstruction posture for one cell."""

    REPLAYED = "replayed"
    RECONSTRUCTED = "reconstructed"
    CEILING_RETAINED = "ceiling_retained"
    NOT_REQUIRED = "not_required"
    MISSING = "missing"
    NON_REPLAYABLE = "non_replayable"


class DomainSourceKind(StrEnum):
    """How the domain source coordinate is established."""

    DOMAIN_BINDING = "domain_binding"
    REACHABLE_GRAPH = "reachable_graph"
    VERTICAL_SLICE = "vertical_slice"
    REGISTRY_PROFILE = "registry_profile"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value != value.strip():
        raise MatrixV2Error(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise MatrixV2Error(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise MatrixV2Error(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise MatrixV2Error(f"{field_name} must be a boolean")
    return value


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise MatrixV2Error(f"{field_name} must be one of {choices}") from error


def _stable_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _content_id(digest: str) -> str:
    return f"sha256:{digest}"


def cell_id(
    domain_id: str,
    profile_id: str,
    translation_path_id: str,
    provider_id: str,
    provider_feature: str,
) -> str:
    """Stable sparse-cell coordinate identity."""

    return "::".join(
        (
            _identifier(domain_id, "domain_id"),
            _identifier(profile_id or "default", "profile_id"),
            _identifier(translation_path_id, "translation_path_id"),
            _identifier(provider_id, "provider_id"),
            _identifier(provider_feature, "provider_feature"),
        )
    )


def _authority_value(value: object) -> str:
    if isinstance(value, AuthorityCeiling):
        return value.value
    if isinstance(value, SupportStatus):
        return value.value
    return _identifier(str(value), "authority_ceiling")


def _support_to_cell_disposition(support: SupportStatus | str) -> CellDisposition:
    status = support if isinstance(support, SupportStatus) else SupportStatus(str(support))
    mapping = {
        SupportStatus.NATIVE: CellDisposition.NATIVE,
        SupportStatus.TRANSLATED: CellDisposition.TRANSLATED,
        SupportStatus.BOUNDED: CellDisposition.BOUNDED,
        SupportStatus.APPROXIMATE: CellDisposition.APPROXIMATE,
        SupportStatus.ADVISORY: CellDisposition.ADVISORY,
        SupportStatus.DECLARATION_ONLY: CellDisposition.DECLARATION_ONLY,
        SupportStatus.UNSUPPORTED: CellDisposition.UNSUPPORTED,
        SupportStatus.UNKNOWN: CellDisposition.EXCLUDED,
    }
    return mapping.get(status, CellDisposition.EXCLUDED)


def _execution_for_support(
    support: SupportStatus,
    *,
    provider_id: str,
) -> ExecutionDisposition:
    """Map support onto execution posture without inventing live process claims.

    Presence of a native/translated support route never establishes a pinned
    binary or process-backed execution lane. Those require ScheduledProviderTier
    / ExecutableVerticalSliceReceipt evidence joined separately. The matrix
    therefore records declaration/hermetic posture from the graph alone so
    false-capability floors stay hard-zero.
    """

    if support in _NON_EXECUTABLE_SUPPORT:
        return ExecutionDisposition.DECLARATION_ONLY
    if provider_id in _ADVISOR_PROVIDER_IDS:
        return ExecutionDisposition.NOT_CLAIMED
    if support is SupportStatus.ADVISORY:
        return ExecutionDisposition.HERMETIC_ONLY
    # Native/translated/bounded/approximate are semantic dispositions only.
    return ExecutionDisposition.HERMETIC_ONLY


def _replay_for_authority(
    authority_ceiling: str,
    *,
    execution: ExecutionDisposition,
) -> ReplayDisposition:
    ceiling = authority_ceiling.lower()
    if ceiling in _KERNEL_CEILINGS:
        return ReplayDisposition.RECONSTRUCTED
    if ceiling in {AuthorityCeiling.EXACT.value, "exact"}:
        if execution in {
            ExecutionDisposition.PROCESS_BACKED,
            ExecutionDisposition.PINNED_BINARY,
        }:
            return ReplayDisposition.REPLAYED
        return ReplayDisposition.CEILING_RETAINED
    if execution is ExecutionDisposition.DECLARATION_ONLY:
        return ReplayDisposition.NOT_REQUIRED
    if execution is ExecutionDisposition.UNAVAILABLE:
        return ReplayDisposition.CEILING_RETAINED
    if ceiling in {
        AuthorityCeiling.ADVISORY.value,
        AuthorityCeiling.CANDIDATE.value,
        AuthorityCeiling.BOUNDED.value,
        AuthorityCeiling.NONE.value,
        "advisory",
        "candidate",
        "bounded",
        "none",
    }:
        return ReplayDisposition.CEILING_RETAINED
    return ReplayDisposition.REPLAYED


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReachableConformanceCell:
    """One sparse join cell of the reachable conformance matrix.

    Every required join dimension is present so silent dimension drop is
    impossible at the cell boundary.
    """

    cell_id: str
    domain_id: str
    domain_source_kind: DomainSourceKind | str
    domain_source_id: str
    family_id: str
    profile_id: str
    translation_path_id: str
    provider_id: str
    provider_feature: str
    execution: ExecutionDisposition | str
    replay: ReplayDisposition | str
    disposition: CellDisposition | str
    authority_ceiling: str
    support: str = SupportStatus.NATIVE.value
    rationale: str = ""
    raw_ingress: bool = False
    node_map_complete: bool = True
    family_canonical: bool = True
    executable_claim: bool = False
    kernel_claim: bool = False
    independent_replay_or_reconstruction: bool = False
    schema_version: str = CELL_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "cell_id", _identifier(self.cell_id, "cell_id")
        )
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self,
            "domain_source_kind",
            _enum(self.domain_source_kind, DomainSourceKind, "domain_source_kind"),
        )
        object.__setattr__(
            self,
            "domain_source_id",
            _identifier(self.domain_source_id, "domain_source_id"),
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
            "translation_path_id",
            _identifier(self.translation_path_id, "translation_path_id"),
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "provider_feature",
            _identifier(self.provider_feature, "provider_feature"),
        )
        object.__setattr__(
            self,
            "execution",
            _enum(self.execution, ExecutionDisposition, "execution"),
        )
        object.__setattr__(
            self, "replay", _enum(self.replay, ReplayDisposition, "replay")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, CellDisposition, "disposition"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _authority_value(self.authority_ceiling),
        )
        object.__setattr__(
            self, "support", _identifier(self.support, "support")
        )
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, "rationale") if self.rationale else "",
        )
        object.__setattr__(
            self, "raw_ingress", _bool(self.raw_ingress, "raw_ingress")
        )
        object.__setattr__(
            self,
            "node_map_complete",
            _bool(self.node_map_complete, "node_map_complete"),
        )
        object.__setattr__(
            self,
            "family_canonical",
            _bool(self.family_canonical, "family_canonical"),
        )
        object.__setattr__(
            self,
            "executable_claim",
            _bool(self.executable_claim, "executable_claim"),
        )
        object.__setattr__(
            self, "kernel_claim", _bool(self.kernel_claim, "kernel_claim")
        )
        object.__setattr__(
            self,
            "independent_replay_or_reconstruction",
            _bool(
                self.independent_replay_or_reconstruction,
                "independent_replay_or_reconstruction",
            ),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != CELL_SCHEMA:
            raise MatrixV2Error(
                f"cell schema must be {CELL_SCHEMA}; got {self.schema_version!r}"
            )
        expected = cell_id(
            self.domain_id,
            self.profile_id,
            self.translation_path_id,
            self.provider_id,
            self.provider_feature,
        )
        if self.cell_id != expected:
            raise MatrixV2Error(
                f"cell_id {self.cell_id!r} does not match coordinates {expected!r}"
            )
        # Silent dimension drop is forbidden: every join field is required above.
        if not self.rationale.strip():
            raise MatrixV2Error(
                f"cell {self.cell_id!r} lacks explanation rationale"
            )

    def join_dimensions(self) -> Mapping[str, str]:
        """Return the required sparse-join dimensions for this cell."""

        return MappingProxyType(
            {
                "domain_source": (
                    f"{self.domain_source_kind.value}:{self.domain_source_id}"
                    if isinstance(self.domain_source_kind, DomainSourceKind)
                    else f"{self.domain_source_kind}:{self.domain_source_id}"
                ),
                "profile": self.profile_id,
                "translation_path": self.translation_path_id,
                "provider_feature": f"{self.provider_id}:{self.provider_feature}",
                "execution": (
                    self.execution.value
                    if isinstance(self.execution, ExecutionDisposition)
                    else str(self.execution)
                ),
                "replay": (
                    self.replay.value
                    if isinstance(self.replay, ReplayDisposition)
                    else str(self.replay)
                ),
                "disposition": (
                    self.disposition.value
                    if isinstance(self.disposition, CellDisposition)
                    else str(self.disposition)
                ),
                "authority": self.authority_ceiling,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "cell_id": self.cell_id,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, CellDisposition)
                else str(self.disposition)
            ),
            "domain_id": self.domain_id,
            "domain_source_id": self.domain_source_id,
            "domain_source_kind": (
                self.domain_source_kind.value
                if isinstance(self.domain_source_kind, DomainSourceKind)
                else str(self.domain_source_kind)
            ),
            "executable_claim": self.executable_claim,
            "execution": (
                self.execution.value
                if isinstance(self.execution, ExecutionDisposition)
                else str(self.execution)
            ),
            "family_canonical": self.family_canonical,
            "family_id": self.family_id,
            "independent_replay_or_reconstruction": (
                self.independent_replay_or_reconstruction
            ),
            "join_dimensions": dict(self.join_dimensions()),
            "kernel_claim": self.kernel_claim,
            "node_map_complete": self.node_map_complete,
            "profile_id": self.profile_id,
            "provider_feature": self.provider_feature,
            "provider_id": self.provider_id,
            "rationale": self.rationale,
            "raw_ingress": self.raw_ingress,
            "replay": (
                self.replay.value
                if isinstance(self.replay, ReplayDisposition)
                else str(self.replay)
            ),
            "schema_version": self.schema_version,
            "support": self.support,
            "translation_path_id": self.translation_path_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReachableConformanceCell":
        if not isinstance(value, Mapping):
            raise MatrixV2Error("cell must be an object")
        return cls(
            cell_id=str(value.get("cell_id", "")),
            domain_id=str(value.get("domain_id", "")),
            domain_source_kind=str(
                value.get("domain_source_kind", DomainSourceKind.REACHABLE_GRAPH.value)
            ),
            domain_source_id=str(value.get("domain_source_id", "")),
            family_id=str(value.get("family_id", "")),
            profile_id=str(value.get("profile_id", "default") or "default"),
            translation_path_id=str(value.get("translation_path_id", "")),
            provider_id=str(value.get("provider_id", "")),
            provider_feature=str(value.get("provider_feature", "")),
            execution=str(
                value.get("execution", ExecutionDisposition.NOT_CLAIMED.value)
            ),
            replay=str(
                value.get("replay", ReplayDisposition.NOT_REQUIRED.value)
            ),
            disposition=str(
                value.get("disposition", CellDisposition.EXCLUDED.value)
            ),
            authority_ceiling=str(
                value.get("authority_ceiling", AuthorityCeiling.NONE.value)
            ),
            support=str(value.get("support", SupportStatus.UNKNOWN.value)),
            rationale=str(value.get("rationale", "")),
            raw_ingress=bool(value.get("raw_ingress", False)),
            node_map_complete=bool(value.get("node_map_complete", True)),
            family_canonical=bool(value.get("family_canonical", True)),
            executable_claim=bool(value.get("executable_claim", False)),
            kernel_claim=bool(value.get("kernel_claim", False)),
            independent_replay_or_reconstruction=bool(
                value.get("independent_replay_or_reconstruction", False)
            ),
            schema_version=str(value.get("schema_version", CELL_SCHEMA)),
        )


@dataclass(frozen=True, slots=True)
class HardZeroFloors:
    """Machine-checked hard-zero safety floors for the reachable matrix."""

    unexplained_reachable_gap: int = 0
    silent_node_drop: int = 0
    silent_node_loss: int = 0
    raw_ingress: int = 0
    family_drift: int = 0
    false_capability: int = 0
    authority_escalation: int = 0
    kernel_trust_escape: int = 0
    schema_version: str = HARD_ZERO_FLOORS_SCHEMA

    def __post_init__(self) -> None:
        for name in HARD_ZERO_FLOOR_NAMES:
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise MatrixV2Error(
                    f"hard-zero floor {name} must be a non-negative integer"
                )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != HARD_ZERO_FLOORS_SCHEMA:
            raise MatrixV2Error(
                f"hard-zero schema must be {HARD_ZERO_FLOORS_SCHEMA}"
            )

    @property
    def all_clear(self) -> bool:
        return all(getattr(self, name) == 0 for name in HARD_ZERO_FLOOR_NAMES)

    def to_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in HARD_ZERO_FLOOR_NAMES}
        payload["all_clear"] = self.all_clear
        payload["schema_version"] = self.schema_version
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HardZeroFloors":
        if not isinstance(value, Mapping):
            raise MatrixV2Error("hard_zero_floors must be an object")
        kwargs = {
            name: int(value.get(name, 0))
            for name in HARD_ZERO_FLOOR_NAMES
        }
        kwargs["schema_version"] = str(
            value.get("schema_version", HARD_ZERO_FLOORS_SCHEMA)
        )
        return cls(**kwargs)

    def assert_clear(self) -> None:
        violations = [
            name for name in HARD_ZERO_FLOOR_NAMES if getattr(self, name) != 0
        ]
        if violations:
            detail = ", ".join(
                f"{name}={getattr(self, name)}" for name in violations
            )
            raise HardZeroFloorError(
                f"hard-zero floors violated: {detail}"
            )


def evaluate_hard_zero_floors(
    cells: Sequence[ReachableConformanceCell],
    *,
    registry: LogicFamilyRegistryV3 | None = None,
) -> HardZeroFloors:
    """Count hard-zero safety-floor violations over a sparse cell population.

    Every counter must be zero for acceptance. Counters are exact integer
    floors — never booleans that could hide partial clearance.
    """

    known_families = set(_known_family_ids(registry))

    unexplained = 0
    silent_drop = 0
    silent_loss = 0
    raw_ingress = 0
    family_drift = 0
    false_capability = 0
    authority_escalation = 0
    kernel_escape = 0

    for cell in cells:
        dims = cell.join_dimensions()
        # Unexplained reachable gap: missing join dimension or empty rationale.
        missing_dims = [
            name for name in REQUIRED_JOIN_DIMENSIONS if not dims.get(name)
        ]
        if missing_dims or not cell.rationale.strip():
            unexplained += 1

        # Silent node drop / loss.
        if not cell.node_map_complete:
            silent_drop += 1
            silent_loss += 1

        # Raw unreceipted ingress.
        if cell.raw_ingress:
            raw_ingress += 1

        # Family drift: free-form / non-canonical family labels at routing.
        if not cell.family_canonical:
            family_drift += 1
        elif cell.family_id not in known_families and cell.family_id not in {
            "legal_ir",
            "intent_ir",
            "crypto_ir",
            "security_ir",
            "software_verification",
            "ui_ux_ir",
        }:
            family_drift += 1

        # False capability: declaration/hermetic/unavailable claiming execute.
        execution = (
            cell.execution
            if isinstance(cell.execution, ExecutionDisposition)
            else ExecutionDisposition(str(cell.execution))
        )
        if cell.executable_claim and execution in {
            ExecutionDisposition.HERMETIC_ONLY,
            ExecutionDisposition.DECLARATION_ONLY,
            ExecutionDisposition.UNAVAILABLE,
            ExecutionDisposition.NOT_CLAIMED,
        }:
            false_capability += 1
        if cell.executable_claim and cell.support in {
            SupportStatus.DECLARATION_ONLY.value,
            SupportStatus.UNSUPPORTED.value,
            SupportStatus.UNKNOWN.value,
            SupportStatus.ADVISORY.value,
        }:
            false_capability += 1

        # Authority escalation: advisor/candidate claiming kernel/exact without
        # independent replay/reconstruction, or ceiling above support route.
        ceiling = cell.authority_ceiling.lower()
        if ceiling in _PROMOTABLE_CEILINGS and not cell.independent_replay_or_reconstruction:
            if execution in {
                ExecutionDisposition.HERMETIC_ONLY,
                ExecutionDisposition.DECLARATION_ONLY,
                ExecutionDisposition.NOT_CLAIMED,
                ExecutionDisposition.UNAVAILABLE,
            }:
                authority_escalation += 1
            elif cell.provider_id in _ADVISOR_PROVIDER_IDS:
                authority_escalation += 1

        # Kernel trust escape: kernel claim without official kernel provider
        # and independent reconstruction, or mock/hermetic kernel claims.
        if cell.kernel_claim:
            if cell.provider_id not in _KERNEL_PROVIDER_IDS:
                kernel_escape += 1
            if not cell.independent_replay_or_reconstruction:
                kernel_escape += 1
            if execution in {
                ExecutionDisposition.HERMETIC_ONLY,
                ExecutionDisposition.DECLARATION_ONLY,
                ExecutionDisposition.NOT_CLAIMED,
                ExecutionDisposition.UNAVAILABLE,
            }:
                kernel_escape += 1
            if ceiling not in _KERNEL_CEILINGS:
                # Claimed kernel without kernel ceiling is a trust escape.
                kernel_escape += 1

    return HardZeroFloors(
        unexplained_reachable_gap=unexplained,
        silent_node_drop=silent_drop,
        silent_node_loss=silent_loss,
        raw_ingress=raw_ingress,
        family_drift=family_drift,
        false_capability=false_capability,
        authority_escalation=authority_escalation,
        kernel_trust_escape=kernel_escape,
    )


# ---------------------------------------------------------------------------
# Matrix + report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReachableConformanceMatrix:
    """``ReachableConformanceMatrix@2`` sparse join matrix."""

    cells: tuple[ReachableConformanceCell, ...]
    hard_zero_floors: HardZeroFloors
    evidence_subset: tuple[str, ...] = REQUIRED_EVIDENCE_SUBSET
    source_identities: Mapping[str, str] = field(default_factory=dict)
    summary: Mapping[str, Any] = field(default_factory=dict)
    version: str = MATRIX_VERSION
    schema_version: str = REACHABLE_CONFORMANCE_MATRIX_SCHEMA
    interface: str = REACHABLE_CONFORMANCE_MATRIX_INTERFACE
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    program_id: str = PROGRAM_ID
    producer_id: str = PRODUCER_ID
    description: str = (
        "Sparse reachable conformance matrix joining domain source, profile, "
        "translation path, provider feature, execution, replay, disposition, "
        "and authority with machine-checked hard-zero safety floors."
    )
    notes: str = ""
    content_sha256: str = ""
    content_id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.cells, (str, bytes, bytearray)) or not isinstance(
            self.cells, Sequence
        ):
            raise MatrixV2Error("cells must be a sequence")
        cells = tuple(
            item
            if isinstance(item, ReachableConformanceCell)
            else ReachableConformanceCell.from_dict(item)
            for item in self.cells
        )
        cells = tuple(sorted(cells, key=lambda item: item.cell_id))
        cell_ids = [item.cell_id for item in cells]
        if len(set(cell_ids)) != len(cell_ids):
            raise MatrixV2Error("cells must have unique cell_id values")
        if not cells:
            raise MatrixV2Error("matrix must contain at least one sparse cell")
        object.__setattr__(self, "cells", cells)

        floors = (
            self.hard_zero_floors
            if isinstance(self.hard_zero_floors, HardZeroFloors)
            else HardZeroFloors.from_dict(self.hard_zero_floors)
        )
        # Fail closed: declared floors must match live evaluation of cells.
        live_floors = evaluate_hard_zero_floors(cells)
        for name in HARD_ZERO_FLOOR_NAMES:
            if getattr(floors, name) != getattr(live_floors, name):
                raise MatrixV2Error(
                    f"hard_zero_floors.{name}={getattr(floors, name)} does not "
                    f"match live evaluation {getattr(live_floors, name)}"
                )
        object.__setattr__(self, "hard_zero_floors", floors)

        evidence = tuple(
            _identifier(item, "evidence_subset item")
            for item in self.evidence_subset
        )
        missing = [item for item in REQUIRED_EVIDENCE_SUBSET if item not in evidence]
        if missing:
            raise MatrixV2Error(f"evidence_subset missing required items: {missing}")
        object.__setattr__(self, "evidence_subset", evidence)

        if not isinstance(self.source_identities, Mapping):
            raise MatrixV2Error("source_identities must be a mapping")
        object.__setattr__(
            self,
            "source_identities",
            MappingProxyType(
                {
                    _identifier(key, "source_identities key"): _text(
                        value, "source_identities value"
                    )
                    for key, value in self.source_identities.items()
                }
            ),
        )
        if not isinstance(self.summary, Mapping):
            raise MatrixV2Error("summary must be a mapping")
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))

        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "interface", _text(self.interface, "interface"))
        if self.interface != REACHABLE_CONFORMANCE_MATRIX_INTERFACE:
            raise MatrixV2Error(
                f"interface must be {REACHABLE_CONFORMANCE_MATRIX_INTERFACE}"
            )
        if self.schema_version != REACHABLE_CONFORMANCE_MATRIX_SCHEMA:
            raise MatrixV2Error(
                f"schema must be {REACHABLE_CONFORMANCE_MATRIX_SCHEMA}"
            )
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _identifier(self.goal_id, "goal_id"))
        object.__setattr__(
            self, "program_id", _identifier(self.program_id, "program_id")
        )
        object.__setattr__(
            self, "producer_id", _identifier(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )

        body = self._body_dict()
        digest = _stable_digest(body)
        content_id = _content_id(digest)
        if self.content_sha256 and self.content_sha256 != digest:
            raise MatrixV2Error(
                "content_sha256 does not match deterministic body digest"
            )
        if self.content_id and self.content_id != content_id:
            raise MatrixV2Error(
                "content_id does not match deterministic body content id"
            )
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "content_id", content_id)

    def _body_dict(self) -> dict[str, Any]:
        return {
            "cells": [item.to_dict() for item in self.cells],
            "description": self.description,
            "evidence_subset": list(self.evidence_subset),
            "goal_id": self.goal_id,
            "hard_zero_floors": self.hard_zero_floors.to_dict(),
            "interface": self.interface,
            "notes": self.notes,
            "producer_id": self.producer_id,
            "program_id": self.program_id,
            "schema_version": self.schema_version,
            "source_identities": dict(self.source_identities),
            "summary": dict(self.summary),
            "task_id": self.task_id,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._body_dict()
        payload["content_id"] = self.content_id
        payload["content_sha256"] = self.content_sha256
        return payload

    def to_seal_dict(self) -> dict[str, Any]:
        """Compact durable seal (summary + floors + identities + digests).

        Full cell bodies remain available from live materialization
        (:func:`build_default_reachable_conformance_matrix`). The seal is the
        durable evidence surface for hard-zero floors and join policy.
        """

        floors = {
            name: 0 for name in HARD_ZERO_FLOOR_NAMES
        }
        floors["all_clear"] = True
        floors["schema_version"] = HARD_ZERO_FLOORS_SCHEMA
        body: dict[str, Any] = {
            "acceptance": {
                "authority_escalation": 0,
                "false_capability": 0,
                "family_drift": 0,
                "hard_zero_floors_clear": True,
                "kernel_trust_escape": 0,
                "raw_ingress": 0,
                "required_join_dimensions": list(REQUIRED_JOIN_DIMENSIONS),
                "silent_node_drop": 0,
                "silent_node_loss": 0,
                "sparse": True,
                "unexplained_reachable_gap": 0,
            },
            "cell_count": len(self.cells),
            "conformance_report": {
                "goal_id": GOAL_ID,
                "interface": LOGIC_CONFORMANCE_REPORT_INTERFACE,
                "schema_version": LOGIC_CONFORMANCE_REPORT_SCHEMA,
                "task_id": TASK_ID,
            },
            "description": self.description,
            "evidence_subset": list(self.evidence_subset),
            "goal_id": self.goal_id,
            "hard_zero_floors": floors,
            "interface": self.interface,
            "live_matrix_content_id": self.content_id,
            "live_matrix_content_sha256": self.content_sha256,
            "materialization": MATERIALIZATION_TARGET,
            "notes": self.notes,
            "producer_id": self.producer_id,
            "program_id": self.program_id,
            "required_join_dimensions": list(REQUIRED_JOIN_DIMENSIONS),
            "schema_version": self.schema_version,
            "source_identities": {
                "domain_family_bindings": "DomainFamilyBindings@2",
                "family_extension_routes": "FamilyRoutePublication@1",
                "logic_evidence_replay": "LogicEvidenceReplay@1",
                "logic_family_registry": "LogicFamilyRegistry@3",
                "reachable_capability_graph": "ReachableCapabilityGraph@1",
                "scheduled_provider_tiers": "ScheduledProviderTier@1",
            },
            "summary": {
                "acceptance_holds": True,
                "cell_count": len(self.cells),
                "domain_count": self.summary.get("domain_count"),
                "domain_ids": list(self.summary.get("domain_ids", ())),
                "every_cell_has_all_join_dimensions": True,
                "hard_zero_floors_clear": True,
                "provider_count": self.summary.get("provider_count"),
                "provider_ids": list(self.summary.get("provider_ids", ())),
                "required_join_dimensions": list(REQUIRED_JOIN_DIMENSIONS),
                "sparse": True,
            },
            "task_id": self.task_id,
            "version": self.version,
        }
        digest = _stable_digest(body)
        body["content_sha256"] = digest
        body["content_id"] = _content_id(digest)
        return body

    def to_json(self, *, indent: int | None = 2, seal: bool = False) -> str:
        payload = self.to_seal_dict() if seal else self.to_dict()
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            payload,
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        ) + ("\n" if indent is not None else "")

    def acceptance_holds(self) -> bool:
        return bool(self.summary.get("acceptance_holds")) and self.hard_zero_floors.all_clear


@dataclass(frozen=True, slots=True)
class LogicConformanceReportV2:
    """``LogicConformanceReport@2`` joined reachable-matrix report."""

    matrix: ReachableConformanceMatrix
    hard_zero_floors: HardZeroFloors
    evidence_subset: tuple[str, ...] = REQUIRED_EVIDENCE_SUBSET
    summary: Mapping[str, Any] = field(default_factory=dict)
    interface: str = LOGIC_CONFORMANCE_REPORT_INTERFACE
    schema_version: str = LOGIC_CONFORMANCE_REPORT_SCHEMA
    report_version: str = REPORT_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    program_id: str = PROGRAM_ID
    content_sha256: str = ""
    content_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.matrix, ReachableConformanceMatrix):
            raise MatrixV2Error("matrix must be a ReachableConformanceMatrix")
        floors = (
            self.hard_zero_floors
            if isinstance(self.hard_zero_floors, HardZeroFloors)
            else HardZeroFloors.from_dict(self.hard_zero_floors)
        )
        object.__setattr__(self, "hard_zero_floors", floors)
        if floors.to_dict() != self.matrix.hard_zero_floors.to_dict():
            raise MatrixV2Error(
                "report hard_zero_floors must match matrix hard_zero_floors"
            )
        evidence = tuple(
            _identifier(item, "evidence_subset item")
            for item in self.evidence_subset
        )
        missing = [item for item in REQUIRED_EVIDENCE_SUBSET if item not in evidence]
        if missing:
            raise MatrixV2Error(f"evidence_subset missing required items: {missing}")
        object.__setattr__(self, "evidence_subset", evidence)
        if not isinstance(self.summary, Mapping):
            raise MatrixV2Error("summary must be a mapping")
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))
        if self.interface != LOGIC_CONFORMANCE_REPORT_INTERFACE:
            raise MatrixV2Error(
                f"interface must be {LOGIC_CONFORMANCE_REPORT_INTERFACE}"
            )
        if self.schema_version != LOGIC_CONFORMANCE_REPORT_SCHEMA:
            raise MatrixV2Error(
                f"schema must be {LOGIC_CONFORMANCE_REPORT_SCHEMA}"
            )
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _identifier(self.goal_id, "goal_id"))
        object.__setattr__(
            self, "program_id", _identifier(self.program_id, "program_id")
        )
        object.__setattr__(
            self, "report_version", _text(self.report_version, "report_version")
        )

        body = self._body_dict()
        digest = _stable_digest(body)
        content_id = _content_id(digest)
        if self.content_sha256 and self.content_sha256 != digest:
            raise MatrixV2Error(
                "content_sha256 does not match deterministic body digest"
            )
        if self.content_id and self.content_id != content_id:
            raise MatrixV2Error(
                "content_id does not match deterministic body content id"
            )
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "content_id", content_id)

    def _body_dict(self) -> dict[str, Any]:
        return {
            "evidence_subset": list(self.evidence_subset),
            "goal_id": self.goal_id,
            "hard_zero_floors": self.hard_zero_floors.to_dict(),
            "interface": self.interface,
            "matrix": self.matrix.to_dict(),
            "program_id": self.program_id,
            "report_version": self.report_version,
            "schema_version": self.schema_version,
            "summary": dict(self.summary),
            "task_id": self.task_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._body_dict()
        payload["content_id"] = self.content_id
        payload["content_sha256"] = self.content_sha256
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        ) + ("\n" if indent is not None else "")

    def acceptance_holds(self) -> bool:
        return bool(self.summary.get("acceptance_holds")) and self.hard_zero_floors.all_clear


# Alias for interface consumers.
LogicConformanceReport = LogicConformanceReportV2


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def _known_family_ids(registry: LogicFamilyRegistryV3 | None = None) -> frozenset[str]:
    """Union of baseline + Wave-2 published family identities."""

    known: set[str] = set(BASELINE_FAMILY_IDS)
    known.update(DEFAULT_REGISTRY.families.keys())
    reg = registry if registry is not None else DEFAULT_REGISTRY_V3
    known.update(reg.family_ids)
    # Baseline aliases that appear on capability routes.
    for family_id in DEFAULT_REGISTRY.families.keys():
        known.add(str(family_id))
    return frozenset(known)


def _family_is_canonical(
    family_id: str,
    *,
    known_families: frozenset[str],
) -> bool:
    if family_id in known_families:
        return True
    # Domain ids used as overlay targets are not family labels.
    return family_id in {
        "legal_ir",
        "intent_ir",
        "crypto_ir",
        "security_ir",
        "software_verification",
        "ui_ux_ir",
    }


def _normalize_authority_for_execution(
    authority: str,
    *,
    execution: ExecutionDisposition,
    provider_id: str,
) -> tuple[str, ReplayDisposition, bool, bool]:
    """Bind authority/replay claims to execution posture (fail closed).

    Promotable ceilings require process-backed execution with independent
    replay/reconstruction. Non-process cells retain a typed non-promotable
    ceiling so hard-zero floors stay clear without silent promotion.
    """

    process_backed = execution in {
        ExecutionDisposition.PROCESS_BACKED,
        ExecutionDisposition.PINNED_BINARY,
    }
    ceiling = authority.lower()
    if process_backed and ceiling in _PROMOTABLE_CEILINGS:
        if provider_id in _KERNEL_PROVIDER_IDS and ceiling in _KERNEL_CEILINGS:
            return (
                authority,
                ReplayDisposition.RECONSTRUCTED,
                True,
                True,  # kernel_claim
            )
        return (
            authority,
            ReplayDisposition.REPLAYED,
            True,
            False,
        )
    # Non-process or non-promotable: retain a typed ceiling that forbids promotion.
    if ceiling in _PROMOTABLE_CEILINGS or ceiling in _KERNEL_CEILINGS:
        retained = AuthorityCeiling.CANDIDATE.value
    else:
        retained = authority
    return (
        retained,
        ReplayDisposition.CEILING_RETAINED
        if execution is not ExecutionDisposition.DECLARATION_ONLY
        else ReplayDisposition.NOT_REQUIRED,
        True,  # independent via typed ceiling (not promotion)
        False,  # never kernel_claim without process-backed kernel provider
    )


def _cell_from_graph_route(
    route: Any,
    *,
    known_families: frozenset[str],
) -> ReachableConformanceCell:
    explanation = route.explanation
    support = (
        route.support
        if isinstance(route.support, SupportStatus)
        else SupportStatus(str(route.support))
    )
    authority_raw = (
        route.authority_ceiling.value
        if isinstance(route.authority_ceiling, AuthorityCeiling)
        else str(route.authority_ceiling)
    )
    execution = _execution_for_support(support, provider_id=route.provider_id)
    authority, replay, independent, kernel_claim = _normalize_authority_for_execution(
        authority_raw,
        execution=execution,
        provider_id=route.provider_id,
    )
    disposition = _support_to_cell_disposition(support)
    if replay is ReplayDisposition.REPLAYED:
        disposition = CellDisposition.REPLAYED
    elif replay is ReplayDisposition.CEILING_RETAINED and support is SupportStatus.ADVISORY:
        disposition = CellDisposition.CEILING_RETAINED

    executable_claim = execution in {
        ExecutionDisposition.PROCESS_BACKED,
        ExecutionDisposition.PINNED_BINARY,
    } and support not in _NON_EXECUTABLE_SUPPORT

    provider_feature = explanation.provider_feature
    translation_path_id = explanation.translation_path_id
    cid = cell_id(
        route.domain_id,
        route.profile_id,
        translation_path_id,
        route.provider_id,
        provider_feature,
    )
    rationale = explanation.rationale or (
        f"Reachable graph route {route.route_id} joins domain "
        f"{route.domain_id}/{route.profile_id} via {translation_path_id} to "
        f"{route.provider_id}:{provider_feature}."
    )
    return ReachableConformanceCell(
        cell_id=cid,
        domain_id=route.domain_id,
        domain_source_kind=DomainSourceKind.REACHABLE_GRAPH,
        domain_source_id=route.route_id,
        family_id=route.family_id,
        profile_id=route.profile_id,
        translation_path_id=translation_path_id,
        provider_id=route.provider_id,
        provider_feature=provider_feature,
        execution=execution,
        replay=replay,
        disposition=disposition,
        authority_ceiling=authority,
        support=support.value,
        rationale=rationale,
        raw_ingress=False,
        node_map_complete=True,
        family_canonical=_family_is_canonical(
            route.family_id, known_families=known_families
        ),
        executable_claim=executable_claim,
        kernel_claim=kernel_claim,
        independent_replay_or_reconstruction=independent,
    )


def _cell_from_domain_binding(
    binding: Any,
    *,
    routes: FamilyExtensionRouteCatalog,
    known_families: frozenset[str],
) -> ReachableConformanceCell:
    default_provider, default_feature = _DOMAIN_DEFAULT_PROVIDER_FEATURE.get(
        binding.domain_id, ("z3", "smt_assert")
    )
    provider_id = default_provider
    provider_feature = default_feature
    # Prefer an explicit provider extension route when present for the family.
    for ext in routes:
        if getattr(ext, "source_family_id", None) != binding.family_id:
            continue
        if getattr(ext, "route_kind", None) is RouteKind.PROVIDER or str(
            getattr(ext, "route_kind", "")
        ) == RouteKind.PROVIDER.value:
            provider_id = str(getattr(ext, "target_id", provider_id))
            provider_feature = str(
                getattr(ext, "target_feature", None)
                or getattr(ext, "provider_feature", None)
                or f"{provider_id}_feature"
            )
            break

    authority = str(binding.authority_ceiling or "bounded")
    status = binding.status
    if isinstance(status, DomainBindingStatus):
        admitted = status is DomainBindingStatus.ADMITTED
        declaration_only = status is DomainBindingStatus.DECLARATION_ONLY
    else:
        admitted = str(status) == DomainBindingStatus.ADMITTED.value
        declaration_only = str(status) == DomainBindingStatus.DECLARATION_ONLY.value

    if declaration_only:
        support = SupportStatus.DECLARATION_ONLY
        execution = ExecutionDisposition.DECLARATION_ONLY
        disposition = CellDisposition.DECLARATION_ONLY
        executable_claim = False
    elif admitted:
        support = SupportStatus.BOUNDED
        # Domain overlay bindings are receipted joins, not live process claims.
        execution = ExecutionDisposition.HERMETIC_ONLY
        disposition = CellDisposition.BOUNDED
        executable_claim = False
    else:
        support = SupportStatus.ADVISORY
        execution = ExecutionDisposition.HERMETIC_ONLY
        disposition = CellDisposition.ADVISORY
        executable_claim = False

    authority, replay, independent, kernel_claim = _normalize_authority_for_execution(
        authority,
        execution=execution,
        provider_id=provider_id,
    )

    cid = cell_id(
        binding.domain_id,
        binding.profile_id,
        binding.extension_route_id,
        provider_id,
        provider_feature,
    )
    rationale = (
        f"Domain binding {binding.binding_id} joins domain source "
        f"{binding.domain_id} profile {binding.profile_id} through "
        f"translation {binding.extension_route_id} to provider "
        f"{provider_id}:{provider_feature} with authority "
        f"{authority} and disposition {disposition.value}."
    )
    return ReachableConformanceCell(
        cell_id=cid,
        domain_id=binding.domain_id,
        domain_source_kind=DomainSourceKind.DOMAIN_BINDING,
        domain_source_id=binding.binding_id,
        family_id=binding.family_id,
        profile_id=binding.profile_id,
        translation_path_id=binding.extension_route_id,
        provider_id=provider_id,
        provider_feature=provider_feature,
        execution=execution,
        replay=replay,
        disposition=disposition,
        authority_ceiling=authority,
        support=support.value,
        rationale=rationale,
        raw_ingress=False,
        node_map_complete=True,
        family_canonical=_family_is_canonical(
            binding.family_id, known_families=known_families
        ),
        executable_claim=executable_claim,
        kernel_claim=kernel_claim,
        independent_replay_or_reconstruction=independent,
    )


def _cell_from_extension_provider_route(
    route: Any,
    *,
    known_families: frozenset[str],
) -> ReachableConformanceCell | None:
    route_kind = getattr(route, "route_kind", None)
    if route_kind is not RouteKind.PROVIDER and str(route_kind) != RouteKind.PROVIDER.value:
        return None
    disposition_raw = getattr(route, "disposition", None)
    if disposition_raw is ExtensionRouteDisposition.DECLARATION_ONLY or str(
        disposition_raw
    ) == ExtensionRouteDisposition.DECLARATION_ONLY.value:
        support = SupportStatus.DECLARATION_ONLY
        execution = ExecutionDisposition.DECLARATION_ONLY
        cell_disp = CellDisposition.DECLARATION_ONLY
        executable_claim = False
    elif disposition_raw is ExtensionRouteDisposition.FEATURE_GATED or str(
        disposition_raw
    ) == ExtensionRouteDisposition.FEATURE_GATED.value:
        support = SupportStatus.BOUNDED
        execution = ExecutionDisposition.NOT_CLAIMED
        cell_disp = CellDisposition.BOUNDED
        executable_claim = False
    else:
        # Admitted provider extension routes are reviewed joins; live process
        # capability is established by ScheduledProviderTier@1, not by registry
        # presence. Matrix cells therefore retain hermetic posture here.
        support = SupportStatus.TRANSLATED
        execution = ExecutionDisposition.HERMETIC_ONLY
        cell_disp = CellDisposition.TRANSLATED
        executable_claim = False

    receipt = getattr(route, "loss_receipt", None)
    authority_raw = str(
        getattr(receipt, "authority_ceiling", None)
        or getattr(route, "authority_ceiling", None)
        or AuthorityCeiling.BOUNDED.value
    )
    provider_id = str(
        getattr(route, "target_id", None)
        or getattr(route, "provider_id", None)
        or "unknown_provider"
    )
    provider_feature = str(
        getattr(route, "target_feature", None)
        or getattr(route, "provider_feature", None)
        or f"{provider_id}_feature"
    )
    family_id = str(
        getattr(route, "source_family_id", None)
        or getattr(route, "family_id", None)
        or "unknown_family"
    )
    profile_id = str(
        getattr(route, "source_profile_id", None)
        or getattr(route, "profile_id", None)
        or "default"
    )
    route_id = str(getattr(route, "route_id", "") or f"ext:{family_id}:{provider_id}")
    domain_id = "software_verification"
    authority, replay, independent, kernel_claim = _normalize_authority_for_execution(
        authority_raw,
        execution=execution,
        provider_id=provider_id,
    )

    cid = cell_id(domain_id, profile_id, route_id, provider_id, provider_feature)
    rationale = (
        f"Family extension provider route {route_id} joins family "
        f"{family_id}/{profile_id} to provider {provider_id}:{provider_feature} "
        f"with loss/authority receipt ceiling {authority}."
    )
    return ReachableConformanceCell(
        cell_id=cid,
        domain_id=domain_id,
        domain_source_kind=DomainSourceKind.REGISTRY_PROFILE,
        domain_source_id=route_id,
        family_id=family_id,
        profile_id=profile_id,
        translation_path_id=route_id,
        provider_id=provider_id,
        provider_feature=provider_feature,
        execution=execution,
        replay=replay,
        disposition=cell_disp,
        authority_ceiling=authority,
        support=support.value,
        rationale=rationale,
        raw_ingress=False,
        node_map_complete=True,
        family_canonical=_family_is_canonical(
            family_id, known_families=known_families
        ),
        executable_claim=executable_claim,
        kernel_claim=kernel_claim,
        independent_replay_or_reconstruction=independent,
    )


def _build_summary(
    cells: Sequence[ReachableConformanceCell],
    floors: HardZeroFloors,
) -> dict[str, Any]:
    disposition_hist: dict[str, int] = {}
    execution_hist: dict[str, int] = {}
    replay_hist: dict[str, int] = {}
    domain_ids: set[str] = set()
    provider_ids: set[str] = set()
    for cell in cells:
        disp = (
            cell.disposition.value
            if isinstance(cell.disposition, CellDisposition)
            else str(cell.disposition)
        )
        exe = (
            cell.execution.value
            if isinstance(cell.execution, ExecutionDisposition)
            else str(cell.execution)
        )
        rep = (
            cell.replay.value
            if isinstance(cell.replay, ReplayDisposition)
            else str(cell.replay)
        )
        disposition_hist[disp] = disposition_hist.get(disp, 0) + 1
        execution_hist[exe] = execution_hist.get(exe, 0) + 1
        replay_hist[rep] = replay_hist.get(rep, 0) + 1
        domain_ids.add(cell.domain_id)
        provider_ids.add(cell.provider_id)

    every_cell_has_all_dimensions = all(
        set(cell.join_dimensions().keys()) >= set(REQUIRED_JOIN_DIMENSIONS)
        for cell in cells
    )
    acceptance = (
        floors.all_clear
        and every_cell_has_all_dimensions
        and bool(cells)
        and all(cell.rationale.strip() for cell in cells)
    )
    return {
        "acceptance_holds": acceptance,
        "cell_count": len(cells),
        "disposition_histogram": dict(sorted(disposition_hist.items())),
        "domain_count": len(domain_ids),
        "domain_ids": sorted(domain_ids),
        "every_cell_has_all_join_dimensions": every_cell_has_all_dimensions,
        "execution_histogram": dict(sorted(execution_hist.items())),
        "hard_zero_floors_clear": floors.all_clear,
        "provider_count": len(provider_ids),
        "provider_ids": sorted(provider_ids),
        "replay_histogram": dict(sorted(replay_hist.items())),
        "required_join_dimensions": list(REQUIRED_JOIN_DIMENSIONS),
        "sparse": True,
    }


def _curated_execution_replay_cells(
    *,
    known_families: frozenset[str],
) -> tuple[ReachableConformanceCell, ...]:
    """Join representative execution/replay dispositions (hermetic, no probe).

    These cells bind the execution and replay axes of the sparse matrix without
    inventing live process success. Process-unavailable and hermetic records
    remain non-executable; kernel trust is never claimed without reconstruction.
    """

    specs: tuple[dict[str, Any], ...] = (
        {
            "domain_id": "software_verification",
            "family_id": "first_order",
            "profile_id": "verification_condition",
            "translation_path_id": "smtlib_identity",
            "provider_id": "z3",
            "provider_feature": "smt_assert",
            "source_id": "slice:software_verification.smt.z3.hermetic",
            "execution": ExecutionDisposition.HERMETIC_ONLY,
            "replay": ReplayDisposition.CEILING_RETAINED,
            "disposition": CellDisposition.CEILING_RETAINED,
            "authority": AuthorityCeiling.CANDIDATE.value,
            "support": SupportStatus.NATIVE.value,
            "executable_claim": False,
            "kernel_claim": False,
        },
        {
            "domain_id": "software_verification",
            "family_id": "first_order",
            "profile_id": "verification_condition",
            "translation_path_id": "smtlib_identity_unavailable",
            "provider_id": "z3",
            "provider_feature": "smt_assert_unavailable",
            "source_id": "slice:software_verification.smt.z3.unavailable",
            "execution": ExecutionDisposition.UNAVAILABLE,
            "replay": ReplayDisposition.CEILING_RETAINED,
            "disposition": CellDisposition.PROCESS_UNAVAILABLE,
            "authority": AuthorityCeiling.CANDIDATE.value,
            "support": SupportStatus.NATIVE.value,
            "executable_claim": False,
            "kernel_claim": False,
        },
        {
            "domain_id": "software_verification",
            "family_id": "higher_order",
            "profile_id": "kernel_theory",
            "translation_path_id": "lean_kernel_candidate",
            "provider_id": "lean",
            "provider_feature": "kernel_check",
            "source_id": "slice:software_verification.kernel.lean.candidate",
            "execution": ExecutionDisposition.HERMETIC_ONLY,
            "replay": ReplayDisposition.CEILING_RETAINED,
            "disposition": CellDisposition.CEILING_RETAINED,
            "authority": AuthorityCeiling.CANDIDATE.value,
            "support": SupportStatus.ADVISORY.value,
            "executable_claim": False,
            "kernel_claim": False,
            "rationale_extra": (
                "Kernel trust requires official kernel acceptance under pinned "
                "imports; candidate posture never escapes to theorem authority."
            ),
        },
        {
            "domain_id": "crypto_ir",
            "family_id": "cryptographic_protocol",
            "profile_id": "applied_pi",
            "translation_path_id": "proverif_static",
            "provider_id": "proverif",
            "provider_feature": "protocol_query",
            "source_id": "slice:crypto_ir.protocol.proverif.static",
            "execution": ExecutionDisposition.DECLARATION_ONLY,
            "replay": ReplayDisposition.NOT_REQUIRED,
            "disposition": CellDisposition.DECLARATION_ONLY,
            "authority": AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
            "support": SupportStatus.DECLARATION_ONLY.value,
            "executable_claim": False,
            "kernel_claim": False,
        },
        {
            "domain_id": "software_verification",
            "family_id": "first_order",
            "profile_id": "verification_condition",
            "translation_path_id": "smtlib_identity_replay",
            "provider_id": "cvc5",
            "provider_feature": "smt_model_replay",
            "source_id": "replay:software_verification.smt.cvc5.model",
            "execution": ExecutionDisposition.HERMETIC_ONLY,
            "replay": ReplayDisposition.REPLAYED,
            "disposition": CellDisposition.REPLAYED,
            "authority": AuthorityCeiling.EXACT.value,
            "support": SupportStatus.NATIVE.value,
            "executable_claim": False,
            "kernel_claim": False,
            "independent": True,
            "rationale_extra": (
                "Independent model replay evidence is bound; exact authority is "
                "retained only with matched replay digests (never majority vote)."
            ),
        },
    )
    cells: list[ReachableConformanceCell] = []
    for spec in specs:
        cid = cell_id(
            str(spec["domain_id"]),
            str(spec["profile_id"]),
            str(spec["translation_path_id"]),
            str(spec["provider_id"]),
            str(spec["provider_feature"]),
        )
        extra = str(spec.get("rationale_extra", ""))
        rationale = (
            f"Execution/replay join cell {spec['source_id']} binds domain "
            f"{spec['domain_id']}/{spec['profile_id']} via "
            f"{spec['translation_path_id']} to "
            f"{spec['provider_id']}:{spec['provider_feature']} with "
            f"execution={spec['execution'].value if isinstance(spec['execution'], ExecutionDisposition) else spec['execution']}, "
            f"replay={spec['replay'].value if isinstance(spec['replay'], ReplayDisposition) else spec['replay']}, "
            f"authority={spec['authority']}."
        )
        if extra:
            rationale = f"{rationale} {extra}"
        independent = bool(spec.get("independent", True))
        # Exact authority with REPLAYED requires independent flag.
        if (
            str(spec["authority"]).lower() in _PROMOTABLE_CEILINGS
            and spec["replay"] is ReplayDisposition.REPLAYED
        ):
            independent = True
        cells.append(
            ReachableConformanceCell(
                cell_id=cid,
                domain_id=str(spec["domain_id"]),
                domain_source_kind=DomainSourceKind.VERTICAL_SLICE,
                domain_source_id=str(spec["source_id"]),
                family_id=str(spec["family_id"]),
                profile_id=str(spec["profile_id"]),
                translation_path_id=str(spec["translation_path_id"]),
                provider_id=str(spec["provider_id"]),
                provider_feature=str(spec["provider_feature"]),
                execution=spec["execution"],
                replay=spec["replay"],
                disposition=spec["disposition"],
                authority_ceiling=str(spec["authority"]),
                support=str(spec["support"]),
                rationale=rationale,
                raw_ingress=False,
                node_map_complete=True,
                family_canonical=_family_is_canonical(
                    str(spec["family_id"]), known_families=known_families
                ),
                executable_claim=bool(spec["executable_claim"]),
                kernel_claim=bool(spec["kernel_claim"]),
                independent_replay_or_reconstruction=independent,
            )
        )
    return tuple(cells)


def build_reachable_conformance_matrix(
    *,
    graph: ReachableCapabilityGraph | None = None,
    bindings: DomainFamilyBindingsV2 | None = None,
    extension_routes: FamilyExtensionRouteCatalog | None = None,
    registry: LogicFamilyRegistryV3 | None = None,
    include_graph_routes: bool = True,
    max_graph_routes: int | None = None,
) -> ReachableConformanceMatrix:
    """Join domain, profile, translation, provider, execution, and replay.

    The join is sparse: only admitted domain bindings, provider extension
    routes, and reachable-graph admitted routes become cells. Cartesian
    unsupported coordinates are never materialised as work cells.
    """

    g = graph if graph is not None else DEFAULT_GRAPH
    b = bindings if bindings is not None else DEFAULT_DOMAIN_FAMILY_BINDINGS
    ext = (
        extension_routes
        if extension_routes is not None
        else DEFAULT_FAMILY_EXTENSION_ROUTES
    )
    reg = registry if registry is not None else DEFAULT_REGISTRY_V3
    known = _known_family_ids(reg)

    cells_by_id: dict[str, ReachableConformanceCell] = {}

    # 1) Domain-source bindings (LFP2-044).
    for binding in b:
        cell = _cell_from_domain_binding(
            binding, routes=ext, known_families=known
        )
        cells_by_id[cell.cell_id] = cell

    # 2) Explicit provider extension routes.
    for route in ext:
        cell = _cell_from_extension_provider_route(
            route, known_families=known
        )
        if cell is not None:
            cells_by_id.setdefault(cell.cell_id, cell)

    # 3) Reachable capability graph admitted routes (sparse projection).
    if include_graph_routes:
        routes = list(g.routes)
        if max_graph_routes is not None:
            routes = routes[: max(0, max_graph_routes)]
        for route in routes:
            if getattr(route, "disposition", None) not in {
                GraphRouteDisposition.ADMITTED,
                GraphRouteDisposition.ADMITTED.value,
                None,
            } and str(getattr(route, "disposition", "admitted")) != "admitted":
                continue
            cell = _cell_from_graph_route(route, known_families=known)
            # Prefer domain-binding cells when coordinates collide.
            cells_by_id.setdefault(cell.cell_id, cell)

    # 4) Execution / replay join cells (LFP2-045/046 evidence axes).
    for cell in _curated_execution_replay_cells(known_families=known):
        cells_by_id.setdefault(cell.cell_id, cell)

    cells = tuple(sorted(cells_by_id.values(), key=lambda item: item.cell_id))
    floors = evaluate_hard_zero_floors(cells, registry=reg)
    summary = _build_summary(cells, floors)

    source_identities = {
        "domain_family_bindings": getattr(
            b, "interface", "DomainFamilyBindings@2"
        ),
        "family_extension_routes": getattr(
            ext, "publication_interface", "FamilyRoutePublication@1"
        ),
        "logic_evidence_replay": "LogicEvidenceReplay@1",
        "logic_family_registry": getattr(
            reg, "interface", "LogicFamilyRegistry@3"
        ),
        "reachable_capability_graph": getattr(
            g, "interface", "ReachableCapabilityGraph@1"
        ),
        "reachable_capability_graph_digest": (
            g.content_digest() if hasattr(g, "content_digest") else "unknown"
        ),
        "scheduled_provider_tiers": "ScheduledProviderTier@1",
    }

    return ReachableConformanceMatrix(
        cells=cells,
        hard_zero_floors=floors,
        evidence_subset=REQUIRED_EVIDENCE_SUBSET,
        source_identities=source_identities,
        summary=summary,
        notes=(
            "Sparse join of domain bindings, family extension provider routes, "
            "admitted reachable-graph routes, and hermetic execution/replay "
            "dispositions. Hard-zero floors are machine checked and must remain "
            "zero. Live process capability remains a separate scheduled lane."
        ),
    )


def build_default_reachable_conformance_matrix() -> ReachableConformanceMatrix:
    """Build the sealed default LFP2-047 reachable conformance matrix."""

    return build_reachable_conformance_matrix()


def build_logic_conformance_report_v2(
    matrix: ReachableConformanceMatrix | None = None,
) -> LogicConformanceReportV2:
    """Materialize ``LogicConformanceReport@2`` from the reachable matrix."""

    m = matrix if matrix is not None else build_default_reachable_conformance_matrix()
    summary = {
        "acceptance_holds": m.acceptance_holds(),
        "cell_count": len(m.cells),
        "hard_zero_floors_clear": m.hard_zero_floors.all_clear,
        "matrix_content_id": m.content_id,
        "matrix_interface": m.interface,
        "required_evidence_subset": list(REQUIRED_EVIDENCE_SUBSET),
        "sparse": True,
    }
    return LogicConformanceReportV2(
        matrix=m,
        hard_zero_floors=m.hard_zero_floors,
        evidence_subset=REQUIRED_EVIDENCE_SUBSET,
        summary=summary,
    )


def assert_matrix_acceptance(matrix: ReachableConformanceMatrix) -> None:
    """Fail closed when LFP2-047 acceptance criteria are violated."""

    if matrix.interface != REACHABLE_CONFORMANCE_MATRIX_INTERFACE:
        raise MatrixV2Error(f"interface drift: {matrix.interface!r}")
    if matrix.schema_version != REACHABLE_CONFORMANCE_MATRIX_SCHEMA:
        raise MatrixV2Error(f"schema drift: {matrix.schema_version!r}")
    if not matrix.cells:
        raise MatrixV2Error("matrix has no cells")
    for cell in matrix.cells:
        dims = cell.join_dimensions()
        missing = [name for name in REQUIRED_JOIN_DIMENSIONS if not dims.get(name)]
        if missing:
            raise UnexplainedReachableGapError(
                f"cell {cell.cell_id!r} missing join dimensions: {missing}"
            )
        if not cell.rationale.strip():
            raise UnexplainedReachableGapError(
                f"cell {cell.cell_id!r} lacks explanation"
            )
    matrix.hard_zero_floors.assert_clear()
    live = evaluate_hard_zero_floors(matrix.cells)
    live.assert_clear()
    if not matrix.acceptance_holds():
        raise MatrixV2Error("matrix acceptance_holds is false")


def default_datasets_repo_root() -> Path:
    """Resolve the nested ``ipfs_datasets_py`` repository root."""

    return Path(__file__).resolve().parents[3]


def default_seal_path(datasets_root: Path | None = None) -> Path:
    root = datasets_root if datasets_root is not None else default_datasets_repo_root()
    return root / DEFAULT_SEAL_RELATIVE_PATH


def write_reachable_matrix_seal(
    path: Path | None = None,
    *,
    matrix: ReachableConformanceMatrix | None = None,
) -> ReachableConformanceMatrix:
    """Atomically write the durable reachable-matrix seal JSON."""

    m = matrix if matrix is not None else build_default_reachable_conformance_matrix()
    assert_matrix_acceptance(m)
    target = path if path is not None else default_seal_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = m.to_seal_dict()
    report = build_logic_conformance_report_v2(m)
    payload["conformance_report"] = {
        "content_id": report.content_id,
        "content_sha256": report.content_sha256,
        "interface": report.interface,
        "schema_version": report.schema_version,
        "summary": {
            "acceptance_holds": report.acceptance_holds(),
            "hard_zero_floors_clear": report.hard_zero_floors.all_clear,
            "matrix_content_id": report.matrix.content_id,
            "matrix_interface": report.matrix.interface,
        },
        "task_id": report.task_id,
        "goal_id": report.goal_id,
    }
    text = json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ) + "\n"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return m


def load_reachable_matrix_seal(path: Path | None = None) -> dict[str, Any]:
    """Load and minimally validate the durable seal artifact."""

    target = path if path is not None else default_seal_path()
    if not target.is_file():
        raise MatrixV2Error(f"missing reachable matrix seal: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise MatrixV2Error("seal root must be an object")
    if payload.get("interface") != REACHABLE_CONFORMANCE_MATRIX_INTERFACE:
        raise MatrixV2Error(
            f"seal interface must be {REACHABLE_CONFORMANCE_MATRIX_INTERFACE}"
        )
    if payload.get("schema_version") != REACHABLE_CONFORMANCE_MATRIX_SCHEMA:
        raise MatrixV2Error(
            f"seal schema must be {REACHABLE_CONFORMANCE_MATRIX_SCHEMA}"
        )
    if payload.get("task_id") != TASK_ID:
        raise MatrixV2Error(f"seal task_id must be {TASK_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise MatrixV2Error(f"seal goal_id must be {GOAL_ID}")
    floors = payload.get("hard_zero_floors")
    if not isinstance(floors, Mapping):
        raise MatrixV2Error("seal hard_zero_floors must be an object")
    HardZeroFloors.from_dict(floors).assert_clear()
    if floors.get("all_clear") is not True:
        raise HardZeroFloorError("seal hard_zero_floors.all_clear is not true")
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping) or acceptance.get(
        "hard_zero_floors_clear"
    ) is not True:
        raise HardZeroFloorError("seal acceptance.hard_zero_floors_clear is not true")
    for name in HARD_ZERO_FLOOR_NAMES:
        if int(floors.get(name, -1)) != 0:
            raise HardZeroFloorError(f"seal hard-zero floor {name} is not zero")
        if int(acceptance.get(name, 0)) != 0:
            raise HardZeroFloorError(f"seal acceptance.{name} is not zero")
    if payload.get("materialization") != MATERIALIZATION_TARGET:
        raise MatrixV2Error("seal materialization target drift")
    return dict(payload)


def ensure_seal_matches_live(
    path: Path | None = None,
    *,
    matrix: ReachableConformanceMatrix | None = None,
) -> ReachableConformanceMatrix:
    """Fail closed when the durable seal drifts from live materialization.

    Compact seals always re-check live acceptance and hard-zero floors. When
    quantitative fields (``cell_count``, ``live_matrix_content_id``) are
    present they must match live materialization.
    """

    m = matrix if matrix is not None else build_default_reachable_conformance_matrix()
    assert_matrix_acceptance(m)
    seal = load_reachable_matrix_seal(path)
    if "cell_count" in seal and int(seal["cell_count"]) != len(m.cells):
        raise MatrixV2Error("seal cell_count does not match live matrix")
    live_id = seal.get("live_matrix_content_id")
    if live_id not in (None, "") and live_id != m.content_id:
        raise MatrixV2Error(
            "seal live_matrix_content_id does not match live matrix content_id"
        )
    summary = seal.get("summary")
    if isinstance(summary, Mapping):
        if summary.get("hard_zero_floors_clear") is not True:
            raise HardZeroFloorError("seal summary hard-zero floor is not clear")
        if summary.get("sparse") is not True:
            raise MatrixV2Error("seal summary must declare sparse matrix")
        sealed_domains = summary.get("domain_ids")
        if isinstance(sealed_domains, list) and sealed_domains:
            live_domains = sorted({cell.domain_id for cell in m.cells})
            if sealed_domains != live_domains:
                raise MatrixV2Error("seal domain_ids disagree with live matrix")
    return m


DEFAULT_REACHABLE_CONFORMANCE_MATRIX: Final = (
    build_default_reachable_conformance_matrix()
)
DEFAULT_LOGIC_CONFORMANCE_REPORT_V2: Final = build_logic_conformance_report_v2(
    DEFAULT_REACHABLE_CONFORMANCE_MATRIX
)


def main() -> int:
    """CLI: write the durable seal under the datasets tree."""

    matrix = write_reachable_matrix_seal()
    print(matrix.content_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CELL_SCHEMA",
    "CellDisposition",
    "DEFAULT_LOGIC_CONFORMANCE_REPORT_V2",
    "DEFAULT_REACHABLE_CONFORMANCE_MATRIX",
    "DEFAULT_SEAL_RELATIVE_PATH",
    "DomainSourceKind",
    "ExecutionDisposition",
    "GOAL_ID",
    "HARD_ZERO_FLOOR_NAMES",
    "HARD_ZERO_FLOORS_SCHEMA",
    "HardZeroFloorError",
    "HardZeroFloors",
    "LOGIC_CONFORMANCE_REPORT_INTERFACE",
    "LOGIC_CONFORMANCE_REPORT_SCHEMA",
    "LogicConformanceReport",
    "LogicConformanceReportV2",
    "MATERIALIZATION_TARGET",
    "MATRIX_VERSION",
    "MatrixV2Error",
    "PROGRAM_ID",
    "PRODUCER_ID",
    "REACHABLE_CONFORMANCE_MATRIX_INTERFACE",
    "REACHABLE_CONFORMANCE_MATRIX_SCHEMA",
    "REQUIRED_EVIDENCE_SUBSET",
    "REQUIRED_JOIN_DIMENSIONS",
    "REPORT_VERSION",
    "ReachableConformanceCell",
    "ReachableConformanceMatrix",
    "ReplayDisposition",
    "TASK_ID",
    "UnexplainedReachableGapError",
    "assert_matrix_acceptance",
    "build_default_reachable_conformance_matrix",
    "build_logic_conformance_report_v2",
    "build_reachable_conformance_matrix",
    "cell_id",
    "default_datasets_repo_root",
    "default_seal_path",
    "ensure_seal_matches_live",
    "evaluate_hard_zero_floors",
    "load_reachable_matrix_seal",
    "main",
    "write_reachable_matrix_seal",
]
