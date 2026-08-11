"""Dyadic, defeasible, prioritized, and contrary-to-duty norms (LFP2-037).

Interface:

* ``NormativeLogicProfiles@2`` — parse/print/evaluate for controlled
  conditional (dyadic), defeasible, prioritized, and contrary-to-duty
  normative systems under **named** semantic profiles

Owned constructs:

* monadic norms (``O``/``P``/``F``, obligated/permitted/forbidden)
* dyadic / conditional norms (``O(content | condition)``)
* defeasible norms (``defeasible`` / ``normally`` / ``unless``)
* exceptions (``exception``)
* priorities (``priority``)
* contrary-to-duty / reparation structures (``ctd`` / ``reparation``)
* violations, conflicts, facts, and status queries

Named semantic profiles (always required; never profile-free):

* ``dyadic`` — conditional norms; **not** material-implication monadic O
* ``defeasible`` — exception-aware nonmonotonic norms
* ``prioritized`` — priority-resolved norm conflicts
* ``contrary_to_duty`` — primary duty + secondary reparation on violation

Authority ceilings (fail-closed):

* Normative evaluation is **never** classical entailment.
* Profiles are **not** interchangeable: no unearned equivalence between
  dyadic, defeasible, prioritized, and CTD systems.
* Each profile carries an explicit **semantic decision record** documenting
  admitted constructs and rejected equivalences.

Grammar (statement conjunction, low → high)::

    theory      ::= statement (('and'|∧|',') statement)*
    statement   ::= monadic | dyadic | defeasible | exception | priority
                  | ctd | reparation | violation | conflict | fact
                  | named_norm | status | '(' theory ')'
    monadic     ::= OP '(' ATOM ')'
    dyadic      ::= OP '(' ATOM ('|'|'/') ATOM ')'
    defeasible  ::= ('defeasible'|'normally') OP '(' ATOM ')'
                    ('unless' ATOM)?
    exception   ::= 'exception' '(' IDENT ',' ATOM ')'
    priority    ::= 'priority' '(' IDENT (','|'>') IDENT ')'
    ctd         ::= ('ctd'|'contrary_to_duty') '(' ATOM ',' ATOM ')'
    reparation  ::= 'reparation' '(' ATOM ',' ATOM ')'
    violation   ::= 'violation' '(' ATOM ')'
    conflict    ::= 'conflict' '(' IDENT ',' IDENT ')'
    fact        ::= ('fact'|'holds') '(' ATOM ')'
    named_norm  ::= 'norm' '(' IDENT ',' OP '(' ATOM ')' ')'
    status      ::= ('status'|'query') '(' ATOM ')'
    OP          ::= O|P|F|obligated|permitted|forbidden|obligation|
                    permission|prohibition|ought|must|may
    ATOM        ::= IDENT

Evidence subset: deontic dyadic defeasible priority exception contrary duty.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    LogicNode,
    NodeKind,
    TypedExpression,
    mk_extension,
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
    INDIVIDUAL_SORT,
    LogicSignature,
    atomic_sort,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

NORMATIVE_LOGIC_PROFILES_INTERFACE: Final = "NormativeLogicProfiles@2"
NORMATIVE_PROFILE_INTERFACE: Final = "NormativeProfile@2"
NORMATIVE_SEMANTIC_DECISION_INTERFACE: Final = "NormativeSemanticDecision@2"

NORM_NOTATION_ID: Final = "canonical_normative_v2"
NORM_NOTATION_VERSION: Final = "2.0.0"
NORM_FAMILY_ID: Final = "deontic"
NORM_MODULE_VERSION: Final = "2.0.0"
NORM_TASK_ID: Final = "LFP2-037"

NORM_PARSE_RESULT_SCHEMA: Final = "canonical-normative-v2-parse-result/v1"
NORM_PROFILE_SCHEMA: Final = "normative-profile/v2"
NORM_SDR_SCHEMA: Final = "normative.semantic-decision-record/v1"
NORM_EVIDENCE_CONTRACT_SCHEMA: Final = "normative.evidence-contract/v2"
NORM_EVALUATION_SCHEMA: Final = "normative.evaluation/v2"
NORM_THEORY_SCHEMA: Final = "normative.theory/v2"
NORM_SOURCE_MAP_SCHEMA: Final = "normative.source-map/v2"
NORM_LOWERING_RECEIPT_SCHEMA: Final = "normative.lowering-receipt/v2"

# Extension payload schemas.
NORM_MONADIC_PAYLOAD_SCHEMA: Final = "normative.monadic_norm/v2"
NORM_DYADIC_PAYLOAD_SCHEMA: Final = "normative.dyadic_norm/v2"
NORM_DEFEASIBLE_PAYLOAD_SCHEMA: Final = "normative.defeasible_norm/v2"
NORM_EXCEPTION_PAYLOAD_SCHEMA: Final = "normative.exception/v2"
NORM_PRIORITY_PAYLOAD_SCHEMA: Final = "normative.priority/v2"
NORM_CTD_PAYLOAD_SCHEMA: Final = "normative.contrary_to_duty/v2"
NORM_REPARATION_PAYLOAD_SCHEMA: Final = "normative.reparation/v2"
NORM_VIOLATION_PAYLOAD_SCHEMA: Final = "normative.violation/v2"
NORM_CONFLICT_PAYLOAD_SCHEMA: Final = "normative.conflict/v2"
NORM_FACT_PAYLOAD_SCHEMA: Final = "normative.fact/v2"
NORM_NAMED_PAYLOAD_SCHEMA: Final = "normative.named_norm/v2"
NORM_STATUS_PAYLOAD_SCHEMA: Final = "normative.status_query/v2"
NORM_AND_PAYLOAD_SCHEMA: Final = "normative.conjunction/v2"

NORM_SORT: Final = atomic_sort("Norm")
PROPOSITION_SORT: Final = atomic_sort("Proposition")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "normative.unexpected_token"
CODE_TRAILING_INPUT: Final = "normative.trailing_input"
CODE_EMPTY_INPUT: Final = "normative.empty_input"
CODE_PARSE_DEPTH: Final = "normative.parse_depth_exceeded"
CODE_UNBALANCED: Final = "normative.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "normative.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "normative.unknown_character"
CODE_PROFILE_MISMATCH: Final = "normative.profile_mismatch"
CODE_PROFILE_REQUIRED: Final = "normative.profile_required"
CODE_ARITY_MISMATCH: Final = "normative.arity_mismatch"
CODE_UNSUPPORTED_CONSTRUCT: Final = "normative.unsupported_construct"
CODE_ROUND_TRIP: Final = "normative.round_trip_failed"
CODE_AUTHORITY_CEILING: Final = "normative.authority_ceiling"
CODE_PROMOTION_REJECTED: Final = "normative.classical_promotion_rejected"
CODE_UNEARNED_EQUIVALENCE: Final = "normative.unearned_equivalence_rejected"
CODE_AMBIGUOUS_FORM: Final = "normative.ambiguous_form"
CODE_EVALUATION_FAILED: Final = "normative.evaluation_failed"
CODE_CROSS_PROFILE_COLLAPSE: Final = "normative.cross_profile_collapse_rejected"

_ALL_NORM_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_UNKNOWN_CHARACTER,
        CODE_PROFILE_MISMATCH,
        CODE_PROFILE_REQUIRED,
        CODE_ARITY_MISMATCH,
        CODE_UNSUPPORTED_CONSTRUCT,
        CODE_ROUND_TRIP,
        CODE_AUTHORITY_CEILING,
        CODE_PROMOTION_REJECTED,
        CODE_UNEARNED_EQUIVALENCE,
        CODE_AMBIGUOUS_FORM,
        CODE_EVALUATION_FAILED,
        CODE_CROSS_PROFILE_COLLAPSE,
    }
)

_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&", ","})

_DEONTIC_OPS: Final[frozenset[str]] = frozenset(
    {
        "o",
        "p",
        "f",
        "obligated",
        "obligation",
        "ought",
        "must",
        "permitted",
        "permission",
        "may",
        "forbidden",
        "prohibition",
        "prohibited",
        "forbid",
    }
)

_OP_CANONICAL: Final[Mapping[str, str]] = {
    "o": "obligation",
    "obligated": "obligation",
    "obligation": "obligation",
    "ought": "obligation",
    "must": "obligation",
    "p": "permission",
    "permitted": "permission",
    "permission": "permission",
    "may": "permission",
    "f": "forbidden",
    "forbidden": "forbidden",
    "prohibition": "forbidden",
    "prohibited": "forbidden",
    "forbid": "forbidden",
}

_OP_SURFACE: Final[Mapping[str, str]] = {
    "obligation": "O",
    "permission": "P",
    "forbidden": "F",
}

_STATEMENT_ATOMS: Final[frozenset[str]] = frozenset(
    {
        *_DEONTIC_OPS,
        "defeasible",
        "normally",
        "exception",
        "priority",
        "ctd",
        "contrary_to_duty",
        "reparation",
        "violation",
        "conflict",
        "fact",
        "holds",
        "norm",
        "status",
        "query",
    }
)

_NORM_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "o",
    "p",
    "f",
    "obligated",
    "obligation",
    "ought",
    "must",
    "permitted",
    "permission",
    "may",
    "forbidden",
    "prohibition",
    "prohibited",
    "forbid",
    "defeasible",
    "normally",
    "unless",
    "exception",
    "priority",
    "ctd",
    "contrary_to_duty",
    "reparation",
    "violation",
    "conflict",
    "fact",
    "holds",
    "norm",
    "status",
    "query",
    "true",
    "false",
)

# Ambiguous surface forms that require a named profile and fail closed when
# the profile cannot disambiguate (negative ambiguity cases).
_AMBIGUOUS_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "unless",  # requires defeasible profile context
        "typically",
        "by_default",
        "prima_facie",
    }
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class NormativeSemantics(str, Enum):
    """Named normative semantic profile identity.

    Every evaluation result must name one of these.  There is no anonymous
    or monadic-only default that silently absorbs dyadic/CTD structure.
    """

    DYADIC = "dyadic"
    DEFEASIBLE = "defeasible"
    PRIORITIZED = "prioritized"
    CONTRARY_TO_DUTY = "contrary_to_duty"


class NormOperator(str, Enum):
    """Canonical deontic operator identity."""

    OBLIGATION = "obligation"
    PERMISSION = "permission"
    FORBIDDEN = "forbidden"


class NormStatus(str, Enum):
    """Three-valued status of a norm content under a named profile."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    VIOLATED = "violated"
    REPARATION_ACTIVE = "reparation_active"
    UNDECIDED = "undecided"


