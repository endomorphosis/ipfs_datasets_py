"""Linear, session, process, and relational refinement profiles (LFP2-043).

Interface:

* ``SessionProcessLogic@1`` — parse/print/elaborate for controlled linear-logic
  resources, session types, process-calculus composition, and relational
  refinement obligations under **named** semantic profiles

Owned constructs:

* linear resources and multiplicative/additive connectives (tensor, lolli,
  with, plus, ofcourse / bang)
* session actions (send ``!``, receive ``?``, internal ``tau``, ``end``)
* session duality (``dual``) with involution checks
* process composition (``par``, ``new``/``restrict``, ``nil``)
* explicit progress models (fair / unfair / partial / none)
* relational refinement and simulation with **explicit direction**

Authority ceilings (fail-closed):

* Linearity is checked; resource duplication is **never** silently normalized.
* Duality must validate (polarity flip + involution).
* Process scope (channel binding under ``new``/``restrict``) is capture-safe.
* Progress models are profile fields or surface atoms — never inferred.
* Refinement direction is required when the profile demands it.

Grammar (connective precedence, low → high)::

    formula     ::= refinement | process | linear
    refinement  ::= 'refines'|'simulates' '(' IDENT ',' IDENT (',' DIR)? ')'
                  | ('forall_states'|'exists_states') IDENT ',' IDENT '.' formula
    process     ::= 'par' '(' formula ',' formula ')'
                  | 'new'|'restrict' '(' IDENT ')' '.' formula
                  | 'nil' | session | linear
    session     ::= 'end'
                  | ('!'|'?') IDENT ('(' IDENT ')')? '.' formula
                  | 'tau' '.' formula
                  | 'dual' '(' formula ')'
    linear      ::= lolli (('tensor'|'*') lolli)*
    lolli       ::= with (('-o'|'lolli'|'⊸') with)?      # right-assoc
    with        ::= plus (('with'|'&') plus)*
    plus        ::= unary (('plus'|'+') unary)*
    unary       ::= ('ofcourse'|'bang'|'!') unary | atomic
    atomic      ::= 'resource'|'res' '(' IDENT ')'
                  | 'chan'|'channel' '(' IDENT ')'
                  | 'progress' '(' MODEL ')'
                  | 'dup' '(' IDENT ')'
                  | 'true'|⊤ | 'false'|⊥
                  | IDENT | '(' formula ')'
    DIR         ::= 'forward'|'backward'|'bisimulation'|'none'
    MODEL       ::= 'fair'|'unfair'|'partial'|'none'|'weak_fair'|'strong_fair'

Evidence subset: linear session process channel duality refinement concurrency
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.concurrency import (
    SessionPolarity,
    SessionRole,
    dual_polarity,
    dual_role,
)
from ipfs_datasets_py.logic.software_verification.refinement import (
    SimulationDirection,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
    mk_false,
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
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SESSION_PROCESS_LOGIC_INTERFACE: Final = "SessionProcessLogic@1"
SESSION_PROCESS_PROFILE_INTERFACE: Final = "SessionProcessLogicProfile@1"
LINEAR_PROFILE_INTERFACE: Final = "LinearLogicProfile@1"
SESSION_PROFILE_INTERFACE: Final = "SessionTypeProfile@1"
PROCESS_PROFILE_INTERFACE: Final = "ProcessCalculusProfile@1"
RELATIONAL_REFINEMENT_PROFILE_INTERFACE: Final = "RelationalRefinementProfile@1"

SP_NOTATION_ID: Final = "canonical_session_process"
SP_NOTATION_VERSION: Final = "1.0.0"
SP_MODULE_VERSION: Final = "1.0.0"
SP_TASK_ID: Final = "LFP2-043"

LINEAR_FAMILY_ID: Final = "linear_logic"
SESSION_FAMILY_ID: Final = "session_process"
PROCESS_FAMILY_ID: Final = "process_calculus"
REFINEMENT_FAMILY_ID: Final = "refinement"

SP_PARSE_RESULT_SCHEMA: Final = "canonical-session-process-parse-result/v1"
SP_PROFILE_SCHEMA: Final = "session-process-logic-profile/v1"
SP_EVIDENCE_CONTRACT_SCHEMA: Final = "session_process.evidence-contract/v1"
SP_SOURCE_MAP_SCHEMA: Final = "session_process.source-map/v1"
SP_IDENTITY_SCHEMA: Final = "session_process.identity/v1"
SP_LINEARITY_REPORT_SCHEMA: Final = "session_process.linearity-report/v1"
SP_DUALITY_REPORT_SCHEMA: Final = "session_process.duality-report/v1"
SP_SCOPE_REPORT_SCHEMA: Final = "session_process.scope-report/v1"
SP_PROGRESS_REPORT_SCHEMA: Final = "session_process.progress-report/v1"
SP_REFINEMENT_REPORT_SCHEMA: Final = "session_process.refinement-report/v1"

# Extension payload schemas (versioned family.construct/vN).
SP_RESOURCE_PAYLOAD_SCHEMA: Final = "session_process.resource/v1"
SP_TENSOR_PAYLOAD_SCHEMA: Final = "session_process.tensor/v1"
SP_LOLLI_PAYLOAD_SCHEMA: Final = "session_process.lolli/v1"
SP_WITH_PAYLOAD_SCHEMA: Final = "session_process.with/v1"
SP_PLUS_PAYLOAD_SCHEMA: Final = "session_process.plus/v1"
SP_OFCOURSE_PAYLOAD_SCHEMA: Final = "session_process.ofcourse/v1"
SP_SESSION_ACTION_PAYLOAD_SCHEMA: Final = "session_process.session_action/v1"
SP_SESSION_END_PAYLOAD_SCHEMA: Final = "session_process.session_end/v1"
SP_SESSION_DUAL_PAYLOAD_SCHEMA: Final = "session_process.session_dual/v1"
SP_PAR_PAYLOAD_SCHEMA: Final = "session_process.par/v1"
SP_NEW_PAYLOAD_SCHEMA: Final = "session_process.new/v1"
SP_NIL_PAYLOAD_SCHEMA: Final = "session_process.nil/v1"
SP_PROGRESS_PAYLOAD_SCHEMA: Final = "session_process.progress/v1"
SP_REFINES_PAYLOAD_SCHEMA: Final = "session_process.refines/v1"
SP_SIMULATES_PAYLOAD_SCHEMA: Final = "session_process.simulates/v1"
SP_TWO_STATE_PAYLOAD_SCHEMA: Final = "session_process.two_state/v1"
SP_ATOM_PAYLOAD_SCHEMA: Final = "session_process.atom/v1"
SP_CHAN_PAYLOAD_SCHEMA: Final = "session_process.channel_ref/v1"

RESOURCE_SORT: Final = atomic_sort("LinearResource")
CHANNEL_SORT: Final = atomic_sort("Channel")
STATE_SORT: Final = atomic_sort("State")
PROCESS_SORT: Final = atomic_sort("Process")
SESSION_SORT: Final = atomic_sort("Session")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "session_process.unexpected_token"
CODE_TRAILING_INPUT: Final = "session_process.trailing_input"
CODE_EMPTY_INPUT: Final = "session_process.empty_input"
CODE_PARSE_DEPTH: Final = "session_process.parse_depth_exceeded"
CODE_UNBALANCED: Final = "session_process.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "session_process.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "session_process.unknown_character"
CODE_PROFILE_REQUIRED: Final = "session_process.profile_required"
CODE_PROFILE_MISMATCH: Final = "session_process.profile_mismatch"
CODE_OPERATOR_FORBIDDEN: Final = "session_process.operator_forbidden"
CODE_LINEARITY: Final = "session_process.linearity_violation"
CODE_RESOURCE_DUPLICATION: Final = "session_process.resource_duplication"
CODE_DUALITY: Final = "session_process.duality_invalid"
CODE_PROCESS_SCOPE: Final = "session_process.process_scope"
CODE_FREE_CHANNEL: Final = "session_process.free_channel"
CODE_PROGRESS_REQUIRED: Final = "session_process.progress_model_required"
CODE_PROGRESS_MISMATCH: Final = "session_process.progress_model_mismatch"
CODE_REFINEMENT_DIRECTION: Final = "session_process.refinement_direction_required"
CODE_REFINEMENT_DIRECTION_MISMATCH: Final = (
    "session_process.refinement_direction_mismatch"
)
CODE_ROUND_TRIP: Final = "session_process.round_trip_failed"
CODE_ARITY_MISMATCH: Final = "session_process.arity_mismatch"
CODE_UNSUPPORTED_CONSTRUCT: Final = "session_process.unsupported_construct"

_ALL_SP_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_UNKNOWN_CHARACTER,
        CODE_PROFILE_REQUIRED,
        CODE_PROFILE_MISMATCH,
        CODE_OPERATOR_FORBIDDEN,
        CODE_LINEARITY,
        CODE_RESOURCE_DUPLICATION,
        CODE_DUALITY,
        CODE_PROCESS_SCOPE,
        CODE_FREE_CHANNEL,
        CODE_PROGRESS_REQUIRED,
        CODE_PROGRESS_MISMATCH,
        CODE_REFINEMENT_DIRECTION,
        CODE_REFINEMENT_DIRECTION_MISMATCH,
        CODE_ROUND_TRIP,
        CODE_ARITY_MISMATCH,
        CODE_UNSUPPORTED_CONSTRUCT,
    }
)

_TENSOR_OPS: Final[frozenset[str]] = frozenset({"tensor", "*", "⊗"})
_LOLLI_OPS: Final[frozenset[str]] = frozenset({"lolli", "-o", "⊸", "linimp"})
_WITH_OPS: Final[frozenset[str]] = frozenset({"with", "&"})
_PLUS_OPS: Final[frozenset[str]] = frozenset({"plus", "+"})
_OFCOURSE_OPS: Final[frozenset[str]] = frozenset({"ofcourse", "bang"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})

_SP_KEYWORDS: Final[tuple[str, ...]] = (
    "tensor",
    "lolli",
    "linimp",
    "with",
    "plus",
    "ofcourse",
    "bang",
    "resource",
    "res",
    "dup",
    "end",
    "tau",
    "dual",
    "par",
    "new",
    "restrict",
    "nil",
    "progress",
    "refines",
    "simulates",
    "forall_states",
    "exists_states",
    "forward",
    "backward",
    "bisimulation",
    "none",
    "fair",
    "unfair",
    "partial",
    "weak_fair",
    "strong_fair",
    "true",
    "false",
    "send",
    "recv",
    "receive",
    "chan",
    "channel",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class SessionProcessFamilyKind(str, Enum):
    """Declared session/process family fragment."""

    LINEAR = "linear"
    SESSION = "session"
    PROCESS = "process"
    RELATIONAL_REFINEMENT = "relational_refinement"


class ProgressModel(str, Enum):
    """Explicit progress / fairness model for process/session profiles.

    Progress is never inferred from operator spelling; profiles declare a
    default and surface ``progress(model)`` atoms must agree when required.
    """

    NONE = "none"
    FAIR = "fair"
    UNFAIR = "unfair"
    PARTIAL = "partial"
    WEAK_FAIR = "weak_fair"
    STRONG_FAIR = "strong_fair"


class RefinementDirectionKind(str, Enum):
    """Explicit refinement / simulation direction."""

    FORWARD = "forward"
    BACKWARD = "backward"
    BISEIMULATION = "bisimulation"
    NONE = "none"


class LinearityMode(str, Enum):
    """How linear resources are treated under a profile."""

    STRICT = "strict"  # each resource used exactly once under tensor
    AFFINE = "affine"  # at most once (weakening allowed)
    RELEVANT = "relevant"  # at least once (contraction forbidden)
    UNRESTRICTED = "unrestricted"  # classical reuse allowed


class SessionPolaritySurface(str, Enum):
    """Surface polarity for session actions."""

    SEND = "send"
    RECEIVE = "receive"
    INTERNAL = "internal"
    END = "end"


_FAMILY_ID_MAP: Final[Mapping[SessionProcessFamilyKind, str]] = {
    SessionProcessFamilyKind.LINEAR: LINEAR_FAMILY_ID,
    SessionProcessFamilyKind.SESSION: SESSION_FAMILY_ID,
    SessionProcessFamilyKind.PROCESS: PROCESS_FAMILY_ID,
    SessionProcessFamilyKind.RELATIONAL_REFINEMENT: REFINEMENT_FAMILY_ID,
}

_DIRECTION_TO_SIM: Final[Mapping[RefinementDirectionKind, str]] = {
    RefinementDirectionKind.FORWARD: SimulationDirection.FORWARD.value,
    RefinementDirectionKind.BACKWARD: SimulationDirection.BACKWARD.value,
    RefinementDirectionKind.BISEIMULATION: "bisimulation",
    RefinementDirectionKind.NONE: "none",
}


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    REFINEMENT = 5
    PROCESS = 10
    LOLLI = 20
    TENSOR = 30
    WITH = 40
    PLUS = 50
    UNARY = 60
    ATOM = 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_name(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SyntaxContractError(f"{label} is required")
    if "\x00" in text:
        raise SyntaxContractError(f"{label} must not contain NUL")
    return text


def _coerce_enum(enum_cls: type[Enum], value: object, label: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as error:
        raise SyntaxContractError(f"unknown {label} {value!r}") from error


def _surface_polarity_to_ir(polarity: str) -> SessionPolarity:
    mapping = {
        "send": SessionPolarity.SEND,
        "!": SessionPolarity.SEND,
        "receive": SessionPolarity.RECEIVE,
        "recv": SessionPolarity.RECEIVE,
        "?": SessionPolarity.RECEIVE,
        "internal": SessionPolarity.INTERNAL,
        "tau": SessionPolarity.INTERNAL,
        "end": SessionPolarity.END,
    }
    key = polarity.casefold()
    if key not in mapping:
        raise SyntaxContractError(f"unknown session polarity {polarity!r}")
    return mapping[key]


def _dual_surface_polarity(polarity: str) -> str:
    ir = dual_polarity(_surface_polarity_to_ir(polarity))
    if ir is SessionPolarity.SEND:
        return SessionPolaritySurface.SEND.value
    if ir is SessionPolarity.RECEIVE:
        return SessionPolaritySurface.RECEIVE.value
    if ir is SessionPolarity.INTERNAL:
        return SessionPolaritySurface.INTERNAL.value
    return SessionPolaritySurface.END.value


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionProcessLogicProfile:
    """Named linear / session / process / relational-refinement profile.

    Interface: ``SessionProcessLogicProfile@1`` (owned by
    ``SessionProcessLogic@1``).

    Linearity mode, duality admission, progress model, process-scope
    enforcement, and refinement direction are **explicit profile fields** —
    never inferred from operator spelling.
    """

    profile_id: str
    family: SessionProcessFamilyKind | str
    linearity: LinearityMode | str = LinearityMode.STRICT
    progress_model: ProgressModel | str = ProgressModel.NONE
    refinement_direction: RefinementDirectionKind | str = (
        RefinementDirectionKind.FORWARD
    )
    admit_duality: bool = True
    admit_session_actions: bool = True
    admit_process_composition: bool = True
    admit_linear_connectives: bool = True
    admit_refinement: bool = True
    require_progress_model: bool = False
    require_refinement_direction: bool = False
    enforce_process_scope: bool = True
    reject_resource_duplication: bool = True
    schema_version: str = SP_PROFILE_SCHEMA

    interface: ClassVar[str] = SESSION_PROCESS_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            _require_non_empty_name(self.profile_id, "profile_id"),
        )
        family = _coerce_enum(SessionProcessFamilyKind, self.family, "family")
        object.__setattr__(self, "family", family)
        linearity = _coerce_enum(LinearityMode, self.linearity, "linearity")
        object.__setattr__(self, "linearity", linearity)
        progress = _coerce_enum(
            ProgressModel, self.progress_model, "progress_model"
        )
        object.__setattr__(self, "progress_model", progress)
        direction = _coerce_enum(
            RefinementDirectionKind,
            self.refinement_direction,
            "refinement_direction",
        )
        object.__setattr__(self, "refinement_direction", direction)

        for name in (
            "admit_duality",
            "admit_session_actions",
            "admit_process_composition",
            "admit_linear_connectives",
            "admit_refinement",
            "require_progress_model",
            "require_refinement_direction",
            "enforce_process_scope",
            "reject_resource_duplication",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")

        if self.schema_version != SP_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported SessionProcessLogicProfile schema "
                f"{self.schema_version!r}"
            )

        # Family-specific hard requirements (acceptance criteria).
        if family is SessionProcessFamilyKind.LINEAR:
            if not self.admit_linear_connectives:
                raise SyntaxContractError(
                    "linear profiles require admit_linear_connectives=True"
                )
            if linearity is LinearityMode.UNRESTRICTED and self.reject_resource_duplication:
                raise SyntaxContractError(
                    "linear profiles with reject_resource_duplication cannot "
                    "use unrestricted linearity"
                )
        if family is SessionProcessFamilyKind.SESSION:
            if not self.admit_session_actions:
                raise SyntaxContractError(
                    "session profiles require admit_session_actions=True"
                )
            if not self.admit_duality:
                raise SyntaxContractError(
                    "session profiles require admit_duality=True"
                )
        if family is SessionProcessFamilyKind.PROCESS:
            if not self.admit_process_composition:
                raise SyntaxContractError(
                    "process profiles require admit_process_composition=True"
                )
            if self.require_progress_model and progress is ProgressModel.NONE:
                raise SyntaxContractError(
                    "process profiles with require_progress_model=True must "
                    "declare a non-none progress_model"
                )
        if family is SessionProcessFamilyKind.RELATIONAL_REFINEMENT:
            if not self.admit_refinement:
                raise SyntaxContractError(
                    "relational_refinement profiles require admit_refinement=True"
                )
            if (
                self.require_refinement_direction
                and direction is RefinementDirectionKind.NONE
            ):
                raise SyntaxContractError(
                    "relational_refinement profiles with "
                    "require_refinement_direction=True must declare a "
                    "non-none refinement_direction"
                )

    @property
    def family_id(self) -> str:
        family = (
            self.family
            if isinstance(self.family, SessionProcessFamilyKind)
            else SessionProcessFamilyKind(str(self.family))
        )
        return _FAMILY_ID_MAP[family]

    @property
    def family_kind(self) -> SessionProcessFamilyKind:
        return (
            self.family
            if isinstance(self.family, SessionProcessFamilyKind)
            else SessionProcessFamilyKind(str(self.family))
        )

    @property
    def linearity_mode(self) -> LinearityMode:
        return (
            self.linearity
            if isinstance(self.linearity, LinearityMode)
            else LinearityMode(str(self.linearity))
        )

    @property
    def progress_model_kind(self) -> ProgressModel:
        return (
            self.progress_model
            if isinstance(self.progress_model, ProgressModel)
            else ProgressModel(str(self.progress_model))
        )

    @property
    def refinement_direction_kind(self) -> RefinementDirectionKind:
        return (
            self.refinement_direction
            if isinstance(self.refinement_direction, RefinementDirectionKind)
            else RefinementDirectionKind(str(self.refinement_direction))
        )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        """Stable identity fragment for profile-sensitive routing."""

        return {
            "admit_duality": self.admit_duality,
            "admit_linear_connectives": self.admit_linear_connectives,
            "admit_process_composition": self.admit_process_composition,
            "admit_refinement": self.admit_refinement,
            "admit_session_actions": self.admit_session_actions,
            "enforce_process_scope": self.enforce_process_scope,
            "family": self.family_kind.value,
            "family_id": self.family_id,
            "linearity": self.linearity_mode.value,
            "profile_id": self.profile_id,
            "progress_model": self.progress_model_kind.value,
            "refinement_direction": self.refinement_direction_kind.value,
            "reject_resource_duplication": self.reject_resource_duplication,
            "require_progress_model": self.require_progress_model,
            "require_refinement_direction": self.require_refinement_direction,
            "schema_version": self.schema_version,
            "silent_resource_duplication_normalized": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_identity,
            "interface": self.interface,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SessionProcessLogicProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError(
                "SessionProcessLogicProfile must be a mapping"
            )
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            family=value.get("family", SessionProcessFamilyKind.SESSION.value),
            linearity=value.get("linearity", LinearityMode.STRICT.value),
            progress_model=value.get(
                "progress_model", ProgressModel.NONE.value
            ),
            refinement_direction=value.get(
                "refinement_direction",
                RefinementDirectionKind.FORWARD.value,
            ),
            admit_duality=bool(value.get("admit_duality", True)),
            admit_session_actions=bool(value.get("admit_session_actions", True)),
            admit_process_composition=bool(
                value.get("admit_process_composition", True)
            ),
            admit_linear_connectives=bool(
                value.get("admit_linear_connectives", True)
            ),
            admit_refinement=bool(value.get("admit_refinement", True)),
            require_progress_model=bool(
                value.get("require_progress_model", False)
            ),
            require_refinement_direction=bool(
                value.get("require_refinement_direction", False)
            ),
            enforce_process_scope=bool(
                value.get("enforce_process_scope", True)
            ),
            reject_resource_duplication=bool(
                value.get("reject_resource_duplication", True)
            ),
            schema_version=str(
                value.get("schema_version") or SP_PROFILE_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Profile factories
# ---------------------------------------------------------------------------


def profile_linear(
    *,
    profile_id: str = "linear_default",
    linearity: LinearityMode | str = LinearityMode.STRICT,
    reject_resource_duplication: bool = True,
) -> SessionProcessLogicProfile:
    """Strict linear-logic resource profile."""

    return SessionProcessLogicProfile(
        profile_id=profile_id,
        family=SessionProcessFamilyKind.LINEAR,
        linearity=linearity,
        progress_model=ProgressModel.NONE,
        refinement_direction=RefinementDirectionKind.NONE,
        admit_duality=False,
        admit_session_actions=False,
        admit_process_composition=False,
        admit_linear_connectives=True,
        admit_refinement=False,
        require_progress_model=False,
        require_refinement_direction=False,
        enforce_process_scope=False,
        reject_resource_duplication=reject_resource_duplication,
    )


def profile_session(
    *,
    profile_id: str = "session_default",
    progress_model: ProgressModel | str = ProgressModel.NONE,
    admit_duality: bool = True,
) -> SessionProcessLogicProfile:
    """Session-type profile with duality."""

    return SessionProcessLogicProfile(
        profile_id=profile_id,
        family=SessionProcessFamilyKind.SESSION,
        linearity=LinearityMode.STRICT,
        progress_model=progress_model,
        refinement_direction=RefinementDirectionKind.NONE,
        admit_duality=admit_duality,
        admit_session_actions=True,
        admit_process_composition=False,
        admit_linear_connectives=False,
        admit_refinement=False,
        require_progress_model=False,
        require_refinement_direction=False,
        enforce_process_scope=True,
        reject_resource_duplication=True,
    )


def profile_process(
    *,
    profile_id: str = "process_default",
    progress_model: ProgressModel | str = ProgressModel.FAIR,
    require_progress_model: bool = True,
    enforce_process_scope: bool = True,
) -> SessionProcessLogicProfile:
    """Process-calculus profile with explicit progress model."""

    return SessionProcessLogicProfile(
        profile_id=profile_id,
        family=SessionProcessFamilyKind.PROCESS,
        linearity=LinearityMode.AFFINE,
        progress_model=progress_model,
        refinement_direction=RefinementDirectionKind.NONE,
        admit_duality=True,
        admit_session_actions=True,
        admit_process_composition=True,
        admit_linear_connectives=False,
        admit_refinement=False,
        require_progress_model=require_progress_model,
        require_refinement_direction=False,
        enforce_process_scope=enforce_process_scope,
        reject_resource_duplication=True,
    )


def profile_relational_refinement(
    *,
    profile_id: str = "relational_refinement_default",
    refinement_direction: RefinementDirectionKind | str = (
        RefinementDirectionKind.FORWARD
    ),
    require_refinement_direction: bool = True,
) -> SessionProcessLogicProfile:
    """Relational refinement / simulation profile with explicit direction."""

    return SessionProcessLogicProfile(
        profile_id=profile_id,
        family=SessionProcessFamilyKind.RELATIONAL_REFINEMENT,
        linearity=LinearityMode.UNRESTRICTED,
        progress_model=ProgressModel.NONE,
        refinement_direction=refinement_direction,
        admit_duality=False,
        admit_session_actions=False,
        admit_process_composition=False,
        admit_linear_connectives=False,
        admit_refinement=True,
        require_progress_model=False,
        require_refinement_direction=require_refinement_direction,
        enforce_process_scope=False,
        reject_resource_duplication=False,
    )


def session_process_semantic_identity(
    profile: SessionProcessLogicProfile,
) -> dict[str, Any]:
    """Public semantic-identity helper for routing / evidence."""

    return dict(profile.semantic_identity)


# ---------------------------------------------------------------------------
# Check reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinearityReport:
    """Result of a linearity / resource-duplication check."""

    ok: bool
    mode: str
    resource_counts: Mapping[str, int] = field(default_factory=dict)
    duplicated: tuple[str, ...] = ()
    unused: tuple[str, ...] = ()
    message: str = ""
    silently_normalized: bool = False
    schema_version: str = SP_LINEARITY_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "duplicated": list(self.duplicated),
            "message": self.message,
            "mode": self.mode,
            "ok": self.ok,
            "resource_counts": dict(self.resource_counts),
            "schema_version": self.schema_version,
            "silently_normalized": self.silently_normalized,
            "unused": list(self.unused),
        }


@dataclass(frozen=True, slots=True)
class DualityReport:
    """Result of a session duality check."""

    ok: bool
    involutive: bool = False
    polarity_flipped: bool = False
    role_dual: bool = False
    message: str = ""
    schema_version: str = SP_DUALITY_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "involutive": self.involutive,
            "message": self.message,
            "ok": self.ok,
            "polarity_flipped": self.polarity_flipped,
            "role_dual": self.role_dual,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProcessScopeReport:
    """Result of a process-scope / free-channel check."""

    ok: bool
    free_channels: tuple[str, ...] = ()
    bound_channels: tuple[str, ...] = ()
    message: str = ""
    schema_version: str = SP_SCOPE_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_channels": list(self.bound_channels),
            "free_channels": list(self.free_channels),
            "message": self.message,
            "ok": self.ok,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProgressReport:
    """Result of a progress-model check."""

    ok: bool
    profile_model: str
    surface_models: tuple[str, ...] = ()
    message: str = ""
    schema_version: str = SP_PROGRESS_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "ok": self.ok,
            "profile_model": self.profile_model,
            "schema_version": self.schema_version,
            "surface_models": list(self.surface_models),
        }


@dataclass(frozen=True, slots=True)
class RefinementDirectionReport:
    """Result of a refinement-direction check."""

    ok: bool
    profile_direction: str
    surface_directions: tuple[str, ...] = ()
    message: str = ""
    schema_version: str = SP_REFINEMENT_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "ok": self.ok,
            "profile_direction": self.profile_direction,
            "schema_version": self.schema_version,
            "surface_directions": list(self.surface_directions),
        }


# ---------------------------------------------------------------------------
# AST walkers / semantic checks
# ---------------------------------------------------------------------------


def _payload_kind(node: LogicNode) -> str:
    if node.kind is NodeKind.EXTENSION and node.extension is not None:
        return str(node.extension.payload.get("kind") or "")
    return ""


def _payload(node: LogicNode) -> dict[str, Any]:
    if node.kind is NodeKind.EXTENSION and node.extension is not None:
        return dict(node.extension.payload)
    return {}


def _children(node: LogicNode) -> tuple[LogicNode, ...]:
    if node.kind is NodeKind.EXTENSION and node.extension is not None:
        return tuple(node.extension.children)
    return tuple(node.arguments)


def collect_resource_names(node: LogicNode) -> list[str]:
    """Collect resource atom names in left-to-right order (no de-duplication)."""

    names: list[str] = []

    def walk(n: LogicNode) -> None:
        kind = _payload_kind(n)
        if kind == "resource":
            name = str(_payload(n).get("name") or "")
            if name:
                names.append(name)
            return
        # Preserve multiplicity: walk children only once.  Duplicates are
        # reported rather than silently normalized.
        seen_ids: set[int] = set()
        for child in _children(n):
            seen_ids.add(id(child))
            walk(child)
        for arg in n.arguments:
            if id(arg) not in seen_ids:
                walk(arg)

    walk(node)
    return names


def check_linearity(
    node: LogicNode,
    profile: SessionProcessLogicProfile,
) -> LinearityReport:
    """Check resource linearity; never silently normalize duplicates.

    Under ``reject_resource_duplication`` / strict or relevant modes, any
    resource name that appears more than once fails closed.  Counts preserve
    multiplicity — duplicates are reported, not collapsed.
    """

    names = collect_resource_names(node)
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1

    mode = profile.linearity_mode
    duplicated = tuple(sorted(n for n, c in counts.items() if c > 1))
    # "unused" is reserved for contexts with declared environments; surface
    # formulas alone do not declare an environment, so unused is empty here.
    unused: tuple[str, ...] = ()

    if not profile.reject_resource_duplication or mode is LinearityMode.UNRESTRICTED:
        return LinearityReport(
            ok=True,
            mode=mode.value,
            resource_counts=counts,
            duplicated=duplicated,
            unused=unused,
            message="linearity not enforced under this profile",
            silently_normalized=False,
        )

    if duplicated:
        return LinearityReport(
            ok=False,
            mode=mode.value,
            resource_counts=counts,
            duplicated=duplicated,
            unused=unused,
            message=(
                "resource duplication is not silently normalized; "
                f"duplicated resources: {', '.join(duplicated)}"
            ),
            silently_normalized=False,
        )

    if mode is LinearityMode.STRICT and not counts and _has_linear_connective(node):
        # Strict linear formulas with connectives but no resources are ok
        # (e.g. pure atoms under lolli).
        pass

    return LinearityReport(
        ok=True,
        mode=mode.value,
        resource_counts=counts,
        duplicated=(),
        unused=unused,
        message="linearity ok",
        silently_normalized=False,
    )


def _has_linear_connective(node: LogicNode) -> bool:
    kind = _payload_kind(node)
    if kind in {"tensor", "lolli", "with", "plus", "ofcourse", "resource"}:
        return True
    return any(_has_linear_connective(c) for c in _children(node))


def collect_session_spine(
    node: LogicNode,
) -> list[dict[str, Any]]:
    """Extract ordered session action payloads (send/recv/tau/end)."""

    actions: list[dict[str, Any]] = []

    def walk(n: LogicNode) -> None:
        kind = _payload_kind(n)
        payload = _payload(n)
        if kind == "dual":
            # Expand dual by walking dualized children.
            for child in _children(n):
                dualized = dualize_session_ast(child)
                walk(dualized)
            return
        if kind == "session_action":
            actions.append(dict(payload))
            for child in _children(n):
                walk(child)
            return
        if kind == "end":
            actions.append({"kind": "end", "polarity": "end", "label": "end"})
            return
        for child in _children(n):
            walk(child)

    walk(node)
    return actions


def dualize_session_ast(node: LogicNode) -> LogicNode:
    """Structurally dualize a session AST (send↔receive; dual cancels).

    Involution laws:

    * ``dualize(dualize(P)) = P`` for session spines
    * ``dualize(dual(P)) = P`` (syntactic dual constructor cancels)
    * expand ``dual(P)`` for action spines via ``dualize(P)`` separately
    """

    kind = _payload_kind(node)
    payload = _payload(node)
    family = (
        node.extension.family
        if node.extension is not None
        else SESSION_FAMILY_ID
    )
    profile = (
        node.extension.profile
        if node.extension is not None
        else "session"
    )
    features = (
        tuple(node.extension.features)
        if node.extension is not None
        else ("session.duality",)
    )

    if kind == "dual":
        # Cancel the dual constructor without dualizing the body first so
        # dualize(dual(P)) = P (involution / constructor cancel).
        children = _children(node)
        if not children:
            return node
        return children[0]

    children = tuple(dualize_session_ast(c) for c in _children(node))

    if kind == "session_action":
        polarity = str(payload.get("polarity") or "")
        new_polarity = _dual_surface_polarity(polarity)
        surface = "!" if new_polarity == "send" else "?"
        if new_polarity == "internal":
            surface = "tau"
        new_payload = {
            **payload,
            "polarity": new_polarity,
            "surface": surface,
        }
        return mk_extension(
            f"{node.node_id}:dual",
            family=family,
            profile=profile,
            features=features,
            payload_schema=SP_SESSION_ACTION_PAYLOAD_SCHEMA,
            payload=new_payload,
            children=children,
            range=node.range,
        )

    if kind == "end":
        return node

    if node.kind is NodeKind.EXTENSION and node.extension is not None:
        return mk_extension(
            f"{node.node_id}:dual",
            family=family,
            profile=profile,
            features=features,
            payload_schema=node.extension.payload_schema,
            payload=dict(payload),
            children=children,
            range=node.range,
        )
    return node


def check_duality(
    node: LogicNode,
    profile: SessionProcessLogicProfile | None = None,
    *,
    role: SessionRole | str = SessionRole.CLIENT,
) -> DualityReport:
    """Validate session duality: polarity flip and dual(dual(P)) involution."""

    if profile is not None and not profile.admit_duality:
        return DualityReport(
            ok=False,
            message="session duality is not admitted by the active profile",
        )

    original = collect_session_spine(node)
    if not original:
        # No session spine — duality vacuously ok when no session content.
        return DualityReport(
            ok=True,
            involutive=True,
            polarity_flipped=True,
            role_dual=True,
            message="no session spine; duality vacuous",
        )

    dual_once = dualize_session_ast(node)
    dual_spine = collect_session_spine(dual_once)
    dual_twice = dualize_session_ast(dual_once)
    twice_spine = collect_session_spine(dual_twice)

    if len(original) != len(dual_spine):
        return DualityReport(
            ok=False,
            message=(
                f"dual action count mismatch: {len(original)} vs {len(dual_spine)}"
            ),
        )

    polarity_ok = True
    for orig, dual in zip(original, dual_spine):
        op = str(orig.get("polarity") or "")
        dp = str(dual.get("polarity") or "")
        expected = _dual_surface_polarity(op)
        if dp != expected:
            polarity_ok = False
            break
        if str(orig.get("label") or "") != str(dual.get("label") or ""):
            polarity_ok = False
            break

    orig_key = tuple(
        (str(a.get("polarity")), str(a.get("label") or "")) for a in original
    )
    twice_key = tuple(
        (str(a.get("polarity")), str(a.get("label") or "")) for a in twice_spine
    )
    involutive = orig_key == twice_key

    role_value = role if isinstance(role, SessionRole) else SessionRole(str(role))
    dual_r = dual_role(role_value)
    role_ok = dual_role(dual_r) is role_value

    ok = polarity_ok and involutive and role_ok
    message = "duality ok" if ok else "session duality invalid"
    if not polarity_ok:
        message = "session dual polarity mismatch"
    elif not involutive:
        message = "session dual is not involutive"
    elif not role_ok:
        message = "session dual role is not involutive"

    return DualityReport(
        ok=ok,
        involutive=involutive,
        polarity_flipped=polarity_ok,
        role_dual=role_ok,
        message=message,
    )


def collect_free_channels(
    node: LogicNode,
    bound: frozenset[str] | None = None,
) -> frozenset[str]:
    """Collect free channel names under process/session scope."""

    bound_set = bound if bound is not None else frozenset()
    free: set[str] = set()

    def walk(n: LogicNode, bound_now: frozenset[str]) -> None:
        kind = _payload_kind(n)
        payload = _payload(n)
        if kind == "new":
            name = str(payload.get("name") or "")
            inner = bound_now | ({name} if name else frozenset())
            for child in _children(n):
                walk(child, inner)
            return
        if kind == "session_action":
            # label is a message label, not a channel binder; channel may be
            # carried as optional payload field.
            channel = str(payload.get("channel") or "")
            if channel and channel not in bound_now:
                free.add(channel)
            for child in _children(n):
                walk(child, bound_now)
            return
        if kind == "channel_ref":
            name = str(payload.get("name") or "")
            if name and name not in bound_now:
                free.add(name)
            return
        if kind == "par":
            for child in _children(n):
                walk(child, bound_now)
            return
        if kind in {"resource", "progress", "refines", "simulates", "end", "nil"}:
            return
        if kind == "two_state":
            # state binders, not channels
            for child in _children(n):
                walk(child, bound_now)
            return
        for child in _children(n):
            walk(child, bound_now)
        for arg in n.arguments:
            if arg not in _children(n):
                walk(arg, bound_now)

    walk(node, bound_set)
    return frozenset(free)


def collect_bound_channels(node: LogicNode) -> frozenset[str]:
    """Collect channel names bound by ``new`` / ``restrict``."""

    bound: set[str] = set()

    def walk(n: LogicNode) -> None:
        kind = _payload_kind(n)
        if kind == "new":
            name = str(_payload(n).get("name") or "")
            if name:
                bound.add(name)
        for child in _children(n):
            walk(child)

    walk(node)
    return frozenset(bound)


def check_process_scope(
    node: LogicNode,
    profile: SessionProcessLogicProfile,
) -> ProcessScopeReport:
    """Fail closed when free channels escape process scope under enforcement."""

    free = tuple(sorted(collect_free_channels(node)))
    bound = tuple(sorted(collect_bound_channels(node)))

    if not profile.enforce_process_scope:
        return ProcessScopeReport(
            ok=True,
            free_channels=free,
            bound_channels=bound,
            message="process scope not enforced under this profile",
        )

    if free:
        return ProcessScopeReport(
            ok=False,
            free_channels=free,
            bound_channels=bound,
            message=(
                "free channels outside process scope: "
                f"{', '.join(free)}"
            ),
        )
    return ProcessScopeReport(
        ok=True,
        free_channels=(),
        bound_channels=bound,
        message="process scope ok",
    )


def collect_progress_models(node: LogicNode) -> tuple[str, ...]:
    """Collect surface progress-model atoms."""

    models: list[str] = []

    def walk(n: LogicNode) -> None:
        if _payload_kind(n) == "progress":
            model = str(_payload(n).get("model") or "")
            if model:
                models.append(model)
        for child in _children(n):
            walk(child)

    walk(node)
    return tuple(models)


def check_progress_model(
    node: LogicNode,
    profile: SessionProcessLogicProfile,
) -> ProgressReport:
    """Ensure progress model is explicit and consistent when required."""

    surface = collect_progress_models(node)
    profile_model = profile.progress_model_kind.value

    if profile.require_progress_model:
        if profile.progress_model_kind is ProgressModel.NONE:
            return ProgressReport(
                ok=False,
                profile_model=profile_model,
                surface_models=surface,
                message="progress model is required but profile declares none",
            )
        if not surface and profile.family_kind is SessionProcessFamilyKind.PROCESS:
            # Process profiles may rely on the profile-level model when no
            # surface atom is present — profile declaration counts as explicit.
            return ProgressReport(
                ok=True,
                profile_model=profile_model,
                surface_models=surface,
                message="progress model supplied by profile",
            )
        mismatched = tuple(m for m in surface if m != profile_model)
        if mismatched:
            return ProgressReport(
                ok=False,
                profile_model=profile_model,
                surface_models=surface,
                message=(
                    f"surface progress model(s) {mismatched} disagree with "
                    f"profile progress_model {profile_model!r}"
                ),
            )
        return ProgressReport(
            ok=True,
            profile_model=profile_model,
            surface_models=surface,
            message="progress model ok",
        )

    # Not required — still reject contradictory surface atoms against profile
    # when a non-none profile model is declared.
    if (
        profile.progress_model_kind is not ProgressModel.NONE
        and surface
    ):
        mismatched = tuple(m for m in surface if m != profile_model)
        if mismatched:
            return ProgressReport(
                ok=False,
                profile_model=profile_model,
                surface_models=surface,
                message=(
                    f"surface progress model(s) {mismatched} disagree with "
                    f"profile progress_model {profile_model!r}"
                ),
            )

    return ProgressReport(
        ok=True,
        profile_model=profile_model,
        surface_models=surface,
        message="progress model check ok",
    )


def collect_refinement_directions(node: LogicNode) -> tuple[str, ...]:
    """Collect refinement/simulation directions from surface AST."""

    directions: list[str] = []

    def walk(n: LogicNode) -> None:
        kind = _payload_kind(n)
        if kind in {"refines", "simulates"}:
            direction = str(_payload(n).get("direction") or "")
            if direction:
                directions.append(direction)
        for child in _children(n):
            walk(child)

    walk(node)
    return tuple(directions)


def check_refinement_direction(
    node: LogicNode,
    profile: SessionProcessLogicProfile,
) -> RefinementDirectionReport:
    """Ensure refinement direction is explicit when the profile requires it."""

    surface = collect_refinement_directions(node)
    profile_dir = profile.refinement_direction_kind.value

    if profile.require_refinement_direction:
        if profile.refinement_direction_kind is RefinementDirectionKind.NONE:
            return RefinementDirectionReport(
                ok=False,
                profile_direction=profile_dir,
                surface_directions=surface,
                message=(
                    "refinement direction is required but profile declares none"
                ),
            )
        if not surface:
            # Profile-level direction counts as explicit for empty formulas,
            # but refinement obligations themselves must carry direction.
            has_refinement = _has_refinement_construct(node)
            if has_refinement:
                return RefinementDirectionReport(
                    ok=False,
                    profile_direction=profile_dir,
                    surface_directions=surface,
                    message=(
                        "refinement/simulation construct missing explicit direction"
                    ),
                )
            return RefinementDirectionReport(
                ok=True,
                profile_direction=profile_dir,
                surface_directions=surface,
                message="refinement direction supplied by profile",
            )
        missing = tuple(d for d in surface if not d or d == "none")
        if missing:
            return RefinementDirectionReport(
                ok=False,
                profile_direction=profile_dir,
                surface_directions=surface,
                message="refinement direction must not be empty or none",
            )
        mismatched = tuple(
            d
            for d in surface
            if d != profile_dir and profile_dir != "none"
        )
        # Surface may state a direction; profile default should agree when set.
        if mismatched and profile.refinement_direction_kind not in {
            RefinementDirectionKind.NONE,
            RefinementDirectionKind.BISEIMULATION,
        }:
            # Allow surface direction to be the authority when present and
            # profile default is only a default — still report mismatch as
            # fail-closed for explicit profile direction enforcement.
            return RefinementDirectionReport(
                ok=False,
                profile_direction=profile_dir,
                surface_directions=surface,
                message=(
                    f"surface refinement direction(s) {mismatched} disagree "
                    f"with profile refinement_direction {profile_dir!r}"
                ),
            )
        return RefinementDirectionReport(
            ok=True,
            profile_direction=profile_dir,
            surface_directions=surface,
            message="refinement direction ok",
        )

    return RefinementDirectionReport(
        ok=True,
        profile_direction=profile_dir,
        surface_directions=surface,
        message="refinement direction not required",
    )


def _has_refinement_construct(node: LogicNode) -> bool:
    kind = _payload_kind(node)
    if kind in {"refines", "simulates", "two_state"}:
        return True
    return any(_has_refinement_construct(c) for c in _children(node))


def run_profile_checks(
    node: LogicNode,
    profile: SessionProcessLogicProfile,
) -> tuple[
    LinearityReport,
    DualityReport,
    ProcessScopeReport,
    ProgressReport,
    RefinementDirectionReport,
    list[SyntaxDiagnostic],
]:
    """Run all acceptance checks; return reports and diagnostics."""

    diags: list[SyntaxDiagnostic] = []
    linearity = check_linearity(node, profile)
    if not linearity.ok:
        diags.append(
            _diag(
                code=CODE_RESOURCE_DUPLICATION
                if linearity.duplicated
                else CODE_LINEARITY,
                message=linearity.message,
                range=node.range,
                metadata={"report": linearity.to_dict()},
            )
        )

    duality = DualityReport(ok=True, message="duality not applicable")
    if profile.admit_duality and (
        profile.family_kind
        in {SessionProcessFamilyKind.SESSION, SessionProcessFamilyKind.PROCESS}
        or _has_session_construct(node)
    ):
        duality = check_duality(node, profile)
        if not duality.ok and _has_session_construct(node):
            diags.append(
                _diag(
                    code=CODE_DUALITY,
                    message=duality.message,
                    range=node.range,
                    metadata={"report": duality.to_dict()},
                )
            )

    scope = check_process_scope(node, profile)
    if not scope.ok:
        diags.append(
            _diag(
                code=CODE_PROCESS_SCOPE
                if scope.free_channels
                else CODE_FREE_CHANNEL,
                message=scope.message,
                range=node.range,
                metadata={"report": scope.to_dict()},
            )
        )

    progress = check_progress_model(node, profile)
    if not progress.ok:
        code = (
            CODE_PROGRESS_REQUIRED
            if "required" in progress.message
            else CODE_PROGRESS_MISMATCH
        )
        diags.append(
            _diag(
                code=code,
                message=progress.message,
                range=node.range,
                metadata={"report": progress.to_dict()},
            )
        )

    refinement = check_refinement_direction(node, profile)
    if not refinement.ok:
        code = (
            CODE_REFINEMENT_DIRECTION
            if "required" in refinement.message or "missing" in refinement.message
            else CODE_REFINEMENT_DIRECTION_MISMATCH
        )
        diags.append(
            _diag(
                code=code,
                message=refinement.message,
                range=node.range,
                metadata={"report": refinement.to_dict()},
            )
        )

    return linearity, duality, scope, progress, refinement, diags


def _has_session_construct(node: LogicNode) -> bool:
    kind = _payload_kind(node)
    if kind in {"session_action", "end", "dual"}:
        return True
    return any(_has_session_construct(c) for c in _children(node))


# ---------------------------------------------------------------------------
# Parse result / errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionProcessParseResult:
    """Typed result of a session/process parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: SessionProcessLogicProfile | None = None
    linearity: LinearityReport | None = None
    duality: DualityReport | None = None
    process_scope: ProcessScopeReport | None = None
    progress: ProgressReport | None = None
    refinement_direction: RefinementDirectionReport | None = None
    schema_version: str = SP_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = SESSION_PROCESS_LOGIC_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "duality": self.duality.to_dict() if self.duality else None,
            "interface": self.interface,
            "linearity": self.linearity.to_dict() if self.linearity else None,
            "printed": self.printed,
            "process_scope": (
                self.process_scope.to_dict() if self.process_scope else None
            ),
            "profile": self.profile.to_dict() if self.profile else None,
            "progress": self.progress.to_dict() if self.progress else None,
            "refinement_direction": (
                self.refinement_direction.to_dict()
                if self.refinement_direction
                else None
            ),
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, ParseStatus)
            else str(self.status),
        }


