"""Content-addressed prior-art search journal (PATLAW-148).

Records every executed public-patent (and optional licensed-source) query so
searches are reproducible: keywords, classifications, filters, cutoffs,
results, scores, retries, adapter identity, database, search time, corpus
cutoff, and source-snapshot bindings.

Design invariants
-----------------
* Serialization is deterministic via :func:`canonical_json` / digests.
* Every query record identifies **database**, **search time**, and
  **corpus cutoff** (fail closed if any are missing).
* Failures and rate limits remain first-class outcomes (never rewritten as
  empty successes).
* Foreign-patent and NPL corpora cannot be marked *searched* unless a
  **named adapter** that declares support for that corpus actually ran and
  reported a non-failure outcome that claims coverage.
* Journals never assert novelty, obviousness, or patentability.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .prior_art import (
    PRIOR_ART_DISCLAIMER,
    SearchCorpus,
)
from .retrieval_contracts import (
    SourceLink,
    SourceSpan,
    canonical_json as contracts_canonical_json,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SEARCH_JOURNAL_SCHEMA_VERSION: Final = "patent.search_journal.v1"
SEARCH_JOURNAL_INTERFACE: Final = "SearchJournal@1"
SEARCH_JOURNAL_CODE_VERSION: Final = "1.0.0"

OUTPUT_KIND_SEARCH_JOURNAL: Final = "prior_art_search_journal"
OUTPUT_KIND_QUERY_RECORD: Final = "prior_art_query_record"

SEARCH_JOURNAL_DISCLAIMER: Final = (
    "This artifact is a reproducible, content-addressed prior-art search "
    "journal for human review. It records which named adapters ran, which "
    "databases were queried, corpus cutoffs, ranks, and explicit failures or "
    "rate limits. Foreign-patent and NPL sources are never treated as "
    "searched unless a named adapter that supports those corpora actually "
    "ran. This is not a novelty, obviousness, or patentability determination, "
    "not legal advice, not an IDS filing, and not a substitute for Patent "
    "Public Search interactive verification."
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_CID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9+=/_-]{7,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

DEFAULT_MAX_RESULTS: Final = 256
DEFAULT_MAX_RETRIES: Final = 64
DEFAULT_MAX_QUERIES: Final = 512
DEFAULT_MAX_PASSAGE_CHARS: Final = 512

# Corpora that require an explicit named adapter before searched=True.
_RESTRICTED_SEARCH_CORPORA: Final[frozenset[SearchCorpus]] = frozenset(
    {
        SearchCorpus.FOREIGN_PATENTS,
        SearchCorpus.NPL,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SearchJournalError(ValueError):
    """Base error for search journal failures."""

    code: str = "search_journal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class MissingQueryIdentityError(SearchJournalError):
    """Raised when database, search time, or cutoff is missing."""

    code = "missing_query_identity"


class ForeignOrNplCoverageError(SearchJournalError):
    """Raised when foreign/NPL is claimed searched without a named adapter run."""

    code = "foreign_or_npl_coverage"


class SearchJournalSchemaError(SearchJournalError):
    """Raised on schema / field validation failures."""

    code = "schema_invalid"


class PatentabilityConclusionError(SearchJournalError):
    """Raised when a journal asserts patentability conclusions."""

    code = "patentability_conclusion"


_FORBIDDEN_CONCLUSION_KEYS: Final[frozenset[str]] = frozenset(
    {
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
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SearchDatabase(str, Enum):
    """Named databases / corpora that a query may target."""

    US_PATENTS = "us_patents"
    US_PUBLICATIONS = "us_publications"
    LOCAL_PUBLIC_SNAPSHOT = "local_public_snapshot"
    ODP_PATENT_FILE_WRAPPER = "odp_patent_file_wrapper"
    FOREIGN_PATENTS = "foreign_patents"
    NPL = "npl"


class QueryOutcomeKind(str, Enum):
    """Explicit outcome of one adapter query (never implicit empty success)."""

    SUCCESS = "success"
    EMPTY = "empty"
    FAILURE = "failure"
    RATE_LIMITED = "rate_limited"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    CANCELLED = "cancelled"
    TRANSPORT_ERROR = "transport_error"
    UPSTREAM_ERROR = "upstream_error"
    CLIENT_ERROR = "client_error"
    MALFORMED = "malformed"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    ADAPTER_NOT_REGISTERED = "adapter_not_registered"
    SKIPPED = "skipped"


class AdapterKind(str, Enum):
    """Category of named search adapter."""

    LOCAL_SNAPSHOT = "local_snapshot"
    ODP_PUBLIC = "odp_public"
    FOREIGN_PATENT = "foreign_patent"
    NPL = "npl"
    OTHER = "other"


# Map databases to SearchCorpus for coverage accounting.
_DATABASE_TO_CORPUS: Final[Mapping[SearchDatabase, SearchCorpus]] = MappingProxyType(
    {
        SearchDatabase.US_PATENTS: SearchCorpus.US_PATENTS,
        SearchDatabase.US_PUBLICATIONS: SearchCorpus.US_PUBLICATIONS,
        SearchDatabase.LOCAL_PUBLIC_SNAPSHOT: SearchCorpus.US_PATENTS,
        SearchDatabase.ODP_PATENT_FILE_WRAPPER: SearchCorpus.US_PATENTS,
        SearchDatabase.FOREIGN_PATENTS: SearchCorpus.FOREIGN_PATENTS,
        SearchDatabase.NPL: SearchCorpus.NPL,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys."""
    return contracts_canonical_json(value)


