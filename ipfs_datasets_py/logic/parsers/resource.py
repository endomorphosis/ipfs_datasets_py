"""Separation, concurrency, session, relational, and refinement syntax.

Interfaces (LFP-032):

* ``ResourceLogicSyntax@1`` — parse/print/elaborate for separation logic with
  heap predicates, ownership, fractional permissions, and resource algebras
* ``SessionProcessSyntax@1`` — session/process actions, channel polarity,
  duality, rely-guarantee, and happens-before over concurrent composition
* ``RefinementSyntax@1`` — two-state relational binding, simulations, and
  refinement obligations with explicit boundedness

Capture-safety is fail-closed: free ownership/session/state variables,
rebindings, and out-of-scope channel endpoints are rejected with exact
scope diagnostics.  Unsupported resource algebras, process operators, or
concurrency assumptions never lower silently — every partial lower emits
an explicit loss receipt with bounds and a non-proof authority ceiling.

Grammar — ResourceLogicSyntax (connective precedence, low → high)::

    formula     ::= quant | iff
    quant       ::= ('exists'|'forall'|∃|∀) IDENT (':' SORT)? '.' formula
    iff         ::= implies (('iff'|↔) implies)*
    implies     ::= or (('implies'|→|=>) formula)?      # classical, right-assoc
    or          ::= and (('or'|∨) and)*
    and         ::= wand (('and'|∧) wand)*              # classical ∧
    wand        ::= sep (('-*'|'wand'|'sepimp') wand)?  # magic wand, right-assoc
    sep         ::= unary (('*'|'sep') unary)*          # separating *
    unary       ::= ('not'|¬) unary | atomic
    atomic      ::= 'emp' | 'true'|⊤ | 'false'|⊥
                  | term '|->' term ('@' perm)?
                  | 'points_to' '(' term ',' term (',' perm)? ')'
                  | 'owns' '(' principal ',' location (',' perm)? ')'
                  | 'pure' '(' formula ')'
                  | IDENT                              # pure atom
                  | '(' formula ')'
    perm        ::= NUMBER ('/' NUMBER)? | 'full' | 'half' | 'none'
    term        ::= IDENT | NUMBER

Grammar — SessionProcessSyntax (session types + concurrency atoms)::

    session     ::= 'end' | '!' IDENT '(' SORT ')' '.' session
                  | '?' IDENT '(' SORT ')' '.' session
                  | 'tau' '.' session | 'dual' '(' session ')'
                  | IDENT                              # named protocol ref
    concurrent  ::= 'rely' formula 'guarantee' formula 'for' IDENT
                  | 'hb' '(' IDENT ',' IDENT ')'
                  | 'atomic' '(' formula ')'
                  | session

Grammar — RefinementSyntax (two-state relational surface)::

    refinement  ::= two_state | simulation | obligation | formula
    two_state   ::= ('forall_states'|'exists_states')
                    IDENT ',' IDENT '.' refinement
    simulation  ::= ('forward_sim'|'backward_sim'|'simulates')
                    '(' IDENT ',' IDENT ')'
    obligation  ::= 'refines' '(' IDENT ',' IDENT (',' KIND)? ')'
    KIND        ::= 'trace'|'state'|'simulation'|'bisimulation'|'data'|'action'

Evidence subset: separation heap resource algebra concurrency rely guarantee
session process duality relational refinement simulation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum, StrEnum
from fractions import Fraction
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.concurrency import (
    CONCURRENCY_IR_INTERFACE,
    ChannelMode,
    ComponentKind,
    ConcurrencyIR,
    ConcurrencyValidationError,
    ConcurrentChannel,
    ConcurrentComponent,
    ConcurrentStep,
    FairnessKind,
    InterferenceKind,
    RelyGuaranteeContract,
    SessionAction,
    SessionPolarity,
    SessionProtocol,
    SessionRole,
    StepOwner,
    dual_polarity,
    dual_role,
)
from ipfs_datasets_py.logic.software_verification.heap import (
    Permission,
    ResourceAlgebraKind,
)
from ipfs_datasets_py.logic.software_verification.refinement import (
    REFINEMENT_IR_INTERFACE,
    BoundednessKind as RefinementBoundednessKind,
    RefinementBoundedness,
    RefinementIR,
    RefinementKind,
    RefinementObligation,
    RefinementState,
    RefinementSystem,
    RefinementTransition,
    RefinementValidationError,
    SimulationCouple,
    SimulationDirection,
    SimulationRelation,
    SystemLevel,
)
from ipfs_datasets_py.logic.software_verification.separation import (
    SEPARATION_LOGIC_IR_INTERFACE,
    FormulaKind,
    HeapTheory,
    SeparationFormula,
    SeparationLogicIR,
    SeparationLoweringError,
    SeparationValidationError,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_exists,
    mk_extension,
    mk_false,
    mk_forall,
    mk_true,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    CSTNodeRole,
    DiagnosticSeverity,
    LogicCST,
    LogicCSTNode,
    LogicToken,
    ParseArtifact,
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
    SourceRange,
    SurfaceASTRef,
    SyntaxContractError,
    SyntaxDiagnostic,
    TokenKind,
)
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    atomic_sort,
    declare_predicate,
    propositional_signature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

RESOURCE_LOGIC_SYNTAX_INTERFACE: Final = "ResourceLogicSyntax@1"
SESSION_PROCESS_SYNTAX_INTERFACE: Final = "SessionProcessSyntax@1"
REFINEMENT_SYNTAX_INTERFACE: Final = "RefinementSyntax@1"

RESOURCE_NOTATION_ID: Final = "canonical_resource_logic"
RESOURCE_NOTATION_VERSION: Final = "1.0.0"
RESOURCE_FAMILY_ID: Final = "separation_logic"
SESSION_FAMILY_ID: Final = "session_process"
REFINEMENT_FAMILY_ID: Final = "refinement"
CONCURRENCY_FAMILY_ID: Final = "concurrency"
RESOURCE_MODULE_VERSION: Final = "1.0.0"

RESOURCE_PARSE_RESULT_SCHEMA: Final = "canonical-resource-parse-result/v1"
SESSION_PARSE_RESULT_SCHEMA: Final = "canonical-session-parse-result/v1"
REFINEMENT_PARSE_RESULT_SCHEMA: Final = "canonical-refinement-parse-result/v1"
RESOURCE_PROFILE_SCHEMA: Final = "resource-logic-profile/v1"
SESSION_PROFILE_SCHEMA: Final = "session-process-profile/v1"
REFINEMENT_PROFILE_SCHEMA: Final = "refinement-syntax-profile/v1"
RESOURCE_BOUND_CONTRACT_SCHEMA: Final = "resource.bound-contract/v1"
RESOURCE_EVIDENCE_CONTRACT_SCHEMA: Final = "resource.evidence-contract/v1"
RESOURCE_LOWERING_RECEIPT_SCHEMA: Final = "resource.lowering-receipt/v1"
RESOURCE_SOURCE_MAP_SCHEMA: Final = "resource.source-map/v1"

# Extension payload schemas (versioned family.construct/vN).
RESOURCE_EMP_PAYLOAD_SCHEMA: Final = "resource.emp/v1"
RESOURCE_POINTS_TO_PAYLOAD_SCHEMA: Final = "resource.points_to/v1"
RESOURCE_SEP_CONJ_PAYLOAD_SCHEMA: Final = "resource.sep_conj/v1"
RESOURCE_WAND_PAYLOAD_SCHEMA: Final = "resource.wand/v1"
RESOURCE_OWNS_PAYLOAD_SCHEMA: Final = "resource.owns/v1"
RESOURCE_PURE_PAYLOAD_SCHEMA: Final = "resource.pure/v1"
RESOURCE_PERM_PAYLOAD_SCHEMA: Final = "resource.permission/v1"
RESOURCE_ATOM_PAYLOAD_SCHEMA: Final = "resource.atom/v1"
SESSION_ACTION_PAYLOAD_SCHEMA: Final = "session.action/v1"
SESSION_END_PAYLOAD_SCHEMA: Final = "session.end/v1"
SESSION_DUAL_PAYLOAD_SCHEMA: Final = "session.dual/v1"
SESSION_CHANNEL_PAYLOAD_SCHEMA: Final = "session.channel/v1"
SESSION_RELY_GUARANTEE_PAYLOAD_SCHEMA: Final = "session.rely_guarantee/v1"
SESSION_HB_PAYLOAD_SCHEMA: Final = "session.happens_before/v1"
SESSION_ATOMIC_PAYLOAD_SCHEMA: Final = "session.atomic/v1"
SESSION_REF_PAYLOAD_SCHEMA: Final = "session.protocol_ref/v1"
REFINEMENT_TWO_STATE_PAYLOAD_SCHEMA: Final = "refinement.two_state/v1"
REFINEMENT_SIM_PAYLOAD_SCHEMA: Final = "refinement.simulation/v1"
REFINEMENT_OBLIGATION_PAYLOAD_SCHEMA: Final = "refinement.obligation/v1"
REFINEMENT_STATE_PAYLOAD_SCHEMA: Final = "refinement.state_var/v1"

HEAP_LOCATION_SORT_NAME: Final = "HeapLoc"
HEAP_VALUE_SORT_NAME: Final = "HeapVal"
OWNER_SORT_NAME: Final = "Owner"
CHANNEL_SORT_NAME: Final = "Channel"
STATE_SORT_NAME: Final = "State"
EVENT_SORT_NAME: Final = "Event"

HEAP_LOC_SORT: Final = atomic_sort(HEAP_LOCATION_SORT_NAME)
HEAP_VAL_SORT: Final = atomic_sort(HEAP_VALUE_SORT_NAME)
OWNER_SORT: Final = atomic_sort(OWNER_SORT_NAME)
CHANNEL_SORT: Final = atomic_sort(CHANNEL_SORT_NAME)
STATE_SORT: Final = atomic_sort(STATE_SORT_NAME)
EVENT_SORT: Final = atomic_sort(EVENT_SORT_NAME)

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "resource.unexpected_token"
CODE_TRAILING_INPUT: Final = "resource.trailing_input"
CODE_EMPTY_INPUT: Final = "resource.empty_input"
CODE_PARSE_DEPTH: Final = "resource.parse_depth_exceeded"
CODE_UNBALANCED: Final = "resource.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "resource.lexer_error"
CODE_PROFILE_MISMATCH: Final = "resource.profile_mismatch"
CODE_ROUND_TRIP: Final = "resource.round_trip_failed"
CODE_FREE_VARIABLE: Final = "resource.free_variable"
CODE_REBIND_VARIABLE: Final = "resource.variable_rebind"
CODE_UNSUPPORTED_ALGEBRA: Final = "resource.unsupported_resource_algebra"
CODE_UNSUPPORTED_PROCESS: Final = "resource.unsupported_process_operator"
CODE_UNSUPPORTED_CONCURRENCY: Final = "resource.unsupported_concurrency_assumption"
CODE_OWNERSHIP_CAPTURE: Final = "resource.ownership_capture_unsafe"
CODE_CHANNEL_CAPTURE: Final = "resource.channel_capture_unsafe"
CODE_SESSION_DUALITY: Final = "resource.session_duality_invalid"
CODE_TWO_STATE_CAPTURE: Final = "resource.two_state_capture_unsafe"
CODE_MISSING_BOUND: Final = "resource.missing_bound"
CODE_PROMOTION_REJECTED: Final = "resource.unbounded_promotion_rejected"
CODE_INVALID_PERMISSION: Final = "resource.invalid_permission"
CODE_LOWERING_LOSS: Final = "resource.lowering_loss"
CODE_INVALID_SESSION: Final = "resource.invalid_session"
CODE_INVALID_REFINEMENT: Final = "resource.invalid_refinement"

_ALL_RESOURCE_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_PROFILE_MISMATCH,
        CODE_ROUND_TRIP,
        CODE_FREE_VARIABLE,
        CODE_REBIND_VARIABLE,
        CODE_UNSUPPORTED_ALGEBRA,
        CODE_UNSUPPORTED_PROCESS,
        CODE_UNSUPPORTED_CONCURRENCY,
        CODE_OWNERSHIP_CAPTURE,
        CODE_CHANNEL_CAPTURE,
        CODE_SESSION_DUALITY,
        CODE_TWO_STATE_CAPTURE,
        CODE_MISSING_BOUND,
        CODE_PROMOTION_REJECTED,
        CODE_INVALID_PERMISSION,
        CODE_LOWERING_LOSS,
        CODE_INVALID_SESSION,
        CODE_INVALID_REFINEMENT,
    }
)

# Connectives / operators.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "|"})  # not || — reserved
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})
_FORALL_OPS: Final[frozenset[str]] = frozenset({"forall", "∀"})
_EXISTS_OPS: Final[frozenset[str]] = frozenset({"exists", "∃"})
_SEP_OPS: Final[frozenset[str]] = frozenset({"*", "sep", "∗"})
_WAND_OPS: Final[frozenset[str]] = frozenset({"-*", "wand", "sepimp", "─*"})
_POINTS_TO_OPS: Final[frozenset[str]] = frozenset({"|->", "↦", "points_to"})

# Closed process operators that are rejected (fail closed).
UNSUPPORTED_PROCESS_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "choice",
        "sum",
        "hide",
        "restrict",
        "interrupt",
        "priority",
        "link",
        "amb",
        "open",
        "cap",
        "replication_unbounded",
        "name_passing_higher_order",
        "mobile_ambients",
        "join_calculus",
        "pi_match",
        "spi_encryption",
    }
)

# Resource algebras that lower only with explicit loss (never silently).
UNSUPPORTED_RESOURCE_ALGEBRAS: Final[frozenset[str]] = frozenset(
    {
        ResourceAlgebraKind.CUSTOM.value,
        "higher_order_ra",
        "step_indexed_ra",
        "iris_ra",
        "cancellative_ra",
        "uninterpreted_ra",
    }
)

# Concurrency assumptions that require explicit loss/bounds on lower.
UNSUPPORTED_CONCURRENCY_ASSUMPTIONS: Final[frozenset[str]] = frozenset(
    {
        "implicit_interference",
        "unbounded_fairness",
        "data_race_free_assumed",
        "sc_memory_model_assumed",
        "lock_freedom_assumed",
        "wait_freedom_assumed",
        "linearizability_assumed",
        "happens_before_complete",
    }
)

_SUPPORTED_HEAP_THEORIES: Final[frozenset[str]] = frozenset(
    {
        HeapTheory.CLASSICAL_SL.value,
        HeapTheory.FRACTIONAL_PERMISSION.value,
        HeapTheory.BINARY_PERMISSION.value,
    }
)

_RESOURCE_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "forall",
    "exists",
    "emp",
    "pure",
    "points_to",
    "owns",
    "sep",
    "wand",
    "sepimp",
    "full",
    "half",
    "none",
    "end",
    "tau",
    "dual",
    "rely",
    "guarantee",
    "for",
    "hb",
    "atomic",
    "channel",
    "send",
    "recv",
    "receive",
    "forward_sim",
    "backward_sim",
    "simulates",
    "refines",
    "forall_states",
    "exists_states",
    "trace",
    "state",
    "simulation",
    "bisimulation",
    "data",
    "action",
)

_DEFAULT_MULTI_OPS: Final[tuple[str, ...]] = (
    "<=>",
    "<->",
    "==>",
    "=>",
    "->",
    "<-",
    "<=",
    ">=",
    "!=",
    "==",
    "/=",
    "&&",
    "||",
    "**",
    "..",
    "::",
    "|->",
    "-*",
)

# Surface rewrites before lexing (unicode / multi-glyph).
_SURFACE_REWRITES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"↦"), " |-> "),
    (re.compile(r"∗"), " * "),
    (re.compile(r"─\*"), " -* "),
    (re.compile(r"—\*"), " -* "),
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by resource/concurrency/refinement evidence."""

    BOUNDED = "bounded"
    ADVISORY = "advisory"
    NONE = "none"


class BoundednessKind(str, Enum):
    """Semantic bound declared for resource/concurrency evidence."""

    FINITE_HEAP = "finite_heap"
    FINITE_SCHEDULE = "finite_schedule"
    FINITE_SIMULATION = "finite_simulation"
    MODEL_CHECK = "model_check"
    UNBOUNDED = "unbounded"


