"""Controlled transition-system and TLA+ property adapters.

Interfaces:

* ``StatePropertySyntax@1`` — parse/print/elaborate for controlled state
  predicates, next-state relations, invariants, fairness, and temporal
  properties over transition systems
* ``ControlledTLAProperty@1`` — TLA-flavoured surface for the same fragment,
  with explicit finite/bounded TLC and Apalache contracts

Controlled expressions round-trip under alpha-equivalence.  Full-module TLA+
constructs (``MODULE``, ``EXTENDS``, ``INSTANCE``, ``THEOREM``, ``PROOF``, …)
are declaration-only or unsupported — this module never claims to parse
complete TLA+ modules.  TLC finite-state and Apalache bounded results carry
explicit evidence contracts and **cannot** be promoted to unbounded proof.

Grammar (connective precedence, low → high)::

    formula     ::= iff_formula
    iff         ::= implies (('iff'|'<=>') implies)*
    implies     ::= or (('=>'|'->'|'implies') formula)?   # right-assoc
    or          ::= and (('\\/'|'or'|'∨') and)*
    and         ::= unary (('/\\'|'and'|'∧') unary)*
    unary       ::= temporal_op unary
                  | ('not'|'~'|'¬'|'ENABLED') unary
                  | atomic
    temporal_op ::= 'always'|'eventually'|'[]'|'<>'
    atomic      ::= 'true'|'false'
                  | 'UNCHANGED' vars
                  | fairness '(' formula ')'
                  | '[' formula ']_' vars          # stuttering
                  | '<<' formula '>>_' vars        # angle action
                  | term ('='|'\\\\in'|'in') term
                  | primed_ident | ident
                  | '(' formula ')'
    fairness    ::= 'WF_' ident | 'SF_' ident | 'weak_fairness' | 'strong_fairness'
    vars        ::= ident | '<<' ident (',' ident)* '>>'
    primed      ::= ident "'"                      # surface prime; lexed as ident @'

Evidence subset: variables, init, next, invariant, fairness, stuttering,
bound, source map, TLC, Apalache.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, ClassVar, Final

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
from ipfs_datasets_py.logic.syntax_core.diagnostics import DiagnosticSink
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    propositional_signature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

STATE_PROPERTY_SYNTAX_INTERFACE: Final = "StatePropertySyntax@1"
CONTROLLED_TLA_PROPERTY_INTERFACE: Final = "ControlledTLAProperty@1"
STATE_NOTATION_ID: Final = "canonical_state_property"
STATE_NOTATION_VERSION: Final = "1.0.0"
STATE_FAMILY_ID: Final = "transition_system"
STATE_MODULE_VERSION: Final = "1.0.0"
STATE_PARSE_RESULT_SCHEMA_VERSION: Final = "canonical-state-parse-result/v1"
STATE_PROPERTY_PROFILE_SCHEMA_VERSION: Final = "state-property-profile/v1"
STATE_OPERATOR_PAYLOAD_SCHEMA: Final = "state.operator/v1"
STATE_VARIABLE_PAYLOAD_SCHEMA: Final = "state.variable/v1"
STATE_STUTTER_PAYLOAD_SCHEMA: Final = "state.stuttering/v1"
STATE_FAIRNESS_PAYLOAD_SCHEMA: Final = "state.fairness/v1"
STATE_EQUALITY_PAYLOAD_SCHEMA: Final = "state.equality/v1"
STATE_MEMBERSHIP_PAYLOAD_SCHEMA: Final = "state.membership/v1"
STATE_UNCHANGED_PAYLOAD_SCHEMA: Final = "state.unchanged/v1"
STATE_ANGLE_PAYLOAD_SCHEMA: Final = "state.angle_action/v1"
STATE_LITERAL_PAYLOAD_SCHEMA: Final = "state.literal/v1"
STATE_SOURCE_MAP_SCHEMA_VERSION: Final = "state.source-map/v1"
STATE_BOUND_CONTRACT_SCHEMA_VERSION: Final = "state.bound-contract/v1"
STATE_CHECKER_CONTRACT_SCHEMA_VERSION: Final = "state.checker-contract/v1"
STATE_MODULE_DISPOSITION_SCHEMA: Final = "state.module-construct/v1"

# Lexeme rewrite: surface ``x'`` becomes ``x @'`` so BoundedLexer can tokenize.
_PRIME_SURFACE_OP: Final = "@'"
_PRIME_REWRITE_RE: Final = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)'")

# Stable diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "state.unexpected_token"
CODE_TRAILING_INPUT: Final = "state.trailing_input"
CODE_EMPTY_INPUT: Final = "state.empty_input"
CODE_PARSE_DEPTH: Final = "state.parse_depth_exceeded"
CODE_UNBALANCED: Final = "state.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "state.lexer_error"
CODE_PROFILE_MISMATCH: Final = "state.profile_mismatch"
CODE_UNSUPPORTED_MODULE: Final = "state.unsupported_module_construct"
CODE_DECLARATION_ONLY: Final = "state.declaration_only_construct"
CODE_ROUND_TRIP: Final = "state.round_trip_failed"
CODE_PROMOTION_REJECTED: Final = "state.unbounded_promotion_rejected"
CODE_MISSING_BOUND: Final = "state.missing_bound"
CODE_INVALID_FAIRNESS: Final = "state.invalid_fairness"
CODE_INVALID_STUTTER: Final = "state.invalid_stuttering"

_ALL_STATE_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_PROFILE_MISMATCH,
        CODE_UNSUPPORTED_MODULE,
        CODE_DECLARATION_ONLY,
        CODE_ROUND_TRIP,
        CODE_PROMOTION_REJECTED,
        CODE_MISSING_BOUND,
        CODE_INVALID_FAIRNESS,
        CODE_INVALID_STUTTER,
    }
)

# Connectives.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_WORDS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_WORDS: Final[frozenset[str]] = frozenset({"or", "∨", "|", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤", "TRUE"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥", "FALSE"})
_ALWAYS_WORDS: Final[frozenset[str]] = frozenset({"always"})
_EVENTUALLY_WORDS: Final[frozenset[str]] = frozenset({"eventually"})
_ENABLED_WORDS: Final[frozenset[str]] = frozenset({"enabled", "ENABLED"})
_UNCHANGED_WORDS: Final[frozenset[str]] = frozenset({"unchanged", "UNCHANGED"})
_IN_OPS: Final[frozenset[str]] = frozenset({"in", "\\in", "∈"})
_EQ_OPS: Final[frozenset[str]] = frozenset({"="})

# Full-module constructs: disposition under ControlledTLAProperty@1.
_UNSUPPORTED_MODULE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "module",
        "instance",
        "theorem",
        "lemma",
        "corollary",
        "proposition",
        "proof",
        "qed",
        "by",
        "obvious",
        "omitted",
        "suffices",
        "pick",
        "witness",
        "define",
        "recursive",
        "local",
        "with",
        "only",
        "use",
        "hide",
        "have",
        "take",
        "case",
        "other",
    }
)
_DECLARATION_ONLY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "extends",
        "constants",
        "constant",
        "variables",
        "variable",
        "assume",
        "assumption",
        "axiom",
        "new",
    }
)

_STATE_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "TRUE",
    "FALSE",
    "always",
    "eventually",
    "enabled",
    "ENABLED",
    "unchanged",
    "UNCHANGED",
    "in",
    "weak_fairness",
    "strong_fairness",
    "init",
    "next",
    "invariant",
    "spec",
    "module",
    "extends",
    "instance",
    "constants",
    "constant",
    "variables",
    "variable",
    "theorem",
    "lemma",
    "proof",
    "assume",
    "assumption",
    "axiom",
)

_STATE_MULTI_OPS: Final[tuple[str, ...]] = (
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
    "\\in",
    _PRIME_SURFACE_OP,
)

_TEMPORAL_UNARY_KINDS: Final[frozenset[str]] = frozenset(
    {"always", "eventually", "enabled"}
)
_ALL_STATE_EXT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "always",
        "eventually",
        "enabled",
        "stuttering",
        "angle_action",
        "fairness",
        "unchanged",
        "prime",
        "variable",
        "equality",
        "membership",
        "literal",
    }
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"
    TLA = "tla"


class PropertyRole(str, Enum):
    """Role of a controlled state/TLA property expression."""

    STATE_PREDICATE = "state_predicate"
    INIT = "init"
    NEXT = "next"
    INVARIANT = "invariant"
    FAIRNESS = "fairness"
    TEMPORAL = "temporal"
    SPEC = "spec"
    GENERIC = "generic"


class FairnessStrength(str, Enum):
    """Fairness strength projected into TLA WF/SF form."""

    WEAK = "weak"
    STRONG = "strong"


class CheckerTool(str, Enum):
    """Model-checker targets for controlled lowering."""

    TLC = "tlc"
    APALACHE = "apalache"
    NONE = "none"


class BoundednessKind(str, Enum):
    """Semantic bound declared for checker evidence."""

    FINITE_STATE = "finite_state"
    STEP_BOUNDED = "step_bounded"
    UNBOUNDED = "unbounded"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by checker evidence (never unbounded proof)."""

    BOUNDED = "bounded"
    ADVISORY = "advisory"
    NONE = "none"


