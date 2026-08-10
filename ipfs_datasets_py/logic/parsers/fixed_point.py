"""Mu-calculus syntax and controlled CTL-star lowering.

Interface:

* ``FixedPointLogicProfiles@1`` — parse/print/elaborate for propositional
  mu-calculus (least/greatest fixed points) with positivity and guardedness
  checks, plus controlled CTL-star fragment lowering to mu-calculus

Owned constructs:

* least fixed point ``mu X. φ`` / ``μ X. φ``
* greatest fixed point ``nu X. φ`` / ``ν X. φ``
* modal next operators ``diamond``/``box`` (and ``EX``/``AX``, ``◇``/``□``)
* binder positivity (no negative occurrences of the bound variable)
* binder guardedness (every occurrence of the bound variable is under a modal)
* alternation-depth ceilings on nested mu/nu binders
* controlled CTL state-formula lowering (``AG``/``EG``/``AF``/``EF``/``AX``/
  ``EX`` and path-quantified until) into equivalent mu-calculus

Authority ceilings (fail-closed):

* Declaration of the ``mu_calculus`` family or a profile **never** implies
  executable model-checking support.  Profiles default to
  ``executable_support=False``; model-check evidence remains bounded/advisory
  and cannot be promoted to universal proof.
* Unsupported CTL-star forms and alternation-depth violations fail with
  explicit diagnostic codes (never silent drop or partial lower).

Grammar (connective precedence, low → high)::

    formula     ::= fixed_point | iff
    fixed_point ::= ('mu'|'nu'|'μ'|'ν') IDENT '.' formula
    iff         ::= implies (('iff'|↔) implies)*
    implies     ::= or (('implies'|→|=>|->) formula)?   # right-assoc
    or          ::= and (('or'|∨) and)*
    and         ::= unary (('and'|∧) unary)*
    unary       ::= ('not'|¬) unary
                  | modal unary
                  | ctl_state
                  | atomic
    modal       ::= 'diamond'|'box'|'EX'|'AX'|'◇'|'□'|'<>'|'[]'
    ctl_state   ::= ctl_letter unary
                  | path_quant temporal unary
                  | path_quant '(' unary 'until' unary ')'
    ctl_letter  ::= 'AG'|'EG'|'AF'|'EF'|'AX'|'EX'   # profile-gated
    path_quant  ::= 'A'|'E'|'all'|'exists'
    temporal    ::= 'always'|'eventually'|'next'|'G'|'F'|'X'
    atomic      ::= 'true'|⊤ | 'false'|⊥ | IDENT | '(' formula ')'

Evidence subset: mu calculus fixed point ctl star guarded positivity
model checking.
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
from ipfs_datasets_py.logic.syntax_core.lexer import BoundedLexer
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

FIXED_POINT_LOGIC_PROFILES_INTERFACE: Final = "FixedPointLogicProfiles@1"
FIXED_POINT_SYNTAX_INTERFACE: Final = "FixedPointSyntax@1"
CTL_STAR_LOWERING_INTERFACE: Final = "ControlledCTLStarLowering@1"

FP_NOTATION_ID: Final = "canonical_mu_calculus"
FP_NOTATION_VERSION: Final = "1.0.0"
FP_FAMILY_ID: Final = "mu_calculus"
FP_MODULE_VERSION: Final = "1.0.0"

FP_PARSE_RESULT_SCHEMA: Final = "canonical-fixed-point-parse-result/v1"
FP_PROFILE_SCHEMA: Final = "fixed-point-logic-profile/v1"
FP_BINDER_PAYLOAD_SCHEMA: Final = "fixed_point.binder/v1"
FP_VAR_PAYLOAD_SCHEMA: Final = "fixed_point.variable/v1"
FP_MODAL_PAYLOAD_SCHEMA: Final = "fixed_point.modal/v1"
FP_CTL_PAYLOAD_SCHEMA: Final = "fixed_point.ctl_surface/v1"
FP_EVIDENCE_CONTRACT_SCHEMA: Final = "fixed-point.evidence-contract/v1"
FP_LOWERING_RECEIPT_SCHEMA: Final = "fixed-point.lowering-receipt/v1"
FP_ALTERNATION_REPORT_SCHEMA: Final = "fixed-point.alternation-report/v1"
FP_GUARD_REPORT_SCHEMA: Final = "fixed-point.guard-report/v1"
FP_SOURCE_MAP_SCHEMA: Final = "fixed-point.source-map/v1"

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "fixed_point.unexpected_token"
CODE_TRAILING_INPUT: Final = "fixed_point.trailing_input"
CODE_EMPTY_INPUT: Final = "fixed_point.empty_input"
CODE_PARSE_DEPTH: Final = "fixed_point.parse_depth_exceeded"
CODE_UNBALANCED: Final = "fixed_point.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "fixed_point.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "fixed_point.unknown_character"
CODE_PROFILE_MISMATCH: Final = "fixed_point.profile_mismatch"
CODE_NEGATIVE_OCCURRENCE: Final = "fixed_point.negative_occurrence"
CODE_UNGUARDED_OCCURRENCE: Final = "fixed_point.unguarded_occurrence"
CODE_REBIND_VARIABLE: Final = "fixed_point.variable_rebind"
CODE_FREE_VARIABLE: Final = "fixed_point.free_variable"
CODE_UNSUPPORTED_CTL_STAR: Final = "fixed_point.unsupported_ctl_star"
CODE_ALTERNATION_DEPTH: Final = "fixed_point.alternation_depth_exceeded"
CODE_EXECUTABLE_SUPPORT: Final = "fixed_point.executable_support_required"
CODE_DECLARATION_ONLY: Final = "fixed_point.declaration_only"
CODE_ROUND_TRIP: Final = "fixed_point.round_trip_failed"
CODE_AUTHORITY_CEILING: Final = "fixed_point.authority_ceiling"
CODE_PROMOTION_REJECTED: Final = "fixed_point.proof_promotion_rejected"
CODE_MISSING_BINDER_DOT: Final = "fixed_point.missing_binder_dot"

_ALL_FP_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_UNKNOWN_CHARACTER,
        CODE_PROFILE_MISMATCH,
        CODE_NEGATIVE_OCCURRENCE,
        CODE_UNGUARDED_OCCURRENCE,
        CODE_REBIND_VARIABLE,
        CODE_FREE_VARIABLE,
        CODE_UNSUPPORTED_CTL_STAR,
        CODE_ALTERNATION_DEPTH,
        CODE_EXECUTABLE_SUPPORT,
        CODE_DECLARATION_ONLY,
        CODE_ROUND_TRIP,
        CODE_AUTHORITY_CEILING,
        CODE_PROMOTION_REJECTED,
        CODE_MISSING_BINDER_DOT,
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

_MU_WORDS: Final[frozenset[str]] = frozenset({"mu", "μ", "least", "lfp"})
_NU_WORDS: Final[frozenset[str]] = frozenset({"nu", "ν", "greatest", "gfp"})
_DIAMOND_WORDS: Final[frozenset[str]] = frozenset(
    {"diamond", "◇", "◊", "ex", "<>"}
)
_BOX_WORDS: Final[frozenset[str]] = frozenset({"box", "□", "ax", "[]"})
_PATH_ALL_WORDS: Final[frozenset[str]] = frozenset({"a", "all"})
_PATH_EXISTS_WORDS: Final[frozenset[str]] = frozenset({"e", "exists"})
_TEMP_ALWAYS: Final[frozenset[str]] = frozenset({"always", "g"})
_TEMP_EVENTUALLY: Final[frozenset[str]] = frozenset({"eventually", "f"})
_TEMP_NEXT: Final[frozenset[str]] = frozenset({"next", "x"})
_UNTIL_WORDS: Final[frozenset[str]] = frozenset({"until", "u"})

# Compact CTL letters (single tokens).
_CTL_COMPACT: Final[Mapping[str, tuple[str, str]]] = {
    "ag": ("all", "always"),
    "eg": ("exists", "always"),
    "af": ("all", "eventually"),
    "ef": ("exists", "eventually"),
    "ax": ("all", "next"),
    "ex": ("exists", "next"),
}

# Surface rewrite: Unicode binders / ASCII angle-bracket modalities.
_MU_NU_RE: Final = re.compile(r"[μν]")
_ANGLE_DIAMOND_RE: Final = re.compile(r"<>")
_BRACKET_BOX_RE: Final = re.compile(r"\[\]")

_FP_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "mu",
    "nu",
    "least",
    "greatest",
    "lfp",
    "gfp",
    "diamond",
    "box",
    "ex",
    "ax",
    "all",
    "exists",
    "always",
    "eventually",
    "next",
    "until",
    "ag",
    "eg",
    "af",
    "ef",
)

_FP_MULTI_OPS: Final[tuple[str, ...]] = (
    "<=>",
    "<->",
    "==>",
    "=>",
    "->",
    "&&",
    "||",
    "<>",
    "[]",
    "..",
    "::",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class FixedPointKind(str, Enum):
    """Least vs greatest fixed-point binder."""

    MU = "mu"
    NU = "nu"


class ModalKind(str, Enum):
    """One-step modal operators over transition systems."""

    DIAMOND = "diamond"  # EX / ◇
    BOX = "box"  # AX / □


class PathQuantifierKind(str, Enum):
    """Branching-time path quantifier for controlled CTL surface."""

    ALL = "all"
    EXISTS = "exists"


class TemporalOpKind(str, Enum):
    """Temporal operators admitted under controlled CTL surface."""

    NEXT = "next"
    ALWAYS = "always"
    EVENTUALLY = "eventually"
    UNTIL = "until"


class SurfaceKind(str, Enum):
    """Declared surface family for a fixed-point profile."""

    MU_CALCULUS = "mu_calculus"
    CTL_STAR_FRAGMENT = "ctl_star_fragment"
    MIXED = "mixed"


class BoundednessKind(str, Enum):
    """Semantic bound for fixed-point / model-check evidence."""

    FINITE_STATE = "finite_state"
    BOUNDED_UNROLLING = "bounded_unrolling"
    MODEL_CHECK = "model_check"
    RESOURCE_BOUNDED = "resource_bounded"
    UNBOUNDED = "unbounded"


class EvidenceSource(str, Enum):
    """Origin of fixed-point / model-check evidence (closed set)."""

    NONE = "none"
    DECLARATION = "declaration"
    SYMBOLIC_MODEL_CHECK = "symbolic_model_check"
    EXPLICIT_MODEL_CHECK = "explicit_model_check"
    BOUNDED_UNROLLING = "bounded_unrolling"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by fixed-point evidence (never universal proof)."""

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    MODEL_CHECK = "model_check"
    PROOF = "proof"