class ResourceLogicKind(str, Enum):
    """Declared resource-logic surface family."""

    SEPARATION = "separation"
    FRACTIONAL = "fractional"
    OWNERSHIP = "ownership"


class SessionSurfaceKind(str, Enum):
    """Declared session/process surface family."""

    SESSION = "session"
    RELY_GUARANTEE = "rely_guarantee"
    HAPPENS_BEFORE = "happens_before"
    CONCURRENT = "concurrent"


class RefinementSurfaceKind(str, Enum):
    """Declared refinement surface family."""

    TWO_STATE = "two_state"
    SIMULATION = "simulation"
    OBLIGATION = "obligation"
    RELATIONAL = "relational"


class LossKind(str, Enum):
    """Why a lowering is partial / lossy."""

    RESOURCE_ALGEBRA = "resource_algebra"
    PROCESS_OPERATOR = "process_operator"
    CONCURRENCY_ASSUMPTION = "concurrency_assumption"
    HEAP_THEORY = "heap_theory"
    SPATIAL_CONNECTIVE = "spatial_connective"
    UNBOUNDED_CLAIM = "unbounded_claim"
    NONE = "none"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    WAND = 50
    SEP = 60
    UNARY = 70
    ATOM = 80


# ---------------------------------------------------------------------------
# Bound / evidence / lowering contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceBoundContract:
    """Explicit finite bound for resource/concurrency/refinement lowerings."""

    max_heap_cells: int = 64
    max_threads: int = 8
    max_schedule_steps: int = 64
    max_simulation_steps: int = 64
    boundedness: BoundednessKind | str = BoundednessKind.FINITE_HEAP
    schema_version: str = RESOURCE_BOUND_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "max_heap_cells",
            "max_threads",
            "max_schedule_steps",
            "max_simulation_steps",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SyntaxContractError(f"{name} must be a positive integer")
        bound = (
            self.boundedness
            if isinstance(self.boundedness, BoundednessKind)
            else BoundednessKind(str(self.boundedness))
        )
        if bound is BoundednessKind.UNBOUNDED:
            raise SyntaxContractError(
                "ResourceBoundContract rejects unboundedness; partial lowers "
                "retain a finite ceiling"
            )
        object.__setattr__(self, "boundedness", bound)
        if self.schema_version != RESOURCE_BOUND_CONTRACT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported bound contract schema {self.schema_version!r}"
            )

    @property
    def unbounded_proof(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundedness": self.boundedness.value
            if isinstance(self.boundedness, BoundednessKind)
            else str(self.boundedness),
            "max_heap_cells": self.max_heap_cells,
            "max_schedule_steps": self.max_schedule_steps,
            "max_simulation_steps": self.max_simulation_steps,
            "max_threads": self.max_threads,
            "schema_version": self.schema_version,
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceBoundContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("bound contract must be a mapping")
        return cls(
            max_heap_cells=int(value.get("max_heap_cells", 64)),
            max_threads=int(value.get("max_threads", 8)),
            max_schedule_steps=int(value.get("max_schedule_steps", 64)),
            max_simulation_steps=int(value.get("max_simulation_steps", 64)),
            boundedness=value.get(
                "boundedness", BoundednessKind.FINITE_HEAP.value
            ),
            schema_version=str(
                value.get("schema_version") or RESOURCE_BOUND_CONTRACT_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class ResourceEvidenceContract:
    """Authority ceiling for resource/concurrency/refinement evidence."""

    bound: ResourceBoundContract = field(default_factory=ResourceBoundContract)
    authority: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    schema_version: str = RESOURCE_EVIDENCE_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        if not isinstance(self.bound, ResourceBoundContract):
            raise SyntaxContractError("bound must be a ResourceBoundContract")
        if authority not in {
            EvidenceAuthority.BOUNDED,
            EvidenceAuthority.ADVISORY,
            EvidenceAuthority.NONE,
        }:
            raise SyntaxContractError(
                "resource evidence admits only none/advisory/bounded authority"
            )
        object.__setattr__(self, "authority", authority)
        if self.schema_version != RESOURCE_EVIDENCE_CONTRACT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported evidence contract schema {self.schema_version!r}"
            )

    @property
    def unbounded_proof(self) -> bool:
        return False

    @property
    def may_promote_to_unbounded_proof(self) -> bool:
        return False

    @property
    def authority_ceiling(self) -> EvidenceAuthority:
        auth = self.authority
        return (
            auth
            if isinstance(auth, EvidenceAuthority)
            else EvidenceAuthority(str(auth))
        )

    def promote_to_unbounded_proof(self) -> None:
        """Fail closed: bounded resource results are not universal proofs."""

        raise SyntaxContractError(
            f"resource/concurrency/refinement evidence cannot be promoted to "
            f"unbounded proof (authority={self.authority_ceiling.value}, "
            f"boundedness={self.bound.boundedness.value})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority_ceiling.value,
            "authority_ceiling": self.authority_ceiling.value,
            "bound": self.bound.to_dict(),
            "may_promote_to_unbounded_proof": False,
            "schema_version": self.schema_version,
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceEvidenceContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("evidence contract must be a mapping")
        raw_bound = value.get("bound")
        bound = (
            raw_bound
            if isinstance(raw_bound, ResourceBoundContract)
            else ResourceBoundContract.from_dict(
                raw_bound if isinstance(raw_bound, Mapping) else {}
            )
        )
        return cls(
            bound=bound,
            authority=value.get("authority", EvidenceAuthority.BOUNDED.value),
            schema_version=str(
                value.get("schema_version") or RESOURCE_EVIDENCE_CONTRACT_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class LoweringReceipt:
    """Explicit loss/bounds receipt for partial or unsupported lowers.

    Unsupported resource algebras, process operators, and concurrency
    assumptions never become silent FOL/SMT claims.  When a lower is
    partial, ``supported`` is false and ``loss_kind`` / ``loss_bounds``
    record the exact gap.
    """

    supported: bool
    loss_kind: LossKind | str = LossKind.NONE
    loss_message: str = ""
    loss_bounds: Mapping[str, Any] = field(default_factory=dict)
    authority: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    target_interface: str = ""
    features_retained: tuple[str, ...] = ()
    features_dropped: tuple[str, ...] = ()
    schema_version: str = RESOURCE_LOWERING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.supported, bool):
            raise SyntaxContractError("supported must be a boolean")
        loss = (
            self.loss_kind
            if isinstance(self.loss_kind, LossKind)
            else LossKind(str(self.loss_kind))
        )
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        if self.supported and loss is not LossKind.NONE:
            raise SyntaxContractError(
                "supported lowers must declare loss_kind=none"
            )
        if not self.supported and loss is LossKind.NONE:
            raise SyntaxContractError(
                "unsupported lowers require an explicit loss_kind"
            )
        if authority is not EvidenceAuthority.BOUNDED and not self.supported:
            # Partial lowers may be advisory, never unbounded proof.
            if authority not in {
                EvidenceAuthority.ADVISORY,
                EvidenceAuthority.NONE,
            }:
                raise SyntaxContractError(
                    "lossy lowers admit only none/advisory/bounded authority"
                )
        object.__setattr__(self, "loss_kind", loss)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(
            self,
            "loss_message",
            str(self.loss_message or "").strip(),
        )
        object.__setattr__(
            self,
            "loss_bounds",
            dict(self.loss_bounds) if self.loss_bounds is not None else {},
        )
        object.__setattr__(
            self,
            "target_interface",
            str(self.target_interface or "").strip(),
        )
        object.__setattr__(
            self,
            "features_retained",
            tuple(str(item) for item in self.features_retained),
        )
        object.__setattr__(
            self,
            "features_dropped",
            tuple(str(item) for item in self.features_dropped),
        )
        if self.schema_version != RESOURCE_LOWERING_RECEIPT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported lowering receipt schema {self.schema_version!r}"
            )

    @property
    def has_loss(self) -> bool:
        return not self.supported

    @property
    def unbounded_proof(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": (
                self.authority.value
                if isinstance(self.authority, EvidenceAuthority)
                else str(self.authority)
            ),
            "features_dropped": list(self.features_dropped),
            "features_retained": list(self.features_retained),
            "has_loss": self.has_loss,
            "loss_bounds": dict(self.loss_bounds),
            "loss_kind": (
                self.loss_kind.value
                if isinstance(self.loss_kind, LossKind)
                else str(self.loss_kind)
            ),
            "loss_message": self.loss_message,
            "schema_version": self.schema_version,
            "supported": self.supported,
            "target_interface": self.target_interface,
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LoweringReceipt:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("lowering receipt must be a mapping")
        return cls(
            supported=bool(value.get("supported", False)),
            loss_kind=value.get("loss_kind", LossKind.NONE.value),
            loss_message=str(value.get("loss_message") or ""),
            loss_bounds=value.get("loss_bounds") or {},
            authority=value.get("authority", EvidenceAuthority.BOUNDED.value),
            target_interface=str(value.get("target_interface") or ""),
            features_retained=tuple(value.get("features_retained") or ()),
            features_dropped=tuple(value.get("features_dropped") or ()),
            schema_version=str(
                value.get("schema_version") or RESOURCE_LOWERING_RECEIPT_SCHEMA
            ),
        )


def supported_lowering_receipt(
    *,
    target_interface: str,
    features_retained: Sequence[str] = (),
) -> LoweringReceipt:
    """Receipt for a fully supported lower (no loss)."""

    return LoweringReceipt(
        supported=True,
        loss_kind=LossKind.NONE,
        target_interface=target_interface,
        features_retained=tuple(features_retained),
        authority=EvidenceAuthority.BOUNDED,
    )


def lossy_lowering_receipt(
    *,
    loss_kind: LossKind | str,
    loss_message: str,
    loss_bounds: Mapping[str, Any],
    target_interface: str = "",
    features_retained: Sequence[str] = (),
    features_dropped: Sequence[str] = (),
    authority: EvidenceAuthority | str = EvidenceAuthority.ADVISORY,
) -> LoweringReceipt:
    """Receipt for an unsupported or partial lower with explicit bounds."""

    return LoweringReceipt(
        supported=False,
        loss_kind=loss_kind,
        loss_message=loss_message,
        loss_bounds=dict(loss_bounds),
        target_interface=target_interface,
        features_retained=tuple(features_retained),
        features_dropped=tuple(features_dropped),
        authority=authority,
    )


# ---------------------------------------------------------------------------
# Semantic profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceLogicProfile:
    """Explicit separation/ownership semantic choices.

    Heap theory and resource algebra participate in identity.  Unsupported
    algebras are recorded and can only lower with explicit loss receipts.
    """

    profile_id: str
    logic: ResourceLogicKind | str = ResourceLogicKind.SEPARATION
    heap_theory: HeapTheory | str = HeapTheory.CLASSICAL_SL
    resource_algebra: str = ResourceAlgebraKind.DISJOINT_HEAP.value
    evidence: ResourceEvidenceContract = field(
        default_factory=ResourceEvidenceContract
    )
    admit_fractional_permissions: bool = True
    admit_wand: bool = True
    admit_ownership: bool = True
    schema_version: str = RESOURCE_PROFILE_SCHEMA

    interface: ClassVar[str] = RESOURCE_LOGIC_SYNTAX_INTERFACE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or self.profile_id != self.profile_id.strip()
            or "\x00" in self.profile_id
        ):
            raise SyntaxContractError(
                "profile_id must be a non-empty trimmed string without NUL"
            )
        logic = (
            self.logic
            if isinstance(self.logic, ResourceLogicKind)
            else ResourceLogicKind(str(self.logic))
        )
        theory = (
            self.heap_theory
            if isinstance(self.heap_theory, HeapTheory)
            else HeapTheory(str(self.heap_theory))
        )
        algebra = str(self.resource_algebra or "").strip()
        if not algebra:
            raise SyntaxContractError("resource_algebra must be non-empty")
        if not isinstance(self.evidence, ResourceEvidenceContract):
            raise SyntaxContractError("evidence must be a ResourceEvidenceContract")
        for name in (
            "admit_fractional_permissions",
            "admit_wand",
            "admit_ownership",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        object.__setattr__(self, "logic", logic)
        object.__setattr__(self, "heap_theory", theory)
        object.__setattr__(self, "resource_algebra", algebra)
        if self.schema_version != RESOURCE_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported ResourceLogicProfile schema {self.schema_version!r}"
            )

    @property
    def algebra_supported(self) -> bool:
        return self.resource_algebra not in UNSUPPORTED_RESOURCE_ALGEBRAS

    @property
    def heap_theory_supported(self) -> bool:
        theory = (
            self.heap_theory.value
            if isinstance(self.heap_theory, HeapTheory)
            else str(self.heap_theory)
        )
        return theory in _SUPPORTED_HEAP_THEORIES

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_fractional_permissions": self.admit_fractional_permissions,
            "admit_ownership": self.admit_ownership,
            "admit_wand": self.admit_wand,
            "algebra_supported": self.algebra_supported,
            "evidence": self.evidence.to_dict(),
            "heap_theory": (
                self.heap_theory.value
                if isinstance(self.heap_theory, HeapTheory)
                else str(self.heap_theory)
            ),
            "heap_theory_supported": self.heap_theory_supported,
            "logic": (
                self.logic.value
                if isinstance(self.logic, ResourceLogicKind)
                else str(self.logic)
            ),
            "profile_id": self.profile_id,
            "resource_algebra": self.resource_algebra,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_identity

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceLogicProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("resource profile must be a mapping")
        raw_evidence = value.get("evidence")
        evidence = (
            raw_evidence
            if isinstance(raw_evidence, ResourceEvidenceContract)
            else ResourceEvidenceContract.from_dict(
                raw_evidence if isinstance(raw_evidence, Mapping) else {}
            )
        )
        return cls(
            profile_id=str(value.get("profile_id") or "separation:classical"),
            logic=value.get("logic", ResourceLogicKind.SEPARATION.value),
            heap_theory=value.get(
                "heap_theory", HeapTheory.CLASSICAL_SL.value
            ),
            resource_algebra=str(
                value.get("resource_algebra")
                or ResourceAlgebraKind.DISJOINT_HEAP.value
            ),
            evidence=evidence,
            admit_fractional_permissions=bool(
                value.get("admit_fractional_permissions", True)
            ),
            admit_wand=bool(value.get("admit_wand", True)),
            admit_ownership=bool(value.get("admit_ownership", True)),
            schema_version=str(
                value.get("schema_version") or RESOURCE_PROFILE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class SessionProcessProfile:
    """Explicit session/process/concurrency semantic choices."""

    profile_id: str
    surface: SessionSurfaceKind | str = SessionSurfaceKind.SESSION
    evidence: ResourceEvidenceContract = field(
        default_factory=lambda: ResourceEvidenceContract(
            bound=ResourceBoundContract(
                boundedness=BoundednessKind.FINITE_SCHEDULE
            )
        )
    )
    admit_duality: bool = True
    admit_rely_guarantee: bool = True
    admit_happens_before: bool = True
    reject_unsupported_process_ops: bool = True
    schema_version: str = SESSION_PROFILE_SCHEMA

    interface: ClassVar[str] = SESSION_PROCESS_SYNTAX_INTERFACE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or self.profile_id != self.profile_id.strip()
            or "\x00" in self.profile_id
        ):
            raise SyntaxContractError(
                "profile_id must be a non-empty trimmed string without NUL"
            )
        surface = (
            self.surface
            if isinstance(self.surface, SessionSurfaceKind)
            else SessionSurfaceKind(str(self.surface))
        )
        if not isinstance(self.evidence, ResourceEvidenceContract):
            raise SyntaxContractError("evidence must be a ResourceEvidenceContract")
        for name in (
            "admit_duality",
            "admit_rely_guarantee",
            "admit_happens_before",
            "reject_unsupported_process_ops",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        object.__setattr__(self, "surface", surface)
        if self.schema_version != SESSION_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported SessionProcessProfile schema {self.schema_version!r}"
            )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_duality": self.admit_duality,
            "admit_happens_before": self.admit_happens_before,
            "admit_rely_guarantee": self.admit_rely_guarantee,
            "evidence": self.evidence.to_dict(),
            "profile_id": self.profile_id,
            "reject_unsupported_process_ops": self.reject_unsupported_process_ops,
            "schema_version": self.schema_version,
            "surface": (
                self.surface.value
                if isinstance(self.surface, SessionSurfaceKind)
                else str(self.surface)
            ),
            "unsupported_process_operators": sorted(UNSUPPORTED_PROCESS_OPERATORS),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_identity

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SessionProcessProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("session profile must be a mapping")
        raw_evidence = value.get("evidence")
        evidence = (
            raw_evidence
            if isinstance(raw_evidence, ResourceEvidenceContract)
            else ResourceEvidenceContract.from_dict(
                raw_evidence if isinstance(raw_evidence, Mapping) else {}
            )
        )
        return cls(
            profile_id=str(value.get("profile_id") or "session:default"),
            surface=value.get("surface", SessionSurfaceKind.SESSION.value),
            evidence=evidence,
            admit_duality=bool(value.get("admit_duality", True)),
            admit_rely_guarantee=bool(value.get("admit_rely_guarantee", True)),
            admit_happens_before=bool(value.get("admit_happens_before", True)),
            reject_unsupported_process_ops=bool(
                value.get("reject_unsupported_process_ops", True)
            ),
            schema_version=str(
                value.get("schema_version") or SESSION_PROFILE_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class RefinementSyntaxProfile:
    """Explicit refinement/relational semantic choices."""

    profile_id: str
    surface: RefinementSurfaceKind | str = RefinementSurfaceKind.TWO_STATE
    evidence: ResourceEvidenceContract = field(
        default_factory=lambda: ResourceEvidenceContract(
            bound=ResourceBoundContract(
                boundedness=BoundednessKind.FINITE_SIMULATION
            )
        )
    )
    admit_forward_simulation: bool = True
    admit_backward_simulation: bool = True
    require_two_state_capture_safety: bool = True
    schema_version: str = REFINEMENT_PROFILE_SCHEMA

    interface: ClassVar[str] = REFINEMENT_SYNTAX_INTERFACE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or self.profile_id != self.profile_id.strip()
            or "\x00" in self.profile_id
        ):
            raise SyntaxContractError(
                "profile_id must be a non-empty trimmed string without NUL"
            )
        surface = (
            self.surface
            if isinstance(self.surface, RefinementSurfaceKind)
            else RefinementSurfaceKind(str(self.surface))
        )
        if not isinstance(self.evidence, ResourceEvidenceContract):
            raise SyntaxContractError("evidence must be a ResourceEvidenceContract")
        for name in (
            "admit_forward_simulation",
            "admit_backward_simulation",
            "require_two_state_capture_safety",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        object.__setattr__(self, "surface", surface)
        if self.schema_version != REFINEMENT_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported RefinementSyntaxProfile schema {self.schema_version!r}"
            )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_backward_simulation": self.admit_backward_simulation,
            "admit_forward_simulation": self.admit_forward_simulation,
            "evidence": self.evidence.to_dict(),
            "profile_id": self.profile_id,
            "require_two_state_capture_safety": (
                self.require_two_state_capture_safety
            ),
            "schema_version": self.schema_version,
            "surface": (
                self.surface.value
                if isinstance(self.surface, RefinementSurfaceKind)
                else str(self.surface)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_identity

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementSyntaxProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("refinement profile must be a mapping")
        raw_evidence = value.get("evidence")
        evidence = (
            raw_evidence
            if isinstance(raw_evidence, ResourceEvidenceContract)
            else ResourceEvidenceContract.from_dict(
                raw_evidence if isinstance(raw_evidence, Mapping) else {}
            )
        )
        return cls(
            profile_id=str(value.get("profile_id") or "refinement:two_state"),
            surface=value.get(
                "surface", RefinementSurfaceKind.TWO_STATE.value
            ),
            evidence=evidence,
            admit_forward_simulation=bool(
                value.get("admit_forward_simulation", True)
            ),
            admit_backward_simulation=bool(
                value.get("admit_backward_simulation", True)
            ),
            require_two_state_capture_safety=bool(
                value.get("require_two_state_capture_safety", True)
            ),
            schema_version=str(
                value.get("schema_version") or REFINEMENT_PROFILE_SCHEMA
            ),
        )


def profile_separation(
    *,
    fractional: bool = False,
    algebra: str = ResourceAlgebraKind.DISJOINT_HEAP.value,
) -> ResourceLogicProfile:
    """Default classical or fractional separation-logic profile."""

    if fractional:
        return ResourceLogicProfile(
            profile_id="separation:fractional",
            logic=ResourceLogicKind.FRACTIONAL,
            heap_theory=HeapTheory.FRACTIONAL_PERMISSION,
            resource_algebra=ResourceAlgebraKind.FRACTIONAL_PERMISSION.value,
            admit_fractional_permissions=True,
        )
    return ResourceLogicProfile(
        profile_id="separation:classical",
        logic=ResourceLogicKind.SEPARATION,
        heap_theory=HeapTheory.CLASSICAL_SL,
        resource_algebra=algebra,
        admit_fractional_permissions=False,
    )


def profile_ownership() -> ResourceLogicProfile:
    """Ownership-transfer oriented resource profile."""

    return ResourceLogicProfile(
        profile_id="separation:ownership",
        logic=ResourceLogicKind.OWNERSHIP,
        heap_theory=HeapTheory.FRACTIONAL_PERMISSION,
        resource_algebra=ResourceAlgebraKind.FRACTIONAL_PERMISSION.value,
        admit_ownership=True,
        admit_fractional_permissions=True,
    )


def profile_session(
    *,
    surface: SessionSurfaceKind | str = SessionSurfaceKind.SESSION,
) -> SessionProcessProfile:
    """Default session/process profile."""

    kind = (
        surface
        if isinstance(surface, SessionSurfaceKind)
        else SessionSurfaceKind(str(surface))
    )
    return SessionProcessProfile(
        profile_id=f"session:{kind.value}",
        surface=kind,
    )


def profile_rely_guarantee() -> SessionProcessProfile:
    """Rely-guarantee concurrency profile."""

    return SessionProcessProfile(
        profile_id="session:rely_guarantee",
        surface=SessionSurfaceKind.RELY_GUARANTEE,
    )


def profile_refinement(
    *,
    surface: RefinementSurfaceKind | str = RefinementSurfaceKind.TWO_STATE,
) -> RefinementSyntaxProfile:
    """Default refinement/relational profile."""

    kind = (
        surface
        if isinstance(surface, RefinementSurfaceKind)
        else RefinementSurfaceKind(str(surface))
    )
    return RefinementSyntaxProfile(
        profile_id=f"refinement:{kind.value}",
        surface=kind,
    )


# ---------------------------------------------------------------------------
# Diagnostics / parse failures
# ---------------------------------------------------------------------------


class ResourceParseError(SyntaxContractError):
    """Raised when resource/session/refinement parsing fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        range: SourceRange | None = None,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.range = range
        self.diagnostics = tuple(diagnostics)


class _ParseFail(Exception):
    """Internal control-flow exception carrying one diagnostic."""

    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None = None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:resource:{code.replace('.', '-')}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


def rewrite_resource_surface(text: str) -> str:
    """Rewrite unicode/multi-glyph resource surface forms for lexing."""

    result = text
    for pattern, replacement in _SURFACE_REWRITES:
        result = pattern.sub(replacement, result)
    return result


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


class _Cursor:
    """Token stream cursor with depth tracking."""

    def __init__(
        self,
        tokens: Sequence[LogicToken],
        *,
        limits: ParseLimits,
    ) -> None:
        self.tokens = tuple(tokens)
        self.index = 0
        self.depth = 0
        self.limits = limits

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> LogicToken:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def advance(self) -> LogicToken:
        token = self.current()
        if token.kind != TokenKind.EOF.value:
            self.index += 1
        return token

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        token = self.current()
        if token.lexeme in lexemes:
            self.advance()
            return token
        return None

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        folded = {item.casefold() for item in lexemes}
        if token.lexeme in lexemes or token.lexeme.casefold() in folded:
            self.advance()
            return token
        return None

    def expect_lexeme(
        self, lexeme: str, *, code: str = CODE_UNEXPECTED_TOKEN
    ) -> LogicToken:
        token = self.current()
        if token.lexeme != lexeme:
            raise _ParseFail(
                _diag(
                    code=code,
                    message=f"expected {lexeme!r}; got {token.lexeme!r}",
                    range=token.range,
                )
            )
        self.advance()
        return token

    def expect_ident(self) -> LogicToken:
        token = self.current()
        if token.kind not in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"expected identifier; got {token.lexeme!r}",
                    range=token.range,
                )
            )
        self.advance()
        return token

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        return SourceRange(
            start=min(start.start, end.start), end=max(start.end, end.end)
        )


# ---------------------------------------------------------------------------
# Resource (separation) parser engine
# ---------------------------------------------------------------------------


class _ResourceParserEngine:
    """Recursive-descent separation-logic parser with capture-safe binders."""

    def __init__(
        self,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: ResourceLogicProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, limits=limits)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._scope: list[str] = []

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"{self.expression_id}:{prefix}:{self._counter}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if not self.document.text.strip():
            return None, (
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty resource-logic input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_formula()
            if self.cursor.current().kind != TokenKind.EOF.value:
                tok = self.cursor.current()
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                        remediation="Remove trailing tokens or close open constructs",
                    )
                )
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_quant_or_iff()
        finally:
            self._leave()

    def _parse_quant_or_iff(self) -> LogicNode:
        token = self.cursor.current()
        quant: str | None = None
        if token.lexeme in _FORALL_OPS or token.lexeme.casefold() == "forall":
            quant = "forall"
        elif token.lexeme in _EXISTS_OPS or token.lexeme.casefold() == "exists":
            quant = "exists"
        if quant is None:
            return self._parse_iff()

        start = self.cursor.advance()
        name_tok = self.cursor.expect_ident()
        name = name_tok.lexeme
        if name in self._scope:
            raise _ParseFail(
                _diag(
                    code=CODE_REBIND_VARIABLE,
                    message=(
                        f"variable {name!r} is already bound "
                        f"(rebinding is capture-unsafe); "
                        f"scope={list(self._scope)!r}"
                    ),
                    range=name_tok.range,
                    remediation="Choose a fresh binder name",
                    metadata={"variable": name, "scope": list(self._scope)},
                )
            )
        sort = HEAP_LOC_SORT
        if self.cursor.match_lexeme(":") is not None:
            sort_tok = self.cursor.expect_ident()
            sort = atomic_sort(sort_tok.lexeme)
            if sort.is_bool:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message="binders must not use Bool sort",
                        range=sort_tok.range,
                    )
                )
        self.cursor.expect_lexeme(".")
        self._scope.append(name)
        try:
            body = self._parse_formula()
        finally:
            self._scope.pop()
        span = self.cursor.range_span(
            start.range, body.range or name_tok.range
        )
        binder = Binder(name=name, sort=sort)
        if quant == "forall":
            built = mk_forall(self._nid("forall"), (binder,), body)
        else:
            built = mk_exists(self._nid("exists"), (binder,), body)
        return LogicNode(
            node_id=built.node_id,
            kind=built.kind,
            sort=BOOL_SORT,
            binders=built.binders,
            arguments=built.arguments,
            range=span,
            metadata={
                "profile_id": self.profile.profile_id,
                "resource_quantifier": True,
                "variable": name,
            },
        )

    def _parse_iff(self) -> LogicNode:
        left = self._parse_implies()
        while self.cursor.match_any(_IFF_OPS) is not None:
            right = self._parse_implies()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = LogicNode(
                node_id=self._nid("iff"),
                kind=NodeKind.IFF,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
        return left

    def _parse_implies(self) -> LogicNode:
        left = self._parse_or()
        if self.cursor.match_any(_IMPLIES_OPS) is not None:
            right = self._parse_implies()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            return LogicNode(
                node_id=self._nid("implies"),
                kind=NodeKind.IMPLIES,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
        return left

    def _parse_or(self) -> LogicNode:
        nodes = [self._parse_and()]
        while True:
            tok = self.cursor.current()
            # Bare '|' is or; '||' is also or via multi-char; avoid matching
            # points-to residual.
            if tok.lexeme in _OR_OPS or tok.lexeme == "||":
                # Do not treat a lone '|' that is part of a mis-lexed stream
                # as or when followed by '->' — points-to is multi-char.
                self.cursor.advance()
                nodes.append(self._parse_and())
            else:
                break
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        return LogicNode(
            node_id=self._nid("or"),
            kind=NodeKind.OR,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )

    def _parse_and(self) -> LogicNode:
        nodes = [self._parse_wand()]
        while self.cursor.match_any(_AND_OPS) is not None:
            nodes.append(self._parse_wand())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        return LogicNode(
            node_id=self._nid("and"),
            kind=NodeKind.AND,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )

    def _parse_wand(self) -> LogicNode:
        left = self._parse_sep()
        if self.cursor.match_any(_WAND_OPS) is not None:
            if not self.profile.admit_wand:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message="magic wand is not admitted by the active profile",
                        range=self.cursor.current().range,
                        remediation="Enable admit_wand or remove -*",
                    )
                )
            # Right-associative separating implication.
            right = self._parse_wand()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            return self._mk_spatial(
                "wand",
                children=(left, right),
                span=span,
                payload_schema=RESOURCE_WAND_PAYLOAD_SCHEMA,
                features=("resource.wand",),
            )
        return left

    def _parse_sep(self) -> LogicNode:
        nodes = [self._parse_unary()]
        while self.cursor.match_any(_SEP_OPS) is not None:
            nodes.append(self._parse_unary())
        if len(nodes) == 1:
            return nodes[0]
        # Nest left-associatively as binary sep_conj extensions.
        left = nodes[0]
        for right in nodes[1:]:
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = self._mk_spatial(
                "sep_conj",
                children=(left, right),
                span=span,
                payload_schema=RESOURCE_SEP_CONJ_PAYLOAD_SCHEMA,
                features=("resource.sep_conj",),
            )
        return left

    def _parse_unary(self) -> LogicNode:
        not_tok = self.cursor.match_any(_NOT_OPS)
        if not_tok is not None:
            self._enter()
            try:
                inner = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(
                not_tok.range, inner.range or not_tok.range
            )
            return LogicNode(
                node_id=self._nid("not"),
                kind=NodeKind.NOT,
                sort=BOOL_SORT,
                arguments=(inner,),
                range=span,
            )
        return self._parse_atomic()

    def _parse_atomic(self) -> LogicNode:
        open_tok = self.cursor.match_lexeme("(")
        if open_tok is not None:
            inner = self._parse_formula()
            close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(open_tok.range, close.range)
            return LogicNode(
                node_id=inner.node_id,
                kind=inner.kind,
                sort=inner.sort,
                symbol=inner.symbol,
                arguments=inner.arguments,
                binders=inner.binders,
                extension=inner.extension,
                range=span,
                metadata=dict(inner.metadata),
            )

        token = self.cursor.match_any(_TRUE_OPS)
        if token is not None:
            return LogicNode(
                node_id=self._nid("true"),
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=token.range,
            )
        token = self.cursor.match_any(_FALSE_OPS)
        if token is not None:
            return LogicNode(
                node_id=self._nid("false"),
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=token.range,
            )

        current = self.cursor.current()
        folded = current.lexeme.casefold()

        if folded == "emp":
            self.cursor.advance()
            return self._mk_spatial(
                "emp",
                children=(),
                span=current.range,
                payload_schema=RESOURCE_EMP_PAYLOAD_SCHEMA,
                features=("resource.emp",),
            )

        if folded == "pure":
            return self._parse_pure()

        if folded == "points_to":
            return self._parse_points_to_call()

        if folded == "owns":
            return self._parse_owns()

        # Term-leading forms: IDENT |-> TERM or pure atom IDENT.
        if current.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.NUMBER.value,
        }:
            return self._parse_term_leading(current)

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def _parse_term_leading(self, current: LogicToken) -> LogicNode:
        left = self._parse_term()
        if self.cursor.match_any(_POINTS_TO_OPS) is not None:
            right = self._parse_term()
            perm = self._optional_permission()
            span = self.cursor.range_span(
                left.range or current.range,
                right.range or current.range,
            )
            return self._mk_points_to(left, right, perm, span)
        # Pure atom — free variables allowed only as pure symbols (not ownership).
        name = left.symbol or left.metadata.get("term") or current.lexeme
        return self._mk_atom(str(name), left.range or current.range)

    def _parse_term(self) -> LogicNode:
        current = self.cursor.current()
        if current.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.NUMBER.value,
        }:
            self.cursor.advance()
            is_number = current.kind == TokenKind.NUMBER.value
            # Symbol names must match the AST identifier grammar; numeric
            # literals are stored under metadata["term"] with a lit_ prefix.
            symbol = current.lexeme if not is_number else f"lit_{current.lexeme}"
            return LogicNode(
                node_id=self._nid("term"),
                kind=NodeKind.CONSTANT if is_number else NodeKind.VARIABLE,
                sort=HEAP_LOC_SORT,
                symbol=symbol,
                range=current.range,
                metadata={"numeric": is_number, "term": current.lexeme},
            )
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected term; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def _optional_permission(self) -> dict[str, Any] | None:
        if self.cursor.match_lexeme("@") is None:
            return None
        return self._parse_permission()

    def _parse_permission(self) -> dict[str, Any]:
        token = self.cursor.current()
        folded = token.lexeme.casefold()
        if folded == "full":
            self.cursor.advance()
            return {"numerator": 1, "denominator": 1, "label": "full"}
        if folded == "half":
            self.cursor.advance()
            return {"numerator": 1, "denominator": 2, "label": "half"}
        if folded == "none":
            self.cursor.advance()
            return {"numerator": 0, "denominator": 1, "label": "none"}
        if token.kind != TokenKind.NUMBER.value:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_PERMISSION,
                    message=f"expected permission amount; got {token.lexeme!r}",
                    range=token.range,
                )
            )
        self.cursor.advance()
        try:
            numerator = int(token.lexeme)
        except ValueError as error:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_PERMISSION,
                    message=f"invalid permission numerator {token.lexeme!r}",
                    range=token.range,
                )
            ) from error
        denominator = 1
        if self.cursor.match_lexeme("/") is not None:
            den_tok = self.cursor.current()
            if den_tok.kind != TokenKind.NUMBER.value:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_PERMISSION,
                        message="permission denominator must be a number",
                        range=den_tok.range,
                    )
                )
            self.cursor.advance()
            try:
                denominator = int(den_tok.lexeme)
            except ValueError as error:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_PERMISSION,
                        message=f"invalid permission denominator {den_tok.lexeme!r}",
                        range=den_tok.range,
                    )
                ) from error
        if denominator <= 0 or numerator < 0 or numerator > denominator:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_PERMISSION,
                    message=(
                        f"permission {numerator}/{denominator} is outside [0, 1]"
                    ),
                    range=token.range,
                )
            )
        if (
            not self.profile.admit_fractional_permissions
            and not (numerator == denominator or numerator == 0)
        ):
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=(
                        "fractional permissions are not admitted by the "
                        "active classical profile"
                    ),
                    range=token.range,
                    remediation="Use full/none or a fractional profile",
                )
            )
        return {
            "numerator": numerator,
            "denominator": denominator,
            "label": f"{numerator}/{denominator}",
        }

    def _parse_points_to_call(self) -> LogicNode:
        start = self.cursor.advance()  # points_to
        self.cursor.expect_lexeme("(")
        loc = self._parse_term()
        self.cursor.expect_lexeme(",")
        val = self._parse_term()
        perm: dict[str, Any] | None = None
        if self.cursor.match_lexeme(",") is not None:
            perm = self._parse_permission()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        return self._mk_points_to(loc, val, perm, span)

    def _parse_owns(self) -> LogicNode:
        if not self.profile.admit_ownership:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="ownership atoms are not admitted by the active profile",
                    range=self.cursor.current().range,
                )
            )
        start = self.cursor.advance()  # owns
        self.cursor.expect_lexeme("(")
        principal = self.cursor.expect_ident()
        # Ownership principal must be bound for capture-safety when quantified.
        # Free principals are allowed as constants but recorded.
        self.cursor.expect_lexeme(",")
        location = self.cursor.expect_ident()
        if (
            location.lexeme not in self._scope
            and principal.lexeme not in self._scope
        ):
            # Free owns is allowed as a pure assertion about named constants,
            # but if either side is meant as a bound resource it must be scoped.
            pass
        perm: dict[str, Any] | None = None
        if self.cursor.match_lexeme(",") is not None:
            perm = self._parse_permission()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        payload: dict[str, Any] = {
            "kind": "owns",
            "location": location.lexeme,
            "permission": perm
            or {"numerator": 1, "denominator": 1, "label": "full"},
            "principal": principal.lexeme,
            "profile_id": self.profile.profile_id,
            "schema_version": RESOURCE_OWNS_PAYLOAD_SCHEMA,
            "scope": list(self._scope),
        }
        return mk_extension(
            self._nid("owns"),
            family=RESOURCE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("resource.owns", "resource.ownership"),
            payload_schema=RESOURCE_OWNS_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_pure(self) -> LogicNode:
        start = self.cursor.advance()  # pure
        self.cursor.expect_lexeme("(")
        inner = self._parse_formula()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "kind": "pure",
            "profile_id": self.profile.profile_id,
            "schema_version": RESOURCE_PURE_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("pure"),
            family=RESOURCE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("resource.pure",),
            payload_schema=RESOURCE_PURE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(inner,),
            range=span,
        )

    def _mk_points_to(
        self,
        loc: LogicNode,
        val: LogicNode,
        perm: dict[str, Any] | None,
        span: SourceRange,
    ) -> LogicNode:
        loc_name = str(loc.metadata.get("term") or loc.symbol or "")
        val_name = str(val.metadata.get("term") or val.symbol or "")
        permission = perm or {
            "numerator": 1,
            "denominator": 1,
            "label": "full",
        }
        payload = {
            "kind": "points_to",
            "location": loc_name,
            "permission": permission,
            "profile_id": self.profile.profile_id,
            "schema_version": RESOURCE_POINTS_TO_PAYLOAD_SCHEMA,
            "value": val_name,
        }
        return mk_extension(
            self._nid("points_to"),
            family=RESOURCE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("resource.points_to", "resource.heap"),
            payload_schema=RESOURCE_POINTS_TO_PAYLOAD_SCHEMA,
            payload=payload,
            children=(loc, val),
            range=span,
        )

    def _mk_atom(self, name: str, span: SourceRange) -> LogicNode:
        payload = {
            "kind": "atom",
            "name": name,
            "profile_id": self.profile.profile_id,
            "schema_version": RESOURCE_ATOM_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("atom"),
            family=RESOURCE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("resource.atom",),
            payload_schema=RESOURCE_ATOM_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _mk_spatial(
        self,
        kind: str,
        *,
        children: Sequence[LogicNode],
        span: SourceRange,
        payload_schema: str,
        features: Sequence[str],
    ) -> LogicNode:
        payload = {
            "kind": kind,
            "profile_id": self.profile.profile_id,
            "schema_version": payload_schema,
        }
        return mk_extension(
            self._nid(kind),
            family=RESOURCE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=tuple(features),
            payload_schema=payload_schema,
            payload=payload,
            children=tuple(children),
            range=span,
        )


# ---------------------------------------------------------------------------
# Session / process parser engine
# ---------------------------------------------------------------------------


class _SessionParserEngine:
    """Parser for session types, rely-guarantee, and happens-before atoms."""

    def __init__(
        self,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: SessionProcessProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, limits=limits)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._channel_scope: list[str] = []
        self._bound_names: list[str] = []

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"{self.expression_id}:{prefix}:{self._counter}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if not self.document.text.strip():
            return None, (
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty session/process input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_top()
            if self.cursor.current().kind != TokenKind.EOF.value:
                tok = self.cursor.current()
                # Reject unsupported process operators explicitly.
                if tok.lexeme.casefold() in UNSUPPORTED_PROCESS_OPERATORS:
                    raise _ParseFail(
                        _diag(
                            code=CODE_UNSUPPORTED_PROCESS,
                            message=(
                                f"unsupported process operator {tok.lexeme!r}; "
                                "lower only with explicit loss and bounds"
                            ),
                            range=tok.range,
                            remediation=(
                                "Use controlled session constructs "
                                "(!label, ?label, end, tau, dual, rely/guarantee, hb)"
                            ),
                            metadata={
                                "operator": tok.lexeme.casefold(),
                                "unsupported": sorted(
                                    UNSUPPORTED_PROCESS_OPERATORS
                                ),
                            },
                        )
                    )
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                    )
                )
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_top(self) -> LogicNode:
        self._enter()
        try:
            current = self.cursor.current()
            folded = current.lexeme.casefold()
            if folded in UNSUPPORTED_PROCESS_OPERATORS:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_PROCESS,
                        message=(
                            f"unsupported process operator {current.lexeme!r}; "
                            "lower only with explicit loss and bounds"
                        ),
                        range=current.range,
                        metadata={
                            "operator": folded,
                            "unsupported": sorted(UNSUPPORTED_PROCESS_OPERATORS),
                        },
                    )
                )
            if folded == "rely":
                return self._parse_rely_guarantee()
            if folded == "hb":
                return self._parse_happens_before()
            if folded == "atomic":
                return self._parse_atomic()
            if folded == "channel":
                return self._parse_channel()
            return self._parse_session()
        finally:
            self._leave()

    def _parse_session(self) -> LogicNode:
        current = self.cursor.current()
        folded = current.lexeme.casefold()

        if folded == "end":
            self.cursor.advance()
            payload = {
                "kind": "end",
                "polarity": SessionPolarity.END.value,
                "profile_id": self.profile.profile_id,
                "schema_version": SESSION_END_PAYLOAD_SCHEMA,
            }
            return mk_extension(
                self._nid("end"),
                family=SESSION_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("session.end",),
                payload_schema=SESSION_END_PAYLOAD_SCHEMA,
                payload=payload,
                children=(),
                range=current.range,
            )

        if folded == "dual":
            return self._parse_dual()

        if folded == "tau":
            start = self.cursor.advance()
            self.cursor.expect_lexeme(".")
            cont = self._parse_session()
            span = self.cursor.range_span(
                start.range, cont.range or start.range
            )
            payload = {
                "kind": "internal",
                "label": "tau",
                "polarity": SessionPolarity.INTERNAL.value,
                "profile_id": self.profile.profile_id,
                "schema_version": SESSION_ACTION_PAYLOAD_SCHEMA,
            }
            return mk_extension(
                self._nid("tau"),
                family=SESSION_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("session.internal",),
                payload_schema=SESSION_ACTION_PAYLOAD_SCHEMA,
                payload=payload,
                children=(cont,),
                range=span,
            )

        # Send: !label(Sort).cont
        if current.lexeme == "!":
            return self._parse_polarity_action(SessionPolarity.SEND, "!")
        # Receive: ?label(Sort).cont
        if current.lexeme == "?":
            return self._parse_polarity_action(SessionPolarity.RECEIVE, "?")

        # Named protocol reference.
        if current.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            name = current.lexeme
            # Capture-safe: named channel endpoints must be bound if required.
            self.cursor.advance()
            if name in self._channel_scope or name in self._bound_names:
                pass
            payload = {
                "kind": "protocol_ref",
                "name": name,
                "profile_id": self.profile.profile_id,
                "schema_version": SESSION_REF_PAYLOAD_SCHEMA,
            }
            return mk_extension(
                self._nid("ref"),
                family=SESSION_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("session.protocol_ref",),
                payload_schema=SESSION_REF_PAYLOAD_SCHEMA,
                payload=payload,
                children=(),
                range=current.range,
            )

        if folded in UNSUPPORTED_PROCESS_OPERATORS:
            raise _ParseFail(
                _diag(
                    code=CODE_UNSUPPORTED_PROCESS,
                    message=(
                        f"unsupported process operator {current.lexeme!r}; "
                        "lower only with explicit loss and bounds"
                    ),
                    range=current.range,
                    metadata={"operator": folded},
                )
            )

        raise _ParseFail(
            _diag(
                code=CODE_INVALID_SESSION,
                message=f"expected session process; got {current.lexeme!r}",
                range=current.range,
                remediation="Write !label(T).end, ?label(T).end, dual(...), or end",
            )
        )

    def _parse_polarity_action(
        self, polarity: SessionPolarity, surface: str
    ) -> LogicNode:
        start = self.cursor.advance()  # ! or ?
        label_tok = self.cursor.expect_ident()
        self.cursor.expect_lexeme("(")
        sort_tok = self.cursor.expect_ident()
        self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        self.cursor.expect_lexeme(".")
        # Bind payload channel label into scope for capture tracking.
        self._bound_names.append(label_tok.lexeme)
        try:
            cont = self._parse_session()
        finally:
            self._bound_names.pop()
        span = self.cursor.range_span(start.range, cont.range or start.range)
        payload = {
            "kind": "session_action",
            "label": label_tok.lexeme,
            "payload_sort": sort_tok.lexeme,
            "polarity": polarity.value,
            "profile_id": self.profile.profile_id,
            "schema_version": SESSION_ACTION_PAYLOAD_SCHEMA,
            "surface": surface,
        }
        return mk_extension(
            self._nid(polarity.value),
            family=SESSION_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"session.{polarity.value}", "session.action"),
            payload_schema=SESSION_ACTION_PAYLOAD_SCHEMA,
            payload=payload,
            children=(cont,),
            range=span,
        )

    def _parse_dual(self) -> LogicNode:
        if not self.profile.admit_duality:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="session duality is not admitted by the active profile",
                    range=self.cursor.current().range,
                )
            )
        start = self.cursor.advance()  # dual
        self.cursor.expect_lexeme("(")
        inner = self._parse_session()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        # Structural duality is validated at lower time; surface dual is typed.
        payload = {
            "kind": "dual",
            "profile_id": self.profile.profile_id,
            "schema_version": SESSION_DUAL_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("dual"),
            family=SESSION_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("session.dual", "session.duality"),
            payload_schema=SESSION_DUAL_PAYLOAD_SCHEMA,
            payload=payload,
            children=(inner,),
            range=span,
        )

    def _parse_rely_guarantee(self) -> LogicNode:
        if not self.profile.admit_rely_guarantee:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="rely-guarantee is not admitted by the active profile",
                    range=self.cursor.current().range,
                )
            )
        start = self.cursor.advance()  # rely
        # Rely/guarantee statements are pure identifiers or parenthesized atoms.
        rely = self._parse_statement_atom()
        if self.cursor.current().lexeme.casefold() != "guarantee":
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message="expected 'guarantee' after rely statement",
                    range=self.cursor.current().range,
                )
            )
        self.cursor.advance()
        guarantee = self._parse_statement_atom()
        if self.cursor.current().lexeme.casefold() != "for":
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message="expected 'for' <component> after guarantee",
                    range=self.cursor.current().range,
                )
            )
        self.cursor.advance()
        component = self.cursor.expect_ident()
        span = self.cursor.range_span(start.range, component.range)
        payload = {
            "component": component.lexeme,
            "guarantee": guarantee,
            "kind": "rely_guarantee",
            "profile_id": self.profile.profile_id,
            "rely": rely,
            "schema_version": SESSION_RELY_GUARANTEE_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("rg"),
            family=CONCURRENCY_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("concurrency.rely_guarantee",),
            payload_schema=SESSION_RELY_GUARANTEE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_statement_atom(self) -> str:
        """Parse a rely/guarantee statement as an identifier or parenthesized name."""

        if self.cursor.match_lexeme("(") is not None:
            parts: list[str] = []
            while self.cursor.current().lexeme != ")":
                if self.cursor.current().kind == TokenKind.EOF.value:
                    raise _ParseFail(
                        _diag(
                            code=CODE_UNBALANCED,
                            message="unbalanced parenthesis in rely/guarantee",
                            range=self.cursor.current().range,
                        )
                    )
                parts.append(self.cursor.advance().lexeme)
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            text = " ".join(parts).strip()
            if not text:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message="empty rely/guarantee statement",
                        range=self.cursor.current().range,
                    )
                )
            return text
        return self.cursor.expect_ident().lexeme

    def _parse_happens_before(self) -> LogicNode:
        if not self.profile.admit_happens_before:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="happens-before is not admitted by the active profile",
                    range=self.cursor.current().range,
                )
            )
        start = self.cursor.advance()  # hb
        self.cursor.expect_lexeme("(")
        left = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        right = self.cursor.expect_ident()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "kind": "happens_before",
            "left": left.lexeme,
            "profile_id": self.profile.profile_id,
            "right": right.lexeme,
            "schema_version": SESSION_HB_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("hb"),
            family=CONCURRENCY_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("concurrency.happens_before",),
            payload_schema=SESSION_HB_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_atomic(self) -> LogicNode:
        start = self.cursor.advance()  # atomic
        self.cursor.expect_lexeme("(")
        body_name = self.cursor.expect_ident().lexeme
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "body": body_name,
            "kind": "atomic",
            "profile_id": self.profile.profile_id,
            "schema_version": SESSION_ATOMIC_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("atomic"),
            family=CONCURRENCY_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("concurrency.atomic",),
            payload_schema=SESSION_ATOMIC_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_channel(self) -> LogicNode:
        start = self.cursor.advance()  # channel
        name_tok = self.cursor.expect_ident()
        # Bind channel name for capture-safe subsequent references.
        if name_tok.lexeme in self._channel_scope:
            raise _ParseFail(
                _diag(
                    code=CODE_CHANNEL_CAPTURE,
                    message=(
                        f"channel {name_tok.lexeme!r} is already bound "
                        f"(rebinding is capture-unsafe); "
                        f"scope={list(self._channel_scope)!r}"
                    ),
                    range=name_tok.range,
                    metadata={
                        "channel": name_tok.lexeme,
                        "scope": list(self._channel_scope),
                    },
                )
            )
        self._channel_scope.append(name_tok.lexeme)
        mode = ChannelMode.SYNCHRONOUS.value
        if self.cursor.match_lexeme(":") is not None:
            mode_tok = self.cursor.expect_ident()
            mode = mode_tok.lexeme.casefold()
            if mode not in {item.value for item in ChannelMode}:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_SESSION,
                        message=f"unknown channel mode {mode_tok.lexeme!r}",
                        range=mode_tok.range,
                    )
                )
        endpoints: list[str] = []
        if self.cursor.current().lexeme.casefold() == "between":
            self.cursor.advance()
            endpoints.append(self.cursor.expect_ident().lexeme)
            self.cursor.expect_lexeme(",")
            endpoints.append(self.cursor.expect_ident().lexeme)
        if len(endpoints) < 2:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_SESSION,
                    message="channel requires 'between A, B' endpoints",
                    range=name_tok.range,
                )
            )
        span = self.cursor.range_span(start.range, name_tok.range)
        payload = {
            "endpoints": endpoints,
            "kind": "channel",
            "mode": mode,
            "name": name_tok.lexeme,
            "profile_id": self.profile.profile_id,
            "schema_version": SESSION_CHANNEL_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("channel"),
            family=SESSION_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("session.channel",),
            payload_schema=SESSION_CHANNEL_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )


# ---------------------------------------------------------------------------
# Refinement parser engine
# ---------------------------------------------------------------------------


class _RefinementParserEngine:
    """Parser for two-state relational / simulation / obligation syntax."""

    def __init__(
        self,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: RefinementSyntaxProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, limits=limits)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._state_scope: list[str] = []

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"{self.expression_id}:{prefix}:{self._counter}"

    def _enter(self) -> None:
        self.cursor.depth += 1
        if self.cursor.depth > self.limits.max_depth:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"parse depth {self.cursor.depth} exceeds limit "
                        f"{self.limits.max_depth}"
                    ),
                    range=self.cursor.current().range,
                )
            )

    def _leave(self) -> None:
        self.cursor.depth = max(0, self.cursor.depth - 1)

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if not self.document.text.strip():
            return None, (
                _diag(
                    code=CODE_EMPTY_INPUT,
                    message="empty refinement input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_refinement()
            if self.cursor.current().kind != TokenKind.EOF.value:
                tok = self.cursor.current()
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                    )
                )
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_refinement(self) -> LogicNode:
        self._enter()
        try:
            current = self.cursor.current()
            folded = current.lexeme.casefold()
            if folded in {"forall_states", "exists_states"}:
                return self._parse_two_state()
            if folded in {
                "forward_sim",
                "backward_sim",
                "simulates",
            }:
                return self._parse_simulation()
            if folded == "refines":
                return self._parse_obligation()
            # Relational atom: related(a, c) or bare state var under scope.
            if folded == "related":
                return self._parse_related()
            if current.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                return self._parse_state_var_or_related()
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_REFINEMENT,
                    message=f"expected refinement formula; got {current.lexeme!r}",
                    range=current.range,
                    remediation=(
                        "Write forall_states a, c. related(a, c), "
                        "forward_sim(A, C), or refines(C, A, simulation)"
                    ),
                )
            )
        finally:
            self._leave()

    def _parse_two_state(self) -> LogicNode:
        start = self.cursor.advance()
        quant = (
            "forall"
            if start.lexeme.casefold() == "forall_states"
            else "exists"
        )
        abstract_tok = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        concrete_tok = self.cursor.expect_ident()
        if abstract_tok.lexeme == concrete_tok.lexeme:
            raise _ParseFail(
                _diag(
                    code=CODE_TWO_STATE_CAPTURE,
                    message=(
                        "two-state binders must be distinct "
                        f"(got {abstract_tok.lexeme!r} twice)"
                    ),
                    range=concrete_tok.range,
                )
            )
        for name, tok in (
            (abstract_tok.lexeme, abstract_tok),
            (concrete_tok.lexeme, concrete_tok),
        ):
            if name in self._state_scope:
                raise _ParseFail(
                    _diag(
                        code=CODE_TWO_STATE_CAPTURE,
                        message=(
                            f"state variable {name!r} is already bound "
                            f"(rebinding is capture-unsafe); "
                            f"scope={list(self._state_scope)!r}"
                        ),
                        range=tok.range,
                        metadata={
                            "variable": name,
                            "scope": list(self._state_scope),
                        },
                    )
                )
        self.cursor.expect_lexeme(".")
        self._state_scope.extend(
            [abstract_tok.lexeme, concrete_tok.lexeme]
        )
        try:
            body = self._parse_refinement()
        finally:
            self._state_scope.pop()
            self._state_scope.pop()
        span = self.cursor.range_span(
            start.range, body.range or concrete_tok.range
        )
        # Capture-safe: wrap with core binders of State sort (abstract outer).
        abs_binder = Binder(name=abstract_tok.lexeme, sort=STATE_SORT)
        conc_binder = Binder(name=concrete_tok.lexeme, sort=STATE_SORT)
        if quant == "forall":
            inner = mk_forall(self._nid("forall_c"), (conc_binder,), body)
            built = mk_forall(self._nid("forall_a"), (abs_binder,), inner)
        else:
            inner = mk_exists(self._nid("exists_c"), (conc_binder,), body)
            built = mk_exists(self._nid("exists_a"), (abs_binder,), inner)
        return LogicNode(
            node_id=built.node_id,
            kind=built.kind,
            sort=BOOL_SORT,
            binders=built.binders,
            arguments=built.arguments,
            range=span,
            metadata={
                "abstract_state": abstract_tok.lexeme,
                "concrete_state": concrete_tok.lexeme,
                "profile_id": self.profile.profile_id,
                "refinement_two_state": True,
                "schema_version": REFINEMENT_TWO_STATE_PAYLOAD_SCHEMA,
                "two_state_quantifier": quant,
            },
        )

    def _require_bound_state(self, name: str, span: SourceRange) -> None:
        if not self.profile.require_two_state_capture_safety:
            return
        if name not in self._state_scope:
            raise _ParseFail(
                _diag(
                    code=CODE_TWO_STATE_CAPTURE,
                    message=(
                        f"state variable {name!r} is free or out of scope; "
                        f"bound variables are {list(self._state_scope)!r}"
                    ),
                    range=span,
                    remediation=(
                        "Bind abstract and concrete states with "
                        "forall_states a, c. ..."
                    ),
                    metadata={
                        "variable": name,
                        "bound": list(self._state_scope),
                    },
                )
            )

    def _parse_related(self) -> LogicNode:
        start = self.cursor.advance()  # related
        self.cursor.expect_lexeme("(")
        left = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        right = self.cursor.expect_ident()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        self._require_bound_state(left.lexeme, left.range)
        self._require_bound_state(right.lexeme, right.range)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "abstract_state": left.lexeme,
            "concrete_state": right.lexeme,
            "kind": "related",
            "profile_id": self.profile.profile_id,
            "schema_version": REFINEMENT_TWO_STATE_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("related"),
            family=REFINEMENT_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("refinement.related", "refinement.two_state"),
            payload_schema=REFINEMENT_TWO_STATE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_state_var_or_related(self) -> LogicNode:
        current = self.cursor.current()
        name = current.lexeme
        self.cursor.advance()
        # Allow bare related(a,c) already handled; bare names under scope.
        self._require_bound_state(name, current.range)
        payload = {
            "kind": "state_var",
            "name": name,
            "profile_id": self.profile.profile_id,
            "schema_version": REFINEMENT_STATE_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("state"),
            family=REFINEMENT_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("refinement.state_var",),
            payload_schema=REFINEMENT_STATE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=current.range,
        )

    def _parse_simulation(self) -> LogicNode:
        start = self.cursor.advance()
        folded = start.lexeme.casefold()
        if folded == "forward_sim":
            direction = SimulationDirection.FORWARD.value
        elif folded == "backward_sim":
            direction = SimulationDirection.BACKWARD.value
        else:
            direction = SimulationDirection.FORWARD.value
        if (
            direction == SimulationDirection.FORWARD.value
            and not self.profile.admit_forward_simulation
        ):
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="forward simulation is not admitted by the profile",
                    range=start.range,
                )
            )
        if (
            direction == SimulationDirection.BACKWARD.value
            and not self.profile.admit_backward_simulation
        ):
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message="backward simulation is not admitted by the profile",
                    range=start.range,
                )
            )
        self.cursor.expect_lexeme("(")
        abstract = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        concrete = self.cursor.expect_ident()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "abstract_system": abstract.lexeme,
            "concrete_system": concrete.lexeme,
            "direction": direction,
            "kind": "simulation",
            "profile_id": self.profile.profile_id,
            "schema_version": REFINEMENT_SIM_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("sim"),
            family=REFINEMENT_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("refinement.simulation", f"refinement.{direction}"),
            payload_schema=REFINEMENT_SIM_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_obligation(self) -> LogicNode:
        start = self.cursor.advance()  # refines
        self.cursor.expect_lexeme("(")
        concrete = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        abstract = self.cursor.expect_ident()
        kind = RefinementKind.SIMULATION.value
        if self.cursor.match_lexeme(",") is not None:
            kind_tok = self.cursor.expect_ident()
            kind = kind_tok.lexeme.casefold()
            allowed = {item.value for item in RefinementKind}
            if kind not in allowed:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_REFINEMENT,
                        message=(
                            f"unknown refinement kind {kind_tok.lexeme!r}; "
                            f"expected one of {sorted(allowed)}"
                        ),
                        range=kind_tok.range,
                    )
                )
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "abstract_system": abstract.lexeme,
            "concrete_system": concrete.lexeme,
            "kind": "obligation",
            "profile_id": self.profile.profile_id,
            "refinement_kind": kind,
            "schema_version": REFINEMENT_OBLIGATION_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("obligation"),
            family=REFINEMENT_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("refinement.obligation", f"refinement.kind.{kind}"),
            payload_schema=REFINEMENT_OBLIGATION_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )


# ---------------------------------------------------------------------------
# Free-variable / capture analysis
# ---------------------------------------------------------------------------


def free_resource_variables(node: LogicNode) -> frozenset[str]:
    """Compute free ownership/heap variables under capture-safe scoping."""

    def walk(n: LogicNode, bound: frozenset[str]) -> set[str]:
        free: set[str] = set()
        if n.kind in {NodeKind.FORALL, NodeKind.EXISTS} and n.binders and n.arguments:
            inner = bound | {b.name for b in n.binders}
            free |= walk(n.arguments[0], inner)
            return free
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            kind = payload.get("kind")
            if kind == "points_to":
                for key in ("location", "value"):
                    var = str(payload.get(key) or "")
                    if var and var not in bound and not var.isdigit():
                        free.add(var)
                return free
            if kind == "owns":
                for key in ("principal", "location"):
                    var = str(payload.get(key) or "")
                    if var and var not in bound:
                        free.add(var)
                return free
            if kind == "atom":
                # Pure atoms are not capture-sensitive ownership vars.
                return free
            for child in n.extension.children:
                free |= walk(child, bound)
            return free
        if n.kind is NodeKind.VARIABLE and n.symbol:
            if n.symbol not in bound and not str(n.symbol).isdigit():
                free.add(n.symbol)
        for child in n.arguments:
            free |= walk(child, bound)
        return free

    return frozenset(walk(node, frozenset()))


def free_session_channels(node: LogicNode) -> frozenset[str]:
    """Free channel names referenced under session capture-safe scoping."""

    def walk(n: LogicNode, bound: frozenset[str]) -> set[str]:
        free: set[str] = set()
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            kind = payload.get("kind")
            if kind == "channel":
                name = str(payload.get("name") or "")
                # Declaration binds; endpoints are free component names.
                return free
            if kind == "protocol_ref":
                name = str(payload.get("name") or "")
                if name and name not in bound:
                    free.add(name)
                return free
            for child in n.extension.children:
                free |= walk(child, bound)
            return free
        for child in n.arguments:
            free |= walk(child, bound)
        return free

    return frozenset(walk(node, frozenset()))


def free_state_variables(node: LogicNode) -> frozenset[str]:
    """Free two-state variables under capture-safe scoping."""

    def walk(n: LogicNode, bound: frozenset[str]) -> set[str]:
        free: set[str] = set()
        if n.kind in {NodeKind.FORALL, NodeKind.EXISTS} and n.binders and n.arguments:
            inner = bound | {b.name for b in n.binders}
            free |= walk(n.arguments[0], inner)
            return free
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            kind = payload.get("kind")
            if kind == "related":
                for key in ("abstract_state", "concrete_state"):
                    var = str(payload.get(key) or "")
                    if var and var not in bound:
                        free.add(var)
                return free
            if kind == "state_var":
                var = str(payload.get("name") or "")
                if var and var not in bound:
                    free.add(var)
                return free
            for child in n.extension.children:
                free |= walk(child, bound)
            return free
        for child in n.arguments:
            free |= walk(child, bound)
        return free

    return frozenset(walk(node, frozenset()))


def dualize_session_node(node: LogicNode) -> LogicNode:
    """Structurally dualize a session AST (send↔receive; dual cancels)."""

    if node.kind is not NodeKind.EXTENSION or node.extension is None:
        return node
    payload = dict(node.extension.payload)
    kind = payload.get("kind")
    children = tuple(dualize_session_node(c) for c in node.extension.children)

    if kind == "dual":
        # Syntactic dual is an involution: dualize(dual(P)) = P.
        # To expand dual(P) into the dualized process, call dualize on P once.
        if not children:
            return node
        return children[0]

    if kind == "session_action":
        polarity = str(payload.get("polarity") or "")
        new_polarity = dual_polarity(polarity).value
        surface = "!" if new_polarity == SessionPolarity.SEND.value else "?"
        if new_polarity == SessionPolarity.INTERNAL.value:
            surface = "tau"
        new_payload = {
            **payload,
            "polarity": new_polarity,
            "surface": surface,
        }
        return mk_extension(
            f"{node.node_id}:dual",
            family=SESSION_FAMILY_ID,
            profile=str(payload.get("profile_id") or "session"),
            features=tuple(node.extension.features),
            payload_schema=node.extension.payload_schema,
            payload=new_payload,
            children=children,
            range=node.range,
        )

    if kind == "end":
        return node

    if kind == "internal":
        return mk_extension(
            f"{node.node_id}:dual",
            family=SESSION_FAMILY_ID,
            profile=str(payload.get("profile_id") or "session"),
            features=tuple(node.extension.features),
            payload_schema=node.extension.payload_schema,
            payload=dict(payload),
            children=children,
            range=node.range,
        )

    return mk_extension(
        f"{node.node_id}:dual",
        family=SESSION_FAMILY_ID,
        profile=str(payload.get("profile_id") or "session"),
        features=tuple(node.extension.features),
        payload_schema=node.extension.payload_schema,
        payload=dict(payload),
        children=children,
        range=node.range,
    )


def session_actions_from_node(
    node: LogicNode, *, prefix: str = "sess"
) -> tuple[SessionAction, ...]:
    """Extract a linear session-action spine from a session AST."""

    actions: list[SessionAction] = []
    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"{prefix}:a{counter[0]}"

    def walk(n: LogicNode) -> str:
        if n.kind is not NodeKind.EXTENSION or n.extension is None:
            raise ResourceParseError(
                "session action extraction requires extension nodes",
                code=CODE_INVALID_SESSION,
            )
        payload = dict(n.extension.payload)
        kind = payload.get("kind")
        if kind == "dual":
            # Expand dual(P) as dualize(P) for action extraction.
            if not n.extension.children:
                raise ResourceParseError(
                    "dual requires a session body",
                    code=CODE_INVALID_SESSION,
                )
            return walk(dualize_session_node(n.extension.children[0]))
        if kind == "end":
            action_id = next_id()
            actions.append(
                SessionAction(
                    action_id=action_id,
                    polarity=SessionPolarity.END,
                    label="end",
                )
            )
            return action_id
        if kind in {"session_action", "internal"}:
            action_id = next_id()
            polarity = SessionPolarity(str(payload.get("polarity")))
            label = str(payload.get("label") or polarity.value)
            payload_sort = str(payload.get("payload_sort") or "")
            cont_ids: tuple[str, ...] = ()
            if n.extension.children:
                cont_ids = (walk(n.extension.children[0]),)
            actions.append(
                SessionAction(
                    action_id=action_id,
                    polarity=polarity,
                    label=label,
                    payload_sort=payload_sort,
                    continuation_action_ids=cont_ids,
                )
            )
            return action_id
        raise ResourceParseError(
            f"cannot extract session actions from kind {kind!r}",
            code=CODE_INVALID_SESSION,
        )

    walk(node)
    return tuple(actions)


# ---------------------------------------------------------------------------
# Printers
# ---------------------------------------------------------------------------


class ResourcePrinter:
    """Deterministic printer for separation-logic formulas."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        if style not in {PrintStyle.ASCII, PrintStyle.UNICODE}:
            raise SyntaxContractError(
                f"print style must be 'ascii' or 'unicode'; got {style!r}"
            )
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            return self._print_node(node.root, _Prec.BOTTOM)
        if not isinstance(node, LogicNode):
            raise SyntaxContractError(
                "print requires a LogicNode or TypedExpression"
            )
        return self._print_node(node, _Prec.BOTTOM)

    def _op(self, ascii_form: str, unicode_form: str) -> str:
        return unicode_form if self.style == PrintStyle.UNICODE else ascii_form

    def _print_node(self, node: LogicNode, parent_prec: int) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return self._op("true", "⊤")
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return self._op("false", "⊥")
        if kind is NodeKind.NOT or kind == NodeKind.NOT.value:
            inner = self._print_node(node.arguments[0], _Prec.UNARY)
            text = f"{self._op('not', '¬')} {inner}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            op = f" {self._op('and', '∧')} "
            text = op.join(
                self._print_node(a, _Prec.AND) for a in node.arguments
            )
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            op = f" {self._op('or', '∨')} "
            text = op.join(
                self._print_node(a, _Prec.OR) for a in node.arguments
            )
            return self._paren(text, _Prec.OR, parent_prec)
        if kind is NodeKind.IMPLIES or kind == NodeKind.IMPLIES.value:
            left = self._print_node(node.arguments[0], _Prec.IMPLIES + 1)
            right = self._print_node(node.arguments[1], _Prec.IMPLIES)
            text = f"{left} {self._op('->', '→')} {right}"
            return self._paren(text, _Prec.IMPLIES, parent_prec)
        if kind is NodeKind.IFF or kind == NodeKind.IFF.value:
            left = self._print_node(node.arguments[0], _Prec.IFF + 1)
            right = self._print_node(node.arguments[1], _Prec.IFF + 1)
            text = f"{left} {self._op('iff', '↔')} {right}"
            return self._paren(text, _Prec.IFF, parent_prec)
        if kind is NodeKind.FORALL or kind == NodeKind.FORALL.value:
            return self._print_quantifier("forall", "∀", node, parent_prec)
        if kind is NodeKind.EXISTS or kind == NodeKind.EXISTS.value:
            return self._print_quantifier("exists", "∃", node, parent_prec)
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, parent_prec)
        if kind in {NodeKind.VARIABLE, NodeKind.CONSTANT} or kind in {
            NodeKind.VARIABLE.value,
            NodeKind.CONSTANT.value,
        }:
            return str(node.symbol or "")
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_quantifier(
        self,
        ascii_kw: str,
        unicode_kw: str,
        node: LogicNode,
        parent_prec: int,
    ) -> str:
        var = node.binders[0].name if node.binders else "x"
        sort = node.binders[0].sort.name if node.binders else HEAP_LOCATION_SORT_NAME
        body = (
            self._print_node(node.arguments[0], _Prec.BOTTOM)
            if node.arguments
            else "true"
        )
        # Omit default HeapLoc sort for compactness.
        if sort == HEAP_LOCATION_SORT_NAME:
            text = f"{self._op(ascii_kw, unicode_kw)} {var}. {body}"
        else:
            text = f"{self._op(ascii_kw, unicode_kw)} {var}: {sort}. {body}"
        return self._paren(text, _Prec.BOTTOM, parent_prec)

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        assert node.extension is not None
        payload = dict(node.extension.payload)
        kind = str(payload.get("kind") or "")
        children = node.extension.children

        if kind == "emp":
            return "emp"
        if kind == "atom":
            return str(payload.get("name") or "p")
        if kind == "points_to":
            loc = str(payload.get("location") or "x")
            val = str(payload.get("value") or "v")
            perm = payload.get("permission") or {}
            text = f"{loc} |-> {val}"
            if isinstance(perm, Mapping):
                num = int(perm.get("numerator", 1))
                den = int(perm.get("denominator", 1))
                if not (num == 1 and den == 1):
                    if num == 1 and den == 2:
                        text = f"{text} @ half"
                    else:
                        text = f"{text} @ {num}/{den}"
            return text
        if kind == "owns":
            principal = str(payload.get("principal") or "o")
            location = str(payload.get("location") or "x")
            perm = payload.get("permission") or {}
            text = f"owns({principal}, {location}"
            if isinstance(perm, Mapping):
                num = int(perm.get("numerator", 1))
                den = int(perm.get("denominator", 1))
                if not (num == 1 and den == 1):
                    text = f"{text}, {num}/{den}"
            return f"{text})"
        if kind == "pure":
            inner = (
                self._print_node(children[0], _Prec.BOTTOM)
                if children
                else "true"
            )
            return f"pure({inner})"
        if kind == "sep_conj":
            left = (
                self._print_node(children[0], _Prec.SEP)
                if children
                else "emp"
            )
            right = (
                self._print_node(children[1], _Prec.SEP)
                if len(children) > 1
                else "emp"
            )
            text = f"{left} * {right}"
            return self._paren(text, _Prec.SEP, parent_prec)
        if kind == "wand":
            left = (
                self._print_node(children[0], _Prec.WAND + 1)
                if children
                else "emp"
            )
            right = (
                self._print_node(children[1], _Prec.WAND)
                if len(children) > 1
                else "emp"
            )
            text = f"{left} -* {right}"
            return self._paren(text, _Prec.WAND, parent_prec)

        # Session / concurrency / refinement extensions.
        if kind == "end":
            return "end"
        if kind == "dual":
            inner = (
                self._print_node(children[0], _Prec.BOTTOM)
                if children
                else "end"
            )
            return f"dual({inner})"
        if kind == "session_action":
            polarity = str(payload.get("polarity") or "")
            label = str(payload.get("label") or "a")
            sort = str(payload.get("payload_sort") or "T")
            cont = (
                self._print_node(children[0], _Prec.BOTTOM)
                if children
                else "end"
            )
            if polarity == SessionPolarity.SEND.value:
                return f"!{label}({sort}). {cont}"
            if polarity == SessionPolarity.RECEIVE.value:
                return f"?{label}({sort}). {cont}"
            return f"{label}. {cont}"
        if kind == "internal":
            cont = (
                self._print_node(children[0], _Prec.BOTTOM)
                if children
                else "end"
            )
            return f"tau. {cont}"
        if kind == "protocol_ref":
            return str(payload.get("name") or "P")
        if kind == "rely_guarantee":
            return (
                f"rely {payload.get('rely')} guarantee "
                f"{payload.get('guarantee')} for {payload.get('component')}"
            )
        if kind == "happens_before":
            return f"hb({payload.get('left')}, {payload.get('right')})"
        if kind == "atomic":
            return f"atomic({payload.get('body')})"
        if kind == "channel":
            eps = payload.get("endpoints") or ()
            return (
                f"channel {payload.get('name')} : {payload.get('mode')} "
                f"between {eps[0]}, {eps[1]}"
                if len(eps) >= 2
                else f"channel {payload.get('name')}"
            )
        if kind == "related":
            return (
                f"related({payload.get('abstract_state')}, "
                f"{payload.get('concrete_state')})"
            )
        if kind == "state_var":
            return str(payload.get("name") or "s")
        if kind == "simulation":
            direction = str(payload.get("direction") or "forward")
            head = (
                "forward_sim"
                if direction == SimulationDirection.FORWARD.value
                else "backward_sim"
            )
            return (
                f"{head}({payload.get('abstract_system')}, "
                f"{payload.get('concrete_system')})"
            )
        if kind == "obligation":
            return (
                f"refines({payload.get('concrete_system')}, "
                f"{payload.get('abstract_system')}, "
                f"{payload.get('refinement_kind')})"
            )

        raise SyntaxContractError(f"unsupported resource extension kind {kind!r}")

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


class SessionPrinter(ResourcePrinter):
    """Printer alias for session/process formulas."""


class RefinementPrinter(ResourcePrinter):
    """Printer alias for refinement formulas."""


# ---------------------------------------------------------------------------
# Parse results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceParseResult:
    """Structured result of one resource/session/refinement parse."""

    status: ParseStatus
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    expression: TypedExpression | None = None
    root: LogicNode | None = None
    profile: (
        ResourceLogicProfile
        | SessionProcessProfile
        | RefinementSyntaxProfile
        | None
    ) = None
    printed: str = ""
    free_variables: tuple[str, ...] = ()
    schema_version: str = RESOURCE_PARSE_RESULT_SCHEMA
    interface: str = RESOURCE_LOGIC_SYNTAX_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "free_variables": list(self.free_variables),
            "interface": self.interface,
            "ok": self.ok,
            "printed": self.printed,
            "profile": None if self.profile is None else self.profile.to_dict(),
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, ParseStatus)
                else str(self.status)
            ),
        }


@dataclass(frozen=True, slots=True)
class ResourceLoweringResult:
    """Result of lowering a resource/session/refinement AST to IR."""

    receipt: LoweringReceipt
    root: LogicNode | None = None
    printed: str = ""
    separation_formulas: tuple[dict[str, Any], ...] = ()
    session_protocol: SessionProtocol | None = None
    rely_guarantee: RelyGuaranteeContract | None = None
    refinement_kind: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.receipt.supported

    @property
    def has_loss(self) -> bool:
        return self.receipt.has_loss

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_loss": self.has_loss,
            "metadata": dict(self.metadata),
            "ok": self.ok,
            "printed": self.printed,
            "receipt": self.receipt.to_dict(),
            "refinement_kind": self.refinement_kind,
            "rely_guarantee": (
                None
                if self.rely_guarantee is None
                else self.rely_guarantee.to_dict()
            ),
            "separation_formulas": list(self.separation_formulas),
            "session_protocol": (
                None
                if self.session_protocol is None
                else self.session_protocol.to_dict()
            ),
        }


