"""Shared semantic SMT compiler for software-verification obligations.

``SoftwareVerificationSMTCompiler@1`` lowers supported verification conditions
and Horn/CHC reachability obligations into deterministic SMT-LIB 2.6 scripts
with typed sorts, theories, declarations, assumptions, goals, optional
model / unsat-core requests, and loss-aware translation receipts.

Fail-closed rules
-----------------
* theorem-by-negation, satisfiability, and fixed-point queries are explicit
  query modes — they never collapse into each other;
* PDR/IC3 are capability-bound engine claims, never silent native SMT-LIB
  encodings;
* unsupported temporal, heap, concurrency, or refinement features raise
  rather than becoming uninterpreted native claims.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import BoundednessKind, EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.software_verification.receipts import LogicTranslationReceipt
from ipfs_datasets_py.logic.software_verification.translations import (
    ApproximationDirection,
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    SemanticMutation,
    SemanticMutationKind,
    TranslationBound,
    UnsupportedConstruct,
    UnsupportedHandling,
)

SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE: Final = "SoftwareVerificationSMTCompiler@1"
SMT_COMPILER_ID: Final = "compiler:software-verification-smt"
SMT_COMPILER_VERSION: Final = "1.0.0"
SMT_COMPILATION_SCHEMA_VERSION: Final = "software-verification-smt-compilation/v1"
SMT_OBLIGATION_SCHEMA_VERSION: Final = "software-verification-smt-obligation/v1"
SMT_SCRIPT_SCHEMA_VERSION: Final = "software-verification-smt-script/v1"
SMT_SOURCE_FAMILY_ID: Final = "software_verification"
SMT_SOURCE_FAMILY_VERSION: Final = "1.0.0"
SMT_TARGET_FAMILY_ID: Final = "smt"
SMT_TARGET_FAMILY_VERSION: Final = "2.6"
SMTLIB_VERSION: Final = "2.6"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._:/-]{0,255}$")
_SMT_SAFE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_RESERVED_SMT = frozenset(
    {
        "Bool",
        "Int",
        "Real",
        "Array",
        "true",
        "false",
        "and",
        "or",
        "not",
        "=>",
        "=",
        "distinct",
        "ite",
        "forall",
        "exists",
        "let",
        "as",
        "par",
        "assert",
        "check-sat",
        "declare-fun",
        "declare-const",
        "declare-sort",
        "declare-datatypes",
        "define-fun",
        "set-logic",
        "set-option",
        "set-info",
        "get-model",
        "get-unsat-core",
    }
)


class SmtCompilerError(ValueError):
    """Raised when an SMT obligation cannot be lowered without semantic loss."""


class UnsupportedSmtFeatureError(SmtCompilerError):
    """Raised when a feature cannot become a native uninterpreted claim."""


class SmtQueryMode(StrEnum):
    """Explicit SMT query mode.

    * ``THEOREM_BY_NEGATION`` — assert the negation of the goal and ask SAT
      (unsat means the theorem holds under the assumptions).
    * ``SATISFIABILITY`` — assert the goal positively.
    * ``FIXED_POINT`` — emit a Horn/CHC fixed-point query (``HORN`` logic).
    """

    THEOREM_BY_NEGATION = "theorem_by_negation"
    SATISFIABILITY = "satisfiability"
    FIXED_POINT = "fixed_point"


class SmtTheory(StrEnum):
    """SMT-LIB theory fragments requested by a compilation."""

    CORE = "core"
    EQUALITY = "equality"
    ARITHMETIC = "arithmetic"
    ARRAYS = "arrays"
    DATATYPES = "datatypes"
    QUANTIFIERS = "quantifiers"
    HORN = "horn"


class SmtFeature(StrEnum):
    """Feature tags used for support decisions and receipts."""

    ARITHMETIC = "arithmetic"
    EQUALITY = "equality"
    ARRAYS = "arrays_maps"
    DATATYPES = "datatypes"
    QUANTIFIERS = "quantifiers"
    HORN_CHC = "horn_chc_reachability"
    STATE_TRANSITIONS = "state_transitions"
    VERIFICATION_CONDITIONS = "verification_conditions"
    HEAP_RESOURCE = "heap_resource_fragments"
    INTERFERENCE = "interference"
    REFINEMENT = "refinement"
    TEMPORAL = "temporal"
    SEPARATION_WAND = "separation_wand"
    UNBOUNDED_CONCURRENCY = "unbounded_concurrency"
    UNBOUNDED_REFINEMENT = "unbounded_refinement"
    PDR = "pdr"
    IC3 = "ic3"


class SmtCapabilityKind(StrEnum):
    """How a capability is exposed to consumers."""

    NATIVE = "native"
    TRANSLATED = "translated"
    CAPABILITY_BOUND = "capability_bound"
    UNSUPPORTED = "unsupported"


class SmtTermKind(StrEnum):
    """Kinds of structured SMT terms accepted by the compiler."""

    TRUE = "true"
    FALSE = "false"
    INT = "int"
    REAL = "real"
    BOOL = "bool"
    SYMBOL = "symbol"
    APPLY = "apply"
    NOT = "not"
    AND = "and"
    OR = "or"
    IMPLIES = "implies"
    IFF = "iff"
    EQ = "eq"
    DISTINCT = "distinct"
    ITE = "ite"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    MOD = "mod"
    NEG = "neg"
    SELECT = "select"
    STORE = "store"
    FORALL = "forall"
    EXISTS = "exists"
    DATATYPE_CONSTRUCTOR = "datatype_constructor"
    DATATYPE_SELECTOR = "datatype_selector"
    DATATYPE_TESTER = "datatype_tester"
    RAW = "raw"


# Features the compiler lowers natively into SMT-LIB.
_NATIVE_FEATURES: Final[frozenset[SmtFeature]] = frozenset(
    {
        SmtFeature.ARITHMETIC,
        SmtFeature.EQUALITY,
        SmtFeature.ARRAYS,
        SmtFeature.DATATYPES,
        SmtFeature.QUANTIFIERS,
        SmtFeature.HORN_CHC,
        SmtFeature.STATE_TRANSITIONS,
        SmtFeature.VERIFICATION_CONDITIONS,
        SmtFeature.HEAP_RESOURCE,
        SmtFeature.INTERFERENCE,
        SmtFeature.REFINEMENT,
    }
)

# Features that never become uninterpreted native claims.
_HARD_UNSUPPORTED: Final[frozenset[SmtFeature]] = frozenset(
    {
        SmtFeature.TEMPORAL,
        SmtFeature.SEPARATION_WAND,
        SmtFeature.UNBOUNDED_CONCURRENCY,
        SmtFeature.UNBOUNDED_REFINEMENT,
    }
)

# Engine-level claims that remain capability-bound (not native SMT-LIB).
_CAPABILITY_BOUND: Final[frozenset[SmtFeature]] = frozenset(
    {
        SmtFeature.PDR,
        SmtFeature.IC3,
    }
)

_THEORY_TO_LOGIC: Final[dict[frozenset[SmtTheory], str]] = {}


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        qualifier = "an empty or " if optional else "a "
        raise SmtCompilerError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _IDENTIFIER_RE.fullmatch(result):
        raise SmtCompilerError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise SmtCompilerError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SmtCompilerError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise SmtCompilerError(f"{label} must be a sequence")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise SmtCompilerError(f"{label} must be immutable JSON data") from error


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise SmtCompilerError(f"{label} must be a boolean")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SmtCompilerError(f"unknown {label} field(s): {', '.join(unknown)}")


def smt_sanitize(name: str, *, prefix: str = "x") -> str:
    """Map an arbitrary identifier to a deterministic SMT-LIB symbol."""

    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    if cleaned in _RESERVED_SMT or not _SMT_SAFE_RE.fullmatch(cleaned):
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        cleaned = f"{prefix}_{digest}"
    return cleaned


def _implementation_identity() -> str:
    """Content-address the compiler source surface for receipt pinning."""

    payload = {
        "compiler_id": SMT_COMPILER_ID,
        "compiler_version": SMT_COMPILER_VERSION,
        "interface": SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE,
        "schema_version": SMT_COMPILATION_SCHEMA_VERSION,
        "native_features": sorted(feature.value for feature in _NATIVE_FEATURES),
        "capability_bound": sorted(feature.value for feature in _CAPABILITY_BOUND),
        "hard_unsupported": sorted(feature.value for feature in _HARD_UNSUPPORTED),
    }
    return f"sha256:{stable_digest(payload)}"


@dataclass(frozen=True, slots=True)
class SmtSort:
    """A named SMT sort reference."""

    name: str
    arity: int = 0
    parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "sort name"))
        if not isinstance(self.arity, int) or isinstance(self.arity, bool) or self.arity < 0:
            raise SmtCompilerError("sort arity must be a non-negative integer")
        parameters = tuple(_text(item, "sort parameter") for item in self.parameters)
        object.__setattr__(self, "parameters", parameters)

    def render(self) -> str:
        if self.parameters:
            return f"({' '.join([self.name, *self.parameters])})"
        return self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "arity": self.arity,
            "name": self.name,
            "parameters": list(self.parameters),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtSort:
        value = _mapping(value, "sort")
        return cls(
            name=value.get("name", ""),
            arity=value.get("arity", 0),
            parameters=tuple(value.get("parameters", ())),
        )


BOOL_SORT: Final = SmtSort("Bool")
INT_SORT: Final = SmtSort("Int")
REAL_SORT: Final = SmtSort("Real")


def array_sort(index: SmtSort | str, element: SmtSort | str) -> SmtSort:
    index_name = index.name if isinstance(index, SmtSort) else index
    element_name = element.name if isinstance(element, SmtSort) else element
    return SmtSort("Array", arity=2, parameters=(index_name, element_name))


@dataclass(frozen=True, slots=True)
class SmtFunDecl:
    """Function or constant declaration."""

    name: str
    domain: tuple[SmtSort, ...] = ()
    range: SmtSort = BOOL_SORT
    is_const: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "function name"))
        domain = tuple(
            item if isinstance(item, SmtSort) else SmtSort.from_dict(_mapping(item, "domain sort"))
            for item in self.domain
        )
        object.__setattr__(self, "domain", domain)
        range_sort = self.range
        if not isinstance(range_sort, SmtSort):
            range_sort = SmtSort.from_dict(_mapping(range_sort, "range sort"))
        object.__setattr__(self, "range", range_sort)
        object.__setattr__(self, "is_const", _bool(self.is_const, "is_const"))
        if self.is_const and domain:
            raise SmtCompilerError("constants must have an empty domain")

    def render(self) -> str:
        if self.is_const or not self.domain:
            return f"(declare-const {self.name} {self.range.render()})"
        domain = " ".join(sort.render() for sort in self.domain)
        return f"(declare-fun {self.name} ({domain}) {self.range.render()})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": [item.to_dict() for item in self.domain],
            "is_const": self.is_const,
            "name": self.name,
            "range": self.range.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtFunDecl:
        value = _mapping(value, "function declaration")
        return cls(
            name=value.get("name", ""),
            domain=tuple(value.get("domain", ())),
            range=value.get("range", BOOL_SORT.to_dict()),
            is_const=value.get("is_const", False),
        )


@dataclass(frozen=True, slots=True)
class SmtDatatypeConstructor:
    """One constructor of an algebraic datatype."""

    name: str
    selectors: tuple[tuple[str, SmtSort], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "constructor name"))
        selectors: list[tuple[str, SmtSort]] = []
        for item in self.selectors:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise SmtCompilerError("datatype selectors must be (name, sort) pairs")
            selector_name = _text(item[0], "selector name")
            selector_sort = (
                item[1]
                if isinstance(item[1], SmtSort)
                else SmtSort.from_dict(_mapping(item[1], "selector sort"))
            )
            selectors.append((selector_name, selector_sort))
        object.__setattr__(self, "selectors", tuple(selectors))

    def render(self) -> str:
        if not self.selectors:
            return f"({self.name})"
        parts = " ".join(
            f"({selector} {sort.render()})" for selector, sort in self.selectors
        )
        return f"({self.name} {parts})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "selectors": [
                {"name": name, "sort": sort.to_dict()} for name, sort in self.selectors
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtDatatypeConstructor:
        value = _mapping(value, "datatype constructor")
        selectors = []
        for item in value.get("selectors", ()):
            item = _mapping(item, "selector")
            selectors.append((item.get("name", ""), item.get("sort", {})))
        return cls(name=value.get("name", ""), selectors=tuple(selectors))


@dataclass(frozen=True, slots=True)
class SmtDatatypeDecl:
    """Algebraic datatype declaration."""

    name: str
    constructors: tuple[SmtDatatypeConstructor, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "datatype name"))
        constructors = tuple(
            item
            if isinstance(item, SmtDatatypeConstructor)
            else SmtDatatypeConstructor.from_dict(_mapping(item, "constructor"))
            for item in self.constructors
        )
        if not constructors:
            raise SmtCompilerError("datatype requires at least one constructor")
        names = [item.name for item in constructors]
        if len(names) != len(set(names)):
            raise SmtCompilerError("datatype constructor names must be unique")
        object.__setattr__(self, "constructors", constructors)

    def render(self) -> str:
        constructors = " ".join(item.render() for item in self.constructors)
        return f"(declare-datatypes () (({self.name} {constructors})))"

    def to_dict(self) -> dict[str, Any]:
        return {
            "constructors": [item.to_dict() for item in self.constructors],
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtDatatypeDecl:
        value = _mapping(value, "datatype declaration")
        return cls(
            name=value.get("name", ""),
            constructors=tuple(value.get("constructors", ())),
        )


@dataclass(frozen=True, slots=True)
class SmtBinder:
    """Quantifier binder ``(name sort)``."""

    name: str
    sort: SmtSort

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "binder name"))
        sort = self.sort if isinstance(self.sort, SmtSort) else SmtSort.from_dict(
            _mapping(self.sort, "binder sort")
        )
        object.__setattr__(self, "sort", sort)

    def render(self) -> str:
        return f"({self.name} {self.sort.render()})"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "sort": self.sort.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtBinder:
        value = _mapping(value, "binder")
        return cls(name=value.get("name", ""), sort=value.get("sort", BOOL_SORT.to_dict()))


@dataclass(frozen=True, slots=True)
class SmtTerm:
    """Structured SMT term / formula."""

    kind: SmtTermKind | str
    value: str = ""
    arguments: tuple[SmtTerm, ...] = ()
    binders: tuple[SmtBinder, ...] = ()
    sort: SmtSort | None = None

    def __post_init__(self) -> None:
        kind = _enum(self.kind, SmtTermKind, "term kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", _text(self.value, "term value", optional=True))
        arguments = tuple(
            item if isinstance(item, SmtTerm) else SmtTerm.from_dict(_mapping(item, "term arg"))
            for item in self.arguments
        )
        object.__setattr__(self, "arguments", arguments)
        binders = tuple(
            item if isinstance(item, SmtBinder) else SmtBinder.from_dict(_mapping(item, "binder"))
            for item in self.binders
        )
        object.__setattr__(self, "binders", binders)
        if self.sort is not None and not isinstance(self.sort, SmtSort):
            object.__setattr__(
                self, "sort", SmtSort.from_dict(_mapping(self.sort, "term sort"))
            )
        self._validate_shape()

    def _validate_shape(self) -> None:
        kind = self.kind
        if kind in {SmtTermKind.TRUE, SmtTermKind.FALSE}:
            if self.arguments or self.value or self.binders:
                raise SmtCompilerError(f"{kind.value} takes no payload")
        elif kind in {SmtTermKind.INT, SmtTermKind.REAL, SmtTermKind.BOOL, SmtTermKind.SYMBOL}:
            if not self.value:
                raise SmtCompilerError(f"{kind.value} requires a value")
            if self.arguments or self.binders:
                raise SmtCompilerError(f"{kind.value} takes no arguments or binders")
            if kind is SmtTermKind.INT:
                try:
                    int(self.value)
                except ValueError as error:
                    raise SmtCompilerError("int term value must be an integer literal") from error
            if kind is SmtTermKind.REAL:
                try:
                    float(self.value)
                except ValueError as error:
                    raise SmtCompilerError("real term value must be a numeric literal") from error
            if kind is SmtTermKind.BOOL and self.value not in {"true", "false"}:
                raise SmtCompilerError("bool term value must be 'true' or 'false'")
        elif kind is SmtTermKind.RAW:
            if not self.value:
                raise SmtCompilerError("raw term requires SMT-LIB text")
            if self.arguments or self.binders:
                raise SmtCompilerError("raw term takes no arguments or binders")
        elif kind is SmtTermKind.NOT:
            if len(self.arguments) != 1:
                raise SmtCompilerError("not requires exactly one argument")
        elif kind in {
            SmtTermKind.AND,
            SmtTermKind.OR,
            SmtTermKind.ADD,
            SmtTermKind.MUL,
            SmtTermKind.DISTINCT,
        }:
            if len(self.arguments) < 2:
                raise SmtCompilerError(f"{kind.value} requires at least two arguments")
        elif kind in {
            SmtTermKind.IMPLIES,
            SmtTermKind.IFF,
            SmtTermKind.EQ,
            SmtTermKind.LT,
            SmtTermKind.LE,
            SmtTermKind.GT,
            SmtTermKind.GE,
            SmtTermKind.SUB,
            SmtTermKind.DIV,
            SmtTermKind.MOD,
            SmtTermKind.SELECT,
        }:
            if len(self.arguments) != 2:
                raise SmtCompilerError(f"{kind.value} requires exactly two arguments")
        elif kind is SmtTermKind.NEG:
            if len(self.arguments) != 1:
                raise SmtCompilerError("neg requires exactly one argument")
        elif kind is SmtTermKind.ITE:
            if len(self.arguments) != 3:
                raise SmtCompilerError("ite requires exactly three arguments")
        elif kind is SmtTermKind.STORE:
            if len(self.arguments) != 3:
                raise SmtCompilerError("store requires array, index, and value")
        elif kind is SmtTermKind.APPLY:
            if not self.value:
                raise SmtCompilerError("apply requires a function symbol")
        elif kind in {SmtTermKind.FORALL, SmtTermKind.EXISTS}:
            if not self.binders:
                raise SmtCompilerError(f"{kind.value} requires binders")
            if len(self.arguments) != 1:
                raise SmtCompilerError(f"{kind.value} requires exactly one body")
        elif kind in {
            SmtTermKind.DATATYPE_CONSTRUCTOR,
            SmtTermKind.DATATYPE_SELECTOR,
            SmtTermKind.DATATYPE_TESTER,
        }:
            if not self.value:
                raise SmtCompilerError(f"{kind.value} requires a constructor/selector name")
        else:  # pragma: no cover - closed enum
            raise SmtCompilerError(f"unsupported term kind {kind!r}")

    def render(self) -> str:
        kind = self.kind
        if kind is SmtTermKind.TRUE:
            return "true"
        if kind is SmtTermKind.FALSE:
            return "false"
        if kind is SmtTermKind.INT:
            return self.value if not self.value.startswith("-") else f"(- {self.value[1:]})"
        if kind is SmtTermKind.REAL:
            return self.value if not self.value.startswith("-") else f"(- {self.value[1:]})"
        if kind is SmtTermKind.BOOL:
            return self.value
        if kind is SmtTermKind.SYMBOL:
            return self.value
        if kind is SmtTermKind.RAW:
            return self.value
        if kind is SmtTermKind.NOT:
            return f"(not {self.arguments[0].render()})"
        if kind is SmtTermKind.AND:
            return f"(and {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.OR:
            return f"(or {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.IMPLIES:
            return f"(=> {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.IFF:
            return f"(= {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.EQ:
            return f"(= {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.DISTINCT:
            return f"(distinct {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.ITE:
            a, b, c = self.arguments
            return f"(ite {a.render()} {b.render()} {c.render()})"
        if kind is SmtTermKind.LT:
            return f"(< {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.LE:
            return f"(<= {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.GT:
            return f"(> {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.GE:
            return f"(>= {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.ADD:
            return f"(+ {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.SUB:
            return f"(- {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.MUL:
            return f"(* {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.DIV:
            return f"(div {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.MOD:
            return f"(mod {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.NEG:
            return f"(- {self.arguments[0].render()})"
        if kind is SmtTermKind.SELECT:
            return f"(select {self.arguments[0].render()} {self.arguments[1].render()})"
        if kind is SmtTermKind.STORE:
            a, i, v = self.arguments
            return f"(store {a.render()} {i.render()} {v.render()})"
        if kind is SmtTermKind.APPLY:
            if not self.arguments:
                return self.value
            return f"({self.value} {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.FORALL:
            binders = " ".join(item.render() for item in self.binders)
            return f"(forall ({binders}) {self.arguments[0].render()})"
        if kind is SmtTermKind.EXISTS:
            binders = " ".join(item.render() for item in self.binders)
            return f"(exists ({binders}) {self.arguments[0].render()})"
        if kind is SmtTermKind.DATATYPE_CONSTRUCTOR:
            if not self.arguments:
                return self.value
            return f"({self.value} {' '.join(arg.render() for arg in self.arguments)})"
        if kind is SmtTermKind.DATATYPE_SELECTOR:
            if len(self.arguments) != 1:
                raise SmtCompilerError("datatype selector requires exactly one argument")
            return f"({self.value} {self.arguments[0].render()})"
        if kind is SmtTermKind.DATATYPE_TESTER:
            if len(self.arguments) != 1:
                raise SmtCompilerError("datatype tester requires exactly one argument")
            return f"((_ is {self.value}) {self.arguments[0].render()})"
        raise SmtCompilerError(f"cannot render term kind {kind!r}")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "arguments": [item.to_dict() for item in self.arguments],
            "binders": [item.to_dict() for item in self.binders],
            "kind": self.kind.value,
            "value": self.value,
        }
        if self.sort is not None:
            payload["sort"] = self.sort.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtTerm:
        value = _mapping(value, "term")
        return cls(
            kind=value.get("kind", ""),
            value=value.get("value", ""),
            arguments=tuple(value.get("arguments", ())),
            binders=tuple(value.get("binders", ())),
            sort=value.get("sort"),
        )


def term_true() -> SmtTerm:
    return SmtTerm(SmtTermKind.TRUE)


def term_false() -> SmtTerm:
    return SmtTerm(SmtTermKind.FALSE)


def term_int(value: int) -> SmtTerm:
    return SmtTerm(SmtTermKind.INT, value=str(int(value)))


def term_symbol(name: str) -> SmtTerm:
    return SmtTerm(SmtTermKind.SYMBOL, value=_text(name, "symbol"))


def term_eq(left: SmtTerm, right: SmtTerm) -> SmtTerm:
    return SmtTerm(SmtTermKind.EQ, arguments=(left, right))


def term_and(*args: SmtTerm) -> SmtTerm:
    if not args:
        return term_true()
    if len(args) == 1:
        return args[0]
    return SmtTerm(SmtTermKind.AND, arguments=args)


def term_or(*args: SmtTerm) -> SmtTerm:
    if not args:
        return term_false()
    if len(args) == 1:
        return args[0]
    return SmtTerm(SmtTermKind.OR, arguments=args)


def term_not(body: SmtTerm) -> SmtTerm:
    return SmtTerm(SmtTermKind.NOT, arguments=(body,))


def term_implies(antecedent: SmtTerm, consequent: SmtTerm) -> SmtTerm:
    return SmtTerm(SmtTermKind.IMPLIES, arguments=(antecedent, consequent))


def term_apply(name: str, *args: SmtTerm) -> SmtTerm:
    return SmtTerm(SmtTermKind.APPLY, value=name, arguments=args)


@dataclass(frozen=True, slots=True)
class SmtNamedAssertion:
    """An assumption or goal fragment, optionally named for unsat cores."""

    formula: SmtTerm
    name: str = ""

    def __post_init__(self) -> None:
        formula = (
            self.formula
            if isinstance(self.formula, SmtTerm)
            else SmtTerm.from_dict(_mapping(self.formula, "formula"))
        )
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "name", _text(self.name, "assertion name", optional=True))

    def render(self) -> str:
        body = self.formula.render()
        if self.name:
            return f"(assert (! {body} :named {smt_sanitize(self.name, prefix='a')}))"
        return f"(assert {body})"

    def to_dict(self) -> dict[str, Any]:
        return {"formula": self.formula.to_dict(), "name": self.name}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtNamedAssertion:
        value = _mapping(value, "named assertion")
        return cls(formula=value.get("formula", {}), name=value.get("name", ""))


@dataclass(frozen=True, slots=True)
class HornClause:
    """One constrained Horn clause ``body => head`` (body may be empty)."""

    clause_id: str
    head: SmtTerm
    body: tuple[SmtTerm, ...] = ()
    is_query: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "clause_id", _identifier(self.clause_id, "clause_id"))
        head = self.head if isinstance(self.head, SmtTerm) else SmtTerm.from_dict(
            _mapping(self.head, "horn head")
        )
        object.__setattr__(self, "head", head)
        body = tuple(
            item if isinstance(item, SmtTerm) else SmtTerm.from_dict(_mapping(item, "horn body"))
            for item in self.body
        )
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "is_query", _bool(self.is_query, "is_query"))

    def as_implication(self) -> SmtTerm:
        if not self.body:
            return self.head
        if len(self.body) == 1:
            return term_implies(self.body[0], self.head)
        return term_implies(term_and(*self.body), self.head)

    def to_dict(self) -> dict[str, Any]:
        return {
            "body": [item.to_dict() for item in self.body],
            "clause_id": self.clause_id,
            "head": self.head.to_dict(),
            "is_query": self.is_query,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HornClause:
        value = _mapping(value, "horn clause")
        return cls(
            clause_id=value.get("clause_id", ""),
            head=value.get("head", {}),
            body=tuple(value.get("body", ())),
            is_query=value.get("is_query", False),
        )


@dataclass(frozen=True, slots=True)
class SmtCapability:
    """Declared compiler capability for one feature."""

    feature: SmtFeature | str
    kind: SmtCapabilityKind | str
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature", _enum(self.feature, SmtFeature, "feature"))
        object.__setattr__(self, "kind", _enum(self.kind, SmtCapabilityKind, "kind"))
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "feature": self.feature.value,
            "kind": self.kind.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtCapability:
        value = _mapping(value, "capability")
        return cls(
            feature=value.get("feature", ""),
            kind=value.get("kind", ""),
            description=value.get("description", ""),
        )


def default_capabilities() -> tuple[SmtCapability, ...]:
    """Canonical capability matrix for the shared semantic SMT compiler."""

    capabilities = [
        SmtCapability(
            feature,
            SmtCapabilityKind.NATIVE,
            f"{feature.value} lowers to deterministic SMT-LIB",
        )
        for feature in _NATIVE_FEATURES
    ]
    capabilities.extend(
        [
            SmtCapability(
                SmtFeature.PDR,
                SmtCapabilityKind.CAPABILITY_BOUND,
                "PDR is an engine strategy, not a native SMT-LIB encoding",
            ),
            SmtCapability(
                SmtFeature.IC3,
                SmtCapabilityKind.CAPABILITY_BOUND,
                "IC3 is an engine strategy, not a native SMT-LIB encoding",
            ),
        ]
    )
    capabilities.extend(
        SmtCapability(
            feature,
            SmtCapabilityKind.UNSUPPORTED,
            f"{feature.value} cannot become an uninterpreted native claim",
        )
        for feature in _HARD_UNSUPPORTED
    )
    return tuple(sorted(capabilities, key=lambda item: item.feature.value))


@dataclass(frozen=True, slots=True)
class SmtObligation:
    """One compile unit for the shared semantic SMT compiler."""

    obligation_id: str
    query_mode: SmtQueryMode | str
    features: tuple[SmtFeature | str, ...]
    goal: SmtTerm | None = None
    assumptions: tuple[SmtNamedAssertion, ...] = ()
    sorts: tuple[SmtSort, ...] = ()
    functions: tuple[SmtFunDecl, ...] = ()
    datatypes: tuple[SmtDatatypeDecl, ...] = ()
    horn_clauses: tuple[HornClause, ...] = ()
    theories: tuple[SmtTheory | str, ...] = ()
    request_model: bool = False
    request_unsat_core: bool = False
    logic: str = ""
    source_family_id: str = SMT_SOURCE_FAMILY_ID
    source_family_version: str = SMT_SOURCE_FAMILY_VERSION
    property_ids: tuple[str, ...] = ()
    bounds: tuple[TranslationBound, ...] = ()
    unsupported_constructs: tuple[UnsupportedConstruct, ...] = ()
    semantic_mutations: tuple[SemanticMutation, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SMT_OBLIGATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "query_mode", _enum(self.query_mode, SmtQueryMode, "query_mode")
        )
        features = tuple(_enum(item, SmtFeature, "features item") for item in self.features)
        if not features:
            raise SmtCompilerError("obligation requires at least one feature tag")
        object.__setattr__(
            self, "features", tuple(sorted(features, key=lambda item: item.value))
        )
        hard = [item for item in features if item in _HARD_UNSUPPORTED]
        if hard:
            raise UnsupportedSmtFeatureError(
                "unsupported features cannot become uninterpreted native claims: "
                + ", ".join(item.value for item in hard)
            )
        capability_only = [item for item in features if item in _CAPABILITY_BOUND]
        if capability_only and self.query_mode is not SmtQueryMode.FIXED_POINT:
            # PDR/IC3 may only be *claimed* alongside a fixed-point query and
            # are never treated as native encodings by themselves.
            raise UnsupportedSmtFeatureError(
                "PDR/IC3 claims require fixed_point query mode and remain capability-bound: "
                + ", ".join(item.value for item in capability_only)
            )

        goal = self.goal
        if goal is not None and not isinstance(goal, SmtTerm):
            goal = SmtTerm.from_dict(_mapping(goal, "goal"))
        object.__setattr__(self, "goal", goal)

        assumptions = tuple(
            item
            if isinstance(item, SmtNamedAssertion)
            else SmtNamedAssertion.from_dict(_mapping(item, "assumption"))
            for item in self.assumptions
        )
        object.__setattr__(self, "assumptions", assumptions)

        sorts = tuple(
            item if isinstance(item, SmtSort) else SmtSort.from_dict(_mapping(item, "sort"))
            for item in self.sorts
        )
        object.__setattr__(
            self, "sorts", tuple(sorted(sorts, key=lambda item: (item.name, item.parameters)))
        )

        functions = tuple(
            item
            if isinstance(item, SmtFunDecl)
            else SmtFunDecl.from_dict(_mapping(item, "function"))
            for item in self.functions
        )
        object.__setattr__(
            self, "functions", tuple(sorted(functions, key=lambda item: item.name))
        )

        datatypes = tuple(
            item
            if isinstance(item, SmtDatatypeDecl)
            else SmtDatatypeDecl.from_dict(_mapping(item, "datatype"))
            for item in self.datatypes
        )
        object.__setattr__(
            self, "datatypes", tuple(sorted(datatypes, key=lambda item: item.name))
        )

        horn_clauses = tuple(
            item
            if isinstance(item, HornClause)
            else HornClause.from_dict(_mapping(item, "horn clause"))
            for item in self.horn_clauses
        )
        object.__setattr__(
            self,
            "horn_clauses",
            tuple(sorted(horn_clauses, key=lambda item: item.clause_id)),
        )

        theories = tuple(_enum(item, SmtTheory, "theories item") for item in self.theories)
        if not theories:
            theories = _infer_theories(self.features, self.query_mode)
        object.__setattr__(
            self, "theories", tuple(sorted(set(theories), key=lambda item: item.value))
        )

        object.__setattr__(self, "request_model", _bool(self.request_model, "request_model"))
        object.__setattr__(
            self, "request_unsat_core", _bool(self.request_unsat_core, "request_unsat_core")
        )
        object.__setattr__(self, "logic", _text(self.logic, "logic", optional=True))
        object.__setattr__(
            self, "source_family_id", _text(self.source_family_id, "source_family_id")
        )
        object.__setattr__(
            self,
            "source_family_version",
            _text(self.source_family_version, "source_family_version"),
        )
        property_ids = tuple(
            _identifier(item, "property_ids item") for item in self.property_ids
        )
        object.__setattr__(self, "property_ids", tuple(sorted(set(property_ids))))

        bounds = tuple(
            item
            if isinstance(item, TranslationBound)
            else TranslationBound.from_dict(_mapping(item, "bound"))
            for item in self.bounds
        )
        object.__setattr__(self, "bounds", bounds)

        unsupported = tuple(
            item
            if isinstance(item, UnsupportedConstruct)
            else UnsupportedConstruct.from_dict(_mapping(item, "unsupported construct"))
            for item in self.unsupported_constructs
        )
        object.__setattr__(self, "unsupported_constructs", unsupported)

        mutations = tuple(
            item
            if isinstance(item, SemanticMutation)
            else SemanticMutation.from_dict(_mapping(item, "semantic mutation"))
            for item in self.semantic_mutations
        )
        object.__setattr__(self, "semantic_mutations", mutations)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))

        if self.schema_version != SMT_OBLIGATION_SCHEMA_VERSION:
            raise SmtCompilerError(
                f"unsupported obligation schema_version {self.schema_version!r}"
            )
        self._validate_query_payload()

    def _validate_query_payload(self) -> None:
        mode = self.query_mode
        if mode is SmtQueryMode.FIXED_POINT:
            if not self.horn_clauses:
                raise SmtCompilerError("fixed_point obligations require Horn clauses")
            queries = [item for item in self.horn_clauses if item.is_query]
            if not queries:
                raise SmtCompilerError("fixed_point obligations require at least one query clause")
            if self.goal is not None:
                raise SmtCompilerError("fixed_point obligations use query clauses, not a goal term")
        else:
            if self.goal is None:
                raise SmtCompilerError(f"{mode.value} obligations require a goal term")
            if self.horn_clauses:
                raise SmtCompilerError(
                    f"{mode.value} obligations must not carry Horn clauses; use fixed_point"
                )
            if mode is SmtQueryMode.THEOREM_BY_NEGATION and self.request_model and not self.request_unsat_core:
                # Models of theorem-by-negation are counter-models; allowed.
                pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "attributes": self.attributes.to_dict(),
            "bounds": [item.to_dict() for item in self.bounds],
            "datatypes": [item.to_dict() for item in self.datatypes],
            "features": [item.value for item in self.features],
            "functions": [item.to_dict() for item in self.functions],
            "goal": None if self.goal is None else self.goal.to_dict(),
            "horn_clauses": [item.to_dict() for item in self.horn_clauses],
            "logic": self.logic,
            "obligation_id": self.obligation_id,
            "property_ids": list(self.property_ids),
            "query_mode": self.query_mode.value,
            "request_model": self.request_model,
            "request_unsat_core": self.request_unsat_core,
            "schema_version": self.schema_version,
            "semantic_mutations": [item.to_dict() for item in self.semantic_mutations],
            "sorts": [item.to_dict() for item in self.sorts],
            "source_family_id": self.source_family_id,
            "source_family_version": self.source_family_version,
            "theories": [item.value for item in self.theories],
            "unsupported_constructs": [item.to_dict() for item in self.unsupported_constructs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtObligation:
        value = _mapping(value, "obligation")
        return cls(
            obligation_id=value.get("obligation_id", ""),
            query_mode=value.get("query_mode", ""),
            features=tuple(value.get("features", ())),
            goal=value.get("goal"),
            assumptions=tuple(value.get("assumptions", ())),
            sorts=tuple(value.get("sorts", ())),
            functions=tuple(value.get("functions", ())),
            datatypes=tuple(value.get("datatypes", ())),
            horn_clauses=tuple(value.get("horn_clauses", ())),
            theories=tuple(value.get("theories", ())),
            request_model=value.get("request_model", False),
            request_unsat_core=value.get("request_unsat_core", False),
            logic=value.get("logic", ""),
            source_family_id=value.get("source_family_id", SMT_SOURCE_FAMILY_ID),
            source_family_version=value.get(
                "source_family_version", SMT_SOURCE_FAMILY_VERSION
            ),
            property_ids=tuple(value.get("property_ids", ())),
            bounds=tuple(value.get("bounds", ())),
            unsupported_constructs=tuple(value.get("unsupported_constructs", ())),
            semantic_mutations=tuple(value.get("semantic_mutations", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", SMT_OBLIGATION_SCHEMA_VERSION),
        )


def _infer_theories(
    features: Sequence[SmtFeature],
    query_mode: SmtQueryMode,
) -> tuple[SmtTheory, ...]:
    theories: set[SmtTheory] = {SmtTheory.CORE, SmtTheory.EQUALITY}
    feature_set = set(features)
    if feature_set & {
        SmtFeature.ARITHMETIC,
        SmtFeature.VERIFICATION_CONDITIONS,
        SmtFeature.STATE_TRANSITIONS,
        SmtFeature.INTERFERENCE,
        SmtFeature.REFINEMENT,
        SmtFeature.HEAP_RESOURCE,
    }:
        theories.add(SmtTheory.ARITHMETIC)
    if SmtFeature.ARRAYS in feature_set or SmtFeature.HEAP_RESOURCE in feature_set:
        theories.add(SmtTheory.ARRAYS)
    if SmtFeature.DATATYPES in feature_set:
        theories.add(SmtTheory.DATATYPES)
    if SmtFeature.QUANTIFIERS in feature_set:
        theories.add(SmtTheory.QUANTIFIERS)
    if SmtFeature.HORN_CHC in feature_set or query_mode is SmtQueryMode.FIXED_POINT:
        theories.add(SmtTheory.HORN)
        theories.add(SmtTheory.QUANTIFIERS)
    return tuple(sorted(theories, key=lambda item: item.value))


def select_smt_logic(theories: Sequence[SmtTheory], query_mode: SmtQueryMode) -> str:
    """Pick a deterministic SMT-LIB logic for the requested theory set."""

    theory_set = set(theories)
    if query_mode is SmtQueryMode.FIXED_POINT or SmtTheory.HORN in theory_set:
        return "HORN"
    quant = SmtTheory.QUANTIFIERS in theory_set
    parts: list[str] = []
    if not quant:
        parts.append("QF_")
    if SmtTheory.ARRAYS in theory_set:
        parts.append("A")
    if SmtTheory.DATATYPES in theory_set:
        parts.append("DT")
    if SmtTheory.EQUALITY in theory_set or SmtTheory.CORE in theory_set:
        parts.append("UF")
    if SmtTheory.ARITHMETIC in theory_set:
        parts.append("LIA")
    logic = "".join(parts)
    if logic in {"", "QF_", "UF", "QF_UF"}:
        return "QF_UF" if not quant else "UF"
    if logic == "QF_UFLIA" or logic == "UFLIA" or logic == "QF_A UFLIA":
        pass
    # Normalize common combinations.
    has_a = SmtTheory.ARRAYS in theory_set
    has_dt = SmtTheory.DATATYPES in theory_set
    has_lia = SmtTheory.ARITHMETIC in theory_set
    prefix = "" if quant else "QF_"
    body = ""
    if has_a:
        body += "A"
    if has_dt:
        body += "DT"
    body += "UF"
    if has_lia:
        body += "LIA"
    return f"{prefix}{body}"


@dataclass(frozen=True, slots=True)
class SmtScript:
    """Deterministic SMT-LIB script artifact."""

    logic: str
    query_mode: SmtQueryMode | str
    lines: tuple[str, ...]
    theories: tuple[SmtTheory | str, ...] = ()
    request_model: bool = False
    request_unsat_core: bool = False
    schema_version: str = SMT_SCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "logic", _text(self.logic, "logic"))
        object.__setattr__(
            self, "query_mode", _enum(self.query_mode, SmtQueryMode, "query_mode")
        )
        lines = tuple(_text(item, "script line") for item in self.lines)
        if not lines:
            raise SmtCompilerError("SMT script requires at least one line")
        object.__setattr__(self, "lines", lines)
        theories = tuple(_enum(item, SmtTheory, "theories item") for item in self.theories)
        object.__setattr__(
            self, "theories", tuple(sorted(theories, key=lambda item: item.value))
        )
        object.__setattr__(self, "request_model", _bool(self.request_model, "request_model"))
        object.__setattr__(
            self, "request_unsat_core", _bool(self.request_unsat_core, "request_unsat_core")
        )
        if self.schema_version != SMT_SCRIPT_SCHEMA_VERSION:
            raise SmtCompilerError(
                f"unsupported script schema_version {self.schema_version!r}"
            )

    @property
    def source(self) -> str:
        return "\n".join(self.lines) + "\n"

    @property
    def digest(self) -> str:
        return stable_digest({"source": self.source, "schema_version": self.schema_version})

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "lines": list(self.lines),
            "logic": self.logic,
            "query_mode": self.query_mode.value,
            "request_model": self.request_model,
            "request_unsat_core": self.request_unsat_core,
            "schema_version": self.schema_version,
            "source": self.source,
            "theories": [item.value for item in self.theories],
        }


@dataclass(frozen=True, slots=True)
class SmtCompilation:
    """Compiler output: SMT-LIB script + translation receipt + capabilities."""

    obligation_id: str
    script: SmtScript
    receipt: LogicTranslationReceipt
    capabilities: tuple[SmtCapability, ...]
    features: tuple[SmtFeature, ...]
    query_mode: SmtQueryMode
    source_identity: str
    target_identity: str
    compiler_version: str = SMT_COMPILER_VERSION
    schema_version: str = SMT_COMPILATION_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        if not isinstance(self.script, SmtScript):
            raise SmtCompilerError("script must be an SmtScript")
        if not isinstance(self.receipt, LogicTranslationReceipt):
            raise SmtCompilerError("receipt must be a LogicTranslationReceipt")
        capabilities = tuple(
            item
            if isinstance(item, SmtCapability)
            else SmtCapability.from_dict(_mapping(item, "capability"))
            for item in self.capabilities
        )
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted(capabilities, key=lambda item: item.feature.value)),
        )
        features = tuple(_enum(item, SmtFeature, "features item") for item in self.features)
        object.__setattr__(
            self, "features", tuple(sorted(features, key=lambda item: item.value))
        )
        object.__setattr__(
            self, "query_mode", _enum(self.query_mode, SmtQueryMode, "query_mode")
        )
        object.__setattr__(
            self, "source_identity", _text(self.source_identity, "source_identity")
        )
        object.__setattr__(
            self, "target_identity", _text(self.target_identity, "target_identity")
        )
        object.__setattr__(
            self, "compiler_version", _text(self.compiler_version, "compiler_version")
        )
        if self.schema_version != SMT_COMPILATION_SCHEMA_VERSION:
            raise SmtCompilerError(
                f"unsupported compilation schema_version {self.schema_version!r}"
            )

    @property
    def smtlib(self) -> str:
        return self.script.source

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain="logic.backends.smt.compilation",
            schema_version=self.schema_version,
        )

    @property
    def compilation_id(self) -> str:
        return self.identity.cid

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "capabilities": [item.to_dict() for item in self.capabilities],
            "compiler_version": self.compiler_version,
            "features": [item.value for item in self.features],
            "obligation_id": self.obligation_id,
            "query_mode": self.query_mode.value,
            "receipt_id": self.receipt.receipt_id,
            "schema_version": self.schema_version,
            "script_digest": self.script.digest,
            "source_identity": self.source_identity,
            "target_identity": self.target_identity,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.semantic_dict()
        payload.update(
            {
                "compilation_id": self.compilation_id,
                "interface": self.INTERFACE,
                "receipt": self.receipt.to_dict(),
                "script": self.script.to_dict(),
                "smtlib": self.smtlib,
            }
        )
        return payload

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.semantic_dict())


def _declare_sort_lines(sorts: Sequence[SmtSort]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for sort in sorts:
        if sort.name in {"Bool", "Int", "Real", "Array"}:
            continue
        if sort.parameters:
            # Parameterized sorts are produced by Array etc.; skip free decls.
            continue
        if sort.name in seen:
            continue
        seen.add(sort.name)
        lines.append(f"(declare-sort {sort.name} {sort.arity})")
    return lines


def _build_script(obligation: SmtObligation) -> SmtScript:
    logic = obligation.logic or select_smt_logic(obligation.theories, obligation.query_mode)
    lines: list[str] = [
        f"; software-verification semantic SMT compiler {SMT_COMPILER_VERSION}",
        f"; obligation_id: {obligation.obligation_id}",
        f"; query_mode: {obligation.query_mode.value}",
        f"; features: {','.join(item.value for item in obligation.features)}",
        f"(set-info :smt-lib-version {SMTLIB_VERSION})",
        f'(set-info :source "{SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE}")',
        f"(set-info :obligation {obligation.obligation_id})",
        f"(set-logic {logic})",
    ]
    if obligation.request_model:
        lines.append("(set-option :produce-models true)")
    if obligation.request_unsat_core:
        lines.append("(set-option :produce-unsat-cores true)")

    lines.extend(_declare_sort_lines(obligation.sorts))
    for datatype in obligation.datatypes:
        lines.append(datatype.render())
    for function in obligation.functions:
        lines.append(function.render())

    if obligation.query_mode is SmtQueryMode.FIXED_POINT:
        for clause in obligation.horn_clauses:
            implication = clause.as_implication().render()
            if clause.is_query:
                # Fixed-point query: ask whether the query head is reachable.
                lines.append(
                    f"(assert (! {implication} :named {smt_sanitize(clause.clause_id, prefix='q')}))"
                )
            else:
                lines.append(
                    f"(assert (! {implication} :named {smt_sanitize(clause.clause_id, prefix='c')}))"
                )
    else:
        for assumption in obligation.assumptions:
            lines.append(assumption.render())
        assert obligation.goal is not None
        goal_text = obligation.goal.render()
        if obligation.query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
            lines.append(f"(assert (not {goal_text}))")
        elif obligation.query_mode is SmtQueryMode.SATISFIABILITY:
            lines.append(f"(assert {goal_text})")
        else:  # pragma: no cover - closed enum
            raise SmtCompilerError(f"unhandled query mode {obligation.query_mode!r}")

    lines.append("(check-sat)")
    if obligation.request_model:
        lines.append("(get-model)")
    if obligation.request_unsat_core:
        lines.append("(get-unsat-core)")

    return SmtScript(
        logic=logic,
        query_mode=obligation.query_mode,
        lines=tuple(lines),
        theories=obligation.theories,
        request_model=obligation.request_model,
        request_unsat_core=obligation.request_unsat_core,
    )


def _source_identity_for(obligation: SmtObligation) -> str:
    payload = obligation.to_dict()
    return canonical_identity(
        payload,
        domain="logic.backends.smt.obligation",
        schema_version=obligation.schema_version,
    ).cid


def _target_identity_for(script: SmtScript) -> str:
    return canonical_identity(
        script.to_dict(),
        domain="logic.backends.smt.script",
        schema_version=script.schema_version,
    ).cid


def _preservation_for(obligation: SmtObligation) -> PreservationClaim:
    property_ids = obligation.property_ids or ("property:smt-obligation",)
    permitted_all = (
        "unknown",
        "unsatisfiable",
        "satisfiable",
        "proved",
        "disproved",
    )
    if obligation.bounds:
        return PreservationClaim(
            kind=PreservationKind.BOUNDED,
            preserved_property_ids=property_ids,
            permitted_result_classes=permitted_all,
            description=(
                "Compilation is step- or resource-bounded over the supported SMT fragment."
            ),
            conditions=tuple(bound.bound_id for bound in obligation.bounds),
        )
    if obligation.unsupported_constructs:
        return PreservationClaim(
            kind=PreservationKind.CONSERVATIVE,
            approximation_direction=ApproximationDirection.OVER,
            preserved_property_ids=property_ids,
            permitted_result_classes=permitted_all,
            description=(
                "Compilation conservatively approximates constructs that are not fully native."
            ),
        )
    # Theorem-by-negation and fixed-point encodings introduce explicit semantic
    # mutations, so they cannot claim exact preservation.
    if obligation.query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
        return PreservationClaim(
            kind=PreservationKind.EQUISATISFIABLE,
            preserved_property_ids=property_ids,
            permitted_result_classes=("proved", "disproved", "unknown"),
            description=(
                "Goal is checked by negation: unsat of the negated goal is equisatisfiable "
                "with theorem validity under the assumptions."
            ),
        )
    if obligation.query_mode is SmtQueryMode.FIXED_POINT:
        return PreservationClaim(
            kind=PreservationKind.EQUISATISFIABLE,
            preserved_property_ids=property_ids,
            permitted_result_classes=("satisfiable", "unsatisfiable", "unknown"),
            description=(
                "Horn/CHC clauses are compiled as an explicit fixed-point query."
            ),
        )
    if any(feature in _CAPABILITY_BOUND for feature in obligation.features):
        return PreservationClaim(
            kind=PreservationKind.EQUISATISFIABLE,
            preserved_property_ids=property_ids,
            permitted_result_classes=permitted_all,
            description=(
                "Capability-bound engine claims accompany an equisatisfiable SMT encoding."
            ),
        )
    # Pure SAT queries with no bounds/mutations are exact structural lowerings.
    return PreservationClaim(
        kind=PreservationKind.EXACT,
        preserved_property_ids=property_ids,
        permitted_result_classes=("satisfiable", "unsatisfiable", "unknown"),
        description="Supported fragment is structurally preserved into SMT-LIB 2.6.",
    )


def _authority_for(claim: PreservationClaim) -> EvidenceAuthority:
    return claim.maximum_authority


def _build_receipt(
    obligation: SmtObligation,
    script: SmtScript,
    *,
    source_identity: str,
    target_identity: str,
) -> LogicTranslationReceipt:
    claim = _preservation_for(obligation)
    mutations = list(obligation.semantic_mutations)
    # Exact preservation forbids mutations; only attach encoding mutations for
    # non-exact claims (theorem-by-negation, fixed-point, capability-bound).
    if claim.kind is not PreservationKind.EXACT:
        if obligation.query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
            mutations.append(
                SemanticMutation(
                    mutation_id="mutation:theorem-by-negation",
                    kind=SemanticMutationKind.POLARITY_CHANGED,
                    description=(
                        "Goal is asserted under negation so that unsat witnesses the theorem."
                    ),
                    source_construct_ids=(obligation.obligation_id,),
                    target_construct_ids=("assert-not-goal",),
                )
            )
        if obligation.query_mode is SmtQueryMode.FIXED_POINT:
            mutations.append(
                SemanticMutation(
                    mutation_id="mutation:fixed-point-query",
                    kind=SemanticMutationKind.ENCODING,
                    description="Horn clauses are compiled as an explicit fixed-point query.",
                    source_construct_ids=(obligation.obligation_id,),
                    target_construct_ids=("horn-fixed-point",),
                )
            )
        for feature in obligation.features:
            if feature in _CAPABILITY_BOUND:
                mutations.append(
                    SemanticMutation(
                        mutation_id=f"mutation:capability-{feature.value}",
                        kind=SemanticMutationKind.OTHER,
                        description=(
                            f"{feature.value} remains capability-bound and is not a native "
                            "SMT-LIB claim."
                        ),
                        source_construct_ids=(obligation.obligation_id,),
                        target_construct_ids=(f"capability:{feature.value}",),
                    )
                )

    return LogicTranslationReceipt(
        source_identity=source_identity,
        target_identity=target_identity,
        source_family_id=obligation.source_family_id,
        source_family_version=obligation.source_family_version,
        target_family_id=SMT_TARGET_FAMILY_ID,
        target_family_version=SMT_TARGET_FAMILY_VERSION,
        compilers=(
            CompilerBinding(
                compiler_id=SMT_COMPILER_ID,
                compiler_version=SMT_COMPILER_VERSION,
                implementation_identity=_implementation_identity(),
                configuration_identity=f"sha256:{script.digest}",
                stage="lower",
            ),
        ),
        preservation_claim=claim,
        authority_ceiling=_authority_for(claim),
        assumptions=tuple(
            f"named:{item.name}" if item.name else f"anon:{index}"
            for index, item in enumerate(obligation.assumptions)
        ),
        bounds=obligation.bounds,
        unsupported_constructs=obligation.unsupported_constructs,
        semantic_mutations=tuple(mutations),
        metadata={
            "logic": script.logic,
            "obligation_id": obligation.obligation_id,
            "query_mode": obligation.query_mode.value,
            "request_model": obligation.request_model,
            "request_unsat_core": obligation.request_unsat_core,
            "theories": [item.value for item in obligation.theories],
        },
    )


class SoftwareVerificationSMTCompiler:
    """Lower software-verification obligations into deterministic SMT-LIB."""

    INTERFACE: ClassVar[str] = SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE
    compiler_id: ClassVar[str] = SMT_COMPILER_ID
    compiler_version: ClassVar[str] = SMT_COMPILER_VERSION

    def __init__(self, *, capabilities: Sequence[SmtCapability] | None = None) -> None:
        caps = (
            tuple(capabilities)
            if capabilities is not None
            else default_capabilities()
        )
        self._capabilities = tuple(
            sorted(
                (
                    item
                    if isinstance(item, SmtCapability)
                    else SmtCapability.from_dict(_mapping(item, "capability"))
                    for item in caps
                ),
                key=lambda item: item.feature.value,
            )
        )
        self._capability_index = {item.feature: item for item in self._capabilities}

    @property
    def capabilities(self) -> tuple[SmtCapability, ...]:
        return self._capabilities

    def capability(self, feature: SmtFeature | str) -> SmtCapability:
        feature = _enum(feature, SmtFeature, "feature")
        try:
            return self._capability_index[feature]
        except KeyError as error:
            raise SmtCompilerError(f"no capability declared for {feature.value}") from error

    def supports(self, feature: SmtFeature | str) -> bool:
        feature = _enum(feature, SmtFeature, "feature")
        capability = self._capability_index.get(feature)
        return capability is not None and capability.kind is SmtCapabilityKind.NATIVE

    def is_capability_bound(self, feature: SmtFeature | str) -> bool:
        feature = _enum(feature, SmtFeature, "feature")
        capability = self._capability_index.get(feature)
        return (
            capability is not None
            and capability.kind is SmtCapabilityKind.CAPABILITY_BOUND
        )

    def reject_unsupported(self, feature: SmtFeature | str, *, detail: str = "") -> None:
        """Fail closed for features that must not become uninterpreted claims."""

        feature = _enum(feature, SmtFeature, "feature")
        capability = self._capability_index.get(feature)
        if capability is None or capability.kind is SmtCapabilityKind.UNSUPPORTED:
            message = (
                f"feature {feature.value} cannot become an uninterpreted native SMT claim"
            )
            if detail:
                message = f"{message}: {detail}"
            raise UnsupportedSmtFeatureError(message)
        if capability.kind is SmtCapabilityKind.CAPABILITY_BOUND:
            message = (
                f"feature {feature.value} is capability-bound and is not a native "
                "SMT-LIB encoding"
            )
            if detail:
                message = f"{message}: {detail}"
            raise UnsupportedSmtFeatureError(message)

    def compile(self, obligation: SmtObligation | Mapping[str, Any]) -> SmtCompilation:
        """Compile one obligation into SMT-LIB plus a translation receipt."""

        if not isinstance(obligation, SmtObligation):
            obligation = SmtObligation.from_dict(_mapping(obligation, "obligation"))
        for feature in obligation.features:
            capability = self._capability_index.get(feature)
            if capability is None:
                raise UnsupportedSmtFeatureError(
                    f"feature {feature.value} is not declared by {self.INTERFACE}"
                )
            if capability.kind is SmtCapabilityKind.UNSUPPORTED:
                raise UnsupportedSmtFeatureError(
                    f"feature {feature.value} cannot become an uninterpreted native claim"
                )
            if capability.kind is SmtCapabilityKind.CAPABILITY_BOUND:
                # Allowed only as an annotation on fixed-point queries.
                if obligation.query_mode is not SmtQueryMode.FIXED_POINT:
                    raise UnsupportedSmtFeatureError(
                        f"capability-bound feature {feature.value} requires fixed_point mode"
                    )
                if feature not in {SmtFeature.PDR, SmtFeature.IC3}:
                    raise UnsupportedSmtFeatureError(
                        f"capability-bound feature {feature.value} is not admitted"
                    )
            elif capability.kind is not SmtCapabilityKind.NATIVE:
                if capability.kind is SmtCapabilityKind.TRANSLATED:
                    continue
                raise UnsupportedSmtFeatureError(
                    f"feature {feature.value} has unsupported capability kind "
                    f"{capability.kind.value}"
                )

        script = _build_script(obligation)
        source_identity = _source_identity_for(obligation)
        target_identity = _target_identity_for(script)
        if source_identity == target_identity:
            # Extremely unlikely; force distinction via salt in target payload.
            target_identity = canonical_identity(
                {**script.to_dict(), "role": "target"},
                domain="logic.backends.smt.script",
                schema_version=script.schema_version,
            ).cid
        receipt = _build_receipt(
            obligation,
            script,
            source_identity=source_identity,
            target_identity=target_identity,
        )
        used_capabilities = tuple(
            self.capability(feature) for feature in obligation.features
        )
        return SmtCompilation(
            obligation_id=obligation.obligation_id,
            script=script,
            receipt=receipt,
            capabilities=used_capabilities,
            features=obligation.features,
            query_mode=obligation.query_mode,
            source_identity=source_identity,
            target_identity=target_identity,
        )

    __call__ = compile

    # ------------------------------------------------------------------
    # Convenience constructors for acceptance-covered fragments
    # ------------------------------------------------------------------

    def compile_arithmetic_goal(
        self,
        *,
        obligation_id: str,
        goal: SmtTerm,
        assumptions: Sequence[SmtNamedAssertion] = (),
        symbols: Sequence[str] = (),
        query_mode: SmtQueryMode = SmtQueryMode.THEOREM_BY_NEGATION,
        request_unsat_core: bool = True,
        property_ids: Sequence[str] = (),
    ) -> SmtCompilation:
        functions = tuple(
            SmtFunDecl(name=smt_sanitize(name, prefix="v"), range=INT_SORT, is_const=True)
            for name in symbols
        )
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=query_mode,
                features=(SmtFeature.ARITHMETIC, SmtFeature.EQUALITY),
                goal=goal,
                assumptions=tuple(assumptions),
                functions=functions,
                request_unsat_core=request_unsat_core,
                property_ids=tuple(property_ids),
            )
        )

    def compile_array_goal(
        self,
        *,
        obligation_id: str,
        array_name: str,
        goal: SmtTerm,
        assumptions: Sequence[SmtNamedAssertion] = (),
        query_mode: SmtQueryMode = SmtQueryMode.THEOREM_BY_NEGATION,
        request_model: bool = False,
    ) -> SmtCompilation:
        array = smt_sanitize(array_name, prefix="arr")
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=query_mode,
                features=(SmtFeature.ARRAYS, SmtFeature.EQUALITY, SmtFeature.ARITHMETIC),
                goal=goal,
                assumptions=tuple(assumptions),
                functions=(
                    SmtFunDecl(
                        name=array,
                        range=array_sort(INT_SORT, INT_SORT),
                        is_const=True,
                    ),
                ),
                request_model=request_model,
            )
        )

    def compile_datatype_goal(
        self,
        *,
        obligation_id: str,
        datatype: SmtDatatypeDecl,
        goal: SmtTerm,
        functions: Sequence[SmtFunDecl] = (),
        query_mode: SmtQueryMode = SmtQueryMode.SATISFIABILITY,
        request_model: bool = True,
    ) -> SmtCompilation:
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=query_mode,
                features=(SmtFeature.DATATYPES, SmtFeature.EQUALITY),
                goal=goal,
                datatypes=(datatype,),
                functions=tuple(functions),
                request_model=request_model,
            )
        )

    def compile_quantified_goal(
        self,
        *,
        obligation_id: str,
        goal: SmtTerm,
        functions: Sequence[SmtFunDecl] = (),
        query_mode: SmtQueryMode = SmtQueryMode.THEOREM_BY_NEGATION,
    ) -> SmtCompilation:
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=query_mode,
                features=(SmtFeature.QUANTIFIERS, SmtFeature.EQUALITY, SmtFeature.ARITHMETIC),
                goal=goal,
                functions=tuple(functions),
            )
        )

    def compile_horn_reachability(
        self,
        *,
        obligation_id: str,
        relations: Sequence[SmtFunDecl],
        clauses: Sequence[HornClause],
        claim_pdr: bool = False,
        claim_ic3: bool = False,
        bounds: Sequence[TranslationBound] = (),
    ) -> SmtCompilation:
        features: list[SmtFeature] = [
            SmtFeature.HORN_CHC,
            SmtFeature.STATE_TRANSITIONS,
            SmtFeature.QUANTIFIERS,
        ]
        if claim_pdr:
            features.append(SmtFeature.PDR)
        if claim_ic3:
            features.append(SmtFeature.IC3)
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=SmtQueryMode.FIXED_POINT,
                features=tuple(features),
                horn_clauses=tuple(clauses),
                functions=tuple(relations),
                bounds=tuple(bounds),
                property_ids=("property:reachability",),
            )
        )

    def compile_verification_condition(
        self,
        *,
        obligation_id: str,
        goal: SmtTerm,
        path_assumptions: Sequence[SmtTerm] = (),
        symbols: Sequence[tuple[str, SmtSort]] = (),
        request_unsat_core: bool = True,
        property_ids: Sequence[str] = ("property:vc",),
    ) -> SmtCompilation:
        assumptions = tuple(
            SmtNamedAssertion(formula=formula, name=f"path_{index}")
            for index, formula in enumerate(path_assumptions)
        )
        functions = tuple(
            SmtFunDecl(name=smt_sanitize(name, prefix="v"), range=sort, is_const=True)
            for name, sort in symbols
        )
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
                features=(
                    SmtFeature.VERIFICATION_CONDITIONS,
                    SmtFeature.ARITHMETIC,
                    SmtFeature.EQUALITY,
                ),
                goal=goal,
                assumptions=assumptions,
                functions=functions,
                request_unsat_core=request_unsat_core,
                property_ids=tuple(property_ids),
            )
        )

    def compile_state_transition(
        self,
        *,
        obligation_id: str,
        state_vars: Sequence[str],
        init: SmtTerm,
        transition: SmtTerm,
        bad: SmtTerm,
        bound_steps: int | None = None,
    ) -> SmtCompilation:
        """Encode bounded or relational reachability of a bad state.

        When ``bound_steps`` is set, emit an explicit finite unrolling as a
        satisfiability query.  Without a bound, emit a single-step relational
        obligation as theorem-by-negation of ``init /\\ transition => not bad``.
        """

        vars_sanitized = [smt_sanitize(name, prefix="s") for name in state_vars]
        functions = tuple(
            SmtFunDecl(name=name, range=INT_SORT, is_const=True) for name in vars_sanitized
        )
        if bound_steps is not None:
            if not isinstance(bound_steps, int) or isinstance(bound_steps, bool) or bound_steps < 1:
                raise SmtCompilerError("bound_steps must be a positive integer")
            # Bounded unrolling: init(s0) /\ step /\ ... /\ bad(sN)
            # The caller supplies already-indexed formulas; we wrap them.
            goal = term_and(init, transition, bad)
            bound = TranslationBound(
                bound_id=f"bound:steps-{bound_steps}",
                kind=BoundednessKind.STEP_BOUNDED,
                limits={"steps": bound_steps},
                description=f"Reachability is checked through {bound_steps} transition steps.",
            )
            return self.compile(
                SmtObligation(
                    obligation_id=obligation_id,
                    query_mode=SmtQueryMode.SATISFIABILITY,
                    features=(
                        SmtFeature.STATE_TRANSITIONS,
                        SmtFeature.ARITHMETIC,
                        SmtFeature.EQUALITY,
                    ),
                    goal=goal,
                    functions=functions,
                    request_model=True,
                    bounds=(bound,),
                    property_ids=("property:state-reachability",),
                )
            )
        safety = term_implies(term_and(init, transition), term_not(bad))
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
                features=(
                    SmtFeature.STATE_TRANSITIONS,
                    SmtFeature.ARITHMETIC,
                    SmtFeature.EQUALITY,
                ),
                goal=safety,
                functions=functions,
                property_ids=("property:state-safety",),
            )
        )

    def compile_heap_fragment(
        self,
        *,
        obligation_id: str,
        heap_name: str = "heap",
        points_to: Sequence[tuple[SmtTerm, SmtTerm]] = (),
        pure_goal: SmtTerm,
        request_unsat_core: bool = True,
    ) -> SmtCompilation:
        """Lower a supported heap fragment: map locations to values via Array.

        Magic wand / septraction are hard-unsupported and must be rejected via
        :meth:`reject_unsupported` rather than encoded as uninterpreted symbols.
        """

        heap = smt_sanitize(heap_name, prefix="heap")
        assumptions = []
        for index, (location, value) in enumerate(points_to):
            assumptions.append(
                SmtNamedAssertion(
                    formula=term_eq(
                        SmtTerm(
                            SmtTermKind.SELECT,
                            arguments=(term_symbol(heap), location),
                        ),
                        value,
                    ),
                    name=f"points_to_{index}",
                )
            )
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
                features=(
                    SmtFeature.HEAP_RESOURCE,
                    SmtFeature.ARRAYS,
                    SmtFeature.EQUALITY,
                    SmtFeature.ARITHMETIC,
                ),
                goal=pure_goal,
                assumptions=tuple(assumptions),
                functions=(
                    SmtFunDecl(
                        name=heap,
                        range=array_sort(INT_SORT, INT_SORT),
                        is_const=True,
                    ),
                ),
                request_unsat_core=request_unsat_core,
                property_ids=("property:heap-fragment",),
                semantic_mutations=(
                    SemanticMutation(
                        mutation_id="mutation:heap-as-array",
                        kind=SemanticMutationKind.ENCODING,
                        description=(
                            "Supported points-to cells are encoded as Array select equalities."
                        ),
                        source_construct_ids=(obligation_id,),
                        target_construct_ids=(heap,),
                    ),
                ),
            )
        )

    def compile_interference(
        self,
        *,
        obligation_id: str,
        rely: SmtTerm,
        guarantee: SmtTerm,
        shared_vars: Sequence[str] = (),
        bound_interleavings: int | None = None,
    ) -> SmtCompilation:
        """Lower a rely/guarantee interference obligation.

        Unbounded concurrent interleaving without an explicit bound is rejected.
        """

        if bound_interleavings is None:
            self.reject_unsupported(
                SmtFeature.UNBOUNDED_CONCURRENCY,
                detail="interference obligations require an explicit interleaving bound",
            )
        if (
            not isinstance(bound_interleavings, int)
            or isinstance(bound_interleavings, bool)
            or bound_interleavings < 1
        ):
            raise SmtCompilerError("bound_interleavings must be a positive integer")
        functions = tuple(
            SmtFunDecl(name=smt_sanitize(name, prefix="sh"), range=INT_SORT, is_const=True)
            for name in shared_vars
        )
        # Interference stability: rely /\\ guarantee is consistent under the bound.
        goal = term_implies(rely, guarantee)
        bound = TranslationBound(
            bound_id=f"bound:interleavings-{bound_interleavings}",
            kind=BoundednessKind.STEP_BOUNDED,
            limits={"interleavings": bound_interleavings},
            description=(
                f"Interference is checked under at most {bound_interleavings} interleavings."
            ),
        )
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
                features=(
                    SmtFeature.INTERFERENCE,
                    SmtFeature.ARITHMETIC,
                    SmtFeature.EQUALITY,
                ),
                goal=goal,
                functions=functions,
                bounds=(bound,),
                property_ids=("property:interference",),
            )
        )

    def compile_refinement(
        self,
        *,
        obligation_id: str,
        simulation: SmtTerm,
        abstract_step: SmtTerm,
        concrete_step: SmtTerm,
        max_matching_steps: int | None = None,
        claims_unbounded: bool = False,
    ) -> SmtCompilation:
        """Lower a refinement/simulation obligation.

        Unbounded refinement claims without a matching bound are hard-unsupported.
        """

        if claims_unbounded and max_matching_steps is None:
            self.reject_unsupported(
                SmtFeature.UNBOUNDED_REFINEMENT,
                detail="unbounded refinement requires an explicit matching bound or must be rejected",
            )
        bounds: list[TranslationBound] = []
        if max_matching_steps is not None:
            if (
                not isinstance(max_matching_steps, int)
                or isinstance(max_matching_steps, bool)
                or max_matching_steps < 1
            ):
                raise SmtCompilerError("max_matching_steps must be a positive integer")
            bounds.append(
                TranslationBound(
                    bound_id=f"bound:matching-{max_matching_steps}",
                    kind=BoundednessKind.STEP_BOUNDED,
                    limits={"matching_steps": max_matching_steps},
                    description=(
                        f"Simulation matching is limited to {max_matching_steps} steps."
                    ),
                )
            )
        # Forward simulation fragment: R /\\ abstract_step => exists concrete matching.
        # Here the existential is supplied by the caller inside concrete_step.
        goal = term_implies(term_and(simulation, abstract_step), concrete_step)
        return self.compile(
            SmtObligation(
                obligation_id=obligation_id,
                query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
                features=(
                    SmtFeature.REFINEMENT,
                    SmtFeature.EQUALITY,
                    SmtFeature.ARITHMETIC,
                ),
                goal=goal,
                bounds=tuple(bounds),
                property_ids=("property:refinement",),
            )
        )

    def compile_temporal_rejected(
        self,
        *,
        obligation_id: str,
        detail: str = "temporal operators are not native SMT claims",
    ) -> None:
        """Explicit rejection path for temporal features."""

        del obligation_id  # identity is caller-owned; rejection is feature-based
        self.reject_unsupported(SmtFeature.TEMPORAL, detail=detail)


def compile_obligation(
    obligation: SmtObligation | Mapping[str, Any],
) -> SmtCompilation:
    """Compile using the default shared semantic SMT compiler."""

    return SoftwareVerificationSMTCompiler().compile(obligation)


__all__ = [
    "BOOL_SORT",
    "INT_SORT",
    "REAL_SORT",
    "SMT_COMPILER_ID",
    "SMT_COMPILER_VERSION",
    "SMT_COMPILATION_SCHEMA_VERSION",
    "SMT_OBLIGATION_SCHEMA_VERSION",
    "SMT_SCRIPT_SCHEMA_VERSION",
    "SMT_SOURCE_FAMILY_ID",
    "SMT_SOURCE_FAMILY_VERSION",
    "SMT_TARGET_FAMILY_ID",
    "SMT_TARGET_FAMILY_VERSION",
    "SMTLIB_VERSION",
    "SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE",
    "HornClause",
    "SmtBinder",
    "SmtCapability",
    "SmtCapabilityKind",
    "SmtCompilation",
    "SmtCompilerError",
    "SmtDatatypeConstructor",
    "SmtDatatypeDecl",
    "SmtFeature",
    "SmtFunDecl",
    "SmtNamedAssertion",
    "SmtObligation",
    "SmtQueryMode",
    "SmtScript",
    "SmtSort",
    "SmtTerm",
    "SmtTermKind",
    "SmtTheory",
    "SoftwareVerificationSMTCompiler",
    "UnsupportedSmtFeatureError",
    "array_sort",
    "compile_obligation",
    "default_capabilities",
    "select_smt_logic",
    "smt_sanitize",
    "term_and",
    "term_apply",
    "term_eq",
    "term_false",
    "term_implies",
    "term_int",
    "term_not",
    "term_or",
    "term_symbol",
    "term_true",
]