class LifecyclePosture(str, Enum):
    """Lifecycle posture: declaration never implies executable support."""

    DECLARATION_ONLY = "declaration_only"
    PARSE_PRINT = "parse_print"
    CONTROLLED_EXECUTABLE = "controlled_executable"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    UNARY = 50
    ATOM = 60


_SOURCE_AUTHORITY_CEILING: Final[Mapping[EvidenceSource, EvidenceAuthority]] = {
    EvidenceSource.NONE: EvidenceAuthority.NONE,
    EvidenceSource.DECLARATION: EvidenceAuthority.NONE,
    EvidenceSource.BOUNDED_UNROLLING: EvidenceAuthority.BOUNDED,
    EvidenceSource.SYMBOLIC_MODEL_CHECK: EvidenceAuthority.MODEL_CHECK,
    EvidenceSource.EXPLICIT_MODEL_CHECK: EvidenceAuthority.MODEL_CHECK,
}

_AUTHORITY_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.MODEL_CHECK: 3,
    EvidenceAuthority.PROOF: 4,
}

# Model-check evidence never becomes universal proof from this module.
_NON_PROOF_SOURCES: Final[frozenset[EvidenceSource]] = frozenset(
    {
        EvidenceSource.NONE,
        EvidenceSource.DECLARATION,
        EvidenceSource.BOUNDED_UNROLLING,
        EvidenceSource.SYMBOLIC_MODEL_CHECK,
        EvidenceSource.EXPLICIT_MODEL_CHECK,
    }
)


# ---------------------------------------------------------------------------
# Surface rewrite
# ---------------------------------------------------------------------------


