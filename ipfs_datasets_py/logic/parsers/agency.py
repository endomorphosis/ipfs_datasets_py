"""BDI, epistemic-temporal, agency, and intention profiles.

Interface:

* ``AgencyLogicProfiles@1`` — parse/print/elaborate for controlled BDI attitudes,
  epistemic-temporal knowledge/belief, agency actions/goals, and intention
  operators under **named** semantic profiles

Owned constructs:

* belief / desire / intention (BDI) attitudes with **explicit agent indices**
* knowledge (epistemic) with optional **time indices** for epistemic-temporal
* goals, actions, agents, and does/achieves agency atoms
* accessibility / frame axioms and introspection assumptions as **profile fields**
  (never inferred from operator spelling)

Authority ceilings (fail-closed):

* BDI profiles are **not** DCEC profiles.  Family identity ``bdi`` never equals
  ``dcec``.  DCEC event-calculus surface is only reachable through an explicit
  ``DCECImporterHook`` that preserves both family identities.
* Profile-free classic letters ``B``/``K``/``D``/``I`` fail closed.
* Agent indices are required by default; time indices are required under
  epistemic-temporal profiles when ``require_time_index=True``.

Grammar (connective precedence, low → high)::

    formula     ::= iff
    iff         ::= implies (('iff'|↔) implies)*
    implies     ::= or (('implies'|→|=>|->) formula)?   # right-assoc
    or          ::= and (('or'|∨) and)*
    and         ::= unary (('and'|∧) unary)*
    unary       ::= attitude agent_index time_index? unary
                  | ('not'|¬) unary
                  | atomic
    attitude    ::= believes|knows|desires|intends|goals|goal
                  | does|achieves|acts
                  | B|K|D|I   # classic letters, profile-gated
    agent_index ::= '[' IDENT ']'
    time_index  ::= '@' IDENT | '@' NUMBER
    atomic      ::= true|false | agency_atom | IDENT | '(' formula ')'
    agency_atom ::= agent '(' IDENT ')'
                  | action '(' IDENT ',' IDENT (',' IDENT|NUMBER)? ')'
                  | goal '(' IDENT ',' IDENT ')'

Evidence subset: bdi epistemic temporal agency intention dcec agent
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
    mk_predicate,
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

AGENCY_LOGIC_PROFILES_INTERFACE: Final = "AgencyLogicProfiles@1"
AGENCY_PROFILE_INTERFACE: Final = "AgencyLogicProfile@1"
BDI_PROFILE_INTERFACE: Final = "BDIProfile@1"
EPISTEMIC_TEMPORAL_PROFILE_INTERFACE: Final = "EpistemicTemporalProfile@1"
INTENTION_AGENCY_PROFILE_INTERFACE: Final = "IntentionAgencyProfile@1"
DCEC_IMPORTER_HOOK_INTERFACE: Final = "DCECImporterHook@1"

AGENCY_NOTATION_ID: Final = "canonical_agency"
AGENCY_NOTATION_VERSION: Final = "1.0.0"
AGENCY_MODULE_VERSION: Final = "1.0.0"
AGENCY_TASK_ID: Final = "LFP2-040"

# Family identities — BDI and DCEC must never share a family id.
BDI_FAMILY_ID: Final = "bdi"
EPISTEMIC_TEMPORAL_FAMILY_ID: Final = "epistemic_temporal"
AGENCY_FAMILY_ID: Final = "agency"
INTENTION_FAMILY_ID: Final = "intention_agency"
# Referenced only by the DCEC importer hook; never assigned to BDI profiles.
DCEC_FAMILY_ID: Final = "dcec"
DCEC_PROFILE_INTERFACE: Final = "DCECProfile@1"

AGENCY_PARSE_RESULT_SCHEMA: Final = "canonical-agency-parse-result/v1"
AGENCY_PROFILE_SCHEMA: Final = "agency-logic-profile/v1"
BDI_PROFILE_SCHEMA: Final = "bdi-profile/v1"
EPISTEMIC_TEMPORAL_PROFILE_SCHEMA: Final = "epistemic-temporal-profile/v1"
INTENTION_PROFILE_SCHEMA: Final = "intention-agency-profile/v1"
DCEC_HOOK_SCHEMA: Final = "dcec-importer-hook/v1"
AGENCY_OPERATOR_PAYLOAD_SCHEMA: Final = "agency.operator/v1"
AGENCY_ATOM_PAYLOAD_SCHEMA: Final = "agency.atom/v1"
AGENCY_SOURCE_MAP_SCHEMA: Final = "agency.source-map/v1"
AGENCY_IDENTITY_SCHEMA: Final = "agency.identity/v1"
AGENCY_EVIDENCE_CONTRACT_SCHEMA: Final = "agency.evidence-contract/v1"

AGENT_SORT: Final = atomic_sort("Agent")
ACTION_SORT: Final = atomic_sort("Action")
TIME_SORT: Final = atomic_sort("Time")
GOAL_SORT: Final = atomic_sort("Goal")
PROPOSITION_SORT: Final = atomic_sort("Proposition")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "agency.unexpected_token"
CODE_TRAILING_INPUT: Final = "agency.trailing_input"
CODE_EMPTY_INPUT: Final = "agency.empty_input"
CODE_PARSE_DEPTH: Final = "agency.parse_depth_exceeded"
CODE_UNBALANCED: Final = "agency.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "agency.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "agency.unknown_character"
CODE_PROFILE_REQUIRED: Final = "agency.profile_required"
CODE_PROFILE_MISMATCH: Final = "agency.profile_mismatch"
CODE_OVERLOADED_SYMBOL: Final = "agency.overloaded_symbol"
CODE_OPERATOR_FORBIDDEN: Final = "agency.operator_forbidden"
CODE_AGENT_REQUIRED: Final = "agency.agent_required"
CODE_AGENT_FORBIDDEN: Final = "agency.agent_forbidden"
CODE_TIME_REQUIRED: Final = "agency.time_required"
CODE_TIME_FORBIDDEN: Final = "agency.time_forbidden"
CODE_ARITY_MISMATCH: Final = "agency.arity_mismatch"
CODE_ROUND_TRIP: Final = "agency.round_trip_failed"
CODE_FAMILY_CONFLATION: Final = "agency.family_conflation_rejected"
CODE_DCEC_HOOK_REQUIRED: Final = "agency.dcec_hook_required"
CODE_FRAME_REQUIRED: Final = "agency.frame_required"
CODE_INTROSPECTION_REQUIRED: Final = "agency.introspection_required"

_ALL_AGENCY_CODES: Final[frozenset[str]] = frozenset(
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
        CODE_OVERLOADED_SYMBOL,
        CODE_OPERATOR_FORBIDDEN,
        CODE_AGENT_REQUIRED,
        CODE_AGENT_FORBIDDEN,
        CODE_TIME_REQUIRED,
        CODE_TIME_FORBIDDEN,
        CODE_ARITY_MISMATCH,
        CODE_ROUND_TRIP,
        CODE_FAMILY_CONFLATION,
        CODE_DCEC_HOOK_REQUIRED,
        CODE_FRAME_REQUIRED,
        CODE_INTROSPECTION_REQUIRED,
    }
)

# Connectives.
_NOT_OPS: Final[frozenset[str]] = frozenset({"not", "¬", "~", "!"})
_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&"})
_OR_OPS: Final[frozenset[str]] = frozenset({"or", "∨", "||"})
_IMPLIES_OPS: Final[frozenset[str]] = frozenset(
    {"implies", "→", "⇒", "=>", "->", "==>"}
)
_IFF_OPS: Final[frozenset[str]] = frozenset({"iff", "↔", "⇔", "<=>", "<->"})
_TRUE_OPS: Final[frozenset[str]] = frozenset({"true", "⊤"})
_FALSE_OPS: Final[frozenset[str]] = frozenset({"false", "⊥"})

# Multi-letter attitude / agency operators.
_BELIEVES_WORDS: Final[frozenset[str]] = frozenset(
    {"believes", "believe", "belief"}
)
_KNOWS_WORDS: Final[frozenset[str]] = frozenset({"knows", "know", "knowledge"})
_DESIRES_WORDS: Final[frozenset[str]] = frozenset(
    {"desires", "desire", "wants", "want"}
)
_INTENDS_WORDS: Final[frozenset[str]] = frozenset(
    {"intends", "intend", "intends_to", "intention"}
)
_GOAL_WORDS: Final[frozenset[str]] = frozenset({"goals", "goal"})
_DOES_WORDS: Final[frozenset[str]] = frozenset(
    {"does", "do", "achieves", "achieve", "acts", "act"}
)

# Classic single-letter overloaded forms (require profile admission).
_CLASSIC_LETTERS: Final[Mapping[str, str]] = {
    "b": "believes",
    "k": "knows",
    "d": "desires",
    "i": "intends",
}

_ATTITUDE_CANON: Final[Mapping[str, str]] = {
    **{w: "believes" for w in _BELIEVES_WORDS},
    **{w: "knows" for w in _KNOWS_WORDS},
    **{w: "desires" for w in _DESIRES_WORDS},
    **{w: "intends" for w in _INTENDS_WORDS},
    **{w: "goal" for w in _GOAL_WORDS},
    **{w: "does" for w in _DOES_WORDS},
    **_CLASSIC_LETTERS,
}

_AGENCY_ATOMS: Final[frozenset[str]] = frozenset(
    {"agent", "action", "goal", "happens", "holds_at", "initiates", "terminates"}
)

# DCEC-only surface constructs — never admitted as native BDI/agency atoms
# without an explicit DCECImporterHook.
_DCEC_SURFACE_ATOMS: Final[frozenset[str]] = frozenset(
    {"happens", "holds_at", "holdsat", "holds", "initiates", "terminates", "releases", "clipped"}
)

_AGENCY_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "or",
    "not",
    "implies",
    "iff",
    "true",
    "false",
    "believes",
    "believe",
    "belief",
    "knows",
    "know",
    "knowledge",
    "desires",
    "desire",
    "wants",
    "want",
    "intends",
    "intend",
    "intends_to",
    "intention",
    "goals",
    "goal",
    "does",
    "do",
    "achieves",
    "achieve",
    "acts",
    "act",
    "agent",
    "action",
    "happens",
    "holds_at",
    "holds",
    "initiates",
    "terminates",
    "releases",
    "clipped",
)


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class AgencyFamilyKind(str, Enum):
    """Declared agency/BDI family fragment.

    ``DCEC`` is intentionally absent: DCEC is a separate family reached only
    through :class:`DCECImporterHook`.
    """

    BDI = "bdi"
    EPISTEMIC_TEMPORAL = "epistemic_temporal"
    AGENCY = "agency"
    INTENTION = "intention_agency"


class AttitudeKind(str, Enum):
    """BDI / epistemic / agency attitude class."""

    BELIEVES = "believes"
    KNOWS = "knows"
    DESIRES = "desires"
    INTENDS = "intends"
    GOAL = "goal"
    DOES = "does"


class AccessibilityFrame(str, Enum):
    """Named accessibility / frame packages for attitude modalities.

    Frame assumptions are profile fields — never inferred from spelling.
    """

    NONE = "none"
    K = "k"  # no special constraints
    D = "d"  # serial (consistency)
    T = "t"  # reflexive (truth)
    KD45 = "kd45"  # standard doxastic (belief)
    S4 = "s4"  # reflexive + transitive
    S5 = "s5"  # epistemic knowledge standard


class IntrospectionAssumption(str, Enum):
    """Explicit positive/negative introspection package.

    Introspection is never inferred; profiles must declare one of these.
    """

    NONE = "none"
    POSITIVE = "positive"  # Aφ → AAφ
    NEGATIVE = "negative"  # ¬Aφ → A¬Aφ
    POSITIVE_AND_NEGATIVE = "positive_and_negative"
    FULL = "full"  # alias-style package: pos + neg (same as POSITIVE_AND_NEGATIVE)


_FRAME_PROPERTIES: Final[Mapping[AccessibilityFrame, Mapping[str, bool]]] = {
    AccessibilityFrame.NONE: {
        "serial": False,
        "reflexive": False,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    AccessibilityFrame.K: {
        "serial": False,
        "reflexive": False,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    AccessibilityFrame.D: {
        "serial": True,
        "reflexive": False,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    AccessibilityFrame.T: {
        "serial": True,
        "reflexive": True,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    },
    AccessibilityFrame.KD45: {
        "serial": True,
        "reflexive": False,
        "transitive": True,
        "euclidean": True,
        "symmetric": False,
    },
    AccessibilityFrame.S4: {
        "serial": True,
        "reflexive": True,
        "transitive": True,
        "euclidean": False,
        "symmetric": False,
    },
    AccessibilityFrame.S5: {
        "serial": True,
        "reflexive": True,
        "transitive": True,
        "euclidean": True,
        "symmetric": True,
    },
}

_INTROSPECTION_FLAGS: Final[Mapping[IntrospectionAssumption, Mapping[str, bool]]] = {
    IntrospectionAssumption.NONE: {
        "positive_introspection": False,
        "negative_introspection": False,
    },
    IntrospectionAssumption.POSITIVE: {
        "positive_introspection": True,
        "negative_introspection": False,
    },
    IntrospectionAssumption.NEGATIVE: {
        "positive_introspection": False,
        "negative_introspection": True,
    },
    IntrospectionAssumption.POSITIVE_AND_NEGATIVE: {
        "positive_introspection": True,
        "negative_introspection": True,
    },
    IntrospectionAssumption.FULL: {
        "positive_introspection": True,
        "negative_introspection": True,
    },
}

# Attitudes admitted per family.
_FAMILY_ATTITUDES: Final[Mapping[AgencyFamilyKind, frozenset[str]]] = {
    AgencyFamilyKind.BDI: frozenset(
        {"believes", "desires", "intends", "goal"}
    ),
    AgencyFamilyKind.EPISTEMIC_TEMPORAL: frozenset({"knows", "believes"}),
    AgencyFamilyKind.AGENCY: frozenset({"does", "goal", "intends"}),
    AgencyFamilyKind.INTENTION: frozenset({"intends", "goal", "desires"}),
}

_FAMILY_ID_MAP: Final[Mapping[AgencyFamilyKind, str]] = {
    AgencyFamilyKind.BDI: BDI_FAMILY_ID,
    AgencyFamilyKind.EPISTEMIC_TEMPORAL: EPISTEMIC_TEMPORAL_FAMILY_ID,
    AgencyFamilyKind.AGENCY: AGENCY_FAMILY_ID,
    AgencyFamilyKind.INTENTION: INTENTION_FAMILY_ID,
}


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    IFF = 10
    IMPLIES = 20
    OR = 30
    AND = 40
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


# ---------------------------------------------------------------------------
# DCEC importer hook (explicit bridge; never conflates families)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DCECImporterHook:
    """Explicit DCEC importer bridge (``DCECImporterHook@1``).

    This hook documents how agency/BDI surface may *reference* DCEC event-
    calculus constructs without collapsing family identity.  BDI profiles
    never become DCEC profiles; DCEC surface requires this hook to be present
    and enabled.
    """

    hook_id: str = "dcec_importer_default"
    enabled: bool = False
    dcec_profile_id: str = "dcec_default"
    dcec_family_id: str = DCEC_FAMILY_ID
    dcec_profile_interface: str = DCEC_PROFILE_INTERFACE
    admit_event_calculus_surface: bool = False
    preserve_source_family: bool = True
    schema_version: str = DCEC_HOOK_SCHEMA

    interface: ClassVar[str] = DCEC_IMPORTER_HOOK_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hook_id", _require_non_empty_name(self.hook_id, "hook_id")
        )
        object.__setattr__(
            self,
            "dcec_profile_id",
            _require_non_empty_name(self.dcec_profile_id, "dcec_profile_id"),
        )
        dcec_family = str(self.dcec_family_id or "").strip()
        if dcec_family != DCEC_FAMILY_ID:
            raise SyntaxContractError(
                f"DCECImporterHook.dcec_family_id must be {DCEC_FAMILY_ID!r}; "
                f"got {dcec_family!r} (BDI/DCEC conflation rejected)"
            )
        object.__setattr__(self, "dcec_family_id", dcec_family)
        for name in ("enabled", "admit_event_calculus_surface", "preserve_source_family"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")
        if not self.preserve_source_family:
            raise SyntaxContractError(
                "DCECImporterHook.preserve_source_family must be True; "
                "collapsing BDI into DCEC (or vice versa) is rejected"
            )
        if self.schema_version != DCEC_HOOK_SCHEMA:
            raise SyntaxContractError(
                f"unsupported DCECImporterHook schema {self.schema_version!r}"
            )
        if self.enabled and not self.admit_event_calculus_surface:
            raise SyntaxContractError(
                "enabled DCECImporterHook requires admit_event_calculus_surface=True"
            )

    @property
    def admits_dcec_surface(self) -> bool:
        return self.enabled and self.admit_event_calculus_surface

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_event_calculus_surface": self.admit_event_calculus_surface,
            "dcec_family_id": self.dcec_family_id,
            "dcec_profile_id": self.dcec_profile_id,
            "dcec_profile_interface": self.dcec_profile_interface,
            "enabled": self.enabled,
            "hook_id": self.hook_id,
            "interface": self.interface,
            "preserve_source_family": self.preserve_source_family,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DCECImporterHook:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("DCECImporterHook must be a mapping")
        return cls(
            hook_id=str(value.get("hook_id") or "dcec_importer_default"),
            enabled=bool(value.get("enabled", False)),
            dcec_profile_id=str(value.get("dcec_profile_id") or "dcec_default"),
            dcec_family_id=str(value.get("dcec_family_id") or DCEC_FAMILY_ID),
            dcec_profile_interface=str(
                value.get("dcec_profile_interface") or DCEC_PROFILE_INTERFACE
            ),
            admit_event_calculus_surface=bool(
                value.get("admit_event_calculus_surface", False)
            ),
            preserve_source_family=bool(value.get("preserve_source_family", True)),
            schema_version=str(value.get("schema_version") or DCEC_HOOK_SCHEMA),
        )

    @classmethod
    def disabled(cls, *, hook_id: str = "dcec_importer_disabled") -> DCECImporterHook:
        return cls(hook_id=hook_id, enabled=False, admit_event_calculus_surface=False)

    @classmethod
    def enabled_bridge(
        cls,
        *,
        hook_id: str = "dcec_importer_enabled",
        dcec_profile_id: str = "dcec_default",
    ) -> DCECImporterHook:
        return cls(
            hook_id=hook_id,
            enabled=True,
            dcec_profile_id=dcec_profile_id,
            admit_event_calculus_surface=True,
            preserve_source_family=True,
        )


# ---------------------------------------------------------------------------
# AgencyLogicProfile@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgencyLogicProfile:
    """Explicit BDI / epistemic-temporal / agency / intention profile.

    Interface: ``AgencyLogicProfile@1`` (owned by ``AgencyLogicProfiles@1``).

    Agent indices, time indices, accessibility frame, and introspection
    assumptions are **required fields** — never inferred from operator spelling.
    Family identity is always one of the agency/BDI families and is never
    ``dcec``.
    """

    profile_id: str
    family: AgencyFamilyKind | str
    frame: AccessibilityFrame | str
    introspection: IntrospectionAssumption | str
    require_agent_index: bool = True
    require_time_index: bool = False
    allow_time_index: bool = False
    admit_classic_letters: bool = False
    admit_goal_atoms: bool = True
    admit_action_atoms: bool = True
    admit_agent_atoms: bool = True
    dcec_hook: DCECImporterHook | None = None
    schema_version: str = AGENCY_PROFILE_SCHEMA

    interface: ClassVar[str] = AGENCY_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            _require_non_empty_name(self.profile_id, "profile_id"),
        )
        family = _coerce_enum(AgencyFamilyKind, self.family, "family")
        if not isinstance(family, AgencyFamilyKind):
            raise SyntaxContractError(f"unknown family {self.family!r}")
        object.__setattr__(self, "family", family)

        # Hard non-conflation: profile family must never be dcec.
        if str(family.value) == DCEC_FAMILY_ID or str(self.profile_id).casefold() == "dcec":
            raise SyntaxContractError(
                "AgencyLogicProfile family/profile_id must not be 'dcec'; "
                "BDI and DCEC profiles are not conflated "
                f"(use DCECImporterHook for DCEC surface; got family={family!r})"
            )

        frame = _coerce_enum(AccessibilityFrame, self.frame, "frame")
        object.__setattr__(self, "frame", frame)
        intro = _coerce_enum(
            IntrospectionAssumption, self.introspection, "introspection"
        )
        object.__setattr__(self, "introspection", intro)

        for name in (
            "require_agent_index",
            "require_time_index",
            "allow_time_index",
            "admit_classic_letters",
            "admit_goal_atoms",
            "admit_action_atoms",
            "admit_agent_atoms",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise SyntaxContractError(f"{name} must be a boolean")

        if self.require_time_index and not self.allow_time_index:
            raise SyntaxContractError(
                "require_time_index=True requires allow_time_index=True"
            )

        hook = self.dcec_hook
        if isinstance(hook, Mapping):
            hook = DCECImporterHook.from_dict(hook)
        if hook is not None and not isinstance(hook, DCECImporterHook):
            raise SyntaxContractError("dcec_hook must be a DCECImporterHook or None")
        object.__setattr__(self, "dcec_hook", hook)

        if self.schema_version != AGENCY_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported AgencyLogicProfile schema {self.schema_version!r}"
            )

        # Epistemic-temporal profiles must allow time indices and declare
        # explicit frame + introspection (acceptance criterion).
        if family is AgencyFamilyKind.EPISTEMIC_TEMPORAL:
            if not self.allow_time_index:
                raise SyntaxContractError(
                    "epistemic_temporal profiles require allow_time_index=True"
                )
            if frame is AccessibilityFrame.NONE:
                raise SyntaxContractError(
                    "epistemic_temporal profiles require an explicit accessibility frame "
                    "(not 'none')"
                )

    @property
    def family_id(self) -> str:
        family = (
            self.family
            if isinstance(self.family, AgencyFamilyKind)
            else AgencyFamilyKind(str(self.family))
        )
        return _FAMILY_ID_MAP[family]

    @property
    def frame_axioms(self) -> dict[str, bool]:
        frame = (
            self.frame
            if isinstance(self.frame, AccessibilityFrame)
            else AccessibilityFrame(str(self.frame))
        )
        return dict(_FRAME_PROPERTIES[frame])

    @property
    def introspection_flags(self) -> dict[str, bool]:
        intro = (
            self.introspection
            if isinstance(self.introspection, IntrospectionAssumption)
            else IntrospectionAssumption(str(self.introspection))
        )
        return dict(_INTROSPECTION_FLAGS[intro])

    @property
    def admitted_attitudes(self) -> frozenset[str]:
        family = (
            self.family
            if isinstance(self.family, AgencyFamilyKind)
            else AgencyFamilyKind(str(self.family))
        )
        return _FAMILY_ATTITUDES[family]

    @property
    def dcec_surface_admitted(self) -> bool:
        return self.dcec_hook is not None and self.dcec_hook.admits_dcec_surface

    @property
    def semantic_identity(self) -> dict[str, Any]:
        """Stable identity fragment — includes agent/time/frame/introspection."""

        family = (
            self.family.value
            if isinstance(self.family, AgencyFamilyKind)
            else str(self.family)
        )
        frame = (
            self.frame.value
            if isinstance(self.frame, AccessibilityFrame)
            else str(self.frame)
        )
        intro = (
            self.introspection.value
            if isinstance(self.introspection, IntrospectionAssumption)
            else str(self.introspection)
        )
        payload: dict[str, Any] = {
            "admit_classic_letters": self.admit_classic_letters,
            "allow_time_index": self.allow_time_index,
            "family": family,
            "family_id": self.family_id,
            "frame": frame,
            "frame_axioms": self.frame_axioms,
            "introspection": intro,
            "introspection_flags": self.introspection_flags,
            "profile_id": self.profile_id,
            "require_agent_index": self.require_agent_index,
            "require_time_index": self.require_time_index,
            # Explicit non-conflation marker.
            "dcec_conflated": False,
            "dcec_family_id": DCEC_FAMILY_ID,
            "is_dcec_profile": False,
        }
        if self.dcec_hook is not None:
            payload["dcec_hook"] = {
                "enabled": self.dcec_hook.enabled,
                "hook_id": self.dcec_hook.hook_id,
                "dcec_family_id": self.dcec_hook.dcec_family_id,
                "dcec_profile_id": self.dcec_hook.dcec_profile_id,
                "preserve_source_family": self.dcec_hook.preserve_source_family,
            }
        return payload

    def admits_attitude(self, attitude: str) -> bool:
        return attitude.casefold() in self.admitted_attitudes

    def to_dict(self) -> dict[str, Any]:
        family = (
            self.family.value
            if isinstance(self.family, AgencyFamilyKind)
            else str(self.family)
        )
        frame = (
            self.frame.value
            if isinstance(self.frame, AccessibilityFrame)
            else str(self.frame)
        )
        intro = (
            self.introspection.value
            if isinstance(self.introspection, IntrospectionAssumption)
            else str(self.introspection)
        )
        return {
            "admit_action_atoms": self.admit_action_atoms,
            "admit_agent_atoms": self.admit_agent_atoms,
            "admit_classic_letters": self.admit_classic_letters,
            "admit_goal_atoms": self.admit_goal_atoms,
            "allow_time_index": self.allow_time_index,
            "dcec_hook": self.dcec_hook.to_dict() if self.dcec_hook else None,
            "family": family,
            "frame": frame,
            "interface": self.interface,
            "introspection": intro,
            "profile_id": self.profile_id,
            "require_agent_index": self.require_agent_index,
            "require_time_index": self.require_time_index,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgencyLogicProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("AgencyLogicProfile must be a mapping")
        hook_raw = value.get("dcec_hook")
        hook: DCECImporterHook | None
        if hook_raw is None:
            hook = None
        elif isinstance(hook_raw, DCECImporterHook):
            hook = hook_raw
        else:
            hook = DCECImporterHook.from_dict(hook_raw)  # type: ignore[arg-type]
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            family=value.get("family", AgencyFamilyKind.BDI.value),
            frame=value.get("frame", AccessibilityFrame.KD45.value),
            introspection=value.get(
                "introspection", IntrospectionAssumption.POSITIVE_AND_NEGATIVE.value
            ),
            require_agent_index=bool(value.get("require_agent_index", True)),
            require_time_index=bool(value.get("require_time_index", False)),
            allow_time_index=bool(value.get("allow_time_index", False)),
            admit_classic_letters=bool(value.get("admit_classic_letters", False)),
            admit_goal_atoms=bool(value.get("admit_goal_atoms", True)),
            admit_action_atoms=bool(value.get("admit_action_atoms", True)),
            admit_agent_atoms=bool(value.get("admit_agent_atoms", True)),
            dcec_hook=hook,
            schema_version=str(value.get("schema_version") or AGENCY_PROFILE_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Profile factories
# ---------------------------------------------------------------------------


def profile_bdi(
    *,
    profile_id: str = "bdi_default",
    frame: AccessibilityFrame | str = AccessibilityFrame.KD45,
    introspection: IntrospectionAssumption | str = (
        IntrospectionAssumption.POSITIVE_AND_NEGATIVE
    ),
    require_agent_index: bool = True,
    admit_classic_letters: bool = False,
    dcec_hook: DCECImporterHook | None = None,
) -> AgencyLogicProfile:
    """Standard BDI profile (belief/desire/intention) — **not** DCEC."""

    return AgencyLogicProfile(
        profile_id=profile_id,
        family=AgencyFamilyKind.BDI,
        frame=frame,
        introspection=introspection,
        require_agent_index=require_agent_index,
        require_time_index=False,
        allow_time_index=False,
        admit_classic_letters=admit_classic_letters,
        admit_goal_atoms=True,
        admit_action_atoms=False,
        admit_agent_atoms=True,
        dcec_hook=dcec_hook or DCECImporterHook.disabled(),
    )


def profile_epistemic_temporal(
    *,
    profile_id: str = "epistemic_temporal_default",
    frame: AccessibilityFrame | str = AccessibilityFrame.S5,
    introspection: IntrospectionAssumption | str = IntrospectionAssumption.FULL,
    require_agent_index: bool = True,
    require_time_index: bool = True,
    admit_classic_letters: bool = False,
    dcec_hook: DCECImporterHook | None = None,
) -> AgencyLogicProfile:
    """Epistemic-temporal profile: knowledge/belief with agent + time indices."""

    return AgencyLogicProfile(
        profile_id=profile_id,
        family=AgencyFamilyKind.EPISTEMIC_TEMPORAL,
        frame=frame,
        introspection=introspection,
        require_agent_index=require_agent_index,
        require_time_index=require_time_index,
        allow_time_index=True,
        admit_classic_letters=admit_classic_letters,
        admit_goal_atoms=False,
        admit_action_atoms=False,
        admit_agent_atoms=True,
        dcec_hook=dcec_hook or DCECImporterHook.disabled(),
    )


def profile_agency(
    *,
    profile_id: str = "agency_default",
    frame: AccessibilityFrame | str = AccessibilityFrame.D,
    introspection: IntrospectionAssumption | str = IntrospectionAssumption.NONE,
    require_agent_index: bool = True,
    allow_time_index: bool = True,
    require_time_index: bool = False,
    admit_classic_letters: bool = False,
    dcec_hook: DCECImporterHook | None = None,
) -> AgencyLogicProfile:
    """Agency profile: agents, actions, goals, does/achieves."""

    return AgencyLogicProfile(
        profile_id=profile_id,
        family=AgencyFamilyKind.AGENCY,
        frame=frame,
        introspection=introspection,
        require_agent_index=require_agent_index,
        require_time_index=require_time_index,
        allow_time_index=allow_time_index,
        admit_classic_letters=admit_classic_letters,
        admit_goal_atoms=True,
        admit_action_atoms=True,
        admit_agent_atoms=True,
        dcec_hook=dcec_hook or DCECImporterHook.disabled(),
    )


def profile_intention(
    *,
    profile_id: str = "intention_agency_default",
    frame: AccessibilityFrame | str = AccessibilityFrame.D,
    introspection: IntrospectionAssumption | str = IntrospectionAssumption.POSITIVE,
    require_agent_index: bool = True,
    admit_classic_letters: bool = False,
    dcec_hook: DCECImporterHook | None = None,
) -> AgencyLogicProfile:
    """Intention-agency profile (Bratman-style intention focus)."""

    return AgencyLogicProfile(
        profile_id=profile_id,
        family=AgencyFamilyKind.INTENTION,
        frame=frame,
        introspection=introspection,
        require_agent_index=require_agent_index,
        require_time_index=False,
        allow_time_index=False,
        admit_classic_letters=admit_classic_letters,
        admit_goal_atoms=True,
        admit_action_atoms=False,
        admit_agent_atoms=True,
        dcec_hook=dcec_hook or DCECImporterHook.disabled(),
    )


def agency_semantic_identity(
    node: LogicNode,
    profile: AgencyLogicProfile,
) -> dict[str, Any]:
    """Stable semantic identity fragment for an agency formula under *profile*."""

    return {
        "family": profile.family_id,
        "node_kind": (
            node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
        ),
        "profile": profile.semantic_identity,
    }


def reject_bdi_dcec_conflation(
    *,
    bdi_family: str,
    dcec_family: str = DCEC_FAMILY_ID,
) -> None:
    """Fail closed if a caller attempts to treat BDI and DCEC as the same family."""

    if str(bdi_family).casefold() == str(dcec_family).casefold():
        raise SyntaxContractError(
            f"BDI/DCEC family conflation rejected: {bdi_family!r} == {dcec_family!r}"
        )
    if str(bdi_family).casefold() == DCEC_FAMILY_ID:
        raise SyntaxContractError(
            "BDI family identity must not be 'dcec'; use DCECImporterHook"
        )


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgencyParseResult:
    """Typed result of a canonical agency/BDI parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: AgencyLogicProfile | None = None
    schema_version: str = AGENCY_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = AGENCY_LOGIC_PROFILES_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)


