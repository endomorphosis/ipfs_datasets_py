"""Modal, normative, epistemic, doxastic, and intention syntax profiles.

Interfaces:

* ``ModalSyntax@1`` — parse/print/elaborate for controlled modal text
* ``NormativeProfile@1`` — monadic deontic O/P/F choices (dyadic/defeasible fail closed)
* ``CognitiveProfile@1`` — epistemic / doxastic / intention-agency agent modalities

Surface semantics are never inferred from spelling alone.  Overloaded symbols
(``O``/``P``/``F``, box/diamond, ``K``/``B``/``I``) require a declared profile;
profile-free uses fail closed.  Unsupported dyadic norms and defeasible
constructs emit typed diagnostics and never lower to classical equivalence.
Parse/print preserves binding structure and source maps; parse/print/parse is
alpha-equivalent.

Grammar (connective precedence, low → high binding strength)::

    formula         ::= iff_formula
    iff_formula     ::= implies_formula (('iff'|↔) implies_formula)*
    implies_formula ::= or_formula (('implies'|→|=>|->) formula)?   # right-assoc
    or_formula      ::= and_formula (('or'|∨) and_formula)*
    and_formula     ::= unary (('and'|∧) unary)*
    unary           ::= modal_op agent_index? unary
                      | ('not'|¬) unary
                      | atomic
    modal_op        ::= box|diamond|necessary|possible|□|◇|[]|<>
                      | obligated|permitted|forbidden|obligation|permission|prohibition
                      | knows|believes|intends|intends_to
                      | O|P|F|K|B|I   # classic letters, profile-gated
    agent_index     ::= '[' IDENT ']'
    atomic          ::= 'true'|⊤ | 'false'|⊥ | IDENT | '(' formula ')'

Dyadic forms such as ``O(p | q)`` / ``obligated(p / q)`` and defeasible
keywords (``normally``, ``unless``, ``typically``, …) always fail closed with
stable codes; they cannot masquerade as classical ``iff``/``and``/``or``.
"""

from __future__ import annotations

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
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    LogicSignature,
    propositional_signature,
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

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

MODAL_SYNTAX_INTERFACE: Final = "ModalSyntax@1"
NORMATIVE_PROFILE_INTERFACE: Final = "NormativeProfile@1"
COGNITIVE_PROFILE_INTERFACE: Final = "CognitiveProfile@1"
MODAL_SEMANTICS_PROFILE_INTERFACE: Final = "ModalSemanticsProfile@1"
MODAL_NOTATION_ID: Final = "canonical_modal"
MODAL_NOTATION_VERSION: Final = "1.0.0"
MODAL_FAMILY_ID: Final = "modal"
DEONTIC_FAMILY_ID: Final = "deontic"
EPISTEMIC_FAMILY_ID: Final = "epistemic"
DOXASTIC_FAMILY_ID: Final = "doxastic"
INTENTION_FAMILY_ID: Final = "intention_agency"
MODAL_MODULE_VERSION: Final = "1.0.0"
MODAL_PARSE_RESULT_SCHEMA_VERSION: Final = "canonical-modal-parse-result/v1"
MODAL_SEMANTICS_PROFILE_SCHEMA_VERSION: Final = "modal-semantics-profile/v1"
NORMATIVE_PROFILE_SCHEMA_VERSION: Final = "normative-profile/v1"
COGNITIVE_PROFILE_SCHEMA_VERSION: Final = "cognitive-profile/v1"
MODAL_OPERATOR_PAYLOAD_SCHEMA: Final = "modal.operator/v1"

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "modal.unexpected_token"
CODE_TRAILING_INPUT: Final = "modal.trailing_input"
CODE_EMPTY_INPUT: Final = "modal.empty_input"
CODE_PARSE_DEPTH: Final = "modal.parse_depth_exceeded"
CODE_UNBALANCED: Final = "modal.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "modal.lexer_error"
CODE_PROFILE_REQUIRED: Final = "modal.profile_required"
CODE_PROFILE_MISMATCH: Final = "modal.profile_mismatch"
CODE_OVERLOADED_SYMBOL: Final = "modal.overloaded_symbol"
CODE_OPERATOR_FORBIDDEN: Final = "modal.operator_forbidden"
CODE_AGENT_REQUIRED: Final = "modal.agent_required"
CODE_AGENT_FORBIDDEN: Final = "modal.agent_forbidden"
CODE_UNSUPPORTED_DYADIC: Final = "modal.unsupported_dyadic"
CODE_UNSUPPORTED_DEFEASIBLE: Final = "modal.unsupported_defeasible"
CODE_ROUND_TRIP: Final = "modal.round_trip_failed"
CODE_MISSING_AGENT: Final = "modal.missing_agent"

_ALL_MODAL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNEXPECTED_TOKEN,
        CODE_TRAILING_INPUT,
        CODE_EMPTY_INPUT,
        CODE_PARSE_DEPTH,
        CODE_UNBALANCED,
        CODE_LEXER_ERROR,
        CODE_PROFILE_REQUIRED,
        CODE_PROFILE_MISMATCH,
        CODE_OVERLOADED_SYMBOL,
        CODE_OPERATOR_FORBIDDEN,
        CODE_AGENT_REQUIRED,
        CODE_AGENT_FORBIDDEN,
        CODE_UNSUPPORTED_DYADIC,
        CODE_UNSUPPORTED_DEFEASIBLE,
        CODE_ROUND_TRIP,
        CODE_MISSING_AGENT,
    }
)

# Operator lexeme sets.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "|", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})

# Alethic (Kripke) operators.
_BOX_WORDS: Final[frozenset[str]] = frozenset(
    {"box", "necessary", "nec", "□"}
)
_DIAMOND_WORDS: Final[frozenset[str]] = frozenset(
    {"diamond", "possible", "poss", "◇", "◊"}
)

# Deontic monadic operators (multi-letter always admitted under deontic profile).
_OBLIGATION_WORDS: Final[frozenset[str]] = frozenset(
    {"obligated", "obligation", "ought", "must"}
)
_PERMISSION_WORDS: Final[frozenset[str]] = frozenset(
    {"permitted", "permission", "may"}
)
_FORBIDDEN_WORDS: Final[frozenset[str]] = frozenset(
    {"forbidden", "prohibition", "prohibited", "forbid"}
)

# Cognitive multi-letter operators.
_KNOWS_WORDS: Final[frozenset[str]] = frozenset({"knows", "know"})
_BELIEVES_WORDS: Final[frozenset[str]] = frozenset({"believes", "believe"})
_INTENDS_WORDS: Final[frozenset[str]] = frozenset(
    {"intends", "intend", "intends_to", "intention"}
)

# Classic single-letter overloaded forms (require profile admission).
_CLASSIC_DEONTIC_LETTERS: Final[frozenset[str]] = frozenset({"O", "P", "F"})
_CLASSIC_COGNITIVE_LETTERS: Final[frozenset[str]] = frozenset({"K", "B", "I"})
_CLASSIC_ALETHIC_BRACKETS: Final[frozenset[str]] = frozenset({"[]", "<>"})

# Defeasible / nonmonotonic surface keywords (always fail closed here).
_DEFEASIBLE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "normally",
        "unless",
        "typically",
        "by_default",
        "defeasibly",
        "defeasible",
        "exception",
        "exceptions",
        "priority",
        "priorities",
        "contrary_to_duty",
        "ctd",
        "override",
        "overrides",
    }
)

# Dyadic separators inside monadic operator parentheses.
_DYADIC_SEPARATORS: Final[frozenset[str]] = frozenset({"|", "/", "//", "given", "if"})

