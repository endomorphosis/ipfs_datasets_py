"""HyperLTL and hyperproperty syntax with tool-fragment lowerings.

Interfaces:

* ``HyperpropertySyntax@1`` — parse/print/elaborate for controlled HyperLTL
  surface text with scoped trace binders and indexed propositions
* ``HyperLTLAdapter@1`` — lower parsed formulas to ``HyperpropertyIR@1``,
  enforce AutoHyper/MCHyper/EAHyper quantifier-fragment restrictions, and
  attach bounded/model-check authority ceilings that cannot be promoted

Trace quantifiers are prenex-only.  Binders are capture-safe: free or
out-of-scope trace variables fail closed, and rebinding a name already in
scope is rejected.  Unsupported quantifier alternation reports the exact
engine limit, observed alternation count, and quantifier signature.
Bounded self-composition and model-check evidence retain a declared
``bounded`` authority ceiling and never authorize universal proof.

Grammar (connective precedence, low → high)::

    formula         ::= quant_prefix matrix
    quant_prefix    ::= quant_binding+
    quant_binding   ::= ('forall'|'exists'|∀|∃) TRACE_IDENT '.'
    matrix          ::= iff_formula
    iff             ::= implies (('iff'|↔) implies)*
    implies         ::= or (('implies'|→|=>|->) matrix)?   # right-assoc
    or              ::= and (('or'|∨) and)*
    and             ::= binary_temporal (('and'|∧) binary_temporal)*
    binary_temporal ::= unary (('until'|U) unary)*
    unary           ::= temporal_unary unary | ('not'|¬) unary | atomic
    temporal_unary  ::= 'next'|'eventually'|'always'|'X'|'F'|'G'
    atomic          ::= 'true'|⊤ | 'false'|⊥
                      | IDENT '[' TRACE_IDENT ']'
                      | IDENT '_' TRACE_IDENT          # split form
                      | 'equal' '(' TRACE ',' TRACE ',' FIELD ')'
                      | 'noninterference' ni_args
                      | '(' matrix ')'
    ni_args         ::= 'low' '=' '[' idents ']' 'high' '=' '[' idents ']'
                        'obs' '=' '[' idents ']'

Evidence subset: forall, exists, trace prefix, alternation, indexed
proposition, tool fragment, bound, noninterference.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    DEFAULT_MAX_COMPOSITION_PAIRS,
    DEFAULT_MAX_COMPOSITION_TRACES,
    AuthorityPromotionError,
    EvidenceAuthorityCeiling,
    HyperpropertyEvidenceKind,
    HyperpropertyEvaluation,
    HyperpropertyFormula,
    HyperpropertyIR,
    HyperpropertyKind,
    HyperpropertyVerdict,
    InformationFlowPolicy,
    ObservationKind,
    ObservationSpec,
    QuantifierBinding,
    RelationalAtom,
    RelationalCondition,
    RelationalOperator,
    RelationalRole,
    SecurityLabel,
    SecurityLevel,
    SelfCompositionBound,
    TraceQuantifier,
    TraceVariable,
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
    propositional_signature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

HYPERPROPERTY_SYNTAX_INTERFACE: Final = "HyperpropertySyntax@1"
HYPERLTL_ADAPTER_INTERFACE: Final = "HyperLTLAdapter@1"
HYPER_NOTATION_ID: Final = "canonical_hyperltl"
HYPER_NOTATION_VERSION: Final = "1.0.0"
HYPER_FAMILY_ID: Final = "hyperproperty"
HYPER_MODULE_VERSION: Final = "1.0.0"
HYPER_PARSE_RESULT_SCHEMA_VERSION: Final = "canonical-hyper-parse-result/v1"
HYPER_PROFILE_SCHEMA_VERSION: Final = "hyperproperty-profile/v1"
HYPER_TRACE_SORT_NAME: Final = "Trace"
HYPER_TRACE_QUANT_PAYLOAD_SCHEMA: Final = "hyper.trace_quantifier/v1"
HYPER_INDEXED_PROP_PAYLOAD_SCHEMA: Final = "hyper.indexed_proposition/v1"
HYPER_TEMPORAL_PAYLOAD_SCHEMA: Final = "hyper.temporal/v1"
HYPER_RELATIONAL_PAYLOAD_SCHEMA: Final = "hyper.relational/v1"
HYPER_NI_PAYLOAD_SCHEMA: Final = "hyper.noninterference/v1"
HYPER_TOOL_FRAGMENT_SCHEMA: Final = "hyper.tool-fragment/v1"
HYPER_BOUND_CONTRACT_SCHEMA: Final = "hyper.bound-contract/v1"
HYPER_EVIDENCE_CONTRACT_SCHEMA: Final = "hyper.evidence-contract/v1"
HYPER_LOWERING_RECEIPT_SCHEMA: Final = "hyper.lowering-receipt/v1"
HYPER_SOURCE_MAP_SCHEMA: Final = "hyper.source-map/v1"

TRACE_SORT: Final = atomic_sort(HYPER_TRACE_SORT_NAME)

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "hyper.unexpected_token"
CODE_TRAILING_INPUT: Final = "hyper.trailing_input"
CODE_EMPTY_INPUT: Final = "hyper.empty_input"
CODE_PARSE_DEPTH: Final = "hyper.parse_depth_exceeded"
CODE_UNBALANCED: Final = "hyper.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "hyper.lexer_error"
CODE_FREE_TRACE_VAR: Final = "hyper.free_trace_variable"
CODE_REBIND_TRACE_VAR: Final = "hyper.trace_variable_rebind"
CODE_EMPTY_PREFIX: Final = "hyper.empty_quantifier_prefix"
CODE_UNSUPPORTED_ALTERNATION: Final = "hyper.unsupported_alternation"
CODE_PROFILE_MISMATCH: Final = "hyper.profile_mismatch"
CODE_ROUND_TRIP: Final = "hyper.round_trip_failed"
CODE_PROMOTION_REJECTED: Final = "hyper.unbounded_promotion_rejected"
CODE_MISSING_BOUND: Final = "hyper.missing_bound"
CODE_INVALID_NI: Final = "hyper.invalid_noninterference"
CODE_NESTED_QUANTIFIER: Final = "hyper.nested_quantifier_rejected"
CODE_TOOL_FRAGMENT: Final = "hyper.tool_fragment_violation"
CODE_AUTHORITY_CEILING: Final = "hyper.invalid_authority_ceiling"

_ALL_HYPER_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_FREE_TRACE_VAR,
        CODE_REBIND_TRACE_VAR,
        CODE_EMPTY_PREFIX,
        CODE_UNSUPPORTED_ALTERNATION,
        CODE_PROFILE_MISMATCH,
        CODE_ROUND_TRIP,
        CODE_PROMOTION_REJECTED,
        CODE_MISSING_BOUND,
        CODE_INVALID_NI,
        CODE_NESTED_QUANTIFIER,
        CODE_TOOL_FRAGMENT,
        CODE_AUTHORITY_CEILING,
    }
)

# Connectives / operators.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "|", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})
_FORALL_OPS: Final[frozenset[str]] = frozenset({"forall", "∀"})
_EXISTS_OPS: Final[frozenset[str]] = frozenset({"exists", "∃"})
_NEXT_WORDS: Final[frozenset[str]] = frozenset({"next", "X"})
_EVENTUALLY_WORDS: Final[frozenset[str]] = frozenset({"eventually", "F"})
_ALWAYS_WORDS: Final[frozenset[str]] = frozenset({"always", "G"})
_UNTIL_WORDS: Final[frozenset[str]] = frozenset({"until", "U"})

_UNARY_CANON: Final[Mapping[str, str]] = {
    "next": "next",
    "x": "next",
    "eventually": "eventually",
    "f": "eventually",
    "always": "always",
    "g": "always",
}
_BINARY_CANON: Final[Mapping[str, str]] = {
    "until": "until",
    "u": "until",
}

_HYPER_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "forall",
    "exists",
    "next",
    "eventually",
    "always",
    "until",
    "equal",
    "noninterference",
    "low",
    "high",
    "obs",
)

_INDEX_SPLIT_RE: Final = re.compile(
    r"^(?P<prop>[A-Za-z][A-Za-z0-9]*)_(?P<trace>[A-Za-z][A-Za-z0-9_]*)$"
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class HyperToolKind(str, Enum):
    """Native HyperLTL-family engines with independent fragment ceilings."""

    EAHYPER = "eahyper"
    AUTOHYPER = "autohyper"
    MCHYPER = "mchyper"
    GENERIC = "generic"


class HyperLogicKind(str, Enum):
    """Declared hyperproperty surface family."""

    HYPERLTL = "hyperltl"
    INFORMATION_FLOW = "information_flow"
    NONINTERFERENCE = "noninterference"


class BoundednessKind(str, Enum):
    """Semantic bound declared for hyperproperty evidence."""

    FINITE_SELF_COMPOSITION = "finite_self_composition"
    MODEL_CHECK = "model_check"
    UNBOUNDED = "unbounded"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by hyperproperty evidence (never universal proof)."""

    BOUNDED = "bounded"
    ADVISORY = "advisory"
    NONE = "none"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    BINARY_TEMP = 50
    UNARY = 60
    ATOM = 70