# ---------------------------------------------------------------------------
# Shared helpers for facades
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument, tokens: Sequence[LogicToken]
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"cst:tok:{index}",
            kind=token.kind
            if isinstance(token.kind, str)
            else token.kind.value,
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for index, token in enumerate(tokens)
        if token.kind != TokenKind.EOF.value
        and (
            token.kind != TokenKind.EOF
            if not isinstance(token.kind, str)
            else True
        )
    )
    covered = [
        token.range
        for token in tokens
        if token.kind != TokenKind.EOF.value
    ]
    holes: list[LogicCSTNode] = []
    cursor = 0
    for item in sorted(covered, key=lambda value: value.start):
        if item.start > cursor:
            holes.append(
                LogicCSTNode(
                    node_id=f"node:gap:{cursor}:{item.start}",
                    kind="gap",
                    range=SourceRange(start=cursor, end=item.start),
                    role=CSTNodeRole.GAP,
                )
            )
        cursor = max(cursor, item.end)
    if cursor < document.byte_length:
        holes.append(
            LogicCSTNode(
                node_id=f"node:gap:{cursor}:{document.byte_length}",
                kind="gap",
                range=SourceRange(start=cursor, end=document.byte_length),
                role=CSTNodeRole.GAP,
            )
        )
    leaves = tuple(sorted((*children, *holes), key=lambda node: node.range.start))
    if not leaves and document.byte_length == 0:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=(),
        )
    else:
        root = LogicCSTNode(
            node_id="node:root",
            kind="source_file",
            range=document.full_range(),
            role=CSTNodeRole.ROOT,
            children=leaves,
        )
    return LogicCST(
        cst_id=f"cst:{document.document_id}",
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_from_node(
    node: LogicNode, *, counter: list[int] | None = None
) -> list[SurfaceASTRef]:
    seq = counter if counter is not None else [0]
    refs: list[SurfaceASTRef] = []

    def walk(n: LogicNode) -> str:
        seq[0] += 1
        node_id = n.node_id if n.node_id else f"ast:{seq[0]}"
        child_ids: list[str] = []
        for child in n.arguments:
            child_ids.append(walk(child))
        if n.extension is not None:
            for child in n.extension.children:
                child_ids.append(walk(child))
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.binders:
            meta["binders"] = [b.name for b in n.binders]
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=kind.replace(" ", "_"),
                range=span,
                child_ids=tuple(child_ids),
                metadata=meta,
            )
        )
        return node_id

    walk(node)
    return refs


