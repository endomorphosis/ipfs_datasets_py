"""Deterministic requirement discovery and test/property selection (IPS-014).

Datasets semantic authority for bounded source/test/property discovery.
Discovery mints stable logical proof-unit IDs, applies a selector policy to
determine the required set, and treats incomplete import/coverage frontiers as
explicit broadening constraints that never narrow requirements.

Rules:

* ``proof_unit_id`` is the stable logical identity CID over repository ID, unit
  kind, canonical locator/selector or property ID, and the proof-unit identity
  schema.  It excludes source closure, repository state, proof object, status,
  and logical epoch (plan §6.1);
* renamed or deleted locators become explicit remove plus add;
* selector policy determines which discovered candidates are required;
* unknown / truncated frontiers cannot narrow the required set;
* imports have no side effects (CID minting reuses identity helpers lazily).

Interfaces: ``ProofUnitSelector``, ``mint_logical_proof_unit_id``,
``discover_requirements``, ``build_proof_dependency_graph``,
``build_verification_requirement_manifest`` (re-export).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .dependency_graph import (
    DEPENDENCY_GRAPH_SCHEMA_VERSION,
    DependencyEdgeType,
    DependencyGraphError,
    DependencyNodeKind,
    ProofDependencyGraph,
    mint_reason_cid,
)
from .evidence import EvidenceClassError, ProofUnitKind, parse_proof_unit_kind
from .identity import (
    ABSENCE_TOKEN,
    CANONICALIZATION_VERSION,
    SECRET_AND_NONDETERMINISTIC_FIELDS,
    IdentityError,
    PropertyIdentity,
    SourceSymbolIdentity,
    TestSelectorIdentity,
    canonical_cid,
    canonicalize_relative_path,
    validate_profile_cid,
)
from .manifest import (
    ManifestError,
    RequiredUnitDescriptor,
    UnitRemovalAuthorization,
    VerificationPolicy,
    VerificationRequirementManifest,
    build_verification_requirement_manifest,
    sample_verification_policy,
)

DISCOVERY_SUBSET: Final[str] = "ips/requirement-discovery@1"
DISCOVERY_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/discovery"
)
SCHEMA_MAJOR: Final[int] = 1
DISCOVERY_SCHEMA_VERSION: Final[str] = f"discovery@{SCHEMA_MAJOR}"
LOGICAL_UNIT_IDENTITY_SCHEMA: Final[str] = (
    f"{DISCOVERY_NAMESPACE}/logical-proof-unit-identity@{SCHEMA_MAJOR}"
)
DISCOVERED_CANDIDATE_SCHEMA: Final[str] = (
    f"{DISCOVERY_NAMESPACE}/discovered-candidate@{SCHEMA_MAJOR}"
)
SELECTOR_SCHEMA: Final[str] = (
    f"{DISCOVERY_NAMESPACE}/proof-unit-selector@{SCHEMA_MAJOR}"
)
DISCOVERY_RESULT_SCHEMA: Final[str] = (
    f"{DISCOVERY_NAMESPACE}/requirement-discovery-result@{SCHEMA_MAJOR}"
)
UNIT_DESCRIPTOR_PAYLOAD_SCHEMA: Final[str] = (
    f"{DISCOVERY_NAMESPACE}/unit-descriptor-payload@{SCHEMA_MAJOR}"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_CANDIDATES: Final[int] = 1 << 18
MAX_FRONTIERS: Final[int] = 1 << 16
MAX_PATH_PREFIXES: Final[int] = 1 << 12

# Closed selection sources admitted into RequiredUnitDescriptor.
DISCOVERY_SELECTION_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "selected_test",
        "selected_property",
        "selected_unit",
        "policy_selected",
        "discovery_selected",
    }
)

# Closed frontier kinds.  Incomplete frontiers broaden, never narrow.
FRONTIER_KINDS: Final[tuple[str, ...]] = (
    "import",
    "coverage",
    "symbol_resolution",
    "test_collection",
    "property_collection",
    "aggregate_membership",
)

# Closed locator kinds aligned with plan §6.1 granularity.
LOCATOR_KINDS: Final[tuple[str, ...]] = (
    "module_symbol",
    "pytest_node",
    "property_obligation",
    "direct_computation",
    "release_invariant",
    "receipt_aggregate",
)

# Default kind -> selection_source mapping.
_KIND_SELECTION_SOURCE: Final[dict[str, str]] = {
    ProofUnitKind.STATIC_ANALYSIS.value: "discovery_selected",
    ProofUnitKind.TYPE_CHECK.value: "discovery_selected",
    ProofUnitKind.UNIT_TEST.value: "selected_test",
    ProofUnitKind.INTEGRATION_TEST.value: "selected_test",
    ProofUnitKind.PROPERTY_TEST.value: "selected_test",
    ProofUnitKind.FORMAL_OBLIGATION.value: "selected_property",
    ProofUnitKind.DIRECT_ZK_COMPUTATION.value: "selected_unit",
    ProofUnitKind.RECEIPT_AGGREGATION.value: "policy_selected",
    ProofUnitKind.RELEASE_INVARIANT.value: "policy_selected",
}

# Default risk class by unit kind.
_KIND_RISK_CLASS: Final[dict[str, str]] = {
    ProofUnitKind.STATIC_ANALYSIS.value: "medium",
    ProofUnitKind.TYPE_CHECK.value: "medium",
    ProofUnitKind.UNIT_TEST.value: "high",
    ProofUnitKind.INTEGRATION_TEST.value: "high",
    ProofUnitKind.PROPERTY_TEST.value: "high",
    ProofUnitKind.FORMAL_OBLIGATION.value: "high",
    ProofUnitKind.DIRECT_ZK_COMPUTATION.value: "high",
    ProofUnitKind.RECEIPT_AGGREGATION.value: "high",
    ProofUnitKind.RELEASE_INVARIANT.value: "high",
}


class DiscoveryError(ValueError):
    """Requirement discovery or selector contract violation."""


class FrontierKind(str, Enum):
    """Closed discovery frontier kinds."""

    IMPORT = "import"
    COVERAGE = "coverage"
    SYMBOL_RESOLUTION = "symbol_resolution"
    TEST_COLLECTION = "test_collection"
    PROPERTY_COLLECTION = "property_collection"
    AGGREGATE_MEMBERSHIP = "aggregate_membership"


class LocatorKind(str, Enum):
    """Closed locator kinds for stable logical proof-unit identity."""

    MODULE_SYMBOL = "module_symbol"
    PYTEST_NODE = "pytest_node"
    PROPERTY_OBLIGATION = "property_obligation"
    DIRECT_COMPUTATION = "direct_computation"
    RELEASE_INVARIANT = "release_invariant"
    RECEIPT_AGGREGATE = "receipt_aggregate"


def closed_frontier_kinds() -> frozenset[str]:
    return frozenset(FRONTIER_KINDS)


def closed_locator_kinds() -> frozenset[str]:
    return frozenset(LOCATOR_KINDS)


def closed_discovery_selection_sources() -> frozenset[str]:
    return frozenset(DISCOVERY_SELECTION_SOURCES)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError(f"{field} must be a non-empty string or {ABSENCE_TOKEN}")
    text = value.strip()
    if text != value:
        raise DiscoveryError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise DiscoveryError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    text = _require_text(value, field, allow_absence=False)
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise DiscoveryError(f"{field}: {exc}") from exc


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise DiscoveryError(f"{field} must be a boolean")
    return value


def _require_nonneg_int(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise DiscoveryError(f"{field} must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise DiscoveryError(f"{field} is out of bounds")
    return value


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    leaked = set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS
    if leaked:
        raise DiscoveryError(
            f"secret or nondeterministic fields are forbidden: {sorted(leaked)}"
        )


def _require_sorted_unique_strings(
    value: Any, field: str, *, allow_absence: bool = True
) -> tuple[str, ...]:
    if allow_absence and value == ABSENCE_TOKEN:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DiscoveryError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_text(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise DiscoveryError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise DiscoveryError(f"{field} must not contain duplicates")
    return items


def _parse_kind(value: Any) -> ProofUnitKind:
    try:
        return parse_proof_unit_kind(value)
    except EvidenceClassError as exc:
        raise DiscoveryError(str(exc)) from exc


def parse_frontier_kind(value: Any) -> FrontierKind:
    if isinstance(value, FrontierKind):
        return value
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError("frontier kind must be a non-empty closed string")
    text = value.strip()
    try:
        return FrontierKind(text)
    except ValueError as exc:
        raise DiscoveryError(
            f"unknown FrontierKind {value!r}; closed set is {list(FRONTIER_KINDS)}"
        ) from exc


def parse_locator_kind(value: Any) -> LocatorKind:
    if isinstance(value, LocatorKind):
        return value
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError("locator kind must be a non-empty closed string")
    text = value.strip()
    try:
        return LocatorKind(text)
    except ValueError as exc:
        raise DiscoveryError(
            f"unknown LocatorKind {value!r}; closed set is {list(LOCATOR_KINDS)}"
        ) from exc


def _mint_cid(payload: Mapping[str, Any]) -> str:
    try:
        return canonical_cid(dict(payload))
    except IdentityError as exc:
        raise DiscoveryError(str(exc)) from exc


def _seq_canonical(values: Sequence[str]) -> list[str] | str:
    return list(values) if values else ABSENCE_TOKEN


# ---------------------------------------------------------------------------
# Logical proof-unit identity (stable across context changes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicalProofUnitIdentity:
    """Stable logical identity for one proof unit (plan §6.1).

    Commits only to repository ID, unit kind, canonical locator, and the
    identity schema.  Source closure, repository state, proof object, terminal
    status, and logical epoch are deliberately excluded so context mutations
    preserve the logical ID.
    """

    repository_id: str
    proof_unit_kind: ProofUnitKind
    locator_kind: LocatorKind
    locator_id: str
    identity_schema: str = LOGICAL_UNIT_IDENTITY_SCHEMA
    canonicalization_version: str = CANONICALIZATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_text(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "proof_unit_kind", _parse_kind(self.proof_unit_kind)
        )
        object.__setattr__(
            self, "locator_kind", parse_locator_kind(self.locator_kind)
        )
        object.__setattr__(
            self, "locator_id", _require_text(self.locator_id, "locator_id")
        )
        object.__setattr__(
            self,
            "identity_schema",
            _require_text(self.identity_schema, "identity_schema"),
        )
        if self.identity_schema != LOGICAL_UNIT_IDENTITY_SCHEMA:
            raise DiscoveryError(
                f"logical identity schema must be {LOGICAL_UNIT_IDENTITY_SCHEMA}"
            )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(
                self.canonicalization_version, "canonicalization_version"
            ),
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.identity_schema,
            "discovery_subset": DISCOVERY_SUBSET,
            "canonicalization_version": self.canonicalization_version,
            "repository_id": self.repository_id,
            "proof_unit_kind": self.proof_unit_kind.value,
            "locator_kind": self.locator_kind.value,
            "locator_id": self.locator_id,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def logical_id(self) -> str:
        """Return the stable content-addressed logical proof_unit_id."""

        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> LogicalProofUnitIdentity:
        if not isinstance(payload, Mapping):
            raise DiscoveryError("LogicalProofUnitIdentity payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            proof_unit_kind=payload.get("proof_unit_kind") or "",
            locator_kind=payload.get("locator_kind") or "",
            locator_id=str(payload.get("locator_id") or ""),
            identity_schema=str(
                payload.get("schema")
                or payload.get("identity_schema")
                or LOGICAL_UNIT_IDENTITY_SCHEMA
            ),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )


def mint_logical_proof_unit_id(
    *,
    repository_id: str,
    proof_unit_kind: ProofUnitKind | str,
    locator_kind: LocatorKind | str,
    locator_id: str,
) -> str:
    """Mint a stable logical ``proof_unit_id`` that survives context changes."""

    return LogicalProofUnitIdentity(
        repository_id=repository_id,
        proof_unit_kind=proof_unit_kind,
        locator_kind=locator_kind,
        locator_id=locator_id,
    ).logical_id()


def locator_id_for_symbol(symbol: SourceSymbolIdentity) -> str:
    """Canonical locator for a module/symbol candidate."""

    if not isinstance(symbol, SourceSymbolIdentity):
        raise DiscoveryError("symbol must be a SourceSymbolIdentity")
    return symbol.identity_cid()


def locator_id_for_test(test: TestSelectorIdentity) -> str:
    """Canonical locator for a pytest node + parameter case."""

    if not isinstance(test, TestSelectorIdentity):
        raise DiscoveryError("test must be a TestSelectorIdentity")
    return test.identity_cid()


def locator_id_for_property(prop: PropertyIdentity) -> str:
    """Canonical locator for a formal property/obligation."""

    if not isinstance(prop, PropertyIdentity):
        raise DiscoveryError("prop must be a PropertyIdentity")
    return prop.identity_cid()


# ---------------------------------------------------------------------------
# Discovered candidates and frontiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveredCandidate:
    """One discovered proof-unit candidate at plan §6.1 granularity.

    The logical ``proof_unit_id`` is derived solely from repository, kind, and
    locator.  Mutable context fields (source root, repository state, epoch,
    descriptor payload) never enter the logical ID.
    """

    repository_id: str
    proof_unit_kind: ProofUnitKind
    locator_kind: LocatorKind
    locator_id: str
    risk_class: str = "high"
    selection_source: str = "discovery_selected"
    source_root_cid: str = ABSENCE_TOKEN
    repository_state_cid: str = ABSENCE_TOKEN
    label: str = ABSENCE_TOKEN
    dependency_node_ids: tuple[str, ...] = ()
    schema: str = DISCOVERED_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_text(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "proof_unit_kind", _parse_kind(self.proof_unit_kind)
        )
        object.__setattr__(
            self, "locator_kind", parse_locator_kind(self.locator_kind)
        )
        object.__setattr__(
            self, "locator_id", _require_text(self.locator_id, "locator_id")
        )
        object.__setattr__(
            self, "risk_class", _require_text(self.risk_class, "risk_class")
        )
        source = _require_text(self.selection_source, "selection_source")
        if source not in DISCOVERY_SELECTION_SOURCES:
            raise DiscoveryError(
                f"unknown selection_source {source!r}; closed set is "
                f"{sorted(DISCOVERY_SELECTION_SOURCES)}"
            )
        object.__setattr__(self, "selection_source", source)
        object.__setattr__(
            self,
            "source_root_cid",
            _require_cid(self.source_root_cid, "source_root_cid", allow_absence=True),
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _require_cid(
                self.repository_state_cid,
                "repository_state_cid",
                allow_absence=True,
            ),
        )
        if self.label == ABSENCE_TOKEN:
            object.__setattr__(self, "label", ABSENCE_TOKEN)
        else:
            object.__setattr__(self, "label", _require_text(self.label, "label"))
        deps = _require_sorted_unique_strings(
            self.dependency_node_ids, "dependency_node_ids"
        )
        object.__setattr__(self, "dependency_node_ids", deps)
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != DISCOVERED_CANDIDATE_SCHEMA:
            raise DiscoveryError(
                f"discovered candidate schema must be {DISCOVERED_CANDIDATE_SCHEMA}"
            )

    @property
    def proof_unit_id(self) -> str:
        return mint_logical_proof_unit_id(
            repository_id=self.repository_id,
            proof_unit_kind=self.proof_unit_kind,
            locator_kind=self.locator_kind,
            locator_id=self.locator_id,
        )

    def logical_identity(self) -> LogicalProofUnitIdentity:
        return LogicalProofUnitIdentity(
            repository_id=self.repository_id,
            proof_unit_kind=self.proof_unit_kind,
            locator_kind=self.locator_kind,
            locator_id=self.locator_id,
        )

    def descriptor_payload(self) -> dict[str, Any]:
        """Context-sensitive descriptor payload (not part of logical ID)."""

        return {
            "schema": UNIT_DESCRIPTOR_PAYLOAD_SCHEMA,
            "proof_unit_id": self.proof_unit_id,
            "proof_unit_kind": self.proof_unit_kind.value,
            "locator_kind": self.locator_kind.value,
            "locator_id": self.locator_id,
            "source_root_cid": self.source_root_cid,
            "repository_state_cid": self.repository_state_cid,
            "label": self.label,
            "dependency_node_ids": _seq_canonical(self.dependency_node_ids),
            "risk_class": self.risk_class,
            "selection_source": self.selection_source,
            "typed_absence": ABSENCE_TOKEN,
        }

    def unit_descriptor_cid(self) -> str:
        return _mint_cid(self.descriptor_payload())

    def to_required_unit(self) -> RequiredUnitDescriptor:
        return RequiredUnitDescriptor.from_selected(
            proof_unit_id=self.proof_unit_id,
            unit_descriptor_cid=self.unit_descriptor_cid(),
            proof_unit_kind=self.proof_unit_kind,
            selection_source=self.selection_source,
            risk_class=self.risk_class,
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "discovery_subset": DISCOVERY_SUBSET,
            "repository_id": self.repository_id,
            "proof_unit_kind": self.proof_unit_kind.value,
            "locator_kind": self.locator_kind.value,
            "locator_id": self.locator_id,
            "proof_unit_id": self.proof_unit_id,
            "risk_class": self.risk_class,
            "selection_source": self.selection_source,
            "source_root_cid": self.source_root_cid,
            "repository_state_cid": self.repository_state_cid,
            "label": self.label,
            "dependency_node_ids": _seq_canonical(self.dependency_node_ids),
            "typed_absence": ABSENCE_TOKEN,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> DiscoveredCandidate:
        if not isinstance(payload, Mapping):
            raise DiscoveryError("DiscoveredCandidate payload must be a mapping")
        _reject_secret_fields(payload)
        deps = payload.get("dependency_node_ids", ABSENCE_TOKEN)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            proof_unit_kind=payload.get("proof_unit_kind") or "",
            locator_kind=payload.get("locator_kind") or "",
            locator_id=str(payload.get("locator_id") or ""),
            risk_class=str(payload.get("risk_class") or "high"),
            selection_source=str(
                payload.get("selection_source") or "discovery_selected"
            ),
            source_root_cid=payload.get("source_root_cid", ABSENCE_TOKEN),
            repository_state_cid=payload.get(
                "repository_state_cid", ABSENCE_TOKEN
            ),
            label=payload.get("label", ABSENCE_TOKEN),
            dependency_node_ids=() if deps == ABSENCE_TOKEN else tuple(deps or ()),
            schema=str(payload.get("schema") or DISCOVERED_CANDIDATE_SCHEMA),
        )

    def with_context(
        self,
        *,
        source_root_cid: str | None = None,
        repository_state_cid: str | None = None,
    ) -> DiscoveredCandidate:
        """Return a copy with mutated context fields (logical ID unchanged)."""

        return DiscoveredCandidate(
            repository_id=self.repository_id,
            proof_unit_kind=self.proof_unit_kind,
            locator_kind=self.locator_kind,
            locator_id=self.locator_id,
            risk_class=self.risk_class,
            selection_source=self.selection_source,
            source_root_cid=(
                self.source_root_cid if source_root_cid is None else source_root_cid
            ),
            repository_state_cid=(
                self.repository_state_cid
                if repository_state_cid is None
                else repository_state_cid
            ),
            label=self.label,
            dependency_node_ids=self.dependency_node_ids,
        )


@dataclass(frozen=True, slots=True)
class DiscoveryFrontier:
    """One explicit import/coverage/collection frontier.

    Incomplete frontiers broaden selection: they never authorize dropping a
    previously required unit, and discovery reports ``complete=False``.
    """

    frontier_id: str
    kind: FrontierKind
    complete: bool
    scope_path: str = ABSENCE_TOKEN
    reason: str = ABSENCE_TOKEN

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frontier_id",
            _require_text(self.frontier_id, "frontier_id"),
        )
        object.__setattr__(self, "kind", parse_frontier_kind(self.kind))
        object.__setattr__(
            self, "complete", _require_bool(self.complete, "complete")
        )
        if self.scope_path == ABSENCE_TOKEN:
            object.__setattr__(self, "scope_path", ABSENCE_TOKEN)
        else:
            try:
                object.__setattr__(
                    self,
                    "scope_path",
                    canonicalize_relative_path(
                        self.scope_path, field="scope_path"
                    ),
                )
            except IdentityError as exc:
                raise DiscoveryError(str(exc)) from exc
        if self.reason == ABSENCE_TOKEN:
            object.__setattr__(self, "reason", ABSENCE_TOKEN)
        else:
            object.__setattr__(
                self, "reason", _require_text(self.reason, "reason")
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "frontier_id": self.frontier_id,
            "kind": self.kind.value,
            "complete": self.complete,
            "scope_path": self.scope_path,
            "reason": self.reason,
            "typed_absence": ABSENCE_TOKEN,
        }

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> DiscoveryFrontier:
        if not isinstance(payload, Mapping):
            raise DiscoveryError("DiscoveryFrontier payload must be a mapping")
        return cls(
            frontier_id=str(payload.get("frontier_id") or ""),
            kind=payload.get("kind") or "",
            complete=payload.get("complete"),
            scope_path=payload.get("scope_path", ABSENCE_TOKEN),
            reason=payload.get("reason", ABSENCE_TOKEN),
        )


# ---------------------------------------------------------------------------
# Selector policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofUnitSelector:
    """Deterministic policy that decides which discovered candidates are required.

    Selection is fail-closed and order-independent:

    * an empty ``included_kinds`` means all closed kinds are eligible;
    * ``excluded_kinds`` always wins over include;
    * path prefixes match candidate labels (module/test paths);
    * explicit include/exclude unit ID sets override path/kind filters;
    * when ``require_all_selected_kinds`` is true every admitted kind that has
      at least one candidate must contribute at least one required unit.
    """

    selector_id: str
    included_kinds: tuple[str, ...] = ()
    excluded_kinds: tuple[str, ...] = ()
    include_path_prefixes: tuple[str, ...] = ()
    exclude_path_prefixes: tuple[str, ...] = ()
    include_unit_ids: tuple[str, ...] = ()
    exclude_unit_ids: tuple[str, ...] = ()
    require_all_selected_kinds: bool = False
    include_release_invariants: bool = True
    include_receipt_aggregates: bool = True
    schema: str = SELECTOR_SCHEMA
    canonicalization_version: str = CANONICALIZATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "selector_id", _require_text(self.selector_id, "selector_id")
        )
        included = _require_sorted_unique_strings(
            self.included_kinds, "included_kinds"
        )
        for kind in included:
            _parse_kind(kind)
        object.__setattr__(self, "included_kinds", included)
        excluded = _require_sorted_unique_strings(
            self.excluded_kinds, "excluded_kinds"
        )
        for kind in excluded:
            _parse_kind(kind)
        object.__setattr__(self, "excluded_kinds", excluded)
        include_paths = _require_sorted_unique_strings(
            self.include_path_prefixes, "include_path_prefixes"
        )
        if len(include_paths) > MAX_PATH_PREFIXES:
            raise DiscoveryError(
                f"include_path_prefixes exceeds MAX_PATH_PREFIXES={MAX_PATH_PREFIXES}"
            )
        for path in include_paths:
            try:
                canonicalize_relative_path(path, field="include_path_prefixes")
            except IdentityError as exc:
                raise DiscoveryError(str(exc)) from exc
        object.__setattr__(self, "include_path_prefixes", include_paths)
        exclude_paths = _require_sorted_unique_strings(
            self.exclude_path_prefixes, "exclude_path_prefixes"
        )
        if len(exclude_paths) > MAX_PATH_PREFIXES:
            raise DiscoveryError(
                f"exclude_path_prefixes exceeds MAX_PATH_PREFIXES={MAX_PATH_PREFIXES}"
            )
        for path in exclude_paths:
            try:
                canonicalize_relative_path(path, field="exclude_path_prefixes")
            except IdentityError as exc:
                raise DiscoveryError(str(exc)) from exc
        object.__setattr__(self, "exclude_path_prefixes", exclude_paths)
        object.__setattr__(
            self,
            "include_unit_ids",
            _require_sorted_unique_strings(
                self.include_unit_ids, "include_unit_ids"
            ),
        )
        object.__setattr__(
            self,
            "exclude_unit_ids",
            _require_sorted_unique_strings(
                self.exclude_unit_ids, "exclude_unit_ids"
            ),
        )
        object.__setattr__(
            self,
            "require_all_selected_kinds",
            _require_bool(
                self.require_all_selected_kinds, "require_all_selected_kinds"
            ),
        )
        object.__setattr__(
            self,
            "include_release_invariants",
            _require_bool(
                self.include_release_invariants, "include_release_invariants"
            ),
        )
        object.__setattr__(
            self,
            "include_receipt_aggregates",
            _require_bool(
                self.include_receipt_aggregates, "include_receipt_aggregates"
            ),
        )
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != SELECTOR_SCHEMA:
            raise DiscoveryError(f"selector schema must be {SELECTOR_SCHEMA}")
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(
                self.canonicalization_version, "canonicalization_version"
            ),
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "discovery_subset": DISCOVERY_SUBSET,
            "selector_id": self.selector_id,
            "included_kinds": _seq_canonical(self.included_kinds),
            "excluded_kinds": _seq_canonical(self.excluded_kinds),
            "include_path_prefixes": _seq_canonical(self.include_path_prefixes),
            "exclude_path_prefixes": _seq_canonical(self.exclude_path_prefixes),
            "include_unit_ids": _seq_canonical(self.include_unit_ids),
            "exclude_unit_ids": _seq_canonical(self.exclude_unit_ids),
            "require_all_selected_kinds": self.require_all_selected_kinds,
            "include_release_invariants": self.include_release_invariants,
            "include_receipt_aggregates": self.include_receipt_aggregates,
            "canonicalization_version": self.canonicalization_version,
            "typed_absence": ABSENCE_TOKEN,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def selector_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ProofUnitSelector:
        if not isinstance(payload, Mapping):
            raise DiscoveryError("ProofUnitSelector payload must be a mapping")
        _reject_secret_fields(payload)

        def _seq(key: str) -> tuple[str, ...]:
            raw = payload.get(key, ABSENCE_TOKEN)
            if raw == ABSENCE_TOKEN or raw is None:
                return ()
            return tuple(raw)

        return cls(
            selector_id=str(payload.get("selector_id") or ""),
            included_kinds=_seq("included_kinds"),
            excluded_kinds=_seq("excluded_kinds"),
            include_path_prefixes=_seq("include_path_prefixes"),
            exclude_path_prefixes=_seq("exclude_path_prefixes"),
            include_unit_ids=_seq("include_unit_ids"),
            exclude_unit_ids=_seq("exclude_unit_ids"),
            require_all_selected_kinds=payload.get(
                "require_all_selected_kinds", False
            ),
            include_release_invariants=payload.get(
                "include_release_invariants", True
            ),
            include_receipt_aggregates=payload.get(
                "include_receipt_aggregates", True
            ),
            schema=str(payload.get("schema") or SELECTOR_SCHEMA),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )

    def admits(self, candidate: DiscoveredCandidate) -> bool:
        """Return True when the selector policy requires this candidate."""

        if not isinstance(candidate, DiscoveredCandidate):
            raise DiscoveryError("candidate must be a DiscoveredCandidate")
        unit_id = candidate.proof_unit_id
        if unit_id in self.exclude_unit_ids:
            return False
        if unit_id in self.include_unit_ids:
            return True

        kind = candidate.proof_unit_kind.value
        if kind in self.excluded_kinds:
            return False
        if self.included_kinds and kind not in self.included_kinds:
            return False
        if (
            kind == ProofUnitKind.RELEASE_INVARIANT.value
            and not self.include_release_invariants
        ):
            return False
        if (
            kind == ProofUnitKind.RECEIPT_AGGREGATION.value
            and not self.include_receipt_aggregates
        ):
            return False

        label = candidate.label if candidate.label != ABSENCE_TOKEN else ""
        if self.exclude_path_prefixes and label:
            for prefix in self.exclude_path_prefixes:
                if label == prefix or label.startswith(prefix + "/"):
                    return False
        if self.include_path_prefixes:
            if not label:
                return False
            if not any(
                label == prefix or label.startswith(prefix + "/")
                for prefix in self.include_path_prefixes
            ):
                return False
        return True

    def select(
        self, candidates: Sequence[DiscoveredCandidate]
    ) -> tuple[DiscoveredCandidate, ...]:
        """Return the deterministically ordered selected candidate set."""

        if not isinstance(candidates, Sequence) or isinstance(
            candidates, (str, bytes)
        ):
            raise DiscoveryError("candidates must be a sequence")
        if len(candidates) > MAX_CANDIDATES:
            raise DiscoveryError(
                f"candidates exceeds MAX_CANDIDATES={MAX_CANDIDATES}"
            )
        selected = [c for c in candidates if self.admits(c)]
        # Deterministic order by logical proof_unit_id.
        selected.sort(key=lambda item: item.proof_unit_id)
        # Deduplicate by logical ID (same locator/kind/repo).
        seen: set[str] = set()
        unique: list[DiscoveredCandidate] = []
        for candidate in selected:
            unit_id = candidate.proof_unit_id
            if unit_id in seen:
                continue
            seen.add(unit_id)
            unique.append(candidate)
        if self.require_all_selected_kinds:
            admitted_kinds = self.included_kinds or tuple(
                sorted({c.proof_unit_kind.value for c in candidates})
            )
            present_kinds = {c.proof_unit_kind.value for c in unique}
            missing = sorted(
                kind
                for kind in admitted_kinds
                if kind not in self.excluded_kinds
                and any(c.proof_unit_kind.value == kind for c in candidates)
                and kind not in present_kinds
            )
            if missing:
                raise DiscoveryError(
                    f"selector require_all_selected_kinds missing kinds: {missing}"
                )
        return tuple(unique)


# ---------------------------------------------------------------------------
# Discovery result and set diff (rename/delete -> remove/add)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoverySetDiff:
    """Diff of two discovered required sets by stable logical ID.

    A rename is never a mutate-in-place: the old locator's logical ID is
    removed and the new locator's logical ID is added.
    """

    added_unit_ids: tuple[str, ...]
    removed_unit_ids: tuple[str, ...]
    retained_unit_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "added_unit_ids",
            _require_sorted_unique_strings(self.added_unit_ids, "added_unit_ids"),
        )
        object.__setattr__(
            self,
            "removed_unit_ids",
            _require_sorted_unique_strings(
                self.removed_unit_ids, "removed_unit_ids"
            ),
        )
        object.__setattr__(
            self,
            "retained_unit_ids",
            _require_sorted_unique_strings(
                self.retained_unit_ids, "retained_unit_ids"
            ),
        )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "added_unit_ids": list(self.added_unit_ids),
            "removed_unit_ids": list(self.removed_unit_ids),
            "retained_unit_ids": list(self.retained_unit_ids),
        }


def diff_discovered_unit_ids(
    previous_unit_ids: Sequence[str],
    current_unit_ids: Sequence[str],
) -> DiscoverySetDiff:
    """Classify unit-set changes as add / remove / retain by logical ID."""

    previous = set(_require_text(item, "previous_unit_ids") for item in previous_unit_ids)
    current = set(_require_text(item, "current_unit_ids") for item in current_unit_ids)
    return DiscoverySetDiff(
        added_unit_ids=tuple(sorted(current - previous)),
        removed_unit_ids=tuple(sorted(previous - current)),
        retained_unit_ids=tuple(sorted(previous & current)),
    )


@dataclass(frozen=True, slots=True)
class RequirementDiscoveryResult:
    """Deterministic outcome of requirement discovery and selection."""

    repository_id: str
    selector_cid: str
    required_units: tuple[DiscoveredCandidate, ...]
    frontiers: tuple[DiscoveryFrontier, ...]
    complete: bool
    discovery_schema_version: str = DISCOVERY_SCHEMA_VERSION
    schema: str = DISCOVERY_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_text(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "selector_cid", _require_cid(self.selector_cid, "selector_cid")
        )
        if not isinstance(self.required_units, Sequence) or isinstance(
            self.required_units, (str, bytes)
        ):
            raise DiscoveryError("required_units must be a sequence")
        units = tuple(self.required_units)
        for unit in units:
            if not isinstance(unit, DiscoveredCandidate):
                raise DiscoveryError(
                    "required_units entries must be DiscoveredCandidate"
                )
            if unit.repository_id != self.repository_id:
                raise DiscoveryError(
                    "required unit repository_id must match discovery result"
                )
        ids = [unit.proof_unit_id for unit in units]
        if list(ids) != sorted(ids):
            raise DiscoveryError(
                "required_units must be canonically sorted by proof_unit_id"
            )
        if len(set(ids)) != len(ids):
            raise DiscoveryError(
                "required_units must not contain duplicate proof_unit_id"
            )
        object.__setattr__(self, "required_units", units)
        if not isinstance(self.frontiers, Sequence) or isinstance(
            self.frontiers, (str, bytes)
        ):
            raise DiscoveryError("frontiers must be a sequence")
        frontiers = tuple(self.frontiers)
        if len(frontiers) > MAX_FRONTIERS:
            raise DiscoveryError(
                f"frontiers exceeds MAX_FRONTIERS={MAX_FRONTIERS}"
            )
        frontier_ids = [item.frontier_id for item in frontiers]
        if list(frontier_ids) != sorted(frontier_ids):
            raise DiscoveryError(
                "frontiers must be canonically sorted by frontier_id"
            )
        if len(set(frontier_ids)) != len(frontier_ids):
            raise DiscoveryError("frontiers must not contain duplicate frontier_id")
        object.__setattr__(self, "frontiers", frontiers)
        complete = _require_bool(self.complete, "complete")
        # Incomplete frontiers force complete=False.
        if any(not item.complete for item in frontiers) and complete:
            raise DiscoveryError(
                "unknown or truncated frontiers cannot report complete=true"
            )
        object.__setattr__(self, "complete", complete)
        object.__setattr__(
            self,
            "discovery_schema_version",
            _require_text(
                self.discovery_schema_version, "discovery_schema_version"
            ),
        )
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != DISCOVERY_RESULT_SCHEMA:
            raise DiscoveryError(
                f"discovery result schema must be {DISCOVERY_RESULT_SCHEMA}"
            )

    @property
    def required_unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.proof_unit_id for unit in self.required_units)

    def to_required_descriptors(self) -> tuple[RequiredUnitDescriptor, ...]:
        return tuple(unit.to_required_unit() for unit in self.required_units)

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "discovery_subset": DISCOVERY_SUBSET,
            "discovery_schema_version": self.discovery_schema_version,
            "repository_id": self.repository_id,
            "selector_cid": self.selector_cid,
            "required_units": [unit.to_canonical() for unit in self.required_units],
            "required_unit_ids": list(self.required_unit_ids),
            "frontiers": [item.to_canonical() for item in self.frontiers],
            "complete": self.complete,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def result_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(
        cls, payload: Mapping[str, Any]
    ) -> RequirementDiscoveryResult:
        if not isinstance(payload, Mapping):
            raise DiscoveryError(
                "RequirementDiscoveryResult payload must be a mapping"
            )
        _reject_secret_fields(payload)
        raw_units = payload.get("required_units") or ()
        units = tuple(
            DiscoveredCandidate.from_canonical(item) for item in raw_units
        )
        raw_frontiers = payload.get("frontiers") or ()
        frontiers = tuple(
            DiscoveryFrontier.from_canonical(item) for item in raw_frontiers
        )
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            selector_cid=str(payload.get("selector_cid") or ""),
            required_units=units,
            frontiers=frontiers,
            complete=payload.get("complete"),
            discovery_schema_version=str(
                payload.get("discovery_schema_version") or DISCOVERY_SCHEMA_VERSION
            ),
            schema=str(payload.get("schema") or DISCOVERY_RESULT_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Discovery pipeline
# ---------------------------------------------------------------------------


def _default_selection_source(kind: ProofUnitKind) -> str:
    return _KIND_SELECTION_SOURCE.get(kind.value, "discovery_selected")


def _default_risk_class(kind: ProofUnitKind) -> str:
    return _KIND_RISK_CLASS.get(kind.value, "high")


def candidate_from_symbol(
    symbol: SourceSymbolIdentity,
    *,
    proof_unit_kind: ProofUnitKind | str = ProofUnitKind.STATIC_ANALYSIS,
    source_root_cid: str = ABSENCE_TOKEN,
    repository_state_cid: str = ABSENCE_TOKEN,
    risk_class: str | None = None,
) -> DiscoveredCandidate:
    """Build a module/symbol-granularity candidate (static analysis / type check)."""

    kind = _parse_kind(proof_unit_kind)
    if kind not in {ProofUnitKind.STATIC_ANALYSIS, ProofUnitKind.TYPE_CHECK}:
        raise DiscoveryError(
            "symbol candidates admit only static_analysis or type_check kinds"
        )
    return DiscoveredCandidate(
        repository_id=symbol.repository_id,
        proof_unit_kind=kind,
        locator_kind=LocatorKind.MODULE_SYMBOL,
        locator_id=locator_id_for_symbol(symbol),
        risk_class=risk_class or _default_risk_class(kind),
        selection_source=_default_selection_source(kind),
        source_root_cid=source_root_cid,
        repository_state_cid=repository_state_cid,
        label=symbol.module_path,
        dependency_node_ids=(symbol.identity_cid(),),
    )


def candidate_from_test(
    test: TestSelectorIdentity,
    *,
    proof_unit_kind: ProofUnitKind | str = ProofUnitKind.UNIT_TEST,
    source_root_cid: str = ABSENCE_TOKEN,
    repository_state_cid: str = ABSENCE_TOKEN,
    risk_class: str | None = None,
) -> DiscoveredCandidate:
    """Build a pytest-node + parameter-case candidate."""

    kind = _parse_kind(proof_unit_kind)
    if kind not in {
        ProofUnitKind.UNIT_TEST,
        ProofUnitKind.INTEGRATION_TEST,
        ProofUnitKind.PROPERTY_TEST,
    }:
        raise DiscoveryError(
            "test candidates admit only unit_test, integration_test, "
            "or property_test kinds"
        )
    return DiscoveredCandidate(
        repository_id=test.repository_id,
        proof_unit_kind=kind,
        locator_kind=LocatorKind.PYTEST_NODE,
        locator_id=locator_id_for_test(test),
        risk_class=risk_class or _default_risk_class(kind),
        selection_source=_default_selection_source(kind),
        source_root_cid=source_root_cid,
        repository_state_cid=repository_state_cid,
        label=test.module_path,
        dependency_node_ids=(test.identity_cid(),),
    )


def candidate_from_property(
    prop: PropertyIdentity,
    *,
    proof_unit_kind: ProofUnitKind | str = ProofUnitKind.FORMAL_OBLIGATION,
    source_root_cid: str = ABSENCE_TOKEN,
    repository_state_cid: str = ABSENCE_TOKEN,
    risk_class: str | None = None,
) -> DiscoveredCandidate:
    """Build a formal property/obligation candidate."""

    kind = _parse_kind(proof_unit_kind)
    if kind not in {
        ProofUnitKind.FORMAL_OBLIGATION,
        ProofUnitKind.PROPERTY_TEST,
    }:
        raise DiscoveryError(
            "property candidates admit only formal_obligation or property_test"
        )
    locator_kind = (
        LocatorKind.PROPERTY_OBLIGATION
        if kind == ProofUnitKind.FORMAL_OBLIGATION
        else LocatorKind.PYTEST_NODE
    )
    return DiscoveredCandidate(
        repository_id=prop.repository_id,
        proof_unit_kind=kind,
        locator_kind=locator_kind,
        locator_id=locator_id_for_property(prop),
        risk_class=risk_class or _default_risk_class(kind),
        selection_source=_default_selection_source(kind),
        source_root_cid=source_root_cid,
        repository_state_cid=repository_state_cid,
        label=prop.property_name,
        dependency_node_ids=(prop.identity_cid(),),
    )


def candidate_for_direct_computation(
    *,
    repository_id: str,
    program_profile_id: str,
    source_root_cid: str = ABSENCE_TOKEN,
    repository_state_cid: str = ABSENCE_TOKEN,
    risk_class: str = "high",
    label: str = ABSENCE_TOKEN,
) -> DiscoveredCandidate:
    """Build a direct ZK computation candidate (fixed program/circuit profile)."""

    profile = _require_text(program_profile_id, "program_profile_id")
    return DiscoveredCandidate(
        repository_id=repository_id,
        proof_unit_kind=ProofUnitKind.DIRECT_ZK_COMPUTATION,
        locator_kind=LocatorKind.DIRECT_COMPUTATION,
        locator_id=profile,
        risk_class=risk_class,
        selection_source=_default_selection_source(
            ProofUnitKind.DIRECT_ZK_COMPUTATION
        ),
        source_root_cid=source_root_cid,
        repository_state_cid=repository_state_cid,
        label=label if label != ABSENCE_TOKEN else profile,
    )


def candidate_for_release_invariant(
    *,
    repository_id: str,
    invariant_id: str,
    source_root_cid: str = ABSENCE_TOKEN,
    repository_state_cid: str = ABSENCE_TOKEN,
    risk_class: str = "high",
    label: str = ABSENCE_TOKEN,
) -> DiscoveredCandidate:
    """Build an explicit release-invariant dependent unit."""

    inv = _require_text(invariant_id, "invariant_id")
    return DiscoveredCandidate(
        repository_id=repository_id,
        proof_unit_kind=ProofUnitKind.RELEASE_INVARIANT,
        locator_kind=LocatorKind.RELEASE_INVARIANT,
        locator_id=inv,
        risk_class=risk_class,
        selection_source=_default_selection_source(ProofUnitKind.RELEASE_INVARIANT),
        source_root_cid=source_root_cid,
        repository_state_cid=repository_state_cid,
        label=label if label != ABSENCE_TOKEN else inv,
    )


def candidate_for_receipt_aggregate(
    *,
    repository_id: str,
    aggregate_id: str,
    source_root_cid: str = ABSENCE_TOKEN,
    repository_state_cid: str = ABSENCE_TOKEN,
    risk_class: str = "high",
    label: str = ABSENCE_TOKEN,
    member_unit_ids: Sequence[str] = (),
) -> DiscoveredCandidate:
    """Build an explicit receipt-aggregation dependent unit."""

    agg = _require_text(aggregate_id, "aggregate_id")
    members = _require_sorted_unique_strings(
        member_unit_ids, "member_unit_ids"
    )
    return DiscoveredCandidate(
        repository_id=repository_id,
        proof_unit_kind=ProofUnitKind.RECEIPT_AGGREGATION,
        locator_kind=LocatorKind.RECEIPT_AGGREGATE,
        locator_id=agg,
        risk_class=risk_class,
        selection_source=_default_selection_source(
            ProofUnitKind.RECEIPT_AGGREGATION
        ),
        source_root_cid=source_root_cid,
        repository_state_cid=repository_state_cid,
        label=label if label != ABSENCE_TOKEN else agg,
        dependency_node_ids=members,
    )


def _normalize_frontiers(
    frontiers: Sequence[DiscoveryFrontier] | None,
) -> tuple[DiscoveryFrontier, ...]:
    if frontiers is None:
        return ()
    if not isinstance(frontiers, Sequence) or isinstance(frontiers, (str, bytes)):
        raise DiscoveryError("frontiers must be a sequence")
    if len(frontiers) > MAX_FRONTIERS:
        raise DiscoveryError(f"frontiers exceeds MAX_FRONTIERS={MAX_FRONTIERS}")
    ordered = tuple(sorted(frontiers, key=lambda item: item.frontier_id))
    ids = [item.frontier_id for item in ordered]
    if len(set(ids)) != len(ids):
        raise DiscoveryError("frontiers must not contain duplicate frontier_id")
    return ordered


def _frontiers_complete(frontiers: Sequence[DiscoveryFrontier]) -> bool:
    return all(item.complete for item in frontiers)


def discover_requirements(
    *,
    repository_id: str,
    candidates: Sequence[DiscoveredCandidate],
    selector: ProofUnitSelector,
    frontiers: Sequence[DiscoveryFrontier] | None = None,
    previous_required_unit_ids: Sequence[str] | None = None,
) -> RequirementDiscoveryResult:
    """Select required proof units under selector policy and frontier rules.

    Incomplete frontiers set ``complete=False`` and refuse to narrow the
    required set below ``previous_required_unit_ids`` for units still present
    in the candidate catalog.  Units that disappeared from the catalog (true
    deletes / renames) remain remove/add classifications via
    :func:`diff_discovered_unit_ids`.
    """

    repo = _require_text(repository_id, "repository_id")
    if not isinstance(selector, ProofUnitSelector):
        raise DiscoveryError("selector must be a ProofUnitSelector")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise DiscoveryError("candidates must be a sequence")
    if len(candidates) > MAX_CANDIDATES:
        raise DiscoveryError(f"candidates exceeds MAX_CANDIDATES={MAX_CANDIDATES}")

    for candidate in candidates:
        if not isinstance(candidate, DiscoveredCandidate):
            raise DiscoveryError("candidates entries must be DiscoveredCandidate")
        if candidate.repository_id != repo:
            raise DiscoveryError(
                f"candidate repository_id {candidate.repository_id!r} "
                f"does not match discovery repository_id {repo!r}"
            )

    ordered_frontiers = _normalize_frontiers(frontiers)
    complete = _frontiers_complete(ordered_frontiers)

    selected = list(selector.select(candidates))
    selected_ids = {unit.proof_unit_id for unit in selected}
    catalog_by_id = {unit.proof_unit_id: unit for unit in candidates}

    # Unknown frontiers cannot narrow: retain any previous required unit that
    # is still in the candidate catalog even if the selector would drop it.
    if not complete and previous_required_unit_ids:
        for unit_id in previous_required_unit_ids:
            unit_id = _require_text(unit_id, "previous_required_unit_ids")
            if unit_id in selected_ids:
                continue
            retained = catalog_by_id.get(unit_id)
            if retained is None:
                # True delete/rename: not in catalog; removal is explicit later.
                continue
            # Frontier incomplete: cannot authorize selector narrowing.
            selected.append(retained)
            selected_ids.add(unit_id)

    selected.sort(key=lambda item: item.proof_unit_id)
    # Deduplicate after retention merge.
    seen: set[str] = set()
    unique: list[DiscoveredCandidate] = []
    for unit in selected:
        if unit.proof_unit_id in seen:
            continue
        seen.add(unit.proof_unit_id)
        unique.append(unit)

    return RequirementDiscoveryResult(
        repository_id=repo,
        selector_cid=selector.selector_cid(),
        required_units=tuple(unique),
        frontiers=ordered_frontiers,
        complete=complete,
    )


def assert_unknown_frontiers_do_not_narrow(
    *,
    previous_required_unit_ids: Sequence[str],
    current: RequirementDiscoveryResult,
    catalog_unit_ids: Sequence[str],
) -> None:
    """Fail closed when an incomplete frontier drops a still-catalogued unit."""

    if current.complete:
        return
    catalog = set(
        _require_text(item, "catalog_unit_ids") for item in catalog_unit_ids
    )
    current_ids = set(current.required_unit_ids)
    for unit_id in previous_required_unit_ids:
        unit_id = _require_text(unit_id, "previous_required_unit_ids")
        if unit_id in catalog and unit_id not in current_ids:
            raise DiscoveryError(
                f"unknown frontier cannot narrow requirements: dropped "
                f"still-catalogued unit {unit_id!r}"
            )


# ---------------------------------------------------------------------------
# Dependency graph construction from discovered units
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveryDependencyEdge:
    """One prerequisite -> dependent edge declared for graph construction."""

    from_id: str
    to_id: str
    edge_type: DependencyEdgeType | str
    reason_label: str = "discovery"

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_id", _require_text(self.from_id, "from_id"))
        object.__setattr__(self, "to_id", _require_text(self.to_id, "to_id"))
        object.__setattr__(
            self, "reason_label", _require_text(self.reason_label, "reason_label")
        )


def build_proof_dependency_graph(
    *,
    units: Sequence[DiscoveredCandidate] | None = None,
    edges: Sequence[DiscoveryDependencyEdge | Mapping[str, Any]] | None = None,
    extra_nodes: Sequence[tuple[str, DependencyNodeKind | str]] | None = None,
    truncated_node_ids: Sequence[str] | None = None,
) -> ProofDependencyGraph:
    """Build a reason-labeled proof dependency graph from discovery inputs.

    Unit nodes are registered as ``DependencyNodeKind.UNIT`` keyed by their
    stable logical ``proof_unit_id``.  Insertion order of ``units`` / ``edges``
    cannot affect the resulting graph CID.
    """

    graph = ProofDependencyGraph()
    units = () if units is None else units
    edges = () if edges is None else edges
    extra_nodes = () if extra_nodes is None else extra_nodes
    truncated_node_ids = () if truncated_node_ids is None else truncated_node_ids

    if not isinstance(units, Sequence) or isinstance(units, (str, bytes)):
        raise DiscoveryError("units must be a sequence")
    if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
        raise DiscoveryError("edges must be a sequence")

    for unit in units:
        if not isinstance(unit, DiscoveredCandidate):
            raise DiscoveryError("units entries must be DiscoveredCandidate")
        graph.add_node(
            unit.proof_unit_id,
            DependencyNodeKind.UNIT,
            label=(
                unit.label
                if unit.label != ABSENCE_TOKEN
                else unit.proof_unit_kind.value
            ),
        )
        for dep in unit.dependency_node_ids:
            if not graph.has_node(dep):
                graph.add_node(dep, DependencyNodeKind.SYMBOL, label=dep)

    for node_id, kind in extra_nodes:
        graph.add_node(node_id, kind)

    for raw in edges:
        if isinstance(raw, DiscoveryDependencyEdge):
            edge = raw
        elif isinstance(raw, Mapping):
            edge = DiscoveryDependencyEdge(
                from_id=str(raw.get("from_id") or raw.get("from") or ""),
                to_id=str(raw.get("to_id") or raw.get("to") or ""),
                edge_type=raw.get("edge_type") or "",
                reason_label=str(raw.get("reason_label") or "discovery"),
            )
        else:
            raise DiscoveryError(
                "edges entries must be DiscoveryDependencyEdge or mapping"
            )
        if not graph.has_node(edge.from_id):
            graph.add_node(edge.from_id, DependencyNodeKind.UNKNOWN)
        if not graph.has_node(edge.to_id):
            graph.add_node(edge.to_id, DependencyNodeKind.UNKNOWN)
        try:
            graph.add_edge(
                edge.from_id,
                edge.to_id,
                edge.edge_type,
                mint_reason_cid(
                    {
                        "reason": edge.reason_label,
                        "from_id": edge.from_id,
                        "to_id": edge.to_id,
                        "v": SCHEMA_MAJOR,
                    }
                ),
            )
        except DependencyGraphError as exc:
            raise DiscoveryError(str(exc)) from exc

    for node_id in truncated_node_ids:
        try:
            graph.mark_truncated(node_id)
        except DependencyGraphError as exc:
            raise DiscoveryError(str(exc)) from exc

    return graph


# ---------------------------------------------------------------------------
# Manifest construction from discovery
# ---------------------------------------------------------------------------


def build_manifest_from_discovery(
    *,
    discovery: RequirementDiscoveryResult,
    revision: str,
    repository_state_cid: str,
    source_root_cid: str,
    policy: VerificationPolicy | str,
    environment_cid: str,
    dependency_lock_cid: str,
    configuration_cid: str,
    network_policy_cid: str = ABSENCE_TOKEN,
    dependency_graph_schema_version: str = DEPENDENCY_GRAPH_SCHEMA_VERSION,
    permitted_removals: Sequence[UnitRemovalAuthorization] = (),
    logical_epoch: int = 0,
) -> VerificationRequirementManifest:
    """Build a verification requirement manifest from a discovery result.

    Incomplete discovery still produces a manifest; ``discovery.complete``
    remains the explicit completeness signal.  Removal authorization for units
    that left a prior required set is supplied via ``permitted_removals`` and
    enforced by the manifest layer.
    """

    if not isinstance(discovery, RequirementDiscoveryResult):
        raise DiscoveryError("discovery must be a RequirementDiscoveryResult")
    units = discovery.to_required_descriptors()
    try:
        return build_verification_requirement_manifest(
            repository_id=discovery.repository_id,
            revision=revision,
            repository_state_cid=repository_state_cid,
            source_root_cid=source_root_cid,
            required_units=units,
            policy=policy,
            test_selector_cid=discovery.selector_cid,
            environment_cid=environment_cid,
            dependency_lock_cid=dependency_lock_cid,
            configuration_cid=configuration_cid,
            network_policy_cid=network_policy_cid,
            dependency_graph_schema_version=dependency_graph_schema_version,
            permitted_removals=permitted_removals,
            logical_epoch=logical_epoch,
            selected_unit_ids=discovery.required_unit_ids,
        )
    except ManifestError as exc:
        raise DiscoveryError(str(exc)) from exc


def classify_rename_or_delete(
    *,
    previous: DiscoveredCandidate,
    current_candidates: Sequence[DiscoveredCandidate],
    previous_candidates: Sequence[DiscoveredCandidate] | None = None,
) -> str:
    """Classify a missing previous unit as ``deleted`` or ``renamed``.

    A rename is detected when exactly one *new* current candidate shares the
    same proof-unit kind and a different locator.  When
    ``previous_candidates`` is supplied, "new" means absent from that prior
    catalog; otherwise every same-kind different-locator peer is considered.
    Both rename and delete are remove+add at the logical-ID layer; this helper
    only labels the transition.
    """

    if not isinstance(previous, DiscoveredCandidate):
        raise DiscoveryError("previous must be a DiscoveredCandidate")
    current_ids = {c.proof_unit_id for c in current_candidates}
    if previous.proof_unit_id in current_ids:
        return "retained"
    prior_ids: set[str] = set()
    if previous_candidates is not None:
        prior_ids = {c.proof_unit_id for c in previous_candidates}
    peers = [
        c
        for c in current_candidates
        if c.proof_unit_kind == previous.proof_unit_kind
        and c.locator_id != previous.locator_id
        and c.repository_id == previous.repository_id
        and c.proof_unit_id not in prior_ids
    ]
    if len(peers) == 1:
        return "renamed"
    return "deleted"


# ---------------------------------------------------------------------------
# Samples and known vectors
# ---------------------------------------------------------------------------


def _sample_cid(label: str) -> str:
    return canonical_cid({"ips_discovery_sample": label, "v": SCHEMA_MAJOR})


def sample_selector(**overrides: Any) -> ProofUnitSelector:
    payload: dict[str, Any] = {
        "selector_id": "selector/default",
        "included_kinds": (),
        "excluded_kinds": (),
        "include_path_prefixes": (),
        "exclude_path_prefixes": (),
        "include_unit_ids": (),
        "exclude_unit_ids": (),
        "require_all_selected_kinds": False,
        "include_release_invariants": True,
        "include_receipt_aggregates": True,
    }
    payload.update(overrides)
    return ProofUnitSelector(**payload)


def sample_candidates(
    *,
    repository_id: str = "repo/datasets",
    source_root_cid: str | None = None,
    repository_state_cid: str | None = None,
) -> tuple[DiscoveredCandidate, ...]:
    """Hermetic multi-granularity candidate set for regression tests."""

    source_root = source_root_cid or _sample_cid("source-root")
    repo_state = repository_state_cid or _sample_cid("repository-state")
    artifact_cid = _sample_cid("artifact:pkg/main.py")
    symbol = SourceSymbolIdentity(
        repository_id=repository_id,
        module_path="pkg/main.py",
        qualified_name="pkg.main:entry",
        symbol_kind="function",
        source_artifact_id=artifact_cid,
    )
    test = TestSelectorIdentity(
        repository_id=repository_id,
        node_id="tests/test_main.py::test_entry",
        module_path="tests/test_main.py",
        function_name="test_entry",
        parameter_case=ABSENCE_TOKEN,
    )
    param_test = TestSelectorIdentity(
        repository_id=repository_id,
        node_id="tests/test_main.py::test_entry[case-a]",
        module_path="tests/test_main.py",
        function_name="test_entry",
        parameter_case="case-a",
    )
    statement_cid = _sample_cid("statement:soundness")
    prop = PropertyIdentity(
        repository_id=repository_id,
        property_name="prop/output-soundness",
        statement_cid=statement_cid,
        obligation_kind="formal_obligation",
    )
    candidates = (
        candidate_from_symbol(
            symbol,
            proof_unit_kind=ProofUnitKind.STATIC_ANALYSIS,
            source_root_cid=source_root,
            repository_state_cid=repo_state,
        ),
        candidate_from_test(
            test,
            proof_unit_kind=ProofUnitKind.UNIT_TEST,
            source_root_cid=source_root,
            repository_state_cid=repo_state,
        ),
        candidate_from_test(
            param_test,
            proof_unit_kind=ProofUnitKind.UNIT_TEST,
            source_root_cid=source_root,
            repository_state_cid=repo_state,
        ),
        candidate_from_property(
            prop,
            source_root_cid=source_root,
            repository_state_cid=repo_state,
        ),
        candidate_for_direct_computation(
            repository_id=repository_id,
            program_profile_id="circuit/profile-v1",
            source_root_cid=source_root,
            repository_state_cid=repo_state,
            label="direct/profile-v1",
        ),
        candidate_for_release_invariant(
            repository_id=repository_id,
            invariant_id="release/invariant-v1",
            source_root_cid=source_root,
            repository_state_cid=repo_state,
        ),
        candidate_for_receipt_aggregate(
            repository_id=repository_id,
            aggregate_id="aggregate/receipt-v1",
            source_root_cid=source_root,
            repository_state_cid=repo_state,
        ),
    )
    return tuple(sorted(candidates, key=lambda item: item.proof_unit_id))


def sample_discovery_result(**overrides: Any) -> RequirementDiscoveryResult:
    selector = sample_selector()
    candidates = sample_candidates()
    result = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates,
        selector=selector,
        frontiers=(),
    )
    if not overrides:
        return result
    payload = result.to_canonical()
    payload.update(overrides)
    return RequirementDiscoveryResult.from_canonical(payload)


def known_vectors() -> dict[str, Any]:
    """Versioned hermetic vectors for requirement-discovery evidence."""

    source_a = _sample_cid("source-root-a")
    source_b = _sample_cid("source-root-b")
    state_a = _sample_cid("repository-state-a")
    state_b = _sample_cid("repository-state-b")

    candidates_a = sample_candidates(
        source_root_cid=source_a, repository_state_cid=state_a
    )
    # Same locators, different context: logical IDs must survive.
    candidates_b = sample_candidates(
        source_root_cid=source_b, repository_state_cid=state_b
    )
    logical_ids_a = [c.proof_unit_id for c in candidates_a]
    logical_ids_b = [c.proof_unit_id for c in candidates_b]

    selector_all = sample_selector(selector_id="selector/all")
    selector_tests = sample_selector(
        selector_id="selector/tests-only",
        included_kinds=sorted(
            [
                ProofUnitKind.UNIT_TEST.value,
                ProofUnitKind.INTEGRATION_TEST.value,
                ProofUnitKind.PROPERTY_TEST.value,
            ]
        ),
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    discovery_all = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates_a,
        selector=selector_all,
    )
    discovery_tests = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates_a,
        selector=selector_tests,
    )

    # Rename: change locator of the non-parametrized unit-test candidate.
    non_param_locator = locator_id_for_test(
        TestSelectorIdentity(
            repository_id="repo/datasets",
            node_id="tests/test_main.py::test_entry",
            module_path="tests/test_main.py",
            function_name="test_entry",
            parameter_case=ABSENCE_TOKEN,
        )
    )
    original_test = next(
        c
        for c in candidates_a
        if c.proof_unit_kind == ProofUnitKind.UNIT_TEST
        and c.locator_id == non_param_locator
    )
    renamed_test = DiscoveredCandidate(
        repository_id=original_test.repository_id,
        proof_unit_kind=original_test.proof_unit_kind,
        locator_kind=original_test.locator_kind,
        locator_id=_sample_cid("renamed-test-locator"),
        risk_class=original_test.risk_class,
        selection_source=original_test.selection_source,
        source_root_cid=original_test.source_root_cid,
        repository_state_cid=original_test.repository_state_cid,
        label="tests/test_renamed.py",
        dependency_node_ids=original_test.dependency_node_ids,
    )
    renamed_catalog = tuple(
        sorted(
            [c for c in candidates_a if c.proof_unit_id != original_test.proof_unit_id]
            + [renamed_test],
            key=lambda item: item.proof_unit_id,
        )
    )
    discovery_renamed = discover_requirements(
        repository_id="repo/datasets",
        candidates=renamed_catalog,
        selector=selector_all,
    )
    rename_diff = diff_discovered_unit_ids(
        discovery_all.required_unit_ids,
        discovery_renamed.required_unit_ids,
    )

    # Incomplete frontier must not drop still-catalogued previous units under
    # a narrower selector.
    incomplete_frontier = DiscoveryFrontier(
        frontier_id="frontier/import-pkg",
        kind=FrontierKind.IMPORT,
        complete=False,
        scope_path="pkg",
        reason="import graph truncated",
    )
    narrow = sample_selector(
        selector_id="selector/narrow",
        included_kinds=[ProofUnitKind.STATIC_ANALYSIS.value],
        include_release_invariants=False,
        include_receipt_aggregates=False,
    )
    discovery_incomplete = discover_requirements(
        repository_id="repo/datasets",
        candidates=candidates_a,
        selector=narrow,
        frontiers=(incomplete_frontier,),
        previous_required_unit_ids=discovery_all.required_unit_ids,
    )
    assert_unknown_frontiers_do_not_narrow(
        previous_required_unit_ids=discovery_all.required_unit_ids,
        current=discovery_incomplete,
        catalog_unit_ids=[c.proof_unit_id for c in candidates_a],
    )

    graph = build_proof_dependency_graph(
        units=discovery_tests.required_units,
        edges=[
            DiscoveryDependencyEdge(
                from_id=discovery_tests.required_unit_ids[0],
                to_id=discovery_tests.required_unit_ids[-1]
                if len(discovery_tests.required_unit_ids) > 1
                else discovery_tests.required_unit_ids[0],
                edge_type=DependencyEdgeType.PROOF_DEPENDS_ON,
                reason_label="test-chain",
            )
        ]
        if len(discovery_tests.required_unit_ids) > 1
        else (),
    )

    policy = sample_verification_policy()
    manifest = build_manifest_from_discovery(
        discovery=discovery_tests,
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        repository_state_cid=state_a,
        source_root_cid=source_a,
        policy=policy,
        environment_cid=_sample_cid("environment"),
        dependency_lock_cid=_sample_cid("lock"),
        configuration_cid=_sample_cid("config"),
        logical_epoch=1,
    )

    return {
        "schema": f"{DISCOVERY_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "discovery_subset": DISCOVERY_SUBSET,
        "discovery_schema_version": DISCOVERY_SCHEMA_VERSION,
        "logical_ids_survive_context_change": logical_ids_a == logical_ids_b,
        "logical_ids_context_a": logical_ids_a,
        "logical_ids_context_b": logical_ids_b,
        "selector_all": {
            "selector_cid": selector_all.selector_cid(),
            "required_unit_ids": list(discovery_all.required_unit_ids),
            "complete": discovery_all.complete,
        },
        "selector_tests": {
            "selector_cid": selector_tests.selector_cid(),
            "required_unit_ids": list(discovery_tests.required_unit_ids),
            "required_kinds": sorted(
                {u.proof_unit_kind.value for u in discovery_tests.required_units}
            ),
        },
        "rename_diff": rename_diff.to_canonical(),
        "rename_classification": classify_rename_or_delete(
            previous=original_test,
            current_candidates=renamed_catalog,
            previous_candidates=candidates_a,
        ),
        "incomplete_frontier": {
            "complete": discovery_incomplete.complete,
            "required_unit_ids": list(discovery_incomplete.required_unit_ids),
            "retained_previous": sorted(
                set(discovery_all.required_unit_ids)
                & set(discovery_incomplete.required_unit_ids)
            ),
        },
        "graph_cid": graph.graph_cid(),
        "manifest_root": manifest.manifest_root(),
        "manifest_required_unit_ids": list(manifest.required_unit_ids),
    }


__all__ = (
    "ABSENCE_TOKEN",
    "CANONICALIZATION_VERSION",
    "DISCOVERED_CANDIDATE_SCHEMA",
    "DISCOVERY_RESULT_SCHEMA",
    "DISCOVERY_SCHEMA_VERSION",
    "DISCOVERY_SELECTION_SOURCES",
    "DISCOVERY_SUBSET",
    "FRONTIER_KINDS",
    "LOCATOR_KINDS",
    "LOGICAL_UNIT_IDENTITY_SCHEMA",
    "SELECTOR_SCHEMA",
    "DiscoveredCandidate",
    "DiscoveryDependencyEdge",
    "DiscoveryError",
    "DiscoveryFrontier",
    "DiscoverySetDiff",
    "FrontierKind",
    "LocatorKind",
    "LogicalProofUnitIdentity",
    "ProofUnitSelector",
    "RequirementDiscoveryResult",
    "assert_unknown_frontiers_do_not_narrow",
    "build_manifest_from_discovery",
    "build_proof_dependency_graph",
    "build_verification_requirement_manifest",
    "candidate_for_direct_computation",
    "candidate_for_receipt_aggregate",
    "candidate_for_release_invariant",
    "candidate_from_property",
    "candidate_from_symbol",
    "candidate_from_test",
    "classify_rename_or_delete",
    "closed_discovery_selection_sources",
    "closed_frontier_kinds",
    "closed_locator_kinds",
    "diff_discovered_unit_ids",
    "discover_requirements",
    "known_vectors",
    "locator_id_for_property",
    "locator_id_for_symbol",
    "locator_id_for_test",
    "mint_logical_proof_unit_id",
    "parse_frontier_kind",
    "parse_locator_kind",
    "sample_candidates",
    "sample_discovery_result",
    "sample_selector",
)