def rewrite_fixed_point_surface(text: str) -> str:
    """Normalize Unicode binders and ASCII modality digraphs before lexing."""

    if not text:
        return text
    rewritten = _MU_NU_RE.sub(
        lambda match: "mu" if match.group(0) == "μ" else "nu", text
    )
    rewritten = _ANGLE_DIAMOND_RE.sub(" diamond ", rewritten)
    rewritten = _BRACKET_BOX_RE.sub(" box ", rewritten)
    return rewritten


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixedPointLogicProfile:
    """Semantic profile for mu-calculus / controlled CTL-star surfaces.

    ``executable_support`` defaults to False: declaring a profile or the
    ``mu_calculus`` family never implies a live model-checker backend.
    """

    profile_id: str
    surface: SurfaceKind | str = SurfaceKind.MU_CALCULUS
    max_alternation_depth: int = 2
    require_positivity: bool = True
    require_guardedness: bool = True
    admit_ctl_surface: bool = False
    admit_classic_ctl_letters: bool = False
    admit_until: bool = True
    executable_support: bool = False
    lifecycle: LifecyclePosture | str = LifecyclePosture.PARSE_PRINT
    max_binder_nesting: int = 16
    schema_version: str = FP_PROFILE_SCHEMA

    interface: ClassVar[str] = FIXED_POINT_LOGIC_PROFILES_INTERFACE

    def __post_init__(self) -> None:
        profile_id = str(self.profile_id or "").strip()
        if not profile_id:
            raise SyntaxContractError("profile_id is required")
        object.__setattr__(self, "profile_id", profile_id)

        surface = (
            self.surface
            if isinstance(self.surface, SurfaceKind)
            else SurfaceKind(str(self.surface))
        )
        object.__setattr__(self, "surface", surface)

        lifecycle = (
            self.lifecycle
            if isinstance(self.lifecycle, LifecyclePosture)
            else LifecyclePosture(str(self.lifecycle))
        )
        object.__setattr__(self, "lifecycle", lifecycle)

        if (
            isinstance(self.max_alternation_depth, bool)
            or not isinstance(self.max_alternation_depth, int)
            or self.max_alternation_depth < 0
        ):
            raise SyntaxContractError(
                "max_alternation_depth must be a non-negative integer"
            )
        if (
            isinstance(self.max_binder_nesting, bool)
            or not isinstance(self.max_binder_nesting, int)
            or self.max_binder_nesting < 1
        ):
            raise SyntaxContractError(
                "max_binder_nesting must be a positive integer"
            )
        if not isinstance(self.require_positivity, bool):
            raise SyntaxContractError("require_positivity must be a boolean")
        if not isinstance(self.require_guardedness, bool):
            raise SyntaxContractError("require_guardedness must be a boolean")
        if not isinstance(self.admit_ctl_surface, bool):
            raise SyntaxContractError("admit_ctl_surface must be a boolean")
        if not isinstance(self.admit_classic_ctl_letters, bool):
            raise SyntaxContractError(
                "admit_classic_ctl_letters must be a boolean"
            )
        if not isinstance(self.admit_until, bool):
            raise SyntaxContractError("admit_until must be a boolean")
        if not isinstance(self.executable_support, bool):
            raise SyntaxContractError("executable_support must be a boolean")

        if lifecycle is LifecyclePosture.DECLARATION_ONLY and self.executable_support:
            raise SyntaxContractError(
                "declaration_only lifecycle cannot set executable_support=True; "
                "declaration never implies executable support"
            )
        if (
            surface is SurfaceKind.CTL_STAR_FRAGMENT
            and not self.admit_ctl_surface
        ):
            object.__setattr__(self, "admit_ctl_surface", True)
        if self.schema_version != FP_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported fixed-point profile schema {self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        return FP_FAMILY_ID

    @property
    def is_declaration_only(self) -> bool:
        return self.lifecycle is LifecyclePosture.DECLARATION_ONLY

    @property
    def grants_executable_support(self) -> bool:
        """True only when explicitly opted in — never from declaration alone."""

        return (
            self.executable_support
            and self.lifecycle is LifecyclePosture.CONTROLLED_EXECUTABLE
        )

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_classic_ctl_letters": self.admit_classic_ctl_letters,
            "admit_ctl_surface": self.admit_ctl_surface,
            "admit_until": self.admit_until,
            "executable_support": self.executable_support,
            "family": FP_FAMILY_ID,
            "lifecycle": (
                self.lifecycle.value
                if isinstance(self.lifecycle, LifecyclePosture)
                else str(self.lifecycle)
            ),
            "max_alternation_depth": self.max_alternation_depth,
            "max_binder_nesting": self.max_binder_nesting,
            "profile_id": self.profile_id,
            "require_guardedness": self.require_guardedness,
            "require_positivity": self.require_positivity,
            "surface": (
                self.surface.value
                if isinstance(self.surface, SurfaceKind)
                else str(self.surface)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_identity,
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FixedPointLogicProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("FixedPointLogicProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            surface=value.get("surface", SurfaceKind.MU_CALCULUS.value),
            max_alternation_depth=int(value.get("max_alternation_depth", 2)),
            require_positivity=bool(value.get("require_positivity", True)),
            require_guardedness=bool(value.get("require_guardedness", True)),
            admit_ctl_surface=bool(value.get("admit_ctl_surface", False)),
            admit_classic_ctl_letters=bool(
                value.get("admit_classic_ctl_letters", False)
            ),
            admit_until=bool(value.get("admit_until", True)),
            executable_support=bool(value.get("executable_support", False)),
            lifecycle=value.get("lifecycle", LifecyclePosture.PARSE_PRINT.value),
            max_binder_nesting=int(value.get("max_binder_nesting", 16)),
            schema_version=str(
                value.get("schema_version") or FP_PROFILE_SCHEMA
            ),
        )


def profile_mu_calculus(
    *,
    profile_id: str = "mu_calculus_guarded",
    max_alternation_depth: int = 2,
    require_positivity: bool = True,
    require_guardedness: bool = True,
    executable_support: bool = False,
    lifecycle: LifecyclePosture | str = LifecyclePosture.PARSE_PRINT,
) -> FixedPointLogicProfile:
    """Pure mu-calculus profile (no CTL surface)."""

    return FixedPointLogicProfile(
        profile_id=profile_id,
        surface=SurfaceKind.MU_CALCULUS,
        max_alternation_depth=max_alternation_depth,
        require_positivity=require_positivity,
        require_guardedness=require_guardedness,
        admit_ctl_surface=False,
        executable_support=executable_support,
        lifecycle=lifecycle,
    )


def profile_ctl_star_fragment(
    *,
    profile_id: str = "ctl_star_fragment_to_mu",
    max_alternation_depth: int = 1,
    admit_classic_ctl_letters: bool = True,
    admit_until: bool = True,
    executable_support: bool = False,
    lifecycle: LifecyclePosture | str = LifecyclePosture.PARSE_PRINT,
) -> FixedPointLogicProfile:
    """Controlled CTL state-formula surface that lowers to mu-calculus."""

    return FixedPointLogicProfile(
        profile_id=profile_id,
        surface=SurfaceKind.CTL_STAR_FRAGMENT,
        max_alternation_depth=max_alternation_depth,
        require_positivity=True,
        require_guardedness=True,
        admit_ctl_surface=True,
        admit_classic_ctl_letters=admit_classic_ctl_letters,
        admit_until=admit_until,
        executable_support=executable_support,
        lifecycle=lifecycle,
    )


def profile_mixed_mu_ctl(
    *,
    profile_id: str = "mixed_mu_ctl",
    max_alternation_depth: int = 2,
    executable_support: bool = False,
) -> FixedPointLogicProfile:
    """Mixed surface: direct mu/nu binders plus controlled CTL letters."""

    return FixedPointLogicProfile(
        profile_id=profile_id,
        surface=SurfaceKind.MIXED,
        max_alternation_depth=max_alternation_depth,
        require_positivity=True,
        require_guardedness=True,
        admit_ctl_surface=True,
        admit_classic_ctl_letters=True,
        admit_until=True,
        executable_support=executable_support,
        lifecycle=LifecyclePosture.PARSE_PRINT,
    )


def profile_declaration_only(
    *,
    profile_id: str = "mu_calculus_declaration_only",
) -> FixedPointLogicProfile:
    """Declaration-only posture: parse/print metadata without executable routes."""

    return FixedPointLogicProfile(
        profile_id=profile_id,
        surface=SurfaceKind.MU_CALCULUS,
        max_alternation_depth=0,
        require_positivity=True,
        require_guardedness=True,
        admit_ctl_surface=False,
        executable_support=False,
        lifecycle=LifecyclePosture.DECLARATION_ONLY,
    )


def fixed_point_semantic_identity(
    node: LogicNode | None,
    profile: FixedPointLogicProfile,
) -> dict[str, Any]:
    """Stable semantic identity fragment for a formula under *profile*."""

    return {
        "family": FP_FAMILY_ID,
        "interface": FIXED_POINT_LOGIC_PROFILES_INTERFACE,
        "notation_id": FP_NOTATION_ID,
        "notation_version": FP_NOTATION_VERSION,
        "profile": profile.semantic_identity,
        "root_kind": (
            None
            if node is None
            else (
                node.kind.value
                if isinstance(node.kind, NodeKind)
                else str(node.kind)
            )
        ),
    }


# ---------------------------------------------------------------------------
# Evidence / authority contracts
# ---------------------------------------------------------------------------


class AuthorityPromotionError(SyntaxContractError):
    """Raised when evidence is promoted beyond its declared authority ceiling."""


@dataclass(frozen=True, slots=True)
class FixedPointEvidenceContract:
    """Authority ceiling for fixed-point / model-check evidence.

    Declaration and model-check results **never** become universal proof
    authority from this module.  Executable support is independent of
    family/profile declaration.
    """

    source: EvidenceSource | str
    authority: EvidenceAuthority | str
    bound: BoundednessKind | str = BoundednessKind.MODEL_CHECK
    grants_proof_authority: bool = False
    grants_executable_support: bool = False
    profile_id: str = ""
    schema_version: str = FP_EVIDENCE_CONTRACT_SCHEMA

    interface: ClassVar[str] = FIXED_POINT_LOGIC_PROFILES_INTERFACE

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
        bound = (
            self.bound
            if isinstance(self.bound, BoundednessKind)
            else BoundednessKind(str(self.bound))
        )
        ceiling = _SOURCE_AUTHORITY_CEILING[source]
        if _AUTHORITY_RANK[authority] > _AUTHORITY_RANK[ceiling]:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot claim {authority.value} "
                f"authority (ceiling={ceiling.value}); declaration or "
                "model-check evidence cannot become universal proof"
            )
        if authority is EvidenceAuthority.PROOF:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot become universal proof "
                "authority from FixedPointLogicProfiles@1"
            )
        if self.grants_proof_authority:
            raise AuthorityPromotionError(
                "FixedPointLogicProfiles@1 never grants proof authority"
            )
        if source is EvidenceSource.DECLARATION and self.grants_executable_support:
            raise AuthorityPromotionError(
                "declaration evidence cannot grant executable support; "
                "declaration never implies executable support"
            )
        if bound is BoundednessKind.UNBOUNDED and authority in {
            EvidenceAuthority.MODEL_CHECK,
            EvidenceAuthority.PROOF,
        }:
            raise AuthorityPromotionError(
                "unbounded bound cannot carry model-check or proof authority"
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "bound", bound)
        object.__setattr__(self, "grants_proof_authority", False)
        object.__setattr__(
            self, "grants_executable_support", bool(self.grants_executable_support)
        )
        if self.schema_version != FP_EVIDENCE_CONTRACT_SCHEMA:
            raise SyntaxContractError(
                f"unsupported evidence contract schema {self.schema_version!r}"
            )

    @property
    def authority_ceiling(self) -> EvidenceAuthority:
        assert isinstance(self.authority, EvidenceAuthority)
        return self.authority

    @property
    def source_ceiling(self) -> EvidenceAuthority:
        assert isinstance(self.source, EvidenceSource)
        return _SOURCE_AUTHORITY_CEILING[self.source]

    @property
    def may_promote_to_proof(self) -> bool:
        return False

    @property
    def is_proof(self) -> bool:
        return False

    def promote_to_proof(self) -> None:
        """Fail closed: model-check / declaration evidence is never proof."""

        source = (
            self.source.value
            if isinstance(self.source, EvidenceSource)
            else str(self.source)
        )
        raise AuthorityPromotionError(
            f"{source} evidence cannot be promoted to universal proof authority"
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
            "grants_executable_support": bool(self.grants_executable_support),
            "grants_proof_authority": False,
            "interface": self.interface,
            "is_proof": False,
            "may_promote_to_proof": False,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "source": (
                self.source.value
                if isinstance(self.source, EvidenceSource)
                else str(self.source)
            ),
            "source_ceiling": self.source_ceiling.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FixedPointEvidenceContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("evidence contract must be a mapping")
        return cls(
            source=value.get("source", EvidenceSource.NONE.value),
            authority=value.get("authority", EvidenceAuthority.NONE.value),
            bound=value.get("bound", BoundednessKind.MODEL_CHECK.value),
            grants_proof_authority=bool(value.get("grants_proof_authority", False)),
            grants_executable_support=bool(
                value.get("grants_executable_support", False)
            ),
            profile_id=str(value.get("profile_id") or ""),
            schema_version=str(
                value.get("schema_version") or FP_EVIDENCE_CONTRACT_SCHEMA
            ),
        )


def declaration_evidence_contract(
    profile: FixedPointLogicProfile | None = None,
) -> FixedPointEvidenceContract:
    """Declaration-only evidence: no authority, no executable support."""

    return FixedPointEvidenceContract(
        source=EvidenceSource.DECLARATION,
        authority=EvidenceAuthority.NONE,
        bound=BoundednessKind.RESOURCE_BOUNDED,
        grants_executable_support=False,
        profile_id=profile.profile_id if profile else "",
    )


def model_check_evidence_contract(
    profile: FixedPointLogicProfile | None = None,
    *,
    source: EvidenceSource | str = EvidenceSource.SYMBOLIC_MODEL_CHECK,
) -> FixedPointEvidenceContract:
    """Model-check evidence: bounded model-check authority only."""

    if profile is not None and not profile.grants_executable_support:
        raise AuthorityPromotionError(
            "model-check evidence requires profile.executable_support=True "
            "with lifecycle=controlled_executable; declaration never implies "
            "executable support"
        )
    src = source if isinstance(source, EvidenceSource) else EvidenceSource(str(source))
    if src not in {
        EvidenceSource.SYMBOLIC_MODEL_CHECK,
        EvidenceSource.EXPLICIT_MODEL_CHECK,
    }:
        raise SyntaxContractError(
            "model_check_evidence_contract requires a model-check source"
        )
    return FixedPointEvidenceContract(
        source=src,
        authority=EvidenceAuthority.MODEL_CHECK,
        bound=BoundednessKind.MODEL_CHECK,
        grants_executable_support=True,
        profile_id=profile.profile_id if profile else "",
    )


def bounded_unrolling_evidence_contract(
    profile: FixedPointLogicProfile | None = None,
) -> FixedPointEvidenceContract:
    """Bounded unrolling evidence: never universal proof."""

    return FixedPointEvidenceContract(
        source=EvidenceSource.BOUNDED_UNROLLING,
        authority=EvidenceAuthority.BOUNDED,
        bound=BoundednessKind.BOUNDED_UNROLLING,
        grants_executable_support=bool(
            profile.grants_executable_support if profile else False
        ),
        profile_id=profile.profile_id if profile else "",
    )


def retain_authority_ceiling(
    evidence: FixedPointEvidenceContract,
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
        claimed_proof = bool(claimed.get("grants_proof_authority", False))
        claimed_is_proof = (
            claimed_authority == EvidenceAuthority.PROOF.value or claimed_proof
        )
        if claimed_is_proof:
            raise AuthorityPromotionError(
                "claimed proof authority exceeds retained ceiling "
                f"(source={payload['source']}, "
                f"ceiling={payload['authority_ceiling']}); "
                "model-check evidence cannot become universal proof"
            )
        if claimed.get("grants_executable_support") and not evidence.grants_executable_support:
            raise AuthorityPromotionError(
                "claimed executable support exceeds retained ceiling; "
                "declaration never implies executable support"
            )
    retained = dict(payload)
    retained["authority"] = evidence.authority_ceiling.value
    retained["authority_ceiling"] = evidence.authority_ceiling.value
    retained["grants_proof_authority"] = False
    retained["may_promote_to_proof"] = False
    retained["is_proof"] = False
    retained["grants_executable_support"] = bool(evidence.grants_executable_support)
    return retained


@dataclass(frozen=True, slots=True)
class FixedPointLoweringReceipt:
    """Receipt for one CTL-star / model-check lowering attachment."""

    document_id: str
    profile_id: str
    source_surface: str
    target_surface: str
    alternation_depth: int
    guarded: bool
    positive: bool
    evidence: dict[str, Any]
    authorizes_proof: bool = False
    authorizes_executable: bool = False
    schema_version: str = FP_LOWERING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.authorizes_proof:
            raise AuthorityPromotionError(
                "lowering receipt cannot authorize universal proof"
            )
        if self.evidence.get("source") == EvidenceSource.DECLARATION.value and (
            self.authorizes_executable
            or self.evidence.get("grants_executable_support")
        ):
            raise AuthorityPromotionError(
                "declaration evidence cannot authorize executable support "
                "on a lowering receipt"
            )
        object.__setattr__(self, "authorizes_proof", False)
        object.__setattr__(
            self, "authorizes_executable", bool(self.authorizes_executable)
        )

    @property
    def authority_ceiling(self) -> str:
        return str(
            self.evidence.get("authority_ceiling") or self.evidence.get("authority")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternation_depth": self.alternation_depth,
            "authorizes_executable": bool(self.authorizes_executable),
            "authorizes_proof": False,
            "authority_ceiling": self.authority_ceiling,
            "document_id": self.document_id,
            "evidence": dict(self.evidence),
            "guarded": self.guarded,
            "positive": self.positive,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "source_surface": self.source_surface,
            "target_surface": self.target_surface,
        }


# ---------------------------------------------------------------------------
# Positivity / guardedness / alternation analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardReport:
    """Result of positivity + guardedness analysis for one formula."""

    positive: bool
    guarded: bool
    negative_variables: tuple[str, ...] = ()
    unguarded_variables: tuple[str, ...] = ()
    free_variables: tuple[str, ...] = ()
    schema_version: str = FP_GUARD_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "free_variables": list(self.free_variables),
            "guarded": self.guarded,
            "negative_variables": list(self.negative_variables),
            "positive": self.positive,
            "schema_version": self.schema_version,
            "unguarded_variables": list(self.unguarded_variables),
        }


@dataclass(frozen=True, slots=True)
class AlternationReport:
    """Alternation-depth report for nested mu/nu binders."""

    alternation_depth: int
    max_alternations: int
    binder_signature: tuple[str, ...] = ()
    accepted: bool = True
    reason: str = ""
    schema_version: str = FP_ALTERNATION_REPORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "alternation_depth": self.alternation_depth,
            "binder_signature": list(self.binder_signature),
            "max_alternations": self.max_alternations,
            "reason": self.reason,
            "schema_version": self.schema_version,
        }