def _signature_for_resource(
    root: LogicNode, profile_id: str, family: str
) -> LogicSignature:
    atoms: list[str] = []

    def walk(n: LogicNode) -> None:
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            if payload.get("kind") == "atom":
                name = str(payload.get("name") or "")
                if name:
                    atoms.append(name)
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(root)
    unique = tuple(sorted(set(atoms)))
    if not unique:
        return LogicSignature(
            signature_id=f"sig:resource:{profile_id}",
            family=family,
            profile=profile_id,
            sorts=(HEAP_LOC_SORT, HEAP_VAL_SORT, OWNER_SORT, STATE_SORT),
            symbols=(),
            features=("resource",),
        )
    return propositional_signature(
        f"sig:resource:{profile_id}",
        unique,
        family=family,
        profile=profile_id,
    )


def _lex_document(
    document: SourceDocument,
    *,
    mode: ParseMode,
    limits: ParseLimits,
    keywords: Sequence[str],
) -> Any:
    rewritten = rewrite_resource_surface(document.text)
    lex_document = (
        document
        if rewritten == document.text
        else SourceDocument.from_text(
            document.document_id, rewritten, encoding="utf-8"
        )
    )
    lexer = BoundedLexer(
        keywords=keywords,
        multi_char_operators=_DEFAULT_MULTI_OPS,
    )
    return lexer.lex(lex_document, mode=mode, limits=limits), lex_document