class SessionProcessParseError(SyntaxContractError):
    """Raised by raising helpers when a session/process parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: SessionProcessParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Diagnostics / cursor
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


_DIAG_SEQ: list[int] = [0]


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    _DIAG_SEQ[0] += 1
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:sp:{code.replace('.', '-')}:{_DIAG_SEQ[0]}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


class _Cursor:
    def __init__(
        self,
        tokens: Sequence[LogicToken],
        document: SourceDocument,
    ) -> None:
        self.tokens = tuple(tokens)
        self.document = document
        self.index = 0
        self.depth = 0

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> LogicToken:
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def is_eof(self) -> bool:
        return self.current().kind == TokenKind.EOF.value

    def advance(self) -> LogicToken:
        token = self.current()
        if not self.is_eof():
            self.index += 1
        return token

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = {item.casefold() for item in lexemes}
        if token.lexeme in lexemes or token.lexeme.casefold() in folded:
            return self.advance()
        return None

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        return self.match_any(frozenset(lexemes))

    def expect_lexeme(
        self, *lexemes: str, code: str = CODE_UNEXPECTED_TOKEN
    ) -> LogicToken:
        token = self.match_lexeme(*lexemes)
        if token is not None:
            return token
        current = self.current()
        expected = " or ".join(repr(item) for item in lexemes)
        raise _ParseFail(
            _diag(
                code=code,
                message=f"expected {expected}; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def expect_ident(self) -> LogicToken:
        token = self.current()
        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            return self.advance()
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected identifier; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def range_span(self, start: SourceRange, end: SourceRange) -> SourceRange:
        if (
            start.start_char is not None
            and start.end_char is not None
            and end.start_char is not None
            and end.end_char is not None
        ):
            return SourceRange(
                start=start.start,
                end=end.end,
                start_char=start.start_char,
                end_char=end.end_char,
            )
        return SourceRange(start=start.start, end=end.end)


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class SessionProcessPrinter:
    """Deterministic printer for linear/session/process/refinement ASTs."""

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
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, parent_prec)
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            return str(node.symbol or "atom")
        raise SyntaxContractError(
            f"cannot print node kind "
            f"{kind.value if isinstance(kind, NodeKind) else kind}"
        )

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        ext = node.extension
        if ext is None:
            raise SyntaxContractError("EXTENSION node missing extension payload")
        payload = dict(ext.payload)
        kind = str(payload.get("kind") or "")
        children = tuple(ext.children)

        if kind == "resource":
            return f"resource({payload['name']})"
        if kind == "channel_ref":
            return f"chan({payload['name']})"
        if kind == "progress":
            return f"progress({payload['model']})"
        if kind == "nil":
            return "nil"
        if kind == "end":
            return "end"
        if kind == "tensor":
            left = self._print_node(children[0], _Prec.TENSOR)
            right = self._print_node(children[1], _Prec.TENSOR)
            text = f"{left} {self._op('*', '⊗')} {right}"
            return f"({text})" if parent_prec > _Prec.TENSOR else text
        if kind == "lolli":
            left = self._print_node(children[0], _Prec.LOLLI + 1)
            right = self._print_node(children[1], _Prec.LOLLI)
            text = f"{left} {self._op('-o', '⊸')} {right}"
            return f"({text})" if parent_prec > _Prec.LOLLI else text
        if kind == "with":
            left = self._print_node(children[0], _Prec.WITH)
            right = self._print_node(children[1], _Prec.WITH)
            text = f"{left} with {right}"
            return f"({text})" if parent_prec > _Prec.WITH else text
        if kind == "plus":
            left = self._print_node(children[0], _Prec.PLUS)
            right = self._print_node(children[1], _Prec.PLUS)
            text = f"{left} plus {right}"
            return f"({text})" if parent_prec > _Prec.PLUS else text
        if kind == "ofcourse":
            inner = self._print_node(children[0], _Prec.UNARY)
            return f"!{inner}"
        if kind == "session_action":
            polarity = str(payload.get("polarity") or "")
            label = str(payload.get("label") or "")
            payload_sort = str(payload.get("payload_sort") or "")
            cont = (
                self._print_node(children[0], _Prec.BOTTOM) if children else "end"
            )
            if polarity == "internal":
                return f"tau. {cont}"
            surface = "!" if polarity == "send" else "?"
            sort_part = f"({payload_sort})" if payload_sort else ""
            return f"{surface}{label}{sort_part}. {cont}"
        if kind == "dual":
            inner = self._print_node(children[0], _Prec.BOTTOM) if children else "end"
            return f"dual({inner})"
        if kind == "par":
            left = self._print_node(children[0], _Prec.BOTTOM)
            right = self._print_node(children[1], _Prec.BOTTOM)
            return f"par({left}, {right})"
        if kind == "new":
            name = str(payload.get("name") or "")
            body = self._print_node(children[0], _Prec.BOTTOM) if children else "nil"
            return f"new({name}). {body}"
        if kind == "refines":
            direction = str(payload.get("direction") or "")
            abs_s = str(payload.get("abstract") or "")
            conc = str(payload.get("concrete") or "")
            if direction and direction != "none":
                return f"refines({abs_s}, {conc}, {direction})"
            return f"refines({abs_s}, {conc})"
        if kind == "simulates":
            direction = str(payload.get("direction") or "")
            abs_s = str(payload.get("abstract") or "")
            conc = str(payload.get("concrete") or "")
            if direction and direction != "none":
                return f"simulates({abs_s}, {conc}, {direction})"
            return f"simulates({abs_s}, {conc})"
        if kind == "two_state":
            quant = str(payload.get("quantifier") or "forall_states")
            a = str(payload.get("abstract_state") or "")
            c = str(payload.get("concrete_state") or "")
            body = self._print_node(children[0], _Prec.BOTTOM) if children else "true"
            return f"{quant} {a}, {c}. {body}"
        if kind == "atom":
            return str(payload.get("name") or "atom")
        raise SyntaxContractError(
            f"cannot print unknown session_process kind {kind!r}"
        )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _extract_profile(value: object) -> SessionProcessLogicProfile | None:
    if value is None:
        return None
    if isinstance(value, SessionProcessLogicProfile):
        return value
    if isinstance(value, Mapping):
        return SessionProcessLogicProfile.from_dict(value)
    return None


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:sp:1",
) -> LogicCST:
    children = tuple(
        LogicCSTNode(
            node_id=f"node:{token.token_id}",
            kind=token.kind,
            range=token.range,
            role=CSTNodeRole.TOKEN,
            token_id=token.token_id,
        )
        for token in tokens
        if token.kind != TokenKind.EOF.value
    )
    covered = [token.range for token in tokens if token.kind != TokenKind.EOF.value]
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
        cst_id=cst_id,
        document_id=document.document_id,
        root=root,
        source_length=document.byte_length,
    )


def _surface_from_node(node: LogicNode) -> list[SurfaceASTRef]:
    refs: list[SurfaceASTRef] = []
    seq = [0]

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
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
            meta["kind"] = n.extension.payload.get("kind")
        refs.append(
            SurfaceASTRef(
                node_id=node_id,
                kind=safe_kind,
                range=span,
                child_ids=tuple(child_ids),
                metadata=meta,
            )
        )
        return node_id

    walk(node)
    return refs


def _signature_for_profile(profile: SessionProcessLogicProfile) -> LogicSignature:
    return LogicSignature(
        signature_id=f"sig:sp:{profile.profile_id}",
        family=profile.family_id,
        profile=profile.profile_id,
        sorts=(
            BOOL_SORT,
            RESOURCE_SORT,
            CHANNEL_SORT,
            STATE_SORT,
            PROCESS_SORT,
            SESSION_SORT,
        ),
        symbols=(),
        features=(
            "session_process",
            profile.family_kind.value,
            profile.linearity_mode.value,
            profile.progress_model_kind.value,
        ),
        metadata=profile.semantic_identity,
    )


class SessionProcessParser:
    """Parser for linear / session / process / relational refinement surfaces."""

    interface: ClassVar[str] = SESSION_PROCESS_LOGIC_INTERFACE

    def __init__(
        self,
        profile: SessionProcessLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_session()
        self.printer = SessionProcessPrinter(style=print_style)
        self._lexer = BoundedLexer(
            keywords=_SP_KEYWORDS,
            multi_char_operators=(
                "-o",
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
            ),
        )
        self._counter = 0

    def _nid(self, prefix: str) -> str:
        self._counter += 1
        return f"sp:{prefix}:{self._counter}"

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("session_process_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:sp:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: SessionProcessLogicProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:sp:1",
        expression_id: str = "expr:sp:1",
        run_checks: bool = True,
    ) -> SessionProcessParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_REQUIRED,
                message=(
                    "session/process parse requires a named profile; "
                    "use profile_linear(), profile_session(), profile_process(), "
                    "or profile_relational_refinement()"
                ),
                range=document.full_range(),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": SESSION_PROCESS_LOGIC_INTERFACE},
            )
            return SessionProcessParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )
        if not isinstance(prof, SessionProcessLogicProfile):
            raise SyntaxContractError(
                "profile must be a SessionProcessLogicProfile"
            )

        self._counter = 0

        if document.byte_length == 0 or not document.text.strip():
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty session/process input",
                range=document.full_range(),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={
                    "interface": SESSION_PROCESS_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return SessionProcessParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
                profile=prof,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:sp:lex:{index + 1}",
                    code=(
                        CODE_UNKNOWN_CHARACTER
                        if "unknown" in item.code
                        else (
                            CODE_LEXER_ERROR
                            if item.code.startswith("lexer.")
                            else item.code
                        )
                    ),
                    message=item.message,
                    severity=item.severity,
                    range=item.range,
                    remediation=item.remediation
                    or "Unknown characters no longer disappear; fix or remove them",
                    metadata={"lexer_code": item.code},
                )
                for index, item in enumerate(lex_result.diagnostics)
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=promoted,
                metadata={
                    "interface": SESSION_PROCESS_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return SessionProcessParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        diags: list[SyntaxDiagnostic] = list(lex_result.diagnostics)
        cursor = _Cursor(lex_result.tokens, document)
        try:
            root = self._parse_formula(cursor, prof)
            if not cursor.is_eof():
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=(
                            f"trailing input after formula: "
                            f"{cursor.current().lexeme!r}"
                        ),
                        range=cursor.current().range,
                    )
                )
        except _ParseFail as error:
            all_diags = tuple(diags) + (error.diagnostic,)
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": SESSION_PROCESS_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return SessionProcessParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        printed = self.printer.print(root)
        linearity: LinearityReport | None = None
        duality: DualityReport | None = None
        scope: ProcessScopeReport | None = None
        progress: ProgressReport | None = None
        refinement: RefinementDirectionReport | None = None
        check_diags: list[SyntaxDiagnostic] = []

        if run_checks:
            (
                linearity,
                duality,
                scope,
                progress,
                refinement,
                check_diags,
            ) = run_profile_checks(root, prof)

        all_diags = tuple(diags) + tuple(check_diags)
        if check_diags:
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": SESSION_PROCESS_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                    "printed": printed,
                    "linearity": linearity.to_dict() if linearity else None,
                    "duality": duality.to_dict() if duality else None,
                    "process_scope": scope.to_dict() if scope else None,
                    "progress": progress.to_dict() if progress else None,
                    "refinement_direction": (
                        refinement.to_dict() if refinement else None
                    ),
                },
            )
            return SessionProcessParseResult(
                status=ParseStatus.FAILED,
                root=root,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                printed=printed,
                profile=prof,
                linearity=linearity,
                duality=duality,
                process_scope=scope,
                progress=progress,
                refinement_direction=refinement,
            )

        signature = _signature_for_profile(prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=prof.family_id,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        artifact = ParseArtifact(
            artifact_id=f"art:{request_id}",
            request_id=request_id,
            document_id=document.document_id,
            status=ParseStatus.OK,
            tokens=lex_result.tokens,
            cst=cst,
            surface_ast=surface,
            diagnostics=all_diags,
            metadata={
                "interface": SESSION_PROCESS_LOGIC_INTERFACE,
                "profile": prof.to_dict(),
                "printed": printed,
                "linearity": linearity.to_dict() if linearity else None,
                "duality": duality.to_dict() if duality else None,
                "process_scope": scope.to_dict() if scope else None,
                "progress": progress.to_dict() if progress else None,
                "refinement_direction": (
                    refinement.to_dict() if refinement else None
                ),
            },
        )
        return SessionProcessParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            linearity=linearity,
            duality=duality,
            process_scope=scope,
            progress=progress,
            refinement_direction=refinement,
        )

    # -- recursive descent -------------------------------------------------

    def _enter(self, cursor: _Cursor) -> None:
        cursor.depth += 1
        if cursor.depth > 1024:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message="parse depth exceeded",
                    range=cursor.current().range,
                )
            )

    def _leave(self, cursor: _Cursor) -> None:
        cursor.depth = max(0, cursor.depth - 1)

    def _ext(
        self,
        *,
        node_id: str,
        profile: SessionProcessLogicProfile,
        features: Sequence[str],
        payload_schema: str,
        payload: Mapping[str, Any],
        children: Sequence[LogicNode] = (),
        range: SourceRange | None = None,
    ) -> LogicNode:
        return mk_extension(
            node_id,
            family=profile.family_id,
            profile=profile.profile_id,
            features=tuple(features),
            payload_schema=payload_schema,
            payload=dict(payload),
            children=tuple(children),
            range=range,
        )

    def _parse_formula(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        self._enter(cursor)
        try:
            return self._parse_prefix_or_linear(cursor, profile)
        finally:
            self._leave(cursor)

    def _parse_prefix_or_linear(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        """Parse refinement / process / session prefixes, else linear formula."""

        lex = cursor.current().lexeme.casefold()

        # Relational refinement
        if lex in {"refines", "simulates"}:
            return self._parse_refinement(cursor, profile)
        if lex in {"forall_states", "exists_states"}:
            return self._parse_two_state(cursor, profile)

        # Process composition
        if lex == "par":
            return self._parse_par(cursor, profile)
        if lex in {"new", "restrict"}:
            return self._parse_new(cursor, profile)
        if lex == "nil":
            return self._parse_nil(cursor, profile)

        # Session
        if lex == "end":
            return self._parse_end(cursor, profile)
        if lex == "dual":
            return self._parse_dual(cursor, profile)
        if lex == "tau":
            return self._parse_tau(cursor, profile)
        if lex in {"!", "?"}:
            return self._parse_session_action(cursor, profile)

        return self._parse_linear(cursor, profile)

    def _require_admission(
        self,
        profile: SessionProcessLogicProfile,
        *,
        admitted: bool,
        construct: str,
        range: SourceRange,
    ) -> None:
        if not admitted:
            raise _ParseFail(
                _diag(
                    code=CODE_OPERATOR_FORBIDDEN,
                    message=(
                        f"{construct} is not admitted by profile "
                        f"{profile.profile_id!r} "
                        f"(family={profile.family_kind.value})"
                    ),
                    range=range,
                    remediation=(
                        "Select a profile that admits this construct, or "
                        "remove the construct from the surface text"
                    ),
                )
            )

    def _parse_refinement(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_refinement,
            construct=start.lexeme,
            range=start.range,
        )
        kind_tok = cursor.advance()
        kind = kind_tok.lexeme.casefold()
        cursor.expect_lexeme("(")
        abstract = cursor.expect_ident().lexeme
        cursor.expect_lexeme(",")
        concrete = cursor.expect_ident().lexeme
        direction = ""
        if cursor.match_lexeme(",") is not None:
            dir_tok = cursor.expect_ident()
            direction = dir_tok.lexeme.casefold()
            try:
                RefinementDirectionKind(direction)
            except ValueError as error:
                raise _ParseFail(
                    _diag(
                        code=CODE_REFINEMENT_DIRECTION,
                        message=f"unknown refinement direction {direction!r}",
                        range=dir_tok.range,
                    )
                ) from error
        end = cursor.expect_lexeme(")")
        if not direction:
            if profile.require_refinement_direction:
                # Fill from profile default when required — but only if profile
                # has a non-none direction.  Surface remains explicit via
                # printer including the direction on round-trip.
                if (
                    profile.refinement_direction_kind
                    is RefinementDirectionKind.NONE
                ):
                    raise _ParseFail(
                        _diag(
                            code=CODE_REFINEMENT_DIRECTION,
                            message=(
                                f"{kind} requires an explicit direction "
                                f"(forward/backward/bisimulation)"
                            ),
                            range=start.range,
                        )
                    )
                direction = profile.refinement_direction_kind.value
            else:
                direction = profile.refinement_direction_kind.value
                if direction == "none":
                    direction = RefinementDirectionKind.FORWARD.value

        span = cursor.range_span(start.range, end.range)
        schema = (
            SP_REFINES_PAYLOAD_SCHEMA
            if kind == "refines"
            else SP_SIMULATES_PAYLOAD_SCHEMA
        )
        return self._ext(
            node_id=self._nid(kind),
            profile=profile,
            features=(f"session_process.{kind}", "session_process.direction"),
            payload_schema=schema,
            payload={
                "kind": kind,
                "abstract": abstract,
                "concrete": concrete,
                "direction": direction,
                "simulation_direction": _DIRECTION_TO_SIM.get(
                    RefinementDirectionKind(direction),
                    direction,
                ),
            },
            range=span,
        )

    def _parse_two_state(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_refinement,
            construct=start.lexeme,
            range=start.range,
        )
        quant = cursor.advance().lexeme.casefold()
        a = cursor.expect_ident().lexeme
        cursor.expect_lexeme(",")
        c = cursor.expect_ident().lexeme
        cursor.expect_lexeme(".")
        body = self._parse_formula(cursor, profile)
        span = cursor.range_span(
            start.range, body.range or start.range
        )
        return self._ext(
            node_id=self._nid("two_state"),
            profile=profile,
            features=("session_process.two_state",),
            payload_schema=SP_TWO_STATE_PAYLOAD_SCHEMA,
            payload={
                "kind": "two_state",
                "quantifier": quant,
                "abstract_state": a,
                "concrete_state": c,
            },
            children=(body,),
            range=span,
        )

    def _parse_par(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_process_composition,
            construct="par",
            range=start.range,
        )
        cursor.advance()
        cursor.expect_lexeme("(")
        left = self._parse_formula(cursor, profile)
        cursor.expect_lexeme(",")
        right = self._parse_formula(cursor, profile)
        end = cursor.expect_lexeme(")")
        span = cursor.range_span(start.range, end.range)
        return self._ext(
            node_id=self._nid("par"),
            profile=profile,
            features=("session_process.par", "session_process.composition"),
            payload_schema=SP_PAR_PAYLOAD_SCHEMA,
            payload={"kind": "par"},
            children=(left, right),
            range=span,
        )

    def _parse_new(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_process_composition,
            construct=start.lexeme,
            range=start.range,
        )
        cursor.advance()
        cursor.expect_lexeme("(")
        name_tok = cursor.expect_ident()
        cursor.expect_lexeme(")")
        cursor.expect_lexeme(".")
        body = self._parse_formula(cursor, profile)
        span = cursor.range_span(start.range, body.range or start.range)
        return self._ext(
            node_id=self._nid("new"),
            profile=profile,
            features=("session_process.new", "session_process.scope"),
            payload_schema=SP_NEW_PAYLOAD_SCHEMA,
            payload={"kind": "new", "name": name_tok.lexeme},
            children=(body,),
            range=span,
        )

    def _parse_nil(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_process_composition
            or profile.admit_session_actions,
            construct="nil",
            range=start.range,
        )
        tok = cursor.advance()
        return self._ext(
            node_id=self._nid("nil"),
            profile=profile,
            features=("session_process.nil",),
            payload_schema=SP_NIL_PAYLOAD_SCHEMA,
            payload={"kind": "nil"},
            range=tok.range,
        )

    def _parse_end(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_session_actions,
            construct="end",
            range=start.range,
        )
        tok = cursor.advance()
        return self._ext(
            node_id=self._nid("end"),
            profile=profile,
            features=("session_process.end",),
            payload_schema=SP_SESSION_END_PAYLOAD_SCHEMA,
            payload={"kind": "end", "polarity": "end", "label": "end"},
            range=tok.range,
        )

    def _parse_dual(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_duality and profile.admit_session_actions,
            construct="dual",
            range=start.range,
        )
        cursor.advance()
        cursor.expect_lexeme("(")
        body = self._parse_formula(cursor, profile)
        end = cursor.expect_lexeme(")")
        span = cursor.range_span(start.range, end.range)
        return self._ext(
            node_id=self._nid("dual"),
            profile=profile,
            features=("session_process.dual", "session_process.duality"),
            payload_schema=SP_SESSION_DUAL_PAYLOAD_SCHEMA,
            payload={"kind": "dual"},
            children=(body,),
            range=span,
        )

    def _parse_tau(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_session_actions,
            construct="tau",
            range=start.range,
        )
        cursor.advance()
        cursor.expect_lexeme(".")
        cont = self._parse_formula(cursor, profile)
        span = cursor.range_span(start.range, cont.range or start.range)
        return self._ext(
            node_id=self._nid("tau"),
            profile=profile,
            features=("session_process.session_action", "session_process.tau"),
            payload_schema=SP_SESSION_ACTION_PAYLOAD_SCHEMA,
            payload={
                "kind": "session_action",
                "polarity": "internal",
                "surface": "tau",
                "label": "tau",
                "payload_sort": "",
            },
            children=(cont,),
            range=span,
        )

    def _parse_session_action(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_session_actions,
            construct=start.lexeme,
            range=start.range,
        )
        surface_tok = cursor.advance()
        surface = surface_tok.lexeme
        polarity = "send" if surface == "!" else "receive"
        label_tok = cursor.expect_ident()
        payload_sort = ""
        if cursor.match_lexeme("(") is not None:
            sort_tok = cursor.expect_ident()
            payload_sort = sort_tok.lexeme
            cursor.expect_lexeme(")")
        cursor.expect_lexeme(".")
        cont = self._parse_formula(cursor, profile)
        span = cursor.range_span(start.range, cont.range or start.range)
        return self._ext(
            node_id=self._nid("action"),
            profile=profile,
            features=(
                "session_process.session_action",
                f"session_process.{polarity}",
            ),
            payload_schema=SP_SESSION_ACTION_PAYLOAD_SCHEMA,
            payload={
                "kind": "session_action",
                "polarity": polarity,
                "surface": surface,
                "label": label_tok.lexeme,
                "payload_sort": payload_sort,
                "channel": "",
            },
            children=(cont,),
            range=span,
        )

    def _parse_linear(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        return self._parse_lolli(cursor, profile)

    def _parse_lolli(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        left = self._parse_tensor(cursor, profile)
        if cursor.match_any(_LOLLI_OPS) is not None:
            self._require_admission(
                profile,
                admitted=profile.admit_linear_connectives,
                construct="lolli",
                range=cursor.current().range,
            )
            # right-assoc
            right = self._parse_lolli(cursor, profile)
            span = cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            return self._ext(
                node_id=self._nid("lolli"),
                profile=profile,
                features=("session_process.lolli", "session_process.linear"),
                payload_schema=SP_LOLLI_PAYLOAD_SCHEMA,
                payload={"kind": "lolli"},
                children=(left, right),
                range=span,
            )
        return left

    def _parse_tensor(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        left = self._parse_with(cursor, profile)
        while cursor.match_any(_TENSOR_OPS) is not None:
            self._require_admission(
                profile,
                admitted=profile.admit_linear_connectives,
                construct="tensor",
                range=cursor.current().range,
            )
            right = self._parse_with(cursor, profile)
            span = cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = self._ext(
                node_id=self._nid("tensor"),
                profile=profile,
                features=("session_process.tensor", "session_process.linear"),
                payload_schema=SP_TENSOR_PAYLOAD_SCHEMA,
                payload={"kind": "tensor"},
                children=(left, right),
                range=span,
            )
        return left

    def _parse_with(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        left = self._parse_plus(cursor, profile)
        while cursor.match_any(_WITH_OPS) is not None:
            self._require_admission(
                profile,
                admitted=profile.admit_linear_connectives,
                construct="with",
                range=cursor.current().range,
            )
            right = self._parse_plus(cursor, profile)
            span = cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = self._ext(
                node_id=self._nid("with"),
                profile=profile,
                features=("session_process.with", "session_process.linear"),
                payload_schema=SP_WITH_PAYLOAD_SCHEMA,
                payload={"kind": "with"},
                children=(left, right),
                range=span,
            )
        return left

    def _parse_plus(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        left = self._parse_unary(cursor, profile)
        while True:
            # Avoid consuming unary + or ofcourse bang; only keyword/plus op.
            tok = cursor.current()
            if tok.lexeme.casefold() in {"plus"} or tok.lexeme == "+":
                # Disambiguate: '+' before identifier at start of unary is
                # still plus connective when left already parsed.
                cursor.advance()
                self._require_admission(
                    profile,
                    admitted=profile.admit_linear_connectives,
                    construct="plus",
                    range=tok.range,
                )
                right = self._parse_unary(cursor, profile)
                span = cursor.range_span(
                    left.range or SourceRange(0, 0),
                    right.range or SourceRange(0, 0),
                )
                left = self._ext(
                    node_id=self._nid("plus"),
                    profile=profile,
                    features=("session_process.plus", "session_process.linear"),
                    payload_schema=SP_PLUS_PAYLOAD_SCHEMA,
                    payload={"kind": "plus"},
                    children=(left, right),
                    range=span,
                )
            else:
                break
        return left

    def _parse_unary(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        # ofcourse / bang: keyword form or '!' before non-session context.
        # Session '!' is handled in _parse_prefix_or_linear when at formula
        # start; here '!' is ofcourse when followed by a primary.
        if cursor.match_any(_OFCOURSE_OPS) is not None:
            start = cursor.tokens[max(0, cursor.index - 1)]
            self._require_admission(
                profile,
                admitted=profile.admit_linear_connectives,
                construct="ofcourse",
                range=start.range,
            )
            inner = self._parse_unary(cursor, profile)
            return self._ext(
                node_id=self._nid("ofcourse"),
                profile=profile,
                features=("session_process.ofcourse", "session_process.linear"),
                payload_schema=SP_OFCOURSE_PAYLOAD_SCHEMA,
                payload={"kind": "ofcourse"},
                children=(inner,),
                range=cursor.range_span(
                    start.range, inner.range or start.range
                ),
            )

        # '!' as ofcourse when profile is linear and next is not ident for session
        if (
            cursor.current().lexeme == "!"
            and profile.admit_linear_connectives
            and not profile.admit_session_actions
        ):
            start = cursor.advance()
            inner = self._parse_unary(cursor, profile)
            return self._ext(
                node_id=self._nid("ofcourse"),
                profile=profile,
                features=("session_process.ofcourse", "session_process.linear"),
                payload_schema=SP_OFCOURSE_PAYLOAD_SCHEMA,
                payload={"kind": "ofcourse"},
                children=(inner,),
                range=cursor.range_span(
                    start.range, inner.range or start.range
                ),
            )

        return self._parse_atomic(cursor, profile)

    def _parse_atomic(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        tok = cursor.current()
        lex = tok.lexeme.casefold()

        if cursor.match_lexeme("(") is not None:
            inner = self._parse_formula(cursor, profile)
            cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            return inner

        if lex in _TRUE_OPS or tok.lexeme in _TRUE_OPS:
            t = cursor.advance()
            node = mk_true(self._nid("true"))
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=node.sort,
                range=t.range,
            )

        if lex in _FALSE_OPS or tok.lexeme in _FALSE_OPS:
            t = cursor.advance()
            node = mk_false(self._nid("false"))
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=node.sort,
                range=t.range,
            )

        if lex in {"resource", "res"}:
            return self._parse_resource(cursor, profile)

        if lex in {"chan", "channel"}:
            return self._parse_channel_ref(cursor, profile)

        if lex == "dup":
            # Explicit duplication surface — always rejected when profile
            # rejects resource duplication (never silently normalized).
            return self._parse_dup(cursor, profile)

        if lex == "progress":
            return self._parse_progress(cursor, profile)

        # Session/process prefixes that appear after a linear connective.
        if lex == "end" and profile.admit_session_actions:
            return self._parse_end(cursor, profile)
        if lex == "nil" and profile.admit_process_composition:
            return self._parse_nil(cursor, profile)
        if lex == "dual" and profile.admit_duality:
            return self._parse_dual(cursor, profile)
        if lex == "tau" and profile.admit_session_actions:
            return self._parse_tau(cursor, profile)
        if tok.lexeme in {"!", "?"} and profile.admit_session_actions:
            return self._parse_session_action(cursor, profile)
        if lex == "par" and profile.admit_process_composition:
            return self._parse_par(cursor, profile)
        if lex in {"new", "restrict"} and profile.admit_process_composition:
            return self._parse_new(cursor, profile)
        if lex in {"refines", "simulates"} and profile.admit_refinement:
            return self._parse_refinement(cursor, profile)

        # Bare identifier atom.
        if tok.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            name_tok = cursor.advance()
            return self._ext(
                node_id=self._nid("atom"),
                profile=profile,
                features=("session_process.atom",),
                payload_schema=SP_ATOM_PAYLOAD_SCHEMA,
                payload={"kind": "atom", "name": name_tok.lexeme},
                range=name_tok.range,
            )

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"unexpected token {tok.lexeme!r}",
                range=tok.range,
            )
        )

    def _parse_resource(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_linear_connectives
            or profile.family_kind is SessionProcessFamilyKind.LINEAR,
            construct="resource",
            range=start.range,
        )
        cursor.advance()
        cursor.expect_lexeme("(")
        name = cursor.expect_ident().lexeme
        end = cursor.expect_lexeme(")")
        span = cursor.range_span(start.range, end.range)
        return self._ext(
            node_id=self._nid("resource"),
            profile=profile,
            features=("session_process.resource", "session_process.linear"),
            payload_schema=SP_RESOURCE_PAYLOAD_SCHEMA,
            payload={"kind": "resource", "name": name},
            range=span,
        )

    def _parse_channel_ref(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        """Parse ``chan(c)`` / ``channel(c)`` free channel references."""

        start = cursor.current()
        self._require_admission(
            profile,
            admitted=profile.admit_process_composition
            or profile.admit_session_actions,
            construct="chan",
            range=start.range,
        )
        cursor.advance()
        cursor.expect_lexeme("(")
        name = cursor.expect_ident().lexeme
        end = cursor.expect_lexeme(")")
        span = cursor.range_span(start.range, end.range)
        return self._ext(
            node_id=self._nid("chan"),
            profile=profile,
            features=("session_process.channel_ref", "session_process.scope"),
            payload_schema=SP_CHAN_PAYLOAD_SCHEMA,
            payload={"kind": "channel_ref", "name": name},
            range=span,
        )

    def _parse_dup(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        """Parse explicit ``dup(r)`` — rejected under duplication-rejecting profiles."""

        start = cursor.current()
        cursor.advance()
        cursor.expect_lexeme("(")
        name_tok = cursor.expect_ident()
        end = cursor.expect_lexeme(")")
        span = cursor.range_span(start.range, end.range)
        if profile.reject_resource_duplication:
            raise _ParseFail(
                _diag(
                    code=CODE_RESOURCE_DUPLICATION,
                    message=(
                        f"resource duplication via dup({name_tok.lexeme}) is "
                        "not silently normalized; rejected by profile"
                    ),
                    range=span,
                    remediation=(
                        "Remove dup(...), use ofcourse/bang for unrestricted "
                        "resources, or select a profile that permits duplication"
                    ),
                )
            )
        # When duplication is permitted, expand as tensor of two resources.
        left = self._ext(
            node_id=self._nid("resource"),
            profile=profile,
            features=("session_process.resource",),
            payload_schema=SP_RESOURCE_PAYLOAD_SCHEMA,
            payload={"kind": "resource", "name": name_tok.lexeme},
            range=span,
        )
        right = self._ext(
            node_id=self._nid("resource"),
            profile=profile,
            features=("session_process.resource",),
            payload_schema=SP_RESOURCE_PAYLOAD_SCHEMA,
            payload={"kind": "resource", "name": name_tok.lexeme},
            range=span,
        )
        return self._ext(
            node_id=self._nid("tensor"),
            profile=profile,
            features=("session_process.tensor", "session_process.dup_expanded"),
            payload_schema=SP_TENSOR_PAYLOAD_SCHEMA,
            payload={"kind": "tensor", "from_dup": True},
            children=(left, right),
            range=span,
        )

    def _parse_progress(
        self,
        cursor: _Cursor,
        profile: SessionProcessLogicProfile,
    ) -> LogicNode:
        start = cursor.current()
        cursor.advance()
        cursor.expect_lexeme("(")
        model_tok = cursor.expect_ident()
        model = model_tok.lexeme.casefold()
        try:
            ProgressModel(model)
        except ValueError as error:
            raise _ParseFail(
                _diag(
                    code=CODE_PROGRESS_MISMATCH,
                    message=f"unknown progress model {model!r}",
                    range=model_tok.range,
                )
            ) from error
        end = cursor.expect_lexeme(")")
        span = cursor.range_span(start.range, end.range)
        return self._ext(
            node_id=self._nid("progress"),
            profile=profile,
            features=("session_process.progress",),
            payload_schema=SP_PROGRESS_PAYLOAD_SCHEMA,
            payload={"kind": "progress", "model": model},
            range=span,
        )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class SessionProcessLogic:
    """Facade for ``SessionProcessLogic@1``."""

    interface: ClassVar[str] = SESSION_PROCESS_LOGIC_INTERFACE

    def __init__(
        self,
        profile: SessionProcessLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_session()
        self.parser = SessionProcessParser(
            self.profile, print_style=print_style
        )
        self.printer = SessionProcessPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> SessionProcessParseResult:
        document_id = str(kwargs.pop("document_id", "doc:sp:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:sp:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:sp:1"))
        run_checks = bool(kwargs.pop("run_checks", True))
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
            run_checks=run_checks,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise SessionProcessParseError(
                "session/process parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def check_linearity(
        self,
        node: LogicNode,
        *,
        profile: SessionProcessLogicProfile | None = None,
    ) -> LinearityReport:
        return check_linearity(node, profile or self.profile)

    def check_duality(
        self,
        node: LogicNode,
        *,
        profile: SessionProcessLogicProfile | None = None,
    ) -> DualityReport:
        return check_duality(node, profile or self.profile)

    def check_process_scope(
        self,
        node: LogicNode,
        *,
        profile: SessionProcessLogicProfile | None = None,
    ) -> ProcessScopeReport:
        return check_process_scope(node, profile or self.profile)

    def check_progress_model(
        self,
        node: LogicNode,
        *,
        profile: SessionProcessLogicProfile | None = None,
    ) -> ProgressReport:
        return check_progress_model(node, profile or self.profile)

    def check_refinement_direction(
        self,
        node: LogicNode,
        *,
        profile: SessionProcessLogicProfile | None = None,
    ) -> RefinementDirectionReport:
        return check_refinement_direction(node, profile or self.profile)


def parse_session_process(
    text: str,
    profile: SessionProcessLogicProfile | None = None,
    **kwargs: Any,
) -> SessionProcessParseResult:
    """Parse linear/session/process/refinement *text* under named *profile*."""

    logic = SessionProcessLogic(profile or profile_session())
    return logic.parse_text(text, **kwargs)


def print_session_process(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return SessionProcessPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: SessionProcessLogicProfile | None = None,
) -> tuple[SessionProcessParseResult, SessionProcessParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_session()
    first = parse_session_process(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_session_process(first.root)
    second = parse_session_process(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "SESSION_PROCESS_LOGIC_INTERFACE",
    "SESSION_PROCESS_PROFILE_INTERFACE",
    "LINEAR_PROFILE_INTERFACE",
    "SESSION_PROFILE_INTERFACE",
    "PROCESS_PROFILE_INTERFACE",
    "RELATIONAL_REFINEMENT_PROFILE_INTERFACE",
    "LINEAR_FAMILY_ID",
    "SESSION_FAMILY_ID",
    "PROCESS_FAMILY_ID",
    "REFINEMENT_FAMILY_ID",
    "SP_NOTATION_ID",
    "SP_TASK_ID",
    "CODE_DUALITY",
    "CODE_LINEARITY",
    "CODE_PROCESS_SCOPE",
    "CODE_PROGRESS_MISMATCH",
    "CODE_PROGRESS_REQUIRED",
    "CODE_PROFILE_MISMATCH",
    "CODE_PROFILE_REQUIRED",
    "CODE_REFINEMENT_DIRECTION",
    "CODE_REFINEMENT_DIRECTION_MISMATCH",
    "CODE_RESOURCE_DUPLICATION",
    "CODE_OPERATOR_FORBIDDEN",
    "DualityReport",
    "LinearityMode",
    "LinearityReport",
    "PrintStyle",
    "ProcessScopeReport",
    "ProgressModel",
    "ProgressReport",
    "RefinementDirectionKind",
    "RefinementDirectionReport",
    "SessionProcessFamilyKind",
    "SessionProcessLogic",
    "SessionProcessLogicProfile",
    "SessionProcessParseError",
    "SessionProcessParseResult",
    "SessionProcessParser",
    "SessionProcessPrinter",
    "check_duality",
    "check_linearity",
    "check_process_scope",
    "check_progress_model",
    "check_refinement_direction",
    "collect_free_channels",
    "collect_resource_names",
    "dualize_session_ast",
    "parse_print_parse",
    "parse_session_process",
    "print_session_process",
    "profile_linear",
    "profile_process",
    "profile_relational_refinement",
    "profile_session",
    "run_profile_checks",
    "session_process_semantic_identity",
]
