"""Controlled argumentation and nonmonotonic reasoning (LFP2-038).

Interface:

* ``ArgumentationLogic@1`` — parse/print/evaluate for controlled abstract
  argumentation frameworks, bipolar support, priorities, and defeasible /
  nonmonotonic rules under **named** semantic profiles

Owned constructs:

* arguments (``arg`` / ``argument``)
* attacks (``attack``)
* support (``support``) for bipolar frameworks
* priorities (``priority``)
* strict and defeasible rules (``strict`` / ``defeasible``)
* status queries (``status`` / ``query``)

Named semantic profiles (always required; never profile-free):

* ``grounded`` — unique least complete extension; undecided preserved
* ``preferred`` — maximal complete extensions; **multiple** preserved
* ``complete`` — all complete extensions; multiple preserved
* ``stable`` — stable extensions when they exist; multiple preserved
* ``defeasible`` — priority-aware nonmonotonic rule evaluation

Authority ceilings (fail-closed):

* Argumentation / nonmonotonic evaluation is **never** classical entailment.
* Undecided labels and multi-extension outcomes are first-class results and
  must not collapse to classical true/false theorem authority.
* Any attempt to promote AF/defeasible results to classical entailment fails
  closed with an explicit diagnostic.

Grammar (statement conjunction, low → high)::

    framework   ::= statement (('and'|∧|',') statement)*
    statement   ::= 'arg'|'argument' '(' IDENT ')'
                  | 'attack' '(' IDENT ',' IDENT ')'
                  | 'support' '(' IDENT ',' IDENT ')'
                  | 'priority' '(' IDENT (','|'>') IDENT ')'
                  | 'strict' IDENT ':-' body
                  | 'defeasible' IDENT ':-' body
                  | 'status'|'query' '(' IDENT ')'
                  | '(' framework ')'
    body        ::= IDENT (',' IDENT)*

Evidence subset: argument attack support nonmonotonic defeasible semantics.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from itertools import chain, combinations
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

ARGUMENTATION_LOGIC_INTERFACE: Final = "ArgumentationLogic@1"
ARGUMENTATION_PROFILE_INTERFACE: Final = "ArgumentationProfile@1"
NONMONOTONIC_PROFILE_INTERFACE: Final = "NonmonotonicProfile@1"

ARG_NOTATION_ID: Final = "canonical_argumentation"
ARG_NOTATION_VERSION: Final = "1.0.0"
ARG_FAMILY_ID: Final = "argumentation"
NONMONOTONIC_FAMILY_ID: Final = "nonmonotonic_logic"
DEFEASIBLE_FAMILY_ID: Final = "defeasible_logic"
ARG_MODULE_VERSION: Final = "1.0.0"
ARG_TASK_ID: Final = "LFP2-038"

ARG_PARSE_RESULT_SCHEMA: Final = "canonical-argumentation-parse-result/v1"
ARG_PROFILE_SCHEMA: Final = "argumentation-profile/v1"
ARG_EVIDENCE_CONTRACT_SCHEMA: Final = "argumentation.evidence-contract/v1"
ARG_EVALUATION_SCHEMA: Final = "argumentation.evaluation/v1"
ARG_EXTENSION_SET_SCHEMA: Final = "argumentation.extension-set/v1"
ARG_LABELING_SCHEMA: Final = "argumentation.labeling/v1"
ARG_SOURCE_MAP_SCHEMA: Final = "argumentation.source-map/v1"
ARG_LOWERING_RECEIPT_SCHEMA: Final = "argumentation.lowering-receipt/v1"

# Extension payload schemas (versioned family.construct/vN).
ARG_ARGUMENT_PAYLOAD_SCHEMA: Final = "argumentation.argument/v1"
ARG_ATTACK_PAYLOAD_SCHEMA: Final = "argumentation.attack/v1"
ARG_SUPPORT_PAYLOAD_SCHEMA: Final = "argumentation.support/v1"
ARG_PRIORITY_PAYLOAD_SCHEMA: Final = "argumentation.priority/v1"
ARG_STRICT_RULE_PAYLOAD_SCHEMA: Final = "argumentation.strict_rule/v1"
ARG_DEFEASIBLE_RULE_PAYLOAD_SCHEMA: Final = "argumentation.defeasible_rule/v1"
ARG_STATUS_QUERY_PAYLOAD_SCHEMA: Final = "argumentation.status_query/v1"
ARG_AND_PAYLOAD_SCHEMA: Final = "argumentation.conjunction/v1"

ARGUMENT_SORT: Final = atomic_sort("Argument")
RULE_SORT: Final = atomic_sort("Rule")

# Stable namespaced diagnostic codes.
CODE_UNEXPECTED_TOKEN: Final = "argumentation.unexpected_token"
CODE_TRAILING_INPUT: Final = "argumentation.trailing_input"
CODE_EMPTY_INPUT: Final = "argumentation.empty_input"
CODE_PARSE_DEPTH: Final = "argumentation.parse_depth_exceeded"
CODE_UNBALANCED: Final = "argumentation.unbalanced_delimiter"
CODE_LEXER_ERROR: Final = "argumentation.lexer_error"
CODE_UNKNOWN_CHARACTER: Final = "argumentation.unknown_character"
CODE_PROFILE_MISMATCH: Final = "argumentation.profile_mismatch"
CODE_PROFILE_REQUIRED: Final = "argumentation.profile_required"
CODE_ARITY_MISMATCH: Final = "argumentation.arity_mismatch"
CODE_UNKNOWN_ARGUMENT: Final = "argumentation.unknown_argument"
CODE_DUPLICATE_ARGUMENT: Final = "argumentation.duplicate_argument"
CODE_SELF_ATTACK: Final = "argumentation.self_attack"
CODE_UNSUPPORTED_CONSTRUCT: Final = "argumentation.unsupported_construct"
CODE_ROUND_TRIP: Final = "argumentation.round_trip_failed"
CODE_AUTHORITY_CEILING: Final = "argumentation.authority_ceiling"
CODE_PROMOTION_REJECTED: Final = "argumentation.classical_promotion_rejected"
CODE_UNDECIDED_COLLAPSE: Final = "argumentation.undecided_collapse_rejected"
CODE_MULTI_EXTENSION_COLLAPSE: Final = (
    "argumentation.multi_extension_collapse_rejected"
)
CODE_EVALUATION_FAILED: Final = "argumentation.evaluation_failed"
CODE_FRAMEWORK_LIMIT: Final = "argumentation.framework_limit"

_ALL_ARG_CODES: Final[frozenset[str]] = frozenset(
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
        CODE_UNKNOWN_ARGUMENT,
        CODE_DUPLICATE_ARGUMENT,
        CODE_SELF_ATTACK,
        CODE_UNSUPPORTED_CONSTRUCT,
        CODE_ROUND_TRIP,
        CODE_AUTHORITY_CEILING,
        CODE_PROMOTION_REJECTED,
        CODE_UNDECIDED_COLLAPSE,
        CODE_MULTI_EXTENSION_COLLAPSE,
        CODE_EVALUATION_FAILED,
        CODE_FRAMEWORK_LIMIT,
    }
)

_AND_OPS: Final[frozenset[str]] = frozenset({"and", "∧", "&", "&&", ","})

_STATEMENT_ATOMS: Final[frozenset[str]] = frozenset(
    {
        "arg",
        "argument",
        "attack",
        "support",
        "priority",
        "strict",
        "defeasible",
        "status",
        "query",
    }
)

_ARG_KEYWORDS: Final[tuple[str, ...]] = (
    "and",
    "arg",
    "argument",
    "attack",
    "support",
    "priority",
    "strict",
    "defeasible",
    "status",
    "query",
    "true",
    "false",
)

# Controlled enumeration ceiling for preferred/complete/stable search.
_MAX_ARGUMENTS_FOR_ENUM: Final = 16
_MAX_EXTENSIONS_REPORTED: Final = 256


class PrintStyle:
    """Printer surface style."""

    ASCII = "ascii"
    UNICODE = "unicode"


class ArgumentationSemantics(str, Enum):
    """Named argumentation / nonmonotonic semantic profile identity.

    Every evaluation result must name one of these.  There is no anonymous
    or classical default.
    """

    GROUNDED = "grounded"
    PREFERRED = "preferred"
    COMPLETE = "complete"
    STABLE = "stable"
    DEFEASIBLE = "defeasible"


class ArgumentLabel(str, Enum):
    """Three-valued labeling under an AF semantics.

    ``UNDECIDED`` is first-class and must never be promoted to classical
    true/false without an explicit named conversion (which this module
    refuses).
    """

    IN = "in"
    OUT = "out"
    UNDECIDED = "undecided"


class EvidenceSource(str, Enum):
    """Origin of argumentation / nonmonotonic evidence (closed set)."""

    GROUNDED_EVALUATOR = "grounded_evaluator"
    PREFERRED_EVALUATOR = "preferred_evaluator"
    COMPLETE_EVALUATOR = "complete_evaluator"
    STABLE_EVALUATOR = "stable_evaluator"
    DEFEASIBLE_EVALUATOR = "defeasible_evaluator"
    CLASSICAL_SOLVER = "classical_solver"
    NONE = "none"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by argumentation evidence.

    Intentionally non-hierarchical for classical promotion: nonmonotonic /
    AF results never become classical entailment authority.
    """

    NONE = "none"
    ADVISORY = "advisory"
    NONMONOTONIC = "nonmonotonic"
    ARGUMENTATION = "argumentation"
    CLASSICAL_ENTAILMENT = "classical_entailment"


class BoundednessKind(str, Enum):
    """Semantic bound for argumentation evidence."""

    FINITE_FRAMEWORK = "finite_framework"
    RESOURCE_BOUNDED = "resource_bounded"
    UNBOUNDED = "unbounded"


class _Prec(IntEnum):
    """Printer/parenthesization precedence (higher = tighter)."""

    BOTTOM = 0
    AND = 10
    ATOM = 60


