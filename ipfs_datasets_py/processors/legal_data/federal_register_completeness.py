"""Cutoff-bound official Federal Register completeness oracle (LCR-049).

Evaluates sealed completion receipts against fail-closed rules for:

* open (unresolved) API result pages;
* overlapping or gapped date partitions;
* mutable observation cutoffs;
* metadata/abstract represented as body text;
* failed-final items in a closed/publication cohort;
* unexplained official-total count drift;
* stale success registries that mark incomplete frontiers as success.

Completeness is cutoff-relative. A closed receipt must prove:

```
enumerated = fetched + duplicate + excluded + quarantined + failed_final
```

with zero unresolved pages/date partitions, zero unexplained document-number
gaps relative to the official inventory, and an explicit delta from the old
2026-03-02 baseline endpoint through the sealed observation cutoff.

Live network I/O is out of scope; unit tests use sealed fixtures only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    BODY_BEARING_DISPOSITIONS,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    FEDERAL_REGISTER_DOCUMENTS_API,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    LEGACY_BASELINE_END_INCLUSIVE,
    LEGACY_DELTA_START_INCLUSIVE,
    METADATA_AS_BODY_CHAR_THRESHOLD,
    PREVIOUS_PUBLIC_PIN,
    SCHEMA_VERSION as POLICY_SCHEMA_VERSION,
    TASK_ID,
    BodyTextDisposition,
    BodyTextDispositionError,
    FederalRegisterSourcePolicy,
    FederalRegisterSourcePolicyError,
    FixtureSchemaError,
    MutableCutoffError,
    OfficialAuthority,
    build_legal_id,
    content_sha256,
    cutoff_release_point,
    days_between_inclusive,
    default_completion_fixture_path,
    default_source_policy,
    digest_mapping,
    disposition_count_map,
    is_mutable_cutoff,
    normalize_sha256,
    parse_calendar_date,
    require_exact_release_point,
    require_immutable_observation_cutoff,
    validate_body_text_disposition_fields,
    validate_calendar_date,
    validate_document_number,
    validate_official_url,
    validate_year_month,
)

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-completeness-v1"
COMPLETENESS_TASK_ID: Final = TASK_ID

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterCompletenessError(FederalRegisterSourcePolicyError):
    """Base error for Federal Register completeness oracle failures."""


class OpenPageError(FederalRegisterCompletenessError):
    """Raised when an API result page is unresolved / open."""


class DatePartitionError(FederalRegisterCompletenessError):
    """Raised when date partitions overlap or leave gaps."""


class CountDriftError(FederalRegisterCompletenessError):
    """Raised when enumerated totals drift from official API totals."""


class ReconciliationError(FederalRegisterCompletenessError):
    """Raised when disposition arithmetic does not reconcile."""


class FailedFinalError(FederalRegisterCompletenessError):
    """Raised when failed-final items remain in a closed/publication cohort."""


class StaleSuccessRegistryError(FederalRegisterCompletenessError):
    """Raised when a success registry marks incomplete work as success."""


class MetadataAsBodyError(FederalRegisterCompletenessError):
    """Raised when metadata/abstract is represented as body text."""


class ResumeError(FederalRegisterCompletenessError):
    """Raised when a resume checkpoint is incomplete or non-deterministic."""


class DeltaError(FederalRegisterCompletenessError):
    """Raised when the legacy-baseline delta is missing or inconsistent."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PageStatus(str, Enum):
    """Lifecycle status of one official API result page."""

    PENDING = "pending"
    FETCHED = "fetched"
    VERIFIED = "verified"
    OPEN = "open"
    FAILED = "failed"
    SKIPPED = "skipped"

    @classmethod
    def coerce(cls, value: Any) -> "PageStatus":
        if isinstance(value, PageStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "closed": cls.VERIFIED,
            "complete": cls.VERIFIED,
            "ok": cls.VERIFIED,
            "done": cls.VERIFIED,
            "unresolved": cls.OPEN,
            "incomplete": cls.OPEN,
            "error": cls.FAILED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise OpenPageError(f"unknown page status: {value!r}")

    @property
    def is_closed(self) -> bool:
        return self in {PageStatus.FETCHED, PageStatus.VERIFIED, PageStatus.SKIPPED}

    @property
    def is_open(self) -> bool:
        return self in {PageStatus.PENDING, PageStatus.OPEN, PageStatus.FAILED}


class PartitionStatus(str, Enum):
    """Lifecycle status of one date partition."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"
    FAILED = "failed"

    @classmethod
    def coerce(cls, value: Any) -> "PartitionStatus":
        if isinstance(value, PartitionStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "complete": cls.CLOSED,
            "done": cls.CLOSED,
            "success": cls.CLOSED,
            "ok": cls.CLOSED,
            "open": cls.IN_PROGRESS,
            "running": cls.IN_PROGRESS,
            "error": cls.FAILED,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        raise DatePartitionError(f"unknown partition status: {value!r}")

    @property
    def is_closed(self) -> bool:
        return self is PartitionStatus.CLOSED


class CompletenessVerdict(str, Enum):
    """Oracle verdict for one completion receipt or fixture case."""

    PASS = "pass"
    FAIL = "fail"

    @classmethod
    def coerce(cls, value: Any) -> "CompletenessVerdict":
        if isinstance(value, CompletenessVerdict):
            return value
        text = str(value or "").strip().lower()
        if text in {"pass", "ok", "success", "closed", "true", "1"}:
            return cls.PASS
        if text in {"fail", "failed", "error", "reject", "false", "0"}:
            return cls.FAIL
        raise FederalRegisterCompletenessError(f"unknown verdict: {value!r}")


class FailureKind(str, Enum):
    """Typed failure kinds rejected by the completeness oracle."""

    OPEN_PAGE = "open_page"
    OVERLAPPING_PARTITION = "overlapping_partition"
    GAPPED_PARTITION = "gapped_partition"
    MUTABLE_CUTOFF = "mutable_cutoff"
    METADATA_AS_BODY = "metadata_as_body"
    FAILED_FINAL = "failed_final"
    COUNT_DRIFT = "count_drift"
    STALE_SUCCESS_REGISTRY = "stale_success_registry"
    RECONCILIATION = "reconciliation"
    DOCUMENT_IDENTITY = "document_identity"
    OFFICIAL_AUTHORITY = "official_authority"
    RESUME = "resume"
    DELTA = "delta"
    SCHEMA = "schema"
    OTHER = "other"

    @classmethod
    def coerce(cls, value: Any) -> "FailureKind":
        if isinstance(value, FailureKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "open_pages": cls.OPEN_PAGE,
            "unresolved_page": cls.OPEN_PAGE,
            "overlap": cls.OVERLAPPING_PARTITION,
            "overlapping": cls.OVERLAPPING_PARTITION,
            "gap": cls.GAPPED_PARTITION,
            "gapped": cls.GAPPED_PARTITION,
            "partition_gap": cls.GAPPED_PARTITION,
            "mutable": cls.MUTABLE_CUTOFF,
            "cutoff": cls.MUTABLE_CUTOFF,
            "metadata_body": cls.METADATA_AS_BODY,
            "metadata_as_full_text": cls.METADATA_AS_BODY,
            "failed": cls.FAILED_FINAL,
            "failed_final_item": cls.FAILED_FINAL,
            "drift": cls.COUNT_DRIFT,
            "unexplained_count_drift": cls.COUNT_DRIFT,
            "stale_success": cls.STALE_SUCCESS_REGISTRY,
            "stale_registry": cls.STALE_SUCCESS_REGISTRY,
            "success_registry": cls.STALE_SUCCESS_REGISTRY,
            "arith": cls.RECONCILIATION,
            "identity": cls.DOCUMENT_IDENTITY,
            "authority": cls.OFFICIAL_AUTHORITY,
        }
        if text in aliases:
            return aliases[text]
        for item in cls:
            if item.value == text or item.name.lower() == text:
                return item
        return cls.OTHER


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterCompletenessError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise FederalRegisterCompletenessError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise FederalRegisterCompletenessError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederalRegisterCompletenessError(f"{name} must be an integer")
    if value < 0:
        raise FederalRegisterCompletenessError(f"{name} must be >= 0")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise FederalRegisterCompletenessError(f"{name} must be a boolean")
    return value


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FederalRegisterCompletenessError(f"{name} must be a mapping")
    return value


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise FederalRegisterCompletenessError(f"{name} must be a list")
    return value


# ---------------------------------------------------------------------------
# Page and partition records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageReceipt:
    """One official API result page within a date partition."""

    page_id: str
    page_number: int
    status: PageStatus
    cursor: Optional[str] = None
    response_hash: Optional[str] = None
    result_count: int = 0
    document_numbers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "page_id", _require_non_empty_str(self.page_id, "page_id", maximum=128)
        )
        page_number = _require_non_negative_int(self.page_number, "page_number")
        if page_number < 1:
            raise OpenPageError("page_number must be >= 1")
        object.__setattr__(self, "page_number", page_number)
        object.__setattr__(self, "status", PageStatus.coerce(self.status))
        if self.cursor is not None and str(self.cursor).strip():
            object.__setattr__(
                self,
                "cursor",
                _require_non_empty_str(self.cursor, "cursor", maximum=512),
            )
        else:
            object.__setattr__(self, "cursor", None)
        if self.response_hash is not None and str(self.response_hash).strip():
            object.__setattr__(
                self,
                "response_hash",
                normalize_sha256(self.response_hash, name="response_hash"),
            )
        else:
            object.__setattr__(self, "response_hash", None)
        object.__setattr__(
            self,
            "result_count",
            _require_non_negative_int(self.result_count, "result_count"),
        )
        docs = tuple(
            validate_document_number(item, name=f"document_numbers[{i}]")
            for i, item in enumerate(self.document_numbers or ())
        )
        object.__setattr__(self, "document_numbers", docs)
        # Closed pages must carry a response hash.
        if self.status.is_closed and self.status is not PageStatus.SKIPPED:
            if not self.response_hash:
                raise OpenPageError(
                    f"page {self.page_id!r} status={self.status.value} requires response_hash"
                )

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "page_number": self.page_number,
            "status": self.status.value,
            "cursor": self.cursor,
            "response_hash": self.response_hash,
            "result_count": self.result_count,
            "document_numbers": list(self.document_numbers),
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping, *, context: str = "page") -> "PageReceipt":
        raw = _as_mapping(value, context)
        docs = raw.get("document_numbers") or ()
        if isinstance(docs, list):
            docs = tuple(docs)
        return cls(
            page_id=raw.get("page_id", ""),
            page_number=raw.get("page_number", 0),
            status=raw.get("status", PageStatus.OPEN),
            cursor=raw.get("cursor"),
            response_hash=raw.get("response_hash"),
            result_count=raw.get("result_count", 0),
            document_numbers=docs,
        )


@dataclass(frozen=True)
class DatePartition:
    """One non-overlapping publication-date partition of the official inventory."""

    partition_id: str
    start_date: str
    end_date: str
    status: PartitionStatus
    api_total: int
    enumerated: int
    fetched: int
    duplicate: int = 0
    excluded: int = 0
    quarantined: int = 0
    failed_final: int = 0
    pages: tuple[PageReceipt, ...] = ()
    document_numbers: tuple[str, ...] = ()
    body_text_dispositions: Mapping[str, int] = field(default_factory=dict)
    year_month: Optional[str] = None
    official_source_url: str = FEDERAL_REGISTER_DOCUMENTS_API
    response_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "partition_id",
            _require_non_empty_str(self.partition_id, "partition_id", maximum=128),
        )
        start = validate_calendar_date(self.start_date, name="start_date")
        end = validate_calendar_date(self.end_date, name="end_date")
        if start > end:
            raise DatePartitionError(
                f"partition {self.partition_id!r}: start_date {start} > end_date {end}"
            )
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        object.__setattr__(self, "status", PartitionStatus.coerce(self.status))
        for field_name in (
            "api_total",
            "enumerated",
            "fetched",
            "duplicate",
            "excluded",
            "quarantined",
            "failed_final",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(getattr(self, field_name), field_name),
            )
        pages = tuple(
            item if isinstance(item, PageReceipt) else PageReceipt.from_mapping(item)
            for item in (self.pages or ())
        )
        object.__setattr__(self, "pages", pages)
        docs = tuple(
            validate_document_number(item, name=f"document_numbers[{i}]")
            for i, item in enumerate(self.document_numbers or ())
        )
        object.__setattr__(self, "document_numbers", docs)
        object.__setattr__(
            self,
            "body_text_dispositions",
            MappingProxyType(
                disposition_count_map(
                    self.body_text_dispositions, name="body_text_dispositions"
                )
            ),
        )
        if self.year_month is not None and str(self.year_month).strip():
            object.__setattr__(
                self, "year_month", validate_year_month(self.year_month)
            )
        else:
            # Derive year_month when the partition sits inside one calendar month.
            if start[:7] == end[:7]:
                object.__setattr__(self, "year_month", start[:7])
            else:
                object.__setattr__(self, "year_month", None)
        object.__setattr__(
            self,
            "official_source_url",
            validate_official_url(
                self.official_source_url or FEDERAL_REGISTER_DOCUMENTS_API,
                name="official_source_url",
            ),
        )
        hashes = tuple(
            normalize_sha256(item, name=f"response_hashes[{i}]")
            for i, item in enumerate(self.response_hashes or ())
        )
        object.__setattr__(self, "response_hashes", hashes)

    @property
    def start(self) -> date:
        return parse_calendar_date(self.start_date)

    @property
    def end(self) -> date:
        return parse_calendar_date(self.end_date)

    @property
    def accounted(self) -> int:
        return (
            self.fetched
            + self.duplicate
            + self.excluded
            + self.quarantined
            + self.failed_final
        )

    @property
    def open_pages(self) -> tuple[PageReceipt, ...]:
        return tuple(page for page in self.pages if page.is_open)

    @property
    def pages_closed(self) -> bool:
        if not self.pages:
            # No page ledger is only acceptable for empty partitions.
            return self.enumerated == 0 and self.api_total == 0
        return all(not page.is_open for page in self.pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "status": self.status.value,
            "api_total": self.api_total,
            "enumerated": self.enumerated,
            "fetched": self.fetched,
            "duplicate": self.duplicate,
            "excluded": self.excluded,
            "quarantined": self.quarantined,
            "failed_final": self.failed_final,
            "pages": [page.to_dict() for page in self.pages],
            "document_numbers": list(self.document_numbers),
            "body_text_dispositions": dict(self.body_text_dispositions),
            "year_month": self.year_month,
            "official_source_url": self.official_source_url,
            "response_hashes": list(self.response_hashes),
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "partition"
    ) -> "DatePartition":
        raw = _as_mapping(value, context)
        pages_raw = raw.get("pages") or ()
        docs = raw.get("document_numbers") or ()
        hashes = raw.get("response_hashes") or ()
        if isinstance(docs, list):
            docs = tuple(docs)
        if isinstance(hashes, list):
            hashes = tuple(hashes)
        return cls(
            partition_id=raw.get("partition_id", raw.get("receipt_id", "")),
            start_date=raw.get("start_date", raw.get("partition_start", "")),
            end_date=raw.get("end_date", raw.get("partition_end", "")),
            status=raw.get("status", PartitionStatus.PENDING),
            api_total=raw.get("api_total", 0),
            enumerated=raw.get("enumerated", 0),
            fetched=raw.get("fetched", 0),
            duplicate=raw.get("duplicate", 0),
            excluded=raw.get("excluded", 0),
            quarantined=raw.get("quarantined", 0),
            failed_final=raw.get("failed_final", 0),
            pages=tuple(pages_raw),
            document_numbers=docs,
            body_text_dispositions=raw.get("body_text_dispositions") or {},
            year_month=raw.get("year_month"),
            official_source_url=raw.get(
                "official_source_url", FEDERAL_REGISTER_DOCUMENTS_API
            ),
            response_hashes=hashes,
        )


# ---------------------------------------------------------------------------
# Document disposition and registry records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentDispositionRecord:
    """Per-document body-text disposition under the sealed cutoff."""

    document_number: str
    publication_date: str
    disposition: BodyTextDisposition
    text: str = ""
    abstract: str = ""
    legal_id: Optional[str] = None

    def __post_init__(self) -> None:
        doc = validate_document_number(self.document_number)
        pub = validate_calendar_date(self.publication_date, name="publication_date")
        object.__setattr__(self, "document_number", doc)
        object.__setattr__(self, "publication_date", pub)
        try:
            disp = validate_body_text_disposition_fields(
                disposition=self.disposition,
                text=self.text,
                abstract=self.abstract,
            )
        except BodyTextDispositionError as exc:
            raise MetadataAsBodyError(str(exc)) from exc
        object.__setattr__(self, "disposition", disp)
        object.__setattr__(self, "text", str(self.text or ""))
        object.__setattr__(self, "abstract", str(self.abstract or ""))
        if self.legal_id is not None and str(self.legal_id).strip():
            object.__setattr__(
                self, "legal_id", _require_non_empty_str(self.legal_id, "legal_id")
            )
        else:
            object.__setattr__(self, "legal_id", build_legal_id(doc, pub))

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "publication_date": self.publication_date,
            "disposition": self.disposition.value,
            "text": self.text,
            "abstract": self.abstract,
            "legal_id": self.legal_id,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "document"
    ) -> "DocumentDispositionRecord":
        raw = _as_mapping(value, context)
        return cls(
            document_number=raw.get("document_number", ""),
            publication_date=raw.get("publication_date", ""),
            disposition=raw.get(
                "disposition",
                raw.get("text_availability", BodyTextDisposition.UNAVAILABLE),
            ),
            text=raw.get("text", ""),
            abstract=raw.get("abstract", ""),
            legal_id=raw.get("legal_id"),
        )


@dataclass(frozen=True)
class SuccessRegistryEntry:
    """One success-registry row (must not mark incomplete frontiers success)."""

    entry_id: str
    status: str
    partition_id: Optional[str] = None
    document_number: Optional[str] = None
    frontier_closed: bool = False
    failed_final: int = 0
    open_pages: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entry_id",
            _require_non_empty_str(self.entry_id, "entry_id", maximum=128),
        )
        object.__setattr__(
            self,
            "status",
            _require_non_empty_str(self.status, "status", maximum=64).lower(),
        )
        if self.partition_id is not None and str(self.partition_id).strip():
            object.__setattr__(
                self,
                "partition_id",
                _require_non_empty_str(self.partition_id, "partition_id", maximum=128),
            )
        else:
            object.__setattr__(self, "partition_id", None)
        if self.document_number is not None and str(self.document_number).strip():
            object.__setattr__(
                self,
                "document_number",
                validate_document_number(self.document_number),
            )
        else:
            object.__setattr__(self, "document_number", None)
        object.__setattr__(
            self, "frontier_closed", _require_bool(self.frontier_closed, "frontier_closed")
        )
        object.__setattr__(
            self,
            "failed_final",
            _require_non_negative_int(self.failed_final, "failed_final"),
        )
        object.__setattr__(
            self, "open_pages", _require_non_negative_int(self.open_pages, "open_pages")
        )
        object.__setattr__(self, "notes", str(self.notes or ""))

    @property
    def claims_success(self) -> bool:
        return self.status in {"success", "complete", "closed", "ok", "pass"}

    @property
    def is_stale_success(self) -> bool:
        """True when success is claimed despite incomplete frontier evidence."""

        if not self.claims_success:
            return False
        if not self.frontier_closed:
            return True
        if self.failed_final > 0:
            return True
        if self.open_pages > 0:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "status": self.status,
            "partition_id": self.partition_id,
            "document_number": self.document_number,
            "frontier_closed": self.frontier_closed,
            "failed_final": self.failed_final,
            "open_pages": self.open_pages,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(
        cls, value: JsonMapping, *, context: str = "registry_entry"
    ) -> "SuccessRegistryEntry":
        raw = _as_mapping(value, context)
        return cls(
            entry_id=raw.get("entry_id", raw.get("id", "")),
            status=raw.get("status", "unknown"),
            partition_id=raw.get("partition_id"),
            document_number=raw.get("document_number"),
            frontier_closed=raw.get("frontier_closed", False),
            failed_final=raw.get("failed_final", 0),
            open_pages=raw.get("open_pages", 0),
            notes=raw.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Completion receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletionReceipt:
    """Cutoff-bound Federal Register completeness receipt for one run/cohort."""

    receipt_id: str
    observation_cutoff: str
    partitions: tuple[DatePartition, ...]
    range_start: str
    range_end: str
    official_total: int
    enumerated: int
    fetched: int
    duplicate: int = 0
    excluded: int = 0
    quarantined: int = 0
    failed_final: int = 0
    frontier_closed: bool = False
    inventory_authority: OfficialAuthority = OfficialAuthority.FEDERAL_REGISTER_API
    release_point: Optional[str] = None
    documents: tuple[DocumentDispositionRecord, ...] = ()
    success_registry: tuple[SuccessRegistryEntry, ...] = ()
    delta_start_inclusive: str = LEGACY_DELTA_START_INCLUSIVE
    legacy_baseline_end_inclusive: str = LEGACY_BASELINE_END_INCLUSIVE
    previous_public_pin: str = PREVIOUS_PUBLIC_PIN
    unexplained_count_drift: int = 0
    count_drift_explanation: Optional[str] = None
    resume_checkpoint_id: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    task_id: str = COMPLETENESS_TASK_ID
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_non_empty_str(self.receipt_id, "receipt_id", maximum=128),
        )
        # Mutable cutoffs fail closed immediately.
        try:
            cutoff = require_immutable_observation_cutoff(self.observation_cutoff)
        except MutableCutoffError:
            raise
        object.__setattr__(self, "observation_cutoff", cutoff)
        start = validate_calendar_date(self.range_start, name="range_start")
        end = validate_calendar_date(self.range_end, name="range_end")
        if start > end:
            raise DatePartitionError(
                f"range_start {start} must be <= range_end {end}"
            )
        object.__setattr__(self, "range_start", start)
        object.__setattr__(self, "range_end", end)
        for field_name in (
            "official_total",
            "enumerated",
            "fetched",
            "duplicate",
            "excluded",
            "quarantined",
            "failed_final",
            "unexplained_count_drift",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_non_negative_int(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self, "frontier_closed", _require_bool(self.frontier_closed, "frontier_closed")
        )
        object.__setattr__(
            self,
            "inventory_authority",
            OfficialAuthority.coerce(self.inventory_authority),
        )
        if not self.inventory_authority.is_inventory_authority:
            raise FederalRegisterCompletenessError(
                "inventory_authority must be FederalRegister.gov API"
            )
        if self.release_point is not None and str(self.release_point).strip():
            object.__setattr__(
                self,
                "release_point",
                require_exact_release_point(self.release_point),
            )
        else:
            object.__setattr__(self, "release_point", cutoff_release_point(cutoff))
        partitions = tuple(
            item if isinstance(item, DatePartition) else DatePartition.from_mapping(item)
            for item in (self.partitions or ())
        )
        object.__setattr__(self, "partitions", partitions)
        documents = tuple(
            item
            if isinstance(item, DocumentDispositionRecord)
            else DocumentDispositionRecord.from_mapping(item)
            for item in (self.documents or ())
        )
        object.__setattr__(self, "documents", documents)
        registry = tuple(
            item
            if isinstance(item, SuccessRegistryEntry)
            else SuccessRegistryEntry.from_mapping(item)
            for item in (self.success_registry or ())
        )
        object.__setattr__(self, "success_registry", registry)
        object.__setattr__(
            self,
            "delta_start_inclusive",
            validate_calendar_date(
                self.delta_start_inclusive, name="delta_start_inclusive"
            ),
        )
        object.__setattr__(
            self,
            "legacy_baseline_end_inclusive",
            validate_calendar_date(
                self.legacy_baseline_end_inclusive,
                name="legacy_baseline_end_inclusive",
            ),
        )
        object.__setattr__(
            self,
            "previous_public_pin",
            _require_non_empty_str(
                self.previous_public_pin, "previous_public_pin", maximum=128
            ),
        )
        if is_mutable_cutoff(self.previous_public_pin):
            raise MutableCutoffError(
                f"previous_public_pin must be immutable, got {self.previous_public_pin!r}"
            )
        if self.count_drift_explanation is not None:
            object.__setattr__(
                self,
                "count_drift_explanation",
                str(self.count_drift_explanation).strip() or None,
            )
        if self.resume_checkpoint_id is not None and str(
            self.resume_checkpoint_id
        ).strip():
            object.__setattr__(
                self,
                "resume_checkpoint_id",
                _require_non_empty_str(
                    self.resume_checkpoint_id, "resume_checkpoint_id", maximum=128
                ),
            )
        else:
            object.__setattr__(self, "resume_checkpoint_id", None)
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version", maximum=128),
        )
        object.__setattr__(
            self, "task_id", _require_non_empty_str(self.task_id, "task_id", maximum=32)
        )
        object.__setattr__(self, "notes", str(self.notes or ""))

    @property
    def accounted(self) -> int:
        return (
            self.fetched
            + self.duplicate
            + self.excluded
            + self.quarantined
            + self.failed_final
        )

    @property
    def open_pages(self) -> tuple[PageReceipt, ...]:
        open_pages: list[PageReceipt] = []
        for partition in self.partitions:
            open_pages.extend(partition.open_pages)
        return tuple(open_pages)

    @property
    def open_page_count(self) -> int:
        return len(self.open_pages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "observation_cutoff": self.observation_cutoff,
            "partitions": [p.to_dict() for p in self.partitions],
            "range_start": self.range_start,
            "range_end": self.range_end,
            "official_total": self.official_total,
            "enumerated": self.enumerated,
            "fetched": self.fetched,
            "duplicate": self.duplicate,
            "excluded": self.excluded,
            "quarantined": self.quarantined,
            "failed_final": self.failed_final,
            "frontier_closed": self.frontier_closed,
            "inventory_authority": self.inventory_authority.value,
            "release_point": self.release_point,
            "documents": [d.to_dict() for d in self.documents],
            "success_registry": [e.to_dict() for e in self.success_registry],
            "delta_start_inclusive": self.delta_start_inclusive,
            "legacy_baseline_end_inclusive": self.legacy_baseline_end_inclusive,
            "previous_public_pin": self.previous_public_pin,
            "unexplained_count_drift": self.unexplained_count_drift,
            "count_drift_explanation": self.count_drift_explanation,
            "resume_checkpoint_id": self.resume_checkpoint_id,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "notes": self.notes,
        }

    @classmethod
    def from_mapping(cls, value: JsonMapping) -> "CompletionReceipt":
        raw = _as_mapping(value, "completion_receipt")
        return cls(
            receipt_id=raw.get("receipt_id", ""),
            observation_cutoff=raw.get(
                "observation_cutoff", DEFAULT_OBSERVATION_CUTOFF
            ),
            partitions=tuple(raw.get("partitions") or ()),
            range_start=raw.get("range_start", ""),
            range_end=raw.get("range_end", ""),
            official_total=raw.get("official_total", 0),
            enumerated=raw.get("enumerated", 0),
            fetched=raw.get("fetched", 0),
            duplicate=raw.get("duplicate", 0),
            excluded=raw.get("excluded", 0),
            quarantined=raw.get("quarantined", 0),
            failed_final=raw.get("failed_final", 0),
            frontier_closed=raw.get("frontier_closed", False),
            inventory_authority=raw.get(
                "inventory_authority", OfficialAuthority.FEDERAL_REGISTER_API
            ),
            release_point=raw.get("release_point"),
            documents=tuple(raw.get("documents") or ()),
            success_registry=tuple(raw.get("success_registry") or ()),
            delta_start_inclusive=raw.get(
                "delta_start_inclusive", LEGACY_DELTA_START_INCLUSIVE
            ),
            legacy_baseline_end_inclusive=raw.get(
                "legacy_baseline_end_inclusive", LEGACY_BASELINE_END_INCLUSIVE
            ),
            previous_public_pin=raw.get(
                "previous_public_pin", PREVIOUS_PUBLIC_PIN
            ),
            unexplained_count_drift=raw.get("unexplained_count_drift", 0),
            count_drift_explanation=raw.get("count_drift_explanation"),
            resume_checkpoint_id=raw.get("resume_checkpoint_id"),
            schema_version=raw.get("schema_version", SCHEMA_VERSION),
            task_id=raw.get("task_id", COMPLETENESS_TASK_ID),
            notes=raw.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Oracle result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletenessFinding:
    """One typed finding from the completeness oracle."""

    kind: FailureKind
    message: str
    path: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FailureKind.coerce(self.kind))
        object.__setattr__(
            self, "message", _require_non_empty_str(self.message, "message", maximum=2048)
        )
        object.__setattr__(self, "path", str(self.path or ""))
        if not isinstance(self.details, Mapping):
            raise FederalRegisterCompletenessError("details must be a mapping")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "path": self.path,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class CompletenessResult:
    """Oracle evaluation outcome for one completion receipt."""

    verdict: CompletenessVerdict
    receipt_id: str
    findings: tuple[CompletenessFinding, ...]
    observation_cutoff: str
    frontier_closed: bool
    open_page_count: int
    failed_final: int
    unexplained_count_drift: int
    accounted: int
    enumerated: int
    official_total: int

    @property
    def passed(self) -> bool:
        return self.verdict is CompletenessVerdict.PASS

    @property
    def failure_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({finding.kind.value for finding in self.findings}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "receipt_id": self.receipt_id,
            "findings": [f.to_dict() for f in self.findings],
            "failure_kinds": list(self.failure_kinds),
            "observation_cutoff": self.observation_cutoff,
            "frontier_closed": self.frontier_closed,
            "open_page_count": self.open_page_count,
            "failed_final": self.failed_final,
            "unexplained_count_drift": self.unexplained_count_drift,
            "accounted": self.accounted,
            "enumerated": self.enumerated,
            "official_total": self.official_total,
        }


# ---------------------------------------------------------------------------
# Partition geometry
# ---------------------------------------------------------------------------


def validate_date_partitions(
    partitions: Sequence[DatePartition],
    *,
    range_start: str,
    range_end: str,
    require_full_coverage: bool = True,
) -> list[CompletenessFinding]:
    """Reject overlapping or gapped date partitions relative to the range."""

    findings: list[CompletenessFinding] = []
    if not partitions:
        if require_full_coverage:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.GAPPED_PARTITION,
                    message="no date partitions cover the inventory range",
                    path="partitions",
                )
            )
        return findings

    start = parse_calendar_date(range_start, name="range_start")
    end = parse_calendar_date(range_end, name="range_end")
    ordered = sorted(partitions, key=lambda p: (p.start, p.end, p.partition_id))

    # Overlap detection (half-open adjacency is required: next.start == prev.end + 1 day).
    for idx in range(len(ordered) - 1):
        left = ordered[idx]
        right = ordered[idx + 1]
        if right.start <= left.end:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.OVERLAPPING_PARTITION,
                    message=(
                        f"partitions overlap: {left.partition_id!r} "
                        f"[{left.start_date}..{left.end_date}] and "
                        f"{right.partition_id!r} [{right.start_date}..{right.end_date}]"
                    ),
                    path=f"partitions[{left.partition_id}]",
                    details={
                        "left": left.partition_id,
                        "right": right.partition_id,
                    },
                )
            )

    if require_full_coverage:
        # Gap / coverage detection against the declared range.
        if ordered[0].start > start:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.GAPPED_PARTITION,
                    message=(
                        f"coverage gap before first partition: range starts "
                        f"{start.isoformat()} but first partition starts "
                        f"{ordered[0].start_date}"
                    ),
                    path=f"partitions[{ordered[0].partition_id}]",
                )
            )
        if ordered[-1].end < end:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.GAPPED_PARTITION,
                    message=(
                        f"coverage gap after last partition: range ends "
                        f"{end.isoformat()} but last partition ends "
                        f"{ordered[-1].end_date}"
                    ),
                    path=f"partitions[{ordered[-1].partition_id}]",
                )
            )
        for idx in range(len(ordered) - 1):
            left = ordered[idx]
            right = ordered[idx + 1]
            expected_next = left.end + timedelta(days=1)
            if right.start > expected_next:
                findings.append(
                    CompletenessFinding(
                        kind=FailureKind.GAPPED_PARTITION,
                        message=(
                            f"coverage gap between {left.partition_id!r} "
                            f"(ends {left.end_date}) and {right.partition_id!r} "
                            f"(starts {right.start_date}); expected next start "
                            f"{expected_next.isoformat()}"
                        ),
                        path=f"partitions[{left.partition_id}]",
                        details={
                            "left": left.partition_id,
                            "right": right.partition_id,
                            "expected_next_start": expected_next.isoformat(),
                        },
                    )
                )
            # Also reject partitions that extend outside the declared range.
        for partition in ordered:
            if partition.start < start or partition.end > end:
                findings.append(
                    CompletenessFinding(
                        kind=FailureKind.GAPPED_PARTITION,
                        message=(
                            f"partition {partition.partition_id!r} "
                            f"[{partition.start_date}..{partition.end_date}] "
                            f"extends outside range [{start.isoformat()}..{end.isoformat()}]"
                        ),
                        path=f"partitions[{partition.partition_id}]",
                    )
                )

    return findings


def validate_page_closure(
    partitions: Sequence[DatePartition],
) -> list[CompletenessFinding]:
    """Reject open / unresolved API result pages."""

    findings: list[CompletenessFinding] = []
    for partition in partitions:
        for page in partition.open_pages:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.OPEN_PAGE,
                    message=(
                        f"open page {page.page_id!r} status={page.status.value} "
                        f"in partition {partition.partition_id!r}"
                    ),
                    path=f"partitions[{partition.partition_id}].pages[{page.page_id}]",
                    details={
                        "page_id": page.page_id,
                        "status": page.status.value,
                        "partition_id": partition.partition_id,
                    },
                )
            )
        if (
            partition.status.is_closed
            and partition.enumerated > 0
            and not partition.pages
        ):
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.OPEN_PAGE,
                    message=(
                        f"closed partition {partition.partition_id!r} has enumerated "
                        f"documents but no page ledger"
                    ),
                    path=f"partitions[{partition.partition_id}].pages",
                )
            )
    return findings


def validate_partition_reconciliation(
    partition: DatePartition,
) -> list[CompletenessFinding]:
    """Require per-partition disposition arithmetic and API-total alignment."""

    findings: list[CompletenessFinding] = []
    if partition.enumerated != partition.accounted:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.RECONCILIATION,
                message=(
                    f"partition {partition.partition_id!r} reconciliation failed: "
                    f"enumerated={partition.enumerated} != "
                    f"fetched+duplicate+excluded+quarantined+failed_final="
                    f"{partition.accounted}"
                ),
                path=f"partitions[{partition.partition_id}]",
                details={
                    "enumerated": partition.enumerated,
                    "accounted": partition.accounted,
                },
            )
        )
    if partition.api_total != partition.enumerated:
        # Unexplained drift at partition level.
        findings.append(
            CompletenessFinding(
                kind=FailureKind.COUNT_DRIFT,
                message=(
                    f"partition {partition.partition_id!r} count drift: "
                    f"api_total={partition.api_total} != enumerated={partition.enumerated}"
                ),
                path=f"partitions[{partition.partition_id}]",
                details={
                    "api_total": partition.api_total,
                    "enumerated": partition.enumerated,
                    "drift": abs(partition.api_total - partition.enumerated),
                },
            )
        )
    if partition.status.is_closed and partition.failed_final > 0:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.FAILED_FINAL,
                message=(
                    f"closed partition {partition.partition_id!r} has "
                    f"failed_final={partition.failed_final}"
                ),
                path=f"partitions[{partition.partition_id}].failed_final",
                details={"failed_final": partition.failed_final},
            )
        )
    return findings


def validate_receipt_reconciliation(
    receipt: CompletionReceipt,
) -> list[CompletenessFinding]:
    """Require top-level disposition arithmetic and official-total alignment."""

    findings: list[CompletenessFinding] = []
    if receipt.enumerated != receipt.accounted:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.RECONCILIATION,
                message=(
                    f"receipt reconciliation failed: enumerated={receipt.enumerated} "
                    f"!= fetched+duplicate+excluded+quarantined+failed_final="
                    f"{receipt.accounted}"
                ),
                path="enumerated",
                details={
                    "enumerated": receipt.enumerated,
                    "accounted": receipt.accounted,
                },
            )
        )

    # Partition sums must match receipt totals.
    sum_enumerated = sum(p.enumerated for p in receipt.partitions)
    sum_fetched = sum(p.fetched for p in receipt.partitions)
    sum_failed = sum(p.failed_final for p in receipt.partitions)
    if receipt.partitions and sum_enumerated != receipt.enumerated:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.RECONCILIATION,
                message=(
                    f"partition enumerated sum {sum_enumerated} != "
                    f"receipt enumerated {receipt.enumerated}"
                ),
                path="partitions",
            )
        )
    if receipt.partitions and sum_fetched != receipt.fetched:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.RECONCILIATION,
                message=(
                    f"partition fetched sum {sum_fetched} != "
                    f"receipt fetched {receipt.fetched}"
                ),
                path="partitions",
            )
        )
    if receipt.partitions and sum_failed != receipt.failed_final:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.RECONCILIATION,
                message=(
                    f"partition failed_final sum {sum_failed} != "
                    f"receipt failed_final {receipt.failed_final}"
                ),
                path="partitions",
            )
        )

    # Official total vs enumerated with optional explained drift.
    drift = abs(receipt.official_total - receipt.enumerated)
    if drift != 0:
        explained = (
            receipt.unexplained_count_drift == 0
            and receipt.count_drift_explanation
            and str(receipt.count_drift_explanation).strip()
        )
        # Explicit unexplained_count_drift field must match observed drift
        # when provided as the residual, otherwise fail.
        if receipt.unexplained_count_drift > 0 or not explained:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.COUNT_DRIFT,
                    message=(
                        f"unexplained count drift: official_total={receipt.official_total} "
                        f"enumerated={receipt.enumerated} drift={drift} "
                        f"unexplained_count_drift={receipt.unexplained_count_drift}"
                    ),
                    path="official_total",
                    details={
                        "official_total": receipt.official_total,
                        "enumerated": receipt.enumerated,
                        "drift": drift,
                        "unexplained_count_drift": receipt.unexplained_count_drift,
                        "explanation": receipt.count_drift_explanation,
                    },
                )
            )
    elif receipt.unexplained_count_drift > 0:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.COUNT_DRIFT,
                message=(
                    f"unexplained_count_drift={receipt.unexplained_count_drift} "
                    "but official_total matches enumerated"
                ),
                path="unexplained_count_drift",
            )
        )
    return findings


def validate_failed_final(receipt: CompletionReceipt) -> list[CompletenessFinding]:
    """Reject failed-final items for closed/publication cohorts."""

    findings: list[CompletenessFinding] = []
    if receipt.failed_final > 0:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.FAILED_FINAL,
                message=(
                    f"failed_final={receipt.failed_final} blocks closed completeness; "
                    "failed-final items create refill work and prevent publication"
                ),
                path="failed_final",
                details={"failed_final": receipt.failed_final},
            )
        )
    if receipt.frontier_closed and receipt.failed_final != 0:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.FAILED_FINAL,
                message="frontier_closed=true requires failed_final=0",
                path="frontier_closed",
            )
        )
    for doc in receipt.documents:
        if doc.disposition is BodyTextDisposition.FAILED_FINAL:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.FAILED_FINAL,
                    message=(
                        f"document {doc.document_number!r} has "
                        f"disposition=failed_final"
                    ),
                    path=f"documents[{doc.document_number}]",
                )
            )
    # Body disposition counts on partitions may also declare failed_final.
    for partition in receipt.partitions:
        failed_disp = partition.body_text_dispositions.get(
            BodyTextDisposition.FAILED_FINAL.value, 0
        )
        if failed_disp > 0:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.FAILED_FINAL,
                    message=(
                        f"partition {partition.partition_id!r} body disposition "
                        f"failed_final={failed_disp}"
                    ),
                    path=f"partitions[{partition.partition_id}].body_text_dispositions",
                )
            )
    return findings


def validate_metadata_as_body(
    receipt: CompletionReceipt,
) -> list[CompletenessFinding]:
    """Reject metadata/abstract masquerading as body text."""

    findings: list[CompletenessFinding] = []
    for doc in receipt.documents:
        disp = doc.disposition
        body = (doc.text or "").strip()
        if disp in BODY_BEARING_DISPOSITIONS:
            if not body:
                findings.append(
                    CompletenessFinding(
                        kind=FailureKind.METADATA_AS_BODY,
                        message=(
                            f"document {doc.document_number!r} disposition="
                            f"{disp.value} requires non-empty body text"
                        ),
                        path=f"documents[{doc.document_number}]",
                    )
                )
            continue
        if body and len(body) > METADATA_AS_BODY_CHAR_THRESHOLD:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.METADATA_AS_BODY,
                    message=(
                        f"document {doc.document_number!r} disposition="
                        f"{disp.value} carries long body text "
                        f"({len(body)} chars); metadata must not be body text"
                    ),
                    path=f"documents[{doc.document_number}].text",
                    details={
                        "disposition": disp.value,
                        "text_length": len(body),
                        "threshold": METADATA_AS_BODY_CHAR_THRESHOLD,
                    },
                )
            )
        elif (
            disp is BodyTextDisposition.METADATA_ONLY
            and body
            and len(body) > 64
            and not (doc.abstract or "").strip()
        ):
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.METADATA_AS_BODY,
                    message=(
                        f"document {doc.document_number!r} metadata_only carries "
                        f"substantial body text ({len(body)} chars)"
                    ),
                    path=f"documents[{doc.document_number}].text",
                )
            )
    return findings


def validate_success_registry(
    receipt: CompletionReceipt,
) -> list[CompletenessFinding]:
    """Reject stale success registries that promote incomplete work."""

    findings: list[CompletenessFinding] = []
    for entry in receipt.success_registry:
        if entry.is_stale_success:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.STALE_SUCCESS_REGISTRY,
                    message=(
                        f"stale success registry entry {entry.entry_id!r} claims "
                        f"status={entry.status!r} while frontier_closed="
                        f"{entry.frontier_closed}, failed_final={entry.failed_final}, "
                        f"open_pages={entry.open_pages}"
                    ),
                    path=f"success_registry[{entry.entry_id}]",
                    details=entry.to_dict(),
                )
            )
    # Receipt-level success claim with open work is also stale.
    if receipt.frontier_closed:
        if receipt.open_page_count > 0 or receipt.failed_final > 0:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.STALE_SUCCESS_REGISTRY,
                    message=(
                        "frontier_closed=true is stale while open pages or "
                        "failed-final items remain"
                    ),
                    path="frontier_closed",
                    details={
                        "open_page_count": receipt.open_page_count,
                        "failed_final": receipt.failed_final,
                    },
                )
            )
    for partition in receipt.partitions:
        if partition.status.is_closed and (
            partition.open_pages or partition.failed_final > 0
        ):
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.STALE_SUCCESS_REGISTRY,
                    message=(
                        f"partition {partition.partition_id!r} status=closed is stale "
                        f"with open_pages={len(partition.open_pages)} "
                        f"failed_final={partition.failed_final}"
                    ),
                    path=f"partitions[{partition.partition_id}].status",
                )
            )
    return findings


def validate_delta_rules(receipt: CompletionReceipt) -> list[CompletenessFinding]:
    """Require an explicit legacy-baseline delta through the sealed cutoff."""

    findings: list[CompletenessFinding] = []
    # Delta start must be the day after the legacy baseline end.
    legacy_end = parse_calendar_date(
        receipt.legacy_baseline_end_inclusive, name="legacy_baseline_end_inclusive"
    )
    delta_start = parse_calendar_date(
        receipt.delta_start_inclusive, name="delta_start_inclusive"
    )
    expected_delta_start = legacy_end + timedelta(days=1)
    if delta_start != expected_delta_start:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.DELTA,
                message=(
                    f"delta_start_inclusive {receipt.delta_start_inclusive} must be "
                    f"the day after legacy baseline end "
                    f"{receipt.legacy_baseline_end_inclusive} "
                    f"(expected {expected_delta_start.isoformat()})"
                ),
                path="delta_start_inclusive",
            )
        )
    # When the receipt range covers the delta window, range_start should not
    # precede the delta start without an explicit full-history note.
    range_start = parse_calendar_date(receipt.range_start)
    if range_start < delta_start and "full_history" not in (receipt.notes or "").lower():
        # Allow full-history inventories; otherwise require delta-aligned start
        # for cutoff-delta receipts.
        if receipt.range_start == LEGACY_DELTA_START_INCLUSIVE or range_start >= delta_start:
            pass
        # Only flag when the receipt claims to be a delta run via notes/id.
        rid = (receipt.receipt_id or "").lower()
        if "delta" in rid or "delta" in (receipt.notes or "").lower():
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.DELTA,
                    message=(
                        f"delta receipt range_start {receipt.range_start} precedes "
                        f"delta_start_inclusive {receipt.delta_start_inclusive}"
                    ),
                    path="range_start",
                )
            )
    cutoff_date = parse_calendar_date(receipt.observation_cutoff[:10])
    range_end = parse_calendar_date(receipt.range_end)
    if range_end > cutoff_date:
        findings.append(
            CompletenessFinding(
                kind=FailureKind.DELTA,
                message=(
                    f"range_end {receipt.range_end} exceeds observation cutoff "
                    f"date {cutoff_date.isoformat()}"
                ),
                path="range_end",
            )
        )
    return findings


def validate_resume_rules(receipt: CompletionReceipt) -> list[CompletenessFinding]:
    """Resume checkpoints must not promote partial frontiers to success."""

    findings: list[CompletenessFinding] = []
    if receipt.resume_checkpoint_id and receipt.frontier_closed:
        # Resume id present with closed frontier is fine when all gates pass;
        # reject only when open work remains.
        if receipt.open_page_count > 0 or receipt.failed_final > 0:
            findings.append(
                CompletenessFinding(
                    kind=FailureKind.RESUME,
                    message=(
                        f"resume checkpoint {receipt.resume_checkpoint_id!r} cannot "
                        "close while open pages or failed-final items remain"
                    ),
                    path="resume_checkpoint_id",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Oracle entry points
# ---------------------------------------------------------------------------


def evaluate_completion_receipt(
    receipt: CompletionReceipt | JsonMapping,
    *,
    policy: Optional[FederalRegisterSourcePolicy] = None,
    require_full_coverage: bool = True,
    raise_on_failure: bool = False,
) -> CompletenessResult:
    """Evaluate a completion receipt against the sealed completeness oracle.

    Returns a :class:`CompletenessResult`. When *raise_on_failure* is True and
    the verdict is fail, raises the first matching typed error.
    """

    if not isinstance(receipt, CompletionReceipt):
        # Mutable cutoff and metadata-as-body must surface as typed errors
        # during parse so callers (and fixture evaluation) can reject them.
        try:
            receipt = CompletionReceipt.from_mapping(receipt)
        except MutableCutoffError:
            raise
        except MetadataAsBodyError:
            raise
        except BodyTextDispositionError as exc:
            raise MetadataAsBodyError(str(exc)) from exc

    _ = policy if policy is not None else default_source_policy()
    findings: list[CompletenessFinding] = []

    # 1. Date partition geometry.
    findings.extend(
        validate_date_partitions(
            receipt.partitions,
            range_start=receipt.range_start,
            range_end=receipt.range_end,
            require_full_coverage=require_full_coverage,
        )
    )

    # 2. Page closure.
    findings.extend(validate_page_closure(receipt.partitions))

    # 3. Per-partition reconciliation / drift / failed-final.
    for partition in receipt.partitions:
        findings.extend(validate_partition_reconciliation(partition))

    # 4. Receipt-level reconciliation and count drift.
    findings.extend(validate_receipt_reconciliation(receipt))

    # 5. Failed-final items.
    findings.extend(validate_failed_final(receipt))

    # 6. Metadata as body text.
    findings.extend(validate_metadata_as_body(receipt))

    # 7. Stale success registries.
    findings.extend(validate_success_registry(receipt))

    # 8. Delta and resume rules.
    findings.extend(validate_delta_rules(receipt))
    findings.extend(validate_resume_rules(receipt))

    # Deduplicate findings by (kind, path, message).
    seen: set[tuple[str, str, str]] = set()
    unique: list[CompletenessFinding] = []
    for finding in findings:
        key = (finding.kind.value, finding.path, finding.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)

    verdict = (
        CompletenessVerdict.PASS if not unique else CompletenessVerdict.FAIL
    )
    result = CompletenessResult(
        verdict=verdict,
        receipt_id=receipt.receipt_id,
        findings=tuple(unique),
        observation_cutoff=receipt.observation_cutoff,
        frontier_closed=receipt.frontier_closed and not unique,
        open_page_count=receipt.open_page_count,
        failed_final=receipt.failed_final,
        unexplained_count_drift=receipt.unexplained_count_drift,
        accounted=receipt.accounted,
        enumerated=receipt.enumerated,
        official_total=receipt.official_total,
    )

    if raise_on_failure and not result.passed:
        raise_for_findings(result.findings)
    return result


def raise_for_findings(findings: Sequence[CompletenessFinding]) -> None:
    """Raise the most specific typed error for the first finding."""

    if not findings:
        return
    finding = findings[0]
    mapping = {
        FailureKind.OPEN_PAGE: OpenPageError,
        FailureKind.OVERLAPPING_PARTITION: DatePartitionError,
        FailureKind.GAPPED_PARTITION: DatePartitionError,
        FailureKind.MUTABLE_CUTOFF: MutableCutoffError,
        FailureKind.METADATA_AS_BODY: MetadataAsBodyError,
        FailureKind.FAILED_FINAL: FailedFinalError,
        FailureKind.COUNT_DRIFT: CountDriftError,
        FailureKind.STALE_SUCCESS_REGISTRY: StaleSuccessRegistryError,
        FailureKind.RECONCILIATION: ReconciliationError,
        FailureKind.RESUME: ResumeError,
        FailureKind.DELTA: DeltaError,
    }
    exc_type = mapping.get(finding.kind, FederalRegisterCompletenessError)
    raise exc_type(finding.message)


def assert_completion_closed(
    receipt: CompletionReceipt | JsonMapping,
    *,
    policy: Optional[FederalRegisterSourcePolicy] = None,
) -> CompletenessResult:
    """Assert that a receipt is fully closed; raise on any finding."""

    return evaluate_completion_receipt(
        receipt, policy=policy, require_full_coverage=True, raise_on_failure=True
    )


# ---------------------------------------------------------------------------
# Fixture load / evaluation
# ---------------------------------------------------------------------------


def load_completion_fixture_payload(
    path: Optional[PathLike] = None,
) -> dict[str, Any]:
    """Load the sealed completion-receipts fixture as a raw mapping."""

    fixture_path = Path(path) if path is not None else default_completion_fixture_path()
    if not fixture_path.is_file():
        raise FixtureSchemaError(f"completion fixture not found: {fixture_path}")
    try:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureSchemaError(f"completion fixture JSON is invalid: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise FixtureSchemaError("completion fixture root must be a JSON object")
    schema = raw.get("schema_version")
    if schema != FIXTURE_SCHEMA_VERSION:
        raise FixtureSchemaError(
            f"schema_version must be {FIXTURE_SCHEMA_VERSION!r}, got {schema!r}"
        )
    task_id = raw.get("task_id")
    if task_id != TASK_ID:
        raise FixtureSchemaError(f"task_id must be {TASK_ID!r}, got {task_id!r}")
    return dict(raw)


def expand_completion_fixture_cases(
    payload: Optional[JsonMapping] = None,
    *,
    path: Optional[PathLike] = None,
) -> list[dict[str, Any]]:
    """Return fixture cases (pass + adversarial fail recipes)."""

    if payload is None:
        payload = load_completion_fixture_payload(path)
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise FixtureSchemaError("cases must be a list")
    if not cases:
        raise FixtureSchemaError("cases must be non-empty")
    expanded: list[dict[str, Any]] = []
    for idx, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise FixtureSchemaError(f"cases[{idx}] must be a mapping")
        case_id = case.get("case_id")
        if not case_id:
            raise FixtureSchemaError(f"cases[{idx}].case_id is required")
        expected = CompletenessVerdict.coerce(case.get("expected_status", "fail"))
        expected_kinds = tuple(
            FailureKind.coerce(item).value
            for item in (case.get("expected_kinds") or ())
        )
        receipt_raw = case.get("receipt")
        if not isinstance(receipt_raw, Mapping):
            raise FixtureSchemaError(f"cases[{idx}].receipt must be a mapping")
        # Inject defaults from fixture header when omitted on the receipt.
        receipt = dict(receipt_raw)
        receipt.setdefault(
            "observation_cutoff",
            payload.get("observation_cutoff", DEFAULT_OBSERVATION_CUTOFF),
        )
        receipt.setdefault(
            "delta_start_inclusive",
            payload.get("legacy_delta_start_inclusive", LEGACY_DELTA_START_INCLUSIVE),
        )
        receipt.setdefault(
            "legacy_baseline_end_inclusive",
            payload.get(
                "legacy_baseline_end_inclusive", LEGACY_BASELINE_END_INCLUSIVE
            ),
        )
        receipt.setdefault(
            "previous_public_pin",
            payload.get("previous_public_pin", PREVIOUS_PUBLIC_PIN),
        )
        receipt.setdefault("task_id", TASK_ID)
        receipt.setdefault("schema_version", SCHEMA_VERSION)
        if "receipt_id" not in receipt:
            receipt["receipt_id"] = str(case_id)
        expanded.append(
            {
                "case_id": str(case_id),
                "expected_status": expected.value,
                "expected_kinds": list(expected_kinds),
                "receipt": receipt,
                "notes": str(case.get("notes") or ""),
            }
        )
    return expanded


def evaluate_fixture_case(case: JsonMapping) -> CompletenessResult:
    """Evaluate one expanded fixture case and return the oracle result."""

    raw = _as_mapping(case, "case")
    receipt_raw = raw.get("receipt")
    if not isinstance(receipt_raw, Mapping):
        raise FixtureSchemaError("case.receipt must be a mapping")

    # Mutable cutoff cases may fail during parse — capture as findings.
    try:
        result = evaluate_completion_receipt(receipt_raw, raise_on_failure=False)
        return result
    except MutableCutoffError as exc:
        return CompletenessResult(
            verdict=CompletenessVerdict.FAIL,
            receipt_id=str(receipt_raw.get("receipt_id") or raw.get("case_id") or ""),
            findings=(
                CompletenessFinding(
                    kind=FailureKind.MUTABLE_CUTOFF,
                    message=str(exc),
                    path="observation_cutoff",
                ),
            ),
            observation_cutoff=str(receipt_raw.get("observation_cutoff") or ""),
            frontier_closed=False,
            open_page_count=0,
            failed_final=int(receipt_raw.get("failed_final") or 0),
            unexplained_count_drift=int(
                receipt_raw.get("unexplained_count_drift") or 0
            ),
            accounted=0,
            enumerated=int(receipt_raw.get("enumerated") or 0),
            official_total=int(receipt_raw.get("official_total") or 0),
        )
    except MetadataAsBodyError as exc:
        return CompletenessResult(
            verdict=CompletenessVerdict.FAIL,
            receipt_id=str(receipt_raw.get("receipt_id") or raw.get("case_id") or ""),
            findings=(
                CompletenessFinding(
                    kind=FailureKind.METADATA_AS_BODY,
                    message=str(exc),
                    path="documents",
                ),
            ),
            observation_cutoff=str(receipt_raw.get("observation_cutoff") or ""),
            frontier_closed=False,
            open_page_count=0,
            failed_final=int(receipt_raw.get("failed_final") or 0),
            unexplained_count_drift=int(
                receipt_raw.get("unexplained_count_drift") or 0
            ),
            accounted=0,
            enumerated=int(receipt_raw.get("enumerated") or 0),
            official_total=int(receipt_raw.get("official_total") or 0),
        )


def evaluate_completion_fixture(
    path: Optional[PathLike] = None,
    *,
    payload: Optional[JsonMapping] = None,
) -> list[dict[str, Any]]:
    """Evaluate every fixture case; return per-case oracle summaries."""

    cases = expand_completion_fixture_cases(payload, path=path)
    results: list[dict[str, Any]] = []
    for case in cases:
        result = evaluate_fixture_case(case)
        expected = CompletenessVerdict.coerce(case["expected_status"])
        expected_kinds = set(case.get("expected_kinds") or [])
        actual_kinds = set(result.failure_kinds)
        status_match = result.verdict is expected
        # For fail cases, require that every expected kind is present.
        kinds_match = (
            True
            if expected is CompletenessVerdict.PASS
            else expected_kinds.issubset(actual_kinds)
        )
        results.append(
            {
                "case_id": case["case_id"],
                "expected_status": expected.value,
                "actual_status": result.verdict.value,
                "expected_kinds": sorted(expected_kinds),
                "actual_kinds": list(result.failure_kinds),
                "status_match": status_match,
                "kinds_match": kinds_match,
                "passed": status_match and kinds_match,
                "result": result.to_dict(),
            }
        )
    return results


def assert_fixture_expectations(
    path: Optional[PathLike] = None,
    *,
    payload: Optional[JsonMapping] = None,
) -> list[dict[str, Any]]:
    """Evaluate the fixture and raise if any case mismatches expectations."""

    results = evaluate_completion_fixture(path=path, payload=payload)
    failures = [row for row in results if not row["passed"]]
    if failures:
        summary = "; ".join(
            f"{row['case_id']}: expected={row['expected_status']}/"
            f"{row['expected_kinds']} actual={row['actual_status']}/"
            f"{row['actual_kinds']}"
            for row in failures
        )
        raise FederalRegisterCompletenessError(
            f"completion fixture expectation mismatches: {summary}"
        )
    return results


# ---------------------------------------------------------------------------
# Example / builder helpers for tests
# ---------------------------------------------------------------------------


def _page(
    page_number: int,
    *,
    status: str = "verified",
    result_count: int = 2,
    docs: Sequence[str] = (),
) -> dict[str, Any]:
    page_id = f"page-{page_number}"
    payload = {
        "page_id": page_id,
        "page_number": page_number,
        "status": status,
        "cursor": f"cursor-{page_number}",
        "result_count": result_count,
        "document_numbers": list(docs),
    }
    if status in {"verified", "fetched", "closed", "complete", "ok", "done"}:
        payload["response_hash"] = content_sha256(f"fr-page:{page_id}")
    return payload


def example_closed_partition(
    *,
    partition_id: str = "p-2026-03",
    start_date: str = "2026-03-03",
    end_date: str = "2026-03-31",
    enumerated: int = 4,
) -> dict[str, Any]:
    """Return a minimal closed date-partition payload."""

    docs = [f"2026-{45000 + i:05d}" for i in range(enumerated)]
    pages = [
        _page(1, result_count=min(2, enumerated), docs=docs[:2]),
        _page(
            2,
            result_count=max(0, enumerated - 2),
            docs=docs[2:],
        ),
    ]
    if enumerated == 0:
        pages = []
    return {
        "partition_id": partition_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "closed",
        "api_total": enumerated,
        "enumerated": enumerated,
        "fetched": enumerated,
        "duplicate": 0,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "pages": pages,
        "document_numbers": docs,
        "body_text_dispositions": {
            BodyTextDisposition.FULL_TEXT.value: enumerated,
        },
        "official_source_url": FEDERAL_REGISTER_DOCUMENTS_API,
        "response_hashes": [content_sha256(f"fr-partition:{partition_id}")],
    }


def example_closed_receipt(
    *,
    receipt_id: str = "fr-complete-closed-ok",
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, Any]:
    """Return a minimal fully-closed completion receipt that passes the oracle."""

    p1 = example_closed_partition(
        partition_id="p-2026-03",
        start_date="2026-03-03",
        end_date="2026-03-31",
        enumerated=4,
    )
    p2 = example_closed_partition(
        partition_id="p-2026-04",
        start_date="2026-04-01",
        end_date="2026-04-30",
        enumerated=3,
    )
    # Adjust document numbers on p2 for uniqueness.
    p2_docs = ["2026-05001", "2026-05002", "2026-05003"]
    p2["document_numbers"] = p2_docs
    p2["pages"] = [
        _page(1, result_count=2, docs=p2_docs[:2]),
        _page(2, result_count=1, docs=p2_docs[2:]),
    ]
    enumerated = p1["enumerated"] + p2["enumerated"]
    return {
        "receipt_id": receipt_id,
        "observation_cutoff": observation_cutoff,
        "partitions": [p1, p2],
        "range_start": "2026-03-03",
        "range_end": "2026-04-30",
        "official_total": enumerated,
        "enumerated": enumerated,
        "fetched": enumerated,
        "duplicate": 0,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "frontier_closed": True,
        "inventory_authority": OfficialAuthority.FEDERAL_REGISTER_API.value,
        "release_point": cutoff_release_point(observation_cutoff),
        "documents": [
            {
                "document_number": "2026-45000",
                "publication_date": "2026-03-10",
                "disposition": BodyTextDisposition.FULL_TEXT.value,
                "text": "Official full text of the example Federal Register document.",
            },
            {
                "document_number": "2026-05001",
                "publication_date": "2026-04-05",
                "disposition": BodyTextDisposition.METADATA_ONLY.value,
                "text": "",
                "abstract": "Short abstract only; body exhausted as unavailable.",
            },
        ],
        "success_registry": [
            {
                "entry_id": "reg-p-2026-03",
                "status": "success",
                "partition_id": "p-2026-03",
                "frontier_closed": True,
                "failed_final": 0,
                "open_pages": 0,
            }
        ],
        "delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
        "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "unexplained_count_drift": 0,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "notes": "Sealed closed delta cohort for oracle unit tests.",
    }


def build_default_completion_fixture_payload() -> dict[str, Any]:
    """Build the compact default completion-receipts fixture recipe."""

    closed = example_closed_receipt()

    open_page = example_closed_receipt(receipt_id="fr-fail-open-page")
    open_page["partitions"][0]["pages"][0]["status"] = "open"
    open_page["partitions"][0]["pages"][0].pop("response_hash", None)
    open_page["frontier_closed"] = False

    overlapping = example_closed_receipt(receipt_id="fr-fail-overlapping-partition")
    overlapping["partitions"][1]["start_date"] = "2026-03-15"  # overlaps p1

    gapped = example_closed_receipt(receipt_id="fr-fail-gapped-partition")
    gapped["partitions"][1]["start_date"] = "2026-04-05"  # gap after 03-31

    mutable = example_closed_receipt(receipt_id="fr-fail-mutable-cutoff")
    mutable["observation_cutoff"] = "latest"

    metadata_body = example_closed_receipt(receipt_id="fr-fail-metadata-as-body")
    metadata_body["documents"] = [
        {
            "document_number": "2026-45000",
            "publication_date": "2026-03-10",
            "disposition": BodyTextDisposition.METADATA_ONLY.value,
            "text": "X" * (METADATA_AS_BODY_CHAR_THRESHOLD + 50),
        }
    ]

    failed_final = example_closed_receipt(receipt_id="fr-fail-failed-final")
    failed_final["failed_final"] = 1
    failed_final["fetched"] = failed_final["enumerated"] - 1
    failed_final["partitions"][0]["failed_final"] = 1
    failed_final["partitions"][0]["fetched"] = (
        failed_final["partitions"][0]["enumerated"] - 1
    )
    failed_final["documents"] = [
        {
            "document_number": "2026-45000",
            "publication_date": "2026-03-10",
            "disposition": BodyTextDisposition.FAILED_FINAL.value,
            "text": "",
        }
    ]

    count_drift = example_closed_receipt(receipt_id="fr-fail-count-drift")
    count_drift["official_total"] = count_drift["enumerated"] + 5
    count_drift["unexplained_count_drift"] = 5
    count_drift["count_drift_explanation"] = None

    stale = example_closed_receipt(receipt_id="fr-fail-stale-success-registry")
    stale["success_registry"] = [
        {
            "entry_id": "reg-stale-open",
            "status": "success",
            "partition_id": "p-2026-03",
            "frontier_closed": False,
            "failed_final": 0,
            "open_pages": 2,
            "notes": "Legacy registry marked success despite open pages.",
        }
    ]

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "completeness_schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "legacy_delta_start_inclusive": LEGACY_DELTA_START_INCLUSIVE,
        "legacy_baseline_end_inclusive": LEGACY_BASELINE_END_INCLUSIVE,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "notes": (
            "Compact adversarial completion-receipt recipes for LCR-049. "
            "Cases encode open pages, overlapping/gapped partitions, mutable "
            "cutoffs, metadata-as-body, failed-final items, unexplained count "
            "drift, and stale success registries. Expand via "
            "expand_completion_fixture_cases()."
        ),
        "cases": [
            {
                "case_id": "closed_ok",
                "expected_status": "pass",
                "expected_kinds": [],
                "receipt": closed,
                "notes": "Fully closed cutoff-bound delta receipt.",
            },
            {
                "case_id": "open_page",
                "expected_status": "fail",
                "expected_kinds": ["open_page"],
                "receipt": open_page,
                "notes": "Unresolved API result page.",
            },
            {
                "case_id": "overlapping_partition",
                "expected_status": "fail",
                "expected_kinds": ["overlapping_partition"],
                "receipt": overlapping,
                "notes": "Date partitions overlap.",
            },
            {
                "case_id": "gapped_partition",
                "expected_status": "fail",
                "expected_kinds": ["gapped_partition"],
                "receipt": gapped,
                "notes": "Date partitions leave a coverage gap.",
            },
            {
                "case_id": "mutable_cutoff",
                "expected_status": "fail",
                "expected_kinds": ["mutable_cutoff"],
                "receipt": mutable,
                "notes": "Observation cutoff uses mutable token 'latest'.",
            },
            {
                "case_id": "metadata_as_body",
                "expected_status": "fail",
                "expected_kinds": ["metadata_as_body"],
                "receipt": metadata_body,
                "notes": "Metadata disposition carries long body text.",
            },
            {
                "case_id": "failed_final",
                "expected_status": "fail",
                "expected_kinds": ["failed_final"],
                "receipt": failed_final,
                "notes": "Failed-final items remain in the cohort.",
            },
            {
                "case_id": "count_drift",
                "expected_status": "fail",
                "expected_kinds": ["count_drift"],
                "receipt": count_drift,
                "notes": "Official total drifts from enumerated without explanation.",
            },
            {
                "case_id": "stale_success_registry",
                "expected_status": "fail",
                "expected_kinds": ["stale_success_registry"],
                "receipt": stale,
                "notes": "Success registry marks incomplete frontier as success.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "COMPLETENESS_TASK_ID",
    "SCHEMA_VERSION",
    "CompletenessFinding",
    "CompletenessResult",
    "CompletenessVerdict",
    "CompletionReceipt",
    "CountDriftError",
    "DatePartition",
    "DatePartitionError",
    "DeltaError",
    "DocumentDispositionRecord",
    "FailedFinalError",
    "FailureKind",
    "FederalRegisterCompletenessError",
    "MetadataAsBodyError",
    "OpenPageError",
    "PageReceipt",
    "PageStatus",
    "PartitionStatus",
    "ReconciliationError",
    "ResumeError",
    "StaleSuccessRegistryError",
    "SuccessRegistryEntry",
    "assert_completion_closed",
    "assert_fixture_expectations",
    "build_default_completion_fixture_payload",
    "evaluate_completion_fixture",
    "evaluate_completion_receipt",
    "evaluate_fixture_case",
    "example_closed_partition",
    "example_closed_receipt",
    "expand_completion_fixture_cases",
    "load_completion_fixture_payload",
    "raise_for_findings",
    "validate_date_partitions",
    "validate_delta_rules",
    "validate_failed_final",
    "validate_metadata_as_body",
    "validate_page_closure",
    "validate_partition_reconciliation",
    "validate_receipt_reconciliation",
    "validate_resume_rules",
    "validate_success_registry",
    "days_between_inclusive",
    "digest_mapping",
]