class ModuleConstructDisposition(str, Enum):
    """How a full-module construct is treated by the controlled adapter."""

    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"
    CONTROLLED = "controlled"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    UNARY = 50
    ATOM = 60


# ---------------------------------------------------------------------------
# Bound / checker contracts (cannot promote to unbounded proof)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FiniteBoundContract:
    """Explicit finite/step bound attached to every TLC/Apalache lowering."""

    max_steps: int = 64
    max_states: int | None = None
    domain_finite: bool = True
    boundedness: BoundednessKind | str = BoundednessKind.FINITE_STATE
    schema_version: str = STATE_BOUND_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int):
            raise SyntaxContractError("max_steps must be an integer")
        if self.max_steps < 1:
            raise SyntaxContractError("max_steps must be positive")
        if self.max_states is not None:
            if isinstance(self.max_states, bool) or not isinstance(self.max_states, int):
                raise SyntaxContractError("max_states must be an integer or None")
            if self.max_states < 1:
                raise SyntaxContractError("max_states must be positive when set")
        if not isinstance(self.domain_finite, bool):
            raise SyntaxContractError("domain_finite must be a boolean")
        bound = (
            self.boundedness
            if isinstance(self.boundedness, BoundednessKind)
            else BoundednessKind(str(self.boundedness))
        )
        if bound is BoundednessKind.UNBOUNDED:
            raise SyntaxContractError(
                "FiniteBoundContract rejects unboundedness; use an explicit "
                "finite_state or step_bounded contract"
            )
        object.__setattr__(self, "boundedness", bound)
        if self.schema_version != STATE_BOUND_CONTRACT_SCHEMA_VERSION:
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
            "domain_finite": self.domain_finite,
            "max_states": self.max_states,
            "max_steps": self.max_steps,
            "schema_version": self.schema_version,
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FiniteBoundContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("bound contract must be a mapping")
        max_states = value.get("max_states")
        return cls(
            max_steps=int(value.get("max_steps", 64)),
            max_states=int(max_states) if max_states is not None else None,
            domain_finite=bool(value.get("domain_finite", True)),
            boundedness=value.get("boundedness", BoundednessKind.FINITE_STATE.value),
            schema_version=str(
                value.get("schema_version") or STATE_BOUND_CONTRACT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckerEvidenceContract:
    """Authority ceiling for TLC / Apalache results.

    Successful finite-state (TLC) or bounded (Apalache) checks are
    ``bounded`` evidence only.  Promotion to unbounded proof is always
    rejected.
    """

    tool: CheckerTool | str
    bound: FiniteBoundContract
    authority: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    schema_version: str = STATE_CHECKER_CONTRACT_SCHEMA_VERSION

    interface: ClassVar[str] = CONTROLLED_TLA_PROPERTY_INTERFACE

    def __post_init__(self) -> None:
        tool = (
            self.tool
            if isinstance(self.tool, CheckerTool)
            else CheckerTool(str(self.tool))
        )
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        if not isinstance(self.bound, FiniteBoundContract):
            raise SyntaxContractError("bound must be a FiniteBoundContract")
        if tool is CheckerTool.NONE:
            if authority not in {EvidenceAuthority.NONE, EvidenceAuthority.ADVISORY}:
                raise SyntaxContractError(
                    "CheckerTool.NONE admits only none/advisory authority"
                )
        else:
            if authority is not EvidenceAuthority.BOUNDED:
                raise SyntaxContractError(
                    "TLC and Apalache contracts require bounded authority; "
                    "unbounded proof authority is rejected"
                )
            if self.bound.boundedness is BoundednessKind.UNBOUNDED:
                raise SyntaxContractError(
                    "TLC/Apalache contracts require finite or step bounds"
                )
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "authority", authority)
        if self.schema_version != STATE_CHECKER_CONTRACT_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported checker contract schema {self.schema_version!r}"
            )

    @property
    def unbounded_proof(self) -> bool:
        return False

    @property
    def may_promote_to_unbounded_proof(self) -> bool:
        return False

    def promote_to_unbounded_proof(self) -> None:
        """Fail closed: finite/bounded checker results are not proofs."""

        raise SyntaxContractError(
            f"{self.tool.value if isinstance(self.tool, CheckerTool) else self.tool} "
            "finite/bounded results cannot be promoted to unbounded proof "
            f"(authority={self.authority.value if isinstance(self.authority, EvidenceAuthority) else self.authority}, "
            f"boundedness={self.bound.boundedness.value if isinstance(self.bound.boundedness, BoundednessKind) else self.bound.boundedness})",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value
            if isinstance(self.authority, EvidenceAuthority)
            else str(self.authority),
            "bound": self.bound.to_dict(),
            "interface": self.interface,
            "may_promote_to_unbounded_proof": False,
            "schema_version": self.schema_version,
            "tool": self.tool.value
            if isinstance(self.tool, CheckerTool)
            else str(self.tool),
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CheckerEvidenceContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("checker contract must be a mapping")
        raw_bound = value.get("bound")
        bound = (
            raw_bound
            if isinstance(raw_bound, FiniteBoundContract)
            else FiniteBoundContract.from_dict(
                raw_bound if isinstance(raw_bound, Mapping) else {}
            )
        )
        return cls(
            tool=value.get("tool", CheckerTool.NONE.value),
            bound=bound,
            authority=value.get("authority", EvidenceAuthority.BOUNDED.value),
            schema_version=str(
                value.get("schema_version") or STATE_CHECKER_CONTRACT_SCHEMA_VERSION
            ),
        )


def tlc_evidence_contract(
    *,
    max_steps: int = 64,
    max_states: int | None = None,
) -> CheckerEvidenceContract:
    """TLC finite-state contract (never unbounded proof)."""

    return CheckerEvidenceContract(
        tool=CheckerTool.TLC,
        bound=FiniteBoundContract(
            max_steps=max_steps,
            max_states=max_states,
            domain_finite=True,
            boundedness=BoundednessKind.FINITE_STATE,
        ),
        authority=EvidenceAuthority.BOUNDED,
    )


def apalache_evidence_contract(
    *,
    max_steps: int = 10,
) -> CheckerEvidenceContract:
    """Apalache step-bounded contract (never unbounded proof)."""

    return CheckerEvidenceContract(
        tool=CheckerTool.APALACHE,
        bound=FiniteBoundContract(
            max_steps=max_steps,
            domain_finite=True,
            boundedness=BoundednessKind.STEP_BOUNDED,
        ),
        authority=EvidenceAuthority.BOUNDED,
    )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatePropertyProfile:
    """Semantic profile for controlled state/TLA property expressions.

    Profile id, role defaults, stuttering admission, and checker bound all
    participate in semantic identity.  Bounds are never optional for TLC or
    Apalache targets.
    """

    profile_id: str
    default_role: PropertyRole | str = PropertyRole.GENERIC
    admit_tla_operators: bool = True
    admit_stuttering: bool = True
    admit_fairness: bool = True
    admit_temporal: bool = True
    checker: CheckerEvidenceContract | None = None
    schema_version: str = STATE_PROPERTY_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = STATE_PROPERTY_SYNTAX_INTERFACE

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
        role = (
            self.default_role
            if isinstance(self.default_role, PropertyRole)
            else PropertyRole(str(self.default_role))
        )
        object.__setattr__(self, "default_role", role)
        for name in (
            "admit_tla_operators",
            "admit_stuttering",
            "admit_fairness",
            "admit_temporal",
        ):
            if not isinstance(getattr(self, name), bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if self.checker is not None and not isinstance(
            self.checker, CheckerEvidenceContract
        ):
            raise SyntaxContractError("checker must be a CheckerEvidenceContract")
        if self.schema_version != STATE_PROPERTY_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported StatePropertyProfile schema {self.schema_version!r}"
            )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "admit_fairness": self.admit_fairness,
            "admit_stuttering": self.admit_stuttering,
            "admit_temporal": self.admit_temporal,
            "admit_tla_operators": self.admit_tla_operators,
            "default_role": self.default_role.value
            if isinstance(self.default_role, PropertyRole)
            else str(self.default_role),
            "profile_id": self.profile_id,
        }
        if self.checker is not None:
            payload["checker"] = self.checker.to_dict()
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_fairness": self.admit_fairness,
            "admit_stuttering": self.admit_stuttering,
            "admit_temporal": self.admit_temporal,
            "admit_tla_operators": self.admit_tla_operators,
            "checker": self.checker.to_dict() if self.checker is not None else None,
            "default_role": self.default_role.value
            if isinstance(self.default_role, PropertyRole)
            else str(self.default_role),
            "interface": self.interface,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StatePropertyProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("StatePropertyProfile must be a mapping")
        raw_checker = value.get("checker")
        checker = None
        if raw_checker is not None:
            checker = (
                raw_checker
                if isinstance(raw_checker, CheckerEvidenceContract)
                else CheckerEvidenceContract.from_dict(raw_checker)
            )
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            default_role=value.get("default_role", PropertyRole.GENERIC.value),
            admit_tla_operators=bool(value.get("admit_tla_operators", True)),
            admit_stuttering=bool(value.get("admit_stuttering", True)),
            admit_fairness=bool(value.get("admit_fairness", True)),
            admit_temporal=bool(value.get("admit_temporal", True)),
            checker=checker,
            schema_version=str(
                value.get("schema_version") or STATE_PROPERTY_PROFILE_SCHEMA_VERSION
            ),
        )