# Sources that may never claim classical entailment.
_NON_CLASSICAL_SOURCES: Final[frozenset[EvidenceSource]] = frozenset(
    {
        EvidenceSource.GROUNDED_EVALUATOR,
        EvidenceSource.PREFERRED_EVALUATOR,
        EvidenceSource.COMPLETE_EVALUATOR,
        EvidenceSource.STABLE_EVALUATOR,
        EvidenceSource.DEFEASIBLE_EVALUATOR,
        EvidenceSource.NONE,
    }
)

# Maximum authority each evidence source may claim.
_SOURCE_AUTHORITY_CEILING: Final[Mapping[EvidenceSource, EvidenceAuthority]] = {
    EvidenceSource.NONE: EvidenceAuthority.NONE,
    EvidenceSource.GROUNDED_EVALUATOR: EvidenceAuthority.ARGUMENTATION,
    EvidenceSource.PREFERRED_EVALUATOR: EvidenceAuthority.ARGUMENTATION,
    EvidenceSource.COMPLETE_EVALUATOR: EvidenceAuthority.ARGUMENTATION,
    EvidenceSource.STABLE_EVALUATOR: EvidenceAuthority.ARGUMENTATION,
    EvidenceSource.DEFEASIBLE_EVALUATOR: EvidenceAuthority.NONMONOTONIC,
    # Classical solver path exists only to document the hard ceiling reject.
    EvidenceSource.CLASSICAL_SOLVER: EvidenceAuthority.CLASSICAL_ENTAILMENT,
}

_AUTHORITY_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.NONMONOTONIC: 2,
    EvidenceAuthority.ARGUMENTATION: 2,
    EvidenceAuthority.CLASSICAL_ENTAILMENT: 3,
}

_SEMANTICS_TO_SOURCE: Final[Mapping[ArgumentationSemantics, EvidenceSource]] = {
    ArgumentationSemantics.GROUNDED: EvidenceSource.GROUNDED_EVALUATOR,
    ArgumentationSemantics.PREFERRED: EvidenceSource.PREFERRED_EVALUATOR,
    ArgumentationSemantics.COMPLETE: EvidenceSource.COMPLETE_EVALUATOR,
    ArgumentationSemantics.STABLE: EvidenceSource.STABLE_EVALUATOR,
    ArgumentationSemantics.DEFEASIBLE: EvidenceSource.DEFEASIBLE_EVALUATOR,
}


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArgumentationProfile:
    """Named argumentation / nonmonotonic semantic profile.

    Interface: ``ArgumentationProfile@1`` (and ``NonmonotonicProfile@1`` when
    ``semantics`` is ``defeasible``).

    The profile identity is **always** required for parse and evaluation.
    """

    profile_id: str
    semantics: ArgumentationSemantics | str
    admit_support: bool = True
    admit_priority: bool = True
    admit_defeasible_rules: bool = True
    admit_strict_rules: bool = True
    admit_self_attack: bool = False
    max_arguments: int = _MAX_ARGUMENTS_FOR_ENUM
    schema_version: str = ARG_PROFILE_SCHEMA

    interface: ClassVar[str] = ARGUMENTATION_PROFILE_INTERFACE

    def __post_init__(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "ArgumentationProfile.profile_id is required; "
                "semantics/profile is always named"
            )
        semantics = self.semantics
        if not isinstance(semantics, ArgumentationSemantics):
            try:
                semantics = ArgumentationSemantics(str(semantics))
            except ValueError as error:
                raise SyntaxContractError(
                    f"unknown argumentation semantics {self.semantics!r}; "
                    "profile must name grounded|preferred|complete|stable|defeasible"
                ) from error
            object.__setattr__(self, "semantics", semantics)
        if not isinstance(self.max_arguments, int) or isinstance(
            self.max_arguments, bool
        ):
            raise SyntaxContractError("max_arguments must be an integer")
        if self.max_arguments < 1 or self.max_arguments > 64:
            raise SyntaxContractError(
                f"max_arguments must be in 1..64; got {self.max_arguments}"
            )
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if self.schema_version != ARG_PROFILE_SCHEMA:
            raise SyntaxContractError(
                f"unsupported ArgumentationProfile schema {self.schema_version!r}"
            )

    @property
    def family_id(self) -> str:
        assert isinstance(self.semantics, ArgumentationSemantics)
        if self.semantics is ArgumentationSemantics.DEFEASIBLE:
            return NONMONOTONIC_FAMILY_ID
        return ARG_FAMILY_ID

    @property
    def semantics_name(self) -> str:
        assert isinstance(self.semantics, ArgumentationSemantics)
        return self.semantics.value

    @property
    def is_multi_extension(self) -> bool:
        """Whether this semantics may yield multiple extensions."""

        assert isinstance(self.semantics, ArgumentationSemantics)
        return self.semantics in {
            ArgumentationSemantics.PREFERRED,
            ArgumentationSemantics.COMPLETE,
            ArgumentationSemantics.STABLE,
        }

    @property
    def preserves_undecided(self) -> bool:
        """Whether undecided labels are first-class under this semantics."""

        assert isinstance(self.semantics, ArgumentationSemantics)
        return self.semantics is not ArgumentationSemantics.DEFEASIBLE

    @property
    def semantic_identity(self) -> dict[str, Any]:
        return {
            "admit_defeasible_rules": self.admit_defeasible_rules,
            "admit_priority": self.admit_priority,
            "admit_self_attack": self.admit_self_attack,
            "admit_strict_rules": self.admit_strict_rules,
            "admit_support": self.admit_support,
            "family_id": self.family_id,
            "is_multi_extension": self.is_multi_extension,
            "max_arguments": self.max_arguments,
            "preserves_undecided": self.preserves_undecided,
            "profile_id": self.profile_id,
            "semantics": self.semantics_name,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_defeasible_rules": self.admit_defeasible_rules,
            "admit_priority": self.admit_priority,
            "admit_self_attack": self.admit_self_attack,
            "admit_strict_rules": self.admit_strict_rules,
            "admit_support": self.admit_support,
            "interface": self.interface,
            "max_arguments": self.max_arguments,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "semantics": self.semantics_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArgumentationProfile:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("ArgumentationProfile must be a mapping")
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            semantics=value.get("semantics") or ArgumentationSemantics.GROUNDED.value,
            admit_support=bool(value.get("admit_support", True)),
            admit_priority=bool(value.get("admit_priority", True)),
            admit_defeasible_rules=bool(value.get("admit_defeasible_rules", True)),
            admit_strict_rules=bool(value.get("admit_strict_rules", True)),
            admit_self_attack=bool(value.get("admit_self_attack", False)),
            max_arguments=int(value.get("max_arguments") or _MAX_ARGUMENTS_FOR_ENUM),
            schema_version=str(value.get("schema_version") or ARG_PROFILE_SCHEMA),
        )


def profile_grounded(
    *,
    profile_id: str = "argumentation_grounded",
) -> ArgumentationProfile:
    return ArgumentationProfile(
        profile_id=profile_id,
        semantics=ArgumentationSemantics.GROUNDED,
        admit_support=True,
        admit_priority=True,
        admit_defeasible_rules=False,
        admit_strict_rules=False,
    )


def profile_preferred(
    *,
    profile_id: str = "argumentation_preferred",
) -> ArgumentationProfile:
    return ArgumentationProfile(
        profile_id=profile_id,
        semantics=ArgumentationSemantics.PREFERRED,
        admit_support=True,
        admit_priority=True,
        admit_defeasible_rules=False,
        admit_strict_rules=False,
    )


def profile_complete(
    *,
    profile_id: str = "argumentation_complete",
) -> ArgumentationProfile:
    return ArgumentationProfile(
        profile_id=profile_id,
        semantics=ArgumentationSemantics.COMPLETE,
        admit_support=True,
        admit_priority=True,
        admit_defeasible_rules=False,
        admit_strict_rules=False,
    )


def profile_stable(
    *,
    profile_id: str = "argumentation_stable",
) -> ArgumentationProfile:
    return ArgumentationProfile(
        profile_id=profile_id,
        semantics=ArgumentationSemantics.STABLE,
        admit_support=True,
        admit_priority=True,
        admit_defeasible_rules=False,
        admit_strict_rules=False,
    )


def profile_defeasible(
    *,
    profile_id: str = "nonmonotonic_defeasible",
) -> ArgumentationProfile:
    return ArgumentationProfile(
        profile_id=profile_id,
        semantics=ArgumentationSemantics.DEFEASIBLE,
        admit_support=True,
        admit_priority=True,
        admit_defeasible_rules=True,
        admit_strict_rules=True,
    )


def argumentation_semantic_identity(
    node: LogicNode,
    profile: ArgumentationProfile,
) -> dict[str, Any]:
    """Stable semantic identity including named profile semantics."""

    framework = extract_framework(node)
    return {
        "family": profile.family_id,
        "framework": framework.to_dict(),
        "node_kind": (
            node.kind.value if isinstance(node.kind, NodeKind) else str(node.kind)
        ),
        "profile": profile.semantic_identity,
        "semantics": profile.semantics_name,
    }


# ---------------------------------------------------------------------------
# Framework model (extracted from AST)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DefeasibleRule:
    """A strict or defeasible rule: head :- body."""

    rule_id: str
    head: str
    body: tuple[str, ...]
    defeasible: bool
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": list(self.body),
            "defeasible": self.defeasible,
            "head": self.head,
            "priority": self.priority,
            "rule_id": self.rule_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DefeasibleRule:
        return cls(
            rule_id=str(value.get("rule_id") or ""),
            head=str(value.get("head") or ""),
            body=tuple(str(item) for item in value.get("body") or ()),
            defeasible=bool(value.get("defeasible", True)),
            priority=int(value.get("priority") or 0),
        )


