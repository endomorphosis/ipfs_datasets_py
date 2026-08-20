"""Invalidation closure, full-fallback rules, and explanations (IPS-016).

Datasets semantic authority for exact invalidation over the reason-labeled
dependency graph, repository diffs, and checkpoint-trigger policy.

Rules:

* walk prerequisite -> dependent (forward) from every changed seed;
* ordinary documentation and unrelated nodes never seed invalidation;
* unknown / truncated / unmapped relevant changes broaden or force full
  fallback and never narrow reuse;
* add/delete of selected tests are explicit prove-new / authorized-remove
  dispositions (never silent);
* unchanged file alone never authorizes reuse;
* imports have no side effects (CID minting reuses identity helpers lazily).

Interfaces: ``compute_invalidation_closure``, ``classify_full_fallback``,
``explain_invalidation``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .dependency_graph import (
    DEPENDENCY_GRAPH_SCHEMA_VERSION,
    DependencyGraphError,
    DependencyNodeKind,
    MAX_EXPLANATION_DEPTH,
    MAX_EXPLANATION_PATHS,
    ProofDependencyEdge,
    ProofDependencyGraph,
    sample_dependency_graph,
)
from .identity import (
    ABSENCE_TOKEN,
    SECRET_AND_NONDETERMINISTIC_FIELDS,
    IdentityError,
    canonical_cid,
    validate_profile_cid,
)
from .repository_diff import (
    BROAD_INVALIDATION_CHANGE_CLASSES,
    FULL_FALLBACK_CHANGE_CLASSES,
    ChangeAction,
    ChangeClass,
    ChangedArtifact,
    RepositoryDiff,
    parse_change_class,
)

INVALIDATION_SUBSET: Final[str] = "ips/invalidation-engine@1"
INVALIDATION_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/invalidation"
)
SCHEMA_MAJOR: Final[int] = 1
INVALIDATION_SCHEMA_VERSION: Final[str] = f"invalidation@{SCHEMA_MAJOR}"

INVALIDATION_POLICY_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/invalidation-policy@{SCHEMA_MAJOR}"
)
FULL_FALLBACK_DECISION_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/full-fallback-decision@{SCHEMA_MAJOR}"
)
UNIT_DISPOSITION_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/unit-disposition@{SCHEMA_MAJOR}"
)
INVALIDATION_CLOSURE_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/invalidation-closure@{SCHEMA_MAJOR}"
)
INVALIDATION_EXPLANATION_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/proof-invalidation-explanation@{SCHEMA_MAJOR}"
)
EXPLANATION_PATH_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/explanation-path@{SCHEMA_MAJOR}"
)
CHANGED_KEY_FIELD_SCHEMA: Final[str] = (
    f"{INVALIDATION_NAMESPACE}/changed-key-field@{SCHEMA_MAJOR}"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_UNITS: Final[int] = 1 << 18
MAX_PATH_MAPPINGS: Final[int] = 1 << 18
MAX_REASONS: Final[int] = 1 << 12
MAX_EXPLANATION_PATH_EDGES: Final[int] = MAX_EXPLANATION_DEPTH

# Closed ordered unit disposition kinds.
UNIT_DISPOSITION_KINDS: Final[tuple[str, ...]] = (
    "invalidate",
    "preserve",
    "prove_new",
    "remove_requires_authorization",
    "remove_authorized",
)

# Closed ordered full-fallback reason codes (plan §6 + §8.1).
FULL_FALLBACK_REASONS: Final[tuple[str, ...]] = (
    "genesis",
    "canonicalization_changed",
    "dependency_graph_schema_changed",
    "proof_schema_changed",
    "circuit_changed",
    "proving_key_changed",
    "verification_key_changed",
    "environment_changed",
    "unknown_change_class",
    "ambiguous_diff",
    "incomplete_inventory",
    "unresolved_merge",
    "repository_id_mismatch",
    "truncated_closure",
    "unmapped_relevant_change",
    "uncertain_cache_integrity",
    "release_qualification",
    "explicit_policy",
    "dependency_lock_policy",
    "excessive_delta_chain_depth",
    "low_reuse_ratio",
    "incremental_reuse_unjustified",
)

# Closed ordered invalidation trigger labels (normative rule axes).
INVALIDATION_TRIGGERS: Final[tuple[str, ...]] = (
    "source_implementation",
    "source_interface",
    "test_source",
    "test_added",
    "test_deleted",
    "fixture",
    "configuration",
    "dependency_lock",
    "circuit",
    "proving_key",
    "verification_key",
    "test_selector",
    "policy",
    "network_policy",
    "canonicalization",
    "environment",
    "checked_specification",
    "generated_input",
    "ordinary_documentation",
    "unknown",
    "seed_node",
    "truncated_frontier",
    "full_fallback",
)

# Change classes that never seed invalidation on their own.
PRESERVE_CHANGE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        ChangeClass.ORDINARY_DOCUMENTATION.value,
    }
)

# Change classes that invalidate only bound dependents (local seeds).
LOCAL_INVALIDATION_CHANGE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        ChangeClass.SOURCE_IMPLEMENTATION.value,
        ChangeClass.TEST_SOURCE.value,
        ChangeClass.FIXTURE.value,
        ChangeClass.CONFIGURATION.value,
    }
)

# Mapping from change class to the primary cache-key / statement fields it
# affects.  Used by explanations so "file unchanged" is never the sole reason.
CHANGE_CLASS_KEY_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    ChangeClass.SOURCE_IMPLEMENTATION.value: (
        "source_root_cid",
        "source_artifact_cids",
    ),
    ChangeClass.SOURCE_INTERFACE.value: (
        "source_root_cid",
        "source_artifact_cids",
        "dependency_unit_roots",
    ),
    ChangeClass.TEST_SOURCE.value: (
        "source_root_cid",
        "source_artifact_cids",
        "test_selector_cid",
    ),
    ChangeClass.FIXTURE.value: ("fixture_cids",),
    ChangeClass.DEPENDENCY_LOCK.value: ("dependency_lock_cid", "environment_cid"),
    ChangeClass.CONFIGURATION.value: ("configuration_cid",),
    ChangeClass.CIRCUIT.value: ("circuit_id", "circuit_version"),
    ChangeClass.PROVING_KEY.value: ("proving_key_id",),
    ChangeClass.VERIFICATION_KEY.value: ("verification_key_id",),
    ChangeClass.TEST_SELECTOR.value: ("test_selector_cid",),
    ChangeClass.POLICY.value: ("policy_cid",),
    ChangeClass.NETWORK_POLICY.value: ("network_policy_cid",),
    ChangeClass.CANONICALIZATION.value: ("canonicalization_version",),
    ChangeClass.ENVIRONMENT.value: ("environment_cid",),
    ChangeClass.CHECKED_SPECIFICATION.value: (
        "statement_cid",
        "source_artifact_cids",
    ),
    ChangeClass.GENERATED_INPUT.value: (
        "public_input_cid",
        "private_input_commitment",
        "fixture_cids",
    ),
    ChangeClass.ORDINARY_DOCUMENTATION.value: (),
    ChangeClass.UNKNOWN.value: (
        "source_root_cid",
        "environment_cid",
        "dependency_lock_cid",
        "configuration_cid",
        "policy_cid",
    ),
}

# Change-class -> full-fallback reason when that class alone forces fallback.
_CLASS_TO_FALLBACK_REASON: Final[Mapping[str, str]] = {
    ChangeClass.CIRCUIT.value: "circuit_changed",
    ChangeClass.PROVING_KEY.value: "proving_key_changed",
    ChangeClass.VERIFICATION_KEY.value: "verification_key_changed",
    ChangeClass.CANONICALIZATION.value: "canonicalization_changed",
    ChangeClass.ENVIRONMENT.value: "environment_changed",
    ChangeClass.UNKNOWN.value: "unknown_change_class",
}


class InvalidationError(ValueError):
    """Invalidation contract violation."""


class UnitDispositionKind(str, Enum):
    """Closed per-unit outcome of an invalidation decision."""

    INVALIDATE = "invalidate"
    PRESERVE = "preserve"
    PROVE_NEW = "prove_new"
    REMOVE_REQUIRES_AUTHORIZATION = "remove_requires_authorization"
    REMOVE_AUTHORIZED = "remove_authorized"


class FullFallbackReason(str, Enum):
    """Closed full-checkpoint trigger reason."""

    GENESIS = "genesis"
    CANONICALIZATION_CHANGED = "canonicalization_changed"
    DEPENDENCY_GRAPH_SCHEMA_CHANGED = "dependency_graph_schema_changed"
    PROOF_SCHEMA_CHANGED = "proof_schema_changed"
    CIRCUIT_CHANGED = "circuit_changed"
    PROVING_KEY_CHANGED = "proving_key_changed"
    VERIFICATION_KEY_CHANGED = "verification_key_changed"
    ENVIRONMENT_CHANGED = "environment_changed"
    UNKNOWN_CHANGE_CLASS = "unknown_change_class"
    AMBIGUOUS_DIFF = "ambiguous_diff"
    INCOMPLETE_INVENTORY = "incomplete_inventory"
    UNRESOLVED_MERGE = "unresolved_merge"
    REPOSITORY_ID_MISMATCH = "repository_id_mismatch"
    TRUNCATED_CLOSURE = "truncated_closure"
    UNMAPPED_RELEVANT_CHANGE = "unmapped_relevant_change"
    UNCERTAIN_CACHE_INTEGRITY = "uncertain_cache_integrity"
    RELEASE_QUALIFICATION = "release_qualification"
    EXPLICIT_POLICY = "explicit_policy"
    DEPENDENCY_LOCK_POLICY = "dependency_lock_policy"
    EXCESSIVE_DELTA_CHAIN_DEPTH = "excessive_delta_chain_depth"
    LOW_REUSE_RATIO = "low_reuse_ratio"
    INCREMENTAL_REUSE_UNJUSTIFIED = "incremental_reuse_unjustified"


class InvalidationTrigger(str, Enum):
    """Closed label for the normative rule that fired for a unit or seed."""

    SOURCE_IMPLEMENTATION = "source_implementation"
    SOURCE_INTERFACE = "source_interface"
    TEST_SOURCE = "test_source"
    TEST_ADDED = "test_added"
    TEST_DELETED = "test_deleted"
    FIXTURE = "fixture"
    CONFIGURATION = "configuration"
    DEPENDENCY_LOCK = "dependency_lock"
    CIRCUIT = "circuit"
    PROVING_KEY = "proving_key"
    VERIFICATION_KEY = "verification_key"
    TEST_SELECTOR = "test_selector"
    POLICY = "policy"
    NETWORK_POLICY = "network_policy"
    CANONICALIZATION = "canonicalization"
    ENVIRONMENT = "environment"
    CHECKED_SPECIFICATION = "checked_specification"
    GENERATED_INPUT = "generated_input"
    ORDINARY_DOCUMENTATION = "ordinary_documentation"
    UNKNOWN = "unknown"
    SEED_NODE = "seed_node"
    TRUNCATED_FRONTIER = "truncated_frontier"
    FULL_FALLBACK = "full_fallback"


def closed_unit_disposition_kinds() -> frozenset[str]:
    return frozenset(UNIT_DISPOSITION_KINDS)


def closed_full_fallback_reasons() -> frozenset[str]:
    return frozenset(FULL_FALLBACK_REASONS)


def closed_invalidation_triggers() -> frozenset[str]:
    return frozenset(INVALIDATION_TRIGGERS)


def parse_unit_disposition_kind(value: Any) -> UnitDispositionKind:
    if isinstance(value, UnitDispositionKind):
        return value
    if not isinstance(value, str) or not value.strip():
        raise InvalidationError("disposition kind must be a non-empty closed string")
    text = value.strip()
    try:
        return UnitDispositionKind(text)
    except ValueError as exc:
        raise InvalidationError(
            f"unknown UnitDispositionKind {value!r}; "
            f"closed set is {list(UNIT_DISPOSITION_KINDS)}"
        ) from exc


def parse_full_fallback_reason(value: Any) -> FullFallbackReason:
    if isinstance(value, FullFallbackReason):
        return value
    if not isinstance(value, str) or not value.strip():
        raise InvalidationError("fallback reason must be a non-empty closed string")
    text = value.strip()
    try:
        return FullFallbackReason(text)
    except ValueError as exc:
        raise InvalidationError(
            f"unknown FullFallbackReason {value!r}; "
            f"closed set is {list(FULL_FALLBACK_REASONS)}"
        ) from exc


def parse_invalidation_trigger(value: Any) -> InvalidationTrigger:
    if isinstance(value, InvalidationTrigger):
        return value
    if not isinstance(value, str) or not value.strip():
        raise InvalidationError("trigger must be a non-empty closed string")
    text = value.strip()
    try:
        return InvalidationTrigger(text)
    except ValueError as exc:
        raise InvalidationError(
            f"unknown InvalidationTrigger {value!r}; "
            f"closed set is {list(INVALIDATION_TRIGGERS)}"
        ) from exc


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise InvalidationError(f"{field} must be a non-empty string or {ABSENCE_TOKEN}")
    text = value.strip()
    if text != value:
        raise InvalidationError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise InvalidationError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    text = _require_text(value, field, allow_absence=False)
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise InvalidationError(f"{field}: {exc}") from exc


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise InvalidationError(f"{field} must be a boolean")
    return value


def _require_nonneg_int(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise InvalidationError(f"{field} must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise InvalidationError(f"{field} is out of bounds")
    return value


def _require_sorted_unique_strings(
    value: Any, field: str, *, allow_absence: bool = True
) -> tuple[str, ...]:
    if allow_absence and (value == ABSENCE_TOKEN or value is None):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InvalidationError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_text(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise InvalidationError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise InvalidationError(f"{field} must not contain duplicates")
    if len(items) > MAX_UNITS:
        raise InvalidationError(f"{field} exceeds MAX_UNITS={MAX_UNITS}")
    return items


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    leaked = set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS
    if leaked:
        raise InvalidationError(
            f"secret or nondeterministic fields are forbidden: {sorted(leaked)}"
        )


def _mint_cid(payload: Mapping[str, Any]) -> str:
    try:
        return canonical_cid(dict(payload))
    except IdentityError as exc:
        raise InvalidationError(str(exc)) from exc


def _seq_canonical(values: Sequence[str]) -> list[str] | str:
    return list(values) if values else ABSENCE_TOKEN


def _sorted_unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(items)))


def _trigger_for_change_class(change_class: ChangeClass | str) -> InvalidationTrigger:
    parsed = parse_change_class(change_class)
    # Ordinary documentation maps to the preserve trigger label.
    try:
        return InvalidationTrigger(parsed.value)
    except ValueError as exc:
        raise InvalidationError(
            f"change class {parsed.value!r} has no InvalidationTrigger"
        ) from exc


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InvalidationPolicy:
    """Checkpoint-trigger and broadening policy for invalidation.

    Defaults match plan §6 / §8.1: circuit/key/environment/canonicalization
    force full checkpoints; dependency-lock does so only when opted in;
    truncated closures force full fallback rather than silently narrowing.
    """

    treat_dependency_lock_as_full_fallback: bool = False
    force_full_fallback: bool = False
    is_genesis: bool = False
    uncertain_cache_integrity: bool = False
    release_qualification: bool = False
    dependency_graph_schema_changed: bool = False
    proof_schema_changed: bool = False
    canonicalization_changed: bool = False
    admit_key_migration_proof: bool = False
    admit_schema_migration_proof: bool = False
    truncated_forces_full_fallback: bool = True
    unmapped_relevant_forces_full_fallback: bool = True
    max_delta_chain_depth: int | str = ABSENCE_TOKEN
    current_delta_chain_depth: int = 0
    min_reuse_ratio_bps: int | str = ABSENCE_TOKEN
    estimated_reuse_ratio_bps: int | str = ABSENCE_TOKEN

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "treat_dependency_lock_as_full_fallback",
            _require_bool(
                self.treat_dependency_lock_as_full_fallback,
                "treat_dependency_lock_as_full_fallback",
            ),
        )
        object.__setattr__(
            self,
            "force_full_fallback",
            _require_bool(self.force_full_fallback, "force_full_fallback"),
        )
        object.__setattr__(
            self, "is_genesis", _require_bool(self.is_genesis, "is_genesis")
        )
        object.__setattr__(
            self,
            "uncertain_cache_integrity",
            _require_bool(
                self.uncertain_cache_integrity, "uncertain_cache_integrity"
            ),
        )
        object.__setattr__(
            self,
            "release_qualification",
            _require_bool(self.release_qualification, "release_qualification"),
        )
        object.__setattr__(
            self,
            "dependency_graph_schema_changed",
            _require_bool(
                self.dependency_graph_schema_changed,
                "dependency_graph_schema_changed",
            ),
        )
        object.__setattr__(
            self,
            "proof_schema_changed",
            _require_bool(self.proof_schema_changed, "proof_schema_changed"),
        )
        object.__setattr__(
            self,
            "canonicalization_changed",
            _require_bool(
                self.canonicalization_changed, "canonicalization_changed"
            ),
        )
        object.__setattr__(
            self,
            "admit_key_migration_proof",
            _require_bool(
                self.admit_key_migration_proof, "admit_key_migration_proof"
            ),
        )
        object.__setattr__(
            self,
            "admit_schema_migration_proof",
            _require_bool(
                self.admit_schema_migration_proof, "admit_schema_migration_proof"
            ),
        )
        object.__setattr__(
            self,
            "truncated_forces_full_fallback",
            _require_bool(
                self.truncated_forces_full_fallback,
                "truncated_forces_full_fallback",
            ),
        )
        object.__setattr__(
            self,
            "unmapped_relevant_forces_full_fallback",
            _require_bool(
                self.unmapped_relevant_forces_full_fallback,
                "unmapped_relevant_forces_full_fallback",
            ),
        )

        # Optional integer bounds use typed absence.
        if self.max_delta_chain_depth == ABSENCE_TOKEN:
            object.__setattr__(self, "max_delta_chain_depth", ABSENCE_TOKEN)
        else:
            object.__setattr__(
                self,
                "max_delta_chain_depth",
                _require_nonneg_int(
                    self.max_delta_chain_depth, "max_delta_chain_depth"
                ),
            )
        object.__setattr__(
            self,
            "current_delta_chain_depth",
            _require_nonneg_int(
                self.current_delta_chain_depth, "current_delta_chain_depth"
            ),
        )
        if self.min_reuse_ratio_bps == ABSENCE_TOKEN:
            object.__setattr__(self, "min_reuse_ratio_bps", ABSENCE_TOKEN)
        else:
            bps = _require_nonneg_int(
                self.min_reuse_ratio_bps, "min_reuse_ratio_bps"
            )
            if bps > 10000:
                raise InvalidationError("min_reuse_ratio_bps must be <= 10000")
            object.__setattr__(self, "min_reuse_ratio_bps", bps)
        if self.estimated_reuse_ratio_bps == ABSENCE_TOKEN:
            object.__setattr__(self, "estimated_reuse_ratio_bps", ABSENCE_TOKEN)
        else:
            bps = _require_nonneg_int(
                self.estimated_reuse_ratio_bps, "estimated_reuse_ratio_bps"
            )
            if bps > 10000:
                raise InvalidationError(
                    "estimated_reuse_ratio_bps must be <= 10000"
                )
            object.__setattr__(self, "estimated_reuse_ratio_bps", bps)

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": INVALIDATION_POLICY_SCHEMA,
            "invalidation_subset": INVALIDATION_SUBSET,
            "treat_dependency_lock_as_full_fallback": (
                self.treat_dependency_lock_as_full_fallback
            ),
            "force_full_fallback": self.force_full_fallback,
            "is_genesis": self.is_genesis,
            "uncertain_cache_integrity": self.uncertain_cache_integrity,
            "release_qualification": self.release_qualification,
            "dependency_graph_schema_changed": self.dependency_graph_schema_changed,
            "proof_schema_changed": self.proof_schema_changed,
            "canonicalization_changed": self.canonicalization_changed,
            "admit_key_migration_proof": self.admit_key_migration_proof,
            "admit_schema_migration_proof": self.admit_schema_migration_proof,
            "truncated_forces_full_fallback": self.truncated_forces_full_fallback,
            "unmapped_relevant_forces_full_fallback": (
                self.unmapped_relevant_forces_full_fallback
            ),
            "max_delta_chain_depth": self.max_delta_chain_depth,
            "current_delta_chain_depth": self.current_delta_chain_depth,
            "min_reuse_ratio_bps": self.min_reuse_ratio_bps,
            "estimated_reuse_ratio_bps": self.estimated_reuse_ratio_bps,
        }

    def policy_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> InvalidationPolicy:
        if not isinstance(payload, Mapping):
            raise InvalidationError("InvalidationPolicy payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            treat_dependency_lock_as_full_fallback=bool(
                payload.get("treat_dependency_lock_as_full_fallback", False)
            ),
            force_full_fallback=bool(payload.get("force_full_fallback", False)),
            is_genesis=bool(payload.get("is_genesis", False)),
            uncertain_cache_integrity=bool(
                payload.get("uncertain_cache_integrity", False)
            ),
            release_qualification=bool(
                payload.get("release_qualification", False)
            ),
            dependency_graph_schema_changed=bool(
                payload.get("dependency_graph_schema_changed", False)
            ),
            proof_schema_changed=bool(payload.get("proof_schema_changed", False)),
            canonicalization_changed=bool(
                payload.get("canonicalization_changed", False)
            ),
            admit_key_migration_proof=bool(
                payload.get("admit_key_migration_proof", False)
            ),
            admit_schema_migration_proof=bool(
                payload.get("admit_schema_migration_proof", False)
            ),
            truncated_forces_full_fallback=bool(
                payload.get("truncated_forces_full_fallback", True)
            ),
            unmapped_relevant_forces_full_fallback=bool(
                payload.get("unmapped_relevant_forces_full_fallback", True)
            ),
            max_delta_chain_depth=payload.get(
                "max_delta_chain_depth", ABSENCE_TOKEN
            ),
            current_delta_chain_depth=int(
                payload.get("current_delta_chain_depth", 0)
            ),
            min_reuse_ratio_bps=payload.get("min_reuse_ratio_bps", ABSENCE_TOKEN),
            estimated_reuse_ratio_bps=payload.get(
                "estimated_reuse_ratio_bps", ABSENCE_TOKEN
            ),
        )


# ---------------------------------------------------------------------------
# Full-fallback decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FullFallbackDecision:
    """Deterministic full-checkpoint classification."""

    required: bool
    reasons: tuple[str, ...]
    complete: bool
    broadens_invalidation: bool
    change_classes: tuple[str, ...]
    policy_cid: str
    schema: str = FULL_FALLBACK_DECISION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "required", _require_bool(self.required, "required")
        )
        reasons = _require_sorted_unique_strings(
            self.reasons, "reasons", allow_absence=False
        )
        for reason in reasons:
            parse_full_fallback_reason(reason)
        if len(reasons) > MAX_REASONS:
            raise InvalidationError("reasons exceeds bound")
        object.__setattr__(self, "reasons", reasons)
        if self.required and not reasons:
            raise InvalidationError(
                "full fallback required must list at least one closed reason"
            )
        if not self.required and reasons:
            raise InvalidationError(
                "full fallback reasons must be empty when not required"
            )
        object.__setattr__(
            self, "complete", _require_bool(self.complete, "complete")
        )
        object.__setattr__(
            self,
            "broadens_invalidation",
            _require_bool(self.broadens_invalidation, "broadens_invalidation"),
        )
        classes = _require_sorted_unique_strings(
            self.change_classes, "change_classes", allow_absence=False
        )
        for name in classes:
            parse_change_class(name)
        object.__setattr__(self, "change_classes", classes)
        object.__setattr__(
            self, "policy_cid", _require_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(self, "schema", _require_text(self.schema, "schema"))
        if self.schema != FULL_FALLBACK_DECISION_SCHEMA:
            raise InvalidationError(
                f"schema must be {FULL_FALLBACK_DECISION_SCHEMA}"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "invalidation_subset": INVALIDATION_SUBSET,
            "required": self.required,
            "reasons": _seq_canonical(self.reasons),
            "complete": self.complete,
            "broadens_invalidation": self.broadens_invalidation,
            "change_classes": _seq_canonical(self.change_classes),
            "policy_cid": self.policy_cid,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def decision_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> FullFallbackDecision:
        if not isinstance(payload, Mapping):
            raise InvalidationError(
                "FullFallbackDecision payload must be a mapping"
            )
        _reject_secret_fields(payload)
        reasons = payload.get("reasons", ABSENCE_TOKEN)
        classes = payload.get("change_classes", ABSENCE_TOKEN)
        return cls(
            required=bool(payload.get("required", False)),
            reasons=(
                ()
                if reasons == ABSENCE_TOKEN
                else tuple(str(item) for item in reasons or ())
            ),
            complete=bool(payload.get("complete", True)),
            broadens_invalidation=bool(
                payload.get("broadens_invalidation", False)
            ),
            change_classes=(
                ()
                if classes == ABSENCE_TOKEN
                else tuple(str(item) for item in classes or ())
            ),
            policy_cid=str(payload.get("policy_cid") or ""),
            schema=str(payload.get("schema") or FULL_FALLBACK_DECISION_SCHEMA),
        )


def classify_full_fallback(
    *,
    change_classes: Sequence[str] | None = None,
    repository_diff: RepositoryDiff | None = None,
    policy: InvalidationPolicy | None = None,
    closure_complete: bool = True,
    unmapped_relevant_changes: bool = False,
    incremental_reuse_justified: bool = True,
) -> FullFallbackDecision:
    """Classify whether a full checkpoint is mandatory.

    Combines repository-diff flags, change-class rules, truncated/unmapped
    closure signals, and explicit InvalidationPolicy triggers.  Admitted key
    or schema migration proofs may suppress the corresponding class triggers
    only; they never suppress genesis, ambiguous, or cache-integrity reasons.
    """

    active = policy if policy is not None else InvalidationPolicy()
    if not isinstance(active, InvalidationPolicy):
        raise InvalidationError("policy must be an InvalidationPolicy")
    closure_complete = _require_bool(closure_complete, "closure_complete")
    unmapped_relevant_changes = _require_bool(
        unmapped_relevant_changes, "unmapped_relevant_changes"
    )
    incremental_reuse_justified = _require_bool(
        incremental_reuse_justified, "incremental_reuse_justified"
    )

    classes: set[str] = set()
    if change_classes is not None:
        if not isinstance(change_classes, Sequence) or isinstance(
            change_classes, (str, bytes)
        ):
            raise InvalidationError("change_classes must be a sequence of strings")
        for item in change_classes:
            classes.add(parse_change_class(item).value)

    diff_ambiguous = False
    diff_incomplete = False
    diff_full = False
    diff_broad = False
    if repository_diff is not None:
        if not isinstance(repository_diff, RepositoryDiff):
            raise InvalidationError("repository_diff must be a RepositoryDiff")
        classes.update(repository_diff.change_classes_present)
        diff_ambiguous = repository_diff.ambiguous
        diff_incomplete = not repository_diff.inventory_complete
        diff_full = repository_diff.full_fallback_required
        diff_broad = repository_diff.requires_broad_invalidation

    reasons: set[str] = set()

    if active.is_genesis:
        reasons.add(FullFallbackReason.GENESIS.value)
    if active.force_full_fallback:
        reasons.add(FullFallbackReason.EXPLICIT_POLICY.value)
    if active.uncertain_cache_integrity:
        reasons.add(FullFallbackReason.UNCERTAIN_CACHE_INTEGRITY.value)
    if active.release_qualification:
        reasons.add(FullFallbackReason.RELEASE_QUALIFICATION.value)

    if active.canonicalization_changed and not active.admit_schema_migration_proof:
        reasons.add(FullFallbackReason.CANONICALIZATION_CHANGED.value)
    if (
        active.dependency_graph_schema_changed
        and not active.admit_schema_migration_proof
    ):
        reasons.add(FullFallbackReason.DEPENDENCY_GRAPH_SCHEMA_CHANGED.value)
    if active.proof_schema_changed and not active.admit_schema_migration_proof:
        reasons.add(FullFallbackReason.PROOF_SCHEMA_CHANGED.value)

    for change_class, reason in _CLASS_TO_FALLBACK_REASON.items():
        if change_class not in classes:
            continue
        if (
            change_class
            in {
                ChangeClass.CIRCUIT.value,
                ChangeClass.PROVING_KEY.value,
                ChangeClass.VERIFICATION_KEY.value,
            }
            and active.admit_key_migration_proof
        ):
            continue
        if (
            change_class == ChangeClass.CANONICALIZATION.value
            and active.admit_schema_migration_proof
        ):
            continue
        reasons.add(reason)

    if (
        active.treat_dependency_lock_as_full_fallback
        and ChangeClass.DEPENDENCY_LOCK.value in classes
    ):
        reasons.add(FullFallbackReason.DEPENDENCY_LOCK_POLICY.value)

    if diff_ambiguous:
        reasons.add(FullFallbackReason.AMBIGUOUS_DIFF.value)
    if diff_incomplete:
        reasons.add(FullFallbackReason.INCOMPLETE_INVENTORY.value)
    if repository_diff is not None:
        if repository_diff.is_merge and not repository_diff.merge_resolved:
            reasons.add(FullFallbackReason.UNRESOLVED_MERGE.value)
        # Diff algorithm may require full fallback for lock-policy, repository-id
        # mismatch, or other residual cases not re-derived above.
        if diff_full and not reasons:
            if repository_diff.ambiguous:
                reasons.add(FullFallbackReason.AMBIGUOUS_DIFF.value)
            elif (
                ChangeClass.DEPENDENCY_LOCK.value in classes
                and FullFallbackReason.DEPENDENCY_LOCK_POLICY.value not in reasons
            ):
                reasons.add(FullFallbackReason.DEPENDENCY_LOCK_POLICY.value)
            else:
                reasons.add(FullFallbackReason.INCREMENTAL_REUSE_UNJUSTIFIED.value)

    if not closure_complete and active.truncated_forces_full_fallback:
        reasons.add(FullFallbackReason.TRUNCATED_CLOSURE.value)
    if unmapped_relevant_changes and active.unmapped_relevant_forces_full_fallback:
        reasons.add(FullFallbackReason.UNMAPPED_RELEVANT_CHANGE.value)

    if (
        active.max_delta_chain_depth != ABSENCE_TOKEN
        and active.current_delta_chain_depth >= active.max_delta_chain_depth
    ):
        reasons.add(FullFallbackReason.EXCESSIVE_DELTA_CHAIN_DEPTH.value)

    if (
        active.min_reuse_ratio_bps != ABSENCE_TOKEN
        and active.estimated_reuse_ratio_bps != ABSENCE_TOKEN
        and active.estimated_reuse_ratio_bps < active.min_reuse_ratio_bps
    ):
        reasons.add(FullFallbackReason.LOW_REUSE_RATIO.value)

    if not incremental_reuse_justified:
        reasons.add(FullFallbackReason.INCREMENTAL_REUSE_UNJUSTIFIED.value)

    required = bool(reasons)
    broad = (
        required
        or diff_broad
        or bool(classes & BROAD_INVALIDATION_CHANGE_CLASSES)
        or bool(classes & FULL_FALLBACK_CHANGE_CLASSES)
        or not closure_complete
        or unmapped_relevant_changes
    )
    complete = closure_complete and not unmapped_relevant_changes and not diff_ambiguous

    return FullFallbackDecision(
        required=required,
        reasons=tuple(sorted(reasons)),
        complete=complete,
        broadens_invalidation=broad,
        change_classes=tuple(sorted(classes)),
        policy_cid=active.policy_cid(),
    )


# ---------------------------------------------------------------------------
# Unit disposition and closure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitDisposition:
    """Per-unit outcome of invalidation (prove / preserve / remove / invalidate)."""

    unit_id: str
    kind: UnitDispositionKind
    triggers: tuple[str, ...]
    seed_node_ids: tuple[str, ...]
    reason: str = ABSENCE_TOKEN

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "unit_id", _require_text(self.unit_id, "unit_id")
        )
        object.__setattr__(self, "kind", parse_unit_disposition_kind(self.kind))
        triggers = _require_sorted_unique_strings(
            self.triggers, "triggers", allow_absence=False
        )
        for trigger in triggers:
            parse_invalidation_trigger(trigger)
        object.__setattr__(self, "triggers", triggers)
        object.__setattr__(
            self,
            "seed_node_ids",
            _require_sorted_unique_strings(
                self.seed_node_ids, "seed_node_ids", allow_absence=False
            ),
        )
        if self.reason == ABSENCE_TOKEN:
            object.__setattr__(self, "reason", ABSENCE_TOKEN)
        else:
            object.__setattr__(
                self, "reason", _require_text(self.reason, "reason")
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": UNIT_DISPOSITION_SCHEMA,
            "unit_id": self.unit_id,
            "kind": self.kind.value,
            "triggers": _seq_canonical(self.triggers),
            "seed_node_ids": _seq_canonical(self.seed_node_ids),
            "reason": self.reason,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> UnitDisposition:
        if not isinstance(payload, Mapping):
            raise InvalidationError("UnitDisposition payload must be a mapping")
        _reject_secret_fields(payload)
        triggers = payload.get("triggers", ABSENCE_TOKEN)
        seeds = payload.get("seed_node_ids", ABSENCE_TOKEN)
        return cls(
            unit_id=str(payload.get("unit_id") or ""),
            kind=payload.get("kind") or "",
            triggers=(
                ()
                if triggers == ABSENCE_TOKEN
                else tuple(str(item) for item in triggers or ())
            ),
            seed_node_ids=(
                ()
                if seeds == ABSENCE_TOKEN
                else tuple(str(item) for item in seeds or ())
            ),
            reason=payload.get("reason", ABSENCE_TOKEN),
        )


@dataclass(frozen=True, slots=True)
class InvalidationClosure:
    """Complete deterministic invalidation result for one repository transition."""

    invalidated_unit_ids: tuple[str, ...]
    preserved_unit_ids: tuple[str, ...]
    added_unit_ids: tuple[str, ...]
    removed_unit_ids: tuple[str, ...]
    unauthorized_removal_unit_ids: tuple[str, ...]
    affected_aggregate_ids: tuple[str, ...]
    seed_node_ids: tuple[str, ...]
    closure_node_ids: tuple[str, ...]
    change_classes: tuple[str, ...]
    triggers: tuple[str, ...]
    dispositions: tuple[UnitDisposition, ...]
    full_fallback: FullFallbackDecision
    complete: bool
    docs_only: bool
    dependency_graph_schema_version: str = DEPENDENCY_GRAPH_SCHEMA_VERSION
    invalidation_schema_version: str = INVALIDATION_SCHEMA_VERSION
    schema: str = INVALIDATION_CLOSURE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "invalidated_unit_ids",
            _require_sorted_unique_strings(
                self.invalidated_unit_ids, "invalidated_unit_ids"
            ),
        )
        object.__setattr__(
            self,
            "preserved_unit_ids",
            _require_sorted_unique_strings(
                self.preserved_unit_ids, "preserved_unit_ids"
            ),
        )
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
            "unauthorized_removal_unit_ids",
            _require_sorted_unique_strings(
                self.unauthorized_removal_unit_ids,
                "unauthorized_removal_unit_ids",
            ),
        )
        object.__setattr__(
            self,
            "affected_aggregate_ids",
            _require_sorted_unique_strings(
                self.affected_aggregate_ids, "affected_aggregate_ids"
            ),
        )
        object.__setattr__(
            self,
            "seed_node_ids",
            _require_sorted_unique_strings(self.seed_node_ids, "seed_node_ids"),
        )
        object.__setattr__(
            self,
            "closure_node_ids",
            _require_sorted_unique_strings(
                self.closure_node_ids, "closure_node_ids"
            ),
        )
        classes = _require_sorted_unique_strings(
            self.change_classes, "change_classes"
        )
        for name in classes:
            parse_change_class(name)
        object.__setattr__(self, "change_classes", classes)
        triggers = _require_sorted_unique_strings(self.triggers, "triggers")
        for trigger in triggers:
            parse_invalidation_trigger(trigger)
        object.__setattr__(self, "triggers", triggers)

        if not isinstance(self.dispositions, tuple):
            object.__setattr__(self, "dispositions", tuple(self.dispositions))
        ordered = tuple(
            sorted(self.dispositions, key=lambda item: item.unit_id)
        )
        if ordered != self.dispositions:
            raise InvalidationError(
                "dispositions must be canonically sorted by unit_id"
            )
        for item in self.dispositions:
            if not isinstance(item, UnitDisposition):
                raise InvalidationError(
                    "dispositions must contain UnitDisposition records"
                )
        if not isinstance(self.full_fallback, FullFallbackDecision):
            raise InvalidationError(
                "full_fallback must be a FullFallbackDecision"
            )
        object.__setattr__(
            self, "complete", _require_bool(self.complete, "complete")
        )
        object.__setattr__(
            self, "docs_only", _require_bool(self.docs_only, "docs_only")
        )
        object.__setattr__(
            self,
            "dependency_graph_schema_version",
            _require_text(
                self.dependency_graph_schema_version,
                "dependency_graph_schema_version",
            ),
        )
        object.__setattr__(
            self,
            "invalidation_schema_version",
            _require_text(
                self.invalidation_schema_version, "invalidation_schema_version"
            ),
        )
        object.__setattr__(self, "schema", _require_text(self.schema, "schema"))
        if self.schema != INVALIDATION_CLOSURE_SCHEMA:
            raise InvalidationError(
                f"schema must be {INVALIDATION_CLOSURE_SCHEMA}"
            )

        # Partition consistency: a unit cannot be both preserved and invalidated.
        overlap = set(self.invalidated_unit_ids) & set(self.preserved_unit_ids)
        if overlap:
            raise InvalidationError(
                f"units cannot be both invalidated and preserved: {sorted(overlap)}"
            )
        # Unauthorized removals must be a subset of removed units.
        if not set(self.unauthorized_removal_unit_ids) <= set(
            self.removed_unit_ids
        ):
            raise InvalidationError(
                "unauthorized_removal_unit_ids must be a subset of removed_unit_ids"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "invalidation_subset": INVALIDATION_SUBSET,
            "invalidation_schema_version": self.invalidation_schema_version,
            "dependency_graph_schema_version": self.dependency_graph_schema_version,
            "invalidated_unit_ids": _seq_canonical(self.invalidated_unit_ids),
            "preserved_unit_ids": _seq_canonical(self.preserved_unit_ids),
            "added_unit_ids": _seq_canonical(self.added_unit_ids),
            "removed_unit_ids": _seq_canonical(self.removed_unit_ids),
            "unauthorized_removal_unit_ids": _seq_canonical(
                self.unauthorized_removal_unit_ids
            ),
            "affected_aggregate_ids": _seq_canonical(self.affected_aggregate_ids),
            "seed_node_ids": _seq_canonical(self.seed_node_ids),
            "closure_node_ids": _seq_canonical(self.closure_node_ids),
            "change_classes": _seq_canonical(self.change_classes),
            "triggers": _seq_canonical(self.triggers),
            "dispositions": [item.to_canonical() for item in self.dispositions],
            "full_fallback": self.full_fallback.to_canonical(),
            "complete": self.complete,
            "docs_only": self.docs_only,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def closure_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    def disposition_for(self, unit_id: str) -> UnitDisposition:
        unit_id = _require_text(unit_id, "unit_id")
        for item in self.dispositions:
            if item.unit_id == unit_id:
                return item
        raise InvalidationError(f"no disposition for unit {unit_id!r}")

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> InvalidationClosure:
        if not isinstance(payload, Mapping):
            raise InvalidationError(
                "InvalidationClosure payload must be a mapping"
            )
        _reject_secret_fields(payload)

        def _seq(key: str) -> tuple[str, ...]:
            raw = payload.get(key, ABSENCE_TOKEN)
            if raw == ABSENCE_TOKEN or raw is None:
                return ()
            return tuple(str(item) for item in raw)

        dispositions_raw = payload.get("dispositions") or ()
        if not isinstance(dispositions_raw, Sequence) or isinstance(
            dispositions_raw, (str, bytes)
        ):
            raise InvalidationError("dispositions must be a sequence")
        dispositions = tuple(
            UnitDisposition.from_canonical(item)  # type: ignore[arg-type]
            for item in dispositions_raw
        )
        fallback_raw = payload.get("full_fallback")
        if not isinstance(fallback_raw, Mapping):
            raise InvalidationError("full_fallback must be a mapping")
        return cls(
            invalidated_unit_ids=_seq("invalidated_unit_ids"),
            preserved_unit_ids=_seq("preserved_unit_ids"),
            added_unit_ids=_seq("added_unit_ids"),
            removed_unit_ids=_seq("removed_unit_ids"),
            unauthorized_removal_unit_ids=_seq("unauthorized_removal_unit_ids"),
            affected_aggregate_ids=_seq("affected_aggregate_ids"),
            seed_node_ids=_seq("seed_node_ids"),
            closure_node_ids=_seq("closure_node_ids"),
            change_classes=_seq("change_classes"),
            triggers=_seq("triggers"),
            dispositions=dispositions,
            full_fallback=FullFallbackDecision.from_canonical(fallback_raw),
            complete=bool(payload.get("complete", False)),
            docs_only=bool(payload.get("docs_only", False)),
            dependency_graph_schema_version=str(
                payload.get("dependency_graph_schema_version")
                or DEPENDENCY_GRAPH_SCHEMA_VERSION
            ),
            invalidation_schema_version=str(
                payload.get("invalidation_schema_version")
                or INVALIDATION_SCHEMA_VERSION
            ),
            schema=str(payload.get("schema") or INVALIDATION_CLOSURE_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Seed resolution
# ---------------------------------------------------------------------------


def _normalize_path_to_node_ids(
    path_to_node_ids: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    if path_to_node_ids is None:
        return {}
    if not isinstance(path_to_node_ids, Mapping):
        raise InvalidationError("path_to_node_ids must be a mapping")
    if len(path_to_node_ids) > MAX_PATH_MAPPINGS:
        raise InvalidationError("path_to_node_ids exceeds bound")
    result: dict[str, tuple[str, ...]] = {}
    for path, nodes in path_to_node_ids.items():
        path_text = _require_text(path, "path_to_node_ids.path")
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            raise InvalidationError(
                "path_to_node_ids values must be sequences of node ids"
            )
        result[path_text] = _require_sorted_unique_strings(
            tuple(nodes), f"path_to_node_ids[{path_text}]"
        )
    return result


def _candidate_node_ids_for_path(path: str) -> tuple[str, ...]:
    """Deterministic candidate node ids derived from a repository path."""

    return (
        path,
        f"artifact/{path}",
        f"fixture/{path}",
        f"config/{path}",
        f"schema/{path}",
        f"unit/{path}",
    )


def resolve_seed_nodes(
    graph: ProofDependencyGraph,
    *,
    changed_node_ids: Sequence[str] = (),
    changed_artifacts: Sequence[ChangedArtifact] = (),
    path_to_node_ids: Mapping[str, Sequence[str]] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], bool, tuple[str, ...]]:
    """Resolve changed artifacts/nodes into graph seed ids.

    Returns ``(seed_node_ids, change_classes, unmapped_relevant, triggers)``.
    Ordinary documentation never contributes seeds.  Unmapped non-preserve
    changes set ``unmapped_relevant`` so callers can broaden or fall back.
    """

    if not isinstance(graph, ProofDependencyGraph):
        raise InvalidationError("graph must be a ProofDependencyGraph")

    mapping = _normalize_path_to_node_ids(path_to_node_ids)
    seeds: set[str] = set()
    classes: set[str] = set()
    triggers: set[str] = set()
    unmapped_relevant = False

    if not isinstance(changed_node_ids, Sequence) or isinstance(
        changed_node_ids, (str, bytes)
    ):
        raise InvalidationError("changed_node_ids must be a sequence of strings")
    for node_id in changed_node_ids:
        text = _require_text(node_id, "changed_node_ids")
        if not graph.has_node(text):
            raise InvalidationError(f"unknown changed node {text!r}")
        seeds.add(text)
        triggers.add(InvalidationTrigger.SEED_NODE.value)

    if not isinstance(changed_artifacts, Sequence) or isinstance(
        changed_artifacts, (str, bytes)
    ):
        raise InvalidationError(
            "changed_artifacts must be a sequence of ChangedArtifact"
        )
    for artifact in changed_artifacts:
        if not isinstance(artifact, ChangedArtifact):
            raise InvalidationError(
                "changed_artifacts must contain ChangedArtifact records"
            )
        change_class = artifact.change_class
        classes.add(change_class.value)
        trigger = _trigger_for_change_class(change_class)
        triggers.add(trigger.value)

        if change_class.value in PRESERVE_CHANGE_CLASSES:
            # Docs-only: record the class/trigger but do not seed invalidation.
            continue

        # Explicit add/delete of tests become triggers even when node mapping
        # is supplied separately via added/removed unit ids.
        if (
            change_class is ChangeClass.TEST_SOURCE
            and artifact.change_action is ChangeAction.ADDED
        ):
            triggers.add(InvalidationTrigger.TEST_ADDED.value)
        if (
            change_class is ChangeClass.TEST_SOURCE
            and artifact.change_action is ChangeAction.DELETED
        ):
            triggers.add(InvalidationTrigger.TEST_DELETED.value)

        candidates: list[str] = []
        if artifact.path in mapping:
            candidates.extend(mapping[artifact.path])
        for candidate in _candidate_node_ids_for_path(artifact.path):
            if graph.has_node(candidate):
                candidates.append(candidate)
        # Label match: any node whose label equals the path.
        for node in graph.nodes():
            if node.label == artifact.path:
                candidates.append(node.node_id)

        resolved = sorted(set(candidates))
        if not resolved:
            unmapped_relevant = True
            continue
        for node_id in resolved:
            if not graph.has_node(node_id):
                raise InvalidationError(
                    f"path_to_node_ids maps {artifact.path!r} to unknown node "
                    f"{node_id!r}"
                )
            seeds.add(node_id)

    return (
        tuple(sorted(seeds)),
        tuple(sorted(classes)),
        unmapped_relevant,
        tuple(sorted(triggers)),
    )


def _aggregate_node_ids(
    graph: ProofDependencyGraph, node_ids: Iterable[str]
) -> tuple[str, ...]:
    aggregates: list[str] = []
    for node_id in node_ids:
        if not graph.has_node(node_id):
            continue
        if graph.get_node(node_id).kind is DependencyNodeKind.AGGREGATE:
            aggregates.append(node_id)
    return tuple(sorted(set(aggregates)))


def _leaf_unit_node_ids(
    graph: ProofDependencyGraph, node_ids: Iterable[str]
) -> tuple[str, ...]:
    leaves: list[str] = []
    for node_id in node_ids:
        if not graph.has_node(node_id):
            continue
        if graph.get_node(node_id).kind is DependencyNodeKind.UNIT:
            leaves.append(node_id)
    return tuple(sorted(set(leaves)))


# ---------------------------------------------------------------------------
# compute_invalidation_closure
# ---------------------------------------------------------------------------


def compute_invalidation_closure(
    graph: ProofDependencyGraph,
    *,
    changed_node_ids: Sequence[str] = (),
    changed_artifacts: Sequence[ChangedArtifact] = (),
    repository_diff: RepositoryDiff | None = None,
    path_to_node_ids: Mapping[str, Sequence[str]] | None = None,
    known_unit_ids: Sequence[str] = (),
    added_unit_ids: Sequence[str] = (),
    removed_unit_ids: Sequence[str] = (),
    authorized_removal_unit_ids: Sequence[str] = (),
    policy: InvalidationPolicy | None = None,
    incremental_reuse_justified: bool = True,
) -> InvalidationClosure:
    """Compute the exact invalidation closure for a repository transition.

    Walks forward from changed prerequisites.  Ordinary documentation never
    seeds invalidation.  Added selected units are ``prove_new``; deleted units
    require authorization.  Full-fallback forces every known unit into the
    invalidated set so incremental reuse cannot be justified by omission.
    """

    if not isinstance(graph, ProofDependencyGraph):
        raise InvalidationError("graph must be a ProofDependencyGraph")
    active = policy if policy is not None else InvalidationPolicy()
    if not isinstance(active, InvalidationPolicy):
        raise InvalidationError("policy must be an InvalidationPolicy")

    # Accept unsorted inputs for known/added/removed by normalizing.
    if not isinstance(known_unit_ids, Sequence) or isinstance(
        known_unit_ids, (str, bytes)
    ):
        raise InvalidationError("known_unit_ids must be a sequence")
    if not isinstance(added_unit_ids, Sequence) or isinstance(
        added_unit_ids, (str, bytes)
    ):
        raise InvalidationError("added_unit_ids must be a sequence")
    if not isinstance(removed_unit_ids, Sequence) or isinstance(
        removed_unit_ids, (str, bytes)
    ):
        raise InvalidationError("removed_unit_ids must be a sequence")
    if not isinstance(authorized_removal_unit_ids, Sequence) or isinstance(
        authorized_removal_unit_ids, (str, bytes)
    ):
        raise InvalidationError("authorized_removal_unit_ids must be a sequence")
    known = _sorted_unique(
        _require_text(item, "known_unit_ids") for item in known_unit_ids
    )
    added = _sorted_unique(
        _require_text(item, "added_unit_ids") for item in added_unit_ids
    )
    removed = _sorted_unique(
        _require_text(item, "removed_unit_ids") for item in removed_unit_ids
    )
    authorized = _sorted_unique(
        _require_text(item, "authorized_removal_unit_ids")
        for item in authorized_removal_unit_ids
    )
    if not set(authorized) <= set(removed):
        raise InvalidationError(
            "authorized_removal_unit_ids must be a subset of removed_unit_ids"
        )
    unauthorized = _sorted_unique(set(removed) - set(authorized))

    artifacts: list[ChangedArtifact] = list(changed_artifacts or ())
    if repository_diff is not None:
        if not isinstance(repository_diff, RepositoryDiff):
            raise InvalidationError("repository_diff must be a RepositoryDiff")
        if not artifacts:
            artifacts = list(repository_diff.changed_artifacts)

    seeds, classes_from_artifacts, unmapped, triggers = resolve_seed_nodes(
        graph,
        changed_node_ids=changed_node_ids,
        changed_artifacts=artifacts,
        path_to_node_ids=path_to_node_ids,
    )

    classes: set[str] = set(classes_from_artifacts)
    if repository_diff is not None:
        classes.update(repository_diff.change_classes_present)

    trigger_set: set[str] = set(triggers)

    # Explicit add/delete rules from unit id sets.
    if added:
        trigger_set.add(InvalidationTrigger.TEST_ADDED.value)
    if removed:
        trigger_set.add(InvalidationTrigger.TEST_DELETED.value)

    docs_only = bool(classes) and classes <= PRESERVE_CHANGE_CLASSES and not seeds

    # Forward walk from seeds.
    closure_nodes: tuple[str, ...]
    closure_complete = True
    if seeds:
        try:
            closure_nodes = graph.invalidation_closure(seeds)
        except DependencyGraphError as exc:
            raise InvalidationError(str(exc)) from exc
        closure_complete = graph.closure_is_complete(closure_nodes)
        if not closure_complete:
            trigger_set.add(InvalidationTrigger.TRUNCATED_FRONTIER.value)
    else:
        closure_nodes = ()

    # Broaden: when unmapped relevant or broad classes, every known unit is
    # considered potentially affected (never narrow).
    broad_classes = bool(classes & BROAD_INVALIDATION_CHANGE_CLASSES)

    fallback = classify_full_fallback(
        change_classes=tuple(sorted(classes)),
        repository_diff=repository_diff,
        policy=active,
        closure_complete=closure_complete,
        unmapped_relevant_changes=unmapped,
        incremental_reuse_justified=incremental_reuse_justified,
    )
    if fallback.required:
        trigger_set.add(InvalidationTrigger.FULL_FALLBACK.value)
    triggers = tuple(sorted(trigger_set))

    # Determine invalidated leaf units and aggregates.
    invalidated: set[str] = set()
    aggregates: set[str] = set()

    if fallback.required or unmapped or (broad_classes and not seeds):
        # Full fallback or unmapped relevant change: invalidate every known unit.
        invalidated.update(known)
        # Also invalidate every unit/aggregate node in the graph that is known
        # or present as a unit-like node.
        for node in graph.nodes():
            if node.kind is DependencyNodeKind.UNIT:
                if not known or node.node_id in known or node.node_id in added:
                    invalidated.add(node.node_id)
            if node.kind is DependencyNodeKind.AGGREGATE:
                aggregates.add(node.node_id)
                invalidated.add(node.node_id)
    else:
        leaf_units = _leaf_unit_node_ids(graph, closure_nodes)
        agg_nodes = _aggregate_node_ids(graph, closure_nodes)
        aggregates.update(agg_nodes)
        # Restrict to known units when a known set is supplied; otherwise take
        # every unit-like node reached by the walk.
        if known:
            known_set = set(known)
            for unit_id in leaf_units:
                if unit_id in known_set:
                    invalidated.add(unit_id)
            # Aggregates that are also in the known set.
            for agg_id in agg_nodes:
                if agg_id in known_set:
                    invalidated.add(agg_id)
            # Broad classes: any known unit whose dependency root is incomplete
            # relative to the change still only invalidates the forward walk,
            # but also any known unit that is a direct graph node seed target.
            if broad_classes:
                # Interface/lock/policy etc. already expanded via seeds when
                # mapped; when seeds exist the walk is authoritative.
                pass
        else:
            invalidated.update(leaf_units)
            invalidated.update(agg_nodes)

        # Seeds that are themselves units are invalidated.
        for seed in seeds:
            if graph.has_node(seed):
                kind = graph.get_node(seed).kind
                if kind is DependencyNodeKind.UNIT:
                    if not known or seed in known:
                        invalidated.add(seed)
                if kind is DependencyNodeKind.AGGREGATE:
                    aggregates.add(seed)
                    if not known or seed in known:
                        invalidated.add(seed)

    # Removed units leave the active set; they are not "invalidated" for re-proof.
    invalidated -= set(removed)
    # Added units are proven new, not reused; exclude from preserve, include
    # separately.
    invalidated -= set(added)

    # Preserved = known units not invalidated, not removed, not added.
    if known:
        preserved = _sorted_unique(
            set(known) - invalidated - set(removed) - set(added)
        )
    else:
        # Without a known set, preserved is empty (cannot claim reuse).
        preserved = ()

    # Docs-only transitions preserve every known unit.
    if docs_only and not fallback.required:
        preserved = _sorted_unique(set(known) | set(preserved))
        invalidated = set()
        aggregates = set()

    # Build dispositions.
    dispositions: list[UnitDisposition] = []
    seed_tuple = seeds

    for unit_id in sorted(invalidated):
        unit_triggers = [
            t
            for t in triggers
            if t
            not in {
                InvalidationTrigger.TEST_ADDED.value,
                InvalidationTrigger.TEST_DELETED.value,
                InvalidationTrigger.ORDINARY_DOCUMENTATION.value,
            }
        ]
        if not unit_triggers:
            unit_triggers = [InvalidationTrigger.SEED_NODE.value]
        dispositions.append(
            UnitDisposition(
                unit_id=unit_id,
                kind=UnitDispositionKind.INVALIDATE,
                triggers=_sorted_unique(unit_triggers),
                seed_node_ids=seed_tuple,
                reason="forward_invalidation",
            )
        )
    for unit_id in preserved:
        dispositions.append(
            UnitDisposition(
                unit_id=unit_id,
                kind=UnitDispositionKind.PRESERVE,
                triggers=(
                    (InvalidationTrigger.ORDINARY_DOCUMENTATION.value,)
                    if docs_only
                    else ()
                ),
                seed_node_ids=(),
                reason="outside_invalidation_closure",
            )
        )
    for unit_id in added:
        dispositions.append(
            UnitDisposition(
                unit_id=unit_id,
                kind=UnitDispositionKind.PROVE_NEW,
                triggers=(InvalidationTrigger.TEST_ADDED.value,),
                seed_node_ids=(),
                reason="added_selected_unit",
            )
        )
    for unit_id in removed:
        if unit_id in unauthorized:
            kind = UnitDispositionKind.REMOVE_REQUIRES_AUTHORIZATION
            reason = "deleted_unit_requires_authorization"
        else:
            kind = UnitDispositionKind.REMOVE_AUTHORIZED
            reason = "deleted_unit_authorized"
        dispositions.append(
            UnitDisposition(
                unit_id=unit_id,
                kind=kind,
                triggers=(InvalidationTrigger.TEST_DELETED.value,),
                seed_node_ids=(),
                reason=reason,
            )
        )

    dispositions_tuple = tuple(
        sorted(dispositions, key=lambda item: item.unit_id)
    )

    complete = (
        closure_complete
        and not unmapped
        and fallback.complete
        and not unauthorized
    )

    return InvalidationClosure(
        invalidated_unit_ids=_sorted_unique(invalidated),
        preserved_unit_ids=preserved,
        added_unit_ids=added,
        removed_unit_ids=removed,
        unauthorized_removal_unit_ids=unauthorized,
        affected_aggregate_ids=_sorted_unique(aggregates),
        seed_node_ids=seeds,
        closure_node_ids=closure_nodes if not fallback.required else _sorted_unique(
            list(closure_nodes) + list(invalidated) + list(aggregates)
        ),
        change_classes=tuple(sorted(classes)),
        triggers=triggers,
        dispositions=dispositions_tuple,
        full_fallback=fallback,
        complete=complete,
        docs_only=docs_only,
    )


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChangedKeyField:
    """One cache-key / statement field affected by the invalidating change."""

    field_name: str
    change_classes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "field_name",
            _require_text(self.field_name, "field_name"),
        )
        classes = _require_sorted_unique_strings(
            self.change_classes, "change_classes"
        )
        for name in classes:
            parse_change_class(name)
        object.__setattr__(self, "change_classes", classes)

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": CHANGED_KEY_FIELD_SCHEMA,
            "field_name": self.field_name,
            "change_classes": _seq_canonical(self.change_classes),
        }

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ChangedKeyField:
        if not isinstance(payload, Mapping):
            raise InvalidationError("ChangedKeyField payload must be a mapping")
        classes = payload.get("change_classes", ABSENCE_TOKEN)
        return cls(
            field_name=str(payload.get("field_name") or ""),
            change_classes=(
                ()
                if classes == ABSENCE_TOKEN
                else tuple(str(item) for item in classes or ())
            ),
        )


@dataclass(frozen=True, slots=True)
class ExplanationPath:
    """One deterministic prerequisite -> dependent edge path."""

    edge_from_ids: tuple[str, ...]
    edge_to_ids: tuple[str, ...]
    edge_types: tuple[str, ...]
    reason_cids: tuple[str, ...]

    def __post_init__(self) -> None:
        from_ids = tuple(
            _require_text(item, "edge_from_ids") for item in self.edge_from_ids
        )
        to_ids = tuple(
            _require_text(item, "edge_to_ids") for item in self.edge_to_ids
        )
        types = tuple(_require_text(item, "edge_types") for item in self.edge_types)
        reasons = tuple(
            _require_cid(item, "reason_cids") for item in self.reason_cids
        )
        if not (len(from_ids) == len(to_ids) == len(types) == len(reasons)):
            raise InvalidationError(
                "explanation path edge fields must have equal length"
            )
        if len(from_ids) > MAX_EXPLANATION_PATH_EDGES:
            raise InvalidationError("explanation path exceeds depth bound")
        object.__setattr__(self, "edge_from_ids", from_ids)
        object.__setattr__(self, "edge_to_ids", to_ids)
        object.__setattr__(self, "edge_types", types)
        object.__setattr__(self, "reason_cids", reasons)

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": EXPLANATION_PATH_SCHEMA,
            "edge_from_ids": list(self.edge_from_ids),
            "edge_to_ids": list(self.edge_to_ids),
            "edge_types": list(self.edge_types),
            "reason_cids": list(self.reason_cids),
        }

    @classmethod
    def from_edges(cls, edges: Sequence[ProofDependencyEdge]) -> ExplanationPath:
        return cls(
            edge_from_ids=tuple(edge.from_id for edge in edges),
            edge_to_ids=tuple(edge.to_id for edge in edges),
            edge_types=tuple(edge.edge_type.value for edge in edges),
            reason_cids=tuple(edge.reason_cid for edge in edges),
        )

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ExplanationPath:
        if not isinstance(payload, Mapping):
            raise InvalidationError("ExplanationPath payload must be a mapping")
        return cls(
            edge_from_ids=tuple(
                str(item) for item in (payload.get("edge_from_ids") or ())
            ),
            edge_to_ids=tuple(
                str(item) for item in (payload.get("edge_to_ids") or ())
            ),
            edge_types=tuple(
                str(item) for item in (payload.get("edge_types") or ())
            ),
            reason_cids=tuple(
                str(item) for item in (payload.get("reason_cids") or ())
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofInvalidationExplanation:
    """Human- and machine-readable invalidation explanation for one unit.

    Reports changed key fields, direct reasons, transitive graph paths,
    affected aggregates, and the fallback policy decision.  Never claims
    reuse solely because a file was unchanged.
    """

    proof_unit_id: str
    disposition: UnitDispositionKind
    invalidated: bool
    seed_node_ids: tuple[str, ...]
    direct_triggers: tuple[str, ...]
    changed_key_fields: tuple[ChangedKeyField, ...]
    paths: tuple[ExplanationPath, ...]
    affected_aggregate_ids: tuple[str, ...]
    full_fallback: FullFallbackDecision
    change_classes: tuple[str, ...]
    summary: str
    schema: str = INVALIDATION_EXPLANATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proof_unit_id",
            _require_text(self.proof_unit_id, "proof_unit_id"),
        )
        object.__setattr__(
            self, "disposition", parse_unit_disposition_kind(self.disposition)
        )
        object.__setattr__(
            self, "invalidated", _require_bool(self.invalidated, "invalidated")
        )
        object.__setattr__(
            self,
            "seed_node_ids",
            _require_sorted_unique_strings(self.seed_node_ids, "seed_node_ids"),
        )
        triggers = _require_sorted_unique_strings(
            self.direct_triggers, "direct_triggers"
        )
        for trigger in triggers:
            parse_invalidation_trigger(trigger)
        object.__setattr__(self, "direct_triggers", triggers)
        if not isinstance(self.changed_key_fields, tuple):
            object.__setattr__(
                self, "changed_key_fields", tuple(self.changed_key_fields)
            )
        ordered_fields = tuple(
            sorted(self.changed_key_fields, key=lambda item: item.field_name)
        )
        if ordered_fields != self.changed_key_fields:
            raise InvalidationError(
                "changed_key_fields must be sorted by field_name"
            )
        for item in self.changed_key_fields:
            if not isinstance(item, ChangedKeyField):
                raise InvalidationError(
                    "changed_key_fields must contain ChangedKeyField records"
                )
        if not isinstance(self.paths, tuple):
            object.__setattr__(self, "paths", tuple(self.paths))
        for item in self.paths:
            if not isinstance(item, ExplanationPath):
                raise InvalidationError(
                    "paths must contain ExplanationPath records"
                )
        if len(self.paths) > MAX_EXPLANATION_PATHS:
            raise InvalidationError("paths exceeds MAX_EXPLANATION_PATHS")
        object.__setattr__(
            self,
            "affected_aggregate_ids",
            _require_sorted_unique_strings(
                self.affected_aggregate_ids, "affected_aggregate_ids"
            ),
        )
        if not isinstance(self.full_fallback, FullFallbackDecision):
            raise InvalidationError(
                "full_fallback must be a FullFallbackDecision"
            )
        classes = _require_sorted_unique_strings(
            self.change_classes, "change_classes"
        )
        for name in classes:
            parse_change_class(name)
        object.__setattr__(self, "change_classes", classes)
        object.__setattr__(
            self, "summary", _require_text(self.summary, "summary")
        )
        object.__setattr__(self, "schema", _require_text(self.schema, "schema"))
        if self.schema != INVALIDATION_EXPLANATION_SCHEMA:
            raise InvalidationError(
                f"schema must be {INVALIDATION_EXPLANATION_SCHEMA}"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "invalidation_subset": INVALIDATION_SUBSET,
            "proof_unit_id": self.proof_unit_id,
            "disposition": self.disposition.value,
            "invalidated": self.invalidated,
            "seed_node_ids": _seq_canonical(self.seed_node_ids),
            "direct_triggers": _seq_canonical(self.direct_triggers),
            "changed_key_fields": [
                item.to_canonical() for item in self.changed_key_fields
            ],
            "paths": [item.to_canonical() for item in self.paths],
            "affected_aggregate_ids": _seq_canonical(
                self.affected_aggregate_ids
            ),
            "full_fallback": self.full_fallback.to_canonical(),
            "change_classes": _seq_canonical(self.change_classes),
            "summary": self.summary,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def explanation_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(
        cls, payload: Mapping[str, Any]
    ) -> ProofInvalidationExplanation:
        if not isinstance(payload, Mapping):
            raise InvalidationError(
                "ProofInvalidationExplanation payload must be a mapping"
            )
        _reject_secret_fields(payload)

        def _seq(key: str) -> tuple[str, ...]:
            raw = payload.get(key, ABSENCE_TOKEN)
            if raw == ABSENCE_TOKEN or raw is None:
                return ()
            return tuple(str(item) for item in raw)

        fields_raw = payload.get("changed_key_fields") or ()
        paths_raw = payload.get("paths") or ()
        if not isinstance(fields_raw, Sequence) or isinstance(
            fields_raw, (str, bytes)
        ):
            raise InvalidationError("changed_key_fields must be a sequence")
        if not isinstance(paths_raw, Sequence) or isinstance(
            paths_raw, (str, bytes)
        ):
            raise InvalidationError("paths must be a sequence")
        fallback_raw = payload.get("full_fallback")
        if not isinstance(fallback_raw, Mapping):
            raise InvalidationError("full_fallback must be a mapping")
        return cls(
            proof_unit_id=str(payload.get("proof_unit_id") or ""),
            disposition=payload.get("disposition") or "",
            invalidated=bool(payload.get("invalidated", False)),
            seed_node_ids=_seq("seed_node_ids"),
            direct_triggers=_seq("direct_triggers"),
            changed_key_fields=tuple(
                ChangedKeyField.from_canonical(item)  # type: ignore[arg-type]
                for item in fields_raw
            ),
            paths=tuple(
                ExplanationPath.from_canonical(item)  # type: ignore[arg-type]
                for item in paths_raw
            ),
            affected_aggregate_ids=_seq("affected_aggregate_ids"),
            full_fallback=FullFallbackDecision.from_canonical(fallback_raw),
            change_classes=_seq("change_classes"),
            summary=str(payload.get("summary") or ""),
            schema=str(
                payload.get("schema") or INVALIDATION_EXPLANATION_SCHEMA
            ),
        )


def _changed_key_fields_for_classes(
    change_classes: Sequence[str],
) -> tuple[ChangedKeyField, ...]:
    field_to_classes: dict[str, set[str]] = {}
    for change_class in change_classes:
        parsed = parse_change_class(change_class).value
        for field_name in CHANGE_CLASS_KEY_FIELDS.get(parsed, ()):
            field_to_classes.setdefault(field_name, set()).add(parsed)
    return tuple(
        ChangedKeyField(
            field_name=field_name,
            change_classes=tuple(sorted(classes)),
        )
        for field_name, classes in sorted(field_to_classes.items())
    )


def explain_invalidation(
    graph: ProofDependencyGraph,
    proof_unit_id: str,
    closure: InvalidationClosure,
    *,
    max_paths: int = MAX_EXPLANATION_PATHS,
) -> ProofInvalidationExplanation:
    """Explain why one proof unit was invalidated, preserved, added, or removed.

    Paths are deterministic simple paths from each seed to the unit (or to an
    affected aggregate containing the unit).  The summary never authorizes
    reuse solely because a file was unchanged.
    """

    if not isinstance(graph, ProofDependencyGraph):
        raise InvalidationError("graph must be a ProofDependencyGraph")
    if not isinstance(closure, InvalidationClosure):
        raise InvalidationError("closure must be an InvalidationClosure")
    proof_unit_id = _require_text(proof_unit_id, "proof_unit_id")
    if max_paths < 1 or max_paths > MAX_EXPLANATION_PATHS:
        raise InvalidationError(
            f"max_paths must be in [1, {MAX_EXPLANATION_PATHS}]"
        )

    try:
        disposition = closure.disposition_for(proof_unit_id)
    except InvalidationError:
        # Unit outside the disposition set is treated as preserve if known
        # incomplete, otherwise fail closed when it is claimed invalidated.
        if proof_unit_id in closure.invalidated_unit_ids:
            disposition = UnitDisposition(
                unit_id=proof_unit_id,
                kind=UnitDispositionKind.INVALIDATE,
                triggers=closure.triggers,
                seed_node_ids=closure.seed_node_ids,
                reason="forward_invalidation",
            )
        elif proof_unit_id in closure.added_unit_ids:
            disposition = UnitDisposition(
                unit_id=proof_unit_id,
                kind=UnitDispositionKind.PROVE_NEW,
                triggers=(InvalidationTrigger.TEST_ADDED.value,),
                seed_node_ids=(),
                reason="added_selected_unit",
            )
        elif proof_unit_id in closure.removed_unit_ids:
            unauthorized = proof_unit_id in closure.unauthorized_removal_unit_ids
            disposition = UnitDisposition(
                unit_id=proof_unit_id,
                kind=(
                    UnitDispositionKind.REMOVE_REQUIRES_AUTHORIZATION
                    if unauthorized
                    else UnitDispositionKind.REMOVE_AUTHORIZED
                ),
                triggers=(InvalidationTrigger.TEST_DELETED.value,),
                seed_node_ids=(),
                reason=(
                    "deleted_unit_requires_authorization"
                    if unauthorized
                    else "deleted_unit_authorized"
                ),
            )
        else:
            disposition = UnitDisposition(
                unit_id=proof_unit_id,
                kind=UnitDispositionKind.PRESERVE,
                triggers=(),
                seed_node_ids=(),
                reason="outside_invalidation_closure",
            )

    invalidated = disposition.kind is UnitDispositionKind.INVALIDATE
    paths: list[ExplanationPath] = []
    if invalidated and graph.has_node(proof_unit_id):
        remaining = max_paths
        for seed in closure.seed_node_ids:
            if remaining <= 0:
                break
            if not graph.has_node(seed):
                continue
            if seed == proof_unit_id:
                continue
            try:
                found = graph.explanation_paths(
                    seed, proof_unit_id, max_paths=remaining
                )
            except DependencyGraphError as exc:
                raise InvalidationError(str(exc)) from exc
            for edge_path in found:
                paths.append(ExplanationPath.from_edges(edge_path))
                remaining -= 1
                if remaining <= 0:
                    break
        paths.sort(
            key=lambda path: (
                path.edge_from_ids,
                path.edge_to_ids,
                path.edge_types,
                path.reason_cids,
            )
        )

    changed_fields = _changed_key_fields_for_classes(closure.change_classes)
    aggregates = closure.affected_aggregate_ids
    if graph.has_node(proof_unit_id):
        # Aggregates reached from this unit specifically.
        try:
            from_unit = graph.forward_dependents(
                proof_unit_id, include_seeds=False
            )
        except DependencyGraphError as exc:
            raise InvalidationError(str(exc)) from exc
        unit_aggs = _aggregate_node_ids(graph, from_unit)
        aggregates = _sorted_unique(set(aggregates) | set(unit_aggs))

    if disposition.kind is UnitDispositionKind.PRESERVE:
        if closure.docs_only:
            summary = (
                f"unit {proof_unit_id} preserved: ordinary documentation only; "
                "execution proofs remain valid"
            )
        else:
            summary = (
                f"unit {proof_unit_id} preserved: outside forward invalidation "
                "closure; file-unchanged alone does not authorize reuse"
            )
    elif disposition.kind is UnitDispositionKind.PROVE_NEW:
        summary = (
            f"unit {proof_unit_id} is a newly selected unit and must be proven"
        )
    elif disposition.kind is UnitDispositionKind.REMOVE_REQUIRES_AUTHORIZATION:
        summary = (
            f"unit {proof_unit_id} was removed and requires current-policy "
            "authorization before the seal can drop it"
        )
    elif disposition.kind is UnitDispositionKind.REMOVE_AUTHORIZED:
        summary = (
            f"unit {proof_unit_id} was removed with current-policy authorization"
        )
    elif closure.full_fallback.required:
        summary = (
            f"unit {proof_unit_id} invalidated under full checkpoint fallback "
            f"reasons={list(closure.full_fallback.reasons)}"
        )
    else:
        summary = (
            f"unit {proof_unit_id} invalidated by forward closure from seeds "
            f"{list(closure.seed_node_ids)}; triggers={list(disposition.triggers)}; "
            f"changed_key_fields={[item.field_name for item in changed_fields]}"
        )

    return ProofInvalidationExplanation(
        proof_unit_id=proof_unit_id,
        disposition=disposition.kind,
        invalidated=invalidated,
        seed_node_ids=closure.seed_node_ids,
        direct_triggers=disposition.triggers,
        changed_key_fields=changed_fields,
        paths=tuple(paths),
        affected_aggregate_ids=aggregates,
        full_fallback=closure.full_fallback,
        change_classes=closure.change_classes,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Samples and known vectors
# ---------------------------------------------------------------------------


def sample_invalidation_policy(**overrides: Any) -> InvalidationPolicy:
    payload = {
        "treat_dependency_lock_as_full_fallback": False,
        "force_full_fallback": False,
        "is_genesis": False,
        "uncertain_cache_integrity": False,
        "release_qualification": False,
        "dependency_graph_schema_changed": False,
        "proof_schema_changed": False,
        "canonicalization_changed": False,
        "admit_key_migration_proof": False,
        "admit_schema_migration_proof": False,
        "truncated_forces_full_fallback": True,
        "unmapped_relevant_forces_full_fallback": True,
        "max_delta_chain_depth": ABSENCE_TOKEN,
        "current_delta_chain_depth": 0,
        "min_reuse_ratio_bps": ABSENCE_TOKEN,
        "estimated_reuse_ratio_bps": ABSENCE_TOKEN,
    }
    payload.update(overrides)
    return InvalidationPolicy(**payload)


def sample_path_to_node_ids() -> dict[str, tuple[str, ...]]:
    """Path mapping aligned with ``sample_dependency_graph`` node ids."""

    return {
        "mod.py": ("artifact/mod.py",),
        "pkg/mod.py": ("artifact/mod.py",),
        "fixture/data": ("fixture/data",),
        "tests/fixtures/data.json": ("fixture/data",),
        "config/env": ("config/env",),
        "config/app.toml": ("config/env",),
        "schema/api": ("schema/api",),
        "pkg/api.py": ("schema/api",),
    }


def sample_invalidation_closure(
    **overrides: Any,
) -> InvalidationClosure:
    """Hermetic sample: source artifact change invalidates the formal chain."""

    graph = sample_dependency_graph()
    known = (
        "unit/static",
        "unit/test",
        "unit/formal",
        "unit/unrelated",
        "aggregate/receipt",
        "aggregate/unrelated",
    )
    result = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
        policy=sample_invalidation_policy(),
    )
    if not overrides:
        return result
    payload = result.to_canonical()
    payload.update(overrides)
    return InvalidationClosure.from_canonical(payload)


def known_vectors() -> dict[str, Any]:
    """Deterministic vectors for the invalidation-engine evidence subset."""

    graph = sample_dependency_graph()
    known = (
        "unit/static",
        "unit/test",
        "unit/formal",
        "unit/unrelated",
        "aggregate/receipt",
        "aggregate/unrelated",
    )
    path_map = sample_path_to_node_ids()

    source = compute_invalidation_closure(
        graph,
        changed_node_ids=("artifact/mod.py",),
        known_unit_ids=known,
    )
    fixture = compute_invalidation_closure(
        graph,
        changed_node_ids=("fixture/data",),
        known_unit_ids=known,
    )
    docs = compute_invalidation_closure(
        graph,
        changed_artifacts=(
            ChangedArtifact(
                path="docs/guide.md",
                change_action=ChangeAction.MODIFIED,
                change_class=ChangeClass.ORDINARY_DOCUMENTATION,
                old_content_cid=canonical_cid({"docs": "v1"}),
                new_content_cid=canonical_cid({"docs": "v2"}),
                old_byte_length=2,
                new_byte_length=2,
            ),
        ),
        known_unit_ids=known,
        path_to_node_ids=path_map,
    )
    circuit = classify_full_fallback(
        change_classes=(ChangeClass.CIRCUIT.value,),
        policy=sample_invalidation_policy(),
    )
    explanation = explain_invalidation(graph, "unit/formal", source)

    return {
        "schema": f"{INVALIDATION_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "subset": INVALIDATION_SUBSET,
        "invalidation_schema_version": INVALIDATION_SCHEMA_VERSION,
        "closed_disposition_kinds": list(UNIT_DISPOSITION_KINDS),
        "closed_fallback_reasons": list(FULL_FALLBACK_REASONS),
        "closed_triggers": list(INVALIDATION_TRIGGERS),
        "source_closure_cid": source.closure_cid(),
        "source_invalidated": list(source.invalidated_unit_ids),
        "source_preserved": list(source.preserved_unit_ids),
        "fixture_invalidated": list(fixture.invalidated_unit_ids),
        "docs_invalidated": list(docs.invalidated_unit_ids),
        "docs_preserved": list(docs.preserved_unit_ids),
        "docs_only": docs.docs_only,
        "circuit_full_fallback": circuit.required,
        "circuit_reasons": list(circuit.reasons),
        "formal_explanation_cid": explanation.explanation_cid(),
        "formal_invalidated": explanation.invalidated,
        "formal_summary": explanation.summary,
    }


__all__ = (
    "BROAD_INVALIDATION_CHANGE_CLASSES",
    "CHANGE_CLASS_KEY_FIELDS",
    "FULL_FALLBACK_CHANGE_CLASSES",
    "FULL_FALLBACK_REASONS",
    "INVALIDATION_SCHEMA_VERSION",
    "INVALIDATION_SUBSET",
    "INVALIDATION_TRIGGERS",
    "LOCAL_INVALIDATION_CHANGE_CLASSES",
    "PRESERVE_CHANGE_CLASSES",
    "UNIT_DISPOSITION_KINDS",
    "ChangedKeyField",
    "ExplanationPath",
    "FullFallbackDecision",
    "FullFallbackReason",
    "InvalidationClosure",
    "InvalidationError",
    "InvalidationPolicy",
    "InvalidationTrigger",
    "ProofInvalidationExplanation",
    "UnitDisposition",
    "UnitDispositionKind",
    "classify_full_fallback",
    "closed_full_fallback_reasons",
    "closed_invalidation_triggers",
    "closed_unit_disposition_kinds",
    "compute_invalidation_closure",
    "explain_invalidation",
    "known_vectors",
    "parse_full_fallback_reason",
    "parse_invalidation_trigger",
    "parse_unit_disposition_kind",
    "resolve_seed_nodes",
    "sample_invalidation_closure",
    "sample_invalidation_policy",
    "sample_path_to_node_ids",
)