def profile_state_property(
    *,
    profile_id: str = "state_property_controlled",
    default_role: PropertyRole | str = PropertyRole.GENERIC,
) -> StatePropertyProfile:
    return StatePropertyProfile(
        profile_id=profile_id,
        default_role=default_role,
        admit_tla_operators=True,
        admit_stuttering=True,
        admit_fairness=True,
        admit_temporal=True,
        checker=None,
    )


def profile_tla_tlc(
    *,
    profile_id: str = "tla_tlc_finite",
    max_steps: int = 64,
    max_states: int | None = None,
    default_role: PropertyRole | str = PropertyRole.SPEC,
) -> StatePropertyProfile:
    return StatePropertyProfile(
        profile_id=profile_id,
        default_role=default_role,
        admit_tla_operators=True,
        admit_stuttering=True,
        admit_fairness=True,
        admit_temporal=True,
        checker=tlc_evidence_contract(max_steps=max_steps, max_states=max_states),
    )


def profile_tla_apalache(
    *,
    profile_id: str = "tla_apalache_bounded",
    max_steps: int = 10,
    default_role: PropertyRole | str = PropertyRole.INVARIANT,
) -> StatePropertyProfile:
    return StatePropertyProfile(
        profile_id=profile_id,
        default_role=default_role,
        admit_tla_operators=True,
        admit_stuttering=True,
        admit_fairness=False,  # Apalache does not check fairness/liveness
        admit_temporal=True,
        checker=apalache_evidence_contract(max_steps=max_steps),
    )


# ---------------------------------------------------------------------------
# Module construct disposition
# ---------------------------------------------------------------------------


def module_construct_disposition(keyword: str) -> ModuleConstructDisposition:
    """Classify a full-module keyword under ControlledTLAProperty@1."""

    key = keyword.casefold()
    if key in _UNSUPPORTED_MODULE_KEYWORDS:
        return ModuleConstructDisposition.UNSUPPORTED
    if key in _DECLARATION_ONLY_KEYWORDS:
        return ModuleConstructDisposition.DECLARATION_ONLY
    return ModuleConstructDisposition.CONTROLLED


