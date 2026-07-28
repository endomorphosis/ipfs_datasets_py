"""Hard-filtered proof-corpus applicability (ProofApplicabilityFilter@1 / LIG-031).

Candidate attested proof envelopes are hard-filtered **before** any bounded
lexical/graph/dense ranking.  Ranking is advisory only and never establishes
applicability or proof authority.

Mandatory hard-filter dimensions (acceptance / plan §8.1):

* tenant / visibility boundary
* exact corpus and revocation root lineage
* jurisdiction / authority / subject / resource / action / capability / data
* effective / expiry temporal window
* supersession / revocation state
* policy / schema / logic / backend / circuit / VK allowlists
* proof / result authority required by the query

This leaf consumes :mod:`.model` and :mod:`.policy` without rewriting the base
query/index surface, body proof verification, domain selection, exports, or
registry.  Private content never enters the applicability receipt; see
:mod:`.audit` for redacted query traces.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.protocols import AuthorityKind
from .model import (
    AttestationKind,
    AttestedProofEnvelope,
    AttestedProofModelError,
    CircuitBinding,
    ScopeBinding,
    TemporalWindow,
    parse_attestation_kind,
    parse_result_authority,
)
from .policy import (
    PolicyBudget,
    ProofTrustPolicy,
    ProofTrustPolicyError,
    TrustEvaluationStatus,
)
from .revocation import ProofRevocationSnapshot

PROOF_APPLICABILITY_FILTER_INTERFACE: Final = "ProofApplicabilityFilter@1"
PROOF_APPLICABILITY_FILTER_SCHEMA_VERSION: Final = "proof-applicability-filter/v1"
PROOF_APPLICABILITY_QUERY_SCHEMA_VERSION: Final = "proof-applicability-query/v1"
PROOF_APPLICABILITY_RESULT_SCHEMA_VERSION: Final = "proof-applicability-result/v1"
HARD_FILTER_ASSESSMENT_SCHEMA_VERSION: Final = "proof-hard-filter-assessment/v1"
RANKED_CANDIDATE_SCHEMA_VERSION: Final = "proof-ranked-candidate/v1"

DEFAULT_MAX_CANDIDATES: Final = 256
DEFAULT_MAX_SELECTED: Final = 64
DEFAULT_MAX_RANK_SCORE_FEATURES: Final = 16
MAX_SELECTION_BUDGET: Final = 1_024
MAX_REASON_LABEL_CHARS: Final = 128
MAX_IDENTIFIER_CHARS: Final = 256

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")
_REASON_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,96}(?::[a-z0-9_./@+-]{1,64}){0,4}$")

# Documented hard-filter dimensions (acceptance).  Ranking is deliberately
# excluded: it never admits or rejects a candidate for applicability.
PROOF_HARD_FILTER_DIMENSIONS: Final[tuple[str, ...]] = (
    "tenant",
    "visibility",
    "corpus_root",
    "revocation_root",
    "parent_lineage",
    "jurisdiction",
    "authority",
    "subject",
    "resource",
    "action",
    "capability",
    "data_class",
    "effective",
    "expiry",
    "supersession",
    "revocation",
    "policy",
    "schema",
    "logic_family",
    "backend",
    "circuit",
    "vk",
    "security_profile",
    "proof_authority",
    "attestation_kind",
    "trust_policy",
)

# Public, non-private diagnostic keys that may carry scope extensions.
_SAFE_DIAGNOSTIC_LIST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "action_ids",
        "capability_ids",
        "data_classes",
        "visibility_classes",
    }
)

# Keys that must never influence ranking-as-authority decisions.
_RANK_FORBIDDEN_AUTHORITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "retrieval_rank",
        "retrieval_score",
        "similarity",
        "bm25",
        "embedding_score",
        "learned_score",
    }
)


class ProofApplicabilityError(AttestedProofModelError):
    """Raised when an applicability query or filter is malformed."""


class FilterDisposition(str, Enum):
    """Per-candidate hard-filter outcome (before ranking)."""

    ADMITTED = "admitted"
    FILTERED = "filtered"
    REJECTED = "rejected"


class SelectionDisposition(str, Enum):
    """Aggregate selection outcome after hard filters and bounded rank."""

    SELECTED = "selected"
    EMPTY = "empty"
    BUDGET_EXHAUSTED = "budget_exhausted"
    COVERAGE_GAP = "coverage_gap"
    ABSTAIN = "abstain"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise ProofApplicabilityError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the applicability filter"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofApplicabilityError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofApplicabilityError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if len(value) > MAX_IDENTIFIER_CHARS:
        raise ProofApplicabilityError(
            f"{field_name} exceeds {MAX_IDENTIFIER_CHARS} characters"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_cid(value: Any, field_name: str) -> str:
    cid = _require_text(value, field_name)
    if not _CID_RE.fullmatch(cid):
        raise ProofApplicabilityError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    return cid


def _optional_cid(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_cid(value, field_name)


def _require_profile(value: Any, field_name: str) -> str:
    profile = _require_text(value, field_name)
    if not _PROFILE_RE.fullmatch(profile):
        raise ProofApplicabilityError(
            f"{field_name} must be a lowercase hyphenated identifier"
        )
    return profile


def _optional_profile(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_profile(value, field_name)


def _unique_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofApplicabilityError(
            f"{field_name} must be a sequence of strings"
        )
    try:
        items = tuple(_require_text(item, field_name) for item in values)
    except TypeError as exc:
        raise ProofApplicabilityError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofApplicabilityError(f"{field_name} values must be unique")
    return items


def _unique_cids(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofApplicabilityError(f"{field_name} must be a sequence of CIDs")
    try:
        items = tuple(_require_cid(item, field_name) for item in values)
    except TypeError as exc:
        raise ProofApplicabilityError(
            f"{field_name} must be a sequence of CIDs"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofApplicabilityError(f"{field_name} values must be unique")
    return items


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProofApplicabilityError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofApplicabilityError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _bounded_budget(value: Any, field_name: str) -> int:
    budget = _positive_int(value, field_name)
    if budget > MAX_SELECTION_BUDGET:
        raise ProofApplicabilityError(
            f"{field_name} must be <= {MAX_SELECTION_BUDGET} (unbounded budgets "
            "are rejected)"
        )
    return budget


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProofApplicabilityError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProofApplicabilityError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _reason_label(value: str) -> str:
    """Normalize a filter reason to a bounded, non-private label."""

    text = _require_text(value, "reason")
    if len(text) > MAX_REASON_LABEL_CHARS:
        text = text[:MAX_REASON_LABEL_CHARS]
    # Collapse whitespace and reject free-form private content.
    compact = re.sub(r"\s+", "_", text.strip().lower())
    compact = re.sub(r"[^a-z0-9_.:/@+-]", "", compact)
    if not compact or not _REASON_RE.fullmatch(compact):
        # Fall back to a stable hashed label rather than leaking raw text.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"reason_hash:{digest}"
    return compact


def _unique_reasons(values: Any) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofApplicabilityError("reasons must be a sequence of strings")
    ordered: list[str] = []
    seen: set[str] = set()
    try:
        for item in values:
            label = _reason_label(str(item))
            if label not in seen:
                seen.add(label)
                ordered.append(label)
    except TypeError as exc:
        raise ProofApplicabilityError(
            "reasons must be a sequence of strings"
        ) from exc
    return tuple(ordered)


def _safe_diagnostic_ids(
    diagnostics: Mapping[str, Any], key: str
) -> tuple[str, ...]:
    """Extract bounded public identifier lists from envelope diagnostics."""

    if key not in _SAFE_DIAGNOSTIC_LIST_KEYS:
        return ()
    raw = diagnostics.get(key)
    if raw in (None, (), []):
        return ()
    if isinstance(raw, (str, bytes, bytearray)):
        return ()
    try:
        items = tuple(
            str(item).strip()
            for item in raw
            if isinstance(item, str) and item.strip() and len(item) <= MAX_IDENTIFIER_CHARS
        )
    except TypeError:
        return ()
    # Preserve order, drop duplicates.
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _finite_score(value: Any, field_name: str = "rank_score") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofApplicabilityError(f"{field_name} must be numeric")
    score = float(value)
    if score != score or score in (float("inf"), float("-inf")):  # NaN/inf
        raise ProofApplicabilityError(f"{field_name} must be finite")
    return score


# ---------------------------------------------------------------------------
# Query context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofApplicabilityQuery:
    """Pinned hard-filter context for a proof-corpus applicability query.

    Every non-empty selector is mandatory for admission.  Ranking budgets are
    finite; unbounded selection is rejected at construction.
    """

    query_id: str
    at_time: str = ""
    tenant: str = ""
    visibility: str = ""
    corpus_root_cid: str = ""
    revocation_root_cid: str = ""
    approved_parent_cids: tuple[str, ...] = ()
    require_parent_lineage: bool = False
    jurisdiction: str = ""
    authority_id: str = ""
    subject_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    action_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    purpose_ids: tuple[str, ...] = ()
    policy_id: str = ""
    schema_version: str = ""
    logic_family: str = ""
    backend_id: str = ""
    circuit_id: str = ""
    vk_id: str = ""
    security_profile: str = ""
    required_result_authority: AuthorityKind | str | None = None
    required_attestation_kinds: tuple[str, ...] = ()
    domain: str = ""
    selection_budget: int = DEFAULT_MAX_SELECTED
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    # When True, envelope-declared revocation_cid / supersession_cid reject.
    reject_revoked: bool = True
    reject_superseded: bool = True
    query_schema_version: str = PROOF_APPLICABILITY_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "query_id", _require_text(self.query_id, "query_id")
        )
        object.__setattr__(
            self, "at_time", _optional_text(self.at_time, "at_time")
        )
        object.__setattr__(self, "tenant", _optional_text(self.tenant, "tenant"))
        object.__setattr__(
            self, "visibility", _optional_text(self.visibility, "visibility")
        )
        object.__setattr__(
            self,
            "corpus_root_cid",
            _optional_cid(self.corpus_root_cid, "corpus_root_cid"),
        )
        object.__setattr__(
            self,
            "revocation_root_cid",
            _optional_cid(self.revocation_root_cid, "revocation_root_cid"),
        )
        object.__setattr__(
            self,
            "approved_parent_cids",
            _unique_cids(self.approved_parent_cids, "approved_parent_cids"),
        )
        if not isinstance(self.require_parent_lineage, bool):
            raise ProofApplicabilityError(
                "require_parent_lineage must be a bool"
            )
        object.__setattr__(
            self,
            "jurisdiction",
            _optional_profile(self.jurisdiction, "jurisdiction"),
        )
        object.__setattr__(
            self,
            "authority_id",
            _optional_text(self.authority_id, "authority_id"),
        )
        object.__setattr__(
            self, "subject_ids", _unique_texts(self.subject_ids, "subject_ids")
        )
        object.__setattr__(
            self,
            "resource_ids",
            _unique_texts(self.resource_ids, "resource_ids"),
        )
        object.__setattr__(
            self, "action_ids", _unique_texts(self.action_ids, "action_ids")
        )
        object.__setattr__(
            self,
            "capability_ids",
            _unique_texts(self.capability_ids, "capability_ids"),
        )
        object.__setattr__(
            self,
            "data_classes",
            _unique_texts(self.data_classes, "data_classes"),
        )
        object.__setattr__(
            self, "purpose_ids", _unique_texts(self.purpose_ids, "purpose_ids")
        )
        object.__setattr__(
            self, "policy_id", _optional_text(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "schema_version",
            _optional_text(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "logic_family",
            _optional_text(self.logic_family, "logic_family"),
        )
        object.__setattr__(
            self, "backend_id", _optional_text(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self, "circuit_id", _optional_text(self.circuit_id, "circuit_id")
        )
        object.__setattr__(self, "vk_id", _optional_text(self.vk_id, "vk_id"))
        object.__setattr__(
            self,
            "security_profile",
            _optional_profile(self.security_profile, "security_profile"),
        )
        if self.required_result_authority is not None:
            object.__setattr__(
                self,
                "required_result_authority",
                parse_result_authority(self.required_result_authority),
            )
        kinds = _unique_texts(
            self.required_attestation_kinds, "required_attestation_kinds"
        )
        object.__setattr__(
            self,
            "required_attestation_kinds",
            tuple(parse_attestation_kind(item).value for item in kinds),
        )
        object.__setattr__(self, "domain", _optional_text(self.domain, "domain"))
        object.__setattr__(
            self,
            "selection_budget",
            _bounded_budget(self.selection_budget, "selection_budget"),
        )
        object.__setattr__(
            self,
            "max_candidates",
            _bounded_budget(self.max_candidates, "max_candidates"),
        )
        for flag_name in ("reject_revoked", "reject_superseded"):
            flag = getattr(self, flag_name)
            if not isinstance(flag, bool):
                raise ProofApplicabilityError(f"{flag_name} must be a bool")
        object.__setattr__(
            self,
            "query_schema_version",
            _require_text(self.query_schema_version, "query_schema_version"),
        )
        if self.query_schema_version != PROOF_APPLICABILITY_QUERY_SCHEMA_VERSION:
            raise ProofApplicabilityError(
                f"unsupported applicability query schema: "
                f"{self.query_schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        authority = self.required_result_authority
        return {
            "action_ids": list(self.action_ids),
            "approved_parent_cids": list(self.approved_parent_cids),
            "at_time": self.at_time,
            "authority_id": self.authority_id,
            "backend_id": self.backend_id,
            "capability_ids": list(self.capability_ids),
            "circuit_id": self.circuit_id,
            "corpus_root_cid": self.corpus_root_cid,
            "data_classes": list(self.data_classes),
            "domain": self.domain,
            "jurisdiction": self.jurisdiction,
            "logic_family": self.logic_family,
            "max_candidates": self.max_candidates,
            "policy_id": self.policy_id,
            "purpose_ids": list(self.purpose_ids),
            "query_id": self.query_id,
            "query_schema_version": self.query_schema_version,
            "reject_revoked": self.reject_revoked,
            "reject_superseded": self.reject_superseded,
            "require_parent_lineage": self.require_parent_lineage,
            "required_attestation_kinds": list(self.required_attestation_kinds),
            "required_result_authority": (
                authority.value if isinstance(authority, AuthorityKind) else ""
            ),
            "resource_ids": list(self.resource_ids),
            "revocation_root_cid": self.revocation_root_cid,
            "schema_version": self.schema_version,
            "security_profile": self.security_profile,
            "selection_budget": self.selection_budget,
            "subject_ids": list(self.subject_ids),
            "tenant": self.tenant,
            "visibility": self.visibility,
            "vk_id": self.vk_id,
        }

    def query_digest(self) -> str:
        return _sha256_digest(_canonical_bytes(self.to_dict()))

    @classmethod
    def from_dict(cls, value: Any) -> "ProofApplicabilityQuery":
        payload = dict(_as_mapping(value, "applicability query"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "action_ids",
                    "approved_parent_cids",
                    "at_time",
                    "authority_id",
                    "backend_id",
                    "capability_ids",
                    "circuit_id",
                    "corpus_root_cid",
                    "data_classes",
                    "domain",
                    "jurisdiction",
                    "logic_family",
                    "max_candidates",
                    "policy_id",
                    "purpose_ids",
                    "query_id",
                    "query_schema_version",
                    "reject_revoked",
                    "reject_superseded",
                    "require_parent_lineage",
                    "required_attestation_kinds",
                    "required_result_authority",
                    "resource_ids",
                    "revocation_root_cid",
                    "schema_version",
                    "security_profile",
                    "selection_budget",
                    "subject_ids",
                    "tenant",
                    "visibility",
                    "vk_id",
                }
            ),
            "applicability query",
        )
        authority = payload.get("required_result_authority") or None
        return cls(
            query_id=payload.get("query_id", ""),
            at_time=payload.get("at_time", ""),
            tenant=payload.get("tenant", ""),
            visibility=payload.get("visibility", ""),
            corpus_root_cid=payload.get("corpus_root_cid", ""),
            revocation_root_cid=payload.get("revocation_root_cid", ""),
            approved_parent_cids=tuple(
                payload.get("approved_parent_cids", ()) or ()
            ),
            require_parent_lineage=bool(
                payload.get("require_parent_lineage", False)
            ),
            jurisdiction=payload.get("jurisdiction", ""),
            authority_id=payload.get("authority_id", ""),
            subject_ids=tuple(payload.get("subject_ids", ()) or ()),
            resource_ids=tuple(payload.get("resource_ids", ()) or ()),
            action_ids=tuple(payload.get("action_ids", ()) or ()),
            capability_ids=tuple(payload.get("capability_ids", ()) or ()),
            data_classes=tuple(payload.get("data_classes", ()) or ()),
            purpose_ids=tuple(payload.get("purpose_ids", ()) or ()),
            policy_id=payload.get("policy_id", ""),
            schema_version=payload.get("schema_version", ""),
            logic_family=payload.get("logic_family", ""),
            backend_id=payload.get("backend_id", ""),
            circuit_id=payload.get("circuit_id", ""),
            vk_id=payload.get("vk_id", ""),
            security_profile=payload.get("security_profile", ""),
            required_result_authority=authority,
            required_attestation_kinds=tuple(
                payload.get("required_attestation_kinds", ()) or ()
            ),
            domain=payload.get("domain", ""),
            selection_budget=int(
                payload.get("selection_budget", DEFAULT_MAX_SELECTED)
            ),
            max_candidates=int(
                payload.get("max_candidates", DEFAULT_MAX_CANDIDATES)
            ),
            reject_revoked=bool(payload.get("reject_revoked", True)),
            reject_superseded=bool(payload.get("reject_superseded", True)),
            query_schema_version=payload.get(
                "query_schema_version", PROOF_APPLICABILITY_QUERY_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Assessments / ranked candidates / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HardFilterAssessment:
    """Per-envelope hard-filter outcome with bounded reason labels."""

    envelope_cid: str
    disposition: FilterDisposition | str
    reasons: tuple[str, ...] = ()
    filter_dimensions: tuple[str, ...] = ()
    rank_score: float | None = None
    schema_version: str = HARD_FILTER_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "envelope_cid",
            _require_cid(self.envelope_cid, "envelope_cid"),
        )
        object.__setattr__(
            self,
            "disposition",
            _parse_enum(self.disposition, FilterDisposition, "disposition"),
        )
        object.__setattr__(self, "reasons", _unique_reasons(self.reasons))
        object.__setattr__(
            self,
            "filter_dimensions",
            _unique_texts(self.filter_dimensions, "filter_dimensions"),
        )
        if self.rank_score is not None:
            object.__setattr__(
                self, "rank_score", _finite_score(self.rank_score, "rank_score")
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != HARD_FILTER_ASSESSMENT_SCHEMA_VERSION:
            raise ProofApplicabilityError(
                f"unsupported assessment schema: {self.schema_version!r}"
            )
        if (
            self.disposition is FilterDisposition.ADMITTED
            and self.reasons
        ):
            # Admitted candidates may carry empty reasons only.
            raise ProofApplicabilityError(
                "admitted assessments must not carry filter reasons"
            )
        if (
            self.disposition is not FilterDisposition.ADMITTED
            and not self.reasons
        ):
            raise ProofApplicabilityError(
                "filtered/rejected assessments require at least one reason"
            )

    @property
    def admitted(self) -> bool:
        return self.disposition is FilterDisposition.ADMITTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "envelope_cid": self.envelope_cid,
            "filter_dimensions": list(self.filter_dimensions),
            "rank_score": self.rank_score,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "HardFilterAssessment":
        payload = dict(_as_mapping(value, "hard filter assessment"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "disposition",
                    "envelope_cid",
                    "filter_dimensions",
                    "rank_score",
                    "reasons",
                    "schema_version",
                }
            ),
            "hard filter assessment",
        )
        return cls(
            envelope_cid=payload.get("envelope_cid", ""),
            disposition=payload.get("disposition", FilterDisposition.FILTERED),
            reasons=tuple(payload.get("reasons", ()) or ()),
            filter_dimensions=tuple(payload.get("filter_dimensions", ()) or ()),
            rank_score=payload.get("rank_score"),
            schema_version=payload.get(
                "schema_version", HARD_FILTER_ASSESSMENT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """Advisory post-filter rank entry; never establishes applicability."""

    envelope_cid: str
    rank_index: int
    rank_score: float
    score_features: Mapping[str, float] = field(default_factory=dict)
    schema_version: str = RANKED_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "envelope_cid",
            _require_cid(self.envelope_cid, "envelope_cid"),
        )
        object.__setattr__(
            self,
            "rank_index",
            _non_negative_int(self.rank_index, "rank_index"),
        )
        object.__setattr__(
            self, "rank_score", _finite_score(self.rank_score, "rank_score")
        )
        features_raw = dict(_as_mapping(self.score_features, "score_features"))
        if len(features_raw) > DEFAULT_MAX_RANK_SCORE_FEATURES:
            raise ProofApplicabilityError(
                f"score_features exceeds {DEFAULT_MAX_RANK_SCORE_FEATURES} entries"
            )
        features: dict[str, float] = {}
        for key, value in sorted(features_raw.items(), key=lambda pair: str(pair[0])):
            key_text = _require_text(str(key), "score_features key")
            if key_text in _RANK_FORBIDDEN_AUTHORITY_KEYS:
                # Features may use these names only as advisory scores; they
                # cannot appear as authority-selection keys (checked on result).
                pass
            features[key_text] = _finite_score(value, f"score_features[{key_text}]")
        object.__setattr__(self, "score_features", MappingProxyType(features))
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != RANKED_CANDIDATE_SCHEMA_VERSION:
            raise ProofApplicabilityError(
                f"unsupported ranked candidate schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_cid": self.envelope_cid,
            "rank_index": self.rank_index,
            "rank_score": self.rank_score,
            "schema_version": self.schema_version,
            "score_features": dict(self.score_features),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RankedCandidate":
        payload = dict(_as_mapping(value, "ranked candidate"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "envelope_cid",
                    "rank_index",
                    "rank_score",
                    "schema_version",
                    "score_features",
                }
            ),
            "ranked candidate",
        )
        return cls(
            envelope_cid=payload.get("envelope_cid", ""),
            rank_index=int(payload.get("rank_index", 0)),
            rank_score=float(payload.get("rank_score", 0.0)),
            score_features=dict(payload.get("score_features", {}) or {}),
            schema_version=payload.get(
                "schema_version", RANKED_CANDIDATE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofApplicabilityResult:
    """Hard-filter + bounded-rank result with traceable counts and gaps.

    Ranking never establishes applicability or proof: selected CIDs are always
    a subset of hard-filter admissions, ordered only for presentation.
    """

    query_id: str
    disposition: SelectionDisposition | str
    assessments: tuple[HardFilterAssessment, ...] = ()
    admitted_cids: tuple[str, ...] = ()
    ranked: tuple[RankedCandidate, ...] = ()
    selected_cids: tuple[str, ...] = ()
    rejected_cids: tuple[str, ...] = ()
    considered_count: int = 0
    filtered_count: int = 0
    ranked_count: int = 0
    selected_count: int = 0
    rejected_count: int = 0
    reason_counts: Mapping[str, int] = field(default_factory=dict)
    budgets: Mapping[str, int] = field(default_factory=dict)
    gaps: tuple[str, ...] = ()
    retrieval_rank_used_for_authority: bool = False
    query_digest: str = ""
    policy_digest: str = ""
    schema_version: str = PROOF_APPLICABILITY_RESULT_SCHEMA_VERSION
    interface: str = PROOF_APPLICABILITY_FILTER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "query_id", _require_text(self.query_id, "query_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _parse_enum(self.disposition, SelectionDisposition, "disposition"),
        )
        assessments = tuple(self.assessments)
        for item in assessments:
            if not isinstance(item, HardFilterAssessment):
                raise ProofApplicabilityError(
                    "assessments must be HardFilterAssessment instances"
                )
        # Stable order by envelope CID.
        assessments = tuple(
            sorted(assessments, key=lambda item: item.envelope_cid)
        )
        object.__setattr__(self, "assessments", assessments)
        object.__setattr__(
            self, "admitted_cids", _unique_cids(self.admitted_cids, "admitted_cids")
        )
        ranked = tuple(self.ranked)
        for item in ranked:
            if not isinstance(item, RankedCandidate):
                raise ProofApplicabilityError(
                    "ranked must be RankedCandidate instances"
                )
        object.__setattr__(self, "ranked", ranked)
        object.__setattr__(
            self,
            "selected_cids",
            _unique_cids(self.selected_cids, "selected_cids"),
        )
        object.__setattr__(
            self,
            "rejected_cids",
            _unique_cids(self.rejected_cids, "rejected_cids"),
        )
        object.__setattr__(
            self,
            "considered_count",
            _non_negative_int(self.considered_count, "considered_count"),
        )
        object.__setattr__(
            self,
            "filtered_count",
            _non_negative_int(self.filtered_count, "filtered_count"),
        )
        object.__setattr__(
            self,
            "ranked_count",
            _non_negative_int(self.ranked_count, "ranked_count"),
        )
        object.__setattr__(
            self,
            "selected_count",
            _non_negative_int(self.selected_count, "selected_count"),
        )
        object.__setattr__(
            self,
            "rejected_count",
            _non_negative_int(self.rejected_count, "rejected_count"),
        )

        reason_counts_raw = dict(_as_mapping(self.reason_counts, "reason_counts"))
        reason_counts: dict[str, int] = {}
        for key, value in sorted(
            reason_counts_raw.items(), key=lambda pair: str(pair[0])
        ):
            label = _reason_label(str(key))
            reason_counts[label] = _non_negative_int(
                value, f"reason_counts[{label}]"
            )
        object.__setattr__(self, "reason_counts", MappingProxyType(reason_counts))

        budgets_raw = dict(_as_mapping(self.budgets, "budgets"))
        budgets: dict[str, int] = {}
        for key, value in sorted(
            budgets_raw.items(), key=lambda pair: str(pair[0])
        ):
            key_text = _require_text(str(key), "budgets key")
            budgets[key_text] = _non_negative_int(value, f"budgets[{key_text}]")
        object.__setattr__(self, "budgets", MappingProxyType(budgets))

        object.__setattr__(self, "gaps", _unique_reasons(self.gaps))

        if not isinstance(self.retrieval_rank_used_for_authority, bool):
            raise ProofApplicabilityError(
                "retrieval_rank_used_for_authority must be a bool"
            )
        if self.retrieval_rank_used_for_authority:
            raise ProofApplicabilityError(
                "ranking never establishes applicability or proof authority"
            )

        # Selected must be a subset of admitted (hard filter precedes rank).
        admitted_set = set(self.admitted_cids)
        if not set(self.selected_cids).issubset(admitted_set):
            raise ProofApplicabilityError(
                "selected_cids must be a subset of hard-filter admitted_cids"
            )
        for candidate in self.ranked:
            if candidate.envelope_cid not in admitted_set:
                raise ProofApplicabilityError(
                    "ranked candidates must be hard-filter admitted"
                )

        object.__setattr__(
            self,
            "query_digest",
            _optional_text(self.query_digest, "query_digest"),
        )
        object.__setattr__(
            self,
            "policy_digest",
            _optional_text(self.policy_digest, "policy_digest"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_APPLICABILITY_RESULT_SCHEMA_VERSION:
            raise ProofApplicabilityError(
                f"unsupported applicability result schema: "
                f"{self.schema_version!r}"
            )
        if self.interface != PROOF_APPLICABILITY_FILTER_INTERFACE:
            raise ProofApplicabilityError(
                f"unsupported applicability interface: {self.interface!r}"
            )

        # Count consistency (fail closed on internal drift).
        if self.selected_count != len(self.selected_cids):
            raise ProofApplicabilityError(
                "selected_count does not match selected_cids"
            )
        if self.ranked_count != len(self.ranked):
            raise ProofApplicabilityError(
                "ranked_count does not match ranked entries"
            )
        if self.rejected_count != len(self.rejected_cids):
            raise ProofApplicabilityError(
                "rejected_count does not match rejected_cids"
            )

    @property
    def ranking_establishes_applicability(self) -> bool:
        """Always False — ranking never admits a candidate."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_cids": list(self.admitted_cids),
            "assessments": [item.to_dict() for item in self.assessments],
            "budgets": dict(self.budgets),
            "considered_count": self.considered_count,
            "disposition": self.disposition.value,
            "filtered_count": self.filtered_count,
            "gaps": list(self.gaps),
            "interface": self.interface,
            "policy_digest": self.policy_digest,
            "query_digest": self.query_digest,
            "query_id": self.query_id,
            "ranked": [item.to_dict() for item in self.ranked],
            "ranked_count": self.ranked_count,
            "ranking_establishes_applicability": False,
            "reason_counts": dict(self.reason_counts),
            "rejected_cids": list(self.rejected_cids),
            "rejected_count": self.rejected_count,
            "retrieval_rank_used_for_authority": False,
            "schema_version": self.schema_version,
            "selected_cids": list(self.selected_cids),
            "selected_count": self.selected_count,
        }

    def result_digest(self) -> str:
        return _sha256_digest(_canonical_bytes(self.to_dict()))

    @classmethod
    def from_dict(cls, value: Any) -> "ProofApplicabilityResult":
        payload = dict(_as_mapping(value, "applicability result"))
        # Derived flag is emitted for consumers; ignore on load.
        payload.pop("ranking_establishes_applicability", None)
        _reject_unknown(
            payload,
            frozenset(
                {
                    "admitted_cids",
                    "assessments",
                    "budgets",
                    "considered_count",
                    "disposition",
                    "filtered_count",
                    "gaps",
                    "interface",
                    "policy_digest",
                    "query_digest",
                    "query_id",
                    "ranked",
                    "ranked_count",
                    "reason_counts",
                    "rejected_cids",
                    "rejected_count",
                    "retrieval_rank_used_for_authority",
                    "schema_version",
                    "selected_cids",
                    "selected_count",
                }
            ),
            "applicability result",
        )
        if payload.get("retrieval_rank_used_for_authority"):
            raise ProofApplicabilityError(
                "ranking never establishes applicability or proof authority"
            )
        return cls(
            query_id=payload.get("query_id", ""),
            disposition=payload.get("disposition", SelectionDisposition.EMPTY),
            assessments=tuple(
                HardFilterAssessment.from_dict(item)
                for item in (payload.get("assessments") or ())
            ),
            admitted_cids=tuple(payload.get("admitted_cids", ()) or ()),
            ranked=tuple(
                RankedCandidate.from_dict(item)
                for item in (payload.get("ranked") or ())
            ),
            selected_cids=tuple(payload.get("selected_cids", ()) or ()),
            rejected_cids=tuple(payload.get("rejected_cids", ()) or ()),
            considered_count=int(payload.get("considered_count", 0)),
            filtered_count=int(payload.get("filtered_count", 0)),
            ranked_count=int(payload.get("ranked_count", 0)),
            selected_count=int(payload.get("selected_count", 0)),
            rejected_count=int(payload.get("rejected_count", 0)),
            reason_counts=dict(payload.get("reason_counts", {}) or {}),
            budgets=dict(payload.get("budgets", {}) or {}),
            gaps=tuple(payload.get("gaps", ()) or ()),
            retrieval_rank_used_for_authority=False,
            query_digest=payload.get("query_digest", ""),
            policy_digest=payload.get("policy_digest", ""),
            schema_version=payload.get(
                "schema_version", PROOF_APPLICABILITY_RESULT_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", PROOF_APPLICABILITY_FILTER_INTERFACE
            ),
        )