class EvidenceSource(str, Enum):
    """Origin of normative evidence (closed set)."""

    DYADIC_EVALUATOR = "dyadic_evaluator"
    DEFEASIBLE_EVALUATOR = "defeasible_evaluator"
    PRIORITIZED_EVALUATOR = "prioritized_evaluator"
    CTD_EVALUATOR = "ctd_evaluator"
    CLASSICAL_SOLVER = "classical_solver"
    NONE = "none"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by normative evidence.

    Intentionally non-hierarchical for classical promotion: normative
    results never become classical entailment authority.
    """

    NONE = "none"
    ADVISORY = "advisory"
    NORMATIVE = "normative"
    NONMONOTONIC = "nonmonotonic"
    CLASSICAL_ENTAILMENT = "classical_entailment"


class BoundednessKind(str, Enum):
    """Semantic bound for normative evidence."""

    FINITE_THEORY = "finite_theory"
    RESOURCE_BOUNDED = "resource_bounded"
    UNBOUNDED = "unbounded"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    AND = 10
    ATOM = 60


_NON_CLASSICAL_SOURCES: Final[frozenset[EvidenceSource]] = frozenset(
    {
        EvidenceSource.DYADIC_EVALUATOR,
        EvidenceSource.DEFEASIBLE_EVALUATOR,
        EvidenceSource.PRIORITIZED_EVALUATOR,
        EvidenceSource.CTD_EVALUATOR,
        EvidenceSource.NONE,
    }
)

_SOURCE_AUTHORITY_CEILING: Final[Mapping[EvidenceSource, EvidenceAuthority]] = {
    EvidenceSource.NONE: EvidenceAuthority.NONE,
    EvidenceSource.DYADIC_EVALUATOR: EvidenceAuthority.NORMATIVE,
    EvidenceSource.DEFEASIBLE_EVALUATOR: EvidenceAuthority.NONMONOTONIC,
    EvidenceSource.PRIORITIZED_EVALUATOR: EvidenceAuthority.NORMATIVE,
    EvidenceSource.CTD_EVALUATOR: EvidenceAuthority.NORMATIVE,
    EvidenceSource.CLASSICAL_SOLVER: EvidenceAuthority.CLASSICAL_ENTAILMENT,
}

_AUTHORITY_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.NONMONOTONIC: 2,
    EvidenceAuthority.NORMATIVE: 2,
    EvidenceAuthority.CLASSICAL_ENTAILMENT: 3,
}

_SEMANTICS_TO_SOURCE: Final[Mapping[NormativeSemantics, EvidenceSource]] = {
    NormativeSemantics.DYADIC: EvidenceSource.DYADIC_EVALUATOR,
    NormativeSemantics.DEFEASIBLE: EvidenceSource.DEFEASIBLE_EVALUATOR,
    NormativeSemantics.PRIORITIZED: EvidenceSource.PRIORITIZED_EVALUATOR,
    NormativeSemantics.CONTRARY_TO_DUTY: EvidenceSource.CTD_EVALUATOR,
}


# ---------------------------------------------------------------------------
# Semantic decision records — one per profile, no unearned equivalence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticDecisionRecord:
    """Explicit semantic decisions for one named normative profile.

    Interface: ``NormativeSemanticDecision@2``.

    Documents admitted constructs and **rejected** equivalences so that
    dyadic, defeasible, prioritized, and CTD systems cannot silently
    collapse into each other or into classical monadic deontic logic.
    """

    profile_id: str
    semantics: NormativeSemantics | str
    admitted_constructs: tuple[str, ...]
    rejected_equivalences: tuple[str, ...]
    decision_notes: tuple[str, ...] = ()
    grants_classical_entailment: bool = False
    grants_material_implication_equiv: bool = False
    grants_cross_profile_equiv: bool = False
    schema_version: str = NORM_SDR_SCHEMA

    interface: ClassVar[str] = NORMATIVE_SEMANTIC_DECISION_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "SemanticDecisionRecord.profile_id is required"
            )
        semantics = (
            self.semantics
            if isinstance(self.semantics, NormativeSemantics)
            else NormativeSemantics(str(self.semantics))
        )
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(
            self,
            "admitted_constructs",
            tuple(str(c) for c in self.admitted_constructs),
        )
        object.__setattr__(
            self,
            "rejected_equivalences",
            tuple(str(e) for e in self.rejected_equivalences),
        )
        object.__setattr__(
            self,
            "decision_notes",
            tuple(str(n) for n in self.decision_notes),
        )
        # Hard ceilings: SDRs never grant classical or cross-profile collapse.
        if self.grants_classical_entailment:
            raise AuthorityPromotionError(
                "semantic decision record cannot grant classical entailment"
            )
        if self.grants_material_implication_equiv:
            raise AuthorityPromotionError(
                "semantic decision record cannot grant unearned "
                "dyadic≡material-implication equivalence"
            )
        if self.grants_cross_profile_equiv:
            raise AuthorityPromotionError(
                "semantic decision record cannot grant cross-profile "
                "norm-system equivalence"
            )
        object.__setattr__(self, "grants_classical_entailment", False)
        object.__setattr__(self, "grants_material_implication_equiv", False)
        object.__setattr__(self, "grants_cross_profile_equiv", False)
        if self.schema_version != NORM_SDR_SCHEMA:
            raise SyntaxContractError(
                f"unsupported SDR schema {self.schema_version!r}"
            )

    @property
    def semantics_name(self) -> str:
        assert isinstance(self.semantics, NormativeSemantics)
        return self.semantics.value

    def admits(self, construct: str) -> bool:
        return construct in self.admitted_constructs

    def rejects_equivalence(self, name: str) -> bool:
        return name in self.rejected_equivalences

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_constructs": list(self.admitted_constructs),
            "decision_notes": list(self.decision_notes),
            "grants_classical_entailment": False,
            "grants_cross_profile_equiv": False,
            "grants_material_implication_equiv": False,
            "interface": self.interface,
            "profile_id": self.profile_id,
            "rejected_equivalences": list(self.rejected_equivalences),
            "schema_version": self.schema_version,
            "semantics": self.semantics_name,
        }


def _sdr_dyadic(profile_id: str) -> SemanticDecisionRecord:
    return SemanticDecisionRecord(
        profile_id=profile_id,
        semantics=NormativeSemantics.DYADIC,
        admitted_constructs=(
            "monadic_norm",
            "dyadic_norm",
            "fact",
            "status_query",
            "named_norm",
        ),
        rejected_equivalences=(
            "dyadic_equals_monadic_material_implication",
            "O(p|q)_equals_O(q_implies_p)",
            "O(p|q)_equals_q_implies_O(p)",
            "dyadic_equals_defeasible",
            "dyadic_equals_prioritized",
            "dyadic_equals_contrary_to_duty",
            "normative_equals_classical_entailment",
        ),
        decision_notes=(
            "Dyadic O(p|q) is a conditional obligation, not classical O(q→p).",
            "Condition and content are first-class; separator '|' is not 'or'.",
            "No silent collapse into monadic SDL or material implication.",
        ),
    )


def _sdr_defeasible(profile_id: str) -> SemanticDecisionRecord:
    return SemanticDecisionRecord(
        profile_id=profile_id,
        semantics=NormativeSemantics.DEFEASIBLE,
        admitted_constructs=(
            "monadic_norm",
            "defeasible_norm",
            "exception",
            "fact",
            "status_query",
            "named_norm",
        ),
        rejected_equivalences=(
            "defeasible_equals_strict_implication",
            "defeasible_equals_classical_conditional",
            "defeasible_equals_dyadic",
            "defeasible_equals_prioritized",
            "defeasible_equals_contrary_to_duty",
            "exception_equals_negation",
            "normative_equals_classical_entailment",
        ),
        decision_notes=(
            "Defeasible norms yield to exceptions; they are nonmonotonic.",
            "unless/exception does not lower to classical ¬p ∧ O(q).",
            "No unearned equivalence with dyadic conditional obligation.",
        ),
    )


def _sdr_prioritized(profile_id: str) -> SemanticDecisionRecord:
    return SemanticDecisionRecord(
        profile_id=profile_id,
        semantics=NormativeSemantics.PRIORITIZED,
        admitted_constructs=(
            "monadic_norm",
            "named_norm",
            "priority",
            "conflict",
            "fact",
            "status_query",
        ),
        rejected_equivalences=(
            "prioritized_equals_unprioritized_conjunction",
            "priority_equals_classical_ordering",
            "prioritized_equals_dyadic",
            "prioritized_equals_defeasible",
            "prioritized_equals_contrary_to_duty",
            "conflict_equals_classical_inconsistency",
            "normative_equals_classical_entailment",
        ),
        decision_notes=(
            "Priority resolves conflicts; lower-priority norms may be inactive.",
            "priority(a,b) is not classical a>b or a∧¬b.",
            "Conflict is a typed normative conflict, not classical ⊥.",
        ),
    )


def _sdr_contrary_to_duty(profile_id: str) -> SemanticDecisionRecord:
    return SemanticDecisionRecord(
        profile_id=profile_id,
        semantics=NormativeSemantics.CONTRARY_TO_DUTY,
        admitted_constructs=(
            "monadic_norm",
            "contrary_to_duty",
            "reparation",
            "violation",
            "fact",
            "status_query",
            "named_norm",
        ),
        rejected_equivalences=(
            "ctd_equals_conjunction_of_monadic_norms",
            "ctd_equals_dyadic_conditional",
            "reparation_equals_independent_obligation",
            "ctd_equals_defeasible",
            "ctd_equals_prioritized",
            "violation_equals_classical_false",
            "normative_equals_classical_entailment",
        ),
        decision_notes=(
            "Primary duty remains; reparation activates only on violation.",
            "ctd(primary, secondary) ≠ O(primary) ∧ O(secondary).",
            "Chisholm-style CTD paradoxes are typed structures, not SDL collapse.",
        ),
    )


_SDR_BUILDERS: Final[
    Mapping[NormativeSemantics, Any]
] = {
    NormativeSemantics.DYADIC: _sdr_dyadic,
    NormativeSemantics.DEFEASIBLE: _sdr_defeasible,
    NormativeSemantics.PRIORITIZED: _sdr_prioritized,
    NormativeSemantics.CONTRARY_TO_DUTY: _sdr_contrary_to_duty,
}


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormativeProfile:
    """Named normative semantic profile (``NormativeProfile@2``).

    The profile identity is **always** required for parse and evaluation.
    Admission flags gate constructs; semantic decision records document
    rejected equivalences so systems stay non-interchangeable.
    """

    profile_id: str
    semantics: NormativeSemantics | str
    admit_monadic: bool = True
    admit_dyadic: bool = False
    admit_defeasible: bool = False
    admit_exception: bool = False
    admit_priority: bool = False
    admit_contrary_to_duty: bool = False
    admit_reparation: bool = False
    admit_violation: bool = False
    admit_conflict: bool = False
    admit_classic_letters: bool = True
    schema_version: str = NORM_PROFILE_SCHEMA

    interface: ClassVar[str] = NORMATIVE_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "NormativeProfile.profile_id is required; "
                "semantics/profile is always named"
            )
        semantics = self.semantics
        if not isinstance(semantics, NormativeSemantics):
            try:
                semantics = NormativeSemantics(str(semantics))
            except ValueError as error:
                raise SyntaxContractError(
                    f"unknown normative semantics {self.semantics!r}; "
                    "profile must name dyadic|defeasible|prioritized|"
                    "contrary_to_duty"
                ) from error
            object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        for name in (
            "admit_monadic",
            "admit_dyadic",
            "admit_defeasible",
            "admit_exception",
            "admit_priority",
            "admit_contrary_to_duty",
            "admit_reparation",
            "admit_violation",
            "admit_conflict",
            "admit_classic_letters",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if self.schema_version != NORM_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported NormativeProfile schema {self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return NORM_FAMILY_ID

    @property
    def semantics_name(self) -> str:
        assert isinstance(self.semantics, NormativeSemantics)
        return self.semantics.value

    @property
    def semantic_decision_record(self) -> SemanticDecisionRecord:
        """Stable SDR for this profile (no unearned equivalences)."""

        assert isinstance(self.semantics, NormativeSemantics)
        builder = _SDR_BUILDERS[self.semantics]
        return builder(self.profile_id)

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_conflict": self.admit_conflict,
            "admit_contrary_to_duty": self.admit_contrary_to_duty,
            "admit_defeasible": self.admit_defeasible,
            "admit_dyadic": self.admit_dyadic,
            "admit_exception": self.admit_exception,
            "admit_monadic": self.admit_monadic,
            "admit_priority": self.admit_priority,
            "admit_reparation": self.admit_reparation,
            "admit_violation": self.admit_violation,
            "family_id": self.family_id,
            "profile_id": self.profile_id,
            "semantics": self.semantics_name,
            "semantic_decision_record": self.semantic_decision_record.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_letters": self.admit_classic_letters,
            "admit_conflict": self.admit_conflict,
            "admit_contrary_to_duty": self.admit_contrary_to_duty,
            "admit_defeasible": self.admit_defeasible,
            "admit_dyadic": self.admit_dyadic,
            "admit_exception": self.admit_exception,
            "admit_monadic": self.admit_monadic,
            "admit_priority": self.admit_priority,
            "admit_reparation": self.admit_reparation,
            "admit_violation": self.admit_violation,
            "interface": self.interface,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "semantics": self.semantics_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NormativeProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("NormativeProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            semantics=value.get("semantics") or NormativeSemantics.DYADIC.value,
            admit_monadic=bool(value.get("admit_monadic", True)),
            admit_dyadic=bool(value.get("admit_dyadic", False)),
            admit_defeasible=bool(value.get("admit_defeasible", False)),
            admit_exception=bool(value.get("admit_exception", False)),
            admit_priority=bool(value.get("admit_priority", False)),
            admit_contrary_to_duty=bool(
                value.get("admit_contrary_to_duty", False)
            ),
            admit_reparation=bool(value.get("admit_reparation", False)),
            admit_violation=bool(value.get("admit_violation", False)),
            admit_conflict=bool(value.get("admit_conflict", False)),
            admit_classic_letters=bool(
                value.get("admit_classic_letters", True)
            ),
            schema_version=str(
                value.get("schema_version") or NORM_PROFILE_SCHEMA
            ),
        )


def profile_dyadic(
    *,
    profile_id: str = "normative_dyadic",
) -> NormativeProfile:
    return NormativeProfile(
        profile_id=profile_id,
        semantics=NormativeSemantics.DYADIC,
        admit_monadic=True,
        admit_dyadic=True,
    )


def profile_defeasible(
    *,
    profile_id: str = "normative_defeasible",
) -> NormativeProfile:
    return NormativeProfile(
        profile_id=profile_id,
        semantics=NormativeSemantics.DEFEASIBLE,
        admit_monadic=True,
        admit_defeasible=True,
        admit_exception=True,
    )


def profile_prioritized(
    *,
    profile_id: str = "normative_prioritized",
) -> NormativeProfile:
    return NormativeProfile(
        profile_id=profile_id,
        semantics=NormativeSemantics.PRIORITIZED,
        admit_monadic=True,
        admit_priority=True,
        admit_conflict=True,
    )


def profile_contrary_to_duty(
    *,
    profile_id: str = "normative_contrary_to_duty",
) -> NormativeProfile:
    return NormativeProfile(
        profile_id=profile_id,
        semantics=NormativeSemantics.CONTRARY_TO_DUTY,
        admit_monadic=True,
        admit_contrary_to_duty=True,
        admit_reparation=True,
        admit_violation=True,
    )


def normative_semantic_identity(
    node: LogicNode,
    profile: NormativeProfile,
) -> dict[str, Any]:
    """Stable semantic identity including named profile and SDR."""

    theory = extract_theory(node)
    return {
        "family": profile.family_id,
        "node_kind": (
            node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
        ),
        "profile": profile.semantic_identity,
        "semantics": profile.semantics_name,
        "theory": theory.to_dict(),
    }


def profiles_are_equivalent(
    left: NormativeProfile,
    right: NormativeProfile,
) -> bool:
    """Return whether two profiles share identity (never cross-semantics).

    Distinct semantics are **never** equivalent under this module.
    """

    if left.semantics_name != right.semantics_name:
        return False
    return left.profile_id == right.profile_id and left.to_dict() == right.to_dict()


def reject_unearned_equivalence(
    left: NormativeProfile,
    right: NormativeProfile,
) -> None:
    """Fail closed if two distinct norm systems are claimed equivalent."""

    if left.semantics_name != right.semantics_name:
        raise AuthorityPromotionError(
            f"unearned equivalence rejected: {left.semantics_name!r} is not "
            f"equivalent to {right.semantics_name!r}; each profile carries "
            "a distinct semantic decision record",
            code=CODE_UNEARNED_EQUIVALENCE,
        )
    if left.profile_id != right.profile_id and not profiles_are_equivalent(
        left, right
    ):
        raise AuthorityPromotionError(
            f"unearned equivalence rejected between profiles "
            f"{left.profile_id!r} and {right.profile_id!r}",
            code=CODE_UNEARNED_EQUIVALENCE,
        )


# ---------------------------------------------------------------------------
# Theory model (extracted from AST)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonadicNorm:
    """Monadic deontic norm O/P/F(content)."""

    operator: str
    content: str
    norm_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "kind": "monadic",
            "norm_id": self.norm_id,
            "operator": self.operator,
        }


@dataclass(frozen=True, slots=True)
class DyadicNorm:
    """Dyadic / conditional norm O(content | condition)."""

    operator: str
    content: str
    condition: str
    norm_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "content": self.content,
            "kind": "dyadic",
            "norm_id": self.norm_id,
            "operator": self.operator,
        }


@dataclass(frozen=True, slots=True)
class DefeasibleNorm:
    """Defeasible monadic norm with optional unless-exception."""

    operator: str
    content: str
    unless: str = ""
    norm_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "kind": "defeasible",
            "norm_id": self.norm_id,
            "operator": self.operator,
            "unless": self.unless,
        }


@dataclass(frozen=True, slots=True)
class ContraryToDuty:
    """Primary duty with secondary reparation duty."""

    primary: str
    secondary: str
    norm_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "contrary_to_duty",
            "norm_id": self.norm_id,
            "primary": self.primary,
            "secondary": self.secondary,
        }


@dataclass(frozen=True, slots=True)
class NormativeTheory:
    """Finite normative theory extracted from an AST."""

    monadic: tuple[MonadicNorm, ...] = ()
    dyadic: tuple[DyadicNorm, ...] = ()
    defeasible: tuple[DefeasibleNorm, ...] = ()
    exceptions: tuple[tuple[str, str], ...] = ()  # (norm_id, exception_atom)
    priorities: tuple[tuple[str, str], ...] = ()  # (higher, lower)
    ctd: tuple[ContraryToDuty, ...] = ()
    reparations: tuple[tuple[str, str], ...] = ()  # (violated, reparation)
    violations: tuple[str, ...] = ()
    conflicts: tuple[tuple[str, str], ...] = ()
    facts: tuple[str, ...] = ()
    named: tuple[tuple[str, str, str], ...] = ()  # (id, operator, content)
    queries: tuple[str, ...] = ()
    schema_version: str = NORM_THEORY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflicts": [list(p) for p in self.conflicts],
            "ctd": [item.to_dict() for item in self.ctd],
            "defeasible": [item.to_dict() for item in self.defeasible],
            "dyadic": [item.to_dict() for item in self.dyadic],
            "exceptions": [list(p) for p in self.exceptions],
            "facts": list(self.facts),
            "monadic": [item.to_dict() for item in self.monadic],
            "named": [list(p) for p in self.named],
            "priorities": [list(p) for p in self.priorities],
            "queries": list(self.queries),
            "reparations": [list(p) for p in self.reparations],
            "schema_version": self.schema_version,
            "violations": list(self.violations),
        }


def extract_theory(node: LogicNode) -> NormativeTheory:
    """Walk a normative AST and collect theory components."""

    monadic: list[MonadicNorm] = []
    dyadic: list[DyadicNorm] = []
    defeasible: list[DefeasibleNorm] = []
    exceptions: list[tuple[str, str]] = []
    priorities: list[tuple[str, str]] = []
    ctd: list[ContraryToDuty] = []
    reparations: list[tuple[str, str]] = []
    violations: list[str] = []
    conflicts: list[tuple[str, str]] = []
    facts: list[str] = []
    named: list[tuple[str, str, str]] = []
    queries: list[str] = []

    def walk(n: LogicNode) -> None:
        kind = n.kind
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            for child in n.arguments:
                walk(child)
            return
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            ext = n.extension
            if ext is None:
                return
            schema = ext.payload_schema
            payload = dict(ext.payload)
            if schema == NORM_MONADIC_PAYLOAD_SCHEMA:
                monadic.append(
                    MonadicNorm(
                        operator=str(payload.get("operator") or ""),
                        content=str(payload.get("content") or ""),
                        norm_id=str(payload.get("norm_id") or ""),
                    )
                )
            elif schema == NORM_DYADIC_PAYLOAD_SCHEMA:
                dyadic.append(
                    DyadicNorm(
                        operator=str(payload.get("operator") or ""),
                        content=str(payload.get("content") or ""),
                        condition=str(payload.get("condition") or ""),
                        norm_id=str(payload.get("norm_id") or ""),
                    )
                )
            elif schema == NORM_DEFEASIBLE_PAYLOAD_SCHEMA:
                defeasible.append(
                    DefeasibleNorm(
                        operator=str(payload.get("operator") or ""),
                        content=str(payload.get("content") or ""),
                        unless=str(payload.get("unless") or ""),
                        norm_id=str(payload.get("norm_id") or ""),
                    )
                )
            elif schema == NORM_EXCEPTION_PAYLOAD_SCHEMA:
                exceptions.append(
                    (
                        str(payload.get("norm_id") or ""),
                        str(payload.get("exception") or ""),
                    )
                )
            elif schema == NORM_PRIORITY_PAYLOAD_SCHEMA:
                priorities.append(
                    (
                        str(payload.get("higher") or ""),
                        str(payload.get("lower") or ""),
                    )
                )
            elif schema == NORM_CTD_PAYLOAD_SCHEMA:
                ctd.append(
                    ContraryToDuty(
                        primary=str(payload.get("primary") or ""),
                        secondary=str(payload.get("secondary") or ""),
                        norm_id=str(payload.get("norm_id") or ""),
                    )
                )
            elif schema == NORM_REPARATION_PAYLOAD_SCHEMA:
                reparations.append(
                    (
                        str(payload.get("violated") or ""),
                        str(payload.get("reparation") or ""),
                    )
                )
            elif schema == NORM_VIOLATION_PAYLOAD_SCHEMA:
                atom = str(payload.get("content") or "")
                if atom:
                    violations.append(atom)
            elif schema == NORM_CONFLICT_PAYLOAD_SCHEMA:
                conflicts.append(
                    (
                        str(payload.get("left") or ""),
                        str(payload.get("right") or ""),
                    )
                )
            elif schema == NORM_FACT_PAYLOAD_SCHEMA:
                atom = str(payload.get("atom") or "")
                if atom:
                    facts.append(atom)
            elif schema == NORM_NAMED_PAYLOAD_SCHEMA:
                named.append(
                    (
                        str(payload.get("norm_id") or ""),
                        str(payload.get("operator") or ""),
                        str(payload.get("content") or ""),
                    )
                )
            elif schema == NORM_STATUS_PAYLOAD_SCHEMA:
                atom = str(payload.get("atom") or "")
                if atom:
                    queries.append(atom)
            for child in ext.children:
                walk(child)
            return
        for child in n.arguments:
            walk(child)

    walk(node)
    return NormativeTheory(
        monadic=tuple(monadic),
        dyadic=tuple(dyadic),
        defeasible=tuple(defeasible),
        exceptions=tuple(exceptions),
        priorities=tuple(priorities),
        ctd=tuple(ctd),
        reparations=tuple(reparations),
        violations=tuple(dict.fromkeys(violations)),
        conflicts=tuple(conflicts),
        facts=tuple(dict.fromkeys(facts)),
        named=tuple(named),
        queries=tuple(dict.fromkeys(queries)),
    )


# ---------------------------------------------------------------------------
# Evaluation — preserves profile identity, no classical collapse
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormativeEvaluation:
    """Evaluation result under a named normative semantics.

    * Statuses remain three-valued (never coerced to classical true/false).
    * Classical entailment flags are always false.
    * Cross-profile collapse is never claimed.
    """

    profile_id: str
    semantics: NormativeSemantics | str
    statuses: Mapping[str, NormStatus | str] = field(default_factory=dict)
    active_norms: tuple[str, ...] = ()
    inactive_norms: tuple[str, ...] = ()
    violated_norms: tuple[str, ...] = ()
    reparation_active: tuple[str, ...] = ()
    queries: Mapping[str, NormStatus | str] = field(default_factory=dict)
    classical_entailment: bool = False
    material_implication_equiv: bool = False
    cross_profile_equiv: bool = False
    schema_version: str = NORM_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        semantics = (
            self.semantics
            if isinstance(self.semantics, NormativeSemantics)
            else NormativeSemantics(str(self.semantics))
        )
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "NormativeEvaluation.profile_id is required; "
                "semantics/profile is always named"
            )
        if self.classical_entailment:
            raise AuthorityPromotionError(
                "normative evaluation cannot claim classical_entailment"
            )
        if self.material_implication_equiv:
            raise AuthorityPromotionError(
                "normative evaluation cannot claim unearned "
                "material-implication equivalence"
            )
        if self.cross_profile_equiv:
            raise AuthorityPromotionError(
                "normative evaluation cannot claim cross-profile equivalence"
            )
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(self, "classical_entailment", False)
        object.__setattr__(self, "material_implication_equiv", False)
        object.__setattr__(self, "cross_profile_equiv", False)

        def _norm_status(value: NormStatus | str) -> NormStatus:
            return value if isinstance(value, NormStatus) else NormStatus(str(value))

        statuses = {
            str(k): _norm_status(v) for k, v in self.statuses.items()
        }
        queries = {
            str(k): _norm_status(v) for k, v in self.queries.items()
        }
        object.__setattr__(self, "statuses", statuses)
        object.__setattr__(self, "queries", queries)
        object.__setattr__(
            self, "active_norms", tuple(str(x) for x in self.active_norms)
        )
        object.__setattr__(
            self, "inactive_norms", tuple(str(x) for x in self.inactive_norms)
        )
        object.__setattr__(
            self, "violated_norms", tuple(str(x) for x in self.violated_norms)
        )
        object.__setattr__(
            self,
            "reparation_active",
            tuple(str(x) for x in self.reparation_active),
        )

    @property
    def semantics_name(self) -> str:
        assert isinstance(self.semantics, NormativeSemantics)
        return self.semantics.value

    def status_of(self, atom: str) -> NormStatus:
        if atom in self.queries:
            raw = self.queries[atom]
            return raw if isinstance(raw, NormStatus) else NormStatus(str(raw))
        if atom in self.statuses:
            raw = self.statuses[atom]
            return raw if isinstance(raw, NormStatus) else NormStatus(str(raw))
        return NormStatus.UNDECIDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_norms": list(self.active_norms),
            "classical_entailment": False,
            "cross_profile_equiv": False,
            "inactive_norms": list(self.inactive_norms),
            "material_implication_equiv": False,
            "profile_id": self.profile_id,
            "queries": {
                k: (v.value if isinstance(v, NormStatus) else str(v))
                for k, v in self.queries.items()
            },
            "reparation_active": list(self.reparation_active),
            "schema_version": self.schema_version,
            "semantics": self.semantics_name,
            "statuses": {
                k: (v.value if isinstance(v, NormStatus) else str(v))
                for k, v in self.statuses.items()
            },
            "violated_norms": list(self.violated_norms),
        }


def _evaluate_dyadic(
    theory: NormativeTheory,
    profile: NormativeProfile,
) -> NormativeEvaluation:
    facts = set(theory.facts)
    statuses: dict[str, NormStatus] = {}
    active: list[str] = []
    inactive: list[str] = []

    for norm in theory.monadic:
        key = norm.content
        statuses[key] = NormStatus.ACTIVE
        active.append(key)

    for norm in theory.dyadic:
        key = norm.content
        # Conditional: active only when condition holds as fact.
        # NOT material implication O(q→p) — condition is a fact premise.
        if norm.condition in facts:
            statuses[key] = NormStatus.ACTIVE
            active.append(key)
        else:
            statuses[key] = NormStatus.INACTIVE
            inactive.append(key)

    for name, _op, content in theory.named:
        if content not in statuses:
            statuses[content] = NormStatus.ACTIVE
            active.append(content)
        statuses[name] = statuses.get(content, NormStatus.ACTIVE)

    queries = {
        q: statuses.get(q, NormStatus.UNDECIDED) for q in theory.queries
    }
    return NormativeEvaluation(
        profile_id=profile.profile_id,
        semantics=NormativeSemantics.DYADIC,
        statuses=statuses,
        active_norms=tuple(dict.fromkeys(active)),
        inactive_norms=tuple(dict.fromkeys(inactive)),
        queries=queries,
    )


def _evaluate_defeasible(
    theory: NormativeTheory,
    profile: NormativeProfile,
) -> NormativeEvaluation:
    facts = set(theory.facts)
    exception_atoms = {exc for _nid, exc in theory.exceptions}
    statuses: dict[str, NormStatus] = {}
    active: list[str] = []
    inactive: list[str] = []

    for norm in theory.monadic:
        statuses[norm.content] = NormStatus.ACTIVE
        active.append(norm.content)

    for norm in theory.defeasible:
        key = norm.content
        defeated = False
        if norm.unless and norm.unless in facts:
            defeated = True
        if key in exception_atoms and any(
            exc in facts for _nid, exc in theory.exceptions if True
        ):
            # Exception atom present as fact defeats matching content.
            for _nid, exc in theory.exceptions:
                if exc in facts and (_nid == key or _nid == norm.norm_id or not _nid):
                    defeated = True
        # Also: if exception(norm_id, atom) and atom is fact.
        for nid, exc in theory.exceptions:
            if exc in facts and (
                nid == key or nid == norm.norm_id or nid == norm.content
            ):
                defeated = True
        if defeated:
            statuses[key] = NormStatus.INACTIVE
            inactive.append(key)
        else:
            statuses[key] = NormStatus.ACTIVE
            active.append(key)

    for name, _op, content in theory.named:
        if content not in statuses:
            statuses[content] = NormStatus.ACTIVE
            active.append(content)
        statuses[name] = statuses.get(content, NormStatus.ACTIVE)

    queries = {
        q: statuses.get(q, NormStatus.UNDECIDED) for q in theory.queries
    }
    return NormativeEvaluation(
        profile_id=profile.profile_id,
        semantics=NormativeSemantics.DEFEASIBLE,
        statuses=statuses,
        active_norms=tuple(dict.fromkeys(active)),
        inactive_norms=tuple(dict.fromkeys(inactive)),
        queries=queries,
    )


def _evaluate_prioritized(
    theory: NormativeTheory,
    profile: NormativeProfile,
) -> NormativeEvaluation:
    # Build rank: higher-priority norms beat lower ones on conflict.
    rank: dict[str, int] = {}
    for higher, lower in theory.priorities:
        rank[higher] = max(rank.get(higher, 0), rank.get(lower, 0) + 1)
        rank.setdefault(lower, 0)

    # Named norms and monadic contents.
    content_by_id: dict[str, str] = {}
    op_by_id: dict[str, str] = {}
    for name, op, content in theory.named:
        content_by_id[name] = content
        op_by_id[name] = op
        rank.setdefault(name, 0)
    for norm in theory.monadic:
        nid = norm.norm_id or norm.content
        content_by_id.setdefault(nid, norm.content)
        op_by_id.setdefault(nid, norm.operator)
        rank.setdefault(nid, 0)

    # Conflict pairs: lower-rank side becomes inactive.
    defeated: set[str] = set()
    for left, right in theory.conflicts:
        left_rank = rank.get(left, 0)
        right_rank = rank.get(right, 0)
        if left_rank > right_rank:
            defeated.add(right)
        elif right_rank > left_rank:
            defeated.add(left)
        # Equal rank → both undecided (not classical inconsistency).

    # Also apply priorities transitively: if a > b and both present, b loses
    # when they conflict or share content.
    for higher, lower in theory.priorities:
        if higher in content_by_id and lower in content_by_id:
            if content_by_id[higher] != content_by_id[lower]:
                # Different content: lower remains unless explicit conflict.
                if (higher, lower) in theory.conflicts or (
                    lower,
                    higher,
                ) in theory.conflicts:
                    defeated.add(lower)
            else:
                defeated.add(lower)

    statuses: dict[str, NormStatus] = {}
    active: list[str] = []
    inactive: list[str] = []
    for nid, content in content_by_id.items():
        if nid in defeated:
            statuses[nid] = NormStatus.INACTIVE
            statuses[content] = NormStatus.INACTIVE
            inactive.append(nid)
        else:
            # Equal-rank conflict → undecided.
            conflicted_equal = False
            for left, right in theory.conflicts:
                if nid in {left, right}:
                    other = right if nid == left else left
                    if rank.get(nid, 0) == rank.get(other, 0):
                        conflicted_equal = True
            if conflicted_equal:
                statuses[nid] = NormStatus.UNDECIDED
                statuses[content] = NormStatus.UNDECIDED
            else:
                statuses[nid] = NormStatus.ACTIVE
                statuses[content] = NormStatus.ACTIVE
                active.append(nid)

    queries = {
        q: statuses.get(q, NormStatus.UNDECIDED) for q in theory.queries
    }
    return NormativeEvaluation(
        profile_id=profile.profile_id,
        semantics=NormativeSemantics.PRIORITIZED,
        statuses=statuses,
        active_norms=tuple(dict.fromkeys(active)),
        inactive_norms=tuple(dict.fromkeys(inactive)),
        queries=queries,
    )


def _evaluate_ctd(
    theory: NormativeTheory,
    profile: NormativeProfile,
) -> NormativeEvaluation:
    facts = set(theory.facts)
    violations = set(theory.violations)
    # Also treat fact of ¬primary as violation when primary content is fact-negated
    # via explicit violation(...) only — no classical ¬ inference.

    statuses: dict[str, NormStatus] = {}
    active: list[str] = []
    inactive: list[str] = []
    violated: list[str] = []
    reparation_active: list[str] = []

    for norm in theory.monadic:
        key = norm.content
        if key in violations or key in facts and False:
            pass
        if key in violations:
            statuses[key] = NormStatus.VIOLATED
            violated.append(key)
        else:
            statuses[key] = NormStatus.ACTIVE
            active.append(key)

    for item in theory.ctd:
        primary = item.primary
        secondary = item.secondary
        primary_violated = primary in violations
        if primary_violated:
            statuses[primary] = NormStatus.VIOLATED
            violated.append(primary)
            statuses[secondary] = NormStatus.REPARATION_ACTIVE
            reparation_active.append(secondary)
            # Primary remains a duty (violated), secondary activates.
            # NOT equivalent to O(primary) ∧ O(secondary) independently.
        else:
            statuses[primary] = NormStatus.ACTIVE
            active.append(primary)
            # Secondary is NOT independently active when primary holds.
            statuses[secondary] = NormStatus.INACTIVE
            inactive.append(secondary)

    for violated_content, reparation in theory.reparations:
        if violated_content in violations:
            statuses[violated_content] = NormStatus.VIOLATED
            violated.append(violated_content)
            statuses[reparation] = NormStatus.REPARATION_ACTIVE
            reparation_active.append(reparation)
        else:
            statuses.setdefault(reparation, NormStatus.INACTIVE)
            if reparation not in inactive:
                inactive.append(reparation)

    for name, _op, content in theory.named:
        if content not in statuses:
            statuses[content] = NormStatus.ACTIVE
            active.append(content)
        statuses[name] = statuses.get(content, NormStatus.ACTIVE)

    queries = {
        q: statuses.get(q, NormStatus.UNDECIDED) for q in theory.queries
    }
    return NormativeEvaluation(
        profile_id=profile.profile_id,
        semantics=NormativeSemantics.CONTRARY_TO_DUTY,
        statuses=statuses,
        active_norms=tuple(dict.fromkeys(active)),
        inactive_norms=tuple(dict.fromkeys(inactive)),
        violated_norms=tuple(dict.fromkeys(violated)),
        reparation_active=tuple(dict.fromkeys(reparation_active)),
        queries=queries,
    )


def evaluate_theory(
    theory: NormativeTheory,
    profile: NormativeProfile,
) -> NormativeEvaluation:
    """Evaluate *theory* under the named *profile* semantics.

    Results never claim classical entailment or cross-profile equivalence.
    """

    if profile is None:
        raise SyntaxContractError(
            "evaluate_theory requires a named NormativeProfile"
        )
    semantics = (
        profile.semantics
        if isinstance(profile.semantics, NormativeSemantics)
        else NormativeSemantics(str(profile.semantics))
    )
    if semantics is NormativeSemantics.DYADIC:
        return _evaluate_dyadic(theory, profile)
    if semantics is NormativeSemantics.DEFEASIBLE:
        return _evaluate_defeasible(theory, profile)
    if semantics is NormativeSemantics.PRIORITIZED:
        return _evaluate_prioritized(theory, profile)
    if semantics is NormativeSemantics.CONTRARY_TO_DUTY:
        return _evaluate_ctd(theory, profile)
    raise SyntaxContractError(f"unsupported semantics {semantics!r}")


# ---------------------------------------------------------------------------
# Evidence contracts — no classical entailment promotion
# ---------------------------------------------------------------------------


class AuthorityPromotionError(SyntaxContractError):
    """Raised when evidence is promoted beyond its declared authority ceiling."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_AUTHORITY_CEILING,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NormativeEvidenceContract:
    """Authority ceiling for normative evidence.

    Normative evaluation results are **never** classical entailment authority.
    """

    source: EvidenceSource | str
    authority: EvidenceAuthority | str
    semantics: NormativeSemantics | str
    profile_id: str
    bound: BoundednessKind | str = BoundednessKind.FINITE_THEORY
    grants_classical_entailment: bool = False
    grants_material_implication_equiv: bool = False
    grants_cross_profile_equiv: bool = False
    schema_version: str = NORM_EVIDENCE_CONTRACT_SCHEMA

    interface: ClassVar[str] = NORMATIVE_LOGIC_PROFILES_INTERFACE

    def __post_init__(self) -> None:
        source = (
            self.source
            if isinstance(self.source, EvidenceSource)
            else EvidenceSource(str(self.source))
        )
        authority = (
            self.authority
            if isinstance(self.authority, EvidenceAuthority)
            else EvidenceAuthority(str(self.authority))
        )
        semantics = (
            self.semantics
            if isinstance(self.semantics, NormativeSemantics)
            else NormativeSemantics(str(self.semantics))
        )
        bound = (
            self.bound
            if isinstance(self.bound, BoundednessKind)
            else BoundednessKind(str(self.bound))
        )
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "NormativeEvidenceContract.profile_id is required"
            )
        ceiling = _SOURCE_AUTHORITY_CEILING[source]
        if _AUTHORITY_RANK[authority] > _AUTHORITY_RANK[ceiling]:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot claim {authority.value} "
                f"authority (ceiling={ceiling.value})"
            )
        if authority is EvidenceAuthority.CLASSICAL_ENTAILMENT:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot become classical entailment"
            )
        if self.grants_classical_entailment:
            raise AuthorityPromotionError(
                "grants_classical_entailment=True is not permitted"
            )
        if self.grants_material_implication_equiv:
            raise AuthorityPromotionError(
                "grants_material_implication_equiv=True is not permitted",
                code=CODE_UNEARNED_EQUIVALENCE,
            )
        if self.grants_cross_profile_equiv:
            raise AuthorityPromotionError(
                "grants_cross_profile_equiv=True is not permitted",
                code=CODE_CROSS_PROFILE_COLLAPSE,
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "bound", bound)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(self, "grants_classical_entailment", False)
        object.__setattr__(self, "grants_material_implication_equiv", False)
        object.__setattr__(self, "grants_cross_profile_equiv", False)

    @property
    def authority_ceiling(self) -> EvidenceAuthority:
        assert isinstance(self.authority, EvidenceAuthority)
        return self.authority

    @property
    def may_promote_to_classical_entailment(self) -> bool:
        return False

    @property
    def is_classical_entailment(self) -> bool:
        return False

    def promote_to_classical_entailment(self) -> None:
        raise AuthorityPromotionError(
            "normative evidence cannot be promoted to classical entailment"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority_ceiling.value,
            "authority_ceiling": self.authority_ceiling.value,
            "bound": (
                self.bound.value
                if isinstance(self.bound, BoundednessKind)
                else str(self.bound)
            ),
            "grants_classical_entailment": False,
            "grants_cross_profile_equiv": False,
            "grants_material_implication_equiv": False,
            "interface": self.interface,
            "is_classical_entailment": False,
            "may_promote_to_classical_entailment": False,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "semantics": (
                self.semantics.value
                if isinstance(self.semantics, NormativeSemantics)
                else str(self.semantics)
            ),
            "source": (
                self.source.value
                if isinstance(self.source, EvidenceSource)
                else str(self.source)
            ),
        }