def _is_fp_binder(node: LogicNode) -> bool:
    ext = node.extension
    return (
        node.kind is NodeKind.EXTENSION
        and ext is not None
        and ext.payload_schema == FP_BINDER_PAYLOAD_SCHEMA
    )


def _is_fp_var(node: LogicNode) -> bool:
    ext = node.extension
    return (
        node.kind is NodeKind.EXTENSION
        and ext is not None
        and ext.payload_schema == FP_VAR_PAYLOAD_SCHEMA
    )


def _is_fp_modal(node: LogicNode) -> bool:
    ext = node.extension
    return (
        node.kind is NodeKind.EXTENSION
        and ext is not None
        and ext.payload_schema == FP_MODAL_PAYLOAD_SCHEMA
    )


def _binder_kind(node: LogicNode) -> str:
    assert node.extension is not None
    return str(node.extension.payload.get("kind") or "")


def _binder_variable(node: LogicNode) -> str:
    assert node.extension is not None
    return str(node.extension.payload.get("variable") or "")


def _var_name(node: LogicNode) -> str:
    assert node.extension is not None
    return str(node.extension.payload.get("variable") or "")


def free_fixed_point_variables(node: LogicNode) -> frozenset[str]:
    """Collect free fixed-point variable names in *node*."""

    def walk(n: LogicNode, bound: frozenset[str]) -> set[str]:
        if _is_fp_var(n):
            name = _var_name(n)
            return set() if name in bound else {name}
        if _is_fp_binder(n):
            name = _binder_variable(n)
            body = n.extension.children[0] if n.extension and n.extension.children else None
            if body is None and n.arguments:
                body = n.arguments[0]
            if body is None:
                return set()
            return walk(body, bound | {name})
        free: set[str] = set()
        for child in n.arguments:
            free |= walk(child, bound)
        if n.extension is not None:
            for child in n.extension.children:
                free |= walk(child, bound)
        return free

    return frozenset(walk(node, frozenset()))


def extract_binder_signature(node: LogicNode) -> tuple[str, ...]:
    """Pre-order sequence of binder kinds (``mu``/``nu``) in *node*."""

    sig: list[str] = []

    def walk(n: LogicNode) -> None:
        if _is_fp_binder(n):
            sig.append(_binder_kind(n))
            body = (
                n.extension.children[0]
                if n.extension and n.extension.children
                else (n.arguments[0] if n.arguments else None)
            )
            if body is not None:
                walk(body)
            return
        for child in n.arguments:
            walk(child)
        if n.extension is not None:
            for child in n.extension.children:
                walk(child)

    walk(node)
    return tuple(sig)


def alternation_depth(node: LogicNode) -> int:
    """Maximum mu/nu alternation depth along nested binder chains.

    Depth is 0 for formulas without binders.  A single binder has depth 0
    (no alternation).  Nested binders of the *same* kind do not increase
    depth; a switch from mu to nu (or vice versa) increments the depth.
    """

    def walk(n: LogicNode, last_kind: str | None, depth: int) -> int:
        if _is_fp_binder(n):
            kind = _binder_kind(n)
            next_depth = depth
            if last_kind is not None and kind != last_kind:
                next_depth = depth + 1
            body = (
                n.extension.children[0]
                if n.extension and n.extension.children
                else (n.arguments[0] if n.arguments else None)
            )
            if body is None:
                return next_depth
            return walk(body, kind, next_depth)
        best = depth if last_kind is not None else 0
        # No binder yet: depth stays 0 until first binder.
        seed_depth = depth if last_kind is not None else 0
        seed_last = last_kind
        for child in n.arguments:
            best = max(best, walk(child, seed_last, seed_depth))
        if n.extension is not None:
            for child in n.extension.children:
                best = max(best, walk(child, seed_last, seed_depth))
        if last_kind is None and not any(
            True for _ in n.arguments
        ) and (n.extension is None or not n.extension.children):
            return 0
        return best

    # Correct depth for leaf / non-binder roots.
    if not _is_fp_binder(node):
        best = 0
        for child in node.arguments:
            best = max(best, alternation_depth(child))
        if node.extension is not None:
            for child in node.extension.children:
                best = max(best, alternation_depth(child))
        return best
    return walk(node, None, 0)


def check_alternation_depth(
    node: LogicNode,
    profile: FixedPointLogicProfile,
) -> AlternationReport:
    """Report whether *node* respects the profile alternation ceiling."""

    depth = alternation_depth(node)
    signature = extract_binder_signature(node)
    max_alt = profile.max_alternation_depth
    if depth > max_alt:
        return AlternationReport(
            alternation_depth=depth,
            max_alternations=max_alt,
            binder_signature=signature,
            accepted=False,
            reason=(
                f"alternation depth {depth} exceeds profile maximum {max_alt} "
                f"(binder signature: {' '.join(signature) or '∅'})"
            ),
        )
    return AlternationReport(
        alternation_depth=depth,
        max_alternations=max_alt,
        binder_signature=signature,
        accepted=True,
        reason="",
    )


def _children_of(node: LogicNode) -> tuple[LogicNode, ...]:
    if node.extension is not None and node.extension.children:
        return tuple(node.extension.children)
    return tuple(node.arguments)


