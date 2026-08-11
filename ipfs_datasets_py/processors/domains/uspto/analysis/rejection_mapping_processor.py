"""Map rejections, claims, statutory bases, and cited references (PATLAW-043).

Builds an **examiner-statement map** from office-action rejection candidates
and optional claim-set snapshots. It records what the examiner stated — which
claims, under which statutory bases, with which cited references, and later
disposition history — without inferring patentability.

Design invariants
-----------------
* Claim ranges and references are **never guessed**. Open-ended or unresolved
  claim surfaces retain explicit ambiguity; unstated references stay empty.
* Rescinded / reissued actions and amended claim-set versions retain history.
* A missing claim set yields ``unknown`` / ``review`` claim resolution.
* Every mapping entry points at source span / candidate identifiers when known.
* Output always declares ``output_kind = examiner_statement_map`` and includes
  a disclaimer that this is **not** a patentability determination.

Body text is never written to logs or exception messages.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
    most_restrictive_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    ActionLifecycleStatus,
    AnalysisCandidate,
    CandidateKind,
    ClaimRangeAmbiguity,
    OfficeActionResult,
    parse_claim_range_surface,
)

REJECTION_MAPPING_SCHEMA_VERSION: Final = "uspto.rejection-mapping.v1"
REJECTION_MAPPING_INTERFACE: Final = "RejectionMappingProcessor@1"
REJECTION_MAPPING_RULESET_VERSION: Final = "rejection-mapping-rules@1"

OUTPUT_KIND_EXAMINER_STATEMENT_MAP: Final = "examiner_statement_map"
NOT_PATENTABILITY_DISCLAIMER: Final = (
    "This output is an examiner-statement map of stated rejections, affected "
    "claims, statutory bases, cited references, and disposition history. "
    "It is not a patentability determination and does not assert validity, "
    "invalidity, or patentability of any claim."
)

DEFAULT_MAX_MAPPINGS: Final = 4096
DEFAULT_MAX_CLAIM_SETS: Final = 64
DEFAULT_MAX_HISTORY: Final = 256

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

# Statutory surface anchors (stated bases only; never invent a section).
_STATUTE_SURFACE_RE = re.compile(
    r"(?i)\b35\s*U\.?\s*S\.?\s*C\.?\s*§?\s*(?P<section>\d+)"
    r"(?:\s*(?P<sub>\([a-z0-9]+\)))?"
)
_OBVIOUS_RE = re.compile(r"(?i)\bobvious(?:ness|ly)?\b")
_ANTICIPAT_RE = re.compile(r"(?i)\banticipat(?:ed|ion)\b")
_INDEFINITE_RE = re.compile(r"(?i)\bindefinite\b")
_ENABLEMENT_RE = re.compile(r"(?i)\benablement\b")
_WRITTEN_DESC_RE = re.compile(r"(?i)\bwritten\s+description\b")
_LIMITATION_RE = re.compile(
    r"(?i)\b(?:limitation|element|recitation)\s+"
    r"['\"](?P<lit>[^'\"]{2,200})['\"]"
    r"|\b(?:limitation|element)\s+(?P<label>[\w\-/]{2,80})\b"
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MappingDisposition(str, Enum):
    """Top-level outcome of rejection mapping."""

    MAPPED = "mapped"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    REJECTED = "rejected"


class ClaimResolutionStatus(str, Enum):
    """How claim tokens were resolved against a claim set.

    Never invents claim numbers for open-ended or unresolved surfaces.
    """

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    OPEN_ENDED = "open_ended"
    AMBIGUOUS = "ambiguous"
    MISSING_CLAIM_SET = "missing_claim_set"
    CLAIM_NOT_IN_SET = "claim_not_in_set"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ReferenceResolutionStatus(str, Enum):
    """Whether cited references were stated on the rejection surface."""

    STATED = "stated"
    UNSTATED = "unstated"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class StatutoryBasisFamily(str, Enum):
    USC_101 = "35_usc_101"
    USC_102 = "35_usc_102"
    USC_103 = "35_usc_103"
    USC_112 = "35_usc_112"
    OTHER = "other"
    UNKNOWN = "unknown"


class MappingLifecycleStatus(str, Enum):
    """Lifecycle of a mapped rejection relative to later actions / claims."""

    ACTIVE = "active"
    RESCINDED = "rescinded"
    SUPERSEDED = "superseded"
    REISSUED = "reissued"
    WITHDRAWN = "withdrawn"
    AMENDED_CLAIM_HISTORY = "amended_claim_history"
    UNKNOWN = "unknown"


class LaterDispositionKind(str, Enum):
    """Later prosecution disposition affecting a rejection mapping."""

    NONE = "none"
    WITHDRAWN = "withdrawn"
    MAINTAINED = "maintained"
    SUPERSEDED = "superseded"
    RESCINDED = "rescinded"
    ALLOWED = "allowed"
    AMENDED = "amended"
    UNKNOWN = "unknown"


class RejectionMappingReasonCode(str, Enum):
    REJECTIONS_MAPPED = "rejections_mapped"
    STATUTORY_BASES_MAPPED = "statutory_bases_mapped"
    CLAIMS_RESOLVED = "claims_resolved"
    REFERENCES_MAPPED = "references_mapped"
    MISSING_CLAIM_SET = "missing_claim_set"
    CLAIM_RANGE_UNRESOLVED = "claim_range_unresolved"
    CLAIM_RANGE_OPEN_ENDED = "claim_range_open_ended"
    CLAIM_NOT_IN_SET = "claim_not_in_set"
    REFERENCE_UNSTATED = "reference_unstated"
    STATUTORY_BASIS_UNKNOWN = "statutory_basis_unknown"
    LIFECYCLE_HISTORY_RETAINED = "lifecycle_history_retained"
    AMENDED_CLAIM_HISTORY_RETAINED = "amended_claim_history_retained"
    ALTERNATIVES_PRESERVED = "alternatives_preserved"
    AMBIGUITY_PRESERVED = "ambiguity_preserved"
    EXAMINER_STATEMENT_MAP_ONLY = "examiner_statement_map_only"
    NOT_PATENTABILITY_DETERMINATION = "not_patentability_determination"
    EMPTY_INPUT = "empty_input"
    NO_REJECTIONS = "no_rejections"
    REVIEW_REQUIRED = "review_required"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    MAPPING_LIMIT = "mapping_limit"
    PARTIAL_MAPPING = "partial_mapping"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class RejectionMappingError(ValueError):
    """Bounded mapping failure with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "rejection_mapping_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text).encode("utf-8"))


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float or None")
    number = float(value)
    if number != number or number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be in [0.0, 1.0]")
    return number


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError(
        f"classification must be DisclosureClassification or str, "
        f"got {type(value).__name__}"
    )


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(
        _require_str(item, f"{field}[{i}]", max_len=2048) for i, item in enumerate(value)
    )


