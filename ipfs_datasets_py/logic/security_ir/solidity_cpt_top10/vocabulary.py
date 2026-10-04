"""Versioned Solidity CPT vocabulary for typed Security IR graph terms.

The terms in this module describe security *facts* and ontology labels.  They
never grant policy, proof, execution, or transaction authority.  Corpus quality
scores are deliberately excluded from the security-concept vocabulary so that
top-decile ranking cannot become a safety label.

Four non-interchangeable authority types are first-class terms:

* ``observed_syntax`` — deterministic parser / structural observations
* ``inferred_candidate`` — heuristic or model-assisted candidates
* ``reviewed_claim`` — human-reviewed but non-proof claims
* ``verified_result`` — prover / evaluation results bound to exact evidence

Canonical terms have this shape::

    security.solidity-cpt/v1/authority_type/observed_syntax
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
from typing import Any, Final


SOLIDITY_VOCABULARY: Final = "security.solidity-cpt"
SOLIDITY_VOCABULARY_NAMESPACE: Final = SOLIDITY_VOCABULARY
SOLIDITY_VOCABULARY_VERSION: Final = "v1"
SOLIDITY_VOCABULARY_SCHEMA_VERSION: Final = (
    f"{SOLIDITY_VOCABULARY}/{SOLIDITY_VOCABULARY_VERSION}"
)
SOLIDITY_SCHEMA_VERSION: Final = SOLIDITY_VOCABULARY_SCHEMA_VERSION
SOLIDITY_POLICY_ATTRIBUTES_KEY: Final = SOLIDITY_VOCABULARY


class SolidityVocabularyError(ValueError):
    """Raised when a Solidity CPT term or attribute payload is unsafe."""


class SolidityTermKind(str, Enum):
    """Closed term categories owned by the Solidity CPT vocabulary."""

    ACTION = "action"
    PRECONDITION = "precondition"
    EFFECT = "effect"
    MITIGATION = "mitigation"
    SECURITY_CONCEPT = "security_concept"
    ASSUMPTION = "assumption"
    LANGUAGE = "language"
    SCOPE = "scope"
    AUTHORITY_TYPE = "authority_type"
    NODE_TYPE = "node_type"
    EDGE_TYPE = "edge_type"


class SolidityPolicyRole(str, Enum):
    """How a term may participate in an exact Security IR policy match."""

    MATCH_CONSTRAINT = "match_constraint"
    CLASSIFICATION_ONLY = "classification_only"
    AUTHORITY_LATTICE = "authority_lattice"
    ONTOLOGY_ONLY = "ontology_only"


class SolidityAuthorityType(str, Enum):
    """Non-interchangeable evidence / authority classes for graph nodes.

    These are *not* interchangeable with derived-record ``authority`` fields
    (``candidate`` / ``non_authoritative``).  They classify the kind of claim
    a node represents.
    """

    OBSERVED_SYNTAX = "observed_syntax"
    INFERRED_CANDIDATE = "inferred_candidate"
    REVIEWED_CLAIM = "reviewed_claim"
    VERIFIED_RESULT = "verified_result"


# Descriptive aliases for the public API surface.
VocabularyTermKind = SolidityTermKind
TermKind = SolidityTermKind
AuthorityType = SolidityAuthorityType


SOLIDITY_ACTIONS: Final = frozenset(
    {
        "call_external_untrusted",
        "delegatecall_untrusted",
        "selfdestruct_contract",
        "transfer_value",
        "write_storage",
        "read_storage",
        "emit_event",
        "create_contract",
        "use_inline_assembly",
        "use_tx_origin",
        "use_block_timestamp",
        "approve_unlimited_allowance",
    }
)
SOLIDITY_PRECONDITIONS: Final = frozenset(
    {
        "missing_access_control",
        "missing_reentrancy_guard",
        "missing_input_validation",
        "unchecked_external_call",
        "privileged_context",
        "state_updated_after_call",
        "uninitialized_storage",
        "floating_pragma",
        "tx_origin_authentication",
    }
)
SOLIDITY_EFFECTS: Final = frozenset(
    {
        "unauthorized_value_transfer",
        "reentrancy",
        "privilege_escalation",
        "storage_corruption",
        "denial_of_service",
        "front_running",
        "oracle_manipulation",
        "signature_replay",
        "arbitrary_code_execution",
    }
)
SOLIDITY_MITIGATIONS: Final = frozenset(
    {
        "enforce_access_control",
        "apply_reentrancy_guard",
        "checks_effects_interactions",
        "validate_input",
        "use_pull_payment",
        "use_safe_math",
        "pin_compiler_version",
        "use_multisig_admin",
        "limit_approval_amount",
    }
)
SOLIDITY_SECURITY_CONCEPTS: Final = frozenset(
    {
        "access_control",
        "reentrancy",
        "integer_overflow",
        "unchecked_call",
        "delegatecall_injection",
        "tx_origin",
        "timestamp_dependence",
        "front_running",
        "oracle_dependency",
        "upgradeability",
        "initialization",
        "signature_malleability",
        "flash_loan",
        "governance",
    }
)
SOLIDITY_ASSUMPTIONS: Final = frozenset(
    {
        "compiler_trustworthy",
        "evm_semantics_as_modeled",
        "admin_keys_not_compromised",
        "oracle_feeds_honest_within_bounds",
        "external_callees_non_reentrant",
        "cryptographic_primitives_unbroken",
    }
)
SOLIDITY_LANGUAGES: Final = frozenset({"solidity", "yul"})
SOLIDITY_SCOPES: Final = frozenset(
    {
        "access_control",
        "value_transfer",
        "storage",
        "external_call",
        "upgrade",
        "initialization",
        "oracle",
        "governance",
        "cryptography",
        "assembly",
        "compiler",
        "license",
        "provenance",
    }
)
SOLIDITY_AUTHORITY_TYPES: Final = frozenset(
    item.value for item in SolidityAuthorityType
)
SOLIDITY_NODE_TYPES: Final = frozenset(
    {
        "source",
        "source_unit",
        "repository",
        "license",
        "compiler",
        "address_hint",
        "contract",
        "library",
        "interface",
        "function",
        "modifier",
        "variable",
        "event",
        "error",
        "call_site",
        "state_access",
        "effect_summary",
        "security_concept",
        "candidate_claim",
        "assumption",
        "mitigation",
        "proof_obligation",
        "formal_view",
        "producer_config",
        "observed_syntax",
        "inferred_candidate",
        "reviewed_claim",
        "verified_result",
        "quality_score",
    }
)
SOLIDITY_EDGE_TYPES: Final = frozenset(
    {
        "contains",
        "declares",
        "inherits",
        "imports",
        "calls",
        "reads",
        "writes",
        "emits",
        "guards",
        "may_effect",
        "derived_from",
        "grounded_in",
        "has_license",
        "has_compiler",
        "candidate_for",
        "similar_to",
        "structurally_similar",
        "semantically_similar",
    }
)

_FIXED_TERMS: Final = MappingProxyType(
    {
        SolidityTermKind.ACTION: SOLIDITY_ACTIONS,
        SolidityTermKind.PRECONDITION: SOLIDITY_PRECONDITIONS,
        SolidityTermKind.EFFECT: SOLIDITY_EFFECTS,
        SolidityTermKind.MITIGATION: SOLIDITY_MITIGATIONS,
        SolidityTermKind.SECURITY_CONCEPT: SOLIDITY_SECURITY_CONCEPTS,
        SolidityTermKind.ASSUMPTION: SOLIDITY_ASSUMPTIONS,
        SolidityTermKind.LANGUAGE: SOLIDITY_LANGUAGES,
        SolidityTermKind.SCOPE: SOLIDITY_SCOPES,
        SolidityTermKind.AUTHORITY_TYPE: SOLIDITY_AUTHORITY_TYPES,
        SolidityTermKind.NODE_TYPE: SOLIDITY_NODE_TYPES,
        SolidityTermKind.EDGE_TYPE: SOLIDITY_EDGE_TYPES,
    }
)
SOLIDITY_TERMS: Final = _FIXED_TERMS

_LOCAL_NAME_RE: Final = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_WILDCARD_CHARS: Final = frozenset("*?[]{}")
_BROADENING_NAMES: Final = frozenset(
    {"all", "any", "everything", "global", "unrestricted", "unknown"}
)
# Quality / ranking tokens that must never resolve as security concepts.
_QUALITY_AS_SECURITY_FORBIDDEN: Final = frozenset(
    {
        "top10",
        "top_10",
        "top_decile",
        "quality",
        "quality_score",
        "safe",
        "secure",
        "audited",
        "owasp_top10",
    }
)


def _coerce_kind(value: SolidityTermKind | str) -> SolidityTermKind:
    if isinstance(value, SolidityTermKind):
        return value
    try:
        return SolidityTermKind(value)
    except (TypeError, ValueError) as exc:
        raise SolidityVocabularyError(
            f"unknown Solidity CPT term kind: {value!r}"
        ) from exc


def _reject_broadening(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SolidityVocabularyError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise SolidityVocabularyError(f"{field_name} must be canonical")
    if any(character in value for character in _WILDCARD_CHARS):
        raise SolidityVocabularyError(
            f"{field_name} must not contain wildcard syntax"
        )
    if value.casefold() in _BROADENING_NAMES:
        raise SolidityVocabularyError(
            f"{field_name} must not use a catch-all value"
        )
    return value


def _validate_local_name(kind: SolidityTermKind, name: Any) -> str:
    name = _reject_broadening(name, f"{kind.value} term")
    if _LOCAL_NAME_RE.fullmatch(name) is None:
        raise SolidityVocabularyError(
            f"{kind.value} term must be canonical lower_snake_case"
        )
    if (
        kind is SolidityTermKind.SECURITY_CONCEPT
        and name in _QUALITY_AS_SECURITY_FORBIDDEN
    ):
        raise SolidityVocabularyError(
            "corpus quality ranking is not a security concept or safety label"
        )
    if name not in _FIXED_TERMS[kind]:
        raise SolidityVocabularyError(
            f"unknown Solidity CPT {kind.value} term: {name!r}"
        )
    return name


@dataclass(frozen=True, slots=True)
class SolidityTerm:
    """One typed, version-bound, canonical vocabulary term."""

    kind: SolidityTermKind
    name: str
    schema_version: str = SOLIDITY_VOCABULARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = _coerce_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        if self.schema_version != SOLIDITY_VOCABULARY_SCHEMA_VERSION:
            raise SolidityVocabularyError(
                "unsupported Solidity CPT vocabulary schema version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(self, "name", _validate_local_name(kind, self.name))

    @property
    def canonical(self) -> str:
        return f"{self.schema_version}/{self.kind.value}/{self.name}"

    @property
    def policy_role(self) -> SolidityPolicyRole:
        if self.kind is SolidityTermKind.AUTHORITY_TYPE:
            return SolidityPolicyRole.AUTHORITY_LATTICE
        if self.kind in {
            SolidityTermKind.NODE_TYPE,
            SolidityTermKind.EDGE_TYPE,
        }:
            return SolidityPolicyRole.ONTOLOGY_ONLY
        if self.kind is SolidityTermKind.LANGUAGE:
            return SolidityPolicyRole.CLASSIFICATION_ONLY
        return SolidityPolicyRole.MATCH_CONSTRAINT

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
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityTerm":
        if not isinstance(value, Mapping):
            raise SolidityVocabularyError("Solidity CPT term must be a mapping")
        expected = {"kind", "name", "schema_version", "term"}
        if set(value) != expected:
            unknown = sorted(set(value) - expected)
            missing = sorted(expected - set(value))
            details = []
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            if missing:
                details.append("missing: " + ", ".join(missing))
            raise SolidityVocabularyError(
                "Solidity CPT term fields are not canonical ("
                + "; ".join(details)
                + ")"
            )
        term = cls(
            kind=value["kind"],
            name=value["name"],
            schema_version=value["schema_version"],
        )
        if value["term"] != term.canonical:
            raise SolidityVocabularyError(
                "Solidity CPT term does not match its typed components"
            )
        return term


def solidity_term(
    kind: SolidityTermKind | str,
    name: str,
) -> SolidityTerm:
    """Build a validated canonical term from an exact local name."""

    return SolidityTerm(_coerce_kind(kind), name)


def parse_solidity_term(
    value: str,
    *,
    expected_kind: SolidityTermKind | str | None = None,
) -> SolidityTerm:
    """Parse an exact canonical term without normalization or broadening."""

    value = _reject_broadening(value, "Solidity CPT term")
    prefix = f"{SOLIDITY_VOCABULARY_SCHEMA_VERSION}/"
    if not value.startswith(prefix):
        if value.startswith(f"{SOLIDITY_VOCABULARY}/"):
            raise SolidityVocabularyError(
                "unsupported Solidity CPT vocabulary version"
            )
        raise SolidityVocabularyError(
            f"term is outside {SOLIDITY_VOCABULARY_SCHEMA_VERSION!r}"
        )
    components = value[len(prefix) :].split("/")
    if len(components) != 2 or not all(components):
        raise SolidityVocabularyError("malformed canonical Solidity CPT term")
    kind = _coerce_kind(components[0])
    if expected_kind is not None and kind is not _coerce_kind(expected_kind):
        raise SolidityVocabularyError(
            f"expected a {_coerce_kind(expected_kind).value} term, "
            f"received {kind.value}"
        )
    term = SolidityTerm(kind, components[1])
    if term.canonical != value:
        raise SolidityVocabularyError("Solidity CPT term is not canonical")
    return term


canonical_term = solidity_term
parse_term = parse_solidity_term


def authority_type_term(
    value: SolidityAuthorityType | str,
) -> SolidityTerm:
    """Return the canonical term for one of the four authority types."""

    if isinstance(value, SolidityAuthorityType):
        name = value.value
    else:
        name = value
    return SolidityTerm(SolidityTermKind.AUTHORITY_TYPE, name)


def require_authority_type(
    value: SolidityAuthorityType | str | SolidityTerm,
) -> SolidityAuthorityType:
    """Coerce and validate a first-class authority type."""

    if isinstance(value, SolidityAuthorityType):
        return value
    if isinstance(value, SolidityTerm):
        if value.kind is not SolidityTermKind.AUTHORITY_TYPE:
            raise SolidityVocabularyError(
                "expected an authority_type term, "
                f"received {value.kind.value}"
            )
        return SolidityAuthorityType(value.name)
    if isinstance(value, str) and value.startswith(
        f"{SOLIDITY_VOCABULARY_SCHEMA_VERSION}/"
    ):
        term = parse_solidity_term(
            value, expected_kind=SolidityTermKind.AUTHORITY_TYPE
        )
        return SolidityAuthorityType(term.name)
    try:
        return SolidityAuthorityType(value)
    except (TypeError, ValueError) as exc:
        raise SolidityVocabularyError(
            f"unknown authority type: {value!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class SolidityAlias:
    """An explicit lexical alias whose identity cannot be discarded."""

    kind: SolidityTermKind
    alias: str
    canonical_name: str

    def __post_init__(self) -> None:
        kind = _coerce_kind(self.kind)
        object.__setattr__(self, "kind", kind)
        alias = _reject_broadening(self.alias, "Solidity CPT alias")
        if "/" in alias:
            raise SolidityVocabularyError(
                "Solidity CPT aliases must be local names"
            )
        object.__setattr__(self, "alias", alias)
        _validate_local_name(kind, self.canonical_name)

    @property
    def target(self) -> SolidityTerm:
        return SolidityTerm(self.kind, self.canonical_name)


def validate_solidity_aliases(
    aliases: Iterable[SolidityAlias],
) -> tuple[SolidityAlias, ...]:
    """Validate aliases while preserving distinct targets."""

    prepared: list[SolidityAlias] = []
    targets: dict[tuple[SolidityTermKind, str], str] = {}
    for value in aliases:
        if not isinstance(value, SolidityAlias):
            raise SolidityVocabularyError(
                "aliases must be SolidityAlias instances"
            )
        key = (value.kind, value.alias)
        previous = targets.get(key)
        if previous is not None and previous != value.canonical_name:
            raise SolidityVocabularyError(
                f"duplicate Solidity CPT alias for {value.alias!r}"
            )
        targets[key] = value.canonical_name
        prepared.append(value)
    return tuple(
        sorted(
            prepared,
            key=lambda item: (
                item.kind.value,
                item.alias,
                item.canonical_name,
            ),
        )
    )


SOLIDITY_ALIASES: Final = validate_solidity_aliases(
    (
        SolidityAlias(SolidityTermKind.LANGUAGE, "sol", "solidity"),
        SolidityAlias(
            SolidityTermKind.SECURITY_CONCEPT, "reentry", "reentrancy"
        ),
        SolidityAlias(
            SolidityTermKind.ACTION, "call_untrusted", "call_external_untrusted"
        ),
        SolidityAlias(
            SolidityTermKind.MITIGATION,
            "cei",
            "checks_effects_interactions",
        ),
    )
)

_ALIASES_BY_NAME: Final = MappingProxyType(
    {(item.kind, item.alias): item for item in SOLIDITY_ALIASES}
)


def resolve_solidity_term(
    kind: SolidityTermKind | str,
    value: str,
) -> SolidityTerm:
    """Resolve a canonical name or declared alias."""

    kind = _coerce_kind(kind)
    value = _reject_broadening(value, f"{kind.value} term or alias")
    if value.startswith(f"{SOLIDITY_VOCABULARY_SCHEMA_VERSION}/"):
        return parse_solidity_term(value, expected_kind=kind)
    try:
        return SolidityTerm(kind, value)
    except SolidityVocabularyError as term_error:
        alias = _ALIASES_BY_NAME.get((kind, value))
        if alias is None:
            raise
        return alias.target


resolve_term = resolve_solidity_term


def _coerce_exact_term(
    value: SolidityTerm | str | None,
    kind: SolidityTermKind,
    *,
    allow_none: bool = False,
) -> SolidityTerm | None:
    if value is None:
        if allow_none:
            return None
        raise SolidityVocabularyError(f"{kind.value} term is required")
    term = (
        value
        if isinstance(value, SolidityTerm)
        else parse_solidity_term(value, expected_kind=kind)
        if isinstance(value, str)
        and value.startswith(f"{SOLIDITY_VOCABULARY_SCHEMA_VERSION}/")
        else SolidityTerm(kind, value)  # type: ignore[arg-type]
    )
    if term.kind is not kind:
        raise SolidityVocabularyError(
            f"expected a {kind.value} term, received {term.kind.value}"
        )
    return term


def _coerce_term_set(
    values: Sequence[SolidityTerm | str],
    kind: SolidityTermKind,
) -> tuple[SolidityTerm, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise SolidityVocabularyError(f"{kind.value} terms must be a sequence")
    terms = tuple(_coerce_exact_term(value, kind) for value in values)
    canonical = [term.canonical for term in terms if term is not None]
    if len(canonical) != len(set(canonical)):
        raise SolidityVocabularyError(f"{kind.value} terms must be unique")
    return tuple(
        sorted(
            (term for term in terms if term is not None),
            key=lambda item: item.canonical,
        )
    )


@dataclass(frozen=True, slots=True)
class SolidityPolicyAttributes:
    """Canonical Solidity CPT payload for Security IR ``attributes``.

    Attributes are descriptive.  They require a separately reviewed Security IR
    ``Policy`` to carry authority.  Quality scores must not appear here as
    security labels.
    """

    action: SolidityTerm | str | None = None
    preconditions: tuple[SolidityTerm | str, ...] = ()
    effects: tuple[SolidityTerm | str, ...] = ()
    mitigations: tuple[SolidityTerm | str, ...] = ()
    security_concepts: tuple[SolidityTerm | str, ...] = ()
    assumptions: tuple[SolidityTerm | str, ...] = ()
    language: SolidityTerm | str | None = None
    scope: SolidityTerm | str | None = None
    authority_type: SolidityTerm | str | None = None
    schema_version: str = SOLIDITY_VOCABULARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SOLIDITY_VOCABULARY_SCHEMA_VERSION:
            raise SolidityVocabularyError(
                "unsupported Solidity CPT policy attribute schema version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(
            self,
            "action",
            _coerce_exact_term(
                self.action, SolidityTermKind.ACTION, allow_none=True
            ),
        )
        for field_name, kind in (
            ("preconditions", SolidityTermKind.PRECONDITION),
            ("effects", SolidityTermKind.EFFECT),
            ("mitigations", SolidityTermKind.MITIGATION),
            ("security_concepts", SolidityTermKind.SECURITY_CONCEPT),
            ("assumptions", SolidityTermKind.ASSUMPTION),
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
                self.language, SolidityTermKind.LANGUAGE, allow_none=True
            ),
        )
        object.__setattr__(
            self,
            "scope",
            _coerce_exact_term(
                self.scope, SolidityTermKind.SCOPE, allow_none=True
            ),
        )
        object.__setattr__(
            self,
            "authority_type",
            _coerce_exact_term(
                self.authority_type,
                SolidityTermKind.AUTHORITY_TYPE,
                allow_none=True,
            ),
        )

    @property
    def classification_only(self) -> bool:
        return not any(
            (
                self.action is not None,
                self.preconditions,
                self.effects,
                self.mitigations,
                self.security_concepts,
                self.assumptions,
                self.language is not None,
                self.scope is not None,
            )
        )

    @property
    def has_exact_policy_constraints(self) -> bool:
        return (
            self.action is not None
            and self.scope is not None
            and bool(self.preconditions or self.effects)
        )

    @property
    def grants_policy_authority(self) -> bool:
        return False

    @property
    def policy_match_terms(self) -> tuple[SolidityTerm, ...]:
        terms = [
            *self.preconditions,
            *self.effects,
            *self.mitigations,
            *self.security_concepts,
            *self.assumptions,
        ]
        if self.action is not None:
            terms.append(self.action)
        if self.language is not None:
            terms.append(self.language)
        if self.scope is not None:
            terms.append(self.scope)
        return tuple(sorted(terms, key=lambda item: item.canonical))

    def require_exact_policy_constraints(self) -> "SolidityPolicyAttributes":
        if not self.has_exact_policy_constraints:
            raise SolidityVocabularyError(
                "quality or classification-only attributes are not sufficient "
                "policy authority; an exact action, scope, and precondition "
                "or effect are required"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.canonical if self.action is not None else None,
            "assumptions": [term.canonical for term in self.assumptions],
            "authority_type": (
                self.authority_type.canonical
                if self.authority_type is not None
                else None
            ),
            "effects": [term.canonical for term in self.effects],
            "language": (
                self.language.canonical if self.language is not None else None
            ),
            "mitigations": [term.canonical for term in self.mitigations],
            "preconditions": [term.canonical for term in self.preconditions],
            "schema_version": self.schema_version,
            "scope": self.scope.canonical if self.scope is not None else None,
            "security_concepts": [
                term.canonical for term in self.security_concepts
            ],
        }

    def to_security_ir_attributes(self) -> dict[str, Any]:
        return {SOLIDITY_POLICY_ATTRIBUTES_KEY: self.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SolidityPolicyAttributes":
        if not isinstance(value, Mapping):
            raise SolidityVocabularyError(
                "Solidity CPT policy attributes must be a mapping"
            )
        expected = {
            "action",
            "assumptions",
            "authority_type",
            "effects",
            "language",
            "mitigations",
            "preconditions",
            "schema_version",
            "scope",
            "security_concepts",
        }
        if set(value) != expected:
            unknown = sorted(set(value) - expected)
            missing = sorted(expected - set(value))
            details = []
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            if missing:
                details.append("missing: " + ", ".join(missing))
            raise SolidityVocabularyError(
                "Solidity CPT policy attribute fields are not canonical ("
                + "; ".join(details)
                + ")"
            )
        return cls(
            action=value["action"],
            preconditions=value["preconditions"],
            effects=value["effects"],
            mitigations=value["mitigations"],
            security_concepts=value["security_concepts"],
            assumptions=value["assumptions"],
            language=value["language"],
            scope=value["scope"],
            authority_type=value["authority_type"],
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_security_ir_attributes(
        cls, attributes: Mapping[str, Any]
    ) -> "SolidityPolicyAttributes":
        if not isinstance(attributes, Mapping):
            raise SolidityVocabularyError(
                "Security IR policy attributes must be a mapping"
            )
        if SOLIDITY_POLICY_ATTRIBUTES_KEY not in attributes:
            raise SolidityVocabularyError(
                f"missing {SOLIDITY_POLICY_ATTRIBUTES_KEY!r} policy attributes"
            )
        return cls.from_dict(attributes[SOLIDITY_POLICY_ATTRIBUTES_KEY])


def validate_solidity_policy_attributes(
    attributes: Mapping[str, Any],
    *,
    require_exact_policy_constraints: bool = False,
) -> SolidityPolicyAttributes:
    """Parse canonical Security IR attributes and optionally require exactness."""

    result = SolidityPolicyAttributes.from_security_ir_attributes(attributes)
    if require_exact_policy_constraints:
        result.require_exact_policy_constraints()
    return result


validate_policy_attributes = validate_solidity_policy_attributes


def _vocab_terms_default() -> Mapping[str, frozenset[str]]:
    return MappingProxyType(
        {kind.value: frozenset(names) for kind, names in _FIXED_TERMS.items()}
    )


@dataclass(frozen=True, slots=True)
class SolidityVocabulary:
    """Immutable registry view of the reviewed Solidity CPT vocabulary."""

    schema_version: str = SOLIDITY_VOCABULARY_SCHEMA_VERSION
    terms: Mapping[str, frozenset[str]] = field(
        default_factory=_vocab_terms_default
    )

    def __post_init__(self) -> None:
        if self.schema_version != SOLIDITY_VOCABULARY_SCHEMA_VERSION:
            raise SolidityVocabularyError(
                "unsupported Solidity vocabulary schema version"
            )
        expected = {
            kind.value: frozenset(names) for kind, names in _FIXED_TERMS.items()
        }
        if not isinstance(self.terms, Mapping):
            raise SolidityVocabularyError("terms must be a mapping")
        actual = {
            str(key): frozenset(value) for key, value in self.terms.items()
        }
        if actual != expected:
            raise SolidityVocabularyError(
                "terms must exactly match the reviewed vocabulary"
            )
        object.__setattr__(
            self, "terms", MappingProxyType(dict(sorted(actual.items())))
        )

    def contains(self, kind: SolidityTermKind | str, name: str) -> bool:
        kind = _coerce_kind(kind)
        return name in _FIXED_TERMS[kind]

    def term(self, kind: SolidityTermKind | str, name: str) -> SolidityTerm:
        return solidity_term(kind, name)

    def authority_types(self) -> tuple[SolidityAuthorityType, ...]:
        return tuple(SolidityAuthorityType)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_types": [item.value for item in SolidityAuthorityType],
            "schema_version": self.schema_version,
            "terms": {
                key: sorted(value) for key, value in sorted(self.terms.items())
            },
        }


DEFAULT_SOLIDITY_VOCABULARY: Final = SolidityVocabulary()


__all__ = [
    "DEFAULT_SOLIDITY_VOCABULARY",
    "SOLIDITY_ACTIONS",
    "SOLIDITY_ALIASES",
    "SOLIDITY_ASSUMPTIONS",
    "SOLIDITY_AUTHORITY_TYPES",
    "SOLIDITY_EDGE_TYPES",
    "SOLIDITY_EFFECTS",
    "SOLIDITY_LANGUAGES",
    "SOLIDITY_MITIGATIONS",
    "SOLIDITY_NODE_TYPES",
    "SOLIDITY_POLICY_ATTRIBUTES_KEY",
    "SOLIDITY_PRECONDITIONS",
    "SOLIDITY_SCHEMA_VERSION",
    "SOLIDITY_SCOPES",
    "SOLIDITY_SECURITY_CONCEPTS",
    "SOLIDITY_TERMS",
    "SOLIDITY_VOCABULARY",
    "SOLIDITY_VOCABULARY_NAMESPACE",
    "SOLIDITY_VOCABULARY_SCHEMA_VERSION",
    "SOLIDITY_VOCABULARY_VERSION",
    "AuthorityType",
    "SolidityAlias",
    "SolidityAuthorityType",
    "SolidityPolicyAttributes",
    "SolidityPolicyRole",
    "SolidityTerm",
    "SolidityTermKind",
    "SolidityVocabulary",
    "SolidityVocabularyError",
    "TermKind",
    "VocabularyTermKind",
    "authority_type_term",
    "canonical_term",
    "parse_solidity_term",
    "parse_term",
    "require_authority_type",
    "resolve_solidity_term",
    "resolve_term",
    "solidity_term",
    "validate_policy_attributes",
    "validate_solidity_aliases",
    "validate_solidity_policy_attributes",
]