def _promote_lex_diagnostics(
    diagnostics: Sequence[SyntaxDiagnostic],
) -> tuple[SyntaxDiagnostic, ...]:
    return tuple(
        SyntaxDiagnostic(
            diagnostic_id=f"diag:resource:lex:{index + 1}",
            code=CODE_LEXER_ERROR
            if item.code.startswith("lexer.")
            else item.code,
            message=item.message,
            severity=item.severity,
            range=item.range,
            remediation=item.remediation,
            metadata={"lexer_code": item.code},
        )
        for index, item in enumerate(diagnostics)
    )


# ---------------------------------------------------------------------------
# ResourceLogicSyntax@1
# ---------------------------------------------------------------------------


class ResourceLogicParser:
    """Notation parser for separation / ownership / heap syntax."""

    interface: ClassVar[str] = RESOURCE_LOGIC_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = RESOURCE_NOTATION_ID
    notation_version: ClassVar[str] = RESOURCE_NOTATION_VERSION

    def __init__(
        self,
        profile: ResourceLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, ResourceLogicProfile):
            raise SyntaxContractError("profile must be a ResourceLogicProfile")
        self.profile = profile
        self.printer = ResourcePrinter(style=print_style)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = self.profile
        raw = request.metadata.get("profile") or request.metadata.get(
            "resource_profile"
        )
        if isinstance(raw, ResourceLogicProfile):
            profile = raw
        elif isinstance(raw, Mapping):
            profile = ResourceLogicProfile.from_dict(raw)
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:resource:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: ResourceLogicProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:resource:1",
        expression_id: str = "expr:resource:1",
    ) -> ResourceParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="resource parse requires a ResourceLogicProfile",
                range=document.full_range(),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": RESOURCE_LOGIC_SYNTAX_INTERFACE},
            )
            return ResourceParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
                interface=RESOURCE_LOGIC_SYNTAX_INTERFACE,
            )

        lex_result, lex_document = _lex_document(
            document,
            mode=parse_mode,
            limits=bounds,
            keywords=_RESOURCE_KEYWORDS,
        )
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = _promote_lex_diagnostics(lex_result.diagnostics)
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=promoted,
                metadata={"interface": RESOURCE_LOGIC_SYNTAX_INTERFACE},
            )
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                interface=RESOURCE_LOGIC_SYNTAX_INTERFACE,
            )

        engine = _ResourceParserEngine(
            document=lex_document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)

        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": RESOURCE_LOGIC_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                interface=RESOURCE_LOGIC_SYNTAX_INTERFACE,
            )

        free = free_resource_variables(root)
        # Free pure atoms are fine; free points-to/owns vars are ownership-sensitive
        # only when the formula quantifies resources — allow free heap names as
        # constants. Capture-safety is enforced for rebinding at parse time.
        sig = _signature_for_resource(root, prof.profile_id, RESOURCE_FAMILY_ID)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=sig,
            family=RESOURCE_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        printed = self.printer.print(root)
        cst = _build_covering_cst(lex_document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            diagnostics=all_diags,
            cst=cst,
            surface_ast=surface,
            metadata={
                "authority_ceiling": prof.evidence.authority_ceiling.value,
                "expression": expression.to_dict(),
                "free_variables": sorted(free),
                "interface": RESOURCE_LOGIC_SYNTAX_INTERFACE,
                "notation_id": RESOURCE_NOTATION_ID,
                "notation_version": RESOURCE_NOTATION_VERSION,
                "printed": printed,
                "profile": prof.to_dict(),
                "source_map_schema": RESOURCE_SOURCE_MAP_SCHEMA,
            },
        )
        return ResourceParseResult(
            status=ParseStatus.OK,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            expression=expression,
            root=root,
            profile=prof,
            printed=printed,
            free_variables=tuple(sorted(free)),
            interface=RESOURCE_LOGIC_SYNTAX_INTERFACE,
        )