def dyadic_evidence_contract(
    profile: NormativeProfile | None = None,
) -> NormativeEvidenceContract:
    prof = profile or profile_dyadic()
    return NormativeEvidenceContract(
        source=EvidenceSource.DYADIC_EVALUATOR,
        authority=EvidenceAuthority.NORMATIVE,
        semantics=NormativeSemantics.DYADIC,
        profile_id=prof.profile_id,
    )


def defeasible_evidence_contract(
    profile: NormativeProfile | None = None,
) -> NormativeEvidenceContract:
    prof = profile or profile_defeasible()
    return NormativeEvidenceContract(
        source=EvidenceSource.DEFEASIBLE_EVALUATOR,
        authority=EvidenceAuthority.NONMONOTONIC,
        semantics=NormativeSemantics.DEFEASIBLE,
        profile_id=prof.profile_id,
    )


def prioritized_evidence_contract(
    profile: NormativeProfile | None = None,
) -> NormativeEvidenceContract:
    prof = profile or profile_prioritized()
    return NormativeEvidenceContract(
        source=EvidenceSource.PRIORITIZED_EVALUATOR,
        authority=EvidenceAuthority.NORMATIVE,
        semantics=NormativeSemantics.PRIORITIZED,
        profile_id=prof.profile_id,
    )


