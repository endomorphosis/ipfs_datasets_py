"""Prior-art coverage declarations for adapters, queries, and named gaps (PATLAW-150).

Emits searched / unsearched / failed coverage records that bind every adapter
run to its query, timestamp, corpus cutoff, rights status, and result count.
Inaccessible or unlicensed sources remain **named** gaps. Citation and family
expansion is delegated to cycle-safe adapters. NPL content cannot enter a
public release without separate rights approval.

Design invariants
-----------------
* Every adapter coverage row records: adapter identity, query id/text,
  search timestamp, corpus cutoff, rights status, result count, and outcome.
* Inaccessible and unlicensed sources are named gaps (never silently omitted).
* Foreign-patent and NPL gaps remain visible unless a named supporting adapter
  actually ran with a search-claiming outcome.
* NPL public-release gating is fail-closed via
  :func:`assert_coverage_npl_release_safe`.
* Serialization is deterministic (canonical JSON / content digests).
* Never asserts novelty, obviousness, or patentability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .prior_art import (
    PRIOR_ART_DISCLAIMER,
    CoverageGap,
    CoverageGapKind,
    PriorArtError,
    SearchCorpus,
    default_coverage_gaps,
    default_foreign_patent_gap,
    default_npl_gap,
)
from .prior_art_adapters import (
    PRIOR_ART_ADAPTERS_SCHEMA_VERSION,
    NplRecord,
    PriorArtAdapterRegistry,
    RightsStatus,
    assert_npl_records_safe_for_public_release,
    rights_blocks_public_release,
)
from .prior_art_runtime import (
    PriorArtSearchRuntime,
    PublicSearchPlan,
    PublicSearchQuery,
)
from .search_journal import (
    AdapterKind,
    NamedAdapterIdentity,
    QueryOutcomeKind,
    QueryRecord,
    SearchDatabase,
    SearchJournal,
    build_search_journal,
    database_to_corpus,
    is_restricted_corpus,
    outcome_claims_search,
    outcome_is_failure,
)

# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------

PRIOR_ART_COVERAGE_SCHEMA_VERSION: Final = "patent.prior_art_coverage.v1"
PRIOR_ART_COVERAGE_INTERFACE: Final = "PriorArtCoverage@1"
PRIOR_ART_COVERAGE_CODE_VERSION: Final = "1.0.0"

OUTPUT_KIND_COVERAGE_DECLARATION: Final = "prior_art_coverage_declaration"
OUTPUT_KIND_ADAPTER_COVERAGE_RECORD: Final = "prior_art_adapter_coverage_record"
OUTPUT_KIND_NAMED_COVERAGE_GAP: Final = "prior_art_named_coverage_gap"

COVERAGE_DISCLAIMER: Final = (
    "This artifact is a reproducible prior-art coverage declaration for human "
    "review. It records every named adapter run with query, timestamp, corpus "
    "cutoff, rights status, and result count. Inaccessible or unlicensed "
    "sources remain named gaps. Foreign-patent and NPL corpora are never "
    "treated as fully covered unless a named adapter that supports those "
    "corpora actually ran. NPL content cannot enter a public release without "
    "separate rights approval. This is not a novelty, obviousness, or "
    "patentability determination, not legal advice, not an IDS filing, and "
    "not a substitute for a licensed search."
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

DEFAULT_MAX_RECORDS: Final = 512
DEFAULT_MAX_GAPS: Final = 128

# Well-known source names used when a restricted corpus was never attempted.
GAP_SOURCE_FOREIGN_PATENTS: Final = "source:foreign_patents"
GAP_SOURCE_NPL: Final = "source:npl"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PriorArtCoverageError(PriorArtError):
    """Base error for coverage declaration failures."""

    code: str = "prior_art_coverage_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class CoverageSchemaError(PriorArtCoverageError):
    code = "coverage_schema_invalid"


class CoverageRecordError(PriorArtCoverageError):
    code = "coverage_record_invalid"


class NamedGapError(PriorArtCoverageError):
    code = "named_gap_invalid"


class NplPublicReleaseError(PriorArtCoverageError):
    """Raised when NPL content would enter a public release without rights approval."""

    code = "npl_public_release_blocked"


class CoverageCompletenessError(PriorArtCoverageError):
    """Raised when coverage claims search without matching records."""

    code = "coverage_completeness"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CoverageRecordStatus(str, Enum):
    """Disposition of one adapter/query coverage row."""

    SEARCHED = "searched"
    UNSEARCHED = "unsearched"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    INACCESSIBLE = "inaccessible"
    UNLICENSED = "unlicensed"


class NamedGapReason(str, Enum):
    """Why a named source remains a coverage gap."""

    NOT_CONFIGURED = "not_configured"
    NOT_RUN = "not_run"
    INACCESSIBLE = "inaccessible"
    UNLICENSED = "unlicensed"
    ADAPTER_FAILURE = "adapter_failure"
    RIGHTS_REQUIRES_APPROVAL = "rights_requires_approval"
    PARTIAL_COVERAGE = "partial_coverage"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    import json

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid(value: Any, *, prefix: str = "bafybeigcoverage") -> str:
    return f"{prefix}{content_digest(value)[:48]}"


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
        raise TypeError(f"{field} must be str or None")
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


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _iso_date_or_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not (_ISO_DATE_RE.match(text) or _ISO_UTC_RE.match(text)):
        raise ValueError(f"{field} must be YYYY-MM-DD or ISO-8601 UTC, got {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _assert_no_forbidden_keys(metadata: Mapping[str, str], label: str) -> None:
    forbidden = {
        "anticipates",
        "is_novel",
        "is_obvious",
        "novelty",
        "novelty_conclusion",
        "obviousness",
        "obviousness_conclusion",
        "patentability",
        "patentability_conclusion",
        "patentable",
        "renders_obvious",
        "unpatentable",
    }
    hits = sorted(set(metadata) & forbidden)
    if hits:
        raise CoverageSchemaError(
            f"{label} metadata must not assert patentability keys: {', '.join(hits)}"
        )


# ---------------------------------------------------------------------------
# Adapter coverage record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterCoverageRecord:
    """One adapter/query coverage row with identity fields required by acceptance.

    Records: adapter, query, timestamp, cutoff, rights status, result count.
    """

    record_id: str
    adapter_name: str
    adapter_kind: AdapterKind
    query_id: str
    query_text: str
    search_time_utc: str
    corpus_cutoff: str
    rights_status: RightsStatus
    result_count: int
    status: CoverageRecordStatus
    database: SearchDatabase
    outcome: QueryOutcomeKind
    corpus: SearchCorpus | None = None
    claims_corpus_searched: bool = False
    error_code: str | None = None
    error_message: str | None = None
    source_snapshot_cid: str | None = None
    adapter_version: str = "1.0.0"
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _identifier(self.record_id, "record_id"))
        object.__setattr__(
            self, "adapter_name", _identifier(self.adapter_name, "adapter_name")
        )
        object.__setattr__(
            self,
            "adapter_kind",
            _coerce_enum(AdapterKind, self.adapter_kind, "adapter_kind"),
        )
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self,
            "query_text",
            _require_str(self.query_text, "query_text", max_len=8192),
        )
        object.__setattr__(
            self, "search_time_utc", _iso_utc(self.search_time_utc, "search_time_utc")
        )
        object.__setattr__(
            self, "corpus_cutoff", _iso_date_or_utc(self.corpus_cutoff, "corpus_cutoff")
        )
        object.__setattr__(
            self,
            "rights_status",
            _coerce_enum(RightsStatus, self.rights_status, "rights_status"),
        )
        object.__setattr__(
            self, "result_count", _nonneg_int(self.result_count, "result_count")
        )
        object.__setattr__(
            self, "status", _coerce_enum(CoverageRecordStatus, self.status, "status")
        )
        object.__setattr__(
            self, "database", _coerce_enum(SearchDatabase, self.database, "database")
        )
        object.__setattr__(
            self, "outcome", _coerce_enum(QueryOutcomeKind, self.outcome, "outcome")
        )
        if self.corpus is not None:
            object.__setattr__(
                self, "corpus", _coerce_enum(SearchCorpus, self.corpus, "corpus")
            )
        else:
            object.__setattr__(self, "corpus", database_to_corpus(self.database))
        if not isinstance(self.claims_corpus_searched, bool):
            raise TypeError("claims_corpus_searched must be bool")
        object.__setattr__(
            self, "error_code", _optional_str(self.error_code, "error_code", max_len=128)
        )
        object.__setattr__(
            self,
            "error_message",
            _optional_str(self.error_message, "error_message", max_len=2048),
        )
        object.__setattr__(
            self,
            "source_snapshot_cid",
            _optional_str(self.source_snapshot_cid, "source_snapshot_cid", max_len=256),
        )
        object.__setattr__(
            self,
            "adapter_version",
            _require_str(self.adapter_version, "adapter_version", max_len=32),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=64)
        )
        _assert_no_forbidden_keys(self.metadata, "AdapterCoverageRecord")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_kind": self.adapter_kind.value,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "claims_corpus_searched": self.claims_corpus_searched,
            "corpus": None if self.corpus is None else self.corpus.value,
            "corpus_cutoff": self.corpus_cutoff,
            "database": self.database.value,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
            "outcome": self.outcome.value,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "record_id": self.record_id,
            "result_count": self.result_count,
            "rights_status": self.rights_status.value,
            "search_time_utc": self.search_time_utc,
            "source_snapshot_cid": self.source_snapshot_cid,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdapterCoverageRecord":
        value = _mapping(value, "AdapterCoverageRecord")
        return cls(
            record_id=value.get("record_id", ""),
            adapter_name=value.get("adapter_name", ""),
            adapter_kind=value.get("adapter_kind", AdapterKind.OTHER.value),
            query_id=value.get("query_id", ""),
            query_text=value.get("query_text", ""),
            search_time_utc=value.get("search_time_utc", ""),
            corpus_cutoff=value.get("corpus_cutoff", ""),
            rights_status=value.get("rights_status", RightsStatus.UNKNOWN.value),
            result_count=int(value.get("result_count") or 0),
            status=value.get("status", CoverageRecordStatus.UNSEARCHED.value),
            database=value.get("database", SearchDatabase.US_PATENTS.value),
            outcome=value.get("outcome", QueryOutcomeKind.SKIPPED.value),
            corpus=value.get("corpus"),
            claims_corpus_searched=bool(value.get("claims_corpus_searched", False)),
            error_code=value.get("error_code"),
            error_message=value.get("error_message"),
            source_snapshot_cid=value.get("source_snapshot_cid"),
            adapter_version=value.get("adapter_version") or "1.0.0",
            metadata=value.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Named coverage gap
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NamedCoverageGap:
    """A named inaccessible, unlicensed, or unsearched source gap (always visible)."""

    gap_id: str
    source_name: str
    reason: NamedGapReason
    description: str
    corpus: SearchCorpus | None = None
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    remains_visible: bool = True
    adapter_name: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "source_name", _require_str(self.source_name, "source_name", max_len=256)
        )
        object.__setattr__(
            self, "reason", _coerce_enum(NamedGapReason, self.reason, "reason")
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=2048),
        )
        if self.corpus is not None:
            object.__setattr__(
                self, "corpus", _coerce_enum(SearchCorpus, self.corpus, "corpus")
            )
        object.__setattr__(
            self,
            "rights_status",
            _coerce_enum(RightsStatus, self.rights_status, "rights_status"),
        )
        if self.remains_visible is not True:
            raise NamedGapError(
                f"named gap {self.gap_id!r} must remain_visible=True",
                code="gap_not_visible",
            )
        object.__setattr__(
            self,
            "adapter_name",
            _optional_str(self.adapter_name, "adapter_name", max_len=256),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=32)
        )
        _assert_no_forbidden_keys(self.metadata, "NamedCoverageGap")

    def to_coverage_gap(self) -> CoverageGap:
        """Project into the PATLAW-094 :class:`CoverageGap` surface."""
        kind = CoverageGapKind.OTHER
        if self.corpus is SearchCorpus.FOREIGN_PATENTS:
            kind = CoverageGapKind.FOREIGN_PATENT
        elif self.corpus is SearchCorpus.NPL:
            kind = CoverageGapKind.NPL
        elif self.reason is NamedGapReason.PARTIAL_COVERAGE:
            kind = CoverageGapKind.PARTIAL_COVERAGE
        elif self.reason in (
            NamedGapReason.NOT_CONFIGURED,
            NamedGapReason.NOT_RUN,
        ):
            kind = CoverageGapKind.UNSEARCHED_CORPUS
        return CoverageGap(
            gap_id=self.gap_id,
            kind=kind,
            description=self.description,
            corpus=self.corpus,
            remains_visible=True,
            searched=False,
            metadata={
                "source_name": self.source_name,
                "reason": self.reason.value,
                "rights_status": self.rights_status.value,
                **(
                    {"adapter_name": self.adapter_name}
                    if self.adapter_name
                    else {}
                ),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_name": self.adapter_name,
            "corpus": None if self.corpus is None else self.corpus.value,
            "description": self.description,
            "gap_id": self.gap_id,
            "metadata": dict(self.metadata),
            "reason": self.reason.value,
            "remains_visible": True,
            "rights_status": self.rights_status.value,
            "source_name": self.source_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NamedCoverageGap":
        value = _mapping(value, "NamedCoverageGap")
        return cls(
            gap_id=value.get("gap_id", ""),
            source_name=value.get("source_name", ""),
            reason=value.get("reason", NamedGapReason.OTHER.value),
            description=value.get("description", ""),
            corpus=value.get("corpus"),
            rights_status=value.get("rights_status", RightsStatus.UNKNOWN.value),
            remains_visible=bool(value.get("remains_visible", True)),
            adapter_name=value.get("adapter_name"),
            metadata=value.get("metadata") or {},
        )


def named_gap_foreign_patents(
    *,
    reason: NamedGapReason = NamedGapReason.NOT_RUN,
    adapter_name: str | None = None,
    rights_status: RightsStatus = RightsStatus.UNKNOWN,
    description: str | None = None,
) -> NamedCoverageGap:
    desc = description or (
        "Foreign-patent corpus was not searched (or the named adapter failed / "
        "was inaccessible / unlicensed). This named gap remains visible."
    )
    return NamedCoverageGap(
        gap_id="gap:named:foreign-patent",
        source_name=GAP_SOURCE_FOREIGN_PATENTS,
        reason=reason,
        description=desc,
        corpus=SearchCorpus.FOREIGN_PATENTS,
        rights_status=rights_status,
        adapter_name=adapter_name,
    )


def named_gap_npl(
    *,
    reason: NamedGapReason = NamedGapReason.NOT_RUN,
    adapter_name: str | None = None,
    rights_status: RightsStatus = RightsStatus.UNLICENSED,
    description: str | None = None,
) -> NamedCoverageGap:
    desc = description or (
        "Non-patent literature (NPL) corpus was not searched (or the named "
        "adapter failed / was inaccessible / unlicensed). Unlicensed NPL body "
        "text is not reproduced. This named gap remains visible."
    )
    return NamedCoverageGap(
        gap_id="gap:named:npl",
        source_name=GAP_SOURCE_NPL,
        reason=reason,
        description=desc,
        corpus=SearchCorpus.NPL,
        rights_status=rights_status,
        adapter_name=adapter_name,
    )


# ---------------------------------------------------------------------------
# Coverage declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PriorArtCoverageDeclaration:
    """Complete coverage declaration for a prior-art search subject.

    Acceptance: records every adapter, query, timestamp, cutoff, rights status
    and result count; inaccessible/unlicensed sources remain named gaps.
    """

    schema_version: str
    declaration_id: str
    subject_id: str
    search_time_utc: str
    corpus_cutoff: str
    records: tuple[AdapterCoverageRecord, ...]
    named_gaps: tuple[NamedCoverageGap, ...]
    searched_corpora: tuple[SearchCorpus, ...] = ()
    unsearched_corpora: tuple[SearchCorpus, ...] = ()
    failed_corpora: tuple[SearchCorpus, ...] = ()
    adapters_run: tuple[str, ...] = ()
    journal_id: str | None = None
    plan_id: str | None = None
    disclaimer: str = COVERAGE_DISCLAIMER
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        schema = _require_str(self.schema_version, "schema_version", max_len=64)
        if schema != PRIOR_ART_COVERAGE_SCHEMA_VERSION:
            raise CoverageSchemaError(
                f"schema_version must be {PRIOR_ART_COVERAGE_SCHEMA_VERSION}, "
                f"got {schema!r}"
            )
        object.__setattr__(self, "schema_version", schema)
        object.__setattr__(
            self, "declaration_id", _identifier(self.declaration_id, "declaration_id")
        )
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "search_time_utc", _iso_utc(self.search_time_utc, "search_time_utc")
        )
        object.__setattr__(
            self, "corpus_cutoff", _iso_date_or_utc(self.corpus_cutoff, "corpus_cutoff")
        )

        parsed_records = _coerce_records(self.records, "records")
        if len(parsed_records) > DEFAULT_MAX_RECORDS:
            raise CoverageRecordError(
                f"records exceeds max items {DEFAULT_MAX_RECORDS}"
            )
        object.__setattr__(self, "records", parsed_records)

        # Every record must carry the acceptance-required identity fields.
        for rec in parsed_records:
            _assert_record_identity(rec)

        parsed_gaps = _coerce_gaps(self.named_gaps, "named_gaps")
        if len(parsed_gaps) > DEFAULT_MAX_GAPS:
            raise NamedGapError(f"named_gaps exceeds max items {DEFAULT_MAX_GAPS}")
        object.__setattr__(self, "named_gaps", parsed_gaps)

        searched = _coerce_corpora(self.searched_corpora, "searched_corpora")
        unsearched = _coerce_corpora(self.unsearched_corpora, "unsearched_corpora")
        failed = _coerce_corpora(self.failed_corpora, "failed_corpora")

        # Derive from records when empty.
        if not searched and not unsearched and not failed:
            searched, unsearched, failed = _derive_corpus_sets(parsed_records)

        # Restricted corpora not searched must appear as named gaps.
        _ensure_restricted_named_gaps(
            searched=searched,
            unsearched=unsearched,
            failed=failed,
            gaps=parsed_gaps,
            records=parsed_records,
        )
        # Re-read gaps after potential validation (immutable — just check)
        _assert_named_gaps_for_restricted(
            searched=searched,
            gaps=parsed_gaps,
        )

        object.__setattr__(self, "searched_corpora", searched)
        object.__setattr__(self, "unsearched_corpora", unsearched)
        object.__setattr__(self, "failed_corpora", failed)

        adapters = tuple(
            _identifier(a, "adapters_run") for a in (self.adapters_run or ())
        )
        if not adapters:
            seen: list[str] = []
            for rec in parsed_records:
                if rec.adapter_name not in seen and rec.adapter_name != "adapter:none":
                    seen.append(rec.adapter_name)
            adapters = tuple(seen)
        object.__setattr__(self, "adapters_run", adapters)

        object.__setattr__(
            self, "journal_id", _optional_str(self.journal_id, "journal_id", max_len=256)
        )
        object.__setattr__(
            self, "plan_id", _optional_str(self.plan_id, "plan_id", max_len=256)
        )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=64)
        )
        _assert_no_forbidden_keys(self.metadata, "PriorArtCoverageDeclaration")

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @property
    def content_cid(self) -> str:
        return content_cid(self.to_dict())

    def record_for_query(self, query_id: str) -> AdapterCoverageRecord | None:
        for rec in self.records:
            if rec.query_id == query_id:
                return rec
        return None

    def gaps_for_corpus(self, corpus: SearchCorpus | str) -> tuple[NamedCoverageGap, ...]:
        c = _coerce_enum(SearchCorpus, corpus, "corpus")
        return tuple(g for g in self.named_gaps if g.corpus is c)

    def to_prior_art_coverage_gaps(self) -> tuple[CoverageGap, ...]:
        """Project named gaps into PATLAW-094 coverage gap pair (+ extras)."""
        projected = [g.to_coverage_gap() for g in self.named_gaps]
        # Ensure foreign + NPL always present for plan/report consumers.
        kinds = {g.kind for g in projected}
        if CoverageGapKind.FOREIGN_PATENT not in kinds:
            projected.insert(
                0,
                default_foreign_patent_gap(
                    searched=SearchCorpus.FOREIGN_PATENTS in self.searched_corpora
                ),
            )
        if CoverageGapKind.NPL not in kinds:
            projected.append(
                default_npl_gap(searched=SearchCorpus.NPL in self.searched_corpora)
            )
        return tuple(projected)

    def npl_records_for_release_check(self) -> tuple[NplRecord, ...]:
        """Build synthetic NPL records from coverage rows for release gating."""
        out: list[NplRecord] = []
        for rec in self.records:
            if rec.corpus is not SearchCorpus.NPL and rec.database is not SearchDatabase.NPL:
                continue
            # Represent each hit count as a placeholder record with the row's rights.
            # Body text is never present here (coverage surface only).
            out.append(
                NplRecord(
                    document_id=f"npl-coverage:{rec.query_id}",
                    title=None,
                    identifier=None,
                    rights_status=rec.rights_status,
                    body_text=None,
                    rights_approval_id=rec.metadata.get("rights_approval_id"),
                    metadata={
                        "adapter_name": rec.adapter_name,
                        "query_id": rec.query_id,
                        "result_count": str(rec.result_count),
                    },
                )
            )
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters_run": list(self.adapters_run),
            "corpus_cutoff": self.corpus_cutoff,
            "declaration_id": self.declaration_id,
            "disclaimer": self.disclaimer,
            "failed_corpora": [c.value for c in self.failed_corpora],
            "journal_id": self.journal_id,
            "metadata": dict(self.metadata),
            "named_gaps": [g.to_dict() for g in self.named_gaps],
            "plan_id": self.plan_id,
            "records": [r.to_dict() for r in self.records],
            "schema_version": self.schema_version,
            "search_time_utc": self.search_time_utc,
            "searched_corpora": [c.value for c in self.searched_corpora],
            "subject_id": self.subject_id,
            "unsearched_corpora": [c.value for c in self.unsearched_corpora],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PriorArtCoverageDeclaration":
        value = _mapping(value, "PriorArtCoverageDeclaration")
        return cls(
            schema_version=value.get(
                "schema_version", PRIOR_ART_COVERAGE_SCHEMA_VERSION
            ),
            declaration_id=value.get("declaration_id", ""),
            subject_id=value.get("subject_id", ""),
            search_time_utc=value.get("search_time_utc", ""),
            corpus_cutoff=value.get("corpus_cutoff", ""),
            records=tuple(value.get("records") or ()),
            named_gaps=tuple(value.get("named_gaps") or ()),
            searched_corpora=tuple(value.get("searched_corpora") or ()),
            unsearched_corpora=tuple(value.get("unsearched_corpora") or ()),
            failed_corpora=tuple(value.get("failed_corpora") or ()),
            adapters_run=tuple(value.get("adapters_run") or ()),
            journal_id=value.get("journal_id"),
            plan_id=value.get("plan_id"),
            disclaimer=value.get("disclaimer") or COVERAGE_DISCLAIMER,
            metadata=value.get("metadata") or {},
        )


def _coerce_records(
    value: Any, field: str
) -> tuple[AdapterCoverageRecord, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[AdapterCoverageRecord] = []
    for i, item in enumerate(value):
        if isinstance(item, AdapterCoverageRecord):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(AdapterCoverageRecord.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be AdapterCoverageRecord or mapping")
    return tuple(out)


def _coerce_gaps(value: Any, field: str) -> tuple[NamedCoverageGap, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[NamedCoverageGap] = []
    for i, item in enumerate(value):
        if isinstance(item, NamedCoverageGap):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(NamedCoverageGap.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be NamedCoverageGap or mapping")
    return tuple(out)


def _coerce_corpora(
    value: Any, field: str
) -> tuple[SearchCorpus, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[SearchCorpus] = []
    for i, item in enumerate(value):
        c = _coerce_enum(SearchCorpus, item, f"{field}[{i}]")
        assert isinstance(c, SearchCorpus)
        out.append(c)
    return tuple(sorted(set(out), key=lambda x: x.value))


def _assert_record_identity(rec: AdapterCoverageRecord) -> None:
    """Acceptance: adapter, query, timestamp, cutoff, rights, result count."""
    missing: list[str] = []
    if not rec.adapter_name:
        missing.append("adapter_name")
    if not rec.query_id:
        missing.append("query_id")
    if not rec.search_time_utc:
        missing.append("search_time_utc")
    if not rec.corpus_cutoff:
        missing.append("corpus_cutoff")
    if rec.rights_status is None:
        missing.append("rights_status")
    if rec.result_count is None:
        missing.append("result_count")
    if missing:
        raise CoverageRecordError(
            f"record {rec.record_id} missing required fields: {', '.join(missing)}"
        )


def _derive_corpus_sets(
    records: Sequence[AdapterCoverageRecord],
) -> tuple[tuple[SearchCorpus, ...], tuple[SearchCorpus, ...], tuple[SearchCorpus, ...]]:
    searched: set[SearchCorpus] = set()
    failed: set[SearchCorpus] = set()
    attempted: set[SearchCorpus] = set()

    for rec in records:
        corpus = rec.corpus
        if corpus is None:
            continue
        attempted.add(corpus)
        if (
            rec.claims_corpus_searched
            and outcome_claims_search(rec.outcome)
            and rec.status is CoverageRecordStatus.SEARCHED
        ):
            searched.add(corpus)
        elif rec.status in (
            CoverageRecordStatus.FAILED,
            CoverageRecordStatus.INACCESSIBLE,
            CoverageRecordStatus.UNLICENSED,
        ) or outcome_is_failure(rec.outcome):
            if corpus not in searched:
                failed.add(corpus)

    unsearched: set[SearchCorpus] = set()
    for restricted in (SearchCorpus.FOREIGN_PATENTS, SearchCorpus.NPL):
        if restricted not in searched:
            unsearched.add(restricted)

    # Failed restricted corpora stay in failed and unsearched (not searched).
    failed -= searched
    return (
        tuple(sorted(searched, key=lambda x: x.value)),
        tuple(sorted(unsearched, key=lambda x: x.value)),
        tuple(sorted(failed, key=lambda x: x.value)),
    )


def _assert_named_gaps_for_restricted(
    *,
    searched: Sequence[SearchCorpus],
    gaps: Sequence[NamedCoverageGap],
) -> None:
    searched_set = set(searched)
    gap_corpora = {g.corpus for g in gaps if g.corpus is not None and g.remains_visible}
    missing: list[str] = []
    if SearchCorpus.FOREIGN_PATENTS not in searched_set:
        if SearchCorpus.FOREIGN_PATENTS not in gap_corpora:
            missing.append("foreign_patents")
    if SearchCorpus.NPL not in searched_set:
        if SearchCorpus.NPL not in gap_corpora:
            missing.append("npl")
    if missing:
        raise CoverageCompletenessError(
            "inaccessible or unsearched restricted corpora must remain named gaps; "
            f"missing named gaps for: {', '.join(missing)}",
            code="missing_named_gaps",
        )
    # All named gaps must remain visible
    for g in gaps:
        if not g.remains_visible:
            raise NamedGapError(f"gap {g.gap_id} must remain visible")


def _ensure_restricted_named_gaps(
    *,
    searched: Sequence[SearchCorpus],
    unsearched: Sequence[SearchCorpus],
    failed: Sequence[SearchCorpus],
    gaps: Sequence[NamedCoverageGap],
    records: Sequence[AdapterCoverageRecord],
) -> None:
    """Validate gap quality; construction helpers inject gaps before build."""
    del unsearched, failed, records, searched, gaps  # validated in _assert


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def coverage_status_from_query_record(rec: QueryRecord) -> CoverageRecordStatus:
    """Map a journal query record to a coverage disposition."""
    if rec.outcome is QueryOutcomeKind.SKIPPED:
        return CoverageRecordStatus.SKIPPED
    if rec.outcome is QueryOutcomeKind.ADAPTER_NOT_REGISTERED:
        return CoverageRecordStatus.UNSEARCHED
    err = (rec.error_code or "").lower()
    if err in {"source_inaccessible", "inaccessible"} or rec.outcome is QueryOutcomeKind.FORBIDDEN:
        return CoverageRecordStatus.INACCESSIBLE
    if err in {"source_unlicensed", "unlicensed"}:
        return CoverageRecordStatus.UNLICENSED
    if outcome_is_failure(rec.outcome):
        return CoverageRecordStatus.FAILED
    if outcome_claims_search(rec.outcome) and rec.claims_corpus_searched:
        return CoverageRecordStatus.SEARCHED
    if outcome_claims_search(rec.outcome) and not rec.claims_corpus_searched:
        return CoverageRecordStatus.PARTIAL
    return CoverageRecordStatus.UNSEARCHED


def rights_status_from_query_record(rec: QueryRecord) -> RightsStatus:
    """Extract rights status from record metadata or adapter kind defaults."""
    meta = dict(rec.metadata or {})
    raw = meta.get("rights_status")
    if raw:
        try:
            return _coerce_enum(RightsStatus, raw, "rights_status")  # type: ignore[return-value]
        except (TypeError, ValueError):
            pass
    if rec.adapter.adapter_kind is AdapterKind.NPL:
        return RightsStatus.UNLICENSED
    if rec.error_code in {"source_inaccessible"}:
        return RightsStatus.INACCESSIBLE
    if rec.error_code in {"source_unlicensed"}:
        return RightsStatus.UNLICENSED
    if rec.adapter.adapter_kind is AdapterKind.FOREIGN_PATENT:
        return RightsStatus.PUBLIC
    return RightsStatus.PUBLIC


def adapter_coverage_record_from_query_record(
    rec: QueryRecord,
    *,
    record_id: str | None = None,
) -> AdapterCoverageRecord:
    """Project a journal :class:`QueryRecord` into an adapter coverage row."""
    rid = record_id or f"cov:{rec.record_id}"
    return AdapterCoverageRecord(
        record_id=rid,
        adapter_name=rec.adapter.adapter_name,
        adapter_kind=rec.adapter.adapter_kind,
        adapter_version=rec.adapter.adapter_version,
        query_id=rec.query_id,
        query_text=rec.query_text,
        search_time_utc=rec.search_time_utc,
        corpus_cutoff=rec.corpus_cutoff,
        rights_status=rights_status_from_query_record(rec),
        result_count=rec.result_count,
        status=coverage_status_from_query_record(rec),
        database=rec.database,
        outcome=rec.outcome,
        corpus=rec.corpus,
        claims_corpus_searched=rec.claims_corpus_searched,
        error_code=rec.error_code,
        error_message=rec.error_message,
        source_snapshot_cid=rec.source_snapshot_cid,
        metadata={
            **dict(rec.metadata),
            "journal_record_id": rec.record_id,
        },
    )


def _named_gaps_from_records(
    records: Sequence[AdapterCoverageRecord],
    *,
    searched: Sequence[SearchCorpus],
    journal: SearchJournal | None = None,
) -> list[NamedCoverageGap]:
    """Build named gaps for restricted corpora and failed/inaccessible adapters."""
    gaps: list[NamedCoverageGap] = []
    searched_set = set(searched)

    # Per-record inaccessible / unlicensed named sources
    seen_sources: set[str] = set()
    for rec in records:
        if rec.status is CoverageRecordStatus.INACCESSIBLE:
            src = rec.adapter_name
            if src not in seen_sources:
                seen_sources.add(src)
                gaps.append(
                    NamedCoverageGap(
                        gap_id=f"gap:inaccessible:{src}",
                        source_name=src,
                        reason=NamedGapReason.INACCESSIBLE,
                        description=(
                            f"Source adapter {src!r} is inaccessible; "
                            f"coverage remains a named gap."
                        ),
                        corpus=rec.corpus,
                        rights_status=RightsStatus.INACCESSIBLE,
                        adapter_name=src,
                    )
                )
        elif rec.status is CoverageRecordStatus.UNLICENSED:
            src = rec.adapter_name
            if src not in seen_sources:
                seen_sources.add(src)
                gaps.append(
                    NamedCoverageGap(
                        gap_id=f"gap:unlicensed:{src}",
                        source_name=src,
                        reason=NamedGapReason.UNLICENSED,
                        description=(
                            f"Source adapter {src!r} is unlicensed; "
                            f"coverage remains a named gap. Content is not redistributed."
                        ),
                        corpus=rec.corpus,
                        rights_status=RightsStatus.UNLICENSED,
                        adapter_name=src,
                    )
                )
        elif rec.status is CoverageRecordStatus.FAILED and is_restricted_corpus(
            rec.corpus or SearchCorpus.US_PATENTS
        ):
            src = rec.adapter_name
            key = f"failed:{src}"
            if key not in seen_sources:
                seen_sources.add(key)
                gaps.append(
                    NamedCoverageGap(
                        gap_id=f"gap:failed:{src}",
                        source_name=src,
                        reason=NamedGapReason.ADAPTER_FAILURE,
                        description=(
                            f"Named adapter {src!r} failed "
                            f"({rec.error_code or rec.outcome.value}); "
                            f"source remains a named gap (not searched)."
                        ),
                        corpus=rec.corpus,
                        rights_status=rec.rights_status,
                        adapter_name=src,
                    )
                )

    # Default foreign / NPL corpus-level gaps when not searched
    if SearchCorpus.FOREIGN_PATENTS not in searched_set:
        reason = NamedGapReason.NOT_RUN
        adapter_name = None
        rights = RightsStatus.UNKNOWN
        for rec in records:
            if rec.corpus is SearchCorpus.FOREIGN_PATENTS:
                adapter_name = rec.adapter_name
                if rec.status is CoverageRecordStatus.INACCESSIBLE:
                    reason = NamedGapReason.INACCESSIBLE
                    rights = RightsStatus.INACCESSIBLE
                elif rec.status is CoverageRecordStatus.UNLICENSED:
                    reason = NamedGapReason.UNLICENSED
                    rights = RightsStatus.UNLICENSED
                elif rec.status is CoverageRecordStatus.FAILED:
                    reason = NamedGapReason.ADAPTER_FAILURE
                else:
                    reason = NamedGapReason.NOT_RUN
                break
        else:
            if journal is not None and SearchCorpus.FOREIGN_PATENTS in journal.unsearched_corpora:
                reason = NamedGapReason.NOT_RUN
        gaps.append(
            named_gap_foreign_patents(
                reason=reason,
                adapter_name=adapter_name,
                rights_status=rights,
            )
        )

    if SearchCorpus.NPL not in searched_set:
        reason = NamedGapReason.NOT_RUN
        adapter_name = None
        rights = RightsStatus.UNLICENSED
        for rec in records:
            if rec.corpus is SearchCorpus.NPL:
                adapter_name = rec.adapter_name
                if rec.status is CoverageRecordStatus.INACCESSIBLE:
                    reason = NamedGapReason.INACCESSIBLE
                    rights = RightsStatus.INACCESSIBLE
                elif rec.status is CoverageRecordStatus.UNLICENSED:
                    reason = NamedGapReason.UNLICENSED
                    rights = RightsStatus.UNLICENSED
                elif rec.status is CoverageRecordStatus.FAILED:
                    reason = NamedGapReason.ADAPTER_FAILURE
                    rights = rec.rights_status
                elif rec.rights_status is RightsStatus.REQUIRES_APPROVAL:
                    reason = NamedGapReason.RIGHTS_REQUIRES_APPROVAL
                    rights = RightsStatus.REQUIRES_APPROVAL
                else:
                    reason = NamedGapReason.NOT_RUN
                break
        gaps.append(
            named_gap_npl(
                reason=reason,
                adapter_name=adapter_name,
                rights_status=rights,
            )
        )

    return gaps


def build_coverage_declaration(
    *,
    subject_id: str,
    search_time_utc: str,
    corpus_cutoff: str,
    records: Sequence[AdapterCoverageRecord | Mapping[str, Any]],
    named_gaps: Sequence[NamedCoverageGap | Mapping[str, Any]] | None = None,
    declaration_id: str | None = None,
    journal_id: str | None = None,
    plan_id: str | None = None,
    adapters_run: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
) -> PriorArtCoverageDeclaration:
    """Assemble a validated coverage declaration from adapter coverage rows."""
    parsed = [
        r if isinstance(r, AdapterCoverageRecord) else AdapterCoverageRecord.from_dict(r)
        for r in records
    ]
    searched, unsearched, failed = _derive_corpus_sets(parsed)

    if named_gaps is None:
        gaps = _named_gaps_from_records(parsed, searched=searched)
    else:
        gaps = [
            g if isinstance(g, NamedCoverageGap) else NamedCoverageGap.from_dict(g)
            for g in named_gaps
        ]
        # Still ensure restricted gaps exist
        gap_corpora = {g.corpus for g in gaps}
        if SearchCorpus.FOREIGN_PATENTS not in searched and SearchCorpus.FOREIGN_PATENTS not in gap_corpora:
            gaps.append(named_gap_foreign_patents())
        if SearchCorpus.NPL not in searched and SearchCorpus.NPL not in gap_corpora:
            gaps.append(named_gap_npl())

    identity = {
        "corpus_cutoff": corpus_cutoff,
        "records": [r.to_dict() for r in parsed],
        "search_time_utc": search_time_utc,
        "subject_id": subject_id,
    }
    digest = content_digest(identity)[:16]
    did = declaration_id or f"coverage:prior-art:{digest}"

    return PriorArtCoverageDeclaration(
        schema_version=PRIOR_ART_COVERAGE_SCHEMA_VERSION,
        declaration_id=did,
        subject_id=subject_id,
        search_time_utc=search_time_utc,
        corpus_cutoff=corpus_cutoff,
        records=tuple(parsed),
        named_gaps=tuple(gaps),
        searched_corpora=searched,
        unsearched_corpora=unsearched,
        failed_corpora=failed,
        adapters_run=tuple(adapters_run),
        journal_id=journal_id,
        plan_id=plan_id,
        metadata=metadata or {},
    )


def build_coverage_from_journal(
    journal: SearchJournal | Mapping[str, Any],
    *,
    declaration_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> PriorArtCoverageDeclaration:
    """Project a :class:`SearchJournal` into a full coverage declaration."""
    if isinstance(journal, Mapping):
        journal = SearchJournal.from_dict(journal)
    records = [adapter_coverage_record_from_query_record(r) for r in journal.records]
    adapters = [a.adapter_name for a in journal.adapters_run]
    meta = {
        "journal_schema": journal.schema_version,
        "source": "search_journal",
        **dict(metadata or {}),
    }
    return build_coverage_declaration(
        subject_id=journal.subject_id,
        search_time_utc=journal.search_date_utc,
        corpus_cutoff=journal.corpus_cutoff,
        records=records,
        declaration_id=declaration_id,
        journal_id=journal.journal_id,
        plan_id=journal.plan_id,
        adapters_run=adapters,
        metadata=meta,
    )


def execute_plan_with_coverage(
    runtime: PriorArtSearchRuntime,
    plan: PublicSearchPlan | Mapping[str, Any],
    *,
    extra_registry: PriorArtAdapterRegistry | None = None,
) -> tuple[SearchJournal, PriorArtCoverageDeclaration]:
    """Execute a public search plan and emit journal + coverage declaration.

    When *extra_registry* is provided, those adapters are registered onto a
    copy of the runtime before execution (citation/family/foreign/NPL).
    """
    if isinstance(plan, Mapping):
        plan = PublicSearchPlan.from_dict(plan)
    rt = runtime
    if extra_registry is not None:
        for adapter in extra_registry.as_runtime_adapters().values():
            rt = rt.register(adapter)
    journal = rt.execute_plan(plan)
    coverage = build_coverage_from_journal(
        journal,
        metadata={
            "coverage_schema": PRIOR_ART_COVERAGE_SCHEMA_VERSION,
            "adapters_schema": PRIOR_ART_ADAPTERS_SCHEMA_VERSION,
            "runtime": PRIOR_ART_COVERAGE_INTERFACE,
        },
    )
    return journal, coverage


# ---------------------------------------------------------------------------
# NPL public release gate
# ---------------------------------------------------------------------------


def assert_coverage_npl_release_safe(
    coverage: PriorArtCoverageDeclaration | Mapping[str, Any],
    *,
    npl_records: Sequence[NplRecord | Mapping[str, Any]] = (),
    allow_empty_npl: bool = True,
) -> None:
    """Fail closed if NPL content would enter a public release without rights.

    Rules
    -----
    * Any coverage row targeting NPL with rights that block public release
      (unlicensed, unknown, requires_approval without approval id, inaccessible)
      raises :class:`NplPublicReleaseError`.
    * Explicit *npl_records* are checked via
      :func:`assert_npl_records_safe_for_public_release`.
    * Successful NPL search without a rights approval id on licensed content
      is blocked.
    """
    if isinstance(coverage, Mapping):
        coverage = PriorArtCoverageDeclaration.from_dict(coverage)

    for rec in coverage.records:
        if rec.corpus is not SearchCorpus.NPL and rec.database is not SearchDatabase.NPL:
            continue
        if not outcome_claims_search(rec.outcome) and rec.result_count == 0:
            # Failed/empty NPL attempts are gaps, not release candidates.
            continue
        approval = rec.metadata.get("rights_approval_id")
        if rec.rights_status is RightsStatus.PUBLIC:
            continue
        if rec.rights_status is RightsStatus.LICENSED and approval:
            continue
        if rights_blocks_public_release(rec.rights_status) or (
            rec.rights_status is RightsStatus.LICENSED and not approval
        ):
            raise NplPublicReleaseError(
                f"NPL coverage record {rec.record_id!r} "
                f"(adapter={rec.adapter_name!r}, rights={rec.rights_status.value!r}) "
                f"cannot enter a public release without separate rights approval",
                code="npl_public_release_blocked",
            )

    records = list(npl_records) if npl_records else list(coverage.npl_records_for_release_check())
    # Only check records that represent releasable content (have results / body).
    releasable = []
    for raw in records:
        rec = raw if isinstance(raw, NplRecord) else NplRecord.from_dict(raw)
        # Synthetic coverage placeholders without body and without claim of
        # release payload are skipped when allow_empty_npl and result is gap.
        if (
            allow_empty_npl
            and rec.body_text is None
            and rec.rights_status
            in (
                RightsStatus.UNLICENSED,
                RightsStatus.INACCESSIBLE,
                RightsStatus.UNKNOWN,
                RightsStatus.REQUIRES_APPROVAL,
            )
            and not rec.may_enter_public_release
        ):
            # Still block if someone tries to mark them for release via PUBLIC claim
            continue
        if rec.may_enter_public_release or rec.body_text is not None:
            releasable.append(rec)

    if releasable:
        try:
            assert_npl_records_safe_for_public_release(releasable)
        except Exception as exc:
            raise NplPublicReleaseError(str(exc), code="npl_public_release_blocked") from exc


def filter_npl_for_public_release(
    records: Sequence[NplRecord | Mapping[str, Any]],
) -> tuple[NplRecord, ...]:
    """Return only NPL records approved for public release (body already gated)."""
    out: list[NplRecord] = []
    for raw in records:
        rec = raw if isinstance(raw, NplRecord) else NplRecord.from_dict(raw)
        if rec.may_enter_public_release:
            out.append(rec)
    return tuple(out)


# ---------------------------------------------------------------------------
# Assertion helpers for tests / gates
# ---------------------------------------------------------------------------


def assert_coverage_records_complete(
    coverage: PriorArtCoverageDeclaration | Mapping[str, Any],
) -> None:
    """Fail closed if any record lacks adapter/query/time/cutoff/rights/count."""
    if isinstance(coverage, Mapping):
        coverage = PriorArtCoverageDeclaration.from_dict(coverage)
    for rec in coverage.records:
        _assert_record_identity(rec)
        # Explicit field presence for acceptance wording
        assert rec.adapter_name, "adapter required"
        assert rec.query_id, "query required"
        assert rec.search_time_utc, "timestamp required"
        assert rec.corpus_cutoff, "cutoff required"
        assert rec.rights_status is not None, "rights status required"
        assert isinstance(rec.result_count, int) and rec.result_count >= 0


def assert_named_gaps_visible(
    coverage: PriorArtCoverageDeclaration | Mapping[str, Any],
) -> None:
    """Fail closed if restricted unsearched corpora lack named visible gaps."""
    if isinstance(coverage, Mapping):
        coverage = PriorArtCoverageDeclaration.from_dict(coverage)
    _assert_named_gaps_for_restricted(
        searched=coverage.searched_corpora,
        gaps=coverage.named_gaps,
    )
    for gap in coverage.named_gaps:
        if not gap.source_name:
            raise NamedGapError(f"gap {gap.gap_id} missing source_name")
        if not gap.remains_visible:
            raise NamedGapError(f"gap {gap.gap_id} not visible")


__all__ = [
    "PRIOR_ART_COVERAGE_CODE_VERSION",
    "PRIOR_ART_COVERAGE_INTERFACE",
    "PRIOR_ART_COVERAGE_SCHEMA_VERSION",
    "OUTPUT_KIND_ADAPTER_COVERAGE_RECORD",
    "OUTPUT_KIND_COVERAGE_DECLARATION",
    "OUTPUT_KIND_NAMED_COVERAGE_GAP",
    "COVERAGE_DISCLAIMER",
    "GAP_SOURCE_FOREIGN_PATENTS",
    "GAP_SOURCE_NPL",
    "AdapterCoverageRecord",
    "CoverageCompletenessError",
    "CoverageRecordError",
    "CoverageRecordStatus",
    "CoverageSchemaError",
    "NamedCoverageGap",
    "NamedGapError",
    "NamedGapReason",
    "NplPublicReleaseError",
    "PriorArtCoverageDeclaration",
    "PriorArtCoverageError",
    "adapter_coverage_record_from_query_record",
    "assert_coverage_npl_release_safe",
    "assert_coverage_records_complete",
    "assert_named_gaps_visible",
    "build_coverage_declaration",
    "build_coverage_from_journal",
    "canonical_json",
    "content_cid",
    "content_digest",
    "coverage_status_from_query_record",
    "execute_plan_with_coverage",
    "filter_npl_for_public_release",
    "named_gap_foreign_patents",
    "named_gap_npl",
    "rights_status_from_query_record",
]