class ResourceLogicSyntax:
    """Facade for ``ResourceLogicSyntax@1``."""

    interface: ClassVar[str] = RESOURCE_LOGIC_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: ResourceLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile if profile is not None else profile_separation()
        self.parser = ResourceLogicParser(
            self.profile, print_style=print_style
        )
        self.printer = self.parser.printer

    def parse_text(self, text: str, **kwargs: Any) -> ResourceParseResult:
        document = SourceDocument.from_text(
            str(kwargs.pop("document_id", "doc:resource:1")),
            text,
            encoding="utf-8",
        )
        return self.parser.parse_document(
            document,
            profile=kwargs.pop("profile", self.profile),
            mode=kwargs.pop("mode", ParseMode.STRICT),
            limits=kwargs.pop("limits", None),
            request_id=str(kwargs.pop("request_id", "req:resource:1")),
            expression_id=str(kwargs.pop("expression_id", "expr:resource:1")),
        )

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)


# ---------------------------------------------------------------------------
# SessionProcessSyntax@1
# ---------------------------------------------------------------------------


class SessionProcessParser:
    """Notation parser for session/process/concurrency syntax."""

    interface: ClassVar[str] = SESSION_PROCESS_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: SessionProcessProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, SessionProcessProfile):
            raise SyntaxContractError("profile must be a SessionProcessProfile")
        self.profile = profile
        self.printer = SessionPrinter(style=print_style)

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: SessionProcessProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:session:1",
        expression_id: str = "expr:session:1",
    ) -> ResourceParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="session parse requires a SessionProcessProfile",
                range=document.full_range(),
            )
            return ResourceParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                interface=SESSION_PROCESS_SYNTAX_INTERFACE,
                schema_version=SESSION_PARSE_RESULT_SCHEMA,
            )

        lex_result, lex_document = _lex_document(
            document,
            mode=parse_mode,
            limits=bounds,
            keywords=_RESOURCE_KEYWORDS,
        )
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = _promote_lex_diagnostics(lex_result.diagnostics)
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                profile=prof,
                interface=SESSION_PROCESS_SYNTAX_INTERFACE,
                schema_version=SESSION_PARSE_RESULT_SCHEMA,
            )

        engine = _SessionParserEngine(
            document=lex_document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)
        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": SESSION_PROCESS_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                interface=SESSION_PROCESS_SYNTAX_INTERFACE,
                schema_version=SESSION_PARSE_RESULT_SCHEMA,
            )

        free = free_session_channels(root)
        sig = _signature_for_resource(root, prof.profile_id, SESSION_FAMILY_ID)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=sig,
            family=SESSION_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        printed = self.printer.print(root)
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            diagnostics=all_diags,
            cst=_build_covering_cst(lex_document, lex_result.tokens),
            surface_ast=tuple(_surface_from_node(root)),
            metadata={
                "authority_ceiling": prof.evidence.authority_ceiling.value,
                "expression": expression.to_dict(),
                "free_variables": sorted(free),
                "interface": SESSION_PROCESS_SYNTAX_INTERFACE,
                "printed": printed,
                "profile": prof.to_dict(),
            },
        )
        return ResourceParseResult(
            status=ParseStatus.OK,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            expression=expression,
            root=root,
            profile=prof,
            printed=printed,
            free_variables=tuple(sorted(free)),
            interface=SESSION_PROCESS_SYNTAX_INTERFACE,
            schema_version=SESSION_PARSE_RESULT_SCHEMA,
        )