@dataclass(frozen=True, slots=True)
class ModuleConstructRecord:
    """Receipt that a full-module construct was not controlled-expression parsed."""

    keyword: str
    disposition: ModuleConstructDisposition | str
    message: str
    range: SourceRange | None = None
    schema_version: str = STATE_MODULE_DISPOSITION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "keyword", str(self.keyword))
        disp = (
            self.disposition
            if isinstance(self.disposition, ModuleConstructDisposition)
            else ModuleConstructDisposition(str(self.disposition))
        )
        object.__setattr__(self, "disposition", disp)
        if not isinstance(self.message, str) or not self.message:
            raise SyntaxContractError("message must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value
            if isinstance(self.disposition, ModuleConstructDisposition)
            else str(self.disposition),
            "keyword": self.keyword,
            "message": self.message,
            "range": self.range.to_dict() if self.range is not None else None,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Source map
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateSourceMapEntry:
    """One source-mapped node from controlled expression to AST symbol."""

    source_span: SourceRange
    node_id: str
    kind: str
    symbol: str = ""
    role: str = ""
    schema_version: str = STATE_SOURCE_MAP_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "node_id": self.node_id,
            "role": self.role,
            "schema_version": self.schema_version,
            "source_span": self.source_span.to_dict(),
            "symbol": self.symbol,
        }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateParseResult:
    """Typed result of a controlled state/TLA property parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: StatePropertyProfile | None = None
    source_map: tuple[StateSourceMapEntry, ...] = ()
    module_constructs: tuple[ModuleConstructRecord, ...] = ()
    checker_contract: CheckerEvidenceContract | None = None
    schema_version: str = STATE_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = STATE_PROPERTY_SYNTAX_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    @property
    def unbounded_proof(self) -> bool:
        return False


class StateParseError(SyntaxContractError):
    """Raised by raising helpers when a state property parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: StateParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Token cursor / diagnostics
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class _TokenCursor:
    def __init__(self, tokens: Sequence[LogicToken], document: SourceDocument) -> None:
        self.tokens = tuple(tokens)
        self.document = document
        self.index = 0
        self.depth = 0

    def current(self) -> LogicToken:
        if self.index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[self.index]

    def peek(self, offset: int = 0) -> LogicToken:
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

    def match_lexeme(self, *lexemes: str) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        targets = {
            item.casefold() if item.isascii() and item.isalpha() else item
            for item in lexemes
        }
        if token.kind == TokenKind.KEYWORD.value:
            if token.lexeme.casefold() in {t.casefold() for t in targets}:
                return self.advance()
            return None
        if token.lexeme in targets:
            return self.advance()
        if token.lexeme.casefold() in {t.casefold() for t in targets if t.isalpha()}:
            return self.advance()
        return None

    def match_any(self, lexemes: frozenset[str]) -> LogicToken | None:
        token = self.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded_targets = {item.casefold() for item in lexemes if item.isalpha()}
        exact_targets = {item for item in lexemes if not item.isalpha() or not item.isascii()}
        if token.kind == TokenKind.KEYWORD.value:
            if token.lexeme.casefold() in {item.casefold() for item in lexemes}:
                return self.advance()
            return None
        if token.lexeme in lexemes or token.lexeme in exact_targets:
            return self.advance()
        if token.lexeme.casefold() in folded_targets:
            return self.advance()
        return None

    def expect_lexeme(self, *lexemes: str, code: str = CODE_UNEXPECTED_TOKEN) -> LogicToken:
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

    def eof_range(self) -> SourceRange:
        return self.tokens[-1].range


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    remediation: str = "",
    diagnostic_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    diag_id = diagnostic_id or f"diag:state:{code.replace('.', '-')}"
    return SyntaxDiagnostic(
        diagnostic_id=diag_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


def rewrite_primes_for_lex(text: str) -> str:
    """Rewrite surface primes ``x'`` into lexer-safe ``x @'`` form."""

    return _PRIME_REWRITE_RE.sub(rf"\1 {_PRIME_SURFACE_OP}", text)


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _StateParserEngine:
    """Profile-bound recursive-descent parser for controlled state/TLA syntax."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: StatePropertyProfile,
        limits: ParseLimits,
        expression_id: str = "expr:state:1",
        variables: frozenset[str] | None = None,
    ) -> None:
        self.document = document
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self.variables = variables
        self.cursor = _TokenCursor(tokens, document)
        self.sink = DiagnosticSink(max_diagnostics=limits.max_diagnostics)
        self._node_seq = 0
        self.source_map: list[StateSourceMapEntry] = []
        self.module_constructs: list[ModuleConstructRecord] = []
        self.root: LogicNode | None = None

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if self.cursor.is_eof():
            self._emit(
                CODE_EMPTY_INPUT,
                "empty input; expected a state/TLA property expression",
                self.cursor.eof_range(),
            )
            return None, self.sink.items
        # Reject full-module constructs at the head (and scan for them).
        head = self.cursor.current()
        if head.kind in {TokenKind.KEYWORD.value, TokenKind.IDENTIFIER.value}:
            disp = module_construct_disposition(head.lexeme)
            if disp is ModuleConstructDisposition.UNSUPPORTED:
                record = ModuleConstructRecord(
                    keyword=head.lexeme,
                    disposition=disp,
                    message=(
                        f"full-module construct {head.lexeme!r} is unsupported by "
                        "ControlledTLAProperty@1; complete TLA+ modules are delegated "
                        "to TLC/Apalache, not this controlled expression adapter"
                    ),
                    range=head.range,
                )
                self.module_constructs.append(record)
                self._emit(
                    CODE_UNSUPPORTED_MODULE,
                    record.message,
                    head.range,
                    remediation=(
                        "Parse only controlled expressions (Init/Next/invariants/"
                        "fairness/temporal properties), not full MODULE bodies"
                    ),
                    metadata={"disposition": disp.value, "keyword": head.lexeme},
                )
                return None, self.sink.items
            if disp is ModuleConstructDisposition.DECLARATION_ONLY:
                record = ModuleConstructRecord(
                    keyword=head.lexeme,
                    disposition=disp,
                    message=(
                        f"full-module construct {head.lexeme!r} is declaration-only; "
                        "it is not a controlled checkable expression"
                    ),
                    range=head.range,
                )
                self.module_constructs.append(record)
                self._emit(
                    CODE_DECLARATION_ONLY,
                    record.message,
                    head.range,
                    remediation=(
                        "Record the declaration separately; controlled adapters "
                        "accept only expression-level fragments"
                    ),
                    metadata={"disposition": disp.value, "keyword": head.lexeme},
                )
                return None, self.sink.items
        try:
            node = self._parse_formula()
            if not self.cursor.is_eof():
                trailing = self.cursor.current()
                # Trailing module keywords also fail closed.
                tdisp = module_construct_disposition(trailing.lexeme)
                if tdisp is not ModuleConstructDisposition.CONTROLLED:
                    self._emit(
                        CODE_UNSUPPORTED_MODULE
                        if tdisp is ModuleConstructDisposition.UNSUPPORTED
                        else CODE_DECLARATION_ONLY,
                        (
                            f"trailing full-module construct {trailing.lexeme!r} "
                            f"is {tdisp.value}"
                        ),
                        trailing.range,
                        metadata={"disposition": tdisp.value},
                    )
                    return None, self.sink.items
                self._emit(
                    CODE_TRAILING_INPUT,
                    f"trailing input starting at {trailing.lexeme!r}",
                    trailing.range,
                    remediation="Remove trailing tokens or terminate the expression",
                )
                return None, self.sink.items
            self.root = node
            return node, self.sink.items
        except _ParseFail as failure:
            diag_id = f"diag:state:fail:{len(self.sink.items) + 1}"
            self.sink.add(
                SyntaxDiagnostic(
                    diagnostic_id=diag_id,
                    code=failure.diagnostic.code,
                    message=failure.diagnostic.message,
                    severity=failure.diagnostic.severity,
                    range=failure.diagnostic.range,
                    remediation=failure.diagnostic.remediation,
                    metadata=dict(failure.diagnostic.metadata),
                )
            )
            return None, self.sink.items

    def _emit(
        self,
        code: str,
        message: str,
        range: SourceRange | None,
        *,
        remediation: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.sink.emit(
            code=code,
            message=message,
            severity=DiagnosticSeverity.ERROR,
            range=range,
            remediation=remediation,
            metadata=metadata,
            diagnostic_id=(
                f"diag:state:{code.replace('.', '-')}:{len(self.sink.items) + 1}"
            ),
        )

    def _nid(self, prefix: str = "n") -> str:
        self._node_seq += 1
        return f"{prefix}:{self._node_seq}"

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

    def _map(
        self,
        node: LogicNode,
        *,
        kind: str,
        symbol: str = "",
        role: str = "",
    ) -> None:
        if node.range is None:
            return
        self.source_map.append(
            StateSourceMapEntry(
                source_span=node.range,
                node_id=node.node_id,
                kind=kind,
                symbol=symbol,
                role=role,
            )
        )

    # -- formula layers ----------------------------------------------------

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_iff()
        finally:
            self._leave()

    def _parse_iff(self) -> LogicNode:
        left = self._parse_implies()
        while True:
            op = self.cursor.match_any(_IFF_OPS)
            if op is None:
                return left
            right = self._parse_implies()
            span = self.cursor.range_span(
                left.range or op.range, right.range or op.range
            )
            left = LogicNode(
                node_id=self._nid("iff"),
                kind=NodeKind.IFF,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
            self._map(left, kind="iff")

    def _parse_implies(self) -> LogicNode:
        left = self._parse_or()
        op = self.cursor.match_any(_IMPLIES_OPS)
        if op is None:
            return left
        right = self._parse_formula()
        span = self.cursor.range_span(left.range or op.range, right.range or op.range)
        node = LogicNode(
            node_id=self._nid("imp"),
            kind=NodeKind.IMPLIES,
            sort=BOOL_SORT,
            arguments=(left, right),
            range=span,
        )
        self._map(node, kind="implies")
        return node

    def _parse_or(self) -> LogicNode:
        nodes = [self._parse_and()]
        while self._match_or_op() is not None:
            nodes.append(self._parse_and())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        node = LogicNode(
            node_id=self._nid("or"),
            kind=NodeKind.OR,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )
        self._map(node, kind="or")
        return node

    def _parse_and(self) -> LogicNode:
        nodes = [self._parse_unary()]
        while self._match_and_op() is not None:
            nodes.append(self._parse_unary())
        if len(nodes) == 1:
            return nodes[0]
        span = self.cursor.range_span(
            nodes[0].range or SourceRange(0, 0),
            nodes[-1].range or SourceRange(0, 0),
        )
        node = LogicNode(
            node_id=self._nid("and"),
            kind=NodeKind.AND,
            sort=BOOL_SORT,
            arguments=tuple(nodes),
            range=span,
        )
        self._map(node, kind="and")
        return node

    def _match_and_op(self) -> LogicToken | None:
        word = self.cursor.match_any(_AND_WORDS)
        if word is not None:
            return word
        # TLA /\\
        if self.cursor.current().lexeme == "/" and self.cursor.peek(1).lexeme == "\\":
            start = self.cursor.advance()
            self.cursor.advance()
            return start
        return None

    def _match_or_op(self) -> LogicToken | None:
        word = self.cursor.match_any(_OR_WORDS)
        if word is not None:
            return word
        # TLA \\/
        if self.cursor.current().lexeme == "\\" and self.cursor.peek(1).lexeme == "/":
            start = self.cursor.advance()
            self.cursor.advance()
            return start
        return None

    def _parse_unary(self) -> LogicNode:
        # always / eventually words
        if self.profile.admit_temporal:
            always = self.cursor.match_any(_ALWAYS_WORDS)
            if always is not None:
                self._enter()
                try:
                    body = self._parse_unary()
                finally:
                    self._leave()
                span = self.cursor.range_span(always.range, body.range or always.range)
                return self._mk_temporal("always", body=body, span=span)
            eventually = self.cursor.match_any(_EVENTUALLY_WORDS)
            if eventually is not None:
                self._enter()
                try:
                    body = self._parse_unary()
                finally:
                    self._leave()
                span = self.cursor.range_span(
                    eventually.range, body.range or eventually.range
                )
                return self._mk_temporal("eventually", body=body, span=span)
            # [] always
            if (
                self.cursor.current().lexeme == "["
                and self.cursor.peek(1).lexeme == "]"
            ):
                open_tok = self.cursor.advance()
                self.cursor.advance()
                self._enter()
                try:
                    body = self._parse_unary()
                finally:
                    self._leave()
                span = self.cursor.range_span(open_tok.range, body.range or open_tok.range)
                return self._mk_temporal("always", body=body, span=span)
            # <> eventually
            if (
                self.cursor.current().lexeme == "<"
                and self.cursor.peek(1).lexeme == ">"
            ):
                open_tok = self.cursor.advance()
                self.cursor.advance()
                self._enter()
                try:
                    body = self._parse_unary()
                finally:
                    self._leave()
                span = self.cursor.range_span(open_tok.range, body.range or open_tok.range)
                return self._mk_temporal("eventually", body=body, span=span)

        enabled = self.cursor.match_any(_ENABLED_WORDS)
        if enabled is not None:
            self._enter()
            try:
                body = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(enabled.range, body.range or enabled.range)
            return self._mk_enabled(body=body, span=span)

        not_tok = self.cursor.match_any(_NOT_OPS)
        if not_tok is not None:
            self._enter()
            try:
                inner = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(not_tok.range, inner.range or not_tok.range)
            node = LogicNode(
                node_id=self._nid("not"),
                kind=NodeKind.NOT,
                sort=BOOL_SORT,
                arguments=(inner,),
                range=span,
            )
            self._map(node, kind="not")
            return node

        return self._parse_atomic()

    def _parse_atomic(self) -> LogicNode:
        # Parenthesized formula or angle action starter.
        if (
            self.cursor.current().lexeme == "<"
            and self.cursor.peek(1).lexeme == "<"
        ):
            return self._parse_angle_action()

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

        # Stuttering [A]_v  (not [] which is handled in unary)
        if self.cursor.current().lexeme == "[":
            return self._parse_stuttering()

        # UNCHANGED
        unchanged = self.cursor.match_any(_UNCHANGED_WORDS)
        if unchanged is not None:
            vars_tuple, end_range = self._parse_vars()
            span = self.cursor.range_span(unchanged.range, end_range)
            return self._mk_unchanged(variables=vars_tuple, span=span)

        # Fairness WF_x(A) / SF_x(A) / weak_fairness(A)
        fair = self._match_fairness_head()
        if fair is not None:
            return fair

        # true / false
        token = self.cursor.match_any(_TRUE_OPS)
        if token is not None:
            node = mk_true(self._nid("true"))
            node = LogicNode(
                node_id=node.node_id,
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=token.range,
            )
            self._map(node, kind="true")
            return node
        token = self.cursor.match_any(_FALSE_OPS)
        if token is not None:
            node = mk_false(self._nid("false"))
            node = LogicNode(
                node_id=node.node_id,
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=token.range,
            )
            self._map(node, kind="false")
            return node

        # Identifier / primed identifier, optionally with = or \\in
        current = self.cursor.current()
        if current.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            # Reject module keywords that slipped through.
            disp = module_construct_disposition(current.lexeme)
            if disp is not ModuleConstructDisposition.CONTROLLED:
                raise _ParseFail(
                    _diag(
                        code=(
                            CODE_UNSUPPORTED_MODULE
                            if disp is ModuleConstructDisposition.UNSUPPORTED
                            else CODE_DECLARATION_ONLY
                        ),
                        message=(
                            f"full-module construct {current.lexeme!r} is "
                            f"{disp.value} under ControlledTLAProperty@1"
                        ),
                        range=current.range,
                        metadata={"disposition": disp.value},
                    )
                )
            name = current.lexeme
            # Role keywords used as atoms (Init, Next, Spec, …) are allowed.
            self.cursor.advance()
            primed = False
            if self.cursor.match_lexeme(_PRIME_SURFACE_OP) is not None:
                primed = True
            # Optional relational suffix: x = y  or  x \\in S
            if self.cursor.current().lexeme in _EQ_OPS or self.cursor.current().lexeme == "=":
                eq_tok = self.cursor.advance()
                right = self._parse_term_atom()
                left = self._mk_variable(name, primed=primed, span=current.range)
                span = self.cursor.range_span(
                    current.range, right.range or eq_tok.range
                )
                return self._mk_equality(left, right, span=span)
            if (
                self.cursor.current().lexeme in _IN_OPS
                or self.cursor.current().lexeme == "\\in"
            ):
                in_tok = self.cursor.advance()
                # handle \\ + in as two tokens? \\in is multi-op.
                right = self._parse_term_atom()
                left = self._mk_variable(name, primed=primed, span=current.range)
                span = self.cursor.range_span(
                    current.range, right.range or in_tok.range
                )
                return self._mk_membership(left, right, span=span)
            node = self._mk_variable(name, primed=primed, span=current.range)
            return node

        # Number literal as term atom in equality contexts only — reject bare.
        if current.kind == TokenKind.NUMBER.value:
            self.cursor.advance()
            return self._mk_literal(current.lexeme, span=current.range)

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def _parse_term_atom(self) -> LogicNode:
        """Parse a term-side atom (variable, primed variable, number, true/false)."""

        current = self.cursor.current()
        if current.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            name = current.lexeme
            self.cursor.advance()
            primed = self.cursor.match_lexeme(_PRIME_SURFACE_OP) is not None
            return self._mk_variable(name, primed=primed, span=current.range)
        if current.kind == TokenKind.NUMBER.value:
            self.cursor.advance()
            return self._mk_literal(current.lexeme, span=current.range)
        tok = self.cursor.match_any(_TRUE_OPS)
        if tok is not None:
            return LogicNode(
                node_id=self._nid("true"),
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=tok.range,
            )
        tok = self.cursor.match_any(_FALSE_OPS)
        if tok is not None:
            return LogicNode(
                node_id=self._nid("false"),
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=tok.range,
            )
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
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected term; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def _parse_stuttering(self) -> LogicNode:
        if not self.profile.admit_stuttering:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_STUTTER,
                    message="stuttering actions are not admitted by this profile",
                    range=self.cursor.current().range,
                )
            )
        open_tok = self.cursor.expect_lexeme("[", code=CODE_INVALID_STUTTER)
        # Disallow empty [] here — that is always, handled in unary.
        if self.cursor.current().lexeme == "]":
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_STUTTER,
                    message=(
                        "empty [] is the always operator and must appear in "
                        "operator position; stuttering requires [Action]_vars"
                    ),
                    range=self.cursor.current().range,
                )
            )
        action = self._parse_formula()
        close = self.cursor.expect_lexeme("]", code=CODE_UNBALANCED)
        # Require _vars suffix: either identifier starting with _ or '_' + ident
        underscore = self.cursor.current()
        if underscore.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            lex = underscore.lexeme
            if lex.startswith("_") and len(lex) > 1:
                self.cursor.advance()
                vars_tuple = (lex[1:],)
                end_range = underscore.range
            else:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_STUTTER,
                        message=(
                            "stuttering action requires '_vars' suffix "
                            f"(got {lex!r})"
                        ),
                        range=underscore.range,
                        remediation="Write e.g. [Next]_vars",
                    )
                )
        else:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_STUTTER,
                    message="stuttering action requires '_vars' suffix after ']'",
                    range=close.range,
                    remediation="Write e.g. [Next]_vars",
                )
            )
        span = self.cursor.range_span(open_tok.range, end_range)
        return self._mk_stuttering(action=action, variables=vars_tuple, span=span)

    def _parse_angle_action(self) -> LogicNode:
        if not self.profile.admit_stuttering:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_STUTTER,
                    message="angle actions are not admitted by this profile",
                    range=self.cursor.current().range,
                )
            )
        open1 = self.cursor.expect_lexeme("<")
        self.cursor.expect_lexeme("<")
        action = self._parse_formula()
        self.cursor.expect_lexeme(">", code=CODE_UNBALANCED)
        close2 = self.cursor.expect_lexeme(">", code=CODE_UNBALANCED)
        underscore = self.cursor.current()
        if underscore.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            lex = underscore.lexeme
            if lex.startswith("_") and len(lex) > 1:
                self.cursor.advance()
                vars_tuple = (lex[1:],)
                end_range = underscore.range
            else:
                raise _ParseFail(
                    _diag(
                        code=CODE_INVALID_STUTTER,
                        message=f"angle action requires '_vars' suffix (got {lex!r})",
                        range=underscore.range,
                    )
                )
        else:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_STUTTER,
                    message="angle action requires '_vars' suffix after '>>'",
                    range=close2.range,
                )
            )
        span = self.cursor.range_span(open1.range, end_range)
        return self._mk_angle(action=action, variables=vars_tuple, span=span)

    def _parse_vars(self) -> tuple[tuple[str, ...], SourceRange]:
        """Parse ``x`` or ``<<x, y>>`` variable lists."""

        if (
            self.cursor.current().lexeme == "<"
            and self.cursor.peek(1).lexeme == "<"
        ):
            self.cursor.advance()
            self.cursor.advance()
            names: list[str] = []
            while True:
                tok = self.cursor.current()
                if tok.kind not in {
                    TokenKind.IDENTIFIER.value,
                    TokenKind.KEYWORD.value,
                }:
                    raise _ParseFail(
                        _diag(
                            code=CODE_UNEXPECTED_TOKEN,
                            message=f"expected variable name; got {tok.lexeme!r}",
                            range=tok.range,
                        )
                    )
                names.append(tok.lexeme)
                self.cursor.advance()
                if self.cursor.match_lexeme(",") is not None:
                    continue
                break
            self.cursor.expect_lexeme(">", code=CODE_UNBALANCED)
            end = self.cursor.expect_lexeme(">", code=CODE_UNBALANCED)
            return tuple(names), end.range
        tok = self.cursor.current()
        if tok.kind not in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"expected variable name; got {tok.lexeme!r}",
                    range=tok.range,
                )
            )
        self.cursor.advance()
        return (tok.lexeme,), tok.range

    def _match_fairness_head(self) -> LogicNode | None:
        if not self.profile.admit_fairness:
            # Still detect and reject if written.
            token = self.cursor.current()
            if token.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
                lex = token.lexeme
                if (
                    lex.casefold() in {"weak_fairness", "strong_fairness"}
                    or lex.startswith("WF_")
                    or lex.startswith("SF_")
                ):
                    raise _ParseFail(
                        _diag(
                            code=CODE_INVALID_FAIRNESS,
                            message=(
                                f"fairness operator {lex!r} is not admitted by "
                                f"profile {self.profile.profile_id!r}"
                            ),
                            range=token.range,
                            remediation="Use a fairness-enabled profile (e.g. TLC)",
                        )
                    )
            return None

        token = self.cursor.current()
        if token.kind not in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            return None
        lex = token.lexeme
        strength: FairnessStrength | None = None
        vars_name = "vars"
        if lex.casefold() == "weak_fairness":
            strength = FairnessStrength.WEAK
        elif lex.casefold() == "strong_fairness":
            strength = FairnessStrength.STRONG
        elif lex.startswith("WF_") and len(lex) > 3:
            strength = FairnessStrength.WEAK
            vars_name = lex[3:]
        elif lex.startswith("SF_") and len(lex) > 3:
            strength = FairnessStrength.STRONG
            vars_name = lex[3:]
        else:
            return None
        self.cursor.advance()
        self.cursor.expect_lexeme("(", code=CODE_INVALID_FAIRNESS)
        body = self._parse_formula()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = self.cursor.range_span(token.range, close.range)
        return self._mk_fairness(
            strength=strength,
            variables=(vars_name,),
            action=body,
            span=span,
        )

    # -- node construction -------------------------------------------------

    def _base_payload(self, kind: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": kind,
            "profile_id": self.profile.profile_id,
            "role": self.profile.default_role.value
            if isinstance(self.profile.default_role, PropertyRole)
            else str(self.profile.default_role),
        }
        if self.profile.checker is not None:
            payload["checker"] = {
                "tool": self.profile.checker.tool.value
                if isinstance(self.profile.checker.tool, CheckerTool)
                else str(self.profile.checker.tool),
                "unbounded_proof": False,
                "authority": self.profile.checker.authority.value
                if isinstance(self.profile.checker.authority, EvidenceAuthority)
                else str(self.profile.checker.authority),
            }
        return payload

    def _mk_temporal(
        self, operator: str, *, body: LogicNode, span: SourceRange
    ) -> LogicNode:
        if not self.profile.admit_temporal:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"temporal operator {operator!r} not admitted",
                    range=span,
                )
            )
        payload = self._base_payload(operator)
        payload["schema_version"] = STATE_OPERATOR_PAYLOAD_SCHEMA
        node = mk_extension(
            self._nid(operator),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"state.{operator}", "state.temporal"),
            payload_schema=STATE_OPERATOR_PAYLOAD_SCHEMA,
            payload=payload,
            children=(body,),
            range=span,
        )
        self._map(node, kind=operator, role="temporal")
        return node

    def _mk_enabled(self, *, body: LogicNode, span: SourceRange) -> LogicNode:
        payload = self._base_payload("enabled")
        payload["schema_version"] = STATE_OPERATOR_PAYLOAD_SCHEMA
        node = mk_extension(
            self._nid("enabled"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.enabled",),
            payload_schema=STATE_OPERATOR_PAYLOAD_SCHEMA,
            payload=payload,
            children=(body,),
            range=span,
        )
        self._map(node, kind="enabled")
        return node

    def _mk_literal(self, lexeme: str, *, span: SourceRange) -> LogicNode:
        """Numeric (or other non-identifier) literal as a controlled extension."""

        payload = self._base_payload("literal")
        payload["schema_version"] = STATE_LITERAL_PAYLOAD_SCHEMA
        payload["lexeme"] = lexeme
        node = mk_extension(
            self._nid("lit"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.literal",),
            payload_schema=STATE_LITERAL_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )
        self._map(node, kind="literal", symbol=lexeme)
        return node

    def _mk_variable(
        self, name: str, *, primed: bool, span: SourceRange
    ) -> LogicNode:
        if self.variables is not None and name not in self.variables:
            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=f"undeclared variable {name!r}",
                    range=span,
                    remediation="Declare the variable in the state alphabet",
                )
            )
        if primed:
            payload = self._base_payload("prime")
            payload["schema_version"] = STATE_VARIABLE_PAYLOAD_SCHEMA
            payload["variable"] = name
            node = mk_extension(
                self._nid("prime"),
                family=STATE_FAMILY_ID,
                profile=self.profile.profile_id,
                features=("state.prime", "state.variable"),
                payload_schema=STATE_VARIABLE_PAYLOAD_SCHEMA,
                payload=payload,
                children=(),
                range=span,
            )
            self._map(node, kind="prime", symbol=name, role="next")
            return node
        payload = self._base_payload("variable")
        payload["schema_version"] = STATE_VARIABLE_PAYLOAD_SCHEMA
        payload["variable"] = name
        node = mk_extension(
            self._nid("var"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.variable",),
            payload_schema=STATE_VARIABLE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )
        self._map(node, kind="variable", symbol=name)
        return node

    def _mk_equality(
        self, left: LogicNode, right: LogicNode, *, span: SourceRange
    ) -> LogicNode:
        payload = self._base_payload("equality")
        payload["schema_version"] = STATE_EQUALITY_PAYLOAD_SCHEMA
        node = mk_extension(
            self._nid("eq"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.equality",),
            payload_schema=STATE_EQUALITY_PAYLOAD_SCHEMA,
            payload=payload,
            children=(left, right),
            range=span,
        )
        self._map(node, kind="equality")
        return node

    def _mk_membership(
        self, left: LogicNode, right: LogicNode, *, span: SourceRange
    ) -> LogicNode:
        payload = self._base_payload("membership")
        payload["schema_version"] = STATE_MEMBERSHIP_PAYLOAD_SCHEMA
        node = mk_extension(
            self._nid("in"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.membership",),
            payload_schema=STATE_MEMBERSHIP_PAYLOAD_SCHEMA,
            payload=payload,
            children=(left, right),
            range=span,
        )
        self._map(node, kind="membership")
        return node

    def _mk_unchanged(
        self, *, variables: tuple[str, ...], span: SourceRange
    ) -> LogicNode:
        payload = self._base_payload("unchanged")
        payload["schema_version"] = STATE_UNCHANGED_PAYLOAD_SCHEMA
        payload["variables"] = list(variables)
        node = mk_extension(
            self._nid("unchanged"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.unchanged", "state.stuttering"),
            payload_schema=STATE_UNCHANGED_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )
        self._map(node, kind="unchanged", role="next")
        return node

    def _mk_stuttering(
        self,
        *,
        action: LogicNode,
        variables: tuple[str, ...],
        span: SourceRange,
    ) -> LogicNode:
        payload = self._base_payload("stuttering")
        payload["schema_version"] = STATE_STUTTER_PAYLOAD_SCHEMA
        payload["variables"] = list(variables)
        node = mk_extension(
            self._nid("stutter"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.stuttering", "state.next"),
            payload_schema=STATE_STUTTER_PAYLOAD_SCHEMA,
            payload=payload,
            children=(action,),
            range=span,
        )
        self._map(node, kind="stuttering", role="next")
        return node

    def _mk_angle(
        self,
        *,
        action: LogicNode,
        variables: tuple[str, ...],
        span: SourceRange,
    ) -> LogicNode:
        payload = self._base_payload("angle_action")
        payload["schema_version"] = STATE_ANGLE_PAYLOAD_SCHEMA
        payload["variables"] = list(variables)
        node = mk_extension(
            self._nid("angle"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.angle_action", "state.next"),
            payload_schema=STATE_ANGLE_PAYLOAD_SCHEMA,
            payload=payload,
            children=(action,),
            range=span,
        )
        self._map(node, kind="angle_action", role="next")
        return node

    def _mk_fairness(
        self,
        *,
        strength: FairnessStrength,
        variables: tuple[str, ...],
        action: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        payload = self._base_payload("fairness")
        payload["schema_version"] = STATE_FAIRNESS_PAYLOAD_SCHEMA
        payload["strength"] = strength.value
        payload["variables"] = list(variables)
        node = mk_extension(
            self._nid("fair"),
            family=STATE_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("state.fairness", f"state.fairness.{strength.value}"),
            payload_schema=STATE_FAIRNESS_PAYLOAD_SCHEMA,
            payload=payload,
            children=(action,),
            range=span,
        )
        self._map(node, kind="fairness", role="fairness")
        return node


# ---------------------------------------------------------------------------
# CST / surface helpers
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:state:1",
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
        safe_kind = kind.replace(" ", "_")
        span = n.range or SourceRange(0, 0)
        meta: dict[str, Any] = {}
        if n.symbol:
            meta["symbol"] = n.symbol
        if n.extension is not None:
            meta["payload_schema"] = n.extension.payload_schema
            meta["features"] = list(n.extension.features)
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


# ---------------------------------------------------------------------------
# Semantic identity
# ---------------------------------------------------------------------------


def state_semantic_identity(
    node: LogicNode,
    profile: StatePropertyProfile,
) -> dict[str, Any]:
    """Build the semantic identity of *node* under *profile*."""

    def walk(n: LogicNode) -> Any:
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        if kind == NodeKind.EXTENSION.value and n.extension is not None:
            ext = n.extension
            payload = dict(ext.payload)
            return {
                "children": [walk(c) for c in ext.children],
                "features": list(ext.features),
                "kind": "extension",
                "payload": payload,
                "payload_schema": ext.payload_schema,
                "profile": ext.profile.value
                if hasattr(ext.profile, "value")
                else str(ext.profile),
            }
        if kind in {NodeKind.TRUE.value, NodeKind.FALSE.value}:
            return {"kind": kind}
        if kind == NodeKind.NOT.value:
            return {"args": [walk(n.arguments[0])], "kind": "not"}
        if kind in {
            NodeKind.AND.value,
            NodeKind.OR.value,
            NodeKind.IMPLIES.value,
            NodeKind.IFF.value,
        }:
            return {"args": [walk(a) for a in n.arguments], "kind": kind}
        return {
            "args": [walk(a) for a in n.arguments],
            "kind": kind,
            "symbol": n.symbol,
        }

    return {
        "formula": walk(node),
        "profile": profile.semantic_identity,
        "unbounded_proof": False,
    }


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class StatePropertyPrinter:
    """Deterministic printer for controlled state/TLA property expressions."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        if style not in {PrintStyle.ASCII, PrintStyle.UNICODE, PrintStyle.TLA}:
            raise SyntaxContractError(
                f"print style must be ascii/unicode/tla; got {style!r}"
            )
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            return self._print_node(node.root, _Prec.BOTTOM)
        if not isinstance(node, LogicNode):
            raise SyntaxContractError("print requires a LogicNode or TypedExpression")
        return self._print_node(node, _Prec.BOTTOM)

    def _and_op(self) -> str:
        if self.style == PrintStyle.UNICODE:
            return "∧"
        if self.style == PrintStyle.TLA:
            return "/\\"
        return "and"

    def _or_op(self) -> str:
        if self.style == PrintStyle.UNICODE:
            return "∨"
        if self.style == PrintStyle.TLA:
            return "\\/"
        return "or"

    def _not_op(self) -> str:
        if self.style == PrintStyle.UNICODE:
            return "¬"
        if self.style == PrintStyle.TLA:
            return "~"
        return "not"

    def _implies_op(self) -> str:
        if self.style == PrintStyle.UNICODE:
            return "→"
        if self.style == PrintStyle.TLA:
            return "=>"
        return "->"

    def _iff_op(self) -> str:
        if self.style == PrintStyle.UNICODE:
            return "↔"
        return "iff"

    def _print_node(self, node: LogicNode, parent_prec: int) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return "TRUE" if self.style == PrintStyle.TLA else "true"
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return "FALSE" if self.style == PrintStyle.TLA else "false"
        if kind is NodeKind.NOT or kind == NodeKind.NOT.value:
            inner = self._print_node(node.arguments[0], _Prec.UNARY)
            text = f"{self._not_op()} {inner}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            op = f" {self._and_op()} "
            text = op.join(self._print_node(a, _Prec.AND) for a in node.arguments)
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            op = f" {self._or_op()} "
            text = op.join(self._print_node(a, _Prec.OR) for a in node.arguments)
            return self._paren(text, _Prec.OR, parent_prec)
        if kind is NodeKind.IMPLIES or kind == NodeKind.IMPLIES.value:
            left = self._print_node(node.arguments[0], _Prec.IMPLIES + 1)
            right = self._print_node(node.arguments[1], _Prec.IMPLIES)
            text = f"{left} {self._implies_op()} {right}"
            return self._paren(text, _Prec.IMPLIES, parent_prec)
        if kind is NodeKind.IFF or kind == NodeKind.IFF.value:
            left = self._print_node(node.arguments[0], _Prec.IFF + 1)
            right = self._print_node(node.arguments[1], _Prec.IFF + 1)
            text = f"{left} {self._iff_op()} {right}"
            return self._paren(text, _Prec.IFF, parent_prec)
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, parent_prec)
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        assert node.extension is not None
        payload = dict(node.extension.payload)
        kind = str(payload.get("kind") or "")
        children = node.extension.children

        if kind == "literal":
            return str(payload.get("lexeme") or "")
        if kind == "variable":
            return str(payload.get("variable") or "")
        if kind == "prime":
            return f"{payload.get('variable')}'"
        if kind == "always":
            body = self._print_node(children[0], _Prec.UNARY)
            if self.style == PrintStyle.TLA:
                text = f"[]{body}"
            else:
                text = f"always {body}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind == "eventually":
            body = self._print_node(children[0], _Prec.UNARY)
            if self.style == PrintStyle.TLA:
                text = f"<>{body}"
            else:
                text = f"eventually {body}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind == "enabled":
            body = self._print_node(children[0], _Prec.UNARY)
            text = f"ENABLED {body}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind == "equality":
            left = self._print_node(children[0], _Prec.ATOM)
            right = self._print_node(children[1], _Prec.ATOM)
            return f"{left} = {right}"
        if kind == "membership":
            left = self._print_node(children[0], _Prec.ATOM)
            right = self._print_node(children[1], _Prec.ATOM)
            if self.style == PrintStyle.TLA:
                return f"{left} \\in {right}"
            return f"{left} in {right}"
        if kind == "unchanged":
            variables = list(payload.get("variables") or [])
            if len(variables) == 1:
                return f"UNCHANGED {variables[0]}"
            inner = ", ".join(variables)
            return f"UNCHANGED <<{inner}>>"
        if kind == "stuttering":
            action = self._print_node(children[0], _Prec.BOTTOM)
            variables = list(payload.get("variables") or ["vars"])
            v = variables[0] if len(variables) == 1 else ",".join(variables)
            return f"[{action}]_{v}"
        if kind == "angle_action":
            action = self._print_node(children[0], _Prec.BOTTOM)
            variables = list(payload.get("variables") or ["vars"])
            v = variables[0] if len(variables) == 1 else ",".join(variables)
            return f"<<{action}>>_{v}"
        if kind == "fairness":
            strength = str(payload.get("strength") or "weak")
            variables = list(payload.get("variables") or ["vars"])
            v = variables[0] if variables else "vars"
            action = self._print_node(children[0], _Prec.BOTTOM)
            prefix = "WF" if strength == "weak" else "SF"
            return f"{prefix}_{v}({action})"

        raise SyntaxContractError(f"unsupported state extension kind {kind!r}")

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# Public parser surface
# ---------------------------------------------------------------------------


