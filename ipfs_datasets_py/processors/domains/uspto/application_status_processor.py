"""Public ODP application status and transaction processor (PATLAW-022).

Fetches and normalizes front-page application, status, and transaction data
while retaining raw upstream fields, source receipts, freshness metadata, and
unknown status/event codes.

Public-access limitations are explicit on every result. Stale or missing API
data is reported as a retrieval freshness gap — never as proof of filing or
nonreceipt. Repeated sync with identical content is idempotent (same version
identity and content digest).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Protocol, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ApplicationIdentity,
    DisclosureClassification,
    MatterEventKind,
    SourceReceipt,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.identifiers import (
    IdentifierStatus,
    normalize_application_number,
)
from ipfs_datasets_py.processors.domains.uspto.matter_events import (
    MATTER_EVENTS_SCHEMA_VERSION,
    ApplicationLifecyclePhase,
    ApplicationStatusSnapshot,
    NormalizedMatterEvent,
    RejectionDisposition,
    build_matter_event,
    normalize_application_status,
    order_matter_events,
)
from ipfs_datasets_py.processors.domains.uspto.providers.base import (
    ProviderOutcomeKind,
    ProviderResult,
    format_utc,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
    PATENT_FILE_WRAPPER_SCHEMA_VERSION,
    PROVIDER_NAME,
    OdpApplicationSnapshot,
    OdpTransactionRecord,
    PatentFileWrapperClient,
    normalize_application_number_text,
)

APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION: Final = (
    "uspto.application-status-processor.v1"
)
APPLICATION_STATUS_PROCESSOR_INTERFACE: Final = "ApplicationStatusProcessor@1"

# Default max age before a successful snapshot is classified as STALE.
# Operators may inject a different bound; we never invent rate limits here.
DEFAULT_MAX_FRESHNESS_AGE: Final = timedelta(hours=24)

_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_DATE_ONLY_RE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})\Z")
_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._:/=+\-]+")


# ---------------------------------------------------------------------------
# Explicit public-access limitations (always attached to results)
# ---------------------------------------------------------------------------


class PublicAccessLimitation(str, Enum):
    """Hard constraints of the public ODP Patent File Wrapper surface.

    Every status/event snapshot carries these so consumers cannot confuse
    public API visibility with private Patent Center completeness or proof
    of filing/nonreceipt.
    """

    ODP_PUBLIC_ONLY = "odp_public_only"
    API_KEY_REQUIRED = "api_key_required"
    NO_PRIVATE_PATENT_CENTER = "no_private_patent_center"
    CONFIDENTIAL_MAY_BE_OMITTED = "confidential_may_be_omitted"
    NPL_MAY_BE_OMITTED = "npl_may_be_omitted"
    NOT_PROOF_OF_FILING = "not_proof_of_filing"
    NOT_PROOF_OF_NONRECEIPT = "not_proof_of_nonreceipt"
    PUBLIC_VIEW_NOT_PRIVATE_EXPORT = "public_view_not_private_export"
    FRESHNESS_BOUND = "freshness_bound"


PUBLIC_ACCESS_LIMITATIONS: Final[tuple[PublicAccessLimitation, ...]] = (
    PublicAccessLimitation.ODP_PUBLIC_ONLY,
    PublicAccessLimitation.API_KEY_REQUIRED,
    PublicAccessLimitation.NO_PRIVATE_PATENT_CENTER,
    PublicAccessLimitation.CONFIDENTIAL_MAY_BE_OMITTED,
    PublicAccessLimitation.NPL_MAY_BE_OMITTED,
    PublicAccessLimitation.NOT_PROOF_OF_FILING,
    PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT,
    PublicAccessLimitation.PUBLIC_VIEW_NOT_PRIVATE_EXPORT,
    PublicAccessLimitation.FRESHNESS_BOUND,
)

PUBLIC_ACCESS_LIMITATION_NOTES: Final[Mapping[str, str]] = MappingProxyType(
    {
        PublicAccessLimitation.ODP_PUBLIC_ONLY.value: (
            "Only USPTO Open Data Portal Patent File Wrapper public data is "
            "retrieved; private/unpublished material is never inferred."
        ),
        PublicAccessLimitation.API_KEY_REQUIRED.value: (
            "ODP currently requires USPTO.gov registration and an API key."
        ),
        PublicAccessLimitation.NO_PRIVATE_PATENT_CENTER.value: (
            "This processor does not access Patent Center interactive sessions "
            "or private exports."
        ),
        PublicAccessLimitation.CONFIDENTIAL_MAY_BE_OMITTED.value: (
            "ODP may omit confidential application records from public responses."
        ),
        PublicAccessLimitation.NPL_MAY_BE_OMITTED.value: (
            "Non-patent literature and some document types may be absent from ODP."
        ),
        PublicAccessLimitation.NOT_PROOF_OF_FILING.value: (
            "Presence of a public status or transaction is not proof of filing "
            "completeness or private-submission acceptance."
        ),
        PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT.value: (
            "Missing, delayed, stale, or not-found public API data is a retrieval "
            "freshness gap — never proof that USPTO did not receive an item."
        ),
        PublicAccessLimitation.PUBLIC_VIEW_NOT_PRIVATE_EXPORT.value: (
            "Public wrapper views are not equivalent to an authorized private "
            "Patent Center export."
        ),
        PublicAccessLimitation.FRESHNESS_BOUND.value: (
            "Snapshots carry source and retrieval timestamps; consumers must "
            "honor freshness before treating data as current."
        ),
    }
)


class FreshnessClass(str, Enum):
    """Freshness of the retrieved (or missing) public snapshot.

    ``RETRIEVAL_GAP`` and ``MISSING`` must never be interpreted as nonreceipt.
    """

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    RETRIEVAL_GAP = "retrieval_gap"
    PARTIAL = "partial"
    PROVIDER_ERROR = "provider_error"
    UNKNOWN = "unknown"


class StatusSyncOutcome(str, Enum):
    """High-level outcome of one status/transaction sync attempt."""

    SUCCESS = "success"
    IDEMPOTENT_HIT = "idempotent_hit"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    STALE_DATA = "stale_data"
    PROVIDER_FAILURE = "provider_failure"
    IDENTITY_REJECTED = "identity_rejected"
    MALFORMED = "malformed"


class EvidentiaryRestriction(str, Enum):
    """Claims this result is forbidden to support."""

    PROOF_OF_FILING = "proof_of_filing"
    PROOF_OF_NONRECEIPT = "proof_of_nonreceipt"
    PRIVATE_ACCESS = "private_access"
    COMPLETE_FILE_WRAPPER = "complete_file_wrapper"
    CURRENT_STATUS_WHEN_STALE = "current_status_when_stale"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApplicationStatusProcessorError(ValueError):
    """Raised for invalid processor inputs or construction failures."""

    def __init__(self, message: str, *, code: str = "status_processor_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


# ---------------------------------------------------------------------------
# Normalized transaction record (unknown codes preserved)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizedTransactionEvent:
    """One transaction/event history row with raw upstream fields retained.

    Unknown ``event_code`` values are preserved verbatim. The processor never
    drops or rewrites an unrecognized code into a generic placeholder.
    """

    schema_version: str
    event_id: str
    application_number: str
    event_code: str | None
    event_description: str | None
    event_date: str | None
    source_event_utc: str
    retrieval_utc: str
    kind: MatterEventKind
    code_recognized: bool
    raw_event: Mapping[str, Any]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION:
            raise ApplicationStatusProcessorError(
                f"NormalizedTransactionEvent.schema_version must be "
                f"{APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(
            self,
            "application_number",
            _require_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self, "event_code", _optional_str(self.event_code, "event_code", max_len=128)
        )
        object.__setattr__(
            self,
            "event_description",
            _optional_str(self.event_description, "event_description", max_len=1024),
        )
        object.__setattr__(
            self, "event_date", _optional_str(self.event_date, "event_date", max_len=64)
        )
        object.__setattr__(
            self, "source_event_utc", _require_utc(self.source_event_utc, "source_event_utc")
        )
        object.__setattr__(
            self, "retrieval_utc", _require_utc(self.retrieval_utc, "retrieval_utc")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(MatterEventKind, self.kind, "kind")
        )
        if not isinstance(self.code_recognized, bool):
            raise TypeError("code_recognized must be bool")
        if not isinstance(self.raw_event, Mapping):
            raise TypeError("raw_event must be a mapping")
        object.__setattr__(
            self, "raw_event", MappingProxyType(dict(self.raw_event))
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "code_recognized": self.code_recognized,
            "event_code": self.event_code,
            "event_date": self.event_date,
            "event_description": self.event_description,
            "event_id": self.event_id,
            "kind": self.kind.value,
            "notes": list(self.notes),
            "raw_event": dict(self.raw_event),
            "retrieval_utc": self.retrieval_utc,
            "schema_version": self.schema_version,
            "source_event_utc": self.source_event_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedTransactionEvent":
        value = _mapping(value, "NormalizedTransactionEvent")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "event_id",
                    "application_number",
                    "event_code",
                    "event_description",
                    "event_date",
                    "source_event_utc",
                    "retrieval_utc",
                    "kind",
                    "code_recognized",
                    "raw_event",
                    "notes",
                }
            ),
            "NormalizedTransactionEvent",
        )
        return cls(
            schema_version=value.get(
                "schema_version", APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
            ),
            event_id=value.get("event_id", ""),
            application_number=value.get("application_number", ""),
            event_code=value.get("event_code"),
            event_description=value.get("event_description"),
            event_date=value.get("event_date"),
            source_event_utc=value.get("source_event_utc", ""),
            retrieval_utc=value.get("retrieval_utc", ""),
            kind=value.get("kind", MatterEventKind.TRANSACTION.value),
            code_recognized=bool(value.get("code_recognized", False)),
            raw_event=value.get("raw_event") or {},
            notes=tuple(value.get("notes") or ()),
        )

    def to_normalized_matter_event(
        self,
        *,
        matter_id: str,
        source_receipt_id: str | None = None,
        status_snapshot: ApplicationStatusSnapshot | None = None,
    ) -> NormalizedMatterEvent:
        """Project into the matter-event model without dropping raw codes."""

        meta: dict[str, str] = {}
        if self.event_code is not None:
            meta["event_code"] = self.event_code
        if self.event_description is not None:
            meta["event_description"] = self.event_description
        if self.event_date is not None:
            meta["event_date"] = self.event_date
        meta["code_recognized"] = "true" if self.code_recognized else "false"
        # Preserve every raw upstream key as a string under raw.*
        for key, raw_val in self.raw_event.items():
            meta_key = f"raw.{key}"
            if meta_key not in meta:
                meta[meta_key] = _stringify_raw(raw_val)
        return build_matter_event(
            event_id=self.event_id,
            matter_id=matter_id,
            kind=self.kind,
            source_event_utc=self.source_event_utc,
            retrieval_utc=self.retrieval_utc,
            source_receipt_id=source_receipt_id,
            classification=DisclosureClassification.PUBLIC_OFFICIAL,
            status_snapshot=status_snapshot,
            metadata=meta,
            notes=self.notes,
        )


# ---------------------------------------------------------------------------
# Versioned status + event snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    """Source-freshness judgment for a snapshot or failed retrieval."""

    schema_version: str
    freshness_class: FreshnessClass
    retrieval_utc: str | None
    source_as_of_utc: str | None
    max_age_seconds: float | None
    age_seconds: float | None
    is_proof_of_filing: bool
    is_proof_of_nonreceipt: bool
    evidentiary_restrictions: tuple[EvidentiaryRestriction, ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION:
            raise ApplicationStatusProcessorError(
                f"FreshnessAssessment.schema_version must be "
                f"{APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self,
            "freshness_class",
            _coerce_enum(FreshnessClass, self.freshness_class, "freshness_class"),
        )
        object.__setattr__(
            self, "retrieval_utc", _optional_utc(self.retrieval_utc, "retrieval_utc")
        )
        object.__setattr__(
            self,
            "source_as_of_utc",
            _optional_utc(self.source_as_of_utc, "source_as_of_utc"),
        )
        for flag_name in ("is_proof_of_filing", "is_proof_of_nonreceipt"):
            val = getattr(self, flag_name)
            if not isinstance(val, bool):
                raise TypeError(f"{flag_name} must be bool")
        # Hard fail-closed: missing/stale never prove filing or nonreceipt.
        if self.is_proof_of_filing or self.is_proof_of_nonreceipt:
            raise ApplicationStatusProcessorError(
                "freshness assessment must never mark public API data as proof "
                "of filing or nonreceipt",
                code="invalid_evidentiary_claim",
            )
        object.__setattr__(
            self,
            "evidentiary_restrictions",
            tuple(
                _coerce_enum(EvidentiaryRestriction, r, "evidentiary_restrictions")
                for r in self.evidentiary_restrictions
            ),
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )
        if self.max_age_seconds is not None:
            object.__setattr__(
                self, "max_age_seconds", _nonneg_float(self.max_age_seconds, "max_age_seconds")
            )
        if self.age_seconds is not None:
            object.__setattr__(
                self, "age_seconds", _nonneg_float(self.age_seconds, "age_seconds")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_seconds": self.age_seconds,
            "evidentiary_restrictions": [r.value for r in self.evidentiary_restrictions],
            "freshness_class": self.freshness_class.value,
            "is_proof_of_filing": self.is_proof_of_filing,
            "is_proof_of_nonreceipt": self.is_proof_of_nonreceipt,
            "max_age_seconds": self.max_age_seconds,
            "notes": list(self.notes),
            "retrieval_utc": self.retrieval_utc,
            "schema_version": self.schema_version,
            "source_as_of_utc": self.source_as_of_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FreshnessAssessment":
        value = _mapping(value, "FreshnessAssessment")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "freshness_class",
                    "retrieval_utc",
                    "source_as_of_utc",
                    "max_age_seconds",
                    "age_seconds",
                    "is_proof_of_filing",
                    "is_proof_of_nonreceipt",
                    "evidentiary_restrictions",
                    "notes",
                }
            ),
            "FreshnessAssessment",
        )
        return cls(
            schema_version=value.get(
                "schema_version", APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
            ),
            freshness_class=value.get("freshness_class", FreshnessClass.UNKNOWN.value),
            retrieval_utc=value.get("retrieval_utc"),
            source_as_of_utc=value.get("source_as_of_utc"),
            max_age_seconds=value.get("max_age_seconds"),
            age_seconds=value.get("age_seconds"),
            is_proof_of_filing=bool(value.get("is_proof_of_filing", False)),
            is_proof_of_nonreceipt=bool(value.get("is_proof_of_nonreceipt", False)),
            evidentiary_restrictions=tuple(value.get("evidentiary_restrictions") or ()),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class VersionedStatusEventSnapshot:
    """Versioned, content-addressed public status + transaction snapshot.

    Schema and content digests version the record. Identical upstream content
    yields the same ``version_id`` / ``content_digest`` / ``sync_key`` so
    repeated sync is idempotent.
    """

    schema_version: str
    version_id: str
    content_digest: str
    sync_key: str
    application_number: str
    identity: ApplicationIdentity
    status: ApplicationStatusSnapshot | None
    transactions: tuple[NormalizedTransactionEvent, ...]
    ordered_events: tuple[NormalizedMatterEvent, ...]
    raw_application_meta: Mapping[str, Any]
    raw_events: tuple[Mapping[str, Any], ...]
    application_receipt: SourceReceipt | None
    transactions_receipt: SourceReceipt | None
    public_access_limitations: tuple[PublicAccessLimitation, ...]
    public_access_notes: Mapping[str, str]
    freshness: FreshnessAssessment
    provider_schema_version: str
    last_ingestion_datetime: str | None
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION:
            raise ApplicationStatusProcessorError(
                f"VersionedStatusEventSnapshot.schema_version must be "
                f"{APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "version_id", _identifier(self.version_id, "version_id")
        )
        object.__setattr__(
            self, "content_digest", _sha256_hex(self.content_digest, "content_digest")
        )
        object.__setattr__(self, "sync_key", _identifier(self.sync_key, "sync_key"))
        object.__setattr__(
            self,
            "application_number",
            _require_str(self.application_number, "application_number", max_len=64),
        )
        if not isinstance(self.identity, ApplicationIdentity):
            raise TypeError("identity must be ApplicationIdentity")
        if self.status is not None and not isinstance(
            self.status, ApplicationStatusSnapshot
        ):
            raise TypeError("status must be ApplicationStatusSnapshot or None")
        object.__setattr__(
            self,
            "transactions",
            tuple(self.transactions),
        )
        for tx in self.transactions:
            if not isinstance(tx, NormalizedTransactionEvent):
                raise TypeError("transactions items must be NormalizedTransactionEvent")
        object.__setattr__(self, "ordered_events", tuple(self.ordered_events))
        for ev in self.ordered_events:
            if not isinstance(ev, NormalizedMatterEvent):
                raise TypeError("ordered_events items must be NormalizedMatterEvent")
        if not isinstance(self.raw_application_meta, Mapping):
            raise TypeError("raw_application_meta must be a mapping")
        object.__setattr__(
            self,
            "raw_application_meta",
            MappingProxyType(dict(self.raw_application_meta)),
        )
        raw_events = tuple(
            MappingProxyType(dict(item)) if isinstance(item, Mapping) else item
            for item in self.raw_events
        )
        for item in raw_events:
            if not isinstance(item, Mapping):
                raise TypeError("raw_events items must be mappings")
        object.__setattr__(self, "raw_events", raw_events)
        if self.application_receipt is not None and not isinstance(
            self.application_receipt, SourceReceipt
        ):
            raise TypeError("application_receipt must be SourceReceipt or None")
        if self.transactions_receipt is not None and not isinstance(
            self.transactions_receipt, SourceReceipt
        ):
            raise TypeError("transactions_receipt must be SourceReceipt or None")
        limitations = tuple(
            _coerce_enum(PublicAccessLimitation, lim, "public_access_limitations")
            for lim in self.public_access_limitations
        )
        if not limitations:
            raise ApplicationStatusProcessorError(
                "public_access_limitations must be non-empty and explicit",
                code="missing_public_access_limitations",
            )
        object.__setattr__(self, "public_access_limitations", limitations)
        if not isinstance(self.public_access_notes, Mapping):
            raise TypeError("public_access_notes must be a mapping")
        object.__setattr__(
            self,
            "public_access_notes",
            MappingProxyType({str(k): str(v) for k, v in self.public_access_notes.items()}),
        )
        if not isinstance(self.freshness, FreshnessAssessment):
            raise TypeError("freshness must be FreshnessAssessment")
        object.__setattr__(
            self,
            "provider_schema_version",
            _require_str(
                self.provider_schema_version, "provider_schema_version", max_len=64
            ),
        )
        object.__setattr__(
            self,
            "last_ingestion_datetime",
            _optional_str(
                self.last_ingestion_datetime, "last_ingestion_datetime", max_len=64
            ),
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=64)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "application_receipt": (
                None
                if self.application_receipt is None
                else self.application_receipt.to_dict()
            ),
            "content_digest": self.content_digest,
            "freshness": self.freshness.to_dict(),
            "identity": self.identity.to_dict(),
            "last_ingestion_datetime": self.last_ingestion_datetime,
            "notes": list(self.notes),
            "ordered_events": [e.to_dict() for e in self.ordered_events],
            "provider_schema_version": self.provider_schema_version,
            "public_access_limitations": [
                lim.value for lim in self.public_access_limitations
            ],
            "public_access_notes": dict(self.public_access_notes),
            "raw_application_meta": dict(self.raw_application_meta),
            "raw_events": [dict(e) for e in self.raw_events],
            "schema_version": self.schema_version,
            "status": None if self.status is None else self.status.to_dict(),
            "sync_key": self.sync_key,
            "transactions": [t.to_dict() for t in self.transactions],
            "transactions_receipt": (
                None
                if self.transactions_receipt is None
                else self.transactions_receipt.to_dict()
            ),
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VersionedStatusEventSnapshot":
        value = _mapping(value, "VersionedStatusEventSnapshot")
        status_raw = value.get("status")
        status = (
            ApplicationStatusSnapshot.from_dict(status_raw)
            if status_raw is not None
            else None
        )
        app_receipt_raw = value.get("application_receipt")
        tx_receipt_raw = value.get("transactions_receipt")
        return cls(
            schema_version=value.get(
                "schema_version", APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
            ),
            version_id=value.get("version_id", ""),
            content_digest=value.get("content_digest", ""),
            sync_key=value.get("sync_key", ""),
            application_number=value.get("application_number", ""),
            identity=ApplicationIdentity.from_dict(value.get("identity") or {}),
            status=status,
            transactions=tuple(
                NormalizedTransactionEvent.from_dict(t)
                for t in (value.get("transactions") or ())
            ),
            ordered_events=tuple(
                NormalizedMatterEvent.from_dict(e)
                for e in (value.get("ordered_events") or ())
            ),
            raw_application_meta=value.get("raw_application_meta") or {},
            raw_events=tuple(value.get("raw_events") or ()),
            application_receipt=(
                SourceReceipt.from_dict(app_receipt_raw)
                if app_receipt_raw is not None
                else None
            ),
            transactions_receipt=(
                SourceReceipt.from_dict(tx_receipt_raw)
                if tx_receipt_raw is not None
                else None
            ),
            public_access_limitations=tuple(
                value.get("public_access_limitations") or PUBLIC_ACCESS_LIMITATIONS
            ),
            public_access_notes=value.get("public_access_notes")
            or dict(PUBLIC_ACCESS_LIMITATION_NOTES),
            freshness=FreshnessAssessment.from_dict(value.get("freshness") or {}),
            provider_schema_version=value.get(
                "provider_schema_version", PATENT_FILE_WRAPPER_SCHEMA_VERSION
            ),
            last_ingestion_datetime=value.get("last_ingestion_datetime"),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class StatusSyncResult:
    """Typed result of :meth:`ApplicationStatusProcessor.sync`."""

    schema_version: str
    outcome: StatusSyncOutcome
    application_number: str | None
    snapshot: VersionedStatusEventSnapshot | None
    provider_kind: str | None
    provider_status_code: int | None
    public_access_limitations: tuple[PublicAccessLimitation, ...]
    public_access_notes: Mapping[str, str]
    freshness: FreshnessAssessment
    evidentiary_restrictions: tuple[EvidentiaryRestriction, ...]
    idempotent_hit: bool
    message: str | None
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION:
            raise ApplicationStatusProcessorError(
                f"StatusSyncResult.schema_version must be "
                f"{APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "outcome", _coerce_enum(StatusSyncOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        if self.snapshot is not None and not isinstance(
            self.snapshot, VersionedStatusEventSnapshot
        ):
            raise TypeError("snapshot must be VersionedStatusEventSnapshot or None")
        limitations = tuple(
            _coerce_enum(PublicAccessLimitation, lim, "public_access_limitations")
            for lim in self.public_access_limitations
        )
        if not limitations:
            raise ApplicationStatusProcessorError(
                "public_access_limitations must be explicit on every result",
                code="missing_public_access_limitations",
            )
        object.__setattr__(self, "public_access_limitations", limitations)
        object.__setattr__(
            self,
            "public_access_notes",
            MappingProxyType(
                {str(k): str(v) for k, v in dict(self.public_access_notes or {}).items()}
            ),
        )
        if not isinstance(self.freshness, FreshnessAssessment):
            raise TypeError("freshness must be FreshnessAssessment")
        object.__setattr__(
            self,
            "evidentiary_restrictions",
            tuple(
                _coerce_enum(EvidentiaryRestriction, r, "evidentiary_restrictions")
                for r in self.evidentiary_restrictions
            ),
        )
        if not isinstance(self.idempotent_hit, bool):
            raise TypeError("idempotent_hit must be bool")
        object.__setattr__(
            self, "message", _optional_str(self.message, "message", max_len=1024)
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=64)
        )
        object.__setattr__(
            self,
            "provider_kind",
            _optional_str(self.provider_kind, "provider_kind", max_len=64),
        )

    @property
    def ok(self) -> bool:
        return self.outcome in {
            StatusSyncOutcome.SUCCESS,
            StatusSyncOutcome.IDEMPOTENT_HIT,
            StatusSyncOutcome.STALE_DATA,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "evidentiary_restrictions": [
                r.value for r in self.evidentiary_restrictions
            ],
            "freshness": self.freshness.to_dict(),
            "idempotent_hit": self.idempotent_hit,
            "message": self.message,
            "notes": list(self.notes),
            "outcome": self.outcome.value,
            "provider_kind": self.provider_kind,
            "provider_status_code": self.provider_status_code,
            "public_access_limitations": [
                lim.value for lim in self.public_access_limitations
            ],
            "public_access_notes": dict(self.public_access_notes),
            "schema_version": self.schema_version,
            "snapshot": None if self.snapshot is None else self.snapshot.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StatusSyncResult":
        value = _mapping(value, "StatusSyncResult")
        snap_raw = value.get("snapshot")
        return cls(
            schema_version=value.get(
                "schema_version", APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
            ),
            outcome=value.get("outcome", StatusSyncOutcome.PROVIDER_FAILURE.value),
            application_number=value.get("application_number"),
            snapshot=(
                VersionedStatusEventSnapshot.from_dict(snap_raw)
                if snap_raw is not None
                else None
            ),
            provider_kind=value.get("provider_kind"),
            provider_status_code=value.get("provider_status_code"),
            public_access_limitations=tuple(
                value.get("public_access_limitations") or PUBLIC_ACCESS_LIMITATIONS
            ),
            public_access_notes=value.get("public_access_notes")
            or dict(PUBLIC_ACCESS_LIMITATION_NOTES),
            freshness=FreshnessAssessment.from_dict(value.get("freshness") or {}),
            evidentiary_restrictions=tuple(
                value.get("evidentiary_restrictions") or ()
            ),
            idempotent_hit=bool(value.get("idempotent_hit", False)),
            message=value.get("message"),
            notes=tuple(value.get("notes") or ()),
        )


# ---------------------------------------------------------------------------
# Idempotent store protocol
# ---------------------------------------------------------------------------


class StatusSnapshotStore(Protocol):
    """Durable or in-memory store keyed by sync_key for idempotent sync."""

    def get(self, sync_key: str) -> VersionedStatusEventSnapshot | None:
        ...

    def put(
        self, snapshot: VersionedStatusEventSnapshot
    ) -> VersionedStatusEventSnapshot:
        ...

    def list_versions(
        self, application_number: str
    ) -> tuple[VersionedStatusEventSnapshot, ...]:
        ...


class InMemoryStatusSnapshotStore:
    """Process-local idempotent store for status/event snapshots."""

    def __init__(self) -> None:
        self._by_sync_key: dict[str, VersionedStatusEventSnapshot] = {}
        self._by_app: dict[str, list[str]] = {}

    def get(self, sync_key: str) -> VersionedStatusEventSnapshot | None:
        return self._by_sync_key.get(sync_key)

    def put(
        self, snapshot: VersionedStatusEventSnapshot
    ) -> VersionedStatusEventSnapshot:
        existing = self._by_sync_key.get(snapshot.sync_key)
        if existing is not None:
            # Idempotent: identical sync_key returns the stored version.
            return existing
        self._by_sync_key[snapshot.sync_key] = snapshot
        self._by_app.setdefault(snapshot.application_number, []).append(
            snapshot.sync_key
        )
        return snapshot

    def list_versions(
        self, application_number: str
    ) -> tuple[VersionedStatusEventSnapshot, ...]:
        keys = self._by_app.get(application_number, [])
        return tuple(
            self._by_sync_key[k] for k in keys if k in self._by_sync_key
        )

    def __len__(self) -> int:
        return len(self._by_sync_key)


# ---------------------------------------------------------------------------
# Known event codes (unknown codes still preserved)
# ---------------------------------------------------------------------------


# Recognized ODP/Patent Center style event codes → MatterEventKind.
# Unlisted codes remain preserved with code_recognized=False.
_KNOWN_EVENT_CODE_KINDS: Final[Mapping[str, MatterEventKind]] = MappingProxyType(
    {
        "APP.FILE.REC": MatterEventKind.FILING,
        "APP.FILE": MatterEventKind.FILING,
        "FILING": MatterEventKind.FILING,
        "CTNF": MatterEventKind.TRANSACTION,
        "CTFR": MatterEventKind.TRANSACTION,
        "NOA": MatterEventKind.ALLOWANCE,
        "ISSUE.NTF": MatterEventKind.GRANT,
        "ABN": MatterEventKind.ABANDONMENT,
        "ABND": MatterEventKind.ABANDONMENT,
        "N/AP": MatterEventKind.APPEAL,
        "AP.BIB": MatterEventKind.APPEAL,
        "RCEX": MatterEventKind.RESPONSE,
        "A...": MatterEventKind.RESPONSE,
        "WRIT": MatterEventKind.DOCUMENT,
        "IFW": MatterEventKind.DOCUMENT,
    }
)


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


@dataclass
class ApplicationStatusProcessor:
    """Validate identity, fetch ODP status/transactions, normalize, version.

    Construction injects the ODP client and optional store/clock. Secrets never
    enter this module; they stay inside the provider client.
    """

    client: PatentFileWrapperClient
    store: StatusSnapshotStore = field(default_factory=InMemoryStatusSnapshotStore)
    max_freshness_age: timedelta = DEFAULT_MAX_FRESHNESS_AGE
    wall_clock: Callable[[], datetime] | None = None
    fetch_transactions: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.client, PatentFileWrapperClient):
            raise ApplicationStatusProcessorError(
                "client must be a PatentFileWrapperClient",
                code="invalid_client",
            )
        if not isinstance(self.max_freshness_age, timedelta):
            raise ApplicationStatusProcessorError(
                "max_freshness_age must be datetime.timedelta",
                code="invalid_max_freshness_age",
            )
        if self.max_freshness_age.total_seconds() < 0:
            raise ApplicationStatusProcessorError(
                "max_freshness_age must be non-negative",
                code="invalid_max_freshness_age",
            )
        if self.wall_clock is None:
            self.wall_clock = lambda: datetime.now(timezone.utc)
        elif not callable(self.wall_clock):
            raise ApplicationStatusProcessorError(
                "wall_clock must be callable", code="invalid_wall_clock"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(
        self,
        application_number: str,
        *,
        matter_id: str | None = None,
        force_refresh: bool = False,
    ) -> StatusSyncResult:
        """Fetch, normalize, version, and store public status/transactions.

        Repeated calls with unchanged upstream content return the same
        versioned snapshot (``idempotent_hit=True``).
        """
        identity_result = self.resolve_identity(application_number)
        if identity_result is None:
            freshness = self._freshness_for_gap(
                freshness_class=FreshnessClass.MISSING,
                retrieval_utc=self._now_utc(),
                notes=(
                    "Application number failed identity validation; no ODP "
                    "request was issued. This is not proof of nonreceipt.",
                ),
            )
            return StatusSyncResult(
                schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
                outcome=StatusSyncOutcome.IDENTITY_REJECTED,
                application_number=None,
                snapshot=None,
                provider_kind=None,
                provider_status_code=None,
                public_access_limitations=PUBLIC_ACCESS_LIMITATIONS,
                public_access_notes=dict(PUBLIC_ACCESS_LIMITATION_NOTES),
                freshness=freshness,
                evidentiary_restrictions=_default_evidentiary_restrictions(
                    include_stale=False
                ),
                idempotent_hit=False,
                message="application identity rejected or unresolved",
                notes=(
                    "Ambiguous or invalid application identifiers are rejected "
                    "before provider I/O.",
                ),
            )

        app_no, identity = identity_result
        matter = matter_id or f"matter:app:{app_no}"

        app_result = self.client.get_application_data(app_no)
        if not app_result.ok:
            return self._result_from_provider_failure(
                application_number=app_no,
                result=app_result,
            )

        snapshot_payload = app_result.payload
        if not isinstance(snapshot_payload, OdpApplicationSnapshot):
            return self._malformed_result(
                application_number=app_no,
                message="application data payload is not OdpApplicationSnapshot",
                provider_kind=app_result.kind.value,
                provider_status_code=app_result.status_code,
            )

        tx_records: tuple[OdpTransactionRecord, ...] = ()
        tx_receipt: SourceReceipt | None = None
        tx_result: ProviderResult | None = None
        if self.fetch_transactions:
            tx_result = self.client.get_transactions(app_no)
            if tx_result.ok and isinstance(tx_result.payload, tuple):
                tx_records = tuple(
                    item
                    for item in tx_result.payload
                    if isinstance(item, OdpTransactionRecord)
                )
                tx_receipt = tx_result.receipt
            elif tx_result.ok:
                return self._malformed_result(
                    application_number=app_no,
                    message="transactions payload is not a tuple of records",
                    provider_kind=tx_result.kind.value,
                    provider_status_code=tx_result.status_code,
                )
            else:
                # Partial: application data succeeded, transactions failed.
                # Do not treat as nonreceipt of filings.
                pass

        built = self.build_snapshot_from_provider(
            application_snapshot=snapshot_payload,
            transaction_records=tx_records,
            application_receipt=app_result.receipt,
            transactions_receipt=tx_receipt,
            identity=identity,
            matter_id=matter,
            transactions_failed=bool(
                self.fetch_transactions and tx_result is not None and not tx_result.ok
            ),
            transactions_provider_kind=(
                None if tx_result is None else tx_result.kind.value
            ),
        )

        stored = self.store.put(built)
        idempotent = stored is not built and stored.sync_key == built.sync_key
        # When force_refresh and content identical, still idempotent.
        if force_refresh and not idempotent:
            # Content differs or first write — already stored above.
            pass

        outcome = (
            StatusSyncOutcome.IDEMPOTENT_HIT
            if idempotent
            else (
                StatusSyncOutcome.STALE_DATA
                if stored.freshness.freshness_class is FreshnessClass.STALE
                else StatusSyncOutcome.SUCCESS
            )
        )
        notes: list[str] = list(stored.notes)
        if idempotent:
            notes.append(
                "Repeated sync returned the existing versioned snapshot "
                f"(sync_key={stored.sync_key})."
            )
        if (
            self.fetch_transactions
            and tx_result is not None
            and not tx_result.ok
        ):
            notes.append(
                "Transaction history retrieval failed; application status was "
                f"still normalized (provider_kind={tx_result.kind.value}). "
                "Partial public data is a retrieval gap, not proof of nonreceipt."
            )

        return StatusSyncResult(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            outcome=outcome,
            application_number=app_no,
            snapshot=stored,
            provider_kind=app_result.kind.value,
            provider_status_code=app_result.status_code,
            public_access_limitations=PUBLIC_ACCESS_LIMITATIONS,
            public_access_notes=dict(PUBLIC_ACCESS_LIMITATION_NOTES),
            freshness=stored.freshness,
            evidentiary_restrictions=stored.freshness.evidentiary_restrictions,
            idempotent_hit=idempotent,
            message=None if not idempotent else "idempotent sync hit",
            notes=tuple(notes),
        )

    def resolve_identity(
        self, application_number: str
    ) -> tuple[str, ApplicationIdentity] | None:
        """Validate and normalize an application number for ODP paths."""

        if not isinstance(application_number, str) or not application_number.strip():
            return None
        ident = normalize_application_number(application_number, strict=False)
        if ident.status is IdentifierStatus.RESOLVED and ident.compact:
            compact = ident.compact
        else:
            try:
                compact = normalize_application_number_text(application_number)
            except Exception:
                return None
        identity = ApplicationIdentity(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            application_number=compact,
            publication_number=None,
            patent_number=None,
            source=PROVIDER_NAME,
            confidence=1.0 if ident.status is IdentifierStatus.RESOLVED else 0.5,
            unresolved_ambiguity=ident.status is not IdentifierStatus.RESOLVED,
            notes=tuple(ident.notes)
            if getattr(ident, "notes", None)
            else (),
        )
        return compact, identity

    def build_snapshot_from_provider(
        self,
        *,
        application_snapshot: OdpApplicationSnapshot,
        transaction_records: Sequence[OdpTransactionRecord] = (),
        application_receipt: SourceReceipt | None,
        transactions_receipt: SourceReceipt | None,
        identity: ApplicationIdentity | None = None,
        matter_id: str | None = None,
        transactions_failed: bool = False,
        transactions_provider_kind: str | None = None,
        retrieval_utc: str | None = None,
    ) -> VersionedStatusEventSnapshot:
        """Normalize provider payloads into a versioned snapshot (no I/O)."""

        app_no = application_snapshot.application_number
        identity = identity or application_snapshot.identity
        matter = matter_id or f"matter:app:{app_no}"
        retrieved = (
            retrieval_utc
            or (application_receipt.retrieval_utc if application_receipt else None)
            or self._now_utc()
        )

        status = normalize_status_from_meta(
            application_snapshot.application_meta_data,
            retrieval_utc=retrieved,
            last_ingestion_datetime=application_snapshot.last_ingestion_datetime,
        )

        # Prefer dedicated transaction endpoint records; fall back to bag events.
        raw_event_maps: list[Mapping[str, Any]] = []
        if transaction_records:
            for rec in transaction_records:
                raw_event_maps.append(dict(rec.event))
        elif application_snapshot.event_data:
            for event in application_snapshot.event_data:
                raw_event_maps.append(dict(event))

        transactions = tuple(
            normalize_transaction_event(
                event,
                application_number=app_no,
                retrieval_utc=retrieved,
                index=index,
            )
            for index, event in enumerate(raw_event_maps)
        )

        ordered = order_matter_events(
            [
                tx.to_normalized_matter_event(
                    matter_id=matter,
                    source_receipt_id=(
                        transactions_receipt.receipt_id
                        if transactions_receipt is not None
                        else (
                            application_receipt.receipt_id
                            if application_receipt is not None
                            else None
                        )
                    ),
                )
                for tx in transactions
            ]
        )

        # Optional status-as-event projection for ledger consumers.
        if status is not None:
            status_event = build_matter_event(
                event_id=f"status:{app_no}:{status.status_code or 'unknown'}",
                matter_id=matter,
                kind=MatterEventKind.STATUS,
                source_event_utc=status.as_of_source_utc or retrieved,
                retrieval_utc=retrieved,
                source_receipt_id=(
                    application_receipt.receipt_id if application_receipt else None
                ),
                classification=DisclosureClassification.PUBLIC_OFFICIAL,
                status_snapshot=status,
                metadata={
                    "projection": "application_status",
                    "provider": PROVIDER_NAME,
                },
                notes=("Projected from applicationMetaData; not a transaction row.",),
            )
            ordered = order_matter_events([*ordered, status_event])

        content_digest = compute_status_content_digest(
            application_number=app_no,
            status=status,
            raw_application_meta=application_snapshot.application_meta_data,
            raw_events=raw_event_maps,
        )
        version_id = f"status-v1:{content_digest[:16]}"
        sync_key = f"{app_no}:{content_digest}"

        freshness = assess_freshness(
            retrieval_utc=retrieved,
            source_as_of_utc=status.as_of_source_utc if status else None,
            last_ingestion_datetime=application_snapshot.last_ingestion_datetime,
            max_age=self.max_freshness_age,
            now=self.wall_clock(),
            partial=transactions_failed,
            missing=False,
        )

        notes: list[str] = [
            "Public ODP status/transaction snapshot; confidential material may "
            "be omitted.",
        ]
        if transactions_failed:
            notes.append(
                "Transaction endpoint failure; event history may be incomplete "
                f"(provider_kind={transactions_provider_kind}). "
                "Incomplete public data is not proof of nonreceipt."
            )
        # Flag unknown status/event codes in notes without dropping them.
        if status is not None and status.status_code:
            if not _status_code_known(status.status_code):
                notes.append(
                    f"Unknown application status code preserved: {status.status_code!r}"
                )
        for tx in transactions:
            if tx.event_code and not tx.code_recognized:
                notes.append(
                    f"Unknown event code preserved: {tx.event_code!r}"
                )

        return VersionedStatusEventSnapshot(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            version_id=version_id,
            content_digest=content_digest,
            sync_key=sync_key,
            application_number=app_no,
            identity=identity,
            status=status,
            transactions=transactions,
            ordered_events=tuple(ordered),
            raw_application_meta=dict(application_snapshot.application_meta_data),
            raw_events=tuple(dict(e) for e in raw_event_maps),
            application_receipt=application_receipt,
            transactions_receipt=transactions_receipt,
            public_access_limitations=PUBLIC_ACCESS_LIMITATIONS,
            public_access_notes=dict(PUBLIC_ACCESS_LIMITATION_NOTES),
            freshness=freshness,
            provider_schema_version=application_snapshot.schema_version,
            last_ingestion_datetime=application_snapshot.last_ingestion_datetime,
            notes=tuple(notes),
        )

    def list_versions(
        self, application_number: str
    ) -> tuple[VersionedStatusEventSnapshot, ...]:
        resolved = self.resolve_identity(application_number)
        if resolved is None:
            return ()
        app_no, _ = resolved
        return self.store.list_versions(app_no)

    # ------------------------------------------------------------------
    # Failure / gap helpers
    # ------------------------------------------------------------------

    def _result_from_provider_failure(
        self,
        *,
        application_number: str,
        result: ProviderResult,
    ) -> StatusSyncResult:
        kind = result.kind
        if kind is ProviderOutcomeKind.NOT_FOUND:
            outcome = StatusSyncOutcome.NOT_FOUND
            freshness_class = FreshnessClass.RETRIEVAL_GAP
            message = (
                "ODP returned not_found for this application number. This is a "
                "public retrieval gap, not proof that USPTO did not receive a "
                "filing or that the application does not exist privately."
            )
            notes = (
                "Missing public API data must not be reported as nonreceipt.",
                PublicAccessLimitation.NOT_PROOF_OF_NONRECEIPT.value,
            )
        elif kind is ProviderOutcomeKind.UNAUTHORIZED:
            outcome = StatusSyncOutcome.UNAUTHORIZED
            freshness_class = FreshnessClass.PROVIDER_ERROR
            message = "ODP unauthorized (API key missing or invalid)"
            notes = ("Credentials never appear in receipts or results.",)
        elif kind is ProviderOutcomeKind.FORBIDDEN:
            outcome = StatusSyncOutcome.FORBIDDEN
            freshness_class = FreshnessClass.PROVIDER_ERROR
            message = "ODP forbidden for this resource"
            notes = (
                "Forbidden responses do not prove private file contents or "
                "nonreceipt.",
            )
        elif kind in {
            ProviderOutcomeKind.MALFORMED,
            ProviderOutcomeKind.SCHEMA_DRIFT,
        }:
            outcome = StatusSyncOutcome.MALFORMED
            freshness_class = FreshnessClass.PROVIDER_ERROR
            message = result.message or f"provider {kind.value}"
            notes = ("Malformed/schema-drift payloads are quarantined.",)
        else:
            outcome = StatusSyncOutcome.PROVIDER_FAILURE
            freshness_class = FreshnessClass.PROVIDER_ERROR
            message = result.message or f"provider outcome {kind.value}"
            notes = (
                "Provider failure is not proof of filing or nonreceipt.",
            )

        retrieval = (
            result.receipt.retrieval_utc
            if result.receipt is not None
            else self._now_utc()
        )
        freshness = self._freshness_for_gap(
            freshness_class=freshness_class,
            retrieval_utc=retrieval,
            notes=notes,
        )
        return StatusSyncResult(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            outcome=outcome,
            application_number=application_number,
            snapshot=None,
            provider_kind=kind.value,
            provider_status_code=result.status_code,
            public_access_limitations=PUBLIC_ACCESS_LIMITATIONS,
            public_access_notes=dict(PUBLIC_ACCESS_LIMITATION_NOTES),
            freshness=freshness,
            evidentiary_restrictions=freshness.evidentiary_restrictions,
            idempotent_hit=False,
            message=message,
            notes=notes,
        )

    def _malformed_result(
        self,
        *,
        application_number: str,
        message: str,
        provider_kind: str | None,
        provider_status_code: int | None,
    ) -> StatusSyncResult:
        freshness = self._freshness_for_gap(
            freshness_class=FreshnessClass.PROVIDER_ERROR,
            retrieval_utc=self._now_utc(),
            notes=(message,),
        )
        return StatusSyncResult(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            outcome=StatusSyncOutcome.MALFORMED,
            application_number=application_number,
            snapshot=None,
            provider_kind=provider_kind,
            provider_status_code=provider_status_code,
            public_access_limitations=PUBLIC_ACCESS_LIMITATIONS,
            public_access_notes=dict(PUBLIC_ACCESS_LIMITATION_NOTES),
            freshness=freshness,
            evidentiary_restrictions=freshness.evidentiary_restrictions,
            idempotent_hit=False,
            message=message,
            notes=(message,),
        )

    def _freshness_for_gap(
        self,
        *,
        freshness_class: FreshnessClass,
        retrieval_utc: str | None,
        notes: Sequence[str],
    ) -> FreshnessAssessment:
        return FreshnessAssessment(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            freshness_class=freshness_class,
            retrieval_utc=retrieval_utc,
            source_as_of_utc=None,
            max_age_seconds=self.max_freshness_age.total_seconds(),
            age_seconds=None,
            is_proof_of_filing=False,
            is_proof_of_nonreceipt=False,
            evidentiary_restrictions=_default_evidentiary_restrictions(
                include_stale=False
            ),
            notes=tuple(notes),
        )

    def _now_utc(self) -> str:
        return format_utc(self.wall_clock())


# ---------------------------------------------------------------------------
# Normalization helpers (pure)
# ---------------------------------------------------------------------------


def normalize_status_from_meta(
    meta: Mapping[str, Any] | None,
    *,
    retrieval_utc: str,
    last_ingestion_datetime: str | None = None,
) -> ApplicationStatusSnapshot | None:
    """Build :class:`ApplicationStatusSnapshot` from ODP applicationMetaData.

    Unknown status codes are preserved as strings in ``status_code`` and
    ``raw_fields``. No field is discarded.
    """
    if not meta:
        return None

    status_code_raw = meta.get("applicationStatusCode")
    status_text_raw = meta.get("applicationStatusDescriptionText")
    status_code = (
        None if status_code_raw is None or status_code_raw == "" else str(status_code_raw)
    )
    status_text = (
        None
        if status_text_raw is None or status_text_raw == ""
        else str(status_text_raw)
    )

    # Capture every meta field as raw string for non-lossy retention.
    raw_fields: dict[str, str] = {}
    for key, value in meta.items():
        raw_fields[str(key)] = _stringify_raw(value)

    entity = meta.get("entityStatusData") or meta.get("businessEntityStatusCategory")
    entity_status = None if entity is None or entity == "" else str(entity)

    as_of = _coerce_source_utc(
        meta.get("applicationStatusDate")
        or meta.get("statusDate")
        or last_ingestion_datetime
        or meta.get("filingDate")
    )

    return normalize_application_status(
        status_code=status_code,
        status_text=status_text,
        entity_status=entity_status,
        as_of_source_utc=as_of,
        retrieval_utc=retrieval_utc,
        raw_fields=raw_fields,
        notes=(),
        infer=True,
    )


def normalize_transaction_event(
    event: Mapping[str, Any],
    *,
    application_number: str,
    retrieval_utc: str,
    index: int = 0,
) -> NormalizedTransactionEvent:
    """Normalize one eventDataBag / transaction row; preserve unknown codes."""

    if not isinstance(event, Mapping):
        raise ApplicationStatusProcessorError(
            "transaction event must be a mapping", code="invalid_event"
        )

    code_raw = (
        event.get("eventCode")
        or event.get("event_code")
        or event.get("transactionCode")
    )
    desc_raw = (
        event.get("eventDescriptionText")
        or event.get("event_description")
        or event.get("transactionDescription")
    )
    date_raw = (
        event.get("eventDate")
        or event.get("event_date")
        or event.get("mailDate")
        or event.get("officialDate")
    )

    event_code = None if code_raw is None or code_raw == "" else str(code_raw)
    event_description = (
        None if desc_raw is None or desc_raw == "" else str(desc_raw)
    )
    event_date = None if date_raw is None or date_raw == "" else str(date_raw)

    recognized = bool(event_code and event_code.upper() in _KNOWN_EVENT_CODE_KINDS)
    kind = (
        _KNOWN_EVENT_CODE_KINDS[event_code.upper()]
        if recognized and event_code
        else _infer_kind_from_text(event_code, event_description)
    )

    source_utc = _coerce_source_utc(event_date) or retrieval_utc
    event_id = _stable_event_id(
        application_number=application_number,
        event_code=event_code,
        event_date=event_date,
        index=index,
        raw_event=event,
    )

    notes: list[str] = []
    if event_code and not recognized and kind is MatterEventKind.TRANSACTION:
        notes.append("event code not in known vocabulary; preserved as-is")

    return NormalizedTransactionEvent(
        schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
        event_id=event_id,
        application_number=application_number,
        event_code=event_code,
        event_description=event_description,
        event_date=event_date,
        source_event_utc=source_utc,
        retrieval_utc=retrieval_utc,
        kind=kind,
        code_recognized=recognized,
        raw_event=dict(event),
        notes=tuple(notes),
    )


def compute_status_content_digest(
    *,
    application_number: str,
    status: ApplicationStatusSnapshot | None,
    raw_application_meta: Mapping[str, Any],
    raw_events: Sequence[Mapping[str, Any]],
) -> str:
    """Deterministic content digest for versioning / idempotent sync keys."""

    material = {
        "application_number": application_number,
        "raw_application_meta": _json_safe(raw_application_meta),
        "raw_events": [_json_safe(e) for e in raw_events],
        "schema_version": APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
        "status": None if status is None else status.to_dict(),
    }
    return sha256_hex(canonical_json(material))


def assess_freshness(
    *,
    retrieval_utc: str | None,
    source_as_of_utc: str | None,
    last_ingestion_datetime: str | None,
    max_age: timedelta,
    now: datetime | None = None,
    partial: bool = False,
    missing: bool = False,
) -> FreshnessAssessment:
    """Classify freshness without ever claiming filing/nonreceipt proof."""

    if missing:
        return FreshnessAssessment(
            schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
            freshness_class=FreshnessClass.MISSING,
            retrieval_utc=retrieval_utc,
            source_as_of_utc=None,
            max_age_seconds=max_age.total_seconds(),
            age_seconds=None,
            is_proof_of_filing=False,
            is_proof_of_nonreceipt=False,
            evidentiary_restrictions=_default_evidentiary_restrictions(
                include_stale=False
            ),
            notes=(
                "Missing public data is a retrieval gap, not proof of nonreceipt.",
            ),
        )

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    anchor = source_as_of_utc or last_ingestion_datetime or retrieval_utc
    anchor_dt = _parse_flexible_utc(anchor) if anchor else None
    age_seconds: float | None = None
    freshness_class = FreshnessClass.UNKNOWN
    notes: list[str] = []

    if partial:
        freshness_class = FreshnessClass.PARTIAL
        notes.append(
            "Partial retrieval; incomplete public history is not proof of nonreceipt."
        )
    elif anchor_dt is not None:
        age_seconds = max(0.0, (current - anchor_dt).total_seconds())
        if age_seconds > max_age.total_seconds():
            freshness_class = FreshnessClass.STALE
            notes.append(
                "Snapshot exceeds max_freshness_age; do not treat as current "
                "status proof. Stale public data is not proof of filing or "
                "nonreceipt."
            )
        else:
            freshness_class = FreshnessClass.FRESH
            notes.append("Snapshot is within the configured freshness bound.")
    else:
        freshness_class = FreshnessClass.UNKNOWN
        notes.append("No source/retrieval anchor available for age calculation.")

    restrictions = _default_evidentiary_restrictions(
        include_stale=freshness_class is FreshnessClass.STALE
    )

    return FreshnessAssessment(
        schema_version=APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
        freshness_class=freshness_class,
        retrieval_utc=retrieval_utc,
        source_as_of_utc=_coerce_source_utc(source_as_of_utc)
        if source_as_of_utc
        else _coerce_source_utc(last_ingestion_datetime),
        max_age_seconds=max_age.total_seconds(),
        age_seconds=age_seconds,
        is_proof_of_filing=False,
        is_proof_of_nonreceipt=False,
        evidentiary_restrictions=restrictions,
        notes=tuple(notes),
    )


def public_access_limitations_dict() -> dict[str, str]:
    """Return the explicit public-access limitation catalog."""

    return {
        lim.value: PUBLIC_ACCESS_LIMITATION_NOTES[lim.value]
        for lim in PUBLIC_ACCESS_LIMITATIONS
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_evidentiary_restrictions(
    *, include_stale: bool
) -> tuple[EvidentiaryRestriction, ...]:
    base = [
        EvidentiaryRestriction.PROOF_OF_FILING,
        EvidentiaryRestriction.PROOF_OF_NONRECEIPT,
        EvidentiaryRestriction.PRIVATE_ACCESS,
        EvidentiaryRestriction.COMPLETE_FILE_WRAPPER,
    ]
    if include_stale:
        base.append(EvidentiaryRestriction.CURRENT_STATUS_WHEN_STALE)
    return tuple(base)


def _status_code_known(code: str) -> bool:
    """Heuristic: numeric USPTO status codes in a common range are 'known'."""

    text = str(code).strip()
    if text.isdigit():
        # USPTO application status codes are small integers; treat common
        # documented-ish range as known without claiming exhaustiveness.
        value = int(text)
        return 0 < value < 1000
    # Non-numeric codes require vocabulary membership.
    return text.upper() in {
        "DOCKETED",
        "PENDING",
        "ABANDONED",
        "ALLOWED",
        "PATENTED",
    }


def _infer_kind_from_text(
    event_code: str | None, event_description: str | None
) -> MatterEventKind:
    blob = " ".join(x for x in (event_code or "", event_description or "") if x).lower()
    if "abandon" in blob:
        return MatterEventKind.ABANDONMENT
    if "allow" in blob:
        return MatterEventKind.ALLOWANCE
    if "grant" in blob or "issue" in blob or "patent" in blob:
        return MatterEventKind.GRANT
    if "appeal" in blob or "ptab" in blob or "bpa" in blob:
        return MatterEventKind.APPEAL
    if "file" in blob and "app" in blob:
        return MatterEventKind.FILING
    if "response" in blob or "amend" in blob or "rce" in blob:
        return MatterEventKind.RESPONSE
    if "document" in blob:
        return MatterEventKind.DOCUMENT
    if "status" in blob:
        return MatterEventKind.STATUS
    return MatterEventKind.TRANSACTION


def _stable_event_id(
    *,
    application_number: str,
    event_code: str | None,
    event_date: str | None,
    index: int,
    raw_event: Mapping[str, Any],
) -> str:
    material = canonical_json(
        {
            "application_number": application_number,
            "event_code": event_code,
            "event_date": event_date,
            "index": index,
            "raw": _json_safe(raw_event),
        }
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    code_part = _ID_SAFE_RE.sub("_", (event_code or "unknown"))[:32]
    return f"tx:{application_number}:{code_part}:{digest}"


def _coerce_source_utc(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    # Date-only → start-of-day UTC.
    m = _DATE_ONLY_RE.match(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T00:00:00Z"
    # Strip trailing timezone forms that are not strict ISO in fixtures.
    # e.g. 2020-08-31T01:20:29.000-0400 → normalize via fromisoformat if possible.
    if _ISO_UTC_RE.match(text):
        return text if text.endswith("Z") or "+" in text[10:] or text[-6] in "+-" else text
    parsed = _parse_flexible_utc(text)
    if parsed is None:
        return None
    return format_utc(parsed)


def _parse_flexible_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    m = _DATE_ONLY_RE.match(text)
    if m:
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            tzinfo=timezone.utc,
        )
    # Normalize Z and compact offsets.
    candidate = text
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    # Convert -0400 → -04:00
    if re.search(r"[+-]\d{4}\Z", candidate):
        candidate = candidate[:-5] + candidate[-5:-2] + ":" + candidate[-2:]
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _stringify_raw(value: Any) -> str:
    if isinstance(value, str):
        return value if len(value) <= 2048 else value[:2045] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return "" if value is None else str(value)
    try:
        text = canonical_json(value)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 2048 else text[:2045] + "..."


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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


def _require_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        # Accept and re-normalize flexible forms.
        parsed = _parse_flexible_utc(text)
        if parsed is None:
            raise ValueError(f"{field} must be an ISO-8601 UTC timestamp")
        return format_utc(parsed)
    return text


def _optional_utc(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    if _ISO_UTC_RE.match(text):
        return text
    parsed = _parse_flexible_utc(text)
    if parsed is None:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp")
    return format_utc(parsed)


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not re.match(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z", text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not re.match(r"\A[0-9a-f]{64}\Z", text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


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
    return tuple(_require_str(item, f"{field}[{i}]", max_len=512) for i, item in enumerate(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")


def _nonneg_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    number = float(value)
    if number < 0 or number != number:  # NaN check
        raise ValueError(f"{field} must be a non-negative finite number")
    return number


__all__ = [
    "APPLICATION_STATUS_PROCESSOR_INTERFACE",
    "APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION",
    "DEFAULT_MAX_FRESHNESS_AGE",
    "PUBLIC_ACCESS_LIMITATIONS",
    "PUBLIC_ACCESS_LIMITATION_NOTES",
    "ApplicationStatusProcessor",
    "ApplicationStatusProcessorError",
    "EvidentiaryRestriction",
    "FreshnessAssessment",
    "FreshnessClass",
    "InMemoryStatusSnapshotStore",
    "NormalizedTransactionEvent",
    "PublicAccessLimitation",
    "StatusSnapshotStore",
    "StatusSyncOutcome",
    "StatusSyncResult",
    "VersionedStatusEventSnapshot",
    "assess_freshness",
    "compute_status_content_digest",
    "normalize_status_from_meta",
    "normalize_transaction_event",
    "public_access_limitations_dict",
]