class SessionProcessSyntax:
    """Facade for ``SessionProcessSyntax@1``."""

    interface: ClassVar[str] = SESSION_PROCESS_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: SessionProcessProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile if profile is not None else profile_session()
        self.parser = SessionProcessParser(
            self.profile, print_style=print_style
        )
        self.printer = self.parser.printer

    def parse_text(self, text: str, **kwargs: Any) -> ResourceParseResult:
        document = SourceDocument.from_text(
            str(kwargs.pop("document_id", "doc:session:1")),
            text,
            encoding="utf-8",
        )
        return self.parser.parse_document(
            document,
            profile=kwargs.pop("profile", self.profile),
            mode=kwargs.pop("mode", ParseMode.STRICT),
            limits=kwargs.pop("limits", None),
            request_id=str(kwargs.pop("request_id", "req:session:1")),
            expression_id=str(kwargs.pop("expression_id", "expr:session:1")),
        )

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def dualize(self, node: LogicNode) -> LogicNode:
        """Return the dual session process (capture-safe structural dual)."""

        return dualize_session_node(node)


# ---------------------------------------------------------------------------
# RefinementSyntax@1
# ---------------------------------------------------------------------------


class RefinementSyntaxParser:
    """Notation parser for refinement / relational / simulation syntax."""

    interface: ClassVar[str] = REFINEMENT_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: RefinementSyntaxProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(
            profile, RefinementSyntaxProfile
        ):
            raise SyntaxContractError(
                "profile must be a RefinementSyntaxProfile"
            )
        self.profile = profile
        self.printer = RefinementPrinter(style=print_style)

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: RefinementSyntaxProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:refinement:1",
        expression_id: str = "expr:refinement:1",
    ) -> ResourceParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="refinement parse requires a RefinementSyntaxProfile",
                range=document.full_range(),
            )
            return ResourceParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                interface=REFINEMENT_SYNTAX_INTERFACE,
                schema_version=REFINEMENT_PARSE_RESULT_SCHEMA,
            )

        lex_result, lex_document = _lex_document(
            document,
            mode=parse_mode,
            limits=bounds,
            keywords=_RESOURCE_KEYWORDS,
        )
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = _promote_lex_diagnostics(lex_result.diagnostics)
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                profile=prof,
                interface=REFINEMENT_SYNTAX_INTERFACE,
                schema_version=REFINEMENT_PARSE_RESULT_SCHEMA,
            )

        engine = _RefinementParserEngine(
            document=lex_document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
        )
        root, diagnostics = engine.parse()
        all_diags = tuple(lex_result.diagnostics) + tuple(diagnostics)
        if root is None or any(item.is_error for item in all_diags):
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": REFINEMENT_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                interface=REFINEMENT_SYNTAX_INTERFACE,
                schema_version=REFINEMENT_PARSE_RESULT_SCHEMA,
            )

        free = free_state_variables(root)
        if free and prof.require_two_state_capture_safety:
            diag = _diag(
                code=CODE_TWO_STATE_CAPTURE,
                message=(
                    f"formula has free state variables {sorted(free)!r} "
                    "(capture-safety violation)"
                ),
                range=root.range or document.full_range(),
                metadata={"free": sorted(free)},
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags + (diag,),
                metadata={"interface": REFINEMENT_SYNTAX_INTERFACE},
            )
            return ResourceParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags + (diag,),
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                free_variables=tuple(sorted(free)),
                interface=REFINEMENT_SYNTAX_INTERFACE,
                schema_version=REFINEMENT_PARSE_RESULT_SCHEMA,
            )

        sig = _signature_for_resource(
            root, prof.profile_id, REFINEMENT_FAMILY_ID
        )
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=sig,
            family=REFINEMENT_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        printed = self.printer.print(root)
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            diagnostics=all_diags,
            cst=_build_covering_cst(lex_document, lex_result.tokens),
            surface_ast=tuple(_surface_from_node(root)),
            metadata={
                "authority_ceiling": prof.evidence.authority_ceiling.value,
                "expression": expression.to_dict(),
                "free_variables": sorted(free),
                "interface": REFINEMENT_SYNTAX_INTERFACE,
                "printed": printed,
                "profile": prof.to_dict(),
            },
        )
        return ResourceParseResult(
            status=ParseStatus.OK,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            expression=expression,
            root=root,
            profile=prof,
            printed=printed,
            free_variables=tuple(sorted(free)),
            interface=REFINEMENT_SYNTAX_INTERFACE,
            schema_version=REFINEMENT_PARSE_RESULT_SCHEMA,
        )


class RefinementSyntax:
    """Facade for ``RefinementSyntax@1``."""

    interface: ClassVar[str] = REFINEMENT_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: RefinementSyntaxProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = (
            profile if profile is not None else profile_refinement()
        )
        self.parser = RefinementSyntaxParser(
            self.profile, print_style=print_style
        )
        self.printer = self.parser.printer

    def parse_text(self, text: str, **kwargs: Any) -> ResourceParseResult:
        document = SourceDocument.from_text(
            str(kwargs.pop("document_id", "doc:refinement:1")),
            text,
            encoding="utf-8",
        )
        return self.parser.parse_document(
            document,
            profile=kwargs.pop("profile", self.profile),
            mode=kwargs.pop("mode", ParseMode.STRICT),
            limits=kwargs.pop("limits", None),
            request_id=str(kwargs.pop("request_id", "req:refinement:1")),
            expression_id=str(
                kwargs.pop("expression_id", "expr:refinement:1")
            ),
        )

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)


# ---------------------------------------------------------------------------
# Public parse / lower entry points
# ---------------------------------------------------------------------------


def parse_resource(
    text: str,
    profile: ResourceLogicProfile | None = None,
    **kwargs: Any,
) -> ResourceParseResult:
    """Parse a separation-logic formula under *profile*."""

    syntax = ResourceLogicSyntax(profile or profile_separation())
    return syntax.parse_text(text, **kwargs)


def parse_session(
    text: str,
    profile: SessionProcessProfile | None = None,
    **kwargs: Any,
) -> ResourceParseResult:
    """Parse a session/process/concurrency formula under *profile*."""

    syntax = SessionProcessSyntax(profile or profile_session())
    return syntax.parse_text(text, **kwargs)


def parse_refinement(
    text: str,
    profile: RefinementSyntaxProfile | None = None,
    **kwargs: Any,
) -> ResourceParseResult:
    """Parse a refinement/relational formula under *profile*."""

    syntax = RefinementSyntax(profile or profile_refinement())
    return syntax.parse_text(text, **kwargs)


def print_resource(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    """Print a resource/session/refinement AST."""

    return ResourcePrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: ResourceLogicProfile | None = None,
) -> tuple[ResourceParseResult, ResourceParseResult, bool]:
    """Parse, print, re-parse; return alpha-equivalence of roots."""

    first = parse_resource(text, profile)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_resource(first.root)
    second = parse_resource(printed, profile)
    if not second.ok or second.root is None:
        return first, second, False
    return first, second, alpha_equivalent(first.root, second.root)


def _collect_spatial_features(node: LogicNode) -> tuple[set[str], set[str]]:
    retained: set[str] = set()
    dropped: set[str] = set()

    def walk(n: LogicNode) -> None:
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            kind = str(payload.get("kind") or "")
            retained.update(n.extension.features)
            if kind in {"wand", "septraction"}:
                dropped.add(f"spatial.{kind}")
            if kind == "points_to":
                retained.add("heap.points_to")
            if kind == "sep_conj":
                retained.add("heap.sep_conj")
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)
        if n.kind in {NodeKind.FORALL, NodeKind.EXISTS}:
            retained.add("binder")

    walk(node)
    return retained, dropped