# ---------------------------------------------------------------------------
# Tool fragment ceilings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolFragmentCeiling:
    """Quantifier-fragment restriction for one HyperLTL engine route.

    Alternation is counted as switches between consecutive quantifiers in
    declaration order (``forall exists forall`` has two alternations).
    """

    tool: HyperToolKind | str
    max_quantifier_alternations: int
    max_trace_variables: int
    supports_exists_forall: bool = True
    supports_forall_exists: bool = True
    description: str = ""
    schema_version: str = HYPER_TOOL_FRAGMENT_SCHEMA

    def __post_init__(self) -> None:
        tool = (
            self.tool
            if isinstance(self.tool, HyperToolKind)
            else HyperToolKind(str(self.tool))
        )
        if (
            isinstance(self.max_quantifier_alternations, bool)
            or not isinstance(self.max_quantifier_alternations, int)
            or self.max_quantifier_alternations < 0
        ):
            raise SyntaxContractError(
                "max_quantifier_alternations must be a non-negative integer"
            )
        if (
            isinstance(self.max_trace_variables, bool)
            or not isinstance(self.max_trace_variables, int)
            or self.max_trace_variables < 1
        ):
            raise SyntaxContractError("max_trace_variables must be a positive integer")
        if not isinstance(self.supports_exists_forall, bool):
            raise SyntaxContractError("supports_exists_forall must be a boolean")
        if not isinstance(self.supports_forall_exists, bool):
            raise SyntaxContractError("supports_forall_exists must be a boolean")
        object.__setattr__(self, "tool", tool)
        object.__setattr__(
            self,
            "description",
            str(self.description or "").strip(),
        )
        if self.schema_version != HYPER_TOOL_FRAGMENT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported tool-fragment schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "max_quantifier_alternations": self.max_quantifier_alternations,
            "max_trace_variables": self.max_trace_variables,
            "schema_version": self.schema_version,
            "supports_exists_forall": self.supports_exists_forall,
            "supports_forall_exists": self.supports_forall_exists,
            "tool": self.tool.value
            if isinstance(self.tool, HyperToolKind)
            else str(self.tool),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ToolFragmentCeiling:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("tool fragment must be a mapping")
        return cls(
            tool=value.get("tool", HyperToolKind.GENERIC.value),
            max_quantifier_alternations=int(
                value.get("max_quantifier_alternations", 4)
            ),
            max_trace_variables=int(value.get("max_trace_variables", 8)),
            supports_exists_forall=bool(value.get("supports_exists_forall", True)),
            supports_forall_exists=bool(value.get("supports_forall_exists", True)),
            description=str(value.get("description") or ""),
            schema_version=str(
                value.get("schema_version") or HYPER_TOOL_FRAGMENT_SCHEMA
            ),
        )


def fragment_eahyper() -> ToolFragmentCeiling:
    """EAHyper decidable fragment (exists*/forall* or forall*/exists*)."""

    return ToolFragmentCeiling(
        tool=HyperToolKind.EAHYPER,
        max_quantifier_alternations=1,
        max_trace_variables=8,
        supports_exists_forall=True,
        supports_forall_exists=True,
        description=(
            "EAHyper decidable HyperLTL fragment "
            "(exists*/forall* and forall*/exists*; not full HyperLTL)"
        ),
    )


def fragment_autohyper() -> ToolFragmentCeiling:
    """AutoHyper automata-based HyperLTL fragment."""

    return ToolFragmentCeiling(
        tool=HyperToolKind.AUTOHYPER,
        max_quantifier_alternations=2,
        max_trace_variables=4,
        supports_exists_forall=True,
        supports_forall_exists=True,
        description="AutoHyper targets automata-based HyperLTL with limited alternation",
    )


def fragment_mchyper() -> ToolFragmentCeiling:
    """MCHyper model-checking HyperLTL fragment under finite models."""

    return ToolFragmentCeiling(
        tool=HyperToolKind.MCHYPER,
        max_quantifier_alternations=2,
        max_trace_variables=4,
        supports_exists_forall=True,
        supports_forall_exists=True,
        description="MCHyper checks HyperLTL under finite system models only",
    )


def fragment_generic(*, max_alternations: int = 4) -> ToolFragmentCeiling:
    """Generic HyperLTL fragment used when no tool route is selected."""

    return ToolFragmentCeiling(
        tool=HyperToolKind.GENERIC,
        max_quantifier_alternations=max_alternations,
        max_trace_variables=16,
        supports_exists_forall=True,
        supports_forall_exists=True,
        description="Generic HyperLTL fragment without engine-specific caps",
    )