# ---------------------------------------------------------------------------
# Filter engine
# ---------------------------------------------------------------------------


def _match_required_ids(
    required: Sequence[str],
    declared: Sequence[str],
    *,
    dimension: str,
    missing_reason: str,
    mismatch_reason: str,
) -> list[str]:
    """Return filter reasons when *required* is not covered by *declared*."""

    if not required:
        return []
    if not declared:
        return [missing_reason]
    declared_set = set(declared)
    reasons: list[str] = []
    for item in required:
        if item not in declared_set:
            reasons.append(f"{mismatch_reason}:{_reason_label(item)}")
    # dimension retained for callers that want dimension tags; silence lint.
    _ = dimension
    return reasons


def hard_filter_envelope(
    envelope: AttestedProofEnvelope,
    query: ProofApplicabilityQuery,
    *,
    trust_policy: ProofTrustPolicy | None = None,
    revocation_snapshot: ProofRevocationSnapshot | None = None,
    revoked_target_cids: Iterable[str] | None = None,
) -> HardFilterAssessment:
    """Apply all hard filters to one envelope (before any ranking)."""

    if not isinstance(envelope, AttestedProofEnvelope):
        raise ProofApplicabilityError(
            "envelope must be an AttestedProofEnvelope"
        )
    if not isinstance(query, ProofApplicabilityQuery):
        raise ProofApplicabilityError(
            "query must be a ProofApplicabilityQuery"
        )

    envelope.verify_integrity()
    reasons: list[str] = []
    dimensions: list[str] = []

    scope = envelope.scope
    assert isinstance(scope, ScopeBinding)
    temporal = envelope.temporal
    assert isinstance(temporal, TemporalWindow)
    circuit = envelope.circuit
    assert isinstance(circuit, CircuitBinding)
    diagnostics = dict(envelope.diagnostics)

    # -- tenant / visibility -------------------------------------------------
    if query.tenant:
        dimensions.append("tenant")
        if not scope.tenant:
            reasons.append("missing_tenant")
        elif scope.tenant != query.tenant:
            reasons.append("tenant_mismatch")
    if query.visibility:
        dimensions.append("visibility")
        declared_vis = _safe_diagnostic_ids(diagnostics, "visibility_classes")
        if not declared_vis:
            reasons.append("missing_visibility")
        elif query.visibility not in declared_vis:
            reasons.append("visibility_mismatch")

    # -- exact root lineage --------------------------------------------------
    if query.corpus_root_cid:
        dimensions.append("corpus_root")
        if not envelope.corpus_root_cid:
            reasons.append("missing_corpus_root")
        elif envelope.corpus_root_cid != query.corpus_root_cid:
            reasons.append("corpus_root_not_exact")
    if query.revocation_root_cid:
        dimensions.append("revocation_root")
        if not envelope.revocation_root_cid:
            reasons.append("missing_revocation_root")
        elif envelope.revocation_root_cid != query.revocation_root_cid:
            reasons.append("revocation_root_not_exact")
    if query.require_parent_lineage or query.approved_parent_cids:
        dimensions.append("parent_lineage")
        if query.require_parent_lineage and not envelope.parent_cids:
            reasons.append("missing_parent_lineage")
        if query.approved_parent_cids:
            approved = set(query.approved_parent_cids)
            for parent in envelope.parent_cids:
                if parent not in approved:
                    reasons.append("parent_not_in_approved_lineage")
                    break

    # -- jurisdiction / authority / subject / resource / purpose -------------
    if query.jurisdiction:
        dimensions.append("jurisdiction")
        if not scope.jurisdiction:
            reasons.append("missing_jurisdiction")
        elif scope.jurisdiction != query.jurisdiction:
            reasons.append("jurisdiction_mismatch")
    if query.authority_id:
        dimensions.append("authority")
        # Authority is bound via producer/policy/pipeline ontology or policy id.
        declared_authority = (
            envelope.policy_id
            or envelope.producer_id
            or getattr(envelope.pipeline, "policy_id", "")
        )
        if not declared_authority:
            reasons.append("missing_authority")
        elif declared_authority != query.authority_id:
            reasons.append("authority_mismatch")
    reasons.extend(
        _match_required_ids(
            query.subject_ids,
            scope.subject_ids,
            dimension="subject",
            missing_reason="missing_subject",
            mismatch_reason="subject_mismatch",
        )
    )
    if query.subject_ids:
        dimensions.append("subject")
    reasons.extend(
        _match_required_ids(
            query.resource_ids,
            scope.resource_ids,
            dimension="resource",
            missing_reason="missing_resource",
            mismatch_reason="resource_mismatch",
        )
    )
    if query.resource_ids:
        dimensions.append("resource")
    reasons.extend(
        _match_required_ids(
            query.purpose_ids,
            scope.purpose_ids,
            dimension="purpose",
            missing_reason="missing_purpose",
            mismatch_reason="purpose_mismatch",
        )
    )

    # -- action / capability / data class (public diagnostic extensions) -----
    if query.action_ids:
        dimensions.append("action")
        reasons.extend(
            _match_required_ids(
                query.action_ids,
                _safe_diagnostic_ids(diagnostics, "action_ids"),
                dimension="action",
                missing_reason="missing_action",
                mismatch_reason="action_mismatch",
            )
        )
    if query.capability_ids:
        dimensions.append("capability")
        reasons.extend(
            _match_required_ids(
                query.capability_ids,
                _safe_diagnostic_ids(diagnostics, "capability_ids"),
                dimension="capability",
                missing_reason="missing_capability",
                mismatch_reason="capability_mismatch",
            )
        )
    if query.data_classes:
        dimensions.append("data_class")
        reasons.extend(
            _match_required_ids(
                query.data_classes,
                _safe_diagnostic_ids(diagnostics, "data_classes"),
                dimension="data_class",
                missing_reason="missing_data_class",
                mismatch_reason="data_class_mismatch",
            )
        )

    # -- effective / expiry --------------------------------------------------
    if query.at_time:
        dimensions.append("effective")
        dimensions.append("expiry")
        if temporal.effective_at and query.at_time < temporal.effective_at:
            reasons.append("not_yet_effective")
        if temporal.expires_at and query.at_time >= temporal.expires_at:
            reasons.append("expired")
        if not temporal.is_effective_at(query.at_time):
            if "not_yet_effective" not in reasons and "expired" not in reasons:
                reasons.append("envelope_not_effective")

    # -- supersession / revocation -------------------------------------------
    if query.reject_revoked:
        dimensions.append("revocation")
        if envelope.is_revoked():
            reasons.append("envelope_revoked")
    if query.reject_superseded:
        dimensions.append("supersession")
        if envelope.is_superseded():
            reasons.append("envelope_superseded")

    revoked_set: set[str] = set()
    if revoked_target_cids is not None:
        for item in revoked_target_cids:
            revoked_set.add(_require_cid(item, "revoked_target_cids"))
    if revocation_snapshot is not None:
        if not isinstance(revocation_snapshot, ProofRevocationSnapshot):
            raise ProofApplicabilityError(
                "revocation_snapshot must be a ProofRevocationSnapshot"
            )
        if (
            query.revocation_root_cid
            and revocation_snapshot.corpus_root_cid
            and query.corpus_root_cid
            and revocation_snapshot.corpus_root_cid != query.corpus_root_cid
        ):
            reasons.append("revocation_snapshot_root_mismatch")
        revoked_set |= set(revocation_snapshot.revoked_cids())
    if revoked_set:
        dimensions.append("revocation")
        target = envelope.envelope_cid or envelope.content_cid
        if target in revoked_set:
            reasons.append("target_in_revocation_snapshot")
        if envelope.proof_artifact_cid and envelope.proof_artifact_cid in revoked_set:
            reasons.append("proof_artifact_revoked")

    # -- policy / schema / logic / backend / circuit / VK --------------------
    if query.policy_id:
        dimensions.append("policy")
        if not envelope.policy_id:
            reasons.append("missing_policy")
        elif envelope.policy_id != query.policy_id:
            reasons.append("policy_mismatch")
    if query.schema_version:
        dimensions.append("schema")
        if envelope.schema_version != query.schema_version:
            reasons.append("schema_mismatch")
    if query.logic_family:
        dimensions.append("logic_family")
        if not envelope.logic_family:
            reasons.append("missing_logic_family")
        elif envelope.logic_family != query.logic_family:
            reasons.append("logic_family_mismatch")
    if query.backend_id:
        dimensions.append("backend")
        backend = envelope.backend_id or circuit.backend_id
        if not backend:
            reasons.append("missing_backend")
        elif backend != query.backend_id:
            reasons.append("backend_mismatch")
    if query.circuit_id:
        dimensions.append("circuit")
        if not circuit.circuit_id:
            reasons.append("missing_circuit")
        elif (
            circuit.circuit_id != query.circuit_id
            and circuit.circuit_ref != query.circuit_id
        ):
            reasons.append("circuit_mismatch")
    if query.vk_id:
        dimensions.append("vk")
        if not circuit.vk_id:
            reasons.append("missing_vk")
        elif circuit.vk_id != query.vk_id:
            reasons.append("vk_mismatch")
    if query.security_profile:
        dimensions.append("security_profile")
        profile = envelope.security_profile or circuit.security_profile
        if not profile:
            reasons.append("missing_security_profile")
        elif profile != query.security_profile:
            reasons.append("security_profile_mismatch")
    if query.domain:
        if not envelope.domain:
            reasons.append("missing_domain")
        elif envelope.domain != query.domain:
            reasons.append("domain_mismatch")

    # -- proof / result authority --------------------------------------------
    if query.required_result_authority is not None:
        dimensions.append("proof_authority")
        assert isinstance(query.required_result_authority, AuthorityKind)
        if envelope.result_authority is not query.required_result_authority:
            reasons.append(
                "result_authority_mismatch:"
                f"{envelope.result_authority.value}"
            )
    if query.required_attestation_kinds:
        dimensions.append("attestation_kind")
        kind_value = envelope.attestation_kind.value
        if kind_value not in query.required_attestation_kinds:
            reasons.append(f"attestation_kind_not_required:{kind_value}")

    # -- optional trust policy (fail closed on reject) -----------------------
    if trust_policy is not None:
        dimensions.append("trust_policy")
        if not isinstance(trust_policy, ProofTrustPolicy):
            raise ProofApplicabilityError(
                "trust_policy must be a ProofTrustPolicy"
            )
        try:
            evaluation = trust_policy.evaluate(
                envelope, at_time=query.at_time or ""
            )
        except ProofTrustPolicyError as exc:
            raise ProofApplicabilityError(
                f"trust policy evaluation failed: {exc}"
            ) from exc
        if evaluation.status is not TrustEvaluationStatus.ACCEPT:
            for reason in evaluation.reasons:
                reasons.append(f"trust_policy:{_reason_label(reason)}")
            if not evaluation.reasons:
                reasons.append("trust_policy_rejected")

    # Deduplicate reasons / dimensions preserving order.
    ordered_reasons = _unique_reasons(reasons)
    ordered_dimensions: list[str] = []
    seen_dim: set[str] = set()
    for dim in dimensions:
        if dim not in seen_dim:
            seen_dim.add(dim)
            ordered_dimensions.append(dim)

    if ordered_reasons:
        # Hard rejections (revocation, authority, root) vs soft filters.
        hard_tokens = (
            "revoked",
            "revocation_snapshot",
            "target_in_revocation",
            "proof_artifact_revoked",
            "superseded",
            "not_exact",
            "result_authority",
            "trust_policy",
            "expired",
            "not_yet_effective",
            "attestation_kind",
            "simulation",
            "membership",
        )
        hard = any(
            any(token in reason for token in hard_tokens)
            for reason in ordered_reasons
        )
        disposition = (
            FilterDisposition.REJECTED if hard else FilterDisposition.FILTERED
        )
        return HardFilterAssessment(
            envelope_cid=envelope.envelope_cid or envelope.content_cid,
            disposition=disposition,
            reasons=ordered_reasons,
            filter_dimensions=tuple(ordered_dimensions),
        )

    return HardFilterAssessment(
        envelope_cid=envelope.envelope_cid or envelope.content_cid,
        disposition=FilterDisposition.ADMITTED,
        reasons=(),
        filter_dimensions=tuple(ordered_dimensions),
    )


