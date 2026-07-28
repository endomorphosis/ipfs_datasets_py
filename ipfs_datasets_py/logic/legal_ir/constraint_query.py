"""Select applicable Legal constraints (``LegalConstraintQuery@1``).

Hard-scopes Legal provisions for a concrete invocation context using
jurisdiction/territory/subject matter, authority hierarchy and precedence,
enactment/effective/repeal windows, amendment/supersession, definitions,
cross-references, exceptions, actor/subject/resource/purpose/threshold facts,
premise taint/provenance, and competing-authority resolution.

Non-goals / fail-closed invariants:

* Retrieval or similarity rank is advisory only and **never** selects authority.
* Hard applicability filters always run before any bounded ranking/budget.
* Unresolved conflict, applicability, or corpus coverage yields review/abstain
  (never silent allow).
* Contradictions are preserved in the result; they are never discarded to force
  a unique winner.
* Domain-native Legal outcomes remain Legal; they do not grant Security
  authorization or execution admission.

Interfaces:

* ``LegalConstraintQuery@1`` — immutable query context + selection entry point.
* ``LegalApplicabilityEvidence@1`` — Legal-domain applicability receipt that
  composes shared ``ApplicabilityEvidence@1`` selectors without flattening
  Legal norms into a neutral formula.

This leaf may *call* temporal authority, premise-security, and shared
constraint contracts.  It does not edit the proof corpus, Security query,
exports, or registries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
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


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LEGAL_CONSTRAINT_QUERY_INTERFACE: Final = "LegalConstraintQuery@1"
LEGAL_APPLICABILITY_EVIDENCE_INTERFACE: Final = "LegalApplicabilityEvidence@1"
LEGAL_CONSTRAINT_QUERY_SCHEMA_VERSION: Final = "legal-constraint-query/v1"
LEGAL_APPLICABILITY_EVIDENCE_SCHEMA_VERSION: Final = (
    "legal-applicability-evidence/v1"
)
LEGAL_CONSTRAINT_RECORD_SCHEMA_VERSION: Final = "legal-constraint-record/v1"
LEGAL_CONSTRAINT_SELECTION_SCHEMA_VERSION: Final = (
    "legal-constraint-selection/v1"
)

LEGAL_CONSTRAINT_QUERY_IDENTITY_DOMAIN: Final = "legal-constraint-query"
LEGAL_APPLICABILITY_EVIDENCE_IDENTITY_DOMAIN: Final = (
    "legal-applicability-evidence"
)
LEGAL_CONSTRAINT_SELECTION_IDENTITY_DOMAIN: Final = "legal-constraint-selection"

MAX_COLLECTION_ITEMS: Final = 1_024
MAX_STRING_CHARS: Final = 16_384
MAX_IDENTIFIER_CHARS: Final = 256
DEFAULT_SELECTION_BUDGET: Final = 64

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WILDCARDS: Final = frozenset({"*", "any", "all", ""})

# Hard-filter dimensions (order is documentary; evaluation is independent).
LEGAL_HARD_FILTER_DIMENSIONS: Final[tuple[str, ...]] = (
    "jurisdiction",
    "territory",
    "subject_matter",
    "authority",
    "temporal",
    "actor",
    "subject",
    "resource",
    "purpose",
    "threshold",
    "provenance",
    "premise_taint",
    "definition_refs",
    "cross_references",
    "exceptions",
)

_SCOPE_MATCH_FIELDS: Final[tuple[str, ...]] = (
    "jurisdiction",
    "territory",
    "subject_matter",
    "actor",
    "subject",
    "resource",
    "purpose",
)

_OPPOSED_MODALITY_PAIRS: Final[frozenset[frozenset[str]]] = frozenset(
    {
        frozenset({"prohibition", "permission"}),
        frozenset({"prohibition", "power"}),
        frozenset({"prohibition", "obligation"}),
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LegalConstraintQueryError(ValueError):
    """Raised when a Legal constraint query contract is malformed."""


class LegalModality(str, Enum):
    """Deontic / definitional role of one Legal constraint record."""

    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    POWER = "power"
    EXCEPTION = "exception"
    DEFINITION = "definition"
    INVARIANT = "invariant"
    UNSPECIFIED = "unspecified"


class LegalConstraintDisposition(str, Enum):
    """Per-constraint outcome after hard filters and relationship resolution."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    EXPIRED = "expired"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    REPEALED = "repealed"
    SUPERSEDED = "superseded"
    DEFEATED = "defeated"
    CONFLICTING = "conflicting"
    INDETERMINATE = "indeterminate"
    REVIEW_REQUIRED = "review_required"
    TAINTED = "tainted"
    COVERAGE_GAP = "coverage_gap"
    ABSTAIN = "abstain"


