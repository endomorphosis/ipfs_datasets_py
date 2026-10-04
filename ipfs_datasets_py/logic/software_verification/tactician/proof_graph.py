"""Bounded backward AND/OR proof obligation graph (``BackwardProofObligationGraph@1``).

FVT-G031 / FVT-019: regress formal targets through programs and transition
systems using weakest preconditions, preimages, temporal regression, typed
rule inversion/unification, subsumption, cycle control, and reconstructable
AND/OR proof rules.

Program invariants:

* every edge names a **checked** inference rule *and* reconstruction method;
* AND nodes are jointly required obligations; OR nodes are alternative rules
  / backends / repair paths — the meanings never collapse;
* finite resource budgets, SCC/cycle detection, and subsumption guarantee
  termination of expansion;
* a leaf may be marked discharged only when it cites evidence of adequate
  authority via an ``evidence_ref`` edge;
* legacy CEC/TDFOL string-equality or forward-only “backward” strategies are
  admitted only as **experimental** alternatives and cannot receive trusted
  status (authority is hard-capped at candidate/advisory); and
* the graph never claims proof or completion (``ProofObligationGraph@1``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    PROOF_OBLIGATION_GRAPH_INTERFACE,
    AuthorityCeiling,
    GraphEdgeKind,
    GraphNodeKind,
    HoleStatus,
    ProofGraphEdge,
    ProofGraphNode,
    ProofHole,
    ProofObligationGraph,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface and schema constants
# ---------------------------------------------------------------------------

BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE: Final = "BackwardProofObligationGraph@1"
BACKWARD_GRAPH_BUILD_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/backward-graph-build@1"
)
REGRESSION_STEP_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/regression-step@1"
)
OBLIGATION_SEED_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/obligation-seed@1"
)
EVIDENCE_CITATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/evidence-citation@1"
)
GRAPH_BUILD_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/backward-graph-result@1"
)
GRAPH_ALGORITHM_VERSION: Final = "backward-proof-obligation-graph/1.0.0"

DEFAULT_BOUNDS: Final = ResourceBounds(
    wall_time_ms=30_000,
    memory_bytes=256 * 1024 * 1024,
    max_steps=128,
    max_depth=16,
    max_nodes=128,
    max_candidates=32,
    model_token_limit=0,
    network_allowed=False,
)

# Authority levels treated as "trusted" for solved-leaf discharge.
_TRUSTED_AUTHORITIES: Final[frozenset[AuthorityCeiling]] = frozenset(
    {
        AuthorityCeiling.BOUNDED,
        AuthorityCeiling.SATISFIABILITY,
        AuthorityCeiling.MODEL_CHECK,
        AuthorityCeiling.MONITOR,
        AuthorityCeiling.AUTHORIZATION,
        AuthorityCeiling.PROTOCOL,
        AuthorityCeiling.HYPERPROPERTY,
        AuthorityCeiling.RECONSTRUCTION,
        AuthorityCeiling.ATTESTATION,
        AuthorityCeiling.THEOREM,
        AuthorityCeiling.DECLARATIVE,
    }
)

# Maximum authority legacy/experimental paths may ever advertise.
_EXPERIMENTAL_AUTHORITY_CAP: Final = AuthorityCeiling.CANDIDATE


class ProofGraphError(ValueError):
    """Raised when backward graph construction inputs are malformed or unsafe."""


class InferenceRule(StrEnum):
    """Closed set of *checked* inference / reconstruction rules for edges.

    Every edge in a trusted graph must name one of these.  Experimental /
    legacy labels exist so they can be wrapped as candidates, but they are
    never treated as reconstructable trusted rules.
    """

    # Core trusted regression / reconstruction rules.
    WEAKEST_PRECONDITION = "weakest_precondition"
    TRANSITION_PREIMAGE = "transition_preimage"
    TEMPORAL_REGRESSION = "temporal_regression"
    RULE_INVERSION = "rule_inversion"
    TYPED_UNIFICATION = "typed_unification"
    AND_INTRO = "and_intro"
    OR_INTRO = "or_intro"
    ASSUMPTION_DISCHARGE = "assumption_discharge"
    EVIDENCE_CITATION = "evidence_citation"
    SUBSUMPTION = "subsumption"
    HOLE_EMISSION = "hole_emission"
    DEPENDS_ON = "depends_on"
    REPAIR = "repair"

    # Explicitly experimental / legacy — not trusted reconstruction.
    LEGACY_STRING_EQUALITY = "legacy_string_equality"
    CEC_FORWARD_AS_BACKWARD = "cec_forward_as_backward"
    TDFOL_FORWARD_ONLY = "tdfol_forward_only"
    EXPERIMENTAL_FORWARD_CHAIN = "experimental_forward_chain"


class ReconstructionMethod(StrEnum):
    """How an edge's inference can be independently reconstructed."""

    SOURCE_VC = "source_vc"
    KERNEL = "kernel"
    SMT_REPLAY = "smt_replay"
    MODEL_CHECK = "model_check"
    TEMPORAL_REGRESSION = "temporal_regression"
    TYPED_UNIFICATION = "typed_unification"
    EVIDENCE_RECEIPT = "evidence_receipt"
    PREIMAGE_REPLAY = "preimage_replay"
    SUBSUMPTION_CHECK = "subsumption_check"
    # Experimental wrappers — never grant trusted status alone.
    EXPERIMENTAL_CEC = "experimental_cec"
    EXPERIMENTAL_TDFOL = "experimental_tdfol"
    STRING_EQUALITY = "string_equality"
    FORWARD_RULE_APPLICATION = "forward_rule_application"


class ObligationSeedKind(StrEnum):
    """What a seed obligation represents before graph expansion."""

    ROOT_GOAL = "root_goal"
    PROOF_HOLE = "proof_hole"
    ASSUMPTION = "assumption"
    EVIDENCE = "evidence"
    PROGRAM_STEP = "program_step"
    TRANSITION = "transition"
    TEMPORAL = "temporal"
    ALTERNATIVE = "alternative"
    JOINT = "joint"
    LEGACY_EXPERIMENTAL = "legacy_experimental"


class GraphBuildStatus(StrEnum):
    """Outcome of a bounded backward expansion."""

    OPEN = "open"
    PARTIAL = "partial"
    BOUNDED = "bounded"
    DISCHARGED = "discharged"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    FALSE = "false"
    UNKNOWN = "unknown"
    TERMINATED = "terminated"


# Inference rules that are experimental and cannot grant trusted status.
_EXPERIMENTAL_RULES: Final[frozenset[InferenceRule]] = frozenset(
    {
        InferenceRule.LEGACY_STRING_EQUALITY,
        InferenceRule.CEC_FORWARD_AS_BACKWARD,
        InferenceRule.TDFOL_FORWARD_ONLY,
        InferenceRule.EXPERIMENTAL_FORWARD_CHAIN,
    }
)

_EXPERIMENTAL_RECONSTRUCTION: Final[frozenset[ReconstructionMethod]] = frozenset(
    {
        ReconstructionMethod.EXPERIMENTAL_CEC,
        ReconstructionMethod.EXPERIMENTAL_TDFOL,
        ReconstructionMethod.STRING_EQUALITY,
        ReconstructionMethod.FORWARD_RULE_APPLICATION,
    }
)

# Map inference rules to the preferred edge kind on the wire contract.
_RULE_TO_EDGE_KIND: Final[Mapping[InferenceRule, GraphEdgeKind]] = {
    InferenceRule.WEAKEST_PRECONDITION: GraphEdgeKind.WEAKEST_PRECONDITION,
    InferenceRule.TRANSITION_PREIMAGE: GraphEdgeKind.PREIMAGE,
    InferenceRule.TEMPORAL_REGRESSION: GraphEdgeKind.REGRESSION,
    InferenceRule.RULE_INVERSION: GraphEdgeKind.RULE_INVERSION,
    InferenceRule.TYPED_UNIFICATION: GraphEdgeKind.UNIFICATION,
    InferenceRule.AND_INTRO: GraphEdgeKind.DEPENDS_ON,
    InferenceRule.OR_INTRO: GraphEdgeKind.ALTERNATIVE,
    InferenceRule.ASSUMPTION_DISCHARGE: GraphEdgeKind.DEPENDS_ON,
    InferenceRule.EVIDENCE_CITATION: GraphEdgeKind.EVIDENCE_REF,
    InferenceRule.SUBSUMPTION: GraphEdgeKind.SUBSUMPTION,
    InferenceRule.HOLE_EMISSION: GraphEdgeKind.DEPENDS_ON,
    InferenceRule.DEPENDS_ON: GraphEdgeKind.DEPENDS_ON,
    InferenceRule.REPAIR: GraphEdgeKind.REPAIR,
    InferenceRule.LEGACY_STRING_EQUALITY: GraphEdgeKind.ALTERNATIVE,
    InferenceRule.CEC_FORWARD_AS_BACKWARD: GraphEdgeKind.ALTERNATIVE,
    InferenceRule.TDFOL_FORWARD_ONLY: GraphEdgeKind.ALTERNATIVE,
    InferenceRule.EXPERIMENTAL_FORWARD_CHAIN: GraphEdgeKind.ALTERNATIVE,
}