def _advisory_rank_score(
    envelope: AttestedProofEnvelope,
    advisory_scores: Mapping[str, float] | None,
) -> tuple[float, dict[str, float]]:
    """Compute a purely advisory rank score (never used for applicability)."""

    cid = envelope.envelope_cid or envelope.content_cid
    features: dict[str, float] = {}
    if advisory_scores and cid in advisory_scores:
        features["advisory"] = _finite_score(
            advisory_scores[cid], "advisory_scores"
        )
    # Deterministic tie-break feature from CID suffix (not authority).
    features["cid_order"] = float(
        int(hashlib.sha256(cid.encode("utf-8")).hexdigest()[:8], 16)
    ) / 0xFFFFFFFF
    # Prefer complete coverage only as a soft presentation signal.
    if envelope.coverage and getattr(envelope.coverage, "complete", False):
        features["coverage_complete"] = 1.0
    else:
        features["coverage_complete"] = 0.0
    # Higher is better for selection ordering of already-admitted candidates.
    score = (
        features.get("advisory", 0.0) * 1_000.0
        + features["coverage_complete"] * 10.0
        + features["cid_order"]
    )
    return score, features


@dataclass(frozen=True, slots=True)
class ProofApplicabilityFilter:
    """ProofApplicabilityFilter@1 — hard filters before bounded rank.

    Ranking never establishes applicability or proof.  Every omission is
    traceable via :class:`HardFilterAssessment` reasons and aggregate counts.
    """

    trust_policy: ProofTrustPolicy | None = None
    revocation_snapshot: ProofRevocationSnapshot | None = None
    revoked_target_cids: tuple[str, ...] = ()
    interface: str = PROOF_APPLICABILITY_FILTER_INTERFACE
    schema_version: str = PROOF_APPLICABILITY_FILTER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.trust_policy is not None and not isinstance(
            self.trust_policy, ProofTrustPolicy
        ):
            raise ProofApplicabilityError(
                "trust_policy must be a ProofTrustPolicy or None"
            )
        if self.revocation_snapshot is not None and not isinstance(
            self.revocation_snapshot, ProofRevocationSnapshot
        ):
            raise ProofApplicabilityError(
                "revocation_snapshot must be a ProofRevocationSnapshot or None"
            )
        object.__setattr__(
            self,
            "revoked_target_cids",
            _unique_cids(self.revoked_target_cids, "revoked_target_cids"),
        )
        if self.interface != PROOF_APPLICABILITY_FILTER_INTERFACE:
            raise ProofApplicabilityError(
                f"unsupported filter interface: {self.interface!r}"
            )
        if self.schema_version != PROOF_APPLICABILITY_FILTER_SCHEMA_VERSION:
            raise ProofApplicabilityError(
                f"unsupported filter schema: {self.schema_version!r}"
            )

    def filter_one(
        self,
        envelope: AttestedProofEnvelope,
        query: ProofApplicabilityQuery,
    ) -> HardFilterAssessment:
        """Hard-filter a single envelope (no ranking)."""

        return hard_filter_envelope(
            envelope,
            query,
            trust_policy=self.trust_policy,
            revocation_snapshot=self.revocation_snapshot,
            revoked_target_cids=self.revoked_target_cids,
        )

    def select(
        self,
        envelopes: Sequence[AttestedProofEnvelope],
        query: ProofApplicabilityQuery,
        *,
        advisory_scores: Mapping[str, float] | None = None,
    ) -> ProofApplicabilityResult:
        """Hard-filter then bounded-rank candidates.

        Order of operations (invariant):

        1. Cap considered set to ``query.max_candidates`` (deterministic CID order).
        2. Hard-filter every considered envelope.
        3. Rank only the admitted set with advisory scores.
        4. Select up to ``query.selection_budget`` from the ranked admitted set.

        Ranking never promotes a filtered/rejected candidate into selection.
        """

        if not isinstance(query, ProofApplicabilityQuery):
            raise ProofApplicabilityError(
                "query must be a ProofApplicabilityQuery"
            )
        if isinstance(envelopes, (str, bytes, bytearray)):
            raise ProofApplicabilityError(
                "envelopes must be a sequence of AttestedProofEnvelope"
            )

        # Deterministic candidate order by envelope CID before budgets.
        ordered: list[AttestedProofEnvelope] = []
        seen_cids: set[str] = set()
        for item in envelopes:
            if not isinstance(item, AttestedProofEnvelope):
                raise ProofApplicabilityError(
                    "envelopes must be AttestedProofEnvelope instances"
                )
            item.verify_integrity()
            cid = item.envelope_cid or item.content_cid
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            ordered.append(item)
        ordered.sort(key=lambda env: env.envelope_cid or env.content_cid)

        considered = ordered[: query.max_candidates]
        truncated = len(ordered) > query.max_candidates

        assessments: list[HardFilterAssessment] = []
        admitted: list[AttestedProofEnvelope] = []
        rejected_cids: list[str] = []
        reason_counts: dict[str, int] = {}

        for envelope in considered:
            assessment = self.filter_one(envelope, query)
            assessments.append(assessment)
            if assessment.admitted:
                admitted.append(envelope)
            else:
                rejected_cids.append(assessment.envelope_cid)
                for reason in assessment.reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1

        # Rank admitted only.
        scored: list[tuple[float, dict[str, float], AttestedProofEnvelope]] = []
        for envelope in admitted:
            score, features = _advisory_rank_score(envelope, advisory_scores)
            scored.append((score, features, envelope))
        # Higher score first; CID ascending as deterministic tie-break.
        scored.sort(
            key=lambda row: (
                -row[0],
                row[2].envelope_cid or row[2].content_cid,
            )
        )

        ranked: list[RankedCandidate] = []
        for index, (score, features, envelope) in enumerate(scored):
            ranked.append(
                RankedCandidate(
                    envelope_cid=envelope.envelope_cid or envelope.content_cid,
                    rank_index=index,
                    rank_score=score,
                    score_features=features,
                )
            )

        selected_cids = tuple(
            item.envelope_cid for item in ranked[: query.selection_budget]
        )
        budget_exhausted = len(ranked) > query.selection_budget

        gaps: list[str] = []
        if truncated:
            gaps.append("candidate_budget_truncated")
        if budget_exhausted:
            gaps.append("selection_budget_exhausted")
        if not considered:
            gaps.append("no_candidates_considered")
        elif not admitted:
            gaps.append("no_candidates_admitted")

        if selected_cids:
            disposition = SelectionDisposition.SELECTED
        elif budget_exhausted:
            disposition = SelectionDisposition.BUDGET_EXHAUSTED
        elif not considered:
            disposition = SelectionDisposition.EMPTY
        elif not admitted:
            disposition = SelectionDisposition.ABSTAIN
        else:
            disposition = SelectionDisposition.EMPTY

        if gaps and disposition is SelectionDisposition.SELECTED:
            # Selection succeeded but coverage/budget gaps remain advisory.
            pass
        elif "no_candidates_admitted" in gaps and not selected_cids:
            disposition = SelectionDisposition.COVERAGE_GAP

        policy_digest = ""
        if self.trust_policy is not None:
            policy_digest = self.trust_policy.policy_digest()

        budgets = {
            "max_candidates": query.max_candidates,
            "selection_budget": query.selection_budget,
            "considered": len(considered),
            "admitted": len(admitted),
            "selected": len(selected_cids),
        }
        if isinstance(
            getattr(self.trust_policy, "budget", None), PolicyBudget
        ):
            assert self.trust_policy is not None
            budget = self.trust_policy.budget
            assert isinstance(budget, PolicyBudget)
            budgets["policy_max_candidates"] = budget.max_candidates
            budgets["policy_timeout_ms"] = budget.timeout_ms

        filtered_count = sum(
            1
            for item in assessments
            if item.disposition is FilterDisposition.FILTERED
        )
        # rejected_count tracks hard rejects + soft filters for trace totals.
        return ProofApplicabilityResult(
            query_id=query.query_id,
            disposition=disposition,
            assessments=tuple(assessments),
            admitted_cids=tuple(
                env.envelope_cid or env.content_cid for env in admitted
            ),
            ranked=tuple(ranked),
            selected_cids=selected_cids,
            rejected_cids=tuple(rejected_cids),
            considered_count=len(considered),
            filtered_count=filtered_count,
            ranked_count=len(ranked),
            selected_count=len(selected_cids),
            rejected_count=len(rejected_cids),
            reason_counts=reason_counts,
            budgets=budgets,
            gaps=tuple(gaps),
            retrieval_rank_used_for_authority=False,
            query_digest=query.query_digest(),
            policy_digest=policy_digest,
        )