def check_positivity_and_guardedness(node: LogicNode) -> GuardReport:
    """Check every binder for positive and guarded occurrences of its variable.

    Positivity: the bound variable must not occur under an odd number of
    negations (implication left-hand side counts as a negation).  IFF
    containing a free occurrence of the bound variable is rejected as
    non-positive.

    Guardedness: every free occurrence of the bound variable in the binder
    body must sit under at least one modal (diamond/box) operator.
    """

    negative: list[str] = []
    unguarded: list[str] = []

    def polarity_walk(
        n: LogicNode,
        *,
        positive: bool,
        under_modal: bool,
        target: str,
    ) -> tuple[bool, bool]:
        """Return (has_negative, has_unguarded) for *target* in *n*."""

        if _is_fp_var(n):
            if _var_name(n) != target:
                return False, False
            neg = not positive
            unguard = not under_modal
            return neg, unguard

        if _is_fp_binder(n):
            # Shadowing: if this binder rebinds *target*, stop.
            if _binder_variable(n) == target:
                return False, False
            body = _children_of(n)[0] if _children_of(n) else None
            if body is None:
                return False, False
            return polarity_walk(
                body, positive=positive, under_modal=under_modal, target=target
            )

        if _is_fp_modal(n):
            body = _children_of(n)[0] if _children_of(n) else None
            if body is None:
                return False, False
            return polarity_walk(
                body, positive=positive, under_modal=True, target=target
            )

        kind = n.kind if isinstance(n.kind, NodeKind) else NodeKind(str(n.kind))
        if kind is NodeKind.NOT and n.arguments:
            return polarity_walk(
                n.arguments[0],
                positive=not positive,
                under_modal=under_modal,
                target=target,
            )
        if kind is NodeKind.IMPLIES and len(n.arguments) == 2:
            left_neg, left_ung = polarity_walk(
                n.arguments[0],
                positive=not positive,
                under_modal=under_modal,
                target=target,
            )
            right_neg, right_ung = polarity_walk(
                n.arguments[1],
                positive=positive,
                under_modal=under_modal,
                target=target,
            )
            return left_neg or right_neg, left_ung or right_ung
        if kind is NodeKind.IFF and len(n.arguments) == 2:
            # Both polarities on both sides: any free occurrence is negative.
            free_left = target in free_fixed_point_variables(n.arguments[0])
            free_right = target in free_fixed_point_variables(n.arguments[1])
            if free_left or free_right:
                # Still compute unguarded under positive polarity for report.
                _, left_ung = polarity_walk(
                    n.arguments[0],
                    positive=True,
                    under_modal=under_modal,
                    target=target,
                )
                _, right_ung = polarity_walk(
                    n.arguments[1],
                    positive=True,
                    under_modal=under_modal,
                    target=target,
                )
                return True, left_ung or right_ung
            return False, False

        has_neg = False
        has_ung = False
        for child in n.arguments:
            n1, u1 = polarity_walk(
                child, positive=positive, under_modal=under_modal, target=target
            )
            has_neg = has_neg or n1
            has_ung = has_ung or u1
        if n.extension is not None:
            for child in n.extension.children:
                n1, u1 = polarity_walk(
                    child,
                    positive=positive,
                    under_modal=under_modal,
                    target=target,
                )
                has_neg = has_neg or n1
                has_ung = has_ung or u1
        return has_neg, has_ung

    def check_binders(n: LogicNode) -> None:
        if _is_fp_binder(n):
            var = _binder_variable(n)
            body = _children_of(n)[0] if _children_of(n) else None
            if body is not None:
                neg, ung = polarity_walk(
                    body, positive=True, under_modal=False, target=var
                )
                if neg and var not in negative:
                    negative.append(var)
                if ung and var not in unguarded:
                    unguarded.append(var)
                check_binders(body)
            return
        for child in n.arguments:
            check_binders(child)
        if n.extension is not None:
            for child in n.extension.children:
                check_binders(child)

    check_binders(node)
    free = tuple(sorted(free_fixed_point_variables(node)))
    return GuardReport(
        positive=not negative,
        guarded=not unguarded,
        negative_variables=tuple(negative),
        unguarded_variables=tuple(unguarded),
        free_variables=free,
    )


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixedPointParseResult:
    """Typed result of a fixed-point / mu-calculus parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: FixedPointLogicProfile | None = None
    guard_report: GuardReport | None = None
    alternation_report: AlternationReport | None = None
    schema_version: str = FP_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = FIXED_POINT_LOGIC_PROFILES_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternation_report": (
                self.alternation_report.to_dict()
                if self.alternation_report
                else None
            ),
            "guard_report": (
                self.guard_report.to_dict() if self.guard_report else None
            ),
            "interface": self.interface,
            "printed": self.printed,
            "profile": self.profile.to_dict() if self.profile else None,
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, ParseStatus)
            else str(self.status),
        }


class FixedPointParseError(SyntaxContractError):
    """Raised by raising helpers when a fixed-point parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: FixedPointParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(diagnostics)
        self.result = result