# ---------------------------------------------------------------------------
# Bound / evidence contracts (authority ceiling retained)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperBoundContract:
    """Explicit finite bound for self-composition or model-check lowerings."""

    max_traces: int = DEFAULT_MAX_COMPOSITION_TRACES
    max_pairs: int = DEFAULT_MAX_COMPOSITION_PAIRS
    max_steps: int = 64
    boundedness: BoundednessKind | str = BoundednessKind.FINITE_SELF_COMPOSITION
    schema_version: str = HYPER_BOUND_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        for name in ("max_traces", "max_pairs", "max_steps"):
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
                "HyperBoundContract rejects unboundedness; hyperproperty "
                "results retain a finite/model-check ceiling"
            )
        object.__setattr__(self, "boundedness", bound)
        if self.schema_version != HYPER_BOUND_CONTRACT_SCHEMA:
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
            "max_pairs": self.max_pairs,
            "max_steps": self.max_steps,
            "max_traces": self.max_traces,
            "schema_version": self.schema_version,
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HyperBoundContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("bound contract must be a mapping")
        return cls(
            max_traces=int(value.get("max_traces", DEFAULT_MAX_COMPOSITION_TRACES)),
            max_pairs=int(value.get("max_pairs", DEFAULT_MAX_COMPOSITION_PAIRS)),
            max_steps=int(value.get("max_steps", 64)),
            boundedness=value.get(
                "boundedness", BoundednessKind.FINITE_SELF_COMPOSITION.value
            ),
            schema_version=str(
                value.get("schema_version") or HYPER_BOUND_CONTRACT_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class HyperEvidenceContract:
    """Authority ceiling for bounded / model-check hyperproperty results.

    Successful finite self-composition and model-check outcomes are
    ``bounded`` evidence only.  Promotion to universal/unbounded proof is
    always rejected and the declared ceiling is retained on every receipt.
    """

    tool: HyperToolKind | str
    bound: HyperBoundContract
    authority: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    schema_version: str = HYPER_EVIDENCE_CONTRACT_SCHEMA

    interface: ClassVar[str] = HYPERLTL_ADAPTER_INTERFACE

    def __post_init__(self) -> None:
        tool = (
            self.tool
            if isinstance(self.tool, HyperToolKind)
            else HyperToolKind(str(self.tool))
        )
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        if not isinstance(self.bound, HyperBoundContract):
            raise SyntaxContractError("bound must be a HyperBoundContract")
        if authority is EvidenceAuthority.BOUNDED:
            if self.bound.boundedness is BoundednessKind.UNBOUNDED:
                raise SyntaxContractError(
                    "bounded authority requires a finite or model-check bound"
                )
        elif authority not in {EvidenceAuthority.NONE, EvidenceAuthority.ADVISORY}:
            raise SyntaxContractError(
                "hyperproperty evidence admits only none/advisory/bounded authority"
            )
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "authority", authority)
        if self.schema_version != HYPER_EVIDENCE_CONTRACT_SCHEMA:
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
        return auth if isinstance(auth, EvidenceAuthority) else EvidenceAuthority(str(auth))

    def promote_to_unbounded_proof(self) -> None:
        """Fail closed: bounded/model-check results are not universal proofs."""

        auth = self.authority_ceiling
        tool = self.tool.value if isinstance(self.tool, HyperToolKind) else str(self.tool)
        bound = (
            self.bound.boundedness.value
            if isinstance(self.bound.boundedness, BoundednessKind)
            else str(self.bound.boundedness)
        )
        raise SyntaxContractError(
            f"{tool} bounded/model-check results cannot be promoted to "
            f"unbounded proof (authority={auth.value}, boundedness={bound})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority_ceiling.value,
            "authority_ceiling": self.authority_ceiling.value,
            "bound": self.bound.to_dict(),
            "interface": self.interface,
            "may_promote_to_unbounded_proof": False,
            "schema_version": self.schema_version,
            "tool": self.tool.value
            if isinstance(self.tool, HyperToolKind)
            else str(self.tool),
            "unbounded_proof": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HyperEvidenceContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("evidence contract must be a mapping")
        raw_bound = value.get("bound")
        bound = (
            raw_bound
            if isinstance(raw_bound, HyperBoundContract)
            else HyperBoundContract.from_dict(
                raw_bound if isinstance(raw_bound, Mapping) else {}
            )
        )
        return cls(
            tool=value.get("tool", HyperToolKind.GENERIC.value),
            bound=bound,
            authority=value.get("authority", EvidenceAuthority.BOUNDED.value),
            schema_version=str(
                value.get("schema_version") or HYPER_EVIDENCE_CONTRACT_SCHEMA
            ),
        )


def model_check_evidence_contract(
    *,
    tool: HyperToolKind | str = HyperToolKind.MCHYPER,
    max_steps: int = 64,
    max_traces: int = 8,
) -> HyperEvidenceContract:
    """Model-check evidence contract (never unbounded proof)."""

    return HyperEvidenceContract(
        tool=tool,
        bound=HyperBoundContract(
            max_traces=max_traces,
            max_pairs=max(1, max_traces * max(0, max_traces - 1) // 2),
            max_steps=max_steps,
            boundedness=BoundednessKind.MODEL_CHECK,
        ),
        authority=EvidenceAuthority.BOUNDED,
    )


def self_composition_evidence_contract(
    *,
    max_traces: int = DEFAULT_MAX_COMPOSITION_TRACES,
    max_pairs: int = DEFAULT_MAX_COMPOSITION_PAIRS,
    max_steps: int = 64,
) -> HyperEvidenceContract:
    """Bounded self-composition evidence contract (never unbounded proof)."""

    return HyperEvidenceContract(
        tool=HyperToolKind.GENERIC,
        bound=HyperBoundContract(
            max_traces=max_traces,
            max_pairs=max_pairs,
            max_steps=max_steps,
            boundedness=BoundednessKind.FINITE_SELF_COMPOSITION,
        ),
        authority=EvidenceAuthority.BOUNDED,
    )


# ---------------------------------------------------------------------------
# Semantic profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperpropertyProfile:
    """Explicit hyperproperty/HyperLTL semantic choices.

    Logic kind, tool fragment, and evidence bound participate in semantic
    identity.  Alternation ceilings are never inferred from spelling alone.
    """

    profile_id: str
    logic: HyperLogicKind | str = HyperLogicKind.HYPERLTL
    tool_fragment: ToolFragmentCeiling = field(default_factory=fragment_generic)
    evidence: HyperEvidenceContract = field(
        default_factory=self_composition_evidence_contract
    )
    admit_classic_letters: bool = True
    require_prenex: bool = True
    schema_version: str = HYPER_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = HYPERPROPERTY_SYNTAX_INTERFACE

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
            if isinstance(self.logic, HyperLogicKind)
            else HyperLogicKind(str(self.logic))
        )
        object.__setattr__(self, "logic", logic)
        if not isinstance(self.tool_fragment, ToolFragmentCeiling):
            raise SyntaxContractError("tool_fragment must be a ToolFragmentCeiling")
        if not isinstance(self.evidence, HyperEvidenceContract):
            raise SyntaxContractError("evidence must be a HyperEvidenceContract")
        if not isinstance(self.admit_classic_letters, bool):
            raise SyntaxContractError("admit_classic_letters must be a boolean")
        if not isinstance(self.require_prenex, bool):
            raise SyntaxContractError("require_prenex must be a boolean")
        if self.schema_version != HYPER_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported HyperpropertyProfile schema {self.schema_version!r}"
            )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_classic_letters": self.admit_classic_letters,
            "evidence": self.evidence.to_dict(),
            "logic": self.logic.value
            if isinstance(self.logic, HyperLogicKind)
            else str(self.logic),
            "profile_id": self.profile_id,
            "require_prenex": self.require_prenex,
            "schema_version": self.schema_version,
            "tool_fragment": self.tool_fragment.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_identity

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HyperpropertyProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("hyperproperty profile must be a mapping")
        raw_fragment = value.get("tool_fragment")
        fragment = (
            raw_fragment
            if isinstance(raw_fragment, ToolFragmentCeiling)
            else ToolFragmentCeiling.from_dict(
                raw_fragment if isinstance(raw_fragment, Mapping) else {}
            )
        )
        raw_evidence = value.get("evidence")
        evidence = (
            raw_evidence
            if isinstance(raw_evidence, HyperEvidenceContract)
            else HyperEvidenceContract.from_dict(
                raw_evidence if isinstance(raw_evidence, Mapping) else {}
            )
        )
        return cls(
            profile_id=str(value.get("profile_id") or "hyperltl"),
            logic=value.get("logic", HyperLogicKind.HYPERLTL.value),
            tool_fragment=fragment,
            evidence=evidence,
            admit_classic_letters=bool(value.get("admit_classic_letters", True)),
            require_prenex=bool(value.get("require_prenex", True)),
            schema_version=str(
                value.get("schema_version") or HYPER_PROFILE_SCHEMA_VERSION
            ),
        )


def profile_hyperltl(
    *,
    tool: HyperToolKind | str = HyperToolKind.GENERIC,
) -> HyperpropertyProfile:
    """Default HyperLTL profile with a generic or tool-specific fragment."""

    tool_kind = tool if isinstance(tool, HyperToolKind) else HyperToolKind(str(tool))
    fragments = {
        HyperToolKind.EAHYPER: fragment_eahyper,
        HyperToolKind.AUTOHYPER: fragment_autohyper,
        HyperToolKind.MCHYPER: fragment_mchyper,
        HyperToolKind.GENERIC: fragment_generic,
    }
    evidence = (
        model_check_evidence_contract(tool=tool_kind)
        if tool_kind is HyperToolKind.MCHYPER
        else self_composition_evidence_contract()
    )
    if tool_kind is not HyperToolKind.GENERIC and tool_kind is not HyperToolKind.MCHYPER:
        evidence = HyperEvidenceContract(
            tool=tool_kind,
            bound=HyperBoundContract(
                boundedness=BoundednessKind.MODEL_CHECK,
            ),
            authority=EvidenceAuthority.BOUNDED,
        )
    return HyperpropertyProfile(
        profile_id=f"hyperltl:{tool_kind.value}",
        logic=HyperLogicKind.HYPERLTL,
        tool_fragment=fragments[tool_kind](),
        evidence=evidence,
    )


def profile_noninterference() -> HyperpropertyProfile:
    """Classical two-trace noninterference profile (forall/forall)."""

    return HyperpropertyProfile(
        profile_id="hyperltl:noninterference",
        logic=HyperLogicKind.NONINTERFERENCE,
        tool_fragment=fragment_generic(max_alternations=0),
        evidence=self_composition_evidence_contract(),
    )


# ---------------------------------------------------------------------------
# Alternation analysis
# ---------------------------------------------------------------------------


def quantifier_alternation_count(signature: Sequence[str]) -> int:
    """Count quantifier alternations (forall/exists switches) in order."""

    if not signature:
        return 0
    count = 0
    previous = signature[0]
    for item in signature[1:]:
        if item != previous:
            count += 1
            previous = item
    return count


@dataclass(frozen=True, slots=True)
class AlternationReport:
    """Exact cause description for a supported or rejected quantifier prefix."""

    supported: bool
    alternation_count: int
    quantifier_signature: tuple[str, ...]
    cause: str
    tool: str
    max_alternations: int
    max_trace_variables: int
    schema_version: str = HYPER_TOOL_FRAGMENT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternation_count": self.alternation_count,
            "cause": self.cause,
            "max_alternations": self.max_alternations,
            "max_trace_variables": self.max_trace_variables,
            "quantifier_signature": list(self.quantifier_signature),
            "schema_version": self.schema_version,
            "supported": self.supported,
            "tool": self.tool,
        }


def check_quantifier_fragment(
    signature: Sequence[str],
    fragment: ToolFragmentCeiling,
) -> AlternationReport:
    """Validate *signature* against *fragment* and report the exact cause."""

    tool = (
        fragment.tool.value
        if isinstance(fragment.tool, HyperToolKind)
        else str(fragment.tool)
    )
    sig = tuple(str(item) for item in signature)
    alternations = quantifier_alternation_count(sig)
    n_vars = len(sig)

    if n_vars == 0:
        return AlternationReport(
            supported=False,
            alternation_count=0,
            quantifier_signature=sig,
            cause="quantifier prefix is empty",
            tool=tool,
            max_alternations=fragment.max_quantifier_alternations,
            max_trace_variables=fragment.max_trace_variables,
        )
    if n_vars > fragment.max_trace_variables:
        return AlternationReport(
            supported=False,
            alternation_count=alternations,
            quantifier_signature=sig,
            cause=(
                f"{tool} supports at most {fragment.max_trace_variables} "
                f"trace variables; got {n_vars}"
            ),
            tool=tool,
            max_alternations=fragment.max_quantifier_alternations,
            max_trace_variables=fragment.max_trace_variables,
        )
    if alternations > fragment.max_quantifier_alternations:
        return AlternationReport(
            supported=False,
            alternation_count=alternations,
            quantifier_signature=sig,
            cause=(
                f"{tool} supports at most "
                f"{fragment.max_quantifier_alternations} quantifier "
                f"alternations; got {alternations} "
                f"(signature={' '.join(sig)})"
            ),
            tool=tool,
            max_alternations=fragment.max_quantifier_alternations,
            max_trace_variables=fragment.max_trace_variables,
        )
    if "exists" in sig and "forall" in sig:
        first_exists = sig.index("exists")
        first_forall = sig.index("forall")
        if first_exists < first_forall and not fragment.supports_exists_forall:
            return AlternationReport(
                supported=False,
                alternation_count=alternations,
                quantifier_signature=sig,
                cause=(
                    f"{tool} does not support exists-forall prefixes "
                    f"(signature={' '.join(sig)})"
                ),
                tool=tool,
                max_alternations=fragment.max_quantifier_alternations,
                max_trace_variables=fragment.max_trace_variables,
            )
        if first_forall < first_exists and not fragment.supports_forall_exists:
            return AlternationReport(
                supported=False,
                alternation_count=alternations,
                quantifier_signature=sig,
                cause=(
                    f"{tool} does not support forall-exists prefixes "
                    f"(signature={' '.join(sig)})"
                ),
                tool=tool,
                max_alternations=fragment.max_quantifier_alternations,
                max_trace_variables=fragment.max_trace_variables,
            )
    return AlternationReport(
        supported=True,
        alternation_count=alternations,
        quantifier_signature=sig,
        cause="",
        tool=tool,
        max_alternations=fragment.max_quantifier_alternations,
        max_trace_variables=fragment.max_trace_variables,
    )


