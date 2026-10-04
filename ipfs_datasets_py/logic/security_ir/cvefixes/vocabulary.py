"""Versioned CVEfixes vocabulary for exact Security IR policy attributes.

The terms in this module describe security facts; they do not grant policy
authority.  In particular, CVE and CWE identifiers are classifications and
must never be treated as substitutes for exact action, scope, and
precondition/effect constraints.

Canonical terms have this shape::

    security.cvefixes/v1/action/construct_path_from_untrusted_input

Only registry-owned local names are accepted.  Wildcards, catch-all names,
unknown terms, and version drift fail closed.  Aliases are an ingestion
convenience only: scoped aliases retain and validate their exact scope before
they can resolve to a canonical term.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
import re
from typing import Any, Final


CVEFIXES_VOCABULARY: Final = "security.cvefixes"
CVEFIXES_VOCABULARY_NAMESPACE: Final = CVEFIXES_VOCABULARY
CVEFIXES_VOCABULARY_VERSION: Final = "v1"
CVEFIXES_VOCABULARY_SCHEMA_VERSION: Final = (
    f"{CVEFIXES_VOCABULARY}/{CVEFIXES_VOCABULARY_VERSION}"
)
CVEFIXES_SCHEMA_VERSION: Final = CVEFIXES_VOCABULARY_SCHEMA_VERSION
CVEFIXES_POLICY_ATTRIBUTES_KEY: Final = CVEFIXES_VOCABULARY


class CVEfixesVocabularyError(ValueError):
    """Raised when a CVEfixes term or policy-attribute payload is unsafe."""


class CVEfixesTermKind(str, Enum):
    """Closed term categories owned by the CVEfixes vocabulary."""

    ACTION = "action"
    PRECONDITION = "precondition"
    EFFECT = "effect"
    MITIGATION = "mitigation"
    LANGUAGE = "language"
    SCOPE = "scope"
    CVE = "cve"
    CWE = "cwe"


class CVEfixesPolicyRole(str, Enum):
    """How a term may participate in an exact Security IR policy match."""

    MATCH_CONSTRAINT = "match_constraint"
    CLASSIFICATION_ONLY = "classification_only"


# Descriptive aliases make the API easy to consume without weakening the
# single owning vocabulary.
VocabularyTermKind = CVEfixesTermKind
TermKind = CVEfixesTermKind


CVEFIXES_ACTIONS: Final = frozenset(
    {
        "access_memory_without_bounds_check",
        "allocate_unbounded_resource",
        "construct_path_from_untrusted_input",
        "deserialize_untrusted_data",
        "execute_command_from_untrusted_input",
        "follow_untrusted_redirect",
        "load_untrusted_code",
        "parse_untrusted_input",
        "perform_privileged_operation",
        "query_with_untrusted_input",
        "render_untrusted_output",
        "use_weak_cryptography",
        "write_sensitive_data",
    }
)
CVEFIXES_PRECONDITIONS: Final = frozenset(
    {
        "attacker_controls_command",
        "attacker_controls_path",
        "attacker_controls_query",
        "concurrent_access",
        "missing_authentication",
        "missing_authorization",
        "missing_bounds_check",
        "missing_canonicalization",
        "missing_input_validation",
        "missing_output_encoding",
        "privileged_context",
        "sensitive_data_present",
        "untrusted_input_reaches_sink",
    }
)
CVEFIXES_EFFECTS: Final = frozenset(
    {
        "arbitrary_code_execution",
        "authentication_bypass",
        "authorization_bypass",
        "command_execution",
        "cross_site_scripting",
        "data_disclosure",
        "data_modification",
        "denial_of_service",
        "memory_corruption",
        "privilege_escalation",
        "query_injection",
        "read_outside_allowed_root",
        "server_side_request_forgery",
        "write_outside_allowed_root",
    }
)
CVEFIXES_MITIGATIONS: Final = frozenset(
    {
        "apply_resource_limits",
        "bounds_check",
        "canonicalize_and_confine",
        "constrain_command_arguments",
        "encode_output",
        "enforce_authentication",
        "enforce_authorization",
        "parameterize_query",
        "restrict_network_destinations",
        "synchronize_shared_state",
        "use_memory_safe_api",
        "use_safe_cryptography",
        "use_safe_deserialization",
        "validate_input",
    }
)
CVEFIXES_LANGUAGES: Final = frozenset(
    {
        "c",
        "cpp",
        "csharp",
        "go",
        "java",
        "javascript",
        "kotlin",
        "objective_c",
        "php",
        "python",
        "ruby",
        "rust",
        "scala",
        "shell",
        "swift",
        "typescript",
    }
)
CVEFIXES_SCOPES: Final = frozenset(
    {
        "authentication",
        "authorization",
        "concurrency",
        "cryptography",
        "database",
        "filesystem",
        "logging",
        "memory",
        "network",
        "parser",
        "process",
        "resource",
        "serialization",
        "web",
    }
)

_FIXED_TERMS: Final = MappingProxyType(
    {
        CVEfixesTermKind.ACTION: CVEFIXES_ACTIONS,
        CVEfixesTermKind.PRECONDITION: CVEFIXES_PRECONDITIONS,
        CVEfixesTermKind.EFFECT: CVEFIXES_EFFECTS,
        CVEfixesTermKind.MITIGATION: CVEFIXES_MITIGATIONS,
        CVEfixesTermKind.LANGUAGE: CVEFIXES_LANGUAGES,
        CVEfixesTermKind.SCOPE: CVEFIXES_SCOPES,
    }
)
CVEFIXES_TERMS: Final = _FIXED_TERMS

_CVE_RE: Final = re.compile(r"CVE-(?:19|20)[0-9]{2}-[0-9]{4,}")
_CWE_RE: Final = re.compile(r"CWE-[1-9][0-9]*")
_LOCAL_NAME_RE: Final = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_WILDCARD_CHARS: Final = frozenset("*?[]{}")
_BROADENING_NAMES: Final = frozenset(
    {"all", "any", "everything", "global", "unrestricted", "unknown"}
)
_SCOPED_ALIAS_KINDS: Final = frozenset(
    {
        CVEfixesTermKind.ACTION,
        CVEfixesTermKind.PRECONDITION,
        CVEfixesTermKind.EFFECT,
        CVEfixesTermKind.MITIGATION,
    }
)


def _coerce_kind(value: CVEfixesTermKind | str) -> CVEfixesTermKind:
    if isinstance(value, CVEfixesTermKind):
        return value
    try:
        return CVEfixesTermKind(value)
    except (TypeError, ValueError) as exc:
        raise CVEfixesVocabularyError(
            f"unknown CVEfixes term kind: {value!r}"
        ) from exc


def _reject_broadening(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CVEfixesVocabularyError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise CVEfixesVocabularyError(f"{field_name} must be canonical")
    if any(character in value for character in _WILDCARD_CHARS):
        raise CVEfixesVocabularyError(
            f"{field_name} must not contain wildcard syntax"
        )
    if value.casefold() in _BROADENING_NAMES:
        raise CVEfixesVocabularyError(
            f"{field_name} must not use a catch-all value"
        )
    return value


def _validate_local_name(kind: CVEfixesTermKind, name: Any) -> str:
    name = _reject_broadening(name, f"{kind.value} term")
    if kind is CVEfixesTermKind.CVE:
        if _CVE_RE.fullmatch(name) is None:
            raise CVEfixesVocabularyError(
                f"invalid canonical CVE classification: {name!r}"
            )
        return name
    if kind is CVEfixesTermKind.CWE:
        if _CWE_RE.fullmatch(name) is None:
            raise CVEfixesVocabularyError(
                f"invalid canonical CWE classification: {name!r}"
            )
        return name
    if _LOCAL_NAME_RE.fullmatch(name) is None:
        raise CVEfixesVocabularyError(
            f"{kind.value} term must be canonical lower_snake_case"
        )
    if name not in _FIXED_TERMS[kind]:
        raise CVEfixesVocabularyError(
            f"unknown CVEfixes {kind.value} term: {name!r}"
        )
    return name


@dataclass(frozen=True, slots=True)
class CVEfixesTerm:
    """One typed, version-bound, canonical vocabulary term."""

    kind: CVEfixesTermKind
    name: str
    schema_version: str = CVEFIXES_VOCABULARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = _coerce_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        if self.schema_version != CVEFIXES_VOCABULARY_SCHEMA_VERSION:
            raise CVEfixesVocabularyError(
                "unsupported CVEfixes vocabulary schema version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(self, "name", _validate_local_name(kind, self.name))

    @property
    def canonical(self) -> str:
        """Return the stable namespaced spelling used in Security IR."""

        return (
            f"{self.schema_version}/{self.kind.value}/{self.name}"
        )

    @property
    def policy_role(self) -> CVEfixesPolicyRole:
        if self.kind in {CVEfixesTermKind.CVE, CVEfixesTermKind.CWE}:
            return CVEfixesPolicyRole.CLASSIFICATION_ONLY
        return CVEfixesPolicyRole.MATCH_CONSTRAINT

    @property
    def grants_policy_authority(self) -> bool:
        """Vocabulary facts never grant policy authority."""

        return False

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "schema_version": self.schema_version,
            "term": self.canonical,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CVEfixesTerm":
        if not isinstance(value, Mapping):
            raise CVEfixesVocabularyError("CVEfixes term must be a mapping")
        expected = {"kind", "name", "schema_version", "term"}
        if set(value) != expected:
            unknown = sorted(set(value) - expected)
            missing = sorted(expected - set(value))
            details = []
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            if missing:
                details.append("missing: " + ", ".join(missing))
            raise CVEfixesVocabularyError(
                "CVEfixes term fields are not canonical (" + "; ".join(details) + ")"
            )
        term = cls(
            kind=value["kind"],
            name=value["name"],
            schema_version=value["schema_version"],
        )
        if value["term"] != term.canonical:
            raise CVEfixesVocabularyError(
                "CVEfixes term does not match its typed components"
            )
        return term


def cvefixes_term(
    kind: CVEfixesTermKind | str,
    name: str,
) -> CVEfixesTerm:
    """Build a validated canonical term from an exact local name."""

    return CVEfixesTerm(_coerce_kind(kind), name)


def parse_cvefixes_term(
    value: str,
    *,
    expected_kind: CVEfixesTermKind | str | None = None,
) -> CVEfixesTerm:
    """Parse an exact canonical term without normalization or broadening."""

    value = _reject_broadening(value, "CVEfixes term")
    prefix = f"{CVEFIXES_VOCABULARY_SCHEMA_VERSION}/"
    if not value.startswith(prefix):
        if value.startswith(f"{CVEFIXES_VOCABULARY}/"):
            raise CVEfixesVocabularyError(
                "unsupported CVEfixes vocabulary version"
            )
        raise CVEfixesVocabularyError(
            f"term is outside {CVEFIXES_VOCABULARY_SCHEMA_VERSION!r}"
        )
    components = value[len(prefix) :].split("/")
    if len(components) != 2 or not all(components):
        raise CVEfixesVocabularyError("malformed canonical CVEfixes term")
    kind = _coerce_kind(components[0])
    if expected_kind is not None and kind is not _coerce_kind(expected_kind):
        raise CVEfixesVocabularyError(
            f"expected a {_coerce_kind(expected_kind).value} term, "
            f"received {kind.value}"
        )
    term = CVEfixesTerm(kind, components[1])
    if term.canonical != value:
        raise CVEfixesVocabularyError("CVEfixes term is not canonical")
    return term


canonical_term = cvefixes_term
parse_term = parse_cvefixes_term


@dataclass(frozen=True, slots=True)
class ScopedCVEfixesTerm:
    """A resolved term that retains the exact scope used for aliasing."""

    term: CVEfixesTerm
    scope: CVEfixesTerm | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.term, CVEfixesTerm):
            raise CVEfixesVocabularyError(
                "scoped term must contain a CVEfixesTerm"
            )
        if self.scope is not None and (
            not isinstance(self.scope, CVEfixesTerm)
            or self.scope.kind is not CVEfixesTermKind.SCOPE
        ):
            raise CVEfixesVocabularyError(
                "scoped term scope must be a CVEfixes scope term"
            )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "scope": self.scope.canonical if self.scope is not None else None,
            "term": self.term.canonical,
        }


@dataclass(frozen=True, slots=True)
class CVEfixesAlias:
    """An explicit lexical alias whose scoped identity cannot be discarded."""

    kind: CVEfixesTermKind
    alias: str
    canonical_name: str
    scope: str | None = None

    def __post_init__(self) -> None:
        kind = _coerce_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        alias = _reject_broadening(self.alias, "CVEfixes alias")
        if "/" in alias:
            raise CVEfixesVocabularyError(
                "CVEfixes aliases must be local names"
            )
        object.__setattr__(self, "alias", alias)
        _validate_local_name(kind, self.canonical_name)
        if kind in _SCOPED_ALIAS_KINDS:
            if self.scope is None:
                raise CVEfixesVocabularyError(
                    f"{kind.value} aliases require an exact scope"
                )
            _validate_local_name(CVEfixesTermKind.SCOPE, self.scope)
        elif self.scope is not None:
            raise CVEfixesVocabularyError(
                f"{kind.value} aliases must not declare a security scope"
            )

    @property
    def target(self) -> ScopedCVEfixesTerm:
        scope = (
            CVEfixesTerm(CVEfixesTermKind.SCOPE, self.scope)
            if self.scope is not None
            else None
        )
        return ScopedCVEfixesTerm(
            CVEfixesTerm(self.kind, self.canonical_name),
            scope,
        )


def validate_cvefixes_aliases(
    aliases: Iterable[CVEfixesAlias],
) -> tuple[CVEfixesAlias, ...]:
    """Validate aliases while preserving distinct scoped targets."""

    prepared: list[CVEfixesAlias] = []
    targets: dict[tuple[CVEfixesTermKind, str, str | None], str] = {}
    scopedness: dict[tuple[CVEfixesTermKind, str], bool] = {}
    for value in aliases:
        if not isinstance(value, CVEfixesAlias):
            raise CVEfixesVocabularyError(
                "CVEfixes aliases must be CVEfixesAlias instances"
            )
        key = (value.kind, value.alias, value.scope)
        previous = targets.get(key)
        if previous is not None:
            raise CVEfixesVocabularyError(
                f"duplicate CVEfixes alias target for {value.alias!r}"
            )
        targets[key] = value.canonical_name
        alias_key = (value.kind, value.alias)
        is_scoped = value.scope is not None
        if (
            alias_key in scopedness
            and scopedness[alias_key] is not is_scoped
        ):
            raise CVEfixesVocabularyError(
                f"alias {value.alias!r} cannot mix scoped and unscoped targets"
            )
        scopedness[alias_key] = is_scoped
        prepared.append(value)
    return tuple(
        sorted(
            prepared,
            key=lambda item: (
                item.kind.value,
                item.alias,
                item.scope or "",
                item.canonical_name,
            ),
        )
    )


CVEFIXES_ALIASES: Final = validate_cvefixes_aliases(
    (
        CVEfixesAlias(
            CVEfixesTermKind.ACTION,
            "build_tainted_path",
            "construct_path_from_untrusted_input",
            "filesystem",
        ),
        CVEfixesAlias(
            CVEfixesTermKind.ACTION,
            "run_tainted_command",
            "execute_command_from_untrusted_input",
            "process",
        ),
        CVEfixesAlias(
            CVEfixesTermKind.ACTION,
            "run_tainted_query",
            "query_with_untrusted_input",
            "database",
        ),
        CVEfixesAlias(CVEfixesTermKind.LANGUAGE, "c++", "cpp"),
        CVEfixesAlias(CVEfixesTermKind.LANGUAGE, "c#", "csharp"),
        CVEfixesAlias(CVEfixesTermKind.LANGUAGE, "js", "javascript"),
        CVEfixesAlias(CVEfixesTermKind.LANGUAGE, "ts", "typescript"),
    )
)

_ALIASES_BY_NAME: Final = MappingProxyType(
    {
        (item.kind, item.alias, item.scope): item
        for item in CVEFIXES_ALIASES
    }
)


def _coerce_scope_name(value: str | CVEfixesTerm | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, CVEfixesTerm):
        if value.kind is not CVEfixesTermKind.SCOPE:
            raise CVEfixesVocabularyError("alias scope must be a scope term")
        return value.name
    if not isinstance(value, str):
        raise CVEfixesVocabularyError(
            "alias scope must be a scope term or canonical string"
        )
    if value.startswith(f"{CVEFIXES_VOCABULARY_SCHEMA_VERSION}/"):
        return parse_cvefixes_term(
            value, expected_kind=CVEfixesTermKind.SCOPE
        ).name
    return _validate_local_name(CVEfixesTermKind.SCOPE, value)


def resolve_cvefixes_term(
    kind: CVEfixesTermKind | str,
    value: str,
    *,
    scope: str | CVEfixesTerm | None = None,
) -> ScopedCVEfixesTerm:
    """Resolve a canonical name or declared alias and retain exact scope."""

    kind = _coerce_kind(kind)
    value = _reject_broadening(value, f"{kind.value} term or alias")
    scope_name = _coerce_scope_name(scope)
    if value.startswith(f"{CVEFIXES_VOCABULARY_SCHEMA_VERSION}/"):
        term = parse_cvefixes_term(value, expected_kind=kind)
    else:
        try:
            term = CVEfixesTerm(kind, value)
        except CVEfixesVocabularyError as term_error:
            alias = _ALIASES_BY_NAME.get((kind, value, scope_name))
            if alias is None:
                candidates = [
                    item
                    for item in CVEFIXES_ALIASES
                    if item.kind is kind and item.alias == value
                ]
                if candidates and scope_name is None:
                    raise CVEfixesVocabularyError(
                        f"alias {value!r} requires an exact scope"
                    ) from term_error
                if candidates:
                    raise CVEfixesVocabularyError(
                        f"alias {value!r} is not valid in scope {scope_name!r}"
                    ) from term_error
                raise
            term = alias.target.term
    scope_term = (
        CVEfixesTerm(CVEfixesTermKind.SCOPE, scope_name)
        if scope_name is not None
        else None
    )
    return ScopedCVEfixesTerm(term, scope_term)


resolve_term = resolve_cvefixes_term


def cve_classification(cve_id: str) -> CVEfixesTerm:
    """Return a typed CVE classification (never an authority grant)."""

    return CVEfixesTerm(CVEfixesTermKind.CVE, cve_id)


def cwe_classification(cwe_id: str) -> CVEfixesTerm:
    """Return a typed CWE classification (never an authority grant)."""

    return CVEfixesTerm(CVEfixesTermKind.CWE, cwe_id)


def _coerce_exact_term(
    value: CVEfixesTerm | str | None,
    kind: CVEfixesTermKind,
    *,
    allow_none: bool = False,
) -> CVEfixesTerm | None:
    if value is None:
        if allow_none:
            return None
        raise CVEfixesVocabularyError(f"{kind.value} term is required")
    term = (
        value
        if isinstance(value, CVEfixesTerm)
        else parse_cvefixes_term(value, expected_kind=kind)
    )
    if term.kind is not kind:
        raise CVEfixesVocabularyError(
            f"expected a {kind.value} term, received {term.kind.value}"
        )
    return term


def _coerce_term_set(
    values: Sequence[CVEfixesTerm | str],
    kind: CVEfixesTermKind,
) -> tuple[CVEfixesTerm, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise CVEfixesVocabularyError(
            f"{kind.value} terms must be a sequence"
        )
    terms = tuple(_coerce_exact_term(value, kind) for value in values)
    canonical = [term.canonical for term in terms if term is not None]
    if len(canonical) != len(set(canonical)):
        raise CVEfixesVocabularyError(
            f"{kind.value} terms must be unique"
        )
    return tuple(
        sorted(
            (term for term in terms if term is not None),
            key=lambda item: item.canonical,
        )
    )


def _coerce_classifications(
    values: Sequence[CVEfixesTerm | str],
    kind: CVEfixesTermKind,
) -> tuple[CVEfixesTerm, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise CVEfixesVocabularyError(
            f"{kind.value} classifications must be a sequence"
        )
    terms: list[CVEfixesTerm] = []
    for value in values:
        if isinstance(value, CVEfixesTerm):
            term = _coerce_exact_term(value, kind)
        elif isinstance(value, str) and value.startswith(
            f"{CVEFIXES_VOCABULARY_SCHEMA_VERSION}/"
        ):
            term = parse_cvefixes_term(value, expected_kind=kind)
        else:
            term = CVEfixesTerm(kind, value)
        assert term is not None
        terms.append(term)
    canonical = [term.canonical for term in terms]
    if len(canonical) != len(set(canonical)):
        raise CVEfixesVocabularyError(
            f"{kind.value} classifications must be unique"
        )
    return tuple(sorted(terms, key=lambda item: item.canonical))


@dataclass(frozen=True, slots=True)
class CVEfixesPolicyAttributes:
    """Canonical CVEfixes payload stored under Security IR ``attributes``.

    A payload can be classification-only for projection and retrieval.  Such
    a payload is deliberately not an exact policy match.  Even a fully
    constrained payload remains descriptive and requires a separately
    reviewed Security IR ``Policy`` to carry authority.
    """

    action: CVEfixesTerm | str | None = None
    preconditions: tuple[CVEfixesTerm | str, ...] = ()
    effects: tuple[CVEfixesTerm | str, ...] = ()
    mitigations: tuple[CVEfixesTerm | str, ...] = ()
    language: CVEfixesTerm | str | None = None
    scope: CVEfixesTerm | str | None = None
    cve_ids: tuple[CVEfixesTerm | str, ...] = ()
    cwe_ids: tuple[CVEfixesTerm | str, ...] = ()
    schema_version: str = CVEFIXES_VOCABULARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CVEFIXES_VOCABULARY_SCHEMA_VERSION:
            raise CVEfixesVocabularyError(
                "unsupported CVEfixes policy attribute schema version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "action",
            _coerce_exact_term(
                self.action, CVEfixesTermKind.ACTION, allow_none=True
            ),
        )
        for field_name, kind in (
            ("preconditions", CVEfixesTermKind.PRECONDITION),
            ("effects", CVEfixesTermKind.EFFECT),
            ("mitigations", CVEfixesTermKind.MITIGATION),
        ):
            object.__setattr__(
                self,
                field_name,
                _coerce_term_set(getattr(self, field_name), kind),
            )
        object.__setattr__(
            self,
            "language",
            _coerce_exact_term(
                self.language, CVEfixesTermKind.LANGUAGE, allow_none=True
            ),
        )
        object.__setattr__(
            self,
            "scope",
            _coerce_exact_term(
                self.scope, CVEfixesTermKind.SCOPE, allow_none=True
            ),
        )
        object.__setattr__(
            self,
            "cve_ids",
            _coerce_classifications(self.cve_ids, CVEfixesTermKind.CVE),
        )
        object.__setattr__(
            self,
            "cwe_ids",
            _coerce_classifications(self.cwe_ids, CVEfixesTermKind.CWE),
        )

    @property
    def classification_only(self) -> bool:
        return not any(
            (
                self.action is not None,
                self.preconditions,
                self.effects,
                self.mitigations,
                self.language is not None,
                self.scope is not None,
            )
        )

    @property
    def has_exact_policy_constraints(self) -> bool:
        """Whether exact non-classification match constraints are present."""

        return (
            self.action is not None
            and self.scope is not None
            and bool(self.preconditions or self.effects)
        )

    @property
    def grants_policy_authority(self) -> bool:
        """Attributes are facts; authority belongs to reviewed Security IR."""

        return False

    @property
    def policy_match_terms(self) -> tuple[CVEfixesTerm, ...]:
        """Return exact match terms, excluding CVE/CWE classifications."""

        terms = [
            *(self.preconditions),
            *(self.effects),
            *(self.mitigations),
        ]
        if self.action is not None:
            terms.append(self.action)
        if self.language is not None:
            terms.append(self.language)
        if self.scope is not None:
            terms.append(self.scope)
        return tuple(sorted(terms, key=lambda item: item.canonical))

    def require_exact_policy_constraints(self) -> "CVEfixesPolicyAttributes":
        if not self.has_exact_policy_constraints:
            raise CVEfixesVocabularyError(
                "CVE/CWE classifications are not sufficient policy authority; "
                "an exact action, scope, and precondition or effect are required"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.canonical if self.action is not None else None,
            "cve_ids": [term.canonical for term in self.cve_ids],
            "cwe_ids": [term.canonical for term in self.cwe_ids],
            "effects": [term.canonical for term in self.effects],
            "language": (
                self.language.canonical if self.language is not None else None
            ),
            "mitigations": [term.canonical for term in self.mitigations],
            "preconditions": [
                term.canonical for term in self.preconditions
            ],
            "schema_version": self.schema_version,
            "scope": self.scope.canonical if self.scope is not None else None,
        }

    def to_security_ir_attributes(self) -> dict[str, Any]:
        """Return a JSON-ready mapping suitable for ``Policy.attributes``."""

        return {CVEFIXES_POLICY_ATTRIBUTES_KEY: self.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CVEfixesPolicyAttributes":
        if not isinstance(value, Mapping):
            raise CVEfixesVocabularyError(
                "CVEfixes policy attributes must be a mapping"
            )
        expected = {
            "action",
            "cve_ids",
            "cwe_ids",
            "effects",
            "language",
            "mitigations",
            "preconditions",
            "schema_version",
            "scope",
        }
        if set(value) != expected:
            unknown = sorted(set(value) - expected)
            missing = sorted(expected - set(value))
            details = []
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            if missing:
                details.append("missing: " + ", ".join(missing))
            raise CVEfixesVocabularyError(
                "CVEfixes policy attribute fields are not canonical ("
                + "; ".join(details)
                + ")"
            )
        return cls(
            action=value["action"],
            preconditions=value["preconditions"],
            effects=value["effects"],
            mitigations=value["mitigations"],
            language=value["language"],
            scope=value["scope"],
            cve_ids=value["cve_ids"],
            cwe_ids=value["cwe_ids"],
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_security_ir_attributes(
        cls, attributes: Mapping[str, Any]
    ) -> "CVEfixesPolicyAttributes":
        if not isinstance(attributes, Mapping):
            raise CVEfixesVocabularyError(
                "Security IR policy attributes must be a mapping"
            )
        if CVEFIXES_POLICY_ATTRIBUTES_KEY not in attributes:
            raise CVEfixesVocabularyError(
                f"missing {CVEFIXES_POLICY_ATTRIBUTES_KEY!r} policy attributes"
            )
        return cls.from_dict(attributes[CVEFIXES_POLICY_ATTRIBUTES_KEY])


def validate_cvefixes_policy_attributes(
    attributes: Mapping[str, Any],
    *,
    require_exact_policy_constraints: bool = False,
) -> CVEfixesPolicyAttributes:
    """Parse canonical Security IR attributes and optionally require exactness."""

    result = CVEfixesPolicyAttributes.from_security_ir_attributes(attributes)
    if require_exact_policy_constraints:
        result.require_exact_policy_constraints()
    return result


validate_policy_attributes = validate_cvefixes_policy_attributes


__all__ = [
    "CVEFIXES_ACTIONS",
    "CVEFIXES_ALIASES",
    "CVEFIXES_EFFECTS",
    "CVEFIXES_LANGUAGES",
    "CVEFIXES_MITIGATIONS",
    "CVEFIXES_POLICY_ATTRIBUTES_KEY",
    "CVEFIXES_PRECONDITIONS",
    "CVEFIXES_SCHEMA_VERSION",
    "CVEFIXES_SCOPES",
    "CVEFIXES_TERMS",
    "CVEFIXES_VOCABULARY",
    "CVEFIXES_VOCABULARY_NAMESPACE",
    "CVEFIXES_VOCABULARY_SCHEMA_VERSION",
    "CVEFIXES_VOCABULARY_VERSION",
    "CVEfixesAlias",
    "CVEfixesPolicyAttributes",
    "CVEfixesPolicyRole",
    "CVEfixesTerm",
    "CVEfixesTermKind",
    "CVEfixesVocabularyError",
    "ScopedCVEfixesTerm",
    "TermKind",
    "VocabularyTermKind",
    "canonical_term",
    "cve_classification",
    "cvefixes_term",
    "cwe_classification",
    "parse_cvefixes_term",
    "parse_term",
    "resolve_cvefixes_term",
    "resolve_term",
    "validate_cvefixes_aliases",
    "validate_cvefixes_policy_attributes",
    "validate_policy_attributes",
]