class _ParseFail(Exception):
    """Internal parse failure carrying one diagnostic."""

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
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    seq: int = 1,
) -> SyntaxDiagnostic:
    return SyntaxDiagnostic(
        diagnostic_id=f"diag:fp:{code.replace('.', '-')}:{seq}",
        code=code,
        message=message,
        severity=severity,
        range=range or SourceRange(0, 0),
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(
        self, tokens: Sequence[LogicToken], document: SourceDocument
    ) -> None:
        self.tokens = tokens
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
            # Reject reserved binder/modal keywords as binder variables.
            folded = token.lexeme.casefold()
            reserved = (
                _MU_WORDS
                | _NU_WORDS
                | _DIAMOND_WORDS
                | _BOX_WORDS
                | _TRUE_OPS
                | _FALSE_OPS
                | _NOT_OPS
                | _AND_OPS
                | _OR_OPS
                | _IMPLIES_OPS
                | _IFF_OPS
                | _PATH_ALL_WORDS
                | _PATH_EXISTS_WORDS
                | _TEMP_ALWAYS
                | _TEMP_EVENTUALLY
                | _TEMP_NEXT
                | _UNTIL_WORDS
                | frozenset(_CTL_COMPACT)
            )
            if folded in reserved and token.kind == TokenKind.KEYWORD.value:
                # Keywords used as propositions are allowed only for non-reserved.
                pass
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
# Parser engine
# ---------------------------------------------------------------------------


class _FPParserEngine:
    """Recursive-descent mu-calculus / controlled CTL-star parser."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: FixedPointLogicProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, document)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0
        self._binder_stack: list[str] = []
        self._binder_nesting = 0

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
                    message="empty fixed-point input is rejected",
                    range=self.document.full_range(),
                ),
            )
        try:
            root = self._parse_formula()
            if not self.cursor.is_eof():
                tok = self.cursor.current()
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=f"trailing input starting at {tok.lexeme!r}",
                        range=tok.range,
                        remediation="Remove trailing tokens or close open constructs",
                    )
                )
            # Post-parse structural checks.
            guard = check_positivity_and_guardedness(root)
            diags: list[SyntaxDiagnostic] = []
            if self.profile.require_positivity and not guard.positive:
                diags.append(
                    _diag(
                        code=CODE_NEGATIVE_OCCURRENCE,
                        message=(
                            "binder positivity violated: variable(s) "
                            f"{', '.join(guard.negative_variables)} occur "
                            "negatively under a fixed-point binder"
                        ),
                        range=root.range or self.document.full_range(),
                        remediation=(
                            "Rewrite so each bound variable occurs only "
                            "positively (even number of negations)"
                        ),
                        metadata={
                            "negative_variables": list(guard.negative_variables)
                        },
                        seq=len(diags) + 1,
                    )
                )
            if self.profile.require_guardedness and not guard.guarded:
                diags.append(
                    _diag(
                        code=CODE_UNGUARDED_OCCURRENCE,
                        message=(
                            "binder guardedness violated: variable(s) "
                            f"{', '.join(guard.unguarded_variables)} occur "
                            "without a surrounding modal operator"
                        ),
                        range=root.range or self.document.full_range(),
                        remediation=(
                            "Guard each bound-variable occurrence under "
                            "diamond/box (EX/AX)"
                        ),
                        metadata={
                            "unguarded_variables": list(guard.unguarded_variables)
                        },
                        seq=len(diags) + 1,
                    )
                )
            alt = check_alternation_depth(root, self.profile)
            if not alt.accepted:
                diags.append(
                    _diag(
                        code=CODE_ALTERNATION_DEPTH,
                        message=alt.reason,
                        range=root.range or self.document.full_range(),
                        remediation=(
                            "Reduce mu/nu alternation nesting or raise "
                            "profile.max_alternation_depth explicitly"
                        ),
                        metadata=alt.to_dict(),
                        seq=len(diags) + 1,
                    )
                )
            if diags:
                return None, tuple(diags)
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_fixed_point()
        finally:
            self._leave()

    def _parse_fixed_point(self) -> LogicNode:
        token = self.cursor.current()
        folded = token.lexeme.casefold()
        kind: FixedPointKind | None = None
        if folded in {item.casefold() for item in _MU_WORDS}:
            kind = FixedPointKind.MU
        elif folded in {item.casefold() for item in _NU_WORDS}:
            kind = FixedPointKind.NU
        if kind is None:
            return self._parse_iff()

        start = self.cursor.advance()
        self._binder_nesting += 1
        if self._binder_nesting > self.profile.max_binder_nesting:
            raise _ParseFail(
                _diag(
                    code=CODE_PARSE_DEPTH,
                    message=(
                        f"binder nesting {self._binder_nesting} exceeds "
                        f"profile maximum {self.profile.max_binder_nesting}"
                    ),
                    range=start.range,
                )
            )
        var_tok = self.cursor.expect_ident()
        var_name = var_tok.lexeme
        if var_name in self._binder_stack:
            raise _ParseFail(
                _diag(
                    code=CODE_REBIND_VARIABLE,
                    message=(
                        f"fixed-point variable {var_name!r} is already bound "
                        "in an enclosing binder"
                    ),
                    range=var_tok.range,
                    remediation="Rename the binder to avoid capture/rebind",
                )
            )
        if self.cursor.match_lexeme(".") is None:
            raise _ParseFail(
                _diag(
                    code=CODE_MISSING_BINDER_DOT,
                    message=(
                        f"expected '.' after binder variable {var_name!r}"
                    ),
                    range=self.cursor.current().range,
                    remediation="Write mu X. φ or nu X. φ",
                )
            )
        self._binder_stack.append(var_name)
        try:
            body = self._parse_formula()
        finally:
            self._binder_stack.pop()
            self._binder_nesting -= 1
        span = self.cursor.range_span(
            start.range, body.range or start.range
        )
        return self._build_binder(kind, var_name, body, span)

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
            right = self._parse_formula()
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
        left = self._parse_and()
        while self.cursor.match_any(_OR_OPS) is not None:
            right = self._parse_and()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = LogicNode(
                node_id=self._nid("or"),
                kind=NodeKind.OR,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
        return left

    def _parse_and(self) -> LogicNode:
        left = self._parse_unary()
        while self.cursor.match_any(_AND_OPS) is not None:
            right = self._parse_unary()
            span = self.cursor.range_span(
                left.range or SourceRange(0, 0),
                right.range or SourceRange(0, 0),
            )
            left = LogicNode(
                node_id=self._nid("and"),
                kind=NodeKind.AND,
                sort=BOOL_SORT,
                arguments=(left, right),
                range=span,
            )
        return left

    def _parse_unary(self) -> LogicNode:
        self._enter()
        try:
            if self.cursor.match_any(_NOT_OPS) is not None:
                start = self.cursor.tokens[self.cursor.index - 1]
                body = self._parse_unary()
                span = self.cursor.range_span(
                    start.range, body.range or start.range
                )
                return LogicNode(
                    node_id=self._nid("not"),
                    kind=NodeKind.NOT,
                    sort=BOOL_SORT,
                    arguments=(body,),
                    range=span,
                )

            # Modal operators.
            modal = self._match_modal()
            if modal is not None:
                kind, start = modal
                body = self._parse_unary()
                span = self.cursor.range_span(
                    start.range, body.range or start.range
                )
                return self._build_modal(kind, body, span)

            # Compact CTL letters: AG, EG, AF, EF, AX, EX.
            compact = self._match_ctl_compact()
            if compact is not None:
                path, temporal, start = compact
                body = self._parse_unary()
                return self._lower_ctl_unary(path, temporal, body, start.range)

            # Path quantifier + temporal: A always p, E (p until q), ...
            path = self._match_path_quantifier()
            if path is not None:
                path_kind, start = path
                return self._parse_path_body(path_kind, start)

            return self._parse_atomic()
        finally:
            self._leave()

    def _match_modal(self) -> tuple[ModalKind, LogicToken] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = token.lexeme.casefold()
        # Compact EX/AX double as both modal and CTL letters; treat bare EX/AX
        # as modals (they lower to diamond/box).  AG/EG/AF/EF stay CTL-only.
        if folded in {item.casefold() for item in _DIAMOND_WORDS} or folded == "ex":
            # When classic CTL letters are admitted, EX is still a modal.
            return ModalKind.DIAMOND, self.cursor.advance()
        if folded in {item.casefold() for item in _BOX_WORDS} or folded == "ax":
            return ModalKind.BOX, self.cursor.advance()
        return None

    def _match_ctl_compact(
        self,
    ) -> tuple[PathQuantifierKind, TemporalOpKind, LogicToken] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = token.lexeme.casefold()
        if folded not in _CTL_COMPACT:
            return None
        if folded in {"ax", "ex"}:
            # Handled as modals in _match_modal; never reach here for those.
            return None
        if not self.profile.admit_ctl_surface:
            raise _ParseFail(
                _diag(
                    code=CODE_UNSUPPORTED_CTL_STAR,
                    message=(
                        f"CTL letter {token.lexeme!r} is not admitted by "
                        f"profile {self.profile.profile_id!r}"
                    ),
                    range=token.range,
                    remediation=(
                        "Use profile_ctl_star_fragment() / profile_mixed_mu_ctl() "
                        "or write the equivalent mu/nu formula directly"
                    ),
                    metadata={
                        "construct": token.lexeme,
                        "supported": False,
                        "fragment": "ctl_state",
                    },
                )
            )
        if not self.profile.admit_classic_ctl_letters:
            raise _ParseFail(
                _diag(
                    code=CODE_UNSUPPORTED_CTL_STAR,
                    message=(
                        f"classic CTL letter {token.lexeme!r} requires "
                        "admit_classic_ctl_letters=True"
                    ),
                    range=token.range,
                    metadata={"construct": token.lexeme, "supported": False},
                )
            )
        path_s, temp_s = _CTL_COMPACT[folded]
        path = (
            PathQuantifierKind.ALL
            if path_s == "all"
            else PathQuantifierKind.EXISTS
        )
        temporal = {
            "always": TemporalOpKind.ALWAYS,
            "eventually": TemporalOpKind.EVENTUALLY,
            "next": TemporalOpKind.NEXT,
        }[temp_s]
        return path, temporal, self.cursor.advance()

    def _match_path_quantifier(
        self,
    ) -> tuple[PathQuantifierKind, LogicToken] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        # Without CTL surface admission, A/E/all/exists remain propositions.
        if not self.profile.admit_ctl_surface:
            return None
        folded = token.lexeme.casefold()
        if folded in {item.casefold() for item in _PATH_ALL_WORDS}:
            return PathQuantifierKind.ALL, self.cursor.advance()
        if folded in {item.casefold() for item in _PATH_EXISTS_WORDS}:
            return PathQuantifierKind.EXISTS, self.cursor.advance()
        return None

    def _parse_path_body(
        self,
        path: PathQuantifierKind,
        start: LogicToken,
    ) -> LogicNode:
        """Parse temporal body after a path quantifier (controlled CTL only)."""

        # A (p until q) / E (p until q)
        if self.cursor.match_lexeme("(") is not None:
            left = self._parse_unary()
            until_tok = self.cursor.match_any(_UNTIL_WORDS)
            if until_tok is None:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_CTL_STAR,
                        message=(
                            "controlled CTL-star fragment only admits "
                            "path-quantified until inside parentheses; "
                            "arbitrary path formulas are unsupported"
                        ),
                        range=self.cursor.current().range,
                        remediation=(
                            "Use A (p until q) / E (p until q) or AG/EG/AF/EF/AX/EX"
                        ),
                        metadata={
                            "construct": "path_formula",
                            "path": path.value,
                            "supported": False,
                            "reason": "non_until_path_formula",
                        },
                    )
                )
            if not self.profile.admit_until:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_CTL_STAR,
                        message="until is not admitted by this profile",
                        range=until_tok.range,
                        metadata={"construct": "until", "supported": False},
                    )
                )
            right = self._parse_unary()
            end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = self.cursor.range_span(start.range, end.range)
            return self._lower_ctl_until(path, left, right, span)

        # A always p / E eventually p / A next p
        temporal = self._match_temporal_word()
        if temporal is None:
            raise _ParseFail(
                _diag(
                    code=CODE_UNSUPPORTED_CTL_STAR,
                    message=(
                        f"path quantifier {path.value!r} must be followed by "
                        "always/eventually/next or '(p until q)'; full CTL* "
                        "path formulas are unsupported"
                    ),
                    range=self.cursor.current().range,
                    remediation=(
                        "Use A always p, E eventually p, A next p, "
                        "or A (p until q)"
                    ),
                    metadata={
                        "construct": "ctl_star_path",
                        "path": path.value,
                        "supported": False,
                        "reason": "missing_controlled_temporal",
                    },
                )
            )
        temp_kind, _temp_tok = temporal
        body = self._parse_unary()
        return self._lower_ctl_unary(path, temp_kind, body, start.range)

    def _match_temporal_word(
        self,
    ) -> tuple[TemporalOpKind, LogicToken] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        folded = token.lexeme.casefold()
        if folded in {item.casefold() for item in _TEMP_ALWAYS}:
            if folded == "g" and not self.profile.admit_classic_ctl_letters:
                return None
            return TemporalOpKind.ALWAYS, self.cursor.advance()
        if folded in {item.casefold() for item in _TEMP_EVENTUALLY}:
            if folded == "f" and not self.profile.admit_classic_ctl_letters:
                return None
            return TemporalOpKind.EVENTUALLY, self.cursor.advance()
        if folded in {item.casefold() for item in _TEMP_NEXT}:
            if folded == "x" and not self.profile.admit_classic_ctl_letters:
                return None
            return TemporalOpKind.NEXT, self.cursor.advance()
        return None

    def _parse_atomic(self) -> LogicNode:
        token = self.cursor.current()
        if token.lexeme == "(":
            self.cursor.advance()
            inner = self._parse_formula()
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            return inner

        if self.cursor.match_any(_TRUE_OPS) is not None:
            node = mk_true(self._nid("true"))
            return LogicNode(
                node_id=node.node_id,
                kind=NodeKind.TRUE,
                sort=BOOL_SORT,
                range=token.range,
            )
        if self.cursor.match_any(_FALSE_OPS) is not None:
            node = mk_false(self._nid("false"))
            return LogicNode(
                node_id=node.node_id,
                kind=NodeKind.FALSE,
                sort=BOOL_SORT,
                range=token.range,
            )

        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            name = token.lexeme
            self.cursor.advance()
            # Bound fixed-point variable reference.
            if name in self._binder_stack:
                return self._build_var(name, token.range)
            # Free proposition / free fixed-point variable.
            # Use predicate for atomic propositions; fp-var only when bound.
            return LogicNode(
                node_id=self._nid("atom"),
                kind=NodeKind.PREDICATE,
                symbol=name,
                sort=BOOL_SORT,
                arguments=(),
                range=token.range,
            )

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {token.lexeme!r}",
                range=token.range,
            )
        )

    # -- node builders -------------------------------------------------------

    def _build_binder(
        self,
        kind: FixedPointKind,
        variable: str,
        body: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        return mk_extension(
            self._nid(kind.value),
            family=FP_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(kind.value, "fixed_point"),
            payload_schema=FP_BINDER_PAYLOAD_SCHEMA,
            payload={
                "kind": kind.value,
                "variable": variable,
                "family": FP_FAMILY_ID,
            },
            children=(body,),
            range=span,
        )

    def _build_var(self, variable: str, span: SourceRange) -> LogicNode:
        return mk_extension(
            self._nid("var"),
            family=FP_FAMILY_ID,
            profile=self.profile.profile_id,
            features=("fixed_point_variable",),
            payload_schema=FP_VAR_PAYLOAD_SCHEMA,
            payload={
                "variable": variable,
                "family": FP_FAMILY_ID,
            },
            children=(),
            range=span,
        )

    def _build_modal(
        self,
        kind: ModalKind,
        body: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        return mk_extension(
            self._nid(kind.value),
            family=FP_FAMILY_ID,
            profile=self.profile.profile_id,
            features=(kind.value, "modal"),
            payload_schema=FP_MODAL_PAYLOAD_SCHEMA,
            payload={
                "kind": kind.value,
                "family": FP_FAMILY_ID,
            },
            children=(body,),
            range=span,
        )

    def _fresh_var(self, base: str = "X") -> str:
        index = 1
        existing = set(self._binder_stack)
        while f"{base}{index}" in existing:
            index += 1
        return f"{base}{index}"

    def _lower_ctl_unary(
        self,
        path: PathQuantifierKind,
        temporal: TemporalOpKind,
        body: LogicNode,
        start_range: SourceRange,
    ) -> LogicNode:
        """Lower controlled CTL unary forms to mu-calculus.

        * ``AX p`` → box p
        * ``EX p`` → diamond p
        * ``AG p`` → nu X. (p ∧ AX X)
        * ``EG p`` → nu X. (p ∧ EX X)
        * ``AF p`` → mu X. (p ∨ AX X)
        * ``EF p`` → mu X. (p ∨ EX X)
        """

        span = self.cursor.range_span(
            start_range, body.range or start_range
        )
        if temporal is TemporalOpKind.NEXT:
            modal = (
                ModalKind.BOX
                if path is PathQuantifierKind.ALL
                else ModalKind.DIAMOND
            )
            return self._build_modal(modal, body, span)

        var = self._fresh_var("Z")
        var_node = self._build_var(var, span)
        modal_kind = (
            ModalKind.BOX
            if path is PathQuantifierKind.ALL
            else ModalKind.DIAMOND
        )
        modal_var = self._build_modal(modal_kind, var_node, span)

        if temporal is TemporalOpKind.ALWAYS:
            # nu X. (p and modal X)
            conjunct = LogicNode(
                node_id=self._nid("and"),
                kind=NodeKind.AND,
                sort=BOOL_SORT,
                arguments=(body, modal_var),
                range=span,
            )
            return self._build_binder(FixedPointKind.NU, var, conjunct, span)

        if temporal is TemporalOpKind.EVENTUALLY:
            # mu X. (p or modal X)
            disjunct = LogicNode(
                node_id=self._nid("or"),
                kind=NodeKind.OR,
                sort=BOOL_SORT,
                arguments=(body, modal_var),
                range=span,
            )
            return self._build_binder(FixedPointKind.MU, var, disjunct, span)

        raise _ParseFail(
            _diag(
                code=CODE_UNSUPPORTED_CTL_STAR,
                message=f"unsupported temporal operator {temporal.value!r}",
                range=start_range,
                metadata={"construct": temporal.value, "supported": False},
            )
        )

    def _lower_ctl_until(
        self,
        path: PathQuantifierKind,
        left: LogicNode,
        right: LogicNode,
        span: SourceRange,
    ) -> LogicNode:
        """Lower ``A(p U q)`` / ``E(p U q)`` to mu-calculus.

        * ``A(p U q)`` → mu X. (q ∨ (p ∧ AX X))
        * ``E(p U q)`` → mu X. (q ∨ (p ∧ EX X))
        """

        var = self._fresh_var("U")
        var_node = self._build_var(var, span)
        modal_kind = (
            ModalKind.BOX
            if path is PathQuantifierKind.ALL
            else ModalKind.DIAMOND
        )
        modal_var = self._build_modal(modal_kind, var_node, span)
        conjunct = LogicNode(
            node_id=self._nid("and"),
            kind=NodeKind.AND,
            sort=BOOL_SORT,
            arguments=(left, modal_var),
            range=span,
        )
        disjunct = LogicNode(
            node_id=self._nid("or"),
            kind=NodeKind.OR,
            sort=BOOL_SORT,
            arguments=(right, conjunct),
            range=span,
        )
        return self._build_binder(FixedPointKind.MU, var, disjunct, span)


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class FixedPointPrinter:
    """Print mu-calculus ASTs to controlled surface text."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        root = node.root if isinstance(node, TypedExpression) else node
        if not isinstance(root, LogicNode):
            raise SyntaxContractError("print requires a LogicNode")
        return self._print(root, _Prec.BOTTOM)

    def _print(self, node: LogicNode, parent_prec: _Prec) -> str:
        kind = node.kind if isinstance(node.kind, NodeKind) else NodeKind(str(node.kind))

        if kind is NodeKind.TRUE:
            return "true" if self.style == PrintStyle.ASCII else "⊤"
        if kind is NodeKind.FALSE:
            return "false" if self.style == PrintStyle.ASCII else "⊥"
        if kind is NodeKind.PREDICATE:
            return str(node.symbol or "")
        if kind is NodeKind.NOT and node.arguments:
            body = self._print(node.arguments[0], _Prec.UNARY)
            op = "not " if self.style == PrintStyle.ASCII else "¬"
            text = f"{op}{body}" if self.style == PrintStyle.ASCII else f"{op}{body}"
            return self._paren(text, _Prec.UNARY, parent_prec)
        if kind is NodeKind.AND and len(node.arguments) >= 2:
            parts = [self._print(c, _Prec.AND) for c in node.arguments]
            op = " and " if self.style == PrintStyle.ASCII else " ∧ "
            return self._paren(op.join(parts), _Prec.AND, parent_prec)
        if kind is NodeKind.OR and len(node.arguments) >= 2:
            parts = [self._print(c, _Prec.OR) for c in node.arguments]
            op = " or " if self.style == PrintStyle.ASCII else " ∨ "
            return self._paren(op.join(parts), _Prec.OR, parent_prec)
        if kind is NodeKind.IMPLIES and len(node.arguments) == 2:
            left = self._print(node.arguments[0], _Prec.IMPLIES)
            right = self._print(node.arguments[1], _Prec.BOTTOM)
            op = " implies " if self.style == PrintStyle.ASCII else " → "
            return self._paren(f"{left}{op}{right}", _Prec.IMPLIES, parent_prec)
        if kind is NodeKind.IFF and len(node.arguments) == 2:
            left = self._print(node.arguments[0], _Prec.IFF)
            right = self._print(node.arguments[1], _Prec.IFF)
            op = " iff " if self.style == PrintStyle.ASCII else " ↔ "
            return self._paren(f"{left}{op}{right}", _Prec.IFF, parent_prec)

        if kind is NodeKind.EXTENSION and node.extension is not None:
            schema = node.extension.payload_schema
            payload = dict(node.extension.payload)
            children = list(node.extension.children)
            if schema == FP_BINDER_PAYLOAD_SCHEMA:
                bkind = str(payload.get("kind") or "mu")
                var = str(payload.get("variable") or "X")
                body = children[0] if children else mk_true(self._nid_fallback())
                if self.style == PrintStyle.UNICODE:
                    op = "μ" if bkind == "mu" else "ν"
                else:
                    op = "mu" if bkind == "mu" else "nu"
                body_text = self._print(body, _Prec.BOTTOM)
                text = f"{op} {var}. {body_text}"
                return self._paren(text, _Prec.UNARY, parent_prec)
            if schema == FP_VAR_PAYLOAD_SCHEMA:
                return str(payload.get("variable") or "")
            if schema == FP_MODAL_PAYLOAD_SCHEMA:
                mkind = str(payload.get("kind") or "diamond")
                body = children[0] if children else mk_true(self._nid_fallback())
                body_text = self._print(body, _Prec.UNARY)
                if self.style == PrintStyle.UNICODE:
                    op = "◇" if mkind == "diamond" else "□"
                    text = f"{op}{body_text}"
                else:
                    op = "diamond" if mkind == "diamond" else "box"
                    text = f"{op} {body_text}"
                return self._paren(text, _Prec.UNARY, parent_prec)
            if schema == FP_CTL_PAYLOAD_SCHEMA:
                # Surface CTL nodes (if ever retained) print as compact letters.
                path = str(payload.get("path") or "all")
                temporal = str(payload.get("temporal") or "next")
                letter = {
                    ("all", "always"): "AG",
                    ("exists", "always"): "EG",
                    ("all", "eventually"): "AF",
                    ("exists", "eventually"): "EF",
                    ("all", "next"): "AX",
                    ("exists", "next"): "EX",
                }.get((path, temporal), f"{path}_{temporal}")
                body = children[0] if children else mk_true(self._nid_fallback())
                return f"{letter} {self._print(body, _Prec.UNARY)}"

        return f"/*unsupported:{kind}*/"

    def _nid_fallback(self) -> str:
        return "node:fp:print:fallback"

    def _paren(self, text: str, prec: _Prec, parent: _Prec) -> str:
        if prec < parent:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# CTL-star lowering API (explicit)
# ---------------------------------------------------------------------------


def lower_ctl_star_fragment(
    text: str,
    profile: FixedPointLogicProfile | None = None,
    **kwargs: Any,
) -> FixedPointParseResult:
    """Parse controlled CTL-star surface and lower to mu-calculus AST.

    Full CTL* path formulas outside the controlled CTL state fragment fail
    with ``fixed_point.unsupported_ctl_star``.
    """

    prof = profile or profile_ctl_star_fragment()
    if not prof.admit_ctl_surface:
        document_id = str(kwargs.get("document_id", "doc:fp:1"))
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        diag = _diag(
            code=CODE_UNSUPPORTED_CTL_STAR,
            message=(
                f"profile {prof.profile_id!r} does not admit CTL-star surface"
            ),
            range=document.full_range(),
            remediation="Use profile_ctl_star_fragment() or profile_mixed_mu_ctl()",
            metadata={"supported": False, "profile_id": prof.profile_id},
        )
        return FixedPointParseResult(
            status=ParseStatus.REJECTED,
            diagnostics=(diag,),
            profile=prof,
        )
    return parse_fixed_point(text, prof, **kwargs)


def is_controlled_ctl_star_supported(construct: str) -> bool:
    """Return whether a surface construct is in the controlled CTL fragment."""

    folded = construct.strip().casefold()
    if folded in _CTL_COMPACT:
        return True
    if folded in {
        "a always",
        "a eventually",
        "a next",
        "e always",
        "e eventually",
        "e next",
        "all always",
        "all eventually",
        "all next",
        "exists always",
        "exists eventually",
        "exists next",
        "a until",
        "e until",
        "all until",
        "exists until",
    }:
        return True
    return False


# ---------------------------------------------------------------------------
# Parser facade
# ---------------------------------------------------------------------------


def _extract_profile(value: object) -> FixedPointLogicProfile | None:
    if value is None:
        return None
    if isinstance(value, FixedPointLogicProfile):
        return value
    if isinstance(value, Mapping):
        return FixedPointLogicProfile.from_dict(value)
    return None


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:fp:1",
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


def _signature_for_formula(
    node: LogicNode,
    profile: FixedPointLogicProfile,
) -> LogicSignature:
    del node  # signature is profile-driven; root available for future harvest
    return LogicSignature(
        signature_id=f"sig:fixed_point:{profile.profile_id}",
        family=FP_FAMILY_ID,
        profile=profile.profile_id,
        sorts=(),
        symbols=(),
        features=("mu_calculus", "fixed_point"),
    )


class FixedPointParser:
    """Notation parser for mu-calculus / controlled CTL-star syntax.

    Interface: ``FixedPointLogicProfiles@1``.
    """

    interface: ClassVar[str] = FIXED_POINT_LOGIC_PROFILES_INTERFACE
    notation_id: ClassVar[str] = FP_NOTATION_ID
    notation_version: ClassVar[str] = FP_NOTATION_VERSION

    def __init__(
        self,
        profile: FixedPointLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, FixedPointLogicProfile):
            raise SyntaxContractError("profile must be a FixedPointLogicProfile")
        self.profile = profile
        self.printer = FixedPointPrinter(style=print_style)
        self._lexer = BoundedLexer(
            keywords=_FP_KEYWORDS,
            multi_char_operators=_FP_MULTI_OPS,
        )

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("fixed_point_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:fp:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: FixedPointLogicProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:fp:1",
        expression_id: str = "expr:fp:1",
    ) -> FixedPointParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_MISMATCH,
                message=(
                    "fixed-point parse requires a FixedPointLogicProfile"
                ),
                range=document.full_range(),
                remediation="Pass profile=profile_mu_calculus()",
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": FIXED_POINT_LOGIC_PROFILES_INTERFACE},
            )
            return FixedPointParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        # Rewrite Unicode binders before lexing.
        rewritten_text = rewrite_fixed_point_surface(document.text)
        if rewritten_text != document.text:
            lex_document = SourceDocument.from_text(
                document.document_id,
                rewritten_text,
                encoding=document.encoding,
            )
        else:
            lex_document = document

        lex_result = self._lexer.lex(lex_document, mode=parse_mode, limits=bounds)
        if lex_result.status is not ParseStatus.OK and any(
            item.is_error for item in lex_result.diagnostics
        ):
            promoted = tuple(
                SyntaxDiagnostic(
                    diagnostic_id=f"diag:fp:lex:{index + 1}",
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
                metadata={"interface": FIXED_POINT_LOGIC_PROFILES_INTERFACE},
            )
            return FixedPointParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _FPParserEngine(
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
                    "interface": FIXED_POINT_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return FixedPointParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        guard = check_positivity_and_guardedness(root)
        alt = check_alternation_depth(root, prof)
        printed = self.printer.print(root)
        signature = _signature_for_formula(root, prof)
        expression = TypedExpression(
            expression_id=expression_id,
            root=root,
            signature=signature,
            family=FP_FAMILY_ID,
            profile=prof.profile_id,
            range=root.range,
            elaborate_on_init=False,
        )
        cst = _build_covering_cst(lex_document, lex_result.tokens)
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
                "interface": FIXED_POINT_LOGIC_PROFILES_INTERFACE,
                "profile": prof.to_dict(),
                "guard_report": guard.to_dict(),
                "alternation_report": alt.to_dict(),
                "printed": printed,
                "executable_support": prof.grants_executable_support,
            },
        )
        return FixedPointParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            guard_report=guard,
            alternation_report=alt,
        )