def _collect_variables(node: LogicNode) -> tuple[str, ...]:
    found: list[str] = []

    def walk(n: LogicNode) -> None:
        if n.extension is not None:
            payload = dict(n.extension.payload)
            kind = payload.get("kind")
            if kind in {"variable", "prime"}:
                var = payload.get("variable")
                if isinstance(var, str) and var:
                    found.append(var)
            for key in ("variables",):
                vals = payload.get(key)
                if isinstance(vals, Sequence) and not isinstance(vals, (str, bytes)):
                    for item in vals:
                        if isinstance(item, str) and item:
                            found.append(item)
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(node)
    return tuple(sorted(set(found)))


def _signature_for_formula(
    root: LogicNode,
    profile: StatePropertyProfile,
) -> LogicSignature:
    variables = _collect_variables(root)
    if not variables:
        return LogicSignature(
            signature_id=f"sig:state:{profile.profile_id}",
            family=STATE_FAMILY_ID,
            profile=profile.profile_id,
            sorts=(),
            symbols=(),
            features=("state", "transition_system"),
        )
    return propositional_signature(
        f"sig:state:{profile.profile_id}",
        variables,
        family=STATE_FAMILY_ID,
        profile=profile.profile_id,
    )


def _extract_profile(value: object) -> StatePropertyProfile | None:
    if value is None:
        return None
    if isinstance(value, StatePropertyProfile):
        return value
    if isinstance(value, Mapping):
        return StatePropertyProfile.from_dict(value)
    return None


