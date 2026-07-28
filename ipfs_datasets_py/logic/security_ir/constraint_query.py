"""Select applicable Security constraints (``SecurityConstraintQuery@1``).

Hard-scopes Security constraints for a concrete invocation context using
principal/delegation/capability, trust zone, asset/data class/channel/network/
filesystem, action/state/effect/failure/rollback, sandbox/environment evidence,
threat/policy version and freshness, and result-authority family.

Non-goals / fail-closed invariants:

* Theorem, runtime-monitor, evidence-gate, and policy artifacts remain distinct
  result authorities; none may substitute for another.
* Abstract-model evidence never substitutes for live-environment evidence (and
  the reverse).
* Stale or digest-mismatched evidence is rejected.
* Unknown extensions fail closed.
* Unresolved conflict, applicability gap, or unbounded selection yields
  review/abstain (never silent allow).
* Contradictions are preserved; they are never discarded to force a winner.
* Retrieval/similarity rank is advisory only and never selects authority.
* Domain-native Security selection does not grant Legal compliance or free
  execution admission by itself.

Interfaces:

* ``SecurityConstraintQuery@1`` — immutable query context + selection entry point.
* ``SecurityApplicabilityEvidence@1`` — Security-domain applicability receipt that
  composes shared ``ApplicabilityEvidence@1`` without flattening Security norms
  into a neutral formula.

This leaf may *call* shared constraint contracts, Security model types, and the
known-extension allowlist from the constraint cache.  It does not edit the proof
corpus, Legal query, exports, or registries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    ApplicabilityEvidence,
    ApplicabilitySelector,
    ApplicabilityStatus,
    ConstraintValidationError,
    CoverageGap,
    CoverageGapKind,
    PremiseSelectionMethod,
    SelectedPremise,
    SelectedPremiseSet,
    WorldPolicy,
    WorldPolicyKind,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind

from .constraint_cache import (
    KNOWN_SECURITY_EXTENSION_VOCABULARIES,
    known_extension_vocabularies,
)
from .exchange.vocabulary import EXCHANGE_VOCABULARY
from .xaman.config import XAMAN_VOCABULARY


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SECURITY_CONSTRAINT_QUERY_INTERFACE: Final = "SecurityConstraintQuery@1"
SECURITY_APPLICABILITY_EVIDENCE_INTERFACE: Final = "SecurityApplicabilityEvidence@1"
SECURITY_CONSTRAINT_QUERY_SCHEMA_VERSION: Final = "security-constraint-query/v1"
SECURITY_APPLICABILITY_EVIDENCE_SCHEMA_VERSION: Final = (
    "security-applicability-evidence/v1"
)
SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION: Final = "security-constraint-record/v1"
SECURITY_CONSTRAINT_SELECTION_SCHEMA_VERSION: Final = (
    "security-constraint-selection/v1"
)
SECURITY_EVIDENCE_BINDING_SCHEMA_VERSION: Final = "security-evidence-binding/v1"

SECURITY_CONSTRAINT_QUERY_IDENTITY_DOMAIN: Final = "security-constraint-query"
SECURITY_APPLICABILITY_EVIDENCE_IDENTITY_DOMAIN: Final = (
    "security-applicability-evidence"
)
SECURITY_CONSTRAINT_SELECTION_IDENTITY_DOMAIN: Final = "security-constraint-selection"

MAX_COLLECTION_ITEMS: Final = 1_024
MAX_STRING_CHARS: Final = 16_384
MAX_IDENTIFIER_CHARS: Final = 256
DEFAULT_SELECTION_BUDGET: Final = 64

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)
_WILDCARDS: Final = frozenset({"*", "any", "all", ""})

# Hard-filter dimensions (documentary order; evaluation is independent).
SECURITY_HARD_FILTER_DIMENSIONS: Final[tuple[str, ...]] = (
    "principal",
    "delegation",
    "capability",
    "trust_zone",
    "asset",
    "data_class",
    "channel",
    "network",
    "filesystem",
    "action",
    "state",
    "effect",
    "failure",
    "rollback",
    "sandbox",
    "environment",
    "threat_model",
    "policy_version",
    "freshness",
    "result_authority",
    "extension",
    "provenance",
    "premise_taint",
    "declaration",
)

# Closed artifact / result-authority families that must never substitute.
SECURITY_ARTIFACT_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "theorem",
        "monitor",
        "evidence_gate",
        "policy",
        "satisfiability",
    }
)

_AUTHORITY_TO_ARTIFACT: Final[Mapping[AuthorityKind, str]] = MappingProxyType(
    {
        AuthorityKind.THEOREM_PROOF: "theorem",
        AuthorityKind.RUNTIME_MONITOR: "monitor",
        AuthorityKind.EVIDENCE_READINESS: "evidence_gate",
        AuthorityKind.POLICY_APPROVAL: "policy",
        AuthorityKind.SATISFIABILITY: "satisfiability",
    }
)

_ARTIFACT_TO_AUTHORITY: Final[Mapping[str, AuthorityKind]] = MappingProxyType(
    {
        "theorem": AuthorityKind.THEOREM_PROOF,
        "monitor": AuthorityKind.RUNTIME_MONITOR,
        "evidence_gate": AuthorityKind.EVIDENCE_READINESS,
        "policy": AuthorityKind.POLICY_APPROVAL,
        "satisfiability": AuthorityKind.SATISFIABILITY,
        # Aliases accepted at the boundary.
        "theorem_proof": AuthorityKind.THEOREM_PROOF,
        "runtime_monitor": AuthorityKind.RUNTIME_MONITOR,
        "evidence_readiness": AuthorityKind.EVIDENCE_READINESS,
        "policy_approval": AuthorityKind.POLICY_APPROVAL,
    }
)

_OPPOSED_EFFECT_PAIRS: Final[frozenset[frozenset[str]]] = frozenset(
    {
        frozenset({"allow", "deny"}),
        frozenset({"permit", "deny"}),
        frozenset({"require", "deny"}),
        frozenset({"allow", "prohibit"}),
    }
)

_DEFAULT_KNOWN_EXTENSION_VOCABS: Final[frozenset[str]] = frozenset(
    KNOWN_SECURITY_EXTENSION_VOCABULARIES
    | {EXCHANGE_VOCABULARY, XAMAN_VOCABULARY}
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SecurityConstraintQueryError(ValueError):
    """Raised when a Security constraint query contract is malformed."""


class SecurityConstraintEffect(str, Enum):
    """Declarative effect / role of one Security constraint candidate."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE = "require"
    AUDIT = "audit"
    INVARIANT = "invariant"
    ASSUMPTION = "assumption"
    CLAIM = "claim"
    PROHIBIT = "prohibit"
    PERMIT = "permit"
    UNSPECIFIED = "unspecified"


class SecurityConstraintDisposition(str, Enum):
    """Per-constraint outcome after hard filters and relationship resolution."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    STALE = "stale"
    MISMATCHED = "mismatched"
    SUPERSEDED = "superseded"
    DEFEATED = "defeated"
    CONFLICTING = "conflicting"
    INDETERMINATE = "indeterminate"
    REVIEW_REQUIRED = "review_required"
    TAINTED = "tainted"
    COVERAGE_GAP = "coverage_gap"
    ABSTAIN = "abstain"
    UNKNOWN_EXTENSION = "unknown_extension"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    AUTHORITY_MISMATCH = "authority_mismatch"


class SecuritySelectionDisposition(str, Enum):
    """Overall selection outcome for one query against a candidate set."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"
    COVERAGE_GAP = "coverage_gap"
    REVIEW_REQUIRED = "review_required"
    ABSTAIN = "abstain"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
    AUTHORITY_MISMATCH = "authority_mismatch"


class SecurityPremiseTaintStatus(str, Enum):
    """Declared premise/provenance trust for one constraint record."""

    CLEAN = "clean"
    TAINTED = "tainted"
    UNKNOWN = "unknown"
    UNREVIEWED = "unreviewed"


class SecurityEnvironmentKind(str, Enum):
    """Environment model boundary for evidence and constraints."""

    ABSTRACT_MODEL = "abstract_model"
    LIVE_ENVIRONMENT = "live_environment"
    SANDBOX = "sandbox"
    UNSPECIFIED = "unspecified"