# ---------------------------------------------------------------------------
# Diagnostics / parse failures
# ---------------------------------------------------------------------------


class HyperParseError(SyntaxContractError):
    """Raised when HyperLTL/hyperproperty parsing fails closed."""

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
        diagnostic_id=f"diag:hyper:{code.replace('.', '-')}",
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


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
        if token.lexeme in lexemes or token.lexeme.casefold() in {
            item.casefold() for item in lexemes
        }:
            # Prefer exact then casefold membership for single-letter ops.
            folded = {item.casefold() for item in lexemes}
            if token.lexeme in lexemes or token.lexeme.casefold() in folded:
                self.advance()
                return token
        return None

    def expect_lexeme(self, lexeme: str, *, code: str = CODE_UNEXPECTED_TOKEN) -> LogicToken:
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
        if token.kind not in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
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
        return SourceRange(start=min(start.start, end.start), end=max(start.end, end.end))


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _HyperParserEngine:
    """Recursive-descent HyperLTL parser with scoped trace binders."""

    def __init__(
        self,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: HyperpropertyProfile,
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
        self._prefix: list[tuple[str, str, SourceRange]] = []  # (quant, name, span)
        self._ni_template: dict[str, Any] | None = None

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
                    message="empty HyperLTL input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_hyper_formula()
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

    def _parse_hyper_formula(self) -> LogicNode:
        self._enter()
        try:
            self._parse_quantifier_prefix()
            if not self._prefix:
                raise _ParseFail(
                    _diag(
                        code=CODE_EMPTY_PREFIX,
                        message=(
                            "HyperLTL formulas require a non-empty prenex "
                            "trace-quantifier prefix"
                        ),
                        range=self.cursor.current().range,
                        remediation="Write e.g. forall pi1. forall pi2. always p[pi1]",
                    )
                )
            # Enforce tool-fragment alternation before parsing matrix so the
            # cause is exact and independent of matrix shape.
            signature = tuple(item[0] for item in self._prefix)
            report = check_quantifier_fragment(
                signature, self.profile.tool_fragment
            )
            if not report.supported:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_ALTERNATION,
                        message=report.cause,
                        range=self._prefix[0][2],
                        remediation=(
                            "Reduce quantifier alternations or select a tool "
                            "fragment that admits the prefix shape"
                        ),
                        metadata=report.to_dict(),
                    )
                )
            matrix = self._parse_matrix()
            return self._wrap_prefix(matrix)
        finally:
            self._leave()

    def _parse_quantifier_prefix(self) -> None:
        while True:
            token = self.cursor.current()
            quant: str | None = None
            if token.lexeme in _FORALL_OPS or token.lexeme.casefold() == "forall":
                quant = "forall"
            elif token.lexeme in _EXISTS_OPS or token.lexeme.casefold() == "exists":
                quant = "exists"
            if quant is None:
                return
            start = self.cursor.advance()
            name_tok = self.cursor.expect_ident()
            name = name_tok.lexeme
            if name in self._scope:
                raise _ParseFail(
                    _diag(
                        code=CODE_REBIND_TRACE_VAR,
                        message=(
                            f"trace variable {name!r} is already bound in the "
                            "quantifier prefix (rebinding is capture-unsafe)"
                        ),
                        range=name_tok.range,
                        remediation="Choose a fresh trace variable name",
                        metadata={"variable": name, "scope": list(self._scope)},
                    )
                )
            self.cursor.expect_lexeme(".", code=CODE_UNEXPECTED_TOKEN)
            self._scope.append(name)
            span = self.cursor.range_span(start.range, name_tok.range)
            self._prefix.append((quant, name, span))

    def _wrap_prefix(self, matrix: LogicNode) -> LogicNode:
        node = matrix
        # Nest quantifiers from the inside out so the outermost binder is first.
        # Trace binders use core FORALL/EXISTS (EXTENSION nodes reject binders),
        # keeping capture-safe free-variable analysis on the shared AST.
        for quant, name, span in reversed(self._prefix):
            binder = Binder(name=name, sort=TRACE_SORT)
            body_span = node.range or span
            full_span = self.cursor.range_span(span, body_span)
            node_id = self._nid(quant)
            if quant == "forall":
                built = mk_forall(node_id, (binder,), node)
            else:
                built = mk_exists(node_id, (binder,), node)
            node = LogicNode(
                node_id=built.node_id,
                kind=built.kind,
                sort=BOOL_SORT,
                binders=built.binders,
                arguments=built.arguments,
                range=full_span,
                metadata={
                    "hyper_trace_quantifier": True,
                    "profile_id": self.profile.profile_id,
                    "quantifier": quant,
                    "schema_version": HYPER_TRACE_QUANT_PAYLOAD_SCHEMA,
                    "variable": name,
                },
            )
        return node

    def _parse_matrix(self) -> LogicNode:
        # Reject nested quantifiers inside the matrix (prenex-only HyperLTL).
        token = self.cursor.current()
        if (
            token.lexeme in _FORALL_OPS
            or token.lexeme in _EXISTS_OPS
            or token.lexeme.casefold() in {"forall", "exists"}
        ):
            raise _ParseFail(
                _diag(
                    code=CODE_NESTED_QUANTIFIER,
                    message=(
                        "nested trace quantifiers inside the matrix are rejected; "
                        "HyperLTL surface is prenex-only"
                    ),
                    range=token.range,
                    remediation="Move all forall/exists binders to the quantifier prefix",
                )
            )
        return self._parse_iff()

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
            # Right-associative.
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
        while self.cursor.match_any(_OR_OPS) is not None:
            nodes.append(self._parse_and())
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
        nodes = [self._parse_binary_temporal()]
        while self.cursor.match_any(_AND_OPS) is not None:
            nodes.append(self._parse_binary_temporal())
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

    def _parse_binary_temporal(self) -> LogicNode:
        left = self._parse_unary()
        while True:
            op = self._match_binary_temporal()
            if op is None:
                return left
            op_token, operator = op
            right = self._parse_unary()
            span = self.cursor.range_span(
                left.range or op_token.range, right.range or op_token.range
            )
            left = self._mk_temporal(
                operator, children=(left, right), span=span
            )

    def _parse_unary(self) -> LogicNode:
        temporal = self._match_unary_temporal()
        if temporal is not None:
            op_token, operator = temporal
            self._enter()
            try:
                body = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(
                op_token.range, body.range or op_token.range
            )
            return self._mk_temporal(operator, children=(body,), span=span)

        not_tok = self.cursor.match_any(_NOT_OPS)
        if not_tok is not None:
            self._enter()
            try:
                inner = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(not_tok.range, inner.range or not_tok.range)
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
            # Nested quantifiers rejected via _parse_matrix path? Use matrix.
            # But matrix doesn't re-check if we're inside parens after quantifiers
            # already consumed — re-check for nested quantifiers.
            token = self.cursor.current()
            if (
                token.lexeme in _FORALL_OPS
                or token.lexeme in _EXISTS_OPS
                or token.lexeme.casefold() in {"forall", "exists"}
            ):
                raise _ParseFail(
                    _diag(
                        code=CODE_NESTED_QUANTIFIER,
                        message=(
                            "nested trace quantifiers are rejected; "
                            "HyperLTL surface is prenex-only"
                        ),
                        range=token.range,
                    )
                )
            inner = self._parse_iff()
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
            node = mk_true(self._nid("true"))
            return LogicNode(
                node_id=node.node_id,
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=token.range,
            )
        token = self.cursor.match_any(_FALSE_OPS)
        if token is not None:
            node = mk_false(self._nid("false"))
            return LogicNode(
                node_id=node.node_id,
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=token.range,
            )

        current = self.cursor.current()
        if current.lexeme.casefold() == "equal":
            return self._parse_equal_atom()
        if current.lexeme.casefold() == "noninterference":
            return self._parse_noninterference_template()

        if current.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            return self._parse_indexed_or_plain(current)

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {current.lexeme!r}",
                range=current.range,
            )
        )

    def _require_bound_trace(self, name: str, span: SourceRange) -> None:
        if name not in self._scope:
            raise _ParseFail(
                _diag(
                    code=CODE_FREE_TRACE_VAR,
                    message=(
                        f"trace variable {name!r} is free or out of scope; "
                        f"bound variables are {list(self._scope)!r}"
                    ),
                    range=span,
                    remediation=(
                        "Bind the trace variable in the prenex prefix before use"
                    ),
                    metadata={
                        "variable": name,
                        "bound": list(self._scope),
                    },
                )
            )

    def _parse_indexed_or_plain(self, current: LogicToken) -> LogicNode:
        """Parse ``p[pi]``, ``p_pi`` (split), or reject bare unindexed atoms."""

        name = current.lexeme
        self.cursor.advance()

        # Bracket form: IDENT '[' TRACE ']'
        if self.cursor.match_lexeme("[") is not None:
            trace_tok = self.cursor.expect_ident()
            close = self.cursor.expect_lexeme("]", code=CODE_UNBALANCED)
            self._require_bound_trace(trace_tok.lexeme, trace_tok.range)
            span = self.cursor.range_span(current.range, close.range)
            return self._mk_indexed(name, trace_tok.lexeme, span)

        # Underscore-split form: single token ``p_pi1`` where suffix is bound.
        match = _INDEX_SPLIT_RE.fullmatch(name)
        if match is not None:
            prop = match.group("prop")
            trace = match.group("trace")
            if trace in self._scope:
                return self._mk_indexed(prop, trace, current.range)
            # If the full name is somehow a bound var (unlikely), fall through.

        # Bare identifiers are not HyperLTL atoms without a trace index.
        raise _ParseFail(
            _diag(
                code=CODE_FREE_TRACE_VAR
                if match is not None and match.group("trace") not in self._scope
                else CODE_UNEXPECTED_TOKEN,
                message=(
                    f"proposition {name!r} is not a trace-indexed atom; "
                    "write p[pi] or p_pi for a bound trace variable pi"
                    if match is None
                    else (
                        f"trace variable {match.group('trace')!r} in indexed "
                        f"proposition {name!r} is free or out of scope; "
                        f"bound variables are {list(self._scope)!r}"
                    )
                ),
                range=current.range,
                remediation="Index the proposition with a bound trace variable",
                metadata={
                    "symbol": name,
                    "bound": list(self._scope),
                },
            )
        )

    def _parse_equal_atom(self) -> LogicNode:
        start = self.cursor.advance()  # 'equal'
        self.cursor.expect_lexeme("(")
        left_tok = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        right_tok = self.cursor.expect_ident()
        self.cursor.expect_lexeme(",")
        field_tok = self.cursor.expect_ident()
        close = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        self._require_bound_trace(left_tok.lexeme, left_tok.range)
        self._require_bound_trace(right_tok.lexeme, right_tok.range)
        span = self.cursor.range_span(start.range, close.range)
        payload = {
            "field": field_tok.lexeme,
            "kind": "relational_equal",
            "left": left_tok.lexeme,
            "profile_id": self.profile.profile_id,
            "right": right_tok.lexeme,
            "schema_version": HYPER_RELATIONAL_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid("equal"),
            family=HYPER_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("hyper.relational", "hyper.relational.equal"),
            payload_schema=HYPER_RELATIONAL_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_noninterference_template(self) -> LogicNode:
        start = self.cursor.advance()  # 'noninterference'
        low = self._parse_ni_field_list("low")
        high = self._parse_ni_field_list("high")
        obs = self._parse_ni_field_list("obs")
        if not obs:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_NI,
                    message="noninterference template requires at least one observation field",
                    range=start.range,
                )
            )
        if set(low) & set(high):
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_NI,
                    message="noninterference low and high field lists must be disjoint",
                    range=start.range,
                    metadata={"low": low, "high": high},
                )
            )
        if set(high) & set(obs):
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_NI,
                    message=(
                        "high inputs cannot also be approved observations "
                        "without declassification"
                    ),
                    range=start.range,
                )
            )
        # Noninterference requires exactly two universally quantified traces.
        if len(self._prefix) != 2 or any(q != "forall" for q, _, _ in self._prefix):
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_NI,
                    message=(
                        "noninterference template requires a classical "
                        "forall/forall two-trace prefix"
                    ),
                    range=start.range,
                    metadata={
                        "prefix": [q for q, _, _ in self._prefix],
                    },
                )
            )
        span = start.range
        payload = {
            "high_fields": list(high),
            "kind": "noninterference",
            "low_fields": list(low),
            "observation_fields": list(obs),
            "profile_id": self.profile.profile_id,
            "schema_version": HYPER_NI_PAYLOAD_SCHEMA,
            "traces": [name for _, name, _ in self._prefix],
        }
        self._ni_template = payload
        return mk_extension(
            self._nid("ni"),
            family=HYPER_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("hyper.noninterference",),
            payload_schema=HYPER_NI_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )

    def _parse_ni_field_list(self, label: str) -> tuple[str, ...]:
        tok = self.cursor.current()
        if tok.lexeme.casefold() != label:
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_NI,
                    message=f"expected noninterference field label {label!r}",
                    range=tok.range,
                )
            )
        self.cursor.advance()
        self.cursor.expect_lexeme("=")
        self.cursor.expect_lexeme("[")
        fields: list[str] = []
        if self.cursor.current().lexeme != "]":
            fields.append(self.cursor.expect_ident().lexeme)
            while self.cursor.match_lexeme(",") is not None:
                fields.append(self.cursor.expect_ident().lexeme)
        self.cursor.expect_lexeme("]", code=CODE_UNBALANCED)
        if len(fields) != len(set(fields)):
            raise _ParseFail(
                _diag(
                    code=CODE_INVALID_NI,
                    message=f"duplicate field in noninterference {label} list",
                    range=tok.range,
                )
            )
        return tuple(fields)

    def _match_unary_temporal(self) -> tuple[LogicToken, str] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        raw = token.lexeme
        folded = raw.casefold()
        if raw in _NEXT_WORDS or folded in {"next"}:
            if raw == "X" and not self.profile.admit_classic_letters:
                return None
            self.cursor.advance()
            return token, "next"
        if raw in _EVENTUALLY_WORDS or folded in {"eventually"}:
            if raw == "F" and not self.profile.admit_classic_letters:
                return None
            self.cursor.advance()
            return token, "eventually"
        if raw in _ALWAYS_WORDS or folded in {"always"}:
            if raw == "G" and not self.profile.admit_classic_letters:
                return None
            self.cursor.advance()
            return token, "always"
        canon = _UNARY_CANON.get(folded)
        if canon is not None and folded not in {"x", "f", "g"}:
            self.cursor.advance()
            return token, canon
        return None

    def _match_binary_temporal(self) -> tuple[LogicToken, str] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        raw = token.lexeme
        folded = raw.casefold()
        if raw in _UNTIL_WORDS or folded == "until":
            if raw == "U" and not self.profile.admit_classic_letters:
                return None
            self.cursor.advance()
            return token, "until"
        return None

    def _mk_temporal(
        self,
        operator: str,
        *,
        children: Sequence[LogicNode],
        span: SourceRange,
    ) -> LogicNode:
        payload: dict[str, Any] = {
            "kind": operator,
            "logic": self.profile.logic.value
            if isinstance(self.profile.logic, HyperLogicKind)
            else str(self.profile.logic),
            "profile_id": self.profile.profile_id,
            "schema_version": HYPER_TEMPORAL_PAYLOAD_SCHEMA,
        }
        return mk_extension(
            self._nid(operator),
            family=HYPER_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(f"hyper.temporal.{operator}",),
            payload_schema=HYPER_TEMPORAL_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(children),
            range=span,
        )

    def _mk_indexed(
        self, proposition: str, trace: str, span: SourceRange
    ) -> LogicNode:
        payload = {
            "kind": "indexed_proposition",
            "profile_id": self.profile.profile_id,
            "proposition": proposition,
            "schema_version": HYPER_INDEXED_PROP_PAYLOAD_SCHEMA,
            "trace_variable": trace,
        }
        return mk_extension(
            self._nid("atom"),
            family=HYPER_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("hyper.indexed_proposition",),
            payload_schema=HYPER_INDEXED_PROP_PAYLOAD_SCHEMA,
            payload=payload,
            children=(),
            range=span,
        )