def lower_resource(
    text_or_node: str | LogicNode,
    profile: ResourceLogicProfile | None = None,
) -> ResourceLoweringResult:
    """Lower separation syntax to formula descriptors with explicit loss.

    Unsupported resource algebras and non-FOL-lowerable heap theories never
    become silent pure FOL claims: the receipt records ``loss_kind`` and
    finite bounds from the profile evidence contract.
    """

    prof = profile or profile_separation()
    if isinstance(text_or_node, str):
        parsed = parse_resource(text_or_node, prof)
        if not parsed.ok or parsed.root is None:
            return ResourceLoweringResult(
                receipt=lossy_lowering_receipt(
                    loss_kind=LossKind.SPATIAL_CONNECTIVE,
                    loss_message="parse failed before lowering",
                    loss_bounds=prof.evidence.bound.to_dict(),
                    target_interface=SEPARATION_LOGIC_IR_INTERFACE,
                    features_dropped=("parse",),
                ),
                metadata={
                    "diagnostics": [d.to_dict() for d in parsed.diagnostics]
                },
            )
        root = parsed.root
        printed = parsed.printed
    else:
        root = text_or_node
        printed = print_resource(root)

    retained, dropped = _collect_spatial_features(root)
    bound = prof.evidence.bound.to_dict()

    # Unsupported algebra → explicit loss.
    if not prof.algebra_supported:
        return ResourceLoweringResult(
            receipt=lossy_lowering_receipt(
                loss_kind=LossKind.RESOURCE_ALGEBRA,
                loss_message=(
                    f"resource algebra {prof.resource_algebra!r} is unsupported; "
                    "lower only with explicit loss and bounds"
                ),
                loss_bounds={
                    **bound,
                    "resource_algebra": prof.resource_algebra,
                    "unsupported_algebras": sorted(
                        UNSUPPORTED_RESOURCE_ALGEBRAS
                    ),
                },
                target_interface=SEPARATION_LOGIC_IR_INTERFACE,
                features_retained=sorted(retained),
                features_dropped=sorted(dropped | {"resource_algebra"}),
            ),
            root=root,
            printed=printed,
            metadata={"profile": prof.to_dict()},
        )

    if not prof.heap_theory_supported:
        theory = (
            prof.heap_theory.value
            if isinstance(prof.heap_theory, HeapTheory)
            else str(prof.heap_theory)
        )
        return ResourceLoweringResult(
            receipt=lossy_lowering_receipt(
                loss_kind=LossKind.HEAP_THEORY,
                loss_message=(
                    f"heap theory {theory!r} cannot silently lower to FOL; "
                    "spatial structure is retained only under explicit loss"
                ),
                loss_bounds={
                    **bound,
                    "heap_theory": theory,
                    "fol_partial_theories": sorted(_SUPPORTED_HEAP_THEORIES),
                },
                target_interface=SEPARATION_LOGIC_IR_INTERFACE,
                features_retained=sorted(retained),
                features_dropped=sorted(dropped | {"heap_theory"}),
            ),
            root=root,
            printed=printed,
            metadata={"profile": prof.to_dict()},
        )

    # Spatial connectives (sep_conj, points_to, wand) are typed but FOL-lossy
    # when wand is present.
    has_wand = "resource.wand" in retained or "spatial.wand" in dropped
    formulas = _flatten_separation_descriptors(root)
    if has_wand:
        return ResourceLoweringResult(
            receipt=lossy_lowering_receipt(
                loss_kind=LossKind.SPATIAL_CONNECTIVE,
                loss_message=(
                    "magic wand does not admit a silent FOL encoding; "
                    "retained as typed spatial obligation under finite bounds"
                ),
                loss_bounds={
                    **bound,
                    "spatial_connectives": ["wand"],
                },
                target_interface=SEPARATION_LOGIC_IR_INTERFACE,
                features_retained=sorted(retained - {"resource.wand"}),
                features_dropped=("resource.wand", "spatial.wand"),
            ),
            root=root,
            printed=printed,
            separation_formulas=tuple(formulas),
            metadata={"profile": prof.to_dict()},
        )

    return ResourceLoweringResult(
        receipt=supported_lowering_receipt(
            target_interface=SEPARATION_LOGIC_IR_INTERFACE,
            features_retained=sorted(retained),
        ),
        root=root,
        printed=printed,
        separation_formulas=tuple(formulas),
        metadata={
            "authority_ceiling": prof.evidence.authority_ceiling.value,
            "bound": bound,
            "profile": prof.to_dict(),
        },
    )


def _flatten_separation_descriptors(node: LogicNode) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def walk(n: LogicNode) -> None:
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            kind = payload.get("kind")
            if kind in {
                "emp",
                "points_to",
                "sep_conj",
                "wand",
                "owns",
                "pure",
                "atom",
            }:
                items.append(
                    {
                        "features": list(n.extension.features),
                        "kind": kind,
                        "payload": payload,
                    }
                )
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(node)
    return items


def lower_session(
    text_or_node: str | LogicNode,
    profile: SessionProcessProfile | None = None,
    *,
    protocol_id: str = "sess:parsed",
    name: str = "ParsedSession",
    role: SessionRole | str = SessionRole.CLIENT,
) -> ResourceLoweringResult:
    """Lower session/process syntax; unsupported ops emit explicit loss."""

    prof = profile or profile_session()
    if isinstance(text_or_node, str):
        # Detect unsupported operators before / during parse.
        folded_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text_or_node))
        bad = folded_tokens & UNSUPPORTED_PROCESS_OPERATORS
        if bad and prof.reject_unsupported_process_ops:
            return ResourceLoweringResult(
                receipt=lossy_lowering_receipt(
                    loss_kind=LossKind.PROCESS_OPERATOR,
                    loss_message=(
                        f"unsupported process operator(s) {sorted(bad)!r}; "
                        "lower only with explicit loss and bounds"
                    ),
                    loss_bounds={
                        **prof.evidence.bound.to_dict(),
                        "operators": sorted(bad),
                        "max_schedule_steps": (
                            prof.evidence.bound.max_schedule_steps
                        ),
                    },
                    target_interface=CONCURRENCY_IR_INTERFACE,
                    features_dropped=tuple(sorted(bad)),
                ),
                metadata={"unsupported_operators": sorted(bad)},
            )
        # Unsupported concurrency assumptions named in the surface.
        bad_assump = folded_tokens & UNSUPPORTED_CONCURRENCY_ASSUMPTIONS
        if bad_assump:
            return ResourceLoweringResult(
                receipt=lossy_lowering_receipt(
                    loss_kind=LossKind.CONCURRENCY_ASSUMPTION,
                    loss_message=(
                        f"unsupported concurrency assumption(s) "
                        f"{sorted(bad_assump)!r}; lower only with explicit "
                        "loss and bounds"
                    ),
                    loss_bounds={
                        **prof.evidence.bound.to_dict(),
                        "assumptions": sorted(bad_assump),
                    },
                    target_interface=CONCURRENCY_IR_INTERFACE,
                    features_dropped=tuple(sorted(bad_assump)),
                ),
                metadata={"unsupported_assumptions": sorted(bad_assump)},
            )
        parsed = parse_session(text_or_node, prof)
        if not parsed.ok or parsed.root is None:
            return ResourceLoweringResult(
                receipt=lossy_lowering_receipt(
                    loss_kind=LossKind.PROCESS_OPERATOR,
                    loss_message="session parse failed before lowering",
                    loss_bounds=prof.evidence.bound.to_dict(),
                    target_interface=CONCURRENCY_IR_INTERFACE,
                ),
                metadata={
                    "diagnostics": [d.to_dict() for d in parsed.diagnostics]
                },
            )
        root = parsed.root
        printed = parsed.printed
    else:
        root = text_or_node
        printed = print_resource(root)

    # Rely-guarantee atom.
    if (
        root.kind is NodeKind.EXTENSION
        and root.extension is not None
        and root.extension.payload.get("kind") == "rely_guarantee"
    ):
        payload = dict(root.extension.payload)
        contract = RelyGuaranteeContract(
            contract_id=f"rg:{payload.get('component')}",
            component_id=f"comp:{payload.get('component')}",
            rely_statement=str(payload.get("rely") or "true"),
            guarantee_statement=str(payload.get("guarantee") or "true"),
        )
        return ResourceLoweringResult(
            receipt=supported_lowering_receipt(
                target_interface=CONCURRENCY_IR_INTERFACE,
                features_retained=("concurrency.rely_guarantee",),
            ),
            root=root,
            printed=printed,
            rely_guarantee=contract,
            metadata={"bound": prof.evidence.bound.to_dict()},
        )

    # Session protocol extraction (send/recv/end spine).
    try:
        if (
            root.kind is NodeKind.EXTENSION
            and root.extension is not None
            and root.extension.payload.get("kind")
            in {
                "session_action",
                "end",
                "dual",
                "internal",
            }
        ):
            actions = session_actions_from_node(root, prefix=protocol_id)
            if not actions:
                raise ResourceParseError(
                    "empty session action spine", code=CODE_INVALID_SESSION
                )
            protocol = SessionProtocol(
                protocol_id=protocol_id,
                name=name,
                role=role,
                actions=actions,
                entry_action_id=actions[0].action_id,
            )
            # Duality check: dual(dual(P)) recovers polarities.
            dual = protocol.dual()
            dual_dual = dual.dual(protocol_id=protocol_id, name=name)
            recovered = tuple(
                (a.action_id, a.polarity) for a in dual_dual.actions
            )
            original = tuple((a.action_id, a.polarity) for a in protocol.actions)
            if recovered != original:
                return ResourceLoweringResult(
                    receipt=lossy_lowering_receipt(
                        loss_kind=LossKind.PROCESS_OPERATOR,
                        loss_message=(
                            "session duality is not involutive for this process"
                        ),
                        loss_bounds=prof.evidence.bound.to_dict(),
                        target_interface=CONCURRENCY_IR_INTERFACE,
                        features_dropped=("session.duality",),
                    ),
                    root=root,
                    printed=printed,
                )
            return ResourceLoweringResult(
                receipt=supported_lowering_receipt(
                    target_interface=CONCURRENCY_IR_INTERFACE,
                    features_retained=(
                        "session.action",
                        "session.duality",
                    ),
                ),
                root=root,
                printed=printed,
                session_protocol=protocol,
                metadata={
                    "bound": prof.evidence.bound.to_dict(),
                    "dual_protocol_id": dual.protocol_id,
                },
            )
    except (ResourceParseError, ConcurrencyValidationError) as error:
        return ResourceLoweringResult(
            receipt=lossy_lowering_receipt(
                loss_kind=LossKind.PROCESS_OPERATOR,
                loss_message=str(error),
                loss_bounds=prof.evidence.bound.to_dict(),
                target_interface=CONCURRENCY_IR_INTERFACE,
            ),
            root=root,
            printed=printed,
        )

    # Happens-before / atomic / channel: typed retained under schedule bounds.
    return ResourceLoweringResult(
        receipt=supported_lowering_receipt(
            target_interface=CONCURRENCY_IR_INTERFACE,
            features_retained=("session.surface",),
        ),
        root=root,
        printed=printed,
        metadata={"bound": prof.evidence.bound.to_dict()},
    )


def lower_refinement(
    text_or_node: str | LogicNode,
    profile: RefinementSyntaxProfile | None = None,
) -> ResourceLoweringResult:
    """Lower refinement/relational syntax with finite simulation bounds."""

    prof = profile or profile_refinement()
    if isinstance(text_or_node, str):
        parsed = parse_refinement(text_or_node, prof)
        if not parsed.ok or parsed.root is None:
            return ResourceLoweringResult(
                receipt=lossy_lowering_receipt(
                    loss_kind=LossKind.UNBOUNDED_CLAIM,
                    loss_message="refinement parse failed before lowering",
                    loss_bounds=prof.evidence.bound.to_dict(),
                    target_interface=REFINEMENT_IR_INTERFACE,
                ),
                metadata={
                    "diagnostics": [d.to_dict() for d in parsed.diagnostics]
                },
            )
        root = parsed.root
        printed = parsed.printed
    else:
        root = text_or_node
        printed = print_resource(root)

    kind = ""
    if root.kind is NodeKind.EXTENSION and root.extension is not None:
        payload = dict(root.extension.payload)
        kind = str(
            payload.get("refinement_kind")
            or payload.get("direction")
            or payload.get("kind")
            or ""
        )
    elif root.metadata.get("refinement_two_state"):
        kind = "two_state"

    return ResourceLoweringResult(
        receipt=supported_lowering_receipt(
            target_interface=REFINEMENT_IR_INTERFACE,
            features_retained=("refinement.surface", kind or "relational"),
        ),
        root=root,
        printed=printed,
        refinement_kind=kind,
        metadata={
            "authority_ceiling": prof.evidence.authority_ceiling.value,
            "bound": prof.evidence.bound.to_dict(),
            "claims_unbounded_refinement": False,
            "max_simulation_steps": prof.evidence.bound.max_simulation_steps,
        },
    )


def validate_session_duality(
    protocol: SessionProtocol,
    dual: SessionProtocol | None = None,
) -> None:
    """Fail closed when session duality does not validate.

    Duality requires flipped send/receive polarities, dual roles, and
    involution (dual twice recovers the original polarities).
    """

    other = dual if dual is not None else protocol.dual()
    if dual_role(protocol.role) != other.role:
        raise ResourceParseError(
            "session dual role mismatch",
            code=CODE_SESSION_DUALITY,
        )
    if len(protocol.actions) != len(other.actions):
        raise ResourceParseError(
            "session dual action count mismatch",
            code=CODE_SESSION_DUALITY,
        )
    by_id = {action.action_id: action for action in other.actions}
    for action in protocol.actions:
        dual_action = by_id.get(action.action_id)
        if dual_action is None:
            raise ResourceParseError(
                f"dual missing action {action.action_id}",
                code=CODE_SESSION_DUALITY,
            )
        if dual_action.polarity != dual_polarity(action.polarity):
            raise ResourceParseError(
                f"dual polarity mismatch for {action.action_id}",
                code=CODE_SESSION_DUALITY,
            )
        if dual_action.label != action.label:
            raise ResourceParseError(
                f"dual label mismatch for {action.action_id}",
                code=CODE_SESSION_DUALITY,
            )
        if dual_action.payload_sort != action.payload_sort:
            raise ResourceParseError(
                f"dual payload_sort mismatch for {action.action_id}",
                code=CODE_SESSION_DUALITY,
            )
    # Involution.
    back = other.dual(
        protocol_id=protocol.protocol_id, name=protocol.name
    )
    orig = tuple((a.action_id, a.polarity) for a in protocol.actions)
    got = tuple((a.action_id, a.polarity) for a in back.actions)
    if orig != got:
        raise ResourceParseError(
            "session dual is not involutive",
            code=CODE_SESSION_DUALITY,
        )


__all__ = [
    "BoundednessKind",
    "CODE_CHANNEL_CAPTURE",
    "CODE_FREE_VARIABLE",
    "CODE_LOWERING_LOSS",
    "CODE_OWNERSHIP_CAPTURE",
    "CODE_REBIND_VARIABLE",
    "CODE_SESSION_DUALITY",
    "CODE_TWO_STATE_CAPTURE",
    "CODE_UNSUPPORTED_ALGEBRA",
    "CODE_UNSUPPORTED_CONCURRENCY",
    "CODE_UNSUPPORTED_PROCESS",
    "EvidenceAuthority",
    "LossKind",
    "LoweringReceipt",
    "PrintStyle",
    "REFINEMENT_SYNTAX_INTERFACE",
    "RESOURCE_LOGIC_SYNTAX_INTERFACE",
    "ResourceBoundContract",
    "ResourceEvidenceContract",
    "ResourceLogicKind",
    "ResourceLogicParser",
    "ResourceLogicProfile",
    "ResourceLogicSyntax",
    "ResourceLoweringResult",
    "ResourceParseError",
    "ResourceParseResult",
    "ResourcePrinter",
    "RefinementSyntax",
    "RefinementSyntaxParser",
    "RefinementSyntaxProfile",
    "RefinementSurfaceKind",
    "SESSION_PROCESS_SYNTAX_INTERFACE",
    "SessionProcessParser",
    "SessionProcessProfile",
    "SessionProcessSyntax",
    "SessionSurfaceKind",
    "UNSUPPORTED_CONCURRENCY_ASSUMPTIONS",
    "UNSUPPORTED_PROCESS_OPERATORS",
    "UNSUPPORTED_RESOURCE_ALGEBRAS",
    "dualize_session_node",
    "free_resource_variables",
    "free_session_channels",
    "free_state_variables",
    "lossy_lowering_receipt",
    "lower_refinement",
    "lower_resource",
    "lower_session",
    "parse_print_parse",
    "parse_refinement",
    "parse_resource",
    "parse_session",
    "print_resource",
    "profile_ownership",
    "profile_refinement",
    "profile_rely_guarantee",
    "profile_separation",
    "profile_session",
    "rewrite_resource_surface",
    "session_actions_from_node",
    "supported_lowering_receipt",
    "validate_session_duality",
]