@dataclass(frozen=True, slots=True)
class ArgumentationFramework:
    """Finite abstract / bipolar argumentation framework with rules."""

    arguments: tuple[str, ...] = ()
    attacks: tuple[tuple[str, str], ...] = ()
    supports: tuple[tuple[str, str], ...] = ()
    priorities: tuple[tuple[str, str], ...] = ()  # (higher, lower)
    rules: tuple[DefeasibleRule, ...] = ()
    queries: tuple[str, ...] = ()
    schema_version: str = ARG_EXTENSION_SET_SCHEMA

    def __post_init__(self) -> None:
        args = tuple(dict.fromkeys(str(a) for a in self.arguments if str(a)))
        attacks = tuple(
            (str(a), str(b)) for a, b in self.attacks if str(a) and str(b)
        )
        supports = tuple(
            (str(a), str(b)) for a, b in self.supports if str(a) and str(b)
        )
        priorities = tuple(
            (str(a), str(b)) for a, b in self.priorities if str(a) and str(b)
        )
        rules = tuple(self.rules)
        queries = tuple(dict.fromkeys(str(q) for q in self.queries if str(q)))
        # Arguments implied by attacks/supports/rules/queries.
        implied: list[str] = list(args)
        for a, b in chain(attacks, supports, priorities):
            if a not in implied:
                implied.append(a)
            if b not in implied:
                implied.append(b)
        for rule in rules:
            if rule.head and rule.head not in implied:
                implied.append(rule.head)
            for atom in rule.body:
                if atom and atom not in implied:
                    implied.append(atom)
        for q in queries:
            if q not in implied:
                implied.append(q)
        object.__setattr__(self, "arguments", tuple(implied))
        object.__setattr__(self, "attacks", attacks)
        object.__setattr__(self, "supports", supports)
        object.__setattr__(self, "priorities", priorities)
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "queries", queries)

    @property
    def attack_map(self) -> dict[str, frozenset[str]]:
        """Map argument -> set of arguments that attack it."""

        result: dict[str, set[str]] = {a: set() for a in self.arguments}
        for attacker, target in self.attacks:
            result.setdefault(target, set()).add(attacker)
            result.setdefault(attacker, set())
        return {k: frozenset(v) for k, v in result.items()}

    @property
    def attacks_from(self) -> dict[str, frozenset[str]]:
        """Map argument -> set of arguments it attacks."""

        result: dict[str, set[str]] = {a: set() for a in self.arguments}
        for attacker, target in self.attacks:
            result.setdefault(attacker, set()).add(target)
            result.setdefault(target, set())
        return {k: frozenset(v) for k, v in result.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": list(self.arguments),
            "attacks": [list(pair) for pair in self.attacks],
            "priorities": [list(pair) for pair in self.priorities],
            "queries": list(self.queries),
            "rules": [rule.to_dict() for rule in self.rules],
            "schema_version": self.schema_version,
            "supports": [list(pair) for pair in self.supports],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArgumentationFramework:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("ArgumentationFramework must be a mapping")
        return cls(
            arguments=tuple(value.get("arguments") or ()),
            attacks=tuple(
                (pair[0], pair[1])
                for pair in value.get("attacks") or ()
                if isinstance(pair, (list, tuple)) and len(pair) >= 2
            ),
            supports=tuple(
                (pair[0], pair[1])
                for pair in value.get("supports") or ()
                if isinstance(pair, (list, tuple)) and len(pair) >= 2
            ),
            priorities=tuple(
                (pair[0], pair[1])
                for pair in value.get("priorities") or ()
                if isinstance(pair, (list, tuple)) and len(pair) >= 2
            ),
            rules=tuple(
                DefeasibleRule.from_dict(item)
                for item in value.get("rules") or ()
                if isinstance(item, Mapping)
            ),
            queries=tuple(value.get("queries") or ()),
            schema_version=str(
                value.get("schema_version") or ARG_EXTENSION_SET_SCHEMA
            ),
        )


def extract_framework(node: LogicNode) -> ArgumentationFramework:
    """Walk an argumentation AST and collect framework components."""

    arguments: list[str] = []
    attacks: list[tuple[str, str]] = []
    supports: list[tuple[str, str]] = []
    priorities: list[tuple[str, str]] = []
    rules: list[DefeasibleRule] = []
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
            if schema == ARG_ARGUMENT_PAYLOAD_SCHEMA:
                name = str(payload.get("name") or "")
                if name:
                    arguments.append(name)
            elif schema == ARG_ATTACK_PAYLOAD_SCHEMA:
                a = str(payload.get("attacker") or "")
                b = str(payload.get("target") or "")
                if a and b:
                    attacks.append((a, b))
            elif schema == ARG_SUPPORT_PAYLOAD_SCHEMA:
                a = str(payload.get("supporter") or "")
                b = str(payload.get("target") or "")
                if a and b:
                    supports.append((a, b))
            elif schema == ARG_PRIORITY_PAYLOAD_SCHEMA:
                higher = str(payload.get("higher") or "")
                lower = str(payload.get("lower") or "")
                if higher and lower:
                    priorities.append((higher, lower))
            elif schema in {
                ARG_STRICT_RULE_PAYLOAD_SCHEMA,
                ARG_DEFEASIBLE_RULE_PAYLOAD_SCHEMA,
            }:
                rules.append(
                    DefeasibleRule(
                        rule_id=str(payload.get("rule_id") or ""),
                        head=str(payload.get("head") or ""),
                        body=tuple(str(x) for x in payload.get("body") or ()),
                        defeasible=bool(payload.get("defeasible", True)),
                        priority=int(payload.get("priority") or 0),
                    )
                )
            elif schema == ARG_STATUS_QUERY_PAYLOAD_SCHEMA:
                name = str(payload.get("argument") or "")
                if name:
                    queries.append(name)
            for child in ext.children:
                walk(child)
            return
        for child in n.arguments:
            walk(child)

    walk(node)
    return ArgumentationFramework(
        arguments=tuple(arguments),
        attacks=tuple(attacks),
        supports=tuple(supports),
        priorities=tuple(priorities),
        rules=tuple(rules),
        queries=tuple(queries),
    )


# ---------------------------------------------------------------------------
# Evaluation — preserves undecided and multiple extensions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArgumentLabeling:
    """Three-valued labeling of arguments under a named semantics."""

    labels: Mapping[str, ArgumentLabel | str]
    semantics: ArgumentationSemantics | str
    profile_id: str
    schema_version: str = ARG_LABELING_SCHEMA

    def __post_init__(self) -> None:
        semantics = (
            self.semantics
            if isinstance(self.semantics, ArgumentationSemantics)
            else ArgumentationSemantics(str(self.semantics))
        )
        frozen: dict[str, ArgumentLabel] = {}
        for name, label in self.labels.items():
            lab = (
                label
                if isinstance(label, ArgumentLabel)
                else ArgumentLabel(str(label))
            )
            frozen[str(name)] = lab
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "labels", dict(sorted(frozen.items())))
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        if not self.profile_id:
            raise SyntaxContractError(
                "ArgumentLabeling.profile_id is required; "
                "semantics/profile is always named"
            )

    @property
    def in_set(self) -> frozenset[str]:
        return frozenset(
            name
            for name, lab in self.labels.items()
            if lab is ArgumentLabel.IN or lab == ArgumentLabel.IN.value
        )

    @property
    def out_set(self) -> frozenset[str]:
        return frozenset(
            name
            for name, lab in self.labels.items()
            if lab is ArgumentLabel.OUT or lab == ArgumentLabel.OUT.value
        )

    @property
    def undecided_set(self) -> frozenset[str]:
        return frozenset(
            name
            for name, lab in self.labels.items()
            if lab is ArgumentLabel.UNDECIDED or lab == ArgumentLabel.UNDECIDED.value
        )

    @property
    def has_undecided(self) -> bool:
        return bool(self.undecided_set)

    def label_of(self, argument: str) -> ArgumentLabel:
        raw = self.labels.get(argument)
        if raw is None:
            raise SyntaxContractError(f"argument {argument!r} not in labeling")
        if isinstance(raw, ArgumentLabel):
            return raw
        return ArgumentLabel(str(raw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_undecided": self.has_undecided,
            "in": sorted(self.in_set),
            "labels": {
                name: (
                    lab.value if isinstance(lab, ArgumentLabel) else str(lab)
                )
                for name, lab in self.labels.items()
            },
            "out": sorted(self.out_set),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "semantics": (
                self.semantics.value
                if isinstance(self.semantics, ArgumentationSemantics)
                else str(self.semantics)
            ),
            "undecided": sorted(self.undecided_set),
        }


@dataclass(frozen=True, slots=True)
class ArgumentationEvaluation:
    """Evaluation result under a named semantics.

    * Multiple extensions are listed explicitly (never collapsed to one).
    * Undecided labels remain first-class (never coerced to classical false).
    * Classical entailment flags are always false.
    """

    profile_id: str
    semantics: ArgumentationSemantics | str
    extensions: tuple[tuple[str, ...], ...]
    labeling: ArgumentLabeling | None = None
    labelings: tuple[ArgumentLabeling, ...] = ()
    queries: Mapping[str, ArgumentLabel | str] = field(default_factory=dict)
    unique_extension: bool = False
    multiple_extensions: bool = False
    has_undecided: bool = False
    classical_entailment: bool = False
    schema_version: str = ARG_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        semantics = (
            self.semantics
            if isinstance(self.semantics, ArgumentationSemantics)
            else ArgumentationSemantics(str(self.semantics))
        )
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "ArgumentationEvaluation.profile_id is required; "
                "semantics/profile is always named"
            )
        extensions = tuple(
            tuple(sorted(str(a) for a in ext)) for ext in self.extensions
        )
        # Deduplicate while preserving order.
        seen: set[tuple[str, ...]] = set()
        unique_exts: list[tuple[str, ...]] = []
        for ext in extensions:
            if ext not in seen:
                seen.add(ext)
                unique_exts.append(ext)
        multiple = len(unique_exts) > 1
        unique = len(unique_exts) == 1
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(self, "extensions", tuple(unique_exts))
        object.__setattr__(self, "multiple_extensions", multiple)
        object.__setattr__(self, "unique_extension", unique)
        # Never allow classical entailment flag to be true.
        if self.classical_entailment:
            raise AuthorityPromotionError(
                "argumentation evaluation cannot claim classical_entailment; "
                "no classical entailment promotion is permitted"
            )
        object.__setattr__(self, "classical_entailment", False)
        # Normalize query labels.
        qmap: dict[str, ArgumentLabel] = {}
        for name, lab in self.queries.items():
            qmap[str(name)] = (
                lab if isinstance(lab, ArgumentLabel) else ArgumentLabel(str(lab))
            )
        object.__setattr__(self, "queries", qmap)
        has_und = bool(self.has_undecided)
        if self.labeling is not None and self.labeling.has_undecided:
            has_und = True
        for lab in self.labelings:
            if lab.has_undecided:
                has_und = True
        if any(lab is ArgumentLabel.UNDECIDED for lab in qmap.values()):
            has_und = True
        object.__setattr__(self, "has_undecided", has_und)

    @property
    def semantics_name(self) -> str:
        assert isinstance(self.semantics, ArgumentationSemantics)
        return self.semantics.value

    @property
    def extension_count(self) -> int:
        return len(self.extensions)

    def status_of(self, argument: str) -> ArgumentLabel:
        """Return the status of *argument* under this evaluation.

        Under multi-extension semantics, an argument is:
        * IN if in every extension
        * OUT if in no extension (and attacked by every extension's members
          when labeling is available)
        * UNDECIDED otherwise (including when extensions disagree)

        Undecided is preserved — never collapsed to classical false.
        """

        if argument in self.queries:
            raw = self.queries[argument]
            return raw if isinstance(raw, ArgumentLabel) else ArgumentLabel(str(raw))
        if self.labeling is not None and argument in self.labeling.labels:
            return self.labeling.label_of(argument)
        if not self.extensions:
            return ArgumentLabel.UNDECIDED
        membership = [argument in ext for ext in self.extensions]
        if all(membership):
            return ArgumentLabel.IN
        if not any(membership):
            # Not in any extension — still not classical false.
            if self.multiple_extensions or self.has_undecided:
                return ArgumentLabel.UNDECIDED
            return ArgumentLabel.OUT
        # Present in some but not all extensions.
        return ArgumentLabel.UNDECIDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "classical_entailment": False,
            "extension_count": self.extension_count,
            "extensions": [list(ext) for ext in self.extensions],
            "has_undecided": self.has_undecided,
            "labeling": self.labeling.to_dict() if self.labeling else None,
            "labelings": [lab.to_dict() for lab in self.labelings],
            "multiple_extensions": self.multiple_extensions,
            "profile_id": self.profile_id,
            "queries": {
                name: (
                    lab.value if isinstance(lab, ArgumentLabel) else str(lab)
                )
                for name, lab in self.queries.items()
            },
            "schema_version": self.schema_version,
            "semantics": self.semantics_name,
            "unique_extension": self.unique_extension,
        }