# ---------------------------------------------------------------------------
# CST / surface helpers
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:hyper:1",
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
        if n.binders:
            meta["binders"] = [b.name for b in n.binders]
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
# Semantic identity / free-trace analysis
# ---------------------------------------------------------------------------


def _is_trace_quantifier(node: LogicNode) -> bool:
    if node.kind in {NodeKind.FORALL, NodeKind.EXISTS}:
        if node.metadata.get("hyper_trace_quantifier"):
            return True
        # Trace-sorted binders are treated as hypertrace quantifiers.
        return bool(node.binders) and all(
            b.sort.name == HYPER_TRACE_SORT_NAME for b in node.binders
        )
    return False


def extract_quantifier_prefix(node: LogicNode) -> tuple[tuple[str, str], ...]:
    """Return ``((quantifier, variable), ...)`` in outer-to-inner order."""

    result: list[tuple[str, str]] = []

    def walk(n: LogicNode) -> LogicNode:
        if _is_trace_quantifier(n) and n.binders and n.arguments:
            quant = (
                "forall"
                if n.kind is NodeKind.FORALL or n.kind == NodeKind.FORALL.value
                else "exists"
            )
            result.append((quant, n.binders[0].name))
            return walk(n.arguments[0])
        return n

    walk(node)
    return tuple(result)


def extract_matrix(node: LogicNode) -> LogicNode:
    """Strip prenex trace quantifiers and return the matrix formula."""

    current = node
    while _is_trace_quantifier(current) and current.arguments:
        current = current.arguments[0]
    return current