def _frozen_str_map(
    value: Any,
    field: str,
    *,
    max_items: int = 64,
    allow_empty_values: bool = False,
    max_value_len: int = 2048,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(str(key), f"{field}.key", max_len=128)
        if not isinstance(raw, str):
            raise TypeError(f"{field}[{k}] must be str")
        if not raw and not allow_empty_values:
            raise ValueError(f"{field}[{k}] must be non-empty")
        if len(raw) > max_value_len:
            raise ValueError(f"{field}[{k}] exceeds max length {max_value_len}")
        out[k] = raw
    return MappingProxyType(out)


# ---------------------------------------------------------------------------
# Statutory / claim pure helpers (no guessing)
# ---------------------------------------------------------------------------


def parse_statutory_basis_surface(
    surface: str,
    *,
    requirement_type: str | None = None,
) -> tuple[StatutoryBasisFamily, str | None, str | None, str | None]:
    """Parse a *stated* statutory basis from surface text or requirement type.

    Returns ``(family, section, subsection, surface_form)``.
    When no basis is stated, returns ``UNKNOWN`` with null section — never
    invents 101/102/103/112 from silence.
    """
    text = _normalize_ws(surface or "")
    req = (requirement_type or "").strip().lower()

    # Prefer structured requirement_type from office-action extraction.
    if req.startswith("rejection_"):
        body = req[len("rejection_") :]
        if body.startswith("101"):
            sub = _extract_paren_sub(body[3:])
            return StatutoryBasisFamily.USC_101, "101", sub, f"35 U.S.C. § 101{sub or ''}"
        if body.startswith("102"):
            sub = _extract_paren_sub(body[3:])
            return StatutoryBasisFamily.USC_102, "102", sub, f"35 U.S.C. § 102{sub or ''}"
        if body.startswith("103"):
            sub = _extract_paren_sub(body[3:])
            return StatutoryBasisFamily.USC_103, "103", sub, f"35 U.S.C. § 103{sub or ''}"
        if body.startswith("112"):
            rest = body[3:]
            if rest.startswith("_enablement"):
                return (
                    StatutoryBasisFamily.USC_112,
                    "112",
                    "enablement",
                    "35 U.S.C. § 112 enablement",
                )
            if rest.startswith("_written_description"):
                return (
                    StatutoryBasisFamily.USC_112,
                    "112",
                    "written_description",
                    "35 U.S.C. § 112 written description",
                )
            if rest.startswith("a") or rest.startswith("(a)"):
                return StatutoryBasisFamily.USC_112, "112", "(a)", "35 U.S.C. § 112(a)"
            if rest.startswith("b") or rest.startswith("(b)"):
                return StatutoryBasisFamily.USC_112, "112", "(b)", "35 U.S.C. § 112(b)"
            sub = _extract_paren_sub(rest)
            return StatutoryBasisFamily.USC_112, "112", sub, f"35 U.S.C. § 112{sub or ''}"
        if body and body != "rejection":
            # Other stated rejection type (e.g. double patenting) — OTHER, not guessed.
            return StatutoryBasisFamily.OTHER, None, None, requirement_type

    m = _STATUTE_SURFACE_RE.search(text)
    if m:
        section = m.group("section")
        sub = m.group("sub")
        surface_form = _normalize_ws(m.group(0))
        if section == "101":
            return StatutoryBasisFamily.USC_101, section, sub, surface_form
        if section == "102":
            return StatutoryBasisFamily.USC_102, section, sub, surface_form
        if section == "103":
            return StatutoryBasisFamily.USC_103, section, sub, surface_form
        if section == "112":
            # Refine subsection from surrounding language when §112 has no paren.
            if not sub:
                if _ENABLEMENT_RE.search(text):
                    return (
                        StatutoryBasisFamily.USC_112,
                        section,
                        "enablement",
                        surface_form,
                    )
                if _WRITTEN_DESC_RE.search(text):
                    return (
                        StatutoryBasisFamily.USC_112,
                        section,
                        "written_description",
                        surface_form,
                    )
                if _INDEFINITE_RE.search(text):
                    return StatutoryBasisFamily.USC_112, section, "(b)", surface_form
            return StatutoryBasisFamily.USC_112, section, sub, surface_form
        return StatutoryBasisFamily.OTHER, section, sub, surface_form

    # Keyword fallback only when language *states* the doctrine without a
    # section number — still a stated basis, not a silent invent. Map to
    # the conventional statute families used by USPTO form language.
    if _OBVIOUS_RE.search(text):
        return StatutoryBasisFamily.USC_103, "103", None, "obviousness (stated)"
    if _ANTICIPAT_RE.search(text):
        return StatutoryBasisFamily.USC_102, "102", None, "anticipation (stated)"
    if _INDEFINITE_RE.search(text):
        return StatutoryBasisFamily.USC_112, "112", "(b)", "indefiniteness (stated)"
    if _ENABLEMENT_RE.search(text):
        return (
            StatutoryBasisFamily.USC_112,
            "112",
            "enablement",
            "enablement (stated)",
        )
    if _WRITTEN_DESC_RE.search(text):
        return (
            StatutoryBasisFamily.USC_112,
            "112",
            "written_description",
            "written description (stated)",
        )

    return StatutoryBasisFamily.UNKNOWN, None, None, None


def _extract_paren_sub(body: str) -> str | None:
    if not body:
        return None
    m = re.search(r"(\([a-z0-9]+\))", body, re.I)
    if m:
        return m.group(1).lower()
    # bare trailing letter after section digits already stripped
    bare = body.strip().lower()
    if bare in {"a", "b", "c", "d", "e", "f"}:
        return f"({bare})"
    return None


def extract_limitation_surfaces(surface: str) -> tuple[str, ...]:
    """Extract *explicitly quoted or labeled* limitation surfaces only.

    Does not invent claim-limitation coverage from general rejection prose.
    """
    text = surface or ""
    found: list[str] = []
    seen: set[str] = set()
    for m in _LIMITATION_RE.finditer(text):
        lit = m.group("lit") or m.group("label") or ""
        lit = _normalize_ws(lit)
        if not lit or lit.lower() in seen:
            continue
        seen.add(lit.lower())
        found.append(lit[:256])
    return tuple(found)


def _lifecycle_from_action(
    status: ActionLifecycleStatus | str | None,
) -> MappingLifecycleStatus:
    if status is None:
        return MappingLifecycleStatus.UNKNOWN
    if isinstance(status, ActionLifecycleStatus):
        value = status.value
    else:
        value = str(status).strip().lower()
    mapping = {
        ActionLifecycleStatus.ACTIVE.value: MappingLifecycleStatus.ACTIVE,
        ActionLifecycleStatus.RESCINDED.value: MappingLifecycleStatus.RESCINDED,
        ActionLifecycleStatus.SUPERSEDED.value: MappingLifecycleStatus.SUPERSEDED,
        ActionLifecycleStatus.REISSUED.value: MappingLifecycleStatus.REISSUED,
        ActionLifecycleStatus.WITHDRAWN.value: MappingLifecycleStatus.WITHDRAWN,
        ActionLifecycleStatus.UNKNOWN.value: MappingLifecycleStatus.UNKNOWN,
    }
    return mapping.get(value, MappingLifecycleStatus.UNKNOWN)


def _claim_resolution_from_ambiguity(
    ambiguity: str | ClaimRangeAmbiguity | None,
    *,
    has_tokens: bool,
    has_claim_set: bool,
) -> ClaimResolutionStatus:
    if not has_claim_set:
        return ClaimResolutionStatus.MISSING_CLAIM_SET
    amb_val: str | None
    if isinstance(ambiguity, ClaimRangeAmbiguity):
        amb_val = ambiguity.value
    else:
        amb_val = ambiguity
    if amb_val == ClaimRangeAmbiguity.OPEN_ENDED.value:
        return ClaimResolutionStatus.OPEN_ENDED
    if amb_val in (
        ClaimRangeAmbiguity.UNRESOLVED.value,
        ClaimRangeAmbiguity.CONFLICTING.value,
    ):
        return ClaimResolutionStatus.UNRESOLVED
    if amb_val == ClaimRangeAmbiguity.MULTI_SEGMENT.value and has_tokens:
        return ClaimResolutionStatus.RESOLVED
    if has_tokens:
        return ClaimResolutionStatus.RESOLVED
    if amb_val == ClaimRangeAmbiguity.EXACT.value:
        # Exact but no tokens is contradictory → unresolved, never guess.
        return ClaimResolutionStatus.UNRESOLVED
    return ClaimResolutionStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClaimSetSnapshot:
    """A claim-set version available for mapping (current or historical).

    ``claim_numbers`` alone is sufficient; claim text digests are optional.
    Missing claim sets are represented by *not* providing any snapshot — the
    processor never invents claim numbers from silence.
    """

    schema_version: str
    version_id: str
    claim_numbers: tuple[str, ...]
    claim_text_digests: Mapping[str, str]
    claim_span_ids: Mapping[str, str]
    artifact_id: str | None
    is_current: bool
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != REJECTION_MAPPING_SCHEMA_VERSION:
            raise ValueError(
                "ClaimSetSnapshot.schema_version must be "
                f"{REJECTION_MAPPING_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "version_id", _identifier(self.version_id, "version_id")
        )
        numbers = _tuple_of_str(self.claim_numbers, "claim_numbers", max_items=512)
        # Normalize claim numbers to stripped digit strings when pure digits.
        normalized: list[str] = []
        seen: set[str] = set()
        for n in numbers:
            key = str(int(n)) if n.isdigit() else n
            if key not in seen:
                seen.add(key)
                normalized.append(key)
        object.__setattr__(self, "claim_numbers", tuple(normalized))
        object.__setattr__(
            self,
            "claim_text_digests",
            _frozen_str_map(
                self.claim_text_digests, "claim_text_digests", max_items=512
            ),
        )
        object.__setattr__(
            self,
            "claim_span_ids",
            _frozen_str_map(self.claim_span_ids, "claim_span_ids", max_items=512),
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.is_current, bool):
            raise TypeError("is_current must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    @property
    def number_set(self) -> frozenset[str]:
        return frozenset(self.claim_numbers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "claim_numbers": list(self.claim_numbers),
            "claim_span_ids": dict(self.claim_span_ids),
            "claim_text_digests": dict(self.claim_text_digests),
            "is_current": self.is_current,
            "labels": dict(self.labels),
            "schema_version": self.schema_version,
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimSetSnapshot":
        if not isinstance(value, Mapping):
            raise TypeError("ClaimSetSnapshot must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", REJECTION_MAPPING_SCHEMA_VERSION
            ),
            version_id=value.get("version_id", ""),
            claim_numbers=tuple(value.get("claim_numbers") or ()),
            claim_text_digests=value.get("claim_text_digests") or {},
            claim_span_ids=value.get("claim_span_ids") or {},
            artifact_id=value.get("artifact_id"),
            is_current=bool(value.get("is_current", False)),
            labels=value.get("labels") or {},
        )

    @classmethod
    def from_numbers(
        cls,
        version_id: str,
        claim_numbers: Sequence[str],
        *,
        is_current: bool = True,
        artifact_id: str | None = None,
        claim_text_digests: Mapping[str, str] | None = None,
        claim_span_ids: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> "ClaimSetSnapshot":
        return cls(
            schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
            version_id=version_id,
            claim_numbers=tuple(claim_numbers),
            claim_text_digests=claim_text_digests or {},
            claim_span_ids=claim_span_ids or {},
            artifact_id=artifact_id,
            is_current=is_current,
            labels=labels or {},
        )


@dataclass(frozen=True, slots=True)
class LaterDispositionEvent:
    """A later prosecution event that may affect a rejection's disposition."""

    schema_version: str
    event_id: str
    kind: LaterDispositionKind
    action_id: str | None
    related_mapping_ids: tuple[str, ...]
    as_of: str | None
    notes: tuple[str, ...]
    source_span_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(LaterDispositionKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self,
            "related_mapping_ids",
            _tuple_of_str(
                self.related_mapping_ids, "related_mapping_ids", max_items=64
            ),
        )
        object.__setattr__(
            self, "as_of", _optional_str(self.as_of, "as_of", max_len=64)
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "as_of": self.as_of,
            "event_id": self.event_id,
            "kind": self.kind.value,
            "notes": list(self.notes),
            "related_mapping_ids": list(self.related_mapping_ids),
            "schema_version": self.schema_version,
            "source_span_id": self.source_span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LaterDispositionEvent":
        if not isinstance(value, Mapping):
            raise TypeError("LaterDispositionEvent must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", REJECTION_MAPPING_SCHEMA_VERSION
            ),
            event_id=value.get("event_id", ""),
            kind=value.get("kind", LaterDispositionKind.UNKNOWN.value),
            action_id=value.get("action_id"),
            related_mapping_ids=tuple(value.get("related_mapping_ids") or ()),
            as_of=value.get("as_of"),
            notes=tuple(value.get("notes") or ()),
            source_span_id=value.get("source_span_id"),
        )


@dataclass(frozen=True, slots=True)
class RejectionSourceInput:
    """One rejection (or objection) surface to map.

    Prefer building from :class:`AnalysisCandidate` via
    :meth:`from_analysis_candidate`. Free-text fields are digests/surfaces for
    mapping only — never treated as a patentability opinion.
    """

    source_id: str
    kind: str
    surface_text: str
    source_span_id: str | None
    action_id: str | None
    artifact_id: str | None
    claim_tokens: tuple[str, ...]
    claim_ambiguity: str | None
    legal_citations: tuple[str, ...]
    citation_keys: tuple[str, ...]
    requirement_type: str | None
    alternatives: tuple[str, ...]
    exceptions: tuple[str, ...]
    confidence: float | None
    lifecycle_status: MappingLifecycleStatus | str
    mailing_date: str | None
    prior_art_surfaces: tuple[str, ...]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "kind", _require_str(self.kind, "kind", max_len=64)
        )
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        if len(self.surface_text) > 16_000:
            raise ValueError("surface_text exceeds max length 16000")
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "claim_tokens",
            _tuple_of_str(self.claim_tokens, "claim_tokens", max_items=256),
        )
        object.__setattr__(
            self,
            "claim_ambiguity",
            _optional_str(self.claim_ambiguity, "claim_ambiguity", max_len=64),
        )
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=64),
        )
        object.__setattr__(
            self,
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        object.__setattr__(
            self,
            "requirement_type",
            _optional_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self,
            "alternatives",
            _tuple_of_str(self.alternatives, "alternatives", max_items=32),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_str(self.exceptions, "exceptions", max_items=32),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "lifecycle_status",
            _coerce_enum(
                MappingLifecycleStatus, self.lifecycle_status, "lifecycle_status"
            ),
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "prior_art_surfaces",
            _tuple_of_str(
                self.prior_art_surfaces, "prior_art_surfaces", max_items=64
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "alternatives": list(self.alternatives),
            "artifact_id": self.artifact_id,
            "citation_keys": list(self.citation_keys),
            "claim_ambiguity": self.claim_ambiguity,
            "claim_tokens": list(self.claim_tokens),
            "confidence": self.confidence,
            "exceptions": list(self.exceptions),
            "kind": self.kind,
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "lifecycle_status": (
                self.lifecycle_status.value
                if isinstance(self.lifecycle_status, MappingLifecycleStatus)
                else str(self.lifecycle_status)
            ),
            "mailing_date": self.mailing_date,
            "prior_art_surfaces": list(self.prior_art_surfaces),
            "requirement_type": self.requirement_type,
            "source_id": self.source_id,
            "source_span_id": self.source_span_id,
            "surface_text": self.surface_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RejectionSourceInput":
        if not isinstance(value, Mapping):
            raise TypeError("RejectionSourceInput must be a mapping")
        return cls(
            source_id=value.get("source_id", ""),
            kind=value.get("kind", "rejection"),
            surface_text=str(value.get("surface_text") or ""),
            source_span_id=value.get("source_span_id"),
            action_id=value.get("action_id"),
            artifact_id=value.get("artifact_id"),
            claim_tokens=tuple(value.get("claim_tokens") or ()),
            claim_ambiguity=value.get("claim_ambiguity"),
            legal_citations=tuple(value.get("legal_citations") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            requirement_type=value.get("requirement_type"),
            alternatives=tuple(value.get("alternatives") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            confidence=value.get("confidence"),
            lifecycle_status=value.get(
                "lifecycle_status", MappingLifecycleStatus.UNKNOWN.value
            ),
            mailing_date=value.get("mailing_date"),
            prior_art_surfaces=tuple(value.get("prior_art_surfaces") or ()),
            labels=value.get("labels") or {},
        )

    @classmethod
    def from_analysis_candidate(
        cls,
        cand: AnalysisCandidate,
        *,
        action_id: str | None = None,
        artifact_id: str | None = None,
        lifecycle_status: MappingLifecycleStatus | str = MappingLifecycleStatus.ACTIVE,
        mailing_date: str | None = None,
        prior_art_surfaces: Sequence[str] = (),
    ) -> "RejectionSourceInput":
        return cls(
            source_id=cand.candidate_id,
            kind=cand.kind.value if isinstance(cand.kind, CandidateKind) else str(cand.kind),
            surface_text=cand.surface_text,
            source_span_id=cand.source_span_id,
            action_id=action_id,
            artifact_id=artifact_id,
            claim_tokens=cand.claim_tokens,
            claim_ambiguity=cand.ambiguity,
            legal_citations=cand.legal_citations,
            citation_keys=cand.citation_keys,
            requirement_type=cand.requirement_type,
            alternatives=cand.alternatives,
            exceptions=cand.exceptions,
            confidence=cand.confidence,
            lifecycle_status=lifecycle_status,
            mailing_date=mailing_date,
            prior_art_surfaces=tuple(prior_art_surfaces),
            labels=dict(cand.labels),
        )


@dataclass(frozen=True, slots=True)
class RejectionMappingInput:
    """Inputs for rejection → claim / statute / reference mapping."""

    matter_id: str | None = None
    rejections: tuple[RejectionSourceInput, ...] = ()
    claim_sets: tuple[ClaimSetSnapshot, ...] = ()
    later_dispositions: tuple[LaterDispositionEvent, ...] = ()
    office_action_results: tuple[OfficeActionResult, ...] = ()
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        if not isinstance(self.rejections, tuple):
            object.__setattr__(self, "rejections", tuple(self.rejections or ()))
        if not isinstance(self.claim_sets, tuple):
            object.__setattr__(self, "claim_sets", tuple(self.claim_sets or ()))
        if not isinstance(self.later_dispositions, tuple):
            object.__setattr__(
                self, "later_dispositions", tuple(self.later_dispositions or ())
            )
        if not isinstance(self.office_action_results, tuple):
            object.__setattr__(
                self,
                "office_action_results",
                tuple(self.office_action_results or ()),
            )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )


@dataclass(frozen=True, slots=True)
class StatutoryBasisRecord:
    """A stated statutory basis — never invented from silence."""

    family: StatutoryBasisFamily
    section: str | None
    subsection: str | None
    surface_form: str | None
    stated_explicitly: bool
    source_span_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "family",
            _coerce_enum(StatutoryBasisFamily, self.family, "family"),
        )
        object.__setattr__(
            self, "section", _optional_str(self.section, "section", max_len=32)
        )
        object.__setattr__(
            self,
            "subsection",
            _optional_str(self.subsection, "subsection", max_len=64),
        )
        object.__setattr__(
            self,
            "surface_form",
            _optional_str(self.surface_form, "surface_form", max_len=256),
        )
        if not isinstance(self.stated_explicitly, bool):
            raise TypeError("stated_explicitly must be bool")
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        # Invariant: UNKNOWN family cannot be stated_explicitly.
        if self.family is StatutoryBasisFamily.UNKNOWN and self.stated_explicitly:
            object.__setattr__(self, "stated_explicitly", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.value,
            "section": self.section,
            "source_span_id": self.source_span_id,
            "stated_explicitly": self.stated_explicitly,
            "subsection": self.subsection,
            "surface_form": self.surface_form,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StatutoryBasisRecord":
        if not isinstance(value, Mapping):
            raise TypeError("StatutoryBasisRecord must be a mapping")
        return cls(
            family=value.get("family", StatutoryBasisFamily.UNKNOWN.value),
            section=value.get("section"),
            subsection=value.get("subsection"),
            surface_form=value.get("surface_form"),
            stated_explicitly=bool(value.get("stated_explicitly", False)),
            source_span_id=value.get("source_span_id"),
        )


@dataclass(frozen=True, slots=True)
class ClaimLinkRecord:
    """One claim number linked to a rejection, with resolution status."""

    claim_number: str
    resolution: ClaimResolutionStatus
    claim_set_version_id: str | None
    claim_span_id: str | None
    in_claim_set: bool | None
    ambiguity: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "claim_number",
            _require_str(self.claim_number, "claim_number", max_len=32),
        )
        object.__setattr__(
            self,
            "resolution",
            _coerce_enum(ClaimResolutionStatus, self.resolution, "resolution"),
        )
        object.__setattr__(
            self,
            "claim_set_version_id",
            _optional_identifier(self.claim_set_version_id, "claim_set_version_id"),
        )
        object.__setattr__(
            self,
            "claim_span_id",
            _optional_identifier(self.claim_span_id, "claim_span_id"),
        )
        if self.in_claim_set is not None and not isinstance(self.in_claim_set, bool):
            raise TypeError("in_claim_set must be bool or None")
        object.__setattr__(
            self, "ambiguity", _optional_str(self.ambiguity, "ambiguity", max_len=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity": self.ambiguity,
            "claim_number": self.claim_number,
            "claim_set_version_id": self.claim_set_version_id,
            "claim_span_id": self.claim_span_id,
            "in_claim_set": self.in_claim_set,
            "resolution": self.resolution.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimLinkRecord":
        if not isinstance(value, Mapping):
            raise TypeError("ClaimLinkRecord must be a mapping")
        return cls(
            claim_number=value.get("claim_number", ""),
            resolution=value.get(
                "resolution", ClaimResolutionStatus.UNKNOWN.value
            ),
            claim_set_version_id=value.get("claim_set_version_id"),
            claim_span_id=value.get("claim_span_id"),
            in_claim_set=value.get("in_claim_set"),
            ambiguity=value.get("ambiguity"),
        )


@dataclass(frozen=True, slots=True)
class CitedReferenceRecord:
    """A cited reference *as stated* by the examiner — never invented."""

    surface: str
    resolution: ReferenceResolutionStatus
    citation_key: str | None
    source_span_id: str | None
    reference_family: str | None
    surface_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.surface, str):
            raise TypeError("surface must be str")
        if len(self.surface) > 1024:
            raise ValueError("surface exceeds max length 1024")
        object.__setattr__(
            self,
            "resolution",
            _coerce_enum(ReferenceResolutionStatus, self.resolution, "resolution"),
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        object.__setattr__(
            self,
            "reference_family",
            _optional_str(self.reference_family, "reference_family", max_len=64),
        )
        digest = _require_str(self.surface_digest, "surface_digest", max_len=64).lower()
        if not _SHA256_RE.match(digest):
            # Auto-compute if placeholder empty-looking but surface present.
            if self.surface:
                digest = _text_digest(self.surface)
            else:
                raise ValueError("surface_digest must be sha256 hex")
        object.__setattr__(self, "surface_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_key": self.citation_key,
            "reference_family": self.reference_family,
            "resolution": self.resolution.value,
            "source_span_id": self.source_span_id,
            "surface": self.surface,
            "surface_digest": self.surface_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CitedReferenceRecord":
        if not isinstance(value, Mapping):
            raise TypeError("CitedReferenceRecord must be a mapping")
        surface = str(value.get("surface") or "")
        return cls(
            surface=surface,
            resolution=value.get(
                "resolution", ReferenceResolutionStatus.UNKNOWN.value
            ),
            citation_key=value.get("citation_key"),
            source_span_id=value.get("source_span_id"),
            reference_family=value.get("reference_family"),
            surface_digest=value.get("surface_digest") or _text_digest(surface),
        )


@dataclass(frozen=True, slots=True)
class DispositionHistoryEntry:
    """One historical disposition state retained for a mapping."""

    status: MappingLifecycleStatus
    as_of: str | None
    action_id: str | None
    note: str | None
    source_event_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_enum(MappingLifecycleStatus, self.status, "status"),
        )
        object.__setattr__(
            self, "as_of", _optional_str(self.as_of, "as_of", max_len=64)
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "note", _optional_str(self.note, "note", max_len=512)
        )
        object.__setattr__(
            self,
            "source_event_id",
            _optional_identifier(self.source_event_id, "source_event_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "as_of": self.as_of,
            "note": self.note,
            "source_event_id": self.source_event_id,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DispositionHistoryEntry":
        if not isinstance(value, Mapping):
            raise TypeError("DispositionHistoryEntry must be a mapping")
        return cls(
            status=value.get("status", MappingLifecycleStatus.UNKNOWN.value),
            as_of=value.get("as_of"),
            action_id=value.get("action_id"),
            note=value.get("note"),
            source_event_id=value.get("source_event_id"),
        )


@dataclass(frozen=True, slots=True)
class RejectionMapEntry:
    """One rejection mapped to claims, statute, examiner statement, references.

    This is an examiner-statement record only — not a patentability opinion.
    """

    schema_version: str
    mapping_id: str
    source_id: str
    action_id: str | None
    artifact_id: str | None
    source_span_id: str | None
    examiner_statement_digest: str
    examiner_statement_surface: str
    statutory_basis: StatutoryBasisRecord
    claim_links: tuple[ClaimLinkRecord, ...]
    claim_resolution: ClaimResolutionStatus
    claim_ambiguity: str | None
    stated_claim_tokens: tuple[str, ...]
    limitation_surfaces: tuple[str, ...]
    cited_references: tuple[CitedReferenceRecord, ...]
    reference_resolution: ReferenceResolutionStatus
    alternatives: tuple[str, ...]
    exceptions: tuple[str, ...]
    lifecycle_status: MappingLifecycleStatus
    later_disposition: LaterDispositionKind
    disposition_history: tuple[DispositionHistoryEntry, ...]
    claim_set_version_ids: tuple[str, ...]
    review_state: ReviewState
    confidence: float | None
    reason_codes: tuple[str, ...]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != REJECTION_MAPPING_SCHEMA_VERSION:
            raise ValueError(
                "RejectionMapEntry.schema_version must be "
                f"{REJECTION_MAPPING_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "mapping_id", _identifier(self.mapping_id, "mapping_id")
        )
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        digest = _require_str(
            self.examiner_statement_digest, "examiner_statement_digest", max_len=64
        ).lower()
        if not _SHA256_RE.match(digest):
            raise ValueError("examiner_statement_digest must be sha256 hex")
        object.__setattr__(self, "examiner_statement_digest", digest)
        if not isinstance(self.examiner_statement_surface, str):
            raise TypeError("examiner_statement_surface must be str")
        if len(self.examiner_statement_surface) > 16_000:
            raise ValueError("examiner_statement_surface exceeds max length")
        if not isinstance(self.statutory_basis, StatutoryBasisRecord):
            raise TypeError("statutory_basis must be StatutoryBasisRecord")
        if not isinstance(self.claim_links, tuple):
            object.__setattr__(self, "claim_links", tuple(self.claim_links))
        object.__setattr__(
            self,
            "claim_resolution",
            _coerce_enum(
                ClaimResolutionStatus, self.claim_resolution, "claim_resolution"
            ),
        )
        object.__setattr__(
            self,
            "claim_ambiguity",
            _optional_str(self.claim_ambiguity, "claim_ambiguity", max_len=64),
        )
        object.__setattr__(
            self,
            "stated_claim_tokens",
            _tuple_of_str(
                self.stated_claim_tokens, "stated_claim_tokens", max_items=256
            ),
        )
        object.__setattr__(
            self,
            "limitation_surfaces",
            _tuple_of_str(
                self.limitation_surfaces, "limitation_surfaces", max_items=64
            ),
        )
        if not isinstance(self.cited_references, tuple):
            object.__setattr__(
                self, "cited_references", tuple(self.cited_references)
            )
        object.__setattr__(
            self,
            "reference_resolution",
            _coerce_enum(
                ReferenceResolutionStatus,
                self.reference_resolution,
                "reference_resolution",
            ),
        )
        object.__setattr__(
            self,
            "alternatives",
            _tuple_of_str(self.alternatives, "alternatives", max_items=32),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_str(self.exceptions, "exceptions", max_items=32),
        )
        object.__setattr__(
            self,
            "lifecycle_status",
            _coerce_enum(
                MappingLifecycleStatus, self.lifecycle_status, "lifecycle_status"
            ),
        )
        object.__setattr__(
            self,
            "later_disposition",
            _coerce_enum(
                LaterDispositionKind, self.later_disposition, "later_disposition"
            ),
        )
        if not isinstance(self.disposition_history, tuple):
            object.__setattr__(
                self, "disposition_history", tuple(self.disposition_history)
            )
        object.__setattr__(
            self,
            "claim_set_version_ids",
            _tuple_of_str(
                self.claim_set_version_ids, "claim_set_version_ids", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "alternatives": list(self.alternatives),
            "artifact_id": self.artifact_id,
            "claim_ambiguity": self.claim_ambiguity,
            "claim_links": [c.to_dict() for c in self.claim_links],
            "claim_resolution": self.claim_resolution.value,
            "claim_set_version_ids": list(self.claim_set_version_ids),
            "cited_references": [r.to_dict() for r in self.cited_references],
            "confidence": self.confidence,
            "disposition_history": [h.to_dict() for h in self.disposition_history],
            "examiner_statement_digest": self.examiner_statement_digest,
            "examiner_statement_surface": self.examiner_statement_surface,
            "exceptions": list(self.exceptions),
            "labels": dict(self.labels),
            "later_disposition": self.later_disposition.value,
            "lifecycle_status": self.lifecycle_status.value,
            "limitation_surfaces": list(self.limitation_surfaces),
            "mapping_id": self.mapping_id,
            "reason_codes": list(self.reason_codes),
            "reference_resolution": self.reference_resolution.value,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_span_id": self.source_span_id,
            "stated_claim_tokens": list(self.stated_claim_tokens),
            "statutory_basis": self.statutory_basis.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RejectionMapEntry":
        if not isinstance(value, Mapping):
            raise TypeError("RejectionMapEntry must be a mapping")
        basis_raw = value.get("statutory_basis") or {}
        basis = (
            basis_raw
            if isinstance(basis_raw, StatutoryBasisRecord)
            else StatutoryBasisRecord.from_dict(basis_raw)
        )
        return cls(
            schema_version=value.get(
                "schema_version", REJECTION_MAPPING_SCHEMA_VERSION
            ),
            mapping_id=value.get("mapping_id", ""),
            source_id=value.get("source_id", ""),
            action_id=value.get("action_id"),
            artifact_id=value.get("artifact_id"),
            source_span_id=value.get("source_span_id"),
            examiner_statement_digest=value.get("examiner_statement_digest", ""),
            examiner_statement_surface=str(
                value.get("examiner_statement_surface") or ""
            ),
            statutory_basis=basis,
            claim_links=tuple(
                ClaimLinkRecord.from_dict(c)
                for c in (value.get("claim_links") or ())
            ),
            claim_resolution=value.get(
                "claim_resolution", ClaimResolutionStatus.UNKNOWN.value
            ),
            claim_ambiguity=value.get("claim_ambiguity"),
            stated_claim_tokens=tuple(value.get("stated_claim_tokens") or ()),
            limitation_surfaces=tuple(value.get("limitation_surfaces") or ()),
            cited_references=tuple(
                CitedReferenceRecord.from_dict(r)
                for r in (value.get("cited_references") or ())
            ),
            reference_resolution=value.get(
                "reference_resolution", ReferenceResolutionStatus.UNKNOWN.value
            ),
            alternatives=tuple(value.get("alternatives") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            lifecycle_status=value.get(
                "lifecycle_status", MappingLifecycleStatus.UNKNOWN.value
            ),
            later_disposition=value.get(
                "later_disposition", LaterDispositionKind.NONE.value
            ),
            disposition_history=tuple(
                DispositionHistoryEntry.from_dict(h)
                for h in (value.get("disposition_history") or ())
            ),
            claim_set_version_ids=tuple(value.get("claim_set_version_ids") or ()),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            confidence=value.get("confidence"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class RejectionMappingResult:
    """Full examiner-statement mapping outcome.

    Always declares ``output_kind`` as examiner-statement map and carries the
    non-patentability disclaimer. Never a patentability determination.
    """

    schema_version: str
    analysis_id: str
    matter_id: str | None
    disposition: MappingDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    output_kind: str
    disclaimer: str
    is_patentability_determination: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    mappings: tuple[RejectionMapEntry, ...]
    claim_sets: tuple[ClaimSetSnapshot, ...]
    later_dispositions: tuple[LaterDispositionEvent, ...]
    retained_history_count: int
    ruleset_versions: Mapping[str, str]
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != REJECTION_MAPPING_SCHEMA_VERSION:
            raise ValueError(
                "RejectionMappingResult.schema_version must be "
                f"{REJECTION_MAPPING_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(MappingDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_EXAMINER_STATEMENT_MAP:
            raise ValueError(
                "output_kind must be "
                f"{OUTPUT_KIND_EXAMINER_STATEMENT_MAP!r} "
                "(examiner-statement map only)"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        if "not a patentability determination" not in self.disclaimer.lower():
            raise ValueError(
                "disclaimer must state this is not a patentability determination"
            )
        if not isinstance(self.is_patentability_determination, bool):
            raise TypeError("is_patentability_determination must be bool")
        if self.is_patentability_determination:
            raise ValueError(
                "is_patentability_determination must be False — this module "
                "never produces a patentability determination"
            )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        if not isinstance(self.mappings, tuple):
            object.__setattr__(self, "mappings", tuple(self.mappings))
        if not isinstance(self.claim_sets, tuple):
            object.__setattr__(self, "claim_sets", tuple(self.claim_sets))
        if not isinstance(self.later_dispositions, tuple):
            object.__setattr__(
                self, "later_dispositions", tuple(self.later_dispositions)
            )
        object.__setattr__(
            self,
            "retained_history_count",
            _nonneg_int(self.retained_history_count, "retained_history_count"),
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=16),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def requires_review(self) -> bool:
        return self.disposition in (
            MappingDisposition.REVIEW,
            MappingDisposition.UNKNOWN,
            MappingDisposition.QUARANTINE,
            MappingDisposition.REJECTED,
            MappingDisposition.PARTIAL,
        ) or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)

    def mapping_by_id(self, mapping_id: str) -> RejectionMapEntry | None:
        for m in self.mappings:
            if m.mapping_id == mapping_id:
                return m
        return None

    def mappings_for_action(self, action_id: str) -> tuple[RejectionMapEntry, ...]:
        return tuple(m for m in self.mappings if m.action_id == action_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "claim_sets": [c.to_dict() for c in self.claim_sets],
            "classification": self.classification.value,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "is_patentability_determination": self.is_patentability_determination,
            "labels": dict(self.labels),
            "later_dispositions": [d.to_dict() for d in self.later_dispositions],
            "mappings": [m.to_dict() for m in self.mappings],
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "retained_history_count": self.retained_history_count,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — no examiner body text."""
        return {
            "analysis_id": self.analysis_id,
            "claim_set_count": len(self.claim_sets),
            "classification": self.classification.value,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "is_patentability_determination": False,
            "later_disposition_count": len(self.later_dispositions),
            "mapping_count": len(self.mappings),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "retained_history_count": self.retained_history_count,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RejectionMappingResult":
        if not isinstance(value, Mapping):
            raise TypeError("RejectionMappingResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", REJECTION_MAPPING_SCHEMA_VERSION
            ),
            analysis_id=value.get("analysis_id", ""),
            matter_id=value.get("matter_id"),
            disposition=value.get("disposition", MappingDisposition.UNKNOWN.value),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_EXAMINER_STATEMENT_MAP
            ),
            disclaimer=value.get("disclaimer", NOT_PATENTABILITY_DISCLAIMER),
            is_patentability_determination=bool(
                value.get("is_patentability_determination", False)
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            mappings=tuple(
                RejectionMapEntry.from_dict(m) for m in (value.get("mappings") or ())
            ),
            claim_sets=tuple(
                ClaimSetSnapshot.from_dict(c) for c in (value.get("claim_sets") or ())
            ),
            later_dispositions=tuple(
                LaterDispositionEvent.from_dict(d)
                for d in (value.get("later_dispositions") or ())
            ),
            retained_history_count=int(value.get("retained_history_count", 0)),
            ruleset_versions=value.get("ruleset_versions") or {},
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class RejectionMappingProcessor:
    """Map examiner rejection statements to claims, statutes, and references.

    Produces an examiner-statement map only. Never determines patentability.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        max_mappings: int = DEFAULT_MAX_MAPPINGS,
    ) -> None:
        self._id_factory = id_factory or (lambda: f"rm:{uuid.uuid4().hex[:16]}")
        self._max_mappings = _nonneg_int(max_mappings, "max_mappings")

    def map(
        self,
        value: RejectionMappingInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> RejectionMappingResult:
        if value is None:
            inp = RejectionMappingInput(**kwargs)
        elif isinstance(value, RejectionMappingInput):
            if kwargs:
                raise TypeError("map() does not accept kwargs with an input object")
            inp = value
        elif isinstance(value, Mapping):
            if kwargs:
                raise TypeError("map() does not accept kwargs with a mapping")
            inp = self._input_from_mapping(value)
        else:
            raise TypeError(
                "value must be RejectionMappingInput, mapping, or None"
            )
        return self._map(inp)

    def map_many(
        self, inputs: Iterable[RejectionMappingInput | Mapping[str, Any]]
    ) -> tuple[RejectionMappingResult, ...]:
        return tuple(self.map(item) for item in inputs)

    def _input_from_mapping(self, value: Mapping[str, Any]) -> RejectionMappingInput:
        rejections = tuple(
            RejectionSourceInput.from_dict(r)
            for r in (value.get("rejections") or ())
        )
        claim_sets = tuple(
            ClaimSetSnapshot.from_dict(c) for c in (value.get("claim_sets") or ())
        )
        later = tuple(
            LaterDispositionEvent.from_dict(d)
            for d in (value.get("later_dispositions") or ())
        )
        oa_results: list[OfficeActionResult] = []
        for raw in value.get("office_action_results") or ():
            if isinstance(raw, OfficeActionResult):
                oa_results.append(raw)
            elif isinstance(raw, Mapping):
                oa_results.append(OfficeActionResult.from_dict(raw))
            else:
                raise TypeError(
                    "office_action_results items must be OfficeActionResult or mapping"
                )
        return RejectionMappingInput(
            matter_id=value.get("matter_id"),
            rejections=rejections,
            claim_sets=claim_sets,
            later_dispositions=later,
            office_action_results=tuple(oa_results),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )

    def _map(self, inp: RejectionMappingInput) -> RejectionMappingResult:
        analysis_id = self._id_factory()
        reason_codes: list[str] = [
            RejectionMappingReasonCode.EXAMINER_STATEMENT_MAP_ONLY.value,
            RejectionMappingReasonCode.NOT_PATENTABILITY_DETERMINATION.value,
        ]
        warnings: list[str] = []

        # Collect rejection sources: explicit inputs + derived from OA results.
        sources = list(inp.rejections)
        for oa in inp.office_action_results:
            sources.extend(self._sources_from_office_action(oa))

        # Inherit classification from office actions when input left as UNKNOWN.
        classification = inp.classification
        if (
            classification is DisclosureClassification.UNKNOWN
            and inp.office_action_results
        ):
            classification = most_restrictive_classification(
                [oa.classification for oa in inp.office_action_results]
            )

        claim_sets = list(inp.claim_sets)
        if len(claim_sets) > DEFAULT_MAX_CLAIM_SETS:
            claim_sets = claim_sets[:DEFAULT_MAX_CLAIM_SETS]
            warnings.append("claim_set_limit_applied")
            reason_codes.append(RejectionMappingReasonCode.MAPPING_LIMIT.value)

        current_set = self._select_current_claim_set(claim_sets)
        has_claim_set = current_set is not None and bool(current_set.claim_numbers)
        if not has_claim_set:
            reason_codes.append(RejectionMappingReasonCode.MISSING_CLAIM_SET.value)

        if not sources:
            reason_codes.append(RejectionMappingReasonCode.EMPTY_INPUT.value)
            reason_codes.append(RejectionMappingReasonCode.NO_REJECTIONS.value)
            disposition = (
                MappingDisposition.REVIEW
                if not has_claim_set
                else MappingDisposition.UNKNOWN
            )
            review = (
                ReviewState.REQUIRED
                if not has_claim_set
                else ReviewState.PENDING
            )
            if requires_quarantine(classification):
                disposition = MappingDisposition.QUARANTINE
                review = ReviewState.REQUIRED
                reason_codes.append(
                    RejectionMappingReasonCode.QUARANTINE_CLASSIFICATION.value
                )
            return RejectionMappingResult(
                schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
                analysis_id=analysis_id,
                matter_id=inp.matter_id,
                disposition=disposition,
                review_state=review,
                classification=classification,
                output_kind=OUTPUT_KIND_EXAMINER_STATEMENT_MAP,
                disclaimer=NOT_PATENTABILITY_DISCLAIMER,
                is_patentability_determination=False,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                warnings=tuple(warnings),
                mappings=(),
                claim_sets=tuple(claim_sets),
                later_dispositions=tuple(inp.later_dispositions),
                retained_history_count=0,
                ruleset_versions={"rejection_mapping": REJECTION_MAPPING_RULESET_VERSION},
                labels=dict(inp.labels),
            )

        # Index later dispositions by action / mapping id for history.
        later_by_action: dict[str, list[LaterDispositionEvent]] = {}
        later_global: list[LaterDispositionEvent] = []
        for ev in inp.later_dispositions:
            if ev.action_id:
                later_by_action.setdefault(ev.action_id, []).append(ev)
            else:
                later_global.append(ev)

        mappings: list[RejectionMapEntry] = []
        history_count = 0
        needs_review = False
        partial = False
        any_mapped = False

        for src in sources[: self._max_mappings]:
            entry = self._map_one(
                src,
                analysis_id=analysis_id,
                current_set=current_set,
                all_claim_sets=claim_sets,
                later_by_action=later_by_action,
                later_global=later_global,
            )
            mappings.append(entry)
            history_count += len(entry.disposition_history)
            any_mapped = True

            if entry.claim_resolution in (
                ClaimResolutionStatus.MISSING_CLAIM_SET,
                ClaimResolutionStatus.UNRESOLVED,
                ClaimResolutionStatus.OPEN_ENDED,
                ClaimResolutionStatus.AMBIGUOUS,
                ClaimResolutionStatus.CLAIM_NOT_IN_SET,
                ClaimResolutionStatus.PARTIAL,
                ClaimResolutionStatus.UNKNOWN,
            ):
                needs_review = True
            if entry.claim_resolution in (
                ClaimResolutionStatus.PARTIAL,
                ClaimResolutionStatus.CLAIM_NOT_IN_SET,
                ClaimResolutionStatus.OPEN_ENDED,
                ClaimResolutionStatus.UNRESOLVED,
            ):
                partial = True
            if entry.statutory_basis.family is StatutoryBasisFamily.UNKNOWN:
                partial = True
                needs_review = True
            if entry.lifecycle_status in (
                MappingLifecycleStatus.RESCINDED,
                MappingLifecycleStatus.SUPERSEDED,
                MappingLifecycleStatus.REISSUED,
                MappingLifecycleStatus.WITHDRAWN,
                MappingLifecycleStatus.AMENDED_CLAIM_HISTORY,
            ):
                reason_codes.append(
                    RejectionMappingReasonCode.LIFECYCLE_HISTORY_RETAINED.value
                )
            if any(
                h.status is MappingLifecycleStatus.AMENDED_CLAIM_HISTORY
                for h in entry.disposition_history
            ):
                reason_codes.append(
                    RejectionMappingReasonCode.AMENDED_CLAIM_HISTORY_RETAINED.value
                )
            if entry.alternatives:
                reason_codes.append(
                    RejectionMappingReasonCode.ALTERNATIVES_PRESERVED.value
                )
            if entry.claim_ambiguity and entry.claim_ambiguity != (
                ClaimRangeAmbiguity.EXACT.value
            ):
                reason_codes.append(
                    RejectionMappingReasonCode.AMBIGUITY_PRESERVED.value
                )

        if len(sources) > self._max_mappings:
            warnings.append("mapping_limit_applied")
            reason_codes.append(RejectionMappingReasonCode.MAPPING_LIMIT.value)
            needs_review = True

        if any_mapped:
            reason_codes.append(RejectionMappingReasonCode.REJECTIONS_MAPPED.value)
        if any(
            m.statutory_basis.stated_explicitly
            and m.statutory_basis.family is not StatutoryBasisFamily.UNKNOWN
            for m in mappings
        ):
            reason_codes.append(
                RejectionMappingReasonCode.STATUTORY_BASES_MAPPED.value
            )
        if any(
            m.claim_resolution is ClaimResolutionStatus.RESOLVED for m in mappings
        ):
            reason_codes.append(RejectionMappingReasonCode.CLAIMS_RESOLVED.value)
        if any(
            m.reference_resolution is ReferenceResolutionStatus.STATED
            for m in mappings
        ):
            reason_codes.append(RejectionMappingReasonCode.REFERENCES_MAPPED.value)
        if any(
            m.claim_resolution is ClaimResolutionStatus.MISSING_CLAIM_SET
            for m in mappings
        ):
            # already added earlier; ensure present
            if (
                RejectionMappingReasonCode.MISSING_CLAIM_SET.value
                not in reason_codes
            ):
                reason_codes.append(
                    RejectionMappingReasonCode.MISSING_CLAIM_SET.value
                )
        if any(
            m.claim_resolution is ClaimResolutionStatus.OPEN_ENDED for m in mappings
        ):
            reason_codes.append(
                RejectionMappingReasonCode.CLAIM_RANGE_OPEN_ENDED.value
            )
        if any(
            m.claim_resolution is ClaimResolutionStatus.UNRESOLVED for m in mappings
        ):
            reason_codes.append(
                RejectionMappingReasonCode.CLAIM_RANGE_UNRESOLVED.value
            )
        if any(
            m.claim_resolution is ClaimResolutionStatus.CLAIM_NOT_IN_SET
            for m in mappings
        ):
            reason_codes.append(RejectionMappingReasonCode.CLAIM_NOT_IN_SET.value)
        if any(
            m.reference_resolution is ReferenceResolutionStatus.UNSTATED
            for m in mappings
        ):
            reason_codes.append(RejectionMappingReasonCode.REFERENCE_UNSTATED.value)
        if any(
            m.statutory_basis.family is StatutoryBasisFamily.UNKNOWN for m in mappings
        ):
            reason_codes.append(
                RejectionMappingReasonCode.STATUTORY_BASIS_UNKNOWN.value
            )

        # Historical claim sets (non-current) always retained on the result.
        historical_sets = [c for c in claim_sets if not c.is_current]
        if historical_sets:
            reason_codes.append(
                RejectionMappingReasonCode.AMENDED_CLAIM_HISTORY_RETAINED.value
            )
            history_count += len(historical_sets)

        disposition, review = self._finalize_disposition(
            classification=classification,
            needs_review=needs_review,
            partial=partial,
            has_claim_set=has_claim_set,
            any_mapped=any_mapped,
        )
        if disposition in (
            MappingDisposition.REVIEW,
            MappingDisposition.UNKNOWN,
            MappingDisposition.PARTIAL,
            MappingDisposition.QUARANTINE,
        ):
            reason_codes.append(RejectionMappingReasonCode.REVIEW_REQUIRED.value)
        if partial:
            reason_codes.append(RejectionMappingReasonCode.PARTIAL_MAPPING.value)
        if requires_quarantine(classification):
            reason_codes.append(
                RejectionMappingReasonCode.QUARANTINE_CLASSIFICATION.value
            )

        # Deduplicate reason codes while preserving order.
        unique_reasons = tuple(dict.fromkeys(reason_codes))

        return RejectionMappingResult(
            schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
            analysis_id=analysis_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review,
            classification=classification,
            output_kind=OUTPUT_KIND_EXAMINER_STATEMENT_MAP,
            disclaimer=NOT_PATENTABILITY_DISCLAIMER,
            is_patentability_determination=False,
            reason_codes=unique_reasons,
            warnings=tuple(dict.fromkeys(warnings)),
            mappings=tuple(mappings),
            claim_sets=tuple(claim_sets),
            later_dispositions=tuple(inp.later_dispositions),
            retained_history_count=history_count,
            ruleset_versions={"rejection_mapping": REJECTION_MAPPING_RULESET_VERSION},
            labels=dict(inp.labels),
        )

    def _sources_from_office_action(
        self, oa: OfficeActionResult
    ) -> list[RejectionSourceInput]:
        # Prefer lifecycle status from OA lifecycle records for this action.
        lifecycle_status = MappingLifecycleStatus.ACTIVE
        if oa.lifecycle:
            # Use the most recent / first matching record for this action_id.
            for rec in oa.lifecycle:
                if rec.action_id == oa.action_id or len(oa.lifecycle) == 1:
                    lifecycle_status = _lifecycle_from_action(rec.status)
                    break
            else:
                lifecycle_status = _lifecycle_from_action(oa.lifecycle[0].status)
        # Also derive from action_kind.
        kind_val = (
            oa.action_kind.value
            if hasattr(oa.action_kind, "value")
            else str(oa.action_kind)
        )
        if kind_val == "rescinded_action":
            lifecycle_status = MappingLifecycleStatus.RESCINDED
        elif kind_val == "reissued_action":
            lifecycle_status = MappingLifecycleStatus.REISSUED

        prior_art = tuple(
            c.surface_text
            for c in oa.candidates
            if c.kind is CandidateKind.PRIOR_ART and c.surface_text
        )

        out: list[RejectionSourceInput] = []
        for cand in oa.candidates:
            if cand.kind is not CandidateKind.REJECTION:
                continue
            out.append(
                RejectionSourceInput.from_analysis_candidate(
                    cand,
                    action_id=oa.action_id,
                    artifact_id=oa.artifact_id,
                    lifecycle_status=lifecycle_status,
                    mailing_date=oa.mailing_date,
                    prior_art_surfaces=prior_art,
                )
            )
        return out

    def _select_current_claim_set(
        self, claim_sets: Sequence[ClaimSetSnapshot]
    ) -> ClaimSetSnapshot | None:
        if not claim_sets:
            return None
        for cs in claim_sets:
            if cs.is_current:
                return cs
        # Fall back to last provided set without inventing numbers.
        return claim_sets[-1]

    def _map_one(
        self,
        src: RejectionSourceInput,
        *,
        analysis_id: str,
        current_set: ClaimSetSnapshot | None,
        all_claim_sets: Sequence[ClaimSetSnapshot],
        later_by_action: Mapping[str, Sequence[LaterDispositionEvent]],
        later_global: Sequence[LaterDispositionEvent],
    ) -> RejectionMapEntry:
        del analysis_id  # reserved for correlated ids
        mapping_id = self._id_factory()
        entry_reasons: list[str] = []

        # --- statutory basis (stated only) ---
        family, section, subsection, surface_form = parse_statutory_basis_surface(
            src.surface_text, requirement_type=src.requirement_type
        )
        stated = family is not StatutoryBasisFamily.UNKNOWN
        basis = StatutoryBasisRecord(
            family=family,
            section=section,
            subsection=subsection,
            surface_form=surface_form,
            stated_explicitly=stated,
            source_span_id=src.source_span_id,
        )
        if not stated:
            entry_reasons.append(
                RejectionMappingReasonCode.STATUTORY_BASIS_UNKNOWN.value
            )

        # --- claims (never guess) ---
        tokens = list(src.claim_tokens)
        ambiguity = src.claim_ambiguity
        # If tokens empty but surface has claim language, re-parse without guessing.
        if not tokens and src.surface_text:
            re_tokens, re_amb = parse_claim_range_surface(src.surface_text)
            # Only accept tokens when ambiguity is exact or multi-segment.
            if re_tokens and re_amb in (
                ClaimRangeAmbiguity.EXACT,
                ClaimRangeAmbiguity.MULTI_SEGMENT,
            ):
                tokens = list(re_tokens)
                ambiguity = re_amb.value
            elif re_amb is ClaimRangeAmbiguity.OPEN_ENDED:
                ambiguity = re_amb.value
            elif re_amb is ClaimRangeAmbiguity.UNRESOLVED and not ambiguity:
                ambiguity = re_amb.value
            elif re_amb is ClaimRangeAmbiguity.CONFLICTING:
                ambiguity = re_amb.value

        has_claim_set = current_set is not None and bool(current_set.claim_numbers)
        claim_resolution = _claim_resolution_from_ambiguity(
            ambiguity, has_tokens=bool(tokens), has_claim_set=has_claim_set
        )

        claim_links: list[ClaimLinkRecord] = []
        version_ids: list[str] = []
        if current_set is not None:
            version_ids.append(current_set.version_id)

        if not has_claim_set:
            claim_resolution = ClaimResolutionStatus.MISSING_CLAIM_SET
            entry_reasons.append(
                RejectionMappingReasonCode.MISSING_CLAIM_SET.value
            )
            # Still record stated tokens as unresolved links (no set membership).
            for tok in tokens:
                claim_links.append(
                    ClaimLinkRecord(
                        claim_number=tok,
                        resolution=ClaimResolutionStatus.MISSING_CLAIM_SET,
                        claim_set_version_id=None,
                        claim_span_id=None,
                        in_claim_set=None,
                        ambiguity=ambiguity,
                    )
                )
        elif claim_resolution is ClaimResolutionStatus.OPEN_ENDED:
            entry_reasons.append(
                RejectionMappingReasonCode.CLAIM_RANGE_OPEN_ENDED.value
            )
            # No claim numbers invented for open-ended surfaces.
        elif claim_resolution is ClaimResolutionStatus.UNRESOLVED:
            entry_reasons.append(
                RejectionMappingReasonCode.CLAIM_RANGE_UNRESOLVED.value
            )
        elif tokens:
            assert current_set is not None
            number_set = current_set.number_set
            in_set_count = 0
            not_in_set = 0
            for tok in tokens:
                key = str(int(tok)) if tok.isdigit() else tok
                present = key in number_set
                if present:
                    in_set_count += 1
                    res = ClaimResolutionStatus.RESOLVED
                else:
                    not_in_set += 1
                    res = ClaimResolutionStatus.CLAIM_NOT_IN_SET
                claim_links.append(
                    ClaimLinkRecord(
                        claim_number=key,
                        resolution=res,
                        claim_set_version_id=current_set.version_id,
                        claim_span_id=current_set.claim_span_ids.get(key),
                        in_claim_set=present,
                        ambiguity=ambiguity,
                    )
                )
            if not_in_set and in_set_count:
                claim_resolution = ClaimResolutionStatus.PARTIAL
                entry_reasons.append(
                    RejectionMappingReasonCode.CLAIM_NOT_IN_SET.value
                )
            elif not_in_set and not in_set_count:
                claim_resolution = ClaimResolutionStatus.CLAIM_NOT_IN_SET
                entry_reasons.append(
                    RejectionMappingReasonCode.CLAIM_NOT_IN_SET.value
                )
            else:
                claim_resolution = ClaimResolutionStatus.RESOLVED

        # Historical claim-set links (amended history retention).
        history: list[DispositionHistoryEntry] = []
        for hist_set in all_claim_sets:
            if hist_set.is_current:
                continue
            version_ids.append(hist_set.version_id)
            # Retain that this version existed at mapping time.
            history.append(
                DispositionHistoryEntry(
                    status=MappingLifecycleStatus.AMENDED_CLAIM_HISTORY,
                    as_of=None,
                    action_id=src.action_id,
                    note=f"claim_set_version:{hist_set.version_id}",
                    source_event_id=None,
                )
            )

        # --- limitations (explicit only) ---
        limitations = extract_limitation_surfaces(src.surface_text)

        # --- cited references (stated only; never invent) ---
        refs: list[CitedReferenceRecord] = []
        ref_resolution = ReferenceResolutionStatus.UNSTATED

        # Prior-art surfaces attached to the source (from OA extraction).
        for surface in src.prior_art_surfaces:
            surface_n = _normalize_ws(surface)
            if not surface_n:
                continue
            # Only attach prior-art that appears in / near the rejection surface
            # OR is the sole prior-art set (action-level). Prefer surface overlap.
            if (
                surface_n.lower() in src.surface_text.lower()
                or len(src.prior_art_surfaces) <= 4
            ):
                refs.append(
                    CitedReferenceRecord(
                        surface=surface_n[:512],
                        resolution=ReferenceResolutionStatus.STATED,
                        citation_key=None,
                        source_span_id=src.source_span_id,
                        reference_family="prior_art",
                        surface_digest=_text_digest(surface_n),
                    )
                )

        # Citation keys / legal citations that look like prior-art patents
        # are already on the candidate; we record them as stated references
        # only when the surface mentions a patent-like identifier.
        patentish = re.findall(
            r"(?i)\b(?:U\.?\s*S\.?\s*Patent(?:\s+Application)?\s*)?"
            r"(?:Pub(?:lication)?\.?\s*)?(?:No\.?\s*)?"
            r"(?:\d[\d, ]{4,12}(?:\s*[A-Z]\d)?|"
            r"US\s*\d{4}/\d{7}\s*[A-Z]\d)\b",
            src.surface_text,
        )
        for pat in patentish:
            surface_n = _normalize_ws(pat)
            if any(r.surface.lower() == surface_n.lower() for r in refs):
                continue
            refs.append(
                CitedReferenceRecord(
                    surface=surface_n[:512],
                    resolution=ReferenceResolutionStatus.STATED,
                    citation_key=None,
                    source_span_id=src.source_span_id,
                    reference_family="patent_or_publication",
                    surface_digest=_text_digest(surface_n),
                )
            )

        # Explicit citation_keys from parser (never fabricate keys).
        for key in src.citation_keys:
            if any(r.citation_key == key for r in refs):
                continue
            # Only attach if key appears in surface or labels — fail closed.
            if key not in src.surface_text and key not in dict(src.labels).values():
                # Still record as stated when the OA candidate carried the key
                # (parser already bound it to this rejection surface).
                pass
            refs.append(
                CitedReferenceRecord(
                    surface=key,
                    resolution=ReferenceResolutionStatus.STATED,
                    citation_key=key,
                    source_span_id=src.source_span_id,
                    reference_family="citation_key",
                    surface_digest=_text_digest(key),
                )
            )

        if refs:
            ref_resolution = ReferenceResolutionStatus.STATED
        else:
            ref_resolution = ReferenceResolutionStatus.UNSTATED
            entry_reasons.append(
                RejectionMappingReasonCode.REFERENCE_UNSTATED.value
            )

        # --- lifecycle + later disposition ---
        lifecycle = (
            src.lifecycle_status
            if isinstance(src.lifecycle_status, MappingLifecycleStatus)
            else MappingLifecycleStatus(str(src.lifecycle_status))
        )
        history.insert(
            0,
            DispositionHistoryEntry(
                status=lifecycle,
                as_of=src.mailing_date,
                action_id=src.action_id,
                note="source_lifecycle",
                source_event_id=None,
            ),
        )

        later_kind = LaterDispositionKind.NONE
        related_events: list[LaterDispositionEvent] = []
        if src.action_id and src.action_id in later_by_action:
            related_events.extend(later_by_action[src.action_id])
        related_events.extend(later_global)
        for ev in related_events:
            if ev.related_mapping_ids and mapping_id not in ev.related_mapping_ids:
                # Event targets specific mappings; skip if not this one.
                # At map time mapping_id is new — allow action-scoped events.
                if ev.related_mapping_ids and src.source_id not in ev.related_mapping_ids:
                    if not ev.action_id:
                        continue
            history.append(
                DispositionHistoryEntry(
                    status=_later_to_lifecycle(ev.kind),
                    as_of=ev.as_of,
                    action_id=ev.action_id or src.action_id,
                    note=ev.notes[0] if ev.notes else f"later:{ev.kind.value}",
                    source_event_id=ev.event_id,
                )
            )
            if later_kind is LaterDispositionKind.NONE:
                later_kind = ev.kind

        # Cap history.
        if len(history) > DEFAULT_MAX_HISTORY:
            history = history[:DEFAULT_MAX_HISTORY]

        # Review state for this entry.
        review = ReviewState.NOT_REQUIRED
        if claim_resolution in (
            ClaimResolutionStatus.MISSING_CLAIM_SET,
            ClaimResolutionStatus.UNRESOLVED,
            ClaimResolutionStatus.OPEN_ENDED,
            ClaimResolutionStatus.AMBIGUOUS,
            ClaimResolutionStatus.CLAIM_NOT_IN_SET,
            ClaimResolutionStatus.PARTIAL,
            ClaimResolutionStatus.UNKNOWN,
        ):
            review = ReviewState.REQUIRED
        elif basis.family is StatutoryBasisFamily.UNKNOWN:
            review = ReviewState.REQUIRED
        elif lifecycle in (
            MappingLifecycleStatus.RESCINDED,
            MappingLifecycleStatus.SUPERSEDED,
            MappingLifecycleStatus.UNKNOWN,
        ):
            review = ReviewState.PENDING

        surface = src.surface_text
        return RejectionMapEntry(
            schema_version=REJECTION_MAPPING_SCHEMA_VERSION,
            mapping_id=mapping_id,
            source_id=src.source_id,
            action_id=src.action_id,
            artifact_id=src.artifact_id,
            source_span_id=src.source_span_id,
            examiner_statement_digest=_text_digest(surface),
            examiner_statement_surface=surface[:8000],
            statutory_basis=basis,
            claim_links=tuple(claim_links),
            claim_resolution=claim_resolution,
            claim_ambiguity=ambiguity,
            stated_claim_tokens=tuple(tokens),
            limitation_surfaces=limitations,
            cited_references=tuple(refs),
            reference_resolution=ref_resolution,
            alternatives=src.alternatives,
            exceptions=src.exceptions,
            lifecycle_status=lifecycle,
            later_disposition=later_kind,
            disposition_history=tuple(history),
            claim_set_version_ids=tuple(dict.fromkeys(version_ids)),
            review_state=review,
            confidence=src.confidence,
            reason_codes=tuple(dict.fromkeys(entry_reasons)),
            labels=dict(src.labels),
        )

    def _finalize_disposition(
        self,
        *,
        classification: DisclosureClassification,
        needs_review: bool,
        partial: bool,
        has_claim_set: bool,
        any_mapped: bool,
    ) -> tuple[MappingDisposition, ReviewState]:
        if requires_quarantine(classification):
            return MappingDisposition.QUARANTINE, ReviewState.REQUIRED
        if not has_claim_set:
            return MappingDisposition.REVIEW, ReviewState.REQUIRED
        if not any_mapped:
            return MappingDisposition.UNKNOWN, ReviewState.PENDING
        if needs_review and partial:
            return MappingDisposition.PARTIAL, ReviewState.REQUIRED
        if needs_review:
            return MappingDisposition.REVIEW, ReviewState.REQUIRED
        if partial:
            return MappingDisposition.PARTIAL, ReviewState.PENDING
        return MappingDisposition.MAPPED, ReviewState.NOT_REQUIRED


def _later_to_lifecycle(kind: LaterDispositionKind) -> MappingLifecycleStatus:
    return {
        LaterDispositionKind.NONE: MappingLifecycleStatus.ACTIVE,
        LaterDispositionKind.WITHDRAWN: MappingLifecycleStatus.WITHDRAWN,
        LaterDispositionKind.MAINTAINED: MappingLifecycleStatus.ACTIVE,
        LaterDispositionKind.SUPERSEDED: MappingLifecycleStatus.SUPERSEDED,
        LaterDispositionKind.RESCINDED: MappingLifecycleStatus.RESCINDED,
        LaterDispositionKind.ALLOWED: MappingLifecycleStatus.WITHDRAWN,
        LaterDispositionKind.AMENDED: MappingLifecycleStatus.AMENDED_CLAIM_HISTORY,
        LaterDispositionKind.UNKNOWN: MappingLifecycleStatus.UNKNOWN,
    }.get(kind, MappingLifecycleStatus.UNKNOWN)


def map_rejections(
    value: RejectionMappingInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> RejectionMappingResult:
    """Module-level convenience wrapper around :class:`RejectionMappingProcessor`."""
    return RejectionMappingProcessor().map(value, **kwargs)


def sources_from_office_action(
    oa: OfficeActionResult,
) -> tuple[RejectionSourceInput, ...]:
    """Extract rejection sources from an office-action result (public helper)."""
    return tuple(RejectionMappingProcessor()._sources_from_office_action(oa))


__all__ = [
    "NOT_PATENTABILITY_DISCLAIMER",
    "OUTPUT_KIND_EXAMINER_STATEMENT_MAP",
    "REJECTION_MAPPING_INTERFACE",
    "REJECTION_MAPPING_RULESET_VERSION",
    "REJECTION_MAPPING_SCHEMA_VERSION",
    "ClaimLinkRecord",
    "ClaimResolutionStatus",
    "ClaimSetSnapshot",
    "CitedReferenceRecord",
    "DispositionHistoryEntry",
    "LaterDispositionEvent",
    "LaterDispositionKind",
    "MappingDisposition",
    "MappingLifecycleStatus",
    "ReferenceResolutionStatus",
    "RejectionMapEntry",
    "RejectionMappingError",
    "RejectionMappingInput",
    "RejectionMappingProcessor",
    "RejectionMappingReasonCode",
    "RejectionMappingResult",
    "RejectionSourceInput",
    "StatutoryBasisFamily",
    "StatutoryBasisRecord",
    "extract_limitation_surfaces",
    "map_rejections",
    "parse_statutory_basis_surface",
    "sha256_hex",
    "sources_from_office_action",
]