def _is_conflict_free(
    candidates: set[str],
    attacks_from: Mapping[str, frozenset[str]],
) -> bool:
    for a in candidates:
        if attacks_from.get(a, frozenset()) & candidates:
            return False
    return True


def _defends(
    candidates: set[str],
    argument: str,
    attack_map: Mapping[str, frozenset[str]],
    attacks_from: Mapping[str, frozenset[str]],
) -> bool:
    """True iff *candidates* defends *argument* (attacks every attacker)."""

    for attacker in attack_map.get(argument, frozenset()):
        if not (attacks_from.keys() and any(
            attacker in attacks_from.get(defender, frozenset())
            for defender in candidates
        )):
            # No member of candidates attacks this attacker.
            defended = False
            for defender in candidates:
                if attacker in attacks_from.get(defender, frozenset()):
                    defended = True
                    break
            if not defended:
                return False
    return True


def _is_admissible(
    candidates: set[str],
    attack_map: Mapping[str, frozenset[str]],
    attacks_from: Mapping[str, frozenset[str]],
) -> bool:
    if not _is_conflict_free(candidates, attacks_from):
        return False
    return all(
        _defends(candidates, arg, attack_map, attacks_from) for arg in candidates
    )


def _is_complete(
    candidates: set[str],
    arguments: Sequence[str],
    attack_map: Mapping[str, frozenset[str]],
    attacks_from: Mapping[str, frozenset[str]],
) -> bool:
    if not _is_admissible(candidates, attack_map, attacks_from):
        return False
    # Contains every argument it defends.
    for arg in arguments:
        if arg in candidates:
            continue
        if _defends(candidates, arg, attack_map, attacks_from):
            return False
    return True


def _is_stable(
    candidates: set[str],
    arguments: Sequence[str],
    attacks_from: Mapping[str, frozenset[str]],
) -> bool:
    if not _is_conflict_free(candidates, attacks_from):
        return False
    outsiders = set(arguments) - candidates
    for out in outsiders:
        attacked = False
        for member in candidates:
            if out in attacks_from.get(member, frozenset()):
                attacked = True
                break
        if not attacked:
            return False
    return True


def _labeling_from_extension(
    arguments: Sequence[str],
    extension: set[str],
    attacks_from: Mapping[str, frozenset[str]],
    *,
    semantics: ArgumentationSemantics,
    profile_id: str,
) -> ArgumentLabeling:
    labels: dict[str, ArgumentLabel] = {}
    attacked_by_ext: set[str] = set()
    for member in extension:
        attacked_by_ext |= set(attacks_from.get(member, frozenset()))
    for arg in arguments:
        if arg in extension:
            labels[arg] = ArgumentLabel.IN
        elif arg in attacked_by_ext:
            labels[arg] = ArgumentLabel.OUT
        else:
            labels[arg] = ArgumentLabel.UNDECIDED
    return ArgumentLabeling(
        labels=labels,
        semantics=semantics,
        profile_id=profile_id,
    )


def _grounded_extension(
    arguments: Sequence[str],
    attack_map: Mapping[str, frozenset[str]],
    attacks_from: Mapping[str, frozenset[str]],
) -> set[str]:
    """Least complete extension via iterative characteristic function."""

    s: set[str] = set()
    changed = True
    while changed:
        changed = False
        # F(S) = { a | S defends a }
        defended = {
            arg
            for arg in arguments
            if _defends(s, arg, attack_map, attacks_from)
        }
        # Restrict to conflict-free accumulation (grounded is always CF).
        next_s = set(defended)
        if next_s != s:
            s = next_s
            changed = True
    return s


def _enumerate_subsets(arguments: Sequence[str]) -> Iterable[set[str]]:
    args = list(arguments)
    n = len(args)
    for r in range(n + 1):
        for combo in combinations(args, r):
            yield set(combo)


def _evaluate_defeasible(
    framework: ArgumentationFramework,
    profile: ArgumentationProfile,
) -> ArgumentationEvaluation:
    """Priority-aware nonmonotonic rule evaluation.

    Strict rules always fire when their body is derived.  Defeasible rules
    fire unless a higher-priority contrary head is derived.  Arguments not
    derived remain UNDECIDED (not classical false).
    """

    derived: set[str] = set()
    # Seed: arguments with no rules that are not attacked? For pure rule
    # programs, start from empty and close under rules.
    # Also treat bare arguments without rules as contingent facts if no
    # contrary priority exists — still nonmonotonic, not classical.
    facts = {
        arg
        for arg in framework.arguments
        if not any(rule.head == arg for rule in framework.rules)
        and not any(target == arg for _, target in framework.attacks)
    }
    derived |= facts

    # Priority: higher beats lower.  Build rank (higher rank = preferred).
    rank: dict[str, int] = {arg: 0 for arg in framework.arguments}
    for higher, lower in framework.priorities:
        rank[higher] = max(rank.get(higher, 0), rank.get(lower, 0) + 1)
        rank.setdefault(lower, 0)

    # Fixed-point derivation with defeat.
    changed = True
    rounds = 0
    max_rounds = max(8, len(framework.rules) * 4 + 1)
    while changed and rounds < max_rounds:
        rounds += 1
        changed = False
        # Strict first.
        for rule in framework.rules:
            if rule.defeasible:
                continue
            if all(atom in derived for atom in rule.body) or not rule.body:
                if rule.head not in derived:
                    derived.add(rule.head)
                    changed = True
        # Defeasible: body satisfied and not defeated by higher contrary.
        for rule in framework.rules:
            if not rule.defeasible:
                continue
            if not (all(atom in derived for atom in rule.body) or not rule.body):
                continue
            if rule.head in derived:
                continue
            defeated = False
            for other in framework.rules:
                if other is rule:
                    continue
                if other.head == rule.head:
                    continue
                # Contrary: other head attacks rule head, or priority lower.
                contrary = (other.head, rule.head) in framework.attacks or (
                    rule.head,
                    other.head,
                ) in framework.attacks
                if not contrary and other.head != rule.head:
                    # Also treat mutual exclusivity via priority pairs.
                    if (other.head, rule.head) not in framework.priorities and (
                        rule.head,
                        other.head,
                    ) not in framework.priorities:
                        continue
                other_ready = all(a in derived for a in other.body) or not other.body
                if not other_ready and other.defeasible:
                    continue
                other_rank = max(
                    rank.get(other.head, 0),
                    other.priority,
                )
                self_rank = max(rank.get(rule.head, 0), rule.priority)
                if other_rank > self_rank and (
                    not other.defeasible or other_ready or other.head in derived
                ):
                    defeated = True
                    break
                if (
                    other.head in derived
                    and other_rank >= self_rank
                    and (other.head, rule.head) in framework.attacks
                ):
                    defeated = True
                    break
            if not defeated:
                # Also defeated if a higher-priority derived attacker exists.
                for attacker, target in framework.attacks:
                    if target == rule.head and attacker in derived:
                        if rank.get(attacker, 0) >= rank.get(rule.head, 0):
                            defeated = True
                            break
            if not defeated:
                derived.add(rule.head)
                changed = True

    labels: dict[str, ArgumentLabel] = {}
    for arg in framework.arguments:
        if arg in derived:
            # OUT if attacked by a higher-priority derived argument.
            out = False
            for attacker, target in framework.attacks:
                if target == arg and attacker in derived:
                    if rank.get(attacker, 0) >= rank.get(arg, 0):
                        out = True
                        break
            labels[arg] = ArgumentLabel.OUT if out else ArgumentLabel.IN
        else:
            labels[arg] = ArgumentLabel.UNDECIDED

    labeling = ArgumentLabeling(
        labels=labels,
        semantics=ArgumentationSemantics.DEFEASIBLE,
        profile_id=profile.profile_id,
    )
    extension = tuple(sorted(a for a, lab in labels.items() if lab is ArgumentLabel.IN))
    queries = {
        q: labels.get(q, ArgumentLabel.UNDECIDED) for q in framework.queries
    }
    return ArgumentationEvaluation(
        profile_id=profile.profile_id,
        semantics=ArgumentationSemantics.DEFEASIBLE,
        extensions=(extension,),
        labeling=labeling,
        labelings=(labeling,),
        queries=queries,
        has_undecided=labeling.has_undecided,
        classical_entailment=False,
    )