def free_trace_variables(node: LogicNode) -> frozenset[str]:
    """Compute free (unbound) trace variables under capture-safe scoping."""

    def walk(n: LogicNode, bound: frozenset[str]) -> set[str]:
        free: set[str] = set()
        if _is_trace_quantifier(n) and n.binders and n.arguments:
            inner_bound = bound | {b.name for b in n.binders}
            free |= walk(n.arguments[0], inner_bound)
            return free
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            kind = payload.get("kind")
            if kind == "indexed_proposition":
                var = str(payload.get("trace_variable") or "")
                if var and var not in bound:
                    free.add(var)
                return free
            if kind == "relational_equal":
                for key in ("left", "right"):
                    var = str(payload.get(key) or "")
                    if var and var not in bound:
                        free.add(var)
                return free
            if kind == "noninterference":
                return free
            for child in n.extension.children:
                free |= walk(child, bound)
            return free
        for child in n.arguments:
            free |= walk(child, bound)
        return free

    return frozenset(walk(node, frozenset()))


def hyper_semantic_identity(
    node: LogicNode,
    profile: HyperpropertyProfile,
) -> dict[str, Any]:
    """Build the semantic identity of *node* under *profile*."""

    def walk(n: LogicNode) -> Any:
        kind = n.kind.value if isinstance(n.kind, NodeKind) else str(n.kind)
        if kind in {NodeKind.FORALL.value, NodeKind.EXISTS.value}:
            return {
                "binders": [
                    {"name": b.name, "sort": b.sort.name} for b in n.binders
                ],
                "body": walk(n.arguments[0]) if n.arguments else None,
                "kind": kind,
            }
        if kind == NodeKind.EXTENSION.value and n.extension is not None:
            ext = n.extension
            payload = dict(ext.payload)
            return {
                "children": [walk(c) for c in ext.children],
                "features": list(ext.features),
                "kind": "extension",
                "payload": payload,
                "payload_schema": ext.payload_schema,
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
        "free_trace_variables": sorted(free_trace_variables(node)),
        "profile": profile.semantic_identity,
        "quantifier_prefix": [
            {"quantifier": q, "variable": v}
            for q, v in extract_quantifier_prefix(node)
        ],
    }


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class HyperPrinter:
    """Deterministic printer for HyperLTL formulas.

    Parenthesization makes implication associativity and binder scope explicit
    so parse(print(parse(s))) is alpha-equivalent to parse(s).
    """

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
            raise SyntaxContractError("print requires a LogicNode or TypedExpression")
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
            text = op.join(self._print_node(a, _Prec.AND) for a in node.arguments)
            return self._paren(text, _Prec.AND, parent_prec)
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            op = f" {self._op('or', '∨')} "
            text = op.join(self._print_node(a, _Prec.OR) for a in node.arguments)
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
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_quantifier(
        self,
        ascii_kw: str,
        unicode_kw: str,
        node: LogicNode,
        parent_prec: int,
    ) -> str:
        var = node.binders[0].name if node.binders else "pi"
        body = (
            self._print_node(node.arguments[0], _Prec.BOTTOM)
            if node.arguments
            else "true"
        )
        text = f"{self._op(ascii_kw, unicode_kw)} {var}. {body}"
        return self._paren(text, _Prec.BOTTOM, parent_prec)

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        assert node.extension is not None
        payload = dict(node.extension.payload)
        kind = str(payload.get("kind") or "")
        children = node.extension.children

        if kind == "indexed_proposition":
            prop = str(payload.get("proposition") or "p")
            trace = str(payload.get("trace_variable") or "pi")
            return f"{prop}[{trace}]"

        if kind == "relational_equal":
            left = str(payload.get("left") or "pi1")
            right = str(payload.get("right") or "pi2")
            field_name = str(payload.get("field") or "obs")
            return f"equal({left}, {right}, {field_name})"

        if kind == "noninterference":
            low = ", ".join(str(x) for x in payload.get("low_fields") or ())
            high = ", ".join(str(x) for x in payload.get("high_fields") or ())
            obs = ", ".join(str(x) for x in payload.get("observation_fields") or ())
            return (
                f"noninterference low=[{low}] high=[{high}] obs=[{obs}]"
            )

        if kind in {"next", "eventually", "always"}:
            op_map = {
                "next": ("next", "X"),
                "eventually": ("eventually", "F"),
                "always": ("always", "G"),
            }
            ascii_op, _uni = op_map[kind]
            body = self._print_node(children[0], _Prec.UNARY) if children else "true"
            text = f"{ascii_op} {body}"
            return self._paren(text, _Prec.UNARY, parent_prec)

        if kind == "until":
            left = (
                self._print_node(children[0], _Prec.BINARY_TEMP)
                if children
                else "true"
            )
            right = (
                self._print_node(children[1], _Prec.BINARY_TEMP)
                if len(children) > 1
                else "true"
            )
            text = f"{left} until {right}"
            return self._paren(text, _Prec.BINARY_TEMP, parent_prec)

        raise SyntaxContractError(f"unsupported hyper extension kind {kind!r}")

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperParseResult:
    """Structured result of one HyperLTL parse attempt."""

    status: ParseStatus
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    expression: TypedExpression | None = None
    root: LogicNode | None = None
    profile: HyperpropertyProfile | None = None
    quantifier_signature: tuple[str, ...] = ()
    alternation_report: AlternationReport | None = None
    printed: str = ""
    schema_version: str = HYPER_PARSE_RESULT_SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternation_report": (
                None
                if self.alternation_report is None
                else self.alternation_report.to_dict()
            ),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "ok": self.ok,
            "printed": self.printed,
            "profile": None if self.profile is None else self.profile.to_dict(),
            "quantifier_signature": list(self.quantifier_signature),
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, ParseStatus)
            else str(self.status),
        }


def _signature_for_formula(
    root: LogicNode,
    profile: HyperpropertyProfile,
) -> LogicSignature:
    props: list[str] = []

    def walk(n: LogicNode) -> None:
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            if payload.get("kind") == "indexed_proposition":
                prop = str(payload.get("proposition") or "")
                if prop:
                    props.append(prop)
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(root)
    atoms = tuple(sorted(set(props)))
    if not atoms:
        return LogicSignature(
            signature_id=f"sig:hyper:{profile.profile_id}",
            family=HYPER_FAMILY_ID,
            profile=profile.profile_id,
            sorts=(TRACE_SORT,),
            symbols=(),
            features=("hyperproperty", "hyperltl"),
        )
    base = propositional_signature(
        f"sig:hyper:{profile.profile_id}",
        atoms,
        family=HYPER_FAMILY_ID,
        profile=profile.profile_id,
    )
    # Rebuild with Trace sort present for binders.
    return LogicSignature(
        signature_id=base.signature_id,
        family=HYPER_FAMILY_ID,
        profile=profile.profile_id,
        sorts=(TRACE_SORT, *base.sorts),
        symbols=base.symbols,
        features=tuple(sorted(set(base.features) | {"hyperproperty", "hyperltl"})),
    )


def _extract_profile(value: object) -> HyperpropertyProfile | None:
    if value is None:
        return None
    if isinstance(value, HyperpropertyProfile):
        return value
    if isinstance(value, Mapping):
        return HyperpropertyProfile.from_dict(value)
    return None


# ---------------------------------------------------------------------------
# Public parser facade
# ---------------------------------------------------------------------------


class HyperpropertyParser:
    """Notation parser for HyperLTL / hyperproperty syntax.

    Interface: ``HyperpropertySyntax@1``.
    """

    interface: ClassVar[str] = HYPERPROPERTY_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = HYPER_NOTATION_ID
    notation_version: ClassVar[str] = HYPER_NOTATION_VERSION

    def __init__(
        self,
        profile: HyperpropertyProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, HyperpropertyProfile):
            raise SyntaxContractError("profile must be a HyperpropertyProfile")
        self.profile = profile
        self.printer = HyperPrinter(style=print_style)
        self._lexer = BoundedLexer(keywords=_HYPER_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("hyperproperty_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:hyper:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: HyperpropertyProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:hyper:1",
        expression_id: str = "expr:hyper:1",
    ) -> HyperParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message="hyperproperty parse requires a HyperpropertyProfile",
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
                metadata={"interface": HYPERPROPERTY_SYNTAX_INTERFACE},
            )
            return HyperParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:hyper:lex:{index + 1}",
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
                metadata={"interface": HYPERPROPERTY_SYNTAX_INTERFACE},
            )
            return HyperParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _HyperParserEngine(
            document=document,
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
                    "interface": HYPERPROPERTY_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            # Surface alternation metadata when present.
            alt = None
            for item in all_diags:
                if item.code == CODE_UNSUPPORTED_ALTERNATION and item.metadata:
                    alt = AlternationReport(
                        supported=False,
                        alternation_count=int(
                            item.metadata.get("alternation_count", 0)
                        ),
                        quantifier_signature=tuple(
                            item.metadata.get("quantifier_signature") or ()
                        ),
                        cause=item.message,
                        tool=str(item.metadata.get("tool") or ""),
                        max_alternations=int(
                            item.metadata.get("max_alternations", 0)
                        ),
                        max_trace_variables=int(
                            item.metadata.get("max_trace_variables", 0)
                        ),
                    )
                    break
            return HyperParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                alternation_report=alt,
            )

        # Capture-safety post-check (should already be empty by construction).
        free = free_trace_variables(root)
        if free:
            diag = _diag(
                code=CODE_FREE_TRACE_VAR,
                message=(
                    f"formula has free trace variables {sorted(free)!r} "
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
                metadata={"interface": HYPERPROPERTY_SYNTAX_INTERFACE},
            )
            return HyperParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags + (diag,),
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        prefix = extract_quantifier_prefix(root)
        signature = tuple(q for q, _ in prefix)
        report = check_quantifier_fragment(signature, prof.tool_fragment)
        sig = _signature_for_formula(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=sig,
            family=HYPER_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(document, lex_result.tokens)
        surface = tuple(_surface_from_node(root))
        printed = self.printer.print(root)
        identity = hyper_semantic_identity(root, prof)
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
                "interface": HYPERPROPERTY_SYNTAX_INTERFACE,
                "expression": expression.to_dict(),
                "notation_id": HYPER_NOTATION_ID,
                "notation_version": HYPER_NOTATION_VERSION,
                "printed": printed,
                "profile": prof.to_dict(),
                "quantifier_signature": list(signature),
                "alternation_report": report.to_dict(),
                "authority_ceiling": prof.evidence.authority_ceiling.value,
                "source_map_schema": HYPER_SOURCE_MAP_SCHEMA,
                "semantic_identity": identity,
            },
        )
        return HyperParseResult(
            status=ParseStatus.OK,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            expression=expression,
            root=root,
            profile=prof,
            quantifier_signature=signature,
            alternation_report=report,
            printed=printed,
        )