def ctd_evidence_contract(
    profile: NormativeProfile | None = None,
) -> NormativeEvidenceContract:
    prof = profile or profile_contrary_to_duty()
    return NormativeEvidenceContract(
        source=EvidenceSource.CTD_EVALUATOR,
        authority=EvidenceAuthority.NORMATIVE,
        semantics=NormativeSemantics.CONTRARY_TO_DUTY,
        profile_id=prof.profile_id,
    )


def retain_authority_ceiling(
    evidence: NormativeEvidenceContract,
    *,
    claimed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project evidence while retaining the declared authority ceiling."""

    payload = evidence.to_dict()
    if claimed:
        claimed_authority = str(
            claimed.get("authority")
            or claimed.get("authority_ceiling")
            or payload["authority"]
        )
        claimed_classical = bool(
            claimed.get("grants_classical_entailment", False)
            or claimed.get("is_classical_entailment", False)
            or claimed.get("classical_entailment", False)
        )
        if (
            claimed_authority == EvidenceAuthority.CLASSICAL_ENTAILMENT.value
            or claimed_classical
        ):
            raise AuthorityPromotionError(
                "claimed classical entailment exceeds retained ceiling"
            )
        if claimed.get("grants_material_implication_equiv") is True:
            raise AuthorityPromotionError(
                "claimed material-implication equivalence is rejected",
                code=CODE_UNEARNED_EQUIVALENCE,
            )
        if claimed.get("grants_cross_profile_equiv") is True:
            raise AuthorityPromotionError(
                "claimed cross-profile equivalence is rejected",
                code=CODE_CROSS_PROFILE_COLLAPSE,
            )
    retained = dict(payload)
    retained["authority"] = evidence.authority_ceiling.value
    retained["authority_ceiling"] = evidence.authority_ceiling.value
    retained["grants_classical_entailment"] = False
    retained["may_promote_to_classical_entailment"] = False
    retained["is_classical_entailment"] = False
    retained["grants_material_implication_equiv"] = False
    retained["grants_cross_profile_equiv"] = False
    return retained


@dataclass(frozen=True, slots=True)
class NormativeLoweringReceipt:
    """Receipt for one evaluation / evidence attachment."""

    document_id: str
    profile_id: str
    semantics: str
    evaluation: dict[str, Any]
    evidence: dict[str, Any]
    semantic_decision_record: dict[str, Any] = field(default_factory=dict)
    authorizes_classical_entailment: bool = False
    schema_version: str = NORM_LOWERING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.authorizes_classical_entailment:
            raise AuthorityPromotionError(
                "lowering receipt cannot authorize classical entailment"
            )
        if self.evidence.get("grants_classical_entailment") or self.evidence.get(
            "is_classical_entailment"
        ):
            raise AuthorityPromotionError(
                "normative evidence cannot become classical entailment "
                "on a lowering receipt"
            )
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "NormativeLoweringReceipt.profile_id is required"
            )
        if not self.semantics or not str(self.semantics).strip():
            raise SyntaxContractError(
                "NormativeLoweringReceipt.semantics is required"
            )
        object.__setattr__(self, "authorizes_classical_entailment", False)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(self, "semantics", str(self.semantics).strip())

    @property
    def authority_ceiling(self) -> str:
        return str(
            self.evidence.get("authority_ceiling")
            or self.evidence.get("authority")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_classical_entailment": False,
            "authority_ceiling": self.authority_ceiling,
            "document_id": self.document_id,
            "evaluation": dict(self.evaluation),
            "evidence": dict(self.evidence),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "semantic_decision_record": dict(self.semantic_decision_record),
            "semantics": self.semantics,
        }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormativeParseResult:
    """Typed result of a controlled normative parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: NormativeProfile | None = None
    theory: NormativeTheory | None = None
    evaluation: NormativeEvaluation | None = None
    semantic_decision_record: SemanticDecisionRecord | None = None
    schema_version: str = NORM_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = NORMATIVE_LOGIC_PROFILES_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "interface": self.interface,
            "printed": self.printed,
            "profile": self.profile.to_dict() if self.profile else None,
            "schema_version": self.schema_version,
            "semantic_decision_record": (
                self.semantic_decision_record.to_dict()
                if self.semantic_decision_record
                else None
            ),
            "status": self.status.value
            if isinstance(self.status, ParseStatus)
            else str(self.status),
            "theory": self.theory.to_dict() if self.theory else None,
        }