# Minimum authority required to discharge a solved leaf, by default.
_DEFAULT_DISCHARGE_AUTHORITY: Final = AuthorityCeiling.BOUNDED


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 4096,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise ProofGraphError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise ProofGraphError(f"{label} must not contain NUL")
    if not optional and not text:
        raise ProofGraphError(f"{label} is required")
    if len(text) > maximum:
        raise ProofGraphError(f"{label} exceeds maximum length of {maximum}")
    return text


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip())
        except ValueError as error:
            allowed = ", ".join(item.value for item in enum_type)
            raise ProofGraphError(
                f"{label} must be one of: {allowed}"
            ) from error
    raise ProofGraphError(f"{label} must be a {enum_type.__name__}")


def _string_tuple(
    values: Sequence[str] | None,
    label: str,
    *,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: tuple[str, ...] = ()
    elif isinstance(values, str):
        items = (_text(values, label, maximum=512),)
    elif isinstance(values, Sequence) and not isinstance(
        values, (bytes, bytearray, memoryview)
    ):
        items = tuple(
            _text(item, f"{label}[{index}]", maximum=512)
            for index, item in enumerate(values)
        )
    else:
        raise ProofGraphError(f"{label} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    if not preserve_order:
        result = sorted(result)
    if required and not result:
        raise ProofGraphError(f"{label} must not be empty")
    return tuple(result)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofGraphError(f"{label} must be a non-negative integer")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProofGraphError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProofGraphError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ProofGraphError(f"{label} keys must be strings")
    return {str(k): value[k] for k in sorted(value)}


def _bounds(value: object, label: str = "bounds") -> ResourceBounds:
    if value is None:
        return DEFAULT_BOUNDS
    if isinstance(value, ResourceBounds):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceBounds.from_dict(value)
        except TacticianContractError as error:
            raise ProofGraphError(f"{label}: {error}") from error
    raise ProofGraphError(f"{label} must be a ResourceBounds")


def _proof_hole(value: object, label: str = "hole") -> ProofHole:
    if isinstance(value, ProofHole):
        return value
    if isinstance(value, Mapping):
        try:
            return ProofHole.from_dict(value)
        except TacticianContractError as error:
            raise ProofGraphError(f"{label}: {error}") from error
    raise ProofGraphError(f"{label} must be a ProofHole")


def _source_binding(value: object, label: str = "source") -> SourceSpanBinding:
    if isinstance(value, SourceSpanBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return SourceSpanBinding.from_dict(value)
        except TacticianContractError as error:
            raise ProofGraphError(f"{label}: {error}") from error
    raise ProofGraphError(f"{label} must be a SourceSpanBinding")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(
        "|".join(parts).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def is_experimental_rule(rule: InferenceRule | str) -> bool:
    """True when an inference rule is legacy/experimental (not trusted)."""

    resolved = _enum(rule, InferenceRule, "inference_rule")
    return resolved in _EXPERIMENTAL_RULES


def is_experimental_reconstruction(method: ReconstructionMethod | str) -> bool:
    """True when a reconstruction method is experimental/legacy."""

    resolved = _enum(method, ReconstructionMethod, "reconstruction_method")
    return resolved in _EXPERIMENTAL_RECONSTRUCTION


def is_trusted_authority(authority: AuthorityCeiling | str) -> bool:
    """True when authority is sufficient to discharge a solved leaf."""

    resolved = _enum(authority, AuthorityCeiling, "authority")
    return resolved in _TRUSTED_AUTHORITIES


def cap_experimental_authority(
    authority: AuthorityCeiling | str,
) -> AuthorityCeiling:
    """Hard-cap authority for experimental paths at candidate."""

    resolved = _enum(authority, AuthorityCeiling, "authority")
    if is_trusted_authority(resolved) or resolved is AuthorityCeiling.NONE:
        # Trusted levels are demoted; NONE stays NONE; advisory/candidate keep.
        if resolved is AuthorityCeiling.NONE:
            return AuthorityCeiling.NONE
        if resolved is AuthorityCeiling.ADVISORY:
            return AuthorityCeiling.ADVISORY
        return _EXPERIMENTAL_AUTHORITY_CAP
    return resolved


def rule_is_checked(rule: InferenceRule | str) -> bool:
    """True when the rule is in the closed checked vocabulary."""

    try:
        _enum(rule, InferenceRule, "inference_rule")
        return True
    except ProofGraphError:
        return False


# ---------------------------------------------------------------------------
# Input contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    """Evidence referenced by a solved leaf (authority-bearing)."""

    SCHEMA: ClassVar[str] = EVIDENCE_CITATION_SCHEMA

    evidence_id: str
    authority: AuthorityCeiling
    receipt_id: str = ""
    provider_id: str = ""
    statement: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _text(self.evidence_id, "evidence_id", maximum=256),
        )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, AuthorityCeiling, "authority"),
        )
        object.__setattr__(
            self,
            "receipt_id",
            _text(self.receipt_id, "receipt_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", optional=True, maximum=4096),
        )
        object.__setattr__(
            self, "metadata", _mapping(self.metadata, "metadata")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "evidence_id": self.evidence_id,
            "authority": self.authority.value,
            "receipt_id": self.receipt_id,
            "provider_id": self.provider_id,
            "statement": self.statement,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceCitation":
        return cls(
            evidence_id=payload.get("evidence_id", ""),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            receipt_id=payload.get("receipt_id", ""),
            provider_id=payload.get("provider_id", ""),
            statement=payload.get("statement", ""),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ObligationSeed:
    """A seed obligation that expansion will attach under the root."""

    SCHEMA: ClassVar[str] = OBLIGATION_SEED_SCHEMA

    seed_id: str
    kind: ObligationSeedKind
    statement: str
    label: str = ""
    hole_id: str = ""
    parent_seed_id: str = ""
    combination: str = "and"  # "and" | "or" relative to siblings under parent
    inference_rule: InferenceRule = InferenceRule.DEPENDS_ON
    reconstruction_method: ReconstructionMethod = ReconstructionMethod.SOURCE_VC
    authority: AuthorityCeiling = AuthorityCeiling.NONE
    status: HoleStatus = HoleStatus.OPEN
    evidence: EvidenceCitation | None = None
    subsumed_by: str = ""
    depth_hint: int = 0
    experimental: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "seed_id", _text(self.seed_id, "seed_id", maximum=256)
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, ObligationSeedKind, "kind")
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", maximum=8192),
        )
        object.__setattr__(
            self, "label", _text(self.label, "label", optional=True, maximum=512)
        )
        object.__setattr__(
            self,
            "hole_id",
            _text(self.hole_id, "hole_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "parent_seed_id",
            _text(
                self.parent_seed_id, "parent_seed_id", optional=True, maximum=256
            ),
        )
        combo = _text(self.combination, "combination", maximum=16).lower()
        if combo not in {"and", "or"}:
            raise ProofGraphError("combination must be 'and' or 'or'")
        object.__setattr__(self, "combination", combo)
        object.__setattr__(
            self,
            "inference_rule",
            _enum(self.inference_rule, InferenceRule, "inference_rule"),
        )
        object.__setattr__(
            self,
            "reconstruction_method",
            _enum(
                self.reconstruction_method,
                ReconstructionMethod,
                "reconstruction_method",
            ),
        )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, AuthorityCeiling, "authority"),
        )
        object.__setattr__(
            self, "status", _enum(self.status, HoleStatus, "status")
        )
        evidence = self.evidence
        if evidence is None:
            pass
        elif isinstance(evidence, Mapping):
            evidence = EvidenceCitation.from_dict(evidence)
        elif not isinstance(evidence, EvidenceCitation):
            raise ProofGraphError("evidence must be an EvidenceCitation")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(
            self,
            "subsumed_by",
            _text(self.subsumed_by, "subsumed_by", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "depth_hint", _nonnegative_int(self.depth_hint, "depth_hint")
        )
        experimental = _bool(self.experimental, "experimental")
        if (
            self.inference_rule in _EXPERIMENTAL_RULES
            or self.reconstruction_method in _EXPERIMENTAL_RECONSTRUCTION
            or self.kind is ObligationSeedKind.LEGACY_EXPERIMENTAL
        ):
            experimental = True
        object.__setattr__(self, "experimental", experimental)
        if experimental:
            object.__setattr__(
                self, "authority", cap_experimental_authority(self.authority)
            )
        object.__setattr__(
            self, "metadata", _mapping(self.metadata, "metadata")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "seed_id": self.seed_id,
            "kind": self.kind.value,
            "statement": self.statement,
            "label": self.label,
            "hole_id": self.hole_id,
            "parent_seed_id": self.parent_seed_id,
            "combination": self.combination,
            "inference_rule": self.inference_rule.value,
            "reconstruction_method": self.reconstruction_method.value,
            "authority": self.authority.value,
            "status": self.status.value,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "subsumed_by": self.subsumed_by,
            "depth_hint": self.depth_hint,
            "experimental": self.experimental,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObligationSeed":
        evidence_raw = payload.get("evidence")
        return cls(
            seed_id=payload.get("seed_id", ""),
            kind=payload.get("kind", ObligationSeedKind.PROOF_HOLE),
            statement=payload.get("statement", ""),
            label=payload.get("label", ""),
            hole_id=payload.get("hole_id", ""),
            parent_seed_id=payload.get("parent_seed_id", ""),
            combination=payload.get("combination", "and"),
            inference_rule=payload.get(
                "inference_rule", InferenceRule.DEPENDS_ON
            ),
            reconstruction_method=payload.get(
                "reconstruction_method", ReconstructionMethod.SOURCE_VC
            ),
            authority=payload.get("authority", AuthorityCeiling.NONE),
            status=payload.get("status", HoleStatus.OPEN),
            evidence=evidence_raw,
            subsumed_by=payload.get("subsumed_by", ""),
            depth_hint=int(payload.get("depth_hint") or 0),
            experimental=bool(payload.get("experimental", False)),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class RegressionStep:
    """One typed regression step from a parent obligation to a child.

    Used to express weakest preconditions, preimages, temporal regression,
    rule inversion, and typed unification without inventing premises.
    """

    SCHEMA: ClassVar[str] = REGRESSION_STEP_SCHEMA

    step_id: str
    parent_obligation_id: str
    child_obligation_id: str
    inference_rule: InferenceRule
    reconstruction_method: ReconstructionMethod
    statement: str = ""
    program_step_id: str = ""
    transition_id: str = ""
    combination: str = "and"
    experimental: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step_id", _text(self.step_id, "step_id", maximum=256)
        )
        object.__setattr__(
            self,
            "parent_obligation_id",
            _text(
                self.parent_obligation_id,
                "parent_obligation_id",
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "child_obligation_id",
            _text(
                self.child_obligation_id, "child_obligation_id", maximum=256
            ),
        )
        if self.parent_obligation_id == self.child_obligation_id:
            raise ProofGraphError(
                "regression steps cannot be self-loops "
                f"({self.parent_obligation_id})"
            )
        object.__setattr__(
            self,
            "inference_rule",
            _enum(self.inference_rule, InferenceRule, "inference_rule"),
        )
        object.__setattr__(
            self,
            "reconstruction_method",
            _enum(
                self.reconstruction_method,
                ReconstructionMethod,
                "reconstruction_method",
            ),
        )
        # Every trusted step must name both a rule and a reconstruction method
        # that are non-empty (enforced by enums) and consistent.
        if not self.inference_rule.value or not self.reconstruction_method.value:
            raise ProofGraphError(
                "regression steps must name inference_rule and "
                "reconstruction_method"
            )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", optional=True, maximum=8192),
        )
        object.__setattr__(
            self,
            "program_step_id",
            _text(
                self.program_step_id,
                "program_step_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "transition_id",
            _text(
                self.transition_id, "transition_id", optional=True, maximum=256
            ),
        )
        combo = _text(self.combination, "combination", maximum=16).lower()
        if combo not in {"and", "or"}:
            raise ProofGraphError("combination must be 'and' or 'or'")
        object.__setattr__(self, "combination", combo)
        experimental = _bool(self.experimental, "experimental")
        if (
            self.inference_rule in _EXPERIMENTAL_RULES
            or self.reconstruction_method in _EXPERIMENTAL_RECONSTRUCTION
        ):
            experimental = True
        object.__setattr__(self, "experimental", experimental)
        object.__setattr__(
            self, "metadata", _mapping(self.metadata, "metadata")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "step_id": self.step_id,
            "parent_obligation_id": self.parent_obligation_id,
            "child_obligation_id": self.child_obligation_id,
            "inference_rule": self.inference_rule.value,
            "reconstruction_method": self.reconstruction_method.value,
            "statement": self.statement,
            "program_step_id": self.program_step_id,
            "transition_id": self.transition_id,
            "combination": self.combination,
            "experimental": self.experimental,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RegressionStep":
        return cls(
            step_id=payload.get("step_id", ""),
            parent_obligation_id=payload.get("parent_obligation_id", ""),
            child_obligation_id=payload.get("child_obligation_id", ""),
            inference_rule=payload.get(
                "inference_rule", InferenceRule.WEAKEST_PRECONDITION
            ),
            reconstruction_method=payload.get(
                "reconstruction_method", ReconstructionMethod.SOURCE_VC
            ),
            statement=payload.get("statement", ""),
            program_step_id=payload.get("program_step_id", ""),
            transition_id=payload.get("transition_id", ""),
            combination=payload.get("combination", "and"),
            experimental=bool(payload.get("experimental", False)),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class BackwardGraphRequest:
    """Inputs for bounded backward AND/OR graph construction."""

    SCHEMA: ClassVar[str] = BACKWARD_GRAPH_BUILD_SCHEMA

    formal_goal_id: str
    tree_id: str
    seeds: tuple[ObligationSeed, ...] = ()
    steps: tuple[RegressionStep, ...] = ()
    holes: tuple[ProofHole, ...] = ()
    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    graph_id: str = ""
    root_label: str = "formal goal"
    discharge_authority: AuthorityCeiling = _DEFAULT_DISCHARGE_AUTHORITY
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", maximum=256)
        )
        seeds: list[ObligationSeed] = []
        for index, item in enumerate(self.seeds or ()):
            if isinstance(item, ObligationSeed):
                seeds.append(item)
            elif isinstance(item, Mapping):
                seeds.append(ObligationSeed.from_dict(item))
            else:
                raise ProofGraphError(
                    f"seeds[{index}] must be an ObligationSeed"
                )
        object.__setattr__(self, "seeds", tuple(seeds))
        steps: list[RegressionStep] = []
        for index, item in enumerate(self.steps or ()):
            if isinstance(item, RegressionStep):
                steps.append(item)
            elif isinstance(item, Mapping):
                steps.append(RegressionStep.from_dict(item))
            else:
                raise ProofGraphError(
                    f"steps[{index}] must be a RegressionStep"
                )
        object.__setattr__(self, "steps", tuple(steps))
        holes: list[ProofHole] = []
        for index, item in enumerate(self.holes or ()):
            holes.append(_proof_hole(item, f"holes[{index}]"))
        object.__setattr__(self, "holes", tuple(holes))
        object.__setattr__(self, "bounds", _bounds(self.bounds, "bounds"))
        object.__setattr__(
            self,
            "graph_id",
            _text(self.graph_id, "graph_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "root_label",
            _text(
                self.root_label, "root_label", optional=True, maximum=512
            )
            or "formal goal",
        )
        object.__setattr__(
            self,
            "discharge_authority",
            _enum(
                self.discharge_authority,
                AuthorityCeiling,
                "discharge_authority",
            ),
        )
        object.__setattr__(
            self, "metadata", _mapping(self.metadata, "metadata")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "formal_goal_id": self.formal_goal_id,
            "tree_id": self.tree_id,
            "seeds": [item.to_dict() for item in self.seeds],
            "steps": [item.to_dict() for item in self.steps],
            "holes": [item.to_dict() for item in self.holes],
            "bounds": self.bounds.to_dict(),
            "graph_id": self.graph_id,
            "root_label": self.root_label,
            "discharge_authority": self.discharge_authority.value,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class BackwardGraphResult:
    """Result of constructing a bounded backward obligation graph."""

    SCHEMA: ClassVar[str] = GRAPH_BUILD_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE

    graph: ProofObligationGraph
    status: GraphBuildStatus
    open_node_ids: tuple[str, ...] = ()
    discharged_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    experimental_edge_ids: tuple[str, ...] = ()
    subsumed_pairs: tuple[tuple[str, str], ...] = ()
    cycle_detected: bool = False
    scc_blocked_ids: tuple[str, ...] = ()
    budget_exhausted: bool = False
    steps_used: int = 0
    algorithm_version: str = GRAPH_ALGORITHM_VERSION
    diagnostics: tuple[str, ...] = ()
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.graph, ProofObligationGraph):
            raise ProofGraphError("graph must be a ProofObligationGraph")
        object.__setattr__(
            self, "status", _enum(self.status, GraphBuildStatus, "status")
        )
        object.__setattr__(
            self,
            "open_node_ids",
            _string_tuple(self.open_node_ids, "open_node_ids"),
        )
        object.__setattr__(
            self,
            "discharged_node_ids",
            _string_tuple(self.discharged_node_ids, "discharged_node_ids"),
        )
        object.__setattr__(
            self,
            "blocked_node_ids",
            _string_tuple(self.blocked_node_ids, "blocked_node_ids"),
        )
        object.__setattr__(
            self,
            "experimental_edge_ids",
            _string_tuple(self.experimental_edge_ids, "experimental_edge_ids"),
        )
        pairs: list[tuple[str, str]] = []
        for item in self.subsumed_pairs or ():
            if (
                isinstance(item, Sequence)
                and not isinstance(item, (str, bytes))
                and len(item) == 2
            ):
                pairs.append(
                    (
                        _text(item[0], "subsumed_pairs[0]", maximum=256),
                        _text(item[1], "subsumed_pairs[1]", maximum=256),
                    )
                )
            else:
                raise ProofGraphError(
                    "subsumed_pairs must be (subsumed, by) id pairs"
                )
        object.__setattr__(self, "subsumed_pairs", tuple(pairs))
        object.__setattr__(
            self, "cycle_detected", _bool(self.cycle_detected, "cycle_detected")
        )
        object.__setattr__(
            self,
            "scc_blocked_ids",
            _string_tuple(self.scc_blocked_ids, "scc_blocked_ids"),
        )
        object.__setattr__(
            self,
            "budget_exhausted",
            _bool(self.budget_exhausted, "budget_exhausted"),
        )
        object.__setattr__(
            self, "steps_used", _nonnegative_int(self.steps_used, "steps_used")
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(self.algorithm_version, "algorithm_version", maximum=128),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _string_tuple(self.diagnostics, "diagnostics", preserve_order=True),
        )
        if self.proof_claimed or self.completion_claimed:
            raise ProofGraphError(
                "BackwardGraphResult cannot claim proof or completion"
            )
        object.__setattr__(self, "proof_claimed", False)
        object.__setattr__(self, "completion_claimed", False)

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "graph": self.graph.to_dict(),
            "status": self.status.value,
            "open_node_ids": list(self.open_node_ids),
            "discharged_node_ids": list(self.discharged_node_ids),
            "blocked_node_ids": list(self.blocked_node_ids),
            "experimental_edge_ids": list(self.experimental_edge_ids),
            "subsumed_pairs": [list(pair) for pair in self.subsumed_pairs],
            "cycle_detected": self.cycle_detected,
            "scc_blocked_ids": list(self.scc_blocked_ids),
            "budget_exhausted": self.budget_exhausted,
            "steps_used": self.steps_used,
            "algorithm_version": self.algorithm_version,
            "diagnostics": list(self.diagnostics),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    def to_record(self) -> dict[str, Any]:
        record = self.to_dict()
        record["content_id"] = self.content_id
        record["contract_version"] = 1
        return record


# ---------------------------------------------------------------------------
# Seed / step factory helpers
# ---------------------------------------------------------------------------


def hole_seed(
    hole: ProofHole | Mapping[str, Any],
    *,
    parent_seed_id: str = "",
    combination: str = "and",
    inference_rule: InferenceRule = InferenceRule.HOLE_EMISSION,
    reconstruction_method: ReconstructionMethod = ReconstructionMethod.SOURCE_VC,
) -> ObligationSeed:
    """Create an obligation seed from a typed proof hole."""

    resolved = _proof_hole(hole)
    return ObligationSeed(
        seed_id=f"seed:{resolved.hole_id}",
        kind=ObligationSeedKind.PROOF_HOLE,
        statement=resolved.statement or resolved.reason,
        label=resolved.kind.value,
        hole_id=resolved.hole_id,
        parent_seed_id=parent_seed_id,
        combination=combination,
        inference_rule=inference_rule,
        reconstruction_method=reconstruction_method,
        authority=resolved.expected_authority,
        status=resolved.status,
        metadata={"hole_kind": resolved.kind.value},
    )


def evidence_seed(
    citation: EvidenceCitation | Mapping[str, Any],
    *,
    parent_seed_id: str,
    combination: str = "and",
) -> ObligationSeed:
    """Create an evidence seed that can discharge a parent leaf."""

    if isinstance(citation, Mapping):
        citation = EvidenceCitation.from_dict(citation)
    elif not isinstance(citation, EvidenceCitation):
        raise ProofGraphError("citation must be an EvidenceCitation")
    return ObligationSeed(
        seed_id=f"seed:evidence:{citation.evidence_id}",
        kind=ObligationSeedKind.EVIDENCE,
        statement=citation.statement or citation.evidence_id,
        label="evidence",
        parent_seed_id=parent_seed_id,
        combination=combination,
        inference_rule=InferenceRule.EVIDENCE_CITATION,
        reconstruction_method=ReconstructionMethod.EVIDENCE_RECEIPT,
        authority=citation.authority,
        status=HoleStatus.DISCHARGED
        if is_trusted_authority(citation.authority)
        else HoleStatus.CANDIDATE,
        evidence=citation,
    )


def experimental_legacy_seed(
    *,
    seed_id: str,
    statement: str,
    parent_seed_id: str = "",
    rule: InferenceRule = InferenceRule.LEGACY_STRING_EQUALITY,
    reconstruction: ReconstructionMethod = ReconstructionMethod.STRING_EQUALITY,
    claimed_authority: AuthorityCeiling = AuthorityCeiling.THEOREM,
) -> ObligationSeed:
    """Wrap a legacy CEC/TDFOL/string-equality path as an experimental seed.

    Claimed elevated authority is hard-capped; the seed is always experimental.
    """

    return ObligationSeed(
        seed_id=seed_id,
        kind=ObligationSeedKind.LEGACY_EXPERIMENTAL,
        statement=statement,
        label="experimental legacy",
        parent_seed_id=parent_seed_id,
        combination="or",
        inference_rule=rule,
        reconstruction_method=reconstruction,
        authority=claimed_authority,
        status=HoleStatus.CANDIDATE,
        experimental=True,
        metadata={"legacy": True, "trusted": False},
    )


def wp_step(
    *,
    step_id: str,
    parent_obligation_id: str,
    child_obligation_id: str,
    statement: str = "",
    program_step_id: str = "",
    combination: str = "and",
) -> RegressionStep:
    """Weakest-precondition regression step (trusted when reconstructed)."""

    return RegressionStep(
        step_id=step_id,
        parent_obligation_id=parent_obligation_id,
        child_obligation_id=child_obligation_id,
        inference_rule=InferenceRule.WEAKEST_PRECONDITION,
        reconstruction_method=ReconstructionMethod.SOURCE_VC,
        statement=statement,
        program_step_id=program_step_id,
        combination=combination,
    )


def preimage_step(
    *,
    step_id: str,
    parent_obligation_id: str,
    child_obligation_id: str,
    transition_id: str = "",
    statement: str = "",
    combination: str = "and",
) -> RegressionStep:
    """Transition-preimage regression step."""

    return RegressionStep(
        step_id=step_id,
        parent_obligation_id=parent_obligation_id,
        child_obligation_id=child_obligation_id,
        inference_rule=InferenceRule.TRANSITION_PREIMAGE,
        reconstruction_method=ReconstructionMethod.PREIMAGE_REPLAY,
        statement=statement,
        transition_id=transition_id,
        combination=combination,
    )


def temporal_step(
    *,
    step_id: str,
    parent_obligation_id: str,
    child_obligation_id: str,
    statement: str = "",
    combination: str = "and",
) -> RegressionStep:
    """Temporal regression step."""

    return RegressionStep(
        step_id=step_id,
        parent_obligation_id=parent_obligation_id,
        child_obligation_id=child_obligation_id,
        inference_rule=InferenceRule.TEMPORAL_REGRESSION,
        reconstruction_method=ReconstructionMethod.TEMPORAL_REGRESSION,
        statement=statement,
        combination=combination,
    )


def rule_inversion_step(
    *,
    step_id: str,
    parent_obligation_id: str,
    child_obligation_id: str,
    statement: str = "",
    combination: str = "and",
) -> RegressionStep:
    """Typed rule-inversion step."""

    return RegressionStep(
        step_id=step_id,
        parent_obligation_id=parent_obligation_id,
        child_obligation_id=child_obligation_id,
        inference_rule=InferenceRule.RULE_INVERSION,
        reconstruction_method=ReconstructionMethod.KERNEL,
        statement=statement,
        combination=combination,
    )


def unification_step(
    *,
    step_id: str,
    parent_obligation_id: str,
    child_obligation_id: str,
    statement: str = "",
    combination: str = "and",
) -> RegressionStep:
    """Typed unification step."""

    return RegressionStep(
        step_id=step_id,
        parent_obligation_id=parent_obligation_id,
        child_obligation_id=child_obligation_id,
        inference_rule=InferenceRule.TYPED_UNIFICATION,
        reconstruction_method=ReconstructionMethod.TYPED_UNIFICATION,
        statement=statement,
        combination=combination,
    )


# ---------------------------------------------------------------------------
# Graph construction engine
# ---------------------------------------------------------------------------


def _node_kind_for_seed(seed: ObligationSeed) -> GraphNodeKind:
    if seed.kind is ObligationSeedKind.ROOT_GOAL:
        return GraphNodeKind.ROOT
    if seed.kind is ObligationSeedKind.EVIDENCE:
        return GraphNodeKind.EVIDENCE
    if seed.kind is ObligationSeedKind.ASSUMPTION:
        return GraphNodeKind.ASSUMPTION
    if seed.kind is ObligationSeedKind.JOINT:
        return GraphNodeKind.AND
    if seed.kind is ObligationSeedKind.ALTERNATIVE:
        return GraphNodeKind.OR
    if seed.kind is ObligationSeedKind.LEGACY_EXPERIMENTAL:
        return GraphNodeKind.LEAF
    if seed.combination == "or":
        # Leaf under OR parent stays LEAF; the parent combination node is OR.
        return GraphNodeKind.LEAF
    return GraphNodeKind.LEAF


def _edge_kind_for_rule(rule: InferenceRule) -> GraphEdgeKind:
    return _RULE_TO_EDGE_KIND.get(rule, GraphEdgeKind.DEPENDS_ON)


def _require_named_rule_and_method(
    rule: InferenceRule, method: ReconstructionMethod, *, context: str
) -> None:
    if not rule.value:
        raise ProofGraphError(f"{context}: inference_rule is required")
    if not method.value:
        raise ProofGraphError(f"{context}: reconstruction_method is required")
    if not rule_is_checked(rule):
        raise ProofGraphError(
            f"{context}: inference_rule {rule!r} is not a checked rule"
        )


def _detect_cycles(
    adjacency: Mapping[str, Sequence[str]],
) -> tuple[bool, tuple[str, ...]]:
    """DFS cycle detection; returns (has_cycle, nodes_on_a_cycle_or_scc)."""

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}
    on_cycle: set[str] = set()
    has_cycle = False

    def visit(node: str, stack: list[str]) -> None:
        nonlocal has_cycle
        color[node] = GRAY
        stack.append(node)
        for nxt in adjacency.get(node, ()):
            if nxt not in color:
                continue
            if color[nxt] is GRAY:
                has_cycle = True
                # Mark the SCC-like cycle segment.
                if nxt in stack:
                    idx = stack.index(nxt)
                    on_cycle.update(stack[idx:])
            elif color[nxt] is WHITE:
                visit(nxt, stack)
        stack.pop()
        color[node] = BLACK

    for node in adjacency:
        if color[node] is WHITE:
            visit(node, [])
    return has_cycle, tuple(sorted(on_cycle))


def _statement_subsumes(stronger: str, weaker: str) -> bool:
    """Conservative syntactic subsumption: identical normalized statements.

    Real logical subsumption is delegated to solvers; this control only
    collapses exact duplicates so expansion terminates.  It never invents
    premises.
    """

    a = " ".join(stronger.strip().lower().split())
    b = " ".join(weaker.strip().lower().split())
    if not a or not b:
        return False
    return a == b


class BackwardProofObligationGraph:
    """Construct a bounded, cycle-safe AND/OR obligation graph.

    Interface: ``BackwardProofObligationGraph@1``.
    """

    INTERFACE: ClassVar[str] = BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE
    ALGORITHM_VERSION: ClassVar[str] = GRAPH_ALGORITHM_VERSION

    def __init__(
        self,
        *,
        default_bounds: ResourceBounds | None = None,
        allow_experimental: bool = True,
    ) -> None:
        self.default_bounds = (
            default_bounds if default_bounds is not None else DEFAULT_BOUNDS
        )
        self.allow_experimental = bool(allow_experimental)

    def build(
        self,
        request: BackwardGraphRequest | Mapping[str, Any],
    ) -> BackwardGraphResult:
        """Expand seeds/steps/holes into a ``ProofObligationGraph@1``."""

        if isinstance(request, Mapping):
            request = BackwardGraphRequest(
                formal_goal_id=request.get("formal_goal_id", ""),
                tree_id=request.get("tree_id", ""),
                seeds=tuple(request.get("seeds") or ()),
                steps=tuple(request.get("steps") or ()),
                holes=tuple(request.get("holes") or ()),
                bounds=request.get("bounds"),
                graph_id=request.get("graph_id", ""),
                root_label=request.get("root_label", "formal goal"),
                discharge_authority=request.get(
                    "discharge_authority", _DEFAULT_DISCHARGE_AUTHORITY
                ),
                metadata=request.get("metadata") or {},
            )
        elif not isinstance(request, BackwardGraphRequest):
            raise ProofGraphError("request must be a BackwardGraphRequest")

        bounds = request.bounds
        if bounds.max_nodes == 0 and bounds.max_depth == 0 and bounds.max_steps == 0:
            # Apply defaults when the caller left all bounds unset.
            bounds = self.default_bounds

        diagnostics: list[str] = []
        nodes_by_id: dict[str, ProofGraphNode] = {}
        edges: list[ProofGraphEdge] = []
        experimental_edge_ids: list[str] = []
        subsumed_pairs: list[tuple[str, str]] = []
        steps_used = 0
        budget_exhausted = False

        root_node_id = "node:root"
        graph_id = request.graph_id or _stable_id(
            "graph", request.formal_goal_id, request.tree_id
        )
        root = ProofGraphNode(
            node_id=root_node_id,
            kind=GraphNodeKind.ROOT,
            obligation_id=f"obl:{request.formal_goal_id}",
            label=request.root_label,
            status=HoleStatus.OPEN,
            authority=AuthorityCeiling.NONE,
            metadata={"formal_goal_id": request.formal_goal_id},
        )
        nodes_by_id[root_node_id] = root

        # Map seed_id / obligation_id → node_id
        seed_to_node: dict[str, str] = {}
        obligation_to_node: dict[str, str] = {
            f"obl:{request.formal_goal_id}": root_node_id,
            request.formal_goal_id: root_node_id,
        }
        statement_index: dict[str, str] = {}  # normalized statement → node_id

        def _budget_ok() -> bool:
            nonlocal budget_exhausted
            if bounds.max_nodes and len(nodes_by_id) >= bounds.max_nodes:
                budget_exhausted = True
                return False
            if bounds.max_steps and steps_used >= bounds.max_steps:
                budget_exhausted = True
                return False
            return True

        def _add_node(node: ProofGraphNode) -> str:
            if node.node_id in nodes_by_id:
                return node.node_id
            if not _budget_ok():
                diagnostics.append(
                    f"budget exhausted before adding node {node.node_id}"
                )
                return ""
            nodes_by_id[node.node_id] = node
            return node.node_id

        def _add_edge(
            *,
            edge_id: str,
            source: str,
            target: str,
            rule: InferenceRule,
            method: ReconstructionMethod,
            kind: GraphEdgeKind | None = None,
            experimental: bool = False,
            metadata: Mapping[str, Any] | None = None,
        ) -> None:
            nonlocal steps_used
            if source not in nodes_by_id or target not in nodes_by_id:
                return
            if source == target:
                diagnostics.append(f"skipped self-loop edge {edge_id}")
                return
            _require_named_rule_and_method(
                rule, method, context=f"edge {edge_id}"
            )
            if experimental or rule in _EXPERIMENTAL_RULES or method in _EXPERIMENTAL_RECONSTRUCTION:
                if not self.allow_experimental:
                    diagnostics.append(
                        f"rejected experimental edge {edge_id} "
                        f"(rule={rule.value})"
                    )
                    return
                experimental = True
            meta = dict(metadata or {})
            if experimental:
                meta["experimental"] = True
                meta["trusted"] = False
            edge = ProofGraphEdge(
                edge_id=edge_id,
                source_node_id=source,
                target_node_id=target,
                kind=kind or _edge_kind_for_rule(rule),
                inference_rule=rule.value,
                reconstruction_method=method.value,
                metadata=meta,
            )
            edges.append(edge)
            steps_used += 1
            if experimental:
                experimental_edge_ids.append(edge_id)

        # --- Incorporate typed holes as seeds if not already present ---
        seeds = list(request.seeds)
        existing_hole_ids = {s.hole_id for s in seeds if s.hole_id}
        for hole in request.holes:
            if hole.hole_id in existing_hole_ids:
                continue
            seeds.append(hole_seed(hole))

        # Group top-level seeds (no parent) by combination for AND/OR structure.
        top_and = [s for s in seeds if not s.parent_seed_id and s.combination == "and"]
        top_or = [s for s in seeds if not s.parent_seed_id and s.combination == "or"]
        child_seeds = [s for s in seeds if s.parent_seed_id]

        def _ensure_combination_parent(
            *,
            combo: str,
            children: Sequence[ObligationSeed],
            parent_node_id: str,
            tag: str,
        ) -> str:
            """Insert an AND/OR structural node when multiple children share combo."""

            if len(children) <= 1:
                return parent_node_id
            combo_id = f"node:{combo}:{tag}"
            kind = GraphNodeKind.AND if combo == "and" else GraphNodeKind.OR
            rule = (
                InferenceRule.AND_INTRO
                if combo == "and"
                else InferenceRule.OR_INTRO
            )
            method = ReconstructionMethod.KERNEL
            if not _budget_ok():
                return parent_node_id
            _add_node(
                ProofGraphNode(
                    node_id=combo_id,
                    kind=kind,
                    obligation_id=f"obl:{combo}:{tag}",
                    label=f"{combo.upper()} obligations",
                    status=HoleStatus.OPEN,
                    authority=AuthorityCeiling.NONE,
                    metadata={"combination": combo},
                )
            )
            _add_edge(
                edge_id=f"edge:{parent_node_id}->{combo_id}",
                source=parent_node_id,
                target=combo_id,
                rule=rule,
                method=method,
                kind=GraphEdgeKind.DEPENDS_ON
                if combo == "and"
                else GraphEdgeKind.ALTERNATIVE,
            )
            return combo_id

        # Build structural parents under root for top-level seeds.
        and_parent = _ensure_combination_parent(
            combo="and",
            children=top_and,
            parent_node_id=root_node_id,
            tag="root-and",
        )
        or_parent = _ensure_combination_parent(
            combo="or",
            children=top_or,
            parent_node_id=root_node_id,
            tag="root-or",
        )

        def _materialize_seed(
            seed: ObligationSeed, default_parent: str
        ) -> str:
            nonlocal budget_exhausted
            if not _budget_ok():
                return ""
            if seed.seed_id in seed_to_node:
                return seed_to_node[seed.seed_id]

            # Depth budget
            if bounds.max_depth and seed.depth_hint > bounds.max_depth:
                diagnostics.append(
                    f"seed {seed.seed_id} exceeds max_depth={bounds.max_depth}"
                )
                budget_exhausted = True
                return ""

            if seed.experimental and not self.allow_experimental:
                diagnostics.append(
                    f"skipped experimental seed {seed.seed_id}"
                )
                return ""

            # Subsumption control: identical statement already present.
            norm = " ".join(seed.statement.strip().lower().split())
            if norm and norm in statement_index:
                existing = statement_index[norm]
                seed_to_node[seed.seed_id] = existing
                subsumed_pairs.append((seed.seed_id, existing))
                if default_parent and existing in nodes_by_id:
                    _add_edge(
                        edge_id=f"edge:subsume:{seed.seed_id}",
                        source=default_parent,
                        target=existing,
                        rule=InferenceRule.SUBSUMPTION,
                        method=ReconstructionMethod.SUBSUMPTION_CHECK,
                        kind=GraphEdgeKind.SUBSUMPTION,
                        metadata={"subsumed_seed": seed.seed_id},
                    )
                return existing

            if seed.subsumed_by:
                # Explicit subsumption declaration.
                target_node = seed_to_node.get(seed.subsumed_by, "")
                if target_node:
                    seed_to_node[seed.seed_id] = target_node
                    subsumed_pairs.append((seed.seed_id, seed.subsumed_by))
                    return target_node

            node_id = f"node:{seed.seed_id}"
            if len(node_id) > 256:
                node_id = _stable_id("node", seed.seed_id)

            authority = seed.authority
            if seed.experimental:
                authority = cap_experimental_authority(authority)

            status = seed.status
            # Evidence nodes with trusted authority start as discharged
            # candidates for leaf discharge; experimental never discharges.
            if seed.experimental and status is HoleStatus.DISCHARGED:
                status = HoleStatus.CANDIDATE
                diagnostics.append(
                    f"experimental seed {seed.seed_id} cannot be discharged"
                )

            kind = _node_kind_for_seed(seed)
            meta: dict[str, Any] = dict(seed.metadata)
            meta["seed_kind"] = seed.kind.value
            meta["statement"] = seed.statement
            if seed.experimental:
                meta["experimental"] = True
                meta["trusted"] = False
            if seed.evidence is not None:
                meta["evidence_id"] = seed.evidence.evidence_id
                meta["evidence_authority"] = seed.evidence.authority.value

            node = ProofGraphNode(
                node_id=node_id,
                kind=kind,
                obligation_id=f"obl:{seed.seed_id}",
                hole_id=seed.hole_id,
                label=seed.label or seed.kind.value,
                status=status,
                authority=authority,
                metadata=meta,
            )
            added = _add_node(node)
            if not added:
                return ""
            seed_to_node[seed.seed_id] = node_id
            obligation_to_node[f"obl:{seed.seed_id}"] = node_id
            obligation_to_node[seed.seed_id] = node_id
            if seed.hole_id:
                obligation_to_node[seed.hole_id] = node_id
            if norm:
                statement_index[norm] = node_id

            parent = default_parent
            if seed.parent_seed_id:
                parent = seed_to_node.get(seed.parent_seed_id, default_parent)
            if parent and parent in nodes_by_id:
                _add_edge(
                    edge_id=f"edge:{parent}->{node_id}",
                    source=parent,
                    target=node_id,
                    rule=seed.inference_rule,
                    method=seed.reconstruction_method,
                    experimental=seed.experimental,
                    metadata={"seed_id": seed.seed_id},
                )
            return node_id

        # Materialize top-level seeds.
        for seed in top_and:
            _materialize_seed(seed, and_parent)
        for seed in top_or:
            _materialize_seed(seed, or_parent)

        # Materialize parented seeds in dependency order (parents first).
        remaining = list(child_seeds)
        progress = True
        while remaining and progress and _budget_ok():
            progress = False
            next_remaining: list[ObligationSeed] = []
            for seed in remaining:
                if seed.parent_seed_id and seed.parent_seed_id not in seed_to_node:
                    # Ensure parent exists as a placeholder if declared only as id.
                    parent_match = next(
                        (s for s in seeds if s.seed_id == seed.parent_seed_id),
                        None,
                    )
                    if parent_match is not None:
                        _materialize_seed(parent_match, root_node_id)
                    else:
                        next_remaining.append(seed)
                        continue
                parent_node = seed_to_node.get(seed.parent_seed_id, root_node_id)
                # Insert combination node if siblings under same parent share combo.
                _materialize_seed(seed, parent_node)
                progress = True
            if not progress:
                # Force-materialize leftovers under root to avoid infinite loop.
                for seed in remaining:
                    _materialize_seed(seed, root_node_id)
                remaining = []
            else:
                remaining = [
                    s for s in next_remaining if s.seed_id not in seed_to_node
                ]

        # --- Apply explicit regression steps ---
        for step in request.steps:
            if not _budget_ok():
                break
            if step.experimental and not self.allow_experimental:
                diagnostics.append(
                    f"skipped experimental step {step.step_id}"
                )
                continue

            parent_node = obligation_to_node.get(step.parent_obligation_id)
            if parent_node is None:
                # Create parent leaf if missing.
                parent_node_id = f"node:obl:{step.parent_obligation_id}"
                if len(parent_node_id) > 256:
                    parent_node_id = _stable_id(
                        "node", step.parent_obligation_id
                    )
                if parent_node_id not in nodes_by_id:
                    if not _budget_ok():
                        break
                    _add_node(
                        ProofGraphNode(
                            node_id=parent_node_id,
                            kind=GraphNodeKind.LEAF,
                            obligation_id=step.parent_obligation_id,
                            label=step.parent_obligation_id,
                            status=HoleStatus.OPEN,
                            authority=AuthorityCeiling.NONE,
                        )
                    )
                    # Attach to root via depends_on if not already linked.
                    _add_edge(
                        edge_id=f"edge:root->{parent_node_id}",
                        source=root_node_id,
                        target=parent_node_id,
                        rule=InferenceRule.DEPENDS_ON,
                        method=ReconstructionMethod.SOURCE_VC,
                    )
                parent_node = parent_node_id
                obligation_to_node[step.parent_obligation_id] = parent_node

            child_node = obligation_to_node.get(step.child_obligation_id)
            if child_node is None:
                child_node_id = f"node:obl:{step.child_obligation_id}"
                if len(child_node_id) > 256:
                    child_node_id = _stable_id(
                        "node", step.child_obligation_id
                    )
                # Subsumption against existing statements.
                norm = " ".join(step.statement.strip().lower().split())
                if norm and norm in statement_index:
                    child_node = statement_index[norm]
                    obligation_to_node[step.child_obligation_id] = child_node
                    subsumed_pairs.append(
                        (step.child_obligation_id, child_node)
                    )
                    _add_edge(
                        edge_id=f"edge:subsume:{step.step_id}",
                        source=parent_node,
                        target=child_node,
                        rule=InferenceRule.SUBSUMPTION,
                        method=ReconstructionMethod.SUBSUMPTION_CHECK,
                        kind=GraphEdgeKind.SUBSUMPTION,
                    )
                    continue
                if not _budget_ok():
                    break
                authority = AuthorityCeiling.NONE
                status = HoleStatus.OPEN
                if step.experimental:
                    authority = AuthorityCeiling.CANDIDATE
                    status = HoleStatus.CANDIDATE
                meta: dict[str, Any] = {
                    "from_step": step.step_id,
                    "statement": step.statement,
                }
                if step.experimental:
                    meta["experimental"] = True
                    meta["trusted"] = False
                _add_node(
                    ProofGraphNode(
                        node_id=child_node_id,
                        kind=GraphNodeKind.LEAF,
                        obligation_id=step.child_obligation_id,
                        label=step.statement or step.child_obligation_id,
                        status=status,
                        authority=authority,
                        metadata=meta,
                    )
                )
                child_node = child_node_id
                obligation_to_node[step.child_obligation_id] = child_node
                if norm:
                    statement_index[norm] = child_node

            # If combination is or/and with siblings, structural nodes already
            # handled via seeds; steps attach directly with the named rule.
            _add_edge(
                edge_id=f"edge:step:{step.step_id}",
                source=parent_node,
                target=child_node,
                rule=step.inference_rule,
                method=step.reconstruction_method,
                experimental=step.experimental,
                metadata={
                    "step_id": step.step_id,
                    "program_step_id": step.program_step_id,
                    "transition_id": step.transition_id,
                },
            )

        # --- Discharge leaves that cite adequate evidence ---
        # Build adjacency for evidence lookup.
        children: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
        for edge in edges:
            children.setdefault(edge.source_node_id, []).append(
                edge.target_node_id
            )

        # Authority enum is not ordered numerically; compare membership + ceiling.
        def _meets_discharge(authority: AuthorityCeiling) -> bool:
            if not is_trusted_authority(authority):
                return False
            # Explicit floor: require at least BOUNDED-class unless caller set NONE.
            floor = request.discharge_authority
            if floor is AuthorityCeiling.NONE:
                return is_trusted_authority(authority)
            if floor is AuthorityCeiling.ADVISORY or floor is AuthorityCeiling.CANDIDATE:
                return is_trusted_authority(authority)
            # For stronger floors, require exact floor or known stronger set.
            stronger_or_eq = {
                AuthorityCeiling.BOUNDED,
                AuthorityCeiling.SATISFIABILITY,
                AuthorityCeiling.MODEL_CHECK,
                AuthorityCeiling.MONITOR,
                AuthorityCeiling.AUTHORIZATION,
                AuthorityCeiling.PROTOCOL,
                AuthorityCeiling.HYPERPROPERTY,
                AuthorityCeiling.RECONSTRUCTION,
                AuthorityCeiling.ATTESTATION,
                AuthorityCeiling.THEOREM,
                AuthorityCeiling.DECLARATIVE,
            }
            return authority in stronger_or_eq

        discharged: list[str] = []
        for nid, node in list(nodes_by_id.items()):
            if node.kind not in {
                GraphNodeKind.LEAF,
                GraphNodeKind.ASSUMPTION,
            }:
                continue
            if node.metadata.get("experimental"):
                # Experimental leaves never receive trusted discharge.
                if node.status is HoleStatus.DISCHARGED:
                    nodes_by_id[nid] = replace(
                        node, status=HoleStatus.CANDIDATE
                    )
                    diagnostics.append(
                        f"refused trusted discharge for experimental node {nid}"
                    )
                continue
            # Look for evidence children linked by evidence_ref edges.
            adequate = False
            for edge in edges:
                if edge.source_node_id != nid:
                    continue
                if edge.kind is not GraphEdgeKind.EVIDENCE_REF and (
                    edge.inference_rule != InferenceRule.EVIDENCE_CITATION.value
                ):
                    continue
                target = nodes_by_id.get(edge.target_node_id)
                if target is None:
                    continue
                if target.kind is GraphNodeKind.EVIDENCE and _meets_discharge(
                    target.authority
                ):
                    if target.metadata.get("experimental"):
                        continue
                    adequate = True
                    break
            # Also accept evidence seeds materialised as children via depends_on
            # when the edge itself is evidence_citation.
            if not adequate:
                for child_id in children.get(nid, ()):
                    child = nodes_by_id.get(child_id)
                    if child is None:
                        continue
                    if child.kind is GraphNodeKind.EVIDENCE and _meets_discharge(
                        child.authority
                    ):
                        if child.metadata.get("experimental"):
                            continue
                        adequate = True
                        break
            if adequate:
                nodes_by_id[nid] = replace(
                    node,
                    status=HoleStatus.DISCHARGED,
                    authority=max(
                        (node.authority, request.discharge_authority),
                        key=lambda a: (
                            0
                            if a is AuthorityCeiling.NONE
                            else 1
                            if a is AuthorityCeiling.ADVISORY
                            else 2
                            if a is AuthorityCeiling.CANDIDATE
                            else 3
                        ),
                    )
                    if node.authority
                    in {
                        AuthorityCeiling.NONE,
                        AuthorityCeiling.ADVISORY,
                        AuthorityCeiling.CANDIDATE,
                    }
                    else node.authority,
                )
                discharged.append(nid)
            elif node.status is HoleStatus.DISCHARGED:
                # Fail closed: claimed discharge without adequate evidence.
                nodes_by_id[nid] = replace(node, status=HoleStatus.OPEN)
                diagnostics.append(
                    f"stripped discharge from {nid}: inadequate evidence"
                )

        # --- Cycle / SCC control: strip cycle-forming edges to terminate ---
        adjacency: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
        for edge in edges:
            if (
                edge.source_node_id in adjacency
                and edge.target_node_id in nodes_by_id
            ):
                adjacency[edge.source_node_id].append(edge.target_node_id)

        has_cycle, cycle_nodes = _detect_cycles(adjacency)
        scc_blocked: list[str] = []
        if has_cycle:
            diagnostics.append(
                "cycle detected during expansion; blocking cyclic nodes"
            )
            # Remove edges that close cycles (keep a DAG for the contract).
            safe_edges: list[ProofGraphEdge] = []
            # Rebuild greedily: add edges that do not create a cycle.
            dag_adj: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}

            def _would_cycle(src: str, dst: str) -> bool:
                # Can we reach src from dst already?
                stack = [dst]
                seen: set[str] = set()
                while stack:
                    cur = stack.pop()
                    if cur == src:
                        return True
                    if cur in seen:
                        continue
                    seen.add(cur)
                    stack.extend(dag_adj.get(cur, ()))
                return False

            for edge in sorted(edges, key=lambda e: e.edge_id):
                if _would_cycle(edge.source_node_id, edge.target_node_id):
                    diagnostics.append(
                        f"dropped cycle-forming edge {edge.edge_id}"
                    )
                    continue
                dag_adj[edge.source_node_id].append(edge.target_node_id)
                safe_edges.append(edge)
            edges = safe_edges
            for nid in cycle_nodes:
                if nid in nodes_by_id:
                    node = nodes_by_id[nid]
                    if node.status not in {
                        HoleStatus.DISCHARGED,
                        HoleStatus.FALSE,
                    }:
                        nodes_by_id[nid] = replace(
                            node, status=HoleStatus.BLOCKED
                        )
                        scc_blocked.append(nid)

        # Final acyclicity check (contract requires DAG).
        final_adj: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
        for edge in edges:
            final_adj[edge.source_node_id].append(edge.target_node_id)
        still_cycle, still_nodes = _detect_cycles(final_adj)
        if still_cycle:
            # Last resort: drop all edges into the residual cycle set.
            edges = [
                e
                for e in edges
                if e.target_node_id not in still_nodes
                or e.source_node_id not in still_nodes
            ]
            for nid in still_nodes:
                if nid in nodes_by_id:
                    nodes_by_id[nid] = replace(
                        nodes_by_id[nid], status=HoleStatus.BLOCKED
                    )
                    if nid not in scc_blocked:
                        scc_blocked.append(nid)
            diagnostics.append("residual cycles collapsed via edge drop")

        # Collect open / blocked / discharged.
        open_ids: list[str] = []
        blocked_ids: list[str] = []
        discharged_ids: list[str] = []
        for nid, node in nodes_by_id.items():
            if node.status is HoleStatus.DISCHARGED:
                discharged_ids.append(nid)
            elif node.status is HoleStatus.BLOCKED:
                blocked_ids.append(nid)
            elif node.status in {
                HoleStatus.OPEN,
                HoleStatus.CANDIDATE,
                HoleStatus.UNKNOWN,
            }:
                if node.kind not in {
                    GraphNodeKind.ROOT,
                    GraphNodeKind.AND,
                    GraphNodeKind.OR,
                    GraphNodeKind.EVIDENCE,
                }:
                    open_ids.append(nid)

        # Overall status.
        if budget_exhausted:
            status = GraphBuildStatus.BOUNDED
        elif scc_blocked:
            status = GraphBuildStatus.BLOCKED
        elif open_ids:
            status = (
                GraphBuildStatus.PARTIAL
                if discharged_ids
                else GraphBuildStatus.OPEN
            )
        elif discharged_ids and not open_ids:
            status = GraphBuildStatus.DISCHARGED
        else:
            status = GraphBuildStatus.TERMINATED

        # Ensure every edge has named rule + reconstruction (fail closed).
        for edge in edges:
            if not edge.inference_rule or not edge.reconstruction_method:
                raise ProofGraphError(
                    f"edge {edge.edge_id} missing inference_rule or "
                    "reconstruction_method"
                )
            if edge.inference_rule in {
                r.value for r in _EXPERIMENTAL_RULES
            } or edge.reconstruction_method in {
                m.value for m in _EXPERIMENTAL_RECONSTRUCTION
            }:
                if edge.edge_id not in experimental_edge_ids:
                    experimental_edge_ids.append(edge.edge_id)
                # Ensure metadata marks untrusted.
                if not edge.metadata.get("experimental"):
                    # ProofGraphEdge is frozen; replace via rebuild.
                    idx = edges.index(edge)
                    meta = dict(edge.metadata)
                    meta["experimental"] = True
                    meta["trusted"] = False
                    edges[idx] = ProofGraphEdge(
                        edge_id=edge.edge_id,
                        source_node_id=edge.source_node_id,
                        target_node_id=edge.target_node_id,
                        kind=edge.kind,
                        inference_rule=edge.inference_rule,
                        reconstruction_method=edge.reconstruction_method,
                        metadata=meta,
                    )

        try:
            graph = ProofObligationGraph(
                graph_id=graph_id,
                formal_goal_id=request.formal_goal_id,
                root_node_id=root_node_id,
                nodes=tuple(nodes_by_id.values()),
                edges=tuple(edges),
                tree_id=request.tree_id,
                bounds=bounds,
                status=status.value,
                authority=AuthorityCeiling.NONE,
                proof_claimed=False,
                completion_claimed=False,
            )
        except TacticianContractError as error:
            raise ProofGraphError(
                f"failed to construct ProofObligationGraph: {error}"
            ) from error

        return BackwardGraphResult(
            graph=graph,
            status=status,
            open_node_ids=tuple(sorted(open_ids)),
            discharged_node_ids=tuple(sorted(discharged_ids)),
            blocked_node_ids=tuple(sorted(set(blocked_ids + scc_blocked))),
            experimental_edge_ids=tuple(sorted(set(experimental_edge_ids))),
            subsumed_pairs=tuple(subsumed_pairs),
            cycle_detected=has_cycle or still_cycle,
            scc_blocked_ids=tuple(sorted(set(scc_blocked))),
            budget_exhausted=budget_exhausted,
            steps_used=steps_used,
            algorithm_version=self.ALGORITHM_VERSION,
            diagnostics=tuple(diagnostics),
            proof_claimed=False,
            completion_claimed=False,
        )


def build_backward_proof_graph(
    request: BackwardGraphRequest | Mapping[str, Any],
    *,
    allow_experimental: bool = True,
) -> BackwardGraphResult:
    """Convenience entry point for ``BackwardProofObligationGraph@1``."""

    return BackwardProofObligationGraph(
        allow_experimental=allow_experimental
    ).build(request)


def and_or_meanings_distinct(graph: ProofObligationGraph) -> bool:
    """Validate that AND and OR node kinds are not conflated in structure.

    AND nodes should only use depends_on-style joint edges to children;
    OR nodes should expose alternative edges (or OR_INTRO).
    """

    nodes = {n.node_id: n for n in graph.nodes}
    children_edges: dict[str, list[ProofGraphEdge]] = {
        n.node_id: [] for n in graph.nodes
    }
    for edge in graph.edges:
        children_edges.setdefault(edge.source_node_id, []).append(edge)

    for node in graph.nodes:
        outs = children_edges.get(node.node_id, [])
        if node.kind is GraphNodeKind.AND:
            for edge in outs:
                if edge.kind is GraphEdgeKind.ALTERNATIVE:
                    return False
                if edge.inference_rule == InferenceRule.OR_INTRO.value:
                    return False
        if node.kind is GraphNodeKind.OR:
            for edge in outs:
                # OR children may be alternatives or or_intro; depends_on alone
                # with and_intro would conflate meanings.
                if edge.inference_rule == InferenceRule.AND_INTRO.value:
                    return False
    return True


def every_edge_names_checked_rule(graph: ProofObligationGraph) -> bool:
    """True when every edge names a checked inference + reconstruction rule."""

    checked_rules = {r.value for r in InferenceRule}
    checked_methods = {m.value for m in ReconstructionMethod}
    for edge in graph.edges:
        if not edge.inference_rule or edge.inference_rule not in checked_rules:
            return False
        if (
            not edge.reconstruction_method
            or edge.reconstruction_method not in checked_methods
        ):
            return False
    return True


def experimental_paths_untrusted(result: BackwardGraphResult) -> bool:
    """True when no experimental edge/node has trusted authority or discharge."""

    nodes = {n.node_id: n for n in result.graph.nodes}
    for edge in result.graph.edges:
        experimental = (
            edge.edge_id in result.experimental_edge_ids
            or edge.metadata.get("experimental") is True
            or edge.inference_rule
            in {r.value for r in _EXPERIMENTAL_RULES}
            or edge.reconstruction_method
            in {m.value for m in _EXPERIMENTAL_RECONSTRUCTION}
        )
        if not experimental:
            continue
        if edge.metadata.get("trusted") is True:
            return False
        target = nodes.get(edge.target_node_id)
        if target is not None:
            if is_trusted_authority(target.authority):
                return False
            if target.status is HoleStatus.DISCHARGED:
                return False
    for node in result.graph.nodes:
        if node.metadata.get("experimental") is True:
            if is_trusted_authority(node.authority):
                return False
            if node.status is HoleStatus.DISCHARGED:
                return False
    return True


def solved_leaves_cite_evidence(result: BackwardGraphResult) -> bool:
    """True when every discharged leaf has an adequate evidence citation."""

    nodes = {n.node_id: n for n in result.graph.nodes}
    for nid in result.discharged_node_ids:
        node = nodes.get(nid)
        if node is None:
            return False
        if node.kind is GraphNodeKind.EVIDENCE:
            continue
        found = False
        for edge in result.graph.edges:
            if edge.source_node_id != nid:
                continue
            target = nodes.get(edge.target_node_id)
            if target is None:
                continue
            if target.kind is GraphNodeKind.EVIDENCE and is_trusted_authority(
                target.authority
            ):
                found = True
                break
            if (
                edge.inference_rule == InferenceRule.EVIDENCE_CITATION.value
                and is_trusted_authority(target.authority)
            ):
                found = True
                break
        if not found:
            return False
    return True


__all__ = [
    "BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE",
    "BACKWARD_GRAPH_BUILD_SCHEMA",
    "REGRESSION_STEP_SCHEMA",
    "OBLIGATION_SEED_SCHEMA",
    "EVIDENCE_CITATION_SCHEMA",
    "GRAPH_BUILD_RESULT_SCHEMA",
    "GRAPH_ALGORITHM_VERSION",
    "DEFAULT_BOUNDS",
    "PROOF_OBLIGATION_GRAPH_INTERFACE",
    "ProofGraphError",
    "InferenceRule",
    "ReconstructionMethod",
    "ObligationSeedKind",
    "GraphBuildStatus",
    "EvidenceCitation",
    "ObligationSeed",
    "RegressionStep",
    "BackwardGraphRequest",
    "BackwardGraphResult",
    "BackwardProofObligationGraph",
    "is_experimental_rule",
    "is_experimental_reconstruction",
    "is_trusted_authority",
    "cap_experimental_authority",
    "rule_is_checked",
    "hole_seed",
    "evidence_seed",
    "experimental_legacy_seed",
    "wp_step",
    "preimage_step",
    "temporal_step",
    "rule_inversion_step",
    "unification_step",
    "build_backward_proof_graph",
    "and_or_meanings_distinct",
    "every_edge_names_checked_rule",
    "experimental_paths_untrusted",
    "solved_leaves_cite_evidence",
]