class StatePropertyParser:
    """Notation parser for controlled state/TLA properties (``StatePropertySyntax@1``)."""

    interface: ClassVar[str] = STATE_PROPERTY_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = STATE_NOTATION_ID
    notation_version: ClassVar[str] = STATE_NOTATION_VERSION

    def __init__(
        self,
        profile: StatePropertyProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
        variables: Sequence[str] | None = None,
    ) -> None:
        if profile is not None and not isinstance(profile, StatePropertyProfile):
            raise SyntaxContractError("profile must be a StatePropertyProfile")
        self.profile = profile
        self.printer = StatePropertyPrinter(style=print_style)
        self.variables = frozenset(variables) if variables is not None else None
        self._lexer = BoundedLexer(
            keywords=_STATE_KEYWORDS,
            multi_char_operators=_STATE_MULTI_OPS,
        )

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("state_property_profile"))
            or self.profile
        )
        vars_meta = request.metadata.get("variables")
        variables = (
            frozenset(str(item) for item in vars_meta)
            if isinstance(vars_meta, Sequence) and not isinstance(vars_meta, (str, bytes))
            else self.variables
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:state:1"
            ),
            variables=variables,
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: StatePropertyProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:state:1",
        expression_id: str = "expr:state:1",
        variables: frozenset[str] | None = None,
    ) -> StateParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="state property parse requires a StatePropertyProfile",
                range=document.full_range(),
                remediation="Pass profile=... or metadata['profile']",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": STATE_PROPERTY_SYNTAX_INTERFACE},
            )
            return StateParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        # Rewrite primes then re-wrap as a document for lexing.
        # Keep the same document_id so ParseArtifact.validate_against matches.
        original_text = document.text
        rewritten = rewrite_primes_for_lex(original_text)
        lex_document = (
            document
            if rewritten == original_text
            else SourceDocument.from_text(
                document.document_id,
                rewritten,
                encoding="utf-8",
            )
        )

        lex_result = self._lexer.lex(lex_document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:state:lex:{index + 1}",
                    code=CODE_LEXER_ERROR
                    if item.code.startswith("lexer.")
                    else item.code,
                    message=item.message,
                    severity=item.severity,
                    range=item.range,
                    remediation=item.remediation,
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
                metadata={"interface": STATE_PROPERTY_SYNTAX_INTERFACE},
            )
            return StateParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                checker_contract=prof.checker,
            )

        engine = _StateParserEngine(
            document=lex_document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
            variables=variables if variables is not None else self.variables,
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
                    "interface": STATE_PROPERTY_SYNTAX_INTERFACE,
                    "module_constructs": [
                        item.to_dict() for item in engine.module_constructs
                    ],
                    "profile": prof.to_dict(),
                    "unbounded_proof": False,
                },
            )
            return StateParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                source_map=tuple(engine.source_map),
                module_constructs=tuple(engine.module_constructs),
                checker_contract=prof.checker,
            )

        signature = _signature_for_formula(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=STATE_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        # CST covers the rewritten document (prime rewrite is internal).
        cst = _build_covering_cst(lex_document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        printed = self.printer.print(root)
        identity = state_semantic_identity(root, prof)
        source_map = tuple(engine.source_map)
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
                "checker_contract": prof.checker.to_dict()
                if prof.checker is not None
                else None,
                "controlled_tla_interface": CONTROLLED_TLA_PROPERTY_INTERFACE,
                "expression": expression.to_dict(),
                "interface": STATE_PROPERTY_SYNTAX_INTERFACE,
                "notation_id": STATE_NOTATION_ID,
                "notation_version": STATE_NOTATION_VERSION,
                "printed": printed,
                "profile": prof.to_dict(),
                "semantic_identity": identity,
                "source_map": [item.to_dict() for item in source_map],
                "unbounded_proof": False,
                "variables": list(_collect_variables(root)),
            },
        )
        # Validate against the lex document (rewritten) so spans cover tokens.
        artifact.validate_against(lex_document, limits=bounds)
        return StateParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            source_map=source_map,
            module_constructs=tuple(engine.module_constructs),
            checker_contract=prof.checker,
        )