def evaluate_framework(
    framework: ArgumentationFramework,
    profile: ArgumentationProfile,
) -> ArgumentationEvaluation:
    """Evaluate *framework* under the named *profile* semantics.

    Undecided labels and multiple extensions are preserved.  The result
    never claims classical entailment.
    """

    if profile is None:
        raise SyntaxContractError(
            "evaluate_framework requires a named ArgumentationProfile"
        )
    semantics = (
        profile.semantics
        if isinstance(profile.semantics, ArgumentationSemantics)
        else ArgumentationSemantics(str(profile.semantics))
    )
    arguments = list(framework.arguments)
    if len(arguments) > profile.max_arguments:
        raise SyntaxContractError(
            f"framework has {len(arguments)} arguments; profile "
            f"{profile.profile_id!r} allows at most {profile.max_arguments}",
        )

    if semantics is ArgumentationSemantics.DEFEASIBLE:
        return _evaluate_defeasible(framework, profile)

    attack_map = framework.attack_map
    attacks_from = framework.attacks_from

    if semantics is ArgumentationSemantics.GROUNDED:
        grounded = _grounded_extension(arguments, attack_map, attacks_from)
        labeling = _labeling_from_extension(
            arguments,
            grounded,
            attacks_from,
            semantics=semantics,
            profile_id=profile.profile_id,
        )
        queries = {
            q: labeling.labels.get(q, ArgumentLabel.UNDECIDED)
            for q in framework.queries
        }
        return ArgumentationEvaluation(
            profile_id=profile.profile_id,
            semantics=semantics,
            extensions=(tuple(sorted(grounded)),),
            labeling=labeling,
            labelings=(labeling,),
            queries=queries,
            has_undecided=labeling.has_undecided,
            classical_entailment=False,
        )

    # Enumerative semantics: complete / preferred / stable.
    complete_exts: list[set[str]] = []
    for subset in _enumerate_subsets(arguments):
        if _is_complete(subset, arguments, attack_map, attacks_from):
            complete_exts.append(subset)

    if semantics is ArgumentationSemantics.COMPLETE:
        selected = complete_exts
    elif semantics is ArgumentationSemantics.PREFERRED:
        # Maximal complete extensions.
        selected = []
        for ext in complete_exts:
            if not any(ext < other for other in complete_exts if other is not ext):
                # Use proper subset check against all others.
                maximal = True
                for other in complete_exts:
                    if ext is other:
                        continue
                    if ext < other:
                        maximal = False
                        break
                if maximal:
                    selected.append(ext)
    elif semantics is ArgumentationSemantics.STABLE:
        selected = [
            subset
            for subset in _enumerate_subsets(arguments)
            if _is_stable(subset, arguments, attacks_from)
        ]
    else:
        raise SyntaxContractError(f"unsupported semantics {semantics!r}")

    # Cap reported extensions (still multi when >1).
    if len(selected) > _MAX_EXTENSIONS_REPORTED:
        selected = selected[:_MAX_EXTENSIONS_REPORTED]

    extensions = tuple(tuple(sorted(ext)) for ext in selected)
    labelings = tuple(
        _labeling_from_extension(
            arguments,
            set(ext),
            attacks_from,
            semantics=semantics,
            profile_id=profile.profile_id,
        )
        for ext in extensions
    )
    # Skeptical labeling across extensions: IN only if in all, OUT only if
    # out in all, else UNDECIDED.  This preserves multi-extension disagreement.
    if extensions:
        skeptical: dict[str, ArgumentLabel] = {}
        for arg in arguments:
            membership = [arg in ext for ext in extensions]
            if all(membership):
                skeptical[arg] = ArgumentLabel.IN
            elif not any(membership):
                # All-out still leaves room for undecided under incomplete
                # attack coverage when multi-extension; mark OUT only when
                # every labeling says OUT, else UNDECIDED.
                if labelings and all(
                    lab.label_of(arg) is ArgumentLabel.OUT for lab in labelings
                ):
                    skeptical[arg] = ArgumentLabel.OUT
                else:
                    skeptical[arg] = ArgumentLabel.UNDECIDED
            else:
                skeptical[arg] = ArgumentLabel.UNDECIDED
        primary = ArgumentLabeling(
            labels=skeptical,
            semantics=semantics,
            profile_id=profile.profile_id,
        )
    else:
        # No extensions: everything undecided (not classical false).
        primary = ArgumentLabeling(
            labels={arg: ArgumentLabel.UNDECIDED for arg in arguments},
            semantics=semantics,
            profile_id=profile.profile_id,
        )

    queries = {
        q: primary.labels.get(q, ArgumentLabel.UNDECIDED) for q in framework.queries
    }
    return ArgumentationEvaluation(
        profile_id=profile.profile_id,
        semantics=semantics,
        extensions=extensions,
        labeling=primary,
        labelings=labelings,
        queries=queries,
        has_undecided=primary.has_undecided,
        classical_entailment=False,
    )


# ---------------------------------------------------------------------------
# Evidence contracts — no classical entailment promotion
# ---------------------------------------------------------------------------


class AuthorityPromotionError(SyntaxContractError):
    """Raised when evidence is promoted beyond its declared authority ceiling."""


