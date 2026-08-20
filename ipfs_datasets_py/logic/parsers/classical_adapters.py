"""Join classical/rule parsers with Z3, cvc5, Vampire, E, SecPAL, and ErgoAI routes.

Interface: ``ClassicalBackendAdapter@1`` (LFP-022).

Typed source from the classical/rule frontends reaches shared backend requests
and typed result decoders with preservation and authority receipts.

Authority rules (fail-closed):

* Exact routes run hermetically when the backend is available, otherwise they
  report ``unavailable`` without inventing a conclusive verdict.
* Approximate or unsupported routes cannot promote authority above their
  declared ceiling (typically ``candidate``).
* Backends never reparse natural language or free-form family labels; only
  typed expressions, controlled source documents, or explicit target encodings
  are admitted.
* ErgoAI remains advisor/candidate only; ATP unreconstructed evidence remains
  candidate until independent reconstruction.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.backends.atp.adapters import (
    ATPAdapterOutcome,
    EProverBackend,
    VampireBackend,
)
from ipfs_datasets_py.logic.backends.cvc5.compiler import CVC5Backend
from ipfs_datasets_py.logic.backends.datalog.adapters import (
    AuthorizationBackendOutcome,
    SecPALAuthorizationBackend,
)
from ipfs_datasets_py.logic.backends.results import (
    AuthorizationResult,
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
    TypedBackendResult,
)
from ipfs_datasets_py.logic.backends.z3.compiler import Z3Backend
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.parsers.flogic import (
    ERGOAI_CONTROLLED_SOURCE_INTERFACE,
    FLOGIC_FAMILY_ID,
    FLOGIC_PROVIDER_ID,
    ErgoAIControlledSource,
    FLogicDocument,
    FLogicFrontend,
    print_flogic,
)
from ipfs_datasets_py.logic.parsers.rules import (
    RULE_FAMILY_ID,
    SECPAL_FAMILY_ID,
    SECPAL_PROFILE_ID,
    RuleDocument,
    RuleEffect,
    RuleProfile,
    RuleStatementKind,
    RuleTermKind,
    print_rules,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    SMTLIB2_FAMILY_ID,
    SMTLIB2_NOTATION_ID,
    SmtlibDocument,
    print_smtlib2,
)
from ipfs_datasets_py.logic.parsers.tptp import (
    TPTP_FAMILY_ID,
    TPTP_NOTATION_ID,
    TPTPDocument,
    print_tptp,
)
from ipfs_datasets_py.logic.software_verification.authorization import (
    AtomPolarity,
    AuthorizationAtom,
    AuthorizationFact,
    AuthorizationIR,
    AuthorizationPrincipal,
    AuthorizationRule,
    AuthorizationTerm,
    DecisionQuery,
    EffectKind,
    PrincipalKind,
    RuleKind,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

CLASSICAL_BACKEND_ADAPTER_INTERFACE: Final = "ClassicalBackendAdapter@1"
CLASSICAL_BACKEND_ADAPTER_VERSION: Final = "1.0.0"
CLASSICAL_ROUTE_RECEIPT_SCHEMA: Final = "classical-backend-route-receipt/v1"
CLASSICAL_ROUTE_RESULT_SCHEMA: Final = "classical-backend-route-result/v1"
CLASSICAL_SOURCE_BINDING_SCHEMA: Final = "classical-backend-source-binding/v1"
CLASSICAL_ADAPTER_MODULE_VERSION: Final = "1.0.0"

# Stable diagnostic codes.
CODE_UNSUPPORTED_ROUTE: Final = "classical.unsupported_route"
CODE_UNAVAILABLE: Final = "classical.backend_unavailable"
CODE_FREE_FORM_FAMILY: Final = "classical.free_form_family_rejected"
CODE_NATURAL_LANGUAGE: Final = "classical.natural_language_rejected"
CODE_TYPED_SOURCE_REQUIRED: Final = "classical.typed_source_required"
CODE_AUTHORITY_PROMOTION: Final = "classical.authority_promotion_rejected"
CODE_APPROXIMATE_ROUTE: Final = "classical.approximate_route_ceiling"
CODE_MALFORMED: Final = "classical.malformed_input"
CODE_PARSE_REQUIRED: Final = "classical.parser_output_required"
CODE_UNSUPPORTED_CONSTRUCT: Final = "classical.unsupported_construct"
CODE_ROUTE: Final = "classical.route_error"

_ALL_CLASSICAL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNSUPPORTED_ROUTE,
        CODE_UNAVAILABLE,
        CODE_FREE_FORM_FAMILY,
        CODE_NATURAL_LANGUAGE,
        CODE_TYPED_SOURCE_REQUIRED,
        CODE_AUTHORITY_PROMOTION,
        CODE_APPROXIMATE_ROUTE,
        CODE_MALFORMED,
        CODE_PARSE_REQUIRED,
        CODE_UNSUPPORTED_CONSTRUCT,
        CODE_ROUTE,
    }
)

# Canonical family IDs only — free-form / legacy aliases are rejected at join.
_CANONICAL_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "first_order",
        "smt",
        SMTLIB2_FAMILY_ID if SMTLIB2_FAMILY_ID else "first_order",
        TPTP_FAMILY_ID,
        RULE_FAMILY_ID,
        SECPAL_FAMILY_ID,
        "authorization",
        "datalog",
        FLOGIC_FAMILY_ID,
        "frame_logic",
        "software_verification",
    }
)

# Free-form / natural-language markers rejected as backend payload.
_NL_MARKERS: Final[tuple[str, ...]] = (
    "natural language",
    "natural_language",
    "free text",
    "freetext",
    "please prove",
    "in plain english",
    "nl_input",
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_IDENT = re.compile(r"[^A-Za-z0-9_]+")


class ClassicalAdapterError(ValueError):
    """Raised when a classical backend join request is invalid."""

    def __init__(self, message: str, *, code: str = CODE_ROUTE, path: str = "") -> None:
        super().__init__(message)
        self.code = code if code in _ALL_CLASSICAL_CODES else CODE_ROUTE
        self.path = path


class AuthorityPromotionError(ClassicalAdapterError):
    """Raised when a route attempts to exceed its authority ceiling."""

    def __init__(self, message: str, *, path: str = "authority") -> None:
        super().__init__(message, code=CODE_AUTHORITY_PROMOTION, path=path)


class FreeFormFamilyError(ClassicalAdapterError):
    """Raised when free-form family labels are offered as backend inputs."""

    def __init__(self, message: str, *, path: str = "logic_family") -> None:
        super().__init__(message, code=CODE_FREE_FORM_FAMILY, path=path)


class NaturalLanguageRejectedError(ClassicalAdapterError):
    """Raised when natural language is offered for backend reparse."""

    def __init__(self, message: str, *, path: str = "source") -> None:
        super().__init__(message, code=CODE_NATURAL_LANGUAGE, path=path)


class ClassicalRouteKind(StrEnum):
    """Closed set of classical/rule backend join routes."""

    Z3 = "z3"
    CVC5 = "cvc5"
    VAMPIRE = "vampire"
    E = "e"
    EPROVER = "eprover"
    SECPAL = "secpal"
    DATALOG_SECPAL = "datalog_secpal"
    ERGOAI = "ergoai"


class RouteExactness(StrEnum):
    """Whether a route is exact (hermetic) or approximate/unsupported."""

    EXACT = "exact"
    APPROXIMATE = "approximate"
    UNSUPPORTED = "unsupported"


class RouteAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


# Provider IDs that may be selected; aliases normalize to a route kind.
_PROVIDER_TO_ROUTE: Final[dict[str, ClassicalRouteKind]] = {
    "z3": ClassicalRouteKind.Z3,
    "cvc5": ClassicalRouteKind.CVC5,
    "vampire": ClassicalRouteKind.VAMPIRE,
    "e": ClassicalRouteKind.E,
    "eprover": ClassicalRouteKind.EPROVER,
    "secpal": ClassicalRouteKind.SECPAL,
    "datalog_secpal": ClassicalRouteKind.DATALOG_SECPAL,
    "datalog-secpal": ClassicalRouteKind.DATALOG_SECPAL,
    "ergoai": ClassicalRouteKind.ERGOAI,
    "ergo_ai": ClassicalRouteKind.ERGOAI,
}

_ROUTE_AUTHORITY_CEILING: Final[dict[ClassicalRouteKind, ResultAuthority]] = {
    ClassicalRouteKind.Z3: ResultAuthority.SATISFIABILITY,
    ClassicalRouteKind.CVC5: ResultAuthority.SATISFIABILITY,
    ClassicalRouteKind.VAMPIRE: ResultAuthority.CANDIDATE,
    ClassicalRouteKind.E: ResultAuthority.CANDIDATE,
    ClassicalRouteKind.EPROVER: ResultAuthority.CANDIDATE,
    ClassicalRouteKind.SECPAL: ResultAuthority.AUTHORIZATION,
    ClassicalRouteKind.DATALOG_SECPAL: ResultAuthority.AUTHORIZATION,
    ClassicalRouteKind.ERGOAI: ResultAuthority.CANDIDATE,
}

_ROUTE_EXACTNESS: Final[dict[ClassicalRouteKind, RouteExactness]] = {
    ClassicalRouteKind.Z3: RouteExactness.EXACT,
    ClassicalRouteKind.CVC5: RouteExactness.EXACT,
    ClassicalRouteKind.VAMPIRE: RouteExactness.EXACT,
    ClassicalRouteKind.E: RouteExactness.EXACT,
    ClassicalRouteKind.EPROVER: RouteExactness.EXACT,
    ClassicalRouteKind.SECPAL: RouteExactness.EXACT,
    ClassicalRouteKind.DATALOG_SECPAL: RouteExactness.EXACT,
    ClassicalRouteKind.ERGOAI: RouteExactness.APPROXIMATE,  # advisor-only
}

_ROUTE_LOGIC_FAMILIES: Final[dict[ClassicalRouteKind, frozenset[str]]] = {
    ClassicalRouteKind.Z3: frozenset(
        {"first_order", "smtlib2", "smt", "software_verification", "quantifier_free"}
    ),
    ClassicalRouteKind.CVC5: frozenset(
        {"first_order", "smtlib2", "smt", "software_verification", "quantifier_free"}
    ),
    ClassicalRouteKind.VAMPIRE: frozenset({"first_order", "tptp"}),
    ClassicalRouteKind.E: frozenset({"first_order", "tptp"}),
    ClassicalRouteKind.EPROVER: frozenset({"first_order", "tptp"}),
    ClassicalRouteKind.SECPAL: frozenset(
        {"authorization", "datalog", "secpal", "software_verification"}
    ),
    ClassicalRouteKind.DATALOG_SECPAL: frozenset(
        {"authorization", "datalog", "secpal", "software_verification"}
    ),
    ClassicalRouteKind.ERGOAI: frozenset({"frame_logic", FLOGIC_FAMILY_ID}),
}

_ROUTE_SOURCE_FORMATS: Final[dict[ClassicalRouteKind, frozenset[str]]] = {
    ClassicalRouteKind.Z3: frozenset({"smtlib2", "smt-lib", "smt-lib2"}),
    ClassicalRouteKind.CVC5: frozenset({"smtlib2", "smt-lib", "smt-lib2"}),
    ClassicalRouteKind.VAMPIRE: frozenset({"tptp", "tptp-fof", "tptp-cnf"}),
    ClassicalRouteKind.E: frozenset({"tptp", "tptp-fof", "tptp-cnf"}),
    ClassicalRouteKind.EPROVER: frozenset({"tptp", "tptp-fof", "tptp-cnf"}),
    ClassicalRouteKind.SECPAL: frozenset(
        {"authorization-ir", "authorization_ir", "authorization", "secpal"}
    ),
    ClassicalRouteKind.DATALOG_SECPAL: frozenset(
        {"authorization-ir", "authorization_ir", "authorization", "secpal", "datalog"}
    ),
    ClassicalRouteKind.ERGOAI: frozenset({"flogic", "ergoai", "controlled-flogic"}),
}


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise ClassicalAdapterError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL",
            code=CODE_MALFORMED,
            path=field_name,
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST_RE.fullmatch(result):
        raise ClassicalAdapterError(
            f"{field_name} must be a lowercase SHA-256 digest",
            code=CODE_MALFORMED,
            path=field_name,
        )
    return result


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _ID_RE.fullmatch(result):
        raise ClassicalAdapterError(
            f"{field_name} must be a safe identifier",
            code=CODE_MALFORMED,
            path=field_name,
        )
    return result


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ClassicalAdapterError(
            f"{field_name} must be one of {[item.value for item in enum_type]}",
            code=CODE_MALFORMED,
            path=field_name,
        ) from error


def content_digest(content: str) -> str:
    """Stable content digest for source binding."""

    return stable_digest({"content": content})


def normalize_route_kind(route: ClassicalRouteKind | str) -> ClassicalRouteKind:
    """Normalize provider/route aliases to a closed route kind."""

    if isinstance(route, ClassicalRouteKind):
        if route is ClassicalRouteKind.EPROVER:
            return ClassicalRouteKind.E
        if route is ClassicalRouteKind.DATALOG_SECPAL:
            return ClassicalRouteKind.SECPAL
        return route
    key = str(route).strip().lower()
    if key not in _PROVIDER_TO_ROUTE:
        raise ClassicalAdapterError(
            f"unsupported classical backend route: {route!r}",
            code=CODE_UNSUPPORTED_ROUTE,
            path="route",
        )
    kind = _PROVIDER_TO_ROUTE[key]
    if kind is ClassicalRouteKind.EPROVER:
        return ClassicalRouteKind.E
    if kind is ClassicalRouteKind.DATALOG_SECPAL:
        return ClassicalRouteKind.SECPAL
    return kind


def route_authority_ceiling(route: ClassicalRouteKind | str) -> ResultAuthority:
    """Maximum result authority a route may ever emit before promotion checks."""

    kind = normalize_route_kind(route)
    return _ROUTE_AUTHORITY_CEILING[kind]


def route_exactness(route: ClassicalRouteKind | str) -> RouteExactness:
    kind = normalize_route_kind(route)
    return _ROUTE_EXACTNESS[kind]


def is_exact_route(route: ClassicalRouteKind | str) -> bool:
    return route_exactness(route) is RouteExactness.EXACT


def reject_free_form_family(logic_family: object) -> str:
    """Admit only canonical family IDs; reject free-form labels."""

    family = _text(logic_family, "logic_family")
    normalized = family.strip().lower().replace("-", "_")
    # Reject natural-language-ish labels and unregistered free-form tokens.
    if " " in family or any(
        marker in normalized
        for marker in ("please", "prove_that", "natural_language", "free_form")
    ):
        raise FreeFormFamilyError(
            f"free-form family label rejected: {family!r}",
            path="logic_family",
        )
    # Accept only known canonical families for classical join routes.
    allowed = {
        "first_order",
        "smtlib2",
        "smt",
        "tptp",
        "datalog",
        "authorization",
        "secpal",
        "frame_logic",
        FLOGIC_FAMILY_ID,
        "software_verification",
        "quantifier_free",
        "propositional",
    }
    if normalized not in allowed and family not in _CANONICAL_FAMILIES:
        raise FreeFormFamilyError(
            f"unregistered or free-form family label rejected: {family!r}",
            path="logic_family",
        )
    return family


def reject_natural_language_payload(source: object, *, path: str = "source") -> str:
    """Reject natural-language payloads intended for backend reparse."""

    if not isinstance(source, str):
        raise ClassicalAdapterError(
            f"{path} must be a string of controlled target source",
            code=CODE_TYPED_SOURCE_REQUIRED,
            path=path,
        )
    text = source
    if "\x00" in text:
        raise ClassicalAdapterError(
            f"{path} must not contain NUL bytes",
            code=CODE_MALFORMED,
            path=path,
        )
    stripped = text.strip()
    if not stripped:
        raise ClassicalAdapterError(
            f"{path} must be non-empty controlled source",
            code=CODE_TYPED_SOURCE_REQUIRED,
            path=path,
        )
    lowered = stripped.lower()
    for marker in _NL_MARKERS:
        if marker in lowered:
            raise NaturalLanguageRejectedError(
                "backends must not reparse natural language; "
                f"found marker {marker!r}",
                path=path,
            )
    # Heuristic: long prose without logic punctuation is rejected.
    if (
        len(stripped) > 80
        and " " in stripped
        and not any(ch in stripped for ch in "():;-.!@?=")
        and not stripped.lstrip().startswith(("fof", "cnf", "tff", "(set-", "(assert", "forall", "exists"))
    ):
        # Allow short identifiers; reject paragraph-like free text.
        words = stripped.split()
        if len(words) >= 8 and all(word.isalpha() or word in {",", "."} for word in words[:8]):
            raise NaturalLanguageRejectedError(
                "backends must not reparse free-form natural language prose",
                path=path,
            )
    return stripped


def enforce_authority_ceiling(
    *,
    route: ClassicalRouteKind | str,
    authority: ResultAuthority | str,
    exactness: RouteExactness | str | None = None,
) -> ResultAuthority:
    """Fail closed when a result would exceed the route ceiling."""

    kind = normalize_route_kind(route)
    ceiling = route_authority_ceiling(kind)
    resolved = (
        authority
        if isinstance(authority, ResultAuthority)
        else ResultAuthority(str(authority))
    )
    exact = (
        route_exactness(kind)
        if exactness is None
        else (
            exactness
            if isinstance(exactness, RouteExactness)
            else RouteExactness(str(exactness))
        )
    )
    # Approximate / unsupported routes may never exceed candidate.
    if exact is not RouteExactness.EXACT and resolved is not ResultAuthority.CANDIDATE:
        if resolved not in {ResultAuthority.CANDIDATE}:
            raise AuthorityPromotionError(
                f"approximate/unsupported route {kind.value!r} cannot promote "
                f"authority to {resolved.value!r}"
            )
    # Ranked non-hierarchy: only allow authority equal to or "weaker" than ceiling.
    # We encode weakness as: candidate < authorization/satisfiability < theorem.
    _RANK: dict[ResultAuthority, int] = {
        ResultAuthority.CANDIDATE: 0,
        ResultAuthority.AUTHORIZATION: 1,
        ResultAuthority.SATISFIABILITY: 1,
        ResultAuthority.MONITOR: 1,
        ResultAuthority.MODEL_CHECK: 1,
        ResultAuthority.PROTOCOL: 1,
        ResultAuthority.HYPERPROPERTY: 1,
        ResultAuthority.RECONSTRUCTION: 2,
        ResultAuthority.ATTESTATION: 2,
        ResultAuthority.THEOREM: 3,
    }
    if _RANK.get(resolved, 99) > _RANK.get(ceiling, 0):
        raise AuthorityPromotionError(
            f"route {kind.value!r} authority ceiling is {ceiling.value!r}; "
            f"cannot emit {resolved.value!r}"
        )
    # Exact SMT routes may emit satisfiability or candidate, never theorem via join.
    if kind in {ClassicalRouteKind.Z3, ClassicalRouteKind.CVC5}:
        if resolved is ResultAuthority.THEOREM:
            raise AuthorityPromotionError(
                "classical SMT join does not mint theorem authority without "
                "an independent kernel reconstruction path"
            )
    return resolved


# ---------------------------------------------------------------------------
# Source binding / route receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassicalSourceBinding:
    """Identity of typed source submitted on one classical join route."""

    request_digest: str
    source_digest: str
    source_format: str
    notation_id: str
    parser_interface: str
    schema_version: str = CLASSICAL_SOURCE_BINDING_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format").lower()
        )
        object.__setattr__(
            self, "notation_id", _text(self.notation_id, "notation_id", optional=True)
        )
        object.__setattr__(
            self,
            "parser_interface",
            _text(self.parser_interface, "parser_interface", optional=True),
        )
        if self.schema_version != CLASSICAL_SOURCE_BINDING_SCHEMA:
            raise ClassicalAdapterError(
                f"unsupported source binding schema: {self.schema_version!r}",
                code=CODE_MALFORMED,
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "notation_id": self.notation_id,
            "parser_interface": self.parser_interface,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
        }


@dataclass(frozen=True, slots=True)
class ClassicalRouteReceipt:
    """Preservation and authority receipt for one classical backend join."""

    route: ClassicalRouteKind | str
    exactness: RouteExactness | str
    authority_ceiling: ResultAuthority | str
    logic_family: str
    source_format: str
    source_digest: str
    request_digest: str
    parser_interface: str
    backend_id: str
    availability: RouteAvailability | str
    proof_safe: bool = False
    counterexample_safe: bool = False
    unsupported_constructs: tuple[str, ...] = ()
    approximated_constructs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    schema_version: str = CLASSICAL_ROUTE_RECEIPT_SCHEMA
    interface: str = CLASSICAL_BACKEND_ADAPTER_INTERFACE
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "route", normalize_route_kind(self.route))
        object.__setattr__(
            self, "exactness", _enum(self.exactness, RouteExactness, "exactness")
        )
        ceiling = enforce_authority_ceiling(
            route=self.route,  # type: ignore[arg-type]
            authority=(
                self.authority_ceiling
                if isinstance(self.authority_ceiling, ResultAuthority)
                else ResultAuthority(str(self.authority_ceiling))
            ),
            exactness=self.exactness,  # type: ignore[arg-type]
        )
        object.__setattr__(self, "authority_ceiling", ceiling)
        object.__setattr__(
            self, "logic_family", reject_free_form_family(self.logic_family)
        )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format").lower()
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self,
            "parser_interface",
            _text(self.parser_interface, "parser_interface", optional=True),
        )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self,
            "availability",
            _enum(self.availability, RouteAvailability, "availability"),
        )
        for flag_name in ("proof_safe", "counterexample_safe"):
            if not isinstance(getattr(self, flag_name), bool):
                raise ClassicalAdapterError(
                    f"{flag_name} must be a boolean",
                    code=CODE_MALFORMED,
                    path=flag_name,
                )
        object.__setattr__(
            self,
            "unsupported_constructs",
            tuple(
                _text(item, "unsupported_constructs item")
                for item in self.unsupported_constructs
            ),
        )
        object.__setattr__(
            self,
            "approximated_constructs",
            tuple(
                _text(item, "approximated_constructs item")
                for item in self.approximated_constructs
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostics item") for item in self.diagnostics),
        )
        # Unsupported constructs force approximate exactness and candidate ceiling.
        if self.unsupported_constructs and self.exactness is RouteExactness.EXACT:
            object.__setattr__(self, "exactness", RouteExactness.UNSUPPORTED)
            object.__setattr__(self, "authority_ceiling", ResultAuthority.CANDIDATE)
        if self.approximated_constructs and self.exactness is RouteExactness.EXACT:
            object.__setattr__(self, "exactness", RouteExactness.APPROXIMATE)
            if self.authority_ceiling is ResultAuthority.THEOREM:
                object.__setattr__(self, "authority_ceiling", ResultAuthority.CANDIDATE)
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise ClassicalAdapterError(
                "receipt metadata must be immutable JSON data",
                code=CODE_MALFORMED,
                path="metadata",
            ) from error
        if self.schema_version != CLASSICAL_ROUTE_RECEIPT_SCHEMA:
            raise ClassicalAdapterError(
                f"unsupported receipt schema: {self.schema_version!r}",
                code=CODE_MALFORMED,
            )
        if self.interface != CLASSICAL_BACKEND_ADAPTER_INTERFACE:
            raise ClassicalAdapterError(
                f"unsupported adapter interface: {self.interface!r}",
                code=CODE_MALFORMED,
            )

    @property
    def can_promote_authority(self) -> bool:
        """Approximate/unsupported receipts never promote authority."""

        return (
            self.exactness is RouteExactness.EXACT
            and not self.unsupported_constructs
            and not self.approximated_constructs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approximated_constructs": list(self.approximated_constructs),
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ResultAuthority)
                else self.authority_ceiling
            ),
            "availability": (
                self.availability.value
                if isinstance(self.availability, RouteAvailability)
                else self.availability
            ),
            "backend_id": self.backend_id,
            "can_promote_authority": self.can_promote_authority,
            "counterexample_safe": self.counterexample_safe,
            "diagnostics": list(self.diagnostics),
            "exactness": (
                self.exactness.value
                if isinstance(self.exactness, RouteExactness)
                else self.exactness
            ),
            "interface": self.interface,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "parser_interface": self.parser_interface,
            "proof_safe": self.proof_safe,
            "request_digest": self.request_digest,
            "route": (
                self.route.value
                if isinstance(self.route, ClassicalRouteKind)
                else self.route
            ),
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
            "unsupported_constructs": list(self.unsupported_constructs),
        }


@dataclass(frozen=True, slots=True)
class ClassicalRouteResult:
    """Typed join outcome: backend result + authority-preserving receipt."""

    route: ClassicalRouteKind | str
    status: ResultStatus | str
    authority: ResultAuthority | str
    receipt: ClassicalRouteReceipt
    result: TypedBackendResult | None = None
    backend_request: BackendRequest | None = None
    source_binding: ClassicalSourceBinding | None = None
    reason: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = CLASSICAL_ROUTE_RESULT_SCHEMA
    interface: str = CLASSICAL_BACKEND_ADAPTER_INTERFACE
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "route", normalize_route_kind(self.route))
        object.__setattr__(
            self, "status", _enum(self.status, ResultStatus, "status")
        )
        authority = (
            self.authority
            if isinstance(self.authority, ResultAuthority)
            else ResultAuthority(str(self.authority))
        )
        enforce_authority_ceiling(
            route=self.route,  # type: ignore[arg-type]
            authority=authority,
            exactness=self.receipt.exactness,  # type: ignore[arg-type]
        )
        # Approximate receipts cannot claim conclusive non-candidate authority.
        if (
            not self.receipt.can_promote_authority
            and authority is not ResultAuthority.CANDIDATE
            and self.status
            not in {
                ResultStatus.UNAVAILABLE,
                ResultStatus.UNSUPPORTED,
                ResultStatus.UNKNOWN,
                ResultStatus.ERROR,
                ResultStatus.MALFORMED,
                ResultStatus.TIMEOUT,
            }
        ):
            raise AuthorityPromotionError(
                "approximate/unsupported classical route cannot promote authority"
            )
        object.__setattr__(self, "authority", authority)
        if not isinstance(self.receipt, ClassicalRouteReceipt):
            raise ClassicalAdapterError(
                "receipt must be a ClassicalRouteReceipt",
                code=CODE_MALFORMED,
                path="receipt",
            )
        if self.result is not None and not isinstance(self.result, TypedBackendResult):
            raise ClassicalAdapterError(
                "result must be a TypedBackendResult or None",
                code=CODE_MALFORMED,
                path="result",
            )
        if self.result is not None:
            enforce_authority_ceiling(
                route=self.route,  # type: ignore[arg-type]
                authority=self.result.authority,
                exactness=self.receipt.exactness,  # type: ignore[arg-type]
            )
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_text(item, "diagnostics item") for item in self.diagnostics),
        )
        try:
            object.__setattr__(self, "metadata", FrozenMap(self.metadata))
        except (TypeError, ValueError) as error:
            raise ClassicalAdapterError(
                "result metadata must be immutable JSON data",
                code=CODE_MALFORMED,
                path="metadata",
            ) from error
        if self.schema_version != CLASSICAL_ROUTE_RESULT_SCHEMA:
            raise ClassicalAdapterError(
                f"unsupported route result schema: {self.schema_version!r}",
                code=CODE_MALFORMED,
            )

    @property
    def unavailable(self) -> bool:
        return self.status is ResultStatus.UNAVAILABLE

    @property
    def is_conclusive(self) -> bool:
        return self.result is not None and self.result.is_conclusive

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": (
                self.authority.value
                if isinstance(self.authority, ResultAuthority)
                else self.authority
            ),
            "backend_request_digest": (
                None if self.backend_request is None else self.backend_request.digest
            ),
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "is_conclusive": self.is_conclusive,
            "metadata": self.metadata.to_dict(),
            "reason": self.reason,
            "receipt": self.receipt.to_dict(),
            "result": None if self.result is None else self.result.to_dict(),
            "route": (
                self.route.value
                if isinstance(self.route, ClassicalRouteKind)
                else self.route
            ),
            "schema_version": self.schema_version,
            "source_binding": (
                None if self.source_binding is None else self.source_binding.to_dict()
            ),
            "status": (
                self.status.value
                if isinstance(self.status, ResultStatus)
                else self.status
            ),
            "unavailable": self.unavailable,
        }


# ---------------------------------------------------------------------------
# Injectable backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class _RunnableBackend(Protocol):
    backend_id: str

    def is_available(self) -> bool: ...

    def run(self, request: BackendRequest, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# AuthorizationIR projection from controlled SecPAL RuleDocument
# ---------------------------------------------------------------------------


def _safe_id(prefix: str, value: str) -> str:
    cleaned = _SAFE_IDENT.sub("_", value).strip("_") or "anon"
    return f"{prefix}:{cleaned}"[:240]


def project_rule_document_to_authorization_ir(
    document: RuleDocument,
    *,
    source_ref_id: str = "source:classical-secpal",
) -> tuple[AuthorizationIR, DecisionQuery | None, tuple[str, ...]]:
    """Project a typed SecPAL/rule document into AuthorizationIR.

    Unsupported constructs are reported rather than silently dropped.
    Returns ``(ir, primary_query_or_none, unsupported_constructs)``.
    """

    if not isinstance(document, RuleDocument):
        raise ClassicalAdapterError(
            "SecPAL projection requires a RuleDocument",
            code=CODE_TYPED_SOURCE_REQUIRED,
            path="document",
        )
    unsupported: list[str] = []
    if document.has_unsupported:
        unsupported.append("unsupported_statements")
    if document.profile not in {RuleProfile.SECPAL, RuleProfile.HORN, RuleProfile.DATALOG}:
        unsupported.append(f"profile:{document.profile.value}")

    source = SourceRef(
        ref_id=source_ref_id,
        source_uri=f"classical://{source_ref_id}",
        source_id=source_ref_id,
        source_revision="classical-join",
        content_sha256=content_digest(document.source_text or print_rules(document)),
    )
    mapped = {
        "source_ref_ids": (source_ref_id,),
        "span_ids": (),
    }

    principal_ids: set[str] = set()
    trust_roots: list[str] = []
    for root in document.trust_roots:
        pid = _safe_id("principal", root)
        principal_ids.add(pid)
        trust_roots.append(pid)
    if not trust_roots:
        trust_roots = ["principal:system"]
        principal_ids.add("principal:system")

    def ensure_principal(name: str) -> str:
        pid = _safe_id("principal", name)
        principal_ids.add(pid)
        return pid

    def term_from_rule(term: Any, *, default_sort: str = "principal") -> AuthorizationTerm:
        name = str(getattr(term, "name", "") or getattr(term, "value", ""))
        if term.kind is RuleTermKind.VARIABLE:
            return AuthorizationTerm.variable(name, default_sort)
        return AuthorizationTerm.constant(name, default_sort)

    def atom_from_rule(atom: Any, *, default_sort: str = "principal") -> AuthorizationAtom:
        args = tuple(term_from_rule(t, default_sort=default_sort) for t in atom.arguments)
        polarity = AtomPolarity.NEGATIVE if atom.is_negative else AtomPolarity.POSITIVE
        return AuthorizationAtom(
            predicate_id=_safe_id("pred", atom.predicate),
            arguments=args,
            polarity=polarity,
        )

    facts: list[AuthorizationFact] = []
    rules: list[AuthorizationRule] = []
    queries: list[DecisionQuery] = []
    predicates: dict[str, tuple[str, int]] = {}

    for index, stmt in enumerate(document.statements):
        if stmt.kind is RuleStatementKind.UNSUPPORTED:
            unsupported.append(f"statement:{index}:unsupported")
            continue
        if stmt.kind is RuleStatementKind.FACT and stmt.head is not None:
            head = stmt.head
            predicates[head.predicate] = (
                head.predicate,
                len(head.arguments),
            )
            for arg in head.arguments:
                if arg.kind is RuleTermKind.CONSTANT:
                    ensure_principal(str(arg.name))
            issuer = (
                ensure_principal(str(head.issuer))
                if head.issuer
                else trust_roots[0]
            )
            facts.append(
                AuthorizationFact(
                    fact_id=_safe_id("fact", f"{index}-{head.predicate}"),
                    atom=atom_from_rule(head),
                    issuer_principal_id=issuer,
                    **mapped,
                )
            )
            continue
        if stmt.kind in {RuleStatementKind.RULE, RuleStatementKind.CHC} and stmt.head is not None:
            head = stmt.head
            predicates[head.predicate] = (head.predicate, len(head.arguments))
            for atom in (head, *stmt.body):
                if atom is None:
                    continue
                predicates[atom.predicate] = (atom.predicate, len(atom.arguments))
            effect = EffectKind.DERIVE
            if stmt.effect is RuleEffect.ALLOW:
                effect = EffectKind.ALLOW
            elif stmt.effect is RuleEffect.DENY:
                effect = EffectKind.DENY
            # Prefer explicit SecPAL says issuer on the head atom.
            issuer = ensure_principal(str(head.issuer)) if head.issuer else ""
            kind = (
                RuleKind.SECPAL_SAYS
                if document.profile is RuleProfile.SECPAL and issuer
                else RuleKind.DATALOG
            )
            if kind is RuleKind.SECPAL_SAYS and not issuer:
                unsupported.append(f"statement:{index}:secpal_says_missing_issuer")
                continue
            rules.append(
                AuthorizationRule(
                    rule_id=_safe_id("rule", f"{index}-{head.predicate}"),
                    head=atom_from_rule(head),
                    body=tuple(atom_from_rule(a) for a in stmt.body),
                    kind=kind,
                    effect=effect,
                    stratum=max(0, int(stmt.stratum or 0)),
                    issuer_principal_id=issuer,
                    **mapped,
                )
            )
            continue
        if stmt.kind is RuleStatementKind.QUERY:
            # Prefer structured SecPAL query fields when present.
            if stmt.principal:
                principal = ensure_principal(stmt.principal)
                action = stmt.action or "read"
                resource = stmt.resource or "resource"
            else:
                principal = "principal:anonymous"
                action = "read"
                resource = "resource"
                if stmt.body:
                    first = stmt.body[0]
                    if first.arguments:
                        principal = ensure_principal(str(first.arguments[0].name))
                        if len(first.arguments) >= 2:
                            action = str(first.arguments[1].name)
                        if len(first.arguments) >= 3:
                            resource = str(first.arguments[2].name)
            # DecisionQuery.action must be a safe identifier.
            action_id = _SAFE_IDENT.sub("_", action).strip("_") or "read"
            queries.append(
                DecisionQuery(
                    query_id=_safe_id("query", f"{index}"),
                    principal_id=principal,
                    action=action_id,
                    resource=resource,
                    **mapped,
                )
            )
            continue
        if stmt.kind in {
            RuleStatementKind.DELEGATION,
            RuleStatementKind.SPEAKS_FOR,
            RuleStatementKind.CONSTRAINT,
        }:
            # Keep as unsupported for the minimal projection (no silent drop).
            unsupported.append(f"statement:{index}:{stmt.kind.value}")
            continue

    principals = tuple(
        AuthorizationPrincipal(
            principal_id=pid,
            name=pid.split(":", 1)[-1],
            kind=PrincipalKind.SYSTEM if pid.endswith("system") else PrincipalKind.USER,
            **mapped,
        )
        for pid in sorted(principal_ids)
    )
    from ipfs_datasets_py.logic.software_verification.authorization import (
        PredicateSignature,
    )

    pred_sigs = tuple(
        PredicateSignature(
            predicate_id=_safe_id("pred", name),
            name=name,
            arity=arity,
            argument_sorts=tuple(["principal"] * arity),
            is_intensional=True,
            **mapped,
        )
        for name, arity in sorted(
            ((n, a) for n, (_, a) in predicates.items()),
            key=lambda item: item[0],
        )
    )

    # Default query when none declared: unknown decision over system principal.
    if not queries and facts:
        queries = [
            DecisionQuery(
                query_id="query:default",
                principal_id=trust_roots[0],
                action="read",
                resource="resource",
                **mapped,
            )
        ]

    ir = AuthorizationIR(
        sources=(source,),
        principals=principals,
        trust_root_principal_ids=tuple(trust_roots),
        predicates=pred_sigs,
        facts=tuple(facts),
        rules=tuple(rules),
        queries=tuple(queries),
        metadata=FrozenMap(
            {
                "projected_from": "RuleDocument",
                "profile": document.profile.value,
                "family_id": document.family_id,
            }
        ),
    )
    primary = queries[0] if queries else None
    return ir, primary, tuple(dict.fromkeys(unsupported))


# ---------------------------------------------------------------------------
# ClassicalBackendAdapter@1
# ---------------------------------------------------------------------------


class ClassicalBackendAdapter:
    """Join classical/rule parser outputs to shared backend routes.

    Interface: ``ClassicalBackendAdapter@1``.

    Construction is side-effect free.  Availability is probed only at
    :meth:`is_available` / :meth:`run` time.  Natural language and free-form
    family labels are rejected before any backend is invoked.
    """

    INTERFACE: ClassVar[str] = CLASSICAL_BACKEND_ADAPTER_INTERFACE
    interface: ClassVar[str] = CLASSICAL_BACKEND_ADAPTER_INTERFACE
    VERSION: ClassVar[str] = CLASSICAL_BACKEND_ADAPTER_VERSION

    def __init__(
        self,
        *,
        z3: _RunnableBackend | None = None,
        cvc5: _RunnableBackend | None = None,
        vampire: _RunnableBackend | None = None,
        eprover: _RunnableBackend | None = None,
        secpal: _RunnableBackend | None = None,
        availability: Mapping[str, bool] | None = None,
        default_bounds: ExecutionBounds | None = None,
    ) -> None:
        self._z3 = z3
        self._cvc5 = cvc5
        self._vampire = vampire
        self._eprover = eprover
        self._secpal = secpal
        self._availability_overrides = {
            str(key).lower(): bool(value)
            for key, value in dict(availability or {}).items()
        }
        self._default_bounds = default_bounds or ExecutionBounds(
            timeout_ms=5_000,
            max_steps=10_000,
            max_memory_bytes=64 * 1024 * 1024,
            max_output_bytes=256 * 1024,
        )
        self._lazy: dict[str, _RunnableBackend] = {}

    # -- discovery ---------------------------------------------------------

    def known_routes(self) -> tuple[str, ...]:
        return tuple(sorted({kind.value for kind in ClassicalRouteKind}))

    def describe_route(self, route: ClassicalRouteKind | str) -> dict[str, Any]:
        kind = normalize_route_kind(route)
        return {
            "authority_ceiling": route_authority_ceiling(kind).value,
            "exactness": route_exactness(kind).value,
            "logic_families": sorted(_ROUTE_LOGIC_FAMILIES[kind]),
            "provider_id": kind.value,
            "route": kind.value,
            "source_formats": sorted(_ROUTE_SOURCE_FORMATS[kind]),
        }

    def is_available(self, route: ClassicalRouteKind | str) -> bool:
        kind = normalize_route_kind(route)
        if kind is ClassicalRouteKind.ERGOAI:
            # Advisor surface is always "available" as a local candidate path.
            return True
        key = kind.value
        if key in self._availability_overrides:
            return self._availability_overrides[key]
        backend = self._backend_for(kind)
        if backend is None:
            return False
        try:
            return bool(backend.is_available())
        except Exception:
            return False

    def _backend_for(self, kind: ClassicalRouteKind) -> _RunnableBackend | None:
        if kind is ClassicalRouteKind.Z3:
            if self._z3 is not None:
                return self._z3
            if "z3" not in self._lazy:
                self._lazy["z3"] = Z3Backend()
            return self._lazy["z3"]
        if kind is ClassicalRouteKind.CVC5:
            if self._cvc5 is not None:
                return self._cvc5
            if "cvc5" not in self._lazy:
                self._lazy["cvc5"] = CVC5Backend()
            return self._lazy["cvc5"]
        if kind is ClassicalRouteKind.VAMPIRE:
            if self._vampire is not None:
                return self._vampire
            if "vampire" not in self._lazy:
                self._lazy["vampire"] = VampireBackend()
            return self._lazy["vampire"]
        if kind is ClassicalRouteKind.E:
            if self._eprover is not None:
                return self._eprover
            if "e" not in self._lazy:
                self._lazy["e"] = EProverBackend()
            return self._lazy["e"]
        if kind is ClassicalRouteKind.SECPAL:
            if self._secpal is not None:
                return self._secpal
            if "secpal" not in self._lazy:
                # Reference evaluator only — hermetic, no external engine.
                self._lazy["secpal"] = SecPALAuthorizationBackend(
                    use_external_engine=False
                )
            return self._lazy["secpal"]
        return None

    # -- request builders --------------------------------------------------

    def _make_request(
        self,
        *,
        route: ClassicalRouteKind,
        logic_family: str,
        query_kind: QueryKind,
        payload: Mapping[str, Any],
        request_id: str,
        claim_id: str = "claim:classical-join",
        obligation_id: str = "obl:classical-join",
        bounds: ExecutionBounds | None = None,
    ) -> BackendRequest:
        family = reject_free_form_family(logic_family)
        allowed = _ROUTE_LOGIC_FAMILIES[route]
        if family not in allowed and family.lower() not in {f.lower() for f in allowed}:
            # Map notation-style families onto admitted backend families.
            if route in {ClassicalRouteKind.Z3, ClassicalRouteKind.CVC5}:
                family = "first_order"
            elif route in {ClassicalRouteKind.VAMPIRE, ClassicalRouteKind.E}:
                family = "first_order"
            elif route is ClassicalRouteKind.SECPAL:
                family = "authorization"
            elif route is ClassicalRouteKind.ERGOAI:
                family = FLOGIC_FAMILY_ID
            else:
                raise FreeFormFamilyError(
                    f"family {logic_family!r} is not admitted on route {route.value}"
                )
        body = dict(payload)
        # Never accept free-form family labels inside payload.
        if "logic_family" in body:
            body["logic_family"] = reject_free_form_family(body["logic_family"])
        if "family" in body:
            raise FreeFormFamilyError(
                "payload.family free-form labels are rejected; use logic_family"
            )
        claim_digest = stable_digest(
            {"claim_id": claim_id, "route": route.value, "family": family}
        )
        obligation_digest = stable_digest(
            {"obligation_id": obligation_id, "payload": body}
        )
        return BackendRequest(
            request_id=_identifier(request_id, "request_id"),
            claim_id=_identifier(claim_id, "claim_id"),
            declaration_id=f"decl:{route.value}",
            claim_digest=claim_digest,
            obligation_id=_identifier(obligation_id, "obligation_id"),
            obligation_digest=obligation_digest,
            assumption_ids=(),
            logic_family=family,
            query_kind=query_kind,
            bounds=bounds or self._default_bounds,
            payload=FrozenMap(body),
            requested_backend_id=route.value if route is not ClassicalRouteKind.E else "e",
        )

    def build_smt_request(
        self,
        document: SmtlibDocument | str,
        *,
        route: ClassicalRouteKind | str = ClassicalRouteKind.Z3,
        query_kind: QueryKind | str = QueryKind.SATISFIABILITY,
        request_id: str = "req:classical-smt:1",
        bounds: ExecutionBounds | None = None,
    ) -> tuple[BackendRequest, ClassicalSourceBinding, str]:
        """Build a Z3/cvc5 request from a typed SMT-LIB document or printout."""

        kind = normalize_route_kind(route)
        if kind not in {ClassicalRouteKind.Z3, ClassicalRouteKind.CVC5}:
            raise ClassicalAdapterError(
                f"SMT requests require z3 or cvc5 route, not {kind.value!r}",
                code=CODE_UNSUPPORTED_ROUTE,
            )
        if isinstance(document, SmtlibDocument):
            source = print_smtlib2(document)
            parser_interface = "SMTLIB2Frontend@1"
            notation_id = SMTLIB2_NOTATION_ID
        elif isinstance(document, str):
            source = reject_natural_language_payload(document, path="smtlib_source")
            # Controlled SMT-LIB must look like S-expressions, not prose.
            if "(" not in source:
                raise ClassicalAdapterError(
                    "SMT-LIB source must be explicit controlled S-expression text",
                    code=CODE_TYPED_SOURCE_REQUIRED,
                    path="smtlib_source",
                )
            parser_interface = "SMTLIB2Frontend@1"
            notation_id = SMTLIB2_NOTATION_ID
        else:
            raise ClassicalAdapterError(
                "SMT route requires SmtlibDocument or controlled SMT-LIB source",
                code=CODE_TYPED_SOURCE_REQUIRED,
            )
        qk = (
            query_kind
            if isinstance(query_kind, QueryKind)
            else QueryKind(str(query_kind))
        )
        payload = {
            "encoding": "smtlib2",
            "source": source,
            "smtlib": source,
            "source_format": "smtlib2",
            "notation_id": notation_id,
            "parser_interface": parser_interface,
        }
        request = self._make_request(
            route=kind,
            logic_family="first_order",
            query_kind=qk,
            payload=payload,
            request_id=request_id,
            bounds=bounds,
        )
        binding = ClassicalSourceBinding(
            request_digest=request.digest,
            source_digest=content_digest(source),
            source_format="smtlib2",
            notation_id=notation_id,
            parser_interface=parser_interface,
        )
        return request, binding, source

    def build_tptp_request(
        self,
        document: TPTPDocument | str,
        *,
        route: ClassicalRouteKind | str = ClassicalRouteKind.VAMPIRE,
        query_kind: QueryKind | str = QueryKind.THEOREM_PROOF,
        request_id: str = "req:classical-tptp:1",
        bounds: ExecutionBounds | None = None,
    ) -> tuple[BackendRequest, ClassicalSourceBinding, str]:
        """Build a Vampire/E request from a typed TPTP document or printout."""

        kind = normalize_route_kind(route)
        if kind not in {ClassicalRouteKind.VAMPIRE, ClassicalRouteKind.E}:
            raise ClassicalAdapterError(
                f"TPTP requests require vampire or e route, not {kind.value!r}",
                code=CODE_UNSUPPORTED_ROUTE,
            )
        if isinstance(document, TPTPDocument):
            source = print_tptp(document)
            parser_interface = "TPTPFrontend@1"
            notation_id = TPTP_NOTATION_ID
        elif isinstance(document, str):
            source = reject_natural_language_payload(document, path="tptp_source")
            head = source.lstrip()[:8].lower()
            if not any(head.startswith(tag) for tag in ("fof", "cnf", "tff", "%", "include")):
                raise ClassicalAdapterError(
                    "TPTP source must be explicit controlled problem text",
                    code=CODE_TYPED_SOURCE_REQUIRED,
                    path="tptp_source",
                )
            parser_interface = "TPTPFrontend@1"
            notation_id = TPTP_NOTATION_ID
        else:
            raise ClassicalAdapterError(
                "ATP route requires TPTPDocument or controlled TPTP source",
                code=CODE_TYPED_SOURCE_REQUIRED,
            )
        qk = (
            query_kind
            if isinstance(query_kind, QueryKind)
            else QueryKind(str(query_kind))
        )
        payload = {
            "encoding": "tptp",
            "source": source,
            "tptp": source,
            "source_format": "tptp",
            "notation_id": notation_id,
            "parser_interface": parser_interface,
        }
        request = self._make_request(
            route=kind,
            logic_family="first_order",
            query_kind=qk,
            payload=payload,
            request_id=request_id,
            bounds=bounds,
        )
        binding = ClassicalSourceBinding(
            request_digest=request.digest,
            source_digest=content_digest(source),
            source_format="tptp",
            notation_id=notation_id,
            parser_interface=parser_interface,
        )
        return request, binding, source

    def build_secpal_request(
        self,
        document: AuthorizationIR | RuleDocument,
        *,
        query: DecisionQuery | Mapping[str, Any] | None = None,
        request_id: str = "req:classical-secpal:1",
        bounds: ExecutionBounds | None = None,
    ) -> tuple[BackendRequest, ClassicalSourceBinding, AuthorizationIR, DecisionQuery, tuple[str, ...]]:
        """Build a SecPAL authorization request from typed IR or RuleDocument."""

        unsupported: tuple[str, ...] = ()
        if isinstance(document, AuthorizationIR):
            ir = document
            primary_query = None
        elif isinstance(document, RuleDocument):
            ir, primary_query, unsupported = project_rule_document_to_authorization_ir(
                document
            )
        else:
            raise ClassicalAdapterError(
                "SecPAL route requires AuthorizationIR or typed RuleDocument",
                code=CODE_TYPED_SOURCE_REQUIRED,
            )

        if isinstance(query, DecisionQuery):
            decision_query = query
        elif isinstance(query, Mapping):
            decision_query = DecisionQuery.from_dict(query)
        elif primary_query is not None:
            decision_query = primary_query
        elif len(ir.queries) == 1:
            decision_query = ir.queries[0]
        elif ir.queries:
            decision_query = ir.queries[0]
        else:
            raise ClassicalAdapterError(
                "SecPAL route requires a DecisionQuery",
                code=CODE_TYPED_SOURCE_REQUIRED,
                path="query",
            )

        payload = {
            "encoding": "authorization-ir",
            "source_format": "authorization-ir",
            "authorization_ir": ir.to_dict(),
            "query": decision_query.to_dict(),
            "parser_interface": "SecPALFrontend@1",
            "notation_id": SECPAL_PROFILE_ID,
        }
        request = self._make_request(
            route=ClassicalRouteKind.SECPAL,
            logic_family="authorization",
            query_kind=QueryKind.POLICY_APPROVAL,
            payload=payload,
            request_id=request_id,
            bounds=bounds,
        )
        # Prefer the AuthorizationIR content digest for the source binding.
        source_digest = ir.sha256 if len(ir.sha256) == 64 else content_digest(
            ir.document_id
        )
        binding = ClassicalSourceBinding(
            request_digest=request.digest,
            source_digest=source_digest,
            source_format="authorization-ir",
            notation_id=SECPAL_PROFILE_ID,
            parser_interface="SecPALFrontend@1",
        )
        return request, binding, ir, decision_query, unsupported

    def build_ergoai_candidate(
        self,
        document: FLogicDocument | ErgoAIControlledSource | str,
        *,
        request_id: str = "req:classical-ergoai:1",
    ) -> tuple[CandidateResult, ClassicalRouteReceipt, ClassicalSourceBinding]:
        """Materialize an ErgoAI advisor-only candidate (never executes ErgoAI)."""

        if isinstance(document, ErgoAIControlledSource):
            controlled = document
            source_text = print_flogic(controlled.document)
        elif isinstance(document, FLogicDocument):
            controlled = ErgoAIControlledSource.from_document(document)
            source_text = print_flogic(document)
        elif isinstance(document, str):
            # Controlled source only — still not natural language reparse by backend.
            text = reject_natural_language_payload(document, path="flogic_source")
            parsed = FLogicFrontend().parse_text(text)
            if not parsed.ok or parsed.document is None:
                raise ClassicalAdapterError(
                    "ErgoAI route requires a successfully parsed F-logic document",
                    code=CODE_PARSE_REQUIRED,
                )
            controlled = ErgoAIControlledSource.from_document(parsed.document)
            source_text = print_flogic(parsed.document)
        else:
            raise ClassicalAdapterError(
                "ErgoAI route requires FLogicDocument or ErgoAIControlledSource",
                code=CODE_TYPED_SOURCE_REQUIRED,
            )

        # Hard authority: advisor/candidate only.
        if controlled.authority is not ResultAuthority.CANDIDATE:
            raise AuthorityPromotionError("ErgoAI controlled source must stay candidate")
        if role_can_satisfy_certified_authority(
            controlled.role, controlled.authority_ceiling
        ):
            raise AuthorityPromotionError(
                "ErgoAI cannot satisfy certified authority on classical join"
            )

        source_digest = content_digest(source_text)
        request_digest = stable_digest(
            {
                "request_id": request_id,
                "route": ClassicalRouteKind.ERGOAI.value,
                "source_digest": source_digest,
            }
        )
        binding = ClassicalSourceBinding(
            request_digest=request_digest,
            source_digest=source_digest,
            source_format="flogic",
            notation_id="flogic",
            parser_interface=ERGOAI_CONTROLLED_SOURCE_INTERFACE,
        )
        receipt = ClassicalRouteReceipt(
            route=ClassicalRouteKind.ERGOAI,
            exactness=RouteExactness.APPROXIMATE,
            authority_ceiling=ResultAuthority.CANDIDATE,
            logic_family=FLOGIC_FAMILY_ID,
            source_format="flogic",
            source_digest=source_digest,
            request_digest=request_digest,
            parser_interface=ERGOAI_CONTROLLED_SOURCE_INTERFACE,
            backend_id=FLOGIC_PROVIDER_ID,
            availability=RouteAvailability.AVAILABLE,
            proof_safe=False,
            counterexample_safe=False,
            approximated_constructs=("ergoai_advisor_only",),
            diagnostics=(
                "ErgoAI route emits advisor/candidate evidence only; "
                "execution remains lazy",
            ),
            metadata=FrozenMap(
                {
                    "role": ToolRole.ADVISOR.value,
                    "authority_ceiling": ToolchainAuthorityCeiling.ADVISORY.value,
                    "grants_proof_authority": False,
                    "provider_id": controlled.provider_id,
                    "trusted": False,
                }
            ),
        )
        result = CandidateResult(
            result_id=f"result:ergoai:{source_digest[:16]}",
            backend_id=FLOGIC_PROVIDER_ID,
            backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
            authority=ResultAuthority.CANDIDATE,
            status=ResultStatus.CANDIDATE,
            translation_ceiling=EvidenceAuthority.NONE,
            usage=ResourceUsage(),
            witness=FrozenMap(
                {
                    "provider_id": FLOGIC_PROVIDER_ID,
                    "controlled_source_interface": ERGOAI_CONTROLLED_SOURCE_INTERFACE,
                    "source_digest": source_digest,
                    "advisor_only": True,
                    "document_profile": controlled.document.profile_id
                    if hasattr(controlled.document, "profile_id")
                    else "frame_core",
                }
            ),
            reason="ErgoAI join is advisor/candidate only",
            metadata=FrozenMap({"route": ClassicalRouteKind.ERGOAI.value}),
        )
        return result, receipt, binding

    # -- run ---------------------------------------------------------------

    def _unavailable_result(
        self,
        *,
        route: ClassicalRouteKind,
        request: BackendRequest,
        binding: ClassicalSourceBinding,
        parser_interface: str,
        logic_family: str,
        source_format: str,
        reason: str,
        unsupported: Sequence[str] = (),
        approximated: Sequence[str] = (),
    ) -> ClassicalRouteResult:
        exactness = (
            RouteExactness.UNSUPPORTED
            if unsupported
            else (
                RouteExactness.APPROXIMATE
                if approximated
                else route_exactness(route)
            )
        )
        ceiling = (
            ResultAuthority.CANDIDATE
            if exactness is not RouteExactness.EXACT
            else route_authority_ceiling(route)
        )
        receipt = ClassicalRouteReceipt(
            route=route,
            exactness=exactness,
            authority_ceiling=ceiling,
            logic_family=logic_family,
            source_format=source_format,
            source_digest=binding.source_digest,
            request_digest=request.digest,
            parser_interface=parser_interface,
            backend_id=route.value if route is not ClassicalRouteKind.E else "e",
            availability=RouteAvailability.UNAVAILABLE,
            unsupported_constructs=tuple(unsupported),
            approximated_constructs=tuple(approximated),
            diagnostics=(reason,),
        )
        result = CandidateResult(
            result_id=f"result:{route.value}:unavailable:{request.digest[:12]}",
            backend_id=route.value if route is not ClassicalRouteKind.E else "e",
            backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
            authority=ResultAuthority.CANDIDATE,
            status=ResultStatus.UNAVAILABLE,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            translation_ceiling=EvidenceAuthority.NONE,
            usage=ResourceUsage(),
            reason=reason,
            diagnostics=(reason,),
            metadata=FrozenMap(
                {
                    "route": route.value,
                    "availability": RouteAvailability.UNAVAILABLE.value,
                }
            ),
        )
        return ClassicalRouteResult(
            route=route,
            status=ResultStatus.UNAVAILABLE,
            authority=ResultAuthority.CANDIDATE,
            receipt=receipt,
            result=result,
            backend_request=request,
            source_binding=binding,
            reason=reason,
            diagnostics=(reason,),
        )

    def _wrap_typed(
        self,
        *,
        route: ClassicalRouteKind,
        request: BackendRequest,
        binding: ClassicalSourceBinding,
        typed: TypedBackendResult,
        parser_interface: str,
        logic_family: str,
        source_format: str,
        unsupported: Sequence[str] = (),
        approximated: Sequence[str] = (),
        proof_safe: bool = False,
        counterexample_safe: bool = False,
    ) -> ClassicalRouteResult:
        exactness = route_exactness(route)
        if unsupported:
            exactness = RouteExactness.UNSUPPORTED
        elif approximated:
            exactness = RouteExactness.APPROXIMATE
        # Cap authority for non-exact.
        authority = typed.authority
        if exactness is not RouteExactness.EXACT:
            authority = ResultAuthority.CANDIDATE
        else:
            enforce_authority_ceiling(route=route, authority=authority, exactness=exactness)
        receipt = ClassicalRouteReceipt(
            route=route,
            exactness=exactness,
            authority_ceiling=(
                ResultAuthority.CANDIDATE
                if exactness is not RouteExactness.EXACT
                else route_authority_ceiling(route)
            ),
            logic_family=logic_family,
            source_format=source_format,
            source_digest=binding.source_digest,
            request_digest=request.digest,
            parser_interface=parser_interface,
            backend_id=typed.backend_id,
            availability=RouteAvailability.AVAILABLE,
            proof_safe=proof_safe and exactness is RouteExactness.EXACT,
            counterexample_safe=counterexample_safe and exactness is RouteExactness.EXACT,
            unsupported_constructs=tuple(unsupported),
            approximated_constructs=tuple(approximated),
        )
        return ClassicalRouteResult(
            route=route,
            status=typed.status,
            authority=authority if exactness is RouteExactness.EXACT else ResultAuthority.CANDIDATE,
            receipt=receipt,
            result=typed,
            backend_request=request,
            source_binding=binding,
            reason=typed.reason,
            diagnostics=typed.diagnostics,
        )

    def run_smt(
        self,
        document: SmtlibDocument | str,
        *,
        route: ClassicalRouteKind | str = ClassicalRouteKind.Z3,
        query_kind: QueryKind | str = QueryKind.SATISFIABILITY,
        request_id: str = "req:classical-smt:1",
        bounds: ExecutionBounds | None = None,
    ) -> ClassicalRouteResult:
        """Join SMT-LIB typed source to Z3 or cvc5 (hermetic or unavailable)."""

        kind = normalize_route_kind(route)
        request, binding, _source = self.build_smt_request(
            document,
            route=kind,
            query_kind=query_kind,
            request_id=request_id,
            bounds=bounds,
        )
        if not self.is_available(kind):
            return self._unavailable_result(
                route=kind,
                request=request,
                binding=binding,
                parser_interface="SMTLIB2Frontend@1",
                logic_family="first_order",
                source_format="smtlib2",
                reason=f"{kind.value} backend is unavailable",
            )
        backend = self._backend_for(kind)
        assert backend is not None
        outcome = backend.run(request)
        typed = self._normalize_smt_outcome(kind, request, outcome)
        return self._wrap_typed(
            route=kind,
            request=request,
            binding=binding,
            typed=typed,
            parser_interface="SMTLIB2Frontend@1",
            logic_family="first_order",
            source_format="smtlib2",
            proof_safe=typed.authority is ResultAuthority.SATISFIABILITY
            and typed.status is ResultStatus.UNSATISFIABLE,
            counterexample_safe=typed.authority is ResultAuthority.SATISFIABILITY
            and typed.status is ResultStatus.SATISFIABLE,
        )

    def _normalize_smt_outcome(
        self,
        route: ClassicalRouteKind,
        request: BackendRequest,
        outcome: Any,
    ) -> TypedBackendResult:
        """Normalize Z3/cvc5 registry outcomes into typed backend results."""

        # CallableProofBackend returns (BackendAttempt, BoundedResult).
        if isinstance(outcome, tuple) and len(outcome) == 2:
            _attempt, bounded = outcome
            status_name = getattr(getattr(bounded, "status", None), "value", str(getattr(bounded, "status", "unknown")))
            classification = ""
            if hasattr(bounded, "to_dict"):
                payload = bounded.to_dict()
                classification = str(
                    payload.get("classification")
                    or payload.get("metadata", {}).get("classification")
                    or ""
                )
            # Map legacy statuses.
            if status_name in {"unknown"} and classification == "unavailable":
                return CandidateResult(
                    result_id=f"result:{route.value}:{request.digest[:12]}",
                    backend_id=route.value,
                    backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
                    authority=ResultAuthority.CANDIDATE,
                    status=ResultStatus.UNAVAILABLE,
                    assumptions=request.assumption_ids,
                    bounds=request.bounds,
                    reason=f"{route.value} unavailable",
                )
            if status_name in {"satisfiable"}:
                return SatisfiabilityResult(
                    result_id=f"result:{route.value}:{request.digest[:12]}",
                    backend_id=route.value,
                    backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
                    authority=ResultAuthority.SATISFIABILITY,
                    status=ResultStatus.SATISFIABLE,
                    assumptions=request.assumption_ids,
                    bounds=request.bounds,
                )
            if status_name in {"unsatisfiable"}:
                return SatisfiabilityResult(
                    result_id=f"result:{route.value}:{request.digest[:12]}",
                    backend_id=route.value,
                    backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
                    authority=ResultAuthority.SATISFIABILITY,
                    status=ResultStatus.UNSATISFIABLE,
                    assumptions=request.assumption_ids,
                    bounds=request.bounds,
                )
            if status_name in {"proved"}:
                # Join surface does not mint theorem authority from SMT alone.
                return SatisfiabilityResult(
                    result_id=f"result:{route.value}:{request.digest[:12]}",
                    backend_id=route.value,
                    backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
                    authority=ResultAuthority.SATISFIABILITY,
                    status=ResultStatus.UNSATISFIABLE,
                    assumptions=request.assumption_ids,
                    bounds=request.bounds,
                    reason="theorem_by_negation normalized to unsat (satisfiability authority)",
                )
            if status_name in {"disproved"}:
                return SatisfiabilityResult(
                    result_id=f"result:{route.value}:{request.digest[:12]}",
                    backend_id=route.value,
                    backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
                    authority=ResultAuthority.SATISFIABILITY,
                    status=ResultStatus.SATISFIABLE,
                    assumptions=request.assumption_ids,
                    bounds=request.bounds,
                )
            return CandidateResult(
                result_id=f"result:{route.value}:{request.digest[:12]}",
                backend_id=route.value,
                backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
                authority=ResultAuthority.CANDIDATE,
                status=ResultStatus.UNKNOWN,
                assumptions=request.assumption_ids,
                bounds=request.bounds,
                reason=f"unclassified SMT status {status_name!r}",
            )
        if isinstance(outcome, TypedBackendResult):
            if isinstance(outcome, TheoremResult):
                # Demote theorem claims from SMT join to satisfiability/candidate.
                return SatisfiabilityResult(
                    result_id=outcome.result_id,
                    backend_id=outcome.backend_id,
                    backend_version=outcome.backend_version,
                    authority=ResultAuthority.SATISFIABILITY,
                    status=(
                        ResultStatus.UNSATISFIABLE
                        if outcome.status is ResultStatus.PROVED
                        else ResultStatus.SATISFIABLE
                        if outcome.status is ResultStatus.DISPROVED
                        else ResultStatus.UNKNOWN
                    ),
                    assumptions=outcome.assumptions,
                    bounds=outcome.bounds,
                    usage=outcome.usage,
                    witness=outcome.witness,
                    diagnostics=outcome.diagnostics,
                    reason="SMT join demotes theorem authority to satisfiability",
                    metadata=outcome.metadata,
                )
            return outcome
        raise ClassicalAdapterError(
            f"unexpected SMT backend outcome type: {type(outcome)!r}",
            code=CODE_ROUTE,
        )

    def run_atp(
        self,
        document: TPTPDocument | str,
        *,
        route: ClassicalRouteKind | str = ClassicalRouteKind.VAMPIRE,
        query_kind: QueryKind | str = QueryKind.THEOREM_PROOF,
        request_id: str = "req:classical-tptp:1",
        bounds: ExecutionBounds | None = None,
    ) -> ClassicalRouteResult:
        """Join TPTP typed source to Vampire or E (hermetic or unavailable)."""

        kind = normalize_route_kind(route)
        request, binding, _source = self.build_tptp_request(
            document,
            route=kind,
            query_kind=query_kind,
            request_id=request_id,
            bounds=bounds,
        )
        if not self.is_available(kind):
            return self._unavailable_result(
                route=kind,
                request=request,
                binding=binding,
                parser_interface="TPTPFrontend@1",
                logic_family="first_order",
                source_format="tptp",
                reason=f"{kind.value} backend is unavailable",
            )
        backend = self._backend_for(kind)
        assert backend is not None
        outcome = backend.run(request)
        if isinstance(outcome, ATPAdapterOutcome):
            typed = outcome.result
        elif isinstance(outcome, TypedBackendResult):
            typed = outcome
        else:
            raise ClassicalAdapterError(
                f"unexpected ATP outcome type: {type(outcome)!r}",
                code=CODE_ROUTE,
            )
        # ATP evidence without reconstruction remains candidate.
        if typed.authority is ResultAuthority.THEOREM:
            typed = CandidateResult(
                result_id=typed.result_id,
                backend_id=typed.backend_id,
                backend_version=typed.backend_version,
                authority=ResultAuthority.CANDIDATE,
                status=ResultStatus.CANDIDATE,
                assumptions=typed.assumptions,
                bounds=typed.bounds,
                usage=typed.usage,
                witness=typed.witness,
                diagnostics=typed.diagnostics + ("atp_unreconstructed_candidate",),
                reason="ATP evidence remains candidate until reconstruction",
                metadata=typed.metadata,
            )
        return self._wrap_typed(
            route=kind,
            request=request,
            binding=binding,
            typed=typed,
            parser_interface="TPTPFrontend@1",
            logic_family="first_order",
            source_format="tptp",
            approximated=("atp_candidate_until_reconstruction",)
            if typed.authority is ResultAuthority.CANDIDATE
            else (),
        )

    def run_secpal(
        self,
        document: AuthorizationIR | RuleDocument,
        *,
        query: DecisionQuery | Mapping[str, Any] | None = None,
        request_id: str = "req:classical-secpal:1",
        bounds: ExecutionBounds | None = None,
    ) -> ClassicalRouteResult:
        """Join typed SecPAL/rule source to the hermetic authorization evaluator."""

        request, binding, _ir, _q, unsupported = self.build_secpal_request(
            document,
            query=query,
            request_id=request_id,
            bounds=bounds,
        )
        if unsupported:
            # Explicit unsupported: do not promote authorization authority.
            return self._secpal_unsupported(
                request=request,
                binding=binding,
                unsupported=unsupported,
            )
        if not self.is_available(ClassicalRouteKind.SECPAL):
            return self._unavailable_result(
                route=ClassicalRouteKind.SECPAL,
                request=request,
                binding=binding,
                parser_interface="SecPALFrontend@1",
                logic_family="authorization",
                source_format="authorization-ir",
                reason="secpal backend is unavailable",
            )
        backend = self._backend_for(ClassicalRouteKind.SECPAL)
        assert backend is not None
        outcome = backend.run(request)
        if isinstance(outcome, AuthorizationBackendOutcome):
            typed: TypedBackendResult = outcome.result
        elif isinstance(outcome, AuthorizationResult):
            typed = outcome
        else:
            raise ClassicalAdapterError(
                f"unexpected SecPAL outcome type: {type(outcome)!r}",
                code=CODE_ROUTE,
            )
        if typed.authority is not ResultAuthority.AUTHORIZATION:
            raise AuthorityPromotionError(
                "SecPAL route must emit authorization authority only"
            )
        return self._wrap_typed(
            route=ClassicalRouteKind.SECPAL,
            request=request,
            binding=binding,
            typed=typed,
            parser_interface="SecPALFrontend@1",
            logic_family="authorization",
            source_format="authorization-ir",
        )

    def _secpal_unsupported(
        self,
        *,
        request: BackendRequest,
        binding: ClassicalSourceBinding,
        unsupported: Sequence[str],
    ) -> ClassicalRouteResult:
        receipt = ClassicalRouteReceipt(
            route=ClassicalRouteKind.SECPAL,
            exactness=RouteExactness.UNSUPPORTED,
            authority_ceiling=ResultAuthority.CANDIDATE,
            logic_family="authorization",
            source_format="authorization-ir",
            source_digest=binding.source_digest,
            request_digest=request.digest,
            parser_interface="SecPALFrontend@1",
            backend_id="secpal",
            availability=RouteAvailability.AVAILABLE,
            unsupported_constructs=tuple(unsupported),
            diagnostics=("unsupported constructs retained; authority not promoted",),
        )
        result = CandidateResult(
            result_id=f"result:secpal:unsupported:{request.digest[:12]}",
            backend_id="secpal",
            backend_version=CLASSICAL_BACKEND_ADAPTER_VERSION,
            authority=ResultAuthority.CANDIDATE,
            status=ResultStatus.UNSUPPORTED,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            reason="unsupported constructs prevent authorization authority",
            diagnostics=tuple(unsupported),
            witness=FrozenMap({"unsupported_constructs": list(unsupported)}),
        )
        return ClassicalRouteResult(
            route=ClassicalRouteKind.SECPAL,
            status=ResultStatus.UNSUPPORTED,
            authority=ResultAuthority.CANDIDATE,
            receipt=receipt,
            result=result,
            backend_request=request,
            source_binding=binding,
            reason=result.reason,
            diagnostics=tuple(unsupported),
        )

    def run_ergoai(
        self,
        document: FLogicDocument | ErgoAIControlledSource | str,
        *,
        request_id: str = "req:classical-ergoai:1",
    ) -> ClassicalRouteResult:
        """Join F-logic controlled source as ErgoAI advisor/candidate only."""

        typed, receipt, binding = self.build_ergoai_candidate(
            document, request_id=request_id
        )
        return ClassicalRouteResult(
            route=ClassicalRouteKind.ERGOAI,
            status=ResultStatus.CANDIDATE,
            authority=ResultAuthority.CANDIDATE,
            receipt=receipt,
            result=typed,
            backend_request=None,
            source_binding=binding,
            reason="ErgoAI advisor/candidate only; no live execution on join",
            diagnostics=receipt.diagnostics,
        )

    def run(
        self,
        route: ClassicalRouteKind | str,
        source: Any,
        *,
        query: DecisionQuery | Mapping[str, Any] | None = None,
        query_kind: QueryKind | str | None = None,
        request_id: str | None = None,
        bounds: ExecutionBounds | None = None,
    ) -> ClassicalRouteResult:
        """Dispatch a typed source to the named classical backend route."""

        kind = normalize_route_kind(route)
        rid = request_id or f"req:classical:{kind.value}:1"
        if kind in {ClassicalRouteKind.Z3, ClassicalRouteKind.CVC5}:
            return self.run_smt(
                source,
                route=kind,
                query_kind=query_kind or QueryKind.SATISFIABILITY,
                request_id=rid,
                bounds=bounds,
            )
        if kind in {ClassicalRouteKind.VAMPIRE, ClassicalRouteKind.E}:
            return self.run_atp(
                source,
                route=kind,
                query_kind=query_kind or QueryKind.THEOREM_PROOF,
                request_id=rid,
                bounds=bounds,
            )
        if kind is ClassicalRouteKind.SECPAL:
            return self.run_secpal(
                source, query=query, request_id=rid, bounds=bounds
            )
        if kind is ClassicalRouteKind.ERGOAI:
            return self.run_ergoai(source, request_id=rid)
        raise ClassicalAdapterError(
            f"unsupported route {route!r}",
            code=CODE_UNSUPPORTED_ROUTE,
        )


__all__ = [
    "CLASSICAL_ADAPTER_MODULE_VERSION",
    "CLASSICAL_BACKEND_ADAPTER_INTERFACE",
    "CLASSICAL_BACKEND_ADAPTER_VERSION",
    "CLASSICAL_ROUTE_RECEIPT_SCHEMA",
    "CLASSICAL_ROUTE_RESULT_SCHEMA",
    "CLASSICAL_SOURCE_BINDING_SCHEMA",
    "CODE_APPROXIMATE_ROUTE",
    "CODE_AUTHORITY_PROMOTION",
    "CODE_FREE_FORM_FAMILY",
    "CODE_MALFORMED",
    "CODE_NATURAL_LANGUAGE",
    "CODE_PARSE_REQUIRED",
    "CODE_ROUTE",
    "CODE_TYPED_SOURCE_REQUIRED",
    "CODE_UNAVAILABLE",
    "CODE_UNSUPPORTED_CONSTRUCT",
    "CODE_UNSUPPORTED_ROUTE",
    "AuthorityPromotionError",
    "ClassicalAdapterError",
    "ClassicalBackendAdapter",
    "ClassicalRouteKind",
    "ClassicalRouteReceipt",
    "ClassicalRouteResult",
    "ClassicalSourceBinding",
    "FreeFormFamilyError",
    "NaturalLanguageRejectedError",
    "RouteAvailability",
    "RouteExactness",
    "content_digest",
    "enforce_authority_ceiling",
    "is_exact_route",
    "normalize_route_kind",
    "project_rule_document_to_authorization_ir",
    "reject_free_form_family",
    "reject_natural_language_payload",
    "route_authority_ceiling",
    "route_exactness",
]