class NormativeParseError(SyntaxContractError):
    """Raised by raising helpers when a normative parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: NormativeParseResult | None = None,
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


def _diag(
    *,
    code: str,
    message: str,
    range: SourceRange | None,
    remediation: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:norm:{code.replace('.', '-')}",
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


class NormativePrinter:
    """Deterministic printer for normative theory ASTs."""

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
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            parts = [
                self._print_node(arg, _Prec.AND) for arg in node.arguments
            ]
            text = f" {self._op('and', '∧')} ".join(parts)
            if parent_prec > _Prec.AND:
                return f"({text})"
            return text
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node)
        raise SyntaxContractError(
            f"cannot print node kind "
            f"{kind.value if isinstance(kind, NodeKind) else kind}"
        )

    def _print_op(self, operator: str) -> str:
        return _OP_SURFACE.get(operator, operator)

    def _print_extension(self, node: LogicNode) -> str:
        ext = node.extension
        if ext is None:
            raise SyntaxContractError("EXTENSION node missing extension payload")
        schema = ext.payload_schema
        payload = dict(ext.payload)

        if schema == NORM_MONADIC_PAYLOAD_SCHEMA:
            return (
                f"{self._print_op(str(payload['operator']))}"
                f"({payload['content']})"
            )
        if schema == NORM_DYADIC_PAYLOAD_SCHEMA:
            return (
                f"{self._print_op(str(payload['operator']))}"
                f"({payload['content']} | {payload['condition']})"
            )
        if schema == NORM_DEFEASIBLE_PAYLOAD_SCHEMA:
            base = (
                f"defeasible {self._print_op(str(payload['operator']))}"
                f"({payload['content']})"
            )
            unless = payload.get("unless") or ""
            if unless:
                return f"{base} unless {unless}"
            return base
        if schema == NORM_EXCEPTION_PAYLOAD_SCHEMA:
            return f"exception({payload['norm_id']}, {payload['exception']})"
        if schema == NORM_PRIORITY_PAYLOAD_SCHEMA:
            return f"priority({payload['higher']}, {payload['lower']})"
        if schema == NORM_CTD_PAYLOAD_SCHEMA:
            return f"ctd({payload['primary']}, {payload['secondary']})"
        if schema == NORM_REPARATION_PAYLOAD_SCHEMA:
            return (
                f"reparation({payload['violated']}, {payload['reparation']})"
            )
        if schema == NORM_VIOLATION_PAYLOAD_SCHEMA:
            return f"violation({payload['content']})"
        if schema == NORM_CONFLICT_PAYLOAD_SCHEMA:
            return f"conflict({payload['left']}, {payload['right']})"
        if schema == NORM_FACT_PAYLOAD_SCHEMA:
            return f"fact({payload['atom']})"
        if schema == NORM_NAMED_PAYLOAD_SCHEMA:
            return (
                f"norm({payload['norm_id']}, "
                f"{self._print_op(str(payload['operator']))}"
                f"({payload['content']}))"
            )
        if schema == NORM_STATUS_PAYLOAD_SCHEMA:
            return f"status({payload['atom']})"
        raise SyntaxContractError(
            f"cannot print unknown normative payload schema {schema!r}"
        )


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


def _extract_profile(value: object) -> NormativeProfile | None:
    if value is None:
        return None
    if isinstance(value, NormativeProfile):
        return value
    if isinstance(value, Mapping):
        return NormativeProfile.from_dict(value)
    return None


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:norm:1",
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


def _signature_for_theory(
    theory: NormativeTheory,
    profile: NormativeProfile,
) -> LogicSignature:
    return LogicSignature(
        signature_id=f"sig:norm:{profile.profile_id}",
        family=profile.family_id,
        profile=profile.profile_id,
        sorts=(NORM_SORT, PROPOSITION_SORT, INDIVIDUAL_SORT),
        symbols=(),
        features=("normative", "deontic", profile.semantics_name),
        metadata={
            "semantics": profile.semantics_name,
            "dyadic_count": len(theory.dyadic),
            "defeasible_count": len(theory.defeasible),
            "ctd_count": len(theory.ctd),
        },
    )


def _canonical_operator(name: str) -> str:
    folded = name.casefold()
    if folded not in _OP_CANONICAL:
        raise SyntaxContractError(f"unknown deontic operator {name!r}")
    return _OP_CANONICAL[folded]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class NormativeParser:
    """Parser for controlled normative surface text under named profiles."""

    interface: ClassVar[str] = NORMATIVE_LOGIC_PROFILES_INTERFACE

    def __init__(
        self,
        profile: NormativeProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_dyadic()
        self.printer = NormativePrinter(style=print_style)
        self._lexer = BoundedLexer(
            keywords=_NORM_KEYWORDS,
            multi_char_operators=(
                ":-",
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
        return f"norm:{prefix}:{self._counter}"

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("normative_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:norm:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: NormativeProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:norm:1",
        expression_id: str = "expr:norm:1",
        evaluate: bool = True,
    ) -> NormativeParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_REQUIRED,
                message=(
                    "normative parse requires a named profile; "
                    "semantics/profile is always named"
                ),
                range=document.full_range(),
                remediation=(
                    "Pass profile_dyadic(), profile_defeasible(), "
                    "profile_prioritized(), or profile_contrary_to_duty()"
                ),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": NORMATIVE_LOGIC_PROFILES_INTERFACE},
            )
            return NormativeParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )
        if not isinstance(prof, NormativeProfile):
            raise SyntaxContractError("profile must be a NormativeProfile")

        self._counter = 0
        sdr = prof.semantic_decision_record

        if document.byte_length == 0 or not document.text.strip():
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty normative input",
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
                    "interface": NORMATIVE_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return NormativeParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
                profile=prof,
                semantic_decision_record=sdr,
            )

        lex_result = self._lexer.lex(document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:norm:lex:{index + 1}",
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
                    "interface": NORMATIVE_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return NormativeParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                semantic_decision_record=sdr,
            )

        diags: list[SyntaxDiagnostic] = list(lex_result.diagnostics)
        cursor = _Cursor(lex_result.tokens, document)
        try:
            root = self._parse_theory(cursor, prof)
            if not cursor.is_eof():
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=(
                            f"trailing input after theory: "
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
                    "interface": NORMATIVE_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return NormativeParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
                semantic_decision_record=sdr,
            )

        printed = self.printer.print(root)
        theory = extract_theory(root)
        evaluation: NormativeEvaluation | None = None
        eval_diags: list[SyntaxDiagnostic] = []
        if evaluate:
            try:
                evaluation = evaluate_theory(theory, prof)
            except SyntaxContractError as error:
                eval_diags.append(
                    _diag(
                        code=CODE_EVALUATION_FAILED,
                        message=str(error),
                        range=root.range or SourceRange(0, 0),
                    )
                )

        all_diags = tuple(diags) + tuple(eval_diags)
        if eval_diags:
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.FAILED,
                tokens=lex_result.tokens,
                diagnostics=all_diags,
                metadata={
                    "interface": NORMATIVE_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return NormativeParseResult(
                status=ParseStatus.FAILED,
                root=root,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                printed=printed,
                profile=prof,
                theory=theory,
                semantic_decision_record=sdr,
            )

        signature = _signature_for_theory(theory, prof)
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
                "interface": NORMATIVE_LOGIC_PROFILES_INTERFACE,
                "profile": prof.to_dict(),
                "theory": theory.to_dict(),
                "evaluation": evaluation.to_dict() if evaluation else None,
                "printed": printed,
                "semantics": prof.semantics_name,
                "semantic_decision_record": sdr.to_dict(),
            },
        )
        return NormativeParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            theory=theory,
            evaluation=evaluation,
            semantic_decision_record=sdr,
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

    def _parse_theory(
        self,
        cursor: _Cursor,
        profile: NormativeProfile,
    ) -> LogicNode:
        left = self._parse_statement(cursor, profile)
        while True:
            if cursor.match_any(frozenset({"and", "∧", "&", "&&"})) is not None:
                right = self._parse_statement(cursor, profile)
            elif cursor.current().lexeme == ",":
                nxt = cursor.peek()
                if nxt.kind == TokenKind.EOF.value:
                    break
                if (
                    nxt.lexeme.casefold() in _STATEMENT_ATOMS
                    or nxt.lexeme == "("
                ):
                    cursor.advance()
                    right = self._parse_statement(cursor, profile)
                else:
                    break
            else:
                break
            span = cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = LogicNode(
                node_id=self._nid("and"),
                kind=NodeKind.AND,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
                metadata={
                    "schema_version": NORM_AND_PAYLOAD_SCHEMA,
                    "family": NORM_FAMILY_ID,
                },
            )
        return left

    def _parse_statement(
        self,
        cursor: _Cursor,
        profile: NormativeProfile,
    ) -> LogicNode:
        self._enter(cursor)
        try:
            token = cursor.current()
            if token.lexeme == "(":
                cursor.advance()
                inner = self._parse_theory(cursor, profile)
                cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                return inner

            name = token.lexeme.casefold()

            # Negative ambiguity: bare ambiguous markers fail closed.
            if name in _AMBIGUOUS_MARKERS and name not in {
                "unless",  # unless only valid after defeasible norm
            }:
                raise _ParseFail(
                    _diag(
                        code=CODE_AMBIGUOUS_FORM,
                        message=(
                            f"ambiguous normative marker {token.lexeme!r} "
                            "requires an explicit named profile construct "
                            "(use defeasible/normally with unless, not bare "
                            f"{token.lexeme!r})"
                        ),
                        range=token.range,
                        remediation=(
                            "Write 'defeasible O(p) unless q' under "
                            "profile_defeasible(); bare markers are rejected"
                        ),
                    )
                )

            if name in _STATEMENT_ATOMS and token.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                return self._parse_atom(cursor, profile, name)

            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=(
                        f"expected normative statement; got {token.lexeme!r}"
                    ),
                    range=token.range,
                    remediation=(
                        "Use O/P/F(...), O(p|q), defeasible O(p) unless q, "
                        "exception(...), priority(...), ctd(...), "
                        "reparation(...), violation(...), fact(...), "
                        "norm(...), or status(...)"
                    ),
                )
            )
        finally:
            self._leave(cursor)

    def _parse_atom(
        self,
        cursor: _Cursor,
        profile: NormativeProfile,
        name: str,
    ) -> LogicNode:
        start = cursor.advance()

        if name in _DEONTIC_OPS:
            return self._parse_deontic_application(cursor, profile, name, start)

        if name in {"defeasible", "normally"}:
            if not profile.admit_defeasible:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"defeasible norms are not admitted by profile "
                            f"{profile.profile_id!r} "
                            f"(semantics={profile.semantics_name})"
                        ),
                        range=start.range,
                        remediation="Use profile_defeasible()",
                    )
                )
            op_tok = cursor.current()
            op_name = op_tok.lexeme.casefold()
            if op_name not in _DEONTIC_OPS:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message=(
                            f"expected deontic operator after {name!r}; "
                            f"got {op_tok.lexeme!r}"
                        ),
                        range=op_tok.range,
                    )
                )
            cursor.advance()
            if not profile.admit_classic_letters and op_name in {"o", "p", "f"}:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"classic letter {op_tok.lexeme!r} not admitted"
                        ),
                        range=op_tok.range,
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            content = cursor.expect_ident()
            # Defeasible form is monadic only (dyadic+defeasible needs both
            # flags and is rejected as ambiguous under this frontend).
            if cursor.match_lexeme("|", "/") is not None:
                raise _ParseFail(
                    _diag(
                        code=CODE_AMBIGUOUS_FORM,
                        message=(
                            "defeasible dyadic form is ambiguous and rejected; "
                            "use pure defeasible monadic or pure dyadic profile"
                        ),
                        range=cursor.current().range,
                        remediation=(
                            "Write 'defeasible O(p) unless q' or "
                            "'O(p | q)' under the matching single profile"
                        ),
                    )
                )
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            unless_atom = ""
            if cursor.match_lexeme("unless") is not None:
                unless_tok = cursor.expect_ident()
                unless_atom = unless_tok.lexeme
                end = unless_tok
            span = cursor.range_span(start.range, end.range)
            return self._build_defeasible(
                _canonical_operator(op_name),
                content.lexeme,
                unless_atom,
                profile,
                span,
            )

        if name == "exception":
            if not profile.admit_exception:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"exceptions are not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                        remediation="Use profile_defeasible()",
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            nid = cursor.expect_ident()
            cursor.expect_lexeme(",")
            exc = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_exception(
                nid.lexeme, exc.lexeme, profile, span
            )

        if name == "priority":
            if not profile.admit_priority:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"priority is not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                        remediation="Use profile_prioritized()",
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            higher = cursor.expect_ident()
            if cursor.match_lexeme(">") is None:
                cursor.expect_lexeme(",")
            lower = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_priority(
                higher.lexeme, lower.lexeme, profile, span
            )

        if name in {"ctd", "contrary_to_duty"}:
            if not profile.admit_contrary_to_duty:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"contrary-to-duty is not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                        remediation="Use profile_contrary_to_duty()",
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            primary = cursor.expect_ident()
            cursor.expect_lexeme(",")
            secondary = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_ctd(
                primary.lexeme, secondary.lexeme, profile, span
            )

        if name == "reparation":
            if not profile.admit_reparation:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"reparation is not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                        remediation="Use profile_contrary_to_duty()",
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            violated = cursor.expect_ident()
            cursor.expect_lexeme(",")
            reparation = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_reparation(
                violated.lexeme, reparation.lexeme, profile, span
            )

        if name == "violation":
            if not profile.admit_violation:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"violation is not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                        remediation="Use profile_contrary_to_duty()",
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            content = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_violation(content.lexeme, profile, span)

        if name == "conflict":
            if not profile.admit_conflict:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"conflict is not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                        remediation="Use profile_prioritized()",
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            left = cursor.expect_ident()
            cursor.expect_lexeme(",")
            right = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_conflict(
                left.lexeme, right.lexeme, profile, span
            )

        if name in {"fact", "holds"}:
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            atom = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_fact(atom.lexeme, profile, span)

        if name == "norm":
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            nid = cursor.expect_ident()
            cursor.expect_lexeme(",")
            op_tok = cursor.current()
            op_name = op_tok.lexeme.casefold()
            if op_name not in _DEONTIC_OPS:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message=(
                            f"expected deontic operator in named norm; "
                            f"got {op_tok.lexeme!r}"
                        ),
                        range=op_tok.range,
                    )
                )
            cursor.advance()
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            content = cursor.expect_ident()
            cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_named(
                nid.lexeme,
                _canonical_operator(op_name),
                content.lexeme,
                profile,
                span,
            )

        if name in {"status", "query"}:
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            atom = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_status(atom.lexeme, profile, span)

        raise _ParseFail(
            _diag(
                code=CODE_UNSUPPORTED_CONSTRUCT,
                message=f"unsupported construct {name!r}",
                range=start.range,
            )
        )

    def _parse_deontic_application(
        self,
        cursor: _Cursor,
        profile: NormativeProfile,
        name: str,
        start: LogicToken,
    ) -> LogicNode:
        if name in {"o", "p", "f"} and not profile.admit_classic_letters:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=f"classic letter {start.lexeme!r} not admitted",
                    range=start.range,
                )
            )
        operator = _canonical_operator(name)
        cursor.expect_lexeme("(", code=CODE_UNBALANCED)
        first = cursor.expect_ident()
        # Dyadic separator?
        if cursor.match_lexeme("|", "/") is not None:
            if not profile.admit_dyadic:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"dyadic norms are not admitted by profile "
                            f"{profile.profile_id!r} "
                            f"(semantics={profile.semantics_name}); "
                            "dyadic separator is not classical disjunction"
                        ),
                        range=cursor.current().range,
                        remediation="Use profile_dyadic()",
                        metadata={"rejected_as": "unearned_or_disjunction"},
                    )
                )
            second = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_dyadic(
                operator, first.lexeme, second.lexeme, profile, span
            )
        # Ambiguous: bare '|' after content without second atom already handled.
        # Reject 'or' misused as dyadic separator under dyadic profile.
        if cursor.current().lexeme.casefold() in {"or", "∨", "||"}:
            raise _ParseFail(
                _diag(
                    code=CODE_AMBIGUOUS_FORM,
                    message=(
                        f"{cursor.current().lexeme!r} is classical disjunction, "
                        "not a dyadic condition separator; use '|' or '/' "
                        "for dyadic norms"
                    ),
                    range=cursor.current().range,
                    remediation="Write O(content | condition), not O(content or condition)",
                )
            )
        if not profile.admit_monadic:
            raise _ParseFail(
                _diag(
                    code=CODE_PROFILE_MISMATCH,
                    message=(
                        f"monadic norms are not admitted by profile "
                        f"{profile.profile_id!r}"
                    ),
                    range=start.range,
                )
            )
        end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
        span = cursor.range_span(start.range, end.range)
        return self._build_monadic(operator, first.lexeme, profile, span)

    # -- builders ----------------------------------------------------------

    def _build_monadic(
        self,
        operator: str,
        content: str,
        profile: NormativeProfile,
        span: SourceRange,
        *,
        norm_id: str = "",
    ) -> LogicNode:
        payload = {
            "content": content,
            "kind": "monadic",
            "norm_id": norm_id,
            "operator": operator,
            "profile_id": profile.profile_id,
            "schema_version": NORM_MONADIC_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("monadic"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.monadic",),
            payload_schema=NORM_MONADIC_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_dyadic(
        self,
        operator: str,
        content: str,
        condition: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "condition": condition,
            "content": content,
            "kind": "dyadic",
            "material_implication_equiv": False,
            "norm_id": "",
            "operator": operator,
            "profile_id": profile.profile_id,
            "schema_version": NORM_DYADIC_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("dyadic"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.dyadic", "normative.conditional"),
            payload_schema=NORM_DYADIC_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_defeasible(
        self,
        operator: str,
        content: str,
        unless: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "content": content,
            "kind": "defeasible",
            "norm_id": "",
            "operator": operator,
            "profile_id": profile.profile_id,
            "schema_version": NORM_DEFEASIBLE_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
            "strict_implication_equiv": False,
            "unless": unless,
        }
        return mk_extension(
            self._nid("defeasible"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.defeasible", "normative.nonmonotonic"),
            payload_schema=NORM_DEFEASIBLE_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_exception(
        self,
        norm_id: str,
        exception: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "exception": exception,
            "kind": "exception",
            "norm_id": norm_id,
            "profile_id": profile.profile_id,
            "schema_version": NORM_EXCEPTION_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("exception"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.exception",),
            payload_schema=NORM_EXCEPTION_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_priority(
        self,
        higher: str,
        lower: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "higher": higher,
            "kind": "priority",
            "lower": lower,
            "profile_id": profile.profile_id,
            "schema_version": NORM_PRIORITY_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("priority"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.priority",),
            payload_schema=NORM_PRIORITY_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_ctd(
        self,
        primary: str,
        secondary: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "conjunction_equiv": False,
            "kind": "contrary_to_duty",
            "norm_id": "",
            "primary": primary,
            "profile_id": profile.profile_id,
            "schema_version": NORM_CTD_PAYLOAD_SCHEMA,
            "secondary": secondary,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("ctd"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.contrary_to_duty", "normative.reparation"),
            payload_schema=NORM_CTD_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_reparation(
        self,
        violated: str,
        reparation: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "independent_obligation_equiv": False,
            "kind": "reparation",
            "profile_id": profile.profile_id,
            "reparation": reparation,
            "schema_version": NORM_REPARATION_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
            "violated": violated,
        }
        return mk_extension(
            self._nid("reparation"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.reparation",),
            payload_schema=NORM_REPARATION_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_violation(
        self,
        content: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "content": content,
            "kind": "violation",
            "profile_id": profile.profile_id,
            "schema_version": NORM_VIOLATION_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("violation"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.violation",),
            payload_schema=NORM_VIOLATION_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_conflict(
        self,
        left: str,
        right: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "kind": "conflict",
            "left": left,
            "profile_id": profile.profile_id,
            "right": right,
            "schema_version": NORM_CONFLICT_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("conflict"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.conflict",),
            payload_schema=NORM_CONFLICT_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_fact(
        self,
        atom: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "atom": atom,
            "kind": "fact",
            "profile_id": profile.profile_id,
            "schema_version": NORM_FACT_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("fact"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.fact",),
            payload_schema=NORM_FACT_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_named(
        self,
        norm_id: str,
        operator: str,
        content: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "content": content,
            "kind": "named_norm",
            "norm_id": norm_id,
            "operator": operator,
            "profile_id": profile.profile_id,
            "schema_version": NORM_NAMED_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("named"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.named_norm",),
            payload_schema=NORM_NAMED_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_status(
        self,
        atom: str,
        profile: NormativeProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "atom": atom,
            "kind": "status_query",
            "profile_id": profile.profile_id,
            "schema_version": NORM_STATUS_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("status"),
            family=NORM_FAMILY_ID,
            profile=profile.profile_id,
            features=("normative.status_query",),
            payload_schema=NORM_STATUS_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class NormativeLogicProfiles:
    """Facade for ``NormativeLogicProfiles@2``."""

    interface: ClassVar[str] = NORMATIVE_LOGIC_PROFILES_INTERFACE

    def __init__(
        self,
        profile: NormativeProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_dyadic()
        self.parser = NormativeParser(self.profile, print_style=print_style)
        self.printer = NormativePrinter(style=print_style)

    @property
    def semantic_decision_record(self) -> SemanticDecisionRecord:
        return self.profile.semantic_decision_record

    def parse_text(self, text: str, **kwargs: Any) -> NormativeParseResult:
        document_id = str(kwargs.pop("document_id", "doc:norm:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:norm:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:norm:1"))
        evaluate = bool(kwargs.pop("evaluate", True))
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
            evaluate=evaluate,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise NormativeParseError(
                "normative parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def evaluate(
        self,
        theory: NormativeTheory | LogicNode | NormativeParseResult,
        *,
        profile: NormativeProfile | None = None,
    ) -> NormativeEvaluation:
        prof = profile or self.profile
        if isinstance(theory, NormativeParseResult):
            if theory.theory is None:
                raise NormativeParseError(
                    "parse result has no theory to evaluate"
                )
            th = theory.theory
            if theory.profile is not None and profile is None:
                prof = theory.profile
        elif isinstance(theory, LogicNode):
            th = extract_theory(theory)
        elif isinstance(theory, NormativeTheory):
            th = theory
        else:
            raise SyntaxContractError(
                "evaluate requires NormativeTheory, LogicNode, or parse result"
            )
        return evaluate_theory(th, prof)

    def attach_evidence(
        self,
        result: NormativeParseResult,
        evidence: NormativeEvidenceContract,
        *,
        document_id: str = "doc:norm:1",
    ) -> NormativeLoweringReceipt:
        """Attach evidence while retaining authority ceilings."""

        if result.profile is None:
            raise NormativeParseError(
                "cannot attach evidence without a profile on the parse result"
            )
        retained = retain_authority_ceiling(evidence)
        evaluation = (
            result.evaluation.to_dict()
            if result.evaluation is not None
            else {}
        )
        sdr = (
            result.semantic_decision_record.to_dict()
            if result.semantic_decision_record is not None
            else result.profile.semantic_decision_record.to_dict()
        )
        return NormativeLoweringReceipt(
            document_id=document_id,
            profile_id=result.profile.profile_id,
            semantics=result.profile.semantics_name,
            evaluation=evaluation,
            evidence=retained,
            semantic_decision_record=sdr,
            authorizes_classical_entailment=False,
        )


def parse_normative(
    text: str,
    profile: NormativeProfile | None = None,
    **kwargs: Any,
) -> NormativeParseResult:
    """Parse normative *text* under named *profile*."""

    logic = NormativeLogicProfiles(profile or profile_dyadic())
    return logic.parse_text(text, **kwargs)


def print_normative(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return NormativePrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: NormativeProfile | None = None,
) -> tuple[NormativeParseResult, NormativeParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_dyadic()
    first = parse_normative(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_normative(first.root)
    second = parse_normative(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "NORMATIVE_LOGIC_PROFILES_INTERFACE",
    "NORMATIVE_PROFILE_INTERFACE",
    "NORMATIVE_SEMANTIC_DECISION_INTERFACE",
    "NORM_FAMILY_ID",
    "NORM_NOTATION_ID",
    "AuthorityPromotionError",
    "BoundednessKind",
    "ContraryToDuty",
    "DefeasibleNorm",
    "DyadicNorm",
    "EvidenceAuthority",
    "EvidenceSource",
    "MonadicNorm",
    "NormOperator",
    "NormStatus",
    "NormativeEvaluation",
    "NormativeEvidenceContract",
    "NormativeLogicProfiles",
    "NormativeLoweringReceipt",
    "NormativeParseError",
    "NormativeParseResult",
    "NormativeParser",
    "NormativePrinter",
    "NormativeProfile",
    "NormativeSemantics",
    "NormativeTheory",
    "PrintStyle",
    "SemanticDecisionRecord",
    "ctd_evidence_contract",
    "defeasible_evidence_contract",
    "dyadic_evidence_contract",
    "evaluate_theory",
    "extract_theory",
    "normative_semantic_identity",
    "parse_normative",
    "parse_print_parse",
    "print_normative",
    "prioritized_evidence_contract",
    "profile_contrary_to_duty",
    "profile_defeasible",
    "profile_dyadic",
    "profile_prioritized",
    "profiles_are_equivalent",
    "reject_unearned_equivalence",
    "retain_authority_ceiling",
    # Diagnostic codes
    "CODE_AMBIGUOUS_FORM",
    "CODE_AUTHORITY_CEILING",
    "CODE_CROSS_PROFILE_COLLAPSE",
    "CODE_EMPTY_INPUT",
    "CODE_PROFILE_MISMATCH",
    "CODE_PROFILE_REQUIRED",
    "CODE_PROMOTION_REJECTED",
    "CODE_UNEARNED_EQUIVALENCE",
    "CODE_UNEXPECTED_TOKEN",
]