class HyperpropertySyntax:
    """Facade for ``HyperpropertySyntax@1``."""

    interface: ClassVar[str] = HYPERPROPERTY_SYNTAX_INTERFACE

    def __init__(
        self,
        profile: HyperpropertyProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile if profile is not None else profile_hyperltl()
        self.parser = HyperpropertyParser(self.profile, print_style=print_style)
        self.printer = self.parser.printer

    def parse_text(self, text: str, **kwargs: Any) -> HyperParseResult:
        document = SourceDocument.from_text(
            str(kwargs.pop("document_id", "doc:hyper:1")),
            text,
            encoding="utf-8",
        )
        return self.parser.parse_document(
            document,
            profile=kwargs.pop("profile", self.profile),
            mode=kwargs.pop("mode", ParseMode.STRICT),
            limits=kwargs.pop("limits", None),
            request_id=str(kwargs.pop("request_id", "req:hyper:1")),
            expression_id=str(kwargs.pop("expression_id", "expr:hyper:1")),
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            messages = "; ".join(d.message for d in result.diagnostics) or "parse failed"
            raise HyperParseError(
                messages,
                code=(
                    result.diagnostics[0].code
                    if result.diagnostics
                    else CODE_UNEXPECTED_TOKEN
                ),
                diagnostics=result.diagnostics,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)


# ---------------------------------------------------------------------------
# HyperLTLAdapter@1 — lowerings to HyperpropertyIR
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyperLoweringReceipt:
    """Receipt for one HyperLTL → HyperpropertyIR lowering.

    Always retains the declared authority ceiling; never claims universal proof.
    """

    formula_id: str
    quantifier_signature: tuple[str, ...]
    alternation_count: int
    tool: str
    fragment_supported: bool
    fragment_cause: str
    authority_ceiling: str
    bound: dict[str, Any]
    document_id: str = ""
    authorizes_universal_proof: bool = False
    schema_version: str = HYPER_LOWERING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.authorizes_universal_proof:
            raise AuthorityPromotionError(
                "HyperLTL lowerings cannot authorize universal proof"
            )
        if self.authority_ceiling not in {
            EvidenceAuthority.BOUNDED.value,
            EvidenceAuthority.ADVISORY.value,
            EvidenceAuthority.NONE.value,
            EvidenceAuthorityCeiling.BOUNDED.value,
            EvidenceAuthorityCeiling.ADVISORY.value,
            EvidenceAuthorityCeiling.NONE.value,
        }:
            raise SyntaxContractError(
                f"invalid authority ceiling for hyper lowering: "
                f"{self.authority_ceiling!r}"
            )
        object.__setattr__(self, "authorizes_universal_proof", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternation_count": self.alternation_count,
            "authority_ceiling": self.authority_ceiling,
            "authorizes_universal_proof": False,
            "bound": dict(self.bound),
            "document_id": self.document_id,
            "formula_id": self.formula_id,
            "fragment_cause": self.fragment_cause,
            "fragment_supported": self.fragment_supported,
            "quantifier_signature": list(self.quantifier_signature),
            "schema_version": self.schema_version,
            "tool": self.tool,
        }


@dataclass(frozen=True, slots=True)
class HyperLoweringResult:
    """Outcome of lowering a parsed HyperLTL formula to HyperpropertyIR."""

    document: HyperpropertyIR
    receipt: HyperLoweringReceipt
    expression: TypedExpression | None = None
    root: LogicNode | None = None

    @property
    def authority_ceiling(self) -> str:
        return self.receipt.authority_ceiling

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "document": self.document.to_dict(),
            "receipt": self.receipt.to_dict(),
        }


class HyperLTLAdapter:
    """Lower HyperLTL surface formulas to ``HyperpropertyIR@1``.

    Interface: ``HyperLTLAdapter@1``.

    Tool-fragment checks remain explicit: unsupported alternation raises with
    the exact cause.  Bounded and model-check results retain the declared
    authority ceiling on every receipt and evaluation wrapper.
    """

    interface: ClassVar[str] = HYPERLTL_ADAPTER_INTERFACE

    def __init__(
        self,
        profile: HyperpropertyProfile | None = None,
    ) -> None:
        self.profile = profile if profile is not None else profile_hyperltl()
        self.syntax = HyperpropertySyntax(self.profile)

    def parse(self, text: str, **kwargs: Any) -> HyperParseResult:
        return self.syntax.parse_text(text, **kwargs)

    def lower_text(self, text: str, **kwargs: Any) -> HyperLoweringResult:
        result = self.syntax.parse_text(text, **kwargs)
        if not result.ok or result.root is None:
            messages = "; ".join(d.message for d in result.diagnostics) or "parse failed"
            code = (
                result.diagnostics[0].code
                if result.diagnostics
                else CODE_UNEXPECTED_TOKEN
            )
            raise HyperParseError(
                messages,
                code=code,
                diagnostics=result.diagnostics,
            )
        return self.lower_node(
            result.root,
            expression=result.expression,
            profile=result.profile or self.profile,
        )

    def lower_node(
        self,
        root: LogicNode,
        *,
        expression: TypedExpression | None = None,
        profile: HyperpropertyProfile | None = None,
        formula_id: str = "formula:hyperltl",
        policy_id: str = "policy:hyper:1",
    ) -> HyperLoweringResult:
        prof = profile or self.profile
        prefix = extract_quantifier_prefix(root)
        if not prefix:
            raise HyperParseError(
                "cannot lower a formula without a quantifier prefix",
                code=CODE_EMPTY_PREFIX,
            )
        signature = tuple(q for q, _ in prefix)
        report = check_quantifier_fragment(signature, prof.tool_fragment)
        if not report.supported:
            raise HyperParseError(
                report.cause,
                code=CODE_UNSUPPORTED_ALTERNATION,
                diagnostics=(
                    _diag(
                        code=CODE_UNSUPPORTED_ALTERNATION,
                        message=report.cause,
                        metadata=report.to_dict(),
                    ),
                ),
            )

        matrix = extract_matrix(root)
        ni = _find_noninterference(matrix)
        variables = tuple(
            TraceVariable(variable_id=f"var:{name}", name=name)
            for _, name in prefix
        )
        quantifier_prefix = tuple(
            QuantifierBinding(
                binding_id=f"bind:{index}",
                quantifier=(
                    TraceQuantifier.FORALL
                    if quant == "forall"
                    else TraceQuantifier.EXISTS
                ),
                variable_id=f"var:{name}",
                index=index,
            )
            for index, (quant, name) in enumerate(prefix)
        )

        if ni is not None:
            low = tuple(str(x) for x in ni.get("low_fields") or ())
            high = tuple(str(x) for x in ni.get("high_fields") or ())
            obs = tuple(str(x) for x in ni.get("observation_fields") or ())
            policy = InformationFlowPolicy(
                policy_id=policy_id,
                low_input_fields=low,
                high_input_fields=high,
                observation_fields=obs,
                labels=tuple(
                    SecurityLabel(
                        label_id=f"label:{field}",
                        field=field,
                        level=SecurityLevel.LOW
                        if field in low or field in obs
                        else SecurityLevel.HIGH,
                        kind=ObservationKind.INPUT
                        if field in low or field in high
                        else ObservationKind.OUTPUT,
                    )
                    for field in (*low, *high, *obs)
                ),
                observations=tuple(
                    ObservationSpec(
                        observation_id=f"obs:{field}",
                        field=field,
                        kind=ObservationKind.OUTPUT,
                        level=SecurityLevel.LOW,
                    )
                    for field in obs
                ),
                description="Lowered noninterference template",
            )
            formula = HyperpropertyFormula.noninterference(
                formula_id=formula_id,
                policy_id=policy.policy_id,
                left_name=variables[0].name,
                right_name=variables[1].name,
            )
        else:
            # General HyperLTL matrix: collect relational equals + indexed props.
            equals = _collect_relational_equals(matrix)
            indexed = _collect_indexed_props(matrix)
            observation_fields = tuple(
                sorted({item["field"] for item in equals} | set(indexed))
            ) or ("observable",)
            low_fields = observation_fields
            policy = InformationFlowPolicy(
                policy_id=policy_id,
                low_input_fields=low_fields,
                high_input_fields=(),
                observation_fields=observation_fields,
                observations=tuple(
                    ObservationSpec(
                        observation_id=f"obs:{field}",
                        field=field,
                        kind=ObservationKind.OUTPUT,
                        level=SecurityLevel.LOW,
                    )
                    for field in observation_fields
                ),
                description="Lowered general HyperLTL matrix",
            )
            preconditions: tuple[RelationalCondition, ...] = ()
            postconditions: tuple[RelationalCondition, ...] = ()
            if equals:
                atoms = tuple(
                    RelationalAtom(
                        atom_id=f"atom:{index}",
                        operator=RelationalOperator.EQUAL,
                        field=item["field"],
                        trace_variable_ids=(
                            f"var:{item['left']}",
                            f"var:{item['right']}",
                        ),
                    )
                    for index, item in enumerate(equals)
                )
                postconditions = (
                    RelationalCondition(
                        condition_id="cond:relational-equals",
                        role=RelationalRole.POSTCONDITION,
                        atoms=atoms,
                        description="Relational equalities from the matrix",
                    ),
                )
            matrix_text = HyperPrinter().print(root)
            formula = HyperpropertyFormula(
                formula_id=formula_id,
                kind=HyperpropertyKind.GENERAL,
                variables=variables,
                quantifier_prefix=quantifier_prefix,
                matrix_statement=matrix_text,
                information_flow_policy_id=policy.policy_id,
                preconditions=preconditions,
                postconditions=postconditions,
                description="Lowered HyperLTL formula",
            )

        bound_contract = prof.evidence.bound
        ir_bound = SelfCompositionBound(
            bound_id="bound:lowered",
            max_traces=bound_contract.max_traces,
            max_pairs=bound_contract.max_pairs,
            max_steps=bound_contract.max_steps,
            description=(
                f"Declared {bound_contract.boundedness.value if isinstance(bound_contract.boundedness, BoundednessKind) else bound_contract.boundedness} "
                f"ceiling under {prof.evidence.authority_ceiling.value} authority"
            ),
        )
        document = HyperpropertyIR(
            formula=formula,
            information_flow_policy=policy,
            self_composition_bound=ir_bound,
            metadata={
                "adapter": HYPERLTL_ADAPTER_INTERFACE,
                "profile_id": prof.profile_id,
                "tool": (
                    prof.tool_fragment.tool.value
                    if isinstance(prof.tool_fragment.tool, HyperToolKind)
                    else str(prof.tool_fragment.tool)
                ),
            },
        )
        receipt = HyperLoweringReceipt(
            formula_id=formula.formula_id,
            quantifier_signature=signature,
            alternation_count=report.alternation_count,
            tool=report.tool,
            fragment_supported=True,
            fragment_cause="",
            authority_ceiling=prof.evidence.authority_ceiling.value,
            bound=bound_contract.to_dict(),
            document_id=document.document_id,
            authorizes_universal_proof=False,
        )
        return HyperLoweringResult(
            document=document,
            receipt=receipt,
            expression=expression,
            root=root,
        )

    def retain_authority_ceiling(
        self,
        evaluation: HyperpropertyEvaluation | Mapping[str, Any],
        *,
        contract: HyperEvidenceContract | None = None,
    ) -> dict[str, Any]:
        """Re-emit an evaluation under the declared authority ceiling.

        Rejects any attempt to inflate the ceiling beyond the contract or to
        claim ``authorizes_universal_proof``.
        """

        evidence = contract or self.profile.evidence
        ceiling = evidence.authority_ceiling.value
        if isinstance(evaluation, HyperpropertyEvaluation):
            payload = evaluation.to_dict()
        elif isinstance(evaluation, Mapping):
            payload = dict(evaluation)
        else:
            raise SyntaxContractError("evaluation must be a HyperpropertyEvaluation or mapping")

        claimed = str(payload.get("authority_ceiling") or ceiling)
        if claimed not in {
            EvidenceAuthority.BOUNDED.value,
            EvidenceAuthority.ADVISORY.value,
            EvidenceAuthority.NONE.value,
            ceiling,
        }:
            raise SyntaxContractError(
                f"evaluation authority ceiling {claimed!r} is not admitted; "
                f"declared ceiling is {ceiling!r}"
            )
        # Never promote above the contract ceiling.
        rank = {
            EvidenceAuthority.NONE.value: 0,
            EvidenceAuthority.ADVISORY.value: 1,
            EvidenceAuthority.BOUNDED.value: 2,
        }
        if rank.get(claimed, -1) > rank.get(ceiling, -1):
            raise SyntaxContractError(
                f"evaluation cannot inflate authority from {ceiling!r} to {claimed!r}"
            )
        if payload.get("authorizes_universal_proof") not in (None, False):
            raise AuthorityPromotionError(
                "bounded/model-check hyperproperty results cannot authorize "
                "universal proof"
            )
        retained = dict(payload)
        retained["authority_ceiling"] = ceiling
        retained["authorizes_universal_proof"] = False
        retained["bounded"] = True
        retained["evidence_contract"] = evidence.to_dict()
        return retained

    def promote_to_unbounded_proof(self) -> None:
        """Fail closed: adapter results never become unbounded proofs."""

        self.profile.evidence.promote_to_unbounded_proof()


def _find_noninterference(node: LogicNode) -> dict[str, Any] | None:
    if node.kind is NodeKind.EXTENSION and node.extension is not None:
        payload = dict(node.extension.payload)
        if payload.get("kind") == "noninterference":
            return payload
        for child in node.extension.children:
            found = _find_noninterference(child)
            if found is not None:
                return found
    for child in node.arguments:
        found = _find_noninterference(child)
        if found is not None:
            return found
    return None


def _collect_relational_equals(node: LogicNode) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def walk(n: LogicNode) -> None:
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            if payload.get("kind") == "relational_equal":
                found.append(
                    {
                        "field": str(payload.get("field") or ""),
                        "left": str(payload.get("left") or ""),
                        "right": str(payload.get("right") or ""),
                    }
                )
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(node)
    return found


def _collect_indexed_props(node: LogicNode) -> list[str]:
    found: list[str] = []

    def walk(n: LogicNode) -> None:
        if n.kind is NodeKind.EXTENSION and n.extension is not None:
            payload = dict(n.extension.payload)
            if payload.get("kind") == "indexed_proposition":
                prop = str(payload.get("proposition") or "")
                if prop:
                    found.append(prop)
            for child in n.extension.children:
                walk(child)
        for child in n.arguments:
            walk(child)

    walk(node)
    return found


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_hyper(
    text: str,
    profile: HyperpropertyProfile | None = None,
    **kwargs: Any,
) -> HyperParseResult:
    """Parse HyperLTL *text* under *profile* (default generic HyperLTL)."""

    syntax = HyperpropertySyntax(profile or profile_hyperltl())
    return syntax.parse_text(text, **kwargs)


def print_hyper(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    """Print a HyperLTL AST deterministically."""

    return HyperPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: HyperpropertyProfile | None = None,
) -> tuple[HyperParseResult, HyperParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_hyperltl()
    first = parse_hyper(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_hyper(first.root)
    second = parse_hyper(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


def lower_hyperltl(
    text: str,
    profile: HyperpropertyProfile | None = None,
    **kwargs: Any,
) -> HyperLoweringResult:
    """Parse and lower HyperLTL *text* through ``HyperLTLAdapter@1``."""

    adapter = HyperLTLAdapter(profile or profile_hyperltl())
    return adapter.lower_text(text, **kwargs)


__all__ = [
    "HYPERPROPERTY_SYNTAX_INTERFACE",
    "HYPERLTL_ADAPTER_INTERFACE",
    "HYPER_NOTATION_ID",
    "HYPER_NOTATION_VERSION",
    "HYPER_FAMILY_ID",
    "HYPER_MODULE_VERSION",
    "TRACE_SORT",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_TRAILING_INPUT",
    "CODE_EMPTY_INPUT",
    "CODE_FREE_TRACE_VAR",
    "CODE_REBIND_TRACE_VAR",
    "CODE_EMPTY_PREFIX",
    "CODE_UNSUPPORTED_ALTERNATION",
    "CODE_PROMOTION_REJECTED",
    "CODE_NESTED_QUANTIFIER",
    "CODE_INVALID_NI",
    "CODE_TOOL_FRAGMENT",
    "CODE_AUTHORITY_CEILING",
    "PrintStyle",
    "HyperToolKind",
    "HyperLogicKind",
    "BoundednessKind",
    "EvidenceAuthority",
    "ToolFragmentCeiling",
    "HyperBoundContract",
    "HyperEvidenceContract",
    "HyperpropertyProfile",
    "AlternationReport",
    "HyperParseError",
    "HyperParseResult",
    "HyperPrinter",
    "HyperpropertyParser",
    "HyperpropertySyntax",
    "HyperLoweringReceipt",
    "HyperLoweringResult",
    "HyperLTLAdapter",
    "fragment_eahyper",
    "fragment_autohyper",
    "fragment_mchyper",
    "fragment_generic",
    "profile_hyperltl",
    "profile_noninterference",
    "model_check_evidence_contract",
    "self_composition_evidence_contract",
    "quantifier_alternation_count",
    "check_quantifier_fragment",
    "extract_quantifier_prefix",
    "extract_matrix",
    "free_trace_variables",
    "hyper_semantic_identity",
    "parse_hyper",
    "print_hyper",
    "parse_print_parse",
    "lower_hyperltl",
]