def content_digest(value: Any) -> str:
    """SHA-256 hex digest of canonical JSON (no ``sha256:`` prefix)."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid(value: Any, *, prefix: str = "bafybeig") -> str:
    """Deterministic content-address token from a payload digest.

    Not a full multihash CIDv1 encoding; used as a stable content-bound id
    within this processor family (matches other patent modules).
    """
    digest = content_digest(value)
    # Pad/truncate to a fixed visual length similar to other synthetic CIDs.
    body = digest[:48]
    return f"{prefix}{body}"


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise SearchJournalSchemaError(
            f"{label} has unknown fields: {', '.join(extra)}",
            code="unknown_fields",
        )


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


def _cid(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _CID_RE.match(text):
        raise ValueError(f"{field} is not a valid content identifier: {text!r}")
    return text


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _iso_date(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=32)
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} must be ISO calendar date YYYY-MM-DD, got {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _positive_int(value: Any, field: str) -> int:
    number = _nonneg_int(value, field)
    if number < 1:
        raise ValueError(f"{field} must be >= 1")
    return number


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be float, got {type(value).__name__}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be a finite float")
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


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=2048) for i, item in enumerate(value))


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


def _assert_no_forbidden_keys(metadata: Mapping[str, str], label: str) -> None:
    for key in metadata:
        if key.lower() in _FORBIDDEN_CONCLUSION_KEYS:
            raise PatentabilityConclusionError(
                f"{label} metadata must not assert patentability conclusion key {key!r}"
            )


def database_to_corpus(database: SearchDatabase | str) -> SearchCorpus:
    """Map a search database to a :class:`SearchCorpus` coverage label."""
    db = _coerce_enum(SearchDatabase, database, "database")
    assert isinstance(db, SearchDatabase)
    return _DATABASE_TO_CORPUS[db]


def is_restricted_corpus(corpus: SearchCorpus | str) -> bool:
    c = _coerce_enum(SearchCorpus, corpus, "corpus")
    return c in _RESTRICTED_SEARCH_CORPORA


def outcome_is_failure(kind: QueryOutcomeKind | str) -> bool:
    """Return True when the outcome is an explicit non-success terminal state."""
    k = _coerce_enum(QueryOutcomeKind, kind, "kind")
    return k in {
        QueryOutcomeKind.FAILURE,
        QueryOutcomeKind.RATE_LIMITED,
        QueryOutcomeKind.RETRY_BUDGET_EXHAUSTED,
        QueryOutcomeKind.CANCELLED,
        QueryOutcomeKind.TRANSPORT_ERROR,
        QueryOutcomeKind.UPSTREAM_ERROR,
        QueryOutcomeKind.CLIENT_ERROR,
        QueryOutcomeKind.MALFORMED,
        QueryOutcomeKind.UNAUTHORIZED,
        QueryOutcomeKind.FORBIDDEN,
        QueryOutcomeKind.ADAPTER_NOT_REGISTERED,
    }


def outcome_claims_search(kind: QueryOutcomeKind | str) -> bool:
    """Whether this outcome may count the database as *searched*."""
    k = _coerce_enum(QueryOutcomeKind, kind, "kind")
    return k in {QueryOutcomeKind.SUCCESS, QueryOutcomeKind.EMPTY}


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NamedAdapterIdentity:
    """Identity of a named prior-art search adapter that actually ran."""

    adapter_name: str
    adapter_kind: AdapterKind
    supported_corpora: tuple[SearchCorpus, ...]
    adapter_version: str = "1.0.0"
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "adapter_name", _identifier(self.adapter_name, "adapter_name")
        )
        object.__setattr__(
            self,
            "adapter_kind",
            _coerce_enum(AdapterKind, self.adapter_kind, "adapter_kind"),
        )
        corpora = self.supported_corpora or ()
        if not isinstance(corpora, Sequence) or isinstance(corpora, (str, bytes)):
            raise TypeError("supported_corpora must be a sequence")
        coerced = tuple(
            _coerce_enum(SearchCorpus, c, f"supported_corpora[{i}]")
            for i, c in enumerate(corpora)
        )
        if not coerced:
            raise ValueError("supported_corpora must be non-empty")
        object.__setattr__(self, "supported_corpora", coerced)
        object.__setattr__(
            self,
            "adapter_version",
            _require_str(self.adapter_version, "adapter_version", max_len=64),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "NamedAdapterIdentity")

    def supports(self, corpus: SearchCorpus | str) -> bool:
        c = _coerce_enum(SearchCorpus, corpus, "corpus")
        return c in self.supported_corpora

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_kind": self.adapter_kind.value,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "metadata": dict(self.metadata),
            "supported_corpora": [c.value for c in self.supported_corpora],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NamedAdapterIdentity":
        value = _mapping(value, "NamedAdapterIdentity")
        _reject_unknown(
            value,
            frozenset(
                {
                    "adapter_kind",
                    "adapter_name",
                    "adapter_version",
                    "metadata",
                    "supported_corpora",
                }
            ),
            "NamedAdapterIdentity",
        )
        return cls(
            adapter_name=value.get("adapter_name", ""),
            adapter_kind=value.get("adapter_kind", AdapterKind.OTHER.value),
            supported_corpora=tuple(value.get("supported_corpora") or ()),
            adapter_version=str(value.get("adapter_version") or "1.0.0"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class RetryAttemptRecord:
    """One retry / transport attempt attached to a query record."""

    attempt: int
    outcome: QueryOutcomeKind
    status_code: int | None = None
    error_code: str | None = None
    message: str | None = None
    elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt", _positive_int(self.attempt, "attempt"))
        object.__setattr__(
            self, "outcome", _coerce_enum(QueryOutcomeKind, self.outcome, "outcome")
        )
        if self.status_code is not None:
            object.__setattr__(
                self, "status_code", _nonneg_int(self.status_code, "status_code")
            )
        object.__setattr__(
            self,
            "error_code",
            _optional_str(self.error_code, "error_code", max_len=128),
        )
        object.__setattr__(
            self, "message", _optional_str(self.message, "message", max_len=1024)
        )
        if self.elapsed_ms is not None:
            object.__setattr__(
                self, "elapsed_ms", _nonneg_int(self.elapsed_ms, "elapsed_ms")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "elapsed_ms": self.elapsed_ms,
            "error_code": self.error_code,
            "message": self.message,
            "outcome": self.outcome.value,
            "status_code": self.status_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetryAttemptRecord":
        value = _mapping(value, "RetryAttemptRecord")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attempt",
                    "elapsed_ms",
                    "error_code",
                    "message",
                    "outcome",
                    "status_code",
                }
            ),
            "RetryAttemptRecord",
        )
        sc = value.get("status_code")
        em = value.get("elapsed_ms")
        return cls(
            attempt=int(value.get("attempt") or 0),
            outcome=value.get("outcome", QueryOutcomeKind.FAILURE.value),
            status_code=None if sc is None else int(sc),
            error_code=value.get("error_code"),
            message=value.get("message"),
            elapsed_ms=None if em is None else int(em),
        )


@dataclass(frozen=True, slots=True)
class JournalHit:
    """One ranked hit recorded in the journal (with source citation)."""

    document_id: str
    rank: int
    score: float
    source_links: tuple[SourceLink, ...]
    passage_excerpt: str | None = None
    identifiers: Mapping[str, str] = MappingProxyType({})
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(self, "rank", _positive_int(self.rank, "rank"))
        object.__setattr__(self, "score", _finite_float(self.score, "score"))
        links = self.source_links or ()
        if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
            raise TypeError("source_links must be a sequence")
        parsed: list[SourceLink] = []
        for i, item in enumerate(links):
            if isinstance(item, SourceLink):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(SourceLink.from_dict(item))
            else:
                raise TypeError(f"source_links[{i}] must be SourceLink or mapping")
        if not parsed:
            raise SearchJournalSchemaError(
                f"hit {self.document_id} must cite at least one source link",
                code="missing_source_link",
            )
        for link in parsed:
            if not link.source_cid:
                raise SearchJournalSchemaError(
                    f"hit {self.document_id} missing source CID",
                    code="missing_source_cid",
                )
            if link.span is None:
                raise SearchJournalSchemaError(
                    f"hit {self.document_id} missing source span",
                    code="missing_source_span",
                )
        object.__setattr__(self, "source_links", tuple(parsed))
        object.__setattr__(
            self,
            "passage_excerpt",
            _optional_str(
                self.passage_excerpt, "passage_excerpt", max_len=DEFAULT_MAX_PASSAGE_CHARS
            ),
        )
        object.__setattr__(
            self, "identifiers", _frozen_str_map(self.identifiers, "identifiers")
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "JournalHit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "identifiers": dict(self.identifiers),
            "metadata": dict(self.metadata),
            "passage_excerpt": self.passage_excerpt,
            "rank": self.rank,
            "score": self.score,
            "source_links": [link.to_dict() for link in self.source_links],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JournalHit":
        value = _mapping(value, "JournalHit")
        _reject_unknown(
            value,
            frozenset(
                {
                    "document_id",
                    "identifiers",
                    "metadata",
                    "passage_excerpt",
                    "rank",
                    "score",
                    "source_links",
                }
            ),
            "JournalHit",
        )
        return cls(
            document_id=value.get("document_id", ""),
            rank=int(value.get("rank") or 0),
            score=float(value.get("score") or 0.0),
            source_links=tuple(value.get("source_links") or ()),
            passage_excerpt=value.get("passage_excerpt"),
            identifiers=value.get("identifiers") or {},
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class QueryRecord:
    """One executed query: database + time + cutoff + adapter + outcome.

    Fail-closed: database, search_time_utc, and corpus_cutoff are always
    required. Foreign/NPL searched flags require a matching named adapter.
    """

    record_id: str
    query_id: str
    query_text: str
    database: SearchDatabase
    search_time_utc: str
    corpus_cutoff: str
    rank_cutoff: int
    adapter: NamedAdapterIdentity
    outcome: QueryOutcomeKind
    keywords: tuple[str, ...] = ()
    classification_codes: tuple[str, ...] = ()
    filters: Mapping[str, str] = MappingProxyType({})
    hits: tuple[JournalHit, ...] = ()
    retries: tuple[RetryAttemptRecord, ...] = ()
    source_snapshot_cid: str | None = None
    transport_receipt_id: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_count: int = 0
    claims_corpus_searched: bool = False
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _identifier(self.record_id, "record_id"))
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "query_text", _require_str(self.query_text, "query_text", max_len=8192)
        )
        object.__setattr__(
            self, "database", _coerce_enum(SearchDatabase, self.database, "database")
        )
        object.__setattr__(
            self, "search_time_utc", _iso_utc(self.search_time_utc, "search_time_utc")
        )
        # Corpus cutoff may be a calendar date or full UTC timestamp.
        cutoff = _require_str(self.corpus_cutoff, "corpus_cutoff", max_len=64)
        if not (_ISO_DATE_RE.match(cutoff) or _ISO_UTC_RE.match(cutoff)):
            raise MissingQueryIdentityError(
                f"corpus_cutoff must be YYYY-MM-DD or ISO-8601 UTC, got {cutoff!r}"
            )
        object.__setattr__(self, "corpus_cutoff", cutoff)
        object.__setattr__(
            self, "rank_cutoff", _positive_int(self.rank_cutoff, "rank_cutoff")
        )
        if not isinstance(self.adapter, NamedAdapterIdentity):
            if isinstance(self.adapter, Mapping):
                object.__setattr__(
                    self, "adapter", NamedAdapterIdentity.from_dict(self.adapter)
                )
            else:
                raise TypeError("adapter must be NamedAdapterIdentity or mapping")
        object.__setattr__(
            self, "outcome", _coerce_enum(QueryOutcomeKind, self.outcome, "outcome")
        )
        object.__setattr__(
            self, "keywords", _tuple_of_str(self.keywords, "keywords", max_items=128)
        )
        object.__setattr__(
            self,
            "classification_codes",
            _tuple_of_str(
                self.classification_codes, "classification_codes", max_items=64
            ),
        )
        object.__setattr__(self, "filters", _frozen_str_map(self.filters, "filters"))

        hits_raw = self.hits or ()
        if not isinstance(hits_raw, Sequence) or isinstance(hits_raw, (str, bytes)):
            raise TypeError("hits must be a sequence")
        if len(hits_raw) > DEFAULT_MAX_RESULTS:
            raise ValueError(f"hits exceeds max items {DEFAULT_MAX_RESULTS}")
        parsed_hits: list[JournalHit] = []
        for i, item in enumerate(hits_raw):
            if isinstance(item, JournalHit):
                parsed_hits.append(item)
            elif isinstance(item, Mapping):
                parsed_hits.append(JournalHit.from_dict(item))
            else:
                raise TypeError(f"hits[{i}] must be JournalHit or mapping")
        # Drop hits past rank_cutoff for journal fidelity to planned cutoff.
        parsed_hits = [h for h in parsed_hits if h.rank <= self.rank_cutoff]
        object.__setattr__(self, "hits", tuple(parsed_hits))

        retries_raw = self.retries or ()
        if not isinstance(retries_raw, Sequence) or isinstance(retries_raw, (str, bytes)):
            raise TypeError("retries must be a sequence")
        if len(retries_raw) > DEFAULT_MAX_RETRIES:
            raise ValueError(f"retries exceeds max items {DEFAULT_MAX_RETRIES}")
        parsed_retries: list[RetryAttemptRecord] = []
        for i, item in enumerate(retries_raw):
            if isinstance(item, RetryAttemptRecord):
                parsed_retries.append(item)
            elif isinstance(item, Mapping):
                parsed_retries.append(RetryAttemptRecord.from_dict(item))
            else:
                raise TypeError(f"retries[{i}] must be RetryAttemptRecord or mapping")
        object.__setattr__(self, "retries", tuple(parsed_retries))

        object.__setattr__(
            self,
            "source_snapshot_cid",
            _optional_str(self.source_snapshot_cid, "source_snapshot_cid", max_len=256),
        )
        if self.source_snapshot_cid is not None:
            object.__setattr__(
                self,
                "source_snapshot_cid",
                _cid(self.source_snapshot_cid, "source_snapshot_cid"),
            )
        object.__setattr__(
            self,
            "transport_receipt_id",
            _optional_str(
                self.transport_receipt_id, "transport_receipt_id", max_len=256
            ),
        )
        if self.status_code is not None:
            object.__setattr__(
                self, "status_code", _nonneg_int(self.status_code, "status_code")
            )
        object.__setattr__(
            self,
            "error_code",
            _optional_str(self.error_code, "error_code", max_len=128),
        )
        object.__setattr__(
            self,
            "error_message",
            _optional_str(self.error_message, "error_message", max_len=2048),
        )
        object.__setattr__(
            self, "result_count", _nonneg_int(self.result_count, "result_count")
        )
        if not isinstance(self.claims_corpus_searched, bool):
            raise TypeError("claims_corpus_searched must be bool")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "QueryRecord")

        # Identity completeness (acceptance: every query identifies these).
        if not self.database or not self.search_time_utc or not self.corpus_cutoff:
            raise MissingQueryIdentityError(
                "every query must identify database, search_time_utc, and corpus_cutoff"
            )

        # Align result_count with hits when success/empty.
        if outcome_claims_search(self.outcome) and self.result_count == 0:
            object.__setattr__(self, "result_count", len(self.hits))

        # Failures must remain explicit: success cannot carry error-only state.
        if self.outcome is QueryOutcomeKind.SUCCESS and outcome_is_failure(
            self.outcome
        ):
            raise SearchJournalSchemaError("internal outcome inconsistency")

        # Rate limits must stay explicit (never rewritten as empty success).
        if self.outcome is QueryOutcomeKind.RATE_LIMITED:
            if not self.error_code:
                object.__setattr__(self, "error_code", "rate_limited")
            if self.claims_corpus_searched:
                raise ForeignOrNplCoverageError(
                    "rate-limited query cannot claim corpus searched",
                    code="rate_limit_claims_searched",
                )

        # Restricted corpora: claims_corpus_searched requires adapter support.
        corpus = database_to_corpus(self.database)
        if self.claims_corpus_searched and is_restricted_corpus(corpus):
            if not self.adapter.supports(corpus):
                raise ForeignOrNplCoverageError(
                    f"adapter {self.adapter.adapter_name!r} does not support "
                    f"{corpus.value}; cannot claim searched",
                )
            if not outcome_claims_search(self.outcome):
                raise ForeignOrNplCoverageError(
                    f"outcome {self.outcome.value} cannot claim {corpus.value} searched",
                )
        # Never allow claims_corpus_searched for restricted corpora on US-only adapters
        # even when outcome is success — enforced above.

    @property
    def corpus(self) -> SearchCorpus:
        return database_to_corpus(self.database)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter.to_dict(),
            "classification_codes": list(self.classification_codes),
            "claims_corpus_searched": self.claims_corpus_searched,
            "corpus_cutoff": self.corpus_cutoff,
            "database": self.database.value,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "filters": dict(self.filters),
            "hits": [h.to_dict() for h in self.hits],
            "keywords": list(self.keywords),
            "metadata": dict(self.metadata),
            "outcome": self.outcome.value,
            "query_id": self.query_id,
            "query_text": self.query_text,
            "rank_cutoff": self.rank_cutoff,
            "record_id": self.record_id,
            "result_count": self.result_count,
            "retries": [r.to_dict() for r in self.retries],
            "search_time_utc": self.search_time_utc,
            "source_snapshot_cid": self.source_snapshot_cid,
            "status_code": self.status_code,
            "transport_receipt_id": self.transport_receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QueryRecord":
        value = _mapping(value, "QueryRecord")
        _reject_unknown(
            value,
            frozenset(
                {
                    "adapter",
                    "classification_codes",
                    "claims_corpus_searched",
                    "corpus_cutoff",
                    "database",
                    "error_code",
                    "error_message",
                    "filters",
                    "hits",
                    "keywords",
                    "metadata",
                    "outcome",
                    "query_id",
                    "query_text",
                    "rank_cutoff",
                    "record_id",
                    "result_count",
                    "retries",
                    "search_time_utc",
                    "source_snapshot_cid",
                    "status_code",
                    "transport_receipt_id",
                }
            ),
            "QueryRecord",
        )
        sc = value.get("status_code")
        return cls(
            record_id=value.get("record_id", ""),
            query_id=value.get("query_id", ""),
            query_text=value.get("query_text", ""),
            database=value.get("database", SearchDatabase.US_PATENTS.value),
            search_time_utc=value.get("search_time_utc", ""),
            corpus_cutoff=value.get("corpus_cutoff", ""),
            rank_cutoff=int(value.get("rank_cutoff") or 1),
            adapter=value.get("adapter") or {},
            outcome=value.get("outcome", QueryOutcomeKind.FAILURE.value),
            keywords=tuple(value.get("keywords") or ()),
            classification_codes=tuple(value.get("classification_codes") or ()),
            filters=value.get("filters") or {},
            hits=tuple(value.get("hits") or ()),
            retries=tuple(value.get("retries") or ()),
            source_snapshot_cid=value.get("source_snapshot_cid"),
            transport_receipt_id=value.get("transport_receipt_id"),
            status_code=None if sc is None else int(sc),
            error_code=value.get("error_code"),
            error_message=value.get("error_message"),
            result_count=int(value.get("result_count") or 0),
            claims_corpus_searched=bool(value.get("claims_corpus_searched", False)),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SearchJournal:
    """Replayable content-addressed collection of prior-art query records."""

    schema_version: str
    journal_id: str
    subject_id: str
    search_date_utc: str
    corpus_cutoff: str
    records: tuple[QueryRecord, ...]
    adapters_run: tuple[NamedAdapterIdentity, ...] = ()
    searched_corpora: tuple[SearchCorpus, ...] = ()
    unsearched_corpora: tuple[SearchCorpus, ...] = ()
    source_snapshot_cids: tuple[str, ...] = ()
    plan_id: str | None = None
    disclaimer: str = SEARCH_JOURNAL_DISCLAIMER
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        schema = _require_str(self.schema_version, "schema_version", max_len=64)
        if schema != SEARCH_JOURNAL_SCHEMA_VERSION:
            raise SearchJournalSchemaError(
                f"schema_version must be {SEARCH_JOURNAL_SCHEMA_VERSION}, got {schema!r}",
                code="schema_version",
            )
        object.__setattr__(self, "schema_version", schema)
        object.__setattr__(self, "journal_id", _identifier(self.journal_id, "journal_id"))
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "search_date_utc", _iso_utc(self.search_date_utc, "search_date_utc")
        )
        cutoff = _require_str(self.corpus_cutoff, "corpus_cutoff", max_len=64)
        if not (_ISO_DATE_RE.match(cutoff) or _ISO_UTC_RE.match(cutoff)):
            raise MissingQueryIdentityError(
                f"corpus_cutoff must be YYYY-MM-DD or ISO-8601 UTC, got {cutoff!r}"
            )
        object.__setattr__(self, "corpus_cutoff", cutoff)

        records_raw = self.records or ()
        if not isinstance(records_raw, Sequence) or isinstance(records_raw, (str, bytes)):
            raise TypeError("records must be a sequence")
        if len(records_raw) > DEFAULT_MAX_QUERIES:
            raise ValueError(f"records exceeds max items {DEFAULT_MAX_QUERIES}")
        parsed: list[QueryRecord] = []
        for i, item in enumerate(records_raw):
            if isinstance(item, QueryRecord):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(QueryRecord.from_dict(item))
            else:
                raise TypeError(f"records[{i}] must be QueryRecord or mapping")
        object.__setattr__(self, "records", tuple(parsed))

        adapters_raw = self.adapters_run or ()
        if not isinstance(adapters_raw, Sequence) or isinstance(adapters_raw, (str, bytes)):
            raise TypeError("adapters_run must be a sequence")
        adapters: list[NamedAdapterIdentity] = []
        for i, item in enumerate(adapters_raw):
            if isinstance(item, NamedAdapterIdentity):
                adapters.append(item)
            elif isinstance(item, Mapping):
                adapters.append(NamedAdapterIdentity.from_dict(item))
            else:
                raise TypeError(f"adapters_run[{i}] must be NamedAdapterIdentity or mapping")
        # Derive adapters_run from records when empty.
        if not adapters:
            seen: dict[str, NamedAdapterIdentity] = {}
            for rec in parsed:
                seen.setdefault(rec.adapter.adapter_name, rec.adapter)
            adapters = list(seen.values())
        object.__setattr__(self, "adapters_run", tuple(adapters))

        # Coverage accounting — fail closed for foreign/NPL claims.
        searched, unsearched = _derive_coverage(
            records=parsed,
            adapters=tuple(adapters),
            claimed_searched=self.searched_corpora,
            claimed_unsearched=self.unsearched_corpora,
        )
        object.__setattr__(self, "searched_corpora", searched)
        object.__setattr__(self, "unsearched_corpora", unsearched)

        cids = _tuple_of_str(self.source_snapshot_cids, "source_snapshot_cids", max_items=64)
        if not cids:
            derived = sorted(
                {
                    r.source_snapshot_cid
                    for r in parsed
                    if r.source_snapshot_cid is not None
                }
            )
            cids = tuple(derived)
        for cid in cids:
            if not _CID_RE.match(cid):
                raise ValueError(f"invalid source_snapshot_cid: {cid!r}")
        object.__setattr__(self, "source_snapshot_cids", cids)

        object.__setattr__(
            self, "plan_id", _optional_str(self.plan_id, "plan_id", max_len=256)
        )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "SearchJournal")

        # Ensure every record carries database/time/cutoff.
        for rec in parsed:
            if not rec.database or not rec.search_time_utc or not rec.corpus_cutoff:
                raise MissingQueryIdentityError(
                    f"record {rec.record_id} missing database/time/cutoff"
                )

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    @property
    def content_cid(self) -> str:
        return content_cid(self.to_dict())

    def outcome_kinds(self) -> tuple[QueryOutcomeKind, ...]:
        return tuple(r.outcome for r in self.records)

    def has_explicit_failure(self) -> bool:
        return any(outcome_is_failure(r.outcome) for r in self.records)

    def has_rate_limit(self) -> bool:
        return any(r.outcome is QueryOutcomeKind.RATE_LIMITED for r in self.records)

    def corpus_was_searched(self, corpus: SearchCorpus | str) -> bool:
        c = _coerce_enum(SearchCorpus, corpus, "corpus")
        return c in self.searched_corpora

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapters_run": [a.to_dict() for a in self.adapters_run],
            "corpus_cutoff": self.corpus_cutoff,
            "disclaimer": self.disclaimer,
            "journal_id": self.journal_id,
            "metadata": dict(self.metadata),
            "plan_id": self.plan_id,
            "records": [r.to_dict() for r in self.records],
            "schema_version": self.schema_version,
            "search_date_utc": self.search_date_utc,
            "searched_corpora": [c.value for c in self.searched_corpora],
            "source_snapshot_cids": list(self.source_snapshot_cids),
            "subject_id": self.subject_id,
            "unsearched_corpora": [c.value for c in self.unsearched_corpora],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SearchJournal":
        value = _mapping(value, "SearchJournal")
        _reject_unknown(
            value,
            frozenset(
                {
                    "adapters_run",
                    "corpus_cutoff",
                    "disclaimer",
                    "journal_id",
                    "metadata",
                    "plan_id",
                    "records",
                    "schema_version",
                    "search_date_utc",
                    "searched_corpora",
                    "source_snapshot_cids",
                    "subject_id",
                    "unsearched_corpora",
                }
            ),
            "SearchJournal",
        )
        return cls(
            schema_version=value.get("schema_version", SEARCH_JOURNAL_SCHEMA_VERSION),
            journal_id=value.get("journal_id", ""),
            subject_id=value.get("subject_id", ""),
            search_date_utc=value.get("search_date_utc", ""),
            corpus_cutoff=value.get("corpus_cutoff", ""),
            records=tuple(value.get("records") or ()),
            adapters_run=tuple(value.get("adapters_run") or ()),
            searched_corpora=tuple(value.get("searched_corpora") or ()),
            unsearched_corpora=tuple(value.get("unsearched_corpora") or ()),
            source_snapshot_cids=tuple(value.get("source_snapshot_cids") or ()),
            plan_id=value.get("plan_id"),
            disclaimer=value.get("disclaimer") or SEARCH_JOURNAL_DISCLAIMER,
            metadata=value.get("metadata") or {},
        )


def _derive_coverage(
    *,
    records: Sequence[QueryRecord],
    adapters: Sequence[NamedAdapterIdentity],
    claimed_searched: Sequence[SearchCorpus | str] | None,
    claimed_unsearched: Sequence[SearchCorpus | str] | None,
) -> tuple[tuple[SearchCorpus, ...], tuple[SearchCorpus, ...]]:
    """Compute searched/unsearched corpora with foreign/NPL fail-closed rules."""
    adapter_by_name = {a.adapter_name: a for a in adapters}
    searched: set[SearchCorpus] = set()

    for rec in records:
        corpus = rec.corpus
        if not rec.claims_corpus_searched:
            continue
        if not outcome_claims_search(rec.outcome):
            continue
        adapter = adapter_by_name.get(rec.adapter.adapter_name, rec.adapter)
        if is_restricted_corpus(corpus) and not adapter.supports(corpus):
            raise ForeignOrNplCoverageError(
                f"cannot mark {corpus.value} searched: adapter "
                f"{adapter.adapter_name!r} does not support it and did not run "
                f"as a named foreign/NPL adapter",
            )
        if is_restricted_corpus(corpus):
            # Require the record's adapter itself to support the corpus.
            if not rec.adapter.supports(corpus):
                raise ForeignOrNplCoverageError(
                    f"record {rec.record_id} claims {corpus.value} searched "
                    f"but adapter {rec.adapter.adapter_name!r} lacks support",
                )
        searched.add(corpus)  # type: ignore[arg-type]

    # Claimed searched corpora must be justified by records.
    if claimed_searched:
        for raw in claimed_searched:
            c = _coerce_enum(SearchCorpus, raw, "searched_corpora")
            if c not in searched:
                # Allow claimed US corpora only when justified; for restricted,
                # always require records.
                if is_restricted_corpus(c):  # type: ignore[arg-type]
                    raise ForeignOrNplCoverageError(
                        f"claimed searched corpus {c.value} has no matching "
                        f"named adapter run",
                    )
                # Non-restricted: accept claim only if some success record maps.
                justified = any(
                    r.corpus is c
                    and r.claims_corpus_searched
                    and outcome_claims_search(r.outcome)
                    for r in records
                )
                if not justified:
                    # Soft-add only when records justify; else ignore claim.
                    continue
                searched.add(c)  # type: ignore[arg-type]

    # Default unsearched: restricted corpora not in searched, plus any claimed.
    unsearched: set[SearchCorpus] = set()
    for restricted in _RESTRICTED_SEARCH_CORPORA:
        if restricted not in searched:
            unsearched.add(restricted)
    if claimed_unsearched:
        for raw in claimed_unsearched:
            c = _coerce_enum(SearchCorpus, raw, "unsearched_corpora")
            unsearched.add(c)  # type: ignore[arg-type]
            if c in searched:
                # Cannot be both.
                raise ForeignOrNplCoverageError(
                    f"corpus {c.value} cannot be both searched and unsearched",
                    code="coverage_conflict",
                )

    return (
        tuple(sorted(searched, key=lambda x: x.value)),
        tuple(sorted(unsearched, key=lambda x: x.value)),
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_query_record(
    *,
    query_id: str,
    query_text: str,
    database: SearchDatabase | str,
    search_time_utc: str,
    corpus_cutoff: str,
    rank_cutoff: int,
    adapter: NamedAdapterIdentity | Mapping[str, Any],
    outcome: QueryOutcomeKind | str,
    keywords: Sequence[str] = (),
    classification_codes: Sequence[str] = (),
    filters: Mapping[str, str] | None = None,
    hits: Sequence[JournalHit | Mapping[str, Any]] = (),
    retries: Sequence[RetryAttemptRecord | Mapping[str, Any]] = (),
    source_snapshot_cid: str | None = None,
    transport_receipt_id: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    result_count: int | None = None,
    claims_corpus_searched: bool | None = None,
    record_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> QueryRecord:
    """Build a validated :class:`QueryRecord` with explicit identity fields."""
    if isinstance(adapter, Mapping):
        adapter = NamedAdapterIdentity.from_dict(adapter)
    outcome_k = _coerce_enum(QueryOutcomeKind, outcome, "outcome")
    assert isinstance(outcome_k, QueryOutcomeKind)

    # Default claims_corpus_searched: only for non-restricted success/empty
    # outcomes from adapters that support the mapped corpus.
    db = _coerce_enum(SearchDatabase, database, "database")
    assert isinstance(db, SearchDatabase)
    corpus = database_to_corpus(db)
    if claims_corpus_searched is None:
        claims_corpus_searched = bool(
            outcome_claims_search(outcome_k)
            and adapter.supports(corpus)
            and (
                not is_restricted_corpus(corpus)
                or (
                    is_restricted_corpus(corpus)
                    and adapter.supports(corpus)
                    and outcome_claims_search(outcome_k)
                )
            )
        )
        # Restricted corpora still need claims flag only when adapter supports.
        if is_restricted_corpus(corpus) and not adapter.supports(corpus):
            claims_corpus_searched = False

    hit_list = list(hits)
    if result_count is None:
        result_count = len(hit_list) if outcome_claims_search(outcome_k) else 0

    rid = record_id or f"qrec:{query_id}:{content_digest({'q': query_id, 't': search_time_utc})[:12]}"
    return QueryRecord(
        record_id=rid,
        query_id=query_id,
        query_text=query_text,
        database=db,
        search_time_utc=search_time_utc,
        corpus_cutoff=corpus_cutoff,
        rank_cutoff=rank_cutoff,
        adapter=adapter,
        outcome=outcome_k,
        keywords=tuple(keywords),
        classification_codes=tuple(classification_codes),
        filters=filters or {},
        hits=tuple(hit_list),
        retries=tuple(retries),
        source_snapshot_cid=source_snapshot_cid,
        transport_receipt_id=transport_receipt_id,
        status_code=status_code,
        error_code=error_code,
        error_message=error_message,
        result_count=int(result_count),
        claims_corpus_searched=bool(claims_corpus_searched),
        metadata=metadata or {},
    )


def build_search_journal(
    *,
    subject_id: str,
    search_date_utc: str,
    corpus_cutoff: str,
    records: Sequence[QueryRecord | Mapping[str, Any]],
    journal_id: str | None = None,
    plan_id: str | None = None,
    adapters_run: Sequence[NamedAdapterIdentity | Mapping[str, Any]] = (),
    source_snapshot_cids: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
) -> SearchJournal:
    """Assemble a content-addressed :class:`SearchJournal` from query records."""
    parsed = [
        r if isinstance(r, QueryRecord) else QueryRecord.from_dict(r) for r in records
    ]
    identity = {
        "corpus_cutoff": corpus_cutoff,
        "records": [r.to_dict() for r in parsed],
        "search_date_utc": search_date_utc,
        "subject_id": subject_id,
    }
    digest = content_digest(identity)[:16]
    jid = journal_id or f"journal:prior-art:{digest}"
    return SearchJournal(
        schema_version=SEARCH_JOURNAL_SCHEMA_VERSION,
        journal_id=jid,
        subject_id=subject_id,
        search_date_utc=search_date_utc,
        corpus_cutoff=corpus_cutoff,
        records=tuple(parsed),
        adapters_run=tuple(adapters_run),
        source_snapshot_cids=tuple(source_snapshot_cids),
        plan_id=plan_id,
        metadata=metadata or {},
    )


def assert_journal_query_identity(journal: SearchJournal | Mapping[str, Any]) -> None:
    """Fail closed if any record lacks database, time, or cutoff."""
    if isinstance(journal, Mapping):
        journal = SearchJournal.from_dict(journal)
    for rec in journal.records:
        if not rec.database:
            raise MissingQueryIdentityError(f"{rec.record_id}: missing database")
        if not rec.search_time_utc:
            raise MissingQueryIdentityError(f"{rec.record_id}: missing search_time_utc")
        if not rec.corpus_cutoff:
            raise MissingQueryIdentityError(f"{rec.record_id}: missing corpus_cutoff")


def assert_no_unjustified_foreign_npl(journal: SearchJournal | Mapping[str, Any]) -> None:
    """Fail closed if foreign/NPL appear searched without a named adapter run."""
    if isinstance(journal, Mapping):
        journal = SearchJournal.from_dict(journal)
    for corpus in (SearchCorpus.FOREIGN_PATENTS, SearchCorpus.NPL):
        if corpus not in journal.searched_corpora:
            continue
        justified = any(
            r.corpus is corpus
            and r.claims_corpus_searched
            and outcome_claims_search(r.outcome)
            and r.adapter.supports(corpus)
            for r in journal.records
        )
        if not justified:
            raise ForeignOrNplCoverageError(
                f"{corpus.value} marked searched without a named adapter that ran"
            )


def make_source_link(
    *,
    source_cid: str,
    artifact_id: str,
    start: int = 0,
    end: int = 1,
    source_receipt_id: str | None = None,
    authority_tier: str = "official-base",
) -> SourceLink:
    """Helper to build a span-bound :class:`SourceLink` for journal hits."""
    if end <= start:
        end = start + 1
    return SourceLink(
        source_cid=source_cid,
        artifact_id=artifact_id,
        span=SourceSpan(start=start, end=end, unit="char"),
        source_receipt_id=source_receipt_id,
        authority_tier=authority_tier,
    )


__all__ = [
    "SEARCH_JOURNAL_CODE_VERSION",
    "SEARCH_JOURNAL_DISCLAIMER",
    "SEARCH_JOURNAL_INTERFACE",
    "SEARCH_JOURNAL_SCHEMA_VERSION",
    "OUTPUT_KIND_QUERY_RECORD",
    "OUTPUT_KIND_SEARCH_JOURNAL",
    "AdapterKind",
    "ForeignOrNplCoverageError",
    "JournalHit",
    "MissingQueryIdentityError",
    "NamedAdapterIdentity",
    "PatentabilityConclusionError",
    "QueryOutcomeKind",
    "QueryRecord",
    "RetryAttemptRecord",
    "SearchDatabase",
    "SearchJournal",
    "SearchJournalError",
    "SearchJournalSchemaError",
    "assert_journal_query_identity",
    "assert_no_unjustified_foreign_npl",
    "build_query_record",
    "build_search_journal",
    "canonical_json",
    "content_cid",
    "content_digest",
    "database_to_corpus",
    "is_restricted_corpus",
    "make_source_link",
    "outcome_claims_search",
    "outcome_is_failure",
]