def select_applicable_proofs(
    envelopes: Sequence[AttestedProofEnvelope],
    query: ProofApplicabilityQuery,
    *,
    trust_policy: ProofTrustPolicy | None = None,
    revocation_snapshot: ProofRevocationSnapshot | None = None,
    revoked_target_cids: Sequence[str] = (),
    advisory_scores: Mapping[str, float] | None = None,
) -> ProofApplicabilityResult:
    """Module-level helper for :meth:`ProofApplicabilityFilter.select`."""

    return ProofApplicabilityFilter(
        trust_policy=trust_policy,
        revocation_snapshot=revocation_snapshot,
        revoked_target_cids=tuple(revoked_target_cids),
    ).select(envelopes, query, advisory_scores=advisory_scores)


def hard_filter_dimensions() -> tuple[str, ...]:
    """Return the closed, documented hard-filter dimension vocabulary."""

    return PROOF_HARD_FILTER_DIMENSIONS


__all__ = [
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_MAX_SELECTED",
    "HARD_FILTER_ASSESSMENT_SCHEMA_VERSION",
    "MAX_SELECTION_BUDGET",
    "PROOF_APPLICABILITY_FILTER_INTERFACE",
    "PROOF_APPLICABILITY_FILTER_SCHEMA_VERSION",
    "PROOF_APPLICABILITY_QUERY_SCHEMA_VERSION",
    "PROOF_APPLICABILITY_RESULT_SCHEMA_VERSION",
    "PROOF_HARD_FILTER_DIMENSIONS",
    "RANKED_CANDIDATE_SCHEMA_VERSION",
    "FilterDisposition",
    "HardFilterAssessment",
    "ProofApplicabilityError",
    "ProofApplicabilityFilter",
    "ProofApplicabilityQuery",
    "ProofApplicabilityResult",
    "RankedCandidate",
    "SelectionDisposition",
    "hard_filter_dimensions",
    "hard_filter_envelope",
    "select_applicable_proofs",
]