@dataclass(frozen=True, slots=True)
class ArgumentationEvidenceContract:
    """Authority ceiling for argumentation / nonmonotonic evidence.

    AF and defeasible evaluation results are **never** classical entailment
    authority.  Classical-solver sources cannot launder nonmonotonic outcomes
    into theorem status through this module.
    """

    source: EvidenceSource | str
    authority: EvidenceAuthority | str
    semantics: ArgumentationSemantics | str
    profile_id: str
    bound: BoundednessKind | str = BoundednessKind.FINITE_FRAMEWORK
    grants_classical_entailment: bool = False
    preserves_undecided: bool = True
    preserves_multiple_extensions: bool = True
    schema_version: str = ARG_EVIDENCE_CONTRACT_SCHEMA

    interface: ClassVar[str] = ARGUMENTATION_LOGIC_INTERFACE

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
            if isinstance(self.semantics, ArgumentationSemantics)
            else ArgumentationSemantics(str(self.semantics))
        )
        bound = (
            self.bound
            if isinstance(self.bound, BoundednessKind)
            else BoundednessKind(str(self.bound))
        )
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "ArgumentationEvidenceContract.profile_id is required; "
                "semantics/profile is always named"
            )
        ceiling = _SOURCE_AUTHORITY_CEILING[source]
        if _AUTHORITY_RANK[authority] > _AUTHORITY_RANK[ceiling]:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot claim {authority.value} "
                f"authority (ceiling={ceiling.value}); argumentation / "
                "nonmonotonic evidence cannot become classical entailment"
            )
        if authority is EvidenceAuthority.CLASSICAL_ENTAILMENT:
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot become classical entailment "
                "authority; no classical entailment promotion is permitted"
            )
        if self.grants_classical_entailment:
            raise AuthorityPromotionError(
                f"{source.value}/{authority.value} cannot set "
                "grants_classical_entailment=True; no classical entailment "
                "promotion is permitted"
            )
        if source in _NON_CLASSICAL_SOURCES and (
            authority is EvidenceAuthority.CLASSICAL_ENTAILMENT
            or self.grants_classical_entailment
        ):
            raise AuthorityPromotionError(
                f"{source.value} evidence cannot become classical entailment"
            )
        # Classical solver source is admitted only at non-classical ceilings
        # when used from this module (hard reject of classical claim above).
        if source is EvidenceSource.CLASSICAL_SOLVER:
            # Even classical_solver cannot claim classical entailment here.
            if authority is EvidenceAuthority.CLASSICAL_ENTAILMENT:
                raise AuthorityPromotionError(
                    "classical_solver evidence cannot become classical "
                    "entailment through ArgumentationLogic@1"
                )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "bound", bound)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(self, "grants_classical_entailment", False)
        if self.schema_version != ARG_EVIDENCE_CONTRACT_SCHEMA:
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
    def may_promote_to_classical_entailment(self) -> bool:
        return False

    @property
    def is_classical_entailment(self) -> bool:
        return False

    def promote_to_classical_entailment(self) -> None:
        """Fail closed: AF/nonmonotonic evidence is never classical entailment."""

        source = (
            self.source.value
            if isinstance(self.source, EvidenceSource)
            else str(self.source)
        )
        authority = (
            self.authority.value
            if isinstance(self.authority, EvidenceAuthority)
            else str(self.authority)
        )
        raise AuthorityPromotionError(
            f"{source} evidence with authority={authority} cannot be promoted "
            "to classical entailment; undecided and multi-extension outcomes "
            "must be preserved under named nonmonotonic/argumentation semantics"
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
            "interface": self.interface,
            "is_classical_entailment": False,
            "may_promote_to_classical_entailment": False,
            "preserves_multiple_extensions": bool(
                self.preserves_multiple_extensions
            ),
            "preserves_undecided": bool(self.preserves_undecided),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
            "semantics": (
                self.semantics.value
                if isinstance(self.semantics, ArgumentationSemantics)
                else str(self.semantics)
            ),
            "source": (
                self.source.value
                if isinstance(self.source, EvidenceSource)
                else str(self.source)
            ),
            "source_ceiling": self.source_ceiling.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ArgumentationEvidenceContract:
        if not isinstance(value, Mapping):
            raise SyntaxContractError("evidence contract must be a mapping")
        return cls(
            source=value.get("source", EvidenceSource.NONE.value),
            authority=value.get("authority", EvidenceAuthority.NONE.value),
            semantics=value.get("semantics", ArgumentationSemantics.GROUNDED.value),
            profile_id=str(value.get("profile_id") or ""),
            bound=value.get("bound", BoundednessKind.FINITE_FRAMEWORK.value),
            grants_classical_entailment=bool(
                value.get("grants_classical_entailment", False)
            ),
            preserves_undecided=bool(value.get("preserves_undecided", True)),
            preserves_multiple_extensions=bool(
                value.get("preserves_multiple_extensions", True)
            ),
            schema_version=str(
                value.get("schema_version") or ARG_EVIDENCE_CONTRACT_SCHEMA
            ),
        )


def grounded_evidence_contract(
    profile: ArgumentationProfile | None = None,
) -> ArgumentationEvidenceContract:
    prof = profile or profile_grounded()
    return ArgumentationEvidenceContract(
        source=EvidenceSource.GROUNDED_EVALUATOR,
        authority=EvidenceAuthority.ARGUMENTATION,
        semantics=ArgumentationSemantics.GROUNDED,
        profile_id=prof.profile_id,
        preserves_undecided=True,
        preserves_multiple_extensions=False,
    )


def preferred_evidence_contract(
    profile: ArgumentationProfile | None = None,
) -> ArgumentationEvidenceContract:
    prof = profile or profile_preferred()
    return ArgumentationEvidenceContract(
        source=EvidenceSource.PREFERRED_EVALUATOR,
        authority=EvidenceAuthority.ARGUMENTATION,
        semantics=ArgumentationSemantics.PREFERRED,
        profile_id=prof.profile_id,
        preserves_undecided=True,
        preserves_multiple_extensions=True,
    )


def complete_evidence_contract(
    profile: ArgumentationProfile | None = None,
) -> ArgumentationEvidenceContract:
    prof = profile or profile_complete()
    return ArgumentationEvidenceContract(
        source=EvidenceSource.COMPLETE_EVALUATOR,
        authority=EvidenceAuthority.ARGUMENTATION,
        semantics=ArgumentationSemantics.COMPLETE,
        profile_id=prof.profile_id,
        preserves_undecided=True,
        preserves_multiple_extensions=True,
    )


def stable_evidence_contract(
    profile: ArgumentationProfile | None = None,
) -> ArgumentationEvidenceContract:
    prof = profile or profile_stable()
    return ArgumentationEvidenceContract(
        source=EvidenceSource.STABLE_EVALUATOR,
        authority=EvidenceAuthority.ARGUMENTATION,
        semantics=ArgumentationSemantics.STABLE,
        profile_id=prof.profile_id,
        preserves_undecided=True,
        preserves_multiple_extensions=True,
    )


def defeasible_evidence_contract(
    profile: ArgumentationProfile | None = None,
) -> ArgumentationEvidenceContract:
    prof = profile or profile_defeasible()
    return ArgumentationEvidenceContract(
        source=EvidenceSource.DEFEASIBLE_EVALUATOR,
        authority=EvidenceAuthority.NONMONOTONIC,
        semantics=ArgumentationSemantics.DEFEASIBLE,
        profile_id=prof.profile_id,
        preserves_undecided=True,
        preserves_multiple_extensions=False,
    )


def retain_authority_ceiling(
    evidence: ArgumentationEvidenceContract,
    claimed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project evidence while retaining the declared authority ceiling.

    Any claim of classical entailment is rejected; the retained payload never
    escalates and always records that undecided / multi-extension outcomes
    are preserved.
    """

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
        claimed_is_classical = (
            claimed_authority == EvidenceAuthority.CLASSICAL_ENTAILMENT.value
            or claimed_classical
        )
        if claimed_is_classical:
            raise AuthorityPromotionError(
                "claimed classical entailment exceeds retained ceiling "
                f"(source={payload['source']}, "
                f"ceiling={payload['authority_ceiling']}); "
                "no classical entailment promotion is permitted"
            )
        # Reject collapse of undecided / multi-extension.
        if claimed.get("preserves_undecided") is False and evidence.preserves_undecided:
            raise AuthorityPromotionError(
                "claimed collapse of undecided outcomes is rejected; "
                "undecided must be preserved under named AF semantics"
            )
        if (
            claimed.get("preserves_multiple_extensions") is False
            and evidence.preserves_multiple_extensions
        ):
            raise AuthorityPromotionError(
                "claimed collapse of multiple extensions is rejected; "
                "multi-extension outcomes must be preserved"
            )
    retained = dict(payload)
    retained["authority"] = evidence.authority_ceiling.value
    retained["authority_ceiling"] = evidence.authority_ceiling.value
    retained["grants_classical_entailment"] = False
    retained["may_promote_to_classical_entailment"] = False
    retained["is_classical_entailment"] = False
    retained["preserves_undecided"] = bool(evidence.preserves_undecided)
    retained["preserves_multiple_extensions"] = bool(
        evidence.preserves_multiple_extensions
    )
    return retained


@dataclass(frozen=True, slots=True)
class ArgumentationLoweringReceipt:
    """Receipt for one evaluation / evidence attachment."""

    document_id: str
    profile_id: str
    semantics: str
    evaluation: dict[str, Any]
    evidence: dict[str, Any]
    authorizes_classical_entailment: bool = False
    schema_version: str = ARG_LOWERING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.authorizes_classical_entailment:
            raise AuthorityPromotionError(
                "lowering receipt cannot authorize classical entailment; "
                "no classical entailment promotion is permitted"
            )
        if self.evidence.get("grants_classical_entailment") or self.evidence.get(
            "is_classical_entailment"
        ):
            raise AuthorityPromotionError(
                "argumentation evidence cannot become classical entailment "
                "on a lowering receipt"
            )
        if self.evidence.get("authority") == (
            EvidenceAuthority.CLASSICAL_ENTAILMENT.value
        ):
            raise AuthorityPromotionError(
                "argumentation evidence cannot become classical entailment "
                "on a lowering receipt"
            )
        if not self.profile_id or not str(self.profile_id).strip():
            raise SyntaxContractError(
                "ArgumentationLoweringReceipt.profile_id is required"
            )
        if not self.semantics or not str(self.semantics).strip():
            raise SyntaxContractError(
                "ArgumentationLoweringReceipt.semantics is required; "
                "semantics/profile is always named"
            )
        object.__setattr__(self, "authorizes_classical_entailment", False)
        object.__setattr__(self, "profile_id", str(self.profile_id).strip())
        object.__setattr__(self, "semantics", str(self.semantics).strip())

    @property
    def authority_ceiling(self) -> str:
        return str(
            self.evidence.get("authority_ceiling") or self.evidence.get("authority")
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
            "semantics": self.semantics,
        }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArgumentationParseResult:
    """Typed result of a controlled argumentation parse attempt."""

    status: ParseStatus
    root: LogicNode | None = None
    expression: TypedExpression | None = None
    diagnostics: tuple[SyntaxDiagnostic, ...] = ()
    tokens: tuple[LogicToken, ...] = ()
    artifact: ParseArtifact | None = None
    printed: str = ""
    profile: ArgumentationProfile | None = None
    framework: ArgumentationFramework | None = None
    evaluation: ArgumentationEvaluation | None = None
    schema_version: str = ARG_PARSE_RESULT_SCHEMA

    interface: ClassVar[str] = ARGUMENTATION_LOGIC_INTERFACE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK and self.root is not None

    @property
    def errors(self) -> tuple[SyntaxDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.is_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "framework": self.framework.to_dict() if self.framework else None,
            "interface": self.interface,
            "printed": self.printed,
            "profile": self.profile.to_dict() if self.profile else None,
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, ParseStatus)
            else str(self.status),
        }


class ArgumentationParseError(SyntaxContractError):
    """Raised by raising helpers when an argumentation parse fails closed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_UNEXPECTED_TOKEN,
        diagnostics: Sequence[SyntaxDiagnostic] = (),
        result: ArgumentationParseResult | None = None,
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
        diagnostic_id=f"diag:arg:{code.replace('.', '-')}",
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


class ArgumentationPrinter:
    """Deterministic printer for argumentation framework ASTs."""

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

    def _print_extension(self, node: LogicNode) -> str:
        ext = node.extension
        if ext is None:
            raise SyntaxContractError("EXTENSION node missing extension payload")
        schema = ext.payload_schema
        payload = dict(ext.payload)

        if schema == ARG_ARGUMENT_PAYLOAD_SCHEMA:
            return f"arg({payload['name']})"
        if schema == ARG_ATTACK_PAYLOAD_SCHEMA:
            return f"attack({payload['attacker']}, {payload['target']})"
        if schema == ARG_SUPPORT_PAYLOAD_SCHEMA:
            return f"support({payload['supporter']}, {payload['target']})"
        if schema == ARG_PRIORITY_PAYLOAD_SCHEMA:
            return f"priority({payload['higher']}, {payload['lower']})"
        if schema == ARG_STRICT_RULE_PAYLOAD_SCHEMA:
            body = ", ".join(str(x) for x in payload.get("body") or ())
            return f"strict {payload['head']} :- {body}" if body else (
                f"strict {payload['head']} :-"
            )
        if schema == ARG_DEFEASIBLE_RULE_PAYLOAD_SCHEMA:
            body = ", ".join(str(x) for x in payload.get("body") or ())
            return (
                f"defeasible {payload['head']} :- {body}"
                if body
                else f"defeasible {payload['head']} :-"
            )
        if schema == ARG_STATUS_QUERY_PAYLOAD_SCHEMA:
            return f"status({payload['argument']})"
        raise SyntaxContractError(
            f"cannot print unknown argumentation payload schema {schema!r}"
        )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _extract_profile(value: object) -> ArgumentationProfile | None:
    if value is None:
        return None
    if isinstance(value, ArgumentationProfile):
        return value
    if isinstance(value, Mapping):
        return ArgumentationProfile.from_dict(value)
    return None


def _build_covering_cst(
    document: SourceDocument,
    tokens: Sequence[LogicToken],
    *,
    cst_id: str = "cst:arg:1",
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


def _signature_for_framework(
    framework: ArgumentationFramework,
    profile: ArgumentationProfile,
) -> LogicSignature:
    return LogicSignature(
        signature_id=f"sig:arg:{profile.profile_id}",
        family=profile.family_id,
        profile=profile.profile_id,
        sorts=(ARGUMENT_SORT, RULE_SORT, INDIVIDUAL_SORT),
        symbols=(),
        features=("argumentation", "nonmonotonic", profile.semantics_name),
        metadata={
            "argument_count": len(framework.arguments),
            "semantics": profile.semantics_name,
        },
    )


class ArgumentationParser:
    """Parser for controlled argumentation / nonmonotonic surface text."""

    interface: ClassVar[str] = ARGUMENTATION_LOGIC_INTERFACE

    def __init__(
        self,
        profile: ArgumentationProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_grounded()
        self.printer = ArgumentationPrinter(style=print_style)
        self._lexer = BoundedLexer(
            keywords=_ARG_KEYWORDS,
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
        return f"arg:{prefix}:{self._counter}"

    def parse(self, request: ParseRequest) -> ParseArtifact:
        if not isinstance(request, ParseRequest):
            raise SyntaxContractError("parse requires a ParseRequest")
        profile = (
            _extract_profile(request.metadata.get("profile"))
            or _extract_profile(request.metadata.get("argumentation_profile"))
            or self.profile
        )
        result = self.parse_document(
            request.document,
            profile=profile,
            mode=request.mode,
            limits=request.limits,
            request_id=request.request_id,
            expression_id=str(request.metadata.get("expression_id") or "expr:arg:1"),
        )
        assert result.artifact is not None
        return result.artifact

    def parse_document(
        self,
        document: SourceDocument,
        *,
        profile: ArgumentationProfile | None = None,
        mode: ParseMode | str = ParseMode.STRICT,
        limits: ParseLimits | None = None,
        request_id: str = "req:arg:1",
        expression_id: str = "expr:arg:1",
        evaluate: bool = True,
    ) -> ArgumentationParseResult:
        if not isinstance(document, SourceDocument):
            raise SyntaxContractError("document must be a SourceDocument")
        bounds = limits if limits is not None else ParseLimits()
        parse_mode = mode if isinstance(mode, ParseMode) else ParseMode(str(mode))
        prof = profile or self.profile
        if prof is None:
            diag = _diag(
                code=CODE_PROFILE_REQUIRED,
                message=(
                    "argumentation parse requires a named profile; "
                    "semantics/profile is always named"
                ),
                range=document.full_range(),
                remediation=(
                    "Pass profile_grounded(), profile_preferred(), "
                    "profile_complete(), profile_stable(), or profile_defeasible()"
                ),
            )
            artifact = ParseArtifact(
                artifact_id=f"art:{request_id}",
                request_id=request_id,
                document_id=document.document_id,
                status=ParseStatus.REJECTED,
                tokens=(),
                diagnostics=(diag,),
                metadata={"interface": ARGUMENTATION_LOGIC_INTERFACE},
            )
            return ArgumentationParseResult(
                status=ParseStatus.REJECTED,
                diagnostics=(diag,),
                artifact=artifact,
            )
        if not isinstance(prof, ArgumentationProfile):
            raise SyntaxContractError("profile must be an ArgumentationProfile")

        self._counter = 0

        if document.byte_length == 0 or not document.text.strip():
            diag = _diag(
                code=CODE_EMPTY_INPUT,
                message="empty argumentation input",
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
                    "interface": ARGUMENTATION_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ArgumentationParseResult(
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
                    diagnostic_id=f"diag:arg:lex:{index + 1}",
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
                    "interface": ARGUMENTATION_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ArgumentationParseResult(
                status=ParseStatus.FAILED,
                diagnostics=promoted,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        diags: list[SyntaxDiagnostic] = list(lex_result.diagnostics)
        cursor = _Cursor(lex_result.tokens, document)
        try:
            root = self._parse_framework(cursor, prof)
            if not cursor.is_eof():
                raise _ParseFail(
                    _diag(
                        code=CODE_TRAILING_INPUT,
                        message=(
                            f"trailing input after framework: "
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
                    "interface": ARGUMENTATION_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ArgumentationParseResult(
                status=ParseStatus.FAILED,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                profile=prof,
            )

        printed = self.printer.print(root)
        framework = extract_framework(root)
        evaluation: ArgumentationEvaluation | None = None
        eval_diags: list[SyntaxDiagnostic] = []
        if evaluate:
            try:
                evaluation = evaluate_framework(framework, prof)
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
                    "interface": ARGUMENTATION_LOGIC_INTERFACE,
                    "profile": prof.to_dict(),
                },
            )
            return ArgumentationParseResult(
                status=ParseStatus.FAILED,
                root=root,
                diagnostics=all_diags,
                tokens=lex_result.tokens,
                artifact=artifact,
                printed=printed,
                profile=prof,
                framework=framework,
            )

        signature = _signature_for_framework(framework, prof)
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
                "interface": ARGUMENTATION_LOGIC_INTERFACE,
                "profile": prof.to_dict(),
                "framework": framework.to_dict(),
                "evaluation": evaluation.to_dict() if evaluation else None,
                "printed": printed,
                "semantics": prof.semantics_name,
            },
        )
        return ArgumentationParseResult(
            status=ParseStatus.OK,
            root=root,
            expression=expression,
            diagnostics=all_diags,
            tokens=lex_result.tokens,
            artifact=artifact,
            printed=printed,
            profile=prof,
            framework=framework,
            evaluation=evaluation,
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

    def _parse_framework(
        self,
        cursor: _Cursor,
        profile: ArgumentationProfile,
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
                    "schema_version": ARG_AND_PAYLOAD_SCHEMA,
                    "family": ARG_FAMILY_ID,
                },
            )
        return left

    def _parse_statement(
        self,
        cursor: _Cursor,
        profile: ArgumentationProfile,
    ) -> LogicNode:
        self._enter(cursor)
        try:
            token = cursor.current()
            if token.lexeme == "(":
                cursor.advance()
                inner = self._parse_framework(cursor, profile)
                cursor.expect_lexeme(")", code=CODE_UNBALANCED)
                return inner

            name = token.lexeme.casefold()
            if name in _STATEMENT_ATOMS and token.kind in {
                TokenKind.IDENTIFIER.value,
                TokenKind.KEYWORD.value,
            }:
                return self._parse_atom(cursor, profile, name)

            raise _ParseFail(
                _diag(
                    code=CODE_UNEXPECTED_TOKEN,
                    message=(
                        f"expected argumentation statement; got {token.lexeme!r}"
                    ),
                    range=token.range,
                    remediation=(
                        "Use arg(...), attack(...), support(...), priority(...), "
                        "strict H :- B, defeasible H :- B, or status(...)"
                    ),
                )
            )
        finally:
            self._leave(cursor)

    def _parse_atom(
        self,
        cursor: _Cursor,
        profile: ArgumentationProfile,
        name: str,
    ) -> LogicNode:
        start = cursor.advance()

        if name in {"arg", "argument"}:
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            ident = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_argument(ident.lexeme, profile, span)

        if name == "attack":
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            attacker = cursor.expect_ident()
            cursor.expect_lexeme(",")
            target = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_attack(
                attacker.lexeme, target.lexeme, profile, span
            )

        if name == "support":
            if not profile.admit_support:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"support is not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            supporter = cursor.expect_ident()
            cursor.expect_lexeme(",")
            target = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_support(
                supporter.lexeme, target.lexeme, profile, span
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

        if name in {"strict", "defeasible"}:
            defeasible = name == "defeasible"
            if defeasible and not profile.admit_defeasible_rules:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"defeasible rules are not admitted by profile "
                            f"{profile.profile_id!r} "
                            f"(semantics={profile.semantics_name})"
                        ),
                        range=start.range,
                        remediation=(
                            "Use profile_defeasible() or enable "
                            "admit_defeasible_rules on the profile"
                        ),
                    )
                )
            if not defeasible and not profile.admit_strict_rules:
                raise _ParseFail(
                    _diag(
                        code=CODE_PROFILE_MISMATCH,
                        message=(
                            f"strict rules are not admitted by profile "
                            f"{profile.profile_id!r}"
                        ),
                        range=start.range,
                    )
                )
            head = cursor.expect_ident()
            # Accept ':-' as two tokens ':' and '-' or a single operator.
            if cursor.match_lexeme(":-") is None:
                cursor.expect_lexeme(":")
                cursor.expect_lexeme("-")
            body: list[str] = []
            # Body may be empty (fact-like rule).
            if (
                not cursor.is_eof()
                and cursor.current().lexeme
                not in {")", ",", "and", "∧", "&", "&&"}
                and cursor.current().kind
                in {TokenKind.IDENTIFIER.value, TokenKind.KEYWORD.value}
            ):
                first = cursor.expect_ident()
                body.append(first.lexeme)
                while cursor.current().lexeme == ",":
                    # Ambiguous: comma may start next statement.
                    nxt = cursor.peek()
                    if nxt.lexeme.casefold() in _STATEMENT_ATOMS or nxt.lexeme == "(":
                        break
                    if nxt.kind not in {
                        TokenKind.IDENTIFIER.value,
                        TokenKind.KEYWORD.value,
                    }:
                        break
                    cursor.advance()
                    body.append(cursor.expect_ident().lexeme)
            end_range = (
                cursor.tokens[cursor.index - 1].range
                if cursor.index > 0
                else start.range
            )
            span = cursor.range_span(start.range, end_range)
            return self._build_rule(
                head.lexeme, tuple(body), defeasible, profile, span
            )

        if name in {"status", "query"}:
            cursor.expect_lexeme("(", code=CODE_UNBALANCED)
            ident = cursor.expect_ident()
            end = cursor.expect_lexeme(")", code=CODE_UNBALANCED)
            span = cursor.range_span(start.range, end.range)
            return self._build_status_query(ident.lexeme, profile, span)

        raise _ParseFail(
            _diag(
                code=CODE_UNSUPPORTED_CONSTRUCT,
                message=f"unsupported construct {name!r}",
                range=start.range,
            )
        )

    # -- builders ----------------------------------------------------------

    def _build_argument(
        self,
        name: str,
        profile: ArgumentationProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "kind": "argument",
            "name": name,
            "profile_id": profile.profile_id,
            "schema_version": ARG_ARGUMENT_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("arg"),
            family=ARG_FAMILY_ID,
            profile=profile.profile_id,
            features=("argumentation.argument",),
            payload_schema=ARG_ARGUMENT_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_attack(
        self,
        attacker: str,
        target: str,
        profile: ArgumentationProfile,
        span: SourceRange,
    ) -> LogicNode:
        if attacker == target and not profile.admit_self_attack:
            raise _ParseFail(
                _diag(
                    code=CODE_SELF_ATTACK,
                    message=(
                        f"self-attack {attacker!r} is not admitted by profile "
                        f"{profile.profile_id!r}"
                    ),
                    range=span,
                    remediation="Enable admit_self_attack or remove self-attack",
                )
            )
        payload = {
            "attacker": attacker,
            "kind": "attack",
            "profile_id": profile.profile_id,
            "schema_version": ARG_ATTACK_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
            "target": target,
        }
        return mk_extension(
            self._nid("attack"),
            family=ARG_FAMILY_ID,
            profile=profile.profile_id,
            features=("argumentation.attack",),
            payload_schema=ARG_ATTACK_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_support(
        self,
        supporter: str,
        target: str,
        profile: ArgumentationProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "kind": "support",
            "profile_id": profile.profile_id,
            "schema_version": ARG_SUPPORT_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
            "supporter": supporter,
            "target": target,
        }
        return mk_extension(
            self._nid("support"),
            family=ARG_FAMILY_ID,
            profile=profile.profile_id,
            features=("argumentation.support",),
            payload_schema=ARG_SUPPORT_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_priority(
        self,
        higher: str,
        lower: str,
        profile: ArgumentationProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "higher": higher,
            "kind": "priority",
            "lower": lower,
            "profile_id": profile.profile_id,
            "schema_version": ARG_PRIORITY_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("priority"),
            family=ARG_FAMILY_ID,
            profile=profile.profile_id,
            features=("argumentation.priority",),
            payload_schema=ARG_PRIORITY_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_rule(
        self,
        head: str,
        body: tuple[str, ...],
        defeasible: bool,
        profile: ArgumentationProfile,
        span: SourceRange,
    ) -> LogicNode:
        schema = (
            ARG_DEFEASIBLE_RULE_PAYLOAD_SCHEMA
            if defeasible
            else ARG_STRICT_RULE_PAYLOAD_SCHEMA
        )
        feature = (
            "argumentation.defeasible_rule"
            if defeasible
            else "argumentation.strict_rule"
        )
        family = (
            NONMONOTONIC_FAMILY_ID
            if profile.semantics is ArgumentationSemantics.DEFEASIBLE
            or (
                isinstance(profile.semantics, str)
                and profile.semantics == ArgumentationSemantics.DEFEASIBLE.value
            )
            else ARG_FAMILY_ID
        )
        payload = {
            "body": list(body),
            "defeasible": defeasible,
            "head": head,
            "kind": "defeasible_rule" if defeasible else "strict_rule",
            "priority": 0,
            "profile_id": profile.profile_id,
            "rule_id": f"rule:{head}:{','.join(body)}",
            "schema_version": schema,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("rule"),
            family=family,
            profile=profile.profile_id,
            features=(feature,),
            payload_schema=schema,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )

    def _build_status_query(
        self,
        argument: str,
        profile: ArgumentationProfile,
        span: SourceRange,
    ) -> LogicNode:
        payload = {
            "argument": argument,
            "kind": "status_query",
            "profile_id": profile.profile_id,
            "schema_version": ARG_STATUS_QUERY_PAYLOAD_SCHEMA,
            "semantics": profile.semantics_name,
        }
        return mk_extension(
            self._nid("status"),
            family=ARG_FAMILY_ID,
            profile=profile.profile_id,
            features=("argumentation.status_query",),
            payload_schema=ARG_STATUS_QUERY_PAYLOAD_SCHEMA,
            payload=payload,
            sort=BOOL_SORT,
            range=span,
        )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class ArgumentationLogic:
    """Facade for ``ArgumentationLogic@1``."""

    interface: ClassVar[str] = ARGUMENTATION_LOGIC_INTERFACE

    def __init__(
        self,
        profile: ArgumentationProfile | None = None,
        *,
        print_style: str = PrintStyle.ASCII,
    ) -> None:
        self.profile = profile or profile_grounded()
        self.parser = ArgumentationParser(self.profile, print_style=print_style)
        self.printer = ArgumentationPrinter(style=print_style)

    def parse_text(self, text: str, **kwargs: Any) -> ArgumentationParseResult:
        document_id = str(kwargs.pop("document_id", "doc:arg:1"))
        mode = kwargs.pop("mode", ParseMode.STRICT)
        limits = kwargs.pop("limits", None)
        request_id = str(kwargs.pop("request_id", "req:arg:1"))
        expression_id = str(kwargs.pop("expression_id", "expr:arg:1"))
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
            raise ArgumentationParseError(
                "argumentation parse failed",
                diagnostics=result.diagnostics,
                result=result,
            )
        return result.expression

    def print(self, node: LogicNode | TypedExpression) -> str:
        return self.printer.print(node)

    def evaluate(
        self,
        framework: ArgumentationFramework | LogicNode | ArgumentationParseResult,
        *,
        profile: ArgumentationProfile | None = None,
    ) -> ArgumentationEvaluation:
        prof = profile or self.profile
        if isinstance(framework, ArgumentationParseResult):
            if framework.framework is None:
                raise ArgumentationParseError(
                    "parse result has no framework to evaluate"
                )
            fw = framework.framework
            if framework.profile is not None and profile is None:
                prof = framework.profile
        elif isinstance(framework, LogicNode):
            fw = extract_framework(framework)
        elif isinstance(framework, ArgumentationFramework):
            fw = framework
        else:
            raise SyntaxContractError(
                "evaluate requires ArgumentationFramework, LogicNode, or parse result"
            )
        return evaluate_framework(fw, prof)

    def attach_evidence(
        self,
        result: ArgumentationParseResult,
        evidence: ArgumentationEvidenceContract,
        *,
        document_id: str = "doc:arg:1",
    ) -> ArgumentationLoweringReceipt:
        """Attach evidence while retaining authority ceilings."""

        if result.profile is None:
            raise ArgumentationParseError(
                "cannot attach evidence without a profile on the parse result"
            )
        retained = retain_authority_ceiling(evidence)
        evaluation = (
            result.evaluation.to_dict()
            if result.evaluation is not None
            else {}
        )
        return ArgumentationLoweringReceipt(
            document_id=document_id,
            profile_id=result.profile.profile_id,
            semantics=result.profile.semantics_name,
            evaluation=evaluation,
            evidence=retained,
            authorizes_classical_entailment=False,
        )


def parse_argumentation(
    text: str,
    profile: ArgumentationProfile | None = None,
    **kwargs: Any,
) -> ArgumentationParseResult:
    """Parse argumentation / nonmonotonic *text* under named *profile*."""

    logic = ArgumentationLogic(profile or profile_grounded())
    return logic.parse_text(text, **kwargs)


def print_argumentation(
    node: LogicNode | TypedExpression,
    *,
    style: str = PrintStyle.ASCII,
) -> str:
    return ArgumentationPrinter(style=style).print(node)


def parse_print_parse(
    text: str,
    profile: ArgumentationProfile | None = None,
) -> tuple[ArgumentationParseResult, ArgumentationParseResult, bool]:
    """Parse, print, re-parse; return both results and alpha-equivalence."""

    prof = profile or profile_grounded()
    first = parse_argumentation(text, prof)
    if not first.ok or first.root is None:
        return first, first, False
    printed = print_argumentation(first.root)
    second = parse_argumentation(printed, prof)
    if not second.ok or second.root is None:
        return first, second, False
    equivalent = alpha_equivalent(first.root, second.root)
    return first, second, equivalent


__all__ = [
    "ARGUMENTATION_LOGIC_INTERFACE",
    "ARGUMENTATION_PROFILE_INTERFACE",
    "NONMONOTONIC_PROFILE_INTERFACE",
    "ARG_FAMILY_ID",
    "ARG_NOTATION_ID",
    "NONMONOTONIC_FAMILY_ID",
    "DEFEASIBLE_FAMILY_ID",
    "ArgumentLabel",
    "ArgumentLabeling",
    "ArgumentationEvaluation",
    "ArgumentationEvidenceContract",
    "ArgumentationFramework",
    "ArgumentationLogic",
    "ArgumentationLoweringReceipt",
    "ArgumentationParseError",
    "ArgumentationParseResult",
    "ArgumentationParser",
    "ArgumentationPrinter",
    "ArgumentationProfile",
    "ArgumentationSemantics",
    "AuthorityPromotionError",
    "BoundednessKind",
    "DefeasibleRule",
    "EvidenceAuthority",
    "EvidenceSource",
    "PrintStyle",
    "argumentation_semantic_identity",
    "complete_evidence_contract",
    "defeasible_evidence_contract",
    "evaluate_framework",
    "extract_framework",
    "grounded_evidence_contract",
    "parse_argumentation",
    "parse_print_parse",
    "preferred_evidence_contract",
    "print_argumentation",
    "profile_complete",
    "profile_defeasible",
    "profile_grounded",
    "profile_preferred",
    "profile_stable",
    "retain_authority_ceiling",
    "stable_evidence_contract",
    # Diagnostic codes
    "CODE_AUTHORITY_CEILING",
    "CODE_EMPTY_INPUT",
    "CODE_MULTI_EXTENSION_COLLAPSE",
    "CODE_PROFILE_MISMATCH",
    "CODE_PROFILE_REQUIRED",
    "CODE_PROMOTION_REJECTED",
    "CODE_SELF_ATTACK",
    "CODE_UNDECIDED_COLLAPSE",
    "CODE_UNEXPECTED_TOKEN",
]