class LegalSelectionDisposition(str, Enum):
    """Overall selection outcome for one query against a candidate set."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"
    COVERAGE_GAP = "coverage_gap"
    REVIEW_REQUIRED = "review_required"
    ABSTAIN = "abstain"
    UNSUPPORTED = "unsupported"


class LegalPremiseTaintStatus(str, Enum):
    """Declared premise/provenance trust for one constraint record."""

    CLEAN = "clean"
    TAINTED = "tainted"
    UNKNOWN = "unknown"
    UNREVIEWED = "unreviewed"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise LegalConstraintQueryError(
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
        raise LegalConstraintQueryError(f"{name} must be a string")
    if value != value.strip() or "\x00" in value:
        raise LegalConstraintQueryError(
            f"{name} must not contain surrounding whitespace or NUL"
        )
    if not allow_empty and not value:
        raise LegalConstraintQueryError(f"{name} must not be empty")
    if len(value) > max_chars:
        raise LegalConstraintQueryError(f"{name} exceeds maximum length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value is None:
        return ""
    return _text(value, name, allow_empty=True)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise LegalConstraintQueryError(f"{name} is not a valid identifier")
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
        raise LegalConstraintQueryError(
            f"{name} must be a sha256:<hex> digest or empty"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LegalConstraintQueryError(f"{name} must be a mapping")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise LegalConstraintQueryError(f"{name} must be a sequence")
    if len(value) > MAX_COLLECTION_ITEMS:
        raise LegalConstraintQueryError(f"{name} exceeds collection bound")
    return value


def _unique_sorted_ids(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = (_identifier(value, name),)
        return items
    seq = _sequence(value, name)
    items = tuple(_identifier(item, name) for item in seq)
    unique = tuple(sorted(set(items)))
    if len(unique) != len(items):
        # Allow unsorted input by normalizing, but reject true duplicates.
        if len(items) != len(set(items)):
            raise LegalConstraintQueryError(f"{name} must be unique")
    return unique


def _unique_sorted_texts(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = _text(value, name)
        if text.lower() in _WILDCARDS:
            raise LegalConstraintQueryError(
                f"{name} must contain explicit values, not a wildcard"
            )
        return (text,)
    seq = _sequence(value, name)
    items: list[str] = []
    for item in seq:
        text = _text(item, name)
        if text.lower() in _WILDCARDS:
            raise LegalConstraintQueryError(
                f"{name} must contain explicit values, not a wildcard"
            )
        items.append(text)
    if len(items) != len(set(items)):
        raise LegalConstraintQueryError(f"{name} must be unique")
    return tuple(sorted(items))


def _non_negative_int(value: Any, name: str, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegalConstraintQueryError(f"{name} must be an int")
    if value < 0:
        raise LegalConstraintQueryError(f"{name} must be non-negative")
    return value


def _bool(value: Any, name: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise LegalConstraintQueryError(f"{name} must be a bool")
    return value


def _enum_value(value: Any, enum_cls: type[Enum], name: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if not isinstance(value, str):
        raise LegalConstraintQueryError(f"{name} must be a string or {enum_cls.__name__}")
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise LegalConstraintQueryError(
            f"unsupported {name}: {value!r}"
        ) from exc


def _frozen_map(value: Any, name: str) -> FrozenMap:
    if isinstance(value, FrozenMap):
        return value
    if value is None:
        return FrozenMap({})
    if not isinstance(value, Mapping):
        raise LegalConstraintQueryError(f"{name} must be a mapping")
    return FrozenMap(dict(value))


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, int) and not isinstance(value, bool):
        # Epoch milliseconds or seconds; treat large values as ms.
        seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
        try:
            return datetime.utcfromtimestamp(seconds).date()
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _DATE_RE.fullmatch(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    # Allow ISO datetime prefixes.
    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _date_text(value: Any, name: str) -> str:
    if value is None or value == "":
        return ""
    parsed = _parse_date(value)
    if parsed is None:
        # Keep raw string only when it is already a calendar date; else fail.
        if isinstance(value, str) and _DATE_RE.fullmatch(value.strip()):
            raise LegalConstraintQueryError(f"{name} is not a valid date")
        if isinstance(value, str):
            # Allow opaque temporal tokens only when empty/normalized fails.
            raise LegalConstraintQueryError(f"{name} is not a valid date")
        raise LegalConstraintQueryError(f"{name} is not a valid date")
    return parsed.isoformat()


def _modality_atom(value: Any) -> LegalModality:
    if value is None or value == "":
        return LegalModality.UNSPECIFIED
    if isinstance(value, LegalModality):
        return value
    raw = _text(str(value), "modality").lower().replace("-", "_")
    aliases = {
        "duty": LegalModality.OBLIGATION,
        "obligatory": LegalModality.OBLIGATION,
        "obligation": LegalModality.OBLIGATION,
        "forbidden": LegalModality.PROHIBITION,
        "prohibited": LegalModality.PROHIBITION,
        "prohibition": LegalModality.PROHIBITION,
        "permission": LegalModality.PERMISSION,
        "permitted": LegalModality.PERMISSION,
        "right": LegalModality.PERMISSION,
        "power": LegalModality.POWER,
        "legal_power": LegalModality.POWER,
        "exception": LegalModality.EXCEPTION,
        "definition": LegalModality.DEFINITION,
        "defined_term": LegalModality.DEFINITION,
        "invariant": LegalModality.INVARIANT,
        "unspecified": LegalModality.UNSPECIFIED,
    }
    modality = aliases.get(raw)
    if modality is None:
        raise LegalConstraintQueryError(f"unsupported modality: {value!r}")
    return modality


def _scope_contains(
    allowed: tuple[str, ...],
    query_value: str,
    *,
    universal: bool,
) -> bool | None:
    """Return True/False for hard match, or None when the scope is open."""

    if universal:
        return True
    if not allowed:
        return None
    if not query_value:
        return None
    return query_value in allowed


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalConstraintRecord:
    """One candidate Legal provision with hard-filter and relationship fields.

    ``retrieval_rank`` is retained only as advisory diagnostics.  Selection
    never uses it to establish applicability or authority.
    """

    constraint_id: str
    modality: LegalModality = LegalModality.UNSPECIFIED
    jurisdictions: tuple[str, ...] = ()
    territories: tuple[str, ...] = ()
    subject_matters: tuple[str, ...] = ()
    authority_id: str = ""
    hierarchy_rank: int = 0
    precedence: int = 0
    enacted_date: str = ""
    effective_from: str = ""
    effective_until: str = ""
    repeal_date: str = ""
    superseded_date: str = ""
    amends: tuple[str, ...] = ()
    amended_by: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: str = ""
    repealed_by: str = ""
    definition_refs: tuple[str, ...] = ()
    cross_references: tuple[str, ...] = ()
    exception_ids: tuple[str, ...] = ()
    exception_to: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    actors: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    purposes: tuple[str, ...] = ()
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    source_ref_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    premise_taint: LegalPremiseTaintStatus = LegalPremiseTaintStatus.UNKNOWN
    trusted_source: bool = False
    reviewed: bool = False
    conflict_key: str = ""
    statement: str = ""
    law_version_id: str = ""
    corpus_id: str = ""
    retrieval_rank: int | None = None
    retrieval_score: float | None = None
    mandatory: bool = True
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGAL_CONSTRAINT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "constraint_id", _identifier(self.constraint_id, "constraint_id")
        )
        object.__setattr__(self, "modality", _modality_atom(self.modality))
        object.__setattr__(
            self, "jurisdictions", _unique_sorted_texts(self.jurisdictions, "jurisdictions")
        )
        object.__setattr__(
            self, "territories", _unique_sorted_texts(self.territories, "territories")
        )
        object.__setattr__(
            self,
            "subject_matters",
            _unique_sorted_texts(self.subject_matters, "subject_matters"),
        )
        object.__setattr__(
            self, "authority_id", _optional_identifier(self.authority_id, "authority_id")
        )
        object.__setattr__(
            self,
            "hierarchy_rank",
            _non_negative_int(self.hierarchy_rank, "hierarchy_rank"),
        )
        object.__setattr__(
            self, "precedence", _non_negative_int(self.precedence, "precedence")
        )
        object.__setattr__(
            self, "enacted_date", _date_text(self.enacted_date, "enacted_date")
            if self.enacted_date
            else ""
        )
        for name in (
            "effective_from",
            "effective_until",
            "repeal_date",
            "superseded_date",
        ):
            raw = getattr(self, name)
            object.__setattr__(self, name, _date_text(raw, name) if raw else "")
        for name in (
            "amends",
            "amended_by",
            "supersedes",
            "definition_refs",
            "cross_references",
            "exception_ids",
            "exception_to",
            "conflicts_with",
            "source_ref_ids",
            "provenance_ids",
        ):
            object.__setattr__(self, name, _unique_sorted_ids(getattr(self, name), name))
        object.__setattr__(
            self, "superseded_by", _optional_identifier(self.superseded_by, "superseded_by")
        )
        object.__setattr__(
            self, "repealed_by", _optional_identifier(self.repealed_by, "repealed_by")
        )
        object.__setattr__(self, "actors", _unique_sorted_texts(self.actors, "actors"))
        object.__setattr__(
            self, "subjects", _unique_sorted_texts(self.subjects, "subjects")
        )
        object.__setattr__(
            self, "resources", _unique_sorted_texts(self.resources, "resources")
        )
        object.__setattr__(
            self, "purposes", _unique_sorted_texts(self.purposes, "purposes")
        )
        thresholds = self.thresholds
        if isinstance(thresholds, FrozenMap):
            thresholds_map = thresholds.to_dict()
        elif thresholds is None:
            thresholds_map = {}
        elif isinstance(thresholds, Mapping):
            thresholds_map = dict(thresholds)
        else:
            raise LegalConstraintQueryError("thresholds must be a mapping")
        object.__setattr__(self, "thresholds", MappingProxyType(thresholds_map))
        object.__setattr__(
            self,
            "premise_taint",
            _enum_value(self.premise_taint, LegalPremiseTaintStatus, "premise_taint"),
        )
        object.__setattr__(
            self, "trusted_source", _bool(self.trusted_source, "trusted_source")
        )
        object.__setattr__(self, "reviewed", _bool(self.reviewed, "reviewed"))
        object.__setattr__(
            self,
            "conflict_key",
            _optional_text(self.conflict_key, "conflict_key"),
        )
        object.__setattr__(
            self, "statement", _optional_text(self.statement, "statement")
        )
        object.__setattr__(
            self,
            "law_version_id",
            _optional_identifier(self.law_version_id, "law_version_id"),
        )
        object.__setattr__(
            self, "corpus_id", _optional_identifier(self.corpus_id, "corpus_id")
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
                raise LegalConstraintQueryError("retrieval_score must be a finite number")
            score = float(self.retrieval_score)
            if score != score or score in (float("inf"), float("-inf")):
                raise LegalConstraintQueryError("retrieval_score must be finite")
            object.__setattr__(self, "retrieval_score", score)
        object.__setattr__(self, "mandatory", _bool(self.mandatory, "mandatory", default=True))
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != LEGAL_CONSTRAINT_RECORD_SCHEMA_VERSION:
            raise LegalConstraintQueryError(
                f"unsupported legal constraint record schema: {self.schema_version!r}"
            )
        start = _parse_date(self.effective_from)
        end = _parse_date(self.effective_until or self.repeal_date or self.superseded_date)
        if start is not None and end is not None and end < start:
            raise LegalConstraintQueryError(
                f"constraint {self.constraint_id!r} has effective window ending before start"
            )

    @property
    def applicability_key(self) -> str:
        return self.conflict_key or self.constraint_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "actors": list(self.actors),
            "amended_by": list(self.amended_by),
            "amends": list(self.amends),
            "authority_id": self.authority_id,
            "conflict_key": self.conflict_key,
            "conflicts_with": list(self.conflicts_with),
            "constraint_id": self.constraint_id,
            "corpus_id": self.corpus_id,
            "cross_references": list(self.cross_references),
            "definition_refs": list(self.definition_refs),
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "enacted_date": self.enacted_date,
            "exception_ids": list(self.exception_ids),
            "exception_to": list(self.exception_to),
            "hierarchy_rank": self.hierarchy_rank,
            "jurisdictions": list(self.jurisdictions),
            "law_version_id": self.law_version_id,
            "mandatory": self.mandatory,
            "metadata": self.metadata.to_dict(),
            "modality": self.modality.value,
            "precedence": self.precedence,
            "premise_taint": self.premise_taint.value,
            "provenance_ids": list(self.provenance_ids),
            "purposes": list(self.purposes),
            "repeal_date": self.repeal_date,
            "repealed_by": self.repealed_by,
            "resources": list(self.resources),
            "retrieval_rank": self.retrieval_rank,
            "retrieval_score": self.retrieval_score,
            "reviewed": self.reviewed,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
            "subject_matters": list(self.subject_matters),
            "subjects": list(self.subjects),
            "superseded_by": self.superseded_by,
            "superseded_date": self.superseded_date,
            "supersedes": list(self.supersedes),
            "territories": list(self.territories),
            "thresholds": dict(self.thresholds),
            "trusted_source": self.trusted_source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalConstraintRecord":
        value = _mapping(value, "legal constraint record")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actors",
                    "amended_by",
                    "amends",
                    "authority_id",
                    "conflict_key",
                    "conflicts_with",
                    "constraint_id",
                    "corpus_id",
                    "cross_references",
                    "definition_refs",
                    "effective_from",
                    "effective_until",
                    "enacted_date",
                    "exception_ids",
                    "exception_to",
                    "hierarchy_rank",
                    "jurisdictions",
                    "law_version_id",
                    "mandatory",
                    "metadata",
                    "modality",
                    "precedence",
                    "premise_taint",
                    "provenance_ids",
                    "purposes",
                    "repeal_date",
                    "repealed_by",
                    "resources",
                    "retrieval_rank",
                    "retrieval_score",
                    "reviewed",
                    "schema_version",
                    "source_ref_ids",
                    "statement",
                    "subject_matters",
                    "subjects",
                    "superseded_by",
                    "superseded_date",
                    "supersedes",
                    "territories",
                    "thresholds",
                    "trusted_source",
                    # Common aliases accepted at the boundary.
                    "jurisdiction",
                    "territory",
                    "subject_matter",
                    "actor",
                    "subject",
                    "resource",
                    "purpose",
                    "provision_id",
                    "id",
                }
            ),
            "legal constraint record",
        )
        constraint_id = value.get("constraint_id") or value.get("provision_id") or value.get("id")
        jurisdictions = value.get("jurisdictions", value.get("jurisdiction", ()))
        territories = value.get("territories", value.get("territory", ()))
        subject_matters = value.get("subject_matters", value.get("subject_matter", ()))
        actors = value.get("actors", value.get("actor", ()))
        subjects = value.get("subjects", value.get("subject", ()))
        resources = value.get("resources", value.get("resource", ()))
        purposes = value.get("purposes", value.get("purpose", ()))
        return cls(
            constraint_id=constraint_id or "",
            modality=value.get("modality", LegalModality.UNSPECIFIED.value),
            jurisdictions=jurisdictions if not isinstance(jurisdictions, str) else (jurisdictions,),
            territories=territories if not isinstance(territories, str) else (territories,),
            subject_matters=(
                subject_matters
                if not isinstance(subject_matters, str)
                else (subject_matters,)
            ),
            authority_id=value.get("authority_id", ""),
            hierarchy_rank=value.get("hierarchy_rank", 0),
            precedence=value.get("precedence", 0),
            enacted_date=value.get("enacted_date", ""),
            effective_from=value.get("effective_from", ""),
            effective_until=value.get("effective_until", ""),
            repeal_date=value.get("repeal_date", ""),
            superseded_date=value.get("superseded_date", ""),
            amends=value.get("amends", ()),
            amended_by=value.get("amended_by", ()),
            supersedes=value.get("supersedes", ()),
            superseded_by=value.get("superseded_by", ""),
            repealed_by=value.get("repealed_by", ""),
            definition_refs=value.get("definition_refs", ()),
            cross_references=value.get("cross_references", ()),
            exception_ids=value.get("exception_ids", ()),
            exception_to=value.get("exception_to", ()),
            conflicts_with=value.get("conflicts_with", ()),
            actors=actors if not isinstance(actors, str) else (actors,),
            subjects=subjects if not isinstance(subjects, str) else (subjects,),
            resources=resources if not isinstance(resources, str) else (resources,),
            purposes=purposes if not isinstance(purposes, str) else (purposes,),
            thresholds=value.get("thresholds", {}),
            source_ref_ids=value.get("source_ref_ids", ()),
            provenance_ids=value.get("provenance_ids", ()),
            premise_taint=value.get(
                "premise_taint", LegalPremiseTaintStatus.UNKNOWN.value
            ),
            trusted_source=value.get("trusted_source", False),
            reviewed=value.get("reviewed", False),
            conflict_key=value.get("conflict_key", ""),
            statement=value.get("statement", ""),
            law_version_id=value.get("law_version_id", ""),
            corpus_id=value.get("corpus_id", ""),
            retrieval_rank=value.get("retrieval_rank", None),
            retrieval_score=value.get("retrieval_score", None),
            mandatory=value.get("mandatory", True),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", LEGAL_CONSTRAINT_RECORD_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalConstraintAssessment:
    """Disposition of one candidate after hard filters / relationship resolution."""

    constraint_id: str
    disposition: LegalConstraintDisposition
    active: bool
    reason_codes: tuple[str, ...] = ()
    matched_dimensions: tuple[str, ...] = ()
    rejected_dimensions: tuple[str, ...] = ()
    defeated_by: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    retrieval_rank: int | None = None
    hierarchy_rank: int = 0
    precedence: int = 0
    modality: LegalModality = LegalModality.UNSPECIFIED
    record: LegalConstraintRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "constraint_id", _identifier(self.constraint_id, "constraint_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum_value(self.disposition, LegalConstraintDisposition, "disposition"),
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
            tuple(sorted(set(_text(item, "matched_dimensions") for item in self.matched_dimensions))),
        )
        object.__setattr__(
            self,
            "rejected_dimensions",
            tuple(
                sorted(
                    set(_text(item, "rejected_dimensions") for item in self.rejected_dimensions)
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
            self,
            "hierarchy_rank",
            _non_negative_int(self.hierarchy_rank, "hierarchy_rank"),
        )
        object.__setattr__(
            self, "precedence", _non_negative_int(self.precedence, "precedence")
        )
        object.__setattr__(self, "modality", _modality_atom(self.modality))
        if self.record is not None and not isinstance(self.record, LegalConstraintRecord):
            raise LegalConstraintQueryError("record must be a LegalConstraintRecord")

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "conflicts_with": list(self.conflicts_with),
            "constraint_id": self.constraint_id,
            "defeated_by": list(self.defeated_by),
            "disposition": self.disposition.value,
            "hierarchy_rank": self.hierarchy_rank,
            "matched_dimensions": list(self.matched_dimensions),
            "modality": self.modality.value,
            "precedence": self.precedence,
            "reason_codes": list(self.reason_codes),
            "record": self.record.to_dict() if self.record is not None else None,
            "rejected_dimensions": list(self.rejected_dimensions),
            "retrieval_rank": self.retrieval_rank,
        }


@dataclass(frozen=True, slots=True)
class LegalContradiction:
    """Preserved contradiction between two or more selected Legal constraints."""

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
            raise LegalConstraintQueryError(
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
class LegalConstraintQuery:
    """``LegalConstraintQuery@1`` — bound Legal applicability query context.

    Selection entry point is :meth:`select`.  Ranking inputs may be supplied on
    candidates for diagnostics, but hard filters and authority/precedence
    resolution alone determine applicability.
    """

    INTERFACE: ClassVar[str] = LEGAL_CONSTRAINT_QUERY_INTERFACE

    query_id: str
    jurisdiction: str
    as_of: str
    territory: str = ""
    subject_matter: str = ""
    authority_id: str = ""
    actor: str = ""
    subject: str = ""
    resource: str = ""
    purpose: str = ""
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    corpus_id: str = ""
    corpus_root_digest: str = ""
    policy_id: str = ""
    invocation_digest: str = ""
    selection_budget: int = DEFAULT_SELECTION_BUDGET
    require_reviewed: bool = True
    require_trusted_source: bool = True
    require_provenance: bool = True
    include_emergency: bool = True
    world_policy_kind: WorldPolicyKind = WorldPolicyKind.CLOSED
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGAL_CONSTRAINT_QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "jurisdiction", _text(self.jurisdiction, "jurisdiction")
        )
        as_of = _date_text(self.as_of, "as_of")
        if not as_of:
            raise LegalConstraintQueryError("as_of is required")
        object.__setattr__(self, "as_of", as_of)
        for name in (
            "territory",
            "subject_matter",
            "actor",
            "subject",
            "resource",
            "purpose",
        ):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name)
            )
        object.__setattr__(
            self, "authority_id", _optional_identifier(self.authority_id, "authority_id")
        )
        thresholds = self.thresholds
        if isinstance(thresholds, FrozenMap):
            thresholds_map = thresholds.to_dict()
        elif thresholds is None:
            thresholds_map = {}
        elif isinstance(thresholds, Mapping):
            thresholds_map = dict(thresholds)
        else:
            raise LegalConstraintQueryError("thresholds must be a mapping")
        object.__setattr__(self, "thresholds", MappingProxyType(thresholds_map))
        object.__setattr__(
            self, "corpus_id", _optional_identifier(self.corpus_id, "corpus_id")
        )
        object.__setattr__(
            self,
            "corpus_root_digest",
            _digest_or_empty(self.corpus_root_digest, "corpus_root_digest"),
        )
        object.__setattr__(
            self, "policy_id", _optional_identifier(self.policy_id, "policy_id")
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
            raise LegalConstraintQueryError("selection_budget must be positive")
        for name in (
            "require_reviewed",
            "require_trusted_source",
            "require_provenance",
            "include_emergency",
        ):
            object.__setattr__(
                self, name, _bool(getattr(self, name), name, default=True)
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
        if self.schema_version != LEGAL_CONSTRAINT_QUERY_SCHEMA_VERSION:
            raise LegalConstraintQueryError(
                f"unsupported legal constraint query schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "as_of": self.as_of,
            "authority_id": self.authority_id,
            "corpus_id": self.corpus_id,
            "corpus_root_digest": self.corpus_root_digest,
            "include_emergency": self.include_emergency,
            "interface": self.INTERFACE,
            "invocation_digest": self.invocation_digest,
            "jurisdiction": self.jurisdiction,
            "metadata": self.metadata.to_dict(),
            "policy_id": self.policy_id,
            "purpose": self.purpose,
            "query_id": self.query_id,
            "require_provenance": self.require_provenance,
            "require_reviewed": self.require_reviewed,
            "require_trusted_source": self.require_trusted_source,
            "resource": self.resource,
            "schema_version": self.schema_version,
            "selection_budget": self.selection_budget,
            "subject": self.subject,
            "subject_matter": self.subject_matter,
            "territory": self.territory,
            "thresholds": dict(self.thresholds),
            "world_policy_kind": self.world_policy_kind.value,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=LEGAL_CONSTRAINT_QUERY_IDENTITY_DOMAIN,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalConstraintQuery":
        value = _mapping(value, "legal constraint query")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actor",
                    "as_of",
                    "authority_id",
                    "corpus_id",
                    "corpus_root_digest",
                    "include_emergency",
                    "interface",
                    "invocation_digest",
                    "jurisdiction",
                    "metadata",
                    "policy_id",
                    "purpose",
                    "query_id",
                    "require_provenance",
                    "require_reviewed",
                    "require_trusted_source",
                    "resource",
                    "schema_version",
                    "selection_budget",
                    "subject",
                    "subject_matter",
                    "territory",
                    "thresholds",
                    "world_policy_kind",
                }
            ),
            "legal constraint query",
        )
        interface = value.get("interface", LEGAL_CONSTRAINT_QUERY_INTERFACE)
        if interface != LEGAL_CONSTRAINT_QUERY_INTERFACE:
            raise LegalConstraintQueryError(
                f"unknown legal constraint query interface: {interface!r}"
            )
        return cls(
            query_id=value.get("query_id", ""),
            jurisdiction=value.get("jurisdiction", ""),
            as_of=value.get("as_of", ""),
            territory=value.get("territory", ""),
            subject_matter=value.get("subject_matter", ""),
            authority_id=value.get("authority_id", ""),
            actor=value.get("actor", ""),
            subject=value.get("subject", ""),
            resource=value.get("resource", ""),
            purpose=value.get("purpose", ""),
            thresholds=value.get("thresholds", {}),
            corpus_id=value.get("corpus_id", ""),
            corpus_root_digest=value.get("corpus_root_digest", ""),
            policy_id=value.get("policy_id", ""),
            invocation_digest=value.get("invocation_digest", ""),
            selection_budget=value.get("selection_budget", DEFAULT_SELECTION_BUDGET),
            require_reviewed=value.get("require_reviewed", True),
            require_trusted_source=value.get("require_trusted_source", True),
            require_provenance=value.get("require_provenance", True),
            include_emergency=value.get("include_emergency", True),
            world_policy_kind=value.get(
                "world_policy_kind", WorldPolicyKind.CLOSED.value
            ),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", LEGAL_CONSTRAINT_QUERY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "LegalConstraintQuery":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise LegalConstraintQueryError(
                "legal constraint query must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "legal constraint query"))

    def select(
        self,
        candidates: Sequence[LegalConstraintRecord | Mapping[str, Any]],
        *,
        known_definition_ids: Sequence[str] | None = None,
        known_cross_reference_ids: Sequence[str] | None = None,
        temporal_applicability: Mapping[str, Any] | None = None,
    ) -> "LegalConstraintSelectionResult":
        """Select applicable Legal constraints under hard filters and authority rules."""

        return select_applicable_legal_constraints(
            self,
            candidates,
            known_definition_ids=known_definition_ids,
            known_cross_reference_ids=known_cross_reference_ids,
            temporal_applicability=temporal_applicability,
        )


@dataclass(frozen=True, slots=True)
class LegalApplicabilityEvidence:
    """``LegalApplicabilityEvidence@1`` — Legal hard-filter applicability receipt.

    Ranking alone never produces an ``APPLICABLE`` disposition.  Coverage gaps,
    conflicts, taint, and unresolved references remain explicit.
    """

    INTERFACE: ClassVar[str] = LEGAL_APPLICABILITY_EVIDENCE_INTERFACE

    evidence_id: str
    status: LegalSelectionDisposition
    query_id: str
    query_digest: str
    selectors: tuple[ApplicabilitySelector, ...]
    matched_selector_ids: tuple[str, ...] = ()
    rejected_selector_ids: tuple[str, ...] = ()
    coverage_gaps: tuple[CoverageGap, ...] = ()
    assessments: tuple[LegalConstraintAssessment, ...] = ()
    contradictions: tuple[LegalContradiction, ...] = ()
    selected_constraint_ids: tuple[str, ...] = ()
    considered_count: int = 0
    hard_filtered_count: int = 0
    selected_count: int = 0
    selection_budget: int = 0
    selection_method: PremiseSelectionMethod = PremiseSelectionMethod.HARD_FILTER
    retrieval_rank_used_for_authority: bool = False
    authority_selection_keys: tuple[str, ...] = (
        "hierarchy_rank",
        "precedence",
        "constraint_id",
    )
    shared_applicability: ApplicabilityEvidence | None = None
    selected_premises: SelectedPremiseSet | None = None
    temporal_proof_safe: bool | None = None
    notes: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGAL_APPLICABILITY_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self,
            "status",
            _enum_value(self.status, LegalSelectionDisposition, "status"),
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
            raise LegalConstraintQueryError("selector IDs must be unique")
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
            raise LegalConstraintQueryError(
                "matched_selector_ids reference unknown selectors"
            )
        if set(self.rejected_selector_ids) - known:
            raise LegalConstraintQueryError(
                "rejected_selector_ids reference unknown selectors"
            )
        if set(self.matched_selector_ids) & set(self.rejected_selector_ids):
            raise LegalConstraintQueryError(
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
            if isinstance(item, LegalConstraintAssessment)
            else LegalConstraintAssessment(**dict(item))  # type: ignore[arg-type]
            for item in _sequence(self.assessments, "assessments")
        )
        object.__setattr__(
            self,
            "assessments",
            tuple(sorted(assessments, key=lambda item: item.constraint_id)),
        )
        contradictions = tuple(
            item
            if isinstance(item, LegalContradiction)
            else LegalContradiction(**dict(item))  # type: ignore[arg-type]
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
            raise LegalConstraintQueryError(
                "retrieval rank must never select authority"
            )
        keys = tuple(
            _identifier(item, "authority_selection_keys")
            for item in _sequence(
                self.authority_selection_keys, "authority_selection_keys"
            )
        )
        if "retrieval_rank" in keys or "retrieval_score" in keys:
            raise LegalConstraintQueryError(
                "authority_selection_keys must not include retrieval rank/score"
            )
        object.__setattr__(self, "authority_selection_keys", keys)
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
                raise LegalConstraintQueryError(
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
                raise LegalConstraintQueryError(
                    "selected_premises must be SelectedPremiseSet"
                )
        if self.temporal_proof_safe is not None and not isinstance(
            self.temporal_proof_safe, bool
        ):
            raise LegalConstraintQueryError("temporal_proof_safe must be a bool or null")
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != LEGAL_APPLICABILITY_EVIDENCE_SCHEMA_VERSION:
            raise LegalConstraintQueryError(
                f"unsupported legal applicability evidence schema: {self.schema_version!r}"
            )
        # Fail-closed consistency.
        if self.status is LegalSelectionDisposition.APPLICABLE:
            if self.rejected_selector_ids:
                raise LegalConstraintQueryError(
                    "APPLICABLE evidence cannot retain rejected selectors"
                )
            if self.coverage_gaps:
                raise LegalConstraintQueryError(
                    "APPLICABLE evidence cannot retain coverage gaps"
                )
            unresolved = [
                item
                for item in self.contradictions
                if not item.resolved
            ]
            if unresolved:
                raise LegalConstraintQueryError(
                    "APPLICABLE evidence cannot retain unresolved contradictions"
                )
        if (
            self.status is LegalSelectionDisposition.COVERAGE_GAP
            and not self.coverage_gaps
        ):
            raise LegalConstraintQueryError(
                "COVERAGE_GAP status requires at least one coverage gap"
            )

    @property
    def grants_security_authorization(self) -> bool:
        return False

    @property
    def grants_execution_authority(self) -> bool:
        return False

    @property
    def allows_action(self) -> bool:
        """Whether Legal selection affirms applicable norms without abstaining."""

        return self.status is LegalSelectionDisposition.APPLICABLE

    @property
    def abstains(self) -> bool:
        return self.status in {
            LegalSelectionDisposition.ABSTAIN,
            LegalSelectionDisposition.REVIEW_REQUIRED,
            LegalSelectionDisposition.CONFLICT,
            LegalSelectionDisposition.INDETERMINATE,
            LegalSelectionDisposition.COVERAGE_GAP,
            LegalSelectionDisposition.UNSUPPORTED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessments": [item.to_dict() for item in self.assessments],
            "authority_selection_keys": list(self.authority_selection_keys),
            "considered_count": self.considered_count,
            "contradictions": [item.to_dict() for item in self.contradictions],
            "coverage_gaps": [item.to_dict() for item in self.coverage_gaps],
            "evidence_id": self.evidence_id,
            "grants_execution_authority": False,
            "grants_security_authorization": False,
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
            "temporal_proof_safe": self.temporal_proof_safe,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=LEGAL_APPLICABILITY_EVIDENCE_IDENTITY_DOMAIN,
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

    def to_shared_applicability_status(self) -> ApplicabilityStatus:
        return _to_shared_status(self.status)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalApplicabilityEvidence":
        value = _mapping(value, "legal applicability evidence")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assessments",
                    "authority_selection_keys",
                    "considered_count",
                    "contradictions",
                    "coverage_gaps",
                    "evidence_id",
                    "grants_execution_authority",
                    "grants_security_authorization",
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
                    "temporal_proof_safe",
                }
            ),
            "legal applicability evidence",
        )
        interface = value.get("interface", LEGAL_APPLICABILITY_EVIDENCE_INTERFACE)
        if interface != LEGAL_APPLICABILITY_EVIDENCE_INTERFACE:
            raise LegalConstraintQueryError(
                f"unknown legal applicability evidence interface: {interface!r}"
            )
        if value.get("retrieval_rank_used_for_authority"):
            raise LegalConstraintQueryError(
                "retrieval rank must never select authority"
            )
        shared = value.get("shared_applicability")
        premises = value.get("selected_premises")
        assessments_raw = value.get("assessments", ())
        assessments: list[LegalConstraintAssessment] = []
        for item in _sequence(assessments_raw, "assessments"):
            if isinstance(item, LegalConstraintAssessment):
                assessments.append(item)
            else:
                mapping = _mapping(item, "assessment")
                record = mapping.get("record")
                assessments.append(
                    LegalConstraintAssessment(
                        constraint_id=mapping.get("constraint_id", ""),
                        disposition=mapping.get("disposition", ""),
                        active=bool(mapping.get("active", False)),
                        reason_codes=tuple(mapping.get("reason_codes", ())),
                        matched_dimensions=tuple(mapping.get("matched_dimensions", ())),
                        rejected_dimensions=tuple(
                            mapping.get("rejected_dimensions", ())
                        ),
                        defeated_by=tuple(mapping.get("defeated_by", ())),
                        conflicts_with=tuple(mapping.get("conflicts_with", ())),
                        retrieval_rank=mapping.get("retrieval_rank"),
                        hierarchy_rank=int(mapping.get("hierarchy_rank", 0)),
                        precedence=int(mapping.get("precedence", 0)),
                        modality=mapping.get(
                            "modality", LegalModality.UNSPECIFIED.value
                        ),
                        record=(
                            LegalConstraintRecord.from_dict(record)
                            if isinstance(record, Mapping)
                            else None
                        ),
                    )
                )
        contradictions_raw = value.get("contradictions", ())
        contradictions: list[LegalContradiction] = []
        for item in _sequence(contradictions_raw, "contradictions"):
            if isinstance(item, LegalContradiction):
                contradictions.append(item)
            else:
                mapping = _mapping(item, "contradiction")
                contradictions.append(
                    LegalContradiction(
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
                    ("hierarchy_rank", "precedence", "constraint_id"),
                )
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
            temporal_proof_safe=value.get("temporal_proof_safe", None),
            notes=value.get("notes", ""),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", LEGAL_APPLICABILITY_EVIDENCE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalConstraintSelectionResult:
    """Complete selection result: assessments, evidence, and selected records."""

    disposition: LegalSelectionDisposition
    query: LegalConstraintQuery
    evidence: LegalApplicabilityEvidence
    assessments: tuple[LegalConstraintAssessment, ...]
    selected: tuple[LegalConstraintRecord, ...]
    contradictions: tuple[LegalContradiction, ...]
    schema_version: str = LEGAL_CONSTRAINT_SELECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum_value(self.disposition, LegalSelectionDisposition, "disposition"),
        )
        if not isinstance(self.query, LegalConstraintQuery):
            raise LegalConstraintQueryError("query must be LegalConstraintQuery")
        if not isinstance(self.evidence, LegalApplicabilityEvidence):
            raise LegalConstraintQueryError(
                "evidence must be LegalApplicabilityEvidence"
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
        if self.schema_version != LEGAL_CONSTRAINT_SELECTION_SCHEMA_VERSION:
            raise LegalConstraintQueryError(
                f"unsupported selection schema: {self.schema_version!r}"
            )

    @property
    def applicable(self) -> tuple[LegalConstraintRecord, ...]:
        return self.selected

    @property
    def abstains(self) -> bool:
        return self.evidence.abstains

    @property
    def allows_action(self) -> bool:
        return self.evidence.allows_action

    @property
    def grants_security_authorization(self) -> bool:
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
            "grants_security_authorization": False,
            "query": self.query.to_dict(),
            "schema_version": self.schema_version,
            "selected": [item.to_dict() for item in self.selected],
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=LEGAL_CONSTRAINT_SELECTION_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest


# ---------------------------------------------------------------------------
# Selection engine
# ---------------------------------------------------------------------------


def _to_shared_status(status: LegalSelectionDisposition) -> ApplicabilityStatus:
    return {
        LegalSelectionDisposition.APPLICABLE: ApplicabilityStatus.APPLICABLE,
        LegalSelectionDisposition.NOT_APPLICABLE: ApplicabilityStatus.NOT_APPLICABLE,
        LegalSelectionDisposition.CONFLICT: ApplicabilityStatus.CONFLICT,
        LegalSelectionDisposition.INDETERMINATE: ApplicabilityStatus.INDETERMINATE,
        LegalSelectionDisposition.COVERAGE_GAP: ApplicabilityStatus.COVERAGE_GAP,
        LegalSelectionDisposition.REVIEW_REQUIRED: ApplicabilityStatus.INDETERMINATE,
        LegalSelectionDisposition.ABSTAIN: ApplicabilityStatus.INDETERMINATE,
        LegalSelectionDisposition.UNSUPPORTED: ApplicabilityStatus.UNSUPPORTED,
    }[status]


def _build_query_selectors(query: LegalConstraintQuery) -> tuple[ApplicabilitySelector, ...]:
    specs: list[tuple[str, str, str, bool]] = [
        ("sel:jurisdiction", "jurisdiction", query.jurisdiction, True),
        ("sel:as_of", "temporal", query.as_of, True),
    ]
    optional = (
        ("sel:territory", "territory", query.territory),
        ("sel:subject_matter", "subject_matter", query.subject_matter),
        ("sel:authority", "authority", query.authority_id),
        ("sel:actor", "actor", query.actor),
        ("sel:subject", "subject", query.subject),
        ("sel:resource", "resource", query.resource),
        ("sel:purpose", "purpose", query.purpose),
    )
    for selector_id, dimension, value in optional:
        if value:
            specs.append((selector_id, dimension, value, True))
    for key, value in sorted(query.thresholds.items()):
        specs.append(
            (
                f"sel:threshold:{key}",
                "threshold",
                f"{key}={value}",
                True,
            )
        )
    return tuple(
        ApplicabilitySelector(
            selector_id=selector_id,
            dimension=dimension,
            value=str(value),
            required=required,
            source_ref_ids=("source:legal-constraint-query",),
        )
        for selector_id, dimension, value, required in specs
    )


def _threshold_match(
    record_thresholds: Mapping[str, Any],
    query_thresholds: Mapping[str, Any],
) -> tuple[bool | None, str]:
    """Match declared thresholds. None means no threshold constraints."""

    if not record_thresholds:
        return None, ""
    if not query_thresholds:
        return None, "missing_query_threshold"
    for key, expected in sorted(record_thresholds.items()):
        if key not in query_thresholds:
            return None, f"missing_threshold:{key}"
        actual = query_thresholds[key]
        # Numeric comparison when both sides are numbers.
        if isinstance(expected, Mapping):
            op = str(expected.get("op", "eq")).lower()
            bound = expected.get("value", expected.get("bound"))
            if bound is None:
                return False, f"malformed_threshold:{key}"
            try:
                actual_num = float(actual)
                bound_num = float(bound)
            except (TypeError, ValueError):
                return False, f"threshold_type_mismatch:{key}"
            ok = {
                "eq": actual_num == bound_num,
                "==": actual_num == bound_num,
                "gte": actual_num >= bound_num,
                ">=": actual_num >= bound_num,
                "lte": actual_num <= bound_num,
                "<=": actual_num <= bound_num,
                "gt": actual_num > bound_num,
                ">": actual_num > bound_num,
                "lt": actual_num < bound_num,
                "<": actual_num < bound_num,
            }.get(op)
            if ok is None:
                return False, f"unsupported_threshold_op:{key}"
            if not ok:
                return False, f"threshold_unsatisfied:{key}"
        else:
            if actual != expected:
                return False, f"threshold_mismatch:{key}"
    return True, "thresholds_match"


def _hard_filter_record(
    query: LegalConstraintQuery,
    record: LegalConstraintRecord,
    *,
    known_definition_ids: frozenset[str],
    known_cross_reference_ids: frozenset[str],
    candidate_ids: frozenset[str],
    temporal_allowed_ids: frozenset[str] | None,
) -> LegalConstraintAssessment:
    reasons: list[str] = []
    matched: list[str] = []
    rejected: list[str] = []
    disposition = LegalConstraintDisposition.APPLICABLE
    active = True

    # Provenance / grounding / taint — fail closed before scope matching.
    if not record.source_ref_ids:
        disposition = LegalConstraintDisposition.REVIEW_REQUIRED
        active = False
        reasons.append("missing_source_refs")
        rejected.append("provenance")
    else:
        matched.append("provenance")

    if query.require_provenance and not record.provenance_ids:
        disposition = LegalConstraintDisposition.REVIEW_REQUIRED
        active = False
        reasons.append("missing_provenance")
        if "provenance" not in rejected:
            rejected.append("provenance")

    if record.premise_taint is LegalPremiseTaintStatus.TAINTED:
        disposition = LegalConstraintDisposition.TAINTED
        active = False
        reasons.append("premise_tainted")
        rejected.append("premise_taint")
    elif record.premise_taint is LegalPremiseTaintStatus.UNKNOWN:
        disposition = LegalConstraintDisposition.REVIEW_REQUIRED
        active = False
        reasons.append("premise_taint_unknown")
        rejected.append("premise_taint")
    elif record.premise_taint is LegalPremiseTaintStatus.UNREVIEWED:
        disposition = LegalConstraintDisposition.REVIEW_REQUIRED
        active = False
        reasons.append("premise_unreviewed")
        rejected.append("premise_taint")
    else:
        matched.append("premise_taint")

    if query.require_trusted_source and not record.trusted_source:
        disposition = LegalConstraintDisposition.REVIEW_REQUIRED
        active = False
        reasons.append("untrusted_source")
        rejected.append("provenance")

    if query.require_reviewed and not record.reviewed:
        disposition = LegalConstraintDisposition.REVIEW_REQUIRED
        active = False
        reasons.append("not_reviewed")
        rejected.append("provenance")

    if query.corpus_id and record.corpus_id and record.corpus_id != query.corpus_id:
        disposition = LegalConstraintDisposition.NOT_APPLICABLE
        active = False
        reasons.append("corpus_mismatch")
        rejected.append("jurisdiction")

    # Explicit lifecycle endpoints on the record itself.
    as_of = _parse_date(query.as_of)
    assert as_of is not None

    repeal_on = _parse_date(record.repeal_date)
    if record.repealed_by or (repeal_on is not None and as_of >= repeal_on):
        disposition = LegalConstraintDisposition.REPEALED
        active = False
        reasons.append("repealed")
        rejected.append("temporal")

    superseded_on = _parse_date(record.superseded_date)
    if disposition is LegalConstraintDisposition.APPLICABLE and (
        record.superseded_by
        or (superseded_on is not None and as_of >= superseded_on)
    ):
        disposition = LegalConstraintDisposition.SUPERSEDED
        active = False
        reasons.append("marked_superseded")
        rejected.append("temporal")

    effective_from = _parse_date(record.effective_from)
    if (
        disposition is LegalConstraintDisposition.APPLICABLE
        and effective_from is not None
        and as_of < effective_from
    ):
        disposition = LegalConstraintDisposition.NOT_YET_EFFECTIVE
        active = False
        reasons.append("not_yet_effective")
        rejected.append("temporal")

    end_candidates = [
        d
        for d in (
            _parse_date(record.effective_until),
            repeal_on,
            superseded_on,
        )
        if d is not None
    ]
    if disposition is LegalConstraintDisposition.APPLICABLE and end_candidates:
        end = min(end_candidates)
        if as_of >= end:
            disposition = LegalConstraintDisposition.EXPIRED
            active = False
            reasons.append("effective_window_expired")
            rejected.append("temporal")

    if (
        disposition is LegalConstraintDisposition.APPLICABLE
        and not record.effective_from
        and not record.enacted_date
    ):
        # Closed world: unknown effective date is indeterminate, not allow.
        if query.world_policy_kind is WorldPolicyKind.CLOSED:
            disposition = LegalConstraintDisposition.INDETERMINATE
            active = False
            reasons.append("missing_effective_date")
            rejected.append("temporal")
    elif disposition is LegalConstraintDisposition.APPLICABLE:
        matched.append("temporal")

    # Optional external temporal-authority graph binding.
    if (
        disposition is LegalConstraintDisposition.APPLICABLE
        and temporal_allowed_ids is not None
        and record.law_version_id
    ):
        if record.law_version_id not in temporal_allowed_ids:
            disposition = LegalConstraintDisposition.NOT_APPLICABLE
            active = False
            reasons.append("temporal_authority_excluded")
            rejected.append("temporal")

    # Scope dimensions.
    scope_pairs = (
        ("jurisdiction", record.jurisdictions, query.jurisdiction),
        ("territory", record.territories, query.territory),
        ("subject_matter", record.subject_matters, query.subject_matter),
        ("actor", record.actors, query.actor),
        ("subject", record.subjects, query.subject),
        ("resource", record.resources, query.resource),
        ("purpose", record.purposes, query.purpose),
    )
    for dimension, allowed, query_value in scope_pairs:
        if disposition not in {
            LegalConstraintDisposition.APPLICABLE,
            LegalConstraintDisposition.INDETERMINATE,
        }:
            break
        # Jurisdiction is always required on the query; empty record jurisdiction
        # under closed world is indeterminate.
        result = _scope_contains(allowed, query_value, universal=False)
        if result is True:
            matched.append(dimension)
        elif result is False:
            disposition = LegalConstraintDisposition.NOT_APPLICABLE
            active = False
            reasons.append(f"{dimension}_mismatch")
            rejected.append(dimension)
        else:
            # Open/missing selector on the record.
            if dimension == "jurisdiction":
                disposition = LegalConstraintDisposition.INDETERMINATE
                active = False
                reasons.append("missing_jurisdiction_selector")
                rejected.append(dimension)
            elif query_value and query.world_policy_kind is WorldPolicyKind.CLOSED:
                # Query binds the dimension but the record does not — coverage gap
                # for mandatory applicability, else indeterminate.
                if record.mandatory:
                    disposition = LegalConstraintDisposition.INDETERMINATE
                    active = False
                    reasons.append(f"missing_{dimension}_selector")
                    rejected.append(dimension)
            # else: optional dimension with empty query value — ignore.

    if (
        disposition is LegalConstraintDisposition.APPLICABLE
        and query.authority_id
        and record.authority_id
        and record.authority_id != query.authority_id
    ):
        # Different authority is not auto-reject; hierarchy resolution handles
        # competition.  Still record the mismatch for evidence.
        reasons.append("authority_differs_from_query")
    elif (
        disposition is LegalConstraintDisposition.APPLICABLE
        and record.authority_id
    ):
        matched.append("authority")

    # Thresholds.
    if disposition is LegalConstraintDisposition.APPLICABLE:
        thr_ok, thr_reason = _threshold_match(record.thresholds, query.thresholds)
        if thr_ok is True:
            matched.append("threshold")
            reasons.append(thr_reason or "thresholds_match")
        elif thr_ok is False:
            disposition = LegalConstraintDisposition.NOT_APPLICABLE
            active = False
            reasons.append(thr_reason or "threshold_mismatch")
            rejected.append("threshold")
        elif thr_reason.startswith("missing_"):
            disposition = LegalConstraintDisposition.INDETERMINATE
            active = False
            reasons.append(thr_reason)
            rejected.append("threshold")

    # Definitions / cross-references: unresolved mandatory refs fail closed.
    if disposition is LegalConstraintDisposition.APPLICABLE:
        missing_defs = sorted(set(record.definition_refs) - known_definition_ids - candidate_ids)
        if missing_defs:
            disposition = LegalConstraintDisposition.INDETERMINATE
            active = False
            reasons.append("unresolved_definition_refs")
            rejected.append("definition_refs")
        else:
            if record.definition_refs:
                matched.append("definition_refs")
        missing_xrefs = sorted(
            set(record.cross_references) - known_cross_reference_ids - candidate_ids
        )
        if missing_xrefs and disposition is LegalConstraintDisposition.APPLICABLE:
            disposition = LegalConstraintDisposition.INDETERMINATE
            active = False
            reasons.append("unresolved_cross_references")
            rejected.append("cross_references")
        elif record.cross_references and disposition is LegalConstraintDisposition.APPLICABLE:
            matched.append("cross_references")

    if not reasons and disposition is LegalConstraintDisposition.APPLICABLE:
        reasons.append("hard_filters_passed")

    return LegalConstraintAssessment(
        constraint_id=record.constraint_id,
        disposition=disposition,
        active=active and disposition is LegalConstraintDisposition.APPLICABLE,
        reason_codes=tuple(reasons),
        matched_dimensions=tuple(matched),
        rejected_dimensions=tuple(rejected),
        retrieval_rank=record.retrieval_rank,
        hierarchy_rank=record.hierarchy_rank,
        precedence=record.precedence,
        modality=record.modality,
        record=record,
    )


def _add_assessment_reason(
    assessment: LegalConstraintAssessment, *reasons: str, **updates: Any
) -> LegalConstraintAssessment:
    merged = tuple(sorted(set((*assessment.reason_codes, *reasons))))
    return replace(assessment, reason_codes=merged, **updates)


def _opposed(left: LegalModality, right: LegalModality) -> bool:
    return frozenset({left.value, right.value}) in _OPPOSED_MODALITY_PAIRS


def _authority_sort_key(assessment: LegalConstraintAssessment) -> tuple[int, int, str]:
    """Higher hierarchy_rank and precedence win; ID is a stable tie-break only.

    Retrieval rank is intentionally absent.
    """

    return (-assessment.hierarchy_rank, -assessment.precedence, assessment.constraint_id)


def _resolve_relationships(
    assessments: dict[str, LegalConstraintAssessment],
    records: Mapping[str, LegalConstraintRecord],
) -> tuple[dict[str, LegalConstraintAssessment], list[LegalContradiction]]:
    contradictions: list[LegalContradiction] = []

    # Unresolved exception / conflict references for still-applicable norms.
    for constraint_id, assessment in tuple(assessments.items()):
        if not assessment.active:
            continue
        record = records[constraint_id]
        for exception_id in record.exception_ids:
            other = assessments.get(exception_id)
            if other is None or other.disposition in {
                LegalConstraintDisposition.INDETERMINATE,
                LegalConstraintDisposition.REVIEW_REQUIRED,
                LegalConstraintDisposition.CONFLICTING,
                LegalConstraintDisposition.TAINTED,
                LegalConstraintDisposition.ABSTAIN,
            }:
                assessments[constraint_id] = _add_assessment_reason(
                    replace(
                        assessment,
                        disposition=LegalConstraintDisposition.INDETERMINATE,
                        active=False,
                    ),
                    "unresolved_exception",
                )
                assessment = assessments[constraint_id]
                break
        missing_conflicts = set(record.conflicts_with) - set(assessments)
        if missing_conflicts and assessment.active:
            assessments[constraint_id] = _add_assessment_reason(
                replace(
                    assessment,
                    disposition=LegalConstraintDisposition.INDETERMINATE,
                    active=False,
                ),
                "unresolved_conflict_reference",
            )

    # Applicable exceptions defeat targets without erasing either record.
    for exception_id, assessment in tuple(assessments.items()):
        if not (
            assessment.active
            and assessment.modality is LegalModality.EXCEPTION
        ):
            continue
        record = records[exception_id]
        if not record.exception_to:
            assessments[exception_id] = _add_assessment_reason(
                replace(
                    assessment,
                    disposition=LegalConstraintDisposition.INDETERMINATE,
                    active=False,
                ),
                "exception_missing_target",
            )
            continue
        for target_id in record.exception_to:
            target = assessments.get(target_id)
            if target is None:
                assessments[exception_id] = _add_assessment_reason(
                    replace(
                        assessments[exception_id],
                        disposition=LegalConstraintDisposition.INDETERMINATE,
                        active=False,
                    ),
                    "exception_target_missing",
                )
            elif target.active:
                assessments[target_id] = _add_assessment_reason(
                    replace(
                        target,
                        disposition=LegalConstraintDisposition.DEFEATED,
                        active=False,
                        defeated_by=tuple(
                            sorted(set((*target.defeated_by, exception_id)))
                        ),
                    ),
                    "applicable_exception",
                )
                assessments[exception_id] = _add_assessment_reason(
                    assessments[exception_id],
                    "exception_applied",
                )
                matched = set(assessments[exception_id].matched_dimensions) | {
                    "exceptions"
                }
                assessments[exception_id] = replace(
                    assessments[exception_id],
                    matched_dimensions=tuple(sorted(matched)),
                )

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
                        disposition=LegalConstraintDisposition.INDETERMINATE,
                        active=False,
                    ),
                    "superseded_provision_missing",
                )
            elif target.active or target.disposition is LegalConstraintDisposition.APPLICABLE:
                assessments[target_id] = _add_assessment_reason(
                    replace(
                        target,
                        disposition=LegalConstraintDisposition.SUPERSEDED,
                        active=False,
                        defeated_by=tuple(
                            sorted(set((*target.defeated_by, winner_id)))
                        ),
                    ),
                    "express_supersession",
                )
                contradictions.append(
                    LegalContradiction(
                        contradiction_id=f"supersession:{winner_id}:{target_id}",
                        constraint_ids=(winner_id, target_id),
                        kind="supersession",
                        reason_codes=("express_supersession",),
                        resolved=True,
                        winning_constraint_id=winner_id,
                    )
                )

    def active_items() -> list[LegalConstraintAssessment]:
        return [
            assessments[key]
            for key in sorted(assessments)
            if assessments[key].active
        ]

    # Competing authorities / opposed modalities on the same applicability key.
    by_key: dict[str, list[LegalConstraintAssessment]] = {}
    for item in active_items():
        record = records[item.constraint_id]
        by_key.setdefault(record.applicability_key, []).append(item)

    for key, group in sorted(by_key.items()):
        if len(group) < 2:
            continue
        # Pairwise opposition or explicit conflict edges.
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                left_rec = records[left.constraint_id]
                right_rec = records[right.constraint_id]
                explicit = (
                    right.constraint_id in left_rec.conflicts_with
                    or left.constraint_id in right_rec.conflicts_with
                )
                opposed = _opposed(left.modality, right.modality)
                if not (explicit or opposed):
                    continue
                if left.hierarchy_rank != right.hierarchy_rank:
                    winner, loser = (
                        (left, right)
                        if left.hierarchy_rank > right.hierarchy_rank
                        else (right, left)
                    )
                    assessments[loser.constraint_id] = _add_assessment_reason(
                        replace(
                            loser,
                            disposition=LegalConstraintDisposition.SUPERSEDED,
                            active=False,
                            defeated_by=tuple(
                                sorted(
                                    set((*loser.defeated_by, winner.constraint_id))
                                )
                            ),
                        ),
                        "higher_authority_preempts",
                    )
                    contradictions.append(
                        LegalContradiction(
                            contradiction_id=(
                                f"authority:{winner.constraint_id}:{loser.constraint_id}"
                            ),
                            constraint_ids=(
                                winner.constraint_id,
                                loser.constraint_id,
                            ),
                            kind="authority_preemption",
                            reason_codes=("higher_authority_preempts",),
                            resolved=True,
                            winning_constraint_id=winner.constraint_id,
                        )
                    )
                elif left.precedence != right.precedence:
                    winner, loser = (
                        (left, right)
                        if left.precedence > right.precedence
                        else (right, left)
                    )
                    assessments[loser.constraint_id] = _add_assessment_reason(
                        replace(
                            loser,
                            disposition=LegalConstraintDisposition.SUPERSEDED,
                            active=False,
                            defeated_by=tuple(
                                sorted(
                                    set((*loser.defeated_by, winner.constraint_id))
                                )
                            ),
                        ),
                        "higher_precedence_provision",
                    )
                    contradictions.append(
                        LegalContradiction(
                            contradiction_id=(
                                f"precedence:{winner.constraint_id}:{loser.constraint_id}"
                            ),
                            constraint_ids=(
                                winner.constraint_id,
                                loser.constraint_id,
                            ),
                            kind="precedence",
                            reason_codes=("higher_precedence_provision",),
                            resolved=True,
                            winning_constraint_id=winner.constraint_id,
                        )
                    )
                else:
                    # Equal hierarchy and precedence — preserve conflict.
                    for item in (left, right):
                        peer = (
                            right.constraint_id
                            if item.constraint_id == left.constraint_id
                            else left.constraint_id
                        )
                        assessments[item.constraint_id] = _add_assessment_reason(
                            replace(
                                assessments[item.constraint_id],
                                disposition=LegalConstraintDisposition.CONFLICTING,
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
                            "unresolved_equal_authority_conflict",
                        )
                    contradictions.append(
                        LegalContradiction(
                            contradiction_id=(
                                f"conflict:{left.constraint_id}:{right.constraint_id}"
                            ),
                            constraint_ids=(left.constraint_id, right.constraint_id),
                            kind="unresolved_conflict",
                            reason_codes=("unresolved_equal_authority_conflict",),
                            resolved=False,
                        )
                    )

    return assessments, contradictions


def _overall_disposition(
    assessments: Sequence[LegalConstraintAssessment],
    contradictions: Sequence[LegalContradiction],
    coverage_gaps: Sequence[CoverageGap],
    *,
    considered_count: int,
) -> LegalSelectionDisposition:
    if considered_count == 0 or coverage_gaps:
        return LegalSelectionDisposition.COVERAGE_GAP

    active = [item for item in assessments if item.active]
    dispositions = {item.disposition for item in assessments}

    if any(not item.resolved for item in contradictions) or (
        LegalConstraintDisposition.CONFLICTING in dispositions
    ):
        return LegalSelectionDisposition.CONFLICT

    if any(
        item.disposition
        in {
            LegalConstraintDisposition.REVIEW_REQUIRED,
            LegalConstraintDisposition.TAINTED,
            LegalConstraintDisposition.ABSTAIN,
        }
        for item in assessments
        if item.disposition
        not in {
            LegalConstraintDisposition.NOT_APPLICABLE,
            LegalConstraintDisposition.EXPIRED,
            LegalConstraintDisposition.NOT_YET_EFFECTIVE,
            LegalConstraintDisposition.REPEALED,
            LegalConstraintDisposition.SUPERSEDED,
            LegalConstraintDisposition.DEFEATED,
        }
    ):
        # Only escalate when no clean applicable set remains, or when a mandatory
        # candidate requires review while competing.
        review_like = [
            item
            for item in assessments
            if item.disposition
            in {
                LegalConstraintDisposition.REVIEW_REQUIRED,
                LegalConstraintDisposition.TAINTED,
                LegalConstraintDisposition.ABSTAIN,
            }
        ]
        if review_like and not active:
            return LegalSelectionDisposition.REVIEW_REQUIRED

    if any(
        item.disposition is LegalConstraintDisposition.INDETERMINATE
        for item in assessments
    ) and not active:
        return LegalSelectionDisposition.INDETERMINATE

    if active:
        return LegalSelectionDisposition.APPLICABLE

    if all(
        item.disposition
        in {
            LegalConstraintDisposition.NOT_APPLICABLE,
            LegalConstraintDisposition.EXPIRED,
            LegalConstraintDisposition.NOT_YET_EFFECTIVE,
            LegalConstraintDisposition.REPEALED,
            LegalConstraintDisposition.SUPERSEDED,
            LegalConstraintDisposition.DEFEATED,
        }
        for item in assessments
    ):
        return LegalSelectionDisposition.NOT_APPLICABLE

    return LegalSelectionDisposition.ABSTAIN


def select_applicable_legal_constraints(
    query: LegalConstraintQuery | Mapping[str, Any],
    candidates: Sequence[LegalConstraintRecord | Mapping[str, Any]],
    *,
    known_definition_ids: Sequence[str] | None = None,
    known_cross_reference_ids: Sequence[str] | None = None,
    temporal_applicability: Mapping[str, Any] | None = None,
) -> LegalConstraintSelectionResult:
    """Hard-filter and select Legal constraints for ``query``.

    Retrieval rank on candidates is ignored for authority and applicability.
    Unresolved conflicts, coverage gaps, taint, and open applicability fail
    closed to review/abstain dispositions.
    """

    if not isinstance(query, LegalConstraintQuery):
        query = LegalConstraintQuery.from_dict(_mapping(query, "query"))

    records: list[LegalConstraintRecord] = []
    for item in _sequence(candidates, "candidates"):
        if isinstance(item, LegalConstraintRecord):
            records.append(item)
        else:
            records.append(LegalConstraintRecord.from_dict(_mapping(item, "candidate")))

    # Deterministic consideration order by constraint_id (not retrieval rank).
    records = sorted(records, key=lambda item: item.constraint_id)
    if len({item.constraint_id for item in records}) != len(records):
        raise LegalConstraintQueryError("candidate constraint_ids must be unique")

    record_by_id = {item.constraint_id: item for item in records}
    candidate_ids = frozenset(record_by_id)
    known_defs = frozenset(
        _unique_sorted_ids(known_definition_ids or (), "known_definition_ids")
    )
    known_xrefs = frozenset(
        _unique_sorted_ids(
            known_cross_reference_ids or (), "known_cross_reference_ids"
        )
    )

    temporal_allowed: frozenset[str] | None = None
    temporal_proof_safe: bool | None = None
    if temporal_applicability is not None:
        temporal_proof_safe = bool(temporal_applicability.get("proof_safe", False))
        allowed = temporal_applicability.get("applicable_law_version_ids", ())
        temporal_allowed = frozenset(
            _unique_sorted_ids(allowed, "applicable_law_version_ids")
        )

    selectors = _build_query_selectors(query)
    assessments_map: dict[str, LegalConstraintAssessment] = {}
    for record in records:
        assessments_map[record.constraint_id] = _hard_filter_record(
            query,
            record,
            known_definition_ids=known_defs,
            known_cross_reference_ids=known_xrefs,
            candidate_ids=candidate_ids,
            temporal_allowed_ids=temporal_allowed,
        )

    assessments_map, contradictions = _resolve_relationships(
        assessments_map, record_by_id
    )

    # Bounded selection by authority hierarchy / precedence only.
    active = [
        item for item in assessments_map.values() if item.active
    ]
    ordered = sorted(active, key=_authority_sort_key)
    budget = query.selection_budget
    selected_assessments = ordered[:budget]
    # If budget truncates, remaining actives become explicit coverage/selection notes
    # but stay in assessments; they are not silently dropped without evidence.
    truncated = ordered[budget:]
    for item in truncated:
        assessments_map[item.constraint_id] = _add_assessment_reason(
            replace(
                item,
                active=False,
                disposition=LegalConstraintDisposition.ABSTAIN,
            ),
            "selection_budget_exceeded",
        )

    selected_ids = tuple(
        item.constraint_id for item in selected_assessments if item.active
    )
    # Re-read after truncation updates.
    selected_ids = tuple(
        item.constraint_id
        for item in sorted(assessments_map.values(), key=_authority_sort_key)
        if item.active
    )
    selected_records = tuple(record_by_id[item_id] for item_id in selected_ids)

    coverage_gaps: list[CoverageGap] = []
    if not records:
        # Empty candidate set is a corpus coverage gap, not a silent allow.
        coverage_gaps.append(
            CoverageGap(
                gap_id="gap:empty-corpus",
                kind=CoverageGapKind.MISSING_AUTHORITY,
                description="No Legal constraint candidates were provided for selection",
                subject_ids=(),
            )
        )

    # Temporal graph said no law versions apply — explicit temporal coverage gap.
    if temporal_allowed is not None and not temporal_allowed and records:
        coverage_gaps.append(
            CoverageGap(
                gap_id="gap:temporal-authority",
                kind=CoverageGapKind.MISSING_TEMPORAL,
                description="Temporal authority graph yielded no applicable law versions",
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

    # If temporal proof is explicitly unsafe while we would otherwise apply, abstain.
    if (
        temporal_proof_safe is False
        and disposition is LegalSelectionDisposition.APPLICABLE
    ):
        disposition = LegalSelectionDisposition.REVIEW_REQUIRED

    # Selector match evidence from assessments + query.
    matched_selector_ids: list[str] = []
    rejected_selector_ids: list[str] = []
    if disposition is LegalSelectionDisposition.APPLICABLE:
        matched_selector_ids = [item.selector_id for item in selectors]
    else:
        # Mark required selectors rejected when overall disposition fails.
        dim_to_selector = {item.dimension: item.selector_id for item in selectors}
        rejected_dims: set[str] = set()
        matched_dims: set[str] = set()
        for assessment in assessments:
            rejected_dims.update(assessment.rejected_dimensions)
            if assessment.active:
                matched_dims.update(assessment.matched_dimensions)
        for dim, selector_id in dim_to_selector.items():
            if dim in rejected_dims:
                rejected_selector_ids.append(selector_id)
            elif dim in matched_dims or disposition is LegalSelectionDisposition.NOT_APPLICABLE:
                if dim in matched_dims:
                    matched_selector_ids.append(selector_id)
                else:
                    rejected_selector_ids.append(selector_id)
            else:
                rejected_selector_ids.append(selector_id)

    # Build shared ApplicabilityEvidence carefully under its consistency rules.
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
            notes="legal-constraint-query shared applicability projection",
        )
    except ConstraintValidationError:
        # Fall back to indeterminate shared evidence rather than raising — Legal
        # evidence remains authoritative for this leaf.
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
            notes="legal-constraint-query shared applicability fallback",
        )

    # Premise receipt: hard-filtered selection only; ranks are authority order.
    premises: list[SelectedPremise] = []
    for rank, constraint_id in enumerate(selected_ids):
        record = record_by_id[constraint_id]
        premises.append(
            SelectedPremise(
                premise_id=f"premise:{constraint_id}",
                statement=record.statement or constraint_id,
                source_ref_ids=record.source_ref_ids,
                logic_family="deontic",
                rank=rank,
                score=None,
                selection_method=PremiseSelectionMethod.HARD_FILTER,
                statement_id=constraint_id,
                metadata={
                    "hierarchy_rank": record.hierarchy_rank,
                    "precedence": record.precedence,
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
        config_id="legal-constraint-query",
        query_digest=query.digest,
        notes="Bounded Legal selection by hierarchy_rank, precedence; retrieval rank ignored",
    )

    hard_filtered_count = sum(1 for item in assessments if not item.active)
    evidence = LegalApplicabilityEvidence(
        evidence_id=f"legal-app:{query.query_id}",
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
        shared_applicability=shared_evidence,
        selected_premises=selected_premises,
        temporal_proof_safe=temporal_proof_safe,
        notes=(
            "Legal hard filters precede authority/precedence selection; "
            "retrieval rank never selects authority"
        ),
    )

    return LegalConstraintSelectionResult(
        disposition=disposition,
        query=query,
        evidence=evidence,
        assessments=assessments,
        selected=selected_records,
        contradictions=contradiction_tuple,
    )


# Public aliases matching interface names in backlog docs.
LegalConstraintQueryEngine = LegalConstraintQuery


__all__ = [
    "DEFAULT_SELECTION_BUDGET",
    "LEGAL_APPLICABILITY_EVIDENCE_INTERFACE",
    "LEGAL_APPLICABILITY_EVIDENCE_SCHEMA_VERSION",
    "LEGAL_CONSTRAINT_QUERY_INTERFACE",
    "LEGAL_CONSTRAINT_QUERY_SCHEMA_VERSION",
    "LEGAL_CONSTRAINT_RECORD_SCHEMA_VERSION",
    "LEGAL_CONSTRAINT_SELECTION_SCHEMA_VERSION",
    "LEGAL_HARD_FILTER_DIMENSIONS",
    "LegalApplicabilityEvidence",
    "LegalConstraintAssessment",
    "LegalConstraintDisposition",
    "LegalConstraintQuery",
    "LegalConstraintQueryEngine",
    "LegalConstraintQueryError",
    "LegalConstraintRecord",
    "LegalConstraintSelectionResult",
    "LegalContradiction",
    "LegalModality",
    "LegalPremiseTaintStatus",
    "LegalSelectionDisposition",
    "select_applicable_legal_constraints",
]