class StatePropertySyntax:
    """Facade for controlled state property parse/print round-trips.

    Interface: ``StatePropertySyntax@1``.
    """

    interface: ClassVar[str] = STATE_PROPERTY_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = STATE_NOTATION_ID
    notation_version: ClassVar[str] = STATE_NOTATION_VERSION
    family_id: ClassVar[str] = STATE_FAMILY_ID

    def __init__(
        self,
        profile: StatePropertyProfile,
        *,
        print_style: str = PrintStyle.ASCII,
        variables: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(profile, StatePropertyProfile):
            raise SyntaxContractError("profile must be a StatePropertyProfile")
        self.profile = profile
        self.parser = StatePropertyParser(
            profile, print_style=print_style, variables=variables
        )
        self.printer = self.parser.printer

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:state:1",
        expression_id: str = "expr:state:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> StateParseResult:
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise StateParseError(
                result.errors[0].message if result.errors else "state parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def round_trip(self, text: str, **kwargs: Any) -> StateParseResult:
        first = self.parse_text(text, **kwargs)
        if not first.ok or first.root is None:
            return first
        printed = self.print(first.root)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:state:1") + ":rt",
            expression_id=str(kwargs.get("expression_id") or "expr:state:1") + ":rt",
            limits=kwargs.get("limits"),
            mode=kwargs.get("mode", ParseMode.STRICT),
        )
        if not second.ok or second.root is None:
            return second
        if not alpha_equivalent(first.root, second.root):
            diag = _diag(
                code=CODE_ROUND_TRIP,
                message="parse/print/parse is not alpha-equivalent",
                range=second.root.range,
            )
            return StateParseResult(
                status=ParseStatus.FAILED,
                root=second.root,
                expression=second.expression,
                diagnostics=second.diagnostics + (diag,),
                tokens=second.tokens,
                artifact=second.artifact,
                printed=printed,
                profile=self.profile,
                source_map=second.source_map,
                checker_contract=self.profile.checker,
            )
        return StateParseResult(
            status=ParseStatus.OK,
            root=second.root,
            expression=second.expression,
            diagnostics=second.diagnostics,
            tokens=second.tokens,
            artifact=second.artifact,
            printed=printed,
            profile=self.profile,
            source_map=second.source_map,
            checker_contract=self.profile.checker,
        )


class ControlledTLAProperty:
    """TLA-flavoured controlled property adapter (``ControlledTLAProperty@1``).

    Full modules remain declaration-only or unsupported.  Checker evidence is
    always finite/bounded and never promotes to unbounded proof.
    """

    interface: ClassVar[str] = CONTROLLED_TLA_PROPERTY_INTERFACE

    def __init__(
        self,
        profile: StatePropertyProfile | None = None,
        *,
        print_style: str = PrintStyle.TLA,
    ) -> None:
        self.profile = profile or profile_tla_tlc()
        if self.profile.checker is None:
            raise SyntaxContractError(
                "ControlledTLAProperty requires a checker evidence contract "
                "(use profile_tla_tlc or profile_tla_apalache)"
            )
        self.syntax = StatePropertySyntax(self.profile, print_style=print_style)

    @property
    def checker_contract(self) -> CheckerEvidenceContract:
        assert self.profile.checker is not None
        return self.profile.checker

    def parse_text(self, text: str, **kwargs: Any) -> StateParseResult:
        return self.syntax.parse_text(text, **kwargs)

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.syntax.print(node)

    def round_trip(self, text: str, **kwargs: Any) -> StateParseResult:
        return self.syntax.round_trip(text, **kwargs)

    def promote_to_unbounded_proof(
        self, result: StateParseResult | CheckerEvidenceContract | None = None
    ) -> None:
        """Always fail closed — TLC/Apalache cannot yield unbounded proofs."""

        contract = self.checker_contract
        if isinstance(result, CheckerEvidenceContract):
            contract = result
        elif isinstance(result, StateParseResult) and result.checker_contract is not None:
            contract = result.checker_contract
        contract.promote_to_unbounded_proof()

    def lowering_receipt(self, result: StateParseResult) -> dict[str, Any]:
        """Receipt for TLC/Apalache lowering of a controlled expression."""

        if not result.ok or result.root is None:
            raise StateParseError(
                "cannot lower a failed parse",
                diagnostics=result.diagnostics,
                result=result,
            )
        contract = result.checker_contract or self.checker_contract
        return {
            "bound": contract.bound.to_dict(),
            "checker": contract.to_dict(),
            "controlled_tla_interface": self.interface,
            "may_promote_to_unbounded_proof": False,
            "printed": result.printed or self.print(result.root),
            "source_map": [item.to_dict() for item in result.source_map],
            "unbounded_proof": False,
            "variables": list(_collect_variables(result.root)),
        }


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_state(
    text: str,
    profile: StatePropertyProfile,
    *,
    document_id: str = "doc:state:1",
    expression_id: str = "expr:state:1",
    limits: ParseLimits | None = None,
    print_style: str = PrintStyle.ASCII,
    variables: Sequence[str] | None = None,
) -> StateParseResult:
    """Parse *text* as a controlled state/TLA property under *profile*."""

    syntax = StatePropertySyntax(
        profile, print_style=print_style, variables=variables
    )
    return syntax.parse_text(
        text,
        document_id=document_id,
        expression_id=expression_id,
        limits=limits,
    )


def print_state(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    """Print *node* in controlled state/TLA notation."""

    return StatePropertyPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: StatePropertyProfile,
    *,
    style: str = PrintStyle.ASCII,
    variables: Sequence[str] | None = None,
) -> StateParseResult:
    """Parse/print/parse round-trip with alpha-equivalence check."""

    syntax = StatePropertySyntax(profile, print_style=style, variables=variables)
    return syntax.round_trip(text)


__all__ = [
    "CONTROLLED_TLA_PROPERTY_INTERFACE",
    "STATE_FAMILY_ID",
    "STATE_MODULE_VERSION",
    "STATE_NOTATION_ID",
    "STATE_NOTATION_VERSION",
    "STATE_PROPERTY_SYNTAX_INTERFACE",
    "CODE_DECLARATION_ONLY",
    "CODE_PROMOTION_REJECTED",
    "CODE_UNSUPPORTED_MODULE",
    "BoundednessKind",
    "CheckerEvidenceContract",
    "CheckerTool",
    "ControlledTLAProperty",
    "EvidenceAuthority",
    "FairnessStrength",
    "FiniteBoundContract",
    "ModuleConstructDisposition",
    "ModuleConstructRecord",
    "PrintStyle",
    "PropertyRole",
    "StateParseError",
    "StateParseResult",
    "StatePropertyParser",
    "StatePropertyPrinter",
    "StatePropertyProfile",
    "StatePropertySyntax",
    "StateSourceMapEntry",
    "apalache_evidence_contract",
    "module_construct_disposition",
    "parse_print_parse",
    "parse_state",
    "print_state",
    "profile_state_property",
    "profile_tla_apalache",
    "profile_tla_tlc",
    "rewrite_primes_for_lex",
    "state_semantic_identity",
    "tlc_evidence_contract",
]