class SecurityArtifactFamily(str, Enum):
    """Closed Security artifact families that must remain non-substitutable."""

    THEOREM = "theorem"
    MONITOR = "monitor"
    EVIDENCE_GATE = "evidence_gate"
    POLICY = "policy"
    SATISFIABILITY = "satisfiability"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SecurityConstraintQueryError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise SecurityConstraintQueryError(f"{name} must be a string")
    if value != value.strip() or "\x00" in value:
        raise SecurityConstraintQueryError(
            f"{name} must not contain surrounding whitespace or NUL"
        )
    if not allow_empty and not value:
        raise SecurityConstraintQueryError(f"{name} must not be empty")
    if len(value) > max_chars:
        raise SecurityConstraintQueryError(f"{name} exceeds maximum length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value is None:
        return ""
    return _text(value, name, allow_empty=True)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise SecurityConstraintQueryError(f"{name} is not a valid identifier")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    if value is None or value == "":
        return ""
    return _identifier(value, name)


def _digest_or_empty(value: Any, name: str) -> str:
    text = _optional_text(value, name)
    if not text:
        return ""
    if not _DIGEST_RE.fullmatch(text):
        raise SecurityConstraintQueryError(
            f"{name} must be a sha256:<hex> digest or empty"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SecurityConstraintQueryError(f"{name} must be a mapping")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SecurityConstraintQueryError(f"{name} must be a sequence")
    if len(value) > MAX_COLLECTION_ITEMS:
        raise SecurityConstraintQueryError(f"{name} exceeds collection bound")
    return value


def _unique_sorted_ids(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_identifier(value, name),)
    seq = _sequence(value, name)
    items = tuple(_identifier(item, name) for item in seq)
    if len(items) != len(set(items)):
        raise SecurityConstraintQueryError(f"{name} must be unique")
    return tuple(sorted(items))


def _unique_sorted_texts(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = _text(value, name)
        if text.lower() in _WILDCARDS:
            raise SecurityConstraintQueryError(
                f"{name} must contain explicit values, not a wildcard"
            )
        return (text,)
    seq = _sequence(value, name)
    items: list[str] = []
    for item in seq:
        text = _text(item, name)
        if text.lower() in _WILDCARDS:
            raise SecurityConstraintQueryError(
                f"{name} must contain explicit values, not a wildcard"
            )
        items.append(text)
    if len(items) != len(set(items)):
        raise SecurityConstraintQueryError(f"{name} must be unique")
    return tuple(sorted(items))


def _non_negative_int(value: Any, name: str, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise SecurityConstraintQueryError(f"{name} must be an int")
    if value < 0:
        raise SecurityConstraintQueryError(f"{name} must be non-negative")
    return value


def _bool(value: Any, name: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SecurityConstraintQueryError(f"{name} must be a bool")
    return value


def _enum_value(value: Any, enum_cls: type[Enum], name: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if not isinstance(value, str):
        raise SecurityConstraintQueryError(
            f"{name} must be a string or {enum_cls.__name__}"
        )
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise SecurityConstraintQueryError(f"unsupported {name}: {value!r}") from exc


def _frozen_map(value: Any, name: str) -> FrozenMap:
    if isinstance(value, FrozenMap):
        return value
    if value is None:
        return FrozenMap({})
    if not isinstance(value, Mapping):
        raise SecurityConstraintQueryError(f"{name} must be a mapping")
    return FrozenMap(dict(value))


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds = seconds / 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _DATE_RE.fullmatch(text):
        try:
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if "T" in text or " " in text:
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _datetime_text(value: Any, name: str) -> str:
    if value is None or value == "":
        return ""
    parsed = _parse_datetime(value)
    if parsed is None:
        raise SecurityConstraintQueryError(f"{name} is not a valid datetime")
    return parsed.isoformat().replace("+00:00", "Z")


def _effect_atom(value: Any) -> SecurityConstraintEffect:
    if value is None or value == "":
        return SecurityConstraintEffect.UNSPECIFIED
    if isinstance(value, SecurityConstraintEffect):
        return value
    raw = _text(str(value), "effect").lower().replace("-", "_")
    aliases = {
        "allow": SecurityConstraintEffect.ALLOW,
        "allowed": SecurityConstraintEffect.ALLOW,
        "permit": SecurityConstraintEffect.PERMIT,
        "permission": SecurityConstraintEffect.PERMIT,
        "deny": SecurityConstraintEffect.DENY,
        "denied": SecurityConstraintEffect.DENY,
        "prohibit": SecurityConstraintEffect.PROHIBIT,
        "prohibition": SecurityConstraintEffect.PROHIBIT,
        "require": SecurityConstraintEffect.REQUIRE,
        "required": SecurityConstraintEffect.REQUIRE,
        "obligation": SecurityConstraintEffect.REQUIRE,
        "audit": SecurityConstraintEffect.AUDIT,
        "invariant": SecurityConstraintEffect.INVARIANT,
        "assumption": SecurityConstraintEffect.ASSUMPTION,
        "claim": SecurityConstraintEffect.CLAIM,
        "unspecified": SecurityConstraintEffect.UNSPECIFIED,
    }
    effect = aliases.get(raw)
    if effect is None:
        raise SecurityConstraintQueryError(f"unsupported effect: {value!r}")
    return effect


def _environment_kind(value: Any) -> SecurityEnvironmentKind:
    if value is None or value == "":
        return SecurityEnvironmentKind.UNSPECIFIED
    if isinstance(value, SecurityEnvironmentKind):
        return value
    raw = _text(str(value), "environment_kind").lower().replace("-", "_")
    aliases = {
        "abstract_model": SecurityEnvironmentKind.ABSTRACT_MODEL,
        "abstract": SecurityEnvironmentKind.ABSTRACT_MODEL,
        "model": SecurityEnvironmentKind.ABSTRACT_MODEL,
        "live_environment": SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        "live": SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        "production": SecurityEnvironmentKind.LIVE_ENVIRONMENT,
        "sandbox": SecurityEnvironmentKind.SANDBOX,
        "unspecified": SecurityEnvironmentKind.UNSPECIFIED,
    }
    kind = aliases.get(raw)
    if kind is None:
        raise SecurityConstraintQueryError(f"unsupported environment_kind: {value!r}")
    return kind


def _artifact_family(value: Any) -> SecurityArtifactFamily:
    if isinstance(value, SecurityArtifactFamily):
        return value
    if isinstance(value, AuthorityKind):
        mapped = _AUTHORITY_TO_ARTIFACT.get(value)
        if mapped is None:
            raise SecurityConstraintQueryError(
                f"unsupported authority kind for artifact family: {value!r}"
            )
        return SecurityArtifactFamily(mapped)
    raw = _text(str(value), "artifact_family").lower().replace("-", "_")
    authority = _ARTIFACT_TO_AUTHORITY.get(raw)
    if authority is None:
        raise SecurityConstraintQueryError(f"unsupported artifact_family: {value!r}")
    return SecurityArtifactFamily(_AUTHORITY_TO_ARTIFACT[authority])


def _authority_kind(value: Any) -> AuthorityKind:
    if isinstance(value, AuthorityKind):
        # Normalize aliases that share values.
        return AuthorityKind(value.value)
    if isinstance(value, SecurityArtifactFamily):
        return _ARTIFACT_TO_AUTHORITY[value.value]
    raw = _text(str(value), "required_authority").lower().replace("-", "_")
    if raw in _ARTIFACT_TO_AUTHORITY:
        return _ARTIFACT_TO_AUTHORITY[raw]
    try:
        return AuthorityKind(raw)
    except ValueError as exc:
        raise SecurityConstraintQueryError(
            f"unsupported required_authority: {value!r}"
        ) from exc


def _scope_contains(
    allowed: tuple[str, ...],
    query_value: str,
    *,
    query_values: tuple[str, ...] = (),
) -> bool | None:
    """Return True/False for hard match, or None when the scope is open."""

    if not allowed:
        return None
    if query_values:
        return bool(set(allowed) & set(query_values))
    if not query_value:
        return None
    return query_value in allowed


def _environments_compatible(
    record_kind: SecurityEnvironmentKind,
    query_kind: SecurityEnvironmentKind,
    *,
    forbid_substitution: bool,
) -> tuple[bool, str]:
    """Check abstract-model vs live-environment substitution rules."""

    if (
        record_kind is SecurityEnvironmentKind.UNSPECIFIED
        or query_kind is SecurityEnvironmentKind.UNSPECIFIED
    ):
        return True, ""
    if record_kind is query_kind:
        return True, "environment_match"
    if not forbid_substitution:
        return True, "environment_substitution_allowed"
    abstract = SecurityEnvironmentKind.ABSTRACT_MODEL
    live = SecurityEnvironmentKind.LIVE_ENVIRONMENT
    if {record_kind, query_kind} == {abstract, live}:
        return False, "abstract_model_live_environment_substitution"
    # Sandbox is not a substitute for live production evidence either.
    if live in {record_kind, query_kind} and abstract not in {record_kind, query_kind}:
        if SecurityEnvironmentKind.SANDBOX in {record_kind, query_kind}:
            return False, "sandbox_live_environment_substitution"
    return False, "environment_kind_mismatch"


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecurityEvidenceBinding:
    """One concrete evidence artifact bound into a selection query.

    Artifact family and environment kind are closed and non-substitutable under
    default policy.  Freshness is evaluated against the query ``as_of``.
    """

    evidence_id: str
    artifact_family: SecurityArtifactFamily
    content_digest: str = ""
    observed_at: str = ""
    environment_kind: SecurityEnvironmentKind = SecurityEnvironmentKind.UNSPECIFIED
    environment_id: str = ""
    authority_kind: AuthorityKind = AuthorityKind.EVIDENCE_READINESS
    max_age_seconds: int | None = None
    schema_version: str = SECURITY_EVIDENCE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "artifact_family", _artifact_family(self.artifact_family)
        )
        object.__setattr__(
            self,
            "content_digest",
            _digest_or_empty(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "observed_at",
            _datetime_text(self.observed_at, "observed_at") if self.observed_at else "",
        )
        object.__setattr__(
            self, "environment_kind", _environment_kind(self.environment_kind)
        )
        object.__setattr__(
            self,
            "environment_id",
            _optional_identifier(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self, "authority_kind", _authority_kind(self.authority_kind)
        )
        # Authority must agree with artifact family.
        expected = _ARTIFACT_TO_AUTHORITY[self.artifact_family.value]
        if self.authority_kind is not expected:
            raise SecurityConstraintQueryError(
                "evidence authority_kind must match artifact_family "
                f"({self.artifact_family.value} requires {expected.value})"
            )
        if self.max_age_seconds is not None:
            object.__setattr__(
                self,
                "max_age_seconds",
                _non_negative_int(self.max_age_seconds, "max_age_seconds"),
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SECURITY_EVIDENCE_BINDING_SCHEMA_VERSION:
            raise SecurityConstraintQueryError(
                f"unsupported evidence binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_family": self.artifact_family.value,
            "authority_kind": self.authority_kind.value,
            "content_digest": self.content_digest,
            "environment_id": self.environment_id,
            "environment_kind": self.environment_kind.value,
            "evidence_id": self.evidence_id,
            "max_age_seconds": self.max_age_seconds,
            "observed_at": self.observed_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityEvidenceBinding":
        value = _mapping(value, "security evidence binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_family",
                    "authority_kind",
                    "content_digest",
                    "environment_id",
                    "environment_kind",
                    "evidence_id",
                    "max_age_seconds",
                    "observed_at",
                    "schema_version",
                    "family",
                    "digest",
                }
            ),
            "security evidence binding",
        )
        family = value.get("artifact_family", value.get("family", "evidence_gate"))
        return cls(
            evidence_id=value.get("evidence_id", ""),
            artifact_family=family,
            content_digest=value.get(
                "content_digest", value.get("digest", "")
            ),
            observed_at=value.get("observed_at", ""),
            environment_kind=value.get("environment_kind", "unspecified"),
            environment_id=value.get("environment_id", ""),
            authority_kind=value.get(
                "authority_kind",
                _ARTIFACT_TO_AUTHORITY.get(
                    str(family).lower().replace("-", "_"),
                    AuthorityKind.EVIDENCE_READINESS,
                ),
            ),
            max_age_seconds=value.get("max_age_seconds"),
            schema_version=value.get(
                "schema_version", SECURITY_EVIDENCE_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SecurityConstraintRecord:
    """One candidate Security constraint with hard-filter and relationship fields.

    Distinct from the content-addressed cache envelope in
    :mod:`constraint_cache`.  ``retrieval_rank`` is advisory diagnostics only.
    """

    constraint_id: str
    effect: SecurityConstraintEffect = SecurityConstraintEffect.UNSPECIFIED
    principals: tuple[str, ...] = ()
    delegation_ids: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    trust_zones: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    networks: tuple[str, ...] = ()
    filesystems: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    rollbacks: tuple[str, ...] = ()
    sandbox_ids: tuple[str, ...] = ()
    environment_kind: SecurityEnvironmentKind = SecurityEnvironmentKind.UNSPECIFIED
    environment_ids: tuple[str, ...] = ()
    threat_model_id: str = ""
    threat_model_version: str = ""
    policy_id: str = ""
    policy_version: str = ""
    artifact_family: SecurityArtifactFamily = SecurityArtifactFamily.EVIDENCE_GATE
    required_authority: AuthorityKind = AuthorityKind.EVIDENCE_READINESS
    evidence_ids: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    max_evidence_age_seconds: int | None = None
    extension_ids: tuple[str, ...] = ()
    extension_vocabularies: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    premise_taint: SecurityPremiseTaintStatus = SecurityPremiseTaintStatus.UNKNOWN
    trusted_source: bool = False
    reviewed: bool = False
    declaration_id: str = ""
    declaration_digest: str = ""
    conflict_key: str = ""
    statement: str = ""
    supersedes: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    precedence: int = 0
    priority: int = 0
    retrieval_rank: int | None = None
    retrieval_score: float | None = None
    mandatory: bool = True
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "constraint_id", _identifier(self.constraint_id, "constraint_id")
        )
        object.__setattr__(self, "effect", _effect_atom(self.effect))
        for name in (
            "principals",
            "delegation_ids",
            "capabilities",
            "trust_zones",
            "assets",
            "data_classes",
            "channels",
            "networks",
            "filesystems",
            "actions",
            "states",
            "effects",
            "failures",
            "rollbacks",
            "sandbox_ids",
            "environment_ids",
            "evidence_ids",
            "extension_ids",
            "extension_vocabularies",
            "source_ref_ids",
            "provenance_ids",
            "supersedes",
            "conflicts_with",
        ):
            raw = getattr(self, name)
            if name in {
                "principals",
                "capabilities",
                "trust_zones",
                "assets",
                "data_classes",
                "channels",
                "networks",
                "filesystems",
                "actions",
                "states",
                "effects",
                "failures",
                "rollbacks",
            }:
                object.__setattr__(self, name, _unique_sorted_texts(raw, name))
            else:
                object.__setattr__(self, name, _unique_sorted_ids(raw, name))
        digests = self.evidence_digests
        if digests is None:
            object.__setattr__(self, "evidence_digests", ())
        elif isinstance(digests, str):
            object.__setattr__(
                self, "evidence_digests", (_digest_or_empty(digests, "evidence_digests"),)
            )
            if not self.evidence_digests[0]:
                object.__setattr__(self, "evidence_digests", ())
        else:
            seq = _sequence(digests, "evidence_digests")
            normalized = tuple(
                _digest_or_empty(item, "evidence_digests") for item in seq
            )
            if any(not item for item in normalized):
                raise SecurityConstraintQueryError(
                    "evidence_digests entries must be sha256 digests"
                )
            if len(normalized) != len(set(normalized)):
                raise SecurityConstraintQueryError("evidence_digests must be unique")
            object.__setattr__(self, "evidence_digests", tuple(sorted(normalized)))
        object.__setattr__(
            self, "environment_kind", _environment_kind(self.environment_kind)
        )
        object.__setattr__(
            self,
            "threat_model_id",
            _optional_identifier(self.threat_model_id, "threat_model_id"),
        )
        object.__setattr__(
            self,
            "threat_model_version",
            _optional_text(self.threat_model_version, "threat_model_version"),
        )
        object.__setattr__(
            self, "policy_id", _optional_identifier(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "policy_version",
            _optional_text(self.policy_version, "policy_version"),
        )
        object.__setattr__(
            self, "artifact_family", _artifact_family(self.artifact_family)
        )
        object.__setattr__(
            self, "required_authority", _authority_kind(self.required_authority)
        )
        expected = _ARTIFACT_TO_AUTHORITY[self.artifact_family.value]
        if self.required_authority is not expected:
            raise SecurityConstraintQueryError(
                "required_authority must match artifact_family "
                f"({self.artifact_family.value} requires {expected.value})"
            )
        if self.max_evidence_age_seconds is not None:
            object.__setattr__(
                self,
                "max_evidence_age_seconds",
                _non_negative_int(
                    self.max_evidence_age_seconds, "max_evidence_age_seconds"
                ),
            )
        object.__setattr__(
            self,
            "premise_taint",
            _enum_value(
                self.premise_taint, SecurityPremiseTaintStatus, "premise_taint"
            ),
        )
        object.__setattr__(
            self, "trusted_source", _bool(self.trusted_source, "trusted_source")
        )
        object.__setattr__(self, "reviewed", _bool(self.reviewed, "reviewed"))
        object.__setattr__(
            self,
            "declaration_id",
            _optional_identifier(self.declaration_id, "declaration_id"),
        )
        object.__setattr__(
            self,
            "declaration_digest",
            _digest_or_empty(self.declaration_digest, "declaration_digest"),
        )
        object.__setattr__(
            self, "conflict_key", _optional_text(self.conflict_key, "conflict_key")
        )
        object.__setattr__(
            self, "statement", _optional_text(self.statement, "statement")
        )
        object.__setattr__(
            self, "precedence", _non_negative_int(self.precedence, "precedence")
        )
        object.__setattr__(
            self, "priority", _non_negative_int(self.priority, "priority")
        )
        if self.retrieval_rank is not None:
            object.__setattr__(
                self,
                "retrieval_rank",
                _non_negative_int(self.retrieval_rank, "retrieval_rank"),
            )
        if self.retrieval_score is not None:
            if not isinstance(self.retrieval_score, (int, float)) or isinstance(
                self.retrieval_score, bool
            ):
                raise SecurityConstraintQueryError(
                    "retrieval_score must be a finite number"
                )
            score = float(self.retrieval_score)
            if score != score or score in (float("inf"), float("-inf")):
                raise SecurityConstraintQueryError("retrieval_score must be finite")
            object.__setattr__(self, "retrieval_score", score)
        object.__setattr__(
            self, "mandatory", _bool(self.mandatory, "mandatory", default=True)
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION:
            raise SecurityConstraintQueryError(
                f"unsupported security constraint record schema: {self.schema_version!r}"
            )

    @property
    def applicability_key(self) -> str:
        return self.conflict_key or self.constraint_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "artifact_family": self.artifact_family.value,
            "assets": list(self.assets),
            "capabilities": list(self.capabilities),
            "channels": list(self.channels),
            "conflict_key": self.conflict_key,
            "conflicts_with": list(self.conflicts_with),
            "constraint_id": self.constraint_id,
            "data_classes": list(self.data_classes),
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "delegation_ids": list(self.delegation_ids),
            "effect": self.effect.value,
            "effects": list(self.effects),
            "environment_ids": list(self.environment_ids),
            "environment_kind": self.environment_kind.value,
            "evidence_digests": list(self.evidence_digests),
            "evidence_ids": list(self.evidence_ids),
            "extension_ids": list(self.extension_ids),
            "extension_vocabularies": list(self.extension_vocabularies),
            "failures": list(self.failures),
            "filesystems": list(self.filesystems),
            "mandatory": self.mandatory,
            "max_evidence_age_seconds": self.max_evidence_age_seconds,
            "metadata": self.metadata.to_dict(),
            "networks": list(self.networks),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "precedence": self.precedence,
            "premise_taint": self.premise_taint.value,
            "principals": list(self.principals),
            "priority": self.priority,
            "provenance_ids": list(self.provenance_ids),
            "required_authority": self.required_authority.value,
            "retrieval_rank": self.retrieval_rank,
            "retrieval_score": self.retrieval_score,
            "reviewed": self.reviewed,
            "rollbacks": list(self.rollbacks),
            "sandbox_ids": list(self.sandbox_ids),
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "states": list(self.states),
            "statement": self.statement,
            "supersedes": list(self.supersedes),
            "threat_model_id": self.threat_model_id,
            "threat_model_version": self.threat_model_version,
            "trust_zones": list(self.trust_zones),
            "trusted_source": self.trusted_source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityConstraintRecord":
        value = _mapping(value, "security constraint record")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actions",
                    "artifact_family",
                    "assets",
                    "capabilities",
                    "channels",
                    "conflict_key",
                    "conflicts_with",
                    "constraint_id",
                    "data_classes",
                    "declaration_digest",
                    "declaration_id",
                    "delegation_ids",
                    "effect",
                    "effects",
                    "environment_ids",
                    "environment_kind",
                    "evidence_digests",
                    "evidence_ids",
                    "extension_ids",
                    "extension_vocabularies",
                    "failures",
                    "filesystems",
                    "id",
                    "mandatory",
                    "max_evidence_age_seconds",
                    "metadata",
                    "networks",
                    "policy_id",
                    "policy_version",
                    "precedence",
                    "premise_taint",
                    "principal",
                    "principals",
                    "priority",
                    "provenance_ids",
                    "required_authority",
                    "retrieval_rank",
                    "retrieval_score",
                    "reviewed",
                    "rollbacks",
                    "sandbox_ids",
                    "schema_version",
                    "source_ref_ids",
                    "states",
                    "statement",
                    "supersedes",
                    "threat_model_id",
                    "threat_model_version",
                    "trust_zone",
                    "trust_zones",
                    "trusted_source",
                    "action",
                    "asset",
                    "capability",
                    "channel",
                    "data_class",
                    "delegation",
                    "network",
                    "filesystem",
                    "sandbox",
                    "state",
                    "failure",
                    "rollback",
                }
            ),
            "security constraint record",
        )
        constraint_id = value.get("constraint_id") or value.get("id")
        principals = value.get("principals", value.get("principal", ()))
        delegations = value.get("delegation_ids", value.get("delegation", ()))
        capabilities = value.get("capabilities", value.get("capability", ()))
        trust_zones = value.get("trust_zones", value.get("trust_zone", ()))
        assets = value.get("assets", value.get("asset", ()))
        data_classes = value.get("data_classes", value.get("data_class", ()))
        channels = value.get("channels", value.get("channel", ()))
        networks = value.get("networks", value.get("network", ()))
        filesystems = value.get("filesystems", value.get("filesystem", ()))
        actions = value.get("actions", value.get("action", ()))
        states = value.get("states", value.get("state", ()))
        effects = value.get("effects", ())
        failures = value.get("failures", value.get("failure", ()))
        rollbacks = value.get("rollbacks", value.get("rollback", ()))
        sandboxes = value.get("sandbox_ids", value.get("sandbox", ()))

        def _as_tuple(raw: Any) -> Any:
            return raw if not isinstance(raw, str) else (raw,)

        return cls(
            constraint_id=constraint_id or "",
            effect=value.get("effect", SecurityConstraintEffect.UNSPECIFIED.value),
            principals=_as_tuple(principals),
            delegation_ids=_as_tuple(delegations),
            capabilities=_as_tuple(capabilities),
            trust_zones=_as_tuple(trust_zones),
            assets=_as_tuple(assets),
            data_classes=_as_tuple(data_classes),
            channels=_as_tuple(channels),
            networks=_as_tuple(networks),
            filesystems=_as_tuple(filesystems),
            actions=_as_tuple(actions),
            states=_as_tuple(states),
            effects=_as_tuple(effects),
            failures=_as_tuple(failures),
            rollbacks=_as_tuple(rollbacks),
            sandbox_ids=_as_tuple(sandboxes),
            environment_kind=value.get("environment_kind", "unspecified"),
            environment_ids=value.get("environment_ids", ()),
            threat_model_id=value.get("threat_model_id", ""),
            threat_model_version=value.get("threat_model_version", ""),
            policy_id=value.get("policy_id", ""),
            policy_version=value.get("policy_version", ""),
            artifact_family=value.get(
                "artifact_family", SecurityArtifactFamily.EVIDENCE_GATE.value
            ),
            required_authority=value.get(
                "required_authority", AuthorityKind.EVIDENCE_READINESS.value
            ),
            evidence_ids=value.get("evidence_ids", ()),
            evidence_digests=value.get("evidence_digests", ()),
            max_evidence_age_seconds=value.get("max_evidence_age_seconds"),
            extension_ids=value.get("extension_ids", ()),
            extension_vocabularies=value.get("extension_vocabularies", ()),
            source_ref_ids=value.get("source_ref_ids", ()),
            provenance_ids=value.get("provenance_ids", ()),
            premise_taint=value.get(
                "premise_taint", SecurityPremiseTaintStatus.UNKNOWN.value
            ),
            trusted_source=value.get("trusted_source", False),
            reviewed=value.get("reviewed", False),
            declaration_id=value.get("declaration_id", ""),
            declaration_digest=value.get("declaration_digest", ""),
            conflict_key=value.get("conflict_key", ""),
            statement=value.get("statement", ""),
            supersedes=value.get("supersedes", ()),
            conflicts_with=value.get("conflicts_with", ()),
            precedence=value.get("precedence", 0),
            priority=value.get("priority", 0),
            retrieval_rank=value.get("retrieval_rank"),
            retrieval_score=value.get("retrieval_score"),
            mandatory=value.get("mandatory", True),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SecurityConstraintAssessment:
    """Disposition of one candidate after hard filters / relationship resolution."""

    constraint_id: str
    disposition: SecurityConstraintDisposition
    active: bool
    reason_codes: tuple[str, ...] = ()
    matched_dimensions: tuple[str, ...] = ()
    rejected_dimensions: tuple[str, ...] = ()
    defeated_by: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    retrieval_rank: int | None = None
    precedence: int = 0
    priority: int = 0
    effect: SecurityConstraintEffect = SecurityConstraintEffect.UNSPECIFIED
    artifact_family: SecurityArtifactFamily = SecurityArtifactFamily.EVIDENCE_GATE
    record: SecurityConstraintRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "constraint_id", _identifier(self.constraint_id, "constraint_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum_value(
                self.disposition, SecurityConstraintDisposition, "disposition"
            ),
        )
        object.__setattr__(self, "active", _bool(self.active, "active"))
        object.__setattr__(
            self,
            "reason_codes",
            tuple(sorted(set(_text(item, "reason_codes") for item in self.reason_codes))),
        )
        object.__setattr__(
            self,
            "matched_dimensions",
            tuple(
                sorted(
                    set(_text(item, "matched_dimensions") for item in self.matched_dimensions)
                )
            ),
        )
        object.__setattr__(
            self,
            "rejected_dimensions",
            tuple(
                sorted(
                    set(
                        _text(item, "rejected_dimensions")
                        for item in self.rejected_dimensions
                    )
                )
            ),
        )
        object.__setattr__(
            self, "defeated_by", _unique_sorted_ids(self.defeated_by, "defeated_by")
        )
        object.__setattr__(
            self,
            "conflicts_with",
            _unique_sorted_ids(self.conflicts_with, "conflicts_with"),
        )
        if self.retrieval_rank is not None:
            object.__setattr__(
                self,
                "retrieval_rank",
                _non_negative_int(self.retrieval_rank, "retrieval_rank"),
            )
        object.__setattr__(
            self, "precedence", _non_negative_int(self.precedence, "precedence")
        )
        object.__setattr__(
            self, "priority", _non_negative_int(self.priority, "priority")
        )
        object.__setattr__(self, "effect", _effect_atom(self.effect))
        object.__setattr__(
            self, "artifact_family", _artifact_family(self.artifact_family)
        )
        if self.record is not None and not isinstance(
            self.record, SecurityConstraintRecord
        ):
            raise SecurityConstraintQueryError(
                "record must be a SecurityConstraintRecord"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "artifact_family": self.artifact_family.value,
            "conflicts_with": list(self.conflicts_with),
            "constraint_id": self.constraint_id,
            "defeated_by": list(self.defeated_by),
            "disposition": self.disposition.value,
            "effect": self.effect.value,
            "matched_dimensions": list(self.matched_dimensions),
            "precedence": self.precedence,
            "priority": self.priority,
            "reason_codes": list(self.reason_codes),
            "record": self.record.to_dict() if self.record is not None else None,
            "rejected_dimensions": list(self.rejected_dimensions),
            "retrieval_rank": self.retrieval_rank,
        }


@dataclass(frozen=True, slots=True)
class SecurityContradiction:
    """Preserved contradiction between two or more selected Security constraints."""

    contradiction_id: str
    constraint_ids: tuple[str, ...]
    kind: str
    reason_codes: tuple[str, ...] = ()
    resolved: bool = False
    winning_constraint_id: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contradiction_id",
            _identifier(self.contradiction_id, "contradiction_id"),
        )
        ids = _unique_sorted_ids(self.constraint_ids, "constraint_ids")
        if len(ids) < 2:
            raise SecurityConstraintQueryError(
                "contradiction requires at least two constraint_ids"
            )
        object.__setattr__(self, "constraint_ids", ids)
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        object.__setattr__(
            self,
            "reason_codes",
            tuple(sorted(set(_text(item, "reason_codes") for item in self.reason_codes))),
        )
        object.__setattr__(self, "resolved", _bool(self.resolved, "resolved"))
        object.__setattr__(
            self,
            "winning_constraint_id",
            _optional_identifier(self.winning_constraint_id, "winning_constraint_id"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_ids": list(self.constraint_ids),
            "contradiction_id": self.contradiction_id,
            "kind": self.kind,
            "notes": self.notes,
            "reason_codes": list(self.reason_codes),
            "resolved": self.resolved,
            "winning_constraint_id": self.winning_constraint_id,
        }


# ---------------------------------------------------------------------------
# Query + evidence interfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecurityConstraintQuery:
    """``SecurityConstraintQuery@1`` — bound Security applicability query context.

    Selection entry point is :meth:`select`.  Ranking inputs on candidates are
    diagnostics only; hard filters, authority family, environment boundary,
    freshness, and precedence alone determine applicability.
    """

    INTERFACE: ClassVar[str] = SECURITY_CONSTRAINT_QUERY_INTERFACE

    query_id: str
    principal_id: str
    as_of: str
    delegation_ids: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    trust_zone: str = ""
    asset_id: str = ""
    data_class: str = ""
    channel_id: str = ""
    network: str = ""
    filesystem: str = ""
    action: str = ""
    state: str = ""
    effect: str = ""
    failure: str = ""
    rollback: str = ""
    sandbox_id: str = ""
    environment_kind: SecurityEnvironmentKind = SecurityEnvironmentKind.UNSPECIFIED
    environment_id: str = ""
    threat_model_id: str = ""
    threat_model_version: str = ""
    policy_id: str = ""
    policy_version: str = ""
    required_authority: AuthorityKind = AuthorityKind.EVIDENCE_READINESS
    artifact_family: SecurityArtifactFamily = SecurityArtifactFamily.EVIDENCE_GATE
    declaration_id: str = ""
    declaration_digest: str = ""
    invocation_digest: str = ""
    selection_budget: int = DEFAULT_SELECTION_BUDGET
    require_reviewed: bool = True
    require_trusted_source: bool = True
    require_provenance: bool = True
    forbid_abstract_live_substitution: bool = True
    require_evidence_binding: bool = False
    known_extension_vocabularies: tuple[str, ...] = ()
    world_policy_kind: WorldPolicyKind = WorldPolicyKind.CLOSED
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SECURITY_CONSTRAINT_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "principal_id", _identifier(self.principal_id, "principal_id")
        )
        as_of = _datetime_text(self.as_of, "as_of")
        if not as_of:
            raise SecurityConstraintQueryError("as_of is required")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(
            self,
            "delegation_ids",
            _unique_sorted_ids(self.delegation_ids, "delegation_ids"),
        )
        object.__setattr__(
            self, "capabilities", _unique_sorted_texts(self.capabilities, "capabilities")
        )
        for name in (
            "trust_zone",
            "asset_id",
            "data_class",
            "channel_id",
            "network",
            "filesystem",
            "action",
            "state",
            "effect",
            "failure",
            "rollback",
            "sandbox_id",
            "environment_id",
            "threat_model_id",
            "threat_model_version",
            "policy_id",
            "policy_version",
            "declaration_id",
        ):
            raw = getattr(self, name)
            if name in {
                "threat_model_version",
                "policy_version",
                "data_class",
                "network",
                "filesystem",
                "action",
                "state",
                "effect",
                "failure",
                "rollback",
                "trust_zone",
            }:
                object.__setattr__(self, name, _optional_text(raw, name))
            else:
                object.__setattr__(self, name, _optional_identifier(raw, name))
        object.__setattr__(
            self, "environment_kind", _environment_kind(self.environment_kind)
        )
        object.__setattr__(
            self, "artifact_family", _artifact_family(self.artifact_family)
        )
        object.__setattr__(
            self, "required_authority", _authority_kind(self.required_authority)
        )
        expected = _ARTIFACT_TO_AUTHORITY[self.artifact_family.value]
        if self.required_authority is not expected:
            raise SecurityConstraintQueryError(
                "required_authority must match artifact_family "
                f"({self.artifact_family.value} requires {expected.value})"
            )
        object.__setattr__(
            self,
            "declaration_digest",
            _digest_or_empty(self.declaration_digest, "declaration_digest"),
        )
        object.__setattr__(
            self,
            "invocation_digest",
            _digest_or_empty(self.invocation_digest, "invocation_digest"),
        )
        object.__setattr__(
            self,
            "selection_budget",
            _non_negative_int(
                self.selection_budget,
                "selection_budget",
                default=DEFAULT_SELECTION_BUDGET,
            ),
        )
        if self.selection_budget == 0:
            raise SecurityConstraintQueryError("selection_budget must be positive")
        if self.selection_budget > MAX_COLLECTION_ITEMS:
            raise SecurityConstraintQueryError(
                "selection_budget exceeds collection bound (unbounded selection rejected)"
            )
        for name in (
            "require_reviewed",
            "require_trusted_source",
            "require_provenance",
            "forbid_abstract_live_substitution",
            "require_evidence_binding",
        ):
            defaults = {
                "require_reviewed": True,
                "require_trusted_source": True,
                "require_provenance": True,
                "forbid_abstract_live_substitution": True,
                "require_evidence_binding": False,
            }
            object.__setattr__(
                self, name, _bool(getattr(self, name), name, default=defaults[name])
            )
        vocabs = self.known_extension_vocabularies
        if not vocabs:
            object.__setattr__(
                self,
                "known_extension_vocabularies",
                tuple(sorted(_DEFAULT_KNOWN_EXTENSION_VOCABS)),
            )
        else:
            object.__setattr__(
                self,
                "known_extension_vocabularies",
                _unique_sorted_ids(vocabs, "known_extension_vocabularies"),
            )
        object.__setattr__(
            self,
            "world_policy_kind",
            _enum_value(self.world_policy_kind, WorldPolicyKind, "world_policy_kind"),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SECURITY_CONSTRAINT_QUERY_SCHEMA_VERSION:
            raise SecurityConstraintQueryError(
                f"unsupported security constraint query schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "artifact_family": self.artifact_family.value,
            "as_of": self.as_of,
            "asset_id": self.asset_id,
            "capabilities": list(self.capabilities),
            "channel_id": self.channel_id,
            "data_class": self.data_class,
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "delegation_ids": list(self.delegation_ids),
            "effect": self.effect,
            "environment_id": self.environment_id,
            "environment_kind": self.environment_kind.value,
            "failure": self.failure,
            "filesystem": self.filesystem,
            "forbid_abstract_live_substitution": self.forbid_abstract_live_substitution,
            "interface": self.INTERFACE,
            "invocation_digest": self.invocation_digest,
            "known_extension_vocabularies": list(self.known_extension_vocabularies),
            "metadata": self.metadata.to_dict(),
            "network": self.network,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "principal_id": self.principal_id,
            "query_id": self.query_id,
            "require_evidence_binding": self.require_evidence_binding,
            "require_provenance": self.require_provenance,
            "require_reviewed": self.require_reviewed,
            "require_trusted_source": self.require_trusted_source,
            "required_authority": self.required_authority.value,
            "rollback": self.rollback,
            "sandbox_id": self.sandbox_id,
            "schema_version": self.schema_version,
            "selection_budget": self.selection_budget,
            "state": self.state,
            "threat_model_id": self.threat_model_id,
            "threat_model_version": self.threat_model_version,
            "trust_zone": self.trust_zone,
            "world_policy_kind": self.world_policy_kind.value,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=SECURITY_CONSTRAINT_QUERY_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityConstraintQuery":
        value = _mapping(value, "security constraint query")
        _reject_unknown(
            value,
            frozenset(
                {
                    "action",
                    "artifact_family",
                    "as_of",
                    "asset_id",
                    "capabilities",
                    "channel_id",
                    "data_class",
                    "declaration_digest",
                    "declaration_id",
                    "delegation_ids",
                    "effect",
                    "environment_id",
                    "environment_kind",
                    "failure",
                    "filesystem",
                    "forbid_abstract_live_substitution",
                    "interface",
                    "invocation_digest",
                    "known_extension_vocabularies",
                    "metadata",
                    "network",
                    "policy_id",
                    "policy_version",
                    "principal_id",
                    "query_id",
                    "require_evidence_binding",
                    "require_provenance",
                    "require_reviewed",
                    "require_trusted_source",
                    "required_authority",
                    "rollback",
                    "sandbox_id",
                    "schema_version",
                    "selection_budget",
                    "state",
                    "threat_model_id",
                    "threat_model_version",
                    "trust_zone",
                    "world_policy_kind",
                }
            ),
            "security constraint query",
        )
        interface = value.get("interface", SECURITY_CONSTRAINT_QUERY_INTERFACE)
        if interface != SECURITY_CONSTRAINT_QUERY_INTERFACE:
            raise SecurityConstraintQueryError(
                f"unknown security constraint query interface: {interface!r}"
            )
        family = value.get(
            "artifact_family", SecurityArtifactFamily.EVIDENCE_GATE.value
        )
        authority = value.get("required_authority")
        if authority is None:
            authority = _ARTIFACT_TO_AUTHORITY.get(
                str(family).lower().replace("-", "_"),
                AuthorityKind.EVIDENCE_READINESS,
            )
        return cls(
            query_id=value.get("query_id", ""),
            principal_id=value.get("principal_id", ""),
            as_of=value.get("as_of", ""),
            delegation_ids=tuple(value.get("delegation_ids", ())),
            capabilities=tuple(value.get("capabilities", ())),
            trust_zone=value.get("trust_zone", ""),
            asset_id=value.get("asset_id", ""),
            data_class=value.get("data_class", ""),
            channel_id=value.get("channel_id", ""),
            network=value.get("network", ""),
            filesystem=value.get("filesystem", ""),
            action=value.get("action", ""),
            state=value.get("state", ""),
            effect=value.get("effect", ""),
            failure=value.get("failure", ""),
            rollback=value.get("rollback", ""),
            sandbox_id=value.get("sandbox_id", ""),
            environment_kind=value.get("environment_kind", "unspecified"),
            environment_id=value.get("environment_id", ""),
            threat_model_id=value.get("threat_model_id", ""),
            threat_model_version=value.get("threat_model_version", ""),
            policy_id=value.get("policy_id", ""),
            policy_version=value.get("policy_version", ""),
            required_authority=authority,
            artifact_family=family,
            declaration_id=value.get("declaration_id", ""),
            declaration_digest=value.get("declaration_digest", ""),
            invocation_digest=value.get("invocation_digest", ""),
            selection_budget=value.get("selection_budget", DEFAULT_SELECTION_BUDGET),
            require_reviewed=value.get("require_reviewed", True),
            require_trusted_source=value.get("require_trusted_source", True),
            require_provenance=value.get("require_provenance", True),
            forbid_abstract_live_substitution=value.get(
                "forbid_abstract_live_substitution", True
            ),
            require_evidence_binding=value.get("require_evidence_binding", False),
            known_extension_vocabularies=tuple(
                value.get("known_extension_vocabularies", ())
            ),
            world_policy_kind=value.get(
                "world_policy_kind", WorldPolicyKind.CLOSED.value
            ),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", SECURITY_CONSTRAINT_QUERY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "SecurityConstraintQuery":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise SecurityConstraintQueryError(
                "security constraint query must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "security constraint query"))

    def select(
        self,
        candidates: Sequence[SecurityConstraintRecord | Mapping[str, Any]],
        *,
        evidence: Sequence[SecurityEvidenceBinding | Mapping[str, Any]] | None = None,
    ) -> "SecurityConstraintSelectionResult":
        """Select applicable Security constraints under hard filters and authority rules."""

        return select_applicable_security_constraints(
            self, candidates, evidence=evidence
        )


@dataclass(frozen=True, slots=True)
class SecurityApplicabilityEvidence:
    """``SecurityApplicabilityEvidence@1`` — Security hard-filter applicability receipt.

    Ranking alone never produces an ``APPLICABLE`` disposition.  Coverage gaps,
    conflicts, stale evidence, unknown extensions, and authority substitution
    remain explicit.
    """

    INTERFACE: ClassVar[str] = SECURITY_APPLICABILITY_EVIDENCE_INTERFACE

    evidence_id: str
    status: SecuritySelectionDisposition
    query_id: str
    query_digest: str
    selectors: tuple[ApplicabilitySelector, ...]
    matched_selector_ids: tuple[str, ...] = ()
    rejected_selector_ids: tuple[str, ...] = ()
    coverage_gaps: tuple[CoverageGap, ...] = ()
    assessments: tuple[SecurityConstraintAssessment, ...] = ()
    contradictions: tuple[SecurityContradiction, ...] = ()
    selected_constraint_ids: tuple[str, ...] = ()
    considered_count: int = 0
    hard_filtered_count: int = 0
    selected_count: int = 0
    selection_budget: int = 0
    selection_method: PremiseSelectionMethod = PremiseSelectionMethod.HARD_FILTER
    retrieval_rank_used_for_authority: bool = False
    authority_selection_keys: tuple[str, ...] = (
        "precedence",
        "priority",
        "constraint_id",
    )
    artifact_families_distinct: bool = True
    environment_substitution_rejected: bool = False
    shared_applicability: ApplicabilityEvidence | None = None
    selected_premises: SelectedPremiseSet | None = None
    notes: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SECURITY_APPLICABILITY_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self,
            "status",
            _enum_value(self.status, SecuritySelectionDisposition, "status"),
        )
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "query_digest", _digest_or_empty(self.query_digest, "query_digest")
        )
        selectors = tuple(
            item
            if isinstance(item, ApplicabilitySelector)
            else ApplicabilitySelector.from_dict(_mapping(item, "selector"))
            for item in _sequence(self.selectors, "selectors")
        )
        selector_ids = [item.selector_id for item in selectors]
        if len(selector_ids) != len(set(selector_ids)):
            raise SecurityConstraintQueryError("selector IDs must be unique")
        object.__setattr__(
            self,
            "selectors",
            tuple(sorted(selectors, key=lambda item: item.selector_id)),
        )
        known = {item.selector_id for item in self.selectors}
        object.__setattr__(
            self,
            "matched_selector_ids",
            _unique_sorted_ids(self.matched_selector_ids, "matched_selector_ids"),
        )
        object.__setattr__(
            self,
            "rejected_selector_ids",
            _unique_sorted_ids(self.rejected_selector_ids, "rejected_selector_ids"),
        )
        if set(self.matched_selector_ids) - known:
            raise SecurityConstraintQueryError(
                "matched_selector_ids reference unknown selectors"
            )
        if set(self.rejected_selector_ids) - known:
            raise SecurityConstraintQueryError(
                "rejected_selector_ids reference unknown selectors"
            )
        if set(self.matched_selector_ids) & set(self.rejected_selector_ids):
            raise SecurityConstraintQueryError(
                "selector IDs cannot be both matched and rejected"
            )
        gaps = tuple(
            item
            if isinstance(item, CoverageGap)
            else CoverageGap.from_dict(_mapping(item, "coverage gap"))
            for item in _sequence(self.coverage_gaps, "coverage_gaps")
        )
        object.__setattr__(
            self, "coverage_gaps", tuple(sorted(gaps, key=lambda item: item.gap_id))
        )
        assessments = tuple(
            item
            if isinstance(item, SecurityConstraintAssessment)
            else SecurityConstraintAssessment(**dict(item))  # type: ignore[arg-type]
            for item in _sequence(self.assessments, "assessments")
        )
        object.__setattr__(
            self,
            "assessments",
            tuple(sorted(assessments, key=lambda item: item.constraint_id)),
        )
        contradictions = tuple(
            item
            if isinstance(item, SecurityContradiction)
            else SecurityContradiction(**dict(item))  # type: ignore[arg-type]
            for item in _sequence(self.contradictions, "contradictions")
        )
        object.__setattr__(
            self,
            "contradictions",
            tuple(sorted(contradictions, key=lambda item: item.contradiction_id)),
        )
        object.__setattr__(
            self,
            "selected_constraint_ids",
            _unique_sorted_ids(
                self.selected_constraint_ids, "selected_constraint_ids"
            ),
        )
        for name in (
            "considered_count",
            "hard_filtered_count",
            "selected_count",
            "selection_budget",
        ):
            object.__setattr__(
                self, name, _non_negative_int(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "selection_method",
            _enum_value(
                self.selection_method, PremiseSelectionMethod, "selection_method"
            ),
        )
        object.__setattr__(
            self,
            "retrieval_rank_used_for_authority",
            _bool(
                self.retrieval_rank_used_for_authority,
                "retrieval_rank_used_for_authority",
            ),
        )
        if self.retrieval_rank_used_for_authority:
            raise SecurityConstraintQueryError(
                "retrieval rank must never select authority"
            )
        keys = tuple(
            _identifier(item, "authority_selection_keys")
            for item in _sequence(
                self.authority_selection_keys, "authority_selection_keys"
            )
        )
        if "retrieval_rank" in keys or "retrieval_score" in keys:
            raise SecurityConstraintQueryError(
                "authority_selection_keys must not include retrieval rank/score"
            )
        object.__setattr__(self, "authority_selection_keys", keys)
        object.__setattr__(
            self,
            "artifact_families_distinct",
            _bool(
                self.artifact_families_distinct,
                "artifact_families_distinct",
                default=True,
            ),
        )
        if not self.artifact_families_distinct:
            raise SecurityConstraintQueryError(
                "theorem/monitor/evidence_gate/policy artifacts must remain distinct"
            )
        object.__setattr__(
            self,
            "environment_substitution_rejected",
            _bool(
                self.environment_substitution_rejected,
                "environment_substitution_rejected",
            ),
        )
        if self.shared_applicability is not None and not isinstance(
            self.shared_applicability, ApplicabilityEvidence
        ):
            if isinstance(self.shared_applicability, Mapping):
                object.__setattr__(
                    self,
                    "shared_applicability",
                    ApplicabilityEvidence.from_dict(self.shared_applicability),
                )
            else:
                raise SecurityConstraintQueryError(
                    "shared_applicability must be ApplicabilityEvidence"
                )
        if self.selected_premises is not None and not isinstance(
            self.selected_premises, SelectedPremiseSet
        ):
            if isinstance(self.selected_premises, Mapping):
                object.__setattr__(
                    self,
                    "selected_premises",
                    SelectedPremiseSet.from_dict(self.selected_premises),
                )
            else:
                raise SecurityConstraintQueryError(
                    "selected_premises must be SelectedPremiseSet"
                )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SECURITY_APPLICABILITY_EVIDENCE_SCHEMA_VERSION:
            raise SecurityConstraintQueryError(
                f"unsupported security applicability evidence schema: {self.schema_version!r}"
            )
        if self.status is SecuritySelectionDisposition.APPLICABLE:
            if self.rejected_selector_ids:
                raise SecurityConstraintQueryError(
                    "APPLICABLE evidence cannot retain rejected selectors"
                )
            if self.coverage_gaps:
                raise SecurityConstraintQueryError(
                    "APPLICABLE evidence cannot retain coverage gaps"
                )
            unresolved = [item for item in self.contradictions if not item.resolved]
            if unresolved:
                raise SecurityConstraintQueryError(
                    "APPLICABLE evidence cannot retain unresolved contradictions"
                )
        if (
            self.status is SecuritySelectionDisposition.COVERAGE_GAP
            and not self.coverage_gaps
        ):
            raise SecurityConstraintQueryError(
                "COVERAGE_GAP status requires at least one coverage gap"
            )

    @property
    def grants_legal_compliance(self) -> bool:
        return False

    @property
    def grants_execution_authority(self) -> bool:
        return False

    @property
    def allows_action(self) -> bool:
        return self.status is SecuritySelectionDisposition.APPLICABLE

    @property
    def abstains(self) -> bool:
        return self.status in {
            SecuritySelectionDisposition.ABSTAIN,
            SecuritySelectionDisposition.REVIEW_REQUIRED,
            SecuritySelectionDisposition.CONFLICT,
            SecuritySelectionDisposition.INDETERMINATE,
            SecuritySelectionDisposition.COVERAGE_GAP,
            SecuritySelectionDisposition.UNSUPPORTED,
            SecuritySelectionDisposition.STALE,
            SecuritySelectionDisposition.AUTHORITY_MISMATCH,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_families_distinct": True,
            "assessments": [item.to_dict() for item in self.assessments],
            "authority_selection_keys": list(self.authority_selection_keys),
            "considered_count": self.considered_count,
            "contradictions": [item.to_dict() for item in self.contradictions],
            "coverage_gaps": [item.to_dict() for item in self.coverage_gaps],
            "environment_substitution_rejected": self.environment_substitution_rejected,
            "evidence_id": self.evidence_id,
            "grants_execution_authority": False,
            "grants_legal_compliance": False,
            "hard_filtered_count": self.hard_filtered_count,
            "interface": self.INTERFACE,
            "matched_selector_ids": list(self.matched_selector_ids),
            "metadata": self.metadata.to_dict(),
            "notes": self.notes,
            "query_digest": self.query_digest,
            "query_id": self.query_id,
            "rejected_selector_ids": list(self.rejected_selector_ids),
            "retrieval_rank_used_for_authority": False,
            "schema_version": self.schema_version,
            "selected_constraint_ids": list(self.selected_constraint_ids),
            "selected_count": self.selected_count,
            "selected_premises": (
                self.selected_premises.to_dict()
                if self.selected_premises is not None
                else None
            ),
            "selection_budget": self.selection_budget,
            "selection_method": self.selection_method.value,
            "selectors": [item.to_dict() for item in self.selectors],
            "shared_applicability": (
                self.shared_applicability.to_dict()
                if self.shared_applicability is not None
                else None
            ),
            "status": self.status.value,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=SECURITY_APPLICABILITY_EVIDENCE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
            collection_semantics={
                "/selectors": "set-like",
                "/matched_selector_ids": "set-like",
                "/rejected_selector_ids": "set-like",
                "/coverage_gaps": "set-like",
                "/assessments": "set-like",
                "/contradictions": "set-like",
                "/selected_constraint_ids": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityApplicabilityEvidence":
        value = _mapping(value, "security applicability evidence")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_families_distinct",
                    "assessments",
                    "authority_selection_keys",
                    "considered_count",
                    "contradictions",
                    "coverage_gaps",
                    "environment_substitution_rejected",
                    "evidence_id",
                    "grants_execution_authority",
                    "grants_legal_compliance",
                    "hard_filtered_count",
                    "interface",
                    "matched_selector_ids",
                    "metadata",
                    "notes",
                    "query_digest",
                    "query_id",
                    "rejected_selector_ids",
                    "retrieval_rank_used_for_authority",
                    "schema_version",
                    "selected_constraint_ids",
                    "selected_count",
                    "selected_premises",
                    "selection_budget",
                    "selection_method",
                    "selectors",
                    "shared_applicability",
                    "status",
                }
            ),
            "security applicability evidence",
        )
        interface = value.get("interface", SECURITY_APPLICABILITY_EVIDENCE_INTERFACE)
        if interface != SECURITY_APPLICABILITY_EVIDENCE_INTERFACE:
            raise SecurityConstraintQueryError(
                f"unknown security applicability evidence interface: {interface!r}"
            )
        if value.get("retrieval_rank_used_for_authority"):
            raise SecurityConstraintQueryError(
                "retrieval rank must never select authority"
            )
        if value.get("artifact_families_distinct") is False:
            raise SecurityConstraintQueryError(
                "theorem/monitor/evidence_gate/policy artifacts must remain distinct"
            )
        shared = value.get("shared_applicability")
        premises = value.get("selected_premises")
        assessments_raw = value.get("assessments", ())
        assessments: list[SecurityConstraintAssessment] = []
        for item in _sequence(assessments_raw, "assessments"):
            if isinstance(item, SecurityConstraintAssessment):
                assessments.append(item)
            else:
                mapping = _mapping(item, "assessment")
                record = mapping.get("record")
                assessments.append(
                    SecurityConstraintAssessment(
                        constraint_id=mapping.get("constraint_id", ""),
                        disposition=mapping.get("disposition", ""),
                        active=bool(mapping.get("active", False)),
                        reason_codes=tuple(mapping.get("reason_codes", ())),
                        matched_dimensions=tuple(
                            mapping.get("matched_dimensions", ())
                        ),
                        rejected_dimensions=tuple(
                            mapping.get("rejected_dimensions", ())
                        ),
                        defeated_by=tuple(mapping.get("defeated_by", ())),
                        conflicts_with=tuple(mapping.get("conflicts_with", ())),
                        retrieval_rank=mapping.get("retrieval_rank"),
                        precedence=int(mapping.get("precedence", 0)),
                        priority=int(mapping.get("priority", 0)),
                        effect=mapping.get(
                            "effect", SecurityConstraintEffect.UNSPECIFIED.value
                        ),
                        artifact_family=mapping.get(
                            "artifact_family",
                            SecurityArtifactFamily.EVIDENCE_GATE.value,
                        ),
                        record=(
                            SecurityConstraintRecord.from_dict(record)
                            if isinstance(record, Mapping)
                            else None
                        ),
                    )
                )
        contradictions_raw = value.get("contradictions", ())
        contradictions: list[SecurityContradiction] = []
        for item in _sequence(contradictions_raw, "contradictions"):
            if isinstance(item, SecurityContradiction):
                contradictions.append(item)
            else:
                mapping = _mapping(item, "contradiction")
                contradictions.append(
                    SecurityContradiction(
                        contradiction_id=mapping.get("contradiction_id", ""),
                        constraint_ids=tuple(mapping.get("constraint_ids", ())),
                        kind=mapping.get("kind", "conflict"),
                        reason_codes=tuple(mapping.get("reason_codes", ())),
                        resolved=bool(mapping.get("resolved", False)),
                        winning_constraint_id=mapping.get(
                            "winning_constraint_id", ""
                        ),
                        notes=mapping.get("notes", ""),
                    )
                )
        return cls(
            evidence_id=value.get("evidence_id", ""),
            status=value.get("status", ""),
            query_id=value.get("query_id", ""),
            query_digest=value.get("query_digest", ""),
            selectors=tuple(
                ApplicabilitySelector.from_dict(_mapping(item, "selector"))
                for item in _sequence(value.get("selectors", ()), "selectors")
            ),
            matched_selector_ids=tuple(value.get("matched_selector_ids", ())),
            rejected_selector_ids=tuple(value.get("rejected_selector_ids", ())),
            coverage_gaps=tuple(
                CoverageGap.from_dict(_mapping(item, "coverage gap"))
                for item in _sequence(value.get("coverage_gaps", ()), "coverage_gaps")
            ),
            assessments=tuple(assessments),
            contradictions=tuple(contradictions),
            selected_constraint_ids=tuple(value.get("selected_constraint_ids", ())),
            considered_count=int(value.get("considered_count", 0)),
            hard_filtered_count=int(value.get("hard_filtered_count", 0)),
            selected_count=int(value.get("selected_count", 0)),
            selection_budget=int(value.get("selection_budget", 0)),
            selection_method=value.get(
                "selection_method", PremiseSelectionMethod.HARD_FILTER.value
            ),
            retrieval_rank_used_for_authority=False,
            authority_selection_keys=tuple(
                value.get(
                    "authority_selection_keys",
                    ("precedence", "priority", "constraint_id"),
                )
            ),
            artifact_families_distinct=True,
            environment_substitution_rejected=bool(
                value.get("environment_substitution_rejected", False)
            ),
            shared_applicability=(
                ApplicabilityEvidence.from_dict(_mapping(shared, "shared"))
                if shared is not None
                else None
            ),
            selected_premises=(
                SelectedPremiseSet.from_dict(_mapping(premises, "premises"))
                if premises is not None
                else None
            ),
            notes=value.get("notes", ""),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", SECURITY_APPLICABILITY_EVIDENCE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SecurityConstraintSelectionResult:
    """Complete selection result: assessments, evidence, and selected records."""

    disposition: SecuritySelectionDisposition
    query: SecurityConstraintQuery
    evidence: SecurityApplicabilityEvidence
    assessments: tuple[SecurityConstraintAssessment, ...]
    selected: tuple[SecurityConstraintRecord, ...]
    contradictions: tuple[SecurityContradiction, ...]
    schema_version: str = SECURITY_CONSTRAINT_SELECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum_value(
                self.disposition, SecuritySelectionDisposition, "disposition"
            ),
        )
        if not isinstance(self.query, SecurityConstraintQuery):
            raise SecurityConstraintQueryError("query must be SecurityConstraintQuery")
        if not isinstance(self.evidence, SecurityApplicabilityEvidence):
            raise SecurityConstraintQueryError(
                "evidence must be SecurityApplicabilityEvidence"
            )
        object.__setattr__(
            self,
            "assessments",
            tuple(sorted(self.assessments, key=lambda item: item.constraint_id)),
        )
        object.__setattr__(
            self,
            "selected",
            tuple(sorted(self.selected, key=lambda item: item.constraint_id)),
        )
        object.__setattr__(
            self,
            "contradictions",
            tuple(sorted(self.contradictions, key=lambda item: item.contradiction_id)),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SECURITY_CONSTRAINT_SELECTION_SCHEMA_VERSION:
            raise SecurityConstraintQueryError(
                f"unsupported selection schema: {self.schema_version!r}"
            )

    @property
    def applicable(self) -> tuple[SecurityConstraintRecord, ...]:
        return self.selected

    @property
    def abstains(self) -> bool:
        return self.evidence.abstains

    @property
    def allows_action(self) -> bool:
        return self.evidence.allows_action

    @property
    def grants_legal_compliance(self) -> bool:
        return False

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessments": [item.to_dict() for item in self.assessments],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "disposition": self.disposition.value,
            "evidence": self.evidence.to_dict(),
            "grants_execution_authority": False,
            "grants_legal_compliance": False,
            "query": self.query.to_dict(),
            "schema_version": self.schema_version,
            "selected": [item.to_dict() for item in self.selected],
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=SECURITY_CONSTRAINT_SELECTION_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest


# ---------------------------------------------------------------------------
# Selection engine
# ---------------------------------------------------------------------------


def _to_shared_status(status: SecuritySelectionDisposition) -> ApplicabilityStatus:
    return {
        SecuritySelectionDisposition.APPLICABLE: ApplicabilityStatus.APPLICABLE,
        SecuritySelectionDisposition.NOT_APPLICABLE: ApplicabilityStatus.NOT_APPLICABLE,
        SecuritySelectionDisposition.CONFLICT: ApplicabilityStatus.CONFLICT,
        SecuritySelectionDisposition.INDETERMINATE: ApplicabilityStatus.INDETERMINATE,
        SecuritySelectionDisposition.COVERAGE_GAP: ApplicabilityStatus.COVERAGE_GAP,
        SecuritySelectionDisposition.REVIEW_REQUIRED: ApplicabilityStatus.INDETERMINATE,
        SecuritySelectionDisposition.ABSTAIN: ApplicabilityStatus.INDETERMINATE,
        SecuritySelectionDisposition.UNSUPPORTED: ApplicabilityStatus.UNSUPPORTED,
        SecuritySelectionDisposition.STALE: ApplicabilityStatus.INDETERMINATE,
        SecuritySelectionDisposition.AUTHORITY_MISMATCH: ApplicabilityStatus.UNSUPPORTED,
    }[status]


def _build_query_selectors(
    query: SecurityConstraintQuery,
) -> tuple[ApplicabilitySelector, ...]:
    specs: list[tuple[str, str, str, bool]] = [
        ("sel:principal", "principal", query.principal_id, True),
        ("sel:as_of", "freshness", query.as_of, True),
        (
            "sel:result_authority",
            "result_authority",
            query.required_authority.value,
            True,
        ),
        ("sel:artifact_family", "result_authority", query.artifact_family.value, True),
    ]
    optional = (
        ("sel:trust_zone", "trust_zone", query.trust_zone),
        ("sel:asset", "asset", query.asset_id),
        ("sel:data_class", "data_class", query.data_class),
        ("sel:channel", "channel", query.channel_id),
        ("sel:network", "network", query.network),
        ("sel:filesystem", "filesystem", query.filesystem),
        ("sel:action", "action", query.action),
        ("sel:state", "state", query.state),
        ("sel:effect", "effect", query.effect),
        ("sel:failure", "failure", query.failure),
        ("sel:rollback", "rollback", query.rollback),
        ("sel:sandbox", "sandbox", query.sandbox_id),
        ("sel:environment", "environment", query.environment_kind.value),
        ("sel:threat_model", "threat_model", query.threat_model_id),
        ("sel:policy_version", "policy_version", query.policy_version or query.policy_id),
    )
    for selector_id, dimension, value in optional:
        if value and value != SecurityEnvironmentKind.UNSPECIFIED.value:
            specs.append((selector_id, dimension, value, True))
    for item in query.delegation_ids:
        specs.append((f"sel:delegation:{item}", "delegation", item, True))
    for item in query.capabilities:
        specs.append((f"sel:capability:{item}", "capability", item, True))
    return tuple(
        ApplicabilitySelector(
            selector_id=selector_id,
            dimension=dimension,
            value=str(value),
            required=required,
            source_ref_ids=("source:security-constraint-query",),
        )
        for selector_id, dimension, value, required in specs
    )


def _is_fresh(
    *,
    as_of: datetime,
    observed_at: datetime | None,
    max_age_seconds: int | None,
) -> tuple[bool | None, str]:
    if max_age_seconds is None:
        return None, ""
    if observed_at is None:
        return None, "missing_evidence_timestamp"
    age = (as_of - observed_at).total_seconds()
    if age < 0:
        return False, "evidence_from_future"
    if age > max_age_seconds:
        return False, "evidence_stale"
    return True, "evidence_fresh"


def _hard_filter_record(
    query: SecurityConstraintQuery,
    record: SecurityConstraintRecord,
    *,
    evidence_by_id: Mapping[str, SecurityEvidenceBinding],
    known_vocabs: frozenset[str],
) -> SecurityConstraintAssessment:
    reasons: list[str] = []
    matched: list[str] = []
    rejected: list[str] = []
    disposition = SecurityConstraintDisposition.APPLICABLE
    active = True

    def fail(
        new_disposition: SecurityConstraintDisposition,
        reason: str,
        dimension: str,
    ) -> None:
        nonlocal disposition, active
        if disposition is SecurityConstraintDisposition.APPLICABLE or (
            disposition is SecurityConstraintDisposition.INDETERMINATE
            and new_disposition
            not in {
                SecurityConstraintDisposition.INDETERMINATE,
                SecurityConstraintDisposition.REVIEW_REQUIRED,
            }
        ):
            disposition = new_disposition
        elif disposition is SecurityConstraintDisposition.APPLICABLE:
            disposition = new_disposition
        # Prefer hard rejects over indeterminate when both apply.
        hard = {
            SecurityConstraintDisposition.NOT_APPLICABLE,
            SecurityConstraintDisposition.STALE,
            SecurityConstraintDisposition.MISMATCHED,
            SecurityConstraintDisposition.UNKNOWN_EXTENSION,
            SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
            SecurityConstraintDisposition.AUTHORITY_MISMATCH,
            SecurityConstraintDisposition.TAINTED,
        }
        if new_disposition in hard:
            disposition = new_disposition
        active = False
        reasons.append(reason)
        if dimension not in rejected:
            rejected.append(dimension)

    # Provenance / grounding / taint — fail closed before scope matching.
    if not record.source_ref_ids:
        fail(
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            "missing_source_refs",
            "provenance",
        )
    else:
        matched.append("provenance")

    if query.require_provenance and not record.provenance_ids:
        fail(
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            "missing_provenance",
            "provenance",
        )

    if record.premise_taint is SecurityPremiseTaintStatus.TAINTED:
        fail(
            SecurityConstraintDisposition.TAINTED,
            "premise_tainted",
            "premise_taint",
        )
    elif record.premise_taint is SecurityPremiseTaintStatus.UNKNOWN:
        fail(
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            "premise_taint_unknown",
            "premise_taint",
        )
    elif record.premise_taint is SecurityPremiseTaintStatus.UNREVIEWED:
        fail(
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            "premise_unreviewed",
            "premise_taint",
        )
    else:
        matched.append("premise_taint")

    if query.require_trusted_source and not record.trusted_source:
        fail(
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            "untrusted_source",
            "provenance",
        )

    if query.require_reviewed and not record.reviewed:
        fail(
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            "not_reviewed",
            "provenance",
        )

    # Unknown extensions fail closed.
    for vocab in record.extension_vocabularies:
        if vocab not in known_vocabs:
            fail(
                SecurityConstraintDisposition.UNKNOWN_EXTENSION,
                f"unknown_extension_vocabulary:{vocab}",
                "extension",
            )
    if record.extension_ids and not record.extension_vocabularies:
        fail(
            SecurityConstraintDisposition.UNKNOWN_EXTENSION,
            "extension_ids_without_vocabulary",
            "extension",
        )
    if record.extension_vocabularies and disposition is SecurityConstraintDisposition.APPLICABLE:
        matched.append("extension")

    # Declaration binding.
    if (
        query.declaration_id
        and record.declaration_id
        and query.declaration_id != record.declaration_id
    ):
        fail(
            SecurityConstraintDisposition.MISMATCHED,
            "declaration_id_mismatch",
            "declaration",
        )
    if (
        query.declaration_digest
        and record.declaration_digest
        and query.declaration_digest != record.declaration_digest
    ):
        fail(
            SecurityConstraintDisposition.MISMATCHED,
            "declaration_digest_mismatch",
            "declaration",
        )
    elif record.declaration_digest or record.declaration_id:
        if disposition is SecurityConstraintDisposition.APPLICABLE:
            matched.append("declaration")

    # Result authority / artifact family — no substitution.
    if record.required_authority is not query.required_authority:
        fail(
            SecurityConstraintDisposition.AUTHORITY_MISMATCH,
            "result_authority_mismatch",
            "result_authority",
        )
    elif record.artifact_family is not query.artifact_family:
        fail(
            SecurityConstraintDisposition.AUTHORITY_MISMATCH,
            "artifact_family_mismatch",
            "result_authority",
        )
    else:
        if disposition is SecurityConstraintDisposition.APPLICABLE:
            matched.append("result_authority")

    # Environment boundary.
    env_ok, env_reason = _environments_compatible(
        record.environment_kind,
        query.environment_kind,
        forbid_substitution=query.forbid_abstract_live_substitution,
    )
    if not env_ok:
        fail(
            SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
            env_reason or "environment_mismatch",
            "environment",
        )
    elif env_reason and disposition is SecurityConstraintDisposition.APPLICABLE:
        matched.append("environment")

    if (
        disposition is SecurityConstraintDisposition.APPLICABLE
        and query.environment_id
        and record.environment_ids
        and query.environment_id not in record.environment_ids
    ):
        fail(
            SecurityConstraintDisposition.NOT_APPLICABLE,
            "environment_id_mismatch",
            "environment",
        )

    # Scope dimensions (single-value query fields).
    single_scope = (
        ("principal", record.principals, query.principal_id, ()),
        ("trust_zone", record.trust_zones, query.trust_zone, ()),
        ("asset", record.assets, query.asset_id, ()),
        ("data_class", record.data_classes, query.data_class, ()),
        ("channel", record.channels, query.channel_id, ()),
        ("network", record.networks, query.network, ()),
        ("filesystem", record.filesystems, query.filesystem, ()),
        ("action", record.actions, query.action, ()),
        ("state", record.states, query.state, ()),
        ("effect", record.effects, query.effect, ()),
        ("failure", record.failures, query.failure, ()),
        ("rollback", record.rollbacks, query.rollback, ()),
        ("sandbox", record.sandbox_ids, query.sandbox_id, ()),
    )
    multi_scope = (
        ("delegation", record.delegation_ids, "", query.delegation_ids),
        ("capability", record.capabilities, "", query.capabilities),
    )

    if disposition in {
        SecurityConstraintDisposition.APPLICABLE,
        SecurityConstraintDisposition.INDETERMINATE,
        SecurityConstraintDisposition.REVIEW_REQUIRED,
    }:
        for dimension, allowed, query_value, query_values in (*single_scope, *multi_scope):
            if disposition not in {
                SecurityConstraintDisposition.APPLICABLE,
                SecurityConstraintDisposition.INDETERMINATE,
            }:
                # Keep collecting reasons for review-required records only on hard mismatches.
                if disposition is not SecurityConstraintDisposition.REVIEW_REQUIRED:
                    break
            result = _scope_contains(
                allowed, query_value, query_values=query_values
            )
            if result is True:
                matched.append(dimension)
            elif result is False:
                fail(
                    SecurityConstraintDisposition.NOT_APPLICABLE,
                    f"{dimension}_mismatch",
                    dimension,
                )
            else:
                # Open/missing selector on the record.
                bound = bool(query_value) or bool(query_values)
                if dimension == "principal":
                    fail(
                        SecurityConstraintDisposition.INDETERMINATE,
                        "missing_principal_selector",
                        dimension,
                    )
                elif bound and query.world_policy_kind is WorldPolicyKind.CLOSED:
                    if record.mandatory:
                        fail(
                            SecurityConstraintDisposition.INDETERMINATE,
                            f"missing_{dimension}_selector",
                            dimension,
                        )

    # Threat model / policy version.
    if disposition is SecurityConstraintDisposition.APPLICABLE:
        if query.threat_model_id and record.threat_model_id:
            if query.threat_model_id != record.threat_model_id:
                fail(
                    SecurityConstraintDisposition.MISMATCHED,
                    "threat_model_id_mismatch",
                    "threat_model",
                )
            elif (
                query.threat_model_version
                and record.threat_model_version
                and query.threat_model_version != record.threat_model_version
            ):
                fail(
                    SecurityConstraintDisposition.MISMATCHED,
                    "threat_model_version_mismatch",
                    "threat_model",
                )
            else:
                matched.append("threat_model")
        elif query.threat_model_id and not record.threat_model_id and record.mandatory:
            fail(
                SecurityConstraintDisposition.INDETERMINATE,
                "missing_threat_model_selector",
                "threat_model",
            )

        if query.policy_id and record.policy_id:
            if query.policy_id != record.policy_id:
                fail(
                    SecurityConstraintDisposition.MISMATCHED,
                    "policy_id_mismatch",
                    "policy_version",
                )
            elif (
                query.policy_version
                and record.policy_version
                and query.policy_version != record.policy_version
            ):
                fail(
                    SecurityConstraintDisposition.MISMATCHED,
                    "policy_version_mismatch",
                    "policy_version",
                )
            else:
                matched.append("policy_version")
        elif query.policy_version and record.policy_version:
            if query.policy_version != record.policy_version:
                fail(
                    SecurityConstraintDisposition.MISMATCHED,
                    "policy_version_mismatch",
                    "policy_version",
                )
            else:
                matched.append("policy_version")

    # Evidence bindings: freshness + digest match.
    as_of = _parse_datetime(query.as_of)
    assert as_of is not None
    if disposition is SecurityConstraintDisposition.APPLICABLE:
        if record.evidence_ids or record.evidence_digests or query.require_evidence_binding:
            if not record.evidence_ids and query.require_evidence_binding:
                fail(
                    SecurityConstraintDisposition.INDETERMINATE,
                    "missing_evidence_binding",
                    "freshness",
                )
            for evidence_id in record.evidence_ids:
                binding = evidence_by_id.get(evidence_id)
                if binding is None:
                    fail(
                        SecurityConstraintDisposition.INDETERMINATE,
                        f"unresolved_evidence:{evidence_id}",
                        "freshness",
                    )
                    continue
                # Authority family of evidence must match constraint/query.
                if binding.authority_kind is not query.required_authority:
                    fail(
                        SecurityConstraintDisposition.AUTHORITY_MISMATCH,
                        f"evidence_authority_mismatch:{evidence_id}",
                        "result_authority",
                    )
                    continue
                if binding.artifact_family is not query.artifact_family:
                    fail(
                        SecurityConstraintDisposition.AUTHORITY_MISMATCH,
                        f"evidence_artifact_family_mismatch:{evidence_id}",
                        "result_authority",
                    )
                    continue
                env_ok, env_reason = _environments_compatible(
                    binding.environment_kind,
                    query.environment_kind,
                    forbid_substitution=query.forbid_abstract_live_substitution,
                )
                if not env_ok:
                    fail(
                        SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
                        f"{env_reason}:{evidence_id}",
                        "environment",
                    )
                    continue
                if record.evidence_digests and binding.content_digest:
                    if binding.content_digest not in record.evidence_digests:
                        fail(
                            SecurityConstraintDisposition.MISMATCHED,
                            f"evidence_digest_mismatch:{evidence_id}",
                            "freshness",
                        )
                        continue
                max_age = binding.max_age_seconds
                if max_age is None:
                    max_age = record.max_evidence_age_seconds
                observed = _parse_datetime(binding.observed_at)
                fresh, fresh_reason = _is_fresh(
                    as_of=as_of,
                    observed_at=observed,
                    max_age_seconds=max_age,
                )
                if fresh is False:
                    fail(
                        SecurityConstraintDisposition.STALE,
                        f"{fresh_reason}:{evidence_id}",
                        "freshness",
                    )
                elif fresh is None and max_age is not None:
                    fail(
                        SecurityConstraintDisposition.INDETERMINATE,
                        f"{fresh_reason or 'freshness_indeterminate'}:{evidence_id}",
                        "freshness",
                    )
                elif fresh is True:
                    matched.append("freshness")
            if (
                disposition is SecurityConstraintDisposition.APPLICABLE
                and "freshness" not in matched
                and not record.evidence_ids
                and record.evidence_digests
            ):
                # Digests declared without bound evidence when binding required.
                if query.require_evidence_binding:
                    fail(
                        SecurityConstraintDisposition.INDETERMINATE,
                        "evidence_digests_unbound",
                        "freshness",
                    )
        else:
            # No evidence constraint on the record — freshness dimension N/A.
            pass

    if not reasons and disposition is SecurityConstraintDisposition.APPLICABLE:
        reasons.append("hard_filters_passed")

    return SecurityConstraintAssessment(
        constraint_id=record.constraint_id,
        disposition=disposition,
        active=active and disposition is SecurityConstraintDisposition.APPLICABLE,
        reason_codes=tuple(reasons),
        matched_dimensions=tuple(sorted(set(matched))),
        rejected_dimensions=tuple(sorted(set(rejected))),
        retrieval_rank=record.retrieval_rank,
        precedence=record.precedence,
        priority=record.priority,
        effect=record.effect,
        artifact_family=record.artifact_family,
        record=record,
    )


def _add_assessment_reason(
    assessment: SecurityConstraintAssessment, *reasons: str, **updates: Any
) -> SecurityConstraintAssessment:
    merged = tuple(sorted(set((*assessment.reason_codes, *reasons))))
    return replace(assessment, reason_codes=merged, **updates)


def _opposed_effects(
    left: SecurityConstraintEffect, right: SecurityConstraintEffect
) -> bool:
    return frozenset({left.value, right.value}) in _OPPOSED_EFFECT_PAIRS


def _authority_sort_key(
    assessment: SecurityConstraintAssessment,
) -> tuple[int, int, str]:
    """Higher precedence and priority win; ID is a stable tie-break only.

    Retrieval rank is intentionally absent.
    """

    return (-assessment.precedence, -assessment.priority, assessment.constraint_id)


def _resolve_relationships(
    assessments: dict[str, SecurityConstraintAssessment],
    records: Mapping[str, SecurityConstraintRecord],
) -> tuple[dict[str, SecurityConstraintAssessment], list[SecurityContradiction]]:
    contradictions: list[SecurityContradiction] = []

    # Express supersession.
    for winner_id, assessment in tuple(assessments.items()):
        if not assessment.active:
            continue
        record = records[winner_id]
        for target_id in record.supersedes:
            target = assessments.get(target_id)
            if target is None:
                assessments[winner_id] = _add_assessment_reason(
                    replace(
                        assessments[winner_id],
                        disposition=SecurityConstraintDisposition.INDETERMINATE,
                        active=False,
                    ),
                    "superseded_constraint_missing",
                )
            elif target.active or target.disposition is SecurityConstraintDisposition.APPLICABLE:
                assessments[target_id] = _add_assessment_reason(
                    replace(
                        target,
                        disposition=SecurityConstraintDisposition.SUPERSEDED,
                        active=False,
                        defeated_by=tuple(
                            sorted(set((*target.defeated_by, winner_id)))
                        ),
                    ),
                    "express_supersession",
                )
                contradictions.append(
                    SecurityContradiction(
                        contradiction_id=f"supersession:{winner_id}:{target_id}",
                        constraint_ids=(winner_id, target_id),
                        kind="supersession",
                        reason_codes=("express_supersession",),
                        resolved=True,
                        winning_constraint_id=winner_id,
                    )
                )

    def active_items() -> list[SecurityConstraintAssessment]:
        return [
            assessments[key]
            for key in sorted(assessments)
            if assessments[key].active
        ]

    # Competing constraints on the same applicability key.
    by_key: dict[str, list[SecurityConstraintAssessment]] = {}
    for item in active_items():
        record = records[item.constraint_id]
        by_key.setdefault(record.applicability_key, []).append(item)

    for _key, group in sorted(by_key.items()):
        if len(group) < 2:
            continue
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                left_rec = records[left.constraint_id]
                right_rec = records[right.constraint_id]
                explicit = (
                    right.constraint_id in left_rec.conflicts_with
                    or left.constraint_id in right_rec.conflicts_with
                )
                opposed = _opposed_effects(left.effect, right.effect)
                if not (explicit or opposed):
                    continue
                if left.precedence != right.precedence:
                    winner, loser = (
                        (left, right)
                        if left.precedence > right.precedence
                        else (right, left)
                    )
                    assessments[loser.constraint_id] = _add_assessment_reason(
                        replace(
                            loser,
                            disposition=SecurityConstraintDisposition.SUPERSEDED,
                            active=False,
                            defeated_by=tuple(
                                sorted(
                                    set((*loser.defeated_by, winner.constraint_id))
                                )
                            ),
                        ),
                        "higher_precedence_constraint",
                    )
                    contradictions.append(
                        SecurityContradiction(
                            contradiction_id=(
                                f"precedence:{winner.constraint_id}:{loser.constraint_id}"
                            ),
                            constraint_ids=(
                                winner.constraint_id,
                                loser.constraint_id,
                            ),
                            kind="precedence",
                            reason_codes=("higher_precedence_constraint",),
                            resolved=True,
                            winning_constraint_id=winner.constraint_id,
                        )
                    )
                elif left.priority != right.priority:
                    winner, loser = (
                        (left, right)
                        if left.priority > right.priority
                        else (right, left)
                    )
                    assessments[loser.constraint_id] = _add_assessment_reason(
                        replace(
                            loser,
                            disposition=SecurityConstraintDisposition.SUPERSEDED,
                            active=False,
                            defeated_by=tuple(
                                sorted(
                                    set((*loser.defeated_by, winner.constraint_id))
                                )
                            ),
                        ),
                        "higher_priority_constraint",
                    )
                    contradictions.append(
                        SecurityContradiction(
                            contradiction_id=(
                                f"priority:{winner.constraint_id}:{loser.constraint_id}"
                            ),
                            constraint_ids=(
                                winner.constraint_id,
                                loser.constraint_id,
                            ),
                            kind="priority",
                            reason_codes=("higher_priority_constraint",),
                            resolved=True,
                            winning_constraint_id=winner.constraint_id,
                        )
                    )
                else:
                    for item in (left, right):
                        peer = (
                            right.constraint_id
                            if item.constraint_id == left.constraint_id
                            else left.constraint_id
                        )
                        assessments[item.constraint_id] = _add_assessment_reason(
                            replace(
                                assessments[item.constraint_id],
                                disposition=SecurityConstraintDisposition.CONFLICTING,
                                active=False,
                                conflicts_with=tuple(
                                    sorted(
                                        set(
                                            (
                                                *assessments[
                                                    item.constraint_id
                                                ].conflicts_with,
                                                peer,
                                            )
                                        )
                                    )
                                ),
                            ),
                            "unresolved_equal_precedence_conflict",
                        )
                    contradictions.append(
                        SecurityContradiction(
                            contradiction_id=(
                                f"conflict:{left.constraint_id}:{right.constraint_id}"
                            ),
                            constraint_ids=(left.constraint_id, right.constraint_id),
                            kind="unresolved_conflict",
                            reason_codes=("unresolved_equal_precedence_conflict",),
                            resolved=False,
                        )
                    )

    return assessments, contradictions


def _overall_disposition(
    assessments: Sequence[SecurityConstraintAssessment],
    contradictions: Sequence[SecurityContradiction],
    coverage_gaps: Sequence[CoverageGap],
    *,
    considered_count: int,
) -> SecuritySelectionDisposition:
    if considered_count == 0 or coverage_gaps:
        return SecuritySelectionDisposition.COVERAGE_GAP

    active = [item for item in assessments if item.active]
    dispositions = {item.disposition for item in assessments}

    if any(not item.resolved for item in contradictions) or (
        SecurityConstraintDisposition.CONFLICTING in dispositions
    ):
        return SecuritySelectionDisposition.CONFLICT

    if SecurityConstraintDisposition.AUTHORITY_MISMATCH in dispositions and not active:
        return SecuritySelectionDisposition.AUTHORITY_MISMATCH

    if SecurityConstraintDisposition.STALE in dispositions and not active:
        # Only escalate when no clean applicable set remains.
        if all(
            item.disposition
            in {
                SecurityConstraintDisposition.STALE,
                SecurityConstraintDisposition.NOT_APPLICABLE,
                SecurityConstraintDisposition.SUPERSEDED,
                SecurityConstraintDisposition.DEFEATED,
            }
            for item in assessments
        ) or not active:
            stale_only = any(
                item.disposition is SecurityConstraintDisposition.STALE
                for item in assessments
            )
            if stale_only and not active:
                return SecuritySelectionDisposition.STALE

    if any(
        item.disposition
        in {
            SecurityConstraintDisposition.REVIEW_REQUIRED,
            SecurityConstraintDisposition.TAINTED,
            SecurityConstraintDisposition.ABSTAIN,
            SecurityConstraintDisposition.UNKNOWN_EXTENSION,
            SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
        }
        for item in assessments
    ):
        review_like = [
            item
            for item in assessments
            if item.disposition
            in {
                SecurityConstraintDisposition.REVIEW_REQUIRED,
                SecurityConstraintDisposition.TAINTED,
                SecurityConstraintDisposition.ABSTAIN,
                SecurityConstraintDisposition.UNKNOWN_EXTENSION,
                SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
            }
        ]
        if review_like and not active:
            if any(
                item.disposition
                in {
                    SecurityConstraintDisposition.UNKNOWN_EXTENSION,
                    SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
                }
                for item in review_like
            ):
                return SecuritySelectionDisposition.REVIEW_REQUIRED
            return SecuritySelectionDisposition.REVIEW_REQUIRED

    if any(
        item.disposition is SecurityConstraintDisposition.INDETERMINATE
        for item in assessments
    ) and not active:
        return SecuritySelectionDisposition.INDETERMINATE

    if any(
        item.disposition is SecurityConstraintDisposition.MISMATCHED
        for item in assessments
    ) and not active:
        return SecuritySelectionDisposition.NOT_APPLICABLE

    if active:
        return SecuritySelectionDisposition.APPLICABLE

    if all(
        item.disposition
        in {
            SecurityConstraintDisposition.NOT_APPLICABLE,
            SecurityConstraintDisposition.SUPERSEDED,
            SecurityConstraintDisposition.DEFEATED,
            SecurityConstraintDisposition.MISMATCHED,
            SecurityConstraintDisposition.STALE,
            SecurityConstraintDisposition.AUTHORITY_MISMATCH,
            SecurityConstraintDisposition.ENVIRONMENT_MISMATCH,
        }
        for item in assessments
    ):
        return SecuritySelectionDisposition.NOT_APPLICABLE

    return SecuritySelectionDisposition.ABSTAIN


def select_applicable_security_constraints(
    query: SecurityConstraintQuery | Mapping[str, Any],
    candidates: Sequence[SecurityConstraintRecord | Mapping[str, Any]],
    *,
    evidence: Sequence[SecurityEvidenceBinding | Mapping[str, Any]] | None = None,
) -> SecurityConstraintSelectionResult:
    """Hard-filter and select Security constraints for ``query``.

    Retrieval rank on candidates is ignored for authority and applicability.
    Unknown extensions, authority substitution, abstract/live environment
    substitution, stale evidence, unresolved conflicts, and coverage gaps fail
    closed to review/abstain dispositions.
    """

    if not isinstance(query, SecurityConstraintQuery):
        query = SecurityConstraintQuery.from_dict(_mapping(query, "query"))

    records: list[SecurityConstraintRecord] = []
    for item in _sequence(candidates, "candidates"):
        if isinstance(item, SecurityConstraintRecord):
            records.append(item)
        else:
            records.append(
                SecurityConstraintRecord.from_dict(_mapping(item, "candidate"))
            )

    records = sorted(records, key=lambda item: item.constraint_id)
    if len({item.constraint_id for item in records}) != len(records):
        raise SecurityConstraintQueryError("candidate constraint_ids must be unique")

    evidence_bindings: list[SecurityEvidenceBinding] = []
    for item in _sequence(evidence or (), "evidence"):
        if isinstance(item, SecurityEvidenceBinding):
            evidence_bindings.append(item)
        else:
            evidence_bindings.append(
                SecurityEvidenceBinding.from_dict(_mapping(item, "evidence"))
            )
    if len({item.evidence_id for item in evidence_bindings}) != len(evidence_bindings):
        raise SecurityConstraintQueryError("evidence_ids must be unique")
    evidence_by_id = {item.evidence_id: item for item in evidence_bindings}

    record_by_id = {item.constraint_id: item for item in records}
    known_vocabs = frozenset(query.known_extension_vocabularies) | frozenset(
        known_extension_vocabularies()
    )

    selectors = _build_query_selectors(query)
    assessments_map: dict[str, SecurityConstraintAssessment] = {}
    for record in records:
        assessments_map[record.constraint_id] = _hard_filter_record(
            query,
            record,
            evidence_by_id=evidence_by_id,
            known_vocabs=known_vocabs,
        )

    assessments_map, contradictions = _resolve_relationships(
        assessments_map, record_by_id
    )

    # Bounded selection by precedence / priority only.
    active = [item for item in assessments_map.values() if item.active]
    ordered = sorted(active, key=_authority_sort_key)
    budget = query.selection_budget
    truncated = ordered[budget:]
    for item in truncated:
        assessments_map[item.constraint_id] = _add_assessment_reason(
            replace(
                item,
                active=False,
                disposition=SecurityConstraintDisposition.ABSTAIN,
            ),
            "selection_budget_exceeded",
        )

    selected_ids = tuple(
        item.constraint_id
        for item in sorted(assessments_map.values(), key=_authority_sort_key)
        if item.active
    )
    selected_records = tuple(record_by_id[item_id] for item_id in selected_ids)

    coverage_gaps: list[CoverageGap] = []
    if not records:
        coverage_gaps.append(
            CoverageGap(
                gap_id="gap:empty-corpus",
                kind=CoverageGapKind.MISSING_AUTHORITY,
                description=(
                    "No Security constraint candidates were provided for selection"
                ),
                subject_ids=(),
            )
        )

    assessments = tuple(
        sorted(assessments_map.values(), key=lambda item: item.constraint_id)
    )
    contradiction_tuple = tuple(
        sorted(contradictions, key=lambda item: item.contradiction_id)
    )
    disposition = _overall_disposition(
        assessments,
        contradiction_tuple,
        coverage_gaps,
        considered_count=len(records),
    )

    env_sub_rejected = any(
        "abstract_model_live_environment_substitution" in item.reason_codes
        or "sandbox_live_environment_substitution" in item.reason_codes
        or any(
            code.startswith("abstract_model_live_environment_substitution")
            or code.startswith("sandbox_live_environment_substitution")
            for code in item.reason_codes
        )
        for item in assessments
    )

    # Selector match evidence.
    matched_selector_ids: list[str] = []
    rejected_selector_ids: list[str] = []
    if disposition is SecuritySelectionDisposition.APPLICABLE:
        matched_selector_ids = [item.selector_id for item in selectors]
    else:
        dim_to_selectors: dict[str, list[str]] = {}
        for item in selectors:
            dim_to_selectors.setdefault(item.dimension, []).append(item.selector_id)
        rejected_dims: set[str] = set()
        matched_dims: set[str] = set()
        for assessment in assessments:
            rejected_dims.update(assessment.rejected_dimensions)
            if assessment.active:
                matched_dims.update(assessment.matched_dimensions)
        for dim, selector_ids in dim_to_selectors.items():
            if dim in rejected_dims:
                rejected_selector_ids.extend(selector_ids)
            elif dim in matched_dims:
                matched_selector_ids.extend(selector_ids)
            else:
                rejected_selector_ids.extend(selector_ids)

    shared_status = _to_shared_status(disposition)
    shared_matched = tuple(sorted(set(matched_selector_ids)))
    shared_rejected = tuple(sorted(set(rejected_selector_ids)))
    if shared_status is ApplicabilityStatus.APPLICABLE:
        shared_rejected = ()
        shared_gaps: tuple[CoverageGap, ...] = ()
        shared_matched = tuple(item.selector_id for item in selectors)
    else:
        shared_gaps = tuple(coverage_gaps)

    world_policy = WorldPolicy(kind=query.world_policy_kind)

    try:
        shared_evidence = ApplicabilityEvidence(
            evidence_id=f"shared:{query.query_id}",
            status=shared_status,
            selectors=selectors,
            matched_selector_ids=shared_matched,
            rejected_selector_ids=shared_rejected,
            coverage_gaps=shared_gaps,
            invocation_digest=query.invocation_digest,
            world_policy=world_policy,
            required_authority=AuthorityKind.EVIDENCE_READINESS,
            notes="security-constraint-query shared applicability projection",
        )
    except ConstraintValidationError:
        shared_evidence = ApplicabilityEvidence(
            evidence_id=f"shared:{query.query_id}",
            status=ApplicabilityStatus.INDETERMINATE,
            selectors=selectors,
            matched_selector_ids=(),
            rejected_selector_ids=tuple(item.selector_id for item in selectors),
            coverage_gaps=tuple(coverage_gaps),
            invocation_digest=query.invocation_digest,
            world_policy=world_policy,
            required_authority=AuthorityKind.EVIDENCE_READINESS,
            notes="security-constraint-query shared applicability fallback",
        )

    premises: list[SelectedPremise] = []
    for rank, constraint_id in enumerate(selected_ids):
        record = record_by_id[constraint_id]
        premises.append(
            SelectedPremise(
                premise_id=f"premise:{constraint_id}",
                statement=record.statement or constraint_id,
                source_ref_ids=record.source_ref_ids,
                logic_family="policy",
                rank=rank,
                score=None,
                selection_method=PremiseSelectionMethod.HARD_FILTER,
                statement_id=constraint_id,
                metadata={
                    "precedence": record.precedence,
                    "priority": record.priority,
                    "artifact_family": record.artifact_family.value,
                    "required_authority": record.required_authority.value,
                    "retrieval_rank_ignored": record.retrieval_rank,
                },
            )
        )
    selected_premises = SelectedPremiseSet(
        set_id=f"premises:{query.query_id}",
        premises=tuple(premises),
        selection_method=PremiseSelectionMethod.HARD_FILTER,
        considered_count=len(records),
        filtered_count=sum(1 for item in assessments if not item.active),
        budget=query.selection_budget,
        config_id="security-constraint-query",
        query_digest=query.digest,
        notes=(
            "Bounded Security selection by precedence, priority; "
            "retrieval rank ignored; artifact families remain distinct"
        ),
    )

    hard_filtered_count = sum(1 for item in assessments if not item.active)
    evidence_receipt = SecurityApplicabilityEvidence(
        evidence_id=f"security-app:{query.query_id}",
        status=disposition,
        query_id=query.query_id,
        query_digest=query.digest,
        selectors=selectors,
        matched_selector_ids=tuple(sorted(set(matched_selector_ids))),
        rejected_selector_ids=tuple(sorted(set(rejected_selector_ids))),
        coverage_gaps=tuple(coverage_gaps),
        assessments=assessments,
        contradictions=contradiction_tuple,
        selected_constraint_ids=selected_ids,
        considered_count=len(records),
        hard_filtered_count=hard_filtered_count,
        selected_count=len(selected_ids),
        selection_budget=query.selection_budget,
        selection_method=PremiseSelectionMethod.HARD_FILTER,
        retrieval_rank_used_for_authority=False,
        artifact_families_distinct=True,
        environment_substitution_rejected=env_sub_rejected,
        shared_applicability=shared_evidence,
        selected_premises=selected_premises,
        notes=(
            "Security hard filters precede precedence selection; "
            "retrieval rank never selects authority; theorem/monitor/"
            "evidence_gate/policy artifacts remain distinct"
        ),
    )

    return SecurityConstraintSelectionResult(
        disposition=disposition,
        query=query,
        evidence=evidence_receipt,
        assessments=assessments,
        selected=selected_records,
        contradictions=contradiction_tuple,
    )


# Public aliases matching interface names in backlog docs.
SecurityConstraintQueryEngine = SecurityConstraintQuery


__all__ = [
    "DEFAULT_SELECTION_BUDGET",
    "SECURITY_APPLICABILITY_EVIDENCE_INTERFACE",
    "SECURITY_APPLICABILITY_EVIDENCE_SCHEMA_VERSION",
    "SECURITY_ARTIFACT_FAMILIES",
    "SECURITY_CONSTRAINT_QUERY_INTERFACE",
    "SECURITY_CONSTRAINT_QUERY_SCHEMA_VERSION",
    "SECURITY_CONSTRAINT_RECORD_SCHEMA_VERSION",
    "SECURITY_CONSTRAINT_SELECTION_SCHEMA_VERSION",
    "SECURITY_HARD_FILTER_DIMENSIONS",
    "SecurityApplicabilityEvidence",
    "SecurityArtifactFamily",
    "SecurityConstraintAssessment",
    "SecurityConstraintDisposition",
    "SecurityConstraintEffect",
    "SecurityConstraintQuery",
    "SecurityConstraintQueryEngine",
    "SecurityConstraintQueryError",
    "SecurityConstraintRecord",
    "SecurityConstraintSelectionResult",
    "SecurityContradiction",
    "SecurityEnvironmentKind",
    "SecurityEvidenceBinding",
    "SecurityPremiseTaintStatus",
    "SecuritySelectionDisposition",
    "select_applicable_security_constraints",
]