class AgencyParseError(SyntaxContractError):
    """Raised by raising helpers when an agency parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: AgencyParseResult | None = None,
    ) -> None:
        super().__init__(message)
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
        diagnostic_id=f"diag:agency:{code.replace('.', '-')}",
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

    def eof_range(self) -> SourceRange:
        return self.document.full_range()


# ---------------------------------------------------------------------------
# Parser engine
# ---------------------------------------------------------------------------


class _AgencyParserEngine:
    """Recursive-descent agency/BDI parser with explicit agent/time indices."""

    def __init__(
        self,
        *,
        document: SourceDocument,
        tokens: Sequence[LogicToken],
        profile: AgencyLogicProfile,
        limits: ParseLimits,
        expression_id: str,
    ) -> None:
        self.document = document
        self.cursor = _Cursor(tokens, document)
        self.profile = profile
        self.limits = limits
        self.expression_id = expression_id
        self._counter = 0

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
                    message="empty agency/BDI input is rejected",
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
            return root, ()
        except _ParseFail as error:
            return None, (error.diagnostic,)

    def _parse_formula(self) -> LogicNode:
        self._enter()
        try:
            return self._parse_iff()
        finally:
            self._leave()

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
        op = self.cursor.match_any(_IMPLIES_OPS)
        if op is None:
            return left
        right = self._parse_formula()  # right-assoc
        span = self.cursor.range_span(
            left.range or op.range,
            right.range or op.range,
        )
        return LogicNode(
            node_id=self._nid("imp"),
            kind=NodeKind.IMPLIES,
            sort=BOOL_SORT,
            arguments=(left, right),
            range=span,
            metadata={
                "associativity": "right",
                "schema_version": "agency.implies/v1",
            },
        )

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
        attitude = self._match_attitude_operator()
        if attitude is not None:
            op_token, operator, agent, time = attitude
            self._enter()
            try:
                body = self._parse_unary()
            finally:
                self._leave()
            span = self.cursor.range_span(
                op_token.range, body.range or op_token.range
            )
            return self._mk_attitude(
                operator,
                body=body,
                agent=agent,
                time=time,
                span=span,
            )

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

    def _looks_like_operator_use(self) -> bool:
        # Caller has not advanced past the operator token yet; peek the next
        # token after the current attitude word / letter.
        nxt = self.cursor.peek(1)
        if nxt.lexeme in {"[", "@", "(", "¬", "~", "!"}:
            return True
        if nxt.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
            TokenKind.NUMBER.value,
        }:
            return True
        if nxt.lexeme.casefold() in _NOT_OPS:
            return True
        return False

    def _match_attitude_operator(
        self,
    ) -> tuple[LogicToken, str, str | None, str | None] | None:
        token = self.cursor.current()
        if token.kind == TokenKind.EOF.value:
            return None
        raw = token.lexeme
        folded = raw.casefold()

        # Classic single-letter forms.
        if folded in _CLASSIC_LETTERS and len(raw) == 1:
            if not self._looks_like_operator_use():
                return None
            if not self.profile.admit_classic_letters:
                raise _ParseFail(
                    _diag(
                        code=CODE_OVERLOADED_SYMBOL,
                        message=(
                            f"overloaded attitude symbol {raw!r} requires "
                            "admit_classic_letters=True or multi-letter form "
                            "(believes/knows/desires/intends)"
                        ),
                        range=token.range,
                        remediation=(
                            "Write multi-letter attitude words, or set "
                            "admit_classic_letters=True on the profile"
                        ),
                        metadata={"operator": raw},
                    )
                )
            canon = _CLASSIC_LETTERS[folded]
            self.cursor.advance()
            return self._consume_attitude_indices(token, canon)

        # Multi-letter attitude words.
        if folded in _ATTITUDE_CANON and folded not in _CLASSIC_LETTERS:
            # Distinguishing goal(...) atom from goal[agent] attitude:
            # if next token is '(' treat as atom (handled in atomic).
            if folded in {"goal", "goals"} and self.cursor.peek(1).lexeme == "(":
                return None
            if folded in {"agent", "action"}:
                return None
            if not self._looks_like_operator_use() and self.cursor.peek(1).lexeme != "[":
                # Bare keyword used as proposition — allow as atom.
                if self.cursor.peek(1).kind == TokenKind.EOF.value:
                    return None
                if self.cursor.peek(1).lexeme in {
                    "and",
                    "or",
                    "implies",
                    "iff",
                    ")",
                    ",",
                } or self.cursor.peek(1).lexeme.casefold() in {
                    "and",
                    "or",
                    "implies",
                    "iff",
                }:
                    return None
            canon = _ATTITUDE_CANON[folded]
            self.cursor.advance()
            return self._consume_attitude_indices(token, canon)

        return None

    def _consume_attitude_indices(
        self,
        op_token: LogicToken,
        operator: str,
    ) -> tuple[LogicToken, str, str | None, str | None]:
        if not self.profile.admits_attitude(operator):
            raise _ParseFail(
                _diag(
                    code=CODE_OPERATOR_FORBIDDEN,
                    message=(
                        f"operator {operator!r} is not admitted by "
                        f"{self.profile.family_id!r} profile "
                        f"{self.profile.profile_id!r}"
                    ),
                    range=op_token.range,
                    remediation=(
                        f"Use a profile that admits {operator!r}; admitted="
                        f"{sorted(self.profile.admitted_attitudes)}"
                    ),
                    metadata={
                        "operator": operator,
                        "family": self.profile.family_id,
                        "admitted": sorted(self.profile.admitted_attitudes),
                    },
                )
            )

        agent: str | None = None
        time: str | None = None

        if self.cursor.match_lexeme("[") is not None:
            agent_tok = self.cursor.expect_ident()
            agent = agent_tok.lexeme
            self.cursor.expect_lexeme("]", code=CODE_UNBALANCED)
        elif self.profile.require_agent_index:
            raise _ParseFail(
                _diag(
                    code=CODE_AGENT_REQUIRED,
                    message=(
                        f"operator {operator!r} requires an agent index "
                        f"[agent] under profile {self.profile.profile_id!r}"
                    ),
                    range=op_token.range,
                    remediation=f"Write e.g. {operator}[alice] p",
                    metadata={
                        "operator": operator,
                        "require_agent_index": True,
                    },
                )
            )

        if agent is None and not self.profile.require_agent_index:
            # Agent-free attitudes only when profile explicitly allows it.
            pass
        elif agent is not None and not self.profile.require_agent_index:
            # Still allowed — agent index is optional when not required.
            pass

        if self.cursor.match_lexeme("@") is not None:
            if not self.profile.allow_time_index:
                raise _ParseFail(
                    _diag(
                        code=CODE_TIME_FORBIDDEN,
                        message=(
                            f"time index is not admitted by profile "
                            f"{self.profile.profile_id!r} "
                            f"(family={self.profile.family_id!r})"
                        ),
                        range=op_token.range,
                        remediation=(
                            "Use profile_epistemic_temporal or profile_agency "
                            "with allow_time_index=True"
                        ),
                        metadata={
                            "operator": operator,
                            "allow_time_index": False,
                        },
                    )
                )
            time_tok = self.cursor.current()
            if time_tok.kind == TokenKind.NUMBER.value:
                self.cursor.advance()
                time = time_tok.lexeme
            else:
                time_tok = self.cursor.expect_ident()
                time = time_tok.lexeme
        elif self.profile.require_time_index:
            raise _ParseFail(
                _diag(
                    code=CODE_TIME_REQUIRED,
                    message=(
                        f"operator {operator!r} requires a time index @t under "
                        f"profile {self.profile.profile_id!r}"
                    ),
                    range=op_token.range,
                    remediation=f"Write e.g. {operator}[alice]@t0 p",
                    metadata={
                        "operator": operator,
                        "require_time_index": True,
                    },
                )
            )

        return op_token, operator, agent, time

    def _mk_attitude(
        self,
        operator: str,
        *,
        body: LogicNode,
        agent: str | None,
        time: str | None,
        span: SourceRange,
    ) -> LogicNode:
        family_id = self.profile.family_id
        # Defensive non-conflation check at node construction.
        if family_id == DCEC_FAMILY_ID:
            raise _ParseFail(
                _diag(
                    code=CODE_FAMILY_CONFLATION,
                    message=(
                        "refusing to emit DCEC family identity from agency/BDI "
                        "parser; BDI and DCEC profiles are not conflated"
                    ),
                    range=span,
                )
            )
        frame = (
            self.profile.frame.value
            if isinstance(self.profile.frame, AccessibilityFrame)
            else str(self.profile.frame)
        )
        intro = (
            self.profile.introspection.value
            if isinstance(self.profile.introspection, IntrospectionAssumption)
            else str(self.profile.introspection)
        )
        payload: dict[str, Any] = {
            "attitude": operator,
            "family": family_id,
            "frame": frame,
            "frame_axioms": self.profile.frame_axioms,
            "introspection": intro,
            "introspection_flags": self.profile.introspection_flags,
            "kind": operator,
            "profile_id": self.profile.profile_id,
            "require_agent_index": self.profile.require_agent_index,
            "require_time_index": self.profile.require_time_index,
            "schema_version": AGENCY_OPERATOR_PAYLOAD_SCHEMA,
            "is_dcec": False,
        }
        if agent is not None:
            payload["agent"] = agent
            payload["agent_indexed"] = True
        else:
            payload["agent_indexed"] = False
        if time is not None:
            payload["time"] = time
            payload["time_indexed"] = True
        else:
            payload["time_indexed"] = False

        features = [f"agency.{operator}", f"agency.family.{family_id}"]
        if agent is not None:
            features.append("agency.agent_indexed")
        if time is not None:
            features.append("agency.time_indexed")
        features.append(f"agency.frame.{frame}")
        features.append(f"agency.introspection.{intro}")

        return mk_extension(
            self._nid(operator),
            family=family_id,
            profile=self.profile.profile_id,
            features=tuple(features),
            payload_schema=AGENCY_OPERATOR_PAYLOAD_SCHEMA,
            payload=payload,
            children=(body,),
            range=span,
        )

    def _parse_atomic(self) -> LogicNode:
        token = self.cursor.current()
        if token.lexeme in _TRUE_OPS or token.lexeme.casefold() == "true":
            self.cursor.advance()
            node = mk_true(self._nid("true"))
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=BOOL_SORT,
                range=token.range,
            )
        if token.lexeme in _FALSE_OPS or token.lexeme.casefold() == "false":
            self.cursor.advance()
            node = mk_false(self._nid("false"))
            return LogicNode(
                node_id=node.node_id,
                kind=node.kind,
                sort=BOOL_SORT,
                range=token.range,
            )
        if token.lexeme == "(":
            self.cursor.advance()
            inner = self._parse_formula()
            self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            return inner

        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            name = token.lexeme
            name_fold = name.casefold()
            self.cursor.advance()
            if self.cursor.current().lexeme == "(":
                self.cursor.advance()
                args = self._parse_term_list()
                end = self.cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                span = self.cursor.range_span(token.range, end.range)
                return self._build_agency_atom(name_fold, name, args, span)
            return mk_predicate(self._nid("prop"), name, (), range=token.range)

        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"unexpected token {token.lexeme!r} in atomic position",
                range=token.range,
            )
        )

    def _parse_term_list(self) -> list[LogicNode]:
        if self.cursor.current().lexeme == ")":
            return []
        terms = [self._parse_term()]
        while self.cursor.match_lexeme(",") is not None:
            terms.append(self._parse_term())
        return terms

    def _parse_term(self) -> LogicNode:
        token = self.cursor.current()
        if token.kind == TokenKind.NUMBER.value:
            self.cursor.advance()
            return LogicNode(
                node_id=self._nid("num"),
                kind=NodeKind.CONSTANT,
                symbol=f"n_{token.lexeme}",
                sort=TIME_SORT,
                range=token.range,
                metadata={"literal": token.lexeme, "sort_hint": "Time"},
            )
        if token.kind in {
            TokenKind.IDENTIFIER.value,
            TokenKind.KEYWORD.value,
        }:
            self.cursor.advance()
            return LogicNode(
                node_id=self._nid("term"),
                kind=NodeKind.CONSTANT,
                symbol=token.lexeme,
                sort=AGENT_SORT,
                range=token.range,
            )
        raise _ParseFail(
            _diag(
                code=CODE_UNEXPECTED_TOKEN,
                message=f"expected term; got {token.lexeme!r}",
                range=token.range,
            )
        )

    def _build_agency_atom(
        self,
        name_fold: str,
        surface: str,
        args: list[LogicNode],
        span: SourceRange,
    ) -> LogicNode:
        # DCEC event-calculus surface requires an explicit importer hook.
        if name_fold in _DCEC_SURFACE_ATOMS or name_fold.replace("_", "") in {
            "holdsat",
            "releasedat",
        }:
            if not self.profile.dcec_surface_admitted:
                raise _ParseFail(
                    _diag(
                        code=CODE_DCEC_HOOK_REQUIRED,
                        message=(
                            f"DCEC/event-calculus atom {surface!r} is not a native "
                            f"BDI/agency construct under family "
                            f"{self.profile.family_id!r}; enable DCECImporterHook"
                        ),
                        range=span,
                        remediation=(
                            "Pass dcec_hook=DCECImporterHook.enabled_bridge() on the "
                            "profile, or use event_calculus / legacy DCEC importers"
                        ),
                        metadata={
                            "atom": surface,
                            "family": self.profile.family_id,
                            "dcec_family_id": DCEC_FAMILY_ID,
                            "conflated": False,
                        },
                    )
                )
            # Admitted via hook: still tagged as imported DCEC surface, not BDI.
            return self._mk_dcec_imported_atom(name_fold, args, span)

        if name_fold == "agent":
            if not self.profile.admit_agent_atoms:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message="agent(...) atoms are not admitted by this profile",
                        range=span,
                    )
                )
            if len(args) != 1:
                raise _ParseFail(
                    _diag(
                        code=CODE_ARITY_MISMATCH,
                        message=f"agent expects 1 argument; got {len(args)}",
                        range=span,
                    )
                )
            return self._mk_atom("agent", args, span, arity=1)

        if name_fold == "action":
            if not self.profile.admit_action_atoms:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message="action(...) atoms are not admitted by this profile",
                        range=span,
                    )
                )
            if len(args) not in {2, 3}:
                raise _ParseFail(
                    _diag(
                        code=CODE_ARITY_MISMATCH,
                        message=(
                            f"action expects 2 or 3 arguments "
                            f"(agent, action[, time]); got {len(args)}"
                        ),
                        range=span,
                    )
                )
            return self._mk_atom("action", args, span, arity=len(args))

        if name_fold == "goal":
            if not self.profile.admit_goal_atoms:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message="goal(...) atoms are not admitted by this profile",
                        range=span,
                    )
                )
            if len(args) != 2:
                raise _ParseFail(
                    _diag(
                        code=CODE_ARITY_MISMATCH,
                        message=f"goal expects 2 arguments (agent, goal); got {len(args)}",
                        range=span,
                    )
                )
            return self._mk_atom("goal", args, span, arity=2)

        # Generic predicate application.
        return mk_predicate(
            self._nid("pred"),
            surface,
            tuple(args),
            range=span,
        )

    def _mk_atom(
        self,
        kind: str,
        args: list[LogicNode],
        span: SourceRange,
        *,
        arity: int,
    ) -> LogicNode:
        family_id = self.profile.family_id
        payload: dict[str, Any] = {
            "arity": arity,
            "family": family_id,
            "kind": kind,
            "profile_id": self.profile.profile_id,
            "schema_version": AGENCY_ATOM_PAYLOAD_SCHEMA,
            "is_dcec": False,
        }
        return mk_extension(
            self._nid(kind),
            family=family_id,
            profile=self.profile.profile_id,
            features=(f"agency.atom.{kind}", f"agency.family.{family_id}"),
            payload_schema=AGENCY_ATOM_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(args),
            range=span,
        )

    def _mk_dcec_imported_atom(
        self,
        kind: str,
        args: list[LogicNode],
        span: SourceRange,
    ) -> LogicNode:
        """Emit an imported DCEC atom while preserving both family identities."""

        hook = self.dcec_hook_or_raise(span)
        # Source family stays agency/BDI; imported family is dcec.
        payload: dict[str, Any] = {
            "imported_family": DCEC_FAMILY_ID,
            "imported_profile_id": hook.dcec_profile_id,
            "kind": kind,
            "profile_id": self.profile.profile_id,
            "schema_version": AGENCY_ATOM_PAYLOAD_SCHEMA,
            "source_family": self.profile.family_id,
            "is_dcec_import": True,
            "is_dcec": False,  # source is not DCEC
            "hook_id": hook.hook_id,
            "preserve_source_family": hook.preserve_source_family,
        }
        return mk_extension(
            self._nid(f"dcec_import_{kind}"),
            # Family remains the source agency family — not dcec.
            family=self.profile.family_id,
            profile=self.profile.profile_id,
            features=(
                f"agency.dcec_import.{kind}",
                f"agency.family.{self.profile.family_id}",
                f"agency.imported_family.{DCEC_FAMILY_ID}",
            ),
            payload_schema=AGENCY_ATOM_PAYLOAD_SCHEMA,
            payload=payload,
            children=tuple(args),
            range=span,
        )

    def dcec_hook_or_raise(self, span: SourceRange) -> DCECImporterHook:
        hook = self.profile.dcec_hook
        if hook is None or not hook.admits_dcec_surface:
            raise _ParseFail(
                _diag(
                    code=CODE_DCEC_HOOK_REQUIRED,
                    message="DCECImporterHook is required for DCEC surface",
                    range=span,
                )
            )
        return hook


# ---------------------------------------------------------------------------
# Printer
# ---------------------------------------------------------------------------


class AgencyPrinter:
    """Print agency/BDI ASTs back to controlled surface text."""

    def __init__(self, *, style: str = PrintStyle.ASCII) -> None:
        self.style = style

    def print(self, node: LogicNode | TypedExpression) -> str:
        if isinstance(node, TypedExpression):
            node = node.root
        return self._print_node(node, _Prec.BOTTOM)

    def _print_node(self, node: LogicNode, prec: _Prec) -> str:
        kind = node.kind
        if kind is NodeKind.TRUE or kind == NodeKind.TRUE.value:
            return "true" if self.style == PrintStyle.ASCII else "⊤"
        if kind is NodeKind.FALSE or kind == NodeKind.FALSE.value:
            return "false" if self.style == PrintStyle.ASCII else "⊥"
        if kind is NodeKind.NOT or kind == NodeKind.NOT.value:
            body = self._print_node(node.arguments[0], _Prec.UNARY)
            op = "not " if self.style == PrintStyle.ASCII else "¬"
            text = f"{op}{body}"
            return text if prec <= _Prec.UNARY else f"({text})"
        if kind is NodeKind.AND or kind == NodeKind.AND.value:
            parts = [self._print_node(c, _Prec.AND) for c in node.arguments]
            op = " and " if self.style == PrintStyle.ASCII else " ∧ "
            text = op.join(parts)
            return text if prec <= _Prec.AND else f"({text})"
        if kind is NodeKind.OR or kind == NodeKind.OR.value:
            parts = [self._print_node(c, _Prec.OR) for c in node.arguments]
            op = " or " if self.style == PrintStyle.ASCII else " ∨ "
            text = op.join(parts)
            return text if prec <= _Prec.OR else f"({text})"
        if kind is NodeKind.IMPLIES or kind == NodeKind.IMPLIES.value:
            left = self._print_node(node.arguments[0], _Prec.IMPLIES)
            right = self._print_node(node.arguments[1], _Prec.IMPLIES)
            op = " implies " if self.style == PrintStyle.ASCII else " → "
            text = f"{left}{op}{right}"
            return text if prec < _Prec.IMPLIES else f"({text})"
        if kind is NodeKind.IFF or kind == NodeKind.IFF.value:
            left = self._print_node(node.arguments[0], _Prec.IFF)
            right = self._print_node(node.arguments[1], _Prec.IFF)
            op = " iff " if self.style == PrintStyle.ASCII else " ↔ "
            text = f"{left}{op}{right}"
            return text if prec <= _Prec.IFF else f"({text})"
        if kind is NodeKind.PREDICATE or kind == NodeKind.PREDICATE.value:
            if not node.arguments:
                return node.symbol or "?"
            args = ", ".join(
                self._print_term(a) for a in node.arguments
            )
            return f"{node.symbol}({args})"
        if kind is NodeKind.CONSTANT or kind == NodeKind.CONSTANT.value:
            return self._print_term(node)
        if kind is NodeKind.EXTENSION or kind == NodeKind.EXTENSION.value:
            return self._print_extension(node, prec)
        return f"/*unknown:{kind}*/"

    def _print_term(self, node: LogicNode) -> str:
        if node.kind is NodeKind.CONSTANT or node.kind == NodeKind.CONSTANT.value:
            sym = node.symbol or "?"
            if sym.startswith("n_") and sym[2:].isdigit():
                return sym[2:]
            return sym
        if node.kind is NodeKind.VARIABLE or node.kind == NodeKind.VARIABLE.value:
            return node.symbol or "?"
        return self._print_node(node, _Prec.ATOM)

    def _print_extension(self, node: LogicNode, prec: _Prec) -> str:
        ext = node.extension
        if ext is None:
            return "/*ext*/"
        payload = dict(ext.payload or {})
        kind = str(payload.get("kind") or payload.get("attitude") or "")
        if payload.get("is_dcec_import"):
            args = ", ".join(self._print_term(c) for c in ext.children)
            return f"{kind}({args})"
        # Agency atoms (agent/action/goal).
        if kind in {"agent", "action", "goal"} and not payload.get("attitude"):
            # Distinguish atom vs attitude: atoms have no formula body as sole child
            # of attitude type; atoms' children are terms only.
            if kind == "agent" or (
                ext.children
                and all(
                    c.kind in {NodeKind.CONSTANT, NodeKind.VARIABLE}
                    or c.kind
                    in {NodeKind.CONSTANT.value, NodeKind.VARIABLE.value}
                    for c in ext.children
                )
            ):
                args = ", ".join(self._print_term(c) for c in ext.children)
                return f"{kind}({args})"
        # Attitude operator.
        agent = payload.get("agent")
        time = payload.get("time")
        body = (
            self._print_node(ext.children[0], _Prec.UNARY)
            if ext.children
            else "true"
        )
        text = kind
        if agent is not None:
            text += f"[{agent}]"
        if time is not None:
            text += f"@{time}"
        text = f"{text} {body}"
        return text if prec <= _Prec.UNARY else f"({text})"


# ---------------------------------------------------------------------------
# CST / surface helpers
# ---------------------------------------------------------------------------


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:agency:1",
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
            payload = dict(n.extension.payload or {})
            if "agent" in payload:
                meta["agent"] = payload["agent"]
            if "time" in payload:
                meta["time"] = payload["time"]
            if "frame" in payload:
                meta["frame"] = payload["frame"]
            if "introspection" in payload:
                meta["introspection"] = payload["introspection"]
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
    profile: AgencyLogicProfile,
) -> LogicSignature:
    atoms = _collect_atoms(root)
    if not atoms:
        return LogicSignature(
            signature_id=f"sig:agency:{profile.profile_id}",
            family=profile.family_id,
            profile=profile.profile_id,
            sorts=(),
            symbols=(),
            features=("agency", "propositional"),
        )
    return propositional_signature(
        f"sig:agency:{profile.profile_id}",
        atoms,
        family=profile.family_id,
        profile=profile.profile_id,
    )


def _extract_profile(value: object) -> AgencyLogicProfile | None:
    if value is None:
        return None
    if isinstance(value, AgencyLogicProfile):
        return value
    if isinstance(value, Mapping):
        return AgencyLogicProfile.from_dict(value)
    return None


# ---------------------------------------------------------------------------
# Parser / facade
# ---------------------------------------------------------------------------


class AgencyParser:
    """Notation parser for controlled agency/BDI syntax.

    Interface: ``AgencyLogicProfiles@1``.
    """

    interface: ClassVar[str] = AGENCY_LOGIC_PROFILES_INTERFACE
    notation_id: ClassVar[str] = AGENCY_NOTATION_ID
    notation_version: ClassVar[str] = AGENCY_NOTATION_VERSION

    def __init__(
        self,
        profile: AgencyLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        if profile is not None and not isinstance(profile, AgencyLogicProfile):
            raise SyntaxContractError("profile must be an AgencyLogicProfile")
        self.profile = profile
        self.printer = AgencyPrinter(style=print_style)
        self._lexer = BoundedLexer(keywords=_AGENCY_KEYWORDS)

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("agency_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(
                request.metadata.get("expression_id") or "expr:agency:1"
            ),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: AgencyLogicProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:agency:1",
        expression_id: str = "expr:agency:1",
    ) -> AgencyParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_REQUIRED,
                message=(
                    "AgencyLogicProfile is required; profile-free agency "
                    "parse is rejected"
                ),
                range=document.full_range(),
                remediation=(
                    "Pass profile_bdi(), profile_epistemic_temporal(), "
                    "profile_agency(), or profile_intention()"
                ),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": AGENCY_LOGIC_PROFILES_INTERFACE},
            )
            return AgencyParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )

        if not isinstance(prof, AgencyLogicProfile):
            raise SyntaxContractError("profile must be an AgencyLogicProfile")

        # Non-conflation guard.
        if prof.family_id == DCEC_FAMILY_ID:
            diag = _diag(
                code=CODE_FAMILY_CONFLATION,
                message=(
                    "BDI/agency profile family_id must not be 'dcec'; "
                    "BDI and DCEC profiles are not conflated"
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
                metadata={"interface": AGENCY_LOGIC_PROFILES_INTERFACE},
            )
            return AgencyParseResult(
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
                    diagnostic_id=f"diag:agency:lex:{index + 1}",
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
                metadata={"interface": AGENCY_LOGIC_PROFILES_INTERFACE},
            )
            return AgencyParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        engine = _AgencyParserEngine(
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
                    "interface": AGENCY_LOGIC_PROFILES_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return AgencyParseResult(
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
        identity = agency_semantic_identity(root, prof)
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
                "interface": AGENCY_LOGIC_PROFILES_INTERFACE,
                "expression": expression.to_dict(),
                "notation_id": AGENCY_NOTATION_ID,
                "notation_version": AGENCY_NOTATION_VERSION,
                "printed": printed,
                "profile": prof.to_dict(),
                "semantic_identity": identity,
                "dcec_conflated": False,
            },
        )
        artifact.validate_against(document, limits=bounds)
        return AgencyParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
        )


class AgencyLogicProfiles:
    """Facade for ``AgencyLogicProfiles@1``."""

    interface: ClassVar[str] = AGENCY_LOGIC_PROFILES_INTERFACE

    def __init__(
        self,
        profile: AgencyLogicProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_bdi()
        self.parser = AgencyParser(self.profile, print_style=print_style)
        self.printer = AgencyPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> AgencyParseResult:
        document_id = str(kwargs.pop("document_id", "doc:agency:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:agency:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:agency:1"))
        profile = kwargs.pop("profile", self.profile)
        document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        return self.parser.parse_document(
            document,
            profile=profile,
            mode=mode,
            limits=limits,
            request_id=request_id,
            expression_id=expression_id,
        )

    def parse_text_or_raise(self, text: str, **kwargs: Any) -> TypedExpression:
        result = self.parse_text(text, **kwargs)
        if not result.ok or result.expression is None:
            raise AgencyParseError(
                "agency/BDI parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)


def parse_agency(
    text: str,
    profile: AgencyLogicProfile | None = None,
    **kwargs: Any,
) -> AgencyParseResult:
    """Parse agency/BDI *text* under *profile*."""

    logic = AgencyLogicProfiles(profile or profile_bdi())
    return logic.parse_text(text, profile=profile or logic.profile, **kwargs)


def print_agency(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return AgencyPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: AgencyLogicProfile | None = None,
) -> tuple[AgencyParseResult, AgencyParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_bdi()
    first = parse_agency(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_agency(first.root)
    second = parse_agency(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "AGENCY_LOGIC_PROFILES_INTERFACE",
    "AGENCY_PROFILE_INTERFACE",
    "BDI_PROFILE_INTERFACE",
    "EPISTEMIC_TEMPORAL_PROFILE_INTERFACE",
    "INTENTION_AGENCY_PROFILE_INTERFACE",
    "DCEC_IMPORTER_HOOK_INTERFACE",
    "AGENCY_NOTATION_ID",
    "AGENCY_NOTATION_VERSION",
    "AGENCY_MODULE_VERSION",
    "BDI_FAMILY_ID",
    "EPISTEMIC_TEMPORAL_FAMILY_ID",
    "AGENCY_FAMILY_ID",
    "INTENTION_FAMILY_ID",
    "DCEC_FAMILY_ID",
    "CODE_UNEXPECTED_TOKEN",
    "CODE_TRAILING_INPUT",
    "CODE_EMPTY_INPUT",
    "CODE_PROFILE_REQUIRED",
    "CODE_PROFILE_MISMATCH",
    "CODE_OVERLOADED_SYMBOL",
    "CODE_OPERATOR_FORBIDDEN",
    "CODE_AGENT_REQUIRED",
    "CODE_AGENT_FORBIDDEN",
    "CODE_TIME_REQUIRED",
    "CODE_TIME_FORBIDDEN",
    "CODE_ARITY_MISMATCH",
    "CODE_FAMILY_CONFLATION",
    "CODE_DCEC_HOOK_REQUIRED",
    "CODE_FRAME_REQUIRED",
    "CODE_INTROSPECTION_REQUIRED",
    "PrintStyle",
    "AgencyFamilyKind",
    "AttitudeKind",
    "AccessibilityFrame",
    "IntrospectionAssumption",
    "DCECImporterHook",
    "AgencyLogicProfile",
    "AgencyParseError",
    "AgencyParseResult",
    "AgencyPrinter",
    "AgencyParser",
    "AgencyLogicProfiles",
    "profile_bdi",
    "profile_epistemic_temporal",
    "profile_agency",
    "profile_intention",
    "agency_semantic_identity",
    "reject_bdi_dcec_conflation",
    "parse_agency",
    "print_agency",
    "parse_print_parse",
    "AGENT_SORT",
    "ACTION_SORT",
    "TIME_SORT",
    "GOAL_SORT",
]
