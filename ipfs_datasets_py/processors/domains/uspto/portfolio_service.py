"""Authorized tenant-isolated portfolio review service (PATLAW-152 / PATLAW-G171).

Reconciles known application numbers, public ODP state, and user-authorized
Patent Center export facts into a private review model. Distinguishes
application lifecycle from Office Action and claim-level rejection events.

Invariants (fail-closed):

* Public and private versions reconcile without disclosure downgrade — the
  result classification is always the most restrictive of the inputs.
* ``rejected`` is never a terminal lifecycle state; final/non-final/advisory
  rejections live on :class:`RejectionEvent` and
  :class:`~.matter_events.RejectionDisposition` while lifecycle remains
  examination/appeal unless abandon, allow, or grant.
* Delayed or absent upstream records remain ``unknown`` / gap records — never
  proof of nonreceipt or invented status.
* Authorization and tenant isolation expose no record, count, timing, or search
  oracle to an unauthorized caller.
* The service cannot enumerate or scrape a Patent Center account; unpublished
  matters require explicit user-authorized local import grants.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from .contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
    is_private_classification,
    most_restrictive_classification,
    requires_quarantine,
)
from .matter_events import (
    ApplicationLifecyclePhase,
    RejectionDisposition,
    normalize_application_status,
)
from .status_vocabulary import classify_status_code

PORTFOLIO_SERVICE_SCHEMA_VERSION: Final = "uspto.portfolio-service.v1"
PORTFOLIO_SERVICE_INTERFACE: Final = "PatentPortfolioService@1"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_TENANT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\-]{0,127}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Uniform denial code — never distinguishes missing vs unauthorized vs wrong tenant.
ACCESS_DENIED_CODE: Final = "access_denied"
# Fixed synthetic duration for unauthorized responses (no timing oracle).
_UNIFORM_DENIAL_DURATION_MS: Final = 0

FORBIDDEN_PORTFOLIO_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "scrape_authenticated_patent_center",
        "enumerate_patent_center_account",
        "store_credentials_or_cookies",
        "automate_mfa",
        "read_browser_profile_or_session_storage",
        "cross_tenant_portfolio_search",
        "existence_oracle",
        "count_oracle",
        "timing_oracle",
        "search_oracle",
    }
)

# Capabilities that may be granted to a principal for a matter or tenant scope.
CAP_READ_REVIEW: Final = "read_review"
CAP_LIST_PORTFOLIO: Final = "list_portfolio"
CAP_SEARCH: Final = "search"
CAP_INGEST_PUBLIC: Final = "ingest_public"
CAP_INGEST_PRIVATE: Final = "ingest_private"
CAP_GRANT_ACCESS: Final = "grant_access"

_ALL_CAPS: Final[frozenset[str]] = frozenset(
    {
        CAP_READ_REVIEW,
        CAP_LIST_PORTFOLIO,
        CAP_SEARCH,
        CAP_INGEST_PUBLIC,
        CAP_INGEST_PRIVATE,
        CAP_GRANT_ACCESS,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PortfolioServiceError(Exception):
    """Base error for the portfolio review service."""

    def __init__(self, message: str, *, code: str = "portfolio_service_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        # Audit surfaces never include private substance.
        return {"code": self.code, "message": str(self)}


class PortfolioAuthorizationError(PortfolioServiceError):
    """Raised only for programming errors (invalid grant construction).

    Runtime unauthorized access does **not** raise this class with matter
    existence details; callers receive :class:`PortfolioAccessResult` so that
    missing and forbidden look identical.
    """

    def __init__(self, message: str, *, code: str = "portfolio_authorization") -> None:
        super().__init__(message, code=code)


class PortfolioCapabilityError(PortfolioServiceError):
    """Raised when a forbidden capability is requested."""

    def __init__(self, message: str, *, capability: str) -> None:
        super().__init__(message, code="forbidden_capability")
        self.capability = capability

    def audit_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "code": self.code,
            "message": str(self),
        }


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FactSourceChannel(str, Enum):
    """Provenance channel for a portfolio fact."""

    PUBLIC_ODP = "public_odp"
    PRIVATE_IMPORT = "private_import"
    MANUAL = "manual"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class FactPresence(str, Enum):
    """Whether upstream content was observed.

    ``delayed`` / ``absent`` / ``unknown`` are never treated as proof of
    nonreceipt or as terminal abandonment.
    """

    PRESENT = "present"
    DELAYED = "delayed"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class PortfolioFactKind(str, Enum):
    """Semantic kind of a portfolio fact."""

    STATUS = "status"
    REJECTION = "rejection"
    OFFICE_ACTION = "office_action"
    SUBMISSION = "submission"
    RECEIPT = "receipt"
    GAP = "gap"
    REVIEWER_ACTION = "reviewer_action"
    IDENTITY = "identity"
    OTHER = "other"


class ReviewDisposition(str, Enum):
    """Human / system review disposition for a projected fact."""

    NOT_REVIEWED = "not_reviewed"
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"


class AccessOutcome(str, Enum):
    """Uniform access outcome codes."""

    AUTHORIZED = "authorized"
    DENIED = "denied"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _require_tenant(value: Any) -> str:
    text = _require_str(value, "tenant_id", max_len=128)
    if not _TENANT_RE.match(text):
        raise ValueError(f"invalid tenant_id: {value!r}")
    return text


def _optional_utc(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC: {text!r}")
    return text


def _require_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC: {text!r}")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
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


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError(
        f"classification must be DisclosureClassification or str, got {type(value).__name__}"
    )


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


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def content_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def lifecycle_is_terminal(phase: ApplicationLifecyclePhase) -> bool:
    """Return True only for terminal prosecution phases.

    Rejection (final or otherwise) is **not** terminal. Terminal phases are
    abandonment and grant. Allowance is still pre-issuance (fees, etc.).
    """
    return phase in (
        ApplicationLifecyclePhase.ABANDONMENT,
        ApplicationLifecyclePhase.GRANT,
    )


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioPrincipal:
    """Authenticated caller identity bound to exactly one tenant."""

    subject_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(self, "tenant_id", _require_tenant(self.tenant_id))
        object.__setattr__(
            self, "roles", _tuple_of_str(self.roles, "roles", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": list(self.roles),
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioPrincipal":
        value = _mapping(value, "PortfolioPrincipal")
        return cls(
            subject_id=value.get("subject_id", ""),
            tenant_id=value.get("tenant_id", ""),
            roles=tuple(value.get("roles") or ()),
        )


@dataclass(frozen=True, slots=True)
class PortfolioAccessGrant:
    """Explicit authorization for a principal over a matter or tenant scope.

    ``matter_id`` of ``*`` grants tenant-scoped list/search/read for all
    matters that already exist under the same tenant (still no cross-tenant
    visibility). Individual matter grants are preferred for least privilege.
    """

    grant_id: str
    tenant_id: str
    subject_id: str
    matter_id: str
    capabilities: tuple[str, ...]
    issued_utc: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _identifier(self.grant_id, "grant_id"))
        object.__setattr__(self, "tenant_id", _require_tenant(self.tenant_id))
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        mid = _require_str(self.matter_id, "matter_id", max_len=256)
        if mid != "*" and not _ID_RE.match(mid):
            raise ValueError(f"matter_id is not a valid identifier: {mid!r}")
        object.__setattr__(self, "matter_id", mid)
        caps = _tuple_of_str(self.capabilities, "capabilities", max_items=16)
        unknown = sorted(set(caps) - _ALL_CAPS)
        if unknown:
            raise PortfolioAuthorizationError(
                f"unknown grant capabilities: {', '.join(unknown)}",
                code="unknown_capability",
            )
        forbidden = sorted(set(caps) & FORBIDDEN_PORTFOLIO_CAPABILITIES)
        if forbidden:
            raise PortfolioAuthorizationError(
                f"cannot grant forbidden capabilities: {', '.join(forbidden)}",
                code="forbidden_capability",
            )
        object.__setattr__(self, "capabilities", tuple(sorted(set(caps))))
        object.__setattr__(
            self, "issued_utc", _optional_utc(self.issued_utc, "issued_utc")
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "grant_id": self.grant_id,
            "issued_utc": self.issued_utc,
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioAccessGrant":
        value = _mapping(value, "PortfolioAccessGrant")
        return cls(
            grant_id=value.get("grant_id", ""),
            tenant_id=value.get("tenant_id", ""),
            subject_id=value.get("subject_id", ""),
            matter_id=value.get("matter_id", ""),
            capabilities=tuple(value.get("capabilities") or ()),
            issued_utc=value.get("issued_utc"),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class ApplicationLifecycle:
    """Application-level lifecycle projection (not claim rejection state).

    Rejection disposition is retained for display but never sets
    ``is_terminal``. Only abandonment and grant are terminal.
    """

    schema_version: str
    matter_id: str
    phase: ApplicationLifecyclePhase
    rejection_disposition: RejectionDisposition
    is_pending: bool | None
    is_abandoned: bool | None
    is_allowed: bool | None
    is_patented: bool | None
    is_appealed: bool | None
    is_terminal: bool
    status_code: str | None
    status_text: str | None
    classification: DisclosureClassification
    source_channel: FactSourceChannel
    source_event_utc: str | None
    observed_utc: str | None
    presence: FactPresence
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != PORTFOLIO_SERVICE_SCHEMA_VERSION:
            raise ValueError(
                f"ApplicationLifecycle.schema_version must be "
                f"{PORTFOLIO_SERVICE_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "phase", _coerce_enum(ApplicationLifecyclePhase, self.phase, "phase")
        )
        object.__setattr__(
            self,
            "rejection_disposition",
            _coerce_enum(
                RejectionDisposition, self.rejection_disposition, "rejection_disposition"
            ),
        )
        for flag in (
            "is_pending",
            "is_abandoned",
            "is_allowed",
            "is_patented",
            "is_appealed",
            "is_terminal",
        ):
            val = getattr(self, flag)
            if flag == "is_terminal":
                if not isinstance(val, bool):
                    raise TypeError("is_terminal must be bool")
            elif val is not None and not isinstance(val, bool):
                raise TypeError(f"{flag} must be bool or None")
        # Hard invariant: rejection never implies terminal.
        if self.is_terminal and self.phase not in (
            ApplicationLifecyclePhase.ABANDONMENT,
            ApplicationLifecyclePhase.GRANT,
        ):
            raise PortfolioServiceError(
                "is_terminal may only be true for abandonment or grant phases; "
                "rejection is not terminal",
                code="rejection_not_terminal",
            )
        if (
            self.rejection_disposition
            in (
                RejectionDisposition.NONFINAL,
                RejectionDisposition.FINAL,
                RejectionDisposition.ADVISORY,
            )
            and self.is_terminal
        ):
            raise PortfolioServiceError(
                "rejection disposition cannot coexist with is_terminal=True",
                code="rejection_not_terminal",
            )
        object.__setattr__(
            self, "status_code", _optional_str(self.status_code, "status_code", max_len=128)
        )
        object.__setattr__(
            self, "status_text", _optional_str(self.status_text, "status_text", max_len=512)
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "source_channel",
            _coerce_enum(FactSourceChannel, self.source_channel, "source_channel"),
        )
        object.__setattr__(
            self,
            "source_event_utc",
            _optional_utc(self.source_event_utc, "source_event_utc"),
        )
        object.__setattr__(
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(
            self, "presence", _coerce_enum(FactPresence, self.presence, "presence")
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=32))

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "is_abandoned": self.is_abandoned,
            "is_allowed": self.is_allowed,
            "is_appealed": self.is_appealed,
            "is_patented": self.is_patented,
            "is_pending": self.is_pending,
            "is_terminal": self.is_terminal,
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "phase": self.phase.value,
            "presence": self.presence.value,
            "rejection_disposition": self.rejection_disposition.value,
            "schema_version": self.schema_version,
            "source_channel": self.source_channel.value,
            "source_event_utc": self.source_event_utc,
            "status_code": self.status_code,
            "status_text": self.status_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationLifecycle":
        value = _mapping(value, "ApplicationLifecycle")
        return cls(
            schema_version=value.get(
                "schema_version", PORTFOLIO_SERVICE_SCHEMA_VERSION
            ),
            matter_id=value.get("matter_id", ""),
            phase=value.get("phase", ApplicationLifecyclePhase.UNKNOWN.value),
            rejection_disposition=value.get(
                "rejection_disposition", RejectionDisposition.UNKNOWN.value
            ),
            is_pending=value.get("is_pending"),
            is_abandoned=value.get("is_abandoned"),
            is_allowed=value.get("is_allowed"),
            is_patented=value.get("is_patented"),
            is_appealed=value.get("is_appealed"),
            is_terminal=bool(value.get("is_terminal", False)),
            status_code=value.get("status_code"),
            status_text=value.get("status_text"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            source_channel=value.get(
                "source_channel", FactSourceChannel.UNKNOWN.value
            ),
            source_event_utc=value.get("source_event_utc"),
            observed_utc=value.get("observed_utc"),
            presence=value.get("presence", FactPresence.UNKNOWN.value),
            notes=tuple(value.get("notes") or ()),
        )

    @classmethod
    def unknown(cls, matter_id: str) -> "ApplicationLifecycle":
        return cls(
            schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
            matter_id=matter_id,
            phase=ApplicationLifecyclePhase.UNKNOWN,
            rejection_disposition=RejectionDisposition.UNKNOWN,
            is_pending=None,
            is_abandoned=None,
            is_allowed=None,
            is_patented=None,
            is_appealed=None,
            is_terminal=False,
            status_code=None,
            status_text=None,
            classification=DisclosureClassification.UNKNOWN,
            source_channel=FactSourceChannel.UNKNOWN,
            source_event_utc=None,
            observed_utc=None,
            presence=FactPresence.UNKNOWN,
            notes=("no admitted status facts; lifecycle remains unknown",),
        )


@dataclass(frozen=True, slots=True)
class RejectionEvent:
    """Office Action / claim-level rejection event — never a terminal lifecycle.

    Application lifecycle is independent: a final rejection mailed does not
    abandon the matter.
    """

    schema_version: str
    event_id: str
    matter_id: str
    disposition: RejectionDisposition
    claim_numbers: tuple[str, ...]
    office_action_artifact_id: str | None
    source_event_utc: str | None
    observed_utc: str | None
    classification: DisclosureClassification
    source_channel: FactSourceChannel
    review_disposition: ReviewDisposition
    source_receipt_id: str | None
    notes: tuple[str, ...] = ()
    is_terminal: bool = False  # always False; field present for explicit consumers

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != PORTFOLIO_SERVICE_SCHEMA_VERSION:
            raise ValueError(
                f"RejectionEvent.schema_version must be {PORTFOLIO_SERVICE_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(RejectionDisposition, self.disposition, "disposition"),
        )
        if self.disposition is RejectionDisposition.NONE:
            raise PortfolioServiceError(
                "RejectionEvent requires a rejection disposition other than none",
                code="invalid_rejection",
            )
        object.__setattr__(
            self,
            "claim_numbers",
            _tuple_of_str(self.claim_numbers, "claim_numbers", max_items=512),
        )
        object.__setattr__(
            self,
            "office_action_artifact_id",
            _optional_identifier(
                self.office_action_artifact_id, "office_action_artifact_id"
            ),
        )
        object.__setattr__(
            self,
            "source_event_utc",
            _optional_utc(self.source_event_utc, "source_event_utc"),
        )
        object.__setattr__(
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "source_channel",
            _coerce_enum(FactSourceChannel, self.source_channel, "source_channel"),
        )
        object.__setattr__(
            self,
            "review_disposition",
            _coerce_enum(
                ReviewDisposition, self.review_disposition, "review_disposition"
            ),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=32))
        if self.is_terminal:
            raise PortfolioServiceError(
                "RejectionEvent.is_terminal must always be False; rejection is not "
                "a terminal application lifecycle state",
                code="rejection_not_terminal",
            )
        object.__setattr__(self, "is_terminal", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_numbers": list(self.claim_numbers),
            "classification": self.classification.value,
            "disposition": self.disposition.value,
            "event_id": self.event_id,
            "is_terminal": False,
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "office_action_artifact_id": self.office_action_artifact_id,
            "review_disposition": self.review_disposition.value,
            "schema_version": self.schema_version,
            "source_channel": self.source_channel.value,
            "source_event_utc": self.source_event_utc,
            "source_receipt_id": self.source_receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RejectionEvent":
        value = _mapping(value, "RejectionEvent")
        return cls(
            schema_version=value.get(
                "schema_version", PORTFOLIO_SERVICE_SCHEMA_VERSION
            ),
            event_id=value.get("event_id", ""),
            matter_id=value.get("matter_id", ""),
            disposition=value.get("disposition", RejectionDisposition.UNKNOWN.value),
            claim_numbers=tuple(value.get("claim_numbers") or ()),
            office_action_artifact_id=value.get("office_action_artifact_id"),
            source_event_utc=value.get("source_event_utc"),
            observed_utc=value.get("observed_utc"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            source_channel=value.get(
                "source_channel", FactSourceChannel.UNKNOWN.value
            ),
            review_disposition=value.get(
                "review_disposition", ReviewDisposition.NOT_REVIEWED.value
            ),
            source_receipt_id=value.get("source_receipt_id"),
            notes=tuple(value.get("notes") or ()),
            is_terminal=bool(value.get("is_terminal", False)),
        )


@dataclass(frozen=True, slots=True)
class PortfolioFactVersion:
    """One source-channel version of a logical portfolio fact."""

    version_id: str
    channel: FactSourceChannel
    classification: DisclosureClassification
    presence: FactPresence
    content_sha256: str | None
    source_receipt_id: str | None
    source_event_utc: str | None
    observed_utc: str | None
    labels: Mapping[str, str] = MappingProxyType({})
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "version_id", _identifier(self.version_id, "version_id")
        )
        object.__setattr__(
            self, "channel", _coerce_enum(FactSourceChannel, self.channel, "channel")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "presence", _coerce_enum(FactPresence, self.presence, "presence")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self,
            "source_event_utc",
            _optional_utc(self.source_event_utc, "source_event_utc"),
        )
        object.__setattr__(
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel.value,
            "classification": self.classification.value,
            "content_sha256": self.content_sha256,
            "labels": dict(self.labels),
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "presence": self.presence.value,
            "source_event_utc": self.source_event_utc,
            "source_receipt_id": self.source_receipt_id,
            "version_id": self.version_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioFactVersion":
        value = _mapping(value, "PortfolioFactVersion")
        return cls(
            version_id=value.get("version_id", ""),
            channel=value.get("channel", FactSourceChannel.UNKNOWN.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            presence=value.get("presence", FactPresence.UNKNOWN.value),
            content_sha256=value.get("content_sha256"),
            source_receipt_id=value.get("source_receipt_id"),
            source_event_utc=value.get("source_event_utc"),
            observed_utc=value.get("observed_utc"),
            labels=value.get("labels") or {},
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class ReconciledFact:
    """Public/private fact versions reconciled without disclosure downgrade."""

    logical_id: str
    kind: PortfolioFactKind
    classification: DisclosureClassification
    versions: tuple[PortfolioFactVersion, ...]
    presence: FactPresence
    downgrade_prevented: bool
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "logical_id", _identifier(self.logical_id, "logical_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(PortfolioFactKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.versions, tuple):
            object.__setattr__(self, "versions", tuple(self.versions))
        for v in self.versions:
            if not isinstance(v, PortfolioFactVersion):
                raise TypeError("versions items must be PortfolioFactVersion")
        # Fail closed: result classification must be at least as restrictive as
        # every version (no disclosure downgrade).
        if self.versions:
            expected = most_restrictive_classification(
                v.classification for v in self.versions
            )
            if self.classification is not expected:
                raise PortfolioServiceError(
                    "reconciled classification must equal most_restrictive of "
                    "versions (disclosure downgrade forbidden)",
                    code="disclosure_downgrade",
                )
        object.__setattr__(
            self, "presence", _coerce_enum(FactPresence, self.presence, "presence")
        )
        if not isinstance(self.downgrade_prevented, bool):
            raise TypeError("downgrade_prevented must be bool")
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "downgrade_prevented": self.downgrade_prevented,
            "kind": self.kind.value,
            "logical_id": self.logical_id,
            "notes": list(self.notes),
            "presence": self.presence.value,
            "versions": [v.to_dict() for v in self.versions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconciledFact":
        value = _mapping(value, "ReconciledFact")
        return cls(
            logical_id=value.get("logical_id", ""),
            kind=value.get("kind", PortfolioFactKind.OTHER.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            versions=tuple(
                PortfolioFactVersion.from_dict(v)
                for v in (value.get("versions") or ())
            ),
            presence=value.get("presence", FactPresence.UNKNOWN.value),
            downgrade_prevented=bool(value.get("downgrade_prevented", True)),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class GapView:
    """Gap / delayed / absent projection — never proof of nonreceipt."""

    gap_id: str
    matter_id: str
    code: str
    presence: FactPresence
    is_proof_of_nonreceipt: bool
    interpretation: str
    message: str
    observed_utc: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(self, "code", _require_str(self.code, "code", max_len=128))
        object.__setattr__(
            self, "presence", _coerce_enum(FactPresence, self.presence, "presence")
        )
        if not isinstance(self.is_proof_of_nonreceipt, bool):
            raise TypeError("is_proof_of_nonreceipt must be bool")
        if self.is_proof_of_nonreceipt:
            raise PortfolioServiceError(
                "gap views must never assert proof of nonreceipt",
                code="gap_nonreceipt_forbidden",
            )
        object.__setattr__(
            self,
            "interpretation",
            _require_str(self.interpretation, "interpretation", max_len=128),
        )
        object.__setattr__(
            self, "message", _require_str(self.message, "message", max_len=1024)
        )
        object.__setattr__(
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "gap_id": self.gap_id,
            "interpretation": self.interpretation,
            "is_proof_of_nonreceipt": False,
            "matter_id": self.matter_id,
            "message": self.message,
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "presence": self.presence.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GapView":
        value = _mapping(value, "GapView")
        return cls(
            gap_id=value.get("gap_id", ""),
            matter_id=value.get("matter_id", ""),
            code=value.get("code", "unknown"),
            presence=value.get("presence", FactPresence.UNKNOWN.value),
            is_proof_of_nonreceipt=bool(value.get("is_proof_of_nonreceipt", False)),
            interpretation=value.get("interpretation", "freshness_gap"),
            message=value.get("message", "gap"),
            observed_utc=value.get("observed_utc"),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class SubmissionView:
    """Submission fact projected for review."""

    submission_id: str
    matter_id: str
    classification: DisclosureClassification
    source_channel: FactSourceChannel
    artifact_id: str | None
    source_event_utc: str | None
    observed_utc: str | None
    presence: FactPresence
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "submission_id", _identifier(self.submission_id, "submission_id")
        )
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "source_channel",
            _coerce_enum(FactSourceChannel, self.source_channel, "source_channel"),
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "source_event_utc",
            _optional_utc(self.source_event_utc, "source_event_utc"),
        )
        object.__setattr__(
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(
            self, "presence", _coerce_enum(FactPresence, self.presence, "presence")
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "presence": self.presence.value,
            "source_channel": self.source_channel.value,
            "source_event_utc": self.source_event_utc,
            "submission_id": self.submission_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionView":
        value = _mapping(value, "SubmissionView")
        return cls(
            submission_id=value.get("submission_id", ""),
            matter_id=value.get("matter_id", ""),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            source_channel=value.get(
                "source_channel", FactSourceChannel.UNKNOWN.value
            ),
            artifact_id=value.get("artifact_id"),
            source_event_utc=value.get("source_event_utc"),
            observed_utc=value.get("observed_utc"),
            presence=value.get("presence", FactPresence.UNKNOWN.value),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class ReceiptView:
    """Acknowledgement / payment receipt projection."""

    receipt_id: str
    matter_id: str
    kind: str
    classification: DisclosureClassification
    source_channel: FactSourceChannel
    artifact_id: str | None
    source_event_utc: str | None
    observed_utc: str | None
    presence: FactPresence
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(self, "kind", _require_str(self.kind, "kind", max_len=64))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "source_channel",
            _coerce_enum(FactSourceChannel, self.source_channel, "source_channel"),
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "source_event_utc",
            _optional_utc(self.source_event_utc, "source_event_utc"),
        )
        object.__setattr__(
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(
            self, "presence", _coerce_enum(FactPresence, self.presence, "presence")
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "kind": self.kind,
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "presence": self.presence.value,
            "receipt_id": self.receipt_id,
            "source_channel": self.source_channel.value,
            "source_event_utc": self.source_event_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReceiptView":
        value = _mapping(value, "ReceiptView")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            matter_id=value.get("matter_id", ""),
            kind=value.get("kind", "acknowledgement"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            source_channel=value.get(
                "source_channel", FactSourceChannel.UNKNOWN.value
            ),
            artifact_id=value.get("artifact_id"),
            source_event_utc=value.get("source_event_utc"),
            observed_utc=value.get("observed_utc"),
            presence=value.get("presence", FactPresence.UNKNOWN.value),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class ReviewerActionView:
    """Reviewer action projection (human-controlled next steps)."""

    action_id: str
    matter_id: str
    action_code: str
    review_state: ReviewState
    classification: DisclosureClassification
    observed_utc: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "action_code", _require_str(self.action_code, "action_code", max_len=128)
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
            self, "observed_utc", _optional_utc(self.observed_utc, "observed_utc")
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=16))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_code": self.action_code,
            "action_id": self.action_id,
            "classification": self.classification.value,
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "observed_utc": self.observed_utc,
            "review_state": self.review_state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewerActionView":
        value = _mapping(value, "ReviewerActionView")
        return cls(
            action_id=value.get("action_id", ""),
            matter_id=value.get("matter_id", ""),
            action_code=value.get("action_code", "unknown"),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            observed_utc=value.get("observed_utc"),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class MatterReviewProjection:
    """Tenant-scoped matter summary for authorized portfolio review."""

    schema_version: str
    tenant_id: str
    matter_id: str
    application_number: str | None
    classification: DisclosureClassification
    lifecycle: ApplicationLifecycle
    rejections: tuple[RejectionEvent, ...]
    office_actions: tuple[dict[str, Any], ...]
    submissions: tuple[SubmissionView, ...]
    receipts: tuple[ReceiptView, ...]
    gaps: tuple[GapView, ...]
    reviewer_actions: tuple[ReviewerActionView, ...]
    reconciled_facts: tuple[ReconciledFact, ...]
    review_state: ReviewState
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != PORTFOLIO_SERVICE_SCHEMA_VERSION:
            raise ValueError(
                f"MatterReviewProjection.schema_version must be "
                f"{PORTFOLIO_SERVICE_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "tenant_id", _require_tenant(self.tenant_id))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, "application_number", max_len=64),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if not isinstance(self.lifecycle, ApplicationLifecycle):
            raise TypeError("lifecycle must be ApplicationLifecycle")
        if not isinstance(self.rejections, tuple):
            object.__setattr__(self, "rejections", tuple(self.rejections))
        if not isinstance(self.office_actions, tuple):
            object.__setattr__(self, "office_actions", tuple(self.office_actions))
        if not isinstance(self.submissions, tuple):
            object.__setattr__(self, "submissions", tuple(self.submissions))
        if not isinstance(self.receipts, tuple):
            object.__setattr__(self, "receipts", tuple(self.receipts))
        if not isinstance(self.gaps, tuple):
            object.__setattr__(self, "gaps", tuple(self.gaps))
        if not isinstance(self.reviewer_actions, tuple):
            object.__setattr__(self, "reviewer_actions", tuple(self.reviewer_actions))
        if not isinstance(self.reconciled_facts, tuple):
            object.__setattr__(self, "reconciled_facts", tuple(self.reconciled_facts))
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=32))
        # Invariant: no rejection is terminal.
        for rej in self.rejections:
            if rej.is_terminal:
                raise PortfolioServiceError(
                    "rejection events must not be terminal",
                    code="rejection_not_terminal",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "classification": self.classification.value,
            "gaps": [g.to_dict() for g in self.gaps],
            "lifecycle": self.lifecycle.to_dict(),
            "matter_id": self.matter_id,
            "notes": list(self.notes),
            "office_actions": [dict(oa) for oa in self.office_actions],
            "receipts": [r.to_dict() for r in self.receipts],
            "reconciled_facts": [f.to_dict() for f in self.reconciled_facts],
            "rejections": [r.to_dict() for r in self.rejections],
            "review_state": self.review_state.value,
            "reviewer_actions": [a.to_dict() for a in self.reviewer_actions],
            "schema_version": self.schema_version,
            "submissions": [s.to_dict() for s in self.submissions],
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatterReviewProjection":
        value = _mapping(value, "MatterReviewProjection")
        return cls(
            schema_version=value.get(
                "schema_version", PORTFOLIO_SERVICE_SCHEMA_VERSION
            ),
            tenant_id=value.get("tenant_id", ""),
            matter_id=value.get("matter_id", ""),
            application_number=value.get("application_number"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            lifecycle=ApplicationLifecycle.from_dict(value.get("lifecycle") or {}),
            rejections=tuple(
                RejectionEvent.from_dict(r) for r in (value.get("rejections") or ())
            ),
            office_actions=tuple(value.get("office_actions") or ()),
            submissions=tuple(
                SubmissionView.from_dict(s) for s in (value.get("submissions") or ())
            ),
            receipts=tuple(
                ReceiptView.from_dict(r) for r in (value.get("receipts") or ())
            ),
            gaps=tuple(GapView.from_dict(g) for g in (value.get("gaps") or ())),
            reviewer_actions=tuple(
                ReviewerActionView.from_dict(a)
                for a in (value.get("reviewer_actions") or ())
            ),
            reconciled_facts=tuple(
                ReconciledFact.from_dict(f)
                for f in (value.get("reconciled_facts") or ())
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class PortfolioAccessResult:
    """Uniform access result — authorized body or denial without oracles.

    Unauthorized and not-found produce the same ``outcome``, ``code``, and
    timing fields so callers cannot distinguish existence.
    """

    outcome: AccessOutcome
    code: str
    authorized: bool
    duration_ms: int
    # Only populated when authorized=True; always None on denial.
    projection: MatterReviewProjection | None = None
    matter_ids: tuple[str, ...] | None = None
    total_count: int | None = None
    search_hits: tuple[str, ...] | None = None
    audit: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "outcome", _coerce_enum(AccessOutcome, self.outcome, "outcome")
        )
        object.__setattr__(self, "code", _require_str(self.code, "code", max_len=64))
        if not isinstance(self.authorized, bool):
            raise TypeError("authorized must be bool")
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool):
            raise TypeError("duration_ms must be int")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")
        if not self.authorized:
            # Hard oracle prevention: no body fields on denial.
            if self.projection is not None:
                raise PortfolioServiceError(
                    "denial must not carry projection", code="oracle_leak"
                )
            if self.matter_ids is not None:
                raise PortfolioServiceError(
                    "denial must not carry matter_ids", code="oracle_leak"
                )
            if self.total_count is not None:
                raise PortfolioServiceError(
                    "denial must not carry total_count", code="oracle_leak"
                )
            if self.search_hits is not None:
                raise PortfolioServiceError(
                    "denial must not carry search_hits", code="oracle_leak"
                )
            if self.duration_ms != _UNIFORM_DENIAL_DURATION_MS:
                raise PortfolioServiceError(
                    "denial duration_ms must be uniform", code="timing_oracle"
                )
            if self.code != ACCESS_DENIED_CODE:
                raise PortfolioServiceError(
                    "denial code must be uniform access_denied", code="oracle_leak"
                )
            if self.outcome is not AccessOutcome.DENIED:
                raise PortfolioServiceError(
                    "unauthorized outcome must be denied", code="oracle_leak"
                )
        object.__setattr__(
            self, "audit", _frozen_str_map(self.audit, "audit", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit": dict(self.audit),
            "authorized": self.authorized,
            "code": self.code,
            "duration_ms": self.duration_ms,
            "matter_ids": None if self.matter_ids is None else list(self.matter_ids),
            "outcome": self.outcome.value,
            "projection": None if self.projection is None else self.projection.to_dict(),
            "search_hits": None if self.search_hits is None else list(self.search_hits),
            "total_count": self.total_count,
        }

    @classmethod
    def denied(cls, *, audit: Mapping[str, str] | None = None) -> "PortfolioAccessResult":
        """Build a uniform denial (no existence / count / timing oracle)."""
        safe_audit = {
            k: v
            for k, v in dict(audit or {}).items()
            if k
            in (
                "operation",
                "reason",
                "principal_tenant",
                # never include matter_id existence flags
            )
        }
        return cls(
            outcome=AccessOutcome.DENIED,
            code=ACCESS_DENIED_CODE,
            authorized=False,
            duration_ms=_UNIFORM_DENIAL_DURATION_MS,
            projection=None,
            matter_ids=None,
            total_count=None,
            search_hits=None,
            audit=safe_audit,
        )


# ---------------------------------------------------------------------------
# Internal matter state
# ---------------------------------------------------------------------------


@dataclass
class _MatterState:
    tenant_id: str
    matter_id: str
    application_number: str | None
    # logical_id -> channel -> version payload
    status_versions: dict[str, dict[str, PortfolioFactVersion]]
    status_payloads: dict[str, dict[str, Mapping[str, Any]]]
    rejections: dict[str, RejectionEvent]
    office_actions: dict[str, dict[str, Any]]
    submissions: dict[str, SubmissionView]
    receipts: dict[str, ReceiptView]
    gaps: dict[str, GapView]
    reviewer_actions: dict[str, ReviewerActionView]
    classification_hints: list[DisclosureClassification]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PatentPortfolioService:
    """Authorized tenant-isolated portfolio review service.

    Access is limited to known public identifiers and explicit user-authorized
    local import grants. The service never scrapes Patent Center, stores
    credentials, or exposes private matter existence across tenants.
    """

    schema_version: str = PORTFOLIO_SERVICE_SCHEMA_VERSION
    interface: str = PORTFOLIO_SERVICE_INTERFACE

    def __init__(
        self,
        *,
        wall_clock: Callable[[], str] | None = None,
        mono_clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = wall_clock or (lambda: "1970-01-01T00:00:00Z")
        # mono_clock is accepted for tests but unauthorized paths never report
        # measured durations (timing oracle prevention).
        self._mono = mono_clock or time.monotonic
        self._lock = threading.RLock()
        # tenant_id -> matter_id -> state
        self._matters: dict[str, dict[str, _MatterState]] = {}
        # (tenant_id, subject_id) -> list of grants
        self._grants: dict[tuple[str, str], list[PortfolioAccessGrant]] = {}
        # Operators (tenant-scoped bootstrap principals that may grant access)
        self._operators: set[tuple[str, str]] = set()

    # -- capability surface --------------------------------------------------

    def assert_capability_allowed(self, capability: str) -> None:
        cap = str(capability or "").strip()
        if cap in FORBIDDEN_PORTFOLIO_CAPABILITIES or cap not in _ALL_CAPS:
            raise PortfolioCapabilityError(
                f"capability not allowed: {cap!r}",
                capability=cap or "empty",
            )

    # -- authorization administration ----------------------------------------

    def register_operator(self, principal: PortfolioPrincipal) -> None:
        """Register a tenant operator allowed to issue grants for that tenant."""
        p = (
            principal
            if isinstance(principal, PortfolioPrincipal)
            else PortfolioPrincipal.from_dict(principal)  # type: ignore[arg-type]
        )
        with self._lock:
            self._operators.add((p.tenant_id, p.subject_id))

    def grant_access(
        self,
        operator: PortfolioPrincipal,
        grant: PortfolioAccessGrant | Mapping[str, Any],
    ) -> PortfolioAccessGrant:
        """Issue an access grant. Operator must match grant.tenant_id."""
        op = (
            operator
            if isinstance(operator, PortfolioPrincipal)
            else PortfolioPrincipal.from_dict(operator)  # type: ignore[arg-type]
        )
        g = (
            grant
            if isinstance(grant, PortfolioAccessGrant)
            else PortfolioAccessGrant.from_dict(grant)
        )
        if op.tenant_id != g.tenant_id:
            # Cross-tenant grant attempt — fail closed without leaking matter.
            raise PortfolioAuthorizationError(
                "operator tenant does not match grant tenant",
                code="tenant_mismatch",
            )
        with self._lock:
            if (op.tenant_id, op.subject_id) not in self._operators:
                raise PortfolioAuthorizationError(
                    "principal is not a registered operator for this tenant",
                    code="not_operator",
                )
            key = (g.tenant_id, g.subject_id)
            existing = self._grants.setdefault(key, [])
            # Replace same grant_id idempotently.
            self._grants[key] = [x for x in existing if x.grant_id != g.grant_id] + [g]
        return g

    def _has_capability(
        self,
        principal: PortfolioPrincipal,
        *,
        capability: str,
        matter_id: str | None = None,
    ) -> bool:
        key = (principal.tenant_id, principal.subject_id)
        grants = self._grants.get(key, ())
        for g in grants:
            if g.tenant_id != principal.tenant_id:
                continue
            if capability not in g.capabilities:
                continue
            if g.matter_id == "*":
                return True
            if matter_id is not None and g.matter_id == matter_id:
                return True
        return False

    # -- ingest (authorized write paths) -------------------------------------

    def ingest_public_odp_status(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        application_number: str | None = None,
        status_code: str | None = None,
        status_text: str | None = None,
        source_event_utc: str | None = None,
        observed_utc: str | None = None,
        source_receipt_id: str | None = None,
        presence: FactPresence | str = FactPresence.PRESENT,
        classification: DisclosureClassification | str = (
            DisclosureClassification.PUBLIC_OFFICIAL
        ),
        raw_fields: Mapping[str, str] | None = None,
        notes: Sequence[str] = (),
    ) -> PortfolioAccessResult:
        """Ingest a public ODP status fact for a known application number."""
        if not self._has_capability(
            principal, capability=CAP_INGEST_PUBLIC, matter_id=matter_id
        ) and not self._has_capability(
            principal, capability=CAP_INGEST_PUBLIC, matter_id=None
        ):
            # Wildcard check: need grant with matter_id * or exact matter.
            if not self._has_capability(
                principal, capability=CAP_INGEST_PUBLIC, matter_id=matter_id
            ):
                return PortfolioAccessResult.denied(
                    audit={
                        "operation": "ingest_public_odp_status",
                        "principal_tenant": principal.tenant_id,
                        "reason": "unauthorized",
                    }
                )
        mid = _identifier(matter_id, "matter_id")
        cls = _coerce_classification(classification)
        if is_private_classification(cls):
            raise PortfolioServiceError(
                "public ODP ingest refuses private classifications",
                code="public_channel_private_class",
            )
        presence_e = _coerce_enum(FactPresence, presence, "presence")
        observed = _optional_utc(observed_utc, "observed_utc") or self._clock()
        source_evt = _optional_utc(source_event_utc, "source_event_utc")

        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id,
                matter_id=mid,
                application_number=application_number,
            )
            if application_number:
                state.application_number = _optional_str(
                    application_number, "application_number", max_len=64
                )
            logical_id = "status:current"
            version_id = f"status:public:{content_digest({'c': status_code, 't': status_text, 'p': presence_e.value})[:16]}"
            payload = {
                "status_code": status_code,
                "status_text": status_text,
                "raw_fields": dict(raw_fields or {}),
                "notes": list(notes),
            }
            version = PortfolioFactVersion(
                version_id=version_id,
                channel=FactSourceChannel.PUBLIC_ODP,
                classification=cls,
                presence=presence_e,  # type: ignore[arg-type]
                content_sha256=content_digest(payload),
                source_receipt_id=_optional_identifier(
                    source_receipt_id, "source_receipt_id"
                ),
                source_event_utc=source_evt,
                observed_utc=observed,
                labels={"logical_id": logical_id},
                notes=tuple(notes),
            )
            state.status_versions.setdefault(logical_id, {})[
                FactSourceChannel.PUBLIC_ODP.value
            ] = version
            state.status_payloads.setdefault(logical_id, {})[
                FactSourceChannel.PUBLIC_ODP.value
            ] = MappingProxyType(payload)
            state.classification_hints.append(cls)

            # Delayed / absent → record gap, leave lifecycle unknown if no present.
            if presence_e is not FactPresence.PRESENT:
                gap = GapView(
                    gap_id=f"gap:status:{presence_e.value}:{mid}",
                    matter_id=mid,
                    code=(
                        "delayed_publication"
                        if presence_e is FactPresence.DELAYED
                        else "status_retrieval_gap"
                        if presence_e is FactPresence.ABSENT
                        else "status_unknown"
                    ),
                    presence=presence_e,  # type: ignore[arg-type]
                    is_proof_of_nonreceipt=False,
                    interpretation=(
                        "freshness_gap"
                        if presence_e is FactPresence.DELAYED
                        else "retrieval_gap"
                    ),
                    message=(
                        "upstream status record is delayed or absent; lifecycle "
                        "remains unknown and is not treated as abandonment"
                    ),
                    observed_utc=observed,
                    notes=("delayed/absent upstream records remain unknown",),
                )
                state.gaps[gap.gap_id] = gap

        return self.get_review(principal, matter_id=mid)

    def ingest_private_export_status(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        application_number: str | None = None,
        status_code: str | None = None,
        status_text: str | None = None,
        source_event_utc: str | None = None,
        observed_utc: str | None = None,
        source_receipt_id: str | None = None,
        presence: FactPresence | str = FactPresence.PRESENT,
        classification: DisclosureClassification | str = (
            DisclosureClassification.CONFIDENTIAL_APPLICATION
        ),
        raw_fields: Mapping[str, str] | None = None,
        notes: Sequence[str] = (),
    ) -> PortfolioAccessResult:
        """Ingest status from a user-authorized local Patent Center export."""
        if not self._has_capability(
            principal, capability=CAP_INGEST_PRIVATE, matter_id=matter_id
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "ingest_private_export_status",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        mid = _identifier(matter_id, "matter_id")
        cls = _coerce_classification(classification)
        if requires_quarantine(cls):
            # Unknown classification still admits as unknown presence.
            presence = FactPresence.UNKNOWN
            notes = tuple(notes) + ("unknown classification quarantined for review",)
        if cls is DisclosureClassification.PUBLIC_OFFICIAL:
            # Private import channel must not re-label as pure public without
            # also recording private provenance — force at least confidential.
            cls = DisclosureClassification.CONFIDENTIAL_APPLICATION
        presence_e = _coerce_enum(FactPresence, presence, "presence")
        observed = _optional_utc(observed_utc, "observed_utc") or self._clock()
        source_evt = _optional_utc(source_event_utc, "source_event_utc")

        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id,
                matter_id=mid,
                application_number=application_number,
            )
            if application_number:
                state.application_number = _optional_str(
                    application_number, "application_number", max_len=64
                )
            logical_id = "status:current"
            version_id = f"status:private:{content_digest({'c': status_code, 't': status_text, 'p': presence_e.value})[:16]}"
            payload = {
                "status_code": status_code,
                "status_text": status_text,
                "raw_fields": dict(raw_fields or {}),
                "notes": list(notes),
            }
            version = PortfolioFactVersion(
                version_id=version_id,
                channel=FactSourceChannel.PRIVATE_IMPORT,
                classification=cls,
                presence=presence_e,  # type: ignore[arg-type]
                content_sha256=content_digest(payload),
                source_receipt_id=_optional_identifier(
                    source_receipt_id, "source_receipt_id"
                ),
                source_event_utc=source_evt,
                observed_utc=observed,
                labels={"logical_id": logical_id},
                notes=tuple(notes),
            )
            state.status_versions.setdefault(logical_id, {})[
                FactSourceChannel.PRIVATE_IMPORT.value
            ] = version
            state.status_payloads.setdefault(logical_id, {})[
                FactSourceChannel.PRIVATE_IMPORT.value
            ] = MappingProxyType(payload)
            state.classification_hints.append(cls)

            if presence_e is not FactPresence.PRESENT:
                gap = GapView(
                    gap_id=f"gap:private-status:{presence_e.value}:{mid}",
                    matter_id=mid,
                    code="private_status_gap",
                    presence=presence_e,  # type: ignore[arg-type]
                    is_proof_of_nonreceipt=False,
                    interpretation="retrieval_gap",
                    message=(
                        "authorized private export status is delayed or absent; "
                        "state remains unknown"
                    ),
                    observed_utc=observed,
                )
                state.gaps[gap.gap_id] = gap

        return self.get_review(principal, matter_id=mid)

    def ingest_rejection_event(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        event_id: str,
        disposition: RejectionDisposition | str,
        claim_numbers: Sequence[str] = (),
        office_action_artifact_id: str | None = None,
        source_event_utc: str | None = None,
        observed_utc: str | None = None,
        classification: DisclosureClassification | str = (
            DisclosureClassification.PUBLIC_OFFICIAL
        ),
        source_channel: FactSourceChannel | str = FactSourceChannel.PUBLIC_ODP,
        source_receipt_id: str | None = None,
        notes: Sequence[str] = (),
        private: bool = False,
    ) -> PortfolioAccessResult:
        """Ingest a claim/OA rejection event (never marks lifecycle terminal)."""
        cap = CAP_INGEST_PRIVATE if private else CAP_INGEST_PUBLIC
        if not self._has_capability(principal, capability=cap, matter_id=matter_id):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "ingest_rejection_event",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        mid = _identifier(matter_id, "matter_id")
        channel = _coerce_enum(FactSourceChannel, source_channel, "source_channel")
        if private:
            channel = FactSourceChannel.PRIVATE_IMPORT
        cls = _coerce_classification(classification)
        if private and not is_private_classification(cls):
            cls = DisclosureClassification.CONFIDENTIAL_APPLICATION
        event = RejectionEvent(
            schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
            event_id=event_id,
            matter_id=mid,
            disposition=disposition,  # type: ignore[arg-type]
            claim_numbers=tuple(claim_numbers),
            office_action_artifact_id=office_action_artifact_id,
            source_event_utc=source_event_utc,
            observed_utc=observed_utc or self._clock(),
            classification=cls,
            source_channel=channel,  # type: ignore[arg-type]
            review_disposition=ReviewDisposition.NOT_REVIEWED,
            source_receipt_id=source_receipt_id,
            notes=tuple(notes)
            + ("rejection is not a terminal application lifecycle state",),
            is_terminal=False,
        )
        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id, matter_id=mid, application_number=None
            )
            state.rejections[event.event_id] = event
            state.classification_hints.append(cls)
            if office_action_artifact_id:
                state.office_actions[office_action_artifact_id] = {
                    "artifact_id": office_action_artifact_id,
                    "matter_id": mid,
                    "kind": "office_action",
                    "linked_rejection_event_id": event.event_id,
                    "classification": cls.value,
                    "source_channel": channel.value,
                }
        return self.get_review(principal, matter_id=mid)

    def ingest_submission(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        submission_id: str,
        classification: DisclosureClassification | str,
        source_channel: FactSourceChannel | str = FactSourceChannel.PRIVATE_IMPORT,
        artifact_id: str | None = None,
        source_event_utc: str | None = None,
        observed_utc: str | None = None,
        presence: FactPresence | str = FactPresence.PRESENT,
        notes: Sequence[str] = (),
    ) -> PortfolioAccessResult:
        if not self._has_capability(
            principal, capability=CAP_INGEST_PRIVATE, matter_id=matter_id
        ) and not self._has_capability(
            principal, capability=CAP_INGEST_PUBLIC, matter_id=matter_id
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "ingest_submission",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        mid = _identifier(matter_id, "matter_id")
        view = SubmissionView(
            submission_id=submission_id,
            matter_id=mid,
            classification=classification,  # type: ignore[arg-type]
            source_channel=source_channel,  # type: ignore[arg-type]
            artifact_id=artifact_id,
            source_event_utc=source_event_utc,
            observed_utc=observed_utc or self._clock(),
            presence=presence,  # type: ignore[arg-type]
            notes=tuple(notes),
        )
        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id, matter_id=mid, application_number=None
            )
            state.submissions[view.submission_id] = view
            state.classification_hints.append(view.classification)
        return self.get_review(principal, matter_id=mid)

    def ingest_receipt(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        receipt_id: str,
        kind: str = "acknowledgement",
        classification: DisclosureClassification | str = (
            DisclosureClassification.CONFIDENTIAL_APPLICATION
        ),
        source_channel: FactSourceChannel | str = FactSourceChannel.PRIVATE_IMPORT,
        artifact_id: str | None = None,
        source_event_utc: str | None = None,
        observed_utc: str | None = None,
        presence: FactPresence | str = FactPresence.PRESENT,
        notes: Sequence[str] = (),
    ) -> PortfolioAccessResult:
        if not self._has_capability(
            principal, capability=CAP_INGEST_PRIVATE, matter_id=matter_id
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "ingest_receipt",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        mid = _identifier(matter_id, "matter_id")
        view = ReceiptView(
            receipt_id=receipt_id,
            matter_id=mid,
            kind=kind,
            classification=classification,  # type: ignore[arg-type]
            source_channel=source_channel,  # type: ignore[arg-type]
            artifact_id=artifact_id,
            source_event_utc=source_event_utc,
            observed_utc=observed_utc or self._clock(),
            presence=presence,  # type: ignore[arg-type]
            notes=tuple(notes),
        )
        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id, matter_id=mid, application_number=None
            )
            state.receipts[view.receipt_id] = view
            state.classification_hints.append(view.classification)
        return self.get_review(principal, matter_id=mid)

    def ingest_reviewer_action(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        action_id: str,
        action_code: str,
        review_state: ReviewState | str = ReviewState.REQUIRED,
        classification: DisclosureClassification | str = (
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT
        ),
        notes: Sequence[str] = (),
    ) -> PortfolioAccessResult:
        if not self._has_capability(
            principal, capability=CAP_INGEST_PRIVATE, matter_id=matter_id
        ) and not self._has_capability(
            principal, capability=CAP_READ_REVIEW, matter_id=matter_id
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "ingest_reviewer_action",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        mid = _identifier(matter_id, "matter_id")
        view = ReviewerActionView(
            action_id=action_id,
            matter_id=mid,
            action_code=action_code,
            review_state=review_state,  # type: ignore[arg-type]
            classification=classification,  # type: ignore[arg-type]
            observed_utc=self._clock(),
            notes=tuple(notes),
        )
        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id, matter_id=mid, application_number=None
            )
            state.reviewer_actions[view.action_id] = view
            state.classification_hints.append(view.classification)
        return self.get_review(principal, matter_id=mid)

    def record_delayed_or_absent(
        self,
        principal: PortfolioPrincipal,
        *,
        matter_id: str,
        gap_id: str,
        code: str,
        presence: FactPresence | str,
        message: str,
        interpretation: str = "freshness_gap",
    ) -> PortfolioAccessResult:
        """Record a delayed/absent upstream record without inventing status."""
        if not self._has_capability(
            principal, capability=CAP_INGEST_PUBLIC, matter_id=matter_id
        ) and not self._has_capability(
            principal, capability=CAP_INGEST_PRIVATE, matter_id=matter_id
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "record_delayed_or_absent",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        mid = _identifier(matter_id, "matter_id")
        presence_e = _coerce_enum(FactPresence, presence, "presence")
        if presence_e is FactPresence.PRESENT:
            raise PortfolioServiceError(
                "record_delayed_or_absent requires non-present presence",
                code="invalid_presence",
            )
        gap = GapView(
            gap_id=gap_id,
            matter_id=mid,
            code=code,
            presence=presence_e,  # type: ignore[arg-type]
            is_proof_of_nonreceipt=False,
            interpretation=interpretation,
            message=message,
            observed_utc=self._clock(),
            notes=("delayed or absent upstream records remain unknown",),
        )
        with self._lock:
            state = self._ensure_matter(
                tenant_id=principal.tenant_id, matter_id=mid, application_number=None
            )
            state.gaps[gap.gap_id] = gap
        return self.get_review(principal, matter_id=mid)

    # -- authorized read surfaces --------------------------------------------

    def get_review(
        self, principal: PortfolioPrincipal, *, matter_id: str
    ) -> PortfolioAccessResult:
        """Return a matter review projection or a uniform denial.

        Unauthorized callers (wrong tenant, missing grant, unknown matter)
        always receive the same denial shape — no existence oracle.
        """
        mid = _identifier(matter_id, "matter_id")
        if not self._has_capability(principal, capability=CAP_READ_REVIEW, matter_id=mid):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "get_review",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        with self._lock:
            tenant_matters = self._matters.get(principal.tenant_id, {})
            state = tenant_matters.get(mid)
            if state is None:
                # Authorized for the matter key but no facts yet — still no
                # cross-tenant leak; return unknown projection for empty matter
                # only when grant covers it.
                projection = self._empty_projection(
                    tenant_id=principal.tenant_id, matter_id=mid
                )
            else:
                projection = self._project(state)
        return PortfolioAccessResult(
            outcome=AccessOutcome.AUTHORIZED,
            code="ok",
            authorized=True,
            duration_ms=_UNIFORM_DENIAL_DURATION_MS,
            projection=projection,
            audit={
                "operation": "get_review",
                "principal_tenant": principal.tenant_id,
                "reason": "authorized",
            },
        )

    def list_portfolio(self, principal: PortfolioPrincipal) -> PortfolioAccessResult:
        """List matter ids the principal may read. Unauthorized → uniform denial.

        Note: denial does not include ``matter_ids`` or ``total_count``. An
        authorized but empty portfolio returns ``matter_ids=()`` and
        ``total_count=0``.
        """
        if not self._has_capability(
            principal, capability=CAP_LIST_PORTFOLIO, matter_id=None
        ) and not self._has_capability(
            principal, capability=CAP_LIST_PORTFOLIO, matter_id="*"
        ):
            # Also allow if any list grant exists (matter-scoped).
            if not self._any_capability(principal, CAP_LIST_PORTFOLIO):
                return PortfolioAccessResult.denied(
                    audit={
                        "operation": "list_portfolio",
                        "principal_tenant": principal.tenant_id,
                        "reason": "unauthorized",
                    }
                )
        with self._lock:
            tenant_matters = self._matters.get(principal.tenant_id, {})
            allowed: list[str] = []
            for mid in sorted(tenant_matters.keys()):
                if self._has_capability(
                    principal, capability=CAP_LIST_PORTFOLIO, matter_id=mid
                ) or self._has_capability(
                    principal, capability=CAP_READ_REVIEW, matter_id=mid
                ):
                    allowed.append(mid)
            # Matter-scoped list grants for not-yet-ingested matters:
            for g in self._grants.get((principal.tenant_id, principal.subject_id), ()):
                if CAP_LIST_PORTFOLIO in g.capabilities and g.matter_id != "*":
                    if g.matter_id not in allowed and g.matter_id in tenant_matters:
                        allowed.append(g.matter_id)
            allowed_sorted = tuple(sorted(set(allowed)))
        return PortfolioAccessResult(
            outcome=AccessOutcome.AUTHORIZED,
            code="ok",
            authorized=True,
            duration_ms=_UNIFORM_DENIAL_DURATION_MS,
            matter_ids=allowed_sorted,
            total_count=len(allowed_sorted),
            audit={
                "operation": "list_portfolio",
                "principal_tenant": principal.tenant_id,
                "reason": "authorized",
            },
        )

    def search_portfolio(
        self,
        principal: PortfolioPrincipal,
        *,
        query: str,
    ) -> PortfolioAccessResult:
        """Search authorized matters only. Unauthorized → uniform denial.

        Search never returns hits outside the principal's grants and never
        reports total corpus size to unauthorized callers.
        """
        if not self._any_capability(principal, CAP_SEARCH) and not self._any_capability(
            principal, CAP_LIST_PORTFOLIO
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "search_portfolio",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        q = str(query or "").strip().lower()
        with self._lock:
            tenant_matters = self._matters.get(principal.tenant_id, {})
            hits: list[str] = []
            for mid, state in tenant_matters.items():
                if not (
                    self._has_capability(principal, capability=CAP_SEARCH, matter_id=mid)
                    or self._has_capability(
                        principal, capability=CAP_READ_REVIEW, matter_id=mid
                    )
                    or self._has_capability(
                        principal, capability=CAP_LIST_PORTFOLIO, matter_id=mid
                    )
                ):
                    continue
                hay = " ".join(
                    x
                    for x in (
                        mid,
                        state.application_number or "",
                    )
                    if x
                ).lower()
                if not q or q in hay:
                    hits.append(mid)
            hits_t = tuple(sorted(hits))
        return PortfolioAccessResult(
            outcome=AccessOutcome.AUTHORIZED,
            code="ok",
            authorized=True,
            duration_ms=_UNIFORM_DENIAL_DURATION_MS,
            search_hits=hits_t,
            total_count=len(hits_t),
            audit={
                "operation": "search_portfolio",
                "principal_tenant": principal.tenant_id,
                "reason": "authorized",
            },
        )

    def count_portfolio(self, principal: PortfolioPrincipal) -> PortfolioAccessResult:
        """Return authorized matter count, or uniform denial without a count."""
        if not self._any_capability(principal, CAP_LIST_PORTFOLIO) and not self._any_capability(
            principal, CAP_READ_REVIEW
        ):
            return PortfolioAccessResult.denied(
                audit={
                    "operation": "count_portfolio",
                    "principal_tenant": principal.tenant_id,
                    "reason": "unauthorized",
                }
            )
        listed = self.list_portfolio(principal)
        if not listed.authorized:
            return listed
        return PortfolioAccessResult(
            outcome=AccessOutcome.AUTHORIZED,
            code="ok",
            authorized=True,
            duration_ms=_UNIFORM_DENIAL_DURATION_MS,
            total_count=listed.total_count,
            audit={
                "operation": "count_portfolio",
                "principal_tenant": principal.tenant_id,
                "reason": "authorized",
            },
        )

    # -- reconciliation core -------------------------------------------------

    def reconcile_public_private_versions(
        self,
        versions: Sequence[PortfolioFactVersion],
        *,
        logical_id: str,
        kind: PortfolioFactKind | str = PortfolioFactKind.STATUS,
    ) -> ReconciledFact:
        """Reconcile multi-channel versions without disclosure downgrade.

        The result classification is always
        :func:`most_restrictive_classification` of the inputs. If a private
        version is present, the result cannot be pure public.
        """
        vers = tuple(versions)
        if not vers:
            return ReconciledFact(
                logical_id=logical_id,
                kind=kind,  # type: ignore[arg-type]
                classification=DisclosureClassification.UNKNOWN,
                versions=(),
                presence=FactPresence.UNKNOWN,
                downgrade_prevented=True,
                notes=("no versions to reconcile; presence unknown",),
            )
        result_cls = most_restrictive_classification(v.classification for v in vers)
        # Presence: if any present, present; else if any delayed, delayed;
        # else if any absent, absent; else unknown. Never invent present.
        presences = {v.presence for v in vers}
        if FactPresence.PRESENT in presences:
            presence = FactPresence.PRESENT
        elif FactPresence.DELAYED in presences:
            presence = FactPresence.DELAYED
        elif FactPresence.ABSENT in presences:
            presence = FactPresence.ABSENT
        else:
            presence = FactPresence.UNKNOWN

        notes: list[str] = ["public/private versions reconciled without disclosure downgrade"]
        private_present = any(
            is_private_classification(v.classification) for v in vers
        )
        public_present = any(
            v.classification
            in (
                DisclosureClassification.PUBLIC_OFFICIAL,
                DisclosureClassification.PUBLIC_USER,
            )
            for v in vers
        )
        if private_present and public_present:
            notes.append(
                "private classification retained over public; no disclosure downgrade"
            )
        if private_present and result_cls not in (
            DisclosureClassification.CONFIDENTIAL_APPLICATION,
            DisclosureClassification.PRIVILEGED_WORK_PRODUCT,
            DisclosureClassification.RESTRICTED_EXPORT_REVIEW,
            DisclosureClassification.CREDENTIAL_OR_PAYMENT,
            DisclosureClassification.UNKNOWN,
        ):
            raise PortfolioServiceError(
                "private version cannot reconcile to public classification",
                code="disclosure_downgrade",
            )

        return ReconciledFact(
            logical_id=logical_id,
            kind=kind,  # type: ignore[arg-type]
            classification=result_cls,
            versions=tuple(sorted(vers, key=lambda v: (v.channel.value, v.version_id))),
            presence=presence,
            downgrade_prevented=True,
            notes=tuple(notes),
        )

    # -- internals -----------------------------------------------------------

    def _any_capability(self, principal: PortfolioPrincipal, capability: str) -> bool:
        key = (principal.tenant_id, principal.subject_id)
        for g in self._grants.get(key, ()):
            if g.tenant_id == principal.tenant_id and capability in g.capabilities:
                return True
        return False

    def _ensure_matter(
        self,
        *,
        tenant_id: str,
        matter_id: str,
        application_number: str | None,
    ) -> _MatterState:
        tenant = _require_tenant(tenant_id)
        mid = _identifier(matter_id, "matter_id")
        bucket = self._matters.setdefault(tenant, {})
        state = bucket.get(mid)
        if state is None:
            state = _MatterState(
                tenant_id=tenant,
                matter_id=mid,
                application_number=_optional_str(
                    application_number, "application_number", max_len=64
                ),
                status_versions={},
                status_payloads={},
                rejections={},
                office_actions={},
                submissions={},
                receipts={},
                gaps={},
                reviewer_actions={},
                classification_hints=[],
            )
            bucket[mid] = state
        return state

    def _empty_projection(
        self, *, tenant_id: str, matter_id: str
    ) -> MatterReviewProjection:
        return MatterReviewProjection(
            schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
            tenant_id=tenant_id,
            matter_id=matter_id,
            application_number=None,
            classification=DisclosureClassification.UNKNOWN,
            lifecycle=ApplicationLifecycle.unknown(matter_id),
            rejections=(),
            office_actions=(),
            submissions=(),
            receipts=(),
            gaps=(),
            reviewer_actions=(),
            reconciled_facts=(),
            review_state=ReviewState.PENDING,
            notes=("no admitted facts for matter; all axes unknown",),
        )

    def _project(self, state: _MatterState) -> MatterReviewProjection:
        reconciled: list[ReconciledFact] = []
        lifecycle = ApplicationLifecycle.unknown(state.matter_id)

        for logical_id, by_channel in sorted(state.status_versions.items()):
            versions = tuple(by_channel.values())
            fact = self.reconcile_public_private_versions(
                versions, logical_id=logical_id, kind=PortfolioFactKind.STATUS
            )
            reconciled.append(fact)
            if fact.presence is FactPresence.PRESENT:
                # Prefer private payload when present, else public — but
                # classification remains most restrictive.
                payload = None
                preferred_channel = None
                if FactSourceChannel.PRIVATE_IMPORT.value in state.status_payloads.get(
                    logical_id, {}
                ):
                    payload = state.status_payloads[logical_id][
                        FactSourceChannel.PRIVATE_IMPORT.value
                    ]
                    preferred_channel = FactSourceChannel.PRIVATE_IMPORT
                elif FactSourceChannel.PUBLIC_ODP.value in state.status_payloads.get(
                    logical_id, {}
                ):
                    payload = state.status_payloads[logical_id][
                        FactSourceChannel.PUBLIC_ODP.value
                    ]
                    preferred_channel = FactSourceChannel.PUBLIC_ODP
                if payload is not None and preferred_channel is not None:
                    lifecycle = self._lifecycle_from_payload(
                        matter_id=state.matter_id,
                        payload=payload,
                        classification=fact.classification,
                        channel=preferred_channel,
                        versions=versions,
                    )
            else:
                # Delayed/absent/unknown: keep lifecycle unknown.
                lifecycle = ApplicationLifecycle(
                    schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
                    matter_id=state.matter_id,
                    phase=ApplicationLifecyclePhase.UNKNOWN,
                    rejection_disposition=RejectionDisposition.UNKNOWN,
                    is_pending=None,
                    is_abandoned=None,
                    is_allowed=None,
                    is_patented=None,
                    is_appealed=None,
                    is_terminal=False,
                    status_code=None,
                    status_text=None,
                    classification=fact.classification,
                    source_channel=FactSourceChannel.UNKNOWN,
                    source_event_utc=None,
                    observed_utc=None,
                    presence=fact.presence,
                    notes=(
                        "status presence is not present; lifecycle remains unknown",
                        "delayed or absent upstream records are not terminal",
                    ),
                )

        rejections = tuple(
            sorted(state.rejections.values(), key=lambda r: r.event_id)
        )
        # If we have rejection events but lifecycle still examination-like,
        # ensure is_terminal stays false even for final rejections.
        if rejections and lifecycle.phase is ApplicationLifecyclePhase.UNKNOWN:
            # Infer examination from rejection history without terminalizing.
            has_final = any(
                r.disposition is RejectionDisposition.FINAL for r in rejections
            )
            has_nonfinal = any(
                r.disposition is RejectionDisposition.NONFINAL for r in rejections
            )
            disp = (
                RejectionDisposition.FINAL
                if has_final
                else RejectionDisposition.NONFINAL
                if has_nonfinal
                else rejections[0].disposition
            )
            lifecycle = ApplicationLifecycle(
                schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
                matter_id=state.matter_id,
                phase=ApplicationLifecyclePhase.EXAMINATION,
                rejection_disposition=disp,
                is_pending=True,
                is_abandoned=False,
                is_allowed=False,
                is_patented=False,
                is_appealed=False,
                is_terminal=False,
                status_code=None,
                status_text=None,
                classification=most_restrictive_classification(
                    [lifecycle.classification]
                    + [r.classification for r in rejections]
                ),
                source_channel=rejections[0].source_channel,
                source_event_utc=rejections[0].source_event_utc,
                observed_utc=rejections[0].observed_utc,
                presence=FactPresence.PRESENT,
                notes=(
                    "lifecycle inferred from rejection events; rejection is not terminal",
                ),
            )

        overall_cls = most_restrictive_classification(
            list(state.classification_hints)
            + [lifecycle.classification]
            + [r.classification for r in rejections]
            + [s.classification for s in state.submissions.values()]
            + [r.classification for r in state.receipts.values()]
            + [a.classification for a in state.reviewer_actions.values()]
            or [DisclosureClassification.UNKNOWN]
        )

        review_state = ReviewState.PENDING
        if state.reviewer_actions:
            # Prefer the most severe review state among actions.
            states = {a.review_state for a in state.reviewer_actions.values()}
            if ReviewState.REQUIRED in states:
                review_state = ReviewState.REQUIRED
            elif ReviewState.PENDING in states:
                review_state = ReviewState.PENDING
            elif ReviewState.COMPLETE in states:
                review_state = ReviewState.COMPLETE

        notes: list[str] = []
        if any(r.disposition is RejectionDisposition.FINAL for r in rejections):
            notes.append(
                "final rejection present; application lifecycle is not terminal"
            )
        if state.gaps:
            notes.append(
                f"{len(state.gaps)} gap(s) retained (not proof of nonreceipt)"
            )
        if any(f.downgrade_prevented for f in reconciled):
            notes.append("reconciled facts preserve most restrictive classification")

        return MatterReviewProjection(
            schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
            tenant_id=state.tenant_id,
            matter_id=state.matter_id,
            application_number=state.application_number,
            classification=overall_cls,
            lifecycle=lifecycle,
            rejections=rejections,
            office_actions=tuple(
                state.office_actions[k] for k in sorted(state.office_actions)
            ),
            submissions=tuple(
                state.submissions[k] for k in sorted(state.submissions)
            ),
            receipts=tuple(state.receipts[k] for k in sorted(state.receipts)),
            gaps=tuple(state.gaps[k] for k in sorted(state.gaps)),
            reviewer_actions=tuple(
                state.reviewer_actions[k] for k in sorted(state.reviewer_actions)
            ),
            reconciled_facts=tuple(reconciled),
            review_state=review_state,
            notes=tuple(notes),
        )

    def _lifecycle_from_payload(
        self,
        *,
        matter_id: str,
        payload: Mapping[str, Any],
        classification: DisclosureClassification,
        channel: FactSourceChannel,
        versions: Sequence[PortfolioFactVersion],
    ) -> ApplicationLifecycle:
        status_code = payload.get("status_code")
        status_text = payload.get("status_text")
        raw_fields = payload.get("raw_fields") or {}
        # Prefer protected vocabulary when known.
        vocab = classify_status_code(status_code if status_code else status_text)
        snap = normalize_application_status(
            status_code=str(status_code) if status_code is not None else None,
            status_text=str(status_text) if status_text is not None else None,
            lifecycle_phase=(
                vocab.entry.lifecycle_phase if vocab.entry is not None else None
            ),
            rejection_disposition=(
                vocab.entry.rejection_disposition if vocab.entry is not None else None
            ),
            is_pending=vocab.entry.is_pending if vocab.entry is not None else None,
            is_abandoned=vocab.entry.is_abandoned if vocab.entry is not None else None,
            is_allowed=vocab.entry.is_allowed if vocab.entry is not None else None,
            is_patented=vocab.entry.is_patented if vocab.entry is not None else None,
            is_appealed=vocab.entry.is_appealed if vocab.entry is not None else None,
            raw_fields={str(k): str(v) for k, v in dict(raw_fields).items()},
            infer=vocab.entry is None,
        )
        phase = snap.lifecycle_phase
        terminal = lifecycle_is_terminal(phase)
        # Explicit: even final rejection disposition does not terminalize.
        if snap.rejection_disposition in (
            RejectionDisposition.FINAL,
            RejectionDisposition.NONFINAL,
            RejectionDisposition.ADVISORY,
        ):
            terminal = False
            if phase is ApplicationLifecyclePhase.UNKNOWN:
                phase = ApplicationLifecyclePhase.EXAMINATION
            if snap.is_pending is None and not (
                snap.is_abandoned or snap.is_patented
            ):
                snap_pending = True
            else:
                snap_pending = snap.is_pending
        else:
            snap_pending = snap.is_pending

        # Observed times from versions.
        source_evt = next(
            (v.source_event_utc for v in versions if v.source_event_utc), None
        )
        observed = next((v.observed_utc for v in versions if v.observed_utc), None)

        notes = list(snap.notes)
        if snap.rejection_disposition is RejectionDisposition.FINAL:
            notes.append("final rejection is not a terminal lifecycle state")
        if vocab.recognition.value != "known":
            notes.append(
                f"status recognition={vocab.recognition.value}; unknown codes stay unknown"
            )

        return ApplicationLifecycle(
            schema_version=PORTFOLIO_SERVICE_SCHEMA_VERSION,
            matter_id=matter_id,
            phase=phase,
            rejection_disposition=snap.rejection_disposition,
            is_pending=snap_pending,
            is_abandoned=snap.is_abandoned,
            is_allowed=snap.is_allowed,
            is_patented=snap.is_patented,
            is_appealed=snap.is_appealed,
            is_terminal=terminal,
            status_code=snap.status_code,
            status_text=snap.status_text,
            classification=classification,
            source_channel=channel,
            source_event_utc=source_evt,
            observed_utc=observed,
            presence=FactPresence.PRESENT,
            notes=tuple(notes),
        )


__all__ = [
    "ACCESS_DENIED_CODE",
    "CAP_GRANT_ACCESS",
    "CAP_INGEST_PRIVATE",
    "CAP_INGEST_PUBLIC",
    "CAP_LIST_PORTFOLIO",
    "CAP_READ_REVIEW",
    "CAP_SEARCH",
    "FORBIDDEN_PORTFOLIO_CAPABILITIES",
    "PORTFOLIO_SERVICE_INTERFACE",
    "PORTFOLIO_SERVICE_SCHEMA_VERSION",
    "AccessOutcome",
    "ApplicationLifecycle",
    "FactPresence",
    "FactSourceChannel",
    "GapView",
    "MatterReviewProjection",
    "PatentPortfolioService",
    "PortfolioAccessGrant",
    "PortfolioAccessResult",
    "PortfolioAuthorizationError",
    "PortfolioCapabilityError",
    "PortfolioFactKind",
    "PortfolioFactVersion",
    "PortfolioPrincipal",
    "PortfolioServiceError",
    "ReceiptView",
    "ReconciledFact",
    "RejectionEvent",
    "ReviewDisposition",
    "ReviewerActionView",
    "SubmissionView",
    "content_digest",
    "lifecycle_is_terminal",
]