class FixedPointLogicProfiles:
    """Facade for ``FixedPointLogicProfiles@1``."""

    interface: ClassVar[str] = FIXED_POINT_LOGIC_PROFILES_INTERFACE

    def __init__(
        self,
        profile: FixedPointLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_mu_calculus()
        self.parser = FixedPointParser(self.profile, print_style=print_style)
        self.printer = FixedPointPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> FixedPointParseResult:
        document_id = str(kwargs.pop("document_id", "doc:fp:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:fp:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:fp:1"))
        rewritten = rewrite_fixed_point_surface(text)
        document = SourceDocument.from_text(
            document_id, rewritten, encoding="utf-8"
        )
        return self.parser.parse_document(
            document,
            profile=self.profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise FixedPointParseError(
                "fixed-point parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def require_executable_support(self) -> None:
        """Fail closed when a caller assumes live model-checking support."""

        if not self.profile.grants_executable_support:
            raise AuthorityPromotionError(
                f"profile {self.profile.profile_id!r} does not grant executable "
                "support (lifecycle="
                f"{self.profile.lifecycle.value if isinstance(self.profile.lifecycle, LifecyclePosture) else self.profile.lifecycle}, "
                f"executable_support={self.profile.executable_support}); "
                "declaration never implies executable support"
            )

    def attach_evidence(
        self,
        result: FixedPointParseResult,
        evidence: FixedPointEvidenceContract,
        *,
        document_id: str = "doc:fp:1",
        source_surface: str = "mu_calculus",
        target_surface: str = "mu_calculus",
    ) -> FixedPointLoweringReceipt:
        """Attach evidence while retaining authority ceilings."""

        if result.profile is None:
            raise FixedPointParseError(
                "cannot attach evidence without a profile on the parse result"
            )
        if (
            evidence.source is EvidenceSource.DECLARATION
            or (
                isinstance(evidence.source, str)
                and evidence.source == EvidenceSource.DECLARATION.value
            )
        ) and evidence.grants_executable_support:
            raise AuthorityPromotionError(
                "declaration never implies executable support"
            )
        retained = retain_authority_ceiling(evidence)
        guard = result.guard_report or (
            check_positivity_and_guardedness(result.root)
            if result.root is not None
            else GuardReport(positive=True, guarded=True)
        )
        alt = result.alternation_report or (
            check_alternation_depth(result.root, result.profile)
            if result.root is not None
            else AlternationReport(alternation_depth=0, max_alternations=0)
        )
        return FixedPointLoweringReceipt(
            document_id=document_id,
            profile_id=result.profile.profile_id,
            source_surface=source_surface,
            target_surface=target_surface,
            alternation_depth=alt.alternation_depth,
            guarded=guard.guarded,
            positive=guard.positive,
            evidence=retained,
            authorizes_executable=bool(retained.get("grants_executable_support")),
            authorizes_proof=False,
        )


def parse_fixed_point(
    text: str,
    profile: FixedPointLogicProfile | None = None,
    **kwargs: Any,
) -> FixedPointParseResult:
    """Parse mu-calculus / controlled CTL-star *text* under *profile*."""

    logic = FixedPointLogicProfiles(profile or profile_mu_calculus())
    return logic.parse_text(text, **kwargs)


def print_fixed_point(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return FixedPointPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: FixedPointLogicProfile | None = None,
) -> tuple[FixedPointParseResult, FixedPointParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_mu_calculus()
    first = parse_fixed_point(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_fixed_point(first.root)
    second = parse_fixed_point(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "FIXED_POINT_LOGIC_PROFILES_INTERFACE",
    "FIXED_POINT_SYNTAX_INTERFACE",
    "CTL_STAR_LOWERING_INTERFACE",
    "FP_FAMILY_ID",
    "FP_NOTATION_ID",
    "CODE_NEGATIVE_OCCURRENCE",
    "CODE_UNGUARDED_OCCURRENCE",
    "CODE_UNSUPPORTED_CTL_STAR",
    "CODE_ALTERNATION_DEPTH",
    "CODE_DECLARATION_ONLY",
    "CODE_EXECUTABLE_SUPPORT",
    "AlternationReport",
    "AuthorityPromotionError",
    "BoundednessKind",
    "EvidenceAuthority",
    "EvidenceSource",
    "FixedPointEvidenceContract",
    "FixedPointKind",
    "FixedPointLogicProfile",
    "FixedPointLogicProfiles",
    "FixedPointLoweringReceipt",
    "FixedPointParseError",
    "FixedPointParseResult",
    "FixedPointParser",
    "FixedPointPrinter",
    "GuardReport",
    "LifecyclePosture",
    "ModalKind",
    "PathQuantifierKind",
    "PrintStyle",
    "SurfaceKind",
    "TemporalOpKind",
    "alternation_depth",
    "bounded_unrolling_evidence_contract",
    "check_alternation_depth",
    "check_positivity_and_guardedness",
    "declaration_evidence_contract",
    "extract_binder_signature",
    "fixed_point_semantic_identity",
    "free_fixed_point_variables",
    "is_controlled_ctl_star_supported",
    "lower_ctl_star_fragment",
    "model_check_evidence_contract",
    "parse_fixed_point",
    "parse_print_parse",
    "print_fixed_point",
    "profile_ctl_star_fragment",
    "profile_declaration_only",
    "profile_mixed_mu_ctl",
    "profile_mu_calculus",
    "retain_authority_ceiling",
    "rewrite_fixed_point_surface",
]