# Canonical operator names after normalizing surface synonyms.
_ALETHIC_CANON: Final[Mapping[str, str]] = {
    "box": "box",
    "necessary": "box",
    "nec": "box",
    "□": "box",
    "[]": "box",
    "diamond": "diamond",
    "possible": "diamond",
    "poss": "diamond",
    "◇": "diamond",
    "◊": "diamond",
    "<>": "diamond",
}
_DEONTIC_CANON: Final[Mapping[str, str]] = {
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
_COGNITIVE_CANON: Final[Mapping[str, str]] = {
    "k": "knows",
    "knows": "knows",
    "know": "knows",
    "b": "believes",
    "believes": "believes",
    "believe": "believes",
    "i": "intends",
    "intends": "intends",
    "intend": "intends",
    "intends_to": "intends",
    "intention": "intends",
}

_ALL_MODAL_UNARY: Final[frozenset[str]] = frozenset(
    {
        "box",
        "diamond",
        "obligation",
        "permission",
        "forbidden",
        "knows",
        "believes",
        "intends",
    }
)

_MODAL_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "box",
    "diamond",
    "necessary",
    "possible",
    "nec",
    "poss",
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
    "knows",
    "know",
    "believes",
    "believe",
    "intends",
    "intend",
    "intends_to",
    "intention",
    "given",
    "if",
    "then",
    # Defeasible keywords registered so they tokenize as keywords (stable diags).
    "normally",
    "unless",
    "typically",
    "by_default",
    "defeasibly",
    "defeasible",
    "exception",
    "exceptions",
    "priority",
    "priorities",
    "contrary_to_duty",
    "ctd",
    "override",
    "overrides",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class ModalFamilyKind(str, Enum):
    """Declared modal family / profile fragment."""

    KRIPKE = "kripke"
    DEONTIC = "deontic"
    EPISTEMIC = "epistemic"
    DOXASTIC = "doxastic"
    INTENTION = "intention_agency"


class KripkeFrameKind(str, Enum):
    """Named Kripke frame constraint packages (K/D/T/S4/S5)."""

    K = "k"
    D = "d"
    T = "t"
    S4 = "s4"
    S5 = "s5"


class NormFormKind(str, Enum):
    """Norm representation shape admitted by a normative profile."""

    MONADIC = "monadic"
    # Dyadic is declared only so profiles can document rejection; parsing
    # of dyadic surface forms always fails closed under this frontend.
    DYADIC = "dyadic"


class PermissionStrengthKind(str, Enum):
    """Permission polarity for deontic norms."""

    STRONG = "strong"
    WEAK = "weak"


class CognitiveAttitudeKind(str, Enum):
    """Cognitive / BDI attitude class."""

    EPISTEMIC = "epistemic"
    DOXASTIC = "doxastic"
    INTENTION = "intention_agency"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
    UNARY = 60
    ATOM = 70


_FRAME_PROPERTIES: Final[Mapping[KripkeFrameKind, Mapping[str, bool]]] = {
    KripkeFrameKind.K: {
        "serial": False,
        "reflexive": False,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    KripkeFrameKind.D: {
        "serial": True,
        "reflexive": False,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    KripkeFrameKind.T: {
        "serial": True,
        "reflexive": True,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    KripkeFrameKind.S4: {
        "serial": True,
        "reflexive": True,
        "transitive": True,
        "euclidean": False,
        "symmetric": False,
    },
    KripkeFrameKind.S5: {
        "serial": True,
        "reflexive": True,
        "transitive": True,
        "euclidean": True,
        "symmetric": True,
    },
}


# ---------------------------------------------------------------------------
# NormativeProfile@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormativeProfile:
    """Explicit monadic deontic profile (``NormativeProfile@1``).

    Dyadic norms, priorities, exceptions, and contrary-to-duty constructs are
    **not** admitted by this frontend.  Profiles may declare those flags only
    as ``False``; any attempt to enable them or parse dyadic/defeasible surface
    forms fails closed with typed diagnostics.
    """

    profile_id: str
    form: NormFormKind | str = NormFormKind.MONADIC
    permission: PermissionStrengthKind | str = PermissionStrengthKind.STRONG
    admit_classic_letters: bool = False
    allow_dyadic: bool = False
    allow_defeasible: bool = False
    priorities: bool = False
    exceptions: bool = False
    contrary_to_duty: bool = False
    schema_version: str = NORMATIVE_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = NORMATIVE_PROFILE_INTERFACE

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
        form = (
            self.form
            if isinstance(self.form, NormFormKind)
            else NormFormKind(str(self.form))
        )
        permission = (
            self.permission
            if isinstance(self.permission, PermissionStrengthKind)
            else PermissionStrengthKind(str(self.permission))
        )
        object.__setattr__(self, "form", form)
        object.__setattr__(self, "permission", permission)
        for name in (
            "admit_classic_letters",
            "allow_dyadic",
            "allow_defeasible",
            "priorities",
            "exceptions",
            "contrary_to_duty",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if self.schema_version != NORMATIVE_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported NormativeProfile schema {self.schema_version!r}"
            )
        # Fail closed: this frontend only elaborates monadic norms.
        if form is NormFormKind.DYADIC or self.allow_dyadic:
            raise SyntaxContractError(
                "dyadic norms are not admitted by NormativeProfile@1; "
                "set form=monadic and allow_dyadic=False"
            )
        if self.allow_defeasible or self.priorities or self.exceptions or self.contrary_to_duty:
            raise SyntaxContractError(
                "defeasible/priority/exception/contrary-to-duty norms are not "
                "admitted by NormativeProfile@1; keep those flags False"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_letters": self.admit_classic_letters,
            "allow_defeasible": self.allow_defeasible,
            "allow_dyadic": self.allow_dyadic,
            "contrary_to_duty": self.contrary_to_duty,
            "exceptions": self.exceptions,
            "form": self.form.value
            if isinstance(self.form, NormFormKind)
            else str(self.form),
            "interface": self.interface,
            "permission": self.permission.value
            if isinstance(self.permission, PermissionStrengthKind)
            else str(self.permission),
            "priorities": self.priorities,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NormativeProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("NormativeProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            form=value.get("form", NormFormKind.MONADIC.value),
            permission=value.get("permission", PermissionStrengthKind.STRONG.value),
            admit_classic_letters=bool(value.get("admit_classic_letters", False)),
            allow_dyadic=bool(value.get("allow_dyadic", False)),
            allow_defeasible=bool(value.get("allow_defeasible", False)),
            priorities=bool(value.get("priorities", False)),
            exceptions=bool(value.get("exceptions", False)),
            contrary_to_duty=bool(value.get("contrary_to_duty", False)),
            schema_version=str(
                value.get("schema_version") or NORMATIVE_PROFILE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# CognitiveProfile@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CognitiveProfile:
    """Epistemic / doxastic / intention-agency profile (``CognitiveProfile@1``).

    Agent indices are required by default so multi-agent attitudes never collapse
    to anonymous classical modalities.
    """

    profile_id: str
    attitude: CognitiveAttitudeKind | str
    require_agent: bool = True
    admit_classic_letters: bool = False
    schema_version: str = COGNITIVE_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = COGNITIVE_PROFILE_INTERFACE

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
        attitude = (
            self.attitude
            if isinstance(self.attitude, CognitiveAttitudeKind)
            else CognitiveAttitudeKind(str(self.attitude))
        )
        object.__setattr__(self, "attitude", attitude)
        for name in ("require_agent", "admit_classic_letters"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if self.schema_version != COGNITIVE_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported CognitiveProfile schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_letters": self.admit_classic_letters,
            "attitude": self.attitude.value
            if isinstance(self.attitude, CognitiveAttitudeKind)
            else str(self.attitude),
            "interface": self.interface,
            "profile_id": self.profile_id,
            "require_agent": self.require_agent,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CognitiveProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("CognitiveProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            attitude=value.get("attitude", CognitiveAttitudeKind.EPISTEMIC.value),
            require_agent=bool(value.get("require_agent", True)),
            admit_classic_letters=bool(value.get("admit_classic_letters", False)),
            schema_version=str(
                value.get("schema_version") or COGNITIVE_PROFILE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# ModalSemanticsProfile (enters semantic identity)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModalSemanticsProfile:
    """Explicit modal/normative/cognitive semantic choices.

    Family, Kripke frame, norm form, and cognitive attitude are fields — never
    inferred from operator spelling.  The profile participates in every modal
    extension node's semantic identity.
    """

    profile_id: str
    family: ModalFamilyKind | str
    frame: KripkeFrameKind | str | None = None
    normative: NormativeProfile | None = None
    cognitive: CognitiveProfile | None = None
    admit_classic_letters: bool = False
    allow_agent_index: bool = False
    schema_version: str = MODAL_SEMANTICS_PROFILE_SCHEMA_VERSION

    interface: ClassVar[str] = MODAL_SEMANTICS_PROFILE_INTERFACE

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
        family = (
            self.family
            if isinstance(self.family, ModalFamilyKind)
            else ModalFamilyKind(str(self.family))
        )
        object.__setattr__(self, "family", family)

        frame = self.frame
        if frame is not None and not isinstance(frame, KripkeFrameKind):
            frame = KripkeFrameKind(str(frame))
        object.__setattr__(self, "frame", frame)

        normative = self.normative
        if isinstance(normative, Mapping):
            normative = NormativeProfile.from_dict(normative)
        if normative is not None and not isinstance(normative, NormativeProfile):
            raise SyntaxContractError("normative must be a NormativeProfile or None")
        object.__setattr__(self, "normative", normative)

        cognitive = self.cognitive
        if isinstance(cognitive, Mapping):
            cognitive = CognitiveProfile.from_dict(cognitive)
        if cognitive is not None and not isinstance(cognitive, CognitiveProfile):
            raise SyntaxContractError("cognitive must be a CognitiveProfile or None")
        object.__setattr__(self, "cognitive", cognitive)

        for name in ("admit_classic_letters", "allow_agent_index"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if self.schema_version != MODAL_SEMANTICS_PROFILE_SCHEMA_VERSION:
            raise SyntaxContractError(
                f"unsupported ModalSemanticsProfile schema {self.schema_version!r}"
            )

        # Cross-field consistency.
        if family is ModalFamilyKind.KRIPKE:
            if frame is None:
                raise SyntaxContractError("kripke profiles require an explicit frame")
            if normative is not None or cognitive is not None:
                raise SyntaxContractError(
                    "kripke profiles must not carry normative or cognitive sub-profiles"
                )
        elif family is ModalFamilyKind.DEONTIC:
            if normative is None:
                raise SyntaxContractError("deontic profiles require a NormativeProfile")
            if frame is not None:
                raise SyntaxContractError(
                    "deontic profiles must not declare a Kripke frame here "
                    "(frame axioms are a separate modal concern)"
                )
            if cognitive is not None:
                raise SyntaxContractError(
                    "deontic profiles must not carry a CognitiveProfile"
                )
        elif family in {
            ModalFamilyKind.EPISTEMIC,
            ModalFamilyKind.DOXASTIC,
            ModalFamilyKind.INTENTION,
        }:
            if cognitive is None:
                raise SyntaxContractError(
                    f"{family.value} profiles require a CognitiveProfile"
                )
            expected = {
                ModalFamilyKind.EPISTEMIC: CognitiveAttitudeKind.EPISTEMIC,
                ModalFamilyKind.DOXASTIC: CognitiveAttitudeKind.DOXASTIC,
                ModalFamilyKind.INTENTION: CognitiveAttitudeKind.INTENTION,
            }[family]
            if cognitive.attitude is not expected:
                raise SyntaxContractError(
                    f"{family.value} profile requires attitude={expected.value}"
                )
            if normative is not None:
                raise SyntaxContractError(
                    f"{family.value} profiles must not carry a NormativeProfile"
                )
        else:
            raise SyntaxContractError(f"unknown modal family {family!r}")

    @property
    def family_id(self) -> str:
        family = self.family
        if family is ModalFamilyKind.KRIPKE:
            return MODAL_FAMILY_ID
        if family is ModalFamilyKind.DEONTIC:
            return DEONTIC_FAMILY_ID
        if family is ModalFamilyKind.EPISTEMIC:
            return EPISTEMIC_FAMILY_ID
        if family is ModalFamilyKind.DOXASTIC:
            return DOXASTIC_FAMILY_ID
        if family is ModalFamilyKind.INTENTION:
            return INTENTION_FAMILY_ID
        return MODAL_FAMILY_ID

    @property
    def frame_axioms(self) -> dict[str, bool] | None:
        if self.frame is None:
            return None
        frame = (
            self.frame
            if isinstance(self.frame, KripkeFrameKind)
            else KripkeFrameKind(str(self.frame))
        )
        return dict(_FRAME_PROPERTIES[frame])

    @property
    def semantic_identity(self) -> dict[str, Any]:
        """Stable identity fragment contributed by the profile."""

        payload: dict[str, Any] = {
            "family": self.family.value
            if isinstance(self.family, ModalFamilyKind)
            else str(self.family),
            "profile_id": self.profile_id,
        }
        if self.frame is not None:
            payload["frame"] = (
                self.frame.value
                if isinstance(self.frame, KripkeFrameKind)
                else str(self.frame)
            )
            axioms = self.frame_axioms
            if axioms is not None:
                payload["frame_axioms"] = axioms
        if self.normative is not None:
            payload["normative"] = {
                "form": self.normative.form.value
                if isinstance(self.normative.form, NormFormKind)
                else str(self.normative.form),
                "permission": self.normative.permission.value
                if isinstance(self.normative.permission, PermissionStrengthKind)
                else str(self.normative.permission),
                "profile_id": self.normative.profile_id,
            }
        if self.cognitive is not None:
            payload["cognitive"] = {
                "attitude": self.cognitive.attitude.value
                if isinstance(self.cognitive.attitude, CognitiveAttitudeKind)
                else str(self.cognitive.attitude),
                "profile_id": self.cognitive.profile_id,
                "require_agent": self.cognitive.require_agent,
            }
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_classic_letters": self.admit_classic_letters,
            "allow_agent_index": self.allow_agent_index,
            "cognitive": self.cognitive.to_dict() if self.cognitive else None,
            "family": self.family.value
            if isinstance(self.family, ModalFamilyKind)
            else str(self.family),
            "frame": (
                self.frame.value
                if isinstance(self.frame, KripkeFrameKind)
                else (str(self.frame) if self.frame is not None else None)
            ),
            "interface": self.interface,
            "normative": self.normative.to_dict() if self.normative else None,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ModalSemanticsProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("ModalSemanticsProfile must be a mapping")
        normative_raw = value.get("normative")
        cognitive_raw = value.get("cognitive")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            family=value.get("family", ModalFamilyKind.KRIPKE.value),
            frame=value.get("frame"),
            normative=(
                NormativeProfile.from_dict(normative_raw)
                if isinstance(normative_raw, Mapping)
                else normative_raw
            ),
            cognitive=(
                CognitiveProfile.from_dict(cognitive_raw)
                if isinstance(cognitive_raw, Mapping)
                else cognitive_raw
            ),
            admit_classic_letters=bool(value.get("admit_classic_letters", False)),
            allow_agent_index=bool(value.get("allow_agent_index", False)),
            schema_version=str(
                value.get("schema_version") or MODAL_SEMANTICS_PROFILE_SCHEMA_VERSION
            ),
        )


def profile_kripke(
    frame: KripkeFrameKind | str = KripkeFrameKind.K,
    *,
    profile_id: str | None = None,
    admit_classic_letters: bool = False,
    allow_agent_index: bool = False,
) -> ModalSemanticsProfile:
    frame_kind = (
        frame if isinstance(frame, KripkeFrameKind) else KripkeFrameKind(str(frame))
    )
    return ModalSemanticsProfile(
        profile_id=profile_id or f"kripke_{frame_kind.value}",
        family=ModalFamilyKind.KRIPKE,
        frame=frame_kind,
        admit_classic_letters=admit_classic_letters,
        allow_agent_index=allow_agent_index,
    )


def profile_k(
    *,
    profile_id: str = "kripke_k",
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    return profile_kripke(
        KripkeFrameKind.K,
        profile_id=profile_id,
        admit_classic_letters=admit_classic_letters,
    )


def profile_d(
    *,
    profile_id: str = "kripke_d",
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    return profile_kripke(
        KripkeFrameKind.D,
        profile_id=profile_id,
        admit_classic_letters=admit_classic_letters,
    )


def profile_t(
    *,
    profile_id: str = "kripke_t",
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    return profile_kripke(
        KripkeFrameKind.T,
        profile_id=profile_id,
        admit_classic_letters=admit_classic_letters,
    )


def profile_s4(
    *,
    profile_id: str = "kripke_s4",
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    return profile_kripke(
        KripkeFrameKind.S4,
        profile_id=profile_id,
        admit_classic_letters=admit_classic_letters,
    )


def profile_s5(
    *,
    profile_id: str = "kripke_s5",
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    return profile_kripke(
        KripkeFrameKind.S5,
        profile_id=profile_id,
        admit_classic_letters=admit_classic_letters,
    )


def profile_deontic(
    *,
    profile_id: str = "deontic_monadic_strong",
    permission: PermissionStrengthKind | str = PermissionStrengthKind.STRONG,
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    normative = NormativeProfile(
        profile_id=f"{profile_id}:norm",
        form=NormFormKind.MONADIC,
        permission=permission,
        admit_classic_letters=admit_classic_letters,
    )
    return ModalSemanticsProfile(
        profile_id=profile_id,
        family=ModalFamilyKind.DEONTIC,
        normative=normative,
        admit_classic_letters=admit_classic_letters,
    )


def profile_epistemic(
    *,
    profile_id: str = "epistemic_agent",
    require_agent: bool = True,
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    cognitive = CognitiveProfile(
        profile_id=f"{profile_id}:cog",
        attitude=CognitiveAttitudeKind.EPISTEMIC,
        require_agent=require_agent,
        admit_classic_letters=admit_classic_letters,
    )
    return ModalSemanticsProfile(
        profile_id=profile_id,
        family=ModalFamilyKind.EPISTEMIC,
        cognitive=cognitive,
        admit_classic_letters=admit_classic_letters,
        allow_agent_index=True,
    )


def profile_doxastic(
    *,
    profile_id: str = "doxastic_agent",
    require_agent: bool = True,
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    cognitive = CognitiveProfile(
        profile_id=f"{profile_id}:cog",
        attitude=CognitiveAttitudeKind.DOXASTIC,
        require_agent=require_agent,
        admit_classic_letters=admit_classic_letters,
    )
    return ModalSemanticsProfile(
        profile_id=profile_id,
        family=ModalFamilyKind.DOXASTIC,
        cognitive=cognitive,
        admit_classic_letters=admit_classic_letters,
        allow_agent_index=True,
    )


def profile_intention(
    *,
    profile_id: str = "intention_agency_agent",
    require_agent: bool = True,
    admit_classic_letters: bool = False,
) -> ModalSemanticsProfile:
    cognitive = CognitiveProfile(
        profile_id=f"{profile_id}:cog",
        attitude=CognitiveAttitudeKind.INTENTION,
        require_agent=require_agent,
        admit_classic_letters=admit_classic_letters,
    )
    return ModalSemanticsProfile(
        profile_id=profile_id,
        family=ModalFamilyKind.INTENTION,
        cognitive=cognitive,
        admit_classic_letters=admit_classic_letters,
        allow_agent_index=True,
    )


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModalParseResult:
    """Typed result of a canonical modal parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: ModalSemanticsProfile | None = None
    schema_version: str = MODAL_PARSE_RESULT_SCHEMA_VERSION

    interface: ClassVar[str] = MODAL_SYNTAX_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)


class ModalParseError(SyntaxContractError):
    """Raised by raising helpers when a modal parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: ModalParseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)
        self.result = result


# ---------------------------------------------------------------------------
# Token cursor
# ---------------------------------------------------------------------------


class _ParseFail(Exception):
    """Internal control-flow exception for recoverable parse failures."""

    def __init__(self, diagnostic: SyntaxDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class _TokenCursor:
    """Cursor over non-trivia lexer tokens (EOF inclusive)."""

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
        if token.kind == TokenKind.KEYWORD.value:
            if token.lexeme.casefold() in {item.casefold() for item in lexemes}:
                return self.advance()
            return None
        if token.lexeme in lexemes:
            return self.advance()
        if token.lexeme.casefold() in {
            item.casefold() for item in lexemes if item.isalpha()
        }:
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
    diag_id = diagnostic_id or f"diag:modal:{code.replace('.', '-')}"
    return SyntaxDiagnostic(
        diagnostic_id=diag_id,
        code=code,
        message=message,
        severity=severity,
        range=range,
        remediation=remediation,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _ModalParserEngine:
    """Profile-bound recursive-descent parser for modal / normative / cognitive syntax."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: ModalSemanticsProfile,
        limits: ParseLimits,
        expression_id: str = "expr:modal:1",
        propositions: frozenset[str] | None = None,
    ) -> None:
        self.document = document
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self.propositions = propositions
        self.cursor = _TokenCursor(tokens, document)
        self.sink = DiagnosticSink(max_diagnostics=limits.max_diagnostics)
        self._node_seq = 0
        self.root: LogicNode | None = None

    def parse(self) -> tuple[LogicNode | None, tuple[SyntaxDiagnostic, ...]]:
        if self.cursor.is_eof():
            self._emit(
                CODE_EMPTY_INPUT,
                "empty input; expected a modal formula",
                self.cursor.eof_range(),
            )
            return None, self.sink.items
        try:
            node = self._parse_formula()
            if not self.cursor.is_eof():
                trailing = self.cursor.current()
                # Catch bare defeasible keywords that appear as trailing noise.
                if trailing.lexeme.casefold() in _DEFEASIBLE_KEYWORDS:
                    raise _ParseFail(
                        _diag(
                            code=CODE_UNSUPPORTED_DEFEASIBLE,
                            message=(
                                f"defeasible construct {trailing.lexeme!r} is not "
                                "admitted; cannot masquerade as classical connective"
                            ),
                            range=trailing.range,
                            remediation=(
                                "Remove defeasible keywords; monadic profiles only "
                                "admit classical connectives plus profile operators"
                            ),
                            metadata={"construct": trailing.lexeme, "classical": False},
                        )
                    )
                self._emit(
                    CODE_TRAILING_INPUT,
                    f"trailing input starting at {trailing.lexeme!r}",
                    trailing.range,
                    remediation="Remove trailing tokens or terminate the formula",
                )
                return None, self.sink.items
            self.root = node
            return node, self.sink.items
        except _ParseFail as failure:
            diag_id = f"diag:modal:fail:{len(self.sink.items) + 1}"
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
                f"diag:modal:{code.replace('.', '-')}:{len(self.sink.items) + 1}"
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

    def _parse_implies(self) -> LogicNode:
        left = self._parse_or()
        op = self.cursor.match_any(_IMPLIES_OPS)
        if op is None:
            return left
        right = self._parse_formula()
        span = self.cursor.range_span(left.range or op.range, right.range or op.range)
        return LogicNode(
            node_id=self._nid("imp"),
            kind=NodeKind.IMPLIES,
            sort=BOOL_SORT,
            arguments=(left, right),
            range=span,
        )

    def _parse_or(self) -> LogicNode:
        # Disjunction uses multi-letter / unicode / || forms only.  Bare '|'
        # is reserved for dyadic norms so O(p | q) and (p | q) never lower to
        # classical disjunction or equivalence.
        nodes = [self._parse_and()]
        while True:
            tok = self.cursor.current()
            if tok.kind == TokenKind.EOF.value:
                break
            if tok.lexeme == "|":
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_DYADIC,
                        message=(
                            "bare '|' is not classical disjunction; "
                            "unsupported dyadic separator (use 'or' / '∨' / '||')"
                        ),
                        range=tok.range,
                        remediation=(
                            "Write 'or' for classical disjunction; dyadic norms "
                            "are not admitted by this frontend"
                        ),
                        metadata={
                            "separator": "|",
                            "classical_equivalence": False,
                        },
                    )
                )
            if tok.lexeme in {"||"} or tok.lexeme.casefold() in {"or"} or tok.lexeme == "∨":
                self.cursor.advance()
                nodes.append(self._parse_and())
                continue
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
        nodes = [self._parse_unary()]
        while self.cursor.match_any(_AND_OPS) is not None:
            nodes.append(self._parse_unary())
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

    def _parse_unary(self) -> LogicNode:
        # Defeasible keywords never become operators or atoms.
        self._reject_defeasible_here()

        modal = self._match_modal_operator()
        if modal is not None:
            op_token, operator, agent, op_class = modal
            # Detect dyadic application O(φ | ψ) before consuming body.
            if op_class == "deontic":
                self._reject_dyadic_application(op_token)
            self._enter()
            try:
                body = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(
                op_token.range, body.range or op_token.range
            )
            return self._mk_modal(
                operator,
                body=body,
                agent=agent,
                span=span,
            )

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
        self._reject_defeasible_here()

        open_tok = self.cursor.match_lexeme("(")
        if open_tok is not None:
            # Inside parentheses, still reject dyadic separators used as if
            # they were classical connectives at top of a group that looks like
            # a bare dyadic payload (p | q) when preceded by nothing modal —
            # handled when modal op sees the form.  Normal grouping is fine.
            inner = self._parse_formula()
            # If after a complete formula we still see a dyadic separator before
            # close, this is a dyadic pair without a modal operator — also reject
            # so it cannot become classical or/iff.
            sep = self.cursor.current()
            if sep.lexeme in {"|", "/", "//"} or sep.lexeme.casefold() in {
                "given",
                "if",
            }:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_DYADIC,
                        message=(
                            f"dyadic separator {sep.lexeme!r} is not classical "
                            "equivalence/disjunction; unsupported dyadic construct"
                        ),
                        range=sep.range,
                        remediation=(
                            "Use monadic operators only; dyadic norms are not "
                            "admitted by this frontend"
                        ),
                        metadata={
                            "separator": sep.lexeme,
                            "classical_equivalence": False,
                        },
                    )
                )
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
        if current.kind in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}:
            name = current.lexeme
            # Profile-free overloaded single letters used as atoms are fine;
            # operator-position overloads are handled in _match_modal_operator.
            self.cursor.advance()
            if self.propositions is not None and name not in self.propositions:
                raise _ParseFail(
                    _diag(
                        code=CODE_UNEXPECTED_TOKEN,
                        message=f"undeclared proposition {name!r}",
                        range=current.range,
                        remediation="Declare the proposition or add it to the alphabet",
                    )
                )
            return LogicNode(
                node_id=self._nid("atom"),
                kind=NodeKind.PREDICATE,
                symbol=name,
                sort=BOOL_SORT,
                arguments=(),
                range=current.range,
            )

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected formula; got {current.lexeme!r}",
                range=current.range,
            )
        )

    # -- defeasible / dyadic rejection -------------------------------------

    def _reject_defeasible_here(self) -> None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return
        if token.lexeme.casefold() in _DEFEASIBLE_KEYWORDS:
            raise _ParseFail(
                _diag(
                    code=CODE_UNSUPPORTED_DEFEASIBLE,
                    message=(
                        f"defeasible construct {token.lexeme!r} is not admitted; "
                        "cannot masquerade as classical connective or modality"
                    ),
                    range=token.range,
                    remediation=(
                        "Remove defeasible/priority/exception keywords; only "
                        "monadic profile-bound operators are supported"
                    ),
                    metadata={
                        "construct": token.lexeme,
                        "classical_equivalence": False,
                        "supported": False,
                    },
                )
            )

    def _reject_dyadic_application(self, op_token: LogicToken) -> None:
        """Reject O(φ | ψ) / obligated(p / q) forms before parsing the body."""

        nxt = self.cursor.current()
        if nxt.lexeme != "(":
            return
        # Scan ahead (without consuming permanently) for a dyadic separator
        # at paren depth 1 before the matching close.
        depth = 0
        idx = self.cursor.index
        tokens = self.cursor.tokens
        while idx < len(tokens):
            tok = tokens[idx]
            if tok.kind == TokenKind.EOF.value:
                break
            if tok.lexeme == "(":
                depth += 1
            elif tok.lexeme == ")":
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1 and (
                tok.lexeme in {"|", "/", "//"}
                or tok.lexeme.casefold() in {"given", "if"}
            ):
                raise _ParseFail(
                    _diag(
                        code=CODE_UNSUPPORTED_DYADIC,
                        message=(
                            f"dyadic norm application of {op_token.lexeme!r} with "
                            f"separator {tok.lexeme!r} is not admitted; "
                            "cannot masquerade as classical equivalence"
                        ),
                        range=self.cursor.range_span(op_token.range, tok.range),
                        remediation=(
                            "Use monadic form e.g. obligated p; dyadic/conditional "
                            "norms are unsupported under NormativeProfile@1"
                        ),
                        metadata={
                            "operator": op_token.lexeme,
                            "separator": tok.lexeme,
                            "classical_equivalence": False,
                            "norm_form": "dyadic",
                        },
                    )
                )
            idx += 1

    # -- operator matching -------------------------------------------------

    def _match_modal_operator(
        self,
    ) -> tuple[LogicToken, str, str | None, str] | None:
        """Return (token, canonical_op, agent, op_class) or None."""

        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None

        # Bracket alethic forms: [] and <> as two consecutive symbols.
        bracket = self._match_alethic_brackets()
        if bracket is not None:
            return bracket

        raw = token.lexeme
        folded = raw.casefold()

        # Unicode box/diamond as single operator tokens.
        if raw in {"□", "◇", "◊"}:
            return self._consume_alethic(token, _ALETHIC_CANON[raw])

        # Multi-letter alethic words.
        if folded in {"box", "necessary", "nec", "diamond", "possible", "poss"}:
            if not self._looks_like_operator_use():
                return None
            return self._consume_alethic(token, _ALETHIC_CANON[folded])

        # Multi-letter deontic words.
        if folded in _OBLIGATION_WORDS | _PERMISSION_WORDS | _FORBIDDEN_WORDS:
            if not self._looks_like_operator_use():
                return None
            return self._consume_deontic(token, _DEONTIC_CANON[folded])

        # Multi-letter cognitive words.
        if folded in _KNOWS_WORDS | _BELIEVES_WORDS | _INTENDS_WORDS:
            if not self._looks_like_operator_use():
                return None
            return self._consume_cognitive(token, _COGNITIVE_CANON[folded])

        # Classic single-letter overloaded symbols.
        if raw in _CLASSIC_DEONTIC_LETTERS or (
            len(raw) == 1 and folded in {"o", "p", "f"} and raw.isalpha()
        ):
            return self._match_classic_deontic(token, raw)

        if raw in _CLASSIC_COGNITIVE_LETTERS or (
            len(raw) == 1 and folded in {"k", "b", "i"} and raw.isalpha()
        ):
            return self._match_classic_cognitive(token, raw)

        return None

    def _match_alethic_brackets(
        self,
    ) -> tuple[LogicToken, str, str | None, str] | None:
        token = self.cursor.current()
        nxt = self.cursor.peek(1)
        if token.lexeme == "[" and nxt.lexeme == "]":
            # []φ — consume both brackets as one operator.
            if not self.profile.admit_classic_letters and self.profile.family is not ModalFamilyKind.KRIPKE:
                # Still an overloaded box spelling; require kripke profile.
                pass
            start = token
            self.cursor.advance()  # [
            close = self.cursor.advance()  # ]
            if self.profile.family is not ModalFamilyKind.KRIPKE:
                raise _ParseFail(
                    _diag(
                        code=CODE_OVERLOADED_SYMBOL,
                        message=(
                            "bracket box '[]' is an overloaded modal symbol; "
                            "requires a declared kripke profile"
                        ),
                        range=self.cursor.range_span(start.range, close.range),
                        remediation="Use profile_k/profile_s4/... or write 'box'",
                        metadata={"operator": "[]", "family_required": "kripke"},
                    )
                )
            agent = self._parse_optional_agent(after=close)
            return start, "box", agent, "alethic"
        if token.lexeme == "<" and nxt.lexeme == ">":
            start = token
            self.cursor.advance()
            close = self.cursor.advance()
            if self.profile.family is not ModalFamilyKind.KRIPKE:
                raise _ParseFail(
                    _diag(
                        code=CODE_OVERLOADED_SYMBOL,
                        message=(
                            "bracket diamond '<>' is an overloaded modal symbol; "
                            "requires a declared kripke profile"
                        ),
                        range=self.cursor.range_span(start.range, close.range),
                        remediation="Use a kripke profile or write 'diamond'",
                        metadata={"operator": "<>", "family_required": "kripke"},
                    )
                )
            agent = self._parse_optional_agent(after=close)
            return start, "diamond", agent, "alethic"
        return None

    def _consume_alethic(
        self, token: LogicToken, canon: str
    ) -> tuple[LogicToken, str, str | None, str]:
        if self.profile.family is not ModalFamilyKind.KRIPKE:
            raise _ParseFail(
                _diag(
                    code=CODE_OPERATOR_FORBIDDEN,
                    message=(
                        f"alethic operator {token.lexeme!r} is not admitted by "
                        f"profile {self.profile.profile_id!r} "
                        f"(family={self.profile.family.value if isinstance(self.profile.family, ModalFamilyKind) else self.profile.family})"
                    ),
                    range=token.range,
                    remediation="Use a kripke K/D/T/S4/S5 profile",
                    metadata={"operator": token.lexeme, "canonical": canon},
                )
            )
        self.cursor.advance()
        agent = self._parse_optional_agent(after=token)
        return token, canon, agent, "alethic"

    def _consume_deontic(
        self, token: LogicToken, canon: str
    ) -> tuple[LogicToken, str, str | None, str]:
        if self.profile.family is not ModalFamilyKind.DEONTIC:
            raise _ParseFail(
                _diag(
                    code=CODE_OPERATOR_FORBIDDEN,
                    message=(
                        f"deontic operator {token.lexeme!r} is not admitted by "
                        f"profile {self.profile.profile_id!r}"
                    ),
                    range=token.range,
                    remediation="Use profile_deontic() / a NormativeProfile",
                    metadata={"operator": token.lexeme, "canonical": canon},
                )
            )
        self.cursor.advance()
        # Monadic deontic does not take agents.
        if self.cursor.current().lexeme == "[":
            raise _ParseFail(
                _diag(
                    code=CODE_AGENT_FORBIDDEN,
                    message=(
                        f"agent index is not admitted on monadic deontic "
                        f"operator {token.lexeme!r}"
                    ),
                    range=self.cursor.current().range,
                )
            )
        return token, canon, None, "deontic"

    def _consume_cognitive(
        self, token: LogicToken, canon: str
    ) -> tuple[LogicToken, str, str | None, str]:
        family = self.profile.family
        expected = {
            "knows": ModalFamilyKind.EPISTEMIC,
            "believes": ModalFamilyKind.DOXASTIC,
            "intends": ModalFamilyKind.INTENTION,
        }[canon]
        if family is not expected:
            raise _ParseFail(
                _diag(
                    code=CODE_OPERATOR_FORBIDDEN,
                    message=(
                        f"cognitive operator {token.lexeme!r} is not admitted by "
                        f"profile {self.profile.profile_id!r} "
                        f"(requires family={expected.value})"
                    ),
                    range=token.range,
                    remediation=f"Use a {expected.value} CognitiveProfile",
                    metadata={"operator": token.lexeme, "canonical": canon},
                )
            )
        self.cursor.advance()
        agent = self._parse_optional_agent(after=token)
        cog = self.profile.cognitive
        assert cog is not None
        if cog.require_agent and not agent:
            raise _ParseFail(
                _diag(
                    code=CODE_AGENT_REQUIRED,
                    message=(
                        f"operator {token.lexeme!r} requires an agent index "
                        f"under profile {self.profile.profile_id!r}"
                    ),
                    range=token.range,
                    remediation="Write e.g. knows[alice] p",
                )
            )
        if agent and not self.profile.allow_agent_index:
            raise _ParseFail(
                _diag(
                    code=CODE_AGENT_FORBIDDEN,
                    message="agent index is not admitted by this profile",
                    range=token.range,
                )
            )
        return token, canon, agent, "cognitive"

    def _match_classic_deontic(
        self, token: LogicToken, raw: str
    ) -> tuple[LogicToken, str, str | None, str] | None:
        if not self._looks_like_operator_use():
            return None  # bare atom O/P/F
        if self.profile.family is not ModalFamilyKind.DEONTIC:
            raise _ParseFail(
                _diag(
                    code=CODE_OVERLOADED_SYMBOL,
                    message=(
                        f"overloaded deontic symbol {raw!r} requires a declared "
                        "deontic/NormativeProfile; profile-free use is rejected"
                    ),
                    range=token.range,
                    remediation=(
                        "Pass profile_deontic(admit_classic_letters=True) or "
                        "write obligated/permitted/forbidden"
                    ),
                    metadata={"operator": raw, "family_required": "deontic"},
                )
            )
        admitted = (
            self.profile.admit_classic_letters
            or (
                self.profile.normative is not None
                and self.profile.normative.admit_classic_letters
            )
        )
        if not admitted:
            raise _ParseFail(
                _diag(
                    code=CODE_OVERLOADED_SYMBOL,
                    message=(
                        f"overloaded deontic symbol {raw!r} requires "
                        "admit_classic_letters=True or multi-letter "
                        "obligated/permitted/forbidden"
                    ),
                    range=token.range,
                    remediation=(
                        "Write 'obligated'/'permitted'/'forbidden', or set "
                        "admit_classic_letters=True on the normative profile"
                    ),
                    metadata={"operator": raw},
                )
            )
        return self._consume_deontic(token, _DEONTIC_CANON[raw.casefold()])

    def _match_classic_cognitive(
        self, token: LogicToken, raw: str
    ) -> tuple[LogicToken, str, str | None, str] | None:
        if not self._looks_like_operator_use():
            return None
        folded = raw.casefold()
        canon = _COGNITIVE_CANON[folded]
        expected = {
            "knows": ModalFamilyKind.EPISTEMIC,
            "believes": ModalFamilyKind.DOXASTIC,
            "intends": ModalFamilyKind.INTENTION,
        }[canon]
        if self.profile.family is not expected:
            raise _ParseFail(
                _diag(
                    code=CODE_OVERLOADED_SYMBOL,
                    message=(
                        f"overloaded cognitive symbol {raw!r} requires a declared "
                        f"{expected.value} CognitiveProfile; profile-free use is rejected"
                    ),
                    range=token.range,
                    remediation=(
                        f"Pass profile_{expected.value.split('_')[0]}("
                        "admit_classic_letters=True) or multi-letter form"
                    ),
                    metadata={"operator": raw, "family_required": expected.value},
                )
            )
        admitted = (
            self.profile.admit_classic_letters
            or (
                self.profile.cognitive is not None
                and self.profile.cognitive.admit_classic_letters
            )
        )
        if not admitted:
            raise _ParseFail(
                _diag(
                    code=CODE_OVERLOADED_SYMBOL,
                    message=(
                        f"overloaded cognitive symbol {raw!r} requires "
                        "admit_classic_letters=True or multi-letter "
                        "knows/believes/intends"
                    ),
                    range=token.range,
                    remediation=(
                        "Write multi-letter attitude words, or set "
                        "admit_classic_letters=True"
                    ),
                    metadata={"operator": raw},
                )
            )
        return self._consume_cognitive(token, canon)

    def _parse_optional_agent(self, *, after: LogicToken) -> str | None:
        if self.cursor.current().lexeme != "[":
            return None
        open_tok = self.cursor.advance()
        agent_tok = self.cursor.current()
        if agent_tok.kind not in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            raise _ParseFail(
                _diag(
                    code=CODE_MISSING_AGENT,
                    message=f"expected agent identifier; got {agent_tok.lexeme!r}",
                    range=agent_tok.range,
                )
            )
        agent = agent_tok.lexeme
        self.cursor.advance()
        close = self.cursor.expect_lexeme("]", code=CODE_UNBALANCED)
        _ = self.cursor.range_span(open_tok.range, close.range)
        if not self.profile.allow_agent_index and self.profile.family is ModalFamilyKind.KRIPKE:
            raise _ParseFail(
                _diag(
                    code=CODE_AGENT_FORBIDDEN,
                    message=(
                        "agent index on alethic operators requires "
                        "allow_agent_index=True"
                    ),
                    range=open_tok.range,
                )
            )
        return agent

    def _looks_like_operator_use(self) -> bool:
        """True when current token is followed by formula material or '[' agent."""

        nxt = self.cursor.peek(1)
        if nxt.kind == TokenKind.EOF.value:
            return False
        if nxt.lexeme in {"[", "("}:
            return True
        if nxt.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.NUMBER.value,
        }:
            if nxt.lexeme.casefold() in {
                "and",
                "or",
                "implies",
                "iff",
            }:
                return False
            return True
        if nxt.lexeme in _NOT_OPS | _TRUE_OPS | _FALSE_OPS | {"□", "◇", "◊"}:
            return True
        return False

    # -- node construction -------------------------------------------------

    def _mk_modal(
        self,
        operator: str,
        *,
        body: LogicNode,
        agent: str | None,
        span: SourceRange,
    ) -> LogicNode:
        family_id = self.profile.family_id
        payload: dict[str, Any] = {
            "family": (
                self.profile.family.value
                if isinstance(self.profile.family, ModalFamilyKind)
                else str(self.profile.family)
            ),
            "kind": operator,
            "profile_id": self.profile.profile_id,
            "schema_version": MODAL_OPERATOR_PAYLOAD_SCHEMA,
        }
        if self.profile.frame is not None:
            payload["frame"] = (
                self.profile.frame.value
                if isinstance(self.profile.frame, KripkeFrameKind)
                else str(self.profile.frame)
            )
            axioms = self.profile.frame_axioms
            if axioms is not None:
                payload["frame_axioms"] = axioms
        if self.profile.normative is not None:
            payload["norm_form"] = (
                self.profile.normative.form.value
                if isinstance(self.profile.normative.form, NormFormKind)
                else str(self.profile.normative.form)
            )
            payload["permission"] = (
                self.profile.normative.permission.value
                if isinstance(self.profile.normative.permission, PermissionStrengthKind)
                else str(self.profile.normative.permission)
            )
        if self.profile.cognitive is not None:
            payload["attitude"] = (
                self.profile.cognitive.attitude.value
                if isinstance(self.profile.cognitive.attitude, CognitiveAttitudeKind)
                else str(self.profile.cognitive.attitude)
            )
        if agent is not None:
            payload["agent"] = agent

        features = (f"modal.{operator}",)
        if agent is not None:
            features = (f"modal.{operator}", "modal.agent_indexed")
        return mk_extension(
            self._nid(operator),
            family=family_id,
            profile=self.profile.profile_id,
            features=features,
            payload_schema=MODAL_OPERATOR_PAYLOAD_SCHEMA,
            payload=payload,
            children=(body,),
            range=span,
        )


# ---------------------------------------------------------------------------
# CST / surface helpers
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:modal:1",
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


def _surface_from_node(node: LogicNode, *, counter: list[int] | None = None) -> list[SurfaceASTRef]:
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
            if n.range is not None:
                meta["source_start"] = n.range.start
                meta["source_end"] = n.range.end
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


def modal_semantic_identity(
    node: LogicNode,
    profile: ModalSemanticsProfile,
) -> dict[str, Any]:
    """Build the semantic identity of *node* under *profile*.

    Profile id, family, frame axioms, norm form, and agent indices always
    participate.  Modal extension payloads already embed them; this helper
    re-exports a stable sorted view for tests and content-addressed consumers.
    """

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
        if kind == NodeKind.PREDICATE.value:
            return {"kind": "atom", "symbol": n.symbol}
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
    }


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class ModalPrinter:
    """Deterministic printer for modal / normative / cognitive formulas.

    Parenthesization makes implication associativity and modal binding
    explicit so parse(print(parse(s))) is alpha-equivalent to parse(s).
    Source binding structure is preserved via explicit parentheses.
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
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            return node.symbol
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, parent_prec)
        raise SyntaxContractError(f"unsupported node kind for printing: {kind!r}")

    def _print_extension(self, node: LogicNode, parent_prec: int) -> str:
        assert node.extension is not None
        payload = dict(node.extension.payload)
        kind = str(payload.get("kind") or "")
        children = node.extension.children
        agent = payload.get("agent")
        agent_text = f"[{agent}]" if agent else ""

        surface = {
            "box": self._op("box", "□"),
            "diamond": self._op("diamond", "◇"),
            "obligation": "obligated",
            "permission": "permitted",
            "forbidden": "forbidden",
            "knows": "knows",
            "believes": "believes",
            "intends": "intends",
        }.get(kind, kind)

        if kind not in _ALL_MODAL_UNARY:
            raise SyntaxContractError(f"unsupported modal extension kind {kind!r}")
        body = self._print_node(children[0], _Prec.UNARY)
        text = f"{surface}{agent_text} {body}"
        return self._paren(text, _Prec.UNARY, parent_prec)

    def _paren(self, text: str, prec: int, parent_prec: int) -> str:
        if prec < parent_prec:
            return f"({text})"
        return text


# ---------------------------------------------------------------------------
# Public parser surface
# ---------------------------------------------------------------------------


def _collect_atoms(node: LogicNode) -> tuple[str, ...]:
    found: list[str] = []

    def walk(n: LogicNode) -> None:
        kind = n.kind
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            if n.symbol and not n.arguments:
                found.append(n.symbol)
        for child in n.arguments:
            walk(child)
        if n.extension is not None:
            for child in n.extension.children:
                walk(child)

    walk(node)
    return tuple(sorted(set(found)))


def _signature_for_formula(
    root: LogicNode,
    profile: ModalSemanticsProfile,
) -> LogicSignature:
    atoms = _collect_atoms(root)
    if not atoms:
        return LogicSignature(
            signature_id=f"sig:modal:{profile.profile_id}",
            family=profile.family_id,
            profile=profile.profile_id,
            sorts=(),
            symbols=(),
            features=("modal", "propositional"),
        )
    return propositional_signature(
        f"sig:modal:{profile.profile_id}",
        atoms,
        family=profile.family_id,
        profile=profile.profile_id,
    )


def _extract_profile(value: object) -> ModalSemanticsProfile | None:
    if value is None:
        return None
    if isinstance(value, ModalSemanticsProfile):
        return value
    if isinstance(value, Mapping):
        return ModalSemanticsProfile.from_dict(value)
    return None


class ModalParser:
    """Notation parser for modal / normative / cognitive syntax (``ModalSyntax@1``)."""

    interface: ClassVar[str] = MODAL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = MODAL_NOTATION_ID
    notation_version: ClassVar[str] = MODAL_NOTATION_VERSION

    def __init__(
        self,
        profile: ModalSemanticsProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
        propositions: Sequence[str] | None = None,
    ) -> None:
        if profile is not None and not isinstance(profile, ModalSemanticsProfile):
            raise SyntaxContractError("profile must be a ModalSemanticsProfile")
        self.profile = profile
        self.printer = ModalPrinter(style=print_style)
        self.propositions = (
            frozenset(propositions) if propositions is not None else None
        )
        self._lexer = BoundedLexer(keywords=_MODAL_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("modal_semantics_profile"))
            or self.profile
        )
        props = request.metadata.get("propositions")
        propositions = (
            frozenset(str(item) for item in props)
            if isinstance(props, Sequence) and not isinstance(props, (str, bytes))
            else self.propositions
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(request.metadata.get("expression_id") or "expr:modal:1"),
            propositions=propositions,
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: ModalSemanticsProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:modal:1",
        expression_id: str = "expr:modal:1",
        propositions: frozenset[str] | None = None,
    ) -> ModalParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_REQUIRED,
                message=(
                    "modal parse requires a declared ModalSemanticsProfile; "
                    "profile-free overloaded symbols are rejected"
                ),
                range=document.full_range(),
                remediation=(
                    "Pass profile=profile_k()/profile_deontic()/profile_epistemic()/... "
                    "or metadata['profile']"
                ),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": MODAL_SYNTAX_INTERFACE},
            )
            return ModalParseResult(
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
                    diagnostic_id=f"diag:modal:lex:{index + 1}",
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
                metadata={"interface": MODAL_SYNTAX_INTERFACE},
            )
            return ModalParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _ModalParserEngine(
            document=document,
            tokens=lex_result.tokens,
            profile=prof,
            limits=bounds,
            expression_id=expression_id,
            propositions=propositions if propositions is not None else self.propositions,
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
                    "interface": MODAL_SYNTAX_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ModalParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        signature = _signature_for_formula(root, prof)
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
        printed = self.printer.print(root)
        identity = modal_semantic_identity(root, prof)
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
                "interface": MODAL_SYNTAX_INTERFACE,
                "expression": expression.to_dict(),
                "notation_id": MODAL_NOTATION_ID,
                "notation_version": MODAL_NOTATION_VERSION,
                "printed": printed,
                "profile": prof.to_dict(),
                "semantic_identity": identity,
            },
        )
        artifact.validate_against(document, limits=bounds)
        return ModalParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
        )


class ModalSyntax:
    """Facade for modal / normative / cognitive parse/print round-trips.

    Interface: ``ModalSyntax@1``.
    """

    interface: ClassVar[str] = MODAL_SYNTAX_INTERFACE
    notation_id: ClassVar[str] = MODAL_NOTATION_ID
    notation_version: ClassVar[str] = MODAL_NOTATION_VERSION

    def __init__(
        self,
        profile: ModalSemanticsProfile,
        *,
        print_style: str = PrintStyle.ASCII,
        propositions: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(profile, ModalSemanticsProfile):
            raise SyntaxContractError("profile must be a ModalSemanticsProfile")
        self.profile = profile
        self.parser = ModalParser(
            profile, print_style=print_style, propositions=propositions
        )
        self.printer = self.parser.printer

    @property
    def family_id(self) -> str:
        return self.profile.family_id

    def parse_text(
        self,
        text: str,
        *,
        document_id: str = "doc:modal:1",
        expression_id: str = "expr:modal:1",
        limits: ParseLimits | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
    ) -> ModalParseResult:
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
            raise ModalParseError(
                result.errors[0].message if result.errors else "modal parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def round_trip(self, text: str, **kwargs: Any) -> ModalParseResult:
        """Parse, print, and re-parse; success requires alpha-equivalence."""

        first = self.parse_text(text, **kwargs)
        if not first.ok or first.root is None:
            return first
        printed = self.print(first.root)
        second = self.parse_text(
            printed,
            document_id=str(kwargs.get("document_id") or "doc:modal:1") + ":rt",
            expression_id=str(kwargs.get("expression_id") or "expr:modal:1") + ":rt",
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
            return ModalParseResult(
                status=ParseStatus.FAILED,
                root=second.root,
                expression=second.expression,
                diagnostics=second.diagnostics + (diag,),
                tokens=second.tokens,
                artifact=second.artifact,
                printed=printed,
                profile=self.profile,
            )
        return ModalParseResult(
            status=ParseStatus.OK,
            root=second.root,
            expression=second.expression,
            diagnostics=second.diagnostics,
            tokens=second.tokens,
            artifact=second.artifact,
            printed=printed,
            profile=self.profile,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def parse_modal(
    text: str,
    profile: ModalSemanticsProfile,
    *,
    document_id: str = "doc:modal:1",
    expression_id: str = "expr:modal:1",
    limits: ParseLimits | None = None,
    print_style: str = PrintStyle.ASCII,
    propositions: Sequence[str] | None = None,
) -> ModalParseResult:
    """Parse *text* as modal / normative / cognitive syntax under *profile*."""

    syntax = ModalSyntax(profile, print_style=print_style, propositions=propositions)
    return syntax.parse_text(
        text,
        document_id=document_id,
        expression_id=expression_id,
        limits=limits,
    )


def print_modal(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    """Print *node* in canonical modal notation."""

    return ModalPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: ModalSemanticsProfile,
    *,
    style: str = PrintStyle.ASCII,
    propositions: Sequence[str] | None = None,
) -> ModalParseResult:
    """Parse/print/parse round-trip with alpha-equivalence check."""

    return ModalSyntax(
        profile, print_style=style, propositions=propositions
    ).round_trip(text)


__all__ = [
    "CODE_AGENT_FORBIDDEN",
    "CODE_AGENT_REQUIRED",
    "CODE_EMPTY_INPUT",
    "CODE_LEXER_ERROR",
    "CODE_MISSING_AGENT",
    "CODE_OPERATOR_FORBIDDEN",
    "CODE_OVERLOADED_SYMBOL",
    "CODE_PARSE_DEPTH",
    "CODE_PROFILE_MISMATCH",
    "CODE_PROFILE_REQUIRED",
    "CODE_ROUND_TRIP",
    "CODE_TRAILING_INPUT",
    "CODE_UNBALANCED",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_UNSUPPORTED_DEFEASIBLE",
    "CODE_UNSUPPORTED_DYADIC",
    "COGNITIVE_PROFILE_INTERFACE",
    "COGNITIVE_PROFILE_SCHEMA_VERSION",
    "CognitiveAttitudeKind",
    "CognitiveProfile",
    "DEONTIC_FAMILY_ID",
    "DOXASTIC_FAMILY_ID",
    "EPISTEMIC_FAMILY_ID",
    "INTENTION_FAMILY_ID",
    "KripkeFrameKind",
    "MODAL_FAMILY_ID",
    "MODAL_MODULE_VERSION",
    "MODAL_NOTATION_ID",
    "MODAL_NOTATION_VERSION",
    "MODAL_PARSE_RESULT_SCHEMA_VERSION",
    "MODAL_SEMANTICS_PROFILE_INTERFACE",
    "MODAL_SEMANTICS_PROFILE_SCHEMA_VERSION",
    "MODAL_SYNTAX_INTERFACE",
    "ModalFamilyKind",
    "ModalParseError",
    "ModalParseResult",
    "ModalParser",
    "ModalPrinter",
    "ModalSemanticsProfile",
    "ModalSyntax",
    "NORMATIVE_PROFILE_INTERFACE",
    "NORMATIVE_PROFILE_SCHEMA_VERSION",
    "NormFormKind",
    "NormativeProfile",
    "PermissionStrengthKind",
    "PrintStyle",
    "modal_semantic_identity",
    "parse_modal",
    "parse_print_parse",
    "print_modal",
    "profile_d",
    "profile_deontic",
    "profile_doxastic",
    "profile_epistemic",
    "profile_intention",
    "profile_k",
    "profile_kripke",
    "profile_s4",
    "profile_s5",
    "profile_t",
]
